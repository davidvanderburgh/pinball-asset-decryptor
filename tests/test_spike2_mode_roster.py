"""Item 146: a mode in Godzilla's battle roster.

- ``roster_slot <n>`` in a mode file (tools/spike2_emu/modes/sdk/mode_file.c): parsed, claimed through
  ``pm_roster_claim``, and a pick of that slot starts the mode. mode_file.c is compiled for the HOST
  against a stub of the SDK calls it makes, so this runs wherever a C compiler is (skips otherwise).
- The Pro 1.15 port's roster lines, and the evidence that the roster is a fixed table of seven: checked
  against the game program when it is present (skips otherwise).
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys

import pytest

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
PORT = SDK / "ports" / "godzilla_pro-1.15.port"
# The Pro 1.15 game program extracted from the card: $PAD_GODZILLA_PRO_115_GAME, or where item 146 read it
# (the same file seen from Windows or from WSL). The ELF checks skip when none is present.
PRO_ELF_CANDIDATES = [os.environ.get("PAD_GODZILLA_PRO_115_GAME", ""),
                      r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game",
                      "/mnt/c/tmp/radium_scene_re/godzilla_pro_1_15/game"]
PRO_ELF = next((p for p in PRO_ELF_CANDIDATES if p and os.path.isfile(p)), PRO_ELF_CANDIDATES[1])

HARNESS = r"""
#define _GNU_SOURCE
#include "pad_mode.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>

extern const struct pm_mode *const __start_pm_modes[];
extern const struct pm_mode *const __stop_pm_modes[];
static int (*claimed[16])(unsigned);
static int running_mode;

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
int pm_trigger(const char *n) { return 0; }
int pm_trigger_text(const char *n, char *o, unsigned cap) { return 0; }
void *pm_node(const char *s, const char *p) { return 0; }
void *pm_text(const char *s, const char *p) { return 0; }
void pm_show(void *n, int on) {}
void pm_set_text(void *t, const char *w) {}
void pm_commas(char *o, unsigned cap, uint64_t v) { snprintf(o, cap, "%llu", (unsigned long long)v); }
int pm_lights(const char *c) { return 0; }
int pm_lights_as(unsigned o, const char *c) { return 0; }
int pm_clip(const char *n) { return 0; }
int pm_message_set(unsigned id, const char *w) { return 1; }
void pm_message_restore(unsigned id) {}
int pm_award_screen(unsigned t, unsigned m, uint64_t v) { return 1; }
static int in_game = 1;
int pm_in_game(void) { return in_game; }
static unsigned player_up = 1;
unsigned pm_player(void) { return player_up; }
uint64_t pm_score(unsigned p) { return 0; }
uint64_t pm_score_add(unsigned p, uint64_t v) { return v; }
static int c_mode;              /* a mode written in C holds pm_begin */
int pm_begin(void) { if (running_mode || c_mode) return 0; running_mode = 1; return 1; }
void pm_end(void) { running_mode = 0; }
static unsigned long now_ms;
unsigned long pm_ms(void) { return now_ms; }
long pm_port_value(const char *name, long fallback)
{ const char *v = getenv("ROSTER_AFTER_MS"); return (!strcmp(name, "roster_start_after_ms") && v) ? atol(v) : fallback; }
int pm_stock_mode_running(unsigned kinds) { return 0; }
const char *pm_stock_mode_what(unsigned kind) { return "a stock mode"; }
void pm_callout(unsigned id) {}
void pm_callout_nth(unsigned id, unsigned n) {}
int pm_callout_own_sound(unsigned c, const unsigned char k[8]) { return 0; }
int pm_can(unsigned w) { return 1; }
int pm_roster_claim(unsigned slot, int (*f)(unsigned)) { if (slot >= 7) return 0; claimed[slot] = f; printf("CLAIM %u\n", slot); return 1; }
void pm_roster_release(unsigned slot) { if (slot < 16) claimed[slot] = 0; printf("RELEASE %u\n", slot); }
void pm_roster_done(void) { printf("ROSTER_DONE\n"); }
int pm_roster_callout(unsigned slot, unsigned id) { printf("CALLOUT %u %u\n", slot, id); return slot < 7 && claimed[slot]; }

