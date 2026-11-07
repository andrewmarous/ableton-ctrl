import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ableton_ctrl import audio


@pytest.fixture(autouse=True)
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ABLETON_AUDIO_DIR", str(tmp_path / "artifacts"))


@pytest.fixture
def make_audio(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg integration tests require ffmpeg and ffprobe")

    def make(expression="0.5*sin(2*PI*1000*t)", duration=1):
        path = tmp_path / "input with spaces.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"aevalsrc={expression}:s=48000:d={duration}",
                "-c:a",
                "pcm_f32le",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        return str(path)

    return make


def test_tone(make_audio):
    result = audio.inspect_audio(make_audio())
    assert result["sample_peak_dbfs"] == pytest.approx(-6.0206, abs=0.01)
    assert result["rms_dbfs"] == pytest.approx(-9.0309, abs=0.01)
    assert result["true_peak_dbfs"] == pytest.approx(-6, abs=0.2)
    assert result["integrated_lufs"] == pytest.approx(-9, abs=0.2)
    assert result["possible_clipping"] is False
    for image in result["images"].values():
        assert Path(image).read_bytes().startswith(b"\x89PNG")
    assert "Parsed_astats" in Path(result["measurement_log"]).read_text()
    assert json.loads(Path(result["report"]).read_text()) == result


@pytest.mark.parametrize("duration", [0.0001, 0.1, 1])
def test_silence_and_short_files(make_audio, duration):
    result = audio.inspect_audio(make_audio("0", duration))
    assert result["rms_dbfs"] is None
    assert result["integrated_lufs"] is None
    assert result["possible_clipping"] is False


def test_clipping_and_antiphase(make_audio):
    result = audio.inspect_audio(make_audio("sin(2*PI*1000*t)|-sin(2*PI*1000*t)"))
    assert result["channels"] == 2
    assert result["sample_peak_dbfs"] == pytest.approx(0)
    assert result["rms_dbfs"] == pytest.approx(-3.01, abs=0.01)
    assert result["possible_clipping"] is True


@pytest.mark.parametrize("seconds", [0, -1, 301, float("nan"), float("inf")])
def test_capture_invalid_duration(seconds):
    with pytest.raises(ValueError):
        audio.capture_audio(seconds, "Loopback")


def test_devices_parses_only_audio(monkeypatch):
    monkeypatch.setattr(audio.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(audio, "executable", lambda name: name)
    log = (
        "[AVFoundation indev @ 0x1] AVFoundation video devices:\n"
        "[AVFoundation indev @ 0x1] [0] Camera\n"
        "[AVFoundation indev @ 0x1] AVFoundation audio devices:\n"
        "[AVFoundation indev @ 0x1] [0] Microphone\n"
        "[AVFoundation indev @ 0x1] [1] BlackHole 2ch\n"
    )
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", log)
    )
    assert audio.list_devices() == [
        {"id": 0, "name": "Microphone"},
        {"id": 1, "name": "BlackHole 2ch"},
    ]


@pytest.mark.parametrize("fail", [False, True])
def test_capture_command_and_cleanup(monkeypatch, tmp_path, fail):
    monkeypatch.setattr(audio.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(audio, "executable", lambda name: name)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"wave")
        if fail:
            raise RuntimeError("Capture failed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(audio, "run", run)
    monkeypatch.setattr(
        audio,
        "probe_audio",
        lambda path: {
            "sample_rate": 48000,
            "channels": 2,
            "duration_seconds": 8,
        },
    )
    if fail:
        with pytest.raises(RuntimeError):
            audio.capture_audio(8, "BlackHole 2ch")
        assert not list((tmp_path / "artifacts").iterdir())
    else:
        result = audio.capture_audio(8, "BlackHole 2ch")
        assert Path(result["path"]).is_file()
        assert commands[0][commands[0].index("-i") + 1] == ":BlackHole 2ch"
        assert "-xerror" in commands[0]
        assert "-nostdin" in commands[0]


@pytest.mark.parametrize("device", ["", "default", "none", "video:audio"])
def test_reject_default_or_ambiguous_input(monkeypatch, device):
    monkeypatch.setattr(audio.platform, "system", lambda: "Darwin")
    with pytest.raises(ValueError, match="explicit loopback"):
        audio.capture_audio(8, device)


def test_missing_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="brew install ffmpeg"):
        audio.inspect_audio("anything.wav")


def test_unsupported_capture_platform(monkeypatch):
    monkeypatch.setattr(audio.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="macOS"):
        audio.list_devices()


def test_bad_summary_fails():
    with pytest.raises(RuntimeError, match="summary"):
        audio.parse_measurements("Unexpected FFmpeg output", 1)


def test_cli_errors(monkeypatch, capsys):
    monkeypatch.delenv("ABLETON_AUDIO_DEVICE", raising=False)
    assert audio.main(["capture"]) == 1
    assert "--device" in capsys.readouterr().err
    monkeypatch.setattr(audio, "executable", lambda name: name)
    assert audio.main(["inspect", "/nonexistent/audio.wav"]) == 1
