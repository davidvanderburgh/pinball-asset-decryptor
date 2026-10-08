"""PAD-463 (DragonRR): the Video tab's color work on the Images tab.

1. The panes draw through the color profiles: Preview colors (overlay / individual files /
   machine screen) and, on each pane, Original / With its color profile.  A change in the
   Colors bar turns the picture's pane to its profile.
2. Compare: up to 4 pictures side by side, each drawn through its own colors.
3. Several pictures selected are one target for the bar: a change gives them all the
   profile, attached, one Undo step; "Same as the other files" drops it from all.
4. The Which files card's "Every replaced picture / video" boxes are "All images" / "All
   videos": every one not locked gets the individual files profile, attached, after an
   "Are you sure?", one Undo step."""

import base64
import io
import os

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from tests.test_webui_images import (_project, _set_folder, _wait, _settled, _by_rel,
                                     BANNER, SPRITE, ATLAS, PLAIN, BOOT)
from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

RED = {"name": "Custom red", "gain": [1.0, 0.9, 0.9]}
_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(_TABS, name), encoding="utf-8") as f:
        return f.read()


def _mine(tmp_path, name, colour):
    d = tmp_path / "mine"
    d.mkdir(exist_ok=True)
    p = d / name
    Image.new("RGBA", (40, 20), colour + (255,)).save(p)
    return str(p)


def _open(w, tmp_path, picks):
    """The project scanned, *picks* ({rel: colour}) chosen as white / grey pictures."""
    for i, (rel, colour) in enumerate(picks.items()):
        w.answers = [_mine(tmp_path, "mine%d.png" % i, colour)]
        assert w.call("images.choose", rel) == rel
        w.drain()


def _cols(w):
    w.drain()
    return {r: row["c"] for r, row in _by_rel(w.state("images")).items()}


def _on(w, rel, more=()):
    """The bar on *rel* (and the pictures selected with it), as images.js sends it."""
    assert w.call("color.panel_open")
    assert w.call("color.set_file", "images", rel, os.path.basename(rel),
                  bool(_cols(w).get(rel)), {"ns": "images"}, list(more))
    w.drain()


def _through(assets, rel, rgb):
    """*rgb* through *rel*'s own profile, the picture maths."""
    import numpy as np
    prof = cp.own_profile(assets, "images", rel)
    return tuple(int(v) for v in prof.apply_array(np.array([[rgb]], np.uint8))[0, 0])


