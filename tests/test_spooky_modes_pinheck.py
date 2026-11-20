"""Spooky custom modes on the pinHeck DMD games (PAD-1422): Jetsons' runtime, its build, the app.

No game files: the runtime (tools/spooky_emu/modes/pinheck/prebuilt/padheck_JET_V004.bin, the
MIPS code that ships) runs on Unicorn against a stand-in game - stubs at Jetsons' hook addresses
that keep the score and count the calls - and the PRG build runs on a synthetic stock PRG made
to pass the hook table's checks.  The real game is proven in the emulator
(tools/spooky_emu/modes/pinheck/prove.py, docs/plans/spooky_modes.md).
"""
import hashlib
import importlib.util
import os
import struct
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = os.path.join(ROOT, "tools", "spooky_emu", "modes")
PH_DIR = os.path.join(MODES, "pinheck")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ph():
    return _load("t_pinheck_build", os.path.join(PH_DIR, "pinheck.py"))


@pytest.fixture(scope="module")
def mk():
    return _load("t_mkspkmodes", os.path.join(MODES, "mkspkmodes.py"))


@pytest.fixture(scope="module")
def port(mk):
    return mk.load_port("jetsons-V004")


# ============================================================================ the runtime on Unicorn
def _mips(*words):
    return struct.pack("<%dI" % len(words), *words)


JR_RA, NOP = 0x03E00008, 0
STOP = 0x9D07FF00               # where the stand-in game's call returns to


class Game:
    """Jetsons as far as the runtime sees it: its RAM, stub functions at the hook addresses."""
    LOG = 0xA0011000            # stub counters: add_score n, play_sfx n, text_str n, link_send n, text_show last

    def __init__(self, ph, prg_tail):
        from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN
        self.t = ph.H.HOOKS["JET_V004"]
        mu = self.mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN)
        mu.mem_map(0x1D000000, 0x80000)
        mu.mem_map(0x00000000, 0x20000)
        mu.mem_map(0x1F806000, 0x1000)           # UART1
        t = self.t
        # AddScore(points): score_array[1] += a0; LOG[0]++
        mu.mem_write(t["add_score"] & 0x1FFFFFFF, _mips(
            0x3C09A000, 0x8D282720, 0x01044021, 0xAD282720,     # lui t1,0xA000; lw t0; addu t0,t0,a0; sw
            0x3C09A001, 0x8D281000, 0x25080001, 0xAD281000,     # LOG[0]++
            JR_RA, NOP))
        for fn, off in (("play_sfx", 4), ("text_str", 8), ("link_send", 12)):
            mu.mem_write(t[fn] & 0x1FFFFFFF, _mips(
                0x3C09A001, 0x8D280000 | (0x1000 + off), 0x25080001, 0xAD280000 | (0x1000 + off),
                JR_RA, NOP))
        # text_show(this, 3, on): LOG[16] = on
        mu.mem_write(t["text_show"] & 0x1FFFFFFF, _mips(0x3C09A001, 0xAD261010, JR_RA, NOP))
        # PAD-1469 fireCoil(this, coil, time): LOG[20]++, LOG[24] = coil, LOG[28] = time
        mu.mem_write(t["coil_fire"] & 0x1FFFFFFF, _mips(
            0x3C09A001, 0x8D281014, 0x25080001, 0xAD281014, 0xAD251018, 0xAD26101C, JR_RA, NOP))
        mu.mem_write(t["tick_target"] & 0x1FFFFFFF, _mips(JR_RA, NOP))
        mu.mem_write(t["free_flash"] & 0x1FFFFFFF, prg_tail)
        self.ms = 1000
        self.set8(t["ball"], 0)

    def set8(self, a, v):
        self.mu.mem_write(a & 0x1FFFFFFF, bytes([v]))

    def set32(self, a, v):
        self.mu.mem_write(a & 0x1FFFFFFF, struct.pack("<I", v))

    def get8(self, a):
        return self.mu.mem_read(a & 0x1FFFFFFF, 1)[0]

    def hold(self, n, closed):
        a = self.t["switch_ram"] + (n >> 3)
        cur = self.get8(a)
        self.set8(a, cur | (1 << (n & 7)) if closed else cur & ~(1 << (n & 7)))

    def get32(self, a):
        return struct.unpack("<I", self.mu.mem_read(a & 0x1FFFFFFF, 4))[0]

    def tick(self, n=1):
        from unicorn.mips_const import UC_MIPS_REG_A0, UC_MIPS_REG_RA, UC_MIPS_REG_SP
        entry = struct.unpack_from("<I", self.mu.mem_read(self.t["free_flash"] & 0x1FFFFFFF, 12), 8)[0]
        for _ in range(n):
            self.ms += 1
            self.mu.mem_write(self.t["millis"] & 0x1FFFFFFF, struct.pack("<I", self.ms))
            self.mu.reg_write(UC_MIPS_REG_SP, 0xA001F000)
            self.mu.reg_write(UC_MIPS_REG_A0, self.t["this"])
            self.mu.reg_write(UC_MIPS_REG_RA, STOP)
            self.mu.emu_start(entry, STOP, count=2_000_000)

    def switch(self, n, ticks=20):
        a = self.t["switch_ram"] + (n >> 3)
        cur = self.mu.mem_read(a & 0x1FFFFFFF, 1)[0]
        self.set8(a, cur | (1 << (n & 7)))
        self.tick(ticks)
        self.set8(a, cur)
        self.tick(ticks)

    def new_ball(self, ball=1):
        self.set8(self.t["player"], 1)
        self.set8(self.t["ball"], ball)
        self.set8(self.t["ball_active"], 1)
        self.tick(5)

    @property
    def score(self):
        return self.get32(self.t["score_array"] + 4)

    def calls(self, k):
        return self.get32(self.LOG + 4 * k)

    @property
    def log(self):
        return bytes(self._uart).decode("latin1")


