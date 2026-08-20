from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .metadata import PaperMetadata, metadata_status


@dataclass(frozen=True)
class CrossrefRecord:
    title: str
    authors: str
    year: str
    doi: str


class CrossrefClient:
    """Small Crossref REST client with per-run caching and graceful failures."""

    def __init__(self, email: str = "", timeout: float = 10.0) -> None:
        self.email = email.strip()
        self.timeout = timeout
        self._cache: Dict[str, Optional[CrossrefRecord]] = {}

    def lookup(self, doi: str) -> Optional[CrossrefRecord]:
        key = doi.strip().casefold()
        if key in self._cache:
            return self._cache[key]

        query = urlencode({"mailto": self.email}) if self.email else ""
        url = "https://api.crossref.org/works/" + quote(doi.strip(), safe="")
        if query:
            url += "?" + query
        agent = "GuiJuan/0.2"
        if self.email:
            agent += " (mailto:" + self.email + ")"
        request = Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                message = json.load(response).get("message", {})
            result = record_from_message(message)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            result = None
        self._cache[key] = result
        return result


def _first_text(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    return ""


def _authors(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names: List[str] = []
    for author in value:
        if not isinstance(author, Mapping):
            continue
        name = " ".join(
            part for part in (str(author.get("given", "")).strip(), str(author.get("family", "")).strip()) if part
        )
        if name:
            names.append(name)
    return "; ".join(names)


def _year(message: Mapping[str, object]) -> str:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        value = message.get(field)
        if not isinstance(value, Mapping):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = str(parts[0][0])
            if len(year) == 4 and year.isdigit():
                return year
    return ""


def record_from_message(message: Mapping[str, object]) -> CrossrefRecord:
    return CrossrefRecord(
        title=_first_text(message.get("title")),
        authors=_authors(message.get("author")),
        year=_year(message),
        doi=str(message.get("DOI", "")).strip(),
    )


def enrich_from_crossref(item: PaperMetadata, client: CrossrefClient) -> PaperMetadata:
    if not item.doi:
        return item
    record = client.lookup(item.doi)
    if record is None:
        note = "; ".join(value for value in (item.note, "Crossref lookup unavailable") if value)
        return replace(item, note=note)

    title = record.title or item.title
    authors = record.authors or item.authors
    year = record.year or item.year
    doi = record.doi or item.doi
    status, missing_note = metadata_status(title, authors, year, doi)
    note = "Crossref verified"
    if missing_note:
        note += "; " + missing_note
    return PaperMetadata(item.path, title, authors, year, doi, status, note, "crossref")
