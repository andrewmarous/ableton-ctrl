import importlib.util
import json
import math
import stat
import sys
import types
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ableton_ctrl.adapter.manifest import LIVE_12_4_2_INTRO_MANIFEST


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [
        {
            "kind": "run",
            "live_version": "12.4.2",
            "edition": "Intro",
            "discovery_complete": True,
            "max_tick_duration_ms": 4.0,
            "p95_tick_duration_ms": 2.5,
        }
    ]
    for type_name, type_spec in LIVE_12_4_2_INTRO_MANIFEST.items():
        for member in (*type_spec.properties, *type_spec.relationships):
            record: dict[str, Any] = {
                "kind": "member",
                "object_type": type_name,
                "member": member.name,
                "status": "supported",
            }
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_complete_report_is_deterministic(tmp_path: Path) -> None:
    smoke = load_script("live_smoke")
    source = tmp_path / "coverage.jsonl"
    output = tmp_path / "report"
    write_jsonl(source, reversed_copy(complete_records()))

    first = smoke.validate_and_write(source, output)
    first_json = (output / "coverage.json").read_bytes()
    first_markdown = (output / "coverage.md").read_bytes()
    second = smoke.validate_and_write(source, output)

    assert first == second
    assert first_json == (output / "coverage.json").read_bytes()
    assert first_markdown == (output / "coverage.md").read_bytes()
    assert first["summary"]["total"] == sum(
        len(spec.properties) + len(spec.relationships)
        for spec in LIVE_12_4_2_INTRO_MANIFEST.values()
    )
    assert "# Live 12.4.2 Intro coverage" in first_markdown.decode()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows.pop(), "missing manifest member"),
        (lambda rows: rows.append(rows[-1].copy()), "duplicate manifest member"),
        (lambda rows: rows[-1].update(status="maybe"), "invalid status"),
        (
            lambda rows: rows[-1].update(status="read_failed"),
            "requires a reason",
        ),
        (lambda rows: rows[0].update(live_version="12.4.1"), "requires Live 12.4.2"),
        (lambda rows: rows[0].update(max_tick_duration_ms=4.01), "exceeds 4 ms"),
    ],
)
def test_invalid_coverage_is_rejected(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    smoke = load_script("live_smoke")
    rows = complete_records()
    mutate(rows)
    source = tmp_path / "coverage.jsonl"
    write_jsonl(source, rows)

    with pytest.raises(smoke.CoverageValidationError, match=message):
        smoke.validate_and_write(source, tmp_path / "report")


def test_absent_reason_for_excluded_is_rejected(tmp_path: Path) -> None:
    smoke = load_script("live_smoke")
    rows = complete_records()
    rows[-1]["status"] = "excluded"
    source = tmp_path / "coverage.jsonl"
    write_jsonl(source, rows)

    with pytest.raises(smoke.CoverageValidationError, match="requires a reason"):
        smoke.validate_and_write(source, tmp_path / "report")


def test_incomplete_discovery_is_rejected(tmp_path: Path) -> None:
    smoke = load_script("live_smoke")
    rows = complete_records()
    rows[0]["discovery_complete"] = False
    source = tmp_path / "coverage.jsonl"
    write_jsonl(source, rows)

    with pytest.raises(smoke.CoverageValidationError, match="discovery did not complete"):
        smoke.validate_and_write(source, tmp_path / "report")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_tick_duration_ms", True),
        ("max_tick_duration_ms", -0.1),
        ("max_tick_duration_ms", math.nan),
        ("max_tick_duration_ms", math.inf),
        ("p95_tick_duration_ms", False),
        ("p95_tick_duration_ms", -0.1),
        ("p95_tick_duration_ms", math.nan),
        ("p95_tick_duration_ms", -math.inf),
    ],
)
def test_tick_timings_require_finite_nonnegative_reals(
    tmp_path: Path, field: str, value: object
) -> None:
    smoke = load_script("live_smoke")
    rows = complete_records()
    rows[0][field] = value
    source = tmp_path / "coverage.jsonl"
    write_jsonl(source, rows)

    message = "invalid JSON" if isinstance(value, float) and not math.isfinite(value) else field
    with pytest.raises(smoke.CoverageValidationError, match=message):
        smoke.validate_and_write(source, tmp_path / "report")


def test_nonstandard_json_numbers_are_rejected(tmp_path: Path) -> None:
    smoke = load_script("live_smoke")
    source = tmp_path / "coverage.jsonl"
    source.write_text('{"kind":"run","max_tick_duration_ms":NaN}\n')

    with pytest.raises(smoke.CoverageValidationError, match="invalid JSON"):
        smoke.validate_and_write(source, tmp_path / "report")


