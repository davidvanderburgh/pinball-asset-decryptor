"""PAD-81 — a tester's suggestion list, the three parts that are in the app.

* **Compare tab, "Extract Both".**  The report diffs digests and can never
  play a sound, so the follow-up is always two extracts.  "Adding an Extract
  Both button for the two images would be very useful in order to have a
  complete comparison in one action."
* **Compare report, double-click.**  "Being able to open/play modified, added
  or deleted assets via double-click would be awesome."
* **Scenes window, bulk save.**  "A bulk Save Preview feature would be very
  helpful."

INVOKED, NOT LOOKED AT, for the same reason as the playfield action row: a
button that is drawn and wired to nothing is exactly what a screenshot cannot
see.  Every assertion here goes through the real call the page makes or the
real handler, and lands on a recorder standing in for the plugin / the
desktop / the run.  Driven through the web UI (webui/tabs/compare.py,
webui/text_scenes.py) and the run logic in app.py.
"""

import os
import time

import pytest

from pinball_decryptor.app import App
from tests.webui_harness import web_app


def _wait(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _svc(w):
    return w.window.service("compare")


# ---------------------------------------------------------------------------
# Compare report: which rows open, and off which card
# ---------------------------------------------------------------------------

_SECTIONS = [
    ("Compared", [("Image A", "a.raw — 8 GB"), ("Image B", "b.raw — 8 GB")]),
    ("Images", [("Added", "1:"),
                ("", "gfx/new.png — 3 KB",
                 {"side": "B", "part": 1, "path": "g/gfx/new.png",
                  "name": "new.png"}),
                ("Deleted", "1:"),
                ("", "gfx/old.png — 4 KB",
                 {"side": "A", "part": 1, "path": "g/gfx/old.png",
                  "name": "old.png"})]),
]


def _render(w):
    w.run(_svc(w).render, _SECTIONS)
    return w.state("compare")["rows"]


def test_only_the_file_rows_are_openable(tmp_path):
    """Section headers and count rows carry no ref, and the tab says so
    instead of swallowing the double-click."""
    with web_app(tmp_path, mfr="stern") as w:
        rows = _render(w)
        svc = _svc(w)
        openable = set(svc._refs)
        assert len(openable) == 2
        # ...and they are marked, so the user can see which rows lead
        # somewhere.
        for r in rows:
            assert r["open"] is (r["id"] in openable)
        sections = [r for r in rows if r["kind"] == "section"]
        heads = [r for r in rows if r["kind"] == "head"]   # "Added:" ...
        assert sections and heads
        assert not ({r["id"] for r in sections + heads} & openable)

        w.run(lambda: svc.set(status=""))
        assert w.run(svc._open_target, sections[0]["id"]) is None
        assert "double-click one of the file rows" in \
            w.state("compare")["status"]


def test_a_deleted_row_opens_image_a_and_the_rest_open_image_b(tmp_path):
    """THE SIDE IS THE WHOLE POINT.  A deleted file is on exactly one of the
    two cards; sending that row to image B would open nothing every time."""
    a = tmp_path / "a.raw"
    b = tmp_path / "b.raw"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "compare", "a", str(a))
        w.call("ui.set", "compare", "b", str(b))
        _render(w)
        svc = _svc(w)

        got = {}
        for rid, ref in dict(svc._refs).items():
            side, image, back = w.run(svc._open_target, rid)
            assert back is ref
            got[ref["name"]] = (side, image)
        assert got == {"new.png": ("B", str(b)), "old.png": ("A", str(a))}


def test_a_card_that_moved_says_so_rather_than_opening_nothing(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "compare", "a", str(tmp_path / "gone.raw"))
        w.call("ui.set", "compare", "b", str(tmp_path / "gone.raw"))
        _render(w)
        svc = _svc(w)
        rid = next(iter(svc._refs))
        assert w.run(svc._open_target, rid) is None
        assert w.asked and "no longer at" in w.asked[-1]["message"]


