#!/usr/bin/env python3
"""appf.py - the American Pinball virtual playfield: the Stern rigs' own
virtual-playfield page (tools/spike2_emu/pfpage, unchanged - David: "use the
stern layout of this window as a template ... we should NOT be reinventing
the wheel"), served for an AP game.

    pythonw tools\\ap_emu\\appf.py --table <switches.json> [--distro PAD-Runtime]
        [--slot 0] [--title "Legends of Valhalla"] [--audio-ctl <audio_ctl.json>]
        [--parent-pipe]

The page is data-driven: a snapshot (/state) and live "frame" events, and a
fixed set of calls back (hold, row, svc, door, ball, key, pause, volume...).
This host answers them from the rig's switches.json (apswitches.py) and a
live `ctl.sh --stream` pipe into the game (apctl.py), as playfield.py does
for a Stern card:

* the playfield: the game's own picture with its switches and lights where
  the game puts them (AP's simulator positions, or the developers' layout -
  apswitches.py says which); lights lit in the game's colours.  A game with
  no usable picture gets the page's schematic view: every light as a swatch,
  every switch as a row.
* the key panel: the cabinet and flipper keys the Stern window uses (arrows
  for the flippers, 1 Start, 5 a coin, Space the Action button, T tilt,
  letters for playfield switches), rows that press what they name, the
  coin-door SERVICE buttons (Backspace/Esc, -, =, Enter), the coin door (C),
  and BALLS: the trough, Plunge (F), Drain (D), Reset balls.
* the status bar: Pause (Pause / F9 freezes the game and apiav), and the
  Emulate tab's Volume / Mute (the shared control file, --audio-ctl).

It runs on WINDOWS, on the app's own Python, as every rig's window does; the
game is in the app's Linux.  --parent-pipe: the tab holds stdin open and
closes it on Stop; the window closes then (and on the game's end).
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.join(os.path.dirname(HERE), "spike2_emu")
sys.path.insert(0, SPIKE)
import pfweb  # noqa: E402  (the rig windows' shared web host)

PAGE_DIR = os.path.join(SPIKE, "pfpage")
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
POLL_S = 0.2
GONE_AFTER = 15          # polls without a live game (~3 s) = it is gone
GEOM_FILE = os.path.join(os.path.expanduser("~"), ".pad_ap_switches.json")
LED_R = 5.5
#: PAD-1468: a picture the user put under a game's numbered spots, one per
#: game: <key>.<ext> and <key>.json ({"rect": [x, y, w, h]} in the table's
#: base, where the picture is drawn).  Theirs, never shipped.
PICTURE_DIR = os.path.join(os.path.expanduser("~"), ".pad_playfield_pictures")
PICTURE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                 "image/gif": "gif", "image/bmp": "bmp"}
PICTURE_MAX = 30 * 1024 * 1024


def picture_key(title):
    return re.sub(r"[^a-z0-9]+", "_", (title or "game").lower()).strip("_") or "game"


def good_rect(r):
    """[x, y, w, h] of finite numbers with a real size, else None."""
    try:
        r = [float(v) for v in r]
    except (TypeError, ValueError):
        return None
    if len(r) != 4 or any(v != v or abs(v) > 1e6 for v in r) or r[2] < 1 or r[3] < 1:
        return None
    return [round(v, 2) for v in r]

#: The coin-door service buttons' look: switch name, then label, caption,
#: glyph, fill, ring, caption colour, key codes, key text - the Stern panel's.
#: (The keys themselves are apswitches.py's keymap, one map for this window
#: and the game's own.)
SERVICE = (
    ("exit", "Service Back", "BACK", "", "#1f9d4e", "#0d5c2a", "#dff5e6",
     ("Backspace", "Escape"), "Bksp/Esc"),
    ("down", "Service Minus", "< -", "-", "#d43535", "#7a1717", "#ffffff",
     ("Minus", "NumpadSubtract"), "-"),
    ("up", "Service Plus", "+ >", "+", "#d43535", "#7a1717", "#ffffff",
     ("Equal", "NumpadAdd"), "="),
    ("enter", "Service Select", "SELECT", "", "#1c1c1c", "#777", "#d8d8d8",
     ("Enter", "NumpadEnter"), "Enter"),
)


def wsl_path(p):
    p = p.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def win_path(linux_path, distro):
    """A path inside the app's Linux, as Windows reaches it."""
    if not distro or not linux_path.startswith("/"):
        return linux_path
    return "\\\\wsl.localhost\\%s%s" % (distro, linux_path.replace("/", "\\"))


