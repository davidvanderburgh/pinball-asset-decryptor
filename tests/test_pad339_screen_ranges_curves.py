"""PAD-339: the machine screen's colour ranges and curves.  Preview only:
they belong to the Machine screen (the Scenes preview's "As on the
machine"), come after its other steps (ranges, then the master curve, then
each channel's) and are neutral when new.  PAD-343 gave them to every
profile; tests/test_pad343_profile_extras_everywhere.py covers the builds."""

import json
import os
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

np = pytest.importorskip("numpy")

_COLOR_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                         "webui", "static", "js", "tabs", "color.js")

SEA = (24, 80, 128)            # the test card's teal-blue sea patch
GREY = (100, 100, 100)
NEAR_GREY = (104, 100, 108)    # a grey with a hint of purple: a portrait, metal
RED = (200, 30, 30)


def _px(*cols):
    return np.array([list(cols)], np.uint8)


def _sea_range(**kw):
    vals = dict(hue=205, width=50, soft=30, shift=15, saturation=0.8,
                brightness=0.85, protect=0.15)
    vals.update(kw)
    return cp.clean_range([vals[k] for k in cp.RANGE_FIELDS])


def test_new_ranges_and_straight_curves_change_nothing():
    rgb = _px(SEA, GREY, NEAR_GREY, RED)
    prof = cp.Profile(ranges=(cp.clean_range([205]),),
                      curves=(("rgb", cp.CURVE_IDENTITY),))
    assert prof.is_identity() and not prof.has_extras()
    assert (prof.apply_array(rgb) == rgb).all()
    assert cp.curve_table(cp.CURVE_IDENTITY) == list(range(256))


def test_a_range_moves_the_sea_and_leaves_greys_and_reds():
    prof = cp.Profile(ranges=(_sea_range(),))
    sea, grey, near, red = prof.apply_array(_px(SEA, GREY, NEAR_GREY, RED))[0]
    assert tuple(grey) == GREY and tuple(red) == RED
    # the near-grey has far less colour than the protect threshold: it may
    # move by a hair at most, never toward purple
    assert max(abs(int(a) - int(b)) for a, b in zip(near, NEAR_GREY)) <= 1
    # the sea: darker, less saturated, hue turned toward blue
    assert int(sea.max()) < max(SEA)
    hue = lambda c: np.degrees(np.arctan2(                   # noqa: E731
        np.sqrt(3) * (int(c[1]) - int(c[2])), 2 * int(c[0]) - int(c[1]) - int(c[2]))) % 360
    assert hue(sea) > hue(SEA)


def test_the_soft_edge_blends_the_range_boundary():
    prof = cp.Profile(ranges=(_sea_range(hue=180, width=0, soft=60, shift=0,
                                         saturation=1, brightness=0.5),))
    # pure hues 180 (in), 210 (half way out) and 240 (out)
    out = prof.apply_array(_px((0, 200, 200), (0, 100, 200), (0, 0, 200)))[0]
    assert int(out[0].max()) == 100
    assert 100 < int(out[1].max()) < 200
    assert tuple(out[2]) == (0, 0, 200)


def test_curves_master_first_then_each_channel():
    pts = cp.clean_points([(0, 0), (64, 48), (255, 255)])
    t = cp.curve_table(pts)
    assert t[0] == 0 and t[64] == 48 and t[255] == 255
    assert all(a <= b for a, b in zip(t, t[1:]))          # no overshoot
    blue = cp.clean_points([(0, 0), (255, 200)])
    prof = cp.Profile(curves=(("rgb", pts), ("b", blue)))
    out = [int(v) for v in prof.apply_array(_px((64, 64, 64)))[0][0]]
    assert tuple(out) == (48, 48, cp.curve_table(blue)[48])


def test_points_are_held_to_the_range_and_need_two():
    assert cp.clean_points([(300, -5), (0, 0)]) == ((0.0, 0.0), (255.0, 0.0))
    with pytest.raises(ValueError):
        cp.clean_points([(10, 10)])
    with pytest.raises(ValueError):
        cp.clean_points([(i, i) for i in range(cp.MAX_POINTS + 1)])
    assert cp.clean_range([400, 999, -1, 0, 9, 1, 2]) == (40.0, 360.0, 0.0, 0.0, 4.0, 1.0, 1.0)


