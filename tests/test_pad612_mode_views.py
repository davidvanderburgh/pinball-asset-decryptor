"""PAD-612: a blocks mode's views are tabs over its one program, and the Playfield is one of them.

* The playfield picture is the game's own, read off the card (playfield_art.pick_art chooses it as the emulator's
  playfield window does), and the inserts sit where the port's lamp lines say (``at X,Y``).
* modes.blocks_playfield gives the page both, each insert with the shots it lights for.
* The page's views share one program and one history (modes_blocks.js useModeProgram): an edit made through one
  view's blocks is undone from the pane's Undo and saved as the program it was. Run under Node, with the page's
  core stubbed, as test_pad350 does.
* modes_views.js reads off the program what the Playfield draws: lit shots and lights in their colors, the rules
  that name a shot or a light, a rule's When in words.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import playfield_art as PA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TABS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
GODZILLA_PRO = r"D:\Pinball\images\Stern\spike2\godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"


# ------------------------------------------------------------ which picture
def test_the_models_own_drawing_is_picked_by_whole_words():
    both = {"": ["Test", "Fonts"], "Test": ["scaled_godzilla_le_playfield.png", "scaled_godzilla_pro_playfield.png",
                                          "lamp.png"]}
    assert PA.pick_art(both, "godzilla_le") == "Test/scaled_godzilla_le_playfield.png"
    assert PA.pick_art(both, "godzilla_pro") == "Test/scaled_godzilla_pro_playfield.png"
    # "le" is not found inside "scaled": Jaws puts the qualifier last
    jaws = {"": ["Test"], "Test": ["jaws_pro_playfield_scaled.png", "jaws_le_playfield_scaled.png"]}
    assert PA.pick_art(jaws, "jaws_le") == "Test/jaws_le_playfield_scaled.png"


def test_the_folder_is_any_that_says_test():
    assert PA.pick_art({"": ["TestMode"], "TestMode": ["kk_playfield.png"]}, "king_kong_le") == "TestMode/kk_playfield.png"
    jp = {"": ["test_menu", "ui"], "test_menu": ["jp_pro_playfield.png", "jp_le_playfield.png"]}
    assert PA.pick_art(jp, "jurassic_park_le") == "test_menu/jp_le_playfield.png"
    nested = {"": ["System"], "System": ["TestMode"], "System/TestMode": ["elvira_playfield.png"]}
    assert PA.pick_art(nested, "elvira3_le") == "System/TestMode/elvira_playfield.png"


def test_an_le_falls_back_to_the_premiums_drawing_and_top_is_the_2025_word():
    xmen = {"": ["TestMode"], "TestMode": ["xmen_pro_playfield_scaled.png", "xmen_pre_playfield_scaled.png"]}
    assert PA.pick_art(xmen, "uncanny_xmen_le") == "TestMode/xmen_pre_playfield_scaled.png"
    assert PA.pick_art(xmen, "uncanny_xmen_pro") == "TestMode/xmen_pro_playfield_scaled.png"
    dnd = {"": ["Test"], "Test": ["ROPE_BACK_PANEL_cropped.png", "Rope_PRO-X7_TOP_rotated_cropped.png",
                                  "Rope_LE-Premium-X8-X9_TOP_rotated_edit_cropped.png"]}
    assert PA.pick_art(dnd, "dungeons_and_dragons_le") == "Test/Rope_LE-Premium-X8-X9_TOP_rotated_edit_cropped.png"
    assert PA.pick_art({"": ["Test"], "Test": ["cabinet.png"]}, "deadpool_le") == ""
    assert PA.pick_art({"": []}, "deadpool_le") == ""


# ------------------------------------------------------------ where the inserts are
def test_the_inserts_are_placed_where_the_port_says():
    places = PA.insert_places(os.path.join(MP.PORTS_DIR, "godzilla_pro-1.15.port"))
    assert len(places) == 81
    by = {p["name"]: p for p in places}
    assert (by["RIGHT RAMP"]["x"], by["RIGHT RAMP"]["y"]) == (199, 189)
    p = MP.profile_for_card("godzilla_pro", "1.15.0")
    assert [n for n, m in p.shots if m & by["RIGHT RAMP"]["shot"]] == ["Right ramp"]
    assert "SHOOT AGAIN (X2)" not in by                         # at 0,0: not on the picture
    assert PA.insert_places(os.path.join(MP.PORTS_DIR, "no_such-0.0.port")) == []


@pytest.mark.skipif(not os.path.isfile(GODZILLA_PRO), reason="needs the Godzilla Pro 1.15 card")
def test_the_picture_comes_off_the_card():
    data, where = PA.card_art(GODZILLA_PRO, "godzilla_pro")
    assert where == "/godzilla_pro/assets/nuk/images/Test/scaled_godzilla_pro_playfield.png"
    assert PA.png_size(data) == (313, 710)
    assert PA.card_art(GODZILLA_PRO, "godzilla_pro")[0] is data          # kept: a tab switch reads nothing again
    assert PA.card_art(GODZILLA_PRO, "no_such_game") == (None, "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw "
                                                                "has no no_such_game/assets/nuk/images folder")


def test_a_missing_card_says_why():
    got = PA.card_art(os.path.join(ROOT, "no-such-card.raw"), "godzilla_pro")
    assert got[0] is None and got[1].startswith("the card image could not be opened")


# ------------------------------------------------------------ the tab's call
def test_blocks_playfield_gives_the_picture_and_the_inserts(tmp_path, monkeypatch):
    from tests.test_webui_modes import _project, preview_on  # noqa: F401
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    from pinball_decryptor.webui.tabs import modes as tab
    monkeypatch.setattr(preview, "enabled", lambda feature: True)
    card = MP.ProjectCard(str(tmp_path / "godzilla_pro-1_15_0.raw"), "godzilla_pro", "1.15.0", "test")
    (tmp_path / "godzilla_pro-1_15_0.raw").write_bytes(b"")      # PAD-623: only a card that is there is read
    monkeypatch.setattr(tab.ModesTab, "_title_card", lambda self, project: (card, "project"))
    png = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x019\0\0\x02\xc6" + b"\0" * 8
    asked = []
    monkeypatch.setattr(PA, "card_art", lambda image, game: asked.append((image, game)) or (png, "/x.png"))
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, tmp_path / "proj")
        assert w.call("modes.new_blocks_mode", "Ramp Frenzy") == "ramp_frenzy"
        got = w.call("modes.blocks_playfield")
        assert asked == [(card.image, "godzilla_pro")]
        assert (got["w"], got["h"], got["why"]) == (313, 710, "")
        assert got["art"].startswith("data:image/png;base64,")
        got_art = got["art"]
        ramp = next(i for i in got["inserts"] if i["name"] == "RIGHT RAMP")
        assert ramp == {"name": "RIGHT RAMP", "x": 199, "y": 189, "shots": ["Right ramp"]}
        assert len(got["inserts"]) == 81
        # a card of another game: the inserts still, no picture, and why
        monkeypatch.setattr(tab.ModesTab, "_title_card", lambda self, project: (
            MP.ProjectCard(card.image, "godzilla_le", "1.15.0", "test"), "project"))
        # PAD-623: the shown game's picture read before is kept on this computer, so it still shows ...
        assert w.call("modes.blocks_playfield")["art"] == got_art
        os.remove(PA._kept_path("godzilla_pro"))
        # ... and with none kept, why not
        got = w.call("modes.blocks_playfield")
        assert got["art"] == "" and "another game's (godzilla_le)" in got["why"] and len(got["inserts"]) == 81
        monkeypatch.setattr(PA, "card_art", lambda image, game: (None, "godzilla_pro ships no playfield picture"))
        monkeypatch.setattr(tab.ModesTab, "_title_card", lambda self, project: (card, "project"))
        assert w.call("modes.blocks_playfield")["why"] == "No playfield picture: godzilla_pro ships no playfield picture."


# ------------------------------------------------------------ the page (Node)
def _stage(tmp_path, names):
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    stubs = {}
    for name in names:
        src = open(os.path.join(_TABS, name), encoding="utf-8").read()
        (tmp_path / "tabs" / name).write_text(src, encoding="utf-8")
        for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
            stubs.setdefault(m.group(2), set()).update(n.strip() for n in m.group(1).split(",") if n.strip())
    return stubs


# the hooks run outside Preact: state is a box, effects are not run, and modes.blocks_save is recorded
_UI = r"""
export const saved = [];
export const useState = (init) => { const box = { v: typeof init === "function" ? init() : init };
  return [box.v, (v) => { box.v = typeof v === "function" ? v(box.v) : v; }]; };
