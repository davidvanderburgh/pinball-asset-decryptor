"""PAD-1506: Pokemon Pro 0.87's Spike 3 port, carried from the emulator-proven Pokemon LE 0.87 port.

The Pro is its own program (sha1 6ef2e77c..., the LE's 4ea25811...), the same title and build: s3port.py paired 111,066
of its functions with the LE's and placed every core entry; the three it cannot place (the high-score gate's bl, the
message table, the challenge high-score table) were found on the Pro's own code. Its start menu, message ids and flag
ids are the LE's; its switch lines are its own (no Bowl opto, Subway enter or Left eject opto; a Psyduck target), each
id its device-table rank, as the rig's census measured. The rig proofs (docs/plans/spike3_modes.md, "Pokemon Pro 0.87")
are in mode_project's tables; these tests keep the port and the tables in step. The checks against the program itself
run when PAD_S3_PROGRAMS names a folder holding pokemon_pro-0.87.game (the card's /games/pokemon_pro/game).
"""
import os
import pathlib
import struct

import pytest

from pinball_decryptor.plugins.stern import idle_pause as IP
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import prolonged_comp as PC
from pinball_decryptor.plugins.stern import spike3_games as G

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTS = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3"
TITLES = ROOT / "tools" / "spike3_emu" / "proofs" / "titles"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
LE, PRO = "pokemon_le-0.87", "pokemon_pro-0.87"
#: the LE's switches the Pro's playfield does not have, and the one it has that the LE does not
LE_ONLY = {"Bowl opto", "Subway enter", "Left eject opto"}
PRO_ONLY = {"Psyduck target"}


def _port(name):
    return MP.read_port(str(PORTS / (name + ".port")))


def _switch_names(port):
    return {rec[-1] if isinstance(rec, (tuple, list)) else rec for rec in port["switch"].values()}


def test_every_line_of_the_les_port_is_carried():
    le, pro = _port(LE), _port(PRO)
    for kind in ("site", "data", "scene"):
        assert set(le[kind]) == set(pro[kind]), kind
    assert le["value"] == pro["value"]             # the start menu, messages, flags and layouts are the LE's
    assert le["scene"] == pro["scene"]             # the clip bank: 60ed7e50, its scene.radium the LE's byte for byte
    assert "switch_edge" not in pro["site"]        # as the LE: not carried


def test_the_switch_lines_are_the_pros_own_and_the_censuss():
    le, pro = _port(LE), _port(PRO)
    text = (PORTS / (PRO + ".port")).read_text(encoding="utf-8")
    lines = {}
    for ln in text.splitlines():
        if ln.startswith("switch "):
            f = ln.split(None, 3)
            lines[f[3].strip().upper()] = int(f[1])
    le_names = {ln.split(None, 3)[3].strip() for ln in (PORTS / (LE + ".port")).read_text(encoding="utf-8").splitlines()
                if ln.startswith("switch ")}
    pro_names = {n.title() for n in lines}
    assert {n.upper() for n in le_names} - set(lines) == {n.upper() for n in LE_ONLY}
    assert set(lines) - {n.upper() for n in le_names} == {n.upper() for n in PRO_ONLY}
    measured = {}
    for ln in (TITLES / (PRO + ".switch_ids")).read_text(encoding="utf-8").splitlines():
        if ln and not ln.startswith("#"):
            i, name = ln.split(" ", 1)
            measured[name] = int(i)
    assert len(measured) == 38 and len(lines) == 43
    for name, i in measured.items():
        assert lines[name] == i, name                # every switch that reached the modes, on its own id
    assert set(lines) - set(measured) == {"LEFT SLINGSHOT", "RIGHT SLINGSHOT", "TOP POP BUMPER", "BOT POP BUMPER",
                                          "RIGHT EJECT"}
    assert pro_names and len(pro["switch"]) == 43 and len(le["switch"]) == 45


def test_the_head_names_the_program():
    head = (PORTS / (PRO + ".port")).read_text(encoding="utf-8")
    assert "6ef2e77c1b01da92503022b8095b17403cd3d221" in head
    assert "\ngame           pokemon_pro\nversion        0.87\n" in head
    assert "NOT RUN" not in head


