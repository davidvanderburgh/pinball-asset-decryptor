"""GUI guards for Replace Audio's Properties (F2) rename — monkeybug b23.

His report: "I hit F2. Changed a name and a type. Hit enter. Came back and the
list had the old values and when I clicked on it, nothing loaded. The whole
line was unresponsive. I had to rescan for it to update. After updating the
replacement column said 'changed on disk' even though the file was not
touched."

Both halves come from the same place: the file is renamed on disk first, and
anything that raised afterwards — re-pointing the extract baseline opens it for
writing, and the assets folder is routinely a NAS share — skipped the list
refresh.  The tree then held a row whose iid was the OLD rel path, which is not
in _audio_slots_by_rel, so clicking it loaded nothing; and the baseline still
named the old file, so the next scan called the untouched audio "changed on
disk".
"""
import os
import time

import pytest

from pinball_decryptor.core import checksums
from pinball_decryptor.core.audio_slots import AudioSlot
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

REL = "audio/idx0001.wav"
NEW_REL = "audio/idx0001 - Cowabunga.wav"


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    return app.window


def _folder(tmp_path, *extra):
    """An assets folder with a baselined slot (plus any *extra* rels)."""
    assets = str(tmp_path)
    for rel in (REL,) + extra:
        path = os.path.join(assets, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"RIFF____WAVEfmt ")
    checksums.generate_checksums(assets)
    return assets


def _slot(assets, rel):
    return AudioSlot(rel_path=rel,
                     abs_path=os.path.join(assets, *rel.split("/")),
                     ext=".wav", info=None, size=16)


def _load(app, assets, rels):
    w = _stern(app)
    slots = [_slot(assets, r) for r in rels]
    w._audio_slots = slots
    w._audio_slots_by_rel = {s.rel_path: s for s in slots}
    w._audio_scan_dir = assets
    w.write_assets_var.set(assets)
    w._audio_changed_on_disk = set()
    w._refresh_audio_list()
    app.root.update()
    return w


def _rename(w, rel, name, cat="sfx"):
    w._ask_audio_name = lambda *a, **k: (name, cat)
    w._audio_rename_slot(rel)


def test_rename_updates_the_row_and_the_row_still_works(app, tmp_path):
    assets = _folder(tmp_path)
    w = _load(app, assets, [REL])
    _rename(w, REL, "Cowabunga")

    assert os.path.isfile(os.path.join(assets, *NEW_REL.split("/")))
    rows = w._audio_tree.get_children()
    assert list(rows) == [NEW_REL]              # re-keyed, not the old rel
    assert w._audio_tree.item(NEW_REL, "text") == NEW_REL
    # The row resolves, which is what "unresponsive" meant when it didn't.
    assert NEW_REL in w._audio_slots_by_rel
    assert w._audio_categories.get(NEW_REL) == "sfx"


def test_rename_leaves_the_slot_clean_against_the_baseline(app, tmp_path):
    """Nothing about the audio changed, so nothing may read as changed."""
    assets = _folder(tmp_path)
    w = _load(app, assets, [REL])
    _rename(w, REL, "Cowabunga")
    assert checksums.changed_rels(assets, [NEW_REL]) == set()


def test_a_failed_baseline_repoint_still_repaints_the_list(app, tmp_path,
                                                           monkeypatch):
    """The NAS-hiccup shape.  The rename is already on disk by then, so the
    list must show it and the failure must be said out loud — not swallowed
    with the refresh."""
    assets = _folder(tmp_path)
    w = _load(app, assets, [REL])
    monkeypatch.setattr(
        "pinball_decryptor.core.checksums.rename_in_baseline",
        lambda *a, **k: (_ for _ in ()).throw(OSError("network path is gone")))
    lines = []
    monkeypatch.setattr(w, "append_log",
                        lambda msg, *a, **k: lines.append(msg))
    _rename(w, REL, "Cowabunga")

    assert list(w._audio_tree.get_children()) == [NEW_REL]
    assert NEW_REL in w._audio_slots_by_rel
    assert any("baseline" in m for m in lines)


