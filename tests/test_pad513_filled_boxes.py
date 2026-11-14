"""PAD-513 (DragonRR): Scenes marked boxes the game never fills as "filled in by the game".

On Godzilla's Tank Attack Multiball start screen every T of TANK ATTACK (a letter to a box)
read as filled with a stray, unused " T!" of the game program's, and the MULTIBALL title with
a MULTIBALL the game shows elsewhere; the Tank Attack code names only the instruction line on
that screen.  A line the game never reads and a single letter are no stand-ins, and on a
screen whose text boxes a mode's code names, matching words count only on those boxes or for
that mode's own lines."""

import pytest

from tests.test_gui_scene_editor import _tv
from tests.test_pad485_game_line_in_scenes import _project, _wait
from tests.webui_harness import web_app

pytest.importorskip("PIL")


def test_rules_an_unused_line_or_a_letter_fills_nothing():
    from pinball_decryptor.webui import text_rules as R
    rows = [{"path": "/g/game", "original": " T!", "replacement": ""},
            {"path": "/g/game", "original": "STRAY", "replacement": "", "unused": True},
            {"path": "/g/game", "original": "MULTIBALL", "replacement": ""},
            {"path": "/g/game", "original": "GIGAN JACKPOT!", "replacement": "",
             "modes": ["cmode_battle_vs_megalon_and_gigan_mb"]},
            {"path": "/g/s/scene.radium", "original": "TANK", "replacement": ""}]
    idx = R.filled_index(rows)
    assert "T" not in idx and "STRAY" not in idx and "TANK" not in idx
    assert idx["MULTIBALL"] == [("MULTIBALL", [])]
    assert idx["GIGAN JACKPOT"][0][0] == "GIGAN JACKPOT!"


def test_rules_a_placeholder_is_the_games_to_fill():
    """Round 2: words that only hold a place - a score, a count, a line of instructions -
    are written over by the game; a name with an X in it is not one."""
    from pinball_decryptor.webui import text_rules as R
    for s in ("XXX,XXX,XXX", "XXXXXXXXXX", "X,XXX,XXX", "00", "0", "LINE 1 INSTRUCTIONS",
              "Line 2", "LINE12", "INSTRUCTIONS ", "AWARDS +XX FLIPS",
              "COLLECT XX MORE TO START TANK ATTACK MULTIBALL"):
        assert R.is_placeholder(s), s
    for s in ("PLANET X", "DESTROY X MORE TANKS", "EXXON", "MULTIBALL", "LINE", "1,000,000",
              "BRIDGE ATTACK", ""):
        assert not R.is_placeholder(s), s


def _score_scene():
    """The synthetic scene with its title reading XXX,XXX,XXX, as a score box does."""
    from tests.test_stern_scene_tree import FLAG, bitmap, cls, fs, node, sprite, text, texture, u32, u64, u8
    kids = [
        node(50, "Art", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + bitmap(3, 16, 8, texture(21, 16, 8))]),
        node(53, "Score", [u32(1) + cls(3, "Text") + u32(FLAG | 13) + text(5, "XXX,XXX,XXX", (9, 7))]),
    ]
    root = sprite(2, "", 20, kids, labels=[("Start", 1), ("End", 20)])
    return (u8(1) + u64(0) + u64(0) + u32(1360) + u32(768) + fs(30.0) + fs(0.2, 0.2, 0.2, 1.0) + root)


def _layers(w):
    return {l["name"] + str(l["depth"]): l["filled"] for l in _tv(w)["layers"]}


def _open(w, folder):
    w.run(lambda: w.window.write_assets_var.set(str(folder)))
    w.call("ui.select_tab", "scenes")
    w.call("text_scenes.select", "/g/scene1")
    _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [])


