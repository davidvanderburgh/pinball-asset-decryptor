#!/usr/bin/env python3
"""playfield.py - the virtual playfield: click switches, watch the inserts light.

Run it on WINDOWS, next to the emulator, while watch.sh has the game up. watch.sh
starts it for you through WSL interop; to run it by hand use pythonw so no
console window appears:

    pythonw tools\\spike2_emu\\playfield.py

WHY WINDOWS AND NOT WSL, because the obvious choice does not work: WSL here has
no Python GUI toolkit at all - no tkinter, no gi/Gtk, no Qt - and installing one
needs a sudo this rig does not have. Windows has tkinter and Pillow already,
because the decryptor's own GUI uses them.

HOW IT REACHES THE GAME, and both halves are deliberate:

  * LED STATE IS READ, not mapped. The shim publishes live values into
    `dump/padled` (see padled.h) and this REOPENS and reads that file over
    \\\\wsl.localhost every frame. A plain read needs no mmap coherence across
    the VM boundary, and it is measurably live - the generation counter climbs.

    REOPENING IS NOT THE SLOW PART, AND HOLDING THE HANDLE OPEN IS A TRAP.
    Measured 2026-08-05 from the Windows side: a reopen+read costs 3.4 ms
    whatever it reads (8 bytes or 1908 - it is the round trip, not the
    bytes), which is a 147 fps ceiling and never the reason this window was
    slow. Holding one handle open instead measured 0.00 ms and 2.9 M ops/s,
    which is what a CLIENT-SIDE CACHE looks like: against a WSL-side writer
    that reached 188, the held handle read 0 for the entire test and never
    moved. It would have frozen the playfield while looking like a 3000x
    speedup.
  * SWITCH INPUT GOES THROUGH swhold.py / swpoke.py / plunge.py, as
    subprocesses. Writing the padsw block from Windows would be a shared-memory
    write racing a guest mmap across a 9p boundary, which is exactly the kind of
    thing that works in testing and fails later. ~200 ms of `wsl.exe` per action
    buys a path that is already proven, and none of these are timing-critical -
    a HOLD's length is set by the mouse button, not by the spawn.

A SWITCH IS HELD FOR AS LONG AS THE MOUSE BUTTON IS DOWN, which is the whole
point for a ball device: a scoop keeps its ball while the switch is made, so a
fixed-length pulse could never play one (REMAINING item 24). Press closes,
release opens, and SwitchDriver serialises the two so a fast click cannot
deliver them out of order and latch a switch on for good.

WHAT THE COLOURS MEAN, honestly. Blue rings are switches, hold one to close it.
Red squares are coils, which flash when the game fires them and play their
switch when clicked (see coilact.py for why a click cannot be a real fire).
Dots are inserts, lit from the wire - an RGB insert is ONE dot in the colour
its three channels compose to, not three orange dots. The device table wires
"SHIELD LEFT-R/-G/-B" as three independent channels because that is what the
board drives, but the playfield has one lens there, so the -R/-G/-B stems are
joined per fixture (see group_fixtures) and the marker shows the joined colour
with a soft glow behind it.

WHAT BRIGHTNESS LOOKS LIKE. A lit insert is drawn at a SIZE and an OPACITY
that both follow its duty cycle, so a half-lit lamp reads as half-lit at a
glance instead of as fully on: markers run 3.8 px at 5% duty to 5.5 px at
100%, blended 57% to 100% over the artwork behind them. Tk canvas items have
no alpha at all, so the "opacity" is the fill colour mixed toward the pixels
the marker covers, sampled from the artwork once at build time. Both scales
have a floor on purpose - a lamp at 5% duty is ON, and must not render as a
ghost. The HUE is still brightness-lifted so a dim insert keeps its colour.

THE RATE IS 60 fps AND IT IS MEASURED, not assumed: the status bar shows the
achieved rate, and PAD_PF_LOG=<path> writes a line a second breaking it into
transport and drawing. It was 15 fps before that was measured, while nominally
being a 20 Hz loop; 30 until 2026-08-07, when David asked why not 60 - the
3.4 ms read is a ~147 fps ceiling, so 30 was only ever the written acceptance
bar, not a limit.

BUT THAT IS THE POLL RATE AND IT IS NOT WHAT A HUMAN SEES, which is why the bar
carries two more numbers. A loop that reads `dump/padled` perfectly on time and
finds nothing new reports its target forever, so "30 fps" sat next to a picture
that was changing 2.6 times a second (item 31, measured off a screen recording:
24 of 275 frame transitions changed a pixel, with one gap of 2.83 s, while
every one of the 276 frames read a rock-steady 30 fps). `LED n.n Hz` is the
rate the STATE ARRIVING actually changes something, `data n.n Hz` is the rate
new bytes arrive at all, `poll n fps` is the loop labelled as the loop. Both
rate fields are ALWAYS shown: the first form of this bar showed the data field
only when it disagreed, and the toggling text width made the window resize
itself to fit (David saw it the same day it shipped). Reading the two numbers
against each other is the diagnosis: data far above LED means the writes carry
values already drawn or address fixtures this window does not draw.

TRANSITIONS ARE ANIMATED, AND THAT IS EMULATION RATHER THAN DECORATION. On the
real machine the LED boards render fades themselves: the game sends a fade
COMMAND and the board ramps the PWM locally, so the wire never carries the
intermediate levels - the indexed stream is 0x00/0x7f/0xff steps. Two layers
render here, matching the wire:

  * THE FADE LAYER - `cmd a2` blen=6, decoded 2026-08-07 (hwshim.c's fade
    notes carry the evidence; 93/93 captured frames fit). Each command is a
    one-shot PULSE ENVELOPE over a lamp range - FROM -> TO at the rate slot
    for that direction, back to FROM on the other slot, 0 = instant - and the
    shim publishes it in the padled fade ring (version 3). This window runs
    the envelope per channel ON TOP of the base picture, which is what turns
    "24 pixel-changes in 9 seconds" into the swells, blinks and BUILDING FIRE
    flicker the real playfield shows. The rate UNIT is the one guess left
    (PAD_PF_FADE_UNIT_MS scales it, reader-side, no rebuild); the long
    a2/b4/b5 bodies are still undecoded - item 1d holds both.
  * THE BASE LAYER snaps softly - PAD_PF_FADE_MS (default 80, 0 = hard snap)
    smooths a step over ~5 frames. The real boards snap direct writes, so
    this is deliberately just above imperceptible: 200 ms here read as LAG,
    which David reported in exactly that word.

A DARK INSERT HERE MEANS OFF, NOT "NO DATA" - which is worth stating plainly,
because the docstring used to warn the opposite. The undecoded strip boards
(nodes 7, 12 and 14) do exist, but every insert this window draws sits on node 8
or node 9, and both of those are decoded index for index against the boot
enumeration. The strip boards drive the TOPPER and the cabinet, and neither is
on this picture. 113 channels (53 on node 8, 60 on node 9) join into 81
fixtures: 13 RGB, 6 red+green (the BUILDING FIRE pairs), 62 single. All covered.
"""
import collections
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilact
import coilmap
import devicexy
import gameinfo
import keybinds
import mktables
import padpath
import padsw
import trough

HERE = padpath.RIG

#: The window's title. It is also the single-instance handle (see
#: raise_existing()), so it MUST carry the title of the game: with a fixed
#: string, starting a Godzilla run while a TMNT window was open just raised the
#: TMNT window and looked like the new run had drawn the wrong playfield. One
#: window per title is the behaviour that was wanted anyway.
#: The tooltip Toplevel is deliberately named something else.

#: Where the window remembers itself. In the user's profile rather than beside
#: the script, because the script's directory is version controlled and this is
#: per-machine state, not part of the rig.
STATE = os.path.join(os.path.expanduser("~"), ".pad_playfield.json")

#: The title, and everything derived from it. watch.sh passes the name on the
#: command line; gameinfo works it out otherwise.
GAME = gameinfo.active(sys.argv[1] if len(sys.argv) > 1 else None)
if not GAME:
    # Better than a window titled "None" drawing nothing. watch.sh always passes
    # the title on the command line, so this is the by-hand case.
    sys.exit("playfield.py: no title - pass one, or set PAD_GAME.\n"
             "  pythonw playfield.py godzilla_pro")
TDIR = gameinfo.table_dir(GAME)

#: Whether the Save/Load state controls exist at all. watch.sh passes
#: --savestates only when the boot is checkpointable (PAD_PIVOT) - the app's
#: Emulate tab owns the user-facing toggle and boots the matching shape - so
#: a window without the flag draws NO state controls, instead of buttons
#: whose only possible answer is "this run is not checkpointable".
SAVESTATES = "--savestates" in sys.argv[2:]

# BUILD WHAT IS MISSING RATHER THAN DRAWING A SCHEMATIC BECAUSE NOBODY RAN A
# SCRIPT. The artwork, the insert map and the coil positions are all derivable
# from the title's own files (mktables.py), so a title that HAS a device table
# should never fall back to the switch list merely because this is the first
# time it has been opened. watch.sh normally builds these before launching this
# window; this is the by-hand path, and the guard keeps the usual start free.
if TDIR and not os.path.exists(os.path.join(TDIR, "device_xy.txt")):
    try:
        mktables.build(GAME, say=lambda m: None)
    except Exception:                                       # noqa: BLE001
        # A window with a schematic beats no window. Whatever went wrong here
        # (no rootfs, an unreadable card mount) is reported properly by
        # mktables.py's own CLI, and is not worth losing the playfield over.
        pass

PF_PNG = gameinfo.playfield_png(GAME)
WINDOW_TITLE = "%s - virtual playfield" % GAME

#: The live LED block, published by the shim inside the guest and read from
#: HERE, which is Windows. Asked of padpath rather than written out as
#: `\\wsl.localhost\Ubuntu\home\david\...`: that literal named a distro and a
#: user that need not exist, under a prefix older WSL spells `\\wsl$`. watch.sh
#: passes PAD_ROOT across interop already translated (WSLENV's `/p`), so in the
#: normal case this costs nothing at all.
LED_PATH = os.path.join(padpath.dump() or "", "padled")

#: PAD_PF_LOG=<path> turns on the once-a-second loop report (see Field._log).
#: Unset in normal use; this is the instrument the frame-rate claim rests on.
PF_LOG = os.environ.get("PAD_PF_LOG")

#: PAD_PF_SWDEBUG=1 echoes every switch action this window takes, with the
#: helper's own reply. See SwitchDriver._run.
SW_DEBUG = bool(os.environ.get("PAD_PF_SWDEBUG"))


