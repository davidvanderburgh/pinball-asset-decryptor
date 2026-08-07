#!/usr/bin/env python3
"""swholdtest.py - does a playfield press-and-hold really hold? Offline.

Run on WINDOWS, with NO emulator up:

    py tools\\spike2_emu\\swholdtest.py [switch_id] [hold_ms] [game]
    py tools\\spike2_emu\\swholdtest.py --pulse     # the negative control

WHY THIS CAN RUN WITHOUT A GAME, which is the whole reason it is worth having:
padsw.py reads `PAD_SW_FILE` and says in terms that it "points the helpers at a
block that is not a running game's, which is the only way to check any of this
without one". So this builds a fake padsw block in WSL, points the helpers at
it, drives the REAL playfield handlers, and reads back what they wrote. A run
costs minutes and cannot be parallelised; this costs seconds and can be run
after any edit.

WHAT IT DRIVES, and it matters that it is not a reimplementation: it constructs
the actual `Field` window and synthesises `<ButtonPress-1>` / `<ButtonRelease-1>`
on its canvas at the marker's own coordinates, so the hit test, the `holding`
bookkeeping and SwitchDriver's queue are all the shipping code. Tk's
`event_generate` needs no OS input injection, which matters because SendInput
into this rig's windows is UIPI-blocked (REMAINING items 7 and 12).

WHAT IT CANNOT SEE, stated so nobody reads more into a pass than is there:
* `mrg[]` NEVER MOVES HERE. The merge is the guest shim's write, and there is no
  guest. This watches `scr_held[]`, which is what this window is responsible
  for; the scr->mrg merge is item 7's and item 17's, already proven on hardware.
* it does not prove the MOUSE works, only that a press and a release do.
  David's hands are the final oracle for a feel item.

THE THREE THINGS IT ACTUALLY CHECKS:
  1. HOLD   - scr_held goes 1 on press and stays 1 for the whole hold, then 0.
              A pulse would drop back on its own and this catches that.
  2. TAP    - a fast click still delivers a closure. The press and release are
              two ~200 ms interop spawns, so a tap must not collapse to nothing.
  3. ORDER  - the stuck-switch failure. Fast clicks repeated; the switch must be
              OPEN at the end every time. On two threads instead of one queue,
              a release can overtake its press and latch the switch on forever.
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

#: The fake block. /var/tmp and not /tmp: /tmp is a tmpfs here and is wiped on a
#: WSL restart, which has bitten this rig before.
WSL_BLOCK = "/var/tmp/pad_swholdtest"
WIN_BLOCK = padpath.to_win(WSL_BLOCK)

#: `--live` runs the SAME test against a RUNNING GAME's block instead of a fake
#: one, which is the only way to watch `mrg[]` - the array the game is actually
#: handed. Offline, mrg never moves, because the merge is the guest shim's write
#: and there is no guest; the offline pass therefore proves this window's half
#: and nothing about the guest's. Start a run first and check alive.sh after.
LIVE = "--live" in sys.argv
if LIVE:
    WSL_BLOCK = padpath.wsl_root() + "/dump/padsw"
    WIN_BLOCK = os.path.join(padpath.dump(), "padsw")

#: How often we look at the block. A reopen+read over \\wsl.localhost costs
#: ~3.4 ms (measured, see playfield.py), so this is about as fast as the far
#: side of the boundary can be sampled - and sampling on the FAR side is the
#: point: everything inside WSL can read perfect while the truth is elsewhere.
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


def scr(d, sw):
    """This window's own half of the block - what we are responsible for."""
    import padsw
    return d[padsw.OFF_SCR_HELD + sw] if d else None


def mrg(d, sw):
    """What the GAME IS HANDED. Only moves with a guest running (--live)."""
    import padsw
    return d[padsw.OFF_MRG + sw] if d else None


def scr_gen(d):
    import padsw
    return struct.unpack_from("<I", d, padsw.OFF_SCR_GEN)[0] if d else None


