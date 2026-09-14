# Live 12 Standard release test

Use this procedure with the exact macOS and Live build for the release.
Fixture tests do not prove compatibility with Live.

## Test Set

Create a Set that contains these items:

- A group with two tracks.
- A return track and at least one send.
- A nested Instrument Rack with chains and macros.
- A Drum Rack.
- A Session MIDI clip with notes.
- A Session audio clip.
- MIDI and audio clips in Arrangement View.
- Two arrangement locators.

Save a copy of the Set before the test.
Record its file hash and modification time.

## Compatibility record

1. Record the Live version and edition.
2. Record the macOS version and computer model.
3. Record the Python version from the adapter diagnostics.
4. Record whether the edition source is `detection`, `configuration`, or `unavailable`.
5. If the build is unverified, set `allow_unverified_live` to `true` in the configuration file.
6. Restart Live after a configuration change.

The adapter must reject an unsupported major version.
An unknown edition must stay `unknown`.

## Bridge and lifecycle test

1. Start Pi with the integration off.
2. Run `/ableton status`.
3. Make sure that the status is `Ableton: off`.
4. Run `/ableton on`.
5. Make sure that one bridge process starts.
6. Run `/ableton on` again.
7. Make sure that a second bridge process does not start.
8. Quit Live.
9. Make sure that the bridge stays on and reports that Live is disconnected.
10. Start Live and open the test Set.
11. Make sure that the bridge publishes a fresh project view.
12. Run `/ableton off`.
13. Make sure that the owned bridge stops.
14. Make sure that a tool inspection returns `integration_disabled`.

Start a bridge outside Pi and repeat the on/off test.
Pi must attach to this external bridge.
Pi must not stop this external bridge.

Repeat the test for `/reload`, `/new`, `/resume`, `/fork`, and Pi exit.
Each old extension instance must stop only its owned bridge.

## Read-only behavior test

1. Start playback.
2. Record the transport state, selection, track states, and Set modification time.
3. Run all inspection actions and summaries.
4. Read MIDI notes from a bounded beat and pitch range.
5. Stop and restart the bridge during discovery.
6. Continue a paginated request after the restart.
7. Make sure that the request returns a reset or stale-cursor result.
8. Make sure that playback did not stop.
9. Make sure that the selection did not change.
10. Make sure that no track, clip, device, parameter, note, or automation value changed.
11. Make sure that the Set file hash and modification time did not change.

## Coverage and value test

Compare reported values with the Live user interface.
Test tracks, groups, returns, sends, routing, arrangement clips, racks, chains, macros, and selection.

Record these results:

- Startup discovery time.
- Steady-state tick duration.
- Reconnect time.
- Bridge shutdown time.
- Maximum bridge memory use.
- Discovery scope and completeness.
- Omitted or unsupported members.
- Capacity-pressure messages.

Run the coverage validator with the recorded target:

```bash
uv run python scripts/live_smoke.py \
  "$HOME/Library/Logs/ableton-ctrl/coverage.jsonl" \
  --output build/live-smoke \
  --target-version 12.4.2 \
  --edition Standard
```

Do not approve the release if a required value is incorrect.
Do not approve the release if an inspection changes the Set.
Keep the generated coverage files with the manual observations.
