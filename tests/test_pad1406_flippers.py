"""PAD-1406: the flippers off and back on for a mode that is the whole game (pm_flippers), through the framework's
all-flippers off and on (`site flippers_off` / `flippers_on`, PAD-733's pair, now on every newest build).

The runtime's section (pad_mode_runtime.c "PAD-1406: the flippers") lifted verbatim and run on the host against stubs
of the game; every newest port's two lines (against the game programs when they are here); the Flippers block."""
import os
import pathlib
import re
import struct

import pytest

from tests.test_spike2_mode_roster import _host_run

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
ELF_DIRS = [os.environ.get("PAD_SPIKE2_ELF_DIR", ""), r"C:\tmp\PAD-1400\elf", "/mnt/c/tmp/PAD-1400/elf"]
#: the newest build of every title (docs/plans/pad1400_own_game.md: 53)
def _newest():
    best = {}
    for p in (SDK / "ports").glob("*.port"):
        game, ver = p.stem.rsplit("-", 1)
        v = tuple(int(x) for x in ver.split("."))
        if game not in best or v > best[game][0]:
            best[game] = (v, p.stem)
    return sorted(k for _v, k in best.values())


NEWEST = _newest()


def _section(src):
    a = src.index("/* ---- PAD-1406: the flippers, for a mode that is the whole game")
    b = src.index("/* PAD-1406: the calling mode has the whole game", a)
    c = src.index("/* the route lets go: back = the ball goes on", b)
    return src[a:b] + src[c:src.index("/* ---- shots from the switch drain (optional; any build)", c)]


def test_it_is_the_game_s_own_switch_and_wired_in():
    src = RUNTIME.read_text(encoding="utf-8")
    sec = re.sub(r"/\*.*?\*/", "", _section(src), flags=re.S)
    for call in ("coil_fire", "proc_create", "coil_off", "spare_drive"):
        assert call not in sec, call                                # nothing powers a coil
    assert "    fl_tick();" in src
    assert 'fl_done("the ball ended", 0);' in src                    # the game's next ball brings them back
    assert src.count('fl_done("the mode') == 2                       # pm_own_game(0) and the mode's end: back on
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert "int pm_flippers(int on);" in hdr and "int pm_flippers_off(void);" in hdr


HOST = r"""#include <stdio.h>
#include <stdarg.h>
struct pm_mode { const char *name; };
static const struct pm_mode game = { "UNCANNY GAME" }, other = { "OTHER" };
static const struct pm_mode *current = &game;
static struct { const struct pm_mode *owner; int tilted; } og = { &game, 0 };
static struct { int state; } dto;
static unsigned long now = 1000;
static int in_game = 1, tilted, has_sites = 1;
static void say(const char *f, ...) { va_list ap; va_start(ap, f); vprintf(f, ap); va_end(ap); putchar('\n'); }
static int pm_snprintf(char *o, unsigned long n, const char *f, ...)
{ va_list ap; int r; va_start(ap, f); r = vsnprintf(o, n, f, ap); va_end(ap); return r; }
static unsigned long pm_ms(void) { return now; }
static int pm_in_game(void) { return in_game; }
static int ball_tilted(void) { return tilted; }
static void g_off(void) { printf("FLIPPERS OFF\n"); }
static void g_on(void) { printf("FLIPPERS ON\n"); }
static int has_query = 1;
static unsigned long (*wrapped)(unsigned long, unsigned long, unsigned long, unsigned long);
static unsigned long q_game(unsigned long id, unsigned long args, unsigned long a2, unsigned long a3)
{ ((unsigned *)args)[1] = 2; printf("GAME POLICY %lx\n", id); return 1; }   /* a listener of the game's: on */
static unsigned hook_call(unsigned a, void *w)
{ wrapped = (unsigned long (*)(unsigned long, unsigned long, unsigned long, unsigned long))w; printf("WRAP %x\n", a);
  return (unsigned)(unsigned long)q_game; }
static unsigned long fn(const char *n)
{
    if (!has_sites) return 0;
    if (!__builtin_strcmp(n, "flippers_off")) return (unsigned long)g_off;
    if (!__builtin_strcmp(n, "flippers_on")) return (unsigned long)g_on;
    if (!__builtin_strcmp(n, "flipper_query_call")) return has_query ? 0x3ca39cul : 0;
    return 0;
}
static unsigned args[2];
static void policy(void)
{ unsigned long r; args[0] = 0; args[1] = 1; r = wrapped(0x40, (unsigned long)args, 0, 0); printf("POLICY %lu %u\n", r, args[1]); }
"""

