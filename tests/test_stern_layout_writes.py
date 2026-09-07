"""Tests for writing a scene's text-LAYOUT edits to the card.

Where a line of scene text sits, how it is aligned and how big it is drawn
are bytes of the SCENE (its keyframe rect, its align word, the glyph table it
bakes for that face), so a layout edit is a size-neutral ``scene.radium``
patch — the same shape as a recolour (``tests/test_stern_text_colors.py``)
on different bytes of the same file.  ``scene_layout.text_layout_patches``
owns the bytes and is tested in ``tests/test_stern_scene_layout_edits.py``;
what is under test here is the CARD side, ``engine._radium_layout_writes``:

* the disk writes are exactly the patches, mapped through the reader's
  extent map (a run split across two extents included);
* the per-inode overlay the ``.sidx`` refresh needs is keyed by ``i_block``
  and carries the file offsets;
* a scene that is not on the card, or cannot be read, is a warning and a
  skip, never a write to the wrong bytes;
* the notes the patcher raises (a resize reaching other lines, a size
  conflict) reach the build log at the right level;
* ``_compute_patches`` carries the writes and counts the lines as text edits,
  so ``write_overrides`` — which calls it — ships them for free.
"""

import io

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import (         # noqa: E402
    engine, radium, scene_layout, text_layout)
from tests._ext4_fake import FakeExt4Reader, materialize_files   # noqa: E402
from tests.test_stern_scene_layout_edits import (     # noqa: E402
    AWARD, FILL_METRICS, _apply, _parse, _scene)
from tests.test_stern_text_colors import _FakeReader  # noqa: E402

CARD = "/godzilla_pro/assets/battle_intro/scene.radium"


def _quiet(*a, **k):
    pass


def _capture(msgs):
    return lambda m, lvl="info": msgs.append((lvl, m))


def _expected_patches(buf, edits):
    imgs, tables = _parse(buf)
    return scene_layout.text_layout_patches(buf, imgs, tables, edits)


# ---------------------------------------------------------------------------
# the writes
# ---------------------------------------------------------------------------

def test_writes_are_the_patches_and_the_overlay_names_the_inode(tmp_path):
    """Every byte the patcher asks for lands on disk, once, and the overlay
    the ``.sidx`` refresh reads carries the same bytes at file offsets."""
    buf = _scene(AWARD)
    reader = _FakeReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD",
                           dx=10, dy=-4, align="left", size=150)
    writes, n, overlays = engine._radium_layout_writes(
        reader, str(tmp_path), _quiet, lambda: False)
    patches, pn, _notes = _expected_patches(
        buf, {"AWARD": {"dx": 10.0, "dy": -4.0, "align": "left",
                        "size": 150}})
    assert n == pn == 1
    assert patches                                    # the edit is real
    # the fake reader maps file offset == disk offset
    assert sorted(writes) == sorted(patches)
    (ib, (node, ov)), = overlays.items()
    assert ib == CARD.encode() and node["_path"] == CARD
    assert ov == dict(patches)

    patched = _apply(buf, writes)
    assert len(patched) == len(buf)                   # size-neutral, always
    imgs2, tables2 = _parse(patched)
    kfs = scene_layout.text_layout_offsets(patched, imgs2, tables2)["AWARD"]
    assert len(kfs) == 2                              # fill + outline
    for kf in kfs:
        assert kf["rect"] == pytest.approx([110.0, 46.0, 410.0, 86.0])
        assert kf["align"] == 0
    by = {t["name"]: t for t in tables2}
    assert radium.table_size_px(by["FillFont"]) == 18         # 12 * 1.5
    assert radium.table_size_px(by["OutlineFont"]) == 21      # 14 * 1.5
    a = {g["char"]: g for g in by["FillFont"]["glyphs"]}[0x41]
    assert a["metrics"] == pytest.approx(tuple(v * 1.5 for v in FILL_METRICS))


