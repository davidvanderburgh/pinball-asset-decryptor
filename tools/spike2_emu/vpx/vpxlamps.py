#!/usr/bin/env python3
"""vpxlamps.py - check a tribute table's lamp map against the machine (PAD-859).

    python vpxlamps.py audit <map.json> "<table.vpx>" <led_io.txt> [overlay.png]
    python vpxlamps.py lit <map.json> "<table.vpx>" <led_io.txt> <padled> <out.png>
    python vpxlamps.py suggest <map.json> "<table.vpx>" <led_io.txt> [--write]
    python vpxlamps.py rgb <map.json> <led_io.txt> [--write]

A shadow map (vpxshadow.py) puts table lights on the machine's LEDs by hand.
Bond's first map left a third of its lights unwired and put several on the
wrong insert, and nothing said so: a mode's shot arrows simply never lit.

audit: fits the table's light positions to led_io.txt's (an affine fit over
the lights the map puts on ONE positioned insert, refitted without the worst
ones), then lists every playfield LED no table light shows, every table light
the map neither wires nor holds dark, and every wired light farther from its
insert than the fit's spread allows. `overlay.png` draws both on the drawing.

lit: what the table shows for one padled sample (a rig's dump/padled): every
wired light lit the way PAD.Controller + the generated script would light it,
drawn on the table's own playfield picture.

suggest: what audit found, mended by the fit: each insert no light shows
takes the nearest table light the map leaves free (within the fit's spread),
a free light that close to an insert already shown joins it (a tribute's
bulb-and-insert twins), and an insert with no light near gets a retrofit
light at its place. --write puts them in the map. Tables whose art the fit
does not hold (rms over 10 px) are refused: map those by eye.

rgb: marks every lamp on an insert's -R/-G/-B LEDs `rgb`, so the light shows
the insert's colour.
"""
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import vpxfile  # noqa: E402

GI_PREFIXES = ("gi",)


def read_led_io(path):
    """(node, index) -> (name, x, y) of every LED placed on the playfield drawing."""
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        p = line.split()
        # the image column: "playfield", or Metallica's TestMode/metallica_playfield_with_handle_cropped
        if line.startswith("#") or len(p) < 7 or "playfield" not in p[-1].lower():
            continue
        out[(int(p[0]), int(p[1]))] = (" ".join(p[2:-4]), int(p[-4]), int(p[-3]))
    return out


NOT_PLAYFIELD = re.compile(r"SPEAKER|TOPPER|BACKBOX|CABINET|COIN|START BUTTON|TOURNAMENT|LOCKDOWN|"
                           r"SHOOTER ILLUM|FLIPPER BUTTON|\bGI\b|GEN(ERAL)? ILLUM", re.I)


def read_unplaced(path):
    """(node, index) -> name of the LEDs a build names but does not place
    (Rush's and Foo Fighters' device tables have no positions): the
    cabinet, speakers, topper and GI left out."""
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        p = line.split()
        if line.startswith("#") or len(p) < 6 or p[-1] != "-" or p[-3:-1] != ["0", "0"]:
            continue
        name = " ".join(p[2:-3])
        if int(p[0]) > 1 and not NOT_PLAYFIELD.search(name):
            out[(int(p[0]), int(p[1]))] = name
    return out


def gi_lights(table):
    """Names in the table's GI collections (Batman 66 names its GI Light001...)."""
    out = set()
    for data in table.collections:
        name, members = "", []
        for tag, payload, _ in vpxfile.biff_records(data, 0):
            if tag == "NAME":
                name = vpxfile.unwide(payload).strip("\x00")
            elif tag == "ITEM":
                members.append(vpxfile.unwide(payload).strip("\x00"))
        if name.lower().startswith("gi"):
            out.update(members)
    return out


def table_lights(table):
    """name -> (x, y) of every Light item, GI strings left out."""
    gi = gi_lights(table)
    out = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        if kind == "Light" and pos and not name.lower().startswith(GI_PREFIXES) and name not in gi:
            out[name] = pos
    return out


def wired(m):
    """name -> [(node, index)] of the map's lamps, lamp calls and retrofit lights."""
    out = {}
    for sect in (m.get("lamps", {}), m.get("lamp_calls", {}),
                 m.get("retrofit_lights", {}).get("lights", {})):
        for k, v in sect.items():
            if k != "_" and isinstance(v, dict):
                out[k] = [tuple(x) for x in v["leds"]]
    return out


