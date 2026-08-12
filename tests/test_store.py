from __future__ import annotations

import sqlite3

import pytest

from retain_memory.store import (
    CATEGORY_DELIMITER,
    ConflictError,
    NotFoundError,
    RetainError,
    Store,
    default_database_path,
)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "memory.db")


def test_default_database_path_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORY_FILE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    store = Store()

    assert default_database_path() == tmp_path / "data/retain/memory.db"
    assert store.path == default_database_path()
    assert store.path.is_file()


def test_default_database_path_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("retain_memory.store.Path.home", lambda: tmp_path)

    assert default_database_path() == tmp_path / ".local/share/retain/memory.db"


def test_new_database_is_created_at_latest_schema(store):
    with store._connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        settings_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(settings)")
        }
        category_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(categories)")
        }

    assert version == 4
    assert {"max_memories_per_category", "max_words_per_memory"} <= settings_columns
    assert "description" in category_columns


def test_existing_database_gains_limit_settings(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE categories (
                name TEXT PRIMARY KEY CHECK (length(trim(name)) > 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL REFERENCES categories(name) ON DELETE CASCADE,
                content TEXT NOT NULL CHECK (length(trim(content)) > 0),
                priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_priority INTEGER NOT NULL CHECK (default_priority BETWEEN 1 AND 5),
                web_host TEXT NOT NULL CHECK (length(trim(web_host)) > 0),
                web_port INTEGER NOT NULL CHECK (web_port BETWEEN 1 AND 65535)
            );
            INSERT INTO settings VALUES (1, 3, '127.0.0.1', 5000);
            PRAGMA user_version = 2;
            """
        )

    settings = Store(database).get_settings()

    assert settings.max_memories_per_category == 100
    assert settings.max_words_per_memory == 500


def test_existing_categories_gain_empty_descriptions(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE categories (
                name TEXT PRIMARY KEY CHECK (length(trim(name)) > 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL REFERENCES categories(name) ON DELETE CASCADE,
                content TEXT NOT NULL CHECK (length(trim(content)) > 0),
                priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_priority INTEGER NOT NULL CHECK (default_priority BETWEEN 1 AND 5),
                web_host TEXT NOT NULL CHECK (length(trim(web_host)) > 0),
                web_port INTEGER NOT NULL CHECK (web_port BETWEEN 1 AND 65535),
                max_memories_per_category INTEGER NOT NULL DEFAULT 100,
                max_words_per_memory INTEGER NOT NULL DEFAULT 500
            );
            INSERT INTO categories VALUES ('notes', 'now');
            INSERT INTO settings VALUES (1, 3, '127.0.0.1', 5000, 100, 500);
            PRAGMA user_version = 3;
            """
        )

    category = Store(database).get_category("notes")

    assert category.description == ""


def test_category_lifecycle(store):
    created = store.create_category("projects")

    assert created.name == "projects"
    assert created.created_at.endswith("Z")
    assert store.list_categories() == [created]

    with pytest.raises(ConflictError, match="already exists"):
        store.create_category("projects")

    store.delete_category("projects")
    assert store.list_categories() == []


def test_nested_category_rename_moves_descendants_and_memories(store):
    store.create_category("projects", "All active projects")
    store.create_category(f"projects{CATEGORY_DELIMITER}retain", "Retain development")
    memory = store.add_memory(f"projects{CATEGORY_DELIMITER}retain", "Ship it")

    renamed = store.rename_category("projects", "work")

    assert renamed.name == "work"
    assert [category.name for category in store.list_categories()] == [
        "work",
        f"work{CATEGORY_DELIMITER}retain",
    ]
    assert store.get_memory(memory.id).category == f"work{CATEGORY_DELIMITER}retain"
    assert store.get_category("work").description == "All active projects"
    assert store.get_category("work::retain").description == "Retain development"


def test_category_description_can_be_created_and_updated(store):
    created = store.create_category("books", "  Books to remember  ")

    updated = store.update_category("books", description="Read and unread books")

    assert created.description == "Books to remember"
    assert updated.description == "Read and unread books"
    assert store.get_category("books") == updated


@pytest.mark.parametrize("name", ["parent:", "parent:::child", "parent::::child"])
def test_category_delimiter_requires_nonempty_segments(store, name):
    with pytest.raises(RetainError, match="non-empty segments"):
        store.create_category(name)


def test_memory_crud_and_persistence(store):
    store.create_category("work")
    memory = store.add_memory("work", "Ship the release", 4)

    assert memory.created_at == memory.updated_at
    assert Store(store.path).get_memory(memory.id) == memory

    updated = store.update_memory(memory.id, content="Ship version 1", priority=5)
    assert updated.content == "Ship version 1"
    assert updated.priority == 5
    assert updated.created_at == memory.created_at
    assert updated.updated_at >= memory.updated_at

    store.delete_memory(memory.id)
    with pytest.raises(NotFoundError, match="memory not found"):
        store.get_memory(memory.id)


def test_memory_can_move_to_another_category(store):
    store.create_category("inbox")
    store.create_category("archive")
    memory = store.add_memory("inbox", "File this")

    updated = store.update_memory(memory.id, category="archive")

    assert updated.category == "archive"
    assert store.list_memories("inbox") == []
    assert store.list_memories("archive") == [updated]


def test_memories_are_ordered_by_priority_then_newest(store, monkeypatch):
    store.create_category("notes")
    timestamps = iter(
        [
            "2026-01-01T00:00:00.000001Z",
            "2026-01-01T00:00:00.000002Z",
            "2026-01-01T00:00:00.000003Z",
        ]
    )
    monkeypatch.setattr("retain_memory.store._timestamp", lambda: next(timestamps))

    low = store.add_memory("notes", "low", 1)
    older_high = store.add_memory("notes", "older high", 5)
    newer_high = store.add_memory("notes", "newer high", 5)

    assert [item.id for item in store.list_memories("notes")] == [
        newer_high.id,
        older_high.id,
        low.id,
    ]


def test_category_delete_requires_force_when_nonempty(store):
    store.create_category("temporary")
    memory = store.add_memory("temporary", "Discard me")

    with pytest.raises(ConflictError, match="--force"):
        store.delete_category("temporary")

    store.delete_category("temporary", force=True)
    with pytest.raises(NotFoundError):
        store.get_memory(memory.id)


@pytest.mark.parametrize("priority", [0, 6])
def test_priority_must_be_between_one_and_five(store, priority):
    store.create_category("notes")

    with pytest.raises(RetainError, match="1 to 5"):
        store.add_memory("notes", "Invalid", priority)


def test_memory_requires_an_existing_category(store):
    with pytest.raises(NotFoundError, match="category not found"):
        store.add_memory("missing", "No category")


def test_database_enforces_priority_constraint(store):
    store.create_category("notes")

    with pytest.raises(sqlite3.IntegrityError), store._connect() as connection:
        connection.execute(
            """
            INSERT INTO memories (id, category, content, priority, created_at, updated_at)
            VALUES ('id', 'notes', 'invalid', 9, 'now', 'now')
            """
        )


def test_settings_are_persisted(store):
    assert store.get_settings().default_priority == 3

    updated = store.update_settings(
        default_priority=4,
        web_host="0.0.0.0",
        web_port=8080,
        max_memories_per_category=25,
        max_words_per_memory=50,
    )

    assert Store(store.path).get_settings() == updated


def test_memory_limits_are_enforced_on_add_edit_and_move(store):
    store.create_category("full")
    store.create_category("other")
    store.update_settings(
        default_priority=3,
        web_host="127.0.0.1",
        web_port=5000,
        max_memories_per_category=1,
        max_words_per_memory=2,
    )
    existing = store.add_memory("full", "two words")
    movable = store.add_memory("other", "move me")

    with pytest.raises(ConflictError, match="maximum of 1"):
        store.add_memory("full", "another one")
    with pytest.raises(RetainError, match="3 words; the maximum is 2"):
        store.update_memory(existing.id, content="one two three")
    with pytest.raises(ConflictError, match="maximum of 1"):
        store.update_memory(movable.id, category="full")


def test_leaf_category_listing_and_reads(store):
    store.create_category("work")
    store.create_category("work::retain")
    store.create_category("personal")

    assert [category.name for category in store.list_leaf_categories()] == [
        "personal",
        "work::retain",
    ]
    with pytest.raises(RetainError, match="fetch a leaf category"):
        store.list_memories("work", leaf_only=True)
    assert store.list_memories("work") == []
