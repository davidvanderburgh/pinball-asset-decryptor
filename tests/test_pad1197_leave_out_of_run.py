"""PAD-1197 (DragonRR): "I need to have a facility to turn off any items individually
which can slow the speed at which the emulator is able to run up especially after the
first time. I think one of the problems would be the extra audio tracks/variants and
possibly video variants?"

  1. ``run_leave_out``: the kinds, which a project is offered, the words for the log.
  2. the engine: a kind left out is not in the set (the patch computation never sees it),
     and the set's manifest says what it went without.
  3. a set built with other kinds left out is not reused.
  4. the Replace tabs' picks of a left-out kind are not converted at Start.
  5. the Emulate tab: the ticks, and what a Start hands the staging and the build.
"""

import io
import json
import types

import pytest

from tests.test_emulate_overrides import card  # noqa: F401  (fixture)
from tests.test_emulate_overrides import _disk
from tests.test_pad489_emulate_conversion_progress import _tab

from pinball_decryptor.plugins.stern import engine, run_leave_out


# --------------------------------------------------------------------------
# 1. the kinds
# --------------------------------------------------------------------------

def test_clean_keeps_known_kinds_sorted():
    assert run_leave_out.clean("videos, sounds,bogus,,") == ("sounds", "videos")
    assert run_leave_out.clean(["modes", "modes"]) == ("modes",)
    assert run_leave_out.clean(None) == ()


def test_said_names_them_in_the_tabs_order():
    assert run_leave_out.said(["videos", "sounds"]) == "replaced sounds and replaced videos"
    assert run_leave_out.said(["modes", "random_clips", "sounds"]) == \
        "replaced sounds, random clips and modes"
    assert run_leave_out.said([]) == ""


def test_a_plain_project_is_offered_the_replaced_kinds_only(tmp_path):
    assert run_leave_out.offered(str(tmp_path)) == ["sounds", "videos", "pictures"]


def test_music_modes_random_clips_and_modes_are_offered_when_the_project_has_them(tmp_path):
    from pinball_decryptor.plugins.stern import clip_variants, sound_modes
    (tmp_path / ".staged_changes.json").write_text(json.dumps({
        sound_modes.STAGED_KEY: {"names": ["Standard", "Custom A"],
                                 "slots": {"audio/idx2095 - music.wav": {"2": "C:/x/song.wav"}}},
        clip_variants.STAGED_KEY: {"video/EndOfBall.mp4": ["C:/x/a.mp4"]},
    }), encoding="utf-8")
    slug = tmp_path / "modes" / "kaiju"
    slug.mkdir(parents=True)
    (slug / "kaiju.c").write_text("/* a code mode */")
    assert run_leave_out.offered(str(tmp_path)) == [
        "sounds", "music_modes", "videos", "random_clips", "pictures", "modes"]


def test_the_words_keep_to_the_house_rules():
    for _k, label, tip in run_leave_out.KINDS:
        for text in (label, tip):
            assert "—" not in text and "–" not in text


# --------------------------------------------------------------------------
# 2. the engine leaves them out
# --------------------------------------------------------------------------

def _scan_only(monkeypatch, tmp_path, kinds, logged):
    """_compute_patches_inner over an empty project whose one change is a replaced video,
    with *kinds* left out; its log lines go into *logged*."""
    assets = tmp_path / "proj"
    assets.mkdir()
    monkeypatch.setattr("pinball_decryptor.core.checksums.read_checksums",
                        lambda d: {"video/x.mp4": "0" * 32})
    monkeypatch.setattr(engine, "_changed_videos",
                        lambda a, b: {"video/x.mp4": str(assets / "video" / "x.mp4")})
    monkeypatch.setattr(engine, "_is_spike3", lambda f: False)
    engine._LEAVE_OUT.kinds = frozenset(kinds)
    try:
        engine._compute_patches_inner(io.BytesIO(bytes(1) * 4096), [], str(assets),
                                      lambda m, level="info": logged.append(m), None,
                                      lambda: False, boot_screen=False)
    finally:
        engine._LEAVE_OUT.kinds = frozenset()


def test_a_left_out_kind_never_reaches_the_build(monkeypatch, tmp_path):
    logged = []
    with pytest.raises(engine.NothingToWrite):
        _scan_only(monkeypatch, tmp_path, {"videos", "sounds"}, logged)
    assert ("Left out of this run (Emulate tab): replaced sounds and replaced videos. "
            "A card you build still carries them.") in logged


