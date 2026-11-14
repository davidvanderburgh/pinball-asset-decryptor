"""PAD-1306: the Visual Pinball controller's lights, coils and switches pushed
from inside WSL (padlink.py + padcontroller.RigLink), and every switch edge
read back off the merge and written again until the game has it
(padsw.Confirmer, behind swkeys.py and padlink.py)."""
import io
import os
import struct
import time
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
for p in (RIG, os.path.join(RIG, "vpx")):
    if p not in sys.path:
        sys.path.insert(0, p)

import padsw  # noqa: E402


class Block(bytearray):
    def flush(self):
        pass

    def close(self):
        pass


class Shim:
    """The guest's merge, last edge wins: each pass diffs scr_held against
    its own last snapshot and moves mrg[] on an edge. `drop` edges are
    swallowed (the snapshot moves, mrg does not): the lost write."""

    def __init__(self, m, drop=0):
        self.m = m
        self.snap = bytes(m[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])
        self.drop = drop

    def boot(self, t0=1234):
        struct.pack_into("<I", self.m, padsw.OFF_GUEST_T0, t0)

    def run(self):
        now = bytes(self.m[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])
        for i, (a, b) in enumerate(zip(self.snap, now)):
            if a != b:
                if self.drop:
                    self.drop -= 1
                else:
                    self.m[padsw.OFF_MRG + i] = b
        self.snap = now


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _confirmer(drop=0, booted=True):
    m = Block(4096)
    shim = Shim(m, drop)
    if booted:
        shim.boot()
    clk = Clock()
    lost = []
    c = padsw.Confirmer(m, confirm_s=0.25, retry_s=0.012, clock=clk,
                        on_lost=lambda sw, v: lost.append((sw, v)))
    return m, shim, clk, c, lost


def _passes(shim, clk, c, n, step=0.004):
    for _ in range(n):
        clk.t += step
        c.tick()
        shim.run()


def test_a_lost_switch_edge_is_written_again_until_the_game_has_it():
    m, shim, clk, c, lost = _confirmer(drop=1)
    c.set(62, 1)                     # a trough ball; the shim loses the edge
    shim.run()
    assert m[padsw.OFF_MRG + 62] == 0
    _passes(shim, clk, c, 20)
    assert m[padsw.OFF_MRG + 62] == 1 and c.pending() == 0
    assert c.again >= 1 and c.lost == 0 and not lost


def test_a_taken_edge_is_never_written_twice():
    m, shim, clk, c, lost = _confirmer()
    c.set(55, 1)
    _passes(shim, clk, c, 20)
    assert m[padsw.OFF_MRG + 55] == 1 and c.again == 0


def test_a_switch_the_game_never_takes_is_reported_lost_at_the_deadline():
    m, shim, clk, c, lost = _confirmer(drop=10 ** 6)
    c.set(66, 1)
    _passes(shim, clk, c, 100)
    assert lost == [(66, 1)] and c.lost == 1 and c.pending() == 0


def test_a_write_before_the_game_is_up_is_checked_from_its_first_passes():
    # the trough a table sets at Init, long before the guest's clock exists;
    # the shim's first pass takes the written level as its baseline: no edge
    m, shim, clk, c, lost = _confirmer(booted=False)
    c.set(63, 1)
    _passes(shim, clk, c, 200)        # nearly a second with no game: not given up
    assert c.pending() == 1 and not lost and c.again == 0
    shim.snap = bytes(m[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])
    shim.boot()
    _passes(shim, clk, c, 20)
    assert m[padsw.OFF_MRG + 63] == 1 and c.pending() == 0 and not lost


def test_a_paused_game_is_waited_for_not_given_up_on():
    # Pause / F9: no merge pass runs, so the take and the write collapse
    # (the shim's snapshot never sees the middle) - lost every time
    m, shim, clk, c, lost = _confirmer()
    m[padsw.OFF_HELD + 66] = 1                      # the keyboard latch holds it
    m[padsw.OFF_MRG + 66] = 1
    struct.pack_into("<I", m, padsw.OFF_PAUSED, 1)
    c.set(66, 0)
    for _ in range(300):                            # 1.2 s paused, nothing merges
        clk.t += 0.004
        c.tick()
    assert not lost and c.pending() == 1
    assert m[padsw.OFF_SCR_HELD + 66] == 0          # no flip left standing
    struct.pack_into("<I", m, padsw.OFF_PAUSED, 0)
    _passes(shim, clk, c, 30)
    assert m[padsw.OFF_MRG + 66] == 0 and c.pending() == 0 and not lost


