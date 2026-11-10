from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Callable, Dict, List

from .arxiv_api import apply_arxiv_entry, arxiv_id_from_filename, lookup_arxiv_entries
from .crossref import CrossrefClient, enrich_from_crossref
from .metadata import PaperMetadata, extract_paper_metadata
from .scanner import scan_pdf_files


ReportProgress = Callable[[str, int, int], None]
NETWORK_TIMEOUT = 5.0
ARXIV_BATCH_SIZE = 100
ARXIV_INTERVAL = 3.0


def _check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise CancelledError


def scan_papers(
    root: Path, recursive: bool, online: bool, email: str,
    report: ReportProgress, cancel: Event,
) -> List[PaperMetadata]:
    """Collect metadata in folder order without making any GUI calls or file changes."""
    _check_cancel(cancel)
    report("discover", 0, 0)
    files = scan_pdf_files(root, recursive=recursive, cancel=cancel)
    items: List[PaperMetadata] = []
    report("local", 0, len(files))
    for file in files:
        _check_cancel(cancel)
        items.append(extract_paper_metadata(file.path))
        report("local", len(items), len(files))
    if online:
        _verify_online(items, email.strip(), report, cancel)
    _check_cancel(cancel)
    return items


def _verify_online(
    items: List[PaperMetadata], email: str, report: ReportProgress, cancel: Event,
) -> None:
    dois: Dict[str, List[int]] = {}
    arxiv_ids: Dict[str, List[int]] = {}
    for index, item in enumerate(items):
        _check_cancel(cancel)
        doi = item.doi.strip().casefold()
        if doi:
            dois.setdefault(doi, []).append(index)
        else:
            arxiv_id = arxiv_id_from_filename(item.path.stem)
            if arxiv_id:
                arxiv_ids.setdefault(arxiv_id, []).append(index)
    total = sum(len(group) for group in dois.values()) + sum(len(group) for group in arxiv_ids.values())
    if not total:
        return

    completed = 0
    report("online", completed, total)
    if dois:
        client = CrossrefClient(email, timeout=NETWORK_TIMEOUT, cancel=cancel)

        def verify_doi(indexes: List[int]) -> List[PaperMetadata]:
            _check_cancel(cancel)
            return [enrich_from_crossref(items[index], client) for index in indexes]

        # The anonymous Crossref pool allows one in-flight request. The polite
        # pool allows more, but two are enough to overlap network waits here.
        with ThreadPoolExecutor(max_workers=2 if email else 1) as pool:
            pending = {}
            try:
                for indexes in dois.values():
                    _check_cancel(cancel)
                    pending[pool.submit(verify_doi, indexes)] = indexes
                for future in as_completed(pending):
                    _check_cancel(cancel)
                    indexes = pending[future]
                    for index, item in zip(indexes, future.result()):
                        items[index] = item
                    completed += len(indexes)
                    report("online", completed, total)
            finally:
                for future in pending:
                    future.cancel()

    ids = list(arxiv_ids)
    next_request = 0.0
    available = True
    for start in range(0, len(ids), ARXIV_BATCH_SIZE):
        _check_cancel(cancel)
        batch = ids[start : start + ARXIV_BATCH_SIZE]
        entries = None
        if available:
            if cancel.wait(max(0.0, next_request - monotonic())):
                raise CancelledError
            next_request = monotonic() + ARXIV_INTERVAL
            entries = lookup_arxiv_entries(batch, timeout=NETWORK_TIMEOUT)
            available = entries is not None
        _check_cancel(cancel)
        for arxiv_id in batch:
            indexes = arxiv_ids[arxiv_id]
            for index in indexes:
                items[index] = apply_arxiv_entry(items[index], entries)
            completed += len(indexes)
        report("online", completed, total)
