"""Private stdlib-only configuration loader for Ableton Live."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    port: int
    secret: str
    edition: str | None = None
    allow_unverified_live: bool = False


def load_or_create_config(directory: Any = None) -> BridgeConfig:
    path = Path(__file__).with_name("config.json")
    value = json.loads(path.read_text())
    return BridgeConfig(
        value["host"],
        value["port"],
        value["secret"],
        value.get("edition"),
        value.get("allow_unverified_live", False),
    )
