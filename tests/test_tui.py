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
