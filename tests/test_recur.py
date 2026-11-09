from datetime import date

import pytest

from tasklane.recur import Rule, add_months, advance, next_task, parse_rule
from tasklane.todo import format_task, parse_task

TODAY = date(2026, 11, 9)


@pytest.mark.parametrize(
    "value,rule",
    [("3d", Rule(False, 3, "d")), ("1w", Rule(False, 1, "w")), ("+1m", Rule(True, 1, "m")), ("2Y", Rule(False, 2, "y"))],
)
def test_parse_rule(value, rule):
    assert parse_rule(value) == rule


@pytest.mark.parametrize("value", ["", "w", "0d", "1x", "-1d", "++1w", "1.5d"])
def test_parse_rule_rejects(value):
    with pytest.raises(ValueError):
        parse_rule(value)


@pytest.mark.parametrize(
    "start,months,expected",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
    ],
)
def test_add_months_clamps_to_month_end(start, months, expected):
    assert add_months(start, months) == expected


def test_yearly_from_leap_day_clamps():
    assert advance(date(2028, 2, 29), Rule(False, 1, "y")) == date(2029, 2, 28)


def test_normal_recurrence_counts_from_today():
    t = parse_task("2026-11-01 Water plants due:2026-11-05 rec:1w")
    assert next_task(t, TODAY).due == date(2026, 11, 16)


def test_strict_recurrence_counts_from_due_date():
    t = parse_task("2026-11-01 Pay rent due:2026-11-01 rec:+1m")
    assert next_task(t, TODAY).due == date(2026, 12, 1)


def test_strict_month_end_clamp():
    t = parse_task("Invoice due:2027-01-31 rec:+1m")
    assert next_task(t, TODAY).due == date(2027, 2, 28)


def test_strict_without_due_falls_back_to_today():
    t = parse_task("Stretch rec:+3d")
    assert next_task(t, TODAY).due == date(2026, 11, 12)


def test_next_task_keeps_text_priority_and_tags():
    t = parse_task("(B) 2026-11-01 Review +work @desk due:2026-11-08 rec:1w est:1h")
    new = next_task(t, TODAY)
    assert format_task(new) == "(B) 2026-11-09 Review +work @desk due:2026-11-16 rec:1w est:1h"
    assert not new.done


def test_no_rec_tag_gives_none():
    assert next_task(parse_task("One-off due:2026-11-20"), TODAY) is None


def test_invalid_rec_raises():
    with pytest.raises(ValueError):
        next_task(parse_task("Bad rec:often"), TODAY)
