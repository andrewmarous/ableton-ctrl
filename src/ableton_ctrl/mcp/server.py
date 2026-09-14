"""FastMCP stdio server exposing the read-only Ableton query surface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ableton_ctrl.config import load_or_create_config
from ableton_ctrl.contracts import (
    ChangesPayload,
    ChangesQuery,
    DeviceTreeQuery,
    GetObjectQuery,
    ListChildrenQuery,
    QueryResponse,
    ProjectSummaryQuery,
    ProjectDiffQuery,
    SchemaQuery,
    SearchQuery,
    SnapshotQuery,
    StatusPayload,
    StatusQuery,
    SelectionQuery,
    TrackSummaryQuery,
    ClipNotesQuery,
)
from ableton_ctrl.mcp.client import BridgeClient

_RESOURCE_DIRECTORY = Path(__file__).parent.parent / "resources"
_implicit_session_id: str | None = None
_implicit_revision: int | None = None
_implicit_bridge_generation: str | None = None

mcp = FastMCP(
    "Ableton Live Intro",
    instructions="Inspect the current Ableton Live set through a strictly read-only surface.",
)


def _client() -> BridgeClient:
    directory = os.environ.get("ABLETON_CTRL_CONFIG_DIR")
    return BridgeClient(load_or_create_config(Path(directory) if directory else None))


def _content(response: QueryResponse) -> dict[str, Any]:
    """Preserve bridge results and stable errors without interpretation."""
    return response.model_dump(mode="json", exclude_none=True)


async def _status() -> QueryResponse:
    return await _client().request(StatusQuery(type="status"))


@mcp.tool()
async def session_snapshot(
    depth: Annotated[int, Field(ge=0, le=8)] = 1,
    page_size: Annotated[int, Field(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Return a bounded overview of the active Live set and omitted-child references."""
    snapshot = _content(
        await _client().request(SnapshotQuery(type="snapshot", depth=depth, page_size=page_size))
    )
    status = _content(await _status())
    if snapshot.get("ok") is True and status.get("ok") is True:
        status_result = status.get("result")
        snapshot_result = snapshot.get("result")
        if isinstance(status_result, dict) and isinstance(snapshot_result, dict):
            outcome = status_result.get("runtime_outcome")
            action = status_result.get("runtime_action")
            if outcome is not None or action is not None:
                snapshot_result["adapter_runtime"] = {
                    "outcome": outcome,
                    "action": action,
                    "recovery": (
                        "Reduce the observed graph or adapter capacity pressure, then "
                        "reload or restart the ableton-ctrl Ableton Remote Script."
                    ),
                }
    return snapshot


@mcp.tool()
async def get_object(object_id: Annotated[str, Field(min_length=1)]) -> dict[str, Any]:
    """Return one object by opaque ID with properties, relationships, and read outcomes."""
    return _content(await _client().request(GetObjectQuery(type="get_object", object_id=object_id)))


