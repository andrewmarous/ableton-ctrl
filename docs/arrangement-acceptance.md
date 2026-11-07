# Arrangement acceptance test

Status: candidate for disposable-Set testing. Issue #14 is not complete.

CAUTION: Use a new disposable Set or a separate copy of a composition.
The reconstruction tools temporarily replace clips and can fail after partial changes.
Production edits remain outside this test.

## 1. Install the candidate

The fork checkout is next to `ableton-ctrl` at `../ableton-live-mcp`.
The candidate package version is `1.8.2.dev15`.
These commands do not edit the open Set. Installation replaces the Remote Script after a backup.

1. Save any open production Set.
2. Close Live.
3. From the fork checkout, run:

```sh
uv sync --extra dev
uv run ableton-live-mcp install --replace
```

For a relocated User Library, add `--user-library "/absolute/User Library"`.
The installer prints the script backup path. Keep that backup until acceptance finishes.

4. Configure the existing AbletonMCP server to run this fork, not upstream `1.8.1`.

For a local checkout, the configuration entry is:

```json
{
  "command": "uv",
  "args": ["--directory", "/absolute/path/to/ableton-live-mcp", "run", "ableton-live-mcp"]
}
```

Preserve unrelated MCP servers and other fields in the configuration.
The `ableton-ctrl` installer also supports the immutable fork pin through `upstream.command`.
A conflicting existing server entry requires manual review before replacement.

5. Start the latest stable Live version, at least 12.4.
6. Enable AbletonMCP in an unused Control Surface row, with Input and Output set to None.
7. Restart the MCP connection and reload Pi tools.
8. From the fork checkout, run:

```sh
uv run ableton-live-mcp doctor --json
```

The result must show `ok: true` and matching installed and running builds.
A matching version alone is insufficient. Restart Live after every Remote Script change.

9. Discover these tools through MCP:

- `inspect_arrangement`
- `preview_arrangement_edit`
- `execute_arrangement_edit`
- `save_and_inspect_arrangement_automation`

## 2. Create a reproducible fixture

The generator makes deterministic synthetic audio, not real vocal or guitar recordings.
It never connects to Live.

```sh
uv run python scripts/create_arrangement_fixture.py --output /tmp/ableton-arrangement-acceptance
```

The output directory must be new or empty.
The generated `fixture.json` contains source hashes, marker settings, notes, and construction steps.

1. Open a new disposable Set.
2. Save it and a separate recovery copy.
3. Ask the agent to construct the fixture from `fixture.json`.
4. Authorize edits only in that disposable Set.

The agent creates temporary Session source clips during fixture construction.
The user does not prepare Session slots. The agent removes its sources after Arrangement placement.
The resulting fixture has four audio tracks and one MIDI track.
The MIDI track needs a stock instrument so it has audio output for reconstruction tests.
Each audio track contains 32-beat clips at beats 0, 32, 64, 96, and 128.
The source loops use a nonzero offset of four beats.

5. Inspect actual timeline bounds before continuing.
6. Save the fixture and keep an unchanged recovery copy.
7. Record the exact Live version, edition, OS, package version, and bridge build ID.

A copy of an existing composition can supplement this fixture with real musical material.

## 3. Exercise direct editing

For every mutation, the agent must inspect, preview, obtain authorization, execute, and inspect the returned state.
Execution requires an existing saved recovery `.als` path.
Reconstruction additionally requires `reconstruction_authorized=true`.
If audio execution returns `prepared`, execute the same plan again after the next Live update.
Alternatively, use `cancel=true` to remove its owned temporary resources.
Keep playback stopped during edits.

| Check | Required result |
| --- | --- |
| Duplicate an audio Arrangement clip into an empty range | Native copy retains source, markers, loop state, gain, pitch, and warp grid. |
| Duplicate a MIDI Arrangement clip into an empty range | Native copy retains notes, probabilities, deviations, release velocities, and expression. |
| Add one MIDI note and update another by ID | Unrelated notes and expressive fields remain unchanged. |
| Delete a selected MIDI note by ID | Only that note disappears. |
| Use `replace_notes` on a disposable copy | Replacement is explicit and affects all previous notes only in that copy. |
| Edit audio gain and pitch | Observed values match, and the original source file hash stays unchanged. |
| Change a source marker | Inspection distinguishes source markers from timeline edges. |
| Change warping separately | A later inspection resolves any `pending_properties`. |
| Add, move, and remove a valid warp marker | Only the requested warp-grid change occurs. |
| Trim either timeline edge | Source offsets, loop playback, expression, and remaining content stay correct. |
| Move a clip, including a self-overlapping destination | Destination bounds are correct, with no holding copies after success. |
| Split audio and MIDI clips inside and across loops | Both pieces meet at the split beat and play continuously. |
| Split exactly at a boundary | No-op, without zero-length clips. |
| Try an overlapping destination or cross-track copy | Structured rejection without mutation. |
| Modify a target after preview | The stale plan is rejected. |
| Delete a target, then use its old reference | The stale reference is rejected. |
| Cancel prepared audio work | Owned temporary clips disappear; original Arrangement content remains unchanged. |

