"""Read and rebuild a Spike 2 card's master directory -- the encrypted record
array in the tail of ``image.bin`` that says where every sound lives and how
long it is.

The firmware decodes it as:

    memcpy(buf, image + hdr[0x40], align16(24 * hdr[0x60]))
    seed = *(u32 *)(image + hdr[0x40] + align16(24n))
    key, iv = <derived from the seed alone>
    aes_cbc_decrypt(buf)            # AES-192 on every build seen
    <per-record post-transform>     # scatters two dwords into bytes 0..7
    crc32(buf, <per-build init>) == <a bit permutation of the seed>

so writing it back is the exact mirror.  Two things here are NOT ported: the
key schedule and the seed permutation are both taken from the firmware itself,
by re-entering the decoder and stopping at its AES-init call (:func:`keygen`).
That costs a few milliseconds a run because it stops before the cipher, so no
PRNG, permute or keystream code has to be reimplemented -- and a build whose
constants nobody has seen is handled by running it, not by guessing.

On a stock card the directory is the whole file tail::

    filesize == hdr[0x40] + align16(24 * count) + 8

The 8 bytes past the aligned ciphertext are the seed word plus one more word.
Because ``align16`` adds 8 for an ODD count and nothing for an even one, a file
with an odd count ends ``24n + 16`` past the directory offset and one with an
even count ends ``24n + 8`` -- both parities ship, and appending a record flips
whichever one a card has.  Sizing the trailer from the record bytes instead of
the aligned size produces a byte-identical ciphertext and a file 8 bytes TOO
LONG, which is why :func:`tail_len` exists and is used everywhere.  On a grown
card the appended bodies follow the directory, so the equality above becomes
"the file is at least this long".

Growing a sound means appending a record (:func:`plan_grow_records`), never
editing one in place: changing a record's length word shifts every LATER
record's decode parameters, including the identity key the game looks a sound
up by, even when its body is untouched.
"""

import collections
import struct
import zlib

from Crypto.Cipher import AES

from unicorn.arm_const import UC_ARM_REG_R1, UC_ARM_REG_R2

from . import locate as _locate

# Bytes on disk after the aligned ciphertext: the seed word and one more word.
TRAILER_AFTER = 8
# Zero bytes placed in front of an appended body.  A codec whose key reads
# sample 0 from the word BELOW ``body_off`` (delta < 0) would otherwise read
# whatever precedes it; for a stock body that is the layout predecessor's tail,
# for an appended one there is nothing, so give it a defined run of zeros.
BODY_PAD = 16
# Where the header keeps the directory offset and the record count.
HDR_MD_OFF = 0x40
HDR_COUNT = 0x60
RECORD_SIZE = 24
# Record-count ceiling, matching the emulator's: the largest shipped catalog is
# about 10.5k sounds, so this has ~6x headroom and anything above it is a
# corrupt header rather than a card.
MAX_RECORDS = 1 << 16


class MasterDirError(Exception):
    """The directory on this card could not be read or rebuilt."""


class MasterDirUnsupported(MasterDirError):
    """This firmware build's directory cipher could not be located.

    Audio decode is unaffected -- only growing the sound bank needs these
    addresses, and callers refuse the grow with this message rather than
    writing a card they cannot verify."""


def align16(n):
    return (n + 15) & ~15


def tail_len(count):
    """On-disk bytes from the directory offset to the end of the file."""
    return align16(RECORD_SIZE * count) + TRAILER_AFTER


def _u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


def _p32(v):
    return struct.pack("<I", v & 0xffffffff)


