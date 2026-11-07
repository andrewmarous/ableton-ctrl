"""Portable, review-first knowledge workflows. No model service is used."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import kb


def initialize(root: Path) -> None:
    if not (root / "kb.json").exists():
        kb.init(root)
    manifest = kb.load(root)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported knowledge schema. No files were changed.")
    if not isinstance(manifest.get("sources"), list):
        raise ValueError("Invalid source manifest.")
    for record in manifest["sources"]:
        name = record.get("imported_filename") if isinstance(record, dict) else None
        if not isinstance(name, str) or Path(name).name != name or "\\" in name or name in {".", ".."}:
            raise ValueError("Unsafe source filename in manifest.")


def stage(root: Path, source: Path, origin: str | None = None) -> str:
    initialize(root)
    data = source.read_bytes()
    identity = hashlib.sha256(data).hexdigest()
    directory = root / "drafts" / identity
    if directory.exists():
        return identity
    directory.mkdir(parents=True)
    shutil.copyfile(source, directory / ("source" + source.suffix.lower()))
    metadata = {"id": identity, "filename": source.name, "origin": origin or source.name,
                "sha256": identity, "state": "review"}
    kb._write_json_atomic(directory / "record.json", metadata)
    text = data.decode("utf-8")
    if source.suffix.lower() == ".json":
        transcript = json.loads(text)
        segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
        text = "\n".join(f"[{s.get('start', 0)}s] {s.get('text', '')}" for s in segments)
        if not text:
            text = data.decode("utf-8")
    # Extractive publication is deliberately not presented as synthesized advice.
    page = (f"---\nsource_id: {identity}\nkind: source-evidence\n---\n\n"
            f"# {source.stem}\n\nSource: {metadata['origin']}\n\n"
            "This page contains source evidence, not independently verified advice.\n\n"
            "## Evidence\n\n" + text + "\n")
    (directory / "page.md").write_text(page, encoding="utf-8")
    return identity


def draft(root: Path, identity: str) -> Path:
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("Use the full draft ID from 'ableton kb status'.")
    return root / "drafts" / identity


def publish(root: Path, identity: str) -> Path:
    from .transaction import Transaction, backup_path
    directory = draft(root, identity)
    target = root / "wiki/sources" / f"{identity}.md"
    techniques = sorted((directory / "techniques").glob("*.md"))
    targets = [root / "wiki/techniques" / p.name for p in techniques]
    for path in [target, *targets]:
        if path.exists():
            raise FileExistsError(f"Published page already exists: {path}")
    paths = [root / "kb.json", root / "raw", root / "wiki/index.md",
             directory / "record.json", target, *targets]
    with Transaction(backup_path(root.parent, "publication"), paths):
        result = _publish(root, identity)
        for source, destination in zip(techniques, targets):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            with (root / "wiki/index.md").open("a", encoding="utf-8") as index:
                index.write(f"\n- [Technique {source.stem}](techniques/{source.name})\n")
    return result


def _publish(root: Path, identity: str) -> Path:
    directory = draft(root, identity)
    record = json.loads((directory / "record.json").read_text())
    page = directory / "page.md"
    target = root / "wiki/sources" / f"{identity}.md"
    if target.exists():
        raise FileExistsError(f"Published page already exists: {target}")
    source = next(directory.glob("source.*"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Draft evidence changed. Add the source again.")
    result = kb.add(root, source)
    manifest = kb.load(root)
    for item in manifest["sources"]:
        if item["id"] == result["source"]["id"]:
            item.update(origin=record["origin"], processing_state="published", page=str(target.relative_to(root)))
    kb._write_json_atomic(root / "kb.json", manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(page, target)
    index = root / "wiki/index.md"
    with index.open("a", encoding="utf-8") as out:
        out.write(f"\n- [Source {identity[:12]}](sources/{identity}.md)\n")
    record["state"] = "published"
    kb._write_json_atomic(directory / "record.json", record)
    return target


def export(root: Path, destination: Path) -> None:
    initialize(root)
    if destination.exists():
        raise FileExistsError(destination)
    # Explicit allowlist: no drafts, jobs, models, credentials, or downloaded media.
    files = [root / name for name in ("kb.json", "README.md", "AGENTS.md")]
    files += list((root / "wiki").rglob("*"))
    manifest = kb.load(root)
    files += [root / "raw" / r["imported_filename"] for r in manifest.get("sources", [])]
    selected = []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Unsafe export path: {path}")
        if path.is_file():
            selected.append(path)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("raw/", "")
        for path in selected:
            archive.write(path, path.relative_to(root).as_posix())


def import_archive(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError("Import requires a new directory; existing knowledge is never overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary) / "library"
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            total = 0
            seen = set()
            for info in archive.infolist():
                name = PurePosixPath(info.filename)
                total += info.file_size
                if (name.is_absolute() or ".." in name.parts or "\\" in info.filename
                        or info.filename in seen or total > 512 * 1024 * 1024
                        or (info.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Unsafe or oversized knowledge archive.")
                seen.add(info.filename)
                allowed = (name.as_posix() in {"kb.json", "README.md", "AGENTS.md"}
                           or (name.parts and name.parts[0] in {"wiki", "raw"}))
                if not allowed:
                    raise ValueError(f"Unexpected archive member: {name}")
                archive.extract(info, staging)
        initialize(staging)
        for record in kb.load(staging)["sources"]:
            source = staging / "raw" / record["imported_filename"]
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != record.get("sha256"):
                raise ValueError("Source evidence is missing or its checksum differs.")
        errors = kb.lint(staging)
        if errors:
            raise ValueError(f"Invalid knowledge archive: {errors}")
        staging.rename(destination)


def status(root: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((root / "drafts").glob("*/record.json"))]
