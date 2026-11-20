"""PAD-1468: Halloween's and Ultraman's virtual playfield draws every switch at
the numbered spot of the Halloween / Ultraman manual's switch locations photo
(no picture shipped), and keeps the LED grid."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
sys.path.insert(0, os.path.join(REPO, "tools", "ap_emu"))
import spktitles  # noqa: E402
import spkswitches  # noqa: E402
import appf  # noqa: E402

SPOTS = spktitles.PINOTAUR_SPOTS


def by_spot():
    return {spot: n for n, (spot, _x, _y) in SPOTS.items()}


def test_the_manuals_chart():
    # the Playfield Switch Description Chart (UM/HW), spot -> switch
    chart = {"1": 49, "2": 50, "3": 51, "4": 66, "5": 73, "6": 78, "7": 74,
             "8": 76, "9": 52, "10": 79, "11": 53, "12": 77, "13": 54,
             "14": 41, "15": 48, "16": 55, "17": 39, "18": 75, "19": 38,
             "20": 29, "21": 27, "22": 28, "23": 71, "25": 72, "26": 31,
             "27": 37, "28": 33, "29": 70, "30": 23, "31": 36, "39": 69,
             "40": 4, "41": 35, "42": 7, "43": 30, "44": 5, "45": 13,
             "46": 14, "47": 12, "48": 26, "49": 68, "50": 67, "51": 15,
             "52": 6, "JAM": 64}
    got = by_spot()
    for spot, n in chart.items():
        assert got[spot] == n, spot
    # 32-38: trough switches 1-7, the order the rig's trough has them
    t = spktitles.get("um")
    assert [got[str(i)] for i in range(32, 39)] == t["trough"]
    assert "24" not in got                      # the manual's placeholder


def test_every_playfield_switch_has_a_spot_inside_the_box():
    w, h = spktitles.PINOTAUR_SPOTS_SIZE
    for s in spkswitches.table(key="um")["switches"]:
        if s["group"] not in ("Playfield", "Trough") or s["n"] in (32, 34):
            continue                            # cabinet, or no spot on the photo
        assert s["n"] in SPOTS, s["label"]
    assert len({s for s, _x, _y in SPOTS.values()}) == len(SPOTS)
    for spot, x, y in SPOTS.values():
        assert 9 <= x <= w - 9 and 9 <= y <= h - 9, spot


@pytest.mark.parametrize("key", ["um", "h78"])
def test_the_window_draws_the_spots_without_a_picture(key):
    table = spkswitches.table(key=key)
    assert table["size"] == spktitles.PINOTAUR_SPOTS_SIZE and table["spots"]
    app = appf.App(table, rig=None, art="", title=table["title"])
    assert app.field and app.spots
    app.lights = {"L1": [255, 0, 0]}
    st = app.state("main")
    assert st["kind"] == "field"
    v = st["view"]
    assert v["art"] is False and v["fixtures"] == [] and v["sketch"]
    assert v["grid"]["blocks"][0]["cells"] == [{"k": "L1", "tip": "L1"}]
    sw = {s[3]: s for s in v["switches"]}
    assert sw[41][4] == "14" and len(sw) == len(SPOTS)
    assert "grid" in st["dyn"] and "fx" not in st["dyn"]
    app.active = {41}
    f = app.frame()
    assert f["sw"] == {"41": 1} and "grid" in f and "fx" not in f
    assert "spot 14 on the manual's switch photo" in app._switch_tip(app.by_n[41])
    labels = [r["label"] for r in table["rows"]]
    assert "44 Middle Left Target" in labels


def test_other_spooky_games_keep_the_list():
    table = spkswitches.table(key="bj")
    assert table["size"] is None and not table["spots"]
    app = appf.App(table, rig=None, art="", title="Beetlejuice")
    assert not app.field and app.state("main")["kind"] == "schematic"


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="needs Node.js")
def test_a_numbered_spot_is_pressed_anywhere_on_its_disc():
    """A plain switch is a bare ring (hit on its outline only); a manual spot
    is a filled, numbered disc: its centre presses it too."""
    import json
    import shutil
    import subprocess
    pf = os.path.join(REPO, "tools", "spike2_emu", "pfpage", "pf.js")
    view = {"switches": [["41", 100, 100, 41, "14"], ["7", 200, 100, 7]],
            "coils": [], "fixtures": []}
    cases = [[view, {}, 1, 100, 100], [view, {}, 1, 108, 100], [view, {}, 1, 122, 100],
             [view, {}, 1, 200, 100], [view, {}, 2, 218, 200]]
    js = ("const { pfHit } = require(%s);\nconst cases = JSON.parse(%s);\n"
          "console.log(JSON.stringify(cases.map((c) => pfHit(...c))));\n"
          % (json.dumps(pf), json.dumps(json.dumps(cases))))
    run = subprocess.run([shutil.which("node"), "-e", js], capture_output=True,
                         text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got[0] == ["switch", "41"] and got[1] == ["switch", "41"]
    assert got[2] is None                    # beyond the disc
    assert got[3] is None                    # a bare ring's centre is nothing
    assert got[4] == ["switch", "41"]       # scale 2: the disc grows to 15 px
