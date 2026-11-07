# Native creator controls: acceptance tests

Candidate: `1.8.2.dev15`. Status: automated tests pass; Live acceptance remains pending.
These controls add ten MCP tools across four feature groups.
They use native Live properties and methods, not GUI automation.

## Setup and common checks

1. Follow the installation steps in [Arrangement acceptance](arrangement-acceptance.md).
2. Use a disposable Set with the latest supported Live version.
3. Keep the original Set and a saved recovery copy unchanged.
4. Record the package version, Live version, and running bridge build identifier.
5. Discover all ten tools listed below.
6. Read each target before writing settings.
7. Record the original settings for restoration.
8. Authorize playback separately from settings changes.
9. After each write, inspect the returned values.
10. If `unconfirmed` contains values, inspect again after a Live update.
11. If a partial failure occurs, stop further edits.
12. Inspect the reported state before using Undo or recovery.

Settings changes request one native Undo group per call.
Execute settings tools outside `batch_commands`.
Batch requests containing these setters must fail before any earlier command changes the Set.
Native setters can fail after earlier settings change. The response must report that partial failure.
The tools do not claim automatic rollback.

Use only existing tracks and returns for these tests.
The agent prepares temporary Session clips and scenes when needed.
The user does not prepare Session slots.
After testing, the agent removes only its own temporary resources.
If a required object is unavailable, record the check as untested rather than passed.

## 1. Session clip launch controls

Tools:

- `get_session_launch_settings`
- `set_session_launch_settings`
- `trigger_session_clip`

1. Ask the agent to prepare two short Session clips on an existing track.
2. Read both clips' launch settings.
3. Set Trigger, Gate, Toggle, and Repeat modes in separate tests.
4. Read back each requested mode.
5. Set global, unquantized, quarter-note, and one-bar quantization in separate tests.
6. Read back each enum value and mapping.
7. Set legato on and off.
8. Set velocity sensitivity within its reported range.
9. Confirm that settings changes do not start playback.
10. Authorize a short playback test at a comfortable level.
11. Test `fire` with a temporary quantization override.
12. Confirm that the override does not replace the stored clip quantization.
13. In Gate and Repeat modes, test `press` followed by `release`.
14. Confirm that release behaves like the corresponding launch-button release in Live.
15. Launch the second clip with legato enabled.
16. Compare its starting position with the expected legato behavior.
17. Stop playback.
18. Try an invalid enum, invalid sensitivity, and an empty slot.
19. Confirm rejection without changes or unintended recording.
20. Undo one settings change and compare its original values.

A queued launch is not immediate proof of playback.
Inspect after the quantization boundary before retrying.
Velocity sensitivity controls response to incoming launch velocity.
The trigger tool does not synthesize a velocity argument.

## 2. Scene tempo and time-signature overrides

Tools:

- `get_scene_musical_settings`
- `set_scene_musical_settings`

1. Use a temporary scene prepared by the agent.
2. Read its tempo, meter, and enable flags.
3. Set a tempo of 96 BPM with the tempo override enabled.
4. Set a 7/8 time signature with the meter override enabled.
5. Confirm that neither settings request launches the scene.
6. Read back all enabled values.
7. Authorize launching the scene.
8. Confirm that the song changes to 96 BPM and 7/8.
9. Stop playback.
10. Disable both scene overrides.
11. Read the disabled state.
12. Restore the song's original tempo and meter explicitly.
13. Launch the disabled scene after authorization.
14. Confirm that the song retains its current tempo and meter.
15. Try a denominator of 3 and a request containing an unknown field.
16. Confirm rejection before any valid sibling setting changes.
17. Undo a settings call and compare the scene's original state.

Live can report disabled scene values as `-1`.
The enable flags distinguish disabled overrides from active musical values.
An explicitly supplied enable flag applies after the requested musical values.

## 3. Simpler sample controls

Tools:

- `get_simpler_sample_controls`
- `set_simpler_sample_controls`
- `edit_simpler_slice`

Use Simpler on an existing MIDI track in the disposable Set.
Replacing an existing instrument requires separate approval.
The generated fixture audio is suitable for sample-region and slicing tests.

