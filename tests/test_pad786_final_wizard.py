"""A final wizard that does not end the game (PAD-786): plugins.stern.final_wizard, the Defaults tab's Final wizard
box and the build step that writes it.

The synthetic programs carry the three shapes the module reads, as Godzilla / Jurassic Park (a per-player word), James
Bond / Elvira / John Wick (a ``_PLAYED`` game flag) and Jaws (a condition switching on the game-play mode) have them:
the ball advance, the end of ball calling it, the one-word stub of it, the handler that starts the stub (the ender)
and the start refusal beside it.  The real builds below run where the card library is (David's PC); the emulator
proof is in the ticket (docs/plans/pad786_final_wizard_game_end.md).
"""
import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import final_wizard as F

TEXT_VA, TEXT_OFF, TEXT_SIZE = 0x8000, 0x1000, 0x1000
DATA_VA, DATA_OFF = 0x100000, 0x2000

ADV, END, STUB, ENDER, GETP, SIB, GETF, COND = (0x8000, 0x8100, 0x8200, 0x8300, 0x8400, 0x8500, 0x8600, 0x8700)
WORD_BASE = 0x7B0CFC
FLAG_ID = 5


def _b(at, to, cond=0xE, link=False):
    return (cond << 28) | ((0xB if link else 0xA) << 24) | (((to - (at + 8)) >> 2) & 0xFFFFFF)


def _movw(rd, va):
    """movw rd, #(low half of *va*)"""
    v = va & 0xFFFF
    return 0xE3000000 | (v >> 12) << 16 | rd << 12 | (v & 0xFFF)


def _movt(rd, va):
    """movt rd, #(high half of *va*)"""
    v = va >> 16
    return 0xE3400000 | (v >> 12) << 16 | rd << 12 | (v & 0xFFF)


PUSH, POP, BXLR = 0xE92D4010, 0xE8BD8010, 0xE12FFF1E


