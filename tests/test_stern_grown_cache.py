"""The grown-bank cache (feature/emulate-prepare): a build that grows the sound bank for
the same sounds as the last one replays that build's derived table, staged places and
verified bodies, skipping the derive, the chain encode and the master-directory restore,
while the play tables are still re-pointed and the firmware integrity check still runs.

Built on the synthetic mode card of test_stern_mode_write_engine (every emulator seam
stubbed); the seams this file is about are made to raise so a hit is proven by their
silence.
"""
import io
import os

import pytest

pytestmark = pytest.mark.usefixtures("preview_modes_on")

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine                           # noqa: E402
from tests.test_stern_audio_grow import _capture, _said, _wav                # noqa: E402
from tests.test_stern_mode_write_engine import _mode_card                    # noqa: E402

CANCELLED = (None, None, None, None, None)     # the five write_image unpacks


def _compute(project, log, cancel=lambda: False, **kw):
    return engine._compute_patches(io.BytesIO(b""), [], str(project), log=log, progress=None,
                                   cancel=cancel, dest_is_device=False, **kw)


def _cache_file(project):
    return os.path.join(str(project), ".write_cache", "audio_grown.bin")


def _end_wav(project):
    """The KAIJU RUSH end sound the fixture gave the project."""
    for root, _dirs, files in os.walk(str(project)):
        if "end.wav" in files:
            return os.path.join(root, "end.wav")
    raise AssertionError("the fixture's end.wav is missing")


def _build(project, log, staged, cancel=lambda: False, **kw):
    """One build; returns ``(result, staged bank bytes)`` and cleans the grow plan up."""
    got = _compute(project, log, cancel=cancel, **kw)
    bank = None
    if staged.get("path") and os.path.exists(staged["path"]):
        with open(staged["path"], "rb") as f:
            bank = f.read()
    if got[2] is not None:
        engine._rmtree_grow_plan(got[2])
    return got, bank


def _cold_seams_raise(monkeypatch):
    """The three stages a hit skips fail the test the moment they run."""
    def boom(name):
        def _f(*a, **k):
            raise AssertionError("%s ran on a cache hit" % name)
        return _f
    monkeypatch.setattr(engine, "_derive_grown", boom("_derive_grown"))
    monkeypatch.setattr(engine, "_chain_encode_appended", boom("_chain_encode_appended"))
    monkeypatch.setattr(engine, "_restore_masterdir_consumed",
                        boom("_restore_masterdir_consumed"))


