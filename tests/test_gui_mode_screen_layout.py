"""Lay out a mode's screen in the Scenes editor (PAD-323), driven through the calls the canvas
makes (webui/scene_mode_layout.py).

"Lay out on the screen..." opens the editor on the title's HUD scene with the mode's screen in
it as virtual layers; moving, sizing and re-layering them writes the mode's ``screen_layout``
(never ``scene_edits.json``), Undo takes it back, As shipped puts the automatic place back, and
Done leaves the scene as the game ships it.
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

pytest.importorskip("numpy")
pytest.importorskip("PIL")

HUD_DIR = "/godzilla_pro/assets/lcd/auto_loaded/32e6ae280ddaec08e203a02289bb39a04968e7b0"
CARD = HUD_DIR + "/scene.radium"
SLUG = "kaiju_rush"


def _seed(folder):
    """The synthetic scene of tests/test_stern_scene_tree.py at the Godzilla HUD's card path,
    and one form mode with a generated panel."""
    from PIL import Image
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import scene_eval, scene_tree
    from tests.test_stern_scene_tree import scene
    sc = scene_tree.parse(scene())
    tex = folder / "images" / "scene_textures"
    tex.mkdir(parents=True)
    tex2rel, rows = {}, []
    for tid, t in sc.textures.items():
        rel = "scene_textures/pic_%d.png" % tid
        Image.new("RGBA", (t["w"], t["h"]), (200, 40, 40, 255)).save(str(folder / "images" / rel))
        tex2rel[t["data_off"]] = rel
        rows.append("%s\t%s\t%d\t%d\t%d\t%d\t5" % (rel, CARD, t["data_off"], len(t["blob"]),
                                                   t["w"], t["h"]))
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    man = scene_eval.manifest(sc, tex2rel)
    (tex / "scene_tree.json").write_text(json.dumps({CARD: man}), encoding="utf-8")
    spec = MP.blank_spec(MP.GODZILLA_PRO_1_15, "KAIJU RUSH")
    MP.save(str(folder), SLUG, spec)
    return man


def _wait(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _layout(folder):
    with open(os.path.join(str(folder), "modes", SLUG, "mode.json"), encoding="utf-8") as f:
        return json.load(f).get("screen_layout")


def _tv(w):
    return w.state("text_scenes")["tree_view"]


def test_a_mode_screen_is_laid_out_into_its_mode_file(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit
    from pinball_decryptor.webui import scene_mode_layout as ML
    folder = tmp_path / "proj"
    folder.mkdir()
    man = _seed(folder)
    n_root = len(man["root"]["kids"])
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        text = w.window.service("text")
        ok, why = w.run(text.scenes.open_mode_layout, str(folder), SLUG)
        assert ok, why
        assert _wait(w, lambda: (w.state("text_scenes").get("tree_view") or {}).get("layers"))
        st = w.state("text_scenes")
        assert st["sel"] == HUD_DIR
        assert st["mode_layout"]["mode"] == "KAIJU RUSH" and not st["mode_layout"]["laid_out"]
        layers = {l["id"]: l for l in _tv(w)["layers"]}
        assert layers[ML.GROUP_ID]["name"] == "PadMode_kaiju_rush_Screen"
        assert layers[ML.GROUP_ID]["mode"] and layers[ML.ART_ID]["mode"]
        # drawn where the build puts the generated panel, on top of the scene's own (last)
        assert _tv(w)["sel"] == ML.GROUP_ID
        box = w.run(text.scenes._tree_box, ML.ART_ID)
        assert (round(box[0]), round(box[1])) == (360, 200)
        kids = [n["id"] for n in text.scenes._tman["root"]["kids"]]
        assert kids.index(ML.GROUP_ID) == n_root

        # a drag of the picture moves the whole screen; nothing goes into scene_edits.json
        assert w.call("text_scenes.tree_move", ML.ART_ID, 40, -20)
        assert _layout(folder) == {"x": 400.0, "y": 180.0}
        assert scene_edit.ops_for(str(folder), CARD) == []
        assert w.state("text_scenes")["mode_layout"]["laid_out"]
        # sized from its top-left (PAD-557): the corner stays, the size is kept as one number
        assert w.call("text_scenes.tree_set_scale", ML.ART_ID, 50)
        lay = _layout(folder)
        assert lay["scale"] == 0.5 and (lay["x"], lay["y"]) == (400.0, 180.0)
        assert w.call("text_scenes.tree_select", ML.ART_ID)
        assert _tv(w)["props"]["scale"] == 50
        # a drag of a sized picture moves it as far on the glass as the pointer went
        assert w.call("text_scenes.tree_move", ML.ART_ID, -60, 30)
        lay = _layout(folder)
        assert (lay["x"], lay["y"], lay["scale"]) == (340.0, 210.0, 0.5)
        box = w.run(text.scenes._tree_box, ML.ART_ID)
        assert (round(box[0]), round(box[1])) == (340, 210)
        # under the HUD: Send to back puts it before every one of the scene's own
        assert w.call("text_scenes.tree_order", ML.GROUP_ID, "back")
        assert _layout(folder)["order"] == 0
        assert w.state("text_scenes")["mode_layout"]["under"]
        kids = [n["id"] for n in text.scenes._tman["root"]["kids"]]
        assert kids[0] == ML.GROUP_ID

        # what cannot be done to a mode's screen here is said, never written
        assert not w.call("text_scenes.tree_visible", ML.ART_ID, False)
        assert not w.call("text_scenes.tree_rotate", ML.GROUP_ID, 30)
        assert scene_edit.ops_for(str(folder), CARD) == []

        # Undo steps back over the layout, Redo forward again
        assert w.call("text_scenes.tree_undo")
        assert "order" not in _layout(folder)
        assert w.call("text_scenes.tree_redo")
        assert _layout(folder)["order"] == 0
        # As shipped on the picture: the automatic place again
        assert w.call("text_scenes.tree_reset", ML.GROUP_ID)
        assert _layout(folder) == {}

        # Done: the scene is the game's own again
        assert w.call("text_scenes.mode_layout_done")
        assert _wait(w, lambda: ML.GROUP_ID not in {l["id"] for l in _tv(w)["layers"]})
        assert w.state("text_scenes")["mode_layout"] is None


def test_a_blocks_modes_info_line_is_laid_out_into_its_assets(tmp_path):
    """PAD-547: a blocks mode's info line ("SUPER JACKPOT = ...") comes into the editor beside its screen as a layer of
    its own, where the build puts it, saying the program's words; dragging it writes the mode's info_layout (its screen's
    layout untouched), Undo takes it back, Place automatically clears it, and the build reads it."""
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import scene_edit
    from pinball_decryptor.webui import scene_mode_layout as ML
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    project = str(folder)
    slug, _c = BM.new_blocks_mode(project, "DAF WIZARD")
    BM.save(project, slug, BM.normalize({
        "name": "DAF WIZARD", "screen": True, "vars": [{"name": "superjackpot"}],
        "info": {"on": True, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}}, "scripts": []}))
    spec = CM.load(project, slug)
    spec.extra["title"] = "godzilla_pro_1_15"
    CM.save(project, slug, spec)
    info = lambda: CM.load(project, slug).info_layout                 # noqa: E731
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(project))
        text = w.window.service("text")
        ok, why = w.run(text.scenes.open_mode_layout, project, slug)
        assert ok, why
        assert _wait(w, lambda: ML.INFO_GROUP_ID in {l["id"] for l in (_tv(w) or {}).get("layers") or ()})
        assert w.state("text_scenes")["mode_layout"]["what"] == "screen and info line"
        layers = {l["id"]: l for l in _tv(w)["layers"]}
        assert layers[ML.INFO_GROUP_ID]["name"] == "PadMode_%s_Info" % slug and layers[ML.INFO_ART_ID]["mode"]
        assert layers[ML.GROUP_ID]["name"] == "PadMode_%s_Screen" % slug
        # where the build puts it: centred on the title's place for it (Godzilla's port names none: the default)
        aw, ah = MA.INFO_ART
        box = w.run(text.scenes._tree_box, ML.INFO_ART_ID)
        assert (round(box[0]), round(box[1])) == (round(MA.INFO_AT_DEFAULT[0] - aw / 2), round(MA.INFO_AT_DEFAULT[1] - ah / 2))
        # its words, as the program says them (this synthetic scene has no font for words, so none are drawn here)
        assert ML.info_words(project, slug) == "SUPER JACKPOT = 1,234,567"
        assert text.scenes._mlay["parts"]["info"]["words_rgba"] == [1.0, 1.0, 1.0, 1.0]
        kids = [n["id"] for n in text.scenes._tman["root"]["kids"]]
        assert kids.index(ML.INFO_GROUP_ID) == kids.index(ML.GROUP_ID) + 1     # drawn over its screen

        # a drag of its band moves the line alone, into info_layout; nothing in scene_edits.json
        assert w.call("text_scenes.tree_move", ML.INFO_ART_ID, 10, 60)
        x0, y0 = MA.INFO_AT_DEFAULT[0] - aw / 2, MA.INFO_AT_DEFAULT[1] - ah / 2
        assert info() == {"x": x0 + 10, "y": y0 + 60}
        assert CM.load(project, slug).screen_layout == {}
        assert scene_edit.ops_for(project, CARD) == []
        scr = [s for s in MA._code_screens(project, [(slug, CM.load(project, slug))], MP.GODZILLA_PRO_1_15)
               if s["name"].endswith("_Info")][0]
        assert (scr["x"], scr["y"]) == (x0 + 10, y0 + 60)                        # the build reads it
        # the screen's own drag leaves the line's layout alone
        assert w.call("text_scenes.tree_move", ML.ART_ID, 40, -20)
        assert CM.load(project, slug).screen_layout == {"x": 400.0, "y": 180.0} and info() == {"x": x0 + 10, "y": y0 + 60}
        # Undo steps back one part at a time
        assert w.call("text_scenes.tree_undo")
        assert CM.load(project, slug).screen_layout == {} and info() == {"x": x0 + 10, "y": y0 + 60}
        assert w.call("text_scenes.tree_undo")
        assert info() == {}
        assert w.call("text_scenes.tree_redo")
        assert info() == {"x": x0 + 10, "y": y0 + 60}
        # Place automatically: both back
        assert w.call("text_scenes.mode_layout_auto")
        assert info() == {} and CM.load(project, slug).screen_layout == {}
        assert w.call("text_scenes.mode_layout_done")


def test_a_words_alone_modes_scored_number_is_laid_out_into_its_assets(tmp_path):
    """PAD-709: a words-alone blocks mode's scored number (a shot's points, large under the bar) comes into the editor
    as a part of its own beside its screen and its info line, where the build puts it; dragging or sizing it writes the
    mode's points_layout alone, the build reads it, and Place automatically clears it."""
    from pinball_decryptor.plugins.stern import block_modes as BM
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import scene_edit
    from pinball_decryptor.webui import scene_mode_layout as ML
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    project = str(folder)
    slug, _c = BM.new_blocks_mode(project, "BOND VS SUMO")
    BM.save(project, slug, BM.normalize({
        "name": "BOND VS SUMO", "screen": True, "screen_style": "words", "vars": [{"name": "superjackpot"}],
        "info": {"on": True, "text": "SUPER JACKPOT", "value": {"k": "var", "name": "superjackpot"}}, "scripts": []}))
    spec = CM.load(project, slug)
    spec.extra["title"] = "godzilla_pro_1_15"
    CM.save(project, slug, spec)
    pts = lambda: CM.load(project, slug).points_layout                 # noqa: E731
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(project))
        text = w.window.service("text")
        ok, why = w.run(text.scenes.open_mode_layout, project, slug)
        assert ok, why
        assert _wait(w, lambda: ML.POINTS_GROUP_ID in {l["id"] for l in (_tv(w) or {}).get("layers") or ()})
        assert w.state("text_scenes")["mode_layout"]["what"] == "screen, info line and scored number"
        layers = {l["id"]: l for l in _tv(w)["layers"]}
        assert layers[ML.POINTS_GROUP_ID]["name"] == "PadMode_%s_Points" % slug and layers[ML.POINTS_ART_ID]["mode"]
        assert layers[ML.POINTS_GROUP_ID]["edits"] == "the mode's scored number, placed automatically"
        # where the build puts it: under the info line's place, by POINTS_DY
        aw, ah = MA.POINTS_ART
        x0, y0 = MA.INFO_AT_DEFAULT[0] - aw / 2, MA.INFO_AT_DEFAULT[1] + MA.POINTS_DY - ah / 2
        box = w.run(text.scenes._tree_box, ML.POINTS_ART_ID)
        assert (round(box[0]), round(box[1])) == (round(x0), round(y0))
        part = text.scenes._mlay["parts"]["points"]
        assert part["words"] == ML.POINTS_SAMPLE and part["words_scale0"] == MA.POINTS_SCALE
        # a drag of its band moves the number alone, into points_layout; nothing in scene_edits.json
        assert w.call("text_scenes.tree_move", ML.POINTS_ART_ID, 0, -40)
        assert pts() == {"x": x0, "y": y0 - 40}
        spec = CM.load(project, slug)
        assert spec.screen_layout == {} and spec.info_layout == {}
        assert scene_edit.ops_for(project, CARD) == []
        scr = [s for s in MA._code_screens(project, [(slug, spec)], MP.GODZILLA_PRO_1_15)
               if s["name"].endswith("_Points")][0]
        assert (scr["x"], scr["y"]) == (x0, y0 - 40)                             # the build reads it
        assert w.call("text_scenes.tree_undo")
        assert pts() == {}
        assert w.call("text_scenes.tree_redo")
        assert w.call("text_scenes.mode_layout_auto")
        assert pts() == {}
        assert w.call("text_scenes.mode_layout_done")
