#!/usr/bin/env python3
"""playfield.py - the virtual playfield: click switches, watch the inserts light.

Run it on WINDOWS, next to the emulator window, while watch.sh has the game up:

    python tools\\spike2_emu\\playfield.py

WHY WINDOWS AND NOT WSL, because the obvious choice does not work: WSL here has
no Python GUI toolkit at all - no tkinter, no gi/Gtk, no Qt - and installing one
needs a sudo this rig does not have. Windows has tkinter and Pillow already,
because the decryptor's own GUI uses them.

HOW IT REACHES THE GAME, and both halves are deliberate:

  * LED STATE IS READ, not mapped. The shim publishes live values into
    `dump/padled` (see padled.h) and this reads that file over
    \\\\wsl.localhost each poll. A plain read needs no mmap coherence across the
    VM boundary, and it is measurably live - the generation counter climbs.
  * CLICKS GO THROUGH swpoke.py, as a subprocess. Writing the padsw block from
    Windows would be a shared-memory write racing a guest mmap across a 9p
    boundary, which is exactly the kind of thing that works in testing and fails
    later. Spending ~200 ms on `wsl.exe` per click buys a path that is already
    proven, and a click is not a timing-critical input.

WHAT THE COLOURS MEAN, honestly: the LED decoder covers the INSERT boards (nodes
1, 8, 9) and NOT the strip boards (7, 12, 14), whose frames are a different
encoding. A dark insert may mean "no data" rather than "off". The status bar
shows the decoded count so that difference stays visible.
"""
import os
import struct
import subprocess
import sys
import threading
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))

PF_PNG = os.path.join(HERE, "pf_ref.png")
LED_PATH = r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\padled"
SWPOKE = ("/mnt/c/Users/david/Documents/development/pinball-asset-decryptor"
          "/tools/spike2_emu/swpoke.py")

PADLED_MAGIC = 0x44454C50
LED_HDR, LED_IDX = 20, 96
PRESS_MS = 150

#: The artwork is 313x710, so a flat 2x is 1420 tall and runs off a 1080p
#: screen with no way to reach the bottom of the playfield - which is where the
#: flippers and the trough are. Fit to the screen instead, and let PAD_PF_SCALE
#: override for a big monitor.
def pick_scale(root, img_h, chrome=90):
    env = os.environ.get("PAD_PF_SCALE")
    if env:
        try:
            return max(1.0, float(env))
        except ValueError:
            pass
    return max(1.0, (root.winfo_screenheight() - chrome) / float(img_h))

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


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
    """id node bit NAME... x y"""
    return [dict(id=int(p[0]), node=int(p[1]), bit=int(p[2]),
                 name=" ".join(p[3:-2]), x=int(p[-2]), y=int(p[-1]))
            for p in _rows(os.path.join(HERE, "switch_xy.txt"), 6)]


def load_leds():
    """node index NAME... x y conn image"""
    out = []
    for p in _rows(os.path.join(HERE, "led_io.txt"), 6):
        if p[-1] != "playfield":
            continue
        try:
            out.append(dict(node=int(p[0]), index=int(p[1]),
                            x=int(p[-4]), y=int(p[-3]),
                            name=" ".join(p[2:-4])))
        except ValueError:
            continue
    return out


class Field:
    def __init__(self, root):
        from PIL import Image, ImageTk
        self.root = root
        self.switches = load_switches()
        self.leds = load_leds()

        img = Image.open(PF_PNG).convert("RGB")
        self.scale = pick_scale(root, img.height)
        w, h = int(img.width * self.scale), int(img.height * self.scale)
        self.bg = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))

        self.cv = tk.Canvas(root, width=w, height=h, highlightthickness=0,
                            bg="black")
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)
        self.status = tk.Label(root, text="hover a switch", anchor="w",
                               bg="#111", fg="#ddd", font=("Consolas", 10))
        self.status.pack(fill="x")

        self.led_items = {}
        for L in self.leds:
            x, y, r = L["x"] * self.scale, L["y"] * self.scale, 3.5
            self.led_items[(L["node"], L["index"])] = self.cv.create_oval(
                x - r, y - r, x + r, y + r, fill="#1a1a1a", outline="#3a3a3a")

        self.sw_items = {}
        for S in self.switches:
            x, y, r = S["x"] * self.scale, S["y"] * self.scale, 6
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    outline="#2a8cff", width=2)
            self.sw_items[i] = S
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_move)

        self.hint = ""
        self.tick()

    # ---- input -----------------------------------------------------------
    def _hit(self, ev):
        for i in self.cv.find_overlapping(ev.x - 2, ev.y - 2, ev.x + 2, ev.y + 2):
            if i in self.sw_items:
                return i
        return None

    def on_move(self, ev):
        i = self._hit(ev)
        S = self.sw_items.get(i) if i else None
        self.hint = ("%s  (id %d, node %d bit %d)"
                     % (S["name"], S["id"], S["node"], S["bit"])) if S else ""

    def on_click(self, ev):
        i = self._hit(ev)
        if not i:
            return
        S = self.sw_items[i]
        self.cv.itemconfig(i, outline="#ffd400", width=3)
        threading.Thread(target=self._press, args=(S, i), daemon=True).start()

    def _press(self, S, item):
        try:
            subprocess.run(["wsl.exe", "-e", "python3", SWPOKE,
                            str(S["id"]), str(PRESS_MS)],
                           capture_output=True, timeout=20,
                           creationflags=_CREATE_NO_WINDOW)
        except Exception:
            pass
        self.root.after(0, lambda: self.cv.itemconfig(item, outline="#2a8cff",
                                                      width=2))

    # ---- live LED state --------------------------------------------------
    def read_leds(self):
        try:
            with open(LED_PATH, "rb") as f:
                d = f.read(LED_HDR + 16 * LED_IDX)
        except OSError:
            return None
        if len(d) < LED_HDR or struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            return None
        return d

    def tick(self):
        d = self.read_leds()
        if d is None:
            self.status.config(text="no emulator (dump/padled not readable)")
        else:
            decoded = struct.unpack_from("<I", d, 12)[0]
            for (node, idx), item in self.led_items.items():
                off = LED_HDR + node * LED_IDX + idx
                v = d[off] if off < len(d) else 0
                if v:
                    self.cv.itemconfig(item, outline="",
                                       fill="#ff%02x00" % (60 + v * 3 // 4))
                else:
                    self.cv.itemconfig(item, fill="#1a1a1a", outline="#3a3a3a")
            self.status.config(
                text="%-52s %d LED writes decoded (insert boards only)"
                     % (self.hint, decoded))
        self.root.after(120, self.tick)


def main():
    root = tk.Tk()
    root.title("Godzilla Pro - virtual playfield")
    Field(root)
    root.mainloop()


if __name__ == "__main__":
    main()