def test_without_leaving_it_out_the_video_is_built(monkeypatch, tmp_path):
    logged = []
    with pytest.raises(Exception) as got:          # the video file is not there to build
        _scan_only(monkeypatch, tmp_path, (), logged)
    assert not isinstance(got.value, engine.NothingToWrite)
    assert not any("Left out of this run" in m for m in logged)


def test_write_overrides_hands_the_kinds_down_and_writes_them_down(card, tmp_path,  # noqa: F811
                                                                   monkeypatch):
    seen = []
    real = engine._compute_patches

    def watch(*a, **k):
        seen.append(set(getattr(engine._LEAVE_OUT, "kinds", ()) or ()))
        return real(*a, **k)

    monkeypatch.setattr(engine, "_compute_patches", watch)
    card.state["writes"] = [(_disk(card.reader, "/turtles_pro/image.bin", 6), b"MINE!")]
    out = tmp_path / "ovr"
    engine.write_overrides(str(card.img), str(tmp_path / "assets"), str(out),
                           leave_out=["music_modes", "sounds", "bogus"])
    assert seen == [{"music_modes", "sounds"}]
    # gone again once the set is built
    assert not getattr(engine._LEAVE_OUT, "kinds", ())
    assert engine.read_override_manifest(str(out))["left_out"] == ["music_modes", "sounds"]
    engine.write_overrides(str(card.img), str(tmp_path / "assets"), str(out))
    assert seen[-1] == set()
    assert engine.read_override_manifest(str(out))["left_out"] == []


# --------------------------------------------------------------------------
# 3. a set built with other kinds left out is built again
# --------------------------------------------------------------------------

def test_a_set_with_other_kinds_left_out_is_not_reused(card, tmp_path):  # noqa: F811
    from pinball_decryptor.webui import emulate_core as rig
    card.state["writes"] = [(_disk(card.reader, "/turtles_pro/image.bin", 6), b"MINE!")]
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    out = tmp_path / "ovr"
    engine.write_overrides(str(card.img), str(assets), str(out), leave_out=["videos"])
    engine.stamp_override_manifest(str(out),
                                   assets_fingerprint=rig.assets_fingerprint(str(assets)))
    man = engine.read_override_manifest(str(out))
    fp = rig.assets_fingerprint(str(assets))
    assert rig.overrides_reason(man, str(card.img), str(assets), fp,
                                left_out=("videos",)) == ""
    assert "leaves out" in rig.overrides_reason(man, str(card.img), str(assets), fp)
    assert "leaves out" in rig.overrides_reason(man, str(card.img), str(assets), fp,
                                                left_out=("videos", "sounds"))


def test_a_set_from_before_the_ticks_is_one_with_nothing_left_out(card, tmp_path):  # noqa: F811
    from pinball_decryptor.webui import emulate_core as rig
    card.state["writes"] = [(_disk(card.reader, "/turtles_pro/image.bin", 6), b"MINE!")]
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    out = tmp_path / "ovr"
    engine.write_overrides(str(card.img), str(assets), str(out))
    fp = rig.assets_fingerprint(str(assets))
    engine.stamp_override_manifest(str(out), assets_fingerprint=fp)
    man = dict(engine.read_override_manifest(str(out)))
    man.pop("left_out")
    assert rig.overrides_reason(man, str(card.img), str(assets), fp) == ""


# --------------------------------------------------------------------------
# 4. the Replace tabs' picks of a left-out kind wait
# --------------------------------------------------------------------------

def _app(calls):
    from pinball_decryptor.app import App
    me = types.SimpleNamespace()
    me._video_staging = lambda a: calls.append("count videos") or {"x": 1}
    me._image_staging = lambda a: calls.append("count pictures") or {"y": 1}
    me._stage_pending_audio = lambda a: calls.append("sounds") or (1, 1, [])
    me._stage_pending_video = lambda a, **k: calls.append("videos") or (2, 2, [])
    me._stage_pending_image = lambda a, **k: calls.append("pictures") or (3, 3, [])
    me._staging_work = lambda a, v, i: calls.append(("work", bool(v), bool(i))) or None
    return lambda **kw: App.stage_pending_replacements(me, "proj", **kw)


def test_staging_converts_everything_by_default():
    calls = []
    assert _app(calls)() == (6, 6, [])
    assert calls == ["count videos", "count pictures", "sounds", "videos", "pictures"]


def test_staging_leaves_the_left_out_kinds_assigned():
    calls = []
    got = _app(calls)(confirm_cb=lambda w: True, leave_out=("videos", "sounds"))
    assert got == (3, 3, [])
    # the videos are not even counted for the "this will take N minutes" question
    assert calls == ["count pictures", ("work", False, True), "pictures"]
    calls = []
    assert _app(calls)(leave_out=("pictures",)) == (3, 3, [])
    assert calls == ["count videos", "sounds", "videos"]


