"""Live compatibility profiles and runtime checks.

This module intentionally contains no imports from Live or third-party packages so
that it can be copied into Live's embedded Remote Script environment unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ableton_ctrl.adapter.manifest import LIVE_12_MANIFEST, TypeSpec

CompatibilityState = Literal["tested", "unverified", "unsupported"]
EditionSource = Literal["detection", "configuration", "unavailable"]

TESTED_LIVE_VERSIONS = frozenset({(12, 4, 2)})
SUPPORTED_MAJOR_VERSION = 12
# Live 12 uses its embedded CPython runtime. The adapter is deliberately limited
# to stdlib syntax and APIs available in this range.
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX_EXCLUSIVE = (3, 13)


@dataclass(frozen=True)
class CompatibilityProfile:
    state: CompatibilityState
    live_version: str
    manifest: dict[str, TypeSpec]
    enabled: bool
    reason: str


@dataclass(frozen=True)
class EditionInfo:
    name: str
    source: EditionSource


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def select_profile(
    version: tuple[int, int, int], *, allow_unverified: bool = False
) -> CompatibilityProfile:
    """Select the Live 12 profile without claiming untested builds are verified."""
    live_version = format_version(version)
    if version[0] != SUPPORTED_MAJOR_VERSION:
        return CompatibilityProfile(
            "unsupported",
            live_version,
            {},
            False,
            f"Live major version {version[0]} is unsupported.",
        )
    if version in TESTED_LIVE_VERSIONS:
        return CompatibilityProfile(
            "tested", live_version, LIVE_12_MANIFEST, True, "Release smoke target."
        )
    return CompatibilityProfile(
        "unverified",
        live_version,
        LIVE_12_MANIFEST,
        allow_unverified,
        (
            "Unverified Live 12 build enabled by explicit configuration."
            if allow_unverified
            else "Unverified Live 12 build requires allow_unverified_live=true."
        ),
    )


def resolve_edition(configured: str | None, detected: str | None = None) -> EditionInfo:
    """Return edition provenance; never guess an edition from the Live version."""
    if detected is not None and detected.strip():
        return EditionInfo(detected.strip(), "detection")
    if configured is not None and configured.strip():
        return EditionInfo(configured.strip(), "configuration")
    return EditionInfo("unknown", "unavailable")


def runtime_supported(version: tuple[int, int]) -> bool:
    return SUPPORTED_PYTHON_MIN <= version < SUPPORTED_PYTHON_MAX_EXCLUSIVE
