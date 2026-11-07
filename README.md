# ableton-ctrl

Connect Pi to Ableton Live and build a production knowledge base from your notes and tutorials.
Ask questions about your Set, with source references separate from observed Live facts.
Live edits require an explicit request.

## Start here

**[Install and get started](docs/getting-started.md)**

The guide covers prerequisites, package installation, the Live connection, and your first published tutorial.
The primary path targets Apple Silicon Macs. Local transcription supports Metal and CPU.

**Release status:** the package is not on PyPI. Installation requires a trusted wheel or a source checkout.
The guide explains both, without assuming that a public release asset exists.

## After setup

Audio commands and agent guidance are included in normal setup, using FFmpeg:

```sh
ableton audio doctor
ableton audio inspect ./recording.wav
```

To capture Live output, [configure a loopback input](docs/audio.md), then run `ableton audio capture --seconds 8`.


```sh
ableton kb add ./tutorial.mp4 --synthesize
ableton kb status
ableton chat
```

Technique synthesis sends transcript text to your configured Pi model. Provider charges can apply.
Generated pages stay in draft form until you review and publish them. Transcription stays local.

## Guides

- [Audio capture and inspection](docs/audio.md): record Live through loopback and inspect audio locally.

- [Getting started](docs/getting-started.md): install, connect, and publish your first tutorial.
- [Knowledge base](docs/knowledge-base.md): add sources, review drafts, search, and share your library.
- [Troubleshooting](docs/troubleshooting.md): resolve installation, connection, and ingestion errors.
- [Recovery](docs/recovery.md): restore an installation without overwriting later changes.
- [Development and distribution](docs/distribution.md): install from source, build wheels, and prepare releases.
- [Integration reference](docs/upstream-integration.md): component responsibilities and advanced installation.

The independent [ingestion](tools/ingest/README.md), [scraping](tools/scrape/README.md), and [transcription](tools/transcribe/README.md) tools remain available for development.
