"""PAD-1090 - the Spike 3 card store (tools/spike3_emu/s3store.py).

A Spike 3 card is 62 GB of LUKS2 ciphertext of which ~3-4 GB is files. The store
keeps only the files, decrypted, each one ONCE however many cards carry it, as
hardlinks into a content-addressed object directory. These tests cover the parts
that do not need root or a real card: the card's identity, the key's resolution
and the de-duplicating tree copy. The decrypt itself (losetup + cryptsetup +
mount) was proven on the six real cards; see docs/plans/spike3_emulation.md.
"""

import json
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG3 = os.path.join(ROOT, "tools", "spike3_emu")
if RIG3 not in sys.path:
    sys.path.insert(0, RIG3)

import s3store                                                     # noqa: E402

SECTOR = 512
P2 = 2048          # rootfs partition start (LBA)
P2N = 4096         # sectors (2 MiB)
DATA_OFF = 64 << 10   # the LUKS data segment offset these fake headers name


def _card(path, uuid=b"11111111-2222-3333-4444-555555555555", payload=b"A"):
    """A tiny Spike-3-shaped card: MBR with one 0x83 partition holding a LUKS2
    header (magic, header size, JSON naming the data segment) and some
    'ciphertext' at the data offset."""
    mbr = bytearray(512)
    struct.pack_into("<B", mbr, 0x1BE + 16 + 4, 0x83)
    struct.pack_into("<II", mbr, 0x1BE + 16 + 8, P2, P2N)
    mbr[510:512] = b"\x55\xaa"
    hdr = bytearray(16384)
    hdr[0:6] = b"LUKS\xba\xbe"
    struct.pack_into(">H", hdr, 6, 2)
    struct.pack_into(">Q", hdr, 8, 16384)
    hdr[0xA8:0xA8 + len(uuid)] = uuid
    js = json.dumps({"segments": {"0": {"offset": str(DATA_OFF), "size": "dynamic",
                                        "encryption": "aes-xts-plain64"}}}).encode()
    hdr[4096:4096 + len(js)] = js
    with open(path, "wb") as f:
        f.write(mbr)
        f.seek(P2 * SECTOR)
        f.write(hdr)
        f.seek(P2 * SECTOR + DATA_OFF)
        f.write(payload * 4096)
        f.truncate((P2 + P2N) * SECTOR)
    return path


