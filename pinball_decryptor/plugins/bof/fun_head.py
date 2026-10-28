"""The first tar member of a GPG-era Barrels of Fun ``.fun``, read in Python
from the file's first few kilobytes (PAD-787, My machines).

A ``.fun`` (Labyrinth, Dune, Winchester) is a gzipped tar, symmetrically
encrypted with gpg: one SKESK packet (AES-256, iterated and salted S2K) and
one SEIPD packet.  BoF stamps the build into the tar's FIRST member: Dune and
Winchester name their game binary for it (``GDHarvest_not_harvest_20260429
.x86_64``; Dune 1.0's ``GDHarvest_202600513`` has a stray digit), Labyrinth's
``update/`` folder carries it as its date.  So "which build is this file?" is
the first 512 bytes of the tar: a few kilobytes of the gpg stream, decrypted
here without gpg (which only runs under WSL on Windows) and without reading
the gigabytes behind them.

Only the parts of OpenPGP (RFC 4880) such a file uses: SKESK v4 with S2K
type 3, SEIPD v1 (CFB, zero IV, MDC not checked: the stream is cut long
before its end), an optional compressed packet (ZIP/ZLIB) and a literal
packet, with partial body lengths at both layers.
"""

import datetime
import hashlib
import re
import tarfile
import zlib

#: Ciphertext read from the head of the file: the tar header sits in the
#: first kilobytes of plaintext even behind gpg's compression.
HEAD_BYTES = 256 * 1024

_HASHES = {1: hashlib.md5, 2: hashlib.sha1, 8: hashlib.sha256,
           9: hashlib.sha384, 10: hashlib.sha512, 11: hashlib.sha224}
_KEY_LEN = {7: 16, 8: 24, 9: 32}           # AES-128/192/256


class FunHeadError(ValueError):
    pass


def _packet(buf, pos):
    """``(tag, body, end)`` for the packet at *pos*, its partial-length
    chunks joined; the body is cut short where *buf* ends."""
    if pos >= len(buf):
        raise FunHeadError("no packet")
    h = buf[pos]
    if not h & 0x80:
        raise FunHeadError("not an OpenPGP packet")
    pos += 1
    if not h & 0x40:                                   # old format
        tag, lt = (h >> 2) & 0x0F, h & 3
        if lt == 3:
            return tag, buf[pos:], len(buf)
        n = (1, 2, 4)[lt]
        length = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
        return tag, buf[pos:pos + length], pos + length
    tag = h & 0x3F
    body = bytearray()
    while pos < len(buf):
        o = buf[pos]
        if o < 192:
            length, pos, partial = o, pos + 1, False
        elif o < 224:
            length = ((o - 192) << 8) + buf[pos + 1] + 192
            pos, partial = pos + 2, False
        elif o == 255:
            length = int.from_bytes(buf[pos + 1:pos + 5], "big")
            pos, partial = pos + 5, False
        else:
            length, pos, partial = 1 << (o & 0x1F), pos + 1, True
        body += buf[pos:pos + length]
        pos += length
        if not partial:
            break
    return tag, bytes(body), pos


def _s2k_key(spec, passphrase, key_len):
    """The session key from a type-3 (iterated and salted) S2K."""
    if spec[0] != 3:
        raise FunHeadError("S2K type %d" % spec[0])
    hash_fn = _HASHES.get(spec[1])
    if hash_fn is None:
        raise FunHeadError("S2K hash %d" % spec[1])
    salt, c = spec[2:10], spec[10]
    count = (16 + (c & 15)) << ((c >> 4) + 6)
    data = salt + passphrase
    count = max(count, len(data))
    out = b""
    preload = 0
    while len(out) < key_len:
        h = hash_fn(b"\0" * preload)
        whole, rest = divmod(count, len(data))
        h.update(data * whole + data[:rest])
        out += h.digest()
        preload += 1
    return out[:key_len]


def _cfb_decrypt(key, data):
    try:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CFB, iv=b"\0" * 16,
                       segment_size=128).decrypt(data)
    except ImportError:
        from .aes_py import cfb128
        return cfb128(key, b"\0" * 16, data)


def _plaintext(head, passphrase):
    """The literal data at the start of the encrypted stream (a gzip
    stream, for a .fun)."""
    tag, skesk, pos = _packet(head, 0)
    if tag != 3 or len(skesk) < 4 or skesk[0] != 4:
        raise FunHeadError("no passphrase packet (SKESK v4)")
    key_len = _KEY_LEN.get(skesk[1])
    if key_len is None:
        raise FunHeadError("cipher %d" % skesk[1])
    if len(skesk) > 13:
        raise FunHeadError("an encrypted session key")
    key = _s2k_key(skesk[2:], passphrase.encode(), key_len)
    tag, body, _end = _packet(head, pos)
    if tag != 18 or not body or body[0] != 1:
        raise FunHeadError("no encrypted data packet (SEIPD v1)")
    clear = _cfb_decrypt(key, body[1:])
    if clear[14:16] != clear[16:18]:
        raise FunHeadError("wrong passphrase")
    inner = clear[18:]
    tag, body, _end = _packet(inner, 0)
    if tag == 8:                                       # compressed
        algo, comp = body[0], body[1:]
        if algo == 1:
            d = zlib.decompressobj(-15)
        elif algo == 2:
            d = zlib.decompressobj()
        elif algo == 0:
            d = None
        else:
            raise FunHeadError("compression %d" % algo)
        inner = comp if d is None else d.decompress(comp)
        tag, body, _end = _packet(inner, 0)
    if tag != 11 or len(body) < 6:
        raise FunHeadError("no literal data packet")
    n = body[1]
    return body[2 + n + 4:]


def first_member(path, passphrase, head_bytes=HEAD_BYTES):
    """``(name, mtime)`` of the first member of the tar inside the .fun at
    *path*.  Raises :class:`FunHeadError` (or OSError) when it can't."""
    with open(path, "rb") as f:
        head = f.read(head_bytes)
    gz = _plaintext(head, passphrase)
    tar_head = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(gz, 4096)
    if len(tar_head) < 512:
        raise FunHeadError("no tar header")
    try:
        info = tarfile.TarInfo.frombuf(tar_head[:512], "utf-8", "replace")
    except tarfile.TarError as e:
        raise FunHeadError("no tar header: %s" % e)
    if info.type in (tarfile.GNUTYPE_LONGNAME, b"x", b"g"):
        raise FunHeadError("a long first name")
    return info.name, info.mtime


_DATE_RUN = re.compile(r"(20\d\d)(\d{4,5})(?!\d)")


def build_date(name, mtime):
    """The build a first member names: the date in its name
    (``..._20260429.x86_64``; ``202600513`` reads 2026-05-13), else its
    file date (Labyrinth's ``update/``)."""
    for m in _DATE_RUN.finditer(name or ""):
        md = m.group(2)[-4:]
        try:
            return datetime.date(int(m.group(1)), int(md[:2]), int(md[2:]))
        except ValueError:
            continue
    if mtime:
        return datetime.datetime.fromtimestamp(
            int(mtime), datetime.timezone.utc).date()
    return None
