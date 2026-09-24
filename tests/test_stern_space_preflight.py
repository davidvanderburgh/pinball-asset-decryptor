"""PAD-176's pre-flight: a Spike 2 build whose whole-file copies can't fit
the card's games partition is refused BEFORE anything is encoded or written,
with the smallest SD card size it fits.  The card copy over the output starts
only once the build has been measured and fits, so a refusal leaves the build
already there as it was, and an update that fits only as a whole build from
the original is built from the original.

The free-space arithmetic is pinned to what resize2fs really did to Stern's
own cards (measured on the real images: godzilla_pro 1.16 8G and jaws_le 1.02
16G).  The pre-flight itself runs on a small real ext2 filesystem placed where
a Spike 2 card keeps its games partition, inside a sparse Stern-shaped card,
with every encode entry point stubbed to fail the test if it is reached.
"""

import os
import struct
import time
import wave

import pytest

from pinball_decryptor.core import ext4_grow
from pinball_decryptor.core import staged_changes
from pinball_decryptor.core import video
from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
from tests import synthetic

# ---------------------------------------------------------------------------
# What resize2fs 1.47 did to the stock cards' games partitions (e2e runs on
# the real images, 2026-09-23): (geometry, from class, to class, free blocks)
# ---------------------------------------------------------------------------
GZ_PRO_116 = dict(blocks=1675263, free=89975, ipg=8064, inode=256, bs=4096,
                  resv_gdt=408)
JAWS_LE_102 = dict(blocks=3538943, free=1543649, ipg=8192, inode=256,
                   bs=4096, resv_gdt=863)
MEASURED = [(GZ_PRO_116, "8G", "16G", 1924909),
            (GZ_PRO_116, "8G", "32G", 5497389),
            (JAWS_LE_102, "16G", "32G", 5114786)]
# Stern's tables: class -> (p3 sectors, p4 start)
TABLES = {"8G": (13402110, 14114816), "16G": (28311550, 29024256),
          "32G": (57343998, 58056704)}
P4_COUNT = 1239038
P3 = cs.P3_START * cs.SECTOR


def _space(g):
    return cs.P3Space(block_size=g["bs"], blocks=g["blocks"], free=g["free"],
                      r_blocks=0, blocks_per_group=32768,
                      inodes_per_group=g["ipg"], inode_size=g["inode"],
                      reserved_gdt=g["resv_gdt"], first_data_block=0,
                      desc_size=32, sparse_super=True, meta_bg=False)


def _layout(cls):
    p3c, p4s = TABLES[cls]
    return cs.Layout(cs.CARD_SIZES[cls], cs.CARD_SIZES[cls], p3c, p4s,
                     P4_COUNT, [(p4s, p4s + 2048, 147454),
                                (p4s + 149502, p4s + 149504, 1089534)])


@pytest.mark.parametrize("geo,src,dst,free", MEASURED)
def test_the_grow_arithmetic_is_resize2fs_to_the_block(geo, src, dst, free):
    space = _space(geo)
    nb = cs.p3_blocks_at(_layout(src), dst, space.block_size)
    blocks, got, r_blocks = cs.grown(space, nb)
    assert got == free
    assert blocks == nb and r_blocks == 0
    # the kernel keeps 4096 blocks back on the loop-mount route only
    assert cs.usable_blocks(space, nb, cs.ROUTE_MOUNT) == free - 4096
    assert cs.usable_blocks(space, nb, cs.ROUTE_PINNED) == free


def test_the_stock_godzilla_figures_the_plan_quotes():
    space = _space(GZ_PRO_116)
    room = cs.room_by_class(_layout("8G"), space, ["8G", "16G", "32G"])
    assert list(room) == ["8G", "16G", "32G"]
    # df's 352 MB (the superblock's 368 MB less the kernel's reserve), then
    # the plan's 7.87 GB and 22.50 GB
    assert room["8G"] == (89975 - 4096) * 4096 == 351760384
    assert [cs.size_words(n) for n in room.values()] == [
        "352 MB", "7.87 GB", "22.50 GB"]
    # the card as it is when it isn't grown, or asked for a smaller class
    assert cs.p3_blocks_at(_layout("16G"), "8G", 4096) is None
    assert cs.grown(space, None) == (1675263, 89975, 0)


def test_a_last_group_too_short_for_its_bookkeeping_is_left_off():
    space = _space(GZ_PRO_116)
    # 60 blocks into a new group: less than its bitmaps and inode table
    blocks, free, _r = cs.grown(space, 51 * 32768 + 32768 + 60)
    assert blocks == 52 * 32768
    assert cs.grown(space, 52 * 32768) == (blocks, free, 0)


