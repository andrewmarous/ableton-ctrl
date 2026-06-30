import asyncio
import ast
import json
import logging
from pathlib import Path
from typing import Any

import pytest

import ableton_ctrl.bridge.server as server_module
from ableton_ctrl.bridge.server import FRAME_LIMIT, BridgeServer
from ableton_ctrl.bridge.store import GraphStore, StoreError

SECRET = "fixture-secret-that-is-at-least-forty-three-characters"
FIXTURE = Path("tests/fixtures/adapter/live-12.4.2-intro-basic.jsonl")


async def send(writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
    writer.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
    await writer.drain()


async def receive(reader: asyncio.StreamReader) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(reader.readline(), timeout=1))


async def connect(server: BridgeServer) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection("127.0.0.1", server.port)


def test_main_loads_config_and_serves_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    config = server_module.BridgeConfig(host="127.0.0.1", port=8765, secret=SECRET)
    served = False

    class FakeBridgeServer:
        def __init__(self, *, config: server_module.BridgeConfig, store: GraphStore) -> None:
            assert config == config_fixture
            assert isinstance(store, GraphStore)

        async def serve_forever(self) -> None:
            nonlocal served
            served = True

    config_fixture = config
    monkeypatch.setattr(server_module, "load_or_create_config", lambda: config)
    monkeypatch.setattr(server_module, "BridgeServer", FakeBridgeServer)

    server_module.main()

    assert served


def authentication(role: str, message: dict[str, Any], secret: str = SECRET) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "role": role,
        "secret": secret,
        "message": message,
    }


@pytest.fixture
async def bridge() -> BridgeServer:
    server = BridgeServer(host="127.0.0.1", port=0, secret=SECRET, store=GraphStore())
    await server.start()
    yield server
    await server.close()


