from __future__ import annotations

import codecs

import pytest

from tasklane import storage
from tasklane.cli import main
from tasklane.merge import join_merged, merge3, merge_bytes, merge_task_line
from tasklane.storage import TodoFile
from tasklane.todo import parse_task


# -- merge3 on plain sequences ----------------------------------------------
def test_changes_to_different_lines_are_combined():
    base = ["a", "b", "c", "d"]
    result = merge3(base, ["A", "b", "c", "d"], ["a", "b", "c", "D"])
    assert result.clean and result.lines == ["A", "b", "c", "D"]


def test_neighbouring_lines_do_not_conflict():
    result = merge3(["a", "b"], ["A", "b"], ["a", "B"])
    assert result.clean and result.lines == ["A", "B"]


def test_both_appending_keeps_ours_first():
    result = merge3(["a"], ["a", "mine"], ["a", "theirs"])
    assert result.clean and result.lines == ["a", "mine", "theirs"]
    assert result.ours_at == [0, 1]


def test_identical_changes_are_taken_once():
    result = merge3(["a", "b"], ["a", "B", "new"], ["a", "B", "new"])
    assert result.clean and result.lines == ["a", "B", "new"]


def test_same_line_changed_differently_is_a_conflict():
    result = merge3(["a", "b", "c"], ["a", "mine", "c"], ["a", "theirs", "c"])
    assert not result.clean
    [conflict] = result.conflicts
    assert (conflict.start, conflict.end) == (1, 2)
    assert (conflict.base, conflict.ours, conflict.theirs) == (["b"], ["mine"], ["theirs"])


def test_insertion_next_to_a_change_is_not_a_conflict():
    result = merge3(["a", "b"], ["b"], ["new", "a", "b"])
    assert result.clean and result.lines == ["new", "b"]
    result = merge3(["a", "b"], ["A", "b"], ["a", "new", "b"])
    assert result.clean and result.lines == ["A", "new", "b"]


def test_their_deletion_of_a_line_we_changed_is_a_conflict():
    result = merge3(["a", "b"], ["a", "B"], ["a"])
    assert not result.clean


def test_ours_at_follows_lines_moved_by_their_insertions_and_deletions():
    base = ["a", "b", "c"]
    ours = ["a", "b", "C"]
    theirs = ["new", "a", "c"]  # inserted at the top, deleted "b"
    result = merge3(base, ours, theirs)
    assert result.clean and result.lines == ["new", "a", "C"]
    assert result.ours_at == [1, None, 2]


# -- merge_task_line: one task, field by field ------------------------------
def test_completing_and_reprioritizing_the_same_task_merge():
    base = "(B) 2026-11-01 Pay rent"
    ours = "x 2026-11-10 2026-11-01 Pay rent pri:B"  # tasklane completed it
    theirs = "(A) 2026-11-01 Pay rent"                # the phone raised it
    assert merge_task_line(base, ours, theirs) == "x 2026-11-10 2026-11-01 Pay rent pri:A"
    # The other way round: the priority lands on the done task's pri: tag too.
    assert merge_task_line(base, theirs, ours) == "x 2026-11-10 2026-11-01 Pay rent pri:A"


def test_undo_on_one_side_keeps_the_other_sides_priority():
    base = "x 2026-11-10 Pay rent pri:B"
    assert merge_task_line(base, "(B) Pay rent", "x 2026-11-10 Pay rent pri:A") == "(A) Pay rent"


def test_words_changed_in_different_places_are_kept():
    assert merge_task_line("Call Bob", "Call Bob +work", "(A) Call Bob @phone") == (
        "(A) Call Bob +work @phone"
    )
    assert merge_task_line("Pay rent", "Pay the rent", "Pay rent now") == "Pay the rent now"
    # Unusual spacing survives.
    assert merge_task_line("Pay  rent", "(A) Pay  rent", "Pay  rent now") == "(A) Pay  rent now"
    assert merge_task_line(
        "2026-11-01 Pay rent", "2026-11-01 Pay rent due:2026-11-20", "x 2026-11-10 2026-11-01 Pay rent"
    ) == "x 2026-11-10 2026-11-01 Pay rent due:2026-11-20"


