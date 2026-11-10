"""PAD-1106: the Audio tab plays a jukebox song for the game's music it replaces.

Ben (Beatles 1.29, a 189-song jukebox): Drive My Car's row showed "Choose..." and its Replacement pane
"no replacement assigned", so Play there was silent although the built card plays a jukebox song in its
place. Now a song mode's record (any pool's music) says the jukebox plays it, the pane holds one of that
pool's songs drawn as the runtime draws them (by weight, none of the last few), and each Stop (or the song
ending) makes the next Play draw another. A pause resumes the same song; a replacement of the row's own
still wins.
"""
import collections
import os
import random

from pinball_decryptor.plugins.stern import jukebox as JB
from tests.test_pad685_jukebox import _gui_offer, _Other, _Prof

DRIVE = "audio/idx0200 - Drive My Car.wav"
TAXMAN = "audio/idx0370 - Taxman.wav"
COIN = "audio/idx0001 - Coin.wav"


# ---- which slots, which pool ----------------------------------------------------------------------
def test_each_music_record_names_its_pool(monkeypatch):
    pools = JB.record_pools(_Prof())
    assert pools[200] == pools[417] == pools[42] == "songs"
    assert pools[461] == pools[370] == pools[574] == "special"
    assert pools[148] == pools[294] == "background"
    assert len(pools) == 18 and JB.record_pools(_Other()) == {}
    monkeypatch.setattr(JB, "project_title", lambda project, probe=False: _Prof())
    got = JB.slot_pools("p", [DRIVE, TAXMAN, COIN, "audio/02m21s867 - idx0148.wav", "video/x.mov"])
    assert got == {DRIVE: "songs", TAXMAN: "special", "audio/02m21s867 - idx0148.wav": "background"}
    monkeypatch.setattr(JB, "project_title", lambda project, probe=False: _Other())
    assert JB.slot_pools("p", [DRIVE]) == {}


def test_a_draw_weighs_like_the_game_and_skips_the_last_ones():
    random.seed(1106)
    songs = [("common", 3), ("normal", 2), ("rare", 1)]
    n = collections.Counter(JB.draw(songs) for _ in range(6000))
    assert 2.5 < n["common"] / n["rare"] < 3.5 and 1.7 < n["normal"] / n["rare"] < 2.4
    assert {JB.draw(songs, recent=["common", "normal"]) for _ in range(50)} == {"rare"}
    # every song just played: the whole list again rather than nothing
    assert JB.draw([("only", 2)], recent=["only"]) == "only"
    assert JB.draw([]) is None


# ---- the Audio tab --------------------------------------------------------------------------------
def _setup(tmp_path, monkeypatch):
    from tests.test_webui_audio import _project, _wav as wav
    _gui_offer(monkeypatch, "")
    monkeypatch.setattr(JB, "project_title", lambda project, probe=False: _Prof())
    proj = _project(tmp_path, names=(COIN, DRIVE, TAXMAN))
    songs = {}
    for name, pool, w in (("Come Together", "songs", 3), ("Something", "songs", 2), ("Get Back", "songs", 1),
                          ("Twist And Shout", "special", 2)):
        songs[name] = str(tmp_path / "mine" / (name + ".wav"))
        wav(songs[name], seconds=0.4)
        songs[name] = os.path.normpath(songs[name])
    JB.save(proj, JB.clean({"songs": [{"audio": songs[n], "weight": w, "pool": p} for n, p, w in (
        ("Come Together", "songs", 3), ("Something", "songs", 2), ("Get Back", "songs", 1),
        ("Twist And Shout", "special", 2))]}))
    return proj, songs


def test_a_song_mode_s_row_plays_a_jukebox_song_and_stop_draws_another(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _svc, _wait, _wav as wav
    from tests.webui_harness import web_app
    proj, songs = _setup(tmp_path, monkeypatch)
    mode_songs = {songs["Come Together"], songs["Something"], songs["Get Back"]}
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        assert rows[DRIVE]["rep"] == "Jukebox: 1 of 3 songs at random" and rows[DRIVE]["t"] == ""
        assert rows[TAXMAN]["rep"] == "Jukebox: 1 of 1 songs at random"
        assert rows[COIN]["rep"] == "Choose…"
        played = []
        svc = _svc(w)
        real = svc._publish
        w.run(lambda: setattr(svc, "_publish", lambda ev, **d: (
            played.append((d.get("pane"), d.get("path"), d.get("pos"))) if ev == "audio_play"
            else None, real(ev, **d))))
        rep = lambda: w.state("audio")["panes"]["rep"]              # noqa: E731
        w.call("audio.select", [DRIVE])
        assert _wait(w, lambda: rep()["path"] in mode_songs)
        first = rep()
        assert first["base"] == "Replacement (jukebox: 1 of 3 songs at random)"
        assert first["rel"] == DRIVE and first["name"] == os.path.basename(first["path"])
        # Play, then Pause and Play again: the same song goes on from where it was
        w.call("audio.play", "rep")
        w.call("audio.play", "rep")
        assert played[-2:] == [("rep", first["path"], None)] * 2
        # Stop: the next Play is another song of the pool, from its start
        heard = [first["path"]]
        for _ in range(6):
            w.call("audio.stop")
            w.call("audio.play", "rep")
            assert played[-1][0] == "rep" and played[-1][2] == 0.0 and rep()["path"] == played[-1][1]
            heard.append(played[-1][1])
        assert set(heard) <= mode_songs
        assert all(a != b for a, b in zip(heard, heard[1:]))      # never the one just heard
        assert all(len(set(heard[i:i + 3])) == 3 for i in range(len(heard) - 2))   # none of the last two
        # played to its end: the next Play draws again too
        w.call("audio.clip_finished", "rep", rep()["path"])
        w.call("audio.play", "rep")
        assert played[-1][1] != heard[-1] and played[-1][1] in mode_songs
        # a special mode's music draws only its own pool's songs
        w.call("audio.select", [TAXMAN])
        assert _wait(w, lambda: rep()["rel"] == TAXMAN)
        assert rep()["path"] == songs["Twist And Shout"]
        # the row's ▶ with Play replacements on plays the jukebox song too
        w.call("audio.set_play_subst", True)
        n = len(played)
        w.call("audio.play_row", DRIVE)
        assert _wait(w, lambda: len(played) > n)
        assert played[-1][0] == "rep" and played[-1][1] in mode_songs
        # a replacement of the row's own wins over the jukebox
        mine = str(tmp_path / "mine" / "my drive.wav")
        wav(mine, seconds=0.5)
        w.answers.append(mine)
        w.call("audio.choose", DRIVE)
        assert _wait(w, lambda: rep()["path"] == os.path.normpath(mine) or rep()["path"] == mine)
        assert rep()["base"] == "Replacement"
        assert {r["k"]: r for r in w.state("audio")["rows"]}[DRIVE]["rep"] == "my drive.wav"
        n = len(played)
        w.call("audio.stop")
        w.call("audio.play", "rep")
        assert played[n:] == [("rep", rep()["path"], None)]


def test_no_jukebox_song_leaves_the_pane_as_it_was(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _wait
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    monkeypatch.setattr(JB, "project_title", lambda project, probe=False: _Prof())
    proj = _project(tmp_path, names=(COIN, DRIVE))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert {r["k"]: r for r in w.state("audio")["rows"]}[DRIVE]["rep"] == "Choose…"
        w.call("audio.select", [DRIVE])
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["rel"] == DRIVE)
        rep = w.state("audio")["panes"]["rep"]
        assert rep["path"] is None or rep["path"] == ""
        assert rep["hint"] == "no replacement assigned"
