#!/usr/bin/env python3
"""ledratetest.py - does the playfield's LED rate report the PICTURE? Offline.

Run on WINDOWS, with NO emulator up:

    py tools\\spike2_emu\\ledratetest.py

WHY IT EXISTS. Item 31 is a window that reported a rock-steady 30 fps over a
picture that changed 2.6 times a second, so the fix is a second number - and a
second number that is wrong is worse than the first one, because it looks like
evidence. This drives the REAL `Field` against a fake `dump/padled` that this
script publishes at a rate IT chooses, so the right answer is known before the
window is asked. No emulator, no card, ~20 s.

THE TWO CASES, and the second is the one that makes the first mean anything:

  1. PACED   - 5 Hz of genuinely new lamp values, then a deliberate 2 s freeze,
               then 5 Hz again. The window must report ~5 Hz and must catch the
               freeze as its worst gap. A field that reported the POLL rate
               would say 30 here and pass nothing.
  2. CHURN   - 30 Hz of writes that carry values ALREADY ON SCREEN. The picture
               cannot change, so the LED rate must fall to ~0 while the data
               rate reads ~30 in the always-present data field.
               This is the labelled negative example: an instrument that has
               never been shown a case it must score LOW is not evidence, and
               this rig has three audio metrics on record that failed exactly
               that check.

  3. FADE    - one step 0 -> 255 -> 0. The window must pass through several
               DISTINCT intermediate paints on the way up and again on the way
               down (PAD_PF_FADE_MS, David's CSS-transition ask, 2026-08-07),
               and must LAND: the final drawn state is the full-brightness
               tuple, then the off tuple. A tween that snaps scores 1 paint
               and fails; a tween that never arrives fails the landing.

It validates ledrate.py in the same breath, off the same writer, because that
one reads the same block from the other side of the VM boundary and its numbers
are only comparable if both agree on a case where the truth is known.
"""
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MAGIC = 0x44454C50
LED_HDR = 20
OFF_GEN, OFF_DECODED = 8, 12
BLOCK = 4096

GAME = os.environ.get("PAD_GAME", "godzilla_pro")


class Feed:
    """Publishes a padled block at a scripted rate. The ground truth."""

    def __init__(self, path, channels):
        self.path = path
        self.channels = channels          # [(node, idx), ...] actually drawn
        self.buf = bytearray(BLOCK)
        struct.pack_into("<II", self.buf, 0, MAGIC, 2)
        self.gen = self.dec = 0
        self.stop = False
        self.frames = 0
        self.written = 0
        self._flush()

    def _flush(self):
        struct.pack_into("<II", self.buf, OFF_GEN, self.gen, self.dec)
        # ONE write, not a field at a time: a reader on the other side polls
        # this at 30-200 Hz and a torn block would be scored as a change that
        # never happened.
        with open(self.path, "r+b") as f:
            f.write(self.buf)

    def frame(self, value, count):
        """One LED frame: `count` channels set to `value`, counters bumped."""
        for node, idx in self.channels[:count]:
            self.buf[LED_HDR + node * 96 + idx] = value
        self.gen += 1
        self.dec += count
        self.frames += 1
        self.written += count
        self._flush()

    def run(self, script):
        """script = [(hz, seconds, changing)] played in order."""
        v = 0
        for hz, secs, changing in script:
            end = time.perf_counter() + secs
            step = 1.0 / hz if hz else secs
            while time.perf_counter() < end and not self.stop:
                if changing:
                    # A NEW value every frame, and never 0 - a fixture whose
                    # value goes to 0 is drawn as OFF, which is a change the
                    # first time and then is not.
                    v = 40 + ((v + 37) % 200)
                    self.frame(v, 12)
                else:
                    self.frame(v, 12)      # the SAME value: no picture change
                time.sleep(step)
            if self.stop:
                return


def build(root_dir):
    os.makedirs(os.path.join(root_dir, "dump"), exist_ok=True)
    p = os.path.join(root_dir, "dump", "padled")
    with open(p, "wb") as f:
        f.write(bytearray(BLOCK))
    return p