def test_a_copy_and_the_project_file_keep_them():
    prof = cp.Profile(name="Mine", gamma=(0.9, 0.85, 0.8), ranges=(_sea_range(),),
                      curves=(("rgb", cp.clean_points([(0, 0), (64, 48), (255, 255)])),
                              ("r", cp.clean_points([(0, 0), (128, 120), (255, 250)]))))
    back, problems = cp.parse(cp.to_text(prof))
    assert problems == [] and back == prof
    assert cp._from_dict(cp._profile_dict(prof)) == prof
    # an old file with none of it reads as before
    plain = cp.Profile(name="Old", gamma=(1.1, 1.2, 1.35))
    assert "range" not in cp.to_text(plain) and cp.parse(cp.to_text(plain))[0] == plain
    _p, problems = cp.parse("range = 1 2 3 4 5 6 7 8\ncurve_rgb = 1 2 3\n"
                            "curve_blue = 10 10\n")
    assert len(problems) == 3


def test_the_video_players_get_the_curves_as_tables():
    prof = cp.Profile(curves=(("rgb", cp.clean_points([(0, 0), (64, 48), (255, 255)])),))
    st = cp.filter_step(prof)
    assert len(st["t"]) == 3 and len(st["t"][0]) == 65
    assert st["t"][0][16] == round(48 / 255.0, 4)
    assert "t" not in cp.filter_step(cp.Profile(gamma=(1.2, 1.2, 1.2)))


def test_a_builds_profiles_keep_them_from_a_hand_edited_file(tmp_path):
    """PAD-343: a sidecar with ranges or curves on the whole screen overlay
    or the individual files profile: both profiles carry them to the card."""
    d = str(tmp_path)
    extras = {"ranges": [[205, 50, 30, 15, 0.8, 0.85, 0.15]],
              "curves": {"rgb": [[0, 0], [64, 48], [255, 255]]}}
    base = {"name": "x", "gamma": [1.1, 1.1, 1.1], "gain": [1, 1, 1],
            "lift": [0, 0, 0], "saturation": 1.0}
    staged_changes.save(d, {cp.KEY: dict(base, **extras),
                            cp.ASSET_KEY: dict(base, **extras)})
    for prof in (cp.for_project(d), cp.asset_profile(d)):
        assert len(prof.ranges) == 1 and prof.curves[0][0] == "rgb"
        assert prof.gamma == (1.1, 1.1, 1.1)
    assert cp.active(d).has_extras()