def test_the_root_reserve_keeps_its_share_and_comes_off():
    space = _space(GZ_PRO_116)._replace(r_blocks=1675263 // 20)   # 5%
    nb = cs.p3_blocks_at(_layout("8G"), "16G", 4096)
    _b, free, r_blocks = cs.grown(space, nb)
    # resize2fs keeps the percentage, in its own double arithmetic
    assert r_blocks == int(space.r_blocks * 100.0 / space.blocks * nb / 100.0)
    assert r_blocks == 176946
    assert cs.usable_blocks(space, nb) == free - 4096 - r_blocks


def test_sizes_are_said_the_way_a_user_reads_them():
    assert [cs.size_words(n) for n in (22500528128, 351760384, 4_200_000,
                                       148_480, 400, 0)] == [
        "22.50 GB", "352 MB", "4.2 MB", "148 KB", "1 KB", "0 KB"]


def test_the_smallest_size_that_fits():
    room = cs.room_by_class(_layout("8G"), _space(GZ_PRO_116),
                            ["32G", "8G", "16G"])
    assert cs.smallest_fit(100 * 10**6, room) == "8G"
    assert cs.smallest_fit(1.61e9, room) == "16G"
    assert cs.smallest_fit(10e9, room) == "32G"
    assert cs.smallest_fit(30e9, room) is None
    # a build already at 16 GB is only ever pointed at something bigger
    assert cs.smallest_fit(1e9, room, above="16G") == "32G"


def test_candidates_are_the_originals_own_size_then_the_offered(tmp_path,
                                                               monkeypatch):
    monkeypatch.setattr(cs, "supported", lambda: True)
    c8 = _stern_card(tmp_path / "8.raw", _tiny_fs(), "8G")
    c16 = _stern_card(tmp_path / "16.raw", _tiny_fs(), "16G")
    assert cs.candidates(str(c8)) == ["8G", "16G", "32G"]
    assert cs.candidates(str(c16)) == ["16G", "32G"]
    monkeypatch.setattr(cs, "supported", lambda: False)
    assert cs.candidates(str(c8)) == ["8G"]


# ---------------------------------------------------------------------------
# The refusal's words
# ---------------------------------------------------------------------------

def test_the_refusal_names_the_size_that_fits_and_the_biggest_files():
    e = cs.WontFit(1_610_000_000, 351760384,
                   [(81_000_000, "big_loop2.mp4"),
                    (20_000_000, "the sound bank with the longer sounds"),
                    (0, "c.mp4")],
                   fits="16G", fits_room=7867650048)
    msg = str(e)
    assert isinstance(e, cs.CardSizeError)
    assert msg.startswith("This build needs 1.61 GB on the card's games "
                          "partition, which has 352 MB free, so the build was "
                          "stopped before anything was written to the card "
                          "image. Any replacements it converted first are "
                          "kept in the project.")
    # only a machine whose SD card is that big can take it (the copy-time
    # hint and the help say the same)
    assert (" Build it for a 16 GB SD card if the SD card in the machine is "
            "16 GB or bigger (SD card size on the Write tab: 7.87 GB free "
            "there). Otherwise take something out (fewer or smaller "
            "replacements).") in msg
    # the files by the names the user knows, one space between sentences
    assert msg.endswith(" Biggest: big_loop2.mp4 (+81 MB), the sound bank "
                        "with the longer sounds (+20 MB).")
    assert "  " not in msg
    assert "c.mp4" not in msg                   # nothing to gain there
    assert (e.need, e.avail, e.fits) == (1_610_000_000, 351760384, "16G")
    for word in ("16G ", "resize2fs", "e2fsck", "losetup", "mode", ".asset"):
        assert word not in msg


def test_the_refusal_when_even_the_biggest_size_is_too_small():
    msg = str(cs.WontFit(30e9, 7867650048, largest="32G",
                         largest_room=22500528128, at="16G"))
    assert "which has 7.87 GB free on a 16 GB SD card," in msg
    assert ("Even a 32 GB SD card has only 22.50 GB free there, so something "
            "has to come out") in msg
    assert "Build it for" not in msg


def test_the_refusal_says_where_the_build_stopped():
    """The Build's first step refuses before anything is converted; the
    engine's pre-flight comes after the Build converted what it had to, so
    it never claims nothing was encoded (the conversions are kept)."""
    early = str(cs.WontFit(400e6, 352e6, early=True))
    assert early.startswith("This build needs at least 400 MB on the card's "
                            "games partition, which has 352 MB free, so the "
                            "build was stopped before anything was converted "
                            "or written.")
    late = str(cs.WontFit(400e6, 352e6))
    assert late.startswith("This build needs 400 MB on the card's games "
                           "partition, which has 352 MB free, so the build "
                           "was stopped before anything was written to the "
                           "card image. Any replacements it converted first "
                           "are kept in the project.")
    for msg in (early, late):
        assert "encoded" not in msg and " more on the" not in msg


def test_a_refusal_at_the_limit_says_how_short_it_is():
    """Two figures that round to the same words would read as fitting."""
    msg = str(cs.WontFit(352_400_000, 352_200_000))
    assert ("needs 352 MB on the card's games partition, which has 352 MB "
            "free (200 KB short), so") in msg
    msg = str(cs.WontFit(7_874_000_000, 7_866_000_000, at="16G"))
    assert "which has 7.87 GB free on a 16 GB SD card (8.0 MB short)," in msg
    assert "short)" not in str(cs.WontFit(400e6, 352e6))


def test_a_floor_names_no_size_as_enough():
    """A refusal that couldn't size every clip (converted later) states its
    need as a floor and the size only as the smallest that could hold it."""
    msg = str(cs.WontFit(7e9, 352e6, fits="16G", fits_room=7.87e9,
                         early=True, uncounted=10))
    assert (" It may need more: 10 replaced video(s) can't be sized until "
            "the build converts them. Only a 16 GB SD card or bigger could "
            "hold it: if the SD card in the machine is that big, pick it "
            "under SD card size on the Write tab. Otherwise take something "
            "out (fewer or smaller replacements).") in msg
    assert "Build it for" not in msg and "free there" not in msg


def test_the_refusal_with_no_bigger_size_on_offer():
    msg = str(cs.WontFit(500e6, 351760384))
    assert "Something has to come out (fewer or smaller replacements)" in msg
    assert "SD card size" not in msg


def test_a_ports_refusal_never_points_at_a_size_the_port_ignores():
    """Port + build makes every card at its own original's size (app.py),
    so its refusal says to build that card on its own for the bigger size."""
    msg = str(cs.WontFit(1_610_000_000, 351760384, fits="16G",
                         fits_room=7867650048, fixed=True))
    assert ("If the SD card in that machine is 16 GB or bigger, build this "
            "card on its own from the Write tab for a 16 GB SD card (7.87 GB "
            "free there; a port builds every card at its original's size). "
            "Otherwise take something out") in msg
    assert "SD card size on the Write tab" not in msg


def test_the_port_flag_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    assert not cs.size_fixed()
    monkeypatch.setenv(cs.FIXED_ENV, "1")
    assert cs.size_fixed()
    assert cs.bigger_card("32G") == ("build it for a 32 GB SD card (SD card "
                                     "size on the Write tab)")


# ---------------------------------------------------------------------------
# A small real filesystem where a Spike 2 card keeps its games partition
# ---------------------------------------------------------------------------
BS = 1024                       # make_ext2_fs's block size
FS_BLOCKS = 512
GAME = "gz"
V1, V2 = GAME + "/assets/lcd/1.asset", GAME + "/assets/lcd/2.asset"
IMAGE = GAME + "/image.bin"
# the stock sound bank's header: its master directory at 0x800, 8 records
MD_OFF, COUNT = 0x800, 8


def _bank_header():
    h = bytearray(0x900)
    struct.pack_into("<I", h, 0x40, MD_OFF)
    struct.pack_into("<I", h, 0x60, COUNT)
    return bytes(h)


def _tiny_fs(free=200, sb_free=None, v1=3000, v2=3000):
    """A 512 KB ext2 with a Spike 2 game directory, its group descriptor
    saying *free* blocks are free (the superblock's own total says
    *sb_free*, stale), and every inode's i_blocks filled in."""
    fs = bytearray(synthetic.make_ext2_fs({
        IMAGE: _bank_header(),
        GAME + "/game": b"\x7fELF" + b"\x00" * 60,
        V1: b"V1" * (v1 // 2),
        V2: b"V2" * (v2 // 2),
    }, fs_blocks=FS_BLOCKS))
    for ino in range(1, 65):
        off = 3 * BS + (ino - 1) * 128
        mode, size = struct.unpack_from("<HxxI", fs, off)
        if mode & 0xF000 in (0x8000, 0x4000):
            struct.pack_into("<I", fs, off + 0x1C,
                             max(1, -(-size // BS)) * (BS // 512))
    struct.pack_into("<I", fs, 1024 + 0x0C,
                     free if sb_free is None else sb_free)
    struct.pack_into("<I", fs, 1024 + 0x64, 1)          # sparse_super
    struct.pack_into("<H", fs, 2 * BS + 0x0C, free)     # group 0's free count
    return bytes(fs)


def _stern_card(path, fs, cls="8G"):
    """A sparse card laid out exactly like Stern's *cls* card, *fs* as its
    games partition."""
    p3c, p4s = TABLES[cls]
    mbr = bytearray(512)
    mbr[446:462] = bytes.fromhex("00000140 0c0320bf 00200000 00400000")
    mbr[462:478] = bytes.fromhex("000001c0 8303e0ff 00600000 00800a00")
    mbr[478:494] = (bytes.fromhex("0003e0ff 8303e0ff 00e00a00")
                    + struct.pack("<I", p3c))
    mbr[494:510] = (bytes.fromhex("0003e0ff 0f03e0ff")
                    + struct.pack("<II", p4s, P4_COUNT))
    mbr[510:512] = b"\x55\xaa"
    with open(path, "wb") as f:
        cs._grow_file(f, 0, cs.CARD_SIZES[cls])
        f.seek(0)
        f.write(bytes(mbr))
        for ebr, raw in ((p4s, "0003e0ff 8303e0ff 00080000 fe3f0200"
                               "0003e0ff 0503e0ff fe470200 00a01000"),
                         (p4s + 149502, "0003e0ff 8303e0ff 02000000 "
                                        "fe9f1000")):
            sec = bytearray(512)
            body = bytes.fromhex(raw)
            sec[446:446 + len(body)] = body
            sec[510:512] = b"\x55\xaa"
            f.seek(ebr * 512)
            f.write(bytes(sec))
        f.seek(P3)
        f.write(fs)
    return path


def _parts():
    return [(P3, TABLES["8G"][0] * cs.SECTOR)]


def _snap(path):
    """The partition table and the games partition's filesystem."""
    with open(path, "rb") as f:
        mbr = f.read(512)
        f.seek(P3)
        return mbr + f.read(FS_BLOCKS * BS)


def test_free_space_is_the_group_descriptors_not_a_stale_superblock(tmp_path):
    card = _stern_card(tmp_path / "c.raw", _tiny_fs(free=200, sb_free=999))
    space = cs.read_space(str(card))
    assert (space.free, space.blocks, space.block_size) == (200, 512, 1024)
    assert space.sparse_super and not space.meta_bg
    # descriptors that can't be read: the superblock's total stands in
    short = tmp_path / "short.raw"
    with open(card, "rb") as f:
        f.seek(P3)
        head = f.read(2048)
    short.write_bytes(head)
    with open(short, "rb") as f:
        assert cs.p3_space(Ext4Reader(f, 0, 2048)).free == 999


# ---------------------------------------------------------------------------
# The pre-flight inside _compute_patches
# ---------------------------------------------------------------------------

class _Reached(Exception):
    """An encode entry point ran: the pre-flight let the build through."""


def _locate_tiny(disk_f, parts):
    off, size = parts[0]
    r = Ext4Reader(disk_f, off, size)
    nodes = {p.lstrip("/"): n for p, _i, n in r.iter_regular_files(min_size=0)}
    return r, nodes[GAME + "/game"], nodes[IMAGE]


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    """Stubs every step that encodes, stages or copies (each records that it
    ran and stops the build with :class:`_Reached`), ffprobe (a clip's
    verdict is its container), and the ext4 driver's availability."""
    ran, kw = [], {}

    def stop(name):
        def _f(*a, **k):
            ran.append(name)
            kw[name] = k
            raise _Reached(name)
        return _f
    for name in ("_prepare_video_patches", "_extract_inputs",
                 "_encode_cat0_sounds", "_stage_grown_image", "_derive_grown",
                 "_chain_encode_appended", "_compute_music_patches",
                 "_restore_masterdir_consumed"):
        monkeypatch.setattr(engine, name, stop(name))
    monkeypatch.setattr(engine, "_locate", _locate_tiny)
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "ok"))
    probes = []

    def probe(path):
        probes.append(os.path.basename(str(path)))
        return None
    monkeypatch.setattr(video, "detect_video_info", probe)
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    lines = []

    def log(msg, lvl="info", *a, **k):
        lines.append((lvl, msg))
    return type("Rig", (), {"ran": ran, "kw": kw, "lines": lines, "log": log,
                            "tmp": tmp_path, "probes": probes})


#: the start of an MP4: a user's own file the build may copy as it is
_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


def _project(tmp, videos, mp4=False):
    """A project whose Replace Video tab assigned *videos*: ``{card path:
    (your file's bytes, the converted copy's bytes)}``.  Your files are MP4s
    with *mp4*, and something the machine can't play otherwise."""
    proj = tmp / "project"
    (proj / "video").mkdir(parents=True, exist_ok=True)
    clips = tmp / "clips"
    clips.mkdir(exist_ok=True)
    rows, assigned = [], {}
    for i, (card_path, (src_n, staged_n)) in enumerate(sorted(videos.items())):
        fname = "%d.mp4" % i
        rows.append("%s\t/%s" % (fname, card_path))
        (proj / "video" / fname).write_bytes(b"S" * staged_n)
        src = clips / ("mine_%d.mkv" % i)
        head = _MP4 if mp4 else b""
        src.write_bytes(head + b"M" * (src_n - len(head)))
        assigned["video/" + fname] = str(src)
    (proj / "video" / "manifest.txt").write_text("\n".join(rows) + "\n")
    staged_changes.save(str(proj), {"video": assigned})
    return proj


def _compute(rig, card, project, budget, **kw):
    with open(card, "rb") as disk_f, engine._SpaceScope(budget):
        return engine._compute_patches(disk_f, _parts(), str(project), rig.log,
                                       None, lambda: False, **kw)


def _budget(orig, out=None, grow_to=None, sizes=("16G", "32G"), **kw):
    return engine._SpaceBudget(str(orig), output=str(out) if out else None,
                               updating=out is not None, grow_to=grow_to,
                               sizes=list(sizes), **kw)


def _blocks(n):
    return -(-n // BS)


def test_a_whole_build_that_cannot_fit_is_refused_before_any_encode(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    # two clips of 150 KB over 3 KB slots: 290 blocks more, 190 usable
    proj = _project(rig.tmp, {V1: (150_000, 150_000), V2: (150_000, 150_000)})
    cleared = []
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj, _budget(card, on_clear=lambda: cleared.append(1)))
    assert rig.ran == [] and cleared == []      # nothing read, staged, written
    e = ei.value
    assert e.avail == (200 - 10) * BS           # the kernel keeps 2% back
    # each 150 KB clip takes 147 blocks where its slot held 3
    assert e.need == 2 * (147 - 3 + engine._SPACE_SLACK_BLOCKS) * BS
    assert e.fits == "16G"
    assert "Build it for a 16 GB SD card if the SD card in the machine" in str(e)
    # named as the project names them, not by their card paths
    assert sorted(name for _n, name in e.items) == ["0.mp4", "1.mp4"]
    assert ".asset" not in str(e)


def test_the_same_build_that_fits_logs_its_budget_and_goes_on(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (150_000, 150_000)})
    cleared = []
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card, on_clear=lambda: cleared.append(1)))
    assert rig.ran == ["_prepare_video_patches"]
    assert cleared == [1]                       # measured, fits: may write now
    [line] = [m for _l, m in rig.lines if "games partition has" in m]
    # 190 usable blocks of 1 KB; the clip's 147 less the 3 its slot held,
    # and one for its extent tree
    assert line == ("The games partition has 195 KB free and this build "
                    "needs about 148 KB of it.")


def test_a_build_for_a_bigger_card_is_measured_at_that_size(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (150_000, 150_000), V2: (150_000, 150_000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card, grow_to="16G"))
    assert any("free on a 16 GB SD card and this build needs about" in m
               for _l, m in rig.lines)


# ---- which file each clip goes on as (E, C, F) -------------------------------

def test_a_clip_counts_as_the_file_that_goes_on_the_card(rig):
    """Your own file goes on only when it is an MP4/QuickTime the slot can
    play; anything else goes on as the app's converted copy.  The pre-flight
    counts that file, never the smaller of the two: a user file smaller than
    its conversion that can't go on used to under-count, pass, and fail at
    the copy after the encode (PAD-176)."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    # yours 50 KB but not an MP4, the converted copy 250 KB: 245 blocks
    proj = _project(rig.tmp, {V1: (50_000, 250_000)})
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == []
    assert ei.value.need == (_blocks(250_000) - 3 + 1) * BS
    # the same sizes with your file an MP4: yours goes on, and fits
    rig.lines.clear()
    proj2 = _project(rig.tmp / "b", {V1: (50_000, 250_000)}, mp4=True)
    with pytest.raises(_Reached):
        _compute(rig, card, proj2, _budget(card))
    [line] = [m for _l, m in rig.lines if "games partition has" in m]
    assert line.endswith("needs about %s of it."
                         % cs.size_words((_blocks(50_000) - 3 + 1) * BS))
    # one figure, never "between": the file is settled before the encode
    assert not any("between" in m or "may need up to" in m
                   for _l, m in rig.lines)


def test_the_settled_verdicts_go_on_to_the_video_step(rig):
    """Each clip is probed once, before the encode, and the video step gets
    the answers (and whether this computer copies whole files) instead of
    probing again."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (20_000, 30_000), V2: (20_000, 30_000)},
                    mp4=True)
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    kw = rig.kw["_prepare_video_patches"]
    assert kw["verdicts"] == {"0.mp4": (True, None), "1.mp4": (True, None)}
    assert kw["grow_check"] == (True, "ok")
    # each user's file once (no ffprobe answer: the container check stands)
    assert sorted(rig.probes) == ["mine_0.mkv", "mine_1.mkv"]


def test_a_settled_verdict_is_not_probed_again(monkeypatch):
    def never(*a, **k):
        raise AssertionError("probed twice")
    monkeypatch.setattr(video, "isobmff_brand", never)
    monkeypatch.setattr(video, "detect_video_info", never)
    lines = []
    got = engine._intact_copy_source("mine.mp4", "slot.mp4", "a.mp4", 10,
                                     lambda m, l="info": lines.append(m),
                                     verdict=(False, "it's HEVC"))
    assert got == "slot.mp4" and "it's HEVC" in lines[0]


def test_many_clips_say_why_the_build_probes_them_first(rig, monkeypatch):
    monkeypatch.setattr(engine, "_SETTLE_SAY", 1)
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (1000, 1000), V2: (1000, 1000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert ("info", "Checking which file each of the 2 replaced videos goes "
                    "on the card as (your own file or the app's converted "
                    "copy), so the room they need is known before the card "
                    "image is written...") in rig.lines
    rig.lines.clear()
    monkeypatch.setattr(engine, "_SETTLE_SAY", 2)
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert not any("Checking which file" in m for _l, m in rig.lines)


def test_the_need_and_the_size_it_names_come_from_one_count(rig):
    """The need stated, the size named and the room quoted agree: a size is
    named only when the stated need fits it, and 'even the biggest' only when
    it doesn't fit that either."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (250_000, 250_000)}, mp4=True)
    need = (_blocks(250_000) - 3 + 1) * BS
    for rooms, fits, largest in (
            ({"8G": 190 * BS, "16G": need, "32G": 10 * need}, "16G", None),
            ({"8G": 190 * BS, "16G": need - 1, "32G": need}, "32G", None),
            ({"8G": 190 * BS, "16G": need - 2, "32G": need - 1}, None, "32G")):
        with open(card, "rb") as f:
            chk = engine._space_check(_budget(card), f, _parts(), str(proj),
                                      engine._changed_videos(str(proj), {}),
                                      rig.log)
        chk.whole.room = rooms
        with pytest.raises(cs.WontFit) as ei:
            chk.check(final=False)
        e = ei.value
        assert e.need == need and (e.fits, e.largest) == (fits, largest)
        if fits:
            assert e.need <= e.fits_room == rooms[fits]
        else:
            assert e.need > e.largest_room
            assert "Even a 32 GB SD card has only" in str(e)


def test_the_banks_room_is_counted_as_the_refusal_counts(rig):
    """The room the bank's budget hands out is exactly what the final check
    allows, and its readout never says the other files take more than the
    partition has."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (60_000, 150_000)}, mp4=True)
    with open(card, "rb") as f:
        chk = engine._space_check(_budget(card), f, _parts(), str(proj),
                                  engine._changed_videos(str(proj), {}),
                                  rig.log)
    room = chk.bank_room()
    assert 0 < room.others <= room.free == 190 * BS
    # the clip goes on as your 60 KB file: 56 blocks and its slack, and the
    # bank's own slack
    assert room.others == (_blocks(60_000) - 3 + 1 + 1) * BS
    chk.check(bank_bytes=room.limit, final=False)           # fits, exactly
    with pytest.raises(cs.WontFit):
        chk.check(bank_bytes=room.limit + 1, final=False)


# ---- an update (B) -------------------------------------------------------------

def test_an_update_that_fits_only_from_the_original_is_built_from_it(rig):
    """The last build put 1.asset on whole at 12 KB and left 30 blocks free.
    The output has no room for this build; the original has.  The build goes
    on as a whole build, with the reason, instead of being refused."""
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=30, v1=12000))
    before = _snap(out)
    # 1.asset unchanged since the last build; 2.asset grows by 95 blocks
    proj = _project(rig.tmp, {V1: (12000, 12000), V2: (100_000, 100_000)},
                    mp4=True)
    budget = _budget(orig, out)
    with pytest.raises(_Reached):
        _compute(rig, orig, proj, budget)
    assert rig.ran == ["_prepare_video_patches"]
    assert budget.whole == ("the build already there has 20 KB free on its "
                            "games partition and this build needs 99 KB of "
                            "it, while built from the original it needs "
                            "109 KB of 195 KB")
    # measured and logged as the whole build it now is
    assert ("info", "The games partition has 195 KB free and this build "
                    "needs about 109 KB of it.") in rig.lines
    assert _snap(out) == before


