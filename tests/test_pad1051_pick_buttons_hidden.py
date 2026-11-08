"""PAD-1051: the co-op character pick's buttons are the pick's alone while its ball waits in the shooter lane.

DoomWalrus666 (Godzilla): "it often changes the language when you're trying to select a new character" and "the only
way to select the character is by hitting the action button which also launches the ball"; wanted: Action takes the
character, then the flippers pick the language, then the plunger or Action launches - in co-op, Team 2v2 and 2v1 alike
(one pick, coop_chars_turn, for all three). The game's own PLAYER LANGUAGE SELECT (adjustment 14) walks on the flippers
at the same ball start, and Godzilla's Action button launches from the lane.

- The runtime's drain hook (on_switch_edge, edge_hide_press), lifted verbatim over test_spike2_switch_drain's fake
  tables: a wanted switch's handler bits are cleared at a press and come back at its first press once nothing wants
  it - never a release without its press; a shared descriptor and the untraced generation are left alone.
- The co-op rule (coop_hides, coop_edge, coop_chars_tick), lifted over test_pad1031's model game: only while a pick is
  open with the ball in the lane, and a launch takes the one shown.
- With the Godzilla LE 1.16 program present: its drain reads the bits after switch_edge returns.
"""
import os
import struct

import pytest

from tests import test_pad1031_coop_characters as C
from tests import test_spike2_switch_drain as D

DRAIN_MAIN = r"""
static void bits(const char *what, unsigned id)
{
    unsigned short f;
    if (edge.desc_via >= 0) memcpy(&f, descs_b[id] + 0x1a, 2); else memcpy(&f, recs_a[id] + 0x1e, 2);
    printf("%s 0x%04x\n", what, f);
}
int main(int argc, char **argv)
{
    unsigned in = 0x1000 + 8;
    int gen_a = !strcmp(argv[1], "A");
    base_b = (unsigned)(unsigned long)recs_b;
    base_a = (unsigned)(unsigned long)recs_a;
    edge.records = (unsigned)(unsigned long)(gen_a ? &base_a : &base_b);
    edge.count = (unsigned)(unsigned long)&count;
    edge.drain = 0x1000; edge.drain_end = 0x1180;
    edge.size = gen_a ? 0x2c : 0x20;
    edge.level_at = gen_a ? 1 : 0x18;
    edge.level_via = gen_a ? 0 : -1;
    edge.level_before = gen_a;
    edge.desc_via = gen_a ? -1 : 8;
    edge.flags_at = gen_a ? 0x1e : 0x1a;
    edge.polarity_at = gen_a ? 0x20 : 0x1c;
    edge_shots = 1;
    coop_live = 1;
    if (gen_a) { sw_a(6, 0x3800, 0); sw_a(3, 0x800, 0); }
    else {
        unsigned i;
        for (i = 1; i < 12; i++) sw_b(i, 0x2000, 0);              /* every switch its own descriptor */
        sw_b(6, 0x3800, 0); sw_b(3, 0x800, 0);
        put32(recs_b[4] + 8, (unsigned long)descs_b[3]);           /* 3 and 4 share one */
    }
    hide_id = 6;
    edge_at(6, 1, in); bits("pressed", 6);
    edge_at(6, 0, in); bits("released", 6);
    edge_at(6, 1, in); bits("pressed again", 6);
    hide_id = 0;
    edge_at(6, 0, in); bits("released, nothing wants it", 6);
    edge_at(6, 1, in); bits("the next press", 6);
    edge_at(6, 0, in); bits("its release", 6);
    hide_id = 3;
    edge_at(3, 1, in); bits("a shared descriptor", 3);
    printf("modes saw %u\n", switch_fired[6]);
    return 0;
}
"""


def _drain(tmp_path, gen):
    src = D._src()
    block = D._between(src, "static struct {\n    unsigned records, count, mode_mask, drain, drain_end;",
                       "/* The switch_edge site's tables")
    code = D._EDGE.replace("@EDGE@", block)
    code = code[:code.index("int main(int argc, char **argv)")] + DRAIN_MAIN
    return D._host_run(tmp_path, code, flags=("-fno-pie", "-no-pie", "-Wno-unused-function", "-Wno-unused-variable"),
                       args=(gen,)).splitlines()


def test_a_hidden_switch_is_hidden_from_a_press_through_its_release(tmp_path):
    out = _drain(tmp_path, "B")
    assert "pressed 0x3000" in out                                  # its handler bits held back at the press
    assert "released 0x3000" in out
    assert "pressed again 0x3000" in out
    assert "released, nothing wants it 0x3000" in out              # a release alone is never shown
    assert "the next press 0x3800" in out                           # the game sees this press, and its release
    assert "its release 0x3800" in out
    assert "a shared descriptor 0x0800" in out                      # hiding 3 would hide 4 too: left alone
    assert "modes saw 3" in out                                     # the runtime's own shots still see every press