export const useRef = (v) => ({ current: v });
export const useEffect = () => {};
export const call = (name, ...args) => { saved.push([name, ...args]); return Promise.resolve({}); };
export const html = () => null;
"""

_RUN = r"""
const ui = await import("./core/ui.js");
const B = await import("./tabs/modes_blocks.js");
const P = await import("./tabs/modes_playfield.js");
const c = { slug: "ramp", blocks: { program: { name: "RAMP", scripts: [{ hat: { kind: "mode_start" }, do: [] }] },
  choices: { shots: ["Left ramp", "Right ramp"] } } };
const pg = B.useModeProgram(c);
const blocksView = B.useEd(pg, c.blocks.choices);        // the Blocks tab's
const fieldView = B.useEd(pg, c.blocks.choices);         // the Playfield tab's
fieldView.addScript({ kind: "shot", shot: "Right ramp", when: "running" });
blocksView.set(["name"], "RAMP 2");
await new Promise((r) => setTimeout(r, 700));
const afterEdits = ui.saved.at(-1)[2];
pg.undo();                                                // the pane's Undo: the name, then the Playfield's rule
pg.undo();
await new Promise((r) => setTimeout(r, 700));
const afterUndo = ui.saved.at(-1)[2];
pg.undo(true);
await new Promise((r) => setTimeout(r, 700));
console.log(JSON.stringify({ afterEdits, afterUndo, afterRedo: ui.saved.at(-1)[2], exports: Object.keys(P).sort(),
  saves: ui.saved.length }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_every_view_edits_one_program_with_one_history(tmp_path):
    stubs = _stage(tmp_path, ("modes_blocks.js", "modes_playfield.js", "modes_views.js"))
    names = set().union(*stubs.values()) - {"useState", "useRef", "useEffect", "call", "html"}
    (tmp_path / "core" / "ui.js").write_text(_UI + "".join("export const %s = () => null;\n" % n for n in sorted(names)),
                                              encoding="utf-8")
    (tmp_path / "tabs" / "modes_dialogs.js").write_text("export const PlayButton = () => null;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js")], capture_output=True, text=True,
                         timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["afterEdits"]["name"] == "RAMP 2"
    assert got["afterEdits"]["scripts"][1] == {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": []}
    assert got["afterUndo"] == {"name": "RAMP", "scripts": [{"hat": {"kind": "mode_start"}, "do": []}]}
    assert len(got["afterRedo"]["scripts"]) == 2 and got["afterRedo"]["name"] == "RAMP"
    assert got["exports"] == ["PickOnField", "PlayfieldView", "loadPlayfield"]     # PAD-614: the shot picker too
    assert got["saves"] == 3                                  # a save a moment after each burst, the whole program


_VIEWS = r"""
const V = await import("./tabs/modes_views.js");
const prog = JSON.parse(process.argv[2]);
const sc = prog.scripts;
console.log(JSON.stringify({
  lights: V.lights(prog),
  used: [...V.usedShots(prog)].sort(),
  rightRamp: sc.map((s, i) => [s, i]).filter(([s]) => V.names(s, "Right ramp")).map(([, i]) => i),
  villain: sc.map((s, i) => [s, i]).filter(([s]) => V.names(s, "VILLAIN", true)).map(([, i]) => i),
  hats: sc.map((s) => V.hatWords(s.hat, { events: [{ name: "skill_shot", label: "the skill shot is made" }] })),
  blocks: sc.map((s) => V.countBlocks(s)),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_playfield_reads_the_program(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "tools", "mode_views"))
    try:
        import showcase
    finally:
        sys.path.pop(0)
    prog = showcase.program()
    prog["scripts"] += [
        {"hat": {"kind": "event", "event": "skill_shot", "when": "idle"}, "do": [
            {"op": "light_mode", "shot": "Left ramp", "insert": "VILLAIN, HENCH", "color": "#00ff00", "pattern": "chase",
             "solid": "FILM", "solid_color": "#ffffff"},
            {"op": "light_shot", "insert": "MAGNA GRAB", "color": "#ff0000", "pattern": "off"}]},
        {"hat": {"kind": "timer_done", "timer": "window"}, "do": []},
        {"hat": {"kind": "every", "seconds": 5}, "do": []}]
    _stage(tmp_path, ("modes_views.js",))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_VIEWS, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js"), json.dumps(prog)], capture_output=True,
                         text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    # RAMP FRENZY lights the Right ramp yellow, blinking, at its start; the Big loop blue, chasing, in the jackpot
    assert got["lights"]["shots"]["Right ramp"] == {"color": "#ffd000", "pattern": "blink"}
    assert got["lights"]["shots"]["Big loop"]["pattern"] == "chase"
    assert got["lights"]["shots"]["Left ramp"] == {"color": "#00ff00", "pattern": "chase"}
    assert got["lights"]["lamps"] == {"VILLAIN": {"color": "#00ff00", "pattern": "chase"},
                                      "HENCH": {"color": "#00ff00", "pattern": "chase"},
                                      "FILM": {"color": "#ffffff", "pattern": "solid"},
                                      "MAGNA GRAB": {"color": "", "pattern": "off"}}
    assert got["used"] == ["Big loop", "Left ramp", "Right ramp"]
    names = [s["hat"] for s in prog["scripts"]]
    assert all(names[i]["kind"] != "shot" or names[i]["shot"] == "Right ramp" for i in got["rightRamp"])
    assert any(names[i].get("shot") == "Right ramp" for i in got["rightRamp"])
    assert any(names[i]["kind"] == "mode_start" for i in got["rightRamp"])      # it lights the Right ramp
    assert got["villain"] == [len(prog["scripts"]) - 3]
    assert got["hats"][0] == "When Left ramp is made, while it is not running"
    assert got["hats"][-3:] == ["When the skill shot is made, while it is not running", "When timer window runs out",
                                "Every 5 seconds while it runs"]
    assert got["blocks"][-3:] == [2, 0, 0]