def _solve(pairs):
    """Least-squares affine (table x, y) -> (drawing x, y): 6 numbers."""
    # normal equations for each output coordinate, 3 unknowns each
    def fit(k):
        s = [[0.0] * 3 for _ in range(3)]
        r = [0.0] * 3
        for (x, y), d in pairs:
            v = (x, y, 1.0)
            for i in range(3):
                r[i] += v[i] * d[k]
                for j in range(3):
                    s[i][j] += v[i] * v[j]
        return _gauss(s, r)
    return fit(0), fit(1)


def _gauss(a, b):
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        a[c], a[p] = a[p], a[c]
        for r in range(n):
            if r != c and a[c][c]:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [a[i][n] / a[i][i] if a[i][i] else 0.0 for i in range(n)]


def apply(fit, pos):
    fx, fy = fit
    return (fx[0] * pos[0] + fx[1] * pos[1] + fx[2], fy[0] * pos[0] + fy[1] * pos[1] + fy[2])


def fit_table(lights, wires, leds):
    """The affine fit and its rms, from wired lights on one positioned LED
    group (an RGB insert's three share a place), the worst fifth dropped."""
    pairs = []
    for name, group in wires.items():
        places = {leds[g][1:] for g in group if g in leds}
        if name in lights and len(places) == 1:
            pairs.append((lights[name], places.pop()))
    if len(pairs) < 6:
        return None, None
    fit = _solve(pairs)
    for _ in range(2):
        err = sorted(pairs, key=lambda p: math.dist(apply(fit, p[0]), p[1]))
        keep = err[:max(6, int(len(err) * 0.8))]
        fit = _solve(keep)
    rms = math.sqrt(sum(math.dist(apply(fit, p[0]), p[1]) ** 2 for p in keep) / len(keep))
    return fit, rms


def _base(name):
    """An RGB insert's name without its -R/-G/-B."""
    return name[:-2] if name[-2:] in ("-R", "-G", "-B") else name


def audit(m, table, leds, unplaced=None):
    lights = table_lights(table)
    wires = wired(m)
    dark = set(m.get("dark", []))
    fit, rms = fit_table(lights, wires, leds)
    shown = {g for group in wires.values() for g in group}
    rep = {"fit_rms": rms, "unwired_leds": [], "unwired_unplaced": [], "unmapped_lights": [], "far": []}
    base = {}
    for k, (name, x, y) in leds.items():
        base.setdefault(_base(name), []).append(k)
    for b, ks in sorted(base.items()):
        if not any(k in shown for k in ks):
            rep["unwired_leds"].append((b, sorted(ks)))
    named = {}
    for k, name in (unplaced or {}).items():
        named.setdefault(_base(name), []).append(k)
    for b, ks in sorted(named.items()):
        if not any(k in shown for k in ks):
            rep["unwired_unplaced"].append((b, sorted(ks)))
    script = table.script().lower()
    for name, pos in sorted(lights.items()):
        if name in wires or name in dark:
            continue
        if not re.search(r"\b%s\b" % re.escape(name.lower()), script):
            continue                    # decoration: the script never lights it
        near = None
        if fit:
            p = apply(fit, pos)
            near = min(base.items(), key=lambda kv: math.dist(leds[kv[1][0]][1:], p))
            near = (near[0], round(math.dist(leds[near[1][0]][1:], p)))
        rep["unmapped_lights"].append((name, near))
    if fit:
        limit = max(4 * rms, 25)
        for name, group in sorted(wires.items()):
            if name not in lights or group[0] not in leds:
                continue
            d = math.dist(apply(fit, lights[name]), leds[group[0]][1:])
            if d > limit:
                rep["far"].append((name, leds[group[0]][0], round(d)))
    return rep, fit


def led_levels(path):
    """(node, index) -> level of one padled sample (padled.h: val[] at 20)."""
    data = open(path, "rb").read()
    return {(n, i): data[20 + n * 96 + i] for n in range(16) for i in range(96)}


def table_image(table):
    """The playfield picture (GameData IMAG) as PIL, and the table's size."""
    from PIL import Image, ImageFile
    import io
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    want = table.gamedata_field("IMAG")
    want = want[4:].decode("latin1").lower() if want else ""
    i = 0
    while table.ole.exists("GameStg/Image%d" % i):
        data = table.ole.openstream("GameStg/Image%d" % i).read()
        name = ""
        for tag, payload, _ in vpxfile.biff_records(data, 0):
            if tag == "NAME":
                name = payload[4:].decode("latin1").lower()
                break
        if name == want:
            for magic in (b"\x89PNG", b"\xff\xd8\xff", b"RIFF"):
                k = data.find(magic)
                if k >= 0:
                    img = Image.open(io.BytesIO(data[k:])).convert("RGB")
                    break
            else:
                img = None
            right = struct.unpack("<f", table.gamedata_field("RGHT")[:4])[0]
            bottom = struct.unpack("<f", table.gamedata_field("BOTM")[:4])[0]
            return img, right, bottom
        i += 1
    return None, 0, 0


