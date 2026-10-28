#!/usr/bin/env python3
"""vpxgen.py - a Visual Pinball table GENERATED from a Spike 2 title's own
device tables, for the emulator to drive.

    python vpxgen.py <title> <rig tables dir> <out dir> [--card <image>]

Where no tribute table exists, the title's build still says where everything
is: `switch_xy.txt` (every switch's playfield position, joined to the running
game's switch ids), `device_xy.txt` (the coils) and `led_io.txt` (every LED,
RGB triples and all), over `playfield.png`, the game's own drawing of the
playfield from its service menu. This puts a flat table under that drawing:

  * the playfield image as the table's art, the table sized to it;
  * a Trigger at every switch a ball rolls over (lanes, orbits, ramp optos),
    a Bumper at every pop, a standup or drop HitTarget at every target, a
    Spinner at every spinner, a Kicker saucer at every VUK / eject / lock /
    scoop whose coil the game fires, a slingshot wall at each sling;
  * a Light at every LED with a position (an RGB insert is one light);
  * flippers at the flipper coils, a plunger and ball release in the shooter
    lane, a drain kicker, the outer walls, the lane guides to the flippers;
  * the bridge script of a scripted tribute (vpxshadow.gen) over a base
    script of this file's own, so the real game owns balls, coils and lamps.

There are no ramps, no plastics, no posts beyond the lane guides, and no
sounds: the table is the title's geometry made playable, for a title that
has no tribute yet. The object prototypes (vpxgen_protos.json) are Visual
Pinball's own example table's objects where it has the kind, with every
name, material and image string blanked.
"""
import base64
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

import vpxfile    # noqa: E402
import vpxshadow  # noqa: E402

TABLE_W = 952.0                  # Visual Pinball units across a standard playfield
BASE_TABLE = r"C:\Visual Pinball\tables\Nudge Test and Calibration.vpx"


# --------------------------------------------------------------- tables ---

def read_switches(d):
    out = []
    for ln in open(os.path.join(d, "switch_xy.txt"), encoding="utf-8", errors="replace"):
        f = ln.split()
        if len(f) >= 6 and f[0].isdigit():
            out.append({"id": int(f[0]), "node": int(f[1]), "bit": int(f[2]),
                        "name": " ".join(f[3:-2]), "x": float(f[-2]), "y": float(f[-1])})
    return out


def read_switch_list(d):
    """Every switch the running game has (switch_list.txt: id num node bit
    name), cabinet ones included, which switch_xy.txt leaves out."""
    out = []
    for ln in open(os.path.join(d, "switch_list.txt"), encoding="utf-8", errors="replace"):
        f = ln.split(None, 4)
        if len(f) == 5 and f[0].isdigit():
            out.append({"id": int(f[0]), "node": int(f[2]), "bit": int(f[3]), "name": f[4].strip()})
    return out


def read_group_node(d):
    """{device-table group: bus node} from the rig's group_node.txt (coilmap's
    per-title derivation): a coil's `grp` column is its board's place in the
    title's node directory, NOT its node - James Bond's group 7 is node 8."""
    out = {}
    try:
        for ln in open(os.path.join(d, "group_node.txt"), encoding="utf-8", errors="replace"):
            f = ln.split()
            if len(f) >= 2 and f[0].isdigit() and f[1].isdigit():
                out[int(f[0])] = int(f[1])
    except OSError:
        pass
    return out


def read_coils(d):
    gn = read_group_node(d)
    out = []
    for ln in open(os.path.join(d, "device_xy.txt"), encoding="utf-8", errors="replace"):
        f = ln.split()
        if len(f) >= 10 and f[0] == "coil":
            grp = int(f[-4])
            if grp not in gn:
                continue                      # a board the title never named: no address
            out.append({"name": " ".join(f[1:-8]), "x": float(f[-8]), "y": float(f[-7]),
                        "node": gn[grp], "idx": int(f[-3])})
    return out


def read_leds(d):
    out = []
    for ln in open(os.path.join(d, "led_io.txt"), encoding="utf-8", errors="replace"):
        if ln.startswith("#"):
            continue
        m = re.match(r"^(\d+)\s+(\d+)\s+(.*?)\s{2,}(\d+)\s+(\d+)\s+(\S+)\s*(.*)$", ln.rstrip("\n"))
        if m:
            out.append({"node": int(m.group(1)), "idx": int(m.group(2)), "name": m.group(3).strip(),
                        "x": float(m.group(4)), "y": float(m.group(5)), "image": m.group(7).strip()})
    return out


def image_size(d):
    from PIL import Image
    with Image.open(os.path.join(d, "playfield.png")) as im:
        return im.size


# -------------------------------------------------------------- objects ---

