# ytkit

`ytkit` extracts YouTube transcript-panel rows with a bounded browser session and
writes validated, structured results. Chrome is required. The only supported
browser backend is `undetected-chromedriver`.

## Install and run

```sh
uv sync --locked
uv run --locked ytkit VIDEO_ID --format md --out talk.md
uv run --locked python -m ytkit VIDEO_ID --format json
```

Use `--raw` for the source segments. `--control` adds a diagnostic control
video; it does not prove that another video has captions.

## Result contract

The Python API returns `FetchResult`, not a bare segment list. Results have
`success`, `unavailable`, `blocked`, or `failed` status. Successful transcripts
contain schema version, source URL, retrieval time, language, track type, and
segments. Segment end times are nullable; no pause or duration is invented.
Unsuccessful results include an error code, extraction stage, diagnostic, and
retry classification. JSON output is always one array, including one-video
runs.

```python
from ytkit import fetch
result = fetch("dQw4w9WgXcQ")
if result.status == "success":
    print(result.transcript.segments)
```

`paragraphs()` is a presentation helper. Use `kb_chunks()` for bounded
retrieval chunks. Chunking never changes canonical transcript text and supports
unpunctuated captions.

## Storage and exit codes

`ytkit.store.save_transcript()` writes canonical JSON atomically. Failed refreshes
must not replace a valid transcript. CLI exits `0` for all success, `1` for no
success, `3` for partial success, and `2` for argument errors.

## Development

```sh
uv sync --locked
uv run --locked pytest -q
```

Live browser checks are opt-in and require Chrome. Headed mode is the default;
use an explicit headless option in code and a dedicated profile directory when
needed. Do not use a personal Chrome profile. Chrome and its driver binary are
external to the Python lockfile.

MIT. See `LICENSE`.
