"""PAD-894: Audio > More > Rename from callouts.csv.

A tester corrected hundreds of Auto-name transcripts in callouts.csv (by hand
and in a spreadsheet) and wanted them all back as file names in one go, with
characters a file name can't hold turned into underscores.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import csv
import json
import os

import pytest

from pinball_decryptor.core import checksums
from pinball_decryptor.core import name_memory as NM
from pinball_decryptor.core.transcribe import CalloutsFile
from pinball_decryptor.webui import compat
from tests.test_gui_audio_rename import _load, _rows, _wav
from tests.webui_harness import web_app

HEARD = {  # rel -> what Whisper heard (the file's name now)
    "audio/idx0001 - Jack pot.wav": "Jack pot",
    "audio/idx0002 - Kai Joo award.wav": "Kai Joo award",
    "audio/idx0003 - Monster lock is lit.wav": "Monster lock is lit",
}


@pytest.fixture
def boxes(monkeypatch, tmp_path):
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE", str(tmp_path / "audio_names.json"))
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "showerror", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda t, m: said.append(m) or True)
    return said


def _project(tmp_path, rows, *, delimiter=",", encoding="utf-8", extra=()):
    """A baselined project of HEARD (+ *extra*) and a callouts.csv of *rows*
    ``(folder, file, text)``."""
    assets = str(tmp_path / "proj")
    for i, rel in enumerate(list(HEARD) + list(extra)):
        p = os.path.join(assets, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _wav(p, amp=1000 + 100 * i)          # distinct bytes, distinct names
    checksums.generate_checksums(assets)
    with open(os.path.join(assets, "callouts.csv"), "w", encoding=encoding,
              newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(["folder", "file", "seconds", "classification", "text"])
        for folder, fname, text in rows:
            w.writerow([folder, fname, "0.200", "speech", text])
    return assets


def _run(w):
    assert w.call("audio.rename_from_callouts") is True


def test_corrected_text_renames_every_sound_and_the_csv_follows(tmp_path, boxes):
    assets = _project(tmp_path, [
        ("audio", "idx0001 - Jack pot.wav", "JACKPOT!"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kaiju award: 2x / \"super\"?"),
        ("audio", "idx0003 - Monster lock is lit.wav", "Monster lock is lit"),
    ])
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        _run(w)
        want = ["audio/idx0001 - JACKPOT!.wav",
                "audio/idx0002 - Kaiju award_ 2x _ _super__.wav",
                "audio/idx0003 - Monster lock is lit.wav"]
        assert sorted(_rows(w)) == want
        assert all(rel in svc._by_rel for rel in want)
        assert "Renamed 2 sound(s)." in boxes[-1]
    assert sorted(os.listdir(os.path.join(assets, "audio"))) == [
        r.rpartition("/")[2] for r in want]
    # untouched audio: nothing reads as changed on disk
    assert checksums.changed_rels(assets, want) == set()
    # the CSV names the files as they are now, so a second press is a no-op
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    assert [cf.get(r, "file") for r in cf.rows] == [r.rpartition("/")[2] for r in want]
    assert [cf.get(r, "text") for r in cf.rows][0] == "JACKPOT!"
    # and remembered for future extracts, like a Properties rename
    with open(NM.AUDIO_NAMES_FILE, encoding="utf-8") as f:
        assert {v["label"] for v in json.load(f).values()} == {
            "JACKPOT!", "Kaiju award_ 2x _ _super__"}


def test_a_second_press_has_nothing_to_do(tmp_path, boxes):
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav", "Jackpot")])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
        _run(w)
    assert "already has the name" in boxes[-1]


def test_rows_find_their_sound_by_idx_when_the_name_moved_on(tmp_path, boxes):
    """The sound was renamed in Properties after the CSV was written: its row
    still finds it by idx number in the same folder."""
    assets = _project(tmp_path, [
        ("audio", "idx0001 - Something else.wav", "Jackpot"),
        ("audio", "idx0099 - Not here.wav", "Gone"),
    ])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
        assert "audio/idx0001 - Jackpot.wav" in _rows(w)
    assert "1 row(s) name a sound this project doesn't have." in boxes[-1]


def test_assignments_follow_the_renamed_slot(tmp_path, boxes):
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav", "Jackpot")])
    mine = str(tmp_path / "mine.wav")
    _wav(mine)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets)
        w.run(lambda: svc._assign.__setitem__("audio/idx0001 - Jack pot.wav", mine))
        _run(w)
        assert svc._assign == {"audio/idx0001 - Jackpot.wav": mine}


def test_excel_semicolons_and_windows_1252_round_trip(tmp_path, boxes):
    """A French Excel saves the CSV back with ';' and Windows-1252."""
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav", "Ça c'est génial")],
                      delimiter=";", encoding="cp1252")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
        assert "audio/idx0001 - Ça c'est génial.wav" in _rows(w)
    with open(os.path.join(assets, "callouts.csv"), "rb") as f:
        raw = f.read()
    assert raw.startswith(b"folder;file;")
    assert "idx0001 - Ça c'est génial.wav".encode("cp1252") in raw


def test_blank_text_keeps_the_name(tmp_path, boxes):
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav", "")])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
        assert "audio/idx0001 - Jack pot.wav" in _rows(w)


def test_no_callouts_csv_says_where_one_comes_from(tmp_path, boxes):
    assets = _project(tmp_path, [])
    os.remove(os.path.join(assets, "callouts.csv"))
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename_from_callouts") is False
    assert "Auto-name call-outs" in boxes[-1]
