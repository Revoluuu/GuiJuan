from __future__ import annotations

from dataclasses import replace
from http.client import HTTPException
from typing import Dict, Optional, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from . import __version__
from .metadata import ARXIV_PATTERN, PaperMetadata, journal_from_citation, metadata_status


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def arxiv_id_from_filename(stem: str) -> str:
    match = ARXIV_PATTERN.match(stem)
    return match.group(0) if match else ""


def enrich_from_arxiv(item: PaperMetadata, timeout: float = 10.0) -> PaperMetadata:
    arxiv_id = arxiv_id_from_filename(item.path.stem)
    if not arxiv_id:
        return item
    entries = lookup_arxiv_entries([arxiv_id], timeout=timeout)
    return apply_arxiv_entry(item, entries)


def lookup_arxiv_entries(
    ids: Sequence[str], *, timeout: float = 10.0,
) -> Optional[Dict[str, ElementTree.Element]]:
    """Return entries keyed by identifier, or None if the service is unavailable."""
    url = "https://export.arxiv.org/api/query?" + urlencode({
        "id_list": ",".join(ids), "max_results": len(ids),
    })
    request = Request(url, headers={"User-Agent": f"GuiJuan/{__version__}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            root = ElementTree.parse(response).getroot()
    except HTTPError as error:
        if error.fp is not None:
            error.close()
        return None
    except (OSError, HTTPException, ValueError, ElementTree.ParseError):
        return None

    requested = set(ids)
    entries = {}
    for entry in root.findall(ATOM + "entry"):
        url = entry.findtext(ATOM + "id", "")
        arxiv_id = arxiv_id_from_filename(url.rsplit("/", 1)[-1])
        if arxiv_id in requested:
            entries[arxiv_id] = entry
    return entries


def apply_arxiv_entry(
    item: PaperMetadata, entries: Optional[Dict[str, ElementTree.Element]],
) -> PaperMetadata:
    arxiv_id = arxiv_id_from_filename(item.path.stem)
    entry = entries.get(arxiv_id) if entries is not None else None
    if entry is None:
        reason = "arXiv lookup unavailable" if entries is None else "arXiv record not found"
        return replace(item, note="; ".join(filter(None, (item.note, reason))))

    title_node = entry.find(ATOM + "title")
    title_text = "" if title_node is None else "".join(title_node.itertext())
    title = " ".join(title_text.split()) or item.title
    authors = [" ".join(author.findtext(ATOM + "name", "").split())
               for author in entry.findall(ATOM + "author")]
    author_text = "; ".join(filter(None, authors)) or item.authors
    published = entry.findtext(ATOM + "published", "")
    year = published[:4] if len(published) >= 4 else item.year
    status, missing = metadata_status(title, author_text, year, item.doi, require_doi=False)
    note = "arXiv verified"
    if not item.doi:
        note += "; DOI not present"
    if missing:
        note += "; " + missing
    journal = journal_from_citation(entry.findtext(ARXIV + "journal_ref", ""))
    return replace(
        item, title=title, authors=author_text, year=year, status=status,
        note=note, source="arxiv", journal=journal or item.journal,
    )
