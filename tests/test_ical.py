from datetime import date
from pathlib import Path

import pytest

from tasklane import ical
from tasklane.cli import main
from tasklane.todo import parse_task

# Defined here rather than imported from conftest.py, which is not an
# importable module when CI runs plain `pytest`.
TODAY = date(2026, 11, 9)


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def unfold(data: str) -> list[str]:
    assert data.endswith("\r\n")
    return data.replace("\r\n ", "").split("\r\n")[:-1]


def todos(data: str) -> list[dict[str, str]]:
    """Each VTODO as {property name with parameters: value}."""
    result: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfold(data):
        if line == "BEGIN:VTODO":
            current = {}
        elif line == "END:VTODO":
            result.append(current)
            current = None
        elif current is not None:
            name, _, value = line.partition(":")
            current[name] = value
    return result


SAMPLE = """(A) 2026-11-01 Renew passport +travel @errands due:2026-11-12
2026-11-02 Book ski trip, cheap; +winter t:2026-12-01 due:2026-12-20

x 2026-11-08 2026-11-01 Pay rent +home pri:B
2026-11-03 Garden placeholder +home h:1
(K) Someday learn Rust t:2027-01-01
"""


@pytest.fixture
def todo(tmp_path):
    path = tmp_path / "todo.txt"
    write(path, SAMPLE)
    return path


def export(capsysbinary, todo, *args):
    code = main(["--file", str(todo), "export", "--ics", *args], today=TODAY)
    out, err = capsysbinary.readouterr()
    return code, out.decode("utf-8"), err.decode("utf-8")


def test_open_task_maps_to_vtodo(capsysbinary, todo):
    code, out, _ = export(capsysbinary, todo)
    assert code == 0
    lines = unfold(out)
    assert lines[:4] == ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{ical.PRODID}", "CALSCALE:GREGORIAN"]
    assert lines[-1] == "END:VCALENDAR"
    first = todos(out)[0]
    assert first == {
        "UID": first["UID"],
        "DTSTAMP": "20261109T000000Z",
        "CREATED": "20261101T000000Z",
        "SUMMARY": "Renew passport +travel @errands",
        "DUE;VALUE=DATE": "20261112",
        "PRIORITY": "1",
        "CATEGORIES": "travel,errands",
        "STATUS": "NEEDS-ACTION",
    }
    assert first["UID"].endswith("@tasklane")


def test_default_skips_done_and_hidden_but_keeps_deferred(capsysbinary, todo):
    _, out, _ = export(capsysbinary, todo)
    summaries = [t["SUMMARY"] for t in todos(out)]
    assert summaries == [
        "Renew passport +travel @errands",
        "Book ski trip\\, cheap\\; +winter",
        "Someday learn Rust",
    ]


def test_threshold_becomes_dtstart_and_text_is_escaped(capsysbinary, todo):
    _, out, _ = export(capsysbinary, todo)
    ski = todos(out)[1]
    assert ski["DTSTART;VALUE=DATE"] == "20261201"
    assert ski["DUE;VALUE=DATE"] == "20261220"
    assert "PRIORITY" not in ski
    rust = todos(out)[2]
    assert rust["PRIORITY"] == "9"  # (K) is past (I)
    assert rust["DTSTART;VALUE=DATE"] == "20270101"
    assert "CREATED" not in rust and "DUE;VALUE=DATE" not in rust


def test_all_and_hidden_include_completed_and_h1(capsysbinary, todo):
    _, out, _ = export(capsysbinary, todo, "--all", "--hidden", "+home")
    done, hidden = todos(out)
    assert done["SUMMARY"] == "Pay rent +home"  # pri:B moved into PRIORITY
    assert done["PRIORITY"] == "2"
    assert done["STATUS"] == "COMPLETED"
    assert done["COMPLETED"] == "20261108T000000Z"
    assert hidden["SUMMARY"] == "Garden placeholder +home h:1"
    assert hidden["STATUS"] == "NEEDS-ACTION"


def test_filters_like_ls_including_exclusions(capsysbinary, todo):
    _, out, _ = export(capsysbinary, todo, "-winter", "-rust")
    assert [t["SUMMARY"] for t in todos(out)] == ["Renew passport +travel @errands"]


def test_uid_survives_renumbering_and_priority_changes():
    a = parse_task("(A) 2026-11-01 Renew passport +travel due:2026-11-12")
    b = parse_task("(C) 2026-11-01 Renew passport +travel due:2026-11-30")
    c = parse_task("2026-11-01 Renew driving licence +travel")
    assert ical.uid(a) == ical.uid(b)
    assert ical.uid(a) != ical.uid(c)


def test_threshold_after_due_is_not_exported_as_dtstart():
    lines = ical.vtodo(parse_task("Odd one t:2026-12-01 due:2026-11-01"), TODAY)
    assert "DUE;VALUE=DATE:20261101" in lines
    assert not any(line.startswith("DTSTART") for line in lines)


