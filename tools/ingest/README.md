# Video ingestion prototype

This package implements the single-video evidence workflow in `docs/video-ingestion-prototype-plan.md`. It has no model API dependency. It uses [uv](https://docs.astral.sh/uv/) for dependency management. From the repository root, create the locked development environment with:

```sh
uv sync --project tools/ingest --locked
```

Include the CUDA runtime dependencies when running transcription:

```sh
uv sync --project tools/ingest --locked --extra cuda
```

Run commands through the locked environment, for example:

```sh
uv run --project tools/ingest --locked video-ingest --help
```

`prepare` uses `yt-dlp` and `ffprobe`; `transcribe` delegates to `tools/transcribe`; `screenshots` uses FFmpeg; `publish` creates an immutable revision. The transcriber requires CUDA and English audio as documented in `../transcribe/README.md`.

Jobs are kept outside `raw/`. The publication contains source metadata, the exact transcript outputs, agent-authored candidate records, frame records, navigation context, and a SHA-256 manifest. Downloaded media and temporary files are never copied into the published bundle.

The prototype accepts one finite public video. Playlist-only URLs, live streams, media without audio/video, unsupported timeline discontinuities, wiki synthesis, distribution, and installer changes are outside its scope.

## End-to-end Pi skill test

The test script starts Pi in print mode with only the local `video-ingest` skill enabled. Pi prepares and transcribes the video, reviews the complete transcript, writes `candidates.json`, extracts screenshots, and publishes the revision.

CUDA must be configured before the script starts. See `../transcribe/README.md`. Pi must also be installed and authenticated with a model provider.

From the repository root, run:

```sh
tools/ingest/scripts/test-e2e-with-pi.sh PUBLIC_SHORT_ENGLISH_VIDEO_URL
```

To retain output at a specific location, pass it as the second argument:

```sh
tools/ingest/scripts/test-e2e-with-pi.sh VIDEO_URL /tmp/video-ingest-e2e
```

The script stores Pi's final output in `pi-output.txt`. The downloaded job cache remains outside the `raw/` directory.
