from __future__ import annotations

import asyncio
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from retain_memory.server import (
    add_memory,
    create_category,
    delete_category,
    delete_memory,
    get_memories,
    list_categories,
    update_category,
    update_memory,
)
from retain_memory.store import RetainError, Store


def test_mcp_functions_manage_memories_but_not_categories(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_FILE", str(tmp_path / "memory.db"))
    Store().create_category("agent")

    assert [item["name"] for item in list_categories()] == ["agent"]
    memory = add_memory("agent", "Remember this", 4)
    assert get_memories("agent") == [memory]

    updated = update_memory(memory["id"], priority=5)
    assert updated["priority"] == 5

    assert delete_memory(memory["id"]) == f"deleted memory: {memory['id']}"
    assert get_memories("agent") == []


def test_stdio_server_exposes_expected_tools(tmp_path):
    database = tmp_path / "mcp.db"
    Store(database).create_category("agent")

    async def inspect_server():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "retain_memory.server"],
            env={**os.environ, "MEMORY_FILE": str(database)},
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "list_categories",
                "create_category",
                "update_category",
                "delete_category",
                "get_memories",
                "add_memory",
                "update_memory",
                "delete_memory",
            }
            result = await session.call_tool(
                "add_memory",
                {"category": "agent", "content": "From MCP", "priority": 5},
            )
            assert not result.isError

    asyncio.run(inspect_server())


def test_mcp_lists_and_fetches_only_leaf_categories(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_FILE", str(tmp_path / "memory.db"))
    store = Store()
    store.create_category("work")
    store.create_category("work::retain", "Knowledge about the Retain project")

    assert [category["name"] for category in list_categories()] == ["work::retain"]
    assert list_categories()[0]["description"] == "Knowledge about the Retain project"
    with pytest.raises(RetainError, match="fetch a leaf category"):
        get_memories("work")


def test_mcp_manages_and_archives_categories(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_FILE", str(tmp_path / "memory.db"))

    created = create_category("agent", "Agent knowledge")
    updated = update_category("agent", description="Curated agent knowledge")
    memory = add_memory("agent", "Remember this")
    archived = delete_category("agent")

    assert created["description"] == "Agent knowledge"
    assert updated["description"] == "Curated agent knowledge"
    assert archived["root_name"] == "agent"
    assert archived["memory_count"] == 1
    with pytest.raises(RetainError, match="category not found"):
        get_memories("agent")
    assert Store().list_archives()[0].id == archived["id"]
    assert memory["id"]
