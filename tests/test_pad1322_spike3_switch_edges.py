"""PAD-1322: a 64-bit switch-edge source for Spike 3.

Spike 3's switch drain makes no per-switch call (Spike 2's `site switch_edge`): it walks the list of switch records
the node boards' reader queued and calls switch_hit / switch_hit2 itself. The edge source is a point INSIDE the
drain's loop that every edge passes after its level is written and before its handler bits are read (Star Wars ELG
1.10: 0x308684), hooked with hook_a64.h's hook_callee so the logger can read the record from x19.

- hook_a64.h: hook_callee saves x19..x28 for its logger and loads them back;
- pad_mode_runtime.c: on_switch_edge64 reads id / level / descriptor off the record (lifted and run on the host
  against fake records with the flag words ELG's rig showed); every feature hooks the drain through edge_hook;
- s3port.py: switch_edge_point reads the point and the record layout off a program's own drain (ELG's real words);
  edge_lines writes them in place of Spike 2's switch_edge lines; both Spike 3 ports carry them;
- on the real programs (PAD_S3_PROGRAMS, as test_pad1287's): one point on each of the seven Spike 3 titles.

Emulator proof (2026-11-15, Spike 3 rig slots 91 / 92, hidden and muted; tools/spike3_emu/proofs PROOF=edge): ELG
1.10 and Walking Dead Remastered 0.92 each started a mode on three trigger hits and scored six shots through the
drain's edges; flipper buttons in attract carried the mode mask's attract bit; slingshots and pop bumpers (no
handler of the game's) came through as edges too.
"""
import hashlib
import os
import pathlib
import sys

import pytest

from tests.test_spike2_mode_roster import _host_run, _lift

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
HOOK = SDK / "hook_a64.h"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports" / "spike3"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
sys.path.insert(0, str(ROOT / "tools" / "spike3_emu"))
import s3port as S  # noqa: E402

PROGS = os.environ.get("PAD_S3_PROGRAMS", "")


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


# ---- the hook layer ---------------------------------------------------------------------------------------------
def test_hook_callee_hands_the_logger_x19_to_x28_and_loads_them_back():
    h = HOOK.read_text(encoding="utf-8")
    body = _between(h, '"pm_a64_callee:\\n"', '".previous\\n"')
    for a, b, off in (("x19", "x20", 16), ("x21", "x22", 32), ("x23", "x24", 48), ("x25", "x26", 64),
                      ("x27", "x28", 80)):
        assert '"    stp  %s, %s, [sp, #%d]\\n"' % (a, b, off) in body
        assert '"    ldp  %s, %s, [sp, #%d]\\n"' % (a, b, off) in body
    assert body.index('"    add  x2, sp, #16\\n"') < body.index('"    bl   pm_a64_callee_call\\n"')
    assert 'void pm_a64_callee_call(pm_reg *r, unsigned n, pm_reg *x)' in h
    assert 'visibility("hidden")' in _between(h, "__attribute__((used", "pm_a64_callee_call")
    fn = _lift(h, "static int hook_callee(")
    assert "hook_n(addr, (hook_n_fn)pm_a64_callee, (unsigned)k)" in fn
    # the 32-bit hook_full's r4-r12 layout is Spike 2's: the 64-bit one still refuses
    assert "return 0;" in _lift(h, "static int hook_full(")


# ---- the runtime ------------------------------------------------------------------------------------------------
def test_every_drain_feature_hooks_through_edge_hook():
    c = _src()
    assert c.count("edge_hook(e)") == 6                     # PAD-1326: co-op's button and the handicaps' flippers
    assert c.count("hook(e->addr, on_switch_edge)") == 1           # edge_hook's Spike 2 branch
    hook = _lift(c, "static int edge_hook(")
    assert "hook_callee(e->addr, on_switch_edge64)" in hook and "#if PM_A64" in hook
    arm = _lift(c, "static int edge_arm(")
    assert "return edge64_arm(why);" in arm
    held = _lift(c, "static int switch_held(unsigned id)\n{")
    assert "return edge64_held(id);" in held


