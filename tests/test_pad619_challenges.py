"""PAD-619: PAD-615's challenge feature on every build of Bond's generation of start menus - a mode in one of the game's
challenges' place where the game names them (Rush, Sword of Rage by their flags alone), and challenges of the modes'
own on the start menu (CHOOSE YOUR MODE OF PLAY) of every such build, including those whose menu offers only Stern
Insider Connected's challenge (MODE_SDK.md "A mode in the game's Challenge list"; docs/plans/pad619_challenges.md).

What is worth failing on:
  * THE FINDER READS EACH BUILD: the flag bitmap, the start menu (its place, entry size, count, room, the kind ours
    become), named challenges from the menu's kinds, the balls-per-game getter - and the shipped ports carry them.
  * THE BALL'S START DECIDES, FROM THE FLAGS ALONE: a challenge game, which pick, whose.
  * ONLY WHERE PROVEN: the tab offers a challenge start on a build only when the emulator has seen it work.
  * A DERIVED PORT NEVER CARRIES A LINE TWICE.
"""
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portchallenge as PC

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
PORTS = SDK / "ports"


def _port(key):
    return MP.read_port(str(PORTS / ("%s.port" % key)))


MENU_PORTS = sorted(p.stem for p in PORTS.glob("*.port")
                    if re.search(r"^site\s+challenge_menu\s", p.read_text(encoding="utf-8"), re.M))


# ---- names ----------------------------------------------------------------------------------------
def test_a_menu_challenge_is_named_from_its_flag():
    assert PC.pretty(PC._short("CYGNUS_CHALLENGE_BOOK_1")) == "Cygnus Book 1"
    assert PC.pretty(PC._short("2112_CHALLENGE")) == "2112"
    assert PC.pretty(PC._short("RETRO_CHALLENGE")) == "Retro"
    assert PC.pretty(PC._short("RANSOM_CHALLENGE")) == "Ransom"


# ---- the shipped ports ----------------------------------------------------------------------------
def test_every_menu_port_names_the_whole_menu():
    assert len(MENU_PORTS) >= 35, MENU_PORTS
    for key in MENU_PORTS:
        port = _port(key)
        v = port["value"]
        assert {"challenge_menu", "challenge_menu_pick"} <= set(port["site"]), key
        assert port["data"].get("game_flags") and port["data"].get("game_flag_count"), key
        cap, count_at, list_at = (int(v["challenge_menu_%s" % n]) for n in ("cap", "count_at", "list_at"))
        assert 5 <= cap <= 9 and 0 < count_at < 1024 and 0 < list_at < 1024, key
        assert int(v.get("challenge_menu_entry", 12)) in (12, 16), key
        assert 1890 < int(v["challenge_menu_caption"]) < 1930, key           # CHALLENGE: 1921, 1911, 1901 by era
        assert int(v.get("challenge_menu_slot", 0)) in (-1, 0), key
        if key.startswith("james_bond_"):
            continue                                                          # PAD-615's own menu lines
        assert "challenge_balls" in port["site"], key                       # a mode's challenge game is one ball
        assert any(e[0] == "ball_start" for e in port["event"]), key        # where the plain one is handed over


def test_named_challenges_by_their_flag_alone_where_the_game_has_no_handler_of_bonds_shape():
    for key, names in (("rush_pro-1.19", ("Cygnus Book 1", "Cygnus Book 2", "2112")),
                       ("rush_le-1.19", ("Cygnus Book 1", "Cygnus Book 2", "2112")),
                       ("rush_le-1.18", ("Cygnus Book 1", "Cygnus Book 2", "2112")),
                       ("sword_of_rage_pro-1.19", ("Retro", "Ransom")),
                       ("sword_of_rage_le-1.19", ("Retro", "Ransom")),
                       ("sword_of_rage_le-1.18", ("Retro", "Ransom"))):
        port = _port(key)
        assert MP._challenges(port) == names, key
        assert not any(s.startswith("challenge_go_") for s in port["site"]), key
        assert int(port["value"]["challenge_menu_slot"]) == 0, key           # ours stand in for challenge 0
    rush = _port("rush_pro-1.19")["value"]
    assert [int(rush["challenge_flag_%d" % n]) for n in range(3)] == [29, 30, 31]
    assert int(_port("rush_le-1.18")["value"]["challenge_on_flag"]) == 16   # the 1.13-era flag numbering


def test_the_plain_builds_have_no_challenge_to_take_only_room_for_their_own():
    for key in ("deadpool_pro-1.16", "led_zeppelin_le-1.22", "beatles-1.29"):
        port = _port(key)
        assert MP._challenges(port) == () and int(port["value"]["challenge_menu_slot"]) == -1, key


# the game programs, when this machine has them (PAD-619's extracted programs)
ELVES = next((d for d in (os.environ.get("PAD_ELVES", ""), r"C:\tmp\PAD-619\elves", "/mnt/c/tmp/PAD-619/elves")
              if d and os.path.isdir(d)), None)


