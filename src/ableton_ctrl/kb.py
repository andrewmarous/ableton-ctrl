"""Deterministic knowledge-base management."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
DIRECTORIES = (
    "raw/assets",
    "wiki/sources",
    "wiki/how-to",
    "wiki/concepts",
    "wiki/techniques",
    "wiki/devices",
    "wiki/genres",
    "wiki/analyses",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_path(root: Path) -> Path:
    return root / "kb.json"


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def init(path: Path) -> Path:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"knowledge base directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    for directory in DIRECTORIES:
        (path / directory).mkdir(parents=True, exist_ok=True)
    (path / "AGENTS.md").write_text(
        "# Ableton knowledge base\n\nFollow provenance and run `ableton-ctrl kb lint` after edits.\n",
        encoding="utf-8",
    )
    (path / "README.md").write_text("# Ableton knowledge base\n", encoding="utf-8")
    (path / "wiki/index.md").write_text("# Index\n", encoding="utf-8")
    (path / "wiki/log.md").write_text("# Activity log\n", encoding="utf-8")
    _write_json_atomic(
        _manifest_path(path),
        {
            "schema_version": SCHEMA_VERSION,
            "id": str(uuid.uuid4()),
            "created_at": _now(),
            "sources": [],
            "tool_compatibility": {"ableton_ctrl": 1},
        },
    )
    return path


def load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_manifest_path(path).read_text(encoding="utf-8")))


def add(root: Path, source: Path, allow_duplicate: bool = False) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix not in {".md", ".markdown", ".txt", ".json"}:
        raise ValueError("supported sources are Markdown, plain text, and JSON transcripts")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    manifest = load(root)
    records = manifest.get("sources", [])
    if not allow_duplicate:
        for record in records:
            if record.get("sha256") == digest:
                return {"duplicate": True, "source": record}
    filename = f"{digest[:12]}-{source.name}"
    target = root / "raw" / filename
    if not target.exists():
        shutil.copyfile(source, target)
    record = {
        "id": str(uuid.uuid4()),
        "original_filename": source.name,
        "imported_filename": filename,
        "media_type": "application/json"
        if suffix == ".json"
        else "text/markdown"
        if suffix in {".md", ".markdown"}
        else "text/plain",
        "sha256": digest,
        "imported_at": _now(),
        "processing_state": "imported",
    }
    records.append(record)
    manifest["sources"] = records
    _write_json_atomic(_manifest_path(root), manifest)
    return {"duplicate": False, "source": record}


def lint(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative in ("kb.json", "AGENTS.md", "README.md", "wiki/index.md", "wiki/log.md", "raw"):
        if not (root / relative).exists():
            findings.append(
                {"severity": "error", "path": relative, "message": "required path is missing"}
            )
    try:
        manifest = load(root)
    except (OSError, json.JSONDecodeError):
        return findings + [{"severity": "error", "path": "kb.json", "message": "invalid manifest"}]
    for record in manifest.get("sources", []):
        name = record.get("imported_filename")
        if not isinstance(name, str) or not (root / "raw" / name).is_file():
            findings.append(
                {
                    "severity": "error",
                    "path": "raw",
                    "message": "source record has no imported file",
                }
            )
    index = (
        (root / "wiki/index.md").read_text(encoding="utf-8")
        if (root / "wiki/index.md").exists()
        else ""
    )
    for page in root.glob("wiki/**/*.md"):
        if page.name in {"index.md", "log.md"}:
            continue
        relative = page.relative_to(root / "wiki").with_suffix("").as_posix()
        text = page.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            findings.append(
                {
                    "severity": "error",
                    "path": str(page.relative_to(root)),
                    "message": "generated page lacks front matter",
                }
            )
        if relative not in index:
            findings.append(
                {
                    "severity": "error",
                    "path": str(page.relative_to(root)),
                    "message": "page is missing from index",
                }
            )
    return findings
