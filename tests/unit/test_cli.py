from ableton_ctrl.cli import (
    ChangesCommand,
    ChildrenCommand,
    ObjectCommand,
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
        ChildrenCommand(
            action="children",
            object_id="obj-1",
            relationship="tracks",
            revision=3,
            offset=10,
            limit=25,
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
    query = build_query(SearchCommand(action="search", name="kick", object_type="Track", path=None))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "search",
        "name": "kick",
        "object_type": "Track",
        "path": None,
        "offset": 0,
        "limit": 20,
    }


def test_builds_schema_query_from_short_action() -> None:
    query = build_query(SchemaCommand(action="schema", object_type="Track"))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "schema",
        "object_type": "Track",
    }


def test_builds_explicit_changes_query_from_short_action() -> None:
    query = build_query(ChangesCommand(action="changes", session_id="s1", after_revision=2, limit=10))
    assert query.model_dump(mode="json") == {
        "protocol_version": 1,
        "type": "changes",
        "session_id": "s1",
        "after_revision": 2,
        "limit": 10,
    }
