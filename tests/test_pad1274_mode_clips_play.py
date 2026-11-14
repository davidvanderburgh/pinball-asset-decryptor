"""PAD-1274: the clips a game's own mode plays (Modes > the game's own > How it works) play on a click: the page
gets each clip's file, a clip the page can't play gets the Video tab's preview copy, and "Open on the Video tab"
picks its slot there (waiting for the tab's first scan when the jump starts it)."""
import os
import threading

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import clip_sounds as CS
from pinball_decryptor.webui import modes_how as MH
from pinball_decryptor.webui import video_helpers as vh

JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui", "static", "js", "tabs")


class _Loop:
    def post(self, fn, *a):
        fn(*a)


class _Ctx:
    loop = _Loop()


class _Tab(MH.HowItWorksMixin):
    def __init__(self, project, clips=None, window=None):
        self._init_how()
        self._project = project
        self._how = clips
        self._how_key = ("p", "card", 1, 1)
        self.state = {}
        self.ctx = _Ctx()
        self.window = window

    def project(self):
        return self._project

    def get(self, key, default=None):
        return self.state.get(key, default)

    def set(self, **kw):
        self.state.update(kw)


def test_each_clip_with_an_extracted_file_carries_its_path(tmp_path):
    from tests.test_pad1064_how_it_works import _build
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "gz_mb_start.mp4").write_bytes(b"x")
    reading = CM.Reading(labels={"cmode_godzilla_multiball": "Godzilla Multiball"},
                         refs={"gz_mb_start": [CM.Ref("lone", [0], 0x100, "cmode_godzilla_multiball", "own")],
                               "gz_mb_gone": [CM.Ref("lone", [0], 0x110, "cmode_godzilla_multiball", "own")],
                               "gz_mb_card": [CM.Ref("lone", [0], 0x120, "cmode_godzilla_multiball", "own")]})
    clips = CM.CardClips(card="card", reading=reading, sounds=CS.SoundReading(origin="port").to_json(),
                         name_of={"video/gz_mb_start.mp4": "gz_mb_start", "video/gz_mb_gone.mp4": "gz_mb_gone"})
    how = _Tab(str(tmp_path), clips)._how_for(_build(), 1)
    by = {c["text"]: c for c in how["clips"]}
    assert by["gz_mb_start"]["path"] == os.path.join(str(tmp_path), "video", "gz_mb_start.mp4")
    assert by["gz_mb_start"]["rel"] == "video/gz_mb_start.mp4"
    assert by["gz_mb_start"]["tip"]["lines"] == ["video/gz_mb_start.mp4", "Click to play it"]
    # named in the extract but its file is not there: listed, nothing to play
    assert by["gz_mb_gone"]["path"] == "" and by["gz_mb_gone"]["tip"]["lines"] == ["video/gz_mb_gone.mp4"]
    # only on the card: not in the extract at all
    assert by["gz_mb_card"]["path"] == "" and by["gz_mb_card"]["rel"] == ""
    assert by["gz_mb_card"]["tip"]["lines"] == ["Not in this project's extract"]


def test_open_on_the_video_tab_picks_the_clips_slot():
    asked = []

    class _Video:
        def reveal_video_slot(self, rel):
            asked.append(rel)
            return True

    class _Win:
        def service(self, ns):
            return _Video() if ns == "video" else None

    tab = _Tab("p", window=_Win())
    assert tab.how_clip_video("video/gz_mb_start.mp4") is True
    assert asked == ["video/gz_mb_start.mp4"]
    assert tab.how_clip_video("") is False                     # a clip only on the card has no slot
    tab.window = type("W", (), {"service": lambda self, ns: None})()
    assert tab.how_clip_video("video/x.mp4") is False           # no Video tab for this manufacturer


def test_a_clip_the_page_cannot_play_gets_the_preview_copy(tmp_path, monkeypatch):
    clip = tmp_path / "G_multiball2.mov"
    clip.write_bytes(b"x")
    made = []

    def fake_proxy(path, fmt="mp4"):
        made.append((path, fmt))
        return str(tmp_path / "proxy.webm")

    monkeypatch.setattr(vh, "browser_proxy", fake_proxy)
    done = threading.Event()
    tab = _Tab(str(tmp_path))
    real_post = tab.ctx.loop.post

    class _L:
        def post(self, fn, *a):
            real_post(fn, *a)
            done.set()

    tab.ctx = type("C", (), {"loop": _L()})()
    assert tab.clip_proxy(str(clip), "webm") is True
    assert done.wait(10)
    assert made == [(str(clip), "webm")]
    assert tab.state["clip_proxy"] == {"path": str(clip), "busy": False, "proxy": str(tmp_path / "proxy.webm"),
                                       "err": ""}
    # asked again for the same clip: the copy it has, no second conversion
    assert tab.clip_proxy(str(clip), "webm") is True and len(made) == 1
    assert tab.clip_proxy(str(tmp_path / "missing.mov")) is False


