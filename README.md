# ableton-ctrl

Read-only, local inspection of an Ableton Live 12 Intro 12.4.2 set through MCP.

> Ableton's Python API is unsupported and undocumented. Runtime availability can change
> across Live builds. This project supports only the exact target above and requires a
> real-session smoke test for each release.

## Prerequisites

- macOS
- Ableton Live 12 Intro 12.4.2
- Python 3.11 or newer
- `uv`

## Install and start

```bash
uv sync --all-extras
uv run python scripts/install_remote_script.py
```

In Live, open Preferences > Link, Tempo & MIDI and select `AbletonCtrl` as a Control
Surface. Start the bridge before the MCP server:

```bash
uv run ableton-ctrl-bridge
uv run ableton-ctrl-mcp
```

Configure an MCP client to launch `uv run ableton-ctrl-mcp` from this checkout.

The adapter, loopback bridge, and MCP server exchange observations only on the local
machine. The bridge refuses non-loopback binding. Configuration and its shared secret
are stored at:

```text
~/Library/Application Support/ableton-ctrl/config.json
```

The installer also places a private copy in the managed Remote Script directory. Config
files are mode `0600`; commands and logs do not print the secret.

## Troubleshooting

The MCP surface reports eight stable error codes:

- `live_offline`: start Live, select the Remote Script, and wait for reconnection.
- `stale_state`: wait for a fresh adapter update and retry.
- `session_changed`: discard old object IDs and cursors; take a new snapshot.
- `unsupported_property`: inspect `get_schema` and the coverage report.
- `read_failed`: inspect the object's outcome reason and retry after state settles.
- `partial_result`: use pagination or wait for discovery to finish.
- `stale_cursor`: restart change tracking from a fresh snapshot/revision.
- `partial_result` with adapter action `reduce_observation_size_or_capacity`: reduce
  the observed Live graph or adapter capacity pressure, then reload or restart the
  `ableton-ctrl` Ableton Remote Script. A restart is the deliberate reset boundary;
  the adapter will not repeatedly retry the same oversized graph.
- `bridge_unavailable`: start or restart `uv run ableton-ctrl-bridge`.

If Live does not list the script, verify that
`~/Music/Ableton/User Library/Remote Scripts/AbletonCtrl` exists, restart Live, and
reselect it. The installer will never overwrite that directory unless its
`.ableton-ctrl-managed` marker is present.

## Removal

First deselect `AbletonCtrl` in Live Preferences and quit Live. Then remove only the
managed script and local configuration:

```bash
rm -rf "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonCtrl"
rm -rf "$HOME/Library/Application Support/ableton-ctrl"
```

## Release gate

Run the automated checks, then complete [the manual Live smoke test](docs/live-smoke-test.md)
on the target installation. Automated fixture replay is not evidence that the real Live
smoke gate passed.