def test_installer_is_marker_protected_and_keeps_secret_private(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    installer = load_script("install_remote_script")
    home = tmp_path / "home"
    destination = home / "Music" / "Ableton" / "User Library" / "Remote Scripts" / "AbletonCtrl"
    secret = "fixture-secret-that-is-at-least-forty-three-characters"
    installed = installer.install(home=home, system="Darwin", secret=secret)

    assert installed == destination
    assert (destination / ".ableton-ctrl-managed").is_file()
    assert (destination / "adapter").is_dir()
    assert {path.name for path in destination.iterdir()} == {
        ".ableton-ctrl-managed",
        "__init__.py",
        "adapter",
        "config.py",
        "config.json",
        "contracts.py",
    }
    assert stat.S_IMODE((destination / "config.json").stat().st_mode) == 0o600
    assert secret not in capsys.readouterr().out

    installer.install(home=home, system="Darwin", secret=secret)
    assert secret not in capsys.readouterr().out


def test_installer_refuses_non_macos_and_unmanaged_destination(tmp_path: Path) -> None:
    installer = load_script("install_remote_script")
    with pytest.raises(installer.InstallError, match="macOS"):
        installer.install(home=tmp_path, system="Linux", secret="x" * 43)

    destination = tmp_path / "Music" / "Ableton" / "User Library" / "Remote Scripts" / "AbletonCtrl"
    destination.mkdir(parents=True)
    (destination / "user-file.txt").write_text("preserve")
    with pytest.raises(installer.InstallError, match="not managed"):
        installer.install(home=tmp_path, system="Darwin", secret="x" * 43)
    assert (destination / "user-file.txt").read_text() == "preserve"


def test_installer_rolls_back_prior_install_when_replacement_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_script("install_remote_script")
    home = tmp_path / "home"
    destination = home / installer.REMOTE_SCRIPT_RELATIVE
    destination.mkdir(parents=True)
    (destination / installer.MARKER).write_text("managed\n")
    (destination / "prior.txt").write_text("prior install")

    def fail_replacement(staging: Path, target: Path) -> None:
        raise OSError("forced replacement failure")

    monkeypatch.setattr(installer, "_activate_staging", fail_replacement)
    with pytest.raises(OSError, match="forced replacement failure"):
        installer.install(home=home, system="Darwin", secret="x" * 43)

    assert (destination / "prior.txt").read_text() == "prior install"
    assert (destination / installer.MARKER).is_file()


def test_installer_recovers_orphan_backup_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_script("install_remote_script")
    home = tmp_path / "home"
    destination = home / installer.REMOTE_SCRIPT_RELATIVE
    backup = destination.with_name(f".{destination.name}.backup")
    backup.mkdir(parents=True)
    (backup / installer.MARKER).write_text("managed\n")
    (backup / "prior.txt").write_text("last known good")

    monkeypatch.setattr(
        installer,
        "_activate_staging",
        lambda staging, target: (_ for _ in ()).throw(OSError("forced failure")),
    )
    with pytest.raises(OSError, match="forced failure"):
        installer.install(home=home, system="Darwin", secret="x" * 43)

    assert (destination / "prior.txt").read_text() == "last known good"
    assert not backup.exists()


def test_installer_reconciles_completed_swap_with_orphan_backup(tmp_path: Path) -> None:
    installer = load_script("install_remote_script")
    home = tmp_path / "home"
    destination = home / installer.REMOTE_SCRIPT_RELATIVE
    backup = destination.with_name(f".{destination.name}.backup")
    destination.mkdir(parents=True)
    (destination / installer.MARKER).write_text("managed\n")
    (destination / "current.txt").write_text("current")
    backup.mkdir()
    (backup / installer.MARKER).write_text("managed\n")
    (backup / "older.txt").write_text("older")

    installer.install(home=home, system="Darwin", secret="x" * 43)

    assert destination.is_dir()
    assert (destination / installer.MARKER).is_file()
    assert not backup.exists()


def test_installer_refuses_unmanaged_orphan_backup(tmp_path: Path) -> None:
    installer = load_script("install_remote_script")
    home = tmp_path / "home"
    destination = home / installer.REMOTE_SCRIPT_RELATIVE
    backup = destination.with_name(f".{destination.name}.backup")
    backup.mkdir(parents=True)
    (backup / "user-file.txt").write_text("preserve")

    with pytest.raises(installer.InstallError, match="backup is not managed"):
        installer.install(home=home, system="Darwin", secret="x" * 43)

    assert (backup / "user-file.txt").read_text() == "preserve"


def test_installed_tree_imports_without_third_party_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = load_script("install_remote_script")
    destination = installer.install(
        home=tmp_path / "home",
        system="Darwin",
        secret="x" * 43,
    )

    framework = types.ModuleType("_Framework")
    control_surface_module = types.ModuleType("_Framework.ControlSurface")

    class ControlSurface:
        def __init__(self, c_instance: object) -> None:
            self._c_instance = c_instance

        def application(self) -> object:
            return types.SimpleNamespace(
                get_major_version=lambda: 12,
                get_minor_version=lambda: 4,
                get_bugfix_version=lambda: 2,
                get_product_name=lambda: "Live Intro",
            )

        def song(self) -> object:
            return types.SimpleNamespace(name="Fixture")

        def disconnect(self) -> None:
            return None

    control_surface_module.ControlSurface = ControlSurface
    monkeypatch.setitem(sys.modules, "_Framework", framework)
    monkeypatch.setitem(sys.modules, "_Framework.ControlSurface", control_surface_module)
    for name in tuple(sys.modules):
        if name == "AbletonCtrl" or name.startswith("AbletonCtrl."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    original_import = __import__

    def isolated_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "pydantic" or name.startswith("pydantic."):
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", isolated_import)
    spec = importlib.util.spec_from_file_location(
        "AbletonCtrl",
        destination / "__init__.py",
        submodule_search_locations=[str(destination)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["AbletonCtrl"] = module
    spec.loader.exec_module(module)

    assert callable(module.create_instance)


def reversed_copy(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [records[0], *reversed(records[1:])]
