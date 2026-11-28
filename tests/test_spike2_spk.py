"""PAD-1641: Stern's Spike 2 update package (``<title>-<version>.spk.zip``).

The package is an unencrypted SquashFS holding an SPKS archive; it was taken
for a Spike 3 package (same name shape) and refused for want of a Spike 3 key.
These build tiny packages by hand (no mksquashfs needed) and check the reader,
the card-like volumes the extract runs over, detection and routing.
"""

import io
import os
import struct
import zipfile
import zlib

import pytest

from pinball_decryptor.plugins.stern import spike2_spk as S2
from pinball_decryptor.plugins.stern import squashfs as SQ

ARM_ELF = (b"\x7fELF\x01\x01\x01" + b"\x00" * 9 + struct.pack("<HH", 2, 40)
           + b"\x00" * (0x10000 - 20))


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------
def _meta(data):
    """One uncompressed metadata block."""
    assert len(data) <= 8192
    return struct.pack("<H", len(data) | 0x8000) + data


def build_squashfs(name, payload, block_size=4096):
    """A SquashFS 4.0 image (gzip) whose root holds one file *name* with
    *payload*: its first block zlib-compressed, the rest stored, and the
    tail in a fragment."""
    nblocks = len(payload) // block_size
    tail = payload[nblocks * block_size:]
    out = bytearray(96)
    data_start = len(out)
    sizes = []
    for i in range(nblocks):
        blk = payload[i * block_size:(i + 1) * block_size]
        if i == 0:
            z = zlib.compress(blk)
            out += z
            sizes.append(len(z))
        else:
            out += blk
            sizes.append(len(blk) | (1 << 24))
    frag_start = len(out)
    out += tail
    # inode table: the file inode, then the root directory inode
    file_ino = struct.pack("<HHHHII", 2, 0o644, 0, 0, 0, 2) + struct.pack(
        "<IIII", data_start, 0 if tail else 0xFFFFFFFF, 0, len(payload)) + \
        struct.pack("<%dI" % len(sizes), *sizes)
    listing = struct.pack("<IIi", 0, 0, 2) + struct.pack(
        "<HhHH", 0, 0, 2, len(name) - 1) + name.encode()
    root_off = len(file_ino)
    root_ino = struct.pack("<HHHHII", 1, 0o755, 0, 0, 0, 1) + struct.pack(
        "<IIHHI", 0, 2, len(listing) + 3, 0, 3)
    inode_table = len(out)
    out += _meta(file_ino + root_ino)
    dir_table = len(out)
    out += _meta(listing)
    frag_meta = len(out)
    out += _meta(struct.pack("<QII", frag_start, len(tail) | (1 << 24), 0))
    frag_table = len(out)
    out += struct.pack("<Q", frag_meta)
    sb = struct.pack("<4sIIIIHHHHHH", b"hsqs", 2, 0, block_size, 1, 1,
                     block_size.bit_length() - 1, 0, 1, 4, 0)
    sb += struct.pack("<QQQQQQQQ", root_off, len(out), 0, 0xFFFFFFFFFFFFFFFF,
                      inode_table, dir_table, frag_table, 0xFFFFFFFFFFFFFFFF)
    out[:96] = sb
    return bytes(out)


def build_spks(sections):
    """An SPKS archive with ``[(section name, [(path, bytes), ...]), ...]``."""
    out = b"SPKS" + b"\xff\xff\xff\xff" + struct.pack("<III", 0x6A6F4697, 2,
                                                      len(sections))
    for sname, files in sections:
        strs, recs, data = b"", b"", b""
        for path, blob in files:
            noff = len(strs)
            strs += path.encode() + b"\x00"
            recs += b"FINF" + struct.pack("<I", 60) + struct.pack(
                "<IIIII", noff, len(blob), len(data), len(blob), 0o100644) \
                + b"\x00" * 40
            data += blob
        nm = sname.encode() + b"\x00"
        nm += b"\x00" * (-len(nm) % 4)
        out += b"SPK0" + b"\xff\xff\xff\xff" + b"\x00" * 8
        out += b"SIDX" + struct.pack("<I", 8) + nm
        out += b"STRS" + struct.pack("<I", len(strs)) + strs + recs
        out += b"FEND" + b"\x00" * 4 + b"SDAT" + b"\x00" * 4 + data
    return out


GAME_IMAGE = bytes(range(256)) * 40          # 10240 bytes
MENU_IMAGE = b"menu" * 100
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000


def build_package():
    spks = build_spks([
        ("spike", [("usr/local/spike/spike_menu/image.bin", MENU_IMAGE),
                   ("usr/local/spike/spike_menu/game", ARM_ELF),
                   ("usr/local/spike/SternLogo.png", b"\x89PNG\r\n\x1a\n")]),
        ("iron_maiden_le", [("iron_maiden_le/game", ARM_ELF),
                            ("iron_maiden_le/image.bin", GAME_IMAGE),
                            ("iron_maiden_le/video/attract.mp4", VIDEO)]),
    ])
    return build_squashfs("iron_maiden_le-1_18_0.spk", spks), spks


