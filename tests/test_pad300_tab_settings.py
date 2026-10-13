"""PAD-300: the Images, Audio, Video and Text tabs save their settings (not the files) to
a file, and load them back."""
import json
import os

import pytest

from pinball_decryptor.core import staged_changes
from pinball_decryptor.core import tab_settings as TS
from pinball_decryptor.webui import compat
from pinball_decryptor.webui import tab_settings_ui


def _file(tmp_path, name, data=b"x"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ---- the media tabs ------------------------------------------------------------------------
def test_audio_settings_round_trip_and_merge(tmp_path):
    a, b = _file(tmp_path, "a.wav"), _file(tmp_path, "b.wav")
    staged = {"audio": {"s/one.wav": a, "s/two.wav": b},
              "audio_loop": {"s/one.wav": True}, "audio_levels": {"s/two.wav": -3},
              "grow_keep_whole": ["s/two.wav"], "audio_trim": True,
              "video": {"v/x.mp4": a}, "image": {"i/y.png": b}}
    out = str(tmp_path / "audio.json")
    assert TS.export_media(staged, "audio", out) == 2
    with open(out, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["kind"] == "audio"
    assert set(doc["sections"]) == {"audio", "audio_loop", "audio_levels",
                                    "grow_keep_whole", "audio_trim"}

    # another project of the card: one pick of its own, one slot the file also sets
    c = _file(tmp_path, "c.wav")
    mine = {"audio": {"s/one.wav": c, "s/three.wav": c}, "audio_trim": False,
            "image": {"i/y.png": a}}
    res = TS.merge_media(mine, TS.read(out, "audio"), "audio",
                         {"s/one.wav", "s/three.wav"})
    assert res.data["audio"] == {"s/one.wav": a, "s/three.wav": c}
    assert res.data["audio_loop"] == {"s/one.wav": True}
    assert res.data["audio_trim"] is True
    assert res.data["image"] == {"i/y.png": a}           # other tabs untouched
    assert "s/two.wav" not in res.data["audio_levels"]
    assert res.slots == {"s/one.wav"}
    assert res.missing == {"s/two.wav"}
    assert res.clash == {"s/one.wav"}
    assert mine["audio"]["s/one.wav"] == c                # the input is not changed


def test_a_pick_whose_file_is_gone_is_kept_for_relink(tmp_path):
    gone = str(tmp_path / "elsewhere" / "pic.png")
    doc = {"format": TS.FORMAT, "kind": "images",
           "sections": {"image": {"i/a.png": gone}, "image_keep_size": ["i/a.png"],
                        "image_group_tags": {"grp": "Title"}}}
    res = TS.merge_media({}, doc, "images", {"i/a.png"})
    assert res.data["image"] == {"i/a.png": gone}
    assert res.data["image_keep_size"] == ["i/a.png"]
    assert res.data["image_group_tags"] == {"grp": "Title"}
    assert res.gone == {"i/a.png"}


def test_a_settings_file_of_another_tab_is_refused(tmp_path):
    out = str(tmp_path / "v.json")
    TS.export_media({"video": {}}, "video", out)
    with pytest.raises(TS.TabSettingsError, match="video settings, not audio"):
        TS.read(out, "audio")
    junk = tmp_path / "junk.json"
    junk.write_text("{}", encoding="utf-8")
    with pytest.raises(TS.TabSettingsError, match="not a PAD settings file"):
        TS.read(str(junk), "video")


class _Window:
    def __init__(self, path):
        self.path = path
        self.cb = {}
        self._relink_hint_for = "x"

    def ask_save(self, *a, **k):
        return self.path

    def ask_open(self, *a, **k):
        return self.path


class _Tab:
    def __init__(self, path):
        self.window = _Window(path)
        self.logged = []
        self.rescans = 0
        self.flushed = 0

    def log(self, text, level="info"):
        self.logged.append(text)

    def invalidate_asset_scans(self, rescan_visible=True):
        assert rescan_visible is False

    def rescan(self):
        self.rescans += 1

    def flush(self):
        self.flushed += 1


@pytest.fixture
def boxes(monkeypatch):
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "showerror", lambda t, m: said.append(m))
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda t, m: said.append(m) or True)
    return said


