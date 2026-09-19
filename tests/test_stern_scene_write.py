"""Tests for :mod:`pinball_decryptor.plugins.stern.scene_write`.

The bar is BYTE-EXACTNESS against nodes the game itself wrote. A tolerant parser
accepting our output proves nothing (the first version of this module passed exactly
that test and the game aborted on its scenes). So the emitters are checked against
real stock nodes of Godzilla Pro 1.15 - a Bitmap leaf, a Sprite group with its child,
and a Text node, in two files whose type ids differ - and ``add_screen`` must
reproduce, from the stock HUD scene, the splice that was proven in the emulator.

Those need the stock scene files, which are game data and live outside the repo;
they are skipped where absent (CI). The rest covers the layout and the refusals
structurally, with synthetic bytes. Desk work only: no card, no emulator, no rig.
"""

import hashlib
import os
import struct

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import scene_write as SW

CORPUS = r"C:\tmp\radium_scene_re\godzilla_pro_1_15"
HUD = os.path.join(CORPUS, "auto_loaded_32e6ae280ddaec08e203a02289bb39a04968e7b0.radium")
ATTRACT = os.path.join(CORPUS, "demand_loaded_394c4a037fb26e12f536c42b2677bfed831f5c98.radium")


def _read(path, md5):
    if not os.path.exists(path):
        pytest.skip("stock scene not present: %s" % path)
    data = open(path, "rb").read()
    assert hashlib.md5(data).hexdigest() == md5
    return data


# ---- a minimal reader for what node() writes ----------------------------------------
def _parse_node(b, o=0):
    ptr = struct.unpack_from("<I", b, o)[0]
    o += 4
    n = struct.unpack_from("<Q", b, o)[0]
    name = b[o + 8:o + 8 + n].decode("latin1")
    o += 8 + n
    flag = struct.unpack_from("<I", b, o)[0]
    o += 4
    k = struct.unpack_from("<Q", b, o)[0]
    o += 8
    keys = [struct.unpack_from("<IB", b, o + 5 * i) for i in range(k)]
    o += 5 * k
    assert struct.unpack_from("<Q", b, o)[0] == 0
    o += 8
    t = struct.unpack_from("<Q", b, o)[0]
    o += 8
    tracks = []
    for _ in range(t):
        tracks.append((struct.unpack_from("<I", b, o)[0], struct.unpack_from("<16f", b, o + 4)))
        o += 68
    c = struct.unpack_from("<Q", b, o)[0]
    comp = struct.unpack_from("<3I", b, o + 8)
    return dict(ptr=ptr, name=name, flag=flag, keyframes=keys, tracks=tracks, n_components=c,
                component=comp, body_at=o + 20)


# ---- encoding and layout -------------------------------------------------------------
def test_strings_are_u64_length_prefixed_latin1():
    assert SW.string("AB") == struct.pack("<Q", 2) + b"AB"
    assert SW.string("") == b"\0" * 8


def test_matrix_is_column_major_with_translation_at_12_and_13():
    m = struct.unpack("<16f", SW.matrix(sx=2.0, sy=0.5, tx=360.0, ty=200.0))
    assert (m[0], m[5], m[10], m[15]) == (2.0, 0.5, 1.0, 1.0)
    assert (m[12], m[13]) == (360.0, 200.0)
    assert len(SW.matrix()) == 64


def test_node_writes_the_grammar_in_order():
    body = b"BODY"
    b = SW.node(SW.FLAG | 7, "Thing", 3, [(1, 1), (110, 0)], [(1, SW.matrix(tx=5.0))],
                [(1, 2, SW.FLAG | 8, body)])
    p = _parse_node(b)
    assert p["ptr"] == SW.FLAG | 7 and p["name"] == "Thing" and p["flag"] == 3
    assert p["keyframes"] == [(1, 1), (110, 0)]
    assert p["tracks"][0][0] == 1 and p["tracks"][0][1][12] == 5.0
    assert p["n_components"] == 1 and p["component"] == (1, 2, SW.FLAG | 8)
    assert b[p["body_at"]:p["body_at"] + 4] == body
    assert b.endswith(body + b"\0" * 8)                         # the frame map, empty


