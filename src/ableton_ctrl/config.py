"""Private, user-local bridge configuration."""

import fcntl
import json
import os
import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_DIRECTORY = Path.home() / "Library" / "Application Support" / "ableton-ctrl"


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    secret: str = Field(min_length=43)


def _write_all(file_descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(file_descriptor, view)
        view = view[written:]


def _load_private_config(config_path: Path) -> BridgeConfig:
    config_path.chmod(0o600)
    return BridgeConfig.model_validate_json(config_path.read_bytes())


def load_or_create_config(directory: Path | None = None) -> BridgeConfig:
    """Load the bridge config, creating it atomically with private permissions."""

    config_directory = directory or DEFAULT_CONFIG_DIRECTORY
    config_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = config_directory / "config.json"

    if config_path.exists():
        return _load_private_config(config_path)

    lock_path = config_directory / ".config.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(lock_descriptor, 0o600)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        if config_path.exists():
            return _load_private_config(config_path)

        config = BridgeConfig(secret=secrets.token_urlsafe(32))
        temporary_path = config_directory / f".config.{secrets.token_hex(8)}.tmp"
        temporary_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        file_descriptor = os.open(temporary_path, temporary_flags, 0o600)
        try:
            data = json.dumps(config.model_dump(), indent=2).encode() + b"\n"
            _write_all(file_descriptor, data)
            os.fsync(file_descriptor)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            os.close(file_descriptor)

        try:
            os.replace(temporary_path, config_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

        return _load_private_config(config_path)
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)
