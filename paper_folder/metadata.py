from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from PyPDF2 import PdfReader


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
ARXIV_PATTERN = re.compile(r"^(\d{2})(?:0[1-9]|1[0-2])\.\d{4,5}")


@dataclass(frozen=True)
class PaperMetadata:
    path: Path
    title: str
    authors: str
    year: str
    doi: str
    status: str
    note: str = ""
    source: str = "local"
    document_type: str = "paper"
    suggested_name: str = ""


def metadata_status(
    title: str, authors: str, year: str, doi: str, *,
    require_doi: bool = True, document_type: str = "paper"
):
    required = [("title", title)]
    if document_type == "paper":
        required.extend((("authors", authors), ("year", year)))
        if require_doi:
            required.append(("DOI", doi))
    missing = [label for label, value in required if not value]
    if missing:
        return "partial", "Missing: " + ", ".join(missing)
    return "complete", ""


def _clean(value: object) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def _clean_doi(value: str) -> str:
    return value.rstrip(".,;:)]}>")


def find_doi(values: Sequence[str]) -> str:
    for value in values:
        match = DOI_PATTERN.search(value or "")
        if match:
            return _clean_doi(match.group(0))
    return ""


def _plausible_title(value: str, filename_stem: str) -> bool:
    lowered = value.casefold()
    if not value or len(value) < 8:
        return False
    if lowered in {filename_stem.casefold(), "untitled", "microsoft word"}:
        return False
    if lowered.startswith(("pii:", "http://", "https://")):
        return False
    if "\\" in value or re.fullmatch(r"[a-z]{1,4}\d{5,}\s+\d+\.\.\d+", lowered):
        return False
    return True


def _title_from_page(text: str, filename_stem: str) -> str:
    lines = [_clean(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    ignored = (
        "arxiv:", "downloaded", "copyright", "published", "received",
        "available online", "journal of", "physical review", "science ",
    )
    candidates: List[str] = []
    for line in lines[:18]:
        lowered = line.casefold()
        if lowered.startswith(ignored) or DOI_PATTERN.search(line):
            continue
        if lowered in {"article", "research article", "abstract"}:
            continue
        if len(line) >= 15 and _plausible_title(line, filename_stem):
            candidates.append(line)
        if candidates and len(" ".join(candidates)) >= 45:
            break
    return " ".join(candidates[:3]) if candidates else ""


def _appendix_fields(text: str):
    lines = [_clean(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines or not re.fullmatch(r"appendix\s+[a-z0-9]+", lines[0], re.IGNORECASE):
        return "", ""
    title = lines[1] if len(lines) > 1 else ""
    author = lines[2] if len(lines) > 2 else ""
    return title, author


def _year_from_filename(stem: str) -> str:
    match = YEAR_PATTERN.search(stem)
    if match:
        return match.group(1)
    arxiv = ARXIV_PATTERN.match(stem)
    if arxiv:
        return str(2000 + int(arxiv.group(1)))
    return ""


def _year_from_text(text: str) -> str:
    for pattern in (
        r"(?:published|publication|received|accepted|cite as)[^\n]{0,100}?(19\d{2}|20\d{2})",
        r"©\s*(19\d{2}|20\d{2})",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return ""


def extract_paper_metadata(path: Path, *, pages_to_read: int = 2) -> PaperMetadata:
    """Extract conservative metadata without changing the PDF."""
    try:
        reader = PdfReader(str(path), strict=False)
        raw = reader.metadata or {}
        page_texts: List[str] = []
        for page in reader.pages[:pages_to_read]:
            try:
                page_texts.append(page.extract_text() or "")
            except Exception:
                page_texts.append("")
    except Exception as error:
        return PaperMetadata(path, "", "", "", "", "error", str(error))

    page_text = "\n".join(page_texts)
    metadata_values = [_clean(value) for value in raw.values()]
    raw_title = _clean(raw.get("/Title"))
    raw_author = _clean(raw.get("/Author"))

    appendix_title, appendix_author = _appendix_fields(page_texts[0] if page_texts else "")
    document_type = "appendix" if appendix_title else "paper"

    title = appendix_title or (raw_title if _plausible_title(raw_title, path.stem) else "")
    if not title:
        title = _title_from_page(page_texts[0] if page_texts else "", path.stem)

    authors = appendix_author or raw_author
    if authors.casefold() in {"administrator", "user", "unknown", "anonymous"}:
        authors = ""

    filename_doi = path.stem.replace("@", "/")
    doi = find_doi([filename_doi, *metadata_values, page_text])
    year = _year_from_filename(path.stem) or _year_from_text(page_text)

    if not page_text.strip() and not any((title, authors, doi)):
        status = "scanned/unknown"
        note = "No searchable text or usable PDF metadata"
    else:
        status, note = metadata_status(
            title, authors, year, doi,
            require_doi=document_type == "paper", document_type=document_type,
        )

    return PaperMetadata(
        path, title, authors, year, doi, status, note,
        document_type=document_type,
    )