# --------------------------------------------------------------------------
# the per-record post-transform
# --------------------------------------------------------------------------
# Read off the firmware's own loop (TMNT 0x347120..0x347188; the same shape on
# every build probed).  Per record it takes three plaintext dwords and scatters
# two computed ones back into bytes 0..7, leaving 8..15 and 20..23 alone:
#
#     S   = pt[k][16:20]              X_k = X_{k-1} ^ S       (X_-1 = 0)
#     A   = ~S ^ X_k ^ pt[k][4:8]     B   = pt[k][0:4] ^ ~X_k
#     md[k][0..7]  = B0, B3, A0, A2, A3, B2, A1, B1
#     md[k][16:20] = X_k
#
# so ``md[k][0:4]`` IS the body offset the band build reads, and
# ``md[k][16:20]`` is a running XOR chain of the raw length words (the build's
# own length XOR is applied on top of it by the codec).
def post_forward(pt, count):
    """Plaintext (the CBC output) -> the record array the firmware CRCs."""
    out = bytearray(pt)
    x = 0
    for k in range(count):
        o = k * RECORD_SIZE
        s = _u32(pt, o + 16)
        p0 = _u32(pt, o + 0)
        p4 = _u32(pt, o + 4)
        x ^= s
        a = ((~s) ^ x ^ p4) & 0xffffffff
        b = (p0 ^ (~x)) & 0xffffffff
        ab = a.to_bytes(4, "little")
        bb = b.to_bytes(4, "little")
        out[o + 0] = bb[0]
        out[o + 1] = bb[3]
        out[o + 2] = ab[0]
        out[o + 3] = ab[2]
        out[o + 4] = ab[3]
        out[o + 5] = bb[2]
        out[o + 6] = ab[1]
        out[o + 7] = bb[1]
        out[o + 16:o + 20] = _p32(x)
    return bytes(out)


def post_inverse(md, count):
    """The record array -> the plaintext the CBC layer produced."""
    out = bytearray(md)
    prev = 0
    for k in range(count):
        o = k * RECORD_SIZE
        x = _u32(md, o + 16)
        s = x ^ prev
        bv = int.from_bytes(bytes((md[o + 0], md[o + 7], md[o + 5], md[o + 1])),
                            "little")
        av = int.from_bytes(bytes((md[o + 2], md[o + 6], md[o + 3], md[o + 4])),
                            "little")
        out[o + 0:o + 4] = _p32(bv ^ (~x))
        out[o + 4:o + 8] = _p32(av ^ (~s) ^ x)
        out[o + 16:o + 20] = _p32(s)
        prev = x
    return bytes(out)


def crc(init, buf):
    """The firmware's table CRC: a plain CRC-32 whose running value starts at
    the build's own constant, with no final inversion."""
    return zlib.crc32(buf, init & 0xffffffff) & 0xffffffff


# --------------------------------------------------------------------------
# seed -> expected-CRC, measured from the firmware and inverted
# --------------------------------------------------------------------------
class BitMap(object):
    """An affine GF(2) map on 32-bit words, built from 33 firmware runs.

    The firmware turns the seed word into the CRC it expects by reassembling
    its bits; measured, that map is linear (``f(0) == 0``) and every basis
    image is a single bit, i.e. a pure permutation.  Building it by probing
    means the encoder never has to reproduce the bit network, and inverting it
    is what lets a rebuilt directory choose the seed for the CRC it needs."""

    def __init__(self, const, basis):
        self.const = const & 0xffffffff
        self.basis = [b & 0xffffffff for b in basis]
        self._piv = None

    def apply(self, x):
        v = self.const
        for i in range(32):
            if (x >> i) & 1:
                v ^= self.basis[i]
        return v & 0xffffffff

    def _build_inverse(self):
        piv = {}
        for i in range(32):
            a, b = self.basis[i], 1 << i
            for bit in range(31, -1, -1):
                if not (a >> bit) & 1:
                    continue
                if bit in piv:
                    pa, pb = piv[bit]
                    a ^= pa
                    b ^= pb
                else:
                    piv[bit] = (a, b)
                    break
        if len(piv) != 32:
            raise MasterDirError(
                "this build's seed-to-CRC map is not invertible (rank %d of 32)"
                % len(piv))
        self._piv = piv

    def invert(self, y):
        """``x`` with ``apply(x) == y``, or None if no such ``x`` exists."""
        if self._piv is None:
            self._build_inverse()
        a = (y ^ self.const) & 0xffffffff
        x = 0
        for bit in range(31, -1, -1):
            if not (a >> bit) & 1:
                continue
            pa, pb = self._piv[bit]
            a ^= pa
            x ^= pb
        return x if a == 0 else None


