# Local video transcription

This tool transcribes local audio and video files in English. Media stays on the machine.
It supports three local inference backends:

| Backend | Engine | Default model |
| --- | --- | --- |
| Apple Silicon Metal | whisper.cpp v1.8.3 | large-v3-turbo (`turbo`) |
| CPU | whisper.cpp v1.8.3 | `base.en` |
| NVIDIA CUDA | faster-whisper | large-v3-turbo (`turbo`) |

`auto` selects Metal on Apple Silicon, then CUDA on other systems with an available CUDA device.
Otherwise, it selects CPU. If GPU initialization or inference fails, `auto` retries once on CPU with `base.en`.
The tool reports the fallback. Explicit `metal`, `cuda`, and `cpu` selections never switch backends.
Model download and checksum errors stop the command rather than trigger another download through a fallback.

## Install Metal or CPU inference

Requirements: Python 3.11–3.13, FFmpeg, and whisper.cpp v1.8.3.
Source builds also require Git, CMake, and a C/C++ compiler.
Metal requires an Apple Silicon Mac and a working Metal runtime.
CPU inference does not require a GPU or CUDA libraries.

On macOS, install the build dependencies:

```bash
brew install cmake ffmpeg
xcode-select --install
```

If Xcode reports a missing Metal Toolchain, install the component:

```bash
xcodebuild -downloadComponent MetalToolchain
```

On Ubuntu or Debian, install the build dependencies:

```bash
sudo apt update
sudo apt install build-essential cmake git ffmpeg
```

Clone the pinned whisper.cpp release outside this repository:

```bash
git clone --depth 1 --branch v1.8.3 https://github.com/ggml-org/whisper.cpp.git ~/whisper.cpp
```

For Apple Silicon, build with Metal:

```bash
cmake -S ~/whisper.cpp -B ~/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON
cmake --build ~/whisper.cpp/build --config Release --target whisper-cli -j 4
```

For CPU-only systems, build without GPU backends:

```bash
cmake -S ~/whisper.cpp -B ~/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=OFF -DGGML_CUDA=OFF -DGGML_VULKAN=OFF
cmake --build ~/whisper.cpp/build --config Release --target whisper-cli -j 4
```

Keep the build directory intact. Its executable depends on libraries in that directory.
Expose the executable through the environment:

```bash
export WHISPER_CPP_BINARY="$HOME/whisper.cpp/build/bin/whisper-cli"
```

Alternatively, put `whisper-cli` on `PATH`, or pass `--whisper-cli /path/to/whisper-cli`.
Windows builds require the equivalent CMake toolchain and an executable path to `whisper-cli.exe`.
Native Windows and Linux builds remain unverified in this workspace.

From the repository root, install the Python environment:

```bash
uv sync --project tools/transcribe --locked
```

## Commands

From the repository root, run:

```bash
uv run --project tools/transcribe --locked video-transcribe ./video.mp4 --output-dir ./transcripts
uv run --project tools/transcribe --locked video-transcribe ./video.mp4 --backend metal
uv run --project tools/transcribe --locked video-transcribe ./video.mp4 --backend cpu
```

The CPU default is `base.en` (approximately 148 MB). `tiny.en` uses approximately 78 MB but offers lower accuracy.
`small.en` uses approximately 488 MB. The Metal default, `turbo`, uses approximately 1.63 GB for model weights.
Runtime memory use exceeds model file size.

To select a smaller fallback model, run:

```bash
uv run --project tools/transcribe --locked video-transcribe ./video.mp4 --cpu-model tiny.en
```

`--model` selects the primary model. `--cpu-model` selects the CPU default and the model after a GPU failure.
For example, `--backend metal --model base.en` uses Metal with `base.en` and disables automatic fallback.
`--threads` controls whisper.cpp CPU threads and defaults to four.
`--compute-type` applies only to CUDA.

The first use downloads model weights. whisper.cpp downloads use an immutable Hugging Face revision and SHA-256 verification.
Downloads use temporary files and atomic replacement. Interrupted downloads do not become cached models.
Cached models also receive a checksum check before use. Corrupt cached models require removal before retry.
The tool never uploads media or uses a hosted transcription service.

