"""PAD-1288: Fallout LE 0.82's Spike 3 port, drafted by s3port.py from Star Wars ELG 1.10's proven Spike 3 port and
proven on the Spike 3 rig: a mode started on three Junk target hits, scored through the game's score_add and ended on
its clock; a mode's ball save served back the drain inside it (the control without one ended on its first drain); a
mode's own multiball was served to 3 and handed back at one ball. A real card was written with a mode and read back.

The drafter never carries the reference game's own mode books (place_flag / done_flag: the flags ITS modes set) nor
one of a pair of sites the runtime arms only together (coil_take / coil_give).
The redraft test reads the real programs when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1
ceb8d70b...) and `fallout_le.game` (sha1 19081048...), each a card's games/<game>/game.
"""
import hashlib
import importlib.util
import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTS3 = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3"
ELG_PORT = PORTS3 / "star_wars_elg-1.10.port"
FO_PORT = PORTS3 / "fallout_le-0.82.port"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "fallout_le": "19081048c0b2427efca8c05775efb109e13689da"}


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _entries(text):
    out = {}
    for line in text.splitlines():
        t = line.split()
        if t and t[0] in ("site", "data", "value", "event", "switch"):
            out[(t[0], t[1])] = t[2]
    return out


#: the lines measured by hand on this program, not drafted from the reference: PAD-1326's co-op (portcoop: the
#: message table and its BALL line) and PAD-1327's start menu, champion framework and audit add
HAND = ("message_", "coop_", "comp_menu_", "challenge_", "game_scores", "audit_add")


def _own(entries):
    return {k: v for k, v in entries.items() if not k[1].startswith(HAND)}


# ---- the drafter's rules --------------------------------------------------------------------------------------

def test_the_reference_games_mode_books_are_its_own():
    S = _s3port()
    for name in ("place_flag_completed_1", "place_flag_played_0", "done_flag_0", "done_audit_2"):
        assert S.GAME_VALUE.match(name), name
    for name in ("score_mult_off", "proc_exit_hooks", "ball_end_event"):
        assert not S.GAME_VALUE.match(name), name
    assert ("coil_take", "coil_give") in S.SITE_PAIRS


# ---- the shipped port -----------------------------------------------------------------------------------------

def test_the_fallout_port_carries_the_core_and_none_of_star_wars_content():
    text = FO_PORT.read_text(encoding="utf-8")
    e = _entries(text)
    for name in ("tick", "switch_hit", "switch_hit2", "hook_dispatch", "score_add", "agent_header", "agent_begin",
                 "multiball_serve"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    assert sum(1 for k in e if k[0] == "switch") == 39
    assert e[("switch", "38")] == "0x40"                       # Junk target: the proofs' trigger
    assert re.search(r"^text example_start_shot\s+Junk target$", text, re.M)
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert not [ln for ln in body if ln.split()[0] in ("lamp", "scene", "callout")]
    assert not [ln for ln in body if re.match(r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|"
                                               r"mode_flag|held_coils|place_flag|done_flag|coil_give|coil_take)", ln)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-15 (PAD-1288)" in text
    assert "19081048c0b2427efca8c05775efb109e13689da" in text


def test_the_app_lists_and_takes_the_fallout_port_for_spike3_only():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("fallout_le", "0_82_0", arch="a64") == str(FO_PORT)
    assert MR.port_arch(str(FO_PORT)) == "a64"
    assert not MW.port_unproven(str(FO_PORT))
    prof = MP.profiles()["fallout_le_0_82_spike3"]
    assert prof.port == "spike3/fallout_le-0.82.port" and prof.label == "Fallout LE 0.82 (Spike 3)"
    assert MP.profile_for_card("fallout_le", "0.82.0", arch="a64").key == prof.key
    assert MP.profile_for_card("fallout_le", "0.82.0") is None           # no Spike 2 Fallout
    # what the rig proved is offered; what it has not seen stays greyed
    cannot = {c[0] for c in prof.cannot}
    assert "ball_save" not in cannot and "multiball" not in cannot
    assert {"stack", "place", "done", "lights", "screen", "clip", "own_sound"} <= cannot
    assert MP.table_key("fallout_le", "0.82", "a64") in MP.BALL_SAVE_PROVEN & MP.MULTIBALL_PROVEN


def test_walking_dead_remastered_s_proven_multiball_is_offered():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = MP.profiles()["walking_dead_remastered_le_0_92_spike3"]
    assert "multiball" not in {c[0] for c in prof.cannot}


# ---- the proof tooling ----------------------------------------------------------------------------------------

def test_the_title_file_and_mode_files_name_switches_the_port_has():
    text = (PROOFS / "titles" / "fallout_le.env").read_text()
    env = {k: v for k, v in re.findall(r"^(\w+)=\$\{\w+:-(.*?)\}", text, re.M)}
    names = {ln.split(None, 3)[3].upper(): int(ln.split()[2], 16)
             for ln in FO_PORT.read_text(encoding="utf-8").splitlines() if ln.startswith("switch ")}
    assert env["PORTNAME"] == FO_PORT.name and env["MODES"] == "$HERE/modes/fallout_le"
    trigger, shots = names[env["TRIGGER_SW"]], sum(names[s] for s in env["SHOT_SWS"].split("|"))
    assert all(s in names for s in env["EARLY_SWS"].split("|"))
    cfgs = sorted((PROOFS / "modes" / "fallout_le").glob("*.cfg"))
    assert {c.stem for c in cfgs} >= {"clock", "save", "savectl", "mb", "edge"}
    for c in cfgs:
        t = c.read_text()
        assert int(re.search(r"^trigger\s+(0x[0-9a-f]+)", t, re.M).group(1), 16) == trigger, c.name
        assert int(re.search(r"^shots\s+(0x[0-9a-f]+)", t, re.M).group(1), 16) == shots, c.name
    assert re.search(r"^(\w+\|)*mode(\|\w+)*\)$", (PROOFS / "play.sh").read_text(), re.M)
    assert "AFTER_START_SWS" in (PROOFS / "play.sh").read_text()


# ---- on the real programs -------------------------------------------------------------------------------------

def _prog(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    with open(p, "rb") as f:
        if hashlib.sha1(f.read()).hexdigest() != SHA[game]:
            pytest.skip("%s.game is another build" % game)
    return p


def test_redrafting_fallout_gives_the_proven_port():
    S = _s3port()
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("fallout_le"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "fallout_le", "0.82")
    assert not core
    assert _own(_entries(text)) == _own(_entries(FO_PORT.read_text(encoding="utf-8")))
    # Star Wars ELG's mode books line up in the framework's flag code but are written as its own, and coil_give alone
    assert re.search(r"^# not carried \(coil_take has no counterpart.*site coil_give", text, re.M)
    assert not re.search(r"^value (done|place)_flag", text, re.M)
