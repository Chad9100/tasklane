# Changelog

All notable changes to tasklane are listed here, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/) and versions follow
[Semantic Versioning](https://semver.org/).

Every release needs a `## [X.Y.Z]` heading here; a test checks that the heading
for the version in `pyproject.toml` exists, and the release workflow publishes
that section as the release notes.

## [0.1.0] - unreleased

First release.

### Added

- Lossless todo.txt parsing and formatting; atomic writes that keep line
  endings, BOM and unknown lines.
- Commands `add`, `ls`, `do`, `undo`, `pri`, `depri`, `edit`, `rm`, `archive`,
  `due`, `projects`, `contexts`, `report`, `conflicts`, `export --ics`, with
  `--json` output.
- Recurring tasks (`rec:`), threshold dates (`t:`) and hidden tasks (`h:1`).
- Shell completion for bash, zsh, fish and PowerShell, including project and
  context names.
- `tasklane tui`: a read-only full-screen task list with live filtering
  (needs `curses`; `windows-curses` on Windows).
- Merging of edits made by other programs on save, a conflict report, `--force`
  with a backup of the other version, and folding in Dropbox/Syncthing
  conflicted copies.
