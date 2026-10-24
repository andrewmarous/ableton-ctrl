# Upstream AbletonMCP integration

The replacement uses `mcp-server-ableton-live@1.8.1` and its bundled Remote Script.
Pi manages MCP directly. This repository adds installation and workflow guidance, not a Live API adapter.

## Installation

1. Install uv.
2. From this repository, run:

   ```bash
   uv run ableton-upstream install
   ```

   For a relocated User Library, use:

   ```bash
   uv run ableton-upstream install --user-library "/path/to/User Library"
   ```

3. Fully restart Live.
4. In Settings > Tempo & MIDI, select AbletonMCP in an unused Control Surface row.
5. Set that row's Input and Output to None.
6. Run `/reload` in Pi.
7. Run diagnostics:

   ```bash
   uv run ableton-upstream doctor
   pi mcp list
   ```

Use the same `--user-library` argument for installation and diagnostics.
If an existing Remote Script differs, upstream refuses replacement. Review it before using upstream's `install --replace` command.
That upstream command retains a backup.

## Preservation and retirement

Installation backs up existing `mcp.json`, the managed skill, and the two legacy extension files under `~/.pi/agent/backups/ableton-upstream/`.
It merges the AbletonMCP entry and preserves unrelated configuration.
A conflicting AbletonMCP entry requires manual review.
It replaces the managed skill and removes `ableton-ctrl.ts` and `ableton-controller.ts` from the extensions directory.
Existing wiki contents remain untouched. New installations receive wiki templates.
Ingestion tools under `tools/` remain unchanged.

The legacy Python transport, custom MCP server, extension sources, installers, smoke scripts, and their tests are removed.
The obsolete Live implementation plans and bridge resources are also removed.
Only upstream MCP provides Live access. The legacy command entry points are removed.

To roll back Pi resources, restore the backup files and remove the newly added AbletonMCP entry if it did not exist before.
Preserve unrelated configuration changes during rollback. Disable the AbletonMCP Control Surface manually if necessary.

## Read-only acceptance

Use Live 12.4.6 on the target computer. Do not start playback or edit the Set.

- Confirm that upstream doctor reports matching installed and running scripts.
- Confirm that native Pi MCP connects.
- Request tempo and track names. Compare track order with Live.
- Inspect a rack with nested chains where upstream supports inspection.
- Answer a production question with wiki references and observed Live facts clearly separated.
- Confirm that existing wiki files remain unchanged after installation and another installation.

Edits require a separate explicit request. Use a disposable Set for edit tests.
Before destructive production edits, save a recovery point.

## Verification in this workspace

Before legacy retirement, all 236 repository tests passed.
The legacy tests are now removed with their implementation. The replacement installer tests remain.
The installation attempt stopped because the default Ableton User Library does not exist here.
Upstream doctor reported no installed script and connection refusal on port 9877.
Pi reported no configured MCP servers. Real-session acceptance remains pending on the target computer.
