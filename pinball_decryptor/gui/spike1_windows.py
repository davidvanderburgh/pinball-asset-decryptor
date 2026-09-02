r"""Pop-out DMD and switch-matrix windows for the Spike 1 emulator.

The Spike 1 game's picture is a 128x32 **DMD** and its I/O is a **switch matrix**
+ LEDs; both want their own window (David: "open the dmd in its own window since
we will also have the switch matrix in its own window too"), the way the Spike 2
emulator has a separate game window and playfield window.

These are **native Tk windows in the app process**, not WSLg windows — WSLg
places geometry-less windows off-screen and its mapping is flaky (that is why the
old ``s1view`` viewer was never reliably visible). They read the emulator's live
run-dir files straight off the WSL disk over the ``\\wsl.localhost\<distro>\...``
UNC path (verified fresh on a growing file), so a poll is a plain file read with
no ``wsl.exe`` per frame:

  * ``spi0.cap`` — the display frame stream; the display window tails the last
    whole frame and renders it.  2048-byte frames for the 128x32 DMD, or —
    when ``s1display`` in the run dir says ``alphanumeric`` (the 2012 home
    models, PAD-101) — 256-byte frames for two 8-digit 16-segment displays,
    drawn as such (``tools/spike1_emu/s1alpha.py``).
  * ``s1hw.state`` — the shared :class:`~...spike1_emulate.StateBlock` the
    node-bus decoder writes (switches / lamps / coils); the switch window shows
    it, and OR-s in the presses the user is holding.
  * ``s1sw.input`` — the :class:`~...spike1_emulate.SwitchInput` block the switch
    window writes on a click and the responder (``nodebus.py``) reads back, so a
    click closes a switch in the running game.
  * ``s1switches.json`` — the title's ``{"node,index": name}`` switch map, put
    there by ``start.sh``: a curated map straight away, or — on a title without
    one — the live registry walk's, **minutes into the boot** (``s1swmap.py``
    has to wait for the game to register its switches).  So this window RE-READS
    the map while it runs and rebuilds itself when it arrives; without that, a
    title with no curated map stayed on the nameless matrix grid with dead play
    keys for the whole session even though the names had shown up (PAD-101).

Live LED/coil colour appears once the node-bus decoder writes it into
``s1hw.state`` — until then only the presses you inject light up.
"""

import os
import sys
import tkinter as tk

from ..plugins.stern.spike1_emulate import (MAX_INDEX, MAX_NODES,  # noqa: F401
                                            HardwareState, StateBlock,
                                            SwitchInput, addr)

# ---- switch/LED layout (kept in step with tools/spike1_emu/s1view.py) ----
CELL = 20
PAD = 3
LABEL_W = 62
SECTION_GAP = 14
BG = (24, 26, 30)
GRID = (54, 58, 66)
SW_OPEN = (44, 48, 56)
SW_CLOSED = (90, 220, 120)
COIL_OFF = (44, 40, 48)
COIL_ON = (240, 170, 60)
TEXT = (200, 205, 214)
DIM = (120, 126, 136)
NAMED = (78, 120, 128)     # outline of a switch cell that has a known name

#: Node addresses a Spike 1 machine polls (from the ELF topology — see s1elf.py);
#: shown even before any state arrives so there is always something to click.
DEFAULT_NODES = (0, 1, 8, 9, 10, 11, 12)
#: node-local switch positions to show per node (boards address up to 64; the
#: low positions are where switches actually sit, and a 64-wide grid is unusable).
SWITCH_COLS = 16


def _tint(rgb):
    return "#%02x%02x%02x" % rgb


def wsl_unc(distro, wsl_path):
    r"""``/home/david/s1emu/x`` -> ``\\wsl.localhost\<distro>\home\david\s1emu\x``."""
    if not distro:
        return None
    return "\\\\wsl.localhost\\" + distro + wsl_path.replace("/", "\\")


class _RunDirIO:
    """Reads/writes the emulator run-dir files over the WSL UNC path."""

    def __init__(self, run_dir_wsl, distro):
        self.run_dir_wsl = run_dir_wsl
        self.distro = distro

    def _unc(self, name):
        return wsl_unc(self.distro, self.run_dir_wsl.rstrip("/") + "/" + name)

    def tail_frame(self, name, frame_bytes):
        """The last whole *frame_bytes* block of a growing capture, or None."""
        p = self._unc(name)
        if not p:
            return None
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                n = size // frame_bytes
                if n == 0:
                    return None
                f.seek((n - 1) * frame_bytes)
                data = f.read(frame_bytes)
            return data if len(data) == frame_bytes else None
        except OSError:
            return None

    def read_state(self):
        """The shared StateBlock -> HardwareState, or an empty one."""
        st = HardwareState()
        p = self._unc("s1hw.state")
        if not p:
            return st
        try:
            with open(p, "rb") as f:
                buf = f.read(StateBlock.SIZE)
            StateBlock.unpack(buf, st)
        except (OSError, ValueError):
            pass
        return st

    def write_injected(self, closed_slots, seq):
        p = self._unc("s1sw.input")
        if not p:
            return
        try:
            with open(p, "wb") as f:
                f.write(SwitchInput.pack(closed_slots, seq))
        except OSError:
            pass

    def append_ball_cmd(self, line):
        """Queue a one-shot for the s1ball.py ball-keeper daemon (coin / start /
        drain…): append a line to s1ball.cmd in the run dir.  Best-effort — if
        the daemon is not running the line is simply never consumed."""
        p = self._unc("s1ball.cmd")
        if not p:
            return False
        try:
            with open(p, "a", encoding="ascii") as f:
                f.write(line + "\n")
            return True
        except OSError:
            return False

    def read_switch_names(self):
        """The title's ``{(node, index): name}`` switch map (s1switches.json —
        the curated map, or the live registry walk's).  ``{}`` if the file is
        missing/unreadable, so the window still works nameless."""
        import json
        p = self._unc("s1switches.json")
        if not p:
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return {}
        out = {}
        for key, name in raw.items():
            try:
                node_s, idx_s = key.split(",")
                out[(int(node_s), int(idx_s))] = name
            except (ValueError, AttributeError):
                continue
        return out

    def read_json(self, name):
        """A small JSON file of the run dir (e.g. ``s1font.json``), or None."""
        import json
        p = self._unc(name)
        if not p:
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def read_text(self, name):
        """A small text file of the run dir (e.g. ``s1display``), stripped;
        ``""`` when absent."""
        p = self._unc(name)
        if not p:
            return ""
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def read_ball_state(self):
        """The ball keeper's published state (s1ball.state JSON): trough
        count, ball-in-shooter, coin door.  ``{}`` when absent."""
        import json
        p = self._unc("s1ball.state")
        if not p:
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}


