"""Command-line entry point for local files."""

import argparse
import sys
from pathlib import Path

from video_transcribe import Transcriber


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe local audio or video with CUDA turbo.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("transcripts"))
    parser.add_argument("--cache-dir", type=Path, help="Persistent model download directory")
    parser.add_argument("--compute-type", choices=["float16", "int8_float16"], default="float16")
    args = parser.parse_args()
    try:
        # Load lazily so invalid media fails before model initialization.
        transcriber = Transcriber(compute_type=args.compute_type, cache_dir=args.cache_dir)
        try:
            transcript = transcriber.transcribe(args.source)
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
