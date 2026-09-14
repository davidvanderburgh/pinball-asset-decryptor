"""Updating the last Spike 2 build in place (feature/stern-build-update).

Same posture as ``test_emulate_overrides``: the fake ext4 reader
(``tests/_ext4_fake``) stands in for the card, the patch computation is
stubbed (it is the Write tab's own machinery, tested elsewhere), and what is
under test is the bookkeeping this feature adds — the build record beside
the output, the decision to update rather than rebuild, the plan, and the
bytes that land: the last build's edits put back to stock, this build's on
top, whole-file copies only for sources that changed, the stock file back
for one no longer replaced.  The ext4 driver's copy is stubbed too (it needs
WSL); what is checked is which files are handed to it.
"""

import hashlib
import json
import os
import shutil

import pytest

from tests._ext4_fake import FakeExt4Reader, materialize_files

from pinball_decryptor import __version__
from pinball_decryptor.core import ext4_grow
from pinball_decryptor.plugins.stern import engine

CARD_TREE = {
    "turtles_pro": {
        "image.bin": b"STOCK-SOUND-BANK-" + b"." * 64,
        "game": b"\x7fELF" + b"F" * 32,
        "assets": {"lcd": {"1.asset": b"STOCK-VIDEO-1-" + b"v" * 32,
                           "2.asset": b"STOCK-VIDEO-2-" + b"w" * 32}},
    },
    "spk": {"index": {"turtles_pro.sidx": b"FINF" + b"s" * 40}},
}
# The same files, laid out differently: an extra file ahead of image.bin
# shifts every later file's blocks — what a build that rewrote a file whole
# looks like to the next one.
MOVED_TREE = {
    "turtles_pro": {
        "aaa.bin": b"x" * 10,
        "image.bin": b"STOCK-SOUND-BANK-" + b"." * 64,
        "game": b"\x7fELF" + b"F" * 32,
        "assets": {"lcd": {"1.asset": b"STOCK-VIDEO-1-" + b"v" * 32,
                           "2.asset": b"STOCK-VIDEO-2-" + b"w" * 32}},
    },
    "spk": {"index": {"turtles_pro.sidx": b"FINF" + b"s" * 40}},
}
PART = (0, 1 << 30)
IMAGE = "/turtles_pro/image.bin"
V1 = "turtles_pro/assets/lcd/1.asset"
V2 = "turtles_pro/assets/lcd/2.asset"


class _Reader(FakeExt4Reader):
    base = 0

    def node(self, path):
        for p, _ino, n in self.iter_regular_files(min_size=1):
            if p == path:
                return n
        raise KeyError(path)


def _md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


@pytest.fixture()
def card(monkeypatch, tmp_path):
    """A stubbed card and project.  ``state`` is what the next Build's patch
    computation returns; ``state["copies"]`` collects what was handed to the
    ext4 driver; ``state["build_reader"]`` is how the BUILT file is read
    (the stock layout unless a test moves a file)."""
    reader = _Reader(CARD_TREE)
    stock = tmp_path / "turtles_pro-1_59_0.raw"
    stock.write_bytes(bytes(4096))
    materialize_files(str(stock), CARD_TREE)
    out = tmp_path / "build" / "turtles_pro-1_59_0-modified.raw"
    project = tmp_path / "project"
    project.mkdir()
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "one.mp4").write_bytes(b"CLIP-ONE-" + b"1" * 40)
    (clips / "two.mp4").write_bytes(b"CLIP-TWO-" + b"2" * 40)

    state = {"writes": [], "grow": None, "counts": (1, 0, 0, 0),
             "audio": None, "val": None, "copies": [], "fail_after": None,
             "build_reader": reader}

    def fake_compute(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None, label=None, dest_is_device=False,
                     boot_screen=True):
        return (list(state["writes"]), state["counts"], state["grow"],
                state["audio"], state["val"])

    def fake_readers(disk_f, parts):
        name = os.path.basename(getattr(disk_f, "name", ""))
        r = state["build_reader"] if name == out.name else reader
        return [(PART[0], r)]

    def fake_grow(image, part_offset, jobs, log=None, cancel=None,
                  timeout=1800):
        # Record what was asked for, with the SOURCE BYTES (a stock restore
        # copies from a scratch file that is gone once the build returns).
        got = [(rel, open(src, "rb").read()) for rel, src in jobs]
        state["copies"].append((os.path.basename(image), part_offset, got))
        if state["fail_after"] is not None and len(jobs) > state["fail_after"]:
            raise ext4_grow.Ext4GrowError("the driver said no",
                                          grown=state["fail_after"])
        return len(jobs)

    monkeypatch.setattr(engine, "_compute_patches", fake_compute)
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [PART])
    monkeypatch.setattr(engine, "_open_readers", fake_readers)
    monkeypatch.setattr(ext4_grow, "grow_files", fake_grow)
    return type("Card", (), {
        "reader": reader, "stock": stock, "out": out, "project": project,
        "clips": clips, "state": state})


