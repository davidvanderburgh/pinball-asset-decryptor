"""JJPE asset-crypto scheme 3 — the engine rebuild that shipped with Sonic.

Reverse-engineered 2026-07-28 from a live memory dump of Sonic's decrypted
``game`` binary (``set_seeds_for_crypto`` @ VA 0x6C0E30, ``rand64`` @ 0x6C0C90,
``hash_string`` @ 0x6DEC60, and the decrypt loop in ``fm_load_file_into_ram``
@ 0x6A9D38).  The dump came from a dongle-extract run on a real machine; the
routines it exposed turn out to need **no dongle secret at all**, so scheme-3
titles decrypt in pure Python exactly like the older ones.

What stayed the same
--------------------
The generator is byte-for-byte the old jcrypt ``rand64`` (LCG ``*0x19BAFFBED
+ 0x12D687``, xorshift 13/17/43, 58-bit counter) and the keystream is still
XORed 8 bytes at a time in little-endian order.  :mod:`.crypto` therefore
supplies both, unchanged.

What changed
------------
1. **A sixth hash input.**  Scheme 2 hashed 5 buffers derived from the path;
   scheme 3 adds ``swapcase(path)``.
2. **Different assembly** of those 6 hashes into the 4 state words.
3. **A key string mixes into the seed.**  The 32 seed bytes are each rotated
   by ``(k >> 1) & 7``, left when ``k & 1`` else right, where ``k`` cycles
   through a key string.  The key is the **game directory name** ("Sonic")
   for a title's own assets and the literal ``core`` for the shared
   ``ecoredata`` tree.  Only bits 0-3 of each key byte are used, so the key
   is effectively case-insensitive.
4. **A post-XOR shuffle.**  The first 128 bytes of the content have each
   8-byte group byte-reversed (a ``pshufb`` pass in the decrypt loop).
5. **Trailing filler.**  The container grew a second random pad:
   ``[lead filler][content][trail filler]``.  Scheme 2 ran content to EOF.
   Both pads are multiples of 8 plus alignment; the lead pad is always a
   multiple of 8, which is what makes dongle-free detection reliable here.

The game reads both pad sizes out of ``fl.dat``, which is still encrypted by
the dongle-only routine, so dongle-free extraction detects the lead pad from
the content signature (as it always has) and finds the content end
structurally — see :func:`trim_trailing_filler`.

This module also carries the non-latin-1 path handling the pinned JJP modules
lack (:func:`write_filelist` / :func:`read_filelist_text`) — Sonic ships asset
names that ``crypto.py`` and ``filelist.py`` cannot encode at all.
"""

import os
import struct

try:
    from .crypto import (PRNG, xor_keystream, crc32_buf, S2_MASK, M64,
                         _MAGIC_TABLE, _TEXT_EXTS, _PRINTABLE,
                         _crc32_partial, _crc32_reverse, _crc32_forge_4bytes,
                         detect_filler_size as _legacy_detect_filler_size)
except ImportError:  # deployed flat into WSL/Docker as jjp_crypto_v3.py
    from jjp_crypto import (PRNG, xor_keystream, crc32_buf, S2_MASK, M64,
                            _MAGIC_TABLE, _TEXT_EXTS, _PRINTABLE,
                            _crc32_partial, _crc32_reverse,
                            _crc32_forge_4bytes,
                            detect_filler_size as _legacy_detect_filler_size)

SCHEME_LEGACY = 2
SCHEME_V3 = 3

#: Key used for the shared ``ecoredata`` / core-engine trees.
CORE_KEY = b"core"

#: Bytes of content whose 8-byte groups are byte-reversed after the XOR.
SHUFFLE_BYTES = 128

#: The lead filler is always a multiple of 8, so candidates step by 8.
FILLER_STEP = 8

#: Signatures :data:`.crypto._MAGIC_TABLE` doesn't carry.  Sonic ships a
#: working Photoshop file among its LED artwork, and the pinned scheme-2
#: table has no entry for it, so detection would give up on a file that
#: decrypts perfectly well.
_EXTRA_MAGIC = {
    ".psd": [b"8BPS"],
}


def _signatures(ext):
    return _MAGIC_TABLE.get(ext) or _EXTRA_MAGIC.get(ext) or []


# ---------- hashing ----------

