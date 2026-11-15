"""PAD-1310: only the file name loses the characters Windows can't hold.

A name typed in Audio Properties ("Who are you? Spider-Man: Here!") makes
the file "idx0001 - Who are you_ Spider-Man_ Here!.wav", but callouts.csv
keeps the words exactly as typed, Properties opens with them again, and
Update callouts.csv / Rename from callouts.csv leave them be.

Driven through the web UI's Replace Audio service (webui/tabs/audio.py).
"""
import os

from pinball_decryptor.core.transcribe import CalloutsFile
from tests.test_gui_audio_rename import _load
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.webui_harness import web_app

JACK = "audio/idx0001 - Jack pot.wav"
ROWS = [("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kai Joo award"),
        ("audio", "idx0003 - Monster lock is lit.wav", "Monster lock is lit")]
WORDS = 'Who are you? Spider-Man: Here! "Go" *now* <a|b>'
SAFE = "Who are you_ Spider-Man_ Here! _Go_ _now_ _a_b_"
NEW = "audio/idx0001 - %s.wav" % SAFE


def _texts(assets):
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    return [(cf.get(r, "file"), cf.get(r, "text")) for r in cf.rows]


def test_the_words_stay_in_the_csv_and_come_back_in_properties(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename", JACK, WORDS, "callouts") is True
        assert os.path.isfile(os.path.join(assets, *NEW.split("/")))
        assert _texts(assets)[0] == (NEW.rpartition("/")[2], WORDS)
        # Properties opens with the words, not the file-safe name
        assert w.call("audio.props_info", NEW)["label"] == WORDS
        # OK again unchanged: nothing moves
        assert w.call("audio.rename", NEW, WORDS, "callouts") is True
        assert _texts(assets)[0][1] == WORDS
        # only the punctuation changes: the file stays, the words follow
        assert w.call("audio.rename", NEW, WORDS.replace("?", "*"),
                      "callouts") is True
        assert _texts(assets)[0] == (NEW.rpartition("/")[2],
                                     WORDS.replace("?", "*"))
        assert w.call("audio.rename", NEW, WORDS, "callouts") is True
        # Update callouts.csv and Rename from callouts.csv keep them
        assert w.call("audio.update_callouts") is True
        assert w.call("audio.rename_from_callouts") is True
        assert _texts(assets)[0] == (NEW.rpartition("/")[2], WORDS)
        assert w.call("audio.props_info", NEW)["label"] == WORDS
        # a name typed with no Windows-only characters: the words are it
        assert w.call("audio.rename", NEW, "Jackpot", "callouts") is True
        assert _texts(assets)[0] == ("idx0001 - Jackpot.wav", "Jackpot")
        assert w.call("audio.props_info",
                      "audio/idx0001 - Jackpot.wav")["label"] == "Jackpot"


def test_a_csv_edited_by_hand_still_names_the_file_safely(tmp_path, boxes):  # noqa: F811
    """Rename from callouts.csv: the file loses the characters, the row
    keeps them."""
    rows = list(ROWS)
    rows[1] = ("audio", "idx0002 - Kai Joo award.wav", "Kaiju award: 2x?")
    assets = _project(tmp_path, rows)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename_from_callouts") is True
        assert _texts(assets)[1] == ("idx0002 - Kaiju award_ 2x_.wav",
                                     "Kaiju award: 2x?")
        assert w.call("audio.props_info",
                      "audio/idx0002 - Kaiju award_ 2x_.wav")["label"] == \
            "Kaiju award: 2x?"


def test_no_csv_yet_the_words_make_one(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    os.remove(os.path.join(assets, "callouts.csv"))
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        # a plain name makes no file
        assert w.call("audio.rename", JACK, "Jackpot", "callouts") is True
        assert not os.path.isfile(os.path.join(assets, "callouts.csv"))
        jack = "audio/idx0001 - Jackpot.wav"
        assert w.call("audio.rename", jack, WORDS, "callouts") is True
        assert _texts(assets) == [(NEW.rpartition("/")[2], WORDS)]
        assert w.call("audio.props_info", NEW)["label"] == WORDS
