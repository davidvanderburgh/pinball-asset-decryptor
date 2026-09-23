"""PAD-163 — "Replace from folder…" and what a dropped-in stray is.

A modder converted every Godzilla clip they extracted to black and white,
deleted the extract's clips and dropped theirs in, hoping for "voila, black
and white".  Their converter wrote .mp4 for the card's .mov clips, so those rows
said "not on this card" and blamed a mod pack, and the only other way in was a
replacement pick per clip.  The Replace tabs now take a whole folder by name,
and a stray that is a slot's own file under another type says so.

Driven through the web UI's Replace Audio / Video / Images services
(webui/tabs/audio.py, video.py, images.py).
"""

import os
import time

import pytest

from pinball_decryptor.core import checksums
from tests.webui_harness import web_app

CLIPS = ["Tank_Jackpot1.mov", "Rampage_P.mov", "tilt.mp4"]


def _wait(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _set_project(w, folder):
    def _set():
        try:
            w.window.write_assets_var.set(str(folder))
        except Exception:                               # noqa: BLE001
            pass
    w.run(_set)


def _files(tmp_path, clips=CLIPS):
    assets = str(tmp_path / "project")
    os.makedirs(os.path.join(assets, "video"))
    for name in clips:
        with open(os.path.join(assets, "video", name), "wb") as f:
            f.write(b"stock " + name.encode())
    return assets


def _scan_video(w, assets):
    """Scan *assets* onto the Video tab; the video service."""
    _set_project(w, assets)
    w.call("video.scan")
    svc = w.window.service("video")
    assert _wait(w, lambda: not w.state("video").get("scanning")
                 and w.state("video").get("rows")), w.state("video")
    # the change diff lands after the list; a test's own _foreign & co
    # must not be overwritten by it
    assert _wait(w, lambda: not svc._change_running)
    return svc


def _project(w, tmp_path, clips=CLIPS):
    """A project folder holding *clips* (with the extract's baseline),
    scanned onto the Video tab."""
    assets = _files(tmp_path, clips)
    checksums.generate_checksums(assets)
    return assets, _scan_video(w, assets)


def _bw_folder(tmp_path, names=("Tank_Jackpot1.mp4", "Rampage_P.mp4",
                                "tilt.mp4", "my_new_intro.mp4")):
    folder = str(tmp_path / "BW clips")
    os.makedirs(folder)
    for name in names:
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"bw " + name.encode())
    return folder


def _boxes(w):
    """Every message box asked so far: (icon, title, message)."""
    return [(a["icon"], a["title"], a["message"]) for a in w.asked
            if a.get("kind") == "message"]


def _logs(svc, monkeypatch):
    lines = []
    monkeypatch.setattr(svc, "log",
                        lambda text, level="info", *a, **k:
                        lines.append((level, text)))
    return lines