def test_the_app_offers_on_the_pro_what_it_offers_on_the_le():
    a = MP.profile_from_port(str(PORTS / (LE + ".port")))
    b = MP.profile_from_port(str(PORTS / (PRO + ".port")))
    assert sorted(dict(a.cannot)) == sorted(dict(b.cannot))
    for part in ("ball_save", "multiball", "challenge", "clip"):
        assert b.can(part), dict(b.cannot).get(part)
    assert PC.port_ready(_port(PRO))
    key = PRO + "/spike3"
    for table in (MP.MULTIBALL_PROVEN, MP.BALL_SAVE_PROVEN, MP.SWITCH_SHOTS_PROVEN, MP.SPARE_IO_PROVEN):
        assert key in table
    assert "PENDING" not in MP.CHALLENGE_MENU_FRAME_PROVEN[key]
    assert MP.TITLE_SCENES[key] == dict(bank="32eb5f813905cf4b00a0304c7195bbb4", clip_proven=True)
    assert "PENDING" not in (ROOT / "pinball_decryptor" / "plugins" / "stern" / "mode_project.py").read_text(
        encoding="utf-8").split('"pokemon_pro-0.87/spike3": dict(', 1)[1].split("\n", 1)[0]


def test_the_card_is_named_pokemon_pro():
    key = G.spike3_key_for_path("cards/pokemon_pro-0_87_0_spike3.Release.64G.sdcard-secure.raw")
    assert key == "pokemon_pro"
    assert G.spike3_display(key) == "Pokemon PRO (Spike 3)"
    assert G.spike3_key_for_path("pokemon_le-0_87_0_spike3.Release.64G.sdcard-secure.raw") == "pokemon_le"
    assert MP.title_label("pokemon_pro", "0.87.0") == "Pokemon Pro 0.87"
    assert "pokemon_pro" in IP.NO_SETTING_TITLES      # no ALLOW INACTIVITY TO PAUSE TIMERS, as the LE


def _raw():
    path = os.path.join(PROGS, PRO + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % PRO)
    return open(path, "rb").read()


def test_the_sites_are_the_programs_own_words():
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    prog = S3R.Program(_raw())
    for name, rec in _port(PRO)["site"].items():
        va, w0, w1 = rec[:3]
        if name == "dynamic_cast":                 # a PLT stub, outside .text's words
            continue
        assert struct.unpack_from("<2I", prog.raw, prog.off(va)) == (w0, w1), name


def test_the_start_menu_messages_and_tables_are_the_ones_measured():
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    from pinball_decryptor.plugins.stern.portcoop import message_lines_a64
    raw = _raw()
    prog = S3R.Program(raw)
    port = _port(PRO)
    va = port["site"]["comp_menu_frame"][0]

    def w(at, n=1):
        return struct.unpack_from("<%dI" % n, prog.raw, prog.off(at))

    assert w(va) == (0xB874DAFA,)                  # ldr w26, [x23, w20, sxtw #2]: the index under cursor w20
    assert 0xB9008FE1 in w(va - 0x70, 8)           # str w1, [sp, #0x8c]: the count - 1, once, before the loop
    assert w(va - 0x14) == (0xB9408FE1,)           # ldr w1, [sp, #0x8c]: the right press wraps at the last index
    assert PC.card_lines(raw) == (17, 1920, 1915)  # Competition's flag, COMPETITION, STANDARD: the LE's
    assert message_lines_a64(raw)[0].split()[2] == "0x%08x" % port["data"]["message_table"]
    gate = port["site"]["challenge_scores_gate"][0]
    assert w(gate - 0xC) == (0x52800B60,)          # mov w0, #0x5b: bus id 91 for the bl to the hook dispatch
    hook = port["site"]["hook_dispatch"][0]
    off = (w(gate)[0] & 0x3FFFFFF) - (1 << 26)
    assert gate + 4 * off == hook
    table = port["data"]["challenge_scores_table"]
    assert prog.rel.get(port["data"]["challenge_scores_count"] - 8) == table   # its slot, beside the count