int main(int argc, char **argv)
{
    const struct pm_mode *m = *__start_pm_modes;
    int i, k;
    m->init();
    for (i = 0; i < 31; i++) { now_ms += 17; m->tick(); }
    for (k = 1; k < argc; k++) {
        if (!strcmp(argv[k], "tick")) {             /* tick <n>: n game ticks, ~17 ms each */
            int n = atoi(argv[++k]);
            for (i = 0; i < n; i++) { now_ms += 17; m->tick(); }
            printf("TICKED %d\n", n);
        } else if (!strcmp(argv[k], "shot")) {      /* shot <mask> */
            m->shot(strtoull(argv[++k], 0, 0));
        } else if (!strcmp(argv[k], "c_mode")) {    /* a mode written in C starts */
            c_mode = 1;
        } else if (!strcmp(argv[k], "game_over")) { /* pm_in_game() falls */
            in_game = 0;
        } else if (!strcmp(argv[k], "player")) {    /* player <n>: pm_player() returns n from now on */
            player_up = (unsigned)atoi(argv[++k]);
        } else if (!strcmp(argv[k], "swap")) {      /* mode.next becomes mode.cfg; the file is re-read */
            char p[512], q[512];
            snprintf(p, sizeof p, "%s/mode.next", getenv("MODE_DIR"));
            snprintf(q, sizeof q, "%s/mode.cfg", getenv("MODE_DIR"));
            rename(p, q);
            for (i = 0; i < 31; i++) m->tick();
            printf("SWAPPED\n");
        } else if (!strcmp(argv[k], "pick")) {
            unsigned s = (unsigned)atoi(argv[++k]);
            printf("PICK %u -> %d\n", s, claimed[s] ? claimed[s](s) : -1);
        } else if (!strcmp(argv[k], "ball_end")) {
            m->ball_end();
        } else if (!strcmp(argv[k], "rm")) {
            char p[512];
            snprintf(p, sizeof p, "%s/mode.cfg", getenv("MODE_DIR"));
            unlink(p);
            for (i = 0; i < 31; i++) m->tick();
        }
    }
    return 0;
}
"""


def _cc():
    if os.name == "nt":
        pytest.skip("the harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        # the CI's macOS leg: Apple clang refuses pad_mode.h's section("pm_modes") (Mach-O wants "segment,section")
        # and has no __start_/__stop_ symbols; the Linux leg runs these
        pytest.skip("the harness needs an ELF toolchain (section(\"pm_modes\"), __start_pm_modes)")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


_ATTRIBUTE = re.compile(r"__attribute__\s*\(\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)\)")
_PROTOTYPE = re.compile(r"(?:^|[;}])\s*(?P<ret>(?:const\s+)?(?:unsigned\s+|signed\s+)?\w+[\s\*]+?)"
                        r"(?P<name>pm_\w+)\s*\((?P<args>[^;{]*)\)\s*;", re.M)


def weak_stubs(header_text):
    """A no-op WEAK definition of every pm_* function pad_mode.h declares: the harness's own stubs are the
    strong ones, and a call a later item adds to mode_file.c (pm_event, pm_sound ...) still links."""
    text = re.sub(r"/\*.*?\*/", " ", header_text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    kept, in_macro = [], False
    for line in text.splitlines():                  # preprocessor lines, with their continuations
        if in_macro or line.lstrip().startswith("#"):
            in_macro = line.rstrip().endswith("\\")
            continue
        kept.append(line)
    text = _ATTRIBUTE.sub(" ", "\n".join(kept))
    out, seen = ['#include "pad_mode.h"'], set()
    for m in _PROTOTYPE.finditer(text):
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        ret = " ".join(m.group("ret").split())
        body = "{}" if ret == "void" else "{ return 0; }"
        out.append("__attribute__((weak)) %s %s(%s) %s" % (ret, name, " ".join(m.group("args").split()), body))
    return "\n".join(out) + "\n", seen


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("roster")
    (d / "harness.c").write_text(HARNESS)
    stubs, _names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    exe = d / "harness"
    for std in ("-std=gnu2x", "-std=gnu17"):     # gnu2x lets a stub keep a prototype's unnamed parameter
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args, mode1=None, after_ms=None):
    (tmp_path / "mode.cfg").write_text(cfg)
    if mode1 is not None:
        (tmp_path / "mode1.cfg").write_text(mode1)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    env.pop("ROSTER_AFTER_MS", None)
    if after_ms is not None:
        env["ROSTER_AFTER_MS"] = str(after_ms)
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


ROSTER_ONLY = "name MOTHRA\nroster_slot 0\nseconds 30\nshots 0x70300000\naward 1000000\n"


def test_a_roster_slot_needs_no_trigger_and_a_pick_starts_the_mode(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0", "pick", "0", "ball_end", "pick", "0")
    assert "unknown key" not in out
    assert "valid without a trigger" in out and "picking roster slot 0 starts it" in out
    assert "CLAIM 0" in out and "MOTHRA claims roster slot 0" in out
    picks = re.findall(r"PICK 0 -> (-?\d)", out)
    assert picks == ["1", "1", "1"]
    assert out.count("MOTHRA START (roster pick)") == 2          # the second pick lands while it runs
    assert "picked while it runs - the pick is taken, nothing restarts" in out
    assert "MOTHRA END (ball ended)" in out
    assert out.count("ROSTER_DONE") == 1                          # the battle rule is told once, at the END
    assert out.index("MOTHRA START (roster pick)") < out.index("ROSTER_DONE") < out.index("MOTHRA END (ball ended)")


def test_a_slot_the_game_does_not_have_is_not_claimed(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY.replace("roster_slot 0", "roster_slot 9"))
    assert "CLAIM" not in out
    assert "MOTHRA: roster slot 9 NOT claimed (out of range)" in out


def test_a_mode_file_without_the_key_is_unchanged(harness, tmp_path):
    out = _run(harness, tmp_path, "name KAIJU RUSH\ntrigger 0x08000000 3\nseconds 30\n", "pick", "0")
    assert "CLAIM" not in out and "roster" not in out
    assert "PICK 0 -> -1" in out and "ROSTER_DONE" not in out
    assert "NOT VALID" not in out


def test_a_roster_mode_still_needs_seconds(harness, tmp_path):
    out = _run(harness, tmp_path, "name MOTHRA\nroster_slot 0\n", "pick", "0")
    assert "CLAIM" not in out and "PICK 0 -> -1" in out


def test_the_claim_is_released_when_the_file_goes(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "rm", "pick", "0")
    assert "CLAIM 0" in out and "RELEASE 0" in out
    assert "PICK 0 -> -1" in out


BOTH = ROSTER_ONLY + "trigger 0x08000000 1\n"          # a roster slot AND a trigger shot


@pytest.mark.parametrize("how, end", [("ball_end", "END (ball ended)"), ("clock", "END (time ran out)")])
def test_a_trigger_started_mode_picked_while_it_runs_gives_the_pick_back_at_its_end(harness, tmp_path, how, end):
    """The verifiers' blocking case: started by its trigger, then its slot picked while it runs. The pick is
    taken (the runtime clears the qualified byte), so its END must call pm_roster_done - or the ramps stay dark."""
    args = ["shot", "0x08000000", "pick", "0"] + (["ball_end"] if how == "ball_end" else ["tick", "1900"])
    out = _run(harness, tmp_path, BOTH, *args)
    assert "MOTHRA START (trigger shot)" in out
    assert "PICK 0 -> 1" in out and "picked while it runs - the pick is taken" in out
    assert "MOTHRA " + end in out
    assert out.count("ROSTER_DONE") == 1
    assert out.index("picked while it runs") < out.index("ROSTER_DONE") < out.index("MOTHRA " + end)


def test_a_trigger_started_mode_never_picked_does_not_touch_the_roster(harness, tmp_path):
    out = _run(harness, tmp_path, BOTH, "shot", "0x08000000", "ball_end")
    assert "MOTHRA START (trigger shot)" in out and "MOTHRA END (ball ended)" in out
    assert "ROSTER_DONE" not in out


KAIJU = "name KAIJU RUSH\ntrigger 0x00100000 1\nseconds 5\n"


def test_a_pick_while_another_mode_runs_starts_when_that_one_ends(harness, tmp_path):
    """Not the game's battle under our name: the pick is taken and the mode starts once the other one ends."""
    out = _run(harness, tmp_path, ROSTER_ONLY, "shot", "0x00100000", "pick", "0", "tick", "400", "ball_end",
               mode1=KAIJU)
    assert "KAIJU RUSH START (trigger shot)" in out
    assert "PICK 0 -> 1" in out
    assert "MOTHRA: roster slot 0 picked while KAIJU RUSH runs - it starts when that one ends" in out
    assert out.index("KAIJU RUSH END (time ran out)") < out.index("MOTHRA START (roster pick)")
    assert "MOTHRA END (ball ended)" in out
    assert out.count("ROSTER_DONE") == 1
    assert out.index("MOTHRA START (roster pick)") < out.index("ROSTER_DONE") < out.index("MOTHRA END (ball ended)")


