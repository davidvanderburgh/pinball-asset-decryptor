#!/usr/bin/env python3
"""vpxauthor.py - what a Visual Pinball table of a Spike 2 title needs, and
what a table has (PAD-941): the checklist for whoever builds or finishes one.

    python vpxauthor.py checklist <title> [--table <file.vpx>] [--out DIR] [--tables DIR]
    python vpxauthor.py machine <title> [--tables DIR]          the machine as JSON
    python vpxauthor.py data <title> [--table <file.vpx>]       the checklist as JSON (the app's sheet)
    python vpxauthor.py titles                                  the titles whose tables are on this PC
    python vpxauthor.py coverage [--tables DIR]                 per mapped title: how much its map wires

The real game behind a table (PAD.Controller, padcontroller.py) sees the
table only through the machine's own numbers: a switch id, a coil's node and
index, an LED's node and index. So what a table needs is exactly what the
game has, and that is in the title's device tables - the rig writes them on
the title's first run (`dump/tables/<title>/`: device_xy.txt and led_io.txt
out of the game binary, switch_list.txt out of the running game's own switch
table, group_node.txt the coils' addresses). This reads them and writes ONE
Markdown checklist:

  * every playfield switch (id, number, name, kind, where on the drawing) and
    what a table does for one of its kind;
  * every coil (node/index, the small solenoid number a map gives it, kind)
    and what fires it: the board from its own switch (flippers, slings,
    pops), or the game, which the table must act on;
  * every insert (lamp number, RGB or single, where), the cabinet and
    topper LEDs set aside;
  * the cabinet switches the kit's system script already presses.

With `--table`, a .vpx: what THAT table has (its triggers, kickers, targets,
bumpers, spinners, flippers, lights) and, when the kit has a map for it,
every machine part the map leaves out - switches with no table object,
coils nothing fires, inserts no light shows, and the places marked GUESS -
so an author can finish the integration part by part. A table the kit has
no map for gets a STARTER MAP beside the checklist (`<title>.starter.shadow.json`):
every switch, coil and insert of the machine listed in the shape
vpxshadow.py reads, each waiting for the table object's name.

Nothing here runs the game or touches the card; the tables must be there
(the title played once in the app or through a table). The last line of
`checklist` is one JSON object (the tab reads it).
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

TABLE_FILES = ("device_xy.txt", "led_io.txt", "switch_list.txt", "group_node.txt")

#: the hint column: what a Visual Pinball table does for a part of this kind
SWITCH_HINTS = {
    "trough": "cvpmBallStack on TROUGH 1..n + JAM (the map's `trough`); the game fires TROUGH",
    "shooter": "a Trigger in the shooter lane, held while the ball rests (`plunger.lane_trigger`)",
    "flipper button": "the key: PADSPIKE2.vbs presses it (`cabinet`); the BOARD fires the flipper",
    "flipper eos": "nothing: the board reads it; leave it unwired",
    "slingshot": "the Wall's Slingshot event (`event: slingshot`); the board fires the coil",
    "pop bumper": "a Bumper, Hit (`event: hit`); the board fires the coil",
    "drop target": "a drop HitTarget, Hit; its bank's reset coil in `solenoids`",
    "target": "a standup HitTarget, Hit (`event: hit`)",
    "spinner": "a Spinner, Spin (`event: spin`)",
    "opto": "a Trigger on the ball's path, Hit (`event: hit`); `event: pass` for a spinner where the machine "
            "has an opto",
    "lane": "a Trigger across the lane, Hit (`event: hit`)",
    "lock": "a Kicker holding the ball (`saucers`: the switch it holds, the coil that empties it)",
    "saucer": "a Kicker holding the ball (`saucers`: the switch it holds, the coil that empties it)",
    "magnet": "a Trigger over the magnet, Hit/UnHit held (`event: hold`); the coil a cvpmMagnet",
    "mech": "a moving part's end stop: `switch_fakes` answers it when the table has no object",
    "virtual": "nothing: the game makes it itself",
    "unnamed": "nothing yet: this build's switch table has no name for it, so no part is known",
    "cabinet": "PADSPIKE2.vbs presses it from the key (`cabinet`)",
    "other": "a Trigger or HitTarget where the drawing puts it, Hit (`event: hit`)",
}

COIL_HINTS = {
    "flipper": "a Flipper; the board fires it from its button (core.vbs UseSolenoids=2, `game_on`)",
    "trough": "`solenoids` -> bsTrough.SolOut: serves a ball",
    "auto plunger": "`solenoids` -> PadAutoPlunge: launches the ball",
    "slingshot": "the board fires it from the slingshot switch; the table's own kick animates",
    "pop bumper": "the board fires it from the bumper's switch",
    "drop reset": "`solenoids` -> a sub that resets the bank's drop targets",
    "post": "`solenoids` -> a Wall or Kicker raised/lowered with the coil",
    "gate": "`solenoids` -> a Gate or diverter turned with the coil",
    "magnet": "`solenoids` -> cvpmMagnet MagnetOn",
    "motor": "`solenoids` or `switch_fakes`: a moving part, its end stops answered",
    "kick": "`solenoids` -> the Kicker's SolOut (`saucers`): the game empties it",
    "cabinet": "nothing on the table: a cabinet part (DOF, if any)",
    "other": "`solenoids` -> a sub of the table's, or null when the table has nothing for it",
}

_SW_KINDS = (
    ("virtual", r"VIRTUAL|RESET DETECTED|FIRED\b"),
    ("cabinet", r"QR SCANNER|\bDIP\b|SERVICE|HEADPHONE|VOLUME|COIN|START BUTTON|TOURNAMENT|TILT|SLAM|"
                r"ACTION BUTTON|LOCKDOWN|TICKET|DOOR|TOPPER|KNOCKER"),
    ("mech", r"DIVERTER|MOTOR|STEPPER|ENCODER"),
    ("flipper eos", r"FLIP(PER)?\s*(EOS|E\.O\.S)"),
    ("flipper button", r"FLIP(PER)?\s*BUTTON|FLIP BUTTON"),
    ("trough", r"\bTROUGH\b"),
    ("shooter", r"SHOOTER LANE|PLUNGER LANE|BALL LAUNCH"),
    ("slingshot", r"SLING"),
    ("pop bumper", r"POP BUMPER|\bPOP\b|JET BUMPER|\bJETS\b|BUMPER"),
    ("drop target", r"DROP"),
    ("spinner", r"SPINNER"),
    ("magnet", r"MAGNET"),
    ("mech", r"MOTOR|HOME\b|STEPPER|ENCODER|STOPPED|\bUP\b$|\bDOWN\b$|OPEN$|CLOSED$|DIVERTER"),
    ("lock", r"\bLOCK\b"),
    ("saucer", r"SCOOP|\bVUK\b|EJECT|SAUCER|HOLE|KICKOUT|SUBWAY"),
    ("target", r"TARGET|\bTGT\b|STANDUP|CAPTIVE|\bBANK\b"),
    ("opto", r"OPTO|\bENTER\b|\bEXIT\b|\bMADE\b|\bRAMP\b"),
    ("lane", r"LANE|OUTLANE|INLANE|ORBIT|LOOP|ROLLOVER|SKILL|RETURN"),
)

_COIL_KINDS = (
    ("cabinet", r"SHAKER|METER|TICKET|KNOCKER|BEACON|COIN|TOPPER|BACKBOX"),
    ("flipper", r"FLIP"),
    ("trough", r"\bTROUGH\b|BALL RELEASE"),
    ("auto plunger", r"AUTO\s*(PLUNGE|LAUNCH)|LAUNCHER|BALL LAUNCH"),
    ("slingshot", r"SLING"),
    ("pop bumper", r"POP|JET BUMPER|\bJETS\b|BUMPER"),
    ("drop reset", r"DROP|RESET"),
    ("magnet", r"MAGNET"),
    ("motor", r"MOTOR|STEPPER|BUILDING|BRIDGE|LIFT|DISC|SPIN"),
    ("gate", r"GATE|DIVERTER"),
    ("post", r"\bPOST\b|STOPPER"),
    ("kick", r"SCOOP|\bVUK\b|EJECT|KICK|LOCK|SAUCER|SUBWAY|HOLE"),
)

#: coils the node boards fire from their own switch (hwshim's coil rules):
#: a table owes the switch, never the coil. Cabinet parts have no table side.
BOARD_COILS = ("flipper", "slingshot", "pop bumper", "cabinet")

#: PAD-943: what a table can never have, so is not owed: a mech's own
#: position switches (motor home/away, encoder optos, a reel's home), a switch
#: or coil the game itself leaves unnamed, a meter or ticket drive
_NOT_OWED_SW = re.compile(r"REEL HOME|^SWITCH #\d+$|MOTOR|ENCODER|STEPPER|POS\.|HOME|AWAY|EOS|E\.O\.S", re.I)
_NOT_OWED_COIL = re.compile(r"^COIL #\d+$|OPTIONAL|METER|TICKET|TEST FIXTURE|^AUX ", re.I)


def owed_switch(s):
    """A playfield switch a table owes the game: one with an id, not the
    board's flipper EOS, not unnamed, not a mech's own position."""
    return (s["where"] in ("playfield", "unplaced") and bool(s["id"])
            and s["kind"] not in ("flipper eos", "unnamed", "mech")
            and not _NOT_OWED_SW.search(s["name"] or ""))


def owed_coil(c):
    """A coil a table owes: on the bus, not one the board fires itself, not
    one the game leaves unnamed."""
    return (c["node"] is not None and c["kind"] not in BOARD_COILS
            and not _NOT_OWED_COIL.search(c["name"] or ""))

#: LEDs that are not on the playfield, by name (vpxlamps.NOT_PLAYFIELD's
#: rule, with the topper boards' rows set aside by node as well)
NOT_PLAYFIELD = re.compile(r"SPEAKER|TOPPER|BACKBOX|CABINET|COIN|START BUTTON|TOURNAMENT|LOCKDOWN|"
                           r"SHOOTER ILLUM|FLIPPER BUTTON|\bGI\d*\b|GEN(ERAL)? ILLUM|MOTOR|"
                           r"QR SCANNER|ACTION BUTTON|BEACON", re.I)


def _kind(name, table, default):
    up = (name or "").upper()
    for kind, rx in table:
        if re.search(rx, up):
            return kind
    return default


def switch_kind(name):
    if (name or "").strip() in ("", "?"):
        return "unnamed"             # the game's table names it "?" (swnames could not): nothing to build
    return _kind(name, _SW_KINDS, "other")


def coil_kind(name):
    return _kind(name, _COIL_KINDS, "other")


def lamp_number(node, index):
    return 1000 + node * 100 + index


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


# ------------------------------------------------------------ the tables --

def _lines(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []


def read_device_xy(path):
    """Every row of device_xy.txt: {kind, name, x, y, w, h, group, index,
    conn, image}, and the header's playfield image name and size."""
    rows, image, size, binary = [], "", None, ""
    for ln in _lines(path):
        if ln.startswith("#"):
            m = re.search(r"playfield image:\s*(\S+)\s*\((\d+)x(\d+)\)", ln)
            if m:
                image, size = m.group(1), (int(m.group(2)), int(m.group(3)))
            m = re.search(r"^#\s*binary:\s*(.*)$", ln)
            if m:
                binary = m.group(1).strip()
            continue
        p = ln.split()
        if len(p) < 10 or p[0] not in ("switch", "coil", "led"):
            continue
        # name, then x y w h grp index (six ints), then the connector (one
        # word, or two: Bond's topper rows say "Topper 105-B"), then the image
        at = None
        for i in range(1, len(p) - 7):
            if all(_isint(t) for t in p[i:i + 6]) and not _isint(p[i + 6]):
                at = i
                break
        if at is None:
            continue
        x, y, w, h, grp, idx = (int(t) for t in p[at:at + 6])
        rows.append({"kind": p[0], "name": " ".join(p[1:at]), "x": x, "y": y, "w": w, "h": h,
                     "group": grp, "index": idx, "conn": " ".join(p[at + 6:-1]), "image": p[-1]})
    return rows, image, size, binary


