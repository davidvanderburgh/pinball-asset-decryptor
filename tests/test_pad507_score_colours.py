"""PAD-507 (DragonRR): Godzilla's score panel is painted by the game program, so its colours
are changed there (plugins/stern/score_colours.py).

His score lines went grey in Scenes through the colour profile, but on the machine the score
stayed gold and the empty boxes green: every frame the score frame's update calls the Text's
colour setter (vtable +0x40) with colours made in code, over whatever the scene says.  These
tests build a small program with the very instruction shapes Godzilla LE 1.16 makes them with
(0x1ae4ac) and check the finder, the same-size patch, a second Write over a patched program,
putting the game's colours back, the project's picks and profile, and the Write step.
"""
import json
import os
import struct

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import score_colours as SC

BASE = 0x10000
FN = 0x100


def _movw(rd, v):
    return 0xE3000000 | ((v >> 12) << 16) | (rd << 12) | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | ((v >> 12) << 16) | (rd << 12) | (v & 0xFFF)


SET = [0xE5903000, 0xE5933040, 0xE12FFF33]        # ldr r3, [r0]; ldr r3, [r3, #0x40]; blx r3


def _code():
    """The score frame's update as LE 1.16 has it, in short: the player who is up (gold,
    r1 straight into the setter), gold-or-grey by ``moveq``, the other players (grey), and
    PRESS START / INSERT COINS made one from the other."""
    w = [0xE92D4010]                                 # push {r4, lr}
    w += [_movw(1, 0x44FF), _movt(1, 0xFFDD)] + SET
    w += [_movw(3, 0x6AFF), _movw(1, 0x44FF), _movt(3, 0x6C6B), _movt(1, 0xFFDD),
          0x01A01003] + SET                          # moveq r1, r3
    w += [_movw(1, 0x6AFF), _movt(1, 0x6C6B)] + SET
    w += [0xE3A090FF, 0xE1A02009, 0xE35B0000,        # mov sb, #0xff; mov r2, sb; cmp fp, #0
          _movt(2, 0x7F00), _movt(9, 0x007F), 0x01A09002,   # movt r2; movt sb; moveq sb, r2
          0xE1A01009] + SET                          # mov r1, sb
    w += [0xE8BD8010]                                # pop {r4, pc}
    return w


def _elf(words=None):
    raw = bytearray(0x400)
    raw[0:4] = b"\x7fELF"
    raw[4], raw[5], raw[6] = 1, 1, 1
    struct.pack_into("<HHIIIIIHHHHHH", raw, 0x10, 2, 40, 1, BASE, 0x34, 0, 0, 0x34, 32, 1,
                     40, 0, 0)
    struct.pack_into("<8I", raw, 0x34, 1, 0, BASE, 0, 0x400, 0x400, 5, 0x1000)
    for i, x in enumerate(_code() if words is None else words):
        struct.pack_into("<I", raw, FN + 4 * i, x)
    return bytes(raw)


def _patched(raw, ov):
    buf = bytearray(raw)
    for off, b in ov.items():
        buf[off:off + len(b)] = b
    return bytes(buf)


PICKS = {"up": (255, 0, 255), "others": (0, 255, 255), "start": (32, 64, 255),
         "coins": (255, 255, 0)}


# ---- the program --------------------------------------------------------------------------
def test_the_four_colours_are_found_in_the_function_that_makes_them():
    raw = _elf()
    found = SC.find(raw)
    assert found is not None and found.fn == BASE + FN
    assert {r: found.count(r) for r in SC.DEFAULTS} == {"up": 2, "others": 2, "start": 1,
                                                        "coins": 1}
    assert SC.read(raw, found) == SC.DEFAULTS


def test_a_program_without_the_colour_setter_calls_is_not_guessed_at():
    words = [x for x in _code() if x not in SET]
    assert SC.find(_elf(words)) is None
    assert SC.find(b"not an elf") is None


