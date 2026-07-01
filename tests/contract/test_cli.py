import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from ableton_ctrl.bridge.server import BridgeServer
from ableton_ctrl.bridge.store import GraphStore

SECRET = "fixture-secret-that-is-at-least-forty-three-characters"
FIXTURE = Path("tests/fixtures/adapter/live-12.4.2-intro-basic.jsonl")


def run_cli(*args: str, config_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if config_dir is not None:
        env["ABLETON_CTRL_CONFIG_DIR"] = str(config_dir)
    return subprocess.run(
        [sys.executable, "-m", "ableton_ctrl.cli", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )


def stdout_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.stderr == ""
    return cast(dict[str, Any], json.loads(result.stdout))


@pytest.mark.parametrize(
    ("args", "code", "message", "recovery"),
    [
        (
            (),
            "invalid_invocation",
            "ableton-ctrl expects exactly one JSON argument.",
            "call_with_one_json_argument",
        ),
        (
            ("{}", "{}"),
            "invalid_invocation",
            "ableton-ctrl expects exactly one JSON argument.",
            "call_with_one_json_argument",
        ),
        (
            ("not-json",),
            "invalid_json",
            "ableton-ctrl argument must be a JSON object.",
            "pass_valid_json_object",
        ),
        (
            ("[]",),
            "invalid_json",
            "ableton-ctrl argument must be a JSON object.",
            "pass_valid_json_object",
        ),
    ],
)
def test_invalid_invocation_returns_structured_json_error(
    args: tuple[str, ...],
    code: str,
    message: str,
    recovery: str,
) -> None:
    result = run_cli(*args)

    assert result.returncode == 2
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": code,
            "message": message,
            "recovery": {"action": recovery},
        },
    }


def test_unknown_action_returns_structured_error() -> None:
    result = run_cli('{"action":"launch_clip"}')

    assert result.returncode == 2
    response = stdout_json(result)
    assert response["error"] == {
        "code": "unknown_action",
        "message": "Unknown ableton-ctrl action: launch_clip.",
        "recovery": {
            "action": "use_supported_action",
            "supported_actions": [
                "snapshot",
                "object",
                "children",
                "search",
                "schema",
                "changes",
                "resource",
            ],
        },
    }


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"action": "object"}, "object_id"),
        ({"action": "children", "relationship": "tracks", "revision": 1}, "object_id"),
        ({"action": "children", "object_id": "obj", "revision": 1}, "relationship"),
        ({"action": "children", "object_id": "obj", "relationship": "tracks"}, "revision"),
        ({"action": "resource"}, "name"),
    ],
)
def test_missing_required_action_fields_return_structured_error(
    payload: dict[str, Any],
    field_name: str,
) -> None:
    result = run_cli(json.dumps(payload))

    assert result.returncode == 2
    response = stdout_json(result)
    assert response["error"]["code"] == "validation_failed"
    assert response["error"]["message"] == f"Invalid fields for action '{payload['action']}'."
    assert response["error"]["recovery"] == {
        "action": "fix_action_fields",
        "details": [{"field": field_name, "reason": "Field required"}],
    }


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"action": "snapshot", "depth": 9}, "depth"),
        ({"action": "snapshot", "page_size": 0}, "page_size"),
        ({"action": "object", "object_id": ""}, "object_id"),
        ({"action": "object", "object_id": "   "}, "object_id"),
        (
            {"action": "children", "object_id": "obj", "relationship": "tracks", "revision": 0},
            "revision",
        ),
        (
            {"action": "children", "object_id": "   ", "relationship": "tracks", "revision": 1},
            "object_id",
        ),
        (
            {"action": "children", "object_id": "obj", "relationship": "   ", "revision": 1},
            "relationship",
        ),
        (
            {
                "action": "children",
                "object_id": "obj",
                "relationship": "tracks",
                "revision": 1,
                "start_index": -1,
            },
            "offset",
        ),
        (
            {
                "action": "children",
                "object_id": "obj",
                "relationship": "tracks",
                "revision": 1,
                "page_size": 0,
            },
            "limit",
        ),
        (
            {
                "action": "children",
                "object_id": "obj",
                "relationship": "tracks",
                "revision": 1,
                "limit": 201,
            },
            "limit",
        ),
        ({"action": "search", "name": "x" * 257}, "name"),
        ({"action": "search", "start_index": -1}, "offset"),
        ({"action": "search", "page_size": 0}, "limit"),
        ({"action": "search", "limit": 201}, "limit"),
        ({"action": "search", "object_type": 12}, "object_type"),
        ({"action": "search", "path": 12}, "path"),
        ({"action": "changes", "session_id": "s1", "after_revision": -1}, "after_revision"),
        ({"action": "changes", "session_id": "s1", "after_revision": 0, "limit": 501}, "limit"),
    ],
)
def test_invalid_action_bounds_return_structured_error(
    payload: dict[str, Any], field_name: str
) -> None:
    result = run_cli(json.dumps(payload))

    assert result.returncode == 2
    response = stdout_json(result)
    assert response["error"]["code"] == "validation_failed"
    assert response["error"]["message"] == f"Invalid fields for action '{payload['action']}'."
    assert response["error"]["recovery"]["action"] == "fix_action_fields"
    assert response["error"]["recovery"]["details"][0]["field"] == field_name