def _disk(reader, path, off):
    return reader.disk_ranges(reader.node(path), off, 1)[0][0]


def _grow(*jobs):
    return {"offset": PART[0], "jobs": list(jobs), "n_video": len(jobs),
            "audio_job": None, "cleanup": None, "boot": None}


def _build(card, log=None, **kw):
    lines = []

    def _log(msg, lvl="info", *a, **k):
        lines.append((msg, lvl))
        if log:
            log(msg, lvl)
    counts = engine.write_image(str(card.stock), str(card.project),
                                str(card.out), log=_log, **kw)
    return counts, lines


def _record(card):
    return json.loads(open(engine.build_manifest_path(card.out)).read())


def _first_build(card):
    """Build #1: one sound patched in place, one video copied whole."""
    r = card.reader
    card.state["writes"] = [(_disk(r, IMAGE, 17), b"NEW-BODY")]
    card.state["grow"] = _grow((V1, str(card.clips / "one.mp4")))
    card.state["counts"] = (1, 1, 0, 0)
    return _build(card)


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

def test_the_first_build_leaves_a_record_of_what_it_put_on_the_card(card):
    counts, lines = _first_build(card)
    assert counts[0] == (1, 1, 0, 0)
    data = card.out.read_bytes()
    off = _disk(card.reader, IMAGE, 17)
    assert data[off:off + 8] == b"NEW-BODY"
    rec = _record(card)
    assert rec["version"] == engine.BUILD_MANIFEST_VERSION
    assert rec["app"] == __version__
    assert rec["building"] is False and rec["complete"] is True
    assert rec["stock"]["path"] == str(card.stock)
    assert rec["assets"] == str(card.project)
    assert rec["inplace"] == {"0:" + IMAGE: [[17, 8]]}
    assert rec["whole"] == {"0:/" + V1: {"digest": _md5(card.clips / "one.mp4"),
                                         "size": 49}}
    assert rec["output"]["size"] == card.out.stat().st_size
    assert engine.build_update_reason(rec, str(card.stock), str(card.out),
                                      str(card.project)) is None
    assert not any("Updating" in m for m, _l in lines)


def test_a_patch_no_file_covers_leaves_the_record_incomplete(card):
    card.state["writes"] = [(5, b"?")]          # ahead of every file
    _build(card)
    rec = _record(card)
    assert rec["complete"] is False and rec["inplace"] == {}
    assert "did not land every file" in engine.build_update_reason(
        rec, str(card.stock), str(card.out), str(card.project))


@pytest.mark.parametrize("twist, expect", [
    (lambda r: r.clear(), "no record"),
    (lambda r: r.update(building=True), "did not finish"),
    (lambda r: r.update(app="0.0.1"), "different version"),
    (lambda r: r.update(complete=False), "did not land"),
    (lambda r: r["stock"].update(mtime_ns=1), "different original"),
    (lambda r: r.update(assets="elsewhere"), "different project"),
    (lambda r: r["output"].update(size=1), "changed since it was built"),
])
def test_the_reason_names_what_disagrees(card, twist, expect):
    _first_build(card)
    rec = _record(card)
    twist(rec)
    why = engine.build_update_reason(rec, str(card.stock), str(card.out),
                                     str(card.project))
    assert why and expect in why


# --------------------------------------------------------------------------
# The update
# --------------------------------------------------------------------------

