"""Reading and atomically writing todo.txt files without losing anything.

Every physical line is kept as an :class:`Entry` holding its exact text and
its own line ending, so a file is written back byte-for-byte unless a task was
changed. Only modified tasks are re-serialised. A UTF-8 BOM is remembered and
restored; bytes that are not valid UTF-8 survive via ``surrogateescape``.

A file read with :meth:`TodoFile.load` remembers a fingerprint (SHA-256 of the
bytes plus their modification time). :meth:`TodoFile.save` refuses to replace
the file if another program, an editor or a sync client changed it in the
meantime without merging: changes to different lines are combined with a
three-way merge (see :mod:`tasklane.merge`), and only edits of the same lines,
a deleted file or one created by someone else raise :class:`FileChangedError`
instead of silently discarding those edits.
"""

from __future__ import annotations

import codecs
import hashlib
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .merge import Conflict, join_merged, merge_bytes
from .todo import Task, format_task, parse_task

_LINE = re.compile(r"([^\r\n]*)(\r\n|\n|\r)")
_ENCODING = "utf-8"
_ERRORS = "surrogateescape"


class TaskIndexError(LookupError):
    """Raised for a line number that does not hold a task."""


class FileChangedError(Exception):
    """Raised by :meth:`TodoFile.save` when the file changed since it was loaded."""

    def __init__(self, path: Path, detail: str, conflicts: list[Conflict] | None = None):
        self.path = Path(path)
        self.detail = detail
        self.conflicts = conflicts or []
        super().__init__(f"{self.path.name} {detail} since tasklane read it; nothing was written")


_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class Fingerprint:
    """What a file looked like on disk. A missing file hashes like an empty
    one, so creating or deleting an *empty* file is not a conflict."""

    exists: bool
    sha256: str = _EMPTY_SHA256
    mtime_ns: int = 0

    @classmethod
    def of_bytes(cls, data: bytes, mtime_ns: int) -> Fingerprint:
        return cls(True, hashlib.sha256(data).hexdigest(), mtime_ns)


def _read_with_mtime(path: Path) -> tuple[bytes, int] | None:
    try:
        with open(path, "rb") as handle:
            mtime_ns = os.fstat(handle.fileno()).st_mtime_ns
            return handle.read(), mtime_ns
    except FileNotFoundError:
        return None


def fingerprint(path: Path | str) -> Fingerprint:
    found = _read_with_mtime(Path(path))
    return Fingerprint(False) if found is None else Fingerprint.of_bytes(*found)


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
        # Set by load(); None (as after from_bytes) means "do not check".
        self.loaded: Fingerprint | None = None
        self._base = b""  # the bytes load() read, the base of a merge
        # After a save that merged edits from another program: True, plus the
        # new number of every line whose number changed (None if it is gone).
        self.merged = False
        self.renumbered: dict[int, int | None] = {}

    # -- loading -------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str) -> TodoFile:
        path = Path(path)
        found = _read_with_mtime(path)
        if found is None:
            tf = cls.from_bytes(path, b"")
            tf.loaded = Fingerprint(False)
        else:
            tf = cls.from_bytes(path, found[0])
            tf.loaded = Fingerprint.of_bytes(*found)
            tf._base = found[0]
        return tf

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

    def number(self, n: int) -> int:
        """Line *n*'s number after the last save (a merge can move lines)."""
        new = self.renumbered.get(n, n)
        return n if new is None else new

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

    def _changed_detail(self, now: Fingerprint) -> str:
        if not now.exists:
            return "was deleted"
        when = datetime.fromtimestamp(now.mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")
        if not self.loaded or not self.loaded.exists:
            return f"was created by another program (at {when})"
        return f"was changed on disk (modified {when})"

    def check_unchanged(self) -> None:
        """Raise :class:`FileChangedError` if the file on disk no longer holds
        the bytes :meth:`load` read. Only content counts: a file that was just
        touched (new mtime, same bytes), as sync clients often do, is fine."""
        if self.loaded is None:
            return
        now = fingerprint(self.path)
        if now.sha256 != self.loaded.sha256:
            raise FileChangedError(self.path, self._changed_detail(now))

    def bytes_to_save(self) -> tuple[bytes, list[int | None] | None]:
        """What :meth:`save` would write now, merged with edits another program
        made since :meth:`load`, plus (after a merge) the new 0-based index of
        each of our lines. Raises :class:`FileChangedError` when the edits
        overlap, or when the file was deleted or created by someone else."""
        data = self.to_bytes()
        if self.loaded is None:
            return data, None
        found = _read_with_mtime(self.path)
        now = Fingerprint(False) if found is None else Fingerprint.of_bytes(*found)
        if now.sha256 == self.loaded.sha256:
            return data, None
        if found is None or not self.loaded.exists:
            raise FileChangedError(self.path, self._changed_detail(now))
        result = merge_bytes(self._base, data, found[0])
        if not result.clean:
            detail = self._changed_detail(now) + " in the same lines"
            raise FileChangedError(self.path, detail, result.conflicts)
        return join_merged(result), result.ours_at

    def save(self) -> None:
        """Write the file atomically, merging edits made since :meth:`load`.

        The check happens right before the atomic replace, so the remaining
        race window is a few milliseconds rather than the whole command. After
        a merge the entries are re-read from the merged bytes and
        :attr:`renumbered` says where lines moved.
        """
        data, ours_at = self.bytes_to_save()
        atomic_write(self.path, data)
        self.merged, self.renumbered = False, {}
        if ours_at is not None:
            fresh = TodoFile.from_bytes(self.path, data)
            self.entries, self.bom, self.newline = fresh.entries, fresh.bom, fresh.newline
            self.merged = True
            self.renumbered = {
                old: (None if new is None else new + 1)
                for old, new in enumerate(ours_at, 1)
                if new is None or new + 1 != old
            }
        if self.loaded is not None:
            self.loaded = Fingerprint.of_bytes(data, os.stat(self.path).st_mtime_ns)
            self._base = data


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
