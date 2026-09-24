"""The runtime's port gate on any Spike 2 title, and what a port may name besides the reference core.

- The gate (tools/spike2_emu/modes/sdk/pad_mode_runtime.c) reads the process's mappings once and never
  reads a site outside the game's own code: a port for another game once killed The Beatles 1.29 at
  boot (godzilla_le-1.16.port's resource_get 0x538484 lies in Beatles' hole between code and data). The
  core sites are checked first, and nothing else is read when one fails. Lifted verbatim from the
  runtime and compiled for the HOST, with sites that would crash the harness if the gate read them
  (skips without an ELF C compiler).
- The core's alternatives, the same in the runtime (core_of_port) and the app (mode_project.core_missing):
  the 32-bit scoring pair (score_add32 + scores32), a ball end from a bus id (value ball_end_event with
  site hook_dispatch), shots from switches only (site switch_edge or switch_hit with `switch` lines).
- Shots from switches: `switch <id> <mask> <name>` lines, counted where the hit happens and handed to
  every mode's .shot from the tick; a ball end on the bus id handed on from the dispatch.
- The Beatles 1.29 port as the app reads it: 27 rule shots and 8 switch shots, 32-bit scoring, its
  events, and every part it cannot do greyed with a reason.
Desk only: no card, no emulator.
"""
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from tests.test_spike2_mode_roster import _host_run, _lift

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"
BEATLES = PORTS / "beatles-1.29.port"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def _port_section(src):
    """The port reader, lifted: its tables, port_line and port_load, then the lookups."""
    helpers = "\n".join(_lift(src, s) for s in (
        "static int str_eq(", "static void str_copy(", "static int hexval(", "static uint64_t number("))
    reader = _between(src, "/* The port is read in PORT_CHUNK pieces", "static struct site *site(const char *name)")
    lookups = "\n".join(_lift(src, s) for s in (
        "static struct site *site(const char *name)", "static unsigned fn(const char *name)",
        "static long named(", "static unsigned data(const char *name)", "long pm_port_value("))
    return helpers + "\n" + reader + "\n" + lookups


_GATE = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <fcntl.h>
#include <unistd.h>
#include "pad_mode.h"
#define N_BUS_IDS 208
static const char *PORT_FILES[1] = { "" };
static void event_line(const char *s) { (void)s; }
static void lamp_line(const char *s) { (void)s; }
static void rule_line(const char *s) { (void)s; }      /* item 160's stock rules: not this test's */
static void say(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    printf("SAY ");
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
}
@PORT@
@MAPS@
@GATE@

/* the game's "code": words the sites point at */
static unsigned code[64] __attribute__((aligned(64))) = {
    0xe92d4038, 0xe3a00037,   /* 0: tick */
    0xe3500b02, 0xe92d4008,   /* 2: shot_dispatch */
    0xe92d4008, 0xe3a00000,   /* 4: ball_end */
    0xe30435de, 0xe3a02000,   /* 6: score_add32 */
    0xe35000cf, 0xe92d4038,   /* 8: hook_dispatch */
    0xe2503000, 0x012fff1e,   /* 10: switch_hit */
    0xe51ff004, 0x00001000,   /* 12: a hook jump to an address that is not mapped */
};

