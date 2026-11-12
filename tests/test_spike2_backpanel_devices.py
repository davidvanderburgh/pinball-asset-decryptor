"""PAD-705: the devices Stern draws on the back panel.

devicexy refused every record whose image is the bare word `backpanel` (no
folder, so no "/"): the back-panel lamps on Avengers, Deadpool, Iron Maiden,
Bond, Jaws, John Wick, Jurassic Park, Stranger Things and X-Men, and switches
and coils on Iron Maiden, Star Wars LE and Stranger Things LE. Iron Maiden LE
also lost three playfield flashers that sat in a run the back-panel rows broke.

Measured over the newest card of every title (60): 20 builds gain records, no
other changes; the lamps are drawn as a Backpanel section of the cabinet
column. The worst-case switch-name fill (every name `?`) over the 33 cached
titles only gains: Iron Maiden LE 26 names, Stranger Things LE 2; Star Wars
LE's one stray `9d` connector is what swnames now refuses.
"""
import collections
import json
import os
import shutil
import struct
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
PF_JS = os.path.join(RIG, "pfpage", "pf.js")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)

import cablights                                   # noqa: E402
import devicexy                                    # noqa: E402
import swnames                                     # noqa: E402

STRIDE = devicexy.STRIDE
BIAS = devicexy.VA_BIAS
TABLE = 0x2000


def _blob(recs, standalone=True):
    """A binary holding `recs` - (image, cls, name, group, index, x, y, w, h) -
    as one run at a true stride. Names go in the PREVIOUS slot
    (devicexy.NAME_OFF). `standalone=False` keeps `backpanel` only as the tail
    of a longer string, the way a linker merges a suffix."""
    buf = bytearray(0x4000)
    at = [0x0010]

    def string(raw):
        off = at[0]
        buf[off:off + len(raw) + 1] = raw + b"\x00"
        at[0] += len(raw) + 1
        return off + BIAS

    imgs = {"playfield": string(b"playfield")}
    if standalone:
        imgs["backpanel"] = string(b"backpanel")
    else:
        imgs["backpanel"] = string(b"Test/x_backpanel") + len(b"Test/x_")
    for i, (img, cls, name, grp, idx, x, y, w, h) in enumerate(recs):
        rec = TABLE + i * STRIDE
        struct.pack_into("<I", buf, rec + 0x00, imgs[img])
        struct.pack_into("<hh", buf, rec + 0x04, grp, idx)
        struct.pack_into("<hh", buf, rec + 0x08, cls, 2)
        struct.pack_into("<hhhh", buf, rec + 0x10, x, y, w, h)
        struct.pack_into("<I", buf, rec + devicexy.NAME_OFF, string(name.encode()))
    return bytes(buf)


def _records(tmp_path, recs, **kw):
    p = tmp_path / "game.bin"
    p.write_bytes(_blob(recs, **kw))
    d, cstr = devicexy.load(str(p))
    return sorted(devicexy.records(d, cstr), key=lambda r: r["va"])


def _iron_maiden():
    """Iron Maiden LE 1.18.0's group 7, as it ships: playfield flashers between
    back-panel lamps and switches, and two lamps with no place on the panel."""
    return [("playfield", 1, "LEFT OUTLANE", 6, 1, 20, 600, 20, 20),
            ("playfield", 1, "LEFT RETURN LANE", 6, 2, 40, 580, 20, 20),
            ("playfield", 1, "LEFT SLING", 6, 3, 60, 560, 20, 20),
            ("backpanel", 1, "DIVERTER MOTOR UP", 7, 0, 118, 48, 20, 20),
            ("backpanel", 1, "DIVERTER MOTOR DOWN", 7, 1, 118, 96, 20, 20),
            ("backpanel", 3, "BACKPANEL GI", 7, 2, 0, 0, 0, 0),
            ("playfield", 3, "TOMB FLASH", 7, 3, 84, 200, 20, 20),
            ("playfield", 3, "PHARAOH FLASH", 7, 4, 308, 70, 20, 20),
            ("playfield", 3, "SARCOPHAGUS FLASH", 7, 5, 165, 129, 20, 20),
            ("backpanel", 3, "BULLSEYE CENTER BLU", 7, 6, 308, 131, 20, 20),
            ("backpanel", 3, "BULLSEYE RED (X2)", 7, 7, 0, 0, 0, 0),
            ("backpanel", 1, "BULLS EYE", 7, 9, 309, 132, 20, 20),
            ("playfield", 1, "RIGHT OUTLANE", 6, 4, 290, 600, 20, 20),
            ("playfield", 1, "RIGHT RETURN LANE", 6, 5, 270, 580, 20, 20),
            ("playfield", 1, "RIGHT SLING", 6, 6, 250, 560, 20, 20)]


