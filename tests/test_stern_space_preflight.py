"""PAD-176's pre-flight: a Spike 2 build whose whole-file copies can't fit
the card's games partition is refused BEFORE anything is encoded or written,
with the smallest SD card size it fits.

The free-space arithmetic is pinned to what resize2fs really did to Stern's
own cards (measured on the real images: godzilla_pro 1.16 8G and jaws_le 1.02
16G).  The pre-flight itself runs on a small real ext2 filesystem placed where
a Spike 2 card keeps its games partition, inside a sparse Stern-shaped card,
with every encode entry point stubbed to fail the test if it is reached.
"""

import os
import struct
import wave

import pytest

from pinball_decryptor.core import ext4_grow
from pinball_decryptor.core import staged_changes
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
                   [(81_000_000, "godzilla_pro/assets/a.asset"),
                    (20_000_000, "godzilla_pro/assets/b.asset"),
                    (0, "godzilla_pro/assets/c.asset")],
                   fits="16G", fits_room=7867650048)
    msg = str(e)
    assert isinstance(e, cs.CardSizeError)
    assert msg.startswith("This build needs 1.61 GB more on the card's games "
                          "partition and it has 352 MB free, so the build was "
                          "stopped before anything was encoded or written.")
    assert ("Build it for a 16 GB SD card (SD card size on the Write tab: "
            "7.87 GB free there), or take something out") in msg
    assert ("Biggest: godzilla_pro/assets/a.asset (+81 MB), "
            "godzilla_pro/assets/b.asset (+20 MB).") in msg
    assert "c.asset" not in msg                 # nothing to gain there
    assert (e.need, e.avail, e.fits) == (1_610_000_000, 351760384, "16G")
    for word in ("16G ", "resize2fs", "e2fsck", "losetup", "mode"):
        assert word not in msg


def test_the_refusal_when_even_the_biggest_size_is_too_small():
    msg = str(cs.WontFit(30e9, 7867650048, largest="32G",
                         largest_room=22500528128, at="16G"))
    assert "it has 7.87 GB free on a 16 GB SD card" in msg
    assert ("Even a 32 GB SD card has only 22.50 GB free there, so something "
            "has to come out") in msg
    assert "Build it for" not in msg


def test_the_refusal_with_no_bigger_size_on_offer():
    msg = str(cs.WontFit(500e6, 351760384))
    assert "Something has to come out (fewer or smaller replacements" in msg
    assert "SD card size" not in msg


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
    ran and stops the build with :class:`_Reached`), and the ext4 driver's
    availability (a refusal asks it)."""
    ran = []

    def stop(name):
        def _f(*a, **k):
            ran.append(name)
            raise _Reached(name)
        return _f
    for name in ("_prepare_video_patches", "_extract_inputs",
                 "_encode_cat0_sounds", "_stage_grown_image", "_derive_grown",
                 "_chain_encode_appended", "_compute_music_patches",
                 "_restore_masterdir_consumed"):
        monkeypatch.setattr(engine, name, stop(name))
    monkeypatch.setattr(engine, "_locate", _locate_tiny)
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "ok"))
    lines = []

    def log(msg, lvl="info", *a, **k):
        lines.append((lvl, msg))
    return type("Rig", (), {"ran": ran, "lines": lines, "log": log,
                            "tmp": tmp_path})


def _project(tmp, videos):
    """A project whose Replace Video tab assigned *videos*: ``{card path:
    (source bytes, staged copy bytes)}``."""
    proj = tmp / "project"
    (proj / "video").mkdir(parents=True)
    clips = tmp / "clips"
    clips.mkdir(exist_ok=True)
    rows, assigned = [], {}
    for i, (card_path, (src_n, staged_n)) in enumerate(sorted(videos.items())):
        fname = "%d.mp4" % i
        rows.append("%s\t/%s" % (fname, card_path))
        (proj / "video" / fname).write_bytes(b"S" * staged_n)
        src = clips / ("mine_%d.mp4" % i)
        src.write_bytes(b"M" * src_n)
        assigned["video/" + fname] = str(src)
    (proj / "video" / "manifest.txt").write_text("\n".join(rows) + "\n")
    staged_changes.save(str(proj), {"video": assigned})
    return proj


def _compute(rig, card, project, budget, **kw):
    with open(card, "rb") as disk_f, engine._SpaceScope(budget):
        return engine._compute_patches(disk_f, _parts(), str(project), rig.log,
                                       None, lambda: False, **kw)


def _budget(ref, updating=False, grow_to=None, sizes=("16G", "32G")):
    return engine._SpaceBudget(reference=str(ref), grow_to=grow_to,
                               updating=updating, sizes=list(sizes))


def test_a_whole_build_that_cannot_fit_is_refused_before_any_encode(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    # two clips of 150 KB over 3 KB slots: 294 blocks more, 190 usable
    proj = _project(rig.tmp, {V1: (150_000, 150_000), V2: (150_000, 150_000)})
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == []                        # nothing read, staged, encoded
    e = ei.value
    assert e.avail == (200 - 10) * BS           # the kernel keeps 2% back
    # each 150 KB clip takes 147 blocks where its slot held 3
    assert e.need == 2 * (147 - 3 + engine._SPACE_SLACK_BLOCKS) * BS
    assert e.fits == "16G"
    assert "Build it for a 16 GB SD card" in str(e)
    assert sorted(rel for _n, rel in e.items) == [V1, V2]


def test_the_same_build_that_fits_logs_its_budget_and_goes_on(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (150_000, 150_000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == ["_prepare_video_patches"]
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


def test_an_update_is_measured_against_the_build_already_there(rig):
    """The last build put 1.asset on whole at 40 KB and left 30 blocks free.
    The original has room for this build, the output does not."""
    orig = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    out = _stern_card(rig.tmp / "out.raw", _tiny_fs(free=30, v1=12000))
    before = _snap(out)
    # 1.asset unchanged since the last build (12 KB there already, adds
    # nothing); 2.asset grows by 95 blocks
    proj = _project(rig.tmp, {V1: (12000, 12000), V2: (100_000, 100_000)})
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, orig, proj, _budget(out, updating=True))
    assert rig.ran == []
    assert ei.value.avail == (30 - 10) * BS
    assert [rel for _n, rel in ei.value.items] == [V2]
    assert _snap(out) == before
    # the same project as a whole build from the original fits
    rig.ran.clear()
    with pytest.raises(_Reached):
        _compute(rig, orig, proj, _budget(orig))
    assert rig.ran == ["_prepare_video_patches"]


def test_videos_count_between_the_smaller_and_the_bigger_file(rig):
    """Each clip goes on as the user's file or the app's converted copy.  A
    build is refused only when even the smaller ones can't fit; when only the
    bigger ones can't, it goes on with a warning."""
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    # your file 250 KB, the converted copy 100 KB: 97..247 blocks, 190 usable
    proj = _project(rig.tmp, {V1: (250_000, 100_000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    budget = [m for _l, m in rig.lines if "games partition has" in m]
    assert budget == ["The games partition has %s free and this build needs "
                      "between %s and %s of it."
                      % tuple(cs.size_words(n * BS) for n in (190, 96, 243))]
    [warn] = [m for lvl, m in rig.lines if lvl == "warning"
              and "may need up to" in m]
    assert "the copy at the end will fail" in warn
    assert "Building for a 16 GB SD card" in warn
    # both bigger than the room: refused, and the size named fits the bigger
    rig.lines.clear()
    rig.ran.clear()
    proj2 = _project(rig.tmp / "b", {V1: (250_000, 220_000)})
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj2, _budget(card))
    assert rig.ran == [] and ei.value.fits == "16G"


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
    monkeypatch.setattr(ext4_grow, "available", lambda: (False, "no WSL"))
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (500_000, 500_000)})
    with pytest.raises(_Reached):
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == ["_prepare_video_patches"]


