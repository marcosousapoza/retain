from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ENV_NAME = "MEMORY_FILE"


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

                PRAGMA user_version = 1;
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

    def create_category(self, name: str) -> Category:
        name = self._validate_text(name, "category name")
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
    ) -> Memory:
        if content is None and priority is None:
            raise RetainError("provide content, priority, or both")
        existing = self.get_memory(memory_id)
        new_content = (
            self._validate_text(content, "memory content")
            if content is not None
            else existing.content
        )
        new_priority = (
            self._validate_priority(priority) if priority is not None else existing.priority
        )
        updated_at = _timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE memories SET content = ?, priority = ?, updated_at = ? WHERE id = ?
                """,
                (new_content, new_priority, updated_at, memory_id),
            )
        return Memory(
            id=existing.id,
            category=existing.category,
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

    def _category_exists(self, name: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone()
                is not None
            )
