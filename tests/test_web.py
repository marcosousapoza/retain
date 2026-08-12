from __future__ import annotations

import pytest

from retain_memory.category_navigation import build_category_tree
from retain_memory.store import Store
from retain_memory.web import create_app


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "memory.db")


@pytest.fixture
def client(store):
    app = create_app(store)
    app.config.update(TESTING=True)
    return app.test_client()


def test_category_tree_includes_virtual_parents(store):
    store.create_category("work::retain::release")
    store.create_category("personal")

    tree = build_category_tree(store.list_categories())

    assert [node.label for node in tree] == ["personal", "work"]
    assert tree[1].exists is False
    assert tree[1].children[0].name == "work::retain"
    assert tree[1].children[0].children[0].exists is True


def test_category_page_renders_hierarchy(client, store):
    store.create_category("work::retain", "Development context")

    page = client.get("/categories")

    assert page.status_code == 200
    assert b'class="management-tree"' in page.data
    assert page.data.index(b">work</span>") < page.data.index(b">retain</a>")
    assert b"Development context" in page.data


def test_selected_category_renders_breadcrumbs_and_active_tree(client, store):
    store.create_category("work")
    store.create_category("work::retain")

    page = client.get("/?category=work::retain")

    assert b'aria-label="Category path"' in page.data
    assert b'href="/?category=work">work</a>' in page.data
    assert b"<h1>retain</h1>" in page.data
    assert b'aria-current="page"' in page.data


def test_web_creates_and_renders_nested_category(client, store):
    response = client.post(
        "/categories",
        data={"name": "work::retain", "description": "Retain development context"},
    )

    assert response.status_code == 302
    page = client.get("/?category=work::retain")
    assert page.status_code == 200
    assert b"work" in page.data
    assert b"retain" in page.data
    assert [category.name for category in store.list_categories()] == ["work::retain"]
    assert store.get_category("work::retain").description == "Retain development context"


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


def test_web_edits_category_description(client, store):
    store.create_category("work", "Old description")

    response = client.post(
        "/categories/work/edit",
        data={"name": "work", "description": "What belongs at work"},
    )

    assert response.status_code == 302
    assert store.get_category("work").description == "What belongs at work"


def test_web_archives_restores_and_permanently_deletes(client, store):
    store.create_category("work")
    store.add_memory("work", "Remember this")

    response = client.post("/categories/work/delete")
    archive = store.list_archives()[0]

    assert response.status_code == 302
    page = client.get("/archive")
    assert b"work" in page.data
    assert b"1 memories" in page.data

    response = client.post(f"/archive/{archive.id}/restore")
    assert response.status_code == 302
    assert store.get_category("work").name == "work"

    archived_again = store.archive_category("work")
    response = client.post(f"/archive/{archived_again.id}/delete")
    assert response.status_code == 302
    assert store.list_archives() == []


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