def test_pyproject_registers_ableton_ctrl_console_script() -> None:
    import tomllib

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["ableton-ctrl"] == "ableton_ctrl.cli:main"


def test_valid_snapshot_dispatch_uses_existing_bridge_client_error(tmp_path: Path) -> None:
    result = run_cli('{"action":"snapshot","depth":1,"page_size":20}', config_dir=tmp_path)

    assert result.returncode == 0
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "bridge_unavailable",
            "message": "The local Ableton bridge is unavailable.",
            "recovery": {"action": "start_or_restart_bridge"},
        },
    }


def test_valid_object_dispatch_uses_existing_bridge_client_error(tmp_path: Path) -> None:
    result = run_cli('{"action":"object","object_id":"obj-1"}', config_dir=tmp_path)

    assert result.returncode == 0
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "bridge_unavailable",
            "message": "The local Ableton bridge is unavailable.",
            "recovery": {"action": "start_or_restart_bridge"},
        },
    }


def test_valid_search_dispatch_uses_existing_bridge_client_error(tmp_path: Path) -> None:
    result = run_cli('{"action":"search","name":"track"}', config_dir=tmp_path)

    assert result.returncode == 0
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "bridge_unavailable",
            "message": "The local Ableton bridge is unavailable.",
            "recovery": {"action": "start_or_restart_bridge"},
        },
    }


def test_valid_schema_dispatch_uses_existing_bridge_client_error(tmp_path: Path) -> None:
    result = run_cli('{"action":"schema"}', config_dir=tmp_path)

    assert result.returncode == 0
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "bridge_unavailable",
            "message": "The local Ableton bridge is unavailable.",
            "recovery": {"action": "start_or_restart_bridge"},
        },
    }


