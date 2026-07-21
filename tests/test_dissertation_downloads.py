from pathlib import Path

import pytest
from fastapi import HTTPException

from od_backend.dissertation_downloads import (
    DissertationQuery,
    author_matches,
    normalize_institution,
    safe_pdf_path,
)
from od_backend.main import download_dissertations


def test_normalize_supported_institutions() -> None:
    assert normalize_institution("Princeton University") == "princeton"
    assert normalize_institution(" University of New South Wales ") == "unsw"
    assert normalize_institution("UNSW") == "unsw"


def test_normalize_unsupported_institution() -> None:
    with pytest.raises(ValueError, match="Unsupported institution"):
        normalize_institution("University of Sydney")


def test_author_matches_accepts_comma_and_surname_forms() -> None:
    assert author_matches("Doe, Jane", ["Jane Alice Doe"])
    assert author_matches("Doe Jane", ["Doe, Jane"])
    assert not author_matches("Smith, Jane", ["Jane Doe"])


def test_safe_pdf_path_uses_tmp_directory() -> None:
    path = safe_pdf_path("Doe, Jane", "unsw", "A Thesis: With Punctuation!")
    assert path.parent == Path("/") / "tmp"
    assert path.name == "od_unsw_Doe_Jane_A_Thesis_With_Punctuation.pdf"


@pytest.mark.anyio
async def test_download_route_rejects_unsupported_institution() -> None:
    payload = type(
        "Payload",
        (),
        {"dissertations": [DissertationQuery(author="Doe, Jane", institution="Other University")]},
    )()
    with pytest.raises(HTTPException) as exc_info:
        await download_dissertations(payload)
    assert exc_info.value.status_code == 400
