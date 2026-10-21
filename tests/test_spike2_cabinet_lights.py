"""The virtual playfield's cabinet lights (PAD-500): the topper, the expression
lighting and the speaker lighting in a column left of the artwork, and a tick box
that takes the blades and the speakers out.

"It would be great to show the Topper, Expression Lighting, and Speaker Lighting
nodes to the left of the playfield artwork for Spike 2 games, and add a toggle to
disable expression lights (blades and speakers)" (peanuts, 2026-10-10). What is
worth failing on:

  * WHICH BOARD. None of these groups is one coilmap.group_node() can measure, so
    the title's own node directory places them: a group is its board's place in
    the directory (nbdir v2 writes it as group=, with the board's name). The
    measured map still wins, and a place is taken only when the board's own name
    or type agrees with the row - never a guess.
  * THE BLADES ARE TWO BARS, PIXEL 1 AT THE BOTTOM, split by the name's side
    (Rush) or by the picture (King Kong numbers 1-96 with no side), and they are
    NOT inserts: John Wick, King Kong and Metallica put them on the playfield
    picture, where they were 96 dark dots.
  * THE BOARDS PAST CHANNEL 96: padled version 6 publishes a strip's banks past
    the first, which the shim used to walk and throw away; a reader takes them
    from `hi` and from nothing older.
  * THE TICK BOX: off leaves the topper and drops the blades and the speakers,
    from the column and from the swatch grid, and is kept for the next run.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
PF_JS = os.path.join(RIG, "pfpage", "pf.js")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import cablights  # noqa: E402
import coilmap  # noqa: E402

#: Rush LE 1.19's node directory as nbdir v2 writes it (stand-in hexes; the
#: places and names are the binary's own)
RUSH_IDENT = """# nbdir v2 elf=rush_le-1.19.elf nodes=9 src=x
node=1 type=pinnode code=2 part=0x00020023 hex=p.hex group=5 name=CABINET
node=2 type=ws2812node code=23 part=0x2c40102b hex=w.hex group=1 name=Cabinet Lights
node=4 type=node4 code=29 part=0x00140040 hex=n.hex group=2 name=QR Scanner
node=7 type=ws2812node code=23 part=0x2c40102b hex=w.hex group=6 name=BACKBOX SPEAKER LIGHTS
node=8 type=pinnode code=5 part=0x00020023 hex=p.hex group=7 name=PLAYFIELD 1
node=9 type=pinnode code=5 part=0x00020023 hex=p.hex group=8 name=PLAYFIELD 2
node=10 type=tmc5041node code=32 part=0x2c40102b hex=t.hex group=9 name=STEPPER MOTOR BOARD 1
node=12 type=coil4node code=13 part=0x2c40102b hex=c.hex group=10 name=TOPPER
node=14 type=ws2812node code=23 part=0x2c40102b hex=w.hex group=3 name=Topper Lights
# skipped node=0 code=41 reason=no-type (CPU/bridge or reserved) group=4 name=CPU / BRIDGE
"""

#: Godzilla Pro 1.16's: its own topper (group 8) is node 12, "Topper", and the
#: universal one (group 3) node 14, "Topper Lights"
GZ_IDENT = """# nbdir v2 elf=godzilla_pro-1.16.elf nodes=8 src=x
node=1 type=pinnode code=2 hex=p.hex group=5 name=Cabinet
node=2 type=ws2812node code=24 hex=w.hex group=1 name=Cabinet Lights
node=4 type=node4 code=30 hex=n.hex group=2 name=QR Scanner
node=7 type=ws2812node code=24 hex=w.hex group=9 name=Backbox Speaker Lights
node=8 type=pinnode code=5 hex=p.hex group=6 name=Lower Playfield
node=9 type=pinnode code=5 hex=p.hex group=7 name=Upper Playfield
node=12 type=ws2812node code=21 hex=w.hex group=8 name=Topper
node=14 type=ws2812node code=24 hex=w.hex group=3 name=Topper Lights
"""


def _ident(tmp_path, text):
    p = tmp_path / "node_ident.txt"
    p.write_text(text)
    return cablights.boards(str(p))


def _row(kind, name, group, index, x=0, y=0, image=""):
    return dict(kind=kind, name=name, group=group, index=index, x=x, y=y,
                image=image, conn="")


def _rush_rows():
    """Rush's cabinet lights: 48 blade pixels a side ("L 1".."R 96", G-R-B on
    the wire) on no picture, 23 speaker pixels, and two playfield inserts."""
    rows = []
    for n in range(96):
        side = "L" if n < 48 else "R"
        for c, o in (("G", 0), ("R", 1), ("B", 2)):
            rows.append(_row("led", "EXPRESSIVE LIGHTING %s %d-%s" % (side, n + 1, c),
                             1, n * 3 + o))
    for n in range(23):
        for c, o in (("G", 0), ("R", 1), ("B", 2)):
            rows.append(_row("led", "SPEAKER %d-%s" % (n + 1, c), 6, n * 3 + o))
    rows.append(_row("led", "LEFT ORBIT", 7, 3, 40, 300, "playfield"))
    rows.append(_row("switch", "LEFT SLING", 7, 1, 60, 500, "playfield"))
    return rows


RUSH_MEASURED = {2: 4, 4: 0, 5: 1, 7: 8, 8: 9, 9: 10, 10: 12}


# ------------------------------------------------------------------ rows ----

def test_the_three_roles():
    assert cablights.role(_row("led", "EXPRESSIVE LIGHTING L 1-G", 1, 0)) == "expression"
    assert cablights.role(_row("led", "SPEAKER 23-B", 6, 68)) == "speaker"
    assert cablights.role(_row("led", "TOPPER BIKE - R", 9, 3)) == "topper"
    # a topper drawn on its own picture, its rows named for what they light
    assert cablights.role(_row("led", "HEAT RAY 12-R", 8, 40, 1, 1,
                               "Test/scaled_godzilla_topper")) == "topper"
    assert cablights.role(_row("led", "LEFT ORBIT", 7, 3)) is None
    assert cablights.role(_row("switch", "TOPPER HOME 1", 12, 0)) is None
    assert cablights.role(_row("led", "SPEAKERPHONE", 7, 0)) is None


def test_the_uv_kit_is_a_section_of_its_own():
    """PAD-551 (peanuts: Stranger Things "missing UV Lighting Kit"): the kit's
    two outputs are lamp channels on a playfield board with no place on any
    picture. A playfield insert merely named for UV (Metallica) stays one."""
    assert cablights.role(_row("led", "UV CONTROL 1 (OPTIONAL)", 7, 3)) == "uv"
    assert cablights.role(_row("led", "HAMMER UV", 8, 18, 166, 271, "playfield")) is None
    rows = [_row("led", "UV CONTROL 1 (OPTIONAL)", 7, 3),
            _row("led", "UV CONTROL 2 (OPTIONAL)", 7, 4),
            _row("led", "LEFT ORBIT", 7, 5, 40, 300, "playfield")]
    secs, left = cablights.sections(rows, {7: 9}, {9: {"type": "pinnode", "group": 7,
                                                       "name": "Playfield"}})
    assert [(S["key"], S["label"], len(S["pixels"])) for S in secs] == [
        ("uv:9", "UV Lighting Kit", 2)] and left == []
    # only the measured map places it: a board's place alone proves nothing
    secs, left = cablights.sections(rows, {}, {9: {"type": "pinnode", "group": 7,
                                                   "name": "Playfield"}})
    assert secs == [] and left[0][:2] == ("uv", 2)


def test_one_pixel_however_the_title_spells_its_channels():
    assert cablights.split_channel("SPEAKER 1-G") == ("SPEAKER 1", "G")
    assert cablights.split_channel("TOPPER BIKE - R") == ("TOPPER BIKE", "R")
    assert cablights.split_channel("RIGHT SCOOP RECTANGLE-BLU") == ("RIGHT SCOOP RECTANGLE", "B")
    assert cablights.split_channel("FLAME PANEL-L") == ("FLAME PANEL-L", "W")
    assert cablights.split_channel("GODZILLA FLASHER") == ("GODZILLA FLASHER", "W")


# ------------------------------------------------------------------ boards --

def test_the_directory_reads_places_and_names(tmp_path):
    bm = _ident(tmp_path, RUSH_IDENT)
    assert bm[2] == {"type": "ws2812node", "group": 1, "name": "Cabinet Lights"}
    assert bm[7]["name"] == "BACKBOX SPEAKER LIGHTS" and bm[7]["group"] == 6
    assert bm[0]["group"] == 4 and bm[0]["name"] == "CPU / BRIDGE"   # a skipped line
    assert cablights.board_for_group(3, bm) == 14


def test_a_v1_table_places_nothing(tmp_path):
    bm = _ident(tmp_path, "# nbdir v1 elf=game nodes=1\nnode=2 type=ws2812node code=5\n")
    assert bm == {2: {"type": "ws2812node", "group": None, "name": ""}}
    assert cablights.resolve("expression", 1, {}, bm)[0] is None
    assert cablights.boards(str(tmp_path / "gone.txt")) == {}


def test_a_v1_table_says_the_game_must_start_again(tmp_path):
    # PAD-532: godzilla_le's rig still had its pre-PAD-500 directory, and the
    # box blamed the title ("group 3 has no board") for every cabinet light
    bm = _ident(tmp_path, GZ_LE_IDENT.replace("# nbdir v2", "# nbdir v1").replace(
        " group=", " was="))
    assert cablights.resolve("topper", 3, {}, bm) == (None, cablights.OLD_DIRECTORY)
    assert cablights.resolve("topper", 3, {}, {}) == (None, cablights.NO_DIRECTORY)
    # a v2 directory that has no board at the place still says so
    bm = _ident(tmp_path, GZ_LE_IDENT)
    assert "group 11 has no board" in cablights.resolve("topper", 11, {}, bm)[1]


def test_the_measured_map_first_then_a_place_the_board_confirms(tmp_path):
    bm = _ident(tmp_path, RUSH_IDENT)
    assert cablights.resolve("expression", 1, RUSH_MEASURED, bm) == (2, "directory")
    assert cablights.resolve("speaker", 6, RUSH_MEASURED, bm) == (7, "directory")
    # Bond 60th's topper: its connectors measure group 10 -> node 12
    assert cablights.resolve("topper", 10, {10: 12}, {}) == (12, "measured")
    # a place whose board says it is something else is refused, not taken
    node, why = cablights.resolve("topper", 7, {}, bm)
    assert node is None and "PLAYFIELD 1" in why and "not a topper board" in why
    node, why = cablights.resolve("expression", 5, {}, bm)
    assert node is None and "not a strip board" in why
    assert cablights.resolve("speaker", 30, {}, bm)[0] is None


# ------------------------------------------------------------------ sections --

def test_rush_the_speakers_then_the_blades(tmp_path):
    secs, left = cablights.sections(_rush_rows(), RUSH_MEASURED, _ident(tmp_path, RUSH_IDENT))
    assert [(S["role"], S["node"], S["board"], len(S["pixels"])) for S in secs] == [
        ("speaker", 7, "BACKBOX SPEAKER LIGHTS", 23),
        ("expression", 2, "Cabinet Lights", 96)]
    assert left == []
    blades = secs[1]
    px = blades["pixels"]
    # two bars, each BOTTOM FIRST: pixel 1 and pixel 49 start them
    assert [len(b) for b in blades["bars"]] == [48, 48]
    assert [px[blades["bars"][0][0]]["name"], px[blades["bars"][0][-1]]["name"]] == [
        "EXPRESSIVE LIGHTING L 1", "EXPRESSIVE LIGHTING L 48"]
    assert px[blades["bars"][1][0]]["name"] == "EXPRESSIVE LIGHTING R 49"
    # one pixel, three channels at their wire places, the last past index 95
    assert px[-1]["channels"] == {"G": (2, 285), "R": (2, 286), "B": (2, 287)}


def test_king_kong_splits_its_blades_by_the_picture(tmp_path):
    # 1-96 with no side, 1-48 up the left edge (x=7, pixel 1 at y=539) and
    # 49-96 up the right (x=305)
    rows = []
    for n in range(96):
        x, k = (7, n) if n < 48 else (305, n - 48)
        for c, o in (("G", 0), ("R", 1), ("B", 2)):
            rows.append(_row("led", "EXPRESSIVE LIGHTING %d-%s" % (n + 1, c), 1,
                             n * 3 + o, x, 539 - k * 9.5, "TestMode/Rodeo_LE_Playfield"))
    secs, _ = cablights.sections(rows, {}, _ident(tmp_path, RUSH_IDENT))
    S = secs[0]
    assert [len(b) for b in S["bars"]] == [48, 48]
    assert S["pixels"][S["bars"][1][0]]["name"] == "EXPRESSIVE LIGHTING 49"
    assert not S["positioned"]


def test_the_tick_box_leaves_the_topper(tmp_path):
    rows = _rush_rows() + [_row("led", "TOPPER %d-%s" % (n // 3 + 1, "GRB"[n % 3]), 10, n)
                           for n in range(12)]
    bm = _ident(tmp_path, RUSH_IDENT)
    on, _ = cablights.sections(rows, RUSH_MEASURED, bm)
    off, _ = cablights.sections(rows, RUSH_MEASURED, bm, expression=False)
    assert [S["role"] for S in on] == ["topper", "speaker", "expression"]
    assert [S["key"] for S in off] == ["topper:12"]
    # and a board the cabinet does not have is not drawn at all
    gone, _ = cablights.sections(rows, RUSH_MEASURED, bm, gone_nodes={12})
    assert "topper" not in [S["role"] for S in gone]


def test_godzilla_s_two_toppers_go_by_their_boards_names(tmp_path):
    rows = [_row("led", "TANK 1A-%s" % c, 8, i, 45 + i, 133, "Test/scaled_godzilla_topper")
            for i, c in enumerate("GRB")]
    rows += [_row("led", "HEAT RAY %d-R" % n, 8, 300 + n, 80 + 9 * n, 90, "Test/scaled_godzilla_topper")
             for n in range(5)]
    rows += [_row("led", "ETOPPER L DOME LED %d-%s" % (n // 3 + 1, "RGB"[n % 3]), 3, n,
                  73 + 6 * (n // 3), 279, "System/TestMode/universal_topper_scaled")
             for n in range(9)]
    gz = {2: 4, 4: 0, 5: 1, 6: 8, 7: 9}
    secs, left = cablights.sections(rows, gz, _ident(tmp_path, GZ_IDENT))
    assert [(S["label"], S["node"]) for S in secs] == [("Topper", 12),
                                                       ("Topper Expression Light", 14)]
    assert all(S["positioned"] for S in secs) and left == []


#: godzilla_le 1.36's, as nbdir derives it on the rig (PAD-532): the topper on
#: group 9, the speakers on group 10 - not the Pro's 8 and 9
GZ_LE_IDENT = """# nbdir v2 elf=game nodes=9 src=game 7962924 bytes
node=1 type=pinnode code=2 part=0x00020023 group=5 name=Cabinet
node=2 type=ws2812node code=24 part=0x2c40102b group=1 name=Cabinet Lights
node=4 type=node4 code=30 part=0x00140040 group=2 name=QR Scanner
node=7 type=ws2812node code=24 part=0x2c40102b group=10 name=Backbox Speaker Lights
node=8 type=pinnode code=5 part=0x00020023 group=6 name=Lower Playfield
node=9 type=pinnode code=5 part=0x00020023 group=7 name=Upper Playfield
node=10 type=tmc5041node code=33 part=0x2c40102b group=8 name=Stepper Motor Board
node=12 type=ws2812node code=21 part=0x2c40102b group=9 name=Topper
node=14 type=ws2812node code=24 part=0x2c40102b group=3 name=Topper Lights
# skipped node=0 code=42 reason=no-type (CPU/bridge or reserved) group=4 name=CPU / Bridge
"""


def test_godzilla_le_draws_both_toppers_and_its_speakers(tmp_path):
    # the three the ticket's box called "not shown": topper 103 channels on
    # group 9, the universal topper 275 on group 3, the speakers 69 on group 10
    rows = [_row("led", "TANK 1A-%s" % c, 9, i, 45 + i, 133, "Test/scaled_godzilla_topper")
            for i, c in enumerate("GRB")]
    rows += [_row("led", "ETOPPER L DOME LED 1-%s" % c, 3, i, 73, 279,
                  "System/TestMode/universal_topper_scaled") for i, c in enumerate("RGB")]
    rows += [_row("led", "SPEAKER %d-%s" % (n // 3 + 1, "GRB"[n % 3]), 10, n)
             for n in range(69)]
    measured = {2: 4, 4: 0, 5: 1, 6: 8, 7: 9, 8: 10}
    secs, left = cablights.sections(rows, measured, _ident(tmp_path, GZ_LE_IDENT))
    assert left == []
    assert [(S["role"], S["node"], S["label"]) for S in secs] == [
        ("topper", 12, "Topper"), ("topper", 14, "Topper Expression Light"),
        ("speaker", 7, "Speaker lighting")]
    assert len(secs[2]["pixels"]) == 23


def test_node_14_is_the_topper_expression_light_not_the_game_s_name(tmp_path):
    # "Node 14 Topper Lights should be renamed Topper Expression Light ... in
    # order to avoid confusion with regular topper" (peanuts, PAD-522): the
    # add-on's name, alone on a title as with its own topper, and the game's
    # "Topper Lights" nowhere - not even as the board's name under it
    rows = [_row("led", "ETOPPER L DOME LED %d-%s" % (n // 3 + 1, "RGB"[n % 3]), 3, n,
                 73 + 6 * (n // 3), 279, "System/TestMode/universal_topper_scaled")
            for n in range(9)]
    secs, _ = cablights.sections(rows, {2: 4, 4: 0, 5: 1}, _ident(tmp_path, GZ_IDENT))
    assert [(S["label"], S["node"], S["board"]) for S in secs] == [
        ("Topper Expression Light", 14, "")]
    # John Wick names its OWN topper on node 12 "Topper Lights" too: that one
    # is still the title's topper
    jw = GZ_IDENT.replace("group=8 name=Topper\n", "group=8 name=Topper Lights\n")
    rows = [_row("led", "TOPPER %d-%s" % (n // 3 + 1, "GRB"[n % 3]), 8, n) for n in range(6)]
    secs, _ = cablights.sections(rows, {}, _ident(tmp_path, jw))
    assert [(S["label"], S["node"], S["board"]) for S in secs] == [
        ("Topper", 12, "Topper Lights")]


#: King Kong Pro 0.97's directory, in its order: the topper is node 12 at
#: place 9, and its rows never say "topper"
KK_IDENT = """# nbdir v2 elf=king_kong_pro-0.97.elf nodes=10 src=x
node=2 type=ws2812node hex=w.hex group=1 name=Cabinet Lights
node=4 type=node4 hex=n.hex group=2 name=QR Scanner
node=14 type=ws2812node hex=w.hex group=3 name=Topper Lights
node=1 type=pinnode hex=p.hex group=5 name=Cabinet
node=7 type=ws2812node hex=w.hex group=6 name=Backbox Speaker Lights
node=8 type=pinnode hex=p.hex group=7 name=Lower Playfield
node=9 type=pinnode hex=p.hex group=8 name=Upper Playfield
node=12 type=ws2812node hex=w.hex group=9 name=Topper
node=13 type=pinnode hex=p.hex group=10 name=Topper Kong SPI Board
"""


def test_a_lamp_on_the_topper_s_board_is_the_topper_whatever_its_name(tmp_path):
    # "MARQUEE GI1-G" .. "MARQUEE RIGHT BACK4-R": a traced King Kong Pro game
    # drove all 228 channels of node 12
    rows = [_row("led", "MARQUEE GI%d-%s" % (n // 3 + 1, "GRB"[n % 3]), 9, n)
            for n in range(9)]
    rows.append(_row("led", "GONG LEFT", 8, 4, 100, 200, "TestMode/Rodeo_PRO_Playfield"))
    bm = _ident(tmp_path, KK_IDENT)
    kk = {2: 4, 4: 0, 5: 1, 7: 8, 8: 9}
    assert cablights.role_of(rows[0], kk, bm) == "topper"
    assert cablights.role_of(rows[-1], kk, bm) is None
    secs, _ = cablights.sections(rows, kk, bm)
    assert [(S["key"], len(S["pixels"]), S["positioned"]) for S in secs] == [
        ("topper:12", 3, False)]


def test_what_no_board_places_is_counted_not_drawn(tmp_path):
    secs, left = cablights.sections(_rush_rows(), RUSH_MEASURED, {})
    assert secs == []
    assert [(w, n) for w, n, _why in left] == [("expression", 288), ("speaker", 69)]


# ------------------------------------------------------------------ nbdir -----

def test_nbdir_writes_the_places_inside_hwshims_line_buffer(tmp_path):
    import nbdir
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    out = tmp_path / "node_ident.txt"
    rows = [(12, "hdmi_ws2812node", 30, 0x2C40102B, 5, 0x05, 0x012100, "1.33.0",
             "hdmi_ws2812node-LPC1313-1_33_0.hex", True, 520853000)]
    boards = {12: (9, "Accessory Topper (Optional)"), 0: (4, "CPU / Bridge")}
    nbdir.emit(rows, [(0, 41, "no-type (CPU/bridge or reserved)")], str(elf), str(out),
               "src", boards)
    text = out.read_text()
    assert text.startswith("# nbdir v2 ")
    assert max(len(ln) + 1 for ln in text.splitlines()) < 256
    bm = cablights.boards(str(out))
    assert bm[12] == {"type": "hdmi_ws2812node", "group": 9,
                      "name": "Accessory Topper (Optional)"}
    assert bm[0]["group"] == 4
    # and coilmap's own reader of the same file is not upset by them
    assert coilmap._playfield_nodes(str(out)) == []


def test_a_v1_table_is_derived_again_not_reused(tmp_path):
    import nbdir
    elf = tmp_path / "game"
    elf.write_bytes(b"\x7fELF" + b"\0" * 64)
    src = nbdir.source_id(str(elf), str(tmp_path))
    have = tmp_path / "node_ident.txt"
    have.write_text("# nbdir v1 elf=game nodes=1 src=%s\nnode=2 type=ws2812node code=5\n" % src)
    assert nbdir.reuse(str(have), str(tmp_path / "o.txt"), str(elf), str(tmp_path)) is False
    have.write_text("# nbdir v2 elf=game nodes=1 src=%s\nnode=2 type=ws2812node code=5 group=1 name=x\n" % src)
    assert nbdir.reuse(str(have), str(tmp_path / "o.txt"), str(elf), str(tmp_path)) is True


# ------------------------------------------------------------------ padled v6 -

def _block(version=6, size=None):
    b = bytearray(size or (16384 if version >= 6 else 8192))
    struct.pack_into("<I", b, 0, coilmap.PADLED_MAGIC)
    struct.pack_into("<I", b, 4, version)
    return b


def test_the_hi_plane_is_where_padled_h_says():
    hdr = open(os.path.join(RIG, "padled.h"), encoding="utf-8").read()
    assert "hi %d" % coilmap.HI_OFF in hdr
    assert coilmap.HI_OFF == coilmap.DRIVE_READ == 7356
    assert int(re.search(r"#define PADLED_BYTES (\d+)", hdr).group(1)) >= coilmap.HI_READ
    watch = open(os.path.join(RIG, "watch.sh"), encoding="utf-8").read()
    assert 'dd if=/dev/zero of="$LED_HOST" bs=16384 count=1' in watch


def test_a_strip_channel_reads_from_val_or_hi():
    b = _block()
    b[20 + 2 * 96 + 5] = 0x40
    b[coilmap.HI_OFF + 2 * coilmap.HI_IDX + (287 - 96)] = 0xC0
    assert coilmap.strip_level(bytes(b), 2, 5) == 0x40
    assert coilmap.strip_level(bytes(b), 2, 287) == 0xC0
    assert coilmap.strip_level(bytes(b), 2, 480) is None
    assert coilmap.strip_level(bytes(b), None, 5) is None
    # a version-5 block has no channel past 95 to give: None, not "off"
    old = _block(version=5)
    assert coilmap.strip_level(bytes(old), 2, 287) is None
    assert coilmap.strip_level(bytes(old), 2, 5) == 0


# ------------------------------------------------------------------ the window

@pytest.fixture()
def pf(monkeypatch, tmp_path):
    import playfield
    monkeypatch.setattr(playfield, "DEV_ROWS", _rush_rows())
    monkeypatch.setattr(playfield, "GROUP_NODE", dict(RUSH_MEASURED))
    monkeypatch.setattr(playfield, "LAYOUT_IMAGE", "playfield")
    monkeypatch.setattr(playfield, "STATE", str(tmp_path / "pad_playfield.json"))
    ident = tmp_path / "node_ident.txt"
    ident.write_text(RUSH_IDENT)
    monkeypatch.setattr(playfield, "load_boards", lambda: cablights.boards(str(ident)))
    return playfield


def test_the_blades_are_not_inserts_on_the_art(pf, monkeypatch):
    rows = _rush_rows() + [_row("led", "EXPRESSIVE LIGHTING L 1-G", 1, 0, 7, 539, "playfield")]
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    assert [L["name"] for L in pf.load_leds()] == ["LEFT ORBIT"]


def test_the_swatch_grid_names_the_cabinet(pf):
    names = pf.load_led_names()
    assert names[(2, 0)] == "EXPRESSIVE LIGHTING L 1-G"
    assert names[(2, 287)] == "EXPRESSIVE LIGHTING R 96-B"
    assert names[(7, 68)] == "SPEAKER 23-B"
    assert names[(8, 3)] == "LEFT ORBIT"


def test_every_section_shows_from_the_start_dark(pf):
    """PAD-551 (peanuts): fifteen titles' toppers and speaker rings read as
    missing, because a section waited for its board to speak and most games
    leave those boards off in attract. Every section is drawn from the start,
    dark; the box says which boards have not spoken yet."""
    cab = pf.CabinetLights(True)
    b = _block()
    changes, grew = cab.tick(bytes(b))
    assert [s["key"] for s in cab.spec()] == ["speaker:7", "expression:2"]
    assert not grew and set(cab.dyn().values()) == {0}
    assert [ln[2].endswith("nothing from it yet") for ln in cab.panel()["lines"]] == [True, True]
    # the right blade's top pixel, channels 285-287 - all three past index 95
    for ch, v in ((285, 0x00), (286, 0xFF), (287, 0x00)):
        b[coilmap.HI_OFF + 2 * coilmap.HI_IDX + ch - 96] = v
    changes, grew = cab.tick(bytes(b))
    assert grew
    spec = cab.spec()
    assert [s["key"] for s in spec] == ["speaker:7", "expression:2"]
    top = spec[1]["bars"][1][-1]
    assert changes[top][:3] == [255, 0, 0] and changes[top][3] > 0.5
    assert cab.dyn()[top] == changes[top]
    # the speakers speak through the `seen` plane before they light
    b[pf.SEEN_OFF + 7 * 96 + 0] = 1
    _c, grew = cab.tick(bytes(b))
    spec = cab.spec()
    assert grew and [s["key"] for s in spec] == ["speaker:7", "expression:2"]
    assert not any(ln[2].endswith("nothing from it yet") for ln in cab.panel()["lines"])
    assert "R=channel 286" in cab.describe(top) and "Cabinet Lights" in cab.describe(top)
    # the speakers are a ring, in chain order (Sam, 2026-10-11)
    assert len(spec[0]["ring"]) == 23 and "row" not in spec[0]
    assert cab.pixels[spec[0]["ring"][0]]["name"] == "SPEAKER 1"


def test_a_topper_left_off_the_bus_gets_no_section(pf, monkeypatch):
    # PAD-498: the Emulate tab's Topper box off leaves the topper's boards off
    # the bus and names them in dump/topper_off
    rows = _rush_rows() + [_row("led", "ALBUM %d" % n, 10, n) for n in range(1, 4)]
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    assert [S["key"] for S in pf.CabinetLights(True).sections] == [
        "topper:12", "speaker:7", "expression:2"]
    monkeypatch.setattr(pf, "topper_off_nodes", lambda: {12, 14})
    assert [S["key"] for S in pf.CabinetLights(True).sections] == [
        "speaker:7", "expression:2"]


def test_the_tick_box_in_the_window(pf):
    assert pf.expression_on() is True
    with open(pf.STATE, "w") as f:
        json.dump({"playfield_pos": [10, 20], "expression_lights": False}, f)
    assert pf.expression_on() is False
    cab = pf.CabinetLights(pf.expression_on())
    assert cab.sections == [] and cab.has_expression
    assert cab.expression_nodes == [2, 7]
    panel = cab.panel()
    assert panel["has_expression"] and panel["expression"] is False


def test_the_tick_box_is_kept_and_takes_effect(pf):
    published = []
    old = pf.CabinetLights(True)
    old.sections[1]["alive"] = True                  # the blades had spoken
    ctl = types.SimpleNamespace(view=types.SimpleNamespace(cab=old),
                                publish=lambda e, d=None: published.append(e))
    assert pf.Playfield.api_expression(ctl, False) is False
    assert json.load(open(pf.STATE)) == {"expression_lights": False}
    assert ctl.view.cab.sections == [] and published == ["layout"]
    assert pf.Playfield.api_expression(ctl, True) is True
    # every section is back at once (PAD-551); what had spoken keeps saying so
    assert [S["key"] for S in ctl.view.cab.shown()] == ["speaker:7", "expression:2"]
    assert not any(S["alive"] for S in ctl.view.cab.sections)
    ctl.view.cab = old
    pf.Playfield.api_expression(ctl, True)
    assert [S["key"] for S in ctl.view.cab.sections if S["alive"]] == ["expression:2"]


def test_the_box_folds_and_is_kept_folded(pf):
    # PAD-532: open until first folded; folded is kept beside the tick box,
    # in the state file, because the page's own storage is private to a run
    assert pf.CabinetLights(True).panel()["open"] is True
    ctl = types.SimpleNamespace()
    with open(pf.STATE, "w") as f:
        json.dump({"expression_lights": False}, f)
    assert pf.Playfield.api_cab_open(ctl, False) is False
    assert json.load(open(pf.STATE)) == {"expression_lights": False,
                                         "cab_panel_open": False}
    assert pf.CabinetLights(True).panel()["open"] is False
    pf.Playfield.api_cab_open(ctl, True)
    assert pf.CabinetLights(True).panel()["open"] is True


def test_the_page_folds_the_box_like_game_hardware():
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8").read()
    body = js[js.index("function cabPanel("):js.index("// ======", js.index("function cabPanel("))]
    assert 'el("details", "kp-acc pf-cabp")' in body
    assert "sum.tabIndex = -1" in body            # the space bar is the Action Button
    assert 'api("cab_open"' in body and "spec.open" in body
    assert "Expression lights" in body


def test_the_schematic_drops_the_blades_and_speakers_blocks(pf):
    S = object.__new__(pf.Schematic)
    S.cab = pf.CabinetLights(False)
    S.leds = types.SimpleNamespace(cells=[], spec=lambda: {"gen": 1, "blocks": [
        {"node": 2, "cells": []}, {"node": 7, "cells": []}, {"node": 8, "cells": []}]})
    S.bar, S.info, S.entries, S.trough, S.shaker = "", [], [], None, None
    spec = S.spec()
    assert [b["node"] for b in spec["grid"]["blocks"]] == [8]
    assert spec["cab_panel"]["expression"] is False
    S.cab = pf.CabinetLights(True)
    assert [b["node"] for b in S.spec()["grid"]["blocks"]] == [2, 7, 8]


def test_the_grid_draws_the_speakers_as_a_ring_and_the_blades_as_columns(pf):
    """Sam, 2026-10-11: "Expression Speaker Lights ... in a circle instead of
    a grid, and the Expression Light Kit in columns". The grid's own cells,
    from the wire, go into the shape by their channels; a pixel the wire has
    not shown keeps its slot empty, and a cell no pixel claims stays a cell."""
    grid = pf.LedGrid(pf.load_led_names())
    b = _block()
    struct.pack_into("<I", b, pf.LED_DECODED_OFF, 1)      # a write was decoded
    for ch in (0, 1, 2, 3, 4, 5):                        # speakers 1 and 2
        b[pf.LED_HDR + 7 * 96 + ch] = 0x40
    for ch in (0, 1, 2):                                 # L 1
        b[pf.LED_HDR + 2 * 96 + ch] = 0x80
    for ch in (144, 145, 146, 287):                      # R 49, R 96-B: in hi
        b[coilmap.HI_OFF + 2 * coilmap.HI_IDX + ch - 96] = 0xFF
    b[pf.LED_HDR + 7 * 96 + 90] = 0x10                   # past the 23 pixels
    grid.tick(bytes(b), 0.0)
    S = object.__new__(pf.Schematic)
    S.cab, S.leds = pf.CabinetLights(True), grid
    S.bar, S.info, S.entries, S.trough, S.shaker = "", [], [], None, None
    blocks = {blk["node"]: blk for blk in S.spec()["grid"]["blocks"]}
    ring = blocks[7]["ring"]
    assert len(ring) == 23 and ring[:2] == ["7:SPEAKER 1", "7:SPEAKER 2"]
    assert ring[2:] == [None] * 21
    assert "7:7.90" in [c["k"] for c in blocks[7]["cells"]]
    left, right = blocks[2]["bars"]
    assert len(left) == len(right) == 48 and "ring" not in blocks[2]
    assert left[0] == "2:EXPRESSIVE LIGHTING L 1"          # bottom first
    assert right[0] == "2:EXPRESSIVE LIGHTING R 49"
    assert right[-1] == "2:EXPRESSIVE LIGHTING R 96"
    assert left[1:] == [None] * 47
    # the tick box off takes both blocks out, shapes and all
    S.cab = pf.CabinetLights(False)
    assert 2 not in {blk["node"] for blk in S.spec()["grid"]["blocks"]}
    assert pf.CabinetLights(False).grid_shapes(grid.cells) == {}


def test_the_schematic_grid_has_the_cabinet_blocks_from_the_start(pf):
    """PAD-551: the switch list's grid grows a block when the wire shows it,
    so a topper or speaker ring the game leaves off in attract had none. The
    cabinet's boards are seeded from the tables: the ring is whole and dark
    before a single write."""
    grid = pf.LedGrid(pf.load_led_names())
    cab = pf.CabinetLights(True)
    grid.seed(cab.channels())
    S = object.__new__(pf.Schematic)
    S.cab, S.leds = cab, grid
    S.bar, S.info, S.entries, S.trough, S.shaker = "", [], [], None, None
    blocks = {blk["node"]: blk for blk in S.spec()["grid"]["blocks"]}
    assert sorted(blocks) == [2, 7]
    assert len(blocks[7]["ring"]) == 23 and None not in blocks[7]["ring"]
    assert blocks[7]["ring"][0] == "7:SPEAKER 1"
    assert None not in blocks[2]["bars"][0] + blocks[2]["bars"][1]
    assert set(grid.dyn().values()) == {0}
    # a board the cabinet does not have (Topper off, PAD-498) is not seeded
    grid = pf.LedGrid({})
    grid.gone = {7}
    grid.seed(cab.channels())
    assert {C["node"] for C in grid.cells} == {2}


# ------------------------------------------------------------------ the page --

def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="needs Node.js")
def test_the_column_layout():
    sections = [
        {"key": "topper:12", "label": "Topper", "node": 12, "board": "Topper",
         "pos": [[0, 20, 30], [1, 286, 30], [2, 150, 56]]},
        {"key": "speaker:7", "label": "Speaker lighting", "node": 7, "board": "",
         "ring": list(range(10, 33))},
        {"key": "expression:2", "label": "Expression lighting", "node": 2, "board": "",
         "bars": [list(range(100, 148)), list(range(148, 196))]},
    ]
    js = ("const { cabLayout, cabHit } = require(%s);\n"
          "const L = cabLayout(%s, 110, 720);\n"
          "const at = (c) => L.marks.find((m) => m.cid === c);\n"
          "process.stdout.write(JSON.stringify({marks: L.marks, labels: L.labels,\n"
          "  hit: cabHit(L.marks, at(147).x, at(147).y)}));"
          % (json.dumps(PF_JS), json.dumps(sections)))
    r = subprocess.run([_node(), "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    by = {m["cid"]: m for m in got["marks"]}
    assert len(by) == 3 + 23 + 96
    for m in got["marks"]:                                   # all inside the column
        half_w, half_h = (m["w"] / 2, m["h"] / 2) if "w" in m else (m["r"], m["r"])
        assert 0 <= m["x"] - half_w and m["x"] + half_w <= 110
        assert 0 <= m["y"] - half_h and m["y"] + half_h <= 720
    # the topper keeps its drawing's shape; the speakers come after it
    assert by[0]["x"] < by[2]["x"] < by[1]["x"] and by[0]["y"] == by[1]["y"] < by[2]["y"]
    assert by[10]["y"] > by[2]["y"]
    # the speakers a ring: pixel 1 at the top, the next one clockwise, every
    # one the same distance from the middle
    ring = [by[c] for c in range(10, 33)]
    cx = sum(m["x"] for m in ring) / 23.0
    cy = sum(m["y"] for m in ring) / 23.0
    radii = [((m["x"] - cx) ** 2 + (m["y"] - cy) ** 2) ** 0.5 for m in ring]
    assert max(radii) - min(radii) < 0.01 and min(radii) > 20
    assert by[10]["y"] == min(m["y"] for m in ring) and abs(by[10]["x"] - cx) < 0.01
    assert by[11]["x"] > by[10]["x"] and by[32]["x"] < by[10]["x"]
    # each blade bottom first, the left one left, both below the speakers
    assert by[100]["y"] > by[147]["y"] and by[148]["y"] > by[195]["y"]
    assert by[100]["x"] < by[148]["x"]
    assert by[147]["y"] - by[147]["h"] / 2 > max(m["y"] + m["r"] for m in ring)
    assert [lb["text"] for lb in got["labels"]] == ["Topper", "Speaker lighting",
                                                    "Expression lighting"]
    assert got["hit"] == 147


@pytest.mark.skipif(_node() is None, reason="needs Node.js")
def test_the_grid_ring_and_columns():
    ring = ["7:SPEAKER %d" % n for n in range(1, 24)]
    ring[5] = None                                       # not shown yet
    bars = [["2:L %d" % n for n in range(1, 49)], ["2:R %d" % n for n in range(49, 97)]]
    js = ("const { gridRing, gridBars } = require(%s);\n"
          "process.stdout.write(JSON.stringify({ring: gridRing(%s), bars: gridBars(%s)}));"
          % (json.dumps(PF_JS), json.dumps(ring), json.dumps(bars)))
    r = subprocess.run([_node(), "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    R, B = got["ring"], got["bars"]
    at = {a["k"]: a for a in R["at"]}
    assert len(at) == 22 and "7:SPEAKER 6" not in at      # its slot stays empty
    for a in R["at"]:                                       # inside the block
        assert 0 <= a["x"] and a["x"] + a["w"] <= R["w"] <= 152
        assert 0 <= a["y"] and a["y"] + a["h"] <= R["h"]
    top = at["7:SPEAKER 1"]
    assert top["y"] == min(a["y"] for a in R["at"])         # pixel 1 at the top
    assert at["7:SPEAKER 2"]["x"] > top["x"] > at["7:SPEAKER 23"]["x"]
    # no two of the ring's round cells overlap
    cells = R["at"]
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            assert ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 >= a["w"]
    # the blades: a column a side, pixel 1 at the bottom, the left one left
    at = {a["k"]: a for a in B["at"]}
    assert len(at) == 96
    assert at["2:L 1"]["x"] == at["2:L 48"]["x"] < at["2:R 49"]["x"]
    assert at["2:L 1"]["y"] > at["2:L 2"]["y"] > at["2:L 48"]["y"] == 0
    assert at["2:L 1"]["y"] == at["2:R 49"]["y"]
    assert at["2:L 1"]["y"] + at["2:L 1"]["h"] <= B["h"]
    assert at["2:R 49"]["x"] + at["2:R 49"]["w"] == B["w"]


# ------------------------------------------------------------------ the shim --

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")


def _extract(src, name):
    m = re.search(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M)
    assert m, "%s not found in hwshim.c" % name
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


#: John Wick LE 1.02, a traced game (PAD-420 lights run): LONG bitmap frames,
#: the form a strip is repainted in bulk. node 2 is the expressive-lighting
#: blades; node 9 a playfield insert board (a mode's light show holds its inserts this way, PAD-658).
JW_LONG = {
    "blades_bank0": "824eb6c008e000ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff"
                    "00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff010100",
    "blades_bank1": "821db2348309f0ff01fc07ff003fff003fff003fff003fff003fff003f018700",
    "blades_bank2": "8267b254c00b0000ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ff"
                    "ff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ffff00ff"
                    "ff00ffff00ffff00ffff00ffff018500",
    "insert_node9": "8913b68919f83820023cffffffffffff00ffff018500",
}
#: batman's b5, lamps 39 and 44 on: a SHORT frame, what the title's vote is drawn from
SHORT = "8905b527ac02e800"

PUBLISH_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void logmsg(const char *s) { fputs(s, stderr); }
@STRUCT@
static struct padled_shm shm;
static struct padled_shm *led_shm = &shm;
static unsigned led_shm_len = 16384;
static unsigned char led_known[16][96], led_wide_owns[16][96];
static int led_wide_verdict = -1;
static unsigned moves, notes;
static void led_map(void) {}
static void led_val(unsigned node, unsigned idx, unsigned char v) { moves++; if (node < 16 && idx < 96) shm.val[node][idx] = v; }
static void led_show_note(unsigned node, unsigned cmd, unsigned weight) { (void)node; (void)cmd; notes += weight; }
static int led_dec_log(void) { return 0; }
@FUNCS@
int main(int argc, char **argv)
{
    int k, i;
    for (k = 1; k < argc; k++) {
        if (!strcmp(argv[k], "send")) {                 /* send <node> <times> <frame hex> */
            unsigned char b[512];
            unsigned node = (unsigned)atoi(argv[k + 1]);
            int times = atoi(argv[k + 2]), n = 0, pub = 0;
            const char *h = argv[k + 3];
            while (h[0] && h[1]) { char t[3] = { h[0], h[1], 0 }; b[n++] = (unsigned char)strtoul(t, 0, 16); h += 2; }
            for (i = 0; i < times; i++) pub += led_wide_publish(node, b[2], b + 3, (unsigned)n - 5);
            printf("PUB %d\n", pub);
            k += 3;
        } else if (!strcmp(argv[k], "q")) {            /* q <node> <channel> */
            unsigned node = (unsigned)atoi(argv[k + 1]), c = (unsigned)atoi(argv[k + 2]);
            printf("LVL %u\n", c < 96 ? shm.val[node][c] : shm.hi[node][c - 96]);
            k += 2;
        } else if (!strcmp(argv[k], "stats")) {
            printf("STATS moves=%u notes=%u settled=%d decoded=%u skipped=%u\n", moves, notes,
                   led_wide_settled(), shm.wide_decoded, shm.wide_skipped);
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def publish_bin(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler on this host")
    src = open(os.path.join(RIG, "hwshim.c"), encoding="utf-8", errors="replace").read()
    struct_src = re.search(r"^struct padled_shm \{.*?^\};", src, re.M | re.S).group(0)
    funcs = "\n".join(_extract(src, n) for n in (
        "popcount8", "led_insert_node", "led_show_cmd", "led_wide_long", "led_wide_walk",
        "led_wide_strip_bank", "led_wide_dialect", "led_wide_settled", "led_hi", "led_seen",
        "led_strip_levels", "led_wide_publish"))
    d = tmp_path_factory.mktemp("ledlong")
    (d / "h.c").write_text(PUBLISH_HARNESS.replace("@STRUCT@", struct_src).replace("@FUNCS@", funcs),
                           encoding="utf-8")
    exe = d / ("h.exe" if os.name == "nt" else "h")
    r = subprocess.run([CC, "-O1", "-o", str(exe), str(d / "h.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(exe)


def _run(exe, *args):
    env = dict(os.environ)
    env.pop("PAD_LED_WIDE", None)
    r = subprocess.run([exe] + list(args), capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.split("\n")


def test_a_strip_s_long_frames_are_read_once_the_title_has_settled(publish_bin):
    import leddecode
    want = {}
    for name in ("blades_bank0", "blades_bank1", "blades_bank2"):
        bank, idxs, vals = leddecode.wide_decode_any(bytes.fromhex(JW_LONG[name]))
        for i, v in zip(idxs, vals):
            want[96 * bank + i] = v
    probe = [0, 1, 2, 96, 98, 192, 193, 287]
    assert {want[c] for c in probe} == {0, 63, 255}       # a probe that can tell
    out = _run(publish_bin,
               # before the vote: a long frame votes no and is not published
               "send", "2", "1", JW_LONG["blades_bank0"], "q", "2", "1", "stats",
               # the title proves the dialect on short frames
               "send", "9", "220", SHORT, "stats",
               # now the strip's long frames land, bank 0 in val[], 1 and 2 in hi
               "send", "2", "1", JW_LONG["blades_bank0"],
               "send", "2", "1", JW_LONG["blades_bank1"],
               "send", "2", "1", JW_LONG["blades_bank2"],
               *sum((["q", "2", str(c)] for c in probe), []),
               # PAD-658: an insert board's long frame lands too (lamps 11 and 77 on, 75 off)
               "send", "9", "1", JW_LONG["insert_node9"], "q", "9", "11", "q", "9", "75", "q", "9", "77", "stats")
    assert out[0] == "PUB 0" and out[1] == "LVL 0"
    assert "settled=0" in out[2] and "moves=0" in out[2]
    # the first 199 calls only vote (the sample is 200, the long frame was one)
    assert out[3] == "PUB 22"
    before = out[4]
    assert "settled=1" in before
    assert out[5:8] == ["PUB 1", "PUB 1", "PUB 1"]
    assert out[8:8 + len(probe)] == ["LVL %d" % want[c] for c in probe]
    rest = out[8 + len(probe):]
    assert rest[0:4] == ["PUB 1", "LVL 255", "LVL 0", "LVL 255"]
    # levels only: the announcer's moves and notes did not move for any of it
    m = lambda s, k: re.search(r"%s=(\d+)" % k, s).group(1)   # noqa: E731
    assert m(rest[4], "moves") == m(before, "moves")
    assert m(rest[4], "notes") == m(before, "notes")
    assert int(m(rest[4], "decoded")) == int(m(before, "decoded")) + 4


@pytest.mark.skipif(CC is None, reason="no C compiler on this host")
def test_the_shim_puts_banks_1_to_4_in_hi(tmp_path):
    src = open(os.path.join(RIG, "hwshim.c"), encoding="utf-8", errors="replace").read()
    struct_src = re.search(r"^struct padled_shm \{.*?^\};", src, re.M | re.S).group(0)
    hdr = open(os.path.join(RIG, "padled.h"), encoding="utf-8").read()
    hdr_struct = re.search(r"^struct padled_shm \{.*?^\};", hdr, re.M | re.S).group(0)
    hdr_struct = hdr_struct.replace("struct padled_shm", "struct padled_hdr")
    prog = r"""
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#define PADLED_NODES 16
#define PADLED_IDX 96
#define PADLED_COILS 16
%s
%s
static struct padled_shm shm;
static struct padled_shm *led_shm = &shm;
static unsigned led_shm_len = 16384;
%s
int main(void)
{
    unsigned char idx[3] = { 0, 95, 7 }, val[3] = { 0x11, 0x22, 0x33 };
    printf("%%u %%u %%u\n", (unsigned)offsetof(struct padled_shm, hi),
           (unsigned)offsetof(struct padled_hdr, hi), (unsigned)sizeof(shm.hi));
    led_hi(2, 1, idx, val, 3);          /* channels 96, 191, 103 */
    led_hi(2, 3, idx, val, 1);          /* channel 288 */
    led_hi(2, 0, idx, val, 3);          /* bank 0 is val[]'s, not this */
    led_hi(2, 5, idx, val, 3);          /* past the plane */
    printf("%%u %%u %%u %%u %%u\n", shm.hi[2][0], shm.hi[2][95], shm.hi[2][7],
           shm.hi[2][192], shm.hi[2][383]);
    led_shm_len = 8192;                 /* an older watch.sh's file */
    memset(&shm, 0, sizeof shm);
    led_hi(2, 1, idx, val, 3);
    printf("%%u\n", shm.hi[2][0]);
    return 0;
}
""" % (struct_src, hdr_struct, _extract(src, "led_hi"))
    c = tmp_path / "hi.c"
    c.write_text(prog, encoding="utf-8")
    exe = tmp_path / ("hi.exe" if os.name == "nt" else "hi")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(c)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True).stdout.split("\n")
    assert out[0].split() == [str(coilmap.HI_OFF), str(coilmap.HI_OFF), str(coilmap.HI_IDX * 16)]
    assert out[1].split() == ["17", "34", "51", "17", "0"]
    assert out[2].strip() == "0"
