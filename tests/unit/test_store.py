from datetime import datetime, timedelta, timezone
import json

import pytest

from ableton_ctrl.bridge.store import GraphStore, SchemaMemberDefinition, StoreError
from ableton_ctrl.contracts import MemberOutcome, ObjectObservation, UpdateBatch

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


def batch(session: str, name: str = "Track 1") -> UpdateBatch:
    track = ObjectObservation(
        source_id="track:1",
        type="Track",
        path="Live Set/Track 1",
        properties={"name": name},
        relationships={},
        outcomes=[],
        captured_at=NOW,
    )
    song = ObjectObservation(
        source_id="song",
        type="Song",
        path="Live Set",
        properties={"tempo": 120.0},
        relationships={"tracks": ["track:1"]},
        outcomes=[],
        captured_at=NOW,
    )
    return UpdateBatch(
        session_id=session,
        live_version="12.4.2",
        captured_at=NOW,
        observations=[song, track],
        removed_source_ids=[],
    )


def test_identity_is_stable_and_revision_increases_per_batch() -> None:
    store = GraphStore(history_limit=2)
    assert store.apply(batch("s1")) == 1
    first_id = (
        store.search(
            name="Track 1",
            object_type=None,
            path=None,
            offset=0,
            limit=10,
            revision=1,
        )
        .items[0]
        .object_id
    )
    assert store.apply(batch("s1", "Bass")) == 2
    assert store.get_object(first_id).properties["name"] == "Bass"


def test_remove_then_readd_source_allocates_new_object_id_and_old_id_stays_invalid() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    old_id = store.search(name="Track 1", limit=10).items[0].object_id
    removal = batch("s1").model_copy(
        update={
            "observations": [
                batch("s1").observations[0].model_copy(update={"relationships": {"tracks": []}})
            ],
            "removed_source_ids": ["track:1"],
        }
    )
    store.apply(removal)
    with pytest.raises(StoreError, match="not_found"):
        store.get_object(old_id)
    store.apply(batch("s1", "Readded"))
    new_id = store.search(name="Readded", limit=10).items[0].object_id
    assert new_id != old_id
    with pytest.raises(StoreError, match="not_found"):
        store.get_object(old_id)


def test_replace_graph_transaction_leaves_no_stale_nodes_or_ids() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    old_track_id = store.search(object_type="Track", limit=10).items[0].object_id
    replacement_song = (
        batch("s1").observations[0].model_copy(update={"relationships": {"tracks": []}})
    )
    replacement = batch("s1").model_copy(
        update={
            "observations": [replacement_song],
            "replace_graph": True,
            "discovery_complete": False,
        }
    )
    store.apply(replacement)
    snapshot = store.snapshot()
    assert snapshot.root.relationships["tracks"].items == []
    assert store.search(object_type="Track", limit=10).items == []
    with pytest.raises(StoreError, match="not_found"):
        store.get_object(old_track_id)


def test_replace_graph_preserves_ids_for_unchanged_sources_in_same_session() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    before = {item.type: item.object_id for item in store.search(limit=10).items}
    store.apply(batch("s1").model_copy(update={"replace_graph": True}))
    after = {item.type: item.object_id for item in store.search(limit=10).items}
    assert after == before


def test_patch_failure_success_transitions_clear_stale_value_and_outcome() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    track = batch("s1").observations[1]
    failure = track.model_copy(
        update={
            "properties": {},
            "outcomes": [MemberOutcome(member="name", status="read_failed", reason="RuntimeError")],
            "update_mode": "patch",
            "attempted_members": ["name"],
            "captured_at": NOW + timedelta(seconds=1),
        }
    )
    store.apply(batch("s1").model_copy(update={"observations": [failure]}))
    track_id = store.search(object_type="Track", limit=10).items[0].object_id
    failed = store.get_object(track_id)
    assert "name" not in failed.properties
    assert failed.outcomes[0].status == "read_failed"
    assert failed.object_captured_at == NOW + timedelta(seconds=1)
    success = failure.model_copy(
        update={
            "properties": {"name": "Recovered"},
            "outcomes": [],
            "captured_at": NOW + timedelta(seconds=2),
        }
    )
    store.apply(batch("s1").model_copy(update={"observations": [success]}))
    recovered = store.get_object(track_id)
    assert recovered.properties["name"] == "Recovered"
    assert recovered.outcomes == []
    assert recovered.object_captured_at == NOW + timedelta(seconds=2)


