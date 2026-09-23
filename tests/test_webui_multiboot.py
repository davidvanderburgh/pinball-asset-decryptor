"""The web Multi-boot tab: multiboot_core's panel behind the page.

Every test runs with PAD_UI_NO_RIG=1 (the harness sets it) and with the
automatic preview and size check off, and asserts no tool process is ever
started: the rig is not touched."""

import os
import subprocess
import types

import pytest

from tests.webui_harness import web_app


@pytest.fixture(autouse=True)
def _no_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_MULTIBOOT_AUTO", "0")
    monkeypatch.setenv("PAD_MULTIBOOT_PLAN", "0")
    monkeypatch.setenv("PAD_MULTIBOOT_PROBE", "0")
    from pinball_decryptor.webui import multiboot_panel as mbp

    def refuse(*a, **k):
        raise AssertionError("a tool was started: %r" % (a,))
    # the panel's own worker is the only place its tools are started
    monkeypatch.setitem(mbp._GLOBALS, "subprocess",
                        types.SimpleNamespace(Popen=refuse,
                                              PIPE=subprocess.PIPE,
                                              STDOUT=subprocess.STDOUT))
    # the preview's volume file lives beside the real settings: keep it here
    monkeypatch.setitem(mbp._GLOBALS, "PREVIEW_AUDIO_CTL_FILE",
                        str(tmp_path / "preview_audio_ctl.json"))
    monkeypatch.setattr(mbp.mt, "PREVIEW_AUDIO_CTL_FILE",
                        str(tmp_path / "preview_audio_ctl.json"))


