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
    return [j.wanted() for j in jobs]


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
        where = table.where(category) if hasattr(table, "where") else ""
        out["pages"].append({"category": category, "name": (where or "").split(" > ")[-1] or "Page %d" % category,
                             "path": where, "rows": page})
    return out
