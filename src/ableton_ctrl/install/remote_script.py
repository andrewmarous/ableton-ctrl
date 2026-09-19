"""Safe installer for the packaged AbletonCtrl Remote Script."""

from __future__ import annotations

import json
import platform
import secrets
import shutil
from importlib import resources
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


def _copy_template(destination: Path) -> None:
    template = resources.files("ableton_ctrl").joinpath("install/templates/remote_script")
    with resources.as_file(template) as source:
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _restore(destination: Path, backup: Path) -> None:
    if not backup.exists():
        return
    if not (backup / MARKER).is_file():
        raise InstallError(f"refusing recovery because backup is not managed: {backup}")
    if not destination.exists():
        backup.replace(destination)
    elif (destination / MARKER).is_file():
        shutil.rmtree(backup)
    else:
        raise InstallError(f"refusing recovery with unmanaged destination: {destination}")


def install(
    *,
    home: Path | None = None,
    system: str | None = None,
    secret: str | None = None,
    host: Literal["127.0.0.1"] = "127.0.0.1",
    port: int = 8765,
    dry_run: bool = False,
) -> Path:
    """Stage and atomically install the managed script without overwriting users' files."""
    if (system or platform.system()) != "Darwin":
        raise InstallError("Ableton Remote Script installation is supported only on macOS")
    root = home or Path.home()
    destination = root / REMOTE_SCRIPT_RELATIVE
    backup = destination.with_name(f".{destination.name}.backup")
    _restore(destination, backup)
    if destination.exists() and not (destination / MARKER).is_file():
        raise InstallError(
            f"refusing to overwrite directory not managed by ableton-ctrl: {destination}"
        )
    if dry_run:
        return destination

    config_directory = root / "Library/Application Support/ableton-ctrl"
    if secret is None and host == "127.0.0.1" and port == 8765:
        config = load_or_create_config(config_directory)
    else:
        config = BridgeConfig(host=host, port=port, secret=secret or secrets.token_urlsafe(32))
        config_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = config_directory / "config.json"
        path.write_text(json.dumps(config.model_dump(), indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)

    staging = destination.with_name(f".{destination.name}.installing")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _copy_template(staging)
        (staging / MARKER).write_text("managed by ableton-ctrl\n", encoding="utf-8")
        config_path = staging / "config.json"
        config_path.write_text(json.dumps(config.model_dump(), indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
        had_destination = destination.exists()
        if had_destination:
            destination.replace(backup)
        try:
            staging.replace(destination)
        except BaseException:
            if had_destination and backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination
