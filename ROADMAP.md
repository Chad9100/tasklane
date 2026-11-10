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

- [x] Completion scripts for bash, zsh, fish and PowerShell (2 h)
- [x] Complete `+project` and `@context` names from the current file (1 h)

## v0.4 - sync-friendly merge of concurrent edits (about 6 h)

- [x] Detect that the file changed on disk between load and save (content hash, mtime reported) and refuse to overwrite it (1 h)
- [x] Three-way merge of changes to different lines on save, with moved task numbers reported (1.5 h)
- [x] Merge two edits of the same task that touch different fields, e.g. one side completes it and the other changes its priority (1.5 h)
- [x] Clear conflict report: the clashing fields plus the lines as they were, as tasklane wanted them and as they are on disk (1 h; first half of a 2 h item, split)
- [x] `--force` escape hatch (keeping a backup of the other version) (0.5 h; first half of the 1 h item, split)
- [x] Tests with simulated Dropbox/Syncthing edits: conflicted-copy files, touch-only rewrites, burst writes (0.5 h; second half)
- [x] `tasklane conflicts [--merge]`: find Dropbox/Syncthing conflicted copies and append their new tasks (1 h)

## v0.5 - calendar export (about 3 h)

- [x] `tasklane export --ics` writing VTODO entries with due dates and priorities (2 h)
- [x] Map recurring tasks to RRULE where possible (1 h)

## v0.6 - interactive TUI (about 8 h)

- [x] Read-only full-screen list built on `curses` with live filtering and an injectable screen for tests (1.5 h; first part of the 4 h item, split)
- [ ] Windows `windows-curses` extra in `pyproject.toml` and colors in the list (1 h; second part)
- [x] Keyboard actions: add, do, undo, priority, saved through the merge path (1.5 h; first part of the 3 h item, split)
- [ ] Keyboard actions: edit a task in place, remove, archive (1.5 h; second part)
- [ ] Respect `NO_COLOR` for list colors and test on real terminals (0.5 h)

## v1.0 - PyPI release (about 2 h)

- [x] Trusted-publishing release workflow and versioned changelog (1 h)
- [ ] Configure the pending publisher on pypi.org, tag and publish the first release (0.5 h; first half of the 1 h item, split)
- [ ] `pipx install tasklane` instructions and final docs pass (0.5 h; second half)

**Total planned after v0.1: about 25 hours.**