def fine_timers():
    """Ask Windows for 1 ms timers, and say whether it agreed.

    WITHOUT THIS, THE TARGET RATE IS UNREACHABLE HERE AND THE REASON IS
    INVISIBLE.
    Windows' default scheduler tick is 15.6 ms and Tk's `after` rounds up to
    it, so a 4 ms frame asking for a 29 ms delay does not wait 29 ms - it
    waits for the next tick, and sometimes the one after. Measured on this
    box: frame work 3.6-4.3 ms, requested 29 ms, ACHIEVED 24-25 fps, i.e.
    ~41 ms between frames. Nothing in the loop looks wrong; the loop is not
    where the time goes.

    timeBeginPeriod(1) is the documented way to ask for a finer tick and is
    what media players use. It is process-wide and paired with timeEndPeriod
    at exit. On anything that is not Windows this is a no-op, and the caller
    treats failure as "run at whatever rate we get" rather than an error -
    the window is still useful at 24 fps, it just must not CLAIM 30.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return ctypes.windll.winmm.timeBeginPeriod(1) == 0
    except Exception:                                       # noqa: BLE001
        return False


def coarse_timers():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:                                       # noqa: BLE001
        pass

#: The switch block, read for ONE thing: the coin door. 48V - the coil supply -
#: is interlocked to it exactly as on the real machine, and with the door open
#: the game will not fire anything and puts "48V DISABLED" on its own screen. A
#: playfield whose coils never flash is then working perfectly, which is not a
#: thing to leave anyone to work out for themselves.
#:
#: It reads the MERGED array, which is what the guest hands the game, and not
#: the keyboard's half of the block - those are different answers now that the
#: two writers have an array each (padsw.py / padsw.h). Reading the keyboard's
#: half would miss a door opened with swhold.py, which is exactly how the door
#: gets opened from a script.
#:
#: PAD_SW_FILE WINS WHEN IT IS SET, exactly as padsw.py honours it: it is that
#: module's own escape hatch, "the only way to check any of this without a
#: running game", and this window is the thing most worth checking that way -
#: a block written by hand with known bytes in it turns the trough display
#: into something that can be judged against a reference instead of against a
#: memory of what the last run looked like. The rig never sets it.
SW_PATH = (os.environ.get("PAD_SW_FILE")
           or os.path.join(padpath.dump() or "", "padsw"))
PADSW_MAGIC = padsw.MAGIC
SW_HELD, SW_COIN_DOOR = padsw.OFF_MRG, 33

#: The key binds padglhost exports at startup (item 39) - the content of the
#: retired Controls window, drawn by THIS window's key panel instead. Same
#: directory as padled and padsw; keybinds.py owns the parse. PAD_PF_BINDS
#: is the offline escape hatch, the same shape as PAD_SW_FILE above: a file
#: written by hand turns the panel into something judgeable without a run.
BINDS_PATH = (os.environ.get("PAD_PF_BINDS")
              or os.path.join(padpath.dump() or "", "padbinds"))

#: This directory, as WSL sees it - the helpers below are run inside WSL through
#: interop, so they cannot be handed the Windows path this file was loaded from.
#: `wslpath -u` is asked instead of assuming the checkout is on C:.
WSL_DIR = padpath.to_wsl(padpath.RIG)

#: Offsets into padled.h's block. Hard-coded because Python cannot include the
#: header; the header lists them next to the struct and says APPEND ONLY, so a
#: version-1 shim and a version-2 reader still agree on everything below `coil`.
PADLED_MAGIC = coilmap.PADLED_MAGIC
#: `decoded` (12) is LED writes that landed. `skipped` (16) is frames that
#: LOOKED like indexed LED writes and did not fit any shape the shim decodes -
#: padled.h has counted it since version 1 and nothing has ever read it. It is
#: the difference between "the game is not lighting anything" and "the game is
#: lighting plenty and we are dropping it", which is the single question this
#: window could never answer about itself.
LED_DECODED_OFF, LED_SKIPPED_OFF = 12, 16
LED_HDR, LED_IDX = 20, 96
#: The coil half of the block is coilmap.py's, because ballfeed.py (item 21b)
#: needed the same numbers from inside WSL, where this file cannot be imported
#: at all - it needs tkinter and this WSL has none. Four copies of an offset
#: is how the rig's two worst drifts started.
COIL_OFF, COIL_N = coilmap.COIL_OFF, coilmap.COIL_N
LVL_OFF = coilmap.LVL_OFF            # last drive byte
COIL_GEN_OFF = coilmap.GEN_OFF
#: Version 3, the fade ring (padled.h): head counter then 96 entries of
#: (u32 guest ms, node, start, end, from, to, rise, fall, pad).
FADE_HEAD_OFF = COIL_GEN_OFF + 8
FADE_ENT_OFF, FADE_STRIDE, FADE_RING = FADE_HEAD_OFF + 4, 12, 96
PADLED_READ = FADE_ENT_OFF + FADE_RING * FADE_STRIDE

#: How long a coil marker stays lit after its fire counter moves. A coil pulse
#: is ~30 ms and a 50 ms poll would show it for one frame or miss it; this is a
#: readable flash, not a measurement. SHORTENED from 260 ms with the move off
#: the 50 ms poll: at 60 fps this is still eight frames of magenta, which is
#: comfortably visible, and it is twice as close to the real pulse - two
#: slingshot hits 150 ms apart now read as two flashes rather than one long one.
COIL_FLASH_MS = 130

#: The pulse length for SwitchDriver.pulse(), which a mouse click no longer
#: uses - a click is now a real press and release (REMAINING item 24), so its
#: length comes from the mouse. Kept for callers that genuinely want an event.
PRESS_MS = 150

#: THE TARGET. David's acceptance test said "at least 30 fps feedback on coil,
#: LED and switch state" and this sat at exactly 30 until 2026-08-07, when he
#: asked why not 60: nothing - the 3.4 ms read is a ~147 fps ceiling and the
#: draw is change-gated, so 60 costs ~25% of one core in blocking reads and
#: buys the tween below its full smoothness. The loop is PACED, not slept -
#: see Field.tick - and the rate it ACHIEVES is measured and printed in the
#: status bar. An unmeasured frame rate is how this window sat at an unknown
#: rate for weeks.
TARGET_FPS = 60
FRAME_MS = 1000.0 / TARGET_FPS

#: How far back the LED rate on the status bar looks. The picture changes a few
#: times a second, so a per-second count would read 2, 5, 0, 3 and be unusable,
#: and an EWMA over a sparse event is worse - it decays toward whatever the last
#: gap was. Counting the events inside a sliding window is the honest form: at
#: ~3 Hz this is ~10 events, which is enough for one decimal place and still
#: responds inside a few seconds when the rate really moves.
RATE_WIN_S = 3.0

#: How long a BASE-LAYER step takes on screen, in ms. The real boards snap on
#: a direct write - the smoothness of a real light show is the FADE layer, not
#: the base - so this is only enough smoothing to keep a step from popping,
#: and it came DOWN from 200 when the fade layer landed: 200 ms of smear on
#: every step read as lag, which David reported in exactly that word. 0 snaps,
#: the A/B control.
FADE_MS = float(os.environ.get("PAD_PF_FADE_MS", "80"))

#: Milliseconds per unit of an a2 fade's rate byte - THE ONE GUESS LEFT in the
#: fade layer, and it is a reader-side scale so it tunes live with no rebuild.
#: At 12: the common blink (rate 0x0a) has 120 ms legs, the BUILDING FIRE
#: ember (0x6d) burns for ~1.3 s, the flare (0x92) ~1.75 s - all plausible
#: against the real machine. The oracle that will pin it is Diagnostics ->
#: LED Tests (item 1d).
FADE_UNIT_MS = float(os.environ.get("PAD_PF_FADE_UNIT_MS", "12"))

#: Kept as the fallback pacing for the Schematic view, which draws nothing per
#: frame and has no reason to run at 30 Hz.
POLL_MS = 50

#: Read the switch block every Nth tick instead of every tick. It is a whole
#: extra round trip across the VM boundary (3.35 ms, measured) on top of the
#: LED read, so it is paced rather than run at the frame rate.
#:
#: ONE READ ANSWERS EVERY SWITCH, which is why this went from 4 Hz to 10 when
#: the trough display landed. The block is 808 bytes and a 9p round trip costs
#: what it costs regardless of how much of it is asked for (measured for the
#: coin door: 3.35 ms for 72 bytes, the same as the LED read's 1908) - so
#: reading the whole merged array for 256 switches costs exactly what reading
#: one byte for the coin door used to. 4 Hz was chosen for a switch a human
#: flips by hand twice an hour; a ball leaving the trough is not that, and at
#: 4 Hz a drain would show up a quarter of a second late. 10 Hz is 6 more
#: round trips a second than before - about 20 ms in every 1000 - and it is
#: what the two numbers in the status bar are measured against.
SW_HZ = float(os.environ.get("PAD_PF_SW_HZ", "10"))
SW_EVERY = max(1, int(round(TARGET_FPS / max(1.0, SW_HZ))))

#: Close with the run: once the emulator has been SEEN, this many consecutive
#: failed polls of the LED block means the run has been torn down (watch.sh
#: removes dump/padled on exit precisely so this can tell), and the window
#: closes itself instead of sitting around as "no emulator". ~2 s of misses
#: rather than one, because a read over \\wsl.localhost can fail transiently
#: while everything is fine - derived from the rate so the 2 s holds whatever
#: TARGET_FPS is (a fixed 40 quietly became 0.7 s when the loop went to 60).
#: A playfield started with no emulator at all never trips this - nothing was
#: seen, so there is nothing to close with.
GONE_POLLS = 2 * TARGET_FPS


def emu_gone(view, readable):
    """Track LED-block readability; True when a once-seen emulator has left."""
    if readable:
        view._seen_emu = True
        view._gone = 0
        return False
    if not getattr(view, "_seen_emu", False):
        return False
    view._gone = getattr(view, "_gone", 0) + 1
    return view._gone >= GONE_POLLS

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class SwitchDriver:
    """The ONE way this window drives a switch, and it is SERIAL on purpose.

    A click here used to be a fixed-length PULSE, which cannot play a ball
    device: holding the scoop needs the switch closed for as long as the mouse
    button is down (REMAINING item 24). So a press and a release are two
    separate actions now, and that is what makes the ordering matter.

    THE FAILURE THIS EXISTS TO PREVENT IS A STUCK SWITCH. Every action is a
    `wsl.exe` interop spawn costing ~200 ms, so a quick click queues the release
    while the press is still starting; on two threads the release can WIN, and
    the switch is then latched closed with nothing left to open it - a machine
    that looks broken and stays broken until the window is closed. One worker
    thread draining one FIFO makes press-before-release a property of the queue
    rather than of the scheduler. It also serialises DIFFERENT switches, which
    is a small cost (nobody holds two playfield switches with one mouse) for not
    having to reason about per-switch workers.

    A RELEASE IS NEVER DROPPED. It retries, and `release_all()` runs on window
    close, because the one outcome worse than a late release is none at all.

    THE SUBPROCESS IS DELIBERATE - see the module docstring. Writing padsw from
    Windows would race the guest mmap across the 9p boundary; ~200 ms of
    `wsl.exe` buys a path that is already proven, and a hold's LENGTH is set by
    the mouse, not by the latency. `PAD_SW_SRC=f` tags every edge as this window
    in the guest's `[sw]` log (padsw.h), which is what a replay needs.
    """

    def __init__(self):
        self.q = queue.Queue()
        self.held = set()                  # ids we have latched ON
        self.spinning = set()              # ids we have set RIPPING (item 26)
        self.last_ms = None                # last action's round trip, measured
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    # ---- what the views call ---------------------------------------------
    def press(self, sw_id):
        with self._lock:
            self.held.add(sw_id)
        self.q.put((sw_id, 1))

    def release(self, sw_id):
        with self._lock:
            self.held.discard(sw_id)
        self.q.put((sw_id, 0))

    def spin(self, sw_id, on):
        """Start or stop a RIP (item 26) - right-hold on a spinner.

        One flag in the block each way, exactly like a hold's press/release;
        the guest shim does the actual ripping by alternating the level it
        reports on each scan of that switch's node. Same serial queue, so a
        rip's stop cannot overtake its start and a fast right-click cannot
        leave a spinner ripping forever - the stuck-switch argument again.
        """
        with self._lock:
            if on:
                self.spinning.add(sw_id)
            else:
                self.spinning.discard(sw_id)
        self.q.put((sw_id, "spin1" if on else "spin0"))

    def release_all(self):
        """Open everything we still hold, and WAIT for it.

        On window close this is the last chance: a daemon worker dies with the
        process, so an unqueued release would simply never happen and the game
        would keep seeing a made switch until the next run rebuilt the block.
        A rip is the same shape: an unstopped spin flag outlives this window,
        so the spins are cleared here too.
        """
        with self._lock:
            ids = sorted(self.held)
            self.held.clear()
            spins = sorted(self.spinning)
            self.spinning.clear()
        for sw_id in ids:
            self.q.put((sw_id, 0))
        for sw_id in spins:
            self.q.put((sw_id, "spin0"))
        if ids or spins:
            self.q.join()

    def pulse(self, sw_id, ms=None):
        """A press and a release `ms` apart, for callers that want an event.

        Kept because a coil's switch and the plunge helper are events, not
        holds. Runs on the same queue so it cannot interleave with a hold.
        """
        self.q.put((sw_id, PRESS_MS if ms is None else ms))

    def run_script(self, script, *args):
        """A helper that is not a switch edge (plunge.py, coilact.py).

        Off the queue and on its own thread: these take seconds, and a hold's
        release must not wait behind one.
        """
        threading.Thread(target=wsl_run, args=(script,) + args,
                         daemon=True).start()

    # ---- the worker -------------------------------------------------------
    def _run(self):
        while True:
            sw_id, what = self.q.get()
            try:
                t0 = time.monotonic()
                if what in (0, 1):
                    ok = wsl_run("swhold.py", str(sw_id), str(what))
                    # A dropped RELEASE is a stuck switch; a dropped press is
                    # only a missed click. So retry the one that matters, once.
                    if ok is None and what == 0:
                        ok = wsl_run("swhold.py", str(sw_id), "0")
                elif what in ("spin0", "spin1"):
                    # item 26: the rip. Same shape as a hold - the stop is the
                    # edge that must not be lost, so it gets the same retry.
                    ok = wsl_run("swspin.py", str(sw_id), what[-1])
                    if ok is None and what == "spin0":
                        ok = wsl_run("swspin.py", str(sw_id), "0")
                else:
                    ok = wsl_run("swpoke.py", str(sw_id), str(what))
                self.last_ms = (time.monotonic() - t0) * 1000.0
                # PAD_PF_SWDEBUG=1 echoes every action WITH THE HELPER'S OWN
                # REPLY. swhold prints `id=53 was 0 -> 1`, which is the only
                # place the before-value is visible; a disagreement between
                # what this window asked for and what the block ended up
                # holding is otherwise invisible from either side.
                if SW_DEBUG:
                    out = (ok.stdout or b"").decode("utf8", "replace").strip()
                    print("[swdrv] %8.1f ms  id=%d -> %s   %s"
                          % (self.last_ms, sw_id, what,
                             out.replace("\n", " | ") if ok else "DID NOT RUN"),
                          flush=True)
            except Exception:                               # noqa: BLE001
                pass
            finally:
                self.q.task_done()


def wsl_run(script, *args):
    """Run one of the rig's switch helpers in WSL. None if it did not run.

    `env PAD_SW_SRC=f` rather than passing it in the environment: this is a
    Windows process calling into WSL, and a Windows variable does not cross that
    boundary without WSLENV. The tag is what makes a click here distinguishable
    from a keyboard press in the guest's `[sw]` log, which is what a replay needs
    (REMAINING item 16; padsw.h has the letters).

    PAD_SW_FILE is forwarded WHEN IT IS SET, and only then. padsw.py says the rig
    never sets it and that it is the only way to check any of this without a
    running game - which is exactly how this window's hold path was measured.
    """
    env = ["PAD_SW_SRC=f"]
    if os.environ.get("PAD_SW_FILE"):
        env.append("PAD_SW_FILE=%s" % os.environ["PAD_SW_FILE"])

    # THE BOUNDARY IS THE ONLY THING THAT DECIDES THIS, and it exists in exactly
    # one case: this window running as a WINDOWS process against a guest inside
    # WSL. On a Linux desktop, and when this file is run inside WSL itself, the
    # helper is on the same machine and is simply run - which also removes the
    # ~200 ms interop spawn that SwitchDriver's whole serialised queue exists to
    # cope with.
    if sys.platform == "win32":
        cmd = (["wsl.exe", "-e", "env"] + env
               + ["python3", "%s/%s" % (WSL_DIR, script)] + list(args))
    else:
        cmd = ["env"] + env + ["python3", os.path.join(HERE, script)] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
    except Exception:                                       # noqa: BLE001
        return None
    return r


def state_run(script, slot="quicksave", label=None):
    """Run savegame.sh / loadgame.sh, the item 13 save-state wrappers.

    NOT wsl_run, for two reasons that are both load-bearing: these are bash
    scripts, not python helpers, and they need ROOT (criu does), which from
    Windows is simply `wsl.exe -u root` - no password, no elevation. No
    HOME/PAD_ROOT juggling either: with a guest up both scripts self-locate
    from the guest's own /proc environ, which is the proven path.

    The timeout is generous because a load is a criu restore with the
    growing-file retry loop in it (~10-15 s measured), and a save writes a
    ~500 MB dump. Returns the CompletedProcess, or None if it did not run.

    NAME COLLISION, again: save_state() in this file is the WINDOW POSITION
    save. Everything in this feature says `state_run`/`run_state` instead.
    """
    extra = [label] if label else []
    if sys.platform == "win32":
        cmd = (["wsl.exe", "-u", "root", "-e", "bash",
                "%s/%s" % (WSL_DIR, script), slot] + extra)
    else:
        # The native-Linux path: run it plainly; without root the script's own
        # "needs root" line lands in the status bar, which is the honest hint.
        cmd = ["bash", os.path.join(HERE, script), slot] + extra
    try:
        return subprocess.run(cmd, capture_output=True, timeout=240,
                              creationflags=_CREATE_NO_WINDOW)
    except Exception:                                       # noqa: BLE001
        return None


def pick_scale(root, img_h, chrome=170):
    """Fit the artwork to the screen.

    A flat 2x is 1420 px tall and puts the flippers and the trough off the
    bottom of a 1080p screen with no way to reach them. PAD_PF_SCALE overrides.

    `chrome` is what the window needs AROUND the artwork: the title bar, the
    button row and the status bar. It was 130 and that was about 40 px short -
    measured on a 5120x1440 screen, the artwork claimed 1310 px, the window's
    client area was 1362, and the status bar did not fit. Being wrong in this
    direction costs a strip of artwork nobody looks at; being wrong the other
    way costs the only line of text the window prints about itself.

    STILL 170 AFTER THE BUTTON ROW WENT AWAY, AND THAT IS DELIBERATE - it was
    tried at 140 and MEASURED (REMAINING item 25). The row claimed ~30 px, so
    reclaiming it is arithmetic and it works: the artwork goes 1270 -> 1300 on
    a 5120x1440 screen with the status bar still fitting. What it also does is
    move every marker, and `_hit()` at a marker's own CENTRE resolves to
    whatever NEIGHBOUR happens to overlap there - a switch oval is unfilled, so
    a click in its middle never finds the switch itself. Diffed offline over 51
    switch and coil centres, 20 of them changed what a press lands on, and one
    was a real loss: the POP BUMPER coil centre stopped resolving to a switch
    and started resolving to an insert, i.e. a click there would do nothing.
    2.3% more artwork is not worth perturbing the hit test item 24 just
    stabilised. Reclaim it only with that diff re-run and clean.
    """
    env = os.environ.get("PAD_PF_SCALE")
    if env:
        try:
            return max(1.0, float(env))
        except ValueError:
            pass
    return max(1.0, (root.winfo_screenheight() - chrome) / float(img_h))


def _rows(path, at_least):
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) >= at_least:
                out.append(p)
    return out


#: Every device the title positions, and WHICH IMAGE the layout is drawn on.
#: Read once, from the text table rather than the ELF, so a card run - whose
#: binary lives on a mount this Windows process cannot reach - is no different
#: from an extracted one. devicexy.layout_image() owns the choice and says why
#: the literal "playfield" was never a safe filter.
DEV_ROWS = devicexy.read_table(os.path.join(TDIR or "", "device_xy.txt"))
LAYOUT_IMAGE = devicexy.layout_image(DEV_ROWS)


def layout_rows(kind):
    """The title's positioned devices of one class, on the layout image."""
    if not LAYOUT_IMAGE:
        return []
    return [r for r in DEV_ROWS
            if r["kind"] == kind and r["image"] == LAYOUT_IMAGE]


def load_switches():
    """Switch id -> position, from switch_xy.txt or derived here.

    switch_xy.txt is the built form (switchxy.py) and is preferred: it is what
    mktables writes and what every title with an extracted binary already has.

    ★ THE FALLBACK IS NOT A CONVENIENCE (item 50). switchxy.py filters on the
    literal image name `playfield`, so james_bond_60th_le - which calls the
    same image `Test/scaled_playfield` - produces an EMPTY join and no file at
    all, and 49 positioned switches were unreachable because of a string
    compare. Deriving here does the identical join (device-table position x
    live id, matched on the NAME, case-insensitively) from two files that are
    already on disk, so the title needs no rebuild and no run to become
    clickable. 49 of 49 join on Bond; 41/41, 60/60 and 57/57 on the three
    titles that also have the built file, which is what says the two paths
    agree.
    """
    rows = [dict(id=int(p[0]), node=int(p[1]), bit=int(p[2]),
                 name=" ".join(p[3:-2]), x=int(p[-2]), y=int(p[-1]))
            for p in _rows(os.path.join(TDIR, "switch_xy.txt"), 6)]
    if rows:
        return rows
    live = {r["name"].strip().upper(): r for r in load_switch_list()
            if r["name"] and r["name"] != "?"}
    if not live:
        return []
    for r in layout_rows("switch"):
        hit = live.get(r["name"].strip().upper())
        if hit:
            rows.append(dict(id=hit["id"], node=hit["node"], bit=hit["bit"],
                             name=r["name"], x=r["x"], y=r["y"]))
    return sorted(rows, key=lambda r: r["id"])


def load_leds():
    """The layout's LEDs: name, position, and the (node, index) on the wire.

    ★ READ FROM device_xy.txt RATHER THAN led_io.txt SINCE ITEM 50, and the
    reason is that led_io.txt cannot carry these rows at all on some titles.
    ledio.py writes only the four groups coilmap.GROUP_NODE can turn into a
    node, so a title whose playfield lamps sit in groups it does not know -
    Bond's are groups 8 and 9 - loses every one of them before the file is
    written. The device table has them, with their positions.

    `node` is therefore None for exactly those lamps: a POSITION is known and a
    WIRE ADDRESS is not. Drawn dark, and the tooltip says which of the two is
    missing rather than leaving a lamp that never lights unexplained. See the
    queue item on the group -> node map being one title's measurement.
    """
    out = []
    for r in layout_rows("led"):
        out.append(dict(node=GROUP_NODE.get(r["group"]), index=r["index"],
                        x=r["x"], y=r["y"], name=r["name"], group=r["group"]))
    return out


def load_led_names():
    """{(node, index): name} for every LED the title's table names, ANY image.

    THE SAME TABLE AS load_leds(), READ WITHOUT ITS ONE FILTER, and the
    omission is the point (item 50). load_leds() keeps only the layout image,
    because it feeds markers onto a picture. This feeds the swatch grid, which
    has no picture and so has no reason to drop a lamp for being on the topper
    or the cabinet front - on james_bond_60th_le that is 315 topper LEDs and 24
    backbox ones that the artwork view will never show.

    It is only ever a LOOKUP. The grid's ROSTER comes from the live ring, not
    from here, because four of the nine titles with tables on this machine
    carry `0 records` in device_xy.txt and would otherwise show an empty grid
    over a running light show.
    """
    out = {}
    for r in DEV_ROWS:
        if r["kind"] != "led":
            continue
        node = GROUP_NODE.get(r["group"])
        if node is not None:
            out[(node, r["index"])] = r["name"]
    return out


#: Insert marker geometry, in screen pixels. The old 3.5 px dot disappeared
#: into the artwork; the glow is what makes a lit insert readable from across
#: the room the way a real one is.
LED_R, LED_GLOW_R = 5.5, 11

#: How often an open window looks for a switch table it did not have when it
#: opened. See Field._pick_up_switches() for why it can appear mid-run.
SWITCH_POLL_S = 2.0


def split_channel(name):
    """('SHIELD LEFT', 'R') for 'SHIELD LEFT-R'; (name, 'W') for a plain insert."""
    if len(name) > 2 and name[-2] == "-" and name[-1] in "RGB":
        return name[:-2].rstrip(), name[-1]
    return name, "W"


def group_fixtures(leds):
    """Join led_io.txt's per-channel rows into one fixture per name stem.

    The device table wires an RGB insert as three channels with -R/-G/-B name
    stems, and channels of one fixture can sit at DIFFERENT XY in the table -
    that is correct data, not an error, so the join is by stem alone and the
    marker goes at the channels' mean position.
    """
    fixtures, order = {}, []
    for L in leds:
        stem, chan = split_channel(L["name"])
        f = fixtures.get(stem)
        if f is None:
            f = fixtures[stem] = dict(name=stem, channels={}, xs=[], ys=[])
            order.append(f)
        f["channels"][chan] = (L["node"], L["index"])
        f["xs"].append(L["x"])
        f["ys"].append(L["y"])
    for f in order:
        xs, ys = f.pop("xs"), f.pop("ys")
        f["x"] = sum(xs) / float(len(xs))
        f["y"] = sum(ys) / float(len(ys))
    return order


def fixture_color(vals):
    """(r, g, b), level for a fixture's channel values, or (None, 0) when off.

    TWO ANSWERS, NOT ONE, and the split is the whole point. The COLOUR is
    brightness-lifted hue-preservingly (sqrt, close enough to display gamma)
    so a dim insert still shows its real hue: the wire carries linear duty
    cycle, and drawing a 20%-duty insert at #33.. renders a clearly-lit lamp
    as nearly off. The LEVEL (0..1, the raw duty of the strongest channel) is
    returned ALONGSIDE it, because that is what the marker's size and its
    blend toward the artwork behind it are driven from - David asked for
    brightness shown by transparency AND size, and folding brightness into
    the colour is exactly what makes both of those impossible.

    Single-channel inserts keep the orange ramp the window has always used -
    the lens colour is not in any table, and the coil flash's "nothing else
    here is magenta" contrast depends on it.
    """
    if "W" in vals:
        v = vals.get("W") or 0
        if not v:
            return None, 0.0
        return (255, 60 + v * 3 // 4, 0), v / 255.0
    r, g, b = (vals.get(c) or 0 for c in "RGB")
    m = max(r, g, b)
    if not m:
        return None, 0.0
    k = 255.0 * (m / 255.0) ** 0.5 / m
    return ((min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k))),
            m / 255.0)


#: How a level (0..1) becomes a marker. Both floors are deliberate: a lamp at
#: 15% duty is ON and must read as on, so the dimmest marker is still 60% of
#: full size and 45% blended in, not a ghost. sqrt because the eye is not
#: linear and neither is the duty cycle.
def level_shape(level):
    """(radius scale, opacity) for a brightness level."""
    s = level ** 0.5
    return 0.60 + 0.40 * s, 0.45 + 0.55 * s


def blend(rgb, bg, alpha):
    """rgb over bg at alpha, as a Tk colour string.

    THE STAND-IN FOR ALPHA. Tk canvas items have no transparency at all - not
    a missing feature, there is nowhere to put it - and `stipple` gives four
    coarse levels of it at best. Blending toward the pixel that is actually
    behind the marker (sampled from the artwork once, at build time) is what
    gives smooth levels, and it is what a real translucent insert does.
    """
    return "#%02x%02x%02x" % tuple(
        min(255, max(0, int(c * alpha + b * (1.0 - alpha))))
        for c, b in zip(rgb, bg))


#: Device-table group -> node on the bus, the same lookup ledio.py verified
#: against the boot enumeration. coilmap.py owns it now; the alias stays so
#: nothing that reads this module has to know that.
GROUP_NODE = coilmap.GROUP_NODE


def load_coils():
    """The playfield's coils, parsed by coilmap.py.

    THE PARSE MOVED because ballfeed.py needs the same rows on the other side
    of the VM boundary and cannot import this file. What it does has not
    changed and coilmap.py keeps the reason it is written the way it is: the
    connector column is empty for every coil, so counting fields from the LEFT
    read `h` as the group for a whole release and every coil tooltip said
    "group 20 index 6".
    """
    return [c for c in coilmap.load(os.path.join(TDIR, "device_xy.txt"))
            if LAYOUT_IMAGE and c.get("image") == LAYOUT_IMAGE]


def load_switch_list():
    """switch_list.txt: id num node bit NAME...  (see swtable.py)

    The fallback, and the only thing available for most titles. It has no
    positions because most titles HAVE no positions: Godzilla Pro 1.15.0 ships a
    graphical device test mode with a playfield drawing and an XY record per
    device, and TMNT 1.59 ships neither - no images/Test directory, and the word
    "playfield" appears in its binary only in adjustment help text.

    THE PARSE ITSELF IS IN trough.py, because swshow.py needs the same file and
    cannot import this module (no tkinter inside WSL). One parser, two callers.
    """
    return trough.load_list(os.path.join(TDIR, "switch_list.txt"))


class Tip:
    """A tooltip that appears at once and follows the cursor.

    Tk's own `after`-delayed tooltips feel broken on a dense diagram - by the
    time one appears the cursor has moved on - so this shows immediately and is
    repositioned on every motion event.
    """

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.wm_overrideredirect(True)
        self.win.attributes("-topmost", True)
        # A Toplevel inherits the app title, so a screenshot tool matching on
        # "virtual playfield" grabs the TOOLTIP instead of the window. Name it.
        self.win.title("playfield tooltip")
        self.lbl = tk.Label(self.win, justify="left", bg="#ffffe0", fg="#000",
                            relief="solid", borderwidth=1,
                            font=("Consolas", 9), padx=5, pady=2)
        self.lbl.pack()
        self.win.withdraw()
        self.shown = False

    def show(self, text, x, y):
        self.lbl.config(text=text)
        self.win.geometry("+%d+%d" % (x + 16, y + 12))
        if not self.shown:
            self.win.deiconify()
            self.shown = True

    def hide(self):
        if self.shown:
            self.win.withdraw()
            self.shown = False


