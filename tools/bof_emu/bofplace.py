#!/usr/bin/env python3
"""bofplace.py - keep a BoF game's window at one spot of the WSLg desktop
(PAD-1308).

    bofplace.py --display :0 --mark BOFEMU_LOG_DIR=<rig> --pidfile <game.pid> --at X,Y

A cabinet split (padsplit.py, on Windows) shows each display of the game's
one window on its own monitor through DWM thumbnails, and the window itself
must be out of sight without being minimised (that stops its picture).
Windows can't move, hide or cloak a WSLg window - msrdc refuses every one of
them and WSLg puts it back - and WSLg never lets a window sit wholly off the
desktop. So it sits UNDER one of padsplit's part windows, which are topmost
and fill their monitors; padsplit works out where (padsplit.cover_spot) and
the run passes it here as PAD_BOF_PLACE.

Under WSLg, X root coordinates are Windows' physical desktop pixels, a
position asked for at create time is ignored, and a later XMoveWindow lands
the client near, not at, the aim (padglhost.c says the same of its windows).
So: find the game's window by the rig's mark, move it, read it back with
XTranslateCoordinates and correct, and look again twice a second for as long
as the game runs - WSLg puts a window back at the top-left now and then.
"""
import argparse
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ap_emu"))

import gamekeys    # noqa: E402

#: how far off the aim still counts as there
SLACK = 2


def _alive(pidfile):
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip() or 0)
        return pid > 0 and os.path.exists("/proc/%d" % pid)
    except (OSError, ValueError):
        return False


class Placer:
    def __init__(self, name):
        self.d = gamekeys.Display(name)
        x = self.d.x
        x.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
        x.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong)]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]

    def game_window(self, mark):
        """The marked process's top-level client window (the first one found
        under the root that carries its pid)."""
        d = self.d
        stack = list(d._children(d.root))
        while stack:
            w = stack.pop(0)
            pid = d._pid(w)
            if pid and gamekeys.marked(pid, mark):
                return w
            stack.extend(d._children(w))
        return 0

    def where(self, w):
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        self.d.x.XTranslateCoordinates(self.d.dpy, w, self.d.root, 0, 0,
                                       ctypes.byref(x), ctypes.byref(y), ctypes.byref(child))
        return x.value, y.value

    def move(self, w, x, y):
        self.d.x.XMoveWindow(self.d.dpy, w, x, y)
        self.d.x.XSync(self.d.dpy, 0)


def place(p, w, aim, log, tries=6):
    """Move w's client to aim, correcting by what it read back; True once there."""
    ax, ay = aim
    tx, ty = aim
    for _ in range(tries):
        gx, gy = p.where(w)
        if abs(gx - ax) <= SLACK and abs(gy - ay) <= SLACK:
            return True
        p.move(w, tx, ty)
        time.sleep(0.25)
        nx, ny = p.where(w)
        log("moved to %d,%d: the window is at %d,%d" % (tx, ty, nx, ny))
        tx, ty = tx + (ax - nx), ty + (ay - ny)
    gx, gy = p.where(w)
    return abs(gx - ax) <= SLACK and abs(gy - ay) <= SLACK


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--display", required=True)
    ap.add_argument("--mark", required=True)
    ap.add_argument("--pidfile", required=True)
    ap.add_argument("--at", required=True, help="X,Y: where the window's top-left goes")
    ap.add_argument("--wait", type=float, default=120.0,
                    help="seconds to wait for the window to open")
    a = ap.parse_args(argv)
    aim = tuple(int(v) for v in a.at.split(","))

    def log(text):
        print("%s bofplace: %s" % (time.strftime("%H:%M:%S"), text), flush=True)

    p = Placer(a.display)
    t0 = time.time()
    w = 0
    while not w:
        if time.time() - t0 > a.wait or (time.time() - t0 > 5 and not _alive(a.pidfile)):
            log("the game's window never opened")
            return 1
        w = p.game_window(a.mark)
        if not w:
            time.sleep(0.2)
    log("the game's window %#x is at %d,%d; aim %d,%d" % ((w,) + p.where(w) + aim))
    time.sleep(0.5)                  # let the compositor's own placement settle first
    log("placed" if place(p, w, aim, log) else "could not place it")
    resets = 0
    while _alive(a.pidfile):
        time.sleep(0.5)
        gx, gy = p.where(w)
        if abs(gx - aim[0]) > SLACK or abs(gy - aim[1]) > SLACK:
            resets += 1
            log("the window was put back at %d,%d (%d): placing it again" % (gx, gy, resets))
            place(p, w, aim, log)
    log("the game ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
