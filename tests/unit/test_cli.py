from ableton_ctrl.cli import (
    ChangesCommand,
    ChildrenCommand,
    ObjectCommand,
    ResourceCommand,
    SchemaCommand,
    SearchCommand,
    SnapshotCommand,
    build_query,
)


def test_builds_snapshot_query_from_short_action() -> None:
    query = build_query(SnapshotCommand(action="snapshot", depth=2, page_size=50))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "snapshot",
        "depth": 2,
        "page_size": 50,
    }


def test_builds_object_query_from_short_action() -> None:
    query = build_query(ObjectCommand(action="object", object_id="obj-1"))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "get_object",
        "object_id": "obj-1",
    }


def test_builds_children_query_from_short_action() -> None:
    query = build_query(
        ChildrenCommand.model_validate(
            {
                "action": "children",
                "object_id": "obj-1",
                "relationship": "tracks",
                "revision": 3,
                "start_index": 10,
                "page_size": 25,
            }
        )
    )
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "list_children",
        "object_id": "obj-1",
        "relationship": "tracks",
        "offset": 10,
        "limit": 25,
        "revision": 3,
    }


def test_builds_search_query_from_short_action() -> None:
    query = build_query(
        SearchCommand.model_validate(
            {
                "action": "search",
                "name": "kick",
                "object_type": "Track",
                "path": "Live Set",
                "start_index": 5,
                "page_size": 25,
            }
        )
    )
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "search",
        "name": "kick",
        "object_type": "Track",
        "path": "Live Set",
        "offset": 5,
        "limit": 25,
    }


def test_builds_schema_query_from_short_action() -> None:
    query = build_query(SchemaCommand(action="schema", object_type="Track"))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "schema",
        "object_type": "Track",
    }


def test_builds_explicit_changes_query_from_short_action() -> None:
    query = build_query(
        ChangesCommand(action="changes", session_id="s1", after_revision=2, limit=10)
    )
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "changes",
        "session_id": "s1",
        "after_revision": 2,
        "limit": 10,
    }


def test_builds_resource_query_from_short_action() -> None:
    query = build_query(ResourceCommand(action="resource", name="glossary"))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "resource",
        "name": "glossary",
    }
