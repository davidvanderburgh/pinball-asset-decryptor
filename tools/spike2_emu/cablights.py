"""cablights.py - the cabinet's own lighting, for the virtual playfield (PAD-500).

"Show the Topper, Expression Lighting, and Speaker Lighting nodes to the left
of the playfield artwork" (peanuts, 2026-10-10). Three kinds of light that are
not inserts and that no playfield picture has a place for:

  TOPPER       the topper's lamps and strips. A title can have two: its own
               topper (Godzilla's tanks and heat ray on node 12, "Topper") and
               the universal one (ETOPPER dome and front LEDs, node 14 "Topper
               Lights", on Godzilla, Deadpool, Star Wars and Elvira), shown as
               the accessory Stern sells it as, "Topper Expression Light".
  EXPRESSION   the cabinet's expressive-lighting blades, "EXPRESSIVE LIGHTING
               L/R n": 96 RGB pixels a side on node 2, "Cabinet Lights" (John
               Wick, King Kong, Led Zeppelin, Metallica, Rush). John Wick, King
               Kong and Metallica even position them on the playfield picture,
               down its two edges, where they were drawn as inserts that never
               lit - their boards were never placed.
  SPEAKER      the backbox speaker lights, "SPEAKER n": 23 RGB pixels on node
               7, "Backbox Speaker Lights" (Foo Fighters, Led Zeppelin, Rush,
               Venom, Elvira).
  BACKPANEL    the lamps on the playfield's back panel, which the game draws on
               a picture of its own named `backpanel` (PAD-705): flashers,
               Avengers' glove gems, Jurassic Park's MAP letters, the BACKPANEL
               GI. Sixteen builds have them. They are on the playfield's own
               boards, so the measured map places them; drawn in the panel's
               shape, like a topper on its own drawing.
  UV           the UV lighting kit's own outputs, "UV CONTROL 1 (OPTIONAL)"
               and 2 on Stranger Things: two lamp channels on a playfield
               board, with no place on any picture (PAD-551, peanuts:
               "missing UV Lighting Kit"). A lamp merely NAMED for UV on the
               playfield (Metallica's "HAMMER UV") is an insert, not this.

WHICH BOARD A ROW IS ON is the whole difficulty, and it is why these were never
drawn. The device table gives each row a GROUP; coilmap.group_node() maps the
groups it can MEASURE (switch names, connectors), and none of these groups is
one of them. nbdir.board_groups() supplies the rest: a group is its board's
place in the title's own node directory (212 of 223 measured groups agree on
the 58 binaries here). This module takes the measured map first, the place
second, and accepts the place only when the board's OWN NAME or TYPE agrees
with the row: a topper row must land on a board the title names a topper, a
blade or speaker row on a ws2812 strip board. A row nothing places is left out,
never guessed - "a wrong address is worse than a missing one" (item 53).

Pure: no Tk, no window, no padled. playfield.py draws what this decides.
"""
import os
import re

TOPPER, EXPRESSION, SPEAKER, UV = "topper", "expression", "speaker", "uv"
BACKPANEL = "backpanel"

#: The image name a back-panel lamp carries (devicexy.BARE_IMAGES).
BACKPANEL_IMAGE = "backpanel"

#: The roles the window's "Expression lights" tick box takes out: the blades
#: and the speakers - "a toggle to disable expression lights (blades and
#: speakers)", in the request's own words.
EXPRESSION_ROLES = (EXPRESSION, SPEAKER)

#: How each role is labelled when its board has no name of its own.
LABEL = {TOPPER: "Topper", EXPRESSION: "Expression lighting",
         SPEAKER: "Speaker lighting", UV: "UV Lighting Kit",
         BACKPANEL: "Backpanel"}

#: Node 14 is the universal topper on every title, and every title names it
#: "Topper Lights" - which John Wick also calls its own topper on node 12. It
#: is the add-on Stern sells as the "Topper Expression Light" (peanuts,
#: PAD-522: "in order to avoid confusion with regular topper"), so it is
#: shown by that name and never by the game's.
EXPRESSION_TOPPER_NODE = 14
EXPRESSION_TOPPER = "Topper Expression Light"

#: The column's order, top to bottom: the topper sits above the backbox, the
#: speakers in it, the back panel below them, the blades down the cabinet.
ORDER = {TOPPER: 0, SPEAKER: 1, BACKPANEL: 2, EXPRESSION: 3, UV: 4}

