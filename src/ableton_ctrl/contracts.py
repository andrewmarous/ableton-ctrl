"""Shared, transport-neutral protocol contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue as PydanticJsonValue,
    model_validator,
)

JsonScalar: TypeAlias = str | int | float | bool | None


def _reject_non_finite(value: PydanticJsonValue) -> PydanticJsonValue:
    if isinstance(value, float) and not (float("-inf") < value < float("inf")):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
    return value


JsonValue: TypeAlias = Annotated[PydanticJsonValue, AfterValidator(_reject_non_finite)]


class OutcomeStatus(StrEnum):
    """All possible classifications for an attempted Live member."""

    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"
    READ_FAILED = "read_failed"
    EXCLUDED = "excluded"


class ErrorCode(StrEnum):
    """Stable errors exposed to clients."""

    LIVE_OFFLINE = "live_offline"
    STALE_STATE = "stale_state"
    SESSION_CHANGED = "session_changed"
    UNSUPPORTED_PROPERTY = "unsupported_property"
    READ_FAILED = "read_failed"
    PARTIAL_RESULT = "partial_result"
    STALE_CURSOR = "stale_cursor"
    BRIDGE_UNAVAILABLE = "bridge_unavailable"
    INVALID_INVOCATION = "invalid_invocation"
    INVALID_JSON = "invalid_json"
    UNKNOWN_ACTION = "unknown_action"
    VALIDATION_FAILED = "validation_failed"


class BridgeProtocolErrorCode(StrEnum):
    """Transport errors private to the adapter-to-bridge protocol."""

    AUTHENTICATION_FAILED = "authentication_failed"
    INVALID_REQUEST = "invalid_request"
    FRAME_TOO_LARGE = "frame_too_large"
    TRANSACTION_TOO_LARGE = "transaction_too_large"


class MemberOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member: str
    status: Literal["unavailable", "read_failed", "excluded"]
    reason: str = Field(min_length=1)


class ObjectObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    type: str
    path: str | None
    properties: dict[str, JsonValue]
    relationships: dict[str, list[str]]
    outcomes: list[MemberOutcome]
    captured_at: datetime
    update_mode: Literal["replace", "patch"] = "replace"
    attempted_members: list[str] = Field(default_factory=list)


class UpdateBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    session_id: str = Field(min_length=1)
    live_version: str
    captured_at: datetime
    observations: list[ObjectObservation]
    removed_source_ids: list[str]
    discovery_complete: bool = False
    replace_graph: bool = False
    resync_generation: int | None = Field(default=None, ge=1)
    runtime_outcome: Literal["partial_result"] | None = None
    runtime_action: Literal["reduce_observation_size_or_capacity"] | None = None


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1


class StatusQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["status"]
    stale_after_seconds: float = Field(default=5.0, gt=0)


class SnapshotQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["snapshot"]
    depth: int = Field(default=1, ge=0, le=8)
    page_size: int = Field(default=20, ge=1, le=200)


class GetObjectQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["get_object"]
    object_id: str = Field(min_length=1)


class ListChildrenQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["list_children"]
    object_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)
    revision: int = Field(ge=1)


class SearchQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["search"]
    name: str | None = Field(default=None, max_length=256)
    object_type: str | None = None
    path: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=200)


class SchemaQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["schema"]
    object_type: str | None = None


class ChangesQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["changes"]
    session_id: str = Field(min_length=1)
    after_revision: int = Field(ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ResourceQuery(QueryModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["resource"]
    name: str = Field(min_length=1)


QueryRequest: TypeAlias = Annotated[
    StatusQuery
    | SnapshotQuery
    | GetObjectQuery
    | ListChildrenQuery
    | SearchQuery
    | SchemaQuery
    | ChangesQuery
    | ResourceQuery,
    Field(discriminator="type"),
]


class QueryError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    recovery: dict[str, JsonValue] | None = None


class QueryMetadata(BaseModel):
    """Metadata shared by successful queries against an active session."""

    model_config = ConfigDict(extra="forbid")

    live_version: str
    session_id: str = Field(min_length=1)
    bridge_revision: int = Field(ge=0)
    captured_at: datetime
    cache_age_seconds: float = Field(ge=0)
    completeness: Literal["complete", "partial"]


class StatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["status"] = "status"
    live_connected: bool
    live_version: str | None
    session_id: str | None
    bridge_revision: int = Field(ge=0)
    captured_at: datetime | None
    cache_age_seconds: float | None = Field(ge=0)
    completeness: Literal["complete", "partial", "unavailable"]
    runtime_outcome: Literal["partial_result"] | None = None
    runtime_action: Literal["reduce_observation_size_or_capacity"] | None = None


class AdapterRuntimeMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["partial_result"] | None = None
    action: Literal["reduce_observation_size_or_capacity"] | None = None
    recovery: str = Field(min_length=1)


class SnapshotPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["snapshot"] = "snapshot"
    root: JsonValue
    adapter_runtime: AdapterRuntimeMetadata | None = None


class ObjectPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["get_object"] = "get_object"
    object: JsonValue


class ChildrenPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["list_children"] = "list_children"
    items: list[JsonValue]
    continuation: str | None = None


class SearchPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["search"] = "search"
    items: list[JsonValue]
    continuation: str | None = None


class SchemaPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["schema"] = "schema"
    types: list[JsonValue]


class ChangesPayload(QueryMetadata):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["changes"] = "changes"
    changes: list[JsonValue]
    next_revision: int = Field(ge=0)


class ResourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource"] = "resource"
    name: str = Field(min_length=1)
    resource: JsonValue


QueryPayload: TypeAlias = Annotated[
    StatusPayload
    | SnapshotPayload
    | ObjectPayload
    | ChildrenPayload
    | SearchPayload
    | SchemaPayload
    | ChangesPayload
    | ResourcePayload,
    Field(discriminator="kind"),
]


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    ok: bool
    live_version: str | None = None
    session_id: str | None = Field(default=None, min_length=1)
    bridge_revision: int | None = Field(default=None, ge=0)
    captured_at: datetime | None = None
    cache_age_seconds: float | None = Field(default=None, ge=0)
    completeness: Literal["complete", "partial", "unavailable"] | None = None
    result: QueryPayload | None = None
    error: QueryError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "QueryResponse":
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful responses require result and forbid error")
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError("error responses require error and forbid result")
        if not self.ok and self.completeness != "unavailable":
            raise ValueError("error responses require unavailable completeness")
        if self.ok and self.result is not None and isinstance(self.result, QueryMetadata):
            metadata_fields = (
                "live_version",
                "session_id",
                "bridge_revision",
                "captured_at",
                "cache_age_seconds",
                "completeness",
            )
            for field_name in metadata_fields:
                if getattr(self, field_name) != getattr(self.result, field_name):
                    raise ValueError(f"response {field_name} must match result metadata")
        return self
