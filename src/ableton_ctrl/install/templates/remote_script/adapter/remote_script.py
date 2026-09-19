"""Minimal Ableton Remote Script wrapper; observation only, with no MIDI map."""

from __future__ import annotations

from time import monotonic
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from _Framework.ControlSurface import ControlSurface  # type: ignore[import-not-found]

from ableton_ctrl.adapter.evidence import CoverageEvidenceRecorder
from ableton_ctrl.adapter.compatibility import resolve_edition, runtime_supported, select_profile
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
        config = load_installed_config()
        profile = select_profile(version, allow_unverified=config.allow_unverified_live)
        edition = resolve_edition(config.edition)
        self._runtime = None
        self._version_status = profile.state
        if not runtime_supported((sys.version_info.major, sys.version_info.minor)):
            c_instance.show_message(
                "ableton-ctrl is disabled: unsupported embedded Python "
                f"{sys.version_info.major}.{sys.version_info.minor}"
            )
            return
        if not profile.enabled:
            c_instance.show_message(f"ableton-ctrl is disabled: {profile.reason}")
            return
        transport = SocketTransport(config.host, config.port, config.secret)
        session_id = str(uuid4())
        evidence = CoverageEvidenceRecorder(
            Path.home() / "Library" / "Logs" / "ableton-ctrl" / "coverage.jsonl",
            profile.manifest,
            session_id=session_id,
            live_version=profile.live_version,
            edition=edition.name,
            edition_source=edition.source,
            compatibility=profile.state,
        )
        self._runtime = AdapterRuntime(
            root=self.song(),
            manifest=profile.manifest,
            transport=transport,
            session_id=session_id,
            live_version=profile.live_version,
            edition=edition.name,
            edition_source=edition.source,
            compatibility=profile.state,
            evidence=evidence,
        )
        self._version_status = profile.state

    def update_display(self) -> None:
        if self._runtime is not None:
            self._runtime.tick(monotonic())

    def disconnect(self) -> None:
        if self._runtime is not None:
            self._runtime.disconnect()
            self._runtime.tick(monotonic())
        super().disconnect()
