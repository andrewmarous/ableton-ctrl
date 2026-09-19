"""Bounded main-thread observation runtime and normalized socket transport."""

from __future__ import annotations

import json
import math
import queue
import socket
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, cast
from uuid import uuid4

from ableton_ctrl.adapter.discovery import DiscoveryBudget, DiscoveryEngine, ListenerCandidate
from ableton_ctrl.adapter.manifest import TypeSpec

_FRAME_LIMIT = 1_048_576
_TRANSACTION_PART_LIMIT = 128
_TRANSACTION_BYTE_LIMIT = 64 * _FRAME_LIMIT
_TRANSACTION_OBSERVATION_LIMIT = 10_000
_TRANSACTION_REMOVAL_LIMIT = 10_000
_INCREMENTAL_PUBLICATION_SIZE = 200


class _TerminalPublicationError(ValueError):
    def __init__(self, message: str, action: str) -> None:
        self.action = action
        super().__init__(message)


class EvidenceRecorder(Protocol):
    def record_coverage(self, entries: tuple[Any, ...]) -> None: ...
    def record_tick(self, duration_ms: float, discovery_complete: bool) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class WorkBudget:
    max_members: int = 100
    max_milliseconds: float = 4.0


class Transport(Protocol):
    connected: bool
    writable: bool

    def connect(self, record: dict[str, object]) -> bool: ...
    def send(self, record: dict[str, object]) -> bool: ...
    def receive(self, limit: int = 100) -> list[dict[str, object]]: ...
    def close(self) -> None: ...