def test_long_lines_fold_at_75_octets_without_splitting_utf8():
    text = "Plan the trip to Zürich and München " * 4
    data = ical.calendar([parse_task(text)], TODAY)
    for line in data.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert f"SUMMARY:{text.strip()}" in unfold(data)


def test_escape_text():
    assert ical.escape_text("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"


def test_output_file_is_written_with_crlf(capsysbinary, todo, tmp_path):
    target = tmp_path / "tasks.ics"
    code, out, err = export(capsysbinary, todo, "-o", str(target))
    assert code == 0 and out == ""
    assert err.strip() == f"Exported 3 task(s) to {target}"
    data = target.read_bytes()
    assert data.startswith(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert todo.read_text(encoding="utf-8") == SAMPLE  # the todo file is untouched


def test_format_flag_is_required(capsys, todo):
    with pytest.raises(SystemExit) as exc:
        main(["--file", str(todo), "export"], today=TODAY)
    assert exc.value.code == 2
    assert "--ics" in capsys.readouterr().err


def test_missing_file_exports_an_empty_calendar(capsysbinary, tmp_path):
    code, out, _ = export(capsysbinary, tmp_path / "none.txt")
    assert code == 0
    assert unfold(out) == ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{ical.PRODID}",
                           "CALSCALE:GREGORIAN", "END:VCALENDAR"]
    assert not (tmp_path / "none.txt").exists()


def rec_lines(text: str) -> list[str]:
    return ical.vtodo(parse_task(text), TODAY)


def test_strict_weekly_task_gets_rrule_anchored_at_due():
    lines = rec_lines("(B) 2026-11-01 Water filter +home due:2026-11-12 rec:+1w")
    assert "SUMMARY:Water filter +home" in lines  # rec: is now the RRULE
    assert "DTSTART;VALUE=DATE:20261112" in lines
    assert "DUE;VALUE=DATE:20261112" in lines
    assert "RRULE:FREQ=WEEKLY" in lines
    assert lines.index("DTSTART;VALUE=DATE:20261112") < lines.index("RRULE:FREQ=WEEKLY")


@pytest.mark.parametrize(
    ("rec", "expected"),
    [
        ("+3d", "FREQ=DAILY;INTERVAL=3"),
        ("+2w", "FREQ=WEEKLY;INTERVAL=2"),
        ("+1m", "FREQ=MONTHLY"),
        ("+6M", "FREQ=MONTHLY;INTERVAL=6"),
        ("+1y", "FREQ=YEARLY"),
    ],
)
def test_rrule_frequencies(rec, expected):
    assert ical.rrule(parse_task(f"Task due:2026-11-28 rec:{rec}")) == expected


def test_threshold_stays_dtstart_for_day_and_week_rules():
    lines = rec_lines("Timesheet t:2026-11-07 due:2026-11-09 rec:+1w")
    assert "DTSTART;VALUE=DATE:20261107" in lines
    assert "RRULE:FREQ=WEEKLY" in lines
    assert sum(line.startswith("DTSTART") for line in lines) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Water plants due:2026-11-12 rec:1w",  # counted from completion day
        "Water plants rec:+1w",  # nothing to anchor the series
        "Pay rent due:2026-01-31 rec:+1m",  # Feb 28, then Mar 28: clamping drifts
        "Birthday due:2028-02-29 rec:+1y",
        "Report t:2026-11-25 due:2026-12-05 rec:+1m",  # day gap vs month step
        "Broken due:2026-11-12 rec:+0w",
        "x 2026-11-08 Paid due:2026-11-12 rec:+1w",
    ],
)
def test_unmappable_recurrences_export_the_current_occurrence(text):
    task = parse_task(text)
    assert ical.rrule(task) is None
    lines = ical.vtodo(task, TODAY)
    assert not any(line.startswith("RRULE") for line in lines)
    assert any(line.startswith("SUMMARY:") and "rec:" in line for line in lines)


def test_month_rule_with_threshold_on_due_day_is_mapped():
    assert ical.rrule(parse_task("Rent t:2026-11-28 due:2026-11-28 rec:+1m")) == "FREQ=MONTHLY"


def test_series_uid_survives_completing_an_occurrence(capsysbinary, tmp_path):
    path = tmp_path / "todo.txt"
    write(path, "2026-11-01 Water filter +home due:2026-11-09 rec:+1w\n")
    _, before, _ = export(capsysbinary, path)
    assert main(["--file", str(path), "do", "1"], today=TODAY) == 0
    capsysbinary.readouterr()
    _, after, _ = export(capsysbinary, path)
    [old], [new] = todos(before), todos(after)
    assert old["RRULE"] == new["RRULE"] == "FREQ=WEEKLY"
    assert new["DUE;VALUE=DATE"] == "20261116"
    assert old["UID"] == new["UID"]
    assert ical.uid(parse_task("2026-11-01 Water filter +home due:2026-11-09 rec:1w")) != old["UID"]
