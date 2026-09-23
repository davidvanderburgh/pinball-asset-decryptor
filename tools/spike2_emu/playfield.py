#!/usr/bin/env python3
"""playfield.py - the virtual playfield: click switches, watch the inserts light.

Run it on WINDOWS, next to the emulator, while watch.sh has the game up. watch.sh
starts it for you through WSL interop; to run it by hand use pythonw so no
console window appears:

    pythonw tools\\spike2_emu\\playfield.py

WHY WINDOWS AND NOT WSL, because the obvious choice does not work: WSL here has
no GUI toolkit at all - no tkinter, no gi/Gtk, no Qt - and installing one needs
a sudo this rig does not have. PAD's own bundled Windows Python carries what
the window needs, because the app's own window is drawn with it.

THE WINDOW IS A WEB PAGE (2026-09-23, the app's cut-over from Tk): pfpage/ is
the page, drawn in the app's own design, and pfweb.py shows it - a native
WebView2 window on Windows (pywebview), GTK WebKit in the macOS container and
on Linux desktops, a browser app window or a plain tab as the fallbacks. This
file keeps every decision; the page only draws what it is told and sends back
what was pressed.

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
100%, drawn at 57% to 100% opacity over the artwork behind them (real alpha
on the page; the Tk window had to fake it by mixing each marker's colour
toward an artwork pixel sampled at build time). Both scales
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
import io
import json
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ballmodel
import coilact
import coilmap
import devicexy
import gameinfo
import keybinds
import mktables
import padpath
import padsw
import pfweb
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
    if __name__ == "__main__":
        # Better than a window titled "None" drawing nothing. watch.sh always
        # passes the title on the command line, so this is the by-hand case.
        sys.exit("playfield.py: no title - pass one, or set PAD_GAME.\n"
                 "  pythonw playfield.py godzilla_pro")
    # Imported as a library: the window classes take their title explicitly
    # (LcdPanel(root, "batman")), so a resolvable global is not required.
    # The tests import this module, and under plain pytest argv[1] happens
    # to be "tests" and passes for a title; a pytest-xdist worker's argv
    # carries no such passenger, and a machine with no rig state has
    # nothing else to answer with - exiting here killed the import and
    # every test in five modules with it.
    GAME = "unknown"
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

#: VILLAIN VISION (padlcd.h, item 83): the lcdnode's display-id state. Same
#: reopen-per-poll rule as LED_PATH - a held handle reads a frozen cache over
#: \\wsl.localhost.
LCD_PATH = os.path.join(padpath.dump() or "", "padlcd")

#: The LCD clip decoder. PIL, not Tk, for two measured reasons: Tk's
#: "gif -index N" has no frame cursor, so every call re-parsed the clip from
#: byte 0 (~139 ms per frame at a 150-frame tail - the documented UI-freeze
#: class), while PIL seeks INCREMENTALLY at ~1 ms/frame flat; and the clips
#: are lossless WEBP now (David, 2026-08-24: GIF's 8-bit palette "looks off
#: ... like it's not rendering the correct bit depth" - it was), which Tk
#: cannot read at all. Pillow is a hard app dependency (requirements.txt,
#: and Field.__init__ imports it unguarded for the playfield artwork); this
#: guard only decides whether the TVs MOVE or stay on their stills, so a
#: stripped environment degrades instead of crashing the window.
try:
    from PIL import Image as _PILImage
except Exception:                                           # noqa: BLE001
    _PILImage = None

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
#: 33 is the door's id on the GODZILLA generation only - the wire (node 0,
#: bit 23) is universal across every derived list, the id is a table index
#: (item 73: 34 on aerosmith, 36 on batman). SwitchWatch resolves the real
#: id from the title's own rows; this constant is the no-table fallback.
SW_HELD, SW_COIN_DOOR = padsw.OFF_MRG, 33
DOOR_NODE, DOOR_BIT = 0, 23

#: The key binds padglhost exports at startup (item 39) - the content of the
#: retired Controls window, drawn by THIS window's key panel instead. Same
#: directory as padled and padsw; keybinds.py owns the parse. PAD_PF_BINDS
#: is the offline escape hatch, the same shape as PAD_SW_FILE above: a file
#: written by hand turns the panel into something judgeable without a run.
BINDS_PATH = (os.environ.get("PAD_PF_BINDS")
              or os.path.join(padpath.dump() or "", "padbinds"))

#: The ball feeder's status (PAD-134): `fed N`, then its newest lines. Written
#: by ballfeed.publish() inside WSL, read here for the key panel's BALLS
#: section. PAD_PF_BALL is the offline hatch, the PAD_PF_BINDS shape.
BALL_PATH = (os.environ.get("PAD_PF_BALL")
             or os.path.join(padpath.dump() or "", "padball"))


def read_ball_status(path=None):
    """(fed, [lines]) from the feeder's status file, or (None, []) without one.

    None and not 0, for the same reason trough.Balls has an unknown total: a
    window whose run has no feeder yet - or PAD_BALL_FEED=0 - has not fed
    nothing, it has nobody counting, and the line should not claim a zero.
    """
    try:
        with open(path or BALL_PATH, encoding="utf8", errors="replace") as f:
            lines = [ln.rstrip("\n") for ln in f]
    except OSError:
        return None, []
    fed = None
    if lines and lines[0].startswith("fed "):
        try:
            fed = int(lines[0][4:])
        except ValueError:
            fed = None
        lines = lines[1:]
    return fed, [ln for ln in lines if ln.strip()]

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
#: Version 4, the ADDRESSED plane (padled.h): one byte per (node, index) the
#: wire has spoken to, whether or not that frame carried a level. It answers
#: the membership question `val` only ever answered by accident - a lamp had to
#: be LIT while somebody was watching to earn a cell - and on the swelf
#: generation half the lamp commands carry no level at all, so without this
#: whole boards stay invisible however long the run.
SEEN_OFF = FADE_ENT_OFF + FADE_RING * FADE_STRIDE
WIDE_DECODED_OFF = SEEN_OFF + 16 * LED_IDX
WIDE_SKIPPED_OFF = WIDE_DECODED_OFF + 4
#: What a version-3 shim publishes, and the most a version-3 FILE can hold.
#: Kept as its own number because the reader must still work against one.
PADLED_READ_V3 = SEEN_OFF
PADLED_READ = WIDE_SKIPPED_OFF + 4

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

#: The action row: label, the script it runs, and its argument (None for a
#: script that takes none). ONE list for BOTH views (item 60). The artwork view
#: draws these as canvas widgets beside the plunger and the schematic packs them
#: on its top bar - different placements, argued separately and both kept - but
#: WHICH actions the window offers is one fact, and it was two:
#: `Field._place_actions()` had the row, `Schematic` never had an equivalent, so
#: on a title that ships no device table nothing in the window reached plunge.py
#: at all. An action added here appears in both windows.
#:
#: IT CARRIES THE SCRIPT NAME as of item 59, and that is exactly what "Clear
#: alerts" needed: the row used to be three plunge.py verbs, so a fourth button
#: running a different helper could not be expressed without either a second
#: list or a special case - and a second list is the thing item 60 collapsed.
#:
#: "Clear switch alerts" (first "Clear alerts"; renamed PAD-134, when it moved
#: under the key panel's SERVICE buttons) is David's ask (2026-08-21, watching
#: turtles_pro still list
#: twelve CHECK SWITCH rows after a boot-time exercise had already run: "maybe
#: we need an 'opt-in' button that clears them?"). It works every safe switch
#: once so the game's own no-usage audit sees usage. swexercise.py's header has
#: the argument, including WHY the boot-time pass can be too early on some
#: titles - which is what earns this button its place rather than making it a
#: duplicate of something automatic.
#: ★ "INSERT COIN" IS FIRST BECAUSE THE ROW WAS UNUSABLE WITHOUT IT (PAD-128,
#: DragonRR 2026-09-11: "If I click plunge a ball goes out but again nothing
#: really happens"). Pressing Start on a machine with no credits does exactly
#: nothing and does it SILENTLY - plunge.py's do_coin() carries the
#: measurement, and it cost item 6 five runs - so a window offering Start,
#: Plunge and Reset but no coin offers no way to start a game at all. The coin
#: has always been on the keyboard (LEFT COIN, the "5" in the legend), which is
#: why this went unnoticed: a mouse-only session cannot reach it.
WINDOW_ACTIONS = (("Insert coin", "plunge.py", "coin"),
                  ("Start", "plunge.py", "start"),
                  ("Plunge", "plunge.py", "plunge"),
                  ("Reset balls", "plunge.py", "reset"),
                  ("Clear switch alerts", "swexercise.py", None))

#: How much of a helper's own answer the status bar carries. Long enough for
#: plunge.py's longest real reply (Start's two lines, ~100 chars) and short
#: enough that it cannot push the window wider than the artwork.
HELPER_MSG_CAP = 160


def helper_message(script, r):
    """One status-bar line from a helper's own output.

    ★ THE WINDOW USED TO THROW THIS AWAY, AND THAT IS MOST OF "NOTHING
    HAPPENED" (PAD-128). `SwitchDriver.run_script` spawned the helper on a
    thread and dropped its CompletedProcess, so every sentence plunge.py
    prints - "Start pressed / NOTE: a game needs CREDITS", "the trough is
    empty - nothing to eject", "shooter lane opened (ball launched)" - went
    nowhere. A user pressing Plunge on a machine with no game in progress got
    the same silence as one pressing it with a ball already in the lane, and
    the two need different next moves.

    EVERY LINE, JOINED, rather than the last one: plunge.py's outcome is the
    FIRST line and its advice is the second ("Start pressed" then the credit
    note), and the save-state ladder's "last tagged line" rule - which exists
    because savegame.sh ends on a bare FAILED - would show the advice without
    the outcome. stderr comes after stdout so item 49's "using godzilla_pro's
    compiled ids" warning is visible rather than buried.
    """
    if r is None:
        return "%s did not run" % script
    lines = [ln.strip() for ln in
             ((r.stdout or b"").decode("utf8", "replace").splitlines()
              + (r.stderr or b"").decode("utf8", "replace").splitlines())
             if ln.strip()]
    if not lines:
        return "%s: no output" % script
    text = "   ".join(lines)
    if len(text) > HELPER_MSG_CAP:
        text = text[:HELPER_MSG_CAP - 1] + "…"
    return text



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

    def run_script(self, script, *args, done=None):
        """A helper that is not a switch edge (plunge.py, coilact.py).

        Off the queue and on its own thread: these take seconds, and a hold's
        release must not wait behind one.

        `done` is called ON THAT THREAD with the CompletedProcess (or None if
        it did not run at all), which is how the window gets to say what the
        helper said - see `helper_message()` for why the answer used to be
        dropped here and what that cost. A raising callback must not kill the
        thread silently mid-action, so it is guarded.
        """
        def work():
            r = wsl_run(script, *args)
            if done is not None:
                try:
                    done(r)
                except Exception:                           # noqa: BLE001
                    pass

        threading.Thread(target=work, daemon=True).start()

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


def wsl_head(root=False):
    """``wsl.exe`` plus the selector that says WHICH Linux, and ``-u root``.

    ★ THE DISTRO HAS TO BE NAMED, and leaving it out is what made every click in
    this window do nothing (David, 2026-09-09). A bare ``wsl.exe -e`` runs in the
    DEFAULT distro, which was fine for as long as there was only one - and the
    app now runs the emulator inside its own PAD-Runtime. So the game sat in one
    Linux while every switch this window drove was delivered into another, wrote
    a ring nobody was reading, and vanished. The game window's keyboard kept
    working throughout, because the renderer is a process INSIDE the run and its
    keys never cross a distro boundary; only this window does. That asymmetry is
    exactly what the report described.

    ``PAD_WSL_DISTRO`` is already handed to this process for the purpose (see
    pad_export_win in padpath.sh); it is simply never a guess."""
    head = ["wsl.exe"]
    distro = os.environ.get("PAD_WSL_DISTRO")
    if distro:
        head += ["-d", distro]
    if root:
        head += ["-u", "root"]
    return head


def wsl_rig_env():
    """``PAD_ROOT=<posix path>`` for a helper we are calling back into WSL.

    THE OTHER HALF OF THE SAME BUG. Naming the distro gets the helper into the
    right Linux; it still has to find the right RIG inside it. A fresh
    ``wsl.exe`` starts with that distro's own defaults, so padpath would resolve
    ``$HOME/spike2root`` - and under the runtime distro the rig actually lives on
    a shared volume somewhere else entirely, so the helper would write a third
    ring nobody reads.

    ``PAD_ROOT`` reaches this process translated to its WINDOWS spelling (WSLENV
    marks it ``/p``), which is the wrong thing to send back; ``PAD_ROOT_WSL``
    carries the same directory in its POSIX spelling for exactly this round
    trip. Absent - an older watch.sh, or a run started by hand - this returns
    nothing and the helper resolves the rig the way it always did."""
    root = os.environ.get("PAD_ROOT_WSL")
    return ["PAD_ROOT=%s" % root] if root else []


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
        cmd = (wsl_head() + ["-e", "env"] + env + wsl_rig_env()
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
        cmd = (wsl_head(root=True) + ["-e", "env"] + wsl_rig_env()
               + ["bash", "%s/%s" % (WSL_DIR, script), slot] + extra)
    else:
        # The native-Linux path: run it plainly; without root the script's own
        # "needs root" line lands in the status bar, which is the honest hint.
        cmd = ["bash", os.path.join(HERE, script), slot] + extra
    try:
        return subprocess.run(cmd, capture_output=True, timeout=240,
                              creationflags=_CREATE_NO_WINDOW)
    except Exception:                                       # noqa: BLE001
        return None


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

#: THIS TITLE'S device-table group -> bus node map, derived (item 53), with
#: godzilla's old constant as the last rung of coilmap.group_node()'s ladder.
#:
#: It used to be `coilmap.GROUP_NODE` itself - one title's measurement, used
#: for every title - and what that cost was the whole of item 53: on
#: james_bond_60th_le the playfield devices are groups 8 and 9, which that dict
#: has no key for, so all 73 lamps and all 16 coils were drawn dark with a
#: position and no wire address while the shim decoded 36351 lamp writes on
#: precisely those boards. coilmap.py's group_node() carries the derivation and
#: the evidence; this is where the artwork view picks it up.
#:
#: DERIVED ONCE, HERE, beside the rows it is derived FROM. Every consumer below
#: reads this name, so the window cannot end up with two answers - and the
#: tables are read once at import for the same reason they always were.
GROUP_NODE = coilmap.group_node_for(
    os.path.join(TDIR or "", "device_xy.txt"), dev_rows=DEV_ROWS)


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
            for p in _rows(os.path.join(TDIR or "", "switch_xy.txt"), 6)]
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
    reason WAS that led_io.txt could not carry these rows at all on some
    titles: ledio.py wrote only the four groups godzilla's constant could turn
    into a node, so james_bond_60th_le - whose playfield lamps are groups 8 and
    9 - lost every one of them before the file was written. Item 53 fixed that
    at the source (ledio.py takes this title's derived map now, so the file
    carries them too), and this still reads the device table, because it is
    where the POSITIONS are and there is no reason to go through a second file
    to reach them.

    `node` is None only for a lamp whose group NOTHING could resolve - a
    POSITION is known and a WIRE ADDRESS is not. Drawn dark, and the tooltip
    says which of the two is missing rather than leaving a lamp that never
    lights unexplained. Bond's group 7, its 24 backbox lamps, is the live
    example: it is not on the layout image, and the derivation deliberately
    leaves it unresolved rather than let godzilla's map call it node 9, which
    on that title is a playfield board.
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
            # `group` rides along so a fixture with no wire address can still
            # say WHICH board it is on (item 50) - the node is None precisely
            # because the group is not one GROUP_NODE knows.
            f = fixtures[stem] = dict(name=stem, channels={}, xs=[], ys=[],
                                      group=L.get("group"))
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


def load_coils():
    """The playfield's coils, parsed by coilmap.py.

    THE PARSE MOVED because ballfeed.py needs the same rows on the other side
    of the VM boundary and cannot import this file. What it does has not
    changed and coilmap.py keeps the reason it is written the way it is: the
    connector column is empty for every coil, so counting fields from the LEFT
    read `h` as the group for a whole release and every coil tooltip said
    "group 20 index 6".
    """
    return [c for c in coilmap.load(os.path.join(TDIR or "", "device_xy.txt"))
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
    if not TDIR:
        # No table dir at all: no card has been prepared on this machine
        # (a bare CI runner is the honest case).  Every reader below is
        # already silent about a MISSING file; only the join minded, and
        # item 73 made this call unconditional, so it minded on import.
        return []
    return trough.load_list(os.path.join(TDIR, "switch_list.txt"))


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
        self.door_id = SW_COIN_DOOR
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

        The door id re-resolves here too (item 73): the wire (0,23) is
        universal, the id is the title's own. The ARTWORK view feeds this
        POSITIONED rows only (load_switches()), and the cabinet has no
        playfield position, so when the given rows carry no (0,23) the full
        switch list is consulted directly - otherwise the 48V banner would
        keep reading godzilla's 33 on every artwork window.
        """
        self.positions, self.how = trough.find(rows)
        for source in (rows or [], load_switch_list()):
            hit = next((r for r in source
                        if r.get("node") == DOOR_NODE
                        and r.get("bit") == DOOR_BIT), None)
            if hit is not None:
                self.door_id = hit["id"]
                break
        # The shooter lane, by NAME (ballmodel.LANE_NAME is the same words in
        # every switch list on this disk). PAD-134: a ball waiting in the lane
        # is neither home nor in play, and the BALLS line says so.
        self.lane_id = None
        for source in (rows or [], load_switch_list()):
            hit = next((r for r in source
                        if (r.get("name") or "").upper().strip()
                        == "SHOOTER LANE"), None)
            if hit is not None:
                self.lane_id = hit["id"]
                break
        return bool(self.positions)

    def poll(self):
        """Re-read on the pacing above; True when this tick actually read."""
        self._n -= 1
        if self._n > 0:
            return False
        self._n = self.every
        self.mrg = read_merged()
        # ★ THE DOOR ID IS NOT ALWAYS AN ADDRESS THIS ARRAY HAS (2026-09-08).
        # is_made() below has bounded every other read of `mrg` since it was
        # written; this one indexed it bare, and on foo_fighters_le 1.04.0 the
        # coin door resolves to id 583 against a 256-entry array - an
        # IndexError out of a paced callback, so the window stops updating
        # entirely. See addressable() for where those ids come from and why
        # the answer here is "unknown", not a guess: an unreadable door read
        # as OPEN would put a 48 V warning on a closed one.
        self.door = self.is_made(self.door_id) is False
        self.balls.update(self.closed())
        return True

    def addressable(self, sw_id):
        """Can this rig read and poke `sw_id` at all?

        ★ NOT EVERY ID IN A SWITCH LIST IS ONE (2026-09-08, peanuts: "for Foo
        Fighters and The Munsters, the list of Switches is still incomplete").
        The shim's arrays are padsw.MAX_ID long - 256 since item 73 widened
        them from 128 - and every id in them is the game's own switch id. The
        DERIVED reader (item 102) has no entry table to read one from on the
        48-byte generation, so it numbers its rows by position in the device
        ARRAY, and those run far past 256: foo_fighters_le 1.04.0 to 847,
        elvira3 1.13.0 to 629, munsters_le 1.28.0 to 268.

        foo_fighters_le is the proof that the two are different numbers and
        not merely a bigger version of the same one: 1.03.0 and 1.04.0 are the
        same machine with the same 105 switches, 1.03.0 has a stored address
        so it is read the old way and puts the coin door at id 34, and 1.04.0
        falls through to the derived reader and puts it at 583.

        So a row past the end is not addressable, and this is what says so
        instead of the window quietly showing a dead one. Renumbering is the
        thing NOT to do - an id is an address, and a poke at an invented one
        closes a switch the user did not ask for.

        ★ THE REAL ID WAS FOUND the same day (swelf._gen2_entry_ids): the
        48-byte generation carries an entry table after all, and no card on
        this disk reaches this test any more. It stays as the backstop, because
        that table is FOUND rather than known - a build whose one cannot be
        identified still falls back to device positions, deliberately, and the
        next record shape will arrive the way this one did, on somebody's
        machine and without notice.
        """
        return 0 <= sw_id < padsw.MAX_ID

    def closed(self):
        """[bool] per trough position, in trough order."""
        return trough.closed(self.mrg, self.positions)

    def is_made(self, sw_id):
        """True/False for one switch, or None when nothing has been read."""
        if self.mrg is None or not 0 <= sw_id < len(self.mrg):
            return None
        return bool(self.mrg[sw_id])


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


