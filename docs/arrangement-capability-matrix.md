# Arrangement capability matrix

Status: acceptance candidate. No Live acceptance result is claimed.

The implementation targets Live 12.4 or later. Acceptance uses the latest stable release available to the user.
The maintainer fork is https://github.com/andrewmarous/ableton-live-mcp, branch `issue-14-arrangement`.
The starting upstream source is tag `v1.8.1`. The candidate version is `1.8.2.dev15`.
Older Live versions receive a structured `unsupported_version` error for the new commands.
No cross-platform or edition-specific acceptance result exists yet.

## Capability matrix

| Requirement | Implementation | Evidence and limits |
| --- | --- | --- |
| Duplicate existing audio and MIDI clips | Native `Track.duplicate_clip_to_arrangement`, with a scoped source reference and absolute destination beats. | The [Track API](https://docs.cycling74.com/apiref/lom/track/) explicitly accepts Arrangement sources. Same-track only. All destination overlaps are rejected. Track automation stays at absolute positions and is not copied with clips. |
| Read and edit MIDI notes | Extended note inspection includes IDs and expressive properties. ID-based add, update, and delete preserve other notes. `replace_notes` explicitly replaces all notes. | The [Clip API](https://docs.cycling74.com/apiref/lom/clip/) covers Arrangement clips. Same-pitch overlaps are rejected before mutation. Note times are source-relative beats, not Arrangement beats. No reduced-schema reconstruction fallback exists. |
| Read and edit audio properties | Source and loop markers, gain, pitch, warp mode, and warping. Native warp-marker add, move, and remove have range checks. | The [Clip API](https://docs.cycling74.com/apiref/lom/clip/) documents these properties and marker operations. Sample times are seconds. Source marker units depend on warping. Terminal warp-reference edits are rejected. Source audio bytes are not rewritten. Deferred warping changes require a later inspection. |
| Trim, move, and split | Native recovery copies in a holding area. Temporary Session clips truncate working copies. Original clips are removed only after working copies exist. | `start_time` and `end_time` are read-only in the [Clip API](https://docs.cycling74.com/apiref/lom/clip/). [External experiments](https://github.com/adamjmurray/producer-pal/blob/main/dev/live-api/arrangement-operations/core-techniques.md) describe native overlap truncation. Only inward, positive-length trims are supported. Boundary splits are no-ops. Timeline automation stays at absolute positions. Loop and source-offset preservation require Live acceptance. |
| Read and write Arrangement automation | Saved-file inspection retains raw events, curves, target IDs, and XML paths. A Session carrier writes linear or step automation over an explicit range on the existing track. Native copies restore displaced clips. | The [Python API reference](https://midiremotescripts.structure-void.com/reference/live12/Live.Clip.runtime) states that Arrangement `automation_envelope` returns `None`. [External experiments](https://github.com/adamjmurray/producer-pal/blob/main/dev/live-api/arrangement-automation.md) document carrier writes. Enabled continuous mixer and device parameters on regular tracks with audio output are the initial supported subset. Returns, master lanes, quantized parameters, curved writes, and lane deletion are rejected or unavailable. Outside-range preservation requires Live acceptance. |

The official [LOM index](https://docs.cycling74.com/apiref/lom/) identifies its documented Live version.
The unofficial Python reference does not establish an exact supported patch version.
External experiments identify Live 12.4.6 and 12.4.15b1. They are not this fork's acceptance results.

## Targeting and validation

`inspect_arrangement` returns scoped clip, track, and parameter references.
Surviving objects retain references across unrelated list changes. Deleted objects and previous script instances produce stale-reference errors.
Device paths and indices are zero-based. Parameter references identify live objects, not saved XML IDs.
Saved XML paths distinguish source parameter candidates. The agent must not infer a live parameter identity from a similar name.

`preview_arrangement_edit` validates the target, clip type, Live version, bounds, and operation-specific ranges.
It reports affected ranges and the reconstruction requirement without changing the Set.
`execute_arrangement_edit` requires explicit authorization and an existing saved recovery `.als` file.
A changed target track invalidates the plan. Completed plans cannot be reused.
Clip edits keep automation at absolute timeline positions. Moving automation requires a separate, explicitly previewed automation edit.

## Save-then-inspect

The user approved the following workflow:

1. Confirm the exact saved path belongs to the open Set.
2. Attempt MCP saving through `song.save_project` when available.
3. Verify a stable file update before snapshot inspection.
4. If verification fails, request a manual save.
5. After user confirmation, read the saved snapshot without another save attempt.

An unchanged file does not prove that saving failed. The Set can already be saved.
A changed file does not prove that it belongs to the open Set. That association requires user confirmation.
Snapshots report the path, digest, size, modification time, and verification method.
Snapshot digests detect disk changes, not unsaved changes in Live.
Before automation writes, the user or agent must confirm that no edits occurred after the save.
The saved file digest is checked again before execution.

Saved inspection excludes Session envelopes and does not move the playhead or start playback.
It preserves raw event attributes, including curve controls and Live sentinel times.
It does not reinterpret the saved events as an exact live-state representation.

## Reconstruction and recovery

The [reconstruction contract](arrangement-reconstruction-contract.md) defines preservation and partial-failure behavior.
Reconstruction requires separate authorization. It never creates tracks.
The agent creates its own temporary Session clips and, when necessary, a temporary scene.
Occupied Session slots remain unchanged.

Audio carriers require a separate preparation request because Live defers warping changes.
A `prepared` response retains the plan. The agent executes it again after the next Live update or cancels it.
Preparation has a separate undo step. The final Arrangement edit requests one further undo group.
Cleanup retains changed temporary slots or occupied temporary scenes and reports warnings.
Generated silent WAV files remain available for Undo. User source audio files remain untouched.

After partial failure, native holding copies remain available and appear in the response.
The tool reports completed changes and the saved recovery point. It does not claim automatic rollback.
No production Set received edit tests during development.

## Automated verification and remaining acceptance

Unit tests cover scoped references, stale plans, invalid ranges, authorization, overlap rejection, and note preservation.
State-machine tests model loops, source offsets, warped audio, boundary splits, native-copy recovery, and scratch cleanup.
Other tests cover deferred audio preparation, cancellation, replaced temporary slots, snapshot freshness, and package/script matching.
The installer bundles the engine into one Remote Script file and checks a per-build identifier.

These tests use doubles rather than a running Live instance.
They do not establish source-offset playback, actual lane preservation, or Live undo behavior.
The [acceptance guide](arrangement-acceptance.md) covers those checks and the bars 17–33 composition.
Issue #14 remains open until the user completes acceptance.
