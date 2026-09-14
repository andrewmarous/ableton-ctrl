from __future__ import annotations
import json
import subprocess
from pathlib import Path
from .models import ROLES, ValidationError, load_json, transcript_segments, validate_candidates


def _ffmpeg(media: Path, target: float, output: Path) -> tuple[int, int, float | None]:
    if target < 0:
        return (0, 0, None)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(target),
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is missing") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or "frame extraction failed") from exc
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("FFmpeg produced an empty frame")
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=width,height,best_effort_timestamp_time",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        frame = json.loads(probe.stdout).get("frames", [{}])[0]
        actual = frame.get("best_effort_timestamp_time")
        return (
            int(frame.get("width", 0)),
            int(frame.get("height", 0)),
            (float(actual) if actual is not None else None),
        )
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
        return (0, 0, None)


def extract(job: Path, candidates_path: Path) -> dict:
    from .models import Job

    job_data = Job.read(job / "job.json")
    media = Path(job_data.media_path or "")
    transcript = next(job.glob("transcripts/*.json"), None)
    if transcript is None:
        raise ValidationError("timestamped transcript is missing")
    segments = transcript_segments(transcript)
    duration = load_json(transcript).get("duration")
    candidates = validate_candidates(candidates_path, segments, float(duration))
    frames_dir = job / "frames"
    frames_dir.mkdir(exist_ok=True)
    records = []
    for candidate in candidates["candidates"]:
        cid, timestamp = candidate["id"], float(candidate["timestamp_seconds"])
        group = frames_dir / cid
        group.mkdir(exist_ok=True)
        for role in ROLES:
            offset = float(candidates["offsets_seconds"][role])
            requested = timestamp + offset
            record = {
                "candidate_id": cid,
                "role": role,
                "offset_seconds": offset,
                "requested_timestamp_seconds": requested,
                "transcript_segment_ids": candidate["segment_ids"],
                "review_status": "unreviewed",
            }
            if requested < 0 or requested > float(duration):
                record.update(
                    status="unavailable", reason="requested timestamp is outside audio duration"
                )
            else:
                name = f"{role}-{round(requested * 1000):012d}.jpg"
                path = group / name
                width, height, actual = _ffmpeg(media, requested, path)
                record.update(
                    status="extracted",
                    image_path=str(path.relative_to(job)),
                    width=width,
                    height=height,
                    actual_frame_timestamp_seconds=actual,
                    mapped_audio_timestamp_seconds=actual,
                )
            records.append(record)
    (job / "frames.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "offsets_seconds": candidates["offsets_seconds"],
                "frames": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"frames": len(records), "job": str(job)}
