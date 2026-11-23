"""The JJP screen layout editor's model (PAD-1515).

JJP games draw their screens in code, so there is no scene file to open; but everything the mode
runtime (``tools/jjp_emu/jjpmodes.c``) draws over the game is ours, placed by ``.mode`` / ``title.cfg``
keys.  The Modes tab's layout editor edits those keys by dragging.  This module is the model behind
it: for one screen (a mode's screen, its progress board, the attract game type menu) the list of
elements with their boxes - set by a key, or the place the runtime draws them at when the key is
empty - and the key value a dragged box writes.

Boxes are ``[x, y, w, h]`` in percent of their parent: the screen, or the box they sit in (a mode's
title, total and timer sit in its panel; the menu's heading, lines and hint in the menu's box), so
moving a panel carries its text along.  The default places are the runtime's own numbers (draw_screen,
draw_menu); the tests hold the two together.
"""
import re

#: the JJP main screen (every title: tools/jjp_emu/display.sh JJP_MAIN_MODE); a frame of the game's
#: own screen, when the editor has one, gives the real size
SCREEN = (1360, 768)
#: the panel word's places (draw_screen: x 16-84 %, 27 % tall)
PANEL_PLACES = {"middle": [16.0, 36.0, 68.0, 27.0], "bottom": [16.0, 70.0, 68.0, 27.0],
                "top": [16.0, 3.0, 68.0, 27.0]}
#: the built-in font's text is 4 times its 8 px: 32 px of a 768 px screen
_TEXT_H = 32.0 / 768
#: draw_screen's default places, fractions of the screen: the built-in font's top for the title,
#: total and timer, and the timer's centre left of the panel's right edge
_TEXT_TOP = {"title_at": 0.02, "value_at": 0.12, "timer_at": 0.07}
_TIMER_IN, _TIMER_W = 0.05, 0.08
#: draw_menu's numbers, fractions of the screen's height (the menu box scales them all alike)
_MENU_BASE, _MENU_ROW = 0.24, 0.075
_MENU_HEAD_MID, _MENU_HEAD_H = 0.055, 40.0 / 768      # the built-in font 5 times its 8 px
_MENU_LINES_TOP, _MENU_LINES_IN = 0.118, 5.4
_MENU_HINT_UP, _MENU_HINT_H = 0.065, 20.0 / 768        # 2.5 times its 8 px

MODE_KEYS = ("panel_at", "title_at", "value_at", "timer_at", "picture_at", "video_at")
MENU_KEYS = ("game_type_at", "game_type_title_at", "game_type_lines_at", "game_type_hint_at",
             "game_type_picture_at")
#: every key the editor writes (progress lines' own boxes go in their progress line)
BOX_KEYS = MODE_KEYS + MENU_KEYS + ("progress_at",)
#: mode keys title.cfg may set for every mode (the title settings' mode screen)
TITLE_MODE_KEYS = ("panel_at", "title_at", "value_at", "timer_at")

_NUM = re.compile(r"^-?[0-9.]+%?$")


def parse_box(v):
    """``"x y w h"`` -> [x, y, w, h], or None (empty, or not a box the runtime takes)."""
    words = re.split(r"[ ,\t]+", (v or "").strip())
    if len(words) != 4 or not all(_NUM.match(w) for w in words):
        return None
    try:
        b = [float(w.rstrip("%")) for w in words]
    except ValueError:
        return None
    return b if b[2] > 0 and b[3] > 0 else None


def box_text(b):
    """[x, y, w, h] -> ``"x y w h"`` at two decimals, no trailing zeros."""
    out = []
    for n in b:
        t = ("%.2f" % round(float(n), 2)).rstrip("0").rstrip(".")
        out.append("0" if t in ("-0", "") else t)
    return " ".join(out)


