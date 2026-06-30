"""Budgeted, resumable discovery over explicitly allowlisted Live members."""

from __future__ import annotations

import inspect
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Literal, TypeAlias, cast
from uuid import uuid4

from ableton_ctrl.adapter.manifest import PropertySpec, RelationshipSpec, TypeSpec
from ableton_ctrl.adapter.models import JsonValue, MemberOutcome, ObjectObservation

_MAX_DEPTH = 8
_MAX_COLLECTION = 1_000
_MemberSpec: TypeAlias = PropertySpec | RelationshipSpec


@dataclass(frozen=True)
class DiscoveryBudget:
    max_members: int
    max_milliseconds: float

    def __post_init__(self) -> None:
        if self.max_members < 0 or self.max_milliseconds < 0:
            raise ValueError("discovery budgets cannot be negative")


@dataclass(frozen=True)
class CoverageEntry:
    source_id: str
    object_type: str
    member: str
    status: Literal["supported", "unavailable", "read_failed", "excluded"]
    reason: str | None = None


@dataclass(frozen=True)
class DiscoverySlice:
    observations: tuple[ObjectObservation, ...]
    coverage: tuple[CoverageEntry, ...]
    remaining_work: int
    complete: bool
    removed_source_ids: tuple[str, ...] = ()


@dataclass
class _WorkItem:
    value: object
    type_name: str
    source_id: str
    path: str
    member_index: int = 0
    properties: dict[str, JsonValue] = field(default_factory=dict)
    relationships: dict[str, list[str]] = field(default_factory=dict)
    outcomes: list[MemberOutcome] = field(default_factory=list)
    selected_members: tuple[_MemberSpec, ...] | None = None


class _NormalizationExcluded(ValueError):
    pass


