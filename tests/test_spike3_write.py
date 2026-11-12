"""PAD-1186: the Spike 3 Write - the games volume written back through its
own encryption, sounds put back into image.bin, files grown through
dm-crypt, and the card store telling a rebuilt card from the last.

Synthetic data only: no Stern files, no keys (random volume keys).
"""
import io
import os
import struct
import sys
import wave
import zlib

import pytest

from pinball_decryptor.plugins.stern import spike3 as S3
from pinball_decryptor.plugins.stern import spike3_card as C
from pinball_decryptor.plugins.stern import spike3_sound as SND
from pinball_decryptor.plugins.stern import spike3_write as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -- the volume -----------------------------------------------------------------

class _Header:
    """What DecryptingSegmentReader reads off a LUKS2 header."""

    def __init__(self, sectors, seg_off=4096):
        self._seg = {"encryption": "aes-xts-plain64", "sector_size": 512,
                     "offset": str(seg_off)}
        self._pad_part_sectors = sectors

    def segment(self, _idx):
        return self._seg


def _volume(n_sectors=64, base_lba=8, seg_off=4096):
    otp = S3._luks_otp()
    key = os.urandom(64)
    plain = bytes(range(256)) * (n_sectors * 2)
    ct = otp.aes_xts_encrypt(key, plain[:n_sectors * 512], 0, 512)
    disk = bytearray(base_lba * 512 + seg_off) + bytearray(ct)
    f = io.BytesIO(bytes(disk))
    part = {"start_lba": base_lba, "sectors": n_sectors + seg_off // 512,
            "index": 6}
    hdr = _Header(part["sectors"], seg_off)
    return f, part, hdr, key, plain[:n_sectors * 512], bytes(disk)


def test_volume_write_reads_back_and_touches_only_its_sectors():
    f, part, hdr, key, plain, before = _volume()
    vol = C.GamesVolume(f, part, hdr, key, writable=True)
    assert vol.pad_spike3 and vol.size == 64 * 512
    data = b"PAD-1186 spans three sectors " * 40          # 1160 bytes
    vol.seek(1000)
    vol.write(data)
    assert vol.sectors_written == 4                      # 1000..2159 -> 1..4
    vol.seek(1000)
    assert vol.read(len(data)) == data
    vol.seek(0)
    whole = vol.read(vol.size)
    assert whole[:1000] == plain[:1000]
    assert whole[1000 + len(data):] == plain[1000 + len(data):]
    # a fresh reader (no cache) decrypts the same: the sectors were
    # re-encrypted under their own tweaks
    f.seek(0)
    fresh = S3.DecryptingSegmentReader(f, part["start_lba"], hdr, key)
    fresh.seek(0)
    assert fresh.read(fresh.size) == whole
    after = f.getvalue()
    base = part["start_lba"] * 512 + 4096
    changed = {i for i in range(64)
               if after[base + i * 512:base + (i + 1) * 512]
               != before[base + i * 512:base + (i + 1) * 512]}
    assert changed == {1, 2, 3, 4}
    assert after[:base] == before[:base]                 # header untouched


def test_volume_refuses_writes_read_only_and_past_the_end():
    f, part, hdr, key, _plain, _before = _volume()
    ro = C.GamesVolume(f, part, hdr, key)
    with pytest.raises(OSError):
        ro.write(b"x")
    rw = C.GamesVolume(f, part, hdr, key, writable=True)
    rw.seek(rw.size - 2)
    with pytest.raises(OSError):
        rw.write(b"xyz")


# -- sounds ---------------------------------------------------------------------

class _Node(dict):
    pass


class _Reader:
    """An Ext4Reader stand-in over in-memory files {path: bytes}."""

    def __init__(self, files, main):
        self.files = files
        self.main = main
        self.nodes = {p: _Node(size=len(b), path=p) for p, b in files.items()}

    def find_spike_assets(self):
        return hash(self.main), None

    def iter_regular_files(self, min_size=1, max_depth=12, root_ino=2):
        for p, n in self.nodes.items():
            yield p, hash(p), n

    def read_range(self, node, off, n):
        return self.files[node["path"]][off:off + n]

    def read_file_chunks(self, node, chunk=64):         # small: crosses chunks
        b = self.files[node["path"]]
        for i in range(0, len(b), chunk):
            yield i, b[i:i + chunk]                  # as Ext4Reader: (offset, bytes)

    def read_file_bytes(self, node):
        return self.files[node["path"]]

    def disk_ranges(self, node, off, n):
        return [(off, n)]


