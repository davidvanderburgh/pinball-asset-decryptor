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
    `dump/padled` (see padled.h) and this reads that file over
    \\\\wsl.localhost every POLL_MS. A plain read needs no mmap coherence across
    the VM boundary, and it is measurably live - the generation counter climbs.
  * SWITCH INPUT GOES THROUGH swpoke.py / plunge.py, as subprocesses. Writing
    the padsw block from Windows would be a shared-memory write racing a guest
    mmap across a 9p boundary, which is exactly the kind of thing that works in
    testing and fails later. ~200 ms of `wsl.exe` per action buys a path that is
    already proven, and none of these are timing-critical.

WHAT THE COLOURS MEAN, honestly. Blue rings are switches, click to close one.
Red squares are coils, which flash when the game fires them and play their
switch when clicked (see coilact.py for why a click cannot be a real fire).
Dots are inserts, lit from the wire.

A DARK INSERT HERE MEANS OFF, NOT "NO DATA" - which is worth stating plainly,
because the docstring used to warn the opposite. The undecoded strip boards
(nodes 7, 12 and 14) do exist, but every insert this window draws sits on node 8
or node 9, and both of those are decoded index for index against the boot
enumeration. The strip boards drive the TOPPER and the cabinet, and neither is
on this picture. 113 inserts, 53 on node 8 and 60 on node 9, all covered.
"""
import json
import os
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilact
import gameinfo

HERE = os.path.dirname(os.path.abspath(__file__))

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
TDIR = gameinfo.table_dir(GAME)
PF_PNG = gameinfo.playfield_png(GAME)
WINDOW_TITLE = "%s - virtual playfield" % GAME
LED_PATH = r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\padled"

#: The switch block, read for ONE thing: the coin door. 48V - the coil supply -
#: is interlocked to it exactly as on the real machine, and with the door open
#: the game will not fire anything and puts "48V DISABLED" on its own screen. A
#: playfield whose coils never flash is then working perfectly, which is not a
#: thing to leave anyone to work out for themselves.
SW_PATH = r"\\wsl.localhost\Ubuntu\home\david\spike2root\dump\padsw"
PADSW_MAGIC = 0x53444150
SW_HELD, SW_COIN_DOOR = 8, 33
WSL_DIR = ("/mnt/c/Users/david/Documents/development/pinball-asset-decryptor"
           "/tools/spike2_emu")

#: Offsets into padled.h's block. Hard-coded because Python cannot include the
#: header; the header lists them next to the struct and says APPEND ONLY, so a
#: version-1 shim and a version-2 reader still agree on everything below `coil`.
PADLED_MAGIC = 0x44454C50
LED_HDR, LED_IDX = 20, 96
COIL_OFF, COIL_N = 1556, 16          # wrapping fire counter per (node, index)
LVL_OFF = COIL_OFF + 16 * COIL_N     # last drive byte
COIL_GEN_OFF = LVL_OFF + 16 * COIL_N
PADLED_READ = COIL_GEN_OFF + 8

#: How long a coil marker stays lit after its fire counter moves. A coil pulse
#: is ~30 ms and a 50 ms poll would show it for one frame or miss it; this is a
#: readable flash, not a measurement.
COIL_FLASH_MS = 260

PRESS_MS = 150

#: 20 Hz. The game blinks inserts at a few hertz, so polling at the old 120 ms
#: aliased the blink into a flicker that looked like a bug in the decoder.
POLL_MS = 50

#: Close with the run: once the emulator has been SEEN, this many consecutive
#: failed polls of the LED block means the run has been torn down (watch.sh
#: removes dump/padled on exit precisely so this can tell), and the window
#: closes itself instead of sitting around as "no emulator". ~2 s of misses
#: rather than one, because a read over \\wsl.localhost can fail transiently
#: while everything is fine. A playfield started with no emulator at all never
#: trips this - nothing was seen, so there is nothing to close with.
GONE_POLLS = 40


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


def pick_scale(root, img_h, chrome=130):
    """Fit the artwork to the screen.

    A flat 2x is 1420 px tall and puts the flippers and the trough off the
    bottom of a 1080p screen with no way to reach them. PAD_PF_SCALE overrides.
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