Repeat trim, move, and split on looped, unlooped, warped, and unwarped cases.
For unwarped audio, confirm the reported native source-marker units against Live.
One Undo after final execution must restore Arrangement content.
Audio preparation has a separate undo step. Undo can restore temporary Session clips as part of history.
Confirm that source assets remain available for Undo and Redo.

## 4. Exercise saved automation inspection and writes

1. Create a recognizable volume lane and a device-parameter lane in the disposable Set.
2. Include existing curves and breakpoints before and after the intended edit range.
3. Confirm the exact saved `.als` path belongs to the open Set.
4. Ask the agent to use `save_and_inspect_arrangement_automation`.
5. If it returns `needs_manual_save`, save in Live.
6. Confirm the manual save, then retry with `manual_save_confirmed=true`.
7. Retain the baseline snapshot result and file hash.

The returned data is a saved-file snapshot, not unsaved live state.
Raw XML preserves curves even though the initial writer supports only linear and step interpolation.
Saved XML IDs are not live parameter handles.

8. Use `inspect_arrangement` to select an unambiguous continuous mixer or device parameter.
9. Preview an `automation` edit with these fields:

```json
{
  "operation": "automation",
  "reference": "CLIP_REFERENCE_FROM_INSPECTION",
  "parameter_reference": "PARAMETER_REFERENCE_FROM_INSPECTION",
  "start": 64,
  "end": 128,
  "points": [
    {"time": 64, "value": 0.2},
    {"time": 96, "value": 0.35},
    {"time": 127, "value": 0.9},
    {"time": 128, "value": 0.9}
  ],
  "interpolation": "linear",
  "snapshot_path": "/absolute/path/to/fixture.als",
  "snapshot_sha256": "DIGEST_FROM_SAVED_INSPECTION",
  "snapshot_confirmed_current": true
}
```

The example values apply only to parameters whose native range contains 0.2 through 0.9.
The replacement interval is `[start, end)`. The lane resumes its previous state at the end boundary.
Step interpolation holds each point's value until the next point. The final point closes the range.

10. Authorize the preview and reconstruction contract.
11. Execute the plan, including a second request after audio preparation when required.
12. Save and inspect again.
13. Compare the target lane inside the interval.
14. Compare original events, curves, and audible values outside the interval.
15. Confirm that other parameter lanes and original clips remain unchanged.
16. Confirm that no tracks were added by the edit.
17. Repeat with a step edit and a nested-device parameter.
18. Confirm that invalid ranges, stale snapshots, and unsupported parameters are rejected.

Do not save or edit while an audio plan is prepared. Cancel and preview again after any intervening change.
Reconfirm snapshot freshness after every edit. A digest cannot detect unsaved Live changes.
An overridden parameter requires explicit re-enablement before preview; the writer does not silently change that state.

## 5. Demonstrate the requested composition

In 4/4, bar 17 starts at beat 64, bar 25 at beat 96, and bar 33 at beat 128.
Use the existing fixture Arrangement clips rather than creating user-prepared Session clips.

1. Remove the kick and bass clips in `[64, 128)` through reference-based `delete` previews.
2. Reshape the existing vocal and guitar clips in `[64, 96)` with inward trims and moves into empty ranges.
3. Split and reshape their existing build clips in `[96, 128)`.
4. Trim the final build pieces to end at beat 127.
5. Keep the existing return clips at beat 128.
6. Write a supported Arrangement automation build through the save-and-inspect workflow.
7. Inspect all resulting clips and saved lanes.
8. Confirm the one-beat gap before the return.
9. Start playback only after explicit listening authorization.
10. Listen for the break, build, gap, and kick/bass return.

Synthetic tones demonstrate timing and transitions, not production quality.
A disposable copy of a real composition provides the musical acceptance check.

## 6. Record the result

Record pass or fail for all five capabilities, Undo, source hashes, outside-range automation, and the composition demonstration.
A partial failure, cleanup warning, or unexplained state change blocks completion.
On partial failure, stop edits and retain reported native recovery copies.
Use Undo or reopen the recovery Set after inspection.
Keep issue #14 open until all required checks pass.

## 7. Additional native creator controls

The same candidate includes four additional feature groups awaiting Live acceptance:

- [ ] Session launch mode, quantization, legato, velocity sensitivity, and explicit triggering
- [ ] Scene tempo and time-signature overrides
- [ ] Simpler sample metadata, regions, loop controls, playback modes, and slices
- [ ] Master cue volume, split-stereo panning, and return mixer controls

Use the [creator controls acceptance guide](creator-controls-acceptance.md) for procedures and expected results.
Record these checks separately from issue #14's Arrangement requirements.
