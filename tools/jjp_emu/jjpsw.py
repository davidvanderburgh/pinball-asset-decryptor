#!/usr/bin/env python3
"""Switch matrix for an emulated JJP game: a playfield view and a labelled list.

WHAT IT IS
----------
Two views of the same switches, side by side:

* the game's OWN playfield photograph (``graphics/Game Tests/pf_image.png``,
  decrypted out of its edata) with a marker on every switch that has a position
  - click a marker to close that switch.  The photo scales with the window and
  the markers ride on top of it, so the view keeps its aspect ratio at any size;
* a LABELLED switch table - every switch by name, grouped into Cabinet /
  Playfield / Mechanism, so you can see what each one is at a glance (this is
  the layout the Stern rig uses).  Click a row to pulse it, right-click to latch.

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
names, and shown in the Keyboard panel with the switch each one hit.  Keys work
while THIS window is focused (the game itself has no keyboard input - a real
cabinet has none either).

LEDS ARE RGB
------------
Playfield lamps render their colour (three bytes each).  The per-lamp byte
mapping is still PROVISIONAL - see ``MatrixUI.led_rgb``.
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

        self.keybindings = self._resolve_keymap()
        self._annotate_tree_keys()
        self._build_keyboard_legend(self._right)
        self._bind_keys()

        self._start_balls(devices)

        # Geometry is saved shortly after any resize/move (survives a SIGKILL'd
        # teardown, like the Stern rig's window recorder), and on close.
        self._geom_job = None
        root.bind('<Configure>', self._on_root_configure)

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

        # Lamp markers (drawn first, so a switch marker is never hidden).
        self.lamp_marks = {}
        for i, l in enumerate(self.lamps):
            x, y = l['px'], l['py']
            oid = self.pf.create_rectangle(x - 4, y - 4, x + 4, y + 4,
                                           fill=LED_DARK, outline='')
            self.lamp_marks[i] = (oid, x, y)
            self.pf.tag_bind(oid, '<Enter>', lambda e, k=i: self.hover_lamp(k))
            self.pf.tag_bind(oid, '<Leave>', lambda e: self.hover(None))

        # Switch markers, keyed by frame address.
        self.markers = {}
        for key, s in self.switches.items():
            if s.get('x') is None:
                continue
            x, y = s['x'], s['y']
            oid = self.pf.create_oval(x - 7, y - 7, x + 7, y + 7,
                                      fill=MARK_OFF, outline='#0b0c10', width=2)
            self.markers[key] = (oid, x, y)
            self.pf.tag_bind(oid, '<Button-1>', lambda e, k=key: self.pulse(k))
            self.pf.tag_bind(oid, '<Button-3>', lambda e, k=key: self.toggle(k))
            self.pf.tag_bind(oid, '<Enter>', lambda e, k=key: self.hover(k))
            self.pf.tag_bind(oid, '<Leave>', lambda e: self.hover(None))

        self.pf.bind('<Configure>', self._on_resize)
        self.root.after(60, self._fit)

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
        sr = max(3, 7 * self.scale)
        for oid, x, y in self.markers.values():
            self.pf.coords(oid, self._cx(x) - sr, self._cy(y) - sr,
                           self._cx(x) + sr, self._cy(y) + sr)
        if self._center_msg is not None:
            self.pf.coords(self._center_msg,
                           self.off_x + self.img_w * self.scale / 2,
                           self.off_y + self.img_h * self.scale / 2)
        if self._corner_msg is not None:
            self.pf.coords(self._corner_msg, self.off_x + 4, self.off_y + 4)

    # ---------------------------------------------------------------- right col
    def _build_right(self, body, devices):
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='y', padx=(12, 0))
        self._right = right

        tk.Label(right, text='Switches  (click = pulse, right-click = latch)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w')

        tw = tk.Frame(right, bg=BG)
        tw.pack(fill='both', expand=True, pady=(2, 4))
        self.tree = ttk.Treeview(tw, columns=('num', 'key', 'addr'),
                                 style='Sw.Treeview', height=16, selectmode='browse')
        self.tree.heading('#0', text='Switch')
        self.tree.heading('num', text='#')
        self.tree.heading('key', text='Key')
        self.tree.heading('addr', text='Frame')
        self.tree.column('#0', width=248, stretch=True)
        self.tree.column('num', width=44, anchor='e', stretch=False)
        self.tree.column('key', width=78, anchor='center', stretch=False)
        self.tree.column('addr', width=54, anchor='center', stretch=False)
        vs = ttk.Scrollbar(tw, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side='left', fill='both', expand=True)
        vs.pack(side='left', fill='y')
        self.tree.tag_configure('closed', background=ROW_CLOSED,
                                foreground=ROW_CLOSED_FG)
        self.tree.tag_configure('nopos', foreground=DIM)
        self.tree.tag_configure('cat', background='#20242c', foreground='#9aa3b2')

        self.row_key = {}           # tree iid -> (fb, mask)
        self.key_row = {}           # (fb, mask) -> tree iid
        self.row_base = {}          # iid -> base tag list
        self._row_closed = {}       # iid -> last drawn closed state
        self._populate_tree()

        self.tree.bind('<Button-1>', self._tree_click)
        self.tree.bind('<Button-3>', self._tree_right)
        self.tree.bind('<<TreeviewSelect>>', self._tree_select)

        self.detail = tk.Label(right, text='', bg=BG, fg=FG, anchor='w',
                               justify='left', font=('Consolas', 9), height=3)
        self.detail.pack(anchor='w', fill='x')

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
        row = tk.Frame(right, bg=BG)
        row.pack(anchor='w', fill='x')
        self.ball_state = tk.Label(row, text='', bg=BG, fg=FG, anchor='w',
                                   font=('Consolas', 10))
        self.ball_state.pack(side='left', fill='x', expand=True)
        tk.Button(row, text='Drain', command=self._do_drain).pack(side='right')
        tk.Button(row, text='Plunge', command=self._do_plunge
                  ).pack(side='right', padx=(0, 4))
        self.ball_note = tk.Label(right, text='', bg=BG, fg='#8a93a2',
                                  anchor='w', justify='left', height=3,
                                  font=('Consolas', 8))
        self.ball_note.pack(anchor='w', fill='x')

    def _do_drain(self):
        if self.feeder is not None:
            self.feeder.drain()

    def _do_plunge(self):
        if self.feeder is not None:
            self.feeder.plunge()

    def _populate_tree(self):
        cats = {}
        for name in CAT_ORDER:
            cats[name] = self.tree.insert('', 'end', text=name, open=True,
                                          tags=('cat',))
        # Stable, readable order: by frame address within each category.
        for key in sorted(self.switches):
            fb, mask = key
            s = self.switches[key]
            cat = _category(fb)
            num = _matrix_num(fb, mask)
            name = s.get('name') or s.get('symbol') or ''
            base = [] if s.get('x') is not None else ['nopos']
            iid = self.tree.insert(
                cats[cat], 'end', text='  ' + name,
                values=('' if num is None else num, '', _addr_str(fb, mask)),
                tags=tuple(base))
            self.row_key[iid] = key
            self.key_row[key] = iid
            self.row_base[iid] = base
            self._row_closed[iid] = False

    def _tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.row_key:
            self.pulse(self.row_key[iid])

    def _tree_right(self, event):
        iid = self.tree.identify_row(event.y)
        if iid in self.row_key:
            self.toggle(self.row_key[iid])

    def _tree_select(self, _event):
        sel = self.tree.selection()
        if sel and sel[0] in self.row_key:
            self.hover(self.row_key[sel[0]])

    # ---------------------------------------------------------------- LEDs
    def _build_led_panel(self, right, devices):
        tk.Label(right, text=f'LEDs  ({len(self.lamps)} placed of '
                             f'{len(devices.get("lamps", []))})  - RGB (provisional)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w',
                                                                 pady=(8, 2))
        self.led_note = tk.Label(right, text='', bg=BG, fg='#c88', anchor='w',
                                 justify='left', font=('Segoe UI', 8))
        self.led_note.pack(anchor='w')
        ledgrid = tk.Frame(right, bg=BG)
        ledgrid.pack(anchor='nw', pady=(2, 0))
        self.led_cells = {}
        per_row = 24
        for i, _l in enumerate(self.lamps):
            c = tk.Label(ledgrid, width=1, height=1, bg=LED_DARK,
                         relief='flat', borderwidth=1)
            c.grid(row=i // per_row, column=i % per_row, padx=1, pady=1)
            c.bind('<Enter>', lambda e, k=i: self.hover_lamp(k))
            c.bind('<Leave>', lambda e: self.hover(None))
            self.led_cells[i] = c

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

        STILL PROVISIONAL, and the UI says so.  The colour is now live and full
        (all pages accumulated, 6-bit values scaled to 8-bit below), read at
        index*3.  What is NOT yet verified is the exact page-ordering and the
        per-lamp offset - decoding which (page, byte) drives which lamp needs a
        correlation pass (drive one lamp in game-test, watch which byte moves).
        The switch matrix, by contrast, WAS derived and verified.
        """
        if not buf:
            return 0, 0, 0
        n = len(buf)
        base = (self.lamps[i]['index'] * 3) % n
        # 6-bit brightness (0x3f max) -> 8-bit for display.
        return (min(255, buf[base] * 4),
                min(255, buf[(base + 1) % n] * 4),
                min(255, buf[(base + 2) % n] * 4))

    @staticmethod
    def _rgb_hex(r, g, b):
        return f'#{r:02x}{g:02x}{b:02x}'

    def _led_colour(self, i, buf):
        r, g, b = self.led_rgb(i, buf)
        return self._rgb_hex(r, g, b) if (r or g or b) else LED_DARK

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

    def _build_keyboard_legend(self, parent):
        tk.Label(parent, text='Keyboard  (this window must be focused)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w',
                                                                 pady=(8, 2))
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(anchor='w')
        col = 0
        rowf = None
        entries = [(ks, lbl, key is not None)
                   for ks, lbl, key in self.keybindings]
        # The ball keys always resolve - they go to the feeder, not a switch.
        entries += [(ks, lbl, True) for ks, lbl, _a in BALL_KEYS]
        for i, (keysyms, label, ok) in enumerate(entries):
            if i % 3 == 0:
                rowf = tk.Frame(wrap, bg=BG)
                rowf.pack(anchor='w')
                col = 0
            keytxt = self._key_label(keysyms)
            fg = FG if ok else DIM
            tk.Label(rowf, text=f'{keytxt:>7} {label}', bg=BG, fg=fg,
                     font=('Consolas', 9), width=20, anchor='w'
                     ).grid(row=0, column=col, sticky='w')
            col += 1

        row = tk.Frame(parent, bg=BG)
        row.pack(anchor='w', pady=(6, 0))
        tk.Label(row, text='switch #', bg=BG, fg=FG,
                 font=('Segoe UI', 9)).pack(side='left')
        self.sw_entry = tk.Entry(row, width=5, font=('Consolas', 10))
        self.sw_entry.pack(side='left', padx=4)
        self.sw_entry.bind('<Return>', lambda e: self._entry_pulse())
        tk.Button(row, text='Pulse', command=self._entry_pulse).pack(side='left')
        tk.Button(row, text='Latch', command=self._entry_latch
                  ).pack(side='left', padx=(4, 0))
        tk.Label(parent, text='(# is the playfield matrix number; Shift+key latches)',
                 bg=BG, fg=DIM, font=('Segoe UI', 8)).pack(anchor='w')

    def _entry_key(self):
        try:
            n = int(self.sw_entry.get().strip())
        except (ValueError, AttributeError):
            return None
        if not 1 <= n <= MATRIX_SWITCHES:
            return None
        fb = MATRIX_FIRST_BYTE + (n - 1) // 8
        mask = 1 << ((n - 1) % 8)
        return (fb, mask)

    def _entry_pulse(self):
        key = self._entry_key()
        if key is not None:
            self.pulse(key)

    def _entry_latch(self):
        key = self._entry_key()
        if key is not None:
            self.toggle(key)

    # ---------------------------------------------------------------- hover
    def hover_lamp(self, i):
        l = self.lamps[i]
        buf = self._led_buf
        r, g, b = self.led_rgb(i, buf) if buf else (0, 0, 0)
        self.detail.config(
            text=f"LED {l['index']}  {l['name']}   rgb ({r}, {g}, {b})\n"
                 f"  {l['symbol']}\n"
                 f"  ({l['x_in']:.2f}, {l['y_in']:.2f}) in  kind {l['lamp_kind']}")

    def hover(self, key):
        if key is None:
            self.detail.config(text='')
            return
        s = self.switches.get(key)
        if not s:
            return
        fb, mask = key
        num = _matrix_num(fb, mask)
        pos = f"({s['x']},{s['y']})" if s.get('x') is not None else '(no position)'
        head = s.get('name') or s.get('symbol') or ''
        self.detail.config(
            text=f"{head}   {'#%d' % num if num else _category(fb)}\n"
                 f"  {s.get('symbol','')}  {pos}\n"
                 f"  frame byte {fb:#04x} bit {mask:#04x}")

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

    def tick(self):
        # Switch markers + table rows (only retag rows whose state changed).
        for key, (oid, _x, _y) in self.markers.items():
            self.pf.itemconfig(oid, fill=MARK_ON if self.shm.get_switch(*key)
                               else MARK_OFF)
        for iid, key in self.row_key.items():
            closed = self.shm.get_switch(*key)
            if closed != self._row_closed[iid]:
                self._row_closed[iid] = closed
                tags = self.row_base[iid] + (['closed'] if closed else [])
                self.tree.item(iid, tags=tuple(tags))

        led_writes = self.shm.led_write_total()
        if led_writes:
            self._accumulate_leds()
        buf = self._led_buf
        for i, cell in self.led_cells.items():
            colour = self._led_colour(i, buf) if buf else LED_DARK
            cell.config(bg=colour)
            self.pf.itemconfig(self.lamp_marks[i][0], fill=colour)
        self.led_note.config(
            text='' if led_writes else
            'LED boards not written yet - cells show LAYOUT ONLY.')

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
