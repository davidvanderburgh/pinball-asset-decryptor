"""Item mode-leds: named playfield inserts, held by a mode in a lamp layer of its own.

- The port's ``lamp`` lines (tools/spike2_emu/modes/sdk/ports/godzilla_*.port): read the way the runtime
  reads them (``lamp_map.parse_lamp``, ``mode_project.read_port``), every name unique, every shot mask one
  of the port's shots or a bit the game's own shot table ties to the insert.
- The runtime's lamp section (pad_mode_runtime.c, between ``named inserts`` and ``LAMPS END``), compiled
  for the HOST against a model of the game's lamp layers: the allocator (a list sorted by priority, a new
  group after every group of equal or lower priority) and the compositor (bottom to top, a slot with +3
  set gives its light the level at +2). Holding, the patterns, priority, release, a lost layer, game over.
- mode_file.c's light lines (``light``, ``light_insert``, ``light_shots``, ``light_priority``), compiled
  for the host against the SDK calls, as test_spike2_mode_roster.py does.
- lamp_map.py against the game programs, when they are present (skips otherwise).
The C parts need an ELF host toolchain (Linux; they skip on Windows and macOS).
"""
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
sys.path.insert(0, str(SDK))
import lamp_map  # noqa: E402

from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402

PORTS = {"godzilla_le-1.16": SDK / "ports" / "godzilla_le-1.16.port",
         "godzilla_pro-1.15": SDK / "ports" / "godzilla_pro-1.15.port"}
