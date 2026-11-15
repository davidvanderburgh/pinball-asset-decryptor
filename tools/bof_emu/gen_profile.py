#!/usr/bin/env python3
"""gen_profile.py - build a title profile for bofhw.py from the title's
decompiled scripts plus a small hand-written overrides file.

    gen_profile.py <decompiled dir> <overrides.json> <out.json>
    gen_profile.py --names <decompiled dir> <profile.json>   (PAD-1305: only
        the LED / servo / BICS names a Visual Pinball link reads)

<decompiled dir> is GDRE's .gd output with the res:// tree kept
(autoloads/switches.gd, autoloads/coils.gd, autoloads/game.gd).  The
overrides carry what is protocol, not table: port list, firmware versions,
node boards, BICS dialect.  Everything the switch panel needs (number, name,
label, opto flag, tags, test-screen position) and the ball model's anchors
(trough, shooter lane, eject/launch drivers, coin door) come from the tables,
so a new title needs only its overrides written.

Dev-time only: the app never runs GDRE; it ships the generated JSON.
"""
import json
import re
import sys

CONST_RE = re.compile(r"^const\s+([A-Z0-9_]+)\s*(?::?=)\s*(\d+)", re.M)
SW_ITEM_RE = re.compile(r"items\[([A-Z0-9_]+)\]\s*=\s*\{(.*?)\"tags\"\s*=\s*\[(.*?)\]\s*\}",
                        re.S)
COIL_ITEM_RE = re.compile(r"items\[([A-Z0-9_]+)\]\s*=\s*\{(.*?)\n\s*\"tags\"\s*:\s*\[(.*?)\]\s*\}",
                          re.S)


def field(body, key, sep):
    m = re.search(r'"%s"\s*%s\s*("([^"]*)"|[^,\n]+)' % (key, re.escape(sep)), body)
    if not m:
        return None
    return m.group(2) if m.group(2) is not None else m.group(1).strip()


def parse(path, item_re, sep):
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    # The scripts open with a doc string whose worked example is itself an
    # items[...] = {...} block; drop string-literal lines so it can't match.
    src = re.sub(r'^\s*"\\n.*"\s*$', "", src, flags=re.M)
    consts = {k: int(v) for k, v in CONST_RE.findall(src)}
    items = []
    for name, body, tags in item_re.findall(src):
        if name not in consts:
            continue
        item = {"n": consts[name], "const": name,
                "tags": re.findall(r'"([^"]+)"', tags)}
        label = field(body, "display_name", sep)
        if label:
            item["label"] = label
        for key, out in (("reversed", "opto"),):
            v = field(body, key, sep)
            if v is not None:
                item[out] = v == "true"
        for key, out in (("x_position", "x"), ("y_position", "y")):
            v = field(body, key, sep)
            if v is not None and re.fullmatch(r"-?\d+", v):
                item[out] = int(v)
        items.append(item)
    items.sort(key=lambda i: i["n"])
    return consts, items


def led_board(board):
    """A board id as one LED lives on it: "840" (an alias's board, breakout
    0 named explicitly) is "84", where the alias's members are listed."""
    board = board.lower()
    return board[:2] if len(board) == 3 and board.endswith("0") else board


