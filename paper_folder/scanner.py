from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from threading import Event
from typing import List, Optional, Union


@dataclass(frozen=True)
class PdfFile:
    """A PDF discovered during a read-only folder scan."""

    path: Path
    relative_path: Path
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_display(self) -> str:
        return format_file_size(self.size_bytes)


def format_file_size(size_bytes: int) -> str:
    """Return a compact human-readable file size."""
    if size_bytes < 0:
        raise ValueError("File size cannot be negative.")

    value = float(size_bytes)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024

    raise AssertionError("Unreachable file-size branch.")


def scan_pdf_files(
    folder: Union[str, Path], *, recursive: bool = False, cancel: Optional[Event] = None,
) -> List[PdfFile]:
    """Scan *folder* for PDFs without modifying any files."""
    root = Path(folder).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a folder: {root}")

    candidates = root.rglob("*") if recursive else root.iterdir()
    results = []
    for path in candidates:
        if cancel is not None and cancel.is_set():
            raise CancelledError
        if path.suffix.lower() != ".pdf":
            continue
        try:
            details = path.stat()
        except FileNotFoundError:
            continue
        if S_ISREG(details.st_mode):
            results.append(PdfFile(path, path.relative_to(root), details.st_size))
    return sorted(results, key=lambda item: str(item.relative_path).casefold())