def test_node_refuses_a_matrix_that_is_not_64_bytes():
    with pytest.raises(SW.SceneWriteError):
        SW.node(SW.FLAG | 1, "x", 1, [], [(1, b"\0" * 60)], [])


def test_sprite_body_holds_its_children_inline_then_two_empty_tails():
    kid = b"KID1"
    b = SW.sprite_body(19, [kid, kid], frames=20)
    assert struct.unpack_from("<I", b, 0)[0] == 19
    assert struct.unpack_from("<Q", b, 4)[0] == 0                # empty name
    assert struct.unpack_from("<I", b, 12)[0] == 20              # frame count
    assert struct.unpack_from("<Q", b, 16)[0] == 2               # children
    assert b[24:32] == kid + kid
    assert b[32:] == b"\0" * 16                                   # u64, then zero labels


def test_texture_new_checks_the_blob_length_per_format():
    blob3 = b"\0" * (8 * 4)                                       # 8x4 BC3 = 1 byte/px
    t = SW.texture_new(0x10, 8, 4, blob3)
    assert struct.unpack_from("<4I", t, 0) == (SW.FLAG | 0x10, 8, 4, SW.BC3)
    assert struct.unpack_from("<Q", t, 16)[0] == 0                # the empty string
    assert struct.unpack_from("<I", t, 24)[0] == len(blob3)
    SW.texture_new(0x10, 8, 4, b"\0" * 16, fmt=SW.BC1)            # BC1 = half
    with pytest.raises(SW.SceneWriteError):
        SW.texture_new(0x10, 8, 4, b"\0" * 31)


def test_text_body_carries_the_string_and_the_font_twice_more():
    b = SW.text_body(5, (0.0, -40.0, 640.0, 48.0), (1, 1, 1, 1), "OURS", 9, "GameFont_Primary",
                     1, (2.0, 0.0), 1, 1)
    assert b.count(b"GameFont_Primary") == 1
    assert b"OURS" in b
    tail = struct.pack("<I", 9) + struct.pack("<Q", 1) + SW.string("GameFont_Primary") + struct.pack("<I", 9)
    assert tail in b
    assert b.endswith(struct.pack("<Q", 1) + struct.pack("<I", 9) + b"\x01" + struct.pack("<I", 1))


# ---- the splice and its refusals, on synthetic bytes ---------------------------------
def _fake_scene(monkeypatch, used_id=None):
    """Bytes that satisfy a profile: a root frame count and child count, and a root
    child's ptr id and name at the insertion point."""
    count_at, at = 64, 200
    data = bytearray(b"\x11" * 400)
    struct.pack_into("<I", data, count_at - 4, 1)
    struct.pack_into("<Q", data, count_at, 3)
    struct.pack_into("<I", data, at, SW.FLAG | 0xD3)
    struct.pack_into("<Q", data, at + 4, 5)
    data[at + 12:at + 17] = b"Other"
    if used_id is not None:
        struct.pack_into("<I", data, 300, SW.FLAG | used_id)
    data = bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    real = SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"]
    prof = SW.SceneProfile(**{**real.__dict__, "md5": md5, "size": len(data), "root_count_at": count_at,
                              "root_count": 3, "insert_at": at, "insert_before": (SW.FLAG | 0xD3, "Other")})
    monkeypatch.setitem(SW.PROFILES, md5, prof)
    return data, prof


def _art(w=16, h=8):
    a = np.zeros((h, w, 4), dtype=np.uint8)
    a[..., 1] = 200
    a[..., 3] = 255
    return a


