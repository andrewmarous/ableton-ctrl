"""Persistent job state helpers."""

from __future__ import annotations
import json
import os
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def job_lock(job: Path):
    lock = job / ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"job is locked: {job}") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_state(job: Path, state: dict) -> None:
    temporary = job / ".state.tmp"
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, job / "state.json")


def load_state(job: Path) -> dict:
    return json.loads((job / "state.json").read_text(encoding="utf-8"))
