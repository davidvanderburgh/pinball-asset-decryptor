#!/usr/bin/env python3
"""Switch matrix for an emulated JJP game: a playfield view and an 8x16 grid.

WHAT IT IS
----------
Two views of the same 128 switches, side by side:

* the game's OWN playfield photograph (``graphics/Game Tests/pf_image.png``,
  decrypted out of its edata) with a labelled marker on every switch that has a
  position - click a marker to close that switch;
* the raw 8x16 matrix grid, which covers every switch including the ~80 with no
  playfield position, laid out the way the 64-byte I/O frame actually stores
  them.

Switch state lives in the POSIX shared-memory block defined by ``jjpshm.h`` and
is read by ``jjphwshim.c`` on every ``read()`` of the fake I/O board.  This file
PARSES jjpshm.h for the layout rather than restating it, because two places
defining one fact is the specific mistake that has bitten this rig hardest.

WHERE THE DATA COMES FROM
-------------------------
``swdump.py --out devices.json`` against a running game.  Every device object is
zeroed in the ELF, so names, playfield coordinates and frame addressing only
exist in a live process.

MOMENTARY vs LATCHED
--------------------
Real playfield switches are momentary: a ball rolls over a rollover and the
contact closes for tens of milliseconds.  Left-click therefore PULSES a switch
(close, then open after --pulse-ms).  Right-click LATCHES it, which is what you
want for things that really are held - a ball resting in the trough, or the coin
door.  Getting this backwards makes the trough impossible to model and the game
think it has lost its balls.
"""

import argparse
import ctypes
import json
import mmap
import os
import re
import sys
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SHM = '/jjp_switches'


# --------------------------------------------------------------------------
# Layout, parsed from the C header so there is exactly one definition of it.
# --------------------------------------------------------------------------

def shm_layout(header=None):
    """Read the #defines out of jjpshm.h.  One definition, two languages."""
    path = header or os.path.join(HERE, 'jjpshm.h')
    text = open(path).read()
    want = ('JJP_MATRIX_FIRST_BYTE', 'JJP_MATRIX_BYTES', 'JJP_MATRIX_SWITCHES',
            'JJP_FRAME_LEN', 'JJP_BOARD_COUNT')
    out = {}
    for key in want:
        m = re.search(rf'^#define\s+{key}\s+(\d+)', text, re.M)
        if m:
            out[key] = int(m.group(1))
    # JJP_BOARD_COUNT is the tail of an enum, not a #define.
    if 'JJP_BOARD_COUNT' not in out:
        m = re.search(r'enum\s*\{(.*?)\}', text, re.S)
        names = [n.strip().split('=')[0].strip()
                 for n in m.group(1).split(',') if n.strip()]
        out['JJP_BOARD_COUNT'] = names.index('JJP_BOARD_COUNT')
    missing = [k for k in want if k not in out]
    if missing:
        raise RuntimeError(f'jjpshm.h missing {missing}')
    return out


L = shm_layout()
MATRIX_BYTES = L['JJP_MATRIX_BYTES']
MATRIX_SWITCHES = L['JJP_MATRIX_SWITCHES']
FRAME_LEN = L['JJP_FRAME_LEN']
BOARD_COUNT = L['JJP_BOARD_COUNT']

# struct jjp_shm, in order.  Must match jjpshm.h.
OFF_MAGIC = 0
OFF_VERSION = 4
OFF_GAME_PID = 8
OFF_SWITCHES = 12
OFF_CABINET = OFF_SWITCHES + MATRIX_BYTES
OFF_OUT = OFF_CABINET + MATRIX_BYTES
OFF_OUT_CHANGES = OFF_OUT + BOARD_COUNT * FRAME_LEN
OFF_READ_COUNT = OFF_OUT_CHANGES + BOARD_COUNT * 4
OFF_WRITE_COUNT = OFF_READ_COUNT + 4
SHM_SIZE = OFF_WRITE_COUNT + 4


