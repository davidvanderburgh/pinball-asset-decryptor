#!/usr/bin/env python3
"""Switch matrix for an emulated JJP game: a playfield view and a labelled list.

WHAT IT IS
----------
Two views of the same machine, side by side:

* the game's OWN playfield photograph (``graphics/Game Tests/pf_image.png``,
  decrypted out of its edata) carrying EVERY placed device - switches, lamps and
  coils - each one hoverable and the switches clickable.  The photo scales with
  the window and the markers ride on top of it, so the view keeps its aspect
  ratio at any size.  This is the primary view; anything it can already show is
  deliberately not repeated in a panel beside it;
* a LABELLED switch table - every REAL switch by name, grouped into Cabinet /
  Playfield / Mechanism, so you can see what each one is at a glance.  Click a
  row to pulse it, right-click to latch.

  Switches the title does not use are left out.  They are not a minor
  proportion: Wonka names 69 of its 296 switch addresses and calls the other 227
  "not used", so listing them buries the real ones in seven times their number
  of blanks.

Switch state lives in the POSIX shared-memory block defined by ``jjpshm.h`` and
is read by ``jjphwshim.c`` / ``jjpcuse.c`` on every ``read()`` of the I/O board.
This file PARSES jjpshm.h for the layout rather than restating it, because two
places defining one fact is the specific mistake that has bitten this rig
hardest.

THE WHOLE FRAME IS DRIVEN, AND IT IS MIXED POLARITY
---------------------------------------------------
The IN frame is 64 bytes and the game reads switches from ALL of it: bytes 0..3
are the direct/cabinet switches (start, flippers, coins, menu buttons), 4..19
the 128-switch playfield matrix, 20..36 the stepper/topper switches.  Every
switch is driven by its ABSOLUTE (frame_byte, frame_bit), so start and the
flippers - which live below the matrix - have a route.

The cabinet region is ACTIVE LOW and the rest ACTIVE HIGH (measured; jjpshm.h
carries the evidence).  Only SwitchShm.set_switch/get_switch know that; the UI
says "closed" and means closed.  It matters because a zeroed frame is not idle -
it is a machine with both flippers, all the menu buttons and the plumb-bob tilt
jammed on, which is why Start used to do nothing.

BALLS
-----
jjpball.py answers the game's coils: the trough eject puts a ball in the shooter
lane, the auto launcher takes it out again.  A DRAIN cannot be observed - there
is no playfield physics - so it is a button and the D key.

MOMENTARY vs LATCHED
--------------------
Real playfield switches are momentary.  Left-click / a bound key PULSES a switch
(close, then open after --pulse-ms).  Right-click / Shift+key LATCHES it, which
is what you want for things that are really held - a ball in the trough, the
coin door.

KEYBOARD
--------
Common controls get keyboard shortcuts, resolved per-title from the switch
names.  Each one is shown in its OWN switch's row (the Key column) and on the
ball buttons, rather than in a legend panel repeating the same pairs a second
time.  Keys work while THIS window is focused (the game itself has no keyboard
input - a real cabinet has none either).

THE TWO COLUMNS ARE FIXED WIDTHS
--------------------------------
The switch column is pinned at ``RIGHT_W`` and the playfield takes the rest, so
the photograph only ever changes size when the WINDOW does.  It used to be sized
by whatever its widest child asked for, and three of those children rewrite
their text ten times a second - so a longer status string made the column grow,
the playfield shrink and the photo rescale, with nothing on the machine having
moved.  See ``RIGHT_W``.

HOVER TELLS YOU WHAT SOMETHING IS
---------------------------------
Hovering any marker raises a tooltip AT THE POINTER.  It used to write into a
label beside the playfield, which meant reading in one place while pointing in
another - and on a 385x768 photo scaled to a tall window that is a long way for
the eye to travel.  The tooltip is drawn as canvas items rather than as a
borderless Toplevel on purpose: a second X window is exactly what makes WSLg
mis-handle surfaces (see the second-window race this rig has already been bitten
by), and a tooltip is not worth that risk.

LEDS ARE RGB, AND BRIGHTNESS IS DRAWN AS OPACITY
------------------------------------------------
Playfield lamps render their colour (three bytes each).  Brightness is shown by
COMPOSITING the lamp over the photograph rather than by painting a darker
square: an insert at a tenth brightness is a tenth-opacity tint of its own
colour, which is what the eye reads as dim.  Painting the raw dark colour
instead made every level below about half look the same flat near-black blob,
so a fading lamp did not appear to fade at all.  Tk has no alpha, so the blend
is done against the photo's own pixels - see ``MatrixUI._lamp_paint``.

The per-lamp byte mapping is still PROVISIONAL - see ``MatrixUI.led_rgb``.

COILS
-----
Coils are drawn too (amber diamonds), and they FLASH when the game fires them.
That is not decoration: it is the only direct evidence that the game is driving
the machine, and it is read from the same rising-edge counters jjpball answers
ejects with, so the picture and the ball feeder can never disagree.
"""

import argparse
import json
import mmap
import os
import re
import signal
import sys
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jjpball                                                   # noqa: E402

# Smooth playfield scaling needs Pillow.  Without it the photo shows at native
# size (still letterbox-centred in a resizable window); markers stay aligned
# either way, and the UI says once how to enable scaling.
try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
    try:
        _RESAMPLE = Image.Resampling.BILINEAR       # Pillow >= 9.1
    except AttributeError:
        _RESAMPLE = Image.BILINEAR
except ImportError:
    _HAVE_PIL = False

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SHM = '/jjp_switches'
DEFAULT_GEOM = os.path.join(os.path.expanduser('~'), '.jjp_matrix.json')
#: First-run window size (clamped to the screen).  Sized so the scaled
#: playfield and the full switch table sit side by side without scrolling.
DEFAULT_W = 1450
DEFAULT_H = 1754

#: The switch table's columns, in order: (id, heading, pixel width, anchor).
#: The right-hand column's fixed width is DERIVED from these rather than being
#: a second number that has to be kept in step with them.
TREE_COLS = (
    ('#0',   'Switch', 248, 'w'),
    ('num',  '#',       44, 'e'),
    ('key',  'Key',     78, 'center'),
    ('addr', 'Frame',   54, 'center'),
)
SCROLLBAR_W = 18

#: THE RIGHT-HAND COLUMN IS A FIXED WIDTH, and that is load-bearing.
#:
#: It used to take whatever width its widest child asked for.  Three of those
#: children re-write their text on every 100 ms tick - the ball state, the
#: three-line ball log and the LED note - so the column silently grew and shrank
#: as the wording changed, the playfield beside it (which expands into whatever
#: is left) was handed a different width each time, and the photograph rescaled
#: under the pointer.  Nothing had moved on the machine; only the length of a
#: status string had.  Pinning the column means the playfield only ever changes
#: size when the WINDOW does.
RIGHT_W = sum(w for _id, _h, w, _a in TREE_COLS) + SCROLLBAR_W


# --------------------------------------------------------------------------
# Layout, parsed from the C header so there is exactly one definition of it.
# --------------------------------------------------------------------------

def shm_layout(header=None):
    """Read the #defines and the board enum out of jjpshm.h."""
    path = header or os.path.join(HERE, 'jjpshm.h')
    text = open(path).read()
    want = ('JJP_MATRIX_FIRST_BYTE', 'JJP_MATRIX_BYTES', 'JJP_MATRIX_SWITCHES',
            'JJP_FRAME_LEN', 'JJP_DIRECT_FIRST_BYTE', 'JJP_DIRECT_BYTES',
            'JJP_DIRECT_IDLE')
    out = {}
    for key in want:
        m = re.search(rf'^#define\s+{key}\s+(0x[0-9a-fA-F]+|\d+)', text, re.M)
        if m:
            out[key] = int(m.group(1), 0)
    m = re.search(r'enum\s*\{(.*?)\}', text, re.S)
    if not m:
        raise RuntimeError('jjpshm.h: board enum not found')
    names = [n.strip().split('=')[0].strip()
             for n in m.group(1).split(',') if n.strip()]
    out['boards'] = {name: i for i, name in enumerate(names)
                     if name != 'JJP_BOARD_COUNT'}
    out['JJP_BOARD_COUNT'] = names.index('JJP_BOARD_COUNT')
    missing = [k for k in want if k not in out]
    if missing:
        raise RuntimeError(f'jjpshm.h missing {missing}')
    return out


