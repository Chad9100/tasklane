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
