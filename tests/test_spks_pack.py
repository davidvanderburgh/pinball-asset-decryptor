"""Round-trip tests for the SPKS writer (:mod:`...plugins.stern.spks_pack`).

Everything here is self-contained: pack synthetic packages, read them back with
the verified :class:`.spks.SpksArchive`, and assert the tree survives. No key
material, no real packages.
"""

import hashlib
import hmac as _hmac
import io
import os

import pytest

from pinball_decryptor.plugins.stern import spks_pack as sp
from pinball_decryptor.plugins.stern import spks as spks_reader


def _reader_over(buf: bytes):
    def read(off, n):
        return buf[off:off + n]
    return read


def _archive(buf: bytes):
    return spks_reader.SpksArchive(_reader_over(buf), len(buf))


def _pkg(name="spike", shortname="spk", version=(1, 2, 3), files=None):
    return sp.SpksPackage(type=sp.PACKAGE_TYPES["SPIKE_3"], name=name,
                          shortname=shortname, version=version,
                          files=files or [])


def test_roundtrip_single_package():
    data_a = b"hello world\n" * 10
    data_b = b"\x01\x02\x03\x04" * 64
    pkg = _pkg(files=[
        sp.file_from_bytes("mfs/sd/a.txt", data_a, mode=0o100644),
        sp.file_from_bytes("mfs/sd/b.bin", data_b, mode=0o100600),
    ])
    out = io.BytesIO()
    sp.write_spks(out, [pkg])
    buf = out.getvalue()

    arc = _archive(buf)
    got = {f.path: f for f in arc.files}
    assert set(got) == {"mfs/sd/a.txt", "mfs/sd/b.bin"}
    assert got["mfs/sd/a.txt"].size == len(data_a)
    assert got["mfs/sd/a.txt"].mode == 0o100644
    assert got["mfs/sd/b.bin"].mode == 0o100600
    assert b"".join(arc.read_file(got["mfs/sd/a.txt"])) == data_a
    assert b"".join(arc.read_file(got["mfs/sd/b.bin"])) == data_b


def test_roundtrip_multi_package():
    pkg1 = _pkg(name="spike", files=[
        sp.file_from_bytes("x.txt", b"X" * 100)])
    pkg2 = _pkg(name="mygame", shortname="mg", version=(0, 84, 0), files=[
        sp.file_from_bytes("assets/v.asset", b"V" * 500)])
    out = io.BytesIO()
    sp.write_spks(out, [pkg1, pkg2])
    buf = out.getvalue()

    pkgs = sp.parse_packages(_reader_over(buf), len(buf))
    by_name = {p.name: p for p in pkgs}
    assert set(by_name) == {"spike", "mygame"}
    assert by_name["mygame"].shortname == "mg"
    assert by_name["mygame"].version == (0, 84, 0)
    assert by_name["spike"].version == (1, 2, 3)
    assert by_name["mygame"].type == sp.PACKAGE_TYPES["SPIKE_3"]
    assert {f.path for f in by_name["mygame"].files} == {"assets/v.asset"}


def test_unsigned_uses_placeholder_hmac():
    pkg = _pkg(files=[sp.file_from_bytes("a", b"payload-bytes")])
    out = io.BytesIO()
    sp.write_spks(out, [pkg])            # no key
    assert sp._PLACEHOLDER_HMAC in out.getvalue()


def test_signed_hmac_matches_key():
    key = bytes(range(16))               # dummy 16-byte factory key (not real)
    data = b"sign-me" * 20
    pkg = _pkg(files=[sp.file_from_bytes("a", data)])
    out = io.BytesIO()
    sp.write_spks(out, [pkg], hmac_key=key)
    expect = _hmac.new(key, data, hashlib.sha1).digest()
    assert expect in out.getvalue()
    assert sp._PLACEHOLDER_HMAC not in out.getvalue()


def test_md5_is_written():
    data = b"check-md5" * 11
    pkg = _pkg(files=[sp.file_from_bytes("a", data)])
    out = io.BytesIO()
    sp.write_spks(out, [pkg])
    assert hashlib.md5(data).digest() in out.getvalue()


def test_load_factory_hmac_key_forms(tmp_path):
    raw = bytes(range(16))
    assert sp.load_factory_hmac_key(raw) == raw
    assert sp.load_factory_hmac_key(raw.hex()) == raw
    assert sp.load_factory_hmac_key(None) is None
    # a full factory-key file: HMAC key is bytes 0xB0:0xC0
    blob = bytearray(os.urandom(0x100))
    blob[0xB0:0xC0] = raw
    p = tmp_path / "factory.key"
    p.write_bytes(bytes(blob))
    assert sp.load_factory_hmac_key(str(p)) == raw
    with pytest.raises(sp.SpksPackError):
        sp.load_factory_hmac_key(b"too-short")


def test_repack_swaps_file_and_marks(tmp_path):
    orig_a = b"ORIGINAL-A" * 50
    orig_b = b"ORIGINAL-B" * 50
    pkg = _pkg(name="spike", files=[
        sp.file_from_bytes("keep.txt", orig_a),
        sp.file_from_bytes("swap.txt", orig_b),
    ])
    src = io.BytesIO()
    sp.write_spks(src, [pkg])
    src_buf = src.getvalue()

    new_b = b"MODDED-CONTENT" * 7
    out_path = str(tmp_path / "mod.spks")
    sp.repack_spks(_reader_over(src_buf), len(src_buf),
                   {"swap.txt": new_b}, out_path)

    with open(out_path, "rb") as f:
        buf = f.read()
    arc = _archive(buf)
    got = {f.path: f for f in arc.files}
    assert sp.MARK_FILENAME in got                      # not-official mark
    assert b"".join(arc.read_file(got["keep.txt"])) == orig_a     # untouched
    assert b"".join(arc.read_file(got["swap.txt"])) == new_b      # swapped
    assert b"".join(arc.read_file(got[sp.MARK_FILENAME])) == sp.MARK_TEXT


def test_repack_refuses_unmarked():
    pkg = _pkg(files=[sp.file_from_bytes("a", b"x" * 10)])
    src = io.BytesIO()
    sp.write_spks(src, [pkg])
    buf = src.getvalue()
    with pytest.raises(sp.SpksPackError):
        sp.repack_spks(_reader_over(buf), len(buf), {}, "unused.spks",
                       mark=False)


def test_repack_rejects_unknown_path(tmp_path):
    pkg = _pkg(files=[sp.file_from_bytes("a", b"x" * 10)])
    src = io.BytesIO()
    sp.write_spks(src, [pkg])
    buf = src.getvalue()
    with pytest.raises(sp.SpksPackError):
        sp.repack_spks(_reader_over(buf), len(buf),
                       {"does/not/exist": b"y"}, str(tmp_path / "o.spks"))


def test_repack_version_bump_and_suffix(tmp_path):
    pkg = _pkg(name="spike", version=(1, 0, 0),
               files=[sp.file_from_bytes("a", b"x" * 10)])
    src = io.BytesIO()
    sp.write_spks(src, [pkg])
    buf = src.getvalue()
    out_path = str(tmp_path / "o.spks")
    sp.repack_spks(_reader_over(buf), len(buf), {}, out_path,
                   version_bump={"spike": (1, 0, 99)}, name_suffix="-MOD")
    with open(out_path, "rb") as f:
        pkgs = sp.parse_packages(_reader_over(f.read()), os.path.getsize(out_path))
    p = pkgs[0]
    assert p.version == (1, 0, 99)
    assert p.name == "spike-MOD"
