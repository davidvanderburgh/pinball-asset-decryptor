"""Unit tests for the BOF v3 PCK directory reader/rewriter.

Covers both flavours without needing a real 2.7 GB game binary:
  * plaintext directory (Winchester-style) — no key,
  * AES-encrypted directory (Dune-style) — built atop a tiny crafted ELF so
    the generic key discovery (TOKEN via code fingerprint + script-key brute
    over .data) runs for real.
"""

import hashlib
import struct

import pytest

pytest.importorskip("Crypto")  # pycryptodome — runtime dep for encrypted dirs

from pinball_decryptor.plugins.bof import pck_directory as pd


def _dir_body(files, base):
    """Serialize a v3 directory body for ``files`` laid out contiguously
    from ofs 0, and return (body_bytes, file_data_bytes, entries)."""
    body = bytearray()
    blob = bytearray()
    ofs = 0
    for path, data in files:
        praw = path + b"\x00" * (((len(path) + 3) // 4 * 4) - len(path))
        md5 = hashlib.md5(data).digest()
        body += struct.pack("<I", len(praw)) + praw
        body += struct.pack("<QQ", ofs, len(data)) + md5 + struct.pack("<I", 0)
        blob += data
        ofs += len(data)
    return bytes(body), bytes(blob), ofs


def _build_plaintext_pck(prefix, files, base=104):
    body, filedata, total = _dir_body(files, base)
    hdr = bytearray(104)
    hdr[0:4] = b"GDPC"
    struct.pack_into("<I", hdr, 4, 3)              # pack_format_version
    struct.pack_into("<III", hdr, 8, 4, 5, 2)
    struct.pack_into("<I", hdr, 20, 2)             # flags: REL_FILEBASE only
    struct.pack_into("<Q", hdr, 24, base)          # file_base
    dir_off = base + total
    struct.pack_into("<Q", hdr, 32, dir_off)       # v3 dir_offset
    dir_blob = struct.pack("<I", len(files)) + body
    pck = bytes(hdr) + filedata + dir_blob
    pck_size = len(pck)
    return prefix + pck + struct.pack("<Q", pck_size) + b"GDPC"


def _build_crafted_elf(sek, token):
    """Tiny ELF whose section table exposes one writable PROGBITS section
    holding ``sek``, plus the key-derivation code fingerprint with a
    ``lea r15,[rip+disp]`` pointing at ``token``.  Enough for
    ``_writable_progbits`` + ``_find_token`` to work."""
    buf = bytearray()
    buf += b"\x7fELF" + b"\x02\x01\x01\x00" + b"\x00" * 8   # e_ident (64-bit LE)
    buf += b"\x00" * (64 - len(buf))                        # rest of ehdr (patched below)
    # --- code: lea r15,[rip+disp]; <fingerprint> ---
    lea_off = len(buf)
    buf += b"\x4c\x8d\x3d" + b"\x00\x00\x00\x00"            # disp patched after token placed
    buf += pd._KEY_XFORM_FP
    # --- token + sek constants ---
    token_off = len(buf)
    buf += token
    sek_off = len(buf)
    buf += sek
    # patch the lea disp so rip+disp == token_off (rip = lea_off + 7)
    disp = token_off - (lea_off + 7)
    struct.pack_into("<i", buf, lea_off + 3, disp)
    # --- section header table: [null][writable PROGBITS covering sek] ---
    e_shoff = len(buf)
    sh_null = b"\x00" * 64
    sh_data = bytearray(64)
    struct.pack_into("<I", sh_data, 4, 1)          # sh_type = PROGBITS
    struct.pack_into("<Q", sh_data, 8, 0x1)        # sh_flags = SHF_WRITE
    struct.pack_into("<Q", sh_data, 24, sek_off)   # sh_offset
    struct.pack_into("<Q", sh_data, 32, 32)        # sh_size (just the key)
    buf += sh_null + bytes(sh_data)
    # patch ehdr: e_shoff(0x28), e_shentsize(0x3a)=64, e_shnum(0x3c)=2
    struct.pack_into("<Q", buf, 0x28, e_shoff)
    struct.pack_into("<H", buf, 0x3a, 64)
    struct.pack_into("<H", buf, 0x3c, 2)
    return bytes(buf)


def _build_encrypted_pck(files, sek, token, base=104):
    from Crypto.Cipher import AES
    prefix = _build_crafted_elf(sek, token)
    body, filedata, total = _dir_body(files, base)
    key = pd._derive_key(sek, token)
    iv = bytes(range(16))
    pad = (16 - len(body) % 16) % 16
    ct = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).encrypt(body + b"\x00" * pad)
    dir_blob = (struct.pack("<I", len(files)) + hashlib.md5(body).digest()
                + struct.pack("<Q", len(body)) + iv + ct)
    hdr = bytearray(104)
    hdr[0:4] = b"GBOF"
    struct.pack_into("<I", hdr, 4, 3)
    struct.pack_into("<III", hdr, 8, 4, 5, 2)
    struct.pack_into("<I", hdr, 20, 3)             # flags: DIR_ENCRYPTED | REL_FILEBASE
    struct.pack_into("<Q", hdr, 24, base)
    dir_off = base + total
    struct.pack_into("<Q", hdr, 32, dir_off)
    pck = bytes(hdr) + filedata + dir_blob
    return prefix + pck + struct.pack("<Q", len(pck)) + b"GBOF"


# --- the Dune-recovered derivation must not regress ---------------------

def test_derive_key_matches_engine():
    sek = bytes.fromhex("be3752c7a29b07a013942b9066fb6e33"
                        "cc852c2aba3d90db4f1c00fec89c978a")
    token = bytes.fromhex("ab3fc070bd131de111707fd306d88cd5"
                          "ce5dd0124f8affd47ff03544adc63ab1")
    key = pd._derive_key(sek, token)
    assert key.hex() == ("fbfb77ff3abdf23a73d9ff3f6ffff6b3"
                         "ee7ed2e6bfd3f9bdf5d353effffffffc")


def _roundtrip(tmp_path, binary_bytes, grow_idx=1, grow_by=777):
    src = tmp_path / "game.x86_64"
    src.write_bytes(binary_bytes)
    d = pd.read(str(src))
    assert d is not None
    # grow one entry; verify EVERY entry resolves in the rebuilt binary
    target = d.entries[grow_idx]
    raw = binary_bytes
    orig = raw[d.pck_off + d.base + target["ofs"]:
               d.pck_off + d.base + target["ofs"] + target["size"]]
    new = orig + b"\x5a" * grow_by
    out = tmp_path / "out.x86_64"
    pd.rewrite(d, {target["ofs"]: new}, str(out))
    d2 = pd.read(str(out))
    nd = out.read_bytes()
    assert d2.file_count == d.file_count
    for e in d2.entries:
        fd = nd[d2.pck_off + d2.base + e["ofs"]:
                d2.pck_off + d2.base + e["ofs"] + e["size"]]
        assert hashlib.md5(fd).digest() == e["md5"], e["praw"]
    # the grown entry holds exactly the new bytes
    te = d2.entries[grow_idx]
    fd = nd[d2.pck_off + d2.base + te["ofs"]:
            d2.pck_off + d2.base + te["ofs"] + te["size"]]
    assert fd == new


def test_plaintext_directory_roundtrip(tmp_path):
    files = [(b".godot/exported/aaa.scn", b"RSRC" + b"\x01" * 500),
             (b".godot/imported/snd.wav-abc.sample", b"RSRC" + b"\x02" * 1200),
             (b".godot/imported/tex.png-def.ctex", b"GST2" + b"\x03" * 800)]
    binary = _build_plaintext_pck(b"\xCC" * 256, files)
    _roundtrip(tmp_path, binary)


def test_encrypted_directory_roundtrip(tmp_path):
    sek = bytes(range(7, 7 + 32))          # arbitrary high-diversity 32 bytes
    token = bytes(range(100, 100 + 32))
    files = [(b".godot/exported/m.scn", b"RSRC" + b"\xAA" * 640),
             (b".godot/imported/voice.wav-h.sample", b"RSRC" + b"\xBB" * 1500),
             (b".godot/imported/img.png-h.ctex", b"GST2" + b"\xCC" * 900)]
    binary = _build_encrypted_pck(files, sek, token)
    # read() must transparently discover the key + decrypt
    d = pd.read(str(_w(tmp_path, "g.x86_64", binary)))
    assert d.encrypted and d.key == pd._derive_key(sek, token)
    _roundtrip(tmp_path, binary)


def _w(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p
