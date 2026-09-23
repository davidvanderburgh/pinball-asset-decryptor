"""Run logic of the Scenes window (webui/text_scenes.py) and the Fonts window
(webui/text_fonts.py), driven through the in-process web harness.

These were Tk SceneBrowser / FontStudio tests; what they checked is still
the app's logic, so they now call the web services' rpc methods (or their
methods directly on the UI loop) and assert on the store and the files
written.  Broader wiring lives in tests/test_webui_text.py.
"""

import json
import os
import types

import pytest

from tests.webui_harness import web_app


# ---------------------------------------------------------------- helpers
def _scenes(w):
    return w.window.service("text").scenes


def _fonts(w):
    """The Fonts window service, with its 120 ms preview refresh switched
    off: that timer rewrites the status line, so a test reading the status
    after an action would race it.  Tests that want a preview call
    ``_render_now`` themselves."""
    fonts = w.window.service("text").fonts
    fonts._schedule_render = lambda: None
    return fonts


def _open_scenes(w, folder, **kw):
    assert w.run(lambda: w.window.open_scene_browser(folder, **kw)) is True
    return _scenes(w)


def _open_fonts(w, folder, preselect=None):
    fonts = _fonts(w)
    assert w.run(lambda: w.window.open_font_studio(
        folder, preselect=preselect)) is True
    return fonts


def _select_quietly(w, svc, scene_dir):
    """Select *scene_dir* and retire the render that selecting starts (its
    result carries the old token and is discarded), so the test can hand
    the window frames of its own.  Returns the store as it was right after
    the select."""
    def _do():
        svc.select(scene_dir)
        snap = dict(w.state("text_scenes"))
        svc._token += 1
        return snap
    return w.run(_do)


def _write_layout(tmp_path, layout):
    from pinball_decryptor.plugins.stern import scene_render
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)


def _alpha_max(path):
    import numpy as np
    from PIL import Image
    return int(np.asarray(Image.open(path).convert("RGBA"))[..., 3].max())


def _seed_scene_with_text(tmp_path, text="CLOCK NOT SET",
                          rgba=(1.0, 1.0, 1.0, 1.0)):
    """``_make_extract`` plus one editable string and a layout drawing it, so
    the Scenes window has a Text row with a known colour."""
    (tmp_path / "text").mkdir(exist_ok=True)
    (tmp_path / "text" / "strings.tsv").write_text(
        "# asset_path\toriginal\treplacement\n"
        "/g/scene1/scene.radium\t%s\t\n" % text, encoding="utf-8")
    _write_layout(tmp_path, {"/g/scene1/scene.radium": {
        "stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0,
        "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": text,
             "rect": [0, 0, 320, 180], "rgba": list(rgba), "align": 1,
             "font": "tbl"}]}})


def _stern_text_extract(tmp_path):
    """A synthetic Stern extract with two scenes' worth of display text."""
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.core import text_manifest
    _make_extract(tmp_path)
    text_manifest.save(str(tmp_path), [
        {"path": "/g/scene1/scene.radium", "original": "HELLO",
         "replacement": ""},
        {"path": "/g/scene2/scene.radium", "original": "BALL ONE",
         "replacement": ""}])
    return str(tmp_path)


class _SyncThread:
    """``threading.Thread`` that runs its target inline on ``start``."""

    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()


