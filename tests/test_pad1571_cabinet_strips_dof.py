"""PAD-1571: the cabinet's light strips to DOF under Visual Pinball.

"Is it possible to map the expression lights of a speaker or a cabinet
(usually Node 7) and map those to DOF lighting commands in VPX? ... Preference
would be to use node 2 for cabinet lights and for games lacking it, use node 7
and display those down led strips in DOF" (Mike St P, 2026-11-24). What is
worth failing on:

  * WHICH LIGHTS: the blades (node 2, 48 RGB pixels a side, pixel 1 at the
    bottom) where the title has them, else the speaker ring (node 7, 23
    pixels) on both sides; a title with neither sends nothing.
  * A DOF E EVENT IS ONE NUMBER, its colour the DOF config's: each part of
    each side has an E per colour, the one nearest the game's colour lit at
    its brightness, the others 0 - so a colour change is two events, never a
    blend DOF cannot show.
  * THE NUMBERS AND THE PASTE: left side's parts first, eight colours each,
    and the DOF lines the tab offers name exactly those numbers, NOBOOL so
    the value is a brightness, AT/AH bottom part last.
  * BOTH ROUTES: PAD's own DOF and, for an original table, B2S.Server's.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
VPX = os.path.join(os.path.dirname(HERE), "tools", "spike2_emu", "vpx")
for p in (VPX, os.path.dirname(VPX)):
    if p not in sys.path:
        sys.path.insert(0, p)

import coilmap  # noqa: E402
import padcabinet  # noqa: E402



class FakeDOF:
    """DOF's ComObject, recording what it hears."""
    def __init__(self):
        self.got = []

    def Init(self, host, table, rom):                  # noqa: N802  DOF's own names
        pass

    def UpdateTableElement(self, kind, n, v):           # noqa: N802
        self.got.append((kind, n, v))

    def Finish(self):                                   # noqa: N802
        pass


class FakeB2SData:
    """B2S.Server as the bridge drives it for DOF: B2SSetData n, v."""
    def __init__(self):
        self.got = []

    def B2SSetIllumination(self, name, value):          # noqa: N802
        self.got.append((name, value))

    def B2SSetData(self, n, v):                         # noqa: N802
        self.got.append(("E", n, v))

#: Rush LE's node directory (nbdir v2): node 2 "Cabinet Lights" is group 1,
#: node 7 the speakers group 6 - places only the directory gives
IDENT = """# nbdir v2 elf=rush_le-1.19.elf nodes=5 src=x
node=1 type=pinnode code=2 part=0x00020023 hex=p.hex group=5 name=CABINET
node=2 type=ws2812node code=23 part=0x2c40102b hex=w.hex group=1 name=Cabinet Lights
node=7 type=ws2812node code=23 part=0x2c40102b hex=w.hex group=6 name=BACKBOX SPEAKER LIGHTS
node=8 type=pinnode code=5 part=0x00020023 hex=p.hex group=7 name=PLAYFIELD 1
# skipped node=0 code=41 reason=no-type (CPU/bridge or reserved) group=4 name=CPU / BRIDGE
"""


def _line(name, group, index, image="-"):
    return "led       %-38s %5d %5d %4d %4d %4d %5d  -      %s" % (name, 0, 0, 0, 0, group, index, image)


def _device(blades=True, speakers=True):
    rows = ["# test device positions, from the game binary.",
            "led       START BUTTON                          102   228   30   30    5     2  -      System/TestMode/spike_2_cabinet_front_cropped"]
    if blades:                     # G-R-B on the wire, as every blade title has it
        for n in range(96):
            side = "L" if n < 48 else "R"
            for c, o in (("G", 0), ("R", 1), ("B", 2)):
                rows.append(_line("EXPRESSIVE LIGHTING %s %d-%s" % (side, n + 1, c), 1, n * 3 + o))
    if speakers:
        for n in range(23):
            for c, o in (("G", 0), ("R", 1), ("B", 2)):
                rows.append(_line("SPEAKER %d-%s" % (n + 1, c), 6, n * 3 + o))
    rows.append(_line("LEFT ORBIT", 7, 3, "playfield"))
    return "\n".join(rows) + "\n"


def _tables(tmp_path, **kw):
    d = tmp_path / "tables" / "rush_le"
    d.mkdir(parents=True)
    (d / "device_xy.txt").write_text(_device(**kw), encoding="utf-8")
    (d / "group_node_exact.txt").write_text("5 1\n7 8\n", encoding="utf-8")
    (d / "node_ident.txt").write_text(IDENT, encoding="utf-8")
    return str(d)


# ------------------------------------------------------------- the strips --