def test_the_start_waits_roster_start_after_ms(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0", "tick", "120", "tick", "80", after_ms=3000)
    assert "PICK 0 -> 1" in out and "picked - it starts in 3000 ms, once the selection screen has closed" in out
    first, second = out.index("TICKED 120"), out.index("TICKED 80")
    assert "START" not in out[:first]                              # 2.0 s: not yet
    assert out.index("MOTHRA START (roster pick)") < second         # by 3.4 s: started
    assert "ROSTER_DONE" not in out


def test_a_pick_that_cannot_start_is_given_back_and_the_battle_does_not_run(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "c_mode", "pick", "0")
    assert "PICK 0 -> 1" in out                                     # taken: the game's battle does not start
    assert "START" not in out
    assert "picked but not started - the pick is given back" in out
    assert out.count("ROSTER_DONE") == 1


def test_a_ball_that_ends_before_a_waiting_pick_starts_gives_it_back(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0", "ball_end", "tick", "300", after_ms=3000)
    assert "the ball ended before the roster pick started - the pick is given back" in out
    assert out.count("ROSTER_DONE") == 1 and "START" not in out


def test_a_picked_mode_with_ends_on_clock_still_ends_with_its_ball(harness, tmp_path):
    """Item 147's `ends_on clock` keeps a mode running into the next ball. A PICKED mode must not: the runtime
    gives an unreturned pick back at the end of the ball, which would light the ramps (and count the city) while
    the mode runs on - the failure run2 ruled out. So a pick ends with its ball, as the game's battles do."""
    cfg = ROSTER_ONLY + "ends_on clock\n"
    out = _run(harness, tmp_path, cfg, "pick", "0", "ball_end", "tick", "1900")
    assert "MOTHRA START (roster pick)" in out
    assert "a roster pick ends with its ball, as the game's battles do (ends_on clock ignored)" in out
    assert "running on (ends_on clock)" not in out
    assert out.count("MOTHRA END") == 1 and "MOTHRA END (ball ended)" in out
    assert out.count("ROSTER_DONE") == 1
    assert out.index("MOTHRA START (roster pick)") < out.index("ROSTER_DONE") < out.index("MOTHRA END (ball ended)")
    # the control: the same file started by its trigger and never picked still runs on through the ball's end
    out = _run(harness, tmp_path, cfg + "trigger 0x08000000 1\n", "shot", "0x08000000", "ball_end")
    assert "MOTHRA START (trigger shot)" in out and "running on (ends_on clock)" in out
    assert "MOTHRA END" not in out and "ROSTER_DONE" not in out


@pytest.mark.parametrize("value", ["-1", "zero", "3000000000", "0x100000000", "16"])
def test_a_roster_slot_that_is_not_a_small_number_is_ignored(harness, tmp_path, value):
    """`roster_slot -1` used to read as 0 and claim slot 0; a huge number used to wrap into range."""
    out = _run(harness, tmp_path, ROSTER_ONLY.replace("roster_slot 0", "roster_slot " + value), "pick", "0")
    assert "CLAIM" not in out and "PICK 0 -> -1" in out
    assert "ignored" in out and "roster_slot" in out


def test_a_trigger_with_a_count_of_0_still_starts_nothing(harness, tmp_path):
    """`trigger <shots> 0` made a file NOT VALID before roster_slot existed; with roster_slot the shots must not
    start it either - only the pick does."""
    out = _run(harness, tmp_path, ROSTER_ONLY + "trigger 0x08000000 0\n", "shot", "0x08000000", "shot", "0x08000000",
               "pick", "0")
    assert "with a count of 0 starts nothing" in out
    assert "START (trigger shot)" not in out and "trigger 1 of 0" not in out
    assert "MOTHRA START (roster pick)" in out


def test_a_waiting_pick_that_lapses_is_given_back(harness, tmp_path):
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0", "game_over", "tick", "300", after_ms=3000)
    assert "the roster pick lapsed" in out
    assert out.count("ROSTER_DONE") == 1 and "START" not in out


def test_a_waiting_pick_lapses_when_another_player_is_up(harness, tmp_path):
    """roster_tick's other lapse branch: the player who picked is no longer up when the wait ends (a multi-player
    game). The mode must not start for the wrong player; the pick is given back (the runtime then waits for the
    player who picked - test_the_runtime_gives_a_pick_back_only_to_the_player_who_picked)."""
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0", "player", "2", "tick", "300", after_ms=3000)
    assert "PICK 0 -> 1" in out and "picked - it starts in 3000 ms" in out
    assert "the roster pick lapsed - the player changed or the game ended" in out
    assert out.count("ROSTER_DONE") == 1 and "START" not in out


def test_the_same_player_still_up_starts_the_waiting_pick(harness, tmp_path):
    """The control for the case above: player 2 picks and is still up when the wait ends."""
    out = _run(harness, tmp_path, ROSTER_ONLY, "player", "2", "pick", "0", "tick", "300", after_ms=3000)
    assert "MOTHRA START (roster pick)" in out and "lapsed" not in out and "ROSTER_DONE" not in out


def test_a_claimed_slot_without_roster_callout_asks_for_nothing(harness, tmp_path):
    """The runtime makes a claimed slot silent itself; a file without the line writes nothing more."""
    out = _run(harness, tmp_path, ROSTER_ONLY, "pick", "0")
    assert "CLAIM 0" in out and "CALLOUT" not in out and "unknown key" not in out


def test_roster_callout_names_the_slot_and_a_reload_follows_the_file(harness, tmp_path):
    (tmp_path / "mode.next").write_text(ROSTER_ONLY)
    out = _run(harness, tmp_path, ROSTER_ONLY + "roster_callout 207\n", "swap")
    assert "unknown key" not in out
    assert out.index("CLAIM 0") < out.index("CALLOUT 0 207") < out.index("SWAPPED")
    assert "MOTHRA: roster slot 0's callout is 207" in out
    after = out[out.index("CALLOUT 0 207") + 1:]
    assert "CALLOUT 0 0" in after and "roster slot 0's callout is 0 (silent)" in after     # the line went: silent again
    assert "RELEASE" not in out                                                              # the slot stays claimed


@pytest.mark.parametrize("value", ["-1", "mothra", "65536", "99999999999"])
def test_a_roster_callout_that_is_not_a_sound_id_is_ignored(harness, tmp_path, value):
    out = _run(harness, tmp_path, ROSTER_ONLY + "roster_callout " + value + "\n", "pick", "0")
    assert "CLAIM 0" in out and "CALLOUT" not in out
    assert "roster_callout needs a sound request id 0-65535" in out and "ignored" in out


def test_the_weak_stubs_find_every_kind_of_prototype():
    stubs, names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    for n in ("pm_log", "pm_snprintf", "pm_can", "pm_game", "pm_ms", "pm_node", "pm_score", "pm_shot_at",
              "pm_callout_own_sound", "pm_stock_mode_running", "pm_roster_claim", "pm_roster_done"):
        assert n in names, n
    assert "__attribute__((weak)) void pm_roster_done(void) {}" in stubs
    later = "/* a later item */\nint pm_event(const char *name, unsigned long *when);\nvoid pm_sound_stop(void);\n" \
            "const char *pm_sound_name(unsigned id)\n    __attribute__((pure));\n"
    _stubs, names = weak_stubs(later)
    assert names == {"pm_event", "pm_sound_stop", "pm_sound_name"}


def test_every_capability_bit_is_its_own():
    """PM_CAN_ROSTER was 0x0080, which item 147 also took for PM_CAN_EVENTS: pm_can() would then confuse them."""
    bits = re.findall(r"#define\s+(PM_CAN_\w+)\s+(0x[0-9a-fA-F]+)u?", (SDK / "pad_mode.h").read_text(encoding="utf-8"))
    values = [int(v, 16) for _n, v in bits]
    assert dict(bits).get("PM_CAN_ROSTER") == "0x0100"
    assert len(set(values)) == len(values), bits
    assert all(v and v & (v - 1) == 0 for v in values), bits


RUNTIME = SDK / "pad_mode_runtime.c"


def _lift(src, signature):
    """A function's text, verbatim from the runtime (brace-matched from its signature)."""
    i = src.index(signature)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced: " + signature)


def _host_run(tmp_path, code, flags=(), args=()):
    cc = _cc()
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", *flags, "-o", str(tmp_path / "t"),
                        str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t"), *args], capture_output=True, text=True, timeout=30).stdout


def test_the_runtime_needs_both_roster_sites():
    """A port whose roster_done does not verify must not take picks: nothing could give them back."""
    src = RUNTIME.read_text(encoding="utf-8")
    assert re.search(r'roster_s\[\]\s*=\s*\{\s*"roster_start",\s*"roster_done",\s*0\s*\}', src)


def test_the_runtime_claim_refuses_a_slot_out_of_range(tmp_path):
    """The bound was `(int)slot >= slots`: 3000000000 and 0xfffffffe went negative, passed, and indexed out of
    bounds inside the game."""
    lifted = _lift(RUNTIME.read_text(encoding="utf-8"), "int pm_roster_claim(unsigned slot, int (*on_pick)(unsigned slot))")
    out = _host_run(tmp_path, "#include <stdio.h>\n#define N_ROSTER 16\nstruct pm_mode;\n"
                    "static const struct pm_mode *current;\nstatic int (*roster_fn[N_ROSTER])(unsigned slot);\n"
                    "static const struct pm_mode *roster_by[N_ROSTER];\nstatic int pm_roster_slots(void) { return 7; }\n"
                    "static int roster_callout_set(unsigned s, unsigned id, const char *why) { return 0; }\n"
                    + lifted + "\nstatic int pick(unsigned s) { return 1; }\n"
                    "int main(void) { printf(\"%d %d %d %d %d\\n\", pm_roster_claim(6, pick), pm_roster_claim(7, pick),"
                    " pm_roster_claim(3000000000u, pick), pm_roster_claim(0xfffffffeu, pick),"
                    " pm_roster_claim(0xffffffffu, pick)); return 0; }\n")
    assert out.split() == ["1", "0", "0", "0", "0"]


CALLOUT_PRELUDE = r"""
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#define N_ROSTER 16
struct pm_mode { int x; };
static const struct pm_mode *current;
static int (*roster_fn[N_ROSTER])(unsigned slot);
static const struct pm_mode *roster_by[N_ROSTER];
static int pm_roster_slots(void) { return 7; }
static void say(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
static unsigned char table[8 * 32];                /* the game's slot table: -no-pie keeps it below 4 GB */
static unsigned table_at;
static unsigned data(const char *name) { return strcmp(name, "roster_screen_table") ? 0 : table_at; }
static long pm_port_value(const char *name, long fallback)
{
    if (!strcmp(name, "roster_screen_record_size")) return 32;
    if (!strcmp(name, "roster_callout_at")) return 28;
    return fallback;
}
"""

CALLOUT_MAIN = r"""
static int pick(unsigned s) { return 1; }
static unsigned id(unsigned slot) { unsigned short v; memcpy(&v, table + slot * 32 + 28, 2); return v; }
/* the call happens BEFORE the table is read (printf's arguments have no evaluation order) */
static void row(const char *label, int r, unsigned slot) { unsigned v = id(slot); printf("%s %d %u\n", label, r, v); }
int main(int argc, char **argv)
{
    static const unsigned ids[7] = { 1888, 1918, 1894, 1910, 0, 0, 0 };   /* Godzilla Pro 1.15 */
    static const struct pm_mode a = { 1 }, b = { 2 };
    unsigned k;
    int r;
    if ((unsigned long)table > 0xffffffffUL) { printf("HIGH\n"); return 0; }
    for (k = 0; k < 7; k++) { unsigned short v = (unsigned short)ids[k]; memcpy(table + k * 32 + 28, &v, 2); }
    if (argc > 1) { unsigned short v = 0x4000; memcpy(table + 5 * 32 + 28, &v, 2); }   /* not a callout table */
    table_at = (unsigned)(unsigned long)table;
    current = &a;
    r = pm_roster_claim(0, pick);   row("claim", r, 0);
    r = pm_roster_callout(0, 207);  row("set", r, 0);
    r = pm_roster_callout(1, 207);  row("unheld", r, 1);
    current = &b;
    r = pm_roster_callout(0, 5);    row("other", r, 0);
    pm_roster_release(0);           row("other_release", 0, 0);
    current = &a;
    r = pm_roster_claim(0, pick);   row("reclaim", r, 0);
    pm_roster_release(0);           row("release", 0, 0);
    r = pm_roster_claim(0, pick);   row("claim2", r, 0);
    pm_roster_release(0);           row("release2", 0, 0);
    row("slot1", 0, 1);
    return 0;
}
"""


@pytest.mark.parametrize("table", ["godzilla", "not_a_callout_table"])
def test_the_runtime_silences_a_claimed_slot_and_puts_the_callout_back(tmp_path, table):
    """The selection screen says a slot's name from its own table (slot 0: 1888, "Ebirah!") and plays nothing
    for 0. A claimed slot goes silent, its holder alone can name another id, and release puts the game's back.
    A table whose ids do not look like callouts is never written."""
    src = RUNTIME.read_text(encoding="utf-8")
    lifted = "\n".join(_lift(src, sig) for sig in (
        "static unsigned short *roster_callout_word(unsigned slot)", "static int roster_callout_set(",
        "static void roster_callout_restore(", "int pm_roster_callout(", "int pm_roster_claim(",
        "void pm_roster_release("))
    decl = "static unsigned roster_callout_was[N_ROSTER];"
    assert decl in src
    out = _host_run(tmp_path, CALLOUT_PRELUDE + decl + "\n" + lifted + CALLOUT_MAIN, flags=("-no-pie",),
                    args=(("bad",) if table != "godzilla" else ()))
    if out.strip() == "HIGH":
        pytest.skip("this host links the table above 4 GB even with -no-pie")
    rows = {line.split(" ", 1)[0]: line.split(" ", 1)[1] for line in out.strip().splitlines() if line[:1].islower()}
    if table == "godzilla":
        assert "holds a callout id per slot" in out
        assert rows["claim"] == "1 0"                 # claimed: silent
        assert rows["set"] == "1 207"                 # the holder names one
        assert rows["unheld"] == "0 1918"             # a slot nobody holds is not written
        assert rows["other"] == "0 207"               # nor one somebody else holds
        assert rows["other_release"] == "0 207"
        assert rows["reclaim"] == "1 207"             # a claim again by the holder keeps its id
        assert rows["release"] == "0 1888"            # released: the game's again
        assert rows["claim2"] == "1 0"
        assert rows["release2"] == "0 1888" and rows["slot1"] == "0 1918"
        assert "slot 0's callout 1888 -> 0 (claimed" in out and "slot 0's callout 207 -> 1888 (released" in out
    else:
        assert "does not look like one" in out
        assert rows["claim"] == "1 1888" and rows["set"] == "0 1888" and rows["release2"] == "0 1888"


def test_the_runtime_gives_a_pick_back_only_to_the_player_who_picked(tmp_path):
    """pm_roster_done's decision: the rule's "battle over" acts on the player UP, so a give-back waits for the
    player who picked, and nothing is done with no pick held or outside a game."""
    lifted = _lift(RUNTIME.read_text(encoding="utf-8"), "static unsigned roster_give_back(")
    out = _host_run(tmp_path, "#include <stdio.h>\n" + lifted + r"""
static unsigned char owed[5];
static void t(const char *label, int in_game, unsigned up)
{
    const char *why = 0;
    unsigned r = roster_give_back(owed, in_game, up, &why);
    printf("%s %u %u%u%u%u %s\n", label, r, owed[1], owed[2], owed[3], owed[4], why ? why : "-");
}
int main(void)
{
    t("none", 1, 1);
    owed[1] = 1; t("held_up", 1, 1);
    owed[1] = 1; t("other_up", 1, 2); t("still_other", 1, 2); t("back_up", 1, 1);
    owed[1] = 1; t("other", 1, 3); t("game_over", 0, 3);
    owed[1] = 1; owed[2] = 1; t("two_held", 1, 2); t("one_left", 1, 4); t("its_player", 1, 1);
    return 0;
}
""")
    rows = {line.split(" ", 1)[0]: line.split(" ", 3)[1:] for line in out.strip().splitlines()}
    assert rows["none"][:2] == ["0", "0000"] and rows["none"][2].startswith("no pick is held")
    assert rows["held_up"] == ["1", "0000", "-"]
    assert rows["other_up"][:2] == ["0", "2000"] and rows["other_up"][2].startswith("another player is up")
    assert rows["still_other"][:2] == ["0", "2000"]
    assert rows["back_up"] == ["1", "0000", "-"]
    assert rows["other"][:2] == ["0", "2000"]
    assert rows["game_over"][:2] == ["0", "0000"] and rows["game_over"][2].startswith("no game is being played")
    assert rows["two_held"] == ["2", "1000", "-"]
    assert rows["one_left"][:2] == ["0", "2000"]
    assert rows["its_player"] == ["1", "0000", "-"]


def test_the_grey_sheet_splice_replaces_only_the_blocks_a_changed_pixel_touches():
    """roster_entry.py's grey sheet: the seven unselected tiles are ONE BC3 image, so only the 4x4 blocks that hold
    a changed pixel are taken from the re-encode; every other block keeps the stock bytes."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import importlib.util
    spec = importlib.util.spec_from_file_location("roster_entry", SDK.parent / "roster_entry.py")
    re_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(re_mod)
    w, h = 16, 12                                        # 4 x 3 blocks, 16 bytes each
    stock = bytes(range(256))[:48] * 4
    new = bytes(255 - b for b in stock)
    changed = np.zeros((h, w), bool)
    changed[1, 1] = True                                 # block (0, 0)
    changed[9, 14] = True                                # block (2, 3)
    out, touched = re_mod.splice_blocks(stock, new, w, h, changed)
    assert touched.shape == (3, 4) and int(touched.sum()) == 2
    for j in range(3):
        for i in range(4):
            o = (j * 4 + i) * 16
            want = new if (j, i) in ((0, 0), (2, 3)) else stock
            assert out[o:o + 16] == want[o:o + 16], (j, i)


def _port_lines(port=PORT):
    out = {}
    for line in open(port, encoding="utf-8"):
        f = line.split()
        if len(f) >= 3 and not f[0].startswith("#"):
            out[(f[0], f[1])] = f[2:]
    return out


def test_the_pro_port_names_the_roster():
    p = _port_lines()
    assert int(p[("site", "roster_start")][0], 0) == 0x1220B8
    assert int(p[("site", "roster_done")][0], 0) == 0x122014
    assert int(p[("value", "roster_qualified_at")][0], 0) == 83
    assert int(p[("data", "rule_battle")][0], 0) == 0x79D8E0
    assert int(p[("value", "roster_slots")][0], 0) == 7
    assert int(p[("value", "roster_vec_at")][0], 0) == 8
    assert int(p[("value", "roster_record_size")][0], 0) == 12
    assert int(p[("value", "roster_id_at")][0], 0) == 4
    assert int(p[("value", "roster_start_after_ms")][0], 0) == 3000


def test_the_premium_port_names_the_roster_and_it_is_on():
    """Premium 1.16 (David's model): drafted, then switched on by item 146 run5 (a claimed pick and a stock pick
    through the hook in the emulator). Same record layout as Pro 1.15, other addresses."""
    p = _port_lines(SDK / "ports" / "godzilla_le-1.16.port")
    assert p[("site", "roster_start")][:3] == ["0x001249c8", "0xe5903000", "0xe5933020"]
    assert p[("site", "roster_done")][:3] == ["0x00124924", "0xe92d4010", "0xe1a04000"]
    assert int(p[("data", "rule_battle")][0], 0) == 0x7B0C70
    for name, want in (("roster_slots", 7), ("roster_vec_at", 8), ("roster_record_size", 12), ("roster_id_at", 4),
                       ("roster_qualified_at", 83), ("roster_start_after_ms", 3000)):
        assert int(p[("value", name)][0], 0) == want, name
    assert "#off" not in (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")


def _elf():
    if not os.path.exists(PRO_ELF):
        pytest.skip("game program not present: %s" % PRO_ELF)
    b = open(PRO_ELF, "rb").read()
    phoff, = struct.unpack_from("<I", b, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
    loads = []
    for i in range(phnum):
        t, off, va, _pa, fsz, _m, _fl, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
        if t == 1:
            loads.append((off, va, fsz))

    def word(va):
        for off, v, fsz in loads:
            if v <= va < v + fsz:
                return struct.unpack_from("<I", b, off + va - v)[0]
        raise KeyError(hex(va))
    return word


def test_the_roster_is_a_fixed_table_of_seven_on_pro_1_15():
    """The evidence behind the fallback: the constructor copies 84 bytes (7 x 12) from a rodata table,
    and the pick bounds the slot with a literal 6 before loading the battle's START at roster_start."""
    word = _elf()
    assert word(0x1214B4) == 0xE3A00054                 # mov r0, #84        (new(84))
    assert word(0x1214E0) == 0xE3A02054                 # mov r2, #84        (memcpy length)
    assert word(0x121514) == 0x00631F44                 # the literal the memcpy source comes from
    ids = [word(0x631F44 + 12 * k + 4) for k in range(7)]
    slots = [word(0x631F44 + 12 * k) for k in range(7)]
    assert slots == list(range(7)) and ids == [12, 13, 14, 15, 16, 6, 17]
    assert word(0x122070) == 0xE3510006                 # cmp r1, #6         (start_slot's bound)
    assert word(0x1220B8) == 0xE5903000 and word(0x1220BC) == 0xE5933020   # ldr r3,[r0]; ldr r3,[r3,#32]
    assert word(0x1220C0) == 0xE12FFF33                 # blx r3             (the battle's START)
    assert word(0x18DBB0) == 0xE3560007                 # cmp r6, #7         (the selector's slot loop)


# ---- item 146 fix-2: a pick counts for the city ---------------------------------------------------------------------

CITY_PRELUDE = r"""
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
struct site { int ok; };
static void say(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
static unsigned cities[32];                 /* RuleCities: +20+4p city index, +44/+48 the mask vector (-no-pie: < 4 GB) */
static unsigned masks[5 * 4];               /* five cities x four players, as on Godzilla */
static unsigned have_site = 1, have_data = 1;
static const char *drop_value = "";
static unsigned data(const char *name) { return have_data && !strcmp(name, "rule_cities") ? (unsigned)(unsigned long)cities : 0; }
static void city_done(unsigned rc, unsigned bit)   /* what the game's 0x135394 does, for the player up (1 here) */
{
    unsigned *c = (unsigned *)(unsigned long)rc;
    masks[c[(20 + 4 * 1) / 4] * 4 + 0] |= 1u << bit;
}
static unsigned fn(const char *name) { return have_site && !strcmp(name, "roster_city_done") ? (unsigned)(unsigned long)city_done : 0; }
static long pm_port_value(const char *name, long fallback)
{
    if (!strcmp(name, drop_value)) return fallback;
    if (!strcmp(name, "roster_city_bit")) return 1;
    if (!strcmp(name, "roster_city_index_at")) return 20;
    if (!strcmp(name, "roster_city_vec_at")) return 44;
    if (!strcmp(name, "roster_city_record_size")) return 16;
    return fallback;
}
"""

CITY_MAIN = r"""
static void t(const char *label, unsigned p, unsigned city)
{
    int r;
    cities[(20 + 4 * p) / 4] = city;
    r = roster_city_step(p);
    printf("%s %d %x\n", label, r, city < 5 ? masks[city * 4 + (p ? p - 1 : 0)] : 0);
}
int main(void)
{
    if ((unsigned long)cities > 0xffffffffUL || (unsigned long)city_done > 0xffffffffUL) { printf("HIGH\n"); return 0; }
    cities[44 / 4] = (unsigned)(unsigned long)masks;
    cities[48 / 4] = (unsigned)(unsigned long)(masks + 20);
    masks[2 * 4] = 0x5;                      /* city 2: tank attack and bridge attack done already */
    t("counted", 1, 2);
    t("again", 1, 2);
    t("outside", 1, 5);
    t("no_player", 0, 2);
    drop_value = "roster_city_record_size"; t("no_record_size", 1, 3); drop_value = "";
    have_site = 0; t("no_site", 1, 3); have_site = 1;
    have_data = 0; t("no_data", 1, 3); have_data = 1;
    cities[44 / 4] = 0; t("no_vector", 1, 3);
    return 0;
}
"""


def test_the_runtime_counts_a_pick_in_the_players_city(tmp_path):
    """The game's battle stop marks the battle done in the player's city (RuleCities 0x135394(cities, 1)); pm_roster_done
    now does the same through the port's `site roster_city_done`, and only after checking the city index against the
    city table (the game's function throws on a bad one). A port without the lines changes nothing."""
    src = RUNTIME.read_text(encoding="utf-8")
    lifted = _lift(src, "static int roster_city_step(unsigned p)")
    assert "roster_city_step(pm_player());" in _lift(src, "void pm_roster_done(void)")
    out = _host_run(tmp_path, CITY_PRELUDE + lifted + CITY_MAIN, flags=("-no-pie",))
    if out.strip() == "HIGH":
        pytest.skip("this host links above 4 GB even with -no-pie")
    rows = {line.split(" ", 1)[0]: line.split(" ", 1)[1] for line in out.strip().splitlines() if line[:1].islower()}
    assert rows["counted"] == "1 7"                          # 0x5 | bit 1
    assert "counts as the battle of player 1's city 2 (its mask 5 -> 7)" in out
    assert rows["again"] == "1 7"
    assert rows["outside"].startswith("0") and "city 5 is not in the city table (80 bytes)" in out
    assert rows["no_player"].startswith("0") and "no player is up (0)" in out
    assert rows["no_record_size"] == "0 0" and "record 0" in out
    assert rows["no_site"] == "0 0" and rows["no_data"] == "0 0"
    assert rows["no_vector"] == "0 0" and "city 3 is not in the city table (0 bytes)" in out


def test_both_godzilla_ports_count_the_pick_in_the_city():
    for port, site, rc in (("godzilla_pro-1.15.port", "0x00135394", 0x79DAE8), ("godzilla_le-1.16.port", "0x001387ac", 0x7B0E78)):
        p = _port_lines(SDK / "ports" / port)
        assert p[("site", "roster_city_done")][:3] == [site, "0xe92d4070", "0xe24dd010"], port
        assert int(p[("data", "rule_cities")][0], 0) == rc, port
        for name, want in (("roster_city_bit", 1), ("roster_city_index_at", 20), ("roster_city_vec_at", 44),
                           ("roster_city_record_size", 16)):
            assert int(p[("value", name)][0], 0) == want, (port, name)


def test_the_battle_stop_counts_the_battle_in_the_city_on_pro_1_15():
    """The evidence behind roster_city_done: RuleBattle's stop loads RuleCities and bit 1 and calls 0x135394, which ORs
    the bit into the player's mask for the city and calls the city complete when the mask is 15."""
    word = _elf()
    assert word(0x122D04) == 0xE30D0AE8                 # movw r0, #0xdae8
    assert word(0x122D08) == 0xE3A01001                 # mov r1, #1          (the battle's bit)
    assert word(0x122D0C) == 0xE3400079                 # movt r0, #0x79     (RuleCities 0x79dae8)
    assert word(0x122D10) == 0xEB000000 | (((0x135394 - 0x122D10 - 8) >> 2) & 0xFFFFFF)   # bl 0x135394
    assert word(0x135394) == 0xE92D4070 and word(0x135398) == 0xE24DD010
    assert word(0x1353DC) == 0xE1836612                 # orr r6, r3, r2, lsl r6
    assert word(0x135420) == 0xE353000F                 # cmp r3, #15        (all four done: the city is complete)