L = shm_layout()
MATRIX_FIRST_BYTE = L['JJP_MATRIX_FIRST_BYTE']
MATRIX_BYTES = L['JJP_MATRIX_BYTES']
MATRIX_SWITCHES = L['JJP_MATRIX_SWITCHES']
FRAME_LEN = L['JJP_FRAME_LEN']
DIRECT_FIRST_BYTE = L['JJP_DIRECT_FIRST_BYTE']
DIRECT_BYTES = L['JJP_DIRECT_BYTES']
DIRECT_IDLE = L['JJP_DIRECT_IDLE']
BOARD_COUNT = L['JJP_BOARD_COUNT']
BOARDS = L['boards']
BOARD_LED = BOARDS['JJP_BOARD_LED']
BOARD_IO = BOARDS['JJP_BOARD_IO']

# LED-bearing boards: everything that is not a switch INPUT (IO, CAB).
LED_BOARDS = [i for name, i in sorted(BOARDS.items(), key=lambda kv: kv[1])
              if name not in ('JJP_BOARD_IO', 'JJP_BOARD_CAB')]

# struct jjp_shm, in order.  Must match jjpshm.h.
OFF_MAGIC = 0
OFF_VERSION = 4
OFF_GAME_PID = 8
OFF_IN_FRAME = 12
OFF_OUT = OFF_IN_FRAME + FRAME_LEN
OFF_OUT_CHANGES = OFF_OUT + BOARD_COUNT * FRAME_LEN
OFF_OUT_RISE = OFF_OUT_CHANGES + BOARD_COUNT * 4
OFF_READ_COUNT = OFF_OUT_RISE + BOARD_COUNT * FRAME_LEN * 8
OFF_WRITE_COUNT = OFF_READ_COUNT + 4
SHM_SIZE = OFF_WRITE_COUNT + 4


def direct_byte(fb):
    """Is this frame byte in the ACTIVE-LOW direct/cabinet region?"""
    return DIRECT_FIRST_BYTE <= fb < DIRECT_FIRST_BYTE + DIRECT_BYTES


def idle_frame():
    """The 64 bytes of a machine at rest - see jjpshm.h on why not zeroes."""
    return bytes(DIRECT_IDLE if direct_byte(i) else 0 for i in range(FRAME_LEN))


class SwitchShm:
    """The shared block.  Create it if the daemon has not yet."""

    # (frame_byte, bit_mask) pairs that are INVERTED optos - the game reads them
    # the other way up (a present ball breaks the beam and reads OPEN; nothing
    # there reads CLOSED).  A CLASS default so bare scripts and test doubles that
    # skip __init__ still have it; the UI replaces it (jjpsw MatrixUI.__init__)
    # with this title's set from the device dump (swdump's 'inverted' flag,
    # Switch off24 bit 0x2).  set/get_switch below speak in ACTIVE terms
    # ("closed" = contact made / ball present) and this set is the one place that
    # flips the electrical bit for an inverted opto - the whole reason a full
    # trough used to read empty and the game never started.
    inverted = frozenset()

    def __init__(self, name=DEFAULT_SHM):
        self.path = '/dev/shm' + name
        if not os.path.exists(self.path):
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
            os.ftruncate(fd, SHM_SIZE)
        else:
            fd = os.open(self.path, os.O_RDWR)
            if os.fstat(fd).st_size < SHM_SIZE:
                os.ftruncate(fd, SHM_SIZE)
        self.map = mmap.mmap(fd, SHM_SIZE)
        os.close(fd)

    def set_switch(self, fb, mask, closed):
        """Drive one switch by its absolute frame byte and bit MASK.

        POLARITY IS PER REGION and this is the one place that knows it: the
        direct/cabinet bytes are active LOW (a closed contact CLEARS its bit),
        the matrix and mech bytes active HIGH.  Measured against the game's own
        Switch objects - all 296 of them agreed, split exactly on the region
        boundary; see jjpshm.h.  Callers everywhere else say "closed" and mean
        ACTIVE (contact made / ball present) - for an INVERTED opto that maps to
        the electrical bit being OPEN, which is the whole reason a full trough
        used to read empty.
        """
        if not (0 <= fb < FRAME_LEN) or not mask:
            return
        eclosed = closed != ((fb, mask) in self.inverted)   # electrical state
        byte = OFF_IN_FRAME + fb
        cur = self.map[byte]
        high = eclosed != direct_byte(fb)          # active low inverts it
        self.map[byte] = (cur | mask) if high else (cur & ~mask)

    def get_switch(self, fb, mask):
        if not (0 <= fb < FRAME_LEN) or not mask:
            return False
        high = bool(self.map[OFF_IN_FRAME + fb] & mask)
        eclosed = high != direct_byte(fb)
        return eclosed != ((fb, mask) in self.inverted)     # ACTIVE / present

    def idle(self):
        """Every switch inactive - which is not an all-zero frame (see jjpshm.h),
        and for an inverted opto is the electrical bit CLOSED, not open."""
        frame = idle_frame()
        for i in range(FRAME_LEN):
            self.map[OFF_IN_FRAME + i] = frame[i]
        # idle_frame() leaves the matrix electrically OPEN, which for an inverted
        # opto reads as PRESENT (phantom ball / stuck jam).  Set them inactive.
        for fb, mask in self.inverted:
            self.set_switch(fb, mask, False)

    def out_rise(self, board, fb, bitno):
        """The shim's rising-edge count for one OUT bit (wraps at 256).

        Coils are 32 ms pulses; any poll rate would miss them as levels, so the
        only honest question is "different from last time?".
        """
        if not (0 <= board < BOARD_COUNT) or not (0 <= fb < FRAME_LEN):
            return 0
        return self.map[OFF_OUT_RISE + (board * FRAME_LEN + fb) * 8 + bitno]

    def counters(self):
        rd = int.from_bytes(self.map[OFF_READ_COUNT:OFF_READ_COUNT + 4], 'little')
        wr = int.from_bytes(self.map[OFF_WRITE_COUNT:OFF_WRITE_COUNT + 4], 'little')
        pid = int.from_bytes(self.map[OFF_GAME_PID:OFF_GAME_PID + 4], 'little')
        return rd, wr, pid

    def out_frame(self, board):
        o = OFF_OUT + board * FRAME_LEN
        return self.map[o:o + FRAME_LEN]

    def board_writes(self, board):
        o = OFF_OUT_CHANGES + board * 4
        return int.from_bytes(self.map[o:o + 4], 'little')

    def led_buffer(self):
        """The LED-board frames that the game has actually written, laid end to
        end - one flat, live byte space for the (provisional) RGB lookup.

        Only WRITTEN boards are included, so the buffer is real traffic rather
        than a wall of zeros: reading every LED_BOARD unconditionally (an
        earlier bug) mapped almost every lamp into an all-zero board and made
        the panel look dead even while the LED board churned.
        """
        return b''.join(bytes(self.out_frame(b))
                        for b in LED_BOARDS if self.board_writes(b))

    def led_write_total(self):
        return sum(self.board_writes(b) for b in LED_BOARDS)


# --------------------------------------------------------------------------
# Switch model
# --------------------------------------------------------------------------

_BARE = re.compile(r'^switch_\d+$')
CAT_CABINET = 'Cabinet / direct'
CAT_PLAYFIELD = 'Playfield matrix'
CAT_MECH = 'Steppers / topper'
CAT_ORDER = (CAT_CABINET, CAT_PLAYFIELD, CAT_MECH)


#: What the game calls a switch address it has nothing wired to.  Blank counts
#: as the same thing: an address with no name is one nobody named.
UNUSED_NAMES = ('', 'not used')


