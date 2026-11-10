"""Find and fold in the conflicted copies sync services leave behind.

When two devices change ``todo.txt`` at once, Dropbox and Nextcloud keep one
version and save the other as ``todo (conflicted copy 2026-11-10).txt`` (the
copy may also carry a device or user name), Syncthing as
``todo.sync-conflict-20261110-123456-ABCDEFG.txt``. There is no common
ancestor to merge against, so :func:`new_lines` just reports the task lines of
a copy that the real file does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

_DROPBOX = re.compile(r" \([^()]*conflicted copy[^()]*\)(?:\s*\(\d+\))?$", re.IGNORECASE)
_SYNCTHING = re.compile(r"\.sync-conflict-\d{8}-\d{6}(?:-[A-Z0-9]+)?$")
MERGED_SUFFIX = ".merged"


def find_copies(path: Path | str) -> list[Path]:
    """Conflicted copies of *path* in its folder, oldest name first."""
    path = Path(path)
    found: list[Path] = []
    try:
        candidates = sorted(path.parent.iterdir(), key=lambda p: p.name)
    except OSError:
        return found
    for other in candidates:
        if other == path or other.suffix != path.suffix or not other.is_file():
            continue
        stem = other.name[: len(other.name) - len(other.suffix)] if other.suffix else other.name
        for pattern in (_DROPBOX, _SYNCTHING):
            match = pattern.search(stem)
            if match and stem[: match.start()] == path.stem:
                found.append(other)
                break
    return found


def _lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", "surrogateescape").lstrip("﻿")
    return [line for line in text.splitlines() if line.strip()]


def new_lines(current: bytes, copy: bytes) -> list[str]:
    """Non-blank lines of *copy* that *current* lacks (compared as exact text,
    ignoring line endings), in the copy's order and without repeats."""
    have = set(_lines(current))
    out: list[str] = []
    for line in _lines(copy):
        if line not in have:
            have.add(line)
            out.append(line)
    return out


def merged_name(copy: Path) -> Path:
    """Where a folded-in copy is moved: ``<name>.merged`` (numbered if taken)."""
    target, n = copy.with_name(copy.name + MERGED_SUFFIX), 1
    while target.exists():
        n += 1
        target = copy.with_name(f"{copy.name}{MERGED_SUFFIX}-{n}")
    return target