class SwitchShm:
    """The shared block.  Create it if the shim has not yet."""

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

    def set_switch(self, n, closed):
        """n is 1-based switch number, matching switch_NNN."""
        if not 1 <= n <= MATRIX_SWITCHES:
            return
        byte = OFF_SWITCHES + (n - 1) // 8
        bit = 1 << ((n - 1) % 8)
        cur = self.map[byte]
        self.map[byte] = (cur | bit) if closed else (cur & ~bit)

    def get_switch(self, n):
        byte = OFF_SWITCHES + (n - 1) // 8
        return bool(self.map[byte] & (1 << ((n - 1) % 8)))

    def clear(self):
        for i in range(MATRIX_BYTES):
            self.map[OFF_SWITCHES + i] = 0

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

    def coil_changes(self):
        o = OFF_OUT_CHANGES
        return [int.from_bytes(self.map[o + i * 4:o + i * 4 + 4], 'little')
                for i in range(BOARD_COUNT)]


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

BG = '#15171c'
FG = '#e8e8ea'
GRID_OFF = '#2a2f3a'
GRID_ON = '#41d67c'
GRID_NOPOS = '#3a3340'
MARK_OFF = '#5aa9e6'
MARK_ON = '#41d67c'


#: Board index for the LED board, matching the enum in jjpshm.h.
BOARD_LED = 1

MARK_LAMP_OFF = '#4a4335'
MARK_LAMP_ON = '#ffd34d'


