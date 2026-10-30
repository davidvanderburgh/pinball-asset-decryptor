"""PAD-863 (DragonRR): "assuming that there will always be a longer delay on the FIRST
time ... WARN the user that this is the case and tell him that if he continues to use the
same build, future changes will be faster IF this is actually true!"

  1. ``engine.override_set_kept``: is there a set the next build patches, or is it laid
     down whole (the long wait)?
  2. the Emulate tab says so, in the log and on the State line, only for a first set.
  3. a staged picture is not converted again because the app was updated: the picture
     cache keys on the converter, not the app's version (his one big picture took 20 s
     after each release).
"""

import os

from PIL import Image

from tests.test_emulate_overrides import card  # noqa: F401  (fixture)
from tests.test_emulate_overrides import _disk
from tests.test_pad489_emulate_conversion_progress import _tab

from pinball_decryptor.plugins.stern import engine


# --------------------------------------------------------------------------
# 1. a set to patch, or a first one
# --------------------------------------------------------------------------

def test_a_set_is_kept_only_once_built_from_the_same_card(card, tmp_path):  # noqa: F811
    out = tmp_path / "ovr"
    assert engine.override_set_kept(str(out), str(card.img)) is False
    card.state["writes"] = [(_disk(card.reader, "/turtles_pro/image.bin", 6), b"MINE!")]
    engine.write_overrides(str(card.img), str(tmp_path / "assets"), str(out))
    assert engine.override_set_kept(str(out), str(card.img)) is True
    # another card (here: the same file, changed) means a first set again
    with open(card.img, "ab") as f:
        f.write(b"\0" * 512)
    assert engine.override_set_kept(str(out), str(card.img)) is False


def test_a_set_whose_file_was_touched_is_not_kept(card, tmp_path):  # noqa: F811
    out = tmp_path / "ovr"
    card.state["writes"] = [(_disk(card.reader, "/turtles_pro/image.bin", 6), b"MINE!")]
    engine.write_overrides(str(card.img), str(tmp_path / "assets"), str(out))
    victim = out / "turtles_pro" / "image.bin"
    assert victim.is_file()
    victim.write_bytes(b"x")
    assert engine.override_set_kept(str(out), str(card.img)) is False


# --------------------------------------------------------------------------
# 2. the Emulate tab says it before a first set, and only then
# --------------------------------------------------------------------------

def _prepare(monkeypatch, tmp_path, kept):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.webui import emulate_rig as rig
    tab, logged, painted, asked = _tab(monkeypatch, None)
    tab.window.cb = {}
    assets = tmp_path / "proj"
    assets.mkdir(exist_ok=True)
    monkeypatch.setattr("pinball_decryptor.core.checksums.read_checksums", lambda d: {"x": 1})
    monkeypatch.setattr(rig, "override_base_card", lambda c, a, f: (c, ""))
    monkeypatch.setattr(rig, "overrides_dir", lambda: str(tmp_path / "set"))
    monkeypatch.setattr(rig, "assets_fingerprint", lambda a: "fp")
    monkeypatch.setattr(rig, "overrides_reason", lambda *a, **k: "edits changed")
    monkeypatch.setattr(E, "read_override_manifest", lambda out: None)
    monkeypatch.setattr(E, "stamp_override_manifest", lambda *a, **k: None)
    asked_kept = []
    monkeypatch.setattr(E, "override_set_kept",
                        lambda out, c: (asked_kept.append((out, c)), kept)[1])
    monkeypatch.setattr(tab, "_scene_edits_on", lambda: True, raising=False)
    monkeypatch.setattr(tab, "_live_ready", lambda a, o, env: env, raising=False)
    monkeypatch.setattr(tab, "_with_override_modes", lambda o, env: env, raising=False)
    monkeypatch.setattr(tab, "_paint_run_btn", lambda: None, raising=False)
    shown = []

    def write_overrides(card, assets_dir, out, progress=None, **kw):
        shown.append(tab._preparing)
        progress(40, 100, "Re-encoding audio...")
        shown.append(tab._preparing)
        return (1, 0, 0, 0), None, None, [("/godzilla_le/image.bin", 10)]

    monkeypatch.setattr(E, "write_overrides", write_overrides)
    env = tab._prepare_overrides_inner("card.raw", str(assets))
    assert env and env[0].startswith("PAD_OVERRIDE_DIR=")
    assert asked_kept == [(str(tmp_path / "set"), "card.raw")]
    return logged, shown


