"""PAD-1015: Project > Export replacement files and Import replacements.

Every file of the user's a project names (each slot's file, the random clips,
the music modes, attract items) copied into one folder (Video, Audio, Images)
with a replacements.json beside them that puts them back on a fresh extract;
and Relink, which only knew the slot maps and the random clips, re-pointing
the music mode files of a moved project too.
"""

import json
import os
import time

from pinball_decryptor.core import relink, replacement_export as rx, staged_changes


def _file(path, data=b"x" * 64):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _project(tmp_path):
    lib = tmp_path / "GZ mods"
    project = tmp_path / "project"
    project.mkdir()
    intro = _file(lib / "clips" / "intro.mp4", b"intro")
    award = _file(lib / "clips" / "award.mp4", b"award")
    take2 = _file(lib / "clips" / "take 2.mp4", b"take2")
    other_intro = _file(lib / "old" / "intro.mp4", b"an older intro")
    roar = _file(lib / "sfx" / "roar.wav", b"RIFFroar")
    theme = _file(lib / "music" / "doom.wav", b"RIFFdoom")
    turn = _file(lib / "music" / "doom 2.wav", b"RIFFdoom2")
    bg = _file(lib / "art" / "bg.png", b"PNGbg")
    photo = _file(lib / "art" / "me.jpg", b"JPGme")
    staged = {
        "video": {"video/attract/intro.mp4": intro, "video/modes/a.mp4": award,
                  "video/modes/b.mp4": award},
        "video_variants": {"video/attract/intro.mp4": [take2, other_intro]},
        "video_length_slots": {"video/modes/a.mp4": "full"},
        "audio": {"audio/roar.wav": roar},
        "audio_levels": {"audio/roar.wav": -3},
        "audio_loop": {"audio/roar.wav": True},
        "sound_modes": {"names": ["", "Doom"],
                        "slots": {"audio/music.wav": {"2": theme}},
                        "turns": {"audio/roar.wav": [turn]},
                        "levels": {"audio/music.wav": {"2": 4}}},
        "image": {"images/bg.png": bg},
        "attract_items": {"items": [{"kind": "photo", "file": photo}]},
        "image_changed_only": True,
        "replacement_names": {"audio/roar.wav": "roar.wav"},
    }
    staged_changes.save(str(project), staged)
    return str(project), staged


# --- what a project names ------------------------------------------------

def test_recorded_files_finds_every_section(tmp_path):
    _p, staged = _project(tmp_path)
    got = rx.recorded_files(staged)
    names = sorted(os.path.basename(p) for p in got)
    assert names == sorted(["intro.mp4", "award.mp4", "take 2.mp4", "intro.mp4",
                            "roar.wav", "doom.wav", "doom 2.wav", "bg.png", "me.jpg"])
    award = [p for p in got if p.endswith("award.mp4")][0]
    assert got[award] == {"kind": "video", "uses": 2}
    assert got[[p for p in got if p.endswith("me.jpg")][0]]["kind"] == "image"
    assert got[[p for p in got if p.endswith("doom.wav")][0]]["kind"] == "audio"


def test_slot_keys_and_names_are_not_files():
    staged = {"replacement_names": {"audio/a.wav": "roar.wav"},
              "own_clips": [{"rel": "video/x.mp4"}], "video": {"video/x.mp4": ""}}
    assert rx.recorded_files(staged) == {}


# --- export ---------------------------------------------------------------

def test_plan_and_export_sort_by_kind_and_rename_clashes(tmp_path):
    project, staged = _project(tmp_path)
    dest = str(tmp_path / "export")
    res = rx.plan(staged, dest, project)
    assert res["counts"] == {"video": 4, "audio": 3, "image": 2}
    assert not res["gone"]
    tos = sorted(os.path.relpath(f["to"], dest).replace("\\", "/") for f in res["files"])
    assert tos == ["Audio/doom 2.wav", "Audio/doom.wav", "Audio/roar.wav",
                   "Images/bg.png", "Images/me.jpg",
                   "Video/award.mp4", "Video/intro (2).mp4", "Video/intro.mp4",
                   "Video/take 2.mp4"]
    out = rx.export(staged, res)
    assert out["copied"] == 9 and not out["cancelled"]
    with open(os.path.join(dest, "Video", "intro (2).mp4"), "rb") as f:
        assert f.read() == b"an older intro"
    # nothing left half-written
    assert not [n for _r, _d, fs in os.walk(dest) for n in fs if n.endswith(".part")]