def test_a_second_build_updates_the_first_in_place(card, monkeypatch):
    _first_build(card)
    r = card.reader
    stock_bytes = card.stock.read_bytes()
    # Build #2: a DIFFERENT sound is patched (the first is taken back), the
    # same video is still assigned and a second one is new.
    card.state["writes"] = [(_disk(r, IMAGE, 40), b"OTHER")]
    card.state["grow"] = _grow((V1, str(card.clips / "one.mp4")),
                               (V2, str(card.clips / "two.mp4")))
    card.state["counts"] = (1, 2, 0, 0)
    card.state["copies"].clear()
    monkeypatch.setattr(shutil, "copyfile",
                        lambda *a, **k: pytest.fail("the card was copied"))
    counts, lines = _build(card)
    assert counts[0] == (1, 2, 0, 0)
    assert any(m.startswith("Updating the build already at") for m, _l in lines)
    data = card.out.read_bytes()
    o17, o40 = _disk(r, IMAGE, 17), _disk(r, IMAGE, 40)
    assert data[o17:o17 + 8] == stock_bytes[o17:o17 + 8]   # taken back
    assert data[o40:o40 + 5] == b"OTHER"                    # this build's
    # Only the NEW video went through the driver.
    assert card.state["copies"] == [
        (card.out.name, 0, [(V2, (card.clips / "two.mp4").read_bytes())])]
    rec = _record(card)
    assert rec["inplace"] == {"0:" + IMAGE: [[40, 5]]}
    assert set(rec["whole"]) == {"0:/" + V1, "0:/" + V2}
    assert rec["complete"] is True
    assert any("1 file(s) copied whole, 1 unchanged" in m for m, _l in lines)


def test_a_video_taken_back_gets_the_stock_file_back(card, monkeypatch):
    _first_build(card)
    card.state["writes"] = []
    card.state["grow"] = None
    card.state["counts"] = (0, 0, 0, 0)
    card.state["copies"].clear()
    monkeypatch.setattr(shutil, "copyfile",
                        lambda *a, **k: pytest.fail("the card was copied"))
    _, lines = _build(card)
    stock_v1 = CARD_TREE["turtles_pro"]["assets"]["lcd"]["1.asset"]
    assert card.state["copies"] == [(card.out.name, 0, [(V1, stock_v1)])]
    rec = _record(card)
    assert rec["whole"] == {} and rec["inplace"] == {}
    assert any("no longer replaced; the stock file goes back" in m
               for m, _l in lines)


def test_a_changed_source_is_copied_again(card, monkeypatch):
    _first_build(card)
    (card.clips / "one.mp4").write_bytes(b"CLIP-ONE-TAKE-2" + b"1" * 40)
    card.state["copies"].clear()
    monkeypatch.setattr(shutil, "copyfile",
                        lambda *a, **k: pytest.fail("the card was copied"))
    _build(card)
    assert card.state["copies"] == [
        (card.out.name, 0, [(V1, (card.clips / "one.mp4").read_bytes())])]
    assert _record(card)["whole"]["0:/" + V1]["digest"] == _md5(
        card.clips / "one.mp4")


def test_update_false_always_builds_whole(card, monkeypatch):
    _first_build(card)
    copies = []
    real = shutil.copyfile
    monkeypatch.setattr(shutil, "copyfile",
                        lambda s, d, *a, **k: (copies.append(d), real(s, d)))
    _, lines = _build(card, update=False)
    assert copies and not any("Updating" in m for m, _l in lines)


def test_an_explicit_update_that_cannot_happen_says_so(card, monkeypatch):
    _first_build(card)
    card.out.write_bytes(card.out.read_bytes() + b"!")     # touched since
    _, lines = _build(card, update=True)
    hits = [(m, l) for m, l in lines
            if m.startswith("Building from the original rather than")]
    assert hits and hits[0][1] == "warning"
    assert "changed since it was built" in hits[0][0]
    assert _record(card)["complete"] is True                # rebuilt whole


# --------------------------------------------------------------------------
# The refusals that keep it safe
# --------------------------------------------------------------------------

def test_a_file_the_last_build_moved_forces_a_whole_build(card):
    _first_build(card)
    card.state["build_reader"] = _Reader(MOVED_TREE)
    copies = []
    real = shutil.copyfile
    import unittest.mock as mock
    with mock.patch.object(shutil, "copyfile",
                           lambda s, d, *a, **k: (copies.append(d),
                                                  real(s, d))):
        _, lines = _build(card)
    hits = [m for m, _l in lines
            if m.startswith("This build can't update the last one in place")]
    assert hits and "no longer sits in the blocks" in hits[0]
    assert copies                                           # built whole
    assert _record(card)["complete"] is True


def test_a_file_rewritten_whole_then_patched_in_place_is_refused(card):
    _first_build(card)
    r = card.reader
    # Build #2 patches the video the last build copied whole.
    card.state["writes"] = [(_disk(r, "/" + V1, 3), b"fit")]
    card.state["grow"] = None
    copies = []
    real = shutil.copyfile
    import unittest.mock as mock
    with mock.patch.object(shutil, "copyfile",
                           lambda s, d, *a, **k: (copies.append(d),
                                                  real(s, d))):
        _, lines = _build(card)
    hits = [m for m, _l in lines
            if m.startswith("This build can't update the last one in place")]
    assert hits and "rewritten whole by the last build" in hits[0]
    assert copies


