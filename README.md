# ableton-ctrl

Pi-compatible, read-only inspection of Ableton Live 12 Intro 12.4.2 Sets.

`ableton-ctrl` lets Pi inspect the active Live Set through a local bridge without
using MCP. It exposes bounded snapshots, object lookup, relationship pagination,
search, schema metadata, revisioned changes, and bundled learning resources. The
existing MCP server remains available as an optional compatibility interface.

> Ableton's Python API is unsupported and undocumented. Runtime availability can
> change across Live builds. This project supports only macOS with Ableton Live
> 12 Intro 12.4.2 and requires a real-session smoke test for each release.

## Prerequisites

- macOS
- Ableton Live 12 Intro 12.4.2
- Python 3.11 or newer
- `uv`
- Pi, for the primary agent integration path

## Primary setup: Pi + Ableton

Install Python dependencies and the Ableton Remote Script:

```bash
uv sync
uv run python scripts/install_remote_script.py
```

In Live, open Preferences > Link, Tempo & MIDI and select `AbletonCtrl` as a
Control Surface. Then start the local bridge:

```bash
uv run ableton-ctrl-bridge
```

Install the global Pi extension and skill:

```bash
uv run ableton-ctrl-install-pi
```

The Pi installer writes global artifacts under:

```text
~/.pi/agent/extensions/ableton-ctrl.ts
~/.pi/agent/skills/ableton-ctrl/SKILL.md
```

It is conservative: it creates these files only when absent and refuses to
overwrite existing files. If reinstalling, manually delete the old files first,
then rerun `uv run ableton-ctrl-install-pi`.

After installation, run `/reload` in Pi or restart Pi. Pi should then have one
read-only tool named `ableton_ctrl` and a matching skill that explains when and
how to use it.

## Using the Pi tool

Ask Pi to inspect the active Ableton Live Set. The installed skill should guide
Pi to call `ableton_ctrl` for read-only inspection tasks such as:

- taking a bounded `snapshot`
- fetching an `object` by ID
- paging `children` relationships such as tracks, scenes, clips, devices, and parameters
- running `search` by name, type, or path
- inspecting `schema` metadata
- reading `changes` since the last call with persisted Set-name cursors
- loading `resource` metadata for glossary, interpretation guidance, and Live Intro limitations

The tool is read-only. It must not be used for transport control, clip launching,
recording, editing, parameter changes, file writes into the Set, or other Live
mutation.

## CLI interface

The Pi extension shells out to the installed `ableton-ctrl` console script. The
CLI is also useful for debugging and accepts exactly one JSON command-line
argument. It returns a structured JSON envelope for both success and errors.

Examples:

```bash
uv run ableton-ctrl '{"action":"snapshot","depth":1,"page_size":20}'
uv run ableton-ctrl '{"action":"search","name":"drums","limit":10}'
uv run ableton-ctrl '{"action":"resource","name":"glossary"}'
uv run ableton-ctrl '{"action":"changes"}'
```

Supported actions are `snapshot`, `object`, `children`, `search`, `schema`,
`changes`, and `resource`. For explicit change queries, provide `session_id` and
`after_revision` together. When both are omitted, `changes` uses a persisted
cursor keyed by the current Ableton Live Set name; if the Set name cannot be
determined, the command fails with a structured error instead of using an
ambiguous fallback cursor.

Configuration and the bridge shared secret are stored at:

```text
~/Library/Application Support/ableton-ctrl/config.json
```

Config files are mode `0600`; commands and logs do not print the secret. The
adapter, loopback bridge, CLI, Pi extension, and optional MCP server communicate
only on the local machine. The bridge refuses non-loopback binding.

## Optional MCP compatibility

MCP-compatible clients can still use the existing MCP server. Start the bridge,
then launch the MCP server from this checkout:

```bash
uv run ableton-ctrl-bridge
uv run ableton-ctrl-mcp
```

Configure the MCP client to run `uv run ableton-ctrl-mcp` from this repository.
Pi does not use this path; Pi should use the installed `ableton_ctrl` tool.

## Development

Install dependencies:

```bash
uv sync
```

Run the test suite:

```bash
uv run pytest
```

Run linting and type checks when changing code:

```bash
uv run ruff check .
uv run mypy src tests
```

Build a package locally:

```bash
uv build
```

## Troubleshooting

The CLI, Pi tool, and MCP surface use stable structured error codes:

- `bridge_unavailable`: start or restart `uv run ableton-ctrl-bridge`.
- `live_offline`: start Live, select the Remote Script, and wait for reconnection.
- `stale_state`: take a fresh snapshot or wait for a fresh adapter update.
- `session_changed`: discard old object IDs and cursors; take a new snapshot.
- `unsupported_property`: inspect `schema` or use the bundled resources.
- `read_failed`: inspect the object's outcome reason and retry after state settles.
- `partial_result`: use pagination, narrower searches, or wait for discovery to finish.
- `stale_cursor`: restart change tracking from a fresh snapshot/revision.
- `invalid_invocation`, `invalid_json`, `unknown_action`, `validation_failed`: fix the
  CLI/Pi action fields and retry.

If a snapshot includes adapter runtime recovery for `partial_result`, reduce the
observed Live graph or adapter capacity pressure, then reload or restart the
`ableton-ctrl` Ableton Remote Script. A restart is the deliberate reset boundary;
the adapter will not repeatedly retry the same oversized graph.

If Live does not list the script, verify that this directory exists, restart
Live, and reselect the Control Surface:

```text
~/Music/Ableton/User Library/Remote Scripts/AbletonCtrl
```

The Remote Script installer will never overwrite that directory unless its
`.ableton-ctrl-managed` marker is present.

## Removal

First deselect `AbletonCtrl` in Live Preferences and quit Live. Then remove the
managed Remote Script, local configuration, and optional global Pi artifacts:

```bash
rm -rf "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonCtrl"
rm -rf "$HOME/Library/Application Support/ableton-ctrl"
rm -f "$HOME/.pi/agent/extensions/ableton-ctrl.ts"
rm -rf "$HOME/.pi/agent/skills/ableton-ctrl"
```

## Release gate

Run the automated checks, then complete [the manual Live smoke test](docs/live-smoke-test.md)
on the target installation. Automated fixture replay is not evidence that the
real Live smoke gate passed.
