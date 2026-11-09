from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tasklane.cli import main

TODAY = date(2026, 11, 9)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never let a test reach the real ~/todo.txt."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("TASKLANE_FILE", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    return home


@pytest.fixture
def todo(tmp_path) -> Path:
    return tmp_path / "todo.txt"


@pytest.fixture
def run(capsys, todo):
    def _run(*args: str, today: date = TODAY, file: Path | None = None):
        argv = ["--file", str(file or todo), *args]
        code = main(argv, today=today)
        out, err = capsys.readouterr()
        return code, out, err

    return _run


def write(path: Path, text: str, newline: str = "\n") -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
