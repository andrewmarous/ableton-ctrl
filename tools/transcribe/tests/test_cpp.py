import hashlib
import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import video_transcribe as stt
from video_transcribe import cpp


@pytest.fixture
def cpp_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp.shutil, "which", lambda _: "/bin/whisper-cli")
    monkeypatch.setattr(cpp, "model_path", lambda name, cache: cache / f"{name}.bin")
    monkeypatch.setattr(stt.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(stt.platform, "machine", lambda: "arm64")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 48000)
    monkeypatch.setattr(stt, "extract_audio", lambda src, dst: dst.write_bytes(src.read_bytes()))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output = Path(command[command.index("--output-file") + 1] + ".json")
        output.write_text(
            json.dumps(
                {
                    "transcription": [
                        {"offsets": {"from": 250, "to": 2500}, "text": " Hello world. "}
                    ]
                }
            )
        )
        return SimpleNamespace(stderr="ggml_metal_device_init: GPU name: Apple M1")

    monkeypatch.setattr(cpp.subprocess, "run", run)
    return source, calls, run


@pytest.mark.parametrize("backend,model", [("metal", "turbo"), ("cpu", "base.en")])
def test_cpp_output_and_cleanup(cpp_environment, tmp_path, backend, model):
    source, calls, _ = cpp_environment
    with stt.Transcriber(backend=backend, cache_dir=tmp_path, threads=2) as transcriber:
        result = transcriber.transcribe(source)
    assert result.backend == backend
    assert result.model == model
    assert result.duration == 3
    assert result.text == "Hello world."
    assert result.segments == (stt.Segment(0, 0.25, 2.5, "Hello world."),)
    assert ("--no-gpu" in calls[0]) == (backend == "cpu")
    assert calls[0][calls[0].index("--threads") + 1] == "2"
    assert not Path(calls[0][calls[0].index("--file") + 1]).exists()
    _, path = result.write(tmp_path / "output")
    assert json.loads(path.read_text())["backend"] == backend


def test_auto_metal_failure_retries_smaller_cpu(cpp_environment, monkeypatch, tmp_path):
    source, calls, run = cpp_environment

    def failing_gpu(command, **kwargs):
        if "--no-gpu" not in command:
            raise subprocess.CalledProcessError(1, command, stderr="Metal out of memory")
        return run(command, **kwargs)

    monkeypatch.setattr(cpp.subprocess, "run", failing_gpu)
    with pytest.warns(RuntimeWarning, match="Falling back to CPU with base.en"):
        result = stt.Transcriber(cache_dir=tmp_path).transcribe(source)
    assert result.backend == "cpu"
    assert result.model == "base.en"
    assert "base.en.bin" in calls[0][calls[0].index("--model") + 1]


def test_explicit_metal_does_not_silently_fallback(cpp_environment, monkeypatch, tmp_path):
    source, _, _ = cpp_environment
    monkeypatch.setattr(
        cpp.subprocess, "run", Mock(return_value=SimpleNamespace(stderr="CPU only"))
    )
    with pytest.raises(cpp.BackendError, match="did not initialize a Metal GPU"):
        stt.Transcriber(backend="metal", cache_dir=tmp_path).transcribe(source)


def test_auto_cpu_without_cuda(cpp_environment, monkeypatch, tmp_path):
    source, calls, _ = cpp_environment
    monkeypatch.setattr(stt.platform, "system", lambda: "Linux")
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    with pytest.warns(RuntimeWarning, match="No supported GPU"):
        result = stt.Transcriber(cache_dir=tmp_path).transcribe(source)
    assert result.backend == "cpu"
    assert "--no-gpu" in calls[0]


def test_missing_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp.shutil, "which", lambda _: None)
    with pytest.raises(cpp.BackendError, match="executable not found"):
        stt.Transcriber(backend="cpu", cache_dir=tmp_path).load()