def test_an_update_that_fits_neither_is_refused_with_the_originals_numbers(rig):
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=30, v1=12000))
    before = _snap(out)
    proj = _project(rig.tmp, {V1: (12000, 12000), V2: (250_000, 250_000)},
                    mp4=True)
    budget = _budget(orig, out)
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, orig, proj, budget)
    e = ei.value
    assert rig.ran == []
    # the original's room and the whole build's need, never the output's
    assert e.avail == (200 - 10) * BS
    assert e.need == ((12 - 3) + (_blocks(250_000) - 3) + 2) * BS
    assert e.fits == "16G"
    assert sorted(n for _b, n in e.items) == ["0.mp4", "1.mp4"]
    assert _snap(out) == before


def _kept_size_row(tmp, w, h):
    """A picture of 1.asset's scene kept at its own *w* x *h* (BC3), where
    the stock picture held 3000 bytes."""
    from PIL import Image
    png = tmp / ("kept_%dx%d.png" % (w, h))
    Image.new("RGBA", (w, h)).save(png)
    return ("a.png", "/" + V1, str(png), 0, 3000, 32, 32, 5)


def test_a_scene_the_last_build_grew_counts_nothing_on_the_update(rig):
    """A picture kept at its own size grows 1.asset's scene from 3 KB to
    12 KB.  The last build grew it there already, so this update, which only
    grows 2.asset by a block, needs 2 blocks of the 10 the output has, and
    stays an update; measured on the original the scene's growth counts in
    full, as before."""
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=20, v1=12288,
                                                    v2=4000))
    proj = _project(rig.tmp, {V2: (5000, 5000)}, mp4=True)
    rows = [_kept_size_row(rig.tmp, 128, 96)]         # 12288 bytes
    budget = _budget(orig, out)
    with open(orig, "rb") as f:
        chk = engine._space_check(budget, f, _parts(), str(proj),
                                  engine._changed_videos(str(proj), {}),
                                  rig.log, radimg_edits=rows)
    chk.check()
    assert budget.whole is None
    assert ("info", "The games partition of the build being updated has "
                    "10 KB free and this build needs about 2 KB of it.") \
        in rig.lines
    assert chk._allowance(chk.whole) == _blocks(12288 - 3000)
    assert chk._allowance(chk.update) == 0
    # an output whose scene is still the stock one: the scene counts there
    out2 = _stern_card(rig.tmp / "out2.raw", _tiny_fs(free=40, v2=4000))
    budget = _budget(orig, out2)
    with open(orig, "rb") as f:
        chk = engine._space_check(budget, f, _parts(), str(proj),
                                  engine._changed_videos(str(proj), {}),
                                  rig.log, radimg_edits=rows)
    assert chk._allowance(chk.update) == _blocks(12288) - 3


