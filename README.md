# ableton-ctrl

Production workflow for upstream AbletonMCP, native Pi MCP, and a persistent production wiki.

## Install

Install [uv](https://docs.astral.sh/uv/), then run from this repository:

```bash
uv run ableton-upstream install
```

For a relocated Ableton User Library:

```bash
uv run ableton-upstream install --user-library "/path/to/User Library"
```

Follow the [integration guide](docs/upstream-integration.md) to activate the Remote Script and verify the connection.
Installation preserves existing wiki contents and unrelated Pi configuration.
It backs up and removes the two legacy Pi extensions.

## Responsibilities

- Upstream `wstierhout/ableton-live-mcp` owns the Remote Script and Live inspection and editing tools.
- Native Pi MCP owns connections, tool discovery, and tool calls.
- This repository owns the version pin, installation, diagnostics, workflow skill, wiki templates, and ingestion tools.
- The wiki at `~/.pi/agent/ableton-wiki` stores persistent production knowledge.

Upstream supports edits. Edits require an explicit user request.
Initial verification uses inspection only and does not start playback.

## Diagnostics

```bash
uv run ableton-upstream doctor
pi mcp list
```

## Ingestion

The independent tools remain available:

- [Video ingestion](tools/ingest/README.md)
- [Scraping](tools/scrape/README.md)
- [Transcription](tools/transcribe/README.md)

## Development

```bash
uv run pytest
```

The custom bridge, MCP server, controller, installers, and their tests are retired.
The `ableton-ctrl`, `ableton-ctrl-bridge`, `ableton-ctrl-mcp`, and `ableton-ctrl-install-pi` commands are removed.
Use `ableton-upstream` instead.
Real-session verification requires Live on the target computer. Installer failure-handling improvements remain deferred.
