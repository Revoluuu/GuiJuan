from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Union


DEFAULT_NAMING_FIELDS = ["year", "title"]
ALLOWED_NAMING_FIELDS = {"title", "authors", "year", "journal", "doi"}


@dataclass
class AppSettings:
    version: int = 1
    email: str = ""
    recursive: bool = True
    online: bool = True
    naming_fields: List[str] = field(default_factory=lambda: list(DEFAULT_NAMING_FIELDS))
    onboarding_complete: bool = False

    def normalized(self) -> "AppSettings":
        fields: List[str] = []
        for value in self.naming_fields:
            if value in ALLOWED_NAMING_FIELDS and value not in fields:
                fields.append(value)
        if not fields:
            fields = list(DEFAULT_NAMING_FIELDS)
        return AppSettings(
            version=1,
            email=str(self.email).strip(),
            recursive=bool(self.recursive),
            online=bool(self.online),
            naming_fields=fields,
            onboarding_complete=bool(self.onboarding_complete),
        )


def default_settings_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "GuiJuan" / "settings.json"
    return Path.home() / ".guijuan" / "settings.json"


def load_settings(path: Optional[Union[str, Path]] = None) -> AppSettings:
    source = Path(path) if path is not None else default_settings_path()
    if not source.exists():
        return AppSettings()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return AppSettings()
        settings = AppSettings(
            version=int(value.get("version", 1)),
            email=str(value.get("email", "")),
            recursive=bool(value.get("recursive", True)),
            online=bool(value.get("online", True)),
            naming_fields=list(value.get("naming_fields", DEFAULT_NAMING_FIELDS)),
            onboarding_complete=bool(value.get("onboarding_complete", False)),
        )
        return settings.normalized()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Optional[Union[str, Path]] = None) -> Path:
    destination = Path(path) if path is not None else default_settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(settings.normalized()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
