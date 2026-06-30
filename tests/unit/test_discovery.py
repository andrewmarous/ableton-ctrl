from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from ableton_ctrl.adapter.discovery import DiscoveryBudget, DiscoveryEngine
from ableton_ctrl.adapter.manifest import (
    LIVE_12_4_2_INTRO_MANIFEST,
    PropertySpec,
    RelationshipSpec,
    TypeSpec,
)
from fakes.live import FakeSong, FakeTrack  # noqa: E402


def _manifest_with_test_members() -> dict[str, TypeSpec]:
    song = LIVE_12_4_2_INTRO_MANIFEST["Song"]
    track = LIVE_12_4_2_INTRO_MANIFEST["Track"]
    return dict(
        LIVE_12_4_2_INTRO_MANIFEST,
        Song=replace(
            song,
            properties=(
                *song.properties,
                PropertySpec("mode", "mode", None, "Current test mode.", "slow"),
                PropertySpec("binary", "binary", None, "Opaque binary test value.", "slow"),
                PropertySpec("deep", "deep", None, "Over-deep test value.", "slow"),
                PropertySpec("huge", "huge", None, "Oversized test value.", "slow"),
            ),
            relationships=(
                *song.relationships,
                RelationshipSpec("loop", "loop", "Song", "single", "Cyclic self-reference."),
            ),
        ),
        Track=replace(
            track,
            properties=(
                *track.properties,
                PropertySpec("missing", "missing", None, "Missing test member.", "slow"),
                PropertySpec("broken", "broken", None, "Failing test descriptor.", "slow"),
            ),
        ),
    )


def test_discovery_classifies_members_without_accessing_excluded_callables() -> None:
    engine = DiscoveryEngine(_manifest_with_test_members())
    result = engine.observe(FakeSong([FakeTrack()]), DiscoveryBudget(100, 1_000))

    track = next(item for item in result.observations if item.type == "Track")
    assert track.properties["name"] == "Bass"
    assert track.properties["color"] == 16711680
    outcomes = {item.member: item.status for item in track.outcomes}
    assert outcomes["missing"] == "unavailable"
    assert outcomes["broken"] == "read_failed"
    assert outcomes["start_playing"] == "excluded"
    assert outcomes["stop_playing"] == "excluded"
    broken = next(item for item in track.outcomes if item.member == "broken")
    assert broken.reason == "RuntimeError"
    assert "secret" not in broken.reason


def test_discovery_normalizes_values_and_relationships_and_stops_cycles() -> None:
    engine = DiscoveryEngine(_manifest_with_test_members())
    result = engine.observe(FakeSong([FakeTrack()]), DiscoveryBudget(100, 1_000))

    song = next(item for item in result.observations if item.type == "Song")
    assert song.properties["binary"] == {"kind": "binary", "size": 3}
    assert song.properties["mode"] == "session"
    assert song.relationships["tracks"] == [
        next(item.source_id for item in result.observations if item.type == "Track")
    ]
    assert song.relationships["loop"] == [song.source_id]
    assert {item.member: item.status for item in song.outcomes}["deep"] == "excluded"
    assert {item.member: item.status for item in song.outcomes}["huge"] == "excluded"
    assert len([item for item in result.observations if item.type == "Song"]) == 1
    assert result.complete is True
    assert result.remaining_work == 0


def test_discovery_is_resumable_and_honors_member_budget() -> None:
    engine = DiscoveryEngine(_manifest_with_test_members())
    root = FakeSong([FakeTrack()])
    slices = []

    while True:
        result = engine.observe(root, DiscoveryBudget(max_members=1, max_milliseconds=1_000))
        slices.append(result)
        assert len(result.coverage) <= 1
        if result.complete:
            break

    observations = [item for result in slices for item in result.observations]
    assert {item.type for item in observations} == {"Song", "Track"}
    assert len(slices) > 2
    assert slices[-1].remaining_work == 0


def test_zero_time_budget_leaves_work_resumable() -> None:
    engine = DiscoveryEngine(_manifest_with_test_members())
    result = engine.observe(
        FakeSong([FakeTrack()]),
        DiscoveryBudget(max_members=100, max_milliseconds=0),
    )

    assert result.observations == ()
    assert result.coverage == ()
    assert result.complete is False
    assert result.remaining_work > 0


def test_positive_deadline_resumes_without_rereads_or_skips() -> None:
    moments = iter((0.0, 0.0, 0.0011, 1.0, 1.0, 1.0011))
    reads: list[str] = []

    class Song:
        @property
        def first(self) -> int:
            reads.append("first")
            return 1

        @property
        def second(self) -> int:
            reads.append("second")
            return 2

    manifest = {
        "Song": TypeSpec(
            "Song",
            properties=(
                PropertySpec("first", "first", None, "first", "slow"),
                PropertySpec("second", "second", None, "second", "slow"),
            ),
        )
    }
    engine = DiscoveryEngine(manifest, clock=lambda: next(moments))
    song = Song()
    first = engine.observe(song, DiscoveryBudget(100, 1.0))
    assert not first.complete
    second = engine.observe(song, DiscoveryBudget(100, 1.0))
    assert second.complete
    assert reads == ["first", "second"]


