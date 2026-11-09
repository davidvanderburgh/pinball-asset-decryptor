"""PAD-1084 (an owner: "add multiple at once ... set loudness for all replacements with a single
loudness entry"): the Audio tab's Play in turn adds several files from one picker, a music mode's
"choose a sound…" takes its song and the songs beside it in one go, and one entry sets the loudness
of a part's every file - each one still set on its own after."""

import os

from pinball_decryptor.plugins.stern import sound_modes as SMo

REL = "audio/idx0001 - Jackpot.wav"


def _setup(tmp_path, monkeypatch, turns=True):
    from tests.test_webui_audio import _project, _wav as wav
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("", {r: "" for r in rels}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: (
        ("", {r: "" for r in rels}) if turns else ("not on this game", {})))
    proj = _project(tmp_path)
    names = ["Song 10.wav", "Song 2.wav", "Song 1.wav", "Own.wav"]
    files = {n: str(tmp_path / "mine" / n) for n in names}
    for f in files.values():
        wav(f)
    return proj, files


def _sub(w, rel=REL):
    items = w.call("audio.menu", rel, [rel])
    return next(i for i in items if str(i.get("label", "")).startswith("Play ")
                and i.get("submenu"))["submenu"]


def _labels(w):
    return [s.get("label") for s in _sub(w) if s.get("label")]


def test_several_files_go_in_turn_from_one_pick_in_name_order(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _sidecar
    from tests.webui_harness import web_app
    proj, f = _setup(tmp_path, monkeypatch)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([f["Song 10.wav"], f["Song 2.wav"], f["Song 1.wav"]])
        assert w.call("audio.menu_action", "turn_add", REL) is True
        assert _sidecar(proj)["sound_modes"]["turns"] == {REL: [
            os.path.normpath(f[n]) for n in ("Song 1.wav", "Song 2.wav", "Song 10.wav")]}
        # a file already in turn is not added twice; cancelling adds nothing
        w.answers.append([f["Song 2.wav"]])
        assert w.call("audio.menu_action", "turn_add", REL) is False
        w.answers.append([])
        assert w.call("audio.menu_action", "turn_add", REL) is False
        assert len(_sidecar(proj)["sound_modes"]["turns"][REL]) == 3


def test_a_pick_past_sixteen_takes_what_fits(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    proj, _f = _setup(tmp_path, monkeypatch)
    many = [str(tmp_path / "many" / ("Take %02d.wav" % k)) for k in range(1, 19)]
    for p in many:
        wav(p)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append(list(reversed(many)))
        assert w.call("audio.menu_action", "turn_add", REL) is True
        got = _sidecar(proj)["sound_modes"]["turns"][REL]
        assert got == [os.path.normpath(p) for p in many[:15]]       # 15 + its own = 16
        assert not any(s.get("action") == "turn_add" for s in _sub(w))  # full: no Add


def test_one_loudness_for_a_sound_s_replacement_and_its_files_in_turn(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _sidecar
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    proj, f = _setup(tmp_path, monkeypatch)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append(f["Own.wav"])
        assert w.call("audio.choose", REL) is True
        w.answers.append([f["Song 1.wav"], f["Song 2.wav"]])
        assert w.call("audio.menu_action", "turn_add", REL) is True
        assert "Loudness of all 3 sounds (0 dB)…" in _labels(w)
        asked = []
        monkeypatch.setattr(compat.simpledialog, "askstring",
                            lambda *a, **k: asked.append((a, k)) or "-5")
        assert w.call("audio.menu_action", "turn_level_all", REL) is True
        assert "Own.wav and the 2 with it" in asked[0][0][1]
        sd = _sidecar(proj)
        assert sd["sound_modes"]["turn_levels"] == {REL: {"2": -5, "3": -5}}
        assert sd["audio_levels"] == {REL: -5}                       # Own.wav's own box
        assert next(r for r in w.state("audio")["rows"] if r["k"] == REL)["lvl"] == "-5 dB"
        labels = _labels(w)
        assert "Loudness of sound 2 (-5 dB)…" in labels
        # each one still has its own: then the "all" entry says they differ
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "2")
        assert w.call("audio.menu_action", "turn_level:3", REL) is True
        assert _sidecar(proj)["sound_modes"]["turn_levels"] == {REL: {"2": -5, "3": 2}}
        assert "Loudness of all 3 sounds (mixed)…" in _labels(w)
        # cancel changes nothing; 0 clears them all
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: None)
        assert w.call("audio.menu_action", "turn_level_all", REL) is False
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "0")
        assert w.call("audio.menu_action", "turn_level_all", REL) is True
        assert not (_sidecar(proj).get("sound_modes") or {}).get("turn_levels")
        assert not _sidecar(proj).get("audio_levels")
        assert "Loudness of all 3 sounds (0 dB)…" in _labels(w)


