import json
import zipfile
from pathlib import Path

import pytest

from ableton_ctrl import library
from ableton_ctrl.cli import add_source, main


def test_empty_library_roundtrip(tmp_path):
    root = tmp_path / "empty"
    library.initialize(root)
    archive = tmp_path / "empty.zip"
    library.export(root, archive)
    library.import_archive(archive, tmp_path / "restored")
    assert (tmp_path / "restored/raw").is_dir()


def test_review_publish_and_portable_roundtrip(tmp_path):
    root = tmp_path / "kb"
    note = tmp_path / "notes.md"
    note.write_text("# Compression\nUse your ears.\n")
    identity = library.stage(root, note)
    assert library.stage(root, note) == identity
    assert not list((root / "wiki/sources").glob("*.md"))
    page = library.publish(root, identity)
    assert "Use your ears" in page.read_text()
    with pytest.raises(FileExistsError):
        library.publish(root, identity)
    (root / "secret.env").write_text("secret")
    archive = tmp_path / "export.zip"
    library.export(root, archive)
    with zipfile.ZipFile(archive) as z:
        assert not any("drafts" in name or "secret" in name for name in z.namelist())
    restored = tmp_path / "restored"
    library.import_archive(archive, restored)
    assert (restored / page.relative_to(root)).read_text() == page.read_text()
    assert json.loads((restored / "kb.json").read_text())["sources"][0]["origin"] == "notes.md"


@pytest.mark.parametrize("name", ["../escape", "/escape", "wiki/../../escape", "secret.env"])
def test_unsafe_archive_rejected(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, "bad")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError):
        library.import_archive(archive, destination)
    assert not destination.exists()


def test_import_never_overwrites(tmp_path):
    with pytest.raises(FileExistsError):
        library.import_archive(tmp_path / "no.zip", tmp_path)


@pytest.mark.parametrize("backend", ["metal", "cpu", "auto"])
def test_transcription_backend_reaches_review(tmp_path, monkeypatch, backend):
    import video_transcribe

    class Transcript:
        def write(self, directory):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "transcript.json"
            path.write_text(json.dumps({"segments": [{"start": 2.5, "text": "Use a rack."}]}))
            return (path,)

    class Transcriber:
        def __init__(self, **kwargs):
            assert kwargs["backend"] == backend

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def transcribe(self, media):
            assert media.name == "tutorial.mp4"
            return Transcript()

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(video_transcribe, "Transcriber", Transcriber)
    media = tmp_path / "tutorial.mp4"
    media.write_bytes(b"fake media")
    root = tmp_path / "knowledge"
    identity = add_source(root, str(media), backend)
    page = library.draft(root, identity) / "page.md"
    assert "[2.5s] Use a rack." in page.read_text()
    assert "tutorial.mp4" in page.read_text()


def test_draft_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        library.draft(tmp_path, "../secret")


def test_cli_knowledge_only_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "knowledge"
    monkeypatch.setattr("sys.argv", ["ableton", "--kb", str(root), "setup", "--knowledge-only", "--yes"])
    assert main() == 0
    assert (root / "kb.json").exists()
    assert main() == 0
