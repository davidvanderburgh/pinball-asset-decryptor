"""PAD-1291: the Spike 3 port of Star Wars 2025 Pro 0.84, drafted from Star Wars ELG 1.10's proven Spike 3 port.

Its switch ids are not the device table's ranks (s3port.py's guess, right on ELG and Walking Dead Remastered): the game
numbers Right target after every other playfield switch (83, rank 61) and each switch after it one lower, so the first
draft's trigger never reached a mode. proofs/swcensus.sh measures the id the game hands its switch_hit site for each
switch, and `s3port.py --switch-ids` writes the port's switch lines from that census only. With it a clock mode started on
three Right target hits, scored through score_add and ended on its clock; a mode's multiball, a ball save and a stack no
mode were proven on the rig, and the Modes tab offers those three on the Spike 3 card.

The redraft test reads the real programs when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1
ceb8d70b...) and `star_wars_2025_pro.game` (sha1 2c9070fb...), each a card's games/<game>/game.
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
PRO_PORT = PORTS3 / "star_wars_2025_pro-0.84.port"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
CENSUS = PROOFS / "titles" / "star_wars_2025_pro-0.84.switch_ids"
TITLE_ENV = PROOFS / "titles" / "star_wars_2025_pro.env"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "star_wars_2025_pro": "2c9070fbd10913ecb3a25d93a7fc5cc2eea74bde"}
KEY = "star_wars_2025_pro-0.84/spike3"


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
    # (and the Pro's game / ball start events, measured on the rig in PAD-1327: its bus ids are one lower past 56)
    return {k: v for k, v in entries.items() if not k[1].startswith(HAND)
            and k not in (("event", "game_start"), ("event", "ball_start"))}


def _switch_lines(text):
    return [(int(m.group(1)), int(m.group(2), 16), m.group(3).strip())
            for m in re.finditer(r"^switch\s+(\d+)\s+(0x[0-9a-f]+)\s+(.+)$", text, re.M)]


# ---- measured switch ids ----------------------------------------------------------------------------------------
def test_the_pro_census_is_read_in_the_shared_format():
    # PAD-1290's format (s3census.sh), which swcensus.sh writes too: `<id> <NAME>`, a switch with no hit a `#` note
    S = _s3port()
    ids = S.read_switch_ids(str(CENSUS))
    assert len(ids) == 27 and ids["RIGHT TARGET"] == 83 and ids["LEFT SPINNER OPTO"] == 61
    assert "LEFT SLINGSHOT" not in ids and "# no switch hit: LEFT SLINGSHOT" in CENSUS.read_text(encoding="utf-8")


def test_measured_ids_replace_the_rank_and_unmeasured_switches_are_left_out(monkeypatch):
    S = _s3port()
    recs = [("SERVICE SELECT", 5, 8, 1), ("RIGHT TARGET", 6, 0, 1), ("LEFT SLINGSHOT", 6, 1, 1),
            ("LEFT ORBIT", 6, 2, 1), ("TOP VUK", 6, 3, 1), ("GI", 6, 0, 3)]
    monkeypatch.setattr(S, "device_records", lambda t: recs)
    # unmeasured: the rank, as before
    assert S.spike3_switches(object()) == [(2, 0x1, "Right target"), (3, 0x2, "Left slingshot"),
                                           (4, 0x4, "Left orbit"), (5, 0x8, "Top vuk")]
    unseen = []
    sw = S.spike3_switches(object(), {"RIGHT TARGET": 83, "LEFT ORBIT": 3}, unseen)
    # each its measured id, the shot bits packed over the switches written
    assert sw == [(83, 0x1, "Right target"), (3, 0x2, "Left orbit")]
    assert unseen == ["Left slingshot", "Top vuk"]


# ---- the shipped port, proven on the rig ------------------------------------------------------------------------
def test_the_pro_port_carries_the_core_and_its_measured_switches():
    text = PRO_PORT.read_text(encoding="utf-8")
    e = _entries(text)
    for name in ("tick", "switch_hit", "switch_hit2", "hook_dispatch", "score_add", "agent_header", "agent_begin",
                 "multiball_serve"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    assert e[("event", "game_over")] == "0x46"          # 0x47 on ELG and Walking Dead Remastered
    census = _s3port().read_switch_ids(str(CENSUS))
    lines = _switch_lines(text)
    assert len(lines) == 27 == len(census)
    for sid, mask, name in lines:
        assert census[name.upper()] == sid, name
    assert ("Right target" in {n for _, _, n in lines}) and dict((n, s) for s, _, n in lines)["Right target"] == 83
    assert [m for _, m, _ in lines] == [1 << k for k in range(27)]
    assert re.search(r"^text example_start_shot\s+Right target$", text, re.M)
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in body if l.split()[0] in ("lamp", "scene", "callout")]
    assert not [l for l in body if re.match(r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|"
                                            r"mode_flag|held_coils|place_flag|done_flag|coil_take|coil_give)", l)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-15 (PAD-1291)" in text


def test_the_title_file_names_the_ports_own_bits():
    env = dict(re.findall(r"^(\w+)=\$\{\w+:-(.*)\}", TITLE_ENV.read_text(encoding="utf-8"), re.M))
    lines = {n.upper(): m for _, m, n in _switch_lines(PRO_PORT.read_text(encoding="utf-8"))}
    assert int(env["TRIGGER_BITS"], 16) == lines[env["TRIGGER_SW"]]
    assert int(env["SHOT_BITS"], 16) == sum(lines[s] for s in env["SHOT_SWS"].split("|"))
    assert env["PORTNAME"] == PRO_PORT.name


def test_the_app_takes_the_pro_port_and_offers_what_the_rig_proved():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("star_wars_2025_pro", "0_84_0", arch="a64") == str(PRO_PORT)
    assert MR.port_arch(str(PRO_PORT)) == "a64"
    assert not MW.port_unproven(str(PRO_PORT))
    prof = MP.profiles()["star_wars_2025_pro_0_84_spike3"]
    assert prof.port == "spike3/star_wars_2025_pro-0.84.port" and "(Spike 3)" in prof.label
    for table in (MP.MULTIBALL_PROVEN, MP.BALL_SAVE_PROVEN, MP.STACK_BALLS_PROVEN, MP.SWITCH_SHOTS_PROVEN):
        assert KEY in table
    prof_p = MP.profile_from_port(str(PRO_PORT))
    assert prof_p.switch_shots_note == ""                    # every switch line seen reaching a mode
    cannot = {c[0] for c in prof_p.cannot}
    assert not cannot & {"multiball", "ball_save", "stack"}
    # never proven here: the Spike 2 tables' other rows stay off the Spike 3 build
    assert {"place", "done", "coils", "lights", "screen"} <= cannot


# ---- on the real programs ---------------------------------------------------------------------------------------
def _prog(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    with open(p, "rb") as f:
        if hashlib.sha1(f.read()).hexdigest() != SHA[game]:
            pytest.skip("%s.game is another build" % game)
    return p


def test_redrafting_the_pro_from_its_census_gives_the_shipped_port():
    S = _s3port()
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("star_wars_2025_pro"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "star_wars_2025_pro", "0.84",
                                         S.read_switch_ids(str(CENSUS)))
    assert not core
    # the shipped port is what the rig proved: shots from the two switch_hit sites, at the census's ids. A draft also
    # writes PAD-1322's 64-bit switch_edge source (merged after this port was proven, as for Pokemon LE); the Pro
    # carries those lines once a run proves them there, so the redraft is the shipped port plus exactly those
    edge = {("site", "switch_edge"), ("value", "switch_record_reg"), ("value", "switch_id_at"),
            ("value", "switch_level_at"), ("value", "switch_desc_via"), ("value", "switch_flags_at"),
            ("value", "switch_polarity_at")}
    mine, shipped = _own(_entries(text)), _own(_entries(PRO_PORT.read_text(encoding="utf-8")))
    assert set(mine) - set(shipped) == edge
    assert {k: v for k, v in mine.items() if k not in edge} == shipped
    # the rank the table alone gives is what the census corrected
    plain = dict((n, s) for s, _, n in S.spike3_switches(tgt))
    assert plain["Right target"] == 61 and plain["Left orbit"] == 64
