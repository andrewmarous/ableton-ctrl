"""Bounded, asynchronous release-smoke evidence recording."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterable

from ableton_ctrl.adapter.discovery import CoverageEntry
from ableton_ctrl.adapter.manifest import TypeSpec

_STATUS_PRIORITY = {"unavailable": 0, "read_failed": 1, "excluded": 2, "supported": 3}


class CoverageEvidenceRecorder:
    """Move coverage aggregation and file I/O off Live's main-thread tick."""

    def __init__(
        self,
        path: Path,
        manifest: dict[str, TypeSpec],
        *,
        session_id: str,
        live_version: str,
        edition: str,
    ) -> None:
        self._path = path
        self._expected: set[tuple[str, str]] = set()
        for type_name, spec in manifest.items():
            self._expected.update((type_name, member.name) for member in spec.properties)
            self._expected.update((type_name, member.name) for member in spec.relationships)
        self._session_id = session_id
        self._live_version = live_version
        self._edition = edition
        self._coverage: dict[tuple[str, str], CoverageEntry] = {}
        self._coverage_queue: queue.Queue[tuple[CoverageEntry, ...]] = queue.Queue(maxsize=256)
        self._timings: deque[float] = deque(maxlen=20_000)
        self._timing_lock = threading.Lock()
        self._discovery_complete = False
        self._dropped = False
        self._closing = False
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def record_coverage(self, entries: tuple[CoverageEntry, ...]) -> None:
        if not entries:
            return
        try:
            self._coverage_queue.put_nowait(entries)
        except queue.Full:
            self._dropped = True
        self._wake.set()

    def record_tick(self, duration_ms: float, discovery_complete: bool) -> None:
        with self._timing_lock:
            self._timings.append(duration_ms)
            self._discovery_complete = self._discovery_complete or discovery_complete
        self._wake.set()

    def close(self) -> None:
        """Request an asynchronous final snapshot without waiting for file I/O."""
        self._closing = True
        self._wake.set()

    def wait_closed(self, timeout: float | None = None) -> bool:
        """Wait for finalization outside Live's main thread (primarily for tests)."""
        return self._closed.wait(timeout)

    def _worker(self) -> None:
        try:
            last_write = 0.0
            while not self._closing:
                self._wake.wait(0.25)
                self._wake.clear()
                self._drain_coverage()
                now = time.monotonic()
                if now - last_write >= 1.0:
                    self._write_snapshot()
                    last_write = now
            self._drain_coverage()
            self._write_snapshot()
        finally:
            self._closed.set()

    def _drain_coverage(self) -> None:
        while True:
            try:
                entries = self._coverage_queue.get_nowait()
            except queue.Empty:
                return
            self._merge(entries)

    def _merge(self, entries: Iterable[CoverageEntry]) -> None:
        for entry in entries:
            key = (entry.object_type, entry.member)
            previous = self._coverage.get(key)
            if (
                previous is None
                or _STATUS_PRIORITY[entry.status] > _STATUS_PRIORITY[previous.status]
            ):
                self._coverage[key] = entry

    def _write_snapshot(self) -> None:
        with self._timing_lock:
            timings = sorted(self._timings)
            complete = self._discovery_complete and not self._dropped
        if not timings:
            return
        maximum = timings[-1]
        p95 = timings[max(0, (95 * len(timings) + 99) // 100 - 1)]
        records: list[dict[str, object]] = [
            {
                "kind": "run",
                "session_id": self._session_id,
                "live_version": self._live_version,
                "edition": self._edition,
                "discovery_complete": complete and self._expected <= self._coverage.keys(),
                "max_tick_duration_ms": maximum,
                "p95_tick_duration_ms": p95,
                "tick_count": len(timings),
            }
        ]
        for key in sorted(self._coverage):
            entry = self._coverage[key]
            record: dict[str, object] = {
                "kind": "member",
                "source_id": entry.source_id,
                "object_type": entry.object_type,
                "member": entry.member,
                "status": entry.status,
            }
            if entry.reason:
                record["reason"] = entry.reason
            records.append(record)
        payload = "".join(
            json.dumps(record, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
            for record in records
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        temporary.write_text(payload)
        os.replace(temporary, self._path)
