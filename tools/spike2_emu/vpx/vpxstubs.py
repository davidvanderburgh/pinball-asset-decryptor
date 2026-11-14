#!/usr/bin/env python3
"""vpxstubs.py - from the checklist to working code (PAD-1303).

    padvpx match-leds <title> --table "<file.vpx>" [--into MAP.json] [--confirm]
        Proposes the machine's LED for each Light in the table by where it
        stands: the device drawing (device_xy.txt) laid over the table - by
        the objects whose names are the machine's switches when there are
        enough of them, else scaled to the table's size - and each light
        paired with the nearest insert, nearest pairs first. Lights the
        table's map already wires are left alone. Writes
        "<table> - LED matches.json" beside it: a `lamps` section in the
        maps' own format, each entry with how far off it stood; one that
        is not clear-cut carries a "GUESS" note, which the checklist then
        counts as a mark to look at. --confirm asks about each one (y / n
        / q); --into adds what was accepted (without --confirm: every
        match, the unsure ones with their GUESS note) to a map's `lamps`.

    padvpx stubs <title> --table "<file.vpx>" [--out FILE] [--print]
        Appends to the table's script a sub for every switch, coil and
        insert the machine has and the table does not yet (what its map
        leaves out, else what its script never names), writing
        "<name> (stubs).vpx" beside it, re-signed. Placing an object with
        the stub's name is then all a part needs:
            switch  sw_<NAME>   Hit/UnHit held (a lane, opto, saucer, magnet),
                                Hit pulsed (a target, bumper), Spin, Slingshot;
                                a drop target stays closed until its bank resets
            coil    a sub on SolCallback, the number told to the controller
                    (Controller.PadSolenoid), with a working default:
                    magnet      cvpmMagnet on the Trigger mag_<NAME>
                    drop reset  raises its bank's sw_<DROP> targets, opens their switches
                    kicker      kicks the saucer's own Kicker (sw_<SAUCER>) or kick_<NAME>
                    post        the Wall post_<NAME> up while the coil is on
                    gate        the Gate (or Flipper) gate_<NAME> open while it is on
                    trough      bsTrough.SolOut; auto plunger: the Plunger plunger_<NAME>
                    other       an empty sub to fill in
            insert  the Light l_<NAME>, on while any of its LEDs is
        Every object is looked up by name under On Error, so a part not
        placed yet changes nothing. Run again after adding parts: the block
        is replaced, never doubled. --print shows the block only.
"""
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import vpxauthor   # noqa: E402

BEGIN = "'==== PAD stubs (padvpx stubs, PAD-1303): made from the machine's own tables; run it again to remake"
END = "'==== end of PAD stubs"
FLIPPER_SOLS = (34, 36, 46, 48)        # core.vbs's flipper Consts
OBJ_KINDS = ("Trigger", "HitTarget", "Kicker", "Bumper", "Spinner", "Gate", "Wall", "Light", "Flasher")
ANCHOR_KINDS = ("Trigger", "HitTarget", "Kicker", "Bumper", "Spinner", "Light")
#: a table's GI bulbs (JAWS' gi004, "GI_Left", "BumperGI2"): no insert's light
GI_LIGHT = re.compile(r"^gi(?![a-z])|(?<![a-z])gi(?![a-z])|[a-z]GI(?![a-z])|_gi\d|GIString|GIBulb", re.I)


# ------------------------------------------------------------ the table --

def table_geometry(path):
    """{"size": (left, top, right, bottom), "lights": [{name, x, y}],
    "objects": [{kind, name, x, y}], "script", "name"} of a .vpx."""
    import vpxfile
    t = vpxfile.VpxTable(path)
    try:
        size = []
        for tag, dflt in (("LEFT", 0.0), ("TOPX", 0.0), ("RGHT", 952.0), ("BOTM", 2162.0)):
            f = t.gamedata_field(tag)
            size.append(struct.unpack("<f", f[:4])[0] if f and len(f) >= 4 else dflt)
        nm = t.gamedata_field("NAME")
        objs = []
        for data in t.items:
            kind, name, pos = t.item_info(data)
            if kind in OBJ_KINDS and name and pos:
                objs.append({"kind": kind, "name": name, "x": pos[0], "y": pos[1]})
        return {"size": tuple(size), "objects": objs, "lights": [o for o in objs if o["kind"] == "Light"],
                "script": t.script(), "name": (vpxfile.unwide(nm).replace("\x00", "").strip() if nm else "")
                or "Table1"}
    finally:
        t.ole.close()


def _squash(name):
    n = (name or "").upper()
    n = re.sub(r"^(SW|L|LIGHT|MAG|KICK|POST|GATE)[_ ]+", "", n)
    return re.sub(r"[^A-Z0-9]", "", n)


