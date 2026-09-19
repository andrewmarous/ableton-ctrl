# Repository Cleanup Implementation Plan

## Purpose

This plan turns the repository into a user-facing Ableton inspection tool. It covers installation, documentation, knowledge-base management, and internal cleanup.

The work has four phases. Each phase must leave the repository usable and tested.

## Product boundaries

The project contains three related parts:

1. **Ableton inspection:** The Remote Script, local bridge, and command-line interface.
2. **Pi integration:** The Pi extension, controller, skill, and optional MCP interface.
3. **Knowledge base:** User sources, generated wiki pages, and optional media processing.

The cleanup must preserve these boundaries. User data must remain separate from installed package files.

## General rules

Apply these rules in all phases:

- Preserve the read-only Ableton behavior.
- Do not replace user-modified files without explicit consent.
- Make each migration reversible.
- Install and test from a built wheel, not only from a checkout.
- Keep CUDA and media dependencies optional.
- Add tests before changing complex adapter or bridge behavior.
- Update user documentation in the same change as user-facing behavior.
- Remove an old path only after its replacement works.

---

# Phase 1: Installation and identity

## Goal

A new user can install, configure, diagnose, upgrade, and remove the product without cloning the repository.

## 1.1 Rename and complete the Python distribution

Change the distribution name in `pyproject.toml` from `ableton-live-intro-mcp` to `ableton-ctrl`.

Add this package metadata:

- A short description
- The README path
- The license
- Project URLs
- The supported Python versions
- The supported operating system
- Development-status classifiers

Keep the import package named `ableton_ctrl`.

Review references to Live Intro. Replace them when they describe the whole product. Keep them when they describe an actual Intro limitation.

## 1.2 Create one user-facing command tree

Keep `ableton-ctrl` as the main executable. Add these subcommands:

```text
ableton-ctrl install
ableton-ctrl upgrade
ableton-ctrl doctor
ableton-ctrl status
ableton-ctrl uninstall
ableton-ctrl call '<json>'
```

Keep the current one-argument JSON form for one compatibility release. Print a migration notice only to standard error.

Add these common installation options:

```text
--with-pi
--with-kb
--kb-path PATH
--dry-run
--yes
--home PATH
```

Use `--home` for isolated tests. Do not advertise it as the normal installation method.

## 1.3 Move the Remote Script installer into the package

Move the logic from `scripts/install_remote_script.py` into:

```text
src/ableton_ctrl/install/remote_script.py
```

Store the complete Remote Script template under package data. Do not generate Python modules from string literals during installation.

Use this package-data layout:

```text
src/ableton_ctrl/install/templates/remote_script/
```

The installer must:

1. Find the standard Ableton Remote Scripts directory.
2. Create the bridge configuration with private permissions.
3. Stage all files in a temporary directory.
4. Preserve the current managed-file marker.
5. Refuse to replace an unmanaged destination.
6. Restore the previous version after an installation error.
7. Print the required Ableton preference step.

Replace `scripts/install_remote_script.py` with a temporary compatibility wrapper. Remove the wrapper after one release.

## 1.4 Unify product installation

Make `ableton-ctrl install` coordinate these operations:

1. Install the Ableton Remote Script.
2. Install Pi files when `--with-pi` is present.
3. Initialize a knowledge base when `--with-kb` is present.
4. Run bounded diagnostics.
5. Print a concise completion report.

Detect Pi before recommending `--with-pi`. Do not modify Pi directories unless the user requests Pi integration.

Continue to track checksums for managed Pi files. Never track checksums for user knowledge-base content.

## 1.5 Add upgrade and removal operations

`ableton-ctrl upgrade` must:

- Back up managed files.
- Replace only unmodified managed files.
- Preserve configuration secrets.
- Preserve all knowledge-base content.
- Report files that require manual reconciliation.

`ableton-ctrl uninstall` must:

- Show every path before removal.
- Require confirmation unless `--yes` is present.
- Remove only files with valid managed markers or manifest entries.
- Keep the knowledge base unless the user adds `--remove-kb`.
- Keep backups unless the user adds `--remove-backups`.

## 1.6 Improve diagnostics

Extend `ableton-ctrl doctor` to examine:

- The operating system
- The Python version
- The configuration path and permissions
- The bridge executable
- The Remote Script installation and marker
- The Live connection
- The selected Live version and edition
- The Pi extension and skill, when installed
- The configured knowledge-base path, when present

