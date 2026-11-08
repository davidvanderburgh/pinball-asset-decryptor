"""PAD-1069: comments on sounds in the Audio tab.

A tester wanted to note on each sound who says it, the mode it belongs to or
what plays it, kept in the project's callouts.csv so the notes last between
sessions and can be shared.  Audio Properties takes the comment; it goes into
a comment column of callouts.csv, shows in the table and the search finds it.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import csv
import os
import sys
import types

from pinball_decryptor.core import transcribe as T
from pinball_decryptor.core.transcribe import CalloutsFile
from tests.test_gui_audio_rename import _load, _rows, _wav
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.webui_harness import web_app

JACK = "audio/idx0001 - Jack pot.wav"
KAI = "audio/idx0002 - Kai Joo award.wav"
ROWS = [("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kai Joo award"),
        ("audio", "idx0003 - Monster lock is lit.wav", "Monster lock is lit")]


def _csv(assets):
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    return cf, [(cf.get(r, "file"), cf.get(r, "comment")) for r in cf.rows]


def _shown(w):
    return {r["k"]: r.get("cm") for r in w.state("audio")["rows"]}


def test_a_comment_goes_into_the_csv_the_table_and_the_search(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.state("audio")["comments"] is False
        info = w.call("audio.props_info", JACK)
        assert info["renamable"] is True and info["comment"] == ""
        # OK in Properties with the name as it was: only the comment changes
        assert w.call("audio.rename", JACK, "Jack pot", "callouts",
                      "  Kong,\n after a  battle ") is True
        assert _shown(w)[JACK] == "Kong, after a battle"
        assert w.state("audio")["comments"] is True
        assert w.call("audio.props_info", JACK)["comment"] == "Kong, after a battle"
        # the search finds a word only the comment holds
        w.run(lambda: w.window.service("audio").audio_search_var.set("BATTLE"))
        assert _rows(w) == [JACK]
        w.run(lambda: w.window.service("audio").audio_search_var.set(""))
        # Comment sorts the commented sounds first
        assert w.call("audio.set_comment", KAI, "Pilot") is True
        assert w.call("audio.sort", "cm") is True
        assert _rows(w)[:2] == [JACK, KAI]
    cf, got = _csv(assets)
    assert cf.fields == ["folder", "file", "seconds", "classification",
                         "text", "comment"]
    assert got == [("idx0001 - Jack pot.wav", "Kong, after a battle"),
                   ("idx0002 - Kai Joo award.wav", "Pilot"),
                   ("idx0003 - Monster lock is lit.wav", "")]
    # a new session reads them back; blank clears one
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert _shown(w)[KAI] == "Pilot"
        assert w.call("audio.set_comment", KAI, "  ") is True
        assert _shown(w)[KAI] is None
    assert _csv(assets)[1][1] == ("idx0002 - Kai Joo award.wav", "")


def test_a_rename_and_a_comment_in_one_ok(tmp_path, boxes):  # noqa: F811
    """The comment lands on the row the rename moved, and stays with the
    sound through Rename from callouts.csv and Update callouts.csv."""
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename", JACK, "JACKPOT", "callouts",
                      "Super jackpot lit") is True
        new = "audio/idx0001 - JACKPOT.wav"
        assert _shown(w)[new] == "Super jackpot lit"
        assert w.call("audio.update_callouts") is True
        assert w.call("audio.rename", new, "Jackpot!", "callouts") is True
        assert _shown(w)["audio/idx0001 - Jackpot!.wav"] == "Super jackpot lit"
    cf, got = _csv(assets)
    assert got[0] == ("idx0001 - Jackpot!.wav", "Super jackpot lit")
    assert len(cf.rows) == 3


def test_a_sound_with_no_row_or_no_csv_gets_one(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, [], extra=("audio/idx0004.wav",
                                           "music/Theme.wav"))
    os.remove(os.path.join(assets, "callouts.csv"))
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.set_comment", "audio/idx0004.wav",
                      "Ball save") is True
        # a name the Properties can't change still takes a comment
        info = w.call("audio.props_info", "music/Theme.wav")
        assert info["renamable"] is False
        labels = [i.get("label") for i in
                  w.call("audio.menu", "music/Theme.wav", ["music/Theme.wav"])]
        assert "Comment…" in labels
        assert w.call("audio.set_comment", "music/Theme.wav",
                      "Attract mode") is True
        assert _shown(w)["music/Theme.wav"] == "Attract mode"
        # a sound with no words is not renamed by its row
        assert w.call("audio.rename_from_callouts") is True
        assert "audio/idx0004.wav" in _rows(w)
    cf, _got = _csv(assets)
    got = [(cf.get(r, "folder"), cf.get(r, "file"), cf.get(r, "text"),
            cf.get(r, "comment")) for r in cf.rows]
    assert got == [("audio", "idx0004.wav", "", "Ball save"),
                   ("music", "Theme.wav", "", "Attract mode")]


def test_excel_semicolons_and_windows_1252_keep_their_shape(tmp_path, boxes):  # noqa: F811
    # (an all-ASCII file reads as UTF-8: one accent says Windows-1252)
    assets = _project(tmp_path, [("audio", "idx0001 - Jack pot.wav",
                                  "Jack pöt")] + ROWS[1:],
                      delimiter=";", encoding="cp1252")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.set_comment", KAI, "no: café") is True
    with open(os.path.join(assets, "callouts.csv"), "rb") as f:
        raw = f.read()
    assert raw.startswith(b"folder;file;seconds;classification;text;comment")
    assert "café".encode("cp1252") in raw


def test_export_csv_has_the_comments(tmp_path, boxes, monkeypatch):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    out = str(tmp_path / "table.csv")
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        svc = w.window.service("audio")
        monkeypatch.setattr(svc, "_ask_path", lambda *a, **k: out)
        assert w.call("audio.set_comment", KAI, "Pilot") is True
        assert w.call("audio.export_csv") is True
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["Original Track"]: r["Comment"] for r in rows}[KAI] == "Pilot"


def test_auto_name_keeps_the_comments(tmp_path, monkeypatch):
    """Auto-name writes callouts.csv anew: the comments stay with their
    sounds, one it renames found again by its idx number."""
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        types.SimpleNamespace(WhisperModel=object))
    (tmp_path / "audio").mkdir()
    _wav(str(tmp_path / "audio" / "idx0001 - Super jackpot.wav"))
    _wav(str(tmp_path / "audio" / "idx0002.wav"))
    with open(tmp_path / T.CALLOUTS_CSV, "w", encoding="utf-8",
              newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["folder", "file", "seconds", "classification", "text",
                     "comment"])
        cw.writerow(["audio", "idx0001 - Super jackpot.wav", "0.100",
                     "speech", "Super jackpot!", "Kong"])
        cw.writerow(["audio", "idx0002.wav", "0.100", "non-speech", "",
                     "Multiball start"])
    counts = T._new_counts()
    T._tally(counts, "speech")
    monkeypatch.setattr(
        T.TranscribePipeline, "_transcribe_serial",
        lambda self, wavs: ([("audio/idx0002.wav", "speech", "Multiball")],
                            counts))
    done = {}
    p = T.TranscribePipeline(
        str(tmp_path), lambda *a: None, lambda *a: None, lambda *a: None,
        lambda ok, msg: done.update(ok=ok, msg=msg), rename_after=True)
    p.run()
    assert done["ok"] is True, done
    with open(tmp_path / T.CALLOUTS_CSV, encoding="utf-8", newline="") as f:
        got = [(r["file"], r["text"], r["comment"]) for r in csv.DictReader(f)]
    assert got == [("idx0001 - Super jackpot.wav", "Super jackpot!", "Kong"),
                   ("idx0002 - Multiball.wav", "Multiball", "Multiball start")]


def test_auto_name_without_comments_writes_the_five_columns(tmp_path):
    (tmp_path / "audio").mkdir()
    assert T.earlier_comments(str(tmp_path)) is None
    with open(tmp_path / T.CALLOUTS_CSV, "w", encoding="utf-8") as f:
        f.write("folder,file,seconds,classification,text\n")
    assert T.earlier_comments(str(tmp_path)) is None