def _pixel(w, path, key=None):
    url = w.call("images.thumb", path, 64, 64, key)
    assert url.startswith("data:image/png;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as im:
        return im.convert("RGB").getpixel((im.width // 2, im.height // 2))


@pytest.fixture
def scanned(tmp_path):
    assets, _reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        yield w, assets


def test_the_panes_draw_through_the_pictures_profile(scanned, tmp_path):
    w, assets = scanned
    _open(w, tmp_path, {BANNER: (255, 255, 255)})
    assert w.call("images.select", BANNER)
    # only the individual files step, so the colours are the profile's alone
    assert w.call("images.set_look_part", "overlay", False)
    assert w.call("images.set_look_part", "screen", False)
    _on(w, BANNER)
    w.call("color.set_params", RED)
    w.drain()
    assert _cols(w)[BANNER] is True
    look = w.state("images")["look"]
    assert look["offered"] and look["sw"] == {"overlay": False, "files": True, "screen": False}
    assert look["parts"]["files"]["set"]
    # the replacement's pane opens on its profile, the original's as it is
    assert look["views"]["rep"]["view"] == "profile" and look["views"]["rep"]["on"] is True
    assert look["views"]["rep"]["name"] == "Custom red"
    assert look["views"]["orig"]["view"] == "plain"
    assert look["keys"]["orig"] is None and look["keys"]["rep"]
    rep = w.state("images")["preview"]["rep"]
    assert _pixel(w, rep) == (255, 255, 255)
    want = _through(assets, BANNER, (255, 255, 255))
    assert want != (255, 255, 255)
    assert _pixel(w, rep, look["keys"]["rep"]) == want
    # Original on its pane: as made
    assert w.call("images.set_pane_view", "rep", "plain")
    w.drain()
    look = w.state("images")["look"]
    assert look["views"]["rep"]["view"] == "plain" and look["keys"]["rep"] is None
    # a change in the bar turns it back to its profile
    w.call("color.set_params", {"gain": [1.0, 0.8, 0.8]})
    w.drain()
    look = w.state("images")["look"]
    assert look["views"]["rep"]["view"] == "profile"
    now = _through(assets, BANNER, (255, 255, 255))
    assert now != want and _pixel(w, rep, look["keys"]["rep"]) == now
    # the Original drawn through it too, nothing attached by that
    assert w.call("images.set_pane_view", "orig", "profile")
    w.drain()
    assert w.state("images")["look"]["keys"]["orig"]
    # Individual files off under Preview colors: drawn without it
    assert w.call("images.set_look_part", "files", False)
    w.drain()
    look = w.state("images")["look"]
    assert look["keys"] == {"orig": None, "rep": None}
    # the switches are remembered, as the Video tab's are
    saved = w.run(lambda: w.window.cb.get("initial_look_switches"))
    assert saved["images"] == {"overlay": False, "files": False, "screen": False}
    # a locked game picture has no Original / With its color profile
    assert w.call("images.select", ATLAS)
    w.drain()
    assert w.state("images")["look"]["views"] == {"orig": None, "rep": None}


def test_compare_up_to_four_pictures(scanned, tmp_path):
    w, assets = scanned
    _open(w, tmp_path, {BANNER: (255, 255, 255), SPRITE: (128, 128, 128),
                        PLAIN: (255, 255, 255)})
    assert w.call("images.set_look_part", "overlay", False)
    assert w.call("images.set_look_part", "screen", False)
    _on(w, BANNER)
    w.call("color.set_params", RED)
    w.drain()
    # five asked for: the first four, each its Replacement where it has one
    assert w.call("images.compare_open", [BANNER, SPRITE, PLAIN, ATLAS, BOOT]) == 4
    w.drain()
    cmp = w.state("images")["compare"]
    assert cmp["open"] and cmp["max"] == 4
    tiles = cmp["tiles"]
    assert [(t["rel"], t["side"]) for t in tiles] == [
        (BANNER, "rep"), (SPRITE, "rep"), (PLAIN, "rep"), (ATLAS, "orig")]
    assert tiles[0]["sides"] == [["orig", "Original"], ["rep", "Replacement"]]
    assert tiles[3]["sides"] == [["orig", "Original"]]
    assert tiles[0]["pane"]["label"] == "mine0.png"
    # each drawn through its own colors: only the one with a profile attached changes
    assert tiles[0]["key"] and not tiles[1]["key"] and not tiles[3]["key"]
    assert _pixel(w, tiles[0]["pane"]["path"], tiles[0]["key"]) == _through(
        assets, BANNER, (255, 255, 255))
    # a palette clicked in Compare attaches it there too
    assert w.call("images.set_color", PLAIN, True)
    w.drain()
    tiles = w.state("images")["compare"]["tiles"]
    assert tiles[2]["key"]
    # the other side, a picture out, Close
    assert w.call("images.compare_side", tiles[0]["id"], "orig")
    w.drain()
    tiles = w.state("images")["compare"]["tiles"]
    assert tiles[0]["pane"]["title"] == "Original"
    assert tiles[0]["pane"]["path"].replace("\\", "/").endswith(BANNER)
    assert w.call("images.compare_remove", tiles[3]["id"])
    assert len(w.state("images")["compare"]["tiles"]) == 3
    assert w.call("images.compare_close")
    assert w.state("images")["compare"] == {"open": False, "max": 4, "tiles": []}
    # one picture: its Original beside its Replacement
    assert w.call("images.compare_open", [BANNER]) == 2
    tiles = w.state("images")["compare"]["tiles"]
    assert [t["pane"]["title"] for t in tiles] == ["Original", "Replacement"]
    assert w.call("images.compare_close")
    # a game's own picture unlocked and attached: its original through its profile
    assert w.call("images.set_color_unlocked", True)
    assert w.call("images.set_color", ATLAS, True)
    assert w.call("images.compare_open", [ATLAS]) == 2
    tiles = w.state("images")["compare"]["tiles"]
    assert [t["pane"]["title"] for t in tiles] == ["Original", "With its color profile"]
    assert tiles[0]["pane"]["path"] == tiles[1]["pane"]["path"]
    assert tiles[1]["key"] and not tiles[0]["key"]
    # its replacement cleared: a slot still listed stays, as its Original
    assert w.call("images.compare_close")
    assert w.call("images.compare_open", [SPRITE]) == 2
    w.answers = ["yes"]
    w.call("images.clear_one", SPRITE)
    w.drain()
    tiles = w.state("images")["compare"]["tiles"]
    assert [t["side"] for t in tiles] == ["orig", "orig"]


def test_several_selected_pictures_get_the_profile_attached(scanned, tmp_path):
    w, assets = scanned
    _open(w, tmp_path, {BANNER: (255, 255, 255), SPRITE: (128, 128, 128),
                        PLAIN: (255, 255, 255)})
    assert w.call("images.set_color", BANNER, True)
    cp.store_own_profile(assets, "images", SPRITE, cp.Profile(name="Old", gain=(1, 1.2, 1)))
    assert {r: _cols(w)[r] for r in (BANNER, SPRITE, PLAIN)} == {
        BANNER: True, SPRITE: False, PLAIN: False}
    _on(w, BANNER, more=[SPRITE, PLAIN])
    f = w.state("color")["file"]
    assert f["rel"] == BANNER and f["count"] == 3 and f["own_n"] == 1
    w.call("color.set_params", RED)
    w.drain()
    assert cp.own_profile_names(assets)["images"] == {r: "Custom red" for r in (BANNER, SPRITE, PLAIN)}
    assert {r: _cols(w)[r] for r in (BANNER, SPRITE, PLAIN)} == dict.fromkeys((BANNER, SPRITE, PLAIN), True)
    # one Undo: profiles and switches as they were
    assert w.call("color.undo")
    w.drain()
    assert cp.own_profile_names(assets)["images"] == {SPRITE: "Old"}
    assert {r: _cols(w)[r] for r in (BANNER, SPRITE, PLAIN)} == {
        BANNER: True, SPRITE: False, PLAIN: False}
    assert w.call("color.undo", True)
    w.drain()
    # Same as the other files: all of them drop their own
    assert w.call("color.file_shared")
    assert cp.own_profile_names(assets)["images"] == {}


def test_all_images_from_the_which_files_card(scanned, tmp_path):
    w, assets = scanned
    _open(w, tmp_path, {BANNER: (255, 255, 255), SPRITE: (128, 128, 128)})
    cp.store_own_profile(assets, "images", BANNER, cp.Profile(name="Old", gain=(1, 1.2, 1)))
    assert w.call("images.set_color", BANNER, True)
    assert w.call("images.set_color_unlocked", True)
    svc = w.window.service("images")
    every = w.run(lambda: svc.color_targets("all"))
    assert set(every) == {BANNER, SPRITE, ATLAS, PLAIN, BOOT, *[r for r in every if "glyph" in r]}
    assert w.call("color.panel_open")
    assert w.call("color.set_mode", "assets") == "assets"
    # with a file on show it is that file's line, not this card's
    _on(w, BANNER)
    n = len(w.asked)
    assert w.call("color.apply_to_all", "all", "images") is False
    assert len(w.asked) == n
    assert w.call("color.set_file") is False
    # asked first: No changes nothing
    w.answers = ["no"]
    assert w.call("color.apply_to_all", "all", "images") is False
    q = w.asked[-1]
    assert q["title"] == "All images"
    assert "Every image that is not locked" in q["message"]
    assert "all %d of them" % len(every) in q["message"]
    assert "One of them loses a color profile of its own." in q["message"]
    assert "attached to the %d that have none attached" % (len(every) - 1) in q["message"]
    assert "Undo puts them all back." in q["message"]
    assert cp.own_profile_names(assets)["images"] == {BANNER: "Old"}
    w.answers = ["yes"]
    assert w.call("color.apply_to_all", "all", "images") is True
    w.drain()
    assert cp.own_profile_names(assets)["images"] == {}
    assert w.run(lambda: svc.color_targets("profiled")) == dict.fromkeys(every, True)
    log = [l["text"] for l in w.run(w.window.log_history)]
    assert any("given to all %d images (attached to %d)" % (len(every), len(every) - 1) in t
               for t in log)
    # one Undo on the individual files profile puts it all back
    assert w.state("color")["can_undo"]
    assert w.call("color.undo")
    w.drain()
    assert cp.own_profile_names(assets)["images"] == {BANNER: "Old"}
    assert w.run(lambda: svc.color_targets("profiled")) == {BANNER: True}
    assert w.call("color.undo", True)
    w.drain()
    assert w.run(lambda: svc.color_targets("profiled")) == dict.fromkeys(every, True)
    # nothing left to change: nothing asked
    n = len(w.asked)
    assert w.call("color.apply_to_all", "all", "images") is False
    assert len(w.asked) == n


def test_all_videos_from_the_which_files_card(tmp_path):
    from tests.test_webui_video import _project as _videos, _scan, _mine as _clip
    proj = _videos(tmp_path)
    d = str(proj)
    a, b, c = "video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4"
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        for i, rel in enumerate((a, b)):
            w.answers.append(str(_clip(tmp_path, "mine%d.mp4" % i)))
            assert w.call("video.choose", rel) is True
        cp.store_own_profile(d, "videos", a, cp.Profile(name="Old", gain=(1, 1.2, 1)))
        assert w.call("color.panel_open")
        assert w.call("color.set_mode", "assets") == "assets"
        w.answers = ["yes"]
        assert w.call("color.apply_to_all", "all", "videos") is True
        q = w.asked[-1]
        assert q["title"] == "All videos"
        assert "Every video that is not locked" in q["message"] and "all 2 of them" in q["message"]
        w.drain()
        assert {r["rel"]: r["col"] for r in w.state("video")["rows"]} == {a: True, b: True, c: None}
        assert cp.own_profile_names(d)["videos"] == {}
        assert staged_changes.load(d)["video_color_slots"] == {a: True, b: True}
        assert w.call("color.undo")
        w.drain()
        assert cp.own_profile_names(d)["videos"] == {a: "Old"}
        assert {r["rel"]: r["col"] for r in w.state("video")["rows"]} == {a: False, b: False, c: None}


def test_the_page_wires_it():
    images = _src("images.js")
    # several selected: the others go to the bar with the one on show
    assert "more: selOpen.filter((r) => r.r !== one.rel).map((r) => r.r)" in images
    assert 'call("images.thumb", path, Math.round((box.w - 8) * dpr), Math.round((box.h - 8) * dpr), look || null)' in images
    assert '<${LookRow} look=${look} ns="images"' in images
    assert 'call("images.set_pane_view", side, v)' in images
    assert 'call("images.compare_open", rels)' in images
    assert 'cls="img-cmp-open"' in images
    # the bar's "Show it in this preview" on the Images tab
    pane = _src("color_pane.js")
    assert 'images: { lookNs: "images"' in pane
    # Which files: two buttons where the two boxes were, and a way off for an old box
    color = _src("color.js")
    assert 'call("color.apply_to_all", "all", k)' in color
    assert '"All images…"' in color and '"All videos…"' in color
    assert 'label="Every replaced picture"' not in color
    assert 'label="Every replaced video"' not in color
    assert 'call("color.set_all", k, false)' in color
    for name in ("images.js", "video.js", "text_scenes.js"):
        assert "Follows the Color profile tab's box" not in _src(name)
        assert "Every replaced video box sets the rest" not in _src(name)
