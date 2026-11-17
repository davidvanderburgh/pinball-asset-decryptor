"""PAD-1330: a mode as a challenge of its own on Star Wars ELG 1.10's Spike 3 start menu.

PAD-1286 left the game's challenges out of the Spike 3 build: the challenge menu's code wrote the entry's name as a
4-byte pointer and read the menu's frame at 32-bit offsets, and the port had no challenge flag, menu kind, balls getter,
extra-ball test, end of ball or ball launch. Now:

- challenge_menu_built finds the count through menu_count_of (hook_full's x22 on ELG's Spike 3) and writes / compares
  the name as a pm_addr; challenge_menu_picked reads the kind from the port's register (w1), as comp_menu_picked does;
- Spike 3 built Spike 2's balls-per-game getter into each of its callers: two whole functions (`site challenge_balls`,
  `challenge_balls_2`, vetoed as on Spike 2) and four compares inside functions (`site challenge_balls_at_<k>` with the
  register in `value challenge_balls_at_<k>_reg`), where a mode's challenge game says 1;
- the port names flag 18, kind 2 (it sets flag 18 alone), CHALLENGE (1921), the extra-ball test 0x304ba0, the end of the
  ball 0x322180 and the launch button's handler 0x31b9b0 (flags 12 / 13);
- the challenge_plain wrappers pass whole registers.

The tests that read the real program run when PAD_S3_PROGRAMS names a folder holding star_wars_elg.game. The lifted C
runs on a 64-bit host compiler: Spike 3's word size.
"""
import os
import pathlib
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
ELG3 = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")

SITES = {   # name: (address, what the program does there)
    "challenge_balls": 0x4177C0,
    "challenge_balls_2": 0x417880,
    "challenge_balls_at_0": 0x4179A8,
    "challenge_balls_at_1": 0x4179FC,
    "challenge_balls_at_2": 0x417A90,
    "challenge_balls_at_3": 0x417C4C,
    "challenge_extra_ball": 0x304BA0,
    "challenge_end_ball": 0x322180,
    "ball_launch": 0x31B9B0,
}


def _host(tmp_path, code):
    cc = R._cc()
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-Wno-unused-function", "-o",
                        str(tmp_path / "t"), str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout


