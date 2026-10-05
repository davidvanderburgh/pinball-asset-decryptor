"""PAD-369 (DragonRR): color profile quality of life.

* a profile picked for the individual files turns the preview's Individual files switch on
  (Scenes and the Video players) where it was off, and leaves it on;
* the chosen file's name on the Images and Video tabs tells its color profile, and every
  tooltip shows "Color profile: <name>" in one color of its own;
* a change in Scenes redraws faster (the colour ranges are worked out once per colour);
* the Scenes list's hide button is a bolder call to action;
* Scenes saves a scene, or every scene, with its replaced pictures and color profiles, and
  loading it deletes nothing and asks before changing the user's own choices.
"""

import json
import os
import zipfile

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL.Image")

_STATIC = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                       "webui", "static")
RED = cp.Profile(name="Custom red", gain=(1.3, 0.9, 0.9))


def _src(*parts):
    return open(os.path.join(_STATIC, *parts), encoding="utf-8").read()


# -- the lag -------------------------------------------------------------------------

def test_ranges_once_per_colour_give_the_same_numbers():
    screen = cp.SCREEN_PRESETS[0][1]
    assert any(not cp.range_neutral(r) for r in screen.ranges)
    rng = np.random.default_rng(369)
    # a frame with flat areas and noise: few colours and many
    img = rng.integers(0, 256, (180, 320, 3), dtype=np.uint8)
    img[:90] = img[0, 0]
    live = [r for r in screen.ranges if not cp.range_neutral(r)]
    want = np.clip(cp.apply_ranges(img, live) + 0.5, 0, 255).astype(np.uint8)
    assert np.array_equal(cp._ranges_uint8(img, live), want)
    assert np.array_equal(cp._ranges_uint8(img[:4, :4], live), want[:4, :4])
    # and through the profile as the Scenes preview uses it
    plain = screen.plain()
    base = plain.apply_array(img)
    tabs = screen.curve_tables()
    ref = np.clip(cp.apply_ranges(base, live) + 0.5, 0, 255).astype(np.uint8)
    if tabs is not None:
        luts = [np.asarray(t, np.uint8) for t in tabs]
        ref = np.stack([luts[c][ref[..., c]] for c in range(3)], axis=-1)
    assert np.array_equal(screen.apply_array(img), ref)


# -- the preview switch ------------------------------------------------------------------

def test_a_profile_picked_for_a_file_switches_its_preview_on(tmp_path):
    from tests.webui_harness import web_app
    from tests.test_webui_images import _project, _set_folder, _wait, _settled, BANNER
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
        assert w.call("images.choose", BANNER) == BANNER
        w.drain()
        scenes = w.window.service("text").scenes
        video = w.window.service("video")
        assert w.call("video.set_look_part", "files", False)
        w.run(lambda: scenes.set_look_part("files", False))
        w.drain()
        assert scenes._look_sw()["files"] is False and video._lsw["files"] is False
        assert w.call("color.panel_open")
        assert w.call("color.set_file", "images", BANNER, "SpaceGodzilla.png", True,
                      {"ns": "images"})
        w.drain()
        # a slider moved is not a pick: the switch the user turned off stays off
        w.call("color.set_params", {"gain": [1.2, 1.0, 1.0]})
        w.drain()
        assert scenes._look_sw()["files"] is False and video._lsw["files"] is False
        # a starting point picked is: both previews show it, and remember it
        assert w.call("color.preset", "recommended")
        w.drain()
        assert scenes._look_sw()["files"] is True and video._lsw["files"] is True
        saved = w.window.cb["initial_look_switches"]
        assert saved["scenes"]["files"] is True and saved["video"]["files"] is True
        # turned off again by the user, it stays off until the next pick
        assert w.call("video.set_look_part", "files", False)
        w.drain()
        assert video._lsw["files"] is False


# -- the tooltips and the hide button --------------------------------------------------

def test_the_chosen_file_name_tells_its_profile_in_one_color():
    ui = _src("js", "core", "ui.js")
    assert "tip-cp" in ui and '"Color profile: "' in ui
    css = _src("css", "app.css")
    assert ".tip .tip-cp { color: var(--cp-ink); }" in css
    assert css.count("--cp-ink:") == 2                       # dark and light
    for name in ("images.js", "video.js"):
        src = _src("js", "tabs", name)
        assert "{ profile: " in src and "Color profile: ${" not in src, name
        rep = src[src.index('key: "rep"'):]
        assert "profileLine(" in rep[:900], name + ": the replacement's own tooltip"
    ts = _src("js", "tabs", "text_scenes.js")
    assert 'return { profile: "None" }' in ts


