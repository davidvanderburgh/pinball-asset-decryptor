"""The virtual playfield as a web page: the controller's side of the contract.

The page (tools/spike2_emu/pfpage/pf.js) draws what /state and the "frame"
events say, and sends back what was pressed. These pin the shape of what it is
told for each of the window's three states (the artwork, the switch list, the
WAITING page), that a frame carries only what changed, that the waiting page
turns into a view by itself when the tables land, and the keyboard's names -
the page sends KeyboardEvent.code and the rows are keyed by Tk keysym names
(keybinds.py), so the translation between the two is the whole of "keys work
with the playfield focused".

Every WSL helper is stubbed before anything is built: nothing here may reach
wsl.exe or a rig.
"""
import json
import os
import shutil
import struct
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


@pytest.fixture()
def pf(monkeypatch, tmp_path):
    import playfield
    ran = []
    monkeypatch.setattr(playfield, "wsl_run",
                        lambda script, *a: ran.append((script,) + a) or None)
    monkeypatch.setattr(playfield, "state_run", lambda *a, **k: None)
    monkeypatch.setattr(playfield, "state_slots", lambda: {})
    monkeypatch.setattr(playfield.SwitchPipe, "_ensure", lambda self: False)
    monkeypatch.setattr(playfield, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(playfield, "BINDS_PATH", str(tmp_path / "padbinds"))
    monkeypatch.setattr(playfield, "BALL_PATH", str(tmp_path / "padball"))
    monkeypatch.setattr(playfield, "SW_PATH", str(tmp_path / "padsw"))
    monkeypatch.setattr(playfield, "LED_PATH", str(tmp_path / "padled"))
    monkeypatch.setattr(playfield, "LCD_PATH", str(tmp_path / "padlcd"))
    playfield._ran = ran
    return playfield


def test_the_page_key_names_become_the_rows_keysyms(pf):
    c = pf.code_to_keysym
    assert c("KeyA") == "a" and c("KeyZ") == "z"
    assert c("Digit1") == "1" and c("Digit5") == "5"
    for code, sym in (("Enter", "Return"), ("NumpadEnter", "KP_Enter"),
                      ("Backspace", "BackSpace"), ("Escape", "Escape"),
                      ("Space", "space"), ("Equal", "equal"),
                      ("Minus", "minus"), ("ArrowLeft", "Left"),
                      ("ArrowRight", "Right"), ("ArrowUp", "Up"),
                      ("ArrowDown", "Down")):
        assert c(code) == sym, code
    assert c("F5") is None and c("") is None and c("ShiftLeft") is None
    # every key name the renderer exports resolves from some page code
    import keybinds
    reachable = {c(k) for k in list(pf.CODE_KEYSYM) + [
        "Key%s" % ch for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + [
        "Digit%d" % d for d in range(10)]}
    for label in ("Enter", "KP Ent", "Bksp", "Esc", "Space", "=", "-",
                  "Left", "Right", "Up", "1", "5", "A", "Q", "Z"):
        assert set(keybinds.tk_keysyms(label)) & reachable, label


def test_a_title_with_no_tables_waits_and_its_keys_still_work(pf, monkeypatch):
    monkeypatch.setattr(pf, "layout_is_usable", lambda: False)
    monkeypatch.setattr(pf, "load_switch_list", lambda: [])
    ctl = pf.Playfield()
    st = ctl.state("main")
    assert st["kind"] == "waiting" and "WAITING" in st["waiting"]
    assert st["acts"] == [] and st["panel"] is None
    # the boot menu's buttons by name, with no table at all
    sent = []
    monkeypatch.setattr(ctl.keys.pipe, "set_cab",
                        lambda name, val: sent.append((name, val)) or True)
    assert ctl.api_key("ArrowLeft", "ArrowLeft", True) is True
    assert ctl.api_key("ArrowLeft", "ArrowLeft", False) is True
    assert sent == [("left", 1), ("left", 0)]


def test_the_waiting_page_becomes_the_switch_list_when_the_table_lands(
        pf, monkeypatch):
    rows = []
    monkeypatch.setattr(pf, "layout_is_usable", lambda: False)
    monkeypatch.setattr(pf, "load_switch_list", lambda: list(rows))
    monkeypatch.setattr(pf, "TABLES_EVERY_S", 0.0)
    published = []

    class Host:
        def publish(self, etype, data=None):
            published.append(etype)
    ctl = pf.Playfield()
    ctl.host = Host()
    ctl._wait_next = 0
    ctl._tick()
    assert ctl.kind == "waiting" and "layout" not in published
    rows.append(dict(id=34, num=1, node=1, bit=4, name="ACTION BUTTON"))
    ctl._wait_next = 0
    ctl._tick()
    assert ctl.kind == "schematic" and "layout" in published
    st = ctl.state("main")
    assert [e.get("name") for e in st["view"]["entries"]
            if "id" in e] == ["ACTION BUTTON"]


def _led_block(pf, lit):
    """A stamped version-4 padled with channel (node, idx) -> level."""
    b = bytearray(pf.PADLED_READ)
    struct.pack_into("<I", b, 0, pf.PADLED_MAGIC)
    struct.pack_into("<I", b, 4, 4)
    struct.pack_into("<I", b, pf.LED_DECODED_OFF, 7)
    for (node, idx), v in lit.items():
        b[pf.LED_HDR + node * pf.LED_IDX + idx] = v
    return bytes(b)


def test_a_frame_carries_only_what_changed(pf, monkeypatch, tmp_path):
    fixtures = [dict(name="INSERT 1", channels={"W": (8, 3)}, x=10, y=20,
                     group=6),
                dict(name="SHIELD", channels={"R": (9, 0), "G": (9, 1),
                                              "B": (9, 2)}, x=30, y=40,
                     group=7)]
    monkeypatch.setattr(pf, "layout_is_usable", lambda: True)
    monkeypatch.setattr(pf, "load_switches", lambda: [])
    monkeypatch.setattr(pf, "load_switch_list", lambda: [])
    monkeypatch.setattr(pf, "load_leds", lambda: [])
    monkeypatch.setattr(pf, "load_coils", lambda: [])
    monkeypatch.setattr(pf, "group_fixtures", lambda leds: [dict(f) for f in fixtures])
    monkeypatch.setattr(pf, "layout_art", lambda: None)
    monkeypatch.setattr(pf, "layout_extent", lambda pad=14: (100, 200))
    monkeypatch.setattr(pf, "FADE_MS", 0.0)
    ctl = pf.Playfield()
    view = ctl.view
    assert ctl.kind == "field"
    spec = ctl.state("main")["view"]
    assert spec["art"] is None and spec["base"] == [100, 200]
    assert [f[0] for f in spec["fixtures"]] == [0, 1]
    with open(pf.LED_PATH, "wb") as f:
        f.write(_led_block(pf, {(8, 3): 255}))
    frame = view.tick(0.0)
    assert frame["fx"][0][:3] == [255, 255, 255]    # one colour, not set: white (PAD-668)
    assert frame["fx"][1] == 0                      # painted dark, once
    # nothing moved: nothing painted again
    frame = view.tick(0.0)
    assert "fx" not in frame
    # the RGB fixture lights in the colour its channels compose to
    with open(pf.LED_PATH, "wb") as f:
        f.write(_led_block(pf, {(8, 3): 255, (9, 0): 255, (9, 2): 255}))
    frame = view.tick(0.0)
    assert list(frame["fx"]) == [1]
    r, g, b, a, rad = frame["fx"][1]
    assert (r, g, b) == (255, 0, 255) and a == 1.0
    # the run ends: its LED block goes, and after the grace the window leaves
    os.remove(pf.LED_PATH)
    gone = None
    for _ in range(pf.GONE_POLLS + 2):
        gone = view.tick(0.0)
        if gone is None:
            break
    assert gone is None


def _one_colour_field(pf, monkeypatch):
    fixtures = [dict(name="MASER", channels={"W": (8, 3)}, x=10, y=20, group=6),
                dict(name="SHIELD", channels={"R": (9, 0), "G": (9, 1), "B": (9, 2)}, x=30, y=40, group=7),
                dict(name="BRIDGE", channels={"W": (8, 4)}, x=50, y=60, group=6)]
    monkeypatch.setattr(pf, "layout_is_usable", lambda: True)
    monkeypatch.setattr(pf, "load_switches", lambda: [])
    monkeypatch.setattr(pf, "load_switch_list", lambda: [])
    monkeypatch.setattr(pf, "load_leds", lambda: [])
    monkeypatch.setattr(pf, "load_coils", lambda: [])
    monkeypatch.setattr(pf, "group_fixtures", lambda leds: [dict(f) for f in fixtures])
    monkeypatch.setattr(pf, "layout_art", lambda: None)
    monkeypatch.setattr(pf, "layout_extent", lambda pad=14: (100, 200))
    monkeypatch.setattr(pf, "FADE_MS", 0.0)
    monkeypatch.setattr(pf, "GROUP_NODE", {6: 8, 7: 9})
    monkeypatch.setattr(pf, "GAME", "godzilla_le")
    monkeypatch.setattr(pf, "_LENS", None)
    return pf.Playfield()


def test_a_mode_s_colour_on_a_one_colour_insert_is_named_not_drawn(pf, monkeypatch):
    """PAD-668: a mode's light show paints a one-colour insert red; the board gets one level, and on the machine
    the insert glows in its own colour. The view draws it white (not set) at the wire's level and names the colour
    the mode asked for in its tooltip - PAD-658 had drawn it red."""
    import coilmap
    view = _one_colour_field(pf, monkeypatch).view
    b = bytearray(16384)
    b[:pf.PADLED_READ] = _led_block(pf, {(8, 3): 128})
    struct.pack_into("<I", b, coilmap.PAINT_OFF, coilmap.PAINT_MAGIC)
    b[coilmap.PAINT_OFF + 8:coilmap.PAINT_OFF + 14] = bytes((6, 3, 255, 0, 0, 1))     # the mode painted it red
    with open(pf.LED_PATH, "wb") as f:
        f.write(bytes(b))
    frame = view.tick(0.0)
    r, g, bl = frame["fx"][0][:3]
    assert r == g == bl and r > 128                                                   # white, lifted; not red
    tip = view.describe("led", 0)
    assert "MASER   (one colour)" in tip and "value 128" in tip
    assert "its colour not set (white): see INSERT COLOURS" in tip
    assert "a mode asks for #ff0000" in tip and "glows in its own colour" in tip
    with open(pf.LED_PATH, "wb") as f:
        f.write(_led_block(pf, {(8, 3): 128}))                                         # no mode holds it
    view.tick(0.0)
    assert "mode" not in view.describe("led", 0)


def test_a_one_colour_insert_is_white_until_given_its_colour():
    """PAD-668: the default is white ("not known"), at the wire's level; a colour from the table is drawn instead.
    An RGB insert's colour stays the wire's own."""
    import playfield
    assert playfield.fixture_color({"W": 255}) == ((255, 255, 255), 1.0)
    assert playfield.fixture_color({"W": 0}) == (None, 0.0)
    assert playfield.fixture_color({"W": 255}, (0, 64, 255)) == ((0, 64, 255), 1.0)
    col, level = playfield.fixture_color({"W": 64}, (255, 0, 0))
    assert col[1:] == (0, 0) and 100 < col[0] < 255 and level == 64 / 255.0          # dim red keeps its hue
    assert playfield.fixture_color({"R": 255, "G": 0, "B": 0}, (0, 0, 255))[0] == (255, 0, 0)


def test_the_insert_colours_table_is_edited_from_the_page_and_kept_per_title(pf, monkeypatch):
    """PAD-668: the side panel's INSERT COLOURS lists the one-colour inserts by name (RGB ones are not in it);
    a colour picked there is drawn at once, kept in the state file under the title for the next run, and x puts it
    back to white."""
    ctl = _one_colour_field(pf, monkeypatch)
    view = ctl.view
    spec = ctl.state("main")["view"]
    assert spec["lens"] == [["BRIDGE", "", [2]], ["MASER", "", [0]]]
    with open(pf.LED_PATH, "wb") as f:
        f.write(_led_block(pf, {(8, 3): 255}))
    assert view.tick(0.0)["fx"][0][:3] == [255, 255, 255]
    assert ctl.api_lens("MASER", "#FF2000") == "#ff2000"
    assert view.tick(0.0)["fx"][0][:3] == [255, 32, 0]                                # redrawn at once
    assert "its colour #ff2000, as set under INSERT COLOURS" in view.describe("led", 0)
    st = pf.load_state()
    assert st["lens_colours"] == {"godzilla_le": {"MASER": "#ff2000"}}
    assert pf.lens_colours("godzilla_pro") == {}                                      # another title: its own
    monkeypatch.setattr(pf, "_LENS", None)                                           # the next run reads it back
    assert pf.Playfield().state("main")["view"]["lens"][1] == ["MASER", "#ff2000", [0]]
    assert ctl.api_lens("MASER", None) == ""                                          # x: back to white
    assert view.tick(0.0)["fx"][0][:3] == [255, 255, 255]
    assert pf.load_state()["lens_colours"] == {"godzilla_le": {}}
    assert ctl.api_lens("MASER", "not a colour") == ""


def test_all_rgb_draws_a_mode_s_colour_on_a_one_colour_insert_and_real_leds_does_not(pf, monkeypatch):
    """PAD-668: the picture's Real LEDs / All RGB switch. Real LEDs (the default) draws a single-colour insert a
    mode paints in its own colour; All RGB draws it in the mode's colour at the wire's level (PAD-658's view), as
    the Modes tab's preview does. Kept for the next run; RGB inserts and unheld inserts are the same either way."""
    import coilmap
    ctl = _one_colour_field(pf, monkeypatch)
    view = ctl.view
    assert ctl.state("main")["view"]["insert_look"] == "real"
    b = bytearray(16384)
    b[:pf.PADLED_READ] = _led_block(pf, {(8, 3): 255, (8, 4): 255})
    struct.pack_into("<I", b, coilmap.PAINT_OFF, coilmap.PAINT_MAGIC)
    b[coilmap.PAINT_OFF + 8:coilmap.PAINT_OFF + 14] = bytes((6, 3, 255, 0, 0, 1))     # MASER painted red
    with open(pf.LED_PATH, "wb") as f:
        f.write(bytes(b))
    frame = view.tick(0.0)
    assert frame["fx"][0][:3] == [255, 255, 255] and frame["fx"][2][:3] == [255, 255, 255]
    assert ctl.api_insert_look("rgb") == "rgb"
    frame = view.tick(0.0)
    assert frame["fx"][0][:3] == [255, 0, 0]                                          # the mode's red
    assert 2 not in frame["fx"]                                                       # BRIDGE: no mode, unchanged
    assert "drawn #ff0000, the mode's colour (All RGB)" in view.describe("led", 0)
    assert pf.load_state()["insert_look"] == "rgb"
    assert pf.Playfield().state("main")["view"]["insert_look"] == "rgb"              # the next run
    assert ctl.api_insert_look("real") == "real"
    assert view.tick(0.0)["fx"][0][:3] == [255, 255, 255]
    assert ctl.api_insert_look("nonsense") == "real"


def test_the_ball_controls_are_never_over_the_playfield():
    """PAD-668 (David: "we should never show those over the playfield"): before the key panel comes, the trough and
    the actions are a BALLS box in the side panel, in both views - no overlay on the picture, no bar of their own."""
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8").read()
    css = open(os.path.join(RIG, "pfpage", "pf.css"), encoding="utf-8").read()
    assert "pf-overlay" not in js and "pf-overlay" not in css and "pf-acts" not in js
    assert js.count("const balls = ballsBox(V, D);") == 2                       # the field and the schematic view
    assert js.count("side: balls ? balls.el : null,") == 2
    assert 'h.append(el("span", "kp-group", "BALLS"));' in js


def test_the_page_has_the_insert_colours_table():
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8").read()
    assert 'function lensPanel(rows)' in js and 'api("lens", name, pick.value)' in js
    assert 'api("lens", name, null)' in js and "markInserts(fids)" in js
    assert 'api("insert_look", k)' in js and '"Real LEDs"' in js and '"All RGB"' in js


def test_the_page_script_parses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs Node.js")
    r = subprocess.run([node, "--check", os.path.join(RIG, "pfpage", "pf.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_the_switch_list_gets_its_trough_strip_back_when_the_panel_goes(
        pf, monkeypatch, tmp_path):
    """The key panel takes the trough over (its read-only dots); if padbinds
    is withdrawn mid-run the panel goes, and on a title with no artwork the
    strip of clickable dots is the only ball control left - it must return."""
    rows = [dict(id=76 - p, num=p, node=8, bit=32 + p, name="TROUGH %d" % p)
            for p in range(1, 7)]
    monkeypatch.setattr(pf, "layout_is_usable", lambda: False)
    monkeypatch.setattr(pf, "load_switch_list", lambda: list(rows))
    binds = tmp_path / "padbinds"
    binds.write_text("1\tc\t36\tStart Button\n"
                     "B\tt\t70,71,72,73,74,75\t6 balls in trough\n",
                     encoding="utf8")
    ctl = pf.Playfield()
    view = ctl.view
    assert ctl.kind == "schematic" and ctl.key_panel is not None
    assert view.trough is ctl.key_panel.ball_dots and not view.trough.clickable
    binds.unlink()
    ctl._binds_next = 0
    view.sw._n = 1                      # read on this tick
    frame = {}
    ctl.poll_switches(view, frame)
    assert frame.get("layout") and ctl.key_panel is None
    assert view.trough is not None and view.trough.clickable
    assert ctl.state("main")["view"]["trough"]["pos"] == [1, 2, 3, 4, 5, 6]


def _field_ctl(pf, monkeypatch):
    monkeypatch.setattr(pf, "layout_is_usable", lambda: True)
    monkeypatch.setattr(pf, "load_switches", lambda: [])
    monkeypatch.setattr(pf, "load_switch_list", lambda: [])
    monkeypatch.setattr(pf, "load_leds", lambda: [])
    monkeypatch.setattr(pf, "load_coils", lambda: [])
    monkeypatch.setattr(pf, "group_fixtures", lambda leds: [])
    monkeypatch.setattr(pf, "layout_art", lambda: None)
    monkeypatch.setattr(pf, "layout_extent", lambda pad=14: (100, 200))
    return pf.Playfield()


def test_the_picture_is_x_ray_until_switched_and_kept_for_the_next_run(pf, monkeypatch):
    # PAD-628: the Modes tab's x-ray look by default; the switch is kept in
    # the window's state file (the page's own storage is private to a run)
    ctl = _field_ctl(pf, monkeypatch)
    assert pf.art_look() == "xray"
    assert ctl.state("main")["view"]["look"] == "xray"
    with open(pf.STATE, "w") as f:
        json.dump({"playfield_pos": [10, 20]}, f)
    assert pf.Playfield.api_art_look(ctl, "drawing") == "drawing"
    assert json.load(open(pf.STATE)) == {"playfield_pos": [10, 20], "art_look": "drawing"}
    assert _field_ctl(pf, monkeypatch).state("main")["view"]["look"] == "drawing"
    # anything else the page might send is the default, never stored as is
    assert pf.Playfield.api_art_look(ctl, "sepia") == "xray"
    assert pf.art_look() == "xray"
    with open(pf.STATE, "w") as f:
        json.dump({"art_look": 7}, f)
    assert pf.art_look() == "xray"


def test_the_page_has_the_switch_on_the_picture():
    js = open(os.path.join(RIG, "pfpage", "pf.js"), encoding="utf-8").read()
    body = js[js.index("function fieldView("):js.index("function draw()", js.index("function fieldView("))]
    assert 'V.look === "drawing"' in body          # anything but "drawing" is the X-ray
    assert '"X-ray"' in body and '"Drawing"' in body
    assert 'api("art_look", k)' in body
    assert ".blur()" in body                       # the space bar is the Action Button
    css = open(os.path.join(RIG, "pfpage", "pf.css"), encoding="utf-8").read()
    # the same look as the Modes tab's playfield picture
    modes = open(os.path.join(os.path.dirname(RIG), "..", "pinball_decryptor", "webui", "static", "css",
                              "tabs", "modes.css"), encoding="utf-8").read()
    look = "filter: invert(.88) hue-rotate(180deg); opacity: .5;"
    assert ".pf-art { " + look in modes
    assert ".pf-stage.xray img.art { " + look in css