def _game(ph, port, modes):
    from unicorn import UC_HOOK_MEM_WRITE
    rt, head = ph.runtime("JET_V004")
    data = ph.pack_data(modes, port)
    tail = rt + b"\xFF" * (head["data"] - ph.H.HOOKS["JET_V004"]["free_flash"] - len(rt)) + data
    g = Game(ph, tail)
    g._uart = bytearray()

    def uart(uc, access, addr, size, value, ud):
        if addr & 0xFFF == 0x020:
            g._uart.append(value & 0xFF)
    g.mu.hook_add(UC_HOOK_MEM_WRITE, uart, begin=0xBF806000, end=0xBF806FFF)
    g.mu.hook_add(UC_HOOK_MEM_WRITE, uart, begin=0x1F806000, end=0x1F806FFF)
    return g


RUSH = dict(file="1_rush.mode", name="Rush", title="ASTRO RUSH", start="switch_20", start_count="2",
            shots="switch_0 switch_10", points="250000", seconds="30", complete="3",
            complete_points="2000000", sound_start="EB0", sound_shot="C01", sound_complete="G00")
SPIN = dict(file="2_spin.mode", name="Spin", title="SPIN", start="switch_40", shots="switch_41",
            points="50000", seconds="0", sound_end="J00", panel="top")


def test_runtime_starts_scores_and_completes_through_the_game(ph, port):
    g = _game(ph, port, [RUSH, SPIN])
    g.new_ball()
    g.switch(20)
    assert g.calls(1) == 0 and g.score == 0                 # one hit of two: not started
    g.switch(0)
    assert g.score == 0                                     # not running: a shot scores nothing
    g.switch(20)
    assert g.calls(1) == 1                                  # sound_start played
    for sw in (0, 10, 0):
        g.switch(sw)
    assert g.score == 3 * 250000 + 2000000                  # three shots, then the bonus
    assert g.calls(0) == 4 and g.calls(1) == 1 + 3 + 1      # AddScore x4; start, 3 shots, complete
    assert g.get32(g.LOG + 16) == 0                         # the panel is down again
    assert "1_rush: COMPLETED, bonus 2000000" in g.log and "1_rush: total 2750000" in g.log


