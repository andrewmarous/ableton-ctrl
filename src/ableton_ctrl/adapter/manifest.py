"""The conservative shared Ableton Live 12 observation allowlist."""

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
            _property("signature_numerator", "Time-signature numerator.", poll_class="normal"),
            _property("signature_denominator", "Time-signature denominator.", poll_class="normal"),
            _property("current_song_time", "Current arrangement song position.", unit="beats", poll_class="fast"),
            _property("loop", "Whether the arrangement loop is enabled.", poll_class="fast"),
            _property("loop_start", "Arrangement loop start.", unit="beats"),
            _property("loop_length", "Arrangement loop length.", unit="beats"),
            _property("record_mode", "Whether arrangement recording is active.", poll_class="fast"),
            _action("start_playing", "Starts transport playback."),
            _action("stop_playing", "Stops transport playback."),
        ),
        relationships=(
            _relationship("tracks", "Track", "collection", "Tracks in canonical Live order."),
            _relationship("scenes", "Scene", "collection", "Scenes in canonical Live order."),
            _relationship("master_track", "Track", "single", "The Live Set master track."),
            _relationship("return_tracks", "Track", "collection", "Return tracks in canonical order."),
            _relationship("cue_points", "CuePoint", "collection", "Arrangement locators in time order."),
            _relationship("view", "SongView", "single", "Read-only Live Set selection view."),
        ),
    ),
    "Track": TypeSpec(
        "Track",
        properties=(
            _property("name", "Track display name."),
            _property("color", "Track color encoded as a Live integer."),
            _property("is_foldable", "Whether the track can contain child tracks."),
            _property("mute", "Whether the track is muted.", poll_class="fast"),
            _property("solo", "Whether the track is soloed.", poll_class="fast"),
            _property("arm", "Whether the track is armed.", poll_class="fast"),
            _property("has_audio_input", "Whether the track accepts audio input."),
            _property("has_midi_input", "Whether the track accepts MIDI input."),
            _property("is_grouped", "Whether the track belongs to a group."),
            _property("is_frozen", "Whether the track is frozen."),
            _property("current_input_routing", "Current input routing display value."),
            _property("current_output_routing", "Current output routing display value."),
            _action("start_playing", "Starts track playback."),
            _action("stop_playing", "Stops track playback."),
        ),
        relationships=(
            _relationship("clip_slots", "ClipSlot", "collection", "Clip slots in scene order."),
            _relationship("devices", "Device", "collection", "Devices in chain order."),
            _relationship("mixer_device", "MixerDevice", "single", "The track mixer device."),
            _relationship("group_track", "Track", "single", "Containing group track, if any."),
            _relationship("arrangement_clips", "Clip", "collection", "Clips in the Arrangement timeline."),
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
            _property("is_audio_clip", "Whether this is an audio clip."),
            _property("is_midi_clip", "Whether this is a MIDI clip."),
            _property("start_time", "Arrangement start position.", unit="beats"),
            _property("end_time", "Arrangement end position.", unit="beats"),
            _property("looping", "Whether clip looping is enabled."),
            _property("loop_start", "Clip loop start.", unit="beats"),
            _property("loop_end", "Clip loop end.", unit="beats"),
            _property("start_marker", "Clip start marker.", unit="beats"),
            _property("end_marker", "Clip end marker.", unit="beats"),
            _property("launch_mode", "Clip launch mode."),
            _property("warping", "Whether audio warping is enabled."),
            _property("warp_mode", "Audio warp mode."),
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
            _property("can_have_chains", "Whether the device can contain rack chains."),
        ),
        relationships=(
            _relationship(
                "parameters",
                "DeviceParameter",
                "collection",
                "Device parameters in canonical order.",
            ),
            _relationship("chains", "Chain", "collection", "Rack chains in canonical order."),
            _relationship("drum_pads", "DrumPad", "collection", "Visible drum pads."),
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
            _property("value_items", "Display values for a quantized parameter."),
        ),
    ),
    "MixerDevice": TypeSpec(
        "MixerDevice",
        relationships=(
            _relationship("volume", "DeviceParameter", "single", "Track volume parameter."),
            _relationship("panning", "DeviceParameter", "single", "Track panning parameter."),
            _relationship("crossfader", "DeviceParameter", "single", "Master crossfader parameter."),
            _relationship("sends", "DeviceParameter", "collection", "Track send parameters."),
        ),
    ),
    "Chain": TypeSpec(
        "Chain",
        properties=(
            _property("name", "Rack chain display name."),
            _property("color", "Rack chain color encoded as a Live integer."),
        ),
        relationships=(
            _relationship("devices", "Device", "collection", "Devices in chain order."),
            _relationship("mixer_device", "MixerDevice", "single", "Chain mixer device."),
        ),
    ),
    "DrumPad": TypeSpec(
        "DrumPad",
        properties=(
            _property("name", "Drum pad display name."),
            _property("note", "MIDI note assigned to the drum pad.", unit="midi_note"),
        ),
        relationships=(
            _relationship("chains", "Chain", "collection", "Chains associated with the pad."),
        ),
    ),
    "CuePoint": TypeSpec(
        "CuePoint",
        properties=(
            _property("name", "Arrangement locator display name."),
            _property("time", "Arrangement locator position.", unit="beats"),
        ),
    ),
    "SongView": TypeSpec(
        "SongView",
        relationships=(
            _relationship("selected_track", "Track", "single", "Currently selected track."),
            _relationship("selected_scene", "Scene", "single", "Currently selected scene."),
            _relationship("selected_device", "Device", "single", "Currently selected device."),
            _relationship("detail_clip", "Clip", "single", "Clip shown in the detail view."),
        ),
    ),
}

# Availability is determined by the running Live build during discovery, not by
# an edition label. Keep the old export as a compatibility alias for consumers.
LIVE_12_MANIFEST = LIVE_12_4_2_INTRO_MANIFEST

LIVE_12_CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "set": ("Song", "CuePoint"),
    "tracks": ("Track",),
    "mixer": ("MixerDevice", "DeviceParameter"),
    "arrangement": ("Clip",),
    "clips": ("Clip", "ClipSlot"),
    "devices": ("Device", "Chain", "DrumPad", "DeviceParameter"),
    "selection": ("SongView",),
}