def test_an_unchanged_clip_of_an_update_adds_nothing(rig):
    """A clip the last build already put on the card, unchanged since, holds
    its blocks there already: it counts nothing, whatever its size."""
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=30, v1=12000))
    proj = _project(rig.tmp, {V1: (12000, 40_000)}, mp4=True)
    budget = _budget(orig, out)
    with pytest.raises(_Reached):
        _compute(rig, orig, proj, budget)
    assert budget.whole is None
    assert ("info", "The games partition of the build being updated has "
                    "20 KB free.") in rig.lines


# ---- what is not copied whole ---------------------------------------------------

def test_a_clip_without_an_assignment_or_a_direct_sd_write_adds_nothing(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (500_000, 500_000)})
    # a direct SD write fits every clip into its slot: never measured
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card), dest_is_device=True)
    assert rig.ran == ["_prepare_video_patches"]
    assert not any("games partition has" in m for _l, m in rig.lines)
    # the assignment gone: the clip is fitted in place, and needs nothing
    rig.ran.clear()
    staged_changes.save(str(proj), {})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert ("info", "The games partition has 195 KB free.") in rig.lines


def test_no_ext4_driver_means_nothing_is_copied_whole_so_nothing_refused(
        rig, monkeypatch):
    """Without the ext4 driver every clip is squeezed into its slot: nothing
    is refused, and the log claims no use of the partition."""
    monkeypatch.setattr(ext4_grow, "available", lambda: (False, "no WSL"))
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (500_000, 500_000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == ["_prepare_video_patches"]
    assert not any("needs about" in m for _l, m in rig.lines)
    assert rig.kw["_prepare_video_patches"]["grow_check"] == (False, "no WSL")


def test_the_ext4_driver_is_asked_once_a_build(rig, monkeypatch):
    """A build with longer sounds and no replaced video: the audio grow gate
    asks whether this computer copies whole files (a WSL round trip), and
    the pre-flight's final check and the other gates take that answer
    instead of asking again before the card copy starts."""
    asked = []
    monkeypatch.setattr(ext4_grow, "available",
                        lambda: asked.append(1) or (True, "ok"))
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {})
    cleared = []
    budget = _budget(card, on_clear=lambda: cleared.append(len(asked)))
    with open(card, "rb") as f, engine._SpaceScope(budget):
        chk = engine._space_check(budget, f, _parts(), str(proj), [], rig.log)
        assert engine._audio_grow_gate(False) == (True, "")
        chk.check(bank_bytes=10_000)
        assert engine._image_grow_gate(False) == (True, "")
        assert engine._text_grow_gate(False) == (True, "")
    assert asked == [1] and cleared == [1]
    assert any("needs about" in m for _l, m in rig.lines)
    # outside a build each gate still asks for itself
    engine._image_grow_gate(False)
    assert asked == [1, 1]


