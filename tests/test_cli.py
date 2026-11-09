import json
from datetime import date
from pathlib import Path

import pytest

from tasklane.cli import main, resolve_path, use_color

# Kept in step with conftest.py. Defined here rather than imported from it:
# conftest isn't an importable module when pytest runs as plain `pytest`
# (as CI does), only with `python -m pytest` from the project folder.
TODAY = date(2026, 11, 9)


def write(path: Path, text: str, newline: str = "\n") -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))

SAMPLE = """(B) 2026-11-01 Write report +work @desk due:2026-11-12
2026-11-02 Buy milk +home @shop
(A) 2026-11-03 Fix roof +home due:2026-11-20
x 2026-11-08 2026-11-01 Old thing +work
2026-11-04 Pay rent +home due:2026-11-05
"""


@pytest.fixture
def sample(todo):
    write(todo, SAMPLE)
    return todo


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_add_sets_creation_date_and_keeps_markup(run, todo):
    code, out, _ = run("add", "(A)", "Call mom +family @phone due:2026-11-20 https://x.org")
    assert code == 0
    assert out == "Added 1: (A) 2026-11-09 Call mom +family @phone due:2026-11-20 https://x.org\n"
    assert lines(todo) == ["(A) 2026-11-09 Call mom +family @phone due:2026-11-20 https://x.org"]


def test_add_keeps_explicit_creation_date(run, todo):
    run("add", "2026-10-01 Backdated")
    assert lines(todo) == ["2026-10-01 Backdated"]


def test_add_empty_text_fails(run, todo):
    code, _, err = run("add", "(A)", "")
    assert code == 1 and "nothing to add" in err
    assert not todo.exists()


def test_ls_sorted_with_stable_numbers(run, sample):
    code, out, _ = run("ls")
    assert code == 0
    assert out.splitlines() == [
        "3 (A) 2026-11-03 Fix roof +home due:2026-11-20",
        "1 (B) 2026-11-01 Write report +work @desk due:2026-11-12",
        "5 2026-11-04 Pay rent +home due:2026-11-05",
        "2 2026-11-02 Buy milk +home @shop",
        "--",
        "4 of 4 tasks shown",
    ]


def test_ls_filters_and_all(run, sample):
    _, out, _ = run("ls", "+home", "-milk")
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["3", "5"]
    _, out, _ = run("ls", "--all", "+work")
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["1", "4"]


def test_ls_json_shape(run, sample):
    _, out, _ = run("ls", "--json", "@desk")
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["line"] == 1
    assert data[0]["priority"] == "B"
    assert data[0]["projects"] == ["work"] and data[0]["contexts"] == ["desk"]
    assert data[0]["due"] == "2026-11-12"
    assert set(data[0]) == {"line", "raw", "done", "priority", "completion_date", "creation_date",
                            "text", "projects", "contexts", "tags", "due", "threshold"}


def test_do_marks_done_and_keeps_line_numbers(run, sample):
    code, out, _ = run("do", "1", "2")
    assert code == 0
    assert "Completed 1: x 2026-11-09 2026-11-01 Write report +work @desk due:2026-11-12 pri:B" in out
    content = lines(sample)
    assert content[1] == "x 2026-11-09 2026-11-02 Buy milk +home @shop"
    assert len(content) == 5
    _, out, _ = run("ls")
    assert out.splitlines()[0].startswith("3 (A)")


def test_do_already_done_is_reported(run, sample):
    code, out, _ = run("do", "4")
    assert code == 0 and "already done" in out


@pytest.mark.parametrize("args", [["do", "99"], ["do", "0"], ["do", "1", "99"], ["undo", "7"], ["pri", "42", "A"],
                                  ["edit", "9", "x"], ["rm", "9", "--yes"]])
def test_bad_index_exits_1_without_changes(run, sample, args):
    before = sample.read_bytes()
    code, out, err = run(*args)
    assert code == 1
    assert "tasklane: error: no task" in err
    assert sample.read_bytes() == before


def test_non_numeric_index_is_usage_error(run, sample):
    with pytest.raises(SystemExit) as exc:
        run("do", "one")
    assert exc.value.code == 2


def test_do_recurring_creates_next_occurrence(run, todo):
    write(todo, "(A) 2026-11-01 Pay rent +home due:2026-11-01 rec:+1m\n2026-11-01 Water plants due:2026-11-05 rec:3d\n")
    code, out, _ = run("do", "1", "2")
    assert code == 0
    assert lines(todo) == [
        "x 2026-11-09 2026-11-01 Pay rent +home due:2026-11-01 rec:+1m pri:A",
        "x 2026-11-09 2026-11-01 Water plants due:2026-11-05 rec:3d",
        "(A) 2026-11-09 Pay rent +home due:2026-12-01 rec:+1m",
        "2026-11-09 Water plants due:2026-11-12 rec:3d",
    ]
    assert "Recurring: added 3:" in out


