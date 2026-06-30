from __future__ import annotations

import ast
import importlib
import json
import sys
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from ableton_ctrl.adapter.discovery import CoverageEntry, DiscoverySlice
from ableton_ctrl.adapter.evidence import CoverageEvidenceRecorder
from ableton_ctrl.adapter.manifest import (
    LIVE_12_4_2_INTRO_MANIFEST,
    PropertySpec,
    TypeSpec,
)
from ableton_ctrl.adapter.runtime import AdapterRuntime, SocketTransport
from ableton_ctrl.bridge.store import GraphStore, StoreError
from ableton_ctrl.contracts import ObjectObservation, UpdateBatch
from fakes.live import FakeSong, FakeTrack


class FakeTransport:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.connect_times: list[float] = []
        self.sent: list[dict[str, object]] = []
        self.connected = False
        self.writable = True

    def connect(self, record: dict[str, object]) -> bool:
        self.connect_times.append(float(record["now"]))
        if len(self.connect_times) <= self.failures:
            return False
        self.connected = True
        self.sent.append(record)
        return True

    def send(self, record: dict[str, object]) -> bool:
        if not self.connected or not self.writable:
            return False
        self.sent.append(record)
        return True

    def receive(self, limit: int = 100) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        self.connected = False


class StoreTransport(FakeTransport):
    def __init__(self, store: GraphStore) -> None:
        super().__init__()
        self.store = store

    def send(self, record: dict[str, object]) -> bool:
        if record.get("kind") == "update":
            payload = {key: value for key, value in record.items() if key != "kind"}
            self.store.apply(UpdateBatch.model_validate(payload))
        return super().send(record)


class FakeEngine:
    def __init__(self, completions: list[bool] | None = None) -> None:
        self.budgets: list[tuple[int, float]] = []
        self.calls = 0
        self.targets: list[tuple[frozenset[str], frozenset[tuple[int, str]]]] = []
        self.completions = completions or []

    def observe_targeted(
        self,
        root: object,
        budget: object,
        poll_classes: frozenset[str],
        dirty: frozenset[tuple[int, str]],
    ) -> DiscoverySlice:
        self.calls += 1
        self.budgets.append((budget.max_members, budget.max_milliseconds))
        self.targets.append((poll_classes, dirty))
        observation = ObjectObservation(
            source_id="Song:root",
            type="Song",
            path="Song",
            properties={"tempo": self.calls},
            relationships={},
            outcomes=[],
            captured_at=datetime.now(timezone.utc),
        )
        complete = self.completions.pop(0) if self.completions else True
        return DiscoverySlice(
            observations=(observation,),
            coverage=(CoverageEntry("Song:root", "Song", "tempo", "supported"),),
            remaining_work=0 if complete else 1,
            complete=complete,
        )

    def observe(self, root: object, budget: object) -> DiscoverySlice:
        return self.observe_targeted(root, budget, frozenset(), frozenset())

    def observe_replacement(self, root: object, budget: object) -> DiscoverySlice:
        return self.observe(root, budget)


class FakeEvidence:
    def __init__(self) -> None:
        self.coverage: list[CoverageEntry] = []
        self.ticks: list[tuple[float, bool]] = []

    def record_coverage(self, entries: tuple[CoverageEntry, ...]) -> None:
        self.coverage.extend(entries)

    def record_tick(self, duration_ms: float, discovery_complete: bool) -> None:
        self.ticks.append((duration_ms, discovery_complete))

    def close(self) -> None:
        return None


class ListenableRoot:
    tempo = 120.0

    def __init__(self) -> None:
        self.callbacks: list[object] = []
        self.removals = 0

    def add_tempo_listener(self, callback: object) -> None:
        self.callbacks.append(callback)

    def remove_tempo_listener(self, callback: object) -> None:
        self.callbacks.remove(callback)
        self.removals += 1


def runtime(
    root: object | None = None, **kwargs: object
) -> tuple[AdapterRuntime, FakeEngine, FakeTransport]:
    engine = FakeEngine()
    transport = FakeTransport()
    instance = AdapterRuntime(
        root=root or ListenableRoot(),
        manifest={},
        transport=transport,
        discovery=engine,
        live_version="12.4.2",
        **kwargs,
    )
    return instance, engine, transport


