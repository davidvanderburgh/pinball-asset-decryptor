"""PAD-1369: a mode's own challenge on the start menu of the six other Spike 3 titles (PAD-1330 did Star Wars ELG).

Walking Dead Remastered LE has ELG's menu (kind 3 sets FG_PLAYER_CHALLENGE_MODE_ACTIVE alone). Fallout LE, Pokemon LE,
Star Wars 2025 LE / Pro and Transformers LE list game-mode indices: one MODE CHALLENGE entry, Standard's index again,
lettered CHALLENGE and the mode's name (Godzilla's PAD-686 entry, at 64-bit, on a site hooked after the press moved the
cursor). Every port names ELG's challenge-game sites (the balls reads, the extra-ball test, the end of the ball, the
launch handler), paired across and read off each program.

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder holding <title>.game. The lifted C runs
on the host compiler (WSL or Linux).
"""
import os
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports", "spike3")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
CC = shutil.which("gcc") or shutil.which("cc")
needs_cc = pytest.mark.skipif(not CC or os.name == "nt", reason="needs a C compiler (WSL or Linux)")

# title: (port, challenge flag, the end of the ball, the launch handler, the first balls compare)
TITLES = {
    "walking_dead_remastered_le": ("walking_dead_remastered_le-0.92", 18, 0x36E4F0, 0x369010, 0x360BD8),
    "fallout_le": ("fallout_le-0.82", 18, 0x935490, 0x92FFB0, 0x8CFB38),
    "pokemon_le": ("pokemon_le-0.82", 17, 0x6D48C0, 0x6CEF90, 0x7A2688),
    "star_wars_2025_le": ("star_wars_2025_le-0.96", 17, 0x378A30, 0x373550, 0x503A28),
    "star_wars_2025_pro": ("star_wars_2025_pro-0.84", 17, 0x33EA50, 0x339570, 0x3C6BC8),
    "transformers_mtmte_le": ("transformers_mtmte_le-0.96", 18, 0x459C80, 0x4543A0, 0x4CEFC8),
}
INDEX = {   # title: (Standard's caption, its name, CHALLENGE)
    "fallout_le": (1915, 1916, 1922),
    "pokemon_le": (1911, 1912, 1915),
    "star_wars_2025_le": (1911, 1912, 1915),
    "star_wars_2025_pro": (1907, 1908, 1911),
    "transformers_mtmte_le": (1915, 1916, 1922),
}
GAME_SITES = ["challenge_balls", "challenge_balls_2"] + ["challenge_balls_at_%d" % k for k in range(4)] + \
    ["challenge_extra_ball", "challenge_end_ball", "ball_launch"]


def _port(title):
    return MP.read_port(os.path.join(PORTS, TITLES[title][0] + ".port"))


@pytest.mark.parametrize("title", sorted(TITLES))
def test_each_port_names_the_challenge_game(title):
    port = _port(title)
    _, flag, end, launch, at0 = TITLES[title]
    for name in GAME_SITES:
        assert name in port["site"], name
    assert port["site"]["challenge_end_ball"][0] == end
    assert port["site"]["ball_launch"][0] == launch
    assert port["site"]["challenge_balls_at_0"][0] == at0
    v = port["value"]
    assert v["challenge_on_flag"] == flag
    assert [v["challenge_balls_at_%d_reg" % k] for k in range(4)] == [19, 19, 19, 20]
    assert (v["ball_launch_flag"], v["ball_launch_wait_flag"], v["challenge_menu_slot"]) == (12, 13, -1)


def test_walking_dead_has_elgs_menu_with_its_own_kind():
    v = _port("walking_dead_remastered_le")["value"]
    assert (v["challenge_menu_kind"], v["challenge_menu_caption"]) == (3, 1920)    # kind 3: flag 18 alone; CHALLENGE
    assert {"challenge_menu", "challenge_menu_pick"} <= set(_port("walking_dead_remastered_le")["site"])


@pytest.mark.parametrize("title", sorted(INDEX))
def test_the_index_menus_get_one_mode_challenge_entry(title):
    port = _port(title)
    v = port["value"]
    assert port["site"]["challenge_menu_frame"] == port["site"]["comp_menu_frame"]   # Prolonged Competition's point
    for k in ("moved", "list_at", "list_reg", "count_at", "count_reg", "last_at", "cap", "cursor_reg"):
        assert v.get("challenge_menu_frame_" + k) == v.get("comp_menu_frame_" + k), k
    cap, name, chal = INDEX[title]
    assert v["challenge_menu_frame_entry"] == v["comp_menu_end_index"] == 1               # STANDARD
    assert (v["challenge_menu_frame_caption_msg"], v["challenge_menu_frame_name_msg"], v["challenge_menu_caption"]) \
        == (cap, name, chal)
    assert v["challenge_menu_sets_on"] == 1
    assert "challenge_menu" not in port["site"]
    assert MP._plain_index_menu(port)


