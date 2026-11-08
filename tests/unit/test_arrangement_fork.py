"""Keep all launch paths in the installed application environment."""
import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ableton_ctrl import upstream


def test_fork_dependency_and_environment_launch():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["dependencies"] == [
        "mcp-server-ableton-live @ git+https://github.com/andrewmarous/ableton-live-mcp.git",
    ]
    assert upstream.command("/bin/python", "doctor", "--json") == [
        "/bin/python", "-m", "ableton_live_mcp.server", "doctor", "--json",
    ]


def test_install_and_mcp_use_identical_source(tmp_path):
    library = tmp_path / "User Library"
    with patch("ableton_ctrl.upstream.subprocess.run") as run:
        upstream.install(tmp_path, "/bin/python", str(library))
    run.assert_called_once_with(
        upstream.command("/bin/python", "install", "--user-library", str(library)), check=True,
    )
    data = json.loads((tmp_path / ".pi/agent/mcp.json").read_text())
    entry = data["mcpServers"][upstream.SERVER]
    assert [entry["command"], *entry["args"]] == upstream.command("/bin/python")
    skill = (tmp_path / ".pi/agent/skills/ableton-ctrl/SKILL.md").read_text()
    assert "preview_arrangement_edit" in skill
    assert "manual_save_confirmed=true" in skill
    assert "does not move its lane automation" in skill


def test_legacy_managed_configuration_requires_review(tmp_path):
    config = tmp_path / ".pi/agent/mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {upstream.SERVER: {
        "command": "uvx", "args": ["mcp-server-ableton-live@1.8.1"],
    }}}))
    original = config.read_bytes()
    with patch("ableton_ctrl.upstream.subprocess.run") as run:
        with pytest.raises(ValueError, match="Review"):
            upstream.install(tmp_path, "/bin/python")
    run.assert_not_called()
    assert config.read_bytes() == original
