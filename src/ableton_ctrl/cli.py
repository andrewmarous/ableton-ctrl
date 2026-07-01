"""Machine-oriented JSON CLI for Ableton inspection."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal, Sequence, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ableton_ctrl.config import load_or_create_config
from ableton_ctrl.contracts import (
    AdapterRuntimeMetadata,
    ChangesQuery,
    ErrorCode,
    GetObjectQuery,
    JsonValue,
    ListChildrenQuery,
    QueryError,
    QueryRequest,
    QueryResponse,
    SnapshotPayload,
    SchemaQuery,
    SearchQuery,
    SnapshotQuery,
    StatusPayload,
    StatusQuery,
)
from ableton_ctrl.mcp.client import BridgeClient

CLI_USAGE_RECOVERY: dict[str, JsonValue] = {"action": "call_with_one_json_argument"}
INVALID_JSON_RECOVERY: dict[str, JsonValue] = {"action": "pass_valid_json_object"}
SUPPORTED_ACTIONS = ["snapshot", "object", "children", "search", "schema", "changes"]
UNKNOWN_ACTION_RECOVERY: dict[str, JsonValue] = cast(
    dict[str, JsonValue],
    {"action": "use_supported_action", "supported_actions": SUPPORTED_ACTIONS},
)
VALIDATION_RECOVERY: dict[str, JsonValue] = {"action": "fix_action_fields"}


class CliModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotCommand(CliModel):
    action: Literal["snapshot"]
    depth: int = Field(default=1, ge=0, le=8)
    page_size: int = Field(default=20, ge=1, le=200)


class ObjectCommand(CliModel):
    action: Literal["object"]
    object_id: str = Field(min_length=1)

    @field_validator("object_id")
    @classmethod
    def reject_blank_object_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("object_id must be non-empty")
        return value


class ChildrenCommand(CliModel):
    action: Literal["children"]
    object_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    revision: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="before")
    @classmethod
    def accept_mcp_pagination_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "start_index" in normalized and "offset" not in normalized:
            normalized["offset"] = normalized.pop("start_index")
        if "page_size" in normalized and "limit" not in normalized:
            normalized["limit"] = normalized.pop("page_size")
        return normalized

    @field_validator("object_id", "relationship")
    @classmethod
    def reject_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


class SearchCommand(CliModel):
    action: Literal["search"]
    name: str | None = Field(default=None, max_length=256)
    object_type: str | None = None
    path: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)


class SchemaCommand(CliModel):
    action: Literal["schema"]
    object_type: str | None = None


class ChangesCommand(CliModel):
    action: Literal["changes"]
    session_id: str = Field(min_length=1)
    after_revision: int = Field(ge=0)
    limit: int = Field(default=100, ge=1, le=500)


CliCommand = (
    SnapshotCommand
    | ObjectCommand
    | ChildrenCommand
    | SearchCommand
    | SchemaCommand
    | ChangesCommand
)
ACTION_MODELS: dict[str, type[CliCommand]] = {
    "snapshot": SnapshotCommand,
    "object": ObjectCommand,
    "children": ChildrenCommand,
    "search": SearchCommand,
    "schema": SchemaCommand,
    "changes": ChangesCommand,
}


def _error_response(code: ErrorCode, message: str, recovery: dict[str, JsonValue]) -> QueryResponse:
    return QueryResponse(
        ok=False,
        completeness="unavailable",
        error=QueryError(code=code, message=message, recovery=recovery),
    )


def _print_response(response: QueryResponse) -> None:
    print(response.model_dump_json(exclude_none=True))


def _parse_json_argument(argv: Sequence[str]) -> tuple[dict[str, Any] | None, QueryResponse | None]:
    if len(argv) != 1:
        return None, _error_response(
            ErrorCode.INVALID_INVOCATION,
            "ableton-ctrl expects exactly one JSON argument.",
            CLI_USAGE_RECOVERY,
        )
    try:
        raw = json.loads(argv[0])
    except json.JSONDecodeError:
        return None, _error_response(
            ErrorCode.INVALID_JSON,
            "ableton-ctrl argument must be a JSON object.",
            INVALID_JSON_RECOVERY,
        )
    if not isinstance(raw, dict):
        return None, _error_response(
            ErrorCode.INVALID_JSON,
            "ableton-ctrl argument must be a JSON object.",
            INVALID_JSON_RECOVERY,
        )
    return raw, None


def _validation_details(exc: ValidationError) -> list[JsonValue]:
    details: list[JsonValue] = []
    for item in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = item.get("loc", ())
        field = str(loc[-1]) if loc else "action"
        reason = str(item.get("msg", "Invalid value"))
        details.append({"field": field, "reason": reason})
    return details


def _validate_command(raw: dict[str, Any]) -> tuple[CliCommand | None, QueryResponse | None]:
    action = raw.get("action")
    if not isinstance(action, str):
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            "Invalid fields for action envelope.",
            cast(
                dict[str, JsonValue],
                {
                    "action": "fix_action_fields",
                    "details": [{"field": "action", "reason": "Field required"}],
                },
            ),
        )
    if action not in SUPPORTED_ACTIONS:
        return None, _error_response(
            ErrorCode.UNKNOWN_ACTION,
            f"Unknown ableton-ctrl action: {action}.",
            UNKNOWN_ACTION_RECOVERY,
        )
    try:
        return ACTION_MODELS[action].model_validate(raw), None
    except ValidationError as exc:
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            f"Invalid fields for action '{action}'.",
            {"action": "fix_action_fields", "details": _validation_details(exc)},
        )


def build_query(command: CliCommand) -> QueryRequest:
    if isinstance(command, SnapshotCommand):
        return SnapshotQuery(type="snapshot", depth=command.depth, page_size=command.page_size)
    if isinstance(command, ObjectCommand):
        return GetObjectQuery(type="get_object", object_id=command.object_id)
    if isinstance(command, ChildrenCommand):
        return ListChildrenQuery(
            type="list_children",
            object_id=command.object_id,
            relationship=command.relationship,
            revision=command.revision,
            offset=command.offset,
            limit=command.limit,
        )
    if isinstance(command, SearchCommand):
        return SearchQuery(
            type="search",
            name=command.name,
            object_type=command.object_type,
            path=command.path,
            offset=command.offset,
            limit=command.limit,
        )
    if isinstance(command, SchemaCommand):
        return SchemaQuery(type="schema", object_type=command.object_type)
    if isinstance(command, ChangesCommand):
        return ChangesQuery(
            type="changes",
            session_id=command.session_id,
            after_revision=command.after_revision,
            limit=command.limit,
        )
    raise AssertionError(f"Unhandled CLI command: {command!r}")


ADAPTER_RUNTIME_RECOVERY = (
    "Reduce the observed graph or adapter capacity pressure, then reload "
    "or restart the ableton-ctrl Ableton Remote Script."
)


def _client() -> BridgeClient:
    directory = os.environ.get("ABLETON_CTRL_CONFIG_DIR")
    config = load_or_create_config(Path(directory) if directory else None)
    return BridgeClient(config)


async def _dispatch_query(request: QueryRequest) -> QueryResponse:
    client = _client()
    response = await client.request(request)
    if request.type == "snapshot":
        return await _with_adapter_runtime_metadata(client, response)
    return response


async def _with_adapter_runtime_metadata(
    client: BridgeClient, response: QueryResponse
) -> QueryResponse:
    if not response.ok or not isinstance(response.result, SnapshotPayload):
        return response

    status_response = await client.request(StatusQuery(type="status"))
    if not status_response.ok or not isinstance(status_response.result, StatusPayload):
        return response

    outcome = status_response.result.runtime_outcome
    action = status_response.result.runtime_action
    if outcome is None and action is None:
        return response

    response.result.adapter_runtime = AdapterRuntimeMetadata(
        outcome=outcome,
        action=action,
        recovery=ADAPTER_RUNTIME_RECOVERY,
    )
    return response


def run(argv: Sequence[str]) -> int:
    raw, parse_error = _parse_json_argument(argv)
    if parse_error is not None:
        _print_response(parse_error)
        return 2
    assert raw is not None

    command, validation_error = _validate_command(raw)
    if validation_error is not None:
        _print_response(validation_error)
        return 2
    assert command is not None

    response = asyncio.run(_dispatch_query(build_query(command)))
    _print_response(response)
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    main()
