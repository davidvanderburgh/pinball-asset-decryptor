"""Spike 1 switch-matrix + LED/lamp viewer.

Reads the emulation rig's shared hardware-state block (written by the host-side
node-bus decoder) and renders the machine's live I/O:

  * the **switch matrix** — every switch as a cell, closed switches lit;
  * the **lamps / RGB LEDs** — each at its live colour/brightness;
  * the **coils** — energized coils flashed.

Click a switch cell to inject a press: it is written to the switch-input block
the decoder feeds back to the game (so you can start a game, hit targets, etc.
from the PC — the parity with the Spike 2 emulator's playfield window).

The render is split from Tk so it is testable headless and can emit a PNG:

    python s1view.py --demo --png out.png     # render one synthetic frame
    python s1view.py --run-dir <dir>          # live Tk viewer over a rig run
    python s1view.py --demo                    # live Tk viewer, synthetic feed

The viewer only ever consumes the abstract HardwareState — it knows nothing of
the (still-unverified) Spike 1 node wire format; the decoder owns that.
"""

import argparse
import math
import os
import sys

# Allow running straight from the repo without installation.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from pinball_decryptor.plugins.stern.spike1_emulate import (  # noqa: E402
    MAX_INDEX, MAX_NODES, HardwareState, StateBlock, SwitchInput, addr)

# ---- layout constants (used by both the PNG render and the Tk grid) ----
CELL = 22
PAD = 3
LABEL_W = 64
SECTION_GAP = 18
BG = (24, 26, 30)
GRID = (54, 58, 66)
SW_OPEN = (44, 48, 56)
SW_CLOSED = (90, 220, 120)
COIL_OFF = (44, 40, 48)
COIL_ON = (240, 170, 60)
TEXT = (200, 205, 214)
DIM = (120, 126, 136)


def active_nodes(state):
    """Nodes that carry any switch/lamp/coil signal, so the viewer shows only
    populated rows instead of a full 16x64 grid of blanks."""
    nodes = set()
    for node in range(MAX_NODES):
        base = node * MAX_INDEX
        if (any(state.switches[base:base + MAX_INDEX])
                or any(state.coils[base:base + MAX_INDEX])
                or any(state.lamps[base * 3:(base + MAX_INDEX) * 3])):
            nodes.add(node)
    return sorted(nodes) or [0]


def _section_geom(nodes, cols):
    rows = len(nodes)
    w = LABEL_W + cols * (CELL + PAD) + PAD
    h = rows * (CELL + PAD) + PAD
    return w, h


def render_png(state, path=None, cols=MAX_INDEX):
    """Render one frame of *state* to a PNG (returns the PIL image).

    Three stacked sections: switches, lamps/LEDs, coils.  Pure function of the
    state — the test oracle and the screenshot generator both call this.
    """
    from PIL import Image, ImageDraw

    nodes = active_nodes(state)
    sec_w, sec_h = _section_geom(nodes, cols)
    title_h = 20
    total_w = sec_w + 2 * PAD
    total_h = 3 * (title_h + sec_h + SECTION_GAP) + PAD
    img = Image.new("RGB", (total_w, total_h), BG)
    d = ImageDraw.Draw(img)

    def draw_section(y0, title, cell_color):
        d.text((PAD, y0), title, fill=TEXT)
        gy = y0 + title_h
        for r, node in enumerate(nodes):
            cy = gy + r * (CELL + PAD) + PAD
            d.text((PAD, cy + 4), "node %d" % node, fill=DIM)
            for c in range(cols):
                cx = LABEL_W + c * (CELL + PAD) + PAD
                col = cell_color(node, c)
                d.rectangle([cx, cy, cx + CELL, cy + CELL], fill=col,
                            outline=GRID)
        return gy + sec_h + SECTION_GAP

    def sw_color(node, i):
        return SW_CLOSED if state.get_switch(node, i) else SW_OPEN

    def lamp_color(node, i):
        r, g, b = state.get_lamp(node, i)
        return (r, g, b) if (r or g or b) else SW_OPEN

    def coil_color(node, i):
        return COIL_ON if state.get_coil(node, i) else COIL_OFF

    y = PAD
    y = draw_section(y, "Switch matrix", sw_color)
    y = draw_section(y, "Lamps / LEDs", lamp_color)
    y = draw_section(y, "Coils", coil_color)

    if path:
        img.save(path)
    return img


