"""Command-line interface for tasklane."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import __version__, completion, query, recur
from .storage import FileChangedError, TaskIndexError, TodoFile, done_path_for
from .todo import Task, parse_task


class CliError(Exception):
    """A user-facing error; reported on stderr with exit code 1."""


# -- colour ------------------------------------------------------------------
RESET = "\033[0m"
PRIORITY_COLORS = {"A": "\033[1;31m", "B": "\033[33m", "C": "\033[36m"}
DONE_COLOR = "\033[2m"
OVERDUE_COLOR = "\033[1;31m"
_DUE_TOKEN = re.compile(r"(?<!\S)due:\S+")


def use_color(mode: str, stream, env: Mapping[str, str]) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    if env.get("NO_COLOR"):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:  # pragma: no cover - depends on the console
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # pragma: no cover
        pass


def colorize(line: str, task: Task, today: date) -> str:
    if task.done:
        return f"{DONE_COLOR}{line}{RESET}"
    base = PRIORITY_COLORS.get(task.priority or "", "")
    overdue = task.due is not None and task.due < today
    if overdue:
        line = _DUE_TOKEN.sub(lambda m: f"{OVERDUE_COLOR}{m.group(0)}{RESET}{base}", line, count=1)
    if base:
        return f"{base}{line}{RESET}"
    return line


# -- plumbing ----------------------------------------------------------------
def resolve_path(arg: str | None, env: Mapping[str, str]) -> Path:
    if arg:
        return Path(arg).expanduser()
    if env.get("TASKLANE_FILE"):
        return Path(env["TASKLANE_FILE"]).expanduser()
    return Path.home() / "todo.txt"


@dataclass
class Context:
    path: Path
    today: date
    color: bool

    @property
    def done_path(self) -> Path:
        return done_path_for(self.path)

    def load(self) -> TodoFile:
        return TodoFile.load(self.path)

    def render(self, n: int, task: Task, raw: str, width: int) -> str:
        line = colorize(raw, task, self.today) if self.color else raw
        return f"{n:>{width}} {line}"


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _width(numbers) -> int:
    return max((len(str(n)) for n in numbers), default=1)


def _clean_text(words: list[str]) -> str:
    text = " ".join(words)
    return " ".join(text.replace("\r", " ").replace("\n", " ").split(" ")).strip()


# -- commands ----------------------------------------------------------------
def cmd_add(args, ctx: Context) -> int:
    text = _clean_text(args.text)
    task = parse_task(text)
    if not task.text.strip():
        raise CliError("nothing to add: the task has no description")
    if not task.done and task.creation_date is None:
        task.creation_date = ctx.today
    tf = ctx.load()
    n = tf.append(task)
    tf.save()
    print(f"Added {n}: {tf.text(n)}")
    return 0


def cmd_ls(args, ctx: Context) -> int:
    tf = ctx.load()
    every = tf.tasks()
    shown = query.filter_tasks(
        every, args.terms, include_done=args.all, today=ctx.today, include_hidden=args.hidden
    )
    if args.json:
        _print_json([query.task_to_dict(n, t, tf.text(n)) for n, t in shown])
        return 0
    width = _width(n for n, _ in shown)
    for n, task in shown:
        print(ctx.render(n, task, tf.text(n), width))
    total = len(every) if args.all else sum(1 for _, t in every if not t.done)
    print("--")
    summary = f"{len(shown)} of {total} tasks shown"
    if not args.all:
        waiting = sum(
            1
            for _, t in every
            if t.deferred(ctx.today) and (args.hidden or not t.hidden) and query.matches(t, args.terms)
        )
        if waiting:
            summary += f" ({waiting} hidden until their t: date; --all shows them)"
    if not args.hidden:
        marked = sum(
            1
            for _, t in every
            if t.hidden and (args.all or not t.done) and query.matches(t, args.terms)
        )
        if marked:
            summary += f" ({marked} marked h:1; --hidden shows them)"
    print(summary)
    return 0


def _numbers(values: list[int]) -> list[int]:
    seen: list[int] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def cmd_do(args, ctx: Context) -> int:
    tf = ctx.load()
    numbers = _numbers(args.numbers)
    tasks = {n: tf.get(n) for n in numbers}  # validate every number before changing anything
    for n in numbers:
        task = tasks[n]
        if task.done:
            print(f"Task {n} is already done.")
            continue
        try:
            following = recur.next_task(task, ctx.today)
        except ValueError as exc:
            print(f"tasklane: warning: task {n}: {exc}", file=sys.stderr)
            following = None
        task.complete(ctx.today)
        tf.set(n, task)
        print(f"Completed {n}: {tf.text(n)}")
        if following is not None:
            m = tf.append(following)
            print(f"Recurring: added {m}: {tf.text(m)}")
    tf.save()
    return 0


def cmd_undo(args, ctx: Context) -> int:
    tf = ctx.load()
    task = tf.get(args.number)
    if not task.done:
        raise CliError(f"task {args.number} is not done")
    task.uncomplete()
    tf.set(args.number, task)
    tf.save()
    print(f"Reopened {args.number}: {tf.text(args.number)}")
    return 0


def cmd_pri(args, ctx: Context) -> int:
    letter = args.priority.upper()
    if not re.fullmatch(r"[A-Z]", letter):
        raise CliError(f"priority must be a single letter A-Z, not {args.priority!r}")
    tf = ctx.load()
    task = tf.get(args.number)
    if task.done:
        raise CliError(f"task {args.number} is done; undo it first")
    task.priority = letter
    tf.set(args.number, task)
    tf.save()
    print(f"Prioritized {args.number}: {tf.text(args.number)}")
    return 0


def cmd_depri(args, ctx: Context) -> int:
    tf = ctx.load()
    task = tf.get(args.number)
    if not task.priority:
        print(f"Task {args.number} has no priority.")
        return 0
    task.priority = None
    tf.set(args.number, task)
    tf.save()
    print(f"Deprioritized {args.number}: {tf.text(args.number)}")
    return 0


def cmd_edit(args, ctx: Context) -> int:
    tf = ctx.load()
    old = tf.get(args.number)
    new = parse_task(_clean_text(args.text))
    if not new.text.strip():
        raise CliError("the new text has no description; use rm to delete a task")
    # Keep whatever the new text does not specify itself.
    if new.creation_date is None:
        new.creation_date = old.creation_date
    if old.done and not new.done:
        new.done, new.completion_date, new.priority = True, old.completion_date, None
    elif not new.done and new.priority is None:
        new.priority = old.priority
    tf.set(args.number, new)
    tf.save()
    print(f"Edited {args.number}: {tf.text(args.number)}")
    return 0


def cmd_rm(args, ctx: Context) -> int:
    tf = ctx.load()
    raw = tf.text(args.number)
    if not args.yes:
        raise CliError(f"refusing to remove task {args.number} without --yes: {raw}")
    tf.blank(args.number)
    tf.save()
    print(f"Removed {args.number}: {raw}")
    return 0


def cmd_archive(args, ctx: Context) -> int:
    tf = ctx.load()
    before = len(tf)
    moved = tf.remove_done()
    if not moved and len(tf) == before:
        print("Nothing to archive.")
        return 0
    if moved:
        tf.check_unchanged()  # before touching done.txt, so a conflict changes nothing
        done = TodoFile.load(ctx.done_path)
        for raw in moved:
            done.append_raw(raw)
        done.save()  # write done.txt first: a crash can duplicate, never lose
    tf.save()
    print(f"Archived {len(moved)} task(s) to {ctx.done_path.name}; line numbers renumbered.")
    return 0


def _due_label(days: int) -> str:
    if days < 0:
        return f"overdue {-days}d"
    if days == 0:
        return "due today"
    return f"due in {days}d"


def cmd_due(args, ctx: Context) -> int:
    if args.days < 0:
        raise CliError("--days must be zero or more")
    tf = ctx.load()
    items = query.due_soon(tf.tasks(), ctx.today, args.days)
    if args.json:
        rows = []
        for n, task in items:
            row = query.task_to_dict(n, task, tf.text(n))
            row["days_left"] = (task.due - ctx.today).days
            row["overdue"] = task.due < ctx.today
            rows.append(row)
        _print_json(rows)
        return 0
    if not items:
        print(f"Nothing overdue or due in the next {args.days} days.")
        return 0
    width = _width(n for n, _ in items)
    for n, task in items:
        days = (task.due - ctx.today).days
        print(f"{ctx.render(n, task, tf.text(n), width)}  [{_due_label(days)}]")
    return 0


def _names(args, ctx: Context, attr: str, sigil: str) -> int:
    tasks = [t for _, t in ctx.load().tasks()]
    names = query.collect(tasks, attr)
    if args.json:
        _print_json(names)
    else:
        for name in names:
            print(f"{sigil}{name}")
    return 0


def cmd_projects(args, ctx: Context) -> int:
    return _names(args, ctx, "projects", "+")


def cmd_contexts(args, ctx: Context) -> int:
    return _names(args, ctx, "contexts", "@")


def cmd_report(args, ctx: Context) -> int:
    tasks = [t for _, t in ctx.load().tasks()]
    archived = [t for _, t in TodoFile.load(ctx.done_path).tasks() if t.done]
    data = query.report(
        [t for t in tasks if not t.done],
        [t for t in tasks if t.done] + archived,
    )
    if args.json:
        _print_json(data)
        return 0
    labels = [("+" + r["project"]) if r["project"] != query.NO_PROJECT else r["project"] for r in data["projects"]]
    width = max([len("PROJECT"), len("TOTAL"), *map(len, labels)])
    print(f"{'PROJECT':<{width}}  {'OPEN':>5}  {'DONE':>5}")
    for label, row in zip(labels, data["projects"]):
        print(f"{label:<{width}}  {row['open']:>5}  {row['done']:>5}")
    print(f"{'TOTAL':<{width}}  {data['total']['open']:>5}  {data['total']['done']:>5}")
    return 0


def cmd_completion(args, ctx: Context) -> int:
    sys.stdout.write(completion.script(args.shell, build_parser()))
    return 0


# -- parser ------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    def add_common(p: argparse.ArgumentParser, default) -> None:
        p.add_argument("--file", metavar="PATH", default=default,
                       help="todo.txt to use (default: $TASKLANE_FILE, else ~/todo.txt)")
        p.add_argument("--color", choices=["auto", "always", "never"], default=default if default is argparse.SUPPRESS else "auto",
                       help="colorize output (default: auto = only on a terminal without NO_COLOR)")

    parser = argparse.ArgumentParser(
        prog="tasklane",
        description="A todo.txt task manager for the command line.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    add_common(parser, None)
    common = argparse.ArgumentParser(add_help=False)
    add_common(common, argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def command(name, func, help_text):
        p = sub.add_parser(name, parents=[common], help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = command("add", cmd_add, "add a task (creation date is added automatically)")
    p.add_argument("text", nargs="+", help='task text, e.g. "(A) Call mom +family due:2026-11-20"')

    p = command("ls", cmd_ls, "list open tasks, optionally filtered (tasks with a future t: date or h:1 are hidden)")
    p.add_argument("terms", nargs="*", metavar="FILTER",
                   help="all must match: word, +project, @context; -term excludes")
    p.add_argument("--all", action="store_true",
                   help="include completed tasks and tasks whose t: threshold date is in the future")
    p.add_argument("--hidden", action="store_true",
                   help="include h:1 hidden tasks (placeholders that are otherwise never listed)")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("do", cmd_do, "mark tasks as done (recurring tasks spawn their next occurrence)")
    p.add_argument("numbers", nargs="+", type=int, metavar="N")

    p = command("undo", cmd_undo, "reopen a completed task")
    p.add_argument("number", type=int, metavar="N")

    p = command("pri", cmd_pri, "set the priority of a task")
    p.add_argument("number", type=int, metavar="N")
    p.add_argument("priority", metavar="A-Z")

    p = command("depri", cmd_depri, "remove the priority of a task")
    p.add_argument("number", type=int, metavar="N")

    p = command("edit", cmd_edit, "replace the text of a task")
    p.add_argument("number", type=int, metavar="N")
    p.add_argument("text", nargs="+")

    p = command("rm", cmd_rm, "delete a task (its line is left blank until archive)")
    p.add_argument("number", type=int, metavar="N")
    p.add_argument("--yes", action="store_true", help="really delete")

    command("archive", cmd_archive, "move completed tasks to done.txt and renumber")

    p = command("due", cmd_due, "show overdue tasks and tasks due soon")
    p.add_argument("--days", type=int, default=7, help="look-ahead window in days (default 7)")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("projects", cmd_projects, "list +projects")
    p.add_argument("--json", action="store_true", help="print JSON")
    p = command("contexts", cmd_contexts, "list @contexts")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("report", cmd_report, "open/done counts per project (done includes done.txt)")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("completion", cmd_completion, "print a shell completion script (bash, zsh, fish, powershell)")
    p.add_argument("shell", choices=completion.SHELLS)
    return parser


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        # "ls +home -milk": argparse sees "-milk" as an unknown option, so hand
        # such exclusion terms (and anything after them) back to the filter.
        if getattr(args, "command", None) == "ls" and not any(e.startswith("--") for e in extra):
            args.terms = [*args.terms, *extra]
        else:
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2
    _configure_stdout()
    color = use_color(args.color, sys.stdout, os.environ)
    if color:
        _enable_windows_ansi()
    ctx = Context(resolve_path(args.file, os.environ), today or date.today(), color)
    try:
        return args.func(args, ctx)
    except (CliError, TaskIndexError) as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        return 1
    except FileChangedError as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        print("tasklane: the other program's version (an editor, a sync client) was kept;"
              " run the command again to apply it to the new contents", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        return 1
