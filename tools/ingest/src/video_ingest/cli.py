from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path
from .acquire import prepare
from .bundle import publish
from .frames import extract
from .models import ValidationError, Job


def result(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(prog="video-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("url")
    p.add_argument("--raw-dir", required=True, type=Path)
    p.add_argument("--cache-dir", required=True, type=Path)
    p = sub.add_parser("screenshots")
    p.add_argument("--job", required=True, type=Path)
    p.add_argument("--candidates", required=True, type=Path)
    p = sub.add_parser("publish")
    p.add_argument("--job", required=True, type=Path)
    p = sub.add_parser("transcribe")
    p.add_argument("--job", required=True, type=Path)
    p.add_argument("--command", nargs="+", help="transcriber command; defaults to video-transcribe")
    try:
        args = parser.parse_args()
        if args.command == "prepare":
            result(prepare(args.url, args.raw_dir, args.cache_dir))
        elif args.command == "screenshots":
            result(extract(args.job, args.candidates))
        elif args.command == "publish":
            result(publish(args.job))
        else:
            job = Job.read(args.job / "job.json")
            out = args.job / "transcripts"
            out.mkdir(exist_ok=True)
            command = args.command or ["video-transcribe"]
            subprocess.run(command + [job.media_path or "", "--output-dir", str(out)], check=True)
            result({"job": str(args.job), "transcripts": str(out)})
        return 0
    except (
        ValidationError,
        OSError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "stage": getattr(args, "command", "unknown"),
                        "code": type(exc).__name__,
                        "diagnostic": str(exc),
                        "job": str(getattr(args, "job", "")),
                    }
                }
            ),
            file=sys.stderr,
        )
        return 2 if isinstance(exc, (ValidationError, ValueError)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
