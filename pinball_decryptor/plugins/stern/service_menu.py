"""The game's operator menu as the machine will show it, with the app's own rows in it (PAD-1382).

David: "how does the user edit the service menu? I feel like we should have a visual render of the service menu in
our app". Each setting of ours (MUSIC MODE, EDITION, CO-OP PLAY, HANDICAP, the picture settings) is switched on its own
tab, and the Write decides which of the game's spare rows each takes and on which page; until now the only word of
where they went was a line of the build log, and since PAD-1382 several can share MORE SETTINGS and the row under it.

:func:`pages` plans the project's rows exactly as a Write does (:func:`.menu_settings.plan_many`, the engine's menu
jobs' own ``wanted()`` in the engine's order) and lays out each page that carries one, in the order the machine draws
it - read in the emulator on Godzilla LE 1.16's Attract Mode page (artifacts/PAD-1382/emulator): the page's SYSTEM
rows in the category table's order, the rows a Write appends to that table (ours), then the game's FEATURE rows
(ids 160 up) whose descriptor names the page. Captions are the menu's own row captions (the descriptor's, title
cased, where a row has none of its own); a value is shown where the descriptor's display kind says how (a number,
Yes/No, Off/On) - the game words the rest itself (12-Hour, Random...), which are left blank rather than guessed. The
game can also hide a row of its own at run time (Godzilla LE does not show 70TH BOOT SCREEN); those are all listed.
"""
from __future__ import annotations

import re
import struct

from . import menu_settings as MS
from .adjustments import OFF_MENU_HELP, AdjustmentTable, menu_label

#: display kinds the menu shows as words (the low 16 bits of the descriptor's kind word)
KIND_WORDS = {1: ("Off", "On"), 9: ("No", "Yes")}
KIND_NUMBER = 2
#: a feature row: its descriptor's u16 at +0x26 names its page (menu_settings, PAD-494)
FEATURE_FIRST = 160
OFF_CATEGORY = 0x26


class _Log:
    def __call__(self, *a, **k):
        pass


def wanted(project):
    """``[(key, values, names, options)]`` the project's settings ask a Write for, in the engine's order (music,
    edition, pictures, co-op, handicap), each from the engine's own menu job."""
    from . import engine as E
    from . import coop_play as CP, editions as Ed, handicap as HC, picture_settings as PS, sound_modes as SMo
    log = _Log()
    jobs = []
    try:
        modes = SMo.load(project)
        if modes.count:
            jobs.append(E._MusicModeMenu(modes.count, modes.menu_names(), log))
    except Exception:                                   # noqa: BLE001 - no music modes then
        pass
    try:
        names = Ed.load(project)
        if Ed.count(names) and not Ed.title_refusal(Ed.project_title(project, probe=True)):
            jobs.append(E._EditionMenu(len(names), names, log))
    except Exception:                                   # noqa: BLE001
        pass
    if PS.load(project):
        jobs += [E._PictureMenu(k, log) for k in PS.KEYS]
    if CP.menu_asked(project):
        jobs.append(E._CoopMenu(log))
    if HC.load(project):
        jobs.append(E._HandicapMenu(log))
    return [j.wanted() for j in arrange(project, jobs, log)]


# ---- the owner's order and settings of their own (PAD-1382 round 3) ------------------------------------------------
#: the sidecar key: {"order": [setting keys], "custom": [{"key", "name", "values": [names], "default": 1..n}]}
STAGED_KEY = "service_menu"
CUSTOM_PREFIX = MS.CUSTOM_PREFIX
#: a custom setting's name: what the row caption shows (the descriptor's caption, which the board keys the stored
#: value by, is its upper case); the shortest room a spare row's caption has on the latest builds is 21
NAME_MAX = 20
VALUE_MAX = 14
CUSTOM_MAX = 8
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-]*$")


def load(project):
    """``{"order": [...], "custom": [...]}`` from the project's sidecar (cleaned; empty when none)."""
    out = {"order": [], "custom": []}
    if not project:
        return out
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return out
    if not isinstance(raw, dict):
        return out
    order = raw.get("order")
    if isinstance(order, list):
        out["order"] = [k for k in order if isinstance(k, str)]
    seen = set()
    for c in raw.get("custom") or []:
        try:
            c = custom_clean(c.get("name"), c.get("values"), c.get("default", 1))
        except (AttributeError, ValueError):
            continue
        if c["key"] not in seen and len(out["custom"]) < CUSTOM_MAX:
            seen.add(c["key"])
            out["custom"].append(c)
    return out


def save(project, data):
    from ...core import staged_changes
    side = staged_changes.load(project)
    keep = {"order": list(data.get("order") or []), "custom": list(data.get("custom") or [])}
    if keep["order"] or keep["custom"]:
        side[STAGED_KEY] = keep
    else:
        side.pop(STAGED_KEY, None)
    staged_changes.save(project, side)