# --------------------------------------------------------------------------
# synthetic demo feed (so the viewer is demonstrable before the device model
# feeds it live data)
# --------------------------------------------------------------------------

def demo_state(t):
    """A lively synthetic HardwareState at time *t* (seconds): a chase across
    lamps, a couple of pulsing RGB LEDs, rolling switch activity, coil pulses.
    Purely illustrative — not real game data."""
    st = HardwareState()
    # node 8: a lamp matrix doing a rainbow chase
    for i in range(MAX_INDEX):
        phase = (i / 8.0 + t) % 1.0
        r = int(127 + 127 * math.sin(2 * math.pi * (phase + 0.00)))
        g = int(127 + 127 * math.sin(2 * math.pi * (phase + 0.33)))
        b = int(127 + 127 * math.sin(2 * math.pi * (phase + 0.66)))
        if (i + int(t * 6)) % 5 == 0:
            st.set_lamp(8, i, r, g, b)
    # node 9: RGB LEDs pulsing
    for i in range(12):
        lvl = int(127 + 127 * math.sin(2 * math.pi * (t * 0.7 + i / 12.0)))
        st.set_lamp(9, i, lvl, int(lvl * 0.4), int(lvl * 0.8))
    # node 2: switch matrix, a moving band of closed switches
    band = int(t * 10) % MAX_INDEX
    for i in range(MAX_INDEX):
        if abs(i - band) <= 1:
            st.set_switch(2, i, True)
    # node 3: trough switches steady-closed
    for i in range(6):
        st.set_switch(3, i, True)
    # node 8/9 coils: pulse a flipper + a pop bumper
    if int(t * 4) % 4 == 0:
        st.set_coil(8, 0, True)
    if int(t * 3) % 3 == 0:
        st.set_coil(9, 6, True)
    return st


# --------------------------------------------------------------------------
# live Tk viewer
# --------------------------------------------------------------------------