def clamp_box(b):
    """A dragged box kept sane: at least 0.5 % a side, and not more than 400 % (text may sit outside
    its panel, a picture may hang off the screen's edge)."""
    x, y, w, h = [float(n) for n in b]
    w, h = min(max(w, 0.5), 400.0), min(max(h, 0.5), 400.0)
    return [min(max(x, -300.0), 300.0), min(max(y, -300.0), 300.0), w, h]


def progress_lines(value):
    """A mode's ``progress`` value -> [{mode, lit, unlit, box}] (box None = the shared progress_at)."""
    out = []
    for line in (value or "").split("\n"):
        w = line.split()
        if not w:
            continue
        box = None
        if len(w) >= 6 and all(_NUM.match(t) for t in w[-4:]):
            box, w = parse_box(" ".join(w[-4:])), w[:-4]
        out.append({"mode": w[0], "lit": w[1] if len(w) > 1 else "", "unlit": w[2] if len(w) > 2 else "",
                    "box": box})
    return out


def progress_with_box(value, index, box):
    """The ``progress`` value with line ``index``'s own box set to ``box`` (None takes it away)."""
    lines = [ln for ln in (value or "").split("\n") if ln.split()]
    p = progress_lines("\n".join(lines))
    if not 0 <= index < len(p):
        raise ValueError("no progress line %d" % (index + 1))
    ln = p[index]
    words = [ln["mode"], ln["lit"]] + ([ln["unlit"]] if ln["unlit"] else [])
    if box is not None:
        words.append(box_text(box))
    lines[index] = " ".join(words)
    return "\n".join(lines)


def _rgba(v, dflt):
    v = (v or dflt or "ffffff").strip().lstrip("#")
    return "#" + (v + "ff" if len(v) == 6 else v)


def _get(form, title, key, scope):
    """(value, where): the mode's own value, else title.cfg's (inherited), for a mode screen."""
    if (form.get(key) or "").strip():
        return form[key].strip(), "own"
    if scope == "mode" and key in TITLE_MODE_KEYS + ("panel",) and (title.get(key) or "").strip():
        return title[key].strip(), "title"
    return "", ""


def text_defaults(panel):
    """The title, total and timer's default boxes (% of the panel) for a panel box (% of the screen):
    where draw_screen puts them in the built-in font."""
    pw, ph = panel[2] / 100.0, panel[3] / 100.0
    out = {}
    for k, top in _TEXT_TOP.items():
        y, h = top / ph * 100, _TEXT_H / ph * 100
        if k == "timer_at":
            w = _TIMER_W / pw * 100
            x = (pw - _TIMER_IN) / pw * 100 - w / 2
        else:
            x, w = 0.0, 100.0
        out[k] = [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]
    return out


def mode_screen(form, title, folder="", scope="mode", defaults=None):
    """The mode screen's elements: its video and picture (screen), its panel (screen) and the
    panel's title, total and timer.  ``scope`` "title" lays out title.cfg's defaults for every mode."""
    defaults = defaults or {}
    els = []
    for key, fkey, kind, label in (("video_at", "video", "video", "Video"), ("picture_at", "picture", "picture", "Picture")):
        f = (form.get(fkey) or "").strip()
        if scope != "mode" or not f:
            continue
        v, where = _get(form, title, key, scope)
        b = parse_box(v)
        els.append({"key": key, "kind": kind, "label": label, "parent": "", "set": bool(b), "where": where,
                    "box": b or [0.0, 0.0, 100.0, 100.0], "file": _join(folder, f), "name": f})
    word, wword = _get(form, title, "panel", scope)
    word = word or "middle"
    v, where = _get(form, title, "panel_at", scope)
    pb = parse_box(v)
    panel = pb or PANEL_PLACES.get(word, PANEL_PLACES["middle"])
    off = word == "none"
    els.append({"key": "panel_at", "kind": "panel", "label": "Panel", "parent": "", "set": bool(pb), "where": where,
                "box": list(panel), "color": _rgba(_get(form, title, "panel_color", scope)[0] or title.get("panel_color"),
                                                   defaults.get("panel_color", "000000b0")),
                "off": off, "word": word, "word_where": wword})
    dflt = text_defaults(panel)
    secs = (form.get("seconds") or "").strip()
    sample = {"title_at": (form.get("title") or form.get("name") or "MODE TITLE").strip()
              if scope == "mode" else "MODE TITLE",
              "value_at": "12,345,678", "timer_at": secs if secs and secs != "0" else "20"}
    for key, ck, fk, label in (("title_at", "title_color", "font_title", "Title"),
                               ("value_at", "value_color", "font_value", "Total"),
                               ("timer_at", "timer_color", "font_timer", "Timer")):
        v, where = _get(form, title, key, scope)
        b = parse_box(v)
        els.append({"key": key, "kind": "text", "label": label, "parent": "panel_at", "set": bool(b), "where": where,
                    "box": b or dflt[key], "text": sample[key], "off": off,
                    "color": _rgba(form.get(ck) or title.get(ck), defaults.get(ck)),
                    "font": (form.get(fk) or title.get(fk) or "").strip()})
    return {"screen": "mode", "scope": scope, "elements": els, "words": ["middle", "bottom", "top", "none"]}


