"""FFmpeg loopback capture and file inspection, independent of Live control."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any


from .config import read_configuration


FILTERS = ("astats", "ebur128", "showwavespic", "showspectrumpic")


def configured_device() -> str | None:
    value = os.environ.get("ABLETON_AUDIO_DEVICE") or read_configuration().get("audio_device")
    if value is not None and not isinstance(value, str):
        raise ValueError("The configured audio_device must be an input name or ID string.")
    return value


def diagnostics() -> dict[str, Any]:
    """Check installed tools without opening an input or starting Live playback."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    missing_filters = list(FILTERS)
    capture_backend = False
    errors = []
    if ffmpeg:
        try:
            filters = run([ffmpeg, "-hide_banner", "-filters"], timeout=15).stdout
            missing_filters = [
                name for name in FILTERS if not re.search(r"(?m)^\s*\S+\s+" + name + r"\s", filters)
            ]
            if platform.system() == "Darwin":
                devices = run([ffmpeg, "-hide_banner", "-devices"], timeout=15).stdout
                capture_backend = bool(re.search(r"(?m)^\s*D\S*\s+avfoundation\s", devices))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
    device = configured_device()
    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "missing_filters": missing_filters,
        "inspection_ready": bool(ffmpeg and ffprobe and not missing_filters and not errors),
        "capture_backend_available": capture_backend,
        "configured_device": device,
        "errors": errors,
        "capture_note": "Configure a loopback input with ableton setup --audio-device NAME. "
        "Routing and permissions require a capture test; no input was opened.",
    }


def require_environment() -> dict[str, Any]:
    result = diagnostics()
    if not result["inspection_ready"]:
        raise RuntimeError(
            "Audio tools are unavailable. Install FFmpeg (macOS: brew install ffmpeg). "
            f"Diagnostics: {json.dumps(result)}"
        )
    if platform.system() == "Darwin" and not result["capture_backend_available"]:
        raise RuntimeError(
            "FFmpeg lacks AVFoundation capture support. Install the Homebrew FFmpeg build."
        )
    return result


