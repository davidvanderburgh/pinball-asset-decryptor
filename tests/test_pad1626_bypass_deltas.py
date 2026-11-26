"""PAD-1626: the validator bypass on a multi-boot STORE card whose extra images keep their game
as a DELTA of the primary's stock game (item 107).

The reporter's 3-image Godzilla card (stock, a mode build, a custom build already bypassed)
failed its own verify: image 1's game "differs" and a delta's base was "missing".  On the card
a delta'd file's own name links the BASE blob, so the bypass read and patched the STOCK game
and put it under the mode build's image, then the base nothing linked any more was removed
from under image 2's delta.  The bypass now patches the file the tree really holds (base +
delta), stores it whole and drops it from the tree's deltas, and the store keeps the base of
every delta that stays.
"""
import hashlib
import os
import sys
import types

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
if RIG not in sys.path:
    sys.path.insert(0, RIG)
import mkmulticard as mk  # noqa: E402
import treesync as ts  # noqa: E402

MARK = b"BYPASSED"
GAME = "godzilla_pro/game"


def _big(seed, n=(1 << 20) + 5000):
    return bytes((i * 7 + seed) & 0xFF for i in range(n))


def _edit(b, off, payload):
    out = bytearray(b)
    out[off:off + len(payload)] = payload
    return bytes(out)


def _bypass(elf, sdata, gpath, title):
    """A stand-in validator patch: the first bytes say whether it is on (same size, as the real one)."""
    if elf.startswith(MARK):
        return "bypassed", None, None, ["bypassed"]
    return "armed", MARK + elf[len(MARK):], None, ["armed"]


def _store(tmp_path):
    stock = _big(1)
    mods = _edit(stock, 4096 * 10, b"mode hooks" * 300)                     # the mode build's game
    kaiju = MARK + _edit(stock, 4096 * 40, b"kaiju" * 600)[len(MARK):]      # a custom build, bypassed already
    ops = mk.DirOps(str(tmp_path))
    ops.mkdir(ts.BLOBS_DIR, 0o700, 0, 0)
    images = []
    for i, (sub, game) in enumerate((("", stock), ("img1", mods), ("img2", kaiju))):
        man, src = ts.mem_source_from({GAME: game, "godzilla_pro/data": b"d%d" % i})
        if sub:
            ops.mkdir(sub, 0o755, 0, 0)
        plan = None
        if i:
            ranges = mk._treesync()._materialize().find_delta(
                ts.MemSource({"": stock}).chunks(""), ts.MemSource({"": game}).chunks(""), len(stock))
            plan = {GAME: {"base": ts.blob_key(images[0].tree.files[GAME]), "ranges": ranges}}
        stats = ts.apply_changes(ops, sub, ts.diff_tree(None, man), man, src, store=True, deltas=plan)
        im = ts.ImageTrees(i, "/dev/mmcblk0p3" + (":" + sub if sub else ""), sub, man,
                           deltas=stats.get("delta_files") or None)
        if im.deltas:
            ts.write_delta_index(ops, sub, im.deltas)
        images.append(im)
    assert images[1].deltas and images[2].deltas                            # both extras keep the game as a delta
    plan = types.SimpleNamespace(trees=[(types.SimpleNamespace(num=3), sub) for sub in ("", "img1", "img2")])
    return ops, plan, ts.CardTrees(images), stock, mods, kaiju


def _real(ops, im):
    """The game the tree holds as the card boots it: rebuilt from its delta, or its own file."""
    if im.deltas and GAME in im.deltas:
        return ts.delta_content(ops, im.deltas[GAME])
    return b"".join(ops.read_chunks(ts._join(im.sub, GAME)))


