"""The conservative Ableton Live 12.4.2 Intro observation allowlist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PropertySpec:
    name: str
    live_member: str
    unit: str | None
    description: str
    poll_class: str
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class RelationshipSpec:
    name: str
    live_member: str
    target_type: str
    cardinality: Literal["single", "collection"]
    description: str
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class TypeSpec:
    live_type: str
    properties: tuple[PropertySpec, ...] = ()
    relationships: tuple[RelationshipSpec, ...] = ()


def _property(
    name: str,
    description: str,
    *,
    unit: str | None = None,
    poll_class: str = "slow",
    live_member: str | None = None,
    excluded: str | None = None,
) -> PropertySpec:
    return PropertySpec(name, live_member or name, unit, description, poll_class, excluded)


def _relationship(
    name: str,
    target_type: str,
    cardinality: Literal["single", "collection"],
    description: str,
) -> RelationshipSpec:
    return RelationshipSpec(name, name, target_type, cardinality, description)


def _action(name: str, description: str) -> PropertySpec:
    return _property(
        name,
        description,
        poll_class="never",
        excluded="Callable action members are outside the read-only discovery surface.",
    )


LIVE_12_4_2_INTRO_MANIFEST: dict[str, TypeSpec] = {
    "Song": TypeSpec(
        "Song",
        properties=(
            _property("name", "Live Set display name."),
            _property("tempo", "Live Set tempo.", unit="bpm", poll_class="fast"),
            _property("is_playing", "Whether transport playback is active.", poll_class="fast"),
            _action("start_playing", "Starts transport playback."),
            _action("stop_playing", "Stops transport playback."),
        ),
        relationships=(
            _relationship("tracks", "Track", "collection", "Tracks in canonical Live order."),
            _relationship("scenes", "Scene", "collection", "Scenes in canonical Live order."),
            _relationship("master_track", "Track", "single", "The Live Set master track."),
        ),
    ),
    "Track": TypeSpec(
        "Track",
        properties=(
            _property("name", "Track display name."),
            _property("color", "Track color encoded as a Live integer."),
            _property("is_foldable", "Whether the track can contain child tracks."),
            _action("start_playing", "Starts track playback."),
            _action("stop_playing", "Stops track playback."),
        ),
        relationships=(
            _relationship("clip_slots", "ClipSlot", "collection", "Clip slots in scene order."),
            _relationship("devices", "Device", "collection", "Devices in chain order."),
            _relationship("mixer_device", "MixerDevice", "single", "The track mixer device."),
        ),
    ),
    "Scene": TypeSpec(
        "Scene",
        properties=(
            _property("name", "Scene display name."),
            _property("color", "Scene color encoded as a Live integer."),
            _action("fire", "Launches the scene."),
        ),
    ),
    "ClipSlot": TypeSpec(
        "ClipSlot",
        properties=(
            _property("has_clip", "Whether the slot contains a clip.", poll_class="fast"),
            _action("fire", "Launches the clip slot."),
            _action("stop", "Stops the clip slot."),
            _action("delete_clip", "Deletes the clip in the slot."),
            _action("duplicate_clip_to", "Duplicates the clip to another slot."),
        ),
        relationships=(
            _relationship("clip", "Clip", "single", "The clip contained by this slot, if any."),
        ),
    ),
    "Clip": TypeSpec(
        "Clip",
        properties=(
            _property("name", "Clip display name."),
            _property("color", "Clip color encoded as a Live integer."),
            _property("length", "Clip duration.", unit="beats"),
            _property("is_playing", "Whether the clip is playing.", poll_class="fast"),
            _action("fire", "Launches the clip."),
            _action("stop", "Stops the clip."),
        ),
    ),
    "Device": TypeSpec(
        "Device",
        properties=(
            _property("name", "Device display name."),
            _property("class_name", "Live device class name."),
            _property("is_active", "Whether the device is active.", poll_class="fast"),
        ),
        relationships=(
            _relationship(
                "parameters",
                "DeviceParameter",
                "collection",
                "Device parameters in canonical order.",
            ),
        ),
    ),
    "DeviceParameter": TypeSpec(
        "DeviceParameter",
        properties=(
            _property("name", "Parameter display name."),
            _property("value", "Current parameter value.", poll_class="fast"),
            _property("min", "Minimum parameter value."),
            _property("max", "Maximum parameter value."),
            _property("is_quantized", "Whether the parameter has discrete values."),
        ),
    ),
    "MixerDevice": TypeSpec(
        "MixerDevice",
        relationships=(
            _relationship("volume", "DeviceParameter", "single", "Track volume parameter."),
            _relationship("panning", "DeviceParameter", "single", "Track panning parameter."),
        ),
    ),
}
