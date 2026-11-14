"""PAD-1190: a JJP song clip names the song the game plays with it, and plays it along.

The lengths below are the ones measured on Guns N' Roses 3.03 (its clips and a sounds-only
extract of its card): every ``live_edited_<song>`` clip against ``BG_GnR_BEAT_MAP_<song>.ogg``.
"""
import os
import shutil
import subprocess

import pytest

from pinball_decryptor.core import clip_songs as CS

#: song -> (live_edited clip seconds, BEAT_MAP song seconds), GnR 3.03
GNR = {"Better": (296.29, 296.26), "ChineseDemocracy": (201.38, 221.11),
       "CivilWar": (455.12, 455.08), "Coma": (609.00, 608.51), "DontCry": (282.25, 282.98),
       "DoubleTalkingJive": (203.38, 193.78), "Estranged": (559.88, 560.97),
       "ItsSoEasy": (200.50, 199.93), "LiveAndLetDie": (182.21, 179.46),
       "MrBrownstone": (224.38, 224.18), "MyMichelle": (217.04, 217.21),
       "Nightrain": (267.67, 269.18), "NovemberRain": (533.46, 531.26),
       "OutTaGetMe": (255.21, 256.77), "ParadiseCity": (404.17, 404.60),
       "Patience": (355.67, 351.08), "RocketQueen": (372.21, 372.37),
       "SweetChildOMine": (354.58, 352.04), "ThisILove": (323.83, 327.52),
       "WelcomeToTheJungle": (268.67, 266.35), "YouCouldBeMine": (342.29, 341.40)}


def _gnr_sounds():
    """The project's sounds as GnR lays them out, with their lengths."""
    lengths = {}
    for song, (_clip, secs) in GNR.items():
        lengths["sound/music/%s/BG_GnR_BEAT_MAP_%s.ogg" % (song, song)] = secs
        lengths["sound/fx/lit_song_target/FX_GnR_LitSongTarget_%s.wav" % song] = 2.0
    lengths.update({
        "sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg": 455.08,
        "sound/music/TearDownTheWall/BG_GnR_PostersMode_CivilWar_Loop.ogg": 109.71,
        "sound/music/EasterEgg/promo_video_easter_egg.ogg": 96.85,
        "sound/music/Slash Solo/BG_GnR_SlashSolo_01.ogg": 63.0,
        "sound/music/Slash Solo/BG_GnR_SlashSolo_02.ogg": 63.0,
        "sound/fx/encore/FX_GnR_EncoreFireworks_LOOP.wav": 10.8,
    })
    return lengths


def _songs(clip, secs, lengths):
    return CS.songs_for("P", clip, secs, audio=sorted(lengths),
                        duration=lambda p: lengths[os.path.relpath(p, "P").replace(os.sep, "/")])


def test_every_gnr_song_clip_pairs_with_its_song():
    lengths = _gnr_sounds()
    for song, (clip_s, song_s) in GNR.items():
        got = _songs("graphics/Songs/%s/live_edited_%s.webm" % (song, song), clip_s, lengths)
        assert got == [("sound/music/%s/BG_GnR_BEAT_MAP_%s.ogg" % (song, song), song_s)], song


def test_the_other_long_clips_pair_by_their_own_names():
    lengths = _gnr_sounds()
    # a variant clip (its short last word left off)
    assert _songs("live_edited_MyMichelle_expl.webm", 217.04, lengths)[0][0].endswith(
        "BG_GnR_BEAT_MAP_MyMichelle.ogg")
    # the stage cut plays the same song, at its own length
    assert _songs("stage_video_CivilWar.webm", 370.83, lengths) == [
        ("sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg", 455.08)]
    assert _songs("SlashSolo_01.webm", 63.0, lengths) == [
        ("sound/music/Slash Solo/BG_GnR_SlashSolo_01.ogg", 63.0)]
    assert _songs("promo_video_easter_egg.webm", 96.85, lengths) == [
        ("sound/music/EasterEgg/promo_video_easter_egg.ogg", 96.85)]


