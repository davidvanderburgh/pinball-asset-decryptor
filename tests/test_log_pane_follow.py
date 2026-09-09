"""The log pane follows the end until the user touches it.

Reported 2026-09-09: during an emulator run the pane appends thousands of lines
a minute, and every one called ``see(END)`` -- so scrolling up to read something
yanked the view straight back down.  "It becomes impossible to look."

The first fix inferred the answer from POSITION: at the bottom means follow.
That reads the symptom rather than the intent, and it is wrong twice -- a pane
the app has not laid out yet is not "scrolled away" however its scrollbar reads,
and a trim from the top can move the view with nobody asking.  So following is
the default and a DECISION, reconsidered only when the user moves the view.
These pin that: appending never parks the pane, a user scroll away from the end
does, scrolling back resumes, and the button is visible exactly while parked.

Real widgets, because the behaviour lives in the widget's own scroll state, and
skipped rather than failed where Tk cannot open a display.
"""

import pytest

tk = pytest.importorskip("tkinter")

from pinball_decryptor.gui.main_window import MainWindow


@pytest.fixture
def root():
    from tests.conftest import make_tk_root
    try:
        r = make_tk_root(tk)
    except tk.TclError:
        pytest.skip("no usable Tk display")
    # OFF-SCREEN, NOT WITHDRAWN.  A withdrawn root never lays its children out,
    # so the Text is 1x1 and `see(END)` leaves yview()[1] at 0.9953 -- the tests
    # would exercise the unlaid-out fallback and call it the scroll rule.
    r.geometry("560x320+10000+10000")
    r.update()
    try:
        yield r
    finally:
        try:
            r.destroy()
        except tk.TclError:
            pass


@pytest.fixture
def pane(root):
    """A MainWindow stub around one real log pane, wired the way it ships."""
    frame = tk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)
    text = tk.Text(frame, height=8, state=tk.DISABLED)
    scroll = tk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text.pack(fill=tk.BOTH, expand=True)

    win = MainWindow.__new__(MainWindow)
    win._log_frame = frame
    win._log_text = text
    win._log_follow = True
    win._log_follow_btn = None
    win._log_follow_btn_shown = False
    win._log_pane_lines = 0
    win._bind_log_follow(text, scroll)
    win._ensure_log_follow_button()
    root.update()
    assert text.winfo_height() > 1, "the pane must be laid out for these"
    return win


def _fill(win, n, start=0):
    for i in range(start, start + n):
        win._write_log_line("12:00:00", "event %d" % i, "info")
    win._log_text.update_idletasks()


def _user_scrolls(win, units):
    """What a wheel tick or a paging key does: move, then let the binding's
    after_idle run, which is where the decision is made."""
    win._log_text.yview_scroll(units, "units")
    win._on_log_user_scroll()
    win._log_text.update()


def test_a_fresh_pane_follows_from_the_first_line(pane):
    assert pane._log_follow is True
    _fill(pane, 200)
    assert "event 199" in pane._log_text.get("end-2l", tk.END)
    assert not pane._log_follow_btn_shown


def test_appending_never_parks_the_pane_on_its_own(pane):
    """The regression the position rule could cause: something moves the view
    (a trim, a relayout) and the pane silently stops following."""
    _fill(pane, 200)
    pane._log_text.yview_moveto(0.0)      # moved, but NOT by the user
    pane._log_text.update_idletasks()
    _fill(pane, 50, start=200)
    assert pane._log_follow is True
    assert pane._log_at_bottom(pane._log_text)


def test_a_user_scroll_away_from_the_end_parks_it(pane):
    _fill(pane, 400)
    _user_scrolls(pane, -20)
    assert pane._log_follow is False
    _fill(pane, 200, start=400)
    assert not pane._log_at_bottom(pane._log_text)


def test_scrolling_back_to_the_end_resumes_following(pane):
    _fill(pane, 400)
    _user_scrolls(pane, -20)
    assert pane._log_follow is False
    _user_scrolls(pane, 999)              # all the way back down
    assert pane._log_follow is True
    _fill(pane, 50, start=400)
    assert pane._log_at_bottom(pane._log_text)


def test_the_button_is_hidden_until_the_user_parks_the_pane(pane):
    _fill(pane, 400)
    assert pane._log_follow_btn.winfo_manager() == ""
    _user_scrolls(pane, -20)
    assert pane._log_follow_btn_shown
    assert pane._log_follow_btn.winfo_manager() == "place"


def test_the_button_jumps_to_the_end_and_follows_again(pane):
    _fill(pane, 400)
    _user_scrolls(pane, -20)
    pane._jump_to_latest_log()
    assert pane._log_follow is True
    assert pane._log_follow_btn.winfo_manager() == ""
    _fill(pane, 100, start=400)
    assert pane._log_at_bottom(pane._log_text)


def test_a_keyed_line_rewritten_in_place_does_not_move_a_parked_view(pane):
    """Per-sound decode progress rewrites one line many times a second."""
    pane._log_line_run = 1
    pane.update_log_line("snd", "decoding 1%")
    _fill(pane, 400)
    _user_scrolls(pane, -20)
    top = pane._log_text.yview()[0]
    for pct in range(2, 60):
        pane.update_log_line("snd", "decoding %d%%" % pct)
    pane._log_text.update_idletasks()
    assert pane._log_text.yview()[0] == pytest.approx(top, abs=1e-6)


def test_at_bottom_is_exact_not_nearly(pane):
    """One line up is not the bottom.  A tolerant test here reads as "the pane
    follows from a few lines up", which is the complaint, quietly."""
    _fill(pane, 400)
    assert pane._log_at_bottom(pane._log_text)
    pane._log_text.yview_scroll(-1, "units")
    pane._log_text.update_idletasks()
    assert not pane._log_at_bottom(pane._log_text)


def test_a_widget_that_cannot_answer_still_follows():
    """The default has to be the old behaviour: a pane being built or torn down
    must not silently stop showing new lines."""
    class Dead:
        def winfo_height(self):
            return 40

        def yview(self):
            raise tk.TclError("this widget no longer exists")

    assert MainWindow._log_at_bottom(Dead())


def test_a_pane_that_was_never_laid_out_follows(root):
    """A 1x1 Text is what an undrawn window holds, and `see(END)` cannot reach
    1.0 in one pixel.  Reading that as "the user scrolled away" would stop a
    STARTING app following its own log."""
    hidden = tk.Toplevel(root)
    hidden.withdraw()
    text = tk.Text(hidden, height=8)
    text.pack(fill=tk.BOTH, expand=True)
    hidden.update()
    for i in range(200):
        text.insert(tk.END, "event %d\n" % i)
    text.see(tk.END)
    text.update_idletasks()

    assert text.winfo_height() <= 1
    assert text.yview()[1] < 1.0                 # geometry alone says no
    assert MainWindow._log_at_bottom(text)       # the rule says yes
    hidden.destroy()
