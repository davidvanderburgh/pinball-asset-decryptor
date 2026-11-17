"""Headless tests for .stock files (PAD-1351): one of a JJP game's OWN modes changed -
its timer, points and shots - by the runtime wrapping that class's virtuals.  The
checker's keys stay in step with the runtime's, the checker catches each kind of
mistake, and jjpstock.shot_table finds and names a shot table the way jjpmodes.c's
read_shot_table does."""
import importlib.util
import os
import re
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "jjp_emu")


def _load(name):
    path = os.path.join(RIG, name + ".py")
    if not os.path.exists(path):
        pytest.skip(f"tools/jjp_emu/{name}.py not present")
    sys.path.insert(0, RIG)
    try:
        spec = importlib.util.spec_from_file_location(name + "_undertest", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(RIG)
    return mod


def _folder(tmp_path, files):
    for n, t in files.items():
        (tmp_path / n).write_text(t, encoding="utf-8")
    return str(tmp_path)


PORT = {
    "switches": ["switch_ramp_right_made", "switch_target_tv"],
    "stock": {"classes": {"CandyLaneMode": {"timer": "own set_time", "points": "own score_and_total", "shots": True}},
              "objects": {"cl_mode": "CandyLaneMode"},
              "shots": [{"id": 36, "name": "target_ul_flipper"}, {"id": 39, "name": "target_tv"}]},
}


def test_every_stock_key_the_runtime_reads_is_a_key_the_checker_knows():
    mm = _load("mkjjpmodes")
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    body = src[src.index("static void apply_stock_kv("):src.index("static void stock_kv(")]
    assert set(re.findall(r'!strcmp\(k, "([a-z_]+)"\)', body)) == set(mm.STOCK_KEYS)


def test_a_folder_of_only_stock_files_checks_clean(tmp_path):
    mm = _load("mkjjpmodes")
    d = _folder(tmp_path, {"title.cfg": "game = Wonka\n", "candy_lane.stock":
                           "mode = cl_mode\nseconds = 60\npoints_x = 1.5\nshots_off = target_ul_flipper\n"
                           "shots_add = switch_ramp_right_made:target_tv\n"})
    modes, problems = mm.check_modes(d, PORT)
    assert problems == []
    assert modes[0]["stock"] and modes[0]["mode"] == "cl_mode"
    # by class name too
    (tmp_path / "candy_lane.stock").write_text("mode = CandyLaneMode\npoints = 2500000\n", encoding="utf-8")
    assert mm.check_modes(d, PORT)[1] == []


@pytest.mark.parametrize("text,want", [
    ("mode = cl_mode\nseconds = 60\ncolour = red\n", "unknown key colour"),
    ("mode = cl_mode\npoints_x = lots\n", "points_x must be a number"),
    ("mode = cl_mode\nshots_add = switch_target_tv\n", "wants switch:shot pairs"),
    ("mode = cl_mode\nshots_add = switch_nope:target_tv\n", "switch_nope"),
    ("mode = cl_mode\nshots_off = loop_nowhere\n", "no shot called loop_nowhere"),
    ("mode = mtv_mode\nseconds = 30\n", "not one of this title's modes"),
    ("seconds = 30\n", "no mode ="),
    ("mode = cl_mode\n", "changes nothing"),
    ("mode = cl_mode\npoints = 5\npoints_x = 2\n", "points wins"),
])
def test_the_checker_names_each_stock_mistake(tmp_path, text, want):
    mm = _load("mkjjpmodes")
    d = _folder(tmp_path, {"a.stock": text})
    problems = mm.check_modes(d, PORT)[1]
    assert any(want in p for p in problems), problems


def test_two_files_for_one_game_mode_are_refused(tmp_path):
    mm = _load("mkjjpmodes")
    d = _folder(tmp_path, {"a.stock": "mode = cl_mode\nseconds = 30\n", "b.stock": "mode = cl_mode\npoints_x = 2\n"})
    assert any("already changed by a.stock" in p for p in mm.check_modes(d, PORT)[1])


def test_shot_names_go_unchecked_where_the_title_has_no_live_table(tmp_path):
    mm = _load("mkjjpmodes")
    port = {"switches": PORT["switches"], "stock": {"classes": PORT["stock"]["classes"]}}
    d = _folder(tmp_path, {"a.stock": "mode = CandyLaneMode\nshots_off = anything 12\n"})
    assert mm.check_modes(d, port)[1] == []


def test_stock_files_ride_the_iso_and_the_hook_counts_them():
    mm = _load("mkjjpmodes")
    assert ".stock" in mm.MODE_FILES and ".mode" in mm.MODE_FILES
    assert "\\.stock$" in mm.PADMODES_SH


def _table(entries, stride=72, base=0x900000, lead=b"\0" * 64):
    """A Wonka-shaped shot table: id at +0, handler at +8, the rest zero."""
    blob = bytearray(lead)
    for sid, fn in entries:
        e = bytearray(stride)
        struct.pack_into("<iQ", e, 0, sid, 0)
        struct.pack_into("<Q", e, 8, fn)
        blob += e
    return [(base, bytes(blob) + b"\0" * 64)]


def test_shot_table_ids_names_and_shared_handlers():
    js = _load("jjpstock")
    fns = {0x5c9b80: "ramp_left", 0x5c99f0: "slings", 0x5c9a50: "jets", 0x5ca3c0: "target_tv", 0x5c9da0: "ramp_center"}
    rows = [(0, 0), (1, 0), (2, 0x5c9da0), (3, 0x5c9b80), (4, 0x5c99f0), (5, 0x5c99f0), (6, 0x5ca3c0),
            (7, 0x5c9a50), (8, 0x5c9a50), (9, 0x5c9b80)]
    disp = {4: "LEFT SLING", 5: "RIGHT SLING", 7: "TOP BUMPER", 8: "LEFT BUMPER", 3: "GOBSTOPPER RAMP", 9: ""}
    segs = _table(rows)
    shots = js.shot_table(segs, fns, lambda sid, at, stride: disp.get(sid, ""))
    got = {s["id"]: s["name"] for s in shots}
    assert got == {2: "ramp_center", 3: "ramp_left", 4: "left_sling", 5: "right_sling", 6: "target_tv",
                   7: "top_bumper", 8: "left_bumper", 9: "ramp_left_9"}
    # without the game's display names, every shared handler after the first is <name>_<id>
    got = {s["id"]: s["name"] for s in js.shot_table(segs, fns, None)}
    assert got[4] == "slings" and got[5] == "slings_5" and got[8] == "jets_8"


def test_shot_table_is_found_among_stray_pointers():
    js = _load("jjpstock")
    fns = {0x1000 + 16 * i: "s%d" % i for i in range(8)}
    rows = [(10 + i, 0x1000 + 16 * i) for i in range(8)]
    segs = _table(rows, stride=40)
    stray = bytearray(256)
    struct.pack_into("<Q", stray, 8, 0x1000)       # a lone pointer to a handler elsewhere
    segs.append((0x800000, bytes(stray)))
    shots = js.shot_table(sorted(segs), fns, None)
    assert [s["id"] for s in shots] == list(range(10, 18))
    assert js.shot_table([(0x900000, b"\0" * 512)], fns, None) == []


def test_normalise_matches_the_runtime():
    js = _load("jjpstock")
    assert js.normalise("LEFT SLING") == "left_sling"
    assert js.normalise("  G TARGET!! ") == "g_target"
    assert js.normalise("") == ""


def test_starter_stock_file_picks_a_mode_class_with_shots_and_checks_clean(tmp_path):
    jp = _load("jjpport")
    mm = _load("mkjjpmodes")
    p = {"stock": {"classes": {
        "QuickRule": {"timer": "Mode::set_time", "points": "Mode::score_and_total", "shots": True},
        "AFDMode": {"timer": "Mode::set_time", "points": "own score_and_total", "shots": True},
        "BMode": {"timer": "Mode::set_time", "points": "Mode::score_and_total", "shots": True},
        "AAMode": {"timer": "own set_time", "points": "own score_and_total", "shots": False}}}}
    path = jp.write_stock_example(p, str(tmp_path), "Test 1.0")
    assert os.path.basename(path) == "AFDMode.stock"
    assert mm.check_modes(str(tmp_path), p)[1] == []
    assert jp.write_stock_example({"stock": {"classes": {"X": dict(p["stock"]["classes"]["AAMode"])}}},
                                  str(tmp_path / "none"), "T") is None
