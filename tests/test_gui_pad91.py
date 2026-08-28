"""PAD-91 — the loudness setting, per clip, on the tab where the clips are.

v0.171.0 put a "Replacement loudness" row in Advanced Audio Options.  The
tester who asked for it came straight back: "Wait will the sound boost affect
every single clip? It looks like if I change the setting on one, it changed it
on another one too" — and then "is there a way to have more control over this
per replacement? would be nice to have the option right on the audio
replacement tab (instead of buried in advanced)."

He was right about the behaviour: that row is one setting for the whole build.
So the Replace Audio tab now carries a dB box beside the Replacement preview
plus a Level column, both Stern-only (the capability), the values persist in
the folder's sidecar for the write pipeline to read, and "Apply to all shown"
covers the case in between one clip and everything — set Type to Music and
only the songs move.
"""

import json

import pytest

from pinball_decryptor.core import staged_changes
from pinball_decryptor.core.audio_slots import AudioSlot
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

RELS = ["audio/idx0006.wav", "audio/idx0007.wav",
        "audio/music_cat07_0003.wav"]


def _stern_with_slots(app, manufacturers_by_key, folder, rels=RELS):
    """A Stern window with *rels* scanned out of *folder* (which is also the
    Write destination, so _save_staged_changes writes its sidecar)."""
    app._on_manufacturer_change(manufacturers_by_key["stern"])
    app.root.update()
    win = app.window
    (folder / "audio").mkdir(parents=True, exist_ok=True)
    for rel in rels:
        (folder / rel).write_bytes(b"RIFF")
    win.write_assets_var.set(str(folder))
    win._audio_slots = [
        AudioSlot(rel_path=r, abs_path=str(folder / r), ext=".wav",
                  info=None, size=4) for r in rels]
    win._audio_slots_by_rel = {s.rel_path: s for s in win._audio_slots}
    win._audio_scan_dir = str(folder)
    win._refresh_audio_list()
    app.root.update()
    return win


def _select(app, win, rel):
    win._audio_tree.selection_set(rel)
    app.root.update()


def test_the_level_column_and_db_box_are_stern_only(app, manufacturers_by_key,
                                                    tmp_path):
    """An inert control is worse than none: the box and the column ride the
    audio_level_offset capability, like Loop (BOF) and Full (JJP) do."""
    win = _stern_with_slots(app, manufacturers_by_key, tmp_path / "ex")
    assert "lvl" in win._audio_tree["displaycolumns"]
    assert win._audio_level_row.winfo_manager() == "grid"

    app._on_manufacturer_change(manufacturers_by_key["cgc"])
    app.root.update()
    assert "lvl" not in win._audio_tree["displaycolumns"]
    assert win._audio_level_row.winfo_manager() != "grid"


def test_a_clips_level_is_its_own_and_lands_in_the_sidecar(
        app, manufacturers_by_key, tmp_path):
    """The report, answered: setting the box on one row must move that row and
    nothing else, and must survive the app being closed."""
    folder = tmp_path / "ex"
    win = _stern_with_slots(app, manufacturers_by_key, folder)

    _select(app, win, RELS[0])
    win._audio_level_var.set("6")
    app.root.update()

    assert win._audio_level_db == {RELS[0]: 6}
    assert win._audio_tree.set(RELS[0], "lvl") == "+6 dB"
    assert win._audio_tree.set(RELS[1], "lvl") == ""     # the neighbour
    saved = staged_changes.load(str(folder))
    assert saved["audio_levels"] == {RELS[0]: 6}

    # Selecting another row shows ITS value, not the one still on screen —
    # otherwise the next keystroke would land on the wrong slot.
    _select(app, win, RELS[1])
    assert win._audio_level_var.get() == "0"
    _select(app, win, RELS[0])
    assert win._audio_level_var.get() == "6"

    # Back to 0 clears the entry rather than storing a zero.
    win._audio_level_var.set("0")
    app.root.update()
    assert win._audio_level_db == {}
    assert staged_changes.load(str(folder))["audio_levels"] == {}


