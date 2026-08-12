from __future__ import annotations

import pytest

from retain_memory.store import Store
from retain_memory.web import build_category_tree, create_app


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "memory.db")


@pytest.fixture
def client(store):
    app = create_app(store)
    app.config.update(TESTING=True)
    return app.test_client()


def test_category_tree_includes_virtual_parents():
    tree = build_category_tree(["work::retain::release", "personal"])

    assert [node["label"] for node in tree] == ["personal", "work"]
    assert tree[1]["exists"] is False
    assert tree[1]["children"][0]["name"] == "work::retain"
    assert tree[1]["children"][0]["children"][0]["exists"] is True


def test_web_creates_and_renders_nested_category(client, store):
    response = client.post("/categories", data={"name": "work::retain"})

    assert response.status_code == 302
    page = client.get("/?category=work::retain")
    assert page.status_code == 200
    assert b"work" in page.data
    assert b"retain" in page.data
    assert [category.name for category in store.list_categories()] == ["work::retain"]


def test_web_edits_and_moves_memory(client, store):
    store.create_category("inbox")
    store.create_category("archive")
    memory = store.add_memory("inbox", "Draft", 2)

    response = client.post(
        f"/memories/{memory.id}/edit",
        data={"content": "Final", "category": "archive", "priority": "5"},
    )

    assert response.status_code == 302
    updated = store.get_memory(memory.id)
    assert (updated.content, updated.category, updated.priority) == ("Final", "archive", 5)


def test_web_renames_category_branch(client, store):
    store.create_category("work")
    store.create_category("work::retain")

    response = client.post("/categories/work/edit", data={"name": "projects"})

    assert response.status_code == 302
    assert [category.name for category in store.list_categories()] == [
        "projects",
        "projects::retain",
    ]


def test_web_updates_settings(client, store):
    response = client.post(
        "/settings",
        data={
            "default_priority": "5",
            "web_host": "0.0.0.0",
            "web_port": "8080",
            "max_memories_per_category": "25",
            "max_words_per_memory": "75",
        },
    )

    assert response.status_code == 302
    assert store.get_settings().to_dict() == {
        "default_priority": 5,
        "web_host": "0.0.0.0",
        "web_port": 8080,
        "max_memories_per_category": 25,
        "max_words_per_memory": 75,
    }


def test_web_returns_validation_error(client):
    response = client.post("/categories", data={"name": "broken:"})

    assert response.status_code == 400
    assert b"non-empty segments" in response.data
