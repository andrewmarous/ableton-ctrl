# Implementation plan

## 1. Migrate to uv-managed dependencies

**Goal:** A clean checkout installs reproducibly through `uv`. The scraper always uses `undetected-chromedriver`.

### Changes

- Add `pyproject.toml` with package metadata, an explicit build backend, and the `ytkit` console entry point.
- Declare `selenium` and `undetected-chromedriver` as required runtime dependencies.
- Add `pytest` to the development dependency group.
- Select Python 3.12 as the initial supported minor version. Record it in `.python-version` and constrain `requires-python` accordingly.
- Expand Python support only after installation and browser smoke tests pass on each additional version.
- Generate and commit `uv.lock`.
- Ignore `.venv/`, build outputs, diagnostic artifacts, and local transcript data.
- Remove `requirements.txt` after the clean-install checks pass.
- Replace pip instructions in `README.md` with `uv sync --locked` and `uv run` commands.

### undetected-chromedriver compatibility

Some releases import `distutils`, which Python 3.12 no longer includes. A successful dependency resolution does not prove runtime compatibility.

- Inspect the selected release for runtime imports of `distutils` and other undeclared dependencies.
- If required, declare a compatible `setuptools` release as a runtime dependency to supply `distutils`.
- Constrain that dependency to a tested range that retains the required compatibility module.
- Do not rely on setuptools from a global installation or an isolated build environment.
- Verify that uv can build the selected source distribution with build isolation enabled.
- If build dependencies are missing, declare package-specific uv build dependencies rather than disabling isolation globally.
- Record the reason for each compatibility constraint in `pyproject.toml`.
- Do not patch installed packages, inject fake modules, or fall back to plain Selenium.

Chrome remains an external runtime prerequisite. The Python lockfile does not lock Chrome or the downloaded driver binary.

### Acceptance criteria

From a clean environment, these commands succeed:

```sh
uv sync --locked
uv run --locked python -c "import undetected_chromedriver; import ytkit"
uv run --locked python -m ytkit --help
uv run --locked ytkit --help
uv run --locked pytest -q
```

Also verify imports with `uv sync --locked --no-dev` in a separate clean environment. Development dependencies must not hide missing runtime dependencies.

An opt-in smoke test launches Chrome through `undetected-chromedriver`, opens a local test page, and closes the browser. Record Python, Chrome, driver, Selenium, and `undetected-chromedriver` versions.

## 2. Define the transcript and result contracts

**Goal:** Distinguish missing captions from extraction errors without adding a large framework.

**Files:** Add `ytkit/models.py`. Update `ytkit/fetch.py`, `ytkit/cli.py`, and public exports.

### Changes

- Use small dataclasses and explicit status values.
- Define a transcript record with schema version, video ID, source URL, retrieval time, language, track type, and segments.
- Preserve unknown metadata as null rather than guessing.
- Give each segment a finite, nonnegative start time and nonempty text.
- Permit an unknown end time. Record whether an available end time is source-provided or estimated.
- Define statuses for success, confirmed unavailable, blocked, and extraction failure.
- Include an error code, extraction stage, diagnostic message, and retry classification in unsuccessful results.
- Track completeness separately as verified, unknown, or partial.
- Accept only complete, validated results into the default KB ingestion path.
- Document the public API change from bare segment lists to structured results.

### Acceptance criteria

- Missing buttons do not become confirmed unavailable results.
- Invalid timestamps, reversed ranges, and malformed rows produce explicit validation errors.
- Serialization round-trips preserve status, metadata, timing provenance, and text.
- Every requested video receives a result, including unsuccessful videos.

## 3. Correct timing and replace pause-dependent KB chunking

**Goal:** Produce bounded KB chunks without invented pauses or punctuation requirements.

**Files:** Update `ytkit/fetch.py` and `ytkit/organize.py`. Add regression tests.

### Changes

