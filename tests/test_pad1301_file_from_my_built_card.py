"""PAD-1301 (DragonRR and DoomWalrus666): a file of scene edits saved from a project of the
card B's own edits were Written to, loaded back on B.

A Write puts each picture B added in Scenes on the card as a node of the game's own, numbered
after the scene's last (Kaiju Battle Select: 1247, 1250, ... 1268).  On B those nodes are
still the adds' (``FIRST_ADDED_ID`` and up), so "made on top of my edits" (PAD-552) never
matched: the file's edits replaced B's 190 and moved the stock scene's nodes, the monster card
filling the screen.  And a picture of the file standing for one B added (the title logo) was
picked on the Images tab, which has no slot for an added picture: "its slot isn't in this
folder", and the logo stayed B's own.
"""
import io
import json
import zipfile

from PIL import Image

from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import scene_edit as X, scene_eval as E, scene_share as S
from pinball_decryptor.plugins.stern import scene_tree as T
from tests.test_stern_scene_tree import scene

A = X.FIRST_ADDED_ID
CARD = "/godzilla_pro/assets/lcd/auto_loaded/abc/scene.radium"


def _project(tmp_path):
    added = tmp_path / "images" / "scene_textures" / "added"
    added.mkdir(parents=True)
    for i, c in enumerate([(200, 40, 40), (40, 200, 40)]):
        Image.new("RGBA", (30, 8), c + (255,)).save(str(added / ("Logo%d_1.png" % i)))
    return str(tmp_path)


def _mine():
    return [{"op": "move", "node": 50, "dx": 12.0, "dy": -3.0},
            {"op": "add_picture", "parent": None, "index": 1 << 20, "id": A + 1,
             "name": "PAD_Logo0", "image": "scene_textures/added/Logo0_1.png", "w": 30, "h": 8,
             "x": 10, "y": 20},
            {"op": "move", "node": 53, "dx": 30.0, "dy": 0.0},
            {"op": "add_picture", "parent": None, "index": 1 << 20, "id": A + 3,
             "name": "PAD_Logo1", "image": "scene_textures/added/Logo1_1.png", "w": 30, "h": 8,
             "x": -10, "y": 50}]


def _written(proj, ops):
    """The scene as a project extracted from the card a Write of *ops* made reads it."""
    sc = T.parse(scene())
    applied, notes = X.apply_scene(sc, ops, assets_dir=proj)
    assert notes == [] and applied == len(ops)
    return E.manifest(T.parse(T.serialize(sc)))


def _card_ids(man):
    out = []

    def walk(kids):
        for n in kids:
            if (n.get("name") or "").startswith("PAD_"):
                out.append(int(n["id"]))
            walk(n.get("kids") or ())
    walk(man["root"]["kids"])
    return sorted(out)


def _theirs(ids):
    return [{"op": "move", "node": ids[0], "dx": 5.0, "dy": -6.0},
            {"op": "scale", "node": ids[0], "px": 0, "py": 0, "s": 0.55},
            {"op": "move", "node": 53, "dx": 20.0, "dy": 10.0},
            {"op": "visible", "node": ids[1], "on": False},
            {"op": "move", "node": 50, "dx": -40.0, "dy": 3.0}]


def test_a_write_numbers_my_adds_as_the_games_own(tmp_path):
    ids = _card_ids(_written(_project(tmp_path), _mine()))
    assert len(ids) == 2 and all(i < A for i in ids)


def test_edits_made_on_my_built_card_go_after_mine_where_they_were_made(tmp_path):
    proj = _project(tmp_path)
    stock = E.manifest(T.parse(scene()))
    card = _written(proj, _mine())
    ids = _card_ids(card)
    theirs = _theirs(ids)
    st = json.loads(json.dumps(X.states_of(card, theirs)))          # as read off the file
    rest = X.on_top_of(stock, _mine(), theirs, st)
    assert rest is not None and len(rest) == len(theirs)
    # their nodes are named as mine names them
    assert rest[0]["node"] == A + 1 and rest[3]["node"] == A + 3
    got = X._Base.of_manifest(X.apply_manifest(stock, _mine() + rest)[0])
    want = X._Base.of_manifest(X.apply_manifest(card, theirs)[0])
    for here, there in ((50, 50), (53, 53), (A + 1, ids[0]), (A + 3, ids[1])):
        assert X._close(got.fp(here), want.fp(there)), (here, there)
    # loaded again: nothing more
    assert X.on_top_of(stock, _mine() + rest, theirs, st) == []


def test_other_adds_of_mine_are_not_taken_for_theirs(tmp_path):
    proj = _project(tmp_path)
    stock = E.manifest(T.parse(scene()))
    card = _written(proj, _mine())
    theirs = _theirs(_card_ids(card))
    st = json.loads(json.dumps(X.states_of(card, theirs)))
    other = [dict(op, x=op["x"] + 99) if op["op"] == "add_picture" else op for op in _mine()]
    assert X.on_top_of(stock, other, theirs, st) is None


def test_a_file_made_on_the_stock_card_is_left_as_it_was():
    stock = E.manifest(T.parse(scene()))
    theirs = [{"op": "move", "node": 53, "dx": 3.0, "dy": 0.0}]
    st = X.states_of(stock, theirs)
    assert X._as_mine(stock, _mine(), theirs, st) == (theirs, st)


def _zip(tmp_path, blob):
    zp = tmp_path / "file.zip"
    with zipfile.ZipFile(str(zp), "w") as z:
        z.writestr("pad_scene_edits.json", json.dumps({"format": 1, "kind": "pad-scene-edits",
                                                       "scenes": {}}))
        z.writestr("pictures/The Title.png", blob)
    return str(zp)