def executable(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Missing {name}. Install FFmpeg (macOS: brew install ffmpeg).")
    return found


def run(command: list[str], timeout: float = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed: {result.stderr[-4000:].strip()}")
    return result


def artifact_path(suffix: str) -> Path:
    root = Path(os.environ.get("ABLETON_AUDIO_DIR", "artifacts/audio")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{uuid.uuid4().hex}{suffix}"


def list_devices() -> list[dict[str, Any]]:
    if platform.system() != "Darwin":
        raise RuntimeError("Live capture currently supports macOS AVFoundation inputs only.")
    # AVFoundation returns a nonzero status after listing devices without opening one.
    result = subprocess.run(
        [
            executable("ffmpeg"),
            "-hide_banner",
            "-nostdin",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            ":",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if "AVFoundation audio devices:" not in result.stderr:
        raise RuntimeError(f"Cannot list AVFoundation audio inputs: {result.stderr[-4000:]}")
    section = result.stderr.split("AVFoundation audio devices:", 1)[1]
    return [
        {"id": int(index), "name": name.strip()}
        for index, name in re.findall(r"\[AVFoundation[^\n]*?\] \[(\d+)\] ([^\n]+)", section)
    ]


def probe_audio(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Audio file does not exist: {path}")
    info = json.loads(
        run(
            [
                executable("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                str(path),
            ]
        ).stdout
    )
    streams = info.get("streams", [])
    if not streams:
        raise ValueError("The file has no audio stream.")
    stream = streams[0]
    duration = float(stream.get("duration", info.get("format", {}).get("duration", "nan")))
    if not math.isfinite(duration) or not 0 < duration <= 300.01:
        raise ValueError("Use a nonempty audio file of at most 300 seconds with a known duration.")
    if stream["channels"] not in (1, 2):
        raise ValueError("Use a mono or stereo audio file.")
    return {
        "sample_rate": int(stream["sample_rate"]),
        "channels": stream["channels"],
        "duration_seconds": duration,
    }


def capture_audio(seconds: float, device: str, channels: int = 2, samplerate: int = 48000) -> dict[str, Any]:
    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError("Duration must be greater than zero and at most 300 seconds.")
    if channels not in (1, 2) or not 8000 <= samplerate <= 192000:
        raise ValueError("Use 1 or 2 channels and a sample rate from 8000 to 192000 Hz.")
    if platform.system() != "Darwin":
        raise RuntimeError("Live capture currently supports macOS AVFoundation inputs only.")
    if not device.strip() or device.lower() in {"default", "none"} or ":" in device:
        raise ValueError(
            "Select an explicit loopback input name or ID from 'ableton-audio devices'."
        )
    ffmpeg = executable("ffmpeg")
    executable("ffprobe")
    path = artifact_path(".wav")
    print(
        "Opening loopback input; capture starts after FFmpeg initializes.",
        file=sys.stderr,
        flush=True,
    )
    try:
        run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-nostats",
                "-xerror",
                "-n",
                "-f",
                "avfoundation",
                "-i",
                f":{device}",
                # Preserve input timing: fill timestamp gaps instead of shortening the WAV.
                "-af",
                "aresample=async=1:first_pts=0",
                "-t",
                str(seconds),
                "-map",
                "0:a:0",
                "-ac",
                str(channels),
                "-ar",
                str(samplerate),
                "-c:a",
                "pcm_f32le",
                str(path),
            ],
            timeout=seconds + 30,
        )
        info = probe_audio(path)
        if abs(info["duration_seconds"] - seconds) > 0.1:
            raise RuntimeError("Capture ended early. Retry the recording.")
        result = {"path": str(path), "device": device, "backend": "ffmpeg/avfoundation", **info}
        path.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    except BaseException:
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)
        raise


def finite(value: str) -> float | None:
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def parse_measurements(log: str, duration: float) -> dict[str, Any]:
    """Extract FFmpeg summaries; preserve the raw log alongside the report."""
    for count in re.findall(r"Number of (?:NaNs|Infs):\s*(\S+)", log):
        if float(count) > 0:
            raise ValueError("Audio contains non-finite samples.")
    overall = log.rsplit("] Overall", 1)
    if len(overall) != 2:
        raise RuntimeError("FFmpeg did not return an astats summary.")

    def stat(label: str) -> float | None:
        found = re.search(r"\] " + re.escape(label) + r":\s*(\S+)", overall[1])
        if not found:
            raise RuntimeError(f"FFmpeg astats summary is missing {label}.")
        return finite(found[1])

    peak = stat("Peak level dB")
    rms = stat("RMS level dB")
    summary = log.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"\bI:\s*(\S+) LUFS", summary)
    true_peak = re.search(r"Peak:\s*(\S+) dBFS", summary)
    if not integrated or not true_peak:
        raise RuntimeError("FFmpeg did not return an ebur128 loudness/true-peak summary.")
    loudness = finite(integrated[1])
    if duration < 0.4 or rms is None or (loudness is not None and loudness <= -70):
        loudness = None
    return {
        "sample_peak_dbfs": peak,
        "rms_dbfs": rms,
        "integrated_lufs": loudness,
        "true_peak_dbfs": finite(true_peak[1]),
        "possible_clipping": peak is not None and peak >= 0,
    }


def inspect_audio(path: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    ffmpeg = executable("ffmpeg")
    info = probe_audio(source)
    base = artifact_path(".json")
    waveform = base.with_name(base.stem + "-waveform.png")
    spectrogram = base.with_name(base.stem + "-spectrogram.png")
    log_path = base.with_suffix(".ffmpeg.log")
    try:
        measured = run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-nostats",
                "-xerror",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-t",
                "300",
                "-af",
                "astats=reset=0,ebur128=peak=true",
                "-f",
                "null",
                "-",
            ]
        )
        measurements = parse_measurements(measured.stderr, info["duration_seconds"])
        # Each channel remains separate, including opposite-polarity stereo signals.
        for output, view in [
            (waveform, "showwavespic=s=1200x300:split_channels=1"),
            (spectrogram, "showspectrumpic=s=1200x600:legend=1:mode=separate:scale=log:fscale=log"),
        ]:
            run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    "-n",
                    "-i",
                    str(source),
                    "-filter_complex",
                    f"[0:a:0]{view}[view]",
                    "-map",
                    "[view]",
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    str(output),
                ]
            )
        result = {
            "source": str(source),
            "engine": "ffmpeg",
            **info,
            **measurements,
            "images": {"waveform": str(waveform), "spectrogram": str(spectrogram)},
            "measurement_log": str(log_path),
            "report": str(base),
            "notes": [
                "Null dB values indicate silence; null LUFS also covers short or gated audio.",
                "Possible clipping means sample peak reaches full scale, not proof of distortion.",
                "Loudness and true peak use FFmpeg ebur128; peak and RMS use astats.",
                "Images show channels separately. No stereo-to-mono cancellation is introduced.",
            ],
        }
        log_path.write_text(measured.stderr)
        base.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        return result
    except BaseException:
        for output in (base, waveform, spectrogram, log_path):
            output.unlink(missing_ok=True)
        raise


def configure_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="audio_command", required=True)
    commands.add_parser("doctor", help="Check FFmpeg filters and saved input without recording")
    commands.add_parser("devices", help="List macOS audio input devices")
    capture = commands.add_parser("capture", help="Record a configured loopback input")
    capture.add_argument("--seconds", type=float, default=8)
    capture.add_argument(
        "--device", help="Loopback name or ID; overrides environment and saved input"
    )
    capture.add_argument("--channels", type=int, default=2)
    capture.add_argument("--sample-rate", type=int, default=48000)
    inspect = commands.add_parser("inspect", help="Measure audio and create FFmpeg images")
    inspect.add_argument("path")


def execute(args: argparse.Namespace) -> int:
    result: dict[str, Any] | list[dict[str, Any]]
    try:
        if args.audio_command == "doctor":
            result = diagnostics()
            print(json.dumps(result, indent=2, allow_nan=False))
            return int(not result["inspection_ready"])
        if args.audio_command == "devices":
            result = list_devices()
        elif args.audio_command == "capture":
            device = args.device or configured_device()
            if not device:
                raise ValueError(
                    "Set --device, ABLETON_AUDIO_DEVICE, or ableton setup --audio-device NAME."
                )
            result = capture_audio(args.seconds, device, args.channels, args.sample_rate)
        else:
            result = inspect_audio(args.path)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Audio error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    configure_parser(parser)
    return execute(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
