import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ableton_ctrl import library, synthesis, upstream, whisper_install
from ableton_ctrl.transaction import Transaction, rollback


def test_transaction_recovers_files_and_new_paths(tmp_path):
    existing = tmp_path / "existing"
    existing.write_text("before")
    new = tmp_path / "new"
    backup = tmp_path / "backup"
    with pytest.raises(RuntimeError):
        with Transaction(backup, [existing, new]):
            existing.write_text("after")
            new.mkdir()
            (new / "child").write_text("temporary")
            raise RuntimeError("failed")
    assert existing.read_text() == "before"
    assert not new.exists()
    assert json.loads((backup / "transaction.json").read_text())["state"] == "rolled-back"


def test_transaction_preserves_internal_library_symlinks(tmp_path):
    directory = tmp_path / "build"
    directory.mkdir()
    (directory / "lib.1.dylib").write_text("library")
    (directory / "lib.dylib").symlink_to("lib.1.dylib")
    backup = tmp_path / "backup"
    with Transaction(backup, [directory]):
        (directory / "lib.1.dylib").write_text("updated")
    rollback(backup)
    assert (directory / "lib.dylib").is_symlink()
    assert (directory / "lib.dylib").read_text() == "library"


def test_transaction_rejects_external_symlinks(tmp_path):
    directory = tmp_path / "build"
    directory.mkdir()
    (tmp_path / "private").write_text("secret")
    (directory / "outside").symlink_to("../private")
    with pytest.raises(ValueError, match="symlink"):
        with Transaction(tmp_path / "backup", [directory]):
            pass


def test_explicit_rollback_refuses_drift_and_restores(tmp_path):
    path = tmp_path / "config"
    path.write_text("before")
    backup = tmp_path / "backup"
    with Transaction(backup, [path]):
        path.write_text("after")
    path.write_text("personal edit")
    with pytest.raises(ValueError, match="changed"):
        rollback(backup)
    assert path.read_text() == "personal edit"
    path.write_text("after")
    rollback(backup)
    assert path.read_text() == "before"


def test_upstream_partial_failure_restores_remote_and_pi(tmp_path):
    remote = tmp_path / "Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py"
    remote.parent.mkdir(parents=True)
    remote.write_text("working plugin")
    config = tmp_path / ".pi/agent/mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"mcpServers":{"other":{"command":"other"}}}')
    original = config.read_bytes()

    def fail(*args, **kwargs):
        remote.write_text("partial installation")
        raise subprocess.CalledProcessError(1, args[0])

    with patch("ableton_ctrl.upstream.subprocess.run", side_effect=fail):
        with pytest.raises(subprocess.CalledProcessError):
            upstream.install(tmp_path, "uvx")
    assert remote.read_text() == "working plugin"
    assert config.read_bytes() == original


def test_upstream_late_failure_restores_remote(tmp_path):
    remote = tmp_path / "Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py"

    def installed(*args, **kwargs):
        remote.parent.mkdir(parents=True)
        remote.write_text("installed")

    with patch("ableton_ctrl.upstream.subprocess.run", side_effect=installed), patch(
        "ableton_ctrl.wiki_templates.artifact_text", side_effect=OSError("disk error")
    ):
        with pytest.raises(OSError):
            upstream.install(tmp_path, "uvx")
    assert not remote.exists()
    assert not (tmp_path / ".pi/agent/mcp.json").exists()


def test_setup_config_failure_restores_whole_installation(tmp_path, monkeypatch):
    from ableton_ctrl import cli, kb
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    remote = tmp_path / "Music/Ableton/User Library/Remote Scripts/AbletonMCP/__init__.py"
    remote.parent.mkdir(parents=True)
    remote.write_text("verified working plugin")
    original_writer = kb._write_json_atomic

    def writer(path, value):
        if path == cli.configuration():
            raise OSError("configuration write failed")
        return original_writer(path, value)

    def run(*args, **kwargs):
        remote.write_text("new installation")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(kb, "_write_json_atomic", writer)
    root = tmp_path / "new-knowledge"
    monkeypatch.setattr("sys.argv", ["ableton", "--kb", str(root), "setup", "--yes"])
    assert cli.main() == 1
    assert remote.read_text() == "verified working plugin"
    assert not root.exists()
    assert not cli.configuration().exists()
    assert not (tmp_path / ".pi/agent/mcp.json").exists()