def test_tick_passes_hard_member_and_time_budget() -> None:
    instance, engine, _ = runtime()
    instance.tick(0.0)
    assert 0 < engine.budgets[0][0] <= 100
    assert 0 < engine.budgets[0][1] <= 4.0


def test_runtime_forwards_discovery_coverage_and_tick_timing() -> None:
    evidence = FakeEvidence()
    instance, _, _ = runtime(evidence=evidence)

    instance.tick(0.0)

    assert evidence.coverage == [CoverageEntry("Song:root", "Song", "tempo", "supported")]
    assert len(evidence.ticks) == 1
    assert evidence.ticks[0][0] >= 0
    assert evidence.ticks[0][1] is True


def test_evidence_recorder_writes_validator_ready_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "Library" / "Logs" / "ableton-ctrl" / "coverage.jsonl"
    recorder = CoverageEvidenceRecorder(
        path,
        LIVE_12_4_2_INTRO_MANIFEST,
        session_id="fixture-session",
        live_version="12.4.2",
        edition="Intro",
    )
    entries = tuple(
        CoverageEntry("fixture", type_name, member.name, "supported")
        for type_name, spec in LIVE_12_4_2_INTRO_MANIFEST.items()
        for member in (*spec.properties, *spec.relationships)
    )
    recorder.record_coverage(entries)
    recorder.record_tick(1.25, True)
    recorder.record_tick(2.5, True)
    recorder.close()
    assert recorder.wait_closed(2.0)

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {
        "discovery_complete": True,
        "edition": "Intro",
        "kind": "run",
        "live_version": "12.4.2",
        "max_tick_duration_ms": 2.5,
        "p95_tick_duration_ms": 2.5,
        "session_id": "fixture-session",
        "tick_count": 2,
    }
    assert len(records) == len(entries) + 1


def test_disconnect_does_not_wait_for_slow_evidence_writer_and_keeps_final_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "coverage.jsonl"
    recorder = CoverageEvidenceRecorder(
        path,
        {},
        session_id="fixture-session",
        live_version="12.4.2",
        edition="Intro",
    )
    writer_started = threading.Event()
    allow_writer = threading.Event()
    original_write = recorder._write_snapshot

    def slow_write() -> None:
        writer_started.set()
        assert allow_writer.wait(2.0)
        original_write()

    monkeypatch.setattr(recorder, "_write_snapshot", slow_write)
    timings = iter((0.0, 0.001, 0.001, 0.004))
    instance, _, _ = runtime(evidence=recorder, timing_clock=lambda: next(timings))
    instance.tick(0.0)
    assert writer_started.wait(1.0)

    instance.disconnect()
    started = time.perf_counter()
    instance.tick(0.1)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    allow_writer.set()
    assert recorder.wait_closed(2.0)
    run = json.loads(path.read_text().splitlines()[0])
    assert run["tick_count"] == 2
    assert run["max_tick_duration_ms"] == pytest.approx(3.0)


def test_poll_cadences_are_fast_normal_and_structural() -> None:
    instance, engine, _ = runtime()
    for now in (0.0, 0.099, 0.1, 0.999, 1.0, 9.999, 10.0):
        instance.tick(now)
    assert instance.poll_counts == {"fast": 4, "normal": 3, "structural": 2}
    assert engine.targets[0][0] == frozenset({"fast", "normal", "structural"})
    assert engine.targets[1][0] == frozenset({"fast"})


def test_listener_callback_only_enqueues_until_tick() -> None:
    root = ListenableRoot()
    instance, engine, _ = runtime(root)
    instance.register_listener(root, "tempo")
    assert root.callbacks == []
    instance.tick(0.0)
    assert len(root.callbacks) == 1
    calls = engine.calls
    root.callbacks[0]()
    assert engine.calls == calls
    assert instance.dirty_count == 1
    instance.tick(0.01)
    assert engine.calls == calls + 1
    assert engine.targets[-1] == (frozenset(), frozenset({(id(root), "tempo")}))