def test_nothing_is_measured_outside_a_build_scope(rig):
    card = _stern_card(rig.tmp / "orig.raw", _tiny_fs(free=200))
    proj = _project(rig.tmp, {V1: (500_000, 500_000)})
    assert getattr(engine._BUILD_SPACE, "budget", None) is None
    with open(card, "rb") as disk_f, pytest.raises(_Reached):
        engine._compute_patches(disk_f, _parts(), str(proj), rig.log, None,
                                lambda: False)
    assert rig.ran == ["_prepare_video_patches"]


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
    with pytest.raises(cs.WontFit) as ei:
        _compute(rig, card, proj, _budget(card))
    assert rig.ran == []                     # not staged, derived or encoded
    e = ei.value
    assert [rel for _n, rel in e.items] == [IMAGE]
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
    assert "building for a 16 GB SD card (SD card size on the Write tab)" in trim
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


# ---------------------------------------------------------------------------
# write_image hands the budget over; the copy-time backstop names one size
# ---------------------------------------------------------------------------

def _stub_compute(monkeypatch, seen, raise_=None):
    def fake(*a, **k):
        seen.append(getattr(engine._BUILD_SPACE, "budget", None))
        if raise_ is not None:
            raise raise_
        return None, None, None, None, None      # "cancelled"
    monkeypatch.setattr(engine, "_compute_patches", fake)


def test_write_image_measures_a_whole_build_against_the_original(
        tmp_path, monkeypatch):
    import shutil
    monkeypatch.delenv(cs.ENV, raising=False)
    orig = _stern_card(tmp_path / "orig.raw", _tiny_fs())
    # never copy the 8 GB sparse card for real
    monkeypatch.setattr(shutil, "copyfile",
                        lambda a, b: open(b, "wb").close())
    seen = []
    _stub_compute(monkeypatch, seen)
    monkeypatch.setattr(cs, "offered", lambda p: ["16G", "32G"])
    engine.write_image(str(orig), str(tmp_path), str(tmp_path / "o.raw"),
                       update=False)
    [b] = seen
    assert (b.reference, b.updating, b.grow_to, b.sizes) == (
        str(orig), False, None, ["16G", "32G"])
    assert getattr(engine._BUILD_SPACE, "budget", None) is None


def test_write_image_measures_an_update_against_its_output_and_leaves_it(
        tmp_path, monkeypatch):
    monkeypatch.delenv(cs.ENV, raising=False)
    monkeypatch.setattr(cs, "offered", lambda p: ["16G", "32G"])
    orig = _stern_card(tmp_path / "orig.raw", _tiny_fs())
    out = _stern_card(tmp_path / "out.raw", _tiny_fs(free=30, v1=12000))
    before = os.path.getmtime(out), _snap(out)
    monkeypatch.setattr(engine, "read_build_manifest",
                        lambda p: {"complete": True})
    monkeypatch.setattr(engine, "build_update_reason", lambda *a: None)
    seen = []
    _stub_compute(monkeypatch, seen, cs.WontFit(10, 1))
    with pytest.raises(cs.WontFit):
        engine.write_image(str(orig), str(tmp_path), str(out))
    [b] = seen
    assert (b.reference, b.updating, b.grow_to) == (str(out), True, None)
    assert (os.path.getmtime(out), _snap(out)) == before
    assert getattr(engine._BUILD_SPACE, "budget", None) is None


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


def test_a_space_failure_points_at_making_room_not_at_switches(monkeypatch,
                                                               tmp_path):
    space = engine._rebuilt_not_written(True)
    assert "ran out of room" in space and "SD card size on the Write tab" in space
    assert "PAD_STERN" not in space
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
