from __future__ import annotations

import json
from unittest.mock import Mock, patch

from retain_memory.cli import main


def invoke(monkeypatch, tmp_path, capsys, *args):
    monkeypatch.setenv("MEMORY_FILE", str(tmp_path / "memory.db"))
    exit_code = main(args)
    captured = capsys.readouterr()
    return exit_code, captured


def test_cli_category_and_memory_flow(monkeypatch, tmp_path, capsys):
    exit_code, captured = invoke(monkeypatch, tmp_path, capsys, "category", "create", "personal")
    assert exit_code == 0
    assert json.loads(captured.out)["name"] == "personal"

    exit_code, captured = invoke(
        monkeypatch,
        tmp_path,
        capsys,
        "memory",
        "add",
        "personal",
        "Call Alice",
        "--priority",
        "5",
    )
    assert exit_code == 0
    memory = json.loads(captured.out)
    assert memory["priority"] == 5

    exit_code, captured = invoke(monkeypatch, tmp_path, capsys, "memory", "list", "personal")
    assert exit_code == 0
    assert json.loads(captured.out) == [memory]


def test_cli_uses_default_location_without_environment_variable(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MEMORY_FILE", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert main(["category", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert (tmp_path / "data/retain/memory.db").is_file()


def test_cli_refuses_nonempty_category_deletion(monkeypatch, tmp_path, capsys):
    invoke(monkeypatch, tmp_path, capsys, "category", "create", "notes")
    invoke(monkeypatch, tmp_path, capsys, "memory", "add", "notes", "Keep this")

    exit_code, captured = invoke(monkeypatch, tmp_path, capsys, "category", "delete", "notes")

    assert exit_code == 1
    assert "--force" in captured.err


def test_cli_starts_web_with_saved_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_FILE", str(tmp_path / "memory.db"))
    app = Mock()

    with patch("retain_memory.web.create_app", return_value=app):
        assert main(["web"]) == 0

    app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)