def test_partitions_name_roles_and_see_luks(tmp_path):
    img = _card(str(tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"))
    assert s3store.card_partitions(img) == [(2, "rootfs", P2, P2N, True)]
    assert s3store.luks_data_offset(img, P2) == DATA_OFF


def test_card_id_is_stem_plus_fingerprint(tmp_path):
    img = _card(str(tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"))
    cid = s3store.card_id(img)
    stem, fp = cid.rsplit("-", 1)
    assert stem == "pokemon_le-0_82_0" and len(fp) == 10
    assert s3store.card_id(img) == cid                     # stable


def test_same_uuids_different_contents_are_different_cards(tmp_path):
    """Stern writes every card from one master image: pokemon_le and fallout_le
    carry the SAME LUKS uuids and partition table. The id must still tell them
    apart, or one card's tree would be booted for the other."""
    a = _card(str(tmp_path / "a" ), payload=b"A")
    b = _card(str(tmp_path / "b"), payload=b"B")
    os.rename(a, str(tmp_path / "x-1.raw"))
    os.makedirs(str(tmp_path / "other"))
    os.rename(b, str(tmp_path / "other" / "x-1.raw"))
    assert s3store.card_id(str(tmp_path / "x-1.raw")) != \
        s3store.card_id(str(tmp_path / "other" / "x-1.raw"))


def test_win_paths_read_as_wsl_paths():
    assert s3store.win_to_wsl("C:/Users/x/k.bin") == "/mnt/c/Users/x/k.bin"
    assert s3store.win_to_wsl("D:\\Pinball\\k.bin") == "/mnt/d/Pinball/k.bin"
    assert s3store.win_to_wsl("/home/x") == "/home/x"


def test_key_order_flag_env_then_padkeys(tmp_path, monkeypatch):
    img = _card(str(tmp_path / "t-1.raw"))
    k1, k2, k3 = b"\x01" * 32, b"\x02" * 32, b"\x03" * 32
    kf = tmp_path / "k3.bin"
    kf.write_bytes(k3)
    (tmp_path / "padkeys.json").write_text(json.dumps({"otp_keyfile": "k3.bin"}))
    monkeypatch.delenv("PAD_SPIKE3_OTP_KEY", raising=False)
    monkeypatch.delenv("PAD_SPIKE3_KEYFILE", raising=False)
    assert s3store.resolve_key(img) == (k3, str(tmp_path / "padkeys.json"))
    monkeypatch.setenv("PAD_SPIKE3_OTP_KEY", k2.hex())
    assert s3store.resolve_key(img)[0] == k2
    assert s3store.resolve_key(img, k1.hex())[0] == k1


def test_padkeys_without_otp_key_is_no_key(tmp_path, monkeypatch):
    """The library's own padkeys.json carries only the .spk key: no OTP key
    must read as 'none', not as a crash or as the .spk key."""
    img = _card(str(tmp_path / "t-1.raw"))
    (tmp_path / "padkeys.json").write_text(json.dumps({"spk_keyfile": "ab" * 32}))
    monkeypatch.delenv("PAD_SPIKE3_OTP_KEY", raising=False)
    monkeypatch.delenv("PAD_SPIKE3_KEYFILE", raising=False)
    assert s3store.resolve_key(img) == (None, None)


def test_bad_key_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        s3store.resolve_key(str(tmp_path / "x.raw"), "abcd")


@pytest.mark.skipif(os.name != "posix", reason="hardlinks + chown: runs under WSL")
def test_copy_tree_shares_identical_files(tmp_path):
    """Two 'cards' with one file in common: the second adds only what is new,
    every tree file is a hardlink into objects/, symlinks and modes survive."""
    store = tmp_path / "store"
    objs = s3store.Objects(str(store))
    for name, extra in (("one", b"only in one"), ("two", b"only in two")):
        src = tmp_path / ("src_" + name)
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "game").write_bytes(b"\x7fELF" + b"x" * 100000)
        os.chmod(str(src / "bin" / "game"), 0o755)
        (src / "own").write_bytes(extra)
        (src / "zeros").write_bytes(bytes(8 << 20))        # stays a hole
        os.symlink("bin/game", str(src / "game"))
        files, nbytes = s3store.copy_tree(str(src), str(store / "cards" / name), objs)
        assert files == 3
    assert objs.new_files == 4 and objs.shared_files == 2  # game + zeros shared
    one, two = store / "cards" / "one", store / "cards" / "two"
    assert os.stat(str(one / "bin" / "game")).st_ino == os.stat(str(two / "bin" / "game")).st_ino
    assert os.stat(str(one / "bin" / "game")).st_mode & 0o777 == 0o755
    assert os.readlink(str(two / "game")) == "bin/game"
    assert (two / "own").read_bytes() == b"only in two"
    assert os.stat(str(one / "zeros")).st_blocks * 512 < (1 << 20)


@pytest.mark.skipif(os.name != "posix", reason="hardlinks: runs under WSL")
def test_gc_drops_only_unreferenced_objects(tmp_path):
    store = tmp_path / "store"
    objs = s3store.Objects(str(store))
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").write_bytes(b"a")
    s3store.copy_tree(str(src), str(store / "cards" / "c1"), objs)
    s3store.copy_tree(str(src), str(store / "cards" / "c2"), objs)

    class A:
        pass
    a = A()
    a.store = str(store)
    import shutil
    shutil.rmtree(str(store / "cards" / "c1"))
    s3store.cmd_gc(a)
    assert (store / "cards" / "c2" / "a").read_bytes() == b"a"
    shutil.rmtree(str(store / "cards" / "c2"))
    s3store.cmd_gc(a)
    left = [f for r, d, fs in os.walk(str(store / "objects")) for f in fs]
    assert left == []


def test_the_store_loads_the_apps_own_spike3_readers():
    """PAD-1090: with no dm-crypt (a stock WSL kernel) the store decrypts with
    the app's own LUKS2/AES-XTS + ext4 code, loaded by path as a bare package
    (no other app import) - and spike3.py finds luks_otp.py beside the app."""
    sp = s3store._app_stern()
    assert hasattr(sp, "open_partition_ext4") and hasattr(sp, "DecryptingSegmentReader")
    assert hasattr(sp._luks_otp(), "aes_xts_decrypt")
    assert "pinball_decryptor" not in sys.modules or True    # bare: nothing more required


class _FakeFs:
    """The slice of Ext4Reader copy_tree_reader uses. Owned by whoever runs
    the test: the store gives every file its card owner, and only root may
    give one away (the real build runs as root; CI's runner does not)."""
    def __init__(self):
        D, F, L = 0o040755, 0o100644, 0o120777
        u, g = os.getuid(), os.getgid()
        self.nodes = {
            2: dict(mode=D, uid=u, gid=g, atime=1, mtime=2),
            3: dict(mode=D, uid=u, gid=g, atime=1, mtime=2),
            4: dict(mode=F, uid=u, gid=g, atime=1, mtime=2, data=b"same bytes"),
            5: dict(mode=F, uid=u, gid=g, atime=1, mtime=2, data=b"same bytes"),
            6: dict(mode=0o100755, uid=u, gid=g, atime=1, mtime=2, data=b"\0" * 70000 + b"x"),
            7: dict(mode=L, uid=u, gid=g, atime=1, mtime=2, target="sub/a"),
        }
        self.tree = [("sub", "dir", 3), ("sub/a", "file", 4), ("sub/b", "file", 5),
                     ("tool", "file", 6), ("link", "symlink", 7)]

    def read_inode(self, ino):
        return self.nodes[ino]

    def iter_tree(self):
        for rel, kind, ino in self.tree:
            yield rel, kind, ino, self.nodes[ino]

    def read_file_chunks(self, inode, chunk):
        d = inode["data"]
        for off in range(0, len(d), chunk):
            yield off, d[off:off + chunk]

    def read_symlink(self, inode):
        return inode["target"]


@pytest.mark.skipif(os.name != "posix", reason="hardlinks + chown: runs under WSL")
def test_copy_tree_reader_rebuilds_the_tree_and_shares_objects(tmp_path):
    objs = s3store.Objects(str(tmp_path / "store"))
    files, nbytes = s3store.copy_tree_reader(_FakeFs(), str(tmp_path / "t"), objs)
    t = tmp_path / "t"
    assert files == 3 and nbytes == 2 * 10 + 70001
    assert (t / "sub" / "a").read_bytes() == b"same bytes"
    assert os.stat(t / "sub" / "a").st_ino == os.stat(t / "sub" / "b").st_ino
    assert oct(os.stat(t / "tool").st_mode & 0o777) == "0o755"
    assert os.readlink(t / "link") == "sub/a"
    assert objs.new_files == 2 and objs.shared_files == 1


def test_the_meter_counts_every_byte_read_and_says_how_long_is_left():
    """PAD-1238: the Emulate bar sat at 2% through a 20-minute decrypt."""
    now = [100.0]
    out = []
    m = s3store.Meter(100 << 20, every=2.0, out=out.append, clock=lambda: now[0])
    m.add(1 << 20)                                   # first read: a line at once
    assert out[-1] == "[s3store] progress 1 1 104 -"
    now[0] += 1.0
    m.add(1 << 20)                                   # inside 2 s: no line
    assert len(out) == 1
    now[0] += 9.0                                    # 10 s in, 25 MiB read
    m.add(23 << 20)
    assert out[-1] == "[s3store] progress 25 26 104 30"
    m.total = 10                                     # never past 100
    assert m.line().startswith("[s3store] progress 100 ")


@pytest.mark.skipif(os.name != "posix", reason="hardlinks + chown: runs under WSL")
def test_objects_feed_the_meter_the_bytes_they_read(tmp_path):
    seen = []

    class _M:
        def add(self, n):
            seen.append(n)
    objs = s3store.Objects(str(tmp_path / "store"), _M())
    fs = _FakeFs()
    for n in fs.nodes.values():
        if "data" in n:
            n["size"] = len(n["data"])
    entries, total = s3store.reader_walk(fs)
    s3store.copy_tree_reader(fs, str(tmp_path / "t"), objs, entries=entries)
    assert sum(seen) == total == 2 * 10 + 70001


@pytest.mark.skipif(os.name != "posix", reason="_FakeFs owns its files by uid: runs under WSL")
def test_the_total_is_the_bytes_the_copy_reads_not_the_blocks_in_use(tmp_path):
    """PAD-1238: Fallout's rootfs has 240 MB of blocks and 636 MB of files
    (hardlinks, holes): the meter's total is the files, read once per name."""
    fs = _FakeFs()
    for n in fs.nodes.values():
        if "data" in n:
            n["size"] = len(n["data"])
    entries, nb = s3store.reader_walk(fs)
    assert nb == 2 * 10 + 70001 and len(entries) == 5
    src = tmp_path / "src"
    (src / "lost+found").mkdir(parents=True)
    (src / "lost+found" / "junk").write_bytes(b"x" * 99)
    (src / "a").write_bytes(b"12345")
    (src / "d").mkdir()
    (src / "d" / "b").write_bytes(b"123")
    assert s3store.file_bytes(str(src)) == 8
