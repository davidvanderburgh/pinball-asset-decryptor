"""PAD-467: a Spike 2 build made as small as it can be (card_size.fit_image).

A finished image still carries every free block of its games partition, so it
is bigger than the card needs to be to keep, share or flash.  fit_layout works
out the shortest table that keeps FIT_SPARE free, and fit_image is PAD-465's
shrink to that length.  The arithmetic is pinned on the real figures of three
cards; the byte moves are exercised on the sparse synthetic cards of
test_stern_card_size, with resize2fs, e2fsck and the reads of the games
partition stood in for (the real ones ran end to end on a copy of a Godzilla
Premium 1.16 retheme, see the ticket).
"""

import os

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.plugins.stern import engine
from tests.test_stern_card_size import _read, make_card
from tests.test_stern_card_size_small import (BOND_PRO_106, SMALL_TABLE,
                                              _FakeShrink, _stub_reads)

#: the games partitions of a stock Godzilla Pro 1.16 (352 MB free) and of a
#: user's Godzilla Premium 1.16 retheme built at Stern's 8 GB size (2.18 GB
#: free), read off the real images; both have 2215 inodes in use
GZ_PRO_116 = BOND_PRO_106._replace(blocks=1675263, free=89975,
                                   inodes_per_group=8064, reserved_gdt=408)
GZ_RETHEME = GZ_PRO_116._replace(free=532955)
GZ_INODES = 2215
BOND_INODES = 5539


def _layout(cls):
    p3c, p4s = {"8G": (13402110, 14114816), "16G": (28311550, 29024256),
                "16S": SMALL_TABLE}[cls]
    laid = cs.LAYOUT_SIZES[cls]
    return cs.Layout(laid, laid, p3c, p4s, 1239038,
                     [(p4s, p4s + 2048, 147454),
                      (p4s + 149502, p4s + 149504, 1089534)])


def test_the_fit_of_three_real_cards():
    # the retheme: 7.86 GB down to 5.93 GB, 256 MiB left usable
    new = cs.fit_layout(_layout("8G"), GZ_RETHEME, GZ_INODES)
    assert (new.size, new.p3_count, new.p4_start) == (
        5931794432, 9633790, 10346496)
    assert new.size == new.laid_out
    assert new.p4_count == 1239038
    assert new.logicals == [(10346496, 10348544, 147454),
                            (10495998, 10496000, 1089534)]
    # Bond Pro 1.06 at Stern's 16 GB size: 15.49 GB down to 10.65 GB
    bond = cs.fit_layout(_layout("16G"), BOND_PRO_106, BOND_INODES)
    assert bond.size == 10651435008
    # a stock Godzilla Pro has 352 MB free: less than FIT_MIN_CUT comes off
    assert cs.fit_layout(_layout("8G"), GZ_PRO_116, GZ_INODES) is None
    small = cs.fit_layout(_layout("8G"), GZ_PRO_116, GZ_INODES, min_cut=0)
    assert 0 < cs.LAYOUT_SIZES["8G"] - small.size < cs.FIT_MIN_CUT


@pytest.mark.parametrize("space,cls,inodes", [
    (GZ_RETHEME, "8G", GZ_INODES), (BOND_PRO_106, "16G", BOND_INODES),
    (GZ_PRO_116, "8G", GZ_INODES)])
