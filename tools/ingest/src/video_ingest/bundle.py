from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from .models import Job, ValidationError, load_json, transcript_segments, validate_candidates


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def publish(job_path: Path) -> dict:
    job = Job.read(job_path / "job.json")
    transcripts = list((job_path / "transcripts").glob("*.txt")) + list(
        (job_path / "transcripts").glob("*.json")
    )
    if len(transcripts) < 2:
        raise ValidationError("both transcript outputs are required")
    transcript_json = next((p for p in transcripts if p.suffix == ".json"), None)
    if transcript_json is None:
        raise ValidationError("timestamped transcript is required")
    segments = transcript_segments(transcript_json)
    transcript = load_json(transcript_json)
    candidates_path = job_path / "candidates.json"
    if not candidates_path.is_file():
        raise ValidationError("candidates.json is required; use explicit skipped analysis")
    candidates = validate_candidates(candidates_path, segments, float(transcript["duration"]))
    frames_path = job_path / "frames.json"
    if candidates["analysis_status"] == "completed":
        if not frames_path.is_file():
            raise ValidationError("frames.json is required for completed analysis")
        frames = load_json(frames_path).get("frames", [])
        expected = len(candidates["candidates"]) * 3
        if len(frames) != expected:
            raise ValidationError(
                f"expected exactly three frame roles per candidate, got {len(frames)}"
            )
    elif not frames_path.is_file():
        (job_path / "frames.json").write_text(
            json.dumps({"schema_version": 1, "frames": []}, indent=2) + "\n", encoding="utf-8"
        )
    destination = Path(job.raw_dir) / "youtube" / str(job.video_id) / job.revision_id
    if destination.exists():
        raise ValidationError(f"revision already exists: {destination}")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{job.revision_id}-",
            dir=str(destination.parent if destination.parent.exists() else Path(job.raw_dir)),
        )
    )
    try:
        (staging / "frames").mkdir()
        source = load_json(job_path / "source-download.json")
        source.update(
            {
                "schema_version": 1,
                "video_id": job.video_id,
                "revision_id": job.revision_id,
                "job_id": job.job_id,
                "screenshot_analysis_status": candidates["analysis_status"],
                "warnings": [],
            }
        )
        (staging / "source.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
        for path in transcripts + [candidates_path, job_path / "frames.json"]:
            shutil.copy2(path, staging / path.name)
        for image in (job_path / "frames").rglob("*"):
            if image.is_file():
                target = staging / image.relative_to(job_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image, target)
        lines = [
            f"# {source.get('title') or job.video_id}",
            "",
            f"Source: {source.get('canonical_url')}",
            "",
            "## Transcripts",
            "",
        ]
        for path in transcripts:
            lines.append(f"- [{path.name}]({path.name})")
        lines += ["", f"Screenshot analysis: **{candidates['analysis_status']}**", ""]
        for candidate in candidates["candidates"]:
            lines += [
                f"## {candidate['id']} — {', '.join(candidate['categories'])}",
                "",
                candidate["reason"],
                "",
                f"Visual question: {candidate['visual_question']}",
                "",
            ]
            for segment in segments:
                if segment["id"] in candidate["segment_ids"]:
                    lines.append(f"> [{segment['id']}] {segment['text']}")
            lines.append("")
            for frame in load_json(job_path / "frames.json").get("frames", []):
                if frame.get("candidate_id") == candidate["id"]:
                    if frame["status"] == "extracted":
                        lines.append(
                            f"- **{frame['role']}** ({frame['requested_timestamp_seconds']}s): [{frame['image_path']}]({frame['image_path']})"
                        )
                    else:
                        lines.append(
                            f"- **{frame['role']}**: unavailable ({frame.get('reason', 'unknown')})"
                        )
        (staging / "context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        artifacts = []
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                artifacts.append(
                    {
                        "path": str(path.relative_to(staging)),
                        "bytes": path.stat().st_size,
                        "sha256": sha(path),
                    }
                )
        (staging / "manifest.json").write_text(
            json.dumps(
                {"schema_version": 1, "revision_id": job.revision_id, "artifacts": artifacts},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "revision": str(destination),
        "artifacts": len(artifacts),
        "candidates": len(candidates["candidates"]),
    }