def test_the_blades_where_the_title_has_them(tmp_path):
    st = padcabinet.cabinet_strips(_tables(tmp_path))
    assert st["source"] == "blades" and st["node"] == 2
    left, right = st["sides"]
    assert len(left) == len(right) == 48
    # pixel 1 at the bottom, its channels G-R-B on the wire
    assert left[0] == {"G": (2, 0), "R": (2, 1), "B": (2, 2)}
    assert left[-1]["B"] == (2, 47 * 3 + 2)
    assert right[0]["G"] == (2, 48 * 3)


def test_the_speakers_on_both_sides_where_it_has_no_blades(tmp_path):
    st = padcabinet.cabinet_strips(_tables(tmp_path, blades=False))
    assert st["source"] == "speakers" and st["node"] == 7
    left, right = st["sides"]
    assert len(left) == len(right) == 23 and left == right
    assert left[0] == {"G": (7, 0), "R": (7, 1), "B": (7, 2)}


def test_no_strips_on_a_title_with_neither(tmp_path):
    assert padcabinet.cabinet_strips(_tables(tmp_path, blades=False, speakers=False)) is None
    assert padcabinet.cabinet_strips(str(tmp_path / "nothing")) is None


# ------------------------------------------------------------- the colours --

@pytest.mark.parametrize("rgb, want", [
    ((255, 0, 0), "red"), ((255, 120, 0), "orange"), ((240, 230, 0), "yellow"),
    ((0, 200, 10), "green"), ((0, 200, 210), "cyan"), ((10, 20, 255), "blue"),
    ((150, 0, 255), "purple"), ((255, 0, 120), "red"), ((200, 190, 180), "white"),
])
def test_a_colour_goes_to_the_nearest_of_the_eight(rgb, want):
    i, top = padcabinet.strip_colour(rgb)
    assert padcabinet.STRIP_COLOURS[i][0] == want and top == max(rgb)


def test_black_is_no_colour():
    assert padcabinet.strip_colour((0, 0, 0)) == (None, 0)


def test_the_numbers_left_side_first_eight_colours_a_part():
    nums = padcabinet.strip_numbers(200, 2)
    assert nums[(0, 0, 0)] == 200 and nums[(0, 0, 7)] == 207
    assert nums[(0, 1, 0)] == 208 and nums[(1, 0, 0)] == 216 and nums[(1, 1, 7)] == 231
    assert sorted(nums.values()) == list(range(200, 232))


def _level(lit):
    return lambda node, ch: lit.get((node, ch), 0)


def test_events_light_one_colour_a_part_at_its_brightness(tmp_path):
    st = padcabinet.cabinet_strips(_tables(tmp_path))
    lit = {}
    for n in range(48):                            # left: red, full
        lit[(2, n * 3 + 1)] = 255
    for n in range(48, 96):                        # right: blue, dimmer
        lit[(2, n * 3 + 2)] = 100
    ev = dict(padcabinet.strip_events(200, 1, st, _level(lit)))
    assert sorted(ev) == list(range(200, 216))
    assert {n: v for n, v in ev.items() if v} == {200: 255, 213: 102}    # red E200, blue E208+5
    # all dark: every event 0, none left out (so DOF hears each one go out)
    ev = dict(padcabinet.strip_events(200, 1, st, _level({})))
    assert len(ev) == 16 and not any(ev.values())
    # none sent with no first number
    assert padcabinet.strip_events(0, 1, st, _level(lit)) == []


def test_parts_follow_a_light_up_the_blade(tmp_path):
    st = padcabinet.cabinet_strips(_tables(tmp_path))
    lit = {(2, n * 3): 255 for n in range(24)}     # left's bottom half green
    ev = dict(padcabinet.strip_events(200, 2, st, _level(lit)))
    assert {n: v for n, v in ev.items() if v} == {203: 255}               # left, bottom part, green
    lit = {(2, n * 3): 255 for n in range(24, 48)}  # and the top half
    ev = dict(padcabinet.strip_events(200, 2, st, _level(lit)))
    assert {n: v for n, v in ev.items() if v} == {211: 255}               # left, top part, green


def test_a_mixed_part_shows_its_sum_and_a_lit_glimmer_is_not_black(tmp_path):
    st = padcabinet.cabinet_strips(_tables(tmp_path, blades=False))
    lit = {(7, 1): 200, (7, 3): 200}               # pixel 1 red, pixel 2 green: yellow
    ev = dict(padcabinet.strip_events(300, 1, st, _level(lit)))
    assert {n: v for n, v in ev.items() if v} == {302: 204, 310: 204}     # both sides: the ring
    ev = dict(padcabinet.strip_events(300, 1, st, _level({(7, 1): 3})))
    assert ev[300] == 17 and ev[308] == 17         # dimmest lit step, never 0


# -------------------------------------------------------------- the paste --