# ============================================================ Scenes window
def test_scene_browser_preview_and_videos(tmp_path):
    """The Scenes window lists a scene's videos and previews the scene itself.

    The render runs on a worker thread, so the threaded hop is exercised by
    calling the two halves directly: a sleep-until-drawn loop would put real
    wall-clock into the suite for no extra coverage."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract

    _make_extract(tmp_path)
    # a video belonging to scene1, named the way the extractor names them
    vdir = tmp_path / "video"
    vdir.mkdir()
    (vdir / "Intro_Clip.mp4").write_bytes(b"\x00" * 32)
    (vdir / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "Intro_Clip.mp4\t/g/scene1/scene.assets/3.asset/0.asset\t32\n",
        encoding="utf-8")
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 60.0], "partial": False, "unplaced": 0,
        "offstage": 0, "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": "A",
             "rect": [0, 0, 320, 180], "rgba": [1, 1, 1, 1], "align": 1,
             "font": "radimg_TestA_8x8_00000001"}]}}
    _write_layout(tmp_path, layout)
    scene = layout["/g/scene1/scene.radium"]

    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open_scenes(w, str(tmp_path))
        snap = _select_quietly(w, svc, "/g/scene1")

        # the video shows up in Contents, and its row jumps to the Video tab
        groups = {g["key"]: g for g in snap["contents"]["groups"]}
        assert [it["text"] for it in groups["vid"]["items"]] == [
            "Intro_Clip.mp4"]
        assert groups["vid"]["items"][0]["id"] == "vid::video/Intro_Clip.mp4"

        # the scene has a layout, so a render was scheduled
        assert snap["caption"] == "Drawing…"
        assert snap["can_save"] is False

        # finishing it enables Save and captions what the frame does/doesn't
        # show
        img = Image.new("RGB", (320, 180), (0, 0, 0))
        w.run(svc._show_preview, svc._token, [img], ["f0.png"], scene)
        st = w.state("text_scenes")
        assert st["can_save"] is True
        # A still picture says so, and offers NO playback controls: a Speed
        # box on something that cannot move implied there was animation
        # being withheld.
        assert "Still picture" in st["caption_full"]
        assert st["animated"] is False
        # ...and no Screen control either: this scene is a single screen
        assert st["screens"] == []
        assert svc._preview_full is img

        # a superseded render is discarded rather than painted over the new
        # scene
        w.run(svc._show_preview, svc._token - 1,
              [Image.new("RGB", (8, 8))], ["x.png"], {})
        assert svc._preview_full is img

        # an animated scene hands over several frames and starts playing them
        frames = [Image.new("RGB", (320, 180), c)
                  for c in ((10, 0, 0), (0, 10, 0), (0, 0, 10))]
        animated = dict(scene)
        animated["sprites"] = [{"name": "a", "x": 0, "y": 0, "image": "x.png",
                                "frames": ["a.png", "b.png", "c.png"]}]
        w.run(svc._show_preview, svc._token, frames,
              ["a.png", "b.png", "c.png"], animated)
        st = w.state("text_scenes")
        assert len(svc._frames_full) == 3
        assert st["frames"] == ["a.png", "b.png", "c.png"]
        assert "Animation: 3 frames" in st["caption_full"]
        assert st["animated"] is True              # ...so Speed appears now
        # the scene's own 60 fps rate is played, not an arbitrary cap (David:
        # the animation ran slow), and the Speed box can pin a fixed rate
        assert "60 fps" in st["caption_full"]
        assert st["fps"] == 60.0
        assert svc._effective_fps(animated) == 60.0
        assert w.call("text_scenes.set_fps", "4 fps") is True
        assert w.state("text_scenes")["fps"] == 4.0
        assert svc._effective_fps(animated) == 4.0
        w.call("text_scenes.set_fps", "Scene rate")
        assert svc._effective_fps(animated) == 60.0
        assert w.state("text_scenes")["fps"] == 60.0

        # switching scenes invalidates the token, which stops the old loop
        before = svc._token
        w.run(svc._render_preview, "/g/scene2")
        assert svc._token != before
        assert svc._frames_full == []

        # a scene with no recorded layout says so instead of drawing a black
        # frame
        assert w.call("text_scenes.select", "/g/scene2") is True
        st = w.state("text_scenes")
        assert st["caption"].startswith("No preview")
        assert st["can_save"] is False
        w.call("text_scenes.close")


def test_scene_browser_caption_is_one_line_with_the_rest_on_its_button(
        tmp_path):
    """The caption admits whatever a scene couldn't decode, so it wrapped to
    one, two or three lines depending on the scene and the pane jumped every
    time you stepped to another screen: "the area gets resized between
    different screens and it is jarring" (David).  One capped line stays on
    screen; the whole text lives on the "?" beside it."""
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.webui import text_scenes as sb_mod

    _make_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open_scenes(w, str(tmp_path))
        long_note = ("Still picture: 2 images and 6 text lines on a 1360x768 "
                     "stage. 43 more images in this scene can't be placed "
                     "yet. 1 element sits off the stage, so its position "
                     "isn't fully decoded.")
        w.run(svc._set_caption, long_note)
        st = w.state("text_scenes")
        shown = st["caption"]
        assert shown == ("Still picture: 2 images and 6 text lines on a "
                         "1360x768 stage.")
        assert "\n" not in shown and len(shown) <= sb_mod._CAPTION_CHARS
        assert st["caption_full"] == long_note    # the rest is a hover away
        # a caption longer than the cap is truncated rather than allowed to
        # widen
        w.run(svc._set_caption, "x" * 400)
        st = w.state("text_scenes")
        assert len(st["caption"]) <= sb_mod._CAPTION_CHARS
        assert st["caption_full"] == "x" * 400
        w.call("text_scenes.close")


def test_scene_browser_saves_an_animated_scene_as_mp4(tmp_path, monkeypatch):
    """"Save preview…" exports a scene that moves as an MP4 (a tester: "it
    would be cool to have the option to export the rendered scenes as MP4").

    The two things worth pinning: MP4 is what an animated scene offers and
    defaults to, and the export covers the WHOLE scene: the page only ever
    plays the first ``_MAX_PREVIEW_FRAMES``, and a GIF of a 1900-frame loop
    is not the answer.  ffmpeg itself is covered in test_scene_export_mp4."""
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.core import video
    from pinball_decryptor.webui import text_scenes as sb_mod

    _make_extract(tmp_path)
    # 80 frames: more than the 60 the preview renders, so "all of it" and
    # "what is on the page" are different numbers.
    n_all = 80
    assert n_all > sb_mod._MAX_PREVIEW_FRAMES
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 30.0], "unplaced": 0, "offstage": 0, "texts": [],
        "sprites": [{"name": "a", "x": 0, "y": 0, "image": "a.png",
                     "frames": ["f%d.png" % i for i in range(n_all)]}]}}
    _write_layout(tmp_path, layout)
    scene = layout["/g/scene1/scene.radium"]
    out = str(tmp_path / "out.mp4")

    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open_scenes(w, str(tmp_path))
        _select_quietly(w, svc, "/g/scene1")
        frames = [Image.new("RGB", (320, 180), (i, 0, 0)) for i in range(60)]
        w.run(svc._show_preview, svc._token, frames,
              ["f%d.png" % i for i in range(60)], scene)
        st = w.state("text_scenes")
        assert st["animated"] is True                    # it moves
        # the caption promises the export, and says how many frames it will
        # hold (on the "?" button: the visible line is one sentence of it)
        assert "writes all 80 to MP4" in st["caption_full"]

        # The worker runs inline so the export is deterministic here, and
        # each frame is a stand-in: what is counted is how many are asked for.
        monkeypatch.setattr(sb_mod, "threading",
                            types.SimpleNamespace(Thread=_SyncThread))
        svc._render_layout = lambda _layout, **_kw: Image.new("RGB", (8, 8))
        got = {}

        def fake_encode(frames_iter, path, fps=12.0, progress=None):
            n = 0
            for _f in frames_iter:               # drains the generator lazily
                n += 1
                if progress is not None:
                    progress(n)
            got.update(path=path, fps=fps, n=n)
            return n

        monkeypatch.setattr(video, "encode_frames_to_mp4", fake_encode)

        w.answers.append(out)
        assert w.call("text_scenes.save_preview") is True
        w.drain()                                # the posted finish
        asked = w.asked[-1]
        # MP4 is offered first and is the default extension for a moving
        # scene
        assert asked["kind"] == "file" and asked["mode"] == "save"
        assert asked["defaultextension"] == ".mp4"
        assert asked["filetypes"][0] == ["MP4 video", "*.mp4"]
        assert ["Animated GIF", "*.gif"] in asked["filetypes"]
        assert asked["initialfile"].endswith(".mp4")
        # ...and the export is the whole scene at its own rate, not the 60
        # frames the page is playing
        assert got["n"] == n_all
        assert got["fps"] == 30.0
        assert got["path"] == out
        st = w.state("text_scenes")
        assert svc._export is None                   # finished, not stuck
        assert st["exporting"] is False and st["can_save"] is True
        assert "Saved out.mp4" in st["caption_full"]
        assert "80 frames at 30 fps" in st["caption_full"]

        # a failed encode (no ffmpeg on this machine) says so and leaves the
        # button usable rather than stuck on Cancel
        def boom(*_a, **_k):
            raise RuntimeError("ffmpeg is needed to write an MP4")

        monkeypatch.setattr(video, "encode_frames_to_mp4", boom)
        n_asked = len(w.asked)
        w.answers.append(out)
        assert w.call("text_scenes.save_preview") is True
        w.drain()
        errs = [a for a in w.asked[n_asked:] if a["kind"] == "message"]
        assert len(errs) == 1 and errs[0]["title"] == "Save failed"
        assert "ffmpeg" in errs[0]["message"]
        st = w.state("text_scenes")
        assert svc._export is None
        assert st["exporting"] is False and st["can_save"] is True
        assert "Could not write out.mp4" in st["caption_full"]

        # While one is being written the button cancels it (a long scene is a
        # minute of rendering), and a cancelled export leaves no half-length
        # file behind: ffmpeg closes a truncated stream cleanly, so one would
        # exist.
        partial = tmp_path / "partial.mp4"
        partial.write_bytes(b"\x00" * 8)
        state = svc._export = {"cancel": False}
        n_asked = len(w.asked)
        assert w.call("text_scenes.save_preview") is True
        assert state["cancel"] is True
        assert len(w.asked) == n_asked               # no file picker
        w.run(svc._export_done, state, str(partial), 12, 30.0, None)
        assert not partial.exists()
        st = w.state("text_scenes")
        assert "Stopped" in st["caption_full"]
        assert st["exporting"] is False and svc._export is None

        # a stale worker's result (its state superseded) is ignored outright
        w.run(svc._export_done, {"cancel": False}, str(tmp_path / "x.mp4"),
              5, 30.0, None)
        assert "Stopped" in w.state("text_scenes")["caption_full"]

        # a still scene offers no video at all: an MP4 of one frame is a
        # picture
        still = dict(scene, sprites=[])
        w.run(svc._show_preview, svc._token, [frames[0]], ["f0.png"], still)
        assert w.call("text_scenes.save_preview") is False    # cancelled
        asked = w.asked[-1]
        assert asked["defaultextension"] == ".png"
        assert [t[0] for t in asked["filetypes"]] == ["PNG image"]
        w.call("text_scenes.close")


def test_scene_browser_steps_through_screens(tmp_path):
    """Back/forward walk the Screen list without re-opening the drop-down
    (David), with "All screens" as the entry before the first and wrap-around
    at both ends."""
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.webui import text_scenes as sb_mod

    _make_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open_scenes(w, str(tmp_path))
        # drive the stepper against a known screen list
        svc._current_layout = lambda: {"groups": ["Intro_Instance", "Award1"]}
        svc._render_preview = lambda *_a, **_k: None

        assert svc._screen == sb_mod._ALL_SCREENS
        assert w.call("text_scenes.step_screen", 1) is True
        assert svc._screen == "Intro_Instance"
        w.call("text_scenes.step_screen", 1)
        assert svc._screen == "Award1"
        w.call("text_scenes.step_screen", 1)     # wraps back to the composite
        assert svc._screen == sb_mod._ALL_SCREENS
        w.call("text_scenes.step_screen", -1)    # and backwards off the front
        assert svc._screen == "Award1"

        # a scene with a single screen has nothing to step through
        svc._current_layout = lambda: {"groups": []}
        assert w.call("text_scenes.step_screen", 1) is False
        w.call("text_scenes.close")


def test_scene_browser_rebuild_previews_action(tmp_path):
    """"Rebuild previews…" re-reads the layouts off the card without a full
    re-extract (which would overwrite the atlas PNGs and glyph slices, wiping
    a font import).  The threaded read is covered in the engine tests; what
    matters here is that it takes the card from the Extract tab, refuses
    politely without one, and can be cancelled."""
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract

    _make_extract(tmp_path)

    def set_card(w, value):
        def _do():
            try:
                w.window.extract_input_var.set(value)
            except Exception:                        # noqa: BLE001
                pass
        w.run(_do)

    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open_scenes(w, str(tmp_path))

        # no card image on the Extract tab -> a nudge, and nothing starts
        set_card(w, "")
        n = len(w.asked)
        assert w.call("text_scenes.rebuild") is False
        assert len(w.asked) == n + 1
        assert w.asked[-1]["title"] == "Rebuild previews"
        assert svc._rebuild is None

        # a path that isn't a file is the same case (a stale saved setting)
        set_card(w, str(tmp_path / "not_a_card.raw"))
        assert w.call("text_scenes.rebuild") is False
        assert len(w.asked) == n + 2 and svc._rebuild is None

        card = tmp_path / "card.raw"
        card.write_bytes(b"\x00" * 16)
        set_card(w, str(card))
        assert svc.card_image_path() == str(card)

        # while one runs the button cancels it, and a cancelled run leaves
        # the layouts alone rather than reporting a rebuild
        state = svc._rebuild = {"cancel": False}
        assert w.call("text_scenes.rebuild") is True
        assert state["cancel"] is True
        w.run(svc._rebuild_done, state, 0, None, [])
        st = w.state("text_scenes")
        assert "Stopped" in st["rebuild_msg"]
        assert st["rebuilding"] is False and svc._rebuild is None

        # a finished run reports the count and reloads the window
        reloaded = []
        svc.reload = lambda preselect=None, focus_text=None: \
            reloaded.append(preselect)
        state = svc._rebuild = {"cancel": False}
        w.run(svc._rebuild_tick, state, 40, 297)
        assert "40 of 297" in w.state("text_scenes")["rebuild_msg"]
        w.run(svc._rebuild_done, state, 297, None, [])
        assert "297" in w.state("text_scenes")["rebuild_msg"]
        assert len(reloaded) == 1

        # a stale worker's result (its state superseded) is ignored outright
        w.run(svc._rebuild_done, {"cancel": False}, 5, None, [])
        assert len(reloaded) == 1
        w.call("text_scenes.close")


def test_scene_browser_blanks_a_font_out_of_one_scene(tmp_path):
    """a tester, about an outline/shadow font: "Is there an easy way to blank
    it out from the scene menu? when i do doubleclick on it, it will go the
    import windows, but it will not blank it out there."

    It blanks scoped to the scene it was asked from: the atlas is shared, so
    an unscoped blank strips the same border off every other scene."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    _seed_scene_with_text(tmp_path)
    folder = str(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        # the caption this test reads must not be overwritten by a render
        _scenes(w)._render_preview = lambda *_a, **_k: None
        svc = _open_scenes(w, folder, preselect_dir="/g/scene1")
        assert w.state("text_scenes")["sel"] == "/g/scene1"

        font = {f["key"]: f for f in fr.load_fonts(folder)}["tbl"]
        glyph = font["glyphs"][0x41]["abs"]
        assert _alpha_max(glyph) > 0

        w.answers.append("yes")
        assert w.call("text_scenes.blank_font", "tbl", True) is True
        assert w.asked[-1]["title"] == "Blank font"
        assert "this scene only" in w.asked[-1]["message"]
        assert _alpha_max(glyph) == 0
        # this font is also in /g/scene9; the blank must not reach it
        assert fr.get_font_scope(folder, font) == ["/g/scene1/scene.radium"]
        assert "Blanked" in w.state("text_scenes")["caption_full"]
        w.call("text_scenes.close")


def test_font_studio_and_scene_browser_smoke(tmp_path):
    """The Fonts and Scenes windows (a tester) open on a synthetic Stern
    extract, populate their lists from the manifests, render a preview, sort,
    and jump.  Layout/pixel correctness lives in test_stern_fontrender; this
    is wiring only."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.core import text_manifest

    _make_extract(tmp_path)
    text_manifest.save(str(tmp_path), [
        {"path": "/g/scene1/scene.radium", "original": "HELLO",
         "replacement": ""}])
    folder = str(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, folder)
        st = w.state("text_fonts")
        assert {r["key"] for r in st["fonts"]} == {"tbl", "tbl2"}
        w.call("text_fonts.select", "tbl")
        w.call("text_fonts.set_opt", "text", "AB")
        w.run(fonts._render_now)
        st = w.state("text_fonts")
        assert st["preview"] and os.path.isfile(st["preview"])
        # scene usage list filled for the selected font
        assert len(st["scenes"]) >= 1

        svc = _open_scenes(w, folder)
        svc._render_preview = lambda *_a, **_k: None
        ds = [r["d"] for r in w.state("text_scenes")["scenes"]]
        assert "/g/scene1" in ds and "/g/scene2" in ds

        # every heading sorts, counts descending first, and clicking again
        # flips
        def by_imgs():
            return [r["imgs"] for r in w.state("text_scenes")["scenes"]]
        assert w.call("text_scenes.sort_by", "imgs") is True
        assert by_imgs() == sorted(by_imgs(), reverse=True)
        assert w.state("text_scenes")["sort"] == {"col": "imgs", "rev": True}
        w.call("text_scenes.sort_by", "imgs")
        assert by_imgs() == sorted(by_imgs())
        assert w.state("text_scenes")["sort"] == {"col": "imgs", "rev": False}
        w.call("text_scenes.sort_by", "#0")
        names = [r["label"].lower() for r in w.state("text_scenes")["scenes"]]
        assert names == sorted(names)
        assert w.call("text_scenes.sort_by", "bogus") is False

        w.call("text_scenes.select", "/g/scene1")
        groups = w.state("text_scenes")["contents"]["groups"]
        assert [g["title"].split(" (")[0] for g in groups] == [
            "Images", "Fonts", "Text", "Videos"]
        # double-clicking a text row lands on the Replace Text tab's search
        # (the tab has not scanned this folder, so there is no row to land
        # on yet; test_webui_text covers landing on the row)
        w.call("text_scenes.activate", groups[2]["items"][0]["id"])
        assert w.window.text_search_var.get() == "HELLO"
        assert not w.state("text_scenes")["open"]      # stepped aside

        w.call("text_fonts.close")
        w.call("text_scenes.close")


def test_scene_jumps_from_the_font_and_video_lists(tmp_path):
    """The other two ways into a scene: right-clicking a scene in the Fonts
    window's usage list, and a video row on the Video tab.  The Fonts one is
    right-click on purpose: that list's selection IS the font's scene scope,
    and a jump must not rewrite where an import lands."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from pinball_decryptor.plugins.stern import fontrender as fr

    assets = _stern_text_extract(tmp_path)
    vdir = tmp_path / "video"
    vdir.mkdir()
    (vdir / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n"
        "Intro.mp4\t/g/scene2/scene.assets/3.asset/0.asset\t32\n",
        encoding="utf-8")

    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, assets, preselect="tbl")
        paths = list(fonts._scene_paths)
        assert paths                                # scenes using the font
        before = w.state("text_fonts")["scope_sel"]
        assert w.call("text_fonts.show_scene", 0) is True
        assert w.state("text_scenes")["sel"] == paths[0].rsplit("/", 1)[0]
        # scope untouched
        assert w.state("text_fonts")["scope_sel"] == before
        assert w.state("text_fonts")["scope"] == "all"
        assert fr.get_font_scope(assets, fonts._current_font()) is None

        # Video row -> the scene that plays the clip.
        assert w.run(lambda: w.window.open_scene_browser(
            assets, preselect_video="video/Intro.mp4")) is True
        assert w.state("text_scenes")["sel"] == "/g/scene2"
        w.call("text_fonts.close")
        w.call("text_scenes.close")


# ============================================================= Fonts window
def test_font_studio_blank_button_and_scene_tint_note(tmp_path):
    """The Fonts window can blank a font on its own (it used to happen only as
    a side effect of importing into the font an outline sits behind), and says
    what the scenes multiply the ink by, which is why a tester's colour picks
    "did not produce what i wanted"."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import fontrender as fr
    from pinball_decryptor.plugins.stern import scene_render

    _make_extract(tmp_path)
    # the scenes draw this font BLACK: no ink colour can ever show there
    _seed_scene_with_text(tmp_path, rgba=(0.0, 0.0, 0.0, 1.0))
    folder = str(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, folder, preselect="tbl")
        st = w.state("text_fonts")
        note = st["tint"]
        assert "MULTIPLIES" in note and "tinted black" in note
        assert st["tint_warn"] is True

        # the preview can be put on something other than black
        assert "Checkerboard" in scene_render.BACKGROUND_NAMES
        assert "Checkerboard" in st["bgs"]
        w.call("text_fonts.set_opt", "bg", "Checkerboard")
        w.run(fonts._render_now)                     # must not fail
        assert os.path.isfile(w.state("text_fonts")["preview"])

        glyph = fonts._current_font()["glyphs"][0x41]["abs"]
        assert _alpha_max(glyph) > 0
        w.answers.append("yes")
        assert w.call("text_fonts.blank") is True
        assert _alpha_max(glyph) == 0
        assert "blanked" in w.state("text_fonts")["status"]

        # blanking is undoable: it is a write like any other, not a one-way
        # door
        assert w.call("text_fonts.undo") is True
        assert _alpha_max(glyph) > 0

        # a font no scene is recorded as drawing says nothing at all rather
        # than guessing white
        assert "tbl2" in {f["key"] for f in fr.load_fonts(folder)}
        w.call("text_fonts.select", "tbl2")
        assert w.state("text_fonts")["tint"] == ""
        w.call("text_fonts.close")


def test_font_studio_colour_alone_repaints_the_current_letters(tmp_path):
    """The Color swatch used to reach only an imported desktop font: pick a
    colour with no font file and the swatch went green while the preview
    stayed white (David hit exactly this).  A colour on its own now stages a
    repaint of the letters already there, applied like any other edit."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract

    _make_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, str(tmp_path), preselect="tbl")
        assert w.state("text_fonts")["can_apply"] is False

        assert w.call("text_fonts.set_color", "#33cc33") is True

        # previewable and applyable with no font file anywhere, and NOT
        # staged as a pending import (browsing the list must not fill it with
        # edits)
        assert "tbl" not in fonts._pending
        assert fonts._custom_color() is True
        assert w.state("text_fonts")["can_apply"] is True
        w.run(fonts._render_now)
        assert "in #33cc33" in w.state("text_fonts")["status"]

        # the colour is a SETTING: it follows the selection down the list,
        # which is what David reported missing ("when i change the font
        # selection, the color preview does not carry over")
        w.call("text_fonts.select", "tbl2")
        w.run(fonts._render_now)
        st = w.state("text_fonts")
        assert fonts._custom_color() is True
        assert st["color"] == "#33cc33"
        assert "in #33cc33" in st["status"]
        assert st["can_apply"] is True

        w.call("text_fonts.select", "tbl")
        glyph = fonts._current_font()["glyphs"][0x41]["abs"]
        assert w.call("text_fonts.apply") is True
        on_disk = np.asarray(Image.open(glyph).convert("RGBA"))
        assert (on_disk[on_disk[..., 3] > 0][:, :3] == (51, 204, 51)).all()
        assert "repainted #33cc33" in w.state("text_fonts")["status"]

        # ...and it undoes like any other write
        assert w.call("text_fonts.undo") is True
        back = np.asarray(Image.open(glyph).convert("RGBA"))
        assert not (back[back[..., 3] > 0][:, :3] == (51, 204, 51)).all()

        # back on "match original" there is nothing of the user's left to
        # apply
        w.call("text_fonts.set_opt", "auto_color", True)
        assert fonts._custom_color() is False
        assert w.state("text_fonts")["can_apply"] is False
        w.call("text_fonts.close")


