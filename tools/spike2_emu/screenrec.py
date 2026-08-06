#!/usr/bin/env python3
"""screenrec.py - record the emulator window from the WINDOWS side and find
the frames a human complains about.

    py screenrec.py record [seconds] [out.mkv]     (default 90 s)
    py screenrec.py analyze out.mkv [outdir]

RUN ON WINDOWS. This is item 11's instrument of last resort, built because
every internal counter said the pipeline was healthy while David watched it
stutter: the only honest referee is the same signal his eyes get, which is
the composited desktop. ffmpeg's gdigrab BitBlts exactly that.

WHY A REGION GRAB AND NOT `-i title=...`: the emulator window is a WSLg RAIL
window owned by msrdc.exe. Grabbing it by title hands ffmpeg a window DC,
and a DWM-composited window's DC is not guaranteed to carry the live GL
content (the same reason shotwin.py checks PrintWindow's pixel content
rather than trusting the BOOL). The DESKTOP always has the real pixels, so:
find the window rect, in PHYSICAL pixels (per-monitor DPI aware, same opt-in
as shotwin.py), and grab that region of the desktop. The window must be
unoccluded while recording - which it is, because the whole point is that a
human is watching it.

WHAT ANALYZE REPORTS, and what each means:
  * freezedetect stretches >= 67 ms (two 30 fps frame periods): the picture
    stopped moving. In ATTRACT the background clip never holds a frame, so
    any freeze is a delivery gap; in a GAME a freeze can be legitimate (a
    static score screen), which is why the dump exists - look at the frames.
  * scene-cut times: clip transitions, for lining the freezes up with
    padvid.log's `serving` lines (the cuts ARE the serves, so the two
    streams of timestamps can be aligned without a shared clock).
  * a PNG dump of each freeze boundary +/- 1 frame, so the offending moment
    can be LOOKED at - tearing shows as a horizontal seam, a jump-back shows
    as the clip's first frame appearing mid-scene.

MJPEG, deliberately: intra-only (every frame stands alone, so a dumped frame
is exactly what was on screen, no inter-frame smearing of a tear), cheap to
encode (this machine is also running the emulator being measured - an x264
encode stealing a core would CAUSE the stutter it records), and q=4 keeps
seams sharp. ~8 MB/s at 30 fps; a 90 s capture is ~700 MB, on c:/tmp.
30 fps because the clips are 30 fps: every source frame is sampled once.
A 60 Hz PRESENTATION tear (monitor-side, below DWM) is invisible here -
if the recording is clean while the eye still sees tearing, that is where
to look next, and that distinction is this instrument's whole value.
"""
import ctypes
import os
import re
import subprocess
import sys
import time

OUT_DEFAULT = r"c:\tmp\spike2_item11\rec.mkv"
TITLE_SUB = "Stern Spike 2 emulator"


def find_window_rect():
    """(left, top, w, h) of the emulator window, physical pixels."""
    user32 = ctypes.windll.user32
    # Per-monitor v2, BEFORE any window query - an unaware process sees a
    # virtualized desktop on this 4K/150% display (see shotwin.py).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    rects = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if TITLE_SUB in buf.value:
            class RECT(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            # CLIENT area, not the window rect: a RAIL window's rect includes
            # the invisible resize border / drop shadow, which put the first
            # capture attempt at (-31,-20) and gdigrab refuses a region
            # outside the desktop. The client area is the game picture.
            r = RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            p = POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(p))
            rects.append((buf.value, p.x, p.y, r.r, r.b))
        return True

    user32.EnumWindows(cb, None)
    if not rects:
        return None
    title, l, t, w, h = rects[0]
    print("window client: %r at (%d,%d) %dx%d" % (title, l, t, w, h))
    # Clamp to the virtual desktop anyway - a window dragged half off the
    # screen should record its visible part rather than error out.
    SM_XVS, SM_YVS, SM_CXVS, SM_CYVS = 76, 77, 78, 79
    dl = user32.GetSystemMetrics(SM_XVS)
    dt = user32.GetSystemMetrics(SM_YVS)
    dw = user32.GetSystemMetrics(SM_CXVS)
    dh = user32.GetSystemMetrics(SM_CYVS)
    r_ = min(l + w, dl + dw)
    b_ = min(t + h, dt + dh)
    l = max(l, dl)
    t = max(t, dt)
    w, h = r_ - l, b_ - t
    if w <= 0 or h <= 0:
        return None
    return l, t, w - (w % 2), h - (h % 2)