def test_resource_cli_returns_all_expected_learning_metadata_without_bridge(
    tmp_path: Path,
) -> None:
    responses = {
        name: stdout_json(
            run_cli(json.dumps({"action": "resource", "name": name}), config_dir=tmp_path)
        )
        for name in ("glossary", "interpretation", "limitations")
    }

    for name, response in responses.items():
        assert response["ok"] is True
        assert response["completeness"] == "complete"
        assert response["result"]["kind"] == "resource"
        assert response["result"]["name"] == name
        assert response["result"]["resource"]["source_kind"] == "learning_metadata"

    glossary = responses["glossary"]["result"]["resource"]
    assert {entry["term"] for entry in glossary["entries"]} == {
        "Live Set",
        "Session View",
        "Arrangement View",
        "scene",
        "track",
        "return track",
        "master track",
        "clip slot",
        "audio clip",
        "MIDI clip",
        "device",
        "device parameter",
        "mixer",
        "routing",
        "automation",
        "selection",
        "beat time",
        "decibel",
        "normalized parameter",
        "revision",
        "capture time",
        "completeness",
    }

    interpretation = responses["interpretation"]["result"]["resource"]
    assert {entry["term"] for entry in interpretation["entries"]} == {
        "revision",
        "capture time",
        "completeness",
        "read outcome",
        "object type",
        "property",
        "relationship",
    }

    limitations = responses["limitations"]["result"]["resource"]
    assert limitations["target"] == {
        "product": "Ableton Live Intro",
        "version": "12.4.2",
    }
    limitation_text = " ".join(limitations["limitations"]).casefold()
    for phrase in (
        "undocumented",
        "max for live",
        "runtime discovery",
        "raw audio",
        "raw midi",
        "coverage report",
    ):
        assert phrase in limitation_text


def test_resource_cli_returns_structured_error_for_unknown_resource(tmp_path: Path) -> None:
    result = run_cli('{"action":"resource","name":"not-a-resource"}', config_dir=tmp_path)

    assert result.returncode == 2
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "validation_failed",
            "message": "Unknown ableton-ctrl resource: not-a-resource.",
            "recovery": {
                "action": "choose_supported_resource",
                "supported_resources": ["glossary", "interpretation", "limitations"],
            },
        },
    }


async def test_children_cli_paginates_fixture_relationship_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge, fixture_batch_with_second_track())
    root_id = bridge.store.snapshot(depth=0, page_size=20).root.object_id
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps(
                {
                    "action": "children",
                    "object_id": root_id,
                    "relationship": "tracks",
                    "revision": 1,
                    "start_index": 0,
                    "page_size": 1,
                }
            ),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] == "partial"
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert response["result"]["kind"] == "list_children"
    assert response["result"]["items"] == [
        {
            "object_id": response["result"]["items"][0]["object_id"],
            "type": "Track",
            "path": "Live Set/Track 1",
        }
    ]
    assert response["result"]["continuation"] == "1:1"


async def test_search_cli_filters_fixture_objects_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge, fixture_batch_with_second_track())
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps(
                {
                    "action": "search",
                    "name": "track",
                    "object_type": "Track",
                    "path": "Live Set",
                    "start_index": 0,
                    "page_size": 1,
                }
            ),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] == "partial"
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert response["result"]["kind"] == "search"
    assert response["result"]["items"] == [
        {
            "object_id": response["result"]["items"][0]["object_id"],
            "type": "Track",
            "path": "Live Set/Track 1",
        }
    ]
    assert response["result"]["continuation"] == "1:1"


async def test_schema_cli_returns_unfiltered_runtime_metadata(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "schema"}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] in {"complete", "partial"}
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert response["result"]["kind"] == "schema"
    assert [item["normalized_type"] for item in response["result"]["types"]] == ["song", "track"]
    track = response["result"]["types"][1]
    assert track["type"] == "Track"
    assert track["object_count"] == 1
    assert track["members"] == [
        {
            "name": "name",
            "kind": "property",
            "runtime_available": True,
            "observed_count": 1,
            "unavailable_count": 0,
            "read_failed_count": 0,
            "excluded_count": 0,
            "manifest_metadata": None,
        }
    ]


async def test_schema_cli_filters_by_object_type_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "schema", "object_type": "Track"}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] in {"complete", "partial"}
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert response["result"]["kind"] == "schema"
    assert [item["normalized_type"] for item in response["result"]["types"]] == ["track"]
    assert response["result"]["types"][0]["members"][0]["name"] == "name"
    assert response["result"]["types"][0]["members"][0]["runtime_available"] is True


