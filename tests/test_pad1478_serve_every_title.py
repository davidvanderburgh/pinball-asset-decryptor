"""PAD-1478: ball 1 waits for the character pick on every co-op title, not only Godzilla 1.16.

Only the Godzilla ports had `site serve_ball` (the ball start's call of the framework's serve, found by hand in
PAD-1114 round 2), so on every other title ball 1 came to the shooter lane before the pick. portcoop.serve_ball reads
it off each build's own program, after the first-ball call (the same ball start on all 53 shipped programs), and the
runtime forms a flipper-held Start's co-op game of one at the serve, before the pick hold decides (it formed on the
tick, after the serve)."""
import glob
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import portcoop, portgen
from pinball_decryptor.plugins.stern.portchallenge import Elf
from tests import test_pad1017_coop_lines as L
from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORTS = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"
RUNTIME = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"

MOV_R0_3, MOV_R0_26, MOV_R1_0, NOP = 0xE3A00003, 0xE3A00026, 0xE3A01000, 0xE1A00000


def _bl(at, to):
    return 0xEB000000 | (((to - at - 8) >> 2) & 0xFFFFFF)


def _ball_start(serve_prefix=MOV_R0_3, serves=1):
    """The ball start from its first-ball call: filler, `mov r0, #3 ; bl <serve> ; mov r0, #0x26 ; mov r1, #0`, then
    the shoot-again branch's tail (`b`, `bl`, the same event)."""
    w = [_bl(L.BASE, L.BASE + 0x8000)] + [NOP] * 53
    for _ in range(serves):
        w += [serve_prefix, _bl(L.BASE + 4 * (len(w) + 1), L.BASE + 0x9000), MOV_R0_26, MOV_R1_0]
    w += [0xEA000010, _bl(L.BASE + 4 * (len(w) + 1), L.BASE + 0xA000), MOV_R0_26, MOV_R1_0] + [NOP] * 8
    return Elf(L._elf(w))


def test_the_serve_is_the_call_after_mov_r0_3():
    e = _ball_start()
    assert portcoop.serve_ball(e, L.BASE) == L.BASE + 4 * 55          # not the shoot-again tail's `bl`


def test_no_serve_without_its_shape_or_with_two():
    assert portcoop.serve_ball(_ball_start(serve_prefix=NOP), L.BASE) is None
    assert portcoop.serve_ball(_ball_start(serves=2), L.BASE) is None


def test_the_line_is_generated_per_build():
    # read off each build's own program, as coop_first_ball is: never carried from a reference, not in a recipe's hash
    assert portgen.generated("site", "serve_ball 0x002a77ec 0xeb038646 0xe3a00026")
    assert portgen.generated("site", "coop_first_ball 0x002a7714 0xebfe6e2b 0xe1a04000")


def _entries(port):
    out = {}
    for line in port.read_text(encoding="utf-8").splitlines():
        p = line.split("#")[0].split()
        if len(p) >= 3 and p[0] == "site":
            out[p[1]] = [int(x, 16) for x in p[2:5]]
    return out


def test_every_coop_port_has_its_serve():
    seen = 0
    for port in sorted(PORTS.glob("*.port")):
        e = _entries(port)
        if "coop_first_ball" not in e:
            continue
        at, w0, w1 = e["serve_ball"]
        assert w0 >> 24 == 0xEB and w1 == MOV_R0_26, port.name        # bl <serve> ; mov r0, #0x26
        assert 54 <= (at - e["coop_first_ball"][0]) // 4 <= 63, port.name
        seen += 1
    assert seen == 64                                                 # the 51 of PAD-1478 + Godzilla LE/Pro 1.16, Pro 1.15; PAD-1555: + 10