def test_runtime_ends_modes_on_time_ball_end_tilt_and_counts_reset_at_a_new_game(ph, port):
    g = _game(ph, port, [RUSH, SPIN])
    g.new_ball()
    g.switch(20)
    g.switch(20)                                            # Rush: 30 s
    g.switch(40)                                            # Spin: until the ball ends
    assert g.get32(g.LOG + 16) == 1 and g.calls(2) > 0      # the panel is up, its text sent
    g.tick(30000)
    assert "1_rush: ended (time ran out)" in g.log and "2_spin: ended" not in g.log
    g.switch(41)
    assert g.score == 50000
    g.set8(g.t["ball_active"], 0)                           # the drain: the bonus count
    g.tick(3)
    assert "2_spin: ended (the ball ended)" in g.log
    g.switch(41)
    assert g.score == 50000                                 # no ball live: nothing scores
    g.new_ball(2)
    g.switch(40)
    g.set8(g.t["tilt"], 1)
    g.tick(3)
    assert "2_spin: ended (tilt)" in g.log
    g.set8(g.t["tilt"], 0)
    g.new_ball(3)
    g.switch(20)                                            # one hit towards Rush ...
    g.set8(g.t["ball"], 0)
    g.tick(3)                                               # ... the game ends ...
    assert "game over" in g.log
    g.new_ball(1)                                           # ... a new game resets it
    assert g.log.count("new game: start counts reset") == 2
    g.switch(20)
    assert "1_rush: STARTED" not in g.log.split("game over")[-1]


# ============================================================================ PAD-1469: parity
def _ball(g, ball=1, limit=4, phase=3):
    """A ball in play: the ball-limit setting, the ball live, then in play (phase 3)."""
    g.set8(g.t["ball_limit"], limit)
    g.set8(g.t["phase"], 2)
    g.new_ball(ball)
    g.set8(g.t["phase"], phase)
    g.tick(3)


def test_start_rules_fire_on_the_games_events(ph, port):
    m = lambda f, **k: dict(file=f, seconds="2", panel="none", **k)
    g = _game(ph, port, [
        m("e1.mode", start_on="ball_start", start_count="2"), m("e2.mode", start_on="first_ball"),
        m("e3.mode", start_on="last_ball"), m("e4.mode", start_on="valid_playfield"),
        m("e5.mode", start_on="extra_ball"), m("e6.mode", start_on="ball_saved"),
        m("e7.mode", start_score="300000"), m("e9.mode", start="switch_44", start_once="game"),
        m("e8.mode", start_combo="switch_20 switch_21", combo_seconds="2")])
    g.hold(34, True)                                       # one ball home in the trough
    _ball(g, 1)
    assert "e2: STARTED" in g.log and "e1: STARTED" not in g.log      # first ball; ball_start 1 of 2
    assert "e3: STARTED" not in g.log
    g.switch(34)                                           # a trough switch is not the playfield
    assert "event valid_playfield" not in g.log
    g.switch(20)                                           # the first playfield switch; combo 1 of 2
    assert "e4: STARTED" in g.log and "e8: STARTED" not in g.log
    g.switch(21)
    assert "e8: start_combo made" in g.log and "e8: STARTED" in g.log
    g.switch(20)
    g.tick(2500)
    g.switch(21)                                           # 2.5 s apart: too slow for 2 s
    assert g.log.count("e8: STARTED") == 1
    g.set8(g.t["extra_balls"], 1)
    g.tick(2)
    assert "e5: STARTED" in g.log
    g.set32(g.t["save_timer"], 3000)
    g.tick(2)
    g.set32(g.t["save_timer"], 0)                          # cut without a ball served back: not a save
    g.tick(2)
    assert "e6: STARTED" not in g.log
    g.set32(g.t["save_timer"], 3000)
    g.tick(2)
    g.set32(g.t["save_timer"], 0)
    g.set32(g.t["load_timer"], 2001)                       # the game served the drained ball back
    g.tick(2)
    g.set32(g.t["load_timer"], 0)
    assert "e6: STARTED" in g.log
    g.set32(g.t["score_array"] + 4, 350000)
    g.tick(2)
    assert "e7: start_score reached 350000" in g.log and "e7: STARTED" in g.log
    g.tick(3000)
    g.set32(g.t["score_array"] + 4, 450000)
    g.tick(2)
    assert g.log.count("e7: STARTED") == 1                 # once per player per game
    g.switch(44)
    g.tick(3000)                                           # e9 runs out
    g.switch(44)
    assert g.log.count("e9: STARTED") == 1 and "e9: not started: start_once" in g.log
    g.set8(g.t["ball_active"], 0)
    g.tick(3)
    _ball(g, 2)
    assert "e1: STARTED" in g.log                          # the second ball start
    g.set8(g.t["ball_active"], 0)
    g.tick(3)
    g.set8(g.t["extra_balls"], 1)
    _ball(g, 3)
    assert "e3: STARTED" not in g.log                      # ball 3 with an extra ball waiting
    g.set8(g.t["ball_active"], 0)
    g.set8(g.t["extra_balls"], 0)
    g.tick(3)
    _ball(g, 3)                                            # the shoot-again: the last ball now
    assert "e3: STARTED" in g.log


