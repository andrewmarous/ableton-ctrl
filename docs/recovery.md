# Recovery

For ordinary errors, start with [Troubleshooting](troubleshooting.md).
This page explains installation snapshots and rollback.

## Automatic recovery

Setup prints a `Setup recovery journal` path before changes.
It snapshots managed Pi files, the Remote Script, and application configuration.
A new knowledge directory or managed whisper.cpp build is also tracked when setup creates it.
Existing knowledge remains untouched.

If installation raises an error, setup restores the tracked paths.
Automatic recovery covers Python exceptions and keyboard interrupts.
It does not cover power loss or forced process termination.
Empty parent directories and downloaded package caches can remain.

Standalone Remote Script installation, whisper.cpp installation, and knowledge publication also use transaction snapshots.
Snapshot locations include:

- Full setup: `~/.pi/agent/backups/setup/`.
- Advanced Live installer: `~/.pi/agent/backups/ableton-upstream/`.
- Standalone whisper.cpp installer: `~/.pi/agent/backups/whisper/`.
- Publication: `.pi/agent/backups/publication/` under the parent of the knowledge directory.

## Restore a completed installation

**CAUTION: Use only a trusted local backup. Its manifest contains absolute restore paths.**

1. Find the setup journal path from the installation output.
2. Save any work in Live.
3. Replace `BACKUP_DIRECTORY` with that journal directory:

   ```sh
   ableton rollback "BACKUP_DIRECTORY"
   ```

4. Read and approve the restoration prompt.
5. Restart Live if the Remote Script changed.
6. Run `/reload` inside Pi if its configuration changed.

**Success:** the command prints `Installation restored.`
Rollback creates a recovery snapshot before restoration.
Live preferences are not part of the snapshot. Adjust the Control Surface row manually if necessary.

## Files changed after setup

Rollback refuses to overwrite tracked files that changed after installation.
This includes personal knowledge added to a library that setup created.
It also includes later edits to a tracked Pi configuration file.
There is no force option.

If rollback reports a conflict, save the later changes separately before any manual recovery.
Do not remove personal knowledge merely to make rollback succeed.
A selective manual restoration can be safer than a complete rollback.

## Interrupted or failed recovery

If the process stops abruptly, keep its journal and snapshots.
If automatic recovery also reports an error, keep the full error output.

`transaction.json` records tracked paths, snapshots, and transaction state.
A journal in the `applying` state requires manual recovery from its snapshots.
The rollback command accepts only a committed transaction.

**CAUTION: Do not copy snapshots over current files without comparing them first. Later changes can be lost.**

For assistance, share the error and a redacted list of affected paths.
Do not publish the snapshots or configuration contents.

## Knowledge backups are separate

Installation rollback is not a replacement for a knowledge export.
Before a move or library changes, use the [export procedure](knowledge-base.md#export-and-import).
Exports contain published knowledge, not unpublished drafts.
