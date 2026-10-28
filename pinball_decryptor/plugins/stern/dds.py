"""BC3/DXT5 texture codec for Stern Spike 2 scene assets.

Spike 2 stores its LCD scene textures (font-glyph atlases, sprite art) as the
non-``ftyp`` ``scene.assets/<N>.asset`` files: **raw BC3/DXT5 block data with no
container header**.  They're commonly called "DDS" because BC3 *is* the DDS DXT5
format — exporting/importing is just adding/stripping the 128-byte DDS header.
Each texture's width/height/format live inline in the co-located
``scene.radium`` (see :func:`.engine.parse_texture_descriptors`); the ``.asset``
is pure block data, 1 byte per pixel (``len == width * height``).

This module decodes those raw blocks to RGBA and re-encodes RGBA back to raw BC3
(size-neutral by construction: identical W×H ⇒ identical byte length), plus
DDS-header wrap/unwrap so a user can round-trip through a real ``.dds`` file in
their image editor.

BC3 layout (16 bytes / 4×4 block): bytes 0-7 = alpha block (a0, a1, then 16×
3-bit indices, LSB-first); bytes 8-15 = colour block (RGB565 c0, c1, then 16×
2-bit indices).  BC3's colour block is **always** decoded in 4-colour mode
regardless of the c0/c1 ordering (unlike BC1).

Spike 2 also ships some textures as **BC1/DXT1** (the radium descriptor's
``format`` enum ``4``): 8 bytes / 4×4 block, half the size of BC3.  BC1's colour
block is mode-switched on the c0/c1 ordering — ``c0 > c1`` ⇒ 4-colour opaque,
``c0 <= c1`` ⇒ 3-colour + 1-bit punch-through alpha (index 3 = transparent
black).  :func:`decode_bc1` / :func:`encode_bc1` handle both modes and are
size-neutral by construction just like the BC3 pair.
"""

import struct

from ...core.lazy_import import lazy_module

# numpy loads on first use, not with this module (PAD-797): the Modes tab
# imports this chain at startup, on the UI loop.
np = lazy_module("numpy")


# --------------------------------------------------------------------------
# RGB565 helpers (vectorised)
# --------------------------------------------------------------------------
def _unpack565(c):
    """uint16 RGB565 array -> (r, g, b) uint16 arrays expanded to 0-255."""
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return r.astype(np.int32), g.astype(np.int32), b.astype(np.int32)


def _pack565(r, g, b):
    """(r, g, b) 0-255 arrays -> uint16 RGB565 array."""
    return (((r.astype(np.uint16) >> 3) << 11)
            | ((g.astype(np.uint16) >> 2) << 5)
            | (b.astype(np.uint16) >> 3)).astype(np.uint16)