To select a persistent model directory, add:

```bash
--cache-dir /path/to/model-cache
```

The whisper.cpp default is `~/.cache/video-transcribe`. CUDA uses the faster-whisper cache unless `--cache-dir` specifies another directory.

## Install NVIDIA CUDA inference

The existing CUDA path targets x86-64 Linux or WSL2 with a compatible NVIDIA driver.
Install FFmpeg through your system package manager. Then, from the repository root, run:

```bash
uv sync --project tools/transcribe --locked --extra cuda
```

The extra installs faster-whisper, CTranslate2, cuBLAS for CUDA 12, and cuDNN 9.
It does not install a GPU driver.
On Linux or WSL2, expose the bundled CUDA libraries before Python starts:

```bash
export LD_LIBRARY_PATH="$(uv run --project tools/transcribe --extra cuda python -c 'import pathlib, nvidia.cublas, nvidia.cudnn; print(":".join(str(pathlib.Path(next(iter(m.__path__))) / "lib") for m in (nvidia.cublas, nvidia.cudnn)))')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
nvidia-smi
uv run --project tools/transcribe --extra cuda video-transcribe ./video.mp4 --backend cuda
```

For lower GPU memory use, add `--compute-type int8_float16`.
Explicit CUDA errors stop the command. In `auto` mode, GPU errors trigger the smaller CPU fallback.
CPU fallback still requires a whisper.cpp executable.

## Python API and resource ownership

```python
from video_transcribe import Transcriber

with Transcriber(backend="auto", cpu_model="base.en") as transcriber:
    result = transcriber.transcribe("/path/to/video.mp4")
    result.write("/path/to/transcripts")
```

`transcribe()` initializes the backend if necessary. CUDA loads one model per context and reuses it across files.
whisper.cpp runs one subprocess per file and releases model memory when that process exits.
`close()` is safe to call more than once. Do not share a `Transcriber` across threads or fork after CUDA initialization.

## Output contract

For `video.mp4`, the tool writes `video.mp4.txt` and `video.mp4.json`.
Existing outputs with those names are replaced. Use separate output directories for sources with identical filenames.

JSON preserves schema version 1 and the existing fields:

- `source`: absolute input path.
- `model`: actual model name, including the smaller model after fallback.
- `language`: `en`.
- `duration`: decoded audio duration in seconds.
- `text`: complete transcript.
- `segments`: objects with `id`, `start`, `end`, and `text`.

Additional metadata records `backend`, `compute_type`, and `threads`.
For whisper.cpp, `compute_type` is `f16-weights`; runtime operations use backend-dependent precision.
For CUDA, it records the requested CTranslate2 compute type. CUDA sets `threads` to null.
Existing ingestion tools accept the additional fields.

FFmpeg extracts the first audio stream into temporary mono, 16 kHz PCM WAV audio.
Temporary audio is removed after success or failure. `TMPDIR` selects its parent directory.
Temporary disk use is approximately 115 MB per hour.

Timestamps use seconds from the start of decoded audio. whisper.cpp millisecond offsets convert to seconds without removing silence.
CUDA uses VAD and restores timestamps to the original timeline. whisper.cpp does not enable VAD or require another model download.
Backends can produce different text, segment boundaries, and accuracy. Neither path supplies speaker labels or translation.

## Tests

Unit tests require neither a GPU nor model downloads:

```bash
uv run --project tools/transcribe --locked --group dev pytest tools/transcribe/tests
```

For opt-in real inference tests, supply a local English speech recording and a whisper.cpp executable:

```bash
WHISPER_CPP_TEST_AUDIO=/path/to/speech.wav WHISPER_CPP_BINARY="$HOME/whisper.cpp/build/bin/whisper-cli" \
  uv run --project tools/transcribe --locked --group dev pytest tools/transcribe/tests/test_real_inference.py -v
```

These tests download `base.en` if necessary. They run CPU inference and, on Apple Silicon, Metal inference.
Real Metal (`turbo` and `base.en`) and CPU (`base.en`) inference passed on the workspace's Apple M1.
CUDA inference was not reverified on this machine.