def progress_board(form, folder=""):
    """A wizard mode's progress board: each progress line's pane in its own box or the shared one."""
    shared = parse_box(form.get("progress_at")) or [0.0, 0.0, 100.0, 100.0]
    lines = progress_lines(form.get("progress"))
    els = []
    if any(ln["box"] is None for ln in lines):
        els.append({"key": "progress_at", "kind": "shared", "label": "Shared box (every pane without its own)",
                    "parent": "", "set": bool(parse_box(form.get("progress_at"))), "where": "own", "box": shared})
    for i, ln in enumerate(lines):
        els.append({"key": "progress#%d" % i, "kind": "pane", "label": ln["mode"], "parent": "", "set": bool(ln["box"]),
                    "where": "own" if ln["box"] else "", "box": ln["box"] or list(shared),
                    "file": _join(folder, ln["lit"]), "unlit": _join(folder, ln["unlit"]) if ln["unlit"] else "",
                    "name": ln["lit"]})
    return {"screen": "progress", "scope": "mode", "elements": els}


def menu_defaults(n):
    """The menu's default box (% of the screen) and its heading, lines and hint (% of the menu box) for
    ``n`` lines (the normal game's and one per game type): draw_menu's places."""
    ph = _MENU_BASE + n * _MENU_ROW
    menu = [22.0, (1 - ph) / 2 * 100, 56.0, ph * 100]
    head = [0.0, (_MENU_HEAD_MID - _MENU_HEAD_H / 2) / ph * 100, 100.0, _MENU_HEAD_H / ph * 100]
    lines = [_MENU_LINES_IN, _MENU_LINES_TOP / ph * 100, 100 - 2 * _MENU_LINES_IN, n * _MENU_ROW / ph * 100]
    hint = [0.0, (ph - _MENU_HINT_UP - _MENU_HINT_H / 2) / ph * 100, 100.0, _MENU_HINT_H / ph * 100]
    r = lambda b: [round(t, 2) for t in b]
    return {"game_type_at": r(menu), "game_type_title_at": r(head), "game_type_lines_at": r(lines),
            "game_type_hint_at": r(hint)}


