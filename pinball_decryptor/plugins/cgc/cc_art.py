"""Cactus Canyon ``cgc.so`` — CGC's colour display-art archive → PNG.

Despite the ``.so`` name, ``ccdata/cgc.so`` is not an ELF — it's CGC's
obfuscated **art archive** (the loose ``art/wmsimg.bin`` / ``newimg.bin`` /
``gels.bin`` files on the card are truncated decoys; the real, full members
live here).  The ``pin`` engine loads it via ``z5_ramfile_tarload`` (@0x7da48).

Container ("CCGC"):
  ``[0:4]``   uint32 CRC32 of ``magic+payload`` (IEEE, seed 0xffffffff, no final
              invert)
  ``[4:8]``   magic ``b"CCGC"``
  ``[8:0x10]``  version/flags
  ``[0x10:]``  **obfuscated** payload — a chain of members, each a 32-byte
              header ``{char name[16]; u32 size@0x10; u32 @0x14..0x1c}`` + ``size``
              payload bytes.  Members: ``wmsimg.bin``, ``newimg.bin`` (the pixel
              buffer), ``gels.bin``, ``cc_font.bin``.

De-obfuscation (closed form, verified byte-for-byte vs the real ``pin`` loop):
  ``plain[i] = enc[i] ^ K1[i%3] ^ K2[i%7] ^ K3[i%13] ^ K4[i%17] ^ K5[i%19]``,
  then ``if (i % 5) is odd: plain[i] = ROL8(plain[i], 3)`` (i=0 at file 0x10).

Images are indexed by a static ``cc_art`` array compiled into the ``pin``
binary (NOT in the archive): 2044 entries × 60 bytes —
``+0x00 name[32]``, ``+0x20 u32 width``, ``+0x24 u32 height``, ``+0x28 u32 flag``,
``+0x2c u32 data_off`` (offset into the ``newimg`` pixel buffer, in 16-bit
WORDS), ``+0x30`` three extra u32.  Pixels are 16-bit little-endian **RGB565**,
row-major ``width*height``; ``0x0000`` is rendered transparent.

We read ``cc_art`` straight out of the extracted ``pin`` ELF (the symbol
``cc_art``; falls back to a known vaddr).  Note the table is baked into the
binary, so a future ``pin`` build could move/resize it — we validate entries
and skip gracefully if the layout looks wrong.

This module is **extract-only**.  Repack (edited PNG → RGB565 → re-obfuscate →
fix CRC) is separate, future work.  See ``docs/CC_REVISITED_RE.md``.
"""

from __future__ import annotations

import json
import os
import struct
from typing import Callable, List, Optional

# cgc.so de-obfuscation keys (pin .rodata @ 0xc79c4/c8/d0/e0/f4; prime lengths).
_K1 = [10, 67, 194]
_K2 = [189, 94, 176, 23, 207, 155, 99]
_K3 = [231, 226, 119, 144, 165, 34, 204, 208, 36, 199, 166, 20, 133]
_K4 = [17, 55, 116, 56, 202, 236, 37, 246, 211, 152, 71, 155, 85, 103,
       209, 41, 145]
_K5 = [112, 163, 129, 197, 244, 7, 203, 50, 115, 192, 85, 18, 135, 181,
       68, 140, 114, 8, 243]

_CGC_MAGIC = b"CCGC"
_CC_ART_FALLBACK_VADDR = 0xFC694
_CC_ART_STRIDE = 60
_PIXBASE_MEMBER = "newimg.bin"


class ArtError(Exception):
    """cgc.so / pin weren't the expected Cactus Canyon art archive."""


# ---------------------------------------------------------------------------
# de-obfuscation
# ---------------------------------------------------------------------------