def test_a_half_typed_value_never_lands_on_a_slot(app, manufacturers_by_key,
                                                  tmp_path):
    """The box is typed into, so it passes through "-" on the way to "-4"."""
    win = _stern_with_slots(app, manufacturers_by_key, tmp_path / "ex")
    _select(app, win, RELS[0])
    win._audio_level_var.set("-")
    app.root.update()
    assert RELS[0] not in win._audio_level_db
    win._audio_level_var.set("-4")
    app.root.update()
    assert win._audio_level_db[RELS[0]] == -4
    # …and it is held to the range the encoder honours.
    win._audio_level_var.set("40")
    app.root.update()
    assert win._audio_level_db[RELS[0]] == 12


def test_apply_to_all_shown_follows_the_type_filter(app, manufacturers_by_key,
                                                    tmp_path, monkeypatch):
    """The middle ground between one clip and the whole build: with the list
    filtered to Music, "Apply to all shown" lifts the songs and leaves the
    callouts where they are."""
    from pinball_decryptor.gui import main_window as mw
    folder = tmp_path / "ex"
    win = _stern_with_slots(app, manufacturers_by_key, folder)
    monkeypatch.setattr(mw.messagebox, "askyesno", lambda *a, **k: True)

    win.audio_search_var.set("music_cat")       # the same narrowing the
    app.root.update()                           # Type filter does
    assert win._audio_visible_rels() == [RELS[2]]

    win._audio_level_var.set("4")
    win._audio_level_apply_all()
    app.root.update()
    assert win._audio_level_db == {RELS[2]: 4}

    win.audio_search_var.set("")
    app.root.update()
    assert win._audio_tree.set(RELS[2], "lvl") == "+4 dB"
    assert win._audio_tree.set(RELS[0], "lvl") == ""

    # The whole list, cleared the same way.
    win._audio_level_var.set("0")
    win._audio_level_apply_all()
    app.root.update()
    assert win._audio_level_db == {}


def test_levels_come_back_from_the_sidecar_on_the_next_scan(
        app, manufacturers_by_key, tmp_path):
    """A level set weeks ago has to be there when the folder is re-opened —
    and a slot that has since vanished must not be resurrected."""
    folder = tmp_path / "ex"
    (folder / "audio").mkdir(parents=True)
    (folder / staged_changes.SIDE_CAR).write_text(json.dumps({
        "audio_levels": {RELS[0]: -3, "audio/idx9999.wav": 5}}),
        encoding="utf-8")
    win = _stern_with_slots(app, manufacturers_by_key, folder, rels=RELS)
    # _stern_with_slots fakes the scan; drive the real restore path.
    win._audio_scan_dir = ""
    win._populate_audio_after_scan(win._audio_slots, win._audio_scan_id,
                                   str(folder))
    app.root.update()
    assert win._audio_level_db == {RELS[0]: -3}
    assert win._audio_tree.set(RELS[0], "lvl") == "-3 dB"


def test_the_advanced_dialog_says_it_is_the_build_wide_one(
        app, manufacturers_by_key, tmp_path):
    """What he actually asked ("will it affect every single clip?") is now
    answered where he asked it, with a pointer to the per-clip box."""
    import tkinter as tk

    win = _stern_with_slots(app, manufacturers_by_key, tmp_path / "ex")
    win._open_audio_advanced()
    app.root.update()
    dlg = [c for c in win.root.winfo_children()
           if isinstance(c, tk.Toplevel)][-1]

    def texts(w):
        out = [str(w.cget("text"))] if "text" in w.keys() else []
        for c in w.winfo_children():
            out += texts(c)
        return out

    blob = "\n".join(texts(dlg))
    assert "WHOLE build" in blob
    assert "Loudness for this clip" in blob
    dlg.destroy()
