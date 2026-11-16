"""PAD-1279, DragonRR's second round: the Test card is a tab of its own.  Its list
(testcard_core) holds what is ticked TEST in the Images, Video, Audio and Scenes tabs
(testcard_tags.TestTagMixin) and files added from the PC; staging bakes a ticked
picture's colour profile in; the tab runs multiboot_core.testcard_commands with each
item's list (--test KIND:PATH|LABEL).
"""
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIL = pytest.importorskip("PIL.Image")

from pinball_decryptor.webui import testcard_core as tc            # noqa: E402
from pinball_decryptor.webui import testcard_tags as tt            # noqa: E402


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TESTCARD_STORE", str(tmp_path / "store" / "testcard.json"))
    tc._SHARED[:] = []
    yield
    tc._SHARED[:] = []


def _png(path, rgb=(200, 40, 40), size=(64, 48)):
    PIL.new("RGB", size, rgb).save(str(path), "PNG")
    return str(path)


def _file(path, data=b"x"):
    with open(str(path), "wb") as f:
        f.write(data)
    return str(path)


# ---- the list -----------------------------------------------------------------------------

def test_files_from_the_pc_go_in_the_list_their_kind_says(tmp_path):
    lst = tc.shared()
    a = _png(tmp_path / "Sunset.png")
    v = _file(tmp_path / "clip.mp4")
    w = _file(tmp_path / "tone.wav")
    n = _file(tmp_path / "notes.txt")
    added, refused = lst.add_files([a, v, w, n, a, str(tmp_path / "gone.png")])
    assert added == 3
    assert [(it.kind, it.label) for it in lst.items] == [("image", "Sunset"), ("video", "clip"), ("sound", "tone")]
    assert [why for _p, why in refused] == ["not a picture, video or sound", "already on the list", "not a file"]
    # kept beside the settings, and read back
    again = tc.TestCardList()
    assert [(it.kind, it.path) for it in again.items] == [("image", a), ("video", v), ("sound", w)]


def test_a_moving_gif_is_a_video_and_a_still_one_a_picture(tmp_path):
    still = tmp_path / "still.gif"
    PIL.new("RGB", (8, 8)).save(str(still))
    moving = tmp_path / "moving.gif"
    frames = [PIL.new("RGB", (8, 8), (k * 60, 0, 0)) for k in range(3)]
    frames[0].save(str(moving), save_all=True, append_images=frames[1:], duration=50)
    assert tc.kind_of_file(str(still)) == "image" and tc.kind_of_file(str(moving)) == "video"


def test_ticks_are_kept_per_project_and_kind(tmp_path):
    lst = tc.shared()
    proj = str(tmp_path / "Godzilla" / "assets")
    os.makedirs(proj)
    f = _png(os.path.join(proj, "a.png"))
    assert lst.set_tag("image", proj, "img/a.png", True, "a", f, "Godzilla") == (True, "")
    assert lst.set_tag("image", proj + os.sep, "img\\a.png", True, "a", f) == (False, "")     # the same one
    assert lst.tagged("image", proj) == {"img/a.png"}
    assert lst.tagged("video", proj) == set() and lst.tagged("image", str(tmp_path)) == set()
    assert lst.set_tag("image", proj, "img/a.png", False) == (True, "")
    assert lst.items == []


def test_the_card_takes_64_and_says_so(tmp_path):
    lst = tc.shared()
    proj = str(tmp_path)
    for k in range(tc.MAX_ITEMS):
        assert lst.set_tag("sound", proj, "s%d.wav" % k, True)[0]
    assert lst.set_tag("sound", proj, "one-more.wav", True) == (False, "the test card takes at most 64 items")
    assert tc.MAX_ITEMS == 64


def test_moving_stays_inside_its_own_list_and_labels_are_what_the_conf_carries(tmp_path):
    lst = tc.shared()
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png")
    w = _file(tmp_path / "w.wav")
    lst.add_files([a, w, b])
    assert lst.move(2, -1) and [it.label for it in lst.items] == ["b", "w", "a"]
    assert not lst.move(1, 1)                       # the only sound: nowhere to go
    assert lst.rename(0, "  Gray | card\nline  ") and lst.items[0].label == "Gray / card line"
    assert [it.kind for it in lst.ordered()] == ["image", "image", "sound"]
    assert lst.counts() == {"image": 2, "video": 0, "scene": 0, "sound": 1}


# ---- staging: the colour profile goes with a ticked picture ---------------------------------

class _Invert(object):
    def apply_image(self, im):
        from PIL import ImageOps
        return ImageOps.invert(im.convert("RGB"))