MAIN = r"""
int main(void)
{
    puts("== A");                                         /* off, ticks keep them off, back on */
    printf("R %d\n", pm_flippers(0));
    printf("R %d OFF %d\n", pm_flippers(0), pm_flippers_off());   /* already off: no second call */
    fl_tick(); fl_tick();
    now = 4000; printf("R %d\n", pm_flippers(1));
    printf("R %d\n", pm_flippers(1));                     /* on again: not switched off by a mode */
    puts("== B");                                         /* the ball ends: the game's next ball brings them back */
    pm_flippers(0); fl_done("the ball ended", 0);
    puts("== C");                                         /* the mode ends mid-ball: back on */
    pm_flippers(0); fl_done("the mode ended", 1);
    puts("== D");                                         /* a tilt: off stays the game's, never back on */
    pm_flippers(0); og.tilted = 1; fl_tick(); fl_done("the mode ended", 1);
    printf("R %d\n", pm_flippers(1)); printf("R %d\n", pm_flippers(0)); og.tilted = 0;
    puts("== E");                                         /* not the whole game's mode */
    current = &other; printf("R %d\n", pm_flippers(0)); current = &game;
    og.owner = 0; printf("R %d\n", pm_flippers(0)); og.owner = &game;
    puts("== F");                                         /* no game, a drain to one, no sites */
    in_game = 0; printf("R %d\n", pm_flippers(0)); in_game = 1;
    dto.state = 1; printf("R %d\n", pm_flippers(0)); dto.state = 0;
    has_sites = 0; printf("R %d\n", pm_flippers(0)); has_sites = 1;
    puts("== H");                                         /* the game's policy: answered off while off, its own else */
    pm_flippers(0); policy(); pm_flippers(1); policy();
    puts("== G");                                         /* the game ends while they are off */
    pm_flippers(0); in_game = 0; fl_tick(); in_game = 1; printf("OFF %d\n", pm_flippers_off());
    return 0;
}
"""