def test_every_replace_tab_has_the_button(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        names = set(w.ctx.registry.names())
        assert {"audio.replace_from_folder", "video.replace_from_folder",
                "images.from_folder"} <= names


def test_a_folder_of_converted_clips_becomes_one_pick_per_slot(
        tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        assets, svc = _project(w, tmp_path)
        folder = _bw_folder(tmp_path)
        lines = _logs(svc, monkeypatch)
        w.answers += [folder, "yes"]

        assert w.call("video.replace_from_folder") is True

        assert svc._assign == {
            "video/Tank_Jackpot1.mov": os.path.join(folder,
                                                    "Tank_Jackpot1.mp4"),
            "video/Rampage_P.mov": os.path.join(folder, "Rampage_P.mp4"),
            "video/tilt.mp4": os.path.join(folder, "tilt.mp4"),
        }
        [(icon, _title, msg)] = _boxes(w)
        assert icon == "question"
        assert "Use 3 file(s)" in msg
        assert "2 of them are a different file type" in msg
        assert "1 file(s) in the folder are left out" in msg
        # The picks are real picks: saved with the project like any other.
        from pinball_decryptor.core import staged_changes
        assert staged_changes.load(assets)["video"]["video/Rampage_P.mov"] \
            == os.path.join(folder, "Rampage_P.mp4")
        text = "\n".join(t for _l, t in lines)
        assert "picked 3 replacement(s) by name" in text
        assert "my_new_intro.mp4" in text
        # ...and the row says what it will build with.
        row = next(r for r in w.state("video")["rows"]
                   if r["rel"] == "video/Tank_Jackpot1.mov")
        assert "Tank_Jackpot1.mp4" in row["rep"]


def test_no_picks_change_when_the_confirm_is_declined(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _assets, svc = _project(w, tmp_path)

        def _pre():
            svc._assign["video/tilt.mp4"] = "C:\\mine\\tilt.mp4"
        w.run(_pre)
        w.answers += [_bw_folder(tmp_path), "no"]

        assert w.call("video.replace_from_folder") is False

        assert svc._assign == {"video/tilt.mp4": "C:\\mine\\tilt.mp4"}


def test_clips_set_to_go_on_as_is_are_converted_when_the_type_differs(
        tmp_path):
    """As-is needs the slot's own file type; the one-clip picker offers to
    convert just that clip, so the folder does the same for its retyped
    clips and leaves the rest alone."""
    with web_app(tmp_path, mfr="stern") as w:
        _assets, svc = _project(w, tmp_path)
        w.run(svc.video_no_conversion_var.set, True)
        w.drain()
        n_before = len(_boxes(w))
        w.answers += [_bw_folder(tmp_path), "yes"]

        w.call("video.replace_from_folder")

        assert svc._asis == {"video/Tank_Jackpot1.mov": False,
                             "video/Rampage_P.mov": False}
        assert w.run(svc._asis_for, "video/tilt.mp4") is True
        assert "set to be converted" in _boxes(w)[n_before][2]


def test_a_folder_inside_the_project_is_refused(tmp_path):
    """Those files ARE the slots; pairing them with themselves (or with
    strays dropped beside them) is never what anyone wants."""
    with web_app(tmp_path, mfr="stern") as w:
        assets, svc = _project(w, tmp_path)
        w.answers.append(os.path.join(assets, "video"))

        w.call("video.replace_from_folder")

        assert svc._assign == {}
        assert _boxes(w)[0][0] == "warning"
        assert "part of the project folder" in _boxes(w)[0][2]


def test_strays_are_not_offered_as_slots(tmp_path):
    """The dropped-in Tank_Jackpot1.mp4 lists as a row; a folder file of the
    same name must go to the card's clip, not to that stray."""
    with web_app(tmp_path, mfr="stern") as w:
        _assets, svc = _project(w, tmp_path,
                                clips=CLIPS + ["Tank_Jackpot1.mp4"])

        def _stray():
            svc._foreign = {"video/Tank_Jackpot1.mp4"}
        w.run(_stray)
        w.answers += [_bw_folder(tmp_path), "yes"]

        w.call("video.replace_from_folder")

        assert "video/Tank_Jackpot1.mp4" not in svc._assign
        assert "video/Tank_Jackpot1.mov" in svc._assign


def test_nothing_named_like_a_slot_explains_the_fingerprint(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        project = tmp_path / "project"
        project.mkdir()
        _set_project(w, project)
        svc = w.window.service("images")

        def _slots():
            svc._by_rel = {
                "images/scene_textures/glyphs/radimg_512x512_a4a16c84/"
                "U+0069_i.png": None}
            svc._foreign_rels = set()
        w.run(_slots)
        folder = tmp_path / "silent" / "glyphs" / "radimg_512x512_bba78124"
        folder.mkdir(parents=True)
        (folder / "U+0041_A.png").write_bytes(b"png")
        w.answers.append(str(tmp_path / "silent"))

        w.call("images.from_folder")

        [(icon, _title, msg)] = _boxes(w)
        assert icon == "info"
        assert "fingerprint" in msg
        assert "Transfer Mods to New Version" in msg


def test_no_slots_yet_says_to_scan(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("audio.replace_from_folder") is False
        assert _boxes(w)[0][0] == "info"
        assert "Scan" in _boxes(w)[0][2]


def _stray_state(w, svc, stray, twin):
    def _do():
        svc._changed = {stray}
        svc._foreign = {stray}
        svc._twins = {stray: twin}
    w.run(_do)


def test_a_retyped_stray_names_the_cards_file(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _assets, svc = _project(w, tmp_path, clips=["Tank_Jackpot1.mp4"])
        stray = "video/Tank_Jackpot1.mp4"
        _stray_state(w, svc, stray, "video/Tank_Jackpot1.mov")

        text = w.run(svc._rep_pane_empty_text, stray,
                     "no replacement assigned")

        assert "Tank_Jackpot1.mov" in text and "Tank_Jackpot1.mp4" in text
        assert "Replace from folder" in text
        # The card's own clip is gone from this folder, so it has to come
        # back.
        assert "extract the card again" in text
        assert "mod pack" not in text


def test_a_retyped_stray_beside_its_slot_needs_no_new_extract(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _assets, svc = _project(
            w, tmp_path, clips=["Tank_Jackpot1.mov", "Tank_Jackpot1.mp4"])
        stray = "video/Tank_Jackpot1.mp4"
        _stray_state(w, svc, stray, "video/Tank_Jackpot1.mov")

        text = w.run(svc._rep_pane_empty_text, stray, "x")

        assert "Replace from folder" in text
        assert "extract the card again" not in text


def test_any_other_stray_mentions_copies_from_another_extract(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("images")
        stray = ("images/scene_textures/glyphs/radimg_512x512_bba78124/"
                 "U+02C6.png")

        def _do():
            svc._changed_on_disk = {stray}
            svc._foreign_rels = {stray}
            svc._foreign_twins = {}
        w.run(_do)

        text = w.run(svc._rep_pane_empty_text, stray, "x")

        assert "not part of this extract" in text
        assert "different extract" in text and "fingerprint" in text
        assert "Transfer Mods" in text


def test_the_change_diff_records_the_twins_and_logs_them(
        tmp_path, monkeypatch):
    """End to end over the real background diff, the way the reporter left
    the folder: the card's .mov gone and a converted .mp4 of the same name in
    its place."""
    assets = _files(tmp_path, clips=["Tank_Jackpot1.mov", "tilt.mp4"])
    checksums.generate_checksums(assets)
    vid = os.path.join(assets, "video")
    os.remove(os.path.join(vid, "Tank_Jackpot1.mov"))
    with open(os.path.join(vid, "Tank_Jackpot1.mp4"), "wb") as f:
        f.write(b"bw clip")
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("video")
        lines = _logs(svc, monkeypatch)
        _set_project(w, assets)
        w.call("video.scan")
        assert _wait(w, lambda: svc._foreign), w.state("video")

        assert svc._foreign == {"video/Tank_Jackpot1.mp4"}
        assert svc._twins == {
            "video/Tank_Jackpot1.mp4": "video/Tank_Jackpot1.mov"}
        assert _wait(w, lambda: any("aren't part of this extract" in t
                                    for _l, t in lines))
        text = "\n".join(t for _l, t in lines)
        assert "Tank_Jackpot1.mp4 where the card has Tank_Jackpot1.mov" in text
