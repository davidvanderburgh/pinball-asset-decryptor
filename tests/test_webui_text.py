"""The web Replace Text tab (webui/tabs/text.py), its rules
(webui/text_rules.py) and the Scenes window it opens (webui/text_scenes.py).

Everything runs through the in-process harness: the page's calls go through
the registry on the UI loop exactly as they would from the browser, modal
questions are answered from ``w.answers``.
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

MFRS = ["stern", "jjp", "spooky", "pb", "williams", "cgc", "dp", "ap", "bof",
        "data_east", "sega"]


# ---------------------------------------------------------------- helpers
def _wait(w, pred, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        w.drain()
        if pred():
            return True
        time.sleep(0.03)
    raise AssertionError("timed out waiting")


def _manifest(folder, rows):
    from pinball_decryptor.core import text_manifest
    text_manifest.save(str(folder), rows)
    return str(folder)


def _rows():
    return [
        {"path": "/g/aaaaaaaaaaaaaaaaaaaa/scene.radium",
         "original": "GODZILLA VS EBIRAH", "replacement": ""},
        {"path": "/g/aaaaaaaaaaaaaaaaaaaa/scene.radium",
         "original": "EBIRAH", "replacement": ""},
        {"path": "/g/bbbbbbbbbbbbbbbbbbbb/scene.radium",
         "original": "EBIRAH", "replacement": ""},
        {"path": "/g/bbbbbbbbbbbbbbbbbbbb/scene.radium",
         "original": "BALL ONE", "replacement": ""},
        {"path": "/godzilla_le/game", "original": "MOTHRA",
         "replacement": "", "budget": 6, "fixed": True},
        {"path": "/godzilla_le/game", "original": "RODAN",
         "replacement": "", "budget": 96, "grow": True},
    ]


def _set_folder(w, folder):
    """Set the shared project folder.  A trace another tab hangs on it may
    raise while that tab is being ported; Tk reports a trace error without
    failing the set, so the tests do the same."""
    def _do():
        try:
            w.window.write_assets_var.set(folder)
        except Exception:                            # noqa: BLE001
            pass
    w.run(_do)


def _open(w, folder):
    """Point the project folder at *folder*, show the tab, wait for the
    scan to land."""
    _set_folder(w, folder)
    w.call("ui.select_tab", "text")
    _wait(w, lambda: not w.state("text")["scanning"]
          and w.state("text").get("total", 0) > 0)
    return w.state("text")


def _row_index(w, original, path_part=""):
    svc = w.window.service("text")
    for i, r in enumerate(svc._text_rows):
        if r["original"] == original and path_part in r["path"]:
            return i
    raise KeyError(original)


# ------------------------------------------------------------ the rules
def test_rules_max_grows_and_budget():
    from pinball_decryptor.webui import text_rules as R
    scene = {"path": "/g/x/scene.radium", "original": "HELLO",
             "replacement": ""}
    fixed = {"path": "/g/game", "original": "MOTHRA", "replacement": "",
             "budget": 6, "fixed": True}
    unflagged = {"path": "/g/game", "original": "ABC", "replacement": "",
                 "budget": 3}
    assert R.row_max_label(scene) == "96 (grows)"
    assert R.row_max_label(fixed) == "6"
    assert R.row_max_label(unflagged) == "96 (grows)"
    assert R.row_len(fixed, "A\\nB") == 3          # \n is one byte
    text, over = R.budget_readout(fixed, "MOTHRAX")
    assert over and text == "7 / 6 bytes  — too long"
    text, over = R.budget_readout(scene, "HELLO WORLD")
    assert not over and "rewritten at the new length" in text
    assert "only 6 fit" in R.too_long_message(fixed, "MOTHRAX")
    assert R.split_edit("GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE") == (
        "EBIRAH", "BIOLLANTE")
    assert R.pending_text_status(
        dict(fixed, replacement="MOTH")) == "Pending (Replace Text)"
    assert R.pending_text_status(
        dict(scene, replacement="HELLO THERE")) == \
        "Pending (text, scene grows)"
    assert R.pending_text_status(
        dict(unflagged, replacement="ABCD"), grow_on=False) == \
        "Pending (Replace Text — too long, grow is off)"


def test_rules_scene_menu_and_filters():
    from pinball_decryptor.webui import text_rules as R
    rows = _rows()
    names = {R.scene_key(rows[2]["path"]): "Battle"}
    values, by_display = R.scene_menu(rows, names)
    assert values[0] == "All scenes" and values[1] == "Game program"
    assert values[2].startswith("Battle — ")          # named first
    assert by_display[values[2]] == rows[2]["path"]
    assert R.row_matches(rows[4], "", None, R.SCENE_PROGRAM)
    assert not R.row_matches(rows[0], "", None, R.SCENE_PROGRAM)
    assert R.row_matches(rows[0], "ebirah", None, None)
    assert not R.row_matches(rows[0], "", True, None)


# ------------------------------------------------------ per manufacturer
def test_the_tab_is_shown_only_for_stern_spike2(tmp_path):
    with web_app(tmp_path) as w:
        keys = {m.key for m in w.window.manufacturers}
        for mfr in MFRS:
            if mfr not in keys:
                continue
            w.call("ui.pick_manufacturer", mfr)
            w.drain()
            tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
            st = w.state("text")
            assert tabs["text"]["visible"] == (mfr == "stern"), mfr
            # a manufacturer switch leaves nothing of the last one behind
            assert st["rows"] == [] and st["view"] == []
            assert st["sel"] is None and not st["can_edit"]
            assert st["empty"].startswith("Set the project folder")
            assert w.window.text_status_var.get() == ""
        if "stern" in keys:
            w.call("ui.pick_manufacturer", "stern")
            for era, shown in (("spike1", False), ("whitestar", False),
                               ("spike2", True)):
                w.call("ui.set_era", era)
                w.drain()
                tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
                assert tabs["text"]["visible"] == shown, era


def test_every_export_answers_on_the_window(tmp_path):
    from pinball_decryptor.webui.tabs.text import TextTab
    with web_app(tmp_path, mfr="stern") as w:
        for name in TextTab.exports:
            getattr(w.window, name)
        assert w.window.text_change_filter_var.get() == "All"
        assert w.window.text_scene_filter_var.get() == "All scenes"
        missing = getattr(w.window, "missing_exports", {}) or {}
        assert not [n for n in missing if n.startswith("text_")]


# ------------------------------------------------------------ scanning
def test_scan_lists_rows_and_the_filters_narrow_them(tmp_path):
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        st = _open(w, folder)
        assert st["total"] == 6 and len(st["view"]) == 6
        assert w.window.text_status_var.get() == "6 string(s), 0 edited"
        assert st["scene_options"][:2] == ["All scenes", "Game program"]
        by_o = {r["o"]: r for r in st["rows"]}
        assert by_o["MOTHRA"]["mx"] == "6"
        assert by_o["RODAN"]["mx"] == "96 (grows)"
        assert by_o["BALL ONE"]["sc"] == "bbbbb…bbbb/scene.radium"
        assert by_o["MOTHRA"]["sc"] == "game program"

        w.call("ui.set", "text", "search", "ebirah")
        st = w.state("text")
        assert len(st["view"]) == 3
        assert w.window.text_status_var.get() == \
            "6 string(s), 0 edited  (3 shown)"
        w.call("ui.set", "text", "search", "")
        w.call("text.set_scene", "Game program")
        assert [w.state("text")["rows"][i]["o"]
                for i in w.state("text")["view"]] == ["MOTHRA", "RODAN"]
        w.call("text.set_scene", "All scenes")
        w.call("text.sort_by", "max")              # Max starts descending
        st = w.state("text")
        assert st["sort"] == {"col": "max", "desc": True}
        assert st["rows"][st["view"][-1]]["o"] == "MOTHRA"
        w.call("text.sort_by", "max")
        assert w.state("text")["sort"]["desc"] is False


def test_scan_cancel_and_no_folder(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "text")
        w.call("text.scan")
        st = w.state("text")
        assert st["empty"] == \
            "Set the project folder on the Extract tab, then click Scan."
        assert not st["scanning"]
        w.call("text.cancel_scan")
        assert w.state("text")["empty"] == \
            "Scan cancelled — click Scan to try again."


def test_cancelling_a_rescan_says_so_over_the_emptied_list(tmp_path):
    """Tk's _cancel_scan emptied the list and put the cancelled message
    over it even with rows loaded; a filter change fills it again."""
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.scan")
        w.call("text.cancel_scan")
        w.drain()
        st = w.state("text")
        assert st["view"] == [] and not st["scanning"]
        assert st["total"] == 6                 # the rows are still held
        assert st["empty"] == "Scan cancelled — click Scan to try again."
        w.call("text.set_show", "Changed")
        w.call("text.set_show", "All")
        st = w.state("text")
        assert len(st["view"]) == 6 and st["empty"] == ""


def test_column_widths_are_kept_under_the_tk_key(tmp_path):
    """Tk _persist_tree_columns(tree, "text", ("#0", "new", "max", "scene",
    "name")): the page's dragged widths land under the same key and ids,
    and widths saved by either version come back on the page."""
    import pinball_decryptor.core.config as config
    saved = {"column_widths": {"text": {"#0": 280, "scene": 230},
                               "audio": {"#0": 404}}}
    with web_app(tmp_path, mfr="stern", settings=saved) as w:
        assert w.state("text")["col_widths"] == {"o": 280, "sc": 230}
        assert w.call("text.save_widths",
                      {"o": 320, "n": 250.4, "mx": 90, "sc": 210,
                       "bogus": 5}) is True
        assert w.state("text")["col_widths"] == {
            "o": 320, "n": 250, "mx": 90, "sc": 210}
        with open(config.SETTINGS_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)["column_widths"]
        assert on_disk["text"] == {"#0": 320, "new": 250, "max": 90,
                                   "scene": 210}
        assert on_disk["audio"] == {"#0": 404}      # other trees untouched


def test_an_empty_folder_says_what_to_do(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, str(folder))
        w.call("ui.select_tab", "text")
        _wait(w, lambda: not w.state("text")["scanning"])
        assert w.state("text")["empty"].startswith(
            "No editable on-screen text found in this folder.")


# -------------------------------------------------------------- editing
def test_apply_revert_and_apply_to_every_scene(tmp_path):
    from pinball_decryptor.core import text_manifest
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        i = _row_index(w, "EBIRAH", "aaaa")
        w.call("text.select", i)
        st = w.state("text")
        assert st["can_edit"] and st["orig"] == "EBIRAH"
        assert st["scene_note"].startswith("Scene: /g/aaaa")
        assert w.window.text_new_var.get() == "EBIRAH"
        assert w.window.text_budget_var.get() == "6 / 96 bytes"

        w.call("ui.set", "text", "apply_all", True)
        assert w.call("text.apply", "BIOLLANTE") is True
        saved = {(r["path"], r["original"]): r["replacement"]
                 for r in text_manifest.load(folder)}
        assert saved[("/g/aaaaaaaaaaaaaaaaaaaa/scene.radium", "EBIRAH")] == \
            "BIOLLANTE"
        assert saved[("/g/bbbbbbbbbbbbbbbbbbbb/scene.radium", "EBIRAH")] == \
            "BIOLLANTE"
        st = w.state("text")
        assert st["edited"] == 2 and st["sel_edited"]
        assert st["rows"][i]["ed"] and st["rows"][i]["n"] == "BIOLLANTE"
        log = [ln["text"] for ln in w.window._log["stern"]]
        assert 'Replace Text: "EBIRAH" → "BIOLLANTE" (2 copies)' in log
        from pinball_decryptor.core import history_log
        with open(history_log.path_for(folder), encoding="utf-8") as f:
            assert 'changed to: "BIOLLANTE"' in f.read()

        w.call("text.revert")
        assert not text_manifest.changed(folder)
        assert w.window.text_new_var.get() == "EBIRAH"
        assert w.state("text")["edited"] == 0


def test_too_long_is_refused_with_the_tk_message(tmp_path):
    from pinball_decryptor.core import text_manifest
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.select", _row_index(w, "MOTHRA"))
        w.call("ui.set", "text", "new", "MOTHRAXX")
        st = w.state("text")
        assert st["budget_over"]
        assert w.window.text_budget_var.get() == "8 / 6 bytes  — too long"
        assert w.call("text.apply") is False
        assert w.asked[-1]["title"] == "Replacement too long"
        assert "but only 6 fit" in w.asked[-1]["message"]
        assert not text_manifest.changed(folder)


def test_clear_all_asks_first(tmp_path):
    from pinball_decryptor.core import text_manifest
    rows = _rows()
    rows[3]["replacement"] = "BALL 1"
    folder = _manifest(tmp_path / "proj", rows)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.answers.append("no")
        assert w.call("text.clear_all") is False
        assert text_manifest.changed(folder)
        w.answers.append("yes")
        assert w.call("text.clear_all") is True
        assert w.asked[-1]["title"] == "Clear all edits"
        assert not text_manifest.changed(folder)


def test_replace_everywhere_prefills_plans_and_skips_misfits(tmp_path):
    from pinball_decryptor.core import text_manifest
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        i = _row_index(w, "GODZILLA VS EBIRAH")
        w.call("text.select", i)
        w.call("ui.set", "text", "new", "GODZILLA VS BIOLLANTE")
        assert w.call("text.replace_open", i) == {"find": "EBIRAH",
                                                  "repl": "BIOLLANTE"}
        plan = w.call("text.replace_plan", "EBIRAH", "BIOLLANTE", True)
        assert plan["text"] == "3 of 3 matching rows fit"
        assert plan["can_apply"] and plan["misfits"] == []
        plan = w.call("text.replace_plan", "MOTHRA", "MOTHRAAA", True)
        assert plan["text"] == ("0 of 1 matching rows fit — 1 listed below "
                                "would not, and will be skipped")
        assert plan["misfits"][0]["mx"] == "6"
        assert not plan["can_apply"]
        assert w.call("text.replace_plan", "", "", True)["text"] == \
            "Type the word to look for."
        got = w.call("text.replace_apply", "ebirah", "BIOLLANTE", False)
        assert got == {"applied": 3, "skipped": 0}
        assert len(text_manifest.changed(folder)
                   ["/g/aaaaaaaaaaaaaaaaaaaa/scene.radium"]) == 2


def test_replace_everywhere_needs_a_scan(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("text.replace_open") is None
        assert w.asked[-1]["title"] == "Replace everywhere"


# -------------------------------------------------------------- scenes
def test_naming_a_scene_writes_the_shared_tag_store(tmp_path):
    from pinball_decryptor.core import staged_changes
    folder = _manifest(tmp_path / "proj", _rows())
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text.rename_prompt", _row_index(w, "MOTHRA")) is None
        assert w.asked[-1]["title"] == "Name this scene"
        i = _row_index(w, "BALL ONE")
        p = w.call("text.rename_prompt", i)
        assert p["prompt"].startswith("A name for the scene bbbbb…bbbb/")
        # filtered to that scene, naming it keeps the filter on it
        display = next(d for d in w.state("text")["scene_options"]
                       if d.startswith("bbbbb"))
        w.call("text.set_scene", display)
        w.call("text.set_scene_name", i, "  Ball   screen ")
        tags = staged_changes.load(folder)["image_group_tags"]
        assert tags == {"rad::/g/bbbbbbbbbbbbbbbbbbbb/scene.radium":
                        "Ball screen"}
        st = w.state("text")
        assert w.window.text_scene_filter_var.get().startswith(
            "Ball screen — ")
        assert len(st["view"]) == 2
        assert st["rows"][i]["nm"] == "Ball screen"


def test_a_scene_named_here_survives_the_images_tab(tmp_path):
    """Tk _text_set_scene_name copied the tags into the Images tab when it
    was on the same folder.  Without that the Images tab's next sidecar save
    (any pick, any filter change) wrote its stale names back and the name
    was lost."""
    from pinball_decryptor.core import staged_changes
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, folder)
        w.call("images.scan")
        _wait(w, lambda: not w.state("images").get("scanning")
              and w.window.service("images")._scan_dir)
        _open(w, folder)
        i = _row_index(w, "BALL ONE")
        key = "rad::/g/scene2/scene.radium"
        w.call("text.set_scene_name", i, "Ball screen")
        images = w.window.service("images")
        assert images._group_tags.get(key) == "Ball screen"
        w.call("images.set_show", "Changed")
        w.call("images.set_show", "All")
        tags = staged_changes.load(folder)["image_group_tags"]
        assert tags == {key: "Ball screen"}
        # clearing the name here clears it there too
        w.call("text.set_scene_name", i, "")
        assert key not in images._group_tags
        w.call("images.set_show", "Changed")
        assert not staged_changes.load(folder).get("image_group_tags")


def test_filters_are_folder_state(tmp_path):
    from pinball_decryptor.core import staged_changes
    folder = _manifest(tmp_path / "proj", _rows())
    other = _manifest(tmp_path / "other", _rows()[:2])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.set_show", "Changed")
        assert staged_changes.load(folder)["text_change_filter"] == "Changed"
        # another folder opens on its own (default) filters ...
        _set_folder(w, other)
        w.call("text.scan")
        _wait(w, lambda: w.state("text")["total"] == 2)
        assert w.window.text_change_filter_var.get() == "All"
        # ... and the first comes back the way it was left
        _set_folder(w, folder)
        w.call("text.scan")
        _wait(w, lambda: w.state("text")["total"] == 6)
        assert w.window.text_change_filter_var.get() == "Changed"


def test_revert_all_and_invalidate_rescan(tmp_path):
    from pinball_decryptor.core import text_manifest
    rows = _rows()
    rows[3]["replacement"] = "BALL 1"
    folder = _manifest(tmp_path / "proj", rows)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.state("text")["edited"] == 1
        text_manifest.revert_all(folder)
        w.run(w.window.refresh_after_revert)
        _wait(w, lambda: w.state("text")["edited"] == 0
              and not w.state("text")["scanning"])
        w.run(w.window.invalidate_asset_scans)
        _wait(w, lambda: not w.state("text")["scanning"]
              and w.window.service("text")._text_scan_dir == folder)


def _scene_extract(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from tests.test_stern_fontrender import _make_extract
    from pinball_decryptor.plugins.stern import scene_render
    _make_extract(tmp_path)
    _manifest(tmp_path, [
        {"path": "/g/scene1/scene.radium", "original": "CLOCK NOT SET",
         "replacement": ""},
        {"path": "/g/scene2/scene.radium", "original": "BALL ONE",
         "replacement": ""}])
    layout = {"/g/scene1/scene.radium": {
        "stage": [320, 180, 60.0], "unplaced": 0, "offstage": 0,
        "sprites": [], "texts": [
            {"name": "Line1", "x": 0, "y": 100, "text": "CLOCK NOT SET",
             "rect": [0, 0, 320, 180], "rgba": [1.0, 1.0, 1.0, 1.0],
             "align": 1, "font": "tbl", "font_px": 8}]}}
    with open(str(tmp_path / scene_render.SCENE_LAYOUT_MANIFEST), "w",
              encoding="utf-8") as f:
        json.dump(layout, f)
    return str(tmp_path)


def test_show_in_scenes_lands_on_the_line_and_jumps_back(tmp_path):
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        # a game-program row has no scene to show
        assert w.call("text.show_in_scene") is False
        assert w.asked[-1]["title"] == "Scenes"
        w.call("text.select", _row_index(w, "BALL ONE"))
        assert w.call("text.show_in_scene") is True
        sc = w.state("text_scenes")
        assert sc["open"] and sc["sel"] == "/g/scene2"
        assert sc["item"] == "txt::0"
        groups = {g["key"]: g for g in sc["contents"]["groups"]}
        assert groups["txt"]["items"][0]["text"] == "BALL ONE"
        assert groups["txt"]["items"][0]["info"] == \
            "double-click: find on Replace Text"
        # a search left in the window does not swallow the next jump
        w.call("text_scenes.set_search", "scene2")
        w.call("text.select", _row_index(w, "CLOCK NOT SET"))
        w.call("text.show_in_scene")
        sc = w.state("text_scenes")
        assert sc["search"] == "" and sc["sel"] == "/g/scene1"
        # double-clicking the line goes back to it on the Text tab
        assert w.call("text_scenes.activate", "txt::0") is True
        assert not w.state("text_scenes")["open"]
        st = w.state("text")
        assert st["rows"][st["sel"]]["o"] == "CLOCK NOT SET"
        assert w.window.text_search_var.get() == "CLOCK NOT SET"
        assert w.call("text_scenes.show") is True
        w.call("text_scenes.close")
        assert not w.state("text_scenes")["open"]


def test_scenes_recolour_move_and_preview(tmp_path):
    from pinball_decryptor.plugins.stern import text_colors, text_layout
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.select", _row_index(w, "CLOCK NOT SET"))
        w.call("text.show_in_scene")
        _wait(w, lambda: w.state("text_scenes")["caption"] != "Drawing…")
        sc = w.state("text_scenes")
        assert sc["frames"] and os.path.isfile(sc["frames"][0])
        assert sc["can_save"]
        item = sc["contents"]["groups"][2]["items"][0]
        assert item["info"] == "#ffffff · right-click to recolour"

        start = w.call("text_scenes.color_start", "CLOCK NOT SET")
        assert start["start"] == "#ffffff"
        assert w.call("text_scenes.set_color", "CLOCK NOT SET", "#33cc33")
        assert text_colors.load(folder) == {"/g/scene1/scene.radium": {
            "CLOCK NOT SET": ((255, 255, 255), (51, 204, 51))}}
        item = w.state("text_scenes")["contents"]["groups"][2]["items"][0]
        assert item["info"] == "#ffffff → #33cc33 (not built yet)"
        assert item["picked"]
        w.call("text_scenes.reset_color", "CLOCK NOT SET")
        assert text_colors.load(folder) == {}

        d = w.call("text_scenes.layout_start", "CLOCK NOT SET", "size")
        assert d["px"] == 8 and d["size"] == 100
        assert w.call("text_scenes.layout_px", {"size": "150"}) == \
            "8 px → 12 px"
        w.call("text_scenes.layout_done", None)          # Cancel
        assert text_layout.load(folder) == {}
        w.call("text_scenes.layout_start", "CLOCK NOT SET", "move")
        assert w.call("text_scenes.layout_done", {"dx": "5", "dy": "-2"})
        row = text_layout.load(folder)["/g/scene1/scene.radium"][
            "CLOCK NOT SET"]
        assert row["dx"] == 5 and row["dy"] == -2
        assert w.call("text_scenes.align_text", "CLOCK NOT SET", "right")
        item = w.state("text_scenes")["contents"]["groups"][2]["items"][0]
        assert item["has_layout"] and item["align"] == "right"
        w.call("text_scenes.reset_layout", "CLOCK NOT SET")
        assert text_layout.load(folder) == {}

        w.call("text_scenes.set_bg", "White")
        assert w.state("text_scenes")["bg_rgb"] == "#ffffff"
        # a line with no recorded layout says why it can't be recoloured
        w.call("text_scenes.select", "/g/scene2")
        assert w.call("text_scenes.color_start", "BALL ONE") is None
        assert w.asked[-1]["title"] == "Text colour"
        assert w.state("text_scenes")["canvas_msg"] == \
            "no preview for this scene"
        w.call("text_scenes.close")


def test_an_edit_redraws_an_open_scenes_window(tmp_path):
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        i = _row_index(w, "CLOCK NOT SET")
        w.call("text.select", i)
        w.call("text.show_in_scene")
        w.call("text.apply", "CLOCK SET")
        item = w.state("text_scenes")["contents"]["groups"][2]["items"][0]
        assert item["info"].startswith('shows: "CLOCK SET"')


def test_other_tabs_open_the_scenes_window_and_its_jumps(tmp_path):
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        # the Images tab's call: open_scene_browser(assets, preselect_rel=)
        rel = next(r for r in os.listdir(os.path.join(
            folder, "images", "scene_textures")) if r.endswith(".png"))
        assert w.run(lambda: w.window.open_scene_browser(folder)) is True
        assert w.state("text_scenes")["open"]
        # the Video tab's call
        assert w.run(lambda: w.window._open_scene_browser(
            preselect_video="video/x.mp4")) is True
        # a jump to a tab that answers it steps the window aside
        seen = []
        w.window.reveal_image_slot = lambda r: seen.append(r)
        w.call("text_scenes.select", "/g/scene1")
        assert w.call("text_scenes.activate", "img::images/x.png") is True
        assert seen == ["images/x.png"]
        assert not w.state("text_scenes")["open"]
        w.call("text_scenes.show")
        # a font row opens the Fonts window on that font
        assert w.call("text_scenes.activate", "font::tbl") is True
        assert w.state("text_fonts")["open"]
        assert w.state("text_fonts")["sel"] == "tbl"
        w.call("text_fonts.close")
        assert rel


# ------------------------------------------------------------ the Fonts window
def _alpha_max(path):
    import numpy as np
    from PIL import Image
    return int(np.asarray(Image.open(path).convert("RGBA"))[..., 3].max())


def test_fonts_window_scope_preview_blank_undo_revert(tmp_path):
    folder = _scene_extract(tmp_path / "proj")
    from pinball_decryptor.plugins.stern import fontrender as fr
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        # the Images tab's call: open_font_studio(assets, preselect_rel=)
        rel = "images/scene_textures/glyphs/radimg_bc1_8x8_00000003/U+0043_C.png"
        assert w.run(lambda: w.window.open_font_studio(
            folder, preselect_rel=rel)) is True
        st = w.state("text_fonts")
        assert st["open"] and st["sel"] == "tbl2"
        assert st["hint"].startswith("2 game font(s) in ")
        w.call("text_fonts.select", "tbl")
        _wait(w, lambda: w.state("text_fonts")["preview"])
        st = w.state("text_fonts")
        assert os.path.isfile(st["preview"])
        assert [s["card"] for s in st["scenes"]] == [
            "/g/scene1/scene.radium", "/g/scene9/scene.radium"]
        assert st["scope"] == "all"
        assert st["scope_lbl"] == \
            "An import or glyph edit is written to all 2 scenes using this font."
        # the scenes draw it white: the ink shows as picked
        assert "draw this font white" in st["tint"]

        # scope: only the scenes I select
        w.call("text_fonts.set_scope_mode", "some")
        st = w.state("text_fonts")
        assert st["scope_sel"] == [0]
        assert st["scope_lbl"] == ("Only 1 of 2 scenes get this font; the "
                                   "rest keep the stock one.")
        font = next(f for f in fr.load_fonts(folder) if f["key"] == "tbl")
        assert fr.get_font_scope(folder, font) == ["/g/scene1/scene.radium"]
        w.call("text_fonts.set_scope_mode", "all")
        assert not fr.get_font_scope(folder, font)

        # a colour alone can be applied (it repaints the current letters)
        assert not w.state("text_fonts")["can_apply"]
        w.call("text_fonts.set_color", "#33cc33")
        assert w.state("text_fonts")["can_apply"]
        assert w.call("text_fonts.apply") is True
        assert "repainted #33cc33" in w.state("text_fonts")["status"]
        assert w.state("text_fonts")["can_undo"]
        # the preview refresh (120 ms after an edit, as in Tk) rewrites the
        # status line: let it land before the next step reads the status
        fonts = w.window.service("text").fonts
        _wait(w, lambda: fonts._render_job is None)

        glyph = font["glyphs"][0x41]["abs"]
        w.answers.append("yes")
        assert w.call("text_fonts.blank") is True
        assert w.asked[-1]["title"] == "Blank font"
        assert _alpha_max(glyph) == 0
        assert "blanked" in w.state("text_fonts")["status"]
        assert w.state("text_fonts")["undo_label"].startswith(
            "Undo blanking")
        assert w.call("text_fonts.undo") is True
        assert _alpha_max(glyph) > 0

        w.answers.append("yes")
        assert w.call("text_fonts.revert") is True
        assert "restored" in w.state("text_fonts")["status"]
        w.answers.append("no")
        assert w.call("text_fonts.revert_all") is False
        w.answers.append("yes")
        assert w.call("text_fonts.revert_all") is True
        assert "restored to stock" in w.state("text_fonts")["status"]

        # the preview options take effect
        w.call("text_fonts.set_opt", "bg", "White")
        _wait(w, lambda: w.state("text_fonts")["preview_bg"] == "#ffffff")
        w.call("text_fonts.set_opt", "stroke", "9")
        assert w.state("text_fonts")["opts"]["stroke"] == 6

        # right-click a scene: the Scenes window opens on it, in front; the
        # Fonts window stays open under it (Tk: two Toplevels)
        raised = w.state("text_fonts")["raise_n"]
        assert w.call("text_fonts.show_scene", 0) is True
        assert w.state("text_fonts")["open"]
        sc = w.state("text_scenes")
        assert sc["open"] and sc["sel"] == "/g/scene1"
        # ...and its font row brings this one to the front again, the Scenes
        # window staying open under it
        assert w.call("text_scenes.activate", "font::tbl") is True
        assert w.state("text_fonts")["open"]
        assert w.state("text_fonts")["raise_n"] > raised
        assert w.state("text_scenes")["open"]
        # closing the top window leaves the one it was opened from showing
        assert w.call("text_fonts.close") is True
        assert not w.state("text_fonts")["open"]
        assert not w.state("text_fonts")["alive"]
        assert w.state("text_scenes")["open"]
        w.call("text_scenes.close")


def test_fonts_window_import_asks_before_closing_unapplied(tmp_path):
    ttf = r"C:\Windows\Fonts\arial.ttf"
    for cand in (ttf, "/Library/Fonts/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.isfile(cand):
            ttf = cand
            break
    else:
        pytest.skip("no desktop font to import")
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.run(lambda: w.window.open_font_studio(folder, preselect="tbl"))
        w.answers.append(ttf)                         # the file picker
        assert w.call("text_fonts.pick_ttf") is True
        st = w.state("text_fonts")
        assert st["ttf_label"] == os.path.basename(ttf)
        assert st["opts"]["show"] == "Imported (preview)"
        assert "NOT APPLIED" in next(r["size"] for r in st["fonts"]
                                     if r["key"] == "tbl")
        w.answers.append("no")
        assert w.call("text_fonts.close") is False
        assert w.asked[-1]["title"] == "Unapplied import"
        # a manufacturer switch does not throw the import away: Tk left the
        # Fonts window open, and closing it still asks
        asked = len(w.asked)
        others = [m.key for m in w.window.manufacturers if m.key != "stern"]
        if others:
            w.call("ui.pick_manufacturer", others[0])
            w.drain()
            st = w.state("text_fonts")
            assert st["open"] and len(w.asked) == asked
            assert "NOT APPLIED" in next(r["size"] for r in st["fonts"]
                                         if r["key"] == "tbl")
            w.call("ui.pick_manufacturer", "stern")
            w.drain()
        w.answers.append("yes")
        assert w.call("text_fonts.close") is True
        assert w.asked[-1]["title"] == "Unapplied import"


def test_a_manufacturer_switch_closes_windows_with_nothing_unsaved(tmp_path):
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.run(lambda: w.window.open_font_studio(folder, preselect="tbl"))
        w.run(lambda: w.window.open_scene_browser(folder))
        others = [m.key for m in w.window.manufacturers if m.key != "stern"]
        if not others:
            pytest.skip("only one manufacturer in this build")
        w.call("ui.pick_manufacturer", others[0])
        w.drain()
        assert not w.state("text_fonts")["alive"]
        assert not w.state("text_scenes")["alive"]


def test_a_jump_steps_both_windows_aside_and_they_come_back(tmp_path):
    """Tk _step_aside_for_jump lowered EVERY open tool window below the main
    one; nothing was closed, and the Scenes… / Fonts… buttons (here also the
    status bar's) lifted them back as they were."""
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.run(lambda: w.window.open_font_studio(folder, preselect="tbl"))
        w.call("text.select", _row_index(w, "CLOCK NOT SET"))
        assert w.call("text.show_in_scene") is True
        w.call("text_scenes.set_bg", "White")
        assert w.call("text_scenes.activate", "txt::0") is True
        for ns in ("text_scenes", "text_fonts"):
            st = w.state(ns)
            assert not st["open"] and st["alive"], ns
        st = w.state("text")
        assert st["rows"][st["sel"]]["o"] == "CLOCK NOT SET"
        # back as they were: the scene, its line, the backdrop, the font
        assert w.call("text_scenes.show") is True
        sc = w.state("text_scenes")
        assert sc["open"] and sc["sel"] == "/g/scene1" and sc["bg"] == "White"
        assert w.call("text_fonts.show") is True
        assert w.state("text_fonts")["sel"] == "tbl"
        # the window's own Step aside button
        assert w.call("text_scenes.hide") is True
        assert not w.state("text_scenes")["open"]
        assert w.state("text_scenes")["alive"]
        w.call("text_scenes.close")
        assert w.call("text_scenes.show") is False     # closed is closed
        w.call("text_fonts.close")


def test_a_new_scene_clears_the_previous_picture_while_it_draws(tmp_path):
    """Tk _render_preview: preview.delete("all") + "drawing…" on the canvas,
    because a near-black leftover reads as the wrong scene."""
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.select", _row_index(w, "CLOCK NOT SET"))
        w.call("text.show_in_scene")
        _wait(w, lambda: w.state("text_scenes")["frames"])
        svc = w.window.service("text").scenes
        seen = {}

        def _start():
            svc._render_preview("/g/scene1")
            seen.update(w.state("text_scenes"))
        w.run(_start)
        assert seen["frames"] == [] and seen["canvas_msg"] == "drawing…"
        assert not seen["animated"]
        _wait(w, lambda: w.state("text_scenes")["frames"])
        w.call("text_scenes.close")


def test_move_is_cancelled_when_another_scene_is_picked(tmp_path):
    """The Move… / Font size… fields sit in the Scenes window's side column;
    picking another scene drops the live edit (it was for a line of the
    previous scene) and writes nothing."""
    from pinball_decryptor.plugins.stern import text_layout
    folder = _scene_extract(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.call("text.select", _row_index(w, "CLOCK NOT SET"))
        w.call("text.show_in_scene")
        assert w.call("text_scenes.layout_start", "CLOCK NOT SET", "move")
        assert w.state("text_scenes")["layout_dialog"]["kind"] == "move"
        w.call("text_scenes.layout_preview", {"dx": "7", "dy": "0"})
        w.call("text_scenes.select", "/g/scene2")
        assert w.state("text_scenes")["layout_dialog"] is None
        assert w.call("text_scenes.layout_done", {"dx": "7"}) is False
        assert text_layout.load(folder) == {}
        w.call("text_scenes.close")
