#!/usr/bin/env python3
"""Validate a Live 12.4.2 Intro coverage recording and write release artifacts."""

from __future__ import annotations

import argparse
import json
import math
import numbers
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

from ableton_ctrl.adapter.manifest import LIVE_12_4_2_INTRO_MANIFEST

STATUSES = ("supported", "unavailable", "read_failed", "excluded")
TARGET_VERSION = "12.4.2"
TARGET_EDITION = "Intro"
MAX_TICK_MS = 4.0


class CoverageValidationError(ValueError):
    """Coverage input does not satisfy the release gate."""


def _valid_timing(value: object) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(
                line,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"nonstandard number {token}")
                ),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise CoverageValidationError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise CoverageValidationError(f"line {line_number}: record must be an object")
        records.append(value)
    return records


def _manifest_members() -> set[tuple[str, str]]:
    members: set[tuple[str, str]] = set()
    for type_name, spec in LIVE_12_4_2_INTRO_MANIFEST.items():
        members.update((type_name, member.name) for member in spec.properties)
        members.update((type_name, member.name) for member in spec.relationships)
    return members


def validate(records: list[dict[str, Any]]) -> dict[str, Any]:
    run_records = [record for record in records if record.get("kind") == "run"]
    if len(run_records) != 1:
        raise CoverageValidationError("coverage requires exactly one run record")
    run = run_records[0]
    if run.get("live_version") != TARGET_VERSION or run.get("edition") != TARGET_EDITION:
        raise CoverageValidationError("coverage requires Live 12.4.2 Intro")
    if run.get("discovery_complete") is not True:
        raise CoverageValidationError("discovery did not complete")
    maximum = run.get("max_tick_duration_ms")
    if not _valid_timing(maximum):
        raise CoverageValidationError(
            "run record max_tick_duration_ms must be a finite nonnegative real"
        )
    maximum_ms = float(cast(numbers.Real, maximum))
    if maximum_ms > MAX_TICK_MS:
        raise CoverageValidationError(f"maximum tick duration {maximum_ms} ms exceeds 4 ms")
    p95 = run.get("p95_tick_duration_ms")
    if p95 is not None and not _valid_timing(p95):
        raise CoverageValidationError(
            "run record p95_tick_duration_ms must be a finite nonnegative real"
        )

    member_records = [record for record in records if record.get("kind") == "member"]
    expected = _manifest_members()
    keys = [(record.get("object_type"), record.get("member")) for record in member_records]
    counts = Counter(keys)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        raise CoverageValidationError(f"duplicate manifest member: {duplicates[0]}")
    actual = set(keys)
    missing = sorted(expected - actual)
    if missing:
        raise CoverageValidationError(f"missing manifest member: {missing[0]}")
    unexpected = sorted(actual - expected)
    if unexpected:
        raise CoverageValidationError(f"unexpected manifest member: {unexpected[0]}")

    normalized: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for record in member_records:
        status = record.get("status")
        if status not in STATUSES:
            raise CoverageValidationError(
                f"invalid status for {record.get('object_type')}.{record.get('member')}"
            )
        reason = record.get("reason")
        if status in {"read_failed", "excluded"} and (
            not isinstance(reason, str) or not reason.strip()
        ):
            raise CoverageValidationError(f"{status} requires a reason")
        entry = {
            "object_type": record["object_type"],
            "member": record["member"],
            "status": status,
        }
        if isinstance(reason, str) and reason:
            entry["reason"] = reason
        normalized.append(entry)
        status_counts[status] += 1

    normalized.sort(key=lambda item: (item["object_type"], item["status"], item["member"]))
    return {
        "target": {"edition": TARGET_EDITION, "live_version": TARGET_VERSION},
        "run": {
            "discovery_complete": True,
            "max_tick_duration_ms": maximum_ms,
            "p95_tick_duration_ms": p95,
        },
        "summary": {
            "total": len(normalized),
            **{status: status_counts[status] for status in STATUSES},
        },
        "members": normalized,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Live 12.4.2 Intro coverage",
        "",
        f"- Discovery complete: {str(report['run']['discovery_complete']).lower()}",
        f"- Maximum tick duration: {report['run']['max_tick_duration_ms']} ms",
        f"- 95th-percentile tick duration: {report['run']['p95_tick_duration_ms']} ms",
        "",
    ]
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for member in report["members"]:
        grouped[member["object_type"]][member["status"]].append(member)
    for type_name in sorted(grouped):
        lines.extend((f"## {type_name}", ""))
        for status in STATUSES:
            entries = grouped[type_name].get(status, [])
            if not entries:
                continue
            lines.extend((f"### {status}", ""))
            for entry in entries:
                suffix = f" — {entry['reason']}" if "reason" in entry else ""
                lines.append(f"- `{entry['member']}`{suffix}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_and_write(input_path: Path, output: Path) -> dict[str, Any]:
    report = validate(_read_records(input_path))
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (output / "coverage.md").write_text(_markdown(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, metavar="INPUT.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        validate_and_write(arguments.input, arguments.output)
    except (OSError, CoverageValidationError) as exc:
        parser.exit(1, f"coverage validation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
