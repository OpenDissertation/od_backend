"""Download supported institutional dissertation PDFs to local storage."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from bs4.element import Tag
    from playwright.sync_api import Page, Response

DOWNLOAD_DIRECTORY = Path("/tmp")  # noqa: S108 - downloads are explicitly required in container /tmp.
MINIMUM_PDF_BYTES = 1000
HTTP_RETRIES = 3
PRINCETON_BASE_URL = "https://dataspace.princeton.edu"
PRINCETON_FULLTEXT_SEARCH_URL = "{base}/simple-search?query={query}&rpp=500"
UNSW_BASE_URL = "https://unsworks.unsw.edu.au"
UNSW_API_BASE = f"{UNSW_BASE_URL}/server/api"
UNSW_THESIS_COLLECTION_UUID = "5ddb1166-7466-4b4a-8b36-8fb9863464e0"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
PRINCETON_LOCALE = "en-US"
PRINCETON_TIMEZONE = "America/New_York"
PRINCETON_VIEWPORT = {"width": 1366, "height": 768}
PRINCETON_VERIFICATION_TIMEOUT_MS = 20_000
PRINCETON_VERIFICATION_DETAIL = (
    "Princeton DataSpace security verification did not complete before this "
    "request timed out. Retry from an allowed network"
)
SUPPORTED_INSTITUTIONS = {
    "princeton university": "princeton",
    "university of new south wales": "unsw",
    "unsw": "unsw",
}


class DissertationQuery(BaseModel):
    """Request entry for one dissertation author and institution."""

    model_config = ConfigDict(frozen=True)

    author: str = Field(min_length=1)
    institution: str = Field(min_length=1)


class DownloadDissertationsRequest(BaseModel):
    """Request body for downloading dissertations from supported institutions."""

    model_config = ConfigDict(frozen=True)

    dissertations: list[DissertationQuery] = Field(min_length=1)


class DownloadedDissertation(BaseModel):
    """Details for a downloaded dissertation or a skipped/failed query."""

    model_config = ConfigDict(frozen=True)

    author: str
    institution: str
    status: Literal["downloaded", "not_found", "failed"]
    file_path: str | None = None
    title: str | None = None
    source_url: str | None = None
    detail: str | None = None


def normalize_institution(institution: str) -> str:
    """Return the supported-institution key for a user supplied name."""
    normalized = re.sub(r"\s+", " ", institution.casefold()).strip()
    try:
        return SUPPORTED_INSTITUTIONS[normalized]
    except KeyError as err:
        msg = (
            "Unsupported institution. Supported institutions are Princeton "
            "University and University of New South Wales."
        )
        raise ValueError(msg) from err


def safe_pdf_path(author: str, institution_key: str, title: str | None) -> Path:
    """Build a deterministic, filesystem-safe /tmp PDF path."""
    name_source = title or author or "dissertation"
    safe_author = (
        re.sub(r"[^\w\-\s,]", "", author).strip().replace(" ", "_").replace(",", "")
    )
    safe_title = re.sub(r"[^\w\-\s]", "", name_source)[:80].strip().replace(" ", "_")
    filename = f"od_{institution_key}_{safe_author}_{safe_title}.pdf"
    return DOWNLOAD_DIRECTORY / filename


def author_surname(author: str) -> str:
    """Extract a surname-like token for loose repository result validation."""
    if "," in author:
        return author.split(",", maxsplit=1)[0].strip().casefold()
    return author.rsplit(maxsplit=1)[-1].strip().casefold()


def author_matches(author: str, repository_authors: list[str]) -> bool:
    """Return whether any repository author looks like the requested author."""
    if not repository_authors:
        return False
    requested = author.casefold().replace(",", " ")
    requested_parts = {part for part in re.split(r"\s+", requested) if part}
    surname = author_surname(author)
    allow_surname_only = len(requested_parts) == 1 and surname in requested_parts
    for repo_author in repository_authors:
        repo = repo_author.casefold().replace(",", " ")
        repo_parts = {part for part in re.split(r"\s+", repo) if part}
        if requested_parts and requested_parts.issubset(repo_parts):
            return True
        if allow_surname_only and surname and surname in repo_parts:
            return True
    return False


def build_princeton_search_url(author: str) -> str:
    """Build the Princeton DataSpace full-text search URL."""
    return PRINCETON_FULLTEXT_SEARCH_URL.format(
        base=PRINCETON_BASE_URL,
        query=quote(author),
    )


def is_princeton_verification_page(url: str, html: str) -> bool:
    """Return whether Princeton DataSpace is showing its verification gate."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
    return url.rstrip("/").endswith("/verify") or title == (
        "security verification required"
    )


