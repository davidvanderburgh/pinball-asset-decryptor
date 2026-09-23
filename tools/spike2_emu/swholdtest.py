#!/usr/bin/env python3
"""swholdtest.py - does a playfield press-and-hold really hold? Offline.

Run on WINDOWS, with NO emulator up:

    py tools\\spike2_emu\\swholdtest.py [switch_id] [hold_ms] [game]
    py tools\\spike2_emu\\swholdtest.py --pulse     # the negative control

WHY THIS CAN RUN WITHOUT A GAME, which is the whole reason it is worth having:
padsw.py reads `PAD_SW_FILE` and says in terms that it "points the helpers at a
block that is not a running game's, which is the only way to check any of this
without one". So this builds a fake padsw block in WSL, points the helpers at
it, drives the REAL playfield controller, and reads back what it wrote. A run
costs minutes and cannot be parallelised; this costs seconds and can be run
after any edit.

WHAT IT DRIVES, and it matters that it is not a reimplementation. The window
is a web page now (2026-09-23): the page decides WHICH marker a press lands on
(`pfHit()` in pfpage/pf.js) and then calls the controller's api - `hold` /
`unhold` for a switch ring, `coil` then `unhold` for a coil square. So this
builds the real `playfield.Playfield()` headless (no page, no window), asks
the SHIPPED pf.js - run under Node - which marker a press at the switch
marker's own screen position reaches, and makes exactly the api calls the
page's pointerdown / pointerup would. The hit test, the `holding` bookkeeping
and SwitchDriver's queue are all the shipping code; only the browser's event
delivery is skipped, which is also why no OS input injection is needed (SendInput
into this rig's windows is UIPI-blocked, REMAINING items 7 and 12). Without
Node on PATH the hit test cannot be asked, so the switch marker is pressed
directly and the report says so.

To SEE the window instead, run `python playfield.py <game>` beside a run.

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
import json
import os
import shutil
import struct
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

#: The page, whose hit test decides which marker a press reaches.
PF_JS = os.path.join(HERE, "pfpage", "pf.js")

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


# ---- the page's side, asked of the page itself -------------------------------

def page_hit(view, px, py, scale):
    """What the PAGE's hit test (pf.js pfHit) returns for a pointer at screen
    (px, py) on `view` (a playfield.Field) drawn at `scale`: ["switch", k],
    ["coil", k], ["led", fid] or None. Run by Node against the shipped pf.js,
    so it is the shipping code rather than a copy of it. Raises LookupError
    when Node is not on PATH."""
    node = shutil.which("node")
    if node is None:
        raise LookupError("node is not on PATH")
    spec = view.spec()
    fx = {str(k): v for k, v in view.dyn()["fx"].items()}
    js = ("const { pfHit } = require(%s);\n"
          "console.log(JSON.stringify(pfHit(%s, %s, %s, %s, %s)));\n"
          % (json.dumps(PF_JS), json.dumps(spec), json.dumps(fx),
             json.dumps(scale), json.dumps(px), json.dumps(py)))
    r = subprocess.run([node, "-e", js], capture_output=True, text=True,
                       timeout=60)
    if r.returncode != 0:
        raise RuntimeError("pf.js under node: %s" % r.stderr.strip())
    return json.loads(r.stdout)


def page_scale(ctl):
    """The artwork scale the page opens at: what Playfield.window_spec() sizes
    the window for (PAD_PF_SCALE still overrides it there), less the key panel
    and the page's 16 px margin. The page refits to whatever the window
    becomes, so this is the OPENING scale - the marker shapes are screen
    pixels, so which marker wins can depend on it."""
    spec = ctl.window_spec()
    panel = 340 if ctl.key_panel is not None else 0
    return max(0.2, (spec["width"] - panel - 16) / float(ctl.view.base[0]))


def marker(ctl, sw_id):
    """(k, row) of the switch marker for `sw_id` on the artwork, or None."""
    for k, S in enumerate(ctl.view.sw_rows):
        if S["id"] == sw_id:
            return k, S
    return None


def describe_hit(ctl, hit):
    if hit is None:
        return "NOTHING"
    kind, k = hit
    if kind == "switch":
        return "SWITCH marker: %s" % ctl.view.sw_rows[k]["name"]
    if kind == "coil":
        import coilact
        coil = ctl.view.coils[k]["name"]
        held = coilact.hold_switch(coil)
        return "COIL marker: %s (a press %s)" % (
            coil, "holds switch %d" % held if held is not None
            else "runs coilact.py - nothing to hold")
    return "INSERT: %s" % ctl.view.fixtures[k].get("name")


class LeftPress:
    """A left press and release, as the page's canvas pointerdown/pointerup
    make them for the marker the hit test gave (pf.js fieldView)."""

    def __init__(self, ctl, hit):
        self.ctl, self.hit = ctl, hit

    def down(self):
        kind, k = self.hit
        if kind == "switch":
            self.ctl.api("hold", [self.ctl.view.sw_rows[k]["id"]])
        elif kind == "coil":
            self.ctl.api("coil", [k])

    def up(self):
        self.ctl.api("unhold", [])


def wait_for(sw, want, limit_s=15.0):
    """Wait until the oracle array reads `want`. Elapsed ms, or None."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit_s:
        if oracle(read_block(), sw) == want:
            return (time.monotonic() - t0) * 1000.0
        time.sleep(POLL_S)
    return None