def test_off_on_and_every_limit(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    out = _host_run(tmp_path, HOST + _section(src) + MAIN, flags=("-no-pie", "-Wno-unused-function"))
    p = dict(re.findall(r"== (\w+)\n(.*?)(?=\n== |\Z)", out, re.S))
    a = p["A"]
    assert a.count("FLIPPERS OFF") == 3                    # the off, then once a tick
    assert "R 1 OFF 1" in a and a.count("FLIPPERS ON") == 1 and "back on after 3000 ms" in a
    assert "they were not switched off by a mode" in a and a.rstrip().endswith("R 0")
    assert "FLIPPERS ON" not in p["B"] and "the game brings them back" in p["B"]
    assert "FLIPPERS ON" in p["C"] and ": back on" in p["C"]
    d = p["D"]
    assert "FLIPPERS ON" not in d and "the ball was tilted" in d and "the ball is tilted" in d
    assert d.count("R 0") == 2
    assert p["E"].count("R 0") == 2 and "only the mode that has the whole game" in p["E"] and "FLIPPERS" not in p["E"]
    f = p["F"]
    assert f.count("R 0") == 3 and "FLIPPERS" not in f
    assert "no game in play" in f and "drain to one" in f and "names no flippers off/on" in f
    a2 = p["A"]
    assert a2.count("WRAP 3ca39c") == 1                     # wrapped once, at the first off
    h = p["H"]
    assert "POLICY 1 1" in h and h.index("POLICY 1 1") < h.index("GAME POLICY 40")   # off: answered 1, not asked
    assert h.rstrip().endswith("POLICY 1 2")                # on: the game's own listener answers
    assert "the game ended" in p["G"] and "FLIPPERS ON" not in p["G"] and "OFF 0" in p["G"]


def _elf(key):
    for d in ELF_DIRS:
        if d and os.path.isfile(os.path.join(d, key)):
            return os.path.join(d, key)
    return None


def test_every_newest_build_has_them():
    assert len(NEWEST) >= 53
    for key in NEWEST:
        text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
        assert re.search(r"^site flippers_off\s", text, re.M) and re.search(r"^site flippers_on\s", text, re.M), key


@pytest.mark.parametrize("key", NEWEST)
def test_the_lines_are_the_framework_pair(key):
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    lines = {m.group(1): (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16))
             for m in re.finditer(r"^site (flippers_off|flippers_on)\s+(0x[0-9a-f]{8}) (0x[0-9a-f]{8}) (0x[0-9a-f]{8})",
                                  text, re.M)}
    assert lines["flippers_on"][0] - lines["flippers_off"][0] == 0xd4          # the same framework file everywhere
    q = re.search(r"^site flipper_query_call\s+(0x[0-9a-f]{8}) (0x[0-9a-f]{8}) (0x[0-9a-f]{8})", text, re.M)
    assert q and int(q.group(1), 16) == lines["flippers_on"][0] + 0xbc          # the flipper policy's hook 0x40 call
    assert int(q.group(2), 16) >> 24 == 0xeb and int(q.group(3), 16) == 0xe3500000   # bl, then cmp r0, #0
    elf = _elf(key)
    if not elf:
        pytest.skip("no %s game program here" % key)
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        e = ELFFile(f)
        segs = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in e.iter_segments() if s["p_type"] == "PT_LOAD"]
        for name, (va, w0, w1) in lines.items():
            v, o, _n = next(s for s in segs if s[0] <= va < s[0] + s[2])
            f.seek(o + va - v)
            body = struct.unpack("<31I", f.read(124))
            assert body[:2] == (w0, w1), name
            # each flipper record's enable bit (+6, 2) cleared / set, under the list's lock
            assert (0xe3c33002 in body) == (name == "flippers_off"), name      # bic r3, r3, #2
            assert (0xe3833006 in body) == (name == "flippers_on"), name       # orr r3, r3, #6


def _program(game_modes, to="off"):
    from pinball_decryptor.plugins.stern import block_modes as BM
    p = BM.normalize({"name": "FLIP", "game_modes": game_modes,
                      "scripts": [{"hat": {"kind": "shot", "shot": "Left ramp"}, "do": [{"op": "flippers", "to": to}]}]})
    return BM, p


def test_the_block_is_the_whole_game_s_alone():
    BM, p = _program("own_game")
    assert not [x for x in BM.problems(p, shots=["Left ramp"], flippers=True) if "flipper" in x]
    assert [x for x in BM.problems(p, shots=["Left ramp"], flippers=False) if "cannot do on this card" in x]
    BM, p = _program("block")
    assert [x for x in BM.problems(p, shots=["Left ramp"], flippers=True) if "only a mode that is the whole game" in x]
    BM, p = _program("own_game", to="sideways")
    assert [x for x in BM.problems(p, shots=["Left ramp"], flippers=True) if "off, or back on" in x]


@pytest.mark.parametrize("to,arg", [("off", 0), ("on", 1)])
def test_the_block_writes_pm_flippers(to, arg):
    BM, p = _program("own_game", to)
    assert "if (run.on && !pm_flippers(%d)) pm_log(\"the flippers stay as they are\");" % arg in BM.to_c(p, "flip")


def test_the_profiles_say_so():
    from pinball_decryptor.plugins.stern import mode_project as MP
    keys = {k for k, p in MP.profiles().items() if getattr(p, "flippers", False)}
    assert len(keys) >= 53, len(keys)
    assert any("uncanny_xmen_pro" in k for k in keys) and any("uncanny_xmen_le" in k for k in keys)