def test_lamps_coils_and_holds_through_the_game(ph, port):
    t = ph.H.HOOKS["JET_V004"]
    g = _game(ph, port, [dict(file="l.mode", start="switch_20", shots="switch_21", seconds="5",
                              lamps="lamp_10 lamp_11", lamp_color="400000", lamp_blink="2",
                              coil_start="KNOCKER", coil_shot="SHAKER 20",
                              coil_hold="SHAKER 600 8", coil_hold_on="switch_22")])
    lamp = lambda n: g.get8(t["lamp_ram"] + n)
    _ball(g)
    g.switch(20)
    assert (g.calls(5), g.calls(6), g.calls(7)) == (1, 0, 2)          # the knocker, 2 x 15 = 30 ms
    levels = set()
    for _ in range(40):
        g.tick(25)
        levels.add((lamp(10), lamp(11)))
    assert levels == {(2, 2), (0, 0)}                      # 0x40 of 255 = 2 of 8, flashing
    g.tick(300)
    g.switch(21)
    assert (g.calls(5), g.calls(6), g.calls(7)) == (2, 1, 2)          # 20 ms asked: 2 units
    n = g.calls(5)
    g.switch(22)                                           # the hold: one 15 ms pulse every 60 ms
    g.tick(560)
    assert 9 <= g.calls(5) - n <= 12 and g.calls(6) == 1 and g.calls(7) == 1
    g.tick(200)
    n = g.calls(5)
    g.tick(500)
    assert g.calls(5) == n and "coil_hold off 1 (its time)" in g.log
    g.switch(22)                                           # 3 s between two holds of one coil
    assert "not held: too soon" in g.log
    g.set32(t["coil_busy"], 12345)                         # the game is driving the knocker
    g.tick(5000)
    g.switch(20)
    assert "coil_start 0 not fired: the game is driving it" in g.log
    g.set8(t["ball_active"], 0)
    g.tick(3)
    g.set8(t["lamp_ram"] + 10, 7)                          # the game's own value, after the mode
    g.tick(5)
    assert lamp(10) == 7


def test_multiball_add_ball_and_ball_save_through_the_games_queue(ph, port):
    t = ph.H.HOOKS["JET_V004"]
    g = _game(ph, port, [dict(file="m.mode", start="switch_20", multiball="2 4", seconds="0"),
                         dict(file="e.mode", start_on="multiball_end", seconds="2", panel="none"),
                         dict(file="a.mode", start="switch_30", add_ball="switch_31 3", seconds="30"),
                         dict(file="s.mode", start="switch_40", ball_save="20", seconds="3")])
    q = lambda: struct.unpack("<H", g.mu.mem_read(t["ball_queue"] & 0x1FFFFFFF, 2))[0]
    g.hold(34, True)                                       # Jetsons has two balls: one home
    _ball(g)
    g.switch(20)
    assert q() == 1 and "m: a ball asked for, in play 1, want 2" in g.log
    assert g.get32(t["save_timer"]) >= 3900                # the multiball's ball save
    g.mu.mem_write(t["ball_queue"] & 0x1FFFFFFF, b"\0\0")  # the game loads it ...
    g.hold(34, False)                                      # ... out of the trough: two in play
    g.tick(5000)
    assert q() == 0
    g.hold(34, True)                                       # one drains, after the save
    g.tick(600)
    assert "event multiball_end" in g.log and "e: STARTED" in g.log
    assert "m: ended" not in g.log                         # the save + 3 s are not over yet
    g.tick(4000)
    assert "m: ended (one ball left)" in g.log
    g.switch(30)
    g.switch(31)
    assert q() == 1 and "a: add_ball on switch 31, balls 2" in g.log
    g.switch(31)                                           # two in play is every ball Jetsons has
    assert "add_ball: every ball of the game is in play" in g.log and q() == 1
    g.mu.mem_write(t["ball_queue"] & 0x1FFFFFFF, b"\0\0")
    g.set32(t["save_timer"], 0)
    g.tick(3000)
    g.set32(t["save_timer"], 5000)                         # the game's own save, 5 s left
    g.switch(40)
    assert g.get32(t["save_timer"]) >= 19000
    g.set32(t["save_timer"], 16900)                        # as the game counts it down
    g.tick(3000)                                           # s ends: the game's own save comes back
    assert "s: ended (time ran out)" in g.log and 1900 <= g.get32(t["save_timer"]) <= 2000


