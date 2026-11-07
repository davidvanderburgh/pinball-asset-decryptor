"""An expression light show made from the song itself (PAD-1040; David: "a way to automatically create light shows
from a music file because we want them to automatically sync up and look good and professional").

The song is read (a WAV, the project's own or its replacement) and its music measured: the beats (the onsets'
tempo, 70-180 BPM, each beat put on its own peak), the bars (the downbeat the strongest of the four), and how loud
each bar is against the rest of the song, which cuts it into SECTIONS - quiet, building, loud - and marks the DROPS
(a section much louder than the one before). The show is then cut on the bar lines: each section's own patterns from
the style (a quiet one breathes and fades, a building one sweeps and chases, a loud one strobes, swaps sides and
fills on the beat), every pattern's pace set from the beat so it lands on it, a drop opening with a white flash, the
song's start fading up and its end fading out. The colours move round the style's palette a section at a time; the
speaker lights breathe with the beat in the same colour. Steps are joined (two bars, four...) where the song is too
long for :data:`.cab_shows.STEPS_MAX`, and their lengths add up to the song's to the millisecond.

Pure numpy over the samples; :func:`analyse` is the measuring, :func:`make` the show."""
import math
import wave

from . import cab_shows as CS

#: the analysis rate and hop (an onset frame is HOP / RATE = 23 ms)
RATE = 11025
HOP = 256
FRAME = 1024
BPM_MIN, BPM_MAX = 70, 180
LEAD = 0.7

#: the styles: label, palette (a section's colour in turn), and the patterns of each kind of section, in turn bar by
#: bar: (fx, rate in beats - 0 = none, use b) with b "dim" (a darker shade of a) or "black"
STYLES = {
    "punchy": ("Punchy (rock)", ["#ff2000", "#ffb000", "#ffffff", "#ff0060", "#ff6000"],
               {"quiet": [("pulse", 1.0), ("crossfade", 0)],
                "build": [("sweep_up", 0), ("chase_up", 0.5), ("sweep_down", 0), ("bounce", 0)],
                "loud": [("strobe", 0.25), ("alternate", 1.0), ("fill_up", 0), ("meter", 0.5)]}),
    "smooth": ("Smooth", ["#4000ff", "#ff40a0", "#00a0ff", "#a040ff", "#00e0ff"],
               {"quiet": [("crossfade", 0), ("pulse", 2.0)],
                "build": [("center_out", 0), ("pulse", 1.0), ("center_in", 0)],
                "loud": [("sweep_up", 0), ("pulse", 0.5), ("sweep_down", 0), ("alternate", 2.0)]}),
    "party": ("Colourful (party)", ["#ff0000", "#ffd000", "#00ff60", "#00a0ff", "#a040ff", "#ff40a0"],
              {"quiet": [("rainbow", 2.0), ("pulse", 1.0)],
               "build": [("chase_up", 0.5), ("rainbow", 1.0), ("chase_down", 0.5)],
               "loud": [("strobe", 0.25), ("rainbow", 0.5), ("alternate", 0.5), ("sparkle", 0)]}),
}
DEFAULT_STYLE = "punchy"


class AutoError(Exception):
    pass


def _samples(path, max_seconds=900):
    """The song as mono floats at :data:`RATE`, and its length in ms."""
    import numpy as np
    try:
        with wave.open(path, "rb") as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            n = min(n, int(max_seconds * rate))
            raw = w.readframes(n)
    except (OSError, EOFError, wave.Error) as e:
        raise AutoError("the song could not be read (%s)" % e) from None
    if width != 2 or rate <= 0 or not n:
        raise AutoError("the song is not a 16-bit WAV the app can measure")
    a = np.frombuffer(raw[:len(raw) - len(raw) % (2 * ch)], dtype="<i2").astype(np.float32) / 32768.0
    a = a.reshape(-1, ch).mean(axis=1)
    step = max(1, int(round(rate / RATE)))
    m = len(a) // step * step
    a = a[:m].reshape(-1, step).mean(axis=1)
    return a, int(round(n * 1000.0 / rate)), rate / step


