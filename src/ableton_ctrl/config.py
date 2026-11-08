"""Shared user configuration for setup and standalone audio commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def configuration() -> Path:
    return Path.home() / ".config/ableton-ctrl/config.json"


def read_configuration() -> dict[str, Any]:
    path = configuration()
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a configuration object: {path}")
    return data
