from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union
from uuid import uuid4

from .naming import RenamePreview


DEFAULT_HISTORY_NAME = ".paper-folder-history.json"


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    changed: int


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("Path leaves the selected folder: " + str(path))


def _read_history(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Cannot read operation history: " + str(error))
    if not isinstance(value, list):
        raise ValueError("Operation history has an invalid format")
    return value


def _write_history(path: Path, history: List[Dict[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def apply_renames(
    previews: Sequence[RenamePreview], root: Path, history_path: Union[str, Path, None] = None
) -> OperationResult:
    root = root.resolve()
    history_file = Path(history_path) if history_path else root / DEFAULT_HISTORY_NAME
    pairs: List[Tuple[Path, Path]] = []
    for preview in previews:
        if preview.status != "preview" or not preview.suggested_name:
            continue
        source = preview.source.resolve()
        _inside(source, root)
        target = source.with_name(preview.suggested_name).resolve()
        _inside(target, root)
        if not source.is_file():
            raise FileNotFoundError("Source PDF not found: " + str(source))
        if source == target:
            continue
        if target.exists():
            raise FileExistsError("Target already exists: " + str(target))
        pairs.append((source, target))

    target_keys = [str(target).casefold() for _, target in pairs]
    if len(target_keys) != len(set(target_keys)):
        raise FileExistsError("Two PDFs would receive the same filename")
    if not pairs:
        raise ValueError("No reviewed filenames are ready to apply")

    completed: List[Tuple[Path, Path]] = []
    try:
        for source, target in pairs:
            source.rename(target)
            completed.append((source, target))
        history = _read_history(history_file)
        operation_id = uuid4().hex
        history.append({
            "id": operation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "undone_at": None,
            "changes": [
                {"old": str(_inside(old, root)), "new": str(_inside(new, root))}
                for old, new in completed
            ],
        })
        _write_history(history_file, history)
    except Exception:
        for source, target in reversed(completed):
            if target.exists() and not source.exists():
                target.rename(source)
        raise
    return OperationResult(operation_id, len(completed))


def undo_last(root: Path, history_path: Union[str, Path, None] = None) -> OperationResult:
    root = root.resolve()
    history_file = Path(history_path) if history_path else root / DEFAULT_HISTORY_NAME
    history = _read_history(history_file)
    operation = next((entry for entry in reversed(history) if not entry.get("undone_at")), None)
    if operation is None:
        raise ValueError("No rename operation is available to undo")
    changes = operation.get("changes")
    if not isinstance(changes, list):
        raise ValueError("Operation history has invalid changes")

    pairs: List[Tuple[Path, Path]] = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Operation history has an invalid change")
        old = (root / str(change.get("old", ""))).resolve()
        new = (root / str(change.get("new", ""))).resolve()
        _inside(old, root)
        _inside(new, root)
        if not new.is_file():
            raise FileNotFoundError("Renamed PDF not found: " + str(new))
        if old.exists():
            raise FileExistsError("Original filename is already occupied: " + str(old))
        pairs.append((old, new))

    completed: List[Tuple[Path, Path]] = []
    try:
        for old, new in reversed(pairs):
            new.rename(old)
            completed.append((old, new))
        operation["undone_at"] = datetime.now(timezone.utc).isoformat()
        _write_history(history_file, history)
    except Exception:
        for old, new in reversed(completed):
            if old.exists() and not new.exists():
                old.rename(new)
        raise
    return OperationResult(str(operation.get("id", "")), len(completed))

