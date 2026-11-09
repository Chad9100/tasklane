"""Recurring tasks: ``rec:3d``, ``rec:1w``, ``rec:1m``, ``rec:1y`` and strict ``rec:+1w``.

Normal recurrence schedules the next occurrence relative to the day the task
was completed; strict recurrence (leading ``+``) schedules it relative to the
task's current due date, so a late completion does not shift the schedule.
Month and year steps clamp to the end of the target month (Jan 31 + 1m is
Feb 28 or 29).

A valid ``t:`` threshold date moves with the due date: the next occurrence
keeps the same number of days between ``t:`` and ``due:``.  Without a valid
due date the gap is taken as zero, so ``t:`` lands on the new due date.
An unreadable ``t:`` value is copied unchanged.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .todo import Task

_RULE = re.compile(r"(\+?)([1-9][0-9]{0,3})([dwmy])", re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    strict: bool
    count: int
    unit: str  # one of d, w, m, y


def parse_rule(value: str) -> Rule:
    match = _RULE.fullmatch(value)
    if not match:
        raise ValueError(f"invalid recurrence rec:{value} (expected e.g. 3d, 1w, 1m, 1y, +1w)")
    return Rule(match.group(1) == "+", int(match.group(2)), match.group(3).lower())


def add_months(day: date, months: int) -> date:
    year, month0 = divmod(day.month - 1 + months, 12)
    year += day.year
    month = month0 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def advance(day: date, rule: Rule) -> date:
    try:
        if rule.unit == "d":
            return day + timedelta(days=rule.count)
        if rule.unit == "w":
            return day + timedelta(weeks=rule.count)
        if rule.unit == "m":
            return add_months(day, rule.count)
        return add_months(day, 12 * rule.count)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"recurrence moves the date out of range: {exc}") from None


def next_task(task: Task, today: date) -> Task | None:
    """Return the next occurrence of an open recurring *task*, or ``None``.

    Raises ``ValueError`` if the ``rec:`` value is malformed.
    """
    value = task.tags.get("rec")
    if value is None:
        return None
    rule = parse_rule(value)
    base = task.due if (rule.strict and task.due) else today
    new = Task(
        text=task.text,
        priority=task.priority,
        creation_date=today if task.creation_date else None,
    )
    new_due = advance(base, rule)
    new.set_tag("due", new_due.isoformat())
    start = task.threshold
    if start is not None:
        gap = (task.due - start) if task.due else timedelta(0)
        try:
            new_start = new_due - gap
        except OverflowError:
            raise ValueError("recurrence moves the t: date out of range") from None
        new.set_tag("t", new_start.isoformat())
    return new
