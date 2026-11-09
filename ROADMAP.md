# Roadmap

Estimates are focused working hours, including tests and docs.

## v0.1 - first release (done)

- [x] Lossless todo.txt parsing and formatting (priority, completion and creation dates, projects, contexts, tags)
- [x] Atomic writes that preserve line endings, BOM and unknown lines
- [x] `add`, `ls` with filters, `do`, `undo`, `pri`, `depri`, `edit`, `rm --yes`, `archive`
- [x] `due`, `projects`, `contexts`, `report`, `--json`
- [x] Recurring tasks (`rec:3d`, `rec:1w`, `rec:1m`, strict `rec:+1w`) with month-end clamping
- [x] Color on terminals, `NO_COLOR`, `--color`
- [x] Test suite and CI on Ubuntu and Windows (Python 3.10, 3.12, 3.13)

## v0.2 - hidden and threshold dates (about 3 h)

- [x] `t:YYYY-MM-DD` threshold dates: hide tasks from `ls` until that day, `--all` shows them (1.5 h)
- [x] Shift `t:` together with `due:` when a recurring task repeats (0.5 h)
- [x] `h:1` hidden tasks, plus `ls --hidden` (1 h)

## v0.3 - shell completions (about 3 h)

- [ ] Completion scripts for bash, zsh, fish and PowerShell (2 h)
- [ ] Complete `+project` and `@context` names from the current file (1 h)

## v0.4 - sync-friendly merge of concurrent edits (about 6 h)

- [ ] Detect that the file changed on disk between load and save (mtime + content hash) (1 h)
- [ ] Three-way merge of line-level changes instead of overwriting (3 h)
- [ ] Clear conflict report and a `--force` escape hatch; tests with simulated Dropbox/Syncthing edits (2 h)

## v0.5 - calendar export (about 3 h)

- [ ] `tasklane export --ics` writing VTODO entries with due dates and priorities (2 h)
- [ ] Map recurring tasks to RRULE where possible (1 h)

## v0.6 - interactive TUI (about 8 h)

- [ ] Full-screen list built on `curses` (Windows via `windows-curses` extra) with live filtering (4 h)
- [ ] Keyboard actions: add, do, undo, priority, edit, archive (3 h)
- [ ] Respect `NO_COLOR` and small terminals (1 h)

## v1.0 - PyPI release (about 2 h)

- [ ] Trusted-publishing release workflow and versioned changelog (1 h)
- [ ] Publish to PyPI, `pipx install tasklane` instructions, final docs pass (1 h)

**Total planned after v0.1: about 25 hours.**