def test_the_opened_copy_is_handed_to_the_desktop(tmp_path, monkeypatch):
    """The finish half: a success reports where it went, and a failure that
    reports nothing is the one outcome this must never produce."""
    from pinball_decryptor.core import desktop
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        opened = []
        monkeypatch.setattr(desktop, "open_path",
                            lambda p, env=None: (opened.append(p),
                                                 (True, ""))[1])

        def _busy():
            svc._open_busy = True
        w.run(_busy)
        w.run(svc._open_finished, "new.png", "B",
              str(tmp_path / "new.png"), None)
        assert opened == [str(tmp_path / "new.png")]
        assert svc._open_busy is False
        assert "Opened new.png from image B" in w.state("compare")["status"]

        # A read that failed says which card it failed on, and unlatches the
        # one-at-a-time guard so the next double-click still works.
        w.run(_busy)
        w.run(svc._open_finished, "old.png", "A", None,
              FileNotFoundError("not on the card"))
        assert svc._open_busy is False
        said = w.asked[-1]["message"]
        assert "image A" in said and "not on the card" in said

        # So does a desktop that refuses to open it — with the path, so the
        # user can still get at the file.
        monkeypatch.setattr(desktop, "open_path",
                            lambda p, env=None: (False, "no handler"))
        w.run(svc._open_finished, "new.png", "B", r"C:\tmp\new.png", None)
        told = w.asked[-1]["message"]
        assert "no handler" in told and "new.png" in told


# ---------------------------------------------------------------------------
# Compare tab: Extract Both
# ---------------------------------------------------------------------------

