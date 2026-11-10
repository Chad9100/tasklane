from datetime import date

import pytest

from tasklane import tui
from tasklane.cli import main
from tasklane.todo import parse_task

TODAY = date(2026, 11, 10)
LINES = ["(A) call mom +family", "buy milk @store", "x 2026-11-01 old thing", "write report +work"]


def make_view():
    items = [(i + 1, parse_task(t)) for i, t in enumerate(LINES)]
    return tui.View(items, {n: LINES[n - 1] for n, _ in items}, TODAY)


class FakeScreen:
    def __init__(self, keys, size=(10, 50)):
        self.keys, self.size, self.frames, self.rows = list(keys), size, [], {}

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.rows = {}

    def addnstr(self, y, x, text, n):
        self.rows[y] = text[:n]

    def refresh(self):
        self.frames.append(dict(self.rows))

    def getch(self):
        return self.keys.pop(0)


def keys(text):
    return [ord(c) for c in text]


def test_lists_open_tasks_sorted_with_selection():
    screen = FakeScreen(keys("q"))
    tui.run(screen, make_view())
    frame = screen.frames[0]
    assert frame[0].startswith("tasklane  3 open task(s)")
    assert frame[1] == ">1 (A) call mom +family"
    assert frame[2] == " 2 buy milk @store"
    assert frame[3] == " 4 write report +work"
    assert "old thing" not in " ".join(frame.values())
    assert frame[9].startswith("j/k move")


def test_move_and_show_all():
    view = make_view()
    for key in keys("jj"):
        view.handle(key)
    assert view.selected == 2
    view.handle(ord("j"))
    assert view.selected == 2  # clamped
    view.handle(ord("a"))
    assert len(view.visible()) == 4
    view.handle(ord("g"))
    assert view.selected == 0


def test_live_filter_and_escape():
    view = make_view()
    for key in keys("/+work"):
        assert view.handle(key)
    assert view.editing
    assert [n for n, _ in view.visible()] == [4]
    view.handle(10)
    assert not view.editing and view.filter == "+work"
    view.handle(tui.ESC)  # first Esc clears the filter, does not quit
    assert view.filter == "" and len(view.visible()) == 3
    assert view.handle(tui.ESC) is False


def test_backspace_and_selection_stays_in_range():
    view = make_view()
    view.handle(ord("G"))
    assert view.selected == 2
    for key in keys("/milk"):
        view.handle(key)
    assert view.selected == 0
    view.handle(tui.KEY_BACKSPACE)
    assert view.filter == "mil"


def test_scrolls_in_small_window_and_truncates():
    screen = FakeScreen([], size=(5, 22))
    view = make_view()
    view.handle(ord("G"))
    view.draw(screen)
    frame = screen.frames[-1]
    assert view.top == 0  # three rows fit in a 5-line window
    assert frame[3].startswith(">")
    assert all(len(text) <= 21 for text in frame.values())
    view.selected = 0
    view.draw(screen)
    assert view.top == 0


def test_too_small_terminal():
    screen = FakeScreen([], size=(2, 10))
    make_view().draw(screen)
    assert screen.frames[-1] == {0: "Terminal "}


def make_store_view(tmp_path, lines=None):
    todo = tmp_path / "todo.txt"
    todo.write_text("\n".join(lines or LINES) + "\n", encoding="utf-8")
    store = tui.TaskStore(todo, TODAY)
    items, raws = store.load()
    return todo, tui.View(items, raws, TODAY, store)


def press(view, text):
    for key in keys(text):
        view.handle(key)


def test_done_key_saves_and_reloads(tmp_path):
    todo, view = make_store_view(tmp_path)
    press(view, "jx")  # selects "buy milk"
    assert todo.read_text(encoding="utf-8").splitlines()[1] == "x 2026-11-10 buy milk @store"
    assert view.message == "Completed 2"
    assert [n for n, _ in view.visible()] == [1, 4]
    screen = FakeScreen([])
    view.draw(screen)
    assert screen.frames[-1][9] == "Completed 2"
    view.handle(ord("j"))
    assert view.message == ""


