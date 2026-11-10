from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple
from xml.dom import Node

from PyPDF2 import PageObject, PdfReader
from PyPDF2.xmp import XmpInformation


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
ARXIV_PATTERN = re.compile(r"^(\d{2})(?:0[1-9]|1[0-2])\.\d{4,5}")
PRISM_NAMESPACES = (
    "http://prismstandard.org/namespaces/basic/3.0/",
    "http://prismstandard.org/namespaces/basic/2.1/",
    "http://prismstandard.org/namespaces/basic/2.0/",
    "http://prismstandard.org/namespaces/1.2/basic/",
)
PDFX_NAMESPACE = "http://ns.adobe.com/pdfx/1.3/"
JOURNAL_FIELDS = ("Journal", "JournalTitle", "JournalName", "PublicationName")
CITATION_YEAR = r"(?:19|20)\d{2}"
ARTICLE_NUMBER = r"[a-z]{0,5}\d{1,9}[a-z]?(?:\s*[-–—−]\s*\d{1,9})?"
JOURNAL_CITATIONS = tuple(
    re.compile(rf"(?P<journal>.+?)[, ]*\s*{details}[. ]*$", re.IGNORECASE)
    for details in (
        # Nature portfolio uses vertical bars in page footers.
        rf"\|\s*\({CITATION_YEAR}\)\s*\d{{1,5}}\s*:\s*{ARTICLE_NUMBER}(?:\s+\d{{1,4}})?",
        rf"\|\s*vol(?:\.|ume)?\s+\d{{1,5}}\s*\|\s*[^|]*{CITATION_YEAR}(?:\s*\|\s*\d+)?",
        # Year, volume, article/page (ACS/RSC), or volume, article/page (APS).
        rf"\s+{CITATION_YEAR}\s*,\s*\d{{1,5}}(?:\s*\(\d{{1,4}}\))?\s*,\s*{ARTICLE_NUMBER}(?:\s*\(\d+ of \d+\))?",
        rf"\s+\d{{1,5}}\s*,\s*{ARTICLE_NUMBER}\s*\({CITATION_YEAR}\)",
        # Volume (year) article/page (e.g. Elsevier and IOP).
        rf"\s+\d{{1,5}}\s*\({CITATION_YEAR}\)\s*{ARTICLE_NUMBER}",
        rf"\s+vol\.?\s+\d{{1,5}}\s*,\s*no\.?\s*\d{{1,5}}\s*,\s*[^,]*{CITATION_YEAR}",
    )
)
CITE_THIS = re.compile(r"cite\s*(?:this(?:\s+article)?|as)\s*:\s*", re.IGNORECASE)
JOURNAL_LABEL = re.compile(r"^(?:journal(?:\s+(?:title|name))?|期刊(?:名称|名)?)\s*[:：]\s*(.+)$", re.IGNORECASE)
REFERENCES_HEADING = re.compile(r"^(?:references|bibliography|参考文献)\s*[:：]?$", re.IGNORECASE)
DOI_LABEL = re.compile(r"(?:doi\s*:|https?://(?:dx\.)?doi\.org/)\s*(?=10\.)", re.IGNORECASE)
NON_JOURNAL_START = re.compile(r"^(?:fig(?:ure)?|table|scheme|chapter|section|appendix)\b", re.IGNORECASE)
FRONTIERS_FOOTER = re.compile(
    rf"(Frontiers in [^|]+)\|\s*www\.frontiersin\.org\s+[a-z]+\s+{CITATION_YEAR}"
    r"\s*\|\s*volume \d+\s*\|\s*article \d+",
    re.IGNORECASE,
)


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
    journal: str = ""


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
            end = match.end()
            cite_label = CITE_THIS.search(value, match.start())
            if cite_label and cite_label.start() < end:
                # Some PDF text streams join the DOI and the citation label
                # without whitespace. Confirm the citation before trimming.
                citation_line = value[cite_label.start():].split("\n", maxsplit=1)[0]
                if journal_from_citation(citation_line):
                    end = cite_label.start()
            return _clean_doi(value[match.start():end])
    return ""


