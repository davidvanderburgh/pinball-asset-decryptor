"""Replace Text tab: growable game-program rows, Replace everywhere, the
Write tab's grow option and its pending-row status.

David (2026-09-07): "on the TEXT tab, it still gives me grief that it is too
long with a Max column still persisting. Ideally, changes here would
propagate everywhere and I would be able to easily view them to confirm it
looks good."  The engine side (plans/spike2_longer_program_text.md) places a
longer program string in a new area of the game program; this is the GUI
half: the Max column shows the manifest's budget (96 for a growable row),
Apply accepts anything within it, "Replace everywhere…" changes a word in
every row at once, and the Write tab says which pending edit grows the
program and whether the Advanced option lets it.
"""

import json
import os

from pinball_decryptor.core import text_manifest as tm
from pinball_decryptor.gui.main_window import MainWindow
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

W = MainWindow
GAME = "/godzilla_le/game"
SCENE = "/godzilla_le/assets/lcd/auto_loaded/aaaa1111bbbb2222/scene.radium"


def _row(path, original, replacement="", budget=None, grow=False,
         unused=False):
    r = {"path": path, "original": original, "replacement": replacement}
    if budget:
        r["budget"] = budget
    if grow:
        r["grow"] = True
    if unused:
        r["unused"] = True
    return r


def _load(w, assets, rows):
    tm.save(assets, rows)
    w._set_tab_scanning("text", True)
    w._populate_text_after_scan(tm.load(assets), None, w._text_scan_id,
                                assets)
    w.write_assets_var.set(assets)


def _select(w, original):
    iid = next(str(i) for i, r in enumerate(w._text_rows)
               if r["original"] == original)
    w._text_tree.selection_set(iid)
    w._text_on_tree_select()
    return iid


def _state(widget):
    return str(widget.cget("state"))


# ---------------------------------------------------------------------------
# Tk-free
# ---------------------------------------------------------------------------

def test_grow_and_unused_flags_round_trip_in_the_manifest(tmp_path):
    """The 5th column carries the flags; a radium row and a 4-column manifest
    never see them, and an old reader that splits cols[0..3] is unaffected."""
    rows = [
        _row(SCENE, "TILT"),
        _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
             grow=True),
        _row(GAME, "GEORGE GOMEZ", budget=12, unused=True),
        _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28),
    ]
    tm.save(str(tmp_path), rows)
    text = (tmp_path / "text" / "strings.tsv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[1].split("\t")[4] == "grows"
    assert lines[2].split("\t")[4] == "unused"
    assert len(lines[0].split("\t")) == 3          # radium: no budget, no flags
    assert len(lines[3].split("\t")) == 4          # budget only
    back = tm.load(str(tmp_path))
    assert back[1].get("grow") is True and back[1]["budget"] == 96
    assert back[2].get("unused") is True and "grow" not in back[2]
    assert "grow" not in back[0] and "grow" not in back[3]
    assert tm.changed(str(tmp_path)) == {
        GAME: [("GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE")]}
    # An older 4-column manifest loads with neither flag.
    (tmp_path / "text" / "strings.tsv").write_text(
        "%s\tEBIRAH\t\t96\n" % GAME, encoding="utf-8")
    old = tm.load(str(tmp_path))
    assert old[0]["budget"] == 96 and "grow" not in old[0]


def test_max_label_budget_and_outgrows_are_tk_free():
    grow = _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True)
    fixed = _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28)
    scene = _row(SCENE, "TILT")
    assert W._text_row_budget(grow) == 96
    assert W._text_row_max_label(grow) == "96 (grows)"
    assert W._text_row_max_label(fixed) == "28"
    # A scene row grows too (Write rewrites the scene at the new length):
    # its Max is the 96-byte line cap, or its own length when that is longer.
    assert W._text_row_max_label(scene) == "96 (grows)"
    assert W._text_row_budget(scene) == 96
    assert W._text_row_grows(scene) and not W._text_row_grows(fixed)
    assert W._text_row_budget(_row(SCENE, "X" * 120)) == 120
    assert W._text_row_outgrows(scene, "TILT!")
    assert "longest a line can be is 96" in W._text_too_long_message(
        scene, "T" * 97)
    assert "can't move" in W._text_too_long_message(fixed, "X" * 29)
    assert W._text_row_outgrows(grow, "GODZILLA VS BIOLLANTE")
    assert not W._text_row_outgrows(grow, "GODZILLA VS GIGAN!")
    # \n is one byte on a budgeted row
    two = _row(GAME, "GODZILLA\\nVS. EBIRAH", budget=96, grow=True)
    assert W._text_row_len(two, "GODZILLA\\nVS. EBIRAH") == 19
    assert "not used" in W._text_program_note(
        _row(GAME, "GEORGE GOMEZ", budget=12, unused=True))
    assert "new area of the game program" in W._text_program_note(grow)
    assert "edit both rows" in W._text_program_note(fixed)


