"""Tests for core.relink — repointing a project's recorded replacement
sources after the project (or the media library) moves to another PC."""

import os

from pinball_decryptor.core import relink, staged_changes


def _staged():
    return {
        "audio": {"audio/idx0001.wav": r"G:\GZ media\audio\roar.wav",
                  "audio/idx0002.wav": r"G:\GZ media\audio\roar.wav"},
        "video": {"video/intro.mov": r"G:\GZ media\video\intro.mp4"},
        "image": {"images/logo.png": r"G:\GZ media\art\logo.png"},
        "audio_loop": {"audio/idx0001.wav": True},
        "audio_levels": {"audio/idx0001.wav": 3},
    }


# --- what the sidecar records -----------------------------------------

def test_recorded_sources_groups_slots_by_source_file():
    got = relink.recorded_sources(_staged())
    assert got[r"G:\GZ media\audio\roar.wav"] == [
        ("audio", "audio/idx0001.wav"), ("audio", "audio/idx0002.wav")]
    assert len(got) == 3          # one entry per FILE, not per slot


def test_recorded_sources_ignores_blanks_and_non_dicts():
    assert relink.recorded_sources({"audio": {"a.wav": ""},
                                    "video": "nonsense"}) == {}
    assert relink.recorded_sources(None) == {}


def test_missing_sources_keeps_only_the_files_that_are_gone(tmp_path):
    here = str(tmp_path / "here.wav")
    open(here, "wb").close()
    staged = {"audio": {"a.wav": here, "b.wav": r"G:\gone\x.wav"}}
    assert list(relink.missing_sources(staged)) == [r"G:\gone\x.wav"]


def test_missing_sources_counts_an_unreachable_drive_as_missing():
    def boom(_p):
        raise OSError("the network path was not found")
    staged = {"video": {"v.mov": r"\\nas\share\clip.mp4"}}
    assert list(relink.missing_sources(staged, isfile=boom)) == [
        r"\\nas\share\clip.mp4"]


# --- "these were last seen in ..." ------------------------------------

def test_common_root_of_windows_paths():
    assert relink.common_root([r"G:\GZ media\audio\roar.wav",
                               r"G:\GZ media\video\intro.mp4"]) \
        == r"G:\GZ media"


def test_common_root_ignores_case_but_keeps_the_first_spelling():
    assert relink.common_root([r"G:\GZ Media\a\x.wav",
                               r"g:\gz media\b\y.wav"]) == r"G:\GZ Media"


def test_common_root_of_two_drives_is_empty():
    assert relink.common_root([r"G:\a\x.wav", r"H:\b\y.wav"]) == ""
    assert relink.common_root([]) == ""


def test_common_root_at_a_drive_root():
    assert relink.common_root([r"G:\x.wav", r"G:\y.wav"]) == "G:\\"


# --- searching the new location ---------------------------------------

def _tree(tmp_path, *rels):
    for rel in rels:
        p = tmp_path.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return str(tmp_path)


def test_build_index_only_keeps_the_names_we_are_looking_for(tmp_path):
    root = _tree(tmp_path, "a/roar.wav", "b/unrelated.wav")
    idx = relink.build_index(root, wanted_names={"roar.wav"})
    assert list(idx) == ["roar.wav"]
    assert idx["roar.wav"] == [os.path.join(root, "a", "roar.wav")]


def test_build_index_skips_dot_directories(tmp_path):
    root = _tree(tmp_path, ".orig/roar.wav", "a/roar.wav")
    idx = relink.build_index(root, wanted_names={"roar.wav"})
    assert idx["roar.wav"] == [os.path.join(root, "a", "roar.wav")]


def test_build_index_stops_when_cancelled(tmp_path):
    root = _tree(tmp_path, "a/roar.wav")
    assert relink.build_index(root, cancel=lambda: True) == {}


def test_best_match_prefers_the_candidate_whose_tail_agrees():
    idx = {"intro.mp4": [r"D:\media\Gigan\intro.mp4",
                         r"D:\media\Godzilla\intro.mp4"]}
    new, n = relink.best_match(r"G:\old\Godzilla\intro.mp4", idx)
    assert new == r"D:\media\Godzilla\intro.mp4"
    assert n == 2