# ------------------------------------------------------------------ devicexy --

def test_backpanel_records_are_read(tmp_path):
    """Every record comes back, the playfield flashers between them too."""
    recs = _records(tmp_path, _iron_maiden())
    assert [(r["name"], r["kind"], r["image"]) for r in recs] == [
        (n, {1: "switch", 3: "led"}[c], img)
        for img, c, n, *_ in _iron_maiden()]
    # the layout is still the playfield's; the back panel never wins the vote
    assert devicexy.layout_image(recs) == "playfield"
    # an unplaced back-panel lamp is kept: the panel is not the layout
    assert [r["name"] for r in recs if devicexy._unplaced(r)] == [
        "BACKPANEL GI", "BULLSEYE RED (X2)"]


def test_a_merged_backpanel_tail_is_seeded(tmp_path):
    """`backpanel` kept only as the tail of a longer string is still found,
    the way godzilla_le's `playfield` is (seeds())."""
    panel = [("backpanel", 3, "BACKPANEL FLASH %d" % n, 8, 45 + n, 200 + 40 * n,
              172, 20, 20) for n in range(1, 6)]
    recs = _records(tmp_path, panel, standalone=False)
    assert len(recs) == 5 and {r["image"] for r in recs} == {"backpanel"}


def test_another_bare_word_is_still_refused(tmp_path):
    rows = [("playfield",) + r[1:] for r in _iron_maiden()]
    blob = bytearray(_blob(rows))
    # point the first four records at a bare word that is no image name
    word = blob.index(b"playfield")
    blob[word:word + 9] = b"ballfield"
    p = tmp_path / "game.bin"
    p.write_bytes(bytes(blob))
    d, cstr = devicexy.load(str(p))
    assert devicexy.records(d, cstr) == []


def test_the_reader_revision_moved():
    """Cached tables from the old reader are rebuilt (mktables)."""
    assert devicexy.READER_REV >= 5


# ------------------------------------------------------------------ swnames --

def _dev(name, group, index, kind="switch", conn=""):
    return dict(name=name, group=group, index=index, conn=conn, image="backpanel",
                cls={"switch": 1, "coil": 2, "led": 3}[kind], kind=kind,
                x=1, y=1, w=20, h=20)


def test_a_group_outnamed_on_its_node_is_placed_by_its_bits(monkeypatch):
    """star_wars_le 1.31.0: the accelerator (group 10, node 11 on the wire)
    carries one connector, `9d`, against group 8's 36 naming node 9. Its four
    optos must not be filed on node 9, where their indices happen to fit."""
    recs = [_dev("SW %d" % i, 8, i, "led", "9%s" % "abc"[i % 3]) for i in range(36)]
    recs += [_dev("FORC(E) DROP TARGET", 8, 4), _dev("FORK RAMP HOME", 8, 5)]
    recs += [_dev("ACCELERATOR MAGNET 4", 10, 3, "coil", "9d")]
    recs += [_dev("ACCELERATOR OPTO %d" % n, 10, 3 + n) for n in range(1, 5)]
    monkeypatch.setattr(swnames.devicexy, "build", lambda **kw: recs)
    bits = {9: set(range(32)), 11: {4, 5, 6, 7}}
    names = {(9, 4): "FORC(E) DROP TARGET", (9, 5): "FORK RAMP HOME",
             (11, 4): "ACCELERATOR OPTO 1", (11, 5): "ACCELERATOR OPTO 2"}
    out = swnames.device_switches(bits_by_node=bits, names=names)
    assert [r["name"] for r in out[9]] == ["FORC(E) DROP TARGET", "FORK RAMP HOME"]
    assert [r["name"] for r in out[11]] == ["ACCELERATOR OPTO %d" % n
                                           for n in range(1, 5)]
    # with nothing to tell the boards apart, the group is left unplaced
    out = swnames.device_switches(bits_by_node=bits, names={})
    assert all(not r["name"].startswith("ACCEL") for r in out.get(9, []))


