from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .store import Store

mcp = FastMCP("retain")


@mcp.tool()
def list_categories() -> list[dict[str, Any]]:
    """List all memory categories. Categories can only be created with the CLI."""
    return [category.to_dict() for category in Store().list_categories()]


@mcp.tool()
def get_memories(category: str) -> list[dict[str, Any]]:
    """Get a category's memories, ordered by highest priority and then newest first."""
    return [memory.to_dict() for memory in Store().list_memories(category)]


@mcp.tool()
def add_memory(category: str, content: str, priority: int = 3) -> dict[str, Any]:
    """Add a memory to an existing category. Priority must be between 1 and 5."""
    return Store().add_memory(category, content, priority).to_dict()


@mcp.tool()
def update_memory(
    memory_id: str, content: str | None = None, priority: int | None = None
) -> dict[str, Any]:
    """Update the content, priority, or both for an existing memory."""
    return Store().update_memory(memory_id, content=content, priority=priority).to_dict()


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    """Delete a memory by ID."""
    Store().delete_memory(memory_id)
    return f"deleted memory: {memory_id}"


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