PROTOS = json.load(open(os.path.join(HERE, "vpxgen_protos.json"), encoding="utf-8"))


def proto(key):
    return base64.b64decode(PROTOS[key]["b64"])


def f32(v):
    return struct.pack("<f", float(v))


def i32(v):
    return struct.pack("<i", int(v))


def narrow(s):
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def ident(s):
    """A VBScript identifier from a device name: `LEFT RAMP ENTER OPTO` ->
    `swLeftRampEnterOpto`; a leading digit gets a letter."""
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", s).split()
    name = "".join(w[:1].upper() + w[1:].lower() for w in words)
    return name if name and not name[0].isdigit() else "X" + name


def set_points(data, points, slingshot_seg=None, smooth=False):
    """A shaped item (wall, trigger, light, ramp) with its drag points
    replaced: `points` are (x, y) on the table; the segment from point i to
    i+1 gets the slingshot flag when i == slingshot_seg; `smooth` makes every
    point a curve point (a ramp's path)."""
    t = struct.unpack_from("<i", data, 0)[0]
    out = bytearray(struct.pack("<i", t))
    tmpl = None
    recs = list(vpxfile.item_records(data, 4))
    # the first drag point's record run is the template for every point
    i = 0
    while i < len(recs):
        tag, payload, _ = recs[i]
        if tag == "DPNT":
            j = i + 1
            run = []
            while recs[j][0] != "ENDB":
                run.append((recs[j][0], recs[j][1]))
                j += 1
            if tmpl is None:
                tmpl = run
            i = j + 1              # past this point's ENDB
            continue
        if tag == "ENDB":
            break                  # the item's own end: points go before it
        out += vpxfile.biff_record(tag, payload)
        i += 1
    assert tmpl is not None, "the prototype has no drag points"
    for k, (x, y) in enumerate(points):
        out += vpxfile.biff_record("DPNT", b"")
        for tag, payload in tmpl:
            if tag == "VCEN":
                payload = struct.pack("<ff", x, y) + payload[8:]
            elif tag == "SLNG":
                payload = i32(1 if slingshot_seg == k else 0)
            elif tag == "SMTH":
                payload = i32(1 if smooth else 0)
            out += vpxfile.biff_record(tag, payload)
        out += vpxfile.biff_record("ENDB", b"")
    out += vpxfile.biff_record("ENDB", b"")
    return bytes(out)


def circle(cx, cy, r, n=12):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def thick(points, t):
    """The closed outline of an open path `t` wide: a wall along a guide
    line. Each vertex moves half the width along the mean of its two
    segments' normals (a mitre, clamped so a sharp corner stays bounded),
    out along one side and back along the other."""
    n = len(points)
    if n < 2:
        raise ValueError("a path needs two points")
    h = t / 2.0
    normals = []
    for i in range(n - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        normals.append((-dy / ln, dx / ln))
    side = []
    for i in range(n):
        if i == 0:
            nx, ny = normals[0]
        elif i == n - 1:
            nx, ny = normals[-1]
        else:
            ax, ay = normals[i - 1]
            bx, by = normals[i]
            nx, ny = ax + bx, ay + by
            ln = math.hypot(nx, ny) or 1.0
            nx, ny = nx / ln, ny / ln
            cos = max(0.3, nx * ax + ny * ay)       # mitre length 1/cos, at most ~3.3x
            nx, ny = nx / cos, ny / cos
        side.append((nx * h, ny * h))
    left = [(x + ox, y + oy) for (x, y), (ox, oy) in zip(points, side)]
    right = [(x - ox, y - oy) for (x, y), (ox, oy) in zip(points, side)]
    return left + right[::-1]


def sling_winding(points, seg):
    """A slingshot wall's corners in the order Visual Pinball kicks OUT of:
    it takes a slingshot's push from the winding of the polygon, and a
    polygon wound clockwise on screen (y down) kicked the ball INTO the
    triangle, where it rattled for ever. Such a polygon is reversed, and the
    kicking edge (segment `seg`, from point seg to seg+1) renumbered."""
    n = len(points)
    area = sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
               for i in range(n))
    if area <= 0:
        return list(points), seg
    return list(reversed(points)), (n - 2 - seg) % n


def load_geo(title):
    """A title's traced geometry (vpxgen_geo/<title>.json, or the user's own
    in ~/.pad-vpx/geo), or None: the generator then builds its plain outline."""
    for d in (os.path.join(os.path.expanduser("~"), ".pad-vpx", "geo"), os.path.join(HERE, "vpxgen_geo")):
        p = os.path.join(d, "%s.json" % title)
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return None


#: Visual Pinball's ramp kinds (RampType): a flat ramp has solid walls, a
#: 4-wire ramp is a wireform that holds the ball on all sides
RAMP_TYPES = {"flat": 0, "wire": 1}


