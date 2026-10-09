"""PAD-465: building a Spike 2 card for a smaller 16 GB SD card (card_size.py).

Stern's 16 GB image (15,494,807,552 bytes) doesn't fit every SD card sold as
16 GB.  "16S" is the same layout with the games partition five block groups
shorter: a 16 GB card is made smaller for it (shrink_image), an 8 GB card
grows to it like to any other size.  The byte move is exercised on the sparse
synthetic cards of test_stern_card_size; resize2fs, e2fsck and the reads of
the games partition are stood in for (the real ones ran end to end on James
Bond Pro 1.06, whose figures are pinned here).
"""

import collections
import os

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from tests.test_stern_card_size import _FakeE2fs, _read, make_card

#: (p3 count, p4 start) of the smaller 16 GB card: Stern's 16 GB table less
#: five 128 MiB block groups
SMALL_TABLE = (28311550 - 1310720, 29024256 - 1310720)
#: James Bond Pro 1.06's games partition, read off the stock image, and the
#: free blocks it had after a real shrink to "16S" (210 files moved).
BOND_PRO_106 = cs.P3Space(block_size=4096, blocks=3538943, free=1233230,
                          r_blocks=0, blocks_per_group=32768,
                          inodes_per_group=8192, inode_size=256,
                          reserved_gdt=863, first_data_block=0, desc_size=32,
                          sparse_super=True, meta_bg=False)
BOND_SHRUNK_FREE = 1071958


def test_the_smaller_16g_card_is_sterns_16g_with_a_shorter_games_partition(
        tmp_path):
    assert cs.LAYOUT_SIZES["16S"] == 14823718912
    assert list(cs.LAYOUT_SIZES) == ["8G", "16S", "16G", "32G"]
    with open(make_card(tmp_path / "c.raw", "16G", marks=False), "rb") as f:
        lay = cs.read_layout(f)
    assert cs.shrinks(lay, "16S")
    delta, new = cs.plan(lay, "16S")
    assert delta == -1310720
    assert (new.p3_count, new.p4_start) == SMALL_TABLE
    assert new.size == new.laid_out == cs.LAYOUT_SIZES["16S"]
    assert new.p4_count == lay.p4_count
    assert new.logicals == [(e - 1310720, s - 1310720, c)
                            for e, s, c in lay.logicals]
    # the moved partitions never overlap their old place
    n = lay.laid_out - lay.p4_start * 512
    assert new.p4_start * 512 + n <= lay.p4_start * 512
    assert cs.layout_class(new.laid_out) == "16S"
    assert cs.class_of(new.laid_out) is None      # never one of Stern's own


def test_only_a_16g_card_is_made_smaller(tmp_path):
    with open(make_card(tmp_path / "8.raw", "8G", marks=False), "rb") as f:
        l8 = cs.read_layout(f)
    with open(make_card(tmp_path / "32.raw", "32G", marks=False), "rb") as f:
        l32 = cs.read_layout(f)
    delta, new = cs.plan(l8, "16S")              # an 8 GB card grows to it
    assert delta > 0 and (new.p3_count, new.p4_start) == SMALL_TABLE
    assert not cs.shrinks(l8, "16S")
    assert cs.plan(l32, "16S") == (0, l32)       # and nothing else shrinks
    assert not cs.shrinks(l32, "16S")
    assert cs.p3_blocks_at(l32, "16S", 4096) is None
    assert cs.shrinks_card(str(tmp_path / "32.raw"), "16S") is False
    assert cs.shrinks_card(str(tmp_path / "nothing.raw"), "16S") is False


def test_the_option_and_its_words(monkeypatch):
    monkeypatch.setenv(cs.ENV, " 16s ")
    assert cs.requested() == "16S"
    assert cs.words("16S") == "smaller 16 GB"
    assert cs.words("16G") == "16 GB"