def test_nothing_is_measured_outside_a_build_scope(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (500_000, 500_000)})
    assert getattr(engine._BUILD_SPACE, "budget", None) is None
    with open(card, "rb") as disk_f, pytest.raises(_Reached):
        engine._compute_patches(disk_f, _parts(), str(proj), rig.log, None,
                                lambda: False)
    assert rig.ran == ["_prepare_video_patches"]


# ---- the files made after the encode, sized before it (H) ----------------------

def test_the_modes_clips_and_screens_are_sized_before_the_encode(
        tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(video, "detect_video_info",
                        lambda p: NS(duration=10.0))
    per_s = engine._MODE_CLIP_BYTES_PER_S * engine._MODE_CLIP_OVERSHOOT
    box = engine._MODE_CLIP_CONTAINER
    title = NS(clip="title", clip_seconds=45, clip_both={}, screen=True)
    both = NS(clip="file", clip_file="a.mp4", clip_seconds=4,
              clip_both={"clip": "title", "seconds": 5.0}, screen=False)
    code = NS(clip="c.mp4", screen=True)
    got = engine._unsized_bytes(str(tmp_path), [("a", title), ("b", both)],
                                [("c", code)], [])
    assert got == (int(30 * per_s) + box                # capped at 30 s
                   + engine._MODE_SCREEN_BYTES
                   + int(10 * per_s) + box + int(5 * per_s) + box
                   + int(10 * per_s) + box + engine._MODE_SCREEN_BYTES)
    # 30 s of the modes' own video is about 11.7 MB: more than the margin
    assert int(30 * per_s) > engine._SPACE_MARGIN


def test_a_picture_kept_at_its_own_size_is_sized_before_the_encode(tmp_path):
    from PIL import Image
    png = tmp_path / "a.png"
    Image.new("RGBA", (64, 32)).save(png)
    same = tmp_path / "b.png"
    Image.new("RGBA", (30, 32)).save(same)      # the stock grid, padded
    rows = [("a.png", "s/scene.radium", str(png), 0, 1024, 32, 32, 5),
            ("a.png", "t/scene.radium", str(png), 0, 1024, 32, 32, 4),
            ("b.png", "s/scene.radium", str(same), 0, 1024, 32, 32, 5)]
    # BC3 a byte a pixel, BC1 half that, less the block data each replaces
    assert engine._unsized_bytes(str(tmp_path), [], [], rows) == 64 * 32 - 1024
    rows[1] = rows[1][:4] + (512,) + rows[1][5:]
    assert engine._unsized_bytes(str(tmp_path), [], [], rows) == (
        64 * 32 - 1024) + (64 * 32 // 2 - 512)


def test_the_sized_allowance_is_counted_in_the_need(rig, monkeypatch):
    monkeypatch.setattr(engine, "_unsized_bytes", lambda *a, **k: 150 * BS)
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (60_000, 60_000)}, mp4=True)
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj, _budget(card))
    assert ei.value.need == (150 + _blocks(60_000) - 3 + 1) * BS


# ---- the grown sound bank ---------------------------------------------------

def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 2 * int(44100 * seconds))
    return path