def test_do_recurring_month_end_clamp(run, todo):
    write(todo, "Invoice due:2027-01-31 rec:+1m\n")
    run("do", "1", today=date(2027, 2, 2))
    assert lines(todo)[1] == "Invoice due:2027-02-28 rec:+1m"


def test_do_with_invalid_rec_warns_but_completes(run, todo):
    write(todo, "Odd rec:sometimes\n")
    code, _, err = run("do", "1")
    assert code == 0 and "warning" in err
    assert lines(todo) == ["x 2026-11-09 Odd rec:sometimes"]


def test_undo_restores_priority(run, sample):
    run("do", "3")
    code, out, _ = run("undo", "3")
    assert code == 0
    assert lines(sample)[2] == "(A) 2026-11-03 Fix roof +home due:2026-11-20"


def test_undo_open_task_fails(run, sample):
    code, _, err = run("undo", "1")
    assert code == 1 and "not done" in err


def test_pri_and_depri(run, sample):
    assert run("pri", "2", "c")[0] == 0
    assert lines(sample)[1] == "(C) 2026-11-02 Buy milk +home @shop"
    assert run("depri", "2")[0] == 0
    assert lines(sample)[1] == "2026-11-02 Buy milk +home @shop"


@pytest.mark.parametrize("letter", ["AA", "1", "?"])
def test_pri_rejects_bad_letters(run, sample, letter):
    code, _, err = run("pri", "1", letter)
    assert code == 1 and "single letter" in err


def test_pri_on_done_task_fails(run, sample):
    assert run("pri", "4", "A")[0] == 1


def test_edit_keeps_priority_and_creation_date(run, sample):
    code, out, _ = run("edit", "3", "Fix roof and gutters +home due:2026-11-25")
    assert code == 0
    assert lines(sample)[2] == "(A) 2026-11-03 Fix roof and gutters +home due:2026-11-25"


def test_rm_requires_yes_and_blanks_line(run, sample):
    code, _, err = run("rm", "2")
    assert code == 1 and "--yes" in err
    assert len(lines(sample)) == 5 and "Buy milk" in lines(sample)[1]
    code, out, _ = run("rm", "2", "--yes")
    assert code == 0 and out.startswith("Removed 2:")
    assert lines(sample)[1] == ""
    _, out, _ = run("ls", "+home")
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["3", "5"]


def test_archive_moves_done_and_renumbers(run, sample, tmp_path):
    done = tmp_path / "done.txt"
    write(done, "x 2026-10-01 ancient\n", newline="\r\n")
    run("do", "1")
    run("rm", "2", "--yes")
    code, out, _ = run("archive")
    assert code == 0 and "Archived 2 task(s)" in out
    assert lines(sample) == [
        "(A) 2026-11-03 Fix roof +home due:2026-11-20",
        "2026-11-04 Pay rent +home due:2026-11-05",
    ]
    assert done.read_bytes() == (
        b"x 2026-10-01 ancient\r\n"
        b"x 2026-11-09 2026-11-01 Write report +work @desk due:2026-11-12 pri:B\r\n"
        b"x 2026-11-08 2026-11-01 Old thing +work\r\n"
    )
    assert run("archive")[1] == "Nothing to archive.\n"


def test_due_default_and_days(run, sample):
    _, out, _ = run("due")
    assert out.splitlines() == [
        "5 2026-11-04 Pay rent +home due:2026-11-05  [overdue 4d]",
        "1 (B) 2026-11-01 Write report +work @desk due:2026-11-12  [due in 3d]",
    ]
    _, out, _ = run("due", "--days", "11")
    assert len(out.splitlines()) == 3
    _, out, _ = run("due", today=date(2026, 1, 1), )
    assert out.startswith("Nothing overdue")


def test_due_json_shape(run, sample):
    _, out, _ = run("due", "--json")
    data = json.loads(out)
    assert [(d["line"], d["days_left"], d["overdue"]) for d in data] == [(5, -4, True), (1, 3, False)]


def test_due_negative_days_fails(run, sample):
    assert run("due", "--days", "-1")[0] == 1


def test_projects_and_contexts(run, sample):
    assert run("projects")[1] == "+home\n+work\n"
    assert run("contexts")[1] == "@desk\n@shop\n"
    assert json.loads(run("projects", "--json")[1]) == ["home", "work"]


def test_report_counts_include_done_txt(run, sample, tmp_path):
    write(tmp_path / "done.txt", "x 2026-10-01 Shed +home\nx 2026-10-02 No project\n")
    _, out, _ = run("report")
    assert out.splitlines() == [
        "PROJECT   OPEN   DONE",
        "+home        3      1",
        "+work        1      1",
        "(none)       0      1",
        "TOTAL        4      3",
    ]
    data = json.loads(run("report", "--json")[1])
    assert data["total"] == {"open": 4, "done": 3}
    assert data["projects"][0] == {"project": "home", "open": 3, "done": 1}