def test_font_studio_outline_companion(tmp_path):
    """The Fonts window names the outline font drawn behind a typeface, and
    can remove it with the import.

    A tester restyled a whole game and kept getting "a strange inconsistent
    black border" he blamed on his own stroke colour: it was the ORIGINAL
    typeface's outline companion, a separate font he had no reason to open.
    The window now says so on the font that has one, and Apply can blank it."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.webui import text_fonts as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_outline_extract(tmp_path)
    folder = str(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, folder, preselect="body")

        # the body font is told what sits behind it, and offered the removal
        st = w.state("text_fonts")
        assert fonts._companion(fonts._current_font())["key"] == "ok"
        assert "in black behind" in st["comp_text"]
        assert st["comp_ctrl"] is True
        assert "+outline" in next(r["size"] for r in st["fonts"]
                                  if r["key"] == "body")

        # the companion itself explains what it IS, with no action offered
        w.call("text_fonts.select", "ok")
        st = w.state("text_fonts")
        assert "This IS an outline font" in st["comp_text"]
        assert st["comp_ctrl"] is False

        # an unpaired outline row offers no removal either
        w.call("text_fonts.select", "wrong")
        assert w.state("text_fonts")["comp_ctrl"] is False

        # Apply with "remove it" blanks the companion's slices...
        w.call("text_fonts.select", "body")
        fo = fonts._current_font()
        fonts._pending[fo["key"]] = (
            {0x41: Image.new("RGBA", (4, 6), (9, 9, 9, 255))}, 6, [], "x.ttf")
        w.call("text_fonts.set_opt", "comp", fs_mod._COMP_CLEAR)
        assert w.call("text_fonts.apply") is True
        comp = fonts._companions["body"]
        a = np.asarray(Image.open(comp["glyphs"][0x41]["abs"]).convert("RGBA"))
        assert a[..., 3].max() == 0, "the old outline should draw nothing now"
        assert "was blanked" in w.state("text_fonts")["status"]

        # ...and ONLY in the scenes this font is in.  Blanking is card-wide by
        # default (one atlas serves every scene that draws it), so an unscoped
        # removal strips the outline off screens the user never touched: on
        # TMNT 446 scene occurrences against 6 that overlap the body font.  A
        # tester did exactly that by hand: "i did remove to much shadow, now
        # on the normal font some are missing too".
        scoped = fr.get_font_scope(folder, comp)
        assert scoped == ["/g/scene1/scene.radium"], scoped
        assert "/g/scene5/scene.radium" not in (scoped or []), \
            "the scene without the body font must keep its outline"

        # ...and Revert puts it back, so the removal is never a one-way door
        w.answers.append("yes")
        assert w.call("text_fonts.revert") is True
        back = np.asarray(
            Image.open(comp["glyphs"][0x41]["abs"]).convert("RGBA"))
        assert back.shape[:2] == a.shape[:2]
        w.call("text_fonts.close", True)


def test_font_studio_outline_scope_covers_every_restyled_size(tmp_path):
    """Removing the outline has to reach the scenes of every size Apply just
    restyled, not only the one size the outline is paired to.

    An outline font pairs with exactly ONE size of its typeface, but Apply
    restyles all of them, so pairing used to decide the scope: on a tester's
    TMNT the OUTLINE6 companion was narrowed to the 1 scene it shared with
    the 94px row while the typeface he had restyled in full is drawn in all
    25 of that outline's scenes, and 24 screens kept the old border.  The
    scope is still an INTERSECTION, so a scene that draws the outline without
    any of those body rows keeps it."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract
    from pinball_decryptor.webui import text_fonts as fs_mod
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_outline_extract(tmp_path)
    # "body2" is the same typeface in /g/scene1 too; make it a second scene
    # so the union is bigger than the paired row's own overlap
    tex = tmp_path / "images" / "scene_textures"
    rows = (tex / "radium_images.txt").read_text(encoding="utf-8")
    rows += ("scene_textures/radimg_T_8x8_00000005.png\t/g/scene5/scene.radium"
             "\t100\t256\t32\t32\t5\n")
    (tex / "radium_images.txt").write_text(rows, encoding="utf-8")
    folder = str(tmp_path)

    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, folder, preselect="body")
        fo = fonts._current_font()
        assert fonts._companion(fo)["key"] == "ok"
        assert set(fr.scenes_for_font(folder, fonts._by_key["body2"])) == {
            "/g/scene1/scene.radium", "/g/scene5/scene.radium"}

        w.call("text_fonts.set_opt", "all_sizes", True)
        w.call("text_fonts.set_opt", "comp", fs_mod._COMP_CLEAR)
        fonts._pending[fo["key"]] = (
            {0x41: Image.new("RGBA", (20, 34), (9, 9, 9, 255))}, 34, [],
            "x.ttf")
        assert w.call("text_fonts.apply") is True

        scoped = fr.get_font_scope(folder, fonts._companions["body"])
        assert scoped == ["/g/scene1/scene.radium",
                          "/g/scene5/scene.radium"], \
            "the outline must go from every scene the restyled sizes are in"
        w.call("text_fonts.close", True)


