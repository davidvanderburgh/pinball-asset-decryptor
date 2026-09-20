"""Does a switch a helper writes actually reach the GAME? PAD-186.

★ DRAGONRR, on Godzilla in the emulator: *"if I click Drain with no timer
running it allows me but the game doesn't end"*, and then *"it doesn't always
take the drain click"*. A click the window accepts and the game never sees
looks exactly like that, and every instrument on the PAD side used to report
the value it had WRITTEN rather than the value the game was handed.

WHY THIS FILE EXISTS RATHER THAN MORE CHECKS IN test_spike2_ball_model.py.
Those tests - and ballfeedtest.py, the WSL harness - model the guest as
`mrg[] = scr_held[]`, a copy. The real shim does not copy: it diffs each
array against the snapshot it took on its own previous pass and applies only
the CHANGES, last edge wins. Copy and diff agree for every single write, which
is why the blind spot survived this long, and they disagree for exactly one
shape: two writes to one id with no merge pass in between. That shape is
`take()` followed by the write take() exists to enable, and it is the whole of
PAD-186. So the merge here is modelled FAITHFULLY and stepped BY HAND, which
also means no test in this file depends on timing luck.

`test_the_twin_still_matches_the_shim` is what keeps the model honest.
"""
import os
import re
import struct
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

#: A trough position id, off godzilla_le's real switch list. Any id does; this
#: one is named so the failure messages read like the machine.
TROUGH_6 = 66


class Block(bytearray):
    """The 4096-byte block, as mutable as the mmap the helpers are written for.

    padsw.bump() calls flush() on what it was handed, because on a real run
    this is a shared mapping the guest reads.
    """

    def flush(self):
        pass


class Shim:
    """A faithful twin of hwshim.c's `sw_shm_merge()`, stepped by hand.

    Line for line, the part that matters:

        unsigned char k = sw_shm->held[n] ? 1 : 0;
        unsigned char s = sw_shm->scr_held[n] ? 1 : 0;
        unsigned char want = sw_mrg[n];
        if (k != sw_kbd_prev[n])      { want = k; }
        else if (s != sw_scr_prev[n]) { want = s; }
        sw_kbd_prev[n] = k;
        sw_scr_prev[n] = s;
        if (want != sw_mrg[n]) { sw_mrg[n] = want; ... }

    THE SNAPSHOTS ARE THE POINT. `sw_scr_prev` is taken on a pass, so a value
    that is written and written back between two passes was never there as far
    as the game is concerned.
    """

    def __init__(self, padsw, m):
        self.padsw, self.m = padsw, m
        self.kbd_prev = bytearray(padsw.MAX_ID)
        self.scr_prev = bytearray(padsw.MAX_ID)
        self.seen = None
        self.passes = 0
        #: The shim publishes its clock on the first transfer; padsw.merging()
        #: reads it to tell "lost" from "nobody home yet".
        struct.pack_into("<I", m, padsw.OFF_GUEST_T0, 1)

    def prime(self):
        """The state the shim's first pass finds, adopted without an edge."""
        p = self.padsw
        for n in range(p.MAX_ID):
            self.kbd_prev[n] = 1 if self.m[p.OFF_HELD + n] else 0
            self.scr_prev[n] = 1 if self.m[p.OFF_SCR_HELD + n] else 0
        return self

    def step(self):
        """One merge pass."""
        p, m = self.padsw, self.m
        gens = (struct.unpack_from("<I", m, p.OFF_GEN)[0],
                struct.unpack_from("<I", m, p.OFF_SCR_GEN)[0])
        if gens == self.seen:                      # the shim's own early-out
            return self
        self.seen = gens
        self.passes += 1
        moved = False
        for n in range(p.MAX_ID):
            k = 1 if m[p.OFF_HELD + n] else 0
            s = 1 if m[p.OFF_SCR_HELD + n] else 0
            want = m[p.OFF_MRG + n]
            if k != self.kbd_prev[n]:
                want = k
            elif s != self.scr_prev[n]:
                want = s
            self.kbd_prev[n] = k
            self.scr_prev[n] = s
            if want != m[p.OFF_MRG + n]:
                m[p.OFF_MRG + n] = want
                moved = True
        if moved:
            struct.pack_into("<I", m, p.OFF_MRG_GEN,
                             struct.unpack_from("<I", m, p.OFF_MRG_GEN)[0] + 1)
        return self


