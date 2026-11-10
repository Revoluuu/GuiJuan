from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .metadata import PaperMetadata


INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
ALLOWED_FIELDS = ("title", "authors", "year", "journal", "doi")
DEFAULT_FIELDS = ("year", "title")
FIELD_LABELS = {
    "title": "标题",
    "authors": "作者",
    "year": "年份",
    "journal": "期刊",
    "doi": "DOI",
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
    items: Sequence[PaperMetadata], template: str = "{year} - {title}", *,
    fields: Optional[Sequence[str]] = None, separator: str = " - ",
    conflict_strategy: str = "block",
) -> List[RenamePreview]:
    allowed = set(ALLOWED_FIELDS)
    template_fields = set(re.findall(r"\{([^{}]+)\}", template))
    unknown = template_fields - allowed
    if unknown:
        raise ValueError("Unknown template field(s): " + ", ".join(sorted(unknown)))
    ordered_fields: Optional[List[str]] = None
    if fields is not None:
        ordered_fields = []
        for field in fields:
            if field not in allowed:
                raise ValueError("Unknown naming field: " + field)
            if field not in ordered_fields:
                ordered_fields.append(field)
        if not ordered_fields:
            raise ValueError("At least one naming field is required")
    if conflict_strategy not in {"block", "suffix"}:
        raise ValueError("Unknown conflict strategy: " + conflict_strategy)

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
            if ordered_fields is None or tuple(ordered_fields) == DEFAULT_FIELDS:
                previews.append(RenamePreview(item.path, "", "needs review", "Missing title or year"))
                continue
        values: Dict[str, str] = {
            "title": item.title,
            "authors": item.authors,
            "year": item.year,
            "journal": item.journal,
            "doi": item.doi,
        }
        note = ""
        if ordered_fields is None:
            name = sanitize_filename(template.format(**values))
        else:
            missing = [field for field in ordered_fields if not values[field]]
            parts = [sanitize_filename(values[field]) for field in ordered_fields if values[field]]
            parts = [part for part in parts if part]
            name = sanitize_filename(separator.join(parts))
            if missing:
                note = "命名时已跳过未识别的" + "、".join(FIELD_LABELS[field] for field in missing)
        if not name:
            previews.append(RenamePreview(item.path, "", "needs review", "Empty suggested name"))
            continue
        previews.append(RenamePreview(item.path, name + ".pdf", "preview", note))

    if conflict_strategy == "suffix":
        return _resolve_conflicts_with_suffix(previews)

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


def _resolve_conflicts_with_suffix(previews: Sequence[RenamePreview]) -> List[RenamePreview]:
    occupied_by_parent: Dict[Path, set] = {}
    for preview in previews:
        parent = preview.source.parent.resolve()
        if parent not in occupied_by_parent:
            try:
                occupied_by_parent[parent] = {
                    child.name.casefold() for child in parent.iterdir()
                }
            except OSError:
                occupied_by_parent[parent] = set()

    final: List[RenamePreview] = []
    for preview in previews:
        if preview.status != "preview" or not preview.suggested_name:
            final.append(preview)
            continue
        parent = preview.source.parent.resolve()
        occupied = occupied_by_parent[parent]
        source_key = preview.source.name.casefold()
        candidate = preview.suggested_name
        # Renames preflight the whole batch before moving any files. Only a
        # PDF's own name is available when it is already present on disk.
        if candidate.casefold() != source_key and candidate.casefold() in occupied:
            path = Path(candidate)
            index = 2
            while True:
                suffix = f" ({index})"
                stem = sanitize_filename(path.stem, max_length=max(1, 180 - len(suffix)))
                alternative = stem + suffix + (path.suffix or ".pdf")
                alternative_key = alternative.casefold()
                if alternative_key == source_key or alternative_key not in occupied:
                    candidate = alternative
                    break
                index += 1
            conflict_note = f"名称冲突，已自动改为 {candidate}"
            note = "; ".join(value for value in (preview.note, conflict_note) if value)
            preview = RenamePreview(preview.source, candidate, "preview", note)
        occupied.add(candidate.casefold())
        final.append(preview)
    return final
