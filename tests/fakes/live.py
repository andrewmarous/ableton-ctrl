from __future__ import annotations

from enum import Enum
from typing import Any


class FakeMode(Enum):
    SESSION = "session"


class FakeClip:
    def __init__(self, name: str = "Loop") -> None:
        self.name = name
        self.color = 255


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None) -> None:
        self.clip = clip
        self.has_clip = clip is not None

    def fire(self) -> None:
        raise AssertionError("callables must never be invoked")

    def delete_clip(self) -> None:
        raise AssertionError("callables must never be invoked")


class FakeTrack:
    name = "Bass"
    color = 16711680

    def __init__(self) -> None:
        self.devices: list[object] = []
        self.clip_slots: list[object] = []

    def __getattribute__(self, name: str) -> Any:
        if name in {"start_playing", "stop_playing"}:
            raise AssertionError("excluded callables must never be retrieved")
        return super().__getattribute__(name)

    def start_playing(self) -> None:
        raise AssertionError("callables must never be invoked")

    @property
    def broken(self) -> str:
        raise RuntimeError("fixture read failure: secret value")


class FakeSong:
    def __init__(self, tracks: list[FakeTrack] | None = None) -> None:
        self.name = "Live Set"
        self.tracks = tracks or []
        self.scenes: list[object] = []
        self.master_track: FakeTrack | None = None
        self.mode = FakeMode.SESSION
        self.binary = b"abc"
        self.loop = self
        self.deep: Any = [[[[[[[[[1]]]]]]]]]
        self.huge = list(range(1001))