def custom_key(name):
    return CUSTOM_PREFIX + re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def custom_clean(name, values, default=1):
    """A custom setting as kept, or ValueError saying what is wrong (in the user's words)."""
    name = " ".join(str(name or "").split())
    if not name or len(name) > NAME_MAX or not _NAME_RE.match(name):
        raise ValueError("A setting's name is 1 to %d letters, digits, spaces or dashes." % NAME_MAX)
    if name.upper() in {v[1] for k, v in MS.SETTINGS.items() if not k.startswith(CUSTOM_PREFIX)}:
        raise ValueError("%s is one of the app's own settings." % name)
    if isinstance(values, str):
        values = values.split(",")
    values = [" ".join(str(v).split())[:VALUE_MAX] for v in (values or [])]
    values = [v for v in values if v]
    if not 2 <= len(values) <= MS.MAX_VALUES:
        raise ValueError("A setting has 2 to %d values." % MS.MAX_VALUES)
    try:
        default = int(default)
    except (TypeError, ValueError):
        default = 1
    if not 1 <= default <= len(values):
        default = 1
    return {"key": custom_key(name), "name": name, "values": values, "default": default}


def register(custom):
    """Make *custom* a setting :mod:`.menu_settings` can place (its captions; Attract Mode, as CO-OP PLAY's)."""
    MS.SETTINGS[custom["key"]] = (None, custom["name"].upper(), custom["name"], 16)


class CustomMenu:
    """A setting of the owner's own as one of the game program's edits, as the engine's menu jobs are (its value is
    read by the card's own code: ``pm_setting("<key>")``, pad_mode.h)."""

    def __init__(self, custom, log):
        self.custom, self.log, self.KEY = custom, log, custom["key"]
        self.ok, self.why, self.setting = False, "", None
        register(custom)

    def wanted(self):
        c = self.custom
        return self.KEY, len(c["values"]), list(c["values"]), {"default": c["default"]}

    def done(self):
        self.ok = True
        self.log("Your settings: %s is in the operator menu (%s), values %s; the card's own code reads it as "
                 "pm_setting(\"%s\")." % (self.custom["name"].upper(), self.setting.where,
                                         ", ".join("%d %s" % (i + 1, v) for i, v in enumerate(self.custom["values"])),
                                         self.KEY), "info")

    def fail(self, why):
        if self.why or self.ok:
            return
        self.why = str(why).rstrip(".") or "unknown"
        self.log("Your settings: %s could not be added to the operator menu (%s)." % (self.custom["name"].upper(),
                                                                                        self.why), "warning")


def arrange(project, jobs, log):
    """The build's menu jobs (None left out) with the owner's settings added, in the owner's order: keys they
    ordered first, as ordered, then the rest as the engine has them (Spike 2)."""
    jobs = [j for j in jobs if j is not None]
    mine = load(project)
    jobs += [CustomMenu(c, log) for c in mine["custom"]]
    order = mine["order"]
    rank = {k: n for n, k in enumerate(order)}
    return [j for _n, j in sorted(enumerate(jobs), key=lambda x: (rank.get(x[1].KEY, len(order)), x[0]))]


def _desc(t, i):
    return t._off(t.table_va + i * t.elem)


def _caption(t, i):
    row = MS._row_caption_line(t, i)
    if row is not None and row[1]:
        return row[1]
    return " ".join(w.capitalize() if w.isalpha() else w for w in menu_label(t, i).split())


def _help(t, i):
    try:
        return t._cstr(struct.unpack_from("<I", t.data, _desc(t, i) + OFF_MENU_HELP)[0], 200) or ""
    except Exception:                                   # noqa: BLE001
        return ""


def _word(kind, v):
    """How the menu shows value *v* of display kind *kind* (``""`` when the game words it itself)."""
    k = kind & 0xffff
    if k in KIND_WORDS and v in (0, 1):
        return KIND_WORDS[k][v]
    if k == KIND_NUMBER:
        return str(v)
    return ""


def _game_row(t, i):
    e = t.entry(i)
    kind = struct.unpack_from("<I", t.data, _desc(t, i) + MS.OFF_KIND)[0] if t.elem == 44 else 0
    word = _word(kind, e["default"])
    return {"id": i, "caption": _caption(t, i), "help": _help(t, i), "ours": False, "value": word,
            "default": word, "name": menu_label(t, i)}


