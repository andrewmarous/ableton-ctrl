"""Keep all launch paths on the same immutable maintained fork."""
import json
import re
from unittest.mock import patch

import pytest

from ableton_ctrl import upstream


def test_fork_pin_is_immutable_and_all_commands_use_it():
    assert re.fullmatch(r"[0-9a-f]{40}", upstream.FORK_COMMIT)
    assert upstream.PACKAGE == (
        "git+https://github.com/andrewmarous/ableton-live-mcp.git@" + upstream.FORK_COMMIT
    )
    assert upstream.command("uvx", "doctor", "--json") == [
        "uvx", "--from", upstream.PACKAGE, "ableton-live-mcp", "doctor", "--json",
    ]


def test_install_and_mcp_use_identical_source(tmp_path):
    library = tmp_path / "User Library"
    with patch("ableton_ctrl.upstream.subprocess.run") as run:
        upstream.install(tmp_path, "/bin/uvx", str(library))
    run.assert_called_once_with(
        upstream.command("/bin/uvx", "install", "--user-library", str(library)), check=True,
    )
    data = json.loads((tmp_path / ".pi/agent/mcp.json").read_text())
    entry = data["mcpServers"][upstream.SERVER]
    assert [entry["command"], *entry["args"]] == upstream.command("/bin/uvx")
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
            upstream.install(tmp_path, "uvx")
    run.assert_not_called()
    assert config.read_bytes() == original