def test_incomplete_slice_preserves_new_targets_and_runs_dirty_first() -> None:
    root = ListenableRoot()
    engine = FakeEngine(completions=[False, True, True, True])
    transport = FakeTransport()
    instance = AdapterRuntime(
        root=root,
        manifest={},
        transport=transport,
        discovery=engine,
    )
    instance.register_listener(root, "tempo")

    instance.tick(0.0)
    root.callbacks[0]()
    instance.tick(0.1)
    instance.tick(0.11)
    instance.tick(0.12)

    assert engine.targets == [
        (frozenset({"fast", "normal", "structural"}), frozenset()),
        (frozenset(), frozenset()),
        (frozenset(), frozenset({(id(root), "tempo")})),
        (frozenset({"fast"}), frozenset()),
    ]


def test_discovery_complete_waits_for_cadence_queued_behind_dirty() -> None:
    root = ListenableRoot()
    instance, _, transport = runtime(root)
    instance.register_listener(root, "tempo")
    instance.tick(0.0)
    root.callbacks[0]()

    instance.tick(0.1)
    updates = [record for record in transport.sent if record.get("kind") == "update"]
    assert updates[-1]["discovery_complete"] is False

    instance.tick(0.11)
    updates = [record for record in transport.sent if record.get("kind") == "update"]
    assert updates[-1]["discovery_complete"] is True


def test_listener_removal_is_main_thread_and_exactly_once() -> None:
    root = ListenableRoot()
    instance, _, _ = runtime(root)
    instance.register_listener(root, "tempo")
    instance.tick(0.0)
    instance.disconnect()
    assert root.removals == 0
    instance.tick(0.1)
    instance.disconnect()
    instance.tick(0.2)
    assert root.removals == 1


def test_connection_backoff_is_bounded_and_tick_does_not_sleep() -> None:
    engine = FakeEngine()
    transport = FakeTransport(failures=6)
    instance = AdapterRuntime(
        root=ListenableRoot(),
        manifest={},
        transport=transport,
        discovery=engine,
    )
    for now in (0, 0.24, 0.25, 0.74, 0.75, 1.74, 1.75, 3.74, 3.75, 7.74, 7.75, 12.74, 12.75):
        instance.tick(float(now))
    assert transport.connect_times == [0.0, 0.25, 0.75, 1.75, 3.75, 7.75, 12.75]


def test_unsent_observations_coalesce_by_source() -> None:
    instance, _, transport = runtime(max_pending=2)
    transport.writable = False
    instance.tick(0.0)
    instance.tick(0.1)
    instance.tick(0.2)
    assert instance.pending_count == 1
    transport.writable = True
    instance.tick(0.3)
    batch = transport.sent[-1]
    assert batch["observations"][0]["properties"]["tempo"] == 3


def test_discovery_runtime_store_is_atomic_and_prunes_removed_tracks() -> None:
    track = FakeTrack()
    song = FakeSong([track])
    store = GraphStore()
    transport = StoreTransport(store)
    instance = AdapterRuntime(
        song,
        LIVE_12_4_2_INTRO_MANIFEST,
        transport,
        session_id="integrated",
    )
    for _ in range(10):
        instance.tick(0.0)
        if store.status().bridge_revision:
            break
    snapshot = store.snapshot(depth=1, page_size=20)
    assert len(snapshot.root.relationships["tracks"].items) == 1
    track_id = snapshot.root.relationships["tracks"].items[0].object_id

    song.tracks = []
    for _ in range(10):
        instance.tick(10.0)
        if store.snapshot(depth=1, page_size=20).root.relationships["tracks"].items == []:
            break
    assert store.snapshot(depth=1, page_size=20).root.relationships["tracks"].items == []
    with pytest.raises(StoreError, match="not_found"):
        store.get_object(track_id)


def test_multi_object_resync_replacement_leaves_exact_graph_after_disconnect() -> None:
    track = FakeTrack()
    song = FakeSong([track])
    store = GraphStore()
    transport = StoreTransport(store)
    instance = AdapterRuntime(
        song,
        LIVE_12_4_2_INTRO_MANIFEST,
        transport,
        session_id="resync",
    )
    for _ in range(10):
        instance.tick(0.0)
        if store.status().bridge_revision:
            break
    old_track_id = store.search(object_type="Track", limit=10).items[0].object_id
    old_root_id = store.snapshot().root.object_id
    song.tracks = []
    assert instance.handle_inbound({"type": "transport_error", "error": "disconnect"})
    for _ in range(10):
        instance.tick(0.1)
        updates = [item for item in transport.sent if item.get("kind") == "update"]
        if updates and updates[-1].get("replace_graph") is True:
            break
    assert store.search(object_type="Track", limit=10).items == []
    assert store.snapshot().root.relationships["tracks"].items == []
    assert store.snapshot().root.object_id == old_root_id
    with pytest.raises(StoreError, match="not_found"):
        store.get_object(old_track_id)