def test_pack_mode_parity_layout(ph, port):
    b = ph.pack_mode(dict(file="p.mode", start="switch_20", start_on="ball_start last_ball",
                          start_score="5000000", start_combo="switch_1 switch_2 switch_3",
                          combo_seconds="4", start_once="ball", start_count_reset="ball",
                          lamps="lamp_0 lamp_63", lamp_color="ff8000", lamp_blink="3",
                          multiball="2 7", multiball_on="switch_9", add_ball="switch_8 2", ball_save="12",
                          coil_start="KNOCKER", coil_shot="SHAKER 40", coil_hold="SHAKER 900 6",
                          coil_hold_on="start"), port)
    assert len(b) == ph.MODE_SIZE == 128 and b[39] == 1 | 2       # flags: reset ball, once ball
    assert b[64] == 1 and b[71] == 0x80                    # lamps 0 and 63
    assert b[72 + 1] == 1 << 1 and b[80 + 1] == 1          # multiball_on 9, add_ball 8
    score, ev, level, blink, cn = struct.unpack_from("<IBBBB", b, 96)
    assert (score, ev, level, blink, cn) == (5000000, 1 | 4, 8, 3, 3) and b[104:107] == bytes([1, 2, 3])
    assert (b[110], b[111], b[112], b[113], b[114], b[115]) == (4, 2, 7, 2, 12, 1)
    assert b[116:122] == bytes([0, 1, 0xFF, 0, 3, 0])      # knocker own, shaker 40 ms = 3 units
    assert struct.unpack_from("<BBH", b, 122) == (1, 6, 900)
    head = ph.pack_data([], port)[6:6 + 64]
    assert head[0] == 32 and head[1] == 15                 # the lane, 15 ms a fireCoil unit
    assert head[2 + (34 >> 3)] == (1 << 2) | (1 << 3)      # the trough: 34, 35
    assert head[10] == 1 and head[11] == 3 and head[34] == 2 and head[35] == 5   # knocker, shaker
    assert ph.lamp_level("000000") == 0 and ph.lamp_level("010000") == 1


def test_check_takes_parity_keys_and_refuses_what_pinheck_cannot_do(mk, port, tmp_path):
    def problems(text, cfg=""):
        d = tmp_path / ("m%d" % abs(hash(text + cfg)))
        d.mkdir()
        (d / "a.mode").write_text(text)
        if cfg:
            (d / "title.cfg").write_text(cfg)
        return mk.check_modes(str(d), port)[1]
    ok = ("start_on = valid_playfield ball_saved\nstart_score = 1000000\nlamps = lamp_5\n"
          "coil_start = KNOCKER\nmultiball = 2\nadd_ball = switch_20\nball_save = 10\n")
    assert problems(ok) == []
    assert problems("start = switch_1\ncoil_hold = SHAKER 1000\n", "coil_holds = on\n") == []
    assert any("multiball 3" in p and "has 2 balls" in p for p in problems("start = switch_1\nmultiball = 3\n"))
    assert any("start_after is not on" in p for p in problems("start_after = any\n"))
    for k, v in (("music", "a.ogg"), ("picture", "a.png"), ("video", "a.webm")):
        assert any("no files of its own" in p for p in problems("start = switch_1\n%s = %s\n" % (k, v)))
    assert any("not one of" in p for p in problems("start = switch_1\nlamps = lamp_64\n"))
    assert any("not one of" in p for p in problems("start = switch_1\ncoil_start = PLUNGER\n"))
    assert any("built to stay on" in p for p in problems("start = switch_1\ncoil_hold = KNOCKER 500\n",
                                                          "coil_holds = on\n"))


def test_runtime_turned_off_and_power_up_logs(ph, port):
    rt, head = ph.runtime("JET_V004")
    t = ph.H.HOOKS["JET_V004"]
    data = ph.pack_data([RUSH], port, off=True)
    g = Game(ph, rt + b"\xFF" * (head["data"] - t["free_flash"] - len(rt)) + data)
    g._uart = bytearray()
    g.new_ball()
    g.switch(20)
    g.switch(20)
    assert g.calls(1) == 0 and g.score == 0