def test_the_scene_list_hide_button_is_bolder():
    ts = _src("js", "tabs", "text_scenes.js")
    btn = ts[ts.index('cls="sc-list-hide"'):]
    assert ">Hide<//>" in btn[:400]
    # the caret under the preview, beside the zoom (the one in DragonRR's screenshot)
    bar = ts[ts.index('<div class="scenes-stagebar">'):]
    assert 'cls="sc-list-hide"' in bar[:500] and '"Hide list"' in bar[:500]
    assert 'kind="ghost" icon=${wide' not in ts
    css = _src("css", "tabs", "text_scenes.css")
    assert ".btn.sc-list-hide {" in css and "var(--accent-soft)" in css


# -- scenes saved with everything -----------------------------------------------------

CARD = "/game/scenes/0123456789abcdef/scene.radium"
PIC = "scene_textures/radimg_hero_40x20_aaaa.png"
ADDED = "scene_textures/added/mine.png"


def _proj(root, name, colour):
    d = root / name
    (d / "images" / "scene_textures" / "added").mkdir(parents=True)
    PIL.new("RGB", (40, 20), (1, 2, 3)).save(d / "images" / PIC)
    return str(d)


def _trees():
    return {CARD: {"objects": {"1": {"kind": "Bitmap", "image": PIC},
                               "2": {"kind": "Text"}}}}


