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


async def test_exposes_exact_read_only_surface(tmp_path: Path) -> None:
    async with mcp_session(tmp_path) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        resources = (await session.list_resources()).resources

    assert {tool.name for tool in tools} == {
        "session_snapshot",
        "get_object",
        "list_children",
        "search",
        "get_schema",
        "get_changes",
    }
    assert {str(resource.uri) for resource in resources} == {
        "ableton://glossary",
        "ableton://interpretation",
        "ableton://limitations/live-12.4.2-intro",
    }

    by_name = {tool.name: tool for tool in tools}
    assert by_name["session_snapshot"].inputSchema["properties"]["depth"]["maximum"] == 8
    assert by_name["session_snapshot"].inputSchema["properties"]["page_size"]["maximum"] == 200

    forbidden = ("set", "invoke", "execute", "eval", "create", "delete", "duplicate")
    for tool in tools:
        serialized_surface = json.dumps(
            {"name": tool.name, "schema": tool.inputSchema},
            sort_keys=True,
        ).casefold()
        assert not {word for word in forbidden if word in serialized_surface}, serialized_surface


async def test_tools_query_fixture_and_keep_explicit_cursor_nonmutating(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    _adapter_reader, adapter = await apply_fixture(bridge)
    try:
        async with mcp_session(tmp_path) as session:
            await session.initialize()
            snapshot = await call(session, "session_snapshot", {"depth": 1, "page_size": 1})
            assert snapshot["ok"] is True
            assert snapshot["result"]["bridge_revision"] == 1
            assert snapshot["result"]["cache_age_seconds"] > 0
            root = snapshot["result"]["root"]
            assert len(root["relationships"]["tracks"]["items"]) <= 1

            object_result = await call(session, "get_object", {"object_id": root["object_id"]})
            assert object_result["result"]["object"]["type"] == "Song"

            children = await call(
                session,
                "list_children",
                {
                    "object_id": root["object_id"],
                    "relationship": "tracks",
                    "revision": 1,
                    "page_size": 1,
                },
            )
            assert children["result"]["items"][0]["type"] == "Track"

            found = await call(session, "search", {"name": "TRACK 1"})
            assert found["ok"] is True
            assert any(item["path"] == "Live Set/Track 1" for item in found["result"]["items"])

            schema = await call(session, "get_schema", {"object_type": "Track"})
            member = schema["result"]["types"][0]["members"][0]
            assert "runtime_available" in member
            assert "manifest_metadata" in member

            first = await call(session, "get_changes", {})
            assert first["result"]["next_revision"] == 1
            explicit = await call(session, "get_changes", {"after_revision": 0})
            assert explicit["result"]["next_revision"] == 1
            second = await call(session, "get_changes", {})
            assert second["result"]["changes"] == []

        async with mcp_session(tmp_path) as restarted:
            await restarted.initialize()
            reset = await call(restarted, "get_changes", {})
            assert reset["result"]["changes"][0]["revision"] == 1
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()


async def test_session_snapshot_exposes_terminal_adapter_recovery(tmp_path: Path) -> None:
    bridge = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await bridge.start()
    write_config(tmp_path, bridge.port)
    reader, adapter = await apply_fixture(bridge)
    terminal = fixture_batch()
    terminal.update(
        {
            "observations": [],
            "removed_source_ids": [],
            "discovery_complete": False,
            "runtime_outcome": "partial_result",
            "runtime_action": "reduce_observation_size_or_capacity",
        }
    )
    await send_update(reader, adapter, terminal, expected_revision=2)
    try:
        async with mcp_session(tmp_path) as session:
            await session.initialize()
            snapshot = await call(session, "session_snapshot", {})
        assert snapshot["result"]["adapter_runtime"] == {
            "outcome": "partial_result",
            "action": "reduce_observation_size_or_capacity",
            "recovery": (
                "Reduce the observed graph or adapter capacity pressure, then reload "
                "or restart the ableton-ctrl Ableton Remote Script."
            ),
        }
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()


async def test_bridge_unavailability_is_a_stable_structured_error(tmp_path: Path) -> None:
    server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    server.close()
    await server.wait_closed()
    write_config(tmp_path, port)

    async with mcp_session(tmp_path) as session:
        await session.initialize()
        response = await call(session, "session_snapshot", {})

    assert response["error"]["code"] == "bridge_unavailable"
    assert response["error"]["recovery"] == {"action": "start_or_restart_bridge"}


async def test_maps_stale_cursor_session_change_live_offline_and_object_outcomes(
    tmp_path: Path,
) -> None:
    bridge = BridgeServer(
        host="127.0.0.1",
        port=0,
        secret=SECRET,
        store=GraphStore(history_limit=1),
    )
    await bridge.start()
    write_config(tmp_path, bridge.port)
    adapter_reader, adapter = await apply_fixture(bridge)
    try:
        async with mcp_session(tmp_path) as session:
            await session.initialize()
            snapshot = await call(session, "session_snapshot", {})
            root_id = snapshot["result"]["root"]["object_id"]
            assert (await call(session, "get_changes", {}))["result"]["next_revision"] == 1

            changed_batch = fixture_batch()
            changed_batch["captured_at"] = "2026-06-29T00:00:01Z"
            changed_batch["observations"][0]["properties"]["tempo"] = 121.0
            changed_batch["observations"][0]["outcomes"] = [
                {
                    "member": "signature_numerator",
                    "status": "read_failed",
                    "reason": "fixture failure",
                }
            ]
            await send_update(adapter_reader, adapter, changed_batch, expected_revision=2)

            stale = await call(session, "get_changes", {"after_revision": 0})
            assert stale["error"]["code"] == "stale_cursor"
            fetched = await call(session, "get_object", {"object_id": root_id})
            assert fetched["result"]["object"]["properties"]["tempo"] == 121.0
            assert fetched["result"]["object"]["outcomes"][0]["status"] == "read_failed"

            replacement_reader, replacement = await connect_adapter(bridge, "s2")
            replacement_batch = fixture_batch("s2")
            await send_update(
                replacement_reader,
                replacement,
                replacement_batch,
                expected_revision=1,
            )
            changed_session = await call(session, "get_changes", {})
            assert changed_session["error"]["code"] == "session_changed"
            old_object = await call(session, "get_object", {"object_id": root_id})
            assert old_object["error"]["code"] == "session_changed"

            replacement.close()
            await replacement.wait_closed()
            await wait_until_offline(bridge)
            retained = await call(session, "session_snapshot", {})
            assert retained["ok"] is True
            assert retained["result"]["cache_age_seconds"] > 0
            offline = await call(session, "get_changes", {"after_revision": 0})
            assert offline["error"]["code"] == "live_offline"
    finally:
        adapter.close()
        await adapter.wait_closed()
        await bridge.close()


async def test_learning_resources_are_complete_and_structured(tmp_path: Path) -> None:
    async with mcp_session(tmp_path) as session:
        await session.initialize()
        glossary = json.loads((await session.read_resource("ableton://glossary")).contents[0].text)
        interpretation = json.loads(
            (await session.read_resource("ableton://interpretation")).contents[0].text
        )
        limitations = json.loads(
            (await session.read_resource("ableton://limitations/live-12.4.2-intro"))
            .contents[0]
            .text
        )

    required_terms = {
        "Live Set",
        "Session View",
        "Arrangement View",
        "scene",
        "track",
        "return track",
        "master track",
        "clip slot",
        "audio clip",
        "MIDI clip",
        "device",
        "device parameter",
        "mixer",
        "routing",
        "automation",
        "selection",
        "beat time",
        "decibel",
        "normalized parameter",
        "revision",
        "capture time",
        "completeness",
    }
    assert {entry["term"] for entry in glossary["entries"]} == required_terms
    assert glossary["source_kind"] == "learning_metadata"
    assert interpretation["source_kind"] == "learning_metadata"
    assert limitations["source_kind"] == "learning_metadata"
    for entry in [*glossary["entries"], *interpretation["entries"]]:
        assert set(entry) == {"term", "description", "related_types", "source_kind"}
        assert entry["source_kind"] == "learning_metadata"

    interpretation_terms = {entry["term"] for entry in interpretation["entries"]}
    assert {"object type", "property", "relationship"} <= interpretation_terms
    assert limitations["target"] == {
        "product": "Ableton Live Intro",
        "version": "12.4.2",
    }
    limitation_text = " ".join(limitations["limitations"]).casefold()
    for phrase in (
        "undocumented",
        "max for live",
        "runtime discovery",
        "raw audio",
        "raw midi",
        "coverage report",
    ):
        assert phrase in limitation_text


@asynccontextmanager
async def mcp_session(tmp_path: Path) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command="uv",
        args=["run", "ableton-ctrl-mcp"],
        cwd=Path.cwd(),
        env={**os.environ, "ABLETON_CTRL_CONFIG_DIR": str(tmp_path)},
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


async def call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    assert result.isError is False
    assert result.structuredContent is not None
    value = result.structuredContent
    return value["result"] if set(value) == {"result"} else value


def write_config(directory: Path, port: int) -> None:
    (directory / "config.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": port, "secret": SECRET})
    )


async def apply_fixture(
    bridge: BridgeServer,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await connect_adapter(bridge, "s1")
    await send_update(reader, writer, fixture_batch(), expected_revision=1)
    return reader, writer


async def connect_adapter(
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
    return reader, writer


def fixture_batch(session_id: str = "s1") -> dict[str, Any]:
    batch: dict[str, Any] = json.loads(FIXTURE.read_text())
    batch["session_id"] = session_id
    return batch


async def send_update(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    batch: dict[str, Any],
    *,
    expected_revision: int,
) -> None:
    writer.write(json.dumps({"kind": "update", "batch": batch}).encode() + b"\n")
    await writer.drain()
    assert json.loads(await reader.readline())["bridge_revision"] == expected_revision


async def wait_until_offline(bridge: BridgeServer) -> None:
    for _ in range(20):
        if not bridge.store.status().live_connected:
            return
        await asyncio.sleep(0)
    raise AssertionError("bridge did not mark adapter offline")
