"""whisper.cpp CLI adapter. No Python inference dependencies are required."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path

# Immutable upstream revision and SHA-256 digests from the model repository.
REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODELS = {
    "tiny.en": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
    "base.en": "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
    "small.en": "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d",
    "turbo": "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
}


class BackendError(RuntimeError):
    """An inference backend could not initialize or execute."""


def model_path(name: str, cache: Path) -> Path:
    """Download atomically and verify both new and cached model files."""
    filename = f"ggml-{'large-v3-turbo' if name == 'turbo' else name}.bin"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / filename
    expected = MODELS[name]
    if destination.is_file():
        with destination.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                return destination
        raise RuntimeError(f"Model checksum mismatch: {destination}. Remove it and retry.")
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{REVISION}/{filename}"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    stream.write(block)
                    digest.update(block)
        if digest.hexdigest() != expected:
            raise RuntimeError(f"Downloaded model checksum mismatch: {filename}")
        os.replace(temporary, destination)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Model download failed for {filename}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


class CppBackend:
    def __init__(self, backend: str, model: str, cache: Path, binary: str | None, threads: int):
        self.backend = backend
        self.model = model
        self.cache = cache
        self.threads = threads
        requested = binary or os.environ.get("WHISPER_CPP_BINARY", "whisper-cli")
        executable = shutil.which(requested)
        if not executable:
            raise BackendError(
                f"whisper.cpp executable not found: {requested}. "
                "Install whisper.cpp v1.8.3 and set WHISPER_CPP_BINARY or --whisper-cli."
            )
        self.binary = executable
        self.path = model_path(model, cache)

    def transcribe(self, audio: Path) -> tuple[float, list[tuple[float, float, str]]]:
        with wave.open(str(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        output = audio.parent / "whisper-result"
        command = [
            self.binary,
            "--model",
            str(self.path),
            "--file",
            str(audio),
            "--language",
            "en",
            "--output-json",
            "--output-file",
            str(output),
            "--threads",
            str(self.threads),
            "--max-context",
            "0",
        ]
        if self.backend == "cpu":
            command.append("--no-gpu")
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            raise BackendError(f"whisper.cpp {self.backend} inference failed: {detail}") from exc
        # whisper.cpp can silently execute on CPU when Metal is unavailable.
        # Require evidence of Metal device initialization before labeling output Metal.
        if self.backend == "metal" and "ggml_metal_device_init: GPU name:" not in result.stderr:
            raise BackendError(
                "whisper.cpp did not initialize a Metal GPU. Use a Metal-enabled build."
            )
        try:
            payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            segments = []
            previous = 0.0
            for row in payload["transcription"]:
                start = row["offsets"]["from"] / 1000
                end = row["offsets"]["to"] / 1000
                text = row["text"]
                if (
                    not isinstance(text, str)
                    or not math.isfinite(start)
                    or not math.isfinite(end)
                    or start < previous
                    or end < start
                    or end > duration + 0.1
                ):
                    raise ValueError("Invalid segment text or timestamps")
                segments.append((start, min(end, duration), text.strip()))
                previous = min(end, duration)
            return duration, segments
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Invalid whisper.cpp JSON output: {exc}") from exc