def test_a_ticked_picture_carries_its_profile_and_a_pc_file_goes_as_it_is(tmp_path):
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    ticked = tc.Item("image", "Ticked", _png(os.path.join(proj, "t.png")), proj, "t.png")
    mine = tc.Item("image", "Mine", _png(tmp_path / "mine.png"))
    snd = tc.Item("sound", "Tone", _file(tmp_path / "tone.wav"))
    gone = tc.Item("image", "Gone", str(tmp_path / "nope.png"))
    said = []
    out = tc.stage([ticked, mine, snd, gone], str(tmp_path / "work"), log=said.append,
                   resolver=lambda it: _Invert())
    assert [(k, lab) for k, _p, lab in out] == [("image", "Ticked"), ("image", "Mine"), ("sound", "Tone")]
    assert PIL.open(out[0][1]).convert("RGB").getpixel((5, 5)) == (55, 215, 215)      # baked in
    assert out[1][1] == mine.path and out[2][1] == snd.path                           # as they are
    assert any("'Gone' left out: the file is gone" in s for s in said)


def test_a_scene_goes_as_the_picture_drawn_of_its_resting_frame(tmp_path):
    pic = _png(tmp_path / "scene.png")
    it = tc.Item("scene", "Title", pic, str(tmp_path), "scenes/title")
    assert tc.stage([it], str(tmp_path / "w"), log=lambda *a: None) == [("scene", pic, "Title")]
    it.path = str(tmp_path / "gone.png")
    assert tc.item_problem(it) == "its picture is gone: tick it again in the Scenes tab"


def test_the_specs_name_each_items_list(tmp_path):
    assert tc.test_specs([("video", "C:/a b/clip.mp4", "Red | clip"), ("scene", "C:/s.png", "")],
                         to_wsl=lambda p: "/mnt/c" + p[2:]) == [
        "--test", "video:/mnt/c/a b/clip.mp4|Red / clip", "--test", "scene:/mnt/c/s.png|item"]


# ---- the TEST tick ----------------------------------------------------------------------------

def _mfr(multiboot=True, modes=True, era="spike2"):
    return types.SimpleNamespace(capabilities=types.SimpleNamespace(multiboot=multiboot, modes=modes), _era=era)


class _Window(object):
    def __init__(self):
        self.tabs = []
        self.current_mfr = _mfr()


class _Tab(tt.TestTagMixin):
    _tc_kind = "image"

    def __init__(self, project, files):
        self.window = _Window()
        self.window.tabs.append(self)
        self.state = {}
        self._project, self._files = project, files

    def set(self, **kw):
        self.state.update(kw)

    def _tc_project(self):
        return self._project

    def _tc_file(self, rel):
        return self._files.get(rel)


def test_a_tick_puts_the_row_on_the_card_and_every_tab_shows_it(tmp_path):
    proj = str(tmp_path / "TMNT" / "assets")
    os.makedirs(proj)
    f = _png(os.path.join(proj, "logo.png"))
    tab = _Tab(proj, {"logo.png": f})
    assert tab.set_test("logo.png", True)
    assert tab.state["test_tags"] == ["logo.png"] and tab.state["test_full"] is False
    assert tab.state["test_on"] is True
    tab.window.current_mfr = _mfr(modes=False)                  # another maker: no TEST column
    tab._tc_publish()
    assert tab.state["test_on"] is False and tab.state["test_tags"] == []
    tab.window.current_mfr = _mfr()
    it = tc.shared().items[0]
    assert (it.kind, it.label, it.path, it.game) == ("image", "logo", f, "TMNT")
    assert tab.set_test("logo.png", False) and tab.state["test_tags"] == []
    from pinball_decryptor.webui.rpc import RpcError
    with pytest.raises(RpcError, match="not in the project folder"):
        tab.set_test("missing.png", True)
    with pytest.raises(RpcError, match="Open a project first"):
        _Tab("", {}).set_test("logo.png", True)


def test_the_four_tabs_tick_their_own_kind():
    from pinball_decryptor.webui.tabs.images import ImagesTab
    from pinball_decryptor.webui.tabs.video import VideoTab
    from pinball_decryptor.webui.tabs.audio import AudioTab
    from pinball_decryptor.webui.text_scenes import TextScenesService
    got = {c.__name__: c._tc_kind for c in (ImagesTab, VideoTab, AudioTab, TextScenesService)}
    assert got == {"ImagesTab": "image", "VideoTab": "video", "AudioTab": "sound", "TextScenesService": "scene"}
    for c in (ImagesTab, VideoTab, AudioTab, TextScenesService):
        assert issubclass(c, tt.TestTagMixin) and hasattr(c, "set_test")
    js = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
    for name, ns in (("images.js", "images"), ("video.js", "video"), ("audio.js", "audio"),
                     ("text_scenes.js", "text_scenes")):
        src = open(os.path.join(js, name), encoding="utf-8").read()
        assert 'testCol({ ns: "%s"' % ns in src