def test_the_editor_knows_the_block():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_blocks.js").read_text(encoding="utf-8")
    assert '{ op: "flippers", to: "off" }' in js and 'case "flippers":' in js and "ch.flippers_off" in js
    views = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_views.js").read_text(encoding="utf-8")
    assert 'flippers: "mech"' in views and 'case "flippers":' in views


SHIM = ROOT / "tools" / "spike2_emu" / "hwshim.c"
SHIM_HOST = r"""#include <stdio.h>
static struct { unsigned char rule_pwr[16][16], rule_in[16][16]; unsigned rule_sets; } shm, *led_shm = &shm;
static unsigned led_shm_len = 16384;
static void led_map(void) {}
"""
SHIM_MAIN = r"""
static void put(unsigned char *f, int n) { unsigned s = 0; int i; for (i = 0; i < n - 2; i++) s += f[i]; f[n - 2] = (unsigned char)(0x100 - (s & 0xff)); }
int main(void)
{
    unsigned char full[52] = { 0x88, 0x31, 0x41, 0x05, 0xf5, 0x04 }, shrt[6] = { 0x88, 0x03, 0x41, 0x05, 0, 0 };
    full[26] = 0x40 | 25;
    put(full, 52); coil_rule_note(full, 52);
    printf("SET %u %u %u\n", shm.rule_pwr[8][5], shm.rule_in[8][5], shm.rule_sets);
    put(shrt, 6); coil_rule_note(shrt, 6);
    printf("SHORT %u %u %u\n", shm.rule_pwr[8][5], shm.rule_in[8][5], shm.rule_sets);
    coil_rule_note(full, 52); shrt[4] ^= 1; coil_rule_note(shrt, 6);      /* a bad checksum changes nothing */
    printf("BAD %u %u\n", shm.rule_pwr[8][5], shm.rule_sets);
    return 0;
}
"""


def test_the_shim_reads_a_short_rule_clear(tmp_path):
    """D&D LE/Pro 1.10 and Metallica 1.04 clear a coil's rule with `41 <coil>` alone (`88 03 41 05 2f 00`, PAD_NB_TRACE):
    the rig's rule table (padled v7, the VPX bridge's live-coil list) must show the flipper dead then too."""
    src = SHIM.read_text(encoding="utf-8")
    a = src.index("static void coil_rule_note(const unsigned char *p, int n)")
    body = src[a:src.index("\n}\n", a) + 3]
    out = _host_run(tmp_path, SHIM_HOST + body + SHIM_MAIN, flags=("-Wno-unused-function",))
    assert "SET 245 89 1" in out                    # 0x40 | 25 kept as the shim stores it
    assert "SHORT 0 0 2" in out
    assert "BAD 245 3" in out


# ---- the game's own devices (run 2) ------------------------------------------------------------------------------------

