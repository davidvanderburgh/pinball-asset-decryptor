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
    assert [(S["label"], S["node"]) for S in secs] == [("Topper", 12), ("Topper Lights", 14)]
    assert all(S["positioned"] for S in secs) and left == []


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


def test_a_section_shows_once_its_board_has_spoken(pf):
    cab = pf.CabinetLights(True)
    b = _block()
    changes, grew = cab.tick(bytes(b))
    assert cab.spec() == [] and not grew       # nothing from either board yet
    # the right blade's top pixel, channels 285-287 - all three past index 95
    for ch, v in ((285, 0x00), (286, 0xFF), (287, 0x00)):
        b[coilmap.HI_OFF + 2 * coilmap.HI_IDX + ch - 96] = v
    changes, grew = cab.tick(bytes(b))
    assert grew
    spec = cab.spec()
    assert [s["key"] for s in spec] == ["expression:2"]
    top = spec[0]["bars"][1][-1]
    assert changes[top][:3] == [255, 0, 0] and changes[top][3] > 0.5
    assert cab.dyn()[top] == changes[top]
    # the speakers speak through the `seen` plane before they light
    b[pf.SEEN_OFF + 7 * 96 + 0] = 1
    _c, grew = cab.tick(bytes(b))
    assert grew and [s["key"] for s in cab.spec()] == ["speaker:7", "expression:2"]
    assert "R=channel 286" in cab.describe(top) and "Cabinet Lights" in cab.describe(top)


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
    # what had already spoken is shown at once, the speakers still wait
    assert [S["key"] for S in ctl.view.cab.shown()] == []
    ctl.view.cab = old
    pf.Playfield.api_expression(ctl, True)
    assert [S["key"] for S in ctl.view.cab.shown()] == ["expression:2"]


def test_the_schematic_drops_the_blades_and_speakers_blocks(pf):
    S = object.__new__(pf.Schematic)
    S.cab = pf.CabinetLights(False)
    S.leds = types.SimpleNamespace(spec=lambda: {"gen": 1, "blocks": [
        {"node": 2, "cells": []}, {"node": 7, "cells": []}, {"node": 8, "cells": []}]})
    S.bar, S.info, S.entries, S.trough = "", [], [], None
    spec = S.spec()
    assert [b["node"] for b in spec["grid"]["blocks"]] == [8]
    assert spec["cab_panel"]["expression"] is False
    S.cab = pf.CabinetLights(True)
    assert [b["node"] for b in S.spec()["grid"]["blocks"]] == [2, 7, 8]


# ------------------------------------------------------------------ the page --

def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="needs Node.js")
def test_the_column_layout():
    sections = [
        {"key": "topper:12", "label": "Topper", "node": 12, "board": "Topper",
         "pos": [[0, 20, 30], [1, 286, 30], [2, 150, 56]]},
        {"key": "speaker:7", "label": "Speaker lighting", "node": 7, "board": "",
         "row": list(range(10, 33))},
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
    # each blade bottom first, the left one left, both below the speakers
    assert by[100]["y"] > by[147]["y"] and by[148]["y"] > by[195]["y"]
    assert by[100]["x"] < by[148]["x"] and by[147]["y"] > by[32]["y"]
    assert [lb["text"] for lb in got["labels"]] == ["Topper", "Speaker lighting",
                                                    "Expression lighting"]
    assert got["hit"] == 147


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
