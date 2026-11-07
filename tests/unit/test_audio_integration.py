"""Plugin installation and CLI integration; no Live or audio hardware required."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
from unittest.mock import patch

import pytest

from ableton_ctrl import audio, cli, upstream
from ableton_ctrl.config import configuration


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ABLETON_AUDIO_DEVICE", raising=False)


def save(data):
    configuration().parent.mkdir(parents=True, exist_ok=True)
    configuration().write_text(json.dumps(data))


def test_device_precedence(monkeypatch):
    save({"audio_device": "Saved Loopback"})
    assert audio.configured_device() == "Saved Loopback"
    monkeypatch.setenv("ABLETON_AUDIO_DEVICE", "Environment Loopback")
    assert audio.configured_device() == "Environment Loopback"
    seen = []
    monkeypatch.setattr(audio, "capture_audio", lambda *args: seen.append(args) or {})
    assert audio.main(["capture", "--device", "Explicit Loopback"]) == 0
    assert seen[-1][1] == "Explicit Loopback"
    assert audio.main(["capture"]) == 0
    assert seen[-1][1] == "Environment Loopback"
    monkeypatch.delenv("ABLETON_AUDIO_DEVICE")
    assert audio.main(["capture"]) == 0
    assert seen[-1][1] == "Saved Loopback"


@pytest.mark.parametrize("arguments", [["audio", "capture"], ["audio", "inspect", "input.wav"]])
def test_plugin_command_dispatch(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["ableton", *arguments])
    calls = []
    monkeypatch.setattr(
        audio, "capture_audio", lambda *args: calls.append(args) or {"path": "recording.wav"}
    )
    monkeypatch.setattr(audio, "inspect_audio", lambda *args: calls.append(args) or {"images": {}})
    save({"audio_device": "Loopback"})
    assert cli.main() == 0
    assert calls


def test_setup_installs_audio_guidance_and_saves_device(tmp_path, monkeypatch):
    save({"custom": "preserved", "audio_device": "Old Loopback"})
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr(audio, "require_environment", lambda: {})
    monkeypatch.setattr(
        sys, "argv", ["ableton", "setup", "--yes", "--audio-device", "BlackHole 2ch"]
    )
    with patch("ableton_ctrl.upstream.subprocess.run"):
        assert cli.main() == 0
    data = json.loads(configuration().read_text())
    assert data["audio_device"] == "BlackHole 2ch"
    assert data["custom"] == "preserved"
    skill = (tmp_path / ".pi/agent/skills/ableton-ctrl/SKILL.md").read_text()
    assert "__ABLETON_AUDIO_COMMAND__" not in skill
    assert shlex.join([sys.executable, "-m", "ableton_ctrl.audio"]) in skill
    assert "capture --seconds 8" in skill
    assert "PNG paths in `images`" in skill
    assert "FFmpeg" in skill
    # Setup upgrades preserve the saved device when the option is omitted.
    monkeypatch.setattr(sys, "argv", ["ableton", "setup", "--yes"])
    with patch("ableton_ctrl.upstream.subprocess.run"):
        assert cli.main() == 0
    assert json.loads(configuration().read_text())["audio_device"] == "BlackHole 2ch"


def test_setup_missing_ffmpeg_does_not_modify_installation(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["ableton", "setup", "--yes"])
    assert cli.main() == 1
    assert not configuration().exists()
    assert not (tmp_path / ".pi/agent").exists()


def test_knowledge_only_setup_does_not_require_audio(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["ableton", "setup", "--knowledge-only", "--yes"])
    assert cli.main() == 0


def test_diagnostics_checks_filters_without_opening_input(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr(audio.platform, "system", lambda: "Darwin")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output = (
            "\n".join(f" .. {name} A->A" for name in audio.FILTERS)
            if "-filters" in command
            else " D  avfoundation    AVFoundation input device\n"
        )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(audio, "run", run)
    result = audio.require_environment()
    assert result["inspection_ready"] is True
    assert result["capture_backend_available"] is True
    assert all("-i" not in command for command in calls)
    assert all("-list_devices" not in command for command in calls)
    monkeypatch.setattr(
        audio, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", "")
    )
    with pytest.raises(RuntimeError, match="Install FFmpeg"):
        audio.require_environment()


def test_audio_doctor_missing_tools(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert audio.main(["doctor"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["inspection_ready"] is False
    assert result["ffmpeg"] is None


def test_plugin_doctor_does_not_hide_missing_audio_tools(tmp_path, monkeypatch):
    from ableton_ctrl import library

    library.initialize(tmp_path / ".pi/agent/ableton-wiki")
    monkeypatch.setattr(
        "shutil.which", lambda name: None if name in {"ffmpeg", "ffprobe"} else "/bin/" + name
    )
    monkeypatch.setattr(sys, "argv", ["ableton", "doctor"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    assert cli.main() == 1


def test_upstream_install_command_checks_audio_before_install(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    monkeypatch.setattr(sys, "argv", ["ableton-upstream", "install"])

    def fail():
        raise RuntimeError("Missing FFmpeg")

    monkeypatch.setattr(audio, "require_environment", fail)
    with patch.object(upstream, "install") as install:
        with pytest.raises(SystemExit):
            upstream.main()
        install.assert_not_called()
