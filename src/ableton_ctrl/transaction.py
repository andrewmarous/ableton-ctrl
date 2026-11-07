"""Durable snapshots with automatic recovery and conflict-aware explicit rollback."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from .kb import _write_json_atomic


def fingerprint(path: Path) -> str | None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError(f"Refusing a symlink: {candidate}")
    if not path.exists():
        return None
    digest = hashlib.sha256()
    digest.update((path.stat().st_mode & 0o777).to_bytes(2, "big"))
    files = [path] if path.is_file() else sorted(path.rglob("*"))
    for file in files:
        digest.update(str(file.relative_to(path) if file != path else ".").encode() + b"\0")
        if file.is_symlink():
            link = os.readlink(file)
            if Path(link).is_absolute() or not file.resolve().is_relative_to(path.resolve()):
                raise ValueError(f"Refusing an external symlink: {file}")
            digest.update(b"l" + link.encode() + b"\0")
            continue
        digest.update(b"d" if file.is_dir() else b"f")
        digest.update((file.stat().st_mode & 0o777).to_bytes(2, "big"))
        if file.is_file():
            with file.open("rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


class Transaction:
    def __init__(self, backup: Path, paths: list[Path]):
        self.backup = backup
        self.paths = list(dict.fromkeys(p.absolute() for p in paths))
        for path in self.paths:
            if any(parent in self.paths for parent in path.parents):
                raise ValueError("Transaction paths must not overlap.")
        self.records: list[dict[str, Any]] = []

    def __enter__(self) -> Transaction:
        # Validate every path before writing anything.
        if any(self.backup.absolute().is_relative_to(path) for path in self.paths):
            raise ValueError("A backup cannot be inside a tracked directory.")
        before = [fingerprint(path) for path in self.paths]
        self.backup.mkdir(parents=True, exist_ok=False)
        for index, (path, digest) in enumerate(zip(self.paths, before)):
            snapshot = self.backup / "snapshots" / str(index)
            if digest is not None:
                _copy(path, snapshot)
            self.records.append({"path": str(path), "before": digest, "snapshot": str(index)})
        self._save("applying")
        return self

    def _save(self, state: str) -> None:
        _write_json_atomic(self.backup / "transaction.json", {"schema_version": 1, "state": state, "records": self.records})

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> Literal[False]:
        if kind is not None:
            try:
                self._restore()
                self._save("rolled-back")
            except BaseException as recovery:
                raise RuntimeError(f"Installation failed; recovery also failed. Keep backup {self.backup}: {recovery}") from error
            return False
        try:
            for record in self.records:
                record["after"] = fingerprint(Path(record["path"]))
            self._save("committed")
        except BaseException:
            self._restore()
            self._save("rolled-back")
            raise
        return False

    def _restore(self) -> None:
        for record in reversed(self.records):
            path = Path(record["path"])
            fingerprint(path)  # Refuse symlinks introduced during installation.
            _remove(path)
            if record["before"] is not None:
                _copy(self.backup / "snapshots" / record["snapshot"], path)


def backup_path(home: Path, name: str) -> Path:
    return home / ".pi/agent/backups" / name / uuid.uuid4().hex


def rollback(backup: Path) -> None:
    """Restore a trusted local snapshot only if no tracked files changed since commit."""
    manifest = json.loads((backup / "transaction.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("state") != "committed":
        raise ValueError("Only a committed installation can be rolled back.")
    records = manifest["records"]
    paths = [Path(r["path"]) for r in records]
    for record, path in zip(records, paths):
        if fingerprint(path) != record["after"]:
            raise ValueError(f"Files changed since setup; refusing rollback: {path}")
        snapshot = backup / "snapshots" / record["snapshot"]
        if record["before"] is not None and fingerprint(snapshot) != record["before"]:
            raise ValueError(f"Backup is damaged: {snapshot}")
    # Snapshot the current state too, so a restore error can itself be recovered.
    recovery = backup.parent / (backup.name + "-recovery-" + uuid.uuid4().hex)
    with Transaction(recovery, paths):
        transaction = Transaction(backup, paths)
        transaction.records = records
        transaction._restore()
    manifest["state"] = "rolled-back"
    _write_json_atomic(backup / "transaction.json", manifest)