def in_use(s):
    """Does this title actually use this switch?

    Worth filtering on rather than showing greyed out: Wonka names 69 of its 296
    switch addresses, so the unused ones outnumber the real ones seven to one
    and a full list is mostly blanks.  The addresses still exist and can still
    be driven - they are simply not worth a row.
    """
    return (s.get('name') or '').strip().lower() not in UNUSED_NAMES


def drawable_coils(coils):
    """The coils that can honestly be drawn on the playfield.

    Three separate reasons a coil is left off, and the middle one is the one
    that bites:

    * no position - real, but there is nowhere to put it (the knocker, the
      coin meter);
    * frame byte 255 - the game's UNMAPPED SENTINEL, the same one the switch
      table uses for ``dswitch_null``.  Coils land on it too: Wonka parks its
      three elevator coils there, all sharing the one address, and swdump's own
      ``coil_addressing.problems`` reports them.  They DO carry positions, so
      nothing else would exclude them - and because ``out_rise`` reads 0 for an
      out-of-frame byte they would draw as markers that can never flash.  That
      is worse than leaving them out: a coil that never lights reads as a coil
      the game is not driving;
    * no frame address at all.
    """
    out = []
    for c in coils or []:
        fb, mask = c.get('frame_byte'), c.get('frame_bit')
        if fb is None or not mask or fb >= FRAME_LEN:
            continue
        if c.get('x') is None or c.get('y') is None:
            continue
        out.append(c)
    return out


def _descriptive(s):
    """A named switch (switch_trough_5) beats the bare alias (switch_071)."""
    return not _BARE.match(s.get('symbol', '') or '')


def _category(fb):
    if fb < MATRIX_FIRST_BYTE:
        return CAT_CABINET
    if fb < MATRIX_FIRST_BYTE + MATRIX_BYTES:
        return CAT_PLAYFIELD
    return CAT_MECH


def _matrix_num(fb, mask):
    """The 1..128 playfield switch number, or None off the matrix."""
    if MATRIX_FIRST_BYTE <= fb < MATRIX_FIRST_BYTE + MATRIX_BYTES:
        return (fb - MATRIX_FIRST_BYTE) * 8 + mask.bit_length()
    return None


def _addr_str(fb, mask):
    return f'{fb}.{mask.bit_length() - 1}'


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

BG = '#15171c'
FG = '#e8e8ea'
PANEL = '#1b1e25'
DIM = '#6b7280'
MARK_OFF = '#5aa9e6'
MARK_ON = '#41d67c'
ROW_CLOSED = '#1f6f42'
ROW_CLOSED_FG = '#eafff0'
LED_DARK = '#242833'

#: Coils: amber, and BRIGHT for the moment one fires.
COIL_OFF = '#9a6b1f'
COIL_FIRED = '#ffd479'
#: How long a fired coil stays lit.  A coil pulse is ~32 ms - far shorter than
#: the 100 ms tick - so what is drawn is deliberately a decay, not the live
#: level: at the true duration a fire would land between two frames and never
#: be seen at all.
COIL_FLASH_TICKS = 4

#: An unlit lamp is still drawn, faintly, so the layout is visible when the game
#: is not running.  Any higher and a dark playfield looks lit; any lower and the
#: lamps vanish.
LAMP_FLOOR_ALPHA = 0.16

#: Canvas tooltip.
TIP_BG = '#0d1017'
TIP_EDGE = '#3d4658'

#: Buttons.  Explicitly coloured rather than left to the platform default: a
#: default Tk button is light grey, which on this dark panel reads as a disabled
#: block of nothing rather than as the control it is.
#:
#: SLATE BLUE, and not green, because every other colour here already means
#: something: green is a CLOSED switch (ROW_CLOSED, MARK_ON), pale blue is an
#: open switch marker and amber is a coil.  A green button sits directly under
#: the green trough rows and reads as another piece of state rather than as
#: something to press.
BTN_BG = '#33507a'
BTN_FG = '#eaf2ff'
BTN_ACTIVE = '#456ba1'

#: The canvas background, and what a lamp blends against when there is no photo
#: to sample (no Pillow, or a title that ships none).
PF_BG = '#0b0c10'


#: One LED channel at full.  MEASURED, not assumed: over 15,393 samples of live
#: traffic the payload runs 0x00..0x80, and 2.5% of bytes sit above 0x3f.  The
#: old code scaled by 4 on a 6-bit (0x3f) assumption, which pinned everything
#: from 0x40 up to 255 - flattening exactly the half of the range a fade climbs
#: through, so lamps appeared to snap between colours instead of crossing.
LED_FULL = 0x80

#: How often the LED pages are RE-READ, which is not the same as how often they
#: are redrawn.  The game rewrites the LED frame ~2,139 times a second, cycling
#: 11 pages, and the shim keeps only the LATEST frame - so a reader sees one
#: page per look.  At the 100 ms repaint tick that is 6 pages a second, i.e.
#: each lamp refreshed about once every 1.8 s, which turns every fade into a
#: jump between two samples taken a second and a half apart.  Polling at 100 Hz
#: refreshes a given page roughly every 110 ms, which is fast enough to see one.
#: (The complete fix is for the shim to keep a buffer PER PAGE instead of one
#: frame; that is a C change and a rebuild, and cannot be done while a game is
#: running.)
LED_POLL_MS = 10


def led_level(v):
    """One raw LED byte -> an 8-bit channel."""
    return 255 if v >= LED_FULL else (v * 255) // LED_FULL


def _hex_rgb(h):
    """'#rrggbb' -> (r, g, b)."""
    h = h.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def blend(fg, bg, alpha):
    """Composite ``fg`` over ``bg`` at ``alpha``, as '#rrggbb'.

    Tk canvas items have no alpha channel, so translucency has to be resolved to
    a solid colour before it is drawn.  Doing it here - against the photograph's
    own pixels - is what lets a dim lamp read as dim rather than as dark.
    """
    a = 0.0 if alpha < 0 else (1.0 if alpha > 1 else alpha)
    return '#%02x%02x%02x' % tuple(
        max(0, min(255, int(round(f * a + b * (1.0 - a)))))
        for f, b in zip(fg, bg))

# Keyboard shortcuts.  (keysyms, label, symbol-patterns).  Resolved per title by
# matching the patterns against each switch's symbol - exact symbol first, then
# startswith, then substring.  The DIRECT switches (start, flippers, coins) live
# below the matrix, so these must be resolved against the whole switch set.
KEYMAP = [
    (('1',),                 'Start',      ('dswitch_start', 'start')),
    (('5',),                 'Coin',       ('dswitch_coin_1', 'dswitch_coin', 'coin')),
    (('Left', 'a'),          'L Flipper',  ('dswitch_l_flipper_lo', 'dswitch_l_flipper',
                                            'l_flipper', 'flipper_left')),
    (('Right', 'apostrophe'), 'R Flipper', ('dswitch_r_flipper_lo', 'dswitch_r_flipper',
                                            'r_flipper', 'flipper_right')),
    (('Return', 'KP_Enter'), 'Menu Enter', ('dswitch_enter',)),
    (('Up', 'equal'),        'Menu +',     ('dswitch_plus',)),
    (('Down', 'minus'),      'Menu -',     ('dswitch_minus',)),
    (('BackSpace', 'Escape'), 'Menu Back', ('dswitch_cancel',)),
]

#: Ball-path actions.  These are NOT switch pulses - a shooter lane you pulse
#: is a ball that appears and vanishes.  They go through the feeder, which knows
#: whether there is a ball there to launch and where a drained one comes home.
BALL_KEYS = [
    (('space',), 'Plunge', 'plunge'),
    (('d', 'D'), 'Drain',  'drain'),
]

_KEY_PRETTY = {'space': 'Space', 'Return': 'Enter', 'KP_Enter': 'Enter',
               'apostrophe': "'", 'Left': '←', 'Right': '→', 'Up': '↑',
               'Down': '↓', 'equal': '=', 'minus': '-', 'BackSpace': 'Bksp',
               'Escape': 'Esc'}