def test_the_bypass_patches_each_trees_own_game_and_keeps_every_delta_whole(tmp_path, monkeypatch, capsys):
    ops, plan, trees, stock, mods, kaiju = _store(tmp_path)
    monkeypatch.setattr(mk, "bypass_tree_bytes", _bypass)
    stock_key = ts.blob_key(trees.image(0).tree.files[GAME])
    mk.bypass_store_ops(ops, plan, trees)
    out = capsys.readouterr().out
    assert "image 1 /dev/mmcblk0p3:img1: validator: bypassed (%s written)" % GAME in out
    assert "image 2 /dev/mmcblk0p3:img2: validator: bypassed (already)" in out
    # every image boots its own game, patched: the mode build is the mode build, not the stock game
    patched = lambda b: MARK + b[len(MARK):]                                 # noqa: E731
    assert _real(ops, trees.image(0)) == patched(stock)
    assert _real(ops, trees.image(1)) == patched(mods) != patched(stock)
    assert _real(ops, trees.image(2)) == kaiju
    # image 1's game is stored whole now: out of its deltas, its index gone, a blob of its own
    assert trees.image(1).deltas is None and not ops.exists("img1/" + ts.DELTA_INDEX)
    assert trees.image(1).bypass["game"] == hashlib.sha256(patched(mods)).hexdigest()
    own = [n for n in ops.listdir(ts.BLOBS_DIR) if n.startswith(trees.image(1).bypass["game"] + ".")]
    assert len(own) == 1 and ops.lstat(ts.BLOBS_DIR + "/" + own[0])["ino"] == ops.lstat("img1/" + GAME)["ino"]
    # image 2's delta stays, and so does the stock base it rebuilds from, though no tree links it now
    assert set(trees.image(2).deltas) == {GAME} and ops.exists("img2/" + ts.DELTA_INDEX)
    assert ops.exists(ts.BLOBS_DIR + "/" + stock_key)
    assert trees.delta_names() == {trees.image(2).deltas[GAME]["delta"]}
    assert all(ops.exists(ts.BLOBS_DIR + "/" + n) for n in trees.delta_names())
    # a second run finds every image patched and changes nothing
    before = sorted(os.listdir(str(tmp_path / ts.BLOBS_DIR)))
    mk.bypass_store_ops(ops, plan, trees)
    assert "armed" not in capsys.readouterr().out
    assert sorted(os.listdir(str(tmp_path / ts.BLOBS_DIR))) == before


def test_gc_keeps_a_kept_deltas_base_and_still_removes_a_dropped_ones(tmp_path):
    ops, _plan, trees, _stock, _mods, _kaiju = _store(tmp_path)
    stock_key = ts.blob_key(trees.image(0).tree.files[GAME])
    ops.unlink(GAME)                                                         # the primary moved off the stock game
    ops.unlink("img1/" + GAME)
    ops.unlink("img2/" + GAME)
    assert ops.lstat(ts.BLOBS_DIR + "/" + stock_key)["nlink"] == 1
    assert ts.gc_blobs(ops, keep_deltas=trees.delta_names())[0] >= 0
    assert ops.exists(ts.BLOBS_DIR + "/" + stock_key)                        # two deltas still name it
    assert ts.gc_blobs(ops, keep_deltas=set())[0] == 3                       # neither kept: both and the base go
    assert not ops.exists(ts.BLOBS_DIR + "/" + stock_key)


def test_a_delta_that_does_not_rebuild_refuses_that_trees_bypass(tmp_path, monkeypatch):
    ops, _plan, trees, _stock, _mods, _kaiju = _store(tmp_path)
    monkeypatch.setattr(mk, "bypass_tree_bytes", _bypass)
    entry = dict(trees.image(1).deltas[GAME], base="0" * 64 + ".0644.0.0")
    with pytest.raises(mk.Refused, match="stored as a delta that can't be rebuilt"):
        mk.apply_bypass_fs(ops, "img1", {GAME: entry})
    assert ts.delta_base(ops, ts.BLOBS_DIR + "/" + entry["delta"]) == trees.image(1).deltas[GAME]["base"]
    assert ts.delta_base(ops, "godzilla_pro/data") is None
