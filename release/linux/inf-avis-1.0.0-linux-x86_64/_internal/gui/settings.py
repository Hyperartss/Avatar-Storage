"""Persistent user settings for INF Avis.

Stored as ``settings.json`` in the platform config directory (see
``paths.py``), so settings survive updates and roam with the user's data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import paths

# --------------------------------------------------------------------------- defaults

DEFAULTS = {
    "theme": "system",          # light / dark / system
    "density": "comfortable",   # comfortable / compact
    "confirm_delete": True,
    "show_sidebar": True,
    "last_sort": "date_added",
    "show_avatar_ids": True,
}


def _settings_path() -> Path:
    return paths.config_dir() / "settings.json"


def load() -> dict[str, Any]:
    """Return the current settings, merged with defaults for any missing keys."""
    settings = dict(DEFAULTS)
    path = _settings_path()
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                settings.update(stored)
        except (OSError, json.JSONDecodeError):
            # A corrupt settings file is worse than missing defaults; ignore it.
            pass
    return settings


def save(settings: dict[str, Any]) -> None:
    """Persist the full settings dict."""
    path = _settings_path()
    paths.ensure_dirs()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, sort_keys=True)
    tmp.replace(path)


def get(settings: dict[str, Any], key: str) -> Any:
    return settings.get(key, DEFAULTS[key])


def set_(settings: dict[str, Any], key: str, value: Any) -> None:
    settings[key] = value