def test_undo_key_reopens_in_all_view(tmp_path):
    todo, view = make_store_view(tmp_path)
    press(view, "a")
    press(view, "jjj")  # the done line is row 3 in sorted order
    assert view.visible()[view.selected][1].done
    press(view, "u")
    assert todo.read_text(encoding="utf-8").splitlines()[2] == "old thing"
    press(view, "u")
    assert "is not done" in view.message  # the selection now sits on another task


def test_priority_prompt(tmp_path):
    todo, view = make_store_view(tmp_path)
    press(view, "jp")
    assert view.pending_priority
    screen = FakeScreen([])
    view.draw(screen)
    assert screen.frames[-1][9].startswith("priority:")
    view.handle(ord("b"))
    assert todo.read_text(encoding="utf-8").splitlines()[1] == "(B) buy milk @store"
    press(view, "p-")
    assert todo.read_text(encoding="utf-8").splitlines()[1] == "buy milk @store"
    press(view, "p1")
    assert "A-Z" in view.message
    press(view, "p")
    view.handle(tui.ESC)  # not a letter: cancels, changes nothing
    assert not view.pending_priority
    assert todo.read_text(encoding="utf-8").splitlines()[1] == "buy milk @store"


def test_add_task_with_creation_date(tmp_path):
    todo, view = make_store_view(tmp_path)
    press(view, "nfix bikex")
    view.handle(tui.KEY_BACKSPACE)
    assert view.adding and view.new_text == "fix bike"
    view.handle(10)
    assert not view.adding
    assert todo.read_text(encoding="utf-8").splitlines()[-1] == "2026-11-10 fix bike"
    assert view.message.startswith("Added")
    assert len(view.visible()) == 4
    press(view, "n")
    view.handle(tui.ESC)  # cancel
    press(view, "n")
    view.handle(10)
    assert view.message == "Nothing to add"
    assert len(todo.read_text(encoding="utf-8").splitlines()) == 5


def test_done_on_recurring_adds_next(tmp_path):
    todo, view = make_store_view(tmp_path, ["pay rent due:2026-11-10 rec:1m"])
    press(view, "x")
    lines = todo.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("x 2026-11-10 pay rent")
    assert "due:2026-12-10" in lines[1]
    assert "recurring" in view.message


def test_action_keys_merge_with_outside_edit(tmp_path):
    todo, view = make_store_view(tmp_path)
    with todo.open("a", encoding="utf-8", newline="") as fh:
        fh.write("added by sync\n")  # another program edits after the list was loaded
    press(view, "x")
    text = todo.read_text(encoding="utf-8")
    assert "x 2026-11-10 call mom" in text and "added by sync" in text
    assert "merged" in view.message


def test_actions_ignored_without_store_and_empty_list(tmp_path):
    view = make_view()
    press(view, "xupn")
    assert not view.adding and not view.pending_priority
    todo, view = make_store_view(tmp_path, ["x 2026-11-01 only done"])
    press(view, "x")
    assert view.message == "No task selected"


def test_save_failure_is_reported_not_raised(tmp_path):
    todo, view = make_store_view(tmp_path)
    todo.unlink()
    todo.mkdir()  # the file cannot be read or written any more
    press(view, "x")
    assert view.message.startswith(("Error", "Not saved"))


def test_launch_without_curses_gives_clear_error():
    def no_curses():
        raise ImportError("no curses")

    with pytest.raises(tui.TuiUnavailable, match="windows-curses"):
        tui.launch([], {}, TODAY, importer=no_curses)


def test_tui_command_needs_a_terminal(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    todo.write_text("a\n", encoding="utf-8")
    assert main(["--file", str(todo), "tui"]) == 1  # pytest's stdin is not a tty
    assert "needs a terminal" in capsys.readouterr().err
