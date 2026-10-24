"""Install upstream AbletonMCP and native Pi configuration; no Live API adapter."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = "mcp-server-ableton-live@1.8.1"
SERVER = "AbletonMCP"


def install(home: Path, uvx: str, user_library: str | None = None) -> Path:
    agent = home / ".pi/agent"
    config = agent / "mcp.json"
    data = json.loads(config.read_text()) if config.exists() else {}
    servers = data.setdefault("mcpServers", {})
    entry = {
        "command": uvx,
        "args": [PACKAGE],
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
    # Let upstream validate and install its own matching Remote Script first.
    command = [uvx, PACKAGE, "install"]
    if user_library:
        command += ["--user-library", user_library]
    subprocess.run(command, check=True)
    backup = agent / "backups/ableton-upstream" / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ")
    for target in [config, skill, *extensions]:
        if target.exists():
            destination = backup / target.relative_to(agent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    servers[SERVER] = entry
    agent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(config)
    from ableton_ctrl.wiki_templates import artifact_text, WIKI_FILES
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(artifact_text("pi_artifacts/skill/ableton-upstream/SKILL.md"))
    wiki = agent / "ableton-wiki"
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
        command = [uvx, PACKAGE, "doctor", "--json"]
        if args.user_library:
            command += ["--user-library", args.user_library]
        raise SystemExit(subprocess.run(command).returncode)
