# retain-memory

`retain-memory` is a small command-line tool and MCP server for keeping categorized
memories in one local SQLite database. Memories have priorities from 1 (lowest) to 5
(highest) and UTC creation/update timestamps.

Categories are intentionally managed only through the CLI. MCP clients can list
categories and create, retrieve, update, or delete memories within them.

## Installation

[Install uv](https://docs.astral.sh/uv/getting-started/installation/), then install the
CLI from PyPI:

```console
uv tool install retain-memory
```

To install the current source checkout instead:

```console
uv tool install .
```

Set `MEMORY_FILE` to the database location. The directory and database are created on
first use:

```console
export MEMORY_FILE="$HOME/.local/share/retain/memory.db"
```

## CLI

Create and inspect categories:

```console
retain category create projects
retain category list
retain category delete projects
retain category delete projects --force
```

`--force` is required to delete a category that contains memories.

Manage memories:

```console
retain memory add projects "Publish the first release" --priority 5
retain memory list projects
retain memory get MEMORY_ID
retain memory update MEMORY_ID --content "Publish version 1.0" --priority 4
retain memory delete MEMORY_ID
```

Commands that return data print JSON. Category memory lists are ordered by priority
descending and creation time descending.

## MCP Installation

The PyPI package includes the `retain-mcp` stdio server. An MCP client can launch it
without a separate installation through `uvx`. For clients using the common
`mcpServers` configuration format:

```json
{
  "mcpServers": {
    "retain": {
      "command": "uvx",
      "args": ["--from", "retain-memory", "retain-mcp"],
      "env": {
        "MEMORY_FILE": "/absolute/path/to/memory.db"
      }
    }
  }
}
```

If the package was installed with `uv tool install retain-memory`, use
`"command": "retain-mcp"` and omit `args`. For development from this checkout, use
`"command": "uv"` with `"args": ["run", "--directory", "/absolute/path/to/retain",
"retain-mcp"]`.

The MCP server exposes:

- `list_categories`
- `get_memories`
- `add_memory`
- `update_memory`
- `delete_memory`

It does not expose category creation or deletion. Create categories with
`retain category create NAME` before adding memories through MCP.

## Development

```console
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

## Publishing

GitHub Actions runs checks on pushes and pull requests. Pushing a version tag builds
the wheel and source distribution and publishes them to PyPI using trusted publishing.
Tags must use a `v` prefix and exactly match the version in `pyproject.toml`:

```console
uv version 0.2.0
git add pyproject.toml uv.lock
git commit -m "Release 0.2.0"
git tag v0.2.0
git push origin main v0.2.0
```

Before the first release, create the `retain-memory` project (or a pending publisher)
on PyPI and configure a trusted publisher with this repository, workflow
`publish.yml`, and environment `pypi`. No PyPI API token is stored in GitHub.