def test_save_then_load_through_the_tab_helpers(tmp_path, boxes):
    a = _file(tmp_path, "a.mp4")
    src = tmp_path / "src"
    src.mkdir()
    staged_changes.save(str(src), {"video": {"v/one.mp4": a}, "video_trim": True,
                                   "video_length_slots": {"v/one.mp4": "own"}})
    out = str(tmp_path / "video.json")
    tab = _Tab(out)
    assert tab_settings_ui.save_media(tab, "video", str(src), True, tab.flush) == out
    assert tab.flushed == 1

    dst = tmp_path / "dst"
    dst.mkdir()
    staged_changes.save(str(dst), {"audio": {"s/a.wav": a}})
    tab2 = _Tab(out)
    got = tab_settings_ui.load_media(tab2, "video", str(dst), {"v/one.mp4"}, False,
                                     tab2.flush, tab2.rescan)
    assert got == {"slots": 1, "missing": 0, "gone": 0}
    data = staged_changes.load(str(dst))
    assert data["video"] == {"v/one.mp4": a}
    assert data["video_trim"] is True
    assert data["video_length_slots"] == {"v/one.mp4": "own"}
    assert data["audio"] == {"s/a.wav": a}
    assert tab2.rescans == 1 and tab2.window._relink_hint_for is None
    assert "Loaded the settings of 1 slot" in boxes[-1]


def test_load_on_another_card_loads_nothing(tmp_path, boxes):
    out = str(tmp_path / "images.json")
    TS.export_media({"image": {"i/a.png": _file(tmp_path, "a.png")}}, "images", out)
    dst = tmp_path / "dst"
    dst.mkdir()
    tab = _Tab(out)
    assert tab_settings_ui.load_media(tab, "images", str(dst), {"i/other.png"}, False,
                                      tab.flush, tab.rescan) is None
    assert "None of the slots" in boxes[-1]
    assert tab.rescans == 0
    assert staged_changes.load(str(dst)) == {}


# ---- text ----------------------------------------------------------------------------------
def test_text_edits_round_trip_by_scene_and_copy(tmp_path):
    rows = [{"path": "s/a.radium", "original": "PLAY", "replacement": "GO"},
            {"path": "s/a.radium", "original": "PLAY", "replacement": "RUN"},
            {"path": "s/b.radium", "original": "PLAY", "replacement": ""},
            {"path": "s/b.radium", "original": "OVER", "replacement": "OVER"}]
    out = str(tmp_path / "text.json")
    assert TS.export_text(rows, out) == 2
    theirs = [{"path": "s/a.radium", "original": "PLAY", "replacement": ""},
              {"path": "s/a.radium", "original": "PLAY", "replacement": ""},
              {"path": "s/b.radium", "original": "PLAY", "replacement": ""}]
    pairs, missing = TS.match_text(TS.read(out, "text"), theirs)
    assert [(r is theirs[0], r is theirs[1], new) for r, new in pairs] == [
        (True, False, "GO"), (False, True, "RUN")]
    assert missing == []
    pairs, missing = TS.match_text(TS.read(out, "text"), theirs[:1])
    assert [new for _r, new in pairs] == ["GO"]
    assert missing == [["s/a.radium", "PLAY", "RUN"]]


