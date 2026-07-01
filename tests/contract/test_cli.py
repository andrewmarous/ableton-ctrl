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
