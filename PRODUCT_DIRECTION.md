# Product direction: upstream AbletonMCP and the production wiki

Status: Approved direction. Integration is not implemented.

## Decision

Replace our custom Live bridge with the upstream project linked from
[abletonmcp.com](https://abletonmcp.com):
[wstierhout/ableton-live-mcp](https://github.com/wstierhout/ableton-live-mcp).
Its Python package is `mcp-server-ableton-live`.

This is not [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp),
which publishes the different `ableton-mcp` package.

The product combines upstream Live inspection and editing with our persistent
production wiki. This repository owns the workflow, not another implementation
of the Ableton API.

## Integration boundary

| Component | Responsibility |
| --- | --- |
| Upstream AbletonMCP | Remote Script, Live connection, inspection tools, editing tools, and compatibility fixes |
| Native Pi MCP support | MCP server lifecycle, tool discovery, connection diagnostics, and tool calls |
| This repository | Pinned upstream version, repeatable installation, diagnostic commands, Pi skill, wiki templates, and ingestion tools |
| User wiki | Persistent production knowledge and source material |

There will be no custom bridge, MCP proxy, upstream fork, or replacement Pi MCP
controller. Upstream limitations remain explicit. Fixes belong upstream rather
than in a parallel Live API implementation here.

Pi supports MCP directly. The intended user-level configuration location is
`~/.pi/agent/mcp.json`. Installation must preserve unrelated server entries.
The implementation will pin the upstream package and matching Remote Script
version. Version 1.8.1 was the documented upstream release during evaluation,
not a permanent version requirement.

## Wiki boundary

The existing wiki remains at `~/.pi/agent/ableton-wiki`.
Installation and upgrades must preserve its contents.

A Pi skill will direct production questions to the wiki and Live inspection to
upstream MCP tools. Pi will read wiki files directly. The wiki does not need
another MCP server.

The skill must distinguish production advice from observed facts about the
current Set. Wiki content is reference material, not evidence of current Live
state. The wiki and ingestion tools remain useful without a Live connection.

## Safety boundary

Upstream supports inspection and edits. The integration must not describe it
as read-only. Tool visibility and tool annotations are not permission controls.

Initial verification will use read-only operations. Edits require an explicit
user request. Destructive tests belong in a disposable Set, not a production
Set. Production work requires a saved recovery point before destructive edits.

## Breaking replacement

The integration does not require compatibility with the old bridge or controller.
The replacement workflow will back up the old managed Pi extensions and skill
before removal or replacement. It will preserve the wiki and unrelated Pi
configuration.

The legacy `/ableton` controller and `ableton_ctrl` tool are not required public
interfaces for the replacement. Native Pi MCP diagnostics and upstream diagnostic
commands will replace their connection-management role.

Legacy transport code can remain temporarily during implementation. It must not
become an adapter layer for upstream MCP. Final removal scope will be explicit
in the implementation change.

## Planned implementation

1. Pin an upstream package version and matching Remote Script.
2. Add repeatable installation and diagnostic commands.
3. Configure native Pi MCP without replacing unrelated server entries.
4. Replace the legacy Pi skill with workflow and wiki guidance.
5. Back up and retire the legacy Pi extensions.
6. Preserve wiki contents and ingestion tools.
7. Verify the connection and read-only inspection in a real Live Set.

## Acceptance criteria

- Native Pi MCP connects to the pinned upstream server.
- Upstream diagnostics identify the installed script and running bridge.
- Track names and order match the current Live Set.
- Device inspection includes nested rack chains where upstream supports them.
- Existing wiki files remain unchanged through installation and upgrades.
- The Pi skill supports wiki questions and MCP inspection together.
- Initial verification does not edit the Set or start playback.
- A disposable Set provides a separate test of explicitly requested edits.

Identifying the bass sample on track 12 is a specific evaluation case.
Read-only sample filename access is not yet verified. Ordinary device parameter
inspection does not establish the sample filename. A sample replacement tool
must not serve as an inspection workaround. Offline saved-project inspection is
an alternative to evaluate, not a guaranteed solution.

Upstream compatibility claims do not establish compatibility with this computer.
Real-session verification must cover the installed Live build, currently 12.4.6.

## Current scope

This document records product direction only. It does not install upstream,
change Pi MCP configuration, retire extensions, or alter the wiki.
