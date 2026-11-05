"""PAD-1007: the jukebox's pools - each of the game's musics draws from its own pool's songs.

An owner asked for "X pools, each with its own song/audio list" on The Beatles 1.29: the five song modes,
the two special modes (its two multiballs) and the two background songs, each rotating only its own songs,
and a song wanted in two pools added to each. The runtime's draw per pool is in test_pad685_jukebox.py (the
compiled harness); this file is the title table, the project's record, the build's lines, the card's record
and the Audio tab.
"""
import os
import re

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import jukebox as JB
from pinball_decryptor.plugins.stern import sound_modes as SMo
from tests.test_pad685_jukebox import RUNTIME, _gui_offer, _Other, _Prof


# ---- the title -------------------------------------------------------------------------------------
def test_the_beatles_has_three_pools_and_nine_musics():
    assert [p.key for p in JB.pools(_Prof())] == ["songs", "special", "background"]
    by = {k: [m.records for m in JB.pool_modes(_Prof(), k)] for k in ("songs", "special", "background")}
    assert len(by["songs"]) == 5
    # the two multiballs: sid 952 (request 90, the four-ball Beatlemania Multiball, emulator) and sid 955
    assert by["special"] == [(461, 370), (574, 797)]
    assert by["background"] == [(148, 311), (294, 494)]          # sids 958 and 956
    records = [i for m in JB.song_modes(_Prof()) for i in m.records]
    assert len(records) == len(set(records)) == 18                  # no record in two musics
    assert JB.pools(_Other()) == () and JB.pools(None) == ()


def test_the_special_modes_have_intros_and_the_background_none():
    assert JB.pool_intro(_Prof(), "songs") == "video/FeatureStarts_Frenzy_Start.mov"
    assert JB.pool_intro(_Prof(), "special") == "video/Taxman_Start.mov"
    assert JB.pool_intro(_Prof(), "background") == ""
    clips = [c for m in JB.pool_modes(_Prof(), "special") for c in m.clips]
    assert clips == ["Taxman_Start", "Multiball_feature.Multiball_A_Start"]
    for m in JB.pool_modes(_Prof(), "special") + JB.pool_modes(_Prof(), "background"):
        assert m.site == ""                                         # each draws at its first ask


def test_the_songs_are_still_made_like_the_song_modes_longest_record(tmp_path):
    from tests.test_webui_audio import _wav as wav
    proj = str(tmp_path)
    wav(os.path.join(proj, "audio", "idx0667.wav"), seconds=0.4)
    wav(os.path.join(proj, "audio", "idx0494.wav"), seconds=0.9)    # a background record, longer
    assert JB.host_slot(proj, _Prof()) == "audio/idx0667.wav"
    os.remove(os.path.join(proj, "audio", "idx0667.wav"))
    assert JB.host_slot(proj, _Prof()) == "audio/idx0494.wav"        # none of the song modes': any pool's


# ---- the project's record ------------------------------------------------------------------------
def test_a_song_keeps_its_pool_and_an_old_jukebox_is_the_song_modes():
    box = JB.clean({"songs": [{"audio": "a.wav"}, {"audio": "b.wav", "pool": "special"},
                              {"audio": "c.wav", "pool": ""}]})
    assert [s.pool for s in box.songs] == ["songs", "special", "songs"]
    assert JB.to_json(box) == {"songs": [{"audio": "a.wav", "weight": 2},
                                         {"audio": "b.wav", "weight": 2, "pool": "special"},
                                         {"audio": "c.wav", "weight": 2}]}


# ---- the build -------------------------------------------------------------------------------------
def test_the_runtime_lines_end_in_their_pool():
    text = SMo.cfg_text(0, 0, [], True, jukebox={
        "modes": [("block_start_3", ["A"], [b"\x01" * 8], 0), ("", ["Taxman_Start"], [b"\x02" * 8], 1),
                  ("", [], [b"\x03" * 8], 2)],
        "songs": [(3, b"\x04" * 8, "PadJukebox1", 0), (1, b"\x05" * 8, "", 2)]})
    assert text.splitlines()[2:] == [
        "jmode\tblock_start_3\tA\t0101010101010101",
        "jmode\t-\tTaxman_Start\t0202020202020202\t1",
        "jmode\t-\t-\t0303030303030303\t2",
        "jsong\t3\t0404040404040404\tPadJukebox1",
        "jsong\t1\t0505050505050505\t-\t2"]


