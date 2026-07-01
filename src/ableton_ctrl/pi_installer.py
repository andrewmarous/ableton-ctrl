"""Install global Pi resources for ableton-ctrl."""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path
from typing import Sequence

EXTENSION_RELATIVE_PATH = Path(".pi/agent/extensions/ableton-ctrl.ts")
SKILL_RELATIVE_PATH = Path(".pi/agent/skills/ableton-ctrl/SKILL.md")


def pi_extension_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / EXTENSION_RELATIVE_PATH


def pi_skill_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / SKILL_RELATIVE_PATH


def _artifact_text(package_path: str) -> str:
    return resources.files("ableton_ctrl").joinpath(package_path).read_text(encoding="utf-8")


def extension_artifact_text() -> str:
    return _artifact_text("pi_artifacts/extension/ableton-ctrl.ts")


def skill_artifact_text() -> str:
    return _artifact_text("pi_artifacts/skill/ableton-ctrl/SKILL.md")


def _existing_paths(paths: Sequence[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def install_pi_artifacts(home: Path | None = None) -> list[Path]:
    root = home or Path.home()
    targets = [pi_extension_path(root), pi_skill_path(root)]
    existing = _existing_paths(targets)
    if existing:
        formatted = "\n".join(f"- {path}" for path in existing)
        raise FileExistsError(
            "Refusing to overwrite existing Pi ableton-ctrl artifact(s):\n"
            f"{formatted}\n"
            "Manually delete the old file(s) above before reinstalling with "
            "ableton-ctrl-install-pi."
        )

    extension_target, skill_target = targets
    extension_target.parent.mkdir(parents=True, exist_ok=True)
    skill_target.parent.mkdir(parents=True, exist_ok=True)

    extension_target.write_text(extension_artifact_text(), encoding="utf-8")
    skill_target.write_text(skill_artifact_text(), encoding="utf-8")
    return targets


def run(argv: Sequence[str] | None = None) -> int:
    if argv:
        print("ableton-ctrl-install-pi does not accept arguments.", file=sys.stderr)
        return 2
    try:
        installed = install_pi_artifacts()
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for path in installed:
        print(f"Installed {path}")
    print("Run /reload in Pi or restart Pi to load ableton_ctrl.")
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