class DiscoveryEngine:
    """Observe a Live graph without touching members absent from the manifest."""

    def __init__(
        self,
        manifest: dict[str, TypeSpec],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._manifest = manifest
        self._clock = clock
        self._work: deque[_WorkItem] = deque()
        self._identity: dict[int, str] = {}
        self._root_identity: int | None = None
        self._known: dict[int, tuple[object, str, str, str]] = {}
        self._target_poll_classes: frozenset[str] | None = None
        self._target_dirty: frozenset[tuple[int, str]] = frozenset()
        self._relationship_cache: dict[str, dict[str, list[str]]] = {}
        self._structural_pass = False
        self._replacement_active = False
        self._replacement_scheduled: set[int] = set()

    def observe(self, root: object, budget: DiscoveryBudget) -> DiscoverySlice:
        if self._root_identity != id(root) or not self._work:
            self._start(root)

        deadline = self._clock() + budget.max_milliseconds / 1_000
        observations: list[ObjectObservation] = []
        coverage: list[CoverageEntry] = []
        processed = 0

        while self._work and processed < budget.max_members and self._clock() < deadline:
            item = self._work[0]
            members = self._members(item.type_name)
            if item.member_index >= len(members):
                observations.append(self._finish(item))
                self._work.popleft()
                continue

            member = members[item.member_index]
            item.member_index += 1
            processed += 1
            coverage.append(self._observe_member(item, member))

        while self._work and self._work[0].member_index >= len(
            self._members(self._work[0].type_name)
        ):
            observations.append(self._finish(self._work.popleft()))

        return DiscoverySlice(
            observations=tuple(observations),
            coverage=tuple(coverage),
            remaining_work=len(self._work),
            complete=not self._work,
        )

    def observe_replacement(self, root: object, budget: DiscoveryBudget) -> DiscoverySlice:
        """Fully traverse reachable objects while preserving known identity IDs."""
        if self._root_identity != id(root):
            self._start(root)
        if not self._replacement_active:
            self._work.clear()
            self._replacement_active = True
            self._replacement_scheduled = {id(root)}
            type_name = self._resolve_type(root, "Song")
            source_id = self._identity.get(id(root), f"{type_name}:root")
            self._identity[id(root)] = source_id
            self._known[id(root)] = (root, type_name, source_id, type_name)
            self._work.append(_WorkItem(root, type_name, source_id, type_name))
        result = self._drain(budget)
        if result.complete:
            for identity in set(self._known) - self._replacement_scheduled:
                _, _, source_id, _ = self._known.pop(identity)
                self._identity.pop(identity, None)
                self._relationship_cache.pop(source_id, None)
            self._replacement_active = False
        return result

    def observe_targeted(
        self,
        root: object,
        budget: DiscoveryBudget,
        poll_classes: frozenset[str],
        dirty: frozenset[tuple[int, str]],
    ) -> DiscoverySlice:
        """Observe only due classes and explicitly dirtied object members."""
        if self._root_identity != id(root):
            self._work.clear()
            self._identity.clear()
            self._known.clear()
            self._root_identity = id(root)
            type_name = self._resolve_type(root, "Song")
            self._identity[id(root)] = f"{type_name}:root"
            self._known[id(root)] = (root, type_name, f"{type_name}:root", type_name)
        if not self._work:
            self._target_poll_classes = poll_classes
            self._target_dirty = dirty
            self._structural_pass = "structural" in poll_classes
            for identity, (value, type_name, source_id, path) in tuple(self._known.items()):
                selected = self._select_members(type_name, identity, poll_classes, dirty)
                if selected:
                    self._work.append(
                        _WorkItem(
                            value,
                            type_name,
                            source_id,
                            path,
                            selected_members=selected,
                        )
                    )
        result = self._drain(budget)
        if result.complete and self._structural_pass:
            removed = self._reconcile_reachability()
            removed_set = set(removed)
            self._structural_pass = False
            return DiscoverySlice(
                tuple(item for item in result.observations if item.source_id not in removed_set),
                result.coverage,
                result.remaining_work,
                result.complete,
                removed,
            )
        return result

    def _select_members(
        self,
        type_name: str,
        identity: int,
        poll_classes: frozenset[str],
        dirty: frozenset[tuple[int, str]],
    ) -> tuple[_MemberSpec, ...]:
        selected: list[_MemberSpec] = []
        for member in self._members_for_type(type_name):
            dirty_match = (identity, member.name) in dirty or (
                identity,
                member.live_member,
            ) in dirty
            if isinstance(member, RelationshipSpec):
                due = "structural" in poll_classes
            else:
                if member.poll_class == "fast":
                    cadence = "fast"
                elif member.poll_class in {"static", "structural"}:
                    cadence = "structural"
                else:
                    cadence = "normal"
                due = cadence in poll_classes
            if dirty_match or due:
                selected.append(member)
        return tuple(selected)

    def _drain(self, budget: DiscoveryBudget) -> DiscoverySlice:
        deadline = self._clock() + budget.max_milliseconds / 1_000
        observations: list[ObjectObservation] = []
        coverage: list[CoverageEntry] = []
        processed = 0
        while self._work and processed < budget.max_members and self._clock() < deadline:
            item = self._work[0]
            members = self._members(item.type_name)
            if item.member_index >= len(members):
                observations.append(self._finish(item))
                self._work.popleft()
                continue
            member = members[item.member_index]
            item.member_index += 1
            processed += 1
            coverage.append(self._observe_member(item, member))
        while self._work and self._work[0].member_index >= len(
            self._members(self._work[0].type_name)
        ):
            observations.append(self._finish(self._work.popleft()))
        return DiscoverySlice(
            tuple(observations),
            tuple(coverage),
            len(self._work),
            not self._work,
        )

    def _start(self, root: object) -> None:
        self._work.clear()
        self._identity.clear()
        self._root_identity = id(root)
        self._known.clear()
        self._target_poll_classes = None
        self._target_dirty = frozenset()
        type_name = self._resolve_type(root, "Song")
        source_id = f"{type_name}:root"
        self._identity[id(root)] = source_id
        self._known[id(root)] = (root, type_name, source_id, type_name)
        self._work.append(_WorkItem(root, type_name, source_id, type_name))

    def _members(self, type_name: str) -> tuple[_MemberSpec, ...]:
        if self._work and self._work[0].type_name == type_name:
            selected = self._work[0].selected_members
            if selected is not None:
                return selected
        return self._members_for_type(type_name)

    def _members_for_type(self, type_name: str) -> tuple[_MemberSpec, ...]:
        spec = self._manifest[type_name]
        return (*spec.properties, *spec.relationships)

    def _observe_member(self, item: _WorkItem, member: _MemberSpec) -> CoverageEntry:
        if member.exclusion_reason is not None:
            return self._outcome(item, member, "excluded", member.exclusion_reason)

        missing = object()
        static_value = inspect.getattr_static(item.value, member.live_member, missing)
        if static_value is missing:
            return self._outcome(item, member, "unavailable", "Member is not available.")
        if callable(static_value) and not isinstance(static_value, property):
            return self._outcome(
                item,
                member,
                "excluded",
                "Callable members cannot be observed.",
            )

        try:
            value = getattr(item.value, member.live_member)
        except Exception as exc:
            return self._outcome(item, member, "read_failed", type(exc).__name__)

        if isinstance(member, PropertySpec):
            try:
                item.properties[member.name] = _normalize(value)
            except _NormalizationExcluded as exc:
                return self._outcome(item, member, "excluded", str(exc))
        else:
            try:
                item.relationships[member.name] = self._relationship_ids(item, member, value)
                self._relationship_cache.setdefault(item.source_id, {})[member.name] = list(
                    item.relationships[member.name]
                )
            except _NormalizationExcluded as exc:
                return self._outcome(item, member, "excluded", str(exc))

        return CoverageEntry(item.source_id, item.type_name, member.name, "supported")

    def _relationship_ids(
        self,
        parent: _WorkItem,
        spec: RelationshipSpec,
        value: object,
    ) -> list[str]:
        if value is None:
            values: list[object] = []
        elif spec.cardinality == "single":
            values = [value]
        else:
            if not isinstance(value, (list, tuple)):
                raise _NormalizationExcluded("Relationship collection has an unsupported type.")
            if len(value) > _MAX_COLLECTION:
                raise _NormalizationExcluded("Relationship collection exceeds 1000 entries.")
            values = list(value)

        result: list[str] = []
        for index, child in enumerate(values):
            identity = id(child)
            source_id = self._identity.get(identity)
            if source_id is None:
                suffix = str(index) if spec.cardinality == "collection" else "0"
                child_path = f"{parent.path}/{spec.name}/{suffix}"
                source_id = f"{spec.target_type}:{uuid4().hex}"
                self._identity[identity] = source_id
                child_type = self._resolve_type(child, spec.target_type)
                self._known[identity] = (child, child_type, source_id, child_path)
                selected = None
                if self._target_poll_classes is not None:
                    selected = self._select_members(
                        child_type,
                        identity,
                        self._target_poll_classes,
                        self._target_dirty,
                    )
                if selected is None or selected:
                    self._work.append(
                        _WorkItem(
                            child,
                            child_type,
                            source_id,
                            child_path,
                            selected_members=selected,
                        )
                    )
            elif self._replacement_active and identity not in self._replacement_scheduled:
                child, child_type, known_source_id, child_path = self._known[identity]
                self._replacement_scheduled.add(identity)
                self._work.append(_WorkItem(child, child_type, known_source_id, child_path))
            if self._replacement_active:
                self._replacement_scheduled.add(identity)
            result.append(source_id)
        return result

    def _resolve_type(self, value: object, fallback: str) -> str:
        class_name = type(value).__name__
        if class_name in self._manifest:
            return class_name
        fake_name = class_name.removeprefix("Fake")
        if fake_name in self._manifest:
            return fake_name
        return fallback

    def _outcome(
        self,
        item: _WorkItem,
        member: _MemberSpec,
        status: Literal["unavailable", "read_failed", "excluded"],
        reason: str,
    ) -> CoverageEntry:
        item.outcomes.append(MemberOutcome(member=member.name, status=status, reason=reason))
        return CoverageEntry(item.source_id, item.type_name, member.name, status, reason)

    @staticmethod
    def _finish(item: _WorkItem) -> ObjectObservation:
        return ObjectObservation(
            source_id=item.source_id,
            type=item.type_name,
            path=item.path,
            properties=item.properties,
            relationships=item.relationships,
            outcomes=item.outcomes,
            captured_at=datetime.now(timezone.utc),
            update_mode=("replace" if item.selected_members is None else "patch"),
            attempted_members=[
                member.name
                for member in (item.selected_members if item.selected_members is not None else ())
            ],
        )

    def _reconcile_reachability(self) -> tuple[str, ...]:
        root_source = self._identity.get(self._root_identity or -1)
        if root_source is None:
            return ()
        reachable = {root_source}
        pending = [root_source]
        while pending:
            source_id = pending.pop()
            for targets in self._relationship_cache.get(source_id, {}).values():
                for target in targets:
                    if target not in reachable:
                        reachable.add(target)
                        pending.append(target)
        removed: list[str] = []
        for identity, (_, _, source_id, _) in tuple(self._known.items()):
            if source_id not in reachable:
                removed.append(source_id)
                del self._known[identity]
                self._identity.pop(identity, None)
                self._relationship_cache.pop(source_id, None)
        return tuple(sorted(removed))


def _normalize(value: object, depth: int = 0) -> JsonValue:
    if depth > _MAX_DEPTH:
        raise _NormalizationExcluded("Value exceeds the maximum depth of 8.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _NormalizationExcluded("Non-finite floating-point values are excluded.")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"kind": "binary", "size": len(value)}
    if isinstance(value, Enum):
        return _normalize(value.value, depth + 1)
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_COLLECTION:
            raise _NormalizationExcluded("Collection exceeds 1000 entries.")
        return [_normalize(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAX_COLLECTION:
            raise _NormalizationExcluded("Record exceeds 1000 entries.")
        if not all(isinstance(key, str) for key in value):
            raise _NormalizationExcluded("Record keys must be strings.")
        record = cast(dict[str, object], value)
        return {key: _normalize(item, depth + 1) for key, item in record.items()}
    raise _NormalizationExcluded(f"Unsupported value type: {type(value).__name__}.")
