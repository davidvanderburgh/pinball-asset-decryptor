"""PAD-710: a mode in the place of one of the game's own modes, counted as that mode, on every Spike 2 C++ title
(plugins/stern/mode_framework.py reads the game's mode framework; the runtime's side is pad_mode_runtime.c, "PAD-710:
a mode in the place of one of the game's own modes"; the mode file's `in_place_of`, mode_file.c).

- The finder's lines, and every shipped C++ port carrying them (the older builds' programs are not on hand: those get
  them from the card's own program when a card is built, mode_write.with_framework).
- The blocks hat "When the game starts one of its modes": its checks, words and the C it makes (the claim, the start
  run on the tick, the outcome given to the game at the end); End the mode's "completed".
- The form mode's `starts_on game_mode` and its `in_place_of` line; the profiles' places.
- The runtime and mode_file.c: the claim in the start hook, the START's bookkeeping, the game's own STOP.
- The desk harness, where an ELF host C compiler is: the game's start plays the mode, its end gives the outcome.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_framework as MF
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portgen

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
SHOTS = ["Left ramp", "Right ramp"]
PLACES = [[21, "Jet Fighter Attack", True], [23, "Tesla Strike", True]]


def _port(name):
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        return f.read()


def jet(won_block=True, seconds=30, hat=None):
    """Jet Fighter Attack's place taken: a Left ramp completes it (or, without won_block, just ends it)."""
    end = {"op": "end_mode", "won": True} if won_block else {"op": "end_mode"}
    return {"name": "JET STAND IN", "seconds": seconds, "game_modes": "stack",
            "scripts": [
                {"hat": hat or {"kind": "game_mode", "mode": 21, "name": "Jet Fighter Attack"},
                 "do": [{"op": "start_mode"}]},
                {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [end]}]}


def problems(program, places=PLACES):
    return BM.problems(program, shots=SHOTS, places=places)


# ---- the finder's lines --------------------------------------------------------------------------
def test_the_lines_are_written_and_only_the_missing_ones_added():
    found = MF.Found()
    found.update(mode_player=0x3387f0, mode_slot_stop=11, mode_stopped_at=0x13, mode_reason_at=0x17,
                 mode_starts_at=0x3c, mode_started=0xd47fc, mode_manager=0x7b0ce4, mode_id_at=4)
    lines = MF.port_lines(found)
    text = "\n".join(lines)
    for want in ("site  mode_player            0x003387f0", "value mode_slot_stop         11",
                 "value mode_stopped_at        0x13", "value mode_reason_at         0x17",
                 "value mode_starts_at         0x3c", "site  mode_started           0x000d47fc",
                 "data  mode_manager           0x007b0ce4", "value mode_id_at             4"):
        assert want in text
    assert "mode_wins_at" not in text
    assert MF.port_lines(MF.Found()) == []
    assert MF.missing_from(lines, text) == []
    assert MF.lines_for(b"", text) == []                 # the port has them: nothing read
    assert MF.lines_for(b"not an elf", "game x\n") == []  # an odd program: none, never an error