def test_a_failed_preview_copy_says_why(tmp_path, monkeypatch):
    clip = tmp_path / "bad.mov"
    clip.write_bytes(b"x")

    def boom(path, fmt="mp4"):
        raise RuntimeError("ffmpeg could not read it")

    monkeypatch.setattr(vh, "browser_proxy", boom)
    done = threading.Event()
    tab = _Tab(str(tmp_path))

    class _L:
        def post(self, fn, *a):
            fn(*a)
            done.set()

    tab.ctx = type("C", (), {"loop": _L()})()
    tab.clip_proxy(str(clip))
    assert done.wait(10)
    assert tab.state["clip_proxy"]["err"] == "ffmpeg could not read it"
    assert tab.state["clip_proxy"]["proxy"] == "" and tab.state["clip_proxy"]["busy"] is False


def _video_tab(scanning, slots):
    from pinball_decryptor.webui.tabs.video import VideoTab
    tab = VideoTab.__new__(VideoTab)
    shown = []
    tab.window = type("W", (), {"select_tab": lambda self, ns: shown.append(ns)})()
    tab._state = {"scanning": scanning, "view": [0]}
    tab.get = lambda key, default=None: tab._state.get(key, default)
    tab._slots = slots
    tab._by_rel = {s: object() for s in slots}
    tab._index = {s: i for i, s in enumerate(slots)}
    tab._scan_id = 1
    tab._reveal_after_scan = ""
    tab.picked = []
    tab._reselect = lambda rels: tab.picked.append(rels)
    tab._load_track = lambda rel: None
    return tab, shown


def test_a_jump_while_the_video_tab_scans_lands_when_the_scan_does():
    tab, shown = _video_tab(scanning=True, slots=[])
    # the jump shows the tab (which starts its first scan): the slot is not known yet, so it waits
    assert tab.reveal_video_slot("video/G_multiball2_1.mp4") is True
    assert shown == ["video"] and tab.picked == [] and tab._reveal_after_scan == "video/G_multiball2_1.mp4"
    # the scan's list lands, then the waiting jump picks its slot
    tab._slots = ["video/G_multiball2_1.mp4"]
    tab._by_rel = {"video/G_multiball2_1.mp4": object()}
    tab._index = {"video/G_multiball2_1.mp4": 0}
    tab._state["scanning"] = False
    tab._reveal_pending(1)
    assert tab.picked == [["video/G_multiball2_1.mp4"]] and tab._reveal_after_scan == ""
    # a scan another one replaced does not pick anything
    tab._reveal_after_scan = "video/G_multiball2_1.mp4"
    tab._reveal_pending(0)
    assert tab.picked == [["video/G_multiball2_1.mp4"]]


def test_a_jump_to_a_slot_a_finished_scan_does_not_have_fails():
    tab, _ = _video_tab(scanning=False, slots=["video/a.mp4"])
    assert tab.reveal_video_slot("video/missing.mp4") is False
    assert tab.reveal_video_slot("video/a.mp4") is True and tab.picked == [["video/a.mp4"]]


def test_the_page_plays_a_clip_on_a_click():
    modes = open(os.path.join(JS, "modes.js"), encoding="utf-8").read()
    dialogs = open(os.path.join(JS, "modes_dialogs.js"), encoding="utf-8").read()
    for bit in ('class="modes-how-clip mono link"', "onClip(playable, playable.indexOf(c))",
                "<${GameModePage} g=${s.game_mode} s=${s} onClip=${showClips} />",
                "list=${clip.list} at=${clip.at}", "proxy=${s.clip_proxy}"):
        assert bit in modes, bit
    for bit in ('call("modes.clip_proxy", cur.path, proxyFormat())', 'call("modes.how_clip_video", cur.rel)',
                "Open on the Video tab", ">Previous<", ">Next<", 'e.key === "ArrowRight"'):
        assert bit in dialogs, bit