async def authenticate_adapter(
    bridge: BridgeServer, session_id: str = "s1"
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await connect(bridge)
    await send(
        writer,
        authentication(
            "adapter",
            {"kind": "hello", "session_id": session_id, "live_version": "12.4.2"},
        ),
    )
    assert (await receive(reader))["ok"] is True
    return reader, writer


async def apply_fixture(
    bridge: BridgeServer, session_id: str = "s1", revision: int = 1
) -> asyncio.StreamWriter:
    reader, writer = await authenticate_adapter(bridge, session_id)
    batch = json.loads(FIXTURE.read_text())
    batch["session_id"] = session_id
    await send(writer, {"kind": "update", "batch": batch})
    assert (await receive(reader))["bridge_revision"] == revision
    return writer


async def test_multi_frame_update_is_applied_only_after_final_part(
    bridge: BridgeServer,
) -> None:
    reader, writer = await authenticate_adapter(bridge)
    batch = json.loads(FIXTURE.read_text())
    observations = batch.pop("observations")
    first = {
        "kind": "update_part",
        "transaction_id": "tx1",
        "part_index": 0,
        "final": False,
        "batch": batch | {"observations": observations[:1]},
    }
    second = {
        "kind": "update_part",
        "transaction_id": "tx1",
        "part_index": 1,
        "final": True,
        "batch": batch | {"observations": observations[1:]},
    }
    await send(writer, first)
    assert (await receive(reader))["ok"] is True
    assert bridge.store.status().bridge_revision == 0
    await send(writer, second)
    assert (await receive(reader))["bridge_revision"] == 1
    assert bridge.store.snapshot().root.type == "Song"
    writer.close()
    await writer.wait_closed()


@pytest.mark.parametrize("limit_kind", ["parts", "bytes", "observations", "removals"])
async def test_transaction_overflow_aborts_and_cleans_buffer(
    bridge: BridgeServer, monkeypatch: pytest.MonkeyPatch, limit_kind: str
) -> None:
    if limit_kind == "parts":
        monkeypatch.setattr(server_module, "TRANSACTION_PART_LIMIT", 0)
    elif limit_kind == "bytes":
        monkeypatch.setattr(server_module, "TRANSACTION_BYTE_LIMIT", 1)
    elif limit_kind == "observations":
        monkeypatch.setattr(server_module, "TRANSACTION_OBSERVATION_LIMIT", 0)
    else:
        monkeypatch.setattr(server_module, "TRANSACTION_REMOVAL_LIMIT", 0)
    reader, writer = await authenticate_adapter(bridge)
    batch = json.loads(FIXTURE.read_text())
    if limit_kind == "removals":
        batch["removed_source_ids"] = ["gone"]
        batch["observations"] = []
    await send(
        writer,
        {
            "kind": "update_part",
            "transaction_id": "overflow",
            "part_index": 0,
            "final": False,
            "batch": batch,
        },
    )
    response = await receive(reader)
    assert response["error"]["code"] == "transaction_too_large"
    assert bridge._update_transactions == {}
    assert bridge.store.status().bridge_revision == 0
    writer.close()
    await writer.wait_closed()


async def test_interrupted_transaction_is_discarded_before_reconnect(
    bridge: BridgeServer,
) -> None:
    reader, writer = await authenticate_adapter(bridge)
    batch = json.loads(FIXTURE.read_text())
    await send(
        writer,
        {
            "kind": "update_part",
            "transaction_id": "interrupted",
            "part_index": 0,
            "final": False,
            "batch": batch | {"observations": batch["observations"][:1]},
        },
    )
    assert (await receive(reader))["ok"] is True
    writer.close()
    await writer.wait_closed()
    await asyncio.sleep(0)
    assert bridge.store.status().bridge_revision == 0
    replacement = await apply_fixture(bridge)
    assert bridge.store.status().bridge_revision == 1
    replacement.close()
    await replacement.wait_closed()


async def test_final_part_rejection_publishes_no_complete_fragment_and_reconnects(
    bridge: BridgeServer,
) -> None:
    reader, writer = await authenticate_adapter(bridge)
    batch = json.loads(FIXTURE.read_text())
    bad = dict(batch["observations"][0])
    bad["relationships"] = {"tracks": ["missing"]}
    await send(
        writer,
        {
            "kind": "update_part",
            "transaction_id": "rejected",
            "part_index": 0,
            "final": True,
            "batch": batch | {"observations": [bad]},
        },
    )
    assert (await receive(reader))["error"]["code"] == "invalid_request"
    assert bridge.store.status().bridge_revision == 0
    writer.close()
    await writer.wait_closed()
    replacement = await apply_fixture(bridge)
    assert bridge.store.status().completeness == "complete"
    replacement.close()
    await replacement.wait_closed()


async def test_wrong_secret_returns_authentication_failed_and_closes(
    bridge: BridgeServer,
) -> None:
    reader, writer = await connect(bridge)
    await send(
        writer,
        authentication(
            "adapter",
            {"kind": "hello", "session_id": "s1", "live_version": "12.4.2"},
            "wrong",
        ),
    )
    response = await receive(reader)
    assert response["error"]["code"] == "authentication_failed"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


async def test_non_ascii_attacker_secret_is_rejected_and_connection_closes(
    bridge: BridgeServer,
) -> None:
    reader, writer = await connect(bridge)
    await send(
        writer,
        authentication(
            "adapter",
            {"kind": "hello", "session_id": "s1", "live_version": "12.4.2"},
            "wrong-秘密-🔐",
        ),
    )
    assert (await receive(reader))["error"]["code"] == "authentication_failed"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


async def test_authenticated_update_is_visible_to_query(bridge: BridgeServer) -> None:
    adapter = await apply_fixture(bridge)
    reader, query = await connect(bridge)
    await send(
        query,
        authentication("query", {"protocol_version": 1, "type": "status"}),
    )
    response = await receive(reader)
    assert response["ok"] is True
    assert response["bridge_revision"] == 1
    adapter.close()
    query.close()
    await adapter.wait_closed()
    await query.wait_closed()


def test_bridge_rejects_non_loopback_host() -> None:
    with pytest.raises(ValueError, match="^bridge host must be loopback$"):
        BridgeServer(host="0.0.0.0", port=0, secret=SECRET, store=GraphStore())


@pytest.mark.parametrize("operation", ["set_property", "invoke", "eval", "update"])
async def test_query_role_rejects_mutation_without_changing_graph_or_leaking_secret(
    bridge: BridgeServer, operation: str
) -> None:
    adapter = await apply_fixture(bridge)
    before = bridge.store.snapshot(depth=8, page_size=200).root.model_dump_json()
    reader, query = await connect(bridge)
    await send(query, authentication("query", {"type": operation, "value": SECRET}))
    raw_response = await asyncio.wait_for(reader.readline(), timeout=1)
    response = json.loads(raw_response)
    assert response["error"]["code"] == "invalid_request"
    assert SECRET.encode() not in raw_response
    assert bridge.store.snapshot(depth=8, page_size=200).root.model_dump_json() == before
    adapter.close()
    query.close()
    await adapter.wait_closed()
    await query.wait_closed()


async def test_same_session_resumes_and_new_session_invalidates_query_cursor(
    bridge: BridgeServer,
) -> None:
    first_adapter = await apply_fixture(bridge)
    first_adapter.close()
    await first_adapter.wait_closed()
    for _ in range(10):
        if not bridge.store.status().live_connected:
            break
        await asyncio.sleep(0)
    assert bridge.store.status().live_connected is False
    assert bridge.store.snapshot(depth=8, page_size=200).bridge_revision == 1

    resumed = await apply_fixture(bridge, revision=2)
    assert bridge.store.status().session_id == "s1"
    resumed.close()
    await resumed.wait_closed()

    replacement = await apply_fixture(bridge, "s2")
    reader, query = await connect(bridge)
    await send(
        query,
        authentication(
            "query",
            {
                "protocol_version": 1,
                "type": "changes",
                "session_id": "s1",
                "after_revision": 1,
            },
        ),
    )
    assert (await receive(reader))["error"]["code"] == "session_changed"
    replacement.close()
    query.close()
    await replacement.wait_closed()
    await query.wait_closed()


async def test_new_session_supersedes_old_adapter_and_active_disconnect_marks_offline(
    bridge: BridgeServer,
) -> None:
    old_reader, old_writer = await authenticate_adapter(bridge, "s1")
    first_batch = json.loads(FIXTURE.read_text())
    await send(old_writer, {"kind": "update", "batch": first_batch})
    assert (await receive(old_reader))["bridge_revision"] == 1
    old_id = bridge.store.snapshot(depth=0, page_size=20).root.object_id

    new_reader, new_writer = await authenticate_adapter(bridge, "s2")
    second_batch = json.loads(FIXTURE.read_text())
    second_batch["session_id"] = "s2"
    await send(new_writer, {"kind": "update", "batch": second_batch})
    assert (await receive(new_reader))["bridge_revision"] == 1

    with pytest.raises(StoreError, match="session_changed"):
        bridge.store.get_object(old_id)
    with pytest.raises(StoreError, match="session_changed"):
        bridge.store.get_changes("s1", 1)

    new_writer.close()
    await new_writer.wait_closed()
    for _ in range(10):
        if not bridge.store.status().live_connected:
            break
        await asyncio.sleep(0)
    assert bridge.store.status().live_connected is False

    await send(old_writer, {"kind": "update", "batch": first_batch})
    assert (await receive(old_reader))["error"]["code"] == "invalid_request"
    assert await asyncio.wait_for(old_reader.read(), timeout=1) == b""
    assert bridge.store.status().session_id == "s2"
    assert bridge.store.status().live_connected is False
    old_writer.close()
    await old_writer.wait_closed()


async def test_malformed_json_is_audited_and_closed(
    bridge: BridgeServer, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ableton_ctrl.bridge.server")
    reader, writer = await connect(bridge)
    writer.write(b'{"secret":"' + SECRET.encode() + b'",malformed}\n')
    await writer.drain()
    raw = await asyncio.wait_for(reader.readline(), timeout=1)
    assert json.loads(raw)["error"]["code"] == "invalid_request"
    assert SECRET.encode() not in raw
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    assert SECRET not in caplog.text
    writer.close()
    await writer.wait_closed()


async def test_oversized_frame_is_rejected_without_echoing_content(
    bridge: BridgeServer,
) -> None:
    reader, writer = await connect(bridge)
    writer.write(b"x" * (FRAME_LIMIT + 1) + b"\n")
    await writer.drain()
    assert (await receive(reader))["error"]["code"] == "frame_too_large"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


async def test_unterminated_frame_is_rejected(bridge: BridgeServer) -> None:
    reader, writer = await connect(bridge)
    writer.write(b"{}")
    await writer.drain()
    writer.write_eof()
    assert (await receive(reader))["error"]["code"] == "frame_too_large"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


@pytest.mark.parametrize(
    "frame",
    [
        {"protocol_version": 2, "role": "query", "secret": SECRET},
        {"role": "query", "secret": SECRET},
        {"protocol_version": 1, "secret": SECRET},
        {"protocol_version": 1, "role": "query"},
    ],
)
async def test_protocol_mismatch_and_missing_auth_fields_are_rejected(
    bridge: BridgeServer, frame: dict[str, Any]
) -> None:
    reader, writer = await connect(bridge)
    await send(writer, frame)
    assert (await receive(reader))["error"]["code"] == "authentication_failed"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


async def test_adapter_role_cannot_issue_query(bridge: BridgeServer) -> None:
    reader, writer = await authenticate_adapter(bridge)
    await send(writer, {"protocol_version": 1, "type": "status"})
    assert (await receive(reader))["error"]["code"] == "invalid_request"
    assert await asyncio.wait_for(reader.read(), timeout=1) == b""
    writer.close()
    await writer.wait_closed()


async def test_failure_audit_and_response_redact_secret_and_payload(
    bridge: BridgeServer, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ableton_ctrl.bridge.server")
    reader, writer = await connect(bridge)
    attacker_payload = "do-not-log-this-request"
    await send(
        writer,
        authentication(
            "query",
            {"type": "eval", "value": attacker_payload, "secret_copy": SECRET},
        ),
    )
    raw = await asyncio.wait_for(reader.readline(), timeout=1)
    assert json.loads(raw)["error"]["code"] == "invalid_request"
    assert SECRET.encode() not in raw
    assert attacker_payload.encode() not in raw

    failure_records = [
        ast.literal_eval(record.getMessage())
        for record in caplog.records
        if "request_failed" in record.getMessage()
    ]
    assert failure_records
    assert all(
        set(record)
        <= {
            "event",
            "role",
            "session_id_hash",
            "revision",
            "error_code",
        }
        for record in failure_records
    )
    assert SECRET not in caplog.text
    assert attacker_payload not in caplog.text
    writer.close()
    await writer.wait_closed()
