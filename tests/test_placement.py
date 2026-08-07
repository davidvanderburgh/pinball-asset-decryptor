"""Window and dropdown placement on a machine with more than one screen.

These exist because one root cause reached a tester as two unrelated bug
reports on the same dual-monitor Mac: "the tips button doesn't work the first
time — a window pops up and closes" (it had not closed; it had been dragged
onto the other monitor) and "the settings dropdown appears all the way over on
the right".

Pure arithmetic, driven through fakes rather than real windows: the whole point
is geometry the CI runner's single screen cannot reproduce, so a test needing a
real second monitor would test nothing anywhere.
"""

import pytest

from pinball_decryptor.gui import placement


class _FakeWin:
    """The handful of winfo_* calls placement asks about."""

    def __init__(self, x, y, w, h, screen=(1920, 1080)):
        self._x, self._y, self._w, self._h = x, y, w, h
        self._sw, self._sh = screen

    def update_idletasks(self):
        pass

    def winfo_rootx(self):
        return self._x

    def winfo_rooty(self):
        return self._y

    def winfo_width(self):
        return self._w

    def winfo_height(self):
        return self._h

    def winfo_screenwidth(self):
        return self._sw

    def winfo_screenheight(self):
        return self._sh

    def winfo_reqwidth(self):
        return self._w


@pytest.fixture(autouse=True)
def _not_windows(monkeypatch):
    """Default the tests to the non-Windows rule.

    On Windows the work area is the parent's REAL monitor, so clamping is
    always correct and the interesting case cannot arise; the bug reported was
    on macOS.  Individual tests opt back into win32 where it matters.
    """
    monkeypatch.setattr(placement.sys, "platform", "linux")


def test_a_window_on_a_second_monitor_is_left_where_it_belongs():
    """THE TIPS-WINDOW BUG.  The app is on a display to the right of the
    primary, so the centred position is beyond winfo_screenwidth() — and the
    old clamp read that as "off screen" and hauled the dialog back onto the
    primary monitor."""
    parent = _FakeWin(2200, 100, 1000, 800)      # second display, to the right
    x, y = placement.centered_over(parent, 640, 500)
    assert x == 2200 + (1000 - 640) // 2
    assert y == 100 + (800 - 500) // 2


def test_a_window_on_a_monitor_to_the_left_is_not_dragged_to_zero():
    """The mirror-image fault, which is what `max(0, x)` did: root coordinates
    are NEGATIVE on a display left of the primary."""
    parent = _FakeWin(-1500, 80, 1000, 800)
    x, _y = placement.centered_over(parent, 640, 500)
    assert x == -1500 + (1000 - 640) // 2
    assert x < 0


def test_a_parent_on_the_primary_screen_is_still_clamped():
    """The clamp is not simply deleted.  A small parent near the bottom-right
    of the primary display would centre a big dialog off the edge, and there
    the clamp is doing real work."""
    parent = _FakeWin(1500, 800, 400, 260)       # wholly inside 1920x1080
    x, y = placement.centered_over(parent, 640, 500)
    assert x == 1920 - 640
    assert y == 1080 - 500


def test_a_parent_straddling_the_primary_edge_is_not_clamped():
    """Deliberate, and it is the safe direction.  A parent hanging off the
    right edge of the primary screen is indistinguishable — without a monitor
    API — from a parent on a second display, and treating it as "off screen"
    is exactly the mistake that teleported the Tips window.  Not clamping
    leaves the dialog over its parent, which is where the user is looking."""
    parent = _FakeWin(1800, 900, 400, 300)
    x, _y = placement.centered_over(parent, 640, 500)
    assert x == 1800 + (400 - 640) // 2


def test_an_unmapped_parent_falls_back_to_the_middle_of_the_screen():
    """A dialog built before its parent is mapped reports width 1; centring on
    that would pin every such dialog to the top-left corner."""
    parent = _FakeWin(0, 0, 1, 1)
    assert placement.centered_over(parent, 640, 500) == ((1920 - 640) // 2,
                                                         (1080 - 500) // 2)


def test_on_primary_display_detects_the_second_monitor():
    assert placement.on_primary_display(_FakeWin(10, 10, 800, 600))
    assert not placement.on_primary_display(_FakeWin(2200, 10, 800, 600))
    assert not placement.on_primary_display(_FakeWin(-900, 10, 800, 600))


def test_a_dropdown_is_right_aligned_under_its_button():
    """The menu's width has to be asked for AFTER it has been laid out — an
    unmapped tk.Menu answers 1, which posts the menu at the button's right
    edge so it opens rightwards.  That is "the dropdown appears all the way
    over on the right"."""
    btn = _FakeWin(1500, 40, 24, 24)
    menu = _FakeWin(0, 0, 260, 300)
    x, y = placement.dropdown_position(menu, btn)
    assert x == 1500 + 24 - 260          # right edges aligned
    assert y == 40 + 24                  # directly underneath


def test_a_dropdown_asks_the_menu_to_lay_itself_out_first():
    """Without update_idletasks the width is 1 and the alignment is a no-op."""
    calls = []
    btn = _FakeWin(100, 40, 24, 24)
    menu = _FakeWin(0, 0, 260, 300)
    menu.update_idletasks = lambda: calls.append(1)
    placement.dropdown_position(menu, btn)
    assert calls, "the menu was measured before it had been laid out"


def test_macos_lets_the_native_menu_place_itself(monkeypatch):
    """On Aqua a tk.Menu IS an NSMenu: its requested width is not a Tk value,
    so the arithmetic cannot work and macOS keeps a posted menu on screen by
    itself anyway."""
    monkeypatch.setattr(placement.sys, "platform", "darwin")
    btn = _FakeWin(1500, 40, 24, 24)
    menu = _FakeWin(0, 0, 1, 1)          # what an unmapped NSMenu reports
    x, y = placement.dropdown_position(menu, btn)
    assert (x, y) == (1500, 64)