def test_font_studio_applies_to_every_size_of_a_typeface(tmp_path):
    """One typeface is baked at many sizes and each is its own font here:
    TMNT lists Stern_CCZoinks 94 times.  A tester "replaced the font wherever
    i found it" and still saw stock letters, because nobody does 94 imports
    by hand.  Apply fits the same font file into every size."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract, _system_ttf
    if _system_ttf() is None:
        pytest.skip("no system TTF found")

    _make_outline_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, str(tmp_path), preselect="body")

        # the tick names the real count and is hidden for a one-off
        # typeface.  It says "copies", not "sizes": a typeface is baked once
        # per size AND once per scene, so its other rows are often the same
        # size (Godzilla lists HelveticaNeueBlack three times at 102px) and
        # "sizes" told a user who wanted one size that he could safely untick
        # it.
        assert fonts._same_typeface(fonts._current_font())[0]["key"] == \
            "body2"
        assert "other 1 copy" in w.state("text_fonts")["all_sizes_label"]

        sib = fonts._by_key["body2"]
        before = open(sib["glyphs"][0x41]["abs"], "rb").read()
        fonts._ttf_paths["body"] = _system_ttf()
        w.run(fonts._rasterize)
        assert "body" in fonts._pending
        assert w.state("text_fonts")["opts"]["all_sizes"] is True
        assert w.call("text_fonts.apply") is True
        after = open(sib["glyphs"][0x41]["abs"], "rb").read()
        assert after != before, "the other size should have been restyled too"
        assert "1 more copy" in w.state("text_fonts")["status"]

        # Revert all puts the whole project back, which is how you start over
        w.answers.append("yes")
        assert w.call("text_fonts.revert_all") is True
        assert "restored to stock" in w.state("text_fonts")["status"]
        a = np.asarray(Image.open(sib["glyphs"][0x41]["abs"]).convert("RGBA"))
        assert a.shape[:2] == (sib["glyphs"][0x41]["h"],
                               sib["glyphs"][0x41]["w"])
        w.call("text_fonts.close", True)


def test_font_studio_blank_reaches_every_copy_of_a_typeface(tmp_path):
    """Blanking an outline font has to reach every ROW of that typeface.

    A typeface is baked into its own atlas per size AND per scene, so it
    fills several rows here that nothing on screen tells apart (Godzilla
    lists HelveticaNeueBlack three times at 102px, 113 letters, 5 scenes,
    different scenes each).  Blank used to erase exactly the row that was
    selected, so a tester who "went through the font list and blanked the
    outlines" still had the old outline on every scene the other rows cover,
    and read the font's short scene list as proof the scenes weren't being
    enumerated."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_outline_extract

    _make_outline_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        # "ok" and "far" are the same outline typeface in different scenes
        fonts = _open_fonts(w, str(tmp_path), preselect="ok")
        assert [f["key"] for f in fonts._same_typeface(
            fonts._current_font())] == ["far"]
        # ...and the list finally says so, instead of showing two identical
        # rows
        st = w.state("text_fonts")
        size = {r["key"]: r["size"] for r in st["fonts"]}
        assert "copy 1 of 2" in size["ok"]
        assert "copy 2 of 2" in size["far"]
        assert "further copies of a font already listed" in st["hint"]

        def ink(key):
            return _alpha_max(fonts._by_key[key]["glyphs"][0x41]["abs"])

        assert ink("ok") > 0 and ink("far") > 0
        w.answers.append("yes")
        assert w.call("text_fonts.blank") is True
        assert ink("ok") == 0
        assert ink("far") == 0, "the other copy still draws the old outline"
        assert "1 more copy" in w.state("text_fonts")["status"]

        # ...and one Undo brings both back: reaching further must not make
        # the step back smaller
        assert w.call("text_fonts.undo") is True
        assert ink("ok") > 0 and ink("far") > 0

        # with the tick off it is the selected row only, which is the old
        # behaviour and still the way to blank an outline out of one place
        w.call("text_fonts.set_opt", "all_sizes", False)
        w.answers.append("yes")
        assert w.call("text_fonts.blank") is True
        assert ink("ok") == 0
        assert ink("far") > 0
        w.call("text_fonts.close", True)