static void line(const char *fmt, ...)
{
    char b[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(b, sizeof b, fmt, ap);
    va_end(ap);
    port_line(b);
}

static void site_at(const char *name, int i) { line("site %s 0x%lx 0x%x 0x%x", name, (unsigned long)&code[i], code[i], code[i + 1]); }

int main(int argc, char **argv)
{
    const char *what = argv[1];
    char maps_text[128];
    int i;
    snprintf(maps_text, sizeof maps_text, "%lx-%lx r-xp 00000000 00:00 0      /games/beatles/game",
             (unsigned long)code, (unsigned long)(code + 64));
    maps_line(maps_text, maps_text + strlen(maps_text));
    line("game beatles");
    line("version 1.29");
    site_at("tick", 0);
    if (strcmp(what, "switch_only") && strcmp(what, "edge_only")) site_at("shot_dispatch", 2);
    if (strcmp(what, "event_end")) site_at("ball_end", 4);
    if (!strcmp(what, "wrong")) line("site score_add32 0x%lx 0x11111111 0x22222222", (unsigned long)&code[6]);
    else site_at("score_add32", 6);
    line("data cur_player 0x5b322c");
    line("data scores32 0x5b3578");
    if (!strcmp(what, "event_end")) { site_at("hook_dispatch", 8); line("value ball_end_event 0x34"); }
    if (!strcmp(what, "switch_only")) { site_at("switch_hit", 10); line("switch 73 0x100000000 Target 1"); }
    if (!strcmp(what, "edge_only")) { site_at("switch_edge", 10); line("switch 73 0x100000000 Target 1"); }
    if (!strcmp(what, "wrong")) {
        /* the mappings SAY 0x1000 is the game's code; it is not mapped at all, so reading it would crash */
        maps_line("1000-2000 r-xp 00000000 00:00 0 /games/beatles/game", 0);
        line("site resource_get 0x1000 0xe92d43f0 0xe1a04000");
    } else {
        line("site resource_get 0x1000 0xe92d43f0 0xe1a04000");        /* not mapped: never read */
        line("site past_the_end 0x%lx 0x0 0x0", (unsigned long)&code[63]);   /* crosses the end of the code */
        line("site jump 0x%lx 0x0 0x0", (unsigned long)&code[12]);     /* a hook jump to nothing */
    }
    printf("GATE %d\n", port_gate());
    for (i = 0; i < port.n_site; i++) printf("SITE %s %d\n", port.site[i].name, port.site[i].ok);
    printf("SHOTS %d SWITCHES %d\n", port.n_shot, port.n_switch);
    return 0;
}
"""


def _gate_source():
    src = _src()
    maps = _between(src, "#define N_MAPS", "/* ---- rule 2:")
    gate = "\n".join(_lift(src, s) for s in (
        "static int words_match(struct site *x)", "static void core_of_port(", "static int site_check(",
        "static int port_gate(void)"))
    maps = maps.replace("static void maps_line(const char *s, const char *e)",
                        "static void maps_line(const char *s, const char *e_)")
    # a C string's end, when the caller passes 0
    maps = maps.replace("    unsigned long lo = 0, hi = 0;\n    const char *q = s, *p;",
                        "    const char *e = e_ ? e_ : s + strlen(s);\n    unsigned long lo = 0, hi = 0;\n"
                        "    const char *q = s, *p;", 1)
    return _GATE.replace("@PORT@", _port_section(src)).replace("@MAPS@", maps).replace("@GATE@", gate)


def _gate(tmp_path, what):
    out = _host_run(tmp_path, _gate_source(), flags=("-fno-pie", "-no-pie", "-I", str(SDK),
                                                    "-Wno-unused-function", "-Wno-unused-variable"),
                    args=(what,))
    return out


def test_the_gate_never_reads_outside_the_games_code(tmp_path):
    out = _gate(tmp_path, "good")
    assert "GATE 1" in out, out
    for name in ("tick", "shot_dispatch", "ball_end", "score_add32"):
        assert "SITE %s 1" % name in out
    # not mapped, crossing the end of the code, a hook jump to nothing: refused, and the harness is alive
    assert "SAY site resource_get 0x00001000: not in the game's code - not read" in out
    assert "SITE resource_get 0" in out and "SITE past_the_end 0" in out
    assert re.search(r"SAY site past_the_end 0x[0-9a-f]+: not in the game's code - not read", out)
    assert "SITE jump 0" in out and re.search(r"SAY site jump 0x[0-9a-f]+: expected 00000000 00000000, found e51ff004 00001000", out)


def test_a_wrong_core_reads_nothing_else(tmp_path):
    """The core is checked first: with score_add32 wrong, the other sites are not read at all - here one
    the mappings claim as code that is not mapped, which would crash the harness if it were read."""
    out = _gate(tmp_path, "wrong")
    assert "GATE 0" in out, out
    assert "SAY site score_add32" in out and "expected 11111111 22222222" in out
    assert "NOT THIS GAME'S PORT" in out and "(1 site(s) wrong)" in out
    assert "resource_get" not in out.split("GATE 0")[0]           # never checked, never logged
    assert "SITE resource_get 0" in out


def test_the_core_takes_a_ball_end_from_the_bus(tmp_path):
    out = _gate(tmp_path, "event_end")
    assert "GATE 1" in out, out
    assert "SITE hook_dispatch 1" in out and "SITE ball_end" not in out


def test_the_core_takes_shots_from_switches_only(tmp_path):
    out = _gate(tmp_path, "switch_only")
    assert "GATE 1" in out, out
    assert "SITE switch_hit 1" in out and "SITE shot_dispatch" not in out
    assert "SHOTS 1 SWITCHES 1" in out                            # the switch's name is a named shot too


def test_the_core_takes_shots_from_the_switch_drain(tmp_path):
    out = _gate(tmp_path, "edge_only")
    assert "GATE 1" in out, out
    assert "SITE switch_edge 1" in out and "SITE shot_dispatch" not in out
    assert "SHOTS 1 SWITCHES 1" in out


def test_maps_lines_are_read_as_the_kernel_writes_them(tmp_path):
    src = _src()
    maps = _between(src, "#define N_MAPS", "/* ---- rule 2:")
    code = r"""
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
@HEX@
@MAPS@
static void add(const char *s) { maps_line(s, s + strlen(s)); }
int main(void)
{
    add("00008000-00533000 r-xp 00000000 08:01 1234       /games/beatles/game");
    add("0053b000-0055c000 rw-p 0052b000 08:01 1234       /games/beatles/game");
    add("40800000-40900000 r-xp 00000000 08:01 99         /lib/libc-2.23.so");
    add("40a00000-40a01000 rwxp 00000000 00:00 0");
    add("garbage");
    printf("%d %d %d %d %d %d %d %d\n", n_maps,
           maps_has(0xc0210, 8, MAP_R | MAP_X | MAP_GAME),       /* the tick: yes */
           maps_has(0x538484, 8, MAP_R),                         /* Beatles' hole: no */
           maps_has(0x532ffc, 8, MAP_R | MAP_X | MAP_GAME),      /* crosses the end of the code: no */
           maps_has(0x540000, 8, MAP_R | MAP_X),                 /* data is not code */
           maps_has(0x40800100, 8, MAP_R | MAP_X | MAP_GAME),    /* a library is not the game */
           maps_has(0x40a00000, 64, MAP_R),                      /* an anonymous page: readable */
           is_game_process(0xc0210));
    return 0;
}
"""
    code = code.replace("@HEX@", _lift(src, "static int hexval(")).replace("@MAPS@", maps)
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function",))
    assert out.split() == ["4", "1", "0", "0", "0", "0", "1", "1"]


def test_switch_hits_and_a_bus_ball_end_reach_the_modes(tmp_path):
    src = _src()
    switches = _between(src, "static volatile unsigned switch_fired[N_SWITCH_IDS];", "static int is_switch_hit(")
    dispatch = _between(src, "static int ball_end_event = -1;", "/* one counter per site event")
    code = r"""
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "pad_mode.h"
#define N_SWITCH_IDS 256
#define N_BUS_IDS 208
#define SYS_GETTID 224
static long fake_syscall(long n) { return 7; }
#define syscall fake_syscall
static void say(const char *fmt, ...) {}
static unsigned can = PM_CAN_SWITCH_SHOTS;
struct switch_shot { unsigned id; uint64_t mask; };
static struct { struct switch_shot sw[8]; int n_switch; } port;
static const struct pm_mode *current;
static void on_shot(uint64_t m) { printf("SHOT %llx\n", (unsigned long long)m); }
static const struct pm_mode mode = { .name = "m", .shot = on_shot };
static const struct pm_mode *const list[] = { &mode };
#define EACH_MODE(m) for (const struct pm_mode *const *pp_ = list; pp_ < list + 1 && ((m) = *pp_, 1); pp_++)
static void on_ball_end(unsigned *r) { printf("BALL_END\n"); }
static volatile unsigned event_fired[N_BUS_IDS];
@SWITCHES@
@DISPATCH@
int main(void)
{
    unsigned r[6] = { 73, 0, 0, 0, 0, 0 };
    int i;
    port.sw[0].id = 73; port.sw[0].mask = 0x100000000ull;
    port.sw[1].id = 48; port.sw[1].mask = 0x1000000000ull;
    port.sw[2].id = 73; port.sw[2].mask = 0x4ull;           /* a second line for 73: one hit, both bits */
    port.n_switch = 3;
    on_switch_hit(r); on_switch_hit(r);
    r[0] = 50; on_switch_hit(r);                           /* a switch no line maps */
    r[0] = 999; on_switch_hit(r);                          /* past the table */
    printf("TICK\n"); switches_deliver();
    printf("TICK\n"); switches_deliver();                  /* nothing new */
    r[0] = 48; for (i = 0; i < 20; i++) on_switch_hit(r);  /* a flood is at most 8 */
    printf("TICK\n"); switches_deliver();
    r[0] = 0x34; on_event_dispatch(r);                     /* no ball_end_event: counted only */
    ball_end_event = 0x34;
    r[0] = 0x25; on_event_dispatch(r);
    r[0] = 0x34; on_event_dispatch(r);
    printf("FIRED %u %u\n", event_fired[0x34], event_fired[0x25]);
    return 0;
}
"""
    code = code.replace("@SWITCHES@", switches).replace("@DISPATCH@", dispatch)
    out = _host_run(tmp_path, code, flags=("-I", str(SDK), "-Wno-unused-function", "-Wno-unused-variable"))
    ticks = out.split("TICK\n")
    assert ticks[1].split() == ["SHOT", "100000004", "SHOT", "100000004"]
    assert ticks[2] == ""
    assert ticks[3].splitlines()[:8] == ["SHOT 1000000000"] * 8 and ticks[3].count("SHOT") == 8
    assert ticks[3].count("BALL_END") == 1 and "FIRED 2 1" in ticks[3]


# ---- the app's rule is the runtime's ---------------------------------------------------------------
def _port_dict(text, tmp_path):
    p = tmp_path / "t.port"
    p.write_text(text, encoding="utf-8")
    return MP.read_port(str(p))


def test_the_apps_core_rule_names_what_the_runtimes_does(tmp_path):
    """mode_project._core_names picks the same core entries as core_of_port: every name core_of_port
    can pick is one _core_names picks for the matching port, and the other way round."""
    body = _lift(_src(), "static void core_of_port(")
    runtime_names = set(re.findall(r'"([a-z_0-9]+)"', body)) - {"ball_end_event"}
    app = set()
    base = ("game g\nversion 1\nsite tick 0x10 0 0\ndata cur_player 0x20\n")
    for extra in ("site shot_dispatch 0x14 0 0\nsite ball_end 0x18 0 0\nsite score_add 0x1c 0 0\ndata scores 0x24\n",
                  "site switch_hit 0x14 0 0\nswitch 73 0x100 T\nsite hook_dispatch 0x18 0 0\n"
                  "value ball_end_event 0x34\nsite score_add32 0x1c 0 0\ndata scores32 0x24\n",
                  "site switch_edge 0x14 0 0\nswitch 73 0x100 T\nsite hook_dispatch 0x18 0 0\n"
                  "value ball_end_event 0x30\nsite score_add 0x1c 0 0\ndata scores 0x24\n"):
        port = _port_dict(base + extra, tmp_path)
        assert MP.core_missing(port) == []
        s, d = MP._core_names(port)
        app |= set(s) | set(d)
    assert app == runtime_names


@pytest.mark.parametrize("drop,missing", [
    ("site score_add32", ["score_add", "scores"]),   # without it the 64-bit pair is the one asked for
    ("data scores32", ["scores32"]),
    ("site shot_dispatch", []),                 # the switch_hit site and switch lines are a shot source
    ("site ball_end ", []),                     # value ball_end_event + hook_dispatch end a ball
    ("site hook_dispatch", []),                 # ball_end is there, so the bus is not core
])
def test_what_the_beatles_port_needs(drop, missing, tmp_path):
    text = "".join(l for l in BEATLES.read_text(encoding="utf-8").splitlines(True) if not l.startswith(drop))
    assert MP.core_missing(_port_dict(text, tmp_path)) == missing


def test_a_port_without_either_way_of_a_core_part_is_refused(tmp_path):
    text = BEATLES.read_text(encoding="utf-8").splitlines(True)
    no_end = "".join(l for l in text if not l.startswith(("site ball_end ", "value ball_end_event")))
    assert MP.core_missing(_port_dict(no_end, tmp_path)) == ["ball_end"]
    no_shots = "".join(l for l in text if not l.startswith(("site shot_dispatch", "switch ")))
    assert MP.core_missing(_port_dict(no_shots, tmp_path)) == ["shot_dispatch"]
    old = "".join(l.replace("score_add32", "score_add").replace("scores32", "scores") for l in text)
    port = _port_dict(old, tmp_path)
    assert MP.core_missing(port) == [] and MP._core_names(port)[1] == ("cur_player", "scores")
    with pytest.raises(MP.ModeProjectError, match="lacks what every mode needs"):
        (tmp_path / "beatles-1.29.port").write_text(no_end, encoding="utf-8")
        MP.profile_from_port(str(tmp_path / "beatles-1.29.port"))


@pytest.mark.parametrize("path", sorted(PORTS.glob("*.port")), ids=lambda p: p.stem)
def test_every_shipped_port_has_its_core(path):
    assert MP.core_missing(MP.read_port(str(path))) == []


# ---- The Beatles 1.29 as the app reads it ----------------------------------------------------------
def test_the_beatles_profile():
    p = MP.profile_from_port(str(BEATLES))
    assert (p.key, p.version, p.port) == ("beatles_1_29", "1.29", "beatles-1.29.port") and "Beatles" in p.label
    assert p.proven and not p.proven_note
    assert p.score_bits == 32 and p.shot_mask_bits == 32
    rule = [n for n, m in p.shots if m < (1 << 32)]
    assert len(rule) == 27 and len(p.shots) == 35
    assert p.switch_shots == ("Target 1", "Target 2", "Target 3", "Target 4", "Left outlane",
                              "Left return lane", "Right return lane", "Right outlane")
    assert dict(p.shots)["Target 1"] == 0x100000000
    assert all(m >= (1 << 32) for n, m in p.shots if n in p.switch_shots)       # bits the rules never send
    assert p.switch_shots_note == ""                   # beatles-1.29 is in SWITCH_SHOTS_PROVEN
    assert set(p.events) == {"game_start", "ball_start", "ball_end", "bonus_start", "bonus_end",
                             "tilt_warning", "tilt", "game_over", "multiball_start"}
    assert p.example_start_shot == "Left orbit target"
    # what the runtime arms: no lights (no light_run) and no clips (no clip_play)
    assert p.runtime_can == ("callout", "screens", "own-sound", "messages", "award-screen")
    # the countdown needs only the countdown callout now (Beatles has 385 and no ten-seconds call)
    assert p.can("countdown") and p.callout_countdown == 385 and p.callout_ten_seconds == 0
    assert "countdown callout" in p.sound_note and "not been heard" in p.sound_note  # run muted
    assert MP.read_port(str(BEATLES))["data"]["score_mult"] == 0x543534   # the byte score_add32 multiplies by
    cannot = {part for part in MP.PARTS if not p.can(part)}
    assert cannot == {"lights", "screen", "clip", "own_sound", "stack"}
    assert "light shows" in p.why_not("lights")
    assert "scenes a mode's screen goes in" in p.why_not("screen")
    assert "plays its clips" in p.why_not("clip")
    assert "time-up" in p.why_not("own_sound")
    assert "tells that one of its own modes is running" in p.why_not("stack")
    for part in cannot:
        # the reasons a person reads name the game and no internal word
        assert p.label in p.why_not(part) and "—" not in p.why_not(part)
        assert "port" not in p.why_not(part) and "HUD" not in p.why_not(part)


def test_a_beatles_mode_file(tmp_path):
    """A blank mode on The Beatles, started on a standup and scoring on a lane: its file has the count
    (and no ten-seconds call it lacks), and a mask above the rules' 32 bits for the switch shots."""
    p = MP.profile("beatles_1_29")
    spec = MP.blank_spec(p)
    spec.start_shot = "Target 1"
    spec.scoring_shots = ["Left return lane", "Left orbit"]
    spec.countdown = True
    text = MP.runtime_cfg(spec, "x")
    lines = dict(l.split(None, 1) for l in text.splitlines() if l and not l.startswith("#"))
    assert int(lines["trigger"].split()[0], 0) == 0x100000000
    assert int(lines["shots"], 0) == 0x2000000000 | 0x4000000
    assert lines["callout_count"] == "385" and "callout_at" not in lines
    for key in ("screen_scene", "clip_start", "clip_end", "light_owner", "sound_key"):
        assert key not in lines


_SCORE32 = r"""
int main(int argc, char **argv)
{
    static struct { unsigned scores[4]; unsigned char mult; } g;
    const char *what = argv[1];
    char m[128];
    snprintf(m, sizeof m, "%lx-%lx rw-p 00000000 00:00 0 /games/beatles/game",
             (unsigned long)&g, (unsigned long)(&g + 1));
    maps_line(m, m + strlen(m));
    line("data scores32 0x%lx", (unsigned long)g.scores);
    if (!strcmp(what, "mult")) line("data score_mult 0x%lx", (unsigned long)&g.mult);
    if (!strcmp(what, "unmapped")) line("data score_mult 0x1000");    /* reading it would crash */
    g.mult = 2;
    g.scores[1] = 0xffffff00u;
    g.scores[2] = 0xffffffffu;
    printf("%u %u %u %u %u %u %u\n",
           score32_points(1, 1000000),              /* room to spare: every point */
           score32_points(1, 5000000000ull),        /* past 32 bits: cut to the room (over the multiplier) */
           score32_points(2, 1000),                 /* 255 left below the top */
           score32_points(3, 1),                    /* at the top: nothing */
           score32_points(0, 1), score32_points(5, 1),
           score32_points(4, 0));
    return 0;
}
"""


@pytest.mark.parametrize("what, want", [
    ("mult", ["1000000", str(0xffffffff // 2), "127", "0", "0", "0", "0"]),
    ("none", ["1000000", str(0xffffffff), "255", "0", "0", "0", "0"]),
    ("unmapped", ["1000000", str(0xffffffff), "255", "0", "0", "0", "0"]),
])
def test_a_32_bit_award_never_wraps_the_score(tmp_path, what, want):
    """The Beatles' score_add32 multiplies the points by a byte and adds them into a u32 with no carry
    check (0x15ee7c): pm_score_add cuts an award to the room left, over the port's score_mult, and never
    reads a score_mult outside the process's mappings."""
    src = _src()
    maps = _between(src, "#define N_MAPS", "/* ---- rule 2:")
    head = _GATE[:_GATE.index("@GATE@")]
    helper = _between(_GATE, "static void line(const char *fmt, ...)", "static void site_at(")
    code = (head.replace("@PORT@", _port_section(src)).replace("@MAPS@", maps) + helper
            + _lift(src, "static unsigned score32_points(") + _SCORE32)
    out = _host_run(tmp_path, code, flags=("-fno-pie", "-no-pie", "-I", str(SDK), "-Wno-unused-function",
                                           "-Wno-unused-variable"), args=(what,))
    assert out.split() == want, out


def test_a_32_bit_title_refuses_an_award_the_game_could_wrap():
    beatles, godzilla = MP.profile("beatles_1_29"), MP.GODZILLA_PRO_1_15
    top = MP.SCORE32_AWARD_MAX
    assert top * 255 <= 0xffffffff < (top + 1) * 255

    def said(p, award, shot_points=None):
        spec = MP.blank_spec(p)
        spec.award = award
        if shot_points is not None:
            spec.shot_award = [[p.shots[0][0], shot_points]]
        return " ".join(MP.validate_parameters(spec, p))

    assert "32 bits" not in said(beatles, top) + said(beatles, 1000, top)
    assert "at most 16,843,009 points" in said(beatles, top + 1)
    assert "can be at most 16,843,009" in said(beatles, 1000, top + 1)
    assert "32 bits" not in said(godzilla, 5000000000) + said(godzilla, 1000, 5000000000)


def test_switch_shots_not_yet_proven_say_so(monkeypatch):
    monkeypatch.setattr(MP, "SWITCH_SHOTS_PROVEN", frozenset())
    p = MP.profile_from_port(str(BEATLES))
    assert "not been seen" in p.switch_shots_note and "Target 1" in p.switch_shots_note


def test_a_port_without_a_switch_hit_site_offers_no_switch_shots(tmp_path):
    text = "".join(l for l in BEATLES.read_text(encoding="utf-8").splitlines(True) if not l.startswith("site switch_hit"))
    (tmp_path / "beatles-1.29.port").write_text(text, encoding="utf-8")
    p = MP.profile_from_port(str(tmp_path / "beatles-1.29.port"))
    assert len(p.shots) == 27 and p.switch_shots == () and p.switch_shots_note == ""
