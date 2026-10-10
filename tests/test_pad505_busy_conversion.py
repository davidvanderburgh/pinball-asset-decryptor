"""PAD-505 (DragonRR): "PAD locked up although PC is very busy ... Needs visual sign
that it is working", then "emulation failed".

Two things.  Emulate's Start converted a whole game's pictures (5,811 for his Godzilla,
two log lines apiece) and the app's one loop handed the log lines on until the queue was
EMPTY, which on a busy PC it never was: the State line sat at "Converting pictures: 5 of
5,811" while the log scrolled, and no button answered.  Then the run stopped with "Your
edits could not be prepared: file offset 0x4a0000 not allocated": his custom card was
copied with a tool that leaves blocks of zeros out of a file, and the font atlas with his
three edited glyphs had its empty part in one of those holes.

The card half runs on tests/fixtures/treesync_tiny.ext4.gz, a real ext4 whose
``d/hole.bin`` has a hole between a 4 KiB head and a 4 KiB tail and whose
``d/uninit.bin`` is an unwritten extent after a 4 KiB head (see test_ext4_reader.py).
"""
import gzip
import hashlib
import hmac
import os
import queue
import shutil
import sys
import threading
import time
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import treesync_tiny as tiny  # noqa: E402

from pinball_decryptor.core import session_log  # noqa: E402
from pinball_decryptor.core.messages import LogMsg  # noqa: E402
from pinball_decryptor.plugins.stern import engine, ext4, sidx  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "treesync_tiny.ext4.gz")


@pytest.fixture(autouse=True)
def _own_logs(tmp_path, monkeypatch):
    """Never the developer's own session log, nor a project left open."""
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE", str(tmp_path / "logs"))
    monkeypatch.setattr(session_log, "_project_dir", None)


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    p = tmp_path_factory.mktemp("ext4") / "tiny.img"
    with gzip.open(FIXTURE, "rb") as g, open(p, "wb") as f:
        f.write(g.read())
    return p


@pytest.fixture
def card(image):
    with open(image, "rb") as f:
        yield f, ext4.Ext4Reader(f, 0, os.path.getsize(image))


def _node(reader, rel):
    return {r: n for r, _k, _i, n in reader.iter_tree(2)}[rel]


def _apply(image, writes, tmp_path):
    """A copy of the card with *writes* on it, read back through a new reader."""
    copy = tmp_path / "written.img"
    shutil.copyfile(image, copy)
    with open(copy, "r+b") as f:
        for disk, b in writes:
            f.seek(disk)
            f.write(b)
    return copy


def _read(path, rel):
    with open(path, "rb") as f:
        r = ext4.Ext4Reader(f, 0, os.path.getsize(path))
        return b"".join(d for _o, d in r.read_file_chunks(_node(r, rel)))


# -- where an edit goes on a card file with a hole ---------------------------

def test_place_is_disk_ranges_where_the_file_has_blocks(card):
    _f, reader = card
    node = _node(reader, "d/hole.bin")
    data = b"x" * 3000
    writes, held = reader.place(node, 100, data)
    want = [(d, n) for d, n in reader.disk_ranges(node, 100, len(data))]
    assert [(d, len(b)) for d, b in writes] == want
    assert b"".join(b for _d, b in writes) == data and held == []


def test_zeros_over_a_hole_need_no_write(card, image, tmp_path):
    """His case: the atlas is written whole, and its empty part, where the hole
    is, is the same zeros the file already reads as there."""
    _f, reader = card
    node = _node(reader, "d/hole.bin")
    with pytest.raises(ext4.Ext4Error):
        reader.disk_ranges(node, 0, node["size"])
    data = bytearray(node["size"])
    data[:4096] = b"A" * 4096                      # the head, edited
    data[tiny.HOLE_TAIL_AT:] = b"B" * 4096          # the tail, edited
    writes, held = reader.place(node, 0, bytes(data))
    assert held == []
    assert sum(len(b) for _d, b in writes) == 8192
    assert _read(_apply(image, writes, tmp_path), "d/hole.bin") == bytes(data)


def test_data_over_a_hole_is_held_with_its_file_offset(card):
    _f, reader = card
    node = _node(reader, "d/hole.bin")
    data = b"C" * 4096 + b"\0" * 4096 + b"D" * 100 + b"\0" * 1000
    writes, held = reader.place(node, 0, data)
    # the head has a block; the hole's zeros and its data do not
    assert [len(b) for _d, b in writes] == [4096]
    assert held == [(4096, data[4096:])]


