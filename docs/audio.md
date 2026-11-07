# Audio capture and inspection

`ableton-audio` records an audio input and inspects audio files locally.
It does not require Ableton for file inspection.
It does not control Live playback, solo states, or routing.

## Install

From a source checkout, run:

```sh
uv sync --extra audio
uv run ableton-audio --help
```

For a wheel installation, include the `audio` extra in your package installer.
The extra includes NumPy, SciPy, SoundFile, sounddevice, Matplotlib, and pyloudnorm.
On systems without bundled PortAudio, install PortAudio through your system package manager.

## Configure capture on the laptop

1. Install a loopback device, such as BlackHole 2ch on macOS.
2. In Audio MIDI Setup, create a Multi-Output Device with BlackHole and your listening output.
3. Use the same sample rate for both devices. Configure drift correction for the secondary device.
4. In Live, select that Multi-Output Device as the audio output.
5. Route Live's master output to channels 1/2.
6. List the available inputs:

```sh
uv run ableton-audio devices
```

7. Set the loopback input name:

```sh
export ABLETON_AUDIO_DEVICE='BlackHole 2ch'
```

If macOS requests microphone access for the terminal, allow access.
An input device ID also works with `--device`. IDs can change when devices reconnect.
Capture requires an explicit input. It never falls back to the default microphone.

## Capture

```sh
uv run ableton-audio capture --seconds 8
# Explicit device and sample rate:
uv run ableton-audio capture --device 'BlackHole 2ch' --seconds 8 --sample-rate 48000
```

The command records immediately and blocks until completion.
It prints a readiness message to stderr after the input stream opens.
It returns JSON on stdout with the WAV path, source device, duration, channels, and sample rate.
Capture supports mono or stereo, with a maximum duration of 300 seconds.
An input overflow fails the capture instead of returning an incomplete recording.

To capture a passage from its beginning, start capture in a background terminal job before playback.
Wait for the readiness message, then start Live through the existing Ableton tools.
Allow extra capture time for the playback delay and effect tails.
The resulting file includes that leading silence; capture is not synchronized to Live's transport.

Existing Ableton tools select the passage and control playback and solo states.
A soloed track still includes the sends, returns, and master processing that reach the selected output.
The recorder cannot identify tracks or remove other audio routed to the same loopback device.

## Inspect

```sh
uv run ableton-audio inspect /absolute/path/to/capture.wav
```

The command returns JSON and saves a PNG with a waveform, spectrogram, and average spectrum.
Read the JSON for measurements. Open the PNG with the agent's image-reading tool for visual inspection.
The output includes:

- Sample peak and RMS in dBFS.
- Integrated loudness in LUFS, with BS.1770 frequency weighting and gating.
- Stereo correlation, when both channels have nonzero variance.
- A count of samples at or above full scale.
- Source metadata and absolute artifact paths.

The full-scale count indicates possible clipping. It does not prove that distortion occurred.
Peak measurement uses samples, not reconstructed true peaks.
Null dB values indicate silence. Null loudness indicates silence, a gated signal, or a file shorter than 400 milliseconds.
Spectrum views average channel power, so opposite-polarity stereo signals do not disappear through mono cancellation.
File inspection accepts mono or stereo formats supported by libsndfile, up to 300 seconds.
Plots and measurements do not give a text/image model direct audio hearing.

Artifacts default to `artifacts/audio` under the current directory.
Set `ABLETON_AUDIO_DIR` to select another directory. Files use unique names and remain until you remove them.
No audio leaves the computer through these commands.
Errors go to stderr and return a nonzero exit status.

## Laptop verification

- Run `devices` and check that BlackHole appears with two input channels.
- Play a passage in Live, capture eight seconds, and inspect the WAV.
- Check that the recording contains the expected sound and both channels.
- Solo one track and repeat. Check that the new recording contains the expected track and effects.
- Stop Live and capture again. Check that the recording contains silence or expected effect tails.
- Start capture before playback. Check that the first transient and final effect tail are present.
- Restore the desired solo states after the test.

Automated tests use synthetic files and a simulated input stream.
Real loopback routing, macOS permissions, and Live playback require verification on the laptop.
