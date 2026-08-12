from __future__ import annotations

from dataclasses import dataclass, field

from .store import CATEGORY_DELIMITER, Category


@dataclass
class CategoryTreeNode:
    label: str
    name: str
    category: Category | None = None
    children: list[CategoryTreeNode] = field(default_factory=list)
    in_selected_path: bool = False

    @property
    def exists(self) -> bool:
        return self.category is not None


@dataclass(frozen=True)
class CategoryCrumb:
    label: str
    name: str
    exists: bool


def build_category_tree(
    categories: list[Category], selected: str | None = None
) -> list[CategoryTreeNode]:
    categories_by_name = {category.name: category for category in categories}
    nodes: dict[tuple[str, ...], CategoryTreeNode] = {}

    for category in categories:
        segments = category.name.split(CATEGORY_DELIMITER)
        for depth in range(1, len(segments) + 1):
            path = tuple(segments[:depth])
            name = CATEGORY_DELIMITER.join(path)
            nodes.setdefault(path, CategoryTreeNode(label=path[-1], name=name))

    for path, node in nodes.items():
        node.category = categories_by_name.get(node.name)
        node.in_selected_path = selected == node.name or bool(
            selected and selected.startswith(f"{node.name}{CATEGORY_DELIMITER}")
        )
        if len(path) > 1:
            nodes[path[:-1]].children.append(node)

    def sort_key(node: CategoryTreeNode) -> tuple[str, str]:
        return node.label.casefold(), node.label

    for node in nodes.values():
        node.children.sort(key=sort_key)
    return sorted((node for path, node in nodes.items() if len(path) == 1), key=sort_key)


def build_category_crumbs(selected: str, categories: list[Category]) -> list[CategoryCrumb]:
    existing_names = {category.name for category in categories}
    segments = selected.split(CATEGORY_DELIMITER)
    return [
        CategoryCrumb(
            label=segment,
            name=CATEGORY_DELIMITER.join(segments[: index + 1]),
            exists=CATEGORY_DELIMITER.join(segments[: index + 1]) in existing_names,
        )
        for index, segment in enumerate(segments)
    ]