def test_extract_both_needs_two_different_real_images(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        asked = []
        w.window.cb["on_extract_both"] = lambda a, b: asked.append((a, b))

        def _said():
            return [a["title"] for a in w.asked]

        w.call("ui.set", "compare", "a", "")
        w.call("ui.set", "compare", "b", "")
        w.call("compare.extract_both")
        assert asked == [] and _said() == ["Pick two images"]

        card = tmp_path / "turtles_pro-1_58_0.raw"
        card.write_bytes(b"card")
        w.call("ui.set", "compare", "a", str(card))
        w.call("ui.set", "compare", "b", str(tmp_path / "not_there.raw"))
        w.call("compare.extract_both")
        assert asked == [] and _said()[-1] == "File not found"

        # The same card twice is one extract, not two.
        w.call("ui.set", "compare", "b", str(card))
        w.call("compare.extract_both")
        assert asked == [] and _said()[-1] == "Same image twice"

        other = tmp_path / "turtles_pro-1_59_0.raw"
        other.write_bytes(b"card")
        w.call("ui.set", "compare", "b", str(other))
        w.call("compare.extract_both")
        assert asked == [(str(card), str(other))]


def test_each_card_gets_a_folder_named_after_the_card():
    """A folder called "A" tells you nothing three days later; the card name
    already carries the title and the version.

    Every path here is built with ``os.path.join``, never as a drive-letter
    literal: the separator is the PLATFORM's, so a backslash literal is one
    path on Windows and a single long filename that happens to contain
    backslashes on the Linux and macOS CI runners, where ``basename`` then
    hands the whole string back.
    """
    f = App._extract_both_folder
    out = os.path.join("out", "compare")
    assert f(out,
             os.path.join("img", "turtles_pro-1_58_0.Release.8G.sdcard.raw"),
             os.path.join("img", "turtles_pro-1_59_0.Release.8G.sdcard.raw")) \
        == os.path.join(out, "turtles_pro-1_58_0.Release.8G.sdcard")
    # Two cards with the SAME filename in different folders would otherwise
    # land on one folder and the second run would extract over the first.
    one = f(out, os.path.join("cards", "stock", "card.raw"),
            os.path.join("cards", "modded", "card.raw"))
    two = f(out, os.path.join("cards", "modded", "card.raw"),
            os.path.join("cards", "stock", "card.raw"))
    assert one != two
    assert one.endswith("card (stock)") and two.endswith("card (modded)")


def test_the_second_card_is_queued_only_once_the_first_run_started(
        tmp_path, monkeypatch):
    """_start_extract bails out at half a dozen guards (no output folder, an
    overwrite the user declines, nothing ticked).  A chain left armed by one
    of those would fire card B onto the end of a later, unrelated extract."""
    a = tmp_path / "lz-1_20_0.raw"
    b = tmp_path / "lz-1_22_0.raw"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    both = str(tmp_path / "both")
    with web_app(tmp_path, mfr="stern") as w:
        app, win = w.app, w.window
        monkeypatch.setattr(app, "_start_extract", lambda: None)  # never starts
        w.answers.append(both)
        w.run(app._start_extract_both, str(a), str(b))
        assert app._chain_extract_next is None
        assert win.extract_input_var.get() == str(a)
        assert win.extract_output_var.get() == os.path.join(both, "lz-1_20_0")
        # A card image is a file: an Extract Both left on "From SSD" would
        # send _start_extract down the physical-device branch with a path
        # that is not a device.
        assert win.extract_input_source_var.get() == "iso"

        def _started():
            app.pipeline = object()
        monkeypatch.setattr(app, "_start_extract", _started)
        w.answers.append(both)
        w.run(app._start_extract_both, str(a), str(b))
        assert app._chain_extract_next == (
            str(b), os.path.join(both, "lz-1_22_0"))


def test_a_finished_first_card_starts_the_second(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        ran = []
        monkeypatch.setattr(app, "_run_chained_extract",
                            lambda i, o: ran.append((i, o)))
        pair = (str(tmp_path / "b.raw"), str(tmp_path / "outb"))

        def _arm():
            app._active_mode = "extract"
            app._last_extract_io = None
            app._chain_extract_next = pair
        w.run(_arm)
        w.run(app._on_done, True, "Extract complete")
        assert _wait(w, lambda: ran)       # the chain is armed with after(0)
        assert ran == [pair]
        assert app._chain_extract_next is None

        # A FAILED first card drops the pair; the second must not ride on
        # whatever run finishes next.
        ran.clear()
        w.run(_arm)
        w.run(app._on_done, False, "Extract failed")
        time.sleep(0.2)
        w.drain()
        assert ran == []
        assert app._chain_extract_next is None


# ---------------------------------------------------------------------------
# Scenes window: save every listed preview
# ---------------------------------------------------------------------------

def _scene_window(w, tmp_path, scenes=("scene1", "scene2", "scene9")):
    """A Scenes window over the shared three-scene font fixture, each scene
    given a layout that draws one real atlas PNG (a sprite always renders; the
    fixture's text needs a font key the layout would have to invent)."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    import json

    from pinball_decryptor.plugins.stern import scene_render
    from tests.test_stern_fontrender import _make_extract

    _make_extract(tmp_path)
    sprite = {"name": "art", "x": 0, "y": 0,
              "image": "scene_textures/radimg_TestA_8x8_00000001.png"}
    layout = {"/g/%s/scene.radium" % n: {
                  "stage": [320, 180, 60.0], "partial": False, "unplaced": 0,
                  "offstage": 0, "sprites": [sprite], "texts": []}
              for n in scenes}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)
    text = w.window.service("text")
    assert w.run(text.open_scene_browser, str(tmp_path)) is True
    return text.scenes


class _NoWorker:
    """Stands in for the bulk-save worker thread: takes the dispatch, never
    runs it."""

    def __init__(self, target=None, **kw):
        self.target = target

    def start(self):
        pass


def _no_worker_thread(monkeypatch):
    """Let the button dispatch a batch with no live thread behind it, so the
    test can press it a second time (the cancel) before any work runs."""
    import threading as _real

    class _Shim:
        Thread = _NoWorker

        def __getattr__(self, name):       # Event, Lock, … stay real
            return getattr(_real, name)

    monkeypatch.setattr("pinball_decryptor.webui.text_scenes.threading",
                        _Shim())


def _run_bulk(w, sb, out):
    """Click "Save all previews…" the way the page does and wait for the
    batch to land.  THE CALL IS PART OF THE TEST — a command wired to nothing
    is exactly what a screenshot cannot see."""
    captured = {}
    orig = sb._save_all_done

    def _done(state, out_, written, skipped, err):
        captured["r"] = (written, skipped)
        return orig(state, out_, written, skipped, err)
    sb._save_all_done = _done
    try:
        w.answers.append(str(out))
        assert w.call("text_scenes.save_all") is True
        # started: still running, or (a fast runner) already done
        assert (w.state("text_scenes")["bulk"] is True
                or sb._bulk is not None or "r" in captured
                or _wait(w, lambda: "r" in captured)), \
            "the button did not start a batch"
        assert _wait(w, lambda: "r" in captured and sb._bulk is None)
    finally:
        del sb._save_all_done
    return captured["r"]


def test_save_all_previews_writes_one_png_per_listed_scene(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        out = tmp_path / "shots"
        out.mkdir()
        written, skipped = _run_bulk(w, sb, out)

        assert (written, skipped) == (3, 0)
        assert sb._bulk is None
        assert w.state("text_scenes")["bulk"] is False
        names = sorted(os.listdir(out))
        assert len(names) == 3, names
        assert all(n.lower().endswith(".png") for n in names)
        full = w.state("text_scenes")["caption_full"]
        assert "Saved 3 previews" in full
        assert "first frame of each" in full


def test_the_search_box_narrows_the_batch(tmp_path):
    """The list is the batch — silently exporting the scenes the user just
    filtered out is the same surprise as extra work nobody asked for."""
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        listed = list(sb._listed)
        assert len(listed) == 3
        w.call("text_scenes.set_search", sb._scenes[listed[0]]["label"])
        assert len(sb._listed) == 1

        out = tmp_path / "one"
        out.mkdir()
        assert _run_bulk(w, sb, out) == (1, 0)
        assert len(os.listdir(out)) == 1


def test_two_scenes_that_sanitise_alike_do_not_overwrite_each_other():
    """An overwrite there would silently drop a scene from a folder that
    claims to hold them all."""
    from pinball_decryptor.webui.text_scenes import _safe_stem, _unique_png

    used = set()
    assert _unique_png("Game · Intro", used) == "Game___Intro.png"
    assert _unique_png("Game / Intro", used) == "Game___Intro_2.png"
    assert _unique_png("Game ? Intro", used) == "Game___Intro_3.png"
    assert _safe_stem("") == "scene"
    assert _safe_stem("///") == "___"


def test_a_scene_with_no_layout_is_counted_not_guessed_at(tmp_path):
    """A folder of 2 PNGs from a 3-scene list has to say what happened to the
    third."""
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")

        def _drop():
            sb._layouts = {k: v for k, v in sb._layouts.items()
                           if not k.endswith("/g/scene9/scene.radium")}
        w.run(_drop)
        out = tmp_path / "partial"
        out.mkdir()
        assert _run_bulk(w, sb, out) == (2, 1)
        assert len(os.listdir(out)) == 2
        assert "1 scene could not be drawn" in \
            w.state("text_scenes")["caption_full"]


def test_a_cancelled_batch_reports_what_it_did_write(tmp_path, monkeypatch):
    """Cancel stops the batch; it does not pretend the folder is empty."""
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        out = tmp_path / "stopped"
        out.mkdir()
        _no_worker_thread(monkeypatch)
        w.answers.append(str(out))
        w.call("text_scenes.save_all")
        state = sb._bulk
        assert state is not None
        # A second press IS the cancel (the button doubles as one, like the
        # MP4 export and Rebuild previews).
        w.call("text_scenes.save_all")
        assert state["cancel"] is True
        written, skipped, err = sb._save_all_work(state)
        assert (written, skipped, err) == (0, 0, None)
        w.run(sb._save_all_done, state, state["out"], written, skipped, err)
        assert "Stopped" in w.state("text_scenes")["caption_full"]
        assert os.listdir(out) == []


def test_closing_the_window_stops_a_bulk_save(tmp_path):
    """It is the one background job here that writes files the user can see,
    so it must not keep dropping PNGs into a folder after the window is
    gone."""
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        bulk = {"cancel": False}

        def _arm():
            sb._bulk = bulk
        w.run(_arm)
        w.call("text_scenes.close")
        assert bulk["cancel"] is True


def _show(w, sb, layout):
    from PIL import Image
    w.run(sb._show_preview, sb._token, [Image.new("RGB", (320, 180))], [],
          layout)
    return w.state("text_scenes")


def test_the_caption_line_leads_with_what_the_preview_cannot_show(tmp_path):
    """PAD-81, from the two files the tester sent in for Venom 1.07's
    7f71ddb3: PAD's PNG of that scene is 327 sprites composited on top of one
    another, and the line under it read "Still picture: 200 images on a
    1360x768 stage." The window had ALREADY established that 309 images could
    not be placed and that the scene holds 327 screens to step through — both
    sentences were behind the "?" while the visible one said all was well.

    Through the real _show_preview, because the caption is the thing that
    was wrong; the full paragraph must still be on the tooltip."""
    pytest.importorskip("PIL")
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        layout = {"stage": [1360, 768, 30.0], "partial": True,
                  "unplaced": 309, "offstage": 0, "texts": [],
                  "sprites": [{"name": "a", "x": 10, "y": 10,
                               "image_off": 1}]}
        st = _show(w, sb, layout)

        assert st["caption"] == \
            "309 more images in this scene can't be placed yet."
        # The summary is not lost, only moved behind the "?".
        assert st["caption_full"].startswith("Still picture:")
        assert "can't be placed yet" in st["caption_full"]


def test_a_scene_with_nothing_to_admit_still_says_what_it_is(tmp_path):
    """The other half of the rule: with no caveat the line is the summary, so
    an ordinary scene reads exactly as it did before."""
    pytest.importorskip("PIL")
    with web_app(tmp_path, mfr="stern") as w:
        sb = _scene_window(w, tmp_path / "extract")
        layout = {"stage": [1360, 768, 30.0], "partial": False,
                  "unplaced": 0, "offstage": 0, "texts": [],
                  "sprites": [{"name": "a", "x": 10, "y": 10,
                               "image_off": 1}]}
        st = _show(w, sb, layout)
        assert st["caption"].startswith("Still picture:")