def test_a_group_alone_on_its_node_keeps_its_connector(monkeypatch):
    recs = [_dev("BULLS EYE", 7, 9, conn="9a"), _dev("INNER RING", 7, 10),
            _dev("OUTER RING", 7, 11)]
    monkeypatch.setattr(swnames.devicexy, "build", lambda **kw: recs)
    out = swnames.device_switches(bits_by_node={9: {9, 10, 11}}, names={})
    assert [r["name"] for r in out[9]] == ["BULLS EYE", "INNER RING", "OUTER RING"]


# ------------------------------------------------------------------ cablights --

def _lamp(name, group, index, x, y, image="backpanel"):
    w = 20 if (x or y) else 0
    return dict(kind="led", name=name, group=group, index=index, x=x, y=y,
                w=w, h=w, image=image, conn="")


#: Avengers' back panel: glove gems on group 6 (node 8), flashers on group 7
#: (node 9), plus Deadpool's unplaced BACKPANEL GI
AVENGERS = ([_lamp("GLOVE GEM %d" % n, 6, 27 + n, 390 + 10 * n, 40) for n in range(1, 7)]
            + [_lamp("BACKPANEL FLASH %d" % n, 7, 47 + n, 250 + 40 * n, 60)
               for n in range(1, 4)]
            + [_lamp("BACKPANEL GI", 7, 2, 0, 0),
               _lamp("LEFT ORBIT", 7, 3, 40, 300, "playfield")])


def test_the_back_panel_is_one_section_across_its_boards():
    assert cablights.role(AVENGERS[0]) == "backpanel"
    assert cablights.role(AVENGERS[-1]) is None
    secs, left = cablights.sections(AVENGERS, {6: 8, 7: 9}, {})
    assert left == [] and [S["key"] for S in secs] == ["backpanel"]
    S = secs[0]
    assert (S["label"], S["node"], S["nodes"]) == ("Backpanel", 8, [8, 9])
    assert cablights.where(S) == "nodes 8, 9"
    assert len(S["pixels"]) == 10 and S["positioned"]
    gi = [P for P in S["pixels"] if P["name"] == "BACKPANEL GI"]
    assert gi and not gi[0]["placed"] and gi[0]["channels"] == {"W": (9, 2)}


def test_only_the_measured_map_places_the_back_panel():
    secs, left = cablights.sections(
        AVENGERS, {}, {8: {"type": "pinnode", "group": 6, "name": "Lower"}})
    assert secs == [] and sum(n for w, n, _ in left if w == "backpanel") == 10


def test_the_back_panel_sits_below_the_speakers():
    rows = AVENGERS + [_lamp("SPEAKER 1-R", 9, 0, 0, 0, "")]
    secs, _ = cablights.sections(rows, {6: 8, 7: 9, 9: 7}, {})
    assert [S["role"] for S in secs] == ["speaker", "backpanel"]