class MatrixUI:
    def __init__(self, root, devices, shm, pf_png=None, pulse_ms=120):
        self.root = root
        self.shm = shm
        self.pulse_ms = pulse_ms
        self.by_num = {}
        self.latched = set()
        self.lamps = []
        self.calib = devices.get('calibration', {})

        # Key on the FRAME ADDRESS, not the symbol name.
        #
        # The game carries two symbols for the same physical switch: a bare
        # switch_NNN and a descriptive one (switch_trough_5, switch_spinner).
        # Only the descriptive ones have playfield coordinates, and matching on
        # /switch_\d+/ therefore silently drops every positioned switch and
        # draws an empty playfield - which is exactly what it did the first
        # time.  byte+bit is the physical identity and unifies both schemes:
        # switch_trough_5 is byte 0x04 bit 0x01, i.e. switch number 1.
        for s in devices.get('switches', []):
            fb, bit = s.get('frame_byte'), s.get('frame_bit')
            if fb is None or not bit:
                continue
            n = (fb - L['JJP_MATRIX_FIRST_BYTE']) * 8 + bit.bit_length()
            if not 1 <= n <= MATRIX_SWITCHES:
                continue
            prev = self.by_num.get(n)
            # Prefer the descriptive alias, and any entry that has a position.
            if prev is None or (prev.get('x') is None and s.get('x') is not None):
                self.by_num[n] = s

        # Lamps arrive in INCHES and must be projected into the playfield
        # photograph's pixel space.  swdump.py solves that mapping from
        # devices that share an exact name suffix with a switch; if the fit
        # failed we draw no lamps rather than draw them all in the corner.
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

        top = tk.Frame(root, bg=BG)
        top.pack(fill='x', padx=10, pady=(10, 4))
        self.status = tk.Label(top, text='', bg=BG, fg=FG, anchor='w',
                               font=('Consolas', 10))
        self.status.pack(side='left', fill='x', expand=True)
        tk.Button(top, text='All open', command=self.all_open).pack(side='right')

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=10, pady=6)

        # --- playfield view -------------------------------------------------
        self.pf_img = None
        if pf_png and os.path.exists(pf_png):
            try:
                self.pf_img = tk.PhotoImage(file=pf_png)
            except tk.TclError:
                self.pf_img = None

        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='y')
        w = self.pf_img.width() if self.pf_img else 385
        h = self.pf_img.height() if self.pf_img else 768
        self.pf = tk.Canvas(left, width=w, height=h, bg='#0b0c10',
                            highlightthickness=0)
        self.pf.pack()
        if self.pf_img:
            self.pf.create_image(0, 0, image=self.pf_img, anchor='nw')
        else:
            self.pf.create_text(w // 2, h // 2, fill='#777',
                                text='no playfield image\n(pass --pf)',
                                justify='center')

        # Lamps first, so a switch marker is never hidden behind one.
        self.lamp_marks = {}
        for i, l in enumerate(self.lamps):
            x, y = l['px'], l['py']
            r = 4
            oid = self.pf.create_rectangle(x - r, y - r, x + r, y + r,
                                           fill=MARK_LAMP_OFF, outline='')
            self.lamp_marks[i] = oid
            self.pf.tag_bind(oid, '<Enter>', lambda e, k=i: self.hover_lamp(k))
            self.pf.tag_bind(oid, '<Leave>', lambda e: self.hover(None))

        self.markers = {}
        for n, s in sorted(self.by_num.items()):
            if s.get('x') is None:
                continue
            x, y = s['x'], s['y']
            r = 7
            oid = self.pf.create_oval(x - r, y - r, x + r, y + r,
                                      fill=MARK_OFF, outline='#0b0c10', width=2)
            self.markers[n] = oid
            self.pf.tag_bind(oid, '<Button-1>', lambda e, k=n: self.pulse(k))
            self.pf.tag_bind(oid, '<Button-3>', lambda e, k=n: self.toggle(k))
            self.pf.tag_bind(oid, '<Enter>',
                             lambda e, k=n: self.hover(k))
            self.pf.tag_bind(oid, '<Leave>', lambda e: self.hover(None))

        # --- grid view ------------------------------------------------------
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True, padx=(12, 0))
        tk.Label(right, text='switch matrix  (rows = frame byte 4..19, cols = bit)',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w')

        grid = tk.Frame(right, bg=BG)
        grid.pack(anchor='nw', pady=(4, 8))
        self.cells = {}
        for row in range(MATRIX_BYTES):
            tk.Label(grid, text=f'{4 + row:#04x}', bg=BG, fg='#6b7280',
                     font=('Consolas', 8)).grid(row=row, column=0, padx=(0, 4))
            for col in range(8):
                n = row * 8 + col + 1
                s = self.by_num.get(n)
                colour = GRID_OFF if s and s.get('x') is not None else GRID_NOPOS
                b = tk.Label(grid, text=f'{n}', width=4, height=1, bg=colour,
                             fg=FG, font=('Consolas', 8), relief='flat',
                             borderwidth=1)
                b.grid(row=row, column=col + 1, padx=1, pady=1)
                b.bind('<Button-1>', lambda e, k=n: self.pulse(k))
                b.bind('<Button-3>', lambda e, k=n: self.toggle(k))
                b.bind('<Enter>', lambda e, k=n: self.hover(k))
                b.bind('<Leave>', lambda e: self.hover(None))
                self.cells[n] = b

        self.detail = tk.Label(right, text='', bg=BG, fg=FG, anchor='w',
                               justify='left', font=('Consolas', 9))
        self.detail.pack(anchor='w', fill='x')

        # --- LED panel ------------------------------------------------------
        tk.Label(right, text=f'LEDs  ({len(self.lamps)} placed of '
                             f'{len(devices.get("lamps", []))})',
                 bg=BG, fg='#9aa3b2', font=('Segoe UI', 9)).pack(anchor='w',
                                                                 pady=(10, 2))
        self.led_note = tk.Label(right, text='', bg=BG, fg='#c88', anchor='w',
                                 justify='left', font=('Segoe UI', 8))
        self.led_note.pack(anchor='w')

        ledgrid = tk.Frame(right, bg=BG)
        ledgrid.pack(anchor='nw', pady=(4, 0))
        self.led_cells = {}
        per_row = 24
        for i, l in enumerate(self.lamps):
            c = tk.Label(ledgrid, width=1, height=1, bg=MARK_LAMP_OFF,
                         relief='flat', borderwidth=1)
            c.grid(row=i // per_row, column=i % per_row, padx=1, pady=1)
            c.bind('<Enter>', lambda e, k=i: self.hover_lamp(k))
            c.bind('<Leave>', lambda e: self.hover(None))
            self.led_cells[i] = c

        tk.Label(right, bg=BG, fg='#6b7280', justify='left', font=('Segoe UI', 9),
                 text=('left-click = pulse (momentary, like a real rollover)\n'
                       'right-click = latch (trough balls, coin door)\n'
                       'grey-purple cells have no playfield position')
                 ).pack(anchor='w', pady=(8, 0))

        self.tick()

    def hover_lamp(self, i):
        l = self.lamps[i]
        self.detail.config(
            text=f"LED {l['index']}  {l['name']}\n"
                 f"  {l['symbol']}\n"
                 f"  ({l['x_in']:.2f}, {l['y_in']:.2f}) in  ->  "
                 f"({l['px']}, {l['py']}) px   kind {l['lamp_kind']}")

    def led_lit(self, i):
        """Is this lamp lit, according to the game's last LED frame?

        PROVISIONAL.  The switch matrix layout was *derived and verified*; this
        one is not.  The game has never yet written the LED board under the
        rig, so there is no traffic to check a mapping against, and the byte
        order inside JJP's 64-byte LED pages is still unknown.  We show a lamp
        as lit when its index maps to a non-zero byte in the last LED frame,
        which is the simplest thing consistent with what we know - and the UI
        says plainly when the board has never been written, so nobody mistakes
        an unlit panel for "all lamps off".
        """
        frame = self.shm.out_frame(BOARD_LED)
        return bool(frame[self.lamps[i]['index'] % FRAME_LEN])

    def hover(self, n):
        if n is None:
            self.detail.config(text='')
            return
        s = self.by_num.get(n)
        if not s:
            self.detail.config(text=f'switch_{n:03d}  (not in this game)')
            return
        pos = f"({s['x']},{s['y']})" if s.get('x') is not None else '(no position)'
        self.detail.config(
            text=f"switch_{n:03d}  {s.get('name','')}\n"
                 f"  {s.get('symbol','')}  {pos}\n"
                 f"  frame byte {s.get('frame_byte',0):#04x} bit {s.get('frame_bit',0):#04x}")

    def pulse(self, n):
        self.shm.set_switch(n, True)
        self.latched.discard(n)
        self.root.after(self.pulse_ms, lambda: self.shm.set_switch(n, False))

    def toggle(self, n):
        now = not self.shm.get_switch(n)
        self.shm.set_switch(n, now)
        if now:
            self.latched.add(n)
        else:
            self.latched.discard(n)

    def all_open(self):
        self.shm.clear()
        self.latched.clear()

    def tick(self):
        for n, cell in self.cells.items():
            on = self.shm.get_switch(n)
            s = self.by_num.get(n)
            base = GRID_OFF if s and s.get('x') is not None else GRID_NOPOS
            cell.config(bg=GRID_ON if on else base)
        for n, oid in self.markers.items():
            self.pf.itemconfig(oid, fill=MARK_ON if self.shm.get_switch(n) else MARK_OFF)
        led_writes = self.shm.board_writes(BOARD_LED)
        for i, cell in self.led_cells.items():
            on = self.led_lit(i) if led_writes else False
            colour = MARK_LAMP_ON if on else MARK_LAMP_OFF
            cell.config(bg=colour)
            self.pf.itemconfig(self.lamp_marks[i], fill=colour)
        self.led_note.config(
            text='' if led_writes else
            'LED board has never been written by the game - these show '
            'LAYOUT ONLY, not live state.')

        rd, wr, pid = self.shm.counters()
        live = 'reading' if rd else 'NOT reading (game has not opened the boards)'
        self.status.config(
            text=f'game pid {pid or "-"}   frames in {rd}  out {wr}   {live}'
                 f'   latched {len(self.latched)}   LED writes {led_writes}')
        self.root.after(100, self.tick)


def main(argv=None):
    ap = argparse.ArgumentParser(description='JJP switch matrix')
    ap.add_argument('--devices', default='/var/tmp/wonka_devices.json',
                    help='JSON from swdump.py')
    ap.add_argument('--pf', default=None, help='playfield PNG (pf_image.png)')
    ap.add_argument('--shm', default=DEFAULT_SHM)
    ap.add_argument('--pulse-ms', type=int, default=120)
    args = ap.parse_args(argv)

    if not os.path.exists(args.devices):
        print(f'jjpsw: {args.devices} not found.  Run:\n'
              f'  python3 swdump.py --out {args.devices}\n'
              f'against a running game first.', file=sys.stderr)
        return 3

    devices = json.load(open(args.devices))
    shm = SwitchShm(args.shm)
    root = tk.Tk()
    MatrixUI(root, devices, shm, pf_png=args.pf, pulse_ms=args.pulse_ms)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
