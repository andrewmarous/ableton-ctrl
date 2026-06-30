import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ableton_ctrl.bridge.server import BridgeServer
from ableton_ctrl.bridge.store import GraphStore

SECRET = "fixture-secret-that-is-at-least-forty-three-characters"
FIXTURE = Path("tests/fixtures/adapter/live-12.4.2-intro-basic.jsonl")


async def test_full_path_fixture_replay_and_session_invalidation(tmp_path: Path) -> None:
    bridge = BridgeServer("127.0.0.1", 0, SECRET, GraphStore())
    await bridge.start()
    (tmp_path / "config.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": bridge.port, "secret": SECRET})
    )
    adapter = await replay_fixture(bridge, "fixture-session")
    try:
        async with mcp_session(tmp_path) as session:
            await session.initialize()
            snapshot = await call_tool(session, "session_snapshot", {"depth": 1, "page_size": 20})
            assert snapshot["live_version"] == "12.4.2"
            assert snapshot["completeness"] in {"complete", "partial"}
            track_id = snapshot["root"]["relationships"]["tracks"]["items"][0]["object_id"]
            track = await call_tool(session, "get_object", {"object_id": track_id})
            assert track["object"]["type"] == "Track"
            assert "captured_at" in track and "bridge_revision" in track

            updated = fixture_record("fixture-session")
            updated["captured_at"] = "2026-06-29T00:00:01Z"
            updated["observations"][1]["captured_at"] = "2026-06-29T00:00:01Z"
            updated["observations"][1]["properties"]["name"] = "Renamed"
            updated["removed_source_ids"] = ["song"]
            await send_update(adapter, updated, 2)
            changes = await call_tool(session, "get_changes", {"after_revision": 1})
            kinds = {
                change["kind"]
                for change_set in changes["changes"]
                for change in change_set["changes"]
            }
            assert {"properties_changed", "removed"} <= kinds

            replacement = await replay_fixture(bridge, "replacement-session")
            try:
                old = await call_tool(session, "get_object", {"object_id": track_id})
                assert old["error"]["code"] == "session_changed"
            finally:
                replacement[1].close()
                await replacement[1].wait_closed()
    finally:
        adapter[1].close()
        await adapter[1].wait_closed()
        await bridge.close()


async def replay_fixture(
    bridge: BridgeServer,
    session_id: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", bridge.port)
    hello = {
        "protocol_version": 1,
        "role": "adapter",
        "secret": SECRET,
        "message": {
            "kind": "hello",
            "session_id": session_id,
            "live_version": "12.4.2",
        },
    }
    writer.write(json.dumps(hello).encode() + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["ok"] is True
    revision = 0
    for line in FIXTURE.read_text().splitlines():
        if not line.strip():
            continue
        revision += 1
        record: dict[str, Any] = json.loads(line)
        record["session_id"] = session_id
        await send_update((reader, writer), record, revision)
    return reader, writer


async def send_update(
    adapter: tuple[asyncio.StreamReader, asyncio.StreamWriter],
    record: dict[str, Any],
    expected_revision: int,
) -> None:
    reader, writer = adapter
    writer.write(json.dumps({"kind": "update", "batch": record}).encode() + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["bridge_revision"] == expected_revision


def fixture_record(session_id: str) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(FIXTURE.read_text())
    record["session_id"] = session_id
    return record


@asynccontextmanager
async def mcp_session(tmp_path: Path) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command="uv",
        args=["run", "ableton-ctrl-mcp"],
        cwd=Path.cwd(),
        env={**os.environ, "ABLETON_CTRL_CONFIG_DIR": str(tmp_path)},
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            yield session


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    assert result.structuredContent is not None
    value = result.structuredContent
    if set(value) == {"result"}:
        value = value["result"]
    if value.get("ok") is True and isinstance(value.get("result"), dict):
        return value["result"]
    return value
