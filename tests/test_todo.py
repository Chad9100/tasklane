from datetime import date

import pytest

from tasklane.todo import Task, format_task, parse_date, parse_task, split_tag


def test_plain_task():
    t = parse_task("Call mom")
    assert (t.text, t.done, t.priority, t.creation_date) == ("Call mom", False, None, None)


def test_priority_and_creation_date():
    t = parse_task("(A) 2026-11-01 Call mom +family @phone")
    assert t.priority == "A"
    assert t.creation_date == date(2026, 11, 1)
    assert t.text == "Call mom +family @phone"


@pytest.mark.parametrize("line", ["Call (A) mom", "(a) lower case", "(A)no space", " (A) leading space", "(AB) two"])
def test_priority_only_at_start_and_well_formed(line):
    assert parse_task(line).priority is None
    assert parse_task(line).text == line


def test_completion_with_both_dates():
    t = parse_task("x 2026-11-09 2026-11-01 Pay rent +home")
    assert t.done
    assert t.completion_date == date(2026, 11, 9)
    assert t.creation_date == date(2026, 11, 1)
    assert t.text == "Pay rent +home"


def test_completion_with_single_date_is_completion_date():
    t = parse_task("x 2026-11-09 Pay rent")
    assert t.completion_date == date(2026, 11, 9)
    assert t.creation_date is None


def test_completion_without_dates():
    t = parse_task("x Pay rent")
    assert t.done and t.completion_date is None and t.text == "Pay rent"


@pytest.mark.parametrize("line", ["X 2026-11-09 shouting", "xylophone lessons", "x"])
def test_not_completed(line):
    assert not parse_task(line).done


def test_completed_task_has_no_prefix_priority():
    t = parse_task("x 2026-11-09 (A) leftover")
    assert t.priority is None
    assert t.text == "(A) leftover"


def test_invalid_date_stays_in_text():
    t = parse_task("2026-13-45 not a date")
    assert t.creation_date is None
    assert t.text == "2026-13-45 not a date"


def test_projects_and_contexts():
    t = parse_task("Plan +Garden trip @home +garden @home +Garden")
    assert t.projects == ["Garden", "garden"]
    assert t.contexts == ["home"]


@pytest.mark.parametrize("line", ["Learn C++ and a+b", "mail bob@example.com", "lone + and @ signs"])
def test_plus_and_at_inside_words_are_not_projects(line):
    t = parse_task(line)
    assert t.projects == [] and t.contexts == []


def test_tags_first_occurrence_wins():
    t = parse_task("Pay due:2026-11-20 est:30m due:2027-01-01")
    assert t.tags == {"due": "2026-11-20", "est": "30m"}
    assert t.due == date(2026, 11, 20)


@pytest.mark.parametrize(
    "word",
    ["https://example.com/a", "http://host:8080/x", "a:b:c", ":empty", "empty:", "+proj:x", "@ctx:y"],
)
def test_not_tags(word):
    assert split_tag(word) is None


def test_url_in_task_is_not_a_tag():
    t = parse_task("Read https://example.com/post?id=1 due:2026-11-20")
    assert t.tags == {"due": "2026-11-20"}


def test_invalid_due_date_is_none():
    assert parse_task("Fix due:tomorrow").due is None
    assert parse_task("Fix due:2026-02-30").due is None


def test_parse_date_rejects_loose_formats():
    assert parse_date("2026-11-09") == date(2026, 11, 9)
    assert parse_date("2026-1-9") is None
    assert parse_date(None) is None


@pytest.mark.parametrize(
    "line",
    [
        "Call mom",
        "(A) Call mom",
        "(B) 2026-11-01 Call mom +family @phone due:2026-11-20",
        "2026-11-01 just a date",
        "x 2026-11-09 2026-11-01 done thing pri:A",
        "x 2026-11-09 done without creation",
        "x done without any date",
        "Read https://example.com:8080/x key:value",
        "Unicode café ✓ +naïve",
        "(Z) last priority",
    ],
)
def test_round_trip(line):
    assert format_task(parse_task(line)) == line


def test_set_tag_replaces_in_place_and_appends():
    t = parse_task("Pay due:2026-11-20 +home")
    t.set_tag("due", "2026-12-20")
    assert t.text == "Pay due:2026-12-20 +home"
    t.set_tag("rec", "1m")
    assert t.text == "Pay due:2026-12-20 +home rec:1m"


def test_complete_moves_priority_to_tag_and_undo_restores():
    t = parse_task("(A) 2026-11-01 Ship it")
    t.complete(date(2026, 11, 9))
    assert format_task(t) == "x 2026-11-09 2026-11-01 Ship it pri:A"
    t.uncomplete()
    assert format_task(t) == "(A) 2026-11-01 Ship it"


def test_task_copy_is_independent():
    t = Task(text="a")
    c = t.copy()
    c.text = "b"
    assert t.text == "a"


def test_threshold_date_and_deferred():
    task = parse_task("2026-11-01 Renew passport t:2026-12-01 due:2027-01-15")
    assert task.threshold == date(2026, 12, 1)
    assert task.deferred(date(2026, 11, 30))
    assert not task.deferred(date(2026, 12, 1))  # visible from the threshold day on
    assert not parse_task("x 2026-11-02 Done t:2099-01-01").deferred(date(2026, 11, 9))
    assert parse_task("Bad t:2026-13-01").threshold is None
    assert parse_task("Bad t:soon").threshold is None
