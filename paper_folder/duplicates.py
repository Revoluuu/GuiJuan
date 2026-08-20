from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from .metadata import PaperMetadata


@dataclass(frozen=True)
class DuplicateGroup:
    reason: str
    files: Sequence[Path]


def _title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def find_duplicates(items: Sequence[PaperMetadata]) -> List[DuplicateGroup]:
    doi_groups: Dict[str, List[Path]] = {}
    fallback_groups: Dict[str, List[Path]] = {}
    for item in items:
        if item.doi:
            doi_groups.setdefault(item.doi.casefold().strip(), []).append(item.path)
        elif item.title and item.year:
            key = item.year + ":" + _title_key(item.title)
            fallback_groups.setdefault(key, []).append(item.path)

    groups = [
        DuplicateGroup("same DOI", tuple(paths))
        for paths in doi_groups.values() if len(paths) > 1
    ]
    groups.extend(
        DuplicateGroup("same title and year", tuple(paths))
        for paths in fallback_groups.values() if len(paths) > 1
    )
    return groups

