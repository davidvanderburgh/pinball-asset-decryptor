"""Feedback batch 27 — the Spike 2 tester's re-test round.

Four fixes under test, all logic-level (no window; the Images tab's search
helpers are called directly, the rest run on duck-typed stubs):

* Images search on a FRESH extract: the pre-slicer fix (batch 26) stopped
  scene labels lying, but a sliced extract has thousands of glyph tiles at
  ``glyphs/<atlas-stem>/U+xxxx_?.png`` — and the atlas stem is the FONT's
  filename, which Stern prefixes "Stern_...".  Searching "stern" matched
  3652 letter tiles out of 3710 hits on a real Jaws extract, all through a
  folder name that is not the tile's own.  A glyph now matches on its own
  filename only (or an explicit path query), and never through its
  font-named fallback container.

* The title bar follows the restored project: a restart (or a switch back
  to a manufacturer with a saved project) showed the detected card's
  caption while every tab pointed at the loaded project.

* Archiving the OPEN project closes it instead of refusing — the Project
  menu's Properties dialog only ever targets the active project, so its
  Archive button was a guaranteed dead-end.

* Mod-pack import reports what came in, by kind, and the import returns
  the member names that make that summary possible.
"""

import os
from types import SimpleNamespace

from pinball_decryptor.core import modpack
from pinball_decryptor.webui.tabs.images import (search_hits_path,
                                                 slot_search_hit)


_GLYPH = ("images/scene_textures/glyphs/"
          "radimg_Stern_14_Segment_FooFight_512x512_c9978ea9/U+0041_A.png")
_ATLAS = "images/scene_textures/radimg_Stern_AmityJack_512x512_04d34017.png"
_PLAIN = "images/backgrounds/loading.png"


# ---------------------------------------------------------------------------
# Images search: glyph tiles no longer match through their font's folder name
# ---------------------------------------------------------------------------

def test_glyph_does_not_match_through_its_atlas_folder():
    assert not search_hits_path(_GLYPH, "stern")


def test_glyph_still_matches_its_own_filename():
    assert search_hits_path(_GLYPH, "u+0041")
    assert search_hits_path(_GLYPH, "a.png")


def test_glyph_matches_a_deliberate_path_query():
    assert search_hits_path(_GLYPH, "glyphs/radimg_stern")


def test_non_glyph_rows_keep_full_path_matching():
    # The atlas itself is genuinely named Stern_… — it must keep matching.
    assert search_hits_path(_ATLAS, "stern")
    assert search_hits_path(_PLAIN, "backgrounds")
    assert not search_hits_path(_PLAIN, "stern")


def test_glyph_gets_no_second_chance_through_its_container():
    calls = []

    def group_hit():
        calls.append(1)
        return True                      # the font-named dir:: group "hits"

    assert not slot_search_hit(_GLYPH, "stern", group_hit)
    assert not calls                     # the container walk never even ran


def test_normal_rows_still_reach_their_container():
    assert slot_search_hit(_PLAIN, "aaaaaaaa", lambda: True)
    assert not slot_search_hit(_PLAIN, "aaaaaaaa", lambda: False)


# ---------------------------------------------------------------------------
# Title bar: _apply_manufacturer puts the restored project (back) in the
# title — and clears it when the restored folder isn't a project.
# ---------------------------------------------------------------------------

def _apply_mfr(tmp_path, folder):
    from pinball_decryptor.app import App
    seen = []
    stub = SimpleNamespace(
        _load_manufacturer_paths=lambda key: None,
        _kick_off_prereq_check=lambda mfr: None,
        _project_folder=lambda: folder,
        _set_loaded_project=lambda p: seen.append(p),
        # These tests are about the TITLE; the Emulate tab's card restore
        # and the Multi-boot tab's form ride along in the same method and
        # have their own tests in test_emulate_tab.py and
        # test_multiboot_tab.py.
        _restore_emulate_card=lambda folder: None,
        restore_multiboot_state=lambda folder: None,
        window=SimpleNamespace(apply_manufacturer=lambda mfr: None),
    )
    App._apply_manufacturer(stub, SimpleNamespace(key="stern"))
    return seen


def test_restored_anchored_project_lands_in_the_title(tmp_path):
    proj = tmp_path / "redux beta 2"
    proj.mkdir()
    (proj / ".pinproj").write_text("{}", encoding="utf-8")
    assert _apply_mfr(tmp_path, str(proj)) == [str(proj)]


def test_restored_plain_folder_clears_the_title(tmp_path):
    plain = tmp_path / "not-a-project"
    plain.mkdir()
    assert _apply_mfr(tmp_path, str(plain)) == [None]
    assert _apply_mfr(tmp_path, "") == [None]


# ---------------------------------------------------------------------------
# Archive of a project that is NOT the open one leaves the open one alone.
# (Archiving the OPEN project, which closes it: test_webui_shellx.py
# test_archive_asks_and_closes_the_open_project.)
# ---------------------------------------------------------------------------

def _archive(tmp_path, monkeypatch, active):
    from pinball_decryptor.core import project_ops
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui.shellx_projects import ProjectsMixin

    target = str(tmp_path / "proj")
    os.makedirs(target)
    events = []
    done = []
    stub = SimpleNamespace(
        _running=lambda: False,
        _active_folder=lambda: (target if active else ""),
        window=SimpleNamespace(
            append_log=lambda *a, **k: events.append(("log", a[0]))),
        app=SimpleNamespace(
            _close_active_project=lambda: events.append(("closed",))),
        _projects_changed=lambda: done.append(1),
        # The progress window: run the work inline and report back.
        _start_job=lambda _title, _text, fn, on_done: on_done(
            fn(lambda *a: None, lambda: False), None),
    )
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda *a, **k: events.append(("confirm", a, k))
                        or True)
    monkeypatch.setattr(project_ops, "archive",
                        lambda t, build_dir=None, progress=None, cancel=None:
                        (3, 4096, False))
    assert ProjectsMixin.project_archive(stub, target) is True
    return events, done


def test_archiving_another_project_leaves_the_open_one_alone(tmp_path,
                                                             monkeypatch):
    events, done = _archive(tmp_path, monkeypatch, active=False)
    kinds = [e[0] for e in events]
    assert "closed" not in kinds
    assert done == [1]
    confirm = next(e for e in events if e[0] == "confirm")
    assert "closes it" not in confirm[1][1]


# ---------------------------------------------------------------------------
# Mod-pack import: names out, kinds summarized
# ---------------------------------------------------------------------------

def test_kind_summary_buckets_by_the_apps_own_extensions():
    assert modpack.kind_summary([
        "audio/idx0001.wav", "audio/idx0002.ogg",
        "videos/attract.mp4",
        "images/logo.png", "images/tex.dds",
        "fonts/segment.bin",
    ]) == "2 audio, 1 video, 2 image(s), 1 other"


def test_kind_summary_skips_empty_buckets_and_empty_lists():
    assert modpack.kind_summary(["a.wav"]) == "1 audio"
    assert modpack.kind_summary([]) == ""
