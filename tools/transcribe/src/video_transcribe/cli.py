"""Command-line entry point for local files."""

import argparse
import sys
from pathlib import Path

from video_transcribe import Transcriber


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe local audio or video with Metal, CUDA, or CPU inference."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("transcripts"))
    parser.add_argument("--cache-dir", type=Path, help="Persistent model download directory")
    parser.add_argument("--compute-type", choices=["float16", "int8_float16"], default="float16")
    parser.add_argument("--backend", choices=["auto", "metal", "cuda", "cpu"], default="auto")
    parser.add_argument("--model", choices=["turbo", "tiny.en", "base.en", "small.en"])
    parser.add_argument(
        "--cpu-model", choices=["tiny.en", "base.en", "small.en"], default="base.en"
    )
    parser.add_argument("--whisper-cli", type=Path, help="Path to the whisper.cpp executable")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        # Load lazily so invalid media fails before model initialization.
        transcriber = Transcriber(
            compute_type=args.compute_type,
            cache_dir=args.cache_dir,
            backend=args.backend,
            model=args.model,
            cpu_model=args.cpu_model,
            whisper_cli=args.whisper_cli,
            threads=args.threads,
        )
        try:
            transcript = transcriber.transcribe(args.source)
            print(
                f"Transcription backend: {transcript.backend}; model: {transcript.model}",
                file=sys.stderr,
            )
            paths = transcript.write(args.output_dir)
        finally:
            transcriber.close()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Transcription failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
