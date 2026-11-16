"""PAD-1287: a Spike 3 port drafted from another Spike 3 title's proven port (s3port.py, a 64-bit reference).

Every Spike 3 program is the same 64-bit framework built with one compiler around a game's rules, so the reference
port carries over by lining up the paired functions' instructions (addresses and immediates masked): sites, globals
and offsets are read at the lined-up instruction, the engines' layouts re-read off the target's own code, the bus ids
checked at the dispatch's own calls and the switch lines made from the target's own device table. The reference game's
own content (shows, lamps, callouts, scenes, held coils, its modes) is never carried.

Walking Dead Remastered LE 0.92 was drafted from Star Wars ELG 1.10's Spike 3 port and proven on the Spike 3 rig: a
mode started on three Tower target hits, scored through the game's score_add, ended on the bus's end of ball and on
its clock; sounds played, stopped and faded on the game's channels; a mode's multiball was served to 3 balls.

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1
ceb8d70b...) and `walking_dead_remastered_le.game` (sha1 bcf428e1...), each a card's games/<game>/game.
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
WD_PORT = PORTS3 / "walking_dead_remastered_le-0.92.port"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "walking_dead_remastered_le": "bcf428e162bfec6add82aac519f5f93968d0e283"}


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


# ---- the instruction shapes the alignment reads ---------------------------------------------------------------
def test_immediates_are_decoded_as_the_alignment_compares_them():
    S = _s3port()
    assert S._imm(0x52804204) == 0x210            # mov w4, #0x210 (Star Wars ELG's mode_mask_busy test)
    assert S._imm(0xF9408820) == 272              # ldr x0, [x1, #272] (the channel's request)
    assert S._imm(0x79404261) == 32               # ldrh w1, [x19, #32]
    assert S._imm(0x91000400) == 1                # add x0, x0, #1
    assert S._imm(0x12000821) == 7                # and w1, w1, #0x7
    assert S._imm(0xF240009F) == 1                # tst x4, #0x1
    assert S._imm(0xA9BA53F3) == -96              # stp x19, x20, [sp, #-96]!
    assert S._imm(0xD65F03C0) is None             # ret


def test_the_loose_shape_masks_addresses_and_offsets_but_keeps_registers():
    S = _s3port()
    assert S._loose(0xF9408820) == S._loose(0xF9409C20)          # ldr x0, [x1, #272] ~ ldr x0, [x1, #312]
    assert S._loose(0xF9408820) != S._loose(0xF9408821)          # ... but not into another register
    assert S._loose(0x94000010) == S._loose(0x94123456)          # bl anywhere
    assert S._loose(0x52804204) == S._loose(0x52800684)          # mov w4, #imm
    assert S._loose(0x37680041) != S._loose(0x37600041)          # tbnz w1, #13 vs #12: the bit is kept


# ---- the switch lines: the target's own device table ------------------------------------------------------------
def test_switch_lines_are_the_playfield_shots_of_the_targets_own_table(monkeypatch):
    S = _s3port()
    recs = ([("QR SCANNER STATUS READY", 2, 0, 1), ("SERVICE SELECT", 5, 8, 1), ("DOOR SWITCH OPTO", 5, 12, 1)] +
            [("RIGHT POP BUMPER", 6, 0, 1), ("LEFT FLIPPER EOS", 6, 1, 1), ("START BUTTON", 6, 2, 1),
             ("TROUGH 1", 6, 3, 1), ("SHOOTER LANE", 6, 4, 1), ("Tower target", 6, 5, 1), ("STANDUP", 6, 6, 1),
             ("STANDUP", 6, 7, 1), ("GI", 6, 0, 3)])
    monkeypatch.setattr(S, "device_records", lambda t: recs)
    sw = S.spike3_switches(object())
    # ids: the record's rank among the table's switches, from 1 (the lamp is not one); two of one name both kept
    assert sw == [(4, 0x1, "Right pop bumper"), (9, 0x2, "Tower target"), (10, 0x4, "Standup (10)"),
                  (11, 0x8, "Standup (11)")]


def test_no_more_switch_lines_than_the_runtime_maps(monkeypatch):
    S = _s3port()
    monkeypatch.setattr(S, "device_records", lambda t: [("TARGET %d" % k, 6, k, 1) for k in range(80)])
    sw = S.spike3_switches(object())
    assert len(sw) == 64 and sw[-1][1] == 1 << 63


# ---- the shipped port it drafted, proven on the rig -------------------------------------------------------------
def test_the_walking_dead_port_carries_the_core_and_none_of_star_wars_content():
    text = WD_PORT.read_text(encoding="utf-8")
    e = _entries(text)
    for name in ("tick", "switch_hit", "switch_hit2", "hook_dispatch", "score_add", "agent_header", "agent_begin"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    assert sum(1 for k in e if k[0] == "switch") == 32
    assert re.search(r"^text example_start_shot\s+Tower target$", text, re.M)
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in body if l.split()[0] in ("lamp", "scene", "callout")]
    assert not [l for l in body if re.match(r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|mode_flag|held_coils)", l)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-15 (PAD-1287)" in text


def test_the_app_lists_and_takes_the_walking_dead_port_for_spike3_only():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("walking_dead_remastered_le", "0_92_0", arch="a64") == str(WD_PORT)
    assert MR.port_arch(str(WD_PORT)) == "a64"
    prof = MP.profiles()["walking_dead_remastered_le_0_92_spike3"]
    assert prof.port == "spike3/walking_dead_remastered_le-0.92.port"
    assert "(Spike 3)" in prof.label
    assert not MW.port_unproven(str(WD_PORT))


# ---- on the real programs ---------------------------------------------------------------------------------------
def _prog(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    with open(p, "rb") as f:
        if hashlib.sha1(f.read()).hexdigest() != SHA[game]:
            pytest.skip("%s.game is another build" % game)
    return p


def test_drafting_star_wars_elg_from_itself_gives_back_its_own_framework_entries():
    S = _s3port()
    p = _prog("star_wars_elg")
    text, M, core, missing = S.draft_spike3(S.Elf(p), str(ELG_PORT), S.Elf(p), "star_wars_elg", "1.10")
    mine, theirs = _entries(text), _entries(ELG_PORT.read_text(encoding="utf-8"))
    assert not core
    assert len(mine) > 90 and {k: v for k, v in mine.items() if theirs.get(k) != v} == {}
    assert "NOT RUN" in text


def test_redrafting_walking_dead_gives_the_proven_port():
    S = _s3port()
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("walking_dead_remastered_le"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "walking_dead_remastered_le", "0.92")
    assert not core
    # (PAD-1326's co-op lines are portcoop's, not the draft's: the message table and its BALL line)
    # (and PAD-1327's start menu, measured by hand on this program)
    def own(entries):
        return {k: v for k, v in entries.items() if not k[1].startswith(("message_", "coop_", "comp_menu_", "challenge_", "game_scores", "audit_add"))}
    assert own(_entries(text)) == own(_entries(WD_PORT.read_text(encoding="utf-8")))
    # a layout that moved is read off this program, not copied: the process's exit hooks (Star Wars ELG's at 312)
    assert re.search(r"^value proc_exit_hooks\s+392\b", text, re.M)


def test_the_reference_games_mode_books_are_never_carried_by_their_numbers():
    """PAD-1292: Star Wars ELG's Captive Multiball / Ramps COMPLETED flags (66 / 68) lined up on Walking Dead
    Remastered, whose 66 / 68 are other flags: a book's flag is the reference game's own, like its mode flags"""
    S = _s3port()
    for name in ("done_flag_0", "place_flag_completed_2", "place_flag_played_1", "mode_flag_1", "block_name_0"):
        assert S.GAME_VALUE.match(name), name
    for name in ("proc_exit_hooks", "event_flags", "game_flag_count"):
        assert not S.GAME_VALUE.match(name), name
    assert not re.search(r"^value (done_flag|place_flag)_", WD_PORT.read_text(encoding="utf-8"), re.M)