def test_pulse_refuses_every_limit(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    a = src.index("static int pulse_refuses(")
    body = src[a:src.index("\n}\n", a) + 3]
    main = r"""
int main(void)
{
    printf("%d %d %d %d %d %d %d %d\n", pulse_refuses(1, 1, 1, 0, 0, ~0ul, 0), pulse_refuses(0, 1, 1, 0, 0, ~0ul, 0),
           pulse_refuses(1, 0, 1, 0, 0, ~0ul, 0), pulse_refuses(1, 1, 0, 0, 0, ~0ul, 0), pulse_refuses(1, 1, 1, 1, 0, ~0ul, 0),
           pulse_refuses(1, 1, 1, 0, 1, ~0ul, 0), pulse_refuses(1, 1, 1, 0, 0, 999, 0), pulse_refuses(1, 1, 1, 0, 0, 1000, 20));
    return 0;
}
"""
    out = _host_run(tmp_path, "#include <stdio.h>\n#define PULSE_GAP_MS 1000ul\n#define PULSE_PER_MIN 20u\n" + body + main)
    assert out.split() == ["0", "1", "2", "3", "4", "5", "6", "7"]


def test_the_held_coils_check_the_whole_game_and_pulses_are_the_game_s_own():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"%s_own_game", c->name' in src and "only the mode that has the whole game may (pm_own_game)" in src
    sec = src[src.index("/* ---- PAD-1406: a game device's own one-shot"):src.index("/* the route lets go: back = the ball")]
    sec = re.sub(r"/\*.*?\*/", "", sec, flags=re.S)
    assert "coil_fire" not in sec and '"%s_fire", name' in sec            # the game's own function, never a pulse of ours
    assert "#define COILS_MAX 10" in src and "coil_proc9" in src
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert "int pm_coil_pulse(const char *name);" in hdr and "int pm_coil_pulse_known(const char *name);" in hdr


XMEN = {"uncanny_xmen_le-0.98": {"cerebro_post": "9 6 a171 a172 a173 3500", "sentinel_jaw": "9 2 a188 a189 a190 5000",
                                 "sentinel_hand": "9 7 a176 a177 a178 3000", "sentinel_finger": "9 8 a180 a181 a182 3000",
                                 "fire": (0x337dc, 0xe3a000c0)},
        "uncanny_xmen_pro-0.98": {"cerebro_post": "9 6 a171 a172 a173 3500", "sentinel_jaw": "9 2 a175 a176 a177 5000",
                                  "fire": (0x30148, 0xe3a000b3)}}


@pytest.mark.parametrize("key", sorted(XMEN))
def test_the_x_men_devices(key):
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    want = XMEN[key]
    held = re.search(r"^text held_coils\s+(.*)$", text, re.M).group(1).split()
    for name, drive in want.items():
        if name == "fire":
            continue
        assert name in held
        assert re.search(r"^text %s_drive %s$" % (name, re.escape(drive)), text, re.M)
        assert re.search(r"^value %s_own_game 1$" % name, text, re.M) and re.search(r"^value %s_off_adj \d+$" % name, text, re.M)
    va, w1 = want["fire"]
    assert re.search(r"^site sentinel_kick_fire 0x%08x 0xe92d4010 0x%08x$" % (va, w1), text, re.M)
    assert re.search(r"^text pulse_coils sentinel_kick$", text, re.M)
    elf = _elf(key)
    if elf:
        from elftools.elf.elffile import ELFFile
        with open(elf, "rb") as f:
            e = ELFFile(f)
            v, o, _n = next((s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in e.iter_segments()
                            if s["p_type"] == "PT_LOAD" and s["p_vaddr"] <= va < s["p_vaddr"] + s["p_filesz"])
            f.seek(o + va - v)
            body = struct.unpack("<14I", f.read(56))
            assert body[0] == 0xe92d4010 and body[13] >> 24 == 0xeb and body[12] == 0xe3a0000c   # ... mov r0,#12; bl coil_fire


def test_profiles_and_blocks_know_the_devices():
    from pinball_decryptor.plugins.stern import mode_project as MP, block_modes as BM
    P = MP.profiles()
    le, pro = P["uncanny_xmen_le_0_98"], P["uncanny_xmen_pro_0_98"]
    assert dict(le.own_game_coils).keys() == {"cerebro_post", "sentinel_jaw", "sentinel_hand", "sentinel_finger"}
    assert dict(pro.own_game_coils).keys() == {"cerebro_post", "sentinel_jaw"}
    assert dict(le.pulse_coils) == dict(pro.pulse_coils) == {"sentinel_kick": "Sentinel kicking target"}
    assert "cerebro_post" not in dict(le.held_coils)                     # never offered to an ordinary mode
    for gm, ok in (("own_game", True), ("block", False)):
        prog = BM.normalize({"name": "X", "game_modes": gm, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
            {"op": "hold", "what": "sentinel_jaw", "ms": {"k": "num", "v": 2000}}, {"op": "pulse", "what": "sentinel_kick"}]}]})
        probs = [x for x in BM.problems(prog, **BM.card_checks(pro)) if "jaw" in x or "sentinel_kick" in x]
        assert (probs == []) == ok, probs
    prog = BM.normalize({"name": "X", "game_modes": "own_game", "scripts": [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "pulse", "what": "sentinel_kick"}]}]})
    assert 'if (run.on && !pm_coil_pulse("sentinel_kick")) pm_log("sentinel_kick: not fired");' in BM.to_c(prog, "x")