def test_new_session_invalidates_ids_and_cursors() -> None:
    store = GraphStore(history_limit=2)
    store.apply(batch("s1"))
    old_id = store.snapshot(depth=0, page_size=10).root.object_id
    store.apply(batch("s2"))
    with pytest.raises(StoreError, match="session_changed"):
        store.get_object(old_id)
    with pytest.raises(StoreError, match="session_changed"):
        store.get_changes(session_id="s1", after_revision=1)


def test_expired_revision_is_never_used_for_pagination() -> None:
    store = GraphStore(history_limit=1)
    store.apply(batch("s1"))
    store.apply(batch("s1", "Bass"))
    with pytest.raises(StoreError, match="stale_cursor"):
        store.list_children(
            store.snapshot(0, 10).root.object_id,
            "tracks",
            0,
            10,
            1,
        )


def test_snapshot_children_and_search_are_bounded_and_revision_pinned() -> None:
    store = GraphStore()
    store.apply(batch("s1"))

    snapshot = store.snapshot(depth=0, page_size=1)
    assert snapshot.completeness == "partial"
    assert snapshot.root.relationships["tracks"].continuation is not None
    assert snapshot.bridge_revision == 1
    assert snapshot.live_version == "12.4.2"

    page = store.list_children(
        snapshot.root.object_id,
        "tracks",
        offset=0,
        limit=1,
        revision=1,
    )
    assert page.revision == 1
    assert page.total == 1

    matches = store.search(
        name="track",
        object_type="Track",
        path="Live Set",
        offset=0,
        limit=10,
        revision=1,
    )
    assert [item.path for item in matches.items] == ["Live Set/Track 1"]


def test_status_reports_offline_then_stale() -> None:
    current = NOW

    def clock() -> datetime:
        return current

    store = GraphStore(clock=clock)
    assert store.status().state == "live_offline"
    store.apply(batch("s1"))
    current = NOW + timedelta(seconds=6)
    assert store.status(stale_after_seconds=5).state == "stale_state"


def test_mark_offline_retains_cached_graph_and_resumes_same_session() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    cached = store.snapshot(depth=8, page_size=200).root.model_dump_json()

    store.mark_offline()

    status = store.status()
    assert status.state == "live_offline"
    assert status.live_connected is False
    assert status.session_id == "s1"
    assert store.snapshot(depth=8, page_size=200).root.model_dump_json() == cached
    assert store.apply(batch("s1", "Bass")) == 2
    assert store.status().live_connected is True


def test_invalid_batch_is_atomic_and_revision_snapshots_are_immutable() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    invalid = batch("s1", "Bass").model_copy(
        update={
            "observations": [
                batch("s1", "Bass")
                .observations[0]
                .model_copy(update={"relationships": {"tracks": ["missing"]}})
            ]
        }
    )
    with pytest.raises(StoreError, match="invalid_relationship"):
        store.apply(invalid)
    assert store.status().bridge_revision == 1
    assert store.search(name="Track 1", revision=1).total == 1


def test_changes_removals_failures_and_schema_are_aggregated() -> None:
    store = GraphStore()
    initial = batch("s1")
    initial.observations[1].outcomes.append(
        MemberOutcome(member="color", status="read_failed", reason="Live error")
    )
    store.apply(initial)
    schema = store.get_schema("track")
    assert schema.types[0].normalized_type == "track"
    assert [member.name for member in schema.types[0].members] == ["color", "name"]
    assert schema.types[0].members[0].read_failed_count == 1

    removal = UpdateBatch(
        session_id="s1",
        live_version="12.4.2",
        captured_at=NOW,
        observations=[initial.observations[0].model_copy(update={"relationships": {"tracks": []}})],
        removed_source_ids=["track:1"],
    )
    store.apply(removal)
    changes = store.get_changes("s1", after_revision=1)
    assert changes.next_revision == 2
    assert [change.kind for change in changes.changes[0].changes] == [
        "removed",
        "relationships_changed",
    ]


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        (lambda store: store.snapshot(depth=9), "invalid_bounds"),
        (lambda store: store.snapshot(page_size=201), "invalid_bounds"),
        (lambda store: store.search(name="x" * 257), "invalid_bounds"),
        (lambda store: store.search(limit=201), "invalid_bounds"),
        (lambda store: store.get_changes("s1", 0, limit=501), "invalid_bounds"),
    ],
)
def test_query_bounds_raise_typed_errors(
    operation: object,
    error: str,
) -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    with pytest.raises(StoreError, match=error):
        assert callable(operation)
        operation(store)