def test_save_everything_and_load_it_without_deleting_anything(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit, scene_share
    a = _proj(tmp_path, "theirs", (1, 2, 3))
    rep = tmp_path / "hero.png"
    PIL.new("RGB", (40, 20), (200, 10, 10)).save(rep)
    PIL.new("RGB", (8, 8), (0, 200, 0)).save(os.path.join(a, "images", ADDED))
    data = staged_changes.load(a)
    data.update(image={"images/" + PIC: str(rep)}, image_keep_size=["images/" + PIC])
    staged_changes.save(a, data)
    cp.set_asset_slot(a, "images", "images/" + PIC, True)
    cp.store_own_profile(a, "images", "images/" + PIC, RED)
    cp.set_asset_slot(a, "images", ADDED, True)
    cp.store(a, cp.Profile(name="Overlay", saturation=1.2))
    scene_edit.add(a, CARD, {"op": "move", "node": 1, "dx": 5, "dy": 0})
    scene_edit.add(a, CARD, {"op": "add_picture", "parent": None, "index": 0, "id": 2130706433,
                             "name": "mine", "image": ADDED, "w": 8, "h": 8, "x": 0, "y": 0})
    out = str(tmp_path / "share.zip")
    assert scene_share.export_all(a, out, [CARD], _trees()) == (1, 1, 0)
    with zipfile.ZipFile(out) as z:
        doc = json.loads(z.read(scene_edit.SHARE_MANIFEST))
    assert doc["scenes"][CARD] and doc["pictures"]["images/" + PIC]["profile"]["name"] == "Custom red"
    assert doc["pictures"]["images/" + PIC]["keep"] is True
    assert doc["added"][ADDED]["color"] is True
    assert doc["overlay"]["name"] == "Overlay"
    # a file of edits alone still reads as one (an older PAD loads the edits part)
    assert list(scene_edit.read_share(out)) == [CARD]

    # the other person's project: a picture of their own already picked there
    b = _proj(tmp_path, "mine", (1, 2, 3))
    own = tmp_path / "my_hero.png"
    PIL.new("RGB", (40, 20), (5, 5, 200)).save(own)
    data = staged_changes.load(b)
    data["image"] = {"images/" + PIC: str(own)}
    staged_changes.save(b, data)
    extras = scene_share.read_extras(out)
    assert scene_share.clashes(b, extras) == {"pictures": ["images/" + PIC], "overlay": True}
    renamed = {}
    scene_edit.import_edits(b, out, [CARD], renamed=renamed)
    pics, gone = scene_share.import_extras(b, out, extras, renamed=renamed)
    assert pics == ["images/" + PIC] and gone == []
    data = staged_changes.load(b)
    copy = data["image"]["images/" + PIC]
    assert os.path.dirname(copy) == os.path.join(b, scene_share.SHARED_DIR, "share")
    assert open(copy, "rb").read() == rep.read_bytes()
    assert own.exists() and PIL.open(own).getpixel((0, 0)) == (5, 5, 200)   # not touched
    assert data["image_keep_size"] == ["images/" + PIC]
    assert cp.own_profile(b, "images", "images/" + PIC).name == "Custom red"
    assert cp.asset_applies(cp.asset_settings(b), "images", "images/" + PIC)
    added_here = renamed.get(ADDED, ADDED)
    assert cp.asset_applies(cp.asset_settings(b), "images", added_here)
    assert cp.for_project(b).name == "Overlay"
    # loading it twice reuses the same copy instead of piling up files
    scene_share.import_extras(b, out, scene_share.read_extras(out))
    assert os.listdir(os.path.dirname(copy)) == [os.path.basename(copy)]
    # a different file of the same name is never overwritten
    with open(copy, "wb") as f:
        f.write(b"edited here")
    scene_share.import_extras(b, out, scene_share.read_extras(out))
    assert open(copy, "rb").read() == b"edited here"
    assert len(os.listdir(os.path.dirname(copy))) == 2


def test_a_picture_the_project_lacks_is_left_out(tmp_path):
    from pinball_decryptor.plugins.stern import scene_share
    a = _proj(tmp_path, "theirs", (1, 2, 3))
    rep = tmp_path / "hero.png"
    PIL.new("RGB", (40, 20), (200, 10, 10)).save(rep)
    staged_changes.save(a, {"image": {"images/" + PIC: str(rep)}})
    out = str(tmp_path / "s.zip")
    assert scene_share.export_all(a, out, None, _trees()) == (0, 1, 0)
    b = tmp_path / "empty"
    (b / "images").mkdir(parents=True)
    extras = scene_share.read_extras(out)
    assert scene_share.clashes(str(b), extras) == {"pictures": [], "overlay": False}
    assert scene_share.import_extras(str(b), out, extras) == ([], ["images/" + PIC])
    assert "images/" + PIC not in (staged_changes.load(str(b)).get("image") or {})


def test_nothing_to_save_says_so(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit, scene_share
    a = _proj(tmp_path, "theirs", (1, 2, 3))
    with pytest.raises(scene_edit.SceneEditError):
        scene_share.export_all(a, str(tmp_path / "x.zip"), None, _trees())


# -- PAD-385: a save loads into a project extracted from another card ----------------------
# A scene picture's name ends in a hash of its bytes on the card it was extracted from: the
# same portrait is radimg_530x726_10a34f06 in a project extracted from a card built with it
# and radimg_530x726_90dbdeb2 in one extracted from the stock card.

LE = "/game_le/assets/lcd/auto_loaded/0123456789abcdef/scene.radium"
PRO = "/game_pro/assets/lcd/auto_loaded/0123456789abcdef/scene.radium"
BUILT = "scene_textures/radimg_530x726_10a34f06.png"      # theirs: off a card built with it
STOCK = "scene_textures/radimg_530x726_90dbdeb2.png"      # here: off the stock card


def _tree(pic, other="scene_textures/radimg_62x90_1c1433fb.png"):
    return {"objects": {"1": {"kind": "Bitmap", "image": pic},
                        "5": {"kind": "Bitmap", "image": other},
                        "7": {"kind": "Sprite"}}}


def _pic_proj(root, name, *pics):
    d = root / name
    for pic in pics:
        p = d / "images" / pic
        p.parent.mkdir(parents=True, exist_ok=True)
        PIL.new("RGB", (8, 8), (1, 2, 3)).save(p)
    return str(d)


def test_a_save_says_which_nodes_draw_each_picture(tmp_path):
    from pinball_decryptor.plugins.stern import scene_share
    a = _pic_proj(tmp_path, "theirs", BUILT)
    rep = tmp_path / "Ghidora.png"
    PIL.new("RGB", (8, 8), (200, 10, 10)).save(rep)
    staged_changes.save(a, {"image": {"images/" + BUILT: str(rep)}})
    out = str(tmp_path / "s.zip")
    trees = {LE: _tree(BUILT), PRO: {"objects": {
        "3": {"kind": "Shape", "fill": 9}, "9": {"kind": "Bitmap", "image": BUILT},
        "4": {"kind": "StreamingFlipbook", "seq": [{"image": "x.png"}, {"image": BUILT}]}}}}
    assert scene_share.export_all(a, out, None, trees) == (0, 1, 0)
    with zipfile.ZipFile(out) as z:
        doc = json.loads(z.read("pad_scene_edits.json"))
    assert doc["pictures"]["images/" + BUILT]["drawn"] == [[LE, "1"], [PRO, "9"], [PRO, "4", 1]]
    # a scene saved alone names only its own nodes
    scene_share.export_all(a, out, [LE], trees)
    with zipfile.ZipFile(out) as z:
        doc = json.loads(z.read("pad_scene_edits.json"))
    assert doc["pictures"]["images/" + BUILT]["drawn"] == [[LE, "1"]]


def test_a_save_loads_its_pictures_into_a_stock_project(tmp_path):
    from pinball_decryptor.plugins.stern import scene_edit, scene_share
    a = _pic_proj(tmp_path, "theirs", BUILT)
    rep = tmp_path / "Ghidora.png"
    PIL.new("RGB", (8, 8), (200, 10, 10)).save(rep)
    staged_changes.save(a, {"image": {"images/" + BUILT: str(rep)},
                            "image_keep_size": ["images/" + BUILT]})
    scene_edit.add(a, LE, {"op": "move", "node": 1, "dx": 5, "dy": 0})
    out = str(tmp_path / "s.zip")
    assert scene_share.export_all(a, out, None, {LE: _tree(BUILT)}) == (1, 1, 0)

    # the stock project of the Pro: the same scene, its portrait under the stock card's name
    b = _pic_proj(tmp_path, "stock", STOCK)
    here = {PRO: _tree(STOCK)}
    extras = scene_share.read_extras(out)
    assert list(scene_share.localise(b, extras, None)["pictures"]) == ["images/" + BUILT]
    extras = scene_share.localise(b, extras, here)
    assert list(extras["pictures"]) == ["images/" + STOCK]
    assert scene_share.clashes(b, extras) == {"pictures": [], "overlay": False}
    got, _missing = scene_edit.import_edits(b, out, here.keys())
    assert list(got) == [PRO]
    assert scene_share.import_extras(b, out, extras) == (["images/" + STOCK], [])
    data = staged_changes.load(b)
    copy = data["image"]["images/" + STOCK]
    assert open(copy, "rb").read() == rep.read_bytes()
    assert data["image_keep_size"] == ["images/" + STOCK]
    assert not os.path.exists(os.path.join(b, "images", *BUILT.split("/")))

    # a file saved before PAD-385 says no nodes: its picture is left out, as it was
    old = dict(scene_share.read_extras(out))
    old["pictures"] = {r: {k: v for k, v in p.items() if k != "drawn"}
                       for r, p in old["pictures"].items()}
    assert list(scene_share.localise(b, old, here)["pictures"]) == ["images/" + BUILT]


def test_localise_takes_only_what_the_nodes_name_alone(tmp_path):
    from pinball_decryptor.plugins.stern import scene_share
    other = "scene_textures/radimg_530x726_3621969f.png"
    b = _pic_proj(tmp_path, "stock", STOCK, other, "scene_textures/flip_0.png")
    trees = {LE: {"objects": {"1": {"kind": "Bitmap", "image": STOCK},
                              "2": {"kind": "Bitmap", "image": other},
                              "4": {"kind": "StreamingFlipbook",
                                    "seq": [{"image": "scene_textures/flip_0.png"}]}}}}

    def pics(**kw):
        ex = {"pictures": {"images/" + r: {"file": "replaced/%d/x.png" % i, "drawn": d}
                           for i, (r, d) in enumerate(kw.items())},
              "added": {}, "overlay": None}
        return sorted(scene_share.localise(b, ex, trees)["pictures"])

    # one picture of a card built with it, drawn by two nodes that draw two pictures here
    assert pics(**{"scene_textures/mine.png": [[LE, "1"], [LE, "2"]]}) == [
        "images/" + other, "images/" + STOCK]
    # a flipbook's frame
    assert pics(**{"scene_textures/f.png": [[LE, "4", 0]]}) == ["images/scene_textures/flip_0.png"]
    # two of the file's pictures leading to one here: neither takes it
    assert pics(**{"scene_textures/m1.png": [[LE, "1"]], "scene_textures/m2.png": [[LE, "1"]]}) == [
        "images/scene_textures/m1.png", "images/scene_textures/m2.png"]
    # a node or a scene this card does not have, a frame out of range, junk
    assert pics(**{"scene_textures/m.png": [[LE, "99"], ["/x/scene.radium", "1"], [LE, "4", 5],
                                            "junk", [LE]]}) == ["images/scene_textures/m.png"]


# -- PAD-387: the whole look in one file - the Text tab's edits and every replaced picture -----
GAME_LE, GAME_PRO = "/game_le/game", "/game_pro/game"
LOGO = "images/boot_screen/SternLogo.png"


def _text_tree(words, other="TOKYO"):
    tree = _tree(BUILT)
    tree["objects"]["9"] = {"kind": "Text", "text": words}
    tree["objects"]["11"] = {"kind": "Text", "text": other}
    return tree


def test_a_whole_project_save_carries_its_text_and_every_picture(tmp_path):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_share
    a = _pic_proj(tmp_path, "theirs", BUILT, LOGO.split("/", 1)[1])
    rep, logo = tmp_path / "Ghidora.png", tmp_path / "logo.png"
    PIL.new("RGB", (8, 8), (200, 10, 10)).save(rep)
    PIL.new("RGB", (8, 8), (10, 10, 200)).save(logo)
    staged_changes.save(a, {"image": {"images/" + BUILT: str(rep), LOGO: str(logo)}})
    text_manifest.save(a, [
        {"path": LE, "original": "EBIRAH", "replacement": "BATTRA"},
        {"path": LE, "original": "TOKYO", "replacement": ""},
        {"path": GAME_LE, "original": "MEGALON", "replacement": "SPACE G", "budget": 12},
        {"path": "/game_le/assets/lcd/x/scene.radium", "original": "GO", "replacement": "GO!"}])
    trees = {LE: _text_tree("EBIRAH")}
    out = str(tmp_path / "all.zip")
    assert scene_share.export_all(a, out, None, trees) == (0, 2, 3)
    with zipfile.ZipFile(out) as z:
        doc = json.loads(z.read("pad_scene_edits.json"))
    assert doc["text"] == [
        {"path": LE, "original": "EBIRAH", "new": "BATTRA", "nodes": ["9"],
         "near": [None, "TOKYO"]},
        {"path": GAME_LE, "original": "MEGALON", "new": "SPACE G", "near": [None, None]},
        {"path": "/game_le/assets/lcd/x/scene.radium", "original": "GO", "new": "GO!",
         "near": [None, None]}]
    # the boot screen no scene draws comes too, with no nodes to name
    assert sorted(doc["pictures"]) == [LOGO, "images/" + BUILT]
    assert "drawn" not in doc["pictures"][LOGO]
    # one scene saved alone: its own words and pictures only
    assert scene_share.export_all(a, out, [LE], trees) == (0, 1, 1)
    # text alone is something to save
    staged_changes.save(a, {})
    assert scene_share.export_all(a, out, None, trees) == (0, 0, 3)
    # and an older reader of the file still finds its scenes (none here) and nothing else
    assert scene_share.read_extras(out)["text"][0]["nodes"] == ["9"]


def test_text_lands_on_this_cards_lines(tmp_path):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_share
    b = str(tmp_path / "stock")
    text_manifest.save(b, [
        {"path": PRO, "original": "EBIRAH", "replacement": ""},
        {"path": PRO, "original": "TOKYO", "replacement": ""},
        {"path": PRO, "original": "GO", "replacement": ""},
        {"path": PRO, "original": "GO", "replacement": ""},
        {"path": GAME_PRO, "original": "MEGALON", "replacement": "MINE", "budget": 12}])
    trees = {PRO: _text_tree("EBIRAH")}
    saved = [
        # built with other words on the card it was saved from: found by its Text node
        {"path": LE, "original": "BIOLLANTE", "new": "BATTRA", "nodes": ["9"]},
        {"path": LE, "original": "TOKYO", "new": "OSAKA", "nodes": ["11"]},
        {"path": LE, "original": "GO", "new": "GO!", "nodes": []},       # n-th copy, n-th edit
        {"path": LE, "original": "GO", "new": "GO!!", "nodes": []},
        {"path": GAME_LE, "original": "MEGALON", "new": "SPACE G", "nodes": []},
        {"path": LE, "original": "NOT HERE", "new": "X", "nodes": ["99"]},
        {"path": "/other/scene.radium", "original": "EBIRAH", "new": "X", "nodes": ["9"]}]
    rows = text_manifest.load(b)
    pairs, missing = scene_share.match_text(saved, rows, trees)
    assert [(r["original"], new) for r, new in pairs] == [
        ("EBIRAH", "BATTRA"), ("TOKYO", "OSAKA"), ("GO", "GO!"), ("GO", "GO!!"),
        ("MEGALON", "SPACE G")]
    assert [e["original"] for e in missing] == ["NOT HERE", "EBIRAH"]
    scene_share.import_text(b, rows, pairs)
    assert text_manifest.changed(b) == {
        PRO: [("EBIRAH", "BATTRA"), ("TOKYO", "OSAKA"), ("GO", "GO!"), ("GO", "GO!!")],
        GAME_PRO: [("MEGALON", "SPACE G")]}
    # a budget row keeps its budget
    assert [r.get("budget") for r in text_manifest.load(b) if r["path"] == GAME_PRO] == [12]


def test_a_program_line_built_with_other_words_is_found_between_its_neighbours(tmp_path):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_share
    b = str(tmp_path / "stock")
    text_manifest.save(b, [{"path": GAME_PRO, "original": w, "replacement": "", "budget": 96}
                           for w in ("BATTLE", "GODZILLA VS. EBIRAH", "CHAMPION", "X", "Y",
                                     "GO", "X", "Y", "GO")])
    rows = text_manifest.load(b)

    def match(original, near):
        pairs, _missing = scene_share.match_text(
            [{"path": GAME_LE, "original": original, "new": "NEW", "nodes": [],
              "near": near}], rows, {})
        return [r["original"] for r, _new in pairs]
    # the card it was saved from had other words there: the one row between the same two
    assert match("GODZILLA VS. BATTRA", ["BATTLE", "CHAMPION"]) == ["GODZILLA VS. EBIRAH"]
    # two rows (both Y) between the same neighbours, neighbours not here, none known: no guess
    assert match("Q", ["X", "GO"]) == []
    assert match("Q", ["NOPE", "CHAMPION"]) == []
    assert match("Q", [None, None]) == []
    # an old file (no near) and its own words still win first
    assert match("CHAMPION", None) == ["CHAMPION"]


def test_scenes_page_loads_text_through_the_text_tab(tmp_path):
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import scene_share
    from tests.test_gui_scene_editor import CARD as SCARD, _open, _seed, _wait
    from tests.webui_harness import web_app
    mine, friend = tmp_path / "mine", tmp_path / "friend"
    _seed(mine)
    _seed(friend)
    text_manifest.save(str(mine), [
        {"path": SCARD, "original": "KAIJU", "replacement": "MONSTER"},
        {"path": "/g/game", "original": "PLAY", "replacement": "GO!", "budget": 8}])
    text_manifest.save(str(friend), [
        {"path": SCARD, "original": "KAIJU", "replacement": "BEAST"},
        {"path": "/g/game", "original": "PLAY", "replacement": "", "budget": 8}])
    zip_path = str(tmp_path / "look.zip")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, mine)
        w.answers.append(zip_path)
        assert w.call("text_scenes.edits_save", "all", True) == zip_path
        assert len(scene_share.read_extras(zip_path)["text"]) == 2
        _open(w, friend)
        w.answers.extend([zip_path, "no"])          # "... 1 line of text you changed" No
        assert w.call("text_scenes.edits_load") is None
        assert "1 line of text you changed" in str(w.asked[-1])
        assert text_manifest.changed(str(friend)) == {SCARD: [("KAIJU", "BEAST")]}
        w.answers.extend([zip_path, "yes"])
        w.call("text_scenes.edits_load")
        assert _wait(w, lambda: text_manifest.changed(str(friend)) == {
            SCARD: [("KAIJU", "MONSTER")], "/g/game": [("PLAY", "GO!")]})
        assert "2 text edits" in w.state("text_scenes").get("caption", ""), w.state(
            "text_scenes").get("caption")


def test_the_menu_offers_it_and_the_builds_ship_the_module():
    ts = _src("js", "tabs", "text_scenes.js")
    assert 'call("text_scenes.edits_save", "this", true)' in ts
    assert 'call("text_scenes.edits_save", "all", true)' in ts
    root = os.path.join(os.path.dirname(__file__), os.pardir, "installer")
    for name in ("build_linux.sh", "build_macos.sh"):
        assert "pinball_decryptor.plugins.stern.scene_share" in open(
            os.path.join(root, name), encoding="utf-8").read(), name
