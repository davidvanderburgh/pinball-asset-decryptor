"""BC3/DXT5 texture codec for Stern Spike 2 scene assets.

Spike 2 stores its LCD scene textures (font-glyph atlases, sprite art) as the
non-``ftyp`` ``scene.assets/<N>.asset`` files: **raw BC3/DXT5 block data with no
container header**.  Pinball Browser calls them "DDS" because BC3 *is* the DDS
DXT5 format — PB simply adds/strips the 128-byte DDS header on export/import.
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
"""

import struct
import numpy as np


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

    # ---- colour block: bounding-box endpoints, 4-colour palette ----
    rmax, rmin = R.max(axis=1), R.min(axis=1)
    gmax, gmin = G.max(axis=1), G.min(axis=1)
    bmax, bmin = B.max(axis=1), B.min(axis=1)
    c0 = _pack565(rmax, gmax, bmax)
    c1 = _pack565(rmin, gmin, bmin)
    # decode endpoints back to 8-bit (so indices match what the decoder sees)
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)
    cR = np.stack([r0, r1, (2 * r0 + r1) // 3, (r0 + 2 * r1) // 3], axis=1)
    cG = np.stack([g0, g1, (2 * g0 + g1) // 3, (g0 + 2 * g1) // 3], axis=1)
    cB = np.stack([b0, b1, (2 * b0 + b1) // 3, (b0 + 2 * b1) // 3], axis=1)
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
    """Wrap raw BC3 block bytes in a DDS container (what PB exports)."""
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
