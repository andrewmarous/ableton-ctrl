# Development and distribution

For normal installation, use [Getting started](getting-started.md).
This page covers source installation, wheel builds, and release preparation.

## Install from source

Use this path when no trusted release wheel is available.
Install the prerequisites from [Getting started](getting-started.md#1-install-prerequisites) first.

```sh
git clone https://github.com/andrewmarous/ableton-ctrl.git
cd ableton-ctrl
uv tool install --python 3.13 .
ableton --help
```

This installs the current checkout as a tool. It does not start setup or connect to Live.
Return to [guided setup](getting-started.md#3-run-guided-setup) after the help command succeeds.

For repository development, use `uv run ableton ...` instead of the installed command.
Changes in the checkout do not update a previous tool installation automatically.
To update that installation from the checkout, run:

```sh
uv tool install --python 3.13 --reinstall .
```

## Run tests and build

From the repository root, run:

```sh
uv run pytest
uv run pytest tools/transcribe/tests
uv run ruff check src/ableton_ctrl tools/transcribe/src
uv run mypy src/ableton_ctrl
uv build
```

`uv build` creates a source archive and a wheel under `dist/`.
The wheel includes the application, video ingestion, and local transcription modules.
It does not include FFmpeg, Git, CMake, a compiler, Pi, or a compiled whisper.cpp build.

## Verify the wheel outside the checkout

1. Create a fresh environment:

   ```sh
   uv venv --python 3.13 /tmp/ableton-wheel-test
   ```

2. Install the wheel with an absolute path:

   ```sh
   uv pip install --python /tmp/ableton-wheel-test/bin/python /absolute/path/to/dist/ableton_ctrl-0.1.0-py3-none-any.whl
   ```

3. Leave the repository:

   ```sh
   cd /tmp
   ```

4. Verify the installed command:

   ```sh
   /tmp/ableton-wheel-test/bin/ableton --help
   ```

Use a fresh macOS test account for full setup tests. Do not point test setup at personal production knowledge.

## Prepare a public release

The package is not on PyPI. A built local wheel is not a published release.

Before release:

- Verify the package version and the project metadata URLs.
- Run the tests and the isolated wheel installation.
- Follow [Getting started](getting-started.md) from a clean test account.
- Verify source ingestion, technique review, publication, and export/import.
- Exercise installer failure recovery and explicit rollback.
- Verify the Live connection through inspection only.
- Record the tested operating system, Live version, and transcription backend.

For the Live acceptance procedure, see the [integration reference](upstream-integration.md#live-acceptance-test).
Compilation smoke tests alone do not prove transcription quality.
Mocked synthesis tests do not prove model output quality.

After verification, create a versioned [GitHub release](https://github.com/andrewmarous/ableton-ctrl/releases).
Attach the wheel and source archive. Include SHA-256 checksums and the tested-platform information.
Then verify the download link and installation command in the getting-started guide.

Do not document a PyPI command until a matching package is published there.

## Optional CUDA dependencies

For an appropriate NVIDIA environment, install the wheel's extra:

```sh
uv tool install --python 3.13 '/path/to/ableton_ctrl-0.1.0-py3-none-any.whl[cuda]'
```

The extra does not install an NVIDIA driver.
See the [transcription reference](../tools/transcribe/README.md) for CUDA requirements.

## Maintainer references

- [Integration](upstream-integration.md): pinned upstream package and managed files.
- [Recovery](recovery.md): transaction behavior and restore limits.
- [Video ingestion prototype plan](video-ingestion-prototype-plan.md): historical prototype scope, not current user instructions.
- [Cleanup implementation plan](cleanup-implementation-plan.md): historical retirement plan, not current user instructions.
