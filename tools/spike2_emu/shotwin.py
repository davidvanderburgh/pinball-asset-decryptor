"""shotwin.py - capture a WSLg window from the Windows side, by title.

    python tools\\spike2_emu\\shotwin.py "Godzilla" c:\\tmp\\spike2_emu_out\\win.png

A WSLg window is a real top-level Windows window (owned by msrdc.exe, not by
any Linux process), so it can be captured with the same PrintWindow technique
the repo's scripts/take_screenshots.py already uses. Three deliberate
differences from those scripts, each for a reason:

  * PER-MONITOR DPI AWARENESS IS OPTED IN. take_screenshots.py is deliberately
    DPI-unaware because that is what Tk wants, and on this 4K/150% display an
    unaware process sees a virtualized 2560x1440 desktop. For a pixel-accurate
    grab of someone else's window we want real physical pixels, so this asks
    for per-monitor v2 before touching any window.

  * NO SAME-PROCESS FILTER AND SUBSTRING TITLE MATCH. shot_write_complete.py's
    find_dialog() hard-filters to the calling process and demands an exact
    title; neither can work for a window owned by msrdc.exe.

  * THE PrintWindow RETURN VALUE IS CHECKED, and so is the pixel content. All
    three existing capture scripts discard the BOOL, which means a failed
    capture silently yields whatever garbage was in the fresh bitmap. An
    all-black result is reported as a FAILURE here, because "the window exists"
    and "the window is showing the game" are different claims - the same
    lesson shot.py already encodes for the PNG dumps.

  * NO BORDER CROP. The crop in take_screenshots.py is tuned to a standard Tk
    toplevel frame and would shave the wrong amount off anything else.
"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Per-monitor v2 (-4). Fall back to the older shcore call, then to nothing.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        pass

EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_windows(needle):
    """Every visible top-level window whose title contains `needle`."""
    hits = []
    needle = needle.lower()

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if needle in title.lower():
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            hits.append((hwnd, title, pid.value,
                         r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return hits


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def snap(hwnd, w, h, out):
    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    # 2 = PW_RENDERFULLCONTENT, needed for anything composited by DWM.
    ok = user32.PrintWindow(hwnd, memdc, 2)

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h          # negative = top-down
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)

    px = buf.raw
    lit = sum(1 for i in range(0, len(px), 4 * 97)      # sample, don't scan 4 MB
              if px[i] or px[i + 1] or px[i + 2])
    sampled = len(range(0, len(px), 4 * 97))

    from PIL import Image
    Image.frombuffer("RGB", (w, h), px, "raw", "BGRX", 0, 1).save(out)
    return ok, got, lit, sampled


if __name__ == "__main__":
    needle = sys.argv[1] if len(sys.argv) > 1 else "Godzilla"
    # Default OUTSIDE the tree: this directory is version controlled now, and a
    # capture tool whose default is to drop a PNG into it is a tool that fills
    # your working copy with untracked screenshots.
    out = sys.argv[2] if len(sys.argv) > 2 else r"c:\tmp\spike2_emu_out\win.png"
    found = find_windows(needle)
    if not found:
        print("NO WINDOW matching %r. Visible titled windows:" % needle)
        for hwnd, t, pid, w, h in find_windows(""):
            print("   %-10s pid=%-6s %5dx%-5d %s" % (hwnd, pid, w, h, t))
        sys.exit(2)
    for hwnd, title, pid, w, h in found:
        print("FOUND hwnd=%s pid=%s %dx%d %r" % (hwnd, pid, w, h, title))
    hwnd, title, pid, w, h = found[0]
    ok, got, lit, sampled = snap(hwnd, w, h, out)
    print("PrintWindow returned %s, GetDIBits scanlines %s" % (ok, got))
    print("non-black sampled pixels: %d / %d (%.1f%%)"
          % (lit, sampled, 100.0 * lit / max(sampled, 1)))
    print("wrote %s" % out)
    if not ok:
        print("FAIL: PrintWindow returned 0 - the bitmap is meaningless")
        sys.exit(3)
    if lit == 0:
        print("FAIL: entirely black - the window exists but is showing nothing")
        sys.exit(4)
    print("OK")