def lamp_value(levels, group, rgb):
    """What PAD.Controller reports for a wired light (padcontroller._poll_lamps)."""
    import padcontroller
    vals = [levels.get(g, 0) for g in group]
    if max(vals) < padcontroller.LAMP_ON:
        return 0
    if rgb and len(group) == 3:
        return padcontroller.rgb_value(*vals)
    return 1


def draw_lit(m, table, levels, out, height=1600):
    from PIL import ImageDraw
    img, right, bottom = table_image(table)
    s = height / float(bottom)
    img = img.resize((int(right * s), height)).point(lambda v: v * 0.45)
    d = ImageDraw.Draw(img)
    objs = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        if pos:
            objs[name] = pos
    entries = {}
    for sect in (m.get("lamps", {}), m.get("lamp_calls", {}),
                 m.get("retrofit_lights", {}).get("lights", {})):
        entries.update((k, v) for k, v in sect.items() if k != "_" and isinstance(v, dict))
    n = 0
    for name, v in entries.items():
        # a Light where it is, a retrofit one where it goes, a lamp call at what shows it
        if name in objs:
            places = [objs[name]]
        elif v.get("at"):
            places = [tuple(v["at"])]
        else:
            places = [objs[o] for o in v.get("show", ()) if o in objs]
        val = lamp_value(levels, [tuple(x) for x in v["leds"]], v.get("rgb"))
        n += bool(val) and bool(places)
        for pos in places:
            x, y = pos[0] * s, pos[1] * s
            if val:
                col = (255, 240, 120) if val == 1 else (val & 255, (val >> 8) & 255, (val >> 16) & 255)
                d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=col, outline=(255, 255, 255), width=2)
            else:
                d.ellipse((x - 4, y - 4, x + 4, y + 4), outline=(110, 110, 110), width=1)
    img.save(out)
    return n


def invert(fit):
    (a, b, c), (d, e, f) = fit
    det = a * e - b * d
    return ((e / det, -b / det, (b * f - c * e) / det), (-d / det, a / det, (c * d - a * f) / det))


def draw_audit(m, table, leds, rep, fit, out, height=2400):
    """The table's art: wired lights green (their insert's name), lights
    neither wired nor dark red, dark ones grey, and every insert no light
    shows magenta at its place through the fit."""
    from PIL import ImageDraw
    img, right, bottom = table_image(table)
    s = height / float(bottom)
    img = img.resize((int(right * s), height)).point(lambda v: v * 0.6)
    d = ImageDraw.Draw(img)
    wires = wired(m)
    dark = set(m.get("dark", []))
    retro = m.get("retrofit_lights", {}).get("lights", {})
    pos = table_lights(table)
    pos.update((k, tuple(v["at"])) for k, v in retro.items() if k != "_")
    for name, (x, y) in pos.items():
        x, y = x * s, y * s
        if name in wires:
            col, label = (60, 255, 60), "%s %s" % (name, leds.get(wires[name][0], ("?",))[0])
        elif name in dark:
            col, label = (150, 150, 150), name
        else:
            col, label = (255, 60, 60), name
        d.ellipse((x - 5, y - 5, x + 5, y + 5), outline=col, width=2)
        d.text((x + 7, y - 6), label[:28], fill=col)
    if fit:
        inv = invert(fit)
        for b, ks in rep["unwired_leds"]:
            x, y = apply(inv, leds[ks[0]][1:])
            x, y = x * s, y * s
            d.rectangle((x - 6, y - 6, x + 6, y + 6), outline=(255, 0, 255), width=2)
            d.text((x + 8, y + 2), b[:28], fill=(255, 0, 255))
    img.save(out)


def is_rgb(leds, group):
    """Three LEDs named <insert>-R, -G, -B, in that order."""
    names = [leds.get(tuple(g), ("",))[0] for g in group]
    return len(names) == 3 and [n[-2:] for n in names] == ["-R", "-G", "-B"]


def retrofit_name(insert):
    return "Pad" + "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", insert))