def _padsw(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_SW_FILE", str(tmp_path / "padsw"))
    import padsw
    return padsw


def _kbd_write(padsw, m, sw, val):
    """padglhost's half of the block. It owns `held[]`; nothing here does."""
    m[padsw.OFF_HELD + sw] = 1 if val else 0
    struct.pack_into("<I", m, padsw.OFF_GEN,
                     struct.unpack_from("<I", m, padsw.OFF_GEN)[0] + 1)


def _the_two_arrays_disagree(padsw):
    """The starting line, and it is a state padsw.py's docstring already names.

    padglhost latches the coin door and the SIX TROUGH BALLS on at window
    open, and its B key is bound to the same six ids ("6 balls in trough"), so
    the keyboard's array moves the trough on its own. Here both halves say
    "ball at TROUGH 6" - the latch, and the scripts after a drain - and then
    the KEYBOARD's copy goes away. Last edge wins, so the merge follows the
    keyboard to 0 and the scripts' array is left saying 1.

    That is all it takes, and nothing about it is exotic: the merge now says
    the position is empty, the script array says there is a ball in it, and
    the shim's snapshot of the script array says 1 as well. A drain aimed at
    that position has nowhere left to make an edge.
    """
    m = Block(4096)
    struct.pack_into("<I", m, padsw.OFF_MAGIC, padsw.MAGIC)
    m[padsw.OFF_HELD + TROUGH_6] = 1                 # padglhost's latch
    m[padsw.OFF_MRG + TROUGH_6] = 1                  # which the merge adopted
    m[padsw.OFF_SCR_HELD + TROUGH_6] = 1             # and a drain, earlier
    shim = Shim(padsw, m).prime()

    _kbd_write(padsw, m, TROUGH_6, 0)                # the B key, or the latch
    shim.step()

    assert padsw.merged(m, TROUGH_6) == 0            # the game: no ball there
    assert m[padsw.OFF_SCR_HELD + TROUGH_6] == 1     # the scripts: yes there is
    return m, shim


def test_a_drain_written_the_old_way_never_reaches_the_game(
        tmp_path, monkeypatch):
    """THE CONTROL, and the whole report in one assertion.

    `take()` sets the script array to what the merge shows - 0 - and the drain
    writes 1 straight after. scr_held goes 1 -> 0 -> 1, the shim's next pass
    compares 1 against a snapshot of 1, and there is no edge to find. The
    click was accepted, the line printed, and the game was never told.
    """
    padsw = _padsw(tmp_path, monkeypatch)
    m, shim = _the_two_arrays_disagree(padsw)

    padsw.take(m, (TROUGH_6,))
    padsw.set_held(m, TROUGH_6, 1)                   # plunge.py drain's write
    shim.step()

    assert padsw.merged(m, TROUGH_6) == 0            # the ball never came home
    assert m[padsw.OFF_SCR_HELD + TROUGH_6] == 1     # though PAD thinks it did


def test_set_confirmed_gets_the_same_drain_through(tmp_path, monkeypatch):
    """The fix, against the same starting state and the same hostile shim.

    The shim here only ever runs a pass when it is asked, and it is asked from
    another thread - so this is not "a merge happened to land in the gap", it
    is set_confirmed noticing the merge still disagrees and re-asserting until
    it does not.
    """
    padsw = _padsw(tmp_path, monkeypatch)
    m, shim = _the_two_arrays_disagree(padsw)

    stop = []
    def merging():
        while not stop:
            shim.step()
            time.sleep(0.001)
    t = threading.Thread(target=merging, daemon=True)
    t.start()
    try:
        padsw.take(m, (TROUGH_6,))
        took = padsw.set_confirmed(m, TROUGH_6, 1)
    finally:
        stop.append(1)
        t.join(timeout=2)

    assert took is True
    assert padsw.merged(m, TROUGH_6) == 1


def test_a_write_the_game_never_takes_is_reported_and_not_claimed(
        tmp_path, monkeypatch):
    """A shim that never runs another pass is a game that is not listening.

    The old code printed its success line here just the same. False is what
    lets plunge.py say "the game did not take that" instead, which is the
    difference between a silent fault and a report.
    """
    padsw = _padsw(tmp_path, monkeypatch)
    m, _shim = _the_two_arrays_disagree(padsw)
    monkeypatch.setattr(padsw, "CONFIRM_S", 0.05)
    monkeypatch.setattr(padsw, "RETRY_S", 0.005)

    padsw.take(m, (TROUGH_6,))
    assert padsw.set_confirmed(m, TROUGH_6, 1) is False


def test_a_window_with_no_game_behind_it_is_not_a_lost_write(
        tmp_path, monkeypatch):
    """None, not False: before the guest publishes its clock there is nobody
    to take a write, and the window is open long before a title boots. Telling
    a player "the game did not take that" there would be a lie."""
    padsw = _padsw(tmp_path, monkeypatch)
    m = Block(4096)
    struct.pack_into("<I", m, padsw.OFF_MAGIC, padsw.MAGIC)

    assert padsw.guest_ms(m) is None
    assert padsw.set_confirmed(m, TROUGH_6, 1) is None
    assert m[padsw.OFF_SCR_HELD + TROUGH_6] == 1     # still written, though


def test_an_ordinary_write_confirms_without_re_asserting(tmp_path, monkeypatch):
    """The common case must not get slower or noisier. With the two arrays
    already agreeing there is a real edge, one pass carries it, and
    set_confirmed returns on the first look."""
    padsw = _padsw(tmp_path, monkeypatch)
    m = Block(4096)
    struct.pack_into("<I", m, padsw.OFF_MAGIC, padsw.MAGIC)
    shim = Shim(padsw, m).prime()

    padsw.set_held(m, TROUGH_6, 1)
    shim.step()
    before = shim.passes
    assert padsw.set_confirmed(m, TROUGH_6, 1) is True
    assert shim.passes == before                     # nothing re-asserted


def test_the_twin_still_matches_the_shim():
    """The twin above is only worth what its likeness is worth.

    hwshim.c is the truth and cannot be imported, so this pins the four lines
    the twin models. If the merge is ever rewritten - a copy instead of a
    diff, or the two inputs weighed differently - this fails and the twin has
    to be re-read rather than quietly drifting into agreeing with anything.
    """
    src = open(os.path.join(RIG, "hwshim.c"), encoding="utf-8",
               errors="replace").read()
    body = src[src.index("static void sw_shm_merge(void)"):]
    body = body[:body.index("\n}\n")]
    for want in ("if (kg == seen_k && sg == seen_s) return;",
                 "if (k != sw_kbd_prev[n])",
                 "else if (s != sw_scr_prev[n])",
                 "sw_scr_prev[n] = s;",
                 "if (want != sw_mrg[n])"):
        assert want in body, "hwshim.c's merge changed: %r is gone" % want
    #: And that it is still a DIFF and not a copy - the one rewrite that would
    #: make the twin's whole point disappear.
    assert not re.search(r"sw_mrg\[n\]\s*=\s*s\s*;", body)
