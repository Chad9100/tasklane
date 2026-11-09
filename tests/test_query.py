from datetime import date

from tasklane import query
from tasklane.todo import parse_task

TODAY = date(2026, 11, 9)

LINES = [
    "(B) Write report +work @desk due:2026-11-12",   # 1
    "Buy milk +home @shop",                          # 2
    "(A) Fix roof +home due:2026-11-20",             # 3
    "x 2026-11-08 Old thing +work",                  # 4
    "(B) Email Bob +work @desk",                     # 5
    "Pay rent +home due:2026-11-05",                 # 6
    "Call dentist due:2026-12-30",                   # 7
]


def items():
    return [(i, parse_task(line)) for i, line in enumerate(LINES, 1)]


def numbers(result):
    return [n for n, _ in result]


def test_sort_priority_then_due_then_line():
    assert numbers(query.filter_tasks(items())) == [3, 1, 5, 6, 7, 2]


def test_project_filter_is_exact_and_case_insensitive():
    assert numbers(query.filter_tasks(items(), ["+HOME"])) == [3, 6, 2]
    assert numbers(query.filter_tasks(items(), ["+hom"])) == []


def test_context_filter():
    assert numbers(query.filter_tasks(items(), ["@desk"])) == [1, 5]


def test_terms_are_anded():
    assert numbers(query.filter_tasks(items(), ["+work", "email"])) == [5]


def test_exclude_word_and_project():
    assert numbers(query.filter_tasks(items(), ["+home", "-roof"])) == [6, 2]
    assert numbers(query.filter_tasks(items(), ["-+home", "-@desk"])) == [7]


def test_done_hidden_unless_requested_and_sorted_last():
    assert 4 not in numbers(query.filter_tasks(items()))
    assert numbers(query.filter_tasks(items(), ["+work"], include_done=True)) == [1, 5, 4]


def test_due_soon_includes_overdue_and_window():
    assert numbers(query.due_soon(items(), TODAY, 7)) == [6, 1]
    assert numbers(query.due_soon(items(), TODAY, 11)) == [6, 1, 3]
    assert numbers(query.due_soon(items(), TODAY, 0)) == [6]


def test_collect_projects_and_contexts():
    tasks = [t for _, t in items()]
    assert query.collect(tasks, "projects") == ["home", "work"]
    assert query.collect(tasks, "contexts") == ["desk", "shop"]


def test_report_counts_per_project():
    tasks = [t for _, t in items()]
    data = query.report([t for t in tasks if not t.done], [t for t in tasks if t.done])
    assert data["projects"] == [
        {"project": "home", "open": 3, "done": 0},
        {"project": "work", "open": 2, "done": 1},
        {"project": "(none)", "open": 1, "done": 0},
    ]
    assert data["total"] == {"open": 6, "done": 1}


def test_task_to_dict_shape():
    d = query.task_to_dict(3, parse_task("(A) 2026-11-01 Fix roof +home @out due:2026-11-20"))
    assert d == {
        "line": 3,
        "raw": "(A) 2026-11-01 Fix roof +home @out due:2026-11-20",
        "done": False,
        "priority": "A",
        "completion_date": None,
        "creation_date": "2026-11-01",
        "text": "Fix roof +home @out due:2026-11-20",
        "projects": ["home"],
        "contexts": ["out"],
        "tags": {"due": "2026-11-20"},
        "due": "2026-11-20",
        "threshold": None,
    }


def test_threshold_hides_future_tasks_only_when_today_given():
    rows = [
        (1, parse_task("Later +home t:2026-11-10")),
        (2, parse_task("Today +home t:2026-11-09")),
        (3, parse_task("Past +home t:2026-11-01")),
        (4, parse_task("Broken +home t:someday")),
    ]
    assert numbers(query.filter_tasks(rows, today=TODAY)) == [2, 3, 4]
    assert numbers(query.filter_tasks(rows, include_done=True, today=TODAY)) == [1, 2, 3, 4]
    assert numbers(query.filter_tasks(rows)) == [1, 2, 3, 4]


def test_task_to_dict_has_threshold():
    task = parse_task("Later t:2026-12-01")
    assert query.task_to_dict(1, task)["threshold"] == "2026-12-01"
    assert query.task_to_dict(1, parse_task("Now"))["threshold"] is None