def test_font_studio_revert_reaches_as_far_as_the_blank_did(tmp_path):
    """Revert follows the same tick as Blank and Apply.  Anything else means
    "blank every copy" is one click and the way back is 94."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import numpy as np
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract

    _make_outline_extract(tmp_path)
    # the fixture's atlases are empty, and revert re-cuts the letters FROM
    # the atlas: give the two outline copies something to come back to
    tex = tmp_path / "images" / "scene_textures"
    for aid in ("0002", "0004"):
        Image.fromarray(np.full((32, 32, 4), 255, np.uint8), "RGBA").save(
            str(tex / ("radimg_T_8x8_0000%s.png" % aid)))
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, str(tmp_path), preselect="ok")

        def ink(key):
            return _alpha_max(fonts._by_key[key]["glyphs"][0x41]["abs"])

        w.answers.append("yes")
        assert w.call("text_fonts.blank") is True
        assert ink("ok") == 0 and ink("far") == 0
        w.answers.append("yes")
        assert w.call("text_fonts.revert") is True
        assert ink("ok") > 0
        assert ink("far") > 0, "the copy blanked with it has to come back"
        assert "all 2 copies" in w.state("text_fonts")["status"]
        w.call("text_fonts.close", True)


def test_font_studio_undo_steps_back_rather_than_to_stock(tmp_path):
    """Undo is not Revert.  Revert goes all the way back to the stock
    letters; Undo goes back ONE step, to whatever was there before: the
    import you had before this one, or the whole project before "Revert all
    fonts"."""
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_outline_extract

    _make_outline_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, str(tmp_path), preselect="body")
        w.call("text_fonts.set_opt", "all_sizes", False)
        fo = fonts._current_font()
        slot = fo["glyphs"][0x41]
        stock = open(slot["abs"], "rb").read()
        assert w.state("text_fonts")["can_undo"] is False

        def apply_colour(rgb):
            fonts._pending[fo["key"]] = (
                {0x41: Image.new("RGBA", (slot["w"], slot["h"]), rgb)},
                34, [], "x.ttf")
            assert w.call("text_fonts.apply") is True
            return open(slot["abs"], "rb").read()

        first = apply_colour((10, 200, 10, 255))
        assert first != stock
        st = w.state("text_fonts")
        assert st["can_undo"] is True
        assert "import" in st["undo_label"]
        second = apply_colour((200, 10, 10, 255))
        assert second != first

        assert w.call("text_fonts.undo") is True
        assert open(slot["abs"], "rb").read() == first, \
            "back one step, not to stock"
        assert "Undid" in w.state("text_fonts")["status"]
        w.call("text_fonts.undo")
        assert open(slot["abs"], "rb").read() == stock
        assert w.state("text_fonts")["can_undo"] is False

        # and the destructive action is recoverable too
        third = apply_colour((10, 10, 200, 255))
        w.answers.append("yes")
        assert w.call("text_fonts.revert_all") is True
        assert open(slot["abs"], "rb").read() != third
        w.call("text_fonts.undo")
        assert open(slot["abs"], "rb").read() == third, \
            "Revert all fonts must be undoable"

        # switching project folders drops the history: those are absolute
        # paths in the OLD project, and undoing would write files back into
        # it
        apply_colour((0, 0, 0, 255))
        assert fonts._undo
        fonts.assets_dir = str(tmp_path / "elsewhere")
        w.run(fonts.reload)
        assert fonts._undo == []
        assert w.state("text_fonts")["can_undo"] is False
        w.call("text_fonts.close", True)