# ============================================================================ the build
def _fake_stock(ph, monkeypatch):
    """A PRG the hook table takes as JET_V004: its sigs and tick site in place, sha1 matched."""
    t = dict(ph.H.HOOKS["JET_V004"])
    prg = bytearray(b"\x00" * t["size"])
    for a, sig in t["sigs"].items():
        prg[a - ph.H.FLASH:a - ph.H.FLASH + len(sig) // 2] = bytes.fromhex(sig)
    struct.pack_into("<I", prg, t["tick_site"] - ph.H.FLASH, ph.H.jal(t["tick_target"]))
    prg = bytes(prg)
    t["sha1"] = hashlib.sha1(prg).hexdigest()
    monkeypatch.setitem(ph.H.HOOKS, "JET_V004", t)
    return prg


def test_build_prg_patches_one_call_and_round_trips_to_stock(ph, port, monkeypatch):
    stock = _fake_stock(ph, monkeypatch)
    out = ph.build_prg(stock, [RUSH, SPIN], port)
    t = ph.H.HOOKS["JET_V004"]
    rt, head = ph.runtime("JET_V004")
    diff = [i for i in range(len(stock)) if stock[i] != out[i]]
    assert diff and all(t["tick_site"] - ph.H.FLASH <= i < t["tick_site"] - ph.H.FLASH + 4 for i in diff)
    assert ph.H.word(out, t["tick_site"]) == ph.H.jal(head["entry"])
    assert out[t["free_flash"] - ph.H.FLASH:][:len(rt)] == rt
    d = head["data"] - ph.H.FLASH
    magic, count = struct.unpack_from("<IB", out, d)
    assert magic == ph.DATA_MAGIC and count == 2
    assert ph.is_modes_build(out) and not ph.is_modes_build(stock)
    assert ph.stock_of(out) == stock                        # a rebuild starts from stock again
    with pytest.raises(ph.Refused, match="not the stock"):
        ph.build_prg(stock[:-4] + b"\x01\x02\x03\x04", [RUSH], port)


def test_pack_mode_layout(ph, port):
    b = ph.pack_mode(dict(RUSH), port)
    title, start, shots, sc, secs, comp, panel, _f, pts, cpts = struct.unpack_from("<16s8s8sHHHBBII", b)
    assert title.rstrip(b"\0") == b"ASTRO RUSH" and (sc, secs, comp, panel) == (2, 30, 3, 1)
    assert start[20 >> 3] == 1 << (20 & 7) and shots[0] == 1 and shots[1] == 1 << 2
    assert (pts, cpts) == (250000, 2000000) and b[48:52] == b"EB0\0" and b[52:56] == b"C01\0"


def test_check_refuses_what_a_dmd_cannot_do(mk, port, tmp_path):
    (tmp_path / "a.mode").write_text("start = switch_1\nshots = switch_2\ntitle = A TITLE MUCH TOO LONG\n"
                                     "font_title = X\ntitle_color = ff0000\nsound_start = ZZZ\n")
    _modes, problems = mk.check_modes(str(tmp_path), port)
    text = "\n".join(problems)
    assert "font_title is not on Jetsons" in text and "title_color is not on Jetsons" in text
    assert "the DMD panel shows 16" in text and "ZZZ" in text


def test_starter_modes_check_clean_and_the_runtime_ships(mk, port):
    modes, problems = mk.check_modes(os.path.join(MODES, "examples", "jetsons-V004"), port)
    assert not problems and len(modes) == 2
    assert mk.runtime_files(port)[0].endswith("padheck_JET_V004.bin")
    assert port["engine"] == "pinheck" and port["prg"] == "JET_V004" and len(port["switches"]) == 64


def test_build_zip_replaces_only_the_prg(mk, ph, port, tmp_path, monkeypatch):
    stock_prg = _fake_stock(ph, monkeypatch)
    monkeypatch.setattr(mk.ph().H, "HOOKS", ph.H.HOOKS)
    stock = tmp_path / "Jetsons_Code.zip"
    with zipfile.ZipFile(stock, "w") as z:
        z.writestr("Jetsons/JET_V004.PRG", stock_prg)
        z.writestr("Jetsons/DMD/_DA/AAA.VID", b"v" * 100, compress_type=zipfile.ZIP_STORED)
        z.writestr("Jetsons/SFX/_FE/EB0.wav", b"w" * 100, compress_type=zipfile.ZIP_DEFLATED)
    out = tmp_path / "out" / "Jetsons_Code.zip"
    out.parent.mkdir()
    mk.build(str(stock), os.path.join(MODES, "examples", "jetsons-V004"), str(out), port, log=lambda s: None)
    with zipfile.ZipFile(stock) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()
        assert [i.compress_type for i in a.infolist()] == [i.compress_type for i in b.infolist()]
        assert a.read("Jetsons/DMD/_DA/AAA.VID") == b.read("Jetsons/DMD/_DA/AAA.VID")
        new = b.read("Jetsons/JET_V004.PRG")
    assert ph.is_modes_build(new) and ph.stock_of(new) == stock_prg
    again = tmp_path / "again.zip"                          # a modes update built again: one runtime
    mk.build(str(out), os.path.join(MODES, "examples", "jetsons-V004"), str(again), port, log=lambda s: None)
    with zipfile.ZipFile(again) as c:
        assert c.read("Jetsons/JET_V004.PRG") == new


def test_write_zip_carries_the_modes_prg(ph, port, tmp_path, monkeypatch):
    from pinball_decryptor.plugins.spooky import custom_modes as SM
    from pinball_decryptor.plugins.spooky.formats import create_zip
    stock_prg = _fake_stock(ph, monkeypatch)
    monkeypatch.setattr(SM.mk().ph().H, "HOOKS", ph.H.HOOKS)
    monkeypatch.setattr(SM, "modes_root", lambda: str(tmp_path / "modes"))
    SM.title_dir("jetsons-V004")                            # seeded from the starter folder
    src = tmp_path / "extract"
    (src / "Jetsons").mkdir(parents=True)
    (src / "Jetsons" / "JET_V004.PRG").write_bytes(stock_prg)
    (src / "Jetsons" / "WHATSNEW.txt").write_text("x")
    assert SM.label_for_extract(str(src), {"game": "Jetsons"}) == "jetsons-V004"
    pm = SM.write_pad_modes("jetsons-V004", str(src))
    assert pm[1].modes == 2 and "JET_V004.PRG" in SM.loads_how("jetsons-V004")
    out = tmp_path / "w.zip"
    create_zip(str(src), str(out), pad_modes=pm)
    with zipfile.ZipFile(out) as z:
        prg = z.read("Jetsons/JET_V004.PRG")
        assert z.read("Jetsons/WHATSNEW.txt") == b"x"
    assert SM.mk().ph().is_modes_build(prg)


def test_modes_tab_form_and_install_note_for_jetsons():
    from pinball_decryptor.plugins.spooky import custom_modes as SM
    port = SM.load_port("jetsons-V004")
    groups, title_keys = SM.form_groups(port), SM.title_form(port)
    keys = {k for _g, ks in groups for k in ks}
    assert "panel" in keys and not keys & {"font_title", "title_color", "panel_color"}
    assert title_keys == ("panel", "lamp_color", "lamp_blink", "coil_holds")     # PAD-1469
    assert "UPDATE CODE" in SM.install_note("jetsons-V004")
    t = next(t for t in SM.titles() if t["label"] == "jetsons-V004")
    assert t["can_run"] and t["name"] == "Jetsons V004"


def test_try_it_runs_the_modes_prg_on_the_updates_card(tmp_path):
    from pinball_decryptor.webui import emulate_spooky_core as spk
    cmd = spk.pinheck_cmd("py", "Jetsons_Code.zip", "ctl.json", r"C:\t\JET_V004.PRG")
    assert cmd[-2:] == ["--prg", r"C:\t\JET_V004.PRG"]
    assert "--prg" not in spk.pinheck_cmd("py", "Jetsons_Code.zip", "ctl.json")


def test_unpack_takes_the_program_from_this_zip(tmp_path):
    """A modes update has the stock one's name and shares its unpacked folder: its PRG wins."""
    from tools.pinheck_emu.machine import unpack
    a, b = tmp_path / "a" / "Jetsons_Code.zip", tmp_path / "b" / "Jetsons_Code.zip"
    for z, prg in ((a, b"stock"), (b, b"modes")):
        z.parent.mkdir()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Jetsons/JET_V004.PRG", prg)
            f.writestr("Jetsons/DMD/_DA/AAA.VID", b"v")
    cache = str(tmp_path / "cache")
    assert open(unpack(str(a), cache)[0], "rb").read() == b"stock"
    assert open(unpack(str(b), cache)[0], "rb").read() == b"modes"
    assert open(unpack(str(a), cache)[0], "rb").read() == b"stock"