_SPEAKER = re.compile(r"^SPEAKER\b")
#: "UV CONTROL 1 (OPTIONAL)": the kit's outputs start with UV; an insert that
#: ends with it (Metallica's "LEFT SLING UV") is on the playfield picture
_UV = re.compile(r"^UV\b")
#: one channel of an RGB pixel, however the title spells it: "SPEAKER 1-G",
#: Venom's "TOPPER BIKE - R", Guardians' "RIGHT SCOOP RECTANGLE-RED"
_CHANNEL = re.compile(r"^(.*?)\s*-\s*(R|G|B|RED|GRN|GREEN|BLU|BLUE)$", re.I)
#: Rush's "LEFT POP BUMPER R": a space, no dash (see split_channel)
_SPACED = re.compile(r"^(.*\S)\s+([RGB])$")
#: "EXPRESSIVE LIGHTING L 12" -> side L, pixel 12
_SIDE = re.compile(r"\b([LR])\s+\d+\s*$")


def role(row):
    """TOPPER, EXPRESSION, SPEAKER, UV, BACKPANEL or None for one row."""
    if row.get("kind") != "led":
        return None
    name = (row.get("name") or "").upper()
    if name.startswith("EXPRESSIVE LIGHTING"):
        return EXPRESSION
    if _SPEAKER.match(name):
        return SPEAKER
    if _UV.match(name):
        return UV
    if "TOPPER" in name or "topper" in (row.get("image") or "").lower():
        return TOPPER
    if row.get("image") == BACKPANEL_IMAGE:
        return BACKPANEL
    return None


def role_of(row, group_node, board_map):
    """role(), or TOPPER for an LED on a board the title itself names a topper.

    King Kong's topper says nothing of itself in its names - "MARQUEE GI1-G" to
    "MARQUEE RIGHT BACK4-R", 76 pixels on no picture - but its group's board is
    node 12, "Topper", and a traced game drove all 228 of its channels. The
    board is found the way resolve() finds one: the measured map, else the
    group's place in the directory."""
    which = role(row)
    if which is not None or row.get("kind") != "led":
        return which
    node = (group_node or {}).get(row.get("group"))
    if node is None:
        node = board_for_group(row.get("group"), board_map or {})
    b = (board_map or {}).get(node) if node is not None else None
    return TOPPER if b and "TOPPER" in b["name"].upper() else None


def split_channel(name, spaced=()):
    """('TOPPER BIKE', 'R') for 'TOPPER BIKE - R'; (name, 'W') otherwise.

    PAD-702: Rush's "LEFT POP BUMPER R" (a space, no dash) splits too, but
    only for a stem in `spaced` (spaced_stems()): Foo Fighters' white "MOD B"
    is one lamp."""
    m = _CHANNEL.match(name or "")
    if not m:
        m = _SPACED.match(name or "")
        if m and m.group(1) in spaced:
            return m.group(1), m.group(2)
        return name, "W"
    return m.group(1).rstrip(), m.group(2)[0].upper()


def spaced_stems(names):
    """The stems a table spells "STEM R" with two or more of R, G, B - an RGB
    light, where a lone "TARGET B" is not."""
    seen = {}
    for name in names:
        m = _SPACED.match(name or "")
        if m:
            seen.setdefault(m.group(1), set()).add(m.group(2))
    return frozenset(s for s, chans in seen.items() if len(chans) > 1)


def repeated_channel(channels, chan, index, last):
    """The channel a row that repeats `chan` in its fixture really is, or None.

    PAD-702: Venom's "TOPPER RIGHT SPOTLIGHT 2" is G, R, G at 48-50 and
    Mandalorian's "TOPPER 25" the same at 72-74 - a typo for B in Stern's
    table. A third channel right after the other two that names one of them
    again is the one missing; anything else is two lamps sharing a name."""
    have = set(channels)
    if (chan in have and len(have) == 2 and have < set("RGB")
            and index == last + 1):
        return (set("RGB") - have).pop()
    return None


def boards(nodedir_path):
    """{node: {type, group, name}} from a node_ident.txt, or {}.

    `group=` and `name=` are nbdir v2's (PAD-500); a v1 table answers with
    types only, and every lookup that needs a place then finds none. The
    skipped lines carry a place too (the CPU is one), so they are read as well.
    """
    out = {}
    try:
        with open(nodedir_path, encoding="ascii", errors="replace") as f:
            lines = f.readlines()
    except (OSError, TypeError):
        return {}
    for line in lines:
        body = line[len("# skipped "):] if line.startswith("# skipped ") else line
        if not body.startswith("node="):
            continue
        head, _, name = body.partition(" name=")
        kv = dict(t.split("=", 1) for t in head.split() if "=" in t)
        try:
            node = int(kv["node"])
        except (KeyError, ValueError):
            continue
        try:
            group = int(kv["group"]) if "group" in kv else None
        except ValueError:
            group = None
        out[node] = {"type": kv.get("type") or "", "group": group,
                     "name": name.strip()}
    return out