def test_an_unwritten_extent_is_a_hole_too(card):
    """It reads as zeros whatever its blocks hold, so a write into them would not
    show."""
    _f, reader = card
    node = _node(reader, "d/uninit.bin")
    writes, held = reader.place(node, 0, b"E" * 4096 + b"F" * 10)
    assert [len(b) for _d, b in writes] == [4096] and held == [(4096, b"F" * 10)]
    assert reader.place(node, 8192, bytes(500)) == ([], [])


def test_engine_place_holds_data_for_a_set_and_a_write_refuses_it(card):
    _f, reader = card
    node = _node(reader, "d/hole.bin")
    data = b"G" * 4096 + b"H" * 10
    with pytest.raises(RuntimeError, match="no space on the card"):
        engine._place(reader, node, 0, data)
    engine._HOLE_WRITES.writes = sink = []
    try:
        writes = engine._place(reader, node, 0, data)
    finally:
        engine._HOLE_WRITES.writes = None
    assert [len(b) for _d, b in writes] == [4096]
    assert sink == [(node, 4096, b"H" * 10)]
    # zeros over it, or no hole at all: as it always was, no sink needed
    assert engine._place(reader, node, 0, b"G" * 4096 + bytes(10))
    a = _node(reader, "d/a.bin")
    assert engine._place(reader, a, 0, b"z" * 10) == [
        (reader.disk_ranges(a, 0, 10)[0][0], b"z" * 10)]


def test_the_digest_of_a_file_with_a_hole_is_of_what_the_game_reads(card):
    """The .sidx record the card checks: the patched file as a mount serves it,
    zeros in the hole.  It used to stop on the hole (the same "not allocated")."""
    f, reader = card
    node = _node(reader, "d/hole.bin")
    over = {10: b"patch", tiny.HOLE_TAIL_AT + 5: b"tail"}
    got = engine._overlay_digests(reader, f, node, over)
    want = bytearray(tiny.hole_bytes())
    for off, b in over.items():
        want[off:off + len(b)] = b
    assert got == sidx.digests(bytes(want))
    # a file with no hole: the same digests as before
    a = _node(reader, "d/a.bin")
    whole = b"".join(d for _o, d in reader.read_file_chunks(a))
    assert engine._overlay_digests(reader, f, a, {}) == (
        hmac.new(sidx.SIDX_KEY, whole, hashlib.sha1).digest(),
        hashlib.md5(whole).digest())


def test_the_set_carries_the_held_writes_in_their_file(card):
    _f, reader = card
    node = _node(reader, "d/hole.bin")
    writes, held = reader.place(node, 0, b"I" * 4096 + b"J" * 8)
    by_file, unmapped = engine._writes_by_file(
        reader, writes, [(node, off, b) for off, b in held])
    assert unmapped == []
    (path, (got_node, file_writes)), = by_file.items()
    assert path.endswith("d/hole.bin") and got_node["i_block"] == node["i_block"]
    assert file_writes == [(0, b"I" * 4096), (4096, b"J" * 8)]


def test_a_second_build_puts_the_hole_back(card, tmp_path):
    """A set patched in place puts the card's own bytes back over what the last
    build wrote; in a hole those are zeros."""
    f, reader = card
    node = _node(reader, "d/hole.bin")
    dest = tmp_path / "hole.bin"
    reader.extract_file(node, str(dest))
    with open(dest, "r+b") as out:
        out.seek(0)
        out.write(b"K" * 5000)                     # the head and into the hole
    engine._restore_stock(f, reader, node, str(dest), [(0, 5000)])
    assert dest.read_bytes() == tiny.hole_bytes()


# -- a card Write from such a card: the file goes on whole --------------------
# DragonRR: "We are using PAD to create these files".  PAD's own debugfs write
# (the Write's grow step on macOS and Linux) and mke2fs -d (Multi-boot) keep no
# block for a block of zeros, so the next Write may start from such a card.

def _locate_tiny(monkeypatch, reader):
    monkeypatch.setattr(engine, "_locate", lambda f, parts: (reader, None, None))