def test_add_screen_splices_before_the_profiled_child_and_counts_it(monkeypatch):
    data, p = _fake_scene(monkeypatch)
    new, info = SW.add_screen(data, "Mode_Screen", _art(), "HELLO")
    group = new[p.insert_at:p.insert_at + info["node_bytes"]]
    assert new[:p.root_count_at] == data[:p.root_count_at]
    assert struct.unpack_from("<Q", new, p.root_count_at)[0] == 4
    assert new[p.root_count_at + 8:p.insert_at] == data[p.root_count_at + 8:p.insert_at]
    assert new[p.insert_at + info["node_bytes"]:] == data[p.insert_at:]
    assert _parse_node(group)["name"] == "Mode_Screen"
    assert b"Mode_Screen_Art" in group and b"Mode_Screen_Words" in group and b"HELLO" in group
    assert info["screen_node"] == "Mode_Screen"
    assert info["screen_text"] == "Mode_Screen.Mode_Screen_Words"
    assert info["md5"] == hashlib.md5(new).hexdigest()


def test_add_screen_refuses_a_scene_nobody_measured():
    with pytest.raises(SW.SceneWriteError, match="no measured profile"):
        SW.add_screen(b"\0" * 64, "X", _art(), "Y")


def test_add_screen_refuses_an_object_id_the_scene_already_uses(monkeypatch):
    real = SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"]
    data, _p = _fake_scene(monkeypatch, used_id=real.first_free_id + 2)
    with pytest.raises(SW.SceneWriteError, match="already used"):
        SW.add_screen(data, "X", _art(), "Y")


def test_screen_refuses_art_bc3_cannot_hold():
    p = SW.PROFILES["f9daed5a19aafc807bf9eb3c2def6c27"]
    with pytest.raises(SW.SceneWriteError, match="multiple of 4"):
        SW.screen(p, "X", _art(w=10), "Y", 0, 0)
    with pytest.raises(SW.SceneWriteError, match="RGBA"):
        SW.screen(p, "X", np.zeros((8, 8, 3), dtype=np.uint8), "Y", 0, 0)


# ---- against the game's own bytes (skipped without the stock scenes) ----------------
def test_emitters_rebuild_attract_nodes_byte_for_byte():
    d = _read(ATTRACT, "c36dd5f54a876772e4a109320a44830e")
    leaf = SW.node(SW.FLAG | 0x8B1, "unnamed_instance_3", 1, [(1, 1)], [(1, d[0x50B43E:0x50B47E])],
                   [(1, 3, SW.FLAG | 0x8B2, SW.bitmap_body(5, 1360, 768, SW.texture_ref(8)))])
    assert leaf == d[0x50B3FB:0x50B4B2]
    group = SW.node(SW.FLAG | 0x8AF, "SternLogo", 18, [(1, 1), (110, 0)], [(1, d[0x50B38F:0x50B3CF])],
                    [(1, 2, SW.FLAG | 0x8B0, SW.sprite_body(11, [leaf]))])
    assert group == d[0x50B350:0x50B4CA]
    credits = SW.node(SW.FLAG | 0x8AD, "Credits", 17, [(1, 1), (230, 0)], [(1, d[0x50B26F:0x50B2AF])],
                      [(1, 5, SW.FLAG | 0x8AE,
                        SW.text_body(10, (-23.65, -31.25, 373.35, 21.55), (1.0, 1.0, 1.0, 1.0), "CREDITS 00",
                                     16, "GameFont_Primary", 2, (2.0, 2.0), 1, 2))])
    assert credits == d[0x50B232:0x50B350]


def test_emitter_rebuilds_a_hud_text_node_byte_for_byte():
    d = _read(HUD, "f9daed5a19aafc807bf9eb3c2def6c27")
    rect = struct.unpack_from("<4f", d, 0xE65E2)
    rgba = struct.unpack_from("<4f", d, 0xE65F2)
    spacing = struct.unpack_from("<2f", d, 0xE6608)
    timer = SW.node(SW.FLAG | 0xDD, "BattleTimer_Instance", 4, [(1, 1)], [(1, d[0x0E6582:0x0E65C2])],
                    [(1, 4, SW.FLAG | 0xDE, SW.text_body(5, rect, rgba, "00", 9, "GameFont_Primary",
                                                           1, spacing, 1, 1))])
    assert timer == d[0x0E653D:0x0E653D + len(timer)]


