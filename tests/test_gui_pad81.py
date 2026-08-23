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
see.  Every assertion here goes through the real command or the real handler,
and lands on a recorder standing in for the plugin / the desktop / the run.
"""

import os

import pytest

from tests.test_gui_smoke import app  # noqa: F401  (fixture)


def _stern(app, manufacturers_by_key):
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    return app.window


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


def test_only_the_file_rows_are_openable(app, manufacturers_by_key):
    """Section headers and count rows carry no ref, and the tab says so
    instead of swallowing the double-click."""
    win = _stern(app, manufacturers_by_key)
    win._compare_render(_SECTIONS)

    tree = win._compare_tree
    openable = set(win._compare_refs)
    assert len(openable) == 2
    # ...and they are marked, so the user can see which rows lead somewhere.
    for iid in openable:
        assert "openable" in tree.item(iid, "tags")
    for section in tree.get_children(""):
        assert section not in openable
        head = [k for k in tree.get_children(section)
                if tree.item(k, "text")]        # "Added:" / "Deleted:"
        assert head and not (set(head) & openable)

    win._compare_status.configure(text="")
    assert win._compare_open_target(tree.get_children("")[0]) is None
    assert "double-click one of the file rows" in \
        win._compare_status.cget("text")


def test_a_deleted_row_opens_image_a_and_the_rest_open_image_b(
        app, manufacturers_by_key, tmp_path):
    """THE SIDE IS THE WHOLE POINT.  A deleted file is on exactly one of the
    two cards; sending that row to image B would open nothing every time."""
    win = _stern(app, manufacturers_by_key)
    a = tmp_path / "a.raw"
    b = tmp_path / "b.raw"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    win.compare_a_var.set(str(a))
    win.compare_b_var.set(str(b))
    win._compare_render(_SECTIONS)

    got = {}
    for iid, ref in win._compare_refs.items():
        side, image, back = win._compare_open_target(iid)
        assert back is ref
        got[ref["name"]] = (side, image)
    assert got == {"new.png": ("B", str(b)), "old.png": ("A", str(a))}


def test_a_card_that_moved_says_so_rather_than_opening_nothing(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    win = _stern(app, manufacturers_by_key)
    win.compare_a_var.set(str(tmp_path / "gone.raw"))
    win.compare_b_var.set(str(tmp_path / "gone.raw"))
    win._compare_render(_SECTIONS)
    said = []
    monkeypatch.setattr("tkinter.messagebox.showerror",
                        lambda t, m, **k: said.append((t, m)))
    iid = next(iter(win._compare_refs))
    assert win._compare_open_target(iid) is None
    assert said and "no longer at" in said[0][1]


def test_the_opened_copy_is_handed_to_the_desktop(app, manufacturers_by_key,
                                                  tmp_path, monkeypatch):
    """The finish half: a success reports where it went, and a failure that
    reports nothing is the one outcome this must never produce."""
    win = _stern(app, manufacturers_by_key)
    from pinball_decryptor.core import desktop

    opened = []
    monkeypatch.setattr(desktop, "open_path",
                        lambda p, env=None: (opened.append(p), (True, ""))[1])
    win._compare_open_busy = True
    win._compare_open_finished("new.png", "B", str(tmp_path / "new.png"), None)
    assert opened == [str(tmp_path / "new.png")]
    assert win._compare_open_busy is False
    assert "Opened new.png from image B" in win._compare_status.cget("text")

    # A read that failed says which card it failed on, and unlatches the
    # one-at-a-time guard so the next double-click still works.
    said = []
    monkeypatch.setattr("tkinter.messagebox.showerror",
                        lambda t, m, **k: said.append(m))
    win._compare_open_busy = True
    win._compare_open_finished("old.png", "A", None,
                               FileNotFoundError("not on the card"))
    assert win._compare_open_busy is False
    assert said and "image A" in said[0] and "not on the card" in said[0]

    # So does a desktop that refuses to open it — with the path, so the user
    # can still get at the file.
    told = []
    monkeypatch.setattr(desktop, "open_path",
                        lambda p, env=None: (False, "no handler"))
    monkeypatch.setattr("tkinter.messagebox.showinfo",
                        lambda t, m, **k: told.append(m))
    win._compare_open_finished("new.png", "B", r"C:\tmp\new.png", None)
    assert told and "no handler" in told[0] and "new.png" in told[0]


# ---------------------------------------------------------------------------
# Compare tab: Extract Both
# ---------------------------------------------------------------------------

def test_extract_both_needs_two_different_real_images(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    win = _stern(app, manufacturers_by_key)
    asked = []
    monkeypatch.setattr(app, "_start_extract_both",
                        lambda a, b: asked.append((a, b)))
    win._on_extract_both = app._start_extract_both
    said = []
    for name in ("showinfo", "showerror"):
        monkeypatch.setattr("tkinter.messagebox." + name,
                            lambda t, m, **k: said.append(t))

    win.compare_a_var.set("")
    win.compare_b_var.set("")
    win._compare_extract_both()
    assert asked == [] and said == ["Pick two images"]

    card = tmp_path / "turtles_pro-1_58_0.raw"
    card.write_bytes(b"card")
    win.compare_a_var.set(str(card))
    win.compare_b_var.set(str(tmp_path / "not_there.raw"))
    win._compare_extract_both()
    assert asked == [] and said[-1] == "File not found"

    # The same card twice is one extract, not two.
    win.compare_b_var.set(str(card))
    win._compare_extract_both()
    assert asked == [] and said[-1] == "Same image twice"

    other = tmp_path / "turtles_pro-1_59_0.raw"
    other.write_bytes(b"card")
    win.compare_b_var.set(str(other))
    win._compare_extract_both()
    assert asked == [(str(card), str(other))]


def test_each_card_gets_a_folder_named_after_the_card(app):
    """A folder called "A" tells you nothing three days later; the card name
    already carries the title and the version."""
    f = app._extract_both_folder
    assert f(r"C:\out", r"D:\img\turtles_pro-1_58_0.Release.8G.sdcard.raw",
             r"D:\img\turtles_pro-1_59_0.Release.8G.sdcard.raw") \
        == os.path.join(r"C:\out", "turtles_pro-1_58_0.Release.8G.sdcard")
    # Two cards with the SAME filename in different folders would otherwise
    # land on one folder and the second run would extract over the first.
    one = f(r"C:\out", os.path.join("D:", "stock", "card.raw"),
            os.path.join("D:", "modded", "card.raw"))
    two = f(r"C:\out", os.path.join("D:", "modded", "card.raw"),
            os.path.join("D:", "stock", "card.raw"))
    assert one != two
    assert one.endswith("card (stock)") and two.endswith("card (modded)")


def test_the_second_card_is_queued_only_once_the_first_run_started(
        app, manufacturers_by_key, tmp_path, monkeypatch):
    """_start_extract bails out at half a dozen guards (no output folder, an
    overwrite the user declines, nothing ticked).  A chain left armed by one
    of those would fire card B onto the end of a later, unrelated extract."""
    win = _stern(app, manufacturers_by_key)
    a = tmp_path / "lz-1_20_0.raw"
    b = tmp_path / "lz-1_22_0.raw"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    monkeypatch.setattr("tkinter.filedialog.askdirectory",
                        lambda **k: str(tmp_path / "both"))

    monkeypatch.setattr(app, "_start_extract", lambda: None)   # never starts
    app._start_extract_both(str(a), str(b))
    assert app._chain_extract_next is None
    assert win.extract_input_var.get() == str(a)
    assert win.extract_output_var.get() == str(tmp_path / "both" / "lz-1_20_0")
    # A card image is a file: an Extract Both left on "From SSD" would send
    # _start_extract down the physical-device branch with a path that is not
    # a device.
    assert win.extract_input_source_var.get() == "iso"

    # A card image is a file: an Extract Both left on "From SSD" would send
    # _start_extract down the physical-device branch with a path that is not
    # a device.
    assert win.extract_input_source_var.get() == "iso"

    def _started():
        app.pipeline = object()
    monkeypatch.setattr(app, "_start_extract", _started)
    app._start_extract_both(str(a), str(b))
    assert app._chain_extract_next == (
        str(b), str(tmp_path / "both" / "lz-1_22_0"))
    # The source flip queues a notebook re-size with after_idle; run it here
    # or the fixture destroys the widget with the idle callback still
    # registered ("can't delete Tcl command" at teardown).
    app.root.update()


def test_a_finished_first_card_starts_the_second(app, manufacturers_by_key,
                                                 tmp_path, monkeypatch):
    _stern(app, manufacturers_by_key)
    ran = []
    monkeypatch.setattr(app, "_run_chained_extract",
                        lambda i, o: ran.append((i, o)))
    app._active_mode = "extract"
    app._last_extract_io = None
    app._chain_extract_next = (str(tmp_path / "b.raw"), str(tmp_path / "outb"))
    app._on_done(True, "Extract complete")
    app.root.update()                # the chain is armed with after(0, …)
    assert ran == [(str(tmp_path / "b.raw"), str(tmp_path / "outb"))]
    assert app._chain_extract_next is None

    # A FAILED first card drops the pair; the second must not ride on
    # whatever run finishes next.
    ran.clear()
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: None)
    app._active_mode = "extract"
    app._chain_extract_next = (str(tmp_path / "b.raw"), str(tmp_path / "outb"))
    app._on_done(False, "Extract failed")
    app.root.update()
    assert ran == []
    assert app._chain_extract_next is None


# ---------------------------------------------------------------------------
# Scenes window: save every listed preview
# ---------------------------------------------------------------------------

def _scene_window(app, tmp_path, scenes=("scene1", "scene2", "scene9")):
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
    win = app.window
    win.write_assets_var.set(str(tmp_path))
    win._open_scene_browser()
    return win._scene_browser


def _run_bulk(sb, out, monkeypatch):
    """Click "Save all previews…" for real, then run the two halves the
    worker thread would have.

    THE BUTTON IS PART OF THE TEST — a command wired to nothing is exactly
    what a screenshot cannot see.  The thread is not: a worker cannot reach Tk
    outside ``mainloop()`` at all, so the hop is exercised by calling
    ``_save_all_work`` and ``_save_all_done`` in order, which is what the
    Scenes window's own render tests already do.
    """
    monkeypatch.setattr("tkinter.filedialog.askdirectory",
                        lambda **k: str(out))
    sb._save_all_btn.invoke()
    state = sb._bulk
    assert state is not None, "the button did not start a batch"
    assert str(sb._save_all_btn.cget("text")) == "Cancel"
    written, skipped, err = sb._save_all_work(state)
    sb._save_all_done(state, state["out"], written, skipped, err)
    return written, skipped


def test_save_all_previews_writes_one_png_per_listed_scene(app, tmp_path,
                                                           monkeypatch):
    sb = _scene_window(app, tmp_path / "extract")
    out = tmp_path / "shots"
    out.mkdir()
    written, skipped = _run_bulk(sb, out, monkeypatch)

    assert (written, skipped) == (3, 0)
    assert sb._bulk is None
    assert str(sb._save_all_btn.cget("text")) == "Save all previews…"
    names = sorted(os.listdir(out))
    assert len(names) == 3, names
    assert all(n.lower().endswith(".png") for n in names)
    assert "Saved 3 previews" in sb._caption_tip.text
    assert "first frame of each" in sb._caption_tip.text


def test_the_search_box_narrows_the_batch(app, tmp_path, monkeypatch):
    """The list is the batch — silently exporting the scenes the user just
    filtered out is the same surprise as extra work nobody asked for."""
    sb = _scene_window(app, tmp_path / "extract")
    listed = list(sb._tree.get_children(""))
    assert len(listed) == 3
    sb._search_var.set(sb._scenes[listed[0]]["label"])
    sb.app._tk_root().update()
    assert len(sb._tree.get_children("")) == 1

    out = tmp_path / "one"
    out.mkdir()
    assert _run_bulk(sb, out, monkeypatch) == (1, 0)
    assert len(os.listdir(out)) == 1


def test_two_scenes_that_sanitise_alike_do_not_overwrite_each_other():
    """An overwrite there would silently drop a scene from a folder that
    claims to hold them all."""
    from pinball_decryptor.gui.scene_browser import _safe_stem, _unique_png

    used = set()
    assert _unique_png("Game · Intro", used) == "Game___Intro.png"
    assert _unique_png("Game / Intro", used) == "Game___Intro_2.png"
    assert _unique_png("Game ? Intro", used) == "Game___Intro_3.png"
    assert _safe_stem("") == "scene"
    assert _safe_stem("///") == "___"


def test_a_scene_with_no_layout_is_counted_not_guessed_at(app, tmp_path,
                                                          monkeypatch):
    """A folder of 2 PNGs from a 3-scene list has to say what happened to the
    third."""
    sb = _scene_window(app, tmp_path / "extract")
    sb._layouts = {k: v for k, v in sb._layouts.items()
                   if not k.endswith("/g/scene9/scene.radium")}
    out = tmp_path / "partial"
    out.mkdir()
    assert _run_bulk(sb, out, monkeypatch) == (2, 1)
    assert len(os.listdir(out)) == 2
    assert "1 scene could not be drawn" in sb._caption_tip.text


def test_a_cancelled_batch_reports_what_it_did_write(app, tmp_path,
                                                     monkeypatch):
    """Cancel stops the batch; it does not pretend the folder is empty."""
    sb = _scene_window(app, tmp_path / "extract")
    out = tmp_path / "stopped"
    out.mkdir()
    monkeypatch.setattr("tkinter.filedialog.askdirectory",
                        lambda **k: str(out))
    sb._save_all_btn.invoke()
    state = sb._bulk
    # A second press IS the cancel (the button doubles as one, like the MP4
    # export and Rebuild previews).
    sb._save_all_btn.invoke()
    assert state["cancel"] is True
    written, skipped, err = sb._save_all_work(state)
    assert (written, skipped, err) == (0, 0, None)
    sb._save_all_done(state, state["out"], written, skipped, err)
    assert "Stopped" in sb._caption_tip.text
    assert os.listdir(out) == []


def test_closing_the_window_stops_a_bulk_save(app, tmp_path):
    """It is the one background job here that writes files the user can see,
    so it must not keep dropping PNGs into a folder after the window is
    gone."""
    sb = _scene_window(app, tmp_path / "extract")
    sb._bulk = {"cancel": False}
    sb._close()
    assert sb._bulk["cancel"] is True
