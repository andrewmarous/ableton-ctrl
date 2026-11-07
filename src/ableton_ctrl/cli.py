"""User-facing setup and knowledge commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from . import kb, library, upstream
from .transaction import Transaction, backup_path, rollback
from . import whisper_install


def configuration() -> Path:
    return Path.home() / ".config/ableton-ctrl/config.json"


def root_path(value: Path | None) -> Path:
    if value:
        return value.expanduser().resolve()
    config = configuration()
    if config.exists():
        return Path(json.loads(config.read_text())["knowledge_base"])
    return Path.home() / ".pi/agent/ableton-wiki"


def add_source(root: Path, source: str, backend: str) -> str:
    if source.startswith(("https://", "http://")):
        from video_ingest.acquire import prepare  # type: ignore[import-untyped]
        cache = Path.home() / ".cache/ableton-ctrl/jobs"
        key = hashlib.sha256(source.encode()).hexdigest()
        state = cache / f"{key}.json"
        if state.exists():
            prepared = json.loads(state.read_text())
        else:
            print("Downloading public video to the local job cache.", file=sys.stderr)
            prepared = prepare(source, root / "raw", cache)
            kb._write_json_atomic(state, prepared)
        media = Path(prepared["media"])
        origin = source
    else:
        media = Path(source).expanduser().resolve()
        origin = media.name
    if media.suffix.lower() in {".md", ".markdown", ".txt", ".json"}:
        return library.stage(root, media, origin)
    from video_transcribe import Transcriber  # type: ignore[import-untyped]
    directory = Path.home() / ".cache/ableton-ctrl/transcripts" / hashlib.sha256(str(media).encode()).hexdigest()
    print(f"Local transcription ({backend}). First use can download model weights.", file=sys.stderr)
    with Transcriber(backend=backend) as transcriber:
        transcript = transcriber.transcribe(media)
        paths = transcript.write(directory)
    evidence = next(Path(p) for p in paths if Path(p).suffix == ".json")
    return library.stage(root, evidence, origin)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ableton")
    parser.add_argument("--kb", type=Path, help="Knowledge directory (overrides saved configuration)")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup")
    setup.add_argument("--knowledge-only", action="store_true")
    setup.add_argument("--user-library")
    setup.add_argument("--yes", action="store_true", help="Apply the displayed setup plan")
    setup.add_argument("--install-whisper", action="store_true", help="Download and compile pinned whisper.cpp")
    setup.add_argument("--backend", choices=["auto", "metal", "cpu"], default="auto")
    restore = sub.add_parser("rollback")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--yes", action="store_true")
    transcriber = sub.add_parser("transcriber").add_subparsers(dest="transcriber_action", required=True)
    installer = transcriber.add_parser("install")
    installer.add_argument("--backend", choices=["auto", "metal", "cpu"], default="auto")
    installer.add_argument("--jobs", type=int, default=4)
    installer.add_argument("--yes", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--user-library")
    sub.add_parser("chat")
    knowledge = sub.add_parser("kb").add_subparsers(dest="action", required=True)
    knowledge.add_parser("init")
    add = knowledge.add_parser("add")
    add.add_argument("source")
    add.add_argument("--backend", choices=["auto", "metal", "cpu", "cuda"], default="auto")
    add.add_argument("--synthesize", action="store_true", help="Send source text to your configured Pi model for cited technique drafts")
    add.add_argument("--model", help="Pi model ID or pattern")
    synthesis_parser = knowledge.add_parser("synthesize")
    synthesis_parser.add_argument("id")
    synthesis_parser.add_argument("--model", help="Pi model ID or pattern")
    knowledge.add_parser("status")
    review = knowledge.add_parser("review")
    review.add_argument("id")
    publish = knowledge.add_parser("publish")
    publish.add_argument("id")
    publish.add_argument("--yes", action="store_true")
    search = knowledge.add_parser("search")
    search.add_argument("query")
    knowledge.add_parser("lint")
    export = knowledge.add_parser("export")
    export.add_argument("archive", type=Path)
    imp = knowledge.add_parser("import")
    imp.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        root = root_path(args.kb) if args.command not in {"rollback", "transcriber"} else Path.home()
        if args.command == "setup":
            print(f"Knowledge directory: {root}")
            print("Save configuration: " + str(configuration()))
            if not args.knowledge_only:
                if not shutil.which("uvx"):
                    raise ValueError("Install uv first, or use --knowledge-only.")
                print("Install pinned AbletonMCP Remote Script and merge Pi configuration; existing files receive backups.")
            paths = [configuration()]
            if not root.exists():
                paths.append(root)
            if not args.knowledge_only:
                paths += upstream.installation_paths(Path.home(), args.user_library, root)
            if args.install_whisper:
                backend = whisper_install.selected_backend(args.backend)
                destination = whisper_install.install_path(Path.home(), backend)
                if not destination.exists():
                    paths.append(destination)
                print(f"Download and compile whisper.cpp {whisper_install.VERSION} ({backend}) into {destination}")
            if not args.yes and input("Apply this plan? [y/N] ").lower() != "y":
                return 0
            backup = backup_path(Path.home(), "setup")
            print(f"Setup recovery journal: {backup}")
            with Transaction(backup, paths):
                library.initialize(root)
                if args.install_whisper:
                    print(f"Transcriber: {whisper_install.install(Path.home(), args.backend)}")
                if not args.knowledge_only:
                    upstream.install(Path.home(), shutil.which("uvx") or "uvx", args.user_library, wiki_path=root)
                kb._write_json_atomic(configuration(), {"schema_version": 1, "knowledge_base": str(root)})
            if not args.knowledge_only:
                print("Restart Live. Select AbletonMCP in an unused Control Surface row; set Input/Output to None.")
                print("In Pi, run /reload. Then run ableton doctor and pi mcp list.")
            print("Setup complete. Add notes with: ableton kb add ./notes.md")
        elif args.command == "rollback":
            if not args.yes and input("Restore this trusted local backup? [y/N] ").lower() != "y":
                return 0
            rollback(args.backup.expanduser().resolve())
            print("Installation restored. Restart Live and run /reload in Pi if Live integration changed.")
        elif args.command == "transcriber":
            print(f"Download and compile pinned whisper.cpp {whisper_install.VERSION}; a C++ compiler, Git, and CMake are required.")
            if not args.yes and input("Install? [y/N] ").lower() != "y":
                return 0
            print(whisper_install.install(Path.home(), args.backend, args.jobs))
        elif args.command == "doctor":
            missing = []
            for executable in ("uvx", "pi", "ffmpeg", "ffprobe", "yt-dlp"):
                found = shutil.which(executable)
                print(f"{executable}: {found or 'missing'}")
                if not found:
                    missing.append(executable)
            managed = whisper_install.binary_path(Path.home(), whisper_install.selected_backend("auto"))
            print("whisper-cli: " + (os.environ.get("WHISPER_CPP_BINARY") or shutil.which("whisper-cli") or (str(managed) if managed.is_file() else "missing; run ableton transcriber install")))
            print(f"Knowledge: {root}")
            if not (root / "kb.json").exists():
                print("Run ableton setup first.")
                return 1
            findings = kb.lint(root)
            print(json.dumps(findings, indent=2))
            if shutil.which("uvx"):
                command = upstream.command("uvx", "doctor", "--json")
                if args.user_library:
                    command += ["--user-library", args.user_library]
                return subprocess.run(command).returncode or int(bool(findings))
            return int(bool(findings or missing))
        elif args.command == "chat":
            return subprocess.run(["pi", f"Use the production knowledge at {root}. Separate source evidence from observed Live facts. Do not edit Live without explicit permission."]).returncode
        elif args.action == "import":
            library.import_archive(args.archive, root)
            print(root)
        elif args.action == "init":
            library.initialize(root)
            print(root)
        elif args.action == "add":
            identity = add_source(root, args.source, args.backend)
            if args.synthesize:
                from .synthesis import synthesize
                print("Sending source text to the configured Pi model; provider charges can apply.", file=sys.stderr)
                print(f"Technique drafts: {len(synthesize(root, identity, args.model))}")
            print(f"Draft: {identity}\nReview: ableton kb review {identity}\nPublish after review: ableton kb publish {identity}")
        elif args.action == "synthesize":
            from .synthesis import synthesize
            print("Sending source text to the configured Pi model; provider charges can apply.", file=sys.stderr)
            print(f"Technique drafts: {len(synthesize(root, args.id, args.model))}")
        elif args.action == "status":
            print(json.dumps(library.status(root), indent=2))
        elif args.action == "review":
            page = library.draft(root, args.id) / "page.md"
            print(f"Draft file (edit before publication): {page}\n")
            print(page.read_text())
            for technique in sorted((page.parent / "techniques").glob("*.md")):
                print(f"\nTechnique draft (edit before publication): {technique}\n")
                print(technique.read_text())
        elif args.action == "publish":
            if not args.yes and input("Publish the reviewed draft? [y/N] ").lower() != "y":
                return 0
            print(library.publish(root, args.id))
        elif args.action == "search":
            for page in sorted((root / "wiki").rglob("*.md")):
                for number, line in enumerate(page.read_text().splitlines(), 1):
                    if args.query.casefold() in line.casefold():
                        print(f"{page.relative_to(root)}:{number}: {line}")
        elif args.action == "lint":
            findings = kb.lint(root)
            print(json.dumps(findings, indent=2))
            return int(bool(findings))
        elif args.action == "export":
            library.export(root, args.archive)
            print(args.archive)
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, EOFError,
            zipfile.BadZipFile, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