def test_best_match_breaks_a_tie_on_the_shallowest_path():
    idx = {"logo.png": [r"D:\media\backup\old\logo.png", r"D:\media\logo.png"]}
    assert relink.best_match(r"G:\art\logo.png",
                             idx)[0] == r"D:\media\logo.png"


def test_best_match_reports_nothing_when_the_name_is_absent():
    assert relink.best_match(r"G:\art\logo.png", {}) == (None, 0)


# --- plan + apply ------------------------------------------------------

def test_plan_finds_the_moved_files_under_the_new_folder(tmp_path):
    root = _tree(tmp_path, "audio/roar.wav", "video/intro.mp4")
    res = relink.plan(_staged(), root)
    assert res["found"][r"G:\GZ media\audio\roar.wav"] == os.path.join(
        root, "audio", "roar.wav")
    assert res["found"][r"G:\GZ media\video\intro.mp4"] == os.path.join(
        root, "video", "intro.mp4")
    assert res["not_found"] == [r"G:\GZ media\art\logo.png"]
    assert res["ambiguous"] == {}


def test_plan_leaves_a_replacement_that_is_still_on_this_pc_alone(tmp_path):
    root = _tree(tmp_path, "audio/roar.wav")
    here = str(tmp_path / "audio" / "roar.wav")
    staged = {"audio": {"a.wav": here}}
    res = relink.plan(staged, root)
    assert res["found"] == {} and res["not_found"] == []


def test_plan_flags_a_name_that_exists_more_than_once(tmp_path):
    root = _tree(tmp_path, "a/intro.mp4", "b/intro.mp4")
    res = relink.plan({"video": {"v.mov": r"G:\old\intro.mp4"}}, root)
    assert res["ambiguous"][r"G:\old\intro.mp4"] == 2


def test_apply_plan_repoints_every_slot_using_a_found_file():
    staged = _staged()
    res = relink.plan(staged, "ignored", isfile=lambda p: False,
                      walk=lambda r: [])
    found = {r"G:\GZ media\audio\roar.wav": r"D:\new\roar.wav"}
    data, n_slots, n_files = relink.apply_plan(staged, found)
    assert n_slots == 2 and n_files == 1
    assert data["audio"] == {"audio/idx0001.wav": r"D:\new\roar.wav",
                             "audio/idx0002.wav": r"D:\new\roar.wav"}
    # Untouched: the file nobody found, and every per-slot flag.
    assert data["video"] == staged["video"]
    assert data["audio_loop"] == {"audio/idx0001.wav": True}
    assert data["audio_levels"] == {"audio/idx0001.wav": 3}
    assert res["found"] == {}


def test_apply_plan_does_not_mutate_the_sidecar_it_was_given():
    staged = _staged()
    relink.apply_plan(staged, {r"G:\GZ media\video\intro.mp4":
                               r"D:\new\intro.mp4"})
    assert staged["video"]["video/intro.mov"] == r"G:\GZ media\video\intro.mp4"


def test_relinked_assignments_come_back_live(tmp_path):
    """End to end: a moved project's dropped assignments restore after a
    relink — which is the whole point (staged_changes.live_assignments is
    what the Replace tabs restore from)."""
    root = _tree(tmp_path, "media/roar.wav")
    staged = {"audio": {"audio/idx0001.wav": r"G:\GZ media\audio\roar.wav"}}
    slots = {"audio/idx0001.wav": object()}
    assert staged_changes.live_assignments(staged["audio"], slots) == {}

    res = relink.plan(staged, root)
    data, n_slots, _ = relink.apply_plan(staged, res["found"])
    assert n_slots == 1
    assert staged_changes.live_assignments(data["audio"], slots) == {
        "audio/idx0001.wav": os.path.join(root, "media", "roar.wav")}


def test_summary_line_names_what_is_still_missing():
    res = {"root": r"D:\media", "found": {"a": "b"}, "not_found": ["c", "d"]}
    line = relink.summary_line(res, 3)
    assert "1 replacement file(s) across 3 slot(s)" in line
    assert r"D:\media" in line and "2 file(s) still not found" in line