def _lsq(pairs):
    """y = a*x + b by least squares, or None."""
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    d = n * sxx - sx * sx
    if not d:
        return None
    a = (n * sxy - sx * sy) / d
    return a, (sy - a * sx) / n


def fit(machine, geo):
    """How a drawing point lands on the table: {"how", "x": (a, b), "y":
    (a, b), "anchors"}. By anchors (table objects named as placed switches
    or inserts) when three or more spread over the table agree, else by
    scaling the drawing to the table."""
    left, top, right, bottom = geo["size"]
    w, h = right - left, bottom - top
    placed = {}
    for s in machine["switches"]:
        if s.get("x") is not None:
            placed.setdefault(_squash(s["name"]), (s["x"], s["y"]))
    for g in machine["inserts"]:
        if g.get("x") is not None and g["where"] == "playfield":
            placed.setdefault(_squash(g["name"]), (g["x"], g["y"]))
    anchors = []
    for o in geo["objects"]:
        # only an object whose place is a point (a wall's is its first
        # corner: Deadpool's slingshots), and a name that says something
        # (JP's "lock" is any lock)
        k = _squash(o["name"])
        if o["kind"] in ANCHOR_KINDS and len(k) >= 6 and k in placed:
            anchors.append((placed[k], (o["x"], o["y"]), o["name"]))
    img = machine.get("image_size") or (1, 1)
    if len(anchors) >= 4:
        xs = [a[0][0] for a in anchors]
        ys = [a[0][1] for a in anchors]
        fx = _lsq([(a[0][0], a[1][0]) for a in anchors])
        fy = _lsq([(a[0][1], a[1][1]) for a in anchors])
        spread = (max(xs) - min(xs), max(ys) - min(ys))
        if fx and fy and fx[0] > 0 and fy[0] > 0 and spread[0] > 0.25 * img[0] and spread[1] > 0.25 * img[1]:
            # an anchor that is not where its name says (an object named for
            # a switch but standing elsewhere) is left out, and the fit made again
            def off(a, fx=fx, fy=fy):
                return math.hypot(fx[0] * a[0][0] + fx[1] - a[1][0], fy[0] * a[0][1] + fy[1] - a[1][1])
            good = [a for a in anchors if off(a) < 0.08 * w]
            if len(good) >= 3 and len(good) < len(anchors):
                fx2 = _lsq([(a[0][0], a[1][0]) for a in good])
                fy2 = _lsq([(a[0][1], a[1][1]) for a in good])
                if fx2 and fy2 and fx2[0] > 0 and fy2[0] > 0:
                    fx, fy, anchors = fx2, fy2, good
            res = sum(off(a) for a in anchors) / len(anchors)
            if res < 0.05 * w:
                return {"how": "anchors", "x": fx, "y": fy, "anchors": [a[2] for a in anchors],
                        "residual": round(res, 1)}
    size = machine.get("image_size")
    if not size:
        pts = [(g["x"], g["y"]) for g in machine["inserts"] if g.get("x") is not None] + \
              [(s["x"], s["y"]) for s in machine["switches"] if s.get("x") is not None]
        size = (max(p[0] for p in pts) or 1, max(p[1] for p in pts) or 1) if pts else (1, 1)
    return {"how": "scaled", "x": (w / size[0], left), "y": (h / size[1], top), "anchors": [], "residual": None}


def _place(f, x, y):
    return f["x"][0] * x + f["x"][1], f["y"][0] * y + f["y"][1]


def _mutual(at, lights, near):
    """The (insert i, light j, distance) pairs that are each other's
    nearest, within `near`."""
    best_l, best_g = {}, {}
    for i, (x, y) in enumerate(at):
        for j, o in enumerate(lights):
            d = math.hypot(o["x"] - x, o["y"] - y)
            if d <= near:
                if d < best_l.get(i, (None, near + 1))[1]:
                    best_l[i] = (j, d)
                if d < best_g.get(j, (None, near + 1))[1]:
                    best_g[j] = (i, d)
    return [(i, j, d) for i, (j, d) in best_l.items() if best_g.get(j, (None,))[0] == i]