# --------------------------------------------------------------------------
# the directory itself
# --------------------------------------------------------------------------
class Directory(object):
    """A card's master directory, decoded.

    ``records`` is ``count * 24`` bytes in RECORD-ARRAY form -- exactly the
    bytes the band build reads -- so a caller edits body offsets and length
    words there and never meets the cipher.  ``pad_plain`` is the plaintext
    past the last record (8 bytes for an odd count, none for an even one),
    ``trailer`` the 4 bytes on disk after the seed word."""

    def __init__(self, records, count, md_off, seed, pad_plain=b"",
                 trailer=b"", crc_value=None):
        if len(records) != RECORD_SIZE * count:
            raise MasterDirError("records is %d bytes, expected %d"
                                 % (len(records), RECORD_SIZE * count))
        self.records = bytes(records)
        self.count = count
        self.md_off = md_off
        self.seed = seed & 0xffffffff
        self.pad_plain = bytes(pad_plain)
        self.trailer = bytes(trailer)
        # The checksum the firmware verified, when this came off a card.
        self.crc_value = crc_value

    # -- geometry --------------------------------------------------------
    @property
    def size_aligned(self):
        return align16(RECORD_SIZE * self.count)

    @property
    def padded_plain(self):
        """``pad_plain`` sized to this record count: the plaintext between the
        last record and the seed word (8 bytes for an odd count, none for an
        even one).  A parity flip changes how many there are, so it is always
        derived from the count rather than carried over blindly."""
        pad = self.size_aligned - RECORD_SIZE * self.count
        return (self.pad_plain + b"\x00" * pad)[:pad]

    @property
    def tail_len(self):
        return tail_len(self.count)

    def file_size(self):
        """What ``image.bin`` must be for this directory to be its tail."""
        return self.md_off + self.tail_len

    # -- records ---------------------------------------------------------
    def record(self, i):
        if not 0 <= i < self.count:
            raise IndexError("record %d of %d" % (i, self.count))
        return self.records[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]

    def body_off(self, i):
        return _u32(self.record(i), 0)

    def length_word(self, i):
        """The record's raw length word.  The decoded sample count is this
        XORed with one constant per build, which the caller knows from its
        derived rows -- see :func:`plan_grow_records`."""
        return _u32(self.record(i), 16)

    def identity(self, i):
        """The bytes of a record that are NOT its geometry.

        Two records with the same identity describe the same sound in the
        sound container; an appended record keeps its source's identity so the
        game's play-time lookup still finds it."""
        r = self.record(i)
        return r[4:16] + r[20:24]

    def with_records(self, records, count):
        """A copy carrying different records.  The seed and the checksum are
        recomputed when it is written, and the plaintext pad resizes itself for
        the new count's parity."""
        return Directory(records, count, self.md_off, self.seed,
                         pad_plain=self.pad_plain, trailer=self.trailer)

    def __repr__(self):
        return ("<Directory count=%d (%s) md_off=0x%x size=%d seed=0x%08x>"
                % (self.count, "odd" if self.count % 2 else "even",
                   self.md_off, self.size_aligned, self.seed))


def set_geometry(record, body_off=None, length_word=None):
    """A record with its body offset and/or raw length word replaced."""
    b = bytearray(record)
    if body_off is not None:
        struct.pack_into("<I", b, 0, body_off & 0xffffffff)
    if length_word is not None:
        struct.pack_into("<I", b, 16, length_word & 0xffffffff)
    return bytes(b)


def header_geometry(header):
    """``(md_off, count)`` from the first 0x100 bytes of ``image.bin``."""
    return _u32(header, HDR_MD_OFF), _u32(header, HDR_COUNT)