def test_the_patch_is_same_size_and_reads_back_as_picked():
    raw = _elf()
    found = SC.find(raw)
    ov = SC.overlay(raw, found, PICKS)
    assert all(len(b) == 4 for b in ov.values())
    new = _patched(raw, ov)
    assert len(new) == len(raw)
    # a Write that does not know what it wrote does not guess
    assert SC.find(new) is None
    again = SC.find(new, known={r: [rgb] for r, rgb in PICKS.items()})
    assert again is not None and SC.read(new, again) == PICKS
    assert [s["words"] for s in again.sites] == [s["words"] for s in found.sites]
    # a second Write of the same colours changes nothing; the game's own put back is the card
    assert SC.overlay(new, again, PICKS) == {}
    assert _patched(new, SC.overlay(new, again, {})) == raw


def test_the_green_and_red_become_two_movws_with_their_own_low_halves():
    raw = _elf()
    found = SC.find(raw)
    new = _patched(raw, SC.overlay(raw, found, {"start": (0x12, 0x34, 0x56)}))
    duo = next(s for s in found.sites if "roles" in s)
    kinds = {kind: struct.unpack_from("<I", new, o)[0] for o, (kind, _rd) in duo["words"].items()}
    assert kinds["a"] == _movw(9, 0x56FF) and kinds["ta"] == _movt(9, 0x1234)
    assert kinds["b"] == _movw(2, 0x00FF) and kinds["tb"] == _movt(2, 0x7F00)
    assert SC.read(new, SC.find(new, known={"start": (0x12, 0x34, 0x56)})) == dict(
        SC.DEFAULTS, start=(0x12, 0x34, 0x56))


# ---- the project --------------------------------------------------------------------------
CARD = "/godzilla_le/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821/scene.radium"


def _manifest():
    """The panel's shape in a scene manifest: Player 1's box (its score) and Player 2's."""
    def text(nid, name):
        return {"id": nid, "name": name, "comps": [[1, nid + 1000]]}

    def group(nid, name, kids):
        return {"id": nid, "name": name, "comps": [[1, nid + 1000]], "kids_": kids}
    score = text(2161, "score")
    other = text(2206, "InActiveScore_Instance")
    label = text(2155, "ActivePlayer_Username_Instance")
    p1 = group(2159, "Player1", [score])
    box = group(2157, "ActiveScore_1_Text_Instance", [p1])
    active = group(2153, "P1_ActiveScore_Instance", [label, box])
    inactive = group(2202, "P2_InActiveScore_Instance", [other])
    top = group(2149, "Player1_Instance", [active, inactive])
    objects = {}
    for n, rgba in ((score, [0.9882, 1.0, 0.0, 1.0]), (other, [0.6, 0.6, 0.6, 1.0]),
                    (label, [1.0, 1.0, 1.0, 1.0])):
        objects[str(n["id"] + 1000)] = {"kind": "Text", "text": "22,000,000,000", "rgba": rgba}
    for n in (p1, box, active, inactive, top):
        objects[str(n["id"] + 1000)] = {"kind": "Sprite", "kids": n.pop("kids_")}
    return {"root": {"kids": [top], "labels": [], "frames": 1}, "objects": objects,
            "stage": [1360, 768]}


def _project(tmp_path, slots=(), profile=None):
    d = tmp_path / "gzho"
    (d / "images" / "scene_textures").mkdir(parents=True)
    with open(d / "images" / "scene_textures" / "scene_tree.json", "w", encoding="utf-8") as f:
        json.dump({CARD: _manifest()}, f)
    data = {}
    if slots:
        data[cp.STOCK_IMAGES_KEY] = True
        data[cp.TEXT_SLOTS_KEY] = {cp.text_rel(CARD, n): True for n in slots}
    if profile is not None:
        data[cp.ASSET_KEY] = cp._profile_dict(profile)
    staged_changes.save(str(d), data)
    return str(d)


def test_the_panels_lines_are_known_by_where_they_sit():
    assert SC.panel_lines(_manifest()) == {2161: "up", 2206: "rest"}
    assert SC.panel_lines({"root": {"kids": []}, "objects": {}}) == {}