def test_the_other_generation_hides_nothing(tmp_path):
    out = _drain(tmp_path, "A")                                      # its drain is not traced
    assert "pressed 0x3800" in out and "the next press 0x3800" in out


LANE_MAIN = r"""
static void lane(int in) { coop_edge(62, in ? 1 : 0, 0x800, 0); }
static void hides(const char *what) { printf("%s %d%d%d%d\n", what, coop_hides(60), coop_hides(59), coop_hides(34), coop_hides(36)); }
int main(void)
{
    coop_char_line("- GODZILLA 1954|");
    coop_char_line("- GODZILLA 2000|");
    coop_pick_on = 1; coop.button = 59; coop_left = 60; coop_action = 34; coop_lane = 62; coop_live = 1;
    coop.n = 2; coop.turn = 1;
    coop_chars_begin(); coop_pick_open(1);
    hides("served, not in the lane");
    lane(1); hides("in the lane");
    press(34); hides("taken, before the tick");
    coop_chars_tick(); hides("picked"); printf("t1 %d\n", coop_pick_of[1]);
    coop.turn = 2; coop_chars_turn(); lane(1);
    press(59); coop_chars_tick(); hides("t2 walking");
    now_ms += 1000; lane(0); coop_chars_tick();
    printf("t2 %d open %d\n", coop_pick_of[2], pk.open);
    coop_chars_begin(); coop.turn = 1; coop_chars_turn(); lane(1); coop_lane = 0; hides("no lane known");
    return 0;
}
"""


def test_the_pick_hides_its_buttons_only_with_the_ball_in_the_lane_and_a_launch_takes_the_one_shown(tmp_path):
    src = C.RUNTIME.read_text(encoding="utf-8")
    main = C.MAIN[:C.MAIN.index("@DECL@")] + "static int coop_live;\n@DECL@" + C.MAIN[C.MAIN.index("@DECL@") + 6:]
    main = main[:main.index("int main(void)")] + LANE_MAIN
    fns = C.FNS[:C.FNS.index("static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)")] \
        + ("static int coop_hides(unsigned id)",) \
        + C.FNS[C.FNS.index("static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity)"):]
    lifted = "\n".join(C.R._lift(src, sig + "\n{") for sig in fns)
    number = "\n".join(C.R._lift(src, sig + "\n{") for sig in ("static int hexval(int c)",
                                                              "static uint64_t number(const char **p, int *ok)"))
    out = C.R._host_run(tmp_path, main.replace("@NUMBER@", number).replace("@DECL@", C._decl(src))
                        .replace("@FNS@", lifted)).splitlines()
    assert "served, not in the lane 0000" in out                     # the ball not in the lane yet: the game's
    assert "in the lane 1110" in out                                 # flippers and Action; never Start
    assert "taken, before the tick 1110" in out                      # the taking press's release stays the pick's
    assert "picked 0000" in out and "t1 0" in out                    # then the language select and the launch
    assert "t2 walking 1110" in out
    assert "t2 1 open 0" in out                                      # launched with RANDOM shown: the one free
    assert any("the ball was launched with it shown" in line for line in out)
    assert "no lane known 0000" in out                               # as before PAD-1051


#: the Godzilla LE 1.16 program: test_pad1031's, PAD_GZ_ELF, or a rig override's copy (its own patches lie elsewhere)
ELF = next((p for p in (os.environ.get("PAD_GZ_ELF", ""), C.GZ_ELF, "C:/tmp/PAD-1031/ovr2/godzilla_le/game")
            if p and os.path.isfile(p)), "")


@pytest.mark.skipif(not os.path.isfile(ELF), reason="no Godzilla LE 1.16 program here")
def test_godzillas_drain_reads_the_handler_bits_after_switch_edge_returns():
    from elftools.elf.elffile import ELFFile
    with open(ELF, "rb") as f:
        data = f.read()
        segs = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in ELFFile(f).iter_segments()
                if s["p_type"] == "PT_LOAD"]

    def word(va):
        for v, o, n in segs:
            if v <= va < v + n:
                return struct.unpack_from("<I", data, o + va - v)[0]

    def bl_target(va):
        w = word(va)
        assert w & 0x0f000000 == 0x0b000000
        imm = w & 0xffffff
        return va + 8 + 4 * (imm - 0x1000000 if imm & 0x800000 else imm)

    assert word(0x379210) == 0xe1a00007                              # mov r0, r7 (the switch id)
    assert bl_target(0x379214) == 0x3783e4                           # bl switch_edge (the port's site)
    assert word(0x379218) == 0xeafffff2                              # b 0x3791e8
    assert word(0x3791e8) == 0xe594a008                              # ldr sl, [r4, #8]: the descriptor
    assert word(0x3791f0) == 0xe1dab1ba                              # ldrh fp, [sl, #0x1a]: its bits, read after
    assert word(0x225304) == 0xe3a0000e and bl_target(0x225308) == 0x2b3614   # the language select reads adj 14