def test_a_first_set_is_said_to_be_the_long_wait(monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_rig as rig
    logged, shown = _prepare(monkeypatch, tmp_path, kept=False)
    assert rig.FIRST_SET_NOTE in logged
    # after the reason, before the build's own lines
    assert logged.index(rig.FIRST_SET_NOTE) == logged.index(
        "[emulate] preparing your edits (edits changed)") + 1
    assert "longest" in rig.FIRST_SET_NOTE and "quicker" in rig.FIRST_SET_NOTE
    assert shown == ["Preparing your edits (first time: the longest)…",
                     "Preparing your edits (first time: the longest): re-encoding audio"]


def test_a_set_to_patch_says_nothing_more(monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_rig as rig
    logged, shown = _prepare(monkeypatch, tmp_path, kept=True)
    assert rig.FIRST_SET_NOTE not in logged
    assert shown == ["Preparing your edits…", "Preparing your edits: re-encoding audio"]


def test_the_note_keeps_to_the_reply_rules():
    from pinball_decryptor.webui import emulate_rig as rig
    for text in (rig.FIRST_SET_NOTE, rig.FIRST_SET_WORDS):
        assert "—" not in text and "–" not in text


# --------------------------------------------------------------------------
# 3. an app update does not convert the pictures again
# --------------------------------------------------------------------------

def test_the_picture_recipe_outlives_an_app_update(monkeypatch, tmp_path):
    import pinball_decryptor
    from pinball_decryptor.core import image_slots
    rep = tmp_path / "rep.png"
    Image.new("RGB", (4, 4)).save(rep)
    before = image_slots.PictureCache.recipe(str(rep), None, False, None)
    monkeypatch.setattr(pinball_decryptor, "__version__", "9.9.9")
    monkeypatch.setattr(image_slots, "_CONVERTER_KEYS", {})
    assert image_slots.PictureCache.recipe(str(rep), None, False, None) == before
    # a converter that converts differently does make it again
    monkeypatch.setattr(image_slots, "CONVERSION_REV", image_slots.CONVERSION_REV + 1)
    monkeypatch.setattr(image_slots, "_CONVERTER_KEYS", {})
    assert image_slots.PictureCache.recipe(str(rep), None, False, None) != before


def test_the_converter_key_reads_the_converter_source(monkeypatch):
    from pinball_decryptor.core import image_slots
    monkeypatch.setattr(image_slots, "_CONVERTER_KEYS", {})
    plain = image_slots._converter_key(False)
    coloured = image_slots._converter_key(True)
    assert not plain.startswith("app-") and plain != coloured
    # an app whose source can't be read falls back to its version
    from pinball_decryptor.core import image
    monkeypatch.setattr(image, "__file__", os.path.join("nowhere", "image.pyc"))
    monkeypatch.setattr(image_slots, "_CONVERTER_KEYS", {})
    import pinball_decryptor
    assert image_slots._converter_key(False) == "app-" + pinball_decryptor.__version__


def test_a_start_after_an_app_update_converts_no_picture_again(tmp_path, monkeypatch):
    """The real staging, his way: pictures converted on one version, the app updated,
    the next Start leaves them as they are."""
    import pinball_decryptor
    from pinball_decryptor.core import image_slots
    from tests.test_pad505_busy_conversion import _count_stagings, _pictures
    assets, slots = _pictures(tmp_path)
    seen = _count_stagings(monkeypatch)
    assert image_slots.stage_replacements(slots, {}, assets_dir=assets) == (3, [])
    assert len(seen) == 3
    monkeypatch.setattr(pinball_decryptor, "__version__", "9.9.9")
    monkeypatch.setattr(image_slots, "_CONVERTER_KEYS", {})
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 0
    assert image_slots.stage_replacements(slots, {}, assets_dir=assets) == (3, [])
    assert len(seen) == 3