_EDGE64 = r"""
#include <stdio.h>
#include <string.h>
/* the harness's prelude declares Spike 2's 32-bit pm_addr / pm_reg: this code is the 64-bit runtime's */
#define pm_addr unsigned long
#define pm_reg unsigned long
#undef PMA
#define PMA "lx"
#define N_SWITCH_IDS 256
#define SYS_GETTID 186
#define MAP_R 1
static long fake_syscall(long n) { (void)n; return 7; }
#define syscall fake_syscall
static void say(const char *fmt, ...) { (void)fmt; }
static int in_game = 1;
int pm_in_game(void) { return in_game; }
static volatile unsigned switch_fired[N_SWITCH_IDS];
static void lit_hold_check(unsigned id) { (void)id; }
static int att_live, gms_live, coop_live, edge_shots = 1;
static unsigned att_n;
static void att_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity, unsigned mask) { att_n++; }
static void gms_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity) {}
static void coop_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity) {}
static long edge_log_left;
static struct { unsigned mode_mask; } edge;
static unsigned short mask_word;
static long pm_port_value(const char *n, long f)
{
    static const struct { const char *n; long v; } v[] = { {"switch_record_reg", 19}, {"switch_id_at", 0x20},
        {"switch_level_at", 0x28}, {"switch_desc_via", 0x10}, {"switch_flags_at", 0x2e}, {"switch_polarity_at", 0x30} };
    unsigned i;
    for (i = 0; i < sizeof v / sizeof v[0]; i++) if (!strcmp(v[i].n, n)) return v[i].v;
    return f;
}
static int have_values(const char *const *n) { for (; *n; n++) if (pm_port_value(*n, -1) < 0) return 0; return 1; }
static pm_addr data(const char *n) { return !strcmp(n, "mode_mask") ? (pm_addr)&mask_word : 0; }
static int maps_has(pm_addr a, unsigned n, int how) { return 1; }
@HIT@
@EDGE@
/* ELG 1.10's records (0x30 bytes here) and descriptors, the flag words its rig run showed */
static unsigned char recs[8][0x30] __attribute__((aligned(8)));
static unsigned char descs[8][0x40] __attribute__((aligned(8)));
static void sw(int k, unsigned id, unsigned flags, unsigned pol)
{
    pm_addr d = (pm_addr)descs[k];
    memcpy(recs[k] + 0x20, &(unsigned short){ (unsigned short)id }, 2);
    memcpy(recs[k] + 0x10, &d, 8);
    memcpy(descs[k] + 0x2e, &(unsigned short){ (unsigned short)flags }, 2);
    memcpy(descs[k] + 0x30, &(unsigned short){ (unsigned short)pol }, 2);
}
static void edge_of(int k, unsigned level)
{
    pm_reg r[11] = {0}, x[10] = {0};
    recs[k][0x28] = (unsigned char)level;
    x[0] = (pm_reg)recs[k];                       /* x19 */
    on_switch_edge64(r, x);
}
int main(void)
{
    const char *why = 0;
    if (!edge64_arm(&why)) { printf("arm %s\n", why); return 1; }
    sw(0, 33, 0x2400, 0x0003);                    /* CENTER TARGET: handler on the level-0 edge, switch_hit */
    sw(1, 54, 0x0000, 0x0020);                    /* RIGHT SLINGSHOT: no handler - its closed level (0) */
    sw(2, 50, 0x0000, 0x0020);                    /* R FLIPPER BUTTON */
    sw(3, 28, 0x1400, 0x0003);                    /* LEFT LUKE ORBIT: switch_hit2 */
    edge_of(0, 0); edge_of(0, 1);                 /* a press: one hit */
    edge_of(1, 0); edge_of(1, 1);
    edge_of(3, 0); edge_of(3, 1);
    printf("%u %u %u\n", switch_fired[33], switch_fired[54], switch_fired[28]);
    edge_of(2, 0); printf("held %d\n", edge64_held(50)); edge_of(2, 1); printf("held %d\n", edge64_held(50));
    printf("never %d\n", edge64_held(51));
    mask_word = 0x0110; in_game = 0; att_live = 1;  /* attract: the mask's attract bit, no hits counted */
    edge_of(0, 0); edge_of(0, 1);
    printf("attract %u %u\n", switch_fired[33], att_n);
    in_game = 1; mask_word = 0x0010;              /* the mask shares no bit with the target's flags: no hit */
    edge_of(0, 0);
    printf("masked %u\n", switch_fired[33]);
    recs[0][0x10] = 0; memset(recs[0] + 0x10, 0, 8);   /* a record with no descriptor: the source turns off */
    edge_of(0, 0); mask_word = 0; edge_of(3, 0);
    printf("bad %u\n", switch_fired[28]);
    return 0;
}
"""


def test_a_spike3_edge_is_a_hit_on_the_edge_the_game_acts_on(tmp_path):
    src = _src()
    block = _between(src, "static struct { pm_addr mask; long reg", "#endif\n\n/* the drain's hook, once")
    code = _EDGE64.replace("@HIT@", _lift(src, "static int edge_is_hit(")).replace("@EDGE@", block)
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function", "-Wno-unused-variable",
                                           "-Wno-unused-parameter")).splitlines()
    assert out == ["1 1 1", "held 1", "held 0", "never 0", "attract 1 2", "masked 1", "bad 1"], out


