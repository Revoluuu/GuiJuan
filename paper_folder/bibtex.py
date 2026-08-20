from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Sequence, Union

from .metadata import PaperMetadata


def _key(item: PaperMetadata, used: Dict[str, int]) -> str:
    first_author = item.authors.split(";")[0].strip().split()
    family = first_author[-1] if first_author else "paper"
    words = re.findall(r"[A-Za-z0-9]+", item.title)
    first_word = words[0] if words else "work"
    base = re.sub(r"[^A-Za-z0-9]", "", family + item.year + first_word).lower() or "paper"
    used[base] = used.get(base, 0) + 1
    return base if used[base] == 1 else base + str(used[base])


def export_bibtex(output: Union[str, Path], items: Sequence[PaperMetadata]) -> Path:
    destination = Path(output)
    used: Dict[str, int] = {}
    entries = []
    for item in items:
        fields = []
        if item.title:
            fields.append(("title", "{" + item.title.replace("{", "").replace("}", "") + "}"))
        if item.authors:
            fields.append(("author", "{" + item.authors.replace(";", " and") + "}"))
        if item.year:
            fields.append(("year", "{" + item.year + "}"))
        if item.doi:
            fields.append(("doi", "{" + item.doi + "}"))
        body = ",\n".join(f"  {name} = {value}" for name, value in fields)
        entries.append(f"@article{{{_key(item, used)},\n{body}\n}}")
    destination.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
    return destination

