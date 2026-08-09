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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilact
import gameinfo
import mktables
import padpath
import padsw

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
SW_PATH = os.path.join(padpath.dump() or "", "padsw")
PADSW_MAGIC = padsw.MAGIC
SW_HELD, SW_COIN_DOOR = padsw.OFF_MRG, 33

#: This directory, as WSL sees it - the helpers below are run inside WSL through
#: interop, so they cannot be handed the Windows path this file was loaded from.
#: `wslpath -u` is asked instead of assuming the checkout is on C:.
WSL_DIR = padpath.to_wsl(padpath.RIG)

#: Offsets into padled.h's block. Hard-coded because Python cannot include the
#: header; the header lists them next to the struct and says APPEND ONLY, so a
#: version-1 shim and a version-2 reader still agree on everything below `coil`.
PADLED_MAGIC = 0x44454C50
#: `decoded` (12) is LED writes that landed. `skipped` (16) is frames that
#: LOOKED like indexed LED writes and did not fit any shape the shim decodes -
#: padled.h has counted it since version 1 and nothing has ever read it. It is
#: the difference between "the game is not lighting anything" and "the game is
#: lighting plenty and we are dropping it", which is the single question this
#: window could never answer about itself.
LED_DECODED_OFF, LED_SKIPPED_OFF = 12, 16
LED_HDR, LED_IDX = 20, 96
COIL_OFF, COIL_N = 1556, 16          # wrapping fire counter per (node, index)
LVL_OFF = COIL_OFF + 16 * COIL_N     # last drive byte
COIL_GEN_OFF = LVL_OFF + 16 * COIL_N
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

#: Read the coin door every Nth tick instead of every tick. It is a whole extra
#: round trip across the VM boundary (3.35 ms, measured) for a switch a human
#: flips by hand; 4 Hz is still faster than anyone can act on the answer.
DOOR_EVERY = max(1, int(TARGET_FPS / 4))

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

    def release_all(self):
        """Open everything we still hold, and WAIT for it.

        On window close this is the last chance: a daemon worker dies with the
        process, so an unqueued release would simply never happen and the game
        would keep seeing a made switch until the next run rebuilt the block.
        """
        with self._lock:
            ids = sorted(self.held)
            self.held.clear()
        for sw_id in ids:
            self.q.put((sw_id, 0))
        if ids:
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


def state_run(script, slot="quicksave"):
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
    if sys.platform == "win32":
        cmd = ["wsl.exe", "-u", "root", "-e", "bash",
               "%s/%s" % (WSL_DIR, script), slot]
    else:
        # The native-Linux path: run it plainly; without root the script's own
        # "needs root" line lands in the status bar, which is the honest hint.
        cmd = ["bash", os.path.join(HERE, script), slot]
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


def load_switches():
    """switch_xy.txt: id node bit NAME... x y"""
    return [dict(id=int(p[0]), node=int(p[1]), bit=int(p[2]),
                 name=" ".join(p[3:-2]), x=int(p[-2]), y=int(p[-1]))
            for p in _rows(os.path.join(TDIR, "switch_xy.txt"), 6)]


def load_leds():
    """led_io.txt: node index NAME... x y conn image"""
    out = []
    for p in _rows(os.path.join(TDIR, "led_io.txt"), 6):
        if p[-1] != "playfield":
            continue
        try:
            out.append(dict(node=int(p[0]), index=int(p[1]),
                            x=int(p[-4]), y=int(p[-3]),
                            name=" ".join(p[2:-4])))
        except ValueError:
            continue
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
#: against the boot enumeration. Used here to turn a coil's (group, index) into
#: the (node, index) the shim publishes fires under.
GROUP_NODE = {4: 0, 5: 1, 6: 8, 7: 9}


def load_coils():
    """device_xy.txt: class NAME... x y w h grp index conn image

    THE CONNECTOR COLUMN IS EMPTY FOR EVERY COIL, which is how this read `h` as
    the group and the group as the index for a whole release - every coil
    tooltip said "group 20 index 6". devicexy.py now writes "-" so the field
    count is uniform, and the assert below refuses to trust a row that does not
    land on a board the enumeration knows, rather than drawing a confident lie.
    """
    out = []
    for p in _rows(os.path.join(TDIR, "device_xy.txt"), 10):
        if p[0] != "coil" or p[-1] != "playfield":
            continue
        try:
            # Eight fields follow the name: x y w h grp index conn image.
            group, index = int(p[-4]), int(p[-3])
            c = dict(name=" ".join(p[1:-8]), x=int(p[-8]), y=int(p[-7]),
                     group=group, index=index,
                     node=GROUP_NODE.get(group) if index < COIL_N else None)
        except ValueError:
            continue
        out.append(c)
    return out


def load_switch_list():
    """switch_list.txt: id num node bit NAME...  (see swtable.py)

    The fallback, and the only thing available for most titles. It has no
    positions because most titles HAVE no positions: Godzilla Pro 1.15.0 ships a
    graphical device test mode with a playfield drawing and an XY record per
    device, and TMNT 1.59 ships neither - no images/Test directory, and the word
    "playfield" appears in its binary only in adjustment help text.
    """
    out = []
    for p in _rows(os.path.join(TDIR, "switch_list.txt"), 5):
        try:
            out.append(dict(id=int(p[0]), num=int(p[1]), node=int(p[2]),
                            bit=int(p[3]), name=" ".join(p[4:])))
        except ValueError:
            continue
    return out


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


