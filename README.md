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

The [`retain-memory` PyPI project](https://pypi.org/project/retain-memory/) and its
trusted publisher are already configured. No PyPI API token is stored in GitHub.

To prepare a release, update the package version and push the release commit:

```console
uv version 0.2.0
git add pyproject.toml uv.lock
git commit -m "Release 0.2.0"
git push origin main
```

After CI passes, create and push an annotated tag matching the version in
`pyproject.toml`:

```console
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
```

The tag triggers `publish.yml`, which builds and publishes the wheel and source
distribution through PyPI trusted publishing. Tags must use the `v` prefix and match
the package version exactly.