def test_replace_plan_scopes_on_originals_and_reports_fits():
    rows = [
        _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True),
        _row(GAME, "EBIRAH", budget=96, grow=True),
        _row(GAME, "BATTLE VS EBIRAH SHOT TIMER", budget=96, grow=True),
        _row(SCENE, "EBIRAH RULES"),                     # scene: grows
        _row(SCENE, "Ebirah wins", "EBIRAH!"),           # edited, lower-case
        _row(GAME, "TILT", budget=4),
        _row(GAME, "EBIRAH!", budget=7),                 # fixed slot
    ]
    plan = W._text_replace_plan(rows, "EBIRAH", "BIOLLANTE")
    assert [p["index"] for p in plan] == [0, 1, 2, 3, 6]
    assert [p["new"] for p in plan] == [
        "GODZILLA VS BIOLLANTE", "BIOLLANTE", "BATTLE VS BIOLLANTE SHOT TIMER",
        "BIOLLANTE RULES", "BIOLLANTE!"]
    assert [p["fits"] for p in plan] == [True, True, True, True, False]
    # Match case off reaches the lower-case original too — matched on the
    # ORIGINAL, never the edit — and keeps the rest of the string intact.
    loose = W._text_replace_plan(rows, "ebirah", "BIOLLANTE", match_case=False)
    assert [p["index"] for p in loose] == [0, 1, 2, 3, 4, 6]
    assert loose[4]["new"] == "BIOLLANTE wins"
    assert loose[4]["fits"] is True                # a scene row grows
    assert loose[5]["fits"] is False               # 10 bytes in a 7 slot
    assert W._text_replace_plan(rows, "", "X") == []
    # every occurrence in a line is replaced
    assert W._text_replace_plan(
        [_row(GAME, "EBIRAH VS EBIRAH", budget=96, grow=True)],
        "EBIRAH", "GIGAN")[0]["new"] == "GIGAN VS GIGAN"


def test_split_edit_finds_the_one_changed_word():
    assert W._text_split_edit("GODZILLA VS EBIRAH STARTED",
                              "GODZILLA VS BIOLLANTE STARTED") == (
        "EBIRAH", "BIOLLANTE")
    assert W._text_split_edit("MEGALON", "SPACE GODZILLA") == (
        "MEGALON", "SPACE GODZILLA")
    assert W._text_split_edit("EBIRAH", "EBIRAH") is None
    assert W._text_split_edit("", "X") is None
    assert W._text_split_edit("AB", "AXB") is None         # pure insertion


def test_pending_text_status_names_the_grow_path():
    longer = _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
                  grow=True)
    same = _row(GAME, "TILT", "TOLT", 96, grow=True)
    fixed = _row(GAME, "EBIRAH", "GIGAN!", 18)
    assert W._pending_text_status(longer) == W._PENDING_TEXT_GROWS
    assert W._pending_text_status(longer, grow_on=False) == \
        W._PENDING_TEXT_GROW_OFF
    assert W._pending_text_status(same) == W._PENDING_TEXT
    assert W._pending_text_status(fixed) == W._PENDING_TEXT
    # a scene row: longer = the scene is rewritten; same length = in place
    scene_longer = _row(SCENE, "TILT", "TILT WARNING")
    scene_same = _row(SCENE, "REPLAY", "SAVED!")
    assert W._pending_text_status(scene_longer) == W._PENDING_TEXT_GROWS_SCENE
    assert W._pending_text_status(scene_longer, grow_on=False) == \
        W._PENDING_TEXT_GROW_OFF
    assert W._pending_text_status(scene_same) == W._PENDING_TEXT


# ---------------------------------------------------------------------------
# Tk
# ---------------------------------------------------------------------------

