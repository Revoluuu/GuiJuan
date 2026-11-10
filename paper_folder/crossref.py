from __future__ import annotations

import json
from concurrent.futures import CancelledError
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from threading import Event, Lock
from time import monotonic
from typing import Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .metadata import PaperMetadata, metadata_status


@dataclass(frozen=True)
class CrossrefRecord:
    title: str
    authors: str
    year: str
    doi: str
    journal: str = ""


class CrossrefClient:
    """Small Crossref REST client with per-run caching and graceful failures."""

    def __init__(
        self, email: str = "", timeout: float = 10.0, *, cancel: Optional[Event] = None,
    ) -> None:
        self.email = email.strip()
        self.timeout = timeout
        self._cancel = cancel
        self._cache: Dict[str, Optional[CrossrefRecord]] = {}
        self._lock = Lock()
        self._next_request = 0.0
        self._transient_failures = 0
        self._paused = False

    def lookup(self, doi: str) -> Optional[CrossrefRecord]:
        key = doi.strip().casefold()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        if not self._wait_for_turn():
            return None

        query = urlencode({"mailto": self.email}) if self.email else ""
        url = "https://api.crossref.org/works/" + quote(doi.strip(), safe="")
        if query:
            url += "?" + query
        agent = f"GuiJuan/{__version__}"
        if self.email:
            agent += " (mailto:" + self.email + ")"
        request = Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            message = payload.get("message") if isinstance(payload, Mapping) else None
            result = record_from_message(message) if isinstance(message, Mapping) else None
            self._record_failure(False)
        except HTTPError as error:
            self._record_failure(error.code >= 500)
            if self._cancel is not None and error.code == 429:
                self._back_off(error.headers.get("Retry-After") if error.headers else None)
            if error.fp is not None:
                error.close()
            result = None
        except (URLError, OSError, HTTPException, ValueError):
            self._record_failure(True)
            result = None
        with self._lock:
            self._cache[key] = result
        return result

    def _wait_for_turn(self) -> bool:
        if self._cancel is None:
            return True
        # Space request starts at the documented 5/s public or 10/s polite rate.
        interval = 0.1 if self.email else 0.2
        while not self._cancel.is_set():
            with self._lock:
                if self._paused:
                    return False
                now = monotonic()
                delay = self._next_request - now
                if delay <= 0:
                    self._next_request = now + interval
                    return True
            self._cancel.wait(delay)
        raise CancelledError

    def _record_failure(self, transient: bool) -> None:
        if self._cancel is not None:
            with self._lock:
                self._transient_failures = self._transient_failures + 1 if transient else 0
                if self._transient_failures >= 3:
                    self._paused = True

    def _back_off(self, retry_after: Optional[str]) -> None:
        delay = 3.0
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                try:
                    retry_date = parsedate_to_datetime(retry_after)
                    delay = max(delay, (retry_date - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        with self._lock:
            if delay > 5:
                # Preserve the local results when the service requests a longer pause.
                self._paused = True
            else:
                self._next_request = max(self._next_request, monotonic() + delay)


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
    work_type = message.get("type")
    journal = ""
    if not work_type or work_type in ("journal-article", "journal-issue", "journal-volume", "journal"):
        journal = _first_text(message.get("container-title")) or _first_text(message.get("short-container-title"))
    return CrossrefRecord(
        title=_first_text(message.get("title")),
        authors=_authors(message.get("author")),
        year=_year(message),
        doi=str(message.get("DOI", "")).strip(),
        journal=journal,
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
    return PaperMetadata(
        item.path, title, authors, year, doi, status, note, "crossref",
        item.document_type, item.suggested_name, record.journal or item.journal,
    )