#: How often the BALLS section re-reads the feeder's status file. Once a
#: second: it is another 9p round trip, and the feeder's lines arrive at the
#: pace a ball moves, not a flipper.
BALL_POLL_S = 1.0


def dots_caption(watch):
    """The key panel's caption beside its READ-ONLY dots (PAD-134): which end
    is which, and nothing about clicking - the buttons below do that now."""
    txt = "1 = eject end"
    return txt if watch.how == "named" else txt + "   (positions assumed)"


def ball_line(watch, fed=None):
    """The BALLS section's one line, in the JJP ball keeper's status() shape.

    `balls 5/6 trough   lane 1   in play 1   fed 3`. The denominator is the
    trough's POSITIONS, which is JJP's choice too, and not trough.Balls's
    learned complement: that one only knows the most balls it has SEEN home,
    so a window opened with a ball out read "0 in play" - the first thing
    David's screenshot of this section showed. A ball waiting in the shooter
    lane is counted on its own, because it is neither home nor in play and
    "Plunge" is the button that moves it. `fed` is None when no feeder is
    publishing, and then the line does not claim a zero.
    """
    if not watch.positions:
        return "no trough found on this title"
    if watch.mrg is None:
        return "balls -   waiting for the switch block"
    flags = watch.closed()
    home = sum(1 for f in flags if f)
    txt = "balls %d/%d trough" % (home, len(flags))
    if _lane_made(watch):
        txt += "   lane 1"
    txt += "   in play %d" % balls_in_play(watch)
    if fed is not None:
        txt += "   fed %d" % fed
    return txt


def _lane_made(watch):
    lane_id = getattr(watch, "lane_id", None)
    return lane_id is not None and bool(watch.is_made(lane_id))


def balls_in_play(watch):
    """How many balls are out on the playfield, by ballmodel.in_play's rule -
    the one plunge.py's drain refuses on, so the line and the button agree."""
    return ballmodel.in_play(ballmodel.Trough(watch.positions), watch.mrg,
                             getattr(watch, "lane_id", None), _lane_made(watch))


def drain_ready(watch):
    """Is Drain a real action right now? Only with a ball IN PLAY (PAD-153).

    DragonRR: "I drained before I plunged.. and that forces an endless cycle.
    Is it possible to grey out the drain until it is valid?" A ball waiting in
    the shooter lane is not in play, and a full trough has nothing out; both
    grey the button. Nothing read yet is not a yes either.
    """
    if not watch.positions or watch.mrg is None:
        return False
    return balls_in_play(watch) > 0


def new_lines(prev, cur):
    """The lines in `cur` that `prev` had not seen.

    The feeder's status file is a SLIDING WINDOW of its newest lines, so a
    re-read overlaps the last one: what is new is whatever follows the longest
    tail of `prev` that `cur` starts with. No overlap at all means the window
    slid past everything - all of it is new.
    """
    for k in range(min(len(prev), len(cur)), 0, -1):
        if list(prev[-k:]) == list(cur[:k]):
            return list(cur[k:])
    return list(cur)


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
                cmd = (wsl_head() + ["-e", "env"] + wsl_rig_env()
                       + ["python3", "%s/swkeys.py" % WSL_DIR])
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
        return self._send(b"%d %d\n" % (sw, val))

    def set_cab(self, name, val):
        """Hold or release one of the boot menu's buttons BY NAME (swkeys.py's
        `cab` line; padsw.h's cab[]). There is no spawn fallback: a name has
        no per-action helper, and the caller has nothing better to do with a
        press the pipe could not carry than drop it."""
        return self._send(b"cab %s %d\n" % (name.encode("ascii"), val))

    def _send(self, line):
        if not self._ensure():
            return False
        try:
            self._p.stdin.write(line)
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
        cmd = (wsl_head(root=True) + ["-e", "env"] + wsl_rig_env()
               + ["bash", "%s/slots.sh" % WSL_DIR, "list"])
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
    pts = layout_points()
    if not pts:
        return None
    return (max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)


def layout_points():
    """Every positioned device, in the layout's own pixels."""
    return [(r["x"], r["y"]) for kind in ("led", "switch", "coil")
            for r in layout_rows(kind)]


#: How much of a title's own layout a picture must contain before it is
#: accepted as that layout's artwork.
#:
#: ★ IT IS NOT "ALL OF IT", AND REQUIRING THAT COST A TITLE ITS PLAYFIELD.
#: uncanny_xmen_le 0.98.0 positions 185 devices on `playfield` and ships
#: `xmen_pre_playfield_scaled.png` at 321x710 to draw them on - the right
#: picture, found by the right route. ONE of those 185 sits at x=383, past the
#: right-hand edge, so the max-extent test made the layout 383 wide, the
#: picture failed by 62 pixels, and the window fell back to a blank field with
#: markers on it. David, 2026-09-07, looking at exactly that: "running xmen on
#: main right now has no artwork" - and the same window in a tester's
#: screenshot the same evening.
#:
#: The refutation this test exists for still works, because it is about
#: PROPORTION and the case it catches is nothing like one stray. The case is
#: uncanny_xmen_le 0.97.0's cabinet front (448x274) under playfield
#: coordinates that reach y=626: not one point over the edge but most of them,
#: which lands far below this floor. A single misplaced device is a wrong ROW,
#: and losing a whole playfield to one wrong row is the worse trade.
ART_FIT_MIN = 0.95


#: PAD_PF_VIEW=schematic forces the switch-list-and-swatch-grid view on ANY
#: title; PAD_PF_VIEW=field forces the positional one. Empty (the default)
#: lets layout_is_usable() decide, which is what every normal run does.
#:
#: WHY IT EXISTS, and it is not a debug knob for its own sake: the grid reads
#: the WIRE and needs no device table and no group -> node map, so it is the
#: only view that can show the light show on a title whose artwork cannot
#: address its lamps - james_bond_60th_le lights 0 of 73 markers while its ring
#: carries real data (item 53). It is also the only way to watch a title's raw
#: LED wire on a machine where the artwork view would otherwise hide it, which
#: is how item 50's own acceptance was finally measured: godzilla_pro drives 59
#: channels of a real attract light show, and forcing it into this view is what
#: let the grid be watched tracking a game rather than a synthetic feed.
PF_VIEW = (os.environ.get("PAD_PF_VIEW") or "").strip().lower()


#: The fewest usable devices (clickable switches + coils + lamps that can
#: light) a positioned layout must carry before it displaces the Schematic.
#: The real playfields here carry 59..217; uncanny_xmen_le's cabinet front,
#: the case this guards, carries 3.
MIN_USABLE_LAYOUT = 8


