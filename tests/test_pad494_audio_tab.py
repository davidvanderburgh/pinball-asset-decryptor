"""PAD-494 on the Replace Audio tab: a sound's files for the other MUSIC MODES.

The row menu's "Music modes" (choose / play / take off a mode's sound, name the modes), the
row's badge and words, the sidecar (``sound_modes``) a Write reads, and a slot or a game that
cannot have them saying why. The Stern plugin's answer is stubbed (no card)."""

import os

from tests.test_webui_audio import _open, _project, _sidecar, _wav
from tests.webui_harness import web_app

REL = "audio/idx0001 - Jackpot.wav"


def _offer(monkeypatch, why="", slots=None):
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: (
        why, {rel: (slots or {}).get(rel, "") for rel in rels}))


def _row(w, rel):
    return next(r for r in w.state("audio")["rows"] if r["k"] == rel)


def _modes_entry(w, rel):
    items = w.call("audio.menu", rel, [rel])
    return next((i for i in items if str(i.get("label", "")).startswith("Music modes")), None)


def _labels(entry):
    return [s["label"] for s in entry["submenu"] if not s.get("sep")]


def test_a_sound_takes_a_file_for_another_music_mode(tmp_path, monkeypatch):
    _offer(monkeypatch)
    proj = _project(tmp_path)
    mine = str(tmp_path / "mine" / "Orchestral jackpot.wav")
    _wav(mine)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        entry = _modes_entry(w, REL)
        assert entry["label"] == "Music modes" and entry["icon"] == "music"
        # four modes to start with, named as the tester asked: Standard, Custom A, Custom B...
        assert _labels(entry) == ["Mode 2 (Custom A): choose a sound…",
                                  "Mode 3 (Custom B): choose a sound…",
                                  "Mode 4 (Custom C): choose a sound…",
                                  "Add a music mode…", "Name the music modes…"]
        w.answers.append(mine)
        assert w.call("audio.menu_action", "mode_pick:2", REL) is True
        assert w.asked[-1]["title"] == "Choose the sound %s plays in music mode 2 (Custom A)" % REL
        assert _sidecar(proj)["sound_modes"] == {"names": [], "slots": {REL: {"2": os.path.normpath(mine)}}}
        r = _row(w, REL)
        assert r["md"] == [2]
        assert r["md_tip"] == ("Music modes - the machine's MUSIC MODE setting picks which plays: "
                               "mode 1 (Standard): the game's own sound; "
                               "mode 2 (Custom A): Orchestral jackpot.wav.")
        # a slot with a mode's file is a change the build makes
        assert w.state("audio")["status"].startswith("1 of 3 slots changed")
        # the modes' names, one line
        from pinball_decryptor.webui import compat
        monkeypatch.setattr(compat.simpledialog, "askstring",
                            lambda *a, **k: " Standard ,  Orchestral Score ")
        assert w.call("audio.menu_action", "mode_names", REL) is True
        assert _sidecar(proj)["sound_modes"]["names"] == ["Standard", "Orchestral Score"]
        entry = _modes_entry(w, REL)
        assert entry["label"] == "Music modes (1)"
        assert _labels(entry) == ["Mode 2 (Orchestral Score): change Orchestral jackpot.wav…",
                                  "Mode 3 (Custom B): choose a sound…",
                                  "Mode 4 (Custom C): choose a sound…",
                                  "Play mode 2's sound (Orchestral jackpot.wav)",
                                  "Take off mode 2's sound (Orchestral jackpot.wav)",
                                  "Add a music mode…", "Name the music modes…"]
        assert w.call("audio.menu_action", "mode_play:2", REL) is True
        assert w.state("audio")["panes"]["rep"]["name"] == \
            "Mode 2 (Orchestral Score): Orchestral jackpot.wav"
    # a fresh session has them back, and taking the file off keeps the names
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert _row(w, REL)["md"] == [2]
        assert w.call("audio.menu_action", "mode_off:2", REL) is True
        assert "md" not in _row(w, REL)
        assert _sidecar(proj)["sound_modes"] == {"names": ["Standard", "Orchestral Score"], "slots": {}}


def test_more_music_modes_can_be_added_up_to_the_games_most(tmp_path, monkeypatch):
    """"Can the user create more than 3 audio modes?" - four to start with, then up to eight."""
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    from pinball_decryptor.webui import compat
    _offer(monkeypatch)
    proj = _project(tmp_path)
    mine = str(tmp_path / "mine" / "Heisei.wav")
    _wav(mine)
    asked = []
    monkeypatch.setattr(compat.simpledialog, "askstring",
                        lambda title, prompt, initialvalue="", **k: asked.append(initialvalue) or " Heisei  Era ")
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.call("audio.menu_action", "mode_add", REL) is True
        assert asked[-1] == "Custom D"
        assert _sidecar(proj)["sound_modes"]["names"] == [
            "Standard", "Custom A", "Custom B", "Custom C", "Heisei Era"]
        labels = _labels(_modes_entry(w, REL))
        assert labels[3] == "Mode 5 (Heisei Era): choose a sound…"
        # the same file can go in more than one mode
        w.answers.extend([mine, mine])
        assert w.call("audio.menu_action", "mode_pick:5", REL) is True
        assert w.call("audio.menu_action", "mode_pick:3", REL) is True
        assert _row(w, REL)["md"] == [3, 5]
        assert _sidecar(proj)["sound_modes"]["slots"] == {
            REL: {"3": os.path.normpath(mine), "5": os.path.normpath(mine)}}
        for _ in range(3):
            assert w.call("audio.menu_action", "mode_add", REL) is True
        labels = _labels(_modes_entry(w, REL))
        assert "Mode %d (Heisei Era): choose a sound…" % SMo.MAX_MODES in labels
        assert "Add a music mode…" not in labels                 # eight is the most
        assert w.call("audio.menu_action", "mode_add", REL) is False


def test_a_sound_that_cannot_have_modes_says_why(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    _offer(monkeypatch, slots={REL: SMo.NOT_SOUND})
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert _labels(_modes_entry(w, REL)) == ["Why not this sound?"]
        assert w.call("audio.menu_action", "mode_pick:2", REL) is False
        w.answers.append("ok")
        assert w.call("audio.menu_action", "mode_why", REL) is True
        assert w.asked[-1]["message"] == SMo.NOT_SOUND


def test_no_music_modes_where_the_plugin_has_none(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="jjp") as w:
        _open(w, proj)
        assert _modes_entry(w, REL) is None