def test_profiles_match_their_stock_files():
    for path, md5 in ((HUD, "f9daed5a19aafc807bf9eb3c2def6c27"), (ATTRACT, "c36dd5f54a876772e4a109320a44830e")):
        d = _read(path, md5)
        SW.check(d, SW.profile_for(d))


def test_add_screen_on_the_stock_hud_scene():
    d = _read(HUD, "f9daed5a19aafc807bf9eb3c2def6c27")
    new, info = SW.add_screen(d, "Mode_Screen", _art(64, 16), "WORDS")
    assert info["screen_scene"] == "32e6ae280ddaec08e203a02289bb39a04968e7b0" and info["in_game"]
    assert len(new) == len(d) + info["node_bytes"]
    assert struct.unpack_from("<Q", new, 0x0E16E1)[0] == 4
    at = 0x0E4BE3 + info["node_bytes"]
    assert new[at + 12:at + 33] == b"BattleSlideOut_Artbox"


# ---- several screens in one pass (item 127: a card carries several modes) -------------
def test_add_screens_puts_each_in_its_own_ids_in_order(monkeypatch):
    data, p = _fake_scene(monkeypatch)
    new, infos = SW.add_screens(data, [dict(name="A_Screen", art_rgba=_art(), words="ONE"),
                                       dict(name="B_Screen", art_rgba=_art(), words="TWO")])
    assert struct.unpack_from("<Q", new, p.root_count_at)[0] == 5
    first = _parse_node(new[p.insert_at:])
    second_at = p.insert_at + infos[0]["node_bytes"]
    second = _parse_node(new[second_at:])
    assert (first["name"], second["name"]) == ("A_Screen", "B_Screen")
    assert first["ptr"] == SW.FLAG | p.first_free_id and second["ptr"] == SW.FLAG | (p.first_free_id + 7)
    assert new[second_at + infos[1]["node_bytes"]:] == data[p.insert_at:]
    assert [i["screen_text"] for i in infos] == ["A_Screen.A_Screen_Words", "B_Screen.B_Screen_Words"]


def test_one_screen_through_add_screens_is_add_screen(monkeypatch):
    data, _p = _fake_scene(monkeypatch)
    one, info = SW.add_screen(data, "Mode_Screen", _art(), "HELLO")
    many, infos = SW.add_screens(data, [dict(name="Mode_Screen", art_rgba=_art(), words="HELLO")])
    assert one == many and info["node_bytes"] == infos[0]["node_bytes"]


def test_add_screens_refuses_a_repeated_or_existing_name(monkeypatch):
    data, _p = _fake_scene(monkeypatch)
    with pytest.raises(SW.SceneWriteError, match="share a name"):
        SW.add_screens(data, [dict(name="S", art_rgba=_art(), words="1"),
                              dict(name="S", art_rgba=_art(), words="2")])
    with pytest.raises(SW.SceneWriteError, match="already in the scene"):
        SW.add_screens(data, [dict(name="Other", art_rgba=_art(), words="1")])
    with pytest.raises(SW.SceneWriteError, match="no screens"):
        SW.add_screens(data, [])


def test_add_screens_on_the_stock_hud_scene():
    d = _read(HUD, "f9daed5a19aafc807bf9eb3c2def6c27")
    new, infos = SW.add_screens(d, [dict(name="PadMode_a_Screen", art_rgba=_art(64, 16), words="A"),
                                    dict(name="PadMode_b_Screen", art_rgba=_art(64, 16), words="B")])
    assert struct.unpack_from("<Q", new, 0x0E16E1)[0] == 5
    at = 0x0E4BE3 + sum(i["node_bytes"] for i in infos)
    assert new[at + 12:at + 33] == b"BattleSlideOut_Artbox"
