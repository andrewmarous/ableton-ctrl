"""Authenticated, read-only JSON Lines bridge bound to the loopback interface."""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import signal
from uuid import uuid4
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import TypeAdapter, ValidationError

from ableton_ctrl.bridge.store import GraphStore, StoreError
from ableton_ctrl.bridge.store import SchemaMemberDefinition
from ableton_ctrl.adapter.manifest import LIVE_12_MANIFEST
from ableton_ctrl.config import BridgeConfig, load_or_create_config
from ableton_ctrl.contracts import (
    ChangesPayload,
    ChildrenPayload,
    DeviceTreePayload,
    DeviceTreeQuery,
    ObjectPayload,
    ProjectSummaryPayload,
    ProjectSummaryQuery,
    ProjectDiffPayload,
    ProjectDiffQuery,
    QueryPayload,
    QueryRequest,
    QueryResponse,
    SchemaPayload,
    SearchPayload,
    SnapshotPayload,
    StatusPayload,
    UpdateBatch,
    SelectionPayload,
    SelectionQuery,
    TrackSummaryPayload,
    TrackSummaryQuery,
    ClipNotesPayload,
    ClipNotesQuery,
)

FRAME_LIMIT = 1_048_576
TRANSACTION_PART_LIMIT = 128
TRANSACTION_BYTE_LIMIT = 64 * FRAME_LIMIT
TRANSACTION_OBSERVATION_LIMIT = 10_000
TRANSACTION_REMOVAL_LIMIT = 10_000
_QUERY_ADAPTER: TypeAdapter[QueryRequest] = TypeAdapter(QueryRequest)
_LOGGER = logging.getLogger(__name__)


def _live_12_schema_metadata() -> dict[str, dict[str, SchemaMemberDefinition]]:
    result: dict[str, dict[str, SchemaMemberDefinition]] = {}
    for type_name, spec in LIVE_12_MANIFEST.items():
        members: dict[str, SchemaMemberDefinition] = {}
        for property_member in spec.properties:
            members[property_member.name] = SchemaMemberDefinition(
                kind="property",
                manifest_metadata={
                    "description": property_member.description,
                    "unit": property_member.unit,
                    "poll_class": property_member.poll_class,
                    "exclusion_reason": property_member.exclusion_reason,
                },
            )
        for relationship_member in spec.relationships:
            members[relationship_member.name] = SchemaMemberDefinition(
                kind="relationship",
                manifest_metadata={
                    "description": relationship_member.description,
                    "target_type": relationship_member.target_type,
                    "cardinality": relationship_member.cardinality,
                },
            )
        result[type_name] = members
    return result