def test_a_game_restart_checks_every_held_switch_again():
    m, shim, clk, c, lost = _confirmer()
    c.set(64, 1)
    _passes(shim, clk, c, 10)
    assert c.pending() == 0
    m[padsw.OFF_MRG:padsw.OFF_MRG + padsw.MAX_ID] = bytes(padsw.MAX_ID)   # a new guest
    shim.snap = bytes(m[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])
    shim.boot(t0=99999)
    _passes(shim, clk, c, 20)
    assert m[padsw.OFF_MRG + 64] == 1


def test_swkeys_keeps_its_lines_and_releases_on_eof(monkeypatch):
    import swkeys
    m = Block(4096)
    Shim(m).boot()
    monkeypatch.setattr(padsw, "open_block", lambda *a, **k: m)
    monkeypatch.setattr(sys, "stdin", iter(["55 1\n", "cab left 1\n", "bogus\n"]))
    assert swkeys.main() == 0
    assert m[padsw.OFF_SCR_HELD + 55] == 0                       # released at EOF
    assert m[padsw.OFF_SCR_CAB + padsw.CAB_NAMES.index("left")] == 0


# --- padlink: what goes up the pipe -------------------------------------------

def test_diff_covers_every_changed_byte_and_nothing_else():
    import padlink
    old = bytes(1000)
    new = bytearray(old)
    new[3] = 1
    new[64] = 2
    new[130] = 3
    new[999] = 4
    runs = padlink.diff(old, bytes(new))
    assert [o for o, _ in runs] == [0, 960]                       # chunks 0-2 run together
    out = bytearray(old)
    for o, b in runs:
        out[o:o + len(b)] = b
    assert out == new
    assert padlink.diff(old, old) == []


def _led(n=15000):
    b = bytearray(n)
    b[0:4] = b"PLED"
    return b


class _Src:
    def __init__(self, data):
        self.data = data
        self.n = len(data)

    def read(self, lo=0, hi=None):
        return bytes(self.data[lo:self.n if hi is None else hi])

    def moved(self):
        return False


def _link(led, sw):
    import padlink
    import swkeys
    out = io.StringIO()
    hold = swkeys.Holder(sw)
    link = padlink.Link(out, _Src(led), _Src(sw), hold, clock=Clock())
    return link, out


def test_link_lines_rebuild_the_blocks_on_the_controller_side(monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "log", lambda s: None)
    import coilmap
    led, sw = _led(), Block(4096)
    link, out = _link(led, sw)
    link.hello()
    led[coilmap.COIL_OFF + 1 * 16 + 3] = 7          # a coil fired
    led[20 + 96 * 2 + 5] = 200                      # an LED lit
    sw[padsw.OFF_MRG + 62] = 1                      # the game took a trough ball
    link.look()
    link.look()                                     # nothing moved: nothing sent
    lines = out.getvalue().splitlines()
    assert lines[0].startswith("HELLO padlink 1 ")
    assert [ln[0] for ln in lines] == ["H", "F", "G", "L", "M", "P"][:len(lines)]
    assert sum(len(ln) for ln in lines[3:]) < 400, "only the changes travel"

    rl = pc.RigLink(None, spawn=lambda: None)       # fed by hand, no helper behind it
    for ln in lines:
        assert rl.feed(ln + "\n")
    assert rl.state == "up"
    got_led, got_mrg = rl.blocks()
    assert got_led == bytes(led) and got_mrg == bytes(sw[padsw.OFF_MRG:padsw.OFF_MRG + 256])


class _Quiet:
    """A helper's stdout that says nothing and never ends."""

    def __iter__(self):
        import threading
        threading.Event().wait()
        return iter(())


class _Proc:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.stdout = _Quiet()

    def poll(self):
        return 0


def test_switches_said_before_hello_go_down_the_link_once_it_is_up(monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "log", lambda s: None)
    proc = _Proc()
    rl = pc.RigLink(None, spawn=lambda: proc)
    rl.set(62, 1)
    rl.set(62, 1)                                   # no change: not sent again
    assert proc.stdin.getvalue() == b"" and rl.blocks() is None
    for ln in ("HELLO padlink 1 led=4 sw=256", "F 504c4544", "G " + "00" * 256):
        rl.feed(ln)
    assert proc.stdin.getvalue() == b"62 1\n"
    rl.set(55, 1)
    assert proc.stdin.getvalue() == b"62 1\n55 1\n"


