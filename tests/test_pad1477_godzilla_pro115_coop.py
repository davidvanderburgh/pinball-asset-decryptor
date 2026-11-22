"""PAD-1477: co-op play, co-op characters and the start menu's play styles on Godzilla Pro 1.15.

The Pro 1.15 port lacked every co-op line, so none of it ran there. Its lines now come from this build's own program:
the co-op finder (portcoop.lines) and the start menu's (prolonged_comp.frame_lines), Pro 1.16's recipe drafted onto
it (each hooked function the same code as Pro 1.16's), and the characters' rule objects read off the code that loads
each one (every one 0x6d58 below Pro 1.16's)."""
import os

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_project as MP

PORTS = os.path.join(os.path.dirname(__file__), "..", "tools", "spike2_emu", "modes", "sdk", "ports")
ELF = os.environ.get("PAD_GODZILLA_PRO115_ELF", "C:/tmp/PAD-1449/godzilla_pro115.elf")

#: the co-op feature's lines: co-op play, characters, the co-op intro, the start menu's styles
COOP = ("coop_", "comp_menu_", "intro_", "language_player", "language_adjustment", "language_0", "language_1",
        "start_logo_", "start_film_clips", "serve_ball", "serve_music", "surface_", "challenge_score",
        "challenge_pages_", "bonus_loop_crop", "audit_add", "switch_hit")


def _entries(name):
    out = {}
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        for line in f:
            p = line.split("#")[0].split()
            if len(p) >= 3 and p[0] in ("site", "data", "value", "text"):
                out[(p[0], p[1])] = p[2:]
    return out


def test_every_coop_line_of_pro_116_is_on_pro_115():
    p15, p16 = _entries("godzilla_pro-1.15"), _entries("godzilla_pro-1.16")
    want = [k for k in p16 if k[1].startswith(COOP)]
    assert len(want) > 110
    assert [k for k in want if k not in p15] == []


def test_build_independent_values_are_pro_116s():
    p15, p16 = _entries("godzilla_pro-1.15"), _entries("godzilla_pro-1.16")
    # masks (the battles are rules 12-18 on both builds), fields, counts and the menu's indices and messages
    for k, v in p16.items():
        # (PAD-1449 round 7's comp_menu_overlay_* are the overlay singleton's words: addresses, each build's own)
        if k[0] == "value" and k[1].startswith(("coop_", "comp_menu_")) and not k[1].endswith("_obj") \
                and not k[1].startswith("comp_menu_overlay_"):
            assert p15[k] == v, k
    for name in ("intro_scene", "start_logo_scene", "bonus_loop_crop"):
        assert p15[("text", name)] == p16[("text", name)]


def test_rule_objects_are_this_builds():
    p15, p16 = _entries("godzilla_pro-1.15"), _entries("godzilla_pro-1.16")
    objs = [k for k in p16 if k[1].endswith("_obj") and k[1].startswith("coop_")] + \
        [("data", "language_player"), ("data", "intro_state"), ("data", "coop_count_jets_rule")]
    assert len(objs) == 14
    for k in objs:
        assert int(p16[k][0], 0) - int(p15[k][0], 0) == 0x6d58, k
    # the framework's own: the player up is the port's proven cur_player
    assert p15[("data", "coop_player")] == p15[("data", "cur_player")] == ["0x00708170"]
    assert p15[("site", "serve_ball")][0] == "0x001f01ac"


def test_the_app_offers_coop_on_pro_115():
    prof = next(p for p in MP.profiles().values() if p.game_dir == "godzilla_pro" and p.version == "1.15")
    assert CP.title_refusal(prof) == ""


@pytest.mark.skipif(not os.path.isfile(ELF), reason="no Godzilla Pro 1.15 program here (PAD_GODZILLA_PRO115_ELF)")
def test_lines_are_read_off_the_program():
    from pinball_decryptor.plugins.stern import portcoop, prolonged_comp
    from pinball_decryptor.plugins.stern.portchallenge import Elf
    p15 = _entries("godzilla_pro-1.15")
    found, notes = portcoop.lines(ELF)
    assert notes == []
    for line in found + [l for l in prolonged_comp.frame_lines(ELF) if not l.startswith("#")]:
        p = line.split("#")[0].split()
        assert p15[(p[0], p[1])] == p[2:], line
    e = Elf(open(ELF, "rb").read())
    for (kind, name), v in p15.items():          # every hooked site's two words are this program's
        if kind == "site" and name.startswith(COOP) and len(v) >= 3:
            at = int(v[0], 0)
            assert ("0x%08x" % e.word(at), "0x%08x" % e.word(at + 4)) == (v[1], v[2]), name