def test_load_in_another_mode_keeps_the_extras(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    prof = cp.Profile(name="Mine", gamma=(0.9, 0.9, 0.9), ranges=(_sea_range(),))
    path = tmp_path / "mine.txt"
    cp.save(prof, str(path))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        w.window.ask_open = lambda *a, **k: str(path)
        assert w.call("color.load_file") is True
        w.drain()
        s = w.state("color")
        assert s["problems"] == [] and len(s["ranges"]) == 1
        assert cp.for_project(str(proj)).ranges == prof.ranges
        assert w.call("color.set_mode", "screen") == "screen"
        w.drain()
        assert w.call("color.load_file") is True
        w.drain()
        s = w.state("color")
        assert s["problems"] == [] and len(s["ranges"]) == 1
        assert cp.screen_profile(str(proj)).ranges == prof.ranges


def test_scenes_draws_through_them(tmp_path):
    d = str(tmp_path)
    prof = cp.Profile(name="Mine", ranges=(_sea_range(),))
    cp.store_screen_profile(d, prof)
    assert cp.screen_profile(d) == prof
    view = cp.machine_view(d, overlay_on=False)
    rgb = _px(SEA, GREY)
    assert (view(rgb) == prof.apply_array(rgb)).all()
    assert tuple(view(rgb)[0][1]) == GREY


def test_color_tab_keeps_them_in_every_mode(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.call("color.set_mode", "screen") == "screen"
        w.drain()
        # the Recommended screen starts with its own (PAD-341)
        rec = dict(cp.SCREEN_PRESETS)["screen_recommended"]
        assert w.state("color")["ranges"] == [list(r) for r in rec.ranges]
        assert sorted(w.state("color")["curves"]) == ["b", "g", "r", "rgb"]
        w.call("color.set_params", {"ranges": [[205, 50, 30, 15, 0.8, 0.85, 0.15]],
                                    "curves": {"rgb": [[0, 0], [64, 48], [255, 255]],
                                               "g": [[0, 0], [255, 255]]}})
        w.drain()
        s = w.state("color")
        assert s["ranges"] == [[205.0, 50.0, 30.0, 15.0, 0.8, 0.85, 0.15]]
        assert s["curves"] == {"rgb": [[0.0, 0.0], [64.0, 48.0], [255.0, 255.0]]}
        # another slider keeps them
        w.call("color.set_params", {"gamma": [0.9, 0.9, 0.9]})
        w.drain()
        scr = cp.screen_profile(str(proj))
        assert scr.gamma == (0.9, 0.9, 0.9) and len(scr.ranges) == 1 and scr.curves
        # PAD-343: the whole screen overlay and the individual files take
        # them too
        for mode, key in (("display", cp.KEY), ("assets", cp.ASSET_KEY)):
            assert w.call("color.set_mode", mode) == mode
            w.drain()
            w.call("color.set_params", {"ranges": [[205, 50, 30, 15, 0.8, 0.85, 0.15]],
                                        "curves": {"b": [[0, 0], [255, 230]]},
                                        "gamma": [1.1, 1.1, 1.1]})
            w.drain()
            assert w.state("color")["ranges"] == [[205.0, 50.0, 30.0, 15.0, 0.8, 0.85, 0.15]]
            stored = staged_changes.load(str(proj))[key]
            assert len(stored["ranges"]) == 1 and stored["curves"]["b"] == [[0, 0], [255, 230]]
        disp, files = cp.for_project(str(proj)), cp.asset_profile(str(proj))
        assert disp.gamma == (1.1, 1.1, 1.1) and len(disp.ranges) == 1
        assert files.curves == (("b", ((0.0, 0.0), (255.0, 230.0))),)


_PARITY = r"""
import { correct, curveTable } from "./tabs/color.js";
const p = JSON.parse(process.argv[2]);
const px = JSON.parse(process.argv[3]);
const src = { data: new Uint8ClampedArray(px.length * 4) };
px.forEach((c, i) => { src.data.set([c[0], c[1], c[2], 255], i * 4); });
const dst = { data: new Uint8ClampedArray(px.length * 4) };
correct(src, dst, p);
const out = [];
for (let i = 0; i < px.length; i++) out.push([dst.data[i * 4], dst.data[i * 4 + 1], dst.data[i * 4 + 2]]);
console.log(JSON.stringify({ out, table: Array.from(curveTable(p.curves.rgb)) }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_tab_preview_draws_what_scenes_does(tmp_path):
    """color.js ``correct`` (the Color tab's live preview) and Python's
    apply_array agree, ranges and curves included."""
    src = open(_COLOR_JS, encoding="utf-8").read()
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tabs" / "color.js").write_text(src, encoding="utf-8")
    for mod, frm in (("ui", "../core/ui.js"), ("store", "../core/store.js")):
        m = re.search(r"import \{([^}]*)\} from \"%s\"" % re.escape(frm), src)
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = () => null;\n" % n for n in names),
            encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "cases.js").write_text(_PARITY, encoding="utf-8")
    prof = cp.Profile(gamma=(0.9, 0.85, 0.8), saturation=1.1,
                      ranges=(_sea_range(), cp.clean_range([30, 40, 20, -5, 0.9, 0.95, 0.1])),
                      curves=(("rgb", cp.clean_points([(0, 0), (40, 28), (160, 170), (255, 255)])),
                              ("b", cp.clean_points([(0, 0), (255, 230)]))))
    rng = np.random.default_rng(339)
    px = rng.integers(0, 256, (400, 3)).tolist() + [list(SEA), list(GREY), list(NEAR_GREY)]
    page = {"gamma": list(prof.gamma), "gain": list(prof.gain), "lift": 0.0,
            "saturation": prof.saturation, "brightness": 1, "contrast": 1,
            "ranges": [list(r) for r in prof.ranges],
            "curves": {ch: [list(q) for q in pts] for ch, pts in prof.curves}}
    run = subprocess.run([shutil.which("node"), str(tmp_path / "cases.js"),
                          json.dumps(page), json.dumps(px)],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["table"] == cp.curve_table(prof.curves[0][1])
    want = prof.apply_array(np.array([px], np.uint8))[0].astype(int)
    diff = np.abs(np.array(got["out"]) - want)
    assert diff.max() <= 1, diff.max()