def suggest(m, table, leds):
    """{"lamps": {light: entry}, "retrofit": {name: entry}} mending the map by
    the fit, or None when the fit does not hold."""
    rep, fit = audit(m, table, leds)
    if not fit or rep["fit_rms"] > 10:
        return None
    lights = table_lights(table)
    script = table.script().lower()
    wires = wired(m)
    dark = set(m.get("dark", []))
    # a VPW table's v*/b* lights are its Lampz twins of a wired control light, and follow it
    twin = {n for n in lights if n[:1] in "vb" and n[1:] in wires}
    free = {n: apply(fit, p) for n, p in lights.items()
            if n not in wires and n not in dark and n not in twin
            and re.search(r"\b%s\b" % re.escape(n.lower()), script)}
    groups = {}
    for k, (name, x, y) in leds.items():
        groups.setdefault(_base(name), {"leds": [], "at": (x, y)})["leds"].append(list(k))
    shown = {g for group in wires.values() for g in group}
    unwired = {b: g for b, g in groups.items() if not any(tuple(k) in shown for k in g["leds"])}
    near = max(3 * rep["fit_rms"], 15)
    out = {"lamps": {}, "retrofit": {}}

    def entry(b, note):
        g = groups[b]
        e = {"leds": sorted(g["leds"])}
        if is_rgb(leds, e["leds"]):
            e["rgb"] = True
        e["name"] = b + (" (%s)" % note if note else "")
        return e
    pairs = sorted((math.dist(p, g["at"]), n, b) for n, p in free.items() for b, g in unwired.items())
    for d, n, b in pairs:
        if d > near or n in out["lamps"] or b not in unwired:
            continue
        out["lamps"][n] = entry(b, "PAD-859: the free light %d px from it" % d)
        del unwired[b]
    for n, p in free.items():                     # twins of an insert already shown
        if n in out["lamps"]:
            continue
        b, g = min(groups.items(), key=lambda kv: math.dist(kv[1]["at"], p))
        if math.dist(g["at"], p) <= near / 2:
            out["lamps"][n] = entry(b, "PAD-859: beside it, %d px" % math.dist(g["at"], p))
    inv = invert(fit)
    by_place = {}                   # inserts at one place (a bash toy's 1-4): one light, lit by any
    for b, g in sorted(unwired.items()):
        by_place.setdefault(tuple(g["at"]), []).append(b)
    for place, names in by_place.items():
        at = apply(inv, place)
        clone = min((n for n in lights if n in wires), key=lambda n: math.dist(lights[n], at))
        e = entry(names[0], "")
        if len(names) > 1:
            e = {"leds": sorted(k for b in names for k in groups[b]["leds"]), "name": " + ".join(names)}
        e["clone"], e["at"] = clone, [int(round(at[0])), int(round(at[1]))]
        out["retrofit"][retrofit_name(names[0])] = e
    return out


RETRO_DOC = ("inserts with no table light: a new Light cloned from `clone`, at [x, y] "
             "(the led_io place through the fit, vpxlamps.py suggest)")


def write_lamps(path, add, retro, rgb_names=()):
    """Add lamps entries and retrofit lights to a map file, and set `rgb` on
    the named lamps, keeping its one-entry-per-line layout (or, for a plain
    json.dump file like Star Wars', dumping it again)."""
    text = open(path, encoding="utf-8").read()
    m = json.loads(text)
    if text == json.dumps(m, indent=2) + "\n":
        for name in rgb_names:
            m["lamps"][name]["rgb"] = True
        m["lamps"].update(add)
        if retro:
            if "retrofit_lights" not in m:      # after the lamps, as the line-layout maps have it
                items = list(m.items())
                at = [k for k, _ in items].index("lamps") + 1
                items.insert(at, ("retrofit_lights", {"_": RETRO_DOC, "lights": {}}))
                m = dict(items)
            m["retrofit_lights"]["lights"].update(retro)
        open(path, "w", encoding="utf-8", newline="").write(json.dumps(m, indent=2) + "\n")
        return
    for name in rgb_names:
        v = m["lamps"][name]
        old = "%s: %s" % (json.dumps(name), json.dumps(v, ensure_ascii=False))
        if old not in text:
            old = "%s: %s" % (json.dumps(name), json.dumps(v))
        assert old in text, name
        v2 = dict(v)
        v2["rgb"] = True
        if "name" in v2:                           # rgb before the name, as written by hand
            v2 = {k: v2[k] for k in ("leds", "rgb")} | {k: x for k, x in v2.items() if k not in ("leds", "rgb")}
        text = text.replace(old, "%s: %s" % (json.dumps(name), json.dumps(v2, ensure_ascii=False)), 1)
    if add:
        start = text.index('  "lamps": {')
        end = text.index("\n  }", start)
        lines = "".join(",\n    %s: %s" % (json.dumps(k), json.dumps(v)) for k, v in add.items())
        text = text[:end] + lines + text[end:]
    if retro:
        m = json.loads(text)
        if "retrofit_lights" in m:
            start = text.index('  "retrofit_lights": {')
            lk = text.index('"lights": {', start)
            end = text.index("\n    }", lk)
            ind = "      "
            lines = "".join(",\n%s%s: %s" % (ind, json.dumps(k), json.dumps(v)) for k, v in retro.items())
            text = text[:end] + lines + text[end:]
        else:
            start = text.index('  "lamps": {')
            end = text.index("\n  }", start) + len("\n  }")
            body = ",\n".join("      %s: %s" % (json.dumps(k), json.dumps(v)) for k, v in retro.items())
            sect = (',\n  "retrofit_lights": {\n    "_": %s,\n    "lights": {\n%s\n    }\n  }'
                    % (json.dumps(RETRO_DOC), body))
            text = text[:end] + sect + text[end:]
    json.loads(text)
    open(path, "w", encoding="utf-8", newline="").write(text)