@pytest.mark.parametrize("key", MENU_PORTS)
def test_the_ports_carry_what_the_finder_reads_off_the_game(key):
    elf = os.path.join(ELVES or "", key + ".elf")
    if not ELVES or not os.path.isfile(elf):
        pytest.skip("the game program is not on this machine")
    lines, notes = PC.find(elf)
    assert lines, notes
    assert [l for l in PC.missing_from(lines, (PORTS / ("%s.port" % key)).read_text(encoding="utf-8"))
            if not l.startswith("#")] == []


def test_a_derived_port_takes_the_finders_lines_once():
    src = (ROOT / "pinball_decryptor" / "plugins" / "stern" / "port_derive.py").read_text(encoding="utf-8")
    assert 'portchallenge.missing_from(challenges, "\\n".join(body))' in src
    body = ["data  game_flags          0x00829200", "value game_flags_at       4"]
    lines = ["data  game_flags          0x00829200", "value game_flags_at       4", "value challenge_on_flag   18"]
    assert PC.missing_from(lines, "\n".join(body)) == ["value challenge_on_flag   18"]


# ---- the runtime --------------------------------------------------------------------------------
def _host():
    from tests import test_spike2_mode_roster as R
    return R


def test_the_balls_start_hands_over_only_a_challenge_game_and_only_its_pick(tmp_path):
    R = _host()
    src = R.RUNTIME.read_text(encoding="utf-8")
    code = "#include <stdio.h>\n" + R._lift(src, "static int challenge_ball_takes(int on, int own, int held, int picked)") + """
int main(void)
{
    int on, own, held, picked;
    for (on = -1; on < 2; on++) for (own = -3; own < 2; own++) for (held = 0; held < 2; held++)
        for (picked = -1; picked < 2; picked++)
            printf("%d,%d,%d,%d:%d\\n", on, own, held, picked, challenge_ball_takes(on, own, held, picked));
    return 0;
}
"""
    out = dict(line.split(":") for line in R._host_run(tmp_path, code).split())
    took = sorted(k for k, v in out.items() if v == "1")
    # a challenge game (1): one of ours picked (any slot but the handler's -2), or none of ours and the held one's flag
    assert all(k.startswith("1,") for k in took)
    assert "1,-2,0,0" not in took and "1,-2,1,1" not in took                 # challenge 0's handler hands it over
    assert {"1,-1,0,0", "1,0,0,0", "1,1,0,0"} <= set(took)                  # ours: the plain one, or in a challenge's place
    assert {k for k in took if k.startswith("1,-3,")} == {"1,-3,1,1"}      # none of ours: held and picked only


def test_the_runtime_takes_flags_at_the_dispatch_and_makes_a_mode_challenge_one_ball():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    disp = src[src.index("static void on_event_dispatch(unsigned *r)"):]
    disp = disp[:disp.index("\n}\n")]
    assert "challenge_ball_start();" in disp and "challenge_ours = 0;" in disp
    arm = src[src.index("static void challenges_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'hook_veto_n(fn("challenge_balls"), challenge_balls_veto, 0, 1)' in arm
    assert 'event_bus_id("ball_start")' in arm
    built = src[src.index("static void challenge_menu_built(unsigned *r)"):]
    built = built[:built.index("\n}\n")]
    assert "if (mine) return;" in built                                     # every frame: appended once
    assert 'pm_port_value("challenge_menu_entry", 12)' in built


# ---- the profile and the tab --------------------------------------------------------------------
def test_only_proven_builds_offer_it_and_the_room_is_the_menus():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        k = "%s-%s" % (p.game_dir, p.version)
        if k in MP.CHALLENGE_PROVEN or k in MP.CHALLENGE_MENU_PROVEN:
            assert p.can("challenge"), key
        else:
            assert not p.can("challenge") and p.label in p.why_not("challenge"), key
        if k in MP.CHALLENGE_MENU_PROVEN:
            cap = int(MP.read_port(str(PORTS / ("%s.port" % k)))["value"]["challenge_menu_cap"])
            assert p.challenge_menu == cap - MP.CHALLENGE_MENU_PROVEN[k] > 0, key
        if k not in MP.CHALLENGE_PROVEN:
            assert p.challenges == (), key


def test_the_tab_lets_a_build_with_only_its_own_choose_it():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert "const challengeOff = off || dis.challenge || (!challenges.length && !challengeNew);" in js
    assert "On James Bond" not in js.split("challenge:", 1)[1].split("\n", 1)[0]


def test_a_challenge_pick_waits_for_the_games_mode_running_as_the_ball_starts():
    # Avengers LE/Pro 1.10 run one of their modes at every ball's start: the pick waits for it to end (the ball's end
    # lapses it) instead of giving up at once, and the refusal names what was in the way
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    tick = src[src.index("static void challenge_tick(void)"):]
    tick = tick[:tick.index("\n}\n")]
    wait = tick.index("pm_stock_mode_running(PM_STOCK_ANY)")
    assert wait < tick.index("challenge_wait = 0;\n    challenge_said_wait = 0;") < tick.index('mode_start(M, "challenge pick")')
    assert "the challenge pick waits - %s is running" in tick
    end = src[src.index("static void challenge_ball_end(void)"):]
    assert "challenge_said_wait = 0;" in end[:end.index("\n}\n")]
    assert "%s not started (%s): %s is running - its trigger count is kept" in src