# ---- s3port: the drain's per-edge point --------------------------------------------------------------------------
# Star Wars ELG 1.10 (Spike 3, games/game sha1 ceb8d70b...), 0x3085c0..0x308770: the switch drain
ELG_DRAIN = 0x3085C0
ELG_DRAIN_WORDS = [
    0xa9ba53f3, 0xa9036bf9, 0xf00021f4, 0x911f8299, 0x91008320, 0xf9002bfe, 0x97f8120a, 0xf9402f33, 0xb4000b13,
    0xa9015bf5, 0xf00021fa, 0x9129e35a, 0x52800616, 0xb0001c95, 0xf942eeb5, 0xa90473fb, 0xb0001c9b, 0xf9402b7b,
    0xa90263f7, 0xf9002f3f, 0x39409262, 0x79404661, 0x79404e64, 0x8b020440, 0x79404277, 0xd37ef400, 0xd3433c23,
    0xcb020000, 0x12000821, 0x8b001340, 0xf240009f, 0x8b030000, 0x39408000, 0x1ac12400, 0x12000000, 0x52000001,
    0x1a800020, 0x3900a260, 0x34000177, 0xf9400361, 0x2a1703e2, 0xeb37203f, 0x540000e9, 0xf9400321, 0xf9400f23,
    0x9bb606e1, 0xf9400821, 0x79406421, 0x78227861, 0xf9400a78, 0x79405f1c, 0x79406301, 0x34000480, 0x37080401,
    0x3658021c, 0x794002a0, 0x34000060, 0x6a00039f, 0x54000180, 0xf9400301, 0xb4000101, 0x79405b02, 0x79406b00,
    0x9400319d, 0xb4000080, 0xb9400b01, 0x79021017, 0xb9011001, 0x3768045c, 0x3760049c, 0x79404e60, 0xf272039f,
    0xf9400662, 0x51000400, 0x12003c01, 0x12000000, 0x1a800021, 0x79004e61, 0x34000081, 0xf9402f20, 0xf9002f33,
    0xf9000660, 0xb4000162, 0xaa0203f3, 0x17ffffc0, 0xf9400b20, 0x3837481f, 0x17ffffdf, 0x36100061, 0xf9400b20,
    0x3837481f, 0x3657fd7c, 0x17ffffdb, 0xa9415bf5, 0xa94263f7, 0xa94473fb, 0x911f8280, 0x91008000, 0xa9436bf9,
    0xf9402bfe, 0xa8c653f3, 0x17f81067, 0x2a1703e0, 0x94048abd, 0x17ffffde, 0x2a1703e0, 0x94048b06, 0x17ffffdb]


def _elg_words():
    """the real words, from tests' constant (the dump in the docstring's range; checked against the program when
    PAD_S3_PROGRAMS has it)"""
    p = os.path.join(PROGS, "star_wars_elg.game")
    if PROGS and os.path.exists(p):
        t = S.Elf(p)
        return [t.u32(ELG_DRAIN + 4 * k) for k in range(len(ELG_DRAIN_WORDS))]
    return ELG_DRAIN_WORDS


class _Prog:
    """an Elf stand-in holding the drain alone (and the GOT slot its mode-mask load reads)"""
    def __init__(self, words):
        self.words, self.tva, self.ptr = tuple(words), ELG_DRAIN, {0x6995D8: 0x79206C}

    def u32(self, va):
        k = (va - self.tva) // 4
        return self.words[k] if 0 <= k < len(self.words) else None


def test_the_drafter_reads_elgs_edge_point_and_record_layout_off_its_drain():
    words = _elg_words()
    if words is not ELG_DRAIN_WORDS:
        assert words == ELG_DRAIN_WORDS
    e = S.switch_edge_point(_Prog(words))
    assert e == {"site": 0x308684, "reg": 19, "id_at": 0x20, "level_at": 0x28, "desc_via": 0x10, "flags_at": 0x2E,
                 "polarity_at": 0x30, "mode_mask": 0x79206C}


