"""A three-screen cabinet's extras for a patched Spike 2 table (PAD-1304).

On a cabinet the game's own screen takes the backglass monitor, so B2S's
backglass has to go elsewhere, and the cabinet's own lights - the backbox's
BACKBOX GI, the START and LOCKDOWN (or ACTION) buttons - have nothing to
follow under Visual Pinball. This module is everything about that which is
not the controller's live poll:

* the kit's `cabinet` settings (~/.pad-vpx.json), with their defaults;
* `cabinet_leds`: where each of those lights is on the title's boards, read
  from the rig's device_xy.txt (the game's own device table, with the group
  -> node map coilmap derives), led_io.txt when that has none;
* `write_res`: `<table>.res` beside a patched table - B2S.Server's own
  table-specific ScreenRes.txt - with the backglass put on the screen chosen,
  and the B2S DMD hidden through B2STableSettings.xml when asked;
* `bulb_names`: the named bulbs of a .directb2s, which the Visual Pinball
  tab offers for BACKBOX GI to light (B2SSetIllumination sets a bulb by name).

The controller (padcontroller.py) reads the settings and the lights, sends
the buttons, the shaker and the light strips (`strip_events`, PAD-1571) to
DOF as E events and BACKBOX GI to the bulbs named.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for _p in (HERE, RIG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import coilmap    # noqa: E402

#: the cabinet lights the controller follows: key -> what the game's tables
#: call them. LOCKDOWN BUTTON is an RGB LED (-R/-G/-B); a title with an
#: ACTION BUTTON of its own (the Home editions) has that in its place.
LIGHTS = {
    "backbox_gi": re.compile(r"^BACKBOX GI\b", re.I),
    "start": re.compile(r"^START BUTTON\b", re.I),
    "lockdown": re.compile(r"^(LOCKDOWN|ACTION) BUTTON\b", re.I),
}

#: DOF events for the buttons and the shaker motor (PAD-1460): off (0) until
#: the person picks numbers, so a table's DOF config never hears an event it
#: uses for something else. E190 / E191 / E192 are the numbers the tab suggests.
SUGGESTED_DOF = {"start": 190, "lockdown": 191, "shaker": 192, "strips": 200}

#: PAD-1571: the cabinet's light strips to DOF. A DOF E event carries one
#: number, and the colour it lights is the one the DOF config gives it, so a
#: strip's colour goes as a choice among these: each part of each side has an
#: E event per colour, the one nearest what the game shows lit at its
#: brightness and the rest 0. Hex, because DOF reads #rrggbb whatever colour
#: names its config defines.
STRIP_COLOURS = (("red", "#FF0000"), ("orange", "#FF8000"), ("yellow", "#FFFF00"),
                 ("green", "#00FF00"), ("cyan", "#00FFFF"), ("blue", "#0000FF"),
                 ("purple", "#FF00FF"), ("white", "#FFFFFF"))
#: how many parts a side may be cut into, bottom to top
STRIP_PARTS_MAX = 8

RES_KEYS = ("pf_w", "pf_h", "bg_w", "bg_h", "bg_screen", "bg_x", "bg_y",
            "dmd_w", "dmd_h", "dmd_x", "dmd_y", "dmd_flip")


# ---------------------------------------------------------------- settings --

def settings(kit):
    """The kit's cabinet settings, every key present:

    backglass   0 = where B2S puts it (no .res written), else the monitor
                number (padisplay's numbering: the main one 1) it fills
    hide_dmd    hide B2S's own DMD window (the game's screen is the DMD)
    dof_start, dof_lockdown   the DOF E event each button's LED is sent as,
                0 = not sent
    dof_shaker  the DOF E event the machine's SHAKER MOTOR is sent as, on
                while the game drives it (PAD-1460), 0 = not sent
    dof_strips  the first DOF E event of the cabinet's light strips
                (PAD-1571), 0 = not sent; strip_numbers numbers the rest
    strip_parts how many parts each side's strip is cut into, 1..8
    gi_bulbs   {title: [bulb name, ...]} that follow BACKBOX GI
    """
    c = kit.get("cabinet") if isinstance(kit.get("cabinet"), dict) else {}

    def num(k):
        try:
            v = int(c.get(k) or 0)
        except (TypeError, ValueError):
            return 0
        return v if v > 0 else 0
    bulbs = c.get("gi_bulbs") if isinstance(c.get("gi_bulbs"), dict) else {}
    return {"backglass": num("backglass"), "hide_dmd": bool(c.get("hide_dmd")),
            "dof_start": num("dof_start"), "dof_lockdown": num("dof_lockdown"),
            "dof_shaker": num("dof_shaker"), "dof_strips": num("dof_strips"),
            "strip_parts": min(STRIP_PARTS_MAX, num("strip_parts") or 1),
            "gi_bulbs": {str(t): [str(b) for b in v if str(b)]
                         for t, v in bulbs.items() if isinstance(v, list)}}


def update(kit, **changes):
    """The kit with its cabinet settings changed (unknown keys refused)."""
    c = settings(kit)
    for k, v in changes.items():
        if k not in c or k == "gi_bulbs":
            raise KeyError(k)
        c[k] = bool(v) if k == "hide_dmd" else max(0, int(v or 0))
        if k == "strip_parts":
            c[k] = min(STRIP_PARTS_MAX, max(1, c[k]))
    kit = dict(kit)
    kit["cabinet"] = c
    return kit


def set_bulbs(kit, title, names):
    c = settings(kit)
    names = [str(n) for n in names if str(n)]
    if names:
        c["gi_bulbs"][title] = names
    else:
        c["gi_bulbs"].pop(title, None)
    kit = dict(kit)
    kit["cabinet"] = c
    return kit


# ------------------------------------------------------------------ lights --

def _lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


#: led_io.txt's row: node, index, the name, then x and y
_LED_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S.*?)\s{2,}-?\d+\s+-?\d+(\s|$)")


#: where the lights are on every Spike 2 title whose device table names them
#: (17 of 17 on the rigs, 2026-11-14): the backbox board is node 0, the
#: cabinet board node 1. Used for a title whose device table could not be
#: read (no rows at all); one that reads but names no such light has none.
SPIKE2_PLACES = {"backbox_gi": [(0, 0)], "start": [(1, 2)], "lockdown": [(1, 4), (1, 5), (1, 7)]}


def cabinet_leds(tables_dir):
    """{key: [(node, index), ...]} of the LIGHTS a title's boards have, from
    its tables folder (the rig's dump/tables/<title>). The device table is
    the game's own and names every LED, the cabinet board's too; led_io.txt
    (which leaves the cabinet's rows out on many titles) only where the
    device table gives none. A light the title does not have is left out."""
    out = {}
    dev = os.path.join(tables_dir, "device_xy.txt")
    rows = [r for r in coilmap.parse_rows(_lines(dev)) if r.get("kind") == "led"]
    if rows:
        gn = coilmap.group_node_for(dev, dev_rows=coilmap.parse_rows(_lines(dev)))
        for r in rows:
            node = gn.get(r["group"])
            if node is None or not 0 <= node < coilmap.NODES:
                continue
            for key, rx in LIGHTS.items():
                if rx.match(r["name"].strip()):
                    leds = out.setdefault(key, [])
                    if (node, r["index"]) not in leds:
                        leds.append((node, r["index"]))
    io = {}
    for line in _lines(os.path.join(tables_dir, "led_io.txt")):
        mo = None if line.startswith("#") else _LED_ROW.match(line)
        if not mo:
            continue
        for key, rx in LIGHTS.items():
            a = (int(mo.group(1)), int(mo.group(2)))
            if key not in out and rx.match(mo.group(3).strip()) and a not in io.get(key, []):
                io.setdefault(key, []).append(a)
    out.update(io)
    if not out and not coilmap.parse_rows(_lines(dev)):
        return {k: list(v) for k, v in SPIKE2_PLACES.items()}
    return out


# ------------------------------------------------------- strips (PAD-1571) --

def cabinet_strips(tables_dir):
    """The cabinet's light strips as DOF sees them: {"source", "node",
    "sides": [left, right]}, each side a list of pixels BOTTOM FIRST, a pixel
    {colour letter: (node, channel)}; None when the title has neither.

    The blades (node 2, "Cabinet Lights": 48 RGB pixels a side) where the
    title has them; else its backbox speaker lights (node 7: one ring of 23),
    which then light both sides alike, in ring order - "use node 2 for
    cabinet lights and for games lacking it, use node 7" (Mike St P). Read as
    the virtual playfield's cabinet column reads them (cablights)."""
    import cablights
    dev = os.path.join(tables_dir, "device_xy.txt")
    rows = coilmap.parse_rows(_lines(dev))
    if not rows:
        return None
    gn = coilmap.group_node_for(dev, dev_rows=rows)
    secs, _left = cablights.sections(rows, gn, cablights.boards(cablights.nodedir_for(dev)))

    def px(P):
        return {c: tuple(a) for c, a in P["channels"].items() if c in ("R", "G", "B")}
    for S in secs:
        if S["role"] == cablights.EXPRESSION and S["pixels"]:
            bars = S["bars"] or [list(range(len(S["pixels"])))]
            sides = [[px(S["pixels"][k]) for k in bar] for bar in bars]
            if len(sides) == 1:                 # one unsided bar: both sides
                sides = sides * 2
            return {"source": "blades", "node": S["node"], "sides": sides[:2]}
    for S in secs:
        if S["role"] == cablights.SPEAKER and S["pixels"]:
            ring = [px(P) for P in S["pixels"]]
            return {"source": "speakers", "node": S["node"], "sides": [ring, list(ring)]}
    return None


def strip_colour(rgb):
    """(STRIP_COLOURS index, brightness 0..255) of a lit colour, or (None, 0)
    for black: white when its channels are near alike, else the hue's."""
    import colorsys
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    top = max(r, g, b)
    if top <= 0:
        return None, 0
    if min(r, g, b) >= 0.55 * top:
        return len(STRIP_COLOURS) - 1, top
    h = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0] * 360.0
    for i, upto in enumerate((15, 45, 75, 150, 200, 260, 330)):
        if h < upto:
            return i, top
    return 0, top


