"""PAD-1048: Audio > More > Update callouts.csv from the names.

A tester renamed sounds by hand in Audio Properties and wanted callouts.csv to
follow, so the names are kept with the rest of the work: Rename from
callouts.csv (PAD-894) only went the other way.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import os

from pinball_decryptor.core.transcribe import CalloutsFile
from tests.test_gui_audio_rename import _load, _rows, _wav
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.webui_harness import web_app


def _csv(assets):
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    return [(cf.get(r, "folder"), cf.get(r, "file"), cf.get(r, "classification"),
             cf.get(r, "text")) for r in cf.rows]


def _run(w):
    assert w.call("audio.update_callouts") is True


def test_names_given_in_pad_go_into_the_csv(tmp_path, boxes):  # noqa: F811
    """Two sounds renamed since Auto-name wrote the CSV, one never in it, and a
    row for a sound this project doesn't have."""
    assets = _project(tmp_path, [
        ("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo.wav", "Kai Joo"),
        ("audio", "idx0099 - Not here.wav", "Not here"),
    ])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
    assert "1 row(s) get their sound's new name and 1 named sound(s) get a row" in boxes[-2]
    assert "Updated 1 row(s) and added 1." in boxes[-1]
    assert _csv(assets) == [
        ("audio", "idx0001 - Jack pot.wav", "speech", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "speech", "Kai Joo award"),
        ("audio", "idx0099 - Not here.wav", "speech", "Not here"),
        ("audio", "idx0003 - Monster lock is lit.wav", "speech", "Monster lock is lit"),
    ]
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
    assert "already has every sound's name" in boxes[-1]


def test_words_that_make_the_name_are_kept(tmp_path, boxes):  # noqa: F811
    """'Kaiju award: 2x' files as 'Kaiju award_ 2x': the CSV keeps its colon."""
    assets = _project(tmp_path, [
        ("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kai Joo award"),
        ("audio", "idx0003 - Monster lock is lit.wav", "Monster lock is lit"),
    ])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename_from_callouts") is True    # nothing to do
        assert w.call("audio.rename", "audio/idx0002 - Kai Joo award.wav",
                      "Kaiju award: 2x", "callouts") is True
        # the Properties rename already moved its row; the words stay as typed
        assert _csv(assets)[1] == ("audio", "idx0002 - Kaiju award_ 2x.wav",
                                   "speech", "Kaiju award_ 2x")
        _run(w)
        assert "already has every sound's name" in boxes[-1]
    # a hand-typed colon in the CSV survives an update
    path = os.path.join(assets, "callouts.csv")
    cf = CalloutsFile(path)
    cf.rows[1][cf.key("text")] = "Kaiju award: 2x"
    cf.save()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        _run(w)
    assert _csv(assets)[1][3] == "Kaiju award: 2x"


def test_properties_rename_moves_its_row(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, [
        ("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kai Joo award"),
    ])
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename", "audio/idx0001 - Jack pot.wav",
                      "JACKPOT!", "callouts") is True
        assert "audio/idx0001 - JACKPOT!.wav" in _rows(w)
        # blank puts the stock name back: the row follows, its words stay
        assert w.call("audio.rename", "audio/idx0002 - Kai Joo award.wav",
                      "", "callouts") is True
    assert _csv(assets) == [
        ("audio", "idx0001 - JACKPOT!.wav", "speech", "JACKPOT!"),
        ("audio", "idx0002.wav", "speech", "Kai Joo award"),
    ]


def test_a_project_with_no_csv_gets_one(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, [], extra=("audio/idx0004.wav",))
    os.remove(os.path.join(assets, "callouts.csv"))
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        # no CSV: a Properties rename leaves it to the menu item
        assert w.call("audio.rename", "audio/idx0001 - Jack pot.wav",
                      "Jackpot", "sfx") is True
        assert not os.path.exists(os.path.join(assets, "callouts.csv"))
        _run(w)
    rows = _csv(assets)
    assert [r[1] for r in rows] == ["idx0001 - Jackpot.wav",
                                    "idx0002 - Kai Joo award.wav",
                                    "idx0003 - Monster lock is lit.wav"]
    # an SFX by its remembered Type is not filed as speech
    assert rows[0][2] == "non-speech"
    with open(os.path.join(assets, "callouts.csv"), "rb") as f:
        assert f.readline() == b"folder,file,seconds,classification,text\r\n"


def test_excel_semicolons_and_windows_1252_round_trip(tmp_path, boxes):  # noqa: F811
    # (an all-ASCII file reads as UTF-8: nothing in it says otherwise)
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav", "Jack pot"),
                                 ("audio", "idx0002 - Kai Joo award.wav", "Kaijû")],
                      delimiter=";", encoding="cp1252")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename", "audio/idx0001 - Jack pot.wav",
                      "Ça c'est génial", "callouts") is True
    with open(os.path.join(assets, "callouts.csv"), "rb") as f:
        raw = f.read()
    assert raw.startswith(b"folder;file;")
    assert "idx0001 - Ça c'est génial.wav".encode("cp1252") in raw
