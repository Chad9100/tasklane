import codecs
import os

import pytest

from tasklane import storage
from tasklane.storage import TaskIndexError, TodoFile, atomic_write
from tasklane.todo import parse_task


def test_missing_file_is_empty(tmp_path):
    tf = TodoFile.load(tmp_path / "nope.txt")
    assert len(tf) == 0 and tf.tasks() == []


def test_unchanged_file_round_trips_byte_for_byte(tmp_path):
    data = (
        b"(A) 2026-11-01 Task one  with  double spaces\r\n"
        b"\r\n"
        b"   \n"
        b"x  weird completion spacing\r"
        b"Caf\xc3\xa9 \xff\xfe not utf8\n"
        b"last line without newline"
    )
    path = tmp_path / "todo.txt"
    path.write_bytes(data)
    tf = TodoFile.load(path)
    tf.save()
    assert path.read_bytes() == data


def test_blank_and_whitespace_lines_are_not_tasks_but_keep_numbers(tmp_path):
    tf = TodoFile.from_bytes(tmp_path / "t.txt", b"a\n\nb\n")
    assert [n for n, _ in tf.tasks()] == [1, 3]
    with pytest.raises(TaskIndexError):
        tf.get(2)


def test_crlf_preserved_after_modification(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    tf = TodoFile.load(path)
    task = tf.get(1)
    task.priority = "A"
    tf.set(1, task)
    tf.append(parse_task("three"))
    tf.save()
    assert path.read_bytes() == b"(A) one\r\ntwo\r\nthree\r\n"


def test_append_after_missing_final_newline(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\r\ntwo")
    tf = TodoFile.load(path)
    tf.append(parse_task("three"))
    tf.save()
    assert path.read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_bom_is_stripped_for_parsing_and_restored(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(codecs.BOM_UTF8 + b"(A) first +p\n")
    tf = TodoFile.load(path)
    assert tf.get(1).priority == "A"
    tf.append(parse_task("second"))
    tf.save()
    assert path.read_bytes() == codecs.BOM_UTF8 + b"(A) first +p\nsecond\n"


def test_bad_indexes_raise(tmp_path):
    tf = TodoFile.from_bytes(tmp_path / "t.txt", b"a\n")
    for n in (0, -1, 2, 99):
        with pytest.raises(TaskIndexError):
            tf.get(n)


def test_blank_keeps_later_line_numbers(tmp_path):
    tf = TodoFile.from_bytes(tmp_path / "t.txt", b"a\nb\nc\n")
    tf.blank(2)
    assert [(n, t.text) for n, t in tf.tasks()] == [(1, "a"), (3, "c")]
    assert tf.to_bytes() == b"a\n\nc\n"


def test_remove_done_returns_lines_and_drops_blanks(tmp_path):
    tf = TodoFile.from_bytes(tmp_path / "t.txt", b"a\nx 2026-11-09 b\n\nc\nx d\n")
    assert tf.remove_done() == ["x 2026-11-09 b", "x d"]
    assert tf.to_bytes() == b"a\nc\n"


def test_atomic_write_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    tmp_path = tmp_path / "data"
    tmp_path.mkdir()
    path = tmp_path / "todo.txt"
    path.write_bytes(b"original\n")

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(path, b"new\n")
    assert path.read_bytes() == b"original\n"
    assert os.listdir(tmp_path) == ["todo.txt"]


def test_atomic_write_creates_and_replaces(tmp_path):
    tmp_path = tmp_path / "data"
    tmp_path.mkdir()
    path = tmp_path / "todo.txt"
    atomic_write(path, b"one\n")
    atomic_write(path, b"two\n")
    assert path.read_bytes() == b"two\n"
    assert os.listdir(tmp_path) == ["todo.txt"]


def test_done_path_is_beside_todo(tmp_path):
    assert storage.done_path_for(tmp_path / "work.txt") == tmp_path / "done.txt"


# -- detecting edits made by other programs between load and save ------------
def test_save_refuses_when_another_program_changed_the_same_line(tmp_path):
    tmp_path = tmp_path / "data"
    tmp_path.mkdir()
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\ntwo\n")
    tf = TodoFile.load(path)
    tf.set(2, parse_task("(A) two"))
    path.write_bytes(b"one\n(B) two, edited in an editor\n")  # a different priority
    with pytest.raises(storage.FileChangedError, match="todo.txt was changed on disk") as info:
        tf.save()
    assert "in the same lines" in str(info.value)
    [conflict] = info.value.conflicts
    assert (conflict.base, conflict.ours, conflict.theirs) == (
        [b"two\n"], [b"(A) two\n"], [b"(B) two, edited in an editor\n"])
    assert path.read_bytes() == b"one\n(B) two, edited in an editor\n"
    assert os.listdir(tmp_path) == ["todo.txt"]  # no stray temp file


def test_same_size_edit_with_restored_mtime_is_still_detected(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"(A) one\n")
    st = os.stat(path)
    tf = TodoFile.load(path)
    tf.set(1, parse_task("(C) one"))
    path.write_bytes(b"(B) one\n")  # same length...
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # ...and same mtime
    with pytest.raises(storage.FileChangedError):
        tf.save()


def test_touch_without_content_change_is_not_a_conflict(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\n")
    tf = TodoFile.load(path)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    tf.append(parse_task("two"))
    tf.save()
    assert path.read_bytes() == b"one\ntwo\n"


def test_deleted_file_is_not_silently_recreated(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\n")
    tf = TodoFile.load(path)
    path.unlink()
    with pytest.raises(storage.FileChangedError, match="was deleted"):
        tf.save()
    assert not path.exists()


def test_file_created_by_someone_else_after_loading_a_missing_one(tmp_path):
    path = tmp_path / "todo.txt"
    tf = TodoFile.load(path)
    tf.append(parse_task("mine"))
    path.write_bytes(b"theirs\n")
    with pytest.raises(storage.FileChangedError, match="was created by another program"):
        tf.save()
    assert path.read_bytes() == b"theirs\n"


def test_empty_file_appearing_or_vanishing_is_not_a_conflict(tmp_path):
    path = tmp_path / "todo.txt"
    tf = TodoFile.load(path)
    path.write_bytes(b"")
    tf.append(parse_task("first"))
    tf.save()
    assert path.read_bytes() == b"first\n"


def test_second_save_after_own_save_is_allowed(tmp_path):
    path = tmp_path / "todo.txt"
    tf = TodoFile.load(path)
    tf.append(parse_task("a"))
    tf.save()
    tf.append(parse_task("b"))
    tf.save()
    assert path.read_bytes() == b"a\nb\n"
    path.write_bytes(b"a\nB\n")
    tf.set(2, parse_task("b2"))
    with pytest.raises(storage.FileChangedError):  # the base moved to our own save
        tf.save()


def test_from_bytes_files_are_not_checked(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"something else\n")
    tf = TodoFile.from_bytes(path, b"a\n")
    tf.save()
    assert path.read_bytes() == b"a\n"
