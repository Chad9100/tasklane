"""Line-level three-way merge for todo.txt files.

When another program (an editor, a phone app, Dropbox or Syncthing) changed
the file while tasklane was working on it, there are three versions: *base*
(what tasklane read), *ours* (what tasklane wants to write) and *theirs* (what
is on disk now). :func:`merge3` keeps every change that only one side made and
reports a :class:`Conflict` where both sides changed the same lines
differently.

todo.txt lines are independent tasks, so two differences from the usual
diff3 rules apply: changes to neighbouring lines do not conflict, and lines
that both sides *inserted* at the same place (typically both appended a task)
are all kept, ours first, so the numbers tasklane just printed stay valid.

When both sides changed the same task, :func:`merge_task_line` merges it field
by field (done state, priority, dates, and the words of the description), so
completing a task on one side and changing its priority on the other is not a
conflict either.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Sequence

from .todo import Task, format_task, parse_task


@dataclass(frozen=True)
class Conflict:
    """Base lines ``start:end`` (0-based) were changed differently on each side."""

    start: int
    end: int
    base: list
    ours: list
    theirs: list


@dataclass
class MergeResult:
    lines: list
    conflicts: list[Conflict] = field(default_factory=list)
    # For every line of *ours*, its index in ``lines`` (None if theirs dropped it).
    ours_at: list[int | None] = field(default_factory=list)
    bom: bool = False  # set by merge_bytes

    @property
    def clean(self) -> bool:
        return not self.conflicts


def _hunks(base: Sequence, other: Sequence) -> list[tuple[int, int, list]]:
    matcher = SequenceMatcher(None, base, other, autojunk=False)
    return [
        (i1, i2, list(other[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _apply(base: Sequence, hunks: list[tuple[int, int, list]], start: int, end: int) -> list:
    out: list = []
    pos = start
    for s, e, lines in hunks:
        out.extend(base[pos:s])
        out.extend(lines)
        pos = e
    out.extend(base[pos:end])
    return out


def merge3(
    base: Sequence,
    ours: Sequence,
    theirs: Sequence,
    resolve: Callable | None = None,
    insert_both_at_end_only: bool = False,
) -> MergeResult:
    """Merge two edited copies of *base*, line by line.

    Items both sides inserted at the same point are all kept (ours first);
    with *insert_both_at_end_only* that holds only at the very end and
    elsewhere it is a conflict. Where both sides changed the same lines and the region has the same length
    in all three versions, ``resolve(base_line, our_line, their_line)`` is
    asked for each line both changed differently; it returns the merged line,
    or None to leave the region a conflict."""
    tagged = [(s, e, 0, lines) for s, e, lines in _hunks(base, ours)]
    tagged += [(s, e, 1, lines) for s, e, lines in _hunks(base, theirs)]
    tagged.sort(key=lambda h: (h[0], h[1], h[2]))

    # Group hunks whose base ranges overlap, and insertions at the same point.
    # An insertion right before or after the other side's change stays apart.
    clusters: list[tuple[int, int, list]] = []
    for hunk in tagged:
        s, e = hunk[0], hunk[1]
        if clusters:
            cs, ce, members = clusters[-1]
            if s < ce or s == e == cs == ce:
                clusters[-1] = (cs, max(ce, e), members + [hunk])
                continue
        clusters.append((s, e, [hunk]))

    result = MergeResult([])
    pos = 0  # next base line to copy

    def keep_ours(lines: list) -> None:
        for line in lines:
            result.ours_at.append(len(result.lines))
            result.lines.append(line)

    for start, end, members in clusters:
        keep_ours(list(base[pos:start]))
        mine = [(s, e, lines) for s, e, side, lines in members if side == 0]
        other = [(s, e, lines) for s, e, side, lines in members if side == 1]
        ours_v = _apply(base, mine, start, end)
        theirs_v = _apply(base, other, start, end)
        if not other or ours_v == theirs_v:
            keep_ours(ours_v)
        elif not mine:
            result.ours_at.extend([None] * len(ours_v))
            result.lines.extend(theirs_v)
        elif start == end and (not insert_both_at_end_only or start == len(base)):
            # both only inserted lines here
            keep_ours(ours_v)
            result.lines.extend(theirs_v)
        elif (resolved := _resolve_lines(resolve, base[start:end], ours_v, theirs_v)) is not None:
            keep_ours(resolved)
        else:
            result.conflicts.append(
                Conflict(start, end, list(base[start:end]), ours_v, theirs_v)
            )
            keep_ours(ours_v)  # placeholder so ours_at stays complete
        pos = end
    keep_ours(list(base[pos:]))
    return result


def _resolve_lines(resolve, base, ours, theirs) -> list | None:
    if resolve is None or not len(base) == len(ours) == len(theirs):
        return None
    out = []
    for b, o, t in zip(base, ours, theirs):
        if o == t or t == b:
            out.append(o)
        elif o == b:
            out.append(t)
        else:
            merged = resolve(b, o, t)
            if merged is None:
                return None
            out.append(merged)
    return out


# -- one task, field by field ------------------------------------------------
_NO_MERGE = object()


def _field(base, ours, theirs):
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    return _NO_MERGE


def _fields(task: Task) -> tuple:
    """(done, completion date, priority, creation date, words). A completed
    task's ``pri:X`` tag counts as its priority, so completing ``(B) task``
    changes only the done state and the other side's new priority survives."""
    priority, text = task.priority, task.text
    pri = task.tags.get("pri", "")
    if task.done and len(pri) == 1 and "A" <= pri <= "Z":
        stripped = task.copy()
        stripped.remove_tag("pri")
        priority, text = pri, stripped.text
    return task.done, task.completion_date, priority, task.creation_date, text.split(" ")


