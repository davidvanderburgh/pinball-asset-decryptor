#!/usr/bin/env python3
"""vpxauthor.py - what a Visual Pinball table of a Spike 2 title needs, and
what a table has (PAD-941): the checklist for whoever builds or finishes one.

    python vpxauthor.py checklist <title> [--table <file.vpx>] [--out DIR] [--tables DIR]
    python vpxauthor.py machine <title> [--tables DIR]          the machine as JSON
    python vpxauthor.py titles                                  the titles whose tables are on this PC

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
    ("flipper eos", r"FLIP(PER)?\s*EOS"),
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
    inserts = []
    for g in groups.values():
        g["leds"].sort(key=lambda k: k[1])
        g["rgb"] = len(g["leds"]) == 3 and all(re.search(r"[- ](R|G|B|RED|GRN|GREEN|BLU|BLUE)$", n, re.I)
                                               for n in g["names"])
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
        if v.get("coil"):
            out.setdefault(tuple(v["coil"]), v.get("name") or obj.upper())
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


def table_dirs(title):
    """Every directory that may hold `title`'s tables on this PC, the most
    likely first: PAD_TABLES, the run on the rig board (padcontroller.Rig),
    the launch distro's rig (the app's data disk, or its home), each slot's
    root, then every other distro's default rig."""
    out = []

    def add(d):
        if d and d not in out:
            out.append(d)
    env = os.environ.get("PAD_TABLES")
    if env:
        try:
            import padpath
            add(os.path.join(padpath.to_win(env) or env, title))
        except Exception:                                   # noqa: BLE001
            add(os.path.join(env, title))
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
                add(_win(dist, home + "/spike2root/dump/tables/" + title))
            try:
                _, acct = padlaunch.account(dist)
            except Exception:                               # noqa: BLE001
                acct = ""
            if acct:
                add(_win(dist, acct + "/spike2root/dump/tables/" + title))
                for p in sorted(glob.glob(_win(dist, acct + "/padslots") + r"\*\root\dump\tables\%s" % title)):
                    add(p)
    except Exception:                                       # noqa: BLE001
        pass
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
    dirs = [tables_dir] if tables_dir else [os.path.dirname(d) for d in table_dirs("_")]
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if re.match(r"^[a-z0-9_]+$", n) and os.path.isfile(os.path.join(d, n, "device_xy.txt")):
                titles.add(n)
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
        sw.update(_ints({k: x for k, x in v.items() if k in ("open", "closed")}))
        if v.get("coil"):
            coils.add(tuple(v["coil"]))
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
    sw = [s for s in machine["switches"]
          if s["where"] in ("playfield", "unplaced") and s["id"] and s["id"] not in cov["switches"]
          and s["kind"] not in ("flipper eos", "unnamed")]
    # flippers, slings and pops are the board's: the switch is what the table owes (checked above)
    coils = [c for c in machine["coils"] if c["node"] is not None and c["kind"] not in BOARD_COILS
             and (c["node"], c["index"]) not in cov["coils"]]
    only = [c for c in coils if (c["node"], c["index"]) in cov["coils_listed_only"]]
    coils = [c for c in coils if c not in only]
    inserts = [g for g in machine["inserts"] if g["where"] == "playfield"
               and not any(k in cov["leds"] for k in g["leds"])]
    return {"switches": sw, "coils": coils, "coils_listed_only": only, "inserts": inserts}


# --------------------------------------------------- what a table has --

TABLE_KINDS = ("Trigger", "Kicker", "HitTarget", "Bumper", "Spinner", "Flipper", "Gate", "Plunger",
               "Light", "Flasher", "Wall", "Ramp", "Primitive", "Timer")


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
    low = script.lower()
    if "pad.controller" in low or "padspike2" in low:
        brain = "pad"
    elif "vpinmame.controller" in low or "loadvpm" in low or re.search(r"\.gamename\s*=", low):
        brain = "rom"
    else:
        brain = "scripted"
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
            e["rgb"] = True
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


# -------------------------------------------------------------- the job --

def _safe(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()


def checklist(title, table=None, out_dir=None, tables_dir=None):
    """Write the checklist (and a starter map when a table has no map).
    Returns the summary the tab shows; `error` when nothing could be made."""
    asked = title
    pick = None
    if table:
        import padvpx
        fits = padvpx.fitting(table)
        pick = next(((t, i) for t, i in fits if t == title), None) or (fits[0] if fits else None)
        if pick and pick[0] != title and "device_xy.txt" in find_tables(pick[0], tables_dir):
            # the table is another title's (Rush's asked as Stranger Things): the
            # checklist is that title's, and the summary says so
            title = pick[0]
    files = find_tables(title, tables_dir)
    if "device_xy.txt" not in files:
        return {"error": "No device tables for %s on this PC yet: play it once (the Emulate tab, or its "
                         "table) and try again." % title}
    machine = read_machine(os.path.dirname(files["device_xy.txt"]), title, files)
    map_info = cov = gap = inventory = None
    starter, wrong = None, []
    out_dir = out_dir or (os.path.dirname(os.path.abspath(table)) if table else os.getcwd())
    os.makedirs(out_dir, exist_ok=True)
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
            starter = os.path.join(out_dir, "%s.starter.shadow.json" % title)
            with open(starter, "w", encoding="utf-8") as f:
                json.dump(starter_map(machine, inventory["name"]), f, indent=1)
    text = markdown(machine, table, map_info, cov, gap, inventory, starter, wrong)
    name = "%s - Visual Pinball table checklist%s.md" % (
        title, " - " + _safe(os.path.splitext(inventory["name"])[0]) if inventory else "")
    out = os.path.join(out_dir, name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    pf_sw = [s for s in machine["switches"] if s["where"] in ("playfield", "unplaced")]
    pf_ins = [g for g in machine["inserts"] if g["where"] == "playfield"]
    coils = [c for c in machine["coils"] if c["node"] is not None]
    summary = {"result": "ok", "out": out, "title": title, "switches": len(pf_sw), "coils": len(coils),
               "inserts": len(pf_ins), "ids": bool(machine["have"].get("switch_list.txt")),
               "tables_from": os.path.dirname(files["device_xy.txt"])}
    if gap:
        summary.update(missing_switches=len(gap["switches"]), missing_coils=len(gap["coils"]),
                       missing_inserts=len(gap["inserts"]), guesses=len(cov["guesses"]),
                       id_mismatch=len(wrong), map=os.path.basename(map_info["_path"]))
    if starter:
        summary["starter"] = starter
    if inventory:
        summary["table"] = inventory["name"]
        summary["brain"] = inventory["brain"]
    if title != asked:
        summary["asked"] = asked
    return summary


def main(argv):
    if argv and argv[0] == "titles":
        print(json.dumps({"titles": titles_with_tables()}), flush=True)
        return 0
    if len(argv) >= 2 and argv[0] in ("checklist", "machine"):
        title = argv[1]
        opt = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else None  # noqa: E731
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