def test_shrunk_is_what_resize2fs_did_to_bond_pro():
    """The arithmetic against a real shrink: never more free than there was,
    and no more than the slack under it."""
    blocks, free, r = cs.shrunk(BOND_PRO_106, 3375103)
    assert (blocks, r) == (3375103, 0)
    assert free <= BOND_SHRUNK_FREE
    assert BOND_SHRUNK_FREE - free <= cs._SHRINK_SLACK + 8
    # what the Write tab quotes: the kernel's reserve off too
    assert cs.usable_blocks(BOND_PRO_106, 3375103) == free - 4096
    # a partition shorter than what it holds (2.3 M blocks) can't take it
    assert cs.shrunk(BOND_PRO_106, 2000000)[1] < 0
    assert cs.usable_blocks(BOND_PRO_106, 2000000) == 0


def test_the_smaller_card_is_never_suggested():
    room = collections.OrderedDict([("16S", 10 ** 9), ("16G", 2 * 10 ** 9),
                                    ("32G", 9 * 10 ** 9)])
    assert cs.smallest_fit(5 * 10 ** 8, room) == "16G"
    assert cs.smallest_fit(5 * 10 ** 8, room, above="16S") == "16G"
    assert cs.smallest_fit(5 * 10 ** 8, room, above="16G") == "32G"
    # out of room on the smaller card: one click to Stern's own 16 GB size,
    # which needs a card that holds Stern's image
    refusal = cs.WontFit(3 * 10 ** 9, 10 ** 9, fits="16G",
                         fits_room=2 * 10 ** 9, current="16S")
    assert cs.bigger_card_offer(refusal) == (
        ("16S", "16G") if cs.supported() else None)
    q = cs.offer_question("16S", "16G")
    assert q.startswith("Your assets no longer fit on a smaller 16 GB SD card.")
    assert "has to hold a 15.49 GB image." in q
    assert cs.offer_question("8G", "16G").endswith("has to be 16 GB or bigger.")


def test_target_for_the_smaller_card_needs_room_for_what_the_card_holds(
        tmp_path, monkeypatch):
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.CardSizeError, match="games partition can't be read"):
        cs.target_for(str(path), "16S")
    monkeypatch.setattr(cs, "p3_space", lambda reader: BOND_PRO_106)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)
    assert cs.target_for(str(path), "16S") == "16S"
    full = BOND_PRO_106._replace(free=100000)       # 3.7 GB short of it
    monkeypatch.setattr(cs, "p3_space", lambda reader: full)
    with pytest.raises(cs.CardSizeError,
                       match="for a smaller 16 GB SD card: its games "
                             "partition already holds 14.09 GB"):
        cs.target_for(str(path), "16S")


class _FakeShrink(_FakeE2fs):
    calls = []

    def shrink(self, image_path, offset, size, new_size, epoch=None,
               timeout=0):
        _FakeShrink.calls.append((image_path, offset, size, new_size, epoch))
        return self.grow(image_path, offset, size)


def _stub_reads(monkeypatch, tail=None, after=None, sizes_after=None):
    """The games-partition reads shrink_image makes, stood in for (the
    synthetic card has no filesystem): the files past the new end and their
    digests, as read before and after.  Returns the block counts asked."""
    tail = {"/game/x.asset": (5, "d1")} if tail is None else tail
    sizes = {"/game/x.asset": 5, "/game/y.bin": 9}
    seen = []

    def files_and_tail(path, blocks, cancel, hash_tail=True):
        seen.append(blocks)
        if hash_tail:
            return dict(sizes), dict(tail)
        return dict(sizes if sizes_after is None else sizes_after), {}
    monkeypatch.setattr(cs, "_files_and_tail", files_and_tail)
    monkeypatch.setattr(cs, "_digest", lambda path, rels, cancel: dict(
        tail if after is None else after))
    monkeypatch.setattr(cs, "read_space", lambda p: BOND_PRO_106)
    return seen