Return a human-readable report for interactive use. Keep a `--json` form for agents and automated support.

Never print the bridge secret.

## 1.7 Rewrite the entry documentation

Replace the root README with a short user entry point. Move detailed material into:

```text
docs/getting-started.md
docs/install.md
docs/ableton-setup.md
docs/pi-integration.md
docs/troubleshooting.md
docs/development.md
```

The getting-started guide must cover one successful path from installation to the first Live Set inspection.

Add an image that shows the Ableton Control Surface selection. Remove the image if the Ableton interface changes and no replacement is available.

## 1.8 Add package and installation tests

Add tests for:

- Installation into an empty home directory
- Refusal to replace unmanaged files
- Upgrade of unchanged managed files
- Refusal to upgrade modified managed files
- Rollback after a staged installation error
- Uninstallation of managed files
- Preservation of the knowledge base
- Configuration permissions
- Installation from a built wheel
- Presence of all package templates and Pi artifacts

Run these commands in continuous integration:

```bash
uv sync --locked
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

Install the wheel into a clean environment. Then run `ableton-ctrl doctor --json` with an isolated home directory.

## Phase 1 removal list

Remove these items after their replacements pass all tests:

- Direct setup instructions that require a repository checkout
- The installer implementation under `scripts/`
- Product-wide references to `ableton-live-intro-mcp`
- Duplicate installation instructions in unrelated documents

## Phase 1 completion criteria

Phase 1 is complete when:

- A user can install from a wheel.
- One command installs all requested managed components.
- Upgrade and removal preserve user content.
- Diagnostics identify each incomplete setup step.
- The README contains one short installation path.

---

# Phase 2: Knowledge-base foundation

## Goal

A user can create, populate, inspect, and maintain a knowledge base through documented commands.

## 2.1 Select one canonical knowledge-base format

Use the current packaged wiki template as the starting point. Remove the repository-level `content-kb` template as a product template.

Keep this logical layout:

```text
knowledge-base/
  kb.json
  AGENTS.md
  README.md
  raw/
  raw/assets/
  wiki/
  wiki/index.md
  wiki/log.md
  wiki/sources/
  wiki/how-to/
  wiki/concepts/
  wiki/techniques/
  wiki/devices/
  wiki/genres/
  wiki/analyses/
