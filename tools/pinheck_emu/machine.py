"""A pinHeck game running in real time, for a window to drive (PAD-320).

``Machine`` boots a game (``run.boot`` with its balls, screen and sound) and
runs it on a thread of its own, paced to the wall clock. Everything the
player does - switches, buttons, balls, pause - is queued and applied by
that thread between emulated milliseconds, so the CPU is never touched from
two threads. ``frame()`` and ``status()`` are safe from any thread.

A game comes as its update zip (``Jetsons_Code.zip``, ``DOM_v6.zip``,
``rzupdate_V26.zip``: a PRG and the SD card's DMD/ and SFX/) or as the PRG
in an unpacked card folder. A zip is unpacked once into ``cache_dir``.
"""
import os
import queue
import threading
import time
import zipfile

from tools.pinheck_emu.games import coil_pins, game_of
from tools.pinheck_emu.run import boot

TAP_MS = 150


def cache_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    return os.path.join(base, "PinballAssetDecryptor", "pinheck")


def find_prg(folder):
    """The game program in an unpacked card: ``<GAME>_Vnnn.PRG``."""
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            if f.upper().endswith(".PRG"):
                return os.path.join(root, f)
    return None


def unpack(path, cache_dir=None):
    """(prg path, card folder) for a zip, a PRG, or a card folder; raises
    ValueError when there is no game program in it."""
    if os.path.isdir(path):
        prg = find_prg(path)
    elif path.lower().endswith(".zip"):
        stem = os.path.splitext(os.path.basename(path))[0]
        dest = os.path.join(cache_dir or cache_root(), stem)
        stamp = os.path.join(dest, ".unpacked")
        size = str(os.path.getsize(path))
        if not (os.path.isfile(stamp) and open(stamp).read() == size):
            os.makedirs(dest, exist_ok=True)
            with zipfile.ZipFile(path) as z:
                z.extractall(dest)
            with open(stamp, "w") as f:
                f.write(size)
        prg = find_prg(dest)
    else:
        prg = path
    if not prg or not os.path.isfile(prg):
        raise ValueError("no pinHeck game program (<GAME>_Vnnn.PRG) in %s" % path)
    card = os.path.dirname(prg)
    if not os.path.isdir(os.path.join(card, "DMD")):        # PRG in a subfolder
        up = os.path.dirname(card)
        card = up if os.path.isdir(os.path.join(up, "DMD")) else card
    return prg, card


