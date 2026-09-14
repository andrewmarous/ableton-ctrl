"""Install global Pi resources for ableton-ctrl."""

from __future__ import annotations

import sys
import hashlib
import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Sequence

EXTENSION_RELATIVE_PATH = Path(".pi/agent/extensions/ableton-ctrl.ts")
CONTROLLER_RELATIVE_PATH = Path(".pi/agent/extensions/ableton-controller.ts")
SKILL_RELATIVE_PATH = Path(".pi/agent/skills/ableton-ctrl/SKILL.md")
MANIFEST_RELATIVE_PATH = Path(".pi/agent/ableton-ctrl-manifest.json")
BACKUP_RELATIVE_PATH = Path(".pi/agent/backups/ableton-ctrl")


def pi_extension_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / EXTENSION_RELATIVE_PATH


def pi_skill_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / SKILL_RELATIVE_PATH


def pi_controller_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / CONTROLLER_RELATIVE_PATH


def _artifact_text(package_path: str) -> str:
    return resources.files("ableton_ctrl").joinpath(package_path).read_text(encoding="utf-8")


def extension_artifact_text() -> str:
    return _artifact_text("pi_artifacts/extension/ableton-ctrl.ts")


def skill_artifact_text() -> str:
    return _artifact_text("pi_artifacts/skill/ableton-ctrl/SKILL.md")


def controller_artifact_text() -> str:
    return _artifact_text("pi_artifacts/extension/ableton-controller.ts")


def _existing_paths(paths: Sequence[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact_payloads(root: Path) -> dict[Path, str]:
    return {
        pi_extension_path(root): extension_artifact_text(),
        pi_controller_path(root): controller_artifact_text(),
        pi_skill_path(root): skill_artifact_text(),
    }


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_RELATIVE_PATH


def _write_manifest(root: Path, payloads: dict[Path, str]) -> None:
    path = _manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    checksums = {
        str(path.relative_to(root)): _sha256(text.encode()) for path, text in payloads.items()
    }
    path.write_text(
        json.dumps({"version": 1, "checksums": checksums}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def install_pi_artifacts(home: Path | None = None) -> list[Path]:
    root = home or Path.home()
    targets = [pi_extension_path(root), pi_controller_path(root), pi_skill_path(root)]
    existing = _existing_paths(targets)
    if existing:
        formatted = "\n".join(f"- {path}" for path in existing)
        raise FileExistsError(
            "Refusing to overwrite existing Pi ableton-ctrl artifact(s):\n"
            f"{formatted}\n"
            "Manually delete the old file(s) above before reinstalling with "
            "ableton-ctrl-install-pi."
        )

    extension_target, controller_target, skill_target = targets
    extension_target.parent.mkdir(parents=True, exist_ok=True)
    skill_target.parent.mkdir(parents=True, exist_ok=True)

    extension_target.write_text(extension_artifact_text(), encoding="utf-8")
    controller_target.write_text(controller_artifact_text(), encoding="utf-8")
    skill_target.write_text(skill_artifact_text(), encoding="utf-8")
    _write_manifest(root, _artifact_payloads(root))
    return targets


def upgrade_pi_artifacts(home: Path | None = None) -> list[Path]:
    """Replace only artifacts that still match the last managed checksums."""
    root = home or Path.home()
    manifest_path = _manifest_path(root)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checksums = manifest["checksums"]
    except (FileNotFoundError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FileExistsError(
            "A managed Pi manifest is absent or invalid. Refusing automatic replacement."
        ) from exc
    if not isinstance(checksums, dict):
        raise FileExistsError("The managed Pi checksums are invalid. Refusing replacement.")

    payloads = _artifact_payloads(root)
    modified: list[Path] = []
    for target in payloads:
        recorded = checksums.get(str(target.relative_to(root)))
        if not target.exists() or not isinstance(recorded, str):
            modified.append(target)
        elif _sha256(target.read_bytes()) != recorded:
            modified.append(target)
    if modified:
        formatted = "\n".join(f"- {path}" for path in modified)
        raise FileExistsError(
            "Refusing to replace user-modified or untracked Pi artifact(s):\n" + formatted
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / BACKUP_RELATIVE_PATH / timestamp
    for target, text in payloads.items():
        relative = target.relative_to(root)
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        target.write_text(text, encoding="utf-8")
    _write_manifest(root, payloads)
    return list(payloads)


def run(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv or [])
    if arguments not in ([], ["--upgrade"]):
        print("Usage: ableton-ctrl-install-pi [--upgrade]", file=sys.stderr)
        return 2
    try:
        installed = upgrade_pi_artifacts() if arguments else install_pi_artifacts()
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