@pytest.mark.parametrize(
    "base, ours, theirs",
    [
        ("Pay rent", "(A) Pay rent", "(B) Pay rent"),            # same field
        ("Pay rent", "Pay big rent", "Pay small rent"),          # same place in the text
        ("Pay rent", "", "(A) Pay rent"),                        # removed vs edited
        ("x 2026-11-09 Pay rent", "x 2026-11-10 Pay rent", "x 2026-11-08 Pay rent"),
    ],
)
def test_same_field_changes_do_not_merge(base, ours, theirs):
    assert merge_task_line(base, ours, theirs) is None


def test_merge3_resolver_is_only_asked_about_equal_length_regions():
    calls = []

    def resolve(b, o, t):
        calls.append((b, o, t))
        return o + t

    result = merge3(["a", "b"], ["A", "B"], ["a", "b2"], resolve)
    assert result.clean and result.lines == ["A", "Bb2"] and calls == [("b", "B", "b2")]
    result = merge3(["a"], ["A", "extra"], ["a2"], resolve)
    assert not result.clean


# -- merge_bytes: whole files ------------------------------------------------
def test_line_endings_travel_with_their_lines():
    base = b"a\r\nb\r\n"
    result = merge_bytes(base, b"A\r\nb\r\n", b"a\r\nb\r\nc\n")
    assert join_merged(result) == b"A\r\nb\r\nc\n"


def test_missing_final_newline_is_handled_as_a_file_property():
    base = b"a\nb"
    ours = b"a\nb\nmine\n"   # tasklane appended, adding the newline
    theirs = b"A\nb"         # the other program left the end alone
    assert join_merged(merge_bytes(base, ours, theirs)) == b"A\nb\nmine\n"
    # Both sides unterminated: stays unterminated.
    assert join_merged(merge_bytes(b"a\nb", b"a\nB", b"A\nb")) == b"A\nB"


def test_bom_is_kept_or_changed_like_any_whole_file_property():
    bom = codecs.BOM_UTF8
    assert join_merged(merge_bytes(bom + b"a\n", bom + b"A\n", bom + b"a\nb\n")) == bom + b"A\nb\n"
    assert join_merged(merge_bytes(b"a\n", b"A\n", bom + b"a\n")) == bom + b"A\n"


