from __future__ import annotations

import os
from functools import cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from .store import ENV_NAME, Store, default_database_path

mcp = FastMCP("retain")


@cache
def _store_for_path(path: str) -> Store:
    return Store(path)


def _get_store() -> Store:
    path = os.environ.get(ENV_NAME, str(default_database_path()))
    return _store_for_path(path)


@mcp.tool()
def list_categories() -> list[dict[str, Any]]:
    """List leaf categories whose memories can be fetched. Manage categories in the web UI."""
    return [category.to_dict() for category in _get_store().list_leaf_categories()]


@mcp.tool()
def create_category(name: str, description: str = "") -> dict[str, Any]:
    """Create a category, optionally with a description of what belongs in it."""
    return _get_store().create_category(name, description).to_dict()


@mcp.tool()
def update_category(
    name: str, new_name: str | None = None, description: str | None = None
) -> dict[str, Any]:
    """Update a category's name, description, or both. Renaming also renames descendants."""
    return _get_store().update_category(name, new_name=new_name, description=description).to_dict()


@mcp.tool()
def delete_category(name: str) -> dict[str, Any]:
    """Archive a category branch and its memories so the user can restore or purge it."""
    return _get_store().archive_category(name).to_dict()


@mcp.tool()
def get_memories(category: str) -> list[dict[str, Any]]:
    """Get a leaf category's memories. Categories with subcategories cannot be fetched."""
    return [memory.to_dict() for memory in _get_store().list_memories(category, leaf_only=True)]


@mcp.tool()
def add_memory(category: str, content: str, priority: int = 3) -> dict[str, Any]:
    """Add a memory to an existing category. Priority must be between 1 and 5."""
    return _get_store().add_memory(category, content, priority).to_dict()


@mcp.tool()
def update_memory(
    memory_id: str, content: str | None = None, priority: int | None = None
) -> dict[str, Any]:
    """Update the content, priority, or both for an existing memory."""
    return _get_store().update_memory(memory_id, content=content, priority=priority).to_dict()


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    """Delete a memory by ID."""
    _get_store().delete_memory(memory_id)
    return f"deleted memory: {memory_id}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
