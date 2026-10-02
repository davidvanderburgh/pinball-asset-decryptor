"""The pinHeck game window: the DMD, the buttons, every switch, the sound (PAD-320).

    python -m tools.pinheck_emu.window <update.zip | GAME_Vnnn.PRG>
           [--audio-ctl FILE] [--mute] [--parent-pipe] [--x X --y Y]

A page in the app's own design (tools/pinheck_emu/page) in a native window,
hosted by the rig windows' web host (tools/spike2_emu/pfweb.py). The game
runs in this process on Windows Python (``machine.Machine``) - no WSL.

Sound goes out through ``sounddevice`` when this Python has it (PAD's own
Python gets it from Prerequisites, as the Stern window's does) and follows
the app's shared Volume / Mute file (``--audio-ctl``); ``--mute`` keeps it
silent whatever the file says. Without sounddevice the game runs silent and
the page says why.
"""
import argparse
import io
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "spike2_emu"))

import pfweb  # noqa: E402  (the rig windows' shared web host)

from tools.pinheck_emu.audio import RATE  # noqa: E402
from tools.pinheck_emu.board import CAB  # noqa: E402
from tools.pinheck_emu.machine import Machine  # noqa: E402

PAGE_DIR = os.path.join(HERE, "page")


class App:
    """pfweb's app: state(), api(), blob(), file()."""

    def __init__(self, path, audio_ctl="", mute=False):
        self.path = path
        self.audio_ctl = audio_ctl
        self.force_mute = mute
        self.host = None
        self.machine = None
        self.stream = None
        self.sound_note = ""
        self.gain, self.muted = 1.0, mute
        self._frame_lock = threading.Lock()
        self._png = b""
        self._boot()

    # ---- the game ------------------------------------------------------------
    def _boot(self):
        self.machine = Machine(self.path, mute=True)
        self.machine.start()
        self._apply_volume()

    def power_cycle(self):
        old = self.machine
        old.stop()
        self._boot()
        return True

    # ---- sound -----------------------------------------------------------------
    def start_sound(self):
        if self.force_mute:
            self.sound_note = "Muted for this run."
            return
        try:
            import sounddevice as sd
        except Exception:                                   # noqa: BLE001
            self.sound_note = ("No sound: this Python has no sounddevice. Prerequisites, "
                               "Install / repair prerequisites, tick Stern Pinball.")
            return

        def callback(outdata, frames, _time, _status):
            m = self.machine
            outdata[:] = m.sound.mix(frames) if m else 0
        try:
            self.stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="int16",
                                          blocksize=1024, callback=callback)
            self.stream.start()
        except Exception as e:                              # noqa: BLE001
            self.sound_note = "No sound: %s" % e

    def _apply_volume(self):
        m = self.machine
        if m is not None:
            m.sound.master = 0.0 if (self.muted or self.force_mute) else self.gain

    def poll_audio_ctl(self):
        while True:
            if self.audio_ctl:
                try:
                    with open(self.audio_ctl, encoding="utf-8") as f:
                        d = json.load(f)
                    self.gain = max(0.0, min(1.0, float(d.get("gain", 1.0))))
                    self.muted = bool(d.get("muted", False))
                except (OSError, ValueError, TypeError):
                    pass
            self._apply_volume()
            time.sleep(0.25)

    def _write_audio_ctl(self):
        if not self.audio_ctl:
            return
        try:
            tmp = self.audio_ctl + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"gain": self.gain, "muted": self.muted}, f)
            os.replace(tmp, self.audio_ctl)
        except OSError:
            pass

    # ---- pfweb ------------------------------------------------------------------
    def state(self, page):
        m = self.machine
        g = m.game or {}
        return {
            "title": m.title, "status": m.status(), "sound_note": self.sound_note,
            "gain": self.gain, "muted": self.muted or self.force_mute,
            "force_mute": self.force_mute,
            "has_launch": g.get("launch") is not None,
            "hand_plunger": bool(g.get("manual_plunger")) or g.get("launch") is None,
            "roles": {str(n): r for n, r in self._roles().items()},
            "cab": sorted(k for k in CAB if k != "door"),
        }

    def _roles(self):
        g = self.machine.game or {}
        roles = {}
        for n in g.get("trough", ()):
            roles[n] = "trough"
        if g.get("shooter") is not None:
            roles[g["shooter"]] = "shooter"
        return roles

    def api(self, m, a):
        mach = self.machine
        if m == "press":
            mach.press(_sw(a[0]))
        elif m == "release":
            mach.release(_sw(a[0]))
        elif m == "tap":
            mach.tap(_sw(a[0]))
        elif m == "plunge":
            mach.plunge()
        elif m == "drain":
            mach.drain()
        elif m == "pause":
            mach.paused = bool(a[0])
        elif m == "power":
            return self.power_cycle()
        elif m == "serial":
            mach.serial(str(a[0]))
        elif m == "volume":
            self.gain = max(0.0, min(1.0, float(a[0])))
            self._write_audio_ctl()
            self._apply_volume()
        elif m == "mute":
            self.muted = bool(a[0])
            self._write_audio_ctl()
            self._apply_volume()
        elif m == "status":
            return mach.status()
        return True

    def blob(self, key):
        if key.startswith("dmd"):
            img = self.machine.frame()
            buf = io.BytesIO()
            img.save(buf, "PNG", compress_level=1)
            return buf.getvalue(), "image/png"
        return None

    def file(self, name):
        return None