class Spike1DisplayWindow(tk.Toplevel):
    """The game's display, in its own window: tails ``spi0.cap`` and renders
    the newest frame.

    Two shapes.  The DMD generation: 2048-byte 128x32x4bit frames, decoded by
    *decode_frame* (s1dmd) and drawn as amber dots at *scale*.  The 2012 home
    models (*alpha* given — ``(decode_frame, render_image)`` from s1alpha):
    256-byte frames for two 8-digit 16-segment displays, drawn as segments —
    a DMD window fed those frames showed nothing at all, since 256 bytes is
    never a whole 2048-byte frame (PAD-101)."""

    FRAME_BYTES = 2048
    WIDTH = 128
    HEIGHT = 32
    #: glyph scale for the 16-segment displays (the default 6 drew a window
    #: barely 300 px wide, which is what "completely unusable" was about)
    ALPHA_SCALE = 9
    #: the machine labels its two displays; so do we, under the right one
    ALPHA_LABELS = ("PLAYER 1", "PLAYER 2")
    ALPHA_FG = "#ff4a30"

    def __init__(self, master, io, decode_frame, scale=7, hz=20,
                 on_close=None, alpha=None):
        super().__init__(master)
        self._io = io
        self._decode = decode_frame
        self._alpha = alpha
        self._scale = scale
        self._delay = max(20, int(1000 / hz))
        self._on_close = on_close
        self._photo = None
        self._job = None
        self._closed = False
        self._frame_bytes = self.FRAME_BYTES

        cw, ch = self.WIDTH * scale, self.HEIGHT * scale
        self.title("Spike 1 — DMD")
        self._font = None
        self._readouts = []
        if alpha is not None:
            # size the canvas from a blank frame's rendering, so the window
            # is right before the first real frame lands
            decode, render = alpha
            blank = render(decode(bytes(256)), scale=self.ALPHA_SCALE)
            cw, ch = blank.size
            self._frame_bytes = 256
            self.title("Spike 1 — display")
            # the segment DECODER: the game's own font, dumped by the rig, so
            # the window can show what the machine actually reads (segment art
            # alone is unusable at this size - David, PAD-101).
            raw = io.read_json("s1font.json") if hasattr(io, "read_json") else None
            if raw:
                self._font = {tuple(int(c) for c in k): v
                              for k, v in raw.items() if len(k) == 16}
        self.configure(bg="#000000")
        self.geometry("+80+80")
        self._canvas = tk.Canvas(self, width=cw, height=ch, bg="#000000",
                                 highlightthickness=0)
        self._canvas.pack(padx=8, pady=8)
        self._imgid = self._canvas.create_image(0, 0, anchor="nw")
        if alpha is not None and self._font:
            # A readout under EACH display, side by side and labelled the way
            # the machine labels them (David's photo: PLAYER 1 left, PLAYER 2
            # right, in the speaker panel).
            import tkinter.font as tkfont
            big = tkfont.Font(family="Consolas", size=20, weight="bold")
            small = tkfont.Font(family="Segoe UI", size=8)
            row = tk.Frame(self, bg="#000000")
            row.pack(side="top", fill="x")
            for i, cap in enumerate(self.ALPHA_LABELS):
                col = tk.Frame(row, bg="#000000")
                col.grid(row=0, column=i, sticky="ew", padx=(12, 12))
                row.grid_columnconfigure(i, weight=1, uniform="disp")
                lbl = tk.Label(col, text="", font=big, bg="#000000",
                               fg=self.ALPHA_FG, anchor="w")
                lbl.pack(side="top", anchor="w")
                tk.Label(col, text=cap, font=small, bg="#000000",
                         fg="#8a8a8a", anchor="w").pack(side="top", anchor="w")
                self._readouts.append(lbl)
        self._placeholder = self._canvas.create_text(
            cw // 2, ch // 2, fill="#6a4718",
            text="waiting for the game to draw…")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._tick()

    def _tick(self):
        self._job = None
        if self._closed:
            return
        data = self._io.tail_frame("spi0.cap", self._frame_bytes)
        if data:
            self._render(data)
        try:
            self._job = self.after(self._delay, self._tick)
        except tk.TclError:
            self._job = None

    def _image(self, frame):
        """The frame as a PIL image, in whichever shape this window draws."""
        from PIL import Image
        if self._alpha is not None:
            decode, render = self._alpha
            rows = decode(frame)
            if self._readouts:
                self._show_text(rows)
            return render(rows, scale=self.ALPHA_SCALE)
        grid = self._decode(frame)
        s = self._scale
        img = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        px = img.load()
        for y in range(self.HEIGHT):
            row = grid[y]
            for x in range(self.WIDTH):
                c = row[x] * 17
                px[x, y] = (c, int(c * 0.55), 0)
        return img.resize((self.WIDTH * s, self.HEIGHT * s), Image.NEAREST)

    def _show_text(self, rows):
        """Put the decoded characters in the readout labels."""
        for i, label in enumerate(self._readouts):
            digits = rows[i * 8:(i + 1) * 8]
            text = ""
            for segs in digits:
                pat = tuple(1 if v else 0 for v in segs)
                text += " " if not any(pat) else self._font.get(pat, "?")
            try:
                label.config(text=text)
            except tk.TclError:
                pass

    def _render(self, frame):
        try:
            from PIL import ImageTk
            img = self._image(frame)
        except Exception:                                      # noqa: BLE001
            return
        try:
            self._photo = ImageTk.PhotoImage(img)
            self._canvas.itemconfigure(self._placeholder, state="hidden")
            self._canvas.itemconfig(self._imgid, image=self._photo)
        except tk.TclError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        cb = self._on_close
        try:
            self.destroy()
        except tk.TclError:
            pass
        if cb:
            cb(self)


