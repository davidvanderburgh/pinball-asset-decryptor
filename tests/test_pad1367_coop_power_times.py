"""PAD-1367 (DoomWalrus666): "In the co-op character abilities powers section, anytime a power has an associated time,
I would like to be able to alter how much time. For example, the character ability to press the action button to
activate ball save is currently set to 10 seconds. I would like to be able to alter that to 3 seconds, or 5 seconds."
Each timed power takes a time of its own per character (coop_play.TIMED): the runtime text, the card's words and the
dialog follow it; at the stock time everything is as before, byte for byte."""
from pinball_decryptor.plugins.stern import coop_play as CP
from tests import test_pad1031_coop_characters as T31

#: the timed powers' runtime text on Godzilla LE 1.16 (as test_pad1031 reads them off its program)
PARTS = {
    "action_save": "save:10",
    "battle_timers_10": ("adj:212+10:30:80,adj:213+10:30:80,adj:214+10:30:80,adj:215+10:30:80,adj:216+10:30:100,"
                         "adj:218+10:30:100"),
    "ball_save_x2": "adj:94x200:0:15,bs:94",
    "o2_x2": "adj:193x200:8:40",
    "rodan_x2": "adj:199x200:40:120",
    "addball_save_x2": "adj:200x200:5:20",
    "multiball_saves_x2": "adj:203x200:10:60,adj:204x200:10:60",
    "addball": "addball:1",
}


def _parts():
    return {k: {"key": k, "cfg": v, "words": CP._POWER[k][2], "line": CP._POWER[k][3], "why": ""}
            for k, v in PARTS.items()}


def test_every_timed_power_is_a_power_with_its_stock_time_among_its_choices():
    for key, (kind, stock, choices) in CP.TIMED.items():
        assert key in CP._POWER and kind in ("save", "plus", "x")
        assert stock in choices and list(choices) == sorted(choices)
        assert CP.power_text(key, stock) == CP._POWER[key][3:5]          # the stock time: the stock words
        assert CP.power_text(key) == CP._POWER[key][3:5]
    assert {3, 5} <= set(CP.TIMED["action_save"][2])                     # the reporter's two
    assert max(CP.TIMED["action_save"][2]) <= 60                         # the runtime's save:<s> top


def test_at_the_stock_time_the_runtime_text_is_as_before():
    keys = list(PARTS)
    stock = CP.compose(keys, _parts())
    assert CP.compose(keys, _parts(), {}) == stock
    assert CP.compose(keys, _parts(), {k: t[1] for k, t in CP.TIMED.items()}) == stock


def test_the_action_save_takes_its_own_seconds():
    got = CP.compose(["action_save", "addball"], _parts(), {"action_save": 5})
    assert got["cfg"] == "save:5,addball:1"
    assert got["line"].startswith("Press Action twice for a 5 second ball save, once a ball. ")
    assert got["words"] == "ACTION BUTTON BALL SAVE, ADD A BALL"            # the badge has no number
    assert CP.compose(["action_save"], _parts(), {"action_save": 3})["cfg"] == "save:3"


def test_the_battle_timers_take_their_own_seconds_and_room_past_the_top():
    got = CP.compose(["battle_timers_10"], _parts(), {"battle_timers_10": 30})
    assert got["cfg"] == ("adj:212+30:30:100,adj:213+30:30:100,adj:214+30:30:100,adj:215+30:30:100,"
                          "adj:216+30:30:120,adj:218+30:30:120")
    assert got["line"] == "30 seconds more on battle timers."
    assert CP.compose(["battle_timers_10"], _parts(), {"battle_timers_10": 5})["cfg"].startswith("adj:212+5:30:80,")


def test_the_longer_powers_take_how_much_longer():
    t = {"ball_save_x2": 300, "o2_x2": 150, "rodan_x2": 400, "addball_save_x2": 300, "multiball_saves_x2": 250}
    got = CP.compose(["ball_save_x2", "o2_x2", "rodan_x2", "addball_save_x2", "multiball_saves_x2"], _parts(), t)
    assert got["cfg"] == ("adj:94x300:0:15,bs:94,"                  # BALL SAVE TIME: still at most its top
                          "adj:193x150:6:30,adj:199x400:80:240,adj:200x300:7:30,adj:203x250:12:75,adj:204x250:12:75")
    assert got["line"] == ("Three times the ball save at the start of every ball. The Oxygen Destroyer lasts one and a "
                           "half times as long. Rodan lasts four times as long. Three times the ball save after every "
                           "added ball, Anguirus's included. Two and a half times the ball save in multiball modes.")


