#!/usr/bin/env python3
"""swspintest.py - does a right-hold really RIP, and really stop? Offline.

Run on WINDOWS, with NO emulator up:

    py tools\\spike2_emu\\swspintest.py [switch_id] [hold_ms] [game]

swholdtest.py's trick, unchanged: a fake padsw block in WSL via PAD_SW_FILE,
the REAL Field window, synthesised <ButtonPress-3>/<ButtonRelease-3> at the
marker's own coordinates - so the hit test, the `ripping` bookkeeping,
SwitchDriver's queue and swspin.py are all the shipping code.

WHAT IT CANNOT SEE, stated so nobody reads more into a pass than is there: the
RIPPING ITSELF. The alternating level is the guest shim's write into the 0x11
scan reply, and there is no guest here; what this proves is that the flag the
shim keys on is SET by a right-press, HELD for the whole hold, and CLEARED by
the release. The shim's half is judged on a live run by its own `[swspin] rip
END` line and by PAD_SW_PEND, per the item's acceptance test.

THE THREE THINGS IT ACTUALLY CHECKS:
  1. RIP    - spin[] goes 1 on right-press, stays 1, then 0 on release.
  2. LANES  - a right-hold must NOT touch scr_held[] (a rip is not a hold; the
              merge staying quiet is WHY a rip can never strand a switch
              closed), and a LEFT-hold must not touch spin[].
  3. ORDER  - 10 fast right-clicks end with spin[]=0 and nothing still queued;
              the stuck-RIP failure is item 24's stuck-switch failure in a new
              coat, and it rides the same serialised queue to be immune.
"""
import os
import struct
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

#: The fake block. /var/tmp and not /tmp: /tmp is a tmpfs here and is wiped on
#: a WSL restart, which has bitten this rig before.
WSL_BLOCK = "/var/tmp/pad_swspintest"
WIN_BLOCK = padpath.to_win(WSL_BLOCK)

POLL_S = 0.004


def make_block():
    """A zeroed 4096-byte block with padsw's magic, made from inside WSL."""
    prog = (
        "import struct,sys;"
        "b=bytearray(4096);"
        "struct.pack_into('<I',b,0,0x53444150);"
        "open(%r,'wb').write(bytes(b))" % WSL_BLOCK)
    subprocess.run(["wsl.exe", "-e", "python3", "-c", prog], check=True)


def read_block():
    try:
        with open(WIN_BLOCK, "rb") as f:
            return f.read(4096)
    except OSError:
        return None


def spin(d, sw):
    """The rip flag - the one byte the shim keys the whole feature on."""
    import padsw
    return d[padsw.OFF_SPIN + sw] if d else None


def scr(d, sw):
    """The HOLD lane, which a rip must leave alone."""
    import padsw
    return d[padsw.OFF_SCR_HELD + sw] if d else None


def spin_gen(d):
    import padsw
    return struct.unpack_from("<I", d, padsw.OFF_SPIN_GEN)[0] if d else None


