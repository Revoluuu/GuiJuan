from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .scanner import PdfFile, scan_pdf_files
from .metadata import PaperMetadata, extract_paper_metadata
from .naming import RenamePreview, build_rename_previews
from .crossref import CrossrefClient, enrich_from_crossref
from .csv_review import export_review_csv, load_review_csv
from .arxiv_api import enrich_from_arxiv
from .duplicates import DuplicateGroup, find_duplicates
from .operations import apply_renames, undo_last
from .bibtex import export_bibtex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-folder",
        description="Safely scan, review and organize a folder of PDF papers.",
    )
    parser.add_argument("folder", type=Path, help="Folder containing PDF files")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include PDF files inside subfolders",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview safe filenames; never renames files",
    )
    parser.add_argument(
        "--name-template",
        default="{year} - {title}",
        help="Filename template used with --preview",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Extract title, author, year and DOI (still read-only)",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Verify locally found DOIs with Crossref",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Contact email for Crossref polite access (recommended)",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        help="Write an editable UTF-8 review CSV",
    )
    parser.add_argument(
        "--review-csv",
        type=Path,
        help="Load corrections from a previously exported CSV",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply reviewed filename changes and write an Undo log",
    )
    action_group.add_argument(
        "--undo",
        action="store_true",
        help="Undo the latest rename operation",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the typed confirmation for --apply or --undo",
    )
    parser.add_argument(
        "--duplicates",
        action="store_true",
        help="Report duplicate DOI or matching title/year",
    )
    parser.add_argument(
        "--export-bibtex",
        type=Path,
        help="Export recognized metadata as a BibTeX file",
    )
    return parser


def render_table(files: Sequence[PdfFile]) -> str:
    if not files:
        return "No PDF files found."

    rows = [
        (str(index), str(item.relative_path), item.size_display, "ready")
        for index, item in enumerate(files, start=1)
    ]
    headers = ("#", "Relative path", "Size", "Status")
    widths = [
        max(len(headers[column]), *(len(row[column]) for row in rows))
        for column in range(len(headers))
    ]

    def format_row(row: Sequence[str]) -> str:
        return " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        )

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join(
        [format_row(headers), separator, *(format_row(row) for row in rows)]
    )


def _shorten(value: str, limit: int) -> str:
    if not value:
        return "—"
    return value if len(value) <= limit else value[: limit - 1] + "…"


def render_metadata_table(items: Sequence[PaperMetadata]) -> str:
    if not items:
        return "No PDF files found."
    rows = []
    for index, item in enumerate(items, start=1):
        rows.append((
            str(index), _shorten(item.path.name, 27), item.document_type, _shorten(item.title, 48),
            _shorten(item.authors, 28), item.year or "—", item.doi or "—", item.status,
        ))
    headers = ("#", "File", "Type", "Title", "Authors", "Year", "DOI", "Status")
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(8)]
    format_row = lambda row: " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))
    return "\n".join([format_row(headers), "-+-".join("-" * w for w in widths), *(format_row(row) for row in rows)])


def render_preview_table(items: Sequence[RenamePreview]) -> str:
    if not items:
        return "No PDF files found."
    rows = [
        (str(i), _shorten(item.source.name, 35), _shorten(item.suggested_name, 64), item.status)
        for i, item in enumerate(items, start=1)
    ]
    headers = ("#", "Current name", "Suggested name", "Status")
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(4)]
    format_row = lambda row: " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))
    return "\n".join([format_row(headers), "-+-".join("-" * w for w in widths), *(format_row(row) for row in rows)])


def render_duplicate_groups(groups: Sequence[DuplicateGroup]) -> str:
    if not groups:
        return "No probable duplicates found."
    lines = []
    for index, group in enumerate(groups, start=1):
        lines.append(f"Group {index} ({group.reason})")
        lines.extend("  - " + str(path) for path in group.files)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Some Windows PowerShell installations still use GBK. Keep unusual author
    # names or filenames from crashing the whole scan in those terminals.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        files = scan_pdf_files(args.folder, recursive=args.recursive)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    if args.undo:
        if not args.yes:
            answer = input("Type UNDO to restore the latest renamed files: ").strip()
            if answer != "UNDO":
                print("Undo cancelled. No files were changed.")
                return 1
        try:
            result = undo_last(args.folder)
        except (OSError, ValueError) as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
        print(f"Restored {result.changed} PDF file(s). Operation: {result.operation_id}")
        return 0

    needs_metadata = any((
        args.preview, args.metadata, args.online, args.export_csv,
        args.review_csv, args.apply, args.duplicates, args.export_bibtex,
    ))
    if not needs_metadata:
        print(render_table(files))
        print(f"\nFound {len(files)} PDF file(s). Read-only scan completed.")
        return 0

    if args.apply and not args.review_csv:
        print("Error: --apply requires a reviewed --review-csv file", file=sys.stderr)
        return 2

    try:
        if args.review_csv:
            items = load_review_csv(args.review_csv, args.folder)
        else:
            items = [extract_paper_metadata(item.path) for item in files]
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    if args.online:
        client = CrossrefClient(email=args.email)
        items = [enrich_from_crossref(item, client) for item in items]
        items = [enrich_from_arxiv(item) if not item.doi else item for item in items]

    try:
        previews = build_rename_previews(items, args.name_template)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    if args.export_csv:
        try:
            destination = export_review_csv(args.export_csv, args.folder, items, previews)
        except OSError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
        print(f"Review CSV written: {destination}")

    if args.export_bibtex:
        try:
            destination = export_bibtex(args.export_bibtex, items)
        except OSError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
        print(f"BibTeX written: {destination}")

    if args.duplicates:
        print(render_duplicate_groups(find_duplicates(items)))

    if args.preview or args.apply:
        print(render_preview_table(previews))
        ready = sum(item.status == "preview" for item in previews)
        if args.apply:
            print(f"\n{ready} of {len(previews)} filename(s) are ready to rename after confirmation.")
        else:
            print(f"\n{ready} of {len(previews)} filename(s) ready for review. No files were renamed.")
        if args.apply:
            if not args.yes:
                answer = input(f"Type RENAME to rename these {ready} PDF file(s): ").strip()
                if answer != "RENAME":
                    print("Rename cancelled. No files were changed.")
                    return 1
            try:
                result = apply_renames(previews, args.folder)
            except (OSError, ValueError) as error:
                print(f"Error: {error}", file=sys.stderr)
                return 2
            print(f"Renamed {result.changed} PDF file(s). Operation: {result.operation_id}")
    elif args.metadata or args.online:
        print(render_metadata_table(items))
        unresolved = sum(item.status != "complete" for item in items)
        print(f"\nFound {len(files)} PDF file(s); {unresolved} need review. Read-only extraction completed.")
    return 0