def test_a_write_puts_a_file_with_data_in_its_hole_on_whole(card, monkeypatch,
                                                              tmp_path):
    f, reader = card
    _locate_tiny(monkeypatch, reader)
    node = _node(reader, "d/hole.bin")
    a = _node(reader, "d/a.bin")
    head = reader.disk_ranges(node, 0, 10)[0][0]
    other = reader.disk_ranges(a, 0, 4)[0][0]
    writes = [(head, b"I" * 10), (other, b"zzzz")]
    held = [(node, 4096, b"J" * 8)]
    plan = {"offset": 0, "jobs": [("v.mp4", "x"), ("bank", "y"), ("game", "z")],
            "n_video": 1, "audio_job": 1, "cleanup": str(tmp_path)}
    got = engine._hole_files_whole(f, [], (writes, "counts", plan, None, None),
                                   held, lambda *a, **k: None)
    w, counts, plan, _a, _v = got
    assert w == [(other, b"zzzz")] and counts == "counts"   # its own write left
    rel, src = plan["jobs"][1]
    assert rel == "d/hole.bin"
    assert [j[0] for j in plan["jobs"]] == ["v.mp4", "d/hole.bin", "bank", "game"]
    assert plan["audio_job"] == 2                      # the bank moved one on
    want = bytearray(tiny.hole_bytes())
    want[:10] = b"I" * 10
    want[4096:4104] = b"J" * 8
    with open(src, "rb") as staged:
        assert staged.read() == bytes(want)


def test_compute_patches_hands_held_writes_to_the_whole_file_step(card,
                                                                  monkeypatch):
    f, reader = card
    _locate_tiny(monkeypatch, reader)
    node = _node(reader, "d/hole.bin")

    def inner(*a, **k):
        return (engine._place(reader, node, 0, b"K" * 4096 + b"L" * 4),
                (1, 0, 0, 0), None, None, None)

    monkeypatch.setattr(engine, "_compute_patches_inner", inner)
    writes, _c, plan, _a, _v = engine._compute_patches(
        f, [], "assets", lambda *a, **k: None, None, lambda: False)
    try:
        assert writes == [] and [r for r, _s in plan["jobs"]] == ["d/hole.bin"]
        assert getattr(engine._HOLE_WRITES, "writes", None) is None
    finally:
        engine._rmtree_grow_plan(plan)
    # straight onto an SD card a file can't grow, so it is refused
    with pytest.raises(RuntimeError, match="no space on the card"):
        engine._compute_patches(f, [], "assets", lambda *a, **k: None, None,
                                lambda: False, dest_is_device=True)


# -- a Start converts only the pictures that need it -------------------------
# DragonRR, after the release that kept the app live: "when I run emulate it is
# still hanging staging files".  Every Start converted all 5,811 pictures again.

def _pictures(tmp_path, names=("a", "b", "c")):
    from PIL import Image
    from pinball_decryptor.core import colour_profile as cp
    from pinball_decryptor.core import image_slots, staged_changes
    assets = tmp_path / "proj"
    (assets / "images").mkdir(parents=True)
    slots = {}
    for i, n in enumerate(names):
        p = assets / "images" / ("%s.png" % n)
        Image.new("RGB", (8, 8), (40 * i, 120, 200)).save(p)
        rel = "images/%s.png" % n
        slots[rel] = image_slots.ImageSlot(rel_path=rel, abs_path=str(p), ext=".png",
                                           info=None, size=p.stat().st_size)
    staged_changes.save(str(assets), {"image_color_unlocked": True,
                                      "image_color_slots": {r: True for r in slots}})
    cp.store_asset_profile(str(assets), dict(cp.PRESETS)["bw"])
    return str(assets), slots


def _count_stagings(monkeypatch):
    from pinball_decryptor.core import image_slots
    real, seen = image_slots.stage_replacement, []

    def counted(slot, rep, **kw):
        seen.append(slot.rel_path)
        return real(slot, rep, **kw)

    monkeypatch.setattr(image_slots, "stage_replacement", counted)
    return seen


def test_a_second_start_converts_no_picture_again(tmp_path, monkeypatch):
    from pinball_decryptor.core import image_slots
    assets, slots = _pictures(tmp_path)
    seen = _count_stagings(monkeypatch)
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 3
    assert image_slots.stage_replacements(slots, {}, assets_dir=assets) == (3, [])
    assert len(seen) == 3
    # the next Start: nothing due, nothing converted, all three still applied
    said = []
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 0
    assert image_slots.stage_replacements(
        slots, {}, assets_dir=assets, log_cb=lambda t, l="info": said.append(t)) == (3, [])
    assert len(seen) == 3
    assert said == ["3 picture(s) left as they are: an earlier build converted them "
                    "just as this one would."]