def test_the_framework_lines_are_each_builds_own():
    for line in ("site mode_player 0x1 0x2 0x3", "value mode_slot_stop 11", "value mode_stopped_at 0x13",
                 "value mode_reason_at 0x17", "value mode_starts_at 0x3c", "value mode_wins_at 0x64",
                 "site mode_started 0x1 0x2 0x3", "data mode_manager 0x1", "value mode_id_at 4"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line
    assert not portgen.generated("value", "mode_mask_busy 3")


#: the C++ builds whose programs the finder read for the shipped ports (PAD-710, the newest build of every title and
#: Godzilla Pro 1.15); the other C++ ports are older builds whose cards are archival - theirs come from the card
CPP_READ = ("avengers_infinity_le-1.10", "avengers_infinity_pro-1.10", "deadpool_le-1.16", "deadpool_pro-1.16",
            "dungeons_and_dragons_le-1.10", "dungeons_and_dragons_pro-1.10", "foo_fighters_le-1.04",
            "foo_fighters_pro-1.04", "godzilla_le-1.16", "godzilla_pro-1.15", "godzilla_pro-1.16",
            "iron_maiden_le-1.18", "iron_maiden_pro-1.18", "jaws_le-1.02", "jaws_pro-1.02", "john_wick_le-1.02",
            "john_wick_pro-1.02", "jurassic_park_le-1.16", "jurassic_park_pro-1.16", "king_kong_le-0.97",
            "king_kong_pro-0.97", "led_zeppelin_le-1.22", "led_zeppelin_pro-1.22", "mando_le-1.45", "mando_pro-1.45",
            "munsters_le-1.28", "munsters_pro-1.28", "rush_le-1.19", "rush_pro-1.19", "star_wars_le-1.31",
            "star_wars_pro-1.31", "sword_of_rage_le-1.19", "sword_of_rage_pro-1.19", "turtles_le-1.59",
            "turtles_pro-1.59", "venom_le-1.07", "venom_pro-1.07")


@pytest.mark.parametrize("port", CPP_READ)
def test_every_newest_cpp_port_names_its_mode_framework(port):
    text = _port(port)
    assert re.search(r"^site  mode_player\s+0x[0-9a-f]{8} 0x[0-9a-f]{8} 0x[0-9a-f]{8}$", text, re.M)
    assert re.search(r"^value mode_slot_stop\s+\d+$", text, re.M)
    assert re.search(r"^value mode_stopped_at\s+0x[0-9a-f]+$", text, re.M)
    # its game modes are named with the object their START is called on (PAD-363): what a claim takes
    assert re.search(r"^data block_obj_\d+\s+0x[0-9a-f]{8}$", text, re.M)


def test_the_generations_read_as_measured():
    # Godzilla's: a reason byte and the manager's STARTED notice; Star Wars' and Venom's: wins, no notice
    gz, sw, vn, jw = _port("godzilla_le-1.16"), _port("star_wars_pro-1.31"), _port("venom_pro-1.07"), \
        _port("john_wick_pro-1.02")
    for text, slot, stopped in ((gz, 11, "0x13"), (sw, 12, "0x17"), (vn, 50, "0x58"), (jw, 50, "0x57")):
        assert re.search(r"^value mode_slot_stop\s+%d$" % slot, text, re.M)
        assert re.search(r"^value mode_stopped_at\s+%s$" % stopped, text, re.M)
    assert re.search(r"^value mode_reason_at\s+0x17$", gz, re.M) and "mode_wins_at" not in gz
    assert re.search(r"^site  mode_started\s+0x000d47fc ", gz, re.M)
    assert re.search(r"^value mode_wins_at\s+0x64$", sw, re.M) and "mode_started" not in sw
    assert re.search(r"^value mode_wins_at\s+0x98$", vn, re.M)


@pytest.mark.parametrize("port", ["beatles-1.29", "james_bond_le-1.06", "stranger_things-1.13", "elvira3-1.13"])
def test_a_plain_c_port_names_no_framework(port):
    assert "mode_slot_stop" not in _port(port)


# ---- the blocks hat --------------------------------------------------------------------------------
def test_a_game_mode_hat_builds_where_the_game_lets_a_mode_take_a_place():
    assert problems(jet()) == []
    assert BM.HATS["game_mode"] == "When the game starts one of its modes"


def test_a_card_without_places_says_so():
    out = problems(jet(), places=[])
    assert any("waits for the game to start one of its modes, which a mode cannot take the place of" in p for p in out)


def test_a_mode_the_card_does_not_have_or_none_is_named():
    assert any("has none of the game's modes chosen" in p for p in problems(jet(hat={"kind": "game_mode"})))
    out = problems(jet(hat={"kind": "game_mode", "mode": 9, "name": "Nine"}))
    assert any("waits for the game's Nine, which this card's game does not let a mode take the place of" in p
               for p in out)


def test_one_script_per_game_mode():
    p = jet()
    p["scripts"].append({"hat": {"kind": "game_mode", "mode": 21, "name": "Jet Fighter Attack"},
                         "do": [{"op": "start_mode"}]})
    assert any("waits for the game's Jet Fighter Attack too: one script per game mode" in x for x in problems(p))


def test_the_words_and_notes():
    assert BM._hat_words({"kind": "game_mode", "mode": 21, "name": "Jet Fighter Attack"}) == \
        "when the game starts its Jet Fighter Attack"
    assert BM.place_name({"kind": "game_mode", "mode": 4}) == "mode 4"
    notes = BM.notes(jet(won_block=False))
    assert any("counts as completed when the mode ends by its clock or an End the mode block" in n for n in notes)
    p = jet()
    p["scripts"][0]["do"] = []
    assert any("starts nothing: the game's mode does not run either" in n for n in BM.notes(p))


def test_card_checks_carry_the_places():
    p = MP.profile("godzilla_le_1_16")
    places = BM.card_checks(p)["places"]
    assert places == [list(x) for x in p.places]
    if p.can("place"):
        names = [n for _i, n, _c in p.places]
        assert "Jet Fighter Attack" in names and not any(n.startswith("Battle vs") for n in names)


def test_the_c_claims_the_mode_and_gives_the_outcome_at_its_end():
    c = BM.to_c(jet(), "jet_stand_in")
    assert "static const unsigned PLACE_IDS[1] = { 21 };" in c
    assert "pm_place_claim(PLACE_IDS[i], on_place)" in c
    assert "return 1;                     /* the game's own does not start */" in c
    assert "pm_place_over(won);" in c and "battle_won = 1;" in c
    assert "if ((place_held) && run.on) drain_end();" in c
    assert "pm_roster" not in c


def test_without_a_won_block_its_own_end_completes_it():
    c = BM.to_c(jet(won_block=False), "jet_stand_in")
    assert "battle_won = 1;" in c                                # its End the mode block wins it


def test_the_c_only_calls_what_the_header_declares():
    with open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8") as f:
        declared = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", f.read()))
    used = set(re.findall(r"\b(pm_[a-z_]+)\s*\(", BM.to_c(jet(), "jet_stand_in")))
    assert used <= declared, used - declared


# ---- the form mode ---------------------------------------------------------------------------------
def _gz_place():
    p = MP.profile("godzilla_le_1_16")
    if not p.can("place"):
        pytest.skip("Godzilla LE 1.16 is not in PLACE_PROVEN")
    return p


def test_a_form_mode_in_a_game_modes_place_writes_its_line():
    p = _gz_place()
    spec = MP.new_mode_spec(p, "JET STAND IN") if hasattr(MP, "new_mode_spec") else MP.ModeSpec(name="JET", title=p.key)
    spec.starts_on, spec.place_mode = "game_mode", 21
    spec.seconds = 30
    assert MP.starts_on_place(spec)
    assert not [x for x in MP._validate_starts_ends(spec, p) if "game's mode" in x]
    lines = MP._starts_ends_lines(spec, ["name x", "seconds 30", "trigger 0x1 1"], p)
    assert "in_place_of    21" in lines and not any(x.startswith("trigger ") for x in lines)
    spec.place_mode = 999
    assert any("Pick the game's mode this one runs in the place of" in x for x in MP._validate_starts_ends(spec, p))


def test_the_places_leave_the_battles_to_the_battle_hat():
    port = MP.read_port(os.path.join(PORTS, "godzilla_le-1.16.port"))
    names = [n for _i, n, _c in MP._places(port)]
    assert "Jet Fighter Attack" in names and "Super Train" in names
    assert not any(n.startswith("Battle vs") for n in names)
    assert all(c for _i, _n, c in MP._places(port))


def test_a_plain_c_title_counts_through_its_own_books():
    """Run 2: a plain-C title's game modes count through their audits and flags, named after the mode."""
    port = MP.read_port(os.path.join(PORTS, "james_bond_le-1.06.port"))
    places = {i: (n, c) for i, n, c in MP._places(port)}
    assert places[6] == ("Ahoy Mr Bond Wizard Mode", True)
    assert places[29] == ("Bird One Multiball", True)    # PAD-715: the game's ROCKET_MULTIBALL books
    text = _port("james_bond_le-1.06")
    assert re.search(r"^site  audit_add\s+0x00245ea0 0xe92d43f0 0xe2505000$", text, re.M)
    for line in ("value place_audit_started_6        276", "value place_flag_played_6          86",   # PAD-714: the id its start counts
                 "value place_flag_completed_6       89"):
        assert line in text, line
    p = MP.profile("james_bond_le_1_06")
    assert p.can("place") == ("james_bond_le-1.06" in MP.PLACE_PROVEN)


def test_the_plain_c_stems_are_the_games_spellings():
    st = MF._stems("Egghead (episodes 47-48)")
    assert "EGGHEAD_MODE_EP_47_48" in st and "EGGHEAD" in st
    assert "UPSIDE_DOWN_HURRYUP" in MF._stems("Upside Down Hurry-Up")
    assert "MODE_ALL_MY_LOVING" in MF._stems("All My Loving") and "BATTERY_MODE" in MF._stems("Battery")
    assert "DR_NOS_LAIR" in MF._stems("Dr No's Lair") and "HOUSE" in MF._stems("Houses (whichever House is selected)")
    for line in ("site audit_add 0x1 0x2 0x3", "value place_audit_started_6 180", "value place_audit_completed_6 3",
                 "value place_flag_played_6 86", "value place_flag_completed_6 89"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line
    assert MF.plain_lines({}, None) == [] and MF.plain_lines_for(b"not an elf", "game x\n") == []


PLAIN_READ = ("aerosmith-1.16", "aerosmith_le-1.16", "batman-1.14", "beatles-1.29", "elvira3-1.13", "guardians-1.15",
              "guardians_le-1.15", "james_bond_le-1.06", "james_bond_pro-1.06", "jurassic_park_the_pin-1.05",
              "metallica_spike-1.04", "star_wars_elg-1.10", "stranger_things-1.13", "stranger_things_le-1.13",
              "uncanny_xmen_le-0.98", "uncanny_xmen_pro-0.98")


@pytest.mark.parametrize("port", PLAIN_READ)
def test_every_newest_plain_c_port_names_its_modes_books(port):
    text = _port(port)
    if port == "star_wars_elg-1.10":     # no standard audit add on it: its flags alone
        assert not re.search(r"^site\s+audit_add\s", text, re.M)
        assert re.search(r"^value place_flag_(played|completed)_\d+\s+\d+$", text, re.M)
        assert not re.search(r"^value place_audit_", text, re.M)
    else:
        assert re.search(r"^site  audit_add\s+0x[0-9a-f]{8} 0xe92d43f0 0xe2505000$", text, re.M)
    assert re.search(r"^value place_(audit_started|audit_completed|flag_played|flag_completed)_\d+\s+\d+$", text, re.M)
    assert "mode_slot_stop" not in text


def test_the_proven_builds_are_ports_with_the_lines():
    for key in MP.PLACE_PROVEN:     # the C++ framework's stop, or a plain-C title's books
        text = _port(key)
        assert "mode_slot_stop" in text or re.search(r"^value place_(audit|flag)_\w+\s", text, re.M), key


# ---- the runtime and mode_file.c -------------------------------------------------------------------
def _src(name):
    with open(os.path.join(SDK, name), encoding="utf-8") as f:
        return f.read()


def test_the_runtime_takes_the_start_and_counts_it():
    rt = _src("pad_mode_runtime.c")
    hook = rt[rt.index("static int on_block_start(unsigned *r, unsigned hook_n)"):]
    hook = hook[:hook.index("\n}\n")]
    assert "if (id < BLOCK_IDS && !place_check[id] && place_take(r, id)) return 1;" in hook
    assert hook.index("place_take") < hook.index("lit_hold_until")   # before the lit hold and the block
    for want in ("place_begin(block_obj[id], id, up);", "place_audit(a);", "place_flag_set(fl)",
                 'place_book("audit_completed", id)', "if (!block_obj[id] && !place_fn[id]) return 0;",
                 "((void (*)(unsigned, unsigned, unsigned))(unsigned long)f)(obj, won ? 1u : 0u, 1u);",
                 "place_arm();", "place_tick();", "place_ball_end();", 'can & PM_CAN_PLACE ? " place" : ""'):
        assert want in rt, want
    h = _src("pad_mode.h")
    assert "#define PM_CAN_PLACE        0x10000000u" in h
    caps = [int(v, 16) for v in re.findall(r"#define PM_CAN_\w+\s+(0x[0-9a-fA-F]+)u", h)]
    assert len(caps) == len(set(caps))                         # no capability bit used twice


def test_mode_files_take_a_place_with_in_place_of():
    mf = _src("mode_file.c")
    for want in ('key_is(line, "in_place_of")', "if (place_line(M, line)) return;", "pm_place_claim(want - 1, place_start)",
                 "place_ended(name_is(why, \"end shot\") || (!cfg.end_shot_bits && name_is(why, \"time ran out\")));",
                 "place_tick();", "place_ball_end();"):
        assert want in mf, want


# ---- the desk -------------------------------------------------------------------------------------
def _cc():
    if os.name == "nt":
        pytest.skip("the desk harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    if sys.platform == "darwin":
        pytest.skip("the desk harness needs an ELF toolchain (section(\"pm_modes\"))")
    for c in ("gcc", "cc", "clang"):
        if shutil.which(c):
            return c
    pytest.skip("no host C compiler")


def play(tmp_path, program, *args, slug="jet_stand_in"):
    cc = _cc()
    src = tmp_path / (slug + ".c")
    src.write_text(BM.to_c(program, slug), encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe),
                        os.path.join(SDK, "examples", "desk_harness.c"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_games_start_plays_the_mode_and_its_win_completes_it(tmp_path):
    out = play(tmp_path, jet(), "gamestart", 21, "secs", 1, "shot", "Left ramp", "secs", 2)
    assert "PLACE CLAIM 21 JET STAND IN" in out
    assert "GAMESTART 21 -> 1" in out
    assert "[JET STAND IN] START (a block): player 1" in out
    assert "[JET STAND IN] the game's mode it took the place of: COMPLETED" in out
    assert out.count("PLACE OVER") == 1 and "PLACE OVER COMPLETED" in out


def test_a_drain_is_not_completed(tmp_path):
    out = play(tmp_path, jet(), "gamestart", 21, "secs", 1, "ball_end", "secs", 12)
    assert "END (ball ended)" in out
    assert out.count("PLACE OVER") == 1 and "PLACE OVER not completed" in out


def test_without_a_won_block_the_clock_completes_it(tmp_path):
    out = play(tmp_path, jet(won_block=False, seconds=5), "gamestart", 21, "secs", 7)
    assert "END (time ran out)" in out and "PLACE OVER COMPLETED" in out


def test_another_mode_is_not_taken_and_a_start_while_it_runs_restarts_nothing(tmp_path):
    out = play(tmp_path, jet(), "gamestart", 23, "gamestart", 21, "secs", 1, "gamestart", 21, "secs", 1)
    assert "GAMESTART 23 -> -1" in out
    assert out.count("START (a block)") == 1
    assert "while this runs - nothing restarts" in out


def test_a_start_the_mode_does_not_take_is_not_completed(tmp_path):
    p = jet()
    p["scripts"][0]["do"] = []                                      # nothing starts it
    out = play(tmp_path, p, "gamestart", 21, "secs", 1)
    assert "the game started its mode and this started nothing - not completed" in out
    assert "PLACE OVER not completed" in out


# ---- the challenges that are one of the game's own modes --------------------------------------------------------
def test_a_challenge_that_is_a_game_mode_maps_by_its_words():
    port = "\n".join(["text block_name_6       Ahoy Mr Bond Wizard Mode", "site block_start_6 0x1000",
                      "text block_name_7       Ahoy Mr Bond Bonus", "text block_name_8       Fourth of July",
                      "site block_start_8 0x2000", "text challenge_name_1   Ahoy Mr. Bond",
                      "text challenge_name_2   4th of July", "text challenge_name_3   Spy Hunter", ""])
    assert MF.challenge_places(port) == {1: 6, 2: 8}       # block 7 has no start; challenge 3 is no mode
    lines = MF.challenge_place_lines(port)
    assert "value challenge_place_1        6" in lines and "value challenge_place_2        8" in lines
    assert MF.challenge_place_lines(port + "\n".join(lines[1:]) + "\n") == []


@pytest.mark.parametrize("port, n, mode", [("james_bond_le-1.06", 1, 6), ("james_bond_pro-1.06", 1, 6),
                                           ("godzilla_le-1.16", 0, 20), ("rush_le-1.19", 2, 35)])
def test_the_ports_name_their_challenges_modes(port, n, mode):
    assert re.search(r"^value challenge_place_%d\s+%d$" % (n, mode), _port(port), re.M)


def test_a_challenge_mode_counts_as_the_game_mode_at_its_take_and_its_end():
    rt = _src("pad_mode_runtime.c")
    assert rt.count("chg_picked(challenge_by[n], n, challenge_title[n], (int)n); place_challenge(n); }") == 2
    assert 'pm_snprintf(key, sizeof key, "challenge_place_%u", n);' in rt
    mf = _src("mode_file.c")
    assert "if (run.by_challenge)" in mf and "pm_place_over(" in mf


def test_a_blocks_mode_a_challenge_started_counts_its_end():
    prog = {"name": "YOLT", "seconds": 30, "game_modes": "block", "vars": [], "scripts": [
        {"hat": {"kind": "challenge", "challenge": "Ahoy Mr. Bond"}, "do": [{"op": "start_mode"}]}]}
    c = BM.to_c(prog, "yolt")
    assert "static int challenge_run;" in c and "if (run.on) challenge_run = 1;" in c
    end = c[c.index("if (challenge_run) {"):]
    assert end.index("challenge_run = 0;") < end.index("pm_place_over(won);")
    assert "challenge_run" not in BM.to_c({"name": "P", "scripts": [{"hat": {"kind": "mode_start"}, "do": []}]}, "p")