# ---- the tab -----------------------------------------------------------------------------------

def test_the_tab_is_on_the_rail_for_stern_spike_2_only():
    from pinball_decryptor.webui.tabs import TABS
    assert ("testcard", "testcard", "Test Card", "Test card", "Build", "palette") in TABS
    win = open(os.path.join(ROOT, "pinball_decryptor", "webui", "window.py"), encoding="utf-8").read()
    assert '"Test Card": _testcard_available(mfr),' in win
    assert tc.available(_mfr()) is True
    assert not tc.available(_mfr(era="spike3"))                 # Spike 3
    assert not tc.available(_mfr(modes=False))                  # JJP, BoF, DP, Spooky: no mode runtime
    assert not tc.available(None)
    from pinball_decryptor.webui.tabs.testcard import TestCardTab
    for name in ("add_files", "remove", "move", "rename", "clear", "pick_source", "build", "cancel"):
        assert getattr(getattr(TestCardTab, name), "__pad_rpc__", None) is not None
    assert os.path.isfile(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "testcard.js"))


def _tab():
    from pinball_decryptor.webui.tabs.testcard import TestCardTab
    tab = TestCardTab.__new__(TestCardTab)
    tab.window = _Window()
    tab.state = {}
    tab.set = lambda **kw: tab.state.update(kw)
    tab._busy, tab._cancel, tab._proc, tab._lines = False, False, None, []
    tab._pct, tab._step, tab._msg = None, "", ("", "")
    return tab


def test_the_build_runs_each_step_and_says_where_the_card_is(tmp_path, monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    seen = {}

    def fake(form, out, media, cwd=None, test_specs=None):
        seen["specs"], seen["source"] = test_specs, form.images[0].path
        with open(out, "wb") as f:
            f.truncate(1 << 20)
        return [("prepare", [sys.executable, "-c", "print('converted')"]),
                ("testcard", lambda texts: [sys.executable, "-c", "print(%r)" % texts["prepare"]])]
    monkeypatch.setattr(mbc, "testcard_commands", fake)
    src = _file(tmp_path / "game.raw")
    out = str(tmp_path / "test.raw")
    item = tc.Item("image", "Mine", _png(tmp_path / "mine.png"))
    tab = _tab()
    tab._run(src, out, [item])
    assert tab.state["msg"][0] == "ok" and out in tab.state["msg"][1]
    assert seen["source"] == src and seen["specs"][0] == "--test" and seen["specs"][1].startswith("image:")
    assert "converted" in tab._lines and tab.state["busy"] is False


def test_a_failed_step_says_which_and_why(tmp_path, monkeypatch):
    from pinball_decryptor.webui import multiboot_core as mbc
    monkeypatch.setattr(mbc, "testcard_commands", lambda *a, **k: [
        ("prepare", [sys.executable, "-c", "import sys; print('selectmedia: refused: no ffmpeg'); sys.exit(2)"])])
    tab = _tab()
    tab._run(_file(tmp_path / "g.raw"), str(tmp_path / "t.raw"), [])
    assert tab.state["msg"] == ["bad", "The test card was not built: converting the files stopped (exit 2): "
                                       "selectmedia: refused: no ffmpeg"]


# ---- a scene's tick, through the real Scenes backend --------------------------------------------

def test_a_ticked_scene_is_its_resting_frame_on_black(tmp_path):
    pytest.importorskip("numpy")
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed(proj)
    with web_app(tmp_path / "app", mfr="stern") as w:
        svc = _open(w, proj)
        svc._bg = "Magenta"                     # the preview's own background is not the machine's
        assert w.call("text_scenes.set_test", "/g/scene1", True)
        w.drain()
        assert w.state("text_scenes")["test_tags"] == ["/g/scene1"]
        it = tc.shared().items[0]
        assert (it.kind, it.rel, it.label) == ("scene", "/g/scene1", "scene1") and os.path.isfile(it.path)
        on_magenta = open(it.path, "rb").read()
        svc._bg = "Black"
        svc.render_resting_frame("/g/scene1", str(tmp_path / "black.png"))
        assert open(str(tmp_path / "black.png"), "rb").read() == on_magenta
        assert w.call("text_scenes.set_test", "/g/scene1", False)
        assert tc.shared().items == []
