"""PAD-1285: a mode's own multiball, its held coils and its blocks of the game's modes on a Spike 3 (64-bit ARM) game.

What the work found, held here at the desk (no card, no emulator):
- the multiball's two calls (balls_in_play, multiball_serve), the process sleep, the adjustment getter and coil_fire
  take their arguments in w0-w5 on both machines (the serve's two stack words are x4 / x5): placed by the matcher,
  carried as they are. Star Wars ELG 1.10's own one-ball saves pass (1, 0, 312, 0xbb) exactly as Spike 2's.
- the coil records coil_fire's writer fills are the same 0x68 bytes (powers +0x29..+0x30, request id +0x14, link
  +0x10, state +0x22, board +0x24, coil +0x1a); the table's pointer and its u64 count are 8 bytes: the runtime reads
  the pointer pointer-sized.
- the device object a held coil takes has its fields 8 bytes on (the vtable pointer is 8): its device u16 at +8, the
  exit hook at +36, the controlling process at +40 (Spike 2: +4 / +28 / +32), its update vtable slot 28 and its
  "disabled" slot 30 (adjustment(obj+12) == 1) where they were. The runtime keeps the object and the record as
  pm_addr and indexes a vtable by pointer size.
- the game's three mode starts (Inner Loop, Orbits, Ramps) set the same game flags (86, 88, 87); the flag bitmap's
  pointer is the global itself (Spike 2: holder + 4), its count 102. The block keeps the starts' addresses pm_addr.
- a mode's own multiball read as one of the game's: the count route sees only balls, so three seconds after our
  serve it said "a multiball is running" and the mode that asked for it ended ("the game's own mode began") - on
  Spike 2 as well, on every title that tells the game's multiballs by the count. The runtime now knows the balls are
  ours until they are back to one.
- s3port.py reads it all off a Spike 3 program (play_engine).
Emulator proof: docs/plans/spike3_modes.md "Multiball, held coils and blocks on Spike 3 (PAD-1285)".
"""
import importlib.util
import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
ELG2, ELG3 = r"C:\tmp\PAD-1271\elg2.game", r"C:\tmp\PAD-1271\elg3.game"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _body(src, head):
    b = src[src.index(head):]
    return b[:b.index("\n}\n")]


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    return S


def _port_lines():
    out = {}
    for line in PORT.read_text(encoding="utf-8").splitlines():
        t = line.split()
        if len(t) >= 3 and t[0] in ("site", "data", "value", "text"):
            out[(t[0], t[1])] = t[2] if t[0] != "text" else line.split(None, 2)[2]
    return out


# ---- the runtime ----------------------------------------------------------------------------------------------
def test_a_held_coils_object_and_record_are_pointer_sized():
    src = _src()
    st = src[src.index("struct held_coil {"):]
    st = st[:st.index("};")]
    assert re.search(r"\bpm_addr obj;", st) and re.search(r"\bpm_addr rec;", st)
    assert re.search(r"unsigned dev;[^\n]*\n\s*pm_addr obj;[^\n]*\n\s*unsigned id;", st)   # Spike 2's layout kept
    v = _body(src, "static unsigned coil_virtual(pm_addr obj, unsigned slot)")
    assert "*(const pm_addr *)" in v and "sizeof(pm_addr) * slot" in v
    assert "typedef unsigned (*coil_take_fn)(pm_addr, unsigned);" in src
    assert "(unsigned (*)(unsigned, unsigned))(unsigned long)coil_call" not in src
    assert "static pm_addr coil_call(" in src


def test_the_coil_table_is_read_pointer_sized():
    src = _src()
    for head in ("static pm_addr coil_find_record(struct held_coil *c)", "static void coil_list(void)"):
        b = _body(src, head)
        assert "base = *(const pm_addr *)(unsigned long)tab;" in b
        assert "maps_has(tab, sizeof(pm_addr), MAP_R)" in b
    dev = _body(src, "static int coil_device_ok(struct held_coil *c)")
    assert "pm_addr obj = 0;" in dev and "obj = ((pm_addr (*)(void))" in dev