- First add a regression test for the current fetch-to-paragraph mismatch.
- Remove the unconditional next-start assignment as a factual segment end.
- Remove the invented four-second final duration.
- Preserve real durations only when the source provides them.
- Keep paragraph formatting separate from KB chunking.
- Split KB chunks with explicit word-count and time-span limits.
- Prefer sentence boundaries within those limits, but support text without punctuation.
- Split oversized individual segments without inventing more precise timestamps.
- Preserve source segment references and timestamp links in every chunk.
- Keep canonical transcript text unchanged by formatting or chunking.
- Retain pause-based paragraph breaks only when real timing data supports them.

### Acceptance criteria

- Fetch-shaped inputs no longer silently collapse into one unbounded KB chunk.
- Punctuated and unpunctuated transcripts produce bounded chunks.
- Every source text span appears in order without accidental omission or duplication.
- Unknown final end times remain unknown in storage and exports.

## 4. Make browser ownership explicit

**Goal:** One required backend, one lifecycle, and actionable startup errors.

**Files:** Update `ytkit/driver.py` and `ytkit/fetch.py`.

### Changes

- Remove the optional import and plain-Selenium fallback.
- Centralize `undetected_chromedriver.Chrome` construction and browser cleanup.
- Use a context manager for owned browser sessions.
- Preserve caller ownership when a caller supplies a driver.
- Keep headed mode as the initial default. Expose headless mode and a dedicated profile directory explicitly.
- Do not reuse a personal Chrome profile by default.
- Inspect the selected backend's subprocess hooks before replacing Windows console suppression.
- Prefer supported per-process configuration over global `subprocess.Popen` replacement.
- If upstream lacks a necessary hook, isolate the workaround in one documented adapter with Windows tests.
- Remove nested global subprocess patches.
- Report startup failures with browser and package versions, without exposing profile secrets.

### Acceptance criteria

- Startup errors never trigger a different backend.
- Owned browsers close after success, failure, and interruption.
- Caller-supplied browsers remain open.
- Windows tests cover console behavior if Windows remains a supported platform.

## 5. Bound extraction and establish completeness

**Goal:** Replace timing guesses with observable conditions and a finite extraction budget.

**Files:** Update `ytkit/fetch.py`. Add local DOM fixtures and browser tests.

### Changes

- Extract pure timestamp and row parsing from browser operations.
- Reject invalid input IDs before browser startup. Accept normalized YouTube URLs only through an explicit parser.
- Replace fixed sleeps with condition-based waits.
- Apply one configurable per-video deadline across navigation, panel discovery, and row collection.
- Bound page-load and script timeouts by the remaining deadline.
- Search selector alternatives within a shared wait instead of assigning each a full timeout.
- Scope selectors to the description and transcript panel.
- Catch expected Selenium exceptions only. Preserve unexpected programming errors.
- Detect explicit consent, unavailable-video, and blocking states where the page exposes them.
- Record the selected language and track. Do not silently substitute another language.
- Inspect live panel behavior to establish whether transcript rows are virtualized.
- If rows are virtualized, scroll and accumulate rows using stable identity that preserves repeated text.
- Use terminal scroll state and stable collection as evidence, not a minimum row count alone.
- Mark extraction as incomplete when the deadline expires before completion evidence appears.
- Add opt-in HTML and screenshot diagnostics with documented retention and privacy limits.

### Acceptance criteria

- Fixtures cover delayed content, missing buttons, stale elements, localized controls, empty panels, and virtualized rows.
- A short transcript with fewer than six segments succeeds.
- A long transcript includes its final segment without duplicate rows.
- A stuck panel returns an explicit failure within the configured budget.
- Live smoke tests distinguish observed site behavior from assumptions in fixtures.

## 6. Add durable, sequential batch ingestion

**Goal:** Preserve completed work and resume safely after failures.

