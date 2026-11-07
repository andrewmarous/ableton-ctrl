# Arrangement reconstruction contract

Status: experimental implementation for disposable-Set acceptance, not production approval.

## Authorization

Complex edits require a preview, explicit edit authorization, a saved recovery point, and separate reconstruction authorization.
They never create tracks. They can create temporary Session clips and, when necessary, a temporary scene.
The agent prepares these clips. The user does not prepare Session slots.

## Content preservation

Moves, splits, and inward trims use native Arrangement copies in a holding area beyond existing content.
Temporary Session clips truncate working copies through Live's overlap behavior.
Native copies preserve content that note-by-note reconstruction cannot reproduce, including expression and audio warp state.
Live acceptance must establish these guarantees for loops, source offsets, unwarped audio, and warped audio.
No source file is cropped, rewritten, or removed.
An audio carrier uses a generated silent WAV. That file remains available for Undo.

Track automation stays at absolute timeline positions during clip edits.
The interface does not claim that moving a clip moves its automation.
If automation must move, the agent must inspect the saved lanes and preview separate automation edits.

Cross-track edits and destructive destination overwrite are rejected.
Native audio source-property edits include guarded warp-marker changes.
Warp-marker sample times use source seconds. Segment tempos must stay within 5..999 BPM.
The terminal warp-reference marker remains protected.
Boundary splits are no-ops. Trims only shorten clips and cannot create a zero-length result.

## Automation

Automation writes use a temporary Session envelope on the existing track.
Native copies park every clip that intersects the requested range.
The implementation removes those originals, stamps the requested envelope, then restores their native copies.
Only the addressed parameter receives an envelope in the carrier.
Automation outside the range must remain unchanged during acceptance.

The initial writer supports continuous step and linear automation for track mixer and device parameters.
Parameter addressing uses zero-based device/chain paths or mixer names.
It does not infer live parameter identity from saved XML IDs.
It refuses tracks without audio output, returns, the master track, and quantized parameters.
Curve inspection retains exact saved XML. Curve writes are outside the initial supported subset.

## Failure behavior

Every final Arrangement edit requests one Live undo group.
Audio carrier preparation requires a preceding request because Live defers warping changes.
Preparation has a separate undo step and does not alter Arrangement clips.
A `prepared` response requires another execution request or explicit cancellation.
One Undo after final execution must restore Arrangement content. Temporary Session resources can reappear through Undo.
Acceptance must verify cleanup and subsequent Undo behavior.
After partial failure, the tool reports completed steps and retained holding copies.
It never deletes the last recovery copy after a failed restoration.
The user can inspect those copies, use Undo, or reopen the saved recovery Set.
Temporary clip or scene cleanup failures are reported, not hidden.
An error does not claim automatic rollback or unchanged Live state.

Preview validation cannot prove that a Live API mutation will succeed.
Production use remains blocked until disposable-Set acceptance verifies preservation and recovery.
