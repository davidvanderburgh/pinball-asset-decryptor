"""PAD-1105: the Audio tab's "Hide unused" tick leaves out the sounds no sound request plays.

A tester asked for a filter to hide the rows whose Requests column reads None (PAD-635): a sound
the game's code never asks for. The tick sits beside Show, only where the Requests column is;
it hides only the None rows (a blank cell, a music bank's song, says nothing either way), is
remembered with the folder like Show, and a reveal of a hidden sound turns it off."""

import os

from pinball_decryptor.plugins.stern import clip_sounds as CS
from tests.test_webui_audio import _open, _project, _sidecar
from tests.webui_harness import web_app

RELS = ("audio/idx0001 - Jackpot.wav", "audio/idx0002.wav", "audio/idx0003 - music loop.wav",
        "music/Song.wav")


def _requests(proj):
    # idx 1 and 3 are played, idx 2 by no request
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]] * 20,
                      {4: [1], 9: [1]}, {4: "SE GZ VO JACKPOT"}, also={12: [3]})


def _keys(w):
    return [r["k"] for r in w.state("audio")["rows"]]


def test_hide_unused_leaves_out_the_none_rows_only(tmp_path):
    proj = _project(tmp_path, RELS)
    _requests(proj)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        s = w.state("audio")
        assert s["req_cap"] is True and s["hide_unused"] is False
        assert sorted(_keys(w)) == sorted(RELS)
        assert w.call("audio.set_hide_unused", True) is True
        # the None row goes; the song's blank cell is not "unused"
        assert sorted(_keys(w)) == sorted(set(RELS) - {RELS[1]})
        assert "(3 shown)" in w.state("audio")["status"]
        assert _sidecar(proj).get("audio_hide_unused") is True
        # it works with Show: Unchanged and the search box, not instead of them
        w.call("audio.set_show", "Unchanged")
        assert RELS[1] not in _keys(w)
        w.run(lambda: w.window.service("audio").audio_search_var.set("idx0002"))
        assert _keys(w) == []
        assert "Hide unused" in w.state("audio")["empty"]
        w.run(lambda: w.window.service("audio").audio_search_var.set(""))
        w.call("audio.set_show", "All")
        assert w.call("audio.set_hide_unused", False) is True
        assert sorted(_keys(w)) == sorted(RELS)
        assert "audio_hide_unused" not in _sidecar(proj)


def test_it_is_remembered_with_the_folder(tmp_path):
    proj = _project(tmp_path / "a", RELS)
    other = _project(tmp_path / "b", RELS[:2])
    _requests(proj)
    _requests(other)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.call("audio.set_hide_unused", True)
        # another folder that never said starts with every sound
        _open(w, other)
        assert w.state("audio")["hide_unused"] is False
        assert sorted(_keys(w)) == sorted(RELS[:2])
        _open(w, proj)
        assert w.state("audio")["hide_unused"] is True
        assert RELS[1] not in _keys(w)


def test_revealing_a_hidden_sound_turns_it_off(tmp_path):
    proj = _project(tmp_path, RELS)
    _requests(proj)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.call("audio.set_hide_unused", True)
        svc = w.window.service("audio")
        assert w.run(lambda: svc.reveal_audio_slot(RELS[1])) is True
        assert w.state("audio")["hide_unused"] is False
        assert RELS[1] in _keys(w)


def test_without_a_request_map_it_hides_nothing(tmp_path):
    proj = _project(tmp_path, RELS)
    # an extract made before the later parts were recorded: no Requests column
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]] * 5, {4: [1]}, {})
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.state("audio")["req_cap"] is False
        w.call("audio.set_hide_unused", True)
        assert sorted(_keys(w)) == sorted(RELS)