async def test_children_cli_invalid_revision_preserves_bridge_error(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    root_id = bridge.store.snapshot(depth=0, page_size=20).root.object_id
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps(
                {
                    "action": "children",
                    "object_id": root_id,
                    "relationship": "tracks",
                    "revision": 999,
                }
            ),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is False
    assert response["completeness"] == "unavailable"
    assert response["error"]["code"] == "stale_cursor"


async def test_object_cli_fetches_fixture_object_with_existing_query_metadata(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    root_id = bridge.store.snapshot(depth=0, page_size=20).root.object_id
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "object", "object_id": root_id}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] in {"complete", "partial"}
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert response["result"]["kind"] == "get_object"
    fetched = response["result"]["object"]
    assert fetched["object_id"] == root_id
    assert fetched["properties"] == {"tempo": 120.0}
    assert "tracks" in fetched["relationships"]
    assert fetched["outcomes"] == []


async def test_snapshot_cli_queries_fixture_and_preserves_metadata(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    try:
        result = await asyncio.to_thread(
            run_cli,
            '{"action":"snapshot","depth":1,"page_size":1}',
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["live_version"] == "12.4.2"
    assert response["session_id"] == "s1"
    assert response["bridge_revision"] == 1
    assert response["completeness"] in {"complete", "partial"}
    assert response["cache_age_seconds"] >= 0
    assert response["captured_at"] == response["result"]["captured_at"]
    assert response["bridge_revision"] == response["result"]["bridge_revision"]
    assert len(response["result"]["root"]["relationships"]["tracks"]["items"]) <= 1


async def test_snapshot_cli_preserves_adapter_runtime_metadata(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    reader, adapter = await apply_fixture(bridge)
    terminal = fixture_batch()
    terminal.update(
        {
            "observations": [],
            "removed_source_ids": [],
            "discovery_complete": False,
            "runtime_outcome": "partial_result",
            "runtime_action": "reduce_observation_size_or_capacity",
        }
    )
    await send_update(reader, adapter, terminal, expected_revision=2)
    try:
        result = await asyncio.to_thread(run_cli, '{"action":"snapshot"}', config_dir=tmp_path)
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response["ok"] is True
    assert response["result"]["adapter_runtime"] == {
        "outcome": "partial_result",
        "action": "reduce_observation_size_or_capacity",
        "recovery": (
            "Reduce the observed graph or adapter capacity pressure, then reload "
            "or restart the ableton-ctrl Ableton Remote Script."
        ),
    }


async def test_changes_cli_persists_implicit_cursor_across_processes(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    reader, adapter = await apply_fixture(bridge, named_fixture_batch("Cursor Test Set"))
    try:
        first = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
        changed = named_fixture_batch("Cursor Test Set")
        changed["observations"][1]["properties"] = {"name": "Renamed Track"}
        await send_update(reader, adapter, changed, expected_revision=2)
        second = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
        third = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert first.returncode == 0
    first_response = stdout_json(first)
    assert first_response["ok"] is True
    assert [item["revision"] for item in first_response["result"]["changes"]] == [1]
    assert first_response["result"]["next_revision"] == 1

    assert second.returncode == 0
    second_response = stdout_json(second)
    assert second_response["ok"] is True
    assert [item["revision"] for item in second_response["result"]["changes"]] == [2]
    assert second_response["result"]["next_revision"] == 2

    assert third.returncode == 0
    third_response = stdout_json(third)
    assert third_response["ok"] is True
    assert third_response["result"]["changes"] == []
    assert third_response["result"]["next_revision"] == 2


async def test_changes_cli_implicit_cursors_are_keyed_by_set_name_only(tmp_path: Path) -> None:
    first_bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await first_bridge.start()
    write_config(tmp_path, first_bridge.port)
    _first_reader, first_adapter = await apply_fixture(first_bridge, named_fixture_batch("Set A"))
    try:
        first = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
    finally:
        first_adapter.close()
        await first_adapter.wait_closed()
        await first_bridge.close()

    second_bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await second_bridge.start()
    write_config(tmp_path, second_bridge.port)
    _second_reader, second_adapter = await apply_fixture(
        second_bridge, named_fixture_batch("Set B")
    )
    try:
        second = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
    finally:
        second_adapter.close()
        await second_adapter.wait_closed()
        await second_bridge.close()

    assert stdout_json(first)["result"]["next_revision"] == 1
    second_response = stdout_json(second)
    assert second_response["ok"] is True
    assert [item["revision"] for item in second_response["result"]["changes"]] == [1]
    cursor_files = sorted((tmp_path / "cursors" / "changes").glob("*.json"))
    assert [path.name for path in cursor_files] == ["Set%20A.json", "Set%20B.json"]


async def test_changes_cli_missing_set_name_returns_structured_error_without_cursor(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge)
    try:
        result = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    assert result.returncode == 0
    response = stdout_json(result)
    assert response == {
        "protocol_version": 1,
        "ok": False,
        "completeness": "unavailable",
        "error": {
            "code": "stale_state",
            "message": "The current Ableton Live Set name could not be determined.",
            "recovery": {"action": "save_or_name_current_live_set"},
        },
    }
    assert not (tmp_path / "cursors").exists()


async def test_changes_cli_explicit_after_revision_is_nonmutating(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _reader, adapter = await apply_fixture(bridge, named_fixture_batch("Explicit Set"))
    try:
        explicit = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes", "session_id": "s1", "after_revision": 0}),
            config_dir=tmp_path,
        )
        explicit_cursor_exists = (tmp_path / "cursors").exists()
        implicit = await asyncio.to_thread(
            run_cli,
            json.dumps({"action": "changes"}),
            config_dir=tmp_path,
        )
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()

    explicit_response = stdout_json(explicit)
    assert explicit_response["ok"] is True
    assert [item["revision"] for item in explicit_response["result"]["changes"]] == [1]
    assert explicit_cursor_exists is False

    implicit_response = stdout_json(implicit)
    assert implicit_response["ok"] is True
    assert [item["revision"] for item in implicit_response["result"]["changes"]] == [1]
    assert (tmp_path / "cursors" / "changes" / "Explicit%20Set.json").exists()


async def apply_fixture(
    bridge: BridgeServer,
    batch: dict[str, Any] | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", bridge.port)
    hello = {
        "protocol_version": 1,
        "role": "adapter",
        "secret": SECRET,
        "message": {"kind": "hello", "session_id": "s1", "live_version": "12.4.2"},
    }
    writer.write(json.dumps(hello).encode() + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["ok"] is True
    await send_update(
        reader, writer, fixture_batch() if batch is None else batch, expected_revision=1
    )
    return reader, writer


def fixture_batch() -> dict[str, Any]:
    batch: dict[str, Any] = json.loads(FIXTURE.read_text())
    batch["session_id"] = "s1"
    return batch


def named_fixture_batch(set_name: str) -> dict[str, Any]:
    batch = fixture_batch()
    batch["observations"][0]["properties"]["name"] = set_name
    return batch


def fixture_batch_with_second_track() -> dict[str, Any]:
    batch = fixture_batch()
    batch["observations"][0]["relationships"]["tracks"].append("track:2")
    second_track = dict(batch["observations"][1])
    second_track.update(
        {
            "source_id": "track:2",
            "path": "Live Set/Track 2",
            "properties": {"name": "Track 2"},
        }
    )
    batch["observations"].append(second_track)
    return batch


async def send_update(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    batch: dict[str, Any],
    *,
    expected_revision: int,
) -> None:
    writer.write(json.dumps({"kind": "update", "batch": batch}).encode() + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["bridge_revision"] == expected_revision


def write_config(directory: Path, port: int) -> None:
    (directory / "config.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": port, "secret": SECRET})
    )
