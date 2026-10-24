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

## Connection diagnostics

Run `ableton-upstream doctor` for installed-script and running-bridge diagnostics.
Run `pi mcp list` for native Pi connection diagnostics. Use `/mcp` inside Pi.
After configuration changes, use `/reload`.
Upstream owns the Remote Script and Live API compatibility. Report upstream limitations rather than creating another bridge.