def test_a_switch_is_found_by_the_game_s_own_name(tmp_path):
    """Drain to one finds the shooter lane and the trough by name on any build (Uncanny X-Men: "Shooter Lane",
    "Trough 1" - mixed case), where the port names no shooter_lane_switch and no Trough shot."""
    src = RUNTIME.read_text(encoding="utf-8")
    a = src.index("static long sw_by_name(const char *name)")
    body = src[a:src.index("\n}\n", a) + 3]
    host = r"""#include <stdio.h>
#define SW_ENT 32u
#define SWN_MAX 1024u
#define MAP_R 1u
static const char *names[] = { 0, "QR SCANNER", "Shooter Lane", "Upper Shooter Lane", "Trough 1 ", "Trough 10" };
static pm_addr swn_entries(void) { return 0x1000u; }
static const char *swn_name(pm_addr e) { unsigned id = (e - 0x1000u) / SW_ENT; return id < 6 ? names[id] : 0; }
static int maps_has(pm_addr a, unsigned long n, unsigned how) { return (a - 0x1000u) / SW_ENT < 6; }
"""
    main = r"""
int main(void)
{
    printf("%ld %ld %ld %ld %ld\n", sw_by_name("SHOOTER LANE"), sw_by_name("UPPER SHOOTER LANE"), sw_by_name("TROUGH 1"),
           sw_by_name("TROUGH"), sw_by_name("TILT"));
    return 0;
}
"""
    out = _host_run(tmp_path, host + body + main, flags=("-Wno-unused-function",))
    assert out.split() == ["2", "3", "4", "-1", "-1"]


# ---- the game's ball devices (run 4) -----------------------------------------------------------------------------------