@pytest.mark.parametrize(
    "payload",
    ["not json", "{}", '{"transcription": [{"offsets": {"from": -1, "to": 4}, "text": "bad"}]}'],
)
def test_malformed_cpp_output(cpp_environment, monkeypatch, tmp_path, payload):
    source, _, run = cpp_environment

    def malformed(command, **kwargs):
        result = run(command, **kwargs)
        Path(command[command.index("--output-file") + 1] + ".json").write_text(payload)
        return result

    monkeypatch.setattr(cpp.subprocess, "run", malformed)
    with pytest.raises(RuntimeError, match="Invalid whisper.cpp JSON"):
        stt.Transcriber(backend="cpu", cache_dir=tmp_path).transcribe(source)


def test_download_integrity_atomic_cache(monkeypatch, tmp_path):
    content = b"fake weights"
    monkeypatch.setitem(cpp.MODELS, "base.en", hashlib.sha256(content).hexdigest())
    download = Mock(return_value=io.BytesIO(content))
    monkeypatch.setattr(cpp.urllib.request, "urlopen", download)
    path = cpp.model_path("base.en", tmp_path)
    assert path.read_bytes() == content
    assert cpp.model_path("base.en", tmp_path) == path
    download.assert_called_once()
    assert not list(tmp_path.glob("*.part"))
    path.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        cpp.model_path("base.en", tmp_path)


def test_failed_download_does_not_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"corrupt"))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        cpp.model_path("base.en", tmp_path)
    assert not list(tmp_path.iterdir())


def test_auto_cuda_initialization_failure_uses_cpu(cpp_environment, monkeypatch, tmp_path):
    source, _, _ = cpp_environment
    monkeypatch.setattr(stt.platform, "system", lambda: "Linux")
    monkeypatch.setitem(
        sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1)
    )
    factory = Mock(side_effect=RuntimeError("CUDA library missing"))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    with pytest.warns(RuntimeWarning, match="Falling back to CPU"):
        result = stt.Transcriber(cache_dir=tmp_path).transcribe(source)
    assert result.backend == "cpu"
    assert result.model == "base.en"
    factory.assert_called_once()


def test_gpu_inference_failure_unloads_cuda_before_cpu(cpp_environment, monkeypatch, tmp_path):
    source, _, _ = cpp_environment
    monkeypatch.setattr(stt.platform, "system", lambda: "Linux")
    monkeypatch.setitem(
        sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1)
    )
    engine = Mock()
    engine.transcribe.side_effect = RuntimeError("out of memory")
    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Mock(return_value=engine))
    )
    with pytest.warns(RuntimeWarning, match="Falling back to CPU"):
        with stt.Transcriber(cache_dir=tmp_path) as transcriber:
            result = transcriber.transcribe(source)
    assert result.backend == "cpu"
    engine.model.unload_model.assert_called_once()


def test_download_error_does_not_trigger_gpu_fallback(cpp_environment, monkeypatch, tmp_path):
    source, _, _ = cpp_environment
    monkeypatch.setattr(cpp, "model_path", Mock(side_effect=RuntimeError("Model download failed")))
    with pytest.raises(RuntimeError, match="Model download failed"):
        stt.Transcriber(cache_dir=tmp_path).transcribe(source)
    cpp.model_path.assert_called_once()


def test_cpu_failure_is_not_retried(cpp_environment, monkeypatch, tmp_path):
    source, _, _ = cpp_environment
    run = Mock(side_effect=subprocess.CalledProcessError(1, "whisper-cli", stderr="failed"))
    monkeypatch.setattr(cpp.subprocess, "run", run)
    with pytest.raises(cpp.BackendError, match="CPU|cpu"):
        stt.Transcriber(backend="cpu", cache_dir=tmp_path).transcribe(source)
    run.assert_called_once()


@pytest.mark.parametrize(
    "options",
    [
        {"threads": 0},
        {"backend": "unknown"},
        {"model": "unknown"},
        {"cpu_model": "turbo"},
        {"backend": "cuda", "model": "base.en"},
    ],
)
def test_invalid_options(options):
    with pytest.raises(ValueError):
        stt.Transcriber(**options)