def _modes(songs):
    m = SMo.Modes(jukebox=[s.audio for s in songs], juke_rel="audio/idx0667.wav")
    m.juke_plan = {"box": JB.Jukebox(songs=songs), "prof": _Prof()}
    return m


def test_the_build_gives_each_pool_its_musics_and_its_songs(tmp_path):
    video = tmp_path / "s.mov"
    video.write_bytes(b"v")
    songs = [JB.Song("song.wav", str(video), 3), JB.Song("special.wav", str(video), 2, "special"),
             JB.Song("back.wav", str(video), 1, "background"), JB.Song("odd.wav", "", 2, "elsewhere")]
    params = [{"idx": i, "findkey": bytes([i % 251]) * 8} for m in JB.song_modes(_Prof()) for i in m.records]
    params += [{"idx": 900 + k, "findkey": bytes([65 + k]) * 8, "grown": True} for k in range(4)]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(k), "host": 899 + k, "db": 0}
            for k in (1, 2, 3, 4)]
    logs = []
    path = E._sound_modes_cfg("gr", {}, params, {}, used, _modes(songs), True, str(tmp_path / "out"),
                              lambda t, lvl="info": logs.append((lvl, t)))
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    jm = [ln for ln in lines if ln.startswith("jmode")]
    assert len(jm) == 9
    assert jm[5] == "jmode\t-\tTaxman_Start\t%s,%s\t1" % ((bytes([461 % 251]) * 8).hex(), (bytes([370 % 251]) * 8).hex())
    assert jm[7].startswith("jmode\t-\t-\t") and jm[7].endswith("\t2")
    assert [ln for ln in lines if ln.startswith("jsong")] == [
        "jsong\t3\t%s\tPadJukebox1" % (b"A" * 8).hex(),
        "jsong\t2\t%s\tPadJukebox2\t1" % (b"B" * 8).hex(),
        "jsong\t1\t%s\t-\t2" % (b"C" * 8).hex()]               # the background shows no intro of its own
    assert any("odd.wav" in t and "no \"elsewhere\" pool" in t for lvl, t in logs if lvl == "warning")
    # the card's record keeps each song's pool, so an extract brings it back to its pool
    assert "#jsong\t2\t667\t901\t2\taudio/idx0667.wav\tspecial.wav\tspecial" in lines
    assert "#jsong\t1\t667\t900\t3\taudio/idx0667.wav\tsong.wav" in lines
    rec = SMo.read_card_record("\n".join(lines))
    assert [(j["k"], j["pool"]) for j in rec["jukebox"]] == [(1, "songs"), (2, "special"), (3, "background")]


def test_a_pool_with_no_song_keeps_the_game_s_own_music(tmp_path):
    songs = [JB.Song("special.wav", "", 2, "special")]
    params = [{"idx": i, "findkey": bytes([i % 251]) * 8} for m in JB.song_modes(_Prof()) for i in m.records]
    params += [{"idx": 900, "findkey": b"A" * 8, "grown": True}]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(1), "host": 900, "db": 0}]
    got = E._jukebox_lines(params, used, _modes(songs), lambda *a: None)
    assert [m[3] for m in got["modes"]] == [1, 1]                   # only the two multiballs are touched
    assert got["songs"] == [(2, b"A" * 8, "", 1)]


def test_only_a_pool_with_intros_gets_its_songs_videos_converted(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import clip_variants as CV
    v = tmp_path / "v.mov"
    v.write_bytes(b"v")
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "FeatureStarts_Frenzy_Start.mov").write_bytes(b"x")
    JB.save(str(tmp_path), JB.Jukebox(songs=[JB.Song("a.wav", str(v)), JB.Song("b.wav", str(v), 2, "special"),
                                             JB.Song("c.wav", str(v), 2, "background")]))
    rel, songs = CV.jukebox_clips(str(tmp_path), _Prof())
    assert rel == "video/FeatureStarts_Frenzy_Start.mov" and [k for k, _v in songs] == [1, 2]