def test_what_the_machine_shows_is_the_scene_colour_times_the_games():
    # measured in the emulator on stock LE 1.16: the score (252, 221, 0), another player's
    # (65, 64, 64), PRESS START (0, 76, 0)
    assert SC.SHOWN == {"up": (252, 221, 0), "others": (65, 64, 64), "start": (0, 76, 0),
                        "coins": (76, 0, 0)}


def test_nothing_to_write_until_a_colour_is_picked(tmp_path):
    proj = _project(tmp_path)
    assert not SC.pending(proj)
    assert SC.wanted(proj) == SC.SHOWN
    assert SC.program_colours(SC.wanted(proj)) == SC.DEFAULTS
    SC.set_pick(proj, "start", (255, 255, 255))
    assert SC.pending(proj)
    assert SC.wanted(proj)["start"] == (255, 255, 255)
    SC.set_pick(proj, "start", SC.SHOWN["start"])             # what the game shows: no pick
    assert SC.picks(proj) == {} and not SC.pending(proj)


def test_a_kind_changed_takes_its_whole_colour_from_the_program(tmp_path):
    proj = _project(tmp_path)
    SC.set_pick(proj, "start", (255, 255, 255))
    want = SC.wanted(proj)
    assert SC.changed(want) == {"rest"}
    # its lines go white, so the program paints what the machine is to show; the other
    # roles of the kind keep what the game shows, the player up the game's own word
    assert SC.program_colours(want) == {"up": SC.DEFAULTS["up"], "others": SC.SHOWN["others"],
                                        "start": (255, 255, 255), "coins": SC.SHOWN["coins"]}
    assert SC.scene_ops(proj, _manifest()) == [
        {"op": "line_colour", "node": 2206, "rgb": [1.0, 1.0, 1.0]}]


def test_a_kind_put_back_gets_its_scene_colour_back(tmp_path):
    proj = _project(tmp_path)
    SC.set_pick(proj, "up", (1, 2, 3))
    SC.remember_written(proj, SC.program_colours(SC.wanted(proj)))
    SC.set_pick(proj, "up", None)
    assert SC.pending(proj)                         # a card built with it needs it back
    ops = SC.scene_ops(proj, _manifest())
    assert ops == [{"op": "line_colour", "node": 2161, "rgb": list(SC.SCENE_RGB["up"])}]


def test_a_score_line_with_the_profile_on_puts_it_on_the_game_colours(tmp_path):
    bw = cp.Profile(name="Black and white", saturation=0.0)
    proj = _project(tmp_path, slots=(2161,), profile=bw)
    want = SC.wanted(proj)
    r, g, b = want["up"]
    assert abs(r - g) <= 1 and abs(g - b) <= 1 and r > 150        # the gold, grey
    assert want["start"] == SC.SHOWN["start"]                      # its line is not on
    assert SC.pending(proj)
    # a colour picked by hand wins over the profile; the preview off draws the game's own
    SC.set_pick(proj, "up", (224, 32, 32))
    assert SC.wanted(proj)["up"] == (224, 32, 32)
    other = _project(tmp_path / "x", slots=(2161,), profile=bw)
    assert SC.wanted(other, bake=False)["up"] == SC.SHOWN["up"]


def test_the_preview_draws_the_panel_as_the_machine_shows_it(tmp_path):
    proj = _project(tmp_path)
    ops = {op["node"]: op["rgb"] for op in SC.preview_ops(proj, _manifest())}
    # the game's own: the scene colour times the game's
    assert ops == {2161: [0.9882, round(0xdd / 255, 4), 0.0],
                   2206: [round(0.6 * 0x6c / 255, 4), round(0.6 * 0x6b / 255, 4),
                          round(0.6 * 0x6a / 255, 4)]}
    SC.set_pick(proj, "others", (0, 255, 255))
    ops = {op["node"]: op["rgb"] for op in SC.preview_ops(proj, _manifest())}
    assert ops[2206] == [0.0, 1.0, 1.0]


