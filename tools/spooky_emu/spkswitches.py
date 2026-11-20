#!/usr/bin/env python3
"""spkswitches.py <rig> [title] - write <rig>/switches.json, the table the
virtual playfield (spkpf.py -> tools/ap_emu/appf.py) works from, in the
format tools/ap_emu/apswitches.py writes for an American Pinball game - so
the window, its keys and its BALLS panel are the same for both makers.

The switches are the running game's (spktitles.py: $SPK_TITLE, else the
title run_game.sh wrote in <rig>/title, else Beetlejuice).  The Spooky games
ship no playfield picture with switch positions, so the window is the
schematic view: every switch as a row - except Halloween and Ultraman, whose
switches have the manual's numbered spots (spktitles.PINOTAUR_SPOTS,
PAD-1468), drawn on a plain playfield.  [title] overrides the window's
title.

THE KEYS follow the AP/Stern window (every Warden game wires its cabinet
inputs to the same numbers; Halloween's Pinotaur has its own, from its
profile's "aliases"): 1 Start, 5 a coin, Space the Launch
button (the plunger), Down the Action button, T tilt, the arrows
the flippers (lower and upper together, as the game's own arrow keys do),
letters for playfield switches, Backspace/Esc, -, = and Enter the coin
door's BACK / - / + / SELECT, F Plunge, D Drain, Pause/F9 freeze.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spktitles  # noqa: E402

#: The same letters, in the same order, as apswitches.py (T, C, F, D are
#: tilt, the coin door, Plunge and Drain).
LETTERS = "ASZXQWGEOPMRNHJKLIUYVB"
#: apswitches.py's service names (appf.py looks the buttons up by them),
#: by the cabinet alias of each button.
SERVICE_KEYS = {"back": ("exit", ("Backspace", "Escape")),
                "down": ("down", ("Minus", "NumpadSubtract")),
                "up": ("up", ("Equal", "NumpadAdd")),
                "enter": ("enter", ("Enter", "NumpadEnter"))}
ACTIONS = ((("KeyF",), "plunge"), (("KeyD",), "drain"), (("KeyC",), "door"),
           (("Pause", "F9"), "pause"))
CABINET = range(80, 100)


def service(key=None):
    """The coin door's buttons of this title: {switch: (name, key codes)}."""
    al = spktitles.aliases(key)
    return {al[k]: v for k, v in SERVICE_KEYS.items() if k in al}


def cabinet(key=None):
    """Switches wired to the cabinet (Warden: 80-99, and whatever the
    title's aliases name)."""
    al = spktitles.aliases(key)
    # and every coin switch: Halloween's and Ultraman's COIN RIGHT (59) is
    # on the coin door but no alias names it (PAD-1468)
    coins = {n for n, name in spktitles.get(key)["switches"].items()
             if name.upper().startswith("COIN")}
    return (set(CABINET) | set(al.values()) | coins) - {al["shooter"]}


def title_key(rig=None):
    key = os.environ.get("SPK_TITLE")
    if not key and rig:
        try:
            with open(os.path.join(rig, "title")) as f:
                key = f.read().strip()
        except OSError:
            pass
    return key if key in spktitles.TITLES else "bj"


def name_of(n, t, svc):
    if n in svc:
        return svc[n][0]
    if n == t["shooter"]:
        return "shooter"
    if n in t["trough"]:
        return "trough%d" % (t["trough"].index(n) + 1)
    if n == t["jam"]:
        return "troughJam"
    words = t["switches"][n].title().split()
    return words[0].lower() + "".join(words[1:])


def group_of(n, t, cab):
    if n in cab:
        return "Cabinet"
    if n in t["trough"] or n == t["jam"] or n == t["shooter"] \
            or n in t["launch"].values():
        return "Trough"
    return "Playfield"


def table(title=None, key=None):
    key = key or title_key()
    t = spktitles.get(key)
    optos = spktitles.optos(key)
    # the flippers' end-of-stroke switches follow the flipper buttons on a
    # machine; they get no letter (the list still has them)
    eos = {n for n, name in t["switches"].items() if "EOS" in name.upper()}
    svc, cab, al = service(key), cabinet(key), spktitles.aliases(key)
    sws = [{"name": name_of(n, t, svc), "n": n, "type": "NC" if n in optos else "NO",
            "label": t["switches"][n].title(), "group": group_of(n, t, cab),
            "nc": n in optos}
           for n in sorted(t["switches"])]
    # where the manual puts them (Halloween, Ultraman: PAD-1468) - the window
    # draws them as its numbered spots on a plain playfield
    spots = t.get("spots") or {}
    for s in sws:
        if s["n"] in spots:
            spot, x, y = spots[s["n"]]
            s.update(x=x, y=y, spot=spot)
    by = {s["n"]: s for s in sws}
    rows, taken = [], set()

    def add(ns, keys, codes, cabinet, hold, unplaced=False):
        found = [by[n] for n in ns if n in by and n not in taken]
        if not found:
            return
        taken.update(s["n"] for s in found)
        # a switch on the manual's photo carries its spot number, so the key
        # panel reads as the photo's legend (PAD-1468)
        rows.append({"label": " + ".join(("%s %s" % (s["spot"], s["label"])) if s.get("spot")
                                         and s["group"] == "Playfield" else s["label"]
                                         for s in found), "keys": keys,
                     "codes": list(codes), "cabinet": cabinet,
                     "ns": [s["n"] for s in found], "hold": hold, "unplaced": unplaced})
    def cab(*names):
        return [al[n] for n in names if n in al]
    add(cab("start"), "1", ["Digit1", "Numpad1"], True, False)
    add(cab("coin"), "5", ["Digit5", "Numpad5"], True, False)
    add(cab("launch"), "Space", ["Space"], True, True)
    add(cab("action"), "Down", ["ArrowDown"], True, True)
    add(cab("tilt"), "T", ["KeyT"], True, False)
    add(cab("lflip", "ulflip"), "Left", ["ArrowLeft"], False, True)
    add(cab("rflip", "urflip"), "Right", ["ArrowRight"], False, True)
    letters = list(LETTERS)
    for s in sws:
        if (letters and s["group"] == "Playfield" and s["n"] not in taken
                and s["n"] not in eos):
            L = letters.pop(0)
            add([s["n"]], L, ["Key" + L], False, False)
    for s in sws:
        if s["n"] in taken or s["n"] in svc or s["group"] == "Trough":
            continue
        add([s["n"]], "", [], s["group"] == "Cabinet", False, unplaced=True)
    keymap = [{"codes": r["codes"], "ns": r["ns"], "action": None} for r in rows if r["codes"]]
    for n, (_name, codes) in svc.items():
        keymap.append({"codes": list(codes), "ns": [n], "action": None})
    for codes, action in ACTIONS:
        keymap.append({"codes": list(codes), "ns": [], "action": action})
    placed = bool(spots)
    return {"title": title or t["name"], "art": "",
            "size": t.get("spots_size") if placed else None,
            "spots": placed, "sketch": t.get("sketch") or [] if placed else [],
            "art_from": t.get("spots_from", "") if placed else "",
            "lights": [], "shooter": t["shooter"],
            "coin_door": None, "balls": t["balls"], "switches": sws,
            "rows": rows, "keymap": keymap}


def main(argv):
    if not argv:
        sys.exit(__doc__)
    out = os.path.join(argv[0], "switches.json")
    with open(out + ".tmp", "w") as f:
        json.dump(table(argv[1] if len(argv) > 1 else None,
                        title_key(argv[0])), f, indent=1)
    os.rename(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
