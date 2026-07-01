"""Machine-oriented JSON CLI for Ableton inspection."""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

from ableton_ctrl.contracts import ErrorCode, JsonValue, QueryError, QueryResponse

CLI_USAGE_RECOVERY = {"action": "call_with_one_json_argument"}
INVALID_JSON_RECOVERY = {"action": "pass_valid_json_object"}
VALIDATION_RECOVERY = {"action": "fix_action_fields"}


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


def run(argv: Sequence[str]) -> int:
    raw, error = _parse_json_argument(argv)
    if error is not None:
        _print_response(error)
        return 2
    assert raw is not None
    response = _error_response(
        ErrorCode.VALIDATION_FAILED,
        "CLI action validation is not initialized.",
        VALIDATION_RECOVERY,
    )
    _print_response(response)
    return 2


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    main()
