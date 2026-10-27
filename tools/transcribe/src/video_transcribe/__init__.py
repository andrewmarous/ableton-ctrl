"""Sequential, process-owned transcription. No server or scraper dependencies."""

from __future__ import annotations

import json
import platform
import subprocess
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .cpp import BackendError, CppBackend, MODELS


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
    backend: str = "cuda"
    compute_type: str = "float16"
    threads: int | None = None

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
        raise RuntimeError(
            "FFmpeg is missing. Install it with brew install ffmpeg (macOS) "
            "or sudo apt install ffmpeg (Ubuntu)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg could not decode {source}: {exc.stderr.strip()}") from exc


class Transcriber:
    """Select local inference. Use from one thread and process files sequentially."""

    def __init__(
        self,
        *,
        compute_type: str = "float16",
        cache_dir: str | Path | None = None,
        backend: str = "auto",
        model: str | None = None,
        cpu_model: str = "base.en",
        whisper_cli: str | Path | None = None,
        threads: int = 4,
    ) -> None:
        if compute_type not in {"float16", "int8_float16"}:
            raise ValueError("compute_type must be float16 or int8_float16")
        if backend not in {"auto", "cuda", "metal", "cpu"}:
            raise ValueError("backend must be auto, cuda, metal, or cpu")
        if model is not None and model not in MODELS:
            raise ValueError(f"model must be one of {', '.join(MODELS)}")
        if cpu_model not in {"tiny.en", "base.en", "small.en"}:
            raise ValueError("cpu_model must be tiny.en, base.en, or small.en")
        if threads < 1:
            raise ValueError("threads must be positive")
        if backend == "cuda" and model not in {None, "turbo"}:
            raise ValueError("The CUDA backend currently supports only turbo")
        self.requested_backend = backend
        self.backend = backend
        self.requested_model = model
        self.cpu_model = cpu_model
        self.whisper_cli = str(whisper_cli) if whisper_cli is not None else None
        self.threads = threads
        self.compute_type = compute_type
        self.cache_dir = str(cache_dir) if cache_dir is not None else None
        self.model_name = "turbo"
        self._model: Any = None
        self._cpp: CppBackend | None = None

    def load(self) -> Transcriber:
        """Initialize the backend and cache its model. Auto mode permits CPU fallback."""
        if self._model is not None or self._cpp is not None:
            return self
        if self.backend == "auto":
            if platform.system() == "Darwin" and platform.machine() == "arm64":
                self.backend = "metal"
            else:
                try:
                    import ctranslate2

                    self.backend = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
                except (ImportError, OSError, RuntimeError):
                    self.backend = "cpu"
            if self.backend == "cpu":
                warnings.warn(
                    f"No supported GPU detected. Using CPU with {self.requested_model or self.cpu_model}.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        try:
            self._load_backend()
        except BackendError as exc:
            if self.requested_backend != "auto" or self.backend == "cpu":
                raise
            self._fallback(exc)
        return self

    def _load_backend(self) -> None:
        self.model_name = self.requested_model or (
            self.cpu_model if self.backend == "cpu" else "turbo"
        )
        if self.backend == "cuda":
            if self.model_name != "turbo":
                raise ValueError("The CUDA backend currently supports only turbo")
            try:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_name,
                    device="cuda",
                    device_index=0,
                    compute_type=self.compute_type,
                    download_root=self.cache_dir,
                    num_workers=1,
                )
            except (ImportError, OSError, RuntimeError) as exc:
                raise BackendError(f"CUDA initialization failed: {exc}") from exc
        else:
            if self.backend == "metal" and not (
                platform.system() == "Darwin" and platform.machine() == "arm64"
            ):
                raise BackendError("The Metal backend requires an Apple Silicon Mac")
            cache = (
                Path(self.cache_dir).expanduser()
                if self.cache_dir
                else (Path.home() / ".cache" / "video-transcribe")
            )
            self._cpp = CppBackend(
                self.backend, self.model_name, cache, self.whisper_cli, self.threads
            )

    def _fallback(self, error: Exception) -> None:
        warnings.warn(
            f"{self.backend} failed: {error}. Falling back to CPU with {self.cpu_model}.",
            RuntimeWarning,
            stacklevel=2,
        )
        self.close()
        self.backend = "cpu"
        # A fallback always uses the configured smaller model, not the GPU model.
        self.requested_model = self.cpu_model
        self._load_backend()

    def close(self) -> None:
        """Release CUDA weights. whisper.cpp releases weights after each subprocess."""
        self._cpp = None
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
            try:
                return self._transcribe_audio(source, audio)
            except (BackendError, RuntimeError) as exc:
                if self.requested_backend != "auto" or self.backend == "cpu":
                    raise
                self._fallback(exc)
                return self._transcribe_audio(source, audio)

    def _transcribe_audio(self, source: Path, audio: Path) -> Transcript:
        if self._cpp is not None:
            duration, rows = self._cpp.transcribe(audio)
            segments = tuple(
                Segment(i, start, end, text) for i, (start, end, text) in enumerate(rows)
            )
            precision = "f16-weights"
        else:
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
            duration = info.duration
            precision = self.compute_type
        return Transcript(
            source=str(source),
            model=self.model_name,
            language="en",
            duration=duration,
            text=" ".join(segment.text for segment in segments if segment.text),
            segments=segments,
            backend=self.backend,
            compute_type=precision,
            threads=self.threads if self._cpp is not None else None,
        )