class _Prog:
    def __init__(self):
        self.text = bytearray(b"\x00\x00\xa0\xe1" * (TEXT_SIZE // 4))      # mov r0, r0
        self.data = bytearray(0x400)

    def put(self, va, *words):
        for k, w in enumerate(words):
            struct.pack_into("<I", self.text, va - TEXT_VA + 4 * k, w)

    def elf(self):
        hdr = bytearray(0x34)
        hdr[:4] = b"\x7fELF"
        struct.pack_into("<I", hdr, 0x1C, 0x34)
        struct.pack_into("<HH", hdr, 0x2A, 32, 2)
        ph = struct.pack("<8I", 1, TEXT_OFF, TEXT_VA, TEXT_VA, TEXT_SIZE, TEXT_SIZE, 5, 0x1000)
        ph += struct.pack("<8I", 1, DATA_OFF, DATA_VA, DATA_VA, len(self.data), len(self.data), 6, 0x1000)
        out = bytearray(DATA_OFF + len(self.data))
        out[:0x34] = hdr
        out[0x34:0x34 + len(ph)] = ph
        out[TEXT_OFF:TEXT_OFF + TEXT_SIZE] = self.text
        out[DATA_OFF:] = self.data
        return bytes(out)


def _frame(p):
    """The ball advance, the end of ball, its one-word stub and the ender's spawn block (at ENDER + 0x40)."""
    p.put(ADV, PUSH, 0xE3A00090, 0xE1A00000, 0xE3A00091, POP)
    p.put(END, PUSH, _b(END + 4, ADV, link=True), POP)
    p.put(STUB - 4, BXLR, _b(STUB, END))
    p.put(GETP, BXLR)
    use = ENDER + 0x40
    p.put(use, _movw(1, STUB), 0xE3A02000, _movt(1, STUB), 0xE3A00F5D, POP)
    return use


def _word_prog(sibling=True):
    p = _Prog()
    use = _frame(p)
    p.put(ENDER, PUSH, _b(ENDER + 4, GETP, link=True), _movw(3, WORD_BASE), _movt(3, WORD_BASE),
          0xE0830100, 0xE5904034, 0xE3540000, _b(ENDER + 28, use, cond=0x1), 0xE3A00001, POP)
    if sibling:
        p.put(SIB, PUSH, _b(SIB + 4, GETP, link=True), _movw(3, WORD_BASE), _movt(3, WORD_BASE),
              0xE0830100, 0xE5903034, 0xE3530000, 0x03A00001, POP)
    return p.elf()


def _flag_prog(name="FG_WIZARD_MODE_MULTIBALL_PLAYED", sibling=True):
    p = _Prog()
    use = _frame(p)
    names = ["FG_INVALID", "FG_A", "FG_B", "FG_C", "FG_D", name]
    ptrs, at = [], 0x100
    for n in names:
        p.data[at:at + len(n) + 1] = n.encode() + b"\0"
        ptrs.append(DATA_VA + at)
        at += (len(n) + 4) & ~3
    struct.pack_into("<%dI" % len(ptrs), p.data, 0, *ptrs)
    p.put(GETF, BXLR)
    p.put(ENDER, PUSH, 0xE3A00000 | FLAG_ID, _b(ENDER + 8, GETF, link=True), 0xE3500000,
          _b(ENDER + 16, use, cond=0x1), 0xE3A00001, POP)
    if sibling:
        p.put(SIB, PUSH, 0xE3A00000 | FLAG_ID, _b(SIB + 8, GETF, link=True), 0xE3500000, 0x03A00001, POP)
    return p.elf()


def _state_prog():
    p = _Prog()
    use = _frame(p)
    p.put(ENDER, PUSH, _b(ENDER + 4, COND, link=True), 0xE2504000, _b(ENDER + 12, use, cond=0x1),
          0xE3A00001, POP)
    case = COND + 0x40
    p.put(COND, PUSH, 0xE353000B, 0x979FF103, _b(COND + 12, COND + 0x60), case, COND + 0x60)
    p.put(case, 0xE590009C, 0xE2400014, 0xE16F0F10, 0xE1A002A0, POP)
    p.put(COND + 0x60, 0xE3A00000, POP)
    return p.elf()


def _word_at(elf, va):
    return struct.unpack_from("<I", elf, TEXT_OFF + va - TEXT_VA)[0]


def test_a_word_title_clears_the_ender_and_the_refusal():
    elf = _word_prog()
    p = F.plan(elf)
    assert p["shape"] == F.WORD
    assert [v for v, _o, _n in p["sites"]] == [ENDER + 20, SIB + 20]
    out = F.patched_bytes(elf, p)
    assert len(out) == len(elf)
    assert _word_at(out, ENDER + 20) == 0xE3A04000 and _word_at(out, SIB + 20) == 0xE3A03000
    assert F.plan(out) is None                      # nothing left to patch


def test_a_flag_title_needs_a_played_flag_and_its_refusal():
    elf = _flag_prog()
    p = F.plan(elf)
    assert p["shape"] == F.FLAG and p["flag"] == "FG_WIZARD_MODE_MULTIBALL_PLAYED"
    assert [v for v, _o, _n in p["sites"]] == [ENDER + 8, SIB + 8]
    out = F.patched_bytes(elf, p)
    assert _word_at(out, ENDER + 8) == 0xE3A00000 and _word_at(out, SIB + 8) == 0xE3A00000
    # a flag that is not a "played" mark (a challenge game's, say) is never touched
    assert F.plan(_flag_prog(name="FG_PLAYER_CHALLENGE_MODE_ACTIVE")) is None


def test_no_refusal_beside_it_offers_nothing():
    assert F.plan(_word_prog(sibling=False)) is None
    assert F.plan(_flag_prog(sibling=False)) is None


def test_a_state_title_clears_only_the_standard_games_case():
    elf = _state_prog()
    p = F.plan(elf)
    assert p["shape"] == F.STATE
    assert [v for v, _o, _n in p["sites"]] == [COND + 0x40]
    assert _word_at(F.patched_bytes(elf, p), COND + 0x40) == 0xE3A00000


def test_other_programs_offer_nothing_and_patching_them_refuses():
    assert F.plan(b"not an elf") is None
    p = _Prog()
    _frame(p)
    plain = p.elf()                                 # a stub but no ender that starts it
    assert F.plan(plain) is None
    with pytest.raises(ValueError):
        F.patched_bytes(plain)


def test_a_site_that_moved_is_refused():
    elf = _word_prog()
    p = F.plan(elf)
    bad = bytearray(elf)
    struct.pack_into("<I", bad, TEXT_OFF + ENDER + 20 - TEXT_VA, 0xE1A00000)
    with pytest.raises(ValueError):
        F.patched_bytes(bytes(bad), p)


def test_the_build_step_patches_or_says_why_not():
    from pinball_decryptor.plugins.stern.explorer import CardImage
    logs = []

    def log(text, level):
        logs.append((level, text))
    out = CardImage._with_final_wizard(_word_prog(), log)
    assert F.plan(out) is None and logs[-1][0] == "info"
    plain = b"x" * 64
    assert CardImage._with_final_wizard(plain, log) == plain
    assert logs[-1][0] == "warning"


# ------------------------------------------------------ the Defaults tab
def _staged(folder):
    p = os.path.join(str(folder), ".staged_changes.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load(w, project, wizard):
    svc = w.window.service("defaults")
    w.run(lambda: w.window.write_assets_var.set(str(project)))
    res = ("ok", object(), 3, "/game", [], "C:/card.raw", None, [], None, None, wizard)
    w.run(lambda: svc._apply_result(res))
    return svc


def test_the_box_shows_only_on_a_build_it_knows(tmp_path):
    from tests.webui_harness import web_app
    project = tmp_path / "proj"
    project.mkdir()
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _load(w, project, None)
        assert w.state("defaults")["wizard_offer"] is False
        assert w.call("defaults.final_wizard_set", True) is False
        assert "final_wizard" not in _staged(project)
        _load(w, project, {"shape": F.WORD, "sites": []})
        st = w.state("defaults")
        assert st["wizard_offer"] is True and st["wizard_on"] is False


def test_ticking_it_stages_for_the_build_and_reset_clears_it(tmp_path):
    from tests.webui_harness import web_app
    project = tmp_path / "proj"
    project.mkdir()
    plan = {"shape": F.FLAG, "sites": []}
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        svc = _load(w, project, plan)
        assert w.call("defaults.final_wizard_set", True) is True
        assert _staged(project)["final_wizard"] == "plays_on"
        assert w.state("defaults")["wizard_on"] is True
        assert svc.staged_final_wizard(str(project)) is True
        assert w.window.staged_final_wizard(str(project)) is True
        _load(w, project, plan)
        assert w.state("defaults")["wizard_on"] is True
        assert w.call("defaults.final_wizard_set", False) is True
        assert "final_wizard" not in _staged(project)
        w.call("defaults.final_wizard_set", True)
        w.call("defaults.reset")
        assert "final_wizard" not in _staged(project)
        assert w.state("defaults")["wizard_on"] is False


def test_packs_and_transfers_carry_it():
    from pinball_decryptor.core import mod_transfer, modpack
    assert "final_wizard" in modpack._EXTRA_SCALARS
    assert "final_wizard" in mod_transfer._TOGGLE_KEYS


# ------------------------------------------------------ the real builds
_LIB = "D:/Pinball/images/Stern/spike2"
#: what each newest build offers (None: nothing), checked against its card's game program
_EXPECT = {
    "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw": (F.WORD, None),
    "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw": (F.WORD, None),
    "jurassic_park_le-1_16_0.Release.8G.sdcard.raw": (F.WORD, None),
    "jurassic_park_pro-1_16_0.Release.8G.sdcard.raw": (F.WORD, None),
    "james_bond_le-1_06_0.Release.16G.sdcard.raw": (F.FLAG, "FG_WIZARD_MODE_MULTIBALL_PLAYED"),
    "james_bond_pro-1_06_0.Release.16G.sdcard.raw": (F.FLAG, "FG_WIZARD_MODE_MULTIBALL_PLAYED"),
    "elvira3-1_13_0.Release.16G.sdcard.raw": (F.FLAG, "FG_WILD_MARKET_VALUE_PLAYED"),
    "john_wick_le-1_02_0.Release.16G.sdcard.raw": (F.FLAG, "FG_SPECIAL_ASSIGNMENT_MODE_PLAYED"),
    "john_wick_pro-1_02_0.Release.16G.sdcard.raw": (F.FLAG, "FG_SPECIAL_ASSIGNMENT_MODE_PLAYED"),
    "jaws_le-1_02_0.Release.16G.sdcard.raw": (F.STATE, None),
    "jaws_pro-1_02_0.Release.16G.sdcard.raw": (F.STATE, None),
    # the same ender ends a challenge game, not a final wizard: nothing offered
    "avengers_infinity_le-1_10_0.Release.8G.sdcard.raw": None,
    "james_bond_60th_le-1_11_0.Release.8G.sdcard.raw": None,
    "led_zeppelin_le-1_22_0.Release.8G.sdcard.raw": None,
    "metallica_spike-1_04_0.Release.32G.sdcard.raw": None,
    "rush_le-1_19_0.Release.16G.sdcard.raw": None,
    "sword_of_rage_le-1_19_0.Release.8G.sdcard.raw": None,
    # no ender at all
    "deadpool_pro-1_16_0.Release.8G.sdcard.raw": None,
    "stranger_things_le-1_13_0.Release.8G.sdcard.raw": None,
}


def _program(card):
    from pinball_decryptor.plugins.stern.explorer import CardImage
    c = CardImage(card)
    _t, part, path = c.adjustment_table()
    return c.read_firmware(part, path)


@pytest.mark.parametrize("card", sorted(_EXPECT))
def test_every_newest_build(card):
    path = os.path.join(_LIB, card)
    if not os.path.isfile(path):
        pytest.skip("the card library is not on this machine")
    elf = bytes(_program(path))
    p = F.plan(elf)
    want = _EXPECT[card]
    if want is None:
        assert p is None
        return
    assert p and p["shape"] == want[0] and p.get("flag") == want[1]
    out = F.patched_bytes(elf, p)
    assert len(out) == len(elf) and F.plan(out) is None