def test_ball_device_decision_and_names(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    body = ""
    for head in ("static int bd_same(const char *a, const char *b)", "static int bd_refuses("):
        a = src.index(head)
        body += src[a:src.index("\n}\n", a) + 3]
    main = r"""
int main(void)
{
    printf("%d %d %d %d %d %d %d|", bd_refuses(1, 1, 1, 0, 0, 1), bd_refuses(0, 1, 1, 0, 0, 1), bd_refuses(1, 0, 1, 0, 0, 1),
           bd_refuses(1, 1, 0, 0, 0, 1), bd_refuses(1, 1, 1, 1, 0, 1), bd_refuses(1, 1, 1, 0, 1, 1), bd_refuses(1, 1, 1, 0, 0, 0));
    printf("%d %d %d %d", bd_same("LEFT SCOOP", "left_scoop"), bd_same("UPPER LOCK", "UPPER_LOCK"), bd_same("TROUGH", "TROUGH 1"),
           bd_same("T.Rex Head", "T.REX_HEAD"));
    return 0;
}
"""
    out = _host_run(tmp_path, "#include <stdio.h>\n" + body + main)
    assert out == "0 1 2 3 4 5 6|1 1 0 1"


def test_ball_device_lines_on_every_newest_build():
    for key in NEWEST:
        text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
        m = re.search(r"^site ball_device_keep\s+(0x[0-9a-f]{8}) (0x[0-9a-f]{8}) (0x[0-9a-f]{8})$", text, re.M)
        cnt = re.search(r"^data ball_device_count\s+(0x[0-9a-f]+)", text, re.M)
        assert m and cnt and re.search(r"^data ball_devices\s+0x[0-9a-f]+", text, re.M), key
        w0, w1 = int(m.group(2), 16), int(m.group(3), 16)
        # movw/movt of the device count, the same address the port names
        lo = (w0 >> 4) & 0xf000 | w0 & 0xfff
        hi = (w1 >> 4) & 0xf000 | w1 & 0xfff
        assert (hi << 16 | lo) == int(cnt.group(1), 16), key
        names = re.search(r"^text ball_device_names\s+(.*)$", text, re.M)
        if names:
            assert not {"TROUGH", "AUTO_PLUNGER"} & set(names.group(1).split()), key


@pytest.mark.parametrize("key", ["turtles_pro-1.59", "godzilla_pro-1.16", "uncanny_xmen_pro-0.98"])
def test_ball_device_keep_is_the_framework_call(key):
    elf = _elf(key)
    if not elf:
        pytest.skip("no %s game program here" % key)
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    va = int(re.search(r"^site ball_device_keep\s+(0x[0-9a-f]{8})", text, re.M).group(1), 16)
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        e = ELFFile(f)
        v, o, _n = next((s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in e.iter_segments()
                        if s["p_type"] == "PT_LOAD" and s["p_vaddr"] <= va < s["p_vaddr"] + s["p_filesz"])
        f.seek(o + va - v)
        body = struct.unpack("<28I", f.read(112))
    assert body[0x48 // 4] == 0x979ff100                                  # ldrls pc, [pc, r0, lsl #2]: the kinds' table
    assert sorted(i + 2 for i in range(7) if body[0x50 // 4 + i] == va + 0x6c) == [2, 3, 6, 8]


def test_profiles_and_blocks_know_the_ball_devices():
    from pinball_decryptor.plugins.stern import mode_project as MP, block_modes as BM
    P = MP.profiles()
    assert dict(P["turtles_pro_1_59"].ball_devices).keys() == {"UPPER_LOCK", "LOWER_LOCK"}
    assert dict(P["godzilla_le_1_16"].ball_devices).keys() == {"RIGHT_SCOOP"}           # its vapor device left out
    assert P["uncanny_xmen_le_0_98"].ball_devices == ()
    for gm, ok in (("own_game", True), ("block", False)):
        prog = BM.normalize({"name": "X", "game_modes": gm, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
            {"op": "device", "what": "UPPER_LOCK", "keep": "hold"}, {"op": "device", "what": "UPPER_LOCK", "keep": "let_go"}]}]})
        probs = [x for x in BM.problems(prog, **BM.card_checks(P["turtles_pro_1_59"])) if "UPPER_LOCK" in x]
        assert (probs == []) == ok, probs
    c = BM.to_c(prog, "x")
    assert 'pm_device_keep("UPPER_LOCK", 99u)' in c and 'pm_device_keep("UPPER_LOCK", 0u)' in c


# ---- the game's kickbacks (run 5) --------------------------------------------------------------------------------------

def test_kickbacks_are_guardians_and_the_whole_game_s():
    from pinball_decryptor.plugins.stern import mode_project as MP, block_modes as BM
    P = MP.profiles()
    have = sorted(k for k, p in P.items() if getattr(p, "kickbacks", False))
    assert have == ["guardians_1_15", "guardians_le_1_15"], have
    src = RUNTIME.read_text(encoding="utf-8")
    sec = src[src.index("/* ---- PAD-1406: the game's kickbacks"):src.index("/* the mode gives the game its rules back (or ends)")]
    assert "og_has_it()" in sec and "kb_saved[i] < 0" in sec            # the game's state saved once, put back at the end
    assert "kb_give_back(why);" in src
    for gm, ok in (("own_game", True), ("block", False)):
        prog = BM.normalize({"name": "X", "game_modes": gm, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
            {"op": "kickback", "to": "off"}]}]})
        probs = [x for x in BM.problems(prog, **BM.card_checks(P["guardians_le_1_15"])) if "kickback" in x]
        assert (probs == []) == ok, probs
    assert [x for x in BM.problems(prog, **BM.card_checks(P["turtles_pro_1_59"])) if "kickback" in x]
    assert 'if (run.on && !pm_kickback(0)) pm_log("the kickbacks stay as they are");' in BM.to_c(prog, "x")


@pytest.mark.parametrize("key,setf,cnt", [("guardians-1.15", 0x39effc, 0x4f3edc), ("guardians_le-1.15", 0x21c25c, 0x4f27c8)])
def test_kickback_lines(key, setf, cnt):
    text = (SDK / "ports" / (key + ".port")).read_text(encoding="utf-8")
    assert re.search(r"^site kickback_set\s+0x%08x 0xe92d4038 0xe1a04001$" % setf, text, re.M)
    assert re.search(r"^data kickback_count\s+0x%08x$" % cnt, text, re.M)
