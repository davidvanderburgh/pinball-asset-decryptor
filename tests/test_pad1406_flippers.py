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
    return src[a:src.index("/* ---- shots from the switch drain (optional; any build)", a)]


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
static unsigned long fn(const char *n)
{
    if (!has_sites) return 0;
    if (!__builtin_strcmp(n, "flippers_off")) return (unsigned long)g_off;
    if (!__builtin_strcmp(n, "flippers_on")) return (unsigned long)g_on;
    return 0;
}
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
