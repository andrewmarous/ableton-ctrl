"""Command line interface for ytkit."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from .fetch import fetch_many
from .models import FetchResult
from .organize import paragraphs, to_markdown, to_plain


def _export(results: list[FetchResult], fmt: str, raw: bool) -> str:
    if fmt == "json":
        return json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False) + "\n"
    parts = []
    for result in results:
        if result.status != "success" or not result.transcript:
            continue
        segs = [s.to_dict() for s in result.transcript.segments]
        if raw:
            parts.append("\n".join(s["text"] for s in segs))
        else:
            try:
                para = paragraphs(segs)
            except ValueError:
                para = segs
            parts.append(to_plain(para) if fmt == "txt" else to_markdown(para, result.video_id))
    return "\n\n".join(parts) + ("\n" if parts else "")


def _atomic_write(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".ytkit-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ytkit", description=__doc__)
    ap.add_argument("video", nargs="+", help="YouTube video IDs or watch URLs")
    ap.add_argument("--format", choices=("md", "txt", "json"), default="md")
    ap.add_argument("--out", default="")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--control", default="")
    args = ap.parse_args(argv)
    try:
        results = fetch_many(args.video + ([args.control] if args.control else []))
    except ValueError as exc:
        ap.error(str(exc))
    requested = [results[v] for v in dict.fromkeys(args.video)]
    if args.control:
        control = results[args.control]
        if control.status != "success":
            print("control failed: %s" % (control.diagnostic or control.error_code), file=sys.stderr)
        else:
            print("control %s: %d segments" % (args.control, len(control.transcript.segments)), file=sys.stderr)
    for result in requested:
        if result.status != "success":
            print("%s: %s (%s)" % (result.video_id, result.diagnostic or result.error_code, result.status), file=sys.stderr)
    text = _export(requested, args.format, args.raw)
    if args.out:
        if any(r.status == "success" for r in requested):
            _atomic_write(args.out, text)
            print("wrote %s" % args.out, file=sys.stderr)
    elif text:
        sys.stdout.write(text)
    successful = sum(r.status == "success" for r in requested)
    if successful == len(requested):
        return 0
    return 1 if successful == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
