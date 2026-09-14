"""Explicit audio-relative to video-presentation timeline mapping."""

from __future__ import annotations
from dataclasses import dataclass


class TimelineError(ValueError):
    pass


@dataclass(frozen=True)
class Timeline:
    audio_start: float = 0.0
    video_start: float = 0.0
    duration: float | None = None

    def audio_to_video(self, seconds: float) -> float:
        if seconds != seconds or seconds in (float("inf"), float("-inf")):
            raise TimelineError("timestamp must be finite")
        value = seconds - self.audio_start + self.video_start
        if self.duration is not None and not 0 <= seconds <= self.duration:
            raise TimelineError("timestamp outside audio duration")
        return value


def map_timestamp(
    seconds: float,
    *,
    audio_start: float = 0.0,
    video_start: float = 0.0,
    duration: float | None = None,
) -> float:
    return Timeline(audio_start, video_start, duration).audio_to_video(seconds)
