"""Local loopback capture and file inspection, independent of Live control."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import uuid


def artifact_path(suffix: str) -> Path:
    root = Path(os.environ.get("ABLETON_AUDIO_DIR", "artifacts/audio")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{uuid.uuid4().hex}{suffix}"


def capture_audio(seconds: float, device: str, channels: int = 2, samplerate: int = 48000) -> dict:
    import sounddevice as sd
    import soundfile as sf

    if not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ValueError("Duration must be greater than zero and at most 300 seconds.")
    if channels not in (1, 2) or not 8000 <= samplerate <= 192000:
        raise ValueError("Use 1 or 2 channels and a sample rate from 8000 to 192000 Hz.")
    selected = int(device) if device.isdecimal() else device
    info = sd.query_devices(selected, "input")
    path = artifact_path(".wav")
    frames = round(seconds * samplerate)
    # A stream avoids sounddevice's process-global convenience recording state.
    with sd.InputStream(
        device=selected, channels=channels, samplerate=samplerate, dtype="float32"
    ) as stream:
        print("Capture ready: recording input now.", file=sys.stderr, flush=True)
        data, overflow = stream.read(frames)
    if overflow:
        raise RuntimeError("Audio input overflowed. Retry the capture.")
    sf.write(path, data, samplerate, subtype="FLOAT")
    result = {
        "path": str(path),
        "device": info["name"],
        "sample_rate": samplerate,
        "channels": channels,
        "duration_seconds": frames / samplerate,
    }
    path.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def inspect_audio(path: str) -> dict:
    import numpy as np
    import soundfile as sf
    from scipy import signal
    import pyloudnorm as pyln
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    source = Path(path).resolve()
    info = sf.info(source)
    if info.frames == 0 or info.duration > 300 or info.channels not in (1, 2):
        raise ValueError("Use a nonempty mono or stereo file of at most 300 seconds.")
    data, rate = sf.read(source, always_2d=True, dtype="float64")
    if not np.isfinite(data).all():
        raise ValueError("Audio contains non-finite samples.")

    def db(value):
        return float(20 * np.log10(value)) if value > 0 else None

    peak = float(np.max(np.abs(data)))
    rms = float(np.sqrt(np.mean(data**2)))
    loudness = None
    if len(data) >= math.ceil(0.4 * rate) and rms > 0:
        measured = float(pyln.Meter(rate).integrated_loudness(data))
        loudness = measured if math.isfinite(measured) else None
    correlation = None
    if data.shape[1] == 2 and np.all(np.std(data, axis=0) > 0):
        correlation = float(np.corrcoef(data.T)[0, 1])
    result = {
        "source": str(source),
        "sample_rate": rate,
        "channels": data.shape[1],
        "duration_seconds": len(data) / rate,
        "sample_peak_dbfs": db(peak),
        "rms_dbfs": db(rms),
        "integrated_lufs": loudness,
        "stereo_correlation": correlation,
        "samples_at_or_above_full_scale": int(np.count_nonzero(np.abs(data) >= 1)),
        "notes": [
            "Null dB values mean silence. Null LUFS also covers clips below 400 ms or the loudness gate.",
            "Full-scale samples indicate possible clipping, not proof of distortion.",
            "Spectrum and spectrogram average channel power; they do not sum stereo channels.",
        ],
    }
    image = artifact_path(".png")
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
    # Min/max envelopes retain short peaks even in long captures.
    edges = np.linspace(0, len(data), min(len(data), 2400) + 1, dtype=int)
    times = edges[:-1] / rate
    for channel in range(data.shape[1]):
        low = [data[a:b, channel].min() for a, b in zip(edges[:-1], edges[1:])]
        high = [data[a:b, channel].max() for a, b in zip(edges[:-1], edges[1:])]
        axes[0].fill_between(times, low, high, alpha=0.5, label=f"Channel {channel + 1}")
    axes[0].set(xlabel="Time (s)", ylabel="Amplitude", title="Waveform")
    axes[0].legend()
    nperseg = min(2048, len(data))
    freq, time, power = signal.spectrogram(
        data, fs=rate, nperseg=nperseg, noverlap=nperseg // 2, axis=0
    )
    power = power.mean(axis=1)
    axes[1].pcolormesh(
        time, freq, 10 * np.log10(np.maximum(power, 1e-16)), shading="auto", vmin=-120, vmax=-20
    )
    axes[1].set(xlabel="Time (s)", ylabel="Frequency (Hz)", title="Spectrogram (dB/Hz)")
    positive = freq > 0
    axes[2].plot(freq[positive], 10 * np.log10(np.maximum(power.mean(axis=-1)[positive], 1e-16)))
    axes[2].set(xlabel="Frequency (Hz)", ylabel="Power (dB/Hz)", title="Average spectrum")
    axes[2].set_xscale("log")
    axes[2].set_xlim(20, max(21, rate / 2))
    fig.savefig(image, dpi=120)
    plt.close(fig)
    result["image"] = str(image)
    report = image.with_suffix(".json")
    result["report"] = str(report)
    report.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List audio input devices")
    capture = commands.add_parser("capture", help="Record a configured loopback input")
    capture.add_argument("--seconds", type=float, default=8)
    capture.add_argument("--device", default=os.environ.get("ABLETON_AUDIO_DEVICE"))
    capture.add_argument("--channels", type=int, default=2)
    capture.add_argument("--sample-rate", type=int, default=48000)
    inspect = commands.add_parser("inspect", help="Measure audio and create a plot")
    inspect.add_argument("path")
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            import sounddevice as sd

            result = [
                {
                    "id": i,
                    "name": d["name"],
                    "input_channels": d["max_input_channels"],
                    "default_sample_rate": d["default_samplerate"],
                }
                for i, d in enumerate(sd.query_devices())
                if d["max_input_channels"] > 0
            ]
        elif args.command == "capture":
            if not args.device:
                raise ValueError("Set --device or ABLETON_AUDIO_DEVICE to the loopback input.")
            result = capture_audio(args.seconds, args.device, args.channels, args.sample_rate)
        else:
            result = inspect_audio(args.path)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except ImportError as exc:
        print(f"Install audio dependencies: uv sync --extra audio ({exc})", file=sys.stderr)
    except Exception as exc:
        print(f"Audio error: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
