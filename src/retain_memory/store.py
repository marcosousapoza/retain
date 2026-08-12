from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ENV_NAME = "MEMORY_FILE"
CATEGORY_DELIMITER = "::"
SCHEMA_VERSION = 4


class RetainError(Exception):
    """Base exception for user-facing errors."""


class NotFoundError(RetainError):
    """Raised when a category or memory does not exist."""


class ConflictError(RetainError):
    """Raised when an operation conflicts with existing data."""


@dataclass(frozen=True)
class Category:
    name: str
    description: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Memory:
    id: str
    category: str
    content: str
    priority: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Settings:
    default_priority: int
    web_host: str
    web_port: int
    max_memories_per_category: int
    max_words_per_memory: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def default_database_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = (
        Path(data_home).expanduser()
        if data_home and data_home.strip()
        else Path.home() / ".local/share"
    )
    return base / "retain/memory.db"


class Store:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        configured_path = str(path) if path is not None else os.environ.get(ENV_NAME)
        if configured_path is None:
            configured_path = str(default_database_path())
        if not configured_path or not configured_path.strip():
            raise RetainError(f"{ENV_NAME} must point to a SQLite database file")

        self.path = Path(configured_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RetainError(
                    f"database schema version {version} is newer than supported version "
                    f"{SCHEMA_VERSION}"
                )
            if version == 0:
                has_tables = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    LIMIT 1
                    """
                ).fetchone()
                if has_tables:
                    raise RetainError("database has tables but no recognized schema version")
                self._create_schema(connection)
                return

            if version == 1:
                connection.executescript(
                    """
                    CREATE TABLE settings (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        default_priority INTEGER NOT NULL
                            CHECK (default_priority BETWEEN 1 AND 5),
                        web_host TEXT NOT NULL CHECK (length(trim(web_host)) > 0),
                        web_port INTEGER NOT NULL CHECK (web_port BETWEEN 1 AND 65535)
                    );
                    INSERT INTO settings (id, default_priority, web_host, web_port)
                    VALUES (1, 3, '127.0.0.1', 5000);
                    PRAGMA user_version = 2;
                    """
                )
                version = 2
            if version == 2:
                connection.executescript(
                    """
                    ALTER TABLE settings ADD COLUMN max_memories_per_category INTEGER
                    NOT NULL DEFAULT 100 CHECK (max_memories_per_category > 0);
                    ALTER TABLE settings ADD COLUMN max_words_per_memory INTEGER
                    NOT NULL DEFAULT 500 CHECK (max_words_per_memory > 0);
                    PRAGMA user_version = 3;
                    """
                )
                version = 3
            if version == 3:
                connection.executescript(
                    """
                    ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT '';
                    PRAGMA user_version = 4;
                    """
                )

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
                CREATE TABLE categories (
                    name TEXT PRIMARY KEY CHECK (length(trim(name)) > 0),
                    description TEXT NOT NULL DEFAULT '',
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

                CREATE INDEX memories_category_order
                ON memories(category, priority DESC, created_at DESC);

                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    default_priority INTEGER NOT NULL CHECK (default_priority BETWEEN 1 AND 5),
                    web_host TEXT NOT NULL CHECK (length(trim(web_host)) > 0),
                    web_port INTEGER NOT NULL CHECK (web_port BETWEEN 1 AND 65535),
                    max_memories_per_category INTEGER NOT NULL DEFAULT 100
                        CHECK (max_memories_per_category > 0),
                    max_words_per_memory INTEGER NOT NULL DEFAULT 500
                        CHECK (max_words_per_memory > 0)
                );

                INSERT INTO settings (
                    id, default_priority, web_host, web_port,
                    max_memories_per_category, max_words_per_memory
                ) VALUES (1, 3, '127.0.0.1', 5000, 100, 500);

                PRAGMA user_version = 4;
                """
        )

    @staticmethod
    def _validate_text(value: str, label: str) -> str:
        value = value.strip()
        if not value:
            raise RetainError(f"{label} cannot be empty")
        return value

    @staticmethod
    def _validate_priority(priority: int) -> int:
        if isinstance(priority, bool) or not 1 <= priority <= 5:
            raise RetainError("priority must be an integer from 1 to 5")
        return priority

    @staticmethod
    def _validate_positive_integer(value: int, label: str) -> int:
        if isinstance(value, bool) or value < 1:
            raise RetainError(f"{label} must be a positive integer")
        return value

    def _validate_memory_content(self, content: str, max_words: int) -> str:
        content = self._validate_text(content, "memory content")
        word_count = len(content.split())
        if word_count > max_words:
            raise RetainError(
                f"memory content contains {word_count} words; the maximum is {max_words}"
            )
        return content

    @classmethod
    def _validate_category_name(cls, name: str) -> str:
        name = cls._validate_text(name, "category name")
        segments = [segment.strip() for segment in name.split(CATEGORY_DELIMITER)]
        if any(not segment or ":" in segment for segment in segments):
            raise RetainError(
                f"category names must contain non-empty segments separated by "
                f"'{CATEGORY_DELIMITER}'"
            )
        return CATEGORY_DELIMITER.join(segments)

    @staticmethod
    def _normalize_description(description: str) -> str:
        return description.strip()

    def create_category(self, name: str, description: str = "") -> Category:
        name = self._validate_category_name(name)
        category = Category(
            name=name,
            description=self._normalize_description(description),
            created_at=_timestamp(),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO categories (name, description, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (category.name, category.description, category.created_at),
                )
        except sqlite3.IntegrityError as error:
            raise ConflictError(f"category already exists: {name}") from error
        return category

    def list_categories(self) -> list[Category]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT name, description, created_at
                FROM categories ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [Category(**dict(row)) for row in rows]

    def get_category(self, name: str) -> Category:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name, description, created_at FROM categories WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"category not found: {name}")
        return Category(**dict(row))

    def list_leaf_categories(self) -> list[Category]:
        categories = self.list_categories()
        names = {category.name for category in categories}
        return [
            category
            for category in categories
            if not any(name.startswith(f"{category.name}{CATEGORY_DELIMITER}") for name in names)
        ]

    def rename_category(self, name: str, new_name: str) -> Category:
        return self.update_category(name, new_name=new_name)

    def update_category(
        self,
        name: str,
        *,
        new_name: str | None = None,
        description: str | None = None,
    ) -> Category:
        if new_name is None and description is None:
            raise RetainError("provide a category name, description, or both")
        existing = self.get_category(name)
        new_name = self._validate_category_name(new_name) if new_name is not None else name
        new_description = (
            self._normalize_description(description)
            if description is not None
            else existing.description
        )
        if new_name == name:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE categories SET description = ? WHERE name = ?",
                    (new_description, name),
                )
            return Category(name, new_description, existing.created_at)

        categories = self.list_categories()
        existing_names = {category.name for category in categories}

        prefix = f"{name}{CATEGORY_DELIMITER}"
        renames = {
            category_name: new_name + category_name[len(name) :]
            for category_name in existing_names
            if category_name == name or category_name.startswith(prefix)
        }
        conflict = next((target for target in renames.values() if target in existing_names), None)
        if conflict is not None:
            raise ConflictError(f"category already exists: {conflict}")

        category_by_name = {category.name: category for category in categories}
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO categories (name, description, created_at)
                VALUES (?, ?, ?)
                """,
                [
                    (
                        new,
                        new_description if old == name else category_by_name[old].description,
                        category_by_name[old].created_at,
                    )
                    for old, new in renames.items()
                ],
            )
            connection.executemany(
                "UPDATE memories SET category = ? WHERE category = ?",
                [(new, old) for old, new in renames.items()],
            )
            connection.executemany(
                "DELETE FROM categories WHERE name = ?", [(old,) for old in renames]
            )

        return Category(new_name, new_description, existing.created_at)

    def delete_category(self, name: str, *, force: bool = False) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.name, COUNT(m.id) AS memory_count
                FROM categories c
                LEFT JOIN memories m ON m.category = c.name
                WHERE c.name = ?
                GROUP BY c.name
                """,
                (name,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"category not found: {name}")
            if row["memory_count"] and not force:
                raise ConflictError(
                    f"category contains {row['memory_count']} memories; use --force to delete it"
                )
            connection.execute("DELETE FROM categories WHERE name = ?", (name,))

    def add_memory(self, category: str, content: str, priority: int = 3) -> Memory:
        settings = self.get_settings()
        content = self._validate_memory_content(content, settings.max_words_per_memory)
        priority = self._validate_priority(priority)
        timestamp = _timestamp()
        memory = Memory(
            id=str(uuid.uuid4()),
            category=category,
            content=content,
            priority=priority,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                category_row = connection.execute(
                    "SELECT 1 FROM categories WHERE name = ?", (category,)
                ).fetchone()
                if category_row is None:
                    raise NotFoundError(f"category not found: {category}")
                memory_count = connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE category = ?", (category,)
                ).fetchone()[0]
                if memory_count >= settings.max_memories_per_category:
                    raise ConflictError(
                        f"category contains the maximum of "
                        f"{settings.max_memories_per_category} memories"
                    )
                connection.execute(
                    """
                    INSERT INTO memories (id, category, content, priority, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory.id,
                        memory.category,
                        memory.content,
                        memory.priority,
                        memory.created_at,
                        memory.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise RetainError(f"could not add memory: {error}") from error
        return memory

    def list_memories(self, category: str, *, leaf_only: bool = False) -> list[Memory]:
        if not self._category_exists(category):
            raise NotFoundError(f"category not found: {category}")
        if leaf_only and not self._category_is_leaf(category):
            raise RetainError(
                f"category has subcategories and cannot be fetched: {category}; "
                "fetch a leaf category instead"
            )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, category, content, priority, created_at, updated_at
                FROM memories
                WHERE category = ?
                ORDER BY priority DESC, created_at DESC
                """,
                (category,),
            ).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def get_memory(self, memory_id: str) -> Memory:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, category, content, priority, created_at, updated_at
                FROM memories WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"memory not found: {memory_id}")
        return Memory(**dict(row))

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        priority: int | None = None,
        category: str | None = None,
    ) -> Memory:
        if content is None and priority is None and category is None:
            raise RetainError("provide content, priority, category, or a combination")
        existing = self.get_memory(memory_id)
        settings = self.get_settings()
        new_content = (
            self._validate_memory_content(content, settings.max_words_per_memory)
            if content is not None
            else existing.content
        )
        new_priority = (
            self._validate_priority(priority) if priority is not None else existing.priority
        )
        new_category = category if category is not None else existing.category
        updated_at = _timestamp()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM categories WHERE name = ?", (new_category,)
                ).fetchone()
                is None
            ):
                raise NotFoundError(f"category not found: {new_category}")
            if new_category != existing.category:
                memory_count = connection.execute(
                    "SELECT COUNT(*) FROM memories WHERE category = ?", (new_category,)
                ).fetchone()[0]
                if memory_count >= settings.max_memories_per_category:
                    raise ConflictError(
                        f"category contains the maximum of "
                        f"{settings.max_memories_per_category} memories"
                    )
            connection.execute(
                """
                UPDATE memories
                SET category = ?, content = ?, priority = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_category, new_content, new_priority, updated_at, memory_id),
            )
        return Memory(
            id=existing.id,
            category=new_category,
            content=new_content,
            priority=new_priority,
            created_at=existing.created_at,
            updated_at=updated_at,
        )

    def delete_memory(self, memory_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            if cursor.rowcount == 0:
                raise NotFoundError(f"memory not found: {memory_id}")

    def get_settings(self) -> Settings:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT default_priority, web_host, web_port,
                       max_memories_per_category, max_words_per_memory
                FROM settings WHERE id = 1
                """
            ).fetchone()
        return Settings(**dict(row))

    def update_settings(
        self,
        *,
        default_priority: int,
        web_host: str,
        web_port: int,
        max_memories_per_category: int,
        max_words_per_memory: int,
    ) -> Settings:
        default_priority = self._validate_priority(default_priority)
        web_host = self._validate_text(web_host, "web host")
        if isinstance(web_port, bool) or not 1 <= web_port <= 65535:
            raise RetainError("web port must be an integer from 1 to 65535")
        max_memories_per_category = self._validate_positive_integer(
            max_memories_per_category, "maximum memories per category"
        )
        max_words_per_memory = self._validate_positive_integer(
            max_words_per_memory, "maximum words per memory"
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE settings
                SET default_priority = ?, web_host = ?, web_port = ?,
                    max_memories_per_category = ?, max_words_per_memory = ?
                WHERE id = 1
                """,
                (
                    default_priority,
                    web_host,
                    web_port,
                    max_memories_per_category,
                    max_words_per_memory,
                ),
            )
        return Settings(
            default_priority,
            web_host,
            web_port,
            max_memories_per_category,
            max_words_per_memory,
        )

    def _category_is_leaf(self, name: str) -> bool:
        prefix = f"{name}{CATEGORY_DELIMITER}"
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM categories WHERE substr(name, 1, length(?)) = ? LIMIT 1",
                    (prefix, prefix),
                ).fetchone()
                is None
            )

    def _category_exists(self, name: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone()
                is not None
            )