@pytest.fixture()
def audio(rig, monkeypatch):
    """The audio step as far as the grown bank's length, on the tiny card:
    idx 5 is a one-second stereo slot; its replacement runs longer."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as emu
    params = [{"idx": i, "chan": 2, "length": 44100 + emu.BLOCK,
               "body_off": 0x100 + i * 0x100} for i in range(COUNT)]

    def extract(disk_f, parts, work, log, prog=None):
        reader, fw_node, img_node = _locate_tiny(disk_f, parts)
        gr = os.path.join(work, "game_real")
        img = os.path.join(work, "image.bin")
        open(gr, "wb").write(b"\x7fELF")
        open(img, "wb").write(_bank_header())
        return gr, img, reader, fw_node, img_node
    monkeypatch.setattr(engine, "_extract_inputs", extract)
    monkeypatch.setattr(emu, "audio_decode_supported", lambda gr: True)
    monkeypatch.setattr(engine, "_params_for", lambda *a, **k: list(params))
    monkeypatch.setattr(engine, "_audio_grow_gate", lambda *a, **k: (True, ""))
    monkeypatch.setattr(engine, "_descriptor_sites", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_grows_named_by_a_descriptor",
                        lambda grows, *a, **k: grows)
    return params


def test_a_grown_bank_that_cannot_fit_is_refused_before_it_is_staged(
        rig, audio, monkeypatch):
    # the bank budget left as it was before the partition was counted, so
    # the bank reaches the final check whole
    monkeypatch.setattr(engine, "_grows_within_bank_limit",
                        lambda grows, *a, **k: grows)
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {})
    _wav(proj / "idx0005.wav", 3.0)           # 3 s where the slot holds 1 s
    cleared = []
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj,
                 _budget(card, on_clear=lambda: cleared.append(1)))
    assert rig.ran == [] and cleared == []   # not staged, derived, encoded
    e = ei.value
    assert [name for _n, name in e.items] == [
        "the sound bank with the longer sounds"]
    # the bank's exact grown length, less the 3 blocks image.bin holds now
    bank = engine._grown_bank_bytes(
        MD_OFF, COUNT, [engine._grown_body_bytes(audio[5], 3 * 44100)])
    assert e.need == (-(-bank // BS) - 3 + engine._SPACE_SLACK_BLOCKS) * BS
    assert e.fits == "16G"


def test_the_bank_budget_trims_to_the_room_instead_of_failing(rig, audio):
    """With the partition counted, the 2 GB pass holds the bank to the room
    left: the longer sound is trimmed, named, and the build goes on."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {})
    _wav(proj / "idx0005.wav", 3.0)
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == ["_encode_cat0_sounds"]
    [trim] = [m for _l, m in rig.lines if "trimmed to fit" in m]
    assert "the card's games partition has room for the sound bank" in trim
    assert ("if the SD card in the machine is 16 GB or bigger, build it for a "
            "16 GB SD card (SD card size on the Write tab) to keep them "
            "whole") in trim
    [readout] = [m for _l, m in rig.lines if m.startswith("Longer sounds:")]
    assert "the game's own limit, which a bigger SD card doesn't raise" in readout
    assert "but the card's games partition has room for it" in readout


def test_the_bank_budget_keeps_the_songs_the_user_chose_first(tmp_path):
    """Keep-whole priority decides who gets the partition's room too."""
    img = tmp_path / "image.bin"
    img.write_bytes(_bank_header())
    byidx = {i: {"idx": i, "chan": 2, "length": 44100} for i in (1, 2, 3)}
    grows = {i: (44100, 60 * 44100) for i in (1, 2, 3)}    # a minute each
    one = engine._grown_body_bytes(byidx[1], 60 * 44100)
    # room for one of them, not two
    room = engine._BankRoom(limit=engine._grown_bank_bytes(
                                MD_OFF, COUNT, [one]) + one // 2,
                            free=40 * 10**6, others=20 * 10**6,
                            suggest=lambda n: "16G")
    lines = []
    kept = engine._grows_within_bank_limit(
        grows, byidx, str(img), lambda m, l="info": lines.append((l, m)),
        priority=[3], room=room)
    assert set(kept) == {3}
    [(_lvl, trim)] = [(l, m) for l, m in lines if "trimmed to fit" in m]
    assert "idx 1 " in trim and "idx 2 " in trim and "idx 3 " not in trim
    assert ("(40 MB free there, about 20 MB of it for the other files this "
            "build copies whole)") in trim
    # without a room the 2 GB limit is the only one, and all three fit
    assert set(engine._grows_within_bank_limit(
        grows, byidx, str(img), lambda *a, **k: None)) == {1, 2, 3}


def test_the_forced_sounds_take_their_room_before_the_trim(tmp_path):
    """The modes' own sounds can't be trimmed: their bodies are placed first,
    and the user's longer songs share what is left, so a build with them
    trims one more song rather than being refused at the final check."""
    img = tmp_path / "image.bin"
    img.write_bytes(_bank_header())
    byidx = {i: {"idx": i, "chan": 2, "length": 44100} for i in (1, 2, 9)}
    grows = {i: (44100, 60 * 44100) for i in (1, 2)}
    forced = {9: (44100, 60 * 44100)}
    one = engine._grown_body_bytes(byidx[1], 60 * 44100)
    # room for two bodies: without the forced one both songs would fit
    room = engine._BankRoom(
        limit=engine._grown_bank_bytes(MD_OFF, COUNT, [one, one]),
        free=40 * 10**6, others=0, suggest=lambda n: None)
    lines = []
    kept = engine._grows_within_bank_limit(
        grows, byidx, str(img), lambda m, l="info": lines.append((l, m)),
        room=room, reserved=forced)
    assert set(kept) == {1}
    assert engine._grown_bank_size(str(img), byidx,
                                   {**kept, **forced}) <= room.limit
    [readout] = [m for _l, m in lines if m.startswith("Longer sounds:")]
    assert readout.startswith("Longer sounds: 1 kept whole beside 1 other "
                              "sound(s) this build adds whole,")


def _bank_rooms(rig, out_free):
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=out_free))
    budget = _budget(orig, out)
    with open(orig, "rb") as f:
        chk = engine._SpaceCheck(budget, f, _parts(), cs.ROUTE_MOUNT, 0, 0,
                                 rig.log)
    return budget, chk


def test_an_update_goes_whole_for_the_bank_only_to_keep_a_song(rig):
    """The output has a block less room than the original.  An update whose
    longer sounds don't all fit stays an update when the original's room
    keeps the same ones (the whole card copied again for nothing), and goes
    whole when it keeps one more."""
    budget, chk = _bank_rooms(rig, 199)
    upd = chk._bank_room(chk.update)
    whl = chk._bank_room(chk.whole)
    assert whl.limit - upd.limit == BS
    want = upd.limit + 100_000
    same = chk.bank_room(want=want, kept_at=lambda limit: {1, 2})
    assert budget.whole is None and same.limit == upd.limit
    more = chk.bank_room(
        want=want, kept_at=lambda limit: {1, 2, 3} if limit > upd.limit
        else {1, 2})
    assert budget.whole is not None and more.limit == whl.limit