class _Reader:
    def __init__(self, raw):
        self.raw = raw

    def read_file_bytes(self, node):
        return self.raw

    def disk_ranges(self, node, off, n):
        return [(0x100000 + off, n)]


def test_the_write_patches_in_place_and_a_second_write_finds_its_own(tmp_path):
    proj = _project(tmp_path)
    for role, rgb in PICKS.items():
        SC.set_pick(proj, role, rgb)
    raw = _elf()
    logs = []
    say = lambda m, lvl="info": logs.append((lvl, m))          # noqa: E731
    writes, ov, n = SC.compute_writes(_Reader(raw), {"i_block": b"x"}, proj, say)
    assert n == len(ov) == len(writes) == 12          # 4 pairs and the green/red shape
    assert all(disk == 0x100000 + off for (disk, _b), off in zip(writes, sorted(ov)))
    new = _patched(raw, ov)
    assert SC.written(proj) == {r: [rgb] for r, rgb in PICKS.items()}
    # building again from the card that Write made: found, and nothing left to change
    writes2, ov2, n2 = SC.compute_writes(_Reader(new), {"i_block": b"x"}, proj, say)
    assert (writes2, ov2, n2) == ([], {}, 0)
    # the picks taken back: the game's own colours go back on that card
    for role in PICKS:
        SC.set_pick(proj, role, None)
    assert SC.pending(proj)                                      # something to put back
    _w, ov3, _n = SC.compute_writes(_Reader(new), {"i_block": b"x"}, proj, say)
    assert _patched(new, ov3) == raw


def test_the_write_bakes_into_a_staged_program(tmp_path):
    proj = _project(tmp_path)
    SC.set_pick(proj, "up", (1, 2, 3))
    fw = tmp_path / "game"
    fw.write_bytes(_elf())
    writes, ov, n = SC.compute_writes(None, None, proj, lambda *a: None, patched_fw=str(fw))
    assert writes == [] and ov == {} and n == 4
    got = fw.read_bytes()
    assert SC.read(got, SC.find(got, known={"up": (1, 2, 3)}))["up"] == (1, 2, 3)


def test_a_program_without_the_panel_says_so_and_writes_nothing(tmp_path):
    proj = _project(tmp_path)
    SC.set_pick(proj, "up", (1, 2, 3))
    logs = []
    out = SC.compute_writes(_Reader(_elf([0xE92D4010, 0xE8BD8010])), {"i_block": b"x"}, proj,
                            lambda m, lvl="info": logs.append((lvl, m)))
    assert out == ([], {}, 0)
    assert logs and logs[0][0] == "warning" and "original card" in logs[0][1]


def test_the_write_tab_lists_the_colours(tmp_path):
    from types import SimpleNamespace
    from pinball_decryptor.webui import write_scan
    proj = _project(tmp_path)
    stern = SimpleNamespace(key="stern")
    assert write_scan.score_colour_rows(stern, proj) == []
    SC.set_pick(proj, "start", (255, 255, 255))
    rows = write_scan.score_colour_rows(stern, proj)
    assert len(rows) == 1 and "PRESS START #ffffff" in rows[0][0]
    assert rows[0][2] == write_scan.PENDING_SCORE_COLOURS
    assert write_scan.score_colour_rows(SimpleNamespace(key="jjp"), proj) == []


STOCK = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


@pytest.mark.skipif(not os.path.isfile(STOCK), reason="the stock LE 1.16 card is not here")
def test_stock_godzilla_le_1_16():
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(STOCK)
    with CardImage(STOCK) as img:
        raw = img.preview(part, "/%s/game" % game, cap=256 << 20)
    found = SC.find(raw)
    assert found is not None and found.fn == 0x1ae4ac
    assert {r: found.count(r) for r in SC.DEFAULTS} == {r: 5 for r in SC.DEFAULTS}
    assert SC.read(raw, found) == SC.DEFAULTS
