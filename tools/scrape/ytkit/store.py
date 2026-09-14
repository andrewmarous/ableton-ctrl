"""Atomic canonical transcript storage."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import Transcript


def path_for(root: str | Path, video_id: str, track_type: str | None = None) -> Path:
    suffix = track_type or "default"
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in suffix)
    return Path(root) / (video_id + "--" + safe + ".json")


def save_transcript(transcript: Transcript, root: str | Path) -> Path:
    destination = path_for(root, transcript.video_id, transcript.track_type)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(transcript.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def load_transcript(root: str | Path, video_id: str, track_type: str | None = None) -> Transcript | None:
    path = path_for(root, video_id, track_type)
    try:
        with path.open(encoding="utf-8") as stream:
            return Transcript.from_dict(json.load(stream))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