def run_case(name, script, secs, expect_led, expect_data, expect_gap,
             tables, root_dir, path, check_ledrate=False):
    import tkinter as tk
    import playfield

    # The real window asks for 1 ms timers in main(); without it Tk's `after`
    # rounds up to Windows' 15.6 ms tick and the loop lands at 24-25 fps. The
    # harness has to ask too, or it measures a slower loop than the thing it is
    # standing in for - and "the poll rate is fine" is half of what this test
    # is asserting.
    playfield.fine_timers()
    root = tk.Tk()
    # Invisible rather than withdrawn: a withdrawn window does not lay out, and
    # the canvas has to be real for draw_fixtures to have anything to change.
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    root.title("ledratetest")
    view = playfield.Field(root)
    root.update()

    chans = []
    for F in view.fixtures:
        for _, (node, idx) in F["channels"].items():
            chans.append((node, idx))
    feed = Feed(path, chans)

    proc = None
    if check_ledrate:
        env = dict(os.environ, PAD_ROOT=root_dir, PAD_LEDRATE_HZ="200")
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "ledrate.py"), str(secs - 1)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)

    th = threading.Thread(target=feed.run, args=(script,), daemon=True)
    th.start()
    root.after(int(secs * 1000), root.quit)
    root.mainloop()
    feed.stop = True
    th.join(timeout=2)

    t = time.perf_counter()
    led = view._rate(view._draw_ev, t)
    data = view._rate(view._data_ev, t)
    gap = view._gap_worst
    bar = view.status.cget("text")
    root.destroy()

    print("\n--- %s ---" % name)
    print("  fed        : %d frames, %d lamp writes in %.0f s"
          % (feed.frames, feed.written, secs))
    print("  window says: LED %.1f Hz   data %.1f Hz   poll %.0f fps   "
          "worst gap %.2f s" % (led, data, view.fps, gap))
    print("  status bar : %s" % bar.strip())

    fail = []
    lo, hi = expect_led
    if not lo <= led <= hi:
        fail.append("LED rate %.1f Hz outside expected %.1f-%.1f" % (led, lo, hi))
    lo, hi = expect_data
    if not lo <= data <= hi:
        fail.append("data rate %.1f Hz outside expected %.1f-%.1f"
                    % (data, lo, hi))
    if expect_gap is not None:
        lo, hi = expect_gap
        if not lo <= gap <= hi:
            fail.append("worst gap %.2f s outside expected %.2f-%.2f"
                        % (gap, lo, hi))
    if view.fps < 25:
        fail.append("poll rate collapsed to %.1f fps - the loop itself is sick"
                    % view.fps)

    if proc is not None:
        out = proc.communicate(timeout=30)[0]
        print("  ledrate.py (the WSL-side reader, run here against the same "
              "block):")
        for line in out.strip().splitlines():
            print("    %s" % line)
        # It counts FRAMES, which is what the feed produced - so it must agree
        # with the feed, not with the window. Matched on the WHOLE label and on
        # there being an `=`, because "gap between LED frames" also contains
        # "LED frames" and carries no rate at all - the loose match took it and
        # died on the missing `=`.
        got = None
        for line in out.splitlines():
            if line.strip().startswith("LED frames") and "=" in line:
                got = float(line.rsplit("=", 1)[1].split()[0])
        if got is None:
            fail.append("ledrate.py printed no frame rate")
        elif not 0.6 * feed.frames / secs <= got <= 1.6 * feed.frames / secs:
            fail.append("ledrate.py says %.2f Hz, the feed produced %.2f Hz"
                        % (got, feed.frames / secs))
    return fail


