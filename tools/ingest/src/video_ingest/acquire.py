from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


class AcquireError(RuntimeError):
    pass


def command(args: list[str]) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as exc:
        raise AcquireError(f"missing dependency: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise AcquireError(exc.stderr.strip() or f"command failed: {args[0]}") from exc


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AcquireError("URL must be public http(s)")
    query = parse_qs(parsed.query)
    if any(k in query for k in ("list", "playlist")) and not query.get("v"):
        raise AcquireError("playlist-only URLs are not supported")


def probe(path: Path) -> dict[str, Any]:
    data = json.loads(
        command(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
        )
    )
    streams = data.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not audio:
        raise AcquireError("video has no audio stream")
    if not video:
        raise AcquireError("video has no video stream")
    return {
        "audio_stream_index": audio[0].get("index"),
        "video_stream_index": video[0].get("index"),
        "streams": streams,
        "format": data.get("format", {}),
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
    }


def prepare(url: str, raw_dir: Path, cache_dir: Path) -> dict[str, Any]:
    check_url(url)
    for dependency in ("yt-dlp", "ffmpeg", "ffprobe"):
        if not shutil.which(dependency):
            raise AcquireError(f"{dependency} is missing")
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    info = json.loads(command(["yt-dlp", "--dump-single-json", "--no-playlist", url]))
    if info.get("is_live") or info.get("live_status") in {"is_live", "was_live", "post_live"}:
        raise AcquireError("live streams are not supported")
    video_id = str(info.get("id") or "")
    if not video_id:
        raise AcquireError("source has no stable video ID")
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + video_id
    job = cache_dir / job_id
    job.mkdir()
    output = job / "video.%(ext)s"
    command(
        [
            "yt-dlp",
            "--no-playlist",
            "--format",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mkv",
            "--output",
            str(output),
            url,
        ]
    )
    media = next((p for p in job.glob("video.*") if p.suffix not in {".json", ".part"}), None)
    if media is None:
        raise AcquireError("yt-dlp produced no media")
    metadata = {
        k: info.get(k)
        for k in (
            "id",
            "title",
            "channel",
            "uploader",
            "upload_date",
            "timestamp",
            "duration",
            "webpage_url",
            "original_url",
            "extractor",
        )
    }
    metadata.update(
        {
            "canonical_url": info.get("webpage_url") or url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "media_filename": media.name,
            "media_sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
        }
    )
    metadata["probe"] = probe(media)
    (job / "source-download.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    (job / "job.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "revision_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + video_id,
                "url": url,
                "raw_dir": str(raw_dir.resolve()),
                "job_dir": str(job.resolve()),
                "video_id": video_id,
                "media_path": str(media.resolve()),
                "duration": metadata["probe"]["duration"],
                "status": "prepared",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "job": str(job),
        "media": str(media),
        "transcript_output": str(job / "transcripts"),
        "source": str(job / "source-download.json"),
    }