# --------------------------------------------------------------------------
# the cipher layer, with the key supplied
# --------------------------------------------------------------------------
# Split out from read/write so it can be exercised without an emulator: given
# any key and IV these two are exact inverses, and everything build-specific
# (which key, which seed) stays in the firmware-driven half.
def pack_tail(directory, key, iv, seed):
    """The on-disk bytes for ``directory`` under ``key``/``iv``: the aligned
    ciphertext, then the seed word, then the trailer word."""
    n = directory.count
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(
        post_inverse(directory.records, n) + directory.padded_plain)
    trailer = (directory.trailer + b"\x00" * TRAILER_AFTER)[:TRAILER_AFTER - 4]
    return ct + _p32(seed) + trailer


def unpack_tail(blob, count, key, iv, md_off=0):
    """The inverse of :func:`pack_tail`: a :class:`Directory` (with no CRC
    checked -- :func:`read_directory` does that against the firmware)."""
    size = align16(RECORD_SIZE * count)
    if len(blob) < size + TRAILER_AFTER:
        raise MasterDirError("sound bank tail is %d bytes, needs %d"
                             % (len(blob), size + TRAILER_AFTER))
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(blob[:size])
    md = post_forward(pt, count)
    after = blob[size:]
    return Directory(md[:RECORD_SIZE * count], count, md_off, _u32(after, 0),
                     pad_plain=pt[RECORD_SIZE * count:], trailer=after[4:8])


# --------------------------------------------------------------------------
# appending records
# --------------------------------------------------------------------------
GrowEdit = collections.namedtuple(
    "GrowEdit", "idx old_length new_length body_bytes")
Placement = collections.namedtuple(
    "Placement", "idx new_idx body_off length body_bytes")


def plan_grow_records(directory, edits, body_pad=BODY_PAD):
    """Append one record per edit, each pointing at a body past the old tail.

    ``edits`` are :class:`GrowEdit` tuples: the record to grow, its current
    decoded length, the length it should have, and how many bytes its new body
    occupies.  Returns ``(directory', placements)``; the appended records are
    copies of their sources with only the body offset and the length word
    replaced, so every stock record stays byte-identical and runs first in the
    firmware's chain.

    Editing a record in place is deliberately not offered.  Changing one
    record's length word shifts every later record's decode parameters --
    including its sound-container identity key -- with its body untouched, so
    there is no arrangement of restored bytes that makes it safe."""
    edits = [GrowEdit(*e) for e in edits]
    if not edits:
        raise MasterDirError("plan_grow_records called with no edits")
    seen = set()
    for e in edits:
        if not 0 <= e.idx < directory.count:
            raise MasterDirError("record %d is not in this directory (%d records)"
                                 % (e.idx, directory.count))
        if e.idx in seen:
            raise MasterDirError("record %d appears twice in the grow plan" % e.idx)
        seen.add(e.idx)
        if e.new_length <= e.old_length:
            raise MasterDirError(
                "record %d: new length %d is not longer than %d -- a sound that "
                "fits its slot is written in place, not grown"
                % (e.idx, e.new_length, e.old_length))
        if e.body_bytes <= 0:
            raise MasterDirError("record %d: body_bytes must be positive" % e.idx)

    # The length word and the decoded length differ by one constant per build.
    # Every edit must agree on it, which catches a caller passing the wrong
    # "old" length far more cheaply than a failed Write does.
    xors = {(directory.length_word(e.idx) ^ (e.old_length & 0xffffffff))
            for e in edits}
    if len(xors) > 1:
        raise MasterDirError(
            "the grow plan's records disagree about this build's length "
            "constant (%s) -- one of the supplied lengths is not the length "
            "that record actually decodes to"
            % ", ".join("0x%08x" % v for v in sorted(xors)))

    new_count = directory.count + len(edits)
    off = directory.md_off + tail_len(new_count) + body_pad
    appended = []
    places = []
    for n, e in enumerate(edits):
        word = directory.length_word(e.idx) ^ (e.old_length & 0xffffffff) \
            ^ (e.new_length & 0xffffffff)
        appended.append(set_geometry(directory.record(e.idx), body_off=off,
                                     length_word=word))
        places.append(Placement(e.idx, directory.count + n, off, e.new_length,
                                e.body_bytes))
        off += e.body_bytes + body_pad
    grown = directory.with_records(
        directory.records + b"".join(appended), new_count)
    return grown, places


