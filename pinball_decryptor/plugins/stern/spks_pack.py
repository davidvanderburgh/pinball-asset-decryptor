"""Stern **SPKS** archive *writer* — the inverse of :mod:`.spks`.

:mod:`.spks` reads the SPKS archive nested inside a decrypted Spike 3 ``.spk``.
This module writes one back, so a user can swap modded assets into a title's
package and hand out a small file instead of a whole modded SD image.

The byte layout is ported from JayFoxRox's ``pack-spk.py`` (ske-spk-tools),
which is verified against real Stern packages, and round-trips with our own
:class:`.spks.SpksArchive` reader::

    SPKS hdr ; u32 package_count
      ( SPK0 hdr ; SIDX hdr ; <name29 short3 ver3 type1 ...> ; u32 file_count ;
        sdat_size ; STRS hdr ; <NUL-separated paths> ;
        ( FINF|FI64 hdr ; <record> ) * file_count ; FEND hdr ;
        SDAT hdr ; <file data back-to-back> ) * package_count
    SEND|SE64 hdr ; u64/u32 spks_offset

Small packages use 32-bit ``FINF`` records; a package whose data region is
>4 GiB switches to 64-bit ``FI64`` (and ``SZ64``/``SE64`` headers), exactly as
``pack-spk`` chooses.

**Signing.** Each file carries an HMAC-SHA1 keyed with the 16-byte factory key
and a plain MD5. The factory key is *symmetric* and every machine already holds
it, so the signature is not a real barrier (see PAD-1125 notes); signing is
**optional**. With no key, the HMAC field is 20 bytes of ``0xAA`` placeholder,
exactly as ``pack-spk`` does. No key material lives in this repo — the caller
passes a user-supplied key or none.

**Not-official mark (mandatory).** :func:`repack_spks` refuses to write without
marking the output so it cannot be mistaken for an official Stern package
(JayFoxRox's ske-spk-tools#pack-spk warning): a visible marker file is injected
and the caller is expected to bump the version / suffix the name.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Union

# Package type tags (SIDX "type" byte), from pack-spk.
PACKAGE_TYPES = {"SPIKE_1": 1, "GAME": 2, "SPIKE_2": 3, "SPIKE_3": 4}
PACKAGE_TYPE_NAMES = {v: k for k, v in PACKAGE_TYPES.items()}

_MAX32 = 0xFFFFFFFE
_PLACEHOLDER_HMAC = b"\xAA" * 20
_CHUNK = 1 << 20

MARK_FILENAME = "NOT_AN_OFFICIAL_STERN_PACKAGE.txt"
MARK_TEXT = (
    b"This package was repacked by PAD (Pinball Asset Decryptor).\n"
    b"It is NOT an official Stern package and must not be distributed as one.\n"
)


class SpksPackError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass
class SpksInputFile:
    """One file to pack.

    *open_chunks* is a zero-arg callable returning an iterator of ``bytes`` that
    together are exactly *size* long. It may be called more than once (once to
    hash, once to write), so it must re-open its source each time.
    """
    path: str
    mode: int
    size: int
    open_chunks: Callable[[], Iterator[bytes]]
    _md5: bytes = field(default=b"", repr=False)
    _hmac: bytes = field(default=b"", repr=False)


@dataclass
class SpksPackage:
    type: int
    name: str
    shortname: str
    version: tuple
    files: List[SpksInputFile]


def file_from_path(path_in_pkg: str, local_path: str,
                   mode: Optional[int] = None) -> SpksInputFile:
    st = os.stat(local_path)

    def _open():
        with open(local_path, "rb") as f:
            while True:
                b = f.read(_CHUNK)
                if not b:
                    break
                yield b

    return SpksInputFile(path=path_in_pkg,
                         mode=st.st_mode if mode is None else mode,
                         size=st.st_size, open_chunks=_open)


def file_from_bytes(path_in_pkg: str, data: bytes,
                    mode: int = 0o100644) -> SpksInputFile:
    data = bytes(data)

    def _open():
        yield data

    return SpksInputFile(path=path_in_pkg, mode=mode, size=len(data),
                         open_chunks=_open)


def file_from_reader(path_in_pkg: str, read: Callable[[int, int], bytes],
                     offset: int, size: int, mode: int) -> SpksInputFile:
    """A file whose bytes come from an existing archive's ``read(off, n)``."""
    def _open():
        left = size
        off = offset
        while left > 0:
            n = min(_CHUNK, left)
            b = read(off, n)
            if not b:
                break
            yield b
            off += len(b)
            left -= len(b)

    return SpksInputFile(path=path_in_pkg, mode=mode, size=size,
                         open_chunks=_open)