def game_menu(title, types, folder="", defaults=None):
    """The attract game type menu: its picture, its box and its heading, lines and hint.
    ``types``: the game_type lines of the folder's modes, in the order the menu lists them."""
    defaults = defaults or {}
    rows = [(title.get("game_type_normal") or defaults.get("game_type_normal") or "NORMAL GAME").strip()]
    rows += [t for t in types if t]
    d = menu_defaults(len(rows))
    els = []
    pic = (title.get("game_type_picture") or "").strip()
    if pic:
        b = parse_box(title.get("game_type_picture_at"))
        els.append({"key": "game_type_picture_at", "kind": "picture", "label": "Picture", "parent": "", "set": bool(b),
                    "where": "own" if b else "", "box": b or [0.0, 0.0, 100.0, 100.0], "file": _join(folder, pic),
                    "name": pic})
    mb = parse_box(title.get("game_type_at"))
    # its bars are 0.6 % of the screen tall, scaled as the whole menu is into a box of its own
    scale = mb[3] / 100 / (_MENU_BASE + len(rows) * _MENU_ROW) if mb else 1.0
    els.append({"key": "game_type_at", "kind": "panel", "label": "Menu", "parent": "", "set": bool(mb),
                "where": "own" if mb else "", "box": mb or d["game_type_at"], "bar_h": round(0.6 * scale, 3),
                "color": _rgba(title.get("game_type_panel_color"), defaults.get("game_type_panel_color")),
                "bar": _rgba(title.get("game_type_bar_color"), defaults.get("game_type_bar_color"))})
    hint = title.get("game_type_hint")
    hint = (defaults.get("game_type_hint", "") if hint is None or hint == "" else hint).strip()
    for key, label, text, ck, fk in (
            ("game_type_title_at", "Heading", (title.get("game_type_title") or defaults.get("game_type_title") or "GAME TYPE").strip(),
             "game_type_title_color", "game_type_font_title"),
            ("game_type_lines_at", "Lines", "", "game_type_item_color", "game_type_font_item"),
            ("game_type_hint_at", "Hint", "" if hint == "none" else hint, "game_type_hint_color", "game_type_font_hint")):
        if key == "game_type_hint_at" and not text:
            continue
        b = parse_box(title.get(key))
        el = {"key": key, "kind": "lines" if key == "game_type_lines_at" else "text", "label": label,
              "parent": "game_type_at", "set": bool(b), "where": "own" if b else "", "box": b or d[key], "text": text,
              "color": _rgba(title.get(ck), defaults.get(ck)), "font": (title.get(fk) or "").strip()}
        if key == "game_type_lines_at":
            el.update(rows=rows, pick=min(1, len(rows) - 1),
                      pick_color=_rgba(title.get("game_type_pick_color"), defaults.get("game_type_pick_color")),
                      pick_bar=_rgba(title.get("game_type_pick_bar_color"), defaults.get("game_type_pick_bar_color")))
        els.append(el)
    return {"screen": "menu", "scope": "title", "elements": els}


def _join(folder, name):
    import os
    return os.path.join(folder, name) if folder and name else ""


PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXTS = (".webm", ".mp4", ".mkv", ".mov", ".ogv", ".avi", ".m4v")
#: the game's own screens grabbed by "Show it in the game", in the title's mode folder
FRAMES_DIR = ".layout"


def backdrops(folder, extra=()):
    """What the editor can show under a layout: frames of the game's own screen (FRAMES_DIR), the
    pictures and videos in the mode folder, and files picked from anywhere (``extra``)."""
    import os
    out, seen = [], set()

    def add(path, label):
        k = os.path.normcase(os.path.abspath(path))
        if k not in seen and os.path.isfile(path):
            seen.add(k)
            out.append({"path": path, "label": label})
    fr = os.path.join(folder, FRAMES_DIR) if folder else ""
    if fr and os.path.isdir(fr):
        for f in sorted(os.listdir(fr), key=lambda f: -os.path.getmtime(os.path.join(fr, f))):
            if f.lower().endswith(PICTURE_EXTS):
                stem = os.path.splitext(f)[0]
                add(os.path.join(fr, f), ("In the game, ours drawn: " + stem[8:].replace("_", " ")) if stem.startswith("in_game_")
                    else "The game's screen: " + stem.replace("_", " "))
    if folder and os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith(PICTURE_EXTS + VIDEO_EXTS):
                add(os.path.join(folder, f), f)
    for p in extra or ():
        add(p, os.path.basename(p))
    return out