def path_bytes(path):
    """The exact bytes the game hashes for *path*.

    The game hashes a ``char *``, i.e. the raw on-disk name, so the encoding
    has to round-trip the filesystem rather than be picked by us.
    ``os.fsencode`` does that (UTF-8 + surrogateescape on Linux, where the
    decrypt actually runs).  Scheme 2 hard-codes ``latin-1`` and simply
    raises on anything outside it — Sonic ships assets with a U+2019
    apostrophe, so that path is not viable here.
    """
    if isinstance(path, (bytes, bytearray)):
        return bytes(path)
    try:
        return os.fsencode(path)
    except (UnicodeEncodeError, TypeError):
        return path.encode("utf-8", "surrogateescape")


def hash_string(data):
    """BKDR-131 hash over **signed** chars.

    The game sign-extends each byte (``movsx`` at 0x6DEC80).  For ASCII paths
    this matches :func:`.crypto.hash_string`; it diverges on bytes >= 0x80,
    which non-ASCII filenames are made of — so this is spelled out rather
    than reused.
    """
    if isinstance(data, str):
        data = path_bytes(data)
    h = 0
    for b in data:
        h = (h * 131 + (b - 256 if b >= 128 else b)) & 0xFFFFFFFF
    return h


def _swapcase(p):
    out = bytearray(len(p))
    for i, c in enumerate(p):
        if 0x61 <= c <= 0x7A:      # islower -> toupper
            out[i] = c - 32
        elif 0x41 <= c <= 0x5A:    # isupper -> tolower
            out[i] = c + 32
        else:
            out[i] = c
    return bytes(out)


# ---------- key selection ----------

def crypto_key(path, game_name):
    """Return the key string that seeds *path*.

    Shared engine trees are keyed by ``core``; a title's own assets are keyed
    by its game directory name (the same token already used to build the
    path), so no per-title constant is needed.
    """
    if "/ecoredata/" in path or "/JJPECore/" in path or "/miscfiles/" in path:
        return CORE_KEY
    return path_bytes(game_name or "")


# ---------- seeding ----------

def set_seeds_for_crypto(prng, path, key):
    """Seed *prng* the way scheme 3's ``set_seeds_for_crypto`` does."""
    p = path_bytes(path)
    k = path_bytes(key)
    if not k:
        raise ValueError("scheme-3 seeding needs a non-empty key string")

    h0 = hash_string(p)
    h1 = hash_string(bytes(reversed(p)))
    h2 = hash_string(bytes(c for c in p if c != 0x2F))
    h3 = hash_string(bytes(c for c in reversed(p) if c != 0x2F))
    h4 = hash_string(bytes((c + 1) & 0xFF for c in p))
    h5 = hash_string(_swapcase(p))

    buf = bytearray(struct.pack(
        "<4Q",
        ((h4 << 32) | (h2 ^ h0)) & M64,
        ((h1 << 32) | (h5 ^ h3)) & M64,
        (((h0 ^ h4) << 32) | h5) & M64,
        (((h1 ^ h3) << 32) | h2) & M64,
    ))

    for i in range(32):
        kc = k[i % len(k)]
        rot = (kc >> 1) & 7
        b = buf[i]
        if kc & 1:
            buf[i] = ((b << rot) | (b >> (8 - rot))) & 0xFF
        else:
            buf[i] = ((b >> rot) | (b << (8 - rot))) & 0xFF

    s3, s1, s0, s2 = struct.unpack("<4Q", bytes(buf))
    prng.set_seeds(s0, s1, s2 & S2_MASK, s3)


# ---------- the shuffle ----------

def _unshuffle(buf, off):
    """Byte-reverse each 8-byte group across the first 128 bytes of content."""
    end = min(off + SHUFFLE_BYTES, len(buf))
    i = off
    while i + 8 <= end:
        buf[i:i + 8] = buf[i:i + 8][::-1]
        i += 8


# ---------- decrypt ----------

def decrypt_plaintext(encrypted_data, path, game_name):
    """XOR the whole blob and undo nothing — the raw scheme-3 plaintext.

    The 128-byte shuffle sits at the content start, which isn't known until
    the filler is detected, so it is applied separately by :func:`decrypt_file`.
    """
    prng = PRNG()
    set_seeds_for_crypto(prng, path, crypto_key(path, game_name))
    return xor_keystream(encrypted_data, prng)


def decrypt_file(encrypted_data, filler_size, path, game_name, trim=True):
    """Decrypt one scheme-3 asset.

    Args:
        encrypted_data: Raw bytes from disk.
        filler_size: Lead filler length (a multiple of 8).
        path: Absolute path, the same string scheme 2 uses as its key.
        game_name: Game directory name, e.g. ``"Sonic"``.
        trim: Drop the trailing filler by finding the structural end of the
            content.  Off gives you everything to EOF.

    Returns:
        The decrypted content bytes.
    """
    buf = bytearray(decrypt_plaintext(encrypted_data, path, game_name))
    _unshuffle(buf, filler_size)
    content = bytes(buf[filler_size:])
    return trim_trailing_filler(content, path) if trim else content