@pytest.mark.parametrize("title", sorted(TITLES))
def test_the_app_offers_a_challenge_of_the_modes_own(title):
    port_name = TITLES[title][0]
    prof = MP.profiles()[port_name.replace("-", "_").replace(".", "_") + "_spike3"]
    assert prof.can("challenge"), dict(prof.cannot).get("challenge")
    key = port_name + "/spike3"
    if title in INDEX:
        assert key in MP.CHALLENGE_MENU_FRAME_PROVEN and "PENDING" not in MP.CHALLENGE_MENU_FRAME_PROVEN[key]
        assert prof.challenge_menu == MP.CHALLENGE_FRAME_ROOM
    else:
        assert MP.CHALLENGE_MENU_PROVEN[key] == 2                 # STANDARD and DJ MIXER on a fresh card
        assert prof.challenge_menu == 6                           # room for 8
    spec = MP.ModeSpec(name="PAD CHALLENGE", title=prof.key, starts_on="challenge", challenge=MP.CHALLENGE_NEW)
    assert not [e for e in MP.validate(spec) if "challenge" in e.lower()]


def test_a_menu_of_no_challenge_frame_is_not_a_plain_index_menu():
    port = _port("fallout_le")
    v = dict(port["value"])
    v.pop("challenge_menu_sets_on")
    assert not MP._plain_index_menu({"site": port["site"], "value": v, "data": port["data"]})
    assert not MP._plain_index_menu(MP.read_port(os.path.join(PORTS, "star_wars_elg-1.10.port")))


@pytest.mark.parametrize("title", sorted(TITLES))
def test_the_sites_are_the_programs_own_words(title):
    path = os.path.join(PROGS, title + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % title)
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    prog = S3R.Program(open(path, "rb").read())
    port = _port(title)

    def words(va, n):
        return struct.unpack_from("<%dI" % n, prog.raw, prog.off(va))

    for name, (va, w0, w1) in ((n, port["site"][n][:3]) for n in GAME_SITES + ["challenge_menu_frame"]
                               if n in port["site"]):
        assert words(va, 2) == (w0, w1), name
    s = port["site"]
    # the end of the ball ORs 0x202 into the status bits (mov wN, #0x202); the extra-ball test decrements its count byte
    # and returns; the compares are `cmp w21|w20, w19`; the launch handler reads flag 13 and fires with 8
    assert any(w & 0xFFFFFFE0 == 0x52804040 for w in words(s["challenge_end_ball"][0], 4))
    tail = words(s["challenge_extra_ball"][0], 8)[5:]
    assert tail[0] == 0x51000421 and tail[1] & 0xFFC003FF == 0x39000041 and tail[2] == 0xD65F03C0
    assert words(s["challenge_balls_at_0"][0], 1) == (0x6B1302BF,) == words(s["challenge_balls_at_1"][0], 1)
    launch = words(s["ball_launch"][0], 40)
    assert 0x528001A0 in launch and 0x52800102 in launch


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


@needs_cc
def test_a_moved_frame_steps_through_the_modes_then_moves_on(tmp_path):
    src = open(RUNTIME, encoding="utf-8").read()
    code = "#include <stdio.h>\n" + "\n".join(_lift(src, sig) for sig in (
        "static int challenge_frame_step(", "static int challenge_frame_arrive(",
        "static void challenge_frame_press(", "static unsigned challenge_frame_moved(")) + r"""
/* the game's own press on a menu of `count` entries, both ways wrapping (the Spike 3 menus' csinc) */
static unsigned game_moves(unsigned c, unsigned count, int right) { return right ? (c + 1) % count : (c + count - 1) % count; }
int main(void)
{
    unsigned count = 4, at = 3, c = 2, was;   /* STANDARD, COMPETITION, DJ MIXER, then ours; 3 modes of ours */
    int sub = 0, on = 0, k;
    for (k = 0; k < 5; k++) {                 /* five right presses from DJ MIXER */
        was = c; c = challenge_frame_moved(was, game_moves(c, count, 1), count, at, on, 3, &sub);
        on = c == at;
        printf("R %u %d\n", c, sub);
    }
    for (k = 0; k < 4; k++) {                 /* four left presses from STANDARD: onto ours (the last mode) */
        was = c; c = challenge_frame_moved(was, game_moves(c, count, 0), count, at, on, 3, &sub);
        on = c == at;
        printf("L %u %d\n", c, sub);
    }
    c = challenge_frame_moved(3, 3, count, at, 1, 3, &sub);     /* no press: nothing moves */
    printf("N %u %d\n", c, sub);
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([CC, "-std=gnu17", "-Wall", "-Werror", "-Wno-unused-function", "-o", str(tmp_path / "t"),
                        str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout.split("\n")
    assert out[:10] == [
        "R 3 0",        # onto ours: its first mode
        "R 3 1",        # the game wrapped the cursor to STANDARD: put back, the next mode
        "R 3 2",
        "R 0 2",        # past the last mode the cursor moves on, as the game's own press did
        "R 1 2",
        "L 0 2",
        "L 3 2",        # onto ours from after it (the wrap): its last mode
        "L 3 1",        # the game moved the cursor to DJ MIXER: put back, the previous mode
        "L 3 0",
        "N 3 0",
    ], out