def test_the_serve_forms_a_held_start_game_before_the_pick_hold():
    src = RUNTIME.read_text(encoding="utf-8")
    wrap = R._lift(src, "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert wrap.index("ci_ball_hold(") < wrap.index("coop_solo_check();") < wrap.index("coop_pick_hold();") \
        < wrap.index("ci_serve_game(")
    assert src.index("static void coop_solo_check(void)") < src.index("static unsigned ci_serve_wrap(")


ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1478/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_finder_reads_every_shipped_program():
    found = {}
    for p in ELFS:
        got = [line for line in portcoop.lines(p)[0] if line.split()[1] == "serve_ball"]
        found[os.path.basename(p)] = got[0].split()[2] if got else None
    assert found.get("godzilla_le-1.16.0.elf", "0x002a77ec") == "0x002a77ec"   # PAD-1114 round 2's, found by hand
    assert found.get("godzilla_pro-1.16.0.elf", "0x00459f44") == "0x00459f44"
    assert [k for k, v in found.items() if v is None] == []
    for p in ELFS:                                                    # and the port says the same
        port = PORTS / (re.sub(r"\.0\.elf$", "", os.path.basename(p)) + ".port")
        if port.exists():
            assert "0x%08x" % _entries(port)["serve_ball"][0] == found[os.path.basename(p)], port.name


# ---- the BALL line's words fitted to the older titles' fixed buffer (ball_line_len / ball_line_fit, verbatim) ----
FIT_MAIN = r"""
#include <stdio.h>
#include <string.h>
@FNS@
int main(void)
{
    static const char *cases[] = {
        "PLAYER 2  BALL %d",              /* the turn line: 16 shown, fits */
        "TEAM 1 P2  BALL %d",             /* 17: its double space goes */
        "PLAYER 1 PICK  20",              /* 17: the same */
        "PLAYER 1 PICK  20: ALPHA",       /* 24: no double space left to drop - the end goes */
        "TEAM 12345 PLAYER 4  BALL %d",   /* the BALL n stays whole, the words before it are cut */
        "ABCDEFGHIJKLMNOP%d",             /* 17: cut before its %%d, never between a %% and its d */
        0 };
    char w[96];
    int i;
    for (i = 0; cases[i]; i++) {
        snprintf(w, sizeof w, "%s", cases[i]);
        ball_line_fit(w, sizeof w, 16);
        printf("%u|%s\n", ball_line_len(w), w);
    }
    snprintf(w, sizeof w, "%s", cases[3]);
    ball_line_fit(w, sizeof w, 0);                      /* 0: no limit (Godzilla) */
    printf("%u|%s\n", ball_line_len(w), w);
    return 0;
}
"""


def test_the_ball_line_is_fitted_to_16(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = (R._lift(src, "static unsigned ball_line_len(const char *w)") + "\n"
           + R._lift(src, "static void ball_line_fit(char *w, unsigned size, unsigned cap)"))
    out = R._host_run(tmp_path, FIT_MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["16|PLAYER 2  BALL %d", "16|TEAM 1 P2 BALL %d", "16|PLAYER 1 PICK 20", "16|PLAYER 1 PICK 20",
                   "16|TEAM 1234 BALL %d", "16|ABCDEFGHIJKLMNOP", "24|PLAYER 1 PICK  20: ALPHA"]


def test_every_word_on_the_ball_line_is_fitted():
    src = RUNTIME.read_text(encoding="utf-8")
    # no borrow of the BALL line but the fitted one
    assert re.findall(r"message_borrow\([^;]*coop_ball_msg", src) == ["message_borrow(id, (unsigned)coop_ball_msg"]
    assert 'pm_port_value("coop_ball_msg_max", 16)' in src
    say = R._lift(src, "static void coop_pick_say(void)")
    assert '"%s%.*s%s", head, (int)room, name, secs' in say      # P1 ALPHA 20 on a short line
    for name in ("godzilla_le-1.16", "godzilla_pro-1.16", "godzilla_pro-1.15"):   # no limit where it was proven
        assert re.search(r"^value coop_ball_msg_max +0\b", (PORTS / (name + ".port")).read_text(encoding="utf-8"), re.M)


def test_the_start_menu_titles_name_their_serve_music():
    want = {"jaws_le-1.02": 66, "jaws_pro-1.02": 66, "john_wick_le-1.02": 77,
            "john_wick_pro-1.02": 77, "king_kong_le-0.97": 124, "king_kong_pro-0.97": 124,
            "metallica_spike-1.04": 65, "uncanny_xmen_le-0.98": 191, "uncanny_xmen_pro-0.98": 191,
            "godzilla_le-1.16": 66, "godzilla_pro-1.16": 66, "godzilla_pro-1.15": 66,
            # PAD-1555: the November 2026 start-menu builds, the same music as each one's earlier build
            "king_kong_le-1.00": 124, "king_kong_le-1.01": 124, "king_kong_pro-1.01": 124, "metallica_spike-1.05": 65}
    for port in PORTS.glob("*.port"):
        text = port.read_text(encoding="utf-8")
        if "comp_menu_end_msg" in text:                                # every start-menu title has its serve music
            got = re.findall(r"^value serve_music +(\d+)", text, re.M)
            assert got == [str(want[port.stem])], port.name
        else:                                                         # no chooser: nothing would ask it (Bond 60th)
            assert "serve_music" not in text, port.name


def test_the_serve_music_plays_on_through_the_games_repeat():
    """Uncanny X-Men 0.98 asks for its serve music (191) again at the serve, and the track started over 6.6 s in
    (emulator sound log). Clearing its steal flag did not help (its record was still looked up again), so from our early
    request until 3 s past the serve, the game's repeat while ours plays is not passed on: the worker gets request 0."""
    src = RUNTIME.read_text(encoding="utf-8")
    worker = R._lift(src, "static int srv_worker(unsigned request)\n{")
    assert "if (!srv.seen++) return 0;" in worker                     # our own request goes as it is
    assert worker.index("pm_sound_active(request)") < worker.index("return 1;")
    assert "if (srv_worker(WORKER_REQ(r))) r[0] = 0;" in R._lift(src, "static void on_sound_worker(pm_reg *r)")
    wrap = R._lift(src, "static unsigned ci_serve_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert wrap.index("ci_serve_game(") < wrap.index("srv.until = (pm_ms() + SRV_AFTER_MS) | 1;")
    assert "srv_tick();" in src
    assert re.search(r"pm_port_value\(\"serve_music\", 0\) && fn\(\"sound_worker\"\) && !worker_hooked\)", src)