def _isint(t):
    return bool(re.match(r"^-?\d+$", t))


def read_switch_list(path):
    """switch_list.txt: [{id, num, node, bit, name}]."""
    out = []
    for ln in _lines(path):
        f = ln.split(None, 4)
        if len(f) == 5 and f[0].isdigit():
            out.append({"id": int(f[0]), "num": int(f[1]), "node": int(f[2]), "bit": int(f[3]),
                        "name": f[4].strip()})
    return out


def read_led_io(path):
    """led_io.txt: [{node, index, name, x, y, image}] (image "-" = unplaced)."""
    out = []
    rx = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S.*?)\s{2,}(-?\d+)\s+(-?\d+)\s+(\S+)\s*(.*)$")
    for ln in _lines(path):
        if ln.startswith("#"):
            continue
        m = rx.match(ln)
        if m:
            out.append({"node": int(m.group(1)), "index": int(m.group(2)), "name": m.group(3).strip(),
                        "x": int(m.group(4)), "y": int(m.group(5)), "image": m.group(7).strip() or "-"})
    return out


def read_group_node(path):
    out = {}
    for ln in _lines(path):
        f = ln.split()
        if len(f) >= 2 and f[0].isdigit() and f[1].isdigit():
            out[int(f[0])] = int(f[1])
    return out


def _is_playfield(image):
    return "playfield" in (image or "").lower()


def _led_where(node, name, image):
    if _is_playfield(image) and not NOT_PLAYFIELD.search(name):
        return "playfield"
    if node >= 12 or "topper" in (image or "").lower() or "TOPPER" in name.upper():
        return "topper"
    if image and image != "-":
        return "cabinet"
    return "unplaced" if not NOT_PLAYFIELD.search(name) else "cabinet"


def _base(name):
    """An RGB channel's insert: `LEFT RAMP-R` -> `LEFT RAMP`."""
    return re.sub(r"[- ](R|G|B|RED|GRN|GREEN|BLU|BLUE)$", "", name.strip(), flags=re.I)


def read_machine(tables_dir, title=None, files=None):
    """The machine, from a title's device tables. `files` names where each
    table file is (several directories may each hold a part); else all of
    them in `tables_dir`."""
    files = dict(files or {})
    for f in TABLE_FILES:
        files.setdefault(f, os.path.join(tables_dir or "", f))
    rows, image, size, binary = read_device_xy(files["device_xy.txt"])
    swlist = read_switch_list(files["switch_list.txt"])
    leds = read_led_io(files["led_io.txt"])
    gn = read_group_node(files["group_node.txt"])
    if not leds:
        # an empty led_io.txt (rush_le 1.19's on one rig): the same LEDs are
        # the device table's led rows, their node through group_node
        leds = [{"node": gn[r["group"]], "index": r["index"], "name": r["name"], "x": r["x"], "y": r["y"],
                 "image": r["image"] if _is_playfield(r["image"]) else "-"}
                for r in rows if r["kind"] == "led" and r["group"] in gn]

    # switches: the running game's ids, positions joined on the name
    by_name = {}
    for r in rows:
        if r["kind"] == "switch":
            by_name.setdefault(_norm(r["name"]), r)
    switches = []
    seen = set()
    cab_nodes = {s["node"] for s in swlist if switch_kind(s["name"]) == "cabinet"
                 and "FLIPPER" not in s["name"].upper() and s["node"] < 8}
    for s in swlist:
        dev = by_name.get(_norm(s["name"]))
        seen.add(_norm(s["name"]))
        placed = bool(dev and _is_playfield(dev["image"]))
        kind = switch_kind(s["name"])
        if kind == "other" and s["node"] in cab_nodes and not placed:
            kind = "cabinet"                     # an unnamed-kind switch on the cabinet's node
        switches.append({"id": s["id"], "num": s["num"], "node": s["node"], "bit": s["bit"],
                         "name": s["name"], "kind": kind,
                         "x": dev["x"] if placed else None, "y": dev["y"] if placed else None,
                         "where": "cabinet" if kind == "cabinet" else "virtual" if kind == "virtual"
                         else "playfield" if placed else "unplaced"})
    for r in rows:                                   # named in the binary, not in the game's table
        if r["kind"] == "switch" and _norm(r["name"]) not in seen:
            kind = switch_kind(r["name"])
            placed = _is_playfield(r["image"])
            switches.append({"id": None, "num": None, "node": gn.get(r["group"]), "bit": None,
                             "name": r["name"], "kind": kind,
                             "x": r["x"] if placed else None, "y": r["y"] if placed else None,
                             "where": "cabinet" if kind == "cabinet" else "virtual" if kind == "virtual"
                             else "playfield" if placed else "unplaced"})

    coils = []
    for r in rows:
        if r["kind"] == "coil":
            node = gn.get(r["group"])
            coils.append({"name": r["name"], "node": node, "index": r["index"], "kind": coil_kind(r["name"]),
                          "x": r["x"] if _is_playfield(r["image"]) else None,
                          "y": r["y"] if _is_playfield(r["image"]) else None,
                          "number": lamp_coil_number(node, r["index"]) if node is not None else None})

    # inserts: an RGB insert's three channels are one
    groups = {}
    for ld in leds:
        key = (_base(ld["name"]), ld["node"], ld["image"])
        g = groups.setdefault(key, {"name": _base(ld["name"]), "leds": [], "names": [], "x": ld["x"],
                                    "y": ld["y"], "image": ld["image"],
                                    "where": _led_where(ld["node"], ld["name"], ld["image"])})
        g["leds"].append((ld["node"], ld["index"]))
        g["names"].append(ld["name"])
    import padcontroller
    inserts = []
    for g in groups.values():
        pairs = sorted(zip(g["leds"], g["names"]), key=lambda p: p[0][1])   # each LED keeps its name
        g["leds"], g["names"] = [p[0] for p in pairs], [p[1] for p in pairs]
        g["rgb"] = len(g["leds"]) == 3 and all(re.search(r"[- ](R|G|B|RED|GRN|GREEN|BLU|BLUE)$", n, re.I)
                                               for n in g["names"])
        # the order they are listed in when not R, G, B (PAD-1097: Aerosmith's BLU, GRN, RED)
        g["rgb_order"] = padcontroller.rgb_channels(g["names"]) if g["rgb"] else None
        if len(g["leds"]) == 1:
            g["name"] = g["names"][0]                 # a lone "TOPPER 105-B" is not a blue channel
        if not g["rgb"] and len(g["leds"]) > 1:
            # same base name, not an RGB triple (TOPPER rows, GI strings): one row each
            for (node, idx), nm in zip(g["leds"], g["names"]):
                inserts.append(dict(g, name=nm, leds=[(node, idx)], names=[nm], rgb=False,
                                    lamp=lamp_number(node, idx)))
            continue
        g["lamp"] = lamp_number(*g["leds"][0])
        inserts.append(g)
    inserts.sort(key=lambda g: g["leds"][0])
    # a build that ships no positions at all (rush_le 1.19, turtles_pro):
    # its playfield inserts are the unplaced ones, listed with no place
    if not any(g["where"] == "playfield" for g in inserts):
        for g in inserts:
            if g["where"] == "unplaced":
                g["where"] = "playfield"
                g["x"] = g["y"] = None

    return {"title": title or "", "binary": binary, "image": image, "image_size": size,
            "tables_from": os.path.dirname(files["device_xy.txt"]),
            "have": {f: os.path.isfile(files[f]) for f in TABLE_FILES},
            "positions": any(_is_playfield(r["image"]) for r in rows),
            "switches": switches, "coils": coils, "inserts": inserts}