def _journal_name(value: object) -> str:
    name = _clean(value).strip(" ,:|")
    if not 2 <= len(name) <= 140 or not name[0].isalpha():
        return ""
    if any(char in name for char in ("@", "|", "©", ";")) or DOI_PATTERN.search(name):
        return ""
    lowered = name.casefold()
    if lowered.startswith(("https:", "http:", "www.", "arxiv:", "preprint ", "published ", "downloaded ")):
        return ""
    if lowered in {"arxiv", "preprint", "unknown", "none", "n/a", "journal", "untitled"}:
        return ""
    return name


def journal_from_citation(citation: str) -> str:
    """Return a venue name only from a citation with a recognizable structure."""
    citation = _clean(citation)
    labeled = CITE_THIS.search(citation)
    if labeled:
        citation = citation[labeled.end():]
        # Some publisher PDFs extract "J.Phys.Chem.C2025" and space out
        # individual digits. Only repair these in an explicitly labeled citation.
        citation = re.sub(r"(?<=\d) (?=\d)", "", citation)
        citation = re.sub(
            rf"(?<=[a-zA-Z.])\s*,?\s*(?={CITATION_YEAR}\s*,)", " ", citation, count=1,
        )
    citation = citation.split("©", maxsplit=1)[0]
    citation = DOI_LABEL.split(citation, maxsplit=1)[0].rstrip(" .;,")
    if len(citation) > 240:
        return ""
    frontiers = FRONTIERS_FOOTER.match(citation)
    if frontiers:
        return _journal_name(frontiers.group(1))
    citation = re.sub(r"^\S+(?:\s+\S+){0,4}\s+et al\.,\s+", "", citation, flags=re.IGNORECASE)
    for pattern in JOURNAL_CITATIONS:
        match = pattern.fullmatch(citation)
        if match:
            journal = _journal_name(match.group("journal"))
            if NON_JOURNAL_START.match(journal):
                return ""
            if labeled:
                journal = re.sub(r"\.(?=[A-Z])", ". ", journal)
                journal = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", journal)
            return journal
    return ""