# --------------------------------------------------------------------------- #
# Factory (HMAC) key loading — user-supplied, never from the repo
# --------------------------------------------------------------------------- #
def load_factory_hmac_key(value: Union[bytes, str, None]) -> Optional[bytes]:
    """Resolve a factory signing key to its 16 HMAC bytes, or ``None``.

    Accepts: ``None`` (unsigned); 16 raw bytes; 32 hex chars; or a path to a
    factory-key file (the HMAC key is bytes ``0xB0:0xC0`` of it, per pack-spk;
    a bare 16-byte file is used as-is).
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
    elif isinstance(value, str) and os.path.exists(value):
        with open(value, "rb") as f:
            b = f.read()
        if len(b) >= 0xC0:
            b = b[0xB0:0xC0]
    else:
        s = str(value).strip().replace(" ", "")
        try:
            b = bytes.fromhex(s)
        except ValueError:
            raise SpksPackError(
                "factory key is neither 32 hex chars nor a file path: %r"
                % (value,))
    if len(b) != 16:
        raise SpksPackError("factory HMAC key must be 16 bytes, got %d" % len(b))
    return b


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #
class _SpksWriter:
    def __init__(self, out, hmac_key: Optional[bytes] = None):
        self._out = out
        self._hmac_key = hmac_key
        self._alloc: List[int] = []     # size-only "allocation" pass stack

    # -- primitives (alloc pass adds sizes; real pass writes) ----------------
    def _w(self, data: bytes) -> int:
        if self._alloc:
            self._alloc[-1] += len(data)
            return len(data)
        self._out.write(data)
        return len(data)

    def _alloc_run(self, fn, *a) -> int:
        self._alloc.append(0)
        fn(*a)
        return self._alloc.pop()

    def _chunk_header(self, magic: bytes, offset: int, needs64: bool = False):
        self._w(magic)
        if not needs64 and offset <= _MAX32:
            self._w(struct.pack("<I", offset))
        else:
            self._w(struct.pack("<I", 0xFFFFFFFF))
            self._w(struct.pack("<Q", offset))

    @staticmethod
    def _align(v: int, a: int) -> int:
        return (a - (v % a)) % a

    # -- records -------------------------------------------------------------
    def _finf(self, f: SpksInputFile, strs: int, sdat: int, needs64: bool):
        length = f.size
        mode = f.mode & 0xFFFF
        if needs64:
            self._chunk_header(b"FI64", 0x50)
            self._w(struct.pack("<Q", strs))
            self._w(struct.pack("<Q", length))
            self._w(struct.pack("<Q", sdat))
            self._w(struct.pack("<Q", length))
            self._w(struct.pack("<H", mode))
            self._w(b"\x00\x00\x00")
            self._w(f._hmac)
            self._w(f._md5)
            self._w(b"\x00\x00\x00")
            self._w(b"\x00\x00\x00\x00")
        else:
            self._chunk_header(b"FINF", 0x3C)
            self._w(struct.pack("<I", strs))
            self._w(struct.pack("<I", length))
            self._w(struct.pack("<I", sdat))
            self._w(struct.pack("<I", length))
            self._w(struct.pack("<H", mode))
            self._w(b"\x00\x00\x00")
            self._w(f._hmac)
            self._w(f._md5)
            self._w(b"\x00\x00\x00")

    def _sidx(self, ptype: int, name: bytes, shortname: bytes, version,
              files: List[SpksInputFile]):
        sdat_size = sum(f.size for f in files)
        needs64 = sdat_size > _MAX32

        def do_sidx():
            if len(name) > 29:
                raise SpksPackError("package name too long (>29): %r" % name)
            self._w(name + b"\x00" * (29 - len(name)))
            if len(shortname) > 3:
                raise SpksPackError("shortname too long (>3): %r" % shortname)
            self._w(shortname + b"\x00" * (3 - len(shortname)))
            self._w(struct.pack("<B", version[0]))
            self._w(struct.pack("<B", version[1]))
            self._w(struct.pack("<B", version[2]))
            self._w(struct.pack("<B", ptype))
            self._w(b"\x00\x00\x00\x00")
            self._w(struct.pack("<I", len(files)))
            if needs64:
                self._w(struct.pack("<I", 0xFFFFFFFF))
                self._chunk_header(b"SZ64", 8)
                self._w(struct.pack("<Q", sdat_size))
            else:
                self._w(struct.pack("<I", sdat_size))

            def do_strs():
                for f in files:
                    self._w(f.path.encode("ascii") + b"\x00")

            x = self._alloc_run(do_strs)
            pad = self._align(x, 4)
            self._chunk_header(b"STRS", x + pad)
            do_strs()
            self._w(b"\x00" * pad)

            strs = 0
            sdat = 0
            for f in files:
                self._finf(f, strs, sdat, needs64)
                strs += len(f.path.encode("ascii")) + 1
                sdat += f.size
            self._chunk_header(b"FEND", 0)

        x = self._alloc_run(do_sidx)
        self._chunk_header(b"SIDX", x, needs64)
        do_sidx()

        self._chunk_header(b"SDAT", sdat_size if needs64 else 0)
        for f in files:
            if self._alloc:
                self._alloc[-1] += f.size
            else:
                self._write_data(f)

    def _write_data(self, f: SpksInputFile):
        written = 0
        for chunk in f.open_chunks():
            self._out.write(chunk)
            written += len(chunk)
        if written != f.size:
            raise SpksPackError(
                "file %r: wrote %d bytes, declared %d" % (f.path, written, f.size))

    def _spk0(self, pkg: SpksPackage, needs64: bool):
        def do():
            self._sidx(pkg.type, pkg.name.encode("ascii"),
                       pkg.shortname.encode("ascii"), pkg.version, pkg.files)
        x = self._alloc_run(do)
        self._chunk_header(b"SPK0", x, needs64)
        do()

    # -- public --------------------------------------------------------------
    def prepare(self, packages: List[SpksPackage]):
        """Hash every file (MD5 + optional HMAC) before the index is written."""
        for pkg in packages:
            for f in pkg.files:
                md5 = hashlib.md5()
                h = (hmac.new(self._hmac_key, digestmod=hashlib.sha1)
                     if self._hmac_key else None)
                n = 0
                for chunk in f.open_chunks():
                    md5.update(chunk)
                    if h is not None:
                        h.update(chunk)
                    n += len(chunk)
                if n != f.size:
                    raise SpksPackError(
                        "file %r: hashed %d bytes, declared %d"
                        % (f.path, n, f.size))
                f._md5 = md5.digest()
                f._hmac = h.digest() if h is not None else _PLACEHOLDER_HMAC

    def write(self, packages: List[SpksPackage]):
        def do(needs64):
            for pkg in packages:
                self._spk0(pkg, needs64)

        spks_off = self._out.tell()
        x = self._alloc_run(do, False)
        needs64 = x > _MAX32
        x = self._alloc_run(do, needs64)
        self._chunk_header(b"SPKS", x)
        self._w(struct.pack("<I", len(packages)))
        do(needs64)
        if needs64:
            self._chunk_header(b"SE64", 8)
            self._w(struct.pack("<Q", spks_off))
        else:
            self._chunk_header(b"SEND", 4)
            self._w(struct.pack("<I", spks_off))


def write_spks(out_stream, packages: List[SpksPackage],
               hmac_key: Union[bytes, str, None] = None):
    """Write *packages* to *out_stream* (a binary file object)."""
    key = load_factory_hmac_key(hmac_key)
    w = _SpksWriter(out_stream, hmac_key=key)
    w.prepare(packages)
    w.write(packages)


def build_spks_file(out_path: str, packages: List[SpksPackage],
                    hmac_key: Union[bytes, str, None] = None):
    with open(out_path, "wb") as out:
        write_spks(out, packages, hmac_key=hmac_key)
    return out_path


# --------------------------------------------------------------------------- #
# Parsing an existing SPKS into package descriptors (for repack)
# --------------------------------------------------------------------------- #
@dataclass
class ParsedFile:
    path: str
    mode: int
    offset: int
    size: int


@dataclass
class ParsedPackage:
    type: int
    name: str
    shortname: str
    version: tuple
    files: List[ParsedFile]


def parse_packages(read: Callable[[int, int], bytes], size: int
                   ) -> List[ParsedPackage]:
    """Walk an SPKS archive and return its packages with full SIDX metadata.

    Mirrors :class:`.spks.SpksArchive`'s structural walk but also recovers the
    per-package name / shortname / version / type needed to rebuild it.
    """
    from . import spks as _spks  # reuse the verified record/section walk

    arc = _spks.SpksArchive(read, size)

    def u32(off):
        return struct.unpack("<I", read(off, 4))[0]

    def find(tag, start, limit=1 << 20):
        window = read(start, min(limit, max(0, size - start)))
        rel = window.find(tag)
        return start + rel if rel >= 0 else -1

    # Locate each SPK0, then read its SIDX metadata block.
    packages: List[ParsedPackage] = []
    pos = find(b"SPK0", 4, 64)
    seen = set()
    guard = 0
    meta_by_section: Dict[str, ParsedPackage] = {}
    while 0 <= pos < size and read(pos, 4) == b"SPK0" and guard < 1024:
        guard += 1
        sidx = find(b"SIDX", pos, 64)
        if sidx < 0:
            break
        off0 = u32(sidx + 4)
        body = sidx + (12 if off0 == 0xFFFFFFFF else 8)
        blob = read(body, 44)
        name = blob[0:29].split(b"\x00", 1)[0].decode("latin1", "replace")
        shortname = blob[29:32].split(b"\x00", 1)[0].decode("latin1", "replace")
        version = (blob[32], blob[33], blob[34])
        ptype = blob[35]
        meta_by_section[name] = ParsedPackage(
            type=ptype, name=name, shortname=shortname, version=version,
            files=[])
        # advance to the next SPK0 the way the reader's walk does
        strs_pos = find(b"STRS", pos, 1 << 20)
        if strs_pos < 0:
            break
        strs_sz = u32(strs_pos + 4)
        # jump past this section by reusing where the reader put its files
        nxt = find(b"SPK0", strs_pos + 8 + strs_sz, size - (strs_pos + 8 + strs_sz))
        if nxt < 0 or nxt in seen:
            break
        seen.add(nxt)
        pos = nxt

    # Attach files (section, path, offset, size, mode) from the verified reader.
    order: List[str] = []
    for fobj in arc.files:
        pkg = meta_by_section.get(fobj.section)
        if pkg is None:
            pkg = meta_by_section.setdefault(
                fobj.section,
                ParsedPackage(type=PACKAGE_TYPES["GAME"], name=fobj.section,
                              shortname="", version=(0, 0, 0), files=[]))
        if fobj.section not in order:
            order.append(fobj.section)
        pkg.files.append(ParsedFile(path=fobj.path, mode=fobj.mode,
                                    offset=fobj.offset, size=fobj.size))
    return [meta_by_section[s] for s in order]


# --------------------------------------------------------------------------- #
# Repack: swap modded files into an existing SPKS, mark, and write a new one
# --------------------------------------------------------------------------- #
def repack_spks(read: Callable[[int, int], bytes], size: int,
                replacements: Dict[str, Union[str, bytes]],
                out_path: str, *,
                hmac_key: Union[bytes, str, None] = None,
                mark: bool = True,
                version_bump: Optional[Dict[str, tuple]] = None,
                name_suffix: Optional[str] = None) -> str:
    """Rebuild the SPKS at ``(read, size)`` with *replacements* swapped in.

    *replacements* maps an archive file path (``"section/path"`` or bare
    ``path``) to a local file path or raw ``bytes``. Unchanged files stream
    straight from the source. The not-official mark is injected unless *mark*
    is False (strongly discouraged). *version_bump* maps a package name to a new
    ``(major, minor, patch)``; *name_suffix* is appended to each package name
    (kept within the 29-byte field).
    """
    if not mark:
        raise SpksPackError(
            "refusing to write an unmarked package; a PAD build must be "
            "distinguishable from an official Stern package (pass mark=True)")

    parsed = parse_packages(read, size)
    if not parsed:
        raise SpksPackError("no packages found in source SPKS")

    # index replacements by both "section/path" and bare "path"
    want = dict(replacements)
    used = set()

    def pick(section, path):
        for key in ("%s/%s" % (section, path), path):
            if key in want:
                used.add(key)
                return want[key]
        return None

    out_packages: List[SpksPackage] = []
    for i, pkg in enumerate(parsed):
        files: List[SpksInputFile] = []
        for pf in pkg.files:
            repl = pick(pkg.name, pf.path)
            if repl is None:
                files.append(file_from_reader(pf.path, read, pf.offset,
                                              pf.size, pf.mode))
            elif isinstance(repl, (bytes, bytearray)):
                files.append(file_from_bytes(pf.path, bytes(repl), pf.mode))
            else:
                files.append(file_from_path(pf.path, repl, pf.mode))

        # inject the not-official marker into the first package
        if mark and i == 0 and not any(f.path == MARK_FILENAME for f in files):
            files.insert(0, file_from_bytes(MARK_FILENAME, MARK_TEXT))

        name = pkg.name
        if name_suffix:
            name = (name + name_suffix)[:29]
        version = pkg.version
        if version_bump and pkg.name in version_bump:
            version = version_bump[pkg.name]

        out_packages.append(SpksPackage(
            type=pkg.type, name=name, shortname=pkg.shortname,
            version=version, files=files))

    missing = set(want) - used
    if missing:
        raise SpksPackError(
            "replacement path(s) not found in the source package: %s"
            % ", ".join(sorted(missing)))

    build_spks_file(out_path, out_packages, hmac_key=hmac_key)
    return out_path