def read_merged():
    """The whole merged switch array - what the GAME is being handed - or None.

    ONE read, 256 answers. This replaces the single-byte coin-door read that
    used to happen here, and it costs the same: the expensive part is the 9p
    round trip, not the bytes (3.35 ms either way, measured 2026-08-05).

    THE FALLBACK TO THE KEYBOARD'S HALF IS DELIBERATE and is the coin door's
    old rule generalised. The merged array is written by the GUEST, so it is
    all zeros until the game is up and scanning switches - and all zeros reads
    as "coin door open, no balls anywhere", which is a window being wrong
    rather than a window being early. Until the shim has published once
    (mrg_gen still 0), the keyboard's array is the only truth there is, and it
    already carries padglhost's window-open latch: the door and a full trough.
    """
    try:
        with open(SW_PATH, "rb") as f:
            d = f.read(padsw.SIZE)
    except OSError:
        return None
    if len(d) < padsw.SIZE or struct.unpack_from("<I", d, 0)[0] != PADSW_MAGIC:
        return None
    off = (padsw.OFF_MRG if struct.unpack_from("<I", d, padsw.OFF_MRG_GEN)[0]
           else padsw.OFF_HELD)
    return d[off:off + padsw.MAX_ID]


class SwitchWatch:
    """The live switch state both views share: one paced read, then answers.

    Kept out of the views because the artwork window and the schematic ask the
    same three questions of the same bytes - is the coin door open, is this
    switch made, where are the balls - and the rig has been bitten twice by
    two readers of one fact drifting apart (alive.sh vs killgame.sh,
    autoattract.sh vs status.sh). One class, two callers.
    """

    def __init__(self, rows, every=None):
        self.mrg = None
        self.door = False
        self.balls = trough.Balls()
        self.positions, self.how = [], None
        self.set_rows(rows)
        # TICKS, NOT MILLISECONDS, because the two views run different loops:
        # the artwork window paces itself at TARGET_FPS and the schematic at
        # POLL_MS. Each passes the count that makes SW_HZ come out right for
        # its own loop, so "10 Hz" means 10 Hz in both windows.
        self.every = max(1, int(every or SW_EVERY))
        self._n = 1                 # tick countdown; first tick reads

    def set_rows(self, rows):
        """(Re-)identify the trough from a switch table.

        Called again when the table arrives mid-run: the game builds its
        switch list on the heap, so a first run of a title has no table for
        the first minute (Field._pick_up_switches), and a trough that could
        not be identified at window open usually can be a minute later.
        """
        self.positions, self.how = trough.find(rows)
        return bool(self.positions)

    def poll(self):
        """Re-read on the pacing above; True when this tick actually read."""
        self._n -= 1
        if self._n > 0:
            return False
        self._n = self.every
        self.mrg = read_merged()
        self.door = bool(self.mrg) and not self.mrg[SW_COIN_DOOR]
        self.balls.update(self.closed())
        return True

    def closed(self):
        """[bool] per trough position, in trough order."""
        return trough.closed(self.mrg, self.positions)

    def is_made(self, sw_id):
        """True/False for one switch, or None when nothing has been read."""
        if self.mrg is None or not 0 <= sw_id < len(self.mrg):
            return None
        return bool(self.mrg[sw_id])


class TroughPanel:
    """Six ball positions in trough order, drawn straight onto a canvas.

    THE NUMBERS UNDER THE BALLS ARE THE POINT, not decoration. The question
    David is asking - "are the trough switches correctly closed or open" - is
    about WHICH position is empty, because item 20 was a wrong-end bug that a
    count could never have shown. Position 1 is the eject end and is drawn
    first, so the row reads left to right in the direction a ball travels, and
    the caption says which end is which in words as well.

    NOTHING HERE GOES INTO `info`, and that is a promise about clicking rather
    than a detail. `Field._hit()` walks find_overlapping and returns the
    topmost item that is IN `self.info`; these items are not, so they are
    skipped exactly as the artwork image and the action buttons are. Item 24
    measured that a click at the centre of RIGHT SCOOP lands on the COIL
    marker rather than the switch, and coilact.py depends on it - a panel that
    joined the hit test could quietly change which device a click reaches.

    ★ THE BALLS ARE CLICKABLE, and that is why the promise above still holds:
    the binding is a per-ITEM `tag_bind` that returns "break", not a place in
    `info`, so the window's own hit test is untouched and a click on a ball
    never reaches it.

    WHY A CLICK HERE AND NOT ON THE TROUGH SWITCH ITSELF. David, 2026-08-11,
    mid-Mechagodzilla-Multiball: "how do i drain a ball? pressing one of the
    trough switches doesn't drain the ball. is there a way to just click on
    the ball indicators to add or remove it". Pressing the switch cannot work
    and never could: item 24's press-and-hold is MOMENTARY - it opens again on
    release - and a ball in a trough holds its switch closed for as long as it
    sits there. So a press is a ball that arrives and leaves, which the game
    correctly ignores. A ball is a LATCHED closure, and these six dots are the
    only place in the window that means "a ball is here" rather than "a switch
    is being pressed".

    THE STACK DECIDES WHICH SWITCH MOVES, NOT WHICH DOT WAS CLICKED, and that
    is deliberate rather than a shortcut. A trough is a ramp: balls sit
    contiguously from the eject end, so the only two things that can physically
    happen are "one more" and "one fewer". Clicking the third dot of four
    therefore removes a ball from the FAR end - the hole appears at position 4,
    which is exactly the geometry item 20 was a bug in and exactly what this
    panel was built to show. Honouring the clicked position instead would put
    a gap in the middle of the stack, which is a state no machine can be in
    and which ballmodel.Trough.anomaly() would then report as a fault.
    """

    R = 7                 # ball radius, screen px
    GAP = 5               # between balls
    PAD = 5               # inside the panel's own background
    #: The panel's own background, named because the per-ball hit pads have to
    #: be filled with EXACTLY it to stay invisible - two hard-coded copies of a
    #: colour is how a hit target becomes a visible grey square on one view.
    BG = "#101010"
    #: Room under the balls for the position numbers. 9 clipped their
    #: descenders against the panel edge (offline check, 2026-08-10) - the
    #: numbers are the part that makes the ORDER checkable, so they get room.
    NUM_H = 12

    def __init__(self, cv, positions, how, x, y, anchor="sw", on_ball=None,
                 label_below=False, wrap=0):
        self.cv = cv
        self.positions = positions
        self.how = how
        self.on_ball = on_ball
        self.label_below = label_below
        self.items = []
        self.balls = []
        self.drawn = []
        step = 2 * self.R + self.GAP
        w = self.PAD * 2 + step * len(positions) - self.GAP + 2
        h = self.PAD * 2 + 2 * self.R + self.NUM_H
        x0 = x if "w" in anchor else x - w
        y0 = y - h if "s" in anchor else y
        self.bg = cv.create_rectangle(x0, y0, x0 + w, y0 + h,
                                      fill=self.BG, outline="#3a3a3a")
        self.items.append(self.bg)
        cy = y0 + self.PAD + self.R
        for i, P in enumerate(positions):
            cx = x0 + self.PAD + self.R + i * step
            # ★ THE HIT TARGET IS THE WHOLE CELL, AND IT IS ITS OWN ITEM.
            # David, 2026-08-11: "when hovering over the circles, it's not
            # always indicating that i can click on it." The cause is a Tk
            # rule rather than a mis-binding: an item with `fill=""` is
            # hittable ONLY ON ITS OUTLINE, and an EMPTY position is drawn
            # hollow - so a ball with a ball in it was a 14 px disc and an
            # empty one was a 1 px ring. Exactly "not always".
            #
            # Filling the empty ones would fix the hover and lose the thing
            # the panel is for (hollow reads as no ball). So the target is a
            # rectangle covering the ball AND its number, filled with the
            # panel's own background so it is invisible, drawn BEFORE them so
            # it stays underneath. The cell is ~19x26 px instead of a ring.
            pad = cv.create_rectangle(cx - step / 2.0 + 1, y0 + 1,
                                      cx + step / 2.0 - 1, y0 + h - 1,
                                      fill=self.BG, outline="")
            self.items.append(pad)
            b = cv.create_oval(cx - self.R, cy - self.R, cx + self.R,
                               cy + self.R, fill="", outline="#666",
                               width=1)
            self.balls.append(b)
            self.drawn.append(None)
            self.items.append(b)
            num = cv.create_text(cx, y0 + h - self.PAD, anchor="s",
                                 fill="#8a8a8a", font=("Consolas", 7),
                                 text=str(P["pos"]))
            self.items.append(num)
            if on_ball is not None:
                # All three, because Enter/Leave fire per ITEM: crossing from
                # the pad onto the ball is a Leave and an Enter, and binding
                # only the pad would drop the cursor the moment the pointer
                # reached the thing it was aiming at.
                for it in (pad, b, num):
                    cv.tag_bind(it, "<Button-1>",
                                lambda e, i=i: self._click(i))
                    cv.tag_bind(it, "<Enter>",
                                lambda e: cv.configure(cursor="hand2"))
                    cv.tag_bind(it, "<Leave>",
                                lambda e: cv.configure(cursor=""))
        # The caption sits to the RIGHT of the balls rather than above them:
        # this panel is pinned to the bottom of the artwork and a line above
        # the balls would be the line closest to the playfield markers.
        # UNLESS label_below (item 39): on the key panel there is no room to
        # the right, so the caption wraps UNDER the balls at `wrap` px.
        if label_below:
            self.label = cv.create_text(x0 + 1, y0 + h + 4, anchor="nw",
                                        fill="#ddd", font=("Consolas", 8),
                                        text="", width=wrap or 0)
        else:
            self.label = cv.create_text(x0 + w + 6, cy, anchor="w", fill="#ddd",
                                        font=("Consolas", 8), text="")
        self.items.append(self.label)
        self._box = (x0, y0, x0 + w, y0 + h)
        self._text = None

    #: A ball is silver and unmistakably solid; an empty position is a hollow
    #: ring, not a dark ball, so "no ball here" cannot read as "a ball I drew
    #: badly". The colours are the only two states this panel has.
    BALL = ("#d8d8d8", "#ffffff")          # fill, outline - occupied
    EMPTY = ("", "#555555")                # fill, outline - open

    def _click(self, i):
        """A dot was clicked: one ball more, or one ball fewer.

        Reads the state this panel last DREW rather than asking anything, so
        the decision is the one the user could see when they clicked. Returns
        "break" so the click stops here and the window's hit test never runs -
        see the class docstring's promise about `info`.
        """
        occupied = bool(self.drawn[i]) if i < len(self.drawn) else False
        self.on_ball("take" if occupied else "drain")
        return "break"

    def update(self, flags, text):
        for i, on in enumerate(flags[:len(self.balls)]):
            if self.drawn[i] == on:
                continue
            self.drawn[i] = on
            fill, outline = self.BALL if on else self.EMPTY
            self.cv.itemconfig(self.balls[i], fill=fill, outline=outline)
        if text != self._text:
            self._text = text
            self.cv.itemconfig(self.label, text=text)
            # THE BACKGROUND GROWS TO COVER THE WORDS. This panel is drawn on
            # top of a WHITE line drawing, and grey text straight onto it is
            # unreadable - which is exactly how the first version came out
            # (offline check, 2026-08-10). The width is not known until Tk has
            # laid the text out, so it is asked for afterwards rather than
            # guessed at, and the rect was created first so it stays behind.
            # A label_below panel skips this: it only ever draws on the key
            # panel, whose background is already the readable dark.
            if not self.label_below:
                b = self.cv.bbox(self.label)
                x0, y0, x1, y1 = self._box
                if b:
                    x1 = max(x1, b[2] + 5)
                self.cv.coords(self.bg, x0, y0, x1, y1)

    def destroy(self):
        for i in self.items:
            self.cv.delete(i)
        self.items, self.balls, self.drawn = [], [], []


#: A made switch, drawn in the middle of its ring (artwork) or beside its row
#: (schematic).
#:
#: GREEN AND NOT THE PANEL'S SILVER, which was the first try and was invisible:
#: this artwork is a white line drawing, and a silver dot on it cannot be seen
#: at all (caught in the offline check, 2026-08-10, before it reached a run).
#: The panel keeps silver because it draws its balls on its own dark
#: background. Green also stays clear of the two colours already in use on the
#: picture - the coil marker's red and its magenta fire flash - and of the
#: orange insert ramp, so a made switch cannot be mistaken for a fired coil.
SW_MADE = "#00c853"


def poll_switches(view):
    """The paced switch read and everything that hangs off it, for both views.

    ONE FUNCTION RATHER THAN A METHOD ON EACH, because the artwork window and
    the schematic keep the same four things (`sw`, `sw_dots`, `_dot_drawn`,
    `trough_panel`) and this rig's standing rule is that two readers of one
    fact drift. Returns True when this tick actually read the block.

    Every draw is change-gated: a still machine costs the read and no canvas
    work at all.
    """
    if not view.sw.poll():
        return False
    for dot, sw_id in view.sw_dots:
        made = view.sw.is_made(sw_id)
        if view._dot_drawn.get(dot) == made:
            continue
        view._dot_drawn[dot] = made
        view.cv.itemconfig(dot, fill=SW_MADE if made else "")
    if view.trough_panel is not None:
        view.trough_panel.update(view.sw.closed(), trough_text(view.sw))
    # The key panel (item 39) rides the same read. It can be missing at
    # window open - padbinds is written by padglhost, which may be seconds
    # behind - so keep asking for it on the switch table's cadence.
    #
    # ★ ITEM 49: AND IT CAN CHANGE MID-RUN. On a title's first run padglhost
    # exports padbinds with the playfield rows withheld ('0': the switch
    # table has not arrived), then RE-exports the moment it has - so a panel
    # read once at construction would show dim dead keys for the rest of a
    # session whose keys came alive a minute in. Watch the file's mtime on
    # the same cadence and rebuild; tmp+rename on the writer's side means a
    # changed mtime is always a WHOLE new file.
    if time.monotonic() >= view._binds_next:
        view._binds_next = time.monotonic() + SWITCH_POLL_S
        if view.key_panel is None:
            view.key_panel = attach_key_panel(view)
            view._binds_mtime = _binds_mtime()
        else:
            m = _binds_mtime()
            if m != getattr(view, "_binds_mtime", None):
                view._binds_mtime = m
                if getattr(view, "keys", None) is not None:
                    view.keys.close()
                    view.keys = None
                # The trough panel lives inside the key panel's canvas and
                # dies with it; forget it BEFORE the destroy so
                # attach_key_panel does not touch a dead widget.
                view.trough_panel = None
                view.key_panel.cv.destroy()
                view.key_panel = attach_key_panel(view)
    if view.key_panel is not None:
        view.key_panel.update(view.sw)
    return True


def _binds_mtime():
    """padbinds' mtime, or None - the change signal for the key panel."""
    try:
        return os.path.getmtime(BINDS_PATH)
    except OSError:
        return None


def trough_text(watch):
    """The line beside a trough panel: the count, the balls out, which end.

    WHICH END IS SAID IN WORDS because the numbers alone do not settle it for
    someone who has not read item 20, and that item was precisely a wrong-end
    bug. "assumed" is said out loud for the same kind of reason: it IS a guess
    (trough.py's fallback shape), and the titles it fires on are the ones
    whose switch names are all `?`, where a wrong drawing has nothing on
    screen to contradict it.
    """
    if not watch.positions:
        return ""
    # "click a ball" is on the line because the control is INVISIBLE otherwise:
    # six small dots on a status strip do not look like buttons, and the thing
    # a user reaches for instead is the trough switch on the artwork, which
    # cannot work (a press is momentary; a ball is latched). David went looking
    # for exactly that during a multiball on 2026-08-11.
    txt = "%s   1 = eject end   click a ball: out / in" % watch.balls.text()
    return txt if watch.how == "named" else txt + "   (positions assumed)"


