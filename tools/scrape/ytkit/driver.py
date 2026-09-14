"""Browser construction and ownership for ytkit."""
from __future__ import annotations

import contextlib
import importlib.metadata
import os
from typing import Iterator


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def make_driver(headless: bool = False, profile_dir: str | None = None):
    """Construct the required backend. There is deliberately no fallback."""
    try:
        import undetected_chromedriver as uc
    except ImportError as exc:
        raise RuntimeError("undetected-chromedriver is required; run `uv sync`") from exc
    options = uc.ChromeOptions()
    options.add_argument("--window-position=-2400,-2400")
    options.add_argument("--mute-audio")
    if profile_dir:
        options.add_argument("--user-data-dir=" + os.fspath(profile_dir))
    if headless:
        options.add_argument("--headless=new")
    try:
        return uc.Chrome(options=options, use_subprocess=True)
    except Exception as exc:
        raise RuntimeError(
            "Chrome startup failed (undetected-chromedriver %s, selenium %s). "
            "Check that Chrome is installed and the profile directory is writable."
            % (_version("undetected-chromedriver"), _version("selenium"))) from exc


@contextlib.contextmanager
def browser_session(**kwargs) -> Iterator[object]:
    driver = make_driver(**kwargs)
    try:
        yield driver
    finally:
        driver.quit()


# Kept as a compatibility no-op. Modern uc owns its child-process setup.
@contextlib.contextmanager
def quiet_subprocesses():
    yield
