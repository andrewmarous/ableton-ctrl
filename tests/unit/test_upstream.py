import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ableton_ctrl.upstream import DESCRIPTION, command, install, managed_entry


def test_install_preserves_wiki_and_configuration(tmp_path: Path) -> None:
    agent = tmp_path / '.pi/agent'
    agent.mkdir(parents=True)
    config = agent / 'mcp.json'
    config.write_text(json.dumps({'mcpServers': {'other': {'command': 'other'}}, 'custom': 1}))
    wiki = agent / 'ableton-wiki/wiki'
    wiki.mkdir(parents=True)
    (wiki / 'index.md').write_bytes(b'personal wiki\n')
    extension = agent / 'extensions/ableton-controller.ts'
    extension.parent.mkdir()
    extension.write_text('legacy')
    with patch('ableton_ctrl.upstream.subprocess.run') as run:
        backup = install(tmp_path, '/bin/python')
        run.assert_called_once_with(command('/bin/python', 'install'), check=True)
        install(tmp_path, '/bin/python')
    assert json.loads(config.read_text())['mcpServers']['other'] == {'command': 'other'}
    assert json.loads(config.read_text())['custom'] == 1
    assert (wiki / 'index.md').read_bytes() == b'personal wiki\n'
    assert not extension.exists()
    assert (backup / 'extensions/ableton-controller.ts').read_text() == 'legacy'


def test_fresh_install_creates_wiki_and_native_workflow(tmp_path: Path) -> None:
    with patch('ableton_ctrl.upstream.subprocess.run'):
        install(tmp_path, '/bin/python')
    agent = tmp_path / '.pi/agent'
    assert (agent / 'ableton-wiki/AGENTS.md').is_file()
    assert (agent / 'ableton-wiki/wiki/index.md').is_file()
    skill = (agent / 'skills/ableton-ctrl/SKILL.md').read_text()
    assert 'native Pi MCP' in skill
    assert 'Edits require an explicit user request' in skill
    assert not (agent / 'extensions/ableton-ctrl.ts').exists()
    assert not (agent / 'extensions/ableton-controller.ts').exists()


def test_conflict_changes_nothing(tmp_path: Path) -> None:
    agent = tmp_path / '.pi/agent'
    agent.mkdir(parents=True)
    config = agent / 'mcp.json'
    original = '{"mcpServers":{"AbletonMCP":{"command":"custom"}}}'
    config.write_text(original)
    with patch('ableton_ctrl.upstream.subprocess.run') as run:
        with pytest.raises(ValueError):
            install(tmp_path, '/bin/python')
        run.assert_not_called()
    assert config.read_text() == original


@pytest.mark.parametrize("launcher", [
    {"command": "/old/venv/bin/python3.12", "args": ["-m", "ableton_live_mcp.server"]},
    {"command": r"C:\old\Scripts\python.exe", "args": ["-m", "ableton_live_mcp.server"]},
    {"command": "/old/bin/uvx", "args": [
        "--from",
        "git+https://github.com/andrewmarous/ableton-live-mcp.git@"
        "558abb654040f40b4f671df764f355350b2cf843",
        "ableton-live-mcp",
    ]},
])
def test_refresh_managed_launcher_preserves_settings_and_backup(tmp_path, launcher):
    config = tmp_path / ".pi/agent/mcp.json"
    config.parent.mkdir(parents=True)
    old = {**launcher, "description": DESCRIPTION,
           "env": {"ABLETON_REQUIRE_RECOVERY_ALS": "false"}, "timeout": 120}
    original = {"mcpServers": {"AbletonMCP": old, "other": {"command": "other"}},
                "custom": True}
    config.write_text(json.dumps(original))
    with patch("ableton_ctrl.upstream.subprocess.run"):
        backup = install(tmp_path, "/new/venv/bin/python")
        install(tmp_path, "/new/venv/bin/python")
    data = json.loads(config.read_text())
    assert data["mcpServers"]["AbletonMCP"] == {
        **old, "command": "/new/venv/bin/python",
        "args": ["-m", "ableton_live_mcp.server"],
    }
    assert data["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert data["custom"] is True
    assert json.loads((backup / "mcp.json").read_text()) == original


@pytest.mark.parametrize("entry", [
    None,
    {"command": "/custom/python", "args": ["-m", "ableton_live_mcp.server"]},
    {"command": "custom", "args": [], "description": DESCRIPTION},
    {"command": "python", "args": ["-m", "custom"], "description": DESCRIPTION},
    {"command": "python", "args": ["-m", "ableton_live_mcp.server", "--extra"],
     "description": DESCRIPTION},
    {"command": "uvx", "args": ["--from", "git+https://example.com/fork", "ableton-live-mcp"],
     "description": DESCRIPTION},
])
def test_unknown_launchers_are_not_managed(entry):
    assert not managed_entry(entry)
