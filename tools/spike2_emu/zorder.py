"""zorder.py - read the REAL z-order of the emulator's windows (item 22).

    py tools\\spike2_emu\\zorder.py                 # one reading, now
    py tools\\spike2_emu\\zorder.py --watch 120     # print every CHANGE for 120 s
    py tools\\spike2_emu\\zorder.py --all           # every visible window, for triage

Item 22's acceptance says the order must be "verified by reading the real
z-order, not by eye", and nothing in this rig could read it. This does.

A run opens three top-level Windows windows - the game and Controls windows are
X11 out of padglhost.c, RAIL-proxied by msrdc.exe, and the virtual playfield is
an ordinary Windows Tk process - and the app is a fourth. All four are matched
by title, the same way shotwin.py finds them.

Three deliberate choices, each because the obvious version would lie:

  * THE WALK IS GetTopWindow + GW_HWNDNEXT, NOT EnumWindows. Item 22's text
    says "EnumWindows returns them IN z-order", and in practice it does, but
    that is NOT what its documentation promises - it promises an enumeration.
    GetWindow(GW_HWNDNEXT) is documented as the z-order walk, so that is the
    reading, and EnumWindows is run alongside as a cross-check. They are
    compared on every reading and a disagreement is printed, because an
    instrument that quietly picks one of two orderings is the thing this rig
    keeps getting bitten by.

  * CLOAKED WINDOWS ARE DROPPED. IsWindowVisible is true for a pile of shell
    and UWP windows that DWM is hiding, and counting them makes the ranks
    jump around between readings for reasons that have nothing to do with the
    emulator. DWMWA_CLOAKED is the only way to see that from outside.

  * WS_EX_TOPMOST IS REPORTED. A topmost window sits above every non-topmost
    one no matter what anybody raises, so if msrdc ever marks one of its
    proxies topmost, "raise the others" cannot be the fix and the reading has
    to say so rather than leave the next pass guessing.

Reading only. It never moves, raises or activates a window: SetWindowPos on an
emulator window is a standing non-negotiable in plans/TODO.md - it froze
David's windows once - and an instrument that could cause the fault it measures
is not an instrument.

Exit codes: 0 the emulator windows are all above the app (or there is no app to
compare against), 2 no emulator window found at all, 4 at least one emulator
window is BELOW the app - the item 22 fault, seen.
"""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:                                     # pre-Vista, or a stripped image
    dwmapi = None

GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

# Title -> role. Substring match, lowercased, first hit wins, so the order
# matters: "Controls - Spike 2 emulator" also contains "spike 2 emulator".
ROLES = (
    ("controls - spike 2 emulator", "CONTROLS"),
    ("- virtual playfield", "PLAYFIELD"),
    ("] - stern spike 2 emulator", "GAME2"),   # item 44: "<game> [display N]"
    ("- stern spike 2 emulator", "GAME"),
    ("pinball asset decryptor", "APP"),
)
EMU_ROLES = ("GAME", "GAME2", "CONTROLS", "PLAYFIELD")


def role_of(title):
    t = title.lower()
    for needle, role in ROLES:
        if needle in t:
            return role
    return None


def _cloaked(hwnd):
    """True if DWM is hiding this window. Absent DWM, nothing is cloaked."""
    if dwmapi is None:
        return False
    val = ctypes.c_int(0)
    try:
        hr = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                          ctypes.byref(val), ctypes.sizeof(val))
    except Exception:                               # noqa: BLE001
        return False
    return hr == 0 and val.value != 0


