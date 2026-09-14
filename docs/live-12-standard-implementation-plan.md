# Live 12 Standard: read-only inspection and bridge controls

## Scope

This plan expands project inspection and adds user controls for the local bridge.
All access to Live remains read-only.

The bridge controls manage this application's processes and observation state. They do not control Live transport or change the Set.

Excluded features:

- Transport control, clip launches, and recording.
- Track, device, parameter, note, or automation edits.
- Selection changes inside Live.
- Set saves, exports, and arbitrary Python execution.
- Windows support in this release.

Local configuration, logs, and explicit inspection bookmarks can still use local files outside the Set.

## Current implementation

- `adapter/remote_script.py` requires version `12.4.2` and hardcodes the edition as `Intro`.
- `adapter/manifest.py` contains a small, Intro-named observation allowlist.
- Discovery excludes callable members, including potential read methods.
- The Pi extension only forwards inspection requests to the CLI.
- The bridge starts through a separate console command.
- The CLI uses Set names for implicit change cursors.
- Publication limits can require a Remote Script restart after capacity errors.
- The README links to a missing `docs/live-smoke-test.md`.

Paths beginning with `adapter/`, `bridge/`, or `resources/` refer to `src/ableton_ctrl/`.

## Design rules

1. Keep the existing Remote Script, bridge, CLI, Pi, and optional MCP architecture.
2. Keep Live API access on the Live main thread.
3. Permit only explicit properties, relationships, and verified read methods.
4. Keep socket work, JSON encoding, and summary computation outside the Live main thread where possible.
5. Distinguish missing data from unsupported data and incomplete discovery.
6. Preserve bounded responses, pagination, authentication, and loopback-only binding.
7. Never start the bridge as a side effect of an inspection request.

## Phase 1: compatibility and diagnostics

### Work

- Add a compatibility profile module with a shared Live 12 manifest and optional capability groups.
- Report the actual Live version in the handshake, schema, diagnostics, and coverage records.
- Detect edition only through a verified mechanism.
- Otherwise, accept explicit edition configuration or report `unknown`.
- Record whether edition information comes from detection or configuration.
- Replace the exact-version gate with tested, unverified, and unsupported compatibility states.
- Require explicit opt-in for unverified builds until their smoke test passes.
- Keep unsupported major versions disabled.
- Verify the installed runtime against the target Live build's embedded Python.
- Keep the installed adapter free of third-party Python dependencies.
- Expose the existing bridge status through the CLI and Pi tool.
- Add a `doctor` action for executable paths, installation, configuration, authentication, connectivity, version, and coverage.
- Replace Intro-only limitations with profile-aware resources.
- Parameterize the smoke validator by target version, edition, and manifest.

Diagnostics must distinguish a stopped bridge, authentication failure, disconnected Live, stale data, partial discovery, and unsupported runtime.
They must not print the shared secret.

### Main files

`adapter/remote_script.py`, `adapter/runtime.py`, `adapter/manifest.py`, `contracts.py`, `cli.py`, `resources/`, `scripts/live_smoke.py`.

### Acceptance criteria

- The target Standard build connects and reports accurate version metadata.
- An unknown edition never becomes Intro by default.
- Existing inspection actions retain their documented behavior.
- Fixture tests do not claim real Live compatibility.

## Phase 2: Pi bridge on/off controls

### User interface

Add one slash command with explicit subcommands:

| Command | Behavior |
| --- | --- |
| `/ableton` | Show status and a Start/Stop/Refresh menu where dialogs are available. |
| `/ableton on` | Start a managed bridge, or attach to an existing compatible bridge. |
| `/ableton off` | Disable inspection in this extension and stop its owned bridge. |
| `/ableton status` | Show integration, bridge, and Live connection states. |
| `/ableton doctor` | Show installation and connection diagnostics. |

Add argument completion and a compact status indicator through `ctx.ui.setStatus`.
Do not replace Pi's footer.

Example states:

- `Ableton: off`
- `Ableton: starting`
- `Ableton: on · waiting for Live`
- `Ableton: on · discovering`
- `Ableton: on · read-only`
- `Ableton: on · partial/stale`
- `Ableton: external bridge`
- `Ableton: error`

The menu and explicit commands share the same controller.
Noninteractive modes receive structured results without dialogs or terminal-only components.
Start/stop remain user commands, not actions in the model-facing inspection tool.

### Process ownership

Add a small, testable process controller used by the extension.
Use `spawn` with an executable and argument array, not a shell command string.

