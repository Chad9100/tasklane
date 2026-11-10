# tasklane

A small command-line task manager that reads and writes the plain-text
[todo.txt](https://github.com/todotxt/todo.txt) format. Your tasks live in one
ordinary text file you can open in any editor, sync with any tool, and keep
using with other todo.txt apps. tasklane adds filters, due-date views,
recurring tasks, per-project reports and JSON output on top.

**Who it is for:** people who want their task list in a plain file they own,
and a fast terminal workflow (`add`, `ls`, `do`) without a database, an account
or a sync service.

**Built with:** Python 3.10+ and the standard library only (no runtime
dependencies). Tests use pytest; CI runs on Ubuntu and Windows with Python
3.10, 3.12 and 3.13.

## Install

```sh
pip install git+https://github.com/Chad9100/tasklane.git
```

or from a clone:

```sh
git clone https://github.com/Chad9100/tasklane.git
cd tasklane
pip install .
```

## Where the tasks are stored

1. `--file PATH` if given (before or after the command),
2. otherwise the `TASKLANE_FILE` environment variable,
3. otherwise `~/todo.txt`.

Completed tasks are moved by `archive` to `done.txt` in the same folder.

## Usage

| Command | What it does |
| --- | --- |
| `add TEXT` | Add a task; today's date is added as the creation date. `(A)` priority, `+project`, `@context` and `key:value` tags are kept. |
| `ls [FILTER...]` | List open tasks. Terms are ANDed: `word`, `+project`, `@context`; `-term` excludes. `--all` includes done tasks and tasks with a future `t:` date, `--hidden` includes `h:1` tasks, `--json` prints JSON. Sorted by priority, then due date, then line number. |
| `do N...` | Mark tasks done. A task with `rec:` creates its next occurrence. |
| `undo N` | Reopen a completed task (its priority is restored). |
| `pri N A` / `depri N` | Set or remove a priority. |
| `edit N TEXT` | Replace a task's text (keeps priority and creation date unless the new text sets them). |
| `rm N --yes` | Delete a task. The line is blanked so other numbers do not move. |
| `archive` | Move completed tasks to `done.txt`, drop blank lines, renumber. |
| `due [--days N]` | Overdue tasks plus tasks due within N days (default 7). `--json` available. |
| `projects` / `contexts` | List the `+projects` / `@contexts` in use. |
| `report` | Open/done counts per project (done includes `done.txt`). `--json` available. |
| `completion SHELL` | Print a completion script for `bash`, `zsh`, `fish` or `powershell` (see [Shell completion](#shell-completion)). |

The number in front of each task is its line in `todo.txt`. Numbers stay the
same through `add`, `do`, `rm` and edits; only `archive` renumbers.

Color (priorities A/B/C, overdue due dates, done tasks) is used only when
stdout is a terminal and `NO_COLOR` is not set. Override with
`--color auto|always|never`.

Exit codes: `0` success, `1` an error such as a missing task number or `rm`
without `--yes`, `2` invalid command-line usage.

### Example session

The output below is real, captured from a throwaway `todo.txt` in a temporary
folder on 2026-11-09 (with `TASKLANE_FILE` pointing at it and `NO_COLOR=1`).

```console
$ tasklane add "(A) Renew passport +travel @errands due:2026-11-12"
Added 1: (A) 2026-11-09 Renew passport +travel @errands due:2026-11-12

$ tasklane add "Water the plants @home due:2026-11-05 rec:3d"
Added 2: 2026-11-09 Water the plants @home due:2026-11-05 rec:3d

$ tasklane add "(B) Pay rent +home due:2026-11-01 rec:+1m"
Added 3: (B) 2026-11-09 Pay rent +home due:2026-11-01 rec:+1m

$ tasklane add "Draft talk outline +conf @laptop due:2026-11-27"
Added 4: 2026-11-09 Draft talk outline +conf @laptop due:2026-11-27

$ tasklane add "Read https://example.com/todo-spec +conf"
Added 5: 2026-11-09 Read https://example.com/todo-spec +conf

$ tasklane ls
1 (A) 2026-11-09 Renew passport +travel @errands due:2026-11-12
3 (B) 2026-11-09 Pay rent +home due:2026-11-01 rec:+1m
2 2026-11-09 Water the plants @home due:2026-11-05 rec:3d
4 2026-11-09 Draft talk outline +conf @laptop due:2026-11-27
5 2026-11-09 Read https://example.com/todo-spec +conf
--
5 of 5 tasks shown

$ tasklane ls +conf -outline
5 2026-11-09 Read https://example.com/todo-spec +conf
--
1 of 5 tasks shown

$ tasklane due
3 (B) 2026-11-09 Pay rent +home due:2026-11-01 rec:+1m  [overdue 8d]
2 2026-11-09 Water the plants @home due:2026-11-05 rec:3d  [overdue 4d]
1 (A) 2026-11-09 Renew passport +travel @errands due:2026-11-12  [due in 3d]

$ tasklane do 3
Completed 3: x 2026-11-09 2026-11-09 Pay rent +home due:2026-11-01 rec:+1m pri:B
Recurring: added 6: (B) 2026-11-09 Pay rent +home due:2026-12-01 rec:+1m

$ tasklane report
PROJECT   OPEN   DONE
+conf        2      0
+home        1      1
+travel      1      0
(none)       1      0
TOTAL        5      1

$ tasklane ls --json @errands
[
  {
    "line": 1,
    "raw": "(A) 2026-11-09 Renew passport +travel @errands due:2026-11-12",
    "done": false,
    "priority": "A",
    "completion_date": null,
    "creation_date": "2026-11-09",
    "text": "Renew passport +travel @errands due:2026-11-12",
    "projects": [
      "travel"
    ],
    "contexts": [
      "errands"
    ],
    "tags": {
      "due": "2026-11-12"
    },
    "due": "2026-11-12"
  }
]

$ tasklane archive
Archived 1 task(s) to done.txt; line numbers renumbered.

$ tasklane ls
1 (A) 2026-11-09 Renew passport +travel @errands due:2026-11-12
5 (B) 2026-11-09 Pay rent +home due:2026-12-01 rec:+1m
2 2026-11-09 Water the plants @home due:2026-11-05 rec:3d
3 2026-11-09 Draft talk outline +conf @laptop due:2026-11-27
4 2026-11-09 Read https://example.com/todo-spec +conf
--
5 of 5 tasks shown
```

After that session the files are plain todo.txt:

```text
# todo.txt
(A) 2026-11-09 Renew passport +travel @errands due:2026-11-12
2026-11-09 Water the plants @home due:2026-11-05 rec:3d
2026-11-09 Draft talk outline +conf @laptop due:2026-11-27
2026-11-09 Read https://example.com/todo-spec +conf
(B) 2026-11-09 Pay rent +home due:2026-12-01 rec:+1m

# done.txt
x 2026-11-09 2026-11-09 Pay rent +home due:2026-11-01 rec:+1m pri:B
```

Filters that start with `-` work anywhere after `ls` (`tasklane ls -milk +home`).
A term that collides with an option (`-h`) can be passed after `--`.

### Recurring tasks

Add `rec:` to a task; completing it with `do` appends the next occurrence with
a new `due:` date.

| Tag | Next due date |
| --- | --- |
| `rec:3d`, `rec:1w`, `rec:1m`, `rec:1y` | counted from the day you complete it |
| `rec:+3d`, `rec:+1w`, `rec:+1m`, `rec:+1y` | strict: counted from the current `due:` date, so a late completion keeps the schedule |

Month and year steps clamp to the end of the month: `due:2027-01-31 rec:+1m`
becomes `due:2027-02-28`. An unreadable `rec:` value prints a warning and the
task is completed without a follow-up.

A [`t:` threshold date](#threshold-dates) moves along with `due:`: the next
occurrence keeps the same number of days between the two, so a task that
appears three days before it is due keeps doing so. Without a `due:` date the
new `t:` is the new due date, and a `t:` value that is not a valid date is
copied unchanged. With today being 2026-11-09:

```text
$ cat todo.txt
2026-11-01 Change the water filter +home t:2026-11-06 due:2026-11-09 rec:+1w
2026-11-02 Send timesheet +work t:2026-11-07 due:2026-11-07 rec:1w

$ tasklane do 1 2
Completed 1: x 2026-11-09 2026-11-01 Change the water filter +home t:2026-11-06 due:2026-11-09 rec:+1w
Recurring: added 3: 2026-11-09 Change the water filter +home t:2026-11-13 due:2026-11-16 rec:+1w
Completed 2: x 2026-11-09 2026-11-02 Send timesheet +work t:2026-11-07 due:2026-11-07 rec:1w
Recurring: added 4: 2026-11-09 Send timesheet +work t:2026-11-16 due:2026-11-16 rec:1w

$ tasklane ls
--
0 of 2 tasks shown (2 hidden until their t: date; --all shows them)
```

### Threshold dates

Add `t:YYYY-MM-DD` to a task you cannot or do not want to start yet. `ls`
hides it until that day, says how many tasks are waiting, and `ls --all` shows
them. A `t:` value that is not a valid date is ignored, so the task stays
visible. With today being 2026-11-09:

```text
$ cat todo.txt
(A) 2026-11-01 File quarterly taxes +money due:2026-11-15
2026-11-02 Book ski trip +winter t:2026-12-01
2026-11-03 Renew car insurance +money t:2026-11-09 due:2026-11-30
2026-11-04 Order holiday cards +winter t:2026-11-25

$ tasklane ls
1 (A) 2026-11-01 File quarterly taxes +money due:2026-11-15
3 2026-11-03 Renew car insurance +money t:2026-11-09 due:2026-11-30
--
2 of 4 tasks shown (2 hidden until their t: date; --all shows them)

$ tasklane ls --all
1 (A) 2026-11-01 File quarterly taxes +money due:2026-11-15
3 2026-11-03 Renew car insurance +money t:2026-11-09 due:2026-11-30
2 2026-11-02 Book ski trip +winter t:2026-12-01
4 2026-11-04 Order holiday cards +winter t:2026-11-25
--
4 of 4 tasks shown

$ tasklane ls +winter
--
0 of 4 tasks shown (2 hidden until their t: date; --all shows them)
```

`ls --json` includes a `threshold` field. `due`, `projects`, `contexts` and
`report` still count deferred tasks, and the file itself is never changed.

### Hidden tasks

A task tagged `h:1` is a placeholder: it keeps a `+project` or `@context`
name in use (for `projects`, `contexts` and other todo.txt apps) without
cluttering your list. `ls` never shows it, not even with `--all`, unless you
pass `--hidden`; `due` and `report` leave it out. Any other value, such as
`h:0`, does not hide the task. Real output from a throwaway file on 2026-11-09:

```text
$ cat todo.txt
2026-11-01 Garden placeholder +garden @shed h:1
(A) 2026-11-02 Prune the roses +garden due:2026-11-12
2026-11-03 Plant tulip bulbs +garden @shed
2026-11-03 Call plumber +house @phone
2026-11-04 Someday: build a greenhouse +garden h:1

$ tasklane ls
2 (A) 2026-11-02 Prune the roses +garden due:2026-11-12
3 2026-11-03 Plant tulip bulbs +garden @shed
4 2026-11-03 Call plumber +house @phone
--
3 of 5 tasks shown (2 marked h:1; --hidden shows them)

$ tasklane ls --hidden
2 (A) 2026-11-02 Prune the roses +garden due:2026-11-12
1 2026-11-01 Garden placeholder +garden @shed h:1
3 2026-11-03 Plant tulip bulbs +garden @shed
4 2026-11-03 Call plumber +house @phone
5 2026-11-04 Someday: build a greenhouse +garden h:1
--
5 of 5 tasks shown

$ tasklane contexts
@phone
@shed

$ tasklane report
PROJECT   OPEN   DONE
+garden      2      0
+house       1      0
TOTAL        3      0
```

`ls --json` includes a `hidden` field (`true`/`false`). Hidden tasks can still
be completed, edited and archived by number like any other task. The file
itself is never changed by hiding.

### Shell completion

`tasklane completion SHELL` prints a completion script for commands, options,
`--color` values, the shell names of `completion` itself, and file paths after
`--file`. The script is generated from the CLI's own argument parser, so it
always matches the installed version. Load it from your shell's startup file:

```sh
# ~/.bashrc
eval "$(tasklane completion bash)"

# ~/.zshrc (after compinit)
eval "$(tasklane completion zsh)"

# fish
tasklane completion fish > ~/.config/fish/completions/tasklane.fish
```

```powershell
# $PROFILE
tasklane completion powershell | Out-String | Invoke-Expression
```

Real output on 2026-11-09, with `TASKLANE_FILE` pointing at a throwaway
`todo.txt` in a temporary folder. In bash, calling the completion function
the way the shell does on <kbd>Tab</kbd>:

```text
$ eval "$(tasklane completion bash)"
$ complete -p tasklane
complete -F _tasklane_complete tasklane
tasklane r<TAB>  ->  rm report
tasklane due --<TAB>  ->  --help --file --color --days --json
tasklane --file to<TAB>  ->  todo.txt
```

In Windows PowerShell 5.1, through `TabExpansion2` (what <kbd>Tab</kbd> uses):

```text
PS> TabExpansion2 'tasklane d'  ->  do depri due
PS> TabExpansion2 'tasklane ls --h'  ->  --help --hidden
PS> TabExpansion2 'tasklane --color '  ->  auto always never
PS> TabExpansion2 'tasklane completion '  ->  bash zsh fish powershell
```

#### Project and context names

In the task text of `add`, `edit` and `ls`, a word starting with `+` or `@`
completes from the names already used in your file. The script runs
`tasklane projects` or `tasklane contexts` for that, with the same `--file`
if the command line has one (otherwise `$TASKLANE_FILE` or `~/todo.txt`), so
it only reads the file and never changes it. Completed tasks count, so names
from finished work are still offered. Real output on 2026-11-09 from a
throwaway `todo.txt` made with:

```text
$ tasklane add "(A) Renew passport +travel @errands"
Added 1: (A) 2026-11-09 Renew passport +travel @errands
$ tasklane add "Pay rent +home @laptop"
Added 2: 2026-11-09 Pay rent +home @laptop
$ tasklane add "Book flights +travel @laptop"
Added 3: 2026-11-09 Book flights +travel @laptop
$ tasklane add "Fix the shelf +home +diy @garage"
Added 4: 2026-11-09 Fix the shelf +home +diy @garage
```

In bash:

```text
tasklane add Call the plumber +<TAB>  ->  +diy +home +travel
tasklane add Call the plumber +h<TAB>  ->  +home
tasklane ls @<TAB>  ->  @errands @garage @laptop
tasklane ls @la<TAB>  ->  laptop
tasklane --file other.txt ls +<TAB>  ->  +x
```

bash treats `@` as a word break, so for `@la` the reply is the rest of the
word (`laptop`) and the line reads `@laptop` after <kbd>Tab</kbd>. The last
line used an `other.txt` containing `Other projects: +x @y`.

In Windows PowerShell 5.1:

```text
PS> TabExpansion2 "tasklane ls +"  ->  +diy +home +travel
PS> TabExpansion2 "tasklane add Call the plumber +h"  ->  +home
PS> TabExpansion2 "tasklane ls @"  ->  '@errands' '@garage' '@laptop'
PS> TabExpansion2 "tasklane ls '@la"  ->  '@laptop'
```

A bare `@laptop` is splatting in PowerShell, so contexts are inserted in
single quotes; start the word with `'@` (or just `@`) to complete one. Names
are matched as plain text and inserted escaped (bash, zsh, fish) or quoted
(PowerShell), so odd characters in a synced file cannot run commands.

The bash, PowerShell and fish scripts are exercised by the test suite in real
shells (fish in CI on Ubuntu); the zsh script is syntax-checked there. Windows
PowerShell 5.1 does not call completers for a bare `--`, so type one letter
after it (`--h`). Task text and task numbers are not completed.

## todo.txt compatibility

* Lines are parsed per the spec: `x` + space marks completion, followed by an
  optional completion date and creation date; `(A)` to `(Z)` followed by a
  space is a priority only at the very start of an open task.
* `+project` and `@context` must start a word: `C++` and `bob@example.com`
  are not projects or contexts.
* `key:value` tags need a non-empty key and value with no further `:`, so URLs
  such as `https://example.com` or `http://host:8080` are not tags.
* Completing a prioritized task drops the `(A)` prefix as the spec asks and
  keeps it as a `pri:A` tag (a common convention) so `undo` can restore it.
* Nothing is lost: unchanged lines are written back byte-for-byte, including
  unusual spacing, blank lines, unknown tags and lines tasklane does not
  understand. Each line keeps its own line ending (LF, CRLF or CR), a UTF-8 BOM
  is kept, a missing final newline stays missing, and bytes that are not valid
  UTF-8 survive.
* Every write goes to a temporary file in the same folder, is flushed to disk,
  and then atomically replaces the original, so a crash never leaves a
  half-written `todo.txt`. `archive` writes `done.txt` before `todo.txt`: an
  interruption can at worst duplicate a task, never lose it.
* `rm` blanks the line instead of deleting it (like todo.sh's default) so line
  numbers stay stable; `archive` removes the blank lines.

## Development

```sh
git clone https://github.com/Chad9100/tasklane.git
cd tasklane
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Layout:

* `src/tasklane/todo.py` parses and formats one todo.txt line.
* `src/tasklane/storage.py` loads files losslessly and writes them atomically.
* `src/tasklane/recur.py` handles `rec:` rules and month arithmetic.
* `src/tasklane/query.py` does filtering, sorting, due views and reports.
* `src/tasklane/completion.py` generates shell completion scripts from the parser.
* `src/tasklane/cli.py` is the argparse front end; `main(argv, today=...)`
  accepts an injected date for tests.

The tests never touch your real `~/todo.txt`: every test points `--file` or
`TASKLANE_FILE` at a temporary folder and redirects `HOME`.

See [ROADMAP.md](ROADMAP.md) for planned work. Licensed under the
[MIT License](LICENSE).
