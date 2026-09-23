"""The emulator's prepare pipeline (feature/emulate-prepare), the engine's share: an
own-sound build restores nothing of the master directory without booting the emulator,
the grown bank's consumed map is kept for the next build, a grown file the set already
holds byte-for-byte is left alone and out of the delta, a Cancel is answered inside the
grow stage, and Try it closes the own-sound gate by parameter rather than by environment.

Built on the synthetic mode card of test_stern_mode_write_engine (every emulator seam
stubbed), with the seams this file is about put back to the real code.
"""
import io
import os

import pytest

pytestmark = pytest.mark.usefixtures("preview_modes_on")

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine                           # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import emulator as EM            # noqa: E402
from tests.test_stern_audio_grow import IMG_PATH, _capture, _said            # noqa: E402
from tests.test_stern_mode_write_engine import _mode_card                    # noqa: E402

REAL_RESTORE = engine._restore_masterdir_consumed


def _no_emulator(monkeypatch):
    """Spike2Emu raises: the test fails the moment anything boots the firmware."""
    def boom(*a, **k):
        raise AssertionError("the emulator was booted")
    monkeypatch.setattr(EM, "Spike2Emu", boom)


def _compute(project, log, cancel=lambda: False, **kw):
    return engine._compute_patches(io.BytesIO(b""), [], str(project), log=log, progress=None,
                                   cancel=cancel, dest_is_device=False, **kw)


# ---- (a) nothing to restore, no boot -----------------------------------------------------
def test_a_restore_with_only_appended_bodies_never_boots_the_emulator(monkeypatch, tmp_path):
    _no_emulator(monkeypatch)
    monkeypatch.setattr(engine, "_load_consumed", lambda gr, img: None)
    gr, img = tmp_path / "game_real", tmp_path / "image.bin"
    gr.write_bytes(b"\x7fELF")
    img.write_bytes(b"\x00" * 0x1000)
    msgs, log = _capture()
    patches = {0x40000: b"\xaa" * 64, 0x50000: b"\xbb" * 64}
    got = REAL_RESTORE(str(gr), str(img), dict(patches), log, None, lambda: False,
                       skip_offsets={0x40000, 0x50000})
    assert got == patches
    assert _said(msgs, "nothing of the master directory to restore")
    # and the cold-derive warning (why a Write is about to take minutes) was not said
    assert not any("decrypt" in m for _l, m in msgs)


def test_an_own_sound_build_restores_nothing_and_boots_nothing(monkeypatch, tmp_path):
    """The synthetic own-sound build: its one patch is the appended end sound, so the
    restore stage has nothing to restore and the emulator is not constructed for it."""
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    monkeypatch.setattr(engine, "_restore_masterdir_consumed", REAL_RESTORE)
    monkeypatch.setattr(engine, "_load_consumed", lambda gr, img: None)
    _no_emulator(monkeypatch)
    msgs, log = _capture()
    writes, _counts, plan, _m, _v = _compute(project, log)
    assert writes is not None and encoded and staged["path"]
    assert _said(msgs, "nothing of the master directory to restore")
    engine._rmtree_grow_plan(plan)