def test_rename_follows_the_slot_into_its_duplicate_group(app, tmp_path):
    """The dup-group cache is keyed by rel path and is otherwise only rebuilt
    by a rescan, so a rename used to evict the slot from its own group — which
    also silently broke "Apply to all copies" for the other copies."""
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    w = _load(app, assets, [REL, other])
    w._audio_dup_groups = [("idx0001", "0:01.000", [REL, other])]
    w._audio_dup_scan_dir = assets
    _rename(w, REL, "Cowabunga")

    assert w._audio_dup_groups[0][2] == [NEW_REL, other]
    assert w._audio_dup_siblings(NEW_REL) == [other]
    assert w._audio_dup_siblings(other) == [NEW_REL]


def test_tk_callback_errors_reach_the_log(app):
    """A callback that raises used to print to a stderr a windowed build has
    nowhere to show, so the control just looked dead."""
    w = _stern(app)
    lines = []
    w.append_log = lambda msg, *a, **k: lines.append(msg)
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        app.root.report_callback_exception(*sys.exc_info())
    assert len(lines) == 1
    assert "boom" in lines[0] and "ValueError" in lines[0]


# ---------------------------------------------------------------------------
# "Play through the list" (monkeybug batch 23 wish-list): select a file and it
# keeps going, so a whole card can be auditioned without clicking each row.
# ---------------------------------------------------------------------------

def test_play_through_advances_to_the_next_visible_row(app, tmp_path):
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    w = _load(app, assets, [REL, other])
    w.audio_play_through_var.set(True)
    w._audio_current_rel = REL
    played = []

    def _fake_load(rel, autoplay=None):
        # Mirror the one side effect the debounce depends on: the real
        # _audio_load_track records the row it loaded, and
        # _audio_preview_selected skips a row that is already current.  A stub
        # that leaves _audio_current_rel stale makes the late TreeviewSelect
        # (it fires a turn late) fail that guard and reload the row with
        # autoplay=None -- which is a bug in the stub, not in the app, but it
        # failed this test on macOS CI where the event lands inside the wait.
        w._audio_current_rel = rel
        played.append((rel, autoplay))

    w._audio_load_track = _fake_load

    w._audio_on_clip_finished(w._audio_pane_orig)
    # The step is deferred off the player's own callback, so let the pending
    # after() land rather than assuming it already has.
    deadline = time.monotonic() + 3
    while not played and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    # Then keep pumping past the 250 ms select debounce, so a regression that
    # DID let the selection clobber the play-through load still fails here
    # instead of being raced past.
    settle = time.monotonic() + 0.6
    while time.monotonic() < settle:
        app.root.update()
        time.sleep(0.02)
    assert played == [(other, "orig")]


def test_play_through_stops_at_the_end_of_the_list(app, tmp_path):
    assets = _folder(tmp_path)
    w = _load(app, assets, [REL])
    w.audio_play_through_var.set(True)
    w._audio_current_rel = REL
    played, lines = [], []
    w._audio_load_track = lambda rel, autoplay=None: played.append(rel)
    w.append_log = lambda msg, *a, **k: lines.append(msg)

    w._audio_on_clip_finished(w._audio_pane_orig)
    app.root.update()
    assert played == []
    assert any("end of the list" in m for m in lines)


def test_play_through_off_does_nothing(app, tmp_path):
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    w = _load(app, assets, [REL, other])
    w.audio_play_through_var.set(False)
    w._audio_current_rel = REL
    played = []
    w._audio_load_track = lambda rel, autoplay=None: played.append(rel)

    w._audio_on_clip_finished(w._audio_pane_orig)
    app.root.update()
    assert played == []


def test_visible_order_follows_the_list_not_the_scan(app, tmp_path):
    """It walks what the tree shows, so a sort or a filter is respected."""
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    w = _load(app, assets, [REL, other])
    assert w._audio_visible_rels() == [REL, other]
    w._audio_sort = ("#0", True)              # reverse the name sort
    w._refresh_audio_list()
    assert w._audio_visible_rels() == [other, REL]
    assert w._audio_next_visible_rel(other) == REL
    assert w._audio_next_visible_rel(REL) is None