def coils_from_map(m):
    """A build whose device table names no coil (rush_le 1.19) still has
    them in its map: `solenoids`, `game_on`, the trough's kick and the
    fakes' coils, as coil rows with no place."""
    out = {}
    for num, v in _entries(m.get("solenoids")):
        c = v.get("coil")
        if c and len(c) == 2:
            out[tuple(c)] = v.get("name") or "coil %s/%s" % tuple(c)
    for c in (m.get("game_on") or {}).get("coils") or []:
        out.setdefault(tuple(c), "FLIPPER")
    kick = (m.get("trough") or {}).get("kick")
    if kick and len(kick) == 2:
        out.setdefault(tuple(kick), "TROUGH")
    for obj, v in _entries(m.get("switch_fakes")):
        for k in ("coil", "up", "down"):
            if v.get(k):
                out.setdefault(tuple(v[k]), v.get("name") or obj.upper())
    return [{"name": name, "node": n, "index": i, "kind": coil_kind(name), "x": None, "y": None,
             "number": lamp_coil_number(n, i)} for (n, i), name in sorted(out.items())]


def inserts_from_map(m):
    """A build whose device table names no LED (rush_le 1.19): the inserts
    its map lights, one per LED group, with no place."""
    out = {}
    for sect in (m.get("lamps"), m.get("lamp_calls"), (m.get("retrofit_lights") or {}).get("lights")):
        for obj, v in _entries(sect):
            leds = [tuple(x) for x in v.get("leds") or []]
            if not leds:
                continue
            key = leds[0]
            name = re.sub(r"\s*\(.*$", "", v.get("name") or obj)
            g = out.setdefault(key, {"name": name, "leds": leds, "names": [name], "x": None, "y": None,
                                     "image": "-", "where": "playfield", "rgb": bool(v.get("rgb")),
                                     "lamp": lamp_number(*key)})
            g["rgb"] = g["rgb"] or bool(v.get("rgb"))
    return [out[k] for k in sorted(out)]


def lamp_coil_number(node, index):
    """The controller's own number for a coil (PADSPIKE2.vbs: 1000 + node*16 + index)."""
    return 1000 + node * 16 + index


# ---------------------------------------------------- where the tables are --

def _win(distro, posix):
    return r"\\wsl.localhost\%s%s" % (distro, posix.replace("/", "\\"))


_ROOTS = None


# ------------------------------------------- a Spike 1 title (PAD-943) --
#
# A Spike 1 title has no device_xy.txt: its parts come out of its game ELF
# (tools/spike1_emu/s1elf.py: the coils and LEDs by node and position, named
# where the game names them) and its switch map (the rig's curated
# switchmaps/<CARD>.json, else the run's own s1switches.json). The ELF is
# the extracted game in a Spike 1 work dir's cache (<work>/cache/<CARD>/game/
# <exe>); no build ships positions, so every part is listed unplaced.

def _s1elf():
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "spike1_emu", "s1elf.py")
    spec = importlib.util.spec_from_file_location("_s1elf", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_S1_WORKS = None


def spike1_works():
    """The Spike 1 work dirs on this PC as Windows sees them: PAD_S1_WORK,
    the app's data disk, each distro's ~/s1emu. Asked of WSL once."""
    global _S1_WORKS
    if _S1_WORKS is not None:
        return _S1_WORKS
    out = []

    def add(d):
        if d and d not in out:
            out.append(d)
    env = os.environ.get("PAD_S1_WORK")
    if env:
        add(env)
    try:
        import padlaunch
        dists = padlaunch.distros()
        first = padlaunch.distro()
        for dist in ([first] if first in dists else []) + [d for d in dists if d != first]:
            try:
                work = padlaunch.app_work(dist, "spike1") if dist == first else ""
            except Exception:                               # noqa: BLE001
                work = ""
            if work:
                add(_win(dist, work))
            try:
                _, acct = padlaunch.account(dist)
            except Exception:                               # noqa: BLE001
                acct = ""
            if acct:
                add(_win(dist, acct + "/s1emu"))
    except Exception:                                       # noqa: BLE001
        pass
    _S1_WORKS = out
    return out


def _s1_card_stem(name):
    """`GOT_LE-1_37` -> (`GOT_LE`, `got_le`): the card's stem and the title."""
    stem = name.split("-")[0]
    return stem, stem.lower()


def spike1_titles(works=None):
    """{title: (card stem, elf path)} for every Spike 1 game extracted on this PC."""
    out = {}
    for w in (spike1_works() if works is None else works):
        try:
            names = sorted(os.listdir(os.path.join(w, "cache")))
        except OSError:
            continue
        for n in names:
            stem, title = _s1_card_stem(n)
            game = os.path.join(w, "cache", n, "game")
            try:
                exe = open(os.path.join(game, ".game_exe"), encoding="utf-8").read().strip() or "game"
            except OSError:
                exe = "game"
            elf = os.path.join(game, exe)
            if os.path.isfile(elf) and title not in out:
                out[title] = (stem, elf)
    return out


def spike1_sources(title, works=None):
    """{elf, switchmap} for a Spike 1 title, or {} when it is not extracted
    here. The switch map: the rig's curated one for the card, else the
    newest s1switches.json of a work dir whose game is this title."""
    got = spike1_titles(works).get(title)
    if not got:
        return {}
    stem, elf = got
    curated = os.path.join(os.path.dirname(os.path.dirname(HERE)), "spike1_emu", "switchmaps", stem + ".json")
    swmap = curated if os.path.isfile(curated) else ""
    if not swmap:
        best = None
        for w in (spike1_works() if works is None else works):
            p = os.path.join(w, "s1switches.json")
            try:
                if _s1_card_stem(os.path.basename(os.path.realpath(os.path.join(w, "game"))))[1] != title:
                    continue
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, p)
        swmap = best[1] if best else ""
    return {"elf": elf, "switchmap": swmap}


def read_machine_spike1(title, elf, switchmap=""):
    """The machine of a Spike 1 title, in read_machine's shape: switches
    from the switch map (id = node * 64 + index, the rig's numbering),
    coils and inserts from the ELF; nothing placed."""
    import s1bridge
    s1elf = _s1elf()
    names = s1bridge.read_names(switchmap) if switchmap else {}
    switches = []
    for (node, idx), name in sorted(names.items()):
        kind = switch_kind(name)
        if kind == "other" and node < 8:
            kind = "cabinet"                     # the cabinet's node (node 1 on GOT)
        switches.append({"id": s1bridge.slot(node, idx), "num": None, "node": node, "bit": idx,
                         "name": name, "kind": kind, "x": None, "y": None,
                         "where": "cabinet" if kind == "cabinet" else "virtual" if kind == "virtual"
                         else "unplaced"})
    coils = []
    for (node, idx), name in sorted(s1elf.extract_coil_map(elf).items()):
        coils.append({"name": name, "node": node, "index": idx, "kind": coil_kind(name), "x": None, "y": None,
                      "number": s1bridge.sol_number(node, idx)})
    inserts = []
    for (node, idx), name in sorted(s1elf.extract_led_map(elf).items()):
        nm = name or "LED %d/%d" % (node, idx)
        inserts.append({"name": nm, "leds": [(node, idx)], "names": [nm], "x": None, "y": None, "image": "-",
                        "where": "cabinet" if node < 8 else "playfield", "rgb": False, "lamp": lamp_number(node, idx)})
    return {"title": title, "platform": "spike1", "binary": os.path.basename(elf), "image": "", "image_size": None,
            "tables_from": os.path.dirname(elf),
            # the names the Spike 2 reader's notes ask about: the ELF is the device table
            "have": {"device_xy.txt": True, "led_io.txt": True, "switch_list.txt": bool(switchmap),
                     "elf": True, "switchmap": bool(switchmap)}, "positions": False,
            "switches": switches, "coils": coils, "inserts": inserts}


# ------------------------------------------------ Spooky titles (PAD-952) --
#
# A Spooky game's switches and coils are its rig profile's
# (tools/spooky_emu/spktitles.py: SwitchConfig.cs and CoilConfig.cs, by
# number); its LEDs are the update's own config/lightconfig.json, read from
# the rig's prepared build when one is on this PC.

