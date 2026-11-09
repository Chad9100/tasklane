"""Reading and atomically writing todo.txt files without losing anything.

Every physical line is kept as an :class:`Entry` holding its exact text and
its own line ending, so a file is written back byte-for-byte unless a task was
changed. Only modified tasks are re-serialised. A UTF-8 BOM is remembered and
restored; bytes that are not valid UTF-8 survive via ``surrogateescape``.
"""

from __future__ import annotations

import codecs
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .todo import Task, format_task, parse_task

_LINE = re.compile(r"([^\r\n]*)(\r\n|\n|\r)")
_ENCODING = "utf-8"
_ERRORS = "surrogateescape"


class TaskIndexError(LookupError):
    """Raised for a line number that does not hold a task."""


@dataclass
class Entry:
    raw: str
    ending: str
    task: Task | None
    dirty: bool = False

    @property
    def text(self) -> str:
        if self.dirty and self.task is not None:
            return format_task(self.task)
        return self.raw


def _make_entry(raw: str, ending: str) -> Entry:
    task = parse_task(raw) if raw.strip() else None
    return Entry(raw, ending, task)


def done_path_for(todo_path: Path) -> Path:
    return Path(todo_path).with_name("done.txt")


class TodoFile:
    def __init__(self, path: Path, entries: list[Entry], bom: bool = False, newline: str = "\n"):
        self.path = Path(path)
        self.entries = entries
        self.bom = bom
        self.newline = newline

    # -- loading -------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str) -> TodoFile:
        path = Path(path)
        data = path.read_bytes() if path.exists() else b""
        return cls.from_bytes(path, data)

    @classmethod
    def from_bytes(cls, path: Path | str, data: bytes) -> TodoFile:
        bom = data.startswith(codecs.BOM_UTF8)
        if bom:
            data = data[len(codecs.BOM_UTF8):]
        text = data.decode(_ENCODING, _ERRORS)
        entries: list[Entry] = []
        newline = None
        pos = 0
        for match in _LINE.finditer(text):
            entries.append(_make_entry(match.group(1), match.group(2)))
            newline = newline or match.group(2)
            pos = match.end()
        if pos < len(text):
            entries.append(_make_entry(text[pos:], ""))
        return cls(Path(path), entries, bom, newline or "\n")

    # -- access --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    def _entry(self, n: int) -> Entry:
        if not 1 <= n <= len(self.entries) or self.entries[n - 1].task is None:
            raise TaskIndexError(f"no task {n} in {self.path.name}")
        return self.entries[n - 1]

    def get(self, n: int) -> Task:
        """Return a copy of task *n* (1-based line number)."""
        return self._entry(n).task.copy()  # type: ignore[union-attr]

    def text(self, n: int) -> str:
        return self._entry(n).text

    def tasks(self) -> list[tuple[int, Task]]:
        return [(i, e.task) for i, e in enumerate(self.entries, 1) if e.task is not None]

    # -- mutation ------------------------------------------------------------
    def set(self, n: int, task: Task) -> None:
        entry = self._entry(n)
        entry.task = task.copy()
        entry.dirty = True

    def append(self, task: Task) -> int:
        self.entries.append(Entry(format_task(task), self.newline, task.copy(), dirty=True))
        return len(self.entries)

    def append_raw(self, raw: str) -> int:
        self.entries.append(_make_entry(raw, self.newline))
        return len(self.entries)

    def blank(self, n: int) -> None:
        """Empty line *n* so that the numbers of later lines do not change."""
        entry = self._entry(n)
        entry.raw, entry.task, entry.dirty = "", None, False

    def remove_done(self) -> list[str]:
        """Drop completed tasks and blank lines; return the removed task lines."""
        removed: list[str] = []
        kept: list[Entry] = []
        for entry in self.entries:
            if entry.task is None:
                continue
            if entry.task.done:
                removed.append(entry.text)
            else:
                kept.append(entry)
        self.entries = kept
        return removed

    # -- writing -------------------------------------------------------------
    def to_text(self) -> str:
        parts: list[str] = []
        last = len(self.entries) - 1
        for i, entry in enumerate(self.entries):
            ending = entry.ending
            if not ending and i < last:
                ending = self.newline
            parts.append(entry.text + ending)
        return "".join(parts)

    def to_bytes(self) -> bytes:
        data = self.to_text().encode(_ENCODING, _ERRORS)
        return (codecs.BOM_UTF8 + data) if self.bom else data

    def save(self) -> None:
        atomic_write(self.path, self.to_bytes())


def atomic_write(path: Path | str, data: bytes) -> None:
    """Write *data* to a temp file beside *path*, fsync, then replace *path*."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace(src: str, dst: Path, attempts: int = 5) -> None:
    # On Windows a reader (editor, sync client) can briefly hold the target
    # open, which makes os.replace fail with PermissionError; retry a little.
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