def test_apply_accepts_35_bytes_on_a_96_row_and_refuses_97(app, tmp_path,
                                                             monkeypatch):
    assets = str(tmp_path)
    w = app.window
    _load(w, assets, [
        _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=96, grow=True)])
    iid = _select(w, "BATTLE VS MEGALON SHOT TIMER")
    assert w._text_tree.set(iid, "max") == "96 (grows)"
    assert "can grow" in w._text_scene_full_var.get()

    new = "BATTLE VS SPACE GODZILLA SHOT TIMER"
    assert len(new) == 35
    w.text_new_var.set(new)
    w._text_update_budget()
    assert w.text_budget_var.get().startswith("35 / 96 bytes")
    assert "new area of the game program" in w.text_budget_var.get()
    assert "too long" not in w.text_budget_var.get()
    assert _state(w._text_apply_btn) == "normal"
    w._text_apply_edit()
    assert tm.changed(assets) == {
        GAME: [("BATTLE VS MEGALON SHOT TIMER", new)]}
    assert w._text_tree.set(iid, "new") == new

    warned = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showwarning",
        lambda title, msg, **kw: warned.append(msg))
    w.text_new_var.set("X" * 97)
    w._text_update_budget()
    assert "too long" in w.text_budget_var.get()
    assert _state(w._text_apply_btn) == "disabled"
    w._text_apply_edit()
    assert warned and "96" in warned[0] and "longest a line" in warned[0]
    assert tm.changed(assets) == {
        GAME: [("BATTLE VS MEGALON SHOT TIMER", new)]}   # unchanged


def test_apply_refuses_30_bytes_on_a_28_byte_row_that_cannot_grow(
        app, tmp_path, monkeypatch):
    assets = str(tmp_path)
    w = app.window
    _load(w, assets, [
        _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28)])
    iid = _select(w, "BATTLE VS MEGALON SHOT TIMER")
    assert w._text_tree.set(iid, "max") == "28"
    assert "can grow" not in w._text_scene_full_var.get()
    warned = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showwarning",
        lambda title, msg, **kw: warned.append(msg))
    w.text_new_var.set("BATTLE VS BIOLLANTE SHOT TIMER")     # 30 bytes
    w._text_update_budget()
    assert w.text_budget_var.get().startswith("30 / 28 bytes")
    assert "too long" in w.text_budget_var.get()
    assert _state(w._text_apply_btn) == "disabled"
    w._text_apply_edit()
    assert warned and "only 28 fit" in warned[0]
    assert "patched in place" in warned[0]
    assert tm.changed(assets) == {}


def test_unused_row_says_so(app, tmp_path):
    assets = str(tmp_path)
    w = app.window
    _load(w, assets, [_row(GAME, "GEORGE GOMEZ", budget=12, unused=True)])
    _select(w, "GEORGE GOMEZ")
    assert "(not used by the game)" in w._text_scene_full_var.get()
    assert "(not used by the game)" in w.text_budget_var.get()


def test_replace_everywhere_updates_three_rows_and_skips_one(
        app, tmp_path, monkeypatch):
    assets = str(tmp_path)
    w = app.window
    _load(w, assets, [
        _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True),
        _row(GAME, "EBIRAH", budget=96, grow=True),
        _row(GAME, "BATTLE VS EBIRAH SHOT TIMER", budget=96, grow=True),
        _row(SCENE, "EBIRAH RULES"),                    # scene: grows
        _row(SCENE, "TILT"),
        _row(GAME, "EBIRAH!", budget=7),                # fixed 7-byte slot
    ])
    fp_before = w._current_write_fingerprint()
    # Opened from a row whose New text changed one word: Find / Replace are
    # pre-filled with that word.
    _select(w, "GODZILLA VS EBIRAH")
    w.text_new_var.set("GODZILLA VS BIOLLANTE")
    dlg = w._text_replace_everywhere()
    assert dlg is w._text_replace_dlg
    assert dlg.find_var.get() == "EBIRAH"
    assert dlg.repl_var.get() == "BIOLLANTE"
    assert dlg.case_var.get() is True
    assert dlg.count_var.get().startswith("4 of 5 matching rows fit")
    assert _state(dlg.apply_btn) == "normal"
    misfits = dlg.misfit_tree.get_children()
    assert len(misfits) == 1
    assert dlg.misfit_tree.item(misfits[0], "text") == "EBIRAH!"
    assert dlg.misfit_tree.item(misfits[0], "values")[0] == "BIOLLANTE!"

    told = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda title, msg, **kw: told.append(msg))
    fits, skipped = dlg.apply()
    assert len(fits) == 4 and len(skipped) == 1
    assert not dlg.dlg.winfo_exists()
    assert w._text_replace_dlg is None
    assert tm.changed(assets) == {
        GAME: [
            ("GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE"),
            ("EBIRAH", "BIOLLANTE"),
            ("BATTLE VS EBIRAH SHOT TIMER",
             "BATTLE VS BIOLLANTE SHOT TIMER")],
        SCENE: [("EBIRAH RULES", "BIOLLANTE RULES")]}
    assert told and "4 row(s) changed" in told[0]
    assert "EBIRAH!" in told[0] and "Max 7" in told[0]
    assert w._current_write_fingerprint() != fp_before
    # the list shows the new text on every changed row
    shown = {w._text_tree.item(i, "text"): w._text_tree.set(i, "new")
             for i in w._text_tree.get_children()}
    assert shown["EBIRAH"] == "BIOLLANTE"
    assert shown["EBIRAH RULES"] == "BIOLLANTE RULES"
    assert shown["EBIRAH!"] == ""
    app.root.update()

    # A word nothing matches plans nothing; an empty Find is not a search.
    dlg = w._text_replace_everywhere()
    dlg.find_var.set("MOTHRA")
    assert dlg.count_var.get().startswith("0 of 0")
    assert _state(dlg.apply_btn) == "disabled"
    assert dlg.apply() is None
    dlg.close()
    app.root.update()