def analyse(path):
    """``{bpm, beat_ms, beats: [ms], bars: [ms], level: [0..1 per bar], sections: [{start, end, kind, drop}],
    length_ms}`` of the song in *path*."""
    import numpy as np
    x, length, sr = _samples(path)
    if len(x) < FRAME * 8:
        raise AutoError("the song is too short to find its beat")
    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(FRAME)[None, :].astype(np.float32)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logm = np.log1p(mag * 100.0)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    rms = np.sqrt((frames ** 2).mean(axis=1))
    # the onset envelope less its local mean: beats, not loudness
    k = 16
    smooth = np.convolve(flux, np.ones(k) / k, mode="same")
    onset = np.maximum(0.0, flux - smooth)
    fps = sr / HOP
    # tempo: the onsets' autocorrelation over 70-180 BPM, a gentle preference for 120
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    lags = np.arange(len(ac))
    lo, hi = int(fps * 60 / BPM_MAX), int(fps * 60 / BPM_MIN) + 1
    if hi >= len(ac):
        raise AutoError("the song is too short to find its beat")
    cand = lags[lo:hi]
    bpms = 60.0 * fps / cand
    score = ac[lo:hi] * np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    lag = cand[int(np.argmax(score))]
    # refine to a fraction of a frame (the parabola through the peak)
    i = lag
    if 1 <= i < len(ac) - 1:
        a0, a1, a2 = ac[i - 1], ac[i], ac[i + 1]
        den = a0 - 2 * a1 + a2
        lagf = i + (0.5 * (a0 - a2) / den if den else 0.0)
    else:
        lagf = float(i)
    period = float(lagf)                         # frames a beat
    # finer: the peaks at 2, 4 and 8 beats, each a beat's length times as many (a long lag pins it closer)
    for mult in (2, 4, 8):
        c = int(round(period * mult))
        w = max(2, int(period / 6))
        if c + w + 1 >= len(ac):
            break
        j = c - w + int(np.argmax(ac[c - w:c + w + 1]))
        if 1 <= j < len(ac) - 1:
            a0, a1, a2 = ac[j - 1], ac[j], ac[j + 1]
            den = a0 - 2 * a1 + a2
            jf = j + (0.5 * (a0 - a2) / den if den else 0.0)
        else:
            jf = float(j)
        period = jf / mult
    bpm = 60.0 * fps / period
    # the phase: the offset whose beat grid lands on the most onset
    offs = np.arange(int(period) + 1)
    def grid_score(o):
        pos = np.arange(o, n, period).astype(int)
        return onset[pos[pos < n]].sum()
    phase = max(offs, key=grid_score)
    # each beat on its own peak (within a sixth of a beat of the grid), then the grid fitted straight through the
    # strong ones (a slightly wrong tempo would drift), and each beat put on its peak again
    win = max(1, int(period / 6))

    def snap(grid):
        out = []
        for t in grid:
            c = int(round(t))
            a, b = max(0, c - win), min(n, c + win + 1)
            if b <= a:
                out.append((float(t), 0.0))
                continue
            j = a + int(np.argmax(onset[a:b]))
            if 1 <= j < n - 1:                          # its sub-frame peak
                y0, y1, y2 = onset[j - 1], onset[j], onset[j + 1]
                den = y0 - 2 * y1 + y2
                jf = j + (0.5 * (y0 - y2) / den if den else 0.0)
            else:
                jf = float(j)
            out.append((jf, float(onset[j])))
        return out

    grid = np.arange(float(phase), n, period)
    got = snap(grid)
    strong = [(k, t) for k, (t, v) in enumerate(got) if v > 0 and v >= 0.3 * max(1e-9, max(v2 for _t, v2 in got))]
    if len(strong) >= 8:
        ks = np.array([k for k, _t in strong], dtype=float)
        ts = np.array([t for _k, t in strong])
        slope, icpt = np.polyfit(ks, ts, 1)
        period = float(slope)
        grid = icpt + period * np.arange(int((n - icpt) / period) + 1)
        grid = grid[grid >= 0]
        got = snap(grid)
    # a beat with no onset under it keeps the grid's time. The windowed flux peaks while the hit is still in the
    # window's leading part, LEAD of a window before the hit itself (measured on a click track: 128 beats, 3.6 ms
    # apart at most from the clicks once taken off)
    peaks = [(t if v > 0 else g) for (t, v), g in zip(got, grid)]
    beats_ms = [max(0, int(round((b + LEAD * FRAME / HOP) * HOP * 1000.0 / sr))) for b in peaks]
    bpm = 60.0 * fps / period
    beats = [max(0, min(n - 1, int(round(b)))) for b in peaks]
    # the downbeat: the one of four whose beats carry the most onset
    down = max(range(4), key=lambda d: sum(onset[beats[j]] for j in range(d, len(beats), 4)))
    bars_ms = beats_ms[down::4]
    if not bars_ms or bars_ms[0] > 0:
        pass
    # each bar's loudness, ranked against the song's
    lv = []
    for j, start in enumerate(bars_ms):
        end = bars_ms[j + 1] if j + 1 < len(bars_ms) else length
        # the frames wholly inside the bar (a frame runs FRAME on from its start: the next bar's first hit
        # would be in the last ones), their mean level
        a = int(start * sr / 1000.0 / HOP)
        b = max(a + 1, int(end * sr / 1000.0 / HOP) - FRAME // HOP)
        seg = rms[a:min(b, len(rms))]
        lv.append(float(seg.mean()) if len(seg) else 0.0)
    lv = np.array(lv) if lv else np.zeros(1)
    q10, q90 = np.percentile(lv, 10), np.percentile(lv, 90)
    level = np.clip((lv - q10) / (q90 - q10 if q90 > q10 else 1.0), 0.0, 1.0)
    # sections: runs of bars of one kind, each at least two bars (a lone bar joins the run before it)
    kinds = ["quiet" if v < 0.35 else "loud" if v > 0.7 else "build" for v in level]
    sections = []
    for j, kd in enumerate(kinds):
        if sections and (sections[-1]["kind"] == kd or j - sections[-1]["first"] < 2):
            sections[-1]["last"] = j
            continue
        sections.append({"kind": kd, "first": j, "last": j})
    for j, s in enumerate(sections):
        s["start"] = bars_ms[s["first"]]
        s["end"] = bars_ms[s["last"] + 1] if s["last"] + 1 < len(bars_ms) else length
        prev = float(level[sections[j - 1]["first"]:sections[j - 1]["last"] + 1].mean()) if j else 0.0
        here = float(level[s["first"]:s["last"] + 1].mean())
        s["drop"] = bool(j and s["kind"] == "loud" and here - prev > 0.35)
    return {"bpm": round(bpm, 1), "beat_ms": int(round(period * HOP * 1000.0 / sr)), "beats": beats_ms,
            "bars": bars_ms, "level": [round(float(v), 3) for v in level], "sections": sections,
            "length_ms": length}


def _dim(c, f=0.18):
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))