def test_a_run_split_across_two_extents_is_split_the_same_way(tmp_path):
    """The writes go through ``disk_ranges`` exactly as a colour edit's do:
    a patch that the extent map splits comes out as two disk writes whose
    bytes, joined, are the patch."""
    buf = _scene(AWARD)
    base = 0x40000

    class _SplitReader(_FakeReader):
        def disk_ranges(self, node, file_off, length):
            if length < 2:
                return [(base + file_off, length)]
            h = length // 2
            return [(base + file_off, h), (base + file_off + h, length - h)]

    reader = _SplitReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", dx=3)
    writes, n, overlays = engine._radium_layout_writes(
        reader, str(tmp_path), _quiet, lambda: False)
    patches, _pn, _notes = _expected_patches(buf, {"AWARD": {"dx": 3.0}})
    assert n == 1 and len(writes) == 2 * len(patches)
    # reassemble by adjacency and compare to the patches
    got = {}
    for disk, b in sorted(writes):
        off = disk - base
        for start, chunk in list(got.items()):
            if start + len(chunk) == off:
                got[start] = chunk + b
                break
        else:
            got[off] = b
    assert got == dict(patches)
    # the overlay is file-relative, whole patches, regardless of the split
    (_ib, (_node, ov)), = overlays.items()
    assert ov == dict(patches)


def test_a_scene_missing_from_the_card_warns_and_skips(tmp_path):
    reader = _FakeReader({"/g/other.radium": _scene(AWARD)})
    text_layout.set_layout(str(tmp_path), "/g/missing.radium", "AWARD", dx=5)
    msgs = []
    writes, n, ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert (writes, n, ov) == ([], 0, {})
    assert any(lvl == "warning" and "wasn't found on the card" in m
               for lvl, m in msgs)


def test_an_unreadable_scene_warns_and_skips(tmp_path):
    """The card's copy of the scene is not what the extract showed: no text
    keyframes can be read, so nothing is written and the user is told."""
    reader = _FakeReader({CARD: b"\x00" * 4096})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", dx=5)
    msgs = []
    writes, n, ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert (writes, n, ov) == ([], 0, {})
    assert any(lvl == "warning" and "left alone" in m for lvl, m in msgs)


def test_a_string_the_scene_no_longer_draws_is_a_warning_not_a_write(tmp_path):
    buf = _scene(AWARD)
    reader = _FakeReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "GONE", dx=5)
    msgs = []
    writes, n, ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert (writes, n, ov) == ([], 0, {})
    assert any(lvl == "warning" and "GONE" in m and "not drawn" in m
               for lvl, m in msgs)


def test_no_manifest_is_not_a_write(tmp_path):
    reader = _FakeReader({CARD: _scene(AWARD)})
    assert engine._radium_layout_writes(
        reader, str(tmp_path), _quiet, lambda: False) == ([], 0, {})


def test_a_resize_that_reaches_other_lines_is_logged_as_information(tmp_path):
    """A size edit scales the scene's glyph table for that face, so every
    line drawn with it in that scene grows too; the log says which."""
    buf = _scene(AWARD + [("BONUS", "FillFont", (0.0, 0.0, 200.0, 40.0),
                           0, 2.0)])
    reader = _FakeReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", size=120)
    msgs = []
    writes, n, _ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert n == 1 and writes
    hits = [(lvl, m) for lvl, m in msgs if "also resizes" in m]
    assert hits and hits[0][0] == "info" and "BONUS" in hits[0][1]
    assert not any(lvl == "warning" for lvl, _m in msgs)


def test_a_size_conflict_on_a_shared_table_is_a_warning(tmp_path):
    """Two lines sharing one baked table asked for different sizes: the
    table takes the first, the second is noted at warning level."""
    buf = _scene(AWARD + [("BONUS", "FillFont", (0.0, 0.0, 200.0, 40.0),
                           0, 2.0)])
    reader = _FakeReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", size=120)
    text_layout.set_layout(str(tmp_path), CARD, "BONUS", size=200)
    msgs = []
    writes, n, _ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert writes and n >= 1
    assert any(lvl == "warning" for lvl, _m in msgs)


def test_an_edit_the_card_already_has_writes_nothing(tmp_path):
    """The AWARD lines are already centred: 'center' is not a write, and the
    user is told so rather than warned about a stale row."""
    buf = _scene(AWARD)
    reader = _FakeReader({CARD: buf})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", align="center")
    msgs = []
    writes, n, ov = engine._radium_layout_writes(
        reader, str(tmp_path), _capture(msgs), lambda: False)
    assert (writes, n, ov) == ([], 0, {})
    assert not any(lvl == "warning" for lvl, _m in msgs)
    assert any("nothing was written" in m for _lvl, m in msgs)