class StateOps:
    """Save state / Load state (item 13), shared by BOTH views - a title with
    no artwork still saves and loads, because savegame.sh/loadgame.sh know
    nothing about drawings. Each view creates its own `self._state_btns` in
    its own layout (Field: canvas buttons bottom-left; Schematic: the top
    bar) and wires `_state_status()` into its own tick's status writes."""

    def run_state(self, script):
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
            r = state_run(script)

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


class Field(StateOps):
    def __init__(self, root):
        from PIL import Image, ImageTk
        self.root = root
        self.switches = load_switches()
        self.leds = load_leds()
        self.coils = load_coils()
        self.last = None

        img = Image.open(PF_PNG).convert("RGB")
        self.scale = pick_scale(root, img.height)
        w, h = int(img.width * self.scale), int(img.height * self.scale)
        # KEPT, not discarded after the PhotoImage is made: each fixture blends
        # toward the pixel that is actually behind it (see blend()), and that
        # pixel has to be sampled from somewhere. Sampled once at build time,
        # never during a tick.
        self._art = img.resize((w, h), Image.LANCZOS)
        self.bg = ImageTk.PhotoImage(self._art)

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
        self.cv = tk.Canvas(root, width=w, height=h, highlightthickness=0,
                            bg="black")
        self.cv.pack(side="top")
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)

        self.info = {}          # canvas item -> dict describing it
        self.fixtures = group_fixtures(self.leds)
        self.coil_items = {}    # (node, index) -> canvas item
        self.coil_seen = {}     # (node, index) -> last fire counter read
        self.coil_until = {}    # (node, index) -> ms after which the flash ends
        self.coil_drawn = {}    # (node, index) -> last hot/cold drawn
        self.fps = 0.0          # measured, EWMA, shown in the status bar
        self._t_last = None
        self._door, self._door_n = False, 1
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
        # THE FADE LAYER (padled.h version 3). overlay maps a channel
        # (node, idx) to its running pulse envelope; while one is active the
        # channel's level comes from the envelope, not from val[]. _fade_seen
        # is the ring head already consumed - primed on the FIRST read so a
        # window opened mid-run does not replay a backlog of old pulses.
        self.overlay = {}
        self._fade_seen = None
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

        self._add_switches(self.switches)
        # When to look for a switch table that did not exist when this window
        # opened. See _pick_up_switches().
        self._sw_next = time.monotonic() + SWITCH_POLL_S

        self._place_actions(w, h)

        self.tip = Tip(root)
        self.drv = SwitchDriver()
        self.holding = None            # (canvas item, switch id) while held
        # PRESS and RELEASE, not <Button-1>: a switch is closed for as long as
        # the mouse is down. Tk's implicit grab delivers the release to this
        # canvas even if the pointer has left it, so a drag off the marker still
        # opens the switch.
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Motion>", self.on_move)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.tick()

    def _add_switches(self, rows):
        """Draw a clickable marker for each switch, above everything else."""
        for S in rows:
            x, y, r = S["x"] * self.scale, S["y"] * self.scale, 6
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    outline="#2a8cff", width=2)
            self.info[i] = dict(kind="switch", d=S)

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
        self._add_switches(rows)

    def _sample(self, x, y):
        """The artwork's colour under a marker, averaged over its footprint.

        One pixel is not enough: inserts sit on high-contrast art, and a
        single sample that lands on a black outline makes the whole fixture
        blend toward black while its neighbour blends toward white. A small
        box average is stable and costs nothing here - this runs once per
        fixture at build time, never in a tick.
        """
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
                    "hold to keep it closed"
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
        self._state_btns = []
        for label, script in (("Save state", "savegame.sh"),
                              ("Load state", "loadgame.sh")):
            self._state_btns.append(
                tk.Button(self.cv, text=label, width=11,
                          command=lambda s=script: self.run_state(s)))
        x = self.ACT_PAD
        for b in self._state_btns:
            self.cv.create_window(x, y, anchor="sw", window=b)
            x += b.winfo_reqwidth() + self.ACT_GAP

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

        CACHED, and re-read only every DOOR_EVERY ticks. This is a SECOND
        round trip across the VM boundary, and it used to happen on every
        tick - at 60 fps that is 120 crossings a second for a switch a human
        toggles by hand perhaps twice an hour. Measured: 3.35 ms, the same as
        the LED read, because a 9p round trip costs what it costs regardless
        of the 72 bytes it carries.

        The merged array is the right source and it is written by the GUEST, so
        it is empty until the game is up and reading switches. An empty merge
        would read as "door open" and put a 48V warning on a window that is
        simply early, so fall back to the keyboard's half until the guest has
        published once. Which half answered is not worth showing; being wrong
        for the first few seconds of every run would have been.
        """
        self._door_n -= 1
        if self._door_n > 0:
            return self._door
        self._door_n = DOOR_EVERY
        try:
            with open(SW_PATH, "rb") as f:
                d = f.read(SW_HELD + 64)
        except OSError:
            return False
        if len(d) < SW_HELD + 64 or struct.unpack_from("<I", d, 0)[0] != PADSW_MAGIC:
            return False
        off = (SW_HELD if struct.unpack_from("<I", d, padsw.OFF_MRG_GEN)[0]
               else padsw.OFF_HELD)
        self._door = not d[off + SW_COIN_DOOR]
        return self._door

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
            if d:
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
    """

    ROW_H = 19
    COL_W = 300

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
        # Save/Load state on the bar's right (item 13, same pair as the
        # artwork view's bottom-left cluster): a title with no artwork still
        # saves and loads - the wrappers know nothing about drawings. Packed
        # side="right", so LOAD goes first to end up rightmost and the pair
        # reads Save | Load left-to-right, matching the artwork view.
        self._state_btns = []
        for label, script in (("Load state", "loadgame.sh"),
                              ("Save state", "savegame.sh")):
            b = tk.Button(bar, text=label, width=11,
                          command=lambda s=script: self.run_state(s))
            b.pack(side="right", padx=(0, 4), pady=2)
            self._state_btns.append(b)

        by_node = {}
        for sw in switches:
            by_node.setdefault(sw["node"], []).append(sw)
        cols = sorted(by_node)
        tall = max(len(v) for v in by_node.values()) + 2
        w = self.COL_W * len(cols)
        h = self.ROW_H * tall + 8
        h = min(h, root.winfo_screenheight() - 160)

        self.cv = tk.Canvas(root, width=w, height=h, bg="#101010",
                            highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.info = {}
        for ci, node in enumerate(cols):
            x = ci * self.COL_W + 10
            self.cv.create_text(x, 12, anchor="w", fill="#7ecbff",
                                font=("Consolas", 10, "bold"),
                                text="node %d" % node)
            for ri, sw in enumerate(sorted(by_node[node], key=lambda s: s["bit"])):
                y = 30 + ri * self.ROW_H
                i = self.cv.create_text(
                    x, y, anchor="w", fill="#d8d8d8", font=("Consolas", 9),
                    text="%3d  %-28s" % (sw["id"], sw["name"][:28]))
                self.info[i] = dict(kind="switch", d=sw)

        # width=1 for the same reason as Field's bar: the text must never be
        # what sizes the window.
        self.status = tk.Label(root, text="", anchor="w", bg="#111", fg="#ddd",
                               font=("Consolas", 9), width=1)
        self.status.pack(fill="x")
        self.tip = Tip(root)
        self.drv = SwitchDriver()
        self.holding = None
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Motion>", self.on_move)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.tick()

    def _hit(self, ev):
        for i in reversed(self.cv.find_overlapping(ev.x - 2, ev.y - 8,
                                                   ev.x + 2, ev.y + 8)):
            if i in self.info:
                return i
        return None

    def on_move(self, ev):
        i = self._hit(ev)
        if i is None:
            self.tip.hide()
            return
        d = self.info[i]["d"]
        self.tip.show("SWITCH  %s\n"
                      "id %d   num %d   node %d  bit %d\n"
                      "hold to keep it closed"
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
        state_msg = self._state_status()
        if not d or struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            self.status.config(text=state_msg
                               or "no emulator (dump/padled not readable)")
        else:
            self.status.config(
                text=state_msg
                     or " emulator up   %d LED writes decoded   %d coils addressed"
                        "   (no positions for this title: see swtable.py)"
                        % (struct.unpack_from("<I", d, 12)[0],
                           struct.unpack_from("<I", d, COIL_GEN_OFF + 4)[0]
                           if len(d) >= PADLED_READ else 0))
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


def main():
    if raise_existing():
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
    if PF_PNG and os.path.exists(PF_PNG) and (
            load_switches() or load_leds() or load_coils()):
        view = Field(root)
    else:
        rows = load_switch_list()
        if not rows:
            tk.Label(root, padx=20, pady=20, justify="left", font=("Consolas", 10),
                     text=("No tables for %s yet." '\n\n'
                           "They are built from the title's own files, not" '\n'
                           "shipped: mktables.py reads the game binary for" '\n'
                           "positions and the run log for the switch list." '\n\n'
                           "  tables : %s" '\n'
                           "  game   : %s" '\n\n'
                           "The switch list only exists once the game has" '\n'
                           "published its table, a few seconds into a run, so" '\n'
                           "the first start of a title can land here.")
                     % (GAME, TDIR, gameinfo.game_dir(GAME))).pack()
        else:
            view = Schematic(root, rows)
    pos = load_state().get("playfield_pos")
    if pos and _onscreen(root, *pos):
        root.geometry("+%d+%d" % (pos[0], pos[1]))

    def bye():
        # OPEN ANYTHING STILL HELD BEFORE THE PROCESS GOES. Closing the window
        # mid-hold otherwise leaves scr_held[] made, and nothing on this side
        # exists any more to clear it - the game would see a stuck switch for
        # the rest of the run.
        if view is not None:
            view.drv.release_all()
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
