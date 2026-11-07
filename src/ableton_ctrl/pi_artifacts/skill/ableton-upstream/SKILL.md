---
name: ableton-ctrl
description: Answer music-production questions from the production wiki, inspect the current Ableton Live Set, and perform explicitly requested Live edits.
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

## Connection diagnostics

Run `ableton-upstream doctor` for installed-script and running-bridge diagnostics.
Run `pi mcp list` for native Pi connection diagnostics. Use `/mcp` inside Pi.
After configuration changes, use `/reload`.
Upstream owns the Remote Script and Live API compatibility. Report upstream limitations rather than creating another bridge.