def _our_row(s, kind_words):
    """One of ours: its values as the menu will show them (low..), default first."""
    words = kind_words.get(s.kind) if s.kind else None
    vals = [{"v": v, "text": (words[v] if words and v in (0, 1) else str(v))}
            for v in range(s.low, s.low + s.values)]
    text = next(x["text"] for x in vals if x["v"] == s.default)
    return {"id": s.id, "key": s.key, "caption": s.caption, "help": s.help, "ours": True, "values": vals,
            "value": text, "default": text, "name": MS.SETTINGS[s.key][1]}


def pages(raw, rows):
    """``{"pages": [...], "spare": n, "used": n, "shared": bool, "refused": {key: why}}`` for game program *raw*
    and the settings *rows* (:func:`wanted`). Each page: ``{"category", "name", "path", "rows"}``; a row:
    ``{"caption", "value", "default", "help", "ours", ...}``; the MORE SETTINGS row has ``options`` - each shared
    setting's row, which the row under it becomes when it is picked."""
    t = AdjustmentTable(raw)
    spare = MS.spare(t)
    out = {"pages": [], "spare": len(spare), "used": 0, "shared": False, "refused": {}, "wanted": [r[0] for r in rows]}
    if not rows:
        return out
    settings, _w, cat, refused = MS.plan_many(t, rows)
    out["refused"] = {k: str(v) for k, v in refused.items()}
    table = cat if cat is not None else MS.menu_table(t)
    if table is None:
        out["refused"] = {r[0]: "the game's operator menu pages could not be read" for r in rows}
        return out
    kinds = {}
    try:
        kinds[MS.onoff_kind(t)] = ("Off", "On")
    except MS.MenuSettingError:
        pass
    own = [s for s in settings if not MS.is_shared(s)]
    shared = [s for s in settings if MS.is_shared(s)]
    out["used"] = len(own)
    out["shared"] = bool(shared)
    listed = {i for c, k, i in table.records if k == MS.KIND_ADJUSTMENT}
    for category in sorted({s.category for s in own}, key=lambda c: min(own.index(s) for s in own
                                                                           if s.category == c)):
        page = []
        for c, k, i in table.records:
            if c == category and k == MS.KIND_ADJUSTMENT and i not in {s.id for s in own}:
                page.append(_game_row(t, i))
        for s in own:
            if s.category != category:
                continue
            row = _our_row(s, kinds)
            if s.key == MS.MORE_SELECT:
                row["options"] = [dict(_our_row(o, kinds), setting=o.key) for o in shared]
                row["values"] = [{"v": k + 1, "text": str(k + 1)} for k in range(len(shared))]
                row["help"] = s.help
            if s.key == MS.MORE_VALUE:
                first = shared[0]
                row = dict(_our_row(first, kinds), shared_value=True, key=MS.MORE_VALUE, setting=first.key)
            page.append(row)
        if t.elem == 44:
            for i in range(FEATURE_FIRST, t.count):
                if i in listed:
                    continue
                if struct.unpack_from("<H", t.data, _desc(t, i) + OFF_CATEGORY)[0] == category:
                    page.append(_game_row(t, i))
        page_rank = _machine_rank(t, table, category)
        where = table.where(category) if hasattr(table, "where") else ""
        out["pages"].append({"category": category, "name": (where or "").split(" > ")[-1] or "Page %d" % category,
                             "path": where, "rows": page, "rank": page_rank})
    return out


#: Machine Settings lists the pages of these categories that have rows, in number order (Godzilla LE 1.16 in the
#: emulator: 8 Machine Operation ... 11 LCD/Lamp 4th, 13 Audio Content 6th, 16 Attract Mode 8th, 17 Test Menu Settings)
MACHINE_PAGES = range(8, 18)


def _machine_rank(t, table, category):
    """Where *category*'s page sits in Adjustments > Machine Settings (0 first), or None when it is not one of them."""
    if category not in MACHINE_PAGES:
        return None
    have = {c for c, k, _i in table.records if k == MS.KIND_ADJUSTMENT}
    if t.elem == 44:
        for i in range(FEATURE_FIRST, t.count):
            have.add(struct.unpack_from("<H", t.data, _desc(t, i) + OFF_CATEGORY)[0])
    return sorted(c for c in have if c in MACHINE_PAGES).index(category) if category in have else None


def walk(rank, row):
    """The presses (``menushot.sh`` steps) that take the game from attract to row *row* of the Machine Settings page
    at *rank*, as walked in the emulator on Godzilla LE 1.16: SELECT into the menu, Adjustments (5th), Machine
    Settings (3rd), the page, then the row (25 select, 26 plus/down; ``w<s>`` waits in game seconds)."""
    steps = ["25", "w2", "25", "w2"] + ["26"] * 4 + ["25", "w1.5"] + ["26"] * 2 + ["25", "w1.5"]
    steps += ["26"] * int(rank) + ["25", "w2"] + ["26"] * int(row) + ["w1"]
    return steps
