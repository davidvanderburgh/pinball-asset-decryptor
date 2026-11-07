"""PAD-1044: the co-op character pick's time - counted down on the machine, settable, never a pick dropped.

DoomWalrus666 (Godzilla): "How long the player has to select the character is unclear so sometimes the selection goes
away before the player is ready ... if a player doesn't choose a character in time they may not be assigned one". The
pick ran 20 s with nothing on the glass saying so, its card vanished at the end with nothing saying whom it took, and
a tick with the game busy (pm_in_game() 0) dropped it with no character for that teammate's whole turn (emulator,
Godzilla LE 1.16). The runtime's side is played in test_pad1031_coop_characters.py's model game; here the app's:
the time kept with the characters, coop.cfg's line, and the box on each pick card the runtime's words count down in."""
import pathlib

import numpy as np

from pinball_decryptor.plugins.stern import coop_play as CP

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
CHARS = [{"name": "GODZILLA 1954", "ability": "longer_save"}, {"name": "SHIN GODZILLA", "ability": ""}]


def test_the_time_to_pick_is_kept_with_the_characters_and_only_a_choice_offered(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    assert CP.load_characters(project)["time"] == CP.PICK_TIME == 30          # the runtime's COOP_PICK_MS
    assert "#define COOP_PICK_MS 30000ul" in RUNTIME.read_text(encoding="utf-8")
    CP.save_characters(project, {"pick": True, "time": 60, "list": CHARS})
    assert CP.load_characters(project)["time"] == 60
    CP.save_characters(project, {"pick": True, "time": 0, "list": CHARS})    # no time limit
    assert CP.load_characters(project)["time"] == 0
    for bad in (7, -1, "x", None, 601):
        assert CP.pick_time(bad) == CP.PICK_TIME
    assert set(CP.PICK_TIMES) >= {0, 30} and all(0 <= t <= 600 for t in CP.PICK_TIMES)   # COOP_PICK_MAX_S


def test_coop_cfg_names_the_time():
    elf = b"\0" * 64
    lines = CP.character_lines(elf, {"pick": True, "time": 45, "list": CHARS})
    assert lines[:2] == ["pick on", "pick_time 45"]
    assert CP.character_lines(elf, {"pick": True, "time": 0, "list": CHARS})[1] == "pick_time 0"
    assert CP.character_lines(elf, {"pick": True, "list": CHARS})[1] == "pick_time 30"   # a project from before


def test_each_pick_card_has_the_box_the_runtime_counts_down_in(tmp_path):
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "time": 30, "list": CHARS})
    screens = CP.pick_screens(project, words_for=CP.words_for())
    x0, y0, x1, y1 = CP.TIMER_BOX
    for sc in screens:
        wx, wy = sc["words_at"]
        s = sc["words_scale"]
        # scene_write.screen: the words box is (0, -40)..(card width, 48) scaled about words_at; the game centres the
        # line on it, its middle on the box's y
        assert abs(wx + CP.CARD_SIZE[0] / 2 * s - CP.TIMER_TEXT_X) < 0.5 and x0 + 40 < CP.TIMER_TEXT_X < x1
        assert wy == (y0 + y1) // 2
        assert sc["words"] == " " and sc["words_name"] == sc["name"] + "_Words"
    timed = screens[0]["art_rgba"]
    CP.save_characters(project, {"pick": True, "time": 0, "list": CHARS})
    untimed = CP.pick_screens(project, words_for=CP.words_for())[0]["art_rgba"]
    box = (slice(y0 + 4, y1 - 4), slice(x0 + 6, x1 - 6))
    assert np.abs(timed[box].astype(int) - untimed[box].astype(int)).sum() > 0   # no limit: no box, nothing to count
    png = CP.preview(project, None, CP.words_for(), 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_runtime_keeps_a_pick_through_a_busy_game_and_reads_the_line():
    src = RUNTIME.read_text(encoding="utf-8")
    tick = src[src.index("static void coop_chars_tick(void)"):]
    tick = tick[:tick.index("\n}\n") if "\n}\n" in tick else tick.index("\r\n}\r\n")]
    busy = tick[tick.index("if (!pm_in_game())"):]
    busy = busy[:busy.index("return;")]
    assert "pk.open = 0" not in busy                                   # it waits: never dropped with no character
    assert 'str_starts(s, "pick_time ")' in src
    assert '"PICKED"' in src and "coop_scr_words" in src
