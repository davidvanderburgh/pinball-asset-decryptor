"""PAD-1246: Audio > More > Update comments from callouts.csv.

A player fills in the comment column of callouts.csv outside the app (an LLM
names who speaks each callout and the mode it belongs to) and brings every
comment in at once, the way Rename from callouts.csv brings the names in.
Only the comments change: names, types and the other columns stay.
"""
import csv
import os

from pinball_decryptor.core.transcribe import CalloutsFile
from tests.test_gui_audio_rename import _load
from tests.test_pad894_rename_from_callouts import _project, boxes  # noqa: F401
from tests.webui_harness import web_app

JACK = "audio/idx0001 - Jack pot.wav"
KAI = "audio/idx0002 - Kai Joo award.wav"
LOCK = "audio/idx0003 - Monster lock is lit.wav"
ROWS = [("audio", "idx0001 - Jack pot.wav", "Jack pot"),
        ("audio", "idx0002 - Kai Joo award.wav", "Kai Joo award"),
        ("audio", "idx0003 - Monster lock is lit.wav", "Monster lock is lit")]


def _rewrite(assets, header, notes):
    """callouts.csv again, as a spreadsheet / LLM hands it back: the five
    columns plus *header*, each row's note from *notes* (by file), and a
    row for a sound the project does not have."""
    path = os.path.join(assets, "callouts.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "file", "seconds", "classification", "text",
                    header])
        for folder, fname, text in ROWS + [
                ("audio", "idx0099 - Gone.wav", "Gone")]:
            w.writerow([folder, fname, "0.200", "speech", text,
                        notes.get(fname, "")])
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))


def _shown(w):
    return {r["k"]: r.get("cm") for r in w.state("audio")["rows"]}


def test_comments_come_in_from_the_csv_names_stay(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.set_comment", LOCK, "Old note") is True
        names = sorted(_shown(w))
        _rewrite(assets, "Comments", {
            "idx0001 - Jack pot.wav": "Announcer\nMonster Multiball",
            "idx0002 - Kai Joo award.wav": "Ken Watanabe",
            "idx0099 - Gone.wav": "nobody"})
        del boxes[:]
        assert w.call("audio.comments_from_callouts") is True
        assert _shown(w) == {JACK: "Announcer Monster Multiball",
                             KAI: "Ken Watanabe", LOCK: None}
        assert sorted(_shown(w)) == names           # no sound renamed
        msg = boxes[-1]
        assert "2 sound(s) have a comment" in msg
        assert "2 new" in msg and "1 cleared" in msg
        assert "1 row(s) with a comment name a sound" in msg
        # pressed again: nothing new
        assert w.call("audio.comments_from_callouts") is True
        assert "already showed every one" in boxes[-1]
        # a comment typed in Properties goes into the same Comments column
        assert w.call("audio.set_comment", LOCK, "Lock lit") is True
    cf = CalloutsFile(os.path.join(assets, "callouts.csv"))
    assert cf.fields[-1] == "Comments" and "comment" not in cf.fields
    assert [cf.get(r, "comment") for r in cf.rows][:3] == [
        "Announcer\nMonster Multiball", "Ken Watanabe", "Lock lit"]
    assert [cf.get(r, "text") for r in cf.rows][:3] == [
        "Jack pot", "Kai Joo award", "Monster lock is lit"]


def test_a_renamed_sound_is_found_by_its_idx(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.rename", JACK, "JACKPOT", "callouts", "") is True
        # the CSV still names the old file (an LLM worked on an older copy)
        _rewrite(assets, "notes", {"idx0001 - Jack pot.wav": "Announcer"})
        assert w.call("audio.comments_from_callouts") is True
        assert _shown(w)["audio/idx0001 - JACKPOT.wav"] == "Announcer"


def test_no_comment_column_says_how_to_add_one(tmp_path, boxes):  # noqa: F811
    assets = _project(tmp_path, ROWS)
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, assets)
        assert w.call("audio.comments_from_callouts") is False
        assert "no comment column" in boxes[-1]


def test_comment_header_beats_an_alias():
    cf = CalloutsFile.empty("x.csv")
    cf.fields += ["Notes", "Comment"]
    assert cf.key("comment") == "Comment"
    cf.fields = ["file", "text", " NOTES "]
    assert cf.key("comment") == " NOTES "
    assert cf.key("text") == "text"
