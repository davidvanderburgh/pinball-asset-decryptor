"""PAD-1292: Walking Dead Remastered LE 0.92's Spike 3 port and its emulator proofs.

The rig (slot 93, hidden, muted) proved its multiball and ball save; nothing has proven a mode of ours waiting out
WDR's own multiball, so that stays greyed. Its proof mode files are ELG's with WDR's own switch masks.
"""
import pathlib
import re

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORT = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3" / "walking_dead_remastered_le-0.92.port"
MODES = ROOT / "tools" / "spike3_emu" / "proofs" / "modes"
KEY = "walking_dead_remastered_le-0.92/spike3"


def test_the_proven_features_are_in_their_tables_and_the_unproven_one_is_not():
    assert KEY in MP.MULTIBALL_PROVEN
    assert KEY in MP.BALL_SAVE_PROVEN
    assert KEY not in MP.STACK_BALLS_PROVEN
    # the Spike 2 build's proofs never stand for its Spike 3 twin
    assert "walking_dead_remastered_le-0.92" not in MP.MULTIBALL_PROVEN


def test_the_modes_tab_offers_multiball_and_ball_save_on_the_wdr_card_and_greys_the_stack():
    greyed = {k: v for k, v in MP.profile_from_port(str(PORT)).cannot}
    assert "multiball" not in greyed and "ball_save" not in greyed
    assert "has not yet seen" in greyed["stack"]


def _mask(port_text, name):
    m = re.search(r"^switch\s+\d+\s+(0x[0-9a-f]+)\s+%s\s*$" % re.escape(name), port_text, re.M | re.I)
    return int(m.group(1), 16)


def test_the_wdr_proof_files_use_wdrs_own_shots():
    text = PORT.read_text(encoding="utf-8")
    trig = _mask(text, "Tower target")
    shots = _mask(text, "Left loop") | _mask(text, "Right loop") | _mask(text, "Right spinner")
    for f in ("mb_wdr.cfg", "save_wdr.cfg", "savectl_wdr.cfg", "stackmb_wdr.cfg"):
        cfg = (MODES / f).read_text(encoding="utf-8")
        assert re.search(r"^trigger\s+0x%x 3$" % trig, cfg, re.M), f
        assert re.search(r"^shots\s+0x%x$" % shots, cfg, re.M), f


def test_the_wdr_port_carries_no_mode_books_of_another_title():
    text = PORT.read_text(encoding="utf-8")
    assert not re.search(r"^value (done_flag|place_flag)_", text, re.M)
    assert not re.search(r"^text (done_name|block_name)_", text, re.M)