def _png(size, colour):
    buf = io.BytesIO()
    Image.new("RGBA", size, colour).save(buf, "PNG")
    return buf.getvalue()


def _extras(rel, keep=False):
    return {"pictures": {rel: {"file": "pictures/The Title.png", "name": "The Title.png",
                               "keep": keep}},
            "added": {}, "colored": {}, "lines": {}, "overlay": None, "text": []}


def test_their_picture_for_my_added_one_is_shown_by_my_add(tmp_path):
    proj = _project(tmp_path)
    X.save(proj, {CARD: _mine()})
    rel = "images/scene_textures/added/Logo0_1.png"
    zp = _zip(tmp_path, _png((60, 16), (1, 2, 250, 255)))
    loaded, gone = S.import_extras(proj, zp, _extras(rel), cards_here=[CARD])
    assert gone == []
    # no Images tab pick on it (it has no slot there: "its slot isn't in this folder")
    assert rel not in ((staged_changes.load(proj) or {}).get("image") or {})
    op = X.load(proj)[CARD][1]
    assert op["image"] == "scene_textures/added/Logo0_2.png" and loaded == ["images/" + op["image"]]
    with Image.open(str(tmp_path / "images" / "scene_textures" / "added" / "Logo0_2.png")) as im:
        assert im.size == (30, 8) and (op["w"], op["h"]) == (30, 8)      # the add's own size
        assert im.convert("RGBA").getpixel((5, 5))[2] > 200
    # the add's own picture is left as it was; the other add is untouched
    with Image.open(str(tmp_path / "images" / "scene_textures" / "added" / "Logo0_1.png")) as im:
        assert im.convert("RGB").getpixel((0, 0)) == (200, 40, 40)
    assert X.load(proj)[CARD][3]["image"] == "scene_textures/added/Logo1_1.png"
    # loaded again: the same file is taken, no third copy
    S.import_extras(proj, zp, _extras("images/" + op["image"]), cards_here=[CARD])
    assert not (tmp_path / "images" / "scene_textures" / "added" / "Logo0_3.png").exists()


def test_kept_at_its_own_size_the_add_keeps_its_box(tmp_path):
    # my moves and resizes of the add were made over its 30x8 picture (round 2: DragonRR's
    # 4211x602 title kept its size and drew twice as wide); test_pad1301_kept_pictures_on_
    # my_layout checks it is fitted and centred there
    proj = _project(tmp_path)
    X.save(proj, {CARD: _mine()})
    zp = _zip(tmp_path, _png((60, 16), (1, 2, 250, 255)))
    S.import_extras(proj, zp, _extras("images/scene_textures/added/Logo1_1.png", keep=True),
                    cards_here=[CARD])
    op = X.load(proj)[CARD][3]
    assert (op["w"], op["h"]) == (30, 8)


def test_the_page_loads_it_after_mine_with_their_logo(tmp_path):
    """The whole round as it happened: B's edits Written; A's project extracted from that card,
    A moves things, replaces B's logo and saves with pictures; B loads the file."""
    from tests.test_gui_scene_editor import CARD as GCARD, _open, _seed
    from tests.webui_harness import web_app
    a, b = tmp_path / "a", tmp_path / "b"
    b.mkdir()
    _seed(b)
    proj_b = _project(b)
    stock = T.parse(scene())
    sc = T.parse(scene())
    X.apply_scene(sc, _mine(), assets_dir=proj_b)
    _seed(a, data=T.serialize(sc))
    # A's extract names the picture B's first add put on the card as a Write's picture
    new_tex = sorted(set(sc.textures) - set(stock.textures))[0]
    t = sc.textures[new_tex]
    radimg = "scene_textures/radimg_PAD_Logo0_%dx%d_0123abcd.png" % (t["w"], t["h"])
    tex = a / "images" / "scene_textures"
    (a / "images" / ("scene_textures/pic_%d.png" % new_tex)).rename(a / "images" / radimg)
    for name in ("scene_tree.json", "radium_images.txt"):
        p = tex / name
        p.write_text(p.read_text(encoding="utf-8").replace(
            "scene_textures/pic_%d.png" % new_tex, radimg), encoding="utf-8")
    ids = _card_ids(json.loads((tex / "scene_tree.json").read_text(encoding="utf-8"))[GCARD])
    X.save(str(a), {GCARD: _theirs(ids)})
    title = a / "The Title.png"
    Image.new("RGBA", (60, 16), (1, 2, 250, 255)).save(str(title))
    staged_changes.save(str(a), {"image": {"images/" + radimg: str(title)}})
    zp = str(tmp_path / "Battle Select with pictures.zip")
    S.export_all(str(a), zp, None, X.trees_of(str(a)))
    X.save(proj_b, {GCARD: _mine()})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, b)
        w.answers.append(zp)
        assert w.call("text_scenes.edits_load") == [GCARD]
        ops = X.ops_for(proj_b, GCARD)
        cap = w.state("text_scenes")["caption_full"]
    assert ops[:1] == _mine()[:1] and len(ops) == len(_mine()) + len(_theirs(ids)), cap
    assert "after your own edits" in cap and "start out" not in cap, cap
    assert ops[1]["image"] == "scene_textures/added/Logo0_2.png", ops[1]
    assert ops[3]["image"] == "scene_textures/added/Logo1_1.png"
    picks = (staged_changes.load(proj_b) or {}).get("image") or {}
    assert not any("/added/" in r for r in picks), picks