# -- TodoFile.save -----------------------------------------------------------
def test_save_merges_an_append_from_a_sync_client(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\ntwo\n")
    tf = TodoFile.load(path)
    tf.set(1, parse_task("(A) one"))
    n = tf.append(parse_task("three"))
    path.write_bytes(b"one\ntwo\nfrom the phone\n")
    tf.save()
    assert path.read_bytes() == b"(A) one\ntwo\nthree\nfrom the phone\n"
    assert tf.merged and tf.number(n) == 3
    assert [t.text for _, t in tf.tasks()] == ["one", "two", "three", "from the phone"]
    # The merged result is the new base: saving again changes nothing.
    tf.save()
    assert path.read_bytes() == b"(A) one\ntwo\nthree\nfrom the phone\n"
    assert not tf.merged


def test_save_renumbers_lines_moved_by_the_other_program(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\ntwo\n")
    tf = TodoFile.load(path)
    tf.set(2, parse_task("x two"))
    path.write_bytes(b"zero\none\ntwo\n")
    tf.save()
    assert path.read_bytes() == b"zero\none\nx two\n"
    assert tf.renumbered == {1: 2, 2: 3}
    assert tf.number(2) == 3 and tf.text(3) == "x two"


def test_conflicting_save_writes_nothing(tmp_path):
    path = tmp_path / "todo.txt"
    path.write_bytes(b"one\n")
    tf = TodoFile.load(path)
    tf.set(1, parse_task("(A) one"))
    path.write_bytes(b"(B) one\n")  # both set the priority
    with pytest.raises(storage.FileChangedError, match="in the same lines"):
        tf.save()
    assert path.read_bytes() == b"(B) one\n"


# -- command line ------------------------------------------------------------
@pytest.fixture
def todo_file(tmp_path, monkeypatch):
    from tasklane import cli

    path = tmp_path / "todo.txt"
    path.write_bytes(b"2026-11-01 Write report\n2026-11-02 Buy milk\n")
    real_load = cli.Context.load

    def load_then_sync(self):
        tf = real_load(self)
        # A sync client adds a task at the top while the command runs.
        self.path.write_bytes(b"2026-11-09 From the phone\n" + self.path.read_bytes())
        return tf

    monkeypatch.setattr(cli.Context, "load", load_then_sync)
    return path


def test_cli_merges_and_prints_the_new_numbers(todo_file, capsys):
    code = main(["--file", str(todo_file), "do", "2"])
    out, err = capsys.readouterr()
    assert code == 0
    assert out.startswith("Completed 3: x ")
    assert "merged with changes another program made to todo.txt" in err
    lines = todo_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "2026-11-09 From the phone"
    assert lines[2].startswith("x ") and lines[2].endswith("Buy milk")


def test_cli_add_after_merge_reports_the_line_it_landed_on(todo_file, capsys):
    code = main(["--file", str(todo_file), "add", "New task"])
    out, _ = capsys.readouterr()
    assert code == 0 and out.startswith("Added 4: ") and out.rstrip().endswith("New task")


def test_cli_archive_merges_before_writing_done_txt(todo_file, capsys):
    todo_file.write_bytes(b"x 2026-11-08 Old\n2026-11-02 Buy milk\n")
    code = main(["--file", str(todo_file), "archive"])
    capsys.readouterr()
    assert code == 0
    assert todo_file.read_bytes() == b"2026-11-09 From the phone\n2026-11-02 Buy milk\n"
    assert (todo_file.parent / "done.txt").read_bytes() == b"x 2026-11-08 Old\n"


def test_merge_bytes_merges_fields_and_keeps_our_line_ending():
    base = b"(B) Pay rent\r\nCall Bob\r\n"
    ours = b"x 2026-11-10 Pay rent pri:B\r\nCall Bob\r\n"
    theirs = b"(A) Pay rent\nCall Bob\r\n"
    result = merge_bytes(base, ours, theirs)
    assert result.clean and join_merged(result) == b"x 2026-11-10 Pay rent pri:A\r\nCall Bob\r\n"
    # Bytes that are not UTF-8 are never merged field by field.
    assert not merge_bytes(b"\xff task\n", b"(A) \xff task\n", b"\xff task +x\n").clean


def test_cli_do_merges_with_a_priority_change_from_the_phone(tmp_path, monkeypatch, capsys):
    from tasklane import cli

    path = tmp_path / "todo.txt"
    path.write_bytes(b"(C) 2026-11-01 Write report\n(B) 2026-11-02 Buy milk\n")
    real_load = cli.Context.load

    def load_then_sync(self):
        tf = real_load(self)
        self.path.write_bytes(b"(C) 2026-11-01 Write report\n(A) 2026-11-02 Buy milk +home\n")
        return tf

    monkeypatch.setattr(cli.Context, "load", load_then_sync)
    code = main(["--file", str(path), "do", "2"])
    _, err = capsys.readouterr()
    assert code == 0 and "merged with changes" in err
    line = path.read_text(encoding="utf-8").splitlines()[1]
    assert line.startswith("x ") and line.endswith(" 2026-11-02 Buy milk +home pri:A")
    # undo brings back the priority the phone set.
    monkeypatch.setattr(cli.Context, "load", real_load)
    assert main(["--file", str(path), "undo", "2"]) == 0
    assert path.read_text(encoding="utf-8").splitlines()[1] == "(A) 2026-11-02 Buy milk +home"
