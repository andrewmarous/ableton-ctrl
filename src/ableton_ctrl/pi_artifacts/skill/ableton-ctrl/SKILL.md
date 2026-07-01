---
name: ableton-ctrl
description: Use ableton_ctrl to inspect Ableton Live Sets through the local read-only ableton-ctrl CLI/Pi bridge. Load this skill when users ask about Live Set structure, tracks, devices, clips, relationships, schemas, changes, or Ableton inspection.
---

# Ableton Ctrl

Use the `ableton_ctrl` tool for Ableton Live inspection tasks. It is read-only: do not use it, or any surrounding workflow, to mutate Live, change parameters, create/delete objects, start transport, write files into the Set, or perform control actions.

The tool accepts flat structured fields and returns the JSON result from the local `ableton-ctrl` CLI. Recovery guidance is included in structured errors; follow the `error.recovery` object before retrying.

## Actions

### `snapshot`

Get a Live Set snapshot.

Required fields:
- `action: "snapshot"`

Optional fields:
- `depth` integer, default 1, range 0-8.
- `page_size` integer, default 20, range 1-200.

Use `snapshot` first when you need the current `session_id`, root object, root revision, available relationships, or initial object IDs.

### `object`

Fetch one object by stable object ID.

Required fields:
- `action: "object"`
- `object_id` string from a snapshot, children page, search result, or previous object result.

### `children`

Page through a relationship from an object.

Required fields:
- `action: "children"`
- `object_id` string.
- `relationship` string exactly as reported by snapshot/object/schema output.
- `revision` integer from the parent object or snapshot.

Optional fields:
- `offset` integer, default 0.
- `limit` integer, default 20, range 1-200.
- `start_index` and `page_size` may be used as pagination aliases.

Although the flat Pi schema accepts larger generic `limit` values for other actions, `children` rejects values above 200.

If output is incomplete or paginated, keep the same `object_id`, `relationship`, and `revision`, then increase `offset`/`start_index` until all pages are read.

### `search`

Find objects by name, type, or path.

Required fields:
- `action: "search"`

Optional fields:
- `name` string.
- `object_type` string.
- `path` string.
- `offset` integer, default 0.
- `limit` integer, default 20, range 1-200.
- `start_index` and `page_size` may be used as pagination aliases.

Although the flat Pi schema accepts larger generic `limit` values for other actions, `search` rejects values above 200.

Use search to locate tracks, devices, clips, scenes, or objects when you do not already have an object ID.

### `schema`

Inspect supported object types, properties, and relationships.

Required fields:
- `action: "schema"`

Optional fields:
- `object_type` string to narrow schema output to one type.

Use schema when you need valid relationship names or supported fields before querying.

### `changes`

Read observed changes since a revision.

Required fields:
- `action: "changes"`

Optional fields:
- `session_id` string, only valid together with `after_revision`.
- `after_revision` integer, only valid together with `session_id`.
- `limit` integer, default 100, range 1-500.

If `session_id` and `after_revision` are omitted, the CLI snapshots the current Set, identifies its Set name, reads the persisted cursor for that Set, and advances that cursor after a successful changes response. Cursor persistence is keyed by Live Set name.

Set-name ambiguity failure: if the current Live Set name cannot be determined, the command fails with recovery guidance such as saving or naming the current Live Set. Do that before relying on persisted cursors.

Use explicit `session_id` and `after_revision` together for revision-pinned workflows where you must not advance the persisted cursor.

### `resource`

Read bundled learning resources.

Required fields:
- `action: "resource"`
- `name` one of `glossary`, `interpretation`, or `limitations`.

Use resources to learn Ableton terminology, interpret inspection output, and understand Live 12.4.2 Intro limitations before answering ambiguous questions.

## Object IDs and revisions

Object IDs come from tool results and are stable only for the observed session/revision context. Do not invent IDs. If a command reports stale state or session changes, take a fresh `snapshot`, discard old IDs/cursors as instructed, and retry with current IDs.

Use revision pinning for paginated reads: keep the same revision while walking children pages so pages describe one coherent observed state.

## Error recovery

All failures are structured. Inspect `ok`, `error.code`, `error.message`, `error.recovery`, and `completeness`.

Common recovery patterns:
- `live_offline`: start Live and the ableton-ctrl bridge/Remote Script.
- `bridge_unavailable`: start or restart `ableton-ctrl-bridge`.
- `stale_state`, `session_changed`, or `stale_cursor`: take a fresh snapshot and retry with current IDs/revisions.
- `partial_result`: paginate, reduce query scope, or wait for discovery to complete.
- `unsupported_property`: call `schema` or use resources to find supported relationships/properties.
- `validation_failed` or `unknown_action`: fix the flat action fields and retry.

Never treat partial or unavailable data as complete. State uncertainty in your answer when `completeness` is not `complete`.

If Pi reports that `ableton_ctrl` output was truncated, avoid asking for the same broad result again. Page through relationships, narrow search filters, reduce snapshot depth/page size, or inspect the saved JSON file path named in the truncation notice.