def test_shrink_moves_the_data_partitions_back_and_cuts_the_file(
        tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _FakeShrink.calls = []
    seen = _stub_reads(monkeypatch)
    path = make_card(tmp_path / "c.raw", "16G")
    with open(path, "rb") as f:
        old = cs.read_layout(f)
    head = {"boot": _read(path, 0, 440), "p1p2": _read(path, 446, 32),
            "p3": _read(path, 712704 * 512, 512)}
    region_head = _read(path, old.p4_start * 512, 2048 * 512 + 512)
    p6_head = _read(path, old.logicals[1][1] * 512, 512)
    tail = _read(path, old.laid_out - 1024, 1024)
    lines = []

    assert cs.shrink_image(str(path), "16S", epoch=7,
                           log=lambda m, k="": lines.append((k, m))) is True

    assert os.path.getsize(path) == cs.LAYOUT_SIZES["16S"]
    with open(path, "rb") as f:
        new = cs.read_layout(f)
    assert (new.p3_count, new.p4_start) == SMALL_TABLE
    # nothing before the games partition's end moved
    assert _read(path, 0, 440) == head["boot"]
    assert _read(path, 446, 32) == head["p1p2"]
    assert _read(path, 712704 * 512, 512) == head["p3"]
    # the EBRs, /data and /dump and the tail moved verbatim
    assert _read(path, new.p4_start * 512, len(region_head)) == region_head
    assert _read(path, new.logicals[1][1] * 512, 512) == p6_head
    assert _read(path, new.laid_out - 1024, 1024) == tail
    # one resize of p3: the loop bounded to the partition as it WAS, the
    # filesystem made the new length, the clock pinned
    assert _FakeShrink.calls == [(str(path), 712704 * 512, 28311550 * 512,
                                  SMALL_TABLE[0] * 512, 7)]
    # the files past the new end (block 3375103) were read before and after
    assert seen == [3375103, 3375103]
    assert lines[-1][0] == "success"
    assert "1 file(s) moved further in and read back the same" in lines[-1][1]
    assert "The image comes out 14.82 GB." in lines[0][1]


def test_shrink_is_a_no_op_for_any_other_card(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _FakeShrink.calls = []
    for cls in ("8G", "32G"):
        path = make_card(tmp_path / (cls + ".raw"), cls, marks=False)
        assert cs.shrink_image(str(path), "16S") is False
        assert os.path.getsize(path) == cs.CARD_SIZES[cls]
    assert _FakeShrink.calls == []


@pytest.mark.parametrize("step,rc,words", [
    ("fsck", 4, "failed its check before shrinking"),
    ("resize", 1, "could not be made smaller"),
    ("check", 4, "smaller games partition did not check clean"),
])
def test_a_failed_shrink_leaves_the_table_as_it_was(tmp_path, monkeypatch,
                                                    step, rc, words):
    class Failing(_FakeShrink):
        rcs = {step: rc}
    monkeypatch.setattr(cs, "_E2fs", Failing)
    _stub_reads(monkeypatch)
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.CardSizeError, match=words):
        cs.shrink_image(str(path), "16S")
    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]
    with open(path, "rb") as f:
        assert cs.read_layout(f).p3_count == 28311550


def test_a_moved_file_that_reads_back_wrong_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _stub_reads(monkeypatch, after={"/game/x.asset": (5, "XX")})
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.CardSizeError,
                       match="/game/x.asset did not read back the same"):
        cs.shrink_image(str(path), "16S")


def test_a_file_gone_after_the_shrink_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _stub_reads(monkeypatch, sizes_after={"/game/x.asset": 5})
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.CardSizeError, match=r"not all there.*/game/y.bin"):
        cs.shrink_image(str(path), "16S")


def test_a_cancel_before_the_resize_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _FakeShrink.calls = []
    _stub_reads(monkeypatch)
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.Cancelled):
        cs.shrink_image(str(path), "16S", cancel=lambda: True)
    assert _FakeShrink.calls == []
    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]