def wait_for(root, fn, sw, want, limit_s=15.0):
    """Pump Tk until `fn` of the block reads `want`. Elapsed ms, or None."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit_s:
        root.update()
        if fn(read_block(), sw) == want:
            return (time.monotonic() - t0) * 1000.0
        time.sleep(POLL_S)
    return None


def pump(root, fn, sw, secs):
    """Keep Tk alive for `secs`, sampling one array. Returns the values seen."""
    seen, t0 = [], time.monotonic()
    while time.monotonic() - t0 < secs:
        root.update()
        v = fn(read_block(), sw)
        if v is not None:
            seen.append(v)
        time.sleep(POLL_S)
    return seen


ARGV = [a for a in sys.argv[1:] if not a.startswith("--")]
SW = int(ARGV[0]) if ARGV else 47                       # LEFT SPINNER
HOLD_MS = int(ARGV[1]) if len(ARGV) > 1 else 2000
GAME = ARGV[2] if len(ARGV) > 2 else None


def main():
    os.environ["PAD_SW_FILE"] = WSL_BLOCK
    make_block()
    if read_block() is None:
        print("cannot read %s from Windows" % WIN_BLOCK)
        return 1

    # Arguments off the command line before playfield is imported - it reads
    # argv[1] as the GAME. Same trap swholdtest.py documents.
    sys.argv = [sys.argv[0]] + ([GAME] if GAME else [])
    import tkinter as tk
    import playfield

    root = tk.Tk()
    root.title("swspintest")
    view = playfield.Field(root)
    root.update()

    target = None
    for i, e in view.info.items():
        if e["kind"] == "switch" and e["d"]["id"] == SW:
            target = (i, e["d"]["name"])
            break
    if target is None:
        print("switch %d is not on this playfield" % SW)
        return 1
    item, name = target
    x0, y0, x1, y1 = view.cv.coords(item)
    # ON THE RING'S STROKE, not its centre. The ring is an UNFILLED oval and
    # Tk's find_overlapping treats a hollow oval as its outline band only, so
    # the exact centre of a bare switch ring hit-tests to NOTHING - measured
    # here, ring 47's own centre returned no marker at all. A mouse never
    # notices because a hand aims at the drawn circle; a synthesised event has
    # to aim there too. (swholdtest.py never hit this: its default target sits
    # under a FILLED coil marker, which is hittable everywhere.)
    x, y = int((x0 + x1) / 2), int(y0) + 1
    print("switch %d  %s  at canvas (%d,%d) on the ring" % (SW, name, x, y))

    # A RIGHT-click must land on the SWITCH to rip: on_rip only rips switch
    # markers, so if the coil marker wins the hit test here the right gesture
    # is a no-op by design and the test says so up front.
    class _Ev:
        pass
    probe = _Ev()
    probe.x, probe.y = x, y
    got = view._hit(probe)
    e = view.info[got]
    print("a press here lands on the %s marker: %s\n"
          % (e["kind"].upper(), e["d"].get("name")))
    if e["kind"] != "switch":
        print("pick a switch id whose marker wins its own hit test")
        return 1

    fail = []

    # ---- 1. RIP ------------------------------------------------------------
    g0 = spin_gen(read_block())
    view.cv.event_generate("<ButtonPress-3>", x=x, y=y)
    t_on = wait_for(root, spin, SW, 1)
    if t_on is None:
        print("RIP    FAIL: right-press never set the spin flag")
        fail.append("rip-start")
    else:
        print("RIP    right-press -> spin[%d]=1 in %6.1f ms" % (SW, t_on))
        seen = pump(root, spin, SW, HOLD_MS / 1000.0)
        held = all(v == 1 for v in seen)
        print("       ripped for %d ms: %d samples, %s"
              % (HOLD_MS, len(seen),
                 "all spinning" if held else "DROPPED OUT (%d off)"
                 % seen.count(0)))
        if not held:
            fail.append("rip-drop")
        view.cv.event_generate("<ButtonRelease-3>", x=x, y=y)
        t_off = wait_for(root, spin, SW, 0)
        if t_off is None:
            print("       FAIL: release never cleared the flag - a rip that "
                  "never ends")
            fail.append("rip-stop")
        else:
            print("       release -> spin[%d]=0 in %6.1f ms" % (SW, t_off))
    print("       spin_gen moved %s -> %s (a real write each way)"
          % (g0, spin_gen(read_block())))

    # ---- 2. LANES ----------------------------------------------------------
    # The rip must not have touched the HOLD lane, and a left-hold must not
    # touch the rip's. One byte each; a cross-write here is exactly the
    # two-writers clobber the block's three regions exist to prevent.
    print("")
    d = read_block()
    if scr(d, SW):
        print("LANES  FAIL: the rip wrote scr_held[%d] - a rip is not a hold"
              % SW)
        fail.append("lanes-scr")
    else:
        print("LANES  scr_held[%d] untouched by the whole rip" % SW)
    view.cv.event_generate("<ButtonPress-1>", x=x, y=y)
    wait_for(root, scr, SW, 1)
    view.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
    wait_for(root, scr, SW, 0)
    if spin(read_block(), SW):
        print("       FAIL: a left-hold set the spin flag")
        fail.append("lanes-spin")
    else:
        print("       spin[%d] untouched by a left hold-and-release" % SW)

    # ---- 3. ORDER ----------------------------------------------------------
    # Fast right-clicks; the flag must end 0 every time. Same argument as
    # swholdtest's ORDER: on one queue, stop-before-start cannot happen.
    print("")
    for _ in range(10):
        view.cv.event_generate("<ButtonPress-3>", x=x, y=y)
        view.cv.event_generate("<ButtonRelease-3>", x=x, y=y)
        root.update()
    t0 = time.monotonic()
    while not view.drv.q.empty() and time.monotonic() - t0 < 60.0:
        root.update()
        time.sleep(POLL_S)
    view.drv.q.join()
    drained = (time.monotonic() - t0) * 1000.0
    end = spin(read_block(), SW)
    if end == 0:
        print("ORDER  10 fast right-clicks -> not spinning, %d actions "
              "drained in %.0f ms" % (20, drained))
    else:
        print("ORDER  FAIL: STILL RIPPING after 10 fast right-clicks "
              "(spin=%s)" % end)
        fail.append("order-stuck")
    print("       driver still spinning: %s (want an empty set)"
          % view.drv.spinning)
    if view.drv.spinning:
        fail.append("order-spinning")

    root.destroy()
    print("\n%s" % ("FAILED: " + ", ".join(fail) if fail else "ALL PASS"))
    return 1 if fail else 0


sys.exit(main())
