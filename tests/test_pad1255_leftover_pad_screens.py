"""PAD-1255: a card built from one an earlier PAD build made keeps that build's scenes.

DragonRR built a Godzilla card from DoomWalrus666's co-op card with co-op off: the HUD the new card kept carried the
old build's co-op pick screens and award cards, authored showing (the runtime hides them), and no co-op runtime ran to
hide them - FINALGOJI's award card, the last drawn, sat over the game all game. A Write now switches every such
screen off in place (scene_write.pad_hidden_patch, engine._pad_leftover_writes), and a build that puts its own
screens in cuts the old set out first (scene_write.without_pad), so the scene carries one set.
"""

import hashlib
import os

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import scene_tree
from pinball_decryptor.plugins.stern import scene_write as SW
from tests.test_stern_scene_tree import cls, fs, mat, node, s, sprite, u8, u32, u64

GROWN_HUD = ("C:/tmp/PAD-1243/rig/ovr/godzilla_le/assets/lcd/auto_loaded/32e6ae280ddaec08e203a02289bb39a04968e7b0/"
             "scene.radium")
STOCK_HUD_MD5 = "f9daed5a19aafc807bf9eb3c2def6c27"


def _art(nid, name, kids=None):
    """A root group like scene_write.screen()'s: a Sprite holding a picture (or *kids*)."""
    inner = kids if kids is not None else [node(nid + 1, name + "_Art", [u32(1) + cls(1) + u32(10)])]
    return node(nid, name, [u32(1) + cls(2) + u32(0x80000000 | (nid + 500)) + sprite(4, "", 1, inner)])


def _scene(root_kids):
    lib = [u32(3) + cls(1, "Bitmap") + u32(0x80000000 | 10) + u32(3) + s("") + u32(8) + u32(4)
           + u32(0x80000000 | 20) + u32(8) + u32(4) + u32(5) + s("") + u32(32) + bytes(range(16)) * 2,
           u32(4) + cls(2, "Sprite") + u32(0x80000000 | 11) + sprite(4, "", 1, [])]
    return (u8(1) + u64(len(lib)) + b"".join(lib) + u64(0) + u32(1360) + u32(768) + fs(30.0)
            + fs(0.2, 0.2, 0.2, 1.0) + sprite(2, "", 1, root_kids))


def _stock_kids():
    return [node(50, "TeslaSlideOut_Artbox", [u32(1) + cls(1) + u32(10)]),
            node(51, "BattleSlideOut_Artbox", [u32(1) + cls(1) + u32(10)], tracks=((1, mat(1, 10, 10)),))]


def _grown_kids():
    stock = _stock_kids()
    return [stock[0], _art(100, "PadCoop_1"), _art(110, "PadCoopAward_11"), _art(120, "PadCoopFinal"), stock[1]]


def _profiled(monkeypatch, data):
    """*data* registered as a measured stock scene (the profile's offsets are not read by without_pad)."""
    md5 = hashlib.md5(data).hexdigest()
    real = SW.PROFILES[STOCK_HUD_MD5]
    monkeypatch.setitem(SW.PROFILES, md5, SW.SceneProfile(**{**real.__dict__, "md5": md5, "size": len(data)}))


def _shown(data):
    return {n.name: [v for _f, v in n.keyframes] for n, _p, _d in scene_tree.parse(data).walk()}


def test_the_nodes_an_earlier_build_left_are_found_and_their_own_children_are_not():
    grown = _scene(_grown_kids())
    assert [n.name for n in SW.pad_nodes(grown)] == ["PadCoop_1", "PadCoopAward_11", "PadCoopFinal"]
    assert SW.pad_nodes(_scene(_stock_kids())) == []
    assert SW.pad_nodes(b"not a scene PadCoop_1") == []          # unreadable: nothing to say, never a raise


