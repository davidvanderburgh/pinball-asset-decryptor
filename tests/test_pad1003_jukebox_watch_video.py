"""PAD-1003 (an owner asking to see a jukebox song's intro video, not only hear the song): the Jukebox
window's rows carry each intro video's path, for its own preview window, and a video the page's engine
can't play as it is plays from a copy made of it (video_helpers.browser_proxy, the Video tab's own),
asked for by the song's number, so the page can only have the jukebox's own videos converted."""

from tests.test_pad685_jukebox import _gui_offer


def test_watch_a_songs_intro_video(tmp_path, monkeypatch):
    from pinball_decryptor.webui import video_helpers as vh
    from tests.test_webui_audio import _open, _project, _wav as wav
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    made = []

    def proxy(path, fmt="mp4"):
        made.append((path, fmt))
        if path.endswith(".wmv"):
            raise RuntimeError("ffmpeg failed")
        return str(tmp_path / ("copy." + fmt))
    monkeypatch.setattr(vh, "browser_proxy", proxy)
    proj = _project(tmp_path)
    mine = tmp_path / "mine"
    wav(str(mine / "Hey Jude.wav"))
    wav(str(mine / "Revolution.wav"))
    wav(str(mine / "Let It Be.wav"))
    (mine / "Hey Jude.mpg").write_bytes(b"v")
    (mine / "Revolution.wmv").write_bytes(b"v")
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        w.answers.append([str(mine / n) for n in ("Hey Jude.wav", "Hey Jude.mpg", "Revolution.wav",
                                                  "Revolution.wmv", "Let It Be.wav")])
        rows = w.call("audio.jukebox_action", "add")
        assert [(g["video"], g["vpath"]) for g in rows["songs"]] == [
            ("Hey Jude.mpg", str(mine / "Hey Jude.mpg")), ("Revolution.wmv", str(mine / "Revolution.wmv")),
            ("", "")]
        assert w.call("audio.jukebox_preview", 1, "webm") == {"path": str(tmp_path / "copy.webm")}
        assert made == [(str(mine / "Hey Jude.mpg"), "webm")]
        # a copy that can't be made says why; a song with no video, or one gone, makes nothing
        assert "ffmpeg failed" in w.call("audio.jukebox_preview", 2)["error"]
        made.clear()
        assert "not on this PC" in w.call("audio.jukebox_preview", 3)["error"]
        assert "not on this PC" in w.call("audio.jukebox_preview", 9)["error"]
        (mine / "Hey Jude.mpg").unlink()
        assert "not on this PC" in w.call("audio.jukebox_preview", 1)["error"]
        assert made == []