def refine(f, pts, lights, near, rounds=4):
    """The fit made again from the lights themselves: each round, the
    inserts and lights that are each other's nearest are the anchors, and
    the new fit is kept while it brings them closer (a replica table's
    lights stand on its inserts, so a fit off by a little pulls in). Off a
    table built to another layout, nothing improves and `f` comes back."""
    if len(pts) < 8 or len(lights) < 8:
        return f

    def median(ps):
        ds = sorted(p[2] for p in ps)
        return ds[len(ds) // 2] if ds else float("inf")

    pairs = _mutual([_place(f, x, y) for x, y in pts], lights, near)
    for _ in range(rounds):
        if len(pairs) < 8:
            break
        # the closest four in five fit it: a pair the last fit got wrong
        # stands far off and would drag the new one
        keep = sorted(pairs, key=lambda p: p[2])[:max(8, len(pairs) * 4 // 5)]
        fx = _lsq([(pts[i][0], lights[j]["x"]) for i, j, _ in keep])
        fy = _lsq([(pts[i][1], lights[j]["y"]) for i, j, _ in keep])
        if not (fx and fy and fx[0] > 0 and fy[0] > 0):
            break
        g = dict(f, x=fx, y=fy)
        new = _mutual([_place(g, x, y) for x, y in pts], lights, near)
        if len(new) < 0.85 * len(pairs) or median(new) >= median(pairs):
            break
        f = dict(g, how=f["how"].split("+")[0] + "+refined", refined_on=len(new), residual=round(median(new), 1))
        pairs = new
    return f


# ------------------------------------------------------------ match-leds --

def match_leds(machine, geo, skip_lights=(), skip_leds=()):
    """{"fit", "matches": [{light, insert, leds, rgb, distance, sure, x, y}],
    "lights_left": [names], "inserts_left": [names]}: each Light of the
    table paired with the insert nearest it on the fitted drawing, nearest
    pairs first, none paired twice."""
    f = fit(machine, geo)
    w = geo["size"][2] - geo["size"][0]
    near, sure_d, margin = 0.06 * w, 0.03 * w, 0.02 * w
    skip_l = {n.upper() for n in skip_lights}
    skip_k = {tuple(k) for k in skip_leds}
    left, top, right, bottom = geo["size"]
    # a light off the playfield (a backglass or apron light: Metallica's
    # stand left of the table) is no insert's
    lights = [o for o in geo["lights"] if o["name"].upper() not in skip_l and not GI_LIGHT.search(o["name"])
              and left <= o["x"] <= right and top <= o["y"] <= bottom]
    inserts = [g for g in machine["inserts"] if g["where"] == "playfield" and g.get("x") is not None
               and not any(tuple(k) in skip_k for k in g["leds"])]
    pts = [(g["x"], g["y"]) for g in inserts]
    g = refine(f, pts, lights, near)
    # a table drawn further off than `near` pairs nothing to refine on: look wider
    f = g if g is not f else refine(f, pts, lights, 2 * near)
    at = [_place(f, g["x"], g["y"]) for g in inserts]
    dist = {}
    for li, o in enumerate(lights):
        for gi, (x, y) in enumerate(at):
            d = math.hypot(o["x"] - x, o["y"] - y)
            if d <= near:
                dist[(li, gi)] = d
    by_light, by_insert = {}, {}
    for (li, gi), d in dist.items():
        by_light.setdefault(li, []).append(d)
        by_insert.setdefault(gi, []).append(d)
    used_l, used_g, out = set(), set(), []
    for (li, gi), d in sorted(dist.items(), key=lambda kv: kv[1]):
        if li in used_l or gi in used_g:
            continue
        used_l.add(li)
        used_g.add(gi)
        rivals = sorted(by_light[li])[1:2] + sorted(by_insert[gi])[1:2]
        second = min(rivals) if rivals else None
        sure = d <= sure_d and (second is None or second >= max(2.0 * d, d + margin))
        g = inserts[gi]
        out.append({"light": lights[li]["name"], "insert": g["name"], "leds": [list(k) for k in g["leds"]],
                    "rgb": (True if g.get("rgb_order") in (None, "RGB") else g["rgb_order"]) if g["rgb"] else None,
                    "distance": round(d, 1), "sure": sure, "x": round(lights[li]["x"], 1),
                    "y": round(lights[li]["y"], 1)})
    out.sort(key=lambda m: m["light"].upper())
    return {"fit": f, "matches": out,
            "lights_left": sorted(o["name"] for i, o in enumerate(lights) if i not in used_l),
            "inserts_left": sorted(g["name"] for i, g in enumerate(inserts) if i not in used_g)}


def lamps_entry(m, guess_note=True):
    e = {"leds": m["leds"], "name": m["insert"]}
    if m["rgb"]:
        e["rgb"] = m["rgb"]
    if guess_note and not m["sure"]:
        e["note"] = "GUESS: by position (match-leds), %s units from the insert" % m["distance"]
    return e


def _map_for_table(title, table):
    import padvpx
    fits = padvpx.fitting(table)
    pick = next(((t, i) for t, i in fits if t == title), None) or (fits[0] if fits else None)
    if not pick:
        return None, None
    return json.load(open(pick[1]["map"], encoding="utf-8")), pick[1]["map"]


def _machine(title, tables_dir=None):
    m = vpxauthor.machine_for(title, tables_dir)
    if m is None:
        return None, {"error": "No device tables for %s on this PC yet: play it once (the Emulate tab, or its "
                               "table) and try again." % title}
    return m, None


def match_leds_cmd(title, table, into=None, confirm=False, out=None, ask=None, tables_dir=None, say=print):
    if confirm and ask is None and not sys.stdin.isatty():
        # answers piped in are read NOW: finding the title's tables starts
        # wsl.exe, and one that inherits the pipe drains it
        answers = sys.stdin.read().splitlines()

        def ask(prompt):
            print(prompt, end="", flush=True)
            if not answers:
                raise EOFError
            a = answers.pop(0)
            print(a)
            return a
    machine, err = _machine(title, tables_dir)
    if err:
        say(err["error"])
        return err
    if not any(g.get("x") is not None for g in machine["inserts"]):
        err = {"error": "%s's tables say where no insert is, so no light can be matched by position." % title}
        say(err["error"])
        return err
    geo = table_geometry(table)
    m, map_path = _map_for_table(title, table)
    skip_l, skip_k = [], []
    if m:
        for sect in ("lamps", "lamp_calls"):
            for k, v in (m.get(sect) or {}).items():
                if k != "_" and isinstance(v, dict):
                    skip_l.append(k)
                    skip_k += [tuple(x) for x in v.get("leds") or []]
    got = match_leds(machine, geo, skip_l, skip_k)
    f = got["fit"]
    say("%s: %d lights in the table, %d matched (%d sure), %d lights and %d inserts left; drawing %s%s"
        % (os.path.basename(table), len(geo["lights"]), len(got["matches"]),
           sum(1 for x in got["matches"] if x["sure"]), len(got["lights_left"]), len(got["inserts_left"]),
           "fitted on %d named objects (%s units off on average)" % (len(f["anchors"]), f["residual"])
           if f["how"] == "anchors" else "scaled to the table's size", "; the map %s already wires %d"
           % (os.path.basename(map_path), len(skip_l)) if m else ""))
    accepted = []
    for x in got["matches"]:
        tag = "sure " if x["sure"] else "GUESS"
        leds = ", ".join("%d/%d" % tuple(k) for k in x["leds"])
        say("  %s  %-24s -> %-28s %-12s  %6.1f units" % (tag, x["light"], x["insert"], leds, x["distance"]))
        if confirm:
            try:
                a = (ask or input)("     %s is %s? [y/n/q] " % (x["light"], x["insert"])).strip().lower()
            except EOFError:
                a = "q"                                     # nobody left to ask: what was said stands
            if a.startswith("q"):
                break
            if a.startswith("y"):
                accepted.append(dict(x, sure=True))
        else:
            accepted.append(x)
    lamps = {"_": "table light -> Spike 2 LEDs [node, index], proposed by position (padvpx match-leds); "
                  "a GUESS note wants a look"}
    for x in accepted:
        lamps[x["light"]] = lamps_entry(x)
    result = {"title": machine["title"], "table": os.path.basename(table), "fit": f["how"],
              "anchors": f["anchors"], "matches": got["matches"], "lights_left": got["lights_left"],
              "inserts_left": got["inserts_left"], "lamps": lamps, "accepted": len(accepted)}
    out = out or os.path.join(os.path.dirname(os.path.abspath(table)),
                              "%s - LED matches.json" % os.path.splitext(os.path.basename(table))[0])
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    result["out"] = out
    say("written: %s" % out)
    if into:
        target = json.load(open(into, encoding="utf-8")) if os.path.isfile(into) else {}
        sect = target.setdefault("lamps", {"_": lamps["_"]})
        added = 0
        for k, v in lamps.items():
            if k != "_" and k not in sect:
                sect[k] = v
                added += 1
        with open(into, "w", encoding="utf-8") as fh:
            json.dump(target, fh, indent=1)
        result["into"], result["added"] = into, added
        say("%d lights added to %s's lamps" % (added, into))
    return result


# ------------------------------------------------------------ stubs --

def ident(name):
    """sw_<NAME>'s NAME: `LEFT RAMP ENTER` -> LEFT_RAMP_ENTER."""
    n = re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_")
    return n if n and not n[0].isdigit() else "X" + n


_HOLD = ("lane", "opto", "magnet", "lock", "saucer", "shooter", "trough", "mech")
_WORDS_GENERIC = {"DROP", "TARGET", "TARGETS", "RESET", "COIL", "BANK", "UP", "DOWN", "THE", "OF", "KICK",
                  "KICKER", "EJECT", "SAUCER", "SCOOP", "VUK", "LOCK", "HOLE", "SWITCH", "OPTO", "MAGNET", "POST"}


def _words(name):
    return {w for w in re.split(r"[^A-Z0-9]+", (name or "").upper()) if w and w not in _WORDS_GENERIC}


def _partners(coil, switches):
    """The switches that go with a coil by name (a bank's drops, a saucer's
    switch): those sharing the most of its own words; all of them when its
    name says nothing past the generic words."""
    mine = _words(coil["name"])
    scored = [(len(mine & _words(s["name"])), s) for s in switches]
    best = max((n for n, _ in scored), default=0)
    if not mine or not best:
        return list(switches)
    return [s for n, s in scored if n == best]


def owed(machine, script, cov=None):
    """What the stubs are for: (switches, coils, inserts) the machine has and
    the table does not - its map's gaps when a map fits (cov), else the parts
    its script never names by number (or, for a coil, by the controller's
    map number on a SolCallback)."""
    body = vpxauthor._uncommented(_without_block(script))
    nums = {int(n) for n in re.findall(r"\b(1\d{3})\b", body)}
    named_subs = {m.lower() for m in re.findall(r"^[ \t]*(?:Public[ \t]+|Private[ \t]+)?Sub[ \t]+(\w+)", body, re.M)}
    if cov is not None:
        gap = vpxauthor.gaps(machine, cov)
        sws, coils, ins = gap["switches"], gap["coils"] + gap["coils_listed_only"], gap["inserts"]
    else:
        sws = [s for s in machine["switches"] if vpxauthor.owed_switch(s)]
        coils = [c for c in machine["coils"] if vpxauthor.owed_coil(c)]
        ins = [g for g in machine["inserts"] if g["where"] == "playfield"]
        sws = [s for s in sws if 1000 + s["id"] not in nums]
        # a coil the controller's map numbers, handed to SolCallback by
        # that number (a patched or generated table's own wiring), is had
        callbacks = {int(n) for n in re.findall(r"SolCallback\(\s*(\d+)\s*\)", body)}
        wired = {coil for n, coil in _controller_sols(machine["title"]).items() if n in callbacks}
        coils = [c for c in coils if c["number"] not in nums and (c["node"], c["index"]) not in wired
                 and not re.search(r"Array\(\s*%d\s*,\s*%d\s*\)" % (c["node"], c["index"]), body)]
        ins = [g for g in ins if not any(vpxauthor.lamp_number(*k) in nums for k in g["leds"])]
    sws = [s for s in sws if s["kind"] not in ("cabinet", "virtual", "flipper button")
           and "sw_%s_hit" % ident(s["name"]).lower() not in named_subs]
    coils = [c for c in coils if "sol_%s" % ident(c["name"]).lower() not in named_subs]
    return sws, coils, ins


def _controller_sols(title):
    """{number: (node, index)} of the map the controller loads for the title."""
    try:
        import padcontroller
        return dict(padcontroller.VpxMap(title).solenoids)
    except Exception:                                       # noqa: BLE001
        return {}


def _without_block(script):
    i = script.find(BEGIN)
    if i < 0:
        return script
    j = script.find(END, i)
    return script[:i].rstrip("\r\n") + ("\r\n" + script[j + len(END):].lstrip("\r\n") if j >= 0 else "")


def _sol_numbers(title, script, m=None):
    """(numbers taken, the highest allowed): the controller's map for the
    title, the script's own SolCallback(n), core.vbs's flipper numbers."""
    taken = set(FLIPPER_SOLS)
    top = 68
    if m is None:
        taken |= set(_controller_sols(title))
        try:
            import padcontroller
            top = padcontroller.VpxMap(title).sol_max
        except Exception:                                   # noqa: BLE001
            pass
    else:
        taken |= {int(k) for k in (m.get("solenoids") or {}) if k != "_" and str(k).isdigit()}
        top = int(m.get("solenoid_max", 68))
    taken |= {int(n) for n in re.findall(r"SolCallback\(\s*(\d+)\s*\)", vpxauthor._uncommented(_without_block(script)))}
    return taken, top


def _map_number(m, c):
    for k, v in (m or {}).get("solenoids", {}).items():
        if k != "_" and isinstance(v, dict) and tuple(v.get("coil") or ()) == (c["node"], c["index"]):
            return int(k)
    return None


def stub_block(machine, geo, m=None, cov=None):
    """The VBScript block and what it holds: {"text", "switches", "coils",
    "inserts", "init_in"}."""
    script = geo["script"]
    sws, coils, ins = owed(machine, script, cov)
    taken, top = _sol_numbers(machine["title"], script, m)
    free = (n for n in range(1, top + 1) if n not in taken)
    drops = [s for s in machine["switches"] if s["kind"] == "drop target" and s.get("id")
             and not re.search(r"RESET|TRIP", s["name"].upper())]
    holders = [s for s in machine["switches"] if s["kind"] in ("saucer", "lock") and s.get("id")]
    L = [BEGIN,
         "' A part's sub runs once an object with its name is placed: sw_<NAME> for a switch,",
         "' l_<NAME> for an insert, and for a coil what its sub names (mag_, post_, gate_, kick_).",
         "' Edit the subs freely, but outside this block: the next `padvpx stubs` remakes it.",
         "Dim PadStubLamps, PadStubTick, PadStubsUp : PadStubsUp = False"]
    init = ["Sub PadStubsInit   ' from %s_Init (or the top level): numbers, magnets, lights" % geo["name"],
            "\tIf PadStubsUp Then Exit Sub",
            "\tPadStubsUp = True",
            "\tOn Error Resume Next"]
    subs = []
    names = set()

    def uniq(n):
        base, i = n, 2
        while n.lower() in names:
            n, i = "%s_%d" % (base, i), i + 1
        names.add(n.lower())
        return n

    # switches
    subs.append("'---- switches: 1000 + the game's switch id")
    for s in sorted(sws, key=lambda s: s["id"] or 0):
        if not s.get("id"):
            continue
        obj, num = uniq("sw_" + ident(s["name"])), 1000 + s["id"]
        k = s["kind"]
        if k in _HOLD:
            subs += ["Sub %s_Hit : Controller.Switch(%d) = 1 : End Sub   ' %s (%s)" % (obj, num, s["name"], k),
                     "Sub %s_UnHit : Controller.Switch(%d) = 0 : End Sub" % (obj, num)]
        elif k == "drop target":
            subs.append("Sub %s_Hit : Controller.Switch(%d) = 1 : End Sub   ' %s: down until its bank resets"
                        % (obj, num, s["name"]))
        elif k == "spinner":
            subs.append("Sub %s_Spin : vpmTimer.PulseSw %d : End Sub   ' %s" % (obj, num, s["name"]))
        elif k == "slingshot":
            subs.append("Sub %s_Slingshot : vpmTimer.PulseSw %d : End Sub   ' %s (the board fires the coil)"
                        % (obj, num, s["name"]))
        else:
            subs.append("Sub %s_Hit : vpmTimer.PulseSw %d : End Sub   ' %s (%s)" % (obj, num, s["name"], k))
    # coils
    subs.append("'---- coils: SolCallback(n), the number told to the controller in PadStubsInit")
    done_coils = []
    for c in sorted(coils, key=lambda c: (c["node"], c["index"])):
        num = _map_number(m, c)
        own = num is None
        if own:
            num = next(free, None)
            if num is None:
                subs.append("' %s: no solenoid number left (1..%d are all taken)" % (c["name"], top))
                continue
            init.append("\tController.PadSolenoid(%d) = Array(%d, %d)   ' %s"
                        % (num, c["node"], c["index"], c["name"]))
        sub = uniq("Sol_" + ident(c["name"]))
        init.append("\tSolCallback(%d) = \"%s\"" % (num, sub))
        k, nm, part = c["kind"], c["name"], ident(c["name"])
        if k == "magnet":
            var = "PadMag_" + part
            L.append("Dim %s" % var)
            init += ["\tSet %s = New cvpmMagnet : %s.InitMagnet mag_%s, 15 : %s.GrabCenter = True"
                     % (var, var, part, var),
                     "\t%s.CreateEvents \"%s\"" % (var, var),
                     "\tIf Err Then Set %s = Nothing : Err.Clear" % var]
            subs.append("Sub %s(aOn) : On Error Resume Next : %s.MagnetOn = aOn : End Sub   ' %s: cvpmMagnet on the "
                        "Trigger mag_%s" % (sub, var, nm, part))
        elif k == "drop reset":
            bank = _partners(c, drops)
            # a TRIP coil knocks the bank down (Deadpool's Lil Deadpool); a reset raises it
            how = "Down" if re.search(r"TRIP|KNOCK", nm.upper()) else "Up"
            if bank:
                subs.append("Sub %s(aOn) : If aOn Then PadStubDrops%s Array(%s), Array(%s) : End If : End Sub   ' %s"
                            % (sub, how, ", ".join('"sw_%s"' % ident(s["name"]) for s in bank),
                               ", ".join(str(1000 + s["id"]) for s in bank), nm))
            else:
                subs.append("Sub %s(aOn) : End Sub   ' %s: the machine names no drop target" % (sub, nm))
        elif k == "kick":
            pair = _partners(c, holders) if holders else []
            obj = "sw_" + ident(pair[0]["name"]) if len(pair) == 1 else "kick_" + part
            up = re.search(r"\bVUK\b|\bUP\s*KICK", nm.upper())
            subs.append("Sub %s(aOn) : If aOn Then PadStubKick \"%s\", %s : End If : End Sub   ' %s: aim it"
                        % (sub, obj, "0, 40, 1.5" if up else "180, 8, 0", nm))
        elif k == "post":
            subs.append("Sub %s(aOn) : PadStubPost \"post_%s\", aOn : End Sub   ' %s: the Wall up while on"
                        % (sub, part, nm))
        elif k == "gate":
            subs.append("Sub %s(aOn) : PadStubGate \"gate_%s\", aOn : End Sub   ' %s: a Gate or Flipper, open "
                        "while on" % (sub, part, nm))
        elif k == "trough":
            subs.append("Sub %s(aOn) : On Error Resume Next : bsTrough.SolOut aOn : End Sub   ' %s: the table's "
                        "cvpmBallStack" % (sub, nm))
        elif k == "auto plunger":
            subs.append("Sub %s(aOn) : If aOn Then PadStubPlunge \"plunger_%s\" : End If : End Sub   ' %s"
                        % (sub, part, nm))
        else:
            subs.append("Sub %s(aOn)   ' %s (%s): what it moves" % (sub, nm, k))
            subs.append("End Sub")
        done_coils.append(dict(c, solenoid=num, sub=sub, told=own))
    # inserts
    init.append("\tSet PadStubLamps = CreateObject(\"Scripting.Dictionary\")")
    for g in ins:
        init.append("\tPadStubAddLamp \"l_%s\", Array(%s)   ' %s" % (
            ident(g["name"]), ", ".join(str(vpxauthor.lamp_number(*k)) for k in g["leds"]), g["name"]))
    if ins:
        init += ["\tSet PadStubTick = New PadStubLampTick",
                 "\tvpmTimer.EnableUpdate PadStubTick, False, True"]
    init.append("End Sub")
    helpers = [
        "'---- the helpers",
        "Function PadStubObj(name)   ' the object by name, or Nothing when it is not placed",
        "\tOn Error Resume Next",
        "\tSet PadStubObj = Nothing",
        "\tSet PadStubObj = Eval(name)",
        "End Function",
        "Sub PadStubDropsUp(objs, sws)",
        "\tDim i, o",
        "\tOn Error Resume Next",
        "\tFor i = 0 To UBound(objs)",
        "\t\tSet o = PadStubObj(objs(i))",
        "\t\tIf Not o Is Nothing Then o.IsDropped = False",
        "\t\tController.Switch(sws(i)) = 0",
        "\tNext",
        "End Sub",
        "Sub PadStubDropsDown(objs, sws)",
        "\tDim i, o",
        "\tOn Error Resume Next",
        "\tFor i = 0 To UBound(objs)",
        "\t\tSet o = PadStubObj(objs(i))",
        "\t\tIf Not o Is Nothing Then o.IsDropped = True",
        "\t\tController.Switch(sws(i)) = 1",
        "\tNext",
        "End Sub",
        "Sub PadStubKick(name, angle, speed, incline)",
        "\tDim o : Set o = PadStubObj(name)",
        "\tOn Error Resume Next",
        "\tIf Not o Is Nothing Then o.Kick angle, speed, incline",
        "End Sub",
        "Sub PadStubPost(name, aOn)",
        "\tDim o : Set o = PadStubObj(name)",
        "\tOn Error Resume Next",
        "\tIf Not o Is Nothing Then o.IsDropped = Not CBool(aOn)",
        "End Sub",
        "Sub PadStubGate(name, aOn)",
        "\tDim o : Set o = PadStubObj(name)",
        "\tOn Error Resume Next",
        "\tIf o Is Nothing Then Exit Sub",
        "\to.Open = CBool(aOn)",
        "\tIf Err Then",
        "\t\tErr.Clear",
        "\t\tIf aOn Then",
        "\t\t\to.RotateToEnd",
        "\t\tElse",
        "\t\t\to.RotateToStart",
        "\t\tEnd If",
        "\tEnd If",
        "End Sub",
        "Sub PadStubPlunge(name)",
        "\tDim o : Set o = PadStubObj(name)",
        "\tOn Error Resume Next",
        "\tIf o Is Nothing Then Exit Sub",
        "\to.AutoPlunger = True",
        "\to.Fire",
        "End Sub",
        "Sub PadStubAddLamp(name, nums)   ' a placed Light and its lamp numbers",
        "\tDim o : Set o = PadStubObj(name)",
        "\tIf o Is Nothing Then Exit Sub",
        "\tIf Not PadStubLamps.Exists(name) Then PadStubLamps.Add name, Array(o, nums)",
        "End Sub",
        "Class PadStubLampTick   ' vpmTimer calls Update every tick",
        "\tPublic Sub Update",
        "\t\tDim r, k, v",
        "\t\tOn Error Resume Next",
        "\t\tFor Each r In PadStubLamps.Items",
        "\t\t\tv = 0",
        "\t\t\tFor Each k In r(1)",
        "\t\t\t\tIf Controller.Lamp(k) Then v = 1",
        "\t\t\tNext",
        "\t\t\tIf r(0).State <> v Then r(0).State = v",
        "\t\tNext",
        "\tEnd Sub",
        "End Class",
    ]
    text = "\r\n".join(L + init + subs + helpers + ["PadStubsInit   ' a table whose Init has not run it yet", END])
    return {"text": text, "switches": [s for s in sws if s.get("id")], "coils": done_coils, "inserts": ins}


def with_stubs(script, block, table_name):
    """The script with the block in place of any old one, and PadStubsInit
    called first thing in <table>_Init when the script has one."""
    s = _without_block(script)
    s = re.sub(r"^[ \t]*PadStubsInit[ \t]*'[^\r\n]*PAD stubs[^\r\n]*\r?\n", "", s, flags=re.M)
    m = re.search(r"^([ \t]*(?:Public[ \t]+|Private[ \t]+)?Sub[ \t]+%s_Init\b[^\r\n]*\r?\n)" % re.escape(table_name),
                  s, re.I | re.M)
    if m:
        s = s[:m.end()] + "\tPadStubsInit   ' the PAD stubs' numbers, magnets and lights\r\n" + s[m.end():]
    return s.rstrip("\r\n") + "\r\n\r\n" + block + "\r\n", bool(m)


def stubs_cmd(title, table, out=None, print_only=False, tables_dir=None, say=print):
    machine, err = _machine(title, tables_dir)
    if err:
        say(err["error"])
        return err
    geo = table_geometry(table)
    brain = vpxauthor.script_brain(geo["script"])
    m, map_path = _map_for_table(title, table)
    cov = vpxauthor.coverage(m) if m else None
    if m and not machine["coils"]:
        machine["coils"] = vpxauthor.coils_from_map(m)
    got = stub_block(machine, geo, m, cov)
    script, in_init = with_stubs(geo["script"], got["text"], geo["name"])
    result = {"title": machine["title"], "table": os.path.basename(table), "brain": brain,
              "map": os.path.basename(map_path) if map_path else "",
              "switches": len(got["switches"]), "coils": len(got["coils"]), "inserts": len(got["inserts"]),
              "init_in": "%s_Init" % geo["name"] if in_init else "the top level"}
    say("%s: stubs for %d switches, %d coils, %d inserts the table has not got%s; PadStubsInit runs from %s"
        % (result["table"], result["switches"], result["coils"], result["inserts"],
           " (by %s)" % result["map"] if map_path else " (none of them named in its script)", result["init_in"]))
    if brain != "pad":
        say("note: this table is not driven by PAD yet (its script is a %s table's): the stubs talk to "
            "PAD.Controller, so patch it first (padvpx patch) and stub the (PAD).vpx" % brain)
    if print_only:
        say(got["text"].replace("\r\n", "\n"))
        result["text"] = got["text"]
        return result
    import vpxfile
    out = out or os.path.join(os.path.dirname(os.path.abspath(table)),
                              "%s (stubs).vpx" % os.path.splitext(os.path.basename(table))[0])
    if os.path.abspath(out) == os.path.abspath(table):
        tmp = out + ".stubs-tmp"
        vpxfile.write_patched(table, tmp, script=script)
        os.replace(tmp, out)
    else:
        vpxfile.write_patched(table, out, script=script)
    result["out"] = out
    say("written: %s" % out)
    return result


def main(argv):
    if len(argv) < 2 or argv[0] not in ("match-leds", "stubs"):
        print(__doc__)
        return 2
    cmd, title, rest = argv[0], argv[1], argv[2:]

    def opt(k):
        return rest[rest.index(k) + 1] if k in rest and rest.index(k) + 1 < len(rest) else None
    table = opt("--table")
    if not table or not os.path.isfile(table):
        print("%s wants --table \"<file.vpx>\" (a table that is there)" % cmd)
        return 2
    if cmd == "match-leds":
        got = match_leds_cmd(title, table, opt("--into"), "--confirm" in rest, opt("--out"),
                             tables_dir=opt("--tables"))
    else:
        got = stubs_cmd(title, table, opt("--out"), "--print" in rest, tables_dir=opt("--tables"))
    return 1 if "error" in got else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
