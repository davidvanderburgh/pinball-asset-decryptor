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
        cap, count_at, list_at = (int(v.get("challenge_menu_%s" % n, 1)) for n in ("cap", "count_at", "list_at"))
        assert "challenge_menu_count_at" in v or 4 <= int(v.get("challenge_menu_count_reg", -1)) <= 11, key
        low = 3 if int(v.get("challenge_menu_sets_on", 0)) else 5          # Star Wars sized its list for its own
        high = 14 if int(v.get("challenge_menu_entry", 12)) == 24 or int(v.get("challenge_menu_sets_on", 0)) else 9   # TMNT, Foo Fighters
        assert low <= cap <= high and 0 < count_at < 1024 and 0 < list_at < 1024, key
        assert int(v.get("challenge_menu_entry", 12)) in (12, 16, 20, 24), key
        assert 1890 < int(v["challenge_menu_caption"]) < 1930, key           # CHALLENGE: 1921, 1911, 1901 by era
        assert int(v.get("challenge_menu_slot", 0)) in (-1, 0), key
        if key.startswith("james_bond_"):
            continue                                                          # PAD-615's own menu lines
        assert "challenge_balls" in port["site"], key                       # a mode's challenge game is one ball
        assert any(e[0] == "ball_start" for e in port["event"]), key        # where the plain one is handed over


def test_tmnt_pro_1_58_has_its_own_event_ids():
    """Its drafted port named no events; the rig saw 1.59's ids less 4 fire (its dispatch is bounded 16 lower)."""
    port = _port("turtles_pro-1.58")
    assert port["site"]["hook_dispatch"][0] == 0x183e08
    text = (PORTS / "turtles_pro-1.58.port").read_text(encoding="utf-8")
    ev = {l.split()[1]: int(l.split()[2], 0) for l in text.splitlines() if l.startswith("event ")}
    assert ev == {"game_start": 0x49, "ball_start": 0x21, "ball_end": 0x30, "bonus_start": 0x23, "bonus_end": 0x24}
    assert {e[0] for e in port["event"]} == set(ev)


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
    # ... but only for CHALLENGE_GRACE_MS: Godzilla's own "any mode running" says yes through a whole challenge game
    assert "pm_ms() - challenge_wait_ms < CHALLENGE_GRACE_MS" in tick and "challenge_force = 1;" in tick
    assert "!challenge_force &&" in src[src.index("static void mode_start(struct slot *M, const char *why)"):][:1200]
    end = src[src.index("static void challenge_ball_end(void)"):]
    assert "challenge_said_wait = 0;" in end[:end.index("\n}\n")]
    assert "%s not started (%s): %s is running - its trigger count is kept" in src


# ---- the GamePlayModes builds: a challenge is the game-play mode's index ---------------------------
GPM_PORTS = ("jaws_le-1.02", "jaws_pro-1.02", "john_wick_le-1.01", "john_wick_le-1.02", "john_wick_pro-1.02",
             "metallica_spike-1.03", "metallica_spike-1.04", "venom_le-1.07", "venom_pro-1.07")


@pytest.mark.parametrize("key", GPM_PORTS + ("godzilla_le-1.16", "godzilla_pro-1.15", "godzilla_pro-1.16"))
def test_the_game_mode_table_ports_carry_what_the_finder_reads(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)


def test_jaws_names_its_four_challenges_by_their_index_and_standard_plays_instead():
    port = _port("jaws_pro-1.02")
    v = port["value"]
    assert port["data"]["game_play_modes"] and int(v["game_play_mode_at"]) == 8 and int(v["challenge_mode_plain"]) == 1
    assert [int(v["challenge_mode_%d" % n]) for n in range(4)] == [8, 9, 11, 12]     # 10 is a video-mode test
    assert MP._challenges(port) == ("4th of July", "Shark Hunter", "Jaws the Revenge", "The Shark Is Broken")
    assert MP._challenges(_port("john_wick_pro-1.02")) == (
        "Red Circle Reckoning", "The Staircase", "The Duel", "Special Assignment", "Tick Tock Mr. Wick")


def test_venom_names_its_knull_challenges_from_the_adapters_own_tables():
    port = _port("venom_pro-1.07")
    v = port["value"]
    assert int(v["game_play_mode_at"]) == 4 and int(v["challenge_mode_plain"]) == 0
    assert [int(v["challenge_mode_%d" % n]) for n in range(3)] == [11, 12, 13]
    assert MP._challenges(port) == ("Challenge Mode Low", "Challenge Mode Medium", "Challenge Mode High")


def test_the_game_modes_with_no_challenge_say_so():
    for key in ("king_kong_pro-0.97", "uncanny_xmen_le-0.98", "dungeons_and_dragons_pro-1.10"):
        p = MP.profile_from_port(str(PORTS / ("%s.port" % key)))
        assert not p.can("challenge") and "has no list of challenges" in p.why_not("challenge"), key


