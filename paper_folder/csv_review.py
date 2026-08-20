from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Sequence, Union

from .metadata import PaperMetadata, extract_paper_metadata, metadata_status
from .naming import RenamePreview


FIELDS = (
    "relative_path", "document_type", "title", "authors", "year", "doi", "status",
    "suggested_name", "note",
)


def export_review_csv(
    output: Union[str, Path], root: Path, items: Sequence[PaperMetadata], previews: Sequence[RenamePreview]
) -> Path:
    destination = Path(output)
    suggestions = {preview.source.resolve(): preview.suggested_name for preview in previews}
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for item in items:
            try:
                relative = item.path.resolve().relative_to(root.resolve())
            except ValueError:
                relative = item.path.name
            writer.writerow({
                "relative_path": str(relative),
                "document_type": item.document_type,
                "title": item.title,
                "authors": item.authors,
                "year": item.year,
                "doi": item.doi,
                "status": item.status,
                "suggested_name": suggestions.get(item.path.resolve(), ""),
                "note": item.note,
            })
    return destination


def load_review_csv(source: Union[str, Path], root: Path) -> List[PaperMetadata]:
    items: List[PaperMetadata] = []
    root_resolved = root.resolve()
    with Path(source).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"relative_path", "title", "authors", "year", "doi"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Review CSV missing column(s): " + ", ".join(sorted(missing)))
        for row in reader:
            path = (root_resolved / row["relative_path"]).resolve()
            try:
                path.relative_to(root_resolved)
            except ValueError:
                raise ValueError("CSV path leaves the selected folder: " + row["relative_path"])
            title = row.get("title", "").strip()
            authors = row.get("authors", "").strip()
            year = row.get("year", "").strip()
            doi = row.get("doi", "").strip()
            document_type = row.get("document_type", "").strip()
            if not document_type and path.is_file():
                document_type = extract_paper_metadata(path).document_type
            document_type = document_type or "paper"
            status, note = metadata_status(
                title, authors, year, doi,
                require_doi=document_type == "paper", document_type=document_type,
            )
            items.append(PaperMetadata(
                path, title, authors, year, doi, status, note, "review-csv",
                document_type, row.get("suggested_name", "").strip(),
            ))
    return items
