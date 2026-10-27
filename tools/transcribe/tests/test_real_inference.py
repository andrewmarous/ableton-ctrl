"""Opt-in model download and hardware tests. See README.md for invocation."""

import os
import platform
from pathlib import Path

import pytest

from video_transcribe import Transcriber

AUDIO = os.environ.get("WHISPER_CPP_TEST_AUDIO")
pytestmark = pytest.mark.skipif(not AUDIO, reason="Set WHISPER_CPP_TEST_AUDIO for real inference")


@pytest.mark.parametrize("backend", ["cpu", "metal"])
def test_real_speech(backend, tmp_path):
    if backend == "metal" and not (platform.system() == "Darwin" and platform.machine() == "arm64"):
        pytest.skip("Metal requires Apple Silicon")
    with Transcriber(backend=backend, model="base.en") as transcriber:
        result = transcriber.transcribe(Path(AUDIO))
    assert result.backend == backend
    assert result.model == "base.en"
    assert result.duration > 0
    assert result.text.strip()
    assert result.segments
    assert all(0 <= s.start <= s.end <= result.duration for s in result.segments)
    text, data = result.write(tmp_path)
    assert text.is_file() and data.is_file()