def main(argv):
    if len(argv) >= 4 and argv[1] == "rgb":
        if argv[2].endswith(".vpxmap.json"):
            # a ROM table's own lamp code (NFadeL, Lampz) takes 0/1 only
            print("refused: %s is a ROM table's map; its lamps stay 0/1" % argv[2])
            return 1
        m = json.load(open(argv[2], encoding="utf-8"))
        leds = read_led_io(argv[3])
        leds.update((k, (n,)) for k, n in read_unplaced(argv[3]).items())
        names = [k for k, v in m.get("lamps", {}).items()
                 if k != "_" and isinstance(v, dict) and not v.get("rgb") and is_rgb(leds, v["leds"])]
        print("%d lamps on an RGB insert without rgb: %s" % (len(names), " ".join(names)))
        if "--write" in argv and names:
            write_lamps(argv[2], {}, {}, names)
        return 0
    if len(argv) >= 5 and argv[1] == "suggest":
        m = json.load(open(argv[2], encoding="utf-8"))
        s = suggest(m, vpxfile.VpxTable(argv[3]), read_led_io(argv[4]))
        if s is None:
            print("refused: the fit does not hold on this table; map it by eye")
            return 1
        for k, v in s["lamps"].items():
            print("lamp     %-20s %s" % (k, v["name"]))
        for k, v in s["retrofit"].items():
            print("retrofit %-28s at %s (clone %s)" % (k, v["at"], v["clone"]))
        if "--write" in argv:
            write_lamps(argv[2], s["lamps"], s["retrofit"])
        return 0
    if len(argv) < 5 or argv[1] not in ("audit", "lit"):
        print(__doc__)
        return 2
    m = json.load(open(argv[2], encoding="utf-8"))
    table = vpxfile.VpxTable(argv[3])
    leds = read_led_io(argv[4])
    if argv[1] == "lit":
        n = draw_lit(m, table, led_levels(argv[5]), argv[6])
        print("%d lights lit -> %s" % (n, argv[6]))
        return 0
    rep, fit = audit(m, table, leds, read_unplaced(argv[4]))
    print("fit: %s" % ("rms %.1f drawing px" % rep["fit_rms"] if fit else "too few single-insert lights"))
    print("playfield inserts no table light shows (%d):" % len(rep["unwired_leds"]))
    for b, ks in rep["unwired_leds"]:
        print("   %-30s %s" % (b, " ".join("%d/%d" % k for k in ks)))
    if rep["unwired_unplaced"]:
        print("LEDs the build names but does not place, no table light shows (%d):" % len(rep["unwired_unplaced"]))
        for b, ks in rep["unwired_unplaced"]:
            print("   %-30s %s" % (b, " ".join("%d/%d" % k for k in ks)))
    print("table lights neither wired nor dark (%d):" % len(rep["unmapped_lights"]))
    for name, near in rep["unmapped_lights"]:
        print("   %-20s nearest %s" % (name, "%s at %d px" % near if near else "-"))
    print("wired lights far from their insert (%d):" % len(rep["far"]))
    for name, ins, dist in rep["far"]:
        print("   %-20s %-30s %d px" % (name, ins, dist))
    if len(argv) > 5:
        draw_audit(m, table, leds, rep, fit, argv[5])
        print("overlay -> %s" % argv[5])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
