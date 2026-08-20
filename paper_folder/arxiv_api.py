from __future__ import annotations

from dataclasses import replace
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .metadata import ARXIV_PATTERN, PaperMetadata, metadata_status


ATOM = "{http://www.w3.org/2005/Atom}"


def arxiv_id_from_filename(stem: str) -> str:
    match = ARXIV_PATTERN.match(stem)
    return match.group(0) if match else ""


def enrich_from_arxiv(item: PaperMetadata, timeout: float = 10.0) -> PaperMetadata:
    arxiv_id = arxiv_id_from_filename(item.path.stem)
    if not arxiv_id:
        return item
    url = "https://export.arxiv.org/api/query?" + urlencode({"id_list": arxiv_id})
    request = Request(url, headers={"User-Agent": "GuiJuan/0.2"})
    try:
        with urlopen(request, timeout=timeout) as response:
            root = ElementTree.parse(response).getroot()
        entry = root.find(ATOM + "entry")
        if entry is None:
            return replace(item, note="; ".join(filter(None, (item.note, "arXiv record not found"))))
        title_node = entry.find(ATOM + "title")
        title_text = "" if title_node is None else "".join(title_node.itertext())
        title = " ".join(title_text.split()) or item.title
        authors: List[str] = []
        for author in entry.findall(ATOM + "author"):
            name = " ".join((author.findtext(ATOM + "name") or "").split())
            if name:
                authors.append(name)
        published = entry.findtext(ATOM + "published") or ""
        year = published[:4] if len(published) >= 4 else item.year
        author_text = "; ".join(authors) or item.authors
        status, missing = metadata_status(title, author_text, year, item.doi, require_doi=False)
        note = "arXiv verified"
        if not item.doi:
            note += "; DOI not present"
        if missing:
            note += "; " + missing
        return PaperMetadata(item.path, title, author_text, year, item.doi, status, note, "arxiv")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, ElementTree.ParseError):
        return replace(item, note="; ".join(filter(None, (item.note, "arXiv lookup unavailable"))))
