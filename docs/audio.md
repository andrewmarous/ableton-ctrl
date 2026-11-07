# Audio capture and inspection

`ableton audio` records a loopback input and inspects audio files locally through FFmpeg.
`ableton-audio` remains an equivalent standalone command.
It does not control Live playback, solo states, or routing.
File inspection does not require Ableton.

## Install

Install FFmpeg, then install this package through the normal wheel or source procedure:

```sh
brew install ffmpeg
# From a source checkout:
uv sync
uv run ableton audio --help
```

Normal package installation includes the audio commands. No Python audio extra is required.
`ableton setup` checks FFmpeg and installs audio guidance in the Pi skill.
Setup stops before changes if the required tools or filters are missing.
`ableton doctor` includes audio diagnostics, even when Live diagnostics succeed.
Knowledge-only setup does not require FFmpeg.
Capture uses FFmpeg's macOS AVFoundation input.
Inspection uses `ffprobe`, `astats`, `ebur128`, `showwavespic`, and `showspectrumpic`.
Our wrapper selects inputs, runs those tools, and returns artifacts. It does not implement audio DSP.

## Configure capture on the laptop

1. Install a loopback device, such as BlackHole 2ch on macOS.
2. In Audio MIDI Setup, create a Multi-Output Device with BlackHole and your listening output.
3. Use the same sample rate for both devices.
4. Configure drift correction for the secondary device.
5. In Live, select that Multi-Output Device as the audio output.
6. Route Live's master output to channels 1/2.
7. List the available inputs:

```sh
ableton audio devices
```

8. Save the loopback input name through normal plugin setup:

```sh
ableton setup --audio-device 'BlackHole 2ch'
ableton audio doctor
```

Setup saves the input in `~/.config/ableton-ctrl/config.json` and preserves it during later setup runs.
The selected input applies to both command names and to the installed agent skill.
The skill uses the installed Python environment, independent of Pi's shell PATH.
Reload Pi after setup to load the new skill guidance.

For a temporary override, set `ABLETON_AUDIO_DEVICE` or pass `--device`.
The selection order is `--device`, then the environment variable, then the saved input.
`doctor` checks tools and reports the selected input without opening a device or starting playback.
A missing input does not prevent file inspection or plugin installation.

If macOS requests microphone access for the terminal, allow access.
An AVFoundation audio device ID also works with `--device`. IDs can change when devices reconnect.
Capture requires an explicit input. It never falls back to the default microphone.
Live capture currently supports macOS only. File inspection works wherever FFmpeg supplies the required filters.

## Capture

```sh
ableton audio capture --seconds 8
# Explicit device and sample rate:
ableton audio capture --device 'BlackHole 2ch' --seconds 8 --sample-rate 48000
```

The command opens the input and records for the specified duration.
It blocks until completion. Device initialization adds time before capture begins.
It returns JSON with the WAV path, source device, duration, channels, and sample rate.
Capture supports mono or stereo, with a maximum duration of 300 seconds.
FFmpeg errors, timeouts, and incomplete recordings fail the command. Partial artifacts are removed.

For an excerpt of ongoing playback, start Live first, then capture.
To include a passage's beginning, start capture in a background job before playback.
Allow time for input initialization and extra recording time for effect tails.
The opening message is not a readiness signal. Capture is not synchronized to Live's transport.
Verify the recording before conclusions about a first transient or exact passage boundary.

Existing Ableton tools select the passage and control playback and solo states.
A soloed track still includes the sends, returns, and master processing that reach the selected output.
The recorder cannot identify tracks or remove other audio routed to the same loopback device.

## Inspect

```sh
ableton audio inspect /absolute/path/to/capture.wav
```

The command returns JSON with measurements, a waveform PNG, and a spectrogram PNG.
Open both paths in `images` with the agent's image-reading tool.
FFmpeg draws each channel separately, so opposite-polarity stereo channels remain visible.
The spectrogram includes frequency and time axes.

Measurements include:

- Sample peak and RMS in dBFS, from `astats`.
- Integrated loudness in LUFS, from `ebur128`.
- Oversampled true peak in dBFS, from `ebur128=peak=true`.
- A possible-clipping flag when sample peak reaches full scale.

Possible clipping does not prove that distortion occurred.
Null dB values indicate silence. Null loudness indicates silence, a gated signal, or audio shorter than 400 milliseconds.
Loudness and true-peak summaries use FFmpeg's reported precision, usually one decimal place.
The raw FFmpeg measurement log is saved alongside the JSON report.

Inspection accepts local mono or stereo files with a known duration of at most 300 seconds.
FFmpeg supplies format support. The first audio stream is selected.
Plots and measurements do not give a text/image model direct audio hearing.

Artifacts default to `artifacts/audio` under the current directory.
Set `ABLETON_AUDIO_DIR` to select another directory. Unique filenames prevent replacement of earlier captures.
Files remain until you remove them. These commands do not upload audio.
Errors go to stderr and return a nonzero exit status.

## Laptop verification

- Run `devices` and verify that BlackHole appears with two input channels in Audio MIDI Setup.
- Play a passage in Live, capture eight seconds, and inspect the WAV.
- Verify that the recording contains the expected sound and both channels.
- Solo one track and repeat. Verify that the recording contains the expected track and effects.
- Stop Live and capture again. Verify that the recording contains silence or expected effect tails.
- Start capture before playback. Verify that the first transient and final effect tail are present.
- Restore the desired solo states after the test.

Automated tests exercise real FFmpeg with synthetic files and simulate AVFoundation capture commands.
Real loopback routing, macOS permissions, and Live playback require verification on the laptop.

## Changes from the first implementation

FFmpeg replaces the optional Python audio stack. The `audio` package extra was removed.
Inspection now returns two native FFmpeg images instead of one custom plot.
The original stereo-correlation measurement and full-scale sample count are no longer returned.
The possible-clipping flag is a peak-level indicator, not a count.