class KeyPanel:
    """The keyboard -> switches reference, docked beside the playfield.

    ★ ITEM 39. This IS the retired Controls window's content - David: "i do
    like the feedback and interface of the small switch window" - moved into
    this window so a run opens two windows instead of three. The rows come
    from dump/padbinds, which padglhost exports after resolving binds[] for
    the title (keybinds.py parses it), so which key does what still has
    exactly one home and it is still the C file.

    THE HIGHLIGHT IS SWITCH STATE, NOT KEY STATE, and that is an upgrade
    rather than a compromise. The old legend inverse-videoed a row off
    key_down[] - the X event, this side of everything that can go wrong. This
    panel reads the MERGED array (the same paced read the dots and the trough
    panel hang off), which is what the GAME is being handed - so a row lights
    when the game can see the press, whoever made it: a key, a click on the
    artwork, or a script. Item 17 exists because those two answers differ.

    KEYS WORK IN THIS WINDOW TOO (KeyInput + SwitchPipe): the same exported
    rows that draw this panel bind the window's keys, and the edges ride a
    persistent WSL helper instead of the ~80 ms-per-action spawn path, so a
    flipper key is playable from here. The game window keeps its own X
    keyboard exactly as before; the guest merges the two writers by last
    edge, which is the machinery item 7 built.

    ★ THE SERVICE BUTTONS ARE CLICKABLE, drawn as the coin-door cluster on the
    real machine (David's reference photo: green BACK, red -/+, black SELECT,
    "Press SELECT for SERVICE MENU"). Press-and-hold, exactly like a switch
    marker on the artwork - the mouse button's length IS the closure - through
    the same SwitchDriver, so the ~80 ms spawn cost is fine here: service
    navigation is not a flipper. The ids come from the exported rows, not from
    a second table. And the COIN DOOR is a click toggle, because on the real
    machine the door is a thing that stays where you put it: open kills 48V
    (the game says so on its own screen), close restores it.

    ★ ONE CONTROL PER ACTION, NOT A ROW AND A BUTTON (David: "we need to
    consolidate the keyboard inputs and the button inputs for the service
    buttons since it looks weird to have them duplicated. maybe put the
    keyboard inputs on or around the buttons somehow?"). The four service
    binds, the door and the trough latch do NOT appear in the key list; their
    key labels sit ON their widgets instead - under each service button, on
    the door bar, beside the BALLS header - in the same blue every other key
    wears, so the key column and the widgets read as one system.

    THE BALL CONTROLS LIVE HERE TOO (David: "move the ball controls to the
    right panel as well") - add_trough() puts the six clickable ball positions
    at the panel's bottom, and the view keeps pointing its `trough_panel` at
    whatever was built, so poll_switches() has one update path wherever the
    trough is drawn.
    """

    ROW_H = 17
    PAD = 10
    #: The panel's own colours. Background matches the window's bars (#111);
    #: the key column takes the schematic's node-header blue so "the thing you
    #: press" reads apart from "what it does" at a glance; the made highlight
    #: is the legend's inverse video, kept because its punch is the feedback
    #: David asked to keep.
    BG, KEY_FG, LAB_FG, DIM = "#111", "#7ecbff", "#d8d8d8", "#555"
    HIT_BG, HIT_FG = "#e8e8e8", "#000"

    #: The binds that are drawn as WIDGETS rather than list rows - the
    #: consolidation above. Labels, because that is the identity the export
    #: carries; the C table never renames its platform rows.
    SVC_ORDER = ("Service Back", "Service Minus", "Service Plus",
                 "Service Select")
    DOOR_LABEL = "Coin Door Closed"

    def __init__(self, parent, rows, drv):
        self.drv = drv
        f9 = tkfont.Font(family="Consolas", size=9)
        f9b = tkfont.Font(family="Consolas", size=9, weight="bold")
        f8 = tkfont.Font(family="Consolas", size=8)
        self._f8, self._f9, self._f9b = f8, f9, f9b
        self._svc_rows = {r["label"]: r for r in rows
                          if r["label"] in self.SVC_ORDER and r["ids"]}
        self._door_row = next((r for r in rows
                               if r["label"] == self.DOOR_LABEL and r["ids"]),
                              None)
        self._trough_row = next((r for r in rows
                                 if r["toggle"] and len(r["ids"]) > 1), None)
        widget_rows = (set(map(id, self._svc_rows.values()))
                       | {id(self._door_row), id(self._trough_row)})
        self.rows = [r for r in rows if id(r) not in widget_rows]
        keyw = max([f9b.measure("/".join(r["keys"])) for r in self.rows] + [30])
        labw = max([f9.measure(r["label"]) for r in self.rows] + [30])
        sufw = f9.measure("[off]")
        w = self.PAD + 10 + keyw + 10 + labw + 8 + sufw + self.PAD
        # The service cluster needs room for a key label under each button
        # ("Enter/KP Ent" is the widest); the list must not be what caps it.
        if self._svc_rows:
            need = max(f8.measure("/".join(r["keys"])) + 14
                       for r in self._svc_rows.values())
            w = max(w, 2 * self.PAD + 4 * max(need, 66))
        self._w = w
        # Two section headers at most (cabinet first in the file, playfield
        # after), a title line and a hint line under the rows.
        nhdr = len(set(r["cabinet"] for r in self.rows))
        h = 30 + nhdr * (self.ROW_H + 6) + len(self.rows) * self.ROW_H + 26
        self.cv = tk.Canvas(parent, width=w, height=h, bg=self.BG,
                            highlightthickness=0)
        self._items, self._drawn = [], []

        x_dot = self.PAD + 3
        x_key = self.PAD + 10 + keyw            # right edge of the key column
        x_lab = x_key + 10
        x_suf = w - self.PAD
        y = 20
        self.cv.create_text(self.PAD, y, anchor="w", fill=self.KEY_FG,
                            font=f9b, text="KEYBOARD")
        self.cv.create_text(x_suf, y, anchor="e", fill="#777", font=f8,
                            text="works here and in the game window")
        y += 8
        section = None
        for r in self.rows:
            if r["cabinet"] != section:
                section = r["cabinet"]
                y += 8
                self.cv.create_text(self.PAD, y + 4, anchor="w",
                                    fill="#8a8a8a", font=f8,
                                    text="CABINET" if section else "PLAYFIELD")
                y += self.ROW_H
            box = self.cv.create_rectangle(self.PAD - 4, y - 8, w - self.PAD + 4,
                                           y + 9, fill="", outline="")
            fg = self.DIM if r["na"] else None
            dot = self.cv.create_oval(x_dot - 3, y - 3 + 1, x_dot + 3, y + 3 + 1,
                                      fill="", outline="")
            key = self.cv.create_text(x_key, y + 1, anchor="e",
                                      fill=fg or self.KEY_FG, font=f9b,
                                      text="/".join(r["keys"]))
            lab = self.cv.create_text(x_lab, y + 1, anchor="w",
                                      fill=fg or self.LAB_FG, font=f9,
                                      text=r["label"])
            suf = self.cv.create_text(x_suf, y + 1, anchor="e",
                                      fill=self.DIM, font=f9,
                                      text="n/a" if r["na"] else "")
            self._items.append((box, dot, key, lab, suf))
            self._drawn.append(None)
            y += self.ROW_H
        self.cv.create_text(self.PAD, y + 10, anchor="w", fill="#777", font=f8,
                            text="green dot = switch made")
        y += 24

        # ---- THE SERVICE CLUSTER, drawn as the real coin-door panel -------
        # ONE control per action: each button wears its own key label in the
        # key column's blue, and these binds are NOT in the list above.
        self._svc_held = None
        self._svc_btns = []            # (oval, switch id, base ring colour)
        svc = [("Service Back", "BACK", "", "#1f9d4e", "#0d5c2a", "#dff5e6"),
               ("Service Minus", "< -", "-", "#d43535", "#7a1717", "#ffffff"),
               ("Service Plus", "+ >", "+", "#d43535", "#7a1717", "#ffffff"),
               ("Service Select", "SELECT", "", "#1c1c1c", "#777", "#d8d8d8")]
        if len(self._svc_rows) == 4:
            y += 12
            self.cv.create_text(self.PAD, y, anchor="w", fill="#8a8a8a",
                                font=f8, text="SERVICE  -  click and hold")
            y += 28
            step = (w - 2 * self.PAD) // 4
            r = 14
            for k, (lbl, sub, glyph, fill, ring, subfg) in enumerate(svc):
                row = self._svc_rows[lbl]
                cx = self.PAD + step // 2 + k * step
                btn = self.cv.create_oval(cx - r, y - r, cx + r, y + r,
                                          fill=fill, outline=ring, width=3)
                gly = self.cv.create_text(cx, y, fill="#fff", font=f9b,
                                          text=glyph)
                cap = self.cv.create_text(cx, y + r + 10, fill=subfg, font=f8,
                                          text=sub)
                keys = self.cv.create_text(cx, y + r + 22, fill=self.KEY_FG,
                                           font=f8,
                                           text="/".join(row["keys"]))
                for it in (btn, gly, cap, keys):
                    self.cv.tag_bind(it, "<ButtonPress-1>",
                                     lambda e, s=row["ids"][0], b=btn:
                                     self._svc_press(s, b))
                    self.cv.tag_bind(it, "<ButtonRelease-1>",
                                     lambda e: self._svc_release())
                self._svc_btns.append((btn, row["ids"][0], ring))
            y += r + 34
            self.cv.create_text(self.PAD, y, anchor="w", fill="#777", font=f8,
                                text="press SELECT for the service menu")
            y += 8

        # ---- THE COIN DOOR, a toggle because the real door STAYS ----------
        self._door_id = self._door_row["ids"][0] if self._door_row else None
        self.door_btn = self.door_txt = None
        self._door_drawn = None
        if self._door_id:
            y += 14
            self.door_btn = self.cv.create_rectangle(
                self.PAD - 4, y, w - self.PAD + 4, y + 26,
                fill="#1a2e1a", outline="#2e7d32", width=1)
            door_key = self.cv.create_text(
                self.PAD + 6, y + 13, anchor="w", fill=self.KEY_FG, font=f9b,
                text="/".join(self._door_row["keys"]))
            self.door_txt = self.cv.create_text(
                w // 2 + 6, y + 13, fill="#d8d8d8", font=f9,
                text="COIN DOOR  closed - 48V on")
            for it in (self.door_btn, self.door_txt, door_key):
                self.cv.tag_bind(it, "<Button-1>", lambda e: self._door_click())
            y += 30

        self._y = y
        self.cv.config(height=y + 12)
        self._last_sw = None
        self._svc_drawn = [None] * len(self._svc_btns)

    # ---- the service buttons: press-and-hold through the same driver ------
    def _svc_press(self, sw_id, btn):
        if self._svc_held is not None:
            return
        self._svc_held = (sw_id, btn)
        self.cv.itemconfig(btn, width=5)
        self.drv.press(sw_id)

    def _svc_release(self):
        """Open whatever the press closed - by what we HELD, the same rule as
        the artwork markers: the canvas freezes its current item for the
        length of a click, so the release lands here whatever is under the
        cursor by then."""
        if self._svc_held is None:
            return
        sw_id, btn = self._svc_held
        self._svc_held = None
        self.cv.itemconfig(btn, width=3)
        self.drv.release(sw_id)

    def _door_click(self):
        """Toggle off the last DRAWN state, the TroughPanel._click rule: the
        decision is the one the user could see when they clicked."""
        if self._door_id is None or self._last_sw is None:
            return
        if self._last_sw.is_made(self._door_id):
            self.drv.release(self._door_id)
        else:
            self.drv.press(self._door_id)

    def add_trough(self, positions, how, on_ball):
        """The ball controls, at the panel's bottom.

        Returns the TroughPanel; the caller stores it as its own
        `trough_panel`, so poll_switches() keeps ONE update path wherever the
        trough is drawn - panel or fallback strip, never both.
        """
        y = self._y + 14
        self.cv.create_text(self.PAD, y, anchor="w", fill="#8a8a8a",
                            font=self._f8, text="BALLS")
        if self._trough_row is not None:
            # The trough latch's key, worn here instead of a list row - the
            # same consolidation as the service buttons and the door.
            self.cv.create_text(self.PAD + 44, y, anchor="w",
                                fill=self.KEY_FG, font=self._f8,
                                text="/".join(self._trough_row["keys"])
                                     + " = all six in / out")
        y += 10
        t = TroughPanel(self.cv, positions, how, self.PAD - 4, y, anchor="nw",
                        on_ball=on_ball, label_below=True,
                        wrap=self._w - 2 * self.PAD)
        # Balls and numbers are ~40 px; the wrapped caption below runs to
        # three short lines.
        self._y = y + 40 + 40
        self.cv.config(height=self._y + 12)
        return t

    def update(self, sw):
        """Repaint rows whose switch state moved; a still machine costs the
        comparison and nothing else - the same change-gate as everything on
        this window."""
        self._last_sw = sw
        # The service buttons wear their made-state as a gold ring - the rows
        # that used to carry it are gone from the list, so the button is now
        # the one place that answers "did the game see that press".
        for k, (btn, sid, ring) in enumerate(self._svc_btns):
            made = bool(sw.is_made(sid))
            if self._svc_drawn[k] != made:
                self._svc_drawn[k] = made
                self.cv.itemconfig(btn, outline="#ffd400" if made else ring)
        if self._door_id is not None:
            closed = bool(sw.is_made(self._door_id))
            if self._door_drawn != closed:
                self._door_drawn = closed
                if closed:
                    self.cv.itemconfig(self.door_btn, fill="#1a2e1a",
                                       outline="#2e7d32")
                    self.cv.itemconfig(self.door_txt,
                                       text="COIN DOOR  closed - 48V on")
                else:
                    # Amber, not red: an open door is a legitimate state you
                    # chose, but the game will not fire a single coil while it
                    # lasts, and that is worth reading at a glance.
                    self.cv.itemconfig(self.door_btn, fill="#33270f",
                                       outline="#c07000")
                    self.cv.itemconfig(self.door_txt,
                                       text="COIN DOOR  OPEN - 48V off, "
                                            "coils dead")
        for i, r in enumerate(self.rows):
            if r["na"]:
                continue
            made = [bool(sw.is_made(sid)) for sid in r["ids"]]
            n = sum(made)
            if len(r["ids"]) > 1:
                state = (n == len(made), "%d/%d" % (n, len(made)))
            elif r["toggle"]:
                state = (n > 0, "[ON]" if n else "[off]")
            else:
                state = (n > 0, "")
            if self._drawn[i] == state:
                continue
            self._drawn[i] = state
            on, suffix = state
            box, dot, key, lab, suf = self._items[i]
            self.cv.itemconfig(box, fill=self.HIT_BG if on else "")
            self.cv.itemconfig(dot, fill=SW_MADE if n else "")
            self.cv.itemconfig(key, fill=self.HIT_FG if on else self.KEY_FG)
            self.cv.itemconfig(lab, fill=self.HIT_FG if on else self.LAB_FG)
            self.cv.itemconfig(suf, text=suffix,
                               fill=self.HIT_FG if on else self.DIM)


class SwitchPipe:
    """ONE persistent WSL helper for keyboard edges, instead of a spawn each.

    The proven SwitchDriver path costs an ~80-200 ms wsl.exe spawn per action
    (item 24 measured it), which is why this window never took keyboard input:
    a flipper through that is unplayable. swkeys.py holds the block open and
    reads "<id> <level>" lines, so a key edge costs a pipe write. The helper
    releases everything it still holds on EOF - the same stuck-switch guard
    as everywhere else - and a dead pipe fails the edge back to the caller,
    who falls back to the spawn path rather than eating the press.
    """

    def __init__(self):
        self._p = None
        self._failed = 0

    def _ensure(self):
        if self._p is not None and self._p.poll() is None:
            return True
        if self._failed >= 2:          # spawn broken twice: stop trying
            return False
        try:
            if sys.platform == "win32":
                cmd = ["wsl.exe", "-e", "python3", "%s/swkeys.py" % WSL_DIR]
            else:
                cmd = ["python3", os.path.join(HERE, "swkeys.py")]
            self._p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=_CREATE_NO_WINDOW)
            return True
        except Exception:                                   # noqa: BLE001
            self._failed += 1
            self._p = None
            return False

    def set(self, sw, val):
        """True when the edge went down the pipe; False = use the fallback."""
        if not self._ensure():
            return False
        try:
            self._p.stdin.write(b"%d %d\n" % (sw, val))
            self._p.stdin.flush()
            return True
        except Exception:                                   # noqa: BLE001
            self._failed += 1
            self._p = None
            return False

    def close(self):
        try:
            if self._p is not None and self._p.poll() is None:
                self._p.stdin.close()                # EOF = helper releases all
        except Exception:                                   # noqa: BLE001
            pass


class KeyInput:
    """Keyboard play with THIS window focused.

    ★ ITEM 39, DAVID: "the keyboard inputs are not working unless the
    emulator window is focused. it should work with the virtual playfield
    focused." The bindings come from the SAME exported rows the panel draws -
    one table, two windows that honour it - and the edges ride SwitchPipe,
    with the per-action spawn as the fallback.

    TWO TRAPS THIS ALREADY KNOWS ABOUT:
    * X auto-repeat arrives as Release-then-Press at the same instant, which
      naively makes a held flipper flutter (padglhost swallows the pair with
      XPeekEvent). Windows Tk repeats differ - repeated KeyPress, one real
      KeyRelease - but the container runs this window under X, so a release
      is committed only after a few ms with no matching press: the same
      swallow, spelled in `after`.
    * A key typed into a real text widget (the save-slot picker) must not
      fire a flipper - the handler drops events whose focus widget takes
      text input.
    """

    #: How long a release waits for the press that would mark it auto-repeat.
    REPEAT_MS = 10

    def __init__(self, view, rows):
        self.view = view
        self.pipe = SwitchPipe()
        self.map = {}
        for r in rows:
            if r["na"] or not r["ids"]:
                continue
            for k in r["keys"]:
                for sym in keybinds.tk_keysyms(k):
                    self.map[sym] = r
        self.down = set()
        self._pending = {}             # keysym -> after id, releases in flight
        # Pre-warm the helper: spawned lazily, the FIRST press of a session
        # pays the ~90-200 ms wsl.exe start (measured live: a 2000 ms hold
        # reached the guest as 1907 ms, the whole shortfall on the press
        # side). Spawning now moves that cost to window open, where nobody
        # is holding a flipper.
        self.pipe._ensure()
        view.root.bind("<KeyPress>", self._on_down)
        view.root.bind("<KeyRelease>", self._on_up)

    def _row(self, ev):
        try:
            if ev.widget.winfo_class() in ("Entry", "TEntry", "TCombobox",
                                           "Text", "Spinbox", "TSpinbox"):
                return None
        except Exception:                                   # noqa: BLE001
            pass
        return self.map.get(ev.keysym)

    def _on_down(self, ev):
        r = self._row(ev)
        if r is None:
            return
        pend = self._pending.pop(ev.keysym, None)
        if pend is not None:
            self.view.root.after_cancel(pend)   # auto-repeat pair: still held
            return
        if ev.keysym in self.down:
            return                              # Windows-style repeat
        self.down.add(ev.keysym)
        if r["toggle"]:
            # The toggle flips off the MERGED state - the same rule as the
            # door button: the state acted on is the one on screen.
            target = 0 if all(bool(self.view.sw.is_made(s))
                              for s in r["ids"]) else 1
            for s in r["ids"]:
                self._set(s, target)
        else:
            self._set(r["ids"][0], 1)

    def _on_up(self, ev):
        r = self._row(ev)
        if r is None or r["toggle"]:
            self.down.discard(ev.keysym)
            return
        if ev.keysym in self._pending:
            return
        self._pending[ev.keysym] = self.view.root.after(
            self.REPEAT_MS, lambda: self._commit_up(ev.keysym, r))

    def _commit_up(self, keysym, r):
        self._pending.pop(keysym, None)
        self.down.discard(keysym)
        self._set(r["ids"][0], 0)

    def _set(self, sw, val):
        if not self.pipe.set(sw, val):
            (self.view.drv.press if val else self.view.drv.release)(sw)

    def close(self):
        self.pipe.close()


def attach_key_panel(view):
    """The panel, packed to the right of the view's canvas, or None.

    None is the NORMAL state for the first seconds of a session: watch.sh
    clears dump/padbinds at start and padglhost rewrites it once it is up, so
    a window that opened first has nothing to read yet. poll_switches() keeps
    asking on the same cadence the switch table uses, and the panel appears
    when the file does - the same late-arrival shape as _pick_up_switches().

    THE BALL CONTROLS MOVE IN WITH IT. A trough drawn before the panel
    existed - the artwork corner, or the schematic's old strip - is destroyed
    and rebuilt at the panel's bottom, so there is never a moment with two
    trough displays disagreeing about where the balls are.
    """
    rows = keybinds.load(BINDS_PATH)
    if not rows:
        return None
    panel = KeyPanel(view.root, rows, view.drv)
    panel.cv.pack(side="right", fill="y", before=view.cv)
    if view.trough_panel is not None:
        view.trough_panel.destroy()
        view.trough_panel = None
    strip = getattr(view, "_trough_strip", None)
    if strip is not None:
        strip.destroy()
        view._trough_strip = None
    if view.sw.positions:
        view.trough_panel = panel.add_trough(view.sw.positions, view.sw.how,
                                             view.run_plunge)
    # The keyboard arrives with the rows (item 39): the same table that drew
    # the panel binds this window's keys, so the two can never disagree.
    view.keys = KeyInput(view, rows)
    return panel


