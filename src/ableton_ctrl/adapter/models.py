"""Small stdlib-only wire models used inside Ableton Live's Python runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class MemberOutcome:
    member: str
    status: Literal["unavailable", "read_failed", "excluded"]
    reason: str


@dataclass(frozen=True)
class ObjectObservation:
    source_id: str
    type: str
    path: str | None
    properties: dict[str, JsonValue]
    relationships: dict[str, list[str]]
    outcomes: list[MemberOutcome]
    captured_at: datetime
    update_mode: Literal["replace", "patch"] = "replace"
    attempted_members: list[str] = field(default_factory=list)

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        record = asdict(self)
        if mode == "json":
            record["captured_at"] = self.captured_at.isoformat()
        return record