# --------------------------------------------------------------------------
# 5. the Emulate tab
# --------------------------------------------------------------------------

class _Var:
    def __init__(self):
        self.v = ""

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def _tab_with_ticks(monkeypatch):
    tab, logged, painted, asked = _tab(monkeypatch, None)
    tab.emulate_leave_out_var = _Var()
    return tab, logged, painted, asked


def test_the_ticks_are_offered_and_remembered_for_the_session(monkeypatch, tmp_path):
    tab, _logged, _painted, _asked = _tab_with_ticks(monkeypatch)
    assert tab._leave_out() == ()
    offer = tab._leave_out_offer(str(tmp_path))
    assert [o["key"] for o in offer] == ["sounds", "videos", "pictures"]
    assert not any(o["on"] for o in offer)
    tab.set_leave_out("videos", True)
    tab.set_leave_out("sounds", True)
    tab.set_leave_out("bogus", True)
    assert tab._leave_out() == ("sounds", "videos")
    assert tab.emulate_leave_out_var.get() == "sounds,videos"
    tab.set_leave_out("sounds", False)
    assert [o["key"] for o in tab._leave_out_offer(str(tmp_path)) if o["on"]] == ["videos"]


def test_a_left_out_kind_stays_offered_so_it_can_be_put_back(monkeypatch, tmp_path):
    tab, _logged, _painted, _asked = _tab_with_ticks(monkeypatch)
    tab.set_leave_out("random_clips", True)
    offer = tab._leave_out_offer(str(tmp_path))
    assert [(o["key"], o["on"]) for o in offer if o["key"] == "random_clips"] == \
        [("random_clips", True)]


def _start(monkeypatch, tmp_path, left):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import emulate_rig as rig
    tab, logged, _painted, _asked = _tab_with_ticks(monkeypatch)
    staged, built, reasons = [], [], []

    def stage(assets, **kw):
        staged.append(kw.get("leave_out", ()))
        return (0, 0, [])

    tab.window.cb = {"on_stage_pending": stage}
    assets = tmp_path / "proj"
    assets.mkdir(exist_ok=True)
    monkeypatch.setattr("pinball_decryptor.core.checksums.read_checksums", lambda d: {"x": 1})
    monkeypatch.setattr(rig, "override_base_card", lambda c, a, f: (c, ""))
    monkeypatch.setattr(rig, "overrides_dir", lambda: str(tmp_path / "set"))
    monkeypatch.setattr(rig, "assets_fingerprint", lambda a: "fp")
    monkeypatch.setattr(rig, "overrides_reason",
                        lambda *a, **k: reasons.append(k.get("left_out")) or "edits changed")
    monkeypatch.setattr(E, "read_override_manifest", lambda out: None)
    monkeypatch.setattr(E, "stamp_override_manifest", lambda *a, **k: None)
    monkeypatch.setattr(E, "override_set_kept", lambda out, c: True)
    monkeypatch.setattr(tab, "_scene_edits_on", lambda: True, raising=False)
    monkeypatch.setattr(tab, "_live_ready", lambda a, o, env: env, raising=False)
    monkeypatch.setattr(tab, "_with_override_modes", lambda o, env: env, raising=False)
    monkeypatch.setattr(tab, "_paint_run_btn", lambda: None, raising=False)

    def write_overrides(card, assets_dir, out, **kw):
        built.append(kw.get("leave_out", "not named"))
        return (1, 0, 0, 0), None, None, [("/godzilla_le/image.bin", 10)]

    monkeypatch.setattr(E, "write_overrides", write_overrides)
    for k in left:
        tab.set_leave_out(k, True)
    env = tab._prepare_overrides_inner("card.raw", str(assets))
    assert env and env[0].startswith("PAD_OVERRIDE_DIR=")
    return staged, built, reasons


def test_a_start_hands_the_kinds_to_the_staging_and_the_build(monkeypatch, tmp_path):
    staged, built, reasons = _start(monkeypatch, tmp_path, ["music_modes", "videos"])
    assert staged == [("music_modes", "videos")]
    assert built == [("music_modes", "videos")]
    assert reasons == [("music_modes", "videos")]


def test_a_start_with_nothing_left_out_calls_them_as_before(monkeypatch, tmp_path):
    staged, built, reasons = _start(monkeypatch, tmp_path, [])
    # not named at all: the stand-ins for both keep their older signatures
    assert staged == [()] and built == ["not named"] and reasons == [()]
