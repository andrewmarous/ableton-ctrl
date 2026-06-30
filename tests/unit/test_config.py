import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

import ableton_ctrl.config as config_module
from ableton_ctrl.config import BridgeConfig, load_or_create_config


def test_config_is_private_and_reused(tmp_path) -> None:
    first = load_or_create_config(tmp_path)
    second = load_or_create_config(tmp_path)
    assert first.secret == second.secret
    assert first.host == "127.0.0.1"
    assert len(first.secret) >= 43
    assert (tmp_path / "config.json").stat().st_mode & 0o077 == 0


def test_config_rejects_non_loopback_host() -> None:
    with pytest.raises(ValidationError):
        BridgeConfig(host="0.0.0.0", secret="x" * 43)


@pytest.mark.parametrize("port", [0, 65536])
def test_config_rejects_out_of_range_port(port) -> None:
    with pytest.raises(ValidationError):
        BridgeConfig(port=port, secret="x" * 43)


def test_config_rejects_weak_secret() -> None:
    with pytest.raises(ValidationError):
        BridgeConfig(secret="too-short")


def test_existing_config_permissions_are_repaired(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    secret = "x" * 43
    config_path.write_text(json.dumps({"secret": secret}))
    config_path.chmod(0o644)

    config = load_or_create_config(tmp_path)

    assert config.secret == secret
    assert config_path.stat().st_mode & 0o077 == 0


def test_concurrent_config_creation_converges_on_persisted_secret(tmp_path) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        configs = list(executor.map(lambda _: load_or_create_config(tmp_path), range(16)))

    persisted = load_or_create_config(tmp_path)
    assert {config.secret for config in configs} == {persisted.secret}


def test_failed_config_write_cleans_temporary_files(tmp_path, monkeypatch) -> None:
    def fail_fsync(_file_descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(config_module.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        load_or_create_config(tmp_path)

    assert {path.name for path in tmp_path.iterdir()} <= {".config.lock"}


def test_stale_lock_file_does_not_block_config_creation(tmp_path) -> None:
    (tmp_path / ".config.lock").touch(mode=0o600)

    config = load_or_create_config(tmp_path)

    assert load_or_create_config(tmp_path).secret == config.secret


@pytest.mark.parametrize("operation", ["fchmod", "flock"])
def test_lock_descriptor_closes_when_lock_setup_fails(
    tmp_path, monkeypatch, operation: str
) -> None:
    real_close = config_module.os.close
    closed: list[int] = []

    def recording_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    def fail(*_args: object) -> None:
        raise OSError("lock setup failed")

    monkeypatch.setattr(config_module.os, "close", recording_close)
    if operation == "fchmod":
        monkeypatch.setattr(config_module.os, "fchmod", fail)
    else:
        monkeypatch.setattr(config_module.fcntl, "flock", fail)
    with pytest.raises(OSError, match="lock setup failed"):
        load_or_create_config(tmp_path)
    assert len(closed) == 1