# ---------------------------------------------------------------- the game's own screen (PAD-1515)
# A census (jjpmodes.c gs_frame, asked for by "Show it in the game" or jjpdrive's census step) leaves
# <label>.png (the game's frame, nothing of ours on it) and <label>.json (every part it drew, named by
# the game's object that holds it, with its box in screen pixels) in FRAMES_DIR.  title.cfg moves them:
#   screen_move = <name> <dx> <dy> [<scale> [<ax> <ay>]]   (percent of the screen; the scale is about
#                 (ax, ay): the part's centre, written whenever it is scaled, so its pieces scale as one)
#   screen_hide = <name>
SCREEN_KEYS = ("screen_move", "screen_hide")
_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def censuses(folder):
    """The game's screens a census has been taken of: [{label, json, png}], newest first."""
    import os
    d = os.path.join(folder, FRAMES_DIR) if folder else ""
    if not d or not os.path.isdir(d):
        return []
    out = []
    for f in os.listdir(d):
        if f.endswith(".json"):
            lab = f[:-5]
            out.append({"label": lab, "json": os.path.join(d, f), "png": os.path.join(d, lab + ".png"),
                        "t": os.path.getmtime(os.path.join(d, f))})
    out.sort(key=lambda c: -c["t"])
    return [{k: c[k] for k in ("label", "json", "png")} for c in out]


def read_census(path):
    """A census file -> {label, size, parts: [{name, kind, box (px), draws, text}]} ({} unreadable)."""
    import json
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    return c if isinstance(c, dict) and isinstance(c.get("parts"), list) else {}


def screen_lines(title):
    """title.cfg's screen_move / screen_hide lines -> {name: {"dx", "dy", "scale", "hide"}}."""
    out = {}
    for key in SCREEN_KEYS:
        for line in (title.get(key) or "").split("\n"):
            w = line.split()
            if not w:
                continue
            e = out.setdefault(w[0], {"dx": 0.0, "dy": 0.0, "scale": 1.0, "hide": False, "anchor": None})
            if key == "screen_hide":
                e["hide"] = True
            else:
                try:
                    e["dx"], e["dy"] = float(w[1].rstrip("%")), float(w[2].rstrip("%"))
                    e["scale"] = float(w[3].rstrip("%")) if len(w) > 3 else 1.0
                    e["anchor"] = [float(w[4].rstrip("%")), float(w[5].rstrip("%"))] if len(w) > 5 else None
                except (IndexError, ValueError):
                    pass
    return out


def with_screen_line(title, name, move=None, hide=None):
    """title.cfg's {screen_move, screen_hide} values with ``name``'s lines changed: ``move`` (dx, dy,
    scale[, ax, ay]) or None to leave it; (0, 0, 1) takes it away; ``hide`` True / False / None (left as
    it is)."""
    if not _PART.match(name or ""):
        raise ValueError("%s is not a part's name" % name)
    out = {}
    for key in SCREEN_KEYS:
        keep = [ln for ln in (title.get(key) or "").split("\n") if ln.split() and ln.split()[0] != name]
        had = any(ln.split() and ln.split()[0] == name for ln in (title.get(key) or "").split("\n"))
        if key == "screen_move" and move is not None:
            dx, dy, sc = move[:3]
            words = [name, _n(dx), _n(dy)] + ([_n(sc, 3)] if abs(sc - 1) > 0.0005 else [])
            if len(words) > 3 and len(move) >= 5:     # scaled: about the part's centre
                words += [_n(move[3]), _n(move[4])]
            if abs(dx) > 0.004 or abs(dy) > 0.004 or len(words) > 3:
                keep.append(" ".join(words))
        if key == "screen_hide" and (hide or (hide is None and had)):
            keep.append(name)
        out[key] = "\n".join(keep)
    return out


def _n(v, places=2):
    t = ("%.*f" % (places, round(float(v), places))).rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t