def test_the_games_own_limit_trims_an_update_and_a_whole_build_alike(
        rig, monkeypatch):
    """Both rooms past the game's 2 GB: the bank is trimmed to that limit
    either way, so the update is never made a whole build for it."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as emu
    budget, chk = _bank_rooms(rig, 150)
    upd = chk._bank_room(chk.update)
    monkeypatch.setattr(emu, "MAX_IMAGE_BYTES", upd.limit - 10)
    room = chk.bank_room(want=upd.limit + 100_000)
    assert budget.whole is None and room.limit == upd.limit


def test_what_a_room_keeps_is_what_the_budget_keeps(tmp_path):
    img = tmp_path / "image.bin"
    img.write_bytes(_bank_header())
    byidx = {i: {"idx": i, "chan": 2, "length": 44100} for i in (1, 2, 3)}
    grows = {i: (44100, 60 * 44100) for i in (1, 2, 3)}
    one = engine._grown_body_bytes(byidx[1], 60 * 44100)
    for bodies in (0, 1, 2, 3):
        limit = engine._grown_bank_bytes(MD_OFF, COUNT, [one] * bodies)
        room = engine._BankRoom(limit=limit, free=0, others=0,
                                suggest=lambda n: None)
        kept = engine._grows_within_bank_limit(
            grows, byidx, str(img), lambda *a, **k: None, priority=[3],
            room=room)
        assert engine._grows_kept_at(grows, byidx, str(img), limit,
                                     priority=[3]) == kept
        assert len(kept) == bodies


def test_a_ports_trim_says_to_build_the_card_on_its_own(tmp_path):
    img = tmp_path / "image.bin"
    img.write_bytes(_bank_header())
    byidx = {i: {"idx": i, "chan": 2, "length": 44100} for i in (1, 2)}
    grows = {i: (44100, 60 * 44100) for i in (1, 2)}
    one = engine._grown_body_bytes(byidx[1], 60 * 44100)
    room = engine._BankRoom(
        limit=engine._grown_bank_bytes(MD_OFF, COUNT, [one]),
        free=40 * 10**6, others=0, suggest=lambda n: "16G", fixed=True)
    lines = []
    engine._grows_within_bank_limit(
        grows, byidx, str(img), lambda m, l="info": lines.append((l, m)),
        room=room)
    [trim] = [m for _l, m in lines if "trimmed to fit" in m]
    assert "build this card on its own from the Write tab for a 16 GB" in trim
    assert "SD card size on the Write tab" not in trim


# ---------------------------------------------------------------------------
# write_image: the copy starts only once the build is measured and fits (A)
# ---------------------------------------------------------------------------

@pytest.fixture()
def build(rig, monkeypatch):
    """write_image on the tiny card, the card copy recorded rather than made
    (the 8 GB sparse card is never copied for real), an earlier build and its
    record at the output."""
    import shutil
    monkeypatch.delenv(cs.ENV, raising=False)
    monkeypatch.setattr(cs, "offered", lambda p: ["16G", "32G"])
    copies = []

    def copy(a, b):
        copies.append(time.monotonic())
        open(b, "wb").close()
    monkeypatch.setattr(shutil, "copyfile", copy)
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = rig.tmp / "out.raw"
    out.write_bytes(b"the last build")
    rec = engine.build_manifest_path(str(out))
    with open(rec, "w") as f:
        f.write('{"the": "last build\'s record"}')

    def run(project, **kw):
        return engine.write_image(str(orig), str(project), str(out),
                                  log=rig.log, **kw)
    return type("Build", (), {"run": run, "copies": copies, "orig": orig,
                              "out": out, "rec": rec})


def _left_as_it_was(build):
    with open(build.rec) as f:
        rec = f.read()
    return build.out.read_bytes() == b"the last build" and "last build" in rec


def test_a_whole_build_refused_leaves_the_output_as_it_was(rig, build):
    """Refused by the videos' check: the copy never started, the stub record
    was never laid, the build already there is untouched, and the refusal
    comes at once rather than after the whole card was copied."""
    proj = _project(rig.tmp, {V1: (150_000, 150_000), V2: (150_000, 150_000)})
    t0 = time.monotonic()
    with pytest.raises(cs.WontFit) as ei:
        build.run(proj, update=False)
    assert time.monotonic() - t0 < 5
    assert build.copies == [] and _left_as_it_was(build)
    assert ("stopped before anything was written to the card image"
            in str(ei.value))
    assert not any("Copying card image" in m for _l, m in rig.lines)


def test_a_bank_refusal_also_leaves_the_output_as_it_was(rig, audio, build,
                                                         monkeypatch):
    monkeypatch.setattr(engine, "_grows_within_bank_limit",
                        lambda grows, *a, **k: grows)
    proj = _project(rig.tmp, {})
    _wav(proj / "idx0005.wav", 3.0)
    with pytest.raises(cs.WontFit) as ei:
        build.run(proj, update=False)
    assert build.copies == [] and _left_as_it_was(build)
    assert ("stopped before anything was written to the card image"
            in str(ei.value))


def test_a_build_that_fits_starts_its_copy_once_it_is_measured(rig, build):
    proj = _project(rig.tmp, {V1: (150_000, 150_000)})
    with pytest.raises(_Reached):
        build.run(proj, update=False)
    assert len(build.copies) == 1
    said = [m for _l, m in rig.lines]
    measured = next(i for i, m in enumerate(said) if "games partition has" in m)
    copying = next(i for i, m in enumerate(said) if "Copying card image" in m)
    assert measured < copying
    # it failed after the copy started: that half-written output goes
    assert not build.out.exists()


def test_a_build_cancelled_before_it_was_measured_leaves_the_output(
        rig, build, monkeypatch):
    seen = []

    def fake(*a, **k):
        seen.append(getattr(engine._BUILD_SPACE, "budget", None))
        return None, None, None, None, None      # "cancelled"
    monkeypatch.setattr(engine, "_compute_patches", fake)
    build.run(rig.tmp, update=False)
    [b] = seen
    assert (b.original, b.updating, b.grow_to, b.sizes, b.fixed) == (
        str(build.orig), False, None, ["16G", "32G"], False)
    assert getattr(engine._BUILD_SPACE, "budget", None) is None
    assert build.copies == [] and _left_as_it_was(build)


def test_a_build_the_preflight_did_not_measure_still_copies(
        rig, build, monkeypatch):
    """A stand-in for _compute_patches never clears the budget: the copy
    starts when it returns, and the build completes."""
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: ([], (0, 0, 0, 0), None, None, None))
    counts, _a, _v = build.run(rig.tmp, update=False)
    assert tuple(counts) == (0, 0, 0, 0)
    assert len(build.copies) == 1
    assert engine.read_build_manifest(str(build.out)).get("complete")


def test_an_update_that_fits_only_from_the_original_says_so_and_copies(
        rig, build, monkeypatch):
    """The fallback is logged like every update that can't be made, and the
    original is copied over the output only once the edits are computed: an
    encode that fails first leaves the last build and its record."""
    out = _stern_card(build.out, _tiny_fs(free=30, v1=12000))
    before = _snap(out)
    monkeypatch.setattr(engine, "read_build_manifest",
                        lambda p: {"complete": True})
    monkeypatch.setattr(engine, "build_update_reason", lambda *a: None)
    proj = _project(rig.tmp, {V1: (12000, 12000), V2: (100_000, 100_000)},
                    mp4=True)
    with pytest.raises(_Reached):           # the encode fails
        engine.write_image(str(build.orig), str(proj), str(out), log=rig.log)
    [warn] = [m for l, m in rig.lines if l == "warning"
              and m.startswith("This build can't update the last one")]
    assert warn == ("This build can't update the last one in place (the "
                    "build already there has 20 KB free on its games "
                    "partition and this build needs 99 KB of it, while built "
                    "from the original it needs 109 KB of 195 KB); building "
                    "from the original instead.")
    assert build.copies == [] and _snap(out) == before
    assert "last build" in open(build.rec).read()
    assert not any("Copying card image" in m for _l, m in rig.lines)


def test_the_fallback_copies_once_its_edits_are_computed(rig, build,
                                                         monkeypatch):
    out = _stern_card(build.out, _tiny_fs(free=30, v1=12000))
    monkeypatch.setattr(engine, "read_build_manifest",
                        lambda p: {"complete": True})
    monkeypatch.setattr(engine, "build_update_reason", lambda *a: None)
    seen = []

    def compute(*a, **k):
        budget = engine._BUILD_SPACE.budget
        budget.whole = "no room"
        budget.clear()                      # the pre-flight's final check
        seen.append(list(build.copies))
        return [], (0, 0, 0, 0), None, None, None
    monkeypatch.setattr(engine, "_compute_patches", compute)
    engine.write_image(str(build.orig), str(rig.tmp), str(out), log=rig.log)
    assert seen == [[]] and len(build.copies) == 1
    said = [m for _l, m in rig.lines]
    assert said.index("Copying card image to output...") > next(
        i for i, m in enumerate(said) if m.startswith("This build can't "
                                                      "update"))
    assert engine.read_build_manifest(str(out)).get("complete")


def test_a_cancel_inside_the_compute_ends_the_build_cleanly(rig, build,
                                                            monkeypatch):
    """Every Cancel inside _compute_patches hands back the five values its
    callers unpack: a Cancel after the video step used to raise ValueError
    into the log as an unexpected error."""
    proj = _project(rig.tmp, {V1: (20_000, 20_000)}, mp4=True)
    done = []

    def prepare(*a, **k):
        done.append(1)
        return [], [], []
    monkeypatch.setattr(engine, "_prepare_video_patches", prepare)
    got = build.run(proj, update=False, cancel=lambda: bool(done))
    assert done == [1]
    assert got == ((0, 0, 0, 0), None, None)
    assert not build.out.exists()           # its half-made copy discarded
    import inspect
    import re
    src = inspect.getsource(engine._compute_patches)
    assert not re.search(r"return None, None, None, None\n", src)


def test_an_update_refused_leaves_the_build_there(rig, build, monkeypatch):
    out = _stern_card(build.out, _tiny_fs(free=30, v1=12000))
    before = os.path.getmtime(out), _snap(out)
    monkeypatch.setattr(engine, "read_build_manifest",
                        lambda p: {"complete": True})
    monkeypatch.setattr(engine, "build_update_reason", lambda *a: None)
    proj = _project(rig.tmp, {V1: (12000, 12000), V2: (250_000, 250_000)},
                    mp4=True)
    with pytest.raises(cs.WontFit) as ei:
        engine.write_image(str(build.orig), str(proj), str(out), log=rig.log)
    assert ei.value.avail == (200 - 10) * BS    # the original's room
    assert build.copies == []
    assert (os.path.getmtime(out), _snap(out)) == before
    assert getattr(engine._BUILD_SPACE, "budget", None) is None


def test_a_port_build_is_measured_as_one_that_cannot_take_a_size(
        rig, build, monkeypatch):
    monkeypatch.setenv(cs.FIXED_ENV, "1")
    proj = _project(rig.tmp, {V1: (150_000, 150_000), V2: (150_000, 150_000)})
    with pytest.raises(cs.WontFit) as ei:
        build.run(proj, update=False)
    msg = str(ei.value)
    assert "build this card on its own from the Write tab for a 16 GB" in msg
    assert "SD card size on the Write tab" not in msg


# ---------------------------------------------------------------------------
# The copy-time backstop names one size
# ---------------------------------------------------------------------------

def test_the_copy_time_failure_carries_its_numbers():
    text = ("PAD_GROW_ITEM 5000000 a/1.asset\nPAD_GROW_ITEM 7000000 a/2.asset\n"
            "PAD_GROW_ENOSPC need=12000000 avail=3000000\n")
    e = ext4_grow._no_space(text, grown=0)
    assert isinstance(e, ext4_grow.Ext4GrowNoSpace)
    assert (e.need, e.avail) == (12000000, 3000000)
    assert e.items == [(5000000, "a/1.asset"), (7000000, "a/2.asset")]
    assert "This build is 9 MB over" in str(e)
    bare = ext4_grow.Ext4GrowNoSpace("full")
    assert (bare.need, bare.avail, bare.items) == (None, None, [])


def test_the_copy_time_hint_names_the_one_size_that_fits(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    card = _stern_card(tmp_path / "c.raw", _tiny_fs(free=200))
    gained = {c: cs.room_gained(str(card), c) for c in ("16G", "32G")}
    assert 0 < gained["16G"] < gained["32G"]
    fits16 = ext4_grow.Ext4GrowNoSpace("x", need=10**6, avail=1000)
    h = engine._bigger_card_hint(fits16, str(card), P3, ["16G", "32G"])
    assert "build it for a 16 GB SD card" in h and "32 GB" not in h
    assert "which then has %s free" % cs.size_words(1000 + gained["16G"]) in h
    only32 = ext4_grow.Ext4GrowNoSpace(
        "x", need=1000 + gained["16G"] + 1, avail=1000)
    assert "build it for a 32 GB SD card" in engine._bigger_card_hint(
        only32, str(card), P3, ["32G", "16G"])
    none = ext4_grow.Ext4GrowNoSpace("x", need=10**15, avail=1000)
    h = engine._bigger_card_hint(none, str(card), P3, ["16G", "32G"])
    assert h.startswith("  Even built for a 32 GB SD card")
    assert "something has to come out" in h
    # a port's copy: build the card on its own, never the ignored control
    monkeypatch.setenv(cs.FIXED_ENV, "1")
    h = engine._bigger_card_hint(fits16, str(card), P3, ["16G", "32G"])
    assert ("  Or, if the SD card in that machine is 16 GB or bigger, build "
            "this card on its own from the Write tab for a 16 GB SD card") in h
    assert "SD card size on the Write tab" not in h


def test_a_space_failure_points_at_making_room_not_at_switches(monkeypatch,
                                                               tmp_path):
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    monkeypatch.setattr(cs, "supported", lambda: True)
    space = engine._rebuilt_not_written(True)
    assert "ran out of room" in space and "SD card size on the Write tab" in space
    assert "PAD_STERN" not in space
    # macOS shows no SD card size control; a port can't take one
    monkeypatch.setattr(cs, "supported", lambda: False)
    mac = engine._rebuilt_not_written(True)
    assert mac.endswith("Make room and Write again: take something out.")
    assert "Write tab" not in mac
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.setenv(cs.FIXED_ENV, "1")
    port = engine._rebuilt_not_written(True)
    assert "build this card on its own from the Write tab" in port
    assert "SD card size on the Write tab" not in port
    monkeypatch.delenv(cs.FIXED_ENV)
    other = engine._rebuilt_not_written(False)
    assert "PAD_STERN_AUDIO_GROW=0" in other
    assert engine._rebuilt_not_written(False, ["a/b"], switches=False).endswith(
        "could NOT be written to the card: a/b. Its SD-validation record was "
        "already updated to match, so this card will fail validation — re-run "
        "the Write.")

    def full(*a, **k):
        raise ext4_grow.Ext4GrowNoSpace("full", grown=2)
    monkeypatch.setattr(ext4_grow, "grow_files", full)
    src = tmp_path / "s"
    src.write_bytes(b"x")
    plan = {"offset": 0, "jobs": [("a", str(src))]}
    assert engine._grow_video_slots(str(tmp_path / "c.raw"), plan,
                                    lambda *a, **k: None) == 2
    assert plan["no_space"] is True
    lines = []
    engine._report_failed_copies([("k", "gz/image.bin", "bank")], (3, 0, 0, 0),
                                 None, lambda m, l="info": lines.append(m),
                                 no_space=True)
    assert "ran out of room" in lines[0] and "PAD_STERN" not in lines[0]