def pump(secs):
    """Sample the block for `secs`. Returns the values seen."""
    seen, t0 = [], time.monotonic()
    while time.monotonic() - t0 < secs:
        v = oracle(read_block(), SW)
        if v is not None:
            seen.append(v)
        time.sleep(POLL_S)
    return seen


#: Flags out of the way before the positional arguments are read, so
#: `swholdtest.py --pulse` does not try to parse "--pulse" as a switch id.
PULSE = "--pulse" in sys.argv
#: Only a SCRIPT's own command line: swspintest.py imports the page helpers
#: below, and its arguments are not this one's.
ARGV = ([a for a in sys.argv[1:] if not a.startswith("--")]
        if __name__ == "__main__" else [])
SW = int(ARGV[0]) if ARGV else 53                       # RIGHT SCOOP
HOLD_MS = int(ARGV[1]) if len(ARGV) > 1 else 2000
GAME = ARGV[2] if len(ARGV) > 2 else None


def close(ctl):
    """The window's close, minus the parts that belong to a window (saving
    its position, telling a page): stop the loop, close the keyboard helper."""
    ctl.stop()
    if ctl.keys is not None:
        ctl.keys.close()


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
    import playfield

    ctl = playfield.Playfield()
    if ctl.kind != "field":
        print("%s has no artwork view here (the window would be the %s page),"
              " so there is no marker to press" % (playfield.GAME, ctl.kind))
        close(ctl)
        return 1

    # The marker's own screen coordinates, found the way a mouse would find it.
    found = marker(ctl, SW)
    if found is None:
        print("switch %d is not on this playfield" % SW)
        close(ctl)
        return 1
    k, S = found
    name = S["name"]
    scale = page_scale(ctl)
    x, y = S["x"] * scale, S["y"] * scale
    print("switch %d  %s  at screen (%.0f,%.0f), artwork scale %.2f"
          % (SW, name, x, y, scale))

    # SAY WHICH MARKER A MOUSE WOULD ACTUALLY GET, because it is not always the
    # switch: the coil is drawn over it, and at RIGHT SCOOP the coil wins. That
    # is the finding this whole item turned on, so the test states it every run
    # rather than leaving the next reader to assume the switch was pressed.
    try:
        hit = page_hit(ctl.view, x, y, scale)
        if hit is None or hit[0] == "led":
            # The middle of a bare ring is its hole (swspintest.py measured
            # it): a hand aims at the drawn circle, so aim at its stroke.
            print("a press at the centre lands on %s; aiming at the ring"
                  % describe_hit(ctl, hit))
            y -= 6
            hit = page_hit(ctl.view, x, y, scale)
        print("a press here lands on the %s\n" % describe_hit(ctl, hit))
    except LookupError as exc:
        hit = ["switch", k]
        print("%s - the page's hit test cannot be asked, so the SWITCH marker"
              " is pressed directly\n" % exc)
    if hit is None or hit[0] == "led":
        print("the page would press nothing there")
        close(ctl)
        return 1
    press = LeftPress(ctl, hit)

    fail = []

    # ---- 0. THE NEGATIVE CONTROL ------------------------------------------
    # `--pulse` drives the OLD gesture - coilact.py's fixed 120 ms pulse - and
    # runs the same HOLD check against it. It MUST FAIL. An instrument that has
    # never been shown the defect it is looking for is not evidence, and this
    # rig has three metrics on record that ranked a known-bad capture as clean.
    if PULSE:
        print("NEGATIVE CONTROL: the pre-item-24 gesture, which must FAIL\n")
        ctl.drv.run_script("coilact.py", name)
        t_close = wait_for(SW, 1)
        if t_close is None:
            print("CTRL   the pulse never closed the switch at all")
            close(ctl)
            return 1
        seen = pump(HOLD_MS / 1000.0)
        held = all(v == 1 for v in seen)
        print("CTRL   closed in %.1f ms, then %d of %d samples read OPEN"
              % (t_close, seen.count(0), len(seen)))
        print("\n%s" % ("CONTROL FAILED AS IT MUST - the test can see a pulse"
                        if not held else
                        "CONTROL PASSED, WHICH IS WRONG - the test is blind"))
        close(ctl)
        return 0 if not held else 1

    # ---- 1. HOLD ---------------------------------------------------------
    g0 = scr_gen(read_block())
    press.down()
    t_close = wait_for(SW, 1)
    if t_close is None:
        print("HOLD   FAIL: press never closed the switch")
        fail.append("hold-press")
    else:
        print("HOLD   press -> %s closed in %6.1f ms" % (ORACLE, t_close))
        seen = pump(HOLD_MS / 1000.0)
        held = all(v == 1 for v in seen)
        print("       held for %d ms: %d samples of %s, %s"
              % (HOLD_MS, len(seen), ORACLE,
                 "all closed" if held else "DROPPED OUT (%d open)"
                 % seen.count(0)))
        if not held:
            fail.append("hold-drop")
        press.up()
        t_open = wait_for(SW, 0)
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
        press.down()
        press.up()
        t0, closed_ms, saw = time.monotonic(), None, False
        while time.monotonic() - t0 < 15.0:
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
    # The stuck-switch check. Ten clicks as fast as the api takes them; the
    # switch must end OPEN. This is the one that fails if press and release
    # ever run on separate threads instead of one queue.
    #
    # WAIT FOR THE QUEUE, NOT FOR A VALUE. Polling for 0 passes INSTANTLY and
    # means nothing - the switch is still 0 because the first press has not
    # spawned yet, and this test reported a cheerful "drained in 3 ms" over
    # twenty pending actions. A metric that can be satisfied before the work
    # starts is not measuring the work.
    print("")
    for _ in range(10):
        press.down()
        press.up()
    t0 = time.monotonic()
    while not ctl.drv.q.empty() and time.monotonic() - t0 < 60.0:
        time.sleep(POLL_S)
    ctl.drv.q.join()
    drained = (time.monotonic() - t0) * 1000.0
    end = oracle(read_block(), SW)
    if end == 0:
        print("ORDER  10 fast clicks -> open, %d actions drained in %.0f ms"
              % (20, drained))
    else:
        print("ORDER  FAIL: STUCK CLOSED after 10 fast clicks (scr_held=%s)"
              % end)
        fail.append("order-stuck")
    print("       driver still holds: %s (want an empty set)" % ctl.drv.held)
    if ctl.drv.held:
        fail.append("order-held")
    print("       controller still holding: %s (want None)" % ctl.holding)
    if ctl.holding is not None:
        fail.append("order-holding")

    close(ctl)
    print("\n%s" % ("FAILED: " + ", ".join(fail) if fail else "ALL PASS"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