def test_the_runtime_takes_a_pick_by_its_flag_or_its_game_play_mode():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    picked = src[src.index("static int challenge_picked(unsigned n)"):]
    picked = picked[:picked.index("\n}\n")]
    assert 'pm_port_value("game_play_mode_at", 8)' in picked and '"challenge_mode_%u"' in picked
    unpick = src[src.index("static void challenge_unpick(unsigned n)"):]
    unpick = unpick[:unpick.index("\n}\n")]
    assert "game_flag_clear(" in unpick and 'pm_port_value("challenge_mode_plain", 1)' in unpick
    start = src[src.index("static void challenge_ball_start(void)"):]
    start = start[:start.index("\n}\n")]
    assert "picked = (int)n == again ? 1 : challenge_picked(n);" in start and "challenge_unpick(n);" in start


# ---- Star Wars' compare-chain start menu: no challenge kind, ours play as Standard ----------------------
@pytest.mark.parametrize("key", ("star_wars_le-1.30", "star_wars_le-1.31", "star_wars_pro-1.31"))
def test_star_wars_menu_takes_ours_as_standard_through_the_entry(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)
    v = _port(key)["value"]
    assert int(v["challenge_menu_kind"]) == 0 and int(v["challenge_menu_slot"]) == -1
    assert int(v["challenge_menu_sets_on"]) == 1 and int(v["challenge_menu_pick_back"]) in (224, 240)
    assert int(v["challenge_menu_entry"]) == 16 and int(v["challenge_menu_list_at"]) == 400


def test_the_runtime_reads_a_compare_chain_pick_through_its_entry_and_knows_ours_by_name():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    own = src[src.index("static int own_entry_at("):]
    own = own[:own.index("\n}\n")]
    assert "name == (unsigned)(unsigned long)own_challenge[k].name" in src
    pick = src[src.index("static void challenge_menu_picked(unsigned *r)"):]
    pick = pick[:pick.index("\n}\n")]
    assert 'pm_port_value("challenge_menu_pick_back", 0)' in pick and "ent[0] = (unsigned)pm_port_value(" in pick
    start = src[src.index("static void challenge_ball_start(void)"):]
    assert 'pm_port_value("challenge_menu_sets_on", 0)) on = 1;' in start[:start.index("\n}\n")]


def test_elvira_keeps_its_menu_count_in_a_register_and_the_frame_hook_saves_every_one():
    test_the_ports_carry_what_the_finder_reads_off_the_game("elvira3-1.13")
    v = _port("elvira3-1.13")["value"]
    assert int(v["challenge_menu_count_reg"]) == 5 and "challenge_menu_count_at" not in v
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    full = src[src.index("static int hook_full(unsigned addr, hook_fn logger)"):]
    full = full[:full.index("\n}\n")]
    assert "0xe92d5fffu" in full and "0xe8bd5fffu" in full                  # push / pop {r0-r12, lr}
    built = src[src.index("static void challenge_menu_built(unsigned *r)"):]
    built = built[:built.index("\n}\n")]
    assert "r + (creg >= 0 ? 14 : 6)" in built and "&r[creg]" in built


def test_a_mode_picked_as_the_challenge_does_not_give_way_to_the_games_modes():
    # Avengers 1.10 / Led Zeppelin: the pick started past the game's ball-start mode, which then ended ours at once
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "run.by_challenge = why[0] == 'c' && why[1] == 'h'" in src
    assert "cfg.game_modes != GM_STACK && !run.by_challenge && !run.by_place && pm_aside()" in src


OLDER = ("aerosmith_le-1.15", "avengers_infinity_le-1.09", "batman-1.13", "guardians_le-1.14", "iron_maiden_le-1.16",
         "rush_le-1.18", "stranger_things_le-1.12", "sword_of_rage_le-1.18")


@pytest.mark.parametrize("key", OLDER)
def test_the_older_builds_name_their_per_player_balls_getter_too(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)
    assert "challenge_balls_2" in _port(key)["site"]


def test_the_runtime_vetoes_the_second_getter_and_portgen_keeps_the_pad630_line():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert 'hook_veto_n(fn("challenge_balls_2"), challenge_balls_veto, 1, 1)' in src
    from pinball_decryptor.plugins.stern import portgen as G
    assert G._GENERATED.match("site challenge_end_ball 0x1") and G._GENERATED.match("site challenge_balls_2 0x1")