# --------------------------------------------------------------------------
# firmware-assisted crypto
# --------------------------------------------------------------------------
class _Session(object):
    """Per-emulator state: the located cipher sites, the seed->CRC map and the
    AES key length, all built once and reused."""

    def __init__(self, emu):
        self.emu = emu
        self.sites = _crypto_sites(emu)
        self._map = None
        self.keylen = None

    @property
    def crc_init(self):
        return self.sites["CRC_INIT"]

    def seed_map(self):
        if self._map is None:
            self._map = _build_seed_map(self)
        return self._map


def _session(emu):
    s = getattr(emu, "_masterdir_session", None)
    if s is None:
        s = _Session(emu)
        emu._masterdir_session = s
    return s


def _crypto_sites(emu):
    sites = getattr(emu, "MASTERDIR_CRYPTO", None)
    if sites is None:
        sites = _locate.masterdir_crypto(
            game_real_path=emu._gr_path, md_start=emu.MASTERDIR_DECODE)
    if not sites:
        raise MasterDirUnsupported(
            "this game version's sound-bank directory cipher could not be "
            "located in its firmware, so the bank cannot be rewritten")
    return sites


def _guest_seed_addr(emu):
    """Where the seed word sits in the guest's view of ``image.bin``."""
    from .emulator import DESC_BASE
    md_off, count = header_geometry(bytes(emu.mm[0:0x100]))
    return DESC_BASE + md_off + align16(RECORD_SIZE * count)


def _prefix_run(emu, sites, seed=None):
    """Re-enter the directory decoder and stop at its AES-init call.

    Returns ``(key32, iv, expected_crc)``.  The key schedule, the IV and the
    register holding the CRC the firmware will demand are all live at that
    point, so one run of a few milliseconds answers everything the encoder
    needs -- and because the key derivation reads only the seed word, poking a
    different seed into the guest's copy-on-write view of the card (image.bin
    is never touched) yields that seed's key and IV."""
    if getattr(emu, "_narrow", False):
        raise MasterDirError(
            "the sound-bank directory must be read before the emulator "
            "switches to decode hooks")
    from .emulator import _R
    addr = _guest_seed_addr(emu)
    saved = None
    out = {}

    def at_aes(e):
        m = e.mu
        out["key"] = bytes(m.mem_read(m.reg_read(UC_ARM_REG_R1), 32))
        out["iv"] = bytes(m.mem_read(m.reg_read(UC_ARM_REG_R2), 16))
        out["expect"] = m.reg_read(_R[sites["CRC_EXPECT_REG"]])
        m.emu_stop()

    if seed is not None:
        emu._ensure_range(addr, 4)
        saved = bytes(emu.mu.mem_read(addr, 4))
        emu.mu.mem_write(addr, _p32(seed))
    emu.add_hook(sites["AES_INIT"], at_aes)
    try:
        emu.call(emu.MASTERDIR_DECODE, (0,), limit=60_000_000)
    finally:
        emu.del_hook(sites["AES_INIT"])
        if saved is not None:
            emu.mu.mem_write(addr, saved)
    if "key" not in out:
        raise MasterDirError(
            "the firmware did not reach its sound-bank key schedule")
    return out["key"], out["iv"], out["expect"]


def _build_seed_map(session):
    """Measure the firmware's seed-to-expected-CRC map and prove it linear."""
    emu, sites = session.emu, session.sites
    f0 = _prefix_run(emu, sites, seed=0)[2]
    basis = [_prefix_run(emu, sites, seed=1 << i)[2] ^ f0 for i in range(32)]
    bm = BitMap(f0, basis)
    for probe in (0x5a5a5a5a, 0x0f1e2d3c):
        got = _prefix_run(emu, sites, seed=probe)[2]
        if bm.apply(probe) != got or bm.invert(got) != probe:
            raise MasterDirUnsupported(
                "this game version derives its sound-bank checksum in a way "
                "this version of the app cannot reproduce")
    return bm