def cgc_deobfuscate(raw: bytes) -> bytes:
    """Return the de-obfuscated payload (the member chain) of a cgc.so blob.

    Validates the ``CCGC`` magic.  Uses numpy for the 70 MB transform.
    """
    import numpy as np

    if raw[4:8] != _CGC_MAGIC:
        raise ArtError(
            f"cgc.so magic mismatch: {raw[4:8]!r} (expected {_CGC_MAGIC!r})")
    enc = np.frombuffer(raw[0x10:], dtype=np.uint8)
    n = enc.size
    ks = (np.resize(np.array(_K1, np.uint8), n)
          ^ np.resize(np.array(_K2, np.uint8), n)
          ^ np.resize(np.array(_K3, np.uint8), n)
          ^ np.resize(np.array(_K4, np.uint8), n)
          ^ np.resize(np.array(_K5, np.uint8), n))
    plain = enc ^ ks
    # ROL8(x, 3) = (x<<3 | x>>5) & 0xff, where (i % 5) is odd.
    idx = np.arange(n)
    mask = (idx % 5) % 2 == 1
    rolled = (((plain.astype(np.uint16) << 3) | (plain >> 5)) & 0xFF
              ).astype(np.uint8)
    plain = np.where(mask, rolled, plain)
    return plain.tobytes()


def cgc_reobfuscate(body: bytes) -> bytes:
    """Inverse of the per-byte de-obfuscation — turn a de-obfuscated payload
    back into the on-disk obfuscated form.  ``decrypt`` does ``XOR`` then a
    conditional ``ROL8(,3)``; encrypt does the conditional ``ROR8(,3)`` then
    the same ``XOR``.  Requires numpy."""
    import numpy as np

    p = np.frombuffer(body, dtype=np.uint8).copy()
    n = p.size
    ks = (np.resize(np.array(_K1, np.uint8), n)
          ^ np.resize(np.array(_K2, np.uint8), n)
          ^ np.resize(np.array(_K3, np.uint8), n)
          ^ np.resize(np.array(_K4, np.uint8), n)
          ^ np.resize(np.array(_K5, np.uint8), n))
    idx = np.arange(n)
    mask = (idx % 5) % 2 == 1
    # ROR8(x, 3) = (x>>3 | x<<5) & 0xff  (undoes the decrypt's ROL8(,3))
    rored = (((p >> 3) | (p.astype(np.uint16) << 5)) & 0xFF).astype(np.uint8)
    t = np.where(mask, rored, p)
    return (t ^ ks).tobytes()


