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

from . import __version__, completion, ical, copies as copies_mod, merge, query, recur, tui
from .storage import FileChangedError, TaskIndexError, TodoFile, atomic_write, done_path_for
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
    force: bool = False

    @property
    def done_path(self) -> Path:
        return done_path_for(self.path)

    def load(self) -> TodoFile:
        return TodoFile.load(self.path)

    def render(self, n: int, task: Task, raw: str, width: int) -> str:
        line = colorize(raw, task, self.today) if self.color else raw
        return f"{n:>{width}} {line}"


def _save(tf: TodoFile, ctx: Context) -> None:
    """Save, telling the user when edits from another program were merged in
    or (with --force) overwritten after a backup."""
    tf.save(force=ctx.force)
    if tf.backup is not None:
        print(f"tasklane: --force: overwrote the other version of {tf.path.name};"
              f" it is saved as {tf.backup}", file=sys.stderr)
    elif tf.merged:
        print(f"tasklane: merged with changes another program made to {tf.path.name}"
              " meanwhile", file=sys.stderr)


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
    _save(tf, ctx)
    n = tf.number(n)
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
    report: list[tuple[str, int]] = []  # printed after saving, when numbers are final
    for n in numbers:
        task = tasks[n]
        if task.done:
            report.append(("Task {n} is already done.", n))
            continue
        try:
            following = recur.next_task(task, ctx.today)
        except ValueError as exc:
            print(f"tasklane: warning: task {n}: {exc}", file=sys.stderr)
            following = None
        task.complete(ctx.today)
        tf.set(n, task)
        report.append(("Completed {n}: {text}", n))
        if following is not None:
            report.append(("Recurring: added {n}: {text}", tf.append(following)))
    _save(tf, ctx)
    for template, n in report:
        n = tf.number(n)
        print(template.format(n=n, text=tf.text(n) if "{text}" in template else ""))
    return 0


def cmd_undo(args, ctx: Context) -> int:
    tf = ctx.load()
    task = tf.get(args.number)
    if not task.done:
        raise CliError(f"task {args.number} is not done")
    task.uncomplete()
    tf.set(args.number, task)
    _save(tf, ctx)
    n = tf.number(args.number)
    print(f"Reopened {n}: {tf.text(n)}")
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
    _save(tf, ctx)
    n = tf.number(args.number)
    print(f"Prioritized {n}: {tf.text(n)}")
    return 0


def cmd_depri(args, ctx: Context) -> int:
    tf = ctx.load()
    task = tf.get(args.number)
    if not task.priority:
        print(f"Task {args.number} has no priority.")
        return 0
    task.priority = None
    tf.set(args.number, task)
    _save(tf, ctx)
    n = tf.number(args.number)
    print(f"Deprioritized {n}: {tf.text(n)}")
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
    _save(tf, ctx)
    n = tf.number(args.number)
    print(f"Edited {n}: {tf.text(n)}")
    return 0


def cmd_rm(args, ctx: Context) -> int:
    tf = ctx.load()
    raw = tf.text(args.number)
    if not args.yes:
        raise CliError(f"refusing to remove task {args.number} without --yes: {raw}")
    tf.blank(args.number)
    _save(tf, ctx)
    print(f"Removed {tf.number(args.number)}: {raw}")
    return 0


def cmd_archive(args, ctx: Context) -> int:
    tf = ctx.load()
    before = len(tf)
    moved = tf.remove_done()
    if not moved and len(tf) == before:
        print("Nothing to archive.")
        return 0
    if moved:
        tf.bytes_to_save(force=ctx.force)  # merge before touching done.txt, so a conflict changes nothing
        done = TodoFile.load(ctx.done_path)
        for raw in moved:
            done.append_raw(raw)
        done.save()  # write done.txt first: a crash can duplicate, never lose
    _save(tf, ctx)
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


def cmd_export(args, ctx: Context) -> int:
    tf = ctx.load()
    chosen = [
        (n, t)
        for n, t in tf.tasks()
        if (args.all or not t.done) and (args.hidden or not t.hidden) and query.matches(t, args.terms)
    ]
    data = ical.calendar((t for _, t in chosen), ctx.today).encode("utf-8", "surrogateescape")
    if args.output is None or args.output == "-":
        sys.stdout.flush()
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:  # pragma: no cover - a text-only stream
            sys.stdout.write(data.decode("utf-8", "surrogateescape"))
        else:
            buffer.write(data)
            buffer.flush()
        return 0
    out = Path(args.output).expanduser()
    atomic_write(out, data)
    print(f"Exported {len(chosen)} task(s) to {out}", file=sys.stderr)
    return 0