# ---- (b) the consumed map is kept under the staged bank ---------------------------------
def test_the_grow_stage_keeps_the_consumed_map_under_the_staged_fingerprint(monkeypatch,
                                                                            tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    derive = engine._derive_grown            # the fixture's stub, which discards the map
    reads = {0x40010, 0x40020, 0x40030}

    def derive_with_map(gr, st, params_stock, log, progress=None):
        rows, _none = derive(gr, st, params_stock, log, progress)
        return rows, set(reads)
    monkeypatch.setattr(engine, "_derive_grown", derive_with_map)
    prints = {}
    real_fp = engine._fingerprint

    def fingerprint(gr, img):
        fp = real_fp(gr, img)
        prints[fp] = (gr, img)
        return fp
    monkeypatch.setattr(engine, "_fingerprint", fingerprint)
    saved = []
    monkeypatch.setattr(engine, "_save_consumed", lambda fp, rd: saved.append((fp, set(rd))))
    _msgs, log = _capture()
    _w, _c, plan, _m, _v = _compute(project, log)
    assert saved, "the grow stage discarded the consumed map"
    for fp, rd in saved:
        assert rd == reads
        gr, img = prints[fp]
        assert img == staged["path"], "keyed on the STAGED bank, not the stock one"
        assert os.path.basename(gr) == "game_real"
    engine._rmtree_grow_plan(plan)


def test_a_map_that_cannot_be_kept_costs_the_build_nothing(monkeypatch, tmp_path):
    def boom(fp, rd):
        raise OSError("disk full")
    monkeypatch.setattr(engine, "_save_consumed", boom)
    gr, img = tmp_path / "g", tmp_path / "i"
    gr.write_bytes(b"g")
    img.write_bytes(b"i" * 64)
    msgs, log = _capture()
    engine._save_grown_consumed(str(gr), str(img), {1, 2}, log)
    assert _said(msgs, "could not be kept for the next build")
    msgs.clear()
    engine._save_grown_consumed(str(gr), str(img), None, log)      # no hook: nothing to file
    engine._save_grown_consumed(str(gr), str(img), set(), log)
    assert not msgs


# ---- (c) a byte-identical grown file stays out of the delta -----------------------------
def _delta_lines(out):
    with open(os.path.join(str(out), engine.OVERRIDE_DELTA), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip() and not ln.startswith("#")]


def test_a_byte_identical_grown_file_is_left_as_it_was_and_out_of_the_delta(monkeypatch,
                                                                            tmp_path):
    card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    with open(str(original), "wb") as f:
        for k, at in card.DISK.items():
            f.seek(at)
            f.write(card.data[k])
    out = tmp_path / "overrides"
    msgs, log = _capture()
    engine.write_overrides(str(original), str(project), str(out), log=log)
    first = _delta_lines(out)
    assert "whole " + IMG_PATH.lstrip("/") in first
    bank = os.path.join(str(out), *IMG_PATH.strip("/").split("/"))
    before = os.stat(bank)
    parent = engine.read_override_manifest(str(out))["generation"]

    msgs.clear()
    _counts, _am, _vp, written = engine.write_overrides(str(original), str(project), str(out),
                                                        log=log)
    lines = _delta_lines(out)
    assert "parent %s" % parent in lines
    # the grown bank came out the same bytes: not rewritten, not in the delta ...
    assert "whole " + IMG_PATH.lstrip("/") not in lines
    assert not any(ln.endswith(" " + IMG_PATH.lstrip("/")) for ln in lines)
    assert os.stat(bank).st_mtime_ns == before.st_mtime_ns
    assert any(IMG_PATH in m and "left as it was" in m for _l, m in msgs)
    # ... but still a file of the set: in the manifest and in what was written
    listed = engine.read_override_manifest(str(out))
    assert IMG_PATH in [r["path"] for r in listed["files"]]
    assert IMG_PATH in [p for p, _n in written]
    # the size line at the end still adds up (it used to pair written with delta by position)
    assert any("Updated the emulator override set" in m for _l, m in msgs)


def test_the_same_bytes_test_is_by_size_then_by_content(tmp_path):
    a, b, c, d = (tmp_path / n for n in "abcd")
    a.write_bytes(b"x" * (3 << 20) + b"end")
    b.write_bytes(b"x" * (3 << 20) + b"end")
    c.write_bytes(b"x" * (3 << 20) + b"END")
    d.write_bytes(b"x" * (3 << 20))
    assert engine._same_file_bytes(str(a), str(b))
    assert not engine._same_file_bytes(str(a), str(c))
    assert not engine._same_file_bytes(str(a), str(d))
    assert not engine._same_file_bytes(str(a), str(tmp_path / "missing"))


# ---- (e) the own-sound gate as a parameter ------------------------------------------------
def test_sound_ok_false_leaves_the_own_sounds_out_with_the_reason(monkeypatch, tmp_path):
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _w, _c, plan, _m, _v = _compute(project, log, sound_ok=False)
    assert "path" not in staged and not encoded
    assert plan["modes"]["names"] and plan["modes"]["end_sound"] is None
    assert _said(msgs, "left out of this run")
    assert not _said(msgs, "PAD_STERN_MODE_SOUND=0")
    engine._rmtree_grow_plan(plan)


def test_sound_ok_is_threaded_through_write_overrides(monkeypatch, tmp_path):
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    original.write_bytes(b"x" * 4096)
    msgs, log = _capture()
    _c, _am, _vp, written = engine.write_overrides(str(original), str(project),
                                                   str(tmp_path / "set"), log=log,
                                                   sound_ok=False)
    assert "path" not in staged and not encoded
    assert IMG_PATH not in [p for p, _n in written]
    assert _said(msgs, "left out of this run")
    # None (the default) still reads the environment gate
    monkeypatch.setenv("PAD_STERN_MODE_SOUND", "0")
    msgs.clear()
    engine.write_overrides(str(original), str(project), str(tmp_path / "set2"), log=log)
    assert _said(msgs, "PAD_STERN_MODE_SOUND=0")


# ---- (d) Cancel inside the grow stage -----------------------------------------------------
def test_a_cancel_during_the_grow_stage_returns_the_cancelled_shape(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    state = {"cancelled": False}
    derive = engine._derive_grown

    def derive_then_cancel(*a, **k):
        state["cancelled"] = True           # Cancel pressed while the derive ran
        return derive(*a, **k)
    monkeypatch.setattr(engine, "_derive_grown", derive_then_cancel)
    _msgs, log = _capture()
    got = _compute(project, log, cancel=lambda: state["cancelled"])
    assert got == (None, None, None, None)
    assert staged["path"], "the bank was staged before the Cancel"
    assert "path" not in staged["repointed"], "the re-point was not started after it"


def test_a_cancel_before_the_restore_returns_the_cancelled_shape(monkeypatch, tmp_path):
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    state = {"cancelled": False}

    def encode_then_cancel(gr, img, prm, ed, np, lg, **k):
        state["cancelled"] = True
        return {0x40000: b"\xaa" * 64}, prm
    monkeypatch.setattr(engine, "_chain_encode_appended", encode_then_cancel)
    monkeypatch.setattr(engine, "_repoint_descriptors", lambda *a, **k: {})

    def not_here(*a, **k):
        raise AssertionError("the restore ran after a Cancel")
    monkeypatch.setattr(engine, "_restore_masterdir_consumed", not_here)
    _msgs, log = _capture()
    assert _compute(project, log, cancel=lambda: state["cancelled"]) == (None, None, None, None)