def layout_is_usable():
    """True when the positional view would actually SHOW something.

    ★ POSITIONS ALONE ARE NOT ENOUGH, and the first version of this gate got
    that wrong (item 50). It asked only "does the title position anything",
    which promoted elvira3 - 275 lamps positioned on a TOPPER image, every one
    in device-table group 3 which GROUP_NODE cannot address, no switches, no
    coils and no playfield.png at all - out of the switch list and into an
    artwork view with nothing live on it. Measured: 0 of 275 lamps can ever
    light, 0 switch markers are drawn, and the 109 individually clickable
    switch rows the Schematic gave it are lost. That is a worse window, and it
    was a regression this pass introduced.

    So the test is whether the layout yields anything a person can USE: a
    switch to click, a coil to watch, or a lamp that can actually light. A
    title that fails it keeps the switch list - and gets the swatch grid, which
    reads the wire directly and so works exactly where the table does not.
    """
    if PF_VIEW == "schematic":
        return False
    if PF_VIEW == "field":
        return bool(layout_extent())
    if not layout_extent():
        return False
    # ★ AND ENOUGH OF THEM TO BE A PLAYFIELD (uncanny_xmen_le 0.97.0, item 80,
    # 2026-09-06). That title positions exactly THREE devices, all lamps -
    # SHOOTER BEZEL 1/2/3 - on `System/TestMode/spike_2_cabinet_front_cropped`,
    # the cabinet-front picture, and nothing at all on a playfield. The image
    # vote hands over the only layout there is, group 5 resolves to node 1,
    # and "any lamp that can light" was satisfied by those three: the window
    # opened as a Field on a blank 448x274 extent - David: "the virtual
    # playfield is just a large empty black space" - while the Schematic it
    # displaced had 109 clickable switch rows and the swatch grid. A cabinet
    # front carries "a handful of each" (devicexy.layout_image); a playfield
    # carries dozens. So the count of things a person can USE has a floor.
    usable = (len(load_switches()) + len(load_coils())
              + sum(1 for L in load_leds() if L["node"] is not None))
    return usable >= MIN_USABLE_LAYOUT


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
    pts = layout_points()
    wh = gameinfo.png_size(PF_PNG)
    if not pts or not wh:
        return None
    inside = sum(1 for x, y in pts if 0 <= x <= wh[0] and 0 <= y <= wh[1])
    return PF_PNG if inside >= len(pts) * ART_FIT_MIN else None


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


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


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

#: The fill of an UNLIT cell. It matches the canvas exactly, so it is invisible
#: - it exists only so the rectangle has an interior for Tk to hit-test. See
#: LedGrid.tick().
LED_GRID_DARK = "#%02x%02x%02x" % LED_GRID_BG


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



# ===========================================================================
# THE WINDOW IS A WEB PAGE (2026-09-23).
#
# Everything above this line is the playfield's knowledge - the wire formats,
# the tables, the switch driver, the trough and ball rules, the fade envelope -
# and it is unchanged. Everything below used to be Tk widgets and is now
# MODELS: the same state and the same decisions, published to a page
# (pfweb/pf.js) that draws them in the app's own design. The rules that were
# about Tk itself (canvas items with no alpha, fill="" hit-testing, PhotoImage
# keep-alives, after() re-entrancy) went with it; every rule that was about
# the GAME stayed, word for word where it could.
# ===========================================================================

class Blobs:
    """Images the page fetches by key (/blob/<key>): the villain vision
    frames. Bounded, oldest out, so a long run cannot grow it without end."""

    CAP = 1200

    def __init__(self):
        self._d = collections.OrderedDict()
        self._n = 0
        self._lock = threading.Lock()

    def put(self, data, mime="image/png"):
        with self._lock:
            self._n += 1
            key = "b%d" % self._n
            self._d[key] = (data, mime)
            while len(self._d) > self.CAP:
                self._d.popitem(last=False)
            return key

    def get(self, key):
        # a read keeps an entry fresh, so a looping clip's frames stay
        with self._lock:
            got = self._d.get(key)
            if got is not None:
                self._d.move_to_end(key)
            return got


BLOBS = Blobs()


def _png(pil):
    """A PIL image as PNG bytes in BLOBS; its key. Level 1: these are
    re-encoded at 10 Hz and the compression ratio is not the point."""
    buf = io.BytesIO()
    pil.save(buf, "PNG", compress_level=1)
    return BLOBS.put(buf.getvalue())


