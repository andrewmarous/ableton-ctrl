# Integration reference

For normal installation, use [Getting started](getting-started.md).
This page covers component responsibilities, the advanced installer, and Live acceptance tests.

## Responsibilities

- The maintained `andrewmarous/ableton-live-mcp` fork owns the Remote Script and Live tools.
- `src/ableton_ctrl/upstream.py` pins its immutable commit through `uvx --from`.
- The current candidate version is `1.8.2.dev15`. Arrangement tools require Live 12.4 or later.
- Pi manages the MCP connection, tool discovery, and tool calls.
- This package owns setup, diagnostics, workflow guidance, knowledge ingestion, and publication.

Only upstream MCP provides Live access. This package does not add another Live transport or API adapter.
Edits require an explicit user request. Initial verification uses inspection only.

## Arrangement acceptance candidate

Issue #14 has an implementation candidate, not a completed Live acceptance result.
Use the [acceptance guide](arrangement-acceptance.md) in a disposable Set.
The [capability matrix](arrangement-capability-matrix.md) lists supported operations and evidence.
The [reconstruction contract](arrangement-reconstruction-contract.md) defines temporary resources and recovery.

The new tools keep edits on existing tracks. They require previews, explicit authorization, and a saved recovery Set.
Clip edits keep automation at absolute timeline positions. Automation does not automatically move with clips.
Automation inspection uses a verified saved `.als` snapshot, with manual-save fallback.
The initial automation writer supports continuous track mixer and device parameters with linear or step interpolation.
Cross-track copies, destination overlap replacement, curved writes, master/return lanes, and quantized parameters remain unsupported.

The installer and MCP configuration use the same immutable fork source.
Diagnostics compare the installed bundle and the running build identifier, not only the package version.
A conflicting older MCP entry or Remote Script requires explicit review before replacement.
The acceptance guide explains migration without silently replacing either component.

## Native creator controls acceptance

The candidate adds Session launch settings, scene tempo and meter overrides, Simpler sample controls, and additional mixer controls.
Use the [creator controls acceptance guide](creator-controls-acceptance.md) in the same disposable test environment.
These ten tools expose native controls rather than high-level composition requests.
They include inspection, validated writes, observed values, and structured unsupported responses.
Mode changes require a separate inspection before mode-dependent writes.
Settings tools manage their own undo groups and run outside `batch_commands`.
Actual Live acceptance remains pending.

## Advanced Live-only installation

The normal `ableton setup` command also creates application configuration and can build whisper.cpp.
For only the upstream integration and its Pi resources, use:

```sh
ableton-upstream install
```

For a relocated User Library:

```sh
ableton-upstream install --user-library "/path/to/User Library"
```

This is an advanced alternative, not an extra step after guided setup.
It does not save a custom knowledge directory or build a transcriber.
From a source checkout, prefix the command with `uv run`.

After installation, complete the [manual Live connection](getting-started.md#4-connect-live).
For upstream diagnostics only, run:

```sh
ableton-upstream doctor
```

Use the same `--user-library` argument for installation and diagnostics.
The normal `ableton doctor` command also reports application prerequisites and library findings.

## Managed files and conflicts

Installation merges the AbletonMCP entry in `~/.pi/agent/mcp.json` and preserves unrelated entries.
A conflicting AbletonMCP entry requires manual review.
Installation replaces the managed skill at `~/.pi/agent/skills/ableton-ctrl/SKILL.md`.
It removes the retired `ableton-ctrl.ts` and `ableton-controller.ts` extensions after snapshot creation.
Existing wiki contents remain untouched.

The installer delegates Remote Script installation to the pinned upstream package without forced replacement.
If the installed script differs, upstream refuses replacement.
Review that conflict before any manual upstream replacement command.
Do not enable two bridges on the same port.

Setup and the advanced installer snapshot managed files before changes.
For backup locations, automatic recovery, and rollback limits, see [Recovery](recovery.md).

## Live acceptance test

Use a known Set on the target computer. Keep playback stopped throughout this test.

1. Run `ableton doctor` with the installed User Library path if necessary.
2. Verify that the upstream diagnostic reports a matching installed and running script.
3. Run `pi mcp list`.
4. Verify that AbletonMCP connects.
5. Ask Pi for the tempo and track names with an inspection-only request.
6. Compare the track order and tempo with Live.
7. Inspect a rack with nested chains where upstream supports it.
8. Ask a production question with published wiki references.
9. Verify that the answer separates source advice from observed Live facts.
10. Verify that existing wiki files remain unchanged after repeated setup.

Edits need a separate explicit request. Use a disposable Set for edit tests.
Before destructive production edits, save a recovery point.

## Retired interfaces

The old custom bridge, MCP server, controller, and Pi extension installers are retired.
The commands `ableton-ctrl`, `ableton-ctrl-bridge`, `ableton-ctrl-mcp`, and `ableton-ctrl-install-pi` are removed.
Use the `ableton` CLI for the current user workflow.