def test_a_second_export_copies_nothing(tmp_path):
    project, staged = _project(tmp_path)
    dest = str(tmp_path / "export")
    out = rx.export(staged, rx.plan(staged, dest, project))
    again = rx.plan(staged, dest, project)
    assert {f["state"] for f in again["files"]} == {"same"} and again["bytes"] == 0
    # and after the project uses the copies, they are already there
    moved, _n = rx.repoint(staged, out["mapping"])
    there = rx.plan(moved, dest, project)
    assert {f["state"] for f in there["files"]} == {"there"}


def test_missing_and_project_internal_files_are_left_out(tmp_path):
    project = tmp_path / "p"
    snap = _file(project / ".orig" / "video" / "x.mp4")
    staged = {"video": {"video/x.mp4": snap, "video/y.mp4": r"Q:\gone\y.mp4"}}
    res = rx.plan(staged, str(tmp_path / "e"), str(project))
    assert res["files"] == [] and res["gone"] == [r"Q:\gone\y.mp4"]


def test_export_can_be_stopped(tmp_path):
    project, staged = _project(tmp_path)
    dest = str(tmp_path / "export")
    calls = []
    out = rx.export(staged, rx.plan(staged, dest, project),
                    cancel=lambda: len(calls) > 0,
                    progress=lambda *a: calls.append(a))
    assert out["cancelled"] and out["copied"] == 0
    assert not [n for _r, _d, fs in os.walk(dest) for n in fs]     # no half file left


def test_repoint_reaches_every_section(tmp_path):
    project, staged = _project(tmp_path)
    dest = str(tmp_path / "export")
    out = rx.export(staged, rx.plan(staged, dest, project))
    data, n = rx.repoint(staged, out["mapping"])
    assert n == 10
    assert data["video"]["video/modes/b.mp4"] == os.path.join(dest, "Video", "award.mp4")
    assert data["video_variants"]["video/attract/intro.mp4"][1] == \
        os.path.join(dest, "Video", "intro (2).mp4")
    assert data["sound_modes"]["slots"]["audio/music.wav"]["2"] == \
        os.path.join(dest, "Audio", "doom.wav")
    assert data["attract_items"]["items"][0]["file"] == os.path.join(dest, "Images", "me.jpg")
    # settings keyed by slot stay as they were
    assert data["audio_levels"] == {"audio/roar.wav": -3}
    assert data["image_changed_only"] is True


# --- the record and a fresh extract -----------------------------------------

def test_record_round_trip_onto_a_fresh_project(tmp_path):
    project, staged = _project(tmp_path)
    dest = tmp_path / "export"
    out = rx.export(staged, rx.plan(staged, str(dest), project))
    path = rx.write_record(str(dest), rx.make_record(staged, out["mapping"], str(dest),
                                                     game="Godzilla Pro 1.20"))
    rec = json.loads(open(path, encoding="utf-8").read())
    assert rec["records"]["video"]["video/modes/a.mp4"] == "Video/award.mp4"
    assert rec["records"]["sound_modes"]["turns"]["audio/roar.wav"] == ["Audio/doom 2.wav"]
    assert "image_changed_only" not in rec["records"]     # a tab's view, not a replacement
    assert rec["records"]["audio_levels"] == {"audio/roar.wav": -3}
    # the folder moves to another PC, and a fresh extract takes it in
    moved = tmp_path / "elsewhere" / "GZ files"
    os.makedirs(moved.parent)
    os.rename(dest, moved)
    _rec, records, missing = rx.read_record(str(moved / rx.RECORD_NAME))
    assert missing == []
    assert rx.counts_of(records) == {"video": 4, "audio": 3, "image": 2}
    fresh = {"image_changed_only": False, "audio": {"audio/other.wav": r"C:\mine\x.wav"}}
    data, n = rx.import_record(fresh, records)
    assert n == 6
    assert data["audio"]["audio/other.wav"] == r"C:\mine\x.wav"     # kept
    assert data["audio"]["audio/roar.wav"] == str(moved / "Audio" / "roar.wav")
    assert data["video_variants"]["video/attract/intro.mp4"] == [
        str(moved / "Video" / "take 2.mp4"), str(moved / "Video" / "intro (2).mp4")]
    assert data["sound_modes"]["slots"]["audio/music.wav"]["2"] == str(moved / "Audio" / "doom.wav")
    assert data["sound_modes"]["levels"] == {"audio/music.wav": {"2": 4}}
    assert data["audio_loop"] == {"audio/roar.wav": True}
    assert data["video_length_slots"] == {"video/modes/a.mp4": "full"}
    assert data["attract_items"]["items"][0]["file"] == str(moved / "Images" / "me.jpg")
    assert data["image_changed_only"] is False