- Resolve an installed bridge executable independently of Pi's current directory.
- Support an explicit executable path in trusted user configuration.
- Do not run `uv sync`, install dependencies, or download packages during startup.
- Default to off. Start only after `/ableton on`.
- Serialize start and stop operations to prevent duplicate children.
- Wait for authenticated readiness with a bounded timeout.
- Track the child handle and a bridge instance identifier.
- Never infer process ownership from an occupied port or a PID file alone.
- Never use `pkill`, process-name matching, or port-based termination.
- Capture bounded, redacted diagnostics from the child.
- On failure, clean up only the child created by this controller.

An existing authenticated bridge is external to this extension instance.
The extension can attach to it, but cannot stop it.
For an external bridge, `/ableton off` disables local inspection and reports that the process remains active.
This rule also covers bridges owned by another Pi process.

### Off and lifecycle behavior

Before stopping an owned bridge, block new inspection requests and cancel this extension's pending queries.
Request graceful shutdown, wait for a bounded interval, and escalate only against the verified owned child if necessary.
The server must close its listener and active connections and finish bounded cleanup.

Keep `ableton_ctrl` registered, but reject live-data requests while off with a structured `integration_disabled` result.
Permit local resources and diagnostics while off.
Do not return cached project data as current data after shutdown.

For the first release, bridge ownership is session-scoped:

- `session_shutdown` closes timers, query processes, sockets, and the owned bridge.
- Quit, reload, new-session, resume, and fork use the same idempotent cleanup.
- The replacement extension starts off and requires `/ableton on` again.
- External bridges remain untouched throughout these events.
- The factory starts no background resources.

Use an inherited supervision pipe or equivalent parent-liveness mechanism for managed children.
An unexpected Pi exit must not leave an indefinitely orphaned bridge.
Do not store process ownership credentials in conversation history.

### Adapter behavior while the bridge is off

Stopping the bridge alone does not unload the Remote Script.
Add an idle state that suspends graph discovery and publication while disconnected.
Keep only bounded connection retries and required listener cleanup active.
Discard obsolete pending graph data and request a fresh synchronization after reconnection.

This behavior must leave playback, recording, selection, and Set contents unchanged.
It does not claim to unload the Control Surface or remove all adapter overhead.

### Main files

`pi_artifacts/extension/ableton-ctrl.ts`, a new extension controller module if needed, `bridge/server.py`, `adapter/runtime.py`, `cli.py`, `contracts.py`, `pi_installer.py`.

If the extension gains helper files, update the installer and package data together.

### Acceptance criteria

- Repeated `on` commands create at most one owned bridge.
- Repeated `off` commands succeed without unrelated process signals.
- The bridge can be on while Live is closed.
- Port conflicts and incorrect authentication produce useful errors.
- An off integration never starts itself through a tool call.
- Reload and session changes leave no owned bridge or duplicate timer.
- An external bridge survives off, reload, and Pi exit.
- Bridge off/on recovers a fresh project view without restarting Live.

## Phase 3: discovery reliability and project identity

Complete this phase before broad graph expansion.

- Register supported listeners and retain polling fallbacks.
- Remove listeners when objects disappear and during adapter cleanup.
- Use slower cadences for stable metadata and bounded polling for changing values.
- Add observation scopes for tracks, device branches, and requested detail.
- Distinguish query pagination from adapter discovery limits.
- Replace terminal oversized-graph behavior with bounded incremental publication and explicit continuation state.
- Preserve transaction consistency and revision semantics during incremental discovery.
- Report scope, discovery progress, omissions, and capacity pressure in metadata.
- Verify object identity behavior against real Live wrappers.
- Update paths after track or device reordering without changing stable object IDs unnecessarily.
- Detect Set replacement and invalidate old object IDs.
- Key change cursors by session identity, not Set display name alone.
- Add a bridge generation identifier because bridge restarts can reset revisions within an adapter session.
- Reset cursors safely after bridge restart, Set replacement, or incompatible schema changes.

### Acceptance criteria

Large fake Sets and real representative Sets complete scoped inspection without silent data loss.
Same-name Sets do not share cursors.
Deleted and reordered objects produce correct relationships and changes.
Timing evidence covers startup, steady state, reconnect, and bridge shutdown.

## Phase 4: richer project inspection

Expand the allowlist in small capability groups.
Each group needs fake objects, contract tests, schema descriptions, units, and real Live evidence.
Availability depends on the target build, not the Standard edition label alone.