class Gen:
    def __init__(self, title, tables, card=None):
        self.title = title
        self.tables = tables
        self.card = card
        self.switches = read_switches(tables)
        self.all_switches = read_switch_list(tables)
        self.coils = read_coils(tables)
        self.leds = read_leds(tables)
        self.img_w, self.img_h = image_size(tables)
        self.scale = TABLE_W / self.img_w
        self.table_h = self.img_h * self.scale
        self.items = []
        self.names = set()
        self.map = {"title": title, "output": "%s (PAD, generated).vpx" % title,
                    "solenoid_max": 68, "cabinet": {}, "keys_skip_orig": [],
                    "switches": {}, "trough": {}, "saucers": {}, "solenoids": {},
                    "lamps": {}, "extra_vbs": ""}
        self.script_parts = []
        self.rep = []
        self.geo = load_geo(title)
        # a switch whose trigger rides a ramp: id -> ramp name
        self.surface = {int(k): v for k, v in ((self.geo or {}).get("switch_surface") or {}).items()}

    # -- geometry
    def pt(self, x, y):
        return x * self.scale, y * self.scale

    def add(self, data):
        kind, name, _ = vpxfile.VpxTable.item_info(data)
        assert name not in self.names, "two objects named %s" % name
        self.names.add(name)
        self.items.append(data)
        return name

    def clone(self, key, name, x, y, fields=None):
        data = vpxfile.clone_item(proto(key), name, x, y)
        if fields:
            data = vpxfile.set_fields(data, fields)
        return data

    def wall(self, name, points, slingshot_seg=None, height=50.0, hit_event=False):
        if slingshot_seg is not None:
            points, slingshot_seg = sling_winding(points, slingshot_seg)
        data = vpxfile.set_fields(proto("wall"), {
            "NAME": vpxfile.wide(name), "HTTP": f32(height), "HTEV": i32(1 if hit_event else 0),
            "VSBL": i32(1), "SVBL": i32(1), "CLDW": i32(1), "SLGF": f32(80.0 if slingshot_seg is not None else 0.0)})
        return self.add(set_points(data, points, slingshot_seg))

    def geo_wall(self, spec, name=None):
        """One wall of the traced geometry: an open guide path `thick` wide,
        or a `closed` polygon (with a `slingshot` segment, for a sling)."""
        pts = [self.pt(x, y) for x, y in spec["points"]]
        if spec.get("closed"):
            poly = pts
        else:
            poly = thick(pts, spec.get("thick", 6) * self.scale)
        sling = spec.get("slingshot")
        return self.wall(name or spec["name"], poly, slingshot_seg=sling,
                         height=spec.get("height", 50.0), hit_event=sling is not None)

    def flipper(self, name, x, y, key="flipper_left"):
        """A flipper at its coil's place, unless the traced geometry places it
        (`flippers`: {name: {"at": [x, y], "start": deg, "end": deg,
        "length": units}}): an upper flipper rarely points the way the main
        ones do."""
        spec = ((self.geo or {}).get("flippers") or {}).get(name)
        if not spec:
            return self.clone(key, name, x, y)
        if spec.get("at"):
            x, y = self.pt(*spec["at"])
        fields = {}
        if "start" in spec:
            fields["ANGS"] = f32(spec["start"])
        if "end" in spec:
            fields["ANGE"] = f32(spec["end"])
        if "length" in spec:
            fields["FLPR"] = f32(spec["length"])
        return self.clone(key, name, x, y, fields)

    def saucer_dir(self, sw, y):
        """Which way a saucer kicks: the traced geometry's `saucer_dir`
        {switch id: degrees, 0 = up}, else down the table from the upper
        half and up it from the lower."""
        d = ((self.geo or {}).get("saucer_dir") or {}).get(str(sw["id"]))
        if d is not None:
            return float(d)
        return 180.0 if y < self.table_h / 2 else 0.0

    def geo_switch_walls(self):
        """{switch id: wall name} for the traced walls that are a switch (a sling)."""
        return {int(w["switch"]): w["name"] for w in (self.geo or {}).get("walls", []) if "switch" in w}

    def ramp(self, spec):
        """A ramp along a path: flat (solid floor and walls) or a wireform,
        its height going linearly from h0 at the first point to h1 at the
        last - a ramp that climbs then falls is two ramps end to end."""
        x0, y0 = self.pt(*spec["points"][0])
        kind = spec.get("kind", "flat")
        wall = float(spec.get("wall", 62.0 if kind == "flat" else 0.0))
        w = float(spec.get("width", 70.0 if kind == "flat" else 55.0))
        data = vpxfile.clone_item(proto("ramp"), spec["name"], x0, y0)
        data = vpxfile.set_fields(data, {
            "HTBT": f32(spec.get("h0", 0.0)), "HTTP": f32(spec.get("h1", 60.0)),
            "WDBT": f32(w), "WDTP": f32(w), "TYPE": i32(RAMP_TYPES[kind]),
            "WLHL": f32(wall), "WLHR": f32(wall),
            "WVHL": f32(min(wall, 30.0)), "WVHR": f32(min(wall, 30.0)), "RVIS": i32(1),
            # the example table's ramp is decoration (Collidable off): ours
            # must carry the ball
            "CLDR": i32(1)})
        pts = [self.pt(x, y) for x, y in spec["points"]]
        return self.add(set_points(data, pts, smooth=True))

    # -- the switches
    def switch_kind(self, sw):
        n = sw["name"].upper()
        if any(w in n for w in ("FLIPPER", "TROUGH", "SHOOTER LANE", "BUTTON", "COIN", "TILT",
                                "SLAM", "DOOR", "ENCODER", "HOME", "JETPACK", "DIVERTER",
                                "COMMAND", "VOLUME", "TICKET", "QR ")):
            return None
        if "SLINGSHOT" in n:
            return "sling"
        if "POP BUMPER" in n and "EXIT" not in n:
            return "bumper"
        if "DROP" in n:
            return "drop"
        if "TARGET" in n:
            return "target"
        if "SPINNER" in n:
            return "spinner"
        if any(w in n for w in ("VUK", "EJECT", "SCOOP", "LOCK")) and "LANE" not in n:
            return "saucer"
        return "trigger"

    def coil_named(self, *words):
        for c in self.coils:
            n = c["name"].upper()
            if all(w in n for w in words):
                return c
        return None

    def build(self):
        W, H = TABLE_W, self.table_h
        sw_by_name = {s["name"].upper(): s for s in self.all_switches}
        sw_by_name.update({s["name"].upper(): s for s in self.switches})
        cab = self.map["cabinet"]
        for key, words in (("start", ("START BUTTON",)), ("launch", ("LOCKDOWN BUTTON", "ACTION BUTTON")),
                           ("tilt", ("TILT PENDULUM",)), ("slam", ("SLAM TILT",)),
                           ("left_flipper", ("LEFT FLIPPER BUTTON",)), ("right_flipper", ("RIGHT FLIPPER BUTTON",)),
                           ("up_left_flipper", ("UP LEFT FLIPPER BUTTON",)),
                           ("up_right_flipper", ("UP RIGHT FLIPPER BUTTON",)), ("coin", ("LEFT COIN",))):
            hits = [s for n, s in sw_by_name.items() if n in words]
            if hits:
                cab[key] = 1000 + hits[0]["id"]
        if "launch" in cab:
            cab["launch_key"] = "LockBarKey"
            self.map["keys_skip_orig"] = ["StartGameKey", "AddCreditKey", "LockBarKey"]
        # trough + shooter lane
        trough = sorted([s for s in self.switches if re.match(r"TROUGH \d$", s["name"].upper())],
                        key=lambda s: int(s["name"].split()[-1]))
        jam = [s for s in self.switches if "TROUGH JAM" in s["name"].upper()]
        lane = sw_by_name.get("SHOOTER LANE")
        lane_x = (lane["x"] * self.scale) if lane else W - 45
        lane_wall_x = lane_x - 40
        geo = self.geo
        if geo:
            # the title's traced geometry: its outline, guides, slings, apron
            # and ramps, from the drawing's own lines
            self.geo_wall(geo["outline"], name="Outline")
            for spec in geo.get("walls", []):
                self.geo_wall(spec)
            for spec in geo.get("ramps", []):
                self.ramp(spec)
        else:
            # no traced geometry: the playfield's outline with a round top
            # (an arch of a quarter of the width at each corner), and the
            # shooter lane's wall
            r = W * 0.25
            arc = lambda cx, cy, a0, a1: [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                                          for a in range(a0, a1 + 1, 10)]
            outline = [(8, H)] + arc(r + 8, r + 8, 180, 270) + arc(W - r - 8, r + 8, 270, 360) + [(W - 8, H)]
            self.wall("Outline", thick(outline, 16), height=60.0)
            self.wall("ShooterLaneWall", thick([(lane_wall_x, H), (lane_wall_x, H * 0.42)], 12))
        # flippers
        lf, rf, uf = self.coil_named("LEFT", "FLIPPER"), self.coil_named("RIGHT", "FLIPPER"), self.coil_named("UPPER", "FLIPPER")
        if lf and "UPPER" in lf["name"].upper():
            lf = [c for c in self.coils if c["name"].upper() == "LEFT FLIPPER"][0]
        if rf and "UPPER" in rf["name"].upper():
            rf = [c for c in self.coils if c["name"].upper() == "RIGHT FLIPPER"][0]
        lx, ly = self.pt(lf["x"], lf["y"]) if lf else (W * 0.3, H * 0.9)
        rx, ry = self.pt(rf["x"], rf["y"]) if rf else (W * 0.62, H * 0.9)
        self.add(self.clone("flipper_left", "LeftFlipper", lx, ly))
        self.add(self.clone("flipper_right", "RightFlipper", rx, ry))
        if uf:
            ux, uy = self.pt(uf["x"], uf["y"])
            self.add(self.flipper("UpperLeftFlipper", ux, uy))
        if geo and geo.get("drain"):
            dx, dy = self.pt(*geo["drain"])
            self.add(self.clone("kicker", "Drain", dx, dy, {"RADI": f32(40.0), "TYPE": i32(0)}))
        else:
            # the apron: guides from the outlanes down to the flipper bases, a drain between
            self.wall("ApronLeft", thick([(8, H * 0.78), (lx - 60, ly - 10), (lx - 30, ly + 36)], 12))
            self.wall("ApronRight", thick([(lane_wall_x, H * 0.78), (rx + 60, ry - 10), (rx + 30, ry + 36)], 12))
            drain_y = min(H - 60, max(ly, ry) + 160)
            self.add(self.clone("kicker", "Drain", (lx + rx) / 2, drain_y, {"RADI": f32(60.0), "TYPE": i32(0)}))
        self.map["trough"] = {"release": "BallRelease", "drain": "Drain",
                              "switches": [s["id"] for s in trough] + [j["id"] for j in jam[:1]],   # TROUGH 1 first: the eject end
                              "balls": max(1, len(trough)), "kick": [0, 4]}
        # the shooter lane: ball release at its foot, the rest trigger above it
        rel_y = H - 90
        self.add(self.clone("kicker", "BallRelease", lane_x, rel_y, {"RADI": f32(30.0), "TYPE": i32(0)}))
        self.add(self.clone("plunger", "Plunger", lane_x, H - 40))
        tr = vpxfile.set_fields(self.clone("trigger", "ShooterLane", lane_x, rel_y - 70), {"RADI": f32(28.0)})
        self.add(set_points(tr, circle(lane_x, rel_y - 70, 28)))
        if lane:
            self.map["plunger"] = {"lane_trigger": "ShooterLane", "lane_switch": lane["id"], "autoplunge": "plungerIM"}
        # every other switch
        for s in self.switches:
            kind = self.switch_kind(s)
            if kind is None or s["x"] <= 0 and s["y"] <= 0:
                continue
            x, y = self.pt(s["x"], s["y"])
            name = ident(s["name"])
            if kind == "trigger":
                fields = {"RADI": f32(26.0)}
                if s["id"] in self.surface:
                    fields["SURF"] = narrow(self.surface[s["id"]])     # it rides that ramp
                data = vpxfile.set_fields(self.clone("trigger", name, x, y), fields)
                self.add(set_points(data, circle(x, y, 26)))
                self.map["switches"][name] = {"id": s["id"], "event": "hit", "name": s["name"]}
            elif kind == "bumper":
                self.add(self.clone("bumper", name, x, y, {"RADI": f32(44.0), "FORC": f32(15.0),
                                                         "HAHE": i32(1), "COLI": i32(1)}))
                self.map["switches"][name] = {"id": s["id"], "event": "hit", "name": s["name"]}
            elif kind == "spinner":
                self.add(self.clone("spinner", name, x, y, {"ROTA": f32(0.0), "LGTH": f32(70.0)}))
                self.map["switches"][name] = {"id": s["id"], "event": "spin", "name": s["name"]}
            elif kind in ("target", "drop"):
                data = vpxfile.set_fields(proto("droptarget" if kind == "drop" else "target"), {
                    "NAME": vpxfile.wide(name),
                    "VPOS": struct.pack("<fff", x, y, 0.0) + b"\x00\x00\x00\x00",
                    "VSIZ": struct.pack("<fff", 32.0, 32.0, 32.0) + b"\x00\x00\x00\x00",
                    "ROTZ": f32(0.0), "HTEV": i32(1), "ISDR": i32(0)})
                self.add(data)
                self.map["switches"][name] = {"id": s["id"], "event": "hit", "name": s["name"]}
                if kind == "drop":
                    self.drops = getattr(self, "drops", []) + [name]
            elif kind == "sling" and s["id"] in self.geo_switch_walls():
                # the traced sling wall is this switch's
                wname = self.geo_switch_walls()[s["id"]]
                self.map["switches"][wname] = {"id": s["id"], "event": "slingshot", "name": s["name"]}
            elif kind == "sling":
                left = x < W / 2
                pts = [(x - 40, y + 60), (x + 50, y - 50)] if left else [(x + 40, y + 60), (x - 50, y - 50)]
                pts = pts + [(pts[1][0] + (-30 if left else 30), pts[1][1] + 70)]
                self.wall(name, pts, slingshot_seg=0, hit_event=True)
                self.map["switches"][name] = {"id": s["id"], "event": "slingshot", "name": s["name"]}
            elif kind == "saucer":
                coil = self.saucer_coil(s)
                self.add(self.clone("kicker", name, x, y, {"RADI": f32(28.0), "TYPE": i32(0)}))
                self.map["saucers"][name] = {"switch": s["id"], "dir": self.saucer_dir(s, y),
                                             "power": 20, "name": s["name"]}
                if coil:
                    self.coil_use(coil, "bs%s.SolOut" % name)
        # coils: trough, auto plunger, drops, flippers
        t = self.coil_named("TROUGH")
        if t:
            self.coil_use(t, "bsTrough.SolOut")
        a = self.coil_named("AUTO", "PLUNGER")
        if a:
            self.coil_use(a, "PadAutoPlunge")
        d = self.coil_named("DROP")
        if d and getattr(self, "drops", None):
            self.coil_use(d, "PadResetDrops")
            self.map["extra_vbs"] += "Sub PadResetDrops(e) : If e Then %s : End If : End Sub\n" % " : ".join(
                "%s.IsDropped = 0" % n for n in self.drops)
        for key, num, c in (("left", 48, lf), ("right", 46, rf), ("upper", 36, uf)):
            if c:
                self.map["solenoids"][str(num)] = {"coil": [c["node"], c["idx"]], "name": c["name"], "callback": None}
        if lf and rf:
            self.map["game_on"] = {"number": 40, "coils": [[lf["node"], lf["idx"]], [rf["node"], rf["idx"]]]}
        self.map["flippers"] = {"sLLFlipper": "SolLFlipper", "sLRFlipper": "SolRFlipper"}
        if uf:
            self.map["flippers"]["sULFlipper"] = "SolULFlipper"
        # lights
        groups = {}
        for led in self.leds:
            if led["node"] in (0, 1, 7, 13) or led["x"] <= 0 or led["x"] >= self.img_w or led["y"] >= self.img_h:
                continue
            if led["image"] and "playfield" not in led["image"].lower():
                continue
            base = re.sub(r"[- ]?[RGB]$", "", led["name"]).strip()
            groups.setdefault(base, []).append(led)
        # an RGB insert is three LEDs whose names end in R, G and B; anything
        # else keeps its whole name (BATH-O-SUB is one lamp, not a B channel)
        split = {}
        for base, leds in groups.items():
            ends = sorted(l["name"][-1] for l in leds)
            if len(leds) == 3 and ends == ["B", "G", "R"]:
                split[base] = leds
            else:
                for l in leds:
                    split[l["name"]] = [l]
        groups = split
        for base, leds in groups.items():
            x, y = self.pt(leds[0]["x"], leds[0]["y"])
            name = "L" + ident(base)
            if name in self.names:
                name += "_%d_%d" % (leds[0]["node"], leds[0]["idx"])
            r = 22.0 if "FLASH" not in base.upper() else 34.0
            data = vpxfile.set_fields(self.clone("light", name, x, y), {
                "RADI": f32(r * 2), "STAT": i32(0), "COLR": i32(0x00FFFFFF if len(leds) > 1 else 0x0060D0FF),
                "COL2": i32(0x00FFFFFF), "BULT": i32(0), "SHBM": i32(0), "VSBL": i32(1)})
            self.add(set_points(data, circle(x, y, r)))
            self.map["lamps"][name] = {"leds": [[l["node"], l["idx"]] for l in leds], "name": base}
        # timers: core.vbs's PinMAMETimer (coils and lamps every tick), its
        # PulseTimer (`PulseTimer_Init` hands it to vpmTimer, which PulseSw
        # and every delayed switch depend on - without it no hit reaches
        # the game), and the test hook
        self.add(self.clone("timer", "PinMAMETimer", -200, 100, {"TMON": i32(1), "TMIN": i32(1)}))
        self.add(self.clone("timer", "PulseTimer", -200, 150, {"TMON": i32(1), "TMIN": i32(100)}))
        self.add(self.clone("timer", "PadTestTimer", -200, 200, {"TMON": i32(1), "TMIN": i32(100)}))
        # the test shooter (vpxkeys.py shoot): a kicker off the table that a
        # test moves to a spot, makes a ball in and kicks
        self.add(self.clone("kicker", "PadTestKicker", -150, 300, {"RADI": f32(25.0), "TYPE": i32(0)}))
        self.map["test_shoot"] = True

    def saucer_coil(self, sw):
        words = [w for w in sw["name"].upper().split() if w not in ("OPTO", "1", "2", "3", "SWITCH")]
        best = None
        for c in self.coils:
            cn = c["name"].upper().split()
            score = sum(1 for w in words if w in cn)
            if score and (best is None or score > best[0]):
                best = (score, c)
        return best[1] if best and best[0] >= max(1, len(words) - 1) else None

    def coil_use(self, c, callback):
        used = {int(k) for k in self.map["solenoids"]}
        num = next(n for n in range(1, 34) if n not in used)
        self.map["solenoids"][str(num)] = {"coil": [c["node"], c["idx"]], "name": c["name"], "callback": callback}

    # -- the script
    def base_script(self):
        upper = "UpperLeftFlipper" in self.names
        return "\n".join([
            "' %s - generated by vpxgen.py from the title's own device tables" % self.title,
            "Option Explicit",
            "Randomize",
            "Const BallSize = 50",
            "Const BallMass = 1",
            "On Error Resume Next",
            'ExecuteGlobal GetTextFile("core.vbs")',
            'If Err Then MsgBox "Can\'t open core.vbs"',
            "On Error Goto 0",
            "Dim plungerIM",
            "' the bridge's saucer and drain handlers call it (every tribute defines it)",
            "Sub PlaySoundAt(sound, obj)",
            "\tPlaySound sound, 0, 1",
            "End Sub",
            "Sub Table1_Init",
            "\tSet plungerIM = New cvpmImpulseP",
            "\tplungerIM.InitImpulseP ShooterLane, 45, 0.6",
            "\tplungerIM.Random 1.5",
            '\tplungerIM.CreateEvents "plungerIM"',
            "End Sub",
            ] + self.flipper_sub("SolLFlipper", "LeftFlipper") + self.flipper_sub("SolRFlipper", "RightFlipper")
            + (self.flipper_sub("SolULFlipper", "UpperLeftFlipper") if upper else []) + [
            "Sub PadShoot(x, y, a, s)   ' a test ball at (x, y), moving at angle a (0 = up), speed s",
            "\tOn Error Resume Next",
            "\tDim b, r",
            "\tSet b = PadTestKicker.CreateBall",
            "\tPadTestKicker.Kick 0, 0",
            "\tr = a * 3.14159265 / 180",
            "\tb.X = x",
            "\tb.Y = y",
            "\tb.Z = 25",
            "\tb.VelZ = 0",
            "\tb.VelX = s * Sin(r)",
            "\tb.VelY = -s * Cos(r)",
            "\tIf Err Then PadShootLog \"PadShoot: \" & Err.Description",
            "\tSet PadBall = b",
            "\tPadTraceN = 60",
            "\tPadShootLog \"shoot \" & x & \" \" & y & \" \" & a & \" \" & s",
            "End Sub",
            "Dim PadBall, PadTraceN : PadTraceN = 0",
            "Sub PadTraceTick   ' the test ball's place, every test tick, for six seconds",
            "\tIf PadTraceN <= 0 Then Exit Sub",
            "\tPadTraceN = PadTraceN - 1",
            "\tOn Error Resume Next",
            "\tPadShootLog \"at \" & Int(PadBall.X) & \" \" & Int(PadBall.Y) & \" \" & Int(PadBall.Z)",
            "End Sub",
            "Sub PadShootLog(t)",
            "\tDim fso, f",
            "\tSet fso = CreateObject(\"Scripting.FileSystemObject\")",
            "\tSet f = fso.OpenTextFile(fso.GetSpecialFolder(2) & \"\\padshoot.log\", 8, True)",
            "\tf.WriteLine t",
            "\tf.Close",
            "End Sub",
            ""])

    @staticmethod
    def flipper_sub(sub, obj):
        return ["Sub %s(e)" % sub, "\tIf e Then", "\t\t%s.RotateToEnd" % obj, "\tElse",
                "\t\t%s.RotateToStart" % obj, "\tEnd If", "End Sub"]

    def script(self):
        m = json.loads(json.dumps(self.map))
        m["_lightseqs"] = []
        text, rep = vpxshadow.patch(self.base_script(), m)
        self.rep = rep
        return text