# ---- the start menu at Spike 3's word size ----------------------------------------------------------------------
MENU_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned long pm_addr;
typedef unsigned long pm_reg;
#define PMU "lu"
#define FULL_REG_LAST 28
#define FULL_SP(r) ((unsigned char *)(unsigned long)(r)[31])
#define HOOK_SP(r) ((unsigned char *)((r) + 10))
#define N_CHALLENGE 8
#define N_OWN_CHALLENGE 16
#define CHALLENGE_MENU_KIND 0x100u
static int (*challenge_fn[N_CHALLENGE])(unsigned slot);
static char challenge_title[N_CHALLENGE][40];
static int challenges_n;
static struct { int (*fn)(unsigned slot); const void *by; char name[40]; int launch; } own_challenge[N_OWN_CHALLENGE];
static volatile int own_pending = -1;
static int challenge_menu_said, challenge_menu_room_said;
static long pm_port_value(const char *k, long d)
{
    if (!strcmp(k, "challenge_menu_count_reg")) return 22;
    if (!strcmp(k, "challenge_menu_list_at")) return 248;
    if (!strcmp(k, "challenge_menu_cap")) return 7;
    if (!strcmp(k, "challenge_menu_entry")) return 16;
    if (!strcmp(k, "challenge_menu_pick_reg")) return 1;
    if (!strcmp(k, "challenge_menu_kind")) return 2;
    if (!strcmp(k, "challenge_menu_slot")) return -1;
    if (!strcmp(k, "challenge_menu_caption")) return 1921;
    return d;
}
static void say(const char *f, ...) { va_list a; va_start(a, f); printf("say: "); vprintf(f, a); printf("\n"); va_end(a); }
#define pm_snprintf snprintf
@DEFS@
@FNS@
static unsigned char frame[0x230] __attribute__((aligned(16)));
static void entry(int i, unsigned kind, unsigned short cap, const char *name)
{
    *(unsigned *)(frame + 248 + 16 * i) = kind;
    *(unsigned short *)(frame + 248 + 16 * i + 4) = cap;
    *(pm_addr *)(frame + 248 + 16 * i + 8) = (pm_addr)name;
}
static int yes(unsigned s) { (void)s; return 1; }
int main(void)
{
    pm_reg a[32] = { 0 }, p[10] = { 0 };
    int i;
    memset(frame, 0xee, sizeof frame);
    entry(0, 0, 1914, "NORMAL PLAY"); entry(1, 6, 1925, "DJ MIXER");       /* a fresh card's menu */
    own_challenge[0].fn = yes; strcpy(own_challenge[0].name, "PAD CHALLENGE");
    own_challenge[1].fn = yes; strcpy(own_challenge[1].name, "TRENCH RUN");
    a[22] = 2; a[31] = (pm_reg)frame;
    challenge_menu_built(a);
    printf("count %lu\n", a[22]);
    for (i = 0; i < (int)a[22]; i++)
        printf("E %u %u %s\n", *(unsigned *)(frame + 248 + 16 * i), *(unsigned short *)(frame + 248 + 16 * i + 4),
               *(const char **)(frame + 248 + 16 * i + 8));
    printf("next %#x\n", frame[248 + 16 * 4]);
    challenge_menu_built(a);                               /* every menu frame of an every-frame site: once */
    printf("again %lu\n", a[22]);
    p[1] = 0x101; challenge_menu_picked(p); printf("pick ours %d kind %lu\n", own_pending, p[1]);
    p[1] = 0; challenge_menu_picked(p); printf("pick game's %d kind %lu\n", own_pending, p[1]);
    p[1] = 0x100 | (1ul << 40); challenge_menu_picked(p); printf("pick high %d kind %lu\n", own_pending, p[1]);
    for (i = 2; i < 7; i++) entry(i, 1, 1919, "THE GAME'S");                /* a menu the game filled */
    a[22] = 7; challenge_menu_built(a); printf("full %lu\n", a[22]);
    return 0;
}
"""


def test_the_challenge_menu_at_spike3s_word_size(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    defs = "\n".join(ln for ln in src.splitlines() if ln.startswith("#define MENU_"))
    fns = "\n".join(R._lift(src, s) for s in (
        "static unsigned *menu_count_of(pm_reg *r, unsigned char **fsp)",
        "static int own_entry_at(const unsigned char *ent, unsigned kat, unsigned nat)",
        "static int own_kind(pm_reg kind)", "static void challenge_menu_built(pm_reg *r)",
        "static void challenge_menu_picked(pm_reg *r)"))
    out = _host(tmp_path, MENU_MAIN.replace("@DEFS@", defs).replace("@FNS@", fns)).splitlines()
    assert "count 4" in out
    entries = [l for l in out if l.startswith("E ")]
    # ours after the game's two, under CHALLENGE, each name a whole 8-byte pointer to the mode's name
    assert entries == ["E 0 1914 NORMAL PLAY", "E 6 1925 DJ MIXER", "E 256 1921 PAD CHALLENGE", "E 257 1921 TRENCH RUN"]
    assert "next 0xee" in out                                   # nothing written past the last entry
    assert "again 4" in out
    assert "pick ours 1 kind 2" in out                          # kind 2: the game's plain challenge game (flag 18)
    assert "pick game's -1 kind 0" in out
    assert "pick high 0 kind 2" in out                          # the kind is the w register: the low word alone
    assert "full 7" in out and any("no room for PAD CHALLENGE" in l for l in out)


BALLS_MAIN = r"""
#include <stdio.h>
#include <string.h>
typedef unsigned long pm_reg;
#define FULL_REG_LAST 28
static int ours;
static int challenge_balls_veto(pm_reg *r, unsigned n) { (void)r; (void)n; return ours; }
static long pm_port_value(const char *k, long d)
{
    if (!strcmp(k, "challenge_balls_at_0_reg")) return 19;
    if (!strcmp(k, "challenge_balls_at_1_reg")) return 20;
    if (!strcmp(k, "challenge_balls_at_2_reg")) return 30;          /* past what hook_full writes back */
    return d;
}
#define pm_snprintf snprintf
@FNS@
int main(void)
{
    pm_reg a[32];
    int k;
    for (k = 0; k < 32; k++) a[k] = 3;
    balls_at(a, 0); printf("plain %lu\n", a[19]);
    ours = 1;
    balls_at(a, 0); balls_at(a, 1); balls_at(a, 2); balls_at(a, 3);
    printf("ours %lu %lu %lu\n", a[19], a[20], a[30]);
    return 0;
}
"""


def test_a_balls_count_built_into_a_function_says_one_in_a_modes_challenge_game(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    out = _host(tmp_path, BALLS_MAIN.replace("@FNS@", R._lift(src, "static void balls_at(pm_reg *r, int k)")))
    assert "plain 3" in out                                     # a game of the game's own: untouched
    assert "ours 1 1 3" in out                                  # x19 / x20 say 1; a register it cannot write: left


def test_the_runtime_arms_them_with_the_challenges():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = src[src.index("static void challenges_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert "balls_at_arm();" in arm
    at = src[src.index("static void balls_at_arm(void)"):]
    at = at[:at.index("\n}\n")]
    assert "hook_full(fn(key), balls_at_fns[k])" in at
    call = src[src.index("static pm_reg plain_call("):]
    assert call.index("pm_reg a, pm_reg b, pm_reg c, pm_reg d") < call.index("\n}\n")   # whole registers on Spike 3


# ---- the port and the Modes tab ---------------------------------------------------------------------------------
def test_the_elg_spike3_port_names_the_challenge_game():
    port = MP.read_port(str(ELG3))
    for name, va in SITES.items():
        assert port["site"][name][0] == va, name
    v = port["value"]
    assert (v["challenge_on_flag"], v["challenge_menu_kind"], v["challenge_menu_slot"], v["challenge_menu_caption"]) \
        == (18, 2, -1, 1921)
    assert (v["ball_launch_flag"], v["ball_launch_wait_flag"]) == (12, 13)
    assert [v["challenge_balls_at_%d_reg" % k] for k in range(4)] == [19, 19, 19, 20]


def test_the_spike3_card_offers_a_challenge_of_the_modes_own():
    key = "star_wars_elg-1.10/spike3"
    assert MP.CHALLENGE_MENU_PROVEN[key] == 2                   # STANDARD and DJ MIXER on a fresh card
    pr = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert pr.can("challenge"), dict(pr.cannot).get("challenge")
    assert pr.challenge_menu == 5                               # room for 7, the game's own take 2
    spec = MP.ModeSpec(name="PAD CHALLENGE", title=pr.key, starts_on="challenge", challenge=MP.CHALLENGE_NEW,
                       start_shot="Death star target", scoring_shots=["Death star target"])
    assert not [e for e in MP.validate(spec) if "challenge" in e.lower()]


def test_the_sites_are_the_programs_own_words():
    path = os.path.join(PROGS, "star_wars_elg.game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no star_wars_elg.game")
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    prog = S3R.Program(open(path, "rb").read())
    port = MP.read_port(str(ELG3))

    def words(va, n):
        return struct.unpack_from("<%dI" % n, prog.raw, prog.off(va))

    for name in SITES:
        va, w0, w1 = port["site"][name][:3]
        assert words(va, 2) == (w0, w1), name
    # what each one is: the end of the ball ORs 0x202 into the status bits (mov w3, #0x202); the extra-ball test
    # decrements its count byte and returns (sub w1, w1, #1; strb; ret); the compares are `cmp w21|w20, w19`
    assert 0x52804043 in words(SITES["challenge_end_ball"], 8)
    assert words(SITES["challenge_extra_ball"], 8)[5:] == (0x51000421, 0x391CA041, 0xD65F03C0)
    assert words(SITES["challenge_balls_at_0"], 1) == (0x6B1302BF,) == words(SITES["challenge_balls_at_1"], 1)
    assert words(SITES["challenge_balls_at_2"], 1) == (0x6B13029F,)
    # the launch handler fires the plunger device with 8 (mov w2, #8) after reading flag 13 (mov w0, #0xd)
    launch = words(SITES["ball_launch"], 40)
    assert 0x528001A0 in launch and 0x52800102 in launch