def test_a_screen_whose_boxes_a_mode_names_keeps_its_own_words(tmp_path):
    """The scene's two KAIJU titles match the game's KAIJU, a line no mode reads.  With no
    mode naming the screen both read as filled, as before; once the battle vs Gigan's code
    names the screen with its Award_Textbox.Title, only that box is filled."""
    gigan = "cmode_battle_vs_gigan"
    from pinball_decryptor.plugins.stern import engine
    plain = tmp_path / "plain"
    plain.mkdir()
    folder = _project(plain, {"original": "KAIJU"}, two=True)
    with web_app(plain, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Title0"] == layers["Title1"] == {"line": "KAIJU", "modes": []}
        w.call("text_scenes.close")
    named = tmp_path / "named"
    named.mkdir()
    folder = _project(named, {"original": "KAIJU"}, two=True)
    engine._program_modes_read(str(folder), {gigan: ["g/scene1"]},
                               {gigan: {"g/scene1": ["Award_Textbox.Title"]}})
    with web_app(named, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Title0"] is None                     # the screen's own words
        assert layers["Title1"] == {"line": "KAIJU", "modes": []}
        assert layers["Art0"] is None
        w.call("text_scenes.close")


def test_godzilla_le_116_modes_name_the_boxes_they_fill():
    """Round 2 (DragonRR: "Have you checked elsewhere?").  Read from the stock card, the
    boxes each mode names with a screen.  Bridge Attack's super jackpot intro fills BRIDGE,
    ATTACK and MULTIBALL (lines 3424-3426, so they show in the player's language); its
    MULTIBALL box sits 0x228 bytes on in the function and was missed.  The other Tank Attack
    screen names Title_Instance by the tail of "SwitchMeter.Title_Instance".  DragonRR's
    Tank Attack start screen still names only its instruction line."""
    from tests.test_pad470_text_modes import LE116, _program
    from pinball_decryptor.plugins.stern import progtext
    raw = _program(LE116)
    ctx = {}
    progtext.enumerate_program_strings(raw, modes=True, ctx=ctx)
    tank = "687f744516db566f57937aa3345db2e82c3e10ea/"
    bridge = ctx["boxes"]["cmode_bridge_attack_multiball"][
        "fb84341a4f335f98b218a0a03136f3c1e6d88a29/7ec20395bac789edbbc33befe4eed2e0dd589de5"]
    assert bridge == ["Bridge_Textbox.Bridge_Instance", "Attack_Textbox.Attack_Instance",
                      "Multiball_Textbox.Mulitball_Instance"]
    boxes = ctx["boxes"]["cmode_tank_attack_multiball"]
    assert boxes[tank + "bf1c6b2c10e0e4d88a62b43abed5a21fc6b07a63"] == ["Title_Instance",
                                                                       "Line1_Instance"]
    assert boxes[tank + "4567f96cb9de3e97ef274b7cec9e74f7ddd8298b"] == ["Line1_Instance"]


def test_a_score_placeholder_is_marked_with_no_line_to_name(tmp_path):
    """A box reading XXX,XXX,XXX is filled in by the game (its score), with no line of the
    game's text and no mode to name."""
    from pinball_decryptor.core import text_manifest
    from tests.test_gui_scene_editor import _seed
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder, _score_scene())
    text_manifest.save(str(folder), [
        {"path": "/g/scene1/scene.radium", "original": "XXX,XXX,XXX", "replacement": ""},
        {"path": "/g/game", "original": "TILT", "replacement": "", "budget": 4, "fixed": True}])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Score0"] == {"line": None, "modes": []}
        assert layers["Art0"] is None
        w.call("text_scenes.close")


def test_with_the_programs_node_paths_a_box_is_filled_when_the_game_can_name_it(tmp_path):
    """Round 3 (emulator-proven: the game's own set_text hooked on stock Godzilla LE 1.16): the
    game finds a box by its path from the screen's root to write in it.  With the program's
    node paths read, a box is filled exactly when its path is one of them - whatever its
    words match - and its words still find its line."""
    gigan = "cmode_battle_vs_gigan"
    from pinball_decryptor.plugins.stern import engine
    folder = _project(tmp_path, {"original": "KAIJU!", "modes": [gigan]}, two=True)
    engine._program_modes_read(str(folder), {gigan: ["g/scene1"]}, {},
                               ["Award_Textbox.Title", "Award_Textbox", "Other_Instance"])
    assert engine.program_node_paths(str(folder)) == {"Award_Textbox.Title", "Award_Textbox",
                                                      "Other_Instance"}
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        layers = _layers(w)
        assert layers["Title0"] is None          # KAIJU like the line, but the game can't name it
        assert layers["Title1"] == {"line": "KAIJU!", "modes": ["Battle vs Gigan"]}
        assert layers["Art0"] is None
        w.call("text_scenes.close")


def test_an_empty_or_older_reading_has_no_node_paths(tmp_path):
    from pinball_decryptor.plugins.stern import engine
    folder = tmp_path / "p"
    (folder / "text").mkdir(parents=True)
    assert engine.program_node_paths(str(folder)) is None
    engine._program_modes_read(str(folder), {}, {}, [])
    assert engine.program_node_paths(str(folder)) is None


def test_godzilla_le_116_node_paths_are_the_boxes_the_game_wrote():
    """The node paths read off the stock card: the boxes the emulator run saw the game write
    (Ebirah's LEFT, Bridge Attack's MULTIBALL, the score panel's 82-character score path) are
    there; DragonRR's Tank Attack title and letters, which the game never wrote, are not."""
    from tests.test_pad470_text_modes import LE116, _program
    from pinball_decryptor.plugins.stern import text_modes
    paths = set(text_modes.node_refs(_program(LE116)))
    for p in ("Line1_Left_Instance", "Multiball_Textbox.Mulitball_Instance", "Line1_Instance",
              "Player1_Instance.P1_ActiveScore_Instance.ActiveScore_1_Text_Instance.Player1.score",
              "DoubleScoringSlideOut_Artbox.DoubleScoringPanel_Artbox.DoubleScoringTimer_Instance"):
        assert p in paths, p
    for p in ("Title2_Textbox.Title_Instance", "Title2_Textbox", "Letter_7T_Textbox.Letter_7T_Instance",
              "Letter_7T_Instance", "Letter_1T_Textbox.Letter_1T_Instance"):
        assert p not in paths, p


# ---- round 4 (DragonRR): "Where it would be pointless to change the text in the scene ... please
# don't allow the user to edit the text in the scene in those instances"
def _paths(folder, paths):
    from pinball_decryptor.plugins.stern import engine
    engine._program_modes_read(str(folder), {"cmode_battle_vs_gigan": ["g/scene1"]}, {}, paths)


def test_a_scene_line_is_locked_only_when_the_game_writes_every_box_of_it(tmp_path):
    from pinball_decryptor.webui import game_filled
    from tests.test_gui_scene_editor import CARD
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    assert game_filled.locked_lines(str(folder)) == {}            # no reading: no lock
    _paths(folder, ["Award_Textbox.Title"])
    # the root's KAIJU is its own words: new words for the line show there
    assert game_filled.locked_lines(str(folder)) == {}
    _paths(folder, ["Award_Textbox.Title", "Title"])
    assert game_filled.locked_lines(str(folder)) == {CARD: frozenset({"KAIJU"})}
    assert game_filled.is_locked(str(folder), {"path": CARD, "original": "KAIJU"})
    assert not game_filled.is_locked(str(folder), {"path": "/g/game", "original": "KAIJU!"})


def test_the_text_tab_keeps_a_line_the_game_writes(tmp_path):
    """Its New text is refused (it would never show), a Revert still puts back an old edit,
    Replace everywhere leaves it, and the game's own line still takes new words."""
    from tests.test_gui_scene_editor import CARD
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    _paths(folder, ["Award_Textbox.Title", "Title"])
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        w.call("ui.select_tab", "text")
        _wait(w, lambda: not w.state("text")["scanning"] and w.state("text").get("total", 0) > 0)
        rows = w.window.service("text")._text_rows
        scene = next(i for i, r in enumerate(rows) if r["path"] == CARD and r["original"] == "KAIJU")
        w.call("text.select", scene)
        assert w.state("text")["locked"] is True
        assert "game writes this line" in w.state("text")["scene_note"]
        # PAD-1261: the note names the game's own line to change instead
        assert "the game program row “KAIJU!”" in w.state("text")["scene_note"]
        n = len(w.asked)
        assert w.call("text.apply", "MONSTER") is False
        assert len(w.asked) == n + 1 and rows[scene]["replacement"] == ""
        assert w.call("text.apply", "KAIJU") is True                 # its own words: no change
        plan = w.call("text.replace_plan", "KAIJU", "MONSTER", True)
        assert "1 line(s) the game writes itself are left as they are" in plan["text"]
        w.call("text.replace_apply", "KAIJU", "MONSTER", True)
        assert rows[scene]["replacement"] == ""
        prog = next(i for i, r in enumerate(rows) if r["path"] == "/g/game")
        assert rows[prog]["replacement"] == "MONSTER!"
        w.call("text.select", prog)
        assert w.state("text")["locked"] is False


def test_the_scenes_words_box_keeps_a_box_the_game_writes(tmp_path):
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    _paths(folder, ["Award_Textbox.Title"])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        ids = {l["name"] + str(l["depth"]): l["id"] for l in _tv(w)["layers"]}
        w.call("text_scenes.tree_select", ids["Title1"])
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == ids["Title1"])
        words = _tv(w)["props"]["words"]
        assert words["locked"] is True and words["text"] == "KAIJU"
        assert "the game program row “KAIJU!”" in words["note"]          # PAD-1261
        assert w.call("text_scenes.tree_words", ids["Title1"], "MONSTER") is False
        # the root's KAIJU is the scene's own: it still takes new words
        w.call("text_scenes.tree_select", ids["Title0"])
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == ids["Title0"])
        assert _tv(w)["props"]["words"].get("locked") is None
        assert w.call("text_scenes.tree_words", ids["Title0"], "MONSTER") is True
        w.call("text_scenes.close")