# --------------------------------------------------------------- writer ---

def write_table(base, dst, title, gamedata, items, image_name, image_path, w, h):
    """A new .vpx from `base`: its GameData replaced (sizes, playfield image,
    item/image/collection counts, name, script), its items and collections
    gone, ours written, the playfield image added, the MAC re-signed."""
    import shutil
    import pythoncom
    from win32com import storagecon as sc
    table = vpxfile.VpxTable(base)
    gd = gamedata
    gd = vpxfile.replace_field(gd, "LEFT", f32(0))
    gd = vpxfile.replace_field(gd, "TOPX", f32(0))
    gd = vpxfile.replace_field(gd, "RGHT", f32(w))
    gd = vpxfile.replace_field(gd, "BOTM", f32(h))
    gd = vpxfile.replace_field(gd, "IMAG", narrow(image_name))
    gd = vpxfile.replace_field(gd, "SEDT", i32(len(items)))
    n_img = struct.unpack("<i", table.gamedata_field("SIMG"))[0]
    gd = vpxfile.replace_field(gd, "SIMG", i32(n_img + 1))
    gd = vpxfile.replace_field(gd, "SCOL", i32(0))
    gd = vpxfile.replace_field(gd, "NAME", vpxfile.wide("Table1"))   # the script's event prefix
    png = open(image_path, "rb").read()
    img = (vpxfile.biff_record("NAME", narrow(image_name)) + vpxfile.biff_record("PATH", narrow(image_name + ".png"))
           + vpxfile.biff_record("WDTH", i32(w)) + vpxfile.biff_record("HGHT", i32(h))
           + vpxfile.biff_record("JPEG", b"") + vpxfile.biff_record("NAME", narrow(image_name))
           + vpxfile.biff_record("PATH", narrow(image_name + ".png")) + vpxfile.biff_record("SIZE", i32(len(png)))
           + vpxfile.biff_record("DATA", png) + vpxfile.biff_record("ENDB", b"")
           + vpxfile.biff_record("ALTV", f32(128.0)) + vpxfile.biff_record("ENDB", b""))
    old_items = len(table.items)
    old_cols = len(table.collections)
    table.collections = []
    tname = title.encode("utf-16-le")
    table.info["TableName"] = tname
    mac = table.digest(gd)
    table.ole.close()
    shutil.copyfile(base, dst)
    mode = sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE | sc.STGM_TRANSACTED
    root = pythoncom.StgOpenStorage(dst, None, mode, None, 0)
    stg = root.OpenStorage("GameStg", None, mode, None, 0)
    for i in range(old_items):
        stg.DestroyElement("GameItem%d" % i)
    for i in range(old_cols):
        stg.DestroyElement("Collection%d" % i)
    cmode = sc.STGM_CREATE | sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE
    for name, data in [("GameData", gd), ("MAC", mac), ("Image%d" % n_img, img)] + \
            [("GameItem%d" % i, item) for i, item in enumerate(items)]:
        stm = stg.CreateStream(name, cmode, 0, 0)
        stm.Write(data)
        stm.Commit(0)
    stg.Commit(0)
    info = root.OpenStorage("TableInfo", None, mode, None, 0)
    stm = info.CreateStream("TableName", cmode, 0, 0)
    stm.Write(tname)
    stm.Commit(0)
    info.Commit(0)
    root.Commit(0)
    return mac


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    title, tables, outdir = argv[1:4]
    card = argv[argv.index("--card") + 1] if "--card" in argv else None
    base = os.environ.get("PAD_VPX_BASE", BASE_TABLE)
    g = Gen(title, tables, card)
    g.build()
    script = g.script()
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, g.map["output"])
    t = vpxfile.VpxTable(base)
    gd = vpxfile.with_script(t.gamedata, script)      # the base's own script goes
    t.ole.close()
    mac = write_table(base, dst, "%s (PAD, generated)" % title, gd, g.items, "playfield",
                      os.path.join(tables, "playfield.png"), int(TABLE_W), int(g.table_h))
    # the map goes beside the table AND where the controller looks for the
    # user's own maps (~/.pad-vpx/maps/<title>.shadow.json)
    json.dump(g.map, open(os.path.join(outdir, "%s.generated.shadow.json" % title), "w", encoding="utf-8"), indent=2)
    import padcontroller
    os.makedirs(padcontroller.USER_MAPS, exist_ok=True)
    json.dump(g.map, open(os.path.join(padcontroller.USER_MAPS, "%s.shadow.json" % title), "w", encoding="utf-8"), indent=2)
    print("map -> %s" % os.path.join(padcontroller.USER_MAPS, "%s.shadow.json" % title))
    open(os.path.join(outdir, g.map["output"][:-4] + ".script.vbs"), "w", encoding="utf-8", newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    kinds = {}
    for d in g.items:
        kinds[vpxfile.VpxTable.item_info(d)[0]] = kinds.get(vpxfile.VpxTable.item_info(d)[0], 0) + 1
    print("wrote %s\n  MAC %s  verify %s\n  %d objects: %s\n  %d switches, %d saucers, %d coils, %d lights"
          % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(g.items),
             ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items())),
             len(g.map["switches"]), len(g.map["saucers"]), len(g.map["solenoids"]), len(g.map["lamps"])))
    for r in g.rep:
        print("  " + r)
    if card:
        import padlaunch
        padlaunch.remember_card(title, os.path.abspath(card))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