def _sw(v):
    return int(v) if str(v).isdigit() else str(v)


def run_script(app, script):
    """--script: press things at emulated times (see main)."""
    steps = []
    for item in script.split(","):
        name, _, when = item.strip().partition("@")
        at, _, hold = when.partition(":")
        steps.append((float(at), name, float(hold or 0.15)))
    for at, name, hold in sorted(steps):
        while app.machine.status()["seconds"] < at:
            time.sleep(0.05)
        m = app.machine
        if name == "power":                 # times after it count from the new boot
            app.power_cycle()
        elif name == "plunge":
            m.plunge()
        elif name == "drain":
            m.drain()
        else:
            sw = _sw(name)
            m.press(sw)
            time.sleep(hold)
            m.release(sw)


def watch_parent(app, host):
    """Close when the app's pipe closes (its Stop)."""
    try:
        while sys.stdin.read(1):
            pass
    except (OSError, ValueError):
        pass
    host.quit()


def main(argv=None):
    ap = argparse.ArgumentParser(description="pinHeck game window")
    ap.add_argument("game", help="the update zip, a PRG, or an unpacked card folder")
    ap.add_argument("--audio-ctl", default="", help="the app's audio_ctl.json (Volume / Mute)")
    ap.add_argument("--mute", action="store_true", help="no sound, whatever the volume says")
    ap.add_argument("--parent-pipe", action="store_true",
                    help="close the window when stdin closes (the app's Stop)")
    ap.add_argument("--x", type=int)
    ap.add_argument("--y", type=int)
    ap.add_argument("--script", default="",
                    help="timed presses for tests and proof shots: comma-separated "
                         "name@seconds[:hold], e.g. coin@14,start@15,launch@19:1.2,"
                         "plunge@20,8@22,drain@25 (a number is a playfield switch; "
                         "power@6 power-cycles, and later times count from that boot)")
    ap.add_argument("--headless", type=float, default=0,
                    help="no window: run this many seconds and print the status (tests)")
    args = ap.parse_args(argv)
    app = App(args.game, args.audio_ctl, args.mute)
    threading.Thread(target=app.poll_audio_ctl, daemon=True, name="pinheck-vol").start()
    if args.script:
        threading.Thread(target=run_script, args=(app, args.script), daemon=True,
                         name="pinheck-script").start()
    if args.headless:
        time.sleep(args.headless)
        print(json.dumps({k: v for k, v in app.state("main")["status"].items() if k != "uart"}))
        app.machine.stop()
        return 0
    app.start_sound()
    host = pfweb.WebHost(PAGE_DIR, app, title="%s - PAD" % app.machine.title)
    app.host = host
    host.start()
    if args.parent_pipe:
        threading.Thread(target=watch_parent, args=(app, host), daemon=True,
                         name="pinheck-parent").start()
    spec = {"page": "main", "width": 1180, "height": 900, "title": "%s - PAD" % app.machine.title,
            "x": args.x, "y": args.y, "min_size": (760, 560)}

    def on_close():
        app.machine.stop()
        if app.stream is not None:
            try:
                app.stream.stop()
            except Exception:                               # noqa: BLE001
                pass
        host.stop()
    host.run(spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
