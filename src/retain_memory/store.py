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


class RetainError(Exception):
    """Base exception for user-facing errors."""


class NotFoundError(RetainError):
    """Raised when a category or memory does not exist."""


class ConflictError(RetainError):
    """Raised when an operation conflicts with existing data."""


@dataclass(frozen=True)
class Category:
    name: str
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        configured_path = str(path) if path is not None else os.environ.get(ENV_NAME)
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    name TEXT PRIMARY KEY CHECK (length(trim(name)) > 0),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL REFERENCES categories(name) ON DELETE CASCADE,
                    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
                    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS memories_category_order
                ON memories(category, priority DESC, created_at DESC);

                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    default_priority INTEGER NOT NULL CHECK (default_priority BETWEEN 1 AND 5),
                    web_host TEXT NOT NULL CHECK (length(trim(web_host)) > 0),
                    web_port INTEGER NOT NULL CHECK (web_port BETWEEN 1 AND 65535)
                );

                INSERT OR IGNORE INTO settings (id, default_priority, web_host, web_port)
                VALUES (1, 3, '127.0.0.1', 5000);

                PRAGMA user_version = 2;
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

    def create_category(self, name: str) -> Category:
        name = self._validate_category_name(name)
        category = Category(name=name, created_at=_timestamp())
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO categories (name, created_at) VALUES (?, ?)",
                    (category.name, category.created_at),
                )
        except sqlite3.IntegrityError as error:
            raise ConflictError(f"category already exists: {name}") from error
        return category

    def list_categories(self) -> list[Category]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, created_at FROM categories ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [Category(**dict(row)) for row in rows]

    def rename_category(self, name: str, new_name: str) -> Category:
        new_name = self._validate_category_name(new_name)
        categories = self.list_categories()
        existing_names = {category.name for category in categories}
        if name not in existing_names:
            raise NotFoundError(f"category not found: {name}")
        created_at = next(category.created_at for category in categories if category.name == name)
        if name == new_name:
            return Category(name=name, created_at=created_at)

        prefix = f"{name}{CATEGORY_DELIMITER}"
        renames = {
            category_name: new_name + category_name[len(name) :]
            for category_name in existing_names
            if category_name == name or category_name.startswith(prefix)
        }
        conflict = next((target for target in renames.values() if target in existing_names), None)
        if conflict is not None:
            raise ConflictError(f"category already exists: {conflict}")

        created_at_by_name = {category.name: category.created_at for category in categories}
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO categories (name, created_at) VALUES (?, ?)",
                [(new, created_at_by_name[old]) for old, new in renames.items()],
            )
            connection.executemany(
                "UPDATE memories SET category = ? WHERE category = ?",
                [(new, old) for old, new in renames.items()],
            )
            connection.executemany(
                "DELETE FROM categories WHERE name = ?", [(old,) for old in renames]
            )

        return Category(name=new_name, created_at=created_at)

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
        content = self._validate_text(content, "memory content")
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
            if not self._category_exists(category):
                raise NotFoundError(f"category not found: {category}") from error
            raise RetainError(f"could not add memory: {error}") from error
        return memory

    def list_memories(self, category: str) -> list[Memory]:
        if not self._category_exists(category):
            raise NotFoundError(f"category not found: {category}")
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
        new_content = (
            self._validate_text(content, "memory content")
            if content is not None
            else existing.content
        )
        new_priority = (
            self._validate_priority(priority) if priority is not None else existing.priority
        )
        new_category = category if category is not None else existing.category
        if not self._category_exists(new_category):
            raise NotFoundError(f"category not found: {new_category}")
        updated_at = _timestamp()
        with self._connect() as connection:
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
                "SELECT default_priority, web_host, web_port FROM settings WHERE id = 1"
            ).fetchone()
        return Settings(**dict(row))

    def update_settings(self, *, default_priority: int, web_host: str, web_port: int) -> Settings:
        default_priority = self._validate_priority(default_priority)
        web_host = self._validate_text(web_host, "web host")
        if isinstance(web_port, bool) or not 1 <= web_port <= 65535:
            raise RetainError("web port must be an integer from 1 to 65535")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE settings
                SET default_priority = ?, web_host = ?, web_port = ?
                WHERE id = 1
                """,
                (default_priority, web_host, web_port),
            )
        return Settings(default_priority, web_host, web_port)

    def _category_exists(self, name: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone()
                is not None
            )
