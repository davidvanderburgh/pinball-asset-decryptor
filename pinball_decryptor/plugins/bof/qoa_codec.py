"""Pure-Python QOA (Quite-OK Audio) codec.

Reference: https://qoaformat.org/qoa-specification.pdf and the C
implementation at https://github.com/phoboslab/qoa.

QOA is a fast lossy 16-bit PCM codec at roughly 3.2:1 compression.
BOF stores ~70 % of Dune's audio as QOA inside the Godot
AudioStreamWAV ``data`` PackedByteArray; without a decoder users
can't easily play those files in standard tools, and without an
encoder we can't round-trip user-edited WAVs back into the .fun.

File layout (all multi-byte fields big-endian):

  qoaf magic    (4 bytes)
  total_samples (u32, per-channel sample count for the whole file)
  qoa_frame...

  qoa_frame:
    channels         (u8)
    samplerate       (u24)
    samples_per_chan (u16, max 5120)
    frame_size       (u16, total bytes including these 8)
    lms_state        (channels × 16 bytes — 4 history + 4 weights, s16 BE)
    slices           (channels × ceil(samples_per_chan / 20) × 8 bytes,
                      each holding a 4-bit scalefactor + 20 × 3-bit residuals)

LMS predictor (per channel):
  predicted = sum(history[i] * weights[i] for i in 0..3) >> 13
  After decode/encode of each sample:
    delta = quantised_residual_dequant >> 4
    weights[i] += delta * (1 if history[i] >= 0 else -1)
    history[0..2] = history[1..3]
    history[3]    = clamped_decoded_sample
"""

import struct


# Scale factors (the SF index 0-15 picks which entry).
_SF_TAB = [1, 7, 21, 45, 84, 138, 211, 304,
           421, 562, 731, 928, 1157, 1419, 1715, 2048]

# Dequantisation table — _DEQUANT[sf][q] gives the dequantised residual
# for scalefactor *sf* and 3-bit residual *q*.  Hardcoded verbatim from
# the QOA reference (qoa.h ``qoa_dequant_tab``) — empirically tuned
# constants, not derivable from a clean formula due to integer rounding
# at the edges (positive vs negative half values round different ways).
_DEQUANT = [
    [   1,    -1,    3,    -3,    5,    -5,     7,     -7],
    [   5,    -5,   18,   -18,   32,   -32,    49,    -49],
    [  16,   -16,   53,   -53,   95,   -95,   147,   -147],
    [  34,   -34,  113,  -113,  203,  -203,   315,   -315],
    [  63,   -63,  210,  -210,  378,  -378,   588,   -588],
    [ 104,  -104,  345,  -345,  621,  -621,   966,   -966],
    [ 158,  -158,  528,  -528,  950,  -950,  1477,  -1477],
    [ 228,  -228,  760,  -760, 1368, -1368,  2128,  -2128],
    [ 316,  -316, 1053, -1053, 1895, -1895,  2947,  -2947],
    [ 422,  -422, 1405, -1405, 2529, -2529,  3934,  -3934],
    [ 548,  -548, 1828, -1828, 3290, -3290,  5117,  -5117],
    [ 696,  -696, 2320, -2320, 4176, -4176,  6496,  -6496],
    [ 868,  -868, 2893, -2893, 5207, -5207,  8099,  -8099],
    [1064, -1064, 3548, -3548, 6386, -6386,  9933,  -9933],
    [1286, -1286, 4288, -4288, 7718, -7718, 12005, -12005],
    [1536, -1536, 5120, -5120, 9216, -9216, 14336, -14336],
]


