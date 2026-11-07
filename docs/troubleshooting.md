# Troubleshooting

For installation order and success criteria, start with [Getting started](getting-started.md).
For snapshots and rollback, see [Recovery](recovery.md).

## Missing commands

If Terminal reports “command not found,” install the prerequisite from the [prerequisite list](getting-started.md#1-install-prerequisites).
Then open a new Terminal window and retry the version command.

Homebrew's FFmpeg package supplies both `ffmpeg` and `ffprobe`.
The uv installation supplies `uvx`, which setup uses for the pinned AbletonMCP package.

## Package command not found

Run:

```sh
uv tool list
```

If `ableton-ctrl` is absent, repeat the [package installation](getting-started.md#2-install-ableton-ctrl).
If it is present but `ableton` is missing from PATH, run:

```sh
uv tool update-shell
```

Open a new Terminal window. Then run `ableton --help`.

## Setup or compilation failed

Read the first error from the failed command. Save the printed recovery journal path.
Setup restores managed files when an installation step raises an error.

| Problem | Next action |
| --- | --- |
| Git, CMake, or a compiler is missing | Install the [build prerequisites](getting-started.md#1-install-prerequisites), then repeat setup. |
| Metal Toolchain is missing | Run `xcodebuild -downloadComponent MetalToolchain`, then repeat setup. |
| Metal remains unavailable | Use `ableton setup --install-whisper --backend cpu`. |
| User Library is not found | Locate it in Live, then repeat setup with `--user-library "/actual/path"`. |
| An existing script or MCP entry differs | Review the existing installation before any replacement. See [integration conflicts](#integration-conflicts). |
| A whisper.cpp directory is incomplete or unmanaged | Move that directory aside, then retry `ableton transcriber install`. |
| A build lock already exists | Wait for the active build. Remove the reported lock only after verifying that no build is running. |
| Recovery also failed | Keep the journal and snapshots. Use [manual recovery](recovery.md#interrupted-or-failed-recovery). |

Repeated setup preserves existing knowledge. It does not automatically replace a different Remote Script.

## Integration conflicts

**CAUTION: Do not force replacement of a working script without a recovery copy.**

Setup refuses an AbletonMCP configuration entry that differs from its managed entry.
It also preserves an existing Remote Script when upstream refuses replacement.
Review the conflicting paths from the error before changes.

The [integration reference](upstream-integration.md) describes the managed files and the advanced installer.
Enabling two bridges on the same port can prevent either bridge from connecting.

## Live connection problems

1. Leave Live open.
2. Verify that **AbletonMCP** is selected in an unused Control Surface row.
3. Verify that its Input and Output are **None**.
4. Fully restart Live after a Remote Script installation.
5. Run `/reload` inside Pi.
6. Run:

   ```sh
   ableton doctor
   pi mcp list
   ```

If setup used a custom User Library, include the same path:

```sh
ableton doctor --user-library "/path/to/User Library"
```

A successful connection has a matching script and a connected AbletonMCP server in Pi.
If the reported tracks differ from Live, use inspection-only requests until the results match.

`doctor` prints missing prerequisites as well as connection diagnostics. Inspect the output, not only its exit status.
For knowledge-only use, validate the library with `ableton kb lint` instead.

## Tutorial ingestion problems

### Download or media errors

Use one finite public video with audio. Playlist-only URLs and live streams are not supported.
Verify that `yt-dlp`, `ffmpeg`, and `ffprobe` are available.
For a local file, use an absolute path if its location is uncertain.

A failed acquisition or transcription can leave a job cache. Completed acquisition can be reused on retry.

### Transcription errors

If no whisper.cpp executable is available, run:

```sh
ableton transcriber install
```

If explicit Metal transcription fails, retry with CPU:

```sh
ableton kb add ./tutorial.mp4 --backend cpu
```

Explicit backend selections do not switch automatically. `auto` reports a CPU retry after a GPU error.
If a model download or checksum fails, resolve that error before retrying.

If an older executable takes precedence, review `WHISPER_CPP_BINARY` and `whisper-cli` on PATH.
The [transcription reference](../tools/transcribe/README.md) covers model files and backend diagnostics.

### Synthesis errors

1. Open Pi with `pi`.
2. Verify that a short question receives a model response.
3. If authentication fails, run `/login` inside Pi.
4. List saved drafts:

   ```sh
   ableton kb status
   ```

5. Retry synthesis with the full unpublished draft ID:

   ```sh
   ableton kb synthesize FULL_DRAFT_ID
   ```

A failed model call leaves the source draft unchanged.
Invalid citations or malformed model output prevent new technique drafts.
An empty technique result is valid when the source contains no supported technique.

If technique drafts already exist, review them before any regeneration.
For replacement rules, see [review and publication](knowledge-base.md#review-and-publish).

## Publication or import errors

Publication never overwrites an existing published page. Repeated publication of the same draft reports an error.
If publication fails partway through, its transaction restores the prior library.

Import requires a destination that does not exist. It rejects unsafe paths, unsupported schemas, and invalid evidence checksums.
Use a new directory rather than importing over personal knowledge.

## Ask for help

Include the failed command, its error, your operating system, and the relevant diagnostic output.
Remove credentials, private paths, and source text before sharing logs.
Keep recovery snapshots private. They can contain configuration and personal knowledge.