def test_fast_normal_and_structural_patches_preserve_unpolled_members_in_store() -> None:
    class Song:
        fast = 1
        normal = 2
        structural = 3

    manifest = {
        "Song": TypeSpec(
            "Song",
            properties=(
                PropertySpec("fast", "fast", None, "fast", "fast"),
                PropertySpec("normal", "normal", None, "normal", "slow"),
                PropertySpec("structural", "structural", None, "structural", "static"),
            ),
        )
    }
    song = Song()
    store = GraphStore()
    instance = AdapterRuntime(song, manifest, StoreTransport(store), session_id="cadence")
    instance.tick(0.0)
    song.fast = 10
    instance.tick(0.1)
    assert store.snapshot().root.properties == {"fast": 10, "normal": 2, "structural": 3}
    song.normal = 20
    instance.tick(1.0)
    assert store.snapshot().root.properties == {"fast": 10, "normal": 20, "structural": 3}
    song.structural = 30
    instance.tick(10.0)
    assert store.snapshot().root.properties == {"fast": 10, "normal": 20, "structural": 30}


def test_session_resume_and_new_runtime_uuid() -> None:
    first, _, transport = runtime(session_id="stable")
    first.tick(0)
    transport.connected = False
    first.tick(1)
    assert transport.connect_times == [0.0, 1.0]
    handshakes = [record for record in transport.sent if "resume" in record]
    assert handshakes[-1]["session_id"] == "stable"
    assert handshakes[-1]["resume"] is True
    second, _, _ = runtime()
    third, _, _ = runtime()
    assert second.session_id != third.session_id


def test_inbound_messages_only_accept_ack_and_transport_error() -> None:
    instance, _, _ = runtime()
    assert instance.handle_inbound({"type": "handshake_ack", "ok": True})
    assert instance.handle_inbound({"type": "transport_error", "error": "closed"})
    assert not instance.handle_inbound({"type": "command", "name": "set_tempo"})
    assert not instance.handle_inbound({"type": "command", "ok": True})
    assert not instance.handle_inbound({"kind": "set_tempo", "error": "no"})


def test_resync_ack_clears_partial_then_publishes_complete() -> None:
    instance, _, transport = runtime()
    instance.tick(0.0)
    assert instance.handle_inbound({"type": "transport_error", "error": "disconnect"})
    assert instance.runtime_outcome == "partial_result"
    instance.tick(0.1)
    replacement = [item for item in transport.sent if item.get("kind") == "update"][-1]
    assert replacement["replace_graph"] is True
    assert replacement["discovery_complete"] is False
    generation = replacement["resync_generation"]
    assert instance.handle_inbound(
        {
            "type": "publication_ack",
            "bridge_revision": 2,
            "resync_generation": generation,
            "complete": False,
        }
    )
    assert instance.runtime_outcome is None
    instance.tick(0.2)
    final = [item for item in transport.sent if item.get("kind") == "update"][-1]
    assert final["replace_graph"] is False
    assert final["discovery_complete"] is True


def test_terminal_capacity_error_stays_partial_without_automatic_retry() -> None:
    instance, engine, transport = runtime()
    instance.tick(0.0)
    calls = engine.calls
    updates = len([item for item in transport.sent if item.get("kind") == "update"])
    assert instance.handle_inbound(
        {
            "type": "transport_error",
            "error": "_TerminalPublicationError",
            "action": "capacity_exceeded_manual_action",
        }
    )
    instance.tick(0.01)
    instance.tick(0.02)
    assert instance.runtime_outcome == "partial_result"
    assert instance.runtime_action == "reduce_observation_size_or_capacity"
    assert engine.calls == calls
    terminal_updates = [
        item for item in transport.sent if item.get("runtime_outcome") == "partial_result"
    ]
    assert len(terminal_updates) == 1
    for now in (10.0, 20.0, 30.0):
        instance.tick(now)
    assert engine.calls == calls
    assert (
        len([item for item in transport.sent if item.get("runtime_outcome") == "partial_result"])
        == 1
    )
    assert len([item for item in transport.sent if item.get("kind") == "update"]) == updates + 1