def state_slots():
    """slots.sh list, parsed: {slot: label} for THIS GAME's existing slots.

    Root for the same reason state_run is - savegame.sh writes slots as
    root, so reading their metadata and sizes needs it too. Best-effort:
    a wedged WSL returns {} and the picker just shows every slot as empty,
    which a save into it corrects.

    ★ ITEM 39, in two steps. David first caught the picker offering OTHER
    games' saves as this game's (the parse dropped the game field - a Save
    would have overwritten another title's slot), then asked the real
    question: "i thought we had 10 slots per game?" Slots are now stored
    per game (saves/<game>/<slot>, slots.sh migrates the old flat layout on
    sight), so this filters to GAME and the ten slots the picker shows are
    genuinely this title's ten. The keys stay bare slot names because that
    is what savegame.sh/loadgame.sh take - they resolve the game from the
    running guest themselves."""
    if sys.platform == "win32":
        cmd = ["wsl.exe", "-u", "root", "-e", "bash",
               "%s/slots.sh" % WSL_DIR, "list"]
    else:
        cmd = ["bash", os.path.join(HERE, "slots.sh"), "list"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
    except Exception:                                       # noqa: BLE001
        return {}
    out = {}
    for ln in (r.stdout or b"").decode("utf8", "replace").splitlines():
        p = ln.split("|")
        if len(p) >= 6 and p[0] == "slot" and p[3] == GAME:
            out[p[1].rsplit("/", 1)[-1]] = p[4]
    return out


class StateOps:
    """Save state / Load state (item 13), shared by BOTH views - a title with
    no artwork still saves and loads, because savegame.sh/loadgame.sh know
    nothing about drawings. Each view calls `_build_state_widgets()` and
    places the returned picker + buttons in its own layout (Field: canvas
    windows bottom-left; Schematic: the top bar) and wires `_state_status()`
    into its own tick's status writes. Nothing is built at all when the boot
    is not checkpointable (module flag SAVESTATES).

    TEN SLOTS, NAMED. The picker lists slot1..slot10 with each slot's label
    (or "(empty)"); Save asks for a name first and passes it to savegame.sh,
    which stores it IN the slot - so names survive sessions and machines and
    the app's own slot manager shows the same truth."""

    SLOT_IDS = ["slot%d" % i for i in range(1, 11)]

    #: What a label may contain. The label crosses wsl.exe's re-parse on its
    #: way into bash argv, and wsl.exe expands $ and backticks even in -e
    #: argv (the executor lesson this repo already paid for) - so the dialog
    #: simply never lets those characters exist.
    _LABEL_OK = ("abcdefghijklmnopqrstuvwxyz"
                 "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.()!-")

    def _build_state_widgets(self, parent, compact=False):
        """The slot picker and the two buttons, for a view to place.

        ``compact`` is the artwork view's shape: its cluster shares the
        bottom edge with Start/Plunge/Reset, and the full-width version
        CROWDED them into each other on a scaled-down window (tester
        screenshot, 2026-08-10). Short labels and a narrower picker keep
        the two clusters apart; the slot names still read in full in the
        picker's dropdown, and the picker right beside Save/Load is what
        keeps the short labels unambiguous. The Schematic bar has the
        room, so it keeps the full labels."""
        self._slot_labels = {}
        self._slot_box = ttk.Combobox(parent, width=12 if compact else 17,
                                      state="readonly",
                                      values=self._slot_values())
        self._slot_box.current(0)
        save_txt, load_txt, bw = (("Save", "Load", 6) if compact
                                  else ("Save state", "Load state", 11))
        self._state_btns = [
            tk.Button(parent, text=save_txt, width=bw,
                      command=self._save_clicked),
            tk.Button(parent, text=load_txt, width=bw,
                      command=self._load_clicked),
        ]
        self._slots_refresh()
        return [self._slot_box] + self._state_btns

    def _slot_values(self):
        """One line per slot. Every slot listed is THIS game's now (slots
        are stored per game and state_slots filters), so ten slots means
        ten of this title's slots - the "1 · [godzilla_pro]" foreign-slot
        marking this method briefly carried is gone with the shared
        namespace that made it necessary."""
        vals = []
        for i, sid in enumerate(self.SLOT_IDS):
            label = getattr(self, "_slot_labels", {}).get(sid)
            if label is None:
                vals.append("%d · (empty)" % (i + 1))
            else:
                vals.append("%d · %s" % (i + 1, label or "unnamed"))
        return vals

    def _current_slot(self):
        try:
            return self.SLOT_IDS[self._slot_box.current()]
        except (ValueError, IndexError, tk.TclError):
            return self.SLOT_IDS[0]

    def _slots_refresh(self, pick_first_empty=False):
        """Re-read the slots off the rig, on a worker thread."""
        def work():
            info = state_slots()

            def apply():
                try:
                    keep = self._slot_box.current()
                    self._slot_labels = {s: info[s] for s in info}
                    self._slot_box.configure(values=self._slot_values())
                    if pick_first_empty:
                        empty = [i for i, sid in enumerate(self.SLOT_IDS)
                                 if sid not in self._slot_labels]
                        self._slot_box.current(empty[0] if empty else 0)
                    elif 0 <= keep < len(self.SLOT_IDS):
                        self._slot_box.current(keep)
                except tk.TclError:
                    pass          # window torn down while we were reading
            # The slot box's after(), NOT self.cv's: Schematic builds its bar
            # (and these widgets) before its canvas exists, and the worker
            # can finish inside that gap.
            try:
                self._slot_box.after(0, apply)
            except (tk.TclError, RuntimeError):
                pass          # window (or the whole interp) is gone

        threading.Thread(target=work, daemon=True).start()

    def _save_clicked(self):
        """Ask for a name, then save. The dialog is the naming surface David
        asked for; empty keeps the slot unnamed, Escape/Cancel aborts."""
        slot = self._current_slot()
        top = self.cv.winfo_toplevel()
        dlg = tk.Toplevel(top)
        dlg.title("Save state")
        dlg.transient(top)
        dlg.resizable(False, False)
        n = self.SLOT_IDS.index(slot) + 1
        tk.Label(dlg, text="Save to slot %d - name (optional):" % n,
                 anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        var = tk.StringVar(value=self._slot_labels.get(slot) or "")
        ent = tk.Entry(dlg, textvariable=var, width=34)
        ent.pack(padx=10, pady=2)
        row = tk.Frame(dlg)
        row.pack(pady=(6, 10))

        def go(_e=None):
            label = "".join(ch for ch in var.get() if ch in self._LABEL_OK)
            label = label.strip()[:40]
            dlg.destroy()
            self.run_state("savegame.sh", slot, label or None)

        tk.Button(row, text="Save", width=9, command=go).pack(side="left",
                                                              padx=4)
        tk.Button(row, text="Cancel", width=9,
                  command=dlg.destroy).pack(side="left", padx=4)
        ent.bind("<Return>", go)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        ent.focus_set()
        # Centre over the parent - a dialog at 0,0 on a big desktop is lost.
        dlg.update_idletasks()
        dlg.geometry("+%d+%d" % (
            top.winfo_rootx() + (top.winfo_width() - dlg.winfo_reqwidth()) // 2,
            top.winfo_rooty() + 120))
        dlg.grab_set()

    def _load_clicked(self):
        slot = self._current_slot()
        if slot not in getattr(self, "_slot_labels", {}):
            n = self.SLOT_IDS.index(slot) + 1
            self._state_msg = ("slot %d is empty - nothing to load" % n,
                               time.monotonic() + 5.0)
            return
        self.run_state("loadgame.sh", slot)

    def run_state(self, script, slot, label=None):
        """One at a time, off the Tk thread.

        The spawn takes seconds (a save dumps ~500 MB; a load is a criu
        restore), so it runs on its own thread with both buttons disabled -
        NOT on SwitchDriver's queue, where it would block a held flipper's
        release behind a 10 s restore. Tk is only ever touched back on the Tk
        thread via after(), which is the cross-thread rule this repo has paid
        for before (the Partition Explorer lockup).
        """
        if getattr(self, "_state_busy", False):
            return
        self._state_busy = True
        for b in self._state_btns:
            b.config(state="disabled")
        verb = "saving" if script.startswith("save") else "loading"
        self._state_msg = ("%s state..." % verb, None)

        def work():
            r = state_run(script, slot, label)

            def done():
                self._state_busy = False
                for b in self._state_btns:
                    b.config(state="normal")
                # The wrappers' own last tagged line is the best one-line
                # answer ("saved to slot...", "this run is not
                # checkpointable..."), and a bare "FAILED" is the WORST one -
                # David's first real button press showed exactly
                # "[savegame] FAILED" while the criu reason sat one line
                # above it. So prefer the last tagged line that says
                # something, and fall back down the ladder from there.
                if r is None:
                    text = "%s did not run" % script
                else:
                    lines = [ln.strip() for ln in
                             (r.stdout or b"").decode("utf8", "replace").splitlines()
                             + (r.stderr or b"").decode("utf8", "replace").splitlines()
                             if ln.strip()]
                    tagged = [ln for ln in lines
                              if ln.startswith(("[savegame]", "[loadgame]",
                                                "[save]", "[restore]",
                                                "savegame:", "loadgame:"))]
                    saying = [ln for ln in tagged
                              if not ln.rstrip().endswith("FAILED")]
                    text = (saying or tagged or lines
                            or ["%s: no output" % script])[-1]
                self._state_msg = (text, time.monotonic() + 8.0)
                # The picker's labels just changed (a save filled or renamed
                # a slot); show the new truth without a manual refresh.
                self._slots_refresh()

            self.cv.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _state_status(self):
        """The status-bar override while a save/load runs, and its result for
        a few seconds after - both ticks rewrite the bar every pass, so a
        plain config() here would survive for one frame at most. Reads its
        OWN monotonic clock: Field's tick t0 is perf_counter, a different
        epoch from the monotonic stamp `until` carries."""
        m = getattr(self, "_state_msg", None)
        if not m:
            return None
        text, until = m
        if until is not None and time.monotonic() > until:
            self._state_msg = None
            return None
        return text


#: What a fixture blends toward when there is no artwork behind it, and the
#: canvas colour that has to match it. See Field._sample().
NO_ART_BG = (16, 16, 16)

#: Space left around the devices when the layout is drawn WITHOUT artwork. The
#: art normally supplies its own margin (a playfield drawing runs to the
#: cabinet rails); an extent computed from marker centres alone would clip
#: every edge device in half.
NO_ART_PAD = 14


def layout_extent(pad=NO_ART_PAD):
    """(w, h) big enough to hold every positioned device, or None if there are
    none. In the LAYOUT's own pixels, i.e. the same space the artwork uses.

    `pad` IS FOR THE BLANK FIELD AND MUST BE 0 WHEN JUDGING ARTWORK. Comparing
    a picture against the PADDED extent is a size check the real artwork fails:
    Godzilla's devices reach x=301 inside a 313-wide drawing, and 301+14 does
    not fit, so both it and Jaws refused their own correct art the first time
    this was written.
    """
    pts = [(r["x"], r["y"]) for kind in ("led", "switch", "coil")
           for r in layout_rows(kind)]
    if not pts:
        return None
    return (max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)


def layout_art():
    """The artwork to draw the layout on, or None to draw on a blank field.

    ★ THE ARTWORK IS ONLY ACCEPTED IF IT CONTAINS THE COORDINATES (item 50).
    The image NAME in the device table and the name of the png beside the
    tables are found by two unrelated pieces of code - the table carries
    `Test/scaled_playfield`, gameinfo picks a file by token match - so nothing
    guarantees the picture that turns up is the one the positions were authored
    against. Drawing on a mismatched image is the failure devicexy.py records
    having shipped once: every marker plausible, every marker wrong.

    A size check is not proof they are the same picture, but it is a cheap
    refutation of the case that actually happens, and it fails SAFE - a title
    whose art is refused still gets its layout, on a blank field, which is what
    David asked for ("even if we can't show the playfield artwork").
    """
    if not PF_PNG or not os.path.exists(PF_PNG):
        return None
    ext = layout_extent(pad=0)
    wh = gameinfo.png_size(PF_PNG)
    if not ext or not wh:
        return None
    return PF_PNG if wh[0] >= ext[0] and wh[1] >= ext[1] else None


class LedRing:
    """Reading the live LED block: the base layer and the a2 pulse layer.

    MOVED OUT OF Field VERBATIM (item 50) so the swatch grid can read the ring
    the same way the artwork view does. Two views decoding one wire format is
    exactly the drift this rig has been bitten by twice - alive.sh against
    killgame.sh, autoattract.sh against status.sh - and the fade layer is the
    half most worth stating once: a pulse is an OVERLAY whose level is computed
    from a running envelope, and a second implementation of that would agree
    with this one only until one of them was tuned.

    A user needs `self.overlay` ({} ) and `self._fade_seen` (None) before the
    first read; _init_ring() is the one line that does it.
    """

    def _init_ring(self):
        # overlay maps a channel (node, idx) to its running pulse envelope;
        # while one is active the channel's level comes from the envelope, not
        # from val[]. _fade_seen is the ring head already consumed - primed on
        # the FIRST read so a window opened mid-run does not replay a backlog
        # of old pulses.
        self.overlay = {}
        self._fade_seen = None

    def _take_fades(self, d, now):
        """Consume new fade-ring entries into channel envelopes. Returns how
        many arrived - each is ONE picture update for the rate fields, however
        many frames its animation spans."""
        if len(d) < FADE_ENT_OFF or struct.unpack_from("<I", d, 4)[0] < 3:
            return 0
        head = struct.unpack_from("<I", d, FADE_HEAD_OFF)[0]
        if self._fade_seen is None:
            self._fade_seen = head          # opened mid-run: skip the backlog
            return 0
        new = head - self._fade_seen
        if new <= 0:
            return 0
        # A reader further than a full ring behind lost the oldest entries;
        # take the survivors rather than replaying slots twice.
        first = head - min(new, FADE_RING)
        for n in range(first, head):
            off = FADE_ENT_OFF + (n % FADE_RING) * FADE_STRIDE
            if off + FADE_STRIDE > len(d):
                break
            _ms, node, s, e, frm, to, rise, fall, _pad = struct.unpack_from(
                "<I8B", d, off)
            # The slot for the direction of travel takes the pulse out; the
            # OTHER slot brings it home. 0 = instantly (padled.h).
            out_r, back_r = (rise, fall) if to >= frm else (fall, rise)
            env = dict(t0=now, frm=frm, to=to,
                       out_s=out_r * FADE_UNIT_MS / 1000.0,
                       back_s=back_r * FADE_UNIT_MS / 1000.0)
            if env["out_s"] <= 0 and env["back_s"] <= 0:
                continue                    # degenerate: nothing visible
            for i in range(s, e + 1):
                self.overlay[(node, i)] = env
        self._fade_seen = head
        return new

    def _env_level(self, env, now):
        """The envelope's level right now, or None once it has expired."""
        t = now - env["t0"]
        if t < env["out_s"]:
            k = t / env["out_s"]
            return env["frm"] + (env["to"] - env["frm"]) * k
        t -= env["out_s"]
        if t < env["back_s"]:
            k = t / env["back_s"]
            return env["to"] + (env["frm"] - env["to"]) * k
        return None

    def _chan_vals(self, F, d, now=None):
        """Live channel values for a fixture, e.g. {'R': 255, 'G': 40, 'B': 0}.
        A channel with no readable byte reports None (distinct from 0 = off).
        An active fade envelope OVERRIDES the base byte for its channel - the
        pulse layer draws on top of the picture, exactly as on the wire."""
        out = {}
        env_on = False
        for chan, (node, idx) in F["channels"].items():
            v = None
            # node is None for a lamp the table POSITIONS but whose group the
            # group -> node map cannot address (item 50). It stays at None,
            # which is already this function's word for "no readable byte" and
            # is drawn dark - as distinct from 0, which means the game turned
            # it off.
            if d and node is not None:
                off = LED_HDR + node * LED_IDX + idx
                if off < len(d):
                    v = d[off]
            if now is not None:
                env = self.overlay.get((node, idx))
                if env is not None:
                    lv = self._env_level(env, now)
                    if lv is None:
                        del self.overlay[(node, idx)]
                    else:
                        v = int(lv)
                        env_on = True
            out[chan] = v
        F["env"] = env_on
        return out


class Field(StateOps, LedRing):
    def __init__(self, root):
        from PIL import Image, ImageTk
        self.root = root
        self.switches = load_switches()
        self.leds = load_leds()
        self.coils = load_coils()
        self.last = None

        # ARTWORK IF IT FITS THE COORDINATES, A BLANK FIELD OTHERWISE. Both
        # draw the same markers in the same places; the picture behind them is
        # the only difference, and a title without one is no longer pushed all
        # the way down to the switch list (item 50).
        art = layout_art()
        img = Image.open(art).convert("RGB") if art else None
        base = (img.width, img.height) if img else layout_extent()
        self.scale = pick_scale(root, base[1])
        w, h = int(base[0] * self.scale), int(base[1] * self.scale)
        # KEPT, not discarded after the PhotoImage is made: each fixture blends
        # toward the pixel that is actually behind it (see blend()), and that
        # pixel has to be sampled from somewhere. Sampled once at build time,
        # never during a tick. None with no artwork, and _sample() answers the
        # flat background instead.
        self._art = img.resize((w, h), Image.LANCZOS) if img else None
        self.bg = ImageTk.PhotoImage(self._art) if self._art else None

        # THE STATUS BAR IS PACKED FIRST, AND side="bottom", AND THAT IS A FIX
        # RATHER THAN A STYLE CHOICE. Packed after the canvas it is last in
        # line for space, and the canvas is sized from the ARTWORK: on David's
        # 5120x1440 screen the sum came to about 2 px more than the window had,
        # so Tk simply did not show the label at all. Everything this window
        # reports about itself - inserts lit, LED writes decoded, frames not
        # decoded, the frame rate - lives in that label, so the one part that
        # says whether the thing is working was invisible on the machine it was
        # built for. Claiming space before the canvas cannot go wrong that way.
        #
        # width=1 SO THE TEXT CAN NEVER SIZE THE WINDOW. A Label asks for the
        # width of its text, the window is the max of its children's asks, and
        # the bar's text changes width as its counters grow - so the whole
        # window widened and narrowed with the wording, which David saw the day
        # the two-rate bar shipped. One nominal character keeps its ask below
        # the canvas's always; fill="x" then stretches it to the artwork's
        # width, and text longer than that clips at the right instead of
        # resizing the playfield.
        self.status = tk.Label(root, text="", anchor="w", bg="#111", fg="#ddd",
                               font=("Consolas", 9), width=1)
        self.status.pack(side="bottom", fill="x")
        # side="left", NOT "top" (item 39): the key panel docks on the RIGHT -
        # the playfield is tall and screens are wide, so the horizontal space
        # is the free direction - and a side="top" canvas would centre itself
        # over the panel's column when the window is stretched.
        self.cv = tk.Canvas(root, width=w, height=h, highlightthickness=0,
                            bg="black" if self.bg
                               else "#%02x%02x%02x" % NO_ART_BG)
        self.cv.pack(side="left")
        if self.bg is not None:
            self.cv.create_image(0, 0, anchor="nw", image=self.bg)
        # ★ ITEM 39: the key panel attaches AFTER SwitchDriver exists, below -
        # its service buttons and door toggle press through the same driver
        # the artwork markers use.
        self.key_panel, self.keys = None, None

        self.info = {}          # canvas item -> dict describing it
        self.fixtures = group_fixtures(self.leds)
        self.coil_items = {}    # (node, index) -> canvas item
        self.coil_seen = {}     # (node, index) -> last fire counter read
        self.coil_until = {}    # (node, index) -> ms after which the flash ends
        self.coil_drawn = {}    # (node, index) -> last hot/cold drawn
        self.fps = 0.0          # measured, EWMA, shown in the status bar
        self._t_last = None
        self._read_ms = 0.0     # last tick's transport cost, for PAD_PF_LOG
        self._redrawn = 0       # fixtures actually reconfigured since the log
        self._log_t, self._log_n = time.perf_counter(), 0
        # THE TWO RATES BEHIND THE STATUS BAR (see the module docstring). Both
        # are deques of the tick times at which the thing happened, trimmed to
        # RATE_WIN_S - a count over a window rather than a smoothed number,
        # because these events are sparse and an EWMA of a sparse event reports
        # the last gap rather than the rate.
        self._draw_ev = collections.deque()   # ticks that changed the picture
        self._data_ev = collections.deque()   # ticks that read a moved counter
        self._decoded = None                  # last `decoded` seen, to diff it
        self._gap_worst = 0.0                 # longest still stretch, for the log
        self._draw_last = None
        # THE FADE LAYER (padled.h version 3), shared with the swatch grid -
        # see LedRing, which owns both it and the base-layer read.
        self._init_ring()
        # channel -> fixtures drawn from it, so a fade range finds its dots
        # without walking all 81 fixtures per lamp.
        self.chan_fix = {}
        for F in self.fixtures:
            for key in F["channels"].values():
                self.chan_fix.setdefault(key, []).append(F)

        # Every glow before any core marker: fixtures overlap on this picture
        # (the three SCOOP BB inserts share one XY), and interleaving would put
        # one fixture's halo over its neighbour's dot.
        for F in self.fixtures:
            x, y, r = F["x"] * self.scale, F["y"] * self.scale, LED_GLOW_R
            F["glow"] = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                            fill="", outline="",
                                            stipple="gray50")
        for F in self.fixtures:
            x, y, r = F["x"] * self.scale, F["y"] * self.scale, LED_R
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    fill="#1a1a1a", outline="#3a3a3a")
            F["item"] = i
            F["cx"], F["cy"] = x, y
            F["bg"] = self._sample(x, y)
            # What is on screen right now, so a tick can skip a fixture that
            # has not changed. See draw_fixtures().
            F["drawn"] = None
            # The tween's state (see draw_fixtures / animate_fixtures):
            # `state` is the last (rgb, level) decoded off the wire - the
            # empty tuple compares unequal to every real state, so the first
            # read always paints; `vis` is what is on screen NOW as floats
            # (r, g, b, alpha, radius); `v0`/`vt`/`t0` are the running fade.
            F["state"] = ()
            F["vis"] = (0.0, 0.0, 0.0, 0.0, float(LED_R))
            F["v0"] = F["vt"] = None
            F["t0"] = 0.0
            self.info[i] = dict(kind="led", d=F)

        for C in self.coils:
            x, y, r = C["x"] * self.scale, C["y"] * self.scale, 7
            i = self.cv.create_rectangle(x - r, y - r, x + r, y + r,
                                         outline="#ff4040", width=2)
            self.coil_items[(C["node"], C["index"])] = i
            self.info[i] = dict(kind="coil", d=C)

        # LIVE SWITCH STATE, all of it off one read (item 21). The dots inside
        # the switch rings, the trough panel and the coin-door warning are
        # three readings of the same 256 bytes.
        self.sw_dots, self._dot_drawn = [], {}
        self.trough_panel, self._panel_at = None, (self.ACT_PAD, 0)
        self.sw = SwitchWatch(self.switches)
        if not self.sw.positions:
            # The artwork table only carries switches that have a POSITION,
            # and a trough lives under the playfield - Godzilla places all six
            # and another title need not. The full switch list is the same
            # data without the coordinates, so ask it before giving up.
            self.sw.set_rows(load_switch_list())
        self._add_switches(self.switches)
        # When to look for a switch table that did not exist when this window
        # opened. See _pick_up_switches().
        self._sw_next = time.monotonic() + SWITCH_POLL_S

        self._place_actions(w, h)

        self.tip = Tip(root)
        self.drv = SwitchDriver()
        # ★ ITEM 39: the retired Controls window's content, beside the art -
        # keys, clickable service buttons, the door toggle, and the trough
        # (attach moves the corner one in when the panel exists).
        self._binds_next = time.monotonic() + SWITCH_POLL_S
        self.key_panel = attach_key_panel(self)
        self.holding = None            # (canvas item, switch id) while held
        self.ripping = None            # (canvas item, switch id) while ripped
        # PRESS and RELEASE, not <Button-1>: a switch is closed for as long as
        # the mouse is down. Tk's implicit grab delivers the release to this
        # canvas even if the pointer has left it, so a drag off the marker still
        # opens the switch.
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        # RIGHT-hold RIPS a switch (item 26) - closures for as long as the
        # button is down, the way a ball spinning a spinner does.
        self.cv.bind("<ButtonPress-3>", self.on_rip)
        self.cv.bind("<ButtonRelease-3>", self.on_rip_end)
        self.cv.bind("<Motion>", self.on_move)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.tick()

    def _add_switches(self, rows):
        """Draw a clickable marker for each switch, above everything else.

        TWO ITEMS PER SWITCH, AND ONLY THE RING IS CLICKABLE. The ring is the
        hit target and carries the hold highlight; the dot inside it is live
        state off the merged array, and it is NOT put into `self.info`.
        That is what keeps this generalisation free: `_hit()` returns the
        topmost item that is in `info`, so a filled dot cannot become the
        thing a click lands on. Filling the RING instead would have changed
        the hit test everywhere a switch and a coil share a spot - item 24
        measured that the centre of RIGHT SCOOP lands on the coil, and
        coilact.py depends on it.

        DRAWING ALL OF THEM COSTS WHAT DRAWING SIX WOULD. The item asked for
        the trough; the merged array arrives in one read for all 256 ids, so
        every other switch is free transport and only its own itemconfig -
        and a window that shows which switches the game currently has made is
        the honest version of the one that showed none of them.
        """
        for S in rows:
            x, y, r = S["x"] * self.scale, S["y"] * self.scale, 6
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    outline="#2a8cff", width=2)
            self.info[i] = dict(kind="switch", d=S)
            dot = self.cv.create_oval(x - 3, y - 3, x + 3, y + 3,
                                      fill="", outline="")
            self.sw_dots.append((dot, S["id"]))

    def _pick_up_switches(self):
        """Take the switch table if it arrives while this window is open.

        THE SWITCH TABLE IS THE ONE PART THAT NEEDS A RUN - the game builds it
        on the heap, so it reaches the outside world only as the shim's dump
        about a minute in, and mktables.py is behind this window waiting for
        exactly that. Loading the tables once at build time therefore meant the
        first run of a title ALWAYS showed a playfield with no switches on it,
        and the fix was to close the window and run the title again, which is a
        strange thing to have to know. The window is already polling fast;
        this is one os.path.exists a couple of seconds while a table is missing,
        and nothing at all once it is there.
        """
        if self.switches or time.monotonic() < self._sw_next:
            return
        self._sw_next = time.monotonic() + SWITCH_POLL_S
        rows = load_switches()
        if not rows:
            return
        self.switches = rows
        # The trough is worth re-asking for at the same moment: a first run of
        # a title opens this window before the game has published its switch
        # table, so "no trough" at window open is usually just "not yet".
        if not self.sw.positions and not self.sw.set_rows(rows):
            self.sw.set_rows(load_switch_list())
        self._add_switches(rows)
        self._make_trough_panel()

    def _sample(self, x, y):
        """The artwork's colour under a marker, averaged over its footprint.

        One pixel is not enough: inserts sit on high-contrast art, and a
        single sample that lands on a black outline makes the whole fixture
        blend toward black while its neighbour blends toward white. A small
        box average is stable and costs nothing here - this runs once per
        fixture at build time, never in a tick.
        """
        if self._art is None:
            return NO_ART_BG        # blank field: one flat colour behind all
        w, h = self._art.size
        r = int(LED_GLOW_R)
        x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
        x1, y1 = min(w, int(x) + r + 1), min(h, int(y) + r + 1)
        if x1 <= x0 or y1 <= y0:
            return (0, 0, 0)
        box = self._art.crop((x0, y0, x1, y1))
        n = box.width * box.height
        px = box.getdata()
        tot = [0, 0, 0]
        for p in px:
            tot[0] += p[0]; tot[1] += p[1]; tot[2] += p[2]
        return (tot[0] // n, tot[1] // n, tot[2] // n)

    # ---- hit testing and tooltips ----------------------------------------
    def _hit(self, ev):
        """Topmost element under the cursor. Switches and coils sit above the
        inserts, so a marker overlapping a dot still wins."""
        for i in reversed(self.cv.find_overlapping(ev.x - 3, ev.y - 3,
                                                   ev.x + 3, ev.y + 3)):
            if i in self.info:
                return i
        return None

    def _describe(self, i):
        e = self.info[i]
        d = e["d"]
        if e["kind"] == "switch":
            return ("SWITCH  %s\nid %d   node %d  bit %d\n"
                    "hold to keep it closed\nright-hold to RIP it (spinners)"
                    % (d["name"], d["id"], d["node"], d["bit"]))
        if e["kind"] == "coil":
            where = ("node %d index %d" % (d["node"], d["index"])
                     if d["node"] is not None
                     else "group %d index %d (board unknown)" % (d["group"],
                                                                 d["index"]))
            fires, lvl = self._coil_state(d)
            live = ("\nfired %d time%s, drive %d"
                    % (fires, "" if fires == 1 else "s", lvl)
                    if fires is not None else "\nno coil data")
            act = coilact.describe(d["name"])
            # "hold" where it now holds and "click" where it still pulses, so
            # the tooltip never promises the gesture the marker does not take.
            how = "hold" if coilact.hold_switch(d["name"]) is not None else "click"
            return "COIL  %s\n%s%s\n%s: %s" % (
                d["name"], where, live, how, act or "nothing wired")
        vals = self._chan_vals(d, self.last)
        fmt = lambda v: "%d" % v if v is not None else "no data"
        if "W" in d["channels"]:
            node, idx = d["channels"]["W"]
            return ("LED  %s\nnode %d  index %d\nvalue %s"
                    % (d["name"], node, idx, fmt(vals.get("W"))))
        lines = ["LED  %s   (RGB fixture)" % d["name"]]
        for chan in "RGB":
            if chan in d["channels"]:
                node, idx = d["channels"][chan]
                lines.append("%s  node %d  index %d  value %s"
                             % (chan, node, idx, fmt(vals.get(chan))))
        return "\n".join(lines)

    def on_move(self, ev):
        i = self._hit(ev)
        if i is None:
            self.tip.hide()
            return
        self.tip.show(self._describe(i), ev.x_root, ev.y_root)

    # ---- actions ---------------------------------------------------------
    def on_press(self, ev):
        i = self._hit(ev)
        if i is None:
            return
        e = self.info[i]
        if e["kind"] == "switch":
            self._hold(i, e["d"]["id"], "#2a8cff")
        elif e["kind"] == "coil":
            # A COIL MARKER IS THE ONE THE SCOOP ACTUALLY GETS. It is drawn over
            # the switch marker, so the middle of RIGHT SCOOP hit-tests to the
            # coil - measured, not assumed. Where the coil follows a switch,
            # hold that switch; where it MOVES a ball (trough eject, auto
            # plunger) there is nothing to hold and it stays a click.
            sw = coilact.hold_switch(e["d"]["name"])
            if sw is not None:
                self._hold(i, sw, "#ff4040")
            elif coilact.describe(e["d"]["name"]):
                self.drv.run_script("coilact.py", e["d"]["name"])

    def _hold(self, item, sw_id, restore):
        self.cv.itemconfig(item, outline="#ffd400", width=3)
        self.holding = (item, sw_id, restore)
        self.drv.press(sw_id)

    def on_release(self, ev):
        """Open whatever the press closed - by what we HELD, not by what is
        under the cursor now. A drag off the marker before letting go would
        otherwise hit-test to nothing and leave the switch made."""
        if self.holding is None:
            return
        item, sw_id, restore = self.holding
        self.holding = None
        self.drv.release(sw_id)
        self.cv.itemconfig(item, outline=restore, width=2)

    def on_rip(self, ev):
        """Right-hold RIPS a switch (item 26): repeated closures for as long
        as the button is down, shim-side, at the game's own scan rate. Only a
        switch marker rips - a coil has no level to alternate."""
        i = self._hit(ev)
        if i is None:
            return
        e = self.info[i]
        if e["kind"] != "switch":
            return
        self.cv.itemconfig(i, outline="#ff9500", width=3)
        self.ripping = (i, e["d"]["id"], "#2a8cff")
        self.drv.spin(e["d"]["id"], True)

    def on_rip_end(self, ev):
        """Stop the rip we STARTED, same argument as on_release: the pointer
        may have left the marker, but the flag we set is the one to clear."""
        if self.ripping is None:
            return
        item, sw_id, restore = self.ripping
        self.ripping = None
        self.drv.spin(sw_id, False)
        self.cv.itemconfig(item, outline=restore, width=2)

    #: The gap between the action buttons, and their inset from the canvas
    #: corner, in screen pixels. Not scaled: these space WIDGETS, which are sized
    #: in points by the theme, not in table units.
    ACT_PAD, ACT_GAP = 6, 4

    def _place_actions(self, w, h):
        """Start / Plunge / Reset balls, on the artwork beside the plunger.

        THEY USED TO BE A TOOLBAR ROW ABOVE THE CANVAS and are down here now
        because that is where the hand already is (REMAINING item 25): the
        shooter lane is switch 62 at table 283,608 of a 313x710 picture, so the
        plunger IS the bottom-right corner and the toolbar was the far end of a
        1300 px window from it.

        REAL tk.Button WIDGETS THROUGH create_window, NOT CANVAS ITEMS. A canvas
        item would land in find_overlapping and therefore in `_hit()`, which is
        the switch/coil hit test - the button would press whatever marker it was
        drawn over. A window item is in find_overlapping too, but it is not in
        `self.info`, so `_hit()` skips it, and the widget eats the click before
        the canvas binding ever runs.

        A ROW PINNED TO THE BOTTOM EDGE, NOT A STACK UP THE RIGHT SIDE, and the
        reason is the markers rather than taste. The lowest marker on this
        picture is RIGHT FLIPPER BUTTON at table y=656, which leaves 54*scale px
        under it: a three-high stack (~86 px) covers that marker on a 1080p
        screen, where one row (~26 px) clears it at every scale this window
        runs at, including PAD_PF_SCALE=1. Widths are asked of the widgets
        rather than assumed, so a different theme or DPI still lines up.
        """
        self._acts = []
        for label, arg in (("Start", "start"), ("Plunge", "plunge"),
                           ("Reset balls", "reset")):
            self._acts.append(tk.Button(self.cv, text=label, width=11,
                                        command=lambda a=arg: self.run_plunge(a)))
        x, y = w - self.ACT_PAD, h - self.ACT_PAD
        # Right to left, so "Reset balls" is the one against the corner and the
        # reading order left to right is the order the toolbar had.
        for b in reversed(self._acts):
            self.cv.create_window(x, y, anchor="se", window=b)
            x -= b.winfo_reqwidth() + self.ACT_GAP

        # Save/Load state, bottom-LEFT (item 13's GUI half, David 2026-08-08:
        # "i'd like to have gui controls to set and load a save state", surface
        # asked and answered - the playfield, over the game window's legend and
        # the Emulate tab). The LEFT corner, not more buttons on the right:
        # game actions stay by the plunger where the hand is, state controls
        # stay apart from them - a misclicked "Load state" yanks the whole game
        # back to the save, which is not a neighbour "Plunge" wants. One row
        # still clears the lowest marker for the same reason the right cluster
        # does (RIGHT FLIPPER BUTTON at y=656; see the docstring above).
        # Only on a checkpointable boot: no flag, no controls at all.
        self._state_btns = []
        row_h = max([b.winfo_reqheight() for b in self._acts] or [0])
        if SAVESTATES:
            x = self.ACT_PAD
            for wdg in self._build_state_widgets(self.cv, compact=True):
                self.cv.create_window(x, y, anchor="sw", window=wdg)
                x += wdg.winfo_reqwidth() + self.ACT_GAP
                row_h = max(row_h, wdg.winfo_reqheight())

        # THE TROUGH PANEL GOES ABOVE THE BOTTOM ROW, not into it: that row is
        # already two clusters wide (state controls left, game actions right)
        # and on a scaled-down window they have crowded each other once
        # already. Above them it is clear of both at every scale, and it is
        # still down at the apron end of the artwork, which is where the real
        # trough is - the physical position and the readable position agree.
        self._panel_at = (self.ACT_PAD, y - row_h - self.ACT_GAP)
        self._make_trough_panel()

    def _make_trough_panel(self):
        """Build the panel once the trough is known. Idempotent.

        On the KEY PANEL when there is one (item 39, the ball controls moved
        there); the artwork corner stays as the fallback for a window with no
        padbinds to read - an old renderer, or a by-hand launch."""
        if self.trough_panel is not None or not self.sw.positions:
            return
        if self.key_panel is not None:
            self.trough_panel = self.key_panel.add_trough(
                self.sw.positions, self.sw.how, self.run_plunge)
            return
        x, y = self._panel_at
        self.trough_panel = TroughPanel(self.cv, self.sw.positions,
                                        self.sw.how, x, y, anchor="sw",
                                        on_ball=self.run_plunge)

    def run_plunge(self, what):
        self.drv.run_script("plunge.py", what)

    # ---- live LED and coil state -----------------------------------------
    def read_leds(self):
        try:
            with open(LED_PATH, "rb") as f:
                d = f.read(PADLED_READ)
        except OSError:
            return None
        if len(d) < LED_HDR or struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            return None
        return d

    def door_open(self):
        """True when the coin door is open, so 48V is off and coils are dead.

        NO READ OF ITS OWN ANY MORE. This used to be the only reason this
        window touched the switch block, on its own cadence and reading a
        single byte; the trough display needs the same block at a higher rate,
        and a 9p round trip costs what it costs regardless of how many bytes
        it carries (3.35 ms either way, measured). So the door is now one
        answer out of SwitchWatch's one read - see read_merged() for why the
        keyboard's half stands in until the guest has published.
        """
        return self.sw.door

    def _coil_state(self, d):
        """(fire count, drive byte) for a coil, or (None, None) with no data."""
        node = d["node"]
        if node is None or not self.last or len(self.last) < PADLED_READ:
            return None, None
        if struct.unpack_from("<I", self.last, 4)[0] < 2:      # version
            return None, None
        o = node * COIL_N + d["index"]
        return self.last[COIL_OFF + o], self.last[LVL_OFF + o]

    def _tick_coils(self, d, now):
        """Flash a coil marker when its fire counter moves.

        The counter, rather than an on/off bit, is what makes this reliable: a
        slingshot pulse is ~30 ms and would fall between two 50 ms polls about
        half the time. A counter cannot miss one.
        """
        fired = 0
        for key, item in self.coil_items.items():
            node, idx = key
            if node is None:
                continue
            c = d[COIL_OFF + node * COIL_N + idx]
            if key in self.coil_seen and c != self.coil_seen[key]:
                self.coil_until[key] = now + COIL_FLASH_MS
            self.coil_seen[key] = c
            hot = self.coil_until.get(key, 0) > now
            fired += hot
            # Same only-what-changed rule as the inserts: a coil is cold in
            # almost every frame, and reconfiguring a cold coil 30 times a
            # second is pure Tcl round trips for no pixels.
            if self.coil_drawn.get(key) == hot:
                continue
            self.coil_drawn[key] = hot
            # MAGENTA, not a hotter orange. Single-channel inserts run
            # #ff3c00..#fffb00, so an orange coil flash is the one colour that
            # cannot be told apart from the thing next to it at a glance - and
            # it is ALSO exactly the ambiguity that made "did the flash
            # render?" unanswerable from a screenshot. An RGB fixture can now
            # compose to magenta, but a coil is a filled SQUARE; no dot is one.
            self.cv.itemconfig(item, fill="#ff00c0" if hot else "",
                               outline="#ff80ff" if hot else "#ff4040",
                               width=3 if hot else 2)
        return fired

    def draw_fixtures(self, d, now):
        """Set each fixture's fade TARGET from the wire. Returns (lit, changed).

        ONLY WHAT CHANGED. This used to reconfigure all 81 fixtures - two
        canvas items each, 162 calls - every single tick, whether or not a
        single byte had moved, and a Tk itemconfig is a round trip into the
        Tcl interpreter. On a real attract frame a handful of inserts change
        and the rest are identical, so the (rgb, level) compare turns almost
        all of that work into a dict lookup. That, and not the transport, is
        what makes the frame rate affordable.

        NOTHING IS PAINTED HERE ANY MORE. The wire carries steps, the real
        boards render the ramps (module docstring), so a state change only
        RETARGETS the fixture's tween and animate_fixtures() draws the frames.
        `changed` counts fixtures whose decoded state moved - the honest
        "picture rate" for the status bar, which must NOT count tween frames:
        a 200 ms fade drawn at 60 fps is one update, not twelve.
        """
        lit = 0
        changed = 0
        for F in self.fixtures:
            rgb, level = fixture_color(self._chan_vals(F, d, now))
            if rgb:
                lit += 1
            st = (rgb, level)
            if st == F["state"]:
                continue
            F["state"] = st
            # An ENVELOPED fixture changes every tick because the envelope is
            # feeding it the ramp: track it with no extra smoothing (the ramp
            # IS the animation) and do not count the frames as picture
            # updates - the pulse was counted once when its command arrived.
            if F.get("env"):
                F["dur"] = 0.0
            else:
                changed += 1
                F["dur"] = FADE_MS / 1000.0
            v = F["vis"]
            if rgb:
                rs, alpha = level_shape(level)
                if v[3] <= 0.0:
                    # A fade IN starts from the target's own hue at zero
                    # alpha, not from black - lerping the colour up from
                    # (0,0,0) sweeps it through mud on the way.
                    v = (float(rgb[0]), float(rgb[1]), float(rgb[2]),
                         0.0, v[4])
                    F["vis"] = v
                F["vt"] = (float(rgb[0]), float(rgb[1]), float(rgb[2]),
                           alpha, LED_R * rs)
            else:
                # A fade OUT keeps the hue it had on the way down, growing
                # back to the resting radius so the dark dots stay one size
                # however each one went out.
                F["vt"] = (v[0], v[1], v[2], 0.0, float(LED_R))
            F["v0"] = v
            F["t0"] = now
        return lit, changed

    def animate_fixtures(self, now):
        """Advance every mid-fade fixture and paint the ones that moved.

        Linear, deliberately: a PWM ramp is linear in duty, and at 60 fps an
        80 ms step is ~5 frames - an easing curve would be invisible. The
        duration is per fixture: a base step gets FADE_MS, an enveloped
        fixture gets 0 because the a2 pulse itself is feeding the ramp.
        """
        for F in self.fixtures:
            vt = F["vt"]
            if vt is None:
                continue
            dur = F.get("dur", FADE_MS / 1000.0)
            t = 1.0 if dur <= 0 else min(1.0, (now - F["t0"]) / dur)
            v0 = F["v0"]
            vis = tuple(a + (b - a) * t for a, b in zip(v0, vt))
            F["vis"] = vis
            if t >= 1.0:
                F["vt"] = None          # arrived; stop paying for this one
            self._paint(F, vis)

    def _paint(self, F, vis):
        """Put one visual state (r, g, b, alpha, radius floats) on the canvas.

        QUANTISED before the change-gate, so a tween costs a handful of
        itemconfigs rather than one per frame: alpha in 1/32 steps (finer
        than blend()'s 8-bit output can show), radius in 0.25 px (finer than
        the eye, and the same step the old PWM-jitter guard used).
        """
        alpha, rad = vis[3], vis[4]
        if alpha <= 1.0 / 64:
            want = ("#1a1a1a", "", 0.0)
        else:
            a_q = round(alpha * 32) / 32.0
            r_q = round(rad * 4) / 4.0
            rgb = (int(vis[0]), int(vis[1]), int(vis[2]))
            want = (blend(rgb, F["bg"], a_q),
                    blend([c // 2 for c in rgb], F["bg"], a_q * 0.7), r_q)
        if want == F["drawn"]:
            return
        prev = F["drawn"]
        F["drawn"] = want
        self._redrawn += 1
        fill, glow, r = want
        if r:
            self.cv.itemconfig(F["item"], fill=fill, outline="")
            self.cv.itemconfig(F["glow"], fill=glow)
            if prev is None or prev[2] != r:
                x, y = F["cx"], F["cy"]
                self.cv.coords(F["item"], x - r, y - r, x + r, y + r)
                g = LED_GLOW_R * (r / LED_R)
                self.cv.coords(F["glow"], x - g, y - g, x + g, y + g)
        else:
            self.cv.itemconfig(F["item"], fill=fill, outline="#3a3a3a")
            self.cv.itemconfig(F["glow"], fill="")
            # An insert that fades out from dim would otherwise keep the
            # SMALL radius it had while lit, so the dark dots would be
            # different sizes depending on how each one last went out.
            if prev is not None and prev[2] != LED_R:
                x, y = F["cx"], F["cy"]
                self.cv.coords(F["item"], x - LED_R, y - LED_R,
                               x + LED_R, y + LED_R)
                self.cv.coords(F["glow"], x - LED_GLOW_R, y - LED_GLOW_R,
                               x + LED_GLOW_R, y + LED_GLOW_R)

    def _mark(self, dq, t):
        """Record an event and return its rate over the last RATE_WIN_S."""
        dq.append(t)
        return self._rate(dq, t)

    @staticmethod
    def _rate(dq, t):
        while dq and t - dq[0] > RATE_WIN_S:
            dq.popleft()
        if not dq:
            return 0.0
        # Divide by the window, NOT by the span of the events in it: dividing by
        # the span reports 30 Hz for two redraws 33 ms apart inside an otherwise
        # dead three seconds, which is the exact overclaim this field exists to
        # stop making.
        return len(dq) / RATE_WIN_S

    def tick(self):
        t0 = time.perf_counter()
        # The achieved rate is measured from tick START to tick START, which is
        # the interval a human actually sees. Measuring the work alone would
        # report a rate this window has never run at.
        if self._t_last:
            dt = t0 - self._t_last
            self.fps = 1.0 / dt if not self.fps else self.fps * 0.9 + 0.1 / dt
        self._t_last = t0
        self._pick_up_switches()

        # ONE PACED READ OF THE SWITCH BLOCK feeds three things: the dot in
        # every switch ring, the trough panel, and the coin-door warning that
        # used to do this read on its own.
        poll_switches(self)

        t_read = time.perf_counter()
        d = self.read_leds()
        self._read_ms = (time.perf_counter() - t_read) * 1000.0
        self.last = d
        if emu_gone(self, d is not None):
            # SAVE FIRST. Leaving with the run is the COMMON way this window
            # closes - the human closes the emulator, not the playfield - so a
            # destroy without this meant the remembered position only ever came
            # from the rare manual close, and a dragged playfield drifted back
            # to where it was two runs ago.
            save_state(self.root)
            self.root.destroy()             # the run ended; leave with it
            return
        state_msg = self._state_status()
        if d is None:
            self.status.config(text=state_msg
                               or "no emulator (dump/padled not readable)")
        else:
            decoded = struct.unpack_from("<I", d, LED_DECODED_OFF)[0]
            skipped = struct.unpack_from("<I", d, LED_SKIPPED_OFF)[0]
            # DID NEW BYTES ARRIVE THIS TICK? Diffed rather than trusted: the
            # counter is written by the shim inside the guest and read across
            # the VM boundary, so "the number moved" is the only evidence this
            # side has that the block is live at all.
            if self._decoded is not None and decoded != self._decoded:
                self._mark(self._data_ev, t0)
            self._decoded = decoded
            # The fade ring first: a pulse command is both data arriving and
            # one picture update, however many frames its envelope spans.
            nfades = self._take_fades(d, t0)
            for _ in range(nfades):
                self._draw_ev.append(t0)
                self._data_ev.append(t0)
            lit, changed = self.draw_fixtures(d, t0)
            if changed:
                self._mark(self._draw_ev, t0)
            if changed or nfades:
                if self._draw_last is not None:
                    self._gap_worst = max(self._gap_worst, t0 - self._draw_last)
                self._draw_last = t0
            self.animate_fixtures(t0)
            coils = ""
            if len(d) >= PADLED_READ and struct.unpack_from("<I", d, 4)[0] >= 2:
                self._tick_coils(d, time.monotonic() * 1000.0)
                coils = "   %d coils addressed" % struct.unpack_from(
                    "<I", d, COIL_GEN_OFF + 4)[0]
                if self.door_open():
                    coils += "   COIN DOOR OPEN: 48V off, no coil can fire"
            # THE DROPPED FRAMES ARE ON SCREEN TOO, and they are the honest
            # answer to "are the LEDs working". A still picture here has two
            # completely different causes - the game is not driving the lamps,
            # or it is driving them through frames this rig cannot decode yet
            # (handoff item 1b) - and the window used to look identical either
            # way. Shown only once any have been dropped, so a clean run stays
            # uncluttered.
            drops = ", %d dropped" % skipped if skipped else ""
            # SAY SO WHEN THERE IS NO TROUGH TO DRAW. A missing panel with
            # nothing to explain it reads as a window that forgot, and the
            # titles it happens on are the `?`-name ones (item 29) where the
            # user most needs to know the rig cannot find the balls.
            if not self.sw.positions:
                coils += "   no trough switches identified"
            # BOTH RATES ARE ON SCREEN, and which is which is spelled out. The
            # loop is not the picture: see the module docstring, and item 31,
            # which is this window reading 30 fps over a 2.83 s freeze. The
            # data field is ALWAYS shown - the first version showed it only
            # when the two disagreed, and the toggling width resized the whole
            # window (the label's width=1 is the belt to this brace).
            draw_hz = self._rate(self._draw_ev, t0)
            data_hz = self._rate(self._data_ev, t0)
            self.status.config(
                text=state_msg
                     or " %d of %d inserts lit   LED %.1f Hz   data %.1f Hz"
                        " (%d writes%s)%s   poll %.0f fps"
                        % (lit, len(self.fixtures), draw_hz, data_hz, decoded,
                           drops, coils, self.fps))

        # PACED, not slept. after(FRAME_MS) would add the frame's own cost to
        # every interval and land at 20-25 fps while claiming 30; subtracting
        # the work keeps the START-to-START interval at the target. The 1 ms
        # floor keeps Tk's event loop breathing when a frame overruns.
        spent = (time.perf_counter() - t0) * 1000.0
        self._log(t0, spent)
        self.root.after(max(1, int(FRAME_MS - spent)), self.tick)

    def _log(self, t0, spent):
        """PAD_PF_LOG=<path>: one line a second of what the loop is doing.

        The status bar shows the rate to the human; this exists so the rate
        can be MEASURED rather than read off a screenshot of a smoothed
        number, and so the split between the read and the drawing is on the
        record. Off unless the variable is set, and it costs one compare when
        it is off.

        IT CARRIES THE PICTURE RATE AND THE WORST FREEZE, not just the loop.
        Item 31's acceptance asks for the achieved visual updates a second and
        the longest still stretch, and getting those off a screen recording
        costs a recording, a frame extraction and a differ. This answers the
        same question from inside the window, on any run, for one line a
        second - and `worst` is a MAXIMUM SINCE THE LAST LINE rather than a
        smoothed figure, because a 2.8 s freeze inside a second-long average is
        exactly what averaging hides.
        """
        if not PF_LOG:
            return
        self._log_n += 1
        if t0 - self._log_t < 1.0:
            return
        try:
            with open(PF_LOG, "a") as f:
                f.write("%.1f fps over %d ticks   frame %.1f ms "
                        "(read %.1f, draw %.1f)   %d fixtures redrawn   "
                        "LED %.1f Hz  data %.1f Hz  worst gap %.2f s\n"
                        % (self._log_n / (t0 - self._log_t), self._log_n,
                           spent, self._read_ms, spent - self._read_ms,
                           self._redrawn, self._rate(self._draw_ev, t0),
                           self._rate(self._data_ev, t0), self._gap_worst))
        except OSError:
            pass
        self._log_t, self._log_n, self._redrawn = t0, 0, 0
        self._gap_worst = 0.0


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(root):
    """Remember where the window was, so it opens there next time.

    Position only, not size: the canvas is sized from the artwork and the
    screen, so restoring a stale WxH would letterbox or clip it after a
    resolution change.
    """
    try:
        st = load_state()
        st["playfield_pos"] = [root.winfo_x(), root.winfo_y()]
        with open(STATE, "w") as f:
            json.dump(st, f, indent=1)
    except Exception:
        pass


def _onscreen(root, x, y):
    """Reject a remembered position that is off every monitor.

    Unplugging a second display otherwise leaves the window permanently at
    -1800,300 with no way to drag it back.
    """
    return (-50 <= x <= root.winfo_screenwidth() - 120
            and -20 <= y <= root.winfo_screenheight() - 80)


#: The swatch grid's geometry in screen pixels: the cell, the pitch between
#: cells, and how many sit in a row before a node's block wraps. 8 per row
#: because the blocks then stack in one narrow column beside the switch list,
#: which is the space this view actually has spare.
LED_CELL, LED_PITCH, LED_PER_ROW = 12, 16, 8
LED_GRID_HDR = 18
LED_GRID_GAP = 10

#: What a swatch blends toward. The grid has no artwork behind it, so unlike
#: the artwork view's per-fixture sample this is one colour - it must match the
#: canvas the cells are drawn on or every dim lamp reads as a smudge.
LED_GRID_BG = (16, 16, 16)


class LedGrid(LedRing):
    """Every LED the wire has shown, as a field of colour, grouped by node.

    ★ THE ROSTER COMES FROM THE RING, NOT FROM A TABLE, and that is the whole
    design (item 50). Four of the nine titles with tables on this machine -
    star_wars_le, stranger_things_le, turtles_pro, led_zeppelin_le - carry `0
    records` in device_xy.txt: no names, no positions, nothing. A grid built
    from a table shows them an empty box over a running light show. A grid
    built from the block shows what the game is actually doing, and the table
    is then only ever a LOOKUP for the name.

    It also needs no group -> node map, which is what makes it the answer for
    the titles item 53 currently costs (Bond addresses 0 of its 73 lamps). The
    grid is keyed by the wire's own (node, index), so it cannot be wrong about
    which lamp moved - only about what that lamp is called.

    A CHANNEL EARNS ITS CELL BY BEING WRITTEN, AND KEEPS IT. Sticky on purpose:
    a lamp that pulses once and goes dark would otherwise have its cell appear
    and vanish, and a grid that reflows while you watch it is unreadable. So
    the roster only ever grows, and a dark cell means "this lamp exists and is
    off" - which is the same promise the artwork view makes.

    ONE CELL PER FIXTURE WHERE THE NAMES ALLOW IT. An RGB insert is three
    channels with -R/-G/-B stems, and joining them shows one cell in the
    lamp's true colour instead of three in red, green and blue. That join
    needs names, so it happens on titles that have a table and not on titles
    that do not; an unnamed channel gets its own cell called `node.index`.
    NOTHING IS INFERRED from consecutive indices - guessing which three
    channels are one lamp is precisely the kind of invention this project
    keeps having to undo, and being wrong would show a colour the game never
    lit.
    """

    def __init__(self, cv, x0, y0, height, names):
        self.cv, self.x0, self.y0, self.height = cv, x0, y0, height
        self.names = names or {}
        self.cells = []                 # one dict per drawn fixture
        self.by_node = {}               # node -> [cell], in index order
        self.seen = set()               # every (node, idx) the ring has shown
        self.info = {}                  # canvas item -> cell, for tooltips
        self.cols = 1                   # how many columns the flow needed
        self._decoded = None            # last `decoded`, to gate discovery
        self._init_ring()
        self._note = cv.create_text(
            x0, y0, anchor="nw", fill="#7a7a7a", font=("Consolas", 9),
            text="LEDs\n\nwaiting for the first\nLED write from the game")

    def reserved_width(self):
        """What to add to the canvas width for the grid, before it has any."""
        return LED_PER_ROW * LED_PITCH + 24

    # ---- roster ----------------------------------------------------------
    def _discover(self, d):
        """Add a cell for every channel the block shows and we have not seen.

        Returns True when the roster grew, i.e. when the layout must be redone.

        THE SCAN IS PER NODE AND STARTS WITH A C-LEVEL TEST. `val` is
        16 nodes x 96 indices; a node whose 96 bytes are all zero cannot
        contribute and `bytes.count(0)` answers that in one call, so the Python
        loop only runs over boards that have data. padled.h says only the
        insert boards are decoded today - this deliberately does NOT hard-code
        which those are, so a shim that starts decoding another board shows up
        here with no change.
        """
        grew = False
        for node in range(coilmap.NODES):
            base = LED_HDR + node * LED_IDX
            s = d[base:base + LED_IDX]
            if len(s) < LED_IDX or s.count(0) == LED_IDX:
                continue
            for idx, v in enumerate(s):
                if v and (node, idx) not in self.seen:
                    self.seen.add((node, idx))
                    grew = True
        return grew

    def _rebuild(self):
        """Group the roster into fixtures and lay the blocks out.

        Called only when the roster GREW, never per tick: it is a few hundred
        coordinate computations, which is nothing once but real at 30 Hz.

        ★ CELLS ARE REUSED ACROSS REBUILDS, KEYED BY (node, name), AND THE
        FIRST VERSION OF THIS DID NOT DO THAT. It built fresh dicts with
        `item=None` every time, so each growth of the roster created a NEW
        rectangle for every cell and left the previous generation on the canvas
        for ever - invisible in a test that lights every channel at once (one
        rebuild), and on a real run a pile of stale swatches that covered the
        node headers and leaked a canvas item per cell per rebuild. Reusing the
        dict also keeps `drawn`/`state` - so a lamp that was already lit does
        not flash off and on when some unrelated board is discovered - and
        keeps `self.info` pointing at objects that still exist.
        """
        # Group by node, then by name stem where a name exists.
        by_node = {}
        for node, idx in sorted(self.seen):
            by_node.setdefault(node, []).append(idx)
        old = {(C["node"], C["name"]): C for C in self.cells}
        cells, self.by_node, live = [], {}, set()
        for node in sorted(by_node):
            stems, order = {}, []
            for idx in by_node[node]:
                name = self.names.get((node, idx))
                if name:
                    stem, chan = split_channel(name)
                else:
                    stem, chan = "%d.%d" % (node, idx), "W"
                # A stem that repeats a channel letter is two lamps sharing a
                # name, not one lamp with two reds: give the second its own
                # cell rather than silently dropping it.
                C = stems.get(stem)
                if C is not None and chan in C["channels"]:
                    stem = "%s (%d.%d)" % (stem, node, idx)
                    C = stems.get(stem)
                if C is None:
                    C = old.get((node, stem))
                    if C is None:
                        C = dict(name=stem, node=node, item=None, drawn=None,
                                 state=(), named=bool(name))
                    C["channels"], C["idxs"] = {}, []
                    stems[stem] = C
                    order.append(C)
                C["channels"][chan] = (node, idx)
                C["idxs"].append(idx)
            for C in order:
                C["sort"] = min(C["idxs"])
            order.sort(key=lambda C: C["sort"])
            self.by_node[node] = order
            cells.extend(order)
            live.update((node, C["name"]) for C in order)
        # A cell whose stem no longer exists (its channels regrouped under a
        # different name) takes its canvas item with it.
        for key, C in old.items():
            if key not in live and C["item"] is not None:
                self.info.pop(C["item"], None)
                self.cv.delete(C["item"])
        self.cells = cells

        # THE FLOW. A node's block is a header plus ceil(n/PER_ROW) rows, and a
        # block that does not fit the remaining height starts a new column -
        # the same shape as the switch list beside it, for the same reason
        # (clipped is unreachable, not merely offscreen).
        col_w = LED_PER_ROW * LED_PITCH + 24
        x, y, self.cols = self.x0, self.y0, 1
        for node in sorted(self.by_node):
            block = self.by_node[node]
            rows = (len(block) + LED_PER_ROW - 1) // LED_PER_ROW
            need = LED_GRID_HDR + rows * LED_PITCH + LED_GRID_GAP
            if y > self.y0 and y + need > self.y0 + self.height:
                x += col_w
                y = self.y0
                self.cols += 1
            hdr = self._hdr(node)
            self.cv.coords(hdr, x, y)
            self.cv.itemconfig(hdr, text="node %d  (%d)" % (node, len(block)))
            y += LED_GRID_HDR
            for i, C in enumerate(block):
                cx = x + (i % LED_PER_ROW) * LED_PITCH
                cy = y + (i // LED_PER_ROW) * LED_PITCH
                if C["item"] is None:
                    C["item"] = self.cv.create_rectangle(
                        0, 0, 0, 0, fill="", outline="#333333")
                    self.info[C["item"]] = C
                self.cv.coords(C["item"], cx, cy,
                               cx + LED_CELL, cy + LED_CELL)
            y += rows * LED_PITCH + LED_GRID_GAP
        if self._note is not None:
            self.cv.delete(self._note)
            self._note = None

    def _hdr(self, node):
        h = self.__dict__.setdefault("_hdrs", {})
        if node not in h:
            h[node] = self.cv.create_text(0, 0, anchor="nw", fill="#7ecbff",
                                          font=("Consolas", 9, "bold"), text="")
        return h[node]

    # ---- the tick --------------------------------------------------------
    def tick(self, d, now):
        """Repaint the cells whose value moved. Returns (lit, total)."""
        if not d or len(d) < LED_HDR:
            return 0, len(self.cells)
        self._take_fades(d, now)
        # Discovery is gated on the block's own write counter, so an idle rig
        # costs one unpack per tick instead of a scan of every board.
        dec = struct.unpack_from("<I", d, LED_DECODED_OFF)[0]
        if dec != self._decoded:
            self._decoded = dec
            if self._discover(d):
                self._rebuild()
        lit = 0
        for C in self.cells:
            rgb, level = fixture_color(self._chan_vals(C, d, now))
            if rgb:
                lit += 1
            st = (rgb, level)
            if st == C["state"]:
                continue
            C["state"] = st
            # SAME ONLY-WHAT-CHANGED RULE AS THE ARTWORK VIEW, and for the same
            # reason: an itemconfig is a round trip into Tcl, and on a real
            # frame a handful of lamps move while the rest are identical.
            if rgb:
                _rs, alpha = level_shape(level)
                want = (blend(rgb, LED_GRID_BG, alpha),
                        blend(rgb, LED_GRID_BG, min(1.0, alpha * 1.3)))
            else:
                want = ("", "#333333")
            if want != C["drawn"]:
                C["drawn"] = want
                self.cv.itemconfig(C["item"], fill=want[0], outline=want[1])
        return lit, len(self.cells)

    def describe(self, C):
        where = ", ".join("%s=node %d index %d" % (c, n, i)
                          for c, (n, i) in sorted(C["channels"].items()))
        return ("LED  %s\n%s\n%s"
                % (C["name"], where,
                   "named by the title's device table" if C["named"]
                   else "no name in this title's table - shown by wire address"))


class Schematic(StateOps):
    """The window for a title with NO positions: every switch, by node, clickable.

    This is not a lesser playfield, it is a different question answered. With no
    device table there is nothing to place markers on and nothing to place them
    from, and inventing coordinates from the names is exactly the guess this
    project keeps having to undo. So it draws what the game actually knows: the
    switch list it carries, in its own order, grouped by the board each switch is
    wired to.

    Clicking a row closes that switch through the same swpoke.py path the
    artwork window uses, so a title with no drawing is still playable.

    ★ ITEM 39 REFLOWED IT. The old form was one 300 px column PER NODE, width
    unbounded and height capped at the screen - and with no scrolling anywhere,
    whatever the cap clipped was unreachable by mouse, not merely offscreen.
    David: "for games without a virtual playfield, we need to compact the view
    since it is so large and overflows even on large monitors." Now the rows
    FLOW: one ordered list (node headers inline), broken into columns of
    however many rows the screen's height actually has, columns as wide as the
    text actually measures. The height fits by construction; a pathological
    width (hundreds of switches on a short screen) scrolls horizontally rather
    than clipping, so every row stays reachable - that is the acceptance line.
    """

    ROW_H = 17
    #: Room the window needs AROUND the switch canvas: title bar, top bar,
    #: trough strip, status bar, taskbar. Same estimating job as pick_scale's
    #: `chrome`, and like there, being generous costs a little empty space
    #: while being short costs reachable rows.
    CHROME = 250
    NAME_W = 26

    def __init__(self, root, switches):
        self.root = root
        self.switches = switches
        self.last = None

        bar = tk.Frame(root, bg="#111")
        bar.pack(fill="x")
        tk.Label(bar, text="  %s: %d switches, no playfield artwork in this title"
                           "  - click a row to close that switch"
                      % (GAME, len(switches)),
                 bg="#111", fg="#bbb", font=("Consolas", 9)).pack(side="left",
                                                                  padx=4, pady=4)
        # Save/Load state on the bar's right (item 13, same cluster as the
        # artwork view's bottom-left): a title with no artwork still saves
        # and loads - the wrappers know nothing about drawings. Packed
        # side="right" in REVERSE so the cluster reads picker | Save | Load
        # left-to-right, matching the artwork view. Only on a checkpointable
        # boot (module flag SAVESTATES) - no flag, no controls.
        self._state_btns = []
        if SAVESTATES:
            for wdg in reversed(self._build_state_widgets(bar)):
                wdg.pack(side="right", padx=(0, 4), pady=2)

        # THE TROUGH GETS ITS OWN STRIP HERE, not a corner of the switch grid.
        # The grid is columns of text that already fill the window and the
        # panel would land on top of a node's rows; a strip of its own cannot
        # collide with anything, and this view is the one that runs on the
        # `?`-name titles (item 29), where seeing that the trough is empty is
        # the difference between "the game is broken" and "the game cannot
        # find its balls".
        self.sw_dots, self._dot_drawn = [], {}
        self.sw = SwitchWatch(switches,
                              every=round(1000.0 / POLL_MS / max(1.0, SW_HZ)))
        # The strip is the FALLBACK now (item 39): when the key panel attaches
        # it destroys this and rebuilds the trough at the panel's bottom, so a
        # window with no padbinds to read still shows its balls.
        self.trough_panel, self._trough_strip = None, None
        if self.sw.positions:
            strip = tk.Frame(root, bg="#111")
            strip.pack(fill="x")
            pcv = tk.Canvas(strip, height=38, bg="#111", highlightthickness=0)
            pcv.pack(fill="x", padx=4, pady=(0, 3))
            self._trough_strip = strip
            self.trough_panel = TroughPanel(
                pcv, self.sw.positions, self.sw.how, 2, 2, anchor="nw",
                on_ball=self.run_plunge)

        # THE FLOW. One entry list in node order, then columns cut to the
        # height the screen has. A node header may not be the LAST row of a
        # column - a label that labels nothing - so it is pushed to the top of
        # the next one.
        by_node = {}
        for sw in switches:
            by_node.setdefault(sw["node"], []).append(sw)
        entries = []
        for node in sorted(by_node):
            entries.append(("hdr", node))
            for sw in sorted(by_node[node], key=lambda s: s["bit"]):
                entries.append(("sw", sw))
        per_col = max(12, (root.winfo_screenheight() - self.CHROME)
                      // self.ROW_H)
        cols, col = [], []
        for j, e in enumerate(entries):
            col.append(e)
            if len(col) >= per_col:
                if col[-1][0] == "hdr" and j + 1 < len(entries):
                    cols.append(col[:-1])
                    col = [col[-1]]
                else:
                    cols.append(col)
                    col = []
        if col:
            cols.append(col)

        # Column width is MEASURED, not guessed: the text is monospaced, so
        # the widest possible row is the format string at full name width.
        f9 = tkfont.Font(family="Consolas", size=9)
        colw = f9.measure("999  " + "M" * self.NAME_W) + 26
        w = len(cols) * colw + 8
        h = per_col * self.ROW_H + 16
        # ★ ITEM 50: the LED swatch grid lives to the RIGHT of the switch
        # columns, on this same canvas, so it inherits the scroll backstop and
        # the hit testing rather than growing a second scrolling surface. Its
        # width is reserved here because the grid has no cells yet - the roster
        # arrives from the wire, seconds into a run.
        grid_x = w + 10
        w = grid_x + LED_PER_ROW * LED_PITCH + 24

        # THE SCROLL BACKSTOP. Normally the flow fits with room to spare (a
        # 108-switch title is two columns on this desktop); if it ever does
        # not, the canvas scrolls horizontally instead of clipping - clipped
        # rows were the old view's real fault, unreachable rather than just
        # offscreen. The status bar and the bars above stay put; only the
        # rows scroll.
        maxw = max(colw + 8, root.winfo_screenwidth() - 420)
        self._hbar = None
        if w > maxw:
            self._hbar = tk.Scrollbar(root, orient="horizontal")
            self._hbar.pack(side="bottom", fill="x")

        # width=1 for the same reason as Field's bar: the text must never be
        # what sizes the window. Packed BEFORE the canvas, side="bottom", the
        # lesson Field's bar carries (a bar packed after the canvas is last in
        # line for space and can simply not be shown).
        self.status = tk.Label(root, text="", anchor="w", bg="#111", fg="#ddd",
                               font=("Consolas", 9), width=1)
        self.status.pack(side="bottom", fill="x")

        self.cv = tk.Canvas(root, width=min(w, maxw), height=h, bg="#101010",
                            highlightthickness=0, scrollregion=(0, 0, w, h))
        if self._hbar is not None:
            self.cv.configure(xscrollcommand=self._hbar.set)
            self._hbar.configure(command=self.cv.xview)
        self.cv.pack(side="left", fill="both", expand=True)
        # ★ ITEM 39: the key panel attaches after SwitchDriver exists, below.
        self.key_panel, self.keys = None, None

        self.info = {}
        for ci, entries_col in enumerate(cols):
            x = ci * colw + 18
            for ri, (kind, d) in enumerate(entries_col):
                y = 14 + ri * self.ROW_H
                if kind == "hdr":
                    self.cv.create_text(x, y, anchor="w", fill="#7ecbff",
                                        font=("Consolas", 9, "bold"),
                                        text="node %d" % d)
                    continue
                i = self.cv.create_text(
                    x, y, anchor="w", fill="#d8d8d8", font=("Consolas", 9),
                    text="%3d  %s" % (d["id"], d["name"][:self.NAME_W]))
                self.info[i] = dict(kind="switch", d=d)
                # The live-state dot beside the row, drawn OUTSIDE the text and
                # not registered in `info` - the same rule as the artwork
                # view's dots, so it can never become what a click lands on.
                dot = self.cv.create_oval(x - 9, y - 3, x - 3, y + 3,
                                          fill="", outline="")
                self.sw_dots.append((dot, d["id"]))

        # ★ ITEM 50. Names come from the device table where the title has one
        # (any image - the grid has no picture, so it has no reason to drop a
        # topper lamp); the ROSTER comes from the wire, which is what makes
        # this work on the four titles whose table is empty.
        self.leds = LedGrid(self.cv, grid_x, 14, h - 28, load_led_names())
        self.led_lit, self.led_total = 0, 0

        self.tip = Tip(root)
        self.drv = SwitchDriver()
        # ★ ITEM 39: the retired Controls window's content, docked right -
        # the same panel the artwork view gets (keys, service buttons, door,
        # trough), so the two shapes of this window agree about where the
        # controls are.
        self._binds_next = time.monotonic() + SWITCH_POLL_S
        self.key_panel = attach_key_panel(self)
        self.holding = None
        self.ripping = None
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        # RIGHT-hold RIPS a switch (item 26), same as the artwork view.
        self.cv.bind("<ButtonPress-3>", self.on_rip)
        self.cv.bind("<ButtonRelease-3>", self.on_rip_end)
        self.cv.bind("<Motion>", self.on_move)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.tick()

    def run_plunge(self, what):
        self.drv.run_script("plunge.py", what)

    def _hit(self, ev):
        # canvasx, because the scroll backstop makes window x and canvas x
        # different things the moment the view is scrolled. canvasy for
        # symmetry; this view never scrolls vertically today.
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        for i in reversed(self.cv.find_overlapping(x - 2, y - 8,
                                                   x + 2, y + 8)):
            if i in self.info:
                return i
        return None

    def _hit_led(self, ev):
        """The swatch under the cursor, or None. SEPARATE from _hit(), so a
        cell can never become something a press tries to close - the same rule
        the live-state dots beside the rows follow."""
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        for i in reversed(self.cv.find_overlapping(x, y, x, y)):
            if i in self.leds.info:
                return self.leds.info[i]
        return None

    def on_move(self, ev):
        i = self._hit(ev)
        if i is None:
            C = self._hit_led(ev)
            if C is not None:
                self.tip.show(self.leds.describe(C), ev.x_root, ev.y_root)
                return
            self.tip.hide()
            return
        d = self.info[i]["d"]
        self.tip.show("SWITCH  %s\n"
                      "id %d   num %d   node %d  bit %d\n"
                      "hold to keep it closed\n"
                      "right-hold to RIP it (spinners)"
                      % (d["name"], d["id"], d["num"], d["node"], d["bit"]),
                      ev.x_root, ev.y_root)

    def on_press(self, ev):
        i = self._hit(ev)
        if i is None:
            return
        d = self.info[i]["d"]
        self.cv.itemconfig(i, fill="#ffd400")
        self.holding = (i, d["id"])
        self.drv.press(d["id"])

    def on_release(self, ev):
        if self.holding is None:
            return
        item, sw_id = self.holding
        self.holding = None
        self.drv.release(sw_id)
        self.cv.itemconfig(item, fill="#d8d8d8")

    def on_rip(self, ev):
        """Right-hold RIPS a switch (item 26) - see the artwork view."""
        i = self._hit(ev)
        if i is None:
            return
        d = self.info[i]["d"]
        self.cv.itemconfig(i, fill="#ff9500")
        self.ripping = (i, d["id"])
        self.drv.spin(d["id"], True)

    def on_rip_end(self, ev):
        if self.ripping is None:
            return
        item, sw_id = self.ripping
        self.ripping = None
        self.drv.spin(sw_id, False)
        self.cv.itemconfig(item, fill="#d8d8d8")

    def tick(self):
        """The LED block still says whether the emulator is up, which is the one
        thing this view can honestly report about it."""
        try:
            with open(LED_PATH, "rb") as f:
                d = f.read(PADLED_READ)
        except OSError:
            d = None
        if emu_gone(self, bool(d)):
            save_state(self.root)           # see Field.tick: this is the COMMON close
            self.root.destroy()             # the run ended; leave with it
            return
        # The same paced read the artwork view does: the dot beside each row
        # and the trough strip both come off it.
        poll_switches(self)
        state_msg = self._state_status()
        # ★ THE MAGIC IS NOT THE TEST FOR "IS THERE AN EMULATOR" (item 50,
        # caught on a live turtles_pro run). hwshim stamps the block on the
        # FIRST LED write it decodes, so a title that decodes none leaves it
        # zeroed for ever - and this window then reported "no emulator" over a
        # game that was plainly running its attract, which is David's item-40
        # complaint arriving by a second route. Worse, the grid lived in the
        # else-branch, so the one view built for these titles could never draw
        # on the one title that needed it.
        #
        # The three states are now distinct: the file is unreadable (no
        # emulator), it is readable and unstamped (a run with no LED data - the
        # switch half above still works and proves the run is there), or it is
        # stamped.
        if not d:
            self.status.config(text=state_msg
                               or "no emulator (dump/padled not readable)")
        else:
            # ★ ITEM 50: the swatch grid, driven off the same read. It is the
            # only LED feedback this view can give - the title has no artwork
            # and, on the four titles that land here, no table either. It runs
            # on an unstamped block too, where it correctly finds nothing.
            self.led_lit, self.led_total = self.leds.tick(d, time.perf_counter())
        if d and struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            self.status.config(
                text=state_msg
                     or " emulator up   NO LED DATA on this title: the shim has"
                        " decoded no LED writes at all   %s"
                        % (self.sw.balls.text() if self.sw.positions
                           else "no trough switches identified"))
        elif d:
            self.status.config(
                text=state_msg
                     or " emulator up   %d of %d LEDs lit   %d LED writes decoded"
                        "   %d coils addressed   %s"
                        % (self.led_lit, self.led_total,
                           struct.unpack_from("<I", d, 12)[0],
                           struct.unpack_from("<I", d, COIL_GEN_OFF + 4)[0]
                           if len(d) >= PADLED_READ else 0,
                           self.sw.balls.text() if self.sw.positions
                           else "no trough switches identified"))
        self.root.after(POLL_MS, self.tick)


def raise_existing():
    """True when a playfield window is already open - which is then brought to
    the front instead of a second one being created.

    watch.sh opens one per run and the window deliberately outlives the game, so
    without this they stack up: four were found layered on one another after an
    afternoon of runs, all reading the same shared memory, all equally live, and
    only the top one visible. Matching on the title needs no lock file and so
    leaves nothing stale behind after a crash.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.FindWindowW(None, WINDOW_TITLE)
        if not h:
            return False
        u.ShowWindow(h, 9)                  # SW_RESTORE
        u.SetForegroundWindow(h)
        return True
    except Exception:
        return False                        # never block on the guard failing


def poll_for_tables(root, load, on_rows, every_ms=2000, timeout_s=900,
                    _now=time.time):
    """Watch for a title's switch list ARRIVING while this window is open.

    THE SWITCH LIST CANNOT EXIST BEFORE A RUN AND THIS WINDOW OPENS DURING ONE.
    The game builds its switch table on the heap, so the id behind a name only
    reaches the outside world as the shim's `[sw]` dump a few seconds into a run
    (mktables.py's header has the whole reasoning). watch.sh therefore rebuilds
    the tables in the background, with --wait, while this window is already up.

    Everything that decides what this window SHOWS used to run once, at
    construction. So a window that opened a few seconds too early stayed a
    paragraph of explanatory text for the rest of the session, while the tables
    it was describing sat complete on disk. The first run of any title was
    therefore a run you could not click a switch in - and on a title with no
    usable artwork, which is most of them, that is the whole window.

    David hit it on james_bond_60th_le's first run, 2026-08-14: "without the
    switches here I can't test it". The tables were fine; only this window did
    not know they had arrived.

    A stat every two seconds costs nothing against a wasted run. `timeout_s`
    stops an abandoned window polling forever; `_now` and the two intervals are
    injected so a test can drive this in milliseconds with real Tk.
    """
    deadline = _now() + timeout_s

    def tick():
        rows = load()
        if rows:
            on_rows(rows)
            return
        if _now() < deadline:
            root.after(every_ms, tick)

    root.after(every_ms, tick)


def main():
    if raise_existing():
        # SAY SO, because from the outside this is a launch that started and
        # stopped with no window to show for it, and that is exactly what a
        # crash looks like. watch.sh keeps the launch's output now
        # (padplayfield.log) and reports a playfield that did not stay up, so
        # this line is the difference between "your window is the one already
        # on screen" and an unexplained failure.
        #
        # AND IT IS THE ONLY WAY TO SEE THE STRANDED-WINDOW CASE AT ALL (queue
        # item 38): a wedged WSLg window keeps its title bar long after there
        # is anything behind it, so FindWindowW answers about a window nobody
        # can see and this returns True for a desktop that shows nothing.
        # print() is a no-op under pythonw.exe with no redirection, and writes
        # to the run's log when watch.sh launched it.
        print("playfield: a window called %r already exists, so it was raised "
              "instead of a second one being opened. If nothing came to the "
              "front, that window is a leftover from an earlier run that WSL "
              "can no longer draw - Stop offers the WSL restart that clears "
              "one." % WINDOW_TITLE)
        return
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    # ARTWORK IF THE TITLE HAS IT, THE SWITCH LIST IF IT DOES NOT. Both are
    # real answers; which one applies is a property of the game, not of this
    # window. See load_switch_list() for why most titles are the second case.
    view = None
    # ARTWORK IF THERE IS ARTWORK AND ANYTHING TO DRAW ON IT.
    #
    # THIS USED TO ALSO REQUIRE SWITCH POSITIONS, and that is a different
    # question from "is there a playfield to show". Switch positions are the
    # one part of the table set that needs a RUN - the game builds its switch
    # list on the heap, so the id behind a name only reaches us in the shim's
    # dump about a minute in - while the artwork, the inserts and the coils all
    # come straight from the card. Requiring all four meant Jaws, which ships a
    # playfield drawing and 217 positioned devices, opened its FIRST run
    # showing the "no tables" label, and only became a playfield on the second.
    # Inserts and coils are worth looking at on their own.
    # ★ THE ARTWORK IS NO LONGER THE GATE (item 50). What decides this is
    # whether the title POSITIONS anything - the picture behind the markers is
    # a bonus, and requiring it sent james_bond_60th_le, which positions 138
    # devices, to the switch list. David: "if we can show them positionally
    # that is ideal... even if we can't show the playfield artwork".
    if layout_extent() and (load_switches() or load_leds() or load_coils()):
        view = Field(root)
    else:
        rows = load_switch_list()
        if not rows:
            waiting = tk.Label(
                root, padx=20, pady=20, justify="left", font=("Consolas", 10),
                text=("No tables for %s yet - WAITING for them." '\n\n'
                      "They are built from the title's own files, not" '\n'
                      "shipped: mktables.py reads the game binary for" '\n'
                      "positions and the run log for the switch list." '\n\n'
                      "  tables : %s" '\n'
                      "  game   : %s" '\n\n'
                      "The switch list only exists once the game has" '\n'
                      "published its table, a few seconds into a run, so" '\n'
                      "the first start of a title lands here first. This" '\n'
                      "window now picks them up by itself when they arrive.")
                % (GAME, TDIR, gameinfo.game_dir(GAME)))
            waiting.pack()

            # ★ THE TABLES LAND *DURING* THIS RUN, AND THIS WINDOW USED TO MISS
            # THEM FOR GOOD.
            #
            # The switch list cannot be built before a run: the game builds its
            # switch table on the heap, so the id behind a name only reaches us
            # as the shim's [sw] dump a few seconds in (mktables.py's own header
            # says so). watch.sh therefore rebuilds in the background with
            # --wait while this window is already up. But everything above runs
            # ONCE, at construction, so the window that opened a few seconds too
            # early stayed a paragraph of text for the whole session - and the
            # tables it was describing were sitting on disk the entire time.
            #
            # David hit exactly that on james_bond_60th_le's first run
            # (2026-08-14): "without the switches here I can't test it". The
            # tables were complete; only this window did not know.
            #
            # So poll. A stat every two seconds costs nothing next to a wasted
            # run, and the swap is the same two branches as the construction
            # above, so a title that has artwork still gets the artwork view.
            def _swap_in(fresh):
                nonlocal view
                waiting.destroy()
                if layout_extent() and (
                        load_switches() or load_leds() or load_coils()):
                    view = Field(root)
                else:
                    view = Schematic(root, fresh)

            poll_for_tables(root, load_switch_list, _swap_in)
        else:
            view = Schematic(root, rows)
    pos = load_state().get("playfield_pos")
    if pos and _onscreen(root, *pos):
        root.geometry("+%d+%d" % (pos[0], pos[1]))

    def bye():
        # OPEN ANYTHING STILL HELD BEFORE THE PROCESS GOES. Closing the window
        # mid-hold otherwise leaves scr_held[] made, and nothing on this side
        # exists any more to clear it - the game would see a stuck switch for
        # the rest of the run. The keyboard pipe's close is its EOF, and the
        # helper releases its own held set on the other side (swkeys.py).
        if view is not None:
            view.drv.release_all()
            if getattr(view, "keys", None) is not None:
                view.keys.close()
        save_state(root)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", bye)
    root.mainloop()


if __name__ == "__main__":
    # The finer timer is asked for around the WHOLE session and released after
    # it, rather than per frame: timeBeginPeriod is a process-wide request with
    # a reference count, and pairing it per tick would be 30 syscalls a second
    # to say the same thing. try/finally so a crash still hands the system tick
    # back - leaving it raised is a battery-life bug in every other process.
    fine = fine_timers()
    try:
        main()
    finally:
        if fine:
            coarse_timers()
