# Getting started

This guide takes you from installation to a verified Live connection and one published tutorial.
The primary path targets an Apple Silicon Mac with Ableton Live installed.
CPU and Metal builds passed compilation tests on Apple Silicon. Linux and native Windows installation remain unverified.

## 1. Install prerequisites

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Install [Pi](https://pi.dev/).
3. Install [Homebrew](https://brew.sh/) if it is not available.
4. Install the Apple compiler tools:

   ```sh
   xcode-select --install
   ```

   An existing installation can report that the tools are already installed.

5. Install the build and media tools:

   ```sh
   brew install cmake ffmpeg yt-dlp
   ```

6. Open Pi:

   ```sh
   pi
   ```

7. Run `/login` inside Pi to connect your model provider.
8. Ask Pi a short question to verify that the model responds.
9. Exit Pi.

**Success:** these commands print version information without a “command not found” error:

```sh
uv --version
pi --version
git --version
cmake --version
ffmpeg -version
yt-dlp --version
```

If a prerequisite fails, see [missing commands](troubleshooting.md#missing-commands).

## 2. Install ableton-ctrl

The package is not on PyPI. Installation requires a maintainer-provided wheel or a source checkout.

1. Open the [GitHub releases page](https://github.com/andrewmarous/ableton-ctrl/releases).
2. If a release contains a wheel, download its `.whl` asset from that trusted release.
3. In Terminal, install the downloaded file:

   ```sh
   uv tool install --python 3.13 /path/to/ableton_ctrl-0.1.0-py3-none-any.whl
   ```

   Replace the path and filename with the actual download. uv manages the Python interpreter.

**If no wheel is available:** use the [source installation procedure](distribution.md#install-from-source).
Then return to step 3 below. Do not run a PyPI installation command for this package.

Verify the installation:

```sh
ableton --help
```

**Success:** the help lists `setup`, `doctor`, `audio`, `chat`, and `kb`.
If the command is missing, see [package command not found](troubleshooting.md#package-command-not-found).

## 3. Run guided setup

Run:

```sh
ableton setup --install-whisper
```

Read the plan before you approve it. Save the printed `Setup recovery journal` path.

Setup creates the knowledge base, builds whisper.cpp, installs the Remote Script, and configures Pi.
Audio commands and agent guidance are included. Setup checks FFmpeg and its required filters without opening an audio input.
On Apple Silicon, the managed build uses Metal. Existing knowledge remains untouched.
The build needs an internet connection and can take several minutes.

**Success:** setup prints `Setup complete.` and the manual Live connection steps.
If setup fails, see [setup or compilation failed](troubleshooting.md#setup-or-compilation-failed).

### Optional: relocated User Library

If your User Library is not in its default location, use its actual path instead:

```sh
ableton setup --install-whisper --user-library "/path/to/User Library"
```

Use that same `--user-library` argument with `ableton doctor` later.

For a custom knowledge directory or no Live connection, see [alternative setup](knowledge-base.md#alternative-setup).

## 4. Connect Live

1. Fully restart Live.
2. Open **Settings > Tempo & MIDI**.
3. Select **AbletonMCP** in an unused **Control Surface** row.
4. Set that row's **Input** to **None**.
5. Set that row's **Output** to **None**.
6. Open Pi.
7. Run `/reload` inside Pi.

Leave Live open for the next step. Older Live versions can use a different name for the MIDI preferences panel.

## 5. Verify the connection

In another Terminal window, run:

```sh
ableton doctor
pi mcp list
```

For a relocated User Library, use:

```sh
ableton doctor --user-library "/path/to/User Library"
```

**Success:** the upstream diagnostic reports a matching script, and Pi reports that AbletonMCP is connected.
The prerequisite list must not report missing commands. Knowledge validation shows `[]` when there are no findings.

In Pi, ask:

> Inspect only. Report the current tempo and track names. Do not start playback or edit the Set.

Compare the answer with Live.

**Success:** the tempo and track order match your Set.
If they do not, stop here and use [Live connection problems](troubleshooting.md#live-connection-problems).

### Optional: capture and inspect Live audio

Audio inspection is part of the normal plugin installation:

```sh
ableton audio doctor
ableton audio inspect /path/to/existing-recording.wav
```

For capture, configure a loopback device and route Live's output through it.
Follow [audio setup](audio.md#configure-capture-on-the-laptop), then save the selected input:

```sh
ableton setup --audio-device 'BlackHole 2ch'
```

Reload Pi after setup. The installed skill includes capture and inspection instructions.
Use existing Live controls to choose the passage and solo tracks or groups.
While Live plays, run:

```sh
ableton audio capture --seconds 8
```

Inspect the returned WAV path with `ableton audio inspect`.
**Success:** the JSON contains measurements and two PNG paths. The recording contains the intended Live output.
Loopback routing and macOS device access require verification on the laptop.
The diagnostic command does not open an input or prove that routing works.

## 6. Add your first tutorial

Choose a short, public English tutorial that you have permission to download.
Replace `VIDEO_URL` with its URL:

```sh
ableton kb add "VIDEO_URL" --synthesize
```

Transcription stays local. First use can download model weights.
`--synthesize` sends transcript text to your configured Pi model. Provider charges can apply.
Without that flag, ingestion creates a source draft without generated technique pages.

**Success:** the command prints a full `Draft` ID and commands for review and publication.
Some sources produce no technique pages. Their source evidence can still be published.
If ingestion fails, see [tutorial ingestion problems](troubleshooting.md#tutorial-ingestion-problems).

Copy the full ID. Replace `FULL_DRAFT_ID` in these commands with that value:

```sh
ableton kb review FULL_DRAFT_ID
```

Review the source page and each technique draft. Compare every generated claim with its cited evidence.
If a draft needs changes, edit the file at the printed path with your text editor.

After review, publish:

```sh
ableton kb publish FULL_DRAFT_ID
```

Approve the publication prompt.

**Success:** publication prints the source page path. This command then prints `[]`:

```sh
ableton kb lint
```

## 7. Use your knowledge

Run:

```sh
ableton chat
```

Ask about a technique from the tutorial. Request a source reference.

**Success:** the answer cites published knowledge and keeps tutorial advice separate from facts observed in Live.

Next: [add more sources, search, and export your library](knowledge-base.md).
For installation recovery, see [backups and rollback](recovery.md).
