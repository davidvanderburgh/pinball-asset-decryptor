"""PAD-1617: a VPX table's WSL link (PAD-1306) that went down on a run
Windows CAN read was never started again - the rest of the session ran on the
fallback (9p reads every poll, switches through swkeys.py): Mike St P's
Walking Dead game lost its link once, 85 s in ("silent 6 s"), and played on
the slow path from there. A new link is now started beside the fallback,
which carries on until it is up; the held switches are then handed over and
the fallback retired with "keep", so nothing the table holds is let go."""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
for p in (RIG, os.path.join(RIG, "vpx")):
    if p not in sys.path:
        sys.path.insert(0, p)

import padsw  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_pad1306_link import Block, Shim  # noqa: E402

pc = pytest.importorskip("padcontroller")


# --- the helpers: "keep" then EOF leaves what they hold ------------------------

def test_swkeys_keep_then_eof_leaves_its_switches_held(monkeypatch):
    import swkeys
    m = Block(4096)
    Shim(m).boot()
    monkeypatch.setattr(padsw, "open_block", lambda *a, **k: m)
    monkeypatch.setattr(sys, "stdin", iter(["55 1\n", "cab left 1\n", "keep\n"]))
    assert swkeys.main() == 0
    assert m[padsw.OFF_SCR_HELD + 55] == 1                       # handed over, not released
    assert m[padsw.OFF_SCR_CAB + padsw.CAB_NAMES.index("left")] == 1


def test_keep_is_a_line_of_its_own_and_eof_still_releases_without_it():
    import swkeys
    assert swkeys.parse("keep") == ("keep", None, None)
    assert swkeys.parse("keep 1") is None
    m = Block(4096)
    Shim(m).boot()
    h = swkeys.Holder(m)
    h.handle(("sw", 57, 1))
    h.release()
    assert m[padsw.OFF_SCR_HELD + 57] == 0


def test_padlink_holds_through_the_same_holder():
    """padlink.py's lines go through swkeys.parse + Holder, so "keep" is its too."""
    src = open(os.path.join(RIG, "padlink.py"), encoding="utf-8").read()
    assert "swkeys.parse(" in src and "swkeys.Holder(" in src and "hold.release()" in src


class _Proc:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.waited = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_switchpipe_close_with_keep_says_keep_before_its_eof():
    sp = pc.SwitchPipe(None)
    sp._p = proc = _Proc()
    sp.close(keep=True)
    assert proc.stdin.getvalue() == b"keep\n" and proc.waited
    sp._p = proc = _Proc()
    sp.close()
    assert proc.stdin.getvalue() == b""                          # a plain close releases, as before


def test_a_down_riglink_closed_with_keep_passes_it_to_its_fallback(monkeypatch):
    monkeypatch.setattr(pc, "log", lambda s: None)
    closed = []

    class Pipe:
        def __init__(self, rig):
            self.held = {}

        def set(self, sw, level):
            self.held[sw] = level

        def close(self, keep=False):
            closed.append(keep)

    monkeypatch.setattr(pc, "SwitchPipe", Pipe)
    rl = pc.RigLink(None, spawn=lambda: None)
    rl._give_up("silent 6 s")
    rl.close(keep=True)
    assert closed == [True]


# --- the bridge: a new link beside the fallback --------------------------------

class FakeLink:
    made = []

    def __init__(self, rig):
        self.rig, self.state, self.held = rig, "starting", {}
        self.closed = None
        FakeLink.made.append(self)

    def set(self, sw, level):
        self.held[sw] = level

    def close(self, keep=False):
        self.closed = "keep" if keep else "release"
        self.state = "down"


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def bridge(monkeypatch):
    said = []
    clk = Clock()
    monkeypatch.setattr(pc, "log", said.append)
    monkeypatch.setattr(pc, "RigLink", FakeLink)
    monkeypatch.setattr(pc, "LINK_ON", True)
    monkeypatch.setattr(pc.time, "monotonic", clk)
    FakeLink.made = []
    b = pc.Bridge()
    old = FakeLink(None)
    old.state, old.held = "down", {61: 1, 62: 1, 57: 0}
    b.pipe = old
    FakeLink.made = []
    return b, old, clk, said


def test_a_dropped_link_is_started_again_beside_the_fallback(bridge):
    b, old, clk, said = bridge
    b._relink_beside(old)
    assert FakeLink.made == []                                   # not at the drop itself
    clk.t += b.RELINK_S + 0.1
    b._relink_beside(old)
    assert len(FakeLink.made) == 1
    new = FakeLink.made[0]
    b._relink_beside(old)                                        # still starting
    assert b.pipe is old and old.closed is None and new.held == {}
    new.state = "up"
    b._relink_beside(old)
    assert b.pipe is new
    assert new.held == {57: 0, 61: 1, 62: 1}                     # every held switch handed over
    assert old.closed == "keep"                                  # the fallback lets go of nothing
    assert any("link back up" in s for s in said)


def test_a_new_link_that_fails_is_dropped_and_tried_later_backing_off(bridge):
    b, old, clk, said = bridge
    b._relink_beside(old)
    clk.t += b.RELINK_S + 0.1
    b._relink_beside(old)
    first = FakeLink.made[-1]
    first.state = "down"
    b._relink_beside(old)
    assert first.closed == "release" and b.pipe is old
    clk.t += b.RELINK_S + 0.1                                    # the second try waits twice as long
    b._relink_beside(old)
    assert len(FakeLink.made) == 1
    clk.t += b.RELINK_S
    b._relink_beside(old)
    assert len(FakeLink.made) == 2
    FakeLink.made[-1].state = "down"
    b._relink_beside(old)
    b._relink_n = 10                                             # many failures: the wait is capped
    n = len(FakeLink.made)
    clk.t += b.RELINK_MAX_S - 1
    b._relink_beside(old)
    assert len(FakeLink.made) == n
    clk.t += 1.1
    b._relink_beside(old)
    assert len(FakeLink.made) == n + 1


def test_a_link_back_up_for_a_rig_that_changed_meanwhile_is_not_used(bridge):
    b, old, clk, said = bridge
    b._relink_beside(old)
    clk.t += b.RELINK_S + 0.1
    b._relink_beside(old)
    new = FakeLink.made[-1]
    b.pipe = other = FakeLink(None)                              # a new run attached meanwhile
    new.state = "up"
    b._relink_beside(old)
    assert b.pipe is other and new.closed == "release"


def test_with_the_link_turned_off_nothing_is_started(bridge, monkeypatch):
    b, old, clk, said = bridge
    monkeypatch.setattr(pc, "LINK_ON", False)
    clk.t += 1000
    b._relink_beside(old)
    b._relink_beside(old)
    assert FakeLink.made == []


def test_the_poll_of_a_run_the_share_reaches_tries_the_link_again():
    src = open(os.path.join(RIG, "vpx", "padcontroller.py"), encoding="utf-8").read()
    poll = src[src.index("    def _poll_once(self):"):]
    poll = poll[:poll.index("        if link is not None and link.alive():")]
    assert "self._relink_beside(link)" in poll