def board_for_group(group, board_map):
    """The node whose directory place is `group`, or None."""
    for node, b in board_map.items():
        if b.get("group") == group:
            return node
    return None


#: Why a group found no board when the directory could not have said
#: (PAD-532). A directory read before PAD-500 (nbdir v1) has no `group=` on any
#: line, so no group can match - every cabinet light on godzilla_le read "group
#: 3 has no board", when the run that rebuilds it places all three boards.
#: nbdir.py refuses to reuse a v1 table, so the next start of the game is the
#: whole cure; the box should say that rather than blame the title.
NO_DIRECTORY = "this title's node directory has not been read yet; start the game to read it"
OLD_DIRECTORY = ("this title's node directory was read before boards had places;"
                 " start the game again to re-read it")


def _unplaced(group, board_map):
    if not board_map:
        return NO_DIRECTORY
    if all(b.get("group") is None for b in board_map.values()):
        return OLD_DIRECTORY
    return "group %s has no board in the title's node directory" % group


def resolve(which, group, group_node, board_map):
    """(node, how) for a row of role `which` in device-table `group`.

    The measured map first (coilmap.group_node - it names Bond's topper,
    group 10 on node 12, from its connectors), then the board at that place in
    the directory, which must CONFIRM the role: a topper row needs a board the
    title names a topper, a blade or speaker row a ws2812 strip board. Else
    (None, why)."""
    node = (group_node or {}).get(group)
    if node is not None:
        return node, "measured"
    node = board_for_group(group, board_map or {})
    if node is None:
        return None, _unplaced(group, board_map or {})
    b = board_map[node]
    if which == TOPPER:
        ok = "TOPPER" in b["name"].upper()
    elif which in (UV, BACKPANEL):
        # the kit's outputs, and the back panel's lamps, are lamp channels on
        # a playfield board, which only the measured map can name; a place
        # alone proves nothing about them
        return None, "group %s is not one the title's tables place" % group
    else:
        ok = "ws2812" in b["type"]
    if not ok:
        return None, ("group %s is node %d (%s, %s), which is not a %s board"
                      % (group, node, b["type"], b["name"] or "unnamed",
                         "topper" if which == TOPPER else "strip"))
    return node, "directory"


def where(S):
    """"node 9", or "nodes 8, 9" for a section on more than one board."""
    ns = S.get("nodes") or [S["node"]]
    return ("node %d" % ns[0] if len(ns) == 1
            else "nodes " + ", ".join(str(n) for n in ns))


def _order(px):
    """A pixel's place along its chain: the lowest channel index it uses."""
    return min(ch for _n, ch in px["channels"].values())


def _bars(pixels):
    """The blades as [[pixel index, ...] per side, BOTTOM FIRST], left side
    first.

    Rush names its sides ("EXPRESSIVE LIGHTING L 1" .. "R 96"); King Kong
    numbers 1 to 96 with no side and puts them on the playfield picture
    instead - 1 to 48 down the left edge at x=7, 49 to 96 at x=305, and pixel
    1 at the BOTTOM (y=539, 48 at y=92). So: the name's side, else the
    picture's, else one bar; and each bar runs bottom to top in chain order,
    which is the order the picture shows wherever there is one.
    """
    sides = {}
    named = all(_SIDE.search(P["name"]) for P in pixels)
    xs = sorted(P["x"] for P in pixels)
    mid = (xs[0] + xs[-1]) / 2.0 if xs else 0.0
    placed = bool(xs) and xs[-1] - xs[0] > 20
    for k, P in enumerate(pixels):
        if named:
            side = _SIDE.search(P["name"]).group(1)
        elif placed:
            side = "L" if P["x"] < mid else "R"
        else:
            side = ""
        sides.setdefault(side, []).append(k)
    return [sides[s] for s in sorted(sides)]