def test_the_shrink_runner_bounds_the_loop_to_the_old_partition():
    shipped = []

    class Ex:
        def to_exec_path(self, p):
            return p

        def run(self, cmd, timeout=0):
            import base64
            import shlex
            tmp = shlex.split(cmd.split("<", 1)[1].split("|", 1)[0])[0]
            with open(tmp, "rb") as fh:
                shipped.append(base64.b64decode(fh.read()).decode())
            return "PAD_E2 loop 0\n"
    e2 = cs._E2fs.__new__(cs._E2fs)
    e2.ex = Ex()
    e2.shrink("C:/x/card.raw", 364904448, 28311550 * 512,
              SMALL_TABLE[0] * 512, epoch=5)
    [script] = shipped
    assert ("losetup -f --show -o 364904448 --sizelimit %d" % (28311550 * 512)
            in script)
    # forced: resize2fs's own minimum is about 2 GB over what is in use on
    # Stern's 16 GB cards (see _E2fs.shrink); shrink_image checks the room
    assert 'resize2fs -f "$L" %ds' % SMALL_TABLE[0] in script
    assert 'e2fsck -fp "$L"' in script and 'e2fsck -fn "$L"' in script
    assert "E2FSCK_TIME=5" in script and "?offset" not in script
    # ...and a grow never is
    shipped.clear()
    e2.grow("C:/x/card.raw", 364904448, 28311550 * 512)
    assert 'resize2fs "$L" 28311550s' in shipped[0]
    assert "resize2fs -f" not in shipped[0]


def test_a_build_too_full_for_the_smaller_card_is_refused_untouched(
        tmp_path, monkeypatch):
    """The room checked on the finished build, before the resize: a build
    that put more on the games partition than the smaller card holds (with
    the kernel's 16 MB to spare) is refused in words, the card as it was."""
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _FakeShrink.calls = []
    _stub_reads(monkeypatch)
    # Bond with 4.37 GB more on it: 1,000 blocks short of the 4,096 to spare
    _blocks, free, _r = cs.shrunk(BOND_PRO_106, 3375103)
    full = BOND_PRO_106._replace(free=BOND_PRO_106.free - (free - 3096))
    monkeypatch.setattr(cs, "read_space", lambda p: full)
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    with pytest.raises(cs.CardSizeError,
                       match="what this build put on the games partition is "
                             "4.1 MB more than a smaller 16 GB SD card has "
                             "room for"):
        cs.shrink_image(str(path), "16S")
    assert _FakeShrink.calls == []
    assert os.path.getsize(path) == cs.CARD_SIZES["16G"]
    # exactly the room: it goes ahead
    room = BOND_PRO_106._replace(free=BOND_PRO_106.free - (free - 4096))
    monkeypatch.setattr(cs, "read_space", lambda p: room)
    assert cs.shrink_image(str(path), "16S") is True


def test_the_room_the_preflight_gives_is_the_room_the_shrink_takes():
    """A build the pre-flight lets use every usable block of the smaller card
    leaves exactly the headroom shrink_image asks for."""
    usable = cs.usable_blocks(BOND_PRO_106, 3375103)
    after = BOND_PRO_106._replace(free=BOND_PRO_106.free - usable)
    assert cs.shrunk(after, 3375103)[1] == cs._SHRINK_HEADROOM


def test_the_wontfit_from_the_smaller_card_names_the_image_size():
    e = cs.WontFit(3 * 10 ** 9, 10 ** 9, fits="16G", fits_room=5 * 10 ** 9,
                   current="16S", at="16S")
    assert ("Build it for a 16 GB SD card if the SD card in the machine "
            "holds a 15.49 GB image (SD card size on the Write tab: 5.00 GB "
            "free there).") in str(e)
    e8 = cs.WontFit(3 * 10 ** 9, 10 ** 9, fits="16G", fits_room=5 * 10 ** 9,
                    current="8G")
    assert "if the SD card in the machine is 16 GB or bigger" in str(e8)