def test_a_different_original_is_never_patched_into_this_build(card):
    _first_build(card)
    other = card.stock.with_name("other.raw")
    shutil.copyfile(card.stock, other)
    why = engine.build_update_reason(_record(card), str(other),
                                     str(card.out), str(card.project))
    assert "different original" in why


def test_a_build_that_dies_half_way_is_never_updated_over(card, monkeypatch):
    _first_build(card)
    card.state["writes"] = [(_disk(card.reader, IMAGE, 40), b"OTHER")]

    def boom(out, writes):
        raise OSError("disk full")
    monkeypatch.setattr(engine, "_apply_writes", boom)
    with pytest.raises(OSError, match="disk full"):
        _build(card)
    assert card.out.exists()                    # the user's build is kept
    rec = _record(card)
    assert rec.get("building") is True
    assert "did not finish" in engine.build_update_reason(
        rec, str(card.stock), str(card.out), str(card.project))


def test_a_copy_that_fails_marks_the_record_incomplete(card, monkeypatch):
    _first_build(card)
    card.state["grow"] = _grow((V1, str(card.clips / "one.mp4")),
                               (V2, str(card.clips / "two.mp4")))
    card.state["counts"] = (1, 2, 0, 0)
    card.state["fail_after"] = 0                # the driver lands nothing
    monkeypatch.setattr(shutil, "copyfile",
                        lambda *a, **k: pytest.fail("the card was copied"))
    counts, lines = _build(card)
    assert counts[0] == (1, 1, 0, 0)            # the failed video is not claimed
    assert any(l == "error" and "could NOT be written" in m
               for m, l in lines)
    rec = _record(card)
    assert rec["complete"] is False
    assert "0:/" + V2 not in rec["whole"] and "0:/" + V1 in rec["whole"]
    assert "did not land every file" in engine.build_update_reason(
        rec, str(card.stock), str(card.out), str(card.project))


def test_a_killed_whole_build_leaves_no_output_and_no_record(card, monkeypatch):
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: (None, None, None, None, None))
    counts = engine.write_image(str(card.stock), str(card.project),
                                str(card.out))
    assert counts == ((0, 0, 0, 0), None, None)
    assert not card.out.exists()
    assert not os.path.exists(engine.build_manifest_path(card.out))


# --------------------------------------------------------------------------
# The digests, and the verified-audio cache
# --------------------------------------------------------------------------

def test_source_digests_go_through_the_project_cache_except_for_scratch(
        tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    inside = project / "video" / "a.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"inside")
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"outside")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    temp = scratch / "fw.bin"
    temp.write_bytes(b"temp")
    assert engine._source_digest(str(project), str(inside)) == _md5(inside)
    assert engine._source_digest(str(project), str(outside)) == _md5(outside)
    assert engine._source_digest(str(project), str(temp),
                                 str(scratch)) == _md5(temp)
    engine._save_hashcache(str(project))
    cache = json.loads((project / ".hashcache.json").read_text())
    assert "video/a.mp4" in cache
    assert any(k.startswith("abs:") for k in cache)
    assert not any("fw.bin" in k for k in cache)


def test_the_verified_audio_set_round_trips(tmp_path, monkeypatch):
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF-firmware")
    assets = tmp_path / "assets"
    assets.mkdir()
    cache = engine._FinalAudioCache(str(assets), str(gr), b"bank-identity")
    encoded = {100: b"A" * 8, 200: b"B" * 8}
    key = cache.key_for(encoded)
    assert cache.load(key) is None
    restored = {100: b"A" * 6 + b"..", 200: b"B" * 8}
    cache.store(key, restored)
    assert cache.load(key) == restored
    assert cache.load(cache.key_for({100: b"A" * 8})) is None
    assert cache.key_for({200: b"B" * 8, 100: b"A" * 8}) == key
    # Another firmware, or another encode environment, is another key.
    other = engine._FinalAudioCache(str(assets), str(gr), b"other-bank")
    assert other.key_for(encoded) != key
    monkeypatch.setenv("PAD_STERN_HEADROOM", "0.5")
    assert engine._FinalAudioCache(str(assets), str(gr),
                                   b"bank-identity").key_for(encoded) != key
    # A path-only toggle does not move it.
    monkeypatch.delenv("PAD_STERN_HEADROOM")
    monkeypatch.setenv("PAD_STERN_SKIP_FINAL_VERIFY", "1")
    assert engine._FinalAudioCache(str(assets), str(gr),
                                   b"bank-identity").key_for(encoded) == key
    # A corrupt file reads as no entry.
    cache.path and open(cache.path, "wb").write(b"junk")
    assert cache.load(key) is None