def test_without_the_programs_paths_nothing_is_locked(tmp_path):
    """The older marks are guesses: a guess never stops an edit."""
    folder = _project(tmp_path, {"original": "KAIJU"}, two=True)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        layers = {l["name"] + str(l["depth"]): l for l in _tv(w)["layers"]}
        assert layers["Title0"]["filled"]                     # marked by its words
        w.call("text_scenes.tree_select", layers["Title0"]["id"])
        _wait(w, lambda: (_tv(w).get("props") or {}).get("id") == layers["Title0"]["id"])
        assert _tv(w)["props"]["words"].get("locked") is None
        assert w.call("text_scenes.tree_words", layers["Title0"]["id"], "MONSTER") is True
        w.call("text_scenes.close")


def test_the_note_names_the_games_line_only_when_there_is_one():
    """PAD-1261 (DragonRR): Godzilla's award screen 293641e4 holds "IMPOSTER BATTLE" in a title
    box the game fills with whichever award was won.  The note said "Change the game's own line
    instead: it is a game program row on the Text tab", but no program line reads IMPOSTER
    BATTLE (only IMPOSTER BATTLE CHAMPION): it names the line when there is one, and otherwise
    says the words are a stand-in."""
    from pinball_decryptor.webui import game_filled as G
    card = "/godzilla_le/assets/lcd/auto_loaded/293641e4/scene.radium"
    rows = [{"path": card, "original": "IMPOSTER BATTLE"},
            {"path": "/godzilla_le/game", "original": "IMPOSTER BATTLE CHAMPION"},
            {"path": "/godzilla_le/game", "original": "Imposter Battle Champion"}]
    note = G.locked_note("IMPOSTER BATTLE", rows)
    assert note.startswith(G.LOCKED_NOTE)
    assert "“IMPOSTER BATTLE” is only a stand-in" in note and "game program row “" not in note
    # the same words, case, spacing and a closing ! aside, name the game's line
    rows.append({"path": "/godzilla_le/game", "original": "Imposter  battle!"})
    assert "the game program row “Imposter battle!”" in G.locked_note("IMPOSTER BATTLE", rows)
    rows.append({"path": "/godzilla_le/game", "original": "IMPOSTER BATTLE"})
    assert "the game program row “IMPOSTER BATTLE”" in G.locked_note("IMPOSTER BATTLE", rows)
    # a line the game never reads, one mode's own text and a single letter are no line to change
    odd = [{"path": "/g/game", "original": "TANK", "unused": True},
           {"path": "/g/game#cmode_x", "original": "TANK"},
           {"path": "/g/game", "original": " T!"}]
    assert "only a stand-in" in G.locked_note("TANK", odd)
    assert G.game_row_for(odd, "T") is None
    assert G.locked_note("", odd) == G.LOCKED_NOTE
