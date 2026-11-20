#!/usr/bin/env python3
r"""spkpf.py - a Spooky game's virtual playfield: the American Pinball
window (tools/ap_emu/appf.py, on the Stern rigs' page tools/spike2_emu/pfpage)
pointed at this rig's board, so every maker's Emulate window looks and works
the same - the key panel, the coin-door service buttons, BALLS (trough dots,
Plunge, Drain, Reset balls), Pause and the Volume / Mute bar.

    pythonw tools\spooky_emu\spkpf.py --table <switches.json> [--distro PAD-Runtime]
        [--slot 0] [--audio-ctl <audio_ctl.json>] [--parent-pipe]

The table is spkswitches.py's (apswitches.py's format); the board answers
appf's requests over ctl.sh --stream (spkwarden.py).  The table names the
running game (spktitles.py).  The Spooky games ship no playfield picture
with switch positions, so the window is appf's schematic view: every switch
as a row.
"""
import argparse
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TOOLS, "ap_emu"))
import appf  # noqa: E402  (the AP window this one is)

GEOM_FILE = os.path.join(os.path.expanduser("~"), ".pad_spooky_switches.json")


class Rig(appf.Rig):
    """appf's pipe, into THIS rig's ctl.sh."""

    def __init__(self, distro, slot):
        super().__init__(distro, slot)
        ctl = os.path.join(HERE, "ctl.sh")
        self.cmd = [(appf.wsl_path(ctl) if sys.platform == "win32" else ctl)
                    if c.endswith("ctl.sh") else c for c in self.cmd]


class App(appf.App):
    """appf's host.  A Spooky game's own window keeps the game's built-in
    keys (Beetlejuice's: Enter starts, Space launches, the arrows flip); since
    PAD-313 the rig's game-window listener (tools/ap_emu/gamekeys.py) adds
    this window's other keys there, so the page's default "works here and in
    the game window" is true."""


def serve(table, distro="", slot="0", audio_ctl="", title="", art=""):
    """The window's page, served and polling: (app, rig, host).  main()
    shows it; a capture script shows it to a headless browser instead."""
    title = title or table.get("title") or "Beetlejuice"
    rig = Rig(distro, slot)
    app = App(table, rig, art, title, slot=slot, audio_ctl=audio_ctl)
    host = appf.pfweb.WebHost(appf.PAGE_DIR, app,
                              title="%s - virtual playfield" % title)
    app.host = host
    host.start()
    threading.Thread(target=app.poll, daemon=True, name="spk-poll").start()
    return app, rig, host


def load_geom():
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Spooky virtual playfield")
    ap.add_argument("--table", required=True, help="the rig's switches.json")
    ap.add_argument("--distro", default="")
    ap.add_argument("--slot", default=os.environ.get("PAD_SLOT", "0"))
    ap.add_argument("--audio-ctl", default="", help="the app's audio_ctl.json (Volume / Mute)")
    ap.add_argument("--parent-pipe", action="store_true",
                    help="close the window when stdin closes (the app's Stop)")
    args = ap.parse_args(argv)
    with open(args.table, encoding="utf-8") as f:
        table = json.load(f)
    # the game's own playfield drawing, copied beside the table (PAD-1468)
    art = os.path.join(os.path.dirname(args.table), table["art"]) if table.get("art") else ""
    app, rig, host = serve(table, args.distro, args.slot, args.audio_ctl, art=art)
    if args.parent_pipe:
        threading.Thread(target=appf.watch_parent, args=(app, host), daemon=True,
                         name="spk-parent").start()
    g = load_geom()
    main_spec = {"page": "main", "width": 1000, "height": 980,
                 "title": "%s - virtual playfield" % app.title,
                 "x": g.get("x"), "y": g.get("y"), "min_size": (720, 560)}

    def on_close():
        app.stopping = True
        pos = host.geometry("main")
        if pos:
            try:
                with open(GEOM_FILE, "w", encoding="utf-8") as f:
                    json.dump({"x": int(pos[0]), "y": int(pos[1])}, f)
            except (OSError, TypeError, ValueError):
                pass
        rig.close()
        host.stop()
    host.run(main_spec, on_close)
    return 0


if __name__ == "__main__":
    sys.exit(main())
