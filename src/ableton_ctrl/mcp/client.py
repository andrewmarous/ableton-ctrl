"""Bounded, authenticated client for one-shot bridge queries."""

from __future__ import annotations

import asyncio
import json

from ableton_ctrl.config import BridgeConfig
from ableton_ctrl.contracts import ErrorCode, QueryError, QueryRequest, QueryResponse

CONNECT_TIMEOUT_SECONDS = 1.0
RESPONSE_TIMEOUT_SECONDS = 5.0
RESPONSE_LIMIT_BYTES = 1_048_576


class BridgeClient:
    """Send one authenticated request on each bridge connection."""

    def __init__(self, config: BridgeConfig) -> None:
        self._config = config

    async def request(self, request: QueryRequest) -> QueryResponse:
        writer: asyncio.StreamWriter | None = None
        try:
            reader, connected_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._config.host,
                    self._config.port,
                    limit=RESPONSE_LIMIT_BYTES,
                ),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
            writer = connected_writer
            frame = {
                "protocol_version": 1,
                "role": "query",
                "secret": self._config.secret,
                "message": request.model_dump(mode="json"),
            }
            writer.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
            await writer.drain()
            raw = await asyncio.wait_for(
                reader.readline(),
                timeout=RESPONSE_TIMEOUT_SECONDS,
            )
            if not raw or len(raw) > RESPONSE_LIMIT_BYTES or not raw.endswith(b"\n"):
                return _bridge_unavailable()
            return QueryResponse.model_validate_json(raw)
        except (
            ConnectionError,
            OSError,
            TimeoutError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return _bridge_unavailable()
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass


def _bridge_unavailable() -> QueryResponse:
    return QueryResponse(
        ok=False,
        completeness="unavailable",
        error=QueryError(
            code=ErrorCode.BRIDGE_UNAVAILABLE,
            message="The local Ableton bridge is unavailable.",
            recovery={"action": "start_or_restart_bridge"},
        ),
    )
