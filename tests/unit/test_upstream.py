import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ableton_ctrl.upstream import install


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
        backup = install(tmp_path, '/bin/uvx')
        run.assert_called_once_with(['/bin/uvx', 'mcp-server-ableton-live@1.8.1', 'install'], check=True)
        install(tmp_path, '/bin/uvx')
    assert json.loads(config.read_text())['mcpServers']['other'] == {'command': 'other'}
    assert json.loads(config.read_text())['custom'] == 1
    assert (wiki / 'index.md').read_bytes() == b'personal wiki\n'
    assert not extension.exists()
    assert (backup / 'extensions/ableton-controller.ts').read_text() == 'legacy'


def test_fresh_install_creates_wiki_and_native_workflow(tmp_path: Path) -> None:
    with patch('ableton_ctrl.upstream.subprocess.run'):
        install(tmp_path, '/bin/uvx')
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
            install(tmp_path, '/bin/uvx')
        run.assert_not_called()
    assert config.read_text() == original