ELFS = {"godzilla_le-1.16": [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""), r"C:\tmp\kaiju_premium\stock\game",
                             "/mnt/c/tmp/kaiju_premium/stock/game"],
        "godzilla_pro-1.15": [os.environ.get("PAD_GODZILLA_PRO_115_GAME", ""), r"C:\tmp\pad_parallel\item144\pro115\game",
                              "/mnt/c/tmp/pad_parallel/item144/pro115/game",
                              r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game", "/mnt/c/tmp/radium_scene_re/godzilla_pro_1_15/game"]}


def _elf(key):
    for p in ELFS[key]:
        if p and os.path.isfile(p):
            return p
    pytest.skip("the %s game program is not here" % key)


def _lamp_lines(path):
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s.startswith("lamp "):
            out.append(lamp_map.parse_lamp(s[5:]))
    return out


# ---- the port lines ---------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(PORTS))
def test_every_lamp_line_reads_and_names_one_insert(key):
    lamps = _lamp_lines(PORTS[key])
    assert len(lamps) >= 80, "the playfield has more inserts than that"
    assert all(l is not None for l in lamps), "a lamp line the runtime would skip"
    names = [l[3] for l in lamps]
    assert len(names) == len(set(names)), "two lamp lines with one name"
    for lights, mono, shot, name in lamps:
        assert mono == (lights[1:] == (0, 0) and lights[0] != 0) or not mono
        assert all(0 <= x < 600 for x in lights)
        assert len(name) < 40 and "#" not in name


@pytest.mark.parametrize("key", sorted(PORTS))
def test_the_shots_inserts_are_the_ones_in_front_of_them(key):
    """The game's own shot table ties one insert to each shot: the ones a mode lights most."""
    lamps = {l[3]: l for l in _lamp_lines(PORTS[key])}
    port = MP.read_port(str(PORTS[key]))
    shots = dict(port["shot"])
    for shot, insert in (("Left ramp", "LEFT RAMP"), ("Right ramp", "RIGHT RAMP"), ("Building", "BUILDING"),
                         ("Maser target", "MASER"), ("Powerline left", "POWERLINE LEFT"),
                         ("Powerline center", "POWERLINE CENTER"), ("Powerline right", "POWERLINE RIGHT"),
                         ("Shield target left", "SHIELD LEFT"), ("Skill shot", "SKILL SHOT"), ("Big loop", "BIG LOOP"),
                         ("Godzilla target", "MAGNA GRAB")):
        assert lamps[insert][2] & shots[shot], (shot, insert)
    assert lamps["LEFT RAMP"][0] == (346, 347, 348) and lamps["MASER"][:2] == ((298, 0, 0), True)
    # a tie is a bit of the game's own shot table (43 cshot objects on both builds): the port's named shots,
    # and bits it leaves unnamed (the outlanes, the spinners' extra bits, the flashers)
    for lights, mono, shot, name in lamps.values():
        assert shot < (1 << 43), name
    assert lamps["LEFT OUTLANE"][2] == 0x8 and lamps["TOP SPINNER"][2] == 0x1800


def test_the_app_reads_the_lamp_lines_and_an_old_port_has_none(tmp_path):
    port = MP.read_port(str(PORTS["godzilla_le-1.16"]))
    assert len(port["lamp"]) == len(_lamp_lines(PORTS["godzilla_le-1.16"]))
    name, lights, shot = port["lamp"][0]
    assert isinstance(name, str) and len(lights) == 3 and isinstance(shot, int)
    assert port["value"]["lamp_slot_size"] == 40 and port["data"]["lamp_layers"]
    old = MP.read_port(str(SDK / "ports" / "jaws_le-1.02.port"))
    assert old["lamp"] == []


def test_a_lamp_line_is_read_as_the_runtime_reads_it():
    assert lamp_map.parse_lamp("346,347,348  0x100000  LEFT RAMP  # lamp 143") == ((346, 347, 348), False, 0x100000, "LEFT RAMP")
    assert lamp_map.parse_lamp("298 0x8000000 MASER") == ((298, 0, 0), True, 0x8000000, "MASER")
    assert lamp_map.parse_lamp("365,366,0 0 BUILDING FIRE LEFT 1") == ((365, 366, 0), False, 0, "BUILDING FIRE LEFT 1")
    assert lamp_map.parse_lamp("0 0 NOTHING") is None
    assert lamp_map.parse_lamp("346,347 0x1") == None or lamp_map.parse_lamp("346,347 0x1")[3]


def test_the_port_stays_readable_by_the_runtime():
    """The runtime reads up to PORT_MAX bytes of a port: the lamp lines must fit, and every line before them
    must sit in the first 16 KB an older runtime read (its runtime then simply has no lamps)."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    cap = int(re.search(r"#define PORT_MAX\s+(\d+)", src).group(1))
    for key, path in PORTS.items():
        b = path.read_bytes()
        assert len(b) < cap - 1, key
        first = b.find(b"\n# ---- named inserts")
        assert 0 < first < 16383, key


# ---- lamp_map.py against the programs -------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(PORTS))
def test_lamp_map_reads_the_committed_lines_off_the_game(key):
    elf = lamp_map.Elf(_elf(key))
    got = [lamp_map.parse_lamp(l[5:]) for l in lamp_map.port_lines(elf) if l.startswith("lamp ")]
    if got and all(g[2] == 0 for g in got):
        pytest.skip("unicorn is not installed: the shot table was not read")
    assert got == _lamp_lines(PORTS[key])


# ---- the runtime's lamp section, on the host ----------------------------------------------------------
def _cc():
    import shutil
    if os.name == "nt":
        pytest.skip("the harness needs an ELF toolchain with non-PIE static addresses below 4 GB")
    if sys.platform == "darwin":
        pytest.skip("the harness needs an ELF toolchain")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


def _function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


RT_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "pad_mode.h"

static unsigned can;
static const struct pm_mode *current;
static unsigned long now_ms;
static int in_game = 1;
unsigned long pm_ms(void) { return now_ms; }
int pm_in_game(void) { return in_game; }
int pm_snprintf(char *o, unsigned long cap, const char *fmt, ...)
{ va_list ap; int n; va_start(ap, fmt); n = vsnprintf(o, cap, fmt, ap); va_end(ap); return n; }
static void log_raw(const char *who, const char *fmt, va_list ap) { printf("[%s] ", who); vprintf(fmt, ap); putchar('\n'); }
static void say(const char *fmt, ...) { va_list ap; va_start(ap, fmt); log_raw("pad", fmt, ap); va_end(ap); }
struct site { char name[40]; unsigned addr, w0, w1; int ok; };

/* ---- a model of the game's lamp layers (Godzilla Premium 1.16) ---- */
#define LIGHTS 600
static unsigned fake_count = LIGHTS, fake_event_current, fake_heads[2];
static unsigned char pool[12][24] __attribute__((aligned(8)));
static unsigned char slots[12][LIGHTS * 40] __attribute__((aligned(8)));
static unsigned char global_level[LIGHTS];
static int pool_used;
static unsigned last_alloc_event = 0xdeadbeef, last_alloc_prio;
#define U32(p) (*(unsigned *)(p))
static unsigned long fake_alloc(unsigned set, unsigned prio, unsigned a, unsigned b)
{
    unsigned char *g = pool[pool_used], *ip, *n;
    memset(slots[pool_used], 0, sizeof slots[0]);
    U32(g) = (unsigned)(unsigned long)slots[pool_used];
    pool_used++;
    g[4] = (unsigned char)prio;
    U32(g + 16) = fake_event_current;
    last_alloc_event = fake_event_current;
    last_alloc_prio = prio;
    ip = (unsigned char *)(unsigned long)fake_heads[1];
    if (!ip || ip[4] > prio) { U32(g + 20) = fake_heads[1]; fake_heads[1] = (unsigned)(unsigned long)g; return (unsigned long)g; }
    while ((n = (unsigned char *)(unsigned long)U32(ip + 20)) && n[4] <= prio) ip = n;
    U32(g + 20) = U32(ip + 20);
    U32(ip + 20) = (unsigned)(unsigned long)g;
    return (unsigned long)g;
}
static void unlink_group(unsigned char *g)
{
    unsigned *pp = &fake_heads[1];
    while (*pp && (unsigned char *)(unsigned long)*pp != g) pp = (unsigned *)(unsigned long)(*pp + 20);
    if (*pp) *pp = U32(g + 20);
}
/* the compositor: the global value, then every layer bottom to top where slot+3 is set */
static int out_level(unsigned light)
{
    int v = global_level[light];
    unsigned char *g;
    for (g = (unsigned char *)(unsigned long)fake_heads[1]; g; g = (unsigned char *)(unsigned long)U32(g + 20)) {
        unsigned char *s = (unsigned char *)(unsigned long)U32(g) + light * 40;
        if (s[3]) v = s[2];
    }
    return v;
}
static struct site lamp_site = { "lamp_group", 0, 0, 0, 1 };
static struct site *site(const char *name) { return !strcmp(name, "lamp_group") ? &lamp_site : 0; }
static unsigned fn(const char *name) { return !strcmp(name, "lamp_group") ? lamp_site.addr : 0; }
static unsigned data(const char *name)
{
    if (!strcmp(name, "lamp_layers")) return (unsigned)(unsigned long)fake_heads;
    if (!strcmp(name, "light_count")) return (unsigned)(unsigned long)&fake_count;
    if (!strcmp(name, "event_current")) return (unsigned)(unsigned long)&fake_event_current;
    return 0;
}
long pm_port_value(const char *name, long fallback) { return fallback; }

@HELPERS@
@SECTION@

static int have_data(const char *const *names) { return 1; }
static int have_values(const char *const *names) { return 1; }
static const struct pm_mode mode_a = { .name = "A" }, mode_b = { .name = "B" };

int main(int argc, char **argv)
{
    int k;
    lamp_site.addr = (unsigned)(unsigned long)fake_alloc;
    for (k = 1; k < argc; k++) {
        const char *a = argv[k];
        if (!strcmp(a, "lamp")) lamp_line(argv[++k]);
        else if (!strcmp(a, "arm")) { lamps_arm(); printf("CAN %d\n", (can & PM_CAN_LAMPS) != 0); }
        else if (!strcmp(a, "count")) fake_count = (unsigned)atoi(argv[++k]);
        else if (!strcmp(a, "event")) fake_event_current = (unsigned)strtoul(argv[++k], 0, 0);
        else if (!strcmp(a, "as")) current = argv[++k][0] == 'A' ? &mode_a : &mode_b;
        else if (!strcmp(a, "game_group")) {        /* game_group <prio> <light> <level>: a show of the game's */
            unsigned p = (unsigned)atoi(argv[++k]), l = (unsigned)atoi(argv[++k]), v = (unsigned)atoi(argv[++k]);
            unsigned char *g = (unsigned char *)fake_alloc(0, p, 0, 0), *s = (unsigned char *)(unsigned long)U32(g) + l * 40;
            s[2] = (unsigned char)v; s[3] = 255;
        }
        else if (!strcmp(a, "global")) { unsigned l = (unsigned)atoi(argv[++k]); global_level[l] = (unsigned char)atoi(argv[++k]); }
        else if (!strcmp(a, "set")) {
            unsigned rgb = (unsigned)strtoul(argv[k + 1], 0, 16); int pat = atoi(argv[k + 2]); unsigned ms = (unsigned)atoi(argv[k + 3]);
            printf("SET %d\n", pm_lamp_set(argv[k + 4], rgb, pat, ms)); k += 4;
        }
        else if (!strcmp(a, "shot")) {
            unsigned long long m = strtoull(argv[k + 1], 0, 0); unsigned rgb = (unsigned)strtoul(argv[k + 2], 0, 16);
            printf("SHOT %d\n", pm_lamp_shot(m, rgb, atoi(argv[k + 3]), (unsigned)atoi(argv[k + 4]))); k += 4;
        }
        else if (!strcmp(a, "release")) printf("RELEASE %d\n", pm_lamp_release(argv[++k]));
        else if (!strcmp(a, "release_shot")) printf("RELEASE %d\n", pm_lamp_release_shot(strtoull(argv[++k], 0, 0)));
        else if (!strcmp(a, "release_all")) printf("RELEASE %d\n", pm_lamp_release_all());
        else if (!strcmp(a, "prio")) printf("PRIO %d\n", pm_lamp_priority((unsigned)atoi(argv[++k])));
        else if (!strcmp(a, "tick")) { int n = atoi(argv[++k]), i; for (i = 0; i < n; i++) { now_ms += 17; lamps_tick(); } }
        else if (!strcmp(a, "out")) { unsigned l = (unsigned)atoi(argv[++k]); printf("OUT %u %d\n", l, out_level(l)); }
        else if (!strcmp(a, "trace")) {             /* trace <light> <ticks>: the composited level each tick */
            unsigned l = (unsigned)atoi(argv[k + 1]); int n = atoi(argv[k + 2]), i; k += 2;
            printf("TRACE %u", l);
            for (i = 0; i < n; i++) { now_ms += 17; lamps_tick(); printf(" %d", out_level(l)); }
            printf("\n");
        }
        else if (!strcmp(a, "layers")) {
            unsigned p[16]; int n = pm_lamp_layers(p, 16), i;
            printf("LAYERS");
            for (i = 0; i < n; i++) printf(" %u%s", p[i] & 255u, p[i] & 256u ? "*" : "");
            printf("\n");
        }
        else if (!strcmp(a, "lose")) unlink_group((unsigned char *)(unsigned long)lamp_layer[0].group);
        else if (!strcmp(a, "game_over")) in_game = 0;
        else if (!strcmp(a, "find")) printf("FIND %d\n", pm_lamp_find(argv[++k]));
        else if (!strcmp(a, "alloc")) printf("ALLOC event 0x%x prio %u\n", last_alloc_event, last_alloc_prio);
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    cc = _cc()
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    start = src.index("/* ---- named inserts: a lamp layer of our own")
    end = src.index("/* ---- LAMPS END */")
    helpers = "\n".join(_function(src, r) for r in (
        r"static int str_eq\(", r"static int hexval\(", r"static uint64_t number\(", r"static void rest\("))
    c = RT_HARNESS.replace("@HELPERS@", helpers).replace("@SECTION@", src[start:end])
    d = tmp_path_factory.mktemp("lamps")
    (d / "rt.c").write_text(c)
    exe = d / "rt"
    r = subprocess.run([cc, "-std=gnu17", "-no-pie", "-fno-pie", "-O1", "-Wall", "-Wno-unused-function",
                        "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe), str(d / "rt.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


# the Premium 1.16 lines the tests use
LINES = ["lamp", "346,347,348 0x100000 LEFT RAMP  # lamp 143", "lamp", "381,382,383 0x200000 RIGHT RAMP",
         "lamp", "298 0x8000000 MASER", "lamp", "354,355,356 0xc00000 BUILDING",
         "lamp", "377 0 HEAT RAY L1", "lamp", "378 0 HEAT RAY L2", "lamp", "379 0 HEAT RAY L3",
         "lamp", "365,366,0 0 BUILDING FIRE LEFT 1"]


def _rt(exe, *args):
    # the first tick checks the lamp lines against the game's light count (the game counts them only once
    # its main() has run), and says so: taken before a test's own steps
    r = subprocess.run([str(exe), *LINES, "arm", "tick", "1", *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _outs(out):
    return {int(a): int(b) for a, b in re.findall(r"^OUT (\d+) (-?\d+)$", out, re.M)}


def test_the_port_lines_arm_the_lamps(runtime):
    out = _rt(runtime, "find", "left ramp", "find", "HEAT RAY L2", "find", "NOPE")
    assert "CAN 1" in out and "8 named inserts (4 tied to a shot)" in out
    assert "the game counts 600 lights; every lamp line is within them" in out
    assert re.findall(r"FIND (-?\d+)", out) == ["0", "5", "-1"]
    r = subprocess.run([str(runtime), *LINES, "count", "300", "arm", "tick", "1", "find", "MASER"],
                       capture_output=True, text=True, timeout=30)
    assert "CAN 1" in r.stdout and "past this game's 300 lights" in r.stdout and "FIND -1" in r.stdout


def test_a_held_insert_shows_our_colour_over_the_game_and_release_gives_it_back(runtime):
    out = _rt(runtime, "as", "A", "game_group", "145", "346", "90", "game_group", "145", "298", "200", "global", "347", "30",
              "out", "346", "out", "347",
              "set", "ff0000", "0", "0", "LEFT RAMP", "tick", "1", "out", "346", "out", "347", "out", "348", "out", "298",
              "release", "Left Ramp", "out", "346", "out", "347", "out", "348")
    levels = re.findall(r"^OUT (\d+) (-?\d+)$", out, re.M)
    assert levels[:2] == [("346", "90"), ("347", "30")]              # the game's show and the global bank
    assert levels[2:6] == [("346", "255"), ("347", "0"), ("348", "0"), ("298", "200")]   # ours; MASER is still the game's
    assert levels[6:] == [("346", "90"), ("347", "30"), ("348", "0")]                    # handed back at once
    assert "SET 1" in out and "RELEASE 1" in out


def test_our_layer_is_made_with_no_current_event_and_goes_on_top(runtime):
    out = _rt(runtime, "as", "A", "event", "0x1234", "game_group", "255", "346", "10", "game_group", "145", "346", "20",
              "set", "00ff00", "0", "0", "MASER", "alloc", "layers", "tick", "1", "out", "298")
    assert "ALLOC event 0x0 prio 255" in out                          # no show's end can free it
    assert "LAYERS 145 255 255*" in out                               # after the game's 255: on top
    assert _outs(out)[298] == 255


def test_blink_pulse_and_chase(runtime):
    out = _rt(runtime, "as", "A", "set", "00ff00", "1", "500", "MASER", "trace", "298", "60")
    trace = [int(x) for x in re.search(r"TRACE 298 (.*)", out).group(1).split()]
    assert set(trace) == {0, 255}
    edges = sum(1 for a, b in zip(trace, trace[1:]) if a != b)
    assert 3 <= edges <= 5                                            # ~1 s of a 500 ms blink
    out = _rt(runtime, "as", "A", "set", "0000ff", "2", "1600", "BUILDING", "trace", "356", "100", "trace", "354", "5")
    blue = [int(x) for x in re.search(r"TRACE 356 (.*)", out).group(1).split()]
    red = [int(x) for x in re.search(r"TRACE 354 (.*)", out).group(1).split()]
    assert min(blue) >= 40 and max(blue) >= 250 and len(set(blue)) > 20 and set(red) == {0}
    assert blue.index(max(blue)) < len(blue) - 1                      # up, then down again
    out = _rt(runtime, "as", "A", "set", "ffc800", "3", "170", "HEAT RAY L1,HEAT RAY L2,HEAT RAY L3",
              "trace", "377", "40", "tick", "0")
    # three inserts, one lit at a time, 10 ticks (170 ms) each: L1 lit one step in three
    t1 = [int(x) for x in re.search(r"TRACE 377 (.*)", out).group(1).split()]
    assert set(t1) == {0, 255} and 8 <= t1.count(255) <= 22


def test_a_single_colour_insert_takes_the_colours_brightest_part_and_an_rg_fixture_its_two(runtime):
    out = _rt(runtime, "as", "A", "set", "402080", "0", "0", "MASER,BUILDING FIRE LEFT 1", "tick", "1",
              "out", "298", "out", "365", "out", "366")
    assert _outs(out) == {298: 0x80, 365: 0x40, 366: 0x20}


def test_a_shot_holds_its_inserts(runtime):
    out = _rt(runtime, "as", "A", "shot", "0x8300000", "ff00ff", "0", "0", "tick", "1",
              "out", "346", "out", "381", "out", "298", "out", "354", "release_shot", "0x200000", "out", "381", "out", "346")
    assert "SHOT 3" in out and "RELEASE 1" in out
    o = re.findall(r"^OUT (\d+) (-?\d+)$", out, re.M)
    assert o == [("346", "255"), ("381", "255"), ("298", "255"), ("354", "0"), ("381", "0"), ("346", "255")]


def test_a_lower_priority_puts_the_game_on_top_and_back(runtime):
    out = _rt(runtime, "as", "A", "game_group", "145", "346", "77", "set", "ff0000", "0", "0", "LEFT RAMP,MASER", "tick", "1",
              "out", "346", "prio", "1", "tick", "1", "out", "346", "out", "298", "layers",
              "prio", "255", "tick", "1", "out", "346")
    o = re.findall(r"^OUT (\d+) (-?\d+)$", out, re.M)
    assert o == [("346", "255"), ("346", "77"), ("298", "255"), ("346", "255")]   # MASER: no show of the game's there
    assert "PRIO 1" in out and "LAYERS 1* 145 255*" in out


def test_only_the_owner_releases_and_a_mode_takes_over_with_a_line(runtime):
    out = _rt(runtime, "as", "A", "set", "ff0000", "0", "0", "LEFT RAMP", "as", "B", "release_all",
              "tick", "1", "out", "346", "set", "0000ff", "0", "0", "LEFT RAMP", "tick", "1", "out", "348",
              "as", "A", "release_all")
    assert re.findall(r"RELEASE (\d+)", out) == ["0", "0"]            # B held nothing; A no longer holds it
    assert _outs(out) == {346: 255, 348: 255}
    assert "B takes LEFT RAMP from A" in out


def test_a_layer_the_game_took_back_is_replaced_and_game_over_hands_everything_back(runtime):
    out = _rt(runtime, "as", "A", "set", "ff0000", "0", "0", "LEFT RAMP", "tick", "1", "lose", "tick", "70",
              "out", "346", "layers", "game_over", "tick", "1", "out", "346")
    assert "is gone from the game's list - a new one" in out
    assert re.findall(r"^OUT 346 (\d+)$", out, re.M) == ["255", "0"]
    assert "the game left play - 1 insert(s) handed back" in out


def test_unknown_names_are_said_and_nothing_is_held(runtime):
    out = _rt(runtime, "as", "A", "set", "ff0000", "0", "0", "NO SUCH INSERT", "set", "ff0000", "9", "0", "MASER",
              "tick", "1", "out", "298")
    assert "SET 0" in out and '"NO SUCH INSERT" is not an insert' in out
    assert "SET 1" in out and _outs(out)[298] == 255                 # a pattern out of range is solid


# ---- mode_file.c's light lines --------------------------------------------------------------------
MF_HARNESS = r"""
#define _GNU_SOURCE
#include "pad_mode.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>
extern const struct pm_mode *const __start_pm_modes[];
void pm_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
int pm_snprintf(char *o, unsigned long cap, const char *fmt, ...)
{ va_list ap; int n; va_start(ap, fmt); n = vsnprintf(o, cap, fmt, ap); va_end(ap); return n; }
long pm_read_file(const char *path, char *buf, unsigned long cap)
{
    char p[512]; long n; int fd;
    if (strncmp(path, "/dump/", 6) != 0) return -1;
    snprintf(p, sizeof p, "%s/%s", getenv("MODE_DIR"), path + 6);
    fd = open(p, O_RDONLY);
    if (fd < 0) return -1;
    n = read(fd, buf, cap);
    close(fd);
    return n;
}
static int running_mode;
int pm_in_game(void) { return 1; }
unsigned pm_player(void) { return 1; }
int pm_begin(void) { if (running_mode) return 0; running_mode = 1; return 1; }
void pm_end(void) { running_mode = 0; }
static unsigned long now_ms;
unsigned long pm_ms(void) { return now_ms; }
long pm_port_value(const char *name, long fallback) { return fallback; }
static int trig_start, trig_stop;
int pm_trigger(const char *n)
{
    if (!strcmp(n, "mode.start") && trig_start) { trig_start = 0; return 1; }
    if (!strcmp(n, "mode.stop") && trig_stop) { trig_stop = 0; return 1; }
    return 0;
}
static int lamps = 1;
int pm_can(unsigned w) { return (w & PM_CAN_LAMPS) ? lamps : 1; }
int pm_lamp_set(const char *names, unsigned rgb, int pattern, unsigned ms)
{ printf("LAMP_SET %s %06x %d %u\n", names, rgb, pattern, ms); return 2; }
int pm_lamp_shot(uint64_t shots, unsigned rgb, int pattern, unsigned ms)
{ printf("LAMP_SHOT 0x%llx %06x %d %u\n", (unsigned long long)shots, rgb, pattern, ms); return 1; }
int pm_lamp_release_all(void) { printf("LAMP_RELEASE_ALL\n"); return 4; }
int pm_lamp_priority(unsigned p) { printf("LAMP_PRIO %u\n", p); return (int)p; }

int main(int argc, char **argv)
{
    const struct pm_mode *m = *__start_pm_modes;
    int i, k;
    m->init();
    for (k = 1; k < argc; k++) {
        if (!strcmp(argv[k], "start")) trig_start = 1;
        else if (!strcmp(argv[k], "stop")) trig_stop = 1;
        else if (!strcmp(argv[k], "nolamps")) lamps = 0;
        else if (!strcmp(argv[k], "shot")) m->shot(strtoull(argv[++k], 0, 0));
        for (i = 0; i < 31; i++) { now_ms += 17; m->tick(); }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def modefile(tmp_path_factory):
    cc = _cc()
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import test_spike2_mode_roster as R
    d = tmp_path_factory.mktemp("lampfile")
    (d / "harness.c").write_text(MF_HARNESS)
    stubs, _names = R.weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _mf(exe, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, MODE_DIR=str(tmp_path)))
    assert r.returncode == 0, r.stderr
    return r.stdout


LIGHT_CFG = ("name LIGHT TEST\ntrigger 0 1\nseconds 25\nshots 0x300000\naward 1000000\nshot_award 0x8000000 5000\n"
             "light_shots orange blink 400\nlight_insert #00ffff pulse 1200 TOP SPINNER,BIG LOOP\n"
             "light 0x70000000 purple chase 250\nlight_priority 200\n")


def test_the_light_lines_light_at_the_start_and_hand_back_at_the_end(modefile, tmp_path):
    out = _mf(modefile, tmp_path, LIGHT_CFG, "start", "stop")
    assert "unknown key" not in out
    held = out[out.index("LIGHT TEST START") - 400:]
    assert "LAMP_PRIO 200" in out
    assert "LAMP_SHOT 0x8300000 ff6000 1 400" in out                  # light_shots: shots + shot_award
    assert "LAMP_SET TOP SPINNER,BIG LOOP 00ffff 2 1200" in out
    assert "LAMP_SHOT 0x70000000 a000ff 3 250" in out
    assert "lights: 4 insert(s) held while it runs (layer 200)" in out and held
    assert out.index("LIGHT TEST START") < out.index("LAMP_RELEASE_ALL") < out.index("LIGHT TEST END")
    assert "lights: 4 insert(s) handed back to the game" in out


def test_bad_light_lines_are_said_and_a_port_without_lamps_lights_nothing(modefile, tmp_path):
    cfg = ("name L\ntrigger 0 1\nseconds 5\nlight 0 red\nlight 0x100000 mauve\nlight 0x100000 red strobe\n"
           "light_insert red solid 0\nlight_priority 900\nlight 0x100000 ff0000\n")
    out = _mf(modefile, tmp_path, cfg, "start")
    assert "light needs shot bits" in out and "no colour" in out and "not solid, blink, pulse or chase" in out
    assert "light_insert names no insert" in out and "light_priority needs 1-255" in out
    assert "LAMP_SHOT 0x100000 ff0000 0 0" in out and "LAMP_PRIO 255" in out
    out = _mf(modefile, tmp_path, "name L\ntrigger 0 1\nseconds 5\nlight 0x100000 red\n", "nolamps", "start", "stop")
    assert "names no inserts - the light lines light nothing" in out and "LAMP_" not in out


def test_a_mode_file_without_light_lines_touches_no_lamp(modefile, tmp_path):
    out = _mf(modefile, tmp_path, "name K\ntrigger 0 1\nseconds 5\nshots 0x100000\n", "start", "stop")
    assert "K START" in out and "K END" in out and "LAMP_" not in out and "lights:" not in out


def test_port_tool_carries_the_lamp_lines_to_another_build_by_name(tmp_path):
    """Pro 1.15's port drafted onto Premium 1.16: the lamp layer's globals are derived like any global,
    and each lamp line is placed by the insert's NAME with the target's own light ids."""
    pro, le = _elf("godzilla_pro-1.15"), _elf("godzilla_le-1.16")
    import port_tool
    out = tmp_path / "draft.port"
    port_tool.main([pro, str(PORTS["godzilla_pro-1.15"]), le, "-o", str(out), "--game", "godzilla_le", "--version", "1.16"])
    draft = MP.read_port(str(out))
    committed = MP.read_port(str(PORTS["godzilla_le-1.16"]))
    assert draft["data"]["lamp_layers"] == committed["data"]["lamp_layers"]
    assert draft["data"]["light_count"] == committed["data"]["light_count"]
    placed = {n: (l, s) for n, l, s in draft["lamp"]}
    ours = {n: (l, s) for n, l, s in committed["lamp"]}
    assert len(placed) >= 80
    for name in placed:
        assert placed[name][0] == ours[name][0], name          # the target's light ids, by name
    text = out.read_text(encoding="utf-8")
    assert "left out: the target names no insert LOWER PLAYFIELD GI-WHT(X8)" in text   # Pro's name, not Premium's
    assert "NOT PLACED" not in text
    # another title: the lines are left out
    out2 = tmp_path / "other.port"
    port_tool.main([pro, str(PORTS["godzilla_pro-1.15"]), le, "-o", str(out2), "--game", "jaws_le", "--version", "9"])
    assert MP.read_port(str(out2))["lamp"] == [] and "another title's insert" in out2.read_text(encoding="utf-8")