def _container_bytes(tmp_path):
    p = str(tmp_path / "c.bin")
    SND._synth_container(p)              # idx0 mono 100 frames, idx1 stereo 50
    with open(p, "rb") as f:
        return f.read()


def _wav(path, frames, ch, value=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<h", value) * frames * ch)


def _project(tmp_path, reader, cont):
    """A project extracted from *reader*: the WAVs and the baseline."""
    from pinball_decryptor.core.checksums import generate_checksums
    proj = tmp_path / "proj"
    for card_path, node, folder in W.project_sound_dirs(reader):
        d = proj / folder
        d.mkdir(parents=True)
        src = tmp_path / ("src_%s.bin" % folder)
        src.write_bytes(reader.files[card_path])
        SND.decode_container(str(src), str(d))
    generate_checksums(str(proj))
    return proj


def test_sound_folders_keep_the_two_sets_apart(tmp_path):
    cont = _container_bytes(tmp_path)
    r = _Reader({"/pk/image.bin": cont,
                 "/pk/spike3/spike_menu/image.bin": cont}, "/pk/image.bin")
    got = [(p, f) for p, _n, f in W.project_sound_dirs(r)]
    assert got == [("/pk/image.bin", "audio"),
                   ("/pk/spike3/spike_menu/image.bin", "audio_spike_menu")]


def test_a_shorter_sound_plays_its_own_length_in_place(tmp_path):
    cont = _container_bytes(tmp_path)
    r = _Reader({"/pk/image.bin": cont}, "/pk/image.bin")
    proj = _project(tmp_path, r, cont)
    _wav(proj / "audio" / "idx0000.wav", 60, 1, 5000)
    from pinball_decryptor.core.checksums import read_checksums
    plans = W.plan_sounds(r, str(proj), read_checksums(str(proj)),
                          str(tmp_path), lambda *a: None)
    assert len(plans) == 1
    p = plans[0]
    assert p.staged is None and p.n_fit == 1 and p.padded == [0]
    img = SND.ImageSound(str(tmp_path / "src_audio.bin"))
    # the body, the directory with the new length, and its CRC - in place
    out = bytearray(cont)
    for off, b in p.inplace:
        out[off:off + len(b)] = b
    assert len(out) == len(cont)
    (tmp_path / "new.bin").write_bytes(bytes(out))
    new = SND.ImageSound(str(tmp_path / "new.bin"))
    r0 = new.records[0]
    assert (r0.offset, r0.frames) == (img.records[0].offset, 60)
    assert new.records[1].frames == 50
    assert max(struct.unpack("<60h", new.read_body(r0))) > 4000
    assert struct.unpack_from("<I", out, len(out) - 8)[0] == \
        zlib.crc32(bytes(out[new.md_off:new.md_off + 48]))
    assert [(x.param, x.param2) for x in new.records] == \
        [(x.param, x.param2) for x in img.records]


def test_a_longer_sound_grows_the_container(tmp_path):
    cont = _container_bytes(tmp_path)
    r = _Reader({"/pk/image.bin": cont}, "/pk/image.bin")
    proj = _project(tmp_path, r, cont)
    _wav(proj / "audio" / "idx0001.wav", 80, 2, 3000)     # 50 -> 80 frames
    _wav(proj / "audio" / "idx0000.wav", 100, 1, 2000)    # same length: in place
    from pinball_decryptor.core.checksums import read_checksums
    p, = W.plan_sounds(r, str(proj), read_checksums(str(proj)),
                       str(tmp_path), lambda *a: None)
    assert p.grown == [1] and p.staged
    old = SND.ImageSound(str(tmp_path / "src_audio.bin"))
    new = SND.ImageSound(p.staged)
    new.validate()
    assert new.count == 2 and new.md_off == old.md_off + 80 * 4
    r1 = new.records[1]
    assert (r1.frames, r1.channels) == (80, 2) and r1.offset == old.md_off
    assert max(struct.unpack("<160h", new.read_body(r1))) > 2000
    # the sound that fit went in at its old place, in the same file
    assert new.records[0].offset == old.records[0].offset
    assert max(struct.unpack("<100h", new.read_body(new.records[0]))) > 1500
    # the trailer's first word is the directory's CRC, as on every card
    with open(p.staged, "rb") as f:
        b = f.read()
    d = b[new.md_off:new.md_off + 48]
    assert struct.unpack_from("<I", b, len(b) - 8)[0] == zlib.crc32(d)
    # the records keep their ids (param / param2)
    assert [(x.param, x.param2) for x in new.records] == \
        [(x.param, x.param2) for x in old.records]


def test_unchanged_sounds_plan_nothing(tmp_path):
    cont = _container_bytes(tmp_path)
    r = _Reader({"/pk/image.bin": cont}, "/pk/image.bin")
    proj = _project(tmp_path, r, cont)
    from pinball_decryptor.core.checksums import read_checksums
    assert W.plan_sounds(r, str(proj), read_checksums(str(proj)),
                         str(tmp_path), lambda *a: None) == []


def test_from_parts_reads_like_the_file(tmp_path):
    cont = _container_bytes(tmp_path)
    p = tmp_path / "x.bin"
    p.write_bytes(cont)
    a = SND.ImageSound(str(p))
    hdr = cont[:SND.HEADER_SIZE]
    b = SND.ImageSound.from_parts(hdr, cont[a.md_off:a.md_off + 48], len(cont))
    assert [(r.offset, r.frames, r.channels) for r in a.records] == \
        [(r.offset, r.frames, r.channels) for r in b.records]


# -- growing a file through dm-crypt --------------------------------------------

def test_grow_script_maps_the_volume_with_its_key():
    """The PAD Runtime image has no cryptsetup: the script carries
    core/dmcrypt.py and maps the data segment with python3 (device-mapper
    ioctls), mounts the mapping, and closes it on the way out."""
    from pinball_decryptor.core import ext4_grow
    key = bytes(range(64))
    luks = {"key": key, "offset": 16 << 20, "sector_size": 512,
            "cipher": "aes-xts-plain64"}
    s = ext4_grow._bash_script(1 << 30, [("pk/image.bin", "/w/image.bin")],
                               "/mnt/c/out.raw", luks=luks, part_size=1 << 32)
    assert "--sizelimit %d" % (1 << 32) in s
    assert not [ln for ln in s.splitlines() if ln.lstrip().startswith(
        ("cryptsetup", "dmsetup", "[ -n \"$DM\" ] && cryptsetup"))]
    seg = (16 << 20) // 512
    assert ('python3 "$DMPY" open "$DM" "$LOOP" %d %d "$KF" 512'
            % (seg, (1 << 32) // 512 - seg)) in s
    assert 'mount "$NODE" "$MP"' in s
    assert "def open_crypt(" in s and ext4_grow._DMPY_EOF in s
    assert "\\x00\\x01\\x02" in s and key.hex() not in s
    assert 'python3 "$DMPY" close "$DM"' in s and "PAD_GROW_NOCRYPT" in s
    assert 'cp /w/image.bin "$MP"/pk/image.bin' in s
    # the plain script is the old one
    plain = ext4_grow._bash_script(4096, [("a", "/b")], "/c")
    assert "dmcrypt" not in plain and 'mount "$LOOP" "$MP"' in plain
    # a cipher the helper does not map is refused, not mapped wrong
    with pytest.raises(ext4_grow.Ext4GrowUnavailable, match="aes-cbc"):
        ext4_grow._bash_script(0, [("a", "/b")], "/c", part_size=1 << 30,
                               luks=dict(luks, cipher="aes-cbc-essiv:sha256"))


def test_dmcrypt_ioctl_layout_and_table():
    """struct dm_ioctl is 312 bytes, dm_target_spec 40; the crypt table
    names the cipher, the key, the device and the data offset, padded to 8."""
    from pinball_decryptor.core import dmcrypt as D
    assert D._DM_SIZE == 312 and D._SPEC_SIZE == 40
    assert D._ioc(3) == 0xC138FD03                    # DM_DEV_CREATE
    t = D.crypt_table("/dev/loop7", 32768, 1000, bytes(range(64)))
    import struct as _s
    start, length, status, nxt, typ = _s.unpack(D._SPEC_FMT, t[:40])
    assert (start, length, nxt, typ.rstrip(b"\0")) == (0, 1000, len(t), b"crypt")
    assert len(t) % 8 == 0
    params = t[40:].rstrip(b"\0").decode()
    assert params == "aes-xts-plain64 %s 0 /dev/loop7 32768" % bytes(range(64)).hex()
    t4k = D.crypt_table("/dev/loop7", 0, 8, b"k" * 64, sector_size=4096)
    assert t4k[40:].rstrip(b"\0").endswith(b" 1 sector_size:4096")
    h = D._header("pad_s3_1", 312)
    f = _s.unpack(D._DM_FMT, h)
    assert f[:5] == (4, 0, 0, 312, 312) and f[11].rstrip(b"\0") == b"pad_s3_1"
    # huge_encode_dev of 254:0 and 254:300
    assert D._decode_dev((254 << 8) | 0) == (254, 0)
    assert D._decode_dev(((300 & 0xff) | (254 << 8) | ((300 & ~0xff) << 12))) == (254, 300)


def test_grow_refuses_an_encrypted_card_where_debugfs_writes(monkeypatch, tmp_path):
    from pinball_decryptor.core import ext4_grow
    src = tmp_path / "f"
    src.write_bytes(b"x")
    monkeypatch.setattr(ext4_grow, "uses_debugfs", lambda platform=None: True)
    with pytest.raises(ext4_grow.Ext4GrowUnavailable, match="dm-crypt"):
        ext4_grow.grow_files(str(tmp_path / "c.raw"), 0, [("a", str(src))],
                             luks={"key": b"k" * 64, "offset": 16 << 20},
                             part_size=1 << 30)


# -- the card store tells a rebuilt card from the last ---------------------------

def test_store_id_follows_the_build_record(tmp_path):
    rig = os.path.join(ROOT, "tools", "spike3_emu")
    if rig not in sys.path:
        sys.path.insert(0, rig)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import s3store
    from test_spike3_store import _card
    img = _card(str(tmp_path / "pk-0_82_0.Release.64G.sdcard-secure.raw"))
    stock = s3store.card_id(img)
    W._write_record(img, img, complete=True)
    one = s3store.card_id(img)
    W._write_record(img, img, complete=True)
    two = s3store.card_id(img)
    assert len({stock, one, two}) == 3
    os.remove(img + s3store.BUILD_RECORD)
    assert s3store.card_id(img) == stock


# -- the app: tabs, Write and the video rules on a Spike 3 card -------------------

def _stern(era):
    from pinball_decryptor.plugins.stern.manufacturer import SternManufacturer
    m = SternManufacturer()
    m.set_era(era)
    return m


def test_spike3_offers_the_replace_tabs_and_write():
    m = _stern("spike3")
    caps = m.capabilities
    for c in ("extract", "write", "replace_audio", "replace_video",
              "replace_image", "replace_text", "emulate"):
        assert getattr(caps, c), c
    assert not caps.dmd_shades and not caps.modes          # Scenes on, no modes
    assert m.write_output_ext() == ".raw"
    assert tuple(m.write_phases) == W.PHASES
    p = m.make_write_pipeline("in.raw", "proj", "out.raw", *([lambda *a, **k: None] * 4))
    assert isinstance(p, W.Spike3WritePipeline)
    assert not m.colour_profile_on_display()   # the profile goes into the files
    assert m.video_codecs() == ("h264", "hevc")
    assert _stern("spike2").video_codecs() == ("h264",)


def test_video_rules_take_the_machines_codecs(monkeypatch):
    from types import SimpleNamespace as NS
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import video_helpers as vh
    from pinball_decryptor.core import video as V
    slot = NS(info=V.VideoInfo("a.mp4", vcodec="hevc", width=1920, height=1080,
                               pix_fmt="yuv420p"), abs_path="a.mp4")
    monkeypatch.setattr(V, "backend_for", lambda p: None)
    for era, plays in (("spike3", True), ("spike2", False)):
        compat.install(NS(window=NS(current_mfr=_stern(era))))
        try:
            why = vh.slot_unplayable("stern", slot)
        finally:
            compat.uninstall()
        assert (why is None) is plays, (era, why)
    assert why == "is HEVC and the machine plays H.264"     # Spike 2's words
    # no app context (a script, a test): Spike 2's rule
    assert vh.machine_codecs() == ("h264",)


def test_a_profiled_clip_never_goes_on_as_the_users_file(monkeypatch):
    """On a Spike 3 card a color profile reaches the machine only baked into
    the converted copy, so that copy goes on whole, not the user's file."""
    from types import SimpleNamespace as NS
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.core import colour_profile as CP
    edits = [("a.mp4", "/g/1.asset", "s/a.mp4"), ("b.mp4", "/g/2.asset", "s/b.mp4")]
    s3, s2 = NS(pad_spike3=True), NS()
    monkeypatch.setattr(CP, "active", lambda d: object())
    assert E._colour_baked_videos("p", edits, s3) == {"video/a.mp4", "video/b.mp4"}
    assert E._colour_baked_videos("p", edits, s2) == set()      # Spike 2: shaders
    monkeypatch.setattr(CP, "active", lambda d: None)
    monkeypatch.setattr(CP, "asset_map", lambda d, kind, rels: {"video/b.mp4": 1})
    assert E._colour_baked_videos("p", edits, s3) == {"video/b.mp4"}
