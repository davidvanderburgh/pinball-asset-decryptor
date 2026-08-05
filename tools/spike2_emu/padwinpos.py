"""padwinpos.py - RECORD the emulator windows' desktop positions. Never move them.

THIS SCRIPT USED TO RESTORE POSITIONS WITH SetWindowPos AND THAT WAS A TRAP,
kept here in writing because the failure is invisible to the obvious test. A
programmatic SetWindowPos on a WSLg window moves the real Windows window but
happens behind the compositor's back: WSLg windows are RAIL proxies, user
drags are reported back to Weston but programmatic moves are NOT, so the X
side and the Windows side end up disagreeing about where the window is - and
from then on RAIL reasserts the stale server position against every user
drag. The windows LOOK correctly restored (read-back said (900,500), the
screenshot agreed) and are in fact STUCK: David could not drag either
emulator window until the keeper was killed and both windows were
minimize/restored to re-sync the two models. Proof of the divergence, from
the live session: X's ~/.pad_windows said `legend 387 79` while Windows'
GetWindowRect said (900,500) for the same window.

The restore therefore has to be done by the COMPOSITOR - move the window
through X (a delayed XMoveWindow from padglhost, well after mapping), so both
sides of the RAIL mirror agree. That work is REMAINING item 5 in the handoff.

What is left here is the harmless half: a passive recorder of where the
emulator windows sit, in Windows desktop coordinates, useful for diagnosing
the X<->Windows coordinate mapping. Nothing launches it automatically.
"""
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Physical pixels, consistent across runs - same opt-in as shotwin.py.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

STATE = os.path.join(os.path.expanduser("~"), ".pad_windows_win.json")

#: key -> title substring. "Controls" must be checked FIRST: both titles
#: contain "Spike 2 emulator".
TRACK = (
    ("controls", "Controls - Spike 2 emulator"),
    ("game", "- Stern Spike 2 emulator"),
)

POLL_S = 1.0
#: Give up if no emulator window has appeared yet.
NEVER_SEEN_S = 180
#: Polls with every once-seen window gone before concluding the run ended.
GONE_POLLS = 5

EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_tracked():
    """{key: hwnd} for every tracked window currently on screen."""
    out = {}

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        for key, needle in TRACK:
            if key not in out and needle in title:
                out[key] = hwnd
                break
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def get_pos(hwnd):
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return [r.left, r.top]


def onscreen(x, y):
    """Reject positions off every monitor (76..79 = virtual screen metrics);
    also rejects the -32000 marker Windows parks minimized windows at."""
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return vx - 50 <= x <= vx + vw - 100 and vy - 20 <= y <= vy + vh - 80


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE, "w") as f:
            json.dump(st, f, indent=1)
    except Exception:
        pass


def main():
    st = load_state()
    seen_any = 0.0
    gone = 0
    start = time.monotonic()

    while True:
        wins = find_tracked()
        now = time.monotonic()
        if wins:
            seen_any = now
            gone = 0
        elif seen_any:
            gone += 1
            if gone >= GONE_POLLS:
                break
        elif now - start > NEVER_SEEN_S:
            return 0                        # no emulator ever came up

        dirty = False
        for key, hwnd in wins.items():
            pos = get_pos(hwnd)
            if pos and onscreen(pos[0], pos[1]) and st.get(key) != pos:
                st[key] = pos
                dirty = True
        if dirty:
            save_state(st)                  # survive a SIGKILL'd teardown
        time.sleep(POLL_S)

    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