def wait_for_princeton_verification(page: Page) -> None:
    """Allow Princeton DataSpace's browser verification page to finish."""
    if not is_princeton_verification_page(page.url, page.content()):
        return
    try:
        page.wait_for_function(
            """() => (
                !window.location.pathname.endsWith('/verify')
                && document.title.trim().toLowerCase() !== 'security verification required'
            )""",
            timeout=PRINCETON_VERIFICATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError as err:
        raise RuntimeError(PRINCETON_VERIFICATION_DETAIL) from err
    page.wait_for_load_state("networkidle", timeout=30_000)
    if is_princeton_verification_page(page.url, page.content()):
        raise RuntimeError(PRINCETON_VERIFICATION_DETAIL)


def get_princeton_item_metadata(page: Page, item_url: str) -> dict[str, Any]:
    """Load a Princeton DataSpace item page and extract dissertation metadata."""
    page.goto(item_url, wait_until="networkidle", timeout=30_000)
    wait_for_princeton_verification(page)
    soup = BeautifulSoup(page.content(), "html.parser")

    def meta(name: str) -> list[str]:
        return [
            cast("str", tag.get("content", "")).strip()
            for tag in soup.find_all("meta", attrs={"name": name})
            if tag.get("content")
        ]

    title = meta("citation_title")
    authors = meta("citation_author")
    date = meta("citation_date") or meta("citation_publication_date")
    dc_type_tags = meta("DC.type") + meta("dc.type") + meta("DCTERMS.type")
    material_type = dc_type_tags[0] if dc_type_tags else None
    is_thesis = bool(
        meta("citation_dissertation_institution")
        or meta("citation_dissertation_name")
        or any(
            keyword in " ".join(dc_type_tags).casefold()
            for keyword in ("thesis", "dissertation")
        )
    )
    pdf_url = None
    bitstream_link = soup.find("a", href=re.compile(r"/bitstream/"))
    if bitstream_link:
        pdf_url = urljoin(item_url, cast("str", bitstream_link["href"]))
    elif pdf_urls := meta("citation_pdf_url"):
        pdf_url = pdf_urls[0]
    if soup.find(string=re.compile(r"request a copy", re.IGNORECASE)):
        pdf_url = None
    return {
        "url": item_url,
        "title": title[0] if title else None,
        "authors": authors,
        "date": date[0] if date else None,
        "pdf_url": pdf_url,
        "is_thesis": is_thesis,
        "material_type": material_type,
    }


def download_princeton_pdf(
    page: Page, pdf_url: str, dest_path: Path, referer: str
) -> None:
    """Download a Princeton PDF through Playwright browser navigation."""
    response_holder: dict[str, Response] = {}

    def capture_response(resp: Response) -> None:
        if pdf_url in (resp.url, resp.request.url):
            response_holder["response"] = resp

    page.on("response", capture_response)
    try:
        try:
            with page.expect_download(timeout=15_000) as download_info:
                try:
                    page.goto(pdf_url, referer=referer, timeout=60_000)
                except PlaywrightError:
                    logger.debug("Princeton PDF navigation interrupted by download")
            download_info.value.save_as(dest_path)
        except PlaywrightTimeoutError as err:
            response = response_holder.get("response")
            if response is None or not response.ok:
                msg = f"Failed to load Princeton PDF: {pdf_url}"
                raise RuntimeError(msg) from err
            dest_path.write_bytes(response.body())
    finally:
        page.remove_listener("response", capture_response)
    validate_pdf(dest_path)


def find_princeton_results_table(soup: BeautifulSoup) -> Tag | None:
    """Find the Princeton DataSpace table containing actual search results."""
    return next(
        (
            table
            for table in soup.find_all("table")
            if all(
                label in table.get_text(" ", strip=True)
                for label in ("Issue Date", "Title", "Author")
            )
        ),
        None,
    )


def load_princeton_search_results(
    page: Page, author: str
) -> tuple[BeautifulSoup, Tag | None]:
    """Load Princeton search results, retrying once for flaky empty pages."""
    search_url = build_princeton_search_url(author)
    for attempt in range(2):
        page.goto(search_url, wait_until="networkidle", timeout=30_000)
        wait_for_princeton_verification(page)
        soup = BeautifulSoup(page.content(), "html.parser")
        results_table = find_princeton_results_table(soup)
        page_text = soup.get_text(" ", strip=True)
        no_results = bool(
            re.search(r"no items? (were )?found|no results", page_text, re.IGNORECASE)
        )
        if results_table is not None or no_results or attempt == 1:
            return soup, results_table
        page.wait_for_timeout(2_000)
    msg = "Princeton search results could not be loaded"
    raise RuntimeError(msg)


def download_princeton_dissertation(author: str) -> DownloadedDissertation:
    """Search Princeton DataSpace and download the first matching PhD dissertation."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            accept_downloads=True,
            locale=PRINCETON_LOCALE,
            timezone_id=PRINCETON_TIMEZONE,
            viewport=PRINCETON_VIEWPORT,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        try:
            _soup, results_table = load_princeton_search_results(page, author)
            if results_table is None:
                return DownloadedDissertation(
                    author=author,
                    institution="Princeton University",
                    status="not_found",
                    detail="No Princeton search results found for author",
                )
            seen: set[str] = set()
            for link in results_table.find_all("a", href=True):
                href = cast("str", link["href"])
                if not re.search(r"/handle/88435/dsp0\w+$", href):
                    continue
                item_url = urljoin(PRINCETON_BASE_URL, href)
                if item_url in seen:
                    continue
                seen.add(item_url)
                item = get_princeton_item_metadata(page, item_url)
                material_type = (item["material_type"] or "").casefold()
                if not item["is_thesis"] or not (
                    "ph.d" in material_type or "phd" in material_type
                ):
                    continue
                if not author_matches(author, item["authors"]):
                    continue
                if not item["pdf_url"]:
                    continue
                dest_path = safe_pdf_path(author, "princeton", item["title"])
                download_princeton_pdf(page, item["pdf_url"], dest_path, item_url)
                return DownloadedDissertation(
                    author=author,
                    institution="Princeton University",
                    status="downloaded",
                    file_path=str(dest_path),
                    title=item["title"],
                    source_url=item_url,
                )
        finally:
            browser.close()
    return DownloadedDissertation(
        author=author,
        institution="Princeton University",
        status="not_found",
        detail="No downloadable Princeton PhD dissertation found for author.",
    )


def httpx_get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, str | int] | None = None,
) -> httpx.Response:
    """GET with retries for transient repository/network errors."""
    last_err: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            response = client.get(url, params=params, timeout=60.0)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as err:
            last_err = err
            if attempt < HTTP_RETRIES:
                time.sleep(2 * attempt)
        else:
            return response
    if last_err is None:
        msg = f"GET failed without an exception: {url}"
        raise RuntimeError(msg)
    raise last_err


def extract_unsw_metadata(
    metadata: dict[str, list[dict[str, Any]]], keywords: tuple[str, ...]
) -> list[str]:
    """Extract DSpace metadata values whose key contains one of the keywords."""
    values: list[str] = []
    for key, entries in metadata.items():
        if any(keyword in key.casefold() for keyword in keywords):
            values.extend(
                str(entry["value"]) for entry in entries if entry.get("value")
            )
    return values


def find_unsw_pdf(client: httpx.Client, uuid: str) -> tuple[str | None, str | None]:
    """Find a downloadable ORIGINAL PDF bitstream for a UNSW thesis item."""
    bundles = (
        httpx_get_with_retry(client, f"{UNSW_API_BASE}/core/items/{uuid}/bundles")
        .json()
        .get("_embedded", {})
        .get("bundles", [])
    )
    for bundle in bundles:
        if bundle.get("name") != "ORIGINAL":
            continue
        bitstreams_url = (
            bundle.get("_links", {}).get("bitstreams", {}).get("href")
            or f"{UNSW_API_BASE}/core/bundles/{bundle.get('uuid')}/bitstreams"
        )
        bitstreams = (
            httpx_get_with_retry(client, bitstreams_url)
            .json()
            .get("_embedded", {})
            .get("bitstreams", [])
        )
        for bitstream in bitstreams:
            filename = bitstream.get("name", "")
            if filename.casefold().endswith(".pdf"):
                return (
                    f"{UNSW_BASE_URL}/bitstreams/{bitstream.get('uuid')}/download",
                    filename,
                )
    return None, None


def validate_pdf(path: Path) -> None:
    """Reject empty or non-PDF-looking downloads."""
    if path.stat().st_size < MINIMUM_PDF_BYTES or not path.read_bytes().startswith(
        b"%PDF"
    ):
        msg = f"Downloaded file does not look like a PDF: {path}"
        raise RuntimeError(msg)


def download_unsw_dissertation(author: str) -> DownloadedDissertation:
    """Search UNSWorks and download the first matching dissertation PDF."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{UNSW_BASE_URL}/",
    }
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        search_response = httpx_get_with_retry(
            client,
            f"{UNSW_API_BASE}/discover/search/objects",
            params={
                "query": author,
                "dsoType": "item",
                "size": 100,
                "scope": UNSW_THESIS_COLLECTION_UUID,
            },
        )
        objects = (
            search_response.json()
            .get("_embedded", {})
            .get("searchResult", {})
            .get("_embedded", {})
            .get("objects", [])
        )
        for obj in objects:
            candidate = obj.get("_embedded", {}).get("indexableObject", {})
            uuid = candidate.get("uuid")
            if not uuid:
                continue
            item = httpx_get_with_retry(
                client, f"{UNSW_API_BASE}/core/items/{uuid}"
            ).json()
            metadata = item.get("metadata", {})
            authors = extract_unsw_metadata(metadata, ("contributor.author", "creator"))
            if not author_matches(author, authors):
                continue
            title_values = extract_unsw_metadata(metadata, ("title",))
            pdf_url, _filename = find_unsw_pdf(client, uuid)
            if not pdf_url:
                continue
            title = title_values[0] if title_values else item.get("name")
            dest_path = safe_pdf_path(author, "unsw", title)
            with client.stream("GET", pdf_url, timeout=60.0) as response:
                response.raise_for_status()
                with dest_path.open("wb") as file_obj:
                    for chunk in response.iter_bytes():
                        file_obj.write(chunk)
            validate_pdf(dest_path)
            return DownloadedDissertation(
                author=author,
                institution="University of New South Wales",
                status="downloaded",
                file_path=str(dest_path),
                title=title,
                source_url=f"{UNSW_BASE_URL}/entities/publication/{uuid}",
            )
    return DownloadedDissertation(
        author=author,
        institution="University of New South Wales",
        status="not_found",
        detail="No downloadable UNSW dissertation found for author.",
    )


def download_dissertation(query: DissertationQuery) -> DownloadedDissertation:
    """Download one dissertation for one author from a supported institution."""
    institution_key = normalize_institution(query.institution)
    try:
        if institution_key == "princeton":
            return download_princeton_dissertation(query.author)
        return download_unsw_dissertation(query.author)
    except Exception as err:
        logger.exception("Failed to download dissertation for %s", query.author)
        return DownloadedDissertation(
            author=query.author,
            institution=query.institution,
            status="failed",
            detail=str(err),
        )