def test_font_studio_warns_before_restyling_a_tiny_font(tmp_path):
    """a tester: "smaller fonts do look more and more strange the smaller
    they get… i guess they should be skipped".  The list marks them and Apply
    asks once: it does not refuse, because his call is the one that
    counts."""
    pytest.importorskip("PIL")
    from PIL import Image
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, str(tmp_path), preselect="tbl")
        fo = fonts._current_font()
        assert fo["px"] < fr.MIN_RESTYLE_PX
        assert "tiny" in next(r["size"] for r in
                              w.state("text_fonts")["fonts"]
                              if r["key"] == "tbl")

        fonts._pending[fo["key"]] = ({0x41: Image.new("RGBA", (4, 6))}, 6, [],
                                     "x.ttf")
        w.answers.append("no")
        assert w.call("text_fonts.apply") is False
        assert w.asked[-1]["title"] == "Small font"
        assert "pixels tall" in w.asked[-1]["message"]
        assert fo["key"] in fonts._pending, "declining must not write anything"

        w.answers.append("yes")
        assert w.call("text_fonts.apply") is True
        assert fo["key"] not in fonts._pending
        w.call("text_fonts.close", True)


def test_font_studio_scene_scope_control(tmp_path):
    """The Fonts window can limit a font edit to chosen scenes: picking scenes
    persists a scope the Build reads, it survives reopening the window, and
    switching back to "all" clears it."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import fontrender as fr

    _make_extract(tmp_path)
    folder = str(tmp_path)
    with web_app(tmp_path / "app", mfr="stern") as w:
        fonts = _open_fonts(w, folder, preselect="tbl")

        # Default is every scene, and nothing is persisted until you narrow
        # it.
        st = w.state("text_fonts")
        assert st["scope"] == "all"
        assert fonts._scene_paths == ["/g/scene1/scene.radium",
                                      "/g/scene9/scene.radium"]
        assert "all 2 scenes" in st["scope_lbl"]
        assert fr.get_font_scope(folder, fonts._current_font()) is None

        # Narrow to the second scene -> saved for the Build to read.
        assert w.call("text_fonts.set_scope_mode", "some") is True
        assert w.call("text_fonts.set_scope_sel", [1]) is True
        assert fr.get_font_scope(folder, fonts._current_font()) == [
            "/g/scene9/scene.radium"]
        assert "Only 1 of 2" in w.state("text_fonts")["scope_lbl"]

        # It survives a reload of the window (it lives in the project folder).
        w.run(fonts.reload, "tbl")
        st = w.state("text_fonts")
        assert st["scope"] == "some"
        assert st["scope_sel"] == [1]

        # Back to all -> scope cleared.
        w.call("text_fonts.set_scope_mode", "all")
        assert fr.get_font_scope(folder, fonts._current_font()) is None
        w.call("text_fonts.close")