def _exe(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(h)
    return "?"


def _describe(hwnd):
    """(title, pid, exe, w, h, topmost) for a window we have decided to keep."""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    return (buf.value, pid.value, _exe(pid.value),
            r.right - r.left, r.bottom - r.top, bool(ex & WS_EX_TOPMOST))


def _keep(hwnd, want_all):
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindowTextLengthW(hwnd) <= 0:
        return False
    if _cloaked(hwnd):
        return False
    if want_all:
        return True
    return True


def walk_zorder():
    """Every visible, titled, uncloaked top-level window, TOPMOST FIRST.

    GetTopWindow(NULL) is the top of the root's child list and GW_HWNDNEXT
    walks down it, which is the documented z-order. Bounded so a corrupt list
    cannot spin forever.
    """
    out = []
    h = user32.GetTopWindow(None)
    seen = 0
    while h and seen < 20000:
        seen += 1
        if _keep(h, False):
            out.append(h)
        h = user32.GetWindow(h, GW_HWNDNEXT)
    return out


def enum_order():
    """The same set, in EnumWindows order - the cross-check, not the reading."""
    out = []

    def cb(hwnd, _):
        if _keep(hwnd, False):
            out.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def reading():
    """(rows, disagrees) - rows are (rank, hwnd, role, title, pid, exe, w, h, top, fg).

    `fg` marks GetForegroundWindow, which is INDEPENDENT ground truth for the
    top of the z-order and is how this tool was validated: the foreground
    window must be the highest-ranked non-topmost row, and if it ever is not,
    the walk is reading something other than the z-order.
    """
    z = walk_zorder()
    e = enum_order()
    disagrees = z != e
    fg = user32.GetForegroundWindow()
    rows = []
    for rank, hwnd in enumerate(z):
        title, pid, exe, w, h, top = _describe(hwnd)
        role = role_of(title)
        rows.append((rank, hwnd, role, title, pid, exe, w, h, top, hwnd == fg))
    return rows, disagrees


def baseline_load(path):
    """The hwnds that existed BEFORE the run, or None if there is no baseline.

    This exists because a WSLg RAIL window can OUTLIVE its X client. Measured
    2026-08-10: a run torn down at 13:35 left `star_wars_le - Stern Spike 2
    emulator (Ubuntu)` and its Controls window on the desktop, still visible,
    still rendering their frames, with alive.sh reporting 0 and no padglhost
    process anywhere - and they ignore WM_CLOSE, because there is no X client
    left to receive WM_DELETE_WINDOW. A reading taken during the NEXT run
    therefore sees two Controls windows with identical titles, and scoring the
    wrong one silently answers a different question than the one asked.
    """
    try:
        with open(path) as fh:
            return set(int(line) for line in fh if line.strip())
    except OSError:
        return None


def baseline_write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write("%d\n" % r[1])


def verdict(rows, base=None):
    """(code, text). The item 22 question: is any emulator window below the app?

    With a baseline, only windows that did NOT exist before it are scored - a
    stranded window from a previous run is not this run's answer.
    """
    if base is not None:
        rows = [r for r in rows if r[1] not in base or r[2] == "APP"]
    emu = [r for r in rows if r[2] in EMU_ROLES]
    app = [r for r in rows if r[2] == "APP"]
    if not emu:
        return 2, "no emulator window found"
    if not app:
        return 0, ("%d emulator window(s), no app window to compare against"
                   % len(emu))
    app_rank = app[0][0]
    below = [r for r in emu if r[0] > app_rank]
    if below:
        return 4, ("BELOW THE APP: %s (app is rank %d)"
                   % (", ".join("%s rank %d" % (r[2], r[0]) for r in below),
                      app_rank))
    return 0, ("all %d emulator window(s) above the app (app rank %d)"
               % (len(emu), app_rank))


def fmt(rows, want_all, base=None):
    lines = []
    for rank, hwnd, role, title, pid, exe, w, h, top, fg in rows:
        if not want_all and role is None:
            continue
        if base is None:
            age = ""
        elif hwnd in base:
            age = "old "
        else:
            age = "NEW "
        lines.append("  %s rank %-4d %-9s %s%-14s pid=%-6d %5dx%-5d %s%s"
                     % ("FG" if fg else "  ", rank, role or "-", age, exe, pid,
                        w, h, "TOPMOST " if top else "", title))
    return lines


def fg_check(rows):
    """The instrument's own self-test, printed on every reading.

    GetForegroundWindow is decided by Windows, not by this walk, so it is a
    free labelled example on every single reading: it must be the top
    non-TOPMOST row. Printed rather than asserted - a legitimately odd desktop
    (a full-screen topmost overlay) should not make the tool refuse to report.
    """
    fg = [r for r in rows if r[9]]
    if not fg:
        return "self-test: no foreground window (nothing to check against)"
    plain = [r for r in rows if not r[8]]
    if not plain:
        return "self-test: every window is TOPMOST (nothing to check against)"
    if fg[0][0] == plain[0][0]:
        return "self-test OK: the foreground window is the top non-TOPMOST row"
    return ("self-test FAILED: foreground is rank %d but the top non-TOPMOST "
            "row is rank %d - do not trust this reading"
            % (fg[0][0], plain[0][0]))


def once(want_all, base=None):
    rows, disagrees = reading()
    code, text = verdict(rows, base)
    print(time.strftime("%H:%M:%S"), "z-order, topmost first:")
    for line in fmt(rows, want_all, base):
        print(line)
    if disagrees:
        print("  NOTE: EnumWindows order != GetWindow(GW_HWNDNEXT) order - "
              "the reading above is the documented walk")
    print("  %s" % fg_check(rows))
    print("  VERDICT: %s" % text)
    return code


def watch(seconds, want_all, base=None):
    """Print a reading whenever the emulator/app ordering CHANGES.

    The interesting moment is when the game window APPEARS, tens of seconds
    into a boot, and a reading taken afterwards cannot show what the order was
    then. Keyed on the roles and their ranks only, so an unrelated window
    opening somewhere does not spam the log.
    """
    print("watching for %d s - a line per change" % seconds)
    end = time.time() + seconds
    last = None
    code = 2
    while time.time() < end:
        rows, disagrees = reading()
        key = tuple((r[2], r[0], r[1]) for r in rows if r[2])
        if key != last:
            last = key
            code = once(want_all, base)
            print("")
        time.sleep(0.25)
    return code


if __name__ == "__main__":
    args = sys.argv[1:]
    show_all = "--all" in args
    base = None
    if "--baseline" in args:
        i = args.index("--baseline")
        path = args[i + 1]
        base = baseline_load(path)
        if base is None:
            rows, _ = reading()
            baseline_write(path, rows)
            print("baseline written: %d window(s) already on the desktop -> %s"
                  % (len(rows), path))
            print("anything not in it is marked NEW, and only NEW emulator "
                  "windows are scored")
            sys.exit(0)
    if "--watch" in args:
        i = args.index("--watch")
        secs = int(args[i + 1]) if len(args) > i + 1 else 60
        sys.exit(watch(secs, show_all, base))
    sys.exit(once(show_all, base))
