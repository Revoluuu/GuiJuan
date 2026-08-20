from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from .metadata import PaperMetadata


INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class RenamePreview:
    source: Path
    suggested_name: str
    status: str
    note: str = ""


def sanitize_filename(value: str, *, max_length: int = 180) -> str:
    value = INVALID_WINDOWS_CHARS.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        return ""
    if value.upper() in RESERVED_NAMES:
        value += "-paper"
    return value[:max_length].rstrip(" .")


def build_rename_previews(
    items: Sequence[PaperMetadata], template: str = "{year} - {title}"
) -> List[RenamePreview]:
    allowed = {"title", "authors", "year", "doi"}
    fields = set(re.findall(r"\{([^{}]+)\}", template))
    unknown = fields - allowed
    if unknown:
        raise ValueError("Unknown template field(s): " + ", ".join(sorted(unknown)))

    previews: List[RenamePreview] = []
    for item in items:
        if item.suggested_name:
            requested = item.suggested_name
            if requested.casefold().endswith(".pdf"):
                requested = requested[:-4]
            name = sanitize_filename(requested)
            previews.append(RenamePreview(item.path, name + ".pdf" if name else "", "preview" if name else "needs review"))
            continue
        if item.document_type == "appendix":
            if not item.title:
                previews.append(RenamePreview(item.path, "", "needs review", "Missing title"))
                continue
            name = sanitize_filename("Appendix - " + item.title)
            previews.append(RenamePreview(item.path, name + ".pdf", "preview"))
            continue
        if not item.title or not item.year:
            previews.append(RenamePreview(item.path, "", "needs review", "Missing title or year"))
            continue
        values: Dict[str, str] = {
            "title": item.title,
            "authors": item.authors,
            "year": item.year,
            "doi": item.doi,
        }
        name = sanitize_filename(template.format(**values))
        if not name:
            previews.append(RenamePreview(item.path, "", "needs review", "Empty suggested name"))
            continue
        previews.append(RenamePreview(item.path, name + ".pdf", "preview"))

    counts: Dict[str, int] = {}
    for preview in previews:
        if preview.suggested_name:
            key = preview.suggested_name.casefold()
            counts[key] = counts.get(key, 0) + 1

    final: List[RenamePreview] = []
    for preview in previews:
        if preview.suggested_name and counts[preview.suggested_name.casefold()] > 1:
            final.append(RenamePreview(preview.source, preview.suggested_name, "conflict", "Duplicate suggestion"))
        elif preview.suggested_name and (preview.source.parent / preview.suggested_name).exists() and preview.source.name.casefold() != preview.suggested_name.casefold():
            final.append(RenamePreview(preview.source, preview.suggested_name, "conflict", "Target already exists"))
        else:
            final.append(preview)
    return final