def test_short_clips_and_far_lengths_pair_with_nothing():
    lengths = _gnr_sounds()
    # a 2 s intro shares its song's name with a 2 s target sound: too short to tell
    assert _songs("Song_Intro_CivilWar.a.webm", 2.12, lengths) == []
    # a 10 s loop and a 10.8 s "LOOP" sound share only a word
    assert _songs("Coma_MB_loop.webm", 10.0, lengths) == []
    # same last words, 23% apart: not its song
    assert _songs("SlashPlaying_easter_egg.webm", 125.83, lengths) == []


def test_names_end_the_same_way():
    assert CS.names_match("live_edited_CivilWar.webm", "BG_GnR_BEAT_MAP_CivilWar.ogg")
    assert CS.names_match("SlashSolo_01.webm", "BG_GnR_SlashSolo_01.ogg")
    assert not CS.names_match("SlashSolo_01.webm", "BG_GnR_SlashSolo_02.ogg")
    assert not CS.names_match("Song_01.webm", "Other_01.ogg")          # a number alone says nothing
    assert CS.names_match("live_edited_ParadiseCity_expl.webm", "BG_GnR_BEAT_MAP_ParadiseCity.ogg")


def test_the_users_own_files_are_not_the_games(tmp_path):
    for rel in ("sound/music/A/BG_Song.ogg", "_Replacements/Songs/BG_Song.ogg",
                ".pad/BG_Song.ogg", "graphics/x.webm"):
        p = tmp_path.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    assert CS.audio_files(str(tmp_path)) == ["sound/music/A/BG_Song.ogg"]


def test_the_lengths_are_said_in_words():
    assert CS.how_words(455.12, 455.08) == "same song name, same length (7:35)"
    assert CS.how_words(370.83, 455.08) == ("same song name; the sound is 7:35, 1:24 longer "
                                            "than the clip")


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_the_video_tab_names_a_jjp_clips_song_and_offers_to_play_it(tmp_path):
    from pinball_decryptor.webui import video_modes as VM
    from tests.test_webui_video import _project, _scan, _wait
    from tests.webui_harness import web_app
    clip = "graphics/Songs/CivilWar/live_edited_CivilWar.webm"
    intro = "graphics/Songs/Intro/Song_Intro_CivilWar.a.webm"
    proj = _project(tmp_path, names=(clip, intro))
    _ffmpeg("-f", "lavfi", "-i", "color=c=black:s=16x16:r=1", "-t", "40", "-c:v", "libvpx-vp9",
            str(proj / clip))
    _ffmpeg("-f", "lavfi", "-i", "color=c=black:s=16x16:r=1", "-t", "2", "-c:v", "libvpx-vp9",
            str(proj / intro))
    song = proj / "sound" / "music" / "CivilWar" / "BG_GnR_BEAT_MAP_CivilWar.ogg"
    song.parent.mkdir(parents=True)
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "40", "-c:a", "libvorbis",
            str(song))

    with web_app(tmp_path, mfr="jjp") as w:
        _scan(w, proj)
        w.call("video.select", clip)
        st = _wait(w, lambda st: ((st.get("preview") or {}).get("sounds") or {}).get("rel") == clip,
                   timeout=60)
        snd = st["preview"]["sounds"]
        # PAD-1266: one row - a short label whose tooltip carries the long head and foot
        assert snd["head"] == VM.SONG_LABEL and snd["sync"] and snd["inline"] and not snd["foot"]
        assert snd["head_tip"] == {"head": VM.SONG_HEAD, "lines": [VM.SONG_FOOT]}
        (it,) = snd["items"]
        assert it["rel"] == "sound/music/CivilWar/BG_GnR_BEAT_MAP_CivilWar.ogg"
        assert it["path"] == str(song) and it["sync"]
        assert it["how"] == "same song name, same length (0:40)"
        # a 2 s clip names no song
        w.call("video.select", intro)
        st = _wait(w, lambda st: (st.get("preview") or {}).get("rel") == intro)
        assert not (st["preview"].get("sounds") or {}).get("items")


def test_the_page_plays_the_song_along_with_the_players():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui",
                           "static", "js", "tabs", "video.js"), encoding="utf-8").read()
    for bit in ('songFollow(e.currentTarget, "play")', 'songFollow(e.currentTarget, "pause")',
                'songFollow(e.currentTarget, "seek")', 'songFollow(v, "stop")',
                "pv.sounds.sync", "<${SongSync}", "T.songSync",
                "pv.sounds.inline", "tip(pv.sounds.head_tip)"):
        assert bit in js, bit
