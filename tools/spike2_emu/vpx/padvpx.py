#!/usr/bin/env python3
"""padvpx.py - the Visual Pinball kit: patch a table, register the controller,
name the card a title boots, start or stop a run by hand.

    padvpx patch "<table.vpx>" [--out DIR] [--card IMAGE]
        Recognise the table (each map carries the words that identify it:
        drhotwing's Rush, JP's Foo Fighters, marty02's Godzilla) and write
        "<name> (PAD).vpx" beside it (or into DIR), re-signed, with the
        Spike 2 emulator behind it. --card records which card image the
        title boots when Visual Pinball opens the table and no run is up.
    padvpx setup "<table.vpx>" <image.raw>
        The one step for a shared table: registers the controller if it is
        not, patches the table beside itself, records the card.
    padvpx lcd top | monitor <n> | <x> <y> <w> <h> | off
        Where the game's LCD window goes when the controller starts a run:
        on top of a full-screen Visual Pinball in the upper middle of the
        main screen (the default), filling screen n, or at a rectangle.
    padvpx card <title> <image.raw>      record a title's card (or `padvpx card`: list)
    padvpx library <dir>                  a directory of cards: the newest build of a title is its card
    padvpx register | unregister          PAD.Controller in the registry (this Python, this folder)
    padvpx run <title> [--hidden] [--mute]   start a run the way the controller would
    padvpx stop <title>                   stop a run padvpx or the controller started
    padvpx status                         the kit: controller, runs on the board, cards
    padvpx tables                         the tables this kit can patch

A run started here or by the controller takes a rig slot as PAD-VPX, visible
and with sound; nothing of the app's or a session's is touched.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import padlaunch   # noqa: E402
import vpxfile     # noqa: E402

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------------------------------------ the tables --

def maps():
    """Every map in this folder: {title: {"kind": shadow|mashup, "map": path,
    "detect": [words], "output": name}}."""
    out = {}
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".shadow.json") or f.endswith(".vpxmap.json"):
            m = json.load(open(os.path.join(HERE, f), encoding="utf-8"))
            title = m.get("title") or f.split(".")[0]
            out[title] = {"kind": "shadow" if f.endswith(".shadow.json") else "mashup",
                          "map": os.path.join(HERE, f), "detect": m.get("detect", []),
                          "output": m.get("output", "")}
    return out


def recognise(table_path):
    """Which title's map fits this table: every `detect` word of the map is
    in the table's script (case does not matter). None when no map does."""
    script = vpxfile.VpxTable(table_path).script().lower()
    for title, info in maps().items():
        words = [w.lower() for w in info["detect"]]
        if words and all(w in script for w in words):
            return title, info
    return None, None


def patch(table_path, outdir=None, card=None):
    title, info = recognise(table_path)
    if not title:
        print("this table is not one the kit knows; it can patch: %s" % ", ".join(
            "%s (%s)" % (t, ", ".join(i["detect"])) for t, i in maps().items()))
        return 2
    outdir = outdir or os.path.dirname(os.path.abspath(table_path))
    py = sys.executable
    if info["kind"] == "shadow":
        cmd = [py, os.path.join(HERE, "vpxshadow.py"), info["map"], table_path, outdir]
    else:
        cmd = [py, os.path.join(HERE, "patch_godzilla.py"), table_path, outdir]
    print("recognised %s: %s" % (title, " ".join(info["detect"])))
    r = subprocess.run(cmd)
    if r.returncode == 0 and card:
        padlaunch.remember_card(title, os.path.abspath(card))
        print("card for %s: %s" % (title, os.path.abspath(card)))
    if r.returncode == 0:
        print("open \"%s\" in Visual Pinball; the game starts with it when its card is known"
              % os.path.join(outdir, info["output"] or "<name> (PAD).vpx"))
    return r.returncode


# ------------------------------------------------------------- the runs ---

def run(title, hidden=False, mute=False):
    card = padlaunch.card_for(title)
    if not card:
        print("no card for %s (looked in %s)" % (title, padlaunch.card_places(title)))
        return 2
    launch = padlaunch.Launch(title, card)
    slot = launch.take_slot()
    env = launch.env()
    if hidden:
        env = [e for e in env if not e.startswith("PAD_HIDDEN=")] + ["PAD_HIDDEN=1"]
    if mute or hidden:
        env = [e for e in env if not e.startswith("PAD_AUDIO=")] + ["PAD_AUDIO=0"]
    head, launch.as_root = launch.head()
    cmd = head + env + ["bash", "%s/watch.sh" % launch.rig_wsl, str(launch.minutes)]
    out = open(launch.logfile, "ab")
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                     creationflags=_CREATE_NO_WINDOW)
    print("started %s on rig slot %d from %s (log %s)" % (title, slot, card, launch.logfile))
    return 0


