# retain-memory

`retain-memory` is a small command-line tool and MCP server for keeping categorized
memories in one local SQLite database. Memories have priorities from 1 (lowest) to 5
(highest) and UTC creation/update timestamps.

Categories are managed through the CLI or web interface. MCP clients can list categories
and create, retrieve, update, or delete memories within them.

Category names can form a hierarchy using the Anki-style `::` delimiter, for example
`projects::retain::release`. Each part must be non-empty and cannot contain a colon.
Categories can also have an optional description explaining what belongs in them. MCP
category listings include these descriptions so clients can choose the appropriate leaf.

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

No setup is required before the first run. By default, Retain creates its database and
settings at `$XDG_DATA_HOME/retain/memory.db`, or
`$HOME/.local/share/retain/memory.db` when `XDG_DATA_HOME` is unset.

Set `MEMORY_FILE` to use a different database location:

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

## Web interface

Start the local Flask interface with:

```console
retain web
```

It provides memory and category editing, displays hierarchical categories as trees,
and includes settings for the default priority, category size limit, memory word limit,
and web host/port. Categories initially allow 100 memories and memories initially allow
500 words. Lowering a limit does not delete existing data. Saved host and port changes
take effect on the next start. They can be overridden for one run:

```console
retain web --host 0.0.0.0 --port 8080
```

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

`list_categories` exposes only leaf categories, and `get_memories` rejects categories
that have subcategories. Reads never implicitly combine a parent with its descendants.

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
