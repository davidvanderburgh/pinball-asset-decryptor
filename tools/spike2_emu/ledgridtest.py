#!/usr/bin/env python3
"""ledgridtest.py - does the swatch grid show the WIRE? Offline, no emulator.

Run on WINDOWS, with NO emulator up:

    py tools\\spike2_emu\\ledgridtest.py

WHY IT EXISTS. Item 50's grid is the LED feedback for a title with no playfield
artwork - and on the four titles that land there (star_wars_le,
stranger_things_le, turtles_pro, led_zeppelin_le) the device table is EMPTY, so
there is nothing to check the picture against except the block itself. That
makes an instrument easy to fool: a grid that drew a cell for every possible
address would light up convincingly on a rig publishing nothing at all.

So the cases below are built around what this rig has learned the hard way -
that a metric which has never been shown an example it must score LOW is not
evidence:

  1. DISCOVERY   - 12 channels written on two boards. The grid must end up with
                   exactly 12 cells, and they must be the twelve that were
                   written, matched by (node, index) and not by count alone.
  2. NOTHING ELSE - THE LABELLED NEGATIVE, and the reason for the whole file.
                   1536 addresses exist in the block; 12 were written. A grid
                   that shows 288 (every index of the decoded boards) or 1536
                   fails here while looking perfectly alive on screen. This is
                   the case that says the roster comes from the wire.
  3. TRACKING    - a written channel's cell paints, the same value again
                   repaints NOTHING (the churn control, borrowed from
                   ledratetest.py), and zeroing it puts the cell back to dark
                   while KEEPING it - a lamp that pulses once must not make its
                   cell vanish.
  4. THE PULSE   - one a2 envelope over a range. The cells must sweep and come
                   home to the base layer, which is the half of the light show
                   that lives in the fade ring rather than in val[].

It drives the REAL `Schematic` view, against the REAL padled writer this rig
already validated (ledratetest.Feed - imported, not copied: two writers of one
block is the drift this repo keeps paying for).
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ledratetest import Feed, build, LED_HDR          # noqa: E402

#: A title with NO device table, on purpose: it is the case the grid exists
#: for, and it means no name can join two channels into one fixture, so a
#: channel is a cell and the arithmetic below is exact.
GAME = os.environ.get("PAD_GRID_GAME", "turtles_pro")

#: What gets written. Two boards and deliberately IRREGULAR indices - a
#: contiguous run would pass a grid that just drew 0..n.
CHANS = [(8, 0), (8, 3), (8, 4), (8, 17), (8, 40), (8, 63),
         (9, 1), (9, 2), (9, 19), (9, 45), (9, 61), (9, 70)]


def settle(root, ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.004)


def main():
    sys.argv = [sys.argv[0], GAME]
    import padpath
    real_tables = padpath.tables()
    if not real_tables or not os.path.isdir(os.path.join(real_tables, GAME)):
        sys.exit("ledgridtest: no derived tables for %s (%s).\n"
                 "  Run a title once, or point PAD_TABLES at a built one."
                 % (GAME, real_tables))

    root_dir = tempfile.mkdtemp(prefix="ledgridtest_")
    path = build(root_dir)
    os.environ["PAD_ROOT"] = root_dir
    os.environ["PAD_TABLES"] = real_tables
    os.environ.pop("PAD_SW_FILE", None)
    print("fake block: %s" % path)
    print("title     : %s (no device table - the case the grid is for)\n" % GAME)

    import tkinter as tk
    import playfield

    playfield.fine_timers()
    root = tk.Tk()
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    root.title("ledgridtest")
    rows = playfield.load_switch_list()
    if not rows:
        sys.exit("ledgridtest: %s has no switch_list.txt, so the Schematic "
                 "view cannot be built" % GAME)
    view = playfield.Schematic(root, rows)
    root.update()

    feed = Feed(path, CHANS)
    fail = []

    # ---- 1 + 2: discovery, and NOTHING BUT what was written ---------------
    for node, idx in CHANS:
        feed.buf[LED_HDR + node * 96 + idx] = 90
    feed.gen += 1
    feed.dec += len(CHANS)
    feed._flush()
    settle(root, 500)

    got = {k for C in view.leds.cells for k in C["channels"].values()}
    want = set(CHANS)
    print("--- DISCOVERY ---")
    print("  wrote %d channels, grid has %d cells" % (len(CHANS),
                                                      len(view.leds.cells)))
    if got != want:
        fail.append("grid roster %s != what was written %s"
                    % (sorted(got - want)[:6], sorted(want - got)[:6]))
    if len(view.leds.cells) != len(CHANS):
        fail.append("grid drew %d cells for %d written channels"
                    % (len(view.leds.cells), len(CHANS)))
    print("  labelled negative: 1536 addresses exist, %d drawn -> %s"
          % (len(view.leds.cells),
             "PASS" if len(view.leds.cells) == len(CHANS) else "FAIL"))

    # ---- 2b: THE ROSTER GROWS IN STAGES, which is how a real run does it --
    # ★ THIS CASE EXISTS BECAUSE THE FIRST GRID FAILED IT AND NOTHING ELSE
    # NOTICED. Lighting every channel at once is ONE rebuild, and the bug -
    # fresh cell dicts per rebuild, so a new rectangle per cell each time and
    # the old generation orphaned on the canvas - only appears from the second
    # rebuild on. It showed up as blue node headers buried under stale
    # swatches, i.e. as a layout problem, which is not where the fault was.
    # Counting canvas items is what makes it a test rather than an opinion.
    items_before = len(view.cv.find_all())
    extra = [(8, 71), (8, 72), (9, 80), (9, 81)]
    for n, (node, idx) in enumerate(extra):
        feed.buf[LED_HDR + node * 96 + idx] = 140
        feed.gen += 1
        feed.dec += 1
        feed._flush()
        settle(root, 200)
    grew = len(view.cv.find_all()) - items_before
    print("--- ROSTER GROWTH ---")
    print("  4 channels arrived in 4 separate rebuilds: %d cells, %d new "
          "canvas items" % (len(view.leds.cells), grew))
    if len(view.leds.cells) != len(CHANS) + len(extra):
        fail.append("roster is %d cells after %d + %d channels"
                    % (len(view.leds.cells), len(CHANS), len(extra)))
    # One rectangle per new cell, and nothing else. A per-rebuild leak shows
    # here as tens of items rather than four.
    if grew > len(extra) + 1:
        fail.append("%d canvas items created for %d new cells - stale items "
                    "are being left behind on every rebuild"
                    % (grew, len(extra)))
    for node, block in view.leds.by_node.items():
        hy = view.cv.coords(view.leds._hdrs[node])[1]
        top = min(view.cv.coords(C["item"])[1] for C in block)
        if top <= hy:
            fail.append("node %d's cells (y=%.0f) sit on top of its header "
                        "(y=%.0f)" % (node, top, hy))

    # ---- 3: tracking, the churn control, and stickiness -------------------
    target = next(C for C in view.leds.cells
                  if (8, 17) in C["channels"].values())
    base = target["drawn"]
    feed.buf[LED_HDR + 8 * 96 + 17] = 255
    feed.gen += 1
    feed.dec += 1
    feed._flush()
    settle(root, 300)
    lit = target["drawn"]
    if lit == base:
        fail.append("a channel driven to 255 did not repaint its cell")

    before = view.leds.cells[0]["drawn"], target["drawn"]
    for _ in range(20):                 # the SAME value, 20 more times
        feed.gen += 1
        feed.dec += 1
        feed._flush()
        settle(root, 20)
    if (view.leds.cells[0]["drawn"], target["drawn"]) != before:
        fail.append("cells repainted for writes that changed no value")

    n_before = len(view.leds.cells)
    feed.buf[LED_HDR + 8 * 96 + 17] = 0
    feed.gen += 1
    feed.dec += 1
    feed._flush()
    settle(root, 300)
    print("--- TRACKING ---")
    print("  at 90 %s -> at 255 %s -> at 0 %s"
          % (base, lit, target["drawn"]))
    if target["drawn"] == lit:
        fail.append("a channel driven to 0 stayed lit")
    if len(view.leds.cells) != n_before:
        fail.append("a cell VANISHED when its channel went dark (%d -> %d)"
                    % (n_before, len(view.leds.cells)))
    print("  cells kept when the lamp went out: %d -> %d"
          % (n_before, len(view.leds.cells)))

    # ---- 4: the a2 pulse envelope ----------------------------------------
    # ★ THE BASE HERE IS 90, NOT DARK, AND THAT IS THE POINT. padled.h: a
    # pulse is an OVERLAY and "ends where the base says", so the assertion is
    # that the cells come home to the value val[] still carries - not that
    # they go out. Asserting darkness was this test's own first bug and it
    # failed a grid that was behaving correctly.
    env_cells = [C for C in view.leds.cells
                 if C["channels"].get("W", (None, None))[0] == 9
                 and C["channels"]["W"][1] in (1, 2)]
    env_base = tuple(C["drawn"] for C in env_cells)
    feed.fade(9, 1, 2, 0x00, 0xFF, 20, 20)
    swing = []
    end = time.perf_counter() + (40 * playfield.FADE_UNIT_MS + 500) / 1000.0
    while time.perf_counter() < end:
        root.update()
        s = tuple(C["drawn"] for C in env_cells)
        if not swing or swing[-1] != s:
            swing.append(s)
        time.sleep(0.004)
    print("--- PULSE ---")
    print("  %d distinct paints over the %d enveloped cells, ended %s"
          % (len(swing), len(env_cells),
             "back on the base layer" if swing and swing[-1] == env_base
             else "SOMEWHERE ELSE"))
    if len(swing) < 6:
        fail.append("the a2 envelope drew %d distinct states - no sweep"
                    % len(swing))
    if not swing or swing[-1] != env_base:
        fail.append("the a2 envelope ended at %s, not back on the base layer %s"
                    % (swing[-1] if swing else None, env_base))

    # ---- 5: A PULSE-ONLY LAMP MUST STILL GET A CELL -----------------------
    # ★ An a2 pulse writes ONLY the fade ring: padled.h says val[] is not
    # touched, and hwshim does not move `decoded` either. A roster built by
    # scanning val[] therefore never sees a lamp the game animates purely with
    # pulses - it is dark in val[] for ever. Drive a channel that has NEVER
    # been written and check it earns a cell.
    n_before = len(view.leds.cells)
    fresh = (9, 33)
    if fresh in view.leds.seen:
        fail.append("test bug: %r was already in the roster" % (fresh,))
    feed.fade(fresh[0], fresh[1], fresh[1], 0x00, 0xFF, 20, 20)
    settle(root, 400)
    print("--- PULSE-ONLY LAMP ---")
    got = fresh in view.leds.seen
    print("  channel %r never written to val[], only pulsed: %s"
          % (fresh, "got a cell" if got else "NO CELL"))
    if not got:
        fail.append("a channel driven only by an a2 pulse never entered the "
                    "roster (%d cells before, %d after)"
                    % (n_before, len(view.leds.cells)))

    # ---- 6: A DARK CELL MUST BE HIT-TESTABLE ------------------------------
    # ★ Tk excludes the INTERIOR of an unfilled rectangle from
    # find_overlapping, so a dark swatch drawn with fill="" cannot be hovered
    # and its tooltip - the only thing naming the lamp on a table-less title -
    # is unreachable. Query the centre of a dark cell the way _hit_led does.
    dark = next((C for C in view.leds.cells if C["state"][0] is None), None)
    if dark is None:
        fail.append("no dark cell to hit-test")
    else:
        x0, y0, x1, y1 = view.cv.coords(dark["item"])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        hits = view.cv.find_overlapping(cx, cy, cx, cy)
        print("--- DARK CELL HIT TEST ---")
        print("  centre of a dark swatch (%s): %d item(s) under the point"
              % (dark["name"], len(hits)))
        if dark["item"] not in hits:
            fail.append("the centre of a DARK cell hit-tests to nothing, so "
                        "its tooltip is unreachable - the one thing that names "
                        "the lamp on a title with no table")

    root.destroy()
    print("\n" + "=" * 62)
    if fail:
        for f in fail:
            print("FAIL  %s" % f)
        return 1
    print("PASS  the grid shows the wire and only the wire:")
    print("      12 written channels become exactly 12 cells out of 1536")
    print("      addresses, four more arriving one at a time cost four canvas")
    print("      items and leave no stale swatch over the headers, a lamp's")
    print("      cell tracks its value up and back to dark, writes that")
    print("      change nothing repaint nothing, a cell survives its lamp")
    print("      going out, and an a2 pulse sweeps and lands on the base.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