def test_grow_setting_round_trips_and_lands_in_the_environment(
        app, tmp_path, monkeypatch):
    import pinball_decryptor.app as app_mod
    monkeypatch.setenv("PAD_STERN_TEXT_GROW", os.environ.get(
        "PAD_STERN_TEXT_GROW", "1"))
    w = app.window
    # default on, mirrored at startup
    assert w.write_text_grow_var.get() is True
    assert w.text_grow_enabled() is True
    assert os.environ["PAD_STERN_TEXT_GROW"] == "1"

    w.write_text_grow_var.set(False)
    w._on_write_text_grow_toggle()
    assert app._settings["text_grow"] is False
    assert os.environ["PAD_STERN_TEXT_GROW"] == "0"
    with open(app_mod.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f)["text_grow"] is False
    assert app._text_grow_setting() is False

    w.write_text_grow_var.set(True)
    w._on_write_text_grow_toggle()
    assert os.environ["PAD_STERN_TEXT_GROW"] == "1"
    with open(app_mod.SETTINGS_FILE, encoding="utf-8") as f:
        assert json.load(f)["text_grow"] is True
    # a settings file that never saw the key reads as on
    app._settings.pop("text_grow", None)
    assert app._text_grow_setting() is True


def test_write_tab_pending_row_says_the_game_program_grows(app, tmp_path):
    from pinball_decryptor.core.registry import all_manufacturers
    assets = str(tmp_path)
    stern = next(m for m in all_manufacturers() if m.key == "stern")
    app._on_manufacturer_change(stern)
    app.root.update()
    w = app.window
    assert w._write_text_grow_row.winfo_manager() == "pack"
    _load(w, assets, [
        _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
             grow=True),
        _row(GAME, "TILT", "TOLT", 96, grow=True),
        _row(SCENE, "REPLAY", "SAVED!"),
        _row(SCENE, "GAME OVER", "GAME OVER, MAN"),     # longer: scene grows
    ])
    w.write_text_grow_var.set(True)
    sid = w._write_preview_scan_id
    n = w._add_pending_preview_rows(assets, sid)
    assert n == 4
    by_status = {}
    for rel, ext, status, tag in w._write_preview_rows:
        by_status.setdefault(status, []).append(rel)
    assert by_status[W._PENDING_TEXT_GROWS] == [
        "GODZILLA VS EBIRAH  →  GODZILLA VS BIOLLANTE"]
    assert by_status[W._PENDING_TEXT_GROWS_SCENE] == [
        "GAME OVER  →  GAME OVER, MAN"]
    assert sorted(by_status[W._PENDING_TEXT]) == [
        "REPLAY  →  SAVED!", "TILT  →  TOLT"]

    # Advanced off: the over-long edits are listed as skipped, the rest stay
    w.write_text_grow_var.set(False)
    w._on_write_text_grow_toggle()
    statuses = sorted(s for _r, e, s, _t in w._write_preview_rows
                      if e == "text")
    assert statuses == sorted([W._PENDING_TEXT, W._PENDING_TEXT,
                               W._PENDING_TEXT_GROW_OFF,
                               W._PENDING_TEXT_GROW_OFF])
    assert len(w._write_preview_tree.get_children()) == 4
    w.write_text_grow_var.set(True)
    w._on_write_text_grow_toggle()
    assert W._PENDING_TEXT_GROWS in [
        s for _r, _e, s, _t in w._write_preview_rows]
