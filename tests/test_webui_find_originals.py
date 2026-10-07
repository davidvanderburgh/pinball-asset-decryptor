"""The Audio and Images tabs' "Find originals…" window (webui/find_originals.py,
PAD-443): picks that are copies off a card, found again among the user's own
files by content and swapped in.

Each project here is set up the way "Transfer Mods to New Version" from an
extract of a built card leaves one: the picks are files in an OLD extract
(it has a baseline, so they are copies off a card), and the user's own files,
named nothing like the slots, sit in a folder of their own.  The matching is
the real core.original_match on tiny made-up sounds and pictures."""

import json
import os
import shutil
import time

import pytest

from tests.test_original_match import (_art, _copy_file, _picture_copy,
                                       _tune, _write, needs_ffmpeg)
from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    """Never touch the real per-card name library under %APPDATA%."""
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "tag_library.json"))


def _wait(w, ns, cond, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if cond(w.state(ns)):
            return w.state(ns)
        time.sleep(0.05)
    raise AssertionError("timed out; %s.originals: %r"
                         % (ns, w.state(ns).get("originals")))


def _sidecar(folder):
    from pinball_decryptor.core import staged_changes
    return staged_changes.load(folder)


def _write_picks(project, key, picks, **extra):
    data = {key: picks}
    data.update(extra)
    with open(os.path.join(project, ".staged_changes.json"), "w",
              encoding="utf-8") as f:
        json.dump(data, f)


def _find(w, ns, folder):
    assert w.call(ns + ".originals_open") is True
    assert w.state(ns)["originals"]["open"]
    w.call(ns + ".originals_set", "folder", str(folder))
    assert w.call(ns + ".originals_find") is True
    return _wait(w, ns, lambda st: not st["originals"]["busy"]
                 and (st["originals"]["rows"] or st["originals"]["status"]
                      and "…" not in st["originals"]["status"]))["originals"]


# ------------------------------------------------------------------ audio
def _audio_project(tmp_path):
    from pinball_decryptor.core import checksums
    project = tmp_path / "proj"
    old = tmp_path / "V1.93 card extract"
    mine = tmp_path / "My sounds"
    for i in (1, 2, 3):
        _write(project / "audio" / ("idx000%d.wav" % i), _tune(50 + i))
    checksums.generate_checksums(str(project))
    picks = {}
    for i in (1, 2):
        x = _tune(i)
        _write(mine / ("final mix %d.wav" % i), x)
        picks["audio/idx000%d.wav" % i] = _copy_file(
            old / "audio" / ("idx000%d.wav" % i), x)
    _write(mine / "outtake.wav", _tune(77))
    checksums.generate_checksums(str(old))
    _write_picks(str(project), "audio", picks)
    return str(project), mine, picks


def _open_audio(w, project):
    w.run(lambda: w.window.write_assets_var.set(project))
    w.call("ui.select_tab", "audio")
    _wait(w, "audio", lambda st: st["rows"] and not st["scanning"]
          and "still checking" not in (st["status"] or ""))


@needs_ffmpeg
def test_audio_finds_the_files_behind_card_copies_and_uses_them(tmp_path):
    project, mine, picks = _audio_project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _open_audio(w, project)
        o = _find(w, "audio", mine)
        assert "2 sounds to look for: 2 are copies off a card" in o["summary"]
        rows = {r["rel"]: r for r in o["rows"]}
        assert set(rows) == {"audio/idx0001.wav", "audio/idx0002.wav"}
        for i in (1, 2):
            r = rows["audio/idx000%d.wav" % i]
            assert r["file"] == "final mix %d.wav" % i
            assert r["use"] and r["sure"] and r["info"].startswith("WAV 48 kHz")
            assert r["ref"] == picks[r["rel"]] and r["now"] == "idx000%d.wav" % i
        assert o["can_apply"] and "2 certain" in o["status"]
        # untick one: only the other is swapped
        w.call("audio.originals_use_row", "audio/idx0002.wav", False)
        assert w.call("audio.originals_apply") is True
        side = _sidecar(project)["audio"]
        assert side["audio/idx0001.wav"] == str(mine / "final mix 1.wav")
        assert side["audio/idx0002.wav"] == picks["audio/idx0002.wav"]
        o = w.state("audio")["originals"]
        assert o["status"].startswith("Done: 1 file") and not o["can_apply"]
        logs = " ".join(m["text"] for m in w.window.log_history())
        assert "now use the file of your own" in logs
        w.call("audio.originals_close")
        assert not w.state("audio")["originals"]["open"]


@needs_ffmpeg
def test_a_pick_already_your_own_is_left_alone(tmp_path):
    project, mine, picks = _audio_project(tmp_path)
    # slot 1 already picks a file of the user's own (not in any extract)
    own = tmp_path / "elsewhere" / "intermediate.wav"
    _write(own, _tune(1)[::2], 24000)
    # slot 3 picks one with nothing like it in the folder
    lone = tmp_path / "elsewhere" / "lonely.wav"
    _write(lone, _tune(99))
    picks = dict(picks, **{"audio/idx0001.wav": str(own),
                           "audio/idx0003.wav": str(lone)})
    _write_picks(project, "audio", picks)
    with web_app(tmp_path, mfr="ap") as w:
        _open_audio(w, project)
        o = _find(w, "audio", mine)
        assert "2 are already files of your own" in o["summary"]
        rows = {r["rel"]: r for r in o["rows"]}
        # found a better copy of the user's own pick: listed, unticked
        assert rows["audio/idx0001.wav"]["file"] == "final mix 1.wav"
        assert rows["audio/idx0001.wav"]["use"] is False
        assert "a file of your own is picked now" in \
            rows["audio/idx0001.wav"]["note"]
        # nothing found for the other one of the user's own: not listed
        assert "audio/idx0003.wav" not in rows
        assert "1 more already use files of your own" in o["status"]
        assert rows["audio/idx0002.wav"]["use"] is True


@needs_ffmpeg
def test_a_longer_file_asks_for_trim_pad(tmp_path):
    from pinball_decryptor.core import checksums
    project, mine, picks = _audio_project(tmp_path)
    x = _tune(5)
    long_take = __import__("numpy").concatenate([x, _tune(6)])
    _write(mine / "long take.wav", long_take)
    picks["audio/idx0003.wav"] = _copy_file(
        tmp_path / "V1.93 card extract" / "audio" / "idx0003.wav", long_take,
        cut=1.2)
    checksums.generate_checksums(str(tmp_path / "V1.93 card extract"))
    _write_picks(project, "audio", picks, audio_trim=False)
    with web_app(tmp_path, mfr="ap") as w:
        _open_audio(w, project)
        if not w.state("audio")["trim_visible"]:
            pytest.skip("this manufacturer always trims")
        o = _find(w, "audio", mine)
        row = next(r for r in o["rows"] if r["rel"] == "audio/idx0003.wav")
        assert row["file"] == "long take.wav"
        assert "needs Trim / pad" in row["note"]
        w.answers.append("no")
        assert w.call("audio.originals_apply") is True
        assert "run longer" in w.asked[-1]["message"]
        side = _sidecar(project)
        assert side["audio"]["audio/idx0003.wav"] == picks["audio/idx0003.wav"]
        assert side["audio"]["audio/idx0001.wav"] == str(
            mine / "final mix 1.wav")
        assert not side.get("audio_trim")


def test_find_says_what_it_needs(tmp_path):
    from pinball_decryptor.core import checksums
    project = tmp_path / "proj"
    _write(project / "audio" / "idx0001.wav", _tune(1))
    checksums.generate_checksums(str(project))
    with web_app(tmp_path, mfr="ap") as w:
        _open_audio(w, str(project))
        assert w.call("audio.originals_open") is True
        o = w.state("audio")["originals"]
        assert "No replacements are picked" in o["summary"]
        assert w.call("audio.originals_find") is False
        assert "Pick the folder" in w.asked[-1]["message"]
        w.call("audio.originals_set", "folder", str(tmp_path))
        assert w.call("audio.originals_find") is False
        assert "nothing to find the originals of" in w.asked[-1]["message"]


# ------------------------------------------------------------------ images
TEX = "images/scene_textures/"


def _images_project(tmp_path):
    from pinball_decryptor.core import checksums
    project = tmp_path / "gz"
    old = tmp_path / "V1.93 card extract"
    mine = tmp_path / "My art"
    (project / "images" / "scene_textures").mkdir(parents=True)
    mine.mkdir()
    names = ["radimg_%dx64_%08d.png" % (96, i) for i in range(4)]
    for i, n in enumerate(names):
        _art(60 + i).save(project / TEX / n)
    checksums.generate_checksums(str(project))
    picks = {}
    for i, n in enumerate(names[:3]):
        master = _art(i).resize((192, 128), Image.LANCZOS)
        master.save(mine / ("BW %d.png" % i))
        picks[TEX + n] = _picture_copy(old / TEX / n, master, (96, 64))
    for seed in range(30, 36):
        _art(seed).save(mine / ("other %d.png" % seed))
    checksums.generate_checksums(str(old))
    return str(project), mine, picks, names


def _open_images(w, project):
    def _do():
        try:
            w.window.write_assets_var.set(project)
        except Exception:                                # noqa: BLE001
            pass
    w.run(_do)
    w.call("images.scan")
    _wait(w, "images", lambda st: not st.get("scanning") and st.get("total")
          and "still checking" not in (st.get("status") or ""))


def test_images_finds_the_masters_behind_card_copies(tmp_path):
    project, mine, picks, names = _images_project(tmp_path)
    _write_picks(project, "image", picks,
                 image_keep_size=[TEX + names[2]])
    with web_app(tmp_path, mfr="stern") as w:
        _open_images(w, project)
        o = _find(w, "images", mine)
        assert "3 pictures to look for: 3 are copies off a card" in o["summary"]
        rows = {r["rel"]: r for r in o["rows"]}
        for i, n in enumerate(names[:3]):
            r = rows[TEX + n]
            assert r["file"] == "BW %d.png" % i and r["sure"]
            assert r["info"] == "192x128 PNG" and r["ref"] == picks[TEX + n]
        assert rows[TEX + names[0]]["use"] and rows[TEX + names[1]]["use"]
        # Keep size is on for this slot: the master would go on at its own
        # size, so it is not ticked
        kept = rows[TEX + names[2]]
        assert kept["use"] is False and "Keep size is on" in kept["note"]
        assert w.call("images.originals_apply") is True
        side = _sidecar(project)["image"]
        assert side[TEX + names[0]] == str(mine / "BW 0.png")
        assert side[TEX + names[1]] == str(mine / "BW 1.png")
        assert side[TEX + names[2]] == picks[TEX + names[2]]


def test_apply_refuses_once_the_project_changed(tmp_path):
    project, mine, picks, names = _images_project(tmp_path)
    _write_picks(project, "image", picks)
    other = tmp_path / "other project"
    shutil.copytree(project, other)
    with web_app(tmp_path, mfr="stern") as w:
        _open_images(w, project)
        _find(w, "images", mine)
        _open_images(w, str(other))
        assert w.call("images.originals_apply") is False
        assert "changed since the search" in w.asked[-1]["message"]
        assert _sidecar(str(other))["image"] == picks