# ---- the runtime ------------------------------------------------------------------------------------
def test_the_runtime_reads_a_pool_on_each_line_and_holds_nine_musics():
    with open(RUNTIME, encoding="utf-8") as f:
        src = f.read()
    assert int(re.search(r"#define JUKE_MODES\s+(\d+)", src).group(1)) >= 9
    assert "jmode_line(f[1], f[2], f[3], n >= 5 ? f[4] : 0);" in src
    assert "jsong_line(f[1], f[2], n >= 4 ? f[3] : 0, n >= 5 ? f[4] : 0);" in src
    assert re.search(r"JUKE_HOOK\(15\)", src) and "on_juke_start_15," in src
    # a music with no start site draws again at each new game: the background is asked for all game long
    assert "e->game != juke_game()" in src


# ---- the Audio tab ---------------------------------------------------------------------------------
def test_the_window_shows_one_pool_at_a_time(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    monkeypatch.setattr(JB, "pool_rows", lambda project, probe=True: [
        {"key": p.key, "name": p.name, "about": p.about, "intro": bool(JB.pool_intro(_Prof(), p.key))}
        for p in JB.pools(_Prof())])
    proj = _project(tmp_path)
    paths = {n: str(tmp_path / "mine" / ("%s.wav" % n)) for n in ("Help", "Get Back", "Twist")}
    for f in paths.values():
        wav(f)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        rows = w.call("audio.jukebox_open")
        assert [p["key"] for p in rows["pools"]] == ["songs", "special", "background"] and rows["pool"] == "songs"
        assert [p["intro"] for p in rows["pools"]] == [True, True, False]
        w.answers.append([paths["Help"], paths["Get Back"]])
        rows = w.call("audio.jukebox_action", "add")
        assert [g["audio"] for g in rows["songs"]] == ["Help.wav", "Get Back.wav"]
        rows = w.call("audio.jukebox_action", "pool:special")
        assert rows["pool"] == "special" and rows["songs"] == []
        # the same song in a second pool is a song of its own there, not the song modes' one replaced
        w.answers.append([paths["Help"], paths["Twist"]])
        rows = w.call("audio.jukebox_action", "add")
        assert [(g["n"], g["k"], g["audio"]) for g in rows["songs"]] == [(1, 3, "Help.wav"), (2, 4, "Twist.wav")]
        assert [p["n"] for p in rows["pools"]] == [2, 2, 0] and rows["total"] == 4
        rows = w.call("audio.jukebox_action", "down:3")             # moves past its own pool's next song
        assert [g["audio"] for g in rows["songs"]] == ["Twist.wav", "Help.wav"]
        assert [(g["audio"], g.get("pool", "songs")) for g in _sidecar(proj)["jukebox"]["songs"]] == [
            (os.path.normpath(paths["Help"]), "songs"), (os.path.normpath(paths["Get Back"]), "songs"),
            (os.path.normpath(paths["Twist"]), "special"), (os.path.normpath(paths["Help"]), "special")]
        # Clear all… takes out the pool shown, not the others
        w.answers.append("yes")
        rows = w.call("audio.jukebox_action", "clear")
        assert "out of Special modes" in w.asked[-1]["message"] and rows["songs"] == []
        rows = w.call("audio.jukebox_action", "pool:songs")
        assert [g["audio"] for g in rows["songs"]] == ["Help.wav", "Get Back.wav"]
        assert w.call("audio.jukebox_action", "pool:nowhere")["pool"] == "songs"


def test_the_page_has_the_pool_picker():
    with open(os.path.join(os.path.dirname(RUNTIME), "..", "..", "..", "..", "pinball_decryptor", "webui",
                           "static", "js", "tabs", "audio.js"), encoding="utf-8") as f:
        js = f.read()
    assert "act(`pool:${v}`)" in js and "aud-juke-pools" in js
    assert "!pool.intro ?" in js                                     # a pool with no intro shows none