def test_a_silent_link_falls_back_with_every_held_switch_handed_over(monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "log", lambda s: None)
    sent = []

    class Pipe:
        def __init__(self, rig):
            self.held = {}

        def set(self, sw, level):
            self.held[sw] = level
            sent.append((sw, level))

        def _send(self, line):
            sent.append(line)
            return True

        def close(self):
            pass

    monkeypatch.setattr(pc, "SwitchPipe", Pipe)
    clk = Clock()
    rl = pc.RigLink(None, spawn=lambda: _Proc(), clock=clk)
    for ln in ("HELLO padlink 1 led=4 sw=256", "F 504c4544", "G " + "00" * 256):
        rl.feed(ln)
    rl.set(62, 1)
    rl.set(55, 1)
    assert rl.blocks() is not None
    clk.t += rl.SILENT_S + 1                        # no ping for 7 s
    assert rl.blocks() is None and rl.state == "down"
    assert sorted(sent) == [(55, 1), (62, 1)]
    rl.set(55, 0)
    assert sent[-1] == b"55 0\n"                    # from here on through swkeys


def test_no_hello_falls_back_too(monkeypatch):
    pc = pytest.importorskip("padcontroller")
    monkeypatch.setattr(pc, "log", lambda s: None)
    monkeypatch.setattr(pc, "SwitchPipe", lambda rig: type("P", (), {
        "held": {}, "set": lambda s, a, b: None, "close": lambda s: None,
        "_send": lambda s, line: True})())
    clk = Clock()
    rl = pc.RigLink(None, spawn=lambda: _Proc(), clock=clk)
    clk.t += rl.HELLO_S + 1
    assert not rl.alive() and "HELLO" in rl.why


def test_the_poll_reads_the_pushed_copy_not_9p(monkeypatch, tmp_path):
    pc = pytest.importorskip("padcontroller")
    import coilmap
    monkeypatch.setattr(pc, "log", lambda s: None)
    monkeypatch.setattr(pc, "LOG", str(tmp_path / "padcontroller.log"))
    reads = []
    monkeypatch.setattr(pc, "read_block", lambda path, n: reads.append(path))
    b = pc.Bridge()
    b.map = pc.VpxMap(None)
    b.rig = type("R", (), {"led_path": lambda s: "led", "sw_path": lambda s: "sw"})()
    led = bytearray(pc.READ_N)
    struct.pack_into("<I", led, 0, coilmap.PADLED_MAGIC)
    led[20 + 3] = 255                               # node 0 LED 3 lit
    mrg = bytearray(256)
    mrg[62] = 1
    link = type("L", (), {"held": {}, "frames": 1, "sent": 0, "up": True})()
    link.alive = lambda: link.up
    link.blocks = lambda: (bytes(led), bytes(mrg))
    b.pipe = link
    b._poll_once()
    assert reads == [] and b.polls == 1 and b.link_polls == 1
    assert b.lamp_state[pc.lamp_number(0, 3)] == 1 and b.mrg[62] == 1
    b._poll_once()                                  # nothing new: not decoded again
    assert b.link_polls == 1 and b.link_idle == 1
    led[20 + 3] = 0
    link.frames = 2                                 # the LED went out
    b._poll_once()
    assert b.link_polls == 2 and b.lamp_state[pc.lamp_number(0, 3)] == 0
    link.sent = 1                                   # the table moved a switch
    b._poll_once()
    assert b.link_polls == 3
    b._link_t -= b.LINK_STALE_S + 0.1               # quiet for long: decoded anyway
    b._poll_once()
    assert b.link_polls == 4
    b._coil_off_at[(1, 3)] = time.monotonic() - 0.001   # a coil's pulse ran out
    b._link_t = time.monotonic() - 0.01
    b._poll_once()
    assert b.link_polls == 5
    b._fake["motor"] = {"open": 0, "moving": None}  # a fake motor at rest: idle
    b._link_t = time.monotonic()
    b._poll_once()
    assert b.link_polls == 5
    b._fake["motor"]["moving"] = time.monotonic() - 0.001   # its travel is up
    b._poll_once()
    assert b.link_polls == 6
    link.up = False                                 # the link gone: 9p again
    b._poll_once()
    assert reads == ["led"] and b.poll_fail == 1   # back on 9p (nothing there in the test)
