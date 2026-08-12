from __future__ import annotations

from contextlib import suppress
from typing import Any

from flask import Flask, abort, redirect, render_template, request, url_for

from .store import CATEGORY_DELIMITER, NotFoundError, RetainError, Store


def build_category_tree(
    names: list[str], descriptions: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    children: dict[tuple[str, ...], list[dict[str, Any]]] = {(): roots}
    real_names = set(names)
    paths = {
        tuple(name.split(CATEGORY_DELIMITER)[:depth])
        for name in names
        for depth in range(1, len(name.split(CATEGORY_DELIMITER)) + 1)
    }
    for path in sorted(paths, key=lambda item: tuple(part.casefold() for part in item)):
        full_name = CATEGORY_DELIMITER.join(path)
        node = {
            "label": path[-1],
            "name": full_name,
            "exists": full_name in real_names,
            "description": (descriptions or {}).get(full_name, ""),
            "children": [],
        }
        children.setdefault(path[:-1], roots).append(node)
        children[path] = node["children"]
    return roots


def create_app(store: Store | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store or Store()

    def get_store() -> Store:
        return app.config["STORE"]

    def page_context(**values: Any) -> dict[str, Any]:
        categories = get_store().list_categories()
        selected = values.get("selected")
        return {
            "categories": categories,
            "category_tree": build_category_tree(
                [category.name for category in categories],
                {category.name: category.description for category in categories},
            ),
            "delimiter": CATEGORY_DELIMITER,
            "selected_description": next(
                (category.description for category in categories if category.name == selected),
                "",
            ),
            **values,
        }

    @app.get("/")
    def index():
        categories = get_store().list_categories()
        selected = request.args.get("category")
        if selected is None and categories:
            selected = categories[0].name
        memories = []
        if selected is not None:
            try:
                memories = get_store().list_memories(selected)
            except NotFoundError:
                abort(404)
        return render_template("index.html", **page_context(selected=selected, memories=memories))

    @app.post("/memories")
    def create_memory():
        category = request.form.get("category", "")
        try:
            get_store().add_memory(
                category,
                request.form.get("content", ""),
                int(request.form.get("priority", "")),
            )
        except (RetainError, ValueError) as error:
            memories = []
            with suppress(RetainError):
                memories = get_store().list_memories(category)
            return (
                render_template(
                    "index.html",
                    **page_context(selected=category, memories=memories, error=str(error)),
                ),
                400,
            )
        return redirect(url_for("index", category=category))

    @app.route("/memories/<memory_id>/edit", methods=["GET", "POST"])
    def edit_memory(memory_id: str):
        try:
            memory = get_store().get_memory(memory_id)
            if request.method == "POST":
                memory = get_store().update_memory(
                    memory_id,
                    category=request.form.get("category", ""),
                    content=request.form.get("content", ""),
                    priority=int(request.form.get("priority", "")),
                )
                return redirect(url_for("index", category=memory.category))
        except NotFoundError:
            abort(404)
        except (RetainError, ValueError) as error:
            return (
                render_template(
                    "memory_edit.html", **page_context(memory=memory, error=str(error))
                ),
                400,
            )
        return render_template("memory_edit.html", **page_context(memory=memory))

    @app.post("/memories/<memory_id>/delete")
    def delete_memory(memory_id: str):
        try:
            category = get_store().get_memory(memory_id).category
            get_store().delete_memory(memory_id)
        except NotFoundError:
            abort(404)
        return redirect(url_for("index", category=category))

    @app.post("/categories")
    def create_category():
        try:
            category = get_store().create_category(
                request.form.get("name", ""), request.form.get("description", "")
            )
        except RetainError as error:
            return render_template("categories.html", **page_context(error=str(error))), 400
        return redirect(url_for("index", category=category.name))

    @app.get("/categories")
    def categories():
        return render_template("categories.html", **page_context())

    @app.route("/categories/<path:name>/edit", methods=["GET", "POST"])
    def edit_category(name: str):
        try:
            category = get_store().get_category(name)
        except NotFoundError:
            abort(404)
        if request.method == "POST":
            try:
                category = get_store().update_category(
                    name,
                    new_name=request.form.get("name", ""),
                    description=request.form.get("description", ""),
                )
            except RetainError as error:
                return (
                    render_template(
                        "category_edit.html",
                        **page_context(category=category, error=str(error)),
                    ),
                    400,
                )
            return redirect(url_for("index", category=category.name))
        return render_template("category_edit.html", **page_context(category=category))

    @app.post("/categories/<path:name>/delete")
    def delete_category(name: str):
        try:
            get_store().delete_category(name, force=request.form.get("force") == "yes")
        except NotFoundError:
            abort(404)
        except RetainError as error:
            return render_template("categories.html", **page_context(error=str(error))), 409
        return redirect(url_for("categories"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        current = get_store().get_settings()
        if request.method == "POST":
            try:
                current = get_store().update_settings(
                    default_priority=int(request.form.get("default_priority", "")),
                    web_host=request.form.get("web_host", ""),
                    web_port=int(request.form.get("web_port", "")),
                    max_memories_per_category=int(
                        request.form.get("max_memories_per_category", "")
                    ),
                    max_words_per_memory=int(request.form.get("max_words_per_memory", "")),
                )
            except (RetainError, ValueError) as error:
                return (
                    render_template(
                        "settings.html", **page_context(settings=current, error=str(error))
                    ),
                    400,
                )
            return redirect(url_for("settings", saved="yes"))
        return render_template(
            "settings.html",
            **page_context(settings=current, saved=request.args.get("saved") == "yes"),
        )

    @app.context_processor
    def template_helpers():
        return {"default_priority": get_store().get_settings().default_priority}

    return app