def stop(title):
    from padcontroller import Rig
    rec = Rig.board_run(title)
    if not rec:
        print("no run of %s on the board" % title)
        return 1
    if rec.get("label") != padlaunch.LABEL:
        print("the run of %s on slot %s is %s's, not the kit's; leaving it"
              % (title, rec.get("slot"), rec.get("label") or "somebody"))
        return 1
    launch = padlaunch.Launch(title, "", dist=rec.get("distro"))
    slot = launch.slot = int(rec.get("slot"))
    launch.stop()
    print("stopped %s on slot %d" % (title, slot))
    return 0


def status():
    kit = padlaunch.kit_load()
    print("kit file: %s" % padlaunch.KIT)
    print("distro: %s" % (padlaunch.distro() or "the default"))
    print("rig: %s" % padlaunch.rig_dir())
    print("library: %s" % (os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or "(none)"))
    cards = kit.get("cards") or {}
    for t in sorted(set(maps()) | set(cards)):
        c = padlaunch.card_for(t)
        print("  %-18s %s" % (t, c or "no card"))
    from padcontroller import Rig, BOARD
    try:
        names = sorted(n for n in os.listdir(BOARD) if n.endswith(".run"))
    except OSError:
        names = []
    for n in names:
        try:
            rec = json.load(open(os.path.join(BOARD, n), encoding="utf-8"))
            print("run: slot %s %s (%s)" % (rec.get("slot"), rec.get("game"), rec.get("label")))
        except (OSError, ValueError):
            pass
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PAD.Controller\\CLSID")
        print("controller: registered (%s)" % winreg.QueryValue(k, None))
    except Exception:                                       # noqa: BLE001
        print("controller: NOT registered (padvpx register)")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "patch":
        outdir = card = None
        args = []
        i = 0
        while i < len(rest):
            if rest[i] == "--out" and i + 1 < len(rest):
                outdir = rest[i + 1]
                i += 2
            elif rest[i] == "--card" and i + 1 < len(rest):
                card = rest[i + 1]
                i += 2
            else:
                args.append(rest[i])
                i += 1
        if len(args) != 1:
            print(__doc__)
            return 2
        return patch(args[0], outdir, card)
    if cmd == "card":
        if len(rest) == 2:
            padlaunch.remember_card(rest[0], os.path.abspath(rest[1]))
            print("card for %s: %s" % (rest[0], os.path.abspath(rest[1])))
            return 0
        for t, c in sorted((padlaunch.kit_load().get("cards") or {}).items()):
            print("%-18s %s" % (t, c))
        return 0
    if cmd == "setup" and len(rest) == 2:
        # one step for a shared table: the controller registered, the table
        # patched beside itself, the title's card recorded
        d = padlaunch.kit_load()
        d["rig"] = RIG
        padlaunch.kit_save(d)
        try:
            import winreg
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PAD.Controller\\CLSID")
        except Exception:                                   # noqa: BLE001
            import padcontroller
            padcontroller.main(["--register"])
        return patch(rest[0], None, rest[1])
    if cmd == "lcd":
        # where the game's LCD window goes when the controller starts a run:
        # `padvpx lcd top` (on top, upper middle of the main screen),
        # `padvpx lcd monitor 2` (fills that screen), `padvpx lcd 100 0 960 540`
        d = padlaunch.kit_load()
        if rest and rest[0] == "monitor" and len(rest) == 2:
            d["lcd"] = {"monitor": int(rest[1]), "topmost": True}
        elif len(rest) == 4:
            d["lcd"] = {"x": int(rest[0]), "y": int(rest[1]), "w": int(rest[2]), "h": int(rest[3]), "topmost": True}
        elif rest and rest[0] == "top":
            d["lcd"] = {"topmost": True}
        elif rest and rest[0] == "off":
            d.pop("lcd", None)
        else:
            print(json.dumps(d.get("lcd", {"topmost": True}), indent=1))
            return 0
        padlaunch.kit_save(d)
        print("lcd: %s" % json.dumps(d.get("lcd")))
        return 0
    if cmd == "library" and len(rest) == 1:
        d = padlaunch.kit_load()
        d["library"] = os.path.abspath(rest[0])
        padlaunch.kit_save(d)
        print("library: %s" % d["library"])
        return 0
    if cmd in ("register", "unregister"):
        import padcontroller
        d = padlaunch.kit_load()
        d["rig"] = RIG
        padlaunch.kit_save(d)
        return padcontroller.main(["--" + cmd])
    if cmd == "run" and rest:
        return run(rest[0], hidden="--hidden" in rest, mute="--mute" in rest)
    if cmd == "stop" and rest:
        return stop(rest[0])
    if cmd == "status":
        return status()
    if cmd == "tables":
        for t, i in maps().items():
            print("%-18s %-7s %-40s %s" % (t, i["kind"], i["output"], ", ".join(i["detect"])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