def test_terminal_capacity_recovery_is_externally_visible_through_store_status() -> None:
    store = GraphStore()
    transport = StoreTransport(store)
    instance = AdapterRuntime(
        ListenableRoot(),
        {},
        transport,
        discovery=FakeEngine(),
        session_id="capacity-status",
    )
    instance.tick(0.0)
    instance.handle_inbound(
        {
            "type": "transport_error",
            "error": "_TerminalPublicationError",
            "action": "capacity_exceeded_manual_action",
        }
    )
    instance.tick(0.01)
    status = store.status()
    assert status.completeness == "partial"
    assert status.runtime_outcome == "partial_result"
    assert status.runtime_action == "reduce_observation_size_or_capacity"


def test_tick_bounds_listener_work_before_discovery() -> None:
    root = ListenableRoot()
    instance, engine, _ = runtime(root, max_members=3)
    for _ in range(10):
        instance.register_listener(root, "tempo")
    instance.tick(0.0)
    assert len(root.callbacks) == 3
    assert engine.calls == 0


def _observation(source_id: str, value: int) -> dict[str, object]:
    return {
        "source_id": source_id,
        "type": "Track",
        "path": source_id,
        "properties": {"value": value},
        "relationships": {},
        "outcomes": [],
        "captured_at": "2026-01-01T00:00:00Z",
    }


def _batch(source_id: str, value: int) -> dict[str, object]:
    return {
        "kind": "update",
        "protocol_version": 1,
        "session_id": "session",
        "live_version": "12.4.2",
        "captured_at": "2026-01-01T00:00:00Z",
        "observations": [_observation(source_id, value)],
        "removed_source_ids": [],
        "discovery_complete": False,
    }


def test_socket_transport_preserves_offline_patch_order_before_capacity() -> None:
    transport = SocketTransport("127.0.0.1", 1, "secret", max_records=2)
    assert transport.send(_batch("one", 1))
    assert transport.send(_batch("one", 2))
    assert transport.pending_count == 2
    assert not transport.send(_batch("two", 1))
    assert transport.pending_count == 2
    assert transport.runtime_outcome == "partial_result"


def test_offline_failure_success_and_unrelated_patch_are_not_coalesced() -> None:
    transport = SocketTransport("127.0.0.1", 1, "secret")
    failure = _batch("one", 1)
    failure["observations"][0].update(
        {
            "properties": {},
            "outcomes": [{"member": "value", "status": "read_failed", "reason": "failed"}],
            "attempted_members": ["value"],
            "update_mode": "patch",
        }
    )
    success = _batch("one", 2)
    success["observations"][0].update({"attempted_members": ["value"], "update_mode": "patch"})
    unrelated = _batch("one", 2)
    unrelated["observations"][0].update(
        {
            "properties": {"other": 3},
            "attempted_members": ["other"],
            "update_mode": "patch",
        }
    )
    assert transport.send(failure)
    assert transport.send(success)
    assert transport.send(unrelated)
    assert transport.pending_records == [failure, success, unrelated]


