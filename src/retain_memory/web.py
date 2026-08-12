from __future__ import annotations

from contextlib import suppress

from flask import Flask, abort, redirect, render_template, request, url_for

from .category_navigation import build_category_crumbs, build_category_tree
from .store import CATEGORY_DELIMITER, Category, Memory, NotFoundError, RetainError, Store


def create_app(store: Store | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store or Store()

    def get_store() -> Store:
        return app.config["STORE"]

    def navigation_context(
        categories: list[Category], selected: str | None = None
    ) -> dict[str, object]:
        return {
            "categories": categories,
            "category_tree": build_category_tree(categories, selected),
            "delimiter": CATEGORY_DELIMITER,
            "selected_description": next(
                (category.description for category in categories if category.name == selected),
                "",
            ),
            "category_crumbs": build_category_crumbs(selected, categories) if selected else [],
        }

    def render_index(
        *,
        categories: list[Category],
        selected: str | None,
        memories: list[Memory],
        error: str | None = None,
    ) -> str:
        return render_template(
            "index.html",
            **navigation_context(categories, selected),
            selected=selected,
            memories=memories,
            default_priority=get_store().get_settings().default_priority,
            error=error,
        )

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
        return render_index(categories=categories, selected=selected, memories=memories)

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
            categories = get_store().list_categories()
            return (
                render_index(
                    categories=categories,
                    selected=category,
                    memories=memories,
                    error=str(error),
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
                    "memory_edit.html",
                    memory=memory,
                    categories=get_store().list_categories(),
                    delimiter=CATEGORY_DELIMITER,
                    error=str(error),
                ),
                400,
            )
        return render_template(
            "memory_edit.html",
            memory=memory,
            categories=get_store().list_categories(),
            delimiter=CATEGORY_DELIMITER,
        )

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
            categories = get_store().list_categories()
            return (
                render_template(
                    "categories.html",
                    **navigation_context(categories),
                    error=str(error),
                ),
                400,
            )
        return redirect(url_for("index", category=category.name))

    @app.get("/categories")
    def categories():
        all_categories = get_store().list_categories()
        return render_template("categories.html", **navigation_context(all_categories))

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
                        category=category,
                        error=str(error),
                    ),
                    400,
                )
            return redirect(url_for("index", category=category.name))
        return render_template("category_edit.html", category=category)

    @app.post("/categories/<path:name>/delete")
    def delete_category(name: str):
        try:
            get_store().archive_category(name)
        except NotFoundError:
            abort(404)
        except RetainError as error:
            all_categories = get_store().list_categories()
            return (
                render_template(
                    "categories.html",
                    **navigation_context(all_categories),
                    error=str(error),
                ),
                409,
            )
        return redirect(url_for("categories"))

    @app.get("/archive")
    def archive():
        return render_template(
            "archive.html",
            archives=get_store().list_archives(),
            delimiter=CATEGORY_DELIMITER,
        )

    @app.post("/archive/<archive_id>/restore")
    def restore_archive(archive_id: str):
        try:
            entry = get_store().restore_archive(archive_id)
        except NotFoundError:
            abort(404)
        except RetainError as error:
            return (
                render_template(
                    "archive.html",
                    archives=get_store().list_archives(),
                    delimiter=CATEGORY_DELIMITER,
                    error=str(error),
                ),
                409,
            )
        return redirect(url_for("index", category=entry.root_name))

    @app.post("/archive/<archive_id>/delete")
    def permanently_delete_archive(archive_id: str):
        try:
            get_store().permanently_delete_archive(archive_id)
        except NotFoundError:
            abort(404)
        return redirect(url_for("archive"))

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
                    render_template("settings.html", settings=current, error=str(error)),
                    400,
                )
            return redirect(url_for("settings", saved="yes"))
        return render_template(
            "settings.html",
            settings=current,
            saved=request.args.get("saved") == "yes",
        )

    return app
