"""Packaged production wiki templates and workflow resources."""
from importlib import resources

WIKI_FILES = (
    "AGENTS.md",
    "README.md",
    "raw/.gitkeep",
    "raw/assets/.gitkeep",
    "wiki/index.md",
    "wiki/log.md",
    "wiki/sources/.gitkeep",
    "wiki/how-to/.gitkeep",
    "wiki/concepts/.gitkeep",
    "wiki/techniques/.gitkeep",
    "wiki/devices/.gitkeep",
    "wiki/genres/.gitkeep",
    "wiki/analyses/.gitkeep",
)


def artifact_text(package_path: str) -> str:
    return resources.files("ableton_ctrl").joinpath(package_path).read_text(encoding="utf-8")