def _part_boxes(census):
    """{name: its biggest box (px)} over a census's parts (a font drawn in several places: each)."""
    best = {}
    for p in census.get("parts", []):
        b = p.get("box") or [0, 0, 0, 0]
        n = p.get("name", "")
        if n not in best or b[2] * b[3] > best[n][2] * best[n][3]:
            best[n] = b
    return best


def move_for(census, name, box):
    """A part dragged to ``box`` (% of the screen) -> its move (dx, dy, scale) against where the
    game draws it (the census's box): the centre's shift in percent of the screen, the width's ratio."""
    W, H = (census.get("size") or SCREEN)[:2]
    o = _part_boxes(census).get(name)
    if not o:
        raise ValueError("%s is not drawn on that screen" % name)
    ox, oy, ow, oh = o[0] * 100.0 / W, o[1] * 100.0 / H, o[2] * 100.0 / W, o[3] * 100.0 / H
    sc = box[2] / ow if ow > 0 else 1.0
    dx = (box[0] + box[2] / 2) - (ox + ow / 2)
    dy = (box[1] + box[3] / 2) - (oy + oh / 2)
    return round(dx, 2), round(dy, 2), round(sc, 3), round(ox + ow / 2, 2), round(oy + oh / 2, 2)


def game_screen(folder, title, label=""):
    """The game's own screen, as the layout editor lays it out: the census ``label`` (else the newest)
    with each part's box where the game draws it (``orig``) and where title.cfg moves it (``box``)."""
    cs = censuses(folder)
    if not cs:
        return {"screen": "game", "scope": "title", "elements": [], "censuses": [], "label": ""}
    c = next((c for c in cs if c["label"] == label), cs[0])
    census = read_census(c["json"])
    W, H = (census.get("size") or SCREEN)[:2]
    moves = screen_lines(title)
    els, seen = [], {}
    for p in census.get("parts", []):
        n = p.get("name", "")
        b = p.get("box") or [0, 0, 0, 0]
        if b[2] < 2 or b[3] < 2 or b[2] * b[3] > W * H * 0.97:     # a speck, or the whole screen (its backdrop)
            continue
        named = p.get("kind") != "unnamed" and bool(_PART.match(n))
        i = seen[n] = seen.get(n, -1) + 1
        orig = [b[0] * 100.0 / W, b[1] * 100.0 / H, b[2] * 100.0 / W, b[3] * 100.0 / H]
        mv = moves.get(n) if named else None
        box = list(orig)
        if mv:
            sc = mv["scale"]
            cx, cy = orig[0] + orig[2] / 2 + mv["dx"], orig[1] + orig[3] / 2 + mv["dy"]
            box = [cx - orig[2] * sc / 2, cy - orig[3] * sc / 2, orig[2] * sc, orig[3] * sc]
        label_ = n + ((' "%s"' % p["text"]) if p.get("text") else "")
        # its pieces: each draw's own box, in percent of the part's box (the editor moves them, not what is between)
        pieces = []
        for r in (p.get("rects") or [])[:24]:
            if b[2] > 0 and b[3] > 0 and r[2] > 0 and r[3] > 0:
                pieces.append([round((r[0] - b[0]) * 100.0 / b[2], 3), round((r[1] - b[1]) * 100.0 / b[3], 3),
                               round(r[2] * 100.0 / b[2], 3), round(r[3] * 100.0 / b[3], 3)])
        els.append({"key": "screen#%s#%s#%d" % (c["label"], n, i), "kind": "part", "part": p.get("kind", ""),
                    "pieces": pieces,
                    "name": n, "label": label_, "parent": "", "set": bool(mv), "where": "own" if mv else "",
                    "box": [round(t, 3) for t in box], "orig": [round(t, 3) for t in orig], "file": c["png"],
                    "fixed": not named, "hidden": bool(mv and mv["hide"]), "draws": p.get("draws", 1)})
    return {"screen": "game", "scope": "title", "elements": els, "label": c["label"], "png": c["png"],
            "size": [W, H], "censuses": [x["label"] for x in cs]}
