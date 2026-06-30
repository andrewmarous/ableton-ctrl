#!/usr/bin/env python3
"""Install the managed AbletonCtrl Remote Script on macOS."""

from __future__ import annotations

import json
import platform
import secrets
import shutil
from pathlib import Path
from typing import Literal

from ableton_ctrl.config import BridgeConfig, load_or_create_config

MARKER = ".ableton-ctrl-managed"
REMOTE_SCRIPT_RELATIVE = Path("Music/Ableton/User Library/Remote Scripts/AbletonCtrl")
PREFERENCES_STEP = (
    "In Live, open Preferences > Link, Tempo & MIDI and select AbletonCtrl as a Control Surface."
)


class InstallError(RuntimeError):
    """The installation cannot be performed safely."""


def _activate_staging(staging: Path, destination: Path) -> None:
    staging.replace(destination)


def _reconcile_backup(destination: Path, backup: Path) -> None:
    if not backup.exists():
        return
    if not (backup / MARKER).is_file():
        raise InstallError(f"refusing recovery because backup is not managed: {backup}")
    if not destination.exists():
        backup.replace(destination)
        return
    if not (destination / MARKER).is_file():
        raise InstallError(
            f"refusing recovery with unmanaged destination and managed backup: {destination}"
        )
    shutil.rmtree(backup)


def install(
    *,
    home: Path | None = None,
    system: str | None = None,
    secret: str | None = None,
    host: Literal["127.0.0.1"] = "127.0.0.1",
    port: int = 8765,
) -> Path:
    """Install into a home directory, refusing unmanaged replacement."""
    if (system or platform.system()) != "Darwin":
        raise InstallError("Ableton Remote Script installation is supported only on macOS")

    user_home = home or Path.home()
    destination = user_home / REMOTE_SCRIPT_RELATIVE
    backup = destination.with_name(f".{destination.name}.backup")
    _reconcile_backup(destination, backup)
    if destination.exists() and not (destination / MARKER).is_file():
        raise InstallError(
            f"refusing to overwrite directory not managed by ableton-ctrl: {destination}"
        )

    source = Path(__file__).resolve().parents[1] / "src" / "ableton_ctrl"
    config_directory = user_home / "Library" / "Application Support" / "ableton-ctrl"
    if secret is None and host == "127.0.0.1" and port == 8765:
        config = load_or_create_config(config_directory)
    else:
        config = BridgeConfig(host=host, port=port, secret=secret or secrets.token_urlsafe(32))
        config_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        shared_config = config_directory / "config.json"
        shared_config.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
        shared_config.chmod(0o600)
    staging = destination.with_name(f".{destination.name}.installing")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(mode=0o700, parents=True)

    try:
        shutil.copytree(
            source / "adapter",
            staging / "adapter",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (staging / "contracts.py").write_text(
            '"""Compatibility exports for the stdlib-only installed runtime."""\n'
            "from .adapter.models import JsonScalar, JsonValue, MemberOutcome, ObjectObservation\n"
        )
        (staging / "config.py").write_text(
            '"""Private stdlib-only configuration loader for Ableton Live."""\n'
            "import json\n"
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n\n"
            "@dataclass(frozen=True)\n"
            "class BridgeConfig:\n"
            "    host: str\n"
            "    port: int\n"
            "    secret: str\n\n"
            "def load_or_create_config(directory=None):\n"
            "    path = Path(__file__).with_name('config.json')\n"
            "    value = json.loads(path.read_text())\n"
            "    return BridgeConfig(value['host'], value['port'], value['secret'])\n"
        )
        (staging / "__init__.py").write_text(
            '"""AbletonCtrl Remote Script entrypoint."""\n'
            "import sys\n"
            'sys.modules.setdefault("ableton_ctrl", sys.modules[__name__])\n'
            "from .adapter.remote_script import create_instance\n"
            '__all__ = ["create_instance"]\n'
        )
        (staging / MARKER).write_text("managed by ableton-ctrl\n")
        config_path = staging / "config.json"
        config_path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
        config_path.chmod(0o600)

        had_destination = destination.exists()
        if had_destination:
            destination.replace(backup)
        try:
            _activate_staging(staging, destination)
        except BaseException:
            if had_destination and backup.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(f"Installed AbletonCtrl Remote Script at {destination}")
    print(PREFERENCES_STEP)
    return destination


def main() -> int:
    try:
        install()
    except InstallError as exc:
        print(f"Installation refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
