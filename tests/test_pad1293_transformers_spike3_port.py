"""PAD-1293: the Spike 3 port of Transformers LE 0.96, drafted from Star Wars ELG 1.10's proven Spike 3 port.

Its switch lines carry ids MEASURED on the rig (proofs/s3census.sh): all 37 switch lines reached the modes, each id 3
below the switch's rank in the device table, so the rank-numbered draft would have put every press on the wrong shot.
The rig then proved a mode started on Megatron target left x3, scored through the game's score_add and ended on its
clock; a mode's ball save and its control; a mode's 3-ball multiball; and a card the app Wrote booted with its own hook
and played its mode.

The redraft test runs when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1 ceb8d70b...) and
`transformers_mtmte_le.game` (sha1 a3b67ca1...), each a card's games/<game>/game.
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
PORT = PORTS3 / "transformers_mtmte_le-0.96.port"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
CENSUS = PROOFS / "titles" / "transformers_mtmte_le-0.96.switch_ids"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "transformers_mtmte_le": "a3b67ca1f27d43de47bb15f73cc2a7808ea36439"}
KEY = "transformers_mtmte_le-0.96/spike3"


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


def _census():
    out = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            sid, name = line.split(None, 1)
            out[name] = int(sid)
    return out


# ---- the shipped port, proven on the rig --------------------------------------------------------------------------
def test_the_port_carries_the_census_ids_the_core_and_none_of_star_wars_elg_content():
    text = PORT.read_text(encoding="utf-8")
    e = _entries(text)
    assert ("game", "transformers_mtmte_le") in e and ("version", "0.96") in e
    for name in ("tick", "switch_hit", "switch_hit2", "switch_edge", "hook_dispatch", "score_add", "agent_header",
                 "agent_begin", "multiball_serve", "balls_in_play"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    switches = {v.split(None, 1)[1]: int(k[1]) for k, v in e.items() if k[0] == "switch"}
    census = _census()
    # every one of the 37 drafted switches reached the modes, each 3 below its device-table rank
    assert {n.upper(): i for n, i in switches.items()} == census and len(census) == 37
    assert switches["Megatron target left"] == 41 and switches["Right orbit"] == 40
    assert switches["Center loop"] == 82 and switches["Left orbit"] == 90
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in body if l.split()[0] in ("lamp", "scene", "callout")]
    assert not [l for l in body if re.match(
        r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|mode_flag|held_coils|place_flag|"
        r"done_flag|coil_take|coil_give)", l)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-16 (PAD-1293)" in text
    assert "a3b67ca1f27d43de47bb15f73cc2a7808ea36439" in text


def test_the_proof_title_names_the_ports_bits():
    env = (PROOFS / "titles" / "transformers_mtmte_le.env").read_text(encoding="utf-8")
    assert "PORTNAME=${PORTNAME:-transformers_mtmte_le-0.96.port}" in env
    assert "TRIGGER_SW=${TRIGGER_SW:-MEGATRON TARGET LEFT}" in env and "TRIGGER_BITS=${TRIGGER_BITS:-0x4}" in env
    # Right orbit 0x2, Center loop 0x2000000, Left orbit 0x200000000 - the port's own lines
    e = _entries(PORT.read_text(encoding="utf-8"))
    bits = {v.split(None, 1)[1]: int(v.split()[0], 16) for k, v in e.items() if k[0] == "switch"}
    assert bits["Megatron target left"] == 0x4
    assert bits["Right orbit"] | bits["Center loop"] | bits["Left orbit"] == 0x202000002
    assert "SHOT_BITS=${SHOT_BITS:-0x202000002}" in env
    assert "\r" not in env


def test_the_app_lists_and_takes_the_port_for_the_spike3_card():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("transformers_mtmte_le", "0_96_0", arch="a64") == str(PORT)
    assert MR.port_arch(str(PORT)) == "a64"
    prof = MP.profiles()["transformers_mtmte_le_0_96_spike3"]
    assert prof.port == "spike3/transformers_mtmte_le-0.96.port"
    assert prof.label == "Transformers LE 0.96 (Spike 3)"
    assert not MW.port_unproven(str(PORT))
    shots = dict(prof.shots)
    assert len(shots) == 37
    assert (shots["Megatron target left"], shots["Right orbit"], shots["Center loop"], shots["Left orbit"]) == (
        0x4, 0x2, 0x2000000, 0x200000000)


def test_what_the_rig_proved_is_offered_and_the_rest_is_not():
    from pinball_decryptor.plugins.stern import mode_project as MP
    for table in (MP.BALL_SAVE_PROVEN, MP.MULTIBALL_PROVEN, MP.SWITCH_SHOTS_PROVEN, MP.SWITCH_EDGE_PROVEN):
        assert KEY in table
    # the game's own multiball never started on the rig, so a mode never waited for one
    assert KEY not in MP.STACK_BALLS_PROVEN
    cannot = {k for k, _why in MP.profiles()["transformers_mtmte_le_0_96_spike3"].cannot}
    assert not cannot & {"ball_save", "multiball"}
    assert {"stack", "lights", "screen", "place", "done"} <= cannot


def test_the_card_reads_as_transformers_le():
    from pinball_decryptor.plugins.stern import spike3_games as S3G
    card = "transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw"
    assert S3G.spike3_key_for_path(card) == "transformers_mtmte_le"
    assert S3G.spike3_display("transformers_mtmte_le") == "Transformers LE (Spike 3)"


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
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("transformers_mtmte_le"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "transformers_mtmte_le", "0.96",
                                            S.read_switch_ids(str(CENSUS)))
    assert not core
    # (the lines the port has from elsewhere: PAD-1326's co-op (portcoop) and PAD-1327's start menu, measured by hand)
    def own(entries):
        return {k: v for k, v in entries.items() if not k[1].startswith(("message_", "coop_", "comp_menu_", "challenge_", "game_scores", "audit_add"))}
    assert own(_entries(text)) == own(_entries(PORT.read_text(encoding="utf-8")))
    assert re.search(r"^value proc_exit_hooks\s+392\b", text, re.M)