def test_the_window_sends_the_shape_and_a_row_for_the_unplaced(monkeypatch, tmp_path):
    import playfield as pf
    monkeypatch.setattr(pf, "DEV_ROWS", AVENGERS)
    monkeypatch.setattr(pf, "GROUP_NODE", {6: 8, 7: 9})
    monkeypatch.setattr(pf, "LAYOUT_IMAGE", "playfield")
    monkeypatch.setattr(pf, "STATE", str(tmp_path / "pad_playfield.json"))
    monkeypatch.setattr(pf, "load_boards", lambda: {})
    monkeypatch.setattr(pf, "topper_off_nodes", lambda: set())
    cab = pf.CabinetLights(True)
    spec = cab.spec()
    assert [s["key"] for s in spec] == ["backpanel"]
    s = spec[0]
    assert s["where"] == "nodes 8, 9" and len(s["pos"]) == 9
    assert [cab.pixels[c]["name"] for c in s["row"]] == ["BACKPANEL GI"]
    assert cab.panel()["lines"][0][:2] == ["Backpanel", "nodes 8, 9"]
    # the inserts are not the back panel's, and the back panel is no insert
    assert [L["name"] for L in pf.load_leds()] == ["LEFT ORBIT"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_column_draws_the_shape_then_the_row():
    sections = [{"key": "backpanel", "label": "Backpanel", "node": 8,
                 "where": "nodes 8, 9", "board": "",
                 "pos": [[0, 290, 71], [1, 328, 40], [2, 359, 40]], "row": [3]}]
    js = ("const { cabLayout } = require(%s);\n"
          "process.stdout.write(JSON.stringify(cabLayout(%s, 110, 720)));"
          % (json.dumps(PF_JS), json.dumps(sections)))
    r = subprocess.run([shutil.which("node"), "-e", js], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    by = {m["cid"]: m for m in got["marks"]}
    assert sorted(by) == [0, 1, 2, 3]
    assert by[0]["x"] < by[1]["x"] < by[2]["x"] and by[1]["y"] == by[2]["y"] < by[0]["y"]
    assert by[3]["y"] > max(by[c]["y"] for c in (0, 1, 2))
    assert got["labels"][0]["sub"] == "nodes 8, 9"


# ------------------------------------------------- back-panel switches (PAD-1179) --

KK_PANEL = "TestMode/Rodeo_LE_Service_Backpanel_Wireframe_300dpi_cropped"


def _sw(name, x, y, image="backpanel", group=7, index=9):
    return dict(kind="switch", name=name, x=x, y=y, w=20, h=20, group=group,
                index=index, image=image, conn="")


#: Iron Maiden LE 1.18.0's switches: two on the playfield, its bullseye and
#: the diverter's sensors on the back panel, and a service button elsewhere
IRON_MAIDEN_SW = [_sw("LEFT OUTLANE", 20, 600, "playfield", 6, 1),
                  _sw("DIVERTER MOTOR UP", 118, 48, index=0),
                  _sw("BULLS EYE", 309, 132, index=9),
                  _sw("INNER RING", 309, 143, index=10),
                  _sw("OUTER RING", 309, 159, index=11),
                  _sw("START BUTTON", 50, 50, "System/TestMode/chuck_buttons_cropped")]
IRON_MAIDEN_LIST = [dict(id=i, node=n, bit=b, name=nm) for i, n, b, nm in (
    (20, 8, 1, "Left Outlane"), (76, 9, 0, "Diverter Motor Up"),
    (83, 9, 9, "Bulls Eye"), (84, 9, 10, "Inner Ring"), (85, 9, 11, "Outer Ring"),
    (1, 1, 0, "Start Button"))]


def test_a_picture_named_for_the_back_panel_is_the_back_panel():
    assert cablights.is_backpanel_image("backpanel")
    assert cablights.is_backpanel_image(KK_PANEL)
    assert not cablights.is_backpanel_image("Test/scaled_playfield")
    assert not cablights.is_backpanel_image("")
    # King Kong LE's waterfall flasher joins the Backpanel section
    assert cablights.role(_lamp("WATERFALL FLASH", 8, 66, 76, 75, KK_PANEL)) == "backpanel"


def _field_tables(monkeypatch, rows, switch_list):
    import playfield as pf
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf, "LAYOUT_IMAGE", "playfield")
    monkeypatch.setattr(pf, "load_switch_list", lambda: list(switch_list))
    return pf


def test_the_back_panel_switches_join_the_live_table(monkeypatch):
    pf = _field_tables(monkeypatch, IRON_MAIDEN_SW, IRON_MAIDEN_LIST)
    got = pf.load_panel_switches()
    assert [(S["name"], S["id"], S["node"], S["bit"]) for S in got] == [
        ("DIVERTER MOTOR UP", 76, 9, 0), ("BULLS EYE", 83, 9, 9),
        ("INNER RING", 84, 9, 10), ("OUTER RING", 85, 9, 11)]
    # a switch the running game does not name cannot be pressed: left out
    pf = _field_tables(monkeypatch, IRON_MAIDEN_SW, IRON_MAIDEN_LIST[:3])
    assert [S["name"] for S in pf.load_panel_switches()] == [
        "DIVERTER MOTOR UP", "BULLS EYE"]
    # no table yet (a first run): nothing, and no error
    pf = _field_tables(monkeypatch, IRON_MAIDEN_SW, [])
    assert pf.load_panel_switches() == []


def test_king_kong_les_train_opto_is_a_back_panel_switch(monkeypatch):
    rows = [_sw("TRAIN ENTER OPTO", 257, 128, KK_PANEL, 8, 6)]
    pf = _field_tables(monkeypatch, rows, [dict(id=40, node=10, bit=6,
                                                name="Train Enter Opto")])
    assert [S["id"] for S in pf.load_panel_switches()] == [40]


def _field_stub(pf, cab_sections, panel_sw, switches=()):
    import types

    class Cab:
        def spec(self):
            return [dict(s) for s in cab_sections]
    return types.SimpleNamespace(cab=Cab(), panel_sw=panel_sw, base=(313, 710),
                                 switches=list(switches))


def test_the_backpanel_section_carries_its_switches(monkeypatch):
    pf = _field_tables(monkeypatch, IRON_MAIDEN_SW, IRON_MAIDEN_LIST)
    top = {"key": "topper:12", "role": "topper", "label": "Topper", "node": 12}
    bp = {"key": "backpanel", "role": "backpanel", "label": "Backpanel", "node": 9,
          "pos": [[0, 34, 67], [1, 137, 67]]}
    # a switch the playfield already draws is not drawn twice
    stub = _field_stub(pf, [top, bp], None, switches=[dict(id=76)])
    stub.panel_sw = pf.Field._panel_switches(stub)
    spec = pf.Field.cab_spec(stub)
    s = [S for S in spec["sections"] if S["key"] == "backpanel"][0]
    assert s["sw"] == [[0, "BULLS EYE", 83], [1, "INNER RING", 84],
                       [2, "OUTER RING", 85]]
    assert s["pos"] == bp["pos"]
    # the tooltip names it and says where it is
    tip = pf.Field.describe(stub, "panelsw", 0)
    assert tip.startswith("SWITCH  BULLS EYE\nid 83   node 9  bit 9\non the back panel")


def test_switches_alone_make_a_backpanel_section(monkeypatch):
    """Star Wars LE's accelerator optos: a back panel with no lamps placed."""
    pf = _field_tables(monkeypatch, [], [])
    top = {"key": "topper:12", "role": "topper", "label": "Topper", "node": 12}
    sw = [dict(id=90 + n, node=11, bit=3 + n, name="ACCELERATOR OPTO %d" % n)
          for n in range(1, 5)]
    spec = pf.Field.cab_spec(_field_stub(pf, [top], sw))
    assert [S["key"] for S in spec["sections"]] == ["topper:12", "backpanel"]
    s = spec["sections"][1]
    assert (s["label"], s["where"], len(s["sw"])) == ("Backpanel", "node 11", 4)
    # and a title with no cabinet lights at all still gets its column
    assert pf.Field.cab_spec(_field_stub(pf, [], sw))["sections"][0]["key"] == "backpanel"
    assert pf.Field.cab_spec(_field_stub(pf, [], [])) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_column_lists_the_back_panel_switches_under_its_lamps():
    sections = [{"key": "backpanel", "label": "Backpanel", "node": 9,
                 "where": "node 9", "board": "",
                 "pos": [[0, 34, 67], [1, 137, 67], [2, 308, 131]], "row": [3],
                 "sw": [[0, "BULLS EYE", 83], [1, "INNER RING", 84],
                        [2, "OUTER RING", 85]]}]
    js = ("const { cabLayout, cabSwHit } = require(%s);\n"
          "const L = cabLayout(%s, 110, 720);\n"
          "const s = L.switches[1];\n"
          "L.hit = [cabSwHit(L.switches, 110, s.x + 40, s.y + 2), cabSwHit(L.switches, 110, s.x, 1)];\n"
          "process.stdout.write(JSON.stringify(L));"
          % (json.dumps(PF_JS), json.dumps(sections)))
    r = subprocess.run([shutil.which("node"), "-e", js], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    sw = got["switches"]
    assert [(s["name"], s["id"], s["k"]) for s in sw] == [
        ("BULLS EYE", 83, 0), ("INNER RING", 84, 1), ("OUTER RING", 85, 2)]
    # under every lamp, one row each, far enough apart to click
    assert sw[0]["y"] > max(m["y"] for m in got["marks"])
    assert sw[1]["y"] - sw[0]["y"] >= 13 and sw[0]["r"] >= 3.5
    # the row's name is part of it; a point above the list is nothing
    assert got["hit"][0]["k"] == 1 and got["hit"][1] is None
