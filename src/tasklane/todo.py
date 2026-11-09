"""Parse and format a single todo.txt line.

The format is described at https://github.com/todotxt/todo.txt.  In short::

    x 2026-11-09 2026-11-01 (text with +project @context key:value)
    (A) 2026-11-01 text ...

* ``x `` (lowercase, followed by a space) at the very start marks completion.
* A completed task may carry a completion date, then a creation date.
* An open task may start with a priority ``(A)``-``(Z)`` followed by a space.
* Projects are words starting with ``+``, contexts words starting with ``@``.
* Tags are ``key:value`` words where neither side is empty or contains ``:``.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import date

_PRIORITY = re.compile(r"\(([A-Z])\)(?: |$)")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_date(value: str | None) -> date | None:
    """Return a date for a strict ``YYYY-MM-DD`` string, else ``None``."""
    if not value or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def split_tag(word: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` if *word* is a todo.txt ``key:value`` tag.

    URLs such as ``https://example.com`` are not tags: their value starts with
    ``//`` and anything with a second ``:`` (``http://host:8080``) is rejected
    by the spec rule that neither side may contain a colon.
    """
    key, sep, value = word.partition(":")
    if not sep or not key or not value:
        return None
    if ":" in value or value.startswith("//"):
        return None
    if key[0] in "+@":
        return None
    return key, value


@dataclass
class Task:
    """One parsed todo.txt task. ``text`` is the description after the prefix."""

    text: str = ""
    done: bool = False
    priority: str | None = None
    completion_date: date | None = None
    creation_date: date | None = None

    # -- derived views -------------------------------------------------------
    @property
    def words(self) -> list[str]:
        return self.text.split()

    @property
    def projects(self) -> list[str]:
        return _unique(w[1:] for w in self.words if w.startswith("+") and len(w) > 1)

    @property
    def contexts(self) -> list[str]:
        return _unique(w[1:] for w in self.words if w.startswith("@") and len(w) > 1)

    @property
    def tags(self) -> dict[str, str]:
        """Tags in order of appearance; the first occurrence of a key wins."""
        result: dict[str, str] = {}
        for word in self.words:
            tag = split_tag(word)
            if tag and tag[0] not in result:
                result[tag[0]] = tag[1]
        return result

    @property
    def due(self) -> date | None:
        return parse_date(self.tags.get("due"))

    @property
    def threshold(self) -> date | None:
        """The ``t:YYYY-MM-DD`` threshold (start) date, if valid."""
        return parse_date(self.tags.get("t"))

    def deferred(self, today: date) -> bool:
        """True for an open task whose threshold date is still in the future."""
        start = self.threshold
        return not self.done and start is not None and start > today

    # -- mutation helpers ----------------------------------------------------
    def copy(self) -> Task:
        return dataclasses.replace(self)

    def set_tag(self, key: str, value: str) -> None:
        """Replace the first ``key:`` tag in place, or append a new one."""
        tokens = self.text.split(" ")
        for i, token in enumerate(tokens):
            tag = split_tag(token)
            if tag and tag[0] == key:
                tokens[i] = f"{key}:{value}"
                self.text = " ".join(tokens)
                return
        self.text = f"{self.text} {key}:{value}" if self.text else f"{key}:{value}"

    def remove_tag(self, key: str) -> None:
        tokens = self.text.split(" ")
        for i, token in enumerate(tokens):
            tag = split_tag(token)
            if tag and tag[0] == key:
                del tokens[i]
                self.text = " ".join(tokens).strip(" ")
                return

    def complete(self, today: date) -> None:
        """Mark done. The priority is kept as a ``pri:X`` tag so undo can restore it."""
        if self.done:
            return
        self.done = True
        self.completion_date = today
        if self.priority:
            self.set_tag("pri", self.priority)
            self.priority = None

    def uncomplete(self) -> None:
        if not self.done:
            return
        self.done = False
        self.completion_date = None
        pri = self.tags.get("pri", "")
        if len(pri) == 1 and "A" <= pri <= "Z":
            self.priority = pri
            self.remove_tag("pri")

    def format(self) -> str:
        return format_task(self)


def _unique(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _take_date(rest: str) -> tuple[date | None, str]:
    token, _, after = rest.partition(" ")
    found = parse_date(token)
    if found is None:
        return None, rest
    return found, after


def parse_task(line: str) -> Task:
    """Parse one line (without its line ending) into a :class:`Task`."""
    task = Task()
    rest = line
    if rest.startswith("x "):
        task.done = True
        rest = rest[2:]
        task.completion_date, rest = _take_date(rest)
        if task.completion_date is not None:
            task.creation_date, rest = _take_date(rest)
    else:
        match = _PRIORITY.match(rest)
        if match:
            task.priority = match.group(1)
            rest = rest[match.end():]
        task.creation_date, rest = _take_date(rest)
    task.text = rest
    return task


def format_task(task: Task) -> str:
    parts: list[str] = []
    if task.done:
        parts.append("x")
        if task.completion_date:
            parts.append(task.completion_date.isoformat())
    elif task.priority:
        parts.append(f"({task.priority})")
    if task.creation_date and (not task.done or task.completion_date):
        parts.append(task.creation_date.isoformat())
    if task.text:
        parts.append(task.text)
    return " ".join(parts)