class Spike1SwitchWindow(tk.Toplevel):
    """The switch matrix / LEDs, in its own window.  Click a switch cell to
    inject a press (written to ``s1sw.input`` for the responder to read back);
    lamps and coils show their live colour once the node-bus decoder writes the
    state block."""

    def __init__(self, master, io, nodes=DEFAULT_NODES, cols=SWITCH_COLS,
                 hz=20, on_close=None):
        super().__init__(master)
        self._io = io
        self._nodes = list(nodes)
        self._cols = cols
        self._delay = max(30, int(1000 / hz))
        self._on_close = on_close
        self._state = HardwareState()
        self._injected = set()      # slots the user is holding closed (clicks)
        self._pulse_gen = {}        # slot -> generation, so overlapping click
                                    # pulses don't cut each other short
        self._keys_held = set()     # slots held via the flipper keys
        self._seq = 0
        self._cells = {}            # (kind, node, index) -> rect id
        self._job = None
        self._closed = False

        # the title's (node, index) -> name map, if the rig has it yet — it may
        # only arrive minutes from now (_refresh_names), so nothing here may
        # assume a nameless window stays nameless.
        self._names = io.read_switch_names() if io else {}
        self._base_cols = cols
        self._names_tick = 0
        if self._names:
            self._cols = self._cols_for(self._names)

        # keyboard rows: resolved from the title's own switch names (curated
        # switchmaps), so the bindings follow the game — the same keys the
        # Spike 2 playfield uses (padglhost.c binds[]): arrows for flippers,
        # 1 Start, 5 coin, T tilt, F shooter lane.  A row whose switch the map
        # does not name is drawn dim and stays inert.
        self._key_rows = self._resolve_key_rows()
        self._keys_held = set()     # slots held via the keyboard
        self._down = set()          # keysyms currently down (repeat dedupe)
        self._ball_state = {}
        self._ball_tick = 0

        self.title("Spike 1 — switches / LEDs")
        self.configure(bg=_tint(BG))
        self.geometry("+80+360")
        # play controls, matching the Spike 2 playfield's window actions:
        # Start and Plunge (plunge serves a ball first if the lane is empty),
        # plus the invisible-ball controls the Spike 1 keeper needs.
        bar = tk.Frame(self, bg=_tint(BG))
        bar.pack(side="top", fill="x", padx=PAD, pady=(4, 0))
        for label, cmd in (("Start", "start"), ("Plunge", "plunge"),
                           ("Drain", "drain"), ("Ball in", "ballin"),
                           ("Ball out", "ballout"), ("Coin", "coin 1")):
            tk.Button(bar, text=label, font=("Segoe UI", 9),
                      bg="#222", fg="#ddd", activebackground="#333",
                      activeforeground="#fff", relief="flat", bd=1,
                      highlightthickness=0, padx=8,
                      command=lambda c=cmd: self._ball_cmd(c)) \
                .pack(side="left", padx=(0, 6))
        # readout line: feedback for clicks and keeper commands.
        self._readout = tk.Label(
            self, bg=_tint(BG), fg=_tint(TEXT), anchor="w",
            font=("Segoe UI", 9),
            text=("click a switch to hold it, click again to release"
                  if self._names
                  else "(no switch names — start the game to load them)"))
        self._readout.pack(side="bottom", fill="x", padx=PAD, pady=(0, 4))
        body = tk.Frame(self, bg=_tint(BG))
        body.pack(side="top", fill="both", expand=True)
        # panel FIRST: pack grants space in order, so the key/service/ball
        # panel keeps its width and a wide switch area scrolls instead of
        # shoving it off the window.
        self._build_key_panel(body)
        grid = tk.Frame(body, bg=_tint(BG))
        grid.pack(side="left", fill="both", expand=True)
        self._canvas = tk.Canvas(grid, bg=self.PANEL_BG if self._names
                                 else _tint(BG), highlightthickness=0)
        self._hbar = tk.Scrollbar(grid, orient="horizontal",
                                  command=self._canvas.xview)
        self._canvas.configure(xscrollcommand=self._hbar.set)
        self._hbar.pack(side="bottom", fill="x")
        self._canvas.pack(side="top", fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self._canvas.bind("<Motion>", self._on_hover)
        self.bind_play_keys(self)
        self.protocol("WM_DELETE_WINDOW", self.close)
        # A curated title lists its switches BY NAME AND POSITION, in the
        # exact row style of the Spike 2 playfield's key panel (David: "the
        # giant matrix is not usable since I have to hover over items to see
        # what they are — list them out like we do on spike 2").  The raw
        # matrix grid survives only as the fallback for a nameless title.
        if self._names:
            self._build_list()
        else:
            self._build_grid()
        self._tick()

    def _switch_name(self, node, index):
        return self._names.get((node, index))

    def _cols_for(self, names):
        """Grid width for *names*: wide enough that every NAMED switch is
        visible (some sit past the default 16, e.g. GoT's shooter lane at index
        20), capped at 40 — not 32, because Ghostbusters' trough sits at
        indexes 32-38 — so it never balloons to a board's full 64 columns."""
        return max(self._base_cols, min(40, max(i for _, i in names) + 1))

    #: how often (in ticks) to look for the switch map.  On a title with no
    #: curated map the rig walks it out of the running game and drops it in
    #: minutes after this window opened, so "read it once at __init__" meant
    #: the names never arrived.  ~2s at the default 20 Hz.
    NAMES_EVERY = 40

    def _refresh_names(self):
        """Adopt a switch map that appeared (or changed) since the last look.

        Rebuilds the body — a named title gets the switch LIST, a nameless one
        the raw grid — and re-resolves the play keys IN PLACE, so the key
        panel's existing rows light up instead of having to be rebuilt."""
        names = self._io.read_switch_names() if self._io else {}
        if names == self._names:
            return False
        self._names = names
        if names:
            self._cols = self._cols_for(names)
        for row, fresh in zip(self._key_rows, self._resolve_key_rows()):
            row["slot"] = fresh["slot"]
        self._canvas.configure(bg=self.PANEL_BG if names else _tint(BG))
        self._canvas.delete("all")
        self._cells = {}
        if names:
            self._build_list()
        else:
            self._build_grid()
        self._readout.config(
            text=("click a switch to hold it, click again to release"
                  if names
                  else "(no switch names — start the game to load them)"))
        return True

    # ---- the switch LIST (curated titles) ----------------------------------
    # The Spike 2 key panel's row idiom, applied to every named switch: the
    # POSITION in the blue key column, the NAME beside it, inverse-video when
    # the game sees the switch made.  Sections per node, flowed into columns.

    def _build_list(self):
        import tkinter.font as tkfont
        f9 = tkfont.Font(family="Consolas", size=9)
        f9b = tkfont.Font(family="Consolas", size=9, weight="bold")
        f8 = tkfont.Font(family="Consolas", size=8)
        cv = self._canvas
        cv.delete("all")
        self._list_rows = []        # {slot, box, pos, name}
        self._list_hit = {}         # canvas item id -> row dict
        by_node = {}
        for (node, idx), name in sorted(self._names.items()):
            by_node.setdefault(node, []).append((idx, str(name)))
        posw = max([f9b.measure("%d,%d" % (n, i))
                    for n in by_node for i, _ in by_node[n]] + [30])
        namew = max([f9.measure(nm) for rows in by_node.values()
                     for _, nm in rows] + [60])
        pad = 10
        col_w = pad + posw + 8 + namew + 18
        total = sum(len(rows) + 1 for rows in by_node.values())
        ncols = 1 + (total > 22) + (total > 44)
        per_col = -(-total // ncols)                    # ceil
        top = 36
        col, line = 0, 0
        cv.create_text(pad, 16, anchor="w", fill=self.KEY_FG, font=f9b,
                       text="SWITCHES")
        cv.create_text(pad + 84, 16, anchor="w", fill="#777", font=f8,
                       text="click = pulse · right-click = hold/release · node,index")
        for node in sorted(by_node):
            rows = by_node[node]
            # a section header never sits alone at the bottom of a column
            if line + 2 > per_col and col < ncols - 1:
                col, line = col + 1, 0
            x0 = pad + col * col_w
            y = top + line * self.ROW_H
            cv.create_text(x0, y + 6, anchor="w", fill="#8a8a8a", font=f8,
                           text="NODE %d" % node)
            line += 1
            for idx, name in rows:
                if line + 1 > per_col and col < ncols - 1:
                    col, line = col + 1, 0
                    x0 = pad + col * col_w
                    y = top + line * self.ROW_H
                    cv.create_text(x0, y + 6, anchor="w", fill="#8a8a8a",
                                   font=f8, text="NODE %d (cont.)" % node)
                    line += 1
                y = top + line * self.ROW_H
                box = cv.create_rectangle(x0 - 4, y - 2, x0 + col_w - 10,
                                          y + self.ROW_H - 3,
                                          fill="", outline="")
                pos = cv.create_text(x0 + posw, y + 6, anchor="e",
                                     fill=self.KEY_FG, font=f9b,
                                     text="%d,%d" % (node, idx))
                nam = cv.create_text(x0 + posw + 8, y + 6, anchor="w",
                                     fill=self.LAB_FG, font=f9, text=name)
                row = {"slot": addr(node, idx), "node": node, "idx": idx,
                       "box": box, "pos": pos, "name": nam}
                self._list_rows.append(row)
                for item in (box, pos, nam):
                    self._list_hit[item] = row
                line += 1
        w = pad + ncols * col_w
        h = top + per_col * self.ROW_H + 12
        cv.config(width=min(w, 660), height=h, scrollregion=(0, 0, w, h))

    def _paint_list(self):
        try:
            for row in self._list_rows:
                slot = row["slot"]
                made = (self._state.get_switch(slot // 64, slot % 64)
                        or slot in self._injected or slot in self._keys_held)
                self._canvas.itemconfig(row["box"],
                                        fill=self.HIT_BG if made else "")
                self._canvas.itemconfig(
                    row["pos"], fill=self.HIT_FG if made else self.KEY_FG)
                self._canvas.itemconfig(
                    row["name"], fill=self.HIT_FG if made else self.LAB_FG)
        except tk.TclError:
            pass

    def _list_row_at(self, x, y):
        x = self._canvas.canvasx(x)
        y = self._canvas.canvasy(y)
        hit = self._canvas.find_closest(x, y)
        return self._list_hit.get(hit[0]) if hit else None

    # ---- play controls (layout + keys shared with the Spike 2 playfield) ----

    #: keysym -> (display key, row label, name matcher).  The KEYS are the
    #: Spike 2 playfield's (padglhost.c binds[]); the SWITCH each drives is
    #: resolved by NAME from the title's curated map.
    # The DMD generation names its flipper switches "L. FLIPPER BUTTON" (and
    # its end-of-stroke ones "LEFT FLIPPER E.O.S."); the 2012 home models just
    # "LEFT FLIPPER" / "LEFT FLIPPER EOS", and their start button "START".
    KEY_TABLE = (
        ("Left", "Left", "Left Flipper",
         lambda u: "FLIPPER" in u and "UP" not in u and "EOS" not in
         u.replace(".", "") and u.startswith("L")),
        ("Right", "Right", "Right Flipper",
         lambda u: "FLIPPER" in u and "UP" not in u and "EOS" not in
         u.replace(".", "") and u.startswith("R")),
        ("Up", "Up", "Upper Left Flipper",
         lambda u: "FLIPPER BUTTON" in u and "UP" in u and "L" in
         u.split("FLIPPER")[0]),
        ("1", "1", "Start Button", lambda u: u in ("START BUTTON", "START")),
        ("5", "5", "Left Coin", lambda u: "LEFT COIN" in u),
        ("t", "T", "Tilt Pendulum", lambda u: u.startswith("TILT")),
        ("f", "F", "Shooter Lane",
         lambda u: "SHOOTER" in u and "EXIT" not in u),
    )
    #: keysym -> service button name (keeper `svc` command).
    SVC_KEYS = {"Return": "select", "KP_Enter": "select", "equal": "plus",
                "minus": "minus", "BackSpace": "back", "Escape": "back"}
    #: the service cluster as drawn on the real coin door (David's reference
    #: photo, same as the Spike 2 panel): green BACK, red -/+, black SELECT.
    SVC_ORDER = (("back", "BACK", "Bksp/Esc", "#2e7d32"),
                 ("minus", "−", "-", "#c62828"),
                 ("plus", "+", "=", "#c62828"),
                 ("select", "SELECT", "Enter", "#1c1c1c"))

    def _resolve_key_rows(self):
        rows = []
        for keysym, key, label, match in self.KEY_TABLE:
            slot = None
            for (node, idx), name in self._names.items():
                if match(str(name).upper()):
                    slot = addr(node, idx)
                    break
            rows.append({"keysym": keysym, "key": key, "label": label,
                         "slot": slot})
        return rows

    def _write_injected(self):
        self._seq += 1
        self._io.write_injected(self._injected | self._keys_held, self._seq)

    def _ball_cmd(self, cmd):
        ok = self._io.append_ball_cmd(cmd)
        self._readout.config(
            text=("sent '%s' to the ball keeper" % cmd) if ok
            else "could not reach the ball keeper (is the game running?)")

    def press_key(self, keysym):
        """KeyPress dispatch.  Idempotent per held key — Windows auto-repeat
        delivers repeated KeyPress events while a key is held."""
        if keysym in self._down:
            return
        self._down.add(keysym)
        if keysym in self.SVC_KEYS:
            self._ball_cmd("svc " + self.SVC_KEYS[keysym])
            return
        if keysym in ("c", "C"):
            self._ball_cmd("door toggle")
            return
        if keysym in ("b", "B"):
            self._ball_cmd("trough toggle")
            return
        for row in self._key_rows:
            if row["keysym"] == keysym and row["slot"] is not None:
                self._keys_held.add(row["slot"])
                self._write_injected()
                return

    def release_key(self, keysym):
        self._down.discard(keysym)
        for row in self._key_rows:
            if row["keysym"] == keysym and row["slot"] in self._keys_held:
                self._keys_held.discard(row["slot"])
                self._write_injected()
                return

    def bind_play_keys(self, widget):
        """Bind the play keys on *widget* (this window, and — via
        Spike1Viewers — the DMD window, so either can have focus while
        playing)."""
        widget.bind("<KeyPress>",
                    lambda e: self.press_key(e.keysym), add="+")
        widget.bind("<KeyRelease>",
                    lambda e: self.release_key(e.keysym), add="+")

    # ---- the keyboard/service/ball panel (Spike 2 playfield conventions) ----
    PANEL_BG, KEY_FG, LAB_FG, PANEL_DIM = "#111", "#7ecbff", "#d8d8d8", "#555"
    HIT_BG, HIT_FG = "#e8e8e8", "#000"
    ROW_H = 17

    def _build_key_panel(self, parent):
        import tkinter.font as tkfont
        f9 = tkfont.Font(family="Consolas", size=9)
        f9b = tkfont.Font(family="Consolas", size=9, weight="bold")
        f8 = tkfont.Font(family="Consolas", size=8)
        self._pf8, self._pf9, self._pf9b = f8, f9, f9b
        w = 276
        rows_h = 44 + len(self._key_rows) * self.ROW_H + 10
        svc_h = 58
        door_h = 30
        trough_h = 46
        h = rows_h + svc_h + door_h + trough_h + 20
        cv = tk.Canvas(parent, width=w, height=h, bg=self.PANEL_BG,
                       highlightthickness=0)
        cv.pack(side="right", fill="y", padx=(6, 0))
        self._panel = cv
        self._panel_items = []
        x_key, x_lab = 12 + 46, 12 + 56
        y = 16
        cv.create_text(12, y, anchor="w", fill=self.KEY_FG, font=f9b,
                       text="KEYBOARD")
        y += 14
        cv.create_text(12, y, anchor="w", fill="#777", font=f8,
                       text="works in the DMD window")
        y += 14
        for row in self._key_rows:
            box = cv.create_rectangle(8, y - 1, w - 8, y + self.ROW_H - 3,
                                      fill="", outline="")
            fg = self.PANEL_DIM if row["slot"] is None else None
            key = cv.create_text(x_key, y + 6, anchor="e",
                                 fill=fg or self.KEY_FG, font=f9b,
                                 text=row["key"])
            lab = cv.create_text(x_lab, y + 6, anchor="w",
                                 fill=fg or self.LAB_FG, font=f9,
                                 text=row["label"])
            self._panel_items.append((row, box, key, lab))
            y += self.ROW_H
        # service cluster: clickable buttons, key labels beneath (one control
        # per action — the keys do not appear in the row list above).
        y += 8
        bw = (w - 24 - 3 * 6) // 4
        self._svc_items = []
        for i, (name, text, keylab, color) in enumerate(self.SVC_ORDER):
            x0 = 12 + i * (bw + 6)
            r = cv.create_rectangle(x0, y, x0 + bw, y + 24, fill=color,
                                    outline="#444")
            t = cv.create_text(x0 + bw / 2, y + 12, fill="#fff", font=f8,
                               text=text)
            cv.create_text(x0 + bw / 2, y + 33, fill=self.KEY_FG, font=f8,
                           text=keylab)
            for item in (r, t):
                cv.tag_bind(item, "<Button-1>",
                            lambda _e, n=name: self._ball_cmd("svc " + n))
            self._svc_items.append((name, r))
        y += svc_h
        # coin door bar: a click toggle, like the real door it stays put.
        self._door_rect = cv.create_rectangle(12, y, w - 12, y + 20,
                                              fill="#333", outline="#444")
        self._door_text = cv.create_text(w / 2, y + 10, fill=self.LAB_FG,
                                         font=f8, text="COIN DOOR")
        cv.create_text(w - 16, y + 10, anchor="e", fill=self.KEY_FG, font=f8,
                       text="C")
        for item in (self._door_rect, self._door_text):
            cv.tag_bind(item, "<Button-1>",
                        lambda _e: self._ball_cmd("door toggle"))
        y += door_h
        # the trough: clickable ball positions, fed by the keeper's state.
        cv.create_text(12, y + 6, anchor="w", fill=self.LAB_FG, font=f9b,
                       text="BALLS")
        cv.create_text(58, y + 6, anchor="w", fill=self.KEY_FG, font=f8,
                       text="B")
        self._ball_items = []
        for i in range(6):
            x0 = 12 + i * 26
            b = cv.create_oval(x0, y + 16, x0 + 18, y + 34, fill="#222",
                               outline="#555")
            cv.tag_bind(b, "<Button-1>",
                        lambda _e, k=i: self._ball_click(k))
            self._ball_items.append(b)

    def _ball_click(self, i):
        """Fill the trough up to ball *i*, or empty it back down to it —
        the Spike 2 trough panel's click semantics, via the keeper."""
        balls = int(self._ball_state.get("balls", 0))
        self._ball_cmd("trough %d" % (i if balls > i else i + 1))

    def _paint_panel(self):
        if not hasattr(self, "_panel"):
            return
        try:
            for row, box, key, lab in self._panel_items:
                slot = row["slot"]
                made = False
                if slot is not None:
                    made = (self._state.get_switch(slot // 64, slot % 64)
                            or slot in self._keys_held
                            or slot in self._injected)
                self._panel.itemconfig(
                    box, fill=self.HIT_BG if made else "")
                if slot is not None:
                    self._panel.itemconfig(
                        key, fill=self.HIT_FG if made else self.KEY_FG)
                    self._panel.itemconfig(
                        lab, fill=self.HIT_FG if made else self.LAB_FG)
            st = self._ball_state
            door_closed = bool(st.get("door_closed", True))
            self._panel.itemconfig(self._door_rect,
                                   fill="#2e5e2e" if door_closed else "#5e2e2e")
            self._panel.itemconfig(
                self._door_text,
                text="COIN DOOR CLOSED" if door_closed else "COIN DOOR OPEN")
            balls = int(st.get("balls", 0))
            nballs = int(st.get("nballs", 6)) or 6
            in_shooter = bool(st.get("in_shooter"))
            for i, item in enumerate(self._ball_items):
                if i >= nballs:
                    self._panel.itemconfig(item, fill="", outline="")
                elif i < balls:
                    self._panel.itemconfig(item, fill="#d8d8d8",
                                           outline="#ffffff")
                else:
                    self._panel.itemconfig(item, fill="#222", outline="#555")
            # the ball in the shooter lane rides the last position's outline
            if in_shooter and self._ball_items:
                self._panel.itemconfig(self._ball_items[min(balls, 5)],
                                       fill="#7ecbff", outline="#ffffff")
        except tk.TclError:
            pass

    # ---- layout ----
    def _visible_nodes(self):
        live = set()
        for node in range(MAX_NODES):
            base = node * MAX_INDEX
            if (any(self._state.switches[base:base + MAX_INDEX])
                    or any(self._state.coils[base:base + MAX_INDEX])
                    or any(self._state.lamps[base * 3:(base + MAX_INDEX) * 3])):
                live.add(node)
        return sorted(set(self._nodes) | live)

    def _sections(self):
        """The switch section is always shown; lamp/coil sections appear only
        once the node-bus decoder writes them (empty rows are just wasted height
        — the window is tall enough with one section per node as it is)."""
        secs = [("sw", "Switch matrix — click to inject")]
        if any(self._state.lamps):
            secs.append(("lamp", "Lamps / LEDs"))
        if any(self._state.coils):
            secs.append(("coil", "Coils"))
        return secs

    def _build_grid(self):
        self._canvas.delete("all")
        self._cells.clear()
        nodes = self._visible_nodes()
        sections = self._sections()
        title_h = 18
        rows = len(nodes)
        sec_w = LABEL_W + self._cols * (CELL + PAD) + PAD
        sec_h = rows * (CELL + PAD) + PAD
        y = PAD
        for kind, label in sections:
            self._canvas.create_text(PAD, y, anchor="nw", fill=_tint(TEXT),
                                     text=label,
                                     font=("Segoe UI", 9, "bold"))
            gy = y + title_h
            for r, node in enumerate(nodes):
                cy = gy + r * (CELL + PAD) + PAD
                self._canvas.create_text(PAD, cy + CELL / 2, anchor="w",
                                         fill=_tint(DIM), text="node %d" % node)
                for c in range(self._cols):
                    cx = LABEL_W + c * (CELL + PAD) + PAD
                    named = kind == "sw" and (node, c) in self._names
                    rid = self._canvas.create_rectangle(
                        cx, cy, cx + CELL, cy + CELL,
                        fill=_tint(SW_OPEN),
                        outline=_tint(NAMED if named else GRID),
                        width=2 if named else 1)
                    self._cells[(kind, node, c)] = rid
            y = gy + sec_h + SECTION_GAP
        full_w = sec_w + 2 * PAD
        # request at most ~28 columns of width (fits a 1024-wide screen with
        # the key panel); wider titles scroll on the bar under the grid.
        self._canvas.config(width=min(full_w, LABEL_W + 28 * (CELL + PAD)),
                            height=y, scrollregion=(0, 0, full_w, y))
        self._visible_cache = nodes
        self._sections_cache = sections

    def _paint(self):
        for (kind, node, c), rid in self._cells.items():
            if kind == "sw":
                closed = (self._state.get_switch(node, c)
                          or addr(node, c) in self._injected
                          or addr(node, c) in self._keys_held)
                col = SW_CLOSED if closed else SW_OPEN
            elif kind == "lamp":
                r, g, b = self._state.get_lamp(node, c)
                col = (r, g, b) if (r or g or b) else SW_OPEN
            else:
                col = COIL_ON if self._state.get_coil(node, c) else COIL_OFF
            try:
                self._canvas.itemconfig(rid, fill=_tint(col))
            except tk.TclError:
                return

    def _cell_at(self, x, y):
        """The (kind, node, index) of the cell under a canvas point, or None."""
        x = self._canvas.canvasx(x)
        y = self._canvas.canvasy(y)
        hit = self._canvas.find_closest(x, y)
        if not hit:
            return None
        for key, cid in self._cells.items():
            if cid == hit[0]:
                return key
        return None

    def _describe(self, node, index, prefix=""):
        name = self._switch_name(node, index)
        tail = " — %s" % name if name else " — (unassigned)"
        self._readout.config(text="%snode %d · index %d%s"
                             % (prefix, node, index, tail))

    #: how long a clicked switch stays closed — a ball rolling over it,
    #: roughly, and comfortably past the game's 2-scan debounce.
    PULSE_S = 0.35

    def _pulse_slot(self, node, c):
        """A left click closes the switch MOMENTARILY, the way a ball would
        hit it (David: "clicking … should only activate it momentarily, not
        hold it indefinitely").  A switch that must stay closed is held with
        right-click (:meth:`_toggle_slot`) instead."""
        slot = addr(node, c)
        gen = self._pulse_gen.get(slot, 0) + 1
        self._pulse_gen[slot] = gen
        self._injected.add(slot)
        self._write_injected()
        self._describe(node, c, prefix="pulsed ")
        self._repaint_switches()

        def release():
            if self._closed or self._pulse_gen.get(slot) != gen:
                return          # a newer pulse (or a hold) owns the slot now
            self._injected.discard(slot)
            try:
                self._write_injected()
                self._repaint_switches()
            except tk.TclError:
                pass
        self.after(int(self.PULSE_S * 1000), release)

    def _toggle_slot(self, node, c):
        slot = addr(node, c)
        # a hold takes the slot over from any in-flight pulse release
        self._pulse_gen[slot] = self._pulse_gen.get(slot, 0) + 1
        if slot in self._injected:
            self._injected.discard(slot)
            verb = "released "
        else:
            self._injected.add(slot)
            verb = "held "
        self._write_injected()
        self._describe(node, c, prefix=verb)

    def _repaint_switches(self):
        if self._names:
            self._paint_list()
        else:
            self._paint()

    def _on_hover(self, ev):
        if self._names:
            row = self._list_row_at(ev.x, ev.y)
            if row:
                self._describe(row["node"], row["idx"])
            return
        key = self._cell_at(ev.x, ev.y)
        if key and key[0] == "sw":
            self._describe(key[1], key[2])

    def _slot_at_event(self, ev):
        if self._names:
            row = self._list_row_at(ev.x, ev.y)
            return (row["node"], row["idx"]) if row else None
        key = self._cell_at(ev.x, ev.y)
        return (key[1], key[2]) if key and key[0] == "sw" else None

    def _on_click(self, ev):
        hit = self._slot_at_event(ev)
        if hit:
            self._pulse_slot(*hit)

    def _on_right_click(self, ev):
        hit = self._slot_at_event(ev)
        if hit:
            self._toggle_slot(*hit)
            self._repaint_switches()

    def _tick(self):
        self._job = None
        if self._closed:
            return
        self._state = self._io.read_state()
        # the keeper's state file changes rarely; every 3rd tick keeps the
        # UNC round-trips off the paint path.
        self._ball_tick += 1
        if self._ball_tick % 3 == 1 and hasattr(self._io, "read_ball_state"):
            self._ball_state = self._io.read_ball_state() or self._ball_state
        # the map can arrive (or change) long after this window opened
        self._names_tick += 1
        if self._names_tick % self.NAMES_EVERY == 0:
            self._refresh_names()
        if self._names:
            self._paint_list()
        else:
            if (self._visible_nodes() != getattr(self, "_visible_cache", None)
                    or self._sections() != getattr(self,
                                                   "_sections_cache", None)):
                self._build_grid()
            self._paint()
        self._paint_panel()
        try:
            self._job = self.after(self._delay, self._tick)
        except tk.TclError:
            self._job = None

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        cb = self._on_close
        try:
            self.destroy()
        except tk.TclError:
            pass
        if cb:
            cb(self)


class Spike1Viewers:
    """Owns the DMD + switch windows for a run and keeps them in step with it.

    The tab calls :meth:`open` when the game comes up, :meth:`reset` for the
    "Reset windows" button, and :meth:`close` on Stop / quit.  Everything is
    best-effort: a viewer that will not open (no Pillow, no UNC) must never take
    the emulator down with it.
    """

    def __init__(self, master_fn, decode_frame, log=None, alpha=None):
        #: returns the Tk widget the windows parent to (the app toplevel).
        self._master_fn = master_fn
        self._decode = decode_frame
        #: ``(decode_frame, render_image)`` for the alphanumeric displays of
        #: the 2012 home models; used when the run dir's ``s1display`` says so.
        self._alpha = alpha
        self._log = log or (lambda _m: None)
        self._io = None
        self._dmd = None
        #: which kind of display window is up ("dmd" / "alpha"), so a change
        #: of era swaps it instead of leaving the wrong one on screen
        self._dmd_mode = None
        self._sw = None

    def configure(self, run_dir_wsl, distro):
        self._io = _RunDirIO(run_dir_wsl, distro)

    def _alive(self, w):
        try:
            return w is not None and not w._closed and w.winfo_exists()
        except tk.TclError:
            return False

    def display_mode(self):
        """``"alpha"`` when the run dir says this machine has the 16-segment
        displays, else ``"dmd"``.  Read on every poll, because the rig only
        writes ``s1display`` once the game is extracted — which is AFTER this
        window first opens."""
        if self._alpha is None or not hasattr(self._io, "read_text"):
            return "dmd"
        return "alpha" if self._io.read_text("s1display") == "alphanumeric" \
            else "dmd"

    def _sweep_orphans(self, master):
        """Close display/switch windows nobody owns any more.

        The panel is rebuilt when the era badges switch, and the new panel
        starts with a fresh Spike1Viewers — so the previous one's windows are
        left on screen with no reference to close them (David saw the stale
        orange DMD window sitting behind the new red one)."""
        mine = {id(self._dmd), id(self._sw)}
        try:
            children = list(master.winfo_children())
        except tk.TclError:
            return
        for w in children:
            if id(w) in mine:
                continue
            if isinstance(w, (Spike1DisplayWindow, Spike1SwitchWindow)):
                try:
                    w.close()
                except tk.TclError:
                    pass

    def open(self):
        """Open whichever windows are not already up.  Idempotent — a running
        game calls this on every status poll."""
        if self._io is None or sys.platform != "win32":
            return
        master = self._master_fn()
        if master is None:
            return
        self._sweep_orphans(master)
        want = self.display_mode()
        if self._alive(self._dmd) and self._dmd_mode != want:
            # The machine turned out to be the other kind of display.  A DMD
            # window fed this era's 256-byte frames reads eight of them as one
            # 2048-byte frame and draws stripes, so replace it rather than
            # leaving it up (PAD-101).
            try:
                self._dmd.close()
            except tk.TclError:
                pass
            self._dmd = None
        if not self._alive(self._dmd):
            try:
                self._dmd = Spike1DisplayWindow(
                    master, self._io, self._decode,
                    alpha=self._alpha if want == "alpha" else None,
                    on_close=lambda _w: setattr(self, "_dmd", None))
                self._dmd_mode = want
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: could not open the display window: %s" % exc)
                self._dmd = None
        if not self._alive(self._sw):
            try:
                self._sw = Spike1SwitchWindow(
                    master, self._io,
                    on_close=lambda _w: setattr(self, "_sw", None))
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: could not open the switch window: %s" % exc)
                self._sw = None
        # the play keys work from the DMD window too (play while watching
        # it): forward its key press/release to the switch window's handlers.
        if self._alive(self._dmd) and self._alive(self._sw):
            try:
                self._sw.bind_play_keys(self._dmd)
            except tk.TclError:
                pass

    def reset(self):
        """Reopen the windows and pull them back on-screen (the escape hatch for
        one dragged to a monitor that went away)."""
        for w, geo in ((self._dmd, "+80+80"), (self._sw, "+80+360")):
            if self._alive(w):
                try:
                    w.geometry(geo)
                    w.deiconify()
                    w.lift()
                except tk.TclError:
                    pass
        self.open()

    def close(self):
        for attr in ("_dmd", "_sw"):
            w = getattr(self, attr, None)
            if self._alive(w):
                try:
                    w.close()
                except tk.TclError:
                    pass
            setattr(self, attr, None)