class AdapterRuntime:
    """Schedule every interaction with Live from ``tick``."""

    _CADENCES = {"fast": 0.1, "normal": 1.0, "structural": 10.0}
    _BACKOFF = (0.25, 0.5, 1.0, 2.0, 4.0, 5.0)

    def __init__(
        self,
        root: object,
        manifest: dict[str, TypeSpec],
        transport: Transport,
        *,
        session_id: str | None = None,
        discovery: DiscoveryEngine | None = None,
        live_version: str = "12.4.2",
        edition: str = "unknown",
        edition_source: str = "unavailable",
        compatibility: str = "unverified",
        max_pending: int = 10_000,
        max_members: int = 100,
        max_milliseconds: float = 4.0,
        clock: Any = time.monotonic,
        evidence: EvidenceRecorder | None = None,
        timing_clock: Any = time.perf_counter,
    ) -> None:
        self._root = root
        self._transport = transport
        self._discovery = discovery or DiscoveryEngine(manifest)
        self.session_id = session_id or str(uuid4())
        self._live_version = live_version
        self._edition = edition
        self._edition_source = edition_source
        self._compatibility = compatibility
        self._max_pending = max_pending
        self._max_members = max_members
        self._max_milliseconds = max_milliseconds
        self._clock = clock
        self._timing_clock = timing_clock
        self._evidence = evidence
        self._pending: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._dirty: set[tuple[int, str]] = set()
        self._listener_requests: deque[tuple[str, object, str, object]] = deque()
        self._listener_request_keys: set[tuple[str, str]] = set()
        self._listener_removals: deque[tuple[str, str]] = deque()
        self._listeners: dict[tuple[str, str], tuple[object, object]] = {}
        self._disconnect_requested = False
        self._disconnected = False
        self._next_due = {name: 0.0 for name in self._CADENCES}
        self.poll_counts = {name: 0 for name in self._CADENCES}
        self._next_connect = 0.0
        self._attempt = 0
        self._connected_once = False
        self._partial_result = False
        self._last_complete = False
        self._due_classes: set[str] = set()
        self._discovery_pending = False
        self._result_observations: deque[Any] = deque()
        self._pending_removals: set[str] = set()
        self._evidence_close_requested = False
        self._force_full_discovery = False
        self._resync_generation = 0
        self._resync_inflight: int | None = None
        self._pending_replace_graph = False
        self._pending_resync_generation: int | None = None
        self._read_requests: deque[dict[str, object]] = deque()
        self._replacement_publication_started = False
        self._terminal_capacity_error = False
        self._terminal_status_pending = False
        self._was_transport_connected = False
        self._active_connection_seen = False

    @property
    def dirty_count(self) -> int:
        return len(self._dirty)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def runtime_outcome(self) -> str | None:
        return "partial_result" if self._partial_result else None

    @property
    def runtime_action(self) -> str | None:
        if self._terminal_capacity_error:
            return "reduce_observation_size_or_capacity"
        return None

    def register_listener(
        self, live_object: object, member: str, *, source_id: str | None = None
    ) -> None:
        """Queue registration; no Live API is touched before the next tick."""
        listener_source = source_id or f"object:{id(live_object)}"
        listener_key = (listener_source, member)
        if listener_key in self._listeners or listener_key in self._listener_request_keys:
            return
        dirty_key = (id(live_object), member)

        def callback() -> None:
            self._dirty.add(dirty_key)

        self._listener_requests.append((listener_source, live_object, member, callback))
        self._listener_request_keys.add(listener_key)

    def tick(self, now: float) -> None:
        started = self._timing_clock()
        try:
            self._tick(now)
        finally:
            if self._evidence is not None:
                duration_ms = max(0.0, (self._timing_clock() - started) * 1_000)
                self._evidence.record_tick(duration_ms, self._last_complete)
                if self._disconnected and not self._evidence_close_requested:
                    self._evidence.close()
                    self._evidence_close_requested = True

    def _tick(self, now: float) -> None:
        deadline = self._clock() + self._max_milliseconds / 1_000
        remaining = self._max_members
        remaining -= self._apply_listener_work(remaining, deadline)
        if self._disconnected:
            return
        if remaining <= 0 or self._clock() >= deadline:
            return
        self._connect_if_due(now)
        remaining -= 1
        if not self._transport.connected:
            if self._was_transport_connected:
                self._enter_idle()
            self._was_transport_connected = False
            return
        if not self._was_transport_connected:
            if self._active_connection_seen:
                self._prepare_fresh_reconnect()
            self._active_connection_seen = True
            self._was_transport_connected = True
        if remaining <= 0 or self._clock() >= deadline:
            return
        inbound = self._transport.receive(remaining)
        for message in inbound:
            self.handle_inbound(message)
        remaining -= len(inbound)
        while self._read_requests and remaining > 0 and self._clock() < deadline:
            self._serve_read_request(self._read_requests.popleft(), deadline)
            remaining -= 1
        if self._terminal_capacity_error:
            self._due_classes.discard("structural")
            if self._terminal_status_pending:
                self._publish_terminal_status()
            return

        due_classes: set[str] = set()
        for name, cadence in self._CADENCES.items():
            if now >= self._next_due[name]:
                self.poll_counts[name] += 1
                self._next_due[name] = now + cadence
                due_classes.add(name)
        self._due_classes.update(due_classes)
        dirty = frozenset(tuple(self._dirty)[:remaining])

        if (
            (self._due_classes or dirty or self._discovery_pending)
            and remaining > 0
            and self._clock() < deadline
        ):
            accepted_dirty: frozenset[tuple[int, str]] = frozenset()
            accepted_classes: frozenset[str] = frozenset()
            if self._discovery_pending:
                pass
            elif dirty:
                accepted_dirty = dirty
            else:
                accepted_classes = frozenset(self._due_classes)
            discovery_budget = DiscoveryBudget(
                max_members=remaining,
                max_milliseconds=max(0.0, (deadline - self._clock()) * 1_000),
            )
            if self._force_full_discovery:
                result = self._discovery.observe_replacement(self._root, discovery_budget)
            else:
                result = self._discovery.observe_targeted(
                    self._root, discovery_budget, accepted_classes, accepted_dirty
                )
            self._dirty.difference_update(accepted_dirty)
            self._due_classes.difference_update(accepted_classes)
            self._discovery_pending = not result.complete
            self._result_observations.extend(result.observations)
            self._pending_removals.update(result.removed_source_ids)
            for source_id in result.removed_source_ids:
                self._pending.pop(source_id, None)
            if result.removed_source_ids:
                removed = set(result.removed_source_ids)
                self._result_observations = deque(
                    item for item in self._result_observations if item.source_id not in removed
                )
            self._last_complete = result.complete
            if self._force_full_discovery and not self._replacement_publication_started:
                self._pending_replace_graph = True
                self._pending_resync_generation = self._resync_generation
                self._replacement_publication_started = True
            for candidate in result.listener_candidates:
                self._queue_discovered_listener(candidate)
            if result.removed_source_ids:
                removed_sources = set(result.removed_source_ids)
                for key in tuple(self._listeners):
                    if key[0] in removed_sources:
                        self._listener_removals.append(key)
            if self._force_full_discovery and result.complete:
                self._force_full_discovery = False
            if self._evidence is not None:
                self._evidence.record_coverage(result.coverage)
        while self._result_observations and self._clock() < deadline:
            observation = self._result_observations.popleft()
            if hasattr(observation, "model_dump"):
                record = observation.model_dump(mode="json")
                self._pending[observation.source_id] = record
                self._pending.move_to_end(observation.source_id)
        while len(self._pending) > self._max_pending and self._clock() < deadline:
            self._pending.popitem(last=False)
            self._partial_result = True
        if self._clock() < deadline and (
            not self._discovery_pending or len(self._pending) >= _INCREMENTAL_PUBLICATION_SIZE
        ):
            self._flush()

    def disconnect(self) -> None:
        """Request cleanup on the next main-thread tick."""
        self._disconnect_requested = True

    def _enter_idle(self) -> None:
        """Discard graph work that cannot be current after a disconnected interval."""
        self._pending.clear()
        self._pending_removals.clear()
        self._result_observations.clear()
        self._dirty.clear()
        self._due_classes.clear()
        self._discovery_pending = False
        self._pending_replace_graph = False
        self._pending_resync_generation = None
        self._replacement_publication_started = False

    def _prepare_fresh_reconnect(self) -> None:
        self._enter_idle()
        self._force_full_discovery = True
        self._replacement_publication_started = False
        self._resync_generation += 1
        self._due_classes.add("structural")

    def handle_inbound(self, message: dict[str, object]) -> bool:
        kind = message.get("type")
        if kind == "read_request":
            if len(self._read_requests) >= 32:
                return False
            message = dict(message)
            message["_received_at"] = self._clock()
            self._read_requests.append(message)
            return True
        if kind == "handshake_ack":
            return message.get("ok") is True
        if kind == "transport_error":
            if isinstance(message.get("error"), str):
                self._partial_result = True
                if message.get("action") == "capacity_exceeded_manual_action":
                    self._terminal_capacity_error = True
                    self._terminal_status_pending = True
                    return True
                self._force_full_discovery = True
                self._replacement_publication_started = False
                self._resync_generation += 1
                self._due_classes.add("structural")
                return True
            return False
        if kind == "publication_ack":
            acknowledged_resync = message.get("resync_generation")
            if (
                isinstance(acknowledged_resync, int)
                and acknowledged_resync == self._resync_inflight
                and acknowledged_resync == self._resync_generation
            ):
                self._partial_result = False
                self._resync_inflight = None
                self._due_classes.add("structural")
            elif message.get("complete") is True:
                self._partial_result = False
            return isinstance(message.get("bridge_revision"), int)
        return False

    def _serve_read_request(self, request: dict[str, object], deadline: float) -> None:
        request_id = request.get("request_id")
        response: dict[str, object] = {
            "kind": "read_response",
            "request_id": request_id,
            "session_id": self.session_id,
            "ok": False,
        }
        if not isinstance(request_id, str) or request.get("session_id") != self.session_id:
            response["error"] = "session_changed"
        elif self._clock() >= deadline or (
            isinstance(request.get("_received_at"), (int, float))
            and self._clock() >= cast(float, request["_received_at"]) + cast(float, request.get("deadline_ms", 2000)) / 1000
        ):
            response["error"] = "deadline_exceeded"
        else:
            source_id = request.get("source_id")
            target = self._discovery.resolve_source(source_id) if isinstance(source_id, str) else None
            if target is None:
                response["error"] = "stale_cursor"
            else:
                try:
                    method = getattr(target, "get_notes_extended")
                    if not callable(method):
                        raise AttributeError("get_notes_extended")
                    notes = method(
                        cast(int, request["from_pitch"]),
                        cast(int, request["pitch_span"]),
                        cast(float, request["from_beat"]),
                        cast(float, request["beat_span"]),
                    )
                    if not isinstance(notes, (list, tuple)):
                        raise TypeError("get_notes_extended did not return a note list")
                    limit = cast(int, request["note_limit"])
                    normalized = [
                        self._normalize_note(note)
                        for note in notes[: limit + 1]
                    ]
                    response["ok"] = True
                    response["notes"] = normalized[:limit]
                    response["truncated"] = len(normalized) > limit
                except Exception as exc:
                    response["error"] = type(exc).__name__
        self._transport.send(response)

    @staticmethod
    def _normalize_note(note: object) -> dict[str, object]:
        if not isinstance(note, dict):
            raise TypeError("note is not a dictionary")
        required = (
            "note_id", "pitch", "start_time", "duration", "velocity", "mute",
            "probability", "velocity_deviation", "release_velocity",
        )
        if any(key not in note for key in required):
            raise ValueError("note is missing required metadata")
        note_id = note["note_id"]
        pitch = note["pitch"]
        mute = note["mute"]
        if not isinstance(note_id, int) or isinstance(note_id, bool):
            raise TypeError("note_id must be an integer")
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not 0 <= pitch <= 127:
            raise ValueError("pitch is outside MIDI range")
        if not isinstance(mute, bool):
            raise TypeError("mute must be boolean")
        numeric = ("start_time", "duration", "velocity", "probability", "velocity_deviation", "release_velocity")
        values: dict[str, object] = {"note_id": note_id, "pitch": pitch, "mute": mute}
        for key in numeric:
            value = note[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise TypeError(f"{key} must be numeric")
            values[key] = float(value)
        return values

    def _apply_listener_work(self, limit: int, deadline: float) -> int:
        processed = 0
        while self._listener_removals and processed < limit and self._clock() < deadline:
            key = self._listener_removals.popleft()
            registered = self._listeners.pop(key, None)
            if registered is not None:
                live_object, callback = registered
                method = getattr(live_object, f"remove_{key[1]}_listener")
                method(callback)
                processed += 1
        while self._listener_requests and processed < limit and self._clock() < deadline:
            source_id, live_object, member, callback = self._listener_requests.popleft()
            key = (source_id, member)
            self._listener_request_keys.discard(key)
            if key in self._listeners:
                continue
            method = getattr(live_object, f"add_{member}_listener")
            method(callback)
            self._listeners[key] = (live_object, callback)
            processed += 1
        if self._disconnect_requested and not self._disconnected:
            self._listener_requests.clear()
            self._listener_request_keys.clear()
            while self._listeners and processed < limit and self._clock() < deadline:
                (_source_id, member), (live_object, callback) = self._listeners.popitem()
                method = getattr(live_object, f"remove_{member}_listener")
                method(callback)
                processed += 1
            if not self._listeners:
                self._transport.close()
                self._disconnected = True
        return processed

    def _queue_discovered_listener(self, candidate: ListenerCandidate) -> None:
        self.register_listener(
            candidate.value,
            candidate.member,
            source_id=candidate.source_id,
        )

    def _connect_if_due(self, now: float) -> None:
        if self._transport.connected or now < self._next_connect:
            return
        hello: dict[str, object] = {
            "protocol_version": 1,
            "role": "adapter",
            "kind": "hello",
            "session_id": self.session_id,
            "live_version": self._live_version,
            "edition": self._edition,
            "edition_source": self._edition_source,
            "compatibility": self._compatibility,
            "resume": self._connected_once,
            "now": now,
        }
        if self._transport.connect(hello):
            self._connected_once = True
            self._attempt = 0
            return
        delay = self._BACKOFF[min(self._attempt, len(self._BACKOFF) - 1)]
        self._attempt += 1
        self._next_connect = now + delay

    def _publish_terminal_status(self) -> None:
        if not self._transport.connected or not self._transport.writable:
            return
        record: dict[str, object] = {
            "kind": "update",
            "protocol_version": 1,
            "session_id": self.session_id,
            "live_version": self._live_version,
            "edition": self._edition,
            "edition_source": self._edition_source,
            "compatibility": self._compatibility,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "observations": [],
            "removed_source_ids": [],
            "discovery_complete": False,
            "runtime_outcome": "partial_result",
            "runtime_action": "reduce_observation_size_or_capacity",
        }
        if self._transport.send(record):
            self._terminal_status_pending = False

    def _flush(self) -> None:
        if (
            (not self._pending and not self._pending_removals)
            or not self._transport.connected
            or not self._transport.writable
        ):
            return
        complete = (
            self._last_complete
            and not self._dirty
            and not self._due_classes
            and not self._discovery_pending
            and not self._result_observations
        )
        batch: dict[str, object] = {
            "kind": "update",
            "protocol_version": 1,
            "session_id": self.session_id,
            "live_version": self._live_version,
            "edition": self._edition,
            "edition_source": self._edition_source,
            "compatibility": self._compatibility,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "observations": list(self._pending.values()),
            "removed_source_ids": sorted(self._pending_removals),
            "discovery_complete": complete and not self._partial_result,
            "replace_graph": self._pending_replace_graph,
            "resync_generation": self._pending_resync_generation,
        }
        if self._transport.send(batch):
            if self._pending_resync_generation is not None:
                self._resync_inflight = self._pending_resync_generation
            self._pending.clear()
            self._pending_removals.clear()
            self._pending_replace_graph = False
            self._pending_resync_generation = None
        elif getattr(self._transport, "runtime_outcome", None) == "partial_result":
            self._partial_result = True


class SocketTransport:
    """Nonblocking façade over a worker that sees normalized JSON records only."""

    def __init__(self, host: str, port: int, secret: str, max_records: int = 10_000) -> None:
        self._host, self._port, self._secret = host, port, secret
        self._max_records = max_records
        self._outbound: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closing = False
        self._inbound: queue.SimpleQueue[dict[str, object]] = queue.SimpleQueue()
        self.connected = False
        self.writable = True
        self._thread: threading.Thread | None = None
        self._partial_result = False

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._outbound)

    @property
    def pending_records(self) -> list[dict[str, object]]:
        with self._lock:
            return list(self._outbound.values())

    @property
    def runtime_outcome(self) -> str | None:
        return "partial_result" if self._partial_result else None

    def connect(self, record: dict[str, object]) -> bool:
        auth = {
            "protocol_version": 1,
            "role": "adapter",
            "secret": self._secret,
            "message": {
                "kind": "hello",
                "session_id": record["session_id"],
                "live_version": record["live_version"],
                "edition": record.get("edition", ""),
                "resume": bool(record.get("resume", False)),
            },
        }
        accepted = self.send(auth)
        if not accepted:
            return False
        with self._lock:
            self._outbound.move_to_end("handshake", last=False)
        if self._thread is None or not self._thread.is_alive():
            self.connected = True
            self._start_worker()
        return True

    def send(self, record: dict[str, object]) -> bool:
        # Runtime records are normalized before this boundary. Keep JSON encoding
        # and byte-bounded splitting entirely on the socket worker.
        key = self._record_key(record)
        with self._lock:
            if key in self._outbound:
                self._outbound[key] = self._merge_records(self._outbound[key], record)
                self._outbound.move_to_end(key)
            elif len(self._outbound) >= self._max_records:
                self._partial_result = True
                self.writable = False
                return False
            else:
                self._outbound[key] = record
            self.writable = len(self._outbound) < self._max_records
        self._wake.set()
        return True

    def receive(self, limit: int = 100) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        while len(records) < limit:
            try:
                records.append(self._inbound.get_nowait())
            except queue.Empty:
                return records
        return records

    def close(self) -> None:
        self._closing = True
        self._wake.set()
        self.connected = False

    def _start_worker(self) -> None:
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @staticmethod
    def _record_key(record: dict[str, object]) -> str:
        message = record.get("message")
        if isinstance(message, dict) and message.get("kind") == "hello":
            return "handshake"
        return f"record:{id(record)}"

    @staticmethod
    def _merge_records(
        previous: dict[str, object],
        current: dict[str, object],
    ) -> dict[str, object]:
        previous_items = previous.get("observations")
        current_items = current.get("observations")
        if not (
            isinstance(previous_items, list)
            and previous_items
            and isinstance(previous_items[0], dict)
            and isinstance(current_items, list)
            and current_items
            and isinstance(current_items[0], dict)
        ):
            return current
        old = previous_items[0]
        new = current_items[0]
        for field in ("properties", "relationships"):
            old_values = old.get(field)
            new_values = new.get(field)
            if isinstance(old_values, dict) and isinstance(new_values, dict):
                new[field] = {**old_values, **new_values}
        return current

    def _next_record(self) -> tuple[str, dict[str, object]] | None:
        with self._lock:
            if not self._outbound:
                return None
            return next(iter(self._outbound.items()))

    def _ack_record(self, key: str) -> None:
        with self._lock:
            self._outbound.pop(key, None)
            self.writable = len(self._outbound) < self._max_records

    def _worker(self) -> None:
        active_key: str | None = None
        try:
            with socket.create_connection((self._host, self._port), timeout=1.0) as stream:
                stream.settimeout(0.1)
                self.connected = True
                reader = stream.makefile("rb")
                while not self._closing:
                    queued = self._next_record()
                    if queued is None:
                        self._wake.wait(0.1)
                        self._wake.clear()
                        continue
                    key, record = queued
                    active_key = key
                    wire_records = self._wire_records(record)
                    final_response: dict[str, Any] | None = None
                    for wire_record in wire_records:
                        stream.sendall(
                            json.dumps(wire_record, separators=(",", ":")).encode() + b"\n"
                        )
                        try:
                            line = reader.readline()
                        except TimeoutError as exc:
                            raise OSError("ack timeout") from exc
                        if not line:
                            raise OSError("connection closed before acknowledgement")
                        decoded: Any = json.loads(line)
                        while isinstance(decoded, dict) and decoded.get("kind") == "read_request":
                            self._inbound.put(decoded)
                            try:
                                line = reader.readline()
                            except TimeoutError as exc:
                                raise OSError("ack timeout") from exc
                            if not line:
                                raise OSError("connection closed before acknowledgement")
                            decoded = json.loads(line)
                        if not isinstance(decoded, dict) or decoded.get("ok") is not True:
                            raise _TerminalPublicationError(
                                "publication rejected", "terminal_rejection_resync"
                            )
                        final_response = decoded
                    assert final_response is not None
                    is_update = record.get("kind") == "update"
                    if is_update and not isinstance(final_response.get("bridge_revision"), int):
                        raise OSError("final revision acknowledgement missing")
                    self._ack_record(key)
                    active_key = None
                    if is_update:
                        if record.get("replace_graph") is True:
                            self._partial_result = False
                        self._inbound.put(
                            {
                                "type": "publication_ack",
                                "bridge_revision": final_response["bridge_revision"],
                                "complete": record.get("discovery_complete") is True,
                                "resync_generation": record.get("resync_generation"),
                            }
                        )
                    else:
                        self._inbound.put(final_response)
        except _TerminalPublicationError as exc:
            if active_key is not None:
                self._ack_record(active_key)
            self._partial_result = True
            self._inbound.put(
                {
                    "type": "transport_error",
                    "error": type(exc).__name__,
                    "action": exc.action,
                }
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._inbound.put({"type": "transport_error", "error": type(exc).__name__})
        finally:
            self.connected = False

    @staticmethod
    def _wire_records(record: dict[str, object]) -> list[dict[str, object]]:
        """Split an update on the worker into bridge-bounded transaction frames."""
        if record.get("kind") != "update":
            return [record]
        observations = record.get("observations")
        removals = record.get("removed_source_ids")
        if not isinstance(observations, list) or not isinstance(removals, list):
            return [record]
        if len(observations) > _TRANSACTION_OBSERVATION_LIMIT:
            raise _TerminalPublicationError(
                "transaction observation limit exceeded",
                "capacity_exceeded_manual_action",
            )
        if len(removals) > _TRANSACTION_REMOVAL_LIMIT:
            raise _TerminalPublicationError(
                "transaction removal limit exceeded",
                "capacity_exceeded_manual_action",
            )
        metadata = {
            key: value
            for key, value in record.items()
            if key not in {"kind", "observations", "removed_source_ids"}
        }
        transaction_id = uuid4().hex
        chunks: list[tuple[list[object], list[object]]] = []
        current_observations: list[object] = []
        current_removals: list[object] = []

        def fits(candidate_observations: list[object], candidate_removals: list[object]) -> bool:
            probe = {
                "kind": "update_part",
                "transaction_id": transaction_id,
                "part_index": len(chunks),
                "final": False,
                "batch": metadata
                | {
                    "observations": candidate_observations,
                    "removed_source_ids": candidate_removals,
                },
            }
            return len(json.dumps(probe, separators=(",", ":")).encode()) + 1 <= _FRAME_LIMIT

        for observation in observations:
            if current_observations and not fits(
                [*current_observations, observation], current_removals
            ):
                chunks.append((current_observations, current_removals))
                current_observations, current_removals = [], []
            if not fits([observation], []):
                raise _TerminalPublicationError(
                    "single observation exceeds bridge frame limit",
                    "capacity_exceeded_manual_action",
                )
            current_observations.append(observation)
        for removal in removals:
            if not fits(current_observations, [*current_removals, removal]):
                chunks.append((current_observations, current_removals))
                current_observations, current_removals = [], []
            current_removals.append(removal)
        chunks.append((current_observations, current_removals))
        frames = [
            {
                "kind": "update_part",
                "transaction_id": transaction_id,
                "part_index": index,
                "final": index == len(chunks) - 1,
                "batch": metadata
                | {"observations": chunk_observations, "removed_source_ids": chunk_removals},
            }
            for index, (chunk_observations, chunk_removals) in enumerate(chunks)
        ]
        if len(frames) > _TRANSACTION_PART_LIMIT:
            raise _TerminalPublicationError(
                "transaction part limit exceeded", "capacity_exceeded_manual_action"
            )
        total_bytes = sum(
            len(json.dumps(frame, separators=(",", ":")).encode()) + 1 for frame in frames
        )
        if total_bytes > _TRANSACTION_BYTE_LIMIT:
            raise _TerminalPublicationError(
                "transaction byte limit exceeded", "capacity_exceeded_manual_action"
            )
        return frames