| Group | Information |
| --- | --- |
| Set | Time signature, song position, loop region, recording state, arrangement locators. |
| Tracks | Mute, solo, arm, audio/MIDI type, group relationships, frozen state, routing. |
| Mixer | Return tracks, sends, crossfader assignments, parameter display values and units. |
| Arrangement | Arrangement clips, timeline positions, lengths, owning tracks. |
| Clips | Audio/MIDI type, loop boundaries, markers, launch settings, warp settings where available. |
| Devices | Nested racks, chains, chain mixers, macros, drum pads, parameter metadata. |
| Selection | Selected track, scene, device, and detail clip, without changing selection. |

Prioritize tracks, return tracks, sends, rack chains, and arrangement clips.
Add cycle protection and explicit depth limits for nested relationships.
Treat third-party plug-in internals as unavailable unless Live exposes them.
Do not infer missing samples, full automation curves, or plug-in state from incomplete metadata.

### Dedicated read operations

Add typed, allowlisted read requests for data that requires method calls.
Start with `clip_notes`, bounded by beat range, pitch range, note count, and response size.

- Validate the session and target before each main-thread read.
- Use request IDs, cancellation, deadlines, and bounded response queues.
- Keep generic method invocation prohibited.
- Verify that each method has no selection or Set mutation side effects.
- Invalidate continuation state when the source clip changes.
- Avoid repeated full-clip reads disguised as pagination.

Investigate automation and sample metadata through the same mechanism.
Keep unsupported reads explicit rather than promising complete coverage.

## Phase 5: project summaries and useful differences

Add deterministic summaries computed from the bridge graph:

- `project_summary`: tracks, groups, returns, tempo, and observed arrangement extent.
- `track_summary`: clips, routing, devices, sends, and mixer state.
- `device_tree`: nested rack contents with depth and page limits.
- `selection`: the current read-only selection view.
- `project_diff`: human-readable changes since an explicit revision or inspection bookmark.

Summary responses include session, bridge generation, revision, capture time, scope, and completeness.
Counts from incomplete scopes must identify themselves as observed counts.
Missing information remains unknown, not zero or false.

Use one coherent graph revision per summary.
Retain the low-level object API for detailed follow-up requests.
Keep CLI, Pi, and optional MCP schemas aligned.
Bound both model-facing text and structured tool details.

Inspection bookmarks contain metadata outside the Set.
When history expires, return `stale_cursor` rather than inventing a difference.

## Phase 6: installation, documentation, and release validation

- Add `docs/live-smoke-test.md` and repair the README release instructions.
- Document bridge ownership, off behavior, lifecycle cleanup, and recovery.
- Document capability limits and the distinction between Session and Arrangement clips.
- Update the bundled Pi skill to describe read-only operations and user bridge commands.
- Preserve the rule that inspection requests never auto-start the bridge.
- Add a managed Pi artifact upgrade path with checksums and backups.
- Refuse automatic replacement of user-modified extension or skill files.
- Verify installation from a package and from a checkout.

### Automated validation

Run the existing pytest, Ruff, mypy, and package-build checks.
Add executable TypeScript tests for the controller and extension lifecycle.
Do not rely only on source-text assertions for process behavior.

Required scenarios:

- Standard, configured edition, unknown edition, and unsupported version.
- Missing executable, startup timeout, occupied port, and authentication failure.
- Concurrent on/off, startup cancellation, child crash, and parent crash.
- Two Pi processes, external bridge attachment, and ownership refusal.
- Reload, quit, new-session, resume, fork, and noninteractive execution.
- Bridge restart during discovery or a paginated read.
- Large Sets, nested racks, return tracks, and arrangement-only projects.
- Renamed Sets, same-name Sets, object deletion, and reordered tracks.
- Unsupported properties, missing read methods, and partial summaries.
- Mutation attempts rejected across CLI, bridge, adapter, Pi, and MCP surfaces.

### Real Live release gate

Use the user's exact Live 12 Standard build on macOS.
Use a representative Set with groups, returns, racks, MIDI clips, audio clips, and arrangement content.

Verify bridge on/off during playback without playback interruption or Set modification.
Verify discovery timing, memory limits, accurate values, and reconnection.
Verify MIDI read operations without note selection or content changes.
Record the version, edition source, capabilities, timing results, and manual observations.

## Delivery order

1. Compatibility profile, status, and diagnostics.
2. Bridge process controller, Pi commands, and disconnected adapter idle state.
3. Discovery capacity, listener lifecycle, and cursor identity.
4. Core track, mixer, rack, and arrangement inspection.
5. Summaries and selection inspection.
6. Bounded MIDI reads and project differences.
7. Managed upgrades, documentation, and the Standard release gate.

Each change remains read-only toward Live.
No editing API or dormant mutation endpoint belongs in this plan.