class Machine:
    def __init__(self, path, nvram=None, mute=False, cache_dir=None):
        self.prg_path, self.card = unpack(path, cache_dir)
        self.game = game_of(self.prg_path) or {}
        self.title = self.game.get("title") or os.path.basename(self.prg_path)
        self.nvram = nvram or os.path.join(cache_dir or cache_root(), "nvram",
                                           os.path.basename(self.prg_path).split("_")[0])
        self.mute = mute
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.paused = False
        self.error = None
        self.fired = []                     # (millis, coil name), newest last
        self.held = set()
        self._started_at = None
        self.speed = 0.0
        link_box = []
        self.pic, self.link = boot(open(self.prg_path, "rb").read(), 0, card=self.card,
                                   nvram=self.nvram, link_box=link_box,
                                   game=self.game or None)
        self.board, self.balls, self.av, self.sound = (
            self.link.board, self.link.balls, self.link.av, self.link.sound)
        from tools.pinheck_emu.board import Lamps
        self.lamps = Lamps(self.pic)
        # the lamp driver only multiplexes lamps nobody sees here: every 8th
        # interrupt is enough, and the game is otherwise unchanged (same
        # packets and videos as a full run, PAD-320 pass 8)
        self.pic.timer_divide[2] = 8
        if mute:
            self.sound.master = 0.0
        by_port = {}
        for name, (port, mask) in (coil_pins(self.game).items() if self.game else ()):
            by_port.setdefault(port, []).append((mask, name))
        masks = {port: sum(m for m, _ in v) for port, v in by_port.items()}

        def lat(port, old, new):
            rose = new & ~old & masks[port]
            if rose:
                for m, n in by_port[port]:
                    if rose & m:
                        self.fired.append((self.pic.millis, n))
                del self.fired[:-40]
        self.pic.watch(by_port, lat)
        self.thread = threading.Thread(target=self._run, name="pinheck-cpu", daemon=True)

    # ---- the CPU thread ----------------------------------------------------
    def start(self):
        self.thread.start()

    def _apply(self, now):
        while True:
            try:
                what, arg = self._q.get_nowait()
            except queue.Empty:
                return
            if what == "press":
                self.board.set(arg, True)
                self.held.add(arg)
            elif what == "release":
                self.board.set(arg, False)
                self.held.discard(arg)
            elif what == "plunge" and self.balls:
                self.balls.plunge()
            elif what == "drain" and self.balls:
                self.balls.drain()
            elif what == "serial":
                self.pic.serial_in(arg)
            elif callable(what):
                what(*arg)

    def _run(self):
        """Keep emulated time on the wall clock: run what is due (up to 50
        ms at a time), sleep only when ahead. When the PC cannot keep up the
        game runs slow rather than skipping (``speed`` says by how much)."""
        try:
            wall0, emu0 = time.monotonic(), self._now()
            last = (wall0, emu0)
            while not self._stop.is_set():
                if self.paused:
                    time.sleep(0.05)
                    wall0, emu0 = time.monotonic(), self._now()
                    continue
                due = int((time.monotonic() - wall0) * 1000) - (self._now() - emu0)
                if due <= 0:
                    time.sleep(0.004)
                    continue
                with self._lock:
                    self._apply(self._now())
                    self.pic.run_ms(min(due, 50))
                if due > 1000:                     # far behind (a slow PC): don't chase
                    wall0, emu0 = time.monotonic(), self._now()
                t = time.monotonic()
                if t - last[0] >= 1:
                    self.speed = (self._now() - last[1]) / 1000 / (t - last[0])
                    last = (t, self._now())
        except Exception as e:                       # noqa: BLE001
            self.error = "%s: %s" % (type(e).__name__, e)
        finally:
            self._save()

    def _now(self):
        return self.pic.millis if self.pic.millis_addr else 0

    def _save(self):
        from tools.pinheck_emu.run import NVRAM
        try:
            os.makedirs(self.nvram, exist_ok=True)
            for (name, _), data in zip(NVRAM, (self.pic.i2c_devices[0x50].data, self.link.eeprom)):
                with open(os.path.join(self.nvram, name), "wb") as f:
                    f.write(data)
        except OSError:
            pass

    def stop(self):
        self._stop.set()
        if self.thread.is_alive():
            self.thread.join(5)

    # ---- what the window calls -------------------------------------------
    def press(self, switch):
        self._q.put(("press", switch))

    def release(self, switch):
        self._q.put(("release", switch))

    def tap(self, switch, ms=TAP_MS):
        self.press(switch)
        threading.Timer(ms / 1000, self.release, (switch,)).start()

    def plunge(self):
        self._q.put(("plunge", None))

    def drain(self):
        self._q.put(("drain", None))

    def serial(self, text):
        self._q.put(("serial", text.encode("latin1")))

    def frame(self):
        with self._lock:
            return self.av.frame(self.pic.millis if self.pic.millis_addr else 0)

    def status(self):
        b = self.balls
        ms = self.pic.millis if self.pic.millis_addr else 0
        return {
            "title": self.title, "seconds": ms / 1000, "speed": round(self.speed, 2),
            "paused": self.paused, "error": self.error,
            "trough": b.in_trough if b else None, "shooter": b.in_shooter if b else None,
            "in_play": b.in_play if b else None,
            "coils": [n for t, n in self.fired if ms - t < 1500][-6:],
            "playing": [c.name for c in list(self.sound.channels.values())],
            "closed": sorted(self.board.matrix),
            "lamps": self.lamps.levels(),
            "scores": {str(k): v for k, v in sorted(self.av.scores.items())},
            "held": sorted(str(h) for h in self.held),
            "uart": self.pic.uart[-600:].decode("latin1", "replace"),
        }
