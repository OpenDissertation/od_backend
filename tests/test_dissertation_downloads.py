from pathlib import Path

import pytest

from od_backend.dissertation_downloads import (
    author_matches,
    normalize_institution,
    safe_pdf_path,
)


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
    assert author_matches("Jane Doe", ["Doe, Jane"])
    assert not author_matches("Jane Smith", ["Jane Doe"])


def test_author_matches_requires_given_name_for_full_name_requests() -> None:
    assert not author_matches("Jane Smith", ["John Smith"])
    assert author_matches("Smith", ["John Smith"])


def test_safe_pdf_path_uses_tmp_directory() -> None:
    path = safe_pdf_path("Doe, Jane", "unsw", "A Thesis: With Punctuation!")
    assert path.parent == Path("/") / "tmp"
    assert path.name == "od_unsw_Doe_Jane_A_Thesis_With_Punctuation.pdf"