def test_the_block_starts_are_held_pointer_sized():
    src = _src()
    for decl in ("static pm_addr block_obj[BLOCK_IDS];", "static pm_addr block_hooked[BLOCK_HOOKS];",
                 "static pm_addr place_from[BLOCK_IDS];", "static void wizard_refused(pm_addr start)\n",
                 "static void place_begin(pm_addr obj, unsigned id, unsigned up)\n"):
        assert decl in src, decl
    arm = _body(src, "static void block_arm(void)")
    assert re.search(r"\n\s*pm_addr a;", arm)
    gms = _body(src, "int pm_game_mode_start(unsigned id)")
    assert "pm_addr f;" in gms and "((void (*)(pm_addr))(unsigned long)f)(block_obj[id]);" in gms


def test_our_own_multiball_is_not_the_games(tmp_path):
    from tests import test_spike2_mode_roster as R
    src = _src()
    defines = "\n".join(line for line in src.splitlines() if line.startswith("#define OURS_MB_GRACE_MS"))
    code = "#include <stdio.h>\n" + defines + "\n" + R._lift(
        src, "static int ours_multiball(unsigned n, unsigned long now, unsigned long *ours_at)") + """
int main(void)
{
    /* served at 10000 (3 asked for: the serve answers 3 at once); a ball saved at 11000 (1 for a moment, within the
     * grace); drains to one at 40000; a game's own multiball later is the game's */
    static const unsigned n[] = { 3, 1, 3, 2, 1, 1, 3 };
    static const unsigned long at[] = { 10000, 11000, 12000, 30000, 40000, 40500, 60000 };
    unsigned long ours = 10000;
    unsigned i;
    for (i = 0; i < 7; i++) printf("%lu:%d\\n", at[i], ours_multiball(n[i], at[i], &ours));
    return 0;
}
"""
    out = dict(line.split(":") for line in R._host_run(tmp_path, code).split())
    assert {k for k, v in out.items() if v == "1"} == {"10000", "11000", "12000", "30000"}


def test_the_count_route_and_the_serve_know_our_balls():
    src = _src()
    sb = _body(src, "static int stock_balls(unsigned kinds)")
    assert sb.index("ours_multiball(n, pm_ms(), &ours_mb_at)") < sb.index("balls_multiball(n, pm_ms(), &two_since)")
    ms = _body(src, "int pm_multiball_start(unsigned balls, unsigned ballsave_s)")
    assert "if (r) ours_mb_at = pm_ms() ? pm_ms() : 1;" in ms
    tick = _body(src, "static void stock_balls_tick(void)")
    assert "ours_mb_at = 0;" in tick and "ours_multiball(n, pm_ms(), &ours_mb_at)" in tick
    bs = _body(src, "int pm_ball_save(unsigned seconds)")
    assert "ours_mb_at" not in bs                      # a one-ball save is no multiball of ours