def _parts(n, parts):
    """[(start, end)] of a side of *n* pixels cut into *parts*, bottom first."""
    parts = max(1, min(parts, n or 1))
    return [(n * k // parts, n * (k + 1) // parts) for k in range(parts)]


def strip_numbers(base, parts):
    """{(side, part, colour index): E number}: side 0 left, 1 right; part 0
    at the bottom. The left side's parts first, eight colours each."""
    out, n = {}, base
    for side in (0, 1):
        for part in range(parts):
            for c in range(len(STRIP_COLOURS)):
                out[(side, part, c)] = n
                n += 1
    return out


def strip_events(base, parts, strips, level, lamp_on=1):
    """[(E number, value)] for every E event of the strips: in each part
    the colour it shows (the sum of its lit pixels) at its brightest
    pixel's level, every other colour 0. *level(node, channel)* reads one
    channel; a level under *lamp_on* is off. Brightness in 15 steps of 17,
    so a fading strip is not a stream of events DOF cannot show anyway."""
    if not base or not strips:
        return []
    nums = strip_numbers(base, parts)
    out = []
    for side, pixels in enumerate(strips["sides"][:2]):
        for part, (a, b) in enumerate(_parts(len(pixels), parts)):
            tot, top = [0, 0, 0], 0
            for P in pixels[a:b]:
                lv = [level(*P[c]) if c in P else 0 for c in ("R", "G", "B")]
                lv = [v if v >= lamp_on else 0 for v in lv]
                tot = [t + v for t, v in zip(tot, lv)]
                top = max([top] + lv)
            mx = max(tot)
            ci = strip_colour([t * 255.0 / mx for t in tot])[0] if mx else None
            val = 0 if ci is None else max(17, int(round(top / 17.0)) * 17)
            for c in range(len(STRIP_COLOURS)):
                out.append((nums[(side, part, c)], val if c == ci else 0))
    return out


def strip_lit(base, parts, events):
    """[(E number, "left red", value)] of the strip events lit in *events*
    (PAD-1603: the controller log names them, so a report says whether PAD
    sent the strips anything); "left p2 red" with parts, part 1 the bottom."""
    if not base:
        return []
    names = {n: k for k, n in strip_numbers(base, parts).items()}
    out = []
    for n, v in events:
        if v and n in names:
            side, part, c = names[n]
            out.append((n, "%s%s %s" % (("left", "right")[side], "" if parts == 1 else " p%d" % (part + 1),
                                        STRIP_COLOURS[c][0]), v))
    return out


def strip_dof_lines(base, parts):
    """The DOF config text for each side's strip toy, {"left", "right"}: an
    effect per part and colour, the part's place given as AT/AH (percent from
    the TOP, so the bottom part is the last), NOBOOL so the value is its
    brightness. A whole strip still names its area (AW100 AH100): DOF only
    plays an effect on an addressable strip when the line gives an area, so
    without one the strip stays dark (PAD-1603, Mike's cabinet). Pasted into the column of an addressable strip in the DOF
    Config Tool (or a directoutputconfig line). Empty with no base."""
    if not base:
        return {"left": "", "right": ""}
    nums = strip_numbers(base, parts)
    out = {}
    for side, key in ((0, "left"), (1, "right")):
        bits = []
        for part, (a, b) in enumerate(_parts(100, parts)):
            area = " AW100 AH100" if parts == 1 else " AT%d AH%d" % (100 - b, b - a)
            for c, (_name, hexc) in enumerate(STRIP_COLOURS):
                bits.append("E%d %s%s NOBOOL" % (nums[(side, part, c)], hexc, area))
        out[key] = "/".join(bits)
    return out


# --------------------------------------------------------------- backglass --

def _b2s_dirs():
    """B2S.Server's folder (where its own ScreenRes.txt is), as its COM
    registration names it; none off Windows or without B2S."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"B2S.Server\CLSID") as k:
            clsid = winreg.QueryValue(k, None)
        for view in ("CLSID", r"WOW6432Node\CLSID"):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, view + "\\" + clsid + r"\InprocServer32") as k:
                    code = winreg.QueryValueEx(k, "CodeBase")[0]
                return [os.path.dirname(code.replace("file:///", "").replace("/", "\\"))]
            except OSError:
                continue
    except OSError:
        pass
    return []


def screenres_source(tables_dir, b2s_dirs=None):
    """The ScreenRes.txt B2S would read for a table in *tables_dir*: the
    tables folder's own, else B2S.Server's; None when there is neither."""
    for d in [tables_dir] + list(_b2s_dirs() if b2s_dirs is None else b2s_dirs):
        p = os.path.join(d or "", "ScreenRes.txt")
        if d and os.path.isfile(p):
            return p
    return None


def parse_screenres(text):
    """The values of a ScreenRes.txt / .res as B2S.Server reads them
    (B2SScreen.ReadB2SSettingsFromFile: a line starting '#' is skipped,
    "@<x>" names the screen at that x), comment lines left out:
    playfield size, backglass size, screen, place, the DMD's size, place and
    flip; any past those (the background picture's) kept as they are."""
    vals = [ln.split("#")[0].strip() if not ln.strip().startswith("#") else None
            for ln in text.splitlines()]
    return [v for v in vals if v is not None and v != ""]


def res_values(base, monitor, mons):
    """ScreenRes values with the backglass filling *monitor* (padisplay's
    {"n", "x", "y", "w", "h"}): its screen given as "@<left x>", which B2S
    matches to the screen at that x, whatever Windows numbers it. *base* is
    the ScreenRes.txt's values, or None to start from the main screen as the
    playfield and no DMD."""
    main = next((m for m in mons if m.get("primary")), mons[0])
    vals = list(base or [])
    if len(vals) < 12:
        vals = [str(main["w"]), str(main["h"]), "0", "0", "1", "0", "0",
                "0", "0", "0", "0", "0"]
    vals[2], vals[3] = str(monitor["w"]), str(monitor["h"])
    vals[4] = "@%d" % monitor["x"]
    vals[5], vals[6] = "0", "0"
    return vals


def res_path(out_vpx):
    """B2S's table-specific ScreenRes: <table>.res beside the table."""
    return os.path.splitext(out_vpx)[0] + ".res"


#: the first line of a .res the kit wrote: one it did not write is the
#: person's own and is never touched
RES_MARK = "# written by PAD (Visual Pinball tab: Backglass screen)"


def write_res(out_vpx, kit, mons, b2s_dirs=None, game_name=None):
    """Write (or take back) <table>.res for a patched table, as the kit's
    cabinet settings say; hide or show the B2S DMD for *game_name* (the name
    B2S knows the table by, its ROM) in B2STableSettings.xml. Returns what
    was done, in words, for the log; a .res the person wrote is left alone."""
    c = settings(kit)
    path = res_path(out_vpx)
    said = []
    ours = os.path.exists(path) and _lines(path)[:1] == [RES_MARK]
    mon = next((m for m in mons if m["n"] == c["backglass"]), None) if c["backglass"] else None
    if mon is None:
        if ours:
            os.remove(path)
            said.append("backglass: back where B2S puts it (%s removed)" % os.path.basename(path))
    elif os.path.exists(path) and not ours:
        said.append("backglass: %s is your own; left as it is" % os.path.basename(path))
    else:
        src = screenres_source(os.path.dirname(os.path.abspath(out_vpx)), b2s_dirs)
        text = open(src, encoding="utf-8", errors="replace").read() if src else ""
        base = parse_screenres(text) if src else None
        vals = res_values(base, mon, mons)
        # B2S reads a "# V2" file's background lines differently: keep it one
        v2 = any(ln.replace(" ", "").startswith("#V2") for ln in text.splitlines())
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(RES_MARK + "\n" + ("# V2\n" if v2 else "") + "\n".join(vals) + "\n")
        said.append("backglass: screen %d (%dx%d), %s" % (
            mon["n"], mon["w"], mon["h"], os.path.basename(path)))
    if game_name:
        changed = set_hide_b2s_dmd(os.path.dirname(os.path.abspath(out_vpx)), game_name, c["hide_dmd"])
        if changed:
            said.append("B2S DMD %s for %s" % ("hidden" if c["hide_dmd"] else "shown", game_name))
    return said


def set_hide_b2s_dmd(tables_dir, game_name, hide):
    """B2STableSettings.xml (B2S.Server's per-table settings, in the tables
    folder): the table's <HideB2SDMD>, 1 to hide B2S's own DMD window, 0 to
    show it. The file is made when there is none and only hiding asks for
    it; everything else in it is kept. True when the file changed."""
    path = os.path.join(tables_dir, "B2STableSettings.xml")
    if not re.match(r"^[A-Za-z_][\w.-]*$", game_name or ""):
        return False
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except FileNotFoundError:
        if not hide:
            return False
        root = ET.Element("B2STableSettings")
        tree = ET.ElementTree(root)
    except (ET.ParseError, OSError):
        return False                                    # never break the person's file
    table = root.find(game_name)
    if table is None:
        if not hide:
            return False
        table = ET.SubElement(root, game_name)
    node = table.find("HideB2SDMD")
    want = "1" if hide else "0"
    if node is not None and (node.text or "").strip() == want:
        return False
    if node is None:
        node = ET.SubElement(table, "HideB2SDMD")
    node.text = want
    tmp = path + ".tmp"
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.replace(tmp, path)
    return True


def bulb_names(directb2s):
    """The named bulbs of a .directb2s, in its order, each once: what
    B2SSetIllumination can light. [] when the file cannot be read."""
    names = []
    try:
        for _, el in ET.iterparse(directb2s, events=("end",)):
            if el.tag == "Bulb":
                n = (el.get("Name") or "").strip()
                if n and n not in names:
                    names.append(n)
            el.clear()                                  # the pictures are large
    except (ET.ParseError, OSError):
        return []
    return names


def rom_name(out_vpx):
    """The name B2S knows a patched table by: the PadB2SName its script sets
    (the ROM's), else its cGameName. Read from the table's script; None when
    it cannot be read."""
    try:
        import vpxfile
        script = vpxfile.VpxTable(out_vpx).script()
    except Exception:                                   # noqa: BLE001
        return None
    for rx in (r'^\s*PadB2SName\s*=\s*"([^"]+)"', r'^\s*Const\s+cGameName\s*=\s*"([^"]+)"',
               r'^\s*cGameName\s*=\s*"([^"]+)"'):
        mo = re.search(rx, script or "", re.I | re.M)
        if mo:
            return mo.group(1)
    return None
