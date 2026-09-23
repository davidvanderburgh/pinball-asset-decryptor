"""Guards for Replace Audio's Properties (F2) rename — a tester b23.

His report: "I hit F2. Changed a name and a type. Hit enter. Came back and the
list had the old values and when I clicked on it, nothing loaded. The whole
line was unresponsive. I had to rescan for it to update. After updating the
replacement column said 'changed on disk' even though the file was not
touched."

Both halves come from the same place: the file is renamed on disk first, and
anything that raised afterwards — re-pointing the extract baseline opens it for
writing, and the assets folder is routinely a NAS share — skipped the list
refresh.  The list then held a row keyed by the OLD rel path, which is not
in the slot index, so clicking it loaded nothing; and the baseline still
named the old file, so the next scan called the untouched audio "changed on
disk".

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import os
import struct
import time
import wave

from pinball_decryptor.core import checksums
from tests.webui_harness import web_app

REL = "audio/idx0001.wav"
NEW_REL = "audio/idx0001 - Cowabunga.wav"


def _wav(path, seconds=0.2, rate=8000, amp=2000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = int(seconds * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", amp if i % 16 < 8 else -amp)
                               for i in range(n)))


def _folder(tmp_path, *extra):
    """An assets folder with a baselined slot (plus any *extra* rels)."""
    assets = str(tmp_path / "proj")
    for rel in (REL,) + extra:
        _wav(os.path.join(assets, *rel.split("/")))
    checksums.generate_checksums(assets)
    return assets


def _wait(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _load(w, assets):
    """Point the project folder at *assets* and scan it; the audio service."""
    w.run(lambda: w.window.write_assets_var.set(assets))
    w.call("ui.select_tab", "audio")
    assert _wait(w, lambda: len(w.state("audio")["rows"]) > 0
                 and not w.state("audio")["scanning"]), w.state("audio")
    assert _wait(w, lambda: "still checking" not in
                 (w.state("audio")["status"] or ""))
    svc = w.window.service("audio")
    # a row selected by the scan must not load behind the test's back
    w.run(svc._cancel_select_job)
    return svc


def _rows(w):
    return [r["k"] for r in w.state("audio")["rows"]]


def _rename(w, rel, name, cat="sfx"):
    assert w.call("audio.rename", rel, name, cat) is True


def test_rename_updates_the_row_and_the_row_still_works(tmp_path):
    assets = _folder(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        _rename(w, REL, "Cowabunga")

        assert os.path.isfile(os.path.join(assets, *NEW_REL.split("/")))
        assert _rows(w) == [NEW_REL]              # re-keyed, not the old rel
        # The row resolves, which is what "unresponsive" meant when it didn't.
        assert NEW_REL in svc._by_rel
        assert svc._cats.get(NEW_REL) == "sfx"


def test_rename_leaves_the_slot_clean_against_the_baseline(tmp_path):
    """Nothing about the audio changed, so nothing may read as changed."""
    assets = _folder(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _rename(w, REL, "Cowabunga")
    assert checksums.changed_rels(assets, [NEW_REL]) == set()


def test_a_failed_baseline_repoint_still_repaints_the_list(tmp_path,
                                                           monkeypatch):
    """The NAS-hiccup shape.  The rename is already on disk by then, so the
    list must show it and the failure must be said out loud — not swallowed
    with the refresh."""
    assets = _folder(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        monkeypatch.setattr(
            "pinball_decryptor.core.checksums.rename_in_baseline",
            lambda *a, **k: (_ for _ in ()).throw(OSError("network path is gone")))
        lines = []
        monkeypatch.setattr(svc, "log",
                            lambda msg, *a, **k: lines.append(msg))
        _rename(w, REL, "Cowabunga")

        assert _rows(w) == [NEW_REL]
        assert NEW_REL in svc._by_rel
        assert any("baseline" in m for m in lines)


def test_rename_follows_the_slot_into_its_duplicate_group(tmp_path):
    """The dup-group cache is keyed by rel path and is otherwise only rebuilt
    by a rescan, so a rename used to evict the slot from its own group — which
    also silently broke "Apply to all copies" for the other copies."""
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)

        def _groups():
            svc._dup_groups = [("idx0001", "0:01.000", [REL, other])]
            svc._dup_scan_dir = assets
        w.run(_groups)
        _rename(w, REL, "Cowabunga")

        assert svc._dup_groups[0][2] == [NEW_REL, other]
        assert w.run(svc._dup_siblings, NEW_REL) == [other]
        assert w.run(svc._dup_siblings, other) == [NEW_REL]


# ---------------------------------------------------------------------------
# "Play through the list" (feedback batch 23 wish-list): select a file and it
# keeps going, so a whole card can be auditioned without clicking each row.
# ---------------------------------------------------------------------------

def _stub_loader(w, svc, played):
    def _fake_load(rel, autoplay=None):
        # Mirror the one side effect the select debounce depends on: the real
        # _load_track records the row it loaded, and a selection of the row
        # that is already current is skipped.
        svc._current_rel = rel
        played.append((rel, autoplay))

    def _install():
        svc._load_track = _fake_load
        svc._current_rel = REL
    w.run(_install)


def test_play_through_advances_to_the_next_visible_row(tmp_path):
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        w.call("ui.set", "audio", "play_through", True)
        played = []
        _stub_loader(w, svc, played)

        assert w.call("audio.clip_finished", "orig") is True
        # The step is deferred off the player's own callback, so let the
        # pending after() land rather than assuming it already has.
        assert _wait(w, lambda: played, timeout=3)
        # Then keep going past the 250 ms select debounce, so a regression
        # that DID let the selection clobber the play-through load still
        # fails here instead of being raced past.
        time.sleep(0.6)
        w.drain()
        assert played == [(other, "orig")]


def test_play_through_stops_at_the_end_of_the_list(tmp_path, monkeypatch):
    assets = _folder(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        w.call("ui.set", "audio", "play_through", True)
        played, lines = [], []
        _stub_loader(w, svc, played)
        monkeypatch.setattr(svc, "log",
                            lambda msg, *a, **k: lines.append(msg))

        assert w.call("audio.clip_finished", "orig") is False
        time.sleep(0.3)
        w.drain()
        assert played == []
        assert any("end of the list" in m for m in lines)


def test_play_through_off_does_nothing(tmp_path):
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        w.call("ui.set", "audio", "play_through", False)
        played = []
        _stub_loader(w, svc, played)

        assert w.call("audio.clip_finished", "orig") is False
        time.sleep(0.3)
        w.drain()
        assert played == []


def test_visible_order_follows_the_list_not_the_scan(tmp_path):
    """It walks what the list shows, so a sort or a filter is respected."""
    other = "audio/idx0002.wav"
    assets = _folder(tmp_path, other)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        assert svc._visible_rels == [REL, other]
        w.call("audio.sort", "#0")                # reverse the name sort
        assert svc._visible_rels == [other, REL]
        assert w.run(svc._next_visible_rel, other) == REL
        assert w.run(svc._next_visible_rel, REL) is None
