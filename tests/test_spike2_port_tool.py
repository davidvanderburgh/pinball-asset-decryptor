"""Tests for tools/spike2_emu/modes/sdk/port_tool.py and shot_census.py (item 135).

The port tool drafts a game build's port from a proven one. Its bar here:
  - run on the REFERENCE build itself it must reproduce the hand-made Godzilla Pro 1.15
    port exactly - every function, global and code-named scene; and
  - on Godzilla LE 1.16 it must place every function and global, and the draft must keep
    two relations the tool never checks (the current event is the word after the event
    list head; the resource manager is field 0x80 of the display holder), which a wrong
    derivation would not.
Both need game programs, which are game data outside the repo, and skip without them.
The census parser is checked on a synthetic log. Desk only.
"""
import importlib.util
import os
import pathlib

import pytest

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
PORT = SDK / "ports" / "godzilla_pro-1.15.port"
PRO_ELF = r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game"
LE_ELF = r"C:\tmp\radium_scene_re\godzilla_le_1_16_game"
JAWS_ELF = r"C:\tmp\ports135\jaws_le-1_02_0__jaws_le_game"
DEADPOOL_LE_ELF = r"C:\tmp\ports135\deadpool_le-1_14_0__deadpool_le_game"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SDK / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entries(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        f = rest.split()
        if key == "site":
            out[(key, f[0])] = tuple(int(x, 0) for x in f[1:4])
        elif key == "data":
            out[(key, f[0])] = int(f[1], 0)
        elif key == "scene":
            out[(key, f[0])] = f[1]
    return out


def _need(path):
    if not os.path.exists(path):
        pytest.skip("game program not present: %s" % path)


@pytest.mark.slow
def test_the_reference_build_reproduces_its_own_port(tmp_path):
    _need(PRO_ELF)
    tool = _load("port_tool")
    out = tmp_path / "identity.port"
    assert tool.main([PRO_ELF, str(PORT), PRO_ELF, "-o", str(out)]) == 0
    assert _entries(out) == _entries(PORT)


@pytest.mark.slow
def test_godzilla_le_draft_places_everything_and_keeps_its_relations(tmp_path):
    _need(PRO_ELF)
    _need(LE_ELF)
    tool = _load("port_tool")
    out = tmp_path / "le.port"
    assert tool.main([PRO_ELF, str(PORT), LE_ELF, "-o", str(out), "--game", "godzilla_le",
                      "--version", "1.16"]) == 0
    le, pro = _entries(out), _entries(PORT)
    assert set(k for k in pro if k[0] in ("site", "data")) <= set(le)
    assert "NOT PLACED" not in out.read_text(encoding="utf-8")
    assert le[("data", "event_current")] == le[("data", "event_head")] + 4
    assert le[("data", "resource_manager")] == le[("data", "display_holder")] + 0x80
    # every address moved: this is a different build, not the reference echoed back
    assert sum(1 for k in pro if k[0] == "site" and le[k][0] == pro[k][0]) == 0


@pytest.mark.slow
def test_another_title_gets_candidates_not_copies(tmp_path):
    """Jaws LE 1.02 (item 136): Godzilla's shot bits, sound ids and example names are left
    out, its HUD id (which Jaws never names) is not copied, and the functions no signature
    places come with the framework calls they end in as candidates."""
    _need(PRO_ELF)
    _need(JAWS_ELF)
    tool = _load("port_tool")
    out = tmp_path / "jaws.port"
    assert tool.main([PRO_ELF, str(PORT), JAWS_ELF, "-o", str(out), "--game", "jaws_le",
                      "--version", "1.02"]) == 1                      # shot_dispatch is placed by hand
    text = out.read_text(encoding="utf-8")
    entries = _entries(out)
    assert not any(k[0] in ("shot", "callout", "text") for k in entries)
    assert not [l for l in text.splitlines() if l.startswith(("shot ", "callout ", "text ",
                                                              "value light_owner", "value award_screen_type"))]
    assert "value event_next" in text                                  # a framework offset is still copied
    assert ("scene", "hud") not in entries
    assert "candidate: 9d57875196c613785a1eee010c55223a0f1aa821" in text
    assert entries[("scene", "video_bank")] == "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"
    assert "the reference callout calls 0x2a3108, which is 0x4c2fe0 in the target" in text
    assert "the reference callout_nth calls 0x2a32bc, which is 0x4c3194 in the target" in text
    # item 138: the end of ball is not the loose look-alike; its hooks' handlers name two
    assert ("site", "ball_end") not in entries
    assert "a loose signature matched 0x1524cc, which no handler of its hooks calls" in text
    assert "candidate: 0x1521e8, called by a handler" in text and "candidate: 0x1522d0, called by a handler" in text


@pytest.mark.slow
def test_the_end_of_ball_is_placed_through_its_hook(tmp_path):
    """Item 138: Deadpool LE 1.14's end of ball has no signature in common with Godzilla's;
    the handler of the same event hook calls it, and that is how it is placed."""
    _need(PRO_ELF)
    _need(DEADPOOL_LE_ELF)
    tool = _load("port_tool")
    out = tmp_path / "dp.port"
    tool.main([PRO_ELF, str(PORT), DEADPOOL_LE_ELF, "-o", str(out), "--game", "deadpool_le", "--version", "1.14"])
    text = out.read_text(encoding="utf-8")
    assert _entries(out)[("site", "ball_end")][0] == 0xFD9A8
    assert "through the handler of hook 0x34" in text


def test_a_hooked_site_may_start_with_a_literal_load():
    """Item 137: TMNT Pro's end-of-ball broadcast begins `push; ldr r4, [pc, #0x1c]`. The
    runtime relocates a literal load, so both checks accept it - and still refuse a branch,
    a load into pc, and anything else read relative to pc."""
    words = _load("port_words")
    tool = _load("port_tool")

    class Two:
        def __init__(self, w0, w1):
            self.w = {0: w0, 4: w1}

        def word(self, va):
            return self.w[va]

    ok = [(0xE92D4038, 0xE59F401C),      # push {r3,r4,r5,lr}; ldr r4, [pc, #0x1c]
          (0xE51F3008, 0xE1A00000),      # ldr r3, [pc, #-8]; nop
          (0xE92D4038, 0xE3A00037),      # push; mov r0, #0x37 (nothing pc-relative)
          (0xE3510035, 0x812FFF1E),      # cmp r1, #0x35; bxhi lr (probed on TMNT)
          (0xE3A00000, 0xE12FFF1E)]      # mov r0, #0; bx lr: two instructions, both moved
    refused = [(0xE92D4038, 0xEB000010),  # bl
               (0xE59FF004, 0xE1A00000),  # ldr pc, [pc, #4]
               (0xE28F0004, 0xE1A00000),  # add r0, pc, #4
               (0xE5DF3004, 0xE1A00000),  # ldrb r3, [pc, #4]: not a word literal
               (0xE12FFF1E, 0xE92D4010)]  # bx lr: a one-instruction function
    for w0, w1 in ok:
        assert tool.is_hooked_ok(Two(w0, w1), 0), (hex(w0), hex(w1))
        assert words.movable(w0, w1), (hex(w0), hex(w1))
    for w0, w1 in refused:
        assert not tool.is_hooked_ok(Two(w0, w1), 0), (hex(w0), hex(w1))
        assert not words.movable(w0, w1), (hex(w0), hex(w1))


def test_census_names_bits_and_keeps_reference_names(tmp_path):
    census = _load("shot_census")
    table = tmp_path / "switch_list.txt"
    table.write_text("# id num node bit name\n"
                     "48     27    8     10   Maser Target\n"
                     "82     63    9     18   VUK Opto\n"
                     "74     59    9     9    Big Loop Exit\n"
                     "84     58    9     20   Big Loop Enter\n"
                     "73     62    9     8    L Ramp Made Opto\n"
                     "90     39    9     30   Shield Target Center\n", encoding="utf-8")
    ref = tmp_path / "ref.port"
    ref.write_text("shot 0x08000000    Maser target\nshot 0x00100000    Left ramp\n"
                   "shot 0x100000000   Shield target right\n", encoding="utf-8")
    log = tmp_path / "mode.log"
    log.write_text("\n".join([
        "  1000 [census] mark 48", "  1450 [census] shot 0x1 player 1 in_game 1",
        "  1451 [census] shot 0x8000000 player 1 in_game 1",
        "  3000 [census] mark 82", "  3450 [census] shot 0x1 player 1 in_game 1",
        "  3451 [census] shot 0x4000000000 player 1 in_game 1",
        "  5000 [census] mark 74", "  5010 [census] shot 0x40000 player 1 in_game 1",   # 82's, late
        "  5450 [census] shot 0x1000000001 player 1 in_game 1",
        "  7000 [census] mark 84", "  7450 [census] shot 0x1000000001 player 1 in_game 1",
        "  9000 [census] mark 73", "  9450 [census] shot 0x100000 player 1 in_game 1",
        "  11000 [census] mark 90", "  11450 [census] shot 0x100000000 player 1 in_game 1",
        "  13000 [census] mark end", "  13450 [census] shot 0x8000 player 1 in_game 1",
    ]) + "\n", encoding="utf-8")
    out = tmp_path / "shots.port"
    assert census.main([str(log), str(table), "--ref-port", str(ref), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "shot 0x8000000    Maser target" in text                     # the reference's name kept
    assert "shot 0x100000     Left ramp" in text                        # kept through "L ... Opto"
    assert "shot 0x4000000000 Vuk opto" in text                         # a new bit, named after its switch
    assert "shot 0x1000000000 Big loop exit / Big loop enter" in text   # two switches, one bit
    assert "shot 0x100000000  Shield target center" in text             # the reference name disagrees
    assert "RENAMED" in text
    assert "0x8000 " not in text                                        # after `end`: not attributed
    assert "shot 0x40000      Vuk opto" in text                         # before 74's press: 82's
    assert "0x1 " not in text.replace("0x1000000000", "")


def test_event_lines_are_checked():
    """Item 147: `event <name> <bus id>` needs an id 0..207; `event <name> site <site>` needs
    a site the port has a line for; both names fit the runtime's 39 characters."""
    words = _load("port_words")
    sites = {"hook_dispatch", "mball_start"}
    assert words.event_problems(3, ["event", "ball_start", "0x25   # a comment"], sites) == []
    assert words.event_problems(4, ["event", "multiball_start", "site mball_start"], sites) == []
    assert "outside 0..207" in words.event_problems(5, ["event", "x", "208"], sites)[0]
    assert "no numeric id" in words.event_problems(6, ["event", "x", "soon"], sites)[0]
    assert "no line for" in words.event_problems(7, ["event", "x", "site nowhere"], sites)[0]
    assert "over 39" in words.event_problems(8, ["event", "e" * 40, "1"], sites)[0]
    assert "name and an id" in words.event_problems(9, ["event", "lonely"], sites)[0]


def test_event_read_separates_what_a_mark_caused_from_the_background(tmp_path, capsys):
    """Item 147: ids firing in nearly every window are background; a window lists only its
    own, and --diff names what a press did that its control did not."""
    reader = _load("event_read")
    log = tmp_path / "event.log"
    log.write_text(
        "12 sub id=0x34 handler=0x000d3dcc prio=128 r0=0x00000000 lr=0x00001234 tid=1\n"
        "900 window boot 900 ms: 37=50 38=50\n"
        "900 mark start p=1 mask=0x0010\n"
        "1000 disp id=0x25 arg=0x00000000 lr=0x001f00c0 tid=7 p=1 mask=0x0020\n"
        "1900 window start 1000 ms: 25=1 37=60 38=60\n"
        "1900 mark skill p=1 mask=0x0000\n"
        "2900 window skill 1000 ms: 37=60 38=60 d0=1\n"
        "2900 mark skill_late p=1 mask=0x0000\n"
        "3900 window skill_late 1000 ms: 37=60 38=60\n", encoding="utf-8")
    assert reader.main([str(log), "--diff", "skill", "skill_late"]) == 0
    out = capsys.readouterr().out
    assert "background ids (in >= 80% of 4 windows): 0x37 0x38" in out
    assert "start            1000 ms @   1900  25=1" in out
    assert "call @1000 arg=0x0 lr=0x1f00c0 tid=7 player=1 mask=0x0020" in out
    assert "handlers 0xd3dcc/p128" in out
    assert "in skill, not in skill_late: 0xd0=1" in out