class Viewer:
    """Tk switch/LED viewer over a rig run dir (or a synthetic demo feed)."""

    def __init__(self, run_dir=None, demo=False, cols=MAX_INDEX):
        import tkinter as tk
        self.tk = tk
        self.run_dir = run_dir
        self.demo = demo
        self.cols = cols
        self.state = HardwareState()
        self.injected = set()       # slots the user is holding closed
        self._t0 = None
        self._seq = 0

        self.state_path = None
        self.input_path = None
        if run_dir:
            self.state_path = os.path.join(run_dir, "s1hw.state")
            self.input_path = os.path.join(run_dir, "s1sw.input")

        self.root = tk.Tk()
        self.root.title("Spike 1 — switches / LEDs" + (" (demo)" if demo else ""))
        # On-screen position (WSLg/Weston places a geometry-less window
        # off-screen); below the DMD window (which opens at +60+60).
        self.root.geometry("+60+320")
        self.root.configure(bg="#%02x%02x%02x" % BG)
        self.canvas = tk.Canvas(self.root, bg="#%02x%02x%02x" % BG,
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self._cells = {}            # (kind, node, index) -> canvas rect id
        self._build_needed = True

    # ---- data refresh ----
    def _read_live(self):
        try:
            with open(self.state_path, "rb") as f:
                buf = f.read(StateBlock.SIZE)
            StateBlock.unpack(buf, self.state)
        except (OSError, ValueError):
            pass

    def _write_injected(self):
        if not self.input_path:
            return
        self._seq += 1
        try:
            with open(self.input_path, "wb") as f:
                f.write(SwitchInput.pack(self.injected, self._seq))
        except OSError:
            pass

    # ---- tk grid ----
    def _tint(self, rgb):
        return "#%02x%02x%02x" % rgb

    def _build_grid(self):
        self.canvas.delete("all")
        self._cells.clear()
        nodes = active_nodes(self.state)
        if self.demo:
            nodes = sorted(set(nodes) | {2, 3, 8, 9})
        title_h = 20
        sec_w, sec_h = _section_geom(nodes, self.cols)
        y = PAD
        for kind, label in (("sw", "Switch matrix"),
                            ("lamp", "Lamps / LEDs"),
                            ("coil", "Coils")):
            self.canvas.create_text(PAD, y, anchor="nw", fill=self._tint(TEXT),
                                    text=label, font=("TkDefaultFont", 10, "bold"))
            gy = y + title_h
            for r, node in enumerate(nodes):
                cy = gy + r * (CELL + PAD) + PAD
                self.canvas.create_text(PAD, cy + CELL / 2, anchor="w",
                                        fill=self._tint(DIM), text="node %d" % node)
                for c in range(self.cols):
                    cx = LABEL_W + c * (CELL + PAD) + PAD
                    rid = self.canvas.create_rectangle(
                        cx, cy, cx + CELL, cy + CELL,
                        fill=self._tint(SW_OPEN), outline=self._tint(GRID))
                    self._cells[(kind, node, c)] = rid
            y = gy + sec_h + SECTION_GAP
        self.canvas.config(width=sec_w + 2 * PAD, height=y)
        self._build_needed = False

    def _paint(self):
        for (kind, node, c), rid in self._cells.items():
            if kind == "sw":
                closed = self.state.get_switch(node, c) or \
                    addr(node, c) in self.injected
                col = SW_CLOSED if closed else SW_OPEN
            elif kind == "lamp":
                r, g, b = self.state.get_lamp(node, c)
                col = (r, g, b) if (r or g or b) else SW_OPEN
            else:
                col = COIL_ON if self.state.get_coil(node, c) else COIL_OFF
            self.canvas.itemconfig(rid, fill=self._tint(col))

    def _on_click(self, ev):
        rid = self.canvas.find_closest(ev.x, ev.y)
        if not rid:
            return
        target = rid[0]
        for (kind, node, c), cid in self._cells.items():
            if cid == target and kind == "sw":
                slot = addr(node, c)
                if slot in self.injected:
                    self.injected.discard(slot)
                else:
                    self.injected.add(slot)
                self._write_injected()
                break

    def _tick(self):
        import time
        if self.demo:
            if self._t0 is None:
                self._t0 = time.monotonic()
            self.state = demo_state(time.monotonic() - self._t0)
        elif self.state_path:
            self._read_live()
        if self._build_needed:
            self._build_grid()
        self._paint()
        self.root.after(50, self._tick)

    def run(self):
        self._tick()
        self.root.mainloop()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Spike 1 switch/LED viewer")
    ap.add_argument("--run-dir", help="rig run dir with s1hw.state / s1sw.input")
    ap.add_argument("--demo", action="store_true", help="synthetic feed")
    ap.add_argument("--png", help="render one frame to this PNG and exit")
    ap.add_argument("--cols", type=int, default=MAX_INDEX)
    args = ap.parse_args(argv)

    if args.png:
        state = demo_state(1.7) if args.demo else HardwareState()
        if args.run_dir and not args.demo:
            try:
                with open(os.path.join(args.run_dir, "s1hw.state"), "rb") as f:
                    StateBlock.unpack(f.read(StateBlock.SIZE), state)
            except (OSError, ValueError):
                pass
        render_png(state, args.png, cols=args.cols)
        print("wrote", args.png)
        return 0

    Viewer(run_dir=args.run_dir, demo=args.demo, cols=args.cols).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
