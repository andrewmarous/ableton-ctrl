"""Small, dependency-free contracts for video ingestion."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

CATEGORIES = {"unclear_visual_reference", "explanation_benefits_from_visual"}
ROLES = ("before", "at", "after")


class ValidationError(ValueError):
    pass


def finite(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValidationError(f"{name} must be finite")
    return float(value)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain an object")
    return value


def transcript_segments(path: Path) -> tuple[dict[str, Any], ...]:
    value = load_json(path)
    segments = value.get("segments")
    duration = finite(value.get("duration"), "duration")
    if duration < 0 or not isinstance(segments, list):
        raise ValidationError("invalid transcript segments")
    previous = 0.0
    result = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValidationError("segment must be an object")
        if not isinstance(segment.get("id"), int):
            raise ValidationError("segment id must be an integer")
        start, end = (
            finite(segment.get("start"), "segment start"),
            finite(segment.get("end"), "segment end"),
        )
        if start < 0 or end < start or end > duration + 2.0 or start < previous:
            raise ValidationError("segment timestamps must be ordered and within duration")
        if not isinstance(segment.get("text"), str):
            raise ValidationError("segment text must be a string")
        previous = end
        result.append(segment)
    return tuple(result)


def validate_candidates(
    path: Path, segments: tuple[dict[str, Any], ...], duration: float | None = None
) -> dict[str, Any]:
    value = load_json(path)
    if (
        value.get("schema_version") != 1
        or value.get("selection_method") != "calling_agent_transcript_analysis"
    ):
        raise ValidationError("unsupported candidate schema or selection method")
    status = value.get("analysis_status")
    if status not in {"completed", "skipped"}:
        raise ValidationError("invalid analysis_status")
    candidates = value.get("candidates")
    ranges = value.get("reviewed_segment_ranges")
    if not isinstance(candidates, list) or not isinstance(ranges, list):
        raise ValidationError("invalid candidates or reviewed ranges")
    for reviewed in ranges:
        if (
            not isinstance(reviewed, list)
            or len(reviewed) != 2
            or any(not isinstance(v, int) for v in reviewed)
            or reviewed[0] < 0
            or reviewed[1] < reviewed[0]
        ):
            raise ValidationError("reviewed segment ranges must be [first, last]")
    if status == "skipped" and (candidates or ranges):
        raise ValidationError("skipped analysis must have no candidates or ranges")
    if not isinstance(value.get("offsets_seconds"), dict):
        raise ValidationError("offsets_seconds is required")
    for role in ROLES:
        finite(value["offsets_seconds"].get(role), f"offset {role}")
    ids: set[str] = set()
    by_id = {s["id"]: s for s in segments}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValidationError("candidate must be an object")
        cid = candidate.get("id")
        if not isinstance(cid, str) or cid in ids:
            raise ValidationError("candidate IDs must be unique strings")
        ids.add(cid)
        timestamp = finite(candidate.get("timestamp_seconds"), "candidate timestamp")
        if duration is not None and not 0 <= timestamp <= duration:
            raise ValidationError("candidate outside audio duration")
        refs = candidate.get("segment_ids")
        if not isinstance(refs, list) or not refs or any(i not in by_id for i in refs):
            raise ValidationError("invalid segment reference")
        if not any(by_id[i]["start"] <= timestamp <= by_id[i]["end"] for i in refs):
            raise ValidationError("timestamp is outside supporting segments")
        if (
            not isinstance(candidate.get("categories"), list)
            or not candidate["categories"]
            or any(c not in CATEGORIES for c in candidate["categories"])
        ):
            raise ValidationError("invalid candidate category")
        for field in ("reason", "visual_question", "timing_precision", "review_status"):
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise ValidationError(f"candidate {field} is required")
    return value


@dataclass(frozen=True)
class Job:
    job_id: str
    revision_id: str
    url: str
    raw_dir: str
    job_dir: str
    video_id: str | None = None
    media_path: str | None = None
    duration: float | None = None
    status: str = "prepared"

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "Job":
        return cls(**load_json(path))