def test_socket_send_does_not_serialize_on_live_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = SocketTransport("127.0.0.1", 1, "secret")

    def fail(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("serialization belongs on worker")

    monkeypatch.setattr("ableton_ctrl.adapter.runtime.json.dumps", fail)
    assert transport.send(_batch("one", 1))


def test_socket_worker_splits_large_update_into_bounded_transaction_frames() -> None:
    record = _batch("one", 1)
    record["observations"] = [
        _observation(f"track:{index}", index) | {"properties": {"blob": "x" * 200_000}}
        for index in range(7)
    ]
    frames = SocketTransport._wire_records(record)
    assert len(frames) > 1
    assert all(
        len(json.dumps(frame, separators=(",", ":")).encode()) + 1 <= 1_048_576 for frame in frames
    )
    assert [frame["part_index"] for frame in frames] == list(range(len(frames)))
    assert frames[-1]["final"] is True


@pytest.mark.parametrize(
    ("limit_name", "value"),
    [
        ("_TRANSACTION_OBSERVATION_LIMIT", 0),
        ("_TRANSACTION_REMOVAL_LIMIT", 0),
        ("_TRANSACTION_PART_LIMIT", 0),
        ("_TRANSACTION_BYTE_LIMIT", 1),
    ],
)
def test_worker_preflight_rejects_every_aggregate_overflow(
    monkeypatch: pytest.MonkeyPatch, limit_name: str, value: int
) -> None:
    record = _batch("one", 1)
    if limit_name == "_TRANSACTION_REMOVAL_LIMIT":
        record["observations"] = []
        record["removed_source_ids"] = ["gone"]
    monkeypatch.setattr(f"ableton_ctrl.adapter.runtime.{limit_name}", value)
    with pytest.raises(ValueError):
        SocketTransport._wire_records(record)


def test_socket_handshake_preserves_resume_and_exact_version() -> None:
    transport = SocketTransport("127.0.0.1", 1, "secret")
    transport._start_worker = lambda: None
    assert transport.connect(
        {
            "session_id": "stable",
            "live_version": "12.4.2",
            "edition": "Intro",
            "resume": True,
        }
    )
    frame = transport.pending_records[0]
    assert frame["message"] == {
        "kind": "hello",
        "session_id": "stable",
        "live_version": "12.4.2",
        "edition": "Intro",
        "resume": True,
    }


def test_reconnect_authentication_precedes_retained_update_until_ack() -> None:
    transport = SocketTransport("127.0.0.1", 1, "secret")
    transport._start_worker = lambda: None
    retained = _batch("one", 1)
    assert transport.send(retained)
    assert transport.connect(
        {
            "session_id": "stable",
            "live_version": "12.4.2",
            "edition": "Intro",
            "resume": True,
        }
    )
    assert transport.pending_records[0]["message"]["kind"] == "hello"
    queued = transport._next_record()
    assert queued is not None
    key, _ = queued
    assert transport.pending_count == 2
    transport._ack_record(key)
    assert transport.pending_records == [retained]


def test_remote_script_publishes_mismatch_without_song_traversal(monkeypatch: object) -> None:
    class Application:
        def get_major_version(self) -> int:
            return 12

        def get_minor_version(self) -> int:
            return 4

        def get_bugfix_version(self) -> int:
            return 1

        def get_product_name(self) -> str:
            return "Live Intro"

    class CInstance:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def show_message(self, message: str) -> None:
            self.messages.append(message)

    class ControlSurface:
        def __init__(self, c_instance: CInstance) -> None:
            self.c_instance = c_instance

        def application(self) -> Application:
            return Application()

        def song(self) -> object:
            raise AssertionError("version mismatch must not traverse song")

        def disconnect(self) -> None:
            pass

    framework = types.ModuleType("_Framework")
    control_surface = types.ModuleType("_Framework.ControlSurface")
    control_surface.ControlSurface = ControlSurface
    monkeypatch.setitem(sys.modules, "_Framework", framework)
    monkeypatch.setitem(sys.modules, "_Framework.ControlSurface", control_surface)
    module = importlib.import_module("ableton_ctrl.adapter.remote_script")
    module = importlib.reload(module)
    c_instance = CInstance()
    surface = module.create_instance(c_instance)
    assert surface._runtime is None
    assert c_instance.messages == [
        "ableton-ctrl requires Live 12.4.2 Intro; found 12.4.1 Live Intro"
    ]


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _assert_read_only(tree: ast.AST) -> None:
    prefixes = ("set_", "start_", "stop_", "fire", "delete_", "duplicate_")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            )
            assert name not in {"setattr", "eval", "exec", "compile"}
            assert not name.startswith(prefixes)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute):
                    assert _root_name(target) not in {
                        "root",
                        "song",
                        "live_object",
                        "application",
                    }


def test_adapter_sources_are_statically_read_only() -> None:
    for path in Path("src/ableton_ctrl/adapter").glob("*.py"):
        _assert_read_only(ast.parse(path.read_text()))


@pytest.mark.parametrize("operator", ["=", ": int =", "+="])
def test_static_guard_rejects_live_rooted_attribute_assignment(operator: str) -> None:
    with pytest.raises(AssertionError):
        _assert_read_only(ast.parse(f"root.track.tempo {operator} 120"))