def _pin_crc(buf: bytes, seed: int) -> int:
    """CRC32 in pin's convention (IEEE table, seed 0xffffffff, no final invert).
    zlib stores the inverted running value, hence the double-invert dance."""
    import binascii
    return binascii.crc32(buf, seed ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def _rgb565_to_rgba(words, w, h):
    """RGB565 LE words (w*h) -> (h, w, 4) uint8 RGBA array.  0x0000 -> alpha 0."""
    import numpy as np
    v = words.astype(np.uint32)
    r = (((v >> 11) & 0x1F) * 255 // 31).astype(np.uint8)
    g = (((v >> 5) & 0x3F) * 255 // 63).astype(np.uint8)
    b = ((v & 0x1F) * 255 // 31).astype(np.uint8)
    a = np.where(v == 0, 0, 255).astype(np.uint8)
    return np.dstack([r, g, b, a]).reshape(h, w, 4)


def _decode_rle_words(src, total):
    """Decode a cgc.so RLE sprite token stream into ``total`` RGB565 words.

    16-bit LE tokens (verified against pin's ``z5_art_blit`` @0x6e184):
      * ``tok & 0x8000``  -> transparent run of ``tok & 0x7fff`` pixels (0x0000),
                             no payload words follow;
      * ``tok == 0``      -> no-op (consumes the token only);
      * else              -> literal run: the next ``tok`` words are RGB565.
    Used for frames whose ``cc_art`` ``extra[0] & 0x10000`` bit is set."""
    import numpy as np
    out = np.zeros(total, dtype=np.uint16)
    i = 0
    dest = 0
    n = src.size
    while dest < total:
        if i >= n:
            break
        tok = int(src[i]); i += 1
        if tok & 0x8000:
            dest += tok & 0x7FFF
        elif tok == 0:
            continue
        else:
            cnt = min(tok, total - dest, n - i)
            out[dest:dest + cnt] = src[i:i + cnt]
            i += tok
            dest += tok
    return out[:total]


def _frame_words(pix, doff_words, w, h, extra0):
    """Return the ``w*h`` RGB565 words for one frame, decoding RLE if needed.
    *pix* is a uint16 view of the whole newimg buffer."""
    total = w * h
    if extra0 & 0x10000:
        return _decode_rle_words(pix[doff_words:], total)
    return pix[doff_words:doff_words + total]


def _rgba_to_rgb565(arr):
    """(h, w, 4) uint8 RGBA -> RGB565 LE words (w*h,).  alpha 0 -> 0x0000."""
    import numpy as np
    r = arr[..., 0].astype(np.uint16)
    g = arr[..., 1].astype(np.uint16)
    b = arr[..., 2].astype(np.uint16)
    a = arr[..., 3]
    v = (((r * 31 // 255) << 11) | ((g * 63 // 255) << 5)
         | (b * 31 // 255)).astype(np.uint16)
    return np.where(a == 0, np.uint16(0), v).astype("<u2").reshape(-1)


def walk_members(body: bytes) -> List[dict]:
    """Parse the de-obfuscated member chain (name/size/data offset)."""
    members = []
    off = 0
    total = len(body)
    while off + 0x20 <= total:
        name = body[off:off + 16].split(b"\x00")[0].decode("latin1", "replace")
        size = struct.unpack_from("<I", body, off + 0x10)[0]
        data_off = off + 0x20
        if (not name or not name.isprintable() or size <= 0
                or data_off + size > total):
            break
        members.append({"name": name, "size": size, "data_off": data_off})
        off = data_off + size
    return members


# ---------------------------------------------------------------------------
# minimal ELF32 reader (pin is ARM 32-bit LSB; avoids a pyelftools dependency)
# ---------------------------------------------------------------------------

def _elf_sections(data: bytes):
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ArtError("pin is not a 32-bit little-endian ELF")
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", data, 0x30)[0]
    secs = []
    for i in range(e_shnum):
        b = e_shoff + i * e_shentsize
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
         sh_link, sh_info, sh_addralign, sh_entsize) = struct.unpack_from(
            "<10I", data, b)
        secs.append({"type": sh_type, "addr": sh_addr, "offset": sh_offset,
                     "size": sh_size, "link": sh_link, "entsize": sh_entsize})
    return secs


def _vaddr_to_offset(secs, vaddr):
    for s in secs:
        if s["type"] != 8 and s["addr"] and s["addr"] <= vaddr < s["addr"] + s["size"]:
            return s["offset"] + (vaddr - s["addr"])
    return None


def _find_symbol(data: bytes, secs, name: str):
    """Return (vaddr, size) for symbol *name*, or None."""
    target = name.encode()
    for s in secs:
        if s["type"] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[s["link"]]
        stroff, strsz = strtab["offset"], strtab["size"]
        ent = s["entsize"] or 16
        for o in range(s["offset"], s["offset"] + s["size"], ent):
            st_name = struct.unpack_from("<I", data, o)[0]
            if st_name == 0:
                continue
            nend = data.find(b"\x00", stroff + st_name, stroff + strsz)
            if data[stroff + st_name:nend] == target:
                st_value, st_size = struct.unpack_from("<II", data, o + 4)
                return st_value, st_size
    return None


def read_cc_art(pin_path: str) -> List[dict]:
    """Read the ``cc_art`` image index out of the ``pin`` ELF."""
    with open(pin_path, "rb") as f:
        data = f.read()
    secs = _elf_sections(data)
    sym = _find_symbol(data, secs, "cc_art")
    if sym is not None:
        vaddr, size = sym
        count = size // _CC_ART_STRIDE
    else:
        vaddr, count = _CC_ART_FALLBACK_VADDR, 0  # discover count by scanning
    base = _vaddr_to_offset(secs, vaddr)
    if base is None:
        raise ArtError(f"cc_art vaddr 0x{vaddr:x} not mapped in pin")
    ents = []
    i = 0
    while True:
        if count and i >= count:
            break
        b = base + i * _CC_ART_STRIDE
        if b + _CC_ART_STRIDE > len(data):
            break
        name = data[b:b + 32].split(b"\x00")[0].decode("latin1", "replace")
        # w@+0x20, h@+0x24, flag@+0x28, data_off@+0x2c, extra[0]@+0x30
        w, h, flag, doff, extra0 = struct.unpack_from("<5I", data, b + 0x20)
        if not count:
            # No symbol size: stop at the first entry that doesn't look valid.
            if not name or not name.isprintable() or not (0 < w <= 4096) \
                    or not (0 < h <= 4096):
                break
        ents.append({"idx": i, "name": name, "w": w, "h": h,
                     "flag": flag, "doff_words": doff, "extra0": extra0})
        i += 1
    return ents


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def extract_art(cgc_so_path: str, pin_path: str, out_dir: str,
                log_cb: Optional[Callable[[str, str], None]] = None,
                progress_cb: Optional[Callable[[int, int, str], None]] = None
                ) -> int:
    """De-obfuscate *cgc_so_path*, read the index from *pin_path*, and render
    every image to a PNG under *out_dir*.  Returns the number written.

    Raises :class:`ArtError` on a format mismatch, or ``ImportError`` if
    numpy/Pillow are unavailable.
    """
    import numpy as np
    from PIL import Image

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    with open(cgc_so_path, "rb") as f:
        raw = f.read()
    body = cgc_deobfuscate(raw)
    members = {m["name"]: m for m in walk_members(body)}
    if _PIXBASE_MEMBER not in members:
        raise ArtError(
            f"cgc.so missing {_PIXBASE_MEMBER} member "
            f"(found: {list(members)})")
    pm = members[_PIXBASE_MEMBER]
    pix = np.frombuffer(body, dtype="<u2",
                        count=pm["size"] // 2,
                        offset=pm["data_off"])

    ents = read_cc_art(pin_path)
    if not ents:
        raise ArtError("cc_art index empty / not found in pin")
    os.makedirs(out_dir, exist_ok=True)

    written = 0
    skipped = 0
    manifest = []
    total = len(ents)
    for e in ents:
        w, h, off, n = e["w"], e["h"], e["doff_words"], e["w"] * e["h"]
        e0 = e.get("extra0", 0)
        # raw needs w*h words in range; RLE needs only a valid start (it reads
        # a variable, smaller token stream).
        bad = (not (0 < w <= 4096 and 0 < h <= 4096) or off >= pix.size
               or (not (e0 & 0x10000) and off + n > pix.size))
        if bad:
            skipped += 1
            manifest.append({**e, "status": "skipped"})
            continue
        img = Image.fromarray(
            _rgb565_to_rgba(_frame_words(pix, off, w, h, e0), w, h), "RGBA")
        safe = "".join(c if (c.isalnum() or c in "_-") else "_"
                       for c in e["name"])
        fn = f"{e['idx']:04d}_{safe}.png"
        img.save(os.path.join(out_dir, fn))
        written += 1
        manifest.append({**e, "status": "ok", "file": fn})
        if progress_cb and (written % 64 == 0 or e["idx"] == total - 1):
            progress_cb(e["idx"] + 1, total, e["name"])

    with open(os.path.join(out_dir, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump({"format": "cgc_art_v1",
                   "source": os.path.basename(cgc_so_path),
                   "members": [{"name": k, "size": v["size"]}
                               for k, v in members.items()],
                   "image_count": written, "skipped": skipped,
                   "images": manifest}, f, indent=1)
    if skipped:
        log(f"  {skipped} art entr(ies) skipped (bad dims / out of range).",
            "info")
    return written


def repack_art(orig_cgc_so_path: str, pin_path: str, art_dir: str,
               out_cgc_so_path: str,
               log_cb: Optional[Callable[[str, str], None]] = None) -> dict:
    """Rebuild cgc.so with edited PNGs from *art_dir* re-encoded back in.

    For each ``display_art/<NNNN>_*.png`` whose pixels differ from what the
    archive currently holds (compared in rendered-RGBA space so untouched
    images aren't needlessly re-quantised), the PNG is re-encoded to RGB565
    and written into the ``newimg`` member at the image's offset.  Edited
    images must keep their original dimensions (so the member layout / offsets
    stay valid).  The payload is then re-obfuscated and the header CRC fixed.

    A no-op repack reproduces the original bytes exactly.  Returns
    ``{"modified_count": n, "total": count}``.
    """
    import glob as _glob

    import numpy as np
    from PIL import Image

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    with open(orig_cgc_so_path, "rb") as f:
        raw = f.read()
    body = bytearray(cgc_deobfuscate(raw))
    members = {m["name"]: m for m in walk_members(bytes(body))}
    if _PIXBASE_MEMBER not in members:
        raise ArtError(f"cgc.so missing {_PIXBASE_MEMBER} member")
    pix_base = members[_PIXBASE_MEMBER]["data_off"]
    pix_end = pix_base + members[_PIXBASE_MEMBER]["size"]
    ents = read_cc_art(pin_path)

    pix = np.frombuffer(bytes(body), dtype="<u2",
                        count=(pix_end - pix_base) // 2, offset=pix_base)
    modified = 0
    rle_edits = 0
    for e in ents:
        w, h, doff, n = e["w"], e["h"], e["doff_words"], e["w"] * e["h"]
        e0 = e.get("extra0", 0)
        if not (0 < w <= 4096 and 0 < h <= 4096):
            continue
        cands = _glob.glob(os.path.join(
            _glob.escape(art_dir), f"{e['idx']:04d}_*.png"))
        if len(cands) != 1:
            continue
        img = Image.open(cands[0]).convert("RGBA")
        if img.size != (w, h):
            log(f"  skip {os.path.basename(cands[0])}: dimensions "
                f"{img.size} != original ({w}x{h})", "warning")
            continue
        png_rgba = np.asarray(img, dtype=np.uint8)
        # RLE sprites are variable-length packed; re-encoding one would shift
        # every following frame AND the cc_art offsets baked into pin, so they
        # can't be repacked in place. Detect (and warn about) edits, skip them.
        if e0 & 0x10000:
            if doff >= pix.size:
                continue
            cur = _rgb565_to_rgba(_decode_rle_words(pix[doff:], n), w, h)
            if not np.array_equal(png_rgba, cur):
                rle_edits += 1
            continue
        boff = pix_base + doff * 2
        if boff + n * 2 > pix_end:
            continue
        cur_words = np.frombuffer(bytes(body[boff:boff + n * 2]), dtype="<u2")
        if np.array_equal(png_rgba, _rgb565_to_rgba(cur_words, w, h)):
            continue  # unchanged — leave the original bytes untouched
        body[boff:boff + n * 2] = _rgba_to_rgb565(png_rgba).tobytes()
        modified += 1

    if rle_edits:
        log(f"  note: {rle_edits} edited RLE-sprite frame(s) can't be repacked "
            f"(variable-length packed format) — those edits were skipped.",
            "warning")

    if modified:
        payload = cgc_reobfuscate(bytes(body))
        crc = _pin_crc(raw[4:8], 0xFFFFFFFF)
        crc = _pin_crc(payload, crc)
        with open(out_cgc_so_path, "wb") as f:
            f.write(struct.pack("<I", crc) + raw[4:0x10] + payload)
    return {"modified_count": modified, "total": len(ents)}
