# Local video transcription

This standalone development tool uses faster-whisper with the Whisper large-v3-turbo model (`turbo`).
It accepts local audio and video files. It does not download videos or run a server.
The main application has no dependency on this package.

## WSL installation

Requirements: x86-64 WSL2, Python 3.11–3.13, and a CUDA-capable Windows NVIDIA driver.
GPU access must work inside WSL. The commands assume Ubuntu or Debian.

From the repository root, run:

```bash
cd tools/transcribe
sudo apt update
sudo apt install ffmpeg python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[cuda]'
```

The `cuda` extra installs cuBLAS for CUDA 12 and cuDNN 9 into the Python environment.
It does not install a GPU driver. An existing CUDA toolkit alone does not guarantee these libraries are available.

Before each session, activate the environment and set the library path:

```bash
source .venv/bin/activate
export LD_LIBRARY_PATH="$(python -c 'import pathlib, nvidia.cublas, nvidia.cudnn; print(":".join(str(pathlib.Path(next(iter(m.__path__))) / "lib") for m in (nvidia.cublas, nvidia.cudnn)))')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
nvidia-smi
python -c 'import ctranslate2; print(ctranslate2.get_supported_compute_types("cuda"))'
```

Set `LD_LIBRARY_PATH` before Python starts, including for the future scraper process.
If compatible CUDA libraries already exist on the system library path, install with `pip install -e .` instead.

## CLI

```bash
video-transcribe /path/to/video.mp4 --output-dir ./transcripts
video-transcribe /path/to/audio.mp3 --output-dir ./transcripts
```

The first run downloads converted turbo weights from Hugging Face. Later runs reuse the cache.
Media stays on the machine. The tool uses no remote transcription service.

To select a persistent cache directory, run:

```bash
video-transcribe /path/to/video.mp4 --cache-dir ~/.cache/video-transcribe
```

The default precision is `float16`, with one file at a time and no batched inference.
Actual VRAM use depends on inference allocations and other GPU processes, not only model weights.
An 8 GB GPU is the target, but this repository does not yet contain measurements from that hardware.

If CUDA reports insufficient memory, close other GPU workloads or use:

```bash
video-transcribe /path/to/video.mp4 --compute-type int8_float16
```

There is no automatic CPU fallback. CUDA errors stop the command.

## Scraper integration

Install this package into the future scraper's Python environment.
Use one context for the entire scraping and transcription job:

```python
from video_transcribe import Transcriber

with Transcriber(cache_dir="/home/me/.cache/video-transcribe") as transcriber:
    # The future scraper supplies local paths here.
    for local_path in ["/data/first.mp4", "/data/second.mp3"]:
        transcript = transcriber.transcribe(local_path)
        transcript.write("/data/transcripts")
```

The context loads the model once and unloads its weights on exit, including after an exception.
For manual lifecycle control, use `load()` and `close()` with `try/finally`.
`transcribe()` also loads the model if necessary. `close()` is safe to call more than once.
Do not share one instance across concurrent calls or fork a process after CUDA initialization.
CTranslate2 can retain runtime allocations until the process exits.

## Outputs and audio handling

For `video.mp4`, the tool writes `video.mp4.txt` and `video.mp4.json` into the output directory.
Existing outputs with these names are replaced. Use separate output directories for sources with identical filenames.

The JSON contains:

- `schema_version`: currently `1`.
- `source`: the absolute input path.
- `model`: `turbo`.
- `language`: `en`.
- `duration`: the decoded audio duration in seconds, before silence removal.
- `text`: the complete transcript.
- `segments`: objects with `id`, `start`, `end`, and `text`.

Segment times use seconds from the start of the decoded audio, not a container timecode.
Voice activity detection skips silence. Faster-whisper restores segment timestamps to the original audio timeline.
The tool does not provide word timestamps, speaker labels, or translation.

FFmpeg extracts the first audio stream into a temporary mono, 16 kHz PCM WAV file.
The temporary file is removed after transcription, including after an exception.
A file without an audio stream produces an error.
Temporary disk use is approximately 115 MB per hour. Faster-whisper also decodes the audio into RAM.
For very long recordings, RAM use increases with duration. Set `TMPDIR` to select another temporary disk.

## Tests

The unit tests use a fake inference backend. They require neither a GPU nor model weights.

```bash
python -m pip install pytest
python -m pytest
```

For a GPU smoke test, transcribe a short English recording with the CLI.
Compare the text and segment timestamps against the recording.
Use `nvidia-smi` during the run to observe GPU memory use.

Upstream references:

- [faster-whisper requirements and usage](https://github.com/SYSTRAN/faster-whisper)
- [CTranslate2 model lifecycle](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html)