def _clamp16(v):
    if v < -32768:
        return -32768
    if v > 32767:
        return 32767
    return v


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def decode(qoa_bytes):
    """Decode a QOA byte string into ``(samples, channels, samplerate)``.

    ``samples`` is a ``bytes`` object holding interleaved 16-bit
    little-endian signed PCM (ready to drop into a WAV ``data`` chunk).
    """
    if qoa_bytes[:4] != b"qoaf":
        raise ValueError(f"not a QOA file (magic = {qoa_bytes[:4]!r})")
    total_samples = struct.unpack(">I", qoa_bytes[4:8])[0]
    p = 8

    out = bytearray()
    channels = None
    samplerate = None

    while p < len(qoa_bytes):
        if p + 8 > len(qoa_bytes):
            break
        ch = qoa_bytes[p]
        sr = (qoa_bytes[p+1] << 16) | (qoa_bytes[p+2] << 8) | qoa_bytes[p+3]
        spc = struct.unpack(">H", qoa_bytes[p+4:p+6])[0]
        fsz = struct.unpack(">H", qoa_bytes[p+6:p+8])[0]
        if channels is None:
            channels, samplerate = ch, sr

        # LMS state per channel
        lms_h = []
        lms_w = []
        q = p + 8
        for _ in range(ch):
            history = list(struct.unpack(">4h", qoa_bytes[q:q+8]))
            weights = list(struct.unpack(">4h", qoa_bytes[q+8:q+16]))
            lms_h.append(history)
            lms_w.append(weights)
            q += 16

        # Per-channel: ceil(spc/20) slices of 8 bytes each
        slices_per_ch = (spc + 19) // 20
        # Decoded samples per channel for this frame (sized for interleave)
        ch_samples = [[0] * spc for _ in range(ch)]
        for sl_idx in range(slices_per_ch):
            for c in range(ch):
                if q + 8 > len(qoa_bytes):
                    break
                slice_word = struct.unpack(">Q", qoa_bytes[q:q+8])[0]
                q += 8
                sf = (slice_word >> 60) & 0xF
                base_i = sl_idx * 20
                for k in range(20):
                    i = base_i + k
                    if i >= spc:
                        break
                    qv = (slice_word >> (57 - k * 3)) & 0x7
                    dequant = _DEQUANT[sf][qv]
                    # LMS predict
                    pred = sum(lms_h[c][j] * lms_w[c][j] for j in range(4)) >> 13
                    sample = _clamp16(pred + dequant)
                    ch_samples[c][i] = sample
                    # Update weights: delta = dequant >> 4, weight += delta * sign(history)
                    delta = dequant >> 4
                    for j in range(4):
                        if lms_h[c][j] < 0:
                            lms_w[c][j] -= delta
                        else:
                            lms_w[c][j] += delta
                    # Shift history
                    lms_h[c][0] = lms_h[c][1]
                    lms_h[c][1] = lms_h[c][2]
                    lms_h[c][2] = lms_h[c][3]
                    lms_h[c][3] = sample

        # Interleave channels into LE 16-bit PCM
        for i in range(spc):
            for c in range(ch):
                out += struct.pack("<h", ch_samples[c][i])

        # Advance to next frame
        p += fsz
        if fsz == 0:
            break  # malformed

    return bytes(out), channels or 1, samplerate or 44100


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

_FRAME_SAMPLES = 5120  # samples per channel per frame (QOA spec max)


def _lms_predict(h, w):
    return (h[0] * w[0] + h[1] * w[1] + h[2] * w[2] + h[3] * w[3]) >> 13