def test_a_changed_profile_or_a_touched_file_converts_again(tmp_path, monkeypatch):
    from pinball_decryptor.core import colour_profile as cp
    from pinball_decryptor.core import image_slots
    assets, slots = _pictures(tmp_path)
    seen = _count_stagings(monkeypatch)
    image_slots.stage_replacements(slots, {}, assets_dir=assets)
    # a picture written over since (a revert, an edit): that one again
    with open(slots["images/b.png"].abs_path, "ab") as f:
        f.write(b"\0")
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 1
    image_slots.stage_replacements(slots, {}, assets_dir=assets)
    assert seen[3:] == ["images/b.png"]
    # another profile: every one again
    import dataclasses
    cp.store_asset_profile(assets, dataclasses.replace(dict(cp.PRESETS)["bw"],
                                                       brightness=1.2))
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 3
    image_slots.stage_replacements(slots, {}, assets_dir=assets)
    assert len(seen) == 7


def test_a_cancelled_start_keeps_what_it_converted(tmp_path, monkeypatch):
    from pinball_decryptor.core import image_slots
    assets, slots = _pictures(tmp_path)
    seen = _count_stagings(monkeypatch)
    image_slots.stage_replacements(slots, {}, assets_dir=assets,
                                   cancel_cb=lambda: len(seen) >= 2)
    assert len(seen) == 2
    assert image_slots.pictures_due(slots, {}, assets_dir=assets) == 1


# -- the app's loop while a staging floods it --------------------------------

def _stub(window_append, turn_s):
    from pinball_decryptor.app import App
    after = []
    stub = types.SimpleNamespace(
        msg_queue=queue.Queue(), POLL_TURN_S=turn_s, _active_mode=None,
        _current_mfr=None, _poll_queue=lambda: None,
        window=types.SimpleNamespace(append_log=window_append),
        root=types.SimpleNamespace(after=lambda ms, fn: after.append(ms)))
    return App, stub, after


def test_a_turn_ends_while_the_queue_is_still_being_filled():
    """The worker refills the queue faster than the loop hands lines on: the turn
    used to run until it was empty, which it never was."""
    calls = []

    def append(text, level):
        calls.append(text)
        time.sleep(0.002)
        if len(calls) < 1000:      # a turn that never ends fails, not hangs
            stub.msg_queue.put(LogMsg("more %d" % len(calls), "info"))

    App, stub, after = _stub(append, 0.05)
    stub.msg_queue.put(LogMsg("first", "info"))
    t0 = time.monotonic()
    App._poll_queue(stub)
    took = time.monotonic() - t0
    assert took < 1.0, took
    assert calls and after == [0]          # straight back, after the others' turn
    assert not stub.msg_queue.empty()


def test_a_turn_that_empties_the_queue_waits_as_before():
    App, stub, after = _stub(lambda text, level: None, 0.05)
    for i in range(20):
        stub.msg_queue.put(LogMsg("line %d" % i, "info"))
    App._poll_queue(stub)
    assert stub.msg_queue.empty() and after == [100]


def test_a_turns_log_lines_reach_the_files_in_one_write(monkeypatch):
    raw = []
    monkeypatch.setattr(session_log, "_append_raw", raw.append)
    App, stub, after = _stub(lambda text, level: session_log.append(text, level), 5.0)
    for i in range(50):
        stub.msg_queue.put(LogMsg("Staging picture %d" % i, "info"))
    App._poll_queue(stub)
    assert len(raw) == 1 and raw[0].count("\n") == 50
    assert raw[0].index("picture 3\n") < raw[0].index("picture 40\n")


# -- the session log's batch -------------------------------------------------

def test_batched_writes_once_and_a_nested_block_flushes(monkeypatch):
    raw = []
    monkeypatch.setattr(session_log, "_append_raw", raw.append)
    with session_log.batched():
        session_log.append("one")
        with session_log.batched():          # a question pumping the loop
            session_log.append("two")
        assert len(raw) == 1 and "one" in raw[0] and "two" in raw[0]
        session_log.append("three")
        assert len(raw) == 1
    assert len(raw) == 2 and "three" in raw[1]
    session_log.append("four")                # no block: at once, as always
    assert len(raw) == 3


def test_another_threads_lines_are_not_held(monkeypatch):
    raw = []
    monkeypatch.setattr(session_log, "_append_raw", raw.append)
    with session_log.batched():
        t = threading.Thread(target=session_log.append, args=("worker",))
        t.start()
        t.join()
        assert len(raw) == 1 and "worker" in raw[0]


def test_a_project_switch_writes_the_held_lines_to_the_old_project(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    session_log.set_project(str(a))
    with session_log.batched():
        session_log.append("for a")
        session_log.set_project(str(b))
        session_log.append("for b")
    log_a = (a / "logs" / "project.log").read_text(encoding="utf-8")
    log_b = (b / "logs" / "project.log").read_text(encoding="utf-8")
    assert "for a" in log_a and "for b" not in log_a
    assert "for b" in log_b and "for a" not in log_b