def test_edge_lines_put_the_point_in_place_of_spike2s_switch_edge_lines():
    body = ["# ---- functions", "site tick 0x1 0x2 0x3",
            "# site switch_edge      NOT ON SPIKE 3: its drain has no per-switch edge call (PAD-1285)",
            "# not carried - the 64-bit drain calls switch_hit ...: site switch_drain     0x003085c0 0xa9ba53f3 0x0",
            "", "# ---- globals: data <name> <address> ----", "data mode_mask              0x0079206c   # x",
            "# data switch_records         NOT PLACED: 5 of 5 paired functions agree",
            "# not carried (64-bit layout, measure it): value switch_record_size    0x20",
            "# not carried (64-bit layout, measure it): value switch_level_at       0x18"]
    placed, notes = {"data:mode_mask": 0x79206C}, []
    S.edge_lines(_Prog(ELG_DRAIN_WORDS), body, placed, notes)
    text = "\n".join(body)
    assert "NOT ON SPIKE 3" not in text and "switch_records" not in text and "switch_record_size" not in text
    assert "site switch_edge      0x00308684 0xf9400a78 0x79405f1c" in body
    for name, v in (("switch_record_reg", "19"), ("switch_id_at", "0x20"), ("switch_level_at", "0x28"),
                    ("switch_desc_via", "0x10"), ("switch_flags_at", "0x2e"), ("switch_polarity_at", "0x30")):
        assert any(l.split()[:3] == ["value", name, v] for l in body), name
    assert body.index("site switch_edge      0x00308684 0xf9400a78 0x79405f1c") < body.index(
        "# ---- globals: data <name> <address> ----")
    assert placed["switch_edge"] == 0x308684 and notes == []
    assert sum(1 for l in body if l.startswith("data mode_mask")) == 1


def test_a_mode_mask_the_drain_disagrees_with_is_noted():
    body, notes = ["# ---- globals: data <name> <address> ----"], []
    S.edge_lines(_Prog(ELG_DRAIN_WORDS), body, {"data:mode_mask": 0x700000}, notes)
    assert notes == ["data mode_mask: 0x700000 written, the switch drain tests 0x79206c"]


@pytest.mark.parametrize("port,site", [("star_wars_elg-1.10.port", 0x308684),
                                       ("walking_dead_remastered_le-0.92.port", 0x2C6C94)])
def test_both_spike3_ports_carry_the_edge_point(port, site):
    lines = (PORTS / port).read_text(encoding="utf-8").splitlines()
    assert "site switch_edge      0x%08x 0xf9400a78 0x79405f1c" % site in lines
    vals = {l.split()[1]: l.split()[2] for l in lines if l.startswith("value ")}
    assert {k: vals.get(k) for k in S.EDGE_VALUES} == {
        "switch_record_reg": "19", "switch_id_at": "0x20", "switch_level_at": "0x28", "switch_desc_via": "0x10",
        "switch_flags_at": "0x2e", "switch_polarity_at": "0x30"}
    text = "\n".join(lines)
    assert "NOT ON SPIKE 3" not in text and "switch_drain" not in text
    assert "value switch_edge_log" not in text            # the proof's log is the run's own copy, not the port's
    assert sum(1 for l in lines if l.startswith("data mode_mask")) == 1


def test_the_proof_recipe_has_the_edge_run():
    play = (PROOFS / "play.sh").read_text(encoding="utf-8")
    assert "\nedge)\n" in play and "FLIP_SWS" in play and "NOHANDLER_SWS" in play
    assert '[ "$COINS" -gt 0 ] && { $P coin "$SLOT" "$COINS"; sleep 3; }' in play
    assert 'sleep "${ATTRACT_WAIT:-20}"' in play
    assert (PROOFS / "modes" / "edge.cfg").exists() and (PROOFS / "modes" / "edge_wdr.cfg").exists()


# ---- on the real programs ----------------------------------------------------------------------------------------
SPIKE3 = {"fallout_le": 0x71B8B4, "pokemon_le": 0x59E444, "star_wars_2025_le": 0x593414,
          "star_wars_2025_pro": 0x2B94D4, "star_wars_elg": 0x308684, "transformers_mtmte_le": 0x4A49B4,
          "walking_dead_remastered_le": 0x2C6C94}


@pytest.mark.parametrize("game", sorted(SPIKE3))
def test_every_spike3_title_has_one_edge_point_of_the_same_layout(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    t = S.Elf(p)
    e = S.switch_edge_point(t)
    if e is None or e["site"] != SPIKE3[game]:
        with open(p, "rb") as f:
            pytest.skip("%s.game is another build (sha1 %s)" % (game, hashlib.sha1(f.read()).hexdigest()[:8]))
    assert (e["reg"], e["id_at"], e["level_at"], e["desc_via"], e["flags_at"], e["polarity_at"]) == (
        19, 0x20, 0x28, 0x10, 0x2E, 0x30)
    assert e["mode_mask"]