def test_the_two_audio_caches_share_one_base_key(tmp_path):
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF")
    assets = tmp_path / "assets"
    assets.mkdir()
    body = engine._AudioBodyCache(str(assets), str(gr), None, {}, {},
                                  img_ident=b"ident")
    final = engine._FinalAudioCache(str(assets), str(gr), b"ident")
    assert body.base_key == final.base_key


# --------------------------------------------------------------------------
# The plumbing: pipeline, manufacturer hooks, the Build button's prompt
# --------------------------------------------------------------------------

def test_the_pipeline_carries_the_answer_to_the_engine(monkeypatch):
    from pinball_decryptor.plugins.stern import pipeline as pl
    seen = {}

    def fake_write(original, assets, out, log=None, progress=None,
                   cancel=None, label=None, update=None):
        seen["update"] = update
        return (0, 0, 0, 0), None, None
    monkeypatch.setattr(pl, "detect_game", lambda p: "turtles_pro")
    monkeypatch.setattr(pl, "_require_engine", lambda: None)
    monkeypatch.setattr(pl, "_log_multi_image", lambda p, log: None)
    monkeypatch.setattr(pl.engine, "write_image", fake_write)
    p = pl.SternWritePipeline("a.raw", "assets", "out.raw",
                              lambda *a, **k: None, lambda *a, **k: None,
                              lambda *a, **k: None, lambda *a, **k: None,
                              update=True)
    p._run()
    assert seen["update"] is True


def test_only_spike2_offers_an_update(tmp_path):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    m = SternManufacturer()
    assert m.supports_build_update() is True
    assert "no record" in m.build_update_reason(
        str(tmp_path / "a.raw"), str(tmp_path), str(tmp_path / "out.raw"))
    m._era = "spike1"
    assert m.supports_build_update() is False
    assert "start from the original" in m.build_update_reason(
        str(tmp_path / "a.raw"), str(tmp_path), str(tmp_path / "out.raw"))


class _Mfr:
    def __init__(self, supports, why):
        self._supports, self._why = supports, why

    def supports_build_update(self):
        return self._supports

    def build_update_reason(self, *a):
        return self._why


def _prompt(monkeypatch, mfr, yesnocancel=None, yesno=None):
    import pinball_decryptor.app as app_mod
    asked = {}
    monkeypatch.setattr(app_mod.messagebox, "askyesnocancel",
                        lambda title, text, **k: asked.setdefault(
                            "ync", (title, text)) and yesnocancel)
    monkeypatch.setattr(app_mod.messagebox, "askyesno",
                        lambda title, text, **k: asked.setdefault(
                            "yn", (title, text)) and yesno)
    stub = type("Stub", (), {"_current_mfr": mfr})()
    return app_mod.App._confirm_build_over(stub, "a.raw", "assets",
                                           os.path.join("build", "out.raw")), asked


@pytest.mark.parametrize("answer, expect", [(True, True), (False, False),
                                            (None, None)])
def test_the_prompt_offers_the_update_when_the_record_vouches(
        monkeypatch, answer, expect):
    got, asked = _prompt(monkeypatch, _Mfr(True, None), yesnocancel=answer)
    assert got is expect
    assert "ync" in asked and "yn" not in asked
    assert asked["ync"][0] == "Update the last build?"
    assert "Yes: update it in place" in asked["ync"][1]


def test_the_prompt_says_why_an_update_is_off(monkeypatch):
    got, asked = _prompt(monkeypatch, _Mfr(True, "the file has changed since "
                                             "it was built"), yesno=True)
    assert got is False and "ync" not in asked
    assert "the file has changed since it was built" in asked["yn"][1]
    assert "Building will overwrite it." in asked["yn"][1]


def test_the_prompt_is_the_plain_question_for_other_plugins(monkeypatch):
    got, asked = _prompt(monkeypatch, _Mfr(False, "n/a"), yesno=False)
    assert got is None and "ync" not in asked
    assert "can't be updated" not in asked["yn"][1]