def _png_file(path):
    """A PNG file's own bytes in BLOBS, or None when it is not a readable
    PNG - the stand-in for tk.PhotoImage(file=...) raising TclError."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if not data.startswith(b"\x89PNG"):
        return None
    if _PILImage is not None:
        try:
            _PILImage.open(io.BytesIO(data)).verify()
        except Exception:                                   # noqa: BLE001
            return None
    return BLOBS.put(data)


class TroughDots:
    """The trough's ball positions in trough order - ONE control, two homes.

    THE NUMBERS UNDER THE BALLS ARE THE POINT: position 1 is the eject end and
    is drawn first, so the row reads in the direction a ball travels (item 20
    was a wrong-end bug a count could never have shown).

    On the KEY PANEL the dots are read-only (PAD-134: Plunge / Drain / Reset
    balls are its buttons). Without a panel - the artwork corner, the
    schematic's strip - they are still the control, and THE STACK DECIDES
    WHICH SWITCH MOVES, NOT WHICH DOT WAS CLICKED: a trough is a ramp, so the
    only two things that can happen are one more ball or one fewer. Clicking a
    full dot takes a ball out; an empty one drains one in. The decision reads
    the state last SHOWN, so it is the one the user could see when they
    clicked.
    """

    def __init__(self, positions, how, clickable=False):
        self.positions, self.how, self.clickable = positions, how, clickable
        self.drawn = [None] * len(positions)
        self.text = None

    def click(self, i):
        occupied = bool(self.drawn[i]) if 0 <= i < len(self.drawn) else False
        return "take" if occupied else "drain"

    def update(self, flags, text):
        changed = False
        for i, on in enumerate(flags[:len(self.drawn)]):
            if self.drawn[i] != on:
                self.drawn[i] = on
                changed = True
        if text != self.text:
            self.text = text
            changed = True
        return changed

    def spec(self):
        return {"pos": [P["pos"] for P in self.positions],
                "clickable": self.clickable, "how": self.how}

    def dyn(self):
        return {"flags": [bool(x) for x in self.drawn], "text": self.text or ""}


class KeyPanel:
    """The keyboard -> switches reference, docked beside the playfield.

    ★ ITEM 39. The retired Controls window's content, moved into this window
    so a run opens two windows instead of three. The rows come from
    dump/padbinds, which padglhost exports after resolving binds[] for the
    title (keybinds.py parses it), so which key does what still has exactly
    one home and it is still the C file.

    THE HIGHLIGHT IS SWITCH STATE, NOT KEY STATE: a row lights off the MERGED
    array - what the GAME is being handed - so it lights when the game can see
    the press, whoever made it (a key, a click on the artwork, a script).

    ★ ONE CONTROL PER ACTION (David: "consolidate the keyboard inputs and the
    button inputs for the service buttons"): the four service binds, the door
    and the trough latch are WIDGETS wearing their key labels, not list rows.
    The service buttons are the real coin-door cluster (green BACK, red -/+,
    black SELECT) and are press-and-hold; the COIN DOOR is a click toggle,
    because the real door stays where you put it. Start Button and Left Coin
    are clickable rows (PAD-134: a mouse-only player needs them).

    THE BALLS SECTION (PAD-134, the JJP window's shape): one line, the
    read-only dots, Plunge / Drain / Reset balls, and a note of the newest
    three messages. Drain is live only with a ball IN PLAY (PAD-153).
    """

    SVC_ORDER = ("Service Back", "Service Minus", "Service Plus",
                 "Service Select")
    CLICK_ROWS = ("Start Button", "Left Coin")
    DOOR_LABEL = "Coin Door Closed"
    #: label, caption, glyph, fill, ring, caption colour - the real panel
    SVC_LOOK = (("Service Back", "BACK", "", "#1f9d4e", "#0d5c2a", "#dff5e6"),
                ("Service Minus", "< -", "-", "#d43535", "#7a1717", "#ffffff"),
                ("Service Plus", "+ >", "+", "#d43535", "#7a1717", "#ffffff"),
                ("Service Select", "SELECT", "", "#1c1c1c", "#777",
                 "#d8d8d8"))
    #: How many of the newest ball messages the section shows.
    NOTE_LINES = 3

    def __init__(self, rows, drv, on_action=None):
        self.drv = drv
        self.on_action = on_action
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
        self._drawn = [None] * len(self.rows)
        self._svc_ids = ([self._svc_rows[lbl]["ids"][0]
                          for lbl in self.SVC_ORDER]
                         if len(self._svc_rows) == 4 else [])
        self._svc_drawn = [None] * len(self._svc_ids)
        self._door_id = self._door_row["ids"][0] if self._door_row else None
        self._door_drawn = None
        self._last_sw = None
        self._svc_held = None
        self._row_held = None
        self.ball_dots = None
        self._ball_drawn = None
        self._drain_live = None
        self._note = []
        self._feed_seen = []
        self.clear_action = (next(a for a in WINDOW_ACTIONS
                                  if a[1] == "swexercise.py")
                             if on_action is not None else None)
        self.dirty = True

    # ---- what the page draws ------------------------------------------------
    def spec(self):
        rows = []
        for r in self.rows:
            click = (r["label"] in self.CLICK_ROWS and not r["na"]
                     and bool(r["ids"]))
            rows.append({"keys": "/".join(r["keys"]), "label": r["label"],
                         "cabinet": bool(r["cabinet"]), "na": bool(r["na"]),
                         "click": r["ids"][0] if click else None})
        svc = []
        if self._svc_ids:
            for lbl, sub, glyph, fill, ring, subfg in self.SVC_LOOK:
                row = self._svc_rows[lbl]
                svc.append({"label": lbl, "sub": sub, "glyph": glyph,
                            "fill": fill, "ring": ring, "subfg": subfg,
                            "keys": "/".join(row["keys"]),
                            "id": row["ids"][0]})
        return {"rows": rows, "svc": svc,
                "clear": self.clear_action[0] if self.clear_action else None,
                "door": ("/".join(self._door_row["keys"])
                         if self._door_row else None),
                "trough_keys": ("/".join(self._trough_row["keys"])
                                + " = all six in / out"
                                if self._trough_row else None),
                "balls": self.ball_dots.spec() if self.ball_dots else None}

    def dyn(self):
        return {"rows": self._drawn, "svc": self._svc_drawn,
                "door": self._door_drawn, "ball": self._ball_drawn or "",
                "drain": bool(self._drain_live), "note": list(self._note),
                "dots": self.ball_dots.dyn() if self.ball_dots else None}

    # ---- the service buttons: press-and-hold through the same driver --------
    def svc_press(self, sw_id):
        if self._svc_held is not None or sw_id not in self._svc_ids:
            return
        self._svc_held = sw_id
        self.drv.press(sw_id)

    def svc_release(self):
        """Open whatever the press closed - by what we HELD, whatever is under
        the pointer by the time the button comes up."""
        if self._svc_held is None:
            return
        sw_id, self._svc_held = self._svc_held, None
        self.drv.release(sw_id)

    # ---- Start Button / Left Coin rows: press-and-hold (PAD-134) ------------
    def row_press(self, sw_id):
        ok = any(r["label"] in self.CLICK_ROWS and not r["na"] and r["ids"]
                 and r["ids"][0] == sw_id for r in self.rows)
        if self._row_held is not None or not ok:
            return
        self._row_held = sw_id
        self.drv.press(sw_id)

    def row_release(self):
        if self._row_held is None:
            return
        sw_id, self._row_held = self._row_held, None
        self.drv.release(sw_id)

    def release_held(self):
        self.svc_release()
        self.row_release()

    def door_click(self):
        """Toggle off the last SHOWN state, the trough dots' rule."""
        if self._door_id is None or self._last_sw is None:
            return
        if self._last_sw.is_made(self._door_id):
            self.drv.release(self._door_id)
        else:
            self.drv.press(self._door_id)

    # ---- the BALLS section --------------------------------------------------
    def set_drain(self, live):
        if live != self._drain_live:
            self._drain_live = live
            self.dirty = True

    def add_trough(self, positions, how):
        """The BALLS section's read-only dots; returns them, and the view
        keeps pointing its `trough` at them so the switch poll has ONE update
        path wherever the trough is drawn."""
        self.ball_dots = TroughDots(positions, how, clickable=False)
        self._drain_live = None
        self.set_drain(False)
        self.dirty = True
        return self.ball_dots

    def show_balls(self, sw, fed, feeder_lines):
        """The line off the switch read, Drain's state, and any NEW feeder
        lines folded into the note (the feeder's file is a sliding window, so
        what is new follows the longest overlap - new_lines())."""
        if self.ball_dots is None:
            return
        text = ball_line(sw, fed)
        if text != self._ball_drawn:
            self._ball_drawn = text
            self.dirty = True
        self.set_drain(drain_ready(sw))
        fresh = new_lines(self._feed_seen, feeder_lines)
        self._feed_seen = list(feeder_lines)
        if fresh:
            self.ball_say(*fresh)

    def ball_say(self, *lines):
        """Messages for the note, newest last. The page fits them into
        NOTE_LINES rows by the rule the Tk panel kept: WHOLE MESSAGES ARE
        DROPPED, OLDEST FIRST - never the head of one; a message that alone
        needs more rows keeps its FIRST rows, the last marked cut, because the
        start of a sentence is the part that says what happened."""
        if self.ball_dots is None:
            return
        self._note.extend(lines)
        del self._note[:-self.NOTE_LINES]
        self.dirty = True

    def update(self, sw):
        """Recompute the rows whose switch state moved (change-gated)."""
        self._last_sw = sw
        for k, sid in enumerate(self._svc_ids):
            made = bool(sw.is_made(sid))
            if self._svc_drawn[k] != made:
                self._svc_drawn[k] = made
                self.dirty = True
        if self._door_id is not None:
            closed = bool(sw.is_made(self._door_id))
            if self._door_drawn != closed:
                self._door_drawn = closed
                self.dirty = True
        for i, r in enumerate(self.rows):
            if r["na"]:
                continue
            made = [bool(sw.is_made(sid)) for sid in r["ids"]]
            n = sum(made)
            if len(r["ids"]) > 1:
                state = [n == len(made), "%d/%d" % (n, len(made)), n > 0]
            elif r["toggle"]:
                state = [n > 0, "[ON]" if n else "[off]", n > 0]
            else:
                state = [n > 0, "", n > 0]
            if self._drawn[i] != state:
                self._drawn[i] = state
                self.dirty = True


#: The page's key names -> the Tk keysym names the rows and the boot menu's
#: buttons are keyed by (keybinds.tk_keysyms / cabinet_keysyms). The page
#: sends KeyboardEvent.code; letters and digits map to themselves.
CODE_KEYSYM = {"Enter": "Return", "NumpadEnter": "KP_Enter",
               "Backspace": "BackSpace", "Escape": "Escape",
               "Space": "space", "Equal": "equal", "Minus": "minus",
               "ArrowLeft": "Left", "ArrowRight": "Right",
               "ArrowUp": "Up", "ArrowDown": "Down"}


def code_to_keysym(code, key=""):
    """KeyboardEvent.code (+ .key) -> a Tk keysym name, or None."""
    if not code:
        return None
    if code in CODE_KEYSYM:
        return CODE_KEYSYM[code]
    if code.startswith("Key") and len(code) == 4:
        return code[3].lower()
    if code.startswith("Digit") and len(code) == 6:
        return code[5]
    return None


class KeyInput:
    """Keyboard play with THIS window focused (item 39, David: "it should work
    with the virtual playfield focused"). The bindings come from the SAME
    exported rows the panel draws, and the edges ride SwitchPipe, with the
    per-action spawn as the fallback.

    The page drops auto-repeat itself (KeyboardEvent.repeat) and keys typed
    into a text box (the save-slot name), which is what the Tk version's
    release-then-press swallow and widget-class test were for. It also sends a
    blur when the window loses focus, and that releases every key still down:
    a flipper held while alt-tabbing away must not stay up for good.
    """

    def __init__(self, ctl, rows):
        self.ctl = ctl
        self.pipe = SwitchPipe()
        self.map = {}
        for r in rows:
            if r["na"] or not r["ids"]:
                continue
            for k in r["keys"]:
                for sym in keybinds.tk_keysyms(k):
                    self.map[sym] = r
        # ★ THE BOOT MENU'S BUTTONS RIDE ALONG BY NAME, whatever rows there
        # are (David, 2026-09-19: "the first time loading a multi image won't
        # let me use arrow keys (or select) since the virtual playfield isn't
        # initialized yet"). A key that already has a row keeps it (a COPY
        # carries the button); one that has none gets a row that presses no
        # switch, only the button.
        for sym, button in keybinds.cabinet_keysyms().items():
            row = dict(self.map.get(sym) or dict(
                keys=[sym], label=button, ids=[], na=False, toggle=False,
                cabinet=True))
            row["cab"] = button
            self.map[sym] = row
        self.down = set()
        # Pre-warm the helper so the FIRST press does not pay the spawn.
        self.pipe._ensure()

    def key(self, sym, down):
        r = self.map.get(sym)
        if r is None:
            return False
        if down:
            if sym in self.down:
                return True
            self.down.add(sym)
            if r["toggle"]:
                # The toggle flips off the MERGED state - the state acted on
                # is the one on screen, the door button's rule.
                sw = getattr(self.ctl.view, "sw", None)
                target = 0 if sw is not None and all(
                    bool(sw.is_made(s)) for s in r["ids"]) else 1
                for s in r["ids"]:
                    self._set(s, target)
            else:
                if r["ids"]:
                    self._set(r["ids"][0], 1)
                if r.get("cab"):
                    self.pipe.set_cab(r["cab"], 1)
            return True
        if r["toggle"]:
            self.down.discard(sym)
            return True
        if sym not in self.down:
            return True
        self.down.discard(sym)
        if r["ids"]:
            self._set(r["ids"][0], 0)
        if r.get("cab"):
            self.pipe.set_cab(r["cab"], 0)
        return True

    def release_all(self):
        for sym in list(self.down):
            self.key(sym, False)
        self.down.clear()

    def _set(self, sw, val):
        if not self.pipe.set(sw, val):
            (self.ctl.drv.press if val else self.ctl.drv.release)(sw)

    def close(self):
        self.pipe.close()

    def detach(self):
        """Stop acting on keys and let the helper release what it holds (EOF)
        - for a KeyInput being REPLACED, as the "WAITING" one is."""
        self.down.clear()
        self.close()


#: Save/Load state: ten named slots (item 13 / item 39). A label crosses
#: wsl.exe's re-parse into bash argv, and wsl.exe expands $ and backticks
#: even in -e argv, so a label may never contain them.
SLOT_IDS = ["slot%d" % i for i in range(1, 11)]
LABEL_OK = ("abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.()!-")


def clean_label(text):
    return "".join(ch for ch in (text or "") if ch in LABEL_OK).strip()[:40]


def state_reply(script, r):
    """The one-line answer to a save or load: the wrappers' last tagged line
    that SAYS something - a bare "[savegame] FAILED" is the worst answer, and
    David's first real press showed exactly that with the criu reason one
    line above it."""
    if r is None:
        return "%s did not run" % script
    lines = [ln.strip() for ln in
             (r.stdout or b"").decode("utf8", "replace").splitlines()
             + (r.stderr or b"").decode("utf8", "replace").splitlines()
             if ln.strip()]
    tagged = [ln for ln in lines
              if ln.startswith(("[savegame]", "[loadgame]", "[save]",
                                "[restore]", "savegame:", "loadgame:"))]
    saying = [ln for ln in tagged if not ln.rstrip().endswith("FAILED")]
    return (saying or tagged or lines or ["%s: no output" % script])[-1]


class LedGrid(LedRing):
    """Every LED the wire has shown, as a field of colour, grouped by node.

    ★ THE ROSTER COMES FROM THE RING, NOT FROM A TABLE (item 50): four titles
    carry `0 records` in device_xy.txt, and a grid built from the block shows
    what the game is actually doing; the table is only ever a LOOKUP for the
    name. It needs no group -> node map either, so it works on the titles
    whose artwork cannot address its lamps.

    A CHANNEL EARNS ITS CELL BY BEING WRITTEN (or addressed, version 4's
    `seen` plane, or pulsed through the fade ring), AND KEEPS IT: a grid that
    reflows while you watch is unreadable, so a dark cell means "this lamp
    exists and is off". ONE CELL PER FIXTURE WHERE THE NAMES ALLOW IT, and
    nothing is inferred from consecutive indices.
    """

    def __init__(self, names):
        self.names = names or {}
        self.cells = []
        self.by_node = {}
        self.seen = set()
        self.gen = 0                    # bumps when the roster is rebuilt
        self._decoded = None
        self._init_ring()

    def _discover(self, d):
        """Add every channel the block shows (val or seen) and we have not.
        Per node, with a C-level all-zero test first. True when it grew."""
        grew = False
        for node in range(coilmap.NODES):
            for base in (LED_HDR + node * LED_IDX, SEEN_OFF + node * LED_IDX):
                s = d[base:base + LED_IDX]
                if len(s) < LED_IDX or s.count(0) == LED_IDX:
                    continue
                for idx, v in enumerate(s):
                    if v and (node, idx) not in self.seen:
                        self.seen.add((node, idx))
                        grew = True
        return grew

    def _rebuild(self):
        """Group the roster into fixtures. Cells are REUSED across rebuilds,
        keyed by (node, name), so a lit lamp keeps its state when an unrelated
        board is discovered; the page lays the blocks out."""
        by_node = {}
        for node, idx in sorted(self.seen):
            by_node.setdefault(node, []).append(idx)
        old = {(C["node"], C["name"]): C for C in self.cells}
        cells, self.by_node = [], {}
        for node in sorted(by_node):
            stems, order = {}, []
            for idx in by_node[node]:
                name = self.names.get((node, idx))
                if name:
                    stem, chan = split_channel(name)
                else:
                    stem, chan = "%d.%d" % (node, idx), "W"
                # A stem that repeats a channel letter is two lamps sharing a
                # name, not one lamp with two reds.
                C = stems.get(stem)
                if C is not None and chan in C["channels"]:
                    stem = "%s (%d.%d)" % (stem, node, idx)
                    C = stems.get(stem)
                if C is None:
                    C = old.get((node, stem))
                    if C is None:
                        C = dict(name=stem, node=node, state=(), drawn=None,
                                 named=bool(name))
                    C["channels"], C["idxs"] = {}, []
                    stems[stem] = C
                    order.append(C)
                C["channels"][chan] = (node, idx)
                C["idxs"].append(idx)
            for C in order:
                C["sort"] = min(C["idxs"])
                C["key"] = "%d:%s" % (node, C["name"])
            order.sort(key=lambda C: C["sort"])
            self.by_node[node] = order
            cells.extend(order)
        self.cells = cells
        self.gen += 1

    def tick(self, d, now):
        """Recompute the cells whose value moved. Returns (lit, total,
        changes, grew): changes maps a cell key to [r, g, b, alpha] or 0."""
        changes = {}
        if not d or len(d) < LED_HDR:
            return 0, len(self.cells), changes, False
        self._take_fades(d, now)
        # The fade ring is a second source of channels (an a2 pulse writes
        # only the ring, never val[]).
        grew = False
        for key in self.overlay:
            if key not in self.seen:
                self.seen.add(key)
                grew = True
        # Discovery gated on BOTH write counters (a swelf frame can grow
        # `seen` without moving `decoded`).
        dec = struct.unpack_from("<I", d, LED_DECODED_OFF)[0]
        if len(d) >= PADLED_READ:
            dec += struct.unpack_from("<I", d, WIDE_DECODED_OFF)[0]
        if dec != self._decoded:
            self._decoded = dec
            grew = self._discover(d) or grew
        if grew:
            self._rebuild()
        lit = 0
        for C in self.cells:
            rgb, level = fixture_color(self._chan_vals(C, d, now))
            if rgb:
                lit += 1
            st = (rgb, level)
            if st == C["state"] and C["drawn"] is not None:
                continue
            C["state"] = st
            if rgb:
                _rs, alpha = level_shape(level)
                want = [rgb[0], rgb[1], rgb[2], round(alpha, 3)]
            else:
                want = 0
            if want != C["drawn"]:
                C["drawn"] = want
                changes[C["key"]] = want
        return lit, len(self.cells), changes, grew

    def spec(self):
        return {"gen": self.gen, "blocks": [
            {"node": node,
             "cells": [{"k": C["key"], "tip": self.describe(C)}
                       for C in self.by_node[node]]}
            for node in sorted(self.by_node)]}

    def dyn(self):
        return {C["key"]: C["drawn"] or 0 for C in self.cells}

    def describe(self, C):
        where = ", ".join("%s=node %d index %d" % (c, n, i)
                          for c, (n, i) in sorted(C["channels"].items()))
        return ("LED  %s\n%s\n%s"
                % (C["name"], where,
                   "named by the title's device table" if C["named"]
                   else "no name in this title's table - shown by wire address"))



class LcdPanel:
    """VILLAIN VISION - the lcdnode's LCD insert, in its OWN window.

    batman's node 24 drives the fixture the ELF calls "3 LCD INSERT" (item
    83). Nothing crosses the bus but ASSET NUMBERS naming stored clips;
    padlcd.h carries the frame table and the disassembly addresses.

    ★ ONE SCREEN, NOT THREE: the game addresses ONE logical display (fixture
    display count 1; all 299 LCD call sites pass the same device) driving ONE
    physical TV - David's video of the real machine shows a single set with
    "Villain Vision" on its bezel. And `asset` is always what to draw; the
    companion number is shown as "aux N" because that is all anybody has
    earned the right to call it.

    The art is extracted LAZILY by lcdart.py into <tables>/<game>/lcd/<id>
    .{png,webp} the first time an asset is seen, cheap-first: the still paints
    the moment it lands, the motion takes over when the encode finishes. Until
    either lands the screen says "asset <id>", which is honest.

    THE CAPTION IS AN INSTRUMENT: it names the asset, the verb the game sent
    (printed as a number past the two that are known), and any companion
    fields - printing the raw numbers is what lets the next wrong reading be
    caught from a photograph.

    A SEPARATE WINDOW (David, 2026-08-24): every other second-display title
    gets its screen as its own desktop window, and this IS batman's second
    display. Closing it HIDES it for the run (item 44's contract). Its
    position persists as "villain_pos" beside the playfield's.

    LAZY BY CONSTRUCTION: no window exists until the padlcd block's magic
    stamps, which only an lcdnode title's shim ever does.

    THE BOARD IS AN ID -> STILL LOOKUP when <art>/stills/map.txt exists
    (2026-08-26, matched frame-level against David's videos): the Villain
    Vision holds ONE STILL per command, fading between them, and never plays
    video. THE DISSOLVE: going dark fades out in FADE_STEPS; the set itself
    never dims, only the screen.

    WHAT CHANGED WITH THE WEB WINDOW, and nothing else did: a picture is a
    PNG in BLOBS instead of a PhotoImage, and the hand-drawn cabinet is drawn
    by the page (no card art); the decisions - which asset, which frame,
    loop / once / block cycle, the dissolve, the filmstrip - are the same
    code.
    """

    READ = 56                       # header .. ms; the ring beyond is RE fuel
    MAGIC = 0x44434c50              # 'PLCD'
    CW, CH = 244, 184               # the screen (clips are 240x180)
    PAD_L, PAD_T = 16, 14           # the drawn case around the screen
    PAD_R, PAD_B = 62, 34
    STRIP_N = 4                     # the filmstrip: last clips, oldest left
    TW, TH = 60, 45
    ASK_S = 60.0                    # lcdart re-ask backoff per id
    FADE_STEPS = (0.62, 0.28)       # fraction of the picture per step

    def __init__(self, game, on_build=None):
        self.game = game
        self.on_build = on_build    # called once, when the window is due
        self.drv = None             # assigned once the SwitchDriver exists
        self.built = False
        self.item = None            # truthy while a picture item exists
        self.item_img = None        # what that item shows (a BLOBS key)
        self.item_state = "normal"  # ... and whether it is shown
        self.placeholder = None     # the "asset N" text, when no picture
        self.img = None             # the current real picture (not a fade)
        self.id = None
        self.have = False
        self.state = None           # (asset, aux, rate, verb)
        self.cycle = None
        self.bright = 255
        self.stillmap = None
        self._map_tried = False
        self._still_imgs = {}
        self._pic_pil = None
        self._fadeq = []
        self.names = None
        self._named = False
        self.tv = None              # the card's own TV sprite (PIL RGBA)
        self.tv_hole = None
        self._tv_tried = False
        self._recent = []           # [(id, BLOBS key)] oldest first
        self.anim = None
        self._asked = {}
        self._hidden = False
        self._next = 0.0
        self._polls = 0
        self.cap_text = ""
        self.nm_text = ""
        self.dirty = False
        self._art = os.path.join(padpath.tables() or "", game, "lcd")

    # ---- what the page draws ------------------------------------------------
    def spec(self):
        if self.tv is not None:
            size = list(self.tv.size)
        else:
            size = [self.CW + self.PAD_L + self.PAD_R,
                    self.CH + self.PAD_T + self.PAD_B]
        return {"built": self.built, "tv": self.tv is not None,
                "size": size, "screen": list(self._screen_rect()),
                "cw": self.CW, "ch": self.CH,
                "pad": [self.PAD_L, self.PAD_T, self.PAD_R, self.PAD_B],
                "tw": self.TW, "th": self.TH, "strip_n": self.STRIP_N,
                "title": "%s [villain vision] - Stern Spike 2 emulator"
                         % self.game}

    def dyn(self):
        return {"pic": self.item_img if self.item else None,
                "shown": bool(self.item) and self.item_state == "normal",
                "placeholder": self.placeholder,
                "cap": self.cap_text, "nm": self.nm_text,
                "strip": [[i, k] for i, k in self._recent],
                "current": self._recent[-1][0] if self._recent else None}

    def _screen_rect(self):
        if self.tv_hole:
            return self.tv_hole
        return (self.PAD_L, self.PAD_T, self.CW, self.CH)

    def _build(self):
        self.built = True
        self._load_tv()
        self.dirty = True
        if self.on_build is not None:
            try:
                self.on_build()
            except Exception:                               # noqa: BLE001
                pass

    def _load_tv(self):
        """The card's own TV sprite + screen rect, once. Absent is normal
        and leaves the page's drawn cabinet in place."""
        if self._tv_tried:
            return
        self._tv_tried = True
        if _PILImage is None:
            return
        png = os.path.join(self._art, "tvframe.png")
        txt = os.path.join(self._art, "tvframe.txt")
        try:
            with open(txt, encoding="utf8") as f:
                x, y, w, h = (int(v) for v in f.read().split()[:4])
            tv = _PILImage.open(png).convert("RGBA")
        except (OSError, ValueError):
            return
        if w <= 0 or h <= 0 or x + w > tv.width or y + h > tv.height:
            return
        self.tv, self.tv_hole = tv, (x, y, w, h)

    def _compose(self, pil, stash=True):
        """A clip frame behind the TV's screen hole, KEEPING ITS ASPECT, the
        whole set as one image. `stash=False` is for the dissolve's own
        darkened frames, which must not overwrite the record of the picture."""
        x, y, w, h = self.tv_hole
        s = min(w / pil.width, h / pil.height)
        nw, nh = max(1, int(pil.width * s)), max(1, int(pil.height * s))
        out = _PILImage.new("RGBA", self.tv.size, (0, 0, 0, 255))
        out.paste(pil.convert("RGB").resize((nw, nh)),
                  (x + (w - nw) // 2, y + (h - nh) // 2))
        out.alpha_composite(self.tv)
        if stash:
            self._pic_pil = pil.convert("RGB")
        return _png(out.convert("RGB"))

    def _fade(self, br):
        """Start (or cut short) the brightness transition. Dark builds the
        dissolve queue - FADE_STEPS darkened frames, then dark - applied one
        per poll starting NOW; bright clears it and restores instantly.
        ★ THE SET NEVER DIMS: only the screen goes dark."""
        self._fadeq = []
        if self.item is None:
            return
        if br >= 128:
            self.item_img, self.item_state = self.img, "normal"
            self.dirty = True
            return
        if _PILImage is None or self._pic_pil is None:
            if self.tv is None:
                self.item_state = "hidden"
                self.dirty = True
            return
        black = _PILImage.new("RGB", self._pic_pil.size, (0, 0, 0))
        steps = [_PILImage.blend(black, self._pic_pil, a)
                 for a in self.FADE_STEPS]
        if self.tv is not None:
            self._fadeq = [self._compose(s, stash=False) for s in steps]
            self._fadeq.append(self._compose(black, stash=False))
        else:
            self._fadeq = [_png(s) for s in steps] + [None]
        self._fade_step()

    def _fade_step(self):
        step = self._fadeq.pop(0)
        if step is None:
            self.item_state = "hidden"
        else:
            self.item_img, self.item_state = step, "normal"
        self.dirty = True

    def hide(self):
        """The close box: hide, don't die (item 44). The ids keep tracking;
        the decode/draw work stops while nobody can see it."""
        self._hidden = True

    def show_again(self):
        self._hidden = False

    def poll(self):
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + 0.1      # 10 Hz: one 56-byte reopen-read
        self._polls += 1
        try:
            with open(LCD_PATH, "rb") as f:
                d = f.read(self.READ)
        except OSError:
            return
        if len(d) < self.READ or struct.unpack_from("<I", d)[0] != self.MAGIC:
            return
        if not self.built:
            self._build()
        (_m, _v, _g, _dec, asset, aux, rate, verb, _x1, _x2, _x3,
         br, _fd, _ms) = struct.unpack_from("<14I", d)
        # BRIGHTNESS IS PART OF THE PICTURE: the game drops the TV to 0 for
        # ~250 ms around every clip swap and restores 255.
        if br != self.bright:
            self.bright = br
            self._fade(br)
        elif self._fadeq:
            self._fade_step()
        cmd = (asset, aux, rate, verb)
        changed = cmd != self.state
        self.state = cmd
        # ONE display, ONE asset field. On a STILLS board the id selects a
        # stored still; a block command selects by its FIRST id. Without a
        # map, a companion naming a LARGER id is the inclusive clip block
        # asset..aux, cycled clip by clip.
        self.cycle = ((asset, aux) if asset and aux > asset
                      and not self._map() else None)
        if changed or not self.cycle:
            want = asset
        else:
            # mid-block the drawn id has advanced ON PURPOSE
            want = (self.id if self.id and asset <= self.id <= aux
                    else asset)
        if want != self.id:
            self._show(want)
        elif self._polls % 10 == 0 and want and (
                not self.have or self.anim is None):
            self._show(want)    # ~1 Hz retry while either artifact is missing
        self._caption()
        self._animate()         # one frame per poll = 10 fps

    def _caption(self):
        asset, aux, rate, verb = self.state
        how = {1: "loop", 2: "once"}.get(verb, "verb %d" % verb if verb else "")
        if self.cycle:
            what = "assets %d-%d" % self.cycle
            if self.id and self.cycle[0] <= self.id <= self.cycle[1]:
                what += " · showing %d" % self.id
        elif asset:
            what = "asset %d" % asset
        else:
            what = "idle"
        extra = []
        if aux and not self.cycle:
            extra.append("aux %d" % aux)
        if rate:
            extra.append("%d fps" % rate)
        txt = " · ".join(x for x in [what, how] + extra if x)
        if self.cap_text != txt:
            self.cap_text = txt
            self.dirty = True
        nm = ""
        if self.id:
            hit = self._map().get(self.id)
            nm = hit[1] if hit else self._name_for(self.id)
        if self.nm_text != nm:
            self.nm_text = nm
            self.dirty = True

    def _name_for(self, i):
        """The clip's episode+timecode ("S1E001 00:18:32"), or "". Loaded
        once from <art>/names.txt (lcdnames.py); absent is normal."""
        if not self._named:
            self._named = True
            path = os.path.join(self._art, "names.txt")
            try:
                with open(path, encoding="utf8") as f:
                    self.names = dict(
                        (int(a), b) for a, _, b in
                        (ln.rstrip("\n").partition("\t") for ln in f)
                        if a.isdigit() and b)
            except (OSError, ValueError):
                self.names = None
        if not self.names:
            return ""
        raw = self.names.get(i, "")
        tail = raw.rsplit(".", 1)[-1]
        m = re.match(r"^(S\d+E\d+)_(\d\d)-(\d\d)-(\d\d)-\d\d$", tail)
        if m:
            return "%s %s:%s:%s" % m.groups()
        return tail[:34]

    def _draw(self, img):
        """One persistent picture item; a new one starts hidden while the
        screen is dark (with no TV sprite - a composed image CONTAINS the set
        and must never blink out with the screen)."""
        self.img = img
        if self.item is None:
            self.placeholder = None
            self.item = True
            self.item_state = ("hidden" if (self.bright < 128
                                            and self.tv is None)
                               else "normal")
        self.item_img = img
        self.dirty = True

    def _push_recent(self, i, thumb):
        """Remember a clip in the filmstrip, only when the DRAWN id changes
        and real art exists (a re-send of the same asset never duplicates)."""
        self._recent.append((i, thumb))
        del self._recent[:-self.STRIP_N]
        self.dirty = True

    def _show(self, i):
        # A stills board first: the mapped still IS the display for this id.
        if i and i in self._map() and self._show_still(i):
            return
        # Ask lcdart.py for whatever this id is missing, at most once per
        # ASK_S per id, checked against BOTH artifacts.
        if (i and self.drv is not None
                and time.monotonic() - self._asked.get(i, -1e9) > self.ASK_S
                and not (
                    os.path.isfile(os.path.join(self._art, "%d.png" % i))
                    and os.path.isfile(os.path.join(self._art, "%d.webp" % i)))):
            self._asked[i] = time.monotonic()
            self.drv.run_script("lcdart.py", self.game, str(i))
        if self.id != i:
            self.anim = None
        png = os.path.join(self._art, "%d.png" % i)
        if i and os.path.isfile(png):
            img = thumb_src = None
            try:
                # The THUMBNAIL always comes from the bare still; the SCREEN
                # gets the composed set when the card art is there.
                thumb_src = _png_file(png)
                if thumb_src is not None:
                    img = (self._compose(_PILImage.open(png))
                           if self.tv is not None else thumb_src)
            except (OSError, ValueError):
                img = None
            if img is not None:
                if self.id != i and thumb_src is not None:
                    self._push_recent(i, thumb_src)
                self._draw(img)
                self.id, self.have = i, True
                return
        if self.id != i:                    # placeholder, once per change
            self.item = None
            self.item_img = None
            self.placeholder = ("asset %d" % i) if i else "—"
            self.dirty = True
        self.id, self.have = i, not i

    def _open_clip(self, i):
        """Read the id's WHOLE clip into memory and open a decoder over it.
        An OSError is the wire (None: retried next tick); a decode failure
        past this point is the file itself ({"dead": True})."""
        if _PILImage is None:
            return {"dead": True}
        try:
            with open(os.path.join(self._art, "%d.webp" % i), "rb") as f:
                data = f.read()
        except OSError:
            return None
        try:
            im = _PILImage.open(io.BytesIO(data))
            return {"pil": im, "n": getattr(im, "n_frames", 1),
                    "i": 0, "frames": []}
        except Exception:                                   # noqa: BLE001
            return {"dead": True}

    def _decode(self, a, idx):
        """Frame idx as a picture key, or None if the clip ends early."""
        try:
            a["pil"].seek(idx)
            if self.tv is not None:
                return self._compose(a["pil"])
            rgb = a["pil"].convert("RGB")
            self._pic_pil = rgb
            return _png(rgb)
        except Exception:                                   # noqa: BLE001
            a["n"] = idx
            return None

    def _cycle_next(self):
        """The clip after this one in a block command, or None for a single
        clip. Verb 1 wraps to the block's first clip, verb 2 holds on the
        last (returned as self.id, which _animate reads as 'stay')."""
        if not self.cycle:
            return None
        first, last = self.cycle
        verb = self.state[3] if self.state else 0
        if self.id is None or self.id >= last or self.id < first:
            return self.id if verb == 2 else first
        return self.id + 1

    def _map(self):
        """{id: (path, label)} from <art>/stills/map.txt, loaded once.
        Non-empty means this display is a STILLS BOARD."""
        if not self._map_tried:
            self._map_tried = True
            self.stillmap = {}
            path = os.path.join(self._art, "stills", "map.txt")
            try:
                with open(path, encoding="utf8") as f:
                    for ln in f:
                        if ln.startswith("#") or not ln.strip():
                            continue
                        parts = ln.rstrip("\n").split("\t")
                        if len(parts) >= 3 and parts[0].isdigit():
                            self.stillmap[int(parts[0])] = (parts[1], parts[2])
            except OSError:
                pass
        return self.stillmap

    def _show_still(self, i):
        """Draw the board still the map holds for id i, composed once and
        cached. False when the mapped file is unreadable, so the caller falls
        back to the clip art."""
        img = self._still_imgs.get(i)
        if img is None:
            path = os.path.join(self._art, "stills", self._map()[i][0])
            if _PILImage is not None:
                try:
                    pil = _PILImage.open(path)
                    pil.load()
                except OSError:
                    return False
                if self.tv is not None:
                    img = self._compose(pil)
                else:
                    s = min(self.CW / pil.width, self.CH / pil.height)
                    nw = max(1, int(pil.width * s))
                    nh = max(1, int(pil.height * s))
                    out = _PILImage.new("RGB", (self.CW, self.CH), (0,) * 3)
                    out.paste(pil.convert("RGB").resize((nw, nh)),
                              ((self.CW - nw) // 2, (self.CH - nh) // 2))
                    self._pic_pil = out
                    img = _png(out)
                thumb = _png(pil.convert("RGB").resize((self.TW, self.TH)))
            else:
                img = _png_file(path)
                if img is None:
                    return False
                thumb = None
            self._still_imgs[i] = img
            self._still_imgs[(i, "t")] = thumb
        if self.id != i:
            thumb = self._still_imgs.get((i, "t"))
            if thumb is not None:
                self._push_recent(i, thumb)
        self._draw(img)
        self.id, self.have = i, True
        self.anim = None                # a stills board never animates
        return True

    def _animate(self):
        """Advance the screen one frame (lcdart encodes at 10 fps and this
        runs once per 10 Hz poll). Skipped while hidden, mid-dissolve, and on
        a stills board."""
        if self._hidden:
            return
        if self._fadeq:
            return
        if self._map():
            return
        i, a = self.id, self.anim
        if not i:
            return
        if a is None:
            a = self.anim = self._open_clip(i)
            if a is None:
                return
        if a.get("dead"):
            return
        idx = a["i"]
        if idx >= a["n"]:
            nxt = self._cycle_next()
            if nxt is not None:
                if nxt != self.id:
                    self._show(nxt)
                    return
                return                  # verb 2 at the block's end: hold
            if self.state and self.state[3] == 2:
                return                  # single clip, once: hold
            idx = a["i"] = 0            # verb 1 (or unknown): it loops
        if idx < len(a["frames"]):
            frame = a["frames"][idx]
        else:
            frame = self._decode(a, idx)
            if frame is None:
                if not a["frames"]:
                    self.anim = {"dead": True}
                    return
                idx = a["i"] = 0
                frame = a["frames"][0]
            else:
                a["frames"].append(frame)
                if len(a["frames"]) >= a["n"]:
                    a.pop("pil", None)
        self._draw(frame)
        a["i"] = idx + 1



def _rate(dq, t):
    """Events per second over the last RATE_WIN_S. Divided by the WINDOW, not
    by the span of the events in it: dividing by the span reports 30 Hz for
    two redraws 33 ms apart inside an otherwise dead three seconds."""
    while dq and t - dq[0] > RATE_WIN_S:
        dq.popleft()
    if not dq:
        return 0.0
    return len(dq) / RATE_WIN_S


def _mark(dq, t):
    dq.append(t)
    return _rate(dq, t)


class Field(LedRing):
    """The positional view: the title's layout (on its artwork when the art
    fits the coordinates, on a blank field otherwise), with every insert lit
    from the wire, every coil flashing on its fire counter, and every
    positioned switch clickable.

    Markers keep the Tk window's semantics and colours: blue rings are
    switches (hold one to close it, right-hold to RIP it), red squares are
    coils (flash magenta when fired; a click holds the switch the coil
    follows, or runs coilact.py where the coil MOVES a ball), dots are inserts
    at a size and opacity that follow their duty cycle. A made switch shows a
    green dot inside its ring. The page draws them; this computes them.
    """

    kind = "field"

    def __init__(self, ctl):
        self.ctl = ctl
        self.switches = load_switches()
        self.leds = load_leds()
        self.coils = load_coils()
        self.last = None
        self.art = layout_art()
        wh = gameinfo.png_size(self.art) if self.art else None
        self.base = tuple(wh) if wh else layout_extent()

        self.fixtures = group_fixtures(self.leds)
        for n, F in enumerate(self.fixtures):
            F["fid"] = n
            F["state"] = ()
            F["vis"] = (0.0, 0.0, 0.0, 0.0, float(LED_R))
            F["v0"] = F["vt"] = None
            F["t0"] = 0.0
            F["drawn"] = None
        self.coil_seen = {}     # (node, index) -> last fire counter read
        self.coil_until = {}    # (node, index) -> ms after which the flash ends
        self.coil_drawn = {}    # (node, index) -> last hot/cold published
        self.fps = 0.0
        self._t_last = None
        self._read_ms = 0.0
        self._redrawn = 0
        self._log_t, self._log_n = time.perf_counter(), 0
        self._draw_ev = collections.deque()
        self._data_ev = collections.deque()
        self._decoded = None
        self._gap_worst = 0.0
        self._draw_last = None
        self._init_ring()
        self.chan_fix = {}
        for F in self.fixtures:
            for key in F["channels"].values():
                self.chan_fix.setdefault(key, []).append(F)

        self.sw_rows = list(self.switches)
        self._dot_drawn = {}
        self.trough = None
        self.sw = SwitchWatch(self.switches)
        if not self.sw.positions:
            # the trough lives under the playfield; the full switch list is
            # the same data without the coordinates - ask it before giving up
            self.sw.set_rows(load_switch_list())
        self._sw_next = time.monotonic() + SWITCH_POLL_S
        self.status = ""

    # ---- what the page draws ------------------------------------------------
    def spec(self):
        return {
            "kind": "field",
            "art": "art" if self.art else None,
            "base": list(self.base or (313, 710)),
            "fixtures": [[F["fid"], round(F["x"], 2), round(F["y"], 2)]
                         for F in self.fixtures],
            "coils": [[k, C["x"], C["y"],
                       "%s:%s" % (C["node"], C["index"])]
                      for k, C in enumerate(self.coils)],
            "switches": [[k, S["x"], S["y"], S["id"]]
                         for k, S in enumerate(self.sw_rows)],
            "trough": self.trough.spec() if (
                self.trough is not None and self.trough.clickable) else None,
        }

    def dyn(self):
        fx = {}
        for F in self.fixtures:
            if F["drawn"] is not None:
                fx[F["fid"]] = F["drawn"]
        return {"fx": fx,
                "coil": {"%s:%s" % k: 1 if v else 0
                         for k, v in self.coil_drawn.items()},
                "sw": {str(s): v for s, v in self._dot_drawn.items()},
                "trough": self.trough.dyn() if (
                    self.trough is not None and self.trough.clickable)
                else None}

    # ---- the switch table arriving mid-run ----------------------------------
    def _pick_up_switches(self):
        """THE SWITCH TABLE IS THE ONE PART THAT NEEDS A RUN - the game builds
        it on the heap, so the first run of a title opens this window without
        it. A stat every SWITCH_POLL_S while it is missing, nothing after."""
        if self.switches or time.monotonic() < self._sw_next:
            return False
        self._sw_next = time.monotonic() + SWITCH_POLL_S
        rows = load_switches()
        if not rows:
            return False
        self.switches = rows
        if not self.sw.positions and not self.sw.set_rows(rows):
            self.sw.set_rows(load_switch_list())
        self.sw_rows = list(rows)
        self.make_trough()
        return True

    def make_trough(self):
        """The trough, once known: on the KEY PANEL when there is one (item
        39), the artwork corner otherwise (the fallback for a window with no
        padbinds - an old renderer, a by-hand launch). Idempotent."""
        if self.trough is not None or not self.sw.positions:
            return
        if self.ctl.key_panel is not None:
            self.trough = self.ctl.key_panel.add_trough(self.sw.positions,
                                                        self.sw.how)
            return
        self.trough = TroughDots(self.sw.positions, self.sw.how,
                                 clickable=True)

    # ---- tooltips -----------------------------------------------------------
    def describe(self, kind, k):
        if kind == "switch":
            d = self.sw_rows[k]
            return ("SWITCH  %s\nid %d   node %d  bit %d\n"
                    "hold to keep it closed\nright-hold to RIP it (spinners)"
                    % (d["name"], d["id"], d["node"], d["bit"]))
        if kind == "coil":
            d = self.coils[k]
            where = ("node %d index %d" % (d["node"], d["index"])
                     if d["node"] is not None
                     else "group %d index %d (board unknown)" % (d["group"],
                                                                 d["index"]))
            fires, lvl = self._coil_state(d)
            live = ("\nfired %d time%s, drive %d"
                    % (fires, "" if fires == 1 else "s", lvl)
                    if fires is not None else "\nno coil data")
            act = coilact.describe(d["name"])
            how = "hold" if coilact.hold_switch(d["name"]) is not None else "click"
            return "COIL  %s\n%s%s\n%s: %s" % (
                d["name"], where, live, how, act or "nothing wired")
        d = self.fixtures[k]
        vals = self._chan_vals(d, self.last)
        fmt = lambda v: "%d" % v if v is not None else "no data"  # noqa: E731
        # node IS None for a lamp the table positions and the wire cannot
        # address (item 50/53) - "%d" % None is a TypeError
        where = lambda node, idx: (                              # noqa: E731
            "node %d  index %d" % (node, idx) if node is not None
            else "group %d  index %d  - no wire address for this board"
                 % (d.get("group", -1), idx))
        if "W" in d["channels"]:
            node, idx = d["channels"]["W"]
            return ("LED  %s\n%s\nvalue %s"
                    % (d["name"], where(node, idx), fmt(vals.get("W"))))
        lines = ["LED  %s   (RGB fixture)" % d["name"]]
        for chan in "RGB":
            if chan in d["channels"]:
                node, idx = d["channels"][chan]
                lines.append("%s  %s  value %s"
                             % (chan, where(node, idx), fmt(vals.get(chan))))
        return "\n".join(lines)

    # ---- the coil marker press ----------------------------------------------
    def coil_down(self, k):
        """A COIL MARKER IS THE ONE THE SCOOP ACTUALLY GETS (item 24): where
        the coil follows a switch, hold that switch; where it MOVES a ball
        there is nothing to hold and it stays a click. Returns the held id."""
        name = self.coils[k]["name"]
        sw = coilact.hold_switch(name)
        if sw is not None:
            return sw
        if coilact.describe(name):
            self.ctl.drv.run_script("coilact.py", name)
        return None

    # ---- live LED and coil state --------------------------------------------
    def read_leds(self):
        """(raw, d): raw whenever dump/padled could be READ at all (the
        emulator is there), d only once the shim has stamped its magic."""
        try:
            with open(LED_PATH, "rb") as f:
                raw = f.read(PADLED_READ)
        except OSError:
            return None, None
        if len(raw) < LED_HDR or struct.unpack_from("<I", raw, 0)[0] != PADLED_MAGIC:
            return raw, None
        return raw, raw

    def door_open(self):
        return self.sw.door

    def _coil_state(self, d):
        node = d["node"]
        if node is None or not self.last or len(self.last) < PADLED_READ:
            return None, None
        if struct.unpack_from("<I", self.last, 4)[0] < 2:
            return None, None
        o = node * COIL_N + d["index"]
        return self.last[COIL_OFF + o], self.last[LVL_OFF + o]

    def _tick_coils(self, d, now, out):
        """Flash a coil marker when its fire counter moves - a counter cannot
        miss a ~30 ms pulse the way an on/off bit between polls can."""
        fired = 0
        for C in self.coils:
            key = (C["node"], C["index"])
            node, idx = key
            if node is None:
                continue
            c = d[COIL_OFF + node * COIL_N + idx]
            if key in self.coil_seen and c != self.coil_seen[key]:
                self.coil_until[key] = now + COIL_FLASH_MS
            self.coil_seen[key] = c
            hot = self.coil_until.get(key, 0) > now
            fired += hot
            if self.coil_drawn.get(key) == hot:
                continue
            self.coil_drawn[key] = hot
            out["%s:%s" % key] = 1 if hot else 0
        return fired

    def draw_fixtures(self, d, now):
        """Set each fixture's fade TARGET from the wire. Returns (lit,
        changed). The wire carries steps and the real boards render the
        ramps, so a state change only RETARGETS the tween; `changed` counts
        decoded state moves - the honest picture rate - not tween frames."""
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
            if F.get("env"):
                F["dur"] = 0.0
            else:
                changed += 1
                F["dur"] = FADE_MS / 1000.0
            v = F["vis"]
            if rgb:
                rs, alpha = level_shape(level)
                if v[3] <= 0.0:
                    # a fade IN starts from the target's own hue at zero
                    # alpha, not from black
                    v = (float(rgb[0]), float(rgb[1]), float(rgb[2]),
                         0.0, v[4])
                    F["vis"] = v
                F["vt"] = (float(rgb[0]), float(rgb[1]), float(rgb[2]),
                           alpha, LED_R * rs)
            else:
                F["vt"] = (v[0], v[1], v[2], 0.0, float(LED_R))
            F["v0"] = v
            F["t0"] = now
        return lit, changed

    def animate_fixtures(self, now, out):
        """Advance every mid-fade fixture and publish the ones that moved.
        Linear, deliberately: a PWM ramp is linear in duty."""
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
                F["vt"] = None
            self._paint(F, vis, out)

    def _paint(self, F, vis, out):
        """One visual state, QUANTISED before the change-gate so a tween
        costs a handful of updates rather than one per frame: alpha in 1/32
        steps, radius in 0.25 px. The page blends with real alpha - what the
        Tk window had to fake by mixing toward a sampled artwork pixel."""
        alpha, rad = vis[3], vis[4]
        if alpha <= 1.0 / 64:
            want = 0
        else:
            want = [int(vis[0]), int(vis[1]), int(vis[2]),
                    round(alpha * 32) / 32.0, round(rad * 4) / 4.0]
        if want == F["drawn"]:
            return
        F["drawn"] = want
        self._redrawn += 1
        out[F["fid"]] = want

    def tick(self, now_mono):
        """One frame. Returns the changes for the page, or None when the run
        has gone (the LED block disappeared after being seen)."""
        t0 = time.perf_counter()
        if self._t_last:
            dt = t0 - self._t_last
            self.fps = 1.0 / dt if not self.fps else self.fps * 0.9 + 0.1 / dt
        self._t_last = t0
        frame = {}
        if self._pick_up_switches():
            frame["layout"] = True

        # ONE PACED READ OF THE SWITCH BLOCK feeds the dot in every switch
        # ring, the trough, the key panel and the coin-door warning.
        self.ctl.poll_switches(self, frame)

        t_read = time.perf_counter()
        raw, d = self.read_leds()
        self._read_ms = (time.perf_counter() - t_read) * 1000.0
        self.last = d
        if emu_gone(self, raw is not None):
            return None
        state_msg = self.ctl.state_status()
        if d is None:
            status = (state_msg
                      or ("emulator up, no LED writes decoded yet"
                          " (normal through boot and Tech Alerts:"
                          " the attract light show is the first)"
                          if raw is not None else
                          "no emulator (dump/padled not readable)"))
        else:
            decoded = struct.unpack_from("<I", d, LED_DECODED_OFF)[0]
            skipped = struct.unpack_from("<I", d, LED_SKIPPED_OFF)[0]
            if self._decoded is not None and decoded != self._decoded:
                _mark(self._data_ev, t0)
            self._decoded = decoded
            nfades = self._take_fades(d, t0)
            for _ in range(nfades):
                self._draw_ev.append(t0)
                self._data_ev.append(t0)
            lit, changed = self.draw_fixtures(d, t0)
            if changed:
                _mark(self._draw_ev, t0)
            if changed or nfades:
                if self._draw_last is not None:
                    self._gap_worst = max(self._gap_worst, t0 - self._draw_last)
                self._draw_last = t0
            fx = {}
            self.animate_fixtures(t0, fx)
            if fx:
                frame["fx"] = fx
            coils = ""
            if len(d) >= PADLED_READ and struct.unpack_from("<I", d, 4)[0] >= 2:
                cf = {}
                self._tick_coils(d, time.monotonic() * 1000.0, cf)
                if cf:
                    frame["coil"] = cf
                coils = "   %d coils addressed" % struct.unpack_from(
                    "<I", d, COIL_GEN_OFF + 4)[0]
                if self.door_open():
                    coils += "   COIN DOOR OPEN: 48V off, no coil can fire"
            drops = ", %d dropped" % skipped if skipped else ""
            if not self.sw.positions:
                coils += "   no trough switches identified"
            draw_hz = _rate(self._draw_ev, t0)
            data_hz = _rate(self._data_ev, t0)
            status = (state_msg
                      or " %d of %d inserts lit   LED %.1f Hz   data %.1f Hz"
                         " (%d writes%s)%s   poll %.0f fps"
                         % (lit, len(self.fixtures), draw_hz, data_hz,
                            decoded, drops, coils, self.fps))
        if status != self.status:
            self.status = status
            frame["status"] = status
        self._log(t0, (time.perf_counter() - t0) * 1000.0)
        return frame

    def _log(self, t0, spent):
        """PAD_PF_LOG=<path>: one line a second of what the loop is doing -
        the rate MEASURED rather than read off a screenshot, the read/compute
        split, the picture rate and the worst freeze since the last line."""
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
                           self._redrawn, _rate(self._draw_ev, t0),
                           _rate(self._data_ev, t0), self._gap_worst))
        except OSError:
            pass
        self._log_t, self._log_n, self._redrawn = t0, 0, 0
        self._gap_worst = 0.0


class Schematic:
    """The window for a title with NO usable positions: every switch, by node,
    clickable, and the LED swatch grid beside it.

    This is not a lesser playfield, it is a different question answered: with
    no device table there is nothing to place markers on, and inventing
    coordinates from names is exactly the guess this project keeps undoing.
    The rows FLOW into columns the window's height actually has (item 39);
    the page scrolls sideways rather than clip, so every row stays reachable.
    The grid goes on the LEFT (item 50: the lamps are what this view is FOR on
    a title with no artwork; the switch list is what scrolls).
    """

    kind = "schematic"

    def __init__(self, ctl, switches):
        self.ctl = ctl
        self.switches = switches
        self.last = None
        # ★ SAY HOW MANY OF THEM THIS BUILD CAN ACTUALLY WORK (2026-09-08):
        # ids past padsw.MAX_ID are positions in the device array, not
        # addresses this rig has (SwitchWatch.addressable()).
        dead = sum(1 for sw in switches
                   if not (0 <= sw["id"] < padsw.MAX_ID))
        note = ("  - click a row to close that switch" if not dead else
                "  - %d of them cannot be read or clicked on this build "
                "(their ids are past the %d this rig addresses)"
                % (dead, padsw.MAX_ID))
        self.bar = "%s: %d switches, no playfield artwork in this title%s" % (
            GAME, len(switches), note)
        self.sw = SwitchWatch(switches,
                              every=round(1000.0 / POLL_MS / max(1.0, SW_HZ)))
        self._dot_drawn = {}
        self.trough = None
        if self.sw.positions:
            # the strip is the FALLBACK: the key panel takes it over
            self.trough = TroughDots(self.sw.positions, self.sw.how,
                                     clickable=True)
        by_node = {}
        for sw in switches:
            by_node.setdefault(sw["node"], []).append(sw)
        self.entries = []
        for node in sorted(by_node):
            self.entries.append({"hdr": node})
            for sw in sorted(by_node[node], key=lambda s: s["bit"]):
                live = 0 <= sw["id"] < padsw.MAX_ID
                self.entries.append({
                    "id": sw["id"], "name": sw["name"][:26], "live": live,
                    "tip": ("SWITCH  %s\n"
                            "id %d   num %d   node %d  bit %d\n"
                            "hold to keep it closed\n"
                            "right-hold to RIP it (spinners)"
                            % (sw["name"], sw["id"], sw.get("num", -1),
                               sw["node"], sw["bit"]))})
        self.leds = LedGrid(load_led_names())
        self.led_lit, self.led_total = 0, 0
        self._grid_gen = 0
        self.status = ""

    def spec(self):
        return {"kind": "schematic", "bar": self.bar, "entries": self.entries,
                "grid": self.leds.spec(),
                "trough": self.trough.spec() if (
                    self.trough is not None and self.trough.clickable)
                else None}

    def dyn(self):
        return {"sw": {str(s): v for s, v in self._dot_drawn.items()},
                "grid": self.leds.dyn(),
                "trough": self.trough.dyn() if (
                    self.trough is not None and self.trough.clickable)
                else None}

    def make_trough(self):
        """The strip, when the key panel that had taken the trough over goes
        (padbinds withdrawn mid-run): the balls must not lose their only
        control on a title with no artwork."""
        if self.trough is None and self.sw.positions:
            self.trough = TroughDots(self.sw.positions, self.sw.how,
                                     clickable=True)

    def describe(self, kind, k):
        return ""

    def tick(self, now_mono):
        try:
            with open(LED_PATH, "rb") as f:
                d = f.read(PADLED_READ)
        except OSError:
            d = None
        if emu_gone(self, bool(d)):
            return None
        frame = {}
        self.ctl.poll_switches(self, frame)
        state_msg = self.ctl.state_status()
        # ★ THE MAGIC IS NOT THE TEST FOR "IS THERE AN EMULATOR" (item 50):
        # readable-and-unstamped is a run with no LED data, not no run.
        if d:
            lit, total, changes, grew = self.leds.tick(d, time.perf_counter())
            self.led_lit, self.led_total = lit, total
            if grew:
                frame["layout"] = True
            if changes:
                frame["grid"] = changes
        if not d:
            status = state_msg or "no emulator (dump/padled not readable)"
        elif struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            status = (state_msg
                      or " emulator up   NO LED DATA on this title: the shim"
                         " has decoded no LED writes at all   %s"
                         % (self.sw.balls.text() if self.sw.positions
                            else "no trough switches identified"))
        else:
            status = (state_msg
                      or " emulator up   %d of %d LEDs lit   %d LED writes"
                         " decoded   %d coils addressed   %s"
                         % (self.led_lit, self.led_total,
                            struct.unpack_from("<I", d, 12)[0],
                            struct.unpack_from("<I", d, COIL_GEN_OFF + 4)[0]
                            if len(d) >= PADLED_READ else 0,
                            self.sw.balls.text() if self.sw.positions
                            else "no trough switches identified"))
        if status != self.status:
            self.status = status
            frame["status"] = status
        return frame



WAITING_TEXT = ("No tables for %s yet - WAITING for them.\n\n"
                "They are built from the title's own files, not\n"
                "shipped: mktables.py reads the game binary for\n"
                "positions and the run log for the switch list.\n\n"
                "  tables : %s\n"
                "  game   : %s\n\n"
                "The switch list only exists once the game has\n"
                "published its table, a few seconds into a run, so\n"
                "the first start of a title lands here first. This\n"
                "window picks them up by itself when they arrive.\n\n"
                "A boot menu on this card already has the keyboard,\n"
                "here or in the game window: arrows choose, 1 or\n"
                "Space boots.")

#: How long a window with no tables keeps looking for them (poll_for_tables'
#: old timeout): a stat every two seconds costs nothing next to a wasted
#: run, and the bound stops an abandoned window polling forever.
TABLES_TIMEOUT_S = 900
TABLES_EVERY_S = 2.0


class Playfield:
    """The window's one controller: which view, the loop, and the page's
    actions. ONE SwitchDriver for the life of the window (every view, the key
    panel, the keyboard fallback and the villain vision's art fetches ride
    it), ONE key panel, ONE flash slot for "what the last thing you pressed
    did" - the same single slot the Tk views each kept, for the same reason:
    two slots would race for one status line with no rule about which won.

    Everything the page can call arrives on server threads and everything
    the loop does runs on its own thread; `lock` serialises the two, so a
    model is never read half-updated.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.host = None
        self.drv = SwitchDriver()
        self.view = None
        self.kind = None
        self.key_panel = None
        self.keys = None
        self.acts_shown = True
        self._binds_next = time.monotonic() + SWITCH_POLL_S
        self._binds_mtime = None
        self._ball_next = 0.0
        self._ball_status = (None, [])
        self.holding = None
        self.ripping = None
        self.slot_labels = {}
        self._state_busy = False
        self._state_msg = None
        self._stop = threading.Event()
        self._closed = False
        self.pos = {}
        self.lcd = LcdPanel(GAME, on_build=self._open_lcd)
        self.lcd.drv = self.drv
        self._wait_deadline = time.time() + TABLES_TIMEOUT_S
        self._wait_next = time.monotonic() + TABLES_EVERY_S
        self._build_view()
        if SAVESTATES:
            self.slots_refresh()

    # ---- which view --------------------------------------------------------
    def _build_view(self, rows=None):
        """ARTWORK (positions) IF THE TITLE HAS A USABLE LAYOUT, THE SWITCH
        LIST IF IT DOES NOT, and a WAITING page while neither exists yet."""
        if layout_is_usable():
            self.view = Field(self)
        else:
            rows = rows if rows is not None else load_switch_list()
            if rows:
                self.view = Schematic(self, rows)
            else:
                self.view = None
                self.kind = "waiting"
                # ★ THE BOOT MENU RUNS BEFORE THE GAME, so on a multi-image
                # card's first run this is the window on screen while the menu
                # is: its buttons go by NAME, which needs no table.
                self.keys = KeyInput(self, [])
                return
        self.kind = self.view.kind
        self.view.make_trough()
        self._binds_next = time.monotonic() + SWITCH_POLL_S
        self.attach_key_panel(self.view)
        self._binds_mtime = _binds_mtime()

    def swap_in(self, rows):
        """The tables landed while the WAITING page was up."""
        if self.keys is not None:
            self.keys.detach()
            self.keys = None
        self._build_view(rows)
        self.publish("layout")

    # ---- the key panel -----------------------------------------------------
    def attach_key_panel(self, view):
        """The panel beside the view, or None - the NORMAL state for the first
        seconds of a session (padglhost writes padbinds once it is up). The
        ball controls move in with it, and the bottom action row goes: every
        action on it has a home on the panel (PAD-134)."""
        rows = keybinds.load(BINDS_PATH)
        if not rows:
            self.key_panel = None
            self.acts_shown = True
            if view.trough is None:
                view.make_trough()
            return None
        panel = KeyPanel(rows, self.drv, on_action=self.run_action)
        if view.trough is not None and view.trough.clickable:
            view.trough = None
        self.key_panel = panel
        if view.sw.positions:
            view.trough = panel.add_trough(view.sw.positions, view.sw.how)
        if self.keys is not None:
            self.keys.close()
        self.keys = KeyInput(self, rows)
        self.acts_shown = False
        return panel

    def poll_switches(self, view, frame):
        """The paced switch read and everything that hangs off it, for both
        views: the dot in every switch marker, the trough, the key panel (and
        its arrival or rebuild when padbinds appears or changes - ★ item 49:
        padglhost RE-exports once the switch table arrives), the BALLS
        section. Every change is gated: a still machine costs the read."""
        if not view.sw.poll():
            return False
        ids = ([S["id"] for S in view.sw_rows] if view.kind == "field"
               else [e["id"] for e in view.entries
                     if "id" in e and e["live"]])
        changes = {}
        for sid in ids:
            made = view.sw.is_made(sid)
            if sid in view._dot_drawn and view._dot_drawn[sid] == made:
                continue
            view._dot_drawn[sid] = made
            changes[str(sid)] = made
        if changes:
            frame["sw"] = changes
        if view.trough is not None:
            on_panel = (self.key_panel is not None
                        and view.trough is self.key_panel.ball_dots)
            if view.trough.update(view.sw.closed(),
                                  dots_caption(view.sw) if on_panel
                                  else trough_text(view.sw)):
                if on_panel:
                    self.key_panel.dirty = True
                else:
                    frame["trough"] = view.trough.dyn()
        if time.monotonic() >= self._binds_next:
            self._binds_next = time.monotonic() + SWITCH_POLL_S
            if self.key_panel is None:
                if self.attach_key_panel(view) is not None:
                    self._binds_mtime = _binds_mtime()
                    frame["layout"] = True
            else:
                m = _binds_mtime()
                if m != self._binds_mtime:
                    self._binds_mtime = m
                    if self.keys is not None:
                        self.keys.close()
                        self.keys = None
                    self.key_panel.release_held()
                    view.trough = None
                    self.key_panel = None
                    self.attach_key_panel(view)
                    frame["layout"] = True
        if self.key_panel is not None:
            self.key_panel.update(view.sw)
            if time.monotonic() >= self._ball_next:
                self._ball_next = time.monotonic() + BALL_POLL_S
                self._ball_status = read_ball_status()
            fed, lines = self._ball_status
            self.key_panel.show_balls(view.sw, fed, lines)
            if self.key_panel.dirty:
                self.key_panel.dirty = False
                frame["panel"] = self.key_panel.dyn()
        return True

    # ---- helpers and the status line's flash slot ----------------------------
    def flash(self, text, secs=8.0):
        """One line over the view's own status, for `secs` (None = until
        replaced) - the result of the last thing pressed."""
        self._state_msg = (text, None if secs is None
                           else time.monotonic() + secs)

    def state_status(self):
        m = self._state_msg
        if not m:
            return None
        text, until = m
        if until is not None and time.monotonic() > until:
            self._state_msg = None
            return None
        return text

    def run_helper(self, script, arg=None):
        """Run one helper and put ITS OWN ANSWER in the status line
        (helper_message() carries why the answer used to be dropped). A
        plunge.py reply also lands in the BALLS note, beside the feeder's
        lines and under the button that asked (PAD-134)."""
        def done(r):
            text = helper_message(script, r)
            with self.lock:
                self.flash(text)
                if script == "plunge.py" and self.key_panel is not None:
                    self.key_panel.ball_say("%s: %s" % (arg, text)
                                            if arg else text)
        if arg is None:
            self.drv.run_script(script, done=done)
        else:
            self.drv.run_script(script, arg, done=done)

    def run_action(self, script, arg=None):
        self.run_helper(script, arg)

    def run_plunge(self, what):
        self.run_helper("plunge.py", what)

    # ---- save states ---------------------------------------------------------
    def slot_values(self):
        vals = []
        for i, sid in enumerate(SLOT_IDS):
            label = self.slot_labels.get(sid)
            if label is None:
                vals.append("%d · (empty)" % (i + 1))
            else:
                vals.append("%d · %s" % (i + 1, label or "unnamed"))
        return vals

    def slots_refresh(self):
        def work():
            info = state_slots()
            with self.lock:
                self.slot_labels = {s: info[s] for s in info}
            self.publish("slots", {"values": self.slot_values(),
                                   "labels": self.slot_labels,
                                   "busy": self._state_busy})
        threading.Thread(target=work, daemon=True).start()

    def run_state(self, script, slot, label=None):
        """One at a time, off every other thread that matters: a save dumps
        ~500 MB and a load is a criu restore, so it must never sit on the
        SwitchDriver queue behind a held flipper's release."""
        if self._state_busy:
            return False
        self._state_busy = True
        verb = "saving" if script.startswith("save") else "loading"
        self.flash("%s state..." % verb, None)
        self.publish("slots", {"values": self.slot_values(),
                               "labels": self.slot_labels, "busy": True})

        def work():
            r = state_run(script, slot, label)
            with self.lock:
                self._state_busy = False
                self.flash(state_reply(script, r))
            self.slots_refresh()
        threading.Thread(target=work, daemon=True).start()
        return True

    # ---- the loop ------------------------------------------------------------
    def publish(self, etype, data=None):
        if self.host is not None:
            self.host.publish(etype, data)

    def start(self):
        threading.Thread(target=self._loop, name="playfield-loop",
                         daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        """PACED, not slept: the work is subtracted from the frame, so the
        START-to-START interval is the target (60 fps on the artwork view,
        POLL_MS on the schematic and the waiting page)."""
        while not self._stop.is_set():
            t0 = time.perf_counter()
            with self.lock:
                try:
                    self._tick()
                except Exception:                           # noqa: BLE001
                    # one surprise costs one frame, never the window
                    import traceback
                    traceback.print_exc()
            period = FRAME_MS if self.kind == "field" else POLL_MS
            spent = (time.perf_counter() - t0) * 1000.0
            self._stop.wait(max(0.001, (period - spent) / 1000.0))

    def _tick(self):
        now = time.monotonic()
        if self.kind == "waiting":
            if (now >= self._wait_next
                    and time.time() < self._wait_deadline):
                self._wait_next = now + TABLES_EVERY_S
                rows = load_switch_list()
                if rows:
                    self.swap_in(rows)
        elif self.view is not None:
            frame = self.view.tick(now)
            if frame is None:
                self.gone()
                return
            if frame.pop("layout", False):
                self.publish("layout")
            if frame:
                self.publish("frame", frame)
        self.lcd.poll()
        if self.lcd.dirty:
            self.lcd.dirty = False
            self.publish("lcd", self.lcd.dyn())

    # ---- windows ---------------------------------------------------------------
    def window_spec(self):
        """The main window's first size and place. The artwork fits the
        screen's height like the Tk window's pick_scale (PAD_PF_SCALE still
        overrides), and the page rescales it to whatever the window becomes."""
        sw_, sh_ = pfweb.screen_size()
        panel_w = 340 if keybinds.load(BINDS_PATH) else 0
        if self.kind == "field":
            bw, bh = self.view.base
            env = os.environ.get("PAD_PF_SCALE")
            try:
                scale = max(1.0, float(env)) if env else None
            except ValueError:
                scale = None
            if scale is None:
                scale = max(1.0, (sh_ - 170) / float(bh))
                scale = min(scale, max(0.5, (sw_ - 80 - panel_w) / float(bw)))
            w = int(bw * scale) + panel_w + 16
            h = int(bh * scale) + 70
        elif self.kind == "schematic":
            w = min(sw_ - 160, 1500)
            h = sh_ - 110
        else:
            w, h = 720, 620
        st = load_state()
        pos = st.get("playfield_pos")
        spec = {"page": "main", "title": WINDOW_TITLE, "width": w,
                "height": min(h, sh_ - 20), "min_size": (420, 360)}
        if pos and _onscreen(sw_, sh_, *pos):
            spec["x"], spec["y"] = pos
        return spec

    def _open_lcd(self):
        spec = self.lcd.spec()
        w, h = spec["size"]
        win = {"page": "lcd", "title": spec["title"], "width": w + 24,
               "height": h + spec["th"] + 118, "fixed": True,
               "min_size": (200, 160)}
        sw_, sh_ = pfweb.screen_size()
        pos = load_state().get("villain_pos")
        if pos and _onscreen(sw_, sh_, *pos):
            win["x"], win["y"] = pos
        if self.host is not None:
            self.host.open_window("lcd", win, on_close=self._lcd_closed)

    def _lcd_closed(self):
        with self.lock:
            self.save_state()
            self.lcd.hide()

    def save_state(self):
        """Where the windows were, so they open there next time. Position only
        - the artwork is sized from the screen, and a stale size would clip
        it after a resolution change."""
        try:
            st = load_state()
            for name, key in (("main", "playfield_pos"),
                              ("lcd", "villain_pos")):
                p = None
                if self.host is not None:
                    p = self.host.geometry(name)
                p = p or self.pos.get(name)
                if p:
                    st[key] = [int(p[0]), int(p[1])]
            with open(STATE, "w") as f:
                json.dump(st, f, indent=1)
        except Exception:                                   # noqa: BLE001
            pass

    def gone(self):
        """The run ended (its LED block went): save first - leaving with the
        run is the COMMON way this window closes - then close everything."""
        self.save_state()
        self.publish("close")
        self._stop.set()
        if self.host is not None:
            threading.Thread(target=self.host.quit, daemon=True).start()

    def bye(self):
        """The window is closing, whoever closed it. OPEN ANYTHING STILL HELD
        BEFORE THE PROCESS GOES: nothing on this side would exist any more to
        clear a switch left made, and the game would see it stuck for the rest
        of the run."""
        if self._closed:
            return
        self._closed = True
        with self.lock:
            self._stop.set()
            if self.holding is not None:
                self.drv.release(self.holding)
                self.holding = None
            if self.ripping is not None:
                self.drv.spin(self.ripping, False)
                self.ripping = None
            if self.key_panel is not None:
                self.key_panel.release_held()
            if self.keys is not None:
                self.keys.release_all()
                self.keys.close()
            self.save_state()
        self.drv.release_all()
        self.publish("close")

    # ---- what the page asks --------------------------------------------------
    def state(self, page):
        with self.lock:
            if page == "lcd":
                return {"lcd": self.lcd.spec(), "dyn": self.lcd.dyn()}
            st = {"title": WINDOW_TITLE, "game": GAME, "kind": self.kind,
                  "savestates": SAVESTATES, "slots": self.slot_values(),
                  "state_busy": self._state_busy,
                  "acts": ([[i, a[0]] for i, a in enumerate(WINDOW_ACTIONS)]
                           if self.acts_shown and self.view is not None
                           else []),
                  "panel": ({"spec": self.key_panel.spec(),
                             "dyn": self.key_panel.dyn()}
                            if self.key_panel is not None else None)}
            if self.kind == "waiting":
                st["waiting"] = WAITING_TEXT % (GAME, TDIR,
                                                gameinfo.game_dir(GAME))
                st["status"] = ""
            else:
                st["view"] = self.view.spec()
                st["dyn"] = self.view.dyn()
                st["status"] = self.view.status
            return st

    def file(self, name):
        if name == "art" and isinstance(self.view, Field) and self.view.art:
            return self.view.art
        return None

    def blob(self, key):
        return BLOBS.get(key)

    def api(self, m, a):
        fn = getattr(self, "api_" + str(m), None)
        if fn is None:
            raise ValueError("no such call: %s" % m)
        with self.lock:
            return fn(*a)

    # switches on the artwork / schematic rows -- press is held until the
    # page's release, and the release opens what was HELD (a drag off the
    # marker before letting go must not leave the switch made)
    def api_hold(self, sw_id):
        if self.holding is not None:
            self.drv.release(self.holding)
        self.holding = int(sw_id)
        self.drv.press(self.holding)
        return True

    def api_unhold(self):
        if self.holding is None:
            return False
        sw_id, self.holding = self.holding, None
        self.drv.release(sw_id)
        return True

    def api_rip(self, sw_id, on):
        """Right-hold RIPS a switch (item 26): the shim alternates it at the
        game's own scan rate for as long as the button is down."""
        if on:
            if self.ripping is not None:
                self.drv.spin(self.ripping, False)
            self.ripping = int(sw_id)
            self.drv.spin(self.ripping, True)
        elif self.ripping is not None:
            self.drv.spin(self.ripping, False)
            self.ripping = None
        return True

    def api_coil(self, k):
        if not isinstance(self.view, Field):
            return None
        sw = self.view.coil_down(int(k))
        if sw is not None:
            self.api_hold(sw)
        return sw

    def api_tip(self, kind, k):
        if self.view is None:
            return ""
        try:
            return self.view.describe(kind, int(k))
        except (IndexError, ValueError, KeyError):
            return ""

    def api_action(self, i):
        label, script, arg = WINDOW_ACTIONS[int(i)]
        self.run_action(script, arg)
        return label

    def api_trough(self, i):
        """A click on a CLICKABLE trough dot (the fallback strip)."""
        t = getattr(self.view, "trough", None)
        if t is None or not t.clickable:
            return None
        what = t.click(int(i))
        self.run_plunge(what)
        return what

    def api_ball(self, what):
        if what not in ("plunge", "drain", "reset"):
            return False
        # A GREYED DRAIN IS NOTHING, whatever the page thought it showed
        # (PAD-153: draining before plunging is an endless cycle). The page
        # disables the button; this is the rule, so a stale page cannot
        # press through it.
        if (what == "drain" and self.key_panel is not None
                and not self.key_panel._drain_live):
            return False
        self.run_plunge(what)
        return True

    def api_svc(self, sw_id, down):
        if self.key_panel is None:
            return False
        if down:
            self.key_panel.svc_press(int(sw_id))
        else:
            self.key_panel.svc_release()
        return True

    def api_row(self, sw_id, down):
        if self.key_panel is None:
            return False
        if down:
            self.key_panel.row_press(int(sw_id))
        else:
            self.key_panel.row_release()
        return True

    def api_door(self):
        if self.key_panel is not None:
            self.key_panel.door_click()
        return True

    def api_clear_alerts(self):
        label, script, arg = next(a for a in WINDOW_ACTIONS
                                  if a[1] == "swexercise.py")
        self.run_action(script, arg)
        return True

    def api_key(self, code, key, down):
        sym = code_to_keysym(code, key)
        if sym is None or self.keys is None:
            return False
        return self.keys.key(sym, bool(down))

    def api_blur(self):
        if self.keys is not None:
            self.keys.release_all()
        self.api_unhold()
        if self.ripping is not None:
            self.api_rip(self.ripping, False)
        if self.key_panel is not None:
            self.key_panel.release_held()
        return True

    def api_save(self, idx, label):
        if not SAVESTATES:
            return False
        slot = SLOT_IDS[int(idx)]
        return self.run_state("savegame.sh", slot, clean_label(label) or None)

    def api_load(self, idx):
        if not SAVESTATES:
            return False
        slot = SLOT_IDS[int(idx)]
        if slot not in self.slot_labels:
            self.flash("slot %d is empty - nothing to load" % (int(idx) + 1),
                       5.0)
            return False
        return self.run_state("loadgame.sh", slot)

    def api_slots(self):
        self.slots_refresh()
        return self.slot_values()

    def api_geom(self, page, x, y):
        self.pos["lcd" if page == "lcd" else "main"] = (int(x), int(y))
        return True

    def api_lcd_close(self):
        self.save_state()
        self.lcd.hide()
        if self.host is not None:
            self.host.show_window("lcd", False)
        return True


def _onscreen(sw_, sh_, x, y):
    """Reject a remembered position that is off every monitor - unplugging a
    second display must not leave the window at -1800,300 for good."""
    return -50 <= x <= sw_ - 120 and -20 <= y <= sh_ - 80


def main():
    if raise_existing():
        # SAY SO: from outside this is a launch that started and stopped
        # with no window to show for it, which is what a crash looks like.
        print("playfield: a window called %r already exists, so it was raised "
              "instead of a second one being opened. If nothing came to the "
              "front, that window is a leftover from an earlier run that WSL "
              "can no longer draw - Stop offers the WSL restart that clears "
              "one." % WINDOW_TITLE)
        return
    ctl = Playfield()
    host = pfweb.WebHost(os.path.join(HERE, "pfpage"), ctl, title=WINDOW_TITLE)
    ctl.host = host
    host.start()
    ctl.start()
    try:
        host.run(ctl.window_spec(), on_close=ctl.bye)
    finally:
        ctl.bye()
        ctl.stop()
        host.stop()


if __name__ == "__main__":
    # The finer timer is asked for around the WHOLE session and released
    # after it: Windows' default 15.6 ms tick makes the 60 fps loop
    # unreachable (fine_timers() has the measurement).
    fine = fine_timers()
    try:
        main()
    finally:
        if fine:
            coarse_timers()
