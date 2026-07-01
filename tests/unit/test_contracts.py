from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from ableton_ctrl.contracts import (
    ErrorCode,
    MemberOutcome,
    ObjectObservation,
    QueryError,
    QueryRequest,
    QueryResponse,
    SnapshotPayload,
    UpdateBatch,
)

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)


def test_update_batch_rejects_non_v1_protocol() -> None:
    with pytest.raises(ValidationError):
        UpdateBatch(
            protocol_version=2,
            session_id="s1",
            live_version="12.4.2",
            captured_at=NOW,
            observations=[],
            removed_source_ids=[],
        )


def test_observation_rejects_callable_values() -> None:
    with pytest.raises(ValidationError):
        ObjectObservation(
            source_id="song",
            type="Song",
            path="Live Set",
            properties={"bad": lambda: None},
            relationships={},
            outcomes=[],
            captured_at=NOW,
        )


def test_observation_rejects_nested_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        ObjectObservation(
            source_id="song",
            type="Song",
            path="Live Set",
            properties={"nested": [1.0, {"bad": float("inf")}]},
            relationships={},
            outcomes=[],
            captured_at=NOW,
        )


def test_member_outcome_requires_reason() -> None:
    with pytest.raises(ValidationError):
        MemberOutcome(member="clip", status="read_failed", reason="")


def test_query_request_rejects_non_v1_protocol() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(QueryRequest).validate_python({"protocol_version": 2, "type": "status"})


def test_query_payload_requires_global_metadata() -> None:
    with pytest.raises(ValidationError):
        SnapshotPayload(root={})


def test_query_response_requires_exactly_one_result_or_error() -> None:
    metadata = {
        "live_version": "12.4.2",
        "session_id": "s1",
        "bridge_revision": 1,
        "captured_at": NOW,
        "cache_age_seconds": 0.1,
        "completeness": "complete",
    }
    result = SnapshotPayload(root={}, **metadata)

    response = QueryResponse(ok=True, result=result, **metadata)
    assert response.result == result
    with pytest.raises(ValidationError):
        QueryResponse(protocol_version=2, ok=True, result=result, **metadata)
    with pytest.raises(ValidationError):
        QueryResponse(ok=True, result=result, **(metadata | {"bridge_revision": 2}))
    with pytest.raises(ValidationError):
        QueryResponse(ok=True)
    with pytest.raises(ValidationError):
        QueryResponse(ok=False, result=result)


def test_error_query_response_has_explicit_unavailable_metadata() -> None:
    response = QueryResponse(
        ok=False,
        completeness="unavailable",
        error=QueryError(code=ErrorCode.LIVE_OFFLINE, message="Live is offline"),
    )

    assert response.model_dump()["live_version"] is None
    assert response.model_dump()["session_id"] is None
    assert response.model_dump()["bridge_revision"] is None
    assert response.model_dump()["captured_at"] is None
    assert response.model_dump()["cache_age_seconds"] is None
    assert response.model_dump()["completeness"] == "unavailable"


def test_query_response_accepts_cli_validation_error_codes() -> None:
    for code in (
        ErrorCode.INVALID_INVOCATION,
        ErrorCode.INVALID_JSON,
        ErrorCode.UNKNOWN_ACTION,
        ErrorCode.VALIDATION_FAILED,
    ):
        response = QueryResponse(
            ok=False,
            completeness="unavailable",
            error=QueryError(
                code=code,
                message="CLI rejected the request.",
                recovery={"action": "fix_cli_invocation"},
            ),
        )
        assert response.model_dump(mode="json", exclude_none=True)["error"]["code"] == code