def test_tasklane_file_env(tmp_path, monkeypatch, capsys):
    path = tmp_path / "env-todo.txt"
    monkeypatch.setenv("TASKLANE_FILE", str(path))
    assert main(["add", "via env"], today=TODAY) == 0
    assert path.read_text(encoding="utf-8") == "2026-11-09 via env\n"


def test_default_path_is_home(isolated_home):
    assert resolve_path(None, {}) == isolated_home / "todo.txt"
    assert resolve_path("x.txt", {"TASKLANE_FILE": "y.txt"}).name == "x.txt"


def test_file_option_after_command(capsys, tmp_path):
    path = tmp_path / "late.txt"
    assert main(["add", "late flag", "--file", str(path)], today=TODAY) == 0
    assert path.exists()


def test_color_always_and_never(run, sample):
    _, out, _ = run("--color", "always", "ls")
    assert "\033[1;31m" in out and "\033[0m" in out
    _, out, _ = run("--color", "never", "ls")
    assert "\033[" not in out
    _, out, _ = run("ls")  # captured stdout is not a TTY
    assert "\033[" not in out


def test_use_color_respects_no_color():
    class Tty:
        def isatty(self):
            return True

    assert use_color("auto", Tty(), {}) is True
    assert use_color("auto", Tty(), {"NO_COLOR": "1"}) is False
    assert use_color("always", Tty(), {"NO_COLOR": "1"}) is True


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "usage: tasklane" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_unknown_lines_survive_commands(run, todo):
    data = b"\xef\xbb\xbf(A) first\r\n\r\nweird \xff bytes  here\r\n2026-11-01 second\r\n"
    todo.write_bytes(data)
    run("do", "4")
    assert todo.read_bytes() == (
        b"\xef\xbb\xbf(A) first\r\n\r\nweird \xff bytes  here\r\nx 2026-11-09 2026-11-01 second\r\n"
    )
    _, out, _ = run("ls")
    assert out.splitlines()[0] == "1 (A) first"


def test_ls_exclusion_terms_in_any_position(run, sample):
    _, out, _ = run("ls", "-milk", "+home", "-roof")
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["5"]


def test_ls_unknown_long_option_is_usage_error(run, sample):
    with pytest.raises(SystemExit) as exc:
        run("ls", "--bogus")
    assert exc.value.code == 2


def test_ls_double_dash_allows_option_like_terms(run, todo):
    write(todo, "a -h b\nc\n")
    _, out, _ = run("ls", "--", "-h")
    assert out.splitlines()[0] == "2 c"


THRESHOLD_SAMPLE = """2026-11-01 Book flights +trip t:2026-11-20
(A) 2026-11-01 File taxes due:2026-11-15
2026-11-02 Renew passport +trip t:2026-11-09
x 2026-11-05 2026-11-01 Pack bags +trip
2026-11-03 Unknown-ish line t:not-a-date
"""


def test_ls_hides_future_threshold_and_says_so(run, todo):
    write(todo, THRESHOLD_SAMPLE)
    code, out, _ = run("ls")
    assert code == 0
    assert out.splitlines() == [
        "2 (A) 2026-11-01 File taxes due:2026-11-15",
        "3 2026-11-02 Renew passport +trip t:2026-11-09",
        "5 2026-11-03 Unknown-ish line t:not-a-date",
        "--",
        "3 of 4 tasks shown (1 hidden until their t: date; --all shows them)",
    ]


def test_ls_threshold_hint_respects_filters(run, todo):
    write(todo, THRESHOLD_SAMPLE)
    _, out, _ = run("ls", "taxes")
    assert out.splitlines()[-1] == "1 of 4 tasks shown"


def test_ls_all_shows_deferred_and_task_appears_on_its_day(run, todo):
    write(todo, THRESHOLD_SAMPLE)
    _, out, _ = run("ls", "--all", "+trip")
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["1", "3", "4"]
    _, out, _ = run("ls", "+trip", today=date(2026, 11, 20))
    assert [l.split()[0] for l in out.splitlines()[:-2]] == ["1", "3"]
    assert out.splitlines()[-1] == "2 of 4 tasks shown"


def test_ls_json_threshold_and_file_untouched(run, todo):
    write(todo, THRESHOLD_SAMPLE)
    _, out, _ = run("ls", "--json", "--all", "flights")
    assert json.loads(out)[0]["threshold"] == "2026-11-20"
    _, out, _ = run("ls", "--json")
    assert [row["line"] for row in json.loads(out)] == [2, 3, 5]
    assert todo.read_text(encoding="utf-8") == THRESHOLD_SAMPLE
