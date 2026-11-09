"""Filtering, sorting and summarising tasks."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from .todo import Task, format_task

Item = tuple[int, Task]

_NO_PRIORITY = "~"  # sorts after "Z"


def _term_matches(task: Task, term: str) -> bool:
    folded = term.casefold()
    if term.startswith("+") and len(term) > 1:
        return folded[1:] in (p.casefold() for p in task.projects)
    if term.startswith("@") and len(term) > 1:
        return folded[1:] in (c.casefold() for c in task.contexts)
    return folded in format_task(task).casefold()


def matches(task: Task, terms: Iterable[str]) -> bool:
    """All terms must match (AND). ``-term`` excludes; ``+p``/``@c`` match exactly."""
    for term in terms:
        if term.startswith("-") and len(term) > 1:
            if _term_matches(task, term[1:]):
                return False
        elif term and not _term_matches(task, term):
            return False
    return True


def sort_key(item: Item) -> tuple:
    n, task = item
    return (task.done, task.priority or _NO_PRIORITY, task.due or date.max, n)


def filter_tasks(items: Iterable[Item], terms: Sequence[str] = (), include_done: bool = False) -> list[Item]:
    chosen = [(n, t) for n, t in items if (include_done or not t.done) and matches(t, terms)]
    return sorted(chosen, key=sort_key)


def due_soon(items: Iterable[Item], today: date, days: int = 7) -> list[Item]:
    """Open tasks that are overdue or due within *days* days, earliest first."""
    limit = today + timedelta(days=days)
    chosen = [(n, t) for n, t in items if not t.done and t.due is not None and t.due <= limit]
    return sorted(chosen, key=lambda it: (it[1].due, it[1].priority or _NO_PRIORITY, it[0]))


def collect(tasks: Iterable[Task], attr: str) -> list[str]:
    names: set[str] = set()
    for task in tasks:
        names.update(getattr(task, attr))
    return sorted(names, key=lambda s: (s.casefold(), s))


NO_PROJECT = "(none)"


def report(open_tasks: Iterable[Task], done_tasks: Iterable[Task]) -> dict:
    """Open/done counts per project. A task with several projects counts in each."""
    rows: dict[str, dict[str, int]] = {}
    totals = {"open": 0, "done": 0}
    for key, tasks in (("open", open_tasks), ("done", done_tasks)):
        for task in tasks:
            totals[key] += 1
            for project in task.projects or [NO_PROJECT]:
                rows.setdefault(project, {"open": 0, "done": 0})[key] += 1
    ordered = sorted(rows, key=lambda p: (p == NO_PROJECT, p.casefold(), p))
    return {
        "projects": [{"project": p, **rows[p]} for p in ordered],
        "total": totals,
    }


def task_to_dict(n: int, task: Task, raw: str | None = None) -> dict:
    return {
        "line": n,
        "raw": raw if raw is not None else format_task(task),
        "done": task.done,
        "priority": task.priority,
        "completion_date": task.completion_date.isoformat() if task.completion_date else None,
        "creation_date": task.creation_date.isoformat() if task.creation_date else None,
        "text": task.text,
        "projects": task.projects,
        "contexts": task.contexts,
        "tags": task.tags,
        "due": task.due.isoformat() if task.due else None,
    }
