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

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""

import json
import os
import struct
import time
import wave

from pinball_decryptor.core import staged_changes
from tests.webui_harness import web_app

RELS = ["audio/idx0006.wav", "audio/idx0007.wav",
        "audio/music_cat07_0003.wav"]


def _wav(path, seconds=0.2, rate=8000, amp=2000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = int(seconds * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", amp if i % 16 < 8 else -amp)
                               for i in range(n)))


def _wait(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _folder(folder, rels=RELS):
    for rel in rels:
        _wav(str(folder / rel))
    return folder


def _scan(w, folder):
    """Scan *folder* (which is also the Write destination, so the sidecar
    lands there) onto the audio tab; the audio service."""
    w.run(lambda: w.window.write_assets_var.set(str(folder)))
    w.call("ui.select_tab", "audio")
    assert _wait(w, lambda: len(w.state("audio")["rows"]) > 0
                 and not w.state("audio")["scanning"]), w.state("audio")
    assert _wait(w, lambda: "still checking" not in
                 (w.state("audio")["status"] or ""))
    svc = w.window.service("audio")
    w.run(svc._cancel_select_job)
    return svc


def _lvl(w, rel):
    return {r["k"]: r for r in w.state("audio")["rows"]}[rel]["lvl"]


def _select(w, rel):
    w.call("audio.select", [rel])


def test_the_level_column_and_db_box_are_stern_only(tmp_path):
    """An inert control is worse than none: the box and the column ride the
    audio_level_offset capability, like Loop (BOF) and Full (JJP) do."""
    with web_app(tmp_path, mfr="stern") as w:
        st = w.state("audio")
        assert st["col"] == "lvl"
        assert st["level_cap"] is True

        w.call("ui.pick_manufacturer", "cgc")
        w.drain()
        st = w.state("audio")
        assert st["col"] != "lvl"
        assert st["level_cap"] is False


def test_a_clips_level_is_its_own_and_lands_in_the_sidecar(tmp_path):
    """The report, answered: setting the box on one row must move that row and
    nothing else, and must survive the app being closed."""
    folder = _folder(tmp_path / "ex")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)

        _select(w, RELS[0])
        assert w.call("audio.set_level", RELS[0], "6") is True

        assert svc._level == {RELS[0]: 6}
        assert _lvl(w, RELS[0]) == "+6 dB"
        assert _lvl(w, RELS[1]) == ""                    # the neighbour
        saved = staged_changes.load(str(folder))
        assert saved["audio_levels"] == {RELS[0]: 6}

        # Selecting another row shows ITS value, not the one still on screen
        # — otherwise the next keystroke would land on the wrong slot.
        _select(w, RELS[1])
        assert w.state("audio")["level"] == "0"
        _select(w, RELS[0])
        assert w.state("audio")["level"] == "6"

        # Back to 0 clears the entry rather than storing a zero.
        w.call("audio.set_level", RELS[0], "0")
        assert svc._level == {}
        assert staged_changes.load(str(folder))["audio_levels"] == {}


def test_a_half_typed_value_never_lands_on_a_slot(tmp_path):
    """The box is typed into, so it passes through "-" on the way to "-4"."""
    folder = _folder(tmp_path / "ex")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)
        _select(w, RELS[0])
        assert w.call("audio.set_level", RELS[0], "-") is False
        assert RELS[0] not in svc._level
        w.call("audio.set_level", RELS[0], "-4")
        assert svc._level[RELS[0]] == -4
        # …and it is held to the range the encoder honours.
        w.call("audio.set_level", RELS[0], "40")
        assert svc._level[RELS[0]] == 12


def test_apply_to_all_shown_follows_the_type_filter(tmp_path):
    """The middle ground between one clip and the whole build: with the list
    filtered to Music, "Apply to all shown" lifts the songs and leaves the
    callouts where they are."""
    folder = _folder(tmp_path / "ex")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)

        w.call("ui.set", "audio", "search", "music_cat")   # the same
        w.drain()                                   # narrowing Type does
        assert svc._visible_rels == [RELS[2]]

        w.answers.append("yes")
        assert w.call("audio.level_apply_all", "4") is True
        assert svc._level == {RELS[2]: 4}

        w.call("ui.set", "audio", "search", "")
        w.drain()
        assert _lvl(w, RELS[2]) == "+4 dB"
        assert _lvl(w, RELS[0]) == ""

        # The whole list, cleared the same way.
        w.answers.append("yes")
        w.call("audio.level_apply_all", "0")
        assert svc._level == {}


def test_levels_come_back_from_the_sidecar_on_the_next_scan(tmp_path):
    """A level set weeks ago has to be there when the folder is re-opened —
    and a slot that has since vanished must not be resurrected."""
    folder = _folder(tmp_path / "ex")
    (folder / staged_changes.SIDE_CAR).write_text(json.dumps({
        "audio_levels": {RELS[0]: -3, "audio/idx9999.wav": 5}}),
        encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)
        assert svc._level == {RELS[0]: -3}
        assert _lvl(w, RELS[0]) == "-3 dB"


def test_the_preview_is_drawn_and_played_at_the_clips_level(tmp_path,
                                                            monkeypatch):
    """"the spectrum image shows the db adjustment? it's hard to tell" — it
    didn't: the strip was the file exactly as handed over.  Now the offset
    goes through the render and through playback (the page's player plays a
    pane at its ``gain``), so the box is something you can see and hear."""
    from pinball_decryptor.webui import audio_media
    folder = _folder(tmp_path / "ex")
    rep = folder / "mine.wav"
    _wav(str(rep))

    drawn = []

    def fake_render(path, width=800, height=90, gain_db=0.0):
        drawn.append((path, gain_db))
        return None
    monkeypatch.setattr(audio_media, "spectrogram_file", fake_render)

    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)

        def _load():
            svc._assign[RELS[0]] = str(rep)
            svc._level[RELS[0]] = 6
            svc._load_track(RELS[0])
        w.run(_load)
        assert _wait(w, lambda: (str(rep), 6) in drawn)

        panes = w.state("audio")["panes"]
        assert panes["rep"]["gain"] == 6
        assert panes["rep"]["path"] == str(rep)
        # the Original is the card's own sound and is never levelled
        assert panes["orig"]["gain"] == 0


def test_moving_the_box_redraws_the_loaded_clip(tmp_path, monkeypatch):
    """The redraw is debounced (it is an ffmpeg render per keystroke
    otherwise), and only re-renders when the number actually moved."""
    from pinball_decryptor.webui import audio_media
    monkeypatch.setattr(audio_media, "spectrogram_file",
                        lambda *a, **k: None)
    folder = _folder(tmp_path / "ex")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, folder)
        _select(w, RELS[0])
        w.run(svc._cancel_select_job)

        def _loaded():
            svc._current_rel = RELS[0]
            pane = dict(svc._panes["rep"])
            pane["path"] = str(folder / RELS[0])
            pane["gain"] = 0.0
            svc._panes["rep"] = pane
        w.run(_loaded)

        w.call("audio.set_level", RELS[0], "4")
        assert svc._panes["rep"]["gain"] == 0.0     # not yet — debounced
        assert svc._level_job is not None
        assert _wait(w, lambda: svc._panes["rep"]["gain"] == 4, timeout=3)