1. Load a known sample through the existing sample-loading tool.
2. Record its file hash before testing.
3. Inspect its path, sample rate, length, markers, slices, and playback mode.
4. Confirm that markers and slices use sample frames, not beats or seconds.
5. Compare a marker position with `seconds * sample_rate`.
6. Change the active sample region inward.
7. Move the region entirely after its previous end.
8. Move the region entirely before its previous start.
9. Confirm the observed boundaries and correct playback after each change.
10. In Classic mode, inspect the available loop parameters and native ranges.
11. Enable the loop through its inspected parameter index.
12. Inspect again before changing parameters that were previously disabled.
13. Change the available loop-region parameters within their native ranges.
14. Confirm the loop behavior through an authorized playback test.
15. Change to One-Shot mode.
16. Inspect before testing its playback behavior.
17. Change to Slicing mode.
18. Inspect again before changing slicing settings.
19. Test Transient, Beat, Region, and Manual slicing styles separately.
20. Test sensitivity, beat division, and region count in their relevant styles.
21. Read Mono, Poly, and Thru playback settings after changing each value.
22. In Manual style, insert a slice at an unused valid frame position.
23. Move that slice to another unused position.
24. Remove that slice.
25. Confirm the observed slice list after each operation.
26. Test pad slicing and retrigger settings in supported modes.
27. Set an accepted voice count and compare the observed value.
28. Repeat inspection and one edit for a Simpler nested inside a rack.
29. Try a non-Simpler device, an empty Simpler, and an unavailable nested path.
30. Try an invalid marker range, missing source slice, and occupied slice destination.
31. Confirm structured rejection without unrelated changes.
32. Confirm that moving or removing the first slice is rejected by this tool.
33. Undo a marker edit and a slice edit separately.
34. Compare the restored markers and slice lists.
35. Compare the source file hash with the original hash.

Mode-dependent edits require a separate mode change and inspection first.
Loop controls use discovered device parameters rather than guessed parameter names or positions.
A disabled parameter must be enabled through a separate supported setting before editing it.
Multisample Simpler is explicitly unsupported.
These tools do not crop, replace, or rewrite the source audio file.

## 4. Additional mixer controls

Tools:

- `get_mixer_controls`
- `set_mixer_controls`

1. Inspect one regular track, one existing return, and the master.
2. Record supported fields, enable states, and native parameter ranges.
3. Change master cue volume within its reported range.
4. Confirm its observed value and the corresponding Live control.
5. Set a regular track to Split Stereo mode.
6. Inspect again before editing its left and right pan values.
7. Change each pan value independently.
8. Confirm that the other side remains unchanged.
9. Return to Stereo mode.
10. Inspect a return track's volume, pan, mute, solo, and available sends.
11. Change each supported field separately.
12. Confirm the observed value and corresponding Live control.
13. If sends exist, change one send without changing the others.
14. Try cue volume on a non-master target.
15. Try an out-of-range pan, invalid target index, and disabled parameter.
16. Confirm rejection without valid sibling changes.
17. Request Split Stereo mode and split pan together from Stereo mode.
18. Confirm rejection with instructions to change the mode separately.
19. Undo a mixer settings call and compare its original values.
20. Confirm that no tracks or returns were added.

Parameter values use native ranges, not dB strings.
Unsupported or disabled controls must not silently receive guessed values.
Hardware cue routing is outside these tools' scope.

## Acceptance record

- [ ] Session launch settings and explicit triggering
- [ ] Scene tempo and time-signature overrides
- [ ] Simpler metadata, regions, loops, modes, and slices
- [ ] Cue volume, split panning, and return mixer controls
- [ ] Validation before writes and structured unsupported responses
- [ ] Undo and readback behavior
- [ ] Source hashes unchanged and temporary resources removed

Record actual Live results separately from automated test results.
These checks supplement the pending Arrangement tests; they do not replace them.

## Native API references

- [Clip](https://docs.cycling74.com/apiref/lom/clip/)
- [ClipSlot](https://docs.cycling74.com/apiref/lom/clipslot/)
- [Scene](https://docs.cycling74.com/apiref/lom/scene/)
- [SimplerDevice](https://docs.cycling74.com/apiref/lom/simplerdevice/)
- [Sample](https://docs.cycling74.com/apiref/lom/sample/)
- [MixerDevice](https://docs.cycling74.com/apiref/lom/mixerdevice/)