def test_a_record_names_no_file_outside_its_folder(tmp_path):
    (tmp_path / "e").mkdir()
    path = tmp_path / "e" / rx.RECORD_NAME
    path.write_text(json.dumps({"format": rx.RECORD_FORMAT, "version": 1, "records": {
        "audio": {"a.wav": "Audio/../../secret.wav", "b.wav": "Audio/b.wav"},
        "settings": {"AD_X": 1}}}), encoding="utf-8")
    _rec, records, missing = rx.read_record(str(path))
    assert records["audio"]["a.wav"] == "Audio/../../secret.wav"   # left unresolved
    assert records["audio"]["b.wav"] == str(tmp_path / "e" / "Audio" / "b.wav")
    assert missing == [str(tmp_path / "e" / "Audio" / "b.wav")]
    assert "settings" not in records                    # only replacement records


def test_read_record_refuses_another_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}", encoding="utf-8")
    try:
        rx.read_record(str(p))
    except ValueError:
        return
    raise AssertionError("took a json that is not a record")


# --- Relink (the sibling gap) -------------------------------------------------

def test_relink_repoints_music_mode_and_attract_files():
    staged = {"sound_modes": {"slots": {"audio/m.wav": {"2": r"G:\old\doom.wav"}}},
              "attract_items": {"items": [{"kind": "clip", "file": r"G:\old\me.mp4"}]}}
    got = relink.recorded_sources(staged)
    assert set(got) == {r"G:\old\doom.wav", r"G:\old\me.mp4"}
    data, n_slots, n_files = relink.apply_plan(
        staged, {r"G:\old\doom.wav": r"D:\new\doom.wav", r"G:\old\me.mp4": r"D:\new\me.mp4"})
    assert data["sound_modes"]["slots"]["audio/m.wav"]["2"] == r"D:\new\doom.wav"
    assert data["attract_items"]["items"][0]["file"] == r"D:\new\me.mp4"
    assert (n_slots, n_files) == (2, 2)


# --- the window (web UI) --------------------------------------------------------

def _until(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_export_window_and_import(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="stern") as w:
        r = w.call("shellx.project_new_create", str(tmp_path), "p1", "stern", "")
        assert r["ok"], r
        folder = str(tmp_path / "p1")
        assert w.call("shellx.export_open") is None             # nothing recorded yet
        assert w.asked[-1]["title"] == "Export replacement files"
        lib = tmp_path / "lib"
        clip = _file(lib / "intro.mp4", b"clip")
        song = _file(lib / "song.wav", b"RIFF")
        staged_changes.save(folder, {"video": {"video/intro.mp4": clip},
                                     "sound_modes": {"slots": {"audio/m.wav": {"2": song}}}})
        st = w.call("shellx.export_open")
        assert st["dest"] == str(tmp_path / "p1 files")
        assert {r["to"] for r in st["rows"]} == {"Video/intro.mp4", "Audio/song.wav"}
        assert st["can_export"] and st["repoint"] is True
        dest = str(tmp_path / "out")
        w.call("shellx.export_set_dest", dest)
        assert w.state("shellx")["export"]["dest"] == dest
        w.answers.append("ok")
        assert w.call("shellx.export_run")
        assert _until(w, lambda: w.state("shellx")["job"] is None
                      and os.path.isfile(os.path.join(dest, rx.RECORD_NAME)))
        assert _until(w, lambda: staged_changes.load(folder)["video"]["video/intro.mp4"]
                      == os.path.join(dest, "Video", "intro.mp4"))
        assert staged_changes.load(folder)["sound_modes"]["slots"]["audio/m.wav"]["2"] == \
            os.path.join(dest, "Audio", "song.wav")
        w.call("shellx.export_close")

        # a fresh project takes them back
        r = w.call("shellx.project_new_create", str(tmp_path), "p2", "stern", "")
        assert r["ok"], r
        w.answers.extend(["yes", "ok"])
        assert w.call("shellx.import_replacements", os.path.join(dest, rx.RECORD_NAME))
        data = staged_changes.load(str(tmp_path / "p2"))
        assert data["video"]["video/intro.mp4"] == os.path.join(dest, "Video", "intro.mp4")
        assert data["sound_modes"]["slots"]["audio/m.wav"]["2"] == \
            os.path.join(dest, "Audio", "song.wav")
