"""PAD-1290: the Spike 3 port of Star Wars 2025 LE 0.96, drafted from Star Wars ELG 1.10's proven Spike 3 port.

Its switch lines carry ids MEASURED on the rig: the draft's ids (each switch's rank in the device table, right on ELG
and Walking Dead Remastered) put a press on the wrong shot here - this program numbers its RIGHT TARGET last (87) and
every switch after it one lower. proofs/s3census.sh presses each switch in a game with a port that gives every id a
bit of its own and writes what reached the modes; `s3port.py --switch-ids` drafts from that.

The redraft test runs when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1 ceb8d70b...) and
`star_wars_2025_le.game` (sha1 91fb0281...), each a card's games/<game>/game.
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
PORT = PORTS3 / "star_wars_2025_le-0.96.port"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
CENSUS = PROOFS / "titles" / "star_wars_2025_le-0.96.switch_ids"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "star_wars_2025_le": "91fb0281b13b607d400fb1b971e9e04c2f71568d"}


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _entries(text):
    out = {}
    for line in text.splitlines():
        t = line.split("#", 1)[0].split()
        if len(t) >= 2:
            out[(t[0], t[1])] = " ".join(t[2:])
    return out


#: the lines measured by hand on this program, not drafted from the reference: PAD-1326's co-op (portcoop: the
#: message table and its BALL line) and PAD-1327's start menu, champion framework and audit add
HAND = ("message_", "coop_", "comp_menu_", "challenge_", "game_scores", "audit_add")


def _own(entries):
    return {k: v for k, v in entries.items() if not k[1].startswith(HAND)}


# ---- the census ---------------------------------------------------------------------------------------------------
def test_measured_ids_renumber_the_switch_lines_and_leave_out_what_never_reached_the_modes(monkeypatch):
    S = _s3port()
    recs = [("QR SCANNER STATUS READY", 2, 0, 1), ("LEFT OUTLANE", 7, 0, 1), ("LEFT SLINGSHOT", 7, 1, 1),
            ("RIGHT TARGET", 7, 2, 1), ("LEFT ORBIT", 8, 0, 1), ("RIGHT ORBIT", 8, 1, 1), ("GI", 6, 0, 3)]
    monkeypatch.setattr(S, "device_records", lambda t: recs)
    # the table's ranks, as drafted without a census
    assert S.spike3_switches(object()) == [(2, 0x1, "Left outlane"), (3, 0x2, "Left slingshot"),
                                           (4, 0x4, "Right target"), (5, 0x8, "Left orbit"), (6, 0x10, "Right orbit")]
    unseen = []
    sw = S.spike3_switches(object(), {"LEFT OUTLANE": 2, "RIGHT TARGET": 6, "LEFT ORBIT": 3, "RIGHT ORBIT": 4},
                           unseen)
    # the measured ids; the slingshot (no id reached the modes) left out and the bits given in order without it
    assert sw == [(2, 0x1, "Left outlane"), (6, 0x2, "Right target"), (3, 0x4, "Left orbit"), (4, 0x8, "Right orbit")]
    assert unseen == ["Left slingshot"]


def test_a_census_file_is_read_by_device_name(tmp_path):
    S = _s3port()
    f = tmp_path / "x.switch_ids"
    f.write_text("# a note\n87 RIGHT TARGET\n63 Left  orbit\n\n", encoding="utf-8")
    assert S.read_switch_ids(str(f)) == {"RIGHT TARGET": 87, "LEFT ORBIT": 63}


def test_the_census_rig_job_is_part_of_the_proof_recipe():
    census = (PROOFS / "s3census.sh").read_text(encoding="utf-8")
    assert "PROOF=census" in census and "shot_probe_mode.c" in census and ".switch_ids" in census
    assert "census)" in (PROOFS / "play.sh").read_text(encoding="utf-8")
    assert "pm_log" in (PROOFS / "shot_probe_mode.c").read_text(encoding="utf-8")
    assert '${2:-$HERE/place_probe_mode.c}' in (PROOFS / "build_probe.sh").read_text(encoding="utf-8")
    # the title's own switch names and bits for play.sh / s3proof.sh, sourced before the defaults
    env = (PROOFS / "titles" / "star_wars_2025_le.env").read_text(encoding="utf-8")
    assert "TRIGGER_BITS=${TRIGGER_BITS:-0x80}" in env and "SHOT_BITS=${SHOT_BITS:-0x800c00}" in env
    proof = (PROOFS / "s3proof.sh").read_text(encoding="utf-8")
    assert proof.index('titles/$TITLE.env') < proof.index("CARD=/mnt/d/")


# ---- the shipped port, proven on the rig --------------------------------------------------------------------------
def test_the_port_carries_the_census_ids_the_core_and_none_of_star_wars_elg_content():
    text = PORT.read_text(encoding="utf-8")
    e = _entries(text)
    for name in ("tick", "switch_hit", "switch_hit2", "hook_dispatch", "score_add", "agent_header", "agent_begin",
                 "multiball_serve", "balls_in_play"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    switches = {v.split(None, 1)[1]: int(k[1]) for k, v in e.items() if k[0] == "switch"}
    census = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            sid, name = line.split(None, 1)
            census[name] = int(sid)
    assert {n.upper(): i for n, i in switches.items()} == census and len(census) == 27
    assert switches["Right target"] == 87 and switches["Left orbit"] == 63 and switches["Right orbit"] == 83
    assert "Left slingshot" not in switches
    assert re.search(r"^text example_start_shot\s+Right target$", text, re.M)
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in body if l.split()[0] in ("lamp", "scene", "callout")]
    assert not [l for l in body if re.match(
        r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|mode_flag|held_coils|place_flag|"
        r"done_flag|coil_take|coil_give)", l)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-15 (PAD-1290)" in text


def test_the_app_lists_and_takes_the_port_for_the_spike3_card():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("star_wars_2025_le", "0_96_0", arch="a64") == str(PORT)
    assert MR.port_arch(str(PORT)) == "a64"
    prof = MP.profiles()["star_wars_2025_le_0_96_spike3"]
    assert prof.port == "spike3/star_wars_2025_le-0.96.port"
    assert "(Spike 3)" in prof.label
    assert not MW.port_unproven(str(PORT))
    shots = dict(prof.shots)
    assert len(shots) == 27 and prof.example_start_shot == "Right target"
    assert (shots["Right target"], shots["Left orbit"], shots["At-at target"], shots["Right orbit"]) == (
        0x80, 0x400, 0x800, 0x800000)


# ---- on the real programs -----------------------------------------------------------------------------------------
def _prog(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    with open(p, "rb") as f:
        if hashlib.sha1(f.read()).hexdigest() != SHA[game]:
            pytest.skip("%s.game is another build" % game)
    return p


def test_redrafting_with_the_census_gives_the_shipped_port():
    S = _s3port()
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("star_wars_2025_le"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "star_wars_2025_le", "0.96",
                                            S.read_switch_ids(str(CENSUS)))
    assert not core
    # PAD-1322's 64-bit switch_edge source (merged after this port was proven): the LE carries those lines once a run
    # proves them there, so the redraft is the shipped port plus exactly those, as for Pokemon LE and the Pro
    edge = {("site", "switch_edge"), ("value", "switch_record_reg"), ("value", "switch_id_at"),
            ("value", "switch_level_at"), ("value", "switch_desc_via"), ("value", "switch_flags_at"),
            ("value", "switch_polarity_at")}
    mine, shipped = _own(_entries(text)), _own(_entries(PORT.read_text(encoding="utf-8")))
    assert set(mine) - set(shipped) == edge
    assert {k: v for k, v in mine.items() if k not in edge} == shipped
    # the process record's exit hooks moved again (ELG 312): read off this program
    assert re.search(r"^value proc_exit_hooks\s+424\b", text, re.M)
