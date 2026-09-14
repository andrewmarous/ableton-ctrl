"""Sequential, process-owned transcription. No server or scraper dependencies."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


@dataclass(frozen=True)
class Segment:
    id: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    source: str
    model: str
    language: str
    duration: float
    text: str
    segments: tuple[Segment, ...]
    schema_version: int = 1

    def write(self, output_dir: str | Path) -> tuple[Path, Path]:
        """Write UTF-8 text and JSON. Replace existing outputs with the same name."""
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        name = Path(self.source).name
        text_path = directory / f"{name}.txt"
        json_path = directory / f"{name}.json"
        text_path.write_text(self.text + "\n" if self.text else "", encoding="utf-8")
        json_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        return text_path, json_path


def extract_audio(source: Path, destination: Path) -> None:
    """Decode the first audio stream to mono 16 kHz PCM without changing its speed."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is missing. Install it with: sudo apt install ffmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg could not decode {source}: {exc.stderr.strip()}") from exc


class Transcriber:
    """Own one CUDA model. Use from one thread and process files sequentially."""

    def __init__(
        self,
        *,
        compute_type: str = "float16",
        cache_dir: str | Path | None = None,
    ) -> None:
        if compute_type not in {"float16", "int8_float16"}:
            raise ValueError("compute_type must be float16 or int8_float16")
        self.compute_type = compute_type
        self.cache_dir = str(cache_dir) if cache_dir is not None else None
        self.model_name = "turbo"
        self._model: Any = None

    def load(self) -> Transcriber:
        """Load once. The first load downloads the model into the persistent cache."""
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device="cuda",
                device_index=0,
                compute_type=self.compute_type,
                download_root=self.cache_dir,
                num_workers=1,
            )
        return self

    def close(self) -> None:
        """Unload model weights from the GPU. Repeated calls have no effect."""
        if self._model is not None:
            self._model.model.unload_model()
            self._model = None

    def __enter__(self) -> Transcriber:
        return self.load()

    def __exit__(self, *_: object) -> None:
        self.close()

    def transcribe(self, source: str | Path) -> Transcript:
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Input file does not exist: {source}")
        with TemporaryDirectory(prefix="video-transcribe-") as directory:
            audio = Path(directory) / "audio.wav"
            extract_audio(source, audio)
            self.load()
            chunks, info = self._model.transcribe(
                str(audio),
                language="en",
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                word_timestamps=False,
                condition_on_previous_text=False,
            )
            # faster-whisper is lazy. Finish inference before deleting the audio.
            segments = tuple(
                Segment(id=chunk.id, start=chunk.start, end=chunk.end, text=chunk.text.strip())
                for chunk in chunks
            )
            return Transcript(
                source=str(source),
                model=self.model_name,
                language="en",
                duration=info.duration,
                text=" ".join(segment.text for segment in segments if segment.text),
                segments=segments,
            )
