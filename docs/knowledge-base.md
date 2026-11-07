# Knowledge base

For first use, follow [Getting started](getting-started.md). This page covers the commands after setup.

The default library is `~/.pi/agent/ableton-wiki`.
Published pages use Markdown. `kb.json` stores the versioned source manifest.
Drafts remain separate from published knowledge.

## Add a source

```sh
ableton kb add ./notes.md
ableton kb add ./transcript.json
ableton kb add ./tutorial.mp4
ableton kb add "VIDEO_URL"
```

Text sources can use `.md`, `.markdown`, `.txt`, or JSON transcripts.
Video acquisition supports one finite public video, not playlist-only URLs or live streams.
Local transcription supports English audio.

`kb add` creates source evidence, not generated production advice.
Identical source bytes reuse the existing draft.

To generate technique drafts during ingestion, add `--synthesize`:

```sh
ableton kb add ./tutorial.mp4 --synthesize
```

To synthesize an existing unpublished source, run:

```sh
ableton kb synthesize FULL_DRAFT_ID
```

To select a Pi model, add `--model YOUR_PI_MODEL` to either synthesis command.
Pi must be installed and authenticated.

**Privacy and cost:** synthesis sends source text to your configured Pi model. Provider charges can apply.
Transcription stays local and does not use a hosted transcription service.

Synthesis runs without tools, MCP, extensions, context files, or persistent Pi sessions.
Long sources use multiple model calls. Each generated step and caution cites input evidence.
Citation validation checks references, not factual correctness.

## Review and publish

List drafts:

```sh
ableton kb status
```

Copy the full draft ID from the output. Use it instead of `FULL_DRAFT_ID` below:

```sh
ableton kb review FULL_DRAFT_ID
```

The output shows the source page, technique drafts, and their file paths.
Review the evidence and citations. Edit the draft files with your text editor if necessary.

After review, run:

```sh
ableton kb publish FULL_DRAFT_ID
```

Publication asks for approval. It adds the source page, technique pages, and index entries together.
An error restores the previous library. Existing published pages never receive automatic replacements.

Synthesis supports unpublished sources only. It does not merge advice across sources.
To regenerate technique drafts, first move the existing draft `techniques` directory aside.

## Search and validate

```sh
ableton kb search "parallel compression"
ableton kb lint
```

Search prints matching published lines with their file paths.
Validation prints `[]` when there are no findings.
To ask a question with library context, run `ableton chat`.

## Export and import

Export published knowledge:

```sh
ableton kb export ./production-knowledge.zip
```

The destination archive must not already exist.
Exports include published pages, imported source evidence, and library metadata.
They exclude drafts, job caches, downloaded media, and application configuration.

**CAUTION: Review the source evidence before you share an archive. It can contain private information.**

Import into a new directory:

```sh
ableton --kb ~/Music/restored-knowledge kb import ./production-knowledge.zip
```

Import never merges into an existing library. It supports schema version 1 and archives up to 512 MiB after extraction.
It rejects unsafe paths and symbolic links.

Import does not change the saved default library. To use the imported library, keep its `--kb` argument:

```sh
ableton --kb ~/Music/restored-knowledge chat
```

## Alternative setup

### Choose a knowledge directory

```sh
ableton --kb ~/Music/production-knowledge setup --install-whisper
```

Setup saves this directory for later commands. `--kb` overrides the saved directory and must precede the subcommand.

### Use knowledge without Live

```sh
ableton --kb ~/Music/production-knowledge setup --knowledge-only --install-whisper
```

This skips the Live integration. For text-only sources, omit `--install-whisper`.
Plain text ingestion, review, search, and export do not require Pi.
Chat and automatic synthesis still require Pi and a model provider.
`ableton doctor` also checks Live, so it is not a knowledge-only acceptance test.

## Transcription choices

The default `auto` mode selects Metal on Apple Silicon, then CUDA where available, otherwise CPU.
If GPU inference fails in `auto` mode, the transcriber reports a CPU retry.
Explicit backend selections never switch backends:

```sh
ableton kb add ./tutorial.mp4 --backend cpu
ableton kb add ./tutorial.mp4 --backend metal
```

Install a managed build separately if necessary:

```sh
ableton transcriber install
ableton transcriber install --backend cpu
```

Build prerequisites are in [Getting started](getting-started.md#1-install-prerequisites).
`WHISPER_CPP_BINARY`, an explicit executable argument in the standalone transcriber, and `whisper-cli` on PATH take precedence over managed builds.

CUDA requires the package's `cuda` extra and a compatible NVIDIA environment.
See the [standalone transcription guide](../tools/transcribe/README.md) for CUDA requirements and lower-level commands.

## Storage and cleanup

- `drafts/`: editable source and technique drafts within your library.
- `wiki/`: published pages within your library.
- `raw/`: imported source evidence within your library.
- `~/.cache/ableton-ctrl/jobs`: downloaded video jobs.
- `~/.cache/ableton-ctrl/transcripts`: transcription outputs.
- `~/.local/share/ableton-ctrl/whisper`: managed inference builds and their libraries.

A completed video acquisition can be reused after a transcription error.
Partial downloads and interrupted transcription do not support stage-level resume.
The application does not automatically prune these caches.

Keep each managed whisper.cpp directory intact. Its executable needs the libraries beside it.
Before removing installation snapshots, read [Recovery](recovery.md).
