"""Validated transcript and extraction result contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal

SCHEMA_VERSION = "1"
Status = Literal["success", "unavailable", "blocked", "failed"]
Completeness = Literal["verified", "unknown", "partial"]


class ValidationError(ValueError):
    """A transcript row or record does not satisfy the public contract."""


@dataclass(frozen=True)
class Segment:
    start: float
    text: str
    end: float | None = None
    end_source: Literal["source", "estimated", "unknown"] = "unknown"
    source_index: int | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or not isfinite(self.start):
            raise ValidationError("segment start must be finite and nonnegative")
        if not self.text.strip():
            raise ValidationError("segment text must not be empty")
        if self.end is not None and (self.end < self.start or not isfinite(self.end)):
            raise ValidationError("segment end must be finite and >= start")
        if self.end is None and self.end_source != "unknown":
            raise ValidationError("an absent end time must have unknown provenance")

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "end_source": self.end_source,
                "text": self.text, "source_index": self.source_index}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Segment":
        return cls(float(value["start"]), str(value["text"]),
                   None if value.get("end") is None else float(value["end"]),
                   value.get("end_source", "unknown"), value.get("source_index"))


@dataclass(frozen=True)
class Transcript:
    video_id: str
    source_url: str
    language: str | None
    track_type: str | None
    segments: tuple[Segment, ...]
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.video_id or not self.source_url:
            raise ValidationError("video_id and source_url are required")
        if any(b.start < a.start for a, b in zip(self.segments, self.segments[1:])):
            raise ValidationError("segments must be ordered by start time")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "video_id": self.video_id,
                "source_url": self.source_url, "retrieved_at": self.retrieved_at,
                "language": self.language, "track_type": self.track_type,
                "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Transcript":
        return cls(value["video_id"], value["source_url"], value.get("language"),
                   value.get("track_type"), tuple(Segment.from_dict(s) for s in value["segments"]),
                   value.get("retrieved_at", ""), value.get("schema_version", SCHEMA_VERSION))


@dataclass(frozen=True)
class FetchResult:
    video_id: str
    status: Status
    transcript: Transcript | None = None
    error_code: str | None = None
    stage: str | None = None
    diagnostic: str | None = None
    retryable: bool = False
    completeness: Completeness = "unknown"

    def __post_init__(self) -> None:
        if self.status == "success" and self.transcript is None:
            raise ValidationError("successful results require a transcript")
        if self.status != "success" and not self.error_code:
            raise ValidationError("unsuccessful results require an error code")

    def to_dict(self) -> dict[str, Any]:
        return {"video_id": self.video_id, "status": self.status,
                "transcript": self.transcript.to_dict() if self.transcript else None,
                "error_code": self.error_code, "stage": self.stage,
                "diagnostic": self.diagnostic, "retryable": self.retryable,
                "completeness": self.completeness}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FetchResult":
        transcript = value.get("transcript")
        return cls(value["video_id"], value["status"],
                   Transcript.from_dict(transcript) if transcript else None,
                   value.get("error_code"), value.get("stage"), value.get("diagnostic"),
                   bool(value.get("retryable", False)), value.get("completeness", "unknown"))


TranscriptSegment = Segment
TranscriptRecord = Transcript
ExtractionResult = FetchResult
