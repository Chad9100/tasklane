import os

from tasklane.cli import main
from tasklane.copies import find_copies, new_lines
from tasklane.storage import TodoFile
from tasklane.todo import parse_task

DROPBOX = "todo (conflicted copy 2026-11-10).txt"
DROPBOX_NAMED = "todo (Chad's laptop's conflicted copy 2026-11-10) (1).txt"
SYNCTHING = "todo.sync-conflict-20261110-123456-ABCDEFG.txt"


def run(todo, *args, capsys):
    code = main(["--file", str(todo), *args], today=None)
    out, err = capsys.readouterr()
    return code, out, err


def test_find_copies_recognises_sync_services_only(tmp_path):
    todo = tmp_path / "todo.txt"
    todo.write_text("a\n")
    for name in (DROPBOX, DROPBOX_NAMED, SYNCTHING, "done.txt", "todo-notes.txt",
                 "other (conflicted copy 2026-11-10).txt", "todo (conflicted copy).md"):
        (tmp_path / name).write_text("x\n")
    assert sorted(p.name for p in find_copies(todo)) == sorted([DROPBOX, DROPBOX_NAMED, SYNCTHING])


def test_new_lines_ignores_endings_blanks_and_repeats():
    assert new_lines(b"a\r\nb\r\n", b"\xef\xbb\xbfb\nc\n\nc\nd") == ["c", "d"]


def test_conflicts_lists_without_changing_anything(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\n")
    copy = tmp_path / DROPBOX
    copy.write_bytes(b"one\ntwo +home\n")
    code, out, _ = run(todo, "conflicts", capsys=capsys)
    assert code == 0 and "+ two +home" in out and "--merge" in out
    assert todo.read_bytes() == b"one\n" and copy.exists()


def test_conflicts_none_found(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\n")
    code, out, _ = run(todo, "conflicts", capsys=capsys)
    assert code == 0 and out.startswith("No conflicted copies")


def test_merge_appends_missing_tasks_from_every_copy(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / DROPBOX).write_bytes(b"one\r\nthree\r\n")
    (tmp_path / SYNCTHING).write_bytes(b"three\r\nfour\r\n")
    code, out, _ = run(todo, "conflicts", "--merge", capsys=capsys)
    assert code == 0 and "Appended 2 task(s) from 2 copy file(s)" in out
    assert todo.read_bytes() == b"one\r\ntwo\r\nthree\r\nfour\r\n"
    assert find_copies(todo) == []
    assert (tmp_path / (DROPBOX + ".merged")).exists()
    assert (tmp_path / (SYNCTHING + ".merged")).exists()


def test_merge_with_nothing_new_leaves_file_alone_but_sets_copy_aside(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\n")
    (tmp_path / DROPBOX).write_bytes(b"one\n")
    before = todo.stat().st_mtime_ns
    code, _, _ = run(todo, "conflicts", "--merge", capsys=capsys)
    assert code == 0 and todo.read_bytes() == b"one\n" and todo.stat().st_mtime_ns == before
    assert find_copies(todo) == []


def test_merge_creates_missing_todo_file(tmp_path, capsys):
    todo = tmp_path / "todo.txt"
    (tmp_path / DROPBOX).write_bytes(b"only here\n")
    code, _, _ = run(todo, "conflicts", "--merge", capsys=capsys)
    assert code == 0 and todo.read_bytes() == b"only here\n"


# -- simulated sync client behaviour against TodoFile --------------------------
def test_touch_only_rewrite_is_not_a_change(tmp_path):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\ntwo\n")
    tf = TodoFile.load(todo)
    tf.append(parse_task("three"))
    st = todo.stat()
    todo.write_bytes(b"one\ntwo\n")  # same bytes, rewritten by a sync client
    os.utime(todo, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    tf.save()
    assert not tf.merged and todo.read_bytes() == b"one\ntwo\nthree\n"


def test_burst_of_appends_by_a_sync_client_is_all_kept(tmp_path):
    todo = tmp_path / "todo.txt"
    todo.write_bytes(b"one\n")
    tf = TodoFile.load(todo)
    n = tf.append(parse_task("mine"))
    for i in range(5):  # the other side writes five times in a row
        with open(todo, "ab") as handle:
            handle.write(f"theirs {i}\n".encode())
    tf.save()
    lines = todo.read_text().splitlines()
    assert lines[0] == "one" and sorted(lines[1:]) == sorted(["mine"] + [f"theirs {i}" for i in range(5)])
    assert tf.merged and tf.text(tf.number(n)) == "mine"
