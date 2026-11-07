import json
from unittest.mock import MagicMock

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("matplotlib")
pytest.importorskip("pyloudnorm")

from ableton_ctrl.audio import capture_audio, inspect_audio, main  # noqa: E402


@pytest.fixture(autouse=True)
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_AUDIO_DIR", str(tmp_path / "artifacts"))


def test_tone(tmp_path):
    rate = 48000
    tone = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(rate) / rate)
    path = tmp_path / "tone.wav"
    sf.write(path, np.column_stack([tone, tone]), rate, subtype="FLOAT")
    result = inspect_audio(str(path))
    assert result["sample_peak_dbfs"] == pytest.approx(-6.0206, abs=0.01)
    assert result["rms_dbfs"] == pytest.approx(-9.0309, abs=0.01)
    assert result["stereo_correlation"] == pytest.approx(1)
    assert result["integrated_lufs"] is not None
    assert result["samples_at_or_above_full_scale"] == 0
    from pathlib import Path

    assert Path(result["image"]).stat().st_size > 1000
    assert json.loads(Path(result["report"]).read_text()) == result


@pytest.mark.parametrize("frames", [1, 100, 48000])
def test_silence_and_short_files(tmp_path, frames):
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(frames), 48000)
    result = inspect_audio(str(path))
    assert result["rms_dbfs"] is None
    assert result["integrated_lufs"] is None
    assert result["stereo_correlation"] is None


def test_clipping_and_antiphase(tmp_path):
    tone = np.tile([1.0, -1.0], 12000)
    path = tmp_path / "clip.wav"
    sf.write(path, np.column_stack([tone, -tone]), 48000, subtype="FLOAT")
    result = inspect_audio(str(path))
    assert result["samples_at_or_above_full_scale"] == 48000
    assert result["stereo_correlation"] == pytest.approx(-1)


def test_capture(tmp_path, monkeypatch):
    import sounddevice as sd

    stream = MagicMock()
    stream.__enter__.return_value.read.return_value = (np.zeros((480, 2)), False)
    monkeypatch.setattr(sd, "InputStream", MagicMock(return_value=stream))
    monkeypatch.setattr(sd, "query_devices", lambda *args: {"name": "Loopback"})
    result = capture_audio(0.01, "Loopback")
    assert sf.info(result["path"]).frames == 480
    assert result["device"] == "Loopback"
    stream.__enter__.return_value.read.return_value = (np.zeros((480, 2)), True)
    with pytest.raises(RuntimeError, match="overflow"):
        capture_audio(0.01, "Loopback")


@pytest.mark.parametrize("seconds", [0, -1, 301, float("nan"), float("inf")])
def test_capture_invalid_duration(seconds):
    with pytest.raises(ValueError):
        capture_audio(seconds, "Loopback")


def test_cli_errors(monkeypatch, capsys):
    monkeypatch.delenv("ABLETON_AUDIO_DEVICE", raising=False)
    assert main(["capture"]) == 1
    assert "--device" in capsys.readouterr().err
    assert main(["inspect", "/nonexistent/audio.wav"]) == 1
