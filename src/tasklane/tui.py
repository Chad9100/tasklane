"""A read-only full-screen task list.

The drawing and key handling work on any *screen* object that offers the small
subset of the ``curses`` window API used here (``getmaxyx``, ``erase``,
``addnstr``, ``refresh``, ``getch``), so tests can drive them with a fake.
``curses`` itself is imported only by :func:`launch`, because Python on Windows
does not ship it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from . import query
from .todo import Task

Item = tuple[int, Task]

# curses key codes, spelled out so this module needs no curses import
KEY_DOWN, KEY_UP, KEY_HOME, KEY_BACKSPACE, KEY_NPAGE, KEY_PPAGE, KEY_END, KEY_RESIZE = (
    258, 259, 262, 263, 338, 339, 360, 410)
ESC = 27
MIN_WIDTH, MIN_HEIGHT = 20, 4


class TuiUnavailable(Exception):
    """curses cannot be used here (not installed, or not a terminal)."""


class View:
    """State of the list: filter text, selection and scroll position."""

    def __init__(self, items: Sequence[Item], raws: dict[int, str], today: date):
        self.items = list(items)
        self.raws = raws
        self.today = today
        self.show_all = False
        self.filter = ""
        self.editing = False  # typing a filter after "/"
        self.selected = 0
        self.top = 0

    def visible(self) -> list[Item]:
        return query.filter_tasks(self.items, self.filter.split(), include_done=self.show_all,
                                  today=self.today)

    def _move(self, to: int, count: int) -> None:
        self.selected = max(0, min(to, count - 1)) if count else 0

    def handle(self, key: int, page: int = 10) -> bool:
        """Apply one key press; False means quit."""
        count = len(self.visible())
        if self.editing:
            if key in (10, 13):
                self.editing = False
            elif key == ESC:
                self.editing, self.filter = False, ""
            elif key in (KEY_BACKSPACE, 8, 127):
                self.filter = self.filter[:-1]
            elif 32 <= key < 0x110000 and key not in (KEY_RESIZE,) and not 256 <= key < 512:
                self.filter += chr(key)
            self._move(self.selected, len(self.visible()))
            return True
        if key in (ord("q"), ESC):
            if key == ESC and self.filter:
                self.filter = ""
            else:
                return False
        elif key in (ord("j"), KEY_DOWN):
            self._move(self.selected + 1, count)
        elif key in (ord("k"), KEY_UP):
            self._move(self.selected - 1, count)
        elif key == KEY_NPAGE:
            self._move(self.selected + page, count)
        elif key == KEY_PPAGE:
            self._move(self.selected - page, count)
        elif key in (ord("g"), KEY_HOME):
            self._move(0, count)
        elif key in (ord("G"), KEY_END):
            self._move(count, count)
        elif key == ord("/"):
            self.editing = True
        elif key == ord("a"):
            self.show_all = not self.show_all
        self._move(self.selected, len(self.visible()))
        return True

    def draw(self, screen) -> None:
        height, width = screen.getmaxyx()
        screen.erase()
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            screen.addnstr(0, 0, "Terminal too small", max(width - 1, 0))
            screen.refresh()
            return
        rows = self.visible()
        room = height - 2  # header and footer
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + room:
            self.top = self.selected - room + 1
        label = "all" if self.show_all else "open"
        header = f"tasklane  {len(rows)} {label} task(s)"
        if self.filter or self.editing:
            header += f"  filter: {self.filter}" + ("_" if self.editing else "")
        screen.addnstr(0, 0, header, width - 1)
        num_width = max((len(str(n)) for n, _ in rows), default=1)
        for i, (n, _task) in enumerate(rows[self.top:self.top + room]):
            mark = ">" if self.top + i == self.selected else " "
            screen.addnstr(1 + i, 0, f"{mark}{n:>{num_width}} {self.raws.get(n, '')}", width - 1)
        footer = "type to filter, Enter/Esc to finish" if self.editing else \
            "j/k move  / filter  a all/open  q quit"
        screen.addnstr(height - 1, 0, footer, width - 1)
        screen.refresh()


def run(screen, view: View) -> None:
    """Draw and handle keys until the user quits."""
    while True:
        view.draw(screen)
        height, _ = screen.getmaxyx()
        if not view.handle(screen.getch(), page=max(height - 2, 1)):
            return


def launch(items: Sequence[Item], raws: dict[int, str], today: date,
           importer: Callable[[], object] | None = None) -> None:
    """Open the list full-screen. Raises :class:`TuiUnavailable` without curses."""
    try:
        curses = importer() if importer else __import__("curses")
    except ImportError:
        raise TuiUnavailable(
            "the full-screen list needs the curses module, which this Python does not have"
            " (on Windows run `pip install windows-curses`); use `tasklane ls` instead") from None
    view = View(items, raws, today)

    def main(stdscr):
        stdscr.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        run(stdscr, view)

    try:
        curses.wrapper(main)
    except curses.error as exc:
        raise TuiUnavailable(f"cannot start the full-screen list: {exc}") from None
