"""Thread-safe, revisioned in-memory graph of observed Live objects."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ableton_ctrl.contracts import JsonValue, MemberOutcome, ObjectObservation, UpdateBatch


class StoreError(Exception):
    """A typed failure produced by a graph-store operation."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message or code}")


class StoreModel(BaseModel):
    """JSON-safe immutable value returned by the graph store."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BindingMetadata(StoreModel):
    protocol_version: Literal[1] = 1
    live_version: str
    session_id: str
    bridge_revision: int = Field(ge=0)
    captured_at: datetime
    cache_age_seconds: float = Field(ge=0)
    completeness: Literal["complete", "partial"]


class ObjectReference(StoreModel):
    object_id: str
    type: str
    path: str | None


class RelationshipPage(StoreModel):
    items: list[ObjectReference | ObjectView]
    total: int
    continuation: str | None


class ObjectView(StoreModel):
    object_id: str
    type: str
    path: str | None
    properties: dict[str, JsonValue]
    relationships: dict[str, RelationshipPage]
    outcomes: list[MemberOutcome]
    captured_at: datetime


class StatusResult(StoreModel):
    protocol_version: Literal[1] = 1
    state: Literal["live_offline", "live", "stale_state"]
    live_connected: bool
    live_version: str | None
    session_id: str | None
    bridge_revision: int
    captured_at: datetime | None
    cache_age_seconds: float | None
    completeness: Literal["complete", "partial", "unavailable"]
    runtime_outcome: Literal["partial_result"] | None = None
    runtime_action: Literal["reduce_observation_size_or_capacity"] | None = None


class SnapshotResult(BindingMetadata):
    root: ObjectView


class ObjectResult(BindingMetadata):
    object_id: str
    type: str
    path: str | None
    properties: dict[str, JsonValue]
    relationships: dict[str, RelationshipPage]
    outcomes: list[MemberOutcome]
    object_captured_at: datetime


class ChildrenResult(BindingMetadata):
    items: list[ObjectReference]
    total: int
    offset: int
    limit: int
    continuation: str | None

    @property
    def revision(self) -> int:
        return self.bridge_revision


class SearchResult(BindingMetadata):
    items: list[ObjectReference]
    total: int
    offset: int
    limit: int
    continuation: str | None

    @property
    def revision(self) -> int:
        return self.bridge_revision


class SchemaMemberDefinition(StoreModel):
    """Optional Task 2 schema knowledge supplied independently of runtime observations."""

    kind: Literal["property", "relationship"]
    manifest_metadata: dict[str, JsonValue] | None = None


class MemberSchema(StoreModel):
    name: str
    kind: Literal["property", "relationship"]
    runtime_available: bool
    observed_count: int
    unavailable_count: int
    read_failed_count: int
    excluded_count: int
    manifest_metadata: dict[str, JsonValue] | None = None


class TypeSchema(StoreModel):
    type: str
    normalized_type: str
    object_count: int
    members: list[MemberSchema]


class SchemaResult(BindingMetadata):
    types: list[TypeSchema]

    @property
    def revision(self) -> int:
        return self.bridge_revision


class ObjectChange(StoreModel):
    object_id: str
    source_id: str
    kind: Literal[
        "added",
        "properties_changed",
        "relationships_changed",
        "outcomes_changed",
        "removed",
        "failure",
    ]
    members: list[str] = Field(default_factory=list)


class ChangeSet(StoreModel):
    revision: int
    captured_at: datetime
    changes: list[ObjectChange]


class ChangesResult(BindingMetadata):
    changes: list[ChangeSet]
    next_revision: int

    @property
    def revision(self) -> int:
        return self.bridge_revision


@dataclass
class _Node:
    object_id: str
    source_id: str
    type: str
    path: str | None
    properties: dict[str, JsonValue]
    relationships: dict[str, list[str]]
    outcomes: list[MemberOutcome]
    captured_at: datetime


@dataclass(frozen=True)
class _Revision:
    number: int
    graph: dict[str, _Node]
    source_to_id: dict[str, str]
    changes: ChangeSet
    live_version: str
    captured_at: datetime
    discovery_complete: bool


@dataclass
class _MemberStats:
    kind: Literal["property", "relationship"]
    observed: int = 0
    unavailable: int = 0
    read_failed: int = 0
    excluded: int = 0


@dataclass
class _TypeStats:
    display_name: str
    object_count: int = 0
    members: dict[str, _MemberStats] = field(default_factory=dict)


Clock = Callable[[], datetime]


class GraphStore:
    """Store atomic observation batches and serve revision-pinned queries."""

    def __init__(
        self,
        history_limit: int = 100,
        clock: Clock | None = None,
        schema_metadata: Mapping[str, Mapping[str, SchemaMemberDefinition]] | None = None,
    ) -> None:
        if history_limit < 1:
            raise StoreError("invalid_bounds", "history_limit must be at least 1")
        self._lock = RLock()
        self._history_limit = history_limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_id: str | None = None
        self._live_version: str | None = None
        self._captured_at: datetime | None = None
        self._live_connected = False
        self._revision = 0
        self._graph: dict[str, _Node] = {}
        self._source_to_id: dict[str, str] = {}
        self._history: deque[_Revision] = deque(maxlen=history_limit)
        self._invalid_sessions: set[str] = set()
        self._invalid_object_ids: set[str] = set()
        self._runtime_outcome: Literal["partial_result"] | None = None
        self._runtime_action: Literal["reduce_observation_size_or_capacity"] | None = None
        self._schema_metadata = {
            object_type.casefold(): {
                member.casefold(): definition for member, definition in members.items()
            }
            for object_type, members in (schema_metadata or {}).items()
        }

    def apply(self, batch: UpdateBatch) -> int:
        """Atomically validate and publish one adapter update batch."""
        with self._lock:
            changing_session = self._session_id is not None and batch.session_id != self._session_id
            replacing_graph = changing_session or batch.replace_graph
            base_graph = {} if replacing_graph else deepcopy(self._graph)
            base_ids = {} if changing_session else dict(self._source_to_id)
            next_revision = (
                1 if changing_session or self._session_id is None else self._revision + 1
            )

            observed_ids = [observation.source_id for observation in batch.observations]
            if len(observed_ids) != len(set(observed_ids)):
                raise StoreError("invalid_batch", "duplicate observation source_id")

            changes: list[ObjectChange] = []
            if batch.replace_graph and not changing_session:
                observed_sources = {item.source_id for item in batch.observations}
                for source_id, stale_object_id in self._source_to_id.items():
                    if source_id not in observed_sources:
                        changes.append(
                            ObjectChange(
                                object_id=stale_object_id,
                                source_id=source_id,
                                kind="removed",
                            )
                        )
            for source_id in batch.removed_source_ids:
                removed_object_id = base_ids.pop(source_id) if source_id in base_ids else None
                if removed_object_id is not None and removed_object_id in base_graph:
                    del base_graph[removed_object_id]
                    changes.append(
                        ObjectChange(
                            object_id=removed_object_id,
                            source_id=source_id,
                            kind="removed",
                        )
                    )

            for observation in batch.observations:
                object_id = base_ids.get(observation.source_id)
                if object_id is None:
                    object_id = f"{batch.session_id}:{uuid4().hex}"
                    base_ids[observation.source_id] = object_id
                old = base_graph.get(object_id)
                node = self._node_from_observation(object_id, observation, old)
                base_graph[object_id] = node
                changes.extend(self._diff(old, node))

            available_sources = {node.source_id for node in base_graph.values()}
            if batch.replace_graph:
                base_ids = {
                    source_id: object_id
                    for source_id, object_id in base_ids.items()
                    if source_id in available_sources
                }
            for node in base_graph.values():
                for relationship, targets in node.relationships.items():
                    missing = set(targets) - available_sources
                    if missing:
                        missing_text = ", ".join(sorted(missing))
                        raise StoreError(
                            "invalid_relationship",
                            f"{node.source_id}.{relationship} references {missing_text}",
                        )

            change_set = ChangeSet(
                revision=next_revision,
                captured_at=batch.captured_at,
                changes=changes,
            )
            revision_snapshot = _Revision(
                next_revision,
                deepcopy(base_graph),
                dict(base_ids),
                change_set,
                batch.live_version,
                batch.captured_at,
                batch.discovery_complete,
            )

            if changing_session:
                assert self._session_id is not None
                self._invalid_sessions.add(self._session_id)
                self._invalid_object_ids.update(self._source_to_id.values())
                self._history.clear()
            self._session_id = batch.session_id
            self._live_version = batch.live_version
            self._captured_at = batch.captured_at
            if batch.runtime_outcome is not None:
                self._runtime_outcome = batch.runtime_outcome
                self._runtime_action = batch.runtime_action
            elif batch.discovery_complete:
                self._runtime_outcome = None
                self._runtime_action = None
            self._live_connected = True
            self._revision = next_revision
            self._graph = base_graph
            self._source_to_id = base_ids
            self._history.append(revision_snapshot)
            return next_revision

    def mark_offline(self) -> None:
        """Record an adapter disconnect without discarding the cached graph."""
        with self._lock:
            self._live_connected = False

    def status(self, stale_after_seconds: float = 5.0) -> StatusResult:
        if stale_after_seconds <= 0:
            raise StoreError("invalid_bounds", "stale_after_seconds must be positive")
        with self._lock:
            if self._captured_at is None:
                return StatusResult(
                    state="live_offline",
                    live_connected=False,
                    live_version=None,
                    session_id=None,
                    bridge_revision=0,
                    captured_at=None,
                    cache_age_seconds=None,
                    completeness="unavailable",
                    runtime_outcome=None,
                    runtime_action=None,
                )
            age = self._age()
            state: Literal["live_offline", "live", "stale_state"]
            if not self._live_connected:
                state = "live_offline"
            else:
                state = "stale_state" if age > stale_after_seconds else "live"
            return StatusResult(
                state=state,
                live_connected=self._live_connected,
                live_version=self._live_version,
                session_id=self._session_id,
                bridge_revision=self._revision,
                captured_at=self._captured_at,
                cache_age_seconds=age,
                completeness=("complete" if self._history[-1].discovery_complete else "partial"),
                runtime_outcome=self._runtime_outcome,
                runtime_action=self._runtime_action,
            )

    def snapshot(self, depth: int = 1, page_size: int = 20) -> SnapshotResult:
        self._bounds("depth", depth, 0, 8)
        self._bounds("page_size", page_size, 1, 200)
        with self._lock:
            self._require_online()
            revision = self._current_snapshot()
            root = self._find_root(revision.graph)
            partial = [False]
            view = self._expand(
                root,
                revision.graph,
                depth,
                page_size,
                partial,
                revision.number,
            )
            assert self._live_version is not None
            assert self._session_id is not None
            assert self._captured_at is not None
            return SnapshotResult(
                root=view,
                **self._metadata(
                    revision,
                    "partial" if partial[0] else "complete",
                ),
            )

    def get_object(self, object_id: str, revision: int | None = None) -> ObjectResult:
        with self._lock:
            self._check_invalid_object(object_id)
            snapshot = self._revision_snapshot(revision)
            node = snapshot.graph.get(object_id)
            if node is None:
                raise StoreError("not_found", f"unknown object_id {object_id}")
            partial = [False]
            view = self._expand(
                node,
                snapshot.graph,
                0,
                200,
                partial,
                snapshot.number,
            )
            return ObjectResult(
                object_id=view.object_id,
                type=view.type,
                path=view.path,
                properties=view.properties,
                relationships=view.relationships,
                outcomes=view.outcomes,
                object_captured_at=view.captured_at,
                **self._metadata(
                    snapshot,
                    "partial" if partial[0] else "complete",
                ),
            )

    def list_children(
        self,
        object_id: str,
        relationship: str,
        offset: int = 0,
        limit: int = 20,
        revision: int | None = None,
    ) -> ChildrenResult:
        self._bounds("offset", offset, 0, None)
        self._bounds("limit", limit, 1, 200)
        with self._lock:
            self._check_invalid_object(object_id)
            snapshot = self._revision_snapshot(revision)
            node = snapshot.graph.get(object_id)
            if node is None:
                raise StoreError("not_found", f"unknown object_id {object_id}")
            if relationship not in node.relationships:
                raise StoreError("not_found", f"unknown relationship {relationship}")
            target_ids = node.relationships[relationship]
            items = [
                self._reference(snapshot.graph[snapshot.source_to_id[source_id]])
                for source_id in target_ids[offset : offset + limit]
            ]
            total = len(target_ids)
            continuation = (
                self._cursor(snapshot.number, offset + limit) if offset + limit < total else None
            )
            return ChildrenResult(
                items=items,
                total=total,
                offset=offset,
                limit=limit,
                continuation=continuation,
                **self._metadata(
                    snapshot,
                    "partial" if continuation is not None else "complete",
                ),
            )

    def search(
        self,
        name: str | None = None,
        object_type: str | None = None,
        path: str | None = None,
        offset: int = 0,
        limit: int = 20,
        revision: int | None = None,
    ) -> SearchResult:
        self._bounds("offset", offset, 0, None)
        self._bounds("limit", limit, 1, 200)
        if name is not None and len(name) > 256:
            raise StoreError("invalid_bounds", "name must be at most 256 characters")
        with self._lock:
            snapshot = self._revision_snapshot(revision)
            name_filter = name.casefold() if name is not None else None
            type_filter = object_type.casefold() if object_type is not None else None
            path_filter = path.casefold() if path is not None else None
            matches = [
                node
                for node in snapshot.graph.values()
                if self._matches(node, name_filter, type_filter, path_filter)
            ]
            matches.sort(key=lambda item: ((item.path or "").casefold(), item.object_id))
            total = len(matches)
            items = [self._reference(node) for node in matches[offset : offset + limit]]
            continuation = (
                self._cursor(snapshot.number, offset + limit) if offset + limit < total else None
            )
            return SearchResult(
                items=items,
                total=total,
                offset=offset,
                limit=limit,
                continuation=continuation,
                **self._metadata(
                    snapshot,
                    "partial" if continuation is not None else "complete",
                ),
            )

    def get_schema(
        self,
        object_type: str | None = None,
        revision: int | None = None,
    ) -> SchemaResult:
        with self._lock:
            snapshot = self._revision_snapshot(revision)
            aggregates: dict[str, _TypeStats] = {}
            for node in snapshot.graph.values():
                normalized = node.type.casefold()
                if object_type is not None and normalized != object_type.casefold():
                    continue
                type_stats = aggregates.setdefault(normalized, _TypeStats(node.type))
                type_stats.object_count += 1
                for member in node.properties:
                    stats = type_stats.members.setdefault(
                        member.casefold(), _MemberStats("property")
                    )
                    stats.observed += 1
                for member in node.relationships:
                    stats = type_stats.members.setdefault(
                        member.casefold(), _MemberStats("relationship")
                    )
                    stats.observed += 1
                for outcome in node.outcomes:
                    definition = self._schema_metadata.get(normalized, {}).get(
                        outcome.member.casefold()
                    )
                    stats = type_stats.members.setdefault(
                        outcome.member.casefold(),
                        _MemberStats(definition.kind if definition is not None else "property"),
                    )
                    if outcome.status == "unavailable":
                        stats.unavailable += 1
                    elif outcome.status == "read_failed":
                        stats.read_failed += 1
                    else:
                        stats.excluded += 1
            types = [
                TypeSchema(
                    type=stats.display_name,
                    normalized_type=normalized,
                    object_count=stats.object_count,
                    members=[
                        MemberSchema(
                            name=name,
                            kind=member.kind,
                            runtime_available=member.observed > 0,
                            observed_count=member.observed,
                            unavailable_count=member.unavailable,
                            read_failed_count=member.read_failed,
                            excluded_count=member.excluded,
                            manifest_metadata=(
                                self._schema_metadata.get(normalized, {})
                                .get(name, SchemaMemberDefinition(kind=member.kind))
                                .manifest_metadata
                            ),
                        )
                        for name, member in sorted(stats.members.items())
                    ],
                )
                for normalized, stats in sorted(aggregates.items())
            ]
            return SchemaResult(
                types=types,
                **self._metadata(
                    snapshot,
                    "complete" if snapshot.discovery_complete else "partial",
                ),
            )

    def get_changes(
        self,
        session_id: str,
        after_revision: int,
        limit: int = 100,
    ) -> ChangesResult:
        self._bounds("after_revision", after_revision, 0, None)
        self._bounds("limit", limit, 1, 500)
        with self._lock:
            self._require_online()
            if session_id != self._session_id:
                code = "session_changed" if session_id in self._invalid_sessions else "not_found"
                raise StoreError(code, f"session {session_id} is not active")
            oldest = self._history[0].number
            if after_revision < oldest - 1 or after_revision > self._revision:
                raise StoreError("stale_cursor", f"revision {after_revision} is not retained")
            changes = [
                deepcopy(item.changes) for item in self._history if item.number > after_revision
            ][:limit]
            next_revision = changes[-1].revision if changes else after_revision
            has_more = any(item.number > next_revision for item in self._history)
            current = self._current_snapshot()
            return ChangesResult(
                changes=changes,
                next_revision=next_revision,
                **self._metadata(
                    current,
                    "partial" if has_more else "complete",
                ),
            )

    @staticmethod
    def _node_from_observation(
        object_id: str,
        observation: ObjectObservation,
        old: _Node | None = None,
    ) -> _Node:
        if observation.update_mode == "patch" and old is not None:
            properties = deepcopy(old.properties)
            relationships = deepcopy(old.relationships)
            outcomes_by_member = {item.member: deepcopy(item) for item in old.outcomes}
            for member in observation.attempted_members:
                properties.pop(member, None)
                relationships.pop(member, None)
                outcomes_by_member.pop(member, None)
            properties.update(deepcopy(observation.properties))
            relationships.update(deepcopy(observation.relationships))
            outcomes_by_member.update(
                {item.member: deepcopy(item) for item in observation.outcomes}
            )
            outcomes = list(outcomes_by_member.values())
        else:
            properties = deepcopy(observation.properties)
            relationships = deepcopy(observation.relationships)
            outcomes = deepcopy(observation.outcomes)
        return _Node(
            object_id,
            observation.source_id,
            observation.type,
            observation.path,
            properties,
            relationships,
            outcomes,
            observation.captured_at,
        )

    @staticmethod
    def _diff(old: _Node | None, new: _Node) -> list[ObjectChange]:
        if old is None:
            changes = [
                ObjectChange(
                    object_id=new.object_id,
                    source_id=new.source_id,
                    kind="added",
                )
            ]
        else:
            changes = []
            property_members = tuple(
                sorted(
                    key
                    for key in old.properties.keys() | new.properties.keys()
                    if old.properties.get(key) != new.properties.get(key)
                )
            )
            if property_members:
                changes.append(
                    ObjectChange(
                        object_id=new.object_id,
                        source_id=new.source_id,
                        kind="properties_changed",
                        members=list(property_members),
                    )
                )
            relationship_members = tuple(
                sorted(
                    key
                    for key in old.relationships.keys() | new.relationships.keys()
                    if old.relationships.get(key) != new.relationships.get(key)
                )
            )
            if relationship_members:
                changes.append(
                    ObjectChange(
                        object_id=new.object_id,
                        source_id=new.source_id,
                        kind="relationships_changed",
                        members=list(relationship_members),
                    )
                )
            if old.outcomes != new.outcomes:
                changes.append(
                    ObjectChange(
                        object_id=new.object_id,
                        source_id=new.source_id,
                        kind="outcomes_changed",
                        members=sorted(outcome.member for outcome in new.outcomes),
                    )
                )
        for outcome in new.outcomes:
            if outcome.status == "read_failed":
                changes.append(
                    ObjectChange(
                        object_id=new.object_id,
                        source_id=new.source_id,
                        kind="failure",
                        members=[outcome.member],
                    )
                )
        return changes

    def _revision_snapshot(self, revision: int | None) -> _Revision:
        self._require_online()
        requested = self._revision if revision is None else revision
        for item in self._history:
            if item.number == requested:
                return item
        raise StoreError("stale_cursor", f"revision {requested} is not retained")

    def _current_snapshot(self) -> _Revision:
        return self._revision_snapshot(self._revision)

    def _require_online(self) -> None:
        if self._session_id is None or not self._history:
            raise StoreError("live_offline")

    def _check_invalid_object(self, object_id: str) -> None:
        if object_id in self._invalid_object_ids:
            raise StoreError("session_changed", "object belongs to a previous session")

    def _age(self) -> float:
        assert self._captured_at is not None
        return max(0.0, (self._clock() - self._captured_at).total_seconds())

    def _metadata(
        self,
        revision: _Revision,
        completeness: Literal["complete", "partial"],
    ) -> dict[str, Any]:
        assert self._session_id is not None
        return {
            "protocol_version": 1,
            "live_version": revision.live_version,
            "session_id": self._session_id,
            "bridge_revision": revision.number,
            "captured_at": revision.captured_at,
            "cache_age_seconds": max(
                0.0,
                (self._clock() - revision.captured_at).total_seconds(),
            ),
            "completeness": (
                "partial"
                if not revision.discovery_complete or completeness == "partial"
                else "complete"
            ),
        }

    @staticmethod
    def _find_root(graph: dict[str, _Node]) -> _Node:
        if not graph:
            raise StoreError("not_found", "graph has no root")
        referenced = {
            target
            for node in graph.values()
            for targets in node.relationships.values()
            for target in targets
        }
        roots = [node for node in graph.values() if node.source_id not in referenced]
        return min(
            roots or list(graph.values()), key=lambda item: (item.path or "", item.object_id)
        )

    def _expand(
        self,
        node: _Node,
        graph: dict[str, _Node],
        depth: int,
        page_size: int,
        partial: list[bool],
        revision: int,
    ) -> ObjectView:
        relationships: dict[str, RelationshipPage] = {}
        source_index = {item.source_id: item for item in graph.values()}
        for name, target_sources in node.relationships.items():
            visible = target_sources[:page_size]
            if depth == 0:
                items: list[ObjectReference | ObjectView] = [
                    self._reference(source_index[source]) for source in visible
                ]
                continuation = self._cursor(revision, len(visible)) if target_sources else None
                if target_sources:
                    partial[0] = True
            else:
                items = [
                    self._expand(
                        source_index[source],
                        graph,
                        depth - 1,
                        page_size,
                        partial,
                        revision,
                    )
                    for source in visible
                ]
                continuation = (
                    self._cursor(revision, page_size) if len(target_sources) > page_size else None
                )
                if continuation is not None:
                    partial[0] = True
            relationships[name] = RelationshipPage(
                items=items,
                total=len(target_sources),
                continuation=continuation,
            )
        return ObjectView(
            object_id=node.object_id,
            type=node.type,
            path=node.path,
            properties=deepcopy(node.properties),
            relationships=relationships,
            outcomes=deepcopy(node.outcomes),
            captured_at=node.captured_at,
        )

    @staticmethod
    def _reference(node: _Node) -> ObjectReference:
        return ObjectReference(
            object_id=node.object_id,
            type=node.type,
            path=node.path,
        )

    @staticmethod
    def _matches(
        node: _Node,
        name: str | None,
        object_type: str | None,
        path: str | None,
    ) -> bool:
        raw_name = node.properties.get("name")
        searchable_name = str(raw_name).casefold() if raw_name is not None else ""
        return (
            (name is None or name in searchable_name)
            and (object_type is None or object_type in node.type.casefold())
            and (path is None or path in (node.path or "").casefold())
        )

    @staticmethod
    def _bounds(name: str, value: int, minimum: int, maximum: int | None) -> None:
        if value < minimum or (maximum is not None and value > maximum):
            suffix = f" and at most {maximum}" if maximum is not None else ""
            raise StoreError(
                "invalid_bounds",
                f"{name} must be at least {minimum}{suffix}",
            )

    @staticmethod
    def _cursor(revision: int, offset: int) -> str:
        return f"{revision}:{offset}"
