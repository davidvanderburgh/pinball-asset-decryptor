"""PAD-999 (an owner filling the jukebox with many songs, each with its intro video): Add songs… takes
the songs' audio and their intro videos picked at once. A video goes with the song of the same name
(the extension aside); a video with no song of its name is left out; a song with no video is added
without one; two files of one name ask which one; a song already in the jukebox takes the old one's
place (its weight, its place in the list and, when none came with it, its intro kept) and the person is
told."""

import os

from pinball_decryptor.plugins.stern import jukebox as JB
from tests.test_pad685_jukebox import _gui_offer


def test_files_named_alike_are_one_song_and_a_lone_video_none():
    songs, lone = JB.pair_files([r"C:\m\Hey Jude.wav", r"C:\m\hey jude.MP4", r"C:\m\Revolution.mp3",
                                 r"C:\m\Let It Be.mov", r"C:\m\Get Back.wav", r"C:\m\Get Back.flac"])
    assert songs == [("hey jude", [r"C:\m\Hey Jude.wav"], [r"C:\m\hey jude.MP4"]),
                     ("revolution", [r"C:\m\Revolution.mp3"], []),
                     ("get back", [r"C:\m\Get Back.wav", r"C:\m\Get Back.flac"], [])]
    assert lone == [r"C:\m\Let It Be.mov"]
    assert JB.song_key(r"C:\x\Hey Jude.wav") == JB.song_key("/y/HEY JUDE.mp4")


def test_add_songs_pairs_the_videos_and_replaces_a_song_of_the_same_name(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    proj = _project(tmp_path)
    old, mine = tmp_path / "old", tmp_path / "mine"
    files = {}
    for d, name in ((old, "Get Back.wav"), (old, "Dig It.wav"), (mine, "Hey Jude.wav"),
                    (mine, "Revolution.wav"), (mine, "Get Back.wav"), (mine, "Two Of Us.wav"),
                    (mine, "Two Of Us.mp3")):
        files[(d.name, name)] = str(d / name)
        wav(str(d / name))
    for d, name in ((old, "Get Back.mp4"), (mine, "Hey Jude.mp4"), (mine, "Let It Be.mp4")):
        (d / name).parent.mkdir(exist_ok=True)
        (d / name).write_bytes(b"v")
        files[(d.name, name)] = str(d / name)
    f = lambda d, n: files[(d, n)]                              # noqa: E731
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([f("old", "Get Back.wav"), f("old", "Get Back.mp4"), f("old", "Dig It.wav")])
        rows = w.call("audio.jukebox_action", "add")
        assert [(g["audio"], g["video"]) for g in rows["songs"]] == [
            ("Get Back.wav", "Get Back.mp4"), ("Dig It.wav", "")]
        w.call("audio.jukebox_action", "weight:1:3")
        w.asked.clear()
        # the batch: two songs with their videos (one without), Get Back again, a video with no
        # song, and Two Of Us twice (the .mp3 is picked)
        w.answers.append([f("mine", "Hey Jude.wav"), f("mine", "Hey Jude.mp4"), f("mine", "Revolution.wav"),
                          f("mine", "Get Back.wav"), f("mine", "Let It Be.mp4"),
                          f("mine", "Two Of Us.wav"), f("mine", "Two Of Us.mp3")])
        w.answers.append("1")                                       # which Two Of Us: the .mp3
        rows = w.call("audio.jukebox_action", "add")
        assert [(g["audio"], g["video"], g["weight_word"]) for g in rows["songs"]] == [
            ("Get Back.wav", "Get Back.mp4", "Common"), ("Dig It.wav", "", "Normal"),
            ("Hey Jude.wav", "Hey Jude.mp4", "Normal"), ("Revolution.wav", "", "Normal"),
            ("Two Of Us.mp3", "", "Normal")]
        pick = [a for a in w.asked if a.get("kind") == "message" and "Which one" in a["message"]]
        assert len(pick) == 1 and [b["label"] for b in pick[0]["buttons"]] == [
            "Two Of Us.wav", "Two Of Us.mp3", "Leave this song out"]
        warn = [a for a in w.asked if a.get("kind") == "message" and a.get("icon") == "warning"]
        assert len(warn) == 1
        assert "Get Back.wav" in warn[0]["message"] and "Let It Be.mp4" in warn[0]["message"]
        side = _sidecar(proj)["jukebox"]["songs"]
        assert side[0] == {"audio": os.path.normpath(f("mine", "Get Back.wav")), "weight": 3,
                           "video": os.path.normpath(f("old", "Get Back.mp4"))}
        # a song left out at the question is not added; a lone video alone adds nothing
        w.asked.clear()
        n = len(rows["songs"])
        w.answers.append([f("old", "Get Back.mp4"), f("mine", "Two Of Us.wav"), f("mine", "Two Of Us.mp3")])
        w.answers.append("none")
        rows = w.call("audio.jukebox_action", "add")
        assert len(rows["songs"]) == n and rows["songs"][0]["video"] == "Get Back.mp4"


def test_the_picker_offers_audio_and_video_together(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, _project(tmp_path))
        w.asked.clear()
        w.call("audio.jukebox_action", "add")
        spec = [a for a in w.asked if a.get("kind") == "file"][0]
        assert spec["multiple"]
        first = spec["filetypes"][0][1].split()
        assert "*.wav" in first and "*.mp4" in first
        assert all(("*" + e) in first for e in JB.VIDEO_EXTS)