def test_the_fit_is_the_shortest_that_keeps_the_spare(space, cls, inodes):
    """On a whole MiB, with FIT_SPARE usable; one MiB shorter has less."""
    old = _layout(cls)
    new = cs.fit_layout(old, space, inodes, min_cut=0)
    assert new.p4_start % cs.ALIGN == 0
    assert new.p4_start - new.p3_count == old.p4_start - old.p3_count

    def usable(p3c):
        return cs.usable_blocks(space, p3c * 512 // 4096) * 4096
    assert usable(new.p3_count) >= cs.FIT_SPARE
    assert usable(new.p3_count - cs.ALIGN) < cs.FIT_SPARE


def test_the_inodes_in_use_have_to_fit_the_groups_kept():
    """A card whose files are many and small: the groups kept must hold
    their inodes, whatever room the blocks leave."""
    few = cs.fit_layout(_layout("8G"), GZ_RETHEME, GZ_INODES)
    many = cs.fit_layout(_layout("8G"), GZ_RETHEME, 8064 * 45)
    assert many.p3_count > few.p3_count
    assert (many.p3_count * 512 // 4096) // 32768 >= 45 - 1


def test_a_card_too_full_to_keep_the_spare_has_no_fit():
    full = GZ_PRO_116._replace(free=1000)
    assert cs.fit_layout(_layout("8G"), full, GZ_INODES, min_cut=0) is None


def test_the_option(monkeypatch):
    monkeypatch.delenv(cs.FIT_ENV, raising=False)
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    assert cs.fit_requested() is False
    monkeypatch.setenv(cs.FIT_ENV, "1")
    assert cs.fit_requested() is cs.supported()
    monkeypatch.setenv(cs.FIXED_ENV, "1")          # a port's chain
    assert cs.fit_requested() is False
    monkeypatch.delenv(cs.FIXED_ENV)
    monkeypatch.setattr(cs, "supported", lambda: False)    # macOS
    assert cs.fit_requested() is False


def test_fit_refusal_names_the_card_it_cant_make_smaller(tmp_path):
    good = make_card(tmp_path / "g.raw", "8G", marks=False)
    assert cs.fit_refusal(str(good)) == ""
    multi = make_card(tmp_path / "m.raw", "8G", extra_logical=True,
                      marks=False)
    assert cs.fit_refusal(str(multi)).startswith(
        "this card can't be made smaller: it has more than two logical "
        "partitions")
    junk = tmp_path / "j.raw"
    junk.write_bytes(b"\0" * 4096)
    assert cs.fit_refusal(str(junk)) == ("this card can't be made smaller: "
                                         "it has no partition table")
    assert cs.fit_refusal(str(tmp_path / "gone.raw")).startswith(
        "the original can't be read")


@pytest.fixture()
def fit_reads(monkeypatch):
    """fit_image's reads of the games partition, stood in for: the
    retheme's figures, and shrink_image's file reads (_stub_reads)."""
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    _FakeShrink.calls = []
    seen = _stub_reads(monkeypatch)
    monkeypatch.setattr(cs, "read_space", lambda p: GZ_RETHEME)
    monkeypatch.setattr(cs, "p3_space", lambda reader: GZ_RETHEME)
    monkeypatch.setattr(cs, "inodes_used", lambda reader: GZ_INODES)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)
    return seen


def _regions(path, lay):
    return {"head": _read(path, 0, 512 * 3),
            "ebr1": _read(path, lay.p4_start * 512, 2048 * 512 + 512),
            "p6": _read(path, lay.logicals[1][1] * 512, 512),
            "tail": _read(path, lay.laid_out - 1024, 1024)}


def test_fit_moves_the_data_partitions_up_and_cuts_the_file(tmp_path,
                                                            fit_reads):
    path = make_card(tmp_path / "c.raw", "8G")
    with open(path, "rb") as f:
        old = cs.read_layout(f)
    was = _regions(path, old)
    lines = []

    assert cs.fit_image(str(path), epoch=9,
                        log=lambda m, k="": lines.append((k, m))) is True

    assert os.path.getsize(path) == 5931794432
    with open(path, "rb") as f:
        with pytest.raises(cs.CardSizeError, match="not one of Stern's"):
            cs.read_layout(f)
        new = cs.read_layout(f, any_size=True)
    assert (new.p3_count, new.p4_start) == (9633790, 10346496)
    now = _regions(path, new)
    assert now["ebr1"] == was["ebr1"]
    assert now["p6"] == was["p6"]
    assert now["tail"] == was["tail"]
    # one resize: the loop bounded to the partition as it WAS
    assert _FakeShrink.calls == [(str(path), 712704 * 512, 13402110 * 512,
                                  9633790 * 512, 9)]
    assert fit_reads == [9633790 * 512 // 4096] * 2
    assert lines[0][1].startswith(
        "Making the image as small as it can be: the games partition shrinks "
        "from 6.86 GB to 4.93 GB with 269 MB of it left free")
    assert lines[0][1].endswith("The image comes out 5.93 GB instead of "
                                "7.86 GB.")
    assert lines[-1][0] == "success"
    assert lines[-1][1].startswith("The image is as small as it can be now")


def test_a_cut_shorter_than_the_data_partitions_moves_them_front_to_back(
        tmp_path, fit_reads, monkeypatch):
    """64 MiB off: the new place of /data and /dump overlaps the old one."""
    path = make_card(tmp_path / "c.raw", "8G")
    with open(path, "rb") as f:
        old = cs.read_layout(f)
    cut = 64 * cs.ALIGN
    short = old._replace(
        size=old.laid_out - cut * 512, laid_out=old.laid_out - cut * 512,
        p3_count=old.p3_count - cut, p4_start=old.p4_start - cut,
        logicals=[(e - cut, s - cut, c) for e, s, c in old.logicals])
    monkeypatch.setattr(cs, "fit_layout", lambda *a, **k: short)
    n = old.laid_out - old.p4_start * 512
    assert short.p4_start * 512 + n > old.p4_start * 512     # overlaps
    was = _regions(path, old)
    copies = []
    monkeypatch.setattr(cs, "_copy_range",
                        lambda *a: copies.append(a))         # never used
    assert cs.fit_image(str(path)) is True
    assert copies == []
    assert os.path.getsize(path) == short.size
    now = _regions(path, short)
    assert (now["ebr1"], now["p6"], now["tail"]) == (
        was["ebr1"], was["p6"], was["tail"])
    with open(path, "rb") as f:
        assert cs.read_layout(f, any_size=True) == short


def test_move_down_catches_a_copy_that_reads_back_wrong(tmp_path,
                                                        monkeypatch):
    path = tmp_path / "x.bin"
    path.write_bytes(bytes(range(256)) * 64)
    digests = iter([b"a", b"b"])
    monkeypatch.setattr(cs, "_range_digest", lambda f, off, n: next(digests))
    with open(path, "r+b") as f:
        with pytest.raises(cs.CardSizeError, match="did not read back"):
            cs._move_down(f, 4096, 1024, 8192)


def test_move_down_moves_overlapping_bytes(tmp_path):
    data = os.urandom(3 * cs.CHUNK + 777)
    path = tmp_path / "x.bin"
    path.write_bytes(b"\0" * 1000 + data)
    with open(path, "r+b") as f:
        cs._move_down(f, 1000, 10, len(data))
    assert path.read_bytes()[10:10 + len(data)] == data


def test_nothing_worth_taking_off_leaves_the_card(tmp_path, fit_reads,
                                                  monkeypatch):
    monkeypatch.setattr(cs, "p3_space", lambda reader: GZ_PRO_116)
    path = make_card(tmp_path / "c.raw", "8G", marks=False)
    lines = []
    assert cs.fit_image(str(path),
                        log=lambda m, k="": lines.append(m)) is False
    assert os.path.getsize(path) == cs.CARD_SIZES["8G"]
    assert _FakeShrink.calls == []
    assert lines == [
        "The image is about as small as it can be already: its games "
        "partition has 352 MB free and keeps 268 MB of it, so there is less "
        "than 134 MB to take off."]


def test_a_file_longer_than_its_table_is_still_cut_to_it(tmp_path, fit_reads,
                                                         monkeypatch):
    monkeypatch.setattr(cs, "p3_space", lambda reader: GZ_PRO_116)
    path = make_card(tmp_path / "c.raw", "8G", marks=False)
    with open(path, "r+b") as f:
        f.seek(cs.CARD_SIZES["8G"] + (1 << 20) - 1)
        f.write(b"\1")
    assert cs.fit_image(str(path)) is False
    assert os.path.getsize(path) == cs.CARD_SIZES["8G"]


def test_a_build_for_the_smaller_16g_card_never_comes_out_longer(
        tmp_path, fit_reads, monkeypatch):
    """Bond with 4.4 GB added: its fit is longer than the smaller 16 GB
    card, which the build was asked for, so that is the shrink made."""
    fuller = BOND_PRO_106._replace(free=BOND_PRO_106.free - 1100000)
    monkeypatch.setattr(cs, "p3_space", lambda reader: fuller)
    monkeypatch.setattr(cs, "read_space", lambda p: BOND_PRO_106)
    monkeypatch.setattr(cs, "inodes_used", lambda reader: BOND_INODES)
    path = make_card(tmp_path / "c.raw", "16G", marks=False)
    assert cs.fit_layout(_layout("16G"), fuller, BOND_INODES).p4_start > \
        SMALL_TABLE[1]
    assert cs.fit_image(str(path), "16S") is True
    assert os.path.getsize(path) == cs.LAYOUT_SIZES["16S"]
    # with room to spare, the fit is the smaller one
    path2 = make_card(tmp_path / "d.raw", "16G", marks=False)
    monkeypatch.setattr(cs, "p3_space", lambda reader: BOND_PRO_106)
    assert cs.fit_image(str(path2), "16S") is True
    assert os.path.getsize(path2) == 10651435008


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------

def test_a_build_made_as_small_as_it_can_be_is_always_whole(tmp_path,
                                                            monkeypatch):
    card = make_card(tmp_path / "c.raw", "8G", marks=False)
    out = tmp_path / "out.raw"
    out.write_bytes(b"\0" * 4096)
    for var in (cs.ENV, cs.FIXED_ENV, cs.FIT_ENV):
        monkeypatch.delenv(var, raising=False)

    def reason(**kw):
        prev = engine._build_record(str(card), str(out), str(tmp_path), [],
                                    {}, {}, True, **kw)
        return engine.build_update_reason(prev, str(card), str(out),
                                          str(tmp_path))
    assert reason() is None             # an ordinary build updates in place
    assert reason(fit=True) == ("the last build here was made as small as "
                                "it could be")
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.setenv(cs.FIT_ENV, "1")
    assert reason() == ("a build made as small as it can be is always made "
                        "from the original")


def test_the_record_says_whether_it_was(tmp_path):
    out = tmp_path / "out.raw"
    out.write_bytes(b"\0" * 4096)
    assert engine._fitted(str(out), True) is True
    assert engine._fitted(str(out), False) is False
    big = make_card(tmp_path / "b.raw", "8G", marks=False)
    assert engine._fitted(str(big), True) is False      # nothing came off
    rec = engine._build_record(str(big), str(big), str(tmp_path), [], {}, {},
                               True, fit=True)
    assert rec["fit"] is True
    assert "fit" not in engine._build_record(str(big), str(big),
                                             str(tmp_path), [], {}, {}, True)


def test_a_card_that_cant_be_made_smaller_is_built_at_its_size(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cs.FIT_ENV, "1")
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.setattr(cs, "_E2fs", _FakeShrink)
    multi = make_card(tmp_path / "m.raw", "8G", extra_logical=True,
                      marks=False)
    lines = []
    assert engine._fit_asked(str(multi),
                             lambda m, k="": lines.append((k, m))) is False
    assert lines[0][0] == "warning"
    assert lines[0][1].startswith("Make the image as small as it can be: "
                                  "this card can't be made smaller")
    assert lines[0][1].endswith(", so the image keeps its size.")
    good = make_card(tmp_path / "g.raw", "8G", marks=False)
    lines = []
    assert engine._fit_asked(str(good),
                             lambda m, k="": lines.append((k, m))) is True
    assert lines == [("info", "Make the image as small as it can be: once "
                      "everything is on the card, its games partition is cut "
                      "down to what it holds, with 268 MB of it left free, "
                      "and the image is cut with it.")]

    class NoTools:
        def __init__(self):
            raise cs.CardSizeError("the Linux this app uses can't attach "
                                   "the card image as a disk (no loop "
                                   "devices)")
    monkeypatch.setattr(cs, "_E2fs", NoTools)
    lines = []
    assert engine._fit_asked(str(good),
                             lambda m, k="": lines.append((k, m))) is False
    assert "this computer can't: the Linux this app uses" in lines[0][1]


def test_a_failed_fit_discards_the_build(tmp_path, monkeypatch):
    class Failing(_FakeShrink):
        rcs = {"resize": 1}
    monkeypatch.setattr(cs, "_E2fs", Failing)
    _stub_reads(monkeypatch)
    monkeypatch.setattr(cs, "read_space", lambda p: GZ_RETHEME)
    monkeypatch.setattr(cs, "p3_space", lambda reader: GZ_RETHEME)
    monkeypatch.setattr(cs, "inodes_used", lambda reader: GZ_INODES)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)
    monkeypatch.setattr("pinball_decryptor.core.ext4_grow.partition_epoch",
                        lambda *a: 5)
    gone = []
    monkeypatch.setattr(engine, "_discard_output", gone.append)
    orig = make_card(tmp_path / "o.raw", "8G", marks=False)
    out = make_card(tmp_path / "b.raw", "8G", marks=False)
    with pytest.raises(cs.CardSizeError,
                       match="The image could not be made as small as it can "
                             "be, so nothing was built: the games partition "
                             "could not be made smaller"):
        engine._shrink_card(str(orig), str(out), None, lambda *a: None,
                            lambda: False, fit=True)
    assert gone == [str(out)]