def _num(name):
    d = "".join(c for c in name if c.isdigit())
    return int(d) if d else 0


# --------------------------------------------------------------- the model
def trough_order(table):
    """The trough's positions from the eject end (as the rig models them)."""
    pos = [s for s in table.get("switches") or []
           if s["group"] == "Trough" and s["name"] != "shooter"
           and "jam" not in (s.get("label") or "").lower()]
    pos.sort(key=lambda s: _num(s["name"]))
    ej = [s for s in pos if "eject" in s["name"].lower()]
    return ej + [s for s in pos if s not in ej]


def light_value(rgb):
    """[r, g, b, alpha, radius] for the page (None = dark): the colour at
    full strength, its brightness as the alpha."""
    if not rgb or not any(rgb):
        return None
    m = max(rgb[:3])
    k = 255.0 / m
    return [int(min(255, c * k)) for c in rgb[:3]] + [round(max(0.35, m / 255.0), 2), LED_R]


class Rig:
    """The ctl.sh --stream pipe: one request, one JSON reply, in order."""

    def __init__(self, distro, slot):
        cmd = ["wsl.exe"] + (["-d", distro] if distro else []) + [
            "-e", "env", "PAD_SLOT=%s" % slot, "bash",
            wsl_path(os.path.join(HERE, "ctl.sh")), "--stream"]
        if sys.platform != "win32":             # a Linux desktop: no wsl.exe
            cmd = ["env", "PAD_SLOT=%s" % slot, "bash",
                   os.path.join(HERE, "ctl.sh"), "--stream"]
        self.cmd = cmd
        self.proc = None
        self.lock = threading.Lock()

    def ask(self, line):
        with self.lock:
            for _attempt in (1, 2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self.proc = subprocess.Popen(
                            self.cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=1,
                            universal_newlines=True, encoding="utf-8",
                            errors="replace", creationflags=_CREATE_NO_WINDOW)
                    self.proc.stdin.write(line + "\n")
                    self.proc.stdin.flush()
                    reply = self.proc.stdout.readline()
                    if reply:
                        try:
                            return json.loads(reply)
                        except ValueError:
                            return None
                except (OSError, ValueError):
                    pass
                self.proc = None
            return None

    def close(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.stdin.close()
                p.wait(timeout=3)
            except Exception:                           # noqa: BLE001
                p.kill()


class App:
    """What the Stern page asks of its host (pfweb's four calls), for an AP
    game."""

    def __init__(self, table, rig, art, title, slot="0", label="", audio_ctl=""):
        self.t = table
        self.rig = rig
        self.art = art if art and os.path.isfile(art) else None
        self.title = title
        self.slot = str(slot)
        self.label = label
        self.audio_ctl = audio_ctl
        self.host = None
        self.stopping = False
        self.misses = 0
        sws = table.get("switches") or []
        self.by_n = {s["n"]: s for s in sws}
        self.by_name = {s["name"]: s for s in sws}
        self.svc = [(self.by_name[row[0]], row[1:]) for row in SERVICE
                    if row[0] in self.by_name]
        if len(self.svc) != len(SERVICE):
            self.svc = []
        self.door = self.by_name.get("coinDoor")
        self.trough = trough_order(table)
        self.shooter = self.by_name.get("shooter")
        self.placed = [s for s in sws if "x" in s]
        self.lights_placed = table.get("lights") or []
        # PAD-1468: a table whose switches are the Spooky manual's numbered
        # spots gets the playfield view, its spots numbered, over the user's
        # picture, the game's own drawing or a plain field; it keeps the
        # schematic's LED grid
        self.spots = bool(table.get("spots") and table.get("size") and self.placed)
        self.field = bool(self.art and table.get("size")
                          and (self.placed or self.lights_placed)) or self.spots
        # PAD-1468: under the spots, the user's own picture of this game, else
        # the game's own drawing (the art the table names, at its art_rect)
        self.pic_key = picture_key(title)
        # the key panel: apswitches.py's rows; the schematic view lists every
        # switch itself, so there it keeps the keyed rows only
        self.rows = [r for r in table.get("rows") or []
                     if self.field or not r.get("unplaced")]
        self.keymap = table.get("keymap") or []
        # live state
        self.active = set()
        self.lights = {}
        self.paused = False
        self.held_ids = set()          # switches this window holds (mouse)
        self.ripping = set()           # switches right-held (ripping)
        self.key_held = {}             # key code -> [switch numbers]
        self.row_hit = set()           # row indexes pressed right now
        self.note = []
        self._sent = {}

    # -- the snapshot ------------------------------------------------------------
    def _audio(self):
        if not self.audio_ctl:
            return None
        try:
            with open(self.audio_ctl, encoding="utf-8") as f:
                d = json.load(f)
            return {"gain": max(0.0, min(1.0, float(d.get("gain", 1.0)))),
                    "muted": bool(d.get("muted", False))}
        except (OSError, ValueError, TypeError, AttributeError):
            return {"gain": 1.0, "muted": False}

    def _run(self):
        return {"paused": self.paused, "audio": self._audio()}

    def _info(self):
        return [["Switches", str(len(self.by_n)),
                 "%d on the manual's spots" % len(self.placed) if self.spots
                 else "%d on the picture" % len(self.placed) if self.field else "no picture"],
                ["Lights", str(len(self.lights) or len(self.lights_placed)),
                 "%d on the picture" % len(self.lights_placed)
                 if self.field and not self.spots else ""],
                ["Positions", self.t.get("art_from") or "none in this game", ""]]

    def _live(self):
        return [["Switches made", str(len(self.active)), ""],
                ["Lights lit", str(sum(1 for v in self.lights.values() if v and any(v))), ""]]

    def _balls(self):
        tr = sum(1 for s in self.trough if s["n"] in self.active)
        sh = 1 if self.shooter and self.shooter["n"] in self.active else 0
        total = self.t.get("balls")
        if total:
            play = max(0, total - tr - sh)
            return tr, sh, play, "balls %d   trough %d   shooter %d   in play %d" % (
                total, tr, sh, play)
        return tr, sh, 0, "trough %d   shooter %d" % (tr, sh)

    def _dots(self):
        """One dot per BALL (the machine's ball count), not per trough
        switch: Legends of Valhalla's trough has 7 switches for 6 balls."""
        return self.t.get("balls") or len(self.trough)

    def _panel_dyn(self):
        _tr, sh, play, text = self._balls()
        rows = [[i in self.row_hit or any(n in self.held_ids for n in r["ns"]), "",
                 any(n in self.active for n in r["ns"])] for i, r in enumerate(self.rows)]
        return {"rows": rows,
                "svc": [s["n"] in self.active for s, _look in self.svc],
                "door": (self.door["n"] in self.active) if self.door else None,
                "ball": text, "drain": play > 0 or sh > 0,
                "dots": {"flags": [i < _tr for i in range(self._dots())],
                         "text": "in the trough"},
                "note": list(self.note[-3:])}

    def _panel_spec(self):
        return {
            "rows": [{"keys": r["keys"], "label": r["label"], "cabinet": r["cabinet"],
                      "na": False, "click": i} for i, r in enumerate(self.rows)],
            "svc": [{"label": look[0], "sub": look[1], "glyph": look[2], "fill": look[3],
                     "ring": look[4], "subfg": look[5], "keys": look[7], "id": s["n"]}
                    for s, look in self.svc],
            "clear": None,
            "door": "C" if self.door else None,
            "trough_keys": "F = plunge   D = drain",
            "balls": ({"pos": [str(i + 1) for i in range(self._dots())]}
                      if self.trough else None),
            "disc": None}

    def _sw_dyn(self):
        return {str(n): 1 for n in self.active}

    def _fx(self):
        return {k: light_value(self.lights.get(k)) for k, _x, _y in self.lights_placed}

    def _grid(self):
        out = {}
        for k, rgb in self.lights.items():
            v = light_value(rgb)
            out[k] = v[:4] if v else None
        return out

    def _status(self):
        _tr, _sh, play, _t = self._balls()
        lit = sum(1 for v in self.lights.values() if v and any(v))
        bits = [self.title, "%d in play" % play, "%d lights lit" % lit]
        if self.paused:
            bits.append("PAUSED")
        return "  ·  ".join(bits)

    def _switch_tip(self, s):
        spot = ""
        if s.get("spot"):
            spot = "\n%s on the manual's switch photo" % (
                "the trough jam" if s["spot"] == "JAM" else "spot %s" % s["spot"])
        return "%s  (%s, %d%s)%s\nhold to make it; hold the right button to rip it" % (
            s["label"] or s["name"], s["name"], s["n"], ", an opto" if s.get("nc") else "",
            spot)

    # -- the picture under the spots (PAD-1468) -------------------------------
    def _prefs(self):
        """This game's saved picture settings: {"rect": ..., "hide": bool}."""
        try:
            with open(os.path.join(PICTURE_DIR, self.pic_key + ".json"),
                      encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_prefs(self, d):
        os.makedirs(PICTURE_DIR, exist_ok=True)
        with open(os.path.join(PICTURE_DIR, self.pic_key + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(d, fh)

    def _own_picture(self):
        """(path, rect or None) of the user's picture of this game, or None."""
        for ext in sorted(set(PICTURE_TYPES.values())):
            f = os.path.join(PICTURE_DIR, "%s.%s" % (self.pic_key, ext))
            if os.path.isfile(f):
                rect = None
                try:
                    with open(os.path.join(PICTURE_DIR, self.pic_key + ".json"),
                              encoding="utf-8") as fh:
                        rect = good_rect(json.load(fh).get("rect"))
                except (OSError, ValueError, AttributeError):
                    pass
                return f, rect
        return None

    def _picture_file(self):
        own = self._own_picture()
        if own:
            return own[0]
        return self.art if self.spots else None

    def _pic_v(self):
        """The picture's version for the page's URL (the file route caches)."""
        try:
            return int(os.path.getmtime(self._picture_file()) * 1000)
        except (OSError, TypeError):
            return 0

    def _picture(self):
        """What the page draws under the spots: {own, rect, v} or None."""
        own = self._own_picture()
        hide = bool(self._prefs().get("hide"))
        if own:
            return {"own": True, "rect": own[1], "v": self._pic_v(),
                    "game": bool(self.art), "hide": hide}
        if self.spots and self.art:
            return {"own": False, "rect": good_rect(self.t.get("art_rect") or ()),
                    "v": self._pic_v(), "game": True, "hide": hide}
        return None

    def _drop_own_picture(self):
        """The picture and where it was lined up; Hide spots stays."""
        for ext in set(PICTURE_TYPES.values()):
            try:
                os.remove(os.path.join(PICTURE_DIR, "%s.%s" % (self.pic_key, ext)))
            except OSError:
                pass
        d = self._prefs()
        if "rect" in d:
            d.pop("rect")
            self._save_prefs(d)

    def set_picture(self, data_url):
        """The page's chosen file, as a data: URL -> this game's picture."""
        m = re.match(r"data:([\w/+.-]+);base64,(.*)$", data_url or "", re.S)
        if not m or m.group(1).lower() not in PICTURE_TYPES:
            raise ValueError("pick a PNG, JPEG, WebP, GIF or BMP picture")
        raw = base64.b64decode(m.group(2), validate=False)
        if not raw or len(raw) > PICTURE_MAX:
            raise ValueError("that picture is empty or bigger than 30 MB")
        os.makedirs(PICTURE_DIR, exist_ok=True)
        self._drop_own_picture()
        f = os.path.join(PICTURE_DIR, "%s.%s" % (self.pic_key,
                                                PICTURE_TYPES[m.group(1).lower()]))
        with open(f + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(f + ".tmp", f)
        return self._picture()

    def set_picture_rect(self, rect):
        """Where the user lined their picture up; a game drawing's place is
        the table's, never moved (Reset puts a moved picture back)."""
        rect = good_rect(rect)
        if rect is None or not self._own_picture():
            return self._picture()
        d = self._prefs()
        d["rect"] = rect
        self._save_prefs(d)
        return self._picture()

    def set_spots_hidden(self, hide):
        """Hide spots: the picture's own buttons show, the switches still work."""
        d = self._prefs()
        d["hide"] = bool(hide)
        self._save_prefs(d)
        return self._picture()

    def clear_picture(self):
        self._drop_own_picture()
        return self._picture()

    def _grid_blocks(self):
        names = sorted(self.lights) or sorted(k for k, _x, _y in self.lights_placed)
        return [{"node": "lights", "cells": [{"k": k, "tip": k} for k in names]}] if names else []

    def _view(self):
        if self.field:
            w, h = self.t["size"]
            v = {"base": [w, h], "art": bool(self.art), "coils": [], "trough": None,
                 "fixtures": [[k, x, y] for k, x, y in self.lights_placed],
                 "switches": [[str(s["n"]), s["x"], s["y"], s["n"]]
                              + ([s["spot"]] if s.get("spot") else []) for s in self.placed],
                 "info": self._info()}
            if self.spots:
                v.update(fixtures=[], sketch=self.t.get("sketch") or [],
                         grid={"blocks": self._grid_blocks()}, art=False,
                         picture=self._picture())
            return v
        return {"bar": "%s - this game ships no playfield picture: its lights, "
                       "and every switch" % self.title,
                "grid": {"blocks": self._grid_blocks()},
                "entries": [{"id": s["n"], "name": s["label"] or s["name"],
                             "tip": self._switch_tip(s), "live": True}
                            for s in sorted(self.by_n.values(), key=lambda s: s["n"])],
                "trough": None, "info": self._info()}

    def state(self, page):
        rig = {}
        if self.slot not in ("", "0"):
            rig = {"slot": int(self.slot), "label": "" if self.label == "PAD" else self.label}
        return {"title": "%s - virtual playfield" % self.title, "rig": rig,
                "status": self._status(), "run": self._run(), "savestates": False,
                "kind": "field" if self.field else "schematic", "view": self._view(),
                "dyn": ({"fx": self._fx(), "coil": {}, "sw": self._sw_dyn()}
                        if self.field and not self.spots
                        else {"grid": self._grid(), "sw": self._sw_dyn()}),
                "panel": {"spec": self._panel_spec(), "dyn": self._panel_dyn()},
                "live": self._live()}

    # -- the calls -----------------------------------------------------------------
    def _press(self, ns, on):
        for n in ns:
            self.rig.ask("sw %d %d" % (n, 1 if on else 0))

    def _say(self, text):
        self.note = (self.note + [text])[-6:]

    def api(self, m, args):
        if m == "pic_set":
            return self.set_picture(args[0])
        if m == "pic_rect":
            return self.set_picture_rect(args[0])
        if m == "pic_clear":
            return self.clear_picture()
        if m == "pic_spots":
            return self.set_spots_hidden(args[0])
        if m == "hold":
            n = int(args[0])
            self.held_ids.add(n)
            self._press([n], True)
            return True
        if m == "unhold":
            ids, self.held_ids = list(self.held_ids), set()
            self._press(ids, False)
            return True
        if m == "rip":
            # right-hold, as on the Stern window: the switch flips as long as
            # it is held (a spinner spinning) - the game loop does the
            # flipping (aprun.py), so it keeps time
            n, on = int(args[0]), bool(args[1])
            (self.ripping.add if on else self.ripping.discard)(n)
            self.rig.ask("rip %d %d" % (n, 1 if on else 0))
            return True
        if m == "row":
            i, down = int(args[0]), bool(args[1])
            if 0 <= i < len(self.rows):
                (self.row_hit.add if down else self.row_hit.discard)(i)
                self._press(self.rows[i]["ns"], down)
            return True
        if m == "svc":
            self._press([int(args[0])], bool(args[1]))
            return True
        if m == "door":
            if self.door:
                self._press([self.door["n"]], self.door["n"] not in self.active)
            return True
        if m == "ball":
            what = args[0]
            if what in ("plunge", "drain", "reset"):
                self.rig.ask(what)
                self._say({"plunge": "plunged", "drain": "a ball drained",
                           "reset": "every ball back in the trough"}[what])
            return True
        if m == "key":
            return self.key(args[0], bool(args[2]))
        if m == "blur":
            for code in list(self.key_held):
                self.key(code, False)
            for n in list(self.ripping):
                self.api("rip", [n, False])
            return True
        if m == "pause":
            self.set_pause(not self.paused)
            return True
        if m == "volume":
            self._write_audio(gain=max(0.0, min(100.0, float(args[0]))) / 100.0)
            return True
        if m == "mute":
            self._write_audio(muted=bool(args[0]))
            return True
        if m == "tip":
            kind, k = args[0], args[1]
            if kind == "switch":
                s = self.by_n.get(int(k))
                return self._switch_tip(s) if s else ""
            if kind == "led":
                rgb = self.lights.get(k)
                return "%s  %s" % (k, "off" if not rgb or not any(rgb)
                                   else "rgb(%d, %d, %d)" % tuple(rgb[:3]))
            return ""
        if m == "geom":
            save_geom(args[1], args[2])
            return True
        return None                    # coil / save / load / clear_alerts: not here

    def key(self, code, down):
        for k in self.keymap:
            if code not in k["codes"]:
                continue
            act = k.get("action")
            if act:
                if down:
                    if act == "pause":
                        self.set_pause(not self.paused)
                    elif act == "door":
                        self.api("door", [])
                    else:
                        self.api("ball", [act])
                return True
            for i, r in enumerate(self.rows):
                if r["ns"] == k["ns"]:
                    (self.row_hit.add if down else self.row_hit.discard)(i)
            self._key_switches(code, k["ns"], down)
            return True
        return False

    def _key_switches(self, code, ns, down):
        if down:
            if code in self.key_held:
                return
            self.key_held[code] = ns
            self._press(ns, True)
        else:
            self._press(self.key_held.pop(code, ns), False)

    def set_pause(self, on):
        r = self.rig.ask("pause %d" % (1 if on else 0)) or {}
        self.paused = bool(r.get("paused", on))
        if self.host:
            self.host.publish("run", self._run())

    def _write_audio(self, gain=None, muted=None):
        if not self.audio_ctl:
            return
        cur = self._audio() or {"gain": 1.0, "muted": False}
        if gain is not None:
            cur["gain"] = gain
        if muted is not None:
            cur["muted"] = muted
        try:
            tmp = self.audio_ctl + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, self.audio_ctl)
        except OSError:
            pass
        if self.host:
            self.host.publish("run", self._run())

    def blob(self, key):
        return None

    def file(self, name):
        if name == "picture":
            return self._picture_file()
        return self.art if name == "art" else None

    # -- the live loop ---------------------------------------------------------------
    def frame(self):
        """What changed since the last frame, for the page."""
        f = {}
        sw = self._sw_dyn()
        prev = self._sent.get("sw", {})
        diff = {k: 1 for k in sw if k not in prev}
        diff.update({k: 0 for k in prev if k not in sw})
        if diff:
            f["sw"] = diff
        self._sent["sw"] = sw
        key, cur = (("fx", self._fx()) if self.field and not self.spots
                    else ("grid", self._grid()))
        prev = self._sent.get(key, {})
        d = {k: v for k, v in cur.items() if k not in prev or prev[k] != v}
        if d:
            f[key] = d
        self._sent[key] = cur
        for name, val in (("panel", self._panel_dyn()), ("status", self._status()),
                          ("live", self._live())):
            if self._sent.get(name) != val:
                f[name] = val
                self._sent[name] = val
        run = self._run()
        if self._sent.get("run") != run:
            self._sent["run"] = run
            if self.host:
                self.host.publish("run", run)
        return f

    def poll(self):
        while not self.stopping:
            st = self.rig.ask("state")
            if not st or not st.get("up"):
                self.misses += 1
                if self.misses >= GONE_AFTER:
                    self.host.publish("close")
                    time.sleep(0.5)
                    self.host.quit()
                    return
            else:
                self.misses = 0
                self.active = {int(k) for k in (st.get("switches") or {})}
                self.lights = st.get("lights") or {}
                self.paused = bool(st.get("paused", self.paused))
                f = self.frame()
                if f and self.host:
                    self.host.publish("frame", f)
            time.sleep(POLL_S)


def watch_parent(app, host, stream=None):
    """--parent-pipe: the Emulate AP tab holds this process's stdin open and
    closes it on Stop.  EOF = close the window and quit - the window is a
    separate browser process (pfweb's AppBackend), which a plain kill of
    this one would leave on screen."""
    if stream is None:
        # fd 0 itself: under pythonw sys.stdin can be None even with a pipe
        try:
            os.fstat(0)
        except OSError:
            return                      # no parent pipe to watch - stay up
        read = lambda: os.read(0, 4096)                 # noqa: E731
    else:
        read = lambda: stream.read(4096)                # noqa: E731
    try:
        while read():
            pass
    except (OSError, ValueError):
        pass
    if app.stopping:
        return
    app.stopping = True
    host.publish("close")
    time.sleep(0.3)
    host.quit()


def load_geom():
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_geom(x, y):
    try:
        with open(GEOM_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": int(x), "y": int(y)}, f)
    except (OSError, TypeError, ValueError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="American Pinball virtual playfield")
    ap.add_argument("--table", required=True, help="the rig's switches.json")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--title", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--audio-ctl", default="", help="the app's audio_ctl.json (Volume / Mute)")
    ap.add_argument("--parent-pipe", action="store_true",
                    help="close the window when stdin closes (the app's Stop)")
    args = ap.parse_args(argv)
    with open(args.table, encoding="utf-8") as f:
        table = json.load(f)
    title = args.title or table.get("title") or "American Pinball"
    rig = Rig(args.distro, args.slot)
    app = App(table, rig, win_path(table.get("art") or "", args.distro), title,
              slot=args.slot, label=args.label, audio_ctl=args.audio_ctl)
    host = pfweb.WebHost(PAGE_DIR, app, title="%s - virtual playfield" % title)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True, name="ap-poll").start()
    if args.parent_pipe:
        threading.Thread(target=watch_parent, args=(app, host), daemon=True,
                         name="ap-parent").start()
    g = load_geom()
    main_spec = {"page": "main", "width": 1000, "height": 980,
                 "title": "%s - virtual playfield" % title,
                 "x": g.get("x"), "y": g.get("y"), "min_size": (720, 560)}

    def on_close():
        app.stopping = True
        pos = host.geometry("main")
        if pos:
            save_geom(pos[0], pos[1])
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