def test_whisper_install_pins_revision_and_reuses_build(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, whisper_install.COMMIT + "\n")
        if "--build" in command:
            binary = whisper_install.binary_path(tmp_path, "cpu")
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    binary = whisper_install.install(tmp_path, "cpu")
    assert binary.is_file()
    assert any("-DGGML_METAL=OFF" in c for c in commands)
    count = len(commands)
    assert whisper_install.install(tmp_path, "cpu") == binary
    assert len(commands) == count + 1  # help smoke test only


def test_transcriber_finds_managed_binary(tmp_path, monkeypatch):
    from video_transcribe import cpp
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("WHISPER_CPP_BINARY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(cpp, "model_path", lambda name, cache: tmp_path / "model.bin")
    binary = whisper_install.binary_path(tmp_path, "cpu")
    binary.parent.mkdir(parents=True)
    binary.write_text("binary")
    backend = cpp.CppBackend("cpu", "base.en", tmp_path / "models", None, 4)
    assert backend.binary == str(binary)
    with pytest.raises(cpp.BackendError):
        cpp.CppBackend("cpu", "base.en", tmp_path / "models", "/missing/override", 4)


def test_whisper_wrong_revision_removes_partial_build(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "wrong"))
    with pytest.raises(RuntimeError, match="revision"):
        whisper_install.install(tmp_path, "cpu")
    assert not whisper_install.install_path(tmp_path, "cpu").exists()
    assert not list((tmp_path / ".local/share/ableton-ctrl/whisper").glob("*.lock"))


def make_draft(tmp_path):
    source = tmp_path / "transcript.json"
    source.write_text(json.dumps({"segments": [{"start": 12.5, "text": "Place a compressor on the drum bus."}]}))
    root = tmp_path / "knowledge"
    return root, library.stage(root, source, "https://example.com/tutorial")


def test_synthesis_citations_review_and_publication(tmp_path, monkeypatch):
    root, identity = make_draft(tmp_path)
    payload = {"techniques": [{"title": "Drum bus compression", "steps": [
        {"text": "Place a compressor on the drum bus.", "evidence": ["E1"]}], "cautions": []}]}

    def run(command, **kwargs):
        assert "--no-tools" in command and "--no-mcp" in command and "--no-session" in command
        assert "--no-context-files" in command and "--no-extensions" in command
        assert "12.5" in kwargs["input"]
        return subprocess.CompletedProcess(command, 0, json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", run)
    pages = synthesis.synthesize(root, identity, "test-model")
    assert len(pages) == 1
    assert "12.5s" in pages[0].read_text()
    assert not list((root / "wiki/techniques").glob("*.md"))
    library.publish(root, identity)
    published = root / "wiki/techniques" / pages[0].name
    assert published.exists()
    assert "techniques/" in (root / "wiki/index.md").read_text()
    archive = tmp_path / "knowledge.zip"
    library.export(root, archive)
    library.import_archive(archive, tmp_path / "restored")
    assert (tmp_path / "restored/wiki/techniques" / pages[0].name).read_text() == published.read_text()


@pytest.mark.parametrize("citations", [[], ["invented"], [3]])
def test_invalid_citations_leave_no_drafts(tmp_path, monkeypatch, citations):
    root, identity = make_draft(tmp_path)
    payload = {"techniques": [{"title": "Unsupported", "steps": [{"text": "A claim", "evidence": citations}]}]}
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, json.dumps(payload)))
    with pytest.raises(ValueError):
        synthesis.synthesize(root, identity)
    assert not (library.draft(root, identity) / "techniques").exists()


def test_provider_failure_preserves_source_and_explains_error(tmp_path, monkeypatch):
    root, identity = make_draft(tmp_path)
    directory = library.draft(root, identity)
    original = (directory / "page.md").read_bytes()

    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="Authentication required")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Authentication required"):
        synthesis.synthesize(root, identity)
    assert (directory / "page.md").read_bytes() == original
    assert not (directory / "techniques").exists()


def test_publication_failure_is_atomic(tmp_path, monkeypatch):
    root, identity = make_draft(tmp_path)
    original = (root / "kb.json").read_bytes()
    real_copy = library.shutil.copyfile

    def fail(source, destination, *args, **kwargs):
        if Path(destination).parent == root / "wiki/sources":
            raise OSError("disk full")
        return real_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(library.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        library.publish(root, identity)
    assert (root / "kb.json").read_bytes() == original
    assert not list((root / "raw").glob("source.*"))
    assert json.loads((library.draft(root, identity) / "record.json").read_text())["state"] == "review"