class BridgeServer:
    """Serve adapter updates and graph queries over an authenticated local socket."""

    def __init__(
        self,
        host: str | BridgeConfig | None = None,
        port: int | GraphStore | None = None,
        secret: str | None = None,
        store: GraphStore | None = None,
        *,
        config: BridgeConfig | None = None,
        instance_id: str | None = None,
    ) -> None:
        if isinstance(host, BridgeConfig):
            if config is not None:
                raise TypeError("provide either host or config")
            if isinstance(port, GraphStore):
                if store is not None:
                    raise TypeError("provide store once")
                store = port
            config = host
            host = None
        if config is not None:
            host = config.host
            port = config.port
            secret = config.secret
        if host is None or not isinstance(port, int) or secret is None or store is None:
            raise TypeError("host, port, secret, and store are required")
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError("bridge host must be loopback")
        if not 0 <= port <= 65535:
            raise ValueError("bridge port must be between 0 and 65535")

        self.host = host
        self._configured_port = port
        self._secret = secret
        self.store = store
        self.instance_id = instance_id
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.StreamWriter] = set()
        self._adapter_generation = 0
        self._active_adapter_generation: int | None = None
        self._update_transactions: dict[int, tuple[str, int, dict[str, Any], int, int]] = {}
        self._active_adapter_writer: asyncio.StreamWriter | None = None
        self._read_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._configured_port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self._configured_port,
            limit=FRAME_LIMIT,
        )
        self._log("bridge_started")

    async def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
        writers = tuple(self._connections)
        for writer in writers:
            writer.close()
        if server is not None:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=1.0)
            except TimeoutError:
                self._log("listener_cleanup_timeout")
        if writers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(writer.wait_closed() for writer in writers), return_exceptions=True
                    ),
                    timeout=1.0,
                )
            except TimeoutError:
                self._log("connection_cleanup_timeout")
        self._log("bridge_stopped")

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        await self._server.serve_forever()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._connections.add(writer)
        role: Literal["adapter", "query"] | None = None
        adapter_session: str | None = None
        adapter_generation: int | None = None
        try:
            first = await self._read_frame(reader, writer)
            if first is None:
                return
            role, message = self._authenticate(first)
            if role is None:
                attempted_role, attempted_session = self._authentication_context(first)
                self._audit_failure(
                    "authentication_failed",
                    role=attempted_role,
                    session_id=attempted_session,
                )
                await self._send_error(writer, "authentication_failed")
                return
            self._log("authenticated", role=role, level=logging.DEBUG)

            if role == "adapter":
                adapter_session = self._validate_hello(message)
                if adapter_session is None:
                    self._audit_failure("invalid_request", role="adapter")
                    await self._send_error(writer, "invalid_request")
                    return
                self._adapter_generation += 1
                adapter_generation = self._adapter_generation
                self._active_adapter_generation = adapter_generation
                self._active_adapter_writer = writer
                await self._send(writer, {"protocol_version": 1, "ok": True})
            elif message is not None:
                if not await self._dispatch_query(message, writer):
                    return

            while True:
                frame = await self._read_frame(reader, writer)
                if frame is None:
                    return
                if role == "adapter":
                    if not await self._dispatch_adapter(
                        frame,
                        adapter_session,
                        adapter_generation,
                        writer,
                    ):
                        return
                elif not await self._dispatch_query(frame, writer):
                    return
        except asyncio.CancelledError:
            raise
        except ConnectionError:
            pass
        finally:
            self._connections.discard(writer)
            if (
                adapter_generation is not None
                and self._active_adapter_generation == adapter_generation
            ):
                self._active_adapter_generation = None
                if self._active_adapter_writer is writer:
                    self._active_adapter_writer = None
                for future in self._read_requests.values():
                    if not future.done():
                        future.set_exception(ConnectionError("adapter disconnected"))
                self._read_requests.clear()
                self._update_transactions.pop(adapter_generation, None)
                self.store.mark_offline()
                self._log(
                    "adapter_disconnected",
                    role="adapter",
                    session_id=adapter_session,
                )
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def _read_frame(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> dict[str, Any] | None:
        try:
            raw = await reader.readline()
        except ValueError:
            self._audit_failure("frame_too_large")
            await self._send_error(writer, "frame_too_large")
            return None
        if not raw:
            return None
        if len(raw) > FRAME_LIMIT or not raw.endswith(b"\n"):
            self._audit_failure("frame_too_large")
            await self._send_error(writer, "frame_too_large")
            return None
        try:
            value = json.loads(
                raw,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid constant {value}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._audit_failure("invalid_request")
            await self._send_error(writer, "invalid_request")
            return None
        if not isinstance(value, dict):
            self._audit_failure("invalid_request")
            await self._send_error(writer, "invalid_request")
            return None
        return value

    def _authenticate(
        self, frame: Mapping[str, Any]
    ) -> tuple[Literal["adapter", "query"] | None, dict[str, Any] | None]:
        supplied_secret = frame.get("secret")
        role = frame.get("role")
        protocol_version = frame.get("protocol_version")
        message = frame.get("message")
        valid_secret = False
        if isinstance(supplied_secret, str):
            valid_secret = hmac.compare_digest(
                supplied_secret.encode("utf-8"),
                self._secret.encode("utf-8"),
            )
        valid_role = role in ("adapter", "query")
        valid_message = message is None or isinstance(message, dict)
        if protocol_version != 1 or not valid_role or not valid_secret or not valid_message:
            return None, None
        return role, message

    @staticmethod
    def _authentication_context(
        frame: Mapping[str, Any],
    ) -> tuple[Literal["adapter", "query"] | None, str | None]:
        raw_role = frame.get("role")
        role: Literal["adapter", "query"] | None = (
            raw_role if raw_role in ("adapter", "query") else None
        )
        message = frame.get("message")
        session_id = message.get("session_id") if isinstance(message, dict) else None
        return role, session_id if isinstance(session_id, str) else None

    @staticmethod
    def _validate_hello(message: dict[str, Any] | None) -> str | None:
        if (
            message is None
            or message.get("kind") != "hello"
            or not isinstance(message.get("session_id"), str)
            or not message["session_id"]
            or not isinstance(message.get("live_version"), str)
        ):
            return None
        return str(message["session_id"])

    async def _dispatch_adapter(
        self,
        frame: dict[str, Any],
        session_id: str | None,
        generation: int | None,
        writer: asyncio.StreamWriter,
    ) -> bool:
        if generation is None or generation != self._active_adapter_generation:
            self._audit_failure(
                "invalid_request",
                role="adapter",
                session_id=session_id,
            )
            await self._send_error(writer, "invalid_request")
            return False
        kind = frame.get("kind")
        if kind == "read_response":
            request_id = frame.get("request_id")
            future = self._read_requests.pop(request_id, None) if isinstance(request_id, str) else None
            if future is not None and not future.done():
                future.set_result(frame)
            await self._send(writer, {"protocol_version": 1, "ok": True})
            return True
        if kind == "disconnect":
            await self._send(writer, {"protocol_version": 1, "ok": True})
            return False
        if kind == "update_part":
            transaction_id = frame.get("transaction_id")
            part_index = frame.get("part_index")
            final = frame.get("final")
            part = frame.get("batch")
            if not (
                isinstance(transaction_id, str)
                and isinstance(part_index, int)
                and isinstance(final, bool)
                and isinstance(part, dict)
                and isinstance(part.get("observations"), list)
                and isinstance(part.get("removed_source_ids"), list)
            ):
                await self._send_error(writer, "invalid_request")
                return False
            current = self._update_transactions.get(generation)
            part_bytes = len(json.dumps(frame, separators=(",", ":")).encode()) + 1
            if current is None:
                if part_index != 0:
                    await self._send_error(writer, "invalid_request")
                    return False
                combined = dict(part)
                combined["observations"] = list(part["observations"])
                combined["removed_source_ids"] = list(part["removed_source_ids"])
                total_bytes = part_bytes
                part_count = 1
            else:
                current_id, expected_index, combined, total_bytes, part_count = current
                if current_id != transaction_id or part_index != expected_index:
                    await self._send_error(writer, "invalid_request")
                    return False
                combined["observations"].extend(part["observations"])
                combined["removed_source_ids"].extend(part["removed_source_ids"])
                total_bytes += part_bytes
                part_count += 1
            if (
                part_count > TRANSACTION_PART_LIMIT
                or total_bytes > TRANSACTION_BYTE_LIMIT
                or len(combined["observations"]) > TRANSACTION_OBSERVATION_LIMIT
                or len(combined["removed_source_ids"]) > TRANSACTION_REMOVAL_LIMIT
            ):
                self._update_transactions.pop(generation, None)
                await self._send_error(writer, "transaction_too_large")
                return False
            if not final:
                self._update_transactions[generation] = (
                    transaction_id,
                    part_index + 1,
                    combined,
                    total_bytes,
                    part_count,
                )
                await self._send(writer, {"protocol_version": 1, "ok": True})
                return True
            self._update_transactions.pop(generation, None)
            frame = {"kind": "update", "batch": combined}
            kind = "update"
        if kind != "update":
            self._audit_failure(
                "invalid_request",
                role="adapter",
                session_id=session_id,
            )
            await self._send_error(writer, "invalid_request")
            return False
        candidate = frame.get("batch", frame.get("message"))
        if candidate is None:
            candidate = {key: value for key, value in frame.items() if key != "kind"}
        try:
            batch = UpdateBatch.model_validate(candidate)
            if batch.session_id != session_id:
                raise ValueError("adapter session changed")
            revision = self.store.apply(batch)
        except (ValidationError, ValueError):
            self._audit_failure(
                "invalid_request",
                role="adapter",
                session_id=session_id,
            )
            await self._send_error(writer, "invalid_request")
            return False
        except StoreError as error:
            await self._send_store_error(writer, error, role="adapter")
            return False
        self._log(
            "update_applied",
            role="adapter",
            session_id=session_id,
            revision=revision,
            level=logging.DEBUG,
        )
        await self._send(
            writer,
            {"protocol_version": 1, "ok": True, "bridge_revision": revision},
        )
        return True

    async def _dispatch_query(
        self,
        frame: dict[str, Any],
        writer: asyncio.StreamWriter,
    ) -> bool:
        if frame.get("kind") == "query" and isinstance(frame.get("request"), dict):
            frame = frame["request"]
        try:
            request = _QUERY_ADAPTER.validate_python(frame)
            if isinstance(request, ClipNotesQuery):
                return await self._dispatch_clip_notes(request, writer)
            result = self._execute_query(request)
        except ValidationError:
            self._audit_failure("invalid_request", role="query")
            await self._send_error(writer, "invalid_request")
            return False
        except StoreError as error:
            await self._send_store_error(writer, error, role="query")
            return True

        response = self._query_response(request, result)
        payload = response.model_dump(mode="json", exclude_none=True)
        await self._send(
            writer,
            payload,
        )
        self._log(
            "query_completed",
            role="query",
            session_id=response.session_id,
            revision=response.bridge_revision,
            level=logging.DEBUG,
        )
        return True

    async def _dispatch_clip_notes(self, request: ClipNotesQuery, writer: asyncio.StreamWriter) -> bool:
        try:
            source_id, _ = self.store.read_target(request.object_id, request.session_id)
            adapter = self._active_adapter_writer
            if adapter is None:
                raise StoreError("live_offline", "adapter is offline")
            request_id = uuid4().hex
            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._read_requests[request_id] = future
            await self._send(adapter, {"kind": "read_request", "request_id": request_id, "session_id": request.session_id, "source_id": source_id, **request.model_dump(exclude={"type", "session_id", "object_id"})})
            frame = await asyncio.wait_for(future, timeout=request.deadline_ms / 1000)
            if frame.get("ok") is not True or not isinstance(frame.get("notes"), list):
                raise StoreError("read_failed", "clip note read failed")
            status = self.store.status()
            metadata = {key: value for key, value in status.model_dump(exclude_none=True).items() if key in {"live_version", "edition", "edition_source", "compatibility", "session_id", "bridge_generation", "bridge_revision", "captured_at", "cache_age_seconds", "completeness"}}
            if frame.get("truncated") is True:
                metadata["completeness"] = "partial"
            payload = ClipNotesPayload(notes=frame["notes"], truncated=bool(frame.get("truncated", False)), requested_range={"from_beat": request.from_beat, "beat_span": request.beat_span, "from_pitch": request.from_pitch, "pitch_span": request.pitch_span}, **metadata)
            await self._send(writer, QueryResponse(ok=True, result=payload, **metadata).model_dump(mode="json", exclude_none=True))
            return True
        except (StoreError, TimeoutError, asyncio.TimeoutError, ConnectionError):
            await self._send_error(writer, "read_failed")
            return True
        finally:
            self._read_requests.pop(locals().get("request_id", ""), None)

    @staticmethod
    def _query_response(request: QueryRequest, result: Any) -> QueryResponse:
        raw = result.model_dump(mode="json")
        metadata = {
            key: raw[key]
            for key in (
                "live_version",
                "edition",
                "edition_source",
                "compatibility",
                "session_id",
                "bridge_generation",
                "bridge_revision",
                "captured_at",
                "cache_age_seconds",
                "completeness",
            )
        }
        payload: QueryPayload
        if request.type == "status":
            payload = StatusPayload(
                live_connected=raw["live_connected"],
                runtime_outcome=raw["runtime_outcome"],
                runtime_action=raw["runtime_action"],
                **metadata,
            )
        elif request.type == "snapshot":
            payload = SnapshotPayload(root=raw["root"], **metadata)
        elif request.type == "get_object":
            object_value = {
                key: raw[key]
                for key in (
                    "object_id",
                    "type",
                    "path",
                    "properties",
                    "relationships",
                    "outcomes",
                    "object_captured_at",
                )
            }
            payload = ObjectPayload(object=object_value, **metadata)
        elif request.type == "list_children":
            payload = ChildrenPayload(
                items=raw["items"],
                continuation=raw["continuation"],
                **metadata,
            )
        elif request.type == "search":
            payload = SearchPayload(
                items=raw["items"],
                continuation=raw["continuation"],
                **metadata,
            )
        elif request.type == "schema":
            payload = SchemaPayload(types=raw["types"], **metadata)
        elif request.type == "changes":
            payload = ChangesPayload(
                changes=raw["changes"],
                next_revision=raw["next_revision"],
                **metadata,
            )
        elif request.type == "project_summary":
            payload = ProjectSummaryPayload(summary=raw["value"], **metadata)
        elif request.type == "track_summary":
            payload = TrackSummaryPayload(summary=raw["value"], **metadata)
        elif request.type == "device_tree":
            payload = DeviceTreePayload(tree=raw["value"], **metadata)
        elif request.type == "selection":
            payload = SelectionPayload(selection=raw["value"], **metadata)
        elif request.type == "project_diff":
            payload = ProjectDiffPayload(diff=raw["value"], **metadata)
        else:
            raise ValueError("resource queries are handled by the CLI before bridge dispatch")
        return QueryResponse(ok=True, result=payload, **metadata)

    def _execute_query(self, request: QueryRequest) -> Any:
        if request.type == "status":
            return self.store.status(request.stale_after_seconds)
        if request.type == "snapshot":
            return self.store.snapshot(request.depth, request.page_size)
        if request.type == "get_object":
            return self.store.get_object(request.object_id)
        if request.type == "list_children":
            return self.store.list_children(
                request.object_id,
                request.relationship,
                request.offset,
                request.limit,
                request.revision,
            )
        if request.type == "search":
            return self.store.search(
                request.name,
                request.object_type,
                request.path,
                request.offset,
                request.limit,
            )
        if request.type == "schema":
            return self.store.get_schema(request.object_type)
        if request.type == "changes":
            return self.store.get_changes(
                request.session_id,
                request.after_revision,
                request.limit,
            )
        if isinstance(request, ProjectSummaryQuery):
            return self.store.project_summary()
        if isinstance(request, TrackSummaryQuery):
            return self.store.track_summary(request.object_id)
        if isinstance(request, DeviceTreeQuery):
            return self.store.device_tree(request.object_id, request.depth, request.page_size)
        if isinstance(request, SelectionQuery):
            return self.store.selection()
        if isinstance(request, ProjectDiffQuery):
            return self.store.project_diff(
                request.session_id, request.after_revision, request.limit
            )
        raise ValueError("resource queries are handled by the CLI before bridge dispatch")

    async def _send_store_error(
        self,
        writer: asyncio.StreamWriter,
        error: StoreError,
        *,
        role: str,
    ) -> None:
        stable_codes = {
            "live_offline",
            "stale_state",
            "session_changed",
            "unsupported_property",
            "read_failed",
            "partial_result",
            "stale_cursor",
            "bridge_unavailable",
        }
        code = error.code if error.code in stable_codes else "invalid_request"
        self._log("request_failed", role=role, error_code=code)
        await self._send_error(writer, code)

    async def _send_error(self, writer: asyncio.StreamWriter, code: str) -> None:
        await self._send(
            writer,
            {
                "protocol_version": 1,
                "ok": False,
                "live_version": None,
                "session_id": None,
                "bridge_revision": None,
                "captured_at": None,
                "cache_age_seconds": None,
                "completeness": "unavailable",
                "error": {"code": code, "message": code.replace("_", " ")},
            },
        )

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, value: Mapping[str, Any]) -> None:
        writer.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")
        await writer.drain()

    @staticmethod
    def _log(
        event: str,
        *,
        role: str | None = None,
        session_id: str | None = None,
        revision: int | None = None,
        error_code: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        fields: dict[str, str | int] = {"event": event}
        if role is not None:
            fields["role"] = role
        if session_id is not None:
            fields["session_id_hash"] = hashlib.sha256(session_id.encode()).hexdigest()[:12]
        if revision is not None:
            fields["revision"] = revision
        if error_code is not None:
            fields["error_code"] = error_code
        _LOGGER.log(level, "%s", fields)

    def _audit_failure(
        self,
        error_code: str,
        *,
        role: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._log(
            "request_failed",
            role=role,
            session_id=session_id,
            error_code=error_code,
        )


async def _wait_for_supervisor(fd: int) -> None:
    """Return when the inherited parent-liveness pipe reaches EOF."""
    loop = asyncio.get_running_loop()
    finished: asyncio.Future[None] = loop.create_future()

    def readable() -> None:
        try:
            data = os.read(fd, 1)
        except OSError:
            data = b""
        if not data and not finished.done():
            finished.set_result(None)

    loop.add_reader(fd, readable)
    try:
        await finished
    finally:
        loop.remove_reader(fd)
        os.close(fd)


async def _run_bridge(config: BridgeConfig, instance_id: str | None, supervision_fd: int | None) -> None:
    server = BridgeServer(
        config=config,
        store=GraphStore(schema_metadata=_live_12_schema_metadata()),
        instance_id=instance_id,
    )
    await server.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(stop.wait())]
    if supervision_fd is not None:
        tasks.append(asyncio.create_task(_wait_for_supervisor(supervision_fd)))
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await server.close()


def main() -> None:
    """Run the bridge until signalled or its supervising parent disappears."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id")
    parser.add_argument("--supervision-fd", type=int)
    arguments, _unknown = parser.parse_known_args()
    configured_directory = os.environ.get("ABLETON_CTRL_CONFIG_DIR")
    config = (
        load_or_create_config(Path(configured_directory))
        if configured_directory
        else load_or_create_config()
    )
    try:
        if arguments.instance_id is None and arguments.supervision_fd is None:
            server = BridgeServer(
                config=config,
                store=GraphStore(schema_metadata=_live_12_schema_metadata()),
            )
            asyncio.run(server.serve_forever())
        else:
            asyncio.run(_run_bridge(config, arguments.instance_id, arguments.supervision_fd))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