def sections(dev_rows, group_node, board_map, expression=True,
             gone_nodes=()):
    """(sections, left_out) - the column, top to bottom.

    A section is one role on one board: {key, role, label, node, board,
    pixels, bars, positioned}. `pixels` are RGB pixels (or single lamps)
    joined by name stem, each {name, channels: {chan: (node, channel)}, x, y};
    `bars` (the blades) is [[pixel index, ...] per side, top to bottom] and
    `positioned` says the pixels' x, y are a picture's own (a topper drawing)
    rather than nothing. `left_out` is [(role, rows, why)] for rows no board
    could be found for - counted, so the window can say so, never drawn.

    expression=False leaves the blades and the speakers out (the window's
    tick box); `gone_nodes` are boards this cabinet does not have at all.
    """
    by_key, left = {}, {}
    for r in dev_rows or []:
        which = role_of(r, group_node, board_map)
        if which is None or (not expression and which in EXPRESSION_ROLES):
            continue
        node, how = resolve(which, r["group"], group_node, board_map)
        if node is None:
            n, _ = left.get((which, how), (0, None))
            left[(which, how)] = (n + 1, how)
            continue
        if node in gone_nodes:
            continue
        # The back panel is ONE picture whichever boards drive it: Avengers
        # puts its glove gems on node 8 and its flashers on node 9, and two
        # sections would split one drawing in two. `node` is its lowest board.
        key = which if which == BACKPANEL else "%s:%d" % (which, node)
        S = by_key.get(key)
        if S is None:
            b = (board_map or {}).get(node) or {}
            S = by_key[key] = {
                "key": key, "role": which, "node": node, "nodes": set(),
                "board": b.get("name") or "",
                "label": LABEL[which], "pixels": {}, "rows": []}
        if node not in S["nodes"] and S["nodes"]:
            S["board"] = ""             # more than one board: none names it
        S["nodes"].add(node)
        S["node"] = min(S["nodes"])
        S["rows"].append((r, node))
    out = []
    spaced = spaced_stems(r["name"] for r in dev_rows or []
                          if r.get("kind") == "led")
    for S in by_key.values():
        pix = S.pop("pixels")
        for r, node in S.pop("rows"):
            stem, chan = split_channel(r["name"], spaced)
            P = pix.get(stem)
            if P is not None and chan in P["channels"]:
                chan = repeated_channel(
                    P["channels"], chan, r["index"],
                    max(i for _n, i in P["channels"].values())) or chan
            if P is None or chan in P["channels"]:
                if P is not None:
                    stem = "%s (%d)" % (stem, r["index"])
                P = pix[stem] = {"name": stem, "channels": {}, "xs": [], "ys": []}
            P["channels"][chan] = (node, r["index"])
            P["xs"].append(r["x"])
            P["ys"].append(r["y"])
            # A lamp with no place on its picture (devicexy._unplaced: the
            # BACKPANEL GI) reads 0, 0, which is not a place.
            P.setdefault("placed", False)
            P["placed"] |= any(r.get(k) for k in ("x", "y", "w", "h"))
        pixels = sorted(pix.values(), key=_order)
        for P in pixels:
            xs, ys = P.pop("xs"), P.pop("ys")
            P["x"] = sum(xs) / float(len(xs))
            P["y"] = sum(ys) / float(len(ys))
        S["pixels"] = pixels
        S["nodes"] = sorted(S["nodes"])
        # A topper or a back panel drawn on its own picture keeps its shape;
        # anything else is a strip, laid out by the page in chain order. Only
        # PLACED pixels say what the shape is; the page puts the rest of a
        # positioned section in a row under it.
        placed = [P for P in pixels if P["placed"]]
        S["positioned"] = (S["role"] in (TOPPER, BACKPANEL) and len(placed) > 1
                           and len({(round(P["x"]), round(P["y"]))
                                    for P in placed}) > 1)
        S["bars"] = _bars(pixels) if S["role"] == EXPRESSION else None
        out.append(S)
    out.sort(key=lambda S: (ORDER[S["role"]], S["node"]))
    # two toppers on one title are told apart by their boards' own names
    tops = [S for S in out if S["role"] == TOPPER]
    if len(tops) > 1:
        for S in tops:
            S["label"] = S["board"] or "Topper (node %d)" % S["node"]
    for S in tops:
        if S["node"] == EXPRESSION_TOPPER_NODE:
            S["label"], S["board"] = EXPRESSION_TOPPER, ""
    left_out = [(which, n, how) for (which, _h), (n, how) in sorted(left.items())]
    return out, left_out


def nodedir_for(table_path):
    """node_ident.txt beside a title's device_xy.txt (coilmap's rule: the
    path names the title, nothing here looks one up)."""
    return os.path.join(os.path.dirname(table_path or ""), "node_ident.txt")