def make(path, style=DEFAULT_STYLE, name="", slot=None, info=None):
    """A show (cab_shows' shape) made from the song in *path*, and what was measured (:func:`analyse`)."""
    info = info or analyse(path)
    label, palette, kinds = STYLES.get(style) or STYLES[DEFAULT_STYLE]
    beat = max(200, info["beat_ms"])
    length = info["length_ms"]
    bars = info["bars"]
    if not bars:
        raise AutoError("no beat was found in the song")
    # bars a step: as many as keep the longer lane within the runtime's room (the intro, the outro and the drops'
    # flashes take a few)
    drops = sum(1 for s in info["sections"] if s["drop"])
    room = CS.STEPS_MAX - 3 - drops
    per = max(1, int(math.ceil(len(bars) / float(room))))
    blades, speakers = [], []

    def add(lane, fx, ms, a, b, rate=0, blend=0):
        ms = int(ms)
        if ms <= 0:
            return
        if lane and ms < CS.STEP_MS_MIN and lane[-1]["ms"] + ms <= CS.STEP_MS_MAX:
            lane[-1]["ms"] += ms                         # too short to be a step: the one before takes it
            return
        lane.append({"fx": fx, "ms": max(CS.STEP_MS_MIN, ms), "a": a, "b": b,
                     "rate": max(0, min(CS.RATE_MAX, int(rate))), "blend": max(0, min(int(blend), ms))})

    intro = bars[0]
    if intro > 0:
        add(blades, "fade_in", intro, palette[0], "#000000")
        add(speakers, "fade_in", intro, palette[0], "#000000")
    for si, sec in enumerate(info["sections"]):
        colour = palette[si % len(palette)]
        nxt = palette[(si + 1) % len(palette)]
        pats = kinds[sec["kind"]]
        sb = [b for b in bars if sec["start"] <= b < sec["end"]]
        t0 = sec["start"]
        if sec["drop"]:                                  # a drop opens with a white flash, a beat long
            add(blades, "strobe", beat, "#ffffff", colour, beat / 8)
            t0 += beat
        groups = [sb[g:g + per] for g in range(0, len(sb), per)]
        for gi, grp in enumerate(groups):
            start = max(t0, grp[0])
            end = groups[gi + 1][0] if gi + 1 < len(groups) else sec["end"]
            fx, rate_beats = pats[gi % len(pats)]
            b = "#000000" if fx in ("strobe", "fill_up", "fill_down", "meter", "chase_up", "chase_down") else _dim(colour)
            a = colour if gi % 2 == 0 or fx in ("crossfade",) else (nxt if sec["kind"] == "loud" else colour)
            if fx == "crossfade":
                a, b = colour, nxt
            if fx == "meter":
                b = "#ffffff"
            add(blades, fx, end - start, a, b, rate_beats * beat if rate_beats else 0,
                blend=min(150, (end - start) // 4) if gi == 0 and si else 0)
        # the speakers: breathe with the beat in the section's colour; swap sides on a loud one
        if sec["kind"] == "loud":
            add(speakers, "alternate", sec["end"] - sec["start"], colour, _dim(colour, 0.1), beat)
        else:
            add(speakers, "pulse", sec["end"] - sec["start"], colour, _dim(colour, 0.05),
                beat / 2 if sec["kind"] == "build" else beat)
    # each lane to the song's end, its last bar or two fading out
    bar_ms = 4 * beat
    for lane in (blades, speakers):
        total = sum(s["ms"] for s in lane)
        if total > length and lane:
            lane[-1]["ms"] = max(CS.STEP_MS_MIN, lane[-1]["ms"] - (total - length))
            total = sum(s["ms"] for s in lane)
        tail = length - total
        if lane and lane[-1]["fx"] != "fade_out":
            take = min(lane[-1]["ms"] - CS.STEP_MS_MIN, 2 * bar_ms if lane[-1]["ms"] > 3 * bar_ms else bar_ms)
            if take > 0 and len(lane) < CS.STEPS_MAX:
                lane[-1]["ms"] -= take
                lane[-1]["blend"] = min(lane[-1]["blend"], lane[-1]["ms"])
                tail += take
        if tail > 0:
            add(lane, "fade_out", tail, lane[-1]["a"] if lane else palette[0], "#000000")
    show = CS.norm_show({"name": name or "From the song", "slot": slot, "loop": False,
                         "blades": blades[:CS.STEPS_MAX], "speakers": speakers[:CS.STEPS_MAX]})
    return show, info


def describe(info):
    """The measuring, in a line: "128 BPM, 9 sections (2 drops)"."""
    n = len(info["sections"])
    d = sum(1 for s in info["sections"] if s["drop"])
    return "%g BPM, %d section%s%s" % (info["bpm"], n, "" if n == 1 else "s",
                                       " (%d drop%s)" % (d, "" if d == 1 else "s") if d else "")
