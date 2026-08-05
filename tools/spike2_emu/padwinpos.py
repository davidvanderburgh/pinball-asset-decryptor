"""padwinpos.py - remember and restore the emulator windows' positions, from
the WINDOWS side, because the X side cannot win this fight.

THE X-SIDE RESTORE IS CORRECT AND STILL LOSES. padglhost creates its windows at
the remembered position with USPosition set before mapping - the textbook X11 -
and .pad_windows was seen holding a real moved position (941,930) while the
window still opened at the WSLg default. Under WSLg every X window is a RAIL
proxy: a real Windows window owned by msrdc, placed by the compositor's own
policy, and the compositor neither honours the client's position hint reliably
nor reliably delivers moves back to the X client (the same one-way mirror that
forced padglhost to poll eglQuerySurface for its own SIZE). So this script
stops arguing with X and manages the only coordinates that are real to the
user: the Windows desktop ones.

watch.sh starts it through interop beside the playfield window (PAD_WINPOS=0
to skip). It polls once a second; the first time each emulator window appears
it is MOVED to its saved spot (SWP_NOACTIVATE - no focus theft), after that
its position is RECORDED whenever it changes. State lives in
%USERPROFILE%\\.pad_windows_win.json, per machine, like playfield.py's own
(working) position memory. When every window it ever saw is gone it saves and
exits; it also gives up quietly if no emulator window appears at all.

The game window and the Controls window are matched by TITLE SUBSTRING because
msrdc decorates titles ("[WARN:COPY MODE] godzilla_pro - Stern Spike 2
emulator (Ubuntu)"), and tracked under fixed keys - positions are per-machine
state, not per-title.
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
#: Give up if no emulator window has appeared yet (the game takes ~20 s to its
#: first frame; 180 covers a cold card boot with slack).
NEVER_SEEN_S = 180
#: Polls with every once-seen window gone before concluding the run ended.
GONE_POLLS = 5

EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10


def single_instance():
    """One keeper at a time; two would fight over the state file."""
    kernel32.CreateMutexW(None, False, "Local\\pad_winpos_keeper")
    return kernel32.GetLastError() != 183          # ERROR_ALREADY_EXISTS


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
    """Reject positions off every monitor (76..79 = virtual screen metrics)."""
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
    if not single_instance():
        return 0
    st = load_state()
    restored = set()
    seen_any = 0.0
    gone = 0
    start = time.monotonic()
    dirty = False

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

        for key, hwnd in wins.items():
            if key not in restored:
                restored.add(key)
                pos = st.get(key)
                if pos and onscreen(pos[0], pos[1]):
                    user32.SetWindowPos(hwnd, None, int(pos[0]), int(pos[1]),
                                        0, 0,
                                        SWP_NOSIZE | SWP_NOZORDER
                                        | SWP_NOACTIVATE)
                    continue                # record from the NEXT poll on
            pos = get_pos(hwnd)
            if pos and onscreen(pos[0], pos[1]) and st.get(key) != pos:
                st[key] = pos
                dirty = True

        if dirty:
            save_state(st)                  # survive a SIGKILL'd teardown
            dirty = False
        time.sleep(POLL_S)

    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
