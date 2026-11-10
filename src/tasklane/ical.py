"""Export tasks as an iCalendar (RFC 5545) file of ``VTODO`` entries.

Calendar and task apps (Thunderbird, Apple Reminders via a subscribed file,
Nextcloud Tasks, Outlook) can import the result. Each task becomes one
``VTODO``:

* ``SUMMARY`` is the task description; ``due:`` and ``t:`` tags are dropped
  from it because they become ``DUE`` and ``DTSTART`` (all-day dates).
* ``PRIORITY`` maps ``(A)``..``(I)`` to 1..9 (1 is highest in iCalendar);
  later letters map to 9. A completed task uses the ``pri:X`` tag ``do`` left.
* ``+projects`` and ``@contexts`` become ``CATEGORIES``.
* ``CREATED`` and ``COMPLETED`` come from the creation and completion dates;
  ``STATUS`` is ``NEEDS-ACTION`` or ``COMPLETED``.
* ``UID`` is derived from the creation date and description, so exporting the
  same file again updates the same entries instead of duplicating them, even
  after the line numbers change.

Lines are folded at 75 octets without splitting a UTF-8 character and end in
CRLF, as the RFC requires.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date

from . import __version__
from .todo import Task, split_tag

PRODID = f"-//tasklane//tasklane {__version__}//EN"
_MAPPED_TAGS = ("due", "t")
_FOLD_OCTETS = 75


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines."""
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fold(line: str) -> str:
    """Fold a content line into chunks of at most 75 octets joined by CRLF + space."""
    pieces: list[str] = []
    current = ""
    size = 0
    limit = _FOLD_OCTETS
    for char in line:
        width = len(char.encode("utf-8", "surrogateescape"))
        if size + width > limit:
            pieces.append(current)
            current, size = "", 0
            limit = _FOLD_OCTETS - 1  # continuation lines start with a space
        current += char
        size += width
    pieces.append(current)
    return "\r\n ".join(pieces)


def _date(day: date) -> str:
    return day.strftime("%Y%m%d")


def _stamp(day: date) -> str:
    return day.strftime("%Y%m%dT000000Z")


def summary(task: Task) -> str:
    """The description without the tags that become DUE/DTSTART."""
    mapped = (*_MAPPED_TAGS, "pri") if _done_priority(task) else _MAPPED_TAGS
    words = []
    for word in task.text.split():
        tag = split_tag(word)
        if tag and tag[0] in mapped:
            continue
        words.append(word)
    return " ".join(words)


def _done_priority(task: Task) -> str | None:
    """The ``pri:X`` tag that ``do`` leaves on a completed task, if valid."""
    value = task.tags.get("pri", "") if task.done else ""
    return value if len(value) == 1 and "A" <= value <= "Z" else None


def priority(task: Task) -> int | None:
    """iCalendar PRIORITY (1 highest .. 9 lowest) for ``(A)`` .. ``(Z)``."""
    letter = _done_priority(task) if task.done else task.priority
    if not letter:
        return None
    return min(ord(letter) - ord("A") + 1, 9)


def uid(task: Task) -> str:
    created = task.creation_date.isoformat() if task.creation_date else ""
    digest = hashlib.sha1(f"{created}\n{summary(task)}".encode("utf-8", "surrogateescape")).hexdigest()
    return f"{digest[:20]}@tasklane"


def vtodo(task: Task, stamp: date) -> list[str]:
    lines = [
        "BEGIN:VTODO",
        f"UID:{uid(task)}",
        f"DTSTAMP:{_stamp(stamp)}",
    ]
    if task.creation_date:
        lines.append(f"CREATED:{_stamp(task.creation_date)}")
    lines.append(f"SUMMARY:{escape_text(summary(task) or task.text)}")
    due, start = task.due, task.threshold
    if start is not None and (due is None or start <= due):
        lines.append(f"DTSTART;VALUE=DATE:{_date(start)}")
    if due is not None:
        lines.append(f"DUE;VALUE=DATE:{_date(due)}")
    pri = priority(task)
    if pri is not None:
        lines.append(f"PRIORITY:{pri}")
    categories = [*task.projects, *task.contexts]
    if categories:
        lines.append("CATEGORIES:" + ",".join(escape_text(c) for c in categories))
    if task.done:
        lines.append("STATUS:COMPLETED")
        if task.completion_date:
            lines.append(f"COMPLETED:{_stamp(task.completion_date)}")
    else:
        lines.append("STATUS:NEEDS-ACTION")
    lines.append("END:VTODO")
    return lines


def calendar(tasks: Iterable[Task], stamp: date) -> str:
    """Return a complete VCALENDAR document (CRLF line endings)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN"]
    for task in tasks:
        lines.extend(vtodo(task, stamp))
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