def _raw(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\0" * 16)
    return str(p)


def _add(w, path):
    w.answers.append(path)
    w.call("multiboot.add_choice", "_add_image")
    w.drain()


def _st(w):
    w.drain()
    w.drain()
    return w.state("multiboot")


def _panel(w):
    return w.window._multiboot_panel


# ------------------------------------------------------------ manufacturers
def test_stern_words_and_gating(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["multiboot"]["visible"]
        s = _st(w)
        assert s["w"]["platform"] == "stern"
        assert s["w"]["out_label"] == "Multi-boot card image:"
        assert s["w"]["build_text"] == "Build / flash card…"
        assert s["w"]["read_card"] and s["w"]["extract"] and s["w"]["compact"]
        assert s["w"]["add_text"] == "Add image or random…"
        assert [c["label"] for c in s["checks"]] == [
            "Card image", "Images", "Built", "Ready to flash"]
        assert s["rows"] == [] and s["dlg"] is None
        assert s["preview"]["placeholder"].startswith(
            "The boot menu is drawn here")
        assert "Browse… to a card you already built" in s["message"]
        assert w.window._multiboot_panel is _panel(w)


def test_jjp_words_and_gating(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["multiboot"]["visible"]
        s = _st(w)
        w_ = s["w"]
        assert w_["platform"] == "jjp"
        assert w_["out_label"] == "Multi-boot install ISO:"
        assert w_["build_text"] == "Build / make stick…"
        assert w_["add_text"] == "Add the second ISO…"
        assert not (w_["read_card"] or w_["extract"] or w_["compact"]
                    or w_["groups"] or w_["machine_volume"])
        assert w_["volume_max"] == 40
        assert [c["label"] for c in s["checks"]] == [
            "Install ISO", "Images", "Built", "Ready for the stick"]
        # a JJP install has no random cards
        assert [c["attr"] for c in s["add_choices"]] == ["_add_image"]


@pytest.mark.parametrize("era", ["spike1", "whitestar"])
def test_tab_follows_the_capability_per_era(tmp_path, era):
    with web_app(tmp_path, mfr="stern", era=era) as w:
        mfr = w.window.current_mfr
        want = bool(getattr(mfr.capabilities, "multiboot", False))
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["multiboot"]["visible"] == want


def test_every_manufacturer_gates_the_tab_by_its_capability(tmp_path):
    with web_app(tmp_path) as w:
        hidden = 0
        for m in list(w.window.manufacturers):
            w.call("ui.pick_manufacturer", m.key)
            w.drain()
            want = bool(getattr(w.window.current_mfr.capabilities,
                                "multiboot", False))
            tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
            assert tabs["multiboot"]["visible"] == want, m.key
            hidden += not want
        assert hidden, "no manufacturer without a multi-boot tab?"


def test_switching_to_jjp_clears_a_stern_form(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        assert len(_st(w)["rows"]) == 1
        w.call("ui.pick_manufacturer", "jjp")
        s = _st(w)
        assert s["w"]["platform"] == "jjp" and s["rows"] == []


# ------------------------------------------------------------ the export
def test_state_and_restore_round_trip_through_app(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        doc = w.run(lambda: w.app.multiboot_state())
        assert doc["v"] == 1 and len(doc["images"]) == 2
        assert doc["card"].endswith("a_pro-1_59_0.Release.8G.sdcard.multi.raw")
        # the heading is Menu settings' (a field of that dialog only)
        w.call("multiboot.menu_settings")
        w.call("ui.set", "multiboot", "heading", "PICK ONE")
        w.call("multiboot.menu_ok")
        doc = w.run(lambda: _panel(w).state())
        assert doc["menu"]["heading"] == "PICK ONE"
        # a fresh form, then the document back: nothing runs, form returns
        w.answers.append("yes")
        w.call("multiboot.new_card")
        assert _st(w)["rows"] == []
        assert w.run(lambda: _panel(w).restore_state(doc)) is True
        s = _st(w)
        assert [r["title"] for r in s["rows"]] == ["a_pro-1_59_0",
                                                   "b_pro-1_59_0"]
        assert s["heading"] == "PICK ONE"
        assert s["message"] == ("2 images and the menu came back from last "
                                "time.")
        assert s["card"] == doc["card"]


# ------------------------------------------------------------ the saved form
_NO_KEY = object()


def _saved_doc(tmp_path):
    """A v1 form over two images, as the Tk tab's state() writes it."""
    from dataclasses import asdict
    from pinball_decryptor.webui import multiboot_core as mt
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    return {"v": 1, "card": str(tmp_path / "multi" / "two.multi.raw"),
            "images": [asdict(mt.ImageRow(path=a, title="ALPHA",
                                          subtitle="One")),
                       asdict(mt.ImageRow(path=b, title="BRAVO"))],
            "menu": {"heading": "PICK A GAME"}}


def _project_settings(tmp_path, doc, anchor_multiboot=_NO_KEY):
    """A Stern project folder (anchor format 2) the app reopens at startup,
    and settings whose GLOBAL multiboot_state is *doc*."""
    from pinball_decryptor.core import project_file
    folder = tmp_path / "proj"
    folder.mkdir()
    project_file.save(project_file.anchor_path(str(folder)),
                      manufacturer_key="stern",
                      paths={"extract_output": str(folder),
                             "write_assets": str(folder)},
                      extract_options={})
    if anchor_multiboot is not _NO_KEY:
        assert project_file.update_anchor(str(folder),
                                          multiboot=anchor_multiboot)
    settings = {"last_manufacturer": "stern",
                "manufacturers": {"stern": {"extract_output": str(folder),
                                            "write_assets": str(folder)}},
                "multiboot_state": doc}
    return str(folder), settings


def _anchor_multiboot(folder):
    from pinball_decryptor.core import project_file
    return project_file.load_anchor(folder).get("multiboot", _NO_KEY)


def test_startup_restores_the_global_form_when_the_anchor_has_none(tmp_path):
    doc = _saved_doc(tmp_path)
    folder, settings = _project_settings(tmp_path, doc)
    with web_app(tmp_path, settings=settings) as w:
        assert w.app._project_path and os.path.samefile(w.app._project_path,
                                                        folder)
        s = _st(w)
        assert s["card"] == doc["card"]
        assert [r["title"] for r in s["rows"]] == ["ALPHA", "BRAVO"]
        # opening the tab (Tk's on_shown: the card is read then, and there
        # is none at that path) keeps the form
        w.call("ui.select_tab", "multiboot")
        s = _st(w)
        assert s["card"] == doc["card"]
        assert [r["title"] for r in s["rows"]] == ["ALPHA", "BRAVO"]
        assert _panel(w).state()["menu"]["heading"] == "PICK A GAME"


def test_a_projects_empty_form_wins(tmp_path):
    """The gzho case: an anchor whose multiboot is {} means "this project's
    tab is empty" (App.restore_multiboot_state) - Tk opens it empty too."""
    doc = _saved_doc(tmp_path)
    folder, settings = _project_settings(tmp_path, doc, anchor_multiboot={})
    with web_app(tmp_path, settings=settings) as w:
        s = _st(w)
        assert s["rows"] == [] and s["card"] == ""
        w.call("ui.select_tab", "multiboot")
        s = _st(w)
        assert s["rows"] == [] and s["card"] == ""


@pytest.mark.parametrize("how", ["import", "construct"])
def test_quit_without_the_panel_keeps_the_saved_form(tmp_path, monkeypatch,
                                                     how):
    """A build whose Multi-boot panel cannot load (import error) or cannot be
    built must not write {} over the project's form on the way out: the
    tab is still built, and hands back the form it was given."""
    from pinball_decryptor.webui.tabs import multiboot as tab_mod
    if how == "import":
        monkeypatch.setattr(tab_mod, "mbp", None)
        monkeypatch.setattr(tab_mod, "_PANEL_IMPORT_ERROR",
                            ImportError("No module named 'PIL'"))
    else:
        def boom(self, *a, **k):
            raise RuntimeError("the panel broke")
        monkeypatch.setattr(tab_mod.mbp.WebMultibootPanel, "__init__", boom)
    doc = _saved_doc(tmp_path)
    folder, settings = _project_settings(tmp_path, doc, anchor_multiboot=doc)
    with web_app(tmp_path, settings=settings) as w:
        panel = w.window._multiboot_panel
        assert isinstance(panel, tab_mod._SavedForm)
        s = w.state("multiboot")
        assert s["broken"].startswith("The Multi-boot tab could not start")
        with pytest.raises(Exception):
            w.call("multiboot.build_flash")
        assert w.run(lambda: w.app.multiboot_state()) == doc
        assert panel.image_titles() == ["ALPHA", "BRAVO"]
        # the quit's flush runs when anything in the anchor changed
        w.run(lambda: w.window.emulate_card_var.set(str(tmp_path / "c.raw")))
        w.run(w.app._save_session_state)
        assert _anchor_multiboot(folder) == doc
        # ...and a project switch's save of the outgoing folder
        w.run(lambda: w.app.save_multiboot_state(folder))
        assert _anchor_multiboot(folder) == doc
        with open(os.path.join(str(tmp_path), "cfg", "settings.json"),
                  encoding="utf-8") as f:
            import json
            assert json.load(f)["multiboot_state"] == doc


def test_quit_with_the_panel_writes_the_restored_form_back(tmp_path):
    doc = _saved_doc(tmp_path)
    folder, settings = _project_settings(tmp_path, doc, anchor_multiboot=doc)
    with web_app(tmp_path, settings=settings) as w:
        w.run(lambda: w.window.emulate_card_var.set(str(tmp_path / "c.raw")))
        w.run(w.app._save_session_state)
        saved = _anchor_multiboot(folder)
        assert saved["card"] == doc["card"]
        assert [r["title"] for r in saved["images"]] == ["ALPHA", "BRAVO"]
        assert saved["menu"]["heading"] == "PICK A GAME"


# ------------------------------------------------------------ the list
def test_add_images_fills_path_checks_and_flippers(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        s = _st(w)
        assert s["rows"][0]["title"] == "a_pro-1_59_0"
        assert s["rows"][0]["sub"] == "Release"
        assert s["card"] == os.path.join(
            str(tmp_path), "multi", "a_pro-1_59_0.Release.8G.sdcard.multi.raw")
        assert not s["flippers"]
        checks = {c["key"]: c for c in s["checks"]}
        assert checks["images"]["state"] == "bad"
        # the random choices say why they are not there yet
        why = {c["attr"]: c for c in s["add_choices"]}
        assert not why["_add_random_over_existing"]["enabled"]
        assert "(add two images first)" in why[
            "_add_random_over_existing"]["label"]
        _add(w, b)
        s = _st(w)
        assert len(s["rows"]) == 2 and s["flippers"] and s["sel"] == 1
        checks = {c["key"]: c for c in s["checks"]}
        assert checks["images"]["state"] == "ok"
        assert checks["images"]["label"] == "2 images"
        assert s["row_line"] == b
        assert s["preview"]["sketch"]["cards"][1]["title"] == "b_pro-1_59_0"


def test_random_group_locks_compact(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        assert not _st(w)["compact"]
        w.call("multiboot.add_choice", "_add_random_over_existing")
        s = _st(w)
        assert len(s["rows"]) == 3 and s["rows"][2]["group"]
        assert s["rows"][2]["title"] == "RANDOM"
        assert "(random, 2 sets)" in s["rows"][2]["suffix"]
        assert s["compact"] is True and s["compact_locked"]
        assert "a random group needs it" in s["compact_tip"]
        # removing the group unlocks the tick again
        w.call("multiboot.row_action", 2, "del")
        s = _st(w)
        assert len(s["rows"]) == 2 and not s["compact_locked"]


def test_group_from_folder_and_random_picker(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    songs = tmp_path / "songs"
    songs.mkdir()
    for n in ("s1.raw", "s2.raw"):
        (songs / n).write_bytes(b"x")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.answers.append(str(songs))
        w.call("multiboot.add_choice", "_add_group_folder")
        s = _st(w)
        assert s["rows"][1]["title"] == "SONGS" and s["rows"][1]["group"]
        asked = w.asked[-1]
        assert asked["kind"] == "file" and asked["mode"] == "folder"
        assert asked["title"] == ("Pick a folder of card images for one "
                                  "random card")


def test_move_and_remove(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.row_action", 1, "up")
        s = _st(w)
        assert [r["title"] for r in s["rows"]] == ["b_pro-1_59_0",
                                                   "a_pro-1_59_0"]
        assert s["sel"] == 0 and not s["rows"][0]["up"]
        # moving row 0 re-derives the default output path
        assert s["card"].endswith("b_pro-1_59_0.Other.8G.sdcard.multi.raw")
        w.call("multiboot.list_action", "_move_down", 0)
        assert [r["title"] for r in _st(w)["rows"]] == ["a_pro-1_59_0",
                                                        "b_pro-1_59_0"]
        w.call("multiboot.row_action", 0, "del")
        assert [r["title"] for r in _st(w)["rows"]] == ["b_pro-1_59_0"]


def test_new_card_asks_first(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.answers.append("no")
        w.call("multiboot.new_card")
        assert w.asked[-1]["title"] == "New card?"
        assert len(_st(w)["rows"]) == 1
        w.answers.append("yes")
        w.call("multiboot.new_card")
        s = _st(w)
        assert s["rows"] == [] and s["card"] == ""
        assert s["message"] == ("A new card: add the primary (stock) image "
                                "and one more.")


# ------------------------------------------------------------ Edit image…
def test_edit_dialog_writes_through_and_cancel_restores(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        # a click on row 0's text opens ITS editor, holding ITS fields
        w.call("multiboot.cell_clicked", 0)
        s = _st(w)
        assert s["dlg"] == "edit"
        assert s["ed"]["title"] == ("Edit image 0 — "
                                    "a_pro-1_59_0.Release.8G.sdcard.raw")
        assert s["ed_title"] == "a_pro-1_59_0"
        assert [k["value"] for k in s["ed"]["kinds"]] == [
            "logo", "picture", "attract", "video", "none"]
        w.call("ui.set", "multiboot", "ed_title", "STOCK")
        s = _st(w)
        assert s["rows"][0]["title"] == "STOCK"
        assert s["ed"]["card"]["title"] == "STOCK"
        w.call("multiboot.edit_cancel")
        s = _st(w)
        assert s["dlg"] is None and s["rows"][0]["title"] == "a_pro-1_59_0"
        # OK keeps it, and 'none' shows text only
        w.call("multiboot.edit", 0)
        w.call("ui.set", "multiboot", "ed_title", "STOCK")
        w.call("ui.set", "multiboot", "ed_media", "none")
        s = _st(w)
        assert s["ed"]["note"].startswith("Text only")
        assert s["ed"]["card"]["note"] == ("This card shows its text and "
                                           "nothing else.")
        w.call("multiboot.edit_ok")
        s = _st(w)
        assert s["dlg"] is None and s["rows"][0]["title"] == "STOCK"
        assert s["rows"][0]["media"] == "none"


def test_a_late_edit_after_cancel_is_dropped(tmp_path):
    """The field's debounce (or its blur) can land after Cancel / Escape put
    the row back: in Tk nothing reaches a dialog that has gone."""
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.edit", 0)
        w.call("ui.set", "multiboot", "ed_title", "X")
        assert _st(w)["rows"][0]["title"] == "X"
        w.call("multiboot.edit_cancel")
        for key, value in (("ed_title", "LATE"), ("ed_sub", "LATE"),
                           ("ed_media", "none"), ("ed_music", "late.wav")):
            w.call("ui.set", "multiboot", key, value)
        s = _st(w)
        assert s["dlg"] is None
        assert s["rows"][0]["title"] == "a_pro-1_59_0"
        assert s["rows"][0]["sub"] == "Release"
        row = _panel(w)._rows[0]
        assert (row.title, row.subtitle, row.music) == ("a_pro-1_59_0",
                                                        "Release", "none")
        assert w.call("multiboot.edit_browse", "picture") is False
        assert w.call("multiboot.sound_browse", "ed_music") is False
        # and a late edit after OK does not reach the row either
        w.call("multiboot.edit", 1)
        w.call("ui.set", "multiboot", "ed_title", "KEPT")
        w.call("multiboot.edit_ok")
        w.call("ui.set", "multiboot", "ed_title", "LATE")
        assert _st(w)["rows"][1]["title"] == "KEPT"


def test_edit_random_card_how_it_picks(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.add_choice", "_add_random_over_existing")
        w.call("multiboot.cell_clicked", 2)
        s = _st(w)
        assert s["ed"]["group"] and s["ed"]["title"] == (
            "Edit random card 2 — 2 games")
        assert s["ed_title"] == "RANDOM"
        assert not s["ed"]["roll_locked"]
        w.call("ui.set", "multiboot", "ed_roll", "shuffle")
        s = _st(w)
        # a shuffle never repeats the last one: the tick is forced and greyed
        assert s["ed"]["roll_locked"] and s["ed_roll_norepeat"] is True
        w.call("multiboot.edit_ok")
        assert _panel(w)._rows[2].roll == "shuffle"


def test_picture_browse_picks_the_option(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    pic = tmp_path / "logo.png"
    from PIL import Image
    Image.new("RGB", (32, 18), (200, 30, 30)).save(pic)
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.call("multiboot.edit", 0)
        w.answers.append(str(pic))
        w.call("multiboot.edit_browse", "picture")
        s = _st(w)
        assert s["ed_media"] == "picture" and s["ed_picture"] == str(pic)
        assert s["ed"]["card"]["img"] == os.path.abspath(str(pic))
        assert s["ed"]["card"]["note"] == "Your picture, fitted to the card."
        w.call("multiboot.edit_ok")
        assert _st(w)["rows"][0]["media"] == "logo.png"


# ------------------------------------------------------------ Menu settings…
def test_menu_settings_cancel_restores_and_theme(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.call("multiboot.menu_settings")
        s = _st(w)
        assert s["dlg"] == "menu"
        assert s["md"]["theme"] == "midnight" and not s["md"]["custom"]
        assert s["md"]["example"] == "starting a_pro-1_59_0 in 15 s"
        w.call("ui.set", "multiboot", "heading", "")
        w.call("ui.set", "multiboot", "timeout", "0")
        s = _st(w)
        assert s["md"]["example"] == "no countdown - the menu waits for START"
        assert "no heading" in s["summary"] and "wait for START" in s["summary"]
        w.call("multiboot.menu_cancel")
        s = _st(w)
        assert s["dlg"] is None and s["heading"] == "SELECT GAME CODE"
        assert s["timeout"] == "15"
        # Make your own…: the swatches edit, a bad value is flagged
        w.call("multiboot.menu_settings")
        assert w.call("multiboot.set_color", "background", "#112233") is False
        w.call("multiboot.pick_theme", "custom")
        assert w.call("multiboot.set_color", "background", "#112233") is True
        w.call("ui.set", "multiboot", "color_heading", "zz")
        s = _st(w)
        assert s["md"]["custom"]
        cols = {c["role"]: c for c in s["md"]["colors"]}
        assert cols["background"]["hex"] == "112233"
        assert not cols["heading"]["ok"]
        w.call("multiboot.menu_ok")
        s = _st(w)
        assert "theme custom" in s["summary"]
        assert s["summary_groups"][0][0] == "Menu"


def test_a_late_menu_edit_after_cancel_is_dropped(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        before = _st(w)["summary"]
        w.call("multiboot.menu_settings")
        w.call("ui.set", "multiboot", "heading", "SELECT GAME CODE ZZ")
        assert _st(w)["heading"] == "SELECT GAME CODE ZZ"
        w.call("multiboot.menu_cancel")
        for key, value in (("heading", "LATE"), ("timeout", "0"),
                           ("volume", "1"), ("default", "0"),
                           ("color_heading", "ff0000")):
            w.call("ui.set", "multiboot", key, value)
        assert w.call("multiboot.pick_theme", "custom") is False
        assert w.call("multiboot.set_color", "heading", "#00ff00") is False
        s = _st(w)
        assert s["dlg"] is None and s["heading"] == "SELECT GAME CODE"
        assert s["timeout"] == "15" and s["summary"] == before
        doc = _panel(w).state()["menu"]
        assert doc["heading"] == "SELECT GAME CODE" and doc["timeout"] == 15
        assert doc["theme"] == "midnight"


def test_menu_settings_number_bounds_are_published(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.menu_settings")
        s = _st(w)
        assert s["md"]["default_max"] == 1       # Tk's Spinbox 0..images-1
        assert s["w"]["volume_max"] == 100
    with web_app(tmp_path / "j", mfr="jjp") as w:
        assert _st(w)["w"]["volume_max"] == 40


# ------------------------------------------------------------ Build / flash
def test_build_dialog_plans_a_fresh_card_and_no_rig_refuses(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.build_flash")
        s = _st(w)
        assert s["dlg"] == "build"
        bf = s["bf"]
        assert bf["write_label"] == ("Build a fresh card at "
                                     "a_pro-1_59_0.Release.8G.sdcard.multi.raw")
        assert bf["can_write"] and bf["write"] and not bf["flash"]
        assert bf["action"] == "build"
        w.call("multiboot.build_tick", "flash", True)
        assert _st(w)["bf"]["flash"]
        w.call("multiboot.build_start")
        s = _st(w)
        assert s["dlg"] is None
        assert "PAD_UI_NO_RIG" in s["message"]
        assert not s["busy"] and s["build_mode"] == "build"


def test_build_refuses_without_images(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("multiboot.build_flash")
        bf = _st(w)["bf"]
        assert not bf["can_write"] and not bf["write"]
        assert bf["write_detail"] == "Add at least one image first."
        w.call("multiboot.build_cancel")
        assert _st(w)["dlg"] is None


def test_run_in_emulator_needs_a_card(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.call("multiboot.run_emulator")
        assert _st(w)["message"].startswith("Build the card first - nothing at ")


def test_run_in_emulator_hands_the_card_to_the_emulate_tab(tmp_path,
                                                          monkeypatch):
    card = _raw(tmp_path, "c.multi.raw")
    with web_app(tmp_path, mfr="stern") as w:
        seen = []
        target = getattr(w.window, "_emulate_panel", None)             or w.window.service("emulate")
        monkeypatch.setattr(target, "launch_card",
                            lambda p, select=False: seen.append((p, select)),
                            raising=False)
        w.call("ui.set", "multiboot", "card", card)
        w.call("multiboot.run_emulator")
        _st(w)
        assert seen == [(card, True)]
        assert w.state("shell")["tab"] == "emulate"


def test_flash_goes_to_the_write_tabs_dialog(tmp_path, monkeypatch):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    card = _raw(tmp_path, "c.multi.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        svc = w.window.service("write")
        if getattr(svc, "_open_flash_dialog", None) is None:
            w.call("ui.set", "multiboot", "card", card)
            w.run(lambda: _panel(w)._flash(fresh=True))
            assert "flash dialog is not available" in _st(w)["message"]
            return
        seen = []
        monkeypatch.setattr(
            svc, "_open_flash_dialog",
            lambda initial_image=None, fresh=False, image_titles=None:
            seen.append((initial_image, fresh, image_titles)))
        w.call("ui.set", "multiboot", "card", card)
        # the Build / flash dialog's flash tick alone: straight to the card
        w.call("multiboot.build_flash")
        w.call("multiboot.build_tick", "write", False)
        w.call("multiboot.build_tick", "flash", True)
        w.call("multiboot.build_start")
        _st(w)
        assert seen == [(card, False, ["a_pro-1_59_0"])]


# ------------------------------------------------------------ the card row
def test_browse_new_name_only_fills_the_box(tmp_path):
    target = str(tmp_path / "new.multi.raw")
    with web_app(tmp_path, mfr="stern") as w:
        w.answers.append(target)
        w.call("multiboot.browse")
        assert w.asked[-1]["title"] == ("The card to read, or where to build "
                                        "a new one")
        assert _st(w)["card"] == target


def test_browse_existing_card_asks_then_reads(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    card = _raw(tmp_path, "old.multi.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        w.answers.extend([card, "yes"])
        w.call("multiboot.browse")
        titles = [q.get("title") for q in w.asked]
        assert "Read this card?" in titles
        # the read itself is a tool run, refused with the rig off
        assert "PAD_UI_NO_RIG" in _st(w)["message"]


def test_browse_never_asks_replace_in_the_desktop_window(tmp_path):
    """Browse… picks a card to READ as often as a place to build one, so
    Tk passed confirmoverwrite=False; the desktop window's native save
    panels ask "replace?" regardless, so this one picker is the page's."""
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    target = str(tmp_path / "new.multi.raw")
    with web_app(tmp_path, mfr="stern") as w:
        native = []

        def fake_native(spec):
            native.append(spec)
            return a
        w.ctx.dialogs.native_file_dialog = fake_native
        w.answers.append(target)
        w.call("multiboot.browse")
        assert native == []
        spec = w.asked[-1]
        assert spec["kind"] == "file" and spec["mode"] == "save"
        assert spec["confirmoverwrite"] is False
        assert spec["title"] == ("The card to read, or where to build a new "
                                 "one")
        assert _st(w)["card"] == target
        # every other picker on the tab is still the native one
        w.call("multiboot.add_choice", "_add_image")
        assert [n["mode"] for n in native] == ["open"]
        assert _st(w)["rows"][0]["title"] == "a_pro-1_59_0"
        # a host whose picker honours the flag gets the question back
        fake_native.honours_confirmoverwrite = True
        w.call("multiboot.browse")
        assert [n["mode"] for n in native] == ["open", "save"]
        assert native[-1]["confirmoverwrite"] is False


def test_path_enter_on_a_missing_path_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_MULTIBOOT_PROBE", "1")      # a local stat only
    target = str(tmp_path / "nothing.raw")
    with web_app(tmp_path, mfr="stern") as w:
        before = _st(w)["message"]
        w.call("ui.set", "multiboot", "card", target)
        import time
        for _ in range(100):
            if _panel(w)._probe_for == target:
                break
            time.sleep(0.05)
        assert _panel(w)._probe_facts.get("kind") == "missing"
        w.call("multiboot.path_enter", target)
        s = _st(w)
        assert s["card"] == str(tmp_path / "nothing.raw")
        assert s["message"] == before


def test_card_reader_dialog(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        class D:
            display = "E:  Reader 32 GB"
            device_path = r"\\.\PhysicalDrive9"
            model, size_bytes = "Reader", 32 * 10 ** 9
        d = D()
        _panel(w)._card_drives = lambda: ([d], d, "The reader.")
        w.call("multiboot.from_card")
        import time
        for _ in range(50):
            s = _st(w)
            if s["cp"] and not s["cp"]["looking"]:
                break
            time.sleep(0.05)
        assert s["dlg"] == "cardpick"
        assert s["cp"]["drives"] == ["E:  Reader 32 GB"]
        assert s["cp"]["picked"] == 0 and s["cp"]["mode"] == "menu"
        w.call("multiboot.cardpick_pick", None, "whole")
        assert _st(w)["cp"]["mode"] == "whole"
        w.call("multiboot.cardpick_pick", None, "menu")
        w.call("multiboot.cardpick_read")
        s = _st(w)
        assert s["dlg"] is None and "PAD_UI_NO_RIG" in s["message"]


# ------------------------------------------------------------ the preview
def test_flippers_wrap_and_move_the_selection(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.select", 0)
        _st(w)
        w.call("multiboot.flip", -1)            # off image 0 wraps to the last
        s = _st(w)
        assert s["sel"] == 1 and s["preview"]["hl"] == 1
        w.call("multiboot.flip", 1)
        s = _st(w)
        assert s["sel"] == 0 and s["preview"]["hl"] == 0


def test_a_rendered_frame_is_shown_with_its_clips(tmp_path):
    from PIL import Image
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Other.8G.sdcard.raw")
    ppm = tmp_path / "frame.ppm"
    Image.new("RGB", (136, 77), (10, 20, 30)).save(ppm)
    media = tmp_path / "media"
    media.mkdir()
    Image.new("RGB", (20, 12)).save(media / "anim0.gif")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        w.call("multiboot.select", 0)
        panel = _panel(w)

        def draw():
            fp = "abc"
            panel._pv_fp, panel._pv_media = fp, str(media)
            panel._pv_cache[(fp, 0, 0)] = str(ppm)
            panel._pv_rects[(fp, 0)] = {0: (10, 20, 30, 17)}
            row = panel._rows[0]
            row.anim = "auto"
            assert panel.load_frame(str(ppm), 0, 0, 1)
            panel._play_start()
        w.run(draw)
        pv = _st(w)["preview"]
        assert pv["frame"]["src"].endswith(".png")
        assert os.path.isfile(pv["frame"]["src"])
        assert (pv["frame"]["w"], pv["frame"]["h"]) == (136, 77)
        assert pv["sketch"] is None
        clips = pv["clips"]
        assert len(clips) == 1 and clips[0]["src"].endswith("anim0.gif")
        assert (clips[0]["x"], clips[0]["y"]) == (10, 20)
        # START holds the LOADING beat (black when there is no frame for it)
        w.run(lambda: panel._blackout(None))
        assert _st(w)["preview"]["black"] == {"src": None}
        w.run(panel._blackout_over)
        assert _st(w)["preview"]["black"] is None


def test_version_alarm(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: _panel(w)._show_alarm(
            {"version_mismatch": "Image 1 is 1.02.0, image 0 is 1.16.0."}))
        s = _st(w)
        assert s["alarm"]["head"] == ("⚠ These images are not the same game "
                                      "code version.")
        assert "1.02.0" in s["alarm"]["full"]
        w.run(lambda: _panel(w)._show_alarm(None))
        assert _st(w)["alarm"] is None


def test_a_menu_card_raises_no_version_alarm(tmp_path):
    """PAD-197: loading a menu read off an SD card - every tree unreadable
    by design - leaves the strip down and says why in the Log, once, instead
    of one 'no such games tree' line per image.  The same report for a
    whole card still raises the alarm."""
    from tests.test_multiboot_tab import _rich_report
    from pinball_decryptor.webui.multiboot_core import (
        MENU_ONLY_VERSIONS, loaded_media_dir)
    report = _rich_report(tmp_path, armed=False)
    note = "images.conf names /dev/mmcblk0p7 but the card carries no such games tree"
    report["warnings"] = ["image 1 (/dev/mmcblk0p7): " + note]
    report["unknown_version"] = "1 image(s) did not say what game code they run: image 1 (%s)." % note
    for name, alarmed in (("SanDisk-32G.menu.raw", False), ("card.multi.raw", True)):
        card = tmp_path / name
        card.write_bytes(bytes(16))
        media = loaded_media_dir(str(card))
        os.makedirs(media, exist_ok=True)
        with web_app(tmp_path / name.split(".")[0], mfr="stern") as w:
            panel = _panel(w)
            lines = []
            orig = panel._write
            panel._write = lambda t, *a, **k: (lines.append(t), orig(t, *a, **k))
            warns = w.run(panel.load_inspect, report, str(card), media)
            assert (_st(w)["alarm"] is not None) == alarmed, name
            assert any("games tree" in x for x in warns) == alarmed, name
            assert any(MENU_ONLY_VERSIONS in x for x in lines) != alarmed, name


def test_size_strip_from_a_plan(tmp_path):
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        G = 1024 ** 3
        panel = _panel(w)

        def plan():
            panel._plan_info = {
                "bytes": int(10 * G),
                "fits": {"8G": (False, -int(2 * G)), "16G": (True, int(4 * G)),
                         "32G": (True, int(20 * G))},
                "versions": {}, "overhead": int(1 * G), "free": int(2 * G),
                "shared": None, "sizes": [(0, "p3", int(7 * G), "a")]}
            panel._draw_size()
        w.run(plan)
        z = _st(w)["size"]
        assert z["known"] and z["head"] == "16 GB" and not z["over"]
        kinds = [b["kind"] for b in z["bands"]]
        assert kinds == ["image", "free", "overhead"]
        assert "Image 0 - a" in z["tip"]
        assert z["detail"].endswith("free for updates.") or " so 16 GB" in \
            z["detail"]


def test_busy_turns_the_green_button_into_cancel(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        panel = _panel(w)
        w.run(lambda: panel._set_busy(True))
        s = _st(w)
        assert s["busy"] and s["build_mode"] == "cancel" and s["locked"]
        # the button's press is the run's Cancel now
        assert w.call("multiboot.build_flash") is True
        s = _st(w)
        assert s["build_mode"] == "cancelling"
        assert s["message"] == "Cancelling…"
        w.run(lambda: panel._set_busy(False))
        panel._cancel_pending = False
        assert _st(w)["build_mode"] == "build"


def test_hidden_tab_plays_nothing(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        panel = _panel(w)
        assert panel._pv_hidden
        w.call("multiboot.visible", True)
        assert not panel._pv_hidden
        w.call("multiboot.visible", False)
        assert panel._pv_hidden


# ------------------------------------------ PAD-188: the restore's own read
def _pad188_card(tmp_path):
    from pinball_decryptor.webui.multiboot_core import loaded_media_dir
    from tests.test_multiboot_tab import _rich_report
    report = _rich_report(tmp_path, armed=False)
    d = tmp_path / "multi"
    d.mkdir(exist_ok=True)
    card = d / "card.multi.raw"
    card.write_bytes(bytes(16))
    card = str(card)
    media = loaded_media_dir(card)
    os.makedirs(media, exist_ok=True)
    return report, card, media


def _restored(w, doc, report, card, media):
    """The second half of a restart: the form restored, the tab opened, and
    the read that follows it standing in for the tool."""
    panel = _panel(w)
    panel.load_card = (
        lambda p, **kw: panel.load_inspect(report, p, media) or True)
    w.run(panel.restore_state, doc)
    return w.run(panel.on_shown)


def test_the_restores_read_keeps_the_edits_the_form_came_back_with(tmp_path):
    """PAD-188.  The restore's read is the one read nobody asked for, and it
    replaces every field - so a form left mid-edit on a card that was never
    rebuilt was thrown away on the next launch, silently.  A random card over
    a built card's games is exactly that edit, and is what was reported."""
    from pinball_decryptor.webui import multiboot_core as mt
    report, card, media = _pad188_card(tmp_path)
    with web_app(tmp_path / "last_night", mfr="stern") as w:
        panel = _panel(w)
        w.run(panel.load_inspect, report, card, media)
        w.run(panel.add_random_over_existing, "SURPRISE ME")
        assert [mt.is_group(r) for r in panel._rows] == [False, False, True]
        doc = w.run(panel.state)
    with web_app(tmp_path / "this_morning", mfr="stern") as w:
        _restored(w, doc, report, card, media)
        panel = _panel(w)
        assert not w.asked, "a restored form is not a question to ask"
        assert panel._loaded_card == card, "the read still earns editing mode"
        assert [r.title for r in panel._rows] == \
            ["STERN 1.59.0", "TMNT 1987", "SURPRISE ME"]
        assert mt.is_group(panel._rows[2])
        assert [m.path for m in panel._rows[2].members] == \
            [r.path for r in panel._rows[:2]]
        assert mt.diff_forms(panel._loaded_form, panel.form()) == (
            [], ["2 images -> 3", "compact layout on"])
        assert "unsaved change" in w.run(panel.message)
        assert panel._carry_edits is None


def test_a_restored_form_that_matches_the_card_is_left_alone(tmp_path):
    """The card's own rows carry facts a saved form cannot, so an identical
    form is never re-applied over them - every restart of everyone who did
    not edit anything."""
    report, card, media = _pad188_card(tmp_path)
    with web_app(tmp_path / "a", mfr="stern") as w:
        panel = _panel(w)
        w.run(panel.load_inspect, report, card, media)
        doc = w.run(panel.state)
    with web_app(tmp_path / "b", mfr="stern") as w:
        _restored(w, doc, report, card, media)
        panel = _panel(w)
        assert [r.title for r in panel._rows] == ["STERN 1.59.0", "TMNT 1987"]
        assert w.run(panel._unsaved_changes) == 0
        assert "unsaved change" not in w.run(panel.message)
        assert panel._carry_edits is None


def test_a_read_that_never_starts_does_not_carry_a_form_into_the_next_one(
        tmp_path):
    report, card, media = _pad188_card(tmp_path)
    with web_app(tmp_path / "a", mfr="stern") as w:
        panel = _panel(w)
        panel.load_card = lambda p, **kw: False         # the tool refused
        w.run(panel.restore_state, {"v": 1, "card": card,
                                    "images": [{"path": card,
                                                "title": "MINE"}],
                                    "menu": {}})
        assert w.run(panel.on_shown) is False
        assert panel._carry_edits is None


def test_a_form_saved_against_another_card_is_not_carried(tmp_path):
    """The path box can be retyped while the read is on the worker: a form
    saved against a different card is not an edit of this one."""
    report, card, media = _pad188_card(tmp_path)
    with web_app(tmp_path / "a", mfr="stern") as w:
        panel = _panel(w)
        panel._carry_edits = {"v": 1, "card": str(tmp_path / "other.raw"),
                              "images": [{"path": "x.raw", "title": "MINE"}],
                              "menu": {}}
        w.run(panel.load_inspect, report, card, media)
        assert [r.title for r in panel._rows] == ["STERN 1.59.0", "TMNT 1987"]
        assert panel._carry_edits is None