def _encode_slice(samples_20, lms_h, lms_w):
    """Encode up to 20 samples into one 8-byte slice.

    Matches the qoa.h reference encoder: for each of the 16
    scalefactors, runs the same decode loop the player will use,
    picking the q value that minimises per-sample reconstruction
    error, and finally keeps the (slice_word, lms_state) pair with
    the lowest total squared error across the slice.

    Returns ``(slice_word, lms_h, lms_w)`` — the LMS state is the
    state AFTER decoding the chosen slice, ready for the next call.
    """
    best_word = 0
    best_err = None
    best_h = None
    best_w = None

    for sf in range(16):
        h = list(lms_h)
        w = list(lms_w)
        slice_word = sf << 60
        err = 0
        for k, s in enumerate(samples_20):
            pred = _lms_predict(h, w)
            # Try all 8 q values, pick the one whose dequantised
            # residual produces the closest reconstructed sample.  The
            # decoder uses dequant directly (not scaled by SF), so we
            # only need the LMS state matching, not a separate residual
            # scaling step.
            best_q = 0
            best_sample = 0
            best_q_err = None
            for q in range(8):
                dequant = _DEQUANT[sf][q]
                candidate = _clamp16(pred + dequant)
                d = abs(candidate - s)
                if best_q_err is None or d < best_q_err:
                    best_q_err = d
                    best_q = q
                    best_sample = candidate
            err += best_q_err * best_q_err
            slice_word |= best_q << (57 - k * 3)
            # Update LMS exactly as the decoder will
            dequant = _DEQUANT[sf][best_q]
            delta = dequant >> 4
            for j in range(4):
                if h[j] < 0:
                    w[j] -= delta
                else:
                    w[j] += delta
            h[0] = h[1]
            h[1] = h[2]
            h[2] = h[3]
            h[3] = best_sample
        if best_err is None or err < best_err:
            best_err = err
            best_word = slice_word
            best_h = h
            best_w = w

    return best_word, best_h, best_w


def encode(pcm_bytes, channels, samplerate):
    """Encode interleaved 16-bit LE PCM into a QOA byte string.

    ``pcm_bytes`` must be a multiple of ``channels * 2`` bytes.
    Returns the full ``.qoa`` file (with header + frames).
    """
    if channels < 1 or channels > 8:
        raise ValueError(f"unsupported channel count: {channels}")
    if len(pcm_bytes) % (channels * 2) != 0:
        raise ValueError("PCM byte count not divisible by channels * 2")

    total_samples = len(pcm_bytes) // (channels * 2)
    out = bytearray()
    out += b"qoaf"
    out += struct.pack(">I", total_samples)

    # Initial LMS state per channel — matches the C reference encoder.
    INITIAL_W = [0, 0, -(1 << 13), (1 << 14)]
    INITIAL_H = [0, 0, 0, 0]
    lms_h = [list(INITIAL_H) for _ in range(channels)]
    lms_w = [list(INITIAL_W) for _ in range(channels)]

    pos = 0
    while pos < total_samples:
        spc = min(_FRAME_SAMPLES, total_samples - pos)
        slices_per_ch = (spc + 19) // 20

        # De-interleave samples for this frame, per channel
        ch_samples = [[] for _ in range(channels)]
        for i in range(spc):
            base = (pos + i) * channels * 2
            for c in range(channels):
                ch_samples[c].append(
                    struct.unpack_from("<h", pcm_bytes, base + c * 2)[0])

        # Frame header
        frame = bytearray()
        frame += bytes([channels])
        frame += bytes([(samplerate >> 16) & 0xFF,
                        (samplerate >> 8) & 0xFF,
                        samplerate & 0xFF])
        frame += struct.pack(">H", spc)
        # frame_size filled in after we know slice count
        frame += b"\x00\x00"

        # LMS state per channel
        for c in range(channels):
            frame += struct.pack(">4h", *lms_h[c])
            frame += struct.pack(">4h", *lms_w[c])

        # Slices — channel-interleaved
        for sl_idx in range(slices_per_ch):
            for c in range(channels):
                start = sl_idx * 20
                samples_20 = ch_samples[c][start:start + 20]
                slice_word, new_h, new_w = _encode_slice(
                    samples_20, lms_h[c], lms_w[c])
                frame += struct.pack(">Q", slice_word)
                lms_h[c] = new_h
                lms_w[c] = new_w

        # Patch frame_size at offset 6
        struct.pack_into(">H", frame, 6, len(frame))
        out += frame
        pos += spc

    return bytes(out)