@pytest.mark.parametrize("key", ("turtles_le-1.59", "turtles_pro-1.58", "turtles_pro-1.59"))
def test_tmnt_menu_has_its_fields_moved_and_the_runtime_follows_them(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)
    v = _port(key)["value"]
    assert int(v["challenge_menu_entry"]) == 24 and int(v["challenge_menu_kind_at"]) == 4
    assert int(v["challenge_menu_name_at"]) == 12 and int(v["challenge_menu_caption_at"]) == 8
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    built = src[src.index("static void challenge_menu_built(unsigned *r)"):]
    built = built[:built.index("\n}\n")]
    assert "list[es * i + k2] = list[es * tmpl + k2]" in built              # ours start as a copy of the game's entry
    assert "*(unsigned *)(list + es * i + nat) = (unsigned)(unsigned long)own_challenge[k].name" in built


@pytest.mark.parametrize("key", ("foo_fighters_le-1.04", "foo_fighters_pro-1.04"))
def test_foo_fighters_live_menu_takes_ours_as_standard_through_the_entry(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)
    v = _port(key)["value"]
    assert int(v["challenge_menu_kind"]) == 0 and int(v["challenge_menu_sets_on"]) == 1
    assert int(v["challenge_menu_pick_back"]) == 176 and int(v["challenge_menu_list_at"]) == 576


def test_bond_60th_says_its_challenge_is_a_timed_whole_game():
    p = MP.profile_from_port(str(PORTS / "james_bond_60th_le-1.11.port"))
    assert not p.can("challenge") and "a whole game played against the clock" in p.why_not("challenge")


@pytest.mark.parametrize("key", ("mando_le-1.45", "mando_pro-1.45", "jurassic_park_le-1.16", "jurassic_park_pro-1.16"))
def test_mando_live_menu_has_20_byte_entries(key):
    test_the_ports_carry_what_the_finder_reads_off_the_game(key)
    v = _port(key)["value"]
    assert int(v["challenge_menu_entry"]) == 20 and int(v["challenge_menu_sets_on"]) == 1
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    assert "es != 20" in src


def test_mando_le_1_44_menu_keeps_its_buttons_and_cursor_in_registers():
    """Its buttons are read at the loop's foot (mov r8, r0 ; tst r8, #0x80 later), the cursor is r6 (lsl r5, r6, #2 ;
    add r3, r5, r6), the pick reads a byte (ldrb sb, [r3, #-0xc8]) and the count is read before the frame."""
    test_the_ports_carry_what_the_finder_reads_off_the_game("mando_le-1.44")
    v = _port("mando_le-1.44")["value"]
    assert int(v["challenge_on_flag"]) == 16 and int(v["challenge_menu_entry"]) == 20
    assert int(v["challenge_menu_pick_back"]) == 200 and int(v["challenge_menu_list_at"]) == 584
    assert int(v["challenge_menu_count_at"]) == 56 and int(v["challenge_menu_sets_on"]) == 1


def test_the_end_of_ball_call_is_told_from_its_lookalikes():
    def elf(words):
        return type("E", (), {"words": tuple(words), "text_va": 0x10000})()
    real = [0xE30C2846, 0xE3402B67, 0xE92D4038, 0xE1A05001, 0xE1D230B0, 0xE1A04000, 0xE3833C02, 0xE3833002,
            0xE1C230B0, 0xEB000000, 0xE3A01A01, 0xE3A00000, 0xEB000000, 0, 0]            # Rush LE 1.19 0x16224c
    other = [0xE30C2846, 0xE3402B67, 0xE92D4008, 0xE1D230B0, 0xE3833C02, 0xE3833002, 0xE1C230B0, 0xEB000000,
             0, 0, 0, 0, 0, 0, 0]                                                       # its 0xfe5f8 (no arg, no flippers)
    lines = PC.end_ball_lines(elf(other + real))
    assert lines[-1].split()[2] == "0x%08x" % (0x10000 + 4 * len(other))


def test_the_tab_says_default_game_mode_only_where_it_can_pick_the_challenge():
    P = MP.profiles(MP.PORTS_DIR)
    assert P["james_bond_le_1_06"].challenge_by_default and P["rush_pro_1_19"].challenge_by_default
    assert not P["jaws_pro_1_02"].challenge_by_default and not P["godzilla_pro_1_16"].challenge_by_default
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert '${prof.challenge_by_default ? " To start every game this way' in js


def test_the_tab_shows_the_challenge_row_where_only_challenges_of_a_modes_own_fit(tmp_path):
    """Deadpool Pro 1.16 names none of the game's challenges, but its start menu takes one of a mode's own: the row
    that picks it was hidden (challenge_found counted the game's named challenges only)."""
    from tests.test_webui_modes import _card_project, _project
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "dp", "deadpool_pro-1_16_0.Release.8G.sdcard.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            prof = w.state("modes")["profile"]
            assert prof["challenges"] == [] and prof["challenge_new"] and prof["challenge_found"]
    finally:
        preview.enabled = old
