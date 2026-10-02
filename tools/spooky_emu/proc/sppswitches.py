#!/usr/bin/env python3
"""sppswitches.py <machine yaml> <title name> <shooter switch> > switches.json

The virtual playfield's table (tools/ap_emu/apswitches.py's format, the one
tools/spooky_emu/spkswitches.py writes for the Warden games) for a Spooky
P-ROC game - Rick and Morty, Alice Cooper's Nightmare Castle - from the
title's own machine yaml, the file the game itself loads.  run_game.sh writes
it beside the rig; the Emulate Spooky tab opens the same window on it as for
every other Spooky game (spkpf.py), and sppctl.py carries the window's
requests to the board.

A switch's number is the one proc_emu's board gives the yaml address
(prochw.Machine), so the window, the board and the game agree.  Run with a
Python 3 that has PyYAML (tools/ap_emu's py3 env: PAD-Runtime's python3 has
none).

THE KEYS are the AP/Stern window's, as on the Warden games: 1 Start, 5 a
coin, Space the Launch button, Down the Action button, T tilt, the arrows
the flippers, letters for playfield switches, Backspace/Esc, -, = and Enter
the coin door's EXIT / DOWN / UP / ENTER (both games' yaml name them exit,
down, up, enter - appf's own names), F Plunge, D Drain, Pause/F9 freeze.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

#: apswitches.py's letters, in its order (T, C, F, D are tilt, the coin
#: door, Plunge and Drain).
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"
SERVICE = {"exit": ("Backspace", "Escape"), "down": ("Minus", "NumpadSubtract"),
           "up": ("Equal", "NumpadAdd"), "enter": ("Enter", "NumpadEnter")}
ACTIONS = ((("KeyF",), "plunge"), (("KeyD",), "drain"), (("KeyC",), "door"),
           (("Pause", "F9"), "pause"))
#: the cabinet's buttons, by the yaml names both games use (Rick and Morty's
#: Action button is its "antigravity" button, wired among the flippers')
CABINET = re.compile(r"^(coin\d+|exit|down|up|enter|startButton|tilt|slamTilt|"
                     r"launchBall\w*|flipper\w+|antigravity|\w*EOS)$", re.I)
TROUGH = re.compile(r"^trough(\d+)$")
UNUSED = re.compile(r"^(sd)?\d+$", re.I)


#: what a cabinet switch is called when the yaml gives no label (Alice
#: Cooper's gives almost none)
CALLED = {"coin1": "Left Coin Slot", "coin2": "Right Coin Slot",
          "startButton": "Start", "launchBall": "Launch Ball",
          "launchBallButton": "Launch Ball", "flipperLwL": "Left Flipper",
          "flipperLwR": "Lower Right Flipper", "flipperUpR": "Upper Right Flipper",
          "flipperUpL": "Upper Left Flipper", "slingl": "Left Sling",
          "slingr": "Right Sling", "enter": "Service Enter", "up": "Service Up",
          "down": "Service Down", "exit": "Service Exit"}


def label_of(name, item):
    """The yaml's label (title-cased when it shouts), else what the switch
    is called (CALLED), else the name in words."""
    lab = str(item.get("label") or "").strip()
    if lab:
        return lab.title() if lab.isupper() else lab
    if name in CALLED:
        return CALLED[name]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()
    return " ".join(w[:1].upper() + w[1:] for w in words)


def used(name, item):
    """A switch the machine wires: not the yaml's unused SD<n> placeholders."""
    lab = str(item.get("label") or "").strip().lower()
    if lab == "unused" or name.lower() == "unused":
        return False
    return not UNUSED.match(name) or bool(lab)


def table(cfg, numbers, nc, title, shooter):
    """The table, from the parsed yaml *cfg* and the board's view of it:
    *numbers* name -> switch number, *nc* the NC numbers."""
    items = cfg.get("PRSwitches") or {}
    sws = []
    for name, item in items.items():
        item = item or {}
        name = str(name)
        if name not in numbers or not used(name, item):
            continue
        n = numbers[name]
        if name == shooter:
            group, sname = "Trough", "shooter"
        elif TROUGH.match(name) or name == "troughJam":
            group, sname = "Trough", name
        elif CABINET.match(name):
            group, sname = "Cabinet", name
        else:
            group, sname = "Playfield", name
        sws.append({"name": sname, "n": n, "type": "NC" if n in nc else "NO",
                    "label": label_of(name, item), "group": group, "nc": n in nc})
    sws.sort(key=lambda s: s["n"])
    by = {s["name"]: s for s in sws}
    rows, taken = [], set()

    def add(names, keys, codes, cabinet, hold, unplaced=False):
        found = [by[x] for x in names if x in by and by[x]["n"] not in taken]
        if not found:
            return
        taken.update(s["n"] for s in found)
        rows.append({"label": " + ".join(s["label"] for s in found), "keys": keys,
                     "codes": list(codes), "cabinet": cabinet,
                     "ns": [s["n"] for s in found], "hold": hold, "unplaced": unplaced})

    def first(*names):
        return [next((x for x in names if x in by), "")]
    add(["startButton"], "1", ["Digit1", "Numpad1"], True, False)
    add(["coin1"], "5", ["Digit5", "Numpad5"], True, False)
    add(first("launchBall", "launchBallButton"), "Space", ["Space"], True, True)
    add(["antigravity"], "Down", ["ArrowDown"], True, True)
    add(["tilt"], "T", ["KeyT"], True, False)
    add(["flipperLwL", "flipperUpL"], "Left", ["ArrowLeft"], False, True)
    add(["flipperLwR", "flipperUpR"], "Right", ["ArrowRight"], False, True)
    letters = list(LETTERS)
    for s in sws:
        if letters and s["group"] == "Playfield" and s["n"] not in taken:
            L = letters.pop(0)
            add([s["name"]], L, ["Key" + L], False, False)
    for s in sws:
        if s["n"] in taken or s["name"] in SERVICE or s["group"] == "Trough":
            continue
        add([s["name"]], "", [], s["group"] == "Cabinet", False, unplaced=True)
    keymap = [{"codes": r["codes"], "ns": r["ns"], "action": None} for r in rows if r["codes"]]
    for name, codes in SERVICE.items():
        if name in by:
            keymap.append({"codes": list(codes), "ns": [by[name]["n"]], "action": None})
    for codes, action in ACTIONS:
        keymap.append({"codes": list(codes), "ns": [], "action": action})
    game = cfg.get("PRGame") or {}
    return {"title": title, "art": "", "size": None, "art_from": "", "lights": [],
            "shooter": by["shooter"]["n"] if "shooter" in by else None,
            "coin_door": None,
            "balls": int(game.get("numBalls") or 0) or None,
            "switches": sws, "rows": rows, "keymap": keymap}


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    import yaml
    sys.path.insert(0, os.path.join(HERE, "..", "..", "proc_emu"))
    from prochw import Machine
    path, title, shooter = argv
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    m = Machine(path)
    json.dump(table(cfg, m.switches, m.nc, title, shooter), sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
