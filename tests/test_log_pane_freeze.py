"""The log pane is a viewport, not the record — and when it was the record
the app froze.

2026-08-09: the window sat "Not Responding" for 40-85 s of every startup on a
machine with a day of emulator runs behind it.  py-spy caught the main thread
inside ``Text.see`` / ``Text.configure`` under ``append_log`` on every sample.
The cause was not WSL, not OneDrive and not any of the three things it was
blamed on first: ``_seed_log_history`` pushed the ENTIRE on-disk history into
a Tk Text widget (5,950 lines that day, 5,490 of them emulator event lines),
and every log line after that paid for the size of the widget.

So both ends are bounded now, and these are the tests that say so.  They use
real widgets because the bug lives in the widget, and skip when Tk is
unusable rather than failing the suite on a headless box.
"""

import pytest

tk = pytest.importorskip("tkinter")

from pinball_decryptor.core import session_log
from pinball_decryptor.gui.main_window import MainWindow


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no usable Tk display")
    r.withdraw()
    try:
        yield r
    finally:
        try:
            r.destroy()
        except tk.TclError:
            pass


def _log_file(tmp_path, monkeypatch, n_history_lines):
    """A session.log with *n_history_lines* of earlier-session history and a
    final banner, which is what previous_tail() splits on."""
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE", str(tmp_path))
    path = session_log.log_path()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("%s0.1.0 — session started earlier =====\n"
                 % session_log.BANNER_PREFIX)
        for i in range(n_history_lines):
            fh.write("[2026-08-09 09:47:41] [emulate] [event] [sw] line %d\n" % i)
        fh.write("%s0.1.0 — session started now =====\n"
                 % session_log.BANNER_PREFIX)
    return path


def test_seed_is_bounded_however_big_the_history_is(root, tmp_path,
                                                    monkeypatch):
    """The regression: a day of emulator logging must not land in the pane.

    Against the pre-fix code this inserts all 6000 lines and fails.
    """
    _log_file(tmp_path, monkeypatch, 6000)
    text = tk.Text(root)
    win = MainWindow.__new__(MainWindow)
    win.show_log_history_var = tk.BooleanVar(root, value=True)

    MainWindow._seed_log_history(win, text)

    n = int(str(text.index("end-1c")).split(".")[0])
    assert n <= MainWindow.LOG_SEED_LINES + 5, (
        "seeded %d lines from a 6000-line history — the pane is unbounded "
        "again and startup will freeze" % n)
    # The history is bounded, not silently cut: the cut line has to say so,
    # or the oldest visible line reads as the beginning of time.
    assert "full history in the log file" in text.get("1.0", tk.END)


def test_a_short_history_is_still_shown_whole(root, tmp_path, monkeypatch):
    """The cap must not cost the ordinary case its history, or the ⚙ toggle
    stops meaning anything for normal use."""
    _log_file(tmp_path, monkeypatch, 12)
    text = tk.Text(root)
    win = MainWindow.__new__(MainWindow)
    win.show_log_history_var = tk.BooleanVar(root, value=True)

    MainWindow._seed_log_history(win, text)

    body = text.get("1.0", tk.END)
    assert "line 0" in body and "line 11" in body
    assert "full history in the log file" not in body   # nothing was dropped


def test_a_poisoned_giant_line_cannot_come_back_out_of_the_file(tmp_path,
                                                               monkeypatch):
    """The second freeze, same widget: line COUNT was bounded (above) but
    line LENGTH was not.  One 341,705-char line — 341,626 NULs from a
    truncate-extended hole in the guest log, plus a real [sw] line — sat
    inside the seed window and pegged the main loop inside Tk_MeasureChars
    for a minute at every startup, of the installed build too, because every
    version seeds from the same file.  previous_tail() must hand back
    cleaned, clamped lines even when the FILE holds the poison (written
    before this fix, or by an older version)."""
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE", str(tmp_path))
    with open(session_log.log_path(), "w", encoding="utf-8") as fh:
        fh.write("%s0.1.0 — session started earlier =====\n"
                 % session_log.BANNER_PREFIX)
        fh.write("[2026-08-09 09:47:28] [emulate] [event] "
                 + "\x00" * 341626 + "[sw] 345896 ms -67a\n")
        fh.write("x" * 500_000 + "\n")          # huge but printable → clamped
        fh.write("\x00\x00\x00\n")              # pure NULs → dropped entirely
        fh.write("%s0.1.0 — session started now =====\n"
                 % session_log.BANNER_PREFIX)

    lines = session_log.previous_tail()

    # The earlier session's banner rides along (it always has); the all-NUL
    # line is GONE, not blanked — so banner + two cleaned lines.
    assert len(lines) == 3
    for ln in lines:
        assert "\x00" not in ln
        # MAX plus the "… [+N chars]" suffix, nothing near 341K.
        assert len(ln) <= session_log.MAX_LINE_CHARS + 32
    # The real content buried behind the NUL flood survives the cleaning.
    assert "[sw] 345896 ms -67a" in lines[1]
    # The clamp says it clamped — a silently shortened line reads as whole.
    assert "chars]" in lines[2]


def test_append_cleans_what_it_mirrors(tmp_path, monkeypatch):
    """The same poison must not reach the DISK either: append() is the one
    writer, so a flood cleaned here can never freeze a later session."""
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE", str(tmp_path))
    session_log.append("\x00" * 1000 + "[sw] still here")
    with open(session_log.log_path(), encoding="utf-8") as fh:
        body = fh.read()
    assert "\x00" not in body
    assert "[sw] still here" in body


def test_a_long_run_cannot_grow_the_pane_without_bound(root):
    """An emulator run appends thousands of lines; the widget must not keep
    all of them, or every later line (and the next startup) pays for it."""
    text = tk.Text(root)
    win = MainWindow.__new__(MainWindow)

    for i in range(MainWindow.LOG_PANE_MAX_LINES * 2):
        text.insert(tk.END, "[sw] event %d\n" % i)
        MainWindow._trim_log_pane(win, text)

    n = int(str(text.index("end-1c")).split(".")[0])
    assert n <= MainWindow.LOG_PANE_MAX_LINES + MainWindow.LOG_PANE_CHECK_EVERY
    # It keeps the NEWEST lines — trimming the wrong end would throw away
    # what the user is actually watching.
    assert "event %d" % (MainWindow.LOG_PANE_MAX_LINES * 2 - 1) in \
        text.get("1.0", tk.END)