@mcp.tool()
async def list_children(
    object_id: Annotated[str, Field(min_length=1)],
    relationship: Annotated[str, Field(min_length=1)],
    revision: Annotated[int, Field(ge=1)],
    start_index: Annotated[int, Field(ge=0)] = 0,
    page_size: Annotated[int, Field(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Traverse a named relationship with pagination pinned to a bridge revision."""
    query = ListChildrenQuery(
        type="list_children",
        object_id=object_id,
        relationship=relationship,
        revision=revision,
        offset=start_index,
        limit=page_size,
    )
    return _content(await _client().request(query))


@mcp.tool()
async def search(
    name: Annotated[str | None, Field(max_length=256)] = None,
    object_type: str | None = None,
    path: str | None = None,
    start_index: Annotated[int, Field(ge=0)] = 0,
    page_size: Annotated[int, Field(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Find cached objects by name, object type, or hierarchical path."""
    query = SearchQuery(
        type="search",
        name=name,
        object_type=object_type,
        path=path,
        offset=start_index,
        limit=page_size,
    )
    return _content(await _client().request(query))


@mcp.tool()
async def get_schema(object_type: str | None = None) -> dict[str, Any]:
    """Return runtime availability separately from documented learning metadata."""
    return _content(await _client().request(SchemaQuery(type="schema", object_type=object_type)))


@mcp.tool()
async def project_summary() -> dict[str, Any]:
    """Return deterministic project counts and observed arrangement extent."""
    return _content(await _client().request(ProjectSummaryQuery(type="project_summary")))


@mcp.tool()
async def track_summary(object_id: Annotated[str, Field(min_length=1)]) -> dict[str, Any]:
    """Return routing, devices, clips, sends, and mixer state for one track."""
    return _content(
        await _client().request(TrackSummaryQuery(type="track_summary", object_id=object_id))
    )


@mcp.tool()
async def device_tree(
    object_id: Annotated[str, Field(min_length=1)],
    depth: Annotated[int, Field(ge=0, le=8)] = 4,
    page_size: Annotated[int, Field(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Return a bounded rack, chain, pad, and device hierarchy."""
    return _content(
        await _client().request(
            DeviceTreeQuery(
                type="device_tree", object_id=object_id, depth=depth, page_size=page_size
            )
        )
    )


@mcp.tool()
async def selection() -> dict[str, Any]:
    """Return the current read-only Live selection view."""
    return _content(await _client().request(SelectionQuery(type="selection")))


@mcp.tool()
async def project_diff(
    session_id: Annotated[str, Field(min_length=1)],
    after_revision: Annotated[int, Field(ge=0)],
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Return deterministic human-readable changes from an explicit revision."""
    return _content(
        await _client().request(
            ProjectDiffQuery(
                type="project_diff",
                session_id=session_id,
                after_revision=after_revision,
                limit=limit,
            )
        )
    )

@mcp.tool()
async def clip_notes(
    session_id: Annotated[str, Field(min_length=1)],
    object_id: Annotated[str, Field(min_length=1)],
    from_beat: float,
    beat_span: Annotated[float, Field(gt=0, le=256)],
    from_pitch: Annotated[int, Field(ge=0, le=127)],
    pitch_span: Annotated[int, Field(ge=1, le=128)],
    note_limit: Annotated[int, Field(ge=1, le=1000)] = 500,
    deadline_ms: Annotated[int, Field(ge=100, le=5000)] = 2000,
) -> dict[str, Any]:
    """Read bounded MIDI clip notes without changing Live selection or content."""
    return _content(await _client().request(ClipNotesQuery(
        type="clip_notes", session_id=session_id, object_id=object_id,
        from_beat=from_beat, beat_span=beat_span, from_pitch=from_pitch,
        pitch_span=pitch_span, note_limit=note_limit, deadline_ms=deadline_ms,
    )))


@mcp.tool()
async def get_changes(
    after_revision: Annotated[int | None, Field(ge=0)] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Return revisioned changes, using a process-local cursor only when omitted."""
    global _implicit_bridge_generation, _implicit_revision, _implicit_session_id

    explicit = after_revision is not None
    status_response = await _status()
    if not status_response.ok:
        return _content(status_response)
    status = status_response.result
    assert isinstance(status, StatusPayload)
    if not status.live_connected or status.session_id is None:
        return {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": "live_offline",
                "message": "Ableton Live is offline.",
                "recovery": {"action": "start_live_and_wait_for_adapter"},
            },
        }
    cursor_reset = (
        _implicit_bridge_generation != status.bridge_generation
        or _implicit_session_id != status.session_id
    )
    if explicit or _implicit_revision is None or cursor_reset:
        session_id = status.session_id
        cursor = after_revision if explicit else 0
    else:
        assert _implicit_session_id is not None
        session_id = _implicit_session_id
        cursor = _implicit_revision
    assert cursor is not None

    response = await _client().request(
        ChangesQuery(
            type="changes",
            session_id=session_id,
            after_revision=cursor,
            limit=limit,
        )
    )
    if not explicit and response.ok:
        result = response.result
        assert isinstance(result, ChangesPayload)
        _implicit_session_id = result.session_id
        _implicit_bridge_generation = result.bridge_generation
        _implicit_revision = result.next_revision
    return _content(response)


def _resource(filename: str) -> str:
    return (_RESOURCE_DIRECTORY / filename).read_text(encoding="utf-8")


@mcp.resource("ableton://glossary", mime_type="application/json")
def glossary() -> str:
    """Ableton terminology learning metadata."""
    return _resource("glossary.json")


@mcp.resource("ableton://interpretation", mime_type="application/json")
def interpretation() -> str:
    """Guidance for interpreting observations and metadata."""
    return _resource("interpretation.json")


@mcp.resource(
    "ableton://limitations/live-12.4.2-intro",
    mime_type="application/json",
)
def limitations() -> str:
    """Known limitations of the exact supported Live target."""
    return _resource("live-12.4.2-intro-limitations.json")


def main() -> None:
    """Run the MCP server on stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