def write_zip(path, payload, part=1 << 16):
    parts = [payload[i:i + part] for i in range(0, len(payload), part)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, p in enumerate(parts):
            z.writestr("%s.%03d.%03d" % (
                os.path.basename(path)[:-len(".zip")], len(parts), i), p)
    return path


# --------------------------------------------------------------------------
# SquashFS reader
# --------------------------------------------------------------------------
def test_squashfs_reads_blocks_and_fragment():
    payload = os.urandom(4096 * 3 + 777)
    img = build_squashfs("blob.bin", payload)
    sq = SQ.SquashfsReader(io.BytesIO(img))
    entries = list(sq.walk())
    assert [p for p, _i in entries] == ["blob.bin"]
    ino = entries[0][1]
    assert ino.is_file and ino.size == len(payload)
    for off, n in ((0, 10), (4090, 20), (4096 * 3 - 5, 100), (100, 99999),
                   (len(payload) - 1, 5), (len(payload), 5)):
        assert sq.read(ino, off, n) == payload[off:off + n]
    assert sq.compressor == "gzip"


def test_squashfs_rejects_other_files():
    with pytest.raises(SQ.SquashfsError):
        SQ.SquashfsReader(io.BytesIO(b"LUKS\xba\xbe" + b"\x00" * 200))


# --------------------------------------------------------------------------
# the package as card volumes
# --------------------------------------------------------------------------
def test_package_volumes_mirror_the_card(tmp_path):
    img, _spks = build_package()
    raw = tmp_path / "pkg.spk"
    raw.write_bytes(img)
    with S2.SpkPackage(str(raw)) as pkg:
        assert pkg.game_sections == ["iron_maiden_le"]
        games, osv = pkg.volumes
        assert (games.name, osv.name) == ("iron_maiden_le", "spike")
        img_ino, fw_ino = games.find_spike_assets()
        assert games.read_file_bytes(games.read_inode(img_ino)) == GAME_IMAGE
        assert games.is_arm_elf(games.read_inode(fw_ino))
        paths = sorted(p for p, _i, _n in games.iter_regular_files())
        # entries come in the archive's order (the card's directory order)
        top = [n for n, _c, _t in games._iter_dir(games.read_inode(games._dirs["iron_maiden_le/"]))]
        assert top == ["game", "image.bin", "video"]
        assert paths == ["/iron_maiden_le/game", "/iron_maiden_le/image.bin",
                         "/iron_maiden_le/video/attract.mp4"]
        node = games.read_inode(img_ino)
        assert games.read_range(node, 300, 50) == GAME_IMAGE[300:350]
        assert b"".join(d for _o, d in games.read_file_chunks(node, 999)) \
            == GAME_IMAGE
        out = tmp_path / "image.bin"
        games.extract_file(node, str(out))
        assert out.read_bytes() == GAME_IMAGE


def test_engine_locates_the_game_not_the_boot_menu(tmp_path):
    """The OS section carries the boot menu's own image.bin + game: the
    extract must take the game section's, as on a card."""
    from pinball_decryptor.plugins.stern import engine
    img, _spks = build_package()
    raw = tmp_path / "pkg.spk"
    raw.write_bytes(img)
    with S2.SpkPackage(str(raw)) as pkg:
        disk = S2._PackageFile(str(raw))
        try:
            reader, fw, im = engine._locate(disk, list(pkg.volumes))
            assert reader is pkg.volumes[0]
            assert im["size"] == len(GAME_IMAGE)
            work = tmp_path / "work"
            work.mkdir()
            gr, ip, *_ = engine._extract_inputs(disk, list(pkg.volumes),
                                                str(work), lambda *a, **k: None)
            assert open(ip, "rb").read() == GAME_IMAGE
            r, node = engine._boot_screen_dir(disk, list(pkg.volumes),
                                              games_base=reader.base)
            assert r is pkg.volumes[1] and node is not None
        finally:
            disk.close()


# --------------------------------------------------------------------------
# detection + routing
# --------------------------------------------------------------------------
def test_spike2_zip_is_not_spike3(tmp_path):
    from pinball_decryptor.plugins.stern import spike3_spk as S3
    img, _ = build_package()
    z = write_zip(str(tmp_path / "iron_maiden_le-1_18_0.spk.zip"), img)
    assert S2.package_kind(z) == "spike2"
    assert S2.is_spike2_spk(z)
    assert not S3.is_spk_input(z)
    # a Spike 3 package with the same name shape still is one
    z3 = write_zip(str(tmp_path / "pokemon_le-0_87_0.spk.zip"),
                   b"LUKS\xba\xbe\x00\x02" + b"\x00" * 5000)
    assert S2.package_kind(z3) == "spike3"
    assert S3.is_spk_input(z3)
    assert not S2.is_spike2_spk(z3)
    # by name alone (nothing to read): _spike2 is never Spike 3
    assert not S3.is_spk_input("godzilla_le-1_17_0_spike2.spk.zip")
    assert S3.is_spk_input("pokemon_le-0_87_0_spike3.spk.zip")


def test_spike2_package_detected_and_routed(tmp_path):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    img, _ = build_package()
    z = write_zip(str(tmp_path / "iron_maiden_le-1_18_0.spk.zip"), img)
    m = SternManufacturer()
    g = m.detect(z)
    assert g is not None and g.era == "spike2"
    assert "Spike 2 update package" in g.notes
    assert "Spike 3" not in g.display
    m.set_era("spike2")
    p = m.make_extract_pipeline(z, str(tmp_path / "out"),
                                lambda *a: None, lambda *a: None,
                                lambda *a: None, lambda *a: None)
    assert isinstance(p, S2.Spike2SpkExtractPipeline)


def test_unpack_zip_and_split_parts(tmp_path):
    img, _ = build_package()
    z = write_zip(str(tmp_path / "x.spk.zip"), img, part=3000)
    out = tmp_path / "a.spk"
    assert S2.unpack_package(z, str(out)) == str(out)
    assert out.read_bytes() == img
    # the same parts loose on disk, any one of them picked
    n = -(-len(img) // 3000)
    for i in range(n):
        (tmp_path / ("y.spk.%03d.%03d" % (n, i))).write_bytes(
            img[i * 3000:(i + 1) * 3000])
    pick = str(tmp_path / ("y.spk.%03d.%03d" % (n, n - 1)))
    assert S2.package_kind(pick) == "spike2"
    assert S2.needs_unpack(pick)
    out2 = tmp_path / "b.spk"
    S2.unpack_package(pick, str(out2))
    assert out2.read_bytes() == img
    # a raw .spk is read in place
    raw = tmp_path / "z.spk"
    raw.write_bytes(img)
    assert not S2.needs_unpack(str(raw)) and S2.is_spike2_spk(str(raw))


def test_spike3_reconstruct_joins_split_parts(tmp_path):
    from pinball_decryptor.plugins.stern import spike3_spk as S3
    blob = b"LUKS\xba\xbe" + os.urandom(7000)
    for i, part in enumerate((blob[:4000], blob[4000:])):
        (tmp_path / ("f.spk.002.%03d" % i)).write_bytes(part)
    out = tmp_path / "f.spk"
    S3.reconstruct_spk(str(tmp_path / "f.spk.002.000"), str(out))
    assert out.read_bytes() == blob


# --------------------------------------------------------------------------
# PAD-1644: a package is not a card (Modes, the emulator, Write)
# --------------------------------------------------------------------------
def test_package_says_it_is_not_a_card(tmp_path):
    for name in ("iron_maiden_le-1_18_0.spk.zip", "x-1_00_0.spk", "x-1_00_0.spk.002.001"):
        why = S2.not_a_card_words(str(tmp_path / name))
        assert why.startswith(name + " is Stern's game code download")
        assert "SD card image" in why and "download this game's SD card image" in why
    for name in ("iron_maiden_le-1_18_0.Release.16G.sdcard.raw", "card.img", "", None):
        assert S2.not_a_card_words(name) == ""
    # a package renamed past its .spk name is told by its first bytes, when asked to look
    img, _ = build_package()
    renamed = write_zip(str(tmp_path / "renamed.zip"), img)
    assert S2.not_a_card_words(renamed) == ""
    assert "game code download" in S2.not_a_card_words(renamed, look=True)


def test_modes_card_reader_names_the_package(tmp_path):
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    img, _ = build_package()
    z = write_zip(str(tmp_path / "iron_maiden_le-1_18_0.spk.zip"), img)
    with pytest.raises(MT.TryItError) as e:
        MT.card_title(z)
    assert "not an SD card image" in str(e.value)
    assert "no games partition" not in str(e.value)
    renamed = write_zip(str(tmp_path / "renamed.zip"), img)
    with pytest.raises(MT.TryItError, match="not an SD card image"):
        MT.card_title(renamed)


def test_write_refuses_a_package_original(tmp_path):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    img, _ = build_package()
    z = write_zip(str(tmp_path / "iron_maiden_le-1_18_0.spk.zip"), img)
    m = SternManufacturer()
    m.set_era("spike2")
    why = m.write_preflight(z, str(tmp_path))
    assert why and "not an SD card image" in str(why)