def test_the_left_screens_are_switched_off_in_place_and_nothing_else_changes():
    grown = _scene(_grown_kids())
    patch = SW.pad_hidden_patch(grown)
    assert len(patch) == 3 and all(v == b"\x00" for v in patch.values())
    out = bytearray(grown)
    for off, b in patch.items():
        out[off:off + 1] = b
    out = bytes(out)
    assert len(out) == len(grown)
    shown = _shown(out)
    assert shown["PadCoop_1"] == shown["PadCoopAward_11"] == shown["PadCoopFinal"] == [0]
    assert shown["TeslaSlideOut_Artbox"] == shown["BattleSlideOut_Artbox"] == [1]
    assert shown["PadCoop_1_Art"] == [1]                         # a hidden group hides its children
    assert SW.pad_hidden_patch(out) == {}                        # a second Write finds nothing left to do


def test_a_build_that_puts_screens_in_gets_the_stock_scene_back(monkeypatch):
    stock = _scene(_stock_kids())
    _profiled(monkeypatch, stock)
    grown = _scene(_grown_kids())
    assert SW.without_pad(grown) == stock
    hidden = bytearray(grown)
    for off, b in SW.pad_hidden_patch(grown).items():
        hidden[off:off + 1] = b
    assert SW.without_pad(bytes(hidden)) == stock                # this Write's own switch-off is cut with them
    assert SW.without_pad(stock) is stock


def test_a_cut_that_is_not_a_measured_scene_is_refused_with_words_that_say_why():
    grown = _scene(_grown_kids())
    assert SW.without_pad(grown) is None                         # the stock scene is not one the app measured
    with pytest.raises(SW.SceneWriteError, match="earlier build of this app.*PadCoop"):
        SW.profile_for(grown)
    logged = []
    assert E._pad_stock_scene(grown, "g/hud", lambda *a: logged.append(a)) is grown and not logged


def test_screens_below_the_root_are_switched_off_but_never_cut(monkeypatch):
    stock_like = _stock_kids()
    nested = _art(200, "Select_Root", kids=[node(201, "Gray", [u32(1) + cls(1) + u32(10)]),
                                            _art(210, "PadSel_kaiju_Lit")])
    data = _scene([stock_like[0], nested, stock_like[1]])
    assert [n.name for n in SW.pad_nodes(data)] == ["PadSel_kaiju_Lit"]
    assert len(SW.pad_hidden_patch(data)) == 1
    _profiled(monkeypatch, data)
    assert SW.without_pad(data) is None                          # nested: never guessed at


def test_the_engine_logs_and_cuts_on_the_modes_path(monkeypatch):
    stock = _scene(_stock_kids())
    _profiled(monkeypatch, stock)
    logged = []
    assert E._pad_stock_scene(_scene(_grown_kids()), "g/hud", lambda m, *a: logged.append(m)) == stock
    assert logged and "taken back out" in logged[0]
    assert E._pad_stock_scene(b"", "g/hud", lambda *a: None) == b""


def test_a_feed_only_build_names_a_title():
    """Found proving this ticket: a build whose one PAD feature was the score feed fell over on a None title."""
    feed = object()
    assert E._build_mode_profile([], [], "", (None,) * 10 + (feed,)) is feed   # PAD-1260 made it a helper


def test_the_real_co_op_hud_comes_back_byte_for_byte():
    """Godzilla LE 1.16's HUD as a co-op build left it (24 screens): switched off in place, then cut, it is the stock
    HUD's md5 again."""
    if not os.path.exists(GROWN_HUD):
        pytest.skip("no co-op build's HUD here: %s" % GROWN_HUD)
    grown = open(GROWN_HUD, "rb").read()
    assert len(SW.pad_nodes(grown)) == 24
    patch = SW.pad_hidden_patch(grown)
    assert len(patch) == 24
    hidden = bytearray(grown)
    for off, b in patch.items():
        hidden[off:off + 1] = b
    shown = {n.name: n.keyframes for n in scene_tree.parse(bytes(hidden)).root["kids"]}
    assert shown["PadCoopAward_11"] == [(1, 0)] and shown["BattleSlideOut_Artbox"] == [(1, 1)]
    assert hashlib.md5(SW.without_pad(bytes(hidden))).hexdigest() == STOCK_HUD_MD5
