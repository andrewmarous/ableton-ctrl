import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


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
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("args", "code", "message", "recovery"),
    [
        ((), "invalid_invocation", "ableton-ctrl expects exactly one JSON argument.", "call_with_one_json_argument"),
        (("{}", "{}"), "invalid_invocation", "ableton-ctrl expects exactly one JSON argument.", "call_with_one_json_argument"),
        (("not-json",), "invalid_json", "ableton-ctrl argument must be a JSON object.", "pass_valid_json_object"),
        (("[]",), "invalid_json", "ableton-ctrl argument must be a JSON object.", "pass_valid_json_object"),
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
            "supported_actions": ["snapshot", "object", "children", "search", "schema", "changes"],
        },
    }


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"action": "object"}, "object_id"),
        ({"action": "children", "object_id": "obj", "relationship": "tracks"}, "revision"),
        ({"action": "changes", "session_id": "s1"}, "after_revision"),
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
        ({"action": "children", "object_id": "obj", "relationship": "tracks", "revision": 0}, "revision"),
        ({"action": "children", "object_id": "obj", "relationship": "tracks", "revision": 1, "limit": 201}, "limit"),
        ({"action": "search", "name": "x" * 257}, "name"),
        ({"action": "changes", "session_id": "s1", "after_revision": -1}, "after_revision"),
        ({"action": "changes", "session_id": "s1", "after_revision": 0, "limit": 501}, "limit"),
    ],
)
def test_invalid_action_bounds_return_structured_error(payload: dict[str, Any], field_name: str) -> None:
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