def test_cancel_stops_the_walk(tmp_path):
    reader = _FakeReader({CARD: _scene(AWARD)})
    text_layout.set_layout(str(tmp_path), CARD, "AWARD", dx=5)
    assert engine._radium_layout_writes(
        reader, str(tmp_path), _quiet, lambda: True) == ([], 0, {})


# ---------------------------------------------------------------------------
# through _compute_patches and write_overrides
# ---------------------------------------------------------------------------

class _CardReader(FakeExt4Reader):
    base = 0


def _card(monkeypatch, tmp_path, buf):
    """A one-file card the orchestrator can be pointed at: the fake ext4
    reader in place of ``_locate``, the .sidx refresh and validator bypass
    (both best-effort, both need a real card) stubbed out."""
    tree = {"godzilla_pro": {"assets": {"battle_intro": {"scene.radium": buf}}}}
    reader = _CardReader(tree)
    img = tmp_path / "card.raw"
    img.write_bytes(bytes(4096))
    materialize_files(str(img), tree)
    monkeypatch.setattr(engine, "_locate", lambda f, p: (reader, None, None))
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 1 << 30)])
    monkeypatch.setattr(engine, "_compute_sidx_writes",
                        lambda *a, **k: [])
    from pinball_decryptor.plugins.stern import valpatch
    monkeypatch.setattr(valpatch, "compute_writes",
                        lambda *a, **k: ([], None))
    return reader, img


def test_compute_patches_carries_the_layout_writes_as_text_edits(
        tmp_path, monkeypatch):
    buf = _scene(AWARD)
    reader, _img = _card(monkeypatch, tmp_path, buf)
    assets = tmp_path / "assets"
    assets.mkdir()
    text_layout.set_layout(str(assets), CARD, "AWARD", dx=10, size=150)
    msgs = []
    writes, counts, grow, _audio, _val = engine._compute_patches(
        io.BytesIO(b""), [], str(assets), log=_capture(msgs), progress=None,
        cancel=lambda: False)
    patches, _pn, _notes = _expected_patches(
        buf, {"AWARD": {"dx": 10.0, "size": 150}})
    node = reader.read_inode(next(
        ino for p, ino, _n in reader.iter_regular_files(min_size=1)
        if p == CARD))
    disk0 = reader.disk_ranges(node, 0, 1)[0][0]
    assert sorted(writes) == sorted((disk0 + off, b) for off, b in patches)
    assert counts == (0, 0, 0, 1)                 # a layout line IS a text edit
    assert grow is None
    assert any("re-laid-out text line(s)" in m for _lvl, m in msgs)


def test_write_overrides_ships_the_re_laid_out_scene(tmp_path, monkeypatch):
    """The override set is the touched files patched: the scene comes out
    with exactly the patcher's bytes and nothing else changed."""
    buf = _scene(AWARD)
    _reader, img = _card(monkeypatch, tmp_path, buf)
    assets = tmp_path / "assets"
    assets.mkdir()
    text_layout.set_layout(str(assets), CARD, "AWARD", dx=10, align="right")
    out = tmp_path / "ovr"
    counts, _mode, _val, files = engine.write_overrides(
        str(img), str(assets), str(out))
    assert counts == (0, 0, 0, 1)
    assert [p for p, _n in files] == [CARD]
    patches, _pn, _notes = _expected_patches(
        buf, {"AWARD": {"dx": 10.0, "align": "right"}})
    shipped = (out / "godzilla_pro" / "assets" / "battle_intro"
               / "scene.radium").read_bytes()
    assert shipped == _apply(buf, patches)
    assert len(shipped) == len(buf)


def test_nothing_to_write_names_the_layout_manifest(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        engine._compute_patches(io.BytesIO(b""), [], str(tmp_path),
                                log=_quiet, progress=None,
                                cancel=lambda: False)
    assert "text/layout.tsv" in str(exc.value)
