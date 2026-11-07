---
name: ableton-ctrl
description: Answer music-production questions from the wiki, inspect and edit Ableton Live, capture its audio output, and inspect recordings with FFmpeg.
---

# Production workflow

1. For production knowledge, read `~/.pi/agent/ableton-wiki/AGENTS.md` and `wiki/index.md` first.
2. Read the relevant wiki files directly. Cite their paths for production advice.
3. For current Set facts, discover the native Pi MCP tools from `AbletonMCP` and inspect Live.
4. Separate observed Live facts from wiki advice and inference in the answer.

The wiki remains useful without Live. If Live is unavailable, report that limitation and continue with wiki material.

## Live safety

Use inspection tools for initial verification. Do not start playback or modify the Set during verification.
Edits require an explicit user request. Before destructive production edits, require a saved recovery point.
Use a disposable Set for destructive tests. Tool annotations and visibility are not permission controls.
Read parameter ranges before edits. Upstream uses zero-based track indices and beat-based times.
Report unsupported inspection as a limitation. Do not use mutation tools as inspection workarounds.

## Arrangement edits

1. Use `inspect_arrangement` to obtain scoped clip and parameter references.
2. Use `preview_arrangement_edit` before each edit.
3. Present the affected ranges and the automation policy to the user.
4. Require explicit edit authorization and an existing saved recovery `.als` file.
5. For reconstruction, obtain separate approval of temporary clip replacement and recovery behavior.
6. Execute the approved plan with `execute_arrangement_edit`.
7. If the result is `prepared`, execute the same plan after the next Live update or cancel it.
8. Inspect the observed state and resolve `pending_properties` through a later inspection.
9. If partial changes or cleanup warnings occur, stop and report recovery steps.

These commands require Live 12.4 or later. Keep edits on the existing tracks.
The agent prepares temporary Session clips; the user does not prepare Session slots.
Completed plans are single-use. Changed targets require a new preview.
Execute Arrangement plans outside `batch_commands`; each plan manages its own undo groups.
Clip edits keep automation at absolute timeline positions. Moving a clip does not move its lane automation.
Cross-track copies and overlapping destinations are unsupported. Report these limits before editing.

## Saved Arrangement automation

1. Confirm the exact `.als` path belongs to the open Set.
2. Use `save_and_inspect_arrangement_automation` with that path.
3. If it returns `needs_manual_save`, ask the user to save in Live.
4. Retry with `manual_save_confirmed=true` only after the user confirms the save.
5. Report the snapshot path and digest with saved-file observations.
6. Before an automation write, confirm that no edits occurred after the snapshot.
7. Select a live parameter reference from inspection; never infer it from a similar XML name.
8. Preview the explicit replacement range and interpolation before execution.
9. After the edit, save and inspect again to compare automation outside the range.

Saved snapshots exclude unsaved changes. A matching file digest does not prove live-state freshness.
The initial writer supports linear and step writes on enabled continuous track mixer and device parameters.
Curved writes, returns, master automation, quantized parameters, and lane deletion are unsupported.
Audio preparation has a separate undo step. The final Arrangement edit requests one further undo group.

## Audio capture and inspection

Use these local commands through the terminal tool. They use this plugin's Python environment, independent of shell PATH.

```sh
__ABLETON_AUDIO_COMMAND__ doctor
__ABLETON_AUDIO_COMMAND__ devices
__ABLETON_AUDIO_COMMAND__ capture --seconds 8
__ABLETON_AUDIO_COMMAND__ inspect /absolute/path/to/recording.wav
```

Capture records Live's output through a configured loopback input, such as BlackHole.
The input comes from `--device`, then `ABLETON_AUDIO_DEVICE`, then the saved plugin configuration.
If no input is configured, list devices and ask the user which loopback receives Live's output.
Save that choice with `ableton setup --audio-device 'BlackHole 2ch'`, or pass `--device` on each capture.
Capture requires macOS, FFmpeg, and Live output routing to the loopback device.
File inspection works without Live and without a configured input.

Use existing AbletonMCP tools to select a passage, control playback, and solo tracks or groups for exploration.
Capture hears everything routed to that output, including active returns and master processing.
For ongoing playback, capture directly. To include a passage's start, launch capture as a background terminal job before playback.
Allow extra time for device initialization and effect tails. The opening message is not a readiness signal.
Verify that the recorded passage is the intended one; capture is not synchronized to Live's transport.

After capture completes successfully, inspect the returned `path`.
Read the measurements and open both PNG paths in `images` with the image-reading tool.
Use the saved measurement log if a value needs investigation.
Report measured facts separately from musical interpretation. Possible clipping is a peak-level indicator, not proof of distortion.
Images and measurements are observations, not direct audio hearing. Captures remain available for playback.
Report missing routing or device access as a capture limitation; continue inspection of existing files.

## Connection diagnostics

Run `ableton-upstream doctor` for installed-script and running-bridge diagnostics.
Run `pi mcp list` for native Pi connection diagnostics. Use `/mcp` inside Pi.
After configuration changes, use `/reload`.
Upstream owns the Remote Script and Live API compatibility. Report upstream limitations rather than creating another bridge.