def test_without_a_replacement_the_game_s_own_sound_keeps_its_loudness(tmp_path, monkeypatch):
    """No replacement: the game's own sound has no offset, so "all" is the files in turn alone."""
    from tests.test_webui_audio import _open, _sidecar
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    proj, f = _setup(tmp_path, monkeypatch)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([f["Song 1.wav"]])
        assert w.call("audio.menu_action", "turn_add", REL) is True
        assert not any("Loudness of all" in str(x) for x in _labels(w))   # only one to set
        w.answers.append([f["Song 2.wav"]])
        assert w.call("audio.menu_action", "turn_add", REL) is True
        assert "Loudness of all 2 sounds (0 dB)…" in _labels(w)
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "-7")
        assert w.call("audio.menu_action", "turn_level_all", REL) is True
        sd = _sidecar(proj)
        assert sd["sound_modes"]["turn_levels"] == {REL: {"2": -7, "3": -7}}
        assert not sd.get("audio_levels")


def test_a_music_mode_takes_its_song_and_the_songs_beside_it_in_one_pick(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _sidecar
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    proj, f = _setup(tmp_path, monkeypatch)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([f["Song 10.wav"], f["Song 2.wav"], f["Song 1.wav"]])
        assert w.call("audio.menu_action", "mode_pick:2", REL) is True
        sm = _sidecar(proj)["sound_modes"]
        assert sm["slots"] == {REL: {"2": os.path.normpath(f["Song 1.wav"])}}
        assert sm["mode_turns"] == {REL: {"2": [os.path.normpath(f["Song 2.wav"]),
                                                os.path.normpath(f["Song 10.wav"])]}}
        # more songs beside it later, several at once
        w.answers.append([f["Own.wav"]])
        assert w.call("audio.menu_action", "mturn_add:2", REL) is True
        assert len(_sidecar(proj)["sound_modes"]["mode_turns"][REL]["2"]) == 3
        assert w.call("audio.menu_action", "mturn_order:2:1", REL) is True
        assert "Loudness of all 4 sounds (0 dB)…" in _labels(w)
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "-3")
        assert w.call("audio.menu_action", "mturn_level_all:2", REL) is True
        sm = _sidecar(proj)["sound_modes"]
        assert sm["levels"] == {REL: {"2": -3}}
        assert sm["mode_turn_levels"] == {REL: {"2": {"2": -3, "3": -3, "4": -3}}}
        assert sm["mode_random"] == {REL: ["2"]}
        assert "Loudness of all 4 sounds (-3 dB)…" in _labels(w)
        # one of them on its own after
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "1")
        assert w.call("audio.menu_action", "mturn_level:2:4", REL) is True
        assert _sidecar(proj)["sound_modes"]["mode_turn_levels"] == {REL: {"2": {"2": -3, "3": -3,
                                                                                 "4": 1}}}
        assert "Loudness of all 4 sounds (mixed)…" in _labels(w)


def test_a_game_without_sounds_in_turn_takes_only_the_mode_s_song(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _sidecar
    from tests.webui_harness import web_app
    proj, f = _setup(tmp_path, monkeypatch, turns=False)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([f["Song 2.wav"], f["Song 1.wav"]])
        assert w.call("audio.menu_action", "mode_pick:2", REL) is True
        sm = _sidecar(proj)["sound_modes"]
        assert sm["slots"] == {REL: {"2": os.path.normpath(f["Song 1.wav"])}}
        assert not sm.get("mode_turns")