def keygen(emu, seed=None):
    """``(key, iv)`` the firmware derives for ``seed`` (default: the card's own
    seed word).  One short run of the firmware; nothing is reimplemented."""
    session = _session(emu)
    key32, iv, _expect = _prefix_run(emu, session.sites, seed=seed)
    if session.keylen is None:
        # 24 on every build seen; confirmed for real by read_directory, which
        # only accepts the length whose plaintext passes the firmware's own
        # checksum.  Fall back to the trailing-zero shape when a caller asks
        # for a key before any directory has been read.
        session.keylen = 24 if key32[24:32] == b"\x00" * 8 else 32
    return key32[:session.keylen], iv


# --------------------------------------------------------------------------
# read / write
# --------------------------------------------------------------------------
def read_tail_bytes(image_path):
    """``(md_off, count, tail_bytes)`` for an image, checked for plausibility.

    Cheap and firmware-free, so a bad header is reported before an emulator is
    involved.  On a stock card the directory IS the file tail; on a grown one
    the appended bodies follow it, so the file only has to be long enough to
    hold the directory -- a wrong offset or count is caught by the checksum in
    :func:`read_directory`."""
    with open(image_path, "rb") as f:
        md_off, count = header_geometry(f.read(0x100))
        f.seek(0, 2)
        filesize = f.tell()
        if not 0 < count <= MAX_RECORDS:
            raise MasterDirError("implausible sound-bank record count %d" % count)
        need = md_off + tail_len(count)
        if md_off < 0x100 or need > filesize:
            raise MasterDirError(
                "sound bank geometry does not add up: the header says %d "
                "records at 0x%x, which needs a %d-byte file, but it is %d"
                % (count, md_off, need, filesize))
        f.seek(md_off)
        return md_off, count, f.read(tail_len(count))


def read_directory(image_path, emu):
    """Decode the master directory of ``image_path``.

    ``emu`` is a booted :class:`~.emulator.Spike2Emu` on the same firmware; it
    supplies the key schedule.  It does NOT have to be the emulator for this
    particular image, so a staged copy can be read with the card's emulator.

    Raises :class:`MasterDirError` if the decoded array fails the firmware's
    own checksum -- the same gate the machine applies at boot, recomputed
    here, so a directory that would not load is never returned as if it had."""
    md_off, count, blob = read_tail_bytes(image_path)
    session = _session(emu)
    seed = _u32(blob, align16(RECORD_SIZE * count))
    key32, iv, expect = _prefix_run(emu, session.sites, seed=seed)
    want = session.seed_map().apply(seed)
    if want != expect:
        raise MasterDirError("the firmware's checksum for this seed is not "
                             "reproducible (0x%08x vs 0x%08x)" % (want, expect))
    for keylen in ((session.keylen,) if session.keylen else (24, 32, 16)):
        d = unpack_tail(blob, count, key32[:keylen], iv, md_off)
        if crc(session.crc_init, d.records + d.padded_plain) == expect:
            session.keylen = keylen
            d.crc_value = expect
            return d
    raise MasterDirError(
        "the sound bank directory did not decode to something the firmware "
        "would accept (checksum mismatch)")


def write_directory(directory, emu):
    """``{file_offset: bytes}`` that turn an image into one carrying
    ``directory``: the rebuilt tail at its directory offset, and the record
    count in the header.  ``hdr[0x40]`` never moves.

    The seed is chosen, not kept: the firmware demands a checksum that is a
    permutation of the seed word, so the seed is whatever maps to the checksum
    of the records being written."""
    session = _session(emu)
    n = directory.count
    want = crc(session.crc_init, directory.records + directory.padded_plain)
    seed = session.seed_map().invert(want)
    if seed is None:
        raise MasterDirError("no seed word produces checksum 0x%08x" % want)
    key, iv = keygen(emu, seed)
    return {directory.md_off: pack_tail(directory, key, iv, seed),
            HDR_COUNT: _p32(n)}