class Field:
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
        self.bg = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))

        bar = tk.Frame(root, bg="#111")
        bar.pack(fill="x")
        for label, arg in (("Start", "start"), ("Plunge", "plunge"),
                           ("Reset balls", "reset")):
            tk.Button(bar, text=label, width=11,
                      command=lambda a=arg: self.run_plunge(a)).pack(side="left",
                                                                    padx=3, pady=3)
        tk.Label(bar, text="  click a switch or a coil - hover anything for detail",
                 bg="#111", fg="#888", font=("Consolas", 9)).pack(side="left")

        self.cv = tk.Canvas(root, width=w, height=h, highlightthickness=0,
                            bg="black")
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)
        self.status = tk.Label(root, text="", anchor="w", bg="#111", fg="#ddd",
                               font=("Consolas", 9))
        self.status.pack(fill="x")

        self.info = {}          # canvas item -> dict describing it
        self.led_items = {}
        self.coil_items = {}    # (node, index) -> canvas item
        self.coil_seen = {}     # (node, index) -> last fire counter read
        self.coil_until = {}    # (node, index) -> ms after which the flash ends

        for L in self.leds:
            x, y, r = L["x"] * self.scale, L["y"] * self.scale, 3.5
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    fill="#1a1a1a", outline="#3a3a3a")
            self.led_items[(L["node"], L["index"])] = i
            self.info[i] = dict(kind="led", d=L)

        for C in self.coils:
            x, y, r = C["x"] * self.scale, C["y"] * self.scale, 7
            i = self.cv.create_rectangle(x - r, y - r, x + r, y + r,
                                         outline="#ff4040", width=2)
            self.coil_items[(C["node"], C["index"])] = i
            self.info[i] = dict(kind="coil", d=C)

        for S in self.switches:
            x, y, r = S["x"] * self.scale, S["y"] * self.scale, 6
            i = self.cv.create_oval(x - r, y - r, x + r, y + r,
                                    outline="#2a8cff", width=2)
            self.info[i] = dict(kind="switch", d=S)

        self.tip = Tip(root)
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_move)
        self.cv.bind("<Leave>", lambda e: self.tip.hide())
        self.tick()

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
            return ("SWITCH  %s\nid %d   node %d  bit %d\nclick to close it"
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
            return "COIL  %s\n%s%s\nclick: %s" % (
                d["name"], where, live, act or "nothing wired")
        v = None
        if self.last:
            off = LED_HDR + d["node"] * LED_IDX + d["index"]
            if off < len(self.last):
                v = self.last[off]
        return ("LED  %s\nnode %d  index %d\nvalue %s"
                % (d["name"], d["node"], d["index"],
                   "%d" % v if v is not None else "no data"))

    def on_move(self, ev):
        i = self._hit(ev)
        if i is None:
            self.tip.hide()
            return
        self.tip.show(self._describe(i), ev.x_root, ev.y_root)

    # ---- actions ---------------------------------------------------------
    def on_click(self, ev):
        i = self._hit(ev)
        if i is None:
            return
        e = self.info[i]
        if e["kind"] == "switch":
            self.cv.itemconfig(i, outline="#ffd400", width=3)
            threading.Thread(target=self._press, args=(e["d"], i),
                             daemon=True).start()
        elif e["kind"] == "coil":
            if coilact.describe(e["d"]["name"]):
                threading.Thread(target=self._wsl,
                                 args=("coilact.py", e["d"]["name"]),
                                 daemon=True).start()

    def _wsl(self, script, *args):
        try:
            return subprocess.run(["wsl.exe", "-e", "python3",
                                   "%s/%s" % (WSL_DIR, script)] + list(args),
                                  capture_output=True, timeout=30,
                                  creationflags=_CREATE_NO_WINDOW)
        except Exception:
            return None

    def _press(self, S, item):
        self._wsl("swpoke.py", str(S["id"]), str(PRESS_MS))
        self.root.after(0, lambda: self.cv.itemconfig(item, outline="#2a8cff",
                                                      width=2))

    def run_plunge(self, what):
        threading.Thread(target=self._wsl, args=("plunge.py", what),
                         daemon=True).start()

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
        """True when the coin door is open, so 48V is off and coils are dead."""
        try:
            with open(SW_PATH, "rb") as f:
                d = f.read(SW_HELD + 64)
        except OSError:
            return False
        if len(d) < SW_HELD + 64 or struct.unpack_from("<I", d, 0)[0] != PADSW_MAGIC:
            return False
        return not d[SW_HELD + SW_COIN_DOOR]

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
            # MAGENTA, not a hotter orange. Lit inserts run #ff3c00..#fffb00, so
            # an orange coil flash is the one colour on this picture that cannot
            # be told apart from the thing next to it at a glance - and it is
            # ALSO exactly the ambiguity that made "did the flash render?"
            # unanswerable from a screenshot. Nothing else here is magenta.
            self.cv.itemconfig(item, fill="#ff00c0" if hot else "",
                               outline="#ff80ff" if hot else "#ff4040",
                               width=3 if hot else 2)
        return fired

    def tick(self):
        d = self.read_leds()
        self.last = d
        if emu_gone(self, d is not None):
            self.root.destroy()             # the run ended; leave with it
            return
        if d is None:
            self.status.config(text="no emulator (dump/padled not readable)")
        else:
            decoded = struct.unpack_from("<I", d, 12)[0]
            lit = 0
            for (node, idx), item in self.led_items.items():
                off = LED_HDR + node * LED_IDX + idx
                v = d[off] if off < len(d) else 0
                if v:
                    lit += 1
                    self.cv.itemconfig(item, outline="",
                                       fill="#ff%02x00" % (60 + v * 3 // 4))
                else:
                    self.cv.itemconfig(item, fill="#1a1a1a", outline="#3a3a3a")
            coils = ""
            if len(d) >= PADLED_READ and struct.unpack_from("<I", d, 4)[0] >= 2:
                self._tick_coils(d, time.monotonic() * 1000.0)
                coils = "   %d coils addressed" % struct.unpack_from(
                    "<I", d, COIL_GEN_OFF + 4)[0]
                if self.door_open():
                    coils += "   COIN DOOR OPEN: 48V off, no coil can fire"
            self.status.config(
                text=" %d of %d inserts lit   %d LED writes decoded%s"
                     % (lit, len(self.led_items), decoded, coils))
        self.root.after(POLL_MS, self.tick)


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


class Schematic:
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

        self.status = tk.Label(root, text="", anchor="w", bg="#111", fg="#ddd",
                               font=("Consolas", 9))
        self.status.pack(fill="x")
        self.tip = Tip(root)
        self.cv.bind("<Button-1>", self.on_click)
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
                      "click to close it"
                      % (d["name"], d["id"], d["num"], d["node"], d["bit"]),
                      ev.x_root, ev.y_root)

    def on_click(self, ev):
        i = self._hit(ev)
        if i is None:
            return
        d = self.info[i]["d"]
        self.cv.itemconfig(i, fill="#ffd400")
        threading.Thread(target=self._press, args=(d, i), daemon=True).start()

    def _press(self, sw, item):
        try:
            subprocess.run(["wsl.exe", "-e", "python3",
                            "%s/swpoke.py" % WSL_DIR, str(sw["id"]),
                            str(PRESS_MS)],
                           capture_output=True, timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
        except Exception:
            pass
        self.root.after(0, lambda: self.cv.itemconfig(item, fill="#d8d8d8"))

    def tick(self):
        """The LED block still says whether the emulator is up, which is the one
        thing this view can honestly report about it."""
        try:
            with open(LED_PATH, "rb") as f:
                d = f.read(PADLED_READ)
        except OSError:
            d = None
        if emu_gone(self, bool(d)):
            self.root.destroy()             # the run ended; leave with it
            return
        if not d or struct.unpack_from("<I", d, 0)[0] != PADLED_MAGIC:
            self.status.config(text="no emulator (dump/padled not readable)")
        else:
            self.status.config(
                text=" emulator up   %d LED writes decoded   %d coils addressed"
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
    if PF_PNG and os.path.exists(PF_PNG) and load_switches():
        Field(root)
    else:
        rows = load_switch_list()
        if not rows:
            tk.Label(root, padx=20, pady=20, justify="left", font=("Consolas", 10),
                     text=("No tables for %s." + '\n\n' +
                           "Positions:   devicexy.py   (needs a title that ships" '\n' +
                           "             a device table; many do not)" '\n' +
                           "Switch list: swtable.py <run.log> %s")
                     % (GAME, GAME)).pack()
        else:
            Schematic(root, rows)
    pos = load_state().get("playfield_pos")
    if pos and _onscreen(root, *pos):
        root.geometry("+%d+%d" % (pos[0], pos[1]))

    def bye():
        save_state(root)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", bye)
    root.mainloop()


if __name__ == "__main__":
    main()
