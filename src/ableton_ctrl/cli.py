"""Machine-oriented JSON CLI for Ableton inspection."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal, Sequence, cast
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ableton_ctrl.config import DEFAULT_CONFIG_DIRECTORY, load_or_create_config
from ableton_ctrl.contracts import (
    AdapterRuntimeMetadata,
    ChangesPayload,
    ChangesQuery,
    ErrorCode,
    GetObjectQuery,
    JsonValue,
    ListChildrenQuery,
    QueryError,
    QueryRequest,
    QueryResponse,
    ResourcePayload,
    ResourceQuery,
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
SUPPORTED_ACTIONS = ["snapshot", "object", "children", "search", "schema", "changes", "resource"]
UNKNOWN_ACTION_RECOVERY: dict[str, JsonValue] = cast(
    dict[str, JsonValue],
    {"action": "use_supported_action", "supported_actions": SUPPORTED_ACTIONS},
)
VALIDATION_RECOVERY: dict[str, JsonValue] = {"action": "fix_action_fields"}
RESOURCE_FILES = {
    "glossary": "glossary.json",
    "interpretation": "interpretation.json",
    "limitations": "live-12.4.2-intro-limitations.json",
}
SUPPORTED_RESOURCES = list(RESOURCE_FILES)
RESOURCE_RECOVERY: dict[str, JsonValue] = cast(
    dict[str, JsonValue],
    {"action": "choose_supported_resource", "supported_resources": SUPPORTED_RESOURCES},
)
RESOURCE_DIRECTORY = Path(__file__).parent / "resources"


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


class SchemaCommand(CliModel):
    action: Literal["schema"]
    object_type: str | None = None


class ChangesCommand(CliModel):
    action: Literal["changes"]
    session_id: str | None = Field(default=None, min_length=1)
    after_revision: int | None = Field(default=None, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def require_complete_explicit_cursor(self) -> "ChangesCommand":
        if self.after_revision is not None and self.session_id is None:
            raise ValueError("session_id is required when after_revision is provided")
        if self.session_id is not None and self.after_revision is None:
            raise ValueError("after_revision is required when session_id is provided")
        return self


class ResourceCommand(CliModel):
    action: Literal["resource"]
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must be non-empty")
        return value


CliCommand = (
    SnapshotCommand
    | ObjectCommand
    | ChildrenCommand
    | SearchCommand
    | SchemaCommand
    | ChangesCommand
    | ResourceCommand
)
ACTION_MODELS: dict[str, type[CliCommand]] = {
    "snapshot": SnapshotCommand,
    "object": ObjectCommand,
    "children": ChildrenCommand,
    "search": SearchCommand,
    "schema": SchemaCommand,
    "changes": ChangesCommand,
    "resource": ResourceCommand,
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
    if action == "changes":
        has_session_id = raw.get("session_id") is not None
        has_after_revision = raw.get("after_revision") is not None
        if has_session_id != has_after_revision:
            missing_field = "after_revision" if has_session_id else "session_id"
            provided_field = "session_id" if has_session_id else "after_revision"
            return None, _error_response(
                ErrorCode.VALIDATION_FAILED,
                "Invalid fields for action 'changes'.",
                {
                    "action": "fix_action_fields",
                    "details": [
                        {
                            "field": missing_field,
                            "reason": f"Required when {provided_field} is provided",
                        }
                    ],
                },
            )
    try:
        command = ACTION_MODELS[action].model_validate(raw)
    except ValidationError as exc:
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            f"Invalid fields for action '{action}'.",
            {"action": "fix_action_fields", "details": _validation_details(exc)},
        )
    if isinstance(command, ResourceCommand) and command.name not in RESOURCE_FILES:
        return None, _error_response(
            ErrorCode.VALIDATION_FAILED,
            f"Unknown ableton-ctrl resource: {command.name}.",
            RESOURCE_RECOVERY,
        )
    return command, None


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
        if command.session_id is None or command.after_revision is None:
            raise ValueError("implicit changes commands are dispatched by run()")
        return ChangesQuery(
            type="changes",
            session_id=command.session_id,
            after_revision=command.after_revision,
            limit=command.limit,
        )
    if isinstance(command, ResourceCommand):
        return ResourceQuery(type="resource", name=command.name)
    raise AssertionError(f"Unhandled CLI command: {command!r}")


ADAPTER_RUNTIME_RECOVERY = (
    "Reduce the observed graph or adapter capacity pressure, then reload "
    "or restart the ableton-ctrl Ableton Remote Script."
)


def _config_directory() -> Path | None:
    directory = os.environ.get("ABLETON_CTRL_CONFIG_DIR")
    return Path(directory) if directory else None


def _client() -> BridgeClient:
    config = load_or_create_config(_config_directory())
    return BridgeClient(config)


async def _dispatch_query(request: QueryRequest) -> QueryResponse:
    if isinstance(request, ResourceQuery):
        return _resource_response(request)

    client = _client()
    response = await client.request(request)
    if request.type == "snapshot":
        return await _with_adapter_runtime_metadata(client, response)
    return response


async def _dispatch_command(command: CliCommand) -> QueryResponse:
    if isinstance(command, ChangesCommand) and command.after_revision is None:
        return await _dispatch_implicit_changes(command)
    return await _dispatch_query(build_query(command))


async def _dispatch_implicit_changes(command: ChangesCommand) -> QueryResponse:
    client = _client()
    snapshot_response = await client.request(SnapshotQuery(type="snapshot", depth=0, page_size=1))
    if not snapshot_response.ok or not isinstance(snapshot_response.result, SnapshotPayload):
        return snapshot_response

    set_name = _set_name_from_snapshot(snapshot_response.result)
    if set_name is None:
        return _missing_set_name_response()

    cursor_path = _changes_cursor_path(set_name)
    after_revision = _read_cursor(cursor_path)
    response = await client.request(
        ChangesQuery(
            type="changes",
            session_id=snapshot_response.result.session_id,
            after_revision=after_revision,
            limit=command.limit,
        )
    )
    if response.ok and isinstance(response.result, ChangesPayload):
        _write_cursor(cursor_path, response.result.next_revision)
    return response


def _set_name_from_snapshot(snapshot: SnapshotPayload) -> str | None:
    root = snapshot.root
    if not isinstance(root, dict):
        return None
    properties = root.get("properties")
    if not isinstance(properties, dict):
        return None
    name = properties.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name


def _missing_set_name_response() -> QueryResponse:
    return QueryResponse(
        ok=False,
        completeness="unavailable",
        error=QueryError(
            code=ErrorCode.STALE_STATE,
            message="The current Ableton Live Set name could not be determined.",
            recovery={"action": "save_or_name_current_live_set"},
        ),
    )


def _changes_cursor_path(set_name: str) -> Path:
    config_directory = _config_directory() or DEFAULT_CONFIG_DIRECTORY
    return config_directory / "cursors" / "changes" / f"{quote(set_name, safe='')}.json"


def _read_cursor(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0
    revision = data.get("next_revision") if isinstance(data, dict) else None
    return revision if isinstance(revision, int) and revision >= 0 else 0


def _write_cursor(path: Path, next_revision: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps({"next_revision": next_revision}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.chmod(0o600)
    os.replace(temporary_path, path)


def _resource_response(request: ResourceQuery) -> QueryResponse:
    filename = RESOURCE_FILES[request.name]
    resource = json.loads((RESOURCE_DIRECTORY / filename).read_text(encoding="utf-8"))
    return QueryResponse(
        ok=True,
        completeness="complete",
        result=ResourcePayload(name=request.name, resource=resource),
    )


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

    response = asyncio.run(_dispatch_command(command))
    _print_response(response)
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    main()