# ---------- filler detection ----------

def _reversed_words(pt):
    """The plaintext with every 8-byte group byte-reversed."""
    return b"".join(pt[i:i + 8][::-1] for i in range(0, len(pt) - 7, 8))


def detect_filler_size(encrypted_data, path, game_name, max_filler=1024):
    """Locate the lead filler without ``fl.dat``.

    The content signature lands inside the shuffled window, so the search
    runs against the byte-reversed stream, and only 8-aligned offsets are
    considered (the lead filler is always a multiple of 8).

    Returns the filler size, or -1 when nothing matched.
    """
    probe_len = min(len(encrypted_data), max_filler + SHUFFLE_BYTES + 64)
    pt = decrypt_plaintext(encrypted_data[:probe_len], path, game_name)
    rv = _reversed_words(pt)
    limit = min(max_filler, max(0, len(rv) - 8))

    ext = os.path.splitext(path)[1].lower()

    for sig in _signatures(ext):
        for fs in range(0, limit + 1, FILLER_STEP):
            if rv[fs:fs + len(sig)] == sig:
                return fs

    if ext in _TEXT_EXTS:
        # Filler is random (~37% printable); text content is ~100%.  Both the
        # shuffled and unshuffled halves stay printable under byte reversal,
        # so a straight run test works — and 8-alignment removes the
        # ambiguity that makes the scheme-2 heuristic so fiddly.
        run = 64
        for fs in range(0, limit + 1, FILLER_STEP):
            window = rv[fs:fs + run]
            if len(window) < run:
                break
            if all(c in _PRINTABLE for c in window):
                return fs

    # Unknown extension: accept any signature at an 8-aligned offset.
    for sigs in _MAGIC_TABLE.values():
        for sig in sigs:
            if len(sig) >= 4:
                for fs in range(0, limit + 1, FILLER_STEP):
                    if rv[fs:fs + len(sig)] == sig:
                        return fs

    return -1


# ---------- trailing filler ----------

def _png_end(c):
    off = 8
    while off + 8 <= len(c):
        ln, typ = struct.unpack(">I4s", c[off:off + 8])
        off += 12 + ln
        if typ == b"IEND":
            return off if off <= len(c) else -1
        if off > len(c):
            return -1
    return -1


def _riff_end(c):
    if len(c) < 8:
        return -1
    size = struct.unpack("<I", c[4:8])[0] + 8
    return size if 8 <= size <= len(c) else -1


def _jpeg_end(c):
    i = c.rfind(b"\xff\xd9")
    return i + 2 if i >= 0 else -1


def _ogg_end(c):
    off = 0
    end = -1
    while off + 27 <= len(c) and c[off:off + 4] == b"OggS":
        nsegs = c[off + 26]
        if off + 27 + nsegs > len(c):
            break
        body = sum(c[off + 27:off + 27 + nsegs])
        off += 27 + nsegs + body
        if off > len(c):
            break
        end = off
    return end


def _sfnt_end(c):
    """TrueType/OpenType: end of the last table in the directory."""
    if len(c) < 12:
        return -1
    num = struct.unpack(">H", c[4:6])[0]
    if num == 0 or 12 + num * 16 > len(c):
        return -1
    end = 0
    for i in range(num):
        rec = 12 + i * 16
        off, ln = struct.unpack(">II", c[rec + 8:rec + 16])
        end = max(end, off + ln)
    end = (end + 3) & ~3          # tables are 4-byte aligned
    return end if end <= len(c) else -1


def _text_end(c):
    """Drop the random trailing pad.

    The pad is ~37% printable, so it never sustains a long printable run.
    Find the last fully-printable 16-byte window and extend to the end of
    its run; a stray printable pad byte or two may survive, but real text is
    never truncated.
    """
    win = 16
    i = len(c) - win
    while i >= 0:
        if all(b in _PRINTABLE for b in c[i:i + win]):
            j = i + win
            while j < len(c) and c[j] in _PRINTABLE:
                j += 1
            return j
        i -= 1
    return -1


