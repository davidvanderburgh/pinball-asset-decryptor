"""The swatch grid's topper block counts the topper's lights, not its channels
(PAD-702).

"Venom: the left column indicates 87 lights (incorrect), while the right column
indicates 30 lights" (peanuts, 2026-10-24). Venom's topper names its channels
"TOPPER BIKE - G", spaces round the dash; the grid read only "-G", so each of
the 87 channels was a cell of its own, white whatever colour the game sent. The
cabinet box read the spaces but counted 30: its "TOPPER RIGHT SPOTLIGHT 2" is
G, R, G in Stern's table (Mandalorian's "TOPPER 25" too), which made a 30th.
What is worth failing on:

  * ONE CELL PER LIGHT, however the title spells its channels - "-G", " - G",
    "-GRN", and Rush's "LEFT POP BUMPER G" when its siblings say it is RGB.
  * THE G, R, G TYPO IS G, R, B, in the grid, the artwork view and the box -
    and two real lamps sharing a name stay two.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

import cablights  # noqa: E402

#: Venom LE 1.07's topper, as its device table names it (group 9, node 12)
VENOM_TOPPER = (
    ["GHOST RIDER STANDEE", "TOPPER BACK WHEEL", "TOPPER BIKE"]
    + ["TOPPER FRONT WHEEL %d" % n for n in (1, 2)]
    + ["TOPPER RIGHT BOTTOM %d" % n for n in (1, 2, 3, 4)]
    + ["TOPPER HULK ", "TOPPER WOLVERINE", "TOPPER CAPTIAN ",
       "TOPPER GHOST RIDER PORTRAIT"]
    + ["TOPPER LEFT SPOTLIGHT %d" % n for n in (1, 2)]
    + ["TOPPER RIGHT SPOTLIGHT %d" % n for n in (1, 2)]
    + ["TOPPER " + s for s in ("FLASH", "GWEN", "PETER", "EDDIE", "LASHER",
                               "RIOT", "PHAGE", "AGONY")]
    + ["TOPPER LEFT BOTTOM %d" % n for n in (1, 2, 3, 4)])

VENOM_IDENT = """# nbdir v2 elf=game nodes=8 src=game
node=1 type=pinnode code=2 hex=p.hex group=5 name=CABINET
node=7 type=ws2812node code=23 hex=w.hex group=6 name=BACKBOX SPEAKER LIGHTS
node=8 type=pinnode code=5 hex=p.hex group=7 name=LOWER PLAYFIELD
node=9 type=pinnode code=4 hex=p.hex group=8 name=UPPER PLAYFIELD
node=12 type=ws2812node code=20 hex=w.hex group=9 name=TOPPER
node=14 type=ws2812node code=23 hex=w.hex group=3 name=Topper Lights
"""
VENOM_GROUPS = {5: 1, 6: 7, 7: 8, 8: 9, 9: 12}


def _row(name, group, index):
    return dict(kind="led", name=name, group=group, index=index, x=0, y=0,
                image="", conn="")


def _venom_rows():
    rows = []
    for n, stem in enumerate(VENOM_TOPPER):
        for c, o in (("G", 0), ("R", 1), ("B", 2)):
            # the table's own typo: the spotlight's third channel says G
            if stem == "TOPPER RIGHT SPOTLIGHT 2" and c == "B":
                c = "G"
            rows.append(_row("%s - %s" % (stem, c), 9, n * 3 + o))
    return rows


def test_every_spelling_of_a_channel():
    assert cablights.split_channel("TOPPER BIKE - G") == ("TOPPER BIKE", "G")
    assert cablights.split_channel("TOPPER HULK  - G") == ("TOPPER HULK", "G")
    assert cablights.split_channel("SHIELD LEFT-R") == ("SHIELD LEFT", "R")
    assert cablights.split_channel("LEFT GI-RED") == ("LEFT GI", "R")
    # a space and no dash only where the table shows it is an RGB light
    spaced = cablights.spaced_stems(["LEFT POP BUMPER R", "LEFT POP BUMPER G",
                                     "LEFT POP BUMPER B", "MOD B", "TARGET B"])
    assert spaced == {"LEFT POP BUMPER"}
    assert cablights.split_channel("LEFT POP BUMPER G", spaced) == ("LEFT POP BUMPER", "G")
    assert cablights.split_channel("MOD B", spaced) == ("MOD B", "W")
    assert cablights.split_channel("LEFT POP BUMPER G") == ("LEFT POP BUMPER G", "W")


def test_g_r_g_is_g_r_b_and_two_lamps_stay_two():
    assert cablights.repeated_channel({"G": 48, "R": 49}, "G", 50, 49) == "B"
    # Venom's CAPTAIN AMERICA: two white lamps, 30 and 45
    assert cablights.repeated_channel({"W": 30}, "W", 45, 30) is None
    # a full light's name used again is a second light
    assert cablights.repeated_channel({"G": 0, "R": 1, "B": 2}, "G", 3, 2) is None
    # not the next channel: not the same light
    assert cablights.repeated_channel({"G": 48, "R": 49}, "G", 60, 49) is None


def test_the_box_counts_29_lights(tmp_path):
    ident = tmp_path / "node_ident.txt"
    ident.write_text(VENOM_IDENT)
    secs, left = cablights.sections(_venom_rows(), VENOM_GROUPS,
                                    cablights.boards(str(ident)))
    assert left == [] and [(S["key"], len(S["pixels"])) for S in secs] == [
        ("topper:12", 29)]
    spot = [P for P in secs[0]["pixels"] if P["name"] == "TOPPER RIGHT SPOTLIGHT 2"]
    assert spot[0]["channels"] == {"G": (12, 48), "R": (12, 49), "B": (12, 50)}


@pytest.fixture()
def pf(monkeypatch):
    import playfield
    monkeypatch.setattr(playfield, "DEV_ROWS", _venom_rows())
    monkeypatch.setattr(playfield, "GROUP_NODE", dict(VENOM_GROUPS))
    monkeypatch.setattr(playfield, "SPACED_RGB", frozenset())
    return playfield


def test_the_grid_draws_29_cells_for_87_channels(pf):
    grid = pf.LedGrid(pf.load_led_names())
    grid.seed([(12, i) for i in range(87)])
    cells = grid.by_node[12]
    assert len(cells) == 29
    assert all(set(C["channels"]) == {"R", "G", "B"} for C in cells)
    assert cells[0]["name"] == "GHOST RIDER STANDEE"
    assert {C["name"] for C in cells} == {s.rstrip() for s in VENOM_TOPPER}


def test_the_artwork_view_joins_them_too(pf):
    leds = [dict(name=r["name"], node=12, index=r["index"], x=0, y=0, group=9)
            for r in _venom_rows()]
    fx = pf.group_fixtures(leds)
    assert len(fx) == 29
    spot = [f for f in fx if f["name"] == "TOPPER RIGHT SPOTLIGHT 2"][0]
    assert spot["channels"] == {"G": (12, 48), "R": (12, 49), "B": (12, 50)}


def test_rush_s_spaced_pop_bumpers_are_one_cell(pf, monkeypatch):
    names = {(8, 0): "LEFT POP BUMPER R", (8, 1): "LEFT POP BUMPER G",
             (8, 2): "LEFT POP BUMPER B", (8, 3): "MOD B"}
    monkeypatch.setattr(pf, "SPACED_RGB", cablights.spaced_stems(names.values()))
    grid = pf.LedGrid(names)
    grid.seed(list(names))
    assert [(C["name"], sorted(C["channels"])) for C in grid.by_node[8]] == [
        ("LEFT POP BUMPER", ["B", "G", "R"]), ("MOD B", ["W"])]