def _items(path):
    """[(NAME, body)] of every `items[NAME] = {...}` in a script."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return []
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(r"items\[([A-Z0-9_]+)\]\s*=\s*\{", src)]
    out = []
    for i, (at, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(src)
        out.append((name, src[at:end]))
    return out


def _str(body, key):
    m = re.search(r'"%s"\s*[:=]\s*"([^"]*)"' % key, body)
    return m.group(1) if m else None


def _num(body, key):
    m = re.search(r'"%s"\s*[:=]\s*(-?\d+)' % key, body)
    return int(m.group(1)) if m else None


def vpx_names(src_dir):
    """What a Visual Pinball link calls the outputs (PAD-1305), from the
    title's own tables: every LED by its leds.gd name ("<board>:<index>",
    aliases left out: bofhw expands them onto their members), the boards
    that carry LEDs in order (an LED's slot in the kit's block is its board's
    place * 128 + index), every expansion-bus servo, and the BICS board's
    magnets / coils (by channel) and flashers (by channel, param_1)."""
    leds, boards = {}, []
    for name, body in _items(src_dir + "/autoloads/leds.gd"):
        board, dec = _str(body, "board"), _num(body, "dec")
        if board is None or dec is None or name.startswith("ALIAS_") or name == "PLACEBO":
            continue
        board = led_board(board)
        leds.setdefault("%s:%d" % (board, dec), name)
        if board not in boards:
            boards.append(board)
    order = {b: i for i, b in enumerate(("48", "b4", "84", "841", "86", "861"))}
    boards.sort(key=lambda b: (order.get(b, len(order)), b))
    servos = {}
    for name, body in _items(src_dir + "/autoloads/servos.gd"):
        board, dec = _str(body, "board"), _num(body, "dec")
        if board is not None and dec is not None:
            servos["%s:%d" % (board.lower(), dec)] = name
    outputs, flashers = {}, {}
    for name, body in _items(src_dir + "/autoloads/coils.gd"):
        tags = re.search(r'"tags"\s*[:=]\s*\[(.*?)\]', body, re.S)
        tags = re.findall(r'"([^"]+)"', tags.group(1)) if tags else []
        if "bics_flasher" in tags and _num(body, "param_1") is not None:
            flashers[str(_num(body, "param_1"))] = name
        elif ("bics_magnet" in tags or "bics_coil" in tags) and _str(body, "driver_id"):
            outputs[_str(body, "driver_id")] = name
    return {"leds": dict(sorted(leds.items(), key=lambda kv: (boards.index(kv[0].split(":")[0]),
                                                             int(kv[0].split(":")[1])))),
            "led_boards": boards, "servos": servos,
            "bics_outputs": outputs, "bics_flashers": flashers}


def names_main(src_dir, profile_path):
    """--names: put vpx_names into an existing profile, nothing else."""
    with open(profile_path) as f:
        prof = json.load(f)
    names = vpx_names(src_dir)
    prof.update(names)
    with open(profile_path, "w", newline="\n") as f:
        json.dump(prof, f, indent=1)
        f.write("\n")
    print("%s: %d LEDs on %s, %d servos, %d BICS outputs, %d BICS flashers" % (
        profile_path, len(names["leds"]), "/".join(names["led_boards"]), len(names["servos"]),
        len(names["bics_outputs"]), len(names["bics_flashers"])))


def main():
    if sys.argv[1:2] == ["--names"]:
        return names_main(*sys.argv[2:4])
    src_dir, overrides_path, out_path = sys.argv[1:4]
    sw_consts, switches = parse(src_dir + "/autoloads/switches.gd", SW_ITEM_RE, "=")
    coil_consts, coils = parse(src_dir + "/autoloads/coils.gd", COIL_ITEM_RE, ":")
    with open(src_dir + "/autoloads/game.gd", encoding="utf-8") as f:
        m = re.search(r"num_balls_total\s*=\s*(\d+)", f.read())
    balls = int(m.group(1)) if m else None
    with open(overrides_path) as f:
        prof = json.load(f)

    def sw(name):
        return sw_consts.get(name)

    trough = sorted(n for k, n in sw_consts.items()
                    if re.fullmatch(r"TROUGH\d+", k))
    prof.setdefault("balls", balls or len(trough))
    anchors = {
        "trough_switches": trough,
        "shooter_switch": sw("SHOOTER_LANE"),
        "coin_door_switch": sw("INTERLOCK"),
        "trough_eject_driver": coil_consts.get("TROUGH_EJECT"),
        "launch_driver": coil_consts.get("AUTOPLUNGER"),
    }
    for k, v in anchors.items():
        prof.setdefault(k, v)
    # Closed coin door (INTERLOCK active = high power on) and a full trough:
    # exactly the title's ball count - a trough that reads one ball too many
    # is "not full" to the game, and Start is refused (Labyrinth has 5 balls
    # in 6 positions).
    prof.setdefault("active_at_boot",
                    [n for n in [anchors["coin_door_switch"]] if n is not None]
                    + trough[:prof["balls"]])
    keys = {}
    for key, const in (("start", "START"), ("coin", "COIN_1"),
                       ("enter", "ENTER"), ("exit", "EXIT"), ("up", "UP"),
                       ("down", "DOWN"), ("flipper_left", "FLIPPER_BUTTON_LL"),
                       ("flipper_right", "FLIPPER_BUTTON_LR"),
                       ("flipper_upper_left", "FLIPPER_BUTTON_UL"),
                       ("flipper_upper_right", "FLIPPER_BUTTON_UR"),
                       ("action", "ACTION_BUTTON"), ("launch", "LAUNCH"),
                       ("tilt", "TILT"), ("coin_door", "INTERLOCK")):
        if sw(const) is not None:
            keys[key] = sw(const)
    prof.setdefault("keys", keys)
    prof["switches"] = switches
    prof["coils"] = [{k: c[k] for k in ("n", "const", "label") if k in c}
                     for c in coils]
    prof.update(vpx_names(src_dir))
    with open(out_path, "w", newline="\n") as f:
        json.dump(prof, f, indent=1)
        f.write("\n")
    print("%s: %d switches, %d coils, %s balls, trough %s, shooter %s, eject %s" % (
        out_path, len(switches), len(coils), prof["balls"], trough, anchors["shooter_switch"],
        anchors["trough_eject_driver"]))


if __name__ == "__main__":
    main()