_ENDERS = {
    ".png": _png_end,
    ".wav": _riff_end,
    ".avi": _riff_end,
    ".jpg": _jpeg_end,
    ".jpeg": _jpeg_end,
    ".ogg": _ogg_end,
    ".ttf": _sfnt_end,
    ".otf": _sfnt_end,
}


def trim_trailing_filler(content, path):
    """Cut the trailing filler off *content*.

    Falls back to returning *content* untouched when the format has no
    cheap structural end marker (webm, and anything unrecognised) — trailing
    bytes are harmless there, and guessing risks truncating real data.
    """
    ext = os.path.splitext(path)[1].lower()
    ender = _ENDERS.get(ext)
    if ender is None and ext in _TEXT_EXTS:
        ender = _text_end
    if ender is None:
        return content
    try:
        end = ender(content)
    except Exception:
        return content
    if 0 < end <= len(content):
        return content[:end]
    return content


# ---------- fl_decrypted.dat I/O that survives non-latin-1 names ----------

def write_filelist(entries, output_path):
    """``filelist.write_fl_dat`` in UTF-8 instead of latin-1.

    The pinned writer opens the file as latin-1 and raises on any name
    outside it, which killed the run *after* all 16,207 assets had already
    been decrypted and written.  Same CSV format, byte-identical output for
    ASCII paths — including the platform newline translation the pinned
    writer gets from ``open(..., "w")``, so sidecars stay byte-identical.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write("{},{},{},{}\n".format(
                e.path, e.filler_size, e.crc_encrypted, e.crc_decrypted))


def read_filelist_text(path):
    """Read a filelist as text for ``filelist.parse_fl_dat``.

    ``parse_fl_dat`` uses a str containing newlines verbatim, so handing it
    correctly-decoded text keeps non-ASCII paths intact without touching the
    pinned parser.  UTF-8 first, latin-1 as the fallback so sidecars written
    by older versions still load.
    """
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if not text.strip():
        return "\n"
    return text if text.endswith("\n") else text + "\n"


# ---------- re-encrypting ----------

class SizeMismatch(ValueError):
    """The replacement content is not the same length as the original."""


def reencrypt_asset(original_encrypted, new_content, path, game_name,
                    filler_size=None):
    """Rebuild a scheme-3 asset around *new_content*.

    Everything the game reads out of ``fl.dat`` is left untouched: the lead
    pad, the trail pad and the file length all stay exactly as they were, and
    four bytes of the lead pad are forged so the whole file still hashes to
    the value ``fl.dat`` records.  That is the only integrity check the loader
    performs, and it was read straight out of the game's own decrypted code
    (``fm_load_file_into_ram``, ``../JJPECore/file_manager.cpp``)::

        006a9ce7  xor   edi, edi              ; seed 0
        006a9ced  mov   rdx, r12              ; r12 = the full size read
        006a9cf0  mov   rsi, r11              ; r11 = start of the buffer
        006a9d19  call  0x849700              ; crc32(0, buf, size)
        006a9d1e  cmp   dword ptr [rbx+0x18], eax   ; vs the fl.dat record

    So the scope is the **whole file**, trailing pad included — nothing
    subtracts the pads — the seed is 0, and 0x849700 is a plain table-driven
    CRC-32 whose table (0xC669A0) is the standard one, bit-identical to
    ``zlib.crc32``.  It is the only crc32 call site in the file manager (50
    exist binary-wide).  There is no decrypted-content checksum in that path,
    which is why nothing has to be appended to the content and the length can
    stay exact.  Because the stock file passes on a stock machine, the stored
    value is by definition the CRC of the bytes already on the card, so the
    target needs no ``fl.dat`` lookup.

    A mismatch is not fatal, for what it's worth: the loader logs
    ``FILE CHECK ERROR: <path>`` to ``/jjpe/temp/game.log``, sets the flag
    behind the operator message "Missing or corrupted file(s) - reinstall
    game", and jumps straight back into the decrypt path, so the asset still
    loads.  A wrong forge shows up as that message, not as a dead machine.

    Because ``fl.dat`` is dongle-encrypted we can neither read nor rewrite the
    pad sizes, so the replacement has to be the same length as the original
    content.  The target hash needs no lookup either: it is simply the CRC-32
    of the file already on the card.

    Args:
        original_encrypted: The asset's current bytes, straight off the image.
        new_content: Replacement content, same length as the original's.
        path: Absolute asset path (the crypto key).
        game_name: Game directory name, e.g. ``"Sonic"``.
        filler_size: Lead pad, if already known; detected otherwise.

    Returns:
        Encrypted bytes to write back, same length as *original_encrypted*.

    Raises:
        SizeMismatch: if the lengths differ.
        ValueError: if the asset isn't scheme 3 or the forge fails.
    """
    f1 = filler_size
    if f1 is None:
        f1 = detect_filler_size(original_encrypted, path, game_name)
    if f1 < 0:
        raise ValueError("could not locate the lead pad — not a scheme-3 "
                         "asset, or an unrecognised content type")
    if f1 < 4:
        raise ValueError("lead pad too small to carry the CRC forge")

    plain = bytearray(decrypt_plaintext(original_encrypted, path, game_name))
    _unshuffle(plain, f1)
    orig_content = trim_trailing_filler(bytes(plain[f1:]), path)
    if len(new_content) != len(orig_content):
        raise SizeMismatch(
            "replacement is %d bytes, original content is %d; the game reads "
            "the content length from fl.dat, which is dongle-encrypted and "
            "cannot be updated" % (len(new_content), len(orig_content)))

    plain[f1:f1 + len(new_content)] = new_content
    _unshuffle(plain, f1)                      # shuffle is its own inverse
    out = bytearray(xor_keystream(bytes(plain),
                                  _seeded_prng(path, game_name)))
    _forge_crc(out, f1 - 4, crc32_buf(original_encrypted))
    return bytes(out)


def _seeded_prng(path, game_name):
    prng = PRNG()
    set_seeds_for_crypto(prng, path, crypto_key(path, game_name))
    return prng


def _forge_crc(buf, pos, target):
    """Set ``buf[pos:pos+4]`` so ``crc32(buf) == target``.

    The CRC helpers are imported at module scope, not here: this module is
    also deployed *flat* into WSL as ``jjp_crypto_v3.py``, where a relative
    import raises at call time — which is exactly how a 16,440-file
    re-encrypt run failed with every file erroring.
    """
    state_a = _crc32_partial(bytes(buf[:pos])) if pos else 0xFFFFFFFF
    state_b = _crc32_reverse(target ^ 0xFFFFFFFF, bytes(buf[pos + 4:]))
    forged = _crc32_forge_4bytes(state_a, state_b)
    if forged is None:
        raise ValueError("CRC-32 forge failed for target %#010x" % target)
    buf[pos:pos + 4] = forged


# ---------- writing back is not supported ----------

#: Why a scheme-3 title extracts but cannot be written back.
#:
#: Re-encrypting needs three things we do not have.  The cipher itself we now
#: know, but the game reads each asset's *two* pad sizes and its checksums out
#: of ``fl.dat``, and Sonic-era ``fl.dat`` is encrypted by the dongle-only
#: routine — we can neither read the originals nor write updated ones.  The
#: pinned scheme-2 encryptor would happily produce a file whose CRC self-check
#: passes (it round-trips against the scheme-2 decryptor) while the game reads
#: garbage, so this has to fail loudly rather than be attempted.
WRITE_UNSUPPORTED = (
    "This game uses Jersey Jack's newer asset encryption (scheme 3), which "
    "this app can extract but cannot write back.\n\n"
    "Writing would need the game's fl.dat — it stores each asset's padding "
    "sizes and checksums — and on this generation fl.dat is encrypted by the "
    "machine's HASP dongle, so it can't be read or updated. Re-encrypting "
    "without it produces files the game cannot load, and the built-in "
    "checksum check would still report success, so the write is blocked "
    "rather than risk a card that looks fine and isn't.\n\n"
    "Extract, Replace-preview and Mod Pack still work; only writing back to "
    "an image or SSD is unavailable."
)


# ---------- scheme dispatch ----------

def detect_scheme(encrypted_data, path, game_name, max_filler=1024):
    """Return ``(scheme, filler_size)`` for one asset, or ``(None, -1)``.

    Scheme 2 is tried first so pre-Sonic titles take exactly the path they
    always did.
    """
    try:
        fs = _legacy_detect_filler_size(encrypted_data, path,
                                        max_filler=max_filler)
    except UnicodeEncodeError:
        # crypto.py is pinned byte-identical to upstream and encodes the key
        # path as latin-1, which raises on names outside it (Sonic ships a
        # U+2019 apostrophe).  Such a file cannot be scheme 2 anyway, so fall
        # through to scheme 3 rather than let one filename kill the run.
        fs = -1
    if fs >= 0:
        return SCHEME_LEGACY, fs

    if game_name:
        fs = detect_filler_size(encrypted_data, path, game_name,
                                max_filler=max_filler)
        if fs >= 0:
            return SCHEME_V3, fs

    return None, -1
