#!/usr/bin/env python3
"""audioscore.py <source.wav> <capture.wav> [...] - measure the damage, not a proxy.

Settle "does the audio path sound right" with a number instead of an argument.
Play a file whose samples you already have, record the SPEAKERS, and run:

    python3 audioscore.py source.wav capture.wav

Recording the speakers is the part people skip. Anything captured inside WSL
sits upstream of the WSLg fault and reads perfectly clean while the room does
not; on Windows use a loopback input such as
`ffmpeg -f dshow -i "audio=What U Hear (...)"`.

Reference scores from the run that built this, same file and rig throughout:
  -13.6 dB  Windows playing the file itself      (flawless)
  +16.4 dB  through WSLg's PulseAudio            (crackly)
  -14.7 dB  through playaudio.sh's Windows sink  (flawless)

WHY IT DOES NOT SIMPLY SCORE THE RECORDING. Three hand-rolled crackle metrics in
a row failed the only test that matters: on labelled files, the known-GOOD
capture scored worse than the known-BAD one. Counting "jumps" or "roughness"
measures the programme material as much as the defect, so music always outscores
a sine and nothing is comparable to anything. A pure tone is worse still - it
came back clean from a path that was destroying music.

So stop scoring the capture on its own. We know exactly what was played. Align
the recording to the source, fit the gain, and SUBTRACT. Whatever is left over
is, by construction, the damage the path did - resampler aliasing, underrun
clicks, dropped blocks, all of it - with the programme material removed.

  resid dB   residual energy relative to signal. -40 is clean, -20 is plainly
             audible damage, -10 is wreckage. THIS IS THE NUMBER.
  slips      blocks where the alignment jumped, i.e. samples were dropped or
             repeated. This is "the music skipped a beat", counted.
  drift      net alignment change end to end, in ms - a clock-rate mismatch
             between the player and the sound card shows up here and nowhere
             else.
  worst      the loudest few damaged moments, so they can be listened to.
"""
import sys, wave, numpy as np
from scipy import signal

BLOCK = 0.25          # s, fine enough to localise a click
SEARCH = 600          # samples of slack per block
TAPS = 128            # FIR fitted per block; see FIT below

def load(path):
    with wave.open(path, "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit(f"{path}: {sw*8}-bit, expected 16")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr

def analyse(src_path, cap_path):
    src, ssr = load(src_path)
    cap, csr = load(cap_path)
    if csr != ssr:                       # bring the capture onto the source clock
        cap = signal.resample_poly(cap, ssr, csr)
    sr = ssr

    # Coarse alignment: correlate a clean loud slice of the capture against the
    # whole source. Taken from the middle because captures usually open on
    # silence, and silence correlates with everything.
    win = int(4 * sr)
    mid = max(0, len(cap) // 2 - win // 2)
    probe = cap[mid:mid + win]
    if len(probe) < win // 2:
        return f"{cap_path}: capture too short"
    xc = signal.correlate(src - src.mean(), probe - probe.mean(), mode="valid", method="fft")
    base = int(np.argmax(np.abs(xc))) - mid      # src index that lines up with cap[0]

    nb = int(BLOCK * sr)
    off = base
    res_db, offs, slips = [], [], 0
    prev = None
    for b0 in range(0, len(cap) - nb, nb):
        c = cap[b0:b0 + nb]
        if np.sqrt((c * c).mean()) < 20:          # skip silence: nothing to damage
            continue
        lo = b0 + off - SEARCH
        hi = b0 + off + SEARCH + nb
        if lo < 0 or hi > len(src):
            continue
        seg = src[lo:hi]
        xc = signal.correlate(seg - seg.mean(), c - c.mean(), mode="valid", method="fft")
        k = int(np.argmax(xc))
        off = off - SEARCH + k
        # FIT. A gain alone is not enough. Integer alignment leaves a sub-sample
        # timing error, and subtracting a signal shifted by half a sample leaves
        # its derivative - which at 10 kHz is nearly as big as the signal. The
        # sound card's own EQ does the same thing. Both are LINEAR AND STABLE,
        # so fit a short FIR from source to capture and let it absorb them.
        # What a fixed filter cannot absorb is a click, a dropout or resampler
        # aliasing, because those are not linear time-invariant. So the residual
        # after this fit is the damage and nothing else.
        s0 = b0 + off - TAPS + 1
        if s0 < 0 or b0 + off + nb > len(src):
            continue
        S = np.lib.stride_tricks.sliding_window_view(src[s0:b0 + off + nb], TAPS)
        if S.shape[0] != nb:
            continue
        den0 = float(S[:, -1] @ S[:, -1])
        if den0 <= 0:
            continue
        h, *_ = np.linalg.lstsq(S, c, rcond=None)
        fit = S @ h
        den = float(fit @ fit)
        if den <= 0:
            continue
        r = c - fit
        rd = 10 * np.log10(max(float(r @ r), 1e-9) / den)
        res_db.append(rd)
        offs.append(off)
        if prev is not None and abs(off - prev) > 2:
            slips += 1
        prev = off

    if not res_db:
        return f"{cap_path}: no usable audio"
    res = np.array(res_db)
    order = np.argsort(res)[::-1][:3]
    worst = " ".join(f"{o * BLOCK:.1f}s:{res[o]:+.0f}" for o in order)
    drift = (offs[-1] - offs[0]) / sr * 1000
    name = cap_path.replace("\\", "/").split("/")[-1]
    return (f"{name:<24} resid {np.median(res):+6.1f} dB  "
            f"p90 {np.percentile(res, 90):+6.1f}  slips {slips:4d}  "
            f"drift {drift:+7.1f} ms  blocks {len(res):4d}  worst {worst}")

src = sys.argv[1]
for cap in sys.argv[2:]:
    try:
        print(analyse(src, cap))
    except Exception as e:
        print(f"{cap}: {type(e).__name__}: {e}")
