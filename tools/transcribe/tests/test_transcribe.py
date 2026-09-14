import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import video_transcribe as stt
from video_transcribe.cli import main


@pytest.fixture
def backend(monkeypatch):
    engine = Mock()
    factory = Mock(return_value=engine)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    return factory, engine


@pytest.fixture
def media(tmp_path, monkeypatch):
    source = tmp_path / "a video.mp4"
    source.touch()
    paths = []

    def extract(source, destination):
        destination.write_bytes(b"audio")
        paths.append(destination)

    monkeypatch.setattr(stt, "extract_audio", extract)
    return source, paths


def test_model_reuse_outputs_and_cleanup(backend, media, tmp_path):
    factory, engine = backend
    source, paths = media

    def transcribe(audio, **kwargs):
        assert kwargs["language"] == "en"
        assert kwargs["vad_filter"] is True

        def chunks():
            assert Path(audio).is_file()
            yield SimpleNamespace(id=0, start=1.25, end=2.5, text=" Hello world. ")

        return chunks(), SimpleNamespace(duration=3.0)

    engine.transcribe.side_effect = transcribe
    with stt.Transcriber(cache_dir=tmp_path / "cache") as transcriber:
        result = transcriber.transcribe(source)
        transcriber.transcribe(source)
        factory.assert_called_once_with(
            "turbo",
            device="cuda",
            device_index=0,
            compute_type="float16",
            download_root=str(tmp_path / "cache"),
            num_workers=1,
        )
    transcriber.close()
    engine.model.unload_model.assert_called_once_with()
    assert all(not path.exists() for path in paths)
    text, data = result.write(tmp_path / "out")
    assert text.read_text() == "Hello world.\n"
    payload = json.loads(data.read_text())
    assert payload["schema_version"] == 1
    assert payload["source"] == str(source)
    assert payload["segments"] == [{"id": 0, "start": 1.25, "end": 2.5, "text": "Hello world."}]


def test_inference_error_cleans_audio_and_model(backend, media):
    _, engine = backend
    source, paths = media

    def broken_chunks():
        raise RuntimeError("inference failed")
        yield  # pragma: no cover

    engine.transcribe.return_value = (broken_chunks(), SimpleNamespace(duration=3))
    with pytest.raises(RuntimeError, match="inference failed"):
        with stt.Transcriber() as transcriber:
            transcriber.transcribe(source)
    assert not paths[0].exists()
    engine.model.unload_model.assert_called_once()


def test_missing_input_does_not_load_model(backend, tmp_path):
    factory, _ = backend
    with pytest.raises(FileNotFoundError):
        stt.Transcriber().transcribe(tmp_path / "missing.mp4")
    factory.assert_not_called()


def test_empty_transcript(backend, media, tmp_path):
    _, engine = backend
    engine.transcribe.return_value = (iter(()), SimpleNamespace(duration=1))
    with stt.Transcriber(compute_type="int8_float16") as transcriber:
        result = transcriber.transcribe(media[0])
    text, data = result.write(tmp_path / "out")
    assert text.read_text() == ""
    assert json.loads(data.read_text())["segments"] == []


def test_ffmpeg_arguments(monkeypatch, tmp_path):
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    source, destination = tmp_path / "a video.mp4", tmp_path / "audio.wav"
    stt.extract_audio(source, destination)
    args = run.call_args.args[0]
    assert args[args.index("-i") + 1] == str(source)
    assert args[args.index("-map") + 1] == "0:a:0"
    assert args[args.index("-ar") + 1] == "16000"
    assert args[args.index("-ac") + 1] == "1"
    assert run.call_args.kwargs["check"] is True


@pytest.mark.parametrize(
    "error, message",
    [
        (FileNotFoundError(), "FFmpeg is missing"),
        (subprocess.CalledProcessError(1, "ffmpeg", stderr="no audio"), "no audio"),
    ],
)
def test_ffmpeg_errors(monkeypatch, tmp_path, error, message):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=error))
    with pytest.raises(RuntimeError, match=message):
        stt.extract_audio(tmp_path / "video", tmp_path / "audio.wav")


def test_cli_success(backend, media, tmp_path, monkeypatch, capsys):
    _, engine = backend
    engine.transcribe.return_value = (iter(()), SimpleNamespace(duration=1))
    monkeypatch.setattr(
        sys, "argv", ["video-transcribe", str(media[0]), "--output-dir", str(tmp_path / "out")]
    )
    assert main() == 0
    assert "a video.mp4.json" in capsys.readouterr().out
    engine.model.unload_model.assert_called_once()


def test_cli_missing_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["video-transcribe", str(tmp_path / "missing")])
    assert main() == 1
    assert "Input file does not exist" in capsys.readouterr().err


def test_invalid_precision():
    with pytest.raises(ValueError, match="compute_type"):
        stt.Transcriber(compute_type="auto")