def _spktitles():
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "spooky_emu", "spktitles.py")
    spec = importlib.util.spec_from_file_location("spktitles", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: the titles a Visual Pinball table plays on the Spooky rig (padlaunch's
#: update files): the authors' card and the coverage know them
def spooky_titles():
    import padlaunch
    return sorted(t for t in padlaunch.SPOOKY_UPDATES if padlaunch.card_for(t, "spooky"))


def spooky_lightconfig(title):
    """The prepared build's config/lightconfig.json for `title` on this PC
    (PAD_SPOOKY_CACHE, else each distro's /var/tmp/pad_spooky/cache), or ""."""
    import glob
    roots = [os.environ["PAD_SPOOKY_CACHE"]] if os.environ.get("PAD_SPOOKY_CACHE") else []
    if not roots:
        try:
            import padlaunch
            for dist in padlaunch.distros():
                roots.append(_win(dist, "/var/tmp/pad_spooky/cache"))
        except Exception:                                   # noqa: BLE001
            pass
    for root in roots:
        found = sorted(glob.glob(os.path.join(root, title + "_*", "config", "lightconfig.json")))
        if found:
            return found[-1]
    return ""


#: Spooky cabinet switches by name: a table does not owe them
_SPOOKY_CABINET = re.compile(r"COIN|MENU|VOLUME|FLIPPER BUTTON|LAUNCH BUTTON|START BUTTON|^TILT$", re.I)


def read_machine_spooky(title, lights=None):
    """The machine of a Spooky title, in read_machine's shape: the switch,
    coil and LED numbers are the game's own (spkbridge.py), so a switch's
    id is its number, a coil is (0, n) - a subway servo (0, 32 + s) - and
    an LED n is (n // 64, n % 64). Nothing placed."""
    import padlaunch
    if title in padlaunch.SPOOKY_PROC:
        return read_machine_spooky_proc(title)
    prof = _spktitles().TITLES[title]
    switches = []
    for n, name in sorted(prof["switches"].items()):
        kind = "cabinet" if _SPOOKY_CABINET.search(name) else switch_kind(name)
        switches.append({"id": n, "num": n, "node": None, "bit": None, "name": name, "kind": kind,
                         "x": None, "y": None, "where": "cabinet" if kind == "cabinet" else "unplaced"})
    coils = [{"name": name, "node": 0, "index": n, "kind": coil_kind(name), "x": None, "y": None,
              "number": 1000 + n} for n, name in sorted((prof.get("coils") or {}).items())]
    coils += [{"name": name, "node": 0, "index": 32 + s, "kind": "other", "x": None, "y": None,
               "number": 1032 + s} for s, name in sorted((prof.get("servos") or {}).items())]
    lights = spooky_lightconfig(title) if lights is None else lights
    inserts = []
    try:
        table = json.load(open(lights, encoding="utf-8")) if lights else {}
    except (OSError, ValueError):
        table = {}
    for key, v in sorted(table.items(), key=lambda kv: kv[1].get("num", 0)):
        n = int(v.get("num", 0))
        nm = v.get("label") or key
        strip = "light_strip" in nm.lower()          # the playfield's edge strips: lit by shows, not inserts
        inserts.append({"name": nm, "leds": [(n // 64, n % 64)], "names": [nm], "x": None, "y": None,
                        "image": "-", "where": "cabinet" if strip else "playfield", "rgb": True,
                        "lamp": lamp_number(n // 64, n % 64)})
    return {"title": title, "platform": "spooky", "binary": "Assembly-CSharp.dll", "image": "",
            "image_size": None, "tables_from": os.path.dirname(os.path.dirname(lights)) if lights else "",
            "have": {"device_xy.txt": True, "led_io.txt": bool(table), "switch_list.txt": True},
            "positions": False, "switches": switches, "coils": coils, "inserts": inserts}


# ------------------------------- Spooky's P-ROC titles (PAD-954) --
#
# Alice Cooper's Nightmare Castle runs on the P-ROC rig (tools/spooky_emu/
# proc); its switches, coils and LEDs are its machine yaml's, read from the
# rig's prepared build: a switch is the board's number (SD24 = 24), a coil
# and an LED their places in PRCoils and PRLEDs (spkbridge.py).

def spooky_proc_yaml(title):
    """The prepared build's machine yaml for a P-ROC `title` on this PC
    (PAD_SPOOKY_PROC_CACHE, else each distro's /var/tmp/pad_spkproc/cache),
    or ""."""
    import glob
    import padlaunch
    rel = padlaunch.SPOOKY_PROC.get(title)
    if not rel:
        return ""
    roots = [os.environ["PAD_SPOOKY_PROC_CACHE"]] if os.environ.get("PAD_SPOOKY_PROC_CACHE") else []
    if not roots:
        try:
            for dist in padlaunch.distros():
                roots.append(_win(dist, "/var/tmp/pad_spkproc/cache"))
        except Exception:                                   # noqa: BLE001
            pass
    for root in roots:
        found = sorted(glob.glob(os.path.join(root, title + "_*", *rel.split("/"))))
        if found:
            return found[-1]
    return ""


def read_machine_yaml(path):
    """{section: {name: {key: value}}} of a pyprocgame machine yaml, in its
    order. Its two levels (a section, its items, their fields) are all a
    table needs, and the app ships no YAML library, so the lines are read
    as they stand."""
    out, sec, item = {}, None, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.split(" #", 1)[0].rstrip()
            if not line.strip() or line.lstrip().startswith(("#", "-")):
                continue
            ind = len(line) - len(line.lstrip())
            key, _, val = line.strip().partition(":")
            val = val.strip().strip("'\"")
            if ind == 0:
                sec, item = key, None
                out[sec] = {}
            elif sec is not None and not val and (item is None or ind <= item[1]):
                item = (key, ind)
                out[sec][key] = {}
            elif sec is not None and item is not None and ind > item[1]:
                out[sec][item[0]][key] = val
            elif sec is not None:
                out[sec][key] = {"_": val}
    return out


def _proc_switch_number(text):
    """pyprocgame's number of a PDB yaml switch address (prochw.Machine)."""
    up = (text or "").strip().upper()
    if up.startswith("SD") and up[2:].isdigit():
        return int(up[2:])
    if "/" in up:
        col, row = up.split("/")[:2]
        return 32 + int(col) * 16 + int(row)
    return int(up) if up.isdigit() else None


#: a P-ROC yaml's cabinet switches by name: a table does not owe them
_PROC_CABINET = re.compile(r"^(coin\d*|enter|up|down|exit|tilt|slamTilt|startButton|launchBall\w*|flipper\w+)$",
                           re.I)


def read_machine_spooky_proc(title, path=None):
    """The machine of a Spooky P-ROC title, in read_machine's shape, from its
    machine yaml: switch id = the board's number, coil n = (0, n) and LED n
    = (n // 64, n % 64) by their places in the yaml. Unused SD<n> switches
    are left out; the GI and the flashers are not inserts a table owes."""
    path = spooky_proc_yaml(title) if path is None else path
    cfg = read_machine_yaml(path) if path and os.path.isfile(path) else {}
    switches = []
    for name, v in (cfg.get("PRSwitches") or {}).items():
        n = _proc_switch_number(v.get("number", ""))
        if n is None or (re.match(r"^SD\d+$", name, re.I) and not v.get("label")):
            continue                                 # a spare input (SD29 has a label: it is wired)
        label = v.get("label") or name
        kind = "cabinet" if _PROC_CABINET.match(name) else switch_kind(label)
        switches.append({"id": n, "num": n, "node": None, "bit": None, "name": label, "kind": kind,
                         "x": None, "y": None, "where": "cabinet" if kind == "cabinet" else "unplaced"})
    switches.sort(key=lambda s: s["id"])
    coils = [{"name": name, "node": 0, "index": i, "kind": coil_kind(v.get("label") or name), "x": None,
              "y": None, "number": 1000 + i} for i, (name, v) in enumerate((cfg.get("PRCoils") or {}).items())]
    inserts = []
    for i, (name, v) in enumerate((cfg.get("PRLEDs") or {}).items()):
        nm = v.get("label") or name
        tags = {t.strip().lower() for t in v.get("tags", "").split(",")}
        inserts.append({"name": nm, "leds": [(i // 64, i % 64)], "names": [nm], "x": None, "y": None,
                        "image": "-", "where": "cabinet" if tags & {"gi", "flasher"} else "playfield",
                        "rgb": True, "lamp": lamp_number(i // 64, i % 64)})
    return {"title": title, "platform": "spooky", "binary": os.path.basename(path) if path else "", "image": "",
            "image_size": None, "tables_from": os.path.dirname(os.path.dirname(path)) if path else "",
            "have": {"device_xy.txt": True, "led_io.txt": bool(inserts), "switch_list.txt": bool(switches)},
            "positions": False, "switches": switches, "coils": coils, "inserts": inserts}


def machine_for(title, tables_dir=None):
    """The machine of any title on this PC: a Spike 2 one from its device
    tables, a Spike 1 one from its ELF, a Spooky one from its rig profile;
    None when none is here."""
    files = find_tables(title, tables_dir)
    if "device_xy.txt" in files:
        return read_machine(os.path.dirname(files["device_xy.txt"]), title, files)
    src = spike1_sources(title) if not tables_dir else {}
    if src:
        return read_machine_spike1(title, src["elf"], src["switchmap"])
    if not tables_dir and title in spooky_titles():
        return read_machine_spooky(title)
    return None


def table_roots():
    """The directories on this PC that hold per-title tables (each has one
    folder per title), the most likely first: PAD_TABLES, the launch
    distro's rig (the app's data disk, or its home) and each of its slots,
    then every other distro's default rig and slots. Asked of WSL once per
    process (padlaunch.distros/account are wsl.exe calls)."""
    global _ROOTS
    if _ROOTS is not None:
        return _ROOTS
    out = []

    def add(d):
        if d and d not in out:
            out.append(d)
    env = os.environ.get("PAD_TABLES")
    if env:
        try:
            import padpath
            add(padpath.to_win(env) or env)
        except Exception:                                   # noqa: BLE001
            add(env)
    try:
        import padlaunch
        dists = padlaunch.distros()
        first = padlaunch.distro()
        for dist in ([first] if first in dists else []) + [d for d in dists if d != first]:
            home = ""
            try:
                home = padlaunch.app_home(dist) if dist == first else ""
            except Exception:                               # noqa: BLE001
                home = ""
            if home:
                add(_win(dist, home + "/spike2root/dump/tables"))
            try:
                _, acct = padlaunch.account(dist)
            except Exception:                               # noqa: BLE001
                acct = ""
            if acct:
                add(_win(dist, acct + "/spike2root/dump/tables"))
                for p in sorted(glob.glob(os.path.join(_win(dist, acct + "/padslots"), "*", "root", "dump", "tables"))):
                    add(p)
    except Exception:                                       # noqa: BLE001
        pass
    _ROOTS = out
    return out


def table_dirs(title):
    """Every directory that may hold `title`'s tables on this PC: the run on
    the rig board for it (padcontroller.Rig) and its slots first, then
    table_roots()."""
    out = []

    def add(d):
        if d and d not in out:
            out.append(d)
    try:
        import padcontroller
        rig = padcontroller.Rig(title)
        if rig.dump:
            add(os.path.join(rig.dump, "tables", title))
            slots = os.path.dirname(os.path.dirname(os.path.dirname(rig.dump)))
            for p in sorted(glob.glob(os.path.join(slots, "*", "root", "dump", "tables", title))):
                add(p)
    except Exception:                                       # noqa: BLE001
        pass
    for root in table_roots():
        add(os.path.join(root, title))
    return out


def find_tables(title, tables_dir=None):
    """{file: path} for each of the title's table files, each from the
    newest directory that has it; {} when none is anywhere."""
    dirs = [os.path.join(tables_dir, title)] if tables_dir else table_dirs(title)
    found = {}
    for f in TABLE_FILES:
        best = None
        for d in dirs:
            p = os.path.join(d, f)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if os.path.getsize(p) and (best is None or mt > best[0]):
                best = (mt, p)
        if best:
            found[f] = best[1]
    return found


def titles_with_tables(tables_dir=None):
    """Every title whose device_xy.txt is somewhere on this PC."""
    titles = set()
    dirs = [tables_dir] if tables_dir else table_roots()
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if re.match(r"^[a-z0-9_]+$", n) and os.path.isfile(os.path.join(d, n, "device_xy.txt")):
                titles.add(n)
    if not tables_dir:
        titles |= set(spike1_titles())          # PAD-943: the Spike 1 games extracted here
        titles |= set(spooky_titles())          # PAD-952: the Spooky updates in the library
    return sorted(titles)


# -------------------------------------------------- what a map covers --

def _ints(v):
    """Every int in a map value: an id, a list of ids, a dict of them."""
    if isinstance(v, bool):
        return []
    if isinstance(v, int):
        return [v]
    if isinstance(v, (list, tuple)):
        return [i for x in v for i in _ints(x)]
    if isinstance(v, dict):
        return [i for k, x in v.items() if k != "_" and k not in ("balls",) for i in _ints(x)]
    return []


def _entries(d):
    return [(k, v) for k, v in (d or {}).items() if k != "_" and isinstance(v, dict)]


def coverage(m):
    """What a map (shadow or vpxmap) wires: the switch ids, the coils (node,
    index), the LEDs (node, index), the coils listed with nothing firing on
    the table, and the GUESS marks."""
    sw, coils, listed_only, leds, guesses = set(), set(), set(), set(), []
    for obj, v in _entries(m.get("switches")):
        if v.get("id"):
            sw.add(int(v["id"]))
        if "GUESS" in json.dumps(v):
            guesses.append(("switch", obj, v.get("name", "")))
    for key in ("switch_rewrite", "switch_by_object", "switch_extra"):
        for k, v in (m.get(key) or {}).items():
            if k != "_" and isinstance(v, int) and v > 0:
                sw.add(v)
    for obj, v in _entries(m.get("switch_subs")):
        sw.update(_ints({k: x for k, x in v.items() if k in ("pulse", "hold")}))
    for k, v in (m.get("switch_holds") or {}).items():
        if k not in ("_", "balls", "balls_why"):
            sw.update(_ints(v))
    for obj, v in _entries(m.get("switch_fakes")):
        sw.update(_ints({k: x for k, x in v.items() if k in ("open", "closed", "switch")}))
        for k in ("coil", "up", "down"):
            if v.get(k):
                coils.add(tuple(v[k]))
    sw.update(_ints((m.get("trough") or {}).get("switches")))
    if (m.get("plunger") or {}).get("lane_switch"):
        sw.add(int(m["plunger"]["lane_switch"]))
    for obj, v in _entries(m.get("saucers")):
        sw.update(_ints({k: x for k, x in v.items() if k in ("switch", "enter")}))
        if "GUESS" in json.dumps(v):
            guesses.append(("saucer", obj, v.get("name", "")))
    for k, v in (m.get("cabinet") or {}).items():
        if k != "_" and isinstance(v, int) and v >= 1000:
            sw.add(v - 1000)
    flippers = {46, 48, 36, 34}                # core.vbs's flipper Consts
    for num, v in _entries(m.get("solenoids")):
        coil = tuple(v.get("coil") or ())
        if len(coil) != 2:
            continue
        fires = (v.get("callback") or int(num) in flippers or "FLIP" in (v.get("name") or "").upper())
        (coils if fires else listed_only).add(coil)
        if "GUESS" in json.dumps(v):
            guesses.append(("coil", num, v.get("name", "")))
    for c in (m.get("game_on") or {}).get("coils") or []:
        coils.add(tuple(c))
    kick = (m.get("trough") or {}).get("kick")
    if kick and len(kick) == 2:
        coils.add(tuple(kick))
    for sect in (m.get("lamps"), m.get("lamp_calls"), (m.get("retrofit_lights") or {}).get("lights")):
        for obj, v in _entries(sect):
            leds.update(tuple(x) for x in v.get("leds") or [])
            if "GUESS" in json.dumps(v):
                guesses.append(("lamp", obj, v.get("name", "")))
    for x in (m.get("gi_leds") or {}).get("leds") or []:
        leds.add(tuple(x))
    for k, v in (m.get("disc_leds") or {}).items():
        if k != "_" and isinstance(v, list) and len(v) == 2:
            leds.add(tuple(v))
    for k, v in (m.get("lamp_flasher_numbers") or {}).items():
        if k not in ("_", "_names") and isinstance(v, int) and v >= 1000:
            leds.add(((v - 1000) // 100, (v - 1000) % 100))
    return {"switches": sw, "coils": coils, "coils_listed_only": listed_only - coils,
            "leds": leds, "guesses": guesses}


def _squash(name):
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"\s*\(.*$", "", (name or "").upper()))


def misnumbered(machine, m):
    """Map switch entries whose name is not what this PC's switch table calls
    that id: (object, id, map name, the machine's name at the id). Rush's
    first map was built from a reading that numbered every switch one higher
    (vpx_bridge.md), and a stale switch_list.txt does the same the other way:
    either way the table presses the wrong switch, and the checklist's yes/NO
    marks are off by one. Entries whose map name is a comment, not a switch
    name, are skipped."""
    by_id = {s["id"]: s["name"] for s in machine["switches"] if s["id"]}
    out = []
    entries = list(_entries(m.get("switches")))
    for obj, v in _entries(m.get("switch_subs")):
        entries.append((obj, {"id": v.get("pulse") or v.get("hold"), "name": v.get("name")}))
    for obj, v in entries:
        sid, name = v.get("id"), v.get("name")
        if not sid or not name or sid not in by_id:
            continue
        want, got = _squash(name), _squash(by_id[sid])
        if got and want and not (want == got or want in got or got in want):
            out.append((obj, int(sid), name, by_id[sid]))
    return out


def gaps(machine, cov):
    """The machine parts a map leaves out, by kind."""
    sw = [s for s in machine["switches"] if owed_switch(s) and s["id"] not in cov["switches"]]
    # flippers, slings and pops are the board's: the switch is what the table owes (checked above)
    coils = [c for c in machine["coils"] if owed_coil(c) and (c["node"], c["index"]) not in cov["coils"]]
    only = [c for c in coils if (c["node"], c["index"]) in cov["coils_listed_only"]]
    coils = [c for c in coils if c not in only]
    inserts = [g for g in machine["inserts"] if g["where"] == "playfield"
               and not any(k in cov["leds"] for k in g["leds"])]
    return {"switches": sw, "coils": coils, "coils_listed_only": only, "inserts": inserts}


# --------------------------------------------------- what a table has --

TABLE_KINDS = ("Trigger", "Kicker", "HitTarget", "Bumper", "Spinner", "Flipper", "Gate", "Plunger",
               "Light", "Flasher", "Wall", "Ramp", "Primitive", "Timer")

# controller.vbs's loaders, which a scripted original often carries a copy of
# in its own script (Allknowing2012's Munsters, PAD-1095): their bodies name
# VPinMAME.Controller whichever loader the table calls, so they say nothing
# about the table's brain; only what the script itself calls does
_LOADER_DEFS = re.compile(
    r"^[ \t]*(?:Public[ \t]+|Private[ \t]+)?Sub[ \t]+(?:LoadVPM|LoadVPMALT|LoadVPinMAME|LoadController|LoadEM"
    r"|LoadPROC)\b.*?^[ \t]*End[ \t]+Sub\b", re.I | re.M | re.S)


def _uncommented(script):
    """The script without its VBScript comments (a ' outside a string to the
    line's end; Rem lines): Stranger Things keeps a commented-out LoadVPM, and
    Iron Maiden names it in a remark."""
    out = []
    for line in script.splitlines():
        if re.match(r"\s*rem\b", line, re.I):
            continue
        inq = False
        for i, ch in enumerate(line):
            if ch == '"':
                inq = not inq
            elif ch == "'" and not inq:
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def script_brain(script):
    """"pad", "rom" or "scripted": what drives a table, from its script."""
    low = _LOADER_DEFS.sub("", _uncommented(script)).lower()
    if "pad.controller" in low or "padspike2" in low:
        return "pad"
    # the ROM's name: Controller.GameName, or .GameName in a `With Controller`
    # (FlexDMD.GameName = cGameName names a DMD's folder, not a ROM: Aerosmith)
    if ("vpinmame.controller" in low or "loadvpm" in low
            or re.search(r"(?:^[ \t]*|\bcontroller)\.gamename\s*=", low, re.M)):
        return "rom"
    return "scripted"


def table_inventory(path):
    """What a .vpx has: its objects by kind (names for the ones that matter),
    and what kind of script drives it."""
    import vpxfile
    t = vpxfile.VpxTable(path)
    by = {}
    for data in t.items:
        kind, name, _pos = t.item_info(data)
        by.setdefault(kind, []).append(name)
    script = t.script()
    brain = script_brain(script)
    return {"path": path, "name": os.path.basename(path), "kinds": {k: sorted(v) for k, v in by.items()},
            "counts": {k: len(v) for k, v in by.items()}, "brain": brain,
            "script_lines": script.count("\n") + 1 if script else 0}


# ------------------------------------------------------------ the text --

def _pos(x, y):
    return "%d,%d" % (x, y) if x is not None else "-"


def _n(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _hint(table, kind):
    return table.get(kind) or table["other"]


def markdown(machine, table=None, map_info=None, cov=None, gap=None, inventory=None, starter=None,
             wrong=None):
    """The checklist as Markdown."""
    title = machine["title"]
    m = []
    w = m.append
    w("# %s: what a Visual Pinball table needs" % title)
    w("")
    w("Made by the Pinball Asset Decryptor's Visual Pinball kit from the game's own device tables"
      + (" (%s)" % machine["binary"] if machine["binary"] else "") + ".")
    w("The real game plays behind the table through `PAD.Controller`; the table talks to it in the "
      "machine's own numbers:")
    w("")
    w("| part | number the table uses | from |")
    w("|---|---|---|")
    w("| switch | 1000 + id | the id column below (switch_list.txt) |")
    w("| coil | the small number its map gives it (1..68; flippers 46/48/36) | `solenoids` in the map |")
    w("| lamp | 1000 + node x 100 + index (an RGB insert: its first LED) | the lamp column below (led_io.txt) |")
    if machine.get("platform") == "spike1":
        w("")
        w("> **A Spike 1 title** (the map says `\"platform\": \"spike1\"`): the ids are the rig's own, "
          "node x 64 + index (switchmaps/<card>.json, s1switches.json); a coil is 1000 + node x 64 + index "
          "until the map gives it its small number; the inserts are the matrix channels the game drives, "
          "named only where its ELF names a lamp - match the rest by watching a run "
          "(tools/spike2_emu/vpx/README.md, \"Other platforms\").")
    w("")
    w("A map (`<title>.shadow.json` for a scripted tribute, `<title>.vpxmap.json` for a ROM table) names "
      "the table object for each part; `tools/spike2_emu/vpx/README.md` has the shape and the kit's "
      "`padvpx patch` applies it.")
    if not machine.get("positions"):
        w("")
        w("> **This build ships no device positions**: the drawing columns below are empty. Place each "
          "part from the real playfield (a photo, the manual) and the names.")
    if machine.get("coils_from_map"):
        w("")
        w("> The build's device table names no coil; the coils below are the ones the kit's map for this "
          "table knows (their node/index come from the node bus).")
    if machine.get("inserts_from_map"):
        w("")
        w("> The build's device table names no LED; the inserts below are the ones the kit's map for this "
          "table lights (seen on the machine's LED plane).")
    if not machine["have"].get("switch_list.txt"):
        w("")
        w("> **No switch ids yet.** The game builds its switch table when it runs; the kit reads it on the "
          "title's first run. Play the title once (the app's Emulate tab, or a table) and make this "
          "checklist again: the id column fills in.")

    pf = [s for s in machine["switches"] if s["where"] == "playfield"]
    unplaced = [s for s in machine["switches"] if s["where"] == "unplaced"]
    cab = [s for s in machine["switches"] if s["where"] == "cabinet"]
    virt = [s for s in machine["switches"] if s["where"] == "virtual"]
    wired_sw = cov["switches"] if cov else None
    missing_sw = {s["id"] for s in gap["switches"]} if gap else set()

    def sw_table(rows, head):
        w("")
        w(head)
        w("")
        cols = "| id | # | node/bit | switch | kind | at (drawing px) | the table does |"
        if cov:
            cols = "| ok | " + cols[2:]
        w(cols)
        w("|---" * (cols.count("|") - 1) + "|")
        for s in rows:
            cells = [str(s["id"]) if s["id"] is not None else "?",
                     str(s["num"]) if s["num"] is not None else "-",
                     "%s/%s" % (s["node"] if s["node"] is not None else "?",
                                s["bit"] if s["bit"] is not None else "?"),
                     s["name"], s["kind"], _pos(s["x"], s["y"]), _hint(SWITCH_HINTS, s["kind"])]
            if cov:
                if s["kind"] in ("flipper eos", "unnamed"):
                    mark = "-"
                elif s["id"] in wired_sw:
                    mark = "yes"
                else:
                    mark = "**NO**"
                cells.insert(0, mark)
            w("| " + " | ".join(cells) + " |")

    w("")
    w("## Switches")
    w("")
    n_sw = len(pf) + len(unplaced)
    eos = len([s for s in pf + unplaced if s["kind"] == "flipper eos"])
    if cov:
        done = len([s for s in pf + unplaced if s["id"] in wired_sw and s["kind"] != "flipper eos"])
        w("%d playfield switches: %d wired by the table's map, %d flipper EOS the board reads, "
          "**%d missing** (marked NO)%s."
          % (n_sw, done, eos, len(missing_sw),
             ": " + ", ".join(s["name"] for s in gap["switches"]) if gap["switches"] else ""))
    else:
        w("%s (%d of them flipper EOS the board reads), %s the kit's system script presses for you, "
          "%d the game makes itself." % (_n(n_sw, "playfield switch", "playfield switches"), eos,
                                          _n(len(cab), "cabinet switch", "cabinet switches"), len(virt)))
    if pf:
        sw_table(sorted(pf, key=lambda s: (s["id"] is None, s["id"] or 0)), "### On the playfield")
    if unplaced:
        sw_table(sorted(unplaced, key=lambda s: (s["id"] is None, s["id"] or 0)),
                 "### On the playfield (no position in this build: place them from the playfield)" if not pf
                 else "### Named by the game, no position in this build (place them from the playfield)")
    if virt:
        w("")
        w("### The game's own (nothing to build)")
        w("")
        w(", ".join("%s (%s)" % (s["name"], s["id"]) for s in virt))
    w("")
    w("### Cabinet (PADSPIKE2.vbs presses these from Visual Pinball's keys)")
    w("")
    w(", ".join("%s (%s)" % (s["name"], s["id"]) for s in cab))

    w("")
    w("## Coils and mechs")
    w("")
    w("Flippers, slingshots and pop bumpers are fired by the machine's node boards from their own "
      "switches, as on the real game: the table only has to send the switch. Every other coil is the "
      "game's decision, and the table acts on it through `solenoids`.")
    wired_c = cov["coils"] if cov else None
    only_c = cov["coils_listed_only"] if cov else set()
    if gap:
        w("")
        w("%d coils; **%d nothing on the table fires**%s%s."
          % (len(machine["coils"]), len(gap["coils"]),
             ": " + ", ".join(c["name"] for c in gap["coils"]) if gap["coils"] else "",
             "; %d listed in the map with no table action (%s)" % (
                 len(gap["coils_listed_only"]), ", ".join(c["name"] for c in gap["coils_listed_only"]))
             if gap["coils_listed_only"] else ""))
    w("")
    head = "| node/index | number | coil | kind | at | the table does |"
    if cov:
        head = "| ok " + head
    w(head)
    w("|---" * (head.count("|") - 1) + "|")
    sol_by_coil = {}
    if map_info:
        for num, v in _entries(map_info.get("solenoids")):
            if len(v.get("coil") or ()) == 2:
                sol_by_coil[tuple(v["coil"])] = num
    for c in sorted(machine["coils"], key=lambda c: (c["node"] is None, c["node"] or 0, c["index"])):
        key = (c["node"], c["index"])
        num = sol_by_coil.get(key, "")
        cells = ["%s/%d" % (c["node"] if c["node"] is not None else "?", c["index"]),
                 num or (str(c["number"]) if c["number"] else "-"), c["name"], c["kind"],
                 _pos(c["x"], c["y"]), _hint(COIL_HINTS, c["kind"])]
        if cov:
            cells.insert(0, "yes" if key in wired_c else "listed" if key in only_c
                         else "board" if c["kind"] in BOARD_COILS[:3]
                         else "-" if c["node"] is None or c["kind"] == "cabinet" else "**NO**")
        w("| " + " | ".join(cells) + " |")
    if any(c["node"] is None for c in machine["coils"]):
        w("")
        w("A coil with node ? sits on a board the title's node directory does not name; the game never "
          "fires it on the emulator.")

    w("")
    w("## Lights")
    w("")
    pf_ins = [g for g in machine["inserts"] if g["where"] == "playfield"]
    other = [g for g in machine["inserts"] if g["where"] != "playfield"]
    rgb = len([g for g in pf_ins if g["rgb"]])
    if gap:
        w("%d playfield inserts (%d RGB); the table shows %d. **%d no table light shows**%s."
          % (len(pf_ins), rgb, len(pf_ins) - len(gap["inserts"]), len(gap["inserts"]),
             ": " + ", ".join(g["name"] for g in gap["inserts"]) if gap["inserts"] else ""))
    else:
        w("%d playfield inserts (%d RGB, lit in the game's colour), %d LEDs off the playfield (cabinet, "
          "speakers, topper: no table light)." % (len(pf_ins), rgb, len(other)))
    w("")
    w("An insert is a Light at the insert's place on the drawing; the map's `lamps` puts the table's "
      "light on the LED (`\"leds\": [[node, index]]`, an RGB insert's three channels together with "
      "`\"rgb\": true`); an insert the table has no light for is a `retrofit_lights` entry (a Light cloned "
      "at the place) or a `lamp_calls` sub for a flasher, bulb or plastic.")
    w("")
    head = "| lamp | node/index | insert | RGB | at |"
    if cov:
        head = "| ok " + head
    w(head)
    w("|---" * (head.count("|") - 1) + "|")
    missing_ins = {id(g) for g in gap["inserts"]} if gap else set()
    for g in pf_ins:
        cells = [str(g["lamp"]), ", ".join("%d/%d" % k for k in g["leds"]), g["name"],
                 "yes" if g["rgb"] else "", _pos(g["x"], g["y"])]
        if cov:
            cells.insert(0, "**NO**" if id(g) in missing_ins else "yes")
        w("| " + " | ".join(cells) + " |")
    if other:
        w("")
        w("### Off the playfield")
        w("")
        w(", ".join("%s (%s)" % (g["name"], g["lamp"]) for g in other[:200]) + (" ..." if len(other) > 200 else ""))

    if wrong:
        w("")
        w("## The map and this PC's switch table disagree (%d)" % len(wrong))
        w("")
        w("The map sends these objects to an id this PC's game calls something else. Either the map was "
          "built from an older reading of the title (every id one off) or the switch table here is "
          "stale: `dump/tables/%s/switch_list.txt` from the run the table attaches to is the numbering "
          "that counts, and the yes/NO marks above follow it." % title)
        w("")
        w("| object | map id | the map says | this PC's switch %s |" % "table says")
        w("|---|---|---|---|")
        for obj, sid, name, got in wrong:
            w("| `%s` | %d | %s | %s |" % (obj, sid, name, got))

    if cov and cov["guesses"]:
        w("")
        w("## Marked GUESS in the map (check these on the machine)")
        w("")
        for kind, obj, name in cov["guesses"]:
            w("- %s `%s`: %s" % (kind, obj, name))

    if inventory:
        w("")
        w("## The table: %s" % inventory["name"])
        w("")
        brain = {"pad": "already patched for PAD.Controller", "rom": "a ROM table (VPinMAME)",
                 "scripted": "a scripted tribute (its rules are its script)"}[inventory["brain"]]
        w("%s, %d lines of script." % (brain, inventory["script_lines"]))
        if map_info:
            table_name = (map_info.get("table") or {}).get("name", "")
            w("The kit's map for it: `%s`%s." % (os.path.basename(map_info.get("_path", "")),
                                                 " (%s)" % table_name if table_name else ""))
        w("")
        w("| kind | count | objects |")
        w("|---|---|---|")
        for k in TABLE_KINDS:
            names = inventory["kinds"].get(k) or []
            if names:
                shown = ", ".join(names[:40]) + (" ... (%d)" % len(names) if len(names) > 40 else "")
                w("| %s | %d | %s |" % (k, len(names), shown))
        if starter:
            w("")
            w("No map in the kit fits this table, so a starter map was written beside this file: `%s`. "
              "Every switch, coil and insert of the machine is in it under a `TODO` key; rename each key "
              "to the table object that is that part (and drop the ones the table has not got), then "
              "`padvpx patch` the table with it." % os.path.basename(starter))
    return "\n".join(m) + "\n"


def starter_map(machine, table_name=""):
    """A shadow map with every part of the machine waiting for its object."""
    sw = {"_": "object -> Spike 2 switch id; event hit (pulse), hold (Hit/UnHit), spin, slingshot. "
               "Rename each TODO key to the table object that is this switch"}
    for s in machine["switches"]:
        # the cabinet's, the trough's and the shooter lane's have their own places in the map
        if s["where"] != "playfield" or not s["id"] or s["kind"] in (
                "flipper eos", "flipper button", "trough", "shooter"):
            continue
        ev = {"slingshot": "slingshot", "spinner": "spin", "magnet": "hold", "shooter": "hold"}.get(s["kind"], "hit")
        sw["TODO_" + re.sub(r"[^A-Z0-9]+", "_", s["name"].upper()).strip("_")] = {
            "id": s["id"], "event": ev, "name": s["name"]}
    sols = {"_": "Spike 2 coil [node, index] -> the small number (1..68) the table sees it as; callback a "
                 "sub of the table's (null = nothing fires)"}
    n = 1
    for c in sorted(machine["coils"], key=lambda c: (c["node"] is None, c["node"] or 0, c["index"])):
        if c["node"] is None or c["kind"] == "cabinet":
            continue
        up = c["name"].upper()
        if c["kind"] == "flipper":
            num = 48 if "LEFT" in up and "UP" not in up else 46 if "RIGHT" in up and "UP" not in up \
                else 36 if "LEFT" in up else 34
        else:
            while n in (34, 36, 46, 48) or str(n) in sols:
                n += 1
            num = n
            n += 1
        cb = {"trough": "bsTrough.SolOut", "auto plunger": "PadAutoPlunge"}.get(c["kind"])
        sols[str(num)] = {"coil": [c["node"], c["index"]], "name": c["name"], "callback": cb}
    lamps = {"_": "table light -> Spike 2 LEDs [node, index] (rgb: an RGB insert, lit in its colour). "
                  "Rename each TODO key to the table's Light at this insert"}
    for g in machine["inserts"]:
        if g["where"] != "playfield":
            continue
        e = {"leds": [list(k) for k in g["leds"]], "name": g["name"]}
        if g["rgb"]:
            e["rgb"] = True if g.get("rgb_order") in (None, "RGB") else g["rgb_order"]
        lamps["TODO_" + re.sub(r"[^A-Z0-9]+", "_", g["name"].upper()).strip("_")] = e
    by_kind = {}
    for s in machine["switches"]:
        by_kind.setdefault(s["kind"], []).append(s)
    trough = sorted((s for s in by_kind.get("trough", []) if s["id"] and "JAM" not in s["name"].upper()),
                    key=lambda s: s["name"])
    jam = [s for s in by_kind.get("trough", []) if s["id"] and "JAM" in s["name"].upper()]
    cab = {}
    for key, rx in (("start", r"^START BUTTON"), ("launch", r"ACTION|LOCKDOWN|LAUNCH"), ("tilt", r"TILT PENDULUM"),
                    ("slam", r"SLAM"), ("left_flipper", r"^LEFT FLIP"), ("right_flipper", r"^RIGHT FLIP"),
                    ("coin", r"^LEFT COIN"), ("coin_door_interlock", r"INTERLOCK")):
        hit = next((s for s in machine["switches"] if s["id"] and re.search(rx, s["name"].upper())
                    and ("BUTTON" in s["name"].upper() or key not in ("left_flipper", "right_flipper"))), None)
        if hit:
            cab[key] = 1000 + hit["id"]
    flip = [c for c in machine["coils"] if c["kind"] == "flipper" and c["node"] is not None]
    return {
        "_": ["%s: a starter map written by vpxauthor.py for %s. Every part of the machine is listed; "
              "rename the TODO keys to the table's objects and remove what the table has not got."
              % (machine["title"], table_name or "a table"),
              "See tools/spike2_emu/vpx/README.md and the maps beside it for finished examples."],
        "title": machine["title"],
        **({"platform": "spike1"} if machine.get("platform") == "spike1" else {}),
        "detect": ["TODO: two words only this table's script has"],
        "output": "%s (PAD).vpx" % (os.path.splitext(table_name)[0] if table_name else machine["title"]),
        "table": {"name": table_name or "", "by": "", "where": ""},
        "solenoid_max": 68,
        "game_on": {"number": 40, "coils": [[c["node"], c["index"]] for c in flip
                                            if "UP" not in c["name"].upper()][:2]},
        "cabinet": cab,
        "switches": sw,
        "plunger": {"lane_trigger": "TODO", "lane_switch": next((s["id"] for s in by_kind.get("shooter", [])
                                                                 if s["id"]), None), "autoplunge": "TODO"},
        "trough": {"release": "TODO", "drain": "TODO",
                   "switches": [s["id"] for s in trough] + [s["id"] for s in jam], "balls": len(trough),
                   "kick": next(([c["node"], c["index"]] for c in machine["coils"]
                                 if c["kind"] == "trough" and c["node"] is not None), None)},
        "saucers": {"_": "kicker -> the switch it holds and how the coil kicks it out (dir, power)"},
        "solenoids": sols,
        "lamps": lamps,
        "retrofit_timers": {"PinMAMETimer": {"clone": "TODO a Timer of the table's", "interval_ms": 1},
                            "PadTestTimer": {"clone": "TODO a Timer of the table's", "interval_ms": 100}},
        "quiet_subs": [], "neuter": [], "orig_hits": False, "orig_keep": [],
    }


# ------------------------------------------------- one line per title --

def summary_for(title, m, tables_dir=None):
    """How much of `title` the map `m` wires, from this PC's tables:
    {switches: [wired, owed], coils: [...], inserts: [...], pct}, or None
    when the title has no tables here. The parts a table owes: playfield
    switches but the flipper EOS and the unnamed, coils but the board's and
    the cabinet's, playfield inserts."""
    machine = machine_for(title, tables_dir)
    if machine is None:
        return None
    if not machine["coils"]:
        machine["coils"] = coils_from_map(m)
    if not machine["inserts"]:
        machine["inserts"] = inserts_from_map(m)
    cov = coverage(m)
    gap = gaps(machine, cov)
    sw = [s for s in machine["switches"] if owed_switch(s)]
    coils = [c for c in machine["coils"] if owed_coil(c)]
    ins = [g for g in machine["inserts"] if g["where"] == "playfield"]
    owed = len(sw) + len(coils) + len(ins)
    missing = len(gap["switches"]) + len(gap["coils"]) + len(gap["coils_listed_only"]) + len(gap["inserts"])
    return {"switches": [len(sw) - len(gap["switches"]), len(sw)],
            "coils": [len(coils) - len(gap["coils"]) - len(gap["coils_listed_only"]), len(coils)],
            "inserts": [len(ins) - len(gap["inserts"]), len(ins)],
            "pct": int(round(100.0 * (owed - missing) / owed)) if owed else 0,
            "ids": bool(machine["have"].get("switch_list.txt"))}


def coverage_all(tables_dir=None):
    """{title: summary_for(...)} for every map the kit has, on this PC's tables."""
    import padvpx
    out = {}
    for title, info in padvpx.maps().items():
        try:
            m = json.load(open(info["map"], encoding="utf-8"))
            got = summary_for(title, m, tables_dir)
        except Exception as exc:                            # noqa: BLE001
            got = {"error": str(exc)}
        if got:
            out[title] = got
    return out


# -------------------------------------------------------------- the job --

def _sw_ok(s, cov, missing_ids):
    if not cov:
        return ""
    if s["kind"] in ("flipper eos", "unnamed"):
        return "-"
    return "no" if s["id"] in missing_ids else "yes" if s["id"] in cov["switches"] else "-"


def _coil_ok(c, cov):
    if not cov:
        return ""
    key = (c["node"], c["index"])
    if key in cov["coils"]:
        return "yes"
    if key in cov["coils_listed_only"]:
        return "listed"
    if c["kind"] in BOARD_COILS[:3]:
        return "board"
    if c["node"] is None or c["kind"] == "cabinet":
        return "-"
    return "no"


def build(title, table=None, tables_dir=None):
    """Everything the app's checklist sheet shows, as one JSON-able dict:
    the machine's parts with their marks, the summary, the notes, the map's
    GUESS marks and id disagreements, the table's inventory, the starter map
    (a dict, when no map fits), and the same checklist as Markdown and CSV
    for export. {"error": ...} when the title has no tables here."""
    asked = title
    pick = None
    if table:
        import padvpx
        fits = padvpx.fitting(table)
        pick = next(((t, i) for t, i in fits if t == title), None) or (fits[0] if fits else None)
        if pick and pick[0] != title and machine_for(pick[0], tables_dir) is not None:
            # the table is another title's (Rush's asked as Stranger Things): the
            # checklist is that title's, and the summary says so
            title = pick[0]
    machine = machine_for(title, tables_dir)
    if machine is None:
        return {"error": "No device tables for %s on this PC yet: play it once (the Emulate tab, or its "
                         "table) and try again." % title}
    map_info = cov = gap = inventory = None
    starter, wrong = None, []
    if table:
        inventory = table_inventory(table)
        if pick:
            map_info = json.load(open(pick[1]["map"], encoding="utf-8"))
            map_info["_path"] = pick[1]["map"]
            if not machine["coils"]:
                machine["coils"] = coils_from_map(map_info)
                machine["coils_from_map"] = True
            if not machine["inserts"]:
                machine["inserts"] = inserts_from_map(map_info)
                machine["inserts_from_map"] = True
            cov = coverage(map_info)
            gap = gaps(machine, cov)
            wrong = misnumbered(machine, map_info)
        else:
            starter = starter_map(machine, inventory["name"])
    text = markdown(machine, table, map_info, cov, gap, inventory,
                    "%s.starter.shadow.json" % title if starter else None, wrong)

    missing_ids = {s["id"] for s in gap["switches"]} if gap else set()
    missing_ins = {id(g) for g in gap["inserts"]} if gap else set()
    sol_by_coil = {}
    if map_info:
        for num, v in _entries(map_info.get("solenoids")):
            if len(v.get("coil") or ()) == 2:
                sol_by_coil[tuple(v["coil"])] = num
    switches = [{"ok": _sw_ok(s, cov, missing_ids), "id": s["id"], "num": s["num"], "node": s["node"],
                 "bit": s["bit"], "name": s["name"], "kind": s["kind"], "x": s["x"], "y": s["y"],
                 "where": s["where"], "hint": _hint(SWITCH_HINTS, s["kind"])}
                for s in sorted(machine["switches"], key=lambda s: (s["id"] is None, s["id"] or 0))]
    coils = [{"ok": _coil_ok(c, cov), "node": c["node"], "index": c["index"],
              "number": sol_by_coil.get((c["node"], c["index"]), "") or (str(c["number"]) if c["number"] else "-"),
              "name": c["name"], "kind": c["kind"], "x": c["x"], "y": c["y"], "hint": _hint(COIL_HINTS, c["kind"])}
             for c in sorted(machine["coils"], key=lambda c: (c["node"] is None, c["node"] or 0, c["index"]))]
    inserts = [{"ok": ("no" if id(g) in missing_ins else "yes") if cov and g["where"] == "playfield" else
                ("-" if cov else ""),
                "lamp": g["lamp"], "leds": ", ".join("%d/%d" % k for k in g["leds"]), "name": g["name"],
                "rgb": bool(g["rgb"]), "x": g["x"], "y": g["y"], "where": g["where"]}
               for g in machine["inserts"]]

    pf_sw = [s for s in switches if s["where"] in ("playfield", "unplaced")]
    owed_sw = [s for s in pf_sw if s["kind"] not in ("flipper eos", "unnamed")]
    owed_coils = [c for c in coils if c["node"] is not None and c["kind"] not in BOARD_COILS]
    pf_ins = [g for g in inserts if g["where"] == "playfield"]
    summary = {"title": title, "switches": len(pf_sw), "coils": len([c for c in coils if c["node"] is not None]),
               "inserts": len(pf_ins), "ids": bool(machine["have"].get("switch_list.txt")),
               "tables_from": machine.get("tables_from", "")}
    if cov:
        wired_sw = len([s for s in owed_sw if s["ok"] == "yes"])
        wired_c = len([c for c in owed_coils if c["ok"] == "yes"])
        wired_i = len([g for g in pf_ins if g["ok"] == "yes"])
        owed = len(owed_sw) + len(owed_coils) + len(pf_ins)
        summary.update(missing_switches=len(gap["switches"]), missing_coils=len(gap["coils"]),
                       listed_coils=len(gap["coils_listed_only"]), missing_inserts=len(gap["inserts"]),
                       guesses=len(cov["guesses"]), id_mismatch=len(wrong), map=os.path.basename(map_info["_path"]),
                       wired={"switches": [wired_sw, len(owed_sw)], "coils": [wired_c, len(owed_coils)],
                              "inserts": [wired_i, len(pf_ins)]},
                       pct=int(round(100.0 * (wired_sw + wired_c + wired_i) / owed)) if owed else 0)
    if inventory:
        summary["table"] = inventory["name"]
        summary["brain"] = inventory["brain"]
    if title != asked:
        summary["asked"] = asked

    notes = []
    if not machine.get("positions"):
        notes.append("This build ships no device positions: place each part from the real playfield.")
    if machine.get("coils_from_map"):
        notes.append("The build's device table names no coil; the coils are the ones the map knows.")
    if machine.get("inserts_from_map"):
        notes.append("The build's device table names no LED; the inserts are the ones the map lights.")
    if not summary["ids"]:
        notes.append("No switch ids yet: the game builds its switch table when it runs. Play the title once "
                     "and make the checklist again.")
    if machine.get("platform") == "spike1":
        notes.append("A Spike 1 title: its parts are read from the game's own program and switch map; the "
                     "switch ids are node x 64 + index, and the inserts are matrix channels named only where "
                     "the game names a lamp.")
    if title != asked:
        notes.append("%s is %s's table, not %s's: this is %s's checklist."
                     % (inventory["name"] if inventory else "The table", title, asked, title))
    if starter:
        notes.append("No map in the app fits this table: a starter map lists every part of the machine under "
                     "a TODO key to rename to the table's object (Save starter map).")

    data = {"title": title, "asked": asked, "summary": summary, "notes": notes, "map": summary.get("map", ""),
            "switches": switches, "coils": coils, "inserts": inserts,
            "guesses": [list(g) for g in cov["guesses"]] if cov else [],
            "wrong": [list(w) for w in wrong],
            "inventory": ({"name": inventory["name"], "brain": inventory["brain"],
                           "script_lines": inventory["script_lines"],
                           "kinds": {k: inventory["kinds"].get(k) or [] for k in TABLE_KINDS}}
                          if inventory else None),
            "starter": starter, "markdown": text}
    data["csv"] = to_csv(data)
    return data


def to_csv(data):
    """The checklist as CSV: one row per part, every section in one sheet."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    marked = bool(data.get("map"))
    w.writerow(["section", "ok" if marked else "", "id / lamp", "number", "node", "bit / index", "name", "kind",
                "x", "y", "where", "the table does"])
    for s in data["switches"]:
        w.writerow(["switch", s["ok"], s["id"] if s["id"] is not None else "?", s["num"] if s["num"] is not None else "",
                    s["node"] if s["node"] is not None else "", s["bit"] if s["bit"] is not None else "",
                    s["name"], s["kind"], s["x"] if s["x"] is not None else "", s["y"] if s["y"] is not None else "",
                    s["where"], s["hint"]])
    for c in data["coils"]:
        w.writerow(["coil", c["ok"], "", c["number"], c["node"] if c["node"] is not None else "", c["index"],
                    c["name"], c["kind"], c["x"] if c["x"] is not None else "", c["y"] if c["y"] is not None else "",
                    "playfield" if c["x"] is not None else "", c["hint"]])
    for g in data["inserts"]:
        w.writerow(["insert", g["ok"], g["lamp"], "", "", g["leds"], g["name"], "rgb" if g["rgb"] else "",
                    g["x"] if g["x"] is not None else "", g["y"] if g["y"] is not None else "", g["where"], ""])
    for kind, obj, name in data["guesses"]:
        w.writerow(["guess", "", "", "", "", "", name, kind, "", "", obj, ""])
    for obj, sid, name, got in data["wrong"]:
        w.writerow(["map id disagrees", "", sid, "", "", "", name, "", "", "", obj, "this PC's game: " + got])
    return out.getvalue()


def _safe(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()


def checklist(title, table=None, out_dir=None, tables_dir=None):
    """Write the checklist as Markdown (and a starter map when a table has
    no map): the command-line form of build(). Returns the summary;
    `error` when nothing could be made."""
    data = build(title, table, tables_dir)
    if "error" in data:
        return data
    out_dir = out_dir or (os.path.dirname(os.path.abspath(table)) if table else os.getcwd())
    os.makedirs(out_dir, exist_ok=True)
    summary = dict(data["summary"], result="ok")
    if data["starter"]:
        starter = os.path.join(out_dir, "%s.starter.shadow.json" % data["title"])
        with open(starter, "w", encoding="utf-8") as f:
            json.dump(data["starter"], f, indent=1)
        summary["starter"] = starter
    name = "%s - Visual Pinball table checklist%s.md" % (
        data["title"], " - " + _safe(os.path.splitext(data["inventory"]["name"])[0]) if data["inventory"] else "")
    out = os.path.join(out_dir, name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(data["markdown"])
    summary["out"] = out
    return summary


def title_platforms(titles):
    """{title: platform} for the titles that are not Spike 2's (PAD-943:
    the tab shows its manufacturer's own)."""
    s1 = set(spike1_titles())
    spk = set(spooky_titles())
    out = {t: "spike1" for t in titles if t in s1}
    out.update({t: "spooky" for t in titles if t in spk})
    return out


def main(argv):
    if argv and argv[0] == "titles":
        titles = titles_with_tables()
        print(json.dumps({"titles": titles, "platforms": title_platforms(titles)}), flush=True)
        return 0
    if argv and argv[0] == "coverage":
        print(json.dumps({"coverage": coverage_all(argv[2] if len(argv) > 2 and argv[1] == "--tables" else None)}),
              flush=True)
        return 0
    if len(argv) >= 2 and argv[0] in ("checklist", "machine", "data"):
        title = argv[1]
        opt = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else None  # noqa: E731
        if argv[0] == "data":
            # the app's sheet: everything build() knows, one JSON line
            print(json.dumps(build(title, opt("--table"), opt("--tables"))), flush=True)
            return 0
        if argv[0] == "machine":
            files = find_tables(title, opt("--tables"))
            if "device_xy.txt" not in files:
                print(json.dumps({"error": "no tables for %s" % title}))
                return 1
            print(json.dumps(read_machine(os.path.dirname(files["device_xy.txt"]), title, files), indent=1,
                             default=list))
            return 0
        got = checklist(title, opt("--table"), opt("--out"), opt("--tables"))
        if "error" in got:
            print(got["error"])
        else:
            print("checklist: %s" % got["out"])
            if got.get("starter"):
                print("starter map: %s" % got["starter"])
        print(json.dumps(got), flush=True)
        return 0 if "error" not in got else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
