from __future__ import annotations

import re
from pathlib import Path

import pytest

from ableton_ctrl.pi_installer import (
    extension_artifact_text,
    install_pi_artifacts,
    pi_extension_path,
    pi_skill_path,
    run,
    skill_artifact_text,
)


ACTIONS = ["snapshot", "object", "children", "search", "schema", "changes", "resource"]


def test_extension_registers_exactly_one_flat_ableton_ctrl_tool() -> None:
    extension = extension_artifact_text()

    assert extension.count("pi.registerTool") == 1
    assert 'name: "ableton_ctrl"' in extension
    assert "Type.Object" in extension
    assert "Type.Union" not in extension
    assert "Type.Record" not in extension
    assert "JSON string" not in extension
    for action in ACTIONS:
        assert f'"{action}"' in extension


def test_extension_shells_out_to_cli_with_one_json_argument() -> None:
    extension = extension_artifact_text()

    assert "execFile(" in extension
    assert '"ableton-ctrl"' in extension
    assert "JSON.stringify(params)" in extension
    assert "JSON.parse(jsonText)" in extension
    assert "details: parsed" in extension
    assert re.search(r"\[JSON\.stringify\(params\)\]", extension)


def test_extension_bounds_buffer_and_truncates_tool_content() -> None:
    extension = extension_artifact_text()

    assert "MAX_CLI_BUFFER_BYTES" in extension
    assert "maxBuffer: MAX_CLI_BUFFER_BYTES" in extension
    assert "truncateHead" in extension
    assert "DEFAULT_MAX_BYTES" in extension
    assert "DEFAULT_MAX_LINES" in extension
    assert "mkdtemp" in extension
    assert "Full JSON saved to" in extension
    assert "contentText" in extension


def test_skill_documents_actions_operational_constraints_and_recovery() -> None:
    skill = skill_artifact_text()

    assert "Use the `ableton_ctrl` tool" in skill
    assert "read-only" in skill
    assert "do not use it" in skill
    assert "mutate Live" in skill
    for action in ACTIONS:
        assert f"`{action}`" in skill
    for phrase in [
        "Object IDs",
        "pagination",
        "revision pinning",
        "persisted cursor",
        "Set-name ambiguity",
        "resource",
        "error.recovery",
        "children` rejects values above 200",
        "search` rejects values above 200",
        "session_id` and `after_revision` together",
        "output was truncated",
    ]:
        assert phrase.lower() in skill.lower()


def test_first_install_creates_global_pi_extension_and_skill(tmp_path: Path) -> None:
    installed = install_pi_artifacts(tmp_path)

    assert installed == [pi_extension_path(tmp_path), pi_skill_path(tmp_path)]
    assert pi_extension_path(tmp_path).read_text(encoding="utf-8") == extension_artifact_text()
    assert pi_skill_path(tmp_path).read_text(encoding="utf-8") == skill_artifact_text()


def test_installer_refuses_to_overwrite_existing_extension(tmp_path: Path) -> None:
    target = pi_extension_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("custom extension", encoding="utf-8")

    with pytest.raises(FileExistsError) as exc_info:
        install_pi_artifacts(tmp_path)

    message = str(exc_info.value)
    assert str(target) in message
    assert "Refusing to overwrite" in message
    assert "Manually delete" in message
    assert "before reinstalling" in message
    assert target.read_text(encoding="utf-8") == "custom extension"
    assert not pi_skill_path(tmp_path).exists()


def test_installer_refuses_to_overwrite_existing_skill(tmp_path: Path) -> None:
    target = pi_skill_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("custom skill", encoding="utf-8")

    with pytest.raises(FileExistsError) as exc_info:
        install_pi_artifacts(tmp_path)

    message = str(exc_info.value)
    assert str(target) in message
    assert "Manually delete" in message
    assert target.read_text(encoding="utf-8") == "custom skill"
    assert not pi_extension_path(tmp_path).exists()


def test_install_command_rejects_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["unexpected"]) == 2
    captured = capsys.readouterr()
    assert "does not accept arguments" in captured.err


def test_pyproject_registers_separate_install_console_script() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'ableton-ctrl-install-pi = "ableton_ctrl.pi_installer:main"' in pyproject
    assert 'ableton-ctrl = "ableton_ctrl.cli:main"' in pyproject


def test_generated_artifacts_are_coherent() -> None:
    extension = extension_artifact_text()
    skill = skill_artifact_text()

    for action in ACTIONS:
        assert f'"{action}"' in extension
        assert f"`{action}`" in skill
    assert "ableton_ctrl" in extension
    assert "ableton_ctrl" in skill
    assert "glossary" in skill
    assert "interpretation" in skill
    assert "limitations" in skill
