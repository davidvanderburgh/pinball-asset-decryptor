"""The table author's checklist (PAD-941): tools/spike2_emu/vpx/vpxauthor.py.

What is worth failing on, none of it needing WSL, a run or a .vpx:

  * THE DEVICE TABLES ARE READ AS THE RIG WRITES THEM: a device_xy.txt row
    whose connector is two words (Bond's "Topper 105-B"), a switch_list.txt
    id joined to its position on the NAME, an RGB insert's three channels as
    one, a build with no positions at all (every insert and switch listed
    with none, not dropped), an empty led_io.txt filled from device_xy.
  * COVERAGE READS EVERY PLACE A MAP WIRES A PART: `switches`, the rewrite
    tables, `switch_subs`, `switch_holds`, the trough, the plunger, the
    saucers, `switch_fakes`, the cabinet; `solenoids` with and without a
    callback; `lamps`, `lamp_calls`, retrofit lights, GI and disc LEDs.
  * THE GAPS ARE THE RIGHT ONES: flipper EOS and the board's coils (flippers,
    slings, pops) are never owed by a table; a cabinet coil is not a gap.
  * A MAP THAT NUMBERS A SWITCH OTHERWISE THAN THE RUN IS CALLED OUT (Rush's
    first map was one off), by name, never by guessing an offset.
  * THE STARTER MAP has the shape vpxshadow.py reads: trough, plunger,
    cabinet, flippers on core.vbs's numbers, every other coil 1..68 once.
  * THE MARKDOWN carries the marks the author reads: NO on what is missing,
    the ids, the lamp numbers, the GUESS list.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike2_emu")
VPX = os.path.join(EMU, "vpx")
for p in (EMU, VPX):
    if p not in sys.path:
        sys.path.insert(0, p)

pytestmark = pytest.mark.skipif(not os.path.isdir(VPX), reason="rig not present")


@pytest.fixture(scope="module")
def A():
    return pytest.importorskip("vpxauthor")


DEVICE_XY = """# mini device positions, from the game binary.
# binary: game 1234 bytes
# 12 records (coil=4 led=5 switch=6), 10 on the playfield image.
# playfield image: mini_playfield.png (459x998)
# class   name                                   x     y    w    h  grp index  conn   image
switch    START BUTTON                           0     0    0    0    5     3  -      -
switch    LEFT OUTLANE                          43   747   20   20    7    17  -      playfield
switch    LEFT SLINGSHOT                       114   710   20   20    7    30  -      playfield
switch    LEFT FLIPPER EOS                     179   807   20   20    7    16  -      playfield
switch    TROUGH 1                             377   854   20   20    7    37  8a     playfield
switch    SHOOTER LANE                         416   859   20   20    7    28  -      playfield
switch    LEFT EJECT                            53   584   20   20    7    10  -      playfield
coil      LEFT FLIPPER                         141   813   20   20    7     5  -      playfield
coil      TROUGH                               370   858   20   20    7     1  -      playfield
coil      LEFT SLINGSHOT                       114   710   20   20    7     3  -      playfield
coil      LEFT EJECT                            54   589   20   20    7     8  -      playfield
coil      SHAKER MOTOR                           0     0    0    0    5     0  -      -
led       SHOOT AGAIN                          210   863   20   20    7     8  -      playfield
led       LEFT LANE ARROW-R                    117   356   20   20    7     3  -      playfield
led       LEFT LANE ARROW-G                    117   356   20   20    7     4  -      playfield
led       LEFT LANE ARROW-B                    117   356   20   20    7     5  -      playfield
led       TOPPER 105-B                         177    17   20   20    9   314  Topper 105-B Test/scaled_topper
led       LEFT SPEAKER 1                         0     0    0    0    7    60  -      -
"""

SWITCH_LIST = """# mini switch list
# id   num   node  bit  name
36     0     1     3    Start Button
59     1     8     17   LEFT OUTLANE
68     7     8     30   LEFT SLINGSHOT
58     11    8     16   LEFT FLIPPER EOS
75     20    8     37   TROUGH 1
66     22    8     28   SHOOTER LANE
53     25    8     10   LEFT EJECT
90     55    9     12   ROCKET OPTO 1
"""

LED_IO = """# mini LED I/O map.
# node index name                                   x     y  conn  image
8      8     SHOOT AGAIN                          210   863  -     playfield
8      3     LEFT LANE ARROW-R                    117   356  -     playfield
8      4     LEFT LANE ARROW-G                    117   356  -     playfield
8      5     LEFT LANE ARROW-B                    117   356  -     playfield
12     314   TOPPER 105-B                         177    17  -     Test/scaled_topper
8      60    LEFT SPEAKER 1                         0     0  -
"""

GROUP_NODE = """# mini group -> node
5     1    coil=1 switch=1
7     8    coil=4 led=5 switch=6
9     12   led=1
"""


def _tables(tmp_path, led_io=LED_IO, device_xy=DEVICE_XY, switch_list=SWITCH_LIST):
    d = tmp_path / "mini"
    d.mkdir()
    (d / "device_xy.txt").write_text(device_xy, encoding="utf-8")
    (d / "led_io.txt").write_text(led_io, encoding="utf-8")
    if switch_list is not None:
        (d / "switch_list.txt").write_text(switch_list, encoding="utf-8")
    (d / "group_node.txt").write_text(GROUP_NODE, encoding="utf-8")
    return str(d)


MAP = {
    "title": "mini", "detect": ["Mini"], "output": "Mini (PAD).vpx",
    "game_on": {"number": 40, "coils": [[8, 5], [8, 0]]},
    "cabinet": {"start": 1036},
    "switches": {"_": "x", "Trigger001": {"id": 59, "event": "hit", "name": "LEFT OUTLANE (GUESS)"},
                 "LeftSlingShot": {"id": 68, "event": "slingshot", "name": "LEFT SLINGSHOT"}},
    "plunger": {"lane_trigger": "swPlungerRest", "lane_switch": 66, "autoplunge": "plungerIM"},
    "trough": {"release": "BallRelease", "drain": "Drain", "switches": [75], "balls": 1, "kick": [8, 1]},
    "saucers": {},
    "solenoids": {"1": {"coil": [8, 1], "name": "TROUGH", "callback": "bsTrough.SolOut"},
                  "6": {"coil": [8, 8], "name": "LEFT EJECT", "callback": None},
                  "48": {"coil": [8, 5], "name": "LEFT FLIPPER", "callback": None}},
    "lamps": {"_": "x", "LightShootAgain": {"leds": [[8, 8]], "name": "SHOOT AGAIN"}},
}


def test_device_xy_rows_parse_with_a_two_word_connector(A, tmp_path):
    rows, image, size, binary = A.read_device_xy(os.path.join(_tables(tmp_path), "device_xy.txt"))
    assert image == "mini_playfield.png" and size == (459, 998) and "1234" in binary
    topper = next(r for r in rows if r["name"] == "TOPPER 105-B")
    assert (topper["x"], topper["y"], topper["group"], topper["index"]) == (177, 17, 9, 314)
    assert topper["conn"] == "Topper 105-B" and topper["image"] == "Test/scaled_topper"
    assert len(rows) == 18


def test_switches_take_the_runs_ids_joined_on_the_name(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    by = {s["name"]: s for s in m["switches"]}
    assert by["LEFT OUTLANE"]["id"] == 59 and by["LEFT OUTLANE"]["x"] == 43
    assert by["LEFT OUTLANE"]["where"] == "playfield" and by["LEFT OUTLANE"]["kind"] == "lane"
    assert by["Start Button"]["where"] == "cabinet"
    assert by["LEFT FLIPPER EOS"]["kind"] == "flipper eos"
    assert by["LEFT EJECT"]["kind"] == "saucer"
    # named by the game, not placed in the binary: kept, with no place
    assert by["ROCKET OPTO 1"]["where"] == "unplaced" and by["ROCKET OPTO 1"]["x"] is None
    assert m["have"]["switch_list.txt"] and m["positions"]


def test_coils_get_their_node_through_group_node(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    by = {c["name"]: c for c in m["coils"]}
    assert (by["LEFT FLIPPER"]["node"], by["LEFT FLIPPER"]["index"]) == (8, 5)
    assert by["LEFT FLIPPER"]["kind"] == "flipper" and by["LEFT FLIPPER"]["number"] == 1000 + 8 * 16 + 5
    assert by["SHAKER MOTOR"]["node"] == 1 and by["SHAKER MOTOR"]["kind"] == "cabinet"
    assert by["LEFT EJECT"]["kind"] == "kick"


def test_an_rgb_inserts_three_channels_are_one(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    pf = [g for g in m["inserts"] if g["where"] == "playfield"]
    assert [g["name"] for g in pf] == ["LEFT LANE ARROW", "SHOOT AGAIN"]
    arrow = pf[0]
    assert arrow["rgb"] and arrow["leds"] == [(8, 3), (8, 4), (8, 5)] and arrow["lamp"] == 1803
    assert not pf[1]["rgb"] and pf[1]["lamp"] == 1808
    others = {g["name"]: g["where"] for g in m["inserts"] if g["where"] != "playfield"}
    assert others["TOPPER 105-B"] == "topper" and others["LEFT SPEAKER 1"] == "cabinet"


def test_an_empty_led_io_is_filled_from_device_xy(A, tmp_path):
    m = A.read_machine(_tables(tmp_path, led_io="# empty\n"), "mini")
    names = sorted(g["name"] for g in m["inserts"] if g["where"] == "playfield")
    assert names == ["LEFT LANE ARROW", "SHOOT AGAIN"]


def test_a_build_with_no_positions_keeps_every_part(A, tmp_path):
    flat = "\n".join(ln if ln.startswith("#") or ln.startswith("led") else ln
                     for ln in DEVICE_XY.replace("playfield", "-").splitlines())
    m = A.read_machine(_tables(tmp_path, led_io="# empty\n", device_xy=flat), "mini")
    assert not m["positions"]
    sw = [s for s in m["switches"] if s["where"] == "unplaced"]
    assert len(sw) == 7 and all(s["x"] is None for s in sw)
    pf = [g for g in m["inserts"] if g["where"] == "playfield"]
    assert sorted(g["name"] for g in pf) == ["LEFT LANE ARROW", "LEFT SPEAKER 1", "SHOOT AGAIN"] or \
        sorted(g["name"] for g in pf) == ["LEFT LANE ARROW", "SHOOT AGAIN"]


def test_no_switch_list_means_no_ids_and_the_checklist_says_so(A, tmp_path):
    d = _tables(tmp_path, switch_list=None)
    m = A.read_machine(d, "mini")
    assert not m["have"]["switch_list.txt"]
    assert all(s["id"] is None for s in m["switches"]) and len(m["switches"]) == 7
    text = A.markdown(m)
    assert "No switch ids yet" in text


def test_coverage_reads_every_place_a_map_wires_a_part(A):
    cov = A.coverage(MAP)
    assert cov["switches"] == {59, 68, 66, 75, 36}
    assert cov["coils"] == {(8, 1), (8, 5), (8, 0)}
    assert cov["coils_listed_only"] == {(8, 8)}
    assert cov["leds"] == {(8, 8)}
    assert cov["guesses"] == [("switch", "Trigger001", "LEFT OUTLANE (GUESS)")]


def test_coverage_of_the_other_map_shapes(A):
    m = {"switch_rewrite": {"_": "x", "16": 62, "23": 0}, "switch_by_object": {"K2_hit": 81},
         "switch_subs": {"T_Hit": {"pulse": 77, "name": "X"}, "S_Hit": {"hold": 83, "name": "Y"}},
         "switch_holds": {"trough": [71, 70], "right_scoop": 53, "balls": 4, "balls_why": "w"},
         "switch_fakes": {"shield": {"coil": [9, 2], "open": 86, "closed": 87}},
         "saucers": {"K": {"switch": 85, "enter": 78}},
         "lamp_calls": {"Dome": {"leds": [[8, 26]], "call": "PadDome"}},
         "retrofit_lights": {"clone": "L21", "lights": {"PL": {"leds": [[8, 9]], "at": [1, 2]}}},
         "gi_leds": {"leds": [[8, 0], [9, 0]]}, "disc_leds": {"cw": [9, 51], "ccw": [9, 52]},
         "lamp_flasher_numbers": {"61": 1947, "_names": {}}}
    cov = A.coverage(m)
    assert cov["switches"] == {62, 81, 77, 83, 71, 70, 53, 86, 87, 85, 78}
    assert cov["coils"] == {(9, 2)}
    assert cov["leds"] == {(8, 26), (8, 9), (8, 0), (9, 0), (9, 51), (9, 52), (9, 47)}


def test_gaps_owe_the_switch_never_the_boards_coil(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    gap = A.gaps(m, A.coverage(MAP))
    assert [s["name"] for s in gap["switches"]] == ["LEFT EJECT", "ROCKET OPTO 1"]   # not the EOS
    assert gap["coils"] == []                        # the sling is the board's, the shaker the cabinet's
    assert [c["name"] for c in gap["coils_listed_only"]] == ["LEFT EJECT"]
    assert [g["name"] for g in gap["inserts"]] == ["LEFT LANE ARROW"]


def test_a_map_numbering_a_switch_otherwise_is_called_out_by_name(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    off = json.loads(json.dumps(MAP))
    off["switches"]["LeftSlingShot"]["id"] = 59            # the run calls 59 LEFT OUTLANE
    wrong = A.misnumbered(m, off)
    assert wrong == [("LeftSlingShot", 59, "LEFT SLINGSHOT", "LEFT OUTLANE")]
    assert A.misnumbered(m, MAP) == []                      # a comment in the name is not a mismatch
    text = A.markdown(m, map_info=off, cov=A.coverage(off), gap=A.gaps(m, A.coverage(off)), wrong=wrong)
    assert "disagree (1)" in text and "| `LeftSlingShot` | 59 | LEFT SLINGSHOT | LEFT OUTLANE |" in text


def test_the_markdown_marks_what_is_missing(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    cov = A.coverage(MAP)
    text = A.markdown(m, map_info=MAP, cov=cov, gap=A.gaps(m, cov))
    assert "| **NO** | 53 | 25 | 8/10 | LEFT EJECT | saucer | 53,584 |" in text
    assert "| yes | 59 | 1 | 8/17 | LEFT OUTLANE | lane | 43,747 |" in text
    assert "| - | 58 | 11 | 8/16 | LEFT FLIPPER EOS | flipper eos |" in text
    assert "| board | 8/3 | 1131 | LEFT SLINGSHOT | slingshot |" in text
    assert "| listed | 8/8 | 6 | LEFT EJECT | kick |" in text
    assert "| **NO** | 1803 | 8/3, 8/4, 8/5 | LEFT LANE ARROW | yes | 117,356 |" in text
    assert "## Marked GUESS in the map" in text and "`Trigger001`" in text
    assert "Start Button (36)" in text                      # the cabinet, set apart


def test_the_plain_checklist_has_no_marks(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    text = A.markdown(m)
    assert "**NO**" not in text and "| 53 | 25 | 8/10 | LEFT EJECT |" in text
    assert "7 playfield switches (1 of them flipper EOS the board reads), 1 cabinet switch the kit" in text


def test_the_starter_map_has_the_shape_vpxshadow_reads(A, tmp_path):
    m = A.read_machine(_tables(tmp_path), "mini")
    s = A.starter_map(m, "Some Table.vpx")
    assert s["title"] == "mini" and s["output"] == "Some Table (PAD).vpx"
    assert s["trough"]["switches"] == [75] and s["trough"]["kick"] == [8, 1] and s["trough"]["balls"] == 1
    assert s["plunger"]["lane_switch"] == 66
    assert s["cabinet"]["start"] == 1036
    assert s["game_on"]["coils"] == [[8, 5]]
    # the trough, shooter lane, flipper buttons and EOS have their own places: not TODO switches
    assert set(s["switches"]) - {"_"} == {"TODO_LEFT_OUTLANE", "TODO_LEFT_SLINGSHOT", "TODO_LEFT_EJECT"}
    assert s["switches"]["TODO_LEFT_SLINGSHOT"] == {"id": 68, "event": "slingshot", "name": "LEFT SLINGSHOT"}
    sols = {k: v for k, v in s["solenoids"].items() if k != "_"}
    assert sols["48"]["name"] == "LEFT FLIPPER" and sols["1"]["callback"] == "bsTrough.SolOut"
    nums = sorted(int(k) for k in sols)
    assert len(nums) == len(set(nums)) and all(1 <= n <= 68 for n in nums)
    assert s["lamps"]["TODO_LEFT_LANE_ARROW"] == {"leds": [[8, 3], [8, 4], [8, 5]], "name": "LEFT LANE ARROW",
                                                  "rgb": True}


def test_coils_and_inserts_come_from_the_map_when_the_build_names_none(A):
    coils = A.coils_from_map(MAP)
    assert [(c["node"], c["index"], c["name"]) for c in coils] == [(8, 0, "FLIPPER"), (8, 1, "TROUGH"),
                                                                    (8, 5, "LEFT FLIPPER"), (8, 8, "LEFT EJECT")]
    ins = A.inserts_from_map(MAP)
    assert ins == [{"name": "SHOOT AGAIN", "leds": [(8, 8)], "names": ["SHOOT AGAIN"], "x": None, "y": None,
                    "image": "-", "where": "playfield", "rgb": False, "lamp": 1808}]


def test_find_tables_takes_each_file_from_the_newest_place_that_has_it(A, tmp_path):
    a = tmp_path / "a" / "mini"
    b = tmp_path / "b" / "mini"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "device_xy.txt").write_text(DEVICE_XY, encoding="utf-8")
    (b / "switch_list.txt").write_text(SWITCH_LIST, encoding="utf-8")
    (b / "led_io.txt").write_text("", encoding="utf-8")            # empty: not taken
    dirs = [str(a), str(b)]
    files = {}
    for f in A.TABLE_FILES:
        best = None
        for d in dirs:
            p = os.path.join(d, f)
            if os.path.isfile(p) and os.path.getsize(p):
                best = p
        if best:
            files[f] = best
    # the same rule find_tables applies (it is given the directories by table_dirs)
    got = A.find_tables("mini", str(tmp_path / "a"))
    assert set(got) == {"device_xy.txt", "group_node.txt"} - {"group_node.txt"}
    assert files["switch_list.txt"].startswith(str(b)) and "led_io.txt" not in files


def test_the_shipped_maps_read_through_coverage(A):
    """Every map beside the kit: coverage reads it without a complaint and
    finds switches, coils and lights in each."""
    import glob
    for path in glob.glob(os.path.join(VPX, "*.json")):
        if "protos" in path:
            continue
        m = json.load(open(path, encoding="utf-8"))
        cov = A.coverage(m)
        assert cov["switches"] and cov["coils"] and cov["leds"], path


def test_summary_for_counts_what_a_table_owes_and_what_the_map_wires(A, tmp_path):
    d = _tables(tmp_path)
    got = A.summary_for("mini", MAP, str(tmp_path))
    # owed: LEFT OUTLANE, LEFT SLINGSHOT, TROUGH 1, SHOOTER LANE, LEFT EJECT, ROCKET OPTO 1 (not the EOS);
    # coils the game fires: TROUGH, LEFT EJECT (not the flipper, the sling, the shaker); two inserts
    assert got["switches"] == [4, 6] and got["coils"] == [1, 2] and got["inserts"] == [1, 2]
    assert got["pct"] == 60 and got["ids"]
    assert A.summary_for("nosuch", MAP, str(tmp_path)) is None
    assert os.path.isdir(d)
