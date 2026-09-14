from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_typescript_controller_lifecycle_suite() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for executable Pi controller tests")
    result = subprocess.run(
        [node, "--test", "tests/typescript/ableton-controller.test.mjs"],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
