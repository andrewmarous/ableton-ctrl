# Issue #14 acceptance record

## Decision

**Status: full acceptance by explicit user override.**

The user accepted the audio-observation limitation and explicitly overrode the previous partial acceptance status:

> No, acceptance is full. I'm overriding the acceptance status marked partial.

This decision completes acceptance for the Arrangement capabilities and the related creator controls.
The decision does not change historical test results or convert unverified checks into measured passes.

## Tested implementation

- Fork: `andrewmarous/ableton-live-mcp`, branch `configurable-recovery`
- Commit: `558abb654040f40b4f671df764f355350b2cf843`
- Package: `1.8.2.dev15`
- Latest Live version: `12.4.16 Standard`
- Running bridge build: `c834b586da7e3357a765f080347c5714936e9d08300cedccb109892ba5de9f0b`
- Environment: user-authorized disposable Set, eight tracks, two returns, eight baseline scenes
- Plugin automated suite: **279 passed, 1 skipped**
- Integration automated suite: **34 passed**

Automated test results and live observations are separate evidence.

## Fixes

- Preserve native note vectors for MIDI updates. Apply updates before note deletions.
- Use unlooped audio carriers to preserve trims shorter than 0.25 beats.
- Pair source-start changes with the effective audio offset for unlooped clips.
- Write loop boundaries before source markers. Reject combined mode and marker changes.
- Compare numeric property readback with floating-point tolerance.
- Construct native warp markers. Preserve inferred sample times in seconds.
- Permit user-configured recovery-file opt-out. Keep the safe default and authorization requirements.

## Observed live results

Arrangement checks covered MIDI duplication and note edits, audio properties, trim, move, split, warp markers, Undo, and rejection paths.
Audio checks included a 0.1-beat trim and looped, warped source-offset cases.

Saved-file inspection confirmed linear and step automation writes.
The step edit preserved outside-range events and the unrelated volume lane.
Nested Saturator Drive automation appeared in saved XML. One Undo removed that lane.
Stale snapshots, quantized parameters, and invalid intervals received structured rejections.

Authorized playback confirmed transport movement, automation changes, and nonzero output meters.
Panning followed the requested steps and resumed the original outside-range ramp.
Volume returned to its original value after the edit interval.

Session checks confirmed a temporary quantization override without a stored-value change, Gate release, Toggle, Repeat, and legato phase inheritance.
Repeat retriggered at quarter-note intervals while held. Playback continued normally after release.
The final Toggle check used active transport after the prior stop reached its quantization boundary.

Scene launches with an owned clip applied 96 BPM and 7/8.
Disabled overrides preserved 120 BPM and 4/4 during playback.
Simpler Classic loops, One-Shot mode, and Slicing mode produced nonzero output meters.
Earlier rounds covered launch configuration, scene configuration, sample markers, slices, mixer controls, and Undo.

The playback round removed its temporary clips and scene, restored edited controls, and returned control to the Arrangement.
Its final state had eight tracks, eight scenes, stopped transport, and recording disabled.
The source sample hash remained unchanged. The agent saved the Set through Live after cleanup.

## Accepted limitations and unverified checks

The available tools expose state and meters, not an audio stream for listening.
The user accepted this limitation. No listening pass is claimed for clicks, distortion, seamless edits, speaker routing, or musical quality.

The following checks remained unverified when the user completed acceptance:

- Preservation of existing automation curves
- An edit to a Simpler nested inside a rack
- The full musical break/build/return demonstration
- Exact sample-accurate legato timing
- Every remaining combination in the procedural acceptance matrix

Raw local test artifacts remain outside version control because they contain machine-specific paths and transient references.
This record preserves the published acceptance decision and the evidence summary.