# ---- through the real tabs -----------------------------------------------------------------
def test_images_tab_saves_and_loads_into_another_project(tmp_path, monkeypatch):
    from tests import test_webui_images as T
    from tests.webui_harness import web_app
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(tmp_path / "tags.json"))
    a_root, b_root = tmp_path / "a", tmp_path / "b"
    a_root.mkdir()
    b_root.mkdir()
    src, reps = T._project(a_root)
    dst, _ = T._project(b_root)
    rep = os.path.join(reps, "SpaceGodzilla.png")
    out = str(tmp_path / "images settings.json")
    with web_app(tmp_path, mfr="stern") as w:
        T._set_folder(w, src)
        w.call("images.scan")
        T._wait(w, T._settled)
        w.answers = [rep]
        w.call("images.choose", T.BANNER)
        w.call("images.set_keep", T.BANNER, True)
        w.answers = [out]
        assert w.call("images.settings_save") == out

        T._set_folder(w, dst)
        w.call("images.scan")
        T._wait(w, lambda st: T._settled(st) and st.get("dir") == dst)
        assert w.window.pending_image_assignments(dst) is None
        w.answers = [out]
        assert w.call("images.settings_load") == {"slots": 1, "missing": 0, "gone": 0}
        T._wait(w, lambda st: T._settled(st) and w.window.pending_image_assignments(dst))
        pend = w.window.pending_image_assignments(dst)
        assert pend[1] == {T.BANNER: os.path.normpath(rep)}
        assert pend[2] == frozenset({T.BANNER})
        assert "Loaded the settings of 1 slot" in w.asked[-1].get("message", "") + \
            json.dumps(w.asked[-1])


def test_text_tab_saves_and_loads_edits(tmp_path):
    from tests import test_webui_text as T
    from tests.webui_harness import web_app
    from pinball_decryptor.core import text_manifest
    src = T._manifest(tmp_path / "src", T._rows())
    rows = T._rows()
    rows[0]["replacement"] = "GODZILLA VS RODAN"
    rows[5]["replacement"] = "RODAN THE FIRE DEMON"
    rows[4]["replacement"] = "MOTHRA"
    T._manifest(tmp_path / "src", rows)
    dst = T._manifest(tmp_path / "dst", T._rows()[:4] + [
        {"path": "/godzilla_le/game", "original": "MOTHRA", "replacement": "",
         "budget": 6, "fixed": True}])
    out = str(tmp_path / "text.json")
    with web_app(tmp_path, mfr="stern") as w:
        T._open(w, src)
        w.answers = [out]
        assert w.call("text.settings_save") == out
        T._set_folder(w, dst)
        w.call("text.scan")
        T._wait(w, lambda: w.state("text").get("folder") == dst
                and not w.state("text")["scanning"] and w.state("text")["total"] == 5)
        w.answers = [out]
        assert w.call("text.settings_load") == 1
        got = {(r["path"], r["original"]): r["replacement"]
               for r in text_manifest.load(dst)}
        assert got[("/g/aaaaaaaaaaaaaaaaaaaa/scene.radium", "GODZILLA VS EBIRAH")] == \
            "GODZILLA VS RODAN"
        assert "1 of them is not on this card" in json.dumps(w.asked[-1])


def test_video_tab_saves_and_loads_into_another_project(tmp_path):
    """PAD-555: the Video tab's Save settings stopped on "'VideoTab' object
    has no attribute '_save_staged_changes'" (and Load settings would have)."""
    from tests import test_webui_video as T
    from tests.webui_harness import web_app
    a_root, b_root = tmp_path / "a", tmp_path / "b"
    a_root.mkdir()
    b_root.mkdir()
    src, dst = T._project(a_root), T._project(b_root)
    mine = T._mine(tmp_path)
    out = str(tmp_path / "video settings.json")
    with web_app(tmp_path, mfr="stern") as w:
        T._scan(w, src)
        w.answers.append(str(mine))
        assert w.call("video.choose", "video/intro.mp4") is True
        w.answers = [out]
        assert w.call("video.settings_save") == out
        assert TS.read(out, "video")

        T._set_project(w, dst)
        w.call("video.scan")
        T._wait(w, lambda st: not st.get("scanning") and st.get("rows")
                and st.get("project") == str(dst))
        assert w.window.pending_video_assignments(str(dst)) is None
        w.answers = [out]
        assert w.call("video.settings_load") == {"slots": 1, "missing": 0, "gone": 0}
        T._wait(w, lambda st: not st.get("scanning") and st.get("rows")
                and w.window.pending_video_assignments(str(dst))[1])
        assigns = w.window.pending_video_assignments(str(dst))[1]
        assert assigns == {"video/intro.mp4": str(mine)}
