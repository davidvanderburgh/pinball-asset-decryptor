"""core.session_log — the rolling on-disk log history (monkeybug batch 18).

Pure-filesystem tests: no Tk needed.
"""

import os
import time

from pinball_decryptor.core import session_log as sl


def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(sl, "LOG_DIR_OVERRIDE", str(tmp_path / "logs"))


def _read():
    with open(sl.log_path(), encoding="utf-8") as fh:
        return fh.read()


def test_start_session_and_append(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    sl.start_session("9.9.9")
    sl.append("hello from the log pane")
    sl.append("something broke", "error")
    text = _read()
    assert "v9.9.9 — session started" in text
    assert "hello from the log pane" in text
    # Non-info levels are labelled so the file reads like the pane's colors.
    assert "[ERROR] something broke" in text
    # Plain info lines are not.
    assert "[INFO]" not in text


def test_rolls_by_size_and_keeps_appending(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(sl, "MAX_BYTES", 100)
    sl.append("x" * 200)          # first file, immediately over the cap
    sl.append("after the roll")   # append sees the oversize file and rolls
    assert os.path.isfile(sl.log_path() + ".1"), "oversize log must roll"
    live = _read()
    assert "after the roll" in live
    assert "x" * 200 not in live, "rolled content must leave the live file"
    with open(sl.log_path() + ".1", encoding="utf-8") as fh:
        assert "x" * 200 in fh.read()


def test_roll_shift_drops_oldest(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(sl, "MAX_BYTES", 50)
    for i in range(6):
        sl.append("chunk %d %s" % (i, "y" * 80))
    # Never more files than the cap allows.
    rolls = [p for p in os.listdir(sl.log_dir())
             if p.startswith("session.log.")]
    assert len(rolls) <= sl.KEEP_ROLLS


def test_prunes_stale_rolls_on_start(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    os.makedirs(sl.log_dir(), exist_ok=True)
    stale = sl.log_path() + ".2"
    with open(stale, "w", encoding="utf-8") as fh:
        fh.write("ancient history")
    old = time.time() - (sl.KEEP_DAYS + 30) * 86400
    os.utime(stale, (old, old))
    fresh = sl.log_path() + ".1"
    with open(fresh, "w", encoding="utf-8") as fh:
        fh.write("recent history")
    sl.start_session("1.0.0")
    assert not os.path.exists(stale), "rolls past KEEP_DAYS are pruned"
    assert os.path.exists(fresh), "recent rolls survive"


def test_previous_tail_splits_on_last_banner(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    sl.start_session("1.0.0")            # an "earlier" session…
    sl.append("first session line")
    sl.append("first session error", "error")
    sl.start_session("1.1.0")            # …then the current one
    sl.append("current session line")
    tail = sl.previous_tail()
    joined = "\n".join(tail)
    assert "first session line" in joined
    assert "[ERROR] first session error" in joined
    # The earlier session's own banner stays (it separates older sessions
    # inside the dimmed block)…
    assert any(sl.BANNER_PREFIX in ln for ln in tail)
    # …but nothing from the current session leaks in.
    assert "current session line" not in joined
    assert not any("v1.1.0" in ln for ln in tail)


def test_previous_tail_empty_cases(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    assert sl.previous_tail() == []      # no file at all
    sl.start_session("1.0.0")
    assert sl.previous_tail() == []      # first-ever session: no history
    # Default is UNCAPPED — the pane shows the whole previous history
    # (the file itself is size-capped by the roll, so this is bounded);
    # an explicit max_lines still trims to the newest.
    sl.append("old line one")
    sl.append("old line two")
    sl.start_session("1.1.0")
    full = sl.previous_tail()
    assert any("old line one" in ln for ln in full)
    assert any("old line two" in ln for ln in full)
    tail = sl.previous_tail(max_lines=1)
    assert len(tail) == 1 and "old line two" in tail[0]


def test_append_never_raises_on_unwritable_dir(tmp_path, monkeypatch):
    # Point the log at a path that cannot be a directory (a file), so
    # makedirs/open fail — append must swallow it (the GUI log must never
    # die because the history file can't be written).
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    monkeypatch.setattr(sl, "LOG_DIR_OVERRIDE", str(blocker / "logs"))
    sl.append("this must not raise")
    sl.start_session("1.0.0")


def test_project_file_roundtrip_and_validation(tmp_path):
    from pinball_decryptor.core import project_file as pf
    p = str(tmp_path / ("t" + pf.EXTENSION))
    pf.save(p, manufacturer_key="stern",
            paths={"extract_input": r"C:\a\in.raw",
                   "write_assets": r"C:\a\assets"},
            extract_options={"auto_name_callouts": True},
            write_filename="out.raw", app_version="1.2.3")
    data = pf.load(p)
    assert data["manufacturer"] == "stern"
    assert data["paths"]["extract_input"] == r"C:\a\in.raw"
    assert data["paths"]["write_output"] == ""      # absent fields default
    assert data["extract_options"]["auto_name_callouts"] is True
    assert data["write_filename"] == "out.raw"

    # Not-a-project files are refused with a readable error.
    bad = tmp_path / "bad.pinproj"
    bad.write_text("{\"kind\": \"something-else\"}", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        pf.load(str(bad))
    notjson = tmp_path / "notjson.pinproj"
    notjson.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError):
        pf.load(str(notjson))