class MatrixUI:
    def __init__(self, root, devices, shm, pf_png=None, pulse_ms=120,
                 geom_file=DEFAULT_GEOM, ball_opts=None):
        self.root = root
        self.shm = shm
        self.pulse_ms = pulse_ms
        self.geom_file = geom_file
        self.ball_opts = dict(ball_opts or {})
        self.switches = {}          # (fb, mask) -> switch record
        self.latched = set()        # keys currently latched
        self.lamps = []
        self.coils = []             # placed coils, drawn on the playfield
        self.calib = devices.get('calibration', {})
        self._led_pages = {}        # (board, page_id) -> 63-byte payload
        self._led_buf = b''         # accumulated LED byte space (all pages)
        self._ball_lines = []       # newest feeder messages, for the panel
        self.ball_note = None
        self.feeder = None
        self.door = None

        # One record per physical switch, keyed by frame address (the physical
        # identity).  Byte 255 is a sentinel the game leaves unmapped; skip it.
        for s in devices.get('switches', []):
            fb, mask = s.get('frame_byte'), s.get('frame_bit')
            if fb is None or not mask or fb >= FRAME_LEN:
                continue
            key = (fb, mask)
            prev = self.switches.get(key)
            score = (s.get('x') is not None, _descriptive(s))
            if prev is None or score > (prev.get('x') is not None,
                                        _descriptive(prev)):
                self.switches[key] = s

        # Tell the shared block which switches are inverted optos, so every
        # set/get from here on (the feeder included) speaks in ball-present
        # terms and the electrical flip happens in one place.  MATRIX optos
        # only: the coin door / ticket notch carry the same flag but are
        # direct-region cabinet switches whose existing polarity already works
        # (flipping the door would drop the game onto its service screen).
        shm.inverted = {key for key, s in self.switches.items()
                        if s.get('inverted') and not direct_byte(key[0])}

        cx = self.calib.get('x') if self.calib.get('ok') else None
        cy = self.calib.get('y') if self.calib.get('ok') else None
        for l in devices.get('lamps', []):
            if not l.get('placed') or not cx or not cy:
                continue
            l = dict(l)
            l['px'] = int(round(cx['scale'] * l['x_in'] + cx['offset']))
            l['py'] = int(round(cy['scale'] * l['y_in'] + cy['offset']))
            self.lamps.append(l)

        # Coils.  Already in playfield-image pixels (like switches, and unlike
        # lamps, which are inches and need the calibration above), and addressed
        # by the same (frame_byte, bit MASK) pair - so jjpball's rising-edge
        # read works for these markers unchanged.  See drawable_coils() for
        # which ones are left off, and why.
        self.coils = drawable_coils(devices.get('coils'))

        root.title('JJP switch matrix')
        root.configure(bg=BG)
        self._restore_geometry()

        self._style_treeview()

        top = tk.Frame(root, bg=BG)
        top.pack(fill='x', padx=10, pady=(10, 4))
        self.status = tk.Label(top, text='', bg=BG, fg=FG, anchor='w',
                               font=('Consolas', 10))
        self.status.pack(side='left', fill='x', expand=True)
        tk.Button(top, text='All open', command=self.all_open).pack(side='right')

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=10, pady=6)

        self._build_playfield(body, pf_png)
        self._build_right(body, devices)

        # The shortcuts still exist and still work; what went away is the panel
        # that listed them.  Each one is written into its own switch's row
        # (_annotate_tree_keys) and onto the ball buttons, so the pairing is
        # shown where the thing it acts on already is.
        self.keybindings = self._resolve_keymap()
        self._annotate_tree_keys()
        self._bind_keys()

        self._start_balls(devices)

        # Geometry is saved shortly after any resize/move (survives a SIGKILL'd
        # teardown, like the Stern rig's window recorder), and on close.
        self._geom_job = None
        root.bind('<Configure>', self._on_root_configure)

        # Two loops, deliberately at different rates: gather the LED pages fast
        # enough to catch a fade, repaint at a rate the eye needs.
        self._led_poll()
        self.tick()

    def _start_balls(self, devices):
        """Bring the machine up at rest, and start answering its coils.

        Three things, in order, because each depends on the one before:

          * the whole IN frame to IDLE.  A block left over from a previous run
            (or created by a shim before any UI existed) can hold anything, and
            an all-zero frame is a machine with every cabinet button jammed;
          * the coin door SHUT.  It is a switch like any other and its resting
            state is closed - an open door puts the game on its service screen
            and it will not start a ball;
          * a full trough, and a feeder watching the eject coil.  The seat alone
            clears BALL TROUGH ERROR; the feeder is what makes Start go
            anywhere, because the game ejects and then waits for the trough to
            CHANGE, which a static fill can never do.
        """
        self.shm.idle()
        self.latched.clear()

        self.door = self._find_switch(('dswitch_coin_door_open', 'coin_door'))
        if self.door is not None:
            self.shm.set_switch(self.door[0], self.door[1], True)
            self.latched.add(self.door)

        self.feeder = jjpball.Feeder(
            self.shm, self.switches, devices.get('coils') or [],
            after=self.root.after, log=self._ball_log, now=time.monotonic,
            board=BOARD_IO, **self.ball_opts)
        for key in self.feeder.seat_trough():
            self.latched.add(key)
        for line in self.feeder.describe():
            self._ball_log(line)
        self._ball_log(self.feeder.settings())

    def _find_switch(self, patterns):
        recs = list(self.switches.items())
        for pat in patterns:
            for test in (lambda s: s == pat, lambda s: s.startswith(pat),
                         lambda s: pat in s):
                for key, rec in recs:
                    if test((rec.get('symbol') or '').lower()):
                        return key
        return None

    def _ball_log(self, msg):
        """One line to the run log, and the newest to the panel."""
        sys.stdout.write('[ball] %s\n' % msg)
        sys.stdout.flush()
        self._ball_lines.append(msg)
        del self._ball_lines[:-3]
        if getattr(self, 'ball_note', None) is not None:
            self.ball_note.config(text='\n'.join(self._ball_lines))

    # ---------------------------------------------------------------- style
    def _style_treeview(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')     # clam actually honours these colours
        except tk.TclError:
            pass
        style.configure('Sw.Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=FG, rowheight=21, borderwidth=0)
        style.map('Sw.Treeview', background=[('selected', '#2d4a63')],
                  foreground=[('selected', FG)])
        style.configure('Sw.Treeview.Heading', background='#20242c',
                        foreground=FG, relief='flat')

    # ---------------------------------------------------------------- playfield
    def _build_playfield(self, body, pf_png):
        self._raw = None
        self.pf_img = None
        self.img_w, self.img_h = 385, 768
        if pf_png and os.path.exists(pf_png):
            if _HAVE_PIL:
                try:
                    self._raw = Image.open(pf_png).convert('RGB')
                    self.img_w, self.img_h = self._raw.size
                except Exception:               # noqa: BLE001
                    self._raw = None
            if self._raw is None:
                try:
                    self.pf_img = tk.PhotoImage(file=pf_png)
                    self.img_w = self.pf_img.width()
                    self.img_h = self.pf_img.height()
                except tk.TclError:
                    self.pf_img = None

        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='both', expand=True)
        self.pf = tk.Canvas(left, width=self.img_w, height=self.img_h,
                            bg='#0b0c10', highlightthickness=0)
        self.pf.pack(fill='both', expand=True)

        self.scale = 1.0
        self.off_x = 0.0
        self.off_y = 0.0
        self._resize_job = None
        self._tip = None            # (rect, label) canvas items, made on demand
        self._bg_id = self.pf.create_image(0, 0, anchor='nw')
        self._center_msg = None
        self._corner_msg = None
        if self._raw is None and self.pf_img is None:
            self._center_msg = self.pf.create_text(
                0, 0, fill='#777', justify='center',
                text='no playfield image\n(pass --pf)')
        elif self._raw is None and self.pf_img is not None:
            self.pf.itemconfig(self._bg_id, image=self.pf_img)
            self._corner_msg = self.pf.create_text(
                0, 0, anchor='nw', fill='#556', font=('Segoe UI', 8),
                text='install python3-pil.imagetk to scale the playfield')

        # What each lamp sits ON.  Sampled once, from the photo's own pixels, so
        # brightness can be composited against it every tick without re-reading
        # the image - the positions never move in IMAGE space, only on screen.
        self._lamp_bg = [self._sample_bg(l['px'], l['py']) for l in self.lamps]
        self._lamp_drawn = {}       # i -> last colour drawn (skip no-op redraws)

        # Lamp markers (drawn first, so a switch marker is never hidden).
        self.lamp_marks = {}
        for i, l in enumerate(self.lamps):
            x, y = l['px'], l['py']
            oid = self.pf.create_rectangle(x - 4, y - 4, x + 4, y + 4,
                                           fill=LED_DARK, outline='')
            self.lamp_marks[i] = (oid, x, y)
            self._bind_tip(oid, lambda i=i: self._lamp_tip(i))

        # Coil markers - diamonds, so they read as a third kind of thing at a
        # glance rather than as another switch.
        self.coil_marks = {}
        self._coil_rise = {}        # index -> last rising-edge byte SAMPLED
        self._coil_fires = {}       # index -> edges counted since we opened
        self._coil_flash = {}       # index -> ticks left lit
        self._coil_drawn = {}       # index -> last colour drawn
        for i, c in enumerate(self.coils):
            x, y = c['x'], c['y']
            oid = self.pf.create_polygon(x, y - 6, x + 6, y, x, y + 6, x - 6, y,
                                         fill=COIL_OFF, outline=PF_BG, width=1)
            self.coil_marks[i] = (oid, x, y)
            self._bind_tip(oid, lambda i=i: self._coil_tip(i))

        # Switch markers, keyed by frame address.
        self.markers = {}
        for key, s in self.switches.items():
            if s.get('x') is None:
                continue
            x, y = s['x'], s['y']
            oid = self.pf.create_oval(x - 7, y - 7, x + 7, y + 7,
                                      fill=MARK_OFF, outline=PF_BG, width=2)
            self.markers[key] = (oid, x, y)
            self.pf.tag_bind(oid, '<Button-1>', lambda e, k=key: self.pulse(k))
            self.pf.tag_bind(oid, '<Button-3>', lambda e, k=key: self.toggle(k))
            self._bind_tip(oid, lambda k=key: self._switch_tip(k))

        self.pf.bind('<Configure>', self._on_resize)
        self.root.after(60, self._fit)

    def _sample_bg(self, x, y):
        """The photograph's own pixel under a marker, for compositing.

        Clamped rather than skipped: a lamp can legitimately calibrate to just
        outside the frame (the backpanel flashers sit above the photo's top
        edge), and those still have to draw as something.
        """
        if self._raw is None:
            return _hex_rgb(PF_BG)
        px = max(0, min(self.img_w - 1, int(x)))
        py = max(0, min(self.img_h - 1, int(y)))
        try:
            return tuple(self._raw.getpixel((px, py)))[:3]
        except Exception:                                   # noqa: BLE001
            return _hex_rgb(PF_BG)

    def _bind_tip(self, oid, text_fn):
        """Raise this item's tooltip under the pointer while it is hovered.

        ``text_fn`` is called on every move rather than once on enter, so a
        tooltip left up over a live lamp keeps showing that lamp's CURRENT
        colour instead of the colour it had when the pointer arrived.
        """
        self.pf.tag_bind(oid, '<Enter>',
                         lambda e, f=text_fn: self._show_tip(e.x, e.y, f()))
        self.pf.tag_bind(oid, '<Motion>',
                         lambda e, f=text_fn: self._show_tip(e.x, e.y, f()))
        self.pf.tag_bind(oid, '<Leave>', lambda e: self._hide_tip())

    def _on_resize(self, _e=None):
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(40, self._fit)

    def _fit(self):
        self._resize_job = None
        cw, ch = self.pf.winfo_width(), self.pf.winfo_height()
        if cw <= 1 or ch <= 1:
            self.root.after(60, self._fit)
            return
        self.scale = min(cw / self.img_w, ch / self.img_h) if self._raw else 1.0
        nw = max(1, int(self.img_w * self.scale))
        nh = max(1, int(self.img_h * self.scale))
        self.off_x = (cw - nw) / 2
        self.off_y = (ch - nh) / 2
        if self._raw is not None:
            self.pf_img = ImageTk.PhotoImage(self._raw.resize((nw, nh), _RESAMPLE))
            self.pf.itemconfig(self._bg_id, image=self.pf_img)
        self.pf.coords(self._bg_id, self.off_x, self.off_y)
        self._reposition_markers()

    def _cx(self, x):
        return self.off_x + x * self.scale

    def _cy(self, y):
        return self.off_y + y * self.scale

    def _reposition_markers(self):
        lr = max(2, 4 * self.scale)
        for oid, x, y in self.lamp_marks.values():
            self.pf.coords(oid, self._cx(x) - lr, self._cy(y) - lr,
                           self._cx(x) + lr, self._cy(y) + lr)
        cr = max(3, 6 * self.scale)
        for oid, x, y in self.coil_marks.values():
            px, py = self._cx(x), self._cy(y)
            self.pf.coords(oid, px, py - cr, px + cr, py, px, py + cr,
                           px - cr, py)
        sr = max(3, 7 * self.scale)
        for oid, x, y in self.markers.values():
            self.pf.coords(oid, self._cx(x) - sr, self._cy(y) - sr,
                           self._cx(x) + sr, self._cy(y) + sr)
        # A tooltip pinned to a marker that has just moved would be pointing at
        # nothing.
        self._hide_tip()
        if self._center_msg is not None:
            self.pf.coords(self._center_msg,
                           self.off_x + self.img_w * self.scale / 2,
                           self.off_y + self.img_h * self.scale / 2)
        if self._corner_msg is not None:
            self.pf.coords(self._corner_msg, self.off_x + 4, self.off_y + 4)

    # ---------------------------------------------------------------- right col
    def _build_right(self, body, devices):
        right = tk.Frame(body, bg=BG, width=RIGHT_W)
        right.pack(side='left', fill='y', padx=(12, 0))
        # Stop the children sizing the parent.  Without this the column is as
        # wide as its widest child WANTS to be, and three of those children
        # rewrite their text ten times a second - so the playfield next door
        # kept being handed a new width and rescaling itself.  See RIGHT_W.
        right.pack_propagate(False)
        self._right = right

        tk.Label(right, text='Switches  (click = pulse, right-click = latch)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w')

        tw = tk.Frame(right, bg=BG)
        tw.pack(fill='both', expand=True, pady=(2, 4))
        # Built from TREE_COLS so the columns and the fixed width of the column
        # they live in cannot drift apart - RIGHT_W is the sum of these.  Only
        # the name column stretches; the three narrow ones are sized to their
        # content and stay put.
        self.tree = ttk.Treeview(tw, columns=tuple(c[0] for c in TREE_COLS[1:]),
                                 style='Sw.Treeview', height=16,
                                 selectmode='browse')
        for cid, heading, width, anchor in TREE_COLS:
            self.tree.heading(cid, text=heading)
            self.tree.column(cid, width=width, anchor=anchor,
                             stretch=(cid == '#0'))
        vs = ttk.Scrollbar(tw, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vs.pack(side='left', fill='y')
        # Rows are one colour.  They used to be dimmed when a switch had no
        # playfield position, which read as "disabled" and was never explained;
        # it was also redundant, because every such switch is a CABINET switch
        # and is already sitting under the Cabinet heading.
        self.tree.tag_configure('closed', background=ROW_CLOSED,
                                foreground=ROW_CLOSED_FG)
        self.tree.tag_configure('cat', background='#20242c', foreground='#9aa3b2')

        self.row_key = {}           # tree iid -> (fb, mask)
        self.key_row = {}           # (fb, mask) -> tree iid
        self._row_closed = {}       # iid -> last drawn closed state
        self._populate_tree()

        self.tree.bind('<Button-1>', self._tree_click)
        self.tree.bind('<Button-3>', self._tree_right)

        self._build_ball_panel(right)
        self._build_led_panel(right, devices)

    def _build_ball_panel(self, right):
        """Where the balls are, and the one thing nothing can observe.

        The Drain button is not a convenience: with no playfield physics a ball
        that leaves the shooter lane stays in play for ever, so without a way to
        say "it drained" a game can start but can never end its ball.
        """
        tk.Label(right, text='Balls', bg=BG, fg='#9aa3b2',
                 font=('Segoe UI', 9)).pack(anchor='w', pady=(8, 2))
        self.ball_state = tk.Label(right, text='', bg=BG, fg=FG, anchor='w',
                                   font=('Consolas', 10))
        self.ball_state.pack(anchor='w', fill='x')

        # THE BUTTONS GET THEIR OWN ROW.  They used to sit beside the status
        # line, which packed first with expand=True and so claimed the whole
        # width - Plunge was pushed off the end and left showing "ge (Sp".  It
        # was never going to fit either: the status line alone is ~300 px of the
        # column's 442, and the two buttons want ~200 more.  Sharing a row with a
        # label whose text the feeder rewrites is a fight the button loses.
        #
        # The shortcut stays written ON the button.  That is where the legend
        # panel that used to list these went: a key is worth knowing at the
        # moment you are looking for the thing it does.
        keys = {action: self._key_label(ks) for ks, _lbl, action in BALL_KEYS}
        row = tk.Frame(right, bg=BG)
        row.pack(anchor='w', fill='x', pady=(4, 6))
        for text, command in (
                ('Plunge  (%s)' % keys.get('plunge', ''), self._do_plunge),
                ('Drain  (%s)' % keys.get('drain', ''), self._do_drain)):
            b = tk.Button(row, text=text, command=command,
                          font=('Segoe UI', 9, 'bold'), pady=4,
                          bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACTIVE,
                          activeforeground=BTN_FG, relief='raised', bd=1,
                          highlightthickness=0)
            # Equal halves of the column: at this width nothing is clipped and
            # both are a big, obvious target.
            b.pack(side='left', fill='x', expand=True,
                   padx=(0, 6) if command is self._do_plunge else 0)
        # Fixed height AND a wrap width: this shows the newest three feeder
        # messages, which vary in length, and both dimensions have to be pinned
        # or the panel below it shuffles every time one arrives.
        self.ball_note = tk.Label(right, text='', bg=BG, fg='#8a93a2',
                                  anchor='w', justify='left', height=3,
                                  wraplength=RIGHT_W, font=('Consolas', 8))
        self.ball_note.pack(anchor='w', fill='x')

    def _do_drain(self):
        if self.feeder is not None:
            self.feeder.drain()

    def _do_plunge(self):
        if self.feeder is not None:
            self.feeder.plunge()

    def _populate_tree(self):
        # Categories are created only if something lands in them, so a title
        # that uses no stepper switches does not get an empty heading.
        cats = {}

        def category(name):
            if name not in cats:
                cats[name] = self.tree.insert('', 'end', text=name, open=True,
                                              tags=('cat',))
            return cats[name]

        # Stable, readable order: by frame address within each category, and
        # categories in their own order rather than first-seen.
        for cat_name in CAT_ORDER:
            for key in sorted(self.switches):
                fb, mask = key
                if _category(fb) != cat_name:
                    continue
                s = self.switches[key]
                if not in_use(s):
                    continue
                num = _matrix_num(fb, mask)
                name = s.get('name') or s.get('symbol') or ''
                iid = self.tree.insert(
                    category(cat_name), 'end', text='  ' + name,
                    values=('' if num is None else num, '',
                            _addr_str(fb, mask)))
                self.row_key[iid] = key
                self.key_row[key] = iid
                self._row_closed[iid] = False

    def _tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.row_key:
            self.pulse(self.row_key[iid])

    def _tree_right(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.row_key:
            self.toggle(self.row_key[iid])

    # ---------------------------------------------------------------- LEDs
    def _build_led_panel(self, right, devices):
        """What the LEDs are doing - in WORDS.

        There used to be a grid here, one coloured cell per placed lamp.  It
        was the same information the playfield already shows, minus the only
        part that makes it meaningful: on the photo a lamp is AT the insert it
        lights, whereas in a 24-wide grid it is at an arbitrary square.  So the
        grid is gone and the playfield is the LED display.
        """
        placed, total = len(self.lamps), len(devices.get('lamps', []))
        tk.Label(right, text=f'LEDs  -  {placed} of {total} on the playfield'
                             f'  (RGB mapping provisional)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w',
                                                                 pady=(8, 2))
        self.led_note = tk.Label(right, text='', bg=BG, fg='#c88', anchor='w',
                                 justify='left', wraplength=RIGHT_W,
                                 font=('Segoe UI', 8))
        self.led_note.pack(anchor='w')

    def _accumulate_leds(self):
        """Cache each LED page as it is seen, into one full LED byte space.

        Decoded from a live capture (~650 writes/s): the LED board writes 64-byte
        PAGES, byte 63 is the page id (0x80|page, ~11 pages) and bytes 0..62 the
        payload of 6-bit brightness values (0x3f = full).  The shim keeps only
        the LAST page, so the UI accumulates them - one page per poll - keyed by
        (board, page_id).  ~11 pages x 63 bytes is enough room for 216 RGB lamps.
        """
        for b in LED_BOARDS:
            if not self.shm.board_writes(b):
                continue
            frame = bytes(self.shm.out_frame(b))
            self._led_pages[(b, frame[FRAME_LEN - 1])] = frame[:FRAME_LEN - 1]
        self._led_buf = b''.join(self._led_pages[k]
                                 for k in sorted(self._led_pages))

    def led_rgb(self, i, buf):
        """(r, g, b) for lamp i from the accumulated LED byte space.

        THE FULL SCALE IS 0x80, NOT 0x3f.  This used to scale by 4, on the
        belief that the values were 6-bit.  Measured against 15,393 samples of
        live traffic they are not: the range runs to 0x80, and 2.5% of all bytes
        sit above 0x3f.  Scaling those by 4 pinned everything from 0x40 upward
        to 255, which is precisely where the bright half of a fade lives - so a
        lamp crossing 0x40 appeared to snap to full instead of climbing.

        The layout itself now has real evidence behind it.  Each lamp is three
        bytes at index*3 in the concatenated pages, and the three are R, G, B:
        during attract the general-illumination lamps read bright and warm
        (gi_left_1 -> 70 00 10), 154 of 164 placed lamps are non-zero, and each
        triplet's channels SUM to a quantised total (0x80, 0x40, 0x3f, 0x15) -
        i.e. the colour is a split of one intensity across three channels, which
        is what an RGB lamp driver looks like.

        What is still NOT verified is the page ORDER (pages are concatenated by
        id, which is an assumption) and therefore which lamp owns which triplet
        beyond the run of them being self-consistent.  Nailing that needs a
        correlation pass - light one lamp from the game's own test menu and
        watch which byte moves.  The switch matrix, by contrast, WAS derived and
        verified.
        """
        if not buf:
            return 0, 0, 0
        n = len(buf)
        base = (self.lamps[i]['index'] * 3) % n
        return (led_level(buf[base]),
                led_level(buf[(base + 1) % n]),
                led_level(buf[(base + 2) % n]))

    def _lamp_paint(self, i, buf):
        """The colour to actually DRAW for lamp i - brightness as opacity.

        Painting the raw value is what made brightness invisible: an insert at a
        fifth brightness is rgb (51, 0, 0), and a near-black square on a dark
        photograph looks exactly like an unlit one.  A real insert at a fifth
        brightness is not a darker red, it is a FAINTER one - the playfield art
        shows through it - so the honest rendering is the lamp's own colour at
        its own hue, composited over the photo at an alpha taken from its level.

        Hue is normalised to full before blending so that dimming changes only
        the opacity: without it a dim lamp loses its colour as well as its
        strength and every lamp converges on the same grey.
        """
        r, g, b = self.led_rgb(i, buf) if buf else (0, 0, 0)
        bg = self._lamp_bg[i]
        peak = max(r, g, b)
        if not peak:
            # Unlit, but still worth seeing: this is the layout when the game is
            # not running, and an invisible lamp cannot be hovered for its name.
            return blend(_hex_rgb(LED_DARK), bg, LAMP_FLOOR_ALPHA)
        k = 255.0 / peak
        hue = (r * k, g * k, b * k)
        level = peak / 255.0
        return blend(hue, bg, LAMP_FLOOR_ALPHA + (1.0 - LAMP_FLOOR_ALPHA) * level)

    # ---------------------------------------------------------------- keyboard
    def _resolve_keymap(self):
        recs = list(self.switches.items())

        def find(pat):
            # exact symbol, then startswith, then substring - most specific win.
            for want in (lambda sym: sym == pat,
                         lambda sym: sym.startswith(pat),
                         lambda sym: pat in sym):
                for key, s in recs:
                    if want((s.get('symbol') or '').lower()):
                        return key
            return None

        resolved = []
        for keysyms, label, patterns in KEYMAP:
            hit = None
            for pat in patterns:
                hit = find(pat.lower())
                if hit is not None:
                    break
            resolved.append((keysyms, label, hit))
        return resolved

    def _annotate_tree_keys(self):
        """Write each resolved shortcut into its switch's row (the Key column)."""
        for keysyms, _label, key in self.keybindings:
            if key is not None and key in self.key_row:
                self.tree.set(self.key_row[key], 'key', self._key_label(keysyms))

    def _bind_keys(self):
        for keysyms, _label, key in self.keybindings:
            if key is None:
                continue
            for ks in keysyms:
                self.root.bind(f'<KeyPress-{ks}>',
                               lambda e, k=key: self._key_pulse(k))
                self.root.bind(f'<Shift-KeyPress-{ks}>',
                               lambda e, k=key: self._key_latch(k))
        for keysyms, _label, action in BALL_KEYS:
            for ks in keysyms:
                self.root.bind(f'<KeyPress-{ks}>',
                               lambda e, a=action: self._key_ball(a))

    def _key_ball(self, action):
        if not self._typing() and self.feeder is not None:
            getattr(self.feeder, action)()

    def _typing(self):
        return isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry))

    def _key_pulse(self, key):
        if not self._typing():
            self.pulse(key)

    def _key_latch(self, key):
        if not self._typing():
            self.toggle(key)

    @staticmethod
    def _key_label(keysyms):
        names = []
        for k in keysyms:
            nm = _KEY_PRETTY.get(k, k)
            if nm not in names:
                names.append(nm)
        return '/'.join(names)

    # The keyboard legend and the "switch # / Pulse / Latch" entry used to live
    # here.  Both were second ways to say something the panel already said: the
    # legend repeated pairings that _annotate_tree_keys writes into each
    # switch's own row (and that the ball buttons now carry), and the entry
    # reached a switch by its matrix number when the table lists every switch
    # WITH its number and pulses it on click.  The bindings themselves are
    # untouched - see _bind_keys.

    # ---------------------------------------------------------------- tooltip
    def _show_tip(self, x, y, text):
        """Draw the tooltip at the pointer, kept inside the canvas.

        Two canvas items reused for the life of the window rather than created
        and deleted per hover: a Motion-driven tooltip would otherwise churn two
        items per mouse move.
        """
        if not text:
            return self._hide_tip()
        if self._tip is None:
            rect = self.pf.create_rectangle(0, 0, 0, 0, fill=TIP_BG,
                                            outline=TIP_EDGE, width=1)
            label = self.pf.create_text(0, 0, anchor='nw', fill=FG,
                                        justify='left', font=('Consolas', 9))
            self._tip = (rect, label)
        rect, label = self._tip
        self.pf.itemconfig(label, text=text, state='normal')
        self.pf.itemconfig(rect, state='normal')

        pad, gap = 5, 14
        self.pf.coords(label, 0, 0)
        box = self.pf.bbox(label)
        if not box:
            return
        w, h = box[2] - box[0], box[3] - box[1]
        tx = self._tip_axis(x, w + 2 * pad, self.pf.winfo_width(), gap)
        ty = self._tip_axis(y, h + 2 * pad, self.pf.winfo_height(), gap)
        self.pf.coords(label, tx + pad, ty + pad)
        self.pf.coords(rect, tx, ty, tx + w + 2 * pad, ty + h + 2 * pad)
        self.pf.tag_raise(rect)
        self.pf.tag_raise(label)

    @staticmethod
    def _tip_axis(pos, size, extent, gap):
        """Place one axis of the tooltip: past the pointer, else before it, else
        pinned inside the canvas.

        Flipping to the near side is only an improvement if the tooltip actually
        FITS there.  Flipping unconditionally is what pins a wide tooltip to 0
        no matter where the pointer is - which is what a narrow canvas (or one
        not yet mapped, whose width Tk reports as 1) does to it.
        """
        if pos + gap + size <= extent:
            return pos + gap
        before = pos - gap - size
        if before >= 0:
            return before
        return max(0, extent - size)

    def _hide_tip(self):
        if self._tip is not None:
            for oid in self._tip:
                self.pf.itemconfig(oid, state='hidden')

    def _lamp_tip(self, i):
        l = self.lamps[i]
        buf = self._led_buf
        r, g, b = self.led_rgb(i, buf) if buf else (0, 0, 0)
        pct = round(max(r, g, b) * 100 / 255)
        return (f"{l['name'] or l['symbol']}\n"
                f"LED {l['index']}   rgb {r},{g},{b}   {pct}%\n"
                f"{l['symbol']}")

    def _coil_tip(self, i):
        """One coil, and how often it has fired SINCE THIS WINDOW OPENED.

        Deliberately not the shim's own counter: that is a byte, it wraps at
        256, and it is already carrying whatever the game did before this
        window existed - so printing it would claim a total it cannot support
        and would eventually count backwards in front of the reader.
        """
        c = self.coils[i]
        fb, mask = c['frame_byte'], c['frame_bit']
        return (f"{c.get('name') or c.get('symbol')}\n"
                f"COIL   {c.get('pulse_ms', '?')} ms pulse   "
                f"{self._coil_fires.get(i, 0)} fired since opening\n"
                f"{c.get('symbol', '')}   frame {_addr_str(fb, mask)}")

    def _switch_tip(self, key):
        s = self.switches.get(key)
        if not s:
            return ''
        fb, mask = key
        num = _matrix_num(fb, mask)
        state = 'CLOSED' if self.shm.get_switch(fb, mask) else 'open'
        what = f'#{num}' if num else _category(fb)
        return (f"{s.get('name') or s.get('symbol') or ''}\n"
                f"SWITCH {what}   {state}"
                + ('   inverted opto' if s.get('inverted') else '') + "\n"
                f"{s.get('symbol', '')}   frame {_addr_str(fb, mask)}")

    # ---------------------------------------------------------------- input
    def pulse(self, key):
        fb, mask = key
        self.shm.set_switch(fb, mask, True)
        self.latched.discard(key)
        self.root.after(self.pulse_ms, lambda: self.shm.set_switch(fb, mask, False))

    def toggle(self, key):
        fb, mask = key
        now = not self.shm.get_switch(fb, mask)
        self.shm.set_switch(fb, mask, now)
        if now:
            self.latched.add(key)
        else:
            self.latched.discard(key)

    def all_open(self):
        """Everything open - then put the machine back at rest.

        "All open" on its own is not a state a machine is ever in: the coin door
        springs shut and the trough is full of balls.  Leaving it genuinely all
        open drops the game straight into BALL TROUGH ERROR, which reads as this
        button having broken something.
        """
        self.shm.idle()
        self.latched.clear()
        if self.door is not None:
            self.shm.set_switch(self.door[0], self.door[1], True)
            self.latched.add(self.door)
        if self.feeder is not None:
            for key in self.feeder.seat_trough():
                self.latched.add(key)

    def _led_poll(self):
        """Gather LED pages far faster than the panel repaints.

        Separate from ``tick`` on purpose.  Repainting 154 lamps ten times a
        second is plenty for the eye; READING them ten times a second is not,
        because each read yields only whichever one of the 11 pages the shim
        last caught.  Sampling and drawing are two different rates and pretending
        they are one is what made every fade look like a snap.
        """
        if self.shm.led_write_total():
            self._accumulate_leds()
        self.root.after(LED_POLL_MS, self._led_poll)

    def _tick_coils(self):
        """Light a coil marker when the game fires it, then fade it back.

        The counter is a byte in shared memory and WRAPS at 256, so the test is
        "different from last time", never "greater than".  First sight of a coil
        seeds the count without flashing - otherwise every coil the game has
        ever fired would appear to fire at once when this window opens.
        """
        for i, c in enumerate(self.coils):
            fb, mask = c['frame_byte'], c['frame_bit']
            now = self.shm.out_rise(BOARD_IO, fb, mask.bit_length() - 1)
            was = self._coil_rise.get(i)
            self._coil_rise[i] = now
            if was is not None and now != was:
                # Count the edges, do not just count this TICK.  The byte is a
                # wrapping counter, so the number of pulses since the last look
                # is the modular difference - a slingshot can fire several times
                # inside one 100 ms tick, and a flat +1 would quietly under-
                # report exactly the coils that are busiest.
                self._coil_fires[i] = (self._coil_fires.get(i, 0)
                                       + ((now - was) & 0xff))
                self._coil_flash[i] = COIL_FLASH_TICKS
            left = self._coil_flash.get(i, 0)
            if left:
                self._coil_flash[i] = left - 1
            want = COIL_FIRED if left else COIL_OFF
            if self._coil_drawn.get(i) != want:
                self._coil_drawn[i] = want
                self.pf.itemconfig(self.coil_marks[i][0], fill=want)

    def tick(self):
        # Switch markers + table rows (only retag rows whose state changed).
        for key, (oid, _x, _y) in self.markers.items():
            self.pf.itemconfig(oid, fill=MARK_ON if self.shm.get_switch(*key)
                               else MARK_OFF)
        for iid, key in self.row_key.items():
            closed = self.shm.get_switch(*key)
            if closed != self._row_closed[iid]:
                self._row_closed[iid] = closed
                self.tree.item(iid, tags=('closed',) if closed else ())

        # The pages are gathered by _led_poll at LED_POLL_MS, NOT here: reading
        # them once per repaint saw only ~6 of the 11 pages a second and turned
        # every fade into a jump.  This just draws whatever the fast loop has.
        led_writes = self.shm.led_write_total()
        buf = self._led_buf
        for i in self.lamp_marks:
            colour = self._lamp_paint(i, buf)
            # Only touch the canvas when the colour actually changed: at ten
            # ticks a second across every placed lamp (154 of Wonka's 216),
            # redrawing unchanged items is most of this loop's work and all of
            # it wasted.
            if self._lamp_drawn.get(i) != colour:
                self._lamp_drawn[i] = colour
                self.pf.itemconfig(self.lamp_marks[i][0], fill=colour)
        self.led_note.config(
            text='' if led_writes else
            'LED boards not written yet - the playfield shows LAYOUT ONLY.')

        # Coils.  A 32 ms pulse cannot be caught as a level by a 100 ms tick, so
        # the shim's rising-edge COUNT is what is read, and a change lights the
        # marker for a few ticks so the eye can catch it.
        self._tick_coils()

        # Answer the game's coils.  Polling here rather than on its own timer
        # keeps one view of the switches: the feeder and a human click are the
        # same hand, so they cannot disagree about where the balls are.
        if self.feeder is not None:
            self.feeder.poll()
            self.ball_state.config(text=self.feeder.status())
            # The feeder writes switches behind the UI's back (that is its job),
            # so a key it opened must stop counting as latched or the number on
            # the status line drifts away from the machine.
            self.latched = {k for k in self.latched if self.shm.get_switch(*k)}

        rd, wr, pid = self.shm.counters()
        live = 'reading' if rd else 'NOT reading (game has not opened the boards)'
        self.status.config(
            text=f'game pid {pid or "-"}   frames in {rd}  out {wr}   {live}'
                 f'   latched {len(self.latched)}   LED writes {led_writes}')
        self.root.after(100, self.tick)

    # ---------------------------------------------------------------- geometry
    def _restore_geometry(self):
        saved = None
        try:
            with open(self.geom_file) as f:
                g = json.load(f).get('geometry', '')
            if re.match(r'^\d+x\d+[+-]\d+[+-]\d+$', g or ''):
                saved = g
        except (OSError, ValueError):
            pass
        if saved:
            try:
                self.root.geometry(saved)
                return
            except tk.TclError:
                pass
        # First run (nothing remembered yet): open at a generous default rather
        # than the natural size, which is dominated by the playfield's narrow
        # native width and comes up too small to read the switch table beside
        # it.  Clamped to the screen so it fits a smaller monitor.
        self.root.geometry(self._default_geometry())

    def _default_geometry(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth() or 1920
        sh = self.root.winfo_screenheight() or 1080
        w = min(DEFAULT_W, max(900, sw - 80))
        h = min(DEFAULT_H, max(700, sh - 80))
        return f'{w}x{h}'

    def _on_root_configure(self, event):
        # Only the toplevel's own configure, and debounced: a drag fires many.
        if event.widget is not self.root:
            return
        if self._geom_job is not None:
            self.root.after_cancel(self._geom_job)
        self._geom_job = self.root.after(500, self.save_geometry)

    def save_geometry(self):
        self._geom_job = None
        try:
            with open(self.geom_file, 'w') as f:
                json.dump({'geometry': self.root.geometry()}, f)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description='JJP switch matrix')
    ap.add_argument('--devices', default='/var/tmp/jjp_devices.json',
                    help='JSON from swdump.py')
    ap.add_argument('--pf', default=None, help='playfield PNG (pf_image.png)')
    ap.add_argument('--shm', default=DEFAULT_SHM)
    ap.add_argument('--pulse-ms', type=int, default=120)
    ap.add_argument('--geom-file', default=DEFAULT_GEOM)
    ap.add_argument('--flight-ms', type=int, default=jjpball.FLIGHT_MS,
                    help='trough eject to shooter lane')
    ap.add_argument('--min-gap-ms', type=int, default=jjpball.MIN_GAP_MS,
                    help='two ejects closer than this are one')
    ap.add_argument('--auto-drain-s', type=float, default=jjpball.AUTO_DRAIN_S,
                    help='a ball nobody is playing comes home after this '
                         '(0 = only the Drain button)')
    args = ap.parse_args(argv)

    if not os.path.exists(args.devices):
        print(f'jjpsw: {args.devices} not found.  Run:\n'
              f'  python3 swdump.py --out {args.devices}\n'
              f'against a running game first.', file=sys.stderr)
        return 3

    devices = json.load(open(args.devices))
    shm = SwitchShm(args.shm)
    root = tk.Tk()
    root.minsize(900, 600)
    ui = MatrixUI(root, devices, shm, pf_png=args.pf, pulse_ms=args.pulse_ms,
                  geom_file=args.geom_file,
                  ball_opts={'flight_ms': args.flight_ms,
                             'min_gap_ms': args.min_gap_ms,
                             'auto_drain_s': args.auto_drain_s})

    # Close cleanly on BOTH the window's X button and a SIGTERM from the rig's
    # Stop.  A Tk window that is SIGKILL'd never releases its WSLg surface and
    # ghosts on the Windows desktop, so Stop must be able to make it close
    # ITSELF.  A Python signal handler does not run while Tcl is in mainloop, so
    # the handler only sets a flag and the always-scheduled tick acts on it.
    closing = {'now': False}

    def request_close(*_a):
        closing['now'] = True

    def watch_close():
        if closing['now']:
            ui.save_geometry()
            try:
                root.destroy()
            except tk.TclError:
                pass
            return
        root.after(50, watch_close)

    root.protocol('WM_DELETE_WINDOW', request_close)
    try:
        signal.signal(signal.SIGTERM, request_close)
        signal.signal(signal.SIGINT, request_close)
    except (ValueError, OSError):
        pass
    root.after(50, watch_close)

    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