def test_snapshot_continuation_advances_past_embedded_references() -> None:
    update = batch("s1")
    update.observations.append(
        ObjectObservation(
            source_id="track:2",
            type="Track",
            path="Live Set/Track 2",
            properties={"name": "Track 2"},
            relationships={},
            outcomes=[],
            captured_at=NOW,
        )
    )
    update.observations[0].relationships["tracks"].append("track:2")
    store = GraphStore()
    store.apply(update)

    snapshot = store.snapshot(depth=0, page_size=1)
    embedded = snapshot.root.relationships["tracks"].items
    assert snapshot.root.relationships["tracks"].continuation == "1:1"
    following = store.list_children(
        snapshot.root.object_id,
        "tracks",
        offset=1,
        limit=1,
        revision=1,
    )
    assert embedded[0].object_id != following.items[0].object_id


def test_schema_outcomes_keep_kind_and_manifest_metadata_separate() -> None:
    store = GraphStore(
        schema_metadata={
            "track": {
                "devices": SchemaMemberDefinition(
                    kind="relationship",
                    manifest_metadata={"introduced_in": "12.0"},
                )
            }
        }
    )
    update = batch("s1")
    update.observations[1].outcomes.append(
        MemberOutcome(member="devices", status="unavailable", reason="Not exposed")
    )
    store.apply(update)

    member = next(
        item for item in store.get_schema("Track").types[0].members if item.name == "devices"
    )
    assert member.kind == "relationship"
    assert member.runtime_available is False
    assert member.unavailable_count == 1
    assert member.manifest_metadata == {"introduced_in": "12.0"}


def test_all_query_results_are_json_serializable_and_versioned() -> None:
    store = GraphStore()
    store.apply(batch("s1"))
    root_id = store.snapshot(depth=0, page_size=1).root.object_id
    results = [
        store.status(),
        store.snapshot(depth=0, page_size=1),
        store.get_object(root_id),
        store.list_children(root_id, "tracks", revision=1),
        store.search(revision=1),
        store.get_schema(revision=1),
        store.get_changes("s1", 0),
    ]

    for result in results:
        payload = json.loads(result.model_dump_json())
        assert payload["protocol_version"] == 1
        assert payload["live_version"] == "12.4.2"
        assert payload["session_id"] == "s1"
        assert payload["bridge_revision"] == 1
        assert payload["captured_at"] == "2026-06-29T00:00:00Z"
        assert payload["cache_age_seconds"] >= 0
        assert payload["completeness"] in {"complete", "partial"}
    assert isinstance(json.loads(results[1].model_dump_json())["root"]["outcomes"], list)


def test_offline_status_is_versioned_serializable_and_has_completeness() -> None:
    payload = json.loads(GraphStore().status().model_dump_json())
    assert payload == {
        "protocol_version": 1,
        "state": "live_offline",
        "live_connected": False,
        "live_version": None,
        "session_id": None,
        "bridge_revision": 0,
        "captured_at": None,
        "cache_age_seconds": None,
        "completeness": "unavailable",
        "runtime_outcome": None,
        "runtime_action": None,
    }


def test_incomplete_discovery_propagates_to_graph_query_completeness() -> None:
    store = GraphStore()
    store.apply(batch("s1").model_copy(update={"discovery_complete": False}))
    snapshot = store.snapshot(depth=1, page_size=10)
    track_id = store.search(name="Track 1", revision=1).items[0].object_id

    assert snapshot.completeness == "partial"
    assert store.get_object(track_id, revision=1).completeness == "partial"
    assert (
        store.list_children(
            snapshot.root.object_id,
            "tracks",
            limit=10,
            revision=1,
        ).completeness
        == "partial"
    )
    assert store.search(limit=10, revision=1).completeness == "partial"


def test_complete_discovery_allows_complete_untruncated_queries() -> None:
    store = GraphStore()
    store.apply(batch("s1").model_copy(update={"discovery_complete": True}))
    snapshot = store.snapshot(depth=1, page_size=10)
    track_id = store.search(name="Track 1", revision=1).items[0].object_id

    assert snapshot.completeness == "complete"
    assert store.get_object(track_id, revision=1).completeness == "complete"
    assert (
        store.list_children(
            snapshot.root.object_id,
            "tracks",
            limit=10,
            revision=1,
        ).completeness
        == "complete"
    )
    assert store.search(limit=10, revision=1).completeness == "complete"


def test_mutating_returned_changes_does_not_mutate_retained_history() -> None:
    store = GraphStore()
    store.apply(batch("s1"))

    first = store.get_changes("s1", 0)
    first.changes[0].changes.clear()

    second = store.get_changes("s1", 0)
    assert [change.kind for change in second.changes[0].changes] == ["added", "added"]