def _journal_from_page(text: str, title: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = _clean(raw_line)
        if REFERENCES_HEADING.fullmatch(line):
            break
        if line:
            lines.append(line)

    # Skip arbitrary mentions in body paragraphs. Use masthead/footer lines
    # and publisher-provided citation labels as evidence.
    header_footer = lines[:16] + lines[max(16, len(lines) - 8):]
    for line in header_footer:
        labeled = JOURNAL_LABEL.fullmatch(line)
        journal = _journal_name(labeled.group(1)) if labeled else journal_from_citation(line)
        if journal and journal.casefold() != title.casefold():
            return journal
    for index, line in enumerate(lines):
        if CITE_THIS.search(line):
            journal = journal_from_citation(line)
            if not journal and line.endswith(",") and index + 1 < len(lines):
                journal = journal_from_citation(line + " " + lines[index + 1])
            if journal and journal.casefold() != title.casefold():
                return journal
        if line.casefold() == "contents lists available at sciencedirect" and index + 2 < len(lines):
            if lines[index + 2].casefold().startswith("journal homepage:"):
                return _journal_name(lines[index + 1])
    return ""


def _xmp_values(xmp: XmpInformation, namespace: str, field: str) -> Iterator[str]:
    for element in xmp.get_element("", namespace, field):
        if element.nodeType == Node.ATTRIBUTE_NODE:
            yield element.value
        else:
            yield "".join(child.data for child in element.childNodes if child.nodeType in (
                Node.TEXT_NODE, Node.CDATA_SECTION_NODE
            ))


def _xmp_citation_fields(reader: PdfReader) -> Tuple[str, str]:
    try:
        xmp = reader.xmp_metadata
        if xmp is None:
            return "", ""
        journal_values = [
            value
            for namespace in PRISM_NAMESPACES
            for value in _xmp_values(xmp, namespace, "publicationName")
        ]
        journal_values.extend(
            value for field in JOURNAL_FIELDS for value in _xmp_values(xmp, PDFX_NAMESPACE, field)
        )
        doi_values = [
            value for namespace in PRISM_NAMESPACES for value in _xmp_values(xmp, namespace, "doi")
        ]
        doi_values.extend(_xmp_values(xmp, PDFX_NAMESPACE, "DOI"))
        doi_values.append(xmp.dc_identifier or "")
        journal = next((name for value in journal_values if (name := _journal_name(value))), "")
        return journal, find_doi(doi_values)
    except Exception:
        # A malformed optional XMP stream must not discard readable PDF text.
        return "", ""


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
        if (lowered.startswith(ignored) or DOI_PATTERN.search(line)
                or CITE_THIS.search(line) or JOURNAL_LABEL.fullmatch(line)
                or journal_from_citation(line)):
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


def _year_from_text(text: str, *, include_copyright: bool = True) -> str:
    match = re.search(
        r"(?:published|publication|received|accepted|cite as)[^\n]{0,100}?(19\d{2}|20\d{2})",
        text, re.IGNORECASE,
    )
    if not match and include_copyright:
        match = re.search(r"©\s*(19\d{2}|20\d{2})", text)
    return match.group(1) if match else ""


def _read_page_text(page: Optional[PageObject]) -> str:
    if page is None:
        return ""
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def extract_paper_metadata(path: Path, *, pages_to_read: int = 2) -> PaperMetadata:
    """Extract conservative metadata without changing the PDF."""
    try:
        reader = PdfReader(str(path), strict=False)
        raw = reader.metadata or {}
        pages = iter(reader.pages[:pages_to_read])
        first_page = _read_page_text(next(pages, None))
    except Exception as error:
        return PaperMetadata(path, "", "", "", "", "error", str(error))

    metadata_values = [_clean(value) for value in raw.values()]
    raw_title = _clean(raw.get("/Title"))
    raw_author = _clean(raw.get("/Author"))

    appendix_title, appendix_author = _appendix_fields(first_page)
    document_type = "appendix" if appendix_title else "paper"

    title = appendix_title or (raw_title if _plausible_title(raw_title, path.stem) else "")
    if not title:
        title = _title_from_page(first_page, path.stem)

    authors = appendix_author or raw_author
    if authors.casefold() in {"administrator", "user", "unknown", "anonymous"}:
        authors = ""

    filename_doi = path.stem.replace("@", "/")
    xmp_journal, xmp_doi = _xmp_citation_fields(reader)
    doi = find_doi([_clean(raw.get("/DOI")), xmp_doi, filename_doi, *metadata_values, first_page])
    year = _year_from_filename(path.stem) or _year_from_text(first_page, include_copyright=False)
    page_text = first_page
    if not doi or not year:
        # Later pages can supply a missing DOI or publication date. Avoid
        # extracting their text when those fields are already known.
        page_text = "\n".join([first_page, *(_read_page_text(page) for page in pages)])
        doi = doi or find_doi([page_text])
        year = year or _year_from_text(page_text)

    journal = xmp_journal or next(
        (name for field in JOURNAL_FIELDS if (name := _journal_name(raw.get("/" + field)))), ""
    )
    if not journal:
        journal = journal_from_citation(_clean(raw.get("/Subject"))) or _journal_from_page(first_page, title)
    if not page_text.strip() and not any((title, authors, doi, journal)):
        status = "scanned/unknown"
        note = "No searchable text or usable PDF metadata"
    else:
        status, note = metadata_status(
            title, authors, year, doi,
            require_doi=document_type == "paper", document_type=document_type,
        )

    return PaperMetadata(
        path, title, authors, year, doi, status, note,
        document_type=document_type, journal=journal,
    )
