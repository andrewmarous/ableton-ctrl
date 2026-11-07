"""Install upstream AbletonMCP and native Pi configuration; no Live API adapter."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

FORK_COMMIT = "558abb654040f40b4f671df764f355350b2cf843"
PACKAGE = f"git+https://github.com/andrewmarous/ableton-live-mcp.git@{FORK_COMMIT}"
SERVER = "AbletonMCP"


def command(uvx: str, *args: str) -> list[str]:
    """Use the same immutable fork for installation, diagnostics, and MCP."""
    return [uvx, "--from", PACKAGE, "ableton-live-mcp", *args]


def installation_paths(home: Path, user_library: str | None = None,
                       wiki_path: Path | None = None) -> list[Path]:
    agent = home / ".pi/agent"
    override = user_library or os.environ.get("ABLETON_USER_LIBRARY")
    base = home / ("Documents" if platform.system() == "Windows" else "Music")
    library = Path(override).expanduser().absolute() if override else base / "Ableton/User Library"
    paths = [agent / "mcp.json", agent / "skills/ableton-ctrl/SKILL.md",
             agent / "extensions/ableton-ctrl.ts", agent / "extensions/ableton-controller.ts",
             library / "Remote Scripts/AbletonMCP/__init__.py"]
    wiki = wiki_path or agent / "ableton-wiki"
    if not wiki.exists():
        paths.append(wiki)
    return paths


def install(home: Path, uvx: str, user_library: str | None = None,
            wiki_path: Path | None = None) -> Path:
    agent = home / ".pi/agent"
    config = agent / "mcp.json"
    data = json.loads(config.read_text()) if config.exists() else {}
    servers = data.setdefault("mcpServers", {})
    entry = {
        "command": uvx,
        "args": command(uvx)[1:],
        "description": "Inspect and edit Ableton Live. Edits require an explicit user request.",
    }
    if SERVER in servers and servers[SERVER] != entry:
        raise ValueError("Existing AbletonMCP configuration differs. Review it before replacement.")
    skill = agent / "skills/ableton-ctrl/SKILL.md"
    extensions = [agent / "extensions" / name for name in
                  ("ableton-ctrl.ts", "ableton-controller.ts")]
    for target in [config, skill, *extensions]:
        if target.is_symlink():
            raise ValueError(f"Refusing to replace a symlink: {target}")
    from .kb import _write_json_atomic
    from .transaction import Transaction, backup_path
    from ableton_ctrl.wiki_templates import artifact_text, WIKI_FILES

    wiki = wiki_path or agent / "ableton-wiki"
    targets = installation_paths(home, user_library, wiki_path)
    backup = backup_path(home, "ableton-upstream")
    with Transaction(backup, targets):
        # Preserve the legacy backup layout as well as the transaction journal.
        for target in [config, skill, *extensions]:
            if target.exists():
                destination = backup / target.relative_to(agent)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, destination)
        install_command = command(uvx, "install")
        if user_library:
            install_command += ["--user-library", user_library]
        subprocess.run(install_command, check=True)
        servers[SERVER] = entry
        _write_json_atomic(config, data)
        skill.parent.mkdir(parents=True, exist_ok=True)
        text = artifact_text("pi_artifacts/skill/ableton-upstream/SKILL.md")
        skill.write_text(text.replace("~/.pi/agent/ableton-wiki", str(wiki)))
        if not wiki.exists():
            for relative in WIKI_FILES:
                target = wiki / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifact_text(f"pi_artifacts/wiki/{relative}"))
        for target in extensions:
            target.unlink(missing_ok=True)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "doctor"])
    parser.add_argument("--user-library")
    args = parser.parse_args()
    uvx = shutil.which("uvx")
    if not uvx:
        parser.error("Install uv before this command.")
    if args.action == "install":
        backup = install(Path.home(), uvx, args.user_library)
        print(f"Backup: {backup}")
        print("Restart Live. Select AbletonMCP in an unused Control Surface row, with Input/Output None.")
        print("Run /reload in Pi, then pi mcp list and ableton-upstream doctor.")
    else:
        doctor_command = command(uvx, "doctor", "--json")
        if args.user_library:
            doctor_command += ["--user-library", args.user_library]
        raise SystemExit(subprocess.run(doctor_command).returncode)