def cmd_conflicts(args, ctx: Context) -> int:
    copies = copies_mod.find_copies(ctx.path)
    if not copies:
        print(f"No conflicted copies of {ctx.path.name} found.")
        return 0
    tf = ctx.load()
    current = ctx.path.read_bytes() if ctx.path.exists() else b""
    pending: list[tuple[Path, list[str]]] = []
    for copy in copies:
        lines = copies_mod.new_lines(current, copy.read_bytes())
        for line in lines:  # later copies only add what is still missing
            current += b"\n" + line.encode("utf-8", "surrogateescape")
        pending.append((copy, lines))
    for copy, lines in pending:
        print(f"{copy.name}: {len(lines)} task(s) not in {ctx.path.name}")
        for line in lines:
            print(f"  + {line}")
    if not args.merge:
        print("Run again with --merge to append these tasks and set the copies aside.")
        return 0
    for _, lines in pending:
        for line in lines:
            tf.append_raw(line)
    if any(lines for _, lines in pending):
        _save(tf, ctx)
    for copy, _ in pending:
        os.replace(copy, copies_mod.merged_name(copy))
    total = sum(len(lines) for _, lines in pending)
    print(f"Appended {total} task(s) from {len(copies)} copy file(s);"
          f" the copies were renamed to *{copies_mod.MERGED_SUFFIX}.")
    return 0


def cmd_tui(args, ctx: Context) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise CliError("tui needs a terminal; use `tasklane ls` in scripts")
    tf = ctx.load()
    items = tf.tasks()
    try:
        tui.launch(items, {n: tf.text(n) for n, _ in items}, ctx.today,
                   store=tui.TaskStore(ctx.path, ctx.today, ctx.force))
    except tui.TuiUnavailable as exc:
        raise CliError(str(exc)) from None
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

    force_help = ("if the file changed on disk in a way that cannot be merged, overwrite it"
                  " after saving the other version as todo.txt.theirs-DATE-TIME.bak")
    parser = argparse.ArgumentParser(
        prog="tasklane",
        description="A todo.txt task manager for the command line.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--force", action="store_true", default=False, help=force_help)
    add_common(parser, None)
    common = argparse.ArgumentParser(add_help=False)
    add_common(common, argparse.SUPPRESS)
    common.add_argument("--force", action="store_true", default=argparse.SUPPRESS, help=force_help)
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

    p = command("export", cmd_export, "export tasks as an iCalendar file of VTODO entries")
    p.add_argument("terms", nargs="*", metavar="FILTER", help="only export matching tasks (same terms as ls)")
    fmt = p.add_mutually_exclusive_group(required=True)
    fmt.add_argument("--ics", action="store_true", help="iCalendar (RFC 5545) VTODO format")
    p.add_argument("-o", "--output", metavar="PATH",
                   help="write to PATH (atomically) instead of standard output")
    p.add_argument("--all", action="store_true", help="include completed tasks (STATUS:COMPLETED)")
    p.add_argument("--hidden", action="store_true", help="include h:1 hidden tasks")

    p = command("conflicts", cmd_conflicts,
                "list conflicted copies left by Dropbox/Syncthing; --merge appends their new tasks")
    p.add_argument("--merge", action="store_true",
                   help="append the tasks the file lacks and rename the copies to NAME.merged")

    command("tui", cmd_tui, "browse and change tasks in a full-screen list (needs curses)")

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
        if getattr(args, "command", None) in ("ls", "export") and not any(e.startswith("--") for e in extra):
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
    ctx = Context(resolve_path(args.file, os.environ), today or date.today(), color,
                  getattr(args, "force", False))
    try:
        return args.func(args, ctx)
    except (CliError, TaskIndexError) as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        return 1
    except FileChangedError as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        for conflict in exc.conflicts:
            for line in merge.describe_conflict(conflict):
                print(f"tasklane: {line}", file=sys.stderr)
        print("tasklane: the other program's version (an editor, a sync client) was kept;"
              " run the command again to apply it to the new contents"
              " (or add --force to overwrite it; a backup is kept)", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"tasklane: error: {exc}", file=sys.stderr)
        return 1