def test_dof_lines_name_the_same_numbers():
    one = padcabinet.strip_dof_lines(200, 1)
    left = one["left"].split("/")
    assert left[0] == "E200 #FF0000 NOBOOL" and left[7] == "E207 #FFFFFF NOBOOL" and len(left) == 8
    assert one["right"].split("/")[0] == "E208 #FF0000 NOBOOL"
    two = padcabinet.strip_dof_lines(200, 2)
    left = two["left"].split("/")
    assert left[0] == "E200 #FF0000 AT50 AH50 NOBOOL"              # bottom part: the lower half
    assert left[8] == "E208 #FF0000 AT0 AH50 NOBOOL"               # top part
    assert two["right"].split("/")[0] == "E216 #FF0000 AT50 AH50 NOBOOL"
    nums = sorted(int(b.split()[0][1:]) for s in two.values() for b in s.split("/"))
    assert nums == sorted(padcabinet.strip_numbers(200, 2).values())
    three = padcabinet.strip_dof_lines(200, 3)["left"].split("/")
    assert three[0].endswith("AT67 AH33 NOBOOL") and three[16].endswith("AT0 AH34 NOBOOL")
    assert padcabinet.strip_dof_lines(0, 1) == {"left": "", "right": ""}


def test_settings_keep_the_strips():
    c = padcabinet.settings({})
    assert c["dof_strips"] == 0 and c["strip_parts"] == 1
    kit = padcabinet.update({}, dof_strips=200, strip_parts=4)
    assert padcabinet.settings(kit)["dof_strips"] == 200
    assert padcabinet.settings(kit)["strip_parts"] == 4
    assert padcabinet.settings(padcabinet.update(kit, strip_parts=20))["strip_parts"] == 8
    assert padcabinet.settings(padcabinet.update(kit, strip_parts=0))["strip_parts"] == 1
    assert padcabinet.settings(padcabinet.update(kit, dof_strips=-5))["dof_strips"] == 0
    assert padcabinet.SUGGESTED_DOF["strips"] == 200


def test_setup_state_gives_the_tab_the_lines():
    vs = pytest.importorskip("vpxsetup")
    c = vs.cabinet_state(padcabinet.update({}, dof_strips=200, strip_parts=2), [])
    assert c["strip_lines"] == padcabinet.strip_dof_lines(200, 2)
    assert c["strip_colours"][0] == "red" and len(c["strip_colours"]) == 8


# ------------------------------------------------------------- the bridge --

def _bridge(tmp_path, kit, **kw):
    pc = pytest.importorskip("padcontroller")
    b = pc.Bridge()
    b.set_game("rush_le")
    b._read_cabinet(_tables(tmp_path, **kw), kit=kit)
    return pc, b


def _data(pc, lit):
    data = bytearray(max(pc.READ_N, coilmap.HI_READ))
    for (node, ch), v in lit.items():
        if ch < 96:
            data[20 + node * 96 + ch] = v
        else:
            data[coilmap.HI_OFF + node * coilmap.HI_IDX + ch - 96] = v
    return bytes(data)


def test_bridge_sends_the_blades_to_dof(tmp_path):
    kit = padcabinet.update({}, dof_strips=200)
    pc, b = _bridge(tmp_path, kit)
    assert b.cab_strips["source"] == "blades"
    dof = FakeDOF()
    assert b.dof_init("rush_le", "x.vpx", factory=lambda: dof)
    right_red = {(2, n * 3 + 1): 255 for n in range(48, 96)}      # channels past 96: the hi plane
    b._poll_dof(_data(pc, {}))
    b._poll_dof(_data(pc, right_red))
    b._poll_dof(_data(pc, right_red))                             # unchanged: nothing again
    b._poll_dof(_data(pc, {}))
    b.dof_finish()
    e = [g for g in dof.got if g[0] == "E"]
    assert e[:16] == [("E", n, 0) for n in range(200, 216)]       # each heard once, dark
    assert e[16:] == [("E", 208, 255), ("E", 208, 0)]


def test_bridge_sends_the_speakers_through_b2s_on_a_title_without_blades(tmp_path):
    kit = padcabinet.update({}, dof_strips=200)
    pc, b = _bridge(tmp_path, kit, blades=False)
    assert b.cab_strips["source"] == "speakers"
    fake = FakeB2SData()
    assert b.b2s_attach(fake, direct=True)
    b._poll_b2s_dof(_data(pc, {}))
    b._poll_b2s_dof(_data(pc, {(7, 2): 255}))                    # one speaker pixel blue
    b.b2s_finish()
    assert fake.got[16:] == [("E", 205, 255), ("E", 213, 255)]
    assert "speakers, node 7, 23+23 pixels" in b._strips_words()


def test_bridge_sends_no_strips_unless_asked(tmp_path):
    pc, b = _bridge(tmp_path, {})
    dof = FakeDOF()
    b.dof_init("rush_le", "x.vpx", factory=lambda: dof)
    b._poll_dof(_data(pc, {(2, 1): 255}))
    b.dof_finish()
    assert not [g for g in dof.got if g[0] == "E"]
    assert b._strips_words().startswith("off (blades, node 2")