def merge_task_line(base: str, ours: str, theirs: str) -> str | None:
    """Merge two edits of the same todo.txt task that touch different fields,
    or return None if they changed the same field differently.

    Words of the description are merged like lines (so one side adding
    ``+project`` and the other ``due:...`` keeps both). Blank lines (a removed
    task) and lines that would not be written back exactly as they are never
    merge."""
    lines = (base, ours, theirs)
    if any(not line.strip() for line in lines):
        return None
    tasks = [parse_task(line) for line in lines]
    if any(format_task(t) != line for t, line in zip(tasks, lines)):
        return None
    b, o, t = (_fields(task) for task in tasks)
    done, completed, priority, created = (_field(*f) for f in zip(b[:4], o[:4], t[:4]))
    # Words both sides appended (tags, usually) are all kept; two different
    # words put in the same place mid-sentence are a conflict.
    words = merge3(b[4], o[4], t[4], insert_both_at_end_only=True)
    if _NO_MERGE in (done, completed, priority, created) or not words.clean:
        return None
    task = Task(" ".join(words.lines), done, None, None, created)
    if done:
        task.completion_date = completed
        if priority:
            task.set_tag("pri", priority)
    else:
        task.priority = priority
    return format_task(task)


def _merge_task_bytes(base: bytes, ours: bytes, theirs: bytes) -> bytes | None:
    ending = _ending(ours)
    try:
        texts = [line[: len(line) - len(_ending(line))].decode("utf-8") for line in (base, ours, theirs)]
    except UnicodeDecodeError:
        return None
    merged = merge_task_line(*texts)
    return None if merged is None else merged.encode("utf-8") + ending


# -- whole files -------------------------------------------------------------
def _split(data: bytes) -> tuple[bool, list[bytes]]:
    bom = data.startswith(codecs.BOM_UTF8)
    if bom:
        data = data[len(codecs.BOM_UTF8):]
    return bom, data.splitlines(keepends=True)


def _ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith((b"\n", b"\r")):
        return line[-1:]
    return b""


def _pick(base, ours, theirs):
    """A whole-file property: ours if tasklane changed it, else theirs."""
    return ours if ours != base else theirs


def merge_bytes(base: bytes, ours: bytes, theirs: bytes) -> MergeResult:
    """Merge three versions of a file; ``result.lines`` joined is the new file
    (prefixed with a BOM by :func:`join_merged`). Line endings travel with
    their lines, and a BOM or a missing final newline is treated as a property
    of the whole file."""
    versions = [_split(v) for v in (base, ours, theirs)]
    newline = next(
        (_ending(line) for _, lines in versions for line in lines if _ending(line)),
        b"\n",
    )
    unterminated = []
    for _, lines in versions:
        open_end = bool(lines) and not _ending(lines[-1])
        unterminated.append(open_end)
        if open_end:
            lines[-1] += newline
    result = merge3(versions[0][1], versions[1][1], versions[2][1], _merge_task_bytes)
    if result.lines and _pick(*unterminated):
        last = result.lines[-1]
        result.lines[-1] = last[: len(last) - len(_ending(last))]
    result.bom = _pick(*(bom for bom, _ in versions))
    return result


def join_merged(result: MergeResult) -> bytes:
    data = b"".join(result.lines)
    return (codecs.BOM_UTF8 + data) if result.bom else data
