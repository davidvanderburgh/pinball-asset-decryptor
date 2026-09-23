"""The Spike 1 emulator's display and switch / LED panel, for the web page.

The Tk app opened these as two native windows (``Spike1DisplayWindow`` and
``Spike1SwitchWindow``, deleted with the Tk UI; their tables are below).  The web app does too
(:class:`ViewWindows`: two more pywebview windows on the view page
``static/js/tabs/emulate_spike1_view.html``), so they stay up whichever tab
or manufacturer is on screen, can go to a second monitor and are sized apart
from the main window.  Where there is no native window to open (``--browser``,
``--serve``) they are two cards on the Emulate tab instead.  Either way they
are fed the same way: the emulator's run-dir files are read straight off the
WSL disk over the ``\\\\wsl.localhost`` UNC path (``_RunDirIO``, the Tk
windows' own reader, now in ``emulate_spike1_core``), so a frame is a plain file read with no ``wsl.exe``
per frame.

* :class:`DisplayFeed` - the newest whole frame of ``spi0.cap``, drawn the
  way the Tk window drew it (amber dots for the 128x32 DMD; the 2012 home
  models' two 8-digit 16-segment displays through ``s1alpha``), as a PNG
  the page scales with ``image-rendering: pixelated`` (= Tk's NEAREST).
* :class:`SwitchModel` - the switch window's state and actions: clicks
  pulse / hold a switch (``s1sw.input``), the play keys, the service
  cluster, the coin door and the trough (``s1ball.cmd``), and the readout.
* :class:`ViewWindows` - the two native windows (Tk's ``Spike1Viewers``).

The feeds are read by the page with ``@rpc(loop=False)`` calls while a game
runs, so a 20 Hz display never floods the event stream.
"""

import base64
import functools
import hashlib
import io as _io
import logging
import threading
from urllib.parse import quote, urlsplit

from . import winbrand
from .emulate_spike1_core import DEFAULT_NODES, SWITCH_COLS
from ..plugins.stern.spike1_emulate import (MAX_INDEX, MAX_NODES,
                                            HardwareState, addr)

log = logging.getLogger(__name__)

#: The Tk switch window's tables (``Spike1SwitchWindow``, word for word;
#: the keys are the Spike 2 playfield's).

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

#: how long a clicked switch stays closed — a ball rolling over it,
#: roughly, and comfortably past the game's 2-scan debounce.
PULSE_S = 0.35


def _png_data_url(img):
    buf = _io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class DisplayFeed:
    """Tails ``spi0.cap`` and renders the newest frame (the Tk display
    window's ``_tick`` / ``_image`` / ``_show_text``)."""

    FRAME_BYTES = 2048
    WIDTH = 128
    HEIGHT = 32
    #: glyph scale for the 16-segment displays (the default 6 drew a window
    #: barely 300 px wide, which is what "completely unusable" was about)
    ALPHA_SCALE = 9
    #: the machine labels its two displays; so do we, under the right one
    ALPHA_LABELS = ("PLAYER 1", "PLAYER 2")

    def __init__(self, io, decode_frame, alpha=None):
        self._io = io
        self._decode = decode_frame
        self._alpha = alpha
        self._mode = "dmd"
        self._font = None
        self._lock = threading.Lock()

    @property
    def mode(self):
        return self._mode

    def set_mode(self, mode):
        """``"alpha"`` (the 16-segment displays) or ``"dmd"``; the font for
        the alpha readouts is the game's own, dumped by the rig."""
        mode = "alpha" if (mode == "alpha" and self._alpha is not None) \
            else "dmd"
        with self._lock:
            if mode == self._mode:
                return
            self._mode = mode
            self._font = None
            if mode == "alpha":
                raw = self._io.read_json("s1font.json") \
                    if hasattr(self._io, "read_json") else None
                if raw:
                    self._font = {tuple(int(c) for c in k): v
                                  for k, v in raw.items() if len(k) == 16}

    def frame(self, since=""):
        """The newest frame as ``{"sig", "mode", "png", "text"}``; only
        ``{"sig"}`` when it is the frame the page already shows; None when
        the game has drawn nothing yet."""
        with self._lock:
            mode, font = self._mode, self._font
        nbytes = 256 if mode == "alpha" else self.FRAME_BYTES
        data = self._io.tail_frame("spi0.cap", nbytes)
        if not data:
            return None
        sig = mode + ":" + hashlib.blake2b(data, digest_size=8).hexdigest()
        if sig == since:
            return {"sig": sig}
        try:
            img, text = self._image(data, mode, font)
        except Exception:                              # noqa: BLE001
            return None
        return {"sig": sig, "mode": mode, "png": _png_data_url(img),
                "w": img.size[0], "h": img.size[1], "text": text,
                "labels": list(self.ALPHA_LABELS) if mode == "alpha" else []}

    def _image(self, frame, mode, font):
        from PIL import Image
        if mode == "alpha":
            decode, render = self._alpha
            rows = decode(frame)
            text = None
            if font:
                text = []
                for i in range(len(self.ALPHA_LABELS)):
                    digits = rows[i * 8:(i + 1) * 8]
                    t = ""
                    for segs in digits:
                        pat = tuple(1 if v else 0 for v in segs)
                        t += " " if not any(pat) else font.get(pat, "?")
                    text.append(t)
            return render(rows, scale=self.ALPHA_SCALE), text
        grid = self._decode(frame)
        img = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        px = img.load()
        for y in range(self.HEIGHT):
            row = grid[y]
            for x in range(self.WIDTH):
                c = row[x] * 17
                px[x, y] = (c, int(c * 0.55), 0)
        return img, None