#: WHICH ARRAY DECIDES A PASS. Live, it is `mrg[]` - the item's own acceptance
#: test names it, and it is the only one that says the GAME saw the hold.
#: Offline there is no guest to write mrg, so the answer is this window's own
#: `scr_held[]` and the report says so rather than quietly grading itself.
def oracle(d, sw):
    return mrg(d, sw) if LIVE else scr(d, sw)


ORACLE = "mrg" if LIVE else "scr_held"


def wait_for(root, sw, want, limit_s=15.0):
    """Pump Tk until the oracle array reads `want`. Elapsed ms, or None."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit_s:
        root.update()
        if oracle(read_block(), sw) == want:
            return (time.monotonic() - t0) * 1000.0
        time.sleep(POLL_S)
    return None


def pump(root, secs):
    """Keep Tk alive for `secs`, sampling the block. Returns the values seen."""
    seen, t0 = [], time.monotonic()
    while time.monotonic() - t0 < secs:
        root.update()
        v = oracle(read_block(), SW)
        if v is not None:
            seen.append(v)
        time.sleep(POLL_S)
    return seen


#: Flags out of the way before the positional arguments are read, so
#: `swholdtest.py --pulse` does not try to parse "--pulse" as a switch id.
PULSE = "--pulse" in sys.argv
ARGV = [a for a in sys.argv[1:] if not a.startswith("--")]
SW = int(ARGV[0]) if ARGV else 53                       # RIGHT SCOOP
HOLD_MS = int(ARGV[1]) if len(ARGV) > 1 else 2000
GAME = ARGV[2] if len(ARGV) > 2 else None


def main():
    if LIVE:
        # The rig never sets PAD_SW_FILE, and the helpers default to the real
        # block - so live means leaving it UNSET rather than pointing at it.
        os.environ.pop("PAD_SW_FILE", None)
        print("LIVE: the running game's own block, oracle is mrg[]\n")
    else:
        os.environ["PAD_SW_FILE"] = WSL_BLOCK
        make_block()
    if read_block() is None:
        print("cannot read %s from Windows%s"
              % (WIN_BLOCK, " - is a run up?" if LIVE else ""))
        return 1

    # playfield.py takes the GAME as argv[1] and works it out from gameinfo
    # otherwise, so our own arguments have to be off the command line before it
    # is imported - `swholdtest.py 53` was read as a title called "53" and the
    # window came up with no artwork.
    sys.argv = [sys.argv[0]] + ([GAME] if GAME else [])
    import tkinter as tk
    import playfield

    root = tk.Tk()
    root.title("swholdtest")
    view = playfield.Field(root)
    root.update()

    # The marker's own canvas coordinates, found the way a mouse would find it.
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
    x, y = int((x0 + x1) / 2), int((y0 + y1) / 2)
    print("switch %d  %s  at canvas (%d,%d)" % (SW, name, x, y))

    # SAY WHICH MARKER A MOUSE WOULD ACTUALLY GET, because it is not always the
    # switch: the coil is drawn over it, and at RIGHT SCOOP the coil wins. That
    # is the finding this whole item turned on, so the test states it every run
    # rather than leaving the next reader to assume the switch was pressed.
    class _Ev:
        pass
    probe = _Ev()
    probe.x, probe.y = x, y
    got = view._hit(probe)
    e = view.info[got]
    print("a press here lands on the %s marker: %s\n"
          % (e["kind"].upper(), e["d"].get("name")))

    fail = []

    # ---- 0. THE NEGATIVE CONTROL ------------------------------------------
    # `--pulse` drives the OLD gesture - coilact.py's fixed 120 ms pulse - and
    # runs the same HOLD check against it. It MUST FAIL. An instrument that has
    # never been shown the defect it is looking for is not evidence, and this
    # rig has three metrics on record that ranked a known-bad capture as clean.
    if PULSE:
        print("NEGATIVE CONTROL: the pre-item-24 gesture, which must FAIL\n")
        view.drv.run_script("coilact.py", name)
        t_close = wait_for(root, SW, 1)
        if t_close is None:
            print("CTRL   the pulse never closed the switch at all")
            return 1
        seen = pump(root, HOLD_MS / 1000.0)
        held = all(v == 1 for v in seen)
        print("CTRL   closed in %.1f ms, then %d of %d samples read OPEN"
              % (t_close, seen.count(0), len(seen)))
        print("\n%s" % ("CONTROL FAILED AS IT MUST - the test can see a pulse"
                        if not held else
                        "CONTROL PASSED, WHICH IS WRONG - the test is blind"))
        root.destroy()
        return 0 if not held else 1

    # ---- 1. HOLD ---------------------------------------------------------
    g0 = scr_gen(read_block())
    view.cv.event_generate("<ButtonPress-1>", x=x, y=y)
    t_close = wait_for(root, SW, 1)
    if t_close is None:
        print("HOLD   FAIL: press never closed the switch")
        fail.append("hold-press")
    else:
        print("HOLD   press -> %s closed in %6.1f ms" % (ORACLE, t_close))
        seen = pump(root, HOLD_MS / 1000.0)
        held = all(v == 1 for v in seen)
        print("       held for %d ms: %d samples of %s, %s"
              % (HOLD_MS, len(seen), ORACLE,
                 "all closed" if held else "DROPPED OUT (%d open)"
                 % seen.count(0)))
        if not held:
            fail.append("hold-drop")
        view.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
        t_open = wait_for(root, SW, 0)
        if t_open is None:
            print("       FAIL: release never opened the switch")
            fail.append("hold-release")
        else:
            print("       release -> open in %6.1f ms" % t_open)
    print("       scr_gen moved %s -> %s (a real edge each way)"
          % (g0, scr_gen(read_block())))

    # ---- 2. TAP ----------------------------------------------------------
    # A click with no dwell at all: the release is queued while the press is
    # still spawning. It must still produce a closure the guest could see.
    print("")
    for trial in range(3):
        view.cv.event_generate("<ButtonPress-1>", x=x, y=y)
        view.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
        t0, closed_ms, saw = time.monotonic(), None, False
        while time.monotonic() - t0 < 15.0:
            root.update()
            v = oracle(read_block(), SW)
            if v == 1 and not saw:
                saw, t_on = True, time.monotonic()
            elif v == 0 and saw:
                closed_ms = (time.monotonic() - t_on) * 1000.0
                break
            time.sleep(POLL_S)
        if not saw:
            print("TAP %d  FAIL: no closure at all" % trial)
            fail.append("tap-lost")
        else:
            print("TAP %d  closure %6.1f ms wide" % (trial, closed_ms or -1))

    # ---- 3. ORDER --------------------------------------------------------
    # The stuck-switch check. Ten clicks as fast as Tk will deliver them; the
    # switch must end OPEN. This is the one that fails if press and release ever
    # run on separate threads instead of one queue.
    #
    # WAIT FOR THE QUEUE, NOT FOR A VALUE. Polling for 0 passes INSTANTLY and
    # means nothing - the switch is still 0 because the first press has not
    # spawned yet, and this test reported a cheerful "drained in 3 ms" over
    # twenty pending actions. A metric that can be satisfied before the work
    # starts is not measuring the work.
    print("")
    for _ in range(10):
        view.cv.event_generate("<ButtonPress-1>", x=x, y=y)
        view.cv.event_generate("<ButtonRelease-1>", x=x, y=y)
        root.update()
    t0 = time.monotonic()
    while not view.drv.q.empty() and time.monotonic() - t0 < 60.0:
        root.update()
        time.sleep(POLL_S)
    view.drv.q.join()
    drained = (time.monotonic() - t0) * 1000.0
    end = oracle(read_block(), SW)
    if end == 0:
        print("ORDER  10 fast clicks -> open, %d actions drained in %.0f ms"
              % (20, drained))
    else:
        print("ORDER  FAIL: STUCK CLOSED after 10 fast clicks (scr_held=%s)"
              % end)
        fail.append("order-stuck")
    print("       driver still holds: %s (want an empty set)" % view.drv.held)
    if view.drv.held:
        fail.append("order-held")

    root.destroy()
    print("\n%s" % ("FAILED: " + ", ".join(fail) if fail else "ALL PASS"))
    return 1 if fail else 0


sys.exit(main())
