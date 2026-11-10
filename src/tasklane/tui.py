"""A full-screen task list that can complete, reopen, prioritise and add tasks.

The drawing and key handling work on any *screen* object that offers the small
subset of the ``curses`` window API used here (``getmaxyx``, ``erase``,
``addnstr``, ``refresh``, ``getch``), so tests can drive them with a fake.
``curses`` itself is imported only by :func:`launch`, because Python on Windows
does not ship it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from . import query, recur
from .storage import FileChangedError, TaskIndexError, TodoFile
from .todo import Task, format_task, parse_task

Item = tuple[int, Task]

# curses key codes, spelled out so this module needs no curses import
KEY_DOWN, KEY_UP, KEY_HOME, KEY_BACKSPACE, KEY_NPAGE, KEY_PPAGE, KEY_END, KEY_RESIZE = (
    258, 259, 262, 263, 338, 339, 360, 410)
ESC = 27
MIN_WIDTH, MIN_HEIGHT = 20, 4


class TuiUnavailable(Exception):
    """curses cannot be used here (not installed, or not a terminal)."""


class TaskStore:
    """Changes made from the list, applied through the normal load, edit and
    :meth:`TodoFile.save` path, so edits made by other programs are merged.

    Every method returns a one-line message for the status bar; a failure
    (conflict, bad line number, unwritable file) is reported, never raised.
    """

    def __init__(self, path: Path, today: date, force: bool = False):
        self.path, self.today, self.force = Path(path), today, force
        self._shown: TodoFile | None = None

    def load(self) -> tuple[list[Item], dict[int, str]]:
        """Read the file; the snapshot is what the list shows and what the
        next change is based on."""
        self._shown = None
        tf = TodoFile.load(self.path)
        self._shown = tf
        items = tf.tasks()
        return items, {n: tf.text(n) for n, _ in items}

    def _apply(self, change: Callable[[TodoFile], str]) -> str:
        # Change the snapshot the user is looking at (its line numbers are the
        # ones on screen); save() merges edits made on disk since it was read.
        tf, self._shown = self._shown, None
        try:
            if tf is None:
                tf = TodoFile.load(self.path)
            message = change(tf)
            tf.save(force=self.force)
        except FileChangedError as exc:
            return f"Not saved: {exc}"
        except (TaskIndexError, ValueError, OSError) as exc:
            return f"Error: {exc}"
        return message + (" (merged with outside changes)" if tf.merged else "")

    def add(self, text: str) -> str:
        task = parse_task(" ".join(text.split()))
        if not task.text.strip():
            return "Nothing to add"
        if not task.done and task.creation_date is None:
            task.creation_date = self.today

        def change(tf: TodoFile) -> str:
            tf.append(task)
            return f"Added: {format_task(task)}"
        return self._apply(change)

    def done(self, n: int) -> str:
        def change(tf: TodoFile) -> str:
            task = tf.get(n)
            if task.done:
                return f"Task {n} is already done"
            try:
                following = recur.next_task(task, self.today)
            except ValueError:
                following = None
            task.complete(self.today)
            tf.set(n, task)
            if following is not None:
                tf.append(following)
            return f"Completed {n}" + (" (recurring: added the next one)" if following else "")
        return self._apply(change)

    def undo(self, n: int) -> str:
        def change(tf: TodoFile) -> str:
            task = tf.get(n)
            if not task.done:
                return f"Task {n} is not done"
            task.uncomplete()
            tf.set(n, task)
            return f"Reopened {n}"
        return self._apply(change)

    def priority(self, n: int, letter: str | None) -> str:
        def change(tf: TodoFile) -> str:
            task = tf.get(n)
            if task.done:
                return f"Task {n} is done; reopen it first"
            task.priority = letter
            tf.set(n, task)
            return f"Priority of {n}: {letter or 'none'}"
        return self._apply(change)


class View:
    """State of the list: filter text, selection and scroll position.

    With a *store* the list can change tasks: ``x`` completes, ``u`` reopens,
    ``p`` then a letter sets the priority (``-`` clears it), ``n`` adds one.
    """

    def __init__(self, items: Sequence[Item], raws: dict[int, str], today: date,
                 store: TaskStore | None = None):
        self.items = list(items)
        self.raws = raws
        self.today = today
        self.store = store
        self.show_all = False
        self.filter = ""
        self.editing = False  # typing a filter after "/"
        self.adding = False  # typing a new task after "n"
        self.new_text = ""
        self.pending_priority = False  # "p" pressed, waiting for the letter
        self.message = ""
        self.selected = 0
        self.top = 0

    def _selected_number(self) -> int | None:
        rows = self.visible()
        return rows[self.selected][0] if rows else None

    def _after(self, message: str) -> None:
        """Reload from disk after a change and show *message*."""
        self.message = message
        if self.store is not None:
            try:
                self.items, self.raws = self.store.load()
            except (OSError, ValueError) as exc:
                self.message = f"Error: {exc}"

    def _act(self, key: int) -> None:
        if self.store is None:
            return
        if key == ord("n"):
            self.adding, self.new_text, self.message = True, "", ""
            return
        n = self._selected_number()
        if n is None:
            self.message = "No task selected"
        elif key == ord("x"):
            self._after(self.store.done(n))
        elif key == ord("u"):
            self._after(self.store.undo(n))
        elif key == ord("p"):
            self.pending_priority, self.message = True, ""

    def _typing(self, key: int, text: str) -> str | None:
        """Edit *text* with *key*; None when the key is not a text key."""
        if key in (KEY_BACKSPACE, 8, 127):
            return text[:-1]
        if 32 <= key < 0x110000 and not 256 <= key < 512:
            return text + chr(key)
        return None

    def visible(self) -> list[Item]:
        return query.filter_tasks(self.items, self.filter.split(), include_done=self.show_all,
                                  today=self.today)

    def _move(self, to: int, count: int) -> None:
        self.selected = max(0, min(to, count - 1)) if count else 0

    def handle(self, key: int, page: int = 10) -> bool:
        """Apply one key press; False means quit."""
        self.message = ""
        count = len(self.visible())
        if self.adding:
            if key in (10, 13):
                self.adding = False
                self._after(self.store.add(self.new_text) if self.store else "")
            elif key == ESC:
                self.adding = False
            else:
                typed = self._typing(key, self.new_text)
                self.new_text = self.new_text if typed is None else typed
            return True
        if self.pending_priority:
            self.pending_priority = False
            n = self._selected_number()
            if n is not None and self.store is not None and 32 <= key < 128:
                letter = chr(key).upper()
                if letter == "-" or letter == " ":
                    self._after(self.store.priority(n, None))
                elif "A" <= letter <= "Z":
                    self._after(self.store.priority(n, letter))
                else:
                    self.message = "Priority must be a letter A-Z (- clears it)"
            return True
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
        else:
            self._act(key)
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
        if self.adding:
            footer = f"new task: {self.new_text}_"
        elif self.pending_priority:
            footer = "priority: press A-Z, or - to clear (Esc cancels)"
        elif self.editing:
            footer = "type to filter, Enter/Esc to finish"
        elif self.message:
            footer = self.message
        elif self.store is not None:
            footer = "j/k move  x done  u undo  p pri  n new  / filter  a all  q quit"
        else:
            footer = "j/k move  / filter  a all/open  q quit"
        if self.adding:  # keep the end of a long new task visible
            footer = footer[-(width - 1):] if width > 1 else footer
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
           importer: Callable[[], object] | None = None,
           store: TaskStore | None = None) -> None:
    """Open the list full-screen. Raises :class:`TuiUnavailable` without curses."""
    try:
        curses = importer() if importer else __import__("curses")
    except ImportError:
        raise TuiUnavailable(
            "the full-screen list needs the curses module, which this Python does not have"
            " (on Windows run `pip install windows-curses`); use `tasklane ls` instead") from None
    view = View(items, raws, today, store)

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