def _count(monkeypatch, name):
    """Wrap engine.<name> so calls are counted; returns the counter."""
    real = getattr(engine, name)
    calls = []

    def wrapped(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(engine, name, wrapped)
    return calls


# ---- the first build populates, the second replays ---------------------------------------
def test_a_first_build_populates_the_cache(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    (writes, _c, _plan, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None
    assert os.path.exists(_cache_file(project))
    assert not _said(msgs, "Grown bank: these")
    with open(_cache_file(project), "rb") as f:
        assert f.read(len(engine._GrownBankCache._MAGIC)) == engine._GrownBankCache._MAGIC


def test_a_second_identical_build_replays_and_still_checks_integrity(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    (writes1, _c, _p, _m, _v), bank1 = _build(project, log, staged)
    repointed = staged["repointed"]
    cold_params = repointed["params"]

    _cold_seams_raise(monkeypatch)
    checked = []
    monkeypatch.setattr(engine, "_assert_param_integrity",
                        lambda gr, img, patches, params, np, lg, work, prog=None:
                        checked.append((dict(patches), params)))
    msgs.clear()
    (writes2, _c, _p, _m, _v), bank2 = _build(project, log, staged)

    assert writes2 == writes1, "a hit must produce the same bytes as the cold build"
    assert bank2 == bank1, "the grown bank must come out byte-identical"
    assert checked, "the integrity check is the one stage a hit never skips"
    patches, params = checked[0]
    assert patches == {0x40000: b"\xaa" * 64}
    assert [p["idx"] for p in params] == [p["idx"] for p in cold_params]
    assert [p.get("grown") for p in params] == [p.get("grown") for p in cold_params]
    # the play tables were re-pointed from the kept table, on the new staged bank
    assert repointed["path"] == staged["path"]
    assert [p["idx"] for p in repointed["params"]] == [p["idx"] for p in params]
    said = _said(msgs, "Grown bank: these 1 longer sound(s)")
    assert said and "integrity check still runs" in said[0]
    assert "PAD_STERN_AUDIO_CACHE=0" in said[0]


# ---- what misses ------------------------------------------------------------------------
def test_a_changed_wav_byte_misses(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    wav = _end_wav(project)
    with open(wav, "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x01")                     # one sample, the same length
    derives = _count(monkeypatch, "_derive_grown")
    msgs.clear()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None and derives
    assert not _said(msgs, "Grown bank: these")


def test_a_changed_gain_misses(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    monkeypatch.setattr(engine, "_slot_gain_maps", lambda a: ({0: -3.0}, {}))
    derives = _count(monkeypatch, "_derive_grown")
    msgs.clear()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None and derives
    assert not _said(msgs, "Grown bank: these")


def test_the_cache_switched_off_misses_and_writes_nothing(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    monkeypatch.setenv("PAD_STERN_AUDIO_CACHE", "0")
    derives = _count(monkeypatch, "_derive_grown")
    before = os.stat(_cache_file(project)).st_mtime_ns
    msgs.clear()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None and derives
    assert not _said(msgs, "Grown bank: these")
    assert os.stat(_cache_file(project)).st_mtime_ns == before


def test_a_damaged_entry_falls_back_to_the_cold_path_and_says_so(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    path = _cache_file(project)
    with open(path, "rb") as f:
        magic = f.read(len(engine._GrownBankCache._MAGIC))
        key_line = f.readline()
    with open(path, "wb") as f:
        f.write(magic + key_line + b"\x80\x04not a pickle at all")
    derives = _count(monkeypatch, "_derive_grown")
    msgs.clear()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None and derives
    assert _said(msgs, "could not be read")
    assert not _said(msgs, "Grown bank: these")
    # and the cold build wrote a whole entry back
    with open(path, "rb") as f:
        f.read(len(magic))
        f.readline()
        import pickle
        assert set(pickle.load(f)) == {"params", "places", "patches", "reads"}


def test_a_kept_table_for_another_bank_is_refused_loudly(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    stage = engine._stage_grown_image

    def stage_elsewhere(gr, ip, grow_work, byidx, grows, log):
        out, places = stage(gr, ip, grow_work, byidx, grows, log)
        return out, [pl._replace(body_off=pl.body_off + 0x100) for pl in places]
    monkeypatch.setattr(engine, "_stage_grown_image", stage_elsewhere)
    derives = _count(monkeypatch, "_derive_grown")
    msgs.clear()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged)
    assert writes is not None and derives
    assert _said(msgs, "not this staged bank's")
    assert not _said(msgs, "Grown bank: these")


# ---- Cancel on a hit, and the fast run --------------------------------------------------
def test_a_cancelled_hit_returns_the_cancelled_shape(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _build(project, log, staged)
    _cold_seams_raise(monkeypatch)
    state = {"cancelled": False}
    repoint = engine._repoint_descriptors

    def repoint_then_cancel(*a, **k):
        state["cancelled"] = True           # Cancel pressed while the re-point ran
        return repoint(*a, **k)
    monkeypatch.setattr(engine, "_repoint_descriptors", repoint_then_cancel)

    def not_here(*a, **k):
        raise AssertionError("the integrity check ran after a Cancel")
    monkeypatch.setattr(engine, "_assert_param_integrity", not_here)
    got, _bank = _build(project, log, staged, cancel=lambda: state["cancelled"])
    assert got == CANCELLED
    assert _said(msgs, "Grown bank: these")


def test_the_fast_run_never_touches_the_cache(monkeypatch, tmp_path):
    _card, staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise AssertionError("the grown-bank cache was opened by a fast run")
    monkeypatch.setattr(engine, "_GrownBankCache", boom)
    msgs, log = _capture()
    (writes, _c, _p, _m, _v), _bank = _build(project, log, staged, sound_ok=False)
    assert writes is not None
    assert not os.path.exists(_cache_file(project))


# ---- the key and the mismatch test, on their own ----------------------------------------
def test_the_sound_tuple_names_every_input_that_changes_the_bank(tmp_path):
    a = _wav(tmp_path / "a.wav", 0.5)
    b = _wav(tmp_path / "b.wav", 0.5)
    own = [{"idx": 7, "request": 1295, "music": False}, {"idx": 9, "sid": 257, "music": True}]
    edits = {7: a, 9: b, 3: "audio/idx0003.wav"}
    (tmp_path / "audio").mkdir()
    _wav(tmp_path / "audio" / "idx0003.wav", 0.2)
    grows = {7: (1000, 22050), 9: (1000, 26460)}
    base = engine._grown_cache_sounds(str(tmp_path), edits, grows, {7: -2.0}, {9}, own)
    assert [e[0] for e in base] == [3, 7, 9]                       # sorted by idx
    assert base[1][1] == ("request", 1295) and base[2][1] == ("sid", 257)
    assert base[0][1] is None and base[0][5] is None               # a fit: no target length
    assert base[1][3] == -2.0 and base[2][4] is True and base[2][5] == 26460
    assert engine._grown_cache_sounds(str(tmp_path), edits, grows, {7: -2.0}, {9}, own) == base
    # each input changes the tuple
    with open(a, "r+b") as f:
        f.seek(-1, 2)
        f.write(b"\x01")
    assert engine._grown_cache_sounds(str(tmp_path), edits, grows, {7: -2.0}, {9}, own) != base
    assert engine._grown_cache_sounds(str(tmp_path), edits, grows, {7: -1.0}, {9}, own) != base
    assert engine._grown_cache_sounds(str(tmp_path), edits, grows, {7: -2.0}, set(), own) != base
    longer = dict(grows)
    longer[9] = (1000, 30000)
    assert engine._grown_cache_sounds(str(tmp_path), edits, longer, {7: -2.0}, {9}, own) != base


def test_the_key_covers_the_family_switch_and_the_revision(monkeypatch, tmp_path):
    gr, img = tmp_path / "game_real", tmp_path / "image.bin"
    gr.write_bytes(b"\x7fELF" + b"\x00" * 64)
    img.write_bytes(b"\x00" * 0x1000)
    cache = engine._GrownBankCache(str(tmp_path), str(gr), str(img), b"ident")
    sounds = ((0, ("request", 1295), "ab" * 32, 0.0, False, 132300),)
    k = cache.key_for(True, sounds)
    assert k == cache.key_for(True, sounds)
    assert k != cache.key_for(False, sounds)
    monkeypatch.setattr(engine, "_GROWN_CACHE_REV", engine._GROWN_CACHE_REV + 1)
    assert k != cache.key_for(True, sounds)


def test_load_tells_no_entry_from_a_damaged_one(tmp_path):
    gr, img = tmp_path / "game_real", tmp_path / "image.bin"
    gr.write_bytes(b"\x7fELF" + b"\x00" * 64)
    img.write_bytes(b"\x00" * 0x1000)
    cache = engine._GrownBankCache(str(tmp_path), str(gr), str(img), b"ident")
    assert cache.load("k") is None                                  # no file yet
    params = [{"idx": 0, "grown": True, "body_off": 0x40000, "length": 300}]
    places = [(0, 4, 0x40000, 300, 1000)]
    cache.store("k", params, places, {0x40000: b"\xaa"}, {1, 2})
    assert cache.load("other") is None                              # another key
    got = cache.load("k")
    assert got["params"] == params and got["places"] == places
    assert got["patches"] == {0x40000: b"\xaa"} and got["reads"] == {1, 2}
    with open(cache.path, "r+b") as f:
        f.seek(0, 2)
        f.truncate(f.tell() - 5)
    with pytest.raises(ValueError):
        cache.load("k")
    # an empty set is never kept
    cache.store("k2", params, places, {}, None)
    assert cache.load("k2") is None


def test_the_mismatch_test_ties_the_kept_table_to_the_staged_bank():
    kept = {"params": [{"idx": 0, "grown": False, "body_off": 0x1000, "length": 100},
                       {"idx": 1, "grown": True, "body_off": 0x40000, "length": 300}],
            "places": [(1, 4, 0x40000, 300, 1000)]}
    assert engine._grown_cache_mismatch(kept, [(1, 4, 0x40000, 300, 1000)]) == ""
    assert "layout" in engine._grown_cache_mismatch(kept, [(1, 4, 0x40100, 300, 1000)])
    assert "layout" in engine._grown_cache_mismatch(kept, [])
    off = dict(kept, params=[dict(kept["params"][1], body_off=0x40100)])
    assert "idx 1 sits at" in engine._grown_cache_mismatch(off, kept["places"])
    extra = dict(kept, places=[(1, 4, 0x40000, 300, 1000), (2, 5, 0x50000, 300, 1000)])
    assert "idx 2 is staged" in engine._grown_cache_mismatch(
        extra, [(1, 4, 0x40000, 300, 1000), (2, 5, 0x50000, 300, 1000)])


def test_the_preview_switch_off_keeps_the_cache_out(monkeypatch, tmp_path):
    """Review: a copy of the app without a preview code writes what main writes. The
    cache's replay is proven on the synthetic card only, so until a real-card Write has
    taken the hit path and booted it stays behind the switch: off, a plain build that
    grows the bank for a longer replacement (PAD_STERN_AUDIO_GROW=1, no modes) never even
    opens the cache, and a second one derives again."""
    from tests.test_stern_audio_grow import BLOCK, _edits, _grow_card, _params, _run
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    monkeypatch.setattr(engine, "_mode_family_on", lambda: False)
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True, shadows=4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params, grown_rows=grown)
    assets, _wavp = _edits(tmp_path, 2.0)

    def boom(*a, **k):
        raise AssertionError("the grown-bank cache was opened with the switch off")
    monkeypatch.setattr(engine, "_GrownBankCache", boom)
    derived = _count(monkeypatch, "_derive_grown")
    msgs, log = _capture()
    for _ in range(2):
        writes, _c, plan, _m, _v = _run(monkeypatch, assets, params, 0x40000, log)
        assert writes is not None and plan["jobs"]
        engine._rmtree_grow_plan(plan)
    assert len(derived) == 2, "with the switch off every build derives the bank again"
    assert not os.path.exists(os.path.join(str(assets), ".write_cache", "audio_grown.bin"))
    assert not _said(msgs, "Grown bank: these")