def _palette4(c0, c1):
    """The 4-colour palette (r, g, b), each ``(nb, 4)``, two RGB565 endpoints decode to."""
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)
    return tuple(np.stack([x0, x1, (2 * x0 + x1) // 3, (x0 + 2 * x1) // 3], axis=1)
                 for x0, x1 in ((r0, r1), (g0, g1), (b0, b1)))


def _endpoints(R, G, B, seen=None, alpha=None):
    """``(c0, c1)`` RGB565 endpoints per block, for the 4-colour palette.

    PAD-306: the corners of the block's RGB bounding box, along the ONE of its four
    diagonals that fits the block best. The (max, max, max) - (min, min, min) diagonal
    alone puts colours whose channels run against each other on a line through neither:
    yellow (255, 230, 0) and magenta (255, 0, 255) became red and pale pink, so a mode
    screen's yellow title on its magenta panel came out speckled and stair-stepped.

    *seen* ``(nb, 16)`` bool leaves texels out of the fit: BC1's punch-through texels, which
    decode transparent whatever the endpoints are. Never BC3's clear texels: the game's
    textures are premultiplied, so a clear texel's colour is added on the glass and has to
    stay black. *alpha* (BC3's) makes that a rule of the fit: colour decoded on a clear
    texel costs far more than any colour error, so a block that cannot hold its clear
    texels' black and its two colours keeps the black (the main diagonal's low corner, as
    before)."""
    if seen is None:
        w = np.ones(R.shape, dtype=bool)
    else:
        w = np.where(seen.any(axis=1)[:, None], seen, True)   # a fully clear block: all of it
    big = np.int32(1 << 20)
    lo = [np.where(w, X, big).min(axis=1) for X in (R, G, B)]
    hi = [np.where(w, X, -big).max(axis=1) for X in (R, G, B)]
    best, best_err = None, None
    for flip_g in (False, True):
        for flip_b in (False, True):
            e0 = (hi[0], lo[1] if flip_g else hi[1], lo[2] if flip_b else hi[2])
            e1 = (lo[0], hi[1] if flip_g else lo[1], hi[2] if flip_b else lo[2])
            c0, c1 = _pack565(*e0), _pack565(*e1)
            cR, cG, cB = _palette4(c0, c1)
            dist = ((R[:, :, None] - cR[:, None, :]) ** 2
                    + (G[:, :, None] - cG[:, None, :]) ** 2
                    + (B[:, :, None] - cB[:, None, :]) ** 2)
            err = np.where(w, dist.min(axis=2), 0).sum(axis=1)
            if alpha is not None:
                pick = dist.argmin(axis=2)
                lit = sum(np.take_along_axis(cX, pick, axis=1) ** 2 for cX in (cR, cG, cB))
                err = err + 64 * np.where(alpha == 0, lit, 0).sum(axis=1)
            if best is None:
                best, best_err = (c0, c1), err
            else:
                take = err < best_err
                best = (np.where(take, c0, best[0]).astype(np.uint16),
                        np.where(take, c1, best[1]).astype(np.uint16))
                best_err = np.where(take, err, best_err)
    return best


# --------------------------------------------------------------------------
# Decode
# --------------------------------------------------------------------------
def decode_bc3(raw, width, height):
    """Decode raw BC3/DXT5 block bytes to an ``(height, width, 4)`` uint8 RGBA
    array.  ``len(raw)`` must be ``ceil(w/4)*ceil(h/4)*16``."""
    bx = (width + 3) // 4
    by = (height + 3) // 4
    nb = bx * by
    need = nb * 16
    if len(raw) < need:
        raise ValueError("BC3 data too short: have %d, need %d (%dx%d)"
                         % (len(raw), need, width, height))
    d = np.frombuffer(raw[:need], dtype=np.uint8).reshape(nb, 16).astype(np.int32)

    # ---- alpha ----
    a0 = d[:, 0]
    a1 = d[:, 1]
    ap = np.zeros((nb, 8), dtype=np.float32)
    ap[:, 0] = a0
    ap[:, 1] = a1
    greater = (a0 > a1)[:, None]
    iA = np.arange(1, 7)
    modeA = ((7 - iA) * a0[:, None] + iA * a1[:, None]) / 7.0       # 6 interp
    iB = np.arange(1, 5)
    modeB = ((5 - iB) * a0[:, None] + iB * a1[:, None]) / 5.0       # 4 interp
    ap[:, 2:8] = np.where(greater, modeA, np.concatenate(
        [modeB, np.zeros((nb, 1)), np.full((nb, 1), 255.0)], axis=1))
    # 48-bit alpha index word -> 16 × 3-bit
    aidx = np.zeros(nb, dtype=np.uint64)
    for i in range(6):
        aidx |= d[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    a_ind = np.empty((nb, 16), dtype=np.int64)
    for t in range(16):
        a_ind[:, t] = (aidx >> np.uint64(3 * t)) & np.uint64(7)
    alpha = np.take_along_axis(ap, a_ind, axis=1)                  # (nb,16)

    # ---- colour (always 4-colour mode for BC3) ----
    c0 = (d[:, 8] | (d[:, 9] << 8)).astype(np.uint16)
    c1 = (d[:, 10] | (d[:, 11] << 8)).astype(np.uint16)
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)
    cR = np.stack([r0, r1, (2 * r0 + r1) // 3, (r0 + 2 * r1) // 3], axis=1)
    cG = np.stack([g0, g1, (2 * g0 + g1) // 3, (g0 + 2 * g1) // 3], axis=1)
    cB = np.stack([b0, b1, (2 * b0 + b1) // 3, (b0 + 2 * b1) // 3], axis=1)
    cbits = (d[:, 12] | (d[:, 13] << 8)
             | (d[:, 14] << 16) | (d[:, 15] << 24)).astype(np.uint32)
    c_ind = np.empty((nb, 16), dtype=np.int64)
    for t in range(16):
        c_ind[:, t] = (cbits >> np.uint32(2 * t)) & np.uint32(3)
    R = np.take_along_axis(cR, c_ind, axis=1)
    G = np.take_along_axis(cG, c_ind, axis=1)
    B = np.take_along_axis(cB, c_ind, axis=1)

    # ---- assemble blocks (texel t = (ty*4+tx), row-major) into image ----
    px = np.empty((nb, 16, 4), dtype=np.uint8)
    px[:, :, 0] = R
    px[:, :, 1] = G
    px[:, :, 2] = B
    px[:, :, 3] = np.clip(np.rint(alpha), 0, 255).astype(np.uint8)
    img = np.zeros((by * 4, bx * 4, 4), dtype=np.uint8)
    block = px.reshape(by, bx, 4, 4, 4)            # (by,bx,ty,tx,rgba)
    img = block.transpose(0, 2, 1, 3, 4).reshape(by * 4, bx * 4, 4)
    return img[:height, :width].copy()


def decode_bc1(raw, width, height):
    """Decode raw BC1/DXT1 block bytes to an ``(height, width, 4)`` uint8 RGBA
    array.  ``len(raw)`` must be ``ceil(w/4)*ceil(h/4)*8``.

    Mode is per-block: ``c0 > c1`` ⇒ 4-colour opaque palette; ``c0 <= c1`` ⇒
    3-colour palette + index 3 = transparent black (1-bit punch-through alpha)."""
    bx = (width + 3) // 4
    by = (height + 3) // 4
    nb = bx * by
    need = nb * 8
    if len(raw) < need:
        raise ValueError("BC1 data too short: have %d, need %d (%dx%d)"
                         % (len(raw), need, width, height))
    d = np.frombuffer(raw[:need], dtype=np.uint8).reshape(nb, 8).astype(np.int32)

    c0 = (d[:, 0] | (d[:, 1] << 8)).astype(np.uint16)
    c1 = (d[:, 2] | (d[:, 3] << 8)).astype(np.uint16)
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)
    four = (c0 > c1)[:, None]                                   # 4-colour mode
    # palette entry 2/3 differ per mode; 0/1 are the endpoints either way
    cR = np.stack([r0, r1,
                   np.where(four[:, 0], (2 * r0 + r1) // 3, (r0 + r1) // 2),
                   np.where(four[:, 0], (r0 + 2 * r1) // 3, 0)], axis=1)
    cG = np.stack([g0, g1,
                   np.where(four[:, 0], (2 * g0 + g1) // 3, (g0 + g1) // 2),
                   np.where(four[:, 0], (g0 + 2 * g1) // 3, 0)], axis=1)
    cB = np.stack([b0, b1,
                   np.where(four[:, 0], (2 * b0 + b1) // 3, (b0 + b1) // 2),
                   np.where(four[:, 0], (b0 + 2 * b1) // 3, 0)], axis=1)
    # alpha palette: opaque for 0/1/2; index 3 transparent only in 3-colour mode
    aP = np.where(four, np.uint16(255), np.uint16(255)).repeat(4, axis=1).astype(np.int32)
    aP[:, 3] = np.where(four[:, 0], 255, 0)

    cbits = (d[:, 4] | (d[:, 5] << 8)
             | (d[:, 6] << 16) | (d[:, 7] << 24)).astype(np.uint32)
    c_ind = np.empty((nb, 16), dtype=np.int64)
    for t in range(16):
        c_ind[:, t] = (cbits >> np.uint32(2 * t)) & np.uint32(3)
    R = np.take_along_axis(cR, c_ind, axis=1)
    G = np.take_along_axis(cG, c_ind, axis=1)
    B = np.take_along_axis(cB, c_ind, axis=1)
    A = np.take_along_axis(aP, c_ind, axis=1)

    px = np.empty((nb, 16, 4), dtype=np.uint8)
    px[:, :, 0] = R
    px[:, :, 1] = G
    px[:, :, 2] = B
    px[:, :, 3] = A.astype(np.uint8)
    block = px.reshape(by, bx, 4, 4, 4)
    img = block.transpose(0, 2, 1, 3, 4).reshape(by * 4, bx * 4, 4)
    return img[:height, :width].copy()


# --------------------------------------------------------------------------
# Encode (range-fit: simple, correct, fast)
# --------------------------------------------------------------------------
def encode_bc3(rgba):
    """Encode an ``(h, w, 4)`` uint8 RGBA array to raw BC3/DXT5 block bytes.

    Uses min/max range fit per block (alpha endpoints = min/max alpha in 8-value
    mode; colour endpoints = RGB bounding-box corners) — not rate-distortion
    optimal, but correct and deterministic.  Output length is exactly
    ``ceil(w/4)*ceil(h/4)*16``."""
    rgba = np.asarray(rgba, dtype=np.uint8)
    h, w, ch = rgba.shape
    if ch != 4:
        raise ValueError("encode_bc3 needs RGBA (h,w,4)")
    bx = (w + 3) // 4
    by = (h + 3) // 4
    # pad to a whole number of 4×4 blocks (edge replicate)
    ph, pw = by * 4, bx * 4
    if (ph, pw) != (h, w):
        pad = np.zeros((ph, pw, 4), dtype=np.uint8)
        pad[:h, :w] = rgba
        if pw > w:
            pad[:h, w:] = rgba[:, w - 1:w]
        if ph > h:
            pad[h:, :] = pad[h - 1:h, :]
        rgba = pad
    # (by,bx,ty,tx,rgba) -> (nb,16,4) with t = ty*4+tx
    blocks = rgba.reshape(by, 4, bx, 4, 4).transpose(0, 2, 1, 3, 4)
    nb = by * bx
    blocks = blocks.reshape(nb, 16, 4).astype(np.int32)
    R = blocks[:, :, 0]
    G = blocks[:, :, 1]
    B = blocks[:, :, 2]
    A = blocks[:, :, 3]
    out = np.zeros((nb, 16), dtype=np.uint8)

    # ---- alpha block: a0=max, a1=min (a0>=a1 -> 8-value mode) ----
    amax = A.max(axis=1)
    amin = A.min(axis=1)
    out[:, 0] = amax.astype(np.uint8)
    out[:, 1] = amin.astype(np.uint8)
    iA = np.arange(1, 7)
    ap = np.empty((nb, 8), dtype=np.float32)
    ap[:, 0] = amax
    ap[:, 1] = amin
    ap[:, 2:8] = ((7 - iA) * amax[:, None] + iA * amin[:, None]) / 7.0
    # nearest palette entry per texel (handles amax==amin: all distances equal -> 0)
    a_ind = np.abs(A[:, :, None] - ap[:, None, :]).argmin(axis=2).astype(np.uint64)
    aidx = np.zeros(nb, dtype=np.uint64)
    for t in range(16):
        aidx |= (a_ind[:, t] & np.uint64(7)) << np.uint64(3 * t)
    for i in range(6):
        out[:, 2 + i] = ((aidx >> np.uint64(8 * i)) & np.uint64(0xFF)).astype(np.uint8)

    # ---- colour block: the best bounding-box diagonal, 4-colour palette ----
    c0, c1 = _endpoints(R, G, B, alpha=A)
    # decode endpoints back to 8-bit (so indices match what the decoder sees)
    cR, cG, cB = _palette4(c0, c1)
    # nearest of 4 palette entries (squared distance)
    dist = ((R[:, :, None] - cR[:, None, :]) ** 2
            + (G[:, :, None] - cG[:, None, :]) ** 2
            + (B[:, :, None] - cB[:, None, :]) ** 2)
    c_ind = dist.argmin(axis=2).astype(np.uint32)
    cbits = np.zeros(nb, dtype=np.uint32)
    for t in range(16):
        cbits |= (c_ind[:, t] & np.uint32(3)) << np.uint32(2 * t)
    out[:, 8] = (c0 & 0xFF).astype(np.uint8)
    out[:, 9] = (c0 >> 8).astype(np.uint8)
    out[:, 10] = (c1 & 0xFF).astype(np.uint8)
    out[:, 11] = (c1 >> 8).astype(np.uint8)
    for i in range(4):
        out[:, 12 + i] = ((cbits >> np.uint32(8 * i)) & np.uint32(0xFF)).astype(np.uint8)

    return out.tobytes()


def encode_bc1(rgba):
    """Encode an ``(h, w, 4)`` uint8 RGBA array to raw BC1/DXT1 block bytes.

    Per block: if every texel is opaque (alpha >= 128) it uses the 4-colour
    opaque mode (``c0 > c1``); otherwise it uses the 3-colour punch-through mode
    (``c0 <= c1``) with transparent texels (alpha < 128) mapped to index 3.
    Bounding-box endpoints, nearest-palette indices — deterministic, not
    rate-distortion optimal.  Output length is exactly ``ceil(w/4)*ceil(h/4)*8``
    (half of BC3), the size-neutral property the in-place patcher relies on."""
    rgba = np.asarray(rgba, dtype=np.uint8)
    h, w, ch = rgba.shape
    if ch != 4:
        raise ValueError("encode_bc1 needs RGBA (h,w,4)")
    bx = (w + 3) // 4
    by = (h + 3) // 4
    ph, pw = by * 4, bx * 4
    if (ph, pw) != (h, w):
        pad = np.zeros((ph, pw, 4), dtype=np.uint8)
        pad[:h, :w] = rgba
        if pw > w:
            pad[:h, w:] = rgba[:, w - 1:w]
        if ph > h:
            pad[h:, :] = pad[h - 1:h, :]
        rgba = pad
    blocks = rgba.reshape(by, 4, bx, 4, 4).transpose(0, 2, 1, 3, 4)
    nb = by * bx
    blocks = blocks.reshape(nb, 16, 4).astype(np.int32)
    R = blocks[:, :, 0]
    G = blocks[:, :, 1]
    B = blocks[:, :, 2]
    A = blocks[:, :, 3]
    out = np.zeros((nb, 8), dtype=np.uint8)

    transp = A < 128                                   # (nb,16) punch-through
    has_alpha = transp.any(axis=1)                     # (nb,) -> 3-colour mode
    # the best bounding-box diagonal over the texels that show (_endpoints), ordered so hi
    # packs >= lo: the mode is chosen by the order below, and indices are fitted after it
    e0, e1 = _endpoints(R, G, B, seen=~transp)
    hi = np.maximum(e0, e1).astype(np.uint16)
    lo = np.minimum(e0, e1).astype(np.uint16)
    # 4-colour opaque wants c0 > c1 (= hi, lo); 3-colour wants c0 <= c1 (= lo, hi)
    c0 = np.where(has_alpha, lo, hi).astype(np.uint16)
    c1 = np.where(has_alpha, hi, lo).astype(np.uint16)
    four = (c0 > c1)                                    # matches decoder's test
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)
    f = four[:, None]
    cR = np.stack([r0, r1,
                   np.where(four, (2 * r0 + r1) // 3, (r0 + r1) // 2),
                   np.where(four, (r0 + 2 * r1) // 3, 0)], axis=1)
    cG = np.stack([g0, g1,
                   np.where(four, (2 * g0 + g1) // 3, (g0 + g1) // 2),
                   np.where(four, (g0 + 2 * g1) // 3, 0)], axis=1)
    cB = np.stack([b0, b1,
                   np.where(four, (2 * b0 + b1) // 3, (b0 + b1) // 2),
                   np.where(four, (b0 + 2 * b1) // 3, 0)], axis=1)
    dist = ((R[:, :, None] - cR[:, None, :]) ** 2
            + (G[:, :, None] - cG[:, None, :]) ** 2
            + (B[:, :, None] - cB[:, None, :]) ** 2).astype(np.int64)
    # in 3-colour blocks index 3 is transparent: forbid it for opaque texels
    forbid3 = (~f) & (~transp)                          # (nb,16)
    dist[:, :, 3] = np.where(forbid3, np.int64(1) << 40, dist[:, :, 3])
    c_ind = dist.argmin(axis=2).astype(np.uint32)
    c_ind = np.where(transp, np.uint32(3), c_ind)       # transparent -> index 3
    cbits = np.zeros(nb, dtype=np.uint32)
    for t in range(16):
        cbits |= (c_ind[:, t] & np.uint32(3)) << np.uint32(2 * t)
    out[:, 0] = (c0 & 0xFF).astype(np.uint8)
    out[:, 1] = (c0 >> 8).astype(np.uint8)
    out[:, 2] = (c1 & 0xFF).astype(np.uint8)
    out[:, 3] = (c1 >> 8).astype(np.uint8)
    for i in range(4):
        out[:, 4 + i] = ((cbits >> np.uint32(8 * i)) & np.uint32(0xFF)).astype(np.uint8)
    return out.tobytes()


# --------------------------------------------------------------------------
# DDS container wrap / unwrap (for round-tripping through a real .dds file)
# --------------------------------------------------------------------------
_DDS_MAGIC = b"DDS "
_DDSD = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000     # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
_DDPF_FOURCC = 0x4
_DDSCAPS_TEXTURE = 0x1000


def dds_header(width, height, linear_size, fourcc=b"DXT5"):
    """Build a 128-byte DDS header for a single-mip DXT-compressed texture."""
    hdr = _DDS_MAGIC + struct.pack("<I", 124)
    hdr += struct.pack("<IIIII", _DDSD, height, width, linear_size, 0)
    hdr += struct.pack("<I", 0)                 # mipMapCount
    hdr += b"\x00" * 44                          # reserved[11]
    hdr += struct.pack("<II", 32, _DDPF_FOURCC) + fourcc + b"\x00" * 20
    hdr += struct.pack("<IIIII", _DDSCAPS_TEXTURE, 0, 0, 0, 0)
    assert len(hdr) == 128, len(hdr)
    return hdr


def to_dds(raw, width, height, fourcc=b"DXT5"):
    """Wrap raw BC3 block bytes in a DDS container."""
    return dds_header(width, height, len(raw), fourcc) + raw


def from_dds(blob):
    """Strip a DDS header -> ``(raw_blocks, width, height, fourcc)``.  Accepts a
    DXT5/BC3 ``.dds``; raises on other formats."""
    if blob[:4] != _DDS_MAGIC or len(blob) < 128:
        raise ValueError("not a DDS file")
    height, width = struct.unpack_from("<II", blob, 12)
    fourcc = blob[84:88]
    if fourcc not in (b"DXT5", b"DXT4"):
        raise ValueError("unsupported DDS fourcc %r (need DXT5/BC3)" % fourcc)
    return blob[128:], width, height, fourcc