def record(seconds, out):
    rect = find_window_rect()
    if not rect:
        print("no window with %r in its title - is the emulator up?" % TITLE_SUB)
        return 1
    l, t, w, h = rect
    os.makedirs(os.path.dirname(out), exist_ok=True)
    t0_wall = time.strftime("%H:%M:%S")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
           "-f", "gdigrab", "-framerate", "30",
           "-offset_x", str(l), "-offset_y", str(t),
           "-video_size", "%dx%d" % (w, h),
           "-i", "desktop",
           "-t", str(seconds),
           "-c:v", "mjpeg", "-q:v", "4", out]
    print("recording %d s starting at wall %s -> %s" % (seconds, t0_wall, out))
    rc = subprocess.call(cmd)
    print("recorder exited %d at wall %s" % (rc, time.strftime("%H:%M:%S")))
    print("REC_START_WALL=%s" % t0_wall)
    return rc


def analyze(path, outdir=None):
    outdir = outdir or os.path.splitext(path)[0] + "_frames"
    os.makedirs(outdir, exist_ok=True)
    # One pass, two filters: freezes >= 67 ms and scene cuts. freezedetect's
    # noise floor (-60dB) tolerates mjpeg grain; d=0.067 is two frame periods,
    # so a single repeated frame is NOT a freeze - the compositor sampling the
    # same 30 fps source frame twice is normal, twice-plus-one is not.
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path,
         "-vf", "freezedetect=n=-60dB:d=0.067,select='gt(scene,0.3)',metadata=print",
         "-f", "null", "-"],
        capture_output=True, text=True)
    txt = p.stderr + p.stdout
    freezes = []   # (start_s, end_s or None)
    for m in re.finditer(r"freeze_start: ([\d.]+)", txt):
        freezes.append([float(m.group(1)), None])
    for i, m in enumerate(re.finditer(r"freeze_end: ([\d.]+)", txt)):
        if i < len(freezes):
            freezes[i][1] = float(m.group(1))
    cuts = [float(m.group(1))
            for m in re.finditer(r"pts_time:([\d.]+)", txt)]
    print("== %d freezes >= 67 ms ==" % len(freezes))
    for s, e in freezes:
        print("  %.2f s -> %s  (%.0f ms)" %
              (s, "%.2f s" % e if e else "unresolved",
               ((e - s) * 1000) if e else -1))
    print("== %d scene cuts (align these with padvid.log 'serving') ==" % len(cuts))
    print("  " + "  ".join("%.2f" % c for c in cuts[:40]))
    # Dump each freeze boundary +/- 1 frame for eyeballing.
    for i, (s, e) in enumerate(freezes[:20]):
        for tag, at in (("pre", max(0.0, s - 0.034)), ("frz", s + 0.001),
                        ("post", (e + 0.034) if e else s + 0.5)):
            f = os.path.join(outdir, "freeze%02d_%s_%.2fs.png" % (i, tag, at))
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                            "-y", "-ss", "%.3f" % at, "-i", path,
                            "-frames:v", "1", f])
    print("frames dumped to %s" % outdir)
    return 0


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "record"
    if what == "record":
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        out = sys.argv[3] if len(sys.argv) > 3 else OUT_DEFAULT
        return record(secs, out)
    if what == "analyze":
        return analyze(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
