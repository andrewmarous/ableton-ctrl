"""Minimal Ableton Remote Script wrapper; observation only, with no MIDI map."""

from __future__ import annotations

from time import monotonic
from pathlib import Path
from typing import Any
from uuid import uuid4

from _Framework.ControlSurface import ControlSurface  # type: ignore[import-not-found]

from ableton_ctrl.adapter.evidence import CoverageEvidenceRecorder
from ableton_ctrl.adapter.manifest import LIVE_12_4_2_INTRO_MANIFEST
from ableton_ctrl.adapter.runtime import AdapterRuntime, SocketTransport
from ableton_ctrl.config import BridgeConfig, load_or_create_config


def load_installed_config() -> BridgeConfig:
    return load_or_create_config()


def create_instance(c_instance: Any) -> AbletonCtrlSurface:
    return AbletonCtrlSurface(c_instance)


class AbletonCtrlSurface(ControlSurface):  # type: ignore[misc]
    def __init__(self, c_instance: Any) -> None:
        super().__init__(c_instance)
        application = self.application()
        version = (
            application.get_major_version(),
            application.get_minor_version(),
            application.get_bugfix_version(),
        )
        edition = str(application.get_product_name())
        self._runtime = None
        self._version_status = "version_mismatch"
        if version != (12, 4, 2) or "Intro" not in edition:
            c_instance.show_message(
                f"ableton-ctrl requires Live 12.4.2 Intro; found "
                f"{version[0]}.{version[1]}.{version[2]} {edition}"
            )
            return
        config = load_installed_config()
        transport = SocketTransport(config.host, config.port, config.secret)
        session_id = str(uuid4())
        evidence = CoverageEvidenceRecorder(
            Path.home() / "Library" / "Logs" / "ableton-ctrl" / "coverage.jsonl",
            LIVE_12_4_2_INTRO_MANIFEST,
            session_id=session_id,
            live_version="12.4.2",
            edition="Intro",
        )
        self._runtime = AdapterRuntime(
            root=self.song(),
            manifest=LIVE_12_4_2_INTRO_MANIFEST,
            transport=transport,
            session_id=session_id,
            live_version="12.4.2",
            edition="Intro",
            evidence=evidence,
        )
        self._version_status = "supported"

    def update_display(self) -> None:
        if self._runtime is not None:
            self._runtime.tick(monotonic())

    def disconnect(self) -> None:
        if self._runtime is not None:
            self._runtime.disconnect()
            self._runtime.tick(monotonic())
        super().disconnect()