def run_fade_case(path):
    """One step 0 -> 255 -> 0: the tween must MOVE and must LAND.

    Samples the target fixture's drawn tuple every few ms across each edge.
    Distinct tuples < 4 means it snapped (or the quantisation ate the ramp);
    a wrong final tuple means it animated somewhere other than the target.
    Runs with the default PAD_PF_FADE_MS so it tests what ships.
    """
    import tkinter as tk
    import playfield

    playfield.fine_timers()
    root = tk.Tk()
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    root.title("ledratetest-fade")
    view = playfield.Field(root)
    root.update()

    feed = Feed(path, [])
    node, idx = None, None
    target = None
    for F in view.fixtures:
        if len(F["channels"]) == 1 and "W" in F["channels"]:
            node, idx = F["channels"]["W"]
            target = F
            break
    if target is None:
        root.destroy()
        return ["no single-channel fixture to drive"]

    def settle(ms):
        """Pump real ticks for ms, collecting the drawn tuples seen."""
        seen = []
        end = time.perf_counter() + ms / 1000.0
        while time.perf_counter() < end:
            root.update()
            d = target["drawn"]
            if d is not None and (not seen or seen[-1] != d):
                seen.append(d)
            time.sleep(0.004)
        return seen

    fail = []
    span = max(400.0, playfield.FADE_MS * 2)

    feed.buf[LED_HDR + node * 96 + idx] = 255
    feed.gen += 1
    feed.dec += 1
    feed._flush()
    up = settle(span)
    if len(up) < 4:
        fail.append("fade IN drew %d distinct states - it snapped: %s"
                    % (len(up), up))
    want_on = up[-1] if up else None
    if not want_on or not want_on[2]:
        fail.append("fade IN never landed lit (last drawn %r)" % (want_on,))

    feed.buf[LED_HDR + node * 96 + idx] = 0
    feed.gen += 1
    feed.dec += 1
    feed._flush()
    down = settle(span)
    if len(down) < 4:
        fail.append("fade OUT drew %d distinct states - it snapped: %s"
                    % (len(down), down))
    if not down or down[-1][2] != 0.0:
        fail.append("fade OUT never landed off (last drawn %r)"
                    % (down[-1] if down else None,))

    print("\n--- FADE  one step up, one step down (FADE_MS=%g) ---"
          % playfield.FADE_MS)
    print("  up  : %d distinct paints, landed %s"
          % (len(up), "lit" if want_on and want_on[2] else "NOT LIT"))
    print("  down: %d distinct paints, landed %s"
          % (len(down), "off" if down and down[-1][2] == 0.0 else "NOT OFF"))
    root.destroy()
    return fail


def main():
    sys.argv = [sys.argv[0], GAME]
    # THE TABLES HAVE TO BE PINNED BEFORE PAD_ROOT MOVES. dump/ and tables/ are
    # both derived from the rootfs, so pointing PAD_ROOT at a temp directory to
    # get a fake padled also points the artwork at a directory that has none -
    # the window then comes up as a schematic with no fixtures at all and the
    # whole test measures nothing. Asked of padpath while the real root is
    # still in force, and set explicitly afterwards.
    import padpath
    real_tables = padpath.tables()
    if not real_tables or not os.path.isdir(os.path.join(real_tables, GAME)):
        sys.exit("ledratetest: no derived tables for %s (%s).\n"
                 "  Run a title once, or point PAD_TABLES at a built one."
                 % (GAME, real_tables))

    root_dir = tempfile.mkdtemp(prefix="ledratetest_")
    path = build(root_dir)
    os.environ["PAD_ROOT"] = root_dir
    os.environ["PAD_TABLES"] = real_tables
    os.environ.pop("PAD_SW_FILE", None)
    print("fake block: %s" % path)
    print("tables    : %s" % real_tables)
    print("title     : %s (real tables, real artwork)\n" % GAME)

    fails = []
    # 1. PACED, with a hole in the middle. 5 Hz -> 2 s of nothing -> 5 Hz.
    # The rate is read at the END, so the window is measured over the second
    # 5 Hz stretch and the gap over the freeze.
    fails += [("paced", f) for f in run_case(
        "PACED  5 Hz, 2 s freeze, 5 Hz",
        [(5, 3.0, True), (0.5, 2.0, False), (5, 4.0, True)],
        9.5, expect_led=(3.5, 6.5), expect_data=(3.5, 8.0),
        expect_gap=(1.5, 3.0), tables=None, root_dir=root_dir, path=path,
        check_ledrate=True)]

    # 2. CHURN, the negative control: writes that change nothing on screen.
    fails += [("churn", f) for f in run_case(
        "CHURN  30 Hz of already-drawn values",
        [(5, 1.5, True), (30, 6.0, False)],
        7.5, expect_led=(0.0, 0.7), expect_data=(15.0, 32.0),
        expect_gap=None, tables=None, root_dir=root_dir, path=path)]

    # 3. FADE: the tween animates and lands. A fresh block so case 2's last
    # values cannot leak into the edge being scored.
    path = build(root_dir)
    fails += [("fade", f) for f in run_fade_case(path)]

    print("\n" + "=" * 62)
    if fails:
        for case, f in fails:
            print("FAIL  %-7s %s" % (case, f))
        return 1
    print("PASS  the LED field tracks the picture, not the poll:")
    print("      it reads ~5 Hz when the picture moves 5 times a second,")
    print("      falls to ~0 when 30 Hz of writes change nothing on screen,")
    print("      catches a 2 s freeze the poll rate cannot see,")
    print("      and a state step fades through the middle and lands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