```

`kb.json` must contain:

- The schema version
- A stable knowledge-base identifier
- The creation time
- Source records
- Tool compatibility information

Do not put secrets or machine-specific absolute paths in `kb.json`.

## 2.2 Add knowledge-base commands

Add this command group:

```text
ableton-ctrl kb init PATH
ableton-ctrl kb add SOURCE
ableton-ctrl kb status
ableton-ctrl kb lint
ableton-ctrl kb migrate
ableton-ctrl kb path
```

`kb init` must:

- Refuse to replace a nonempty directory.
- Create the canonical layout.
- Write the initial manifest atomically.
- Print the new path and the next command.

`kb add` must initially support:

- Markdown
- Plain text
- JSON transcripts that use a documented schema

Copy imported files into `raw/`. Do not modify the original source.

## 2.3 Add source identity and provenance

For each source, record:

- A stable source identifier
- The original filename
- The imported filename
- The media type
- A SHA-256 hash
- The import time
- Optional title and creator metadata
- The processing state

If the same content already exists, `kb add` must report it. It must not create another copy by default.

Add `--allow-duplicate` for intentional duplicate imports.

## 2.4 Separate deterministic work from agent work

The CLI must handle deterministic operations:

- Directory creation
- File import
- Hash calculation
- Manifest updates
- Link validation
- Front-matter validation
- Index coverage checks
- Log formatting checks

The Pi skill can handle semantic operations:

- Source summaries
- Claim extraction
- Synthesis
- Page updates
- Conflict analysis

Document this boundary in `docs/knowledge-base.md`.

## 2.5 Convert the knowledge-base rules into validation

Implement `kb lint` for rules that software can evaluate reliably:

- Required files exist.
- Generated pages contain valid front matter.
- Generated pages appear in `wiki/index.md`.
- Wiki links point to existing pages.
- Source pages refer to imported raw files.
- Duplicate page paths do not exist.
- The activity log uses the required heading format.

Report uncited claims and stale guidance as advisory findings. Do not claim full semantic validation.

Support `--json` output for Pi.

## 2.6 Configure the Pi integration

Store the selected knowledge-base path in a small Pi integration file or the main application configuration.

Do not require the knowledge base to live under `~/.pi/agent/`. Recommend a user-owned documents directory.

Update the Pi skill to:

1. Read the configured path.
2. Run `ableton-ctrl kb status` before an ingest operation.
3. Follow the knowledge-base rules.
4. Run `ableton-ctrl kb lint` after changes.
5. Report unresolved findings.

## 2.7 Migrate existing knowledge bases

Add a schema-version migration framework before changing the template after release.

`kb migrate` must:

- Detect the source schema version.
- Create a backup before a write.
- Apply migrations in order.
- Update the schema version only after success.
- Leave the original usable after an error.

Provide a documented manual migration for the current `~/.pi/agent/ableton-wiki` location.

## 2.8 Add knowledge-base tests

Add tests for:

- Initialization
- Refusal to replace existing content
- Text and Markdown import
- Transcript import
- Duplicate detection
- Atomic manifest updates
- Broken-link detection
- Missing index entries
- Invalid front matter
- Migration rollback
- Paths that contain spaces
- Pi use of a custom knowledge-base path

Use fixtures that contain small synthetic sources. Do not commit copyrighted tutorial transcripts.

## Phase 2 removal list

Remove these items after migration support works:

- The duplicate repository knowledge-base template
- Instructions that require manual placement under `~/.pi/agent/`
- The vague “ask an agent to ingest it” setup as the only workflow
- Empty tracked directories that the initializer can create

## Phase 2 completion criteria

Phase 2 is complete when:

- A user can initialize a knowledge base at a selected path.
- A user can import supported source files safely.
- The system detects duplicate sources.
- The linter reports structural defects.
- Pi uses the configured knowledge-base path.
- Upgrades do not modify user wiki pages.

---

# Phase 3: Tool consolidation

## Goal

The repository has one supported source-ingestion pipeline. Large media dependencies remain optional.

## 3.1 Inventory the existing tools

Document the capabilities and callers of:

- `tools/ingest`
- `tools/transcribe`
- `tools/scrape`
- `tools/ingest/scripts/ingest-youtube-playlist.sh`
- `tools/ingest/scripts/test-e2e-with-pi.sh`

For each capability, choose one of these outcomes:

- Move into the supported knowledge-base package.
- Keep as a development-only test tool.
- Archive with a replacement reference.
- Remove because another implementation replaces it.

Do not merge code until this inventory identifies overlapping responsibilities.

## 3.2 Define one provider interface

Create a source-provider interface for optional acquisition backends. A provider must return a common source bundle with:

- Source metadata
- Canonical source files
- Transcript data, when available
- Image records, when available
- Provenance
- Content hashes
- Provider diagnostics

Add providers incrementally:

1. Local text and Markdown
2. Local transcript JSON
3. Local audio or video
4. Public YouTube video
5. YouTube playlist

Keep local file support in the base installation.

## 3.3 Consolidate Python packages

Move supported ingestion code into a package with one identity. Use either `ableton_ctrl.kb` or a separate `ableton-kb` distribution.

Prefer a separate `ableton-kb` distribution if media dependencies or Python constraints conflict with the main application.

Expose optional dependency groups such as:

```text
ableton-kb[youtube]
ableton-kb[transcribe]
ableton-kb[transcribe-cuda]
```

The main `ableton-ctrl` installation must not install:

- CUDA libraries
- Browser automation
- Whisper models
- FFmpeg Python wrappers

## 3.4 Consolidate transcription

Preserve these properties from `tools/transcribe`:

- Local processing
- Structured transcript output
- Stable segment timestamps
- Explicit CUDA errors
- Temporary-file cleanup
- Reusable model lifetime

Add a backend protocol so future CPU or remote backends do not change the ingest pipeline.

Keep CUDA as an explicit option. Do not add an automatic CPU fallback without benchmarks and clear user feedback.

Document external requirements:

- FFmpeg
- An NVIDIA driver
- A compatible CUDA environment
- Available model storage

## 3.5 Consolidate YouTube acquisition

Compare `tools/scrape` with the acquisition logic in `tools/ingest`.

Keep one implementation for each operation:

- Metadata retrieval
- Caption retrieval
- Media download
- Playlist enumeration
- Retry classification
- Canonical storage

Preserve useful result contracts from `ytkit`, including explicit blocked and unavailable states.

Remove machine-specific defaults from shell scripts. In particular, remove paths tied to a developer home directory.

## 3.6 Connect source bundles to the knowledge base

Add these commands after provider support is stable:

```text
ableton-ctrl kb add-video FILE
ableton-ctrl kb add-url URL
ableton-ctrl kb add-playlist URL
```

Each command must:

1. Show the required optional dependencies when they are absent.
2. Store job data outside `raw/`.
3. Publish only canonical source outputs into `raw/`.
4. Record hashes and provenance in `kb.json`.
5. Leave failed jobs available for diagnosis.
6. Avoid duplicate publication after a retry.

Do not claim that publication completed the semantic wiki synthesis. Report publication and synthesis as separate states.

## 3.7 Reduce environment and lockfile sprawl

Keep one lockfile for each independently released environment.

Remove a tool lockfile when its code moves into another package. Align Python ranges unless a dependency requires a narrower range.

Add root commands for supported environments, for example:

```bash
uv sync --locked
uv sync --project packages/ableton-kb --locked
```

Do not commit virtual environments, model caches, downloaded media, browser profiles, or job caches.

## 3.8 Add ingestion tests

Add unit tests for each provider. Use local fixtures and fake external processes.

Add integration tests for:

- Local video preparation
- Transcript publication
- Failed transcription recovery
- Duplicate publication prevention
- Playlist continuation
- Partial playlist results
- Missing optional dependencies
- Paths with spaces

Keep live YouTube, browser, and CUDA tests outside the default test suite. Run them through explicit smoke-test jobs.

## Phase 3 removal list

Remove these items after equivalent supported paths exist:

- Redundant acquisition implementations
- Developer-specific playlist scripts
- Obsolete tool package metadata
- Obsolete tool lockfiles
- Documentation for removed commands
- References to a “future scraper” after the provider exists

## Phase 3 completion criteria

Phase 3 is complete when:

- One command imports each supported source type.
- Media features use optional dependencies.
- One provider owns each acquisition operation.
- Failed jobs can resume without duplicate publication.
- Published sources enter the canonical knowledge-base workflow.
- The default installation remains small and does not require CUDA.

---

# Phase 4: Internal simplification

## Goal

The code has fewer repeated definitions and clearer module boundaries. Behavior remains compatible and tested.

## 4.1 Create one CLI action registry

The current CLI repeats action information in command models, unions, action lists, mappings, and dispatch logic.

Create one registry that contains:

- The public action name
- The validation model
- The request builder
- The help text
- Availability requirements
- Documentation examples

Generate these values from the registry:

- Supported action names
- Action validation lookup
- CLI help
- Agent schema metadata
- CLI reference documentation

Keep special dispatch behavior, such as implicit change cursors, in named handlers.

## 4.2 Split `cli.py` by responsibility

Move code into focused modules:

```text
src/ableton_ctrl/commands/models.py
src/ableton_ctrl/commands/registry.py
src/ableton_ctrl/commands/dispatch.py
src/ableton_ctrl/diagnostics.py
src/ableton_ctrl/cursors.py
src/ableton_ctrl/resources.py
```

Keep `cli.py` responsible for argument parsing, output selection, and exit codes.

Do not change the JSON response contracts during this split.

## 4.3 Simplify installer internals

Create shared primitives for:

- Managed markers
- Checksums
- Staging directories
- Backups
- Atomic replacement
- Rollback
- Dry-run reports

Use these primitives for the Remote Script and Pi installations. Keep separate manifests because the destinations have different ownership rules.

Replace broad `BaseException` cleanup blocks when a narrower exception boundary is sufficient. Preserve cleanup during interruption where required.

## 4.4 Review the Pi extension artifacts

Keep `ableton-ctrl.ts` as the extension entry point. Keep `ableton-controller.ts` only if it remains a separate tested process controller.

Review both files for:

- Duplicate status models
- Duplicate process lifecycle logic
- Repeated action lists
- Unbounded output
- Unclear ownership rules

Generate the extension action schema from a checked-in artifact or add a contract test against the Python registry.

The extension must continue to stop only bridges that it owns.

## 4.5 Make MCP optional

Move the MCP dependency to an optional dependency group.

Guard MCP entry points with a clear missing-dependency message. Keep MCP contract tests in an environment that installs the MCP extra.

Move MCP documentation into `docs/mcp.md`. Do not present MCP as part of the primary setup.

Remove MCP only in a later major release, and only if usage data justifies removal.

## 4.6 Characterize large modules before refactoring

Add characterization tests before modifying:

- `src/ableton_ctrl/bridge/store.py`
- `src/ableton_ctrl/bridge/server.py`
- `src/ableton_ctrl/adapter/runtime.py`
- `src/ableton_ctrl/adapter/discovery.py`

Measure these concerns:

- State ownership
- Revision behavior
- Session replacement
- Capacity limits
- Pagination
- Error conversion
- Live compatibility fallbacks

Split modules only where one section has an independent responsibility. Do not introduce abstractions only to reduce line counts.

## 4.7 Remove repository cruft

Review and remove or relocate:

- Completed implementation plans
- Empty coverage artifact directories
- Duplicate knowledge-base templates
- Obsolete compatibility wrappers
- Unused fixtures
- Stale package names
- Stale Live edition references
- Generated files that appear in source directories

Move useful historical plans to `docs/internal/` only when they still explain an active constraint. Git history is sufficient for completed plans.

Expand `.gitignore` to include nested development output:

```gitignore
**/.venv/
**/__pycache__/
**/.pytest_cache/
**/.mypy_cache/
**/.ruff_cache/
dist/
build/
*.egg-info/
artifacts/
```

Keep a tracked artifact directory only when a documented process requires it.

## 4.8 Add public project files

Add:

```text
LICENSE
CONTRIBUTING.md
CHANGELOG.md
SECURITY.md
.github/ISSUE_TEMPLATE/
.github/workflows/
```

Document:

- Supported Ableton versions
- Supported Python versions
- The release process
- The real Live smoke-test requirement
- Security-reporting instructions
- The unsupported status of Ableton's Python API

## 4.9 Add architecture and contract documentation

Create `docs/architecture.md` with these flows:

```text
Live -> Remote Script -> local bridge -> CLI -> Pi extension
Live -> Remote Script -> local bridge -> optional MCP server
Source -> provider -> raw files -> Pi synthesis -> wiki
```

Document ownership and persistence for:

- Bridge processes
- Configuration
- Secrets
- Change cursors
- Managed installation files
- Knowledge-base files
- Job caches

Keep stable JSON contracts in one reference document. Add tests that compare examples with current validation models.

## 4.10 Establish release gates

A release must pass:

1. Formatting, linting, typing, and unit tests.
2. Contract tests for the CLI, bridge, Pi artifacts, and optional MCP interface.
3. Installation and upgrade tests from a wheel.
4. Knowledge-base migration tests.
5. A manual Live smoke test on the declared target version and edition.
6. A clean installation test on a supported macOS system.

Record the tested Live build in the release notes.

## Phase 4 removal list

Remove these items after compatibility tests pass:

- Repeated action-name lists
- Generated Python source in installers
- Compatibility wrappers past their stated removal release
- Unused package dependencies
- Completed internal plans from user documentation
- Empty artifact placeholders without a consumer

## Phase 4 completion criteria

Phase 4 is complete when:

- CLI actions have one authoritative registry.
- Installer operations use shared safe-write primitives.
- MCP is optional.
- Large modules have characterization coverage.
- User documentation contains no internal implementation plans.
- Continuous integration tests built distributions.
- The release gate includes a real Ableton smoke test.

---

# Proposed change sequence

Use small pull requests in this order:

1. Add package metadata and public project files.
2. Add package-data tests for current artifacts.
3. Move the Remote Script installer into the package.
4. Add the new install, upgrade, doctor, and uninstall commands.
5. Rewrite the README and installation guides.
6. Add the canonical knowledge-base manifest and initializer.
7. Add source import and structural linting.
8. Update Pi to use a configured knowledge-base path.
9. Inventory and consolidate the media tools.
10. Add optional source providers.
11. Introduce the CLI action registry.
12. Split CLI support modules.
13. Make MCP optional.
14. Characterize and simplify large runtime modules.
15. Remove compatibility paths and remaining cruft.

Each pull request must include its migration notes and rollback method.

# Final user workflow

The completed workflow will look like this:

```bash
uv tool install ableton-ctrl
ableton-ctrl install --with-pi --with-kb --kb-path "$HOME/Documents/Ableton Knowledge"
ableton-ctrl doctor
```

The user then selects `AbletonCtrl` as a Control Surface in Live.

The user can add knowledge sources with:

```bash
ableton-ctrl kb add tutorial.md
ableton-ctrl kb lint
```

Optional media support can add URLs and local videos without changing the core installation.
