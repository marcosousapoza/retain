from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence

from .store import RetainError, Store


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retain", description="Retain categorized memories")
    resources = parser.add_subparsers(dest="resource", required=True)

    category = resources.add_parser("category", help="Manage categories")
    category_commands = category.add_subparsers(dest="command", required=True)
    category_commands.add_parser("list", help="List categories")
    category_create = category_commands.add_parser("create", help="Create a category")
    category_create.add_argument("name")
    category_delete = category_commands.add_parser("delete", help="Delete a category")
    category_delete.add_argument("name")
    category_delete.add_argument(
        "--force", action="store_true", help="Also delete memories in the category"
    )

    memory = resources.add_parser("memory", help="Manage memories")
    memory_commands = memory.add_subparsers(dest="command", required=True)
    memory_list = memory_commands.add_parser("list", help="List memories in a category")
    memory_list.add_argument("category")
    memory_get = memory_commands.add_parser("get", help="Fetch one memory")
    memory_get.add_argument("id")
    memory_add = memory_commands.add_parser("add", help="Add a memory")
    memory_add.add_argument("category")
    memory_add.add_argument("content")
    memory_add.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    memory_update = memory_commands.add_parser("update", help="Update a memory")
    memory_update.add_argument("id")
    memory_update.add_argument("--content")
    memory_update.add_argument("--priority", type=int, choices=range(1, 6))
    memory_delete = memory_commands.add_parser("delete", help="Delete a memory")
    memory_delete.add_argument("id")
    return parser


def run(args: argparse.Namespace, store: Store) -> None:
    if args.resource == "category":
        if args.command == "list":
            _print_json([category.to_dict() for category in store.list_categories()])
        elif args.command == "create":
            _print_json(store.create_category(args.name).to_dict())
        elif args.command == "delete":
            store.delete_category(args.name, force=args.force)
        return

    if args.command == "list":
        _print_json([memory.to_dict() for memory in store.list_memories(args.category)])
    elif args.command == "get":
        _print_json(store.get_memory(args.id).to_dict())
    elif args.command == "add":
        _print_json(store.add_memory(args.category, args.content, args.priority).to_dict())
    elif args.command == "update":
        _print_json(
            store.update_memory(args.id, content=args.content, priority=args.priority).to_dict()
        )
    elif args.command == "delete":
        store.delete_memory(args.id)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args, Store())
    except (RetainError, OSError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