def test_a_character_keeps_its_times_and_only_good_ones(tmp_path):
    project = str(tmp_path)
    chars = CP.save_characters(project, {"pick": True, "list": [
        {"name": "miregoji", "powers": ["action_save", "ball_save_x2"],
         "times": {"action_save": "5", "ball_save_x2": 200, "o2_x2": 300, "addball": 2, "battle_timers_10": 11}},
        {"name": "old", "powers": ["action_save"]}]})
    a, b = chars["list"]
    assert a["times"] == {"action_save": 5}    # the stock time, a power it has not got, an untimed one, no such choice
    assert b["times"] == {}
    assert CP.load_characters(project) == chars
    assert CP.character_line(a) == ("Press Action twice for a 5 second ball save, once a ball. "
                                    "Twice the ball save at the start of every ball.")
    assert CP.character_line(b) == "Press Action twice for a 10 second ball save, once a ball."
    assert CP.time_label("action_save", 5) == "5 seconds" and CP.time_label("battle_timers_10", 30) == "+30 seconds"
    assert CP.time_label("ball_save_x2", 150) == "1.5x as long" and CP.time_label("o2_x2", 200) == "2x as long"


def test_the_dialog_sets_one_powers_time(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs.modes import ModesTab
    project = str(tmp_path)
    CP.save_characters(project, {"pick": True, "list": [{"name": "MIREGOJI", "powers": ["action_save"]}]})
    tab = object.__new__(ModesTab)
    monkeypatch.setattr(tab, "project", lambda: project, raising=False)
    monkeypatch.setattr(tab, "_publish_coop_chars", lambda p: None, raising=False)
    assert tab.coop_char_time(0, "action_save", 5)
    assert CP.load_characters(project)["list"][0]["times"] == {"action_save": 5}
    assert not tab.coop_char_time(0, "action_save", 11)              # not one of its choices
    assert not tab.coop_char_time(0, "addball", 2)                    # not a timed power
    assert not tab.coop_char_time(3, "action_save", 5)                # no such character
    assert tab.coop_char_time(0, "action_save", 10)                   # back to the stock time: nothing kept
    assert CP.load_characters(project)["list"][0]["times"] == {}


def test_the_runtime_gives_the_times_the_app_writes(tmp_path):
    """The character section of pad_mode_runtime.c, built on this host, fed the lines compose() writes: a 5 second
    Action save, and BALL SAVE TIME three times its own 5 (held to its top, 15)."""
    save = CP.compose(["action_save"], _parts(), {"action_save": 5})["cfg"]
    longer = CP.compose(["ball_save_x2"], _parts(), {"ball_save_x2": 300})["cfg"]
    main = T31.MAIN.replace('"adj:94x200:0:15,bs:94 GODZILLA', '"%s GODZILLA' % longer, 1)
    main = main.replace('"save:10 GODZILLA 2000', '"%s GODZILLA 2000' % save, 1)
    out = T31._run(tmp_path, main)
    assert "char 1 [GODZILLA 2000] [ACTION BUTTON BALL SAVE] adj 0 save 5 boost 0 gift 0" in out
    assert "save 5" in out                                            # the double press: a 5 second save
    assert "again 0" in out                                           # once a ball, as before
    t1 = next(ln for ln in out if ln.startswith("t1 0 "))
    assert t1.endswith("reads 94: 15 195: 20")                        # 5 x 3 = 15, the game's own 5 untouched else
    # at x150: 7 (5 x 1.5, rounded down by the runtime)
    main = T31.MAIN.replace('"adj:94x200:0:15,bs:94 GODZILLA',
                            '"%s GODZILLA' % CP.compose(["ball_save_x2"], _parts(), {"ball_save_x2": 150})["cfg"], 1)
    assert next(ln for ln in T31._run(tmp_path, main) if ln.startswith("t1 0 ")).endswith("reads 94: 7 195: 20")