def test_structural_discovery_reports_objects_removed_from_root_reachability() -> None:
    track = FakeTrack()
    song = FakeSong([track])
    engine = DiscoveryEngine(_manifest_with_test_members())
    first = engine.observe_targeted(
        song, DiscoveryBudget(1_000, 1_000), frozenset({"structural"}), frozenset()
    )
    track_id = next(item.source_id for item in first.observations if item.type == "Track")
    song.tracks = []
    second = engine.observe_targeted(
        song, DiscoveryBudget(1_000, 1_000), frozenset({"structural"}), frozenset()
    )
    assert second.removed_source_ids == (track_id,)


def test_same_index_replacement_gets_new_source_id_and_removes_old_identity() -> None:
    first_track = FakeTrack()
    song = FakeSong([first_track])
    engine = DiscoveryEngine(_manifest_with_test_members())
    first = engine.observe_targeted(
        song, DiscoveryBudget(1_000, 1_000), frozenset({"structural"}), frozenset()
    )
    old_id = next(item.source_id for item in first.observations if item.type == "Track")
    song.tracks = [FakeTrack()]
    second = engine.observe_targeted(
        song, DiscoveryBudget(1_000, 1_000), frozenset({"structural"}), frozenset()
    )
    new_id = next(item.source_id for item in second.observations if item.type == "Track")
    assert new_id != old_id
    assert second.removed_source_ids == (old_id,)


def test_targeted_observation_reads_only_due_or_dirty_members() -> None:
    reads: list[str] = []

    class Song:
        @property
        def fast_value(self) -> int:
            reads.append("fast_value")
            return 1

        @property
        def normal_value(self) -> int:
            reads.append("normal_value")
            return 2

        @property
        def static_value(self) -> int:
            reads.append("static_value")
            return 3

    manifest = {
        "Song": TypeSpec(
            "Song",
            properties=(
                PropertySpec("fast_value", "fast_value", None, "fast", "fast"),
                PropertySpec("normal_value", "normal_value", None, "normal", "slow"),
                PropertySpec("static_value", "static_value", None, "static", "static"),
            ),
        )
    }
    song = Song()
    engine = DiscoveryEngine(manifest)
    budget = DiscoveryBudget(100, 100)

    engine.observe_targeted(song, budget, frozenset({"fast"}), frozenset())
    assert reads == ["fast_value"]
    reads.clear()
    engine.observe_targeted(song, budget, frozenset({"normal"}), frozenset())
    assert reads == ["normal_value"]
    reads.clear()
    engine.observe_targeted(song, budget, frozenset({"structural"}), frozenset())
    assert reads == ["static_value"]
    reads.clear()
    engine.observe_targeted(
        song,
        budget,
        frozenset(),
        frozenset({(id(song), "normal_value")}),
    )
    assert reads == ["normal_value"]


def test_targeted_resume_keeps_structural_selection_for_new_children() -> None:
    reads: list[str] = []

    class Child:
        @property
        def static_value(self) -> int:
            reads.append("child.static_value")
            return 1

    class Song:
        def __init__(self) -> None:
            self.children = [Child()]

    manifest = {
        "Song": TypeSpec(
            "Song",
            relationships=(
                RelationshipSpec("children", "children", "Child", "collection", "children"),
            ),
        ),
        "Child": TypeSpec(
            "Child",
            properties=(PropertySpec("static_value", "static_value", None, "static", "static"),),
        ),
    }
    engine = DiscoveryEngine(manifest)
    song = Song()

    first = engine.observe_targeted(
        song,
        DiscoveryBudget(1, 100),
        frozenset({"structural"}),
        frozenset(),
    )
    assert not first.complete
    assert reads == []
    second = engine.observe_targeted(
        song,
        DiscoveryBudget(1, 100),
        frozenset(),
        frozenset(),
    )
    assert second.complete
    assert reads == ["child.static_value"]


def test_manifest_is_internally_safe_and_complete() -> None:
    forbidden_prefixes = ("set_", "delete_", "duplicate_", "create_", "invoke_")
    expected_types = {
        "Song",
        "Track",
        "Scene",
        "ClipSlot",
        "Clip",
        "Device",
        "DeviceParameter",
        "MixerDevice",
    }
    assert set(LIVE_12_4_2_INTRO_MANIFEST) == expected_types

    for type_name, spec in LIVE_12_4_2_INTRO_MANIFEST.items():
        assert spec.live_type == type_name
        names = [item.name for item in (*spec.properties, *spec.relationships)]
        live_members = [item.live_member for item in (*spec.properties, *spec.relationships)]
        assert len(names) == len(set(names))
        assert len(live_members) == len(set(live_members))
        for prop in spec.properties:
            assert prop.name.strip()
            assert prop.live_member.strip()
            assert prop.description.strip()
            assert prop.poll_class.strip()
            assert prop.unit is None or prop.unit.strip()
            if prop.exclusion_reason:
                assert prop.exclusion_reason.strip()
            else:
                assert not prop.name.startswith(forbidden_prefixes)
        for relationship in spec.relationships:
            assert relationship.name.strip()
            assert relationship.live_member.strip()
            assert relationship.description.strip()
            assert relationship.target_type in LIVE_12_4_2_INTRO_MANIFEST
            assert relationship.cardinality in {"single", "collection"}
            if relationship.exclusion_reason:
                assert relationship.exclusion_reason.strip()
            else:
                assert not relationship.name.startswith(forbidden_prefixes)
                assert not relationship.live_member.startswith(forbidden_prefixes)