**Files:** Add `ytkit/store.py`. Update batch orchestration in `ytkit/fetch.py` and `ytkit/cli.py`.

### Changes

- Keep one sequential worker and reuse one browser session.
- Deduplicate requested video IDs while preserving their order.
- Save each validated transcript immediately to a canonical JSON file.
- Key stored transcripts by video ID and track selection.
- Write temporary files beside their destinations, then replace destinations atomically.
- Store failed attempts separately from successful transcripts.
- Never replace a valid transcript with an unsuccessful refresh.
- Resume by skipping valid records with matching schema and track selection.
- Add an explicit refresh option.
- Retry transient failures at most twice with bounded exponential backoff and jitter.
- Restart a dead browser within that same retry budget.
- Do not retry confirmed unavailable results.
- On explicit blocking, stop the batch and record remaining items as deferred.
- Do not introduce proxy rotation or automatic blocking bypasses.
- Treat the control video as diagnostic evidence, not proof of availability or session health.

### Acceptance criteria

- A failure on the third video preserves the first two records.
- A resumed run does not fetch completed videos again.
- An interrupted write leaves the previous valid record intact.
- Tests verify retry counts, browser restarts, blocking behavior, and failed refreshes.

## 7. Repair CLI output and exit behavior

**Goal:** Stable machine-readable output and truthful process status.

**Files:** Update `ytkit/cli.py` and add CLI tests.

### Changes

- Emit one JSON array for `--format json`, including single-video runs.
- Include structured failure results in JSON output.
- Keep logs and progress on stderr.
- Preserve requested results when a control ID also appears in the input list.
- Derive Markdown and plain text from canonical transcript records.
- Replace explicit output files atomically only after successful serialization.
- Do not replace an existing export when no requested video succeeds.
- Document partial exports and include their failures in the batch summary.
- Return `0` when all requested videos succeed.
- Return `1` when no requested video succeeds.
- Reserve `2` for argument errors.
- Return `3` for partial success, including deferred items.
- Report control failures separately without discarding successful requested transcripts.

### Acceptance criteria

- Standard JSON parsers accept single-video and multi-video output.
- Tests cover duplicate IDs, control overlap, total failure, partial success, and unwritable output paths.
- No routine extraction failure produces a traceback without an actionable summary.
- Existing valid exports survive failed runs.

## 8. Add repeatable verification and update documentation

**Goal:** Fast offline checks plus a small, explicit live compatibility check.

### Changes

- Run offline tests through `uv sync --locked` and `uv run --locked pytest` in CI.
- Add clean-install import tests without development dependencies.
- Separate pure parser tests, orchestration tests, local browser tests, and live YouTube smoke tests.
- Inject the driver factory, clock, and sleep function where tests need deterministic behavior.
- Keep live tests opt-in and low-volume.
- Include short, long, unpunctuated, and unavailable-video cases in the live test checklist.
- Record exact browser versions and extraction diagnostics for live failures.
- Replace unsupported README claims about speed, throttling immunity, and control-video certainty.
- Document Chrome prerequisites, uv commands, output schema, exit codes, resume behavior, and compatibility limits.
- Document the public API and JSON format changes with migration examples.

### Release gate

- All offline tests pass from a clean locked installation.
- The no-development-dependencies import test passes.
- The required backend launches and closes on each claimed platform.
- Live smoke tests demonstrate full collection for a long transcript.
- A forced interruption and resume preserve completed work.
- Failed refreshes never destroy successful transcript records.

## Delivery order and scope

Implement sections 1 through 8 as small, reviewable commits. Add regression tests with each behavior change, not only in the final section.

The initial design remains:

```text
video IDs -> fetch -> validate -> save canonical JSON -> chunk/export
```

Exclude concurrent browser pools, queue services, databases, alternate scraper backends, audio transcription, and LLM-based formatting from this work.

This document is a plan. Dependency constraints, backend compatibility, and live extraction behavior still require implementation-time verification.