# ---- the port ---------------------------------------------------------------------------------------------------
def test_elg_spike3_port_carries_the_multiball_coils_and_blocks():
    p = _port_lines()
    want_sites = {"balls_in_play": "0x0031ee60", "multiball_serve": "0x0031f0d0", "proc_sleep": "0x00315000",
                  "adjustment": "0x0042cb90", "coil_fire": "0x00312b70", "coil_take": "0x00184180",
                  "coil_give": "0x001842d0", "block_start_0": "0x0017a820", "block_start_1": "0x001798b0",
                  "block_start_2": "0x00173430"}
    for k, v in want_sites.items():
        assert p.get(("site", k)) == v, k
    assert {k: p.get(("data", k)) for k in ("coil_table", "coil_count", "right_gate_obj", "game_flags",
                                             "game_flag_count")} == {
        "coil_table": "0x00749300", "coil_count": "0x0073e1d8", "right_gate_obj": "0x00711730",
        "game_flags": "0x00749630", "game_flag_count": "0x005a37c8"}
    assert {k: p.get(("value", k)) for k in ("magnet_proc", "right_gate_dev", "right_gate_ctl", "right_gate_devoff",
                                              "right_gate_off_slot", "game_flags_at", "mode_flag_1", "mode_flag_2",
                                              "mode_flag_3")} == {
        "magnet_proc": "13185", "right_gate_dev": "9", "right_gate_ctl": "40", "right_gate_devoff": "8",
        "right_gate_off_slot": "30", "game_flags_at": "0", "mode_flag_1": "86", "mode_flag_2": "88", "mode_flag_3": "87"}
    assert p[("text", "held_coils")] == "right_gate"
    assert p[("text", "right_gate_drive")] == "8 2 255 64 128"
    assert [p[("text", "block_name_%d" % i)] for i in range(3)] == ["Inner Loop", "Orbits", "Ramps"]
    assert ("value", "multiball_arg3") not in p                   # the game's own 0xbb, the runtime's default


# ---- the drafter ------------------------------------------------------------------------------------------------
def test_s3port_decodes_the_new_words():
    S = _s3port()
    assert S._movz_w(0x52800D03) == (3, 0x68)                     # mov w3, #0x68
    assert S._movz_w(0x52800121) == (1, 9)                        # mov w1, #0x9
    assert S._mov_x0(0xAA0003F4) == 20                            # mov x20, x0
    assert S._mov_x0(0xAA0103F4) is None
    assert S._arm_mov_r0(0xE3A00056) == 86                        # mov r0, #86
    assert S._arm_mov_r0(0xE3A01056) is None                      # mov r1, ...
    assert S._b(0x312B8C, 0x17FFFEA5) == 0x312620                  # b 0x312620 (coil_fire's tail)


@pytest.mark.skipif(not (os.path.isfile(ELG2) and os.path.isfile(ELG3)), reason="the Star Wars ELG programs are not here")
def test_play_engine_reads_the_elg_program():
    S = _s3port()
    ref, tgt = S.Elf(ELG2), S.Elf(ELG3)
    S.scan(ref)
    S.scan(tgt)
    lines = S.read_port(str(SDK / "ports" / "star_wars_elg-1.10.port"))
    la = dict(balls_in_play=0x31ee60, multiball_serve=0x31f0d0, proc_sleep=0x315000, adjustment=0x42cb90,
              coil_fire=0x312b70)
    la["data:game_flags"] = 0x749630
    o = S.play_engine(ref, lines, tgt, la, {})
    assert o["why"] == []
    assert o["carry"] == ["balls_in_play", "multiball_serve", "proc_sleep", "adjustment", "coil_fire"]
    assert o["site"] == {"coil_take": 0x184180, "coil_give": 0x1842d0, "block_start_0": 0x17a820,
                         "block_start_1": 0x1798b0, "block_start_2": 0x173430}
    assert o["data"] == {"coil_table": 0x749300, "coil_count": 0x73e1d8, "right_gate_obj": 0x711730,
                         "game_flags": 0x749630, "game_flag_count": 0x5a37c8}
    assert o["value"] == {"magnet_proc": 13185, "right_gate_ctl": 40, "right_gate_devoff": 8,
                          "right_gate_off_slot": 30, "right_gate_dev": 9, "game_flags_at": 0,
                          "mode_flag_1": 86, "mode_flag_2": 88, "mode_flag_3": 87}
    # more than one device family has a take / give of the same shape; the gate's constructor names its own (+40)
    pairs = S.coil_control(tgt, 0x315000)
    assert sorted(p["value"]["ctl"] for p in pairs) == [40, 72]
    assert S.flag_set(tgt, 0x749630) == (0x316940, 0x5a37c8)