class SwitchModel:
    """The switch window's state, without the window (the page draws it).

    ``post(fn, *args)`` runs on the UI loop; ``after(ms, fn)`` schedules on
    it; ``on_change(**state)`` publishes what the page shows (the readout,
    the names, the key rows)."""

    NAMES_EVERY = 1        # refreshed from the status poll (every ~2 s)

    def __init__(self, io, after, on_change, cols=SWITCH_COLS,
                 nodes=DEFAULT_NODES):
        self._io = io
        self._after = after
        self._on_change = on_change
        self._lock = threading.RLock()
        self._nodes = list(nodes)
        self._base_cols = cols
        self._cols = cols
        self._state = HardwareState()
        self._injected = set()
        self._pulse_gen = {}
        self._keys_held = set()
        self._down = set()
        self._seq = 0
        self._ball_state = {}
        self._ball_tick = 0
        self._closed = False
        self._era = io.read_text("s1era") if hasattr(io, "read_text") else ""
        self._names = io.read_switch_names() if io else {}
        if self._names:
            self._cols = self._cols_for(self._names)
        self._key_rows = self._resolve_key_rows()
        self._readout = ("click a switch to hold it, click again to release"
                         if self._names
                         else "(no switch names — start the game to load them)")
        self._publish()

    # -- what the page shows ---------------------------------------------
    def page_state(self):
        with self._lock:
            names = [{"node": n, "idx": i, "name": str(nm),
                      "slot": addr(n, i)}
                     for (n, i), nm in sorted(self._names.items())]
            return {
                "era": self._era or "",
                "early": self._era == "early",
                "names": names,
                "cols": self._cols,
                "key_rows": [dict(r) for r in self._key_rows],
                "svc": [{"name": n, "text": t, "key": k, "color": c}
                        for n, t, k, c in SVC_ORDER],
                "readout": self._readout,
            }

    def _publish(self):
        try:
            self._on_change(self.page_state())
        except Exception:                              # noqa: BLE001
            pass

    def _set_readout(self, text):
        with self._lock:
            self._readout = text
        self._publish()

    def close(self):
        self._closed = True

    # -- names -------------------------------------------------------------
    def _cols_for(self, names):
        return max(self._base_cols, min(40, max(i for _, i in names) + 1))

    def _resolve_key_rows(self):
        rows = []
        for keysym, key, label, match in KEY_TABLE:
            slot = None
            for (node, idx), name in self._names.items():
                if match(str(name).upper()):
                    slot = addr(node, idx)
                    break
            rows.append({"keysym": keysym, "key": key, "label": label,
                         "slot": slot})
        return rows

    def refresh_names(self, names=None):
        """Adopt a switch map that appeared (or changed) since the last look
        (a title with no curated map gets its names minutes into the boot).
        ``names`` is the map already read off the loop, or None to read it."""
        if names is None:
            names = self._io.read_switch_names() if self._io else {}
        with self._lock:
            if names == self._names:
                return False
            self._names = names
            if names:
                self._cols = self._cols_for(names)
            for row, fresh in zip(self._key_rows, self._resolve_key_rows()):
                row["slot"] = fresh["slot"]
            self._readout = (
                "click a switch to hold it, click again to release" if names
                else "(no switch names — start the game to load them)")
        self._publish()
        return True

    # -- live state (read by the page) -------------------------------------
    def _visible_nodes(self):
        live = set()
        st = self._state
        for node in range(MAX_NODES):
            base = node * MAX_INDEX
            if (any(st.switches[base:base + MAX_INDEX])
                    or any(st.coils[base:base + MAX_INDEX])
                    or any(st.lamps[base * 3:(base + MAX_INDEX) * 3])):
                live.add(node)
        return sorted(set(self._nodes) | live)

    def _sections(self):
        secs = [("sw", "Switch matrix — click to inject")]
        if any(self._state.lamps):
            secs.append(("lamp", "Lamps / LEDs"))
        if any(self._state.coils):
            secs.append(("coil", "Coils"))
        return secs

    def snapshot(self):
        """Read the shared state block (and, every 3rd call, the keeper's
        state) and return what the page paints."""
        st = self._io.read_state()
        with self._lock:
            self._state = st
            self._ball_tick += 1
            if self._ball_tick % 3 == 1 and hasattr(self._io,
                                                    "read_ball_state"):
                self._ball_state = self._io.read_ball_state() or \
                    self._ball_state
            made = {i for i, v in enumerate(st.switches) if v}
            made |= self._injected | self._keys_held
            lamps = {}
            for slot in range(len(st.lamps) // 3):
                r, g, b = st.lamps[slot * 3:slot * 3 + 3]
                if r or g or b:
                    lamps[str(slot)] = "#%02x%02x%02x" % (r, g, b)
            coils = [i for i, v in enumerate(st.coils) if v]
            ball = dict(self._ball_state)
            return {
                "made": sorted(made),
                "lamps": lamps,
                "coils": coils,
                "ball": {"balls": int(ball.get("balls", 0) or 0),
                         "nballs": int(ball.get("nballs", 6) or 6),
                         "in_shooter": bool(ball.get("in_shooter")),
                         "door_closed": bool(ball.get("door_closed", True))},
                "nodes": self._visible_nodes(),
                "sections": [list(s) for s in self._sections()],
            }

    # -- actions (on the UI loop) ------------------------------------------
    def _write_injected(self):
        with self._lock:
            self._seq += 1
            slots, seq = self._injected | self._keys_held, self._seq
        self._io.write_injected(slots, seq)

    def ball_cmd(self, cmd):
        ok = self._io.append_ball_cmd(cmd)
        self._set_readout(("sent '%s' to the ball keeper" % cmd) if ok
                          else "could not reach the ball keeper (is the game "
                               "running?)")
        return ok

    def press_key(self, keysym):
        """KeyPress dispatch; idempotent per held key (auto-repeat)."""
        if keysym in self._down:
            return
        self._down.add(keysym)
        if self._era != "early":       # that machine has neither
            if keysym in SVC_KEYS:
                self.ball_cmd("svc " + SVC_KEYS[keysym])
                return
            if keysym in ("c", "C"):
                self.ball_cmd("door toggle")
                return
        if keysym in ("b", "B"):
            self.ball_cmd("trough toggle")
            return
        for row in self._key_rows:
            if row["keysym"] == keysym and row["slot"] is not None:
                with self._lock:
                    self._keys_held.add(row["slot"])
                self._write_injected()
                return

    def release_key(self, keysym):
        self._down.discard(keysym)
        for row in self._key_rows:
            if row["keysym"] == keysym and row["slot"] in self._keys_held:
                with self._lock:
                    self._keys_held.discard(row["slot"])
                self._write_injected()
                return

    def release_all_keys(self):
        """The page lost focus with keys down: let them all go."""
        for keysym in list(self._down):
            self.release_key(keysym)
        self._down.clear()

    def ball_click(self, i):
        """Fill the trough up to ball *i*, or empty it back down to it."""
        balls = int(self._ball_state.get("balls", 0) or 0)
        return self.ball_cmd("trough %d" % (i if balls > i else i + 1))

    def _describe(self, node, index, prefix=""):
        name = self._names.get((node, index))
        tail = " — %s" % name if name else " — (unassigned)"
        self._set_readout("%snode %d · index %d%s" % (prefix, node, index,
                                                       tail))

    def pulse(self, node, c):
        """A click closes the switch MOMENTARILY, the way a ball would hit
        it; right-click holds it (:meth:`toggle`)."""
        slot = addr(node, c)
        with self._lock:
            gen = self._pulse_gen.get(slot, 0) + 1
            self._pulse_gen[slot] = gen
            self._injected.add(slot)
        self._write_injected()
        self._describe(node, c, prefix="pulsed ")

        def release():
            if self._closed or self._pulse_gen.get(slot) != gen:
                return          # a newer pulse (or a hold) owns the slot now
            with self._lock:
                self._injected.discard(slot)
            self._write_injected()
        self._after(int(PULSE_S * 1000), release)

    def toggle(self, node, c):
        slot = addr(node, c)
        with self._lock:
            self._pulse_gen[slot] = self._pulse_gen.get(slot, 0) + 1
            if slot in self._injected:
                self._injected.discard(slot)
                verb = "released "
            else:
                self._injected.add(slot)
                verb = "held "
        self._write_injected()
        self._describe(node, c, prefix=verb)


class ViewWindows:
    """The display and the switch / LED panel in their OWN native windows,
    as the Tk app had them (``Spike1Viewers``): up whichever tab or
    manufacturer shows, movable to another monitor, closed with the run.

    ``available()`` is False without a native main window (``--browser``,
    ``--serve``, the tests); the tab then draws the two cards in the page.

    Every pywebview call is made on this object's own thread, never on the UI
    loop: pywebview marshals a window call onto its GUI thread and waits, and
    at quit that thread sits in the main window's closing handler waiting for
    the UI loop - a window call made from the loop then would hang the quit.
    Requests only record what is wanted (the latest wins); the thread brings
    the windows in line."""

    PAGE = "/static/js/tabs/emulate_spike1_view.html"
    #: Tk's places (Spike1Viewers.reset): the display at +80+80, the switch
    #: panel under it at +80+360
    PLACE = {"display": (80, 80), "switches": (80, 360)}
    TITLES = {"dmd": "Spike 1 — DMD", "alpha": "Spike 1 — display",
              "switches": "Spike 1 — switches / LEDs"}
    #: outer sizes: the Tk DMD canvas was 128x32 at scale 7 (896x224) inside
    #: an 8 px margin; the 16-segment pair renders 870x78 at ALPHA_SCALE with
    #: the PLAYER 1 / 2 readouts under it
    SIZES = {"dmd": (940, 300), "alpha": (920, 250), "switches": (1000, 640)}
    MIN_SIZE = (360, 160)

    def __init__(self, ctx, log_line=None):
        self._ctx = ctx
        self._log_line = log_line or (lambda _m: None)
        self._cv = threading.Condition()
        self._want = None           # None: no windows; else (mode|None, bool)
        self._reset = False
        self._dirty = False
        self._shut = False
        self._thread = None
        self._lock = threading.Lock()
        self._wins = {}             # "display" | "switches" -> pywebview Window
        self._mode = None           # the display window's kind (dmd | alpha)
        #: a window would not open: the tab's cards stand in for the rest of
        #: the session rather than a window that never comes
        self._broken = False

    # -- asked on the UI loop ----------------------------------------------
    def _host(self):
        return getattr(self._ctx, "host", None)

    def _origin(self):
        win = getattr(self._host(), "window", None)
        url = getattr(win, "original_url", None) or ""
        try:
            parts = urlsplit(url)
        except ValueError:
            return ""
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return ""
        return "%s://%s" % (parts.scheme, parts.netloc)

    def available(self):
        """True when this session has a native main window to open more
        windows beside."""
        if self._shut or self._broken:
            return False
        host = self._host()
        if host is None or getattr(host, "mode", "") != "native" or \
                getattr(host, "quitting", False):
            return False
        return bool(self._origin())

    def show(self, display_mode, switches=True, reset=False):
        """Want the display (``"dmd"`` / ``"alpha"``, or None for no display
        window) and the switch panel up.  Idempotent: a running game asks on
        every poll, which also reopens one the user closed (as Tk's did).
        ``reset`` puts them back at their places and in front."""
        self._request((display_mode, bool(switches)), reset)

    def close(self):
        self._request(None)

    def shutdown(self):
        """App quit: close them and open nothing more.  Never waits."""
        self._shut = True
        self._request(None)

    def is_open(self, kind):
        with self._lock:
            return kind in self._wins

    def _request(self, want, reset=False):
        with self._cv:
            self._want = want
            self._reset = self._reset or reset
            self._dirty = True
            if self._thread is None and want is not None:
                self._thread = threading.Thread(
                    target=self._run, name="pad-s1-windows", daemon=True)
                self._thread.start()
            self._cv.notify()

    # -- this object's thread ------------------------------------------------
    def _run(self):
        while True:
            with self._cv:
                while not self._dirty:
                    self._cv.wait()
                self._dirty = False
                want, reset = self._want, self._reset
                self._reset = False
            try:
                self._bring_in_line(want, reset)
            except Exception:                          # noqa: BLE001
                log.exception("the Spike 1 view windows")

    def _bring_in_line(self, want, reset):
        with self._lock:
            wins = dict(self._wins)
            mode_now = self._mode
        if want is None or not self.available():
            for kind, win in wins.items():
                self._destroy(kind, win)
            return
        mode, switches = want
        disp = wins.get("display")
        if disp is not None and (mode is None or mode_now != mode):
            # the machine turned out to be the other kind of display: a new
            # window of the right size, as Tk replaced its window (PAD-101)
            self._destroy("display", disp)
            wins.pop("display")
            disp = None
        if reset:
            for kind, win in wins.items():
                self._place(kind, win)
        if mode is not None and disp is None:
            self._open("display", mode)
        if switches and "switches" not in wins:
            self._open("switches", None)
        elif not switches and "switches" in wins:
            self._destroy("switches", wins["switches"])

    def _open(self, kind, mode):
        import webview
        origin = self._origin()
        if not origin or self._shut:
            return
        size_key = mode if kind == "display" else "switches"
        width, height = self.SIZES[size_key]
        x, y = self.PLACE[kind]
        theme = self._ctx.store.get("shell", "theme")
        bg = "#000000" if kind == "display" else (
            "#f4f4f1" if theme == "light" else "#15171a")
        url = "%s%s?t=%s&view=%s" % (origin, self.PAGE,
                                     quote(self._ctx.token or ""), kind)
        try:
            win = webview.create_window(
                self.TITLES[size_key], url, width=width, height=height,
                x=x, y=y, min_size=self.MIN_SIZE, background_color=bg)
        except Exception as exc:                       # noqa: BLE001
            # Tk's words; the tab shows the cards from the next poll on
            self._broken = True
            self._log_line("Spike 1: could not open the %s window: %s — "
                           "the display and switches are on the Emulate tab "
                           "instead." % ("display" if kind == "display"
                                         else "switch", exc))
            return
        if win is None:
            return
        # a taskbar button and icon of its own, not a second PAD one: the
        # DMD backbox for the display, the playfield for the switch panel
        if kind == "display":
            winbrand.brand(win, "dmdwin", winbrand.GAME_SCREEN)
        else:
            winbrand.brand(win, "playfield", winbrand.PLAYFIELD)
        win.events.closed += functools.partial(self._closed, kind, win)
        with self._lock:
            self._wins[kind] = win
            if kind == "display":
                self._mode = mode

    def _closed(self, kind, win):
        """The window went (the user closed it, or we did)."""
        with self._lock:
            if self._wins.get(kind) is win:
                del self._wins[kind]

    def _destroy(self, kind, win):
        with self._lock:
            if self._wins.get(kind) is win:
                del self._wins[kind]
        try:
            win.destroy()
        except Exception:                              # noqa: BLE001
            pass

    def _place(self, kind, win):
        """Back on-screen at its place, restored and in front (the escape
        hatch for a window on a monitor that went away)."""
        x, y = self.PLACE[kind]
        for step in (win.restore, lambda: win.move(x, y), win.show):
            try:
                step()
            except Exception:                          # noqa: BLE001
                pass
