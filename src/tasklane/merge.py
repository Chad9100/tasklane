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
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Sequence


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


def merge3(base: Sequence, ours: Sequence, theirs: Sequence) -> MergeResult:
    """Merge two edited copies of *base*, line by line."""
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
        elif start == end:  # both only inserted lines here
            keep_ours(ours_v)
            result.lines.extend(theirs_v)
        else:
            result.conflicts.append(
                Conflict(start, end, list(base[start:end]), ours_v, theirs_v)
            )
            keep_ours(ours_v)  # placeholder so ours_at stays complete
        pos = end
    keep_ours(list(base[pos:]))
    return result


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
    result = merge3(versions[0][1], versions[1][1], versions[2][1])
    if result.lines and _pick(*unterminated):
        last = result.lines[-1]
        result.lines[-1] = last[: len(last) - len(_ending(last))]
    result.bom = _pick(*(bom for bom, _ in versions))
    return result


def join_merged(result: MergeResult) -> bytes:
    data = b"".join(result.lines)
    return (codecs.BOM_UTF8 + data) if result.bom else data
