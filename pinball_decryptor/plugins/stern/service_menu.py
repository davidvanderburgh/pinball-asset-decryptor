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

import os
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


def wanted(project, honour_off=True):
    """``[(key, values, names, options)]`` the project's settings ask a Write for, in the engine's order (music,
    edition, pictures, co-op, handicap, image set), each from the engine's own menu job. PAD-1393 round 2: the ones
    not ticked on the Service menu tab (:func:`off_keys`; round 3: they start unticked) are left out, unless
    *honour_off* is false."""
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
    from . import scene_variants as SV
    sets = SV.load(project)                             # PAD-1390: IMAGE SET, when the project has image sets
    if sets:
        jobs.append(E._ImageSetMenu(sets["names"], log))
    from . import saved_progress as SP
    if SP.project_wants(project):                       # PAD-1402: SAVED PROGRESS, when a mode keeps progress
        jobs.append(E._SavedProgressMenu(log))
    if honour_off:
        off = off_keys(project)
        jobs = [j for j in jobs if j.KEY not in off]
    return [j.wanted() for j in arrange(project, jobs, log)]


# ---- the owner's order of the app's rows (PAD-1382 round 3) ---------------------------------------------------------
# Round 5 (David): "we should just be checking off items that exist (making a new one here doesn't make sense...)":
# the rows are the app's own settings, switched on their tabs or on the Service menu tab; the owner orders them.
#: the sidecar key: {"order": [setting keys], "on": [setting keys], "coop": true}
STAGED_KEY = "service_menu"
#: PAD-1393 round 2 (DragonRR: "Image set ... I cannot uncheck it"): the settings whose row the Service menu tab can
#: leave off the card although the project has them; the Write then leaves the setting off the card, as when the game
#: has no spare row for it (music modes: every sound plays its own; editions: none to pick; image sets: the scenes as
#: the project has them). Co-op Play and Handicap have switches of their own.
#: Round 3 (DragonRR: "Everything should be unchecked by default - this is important"): these rows start unticked: a
#: setting of them goes on the card only once the owner ticks its row (the sidecar's "on" list). The round-2 "off"
#: list is read no more: everything is off until ticked.
OFF_KEYS = ("music_mode", "edition", "image_set")


def on_keys(project):
    """The settings of :data:`OFF_KEYS` the owner ticked on the Service menu tab, a set."""
    return set(load(project)["on"])


def off_keys(project):
    """The settings of :data:`OFF_KEYS` the card leaves off: every one the owner has not ticked (round 3), a set."""
    return set(OFF_KEYS) - on_keys(project)


def load(project):
    """``{"order": [...], "on": [...], "coop": bool}`` from the project's sidecar (empty when none). *coop*: co-op
    play was switched on by ticking its row here (so unticking it there switches it off again)."""
    out = {"order": [], "on": [], "coop": False}
    if not project:
        return out
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return out
    if isinstance(raw, dict) and isinstance(raw.get("order"), list):
        out["order"] = [k for k in raw["order"] if isinstance(k, str)]
    if isinstance(raw, dict) and isinstance(raw.get("on"), list):
        out["on"] = [k for k in raw["on"] if k in OFF_KEYS]
    if isinstance(raw, dict):
        out["coop"] = raw.get("coop") is True
    return out


def save(project, data):
    from ...core import staged_changes
    side = staged_changes.load(project)
    order = list(data.get("order") or [])
    on = [k for k in OFF_KEYS if k in (data.get("on") or ())]
    coop = data.get("coop") is True
    if order or on or coop:
        side[STAGED_KEY] = {k: v for k, v in (("order", order), ("on", on), ("coop", coop)) if v}
    else:
        side.pop(STAGED_KEY, None)
    staged_changes.save(project, side)


def arrange(project, jobs, log=None):
    """The build's menu jobs (None left out) in the owner's order: keys they ordered first, as ordered, then the rest as
    the engine has them (Spike 2)."""
    jobs = [j for j in jobs if j is not None]
    order = load(project)["order"]
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
        if getattr(t, "wide", False):                 # Spike 3: the table names its fields
            return t._cstr(t.word(t.field_off(i, "help")), 200) or ""
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
    try:
        kind = MS._kind_at(t, i) if t.elem == MS._kind_elem(t) else 0
    except Exception:                                   # noqa: BLE001
        kind = 0
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
    t = AdjustmentTable(raw, wide_ok=True)
    wide = bool(getattr(t, "wide", False))
    spare = MS.spare(t)
    out = {"pages": [], "spare": len(spare), "used": 0, "shared": False, "refused": {}, "wanted": [r[0] for r in rows],
           "wide": wide}
    settings, _w, cat, refused = MS.plan_many(t, rows) if rows else ([], {}, None, {})
    out["refused"] = {k: str(v) for k, v in refused.items()}
    table = cat if cat is not None else (MS.menu_table(t, MS.wide_consts(t)) if wide else MS.menu_table(t))
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
    if isinstance(table, MS.StandardList):            # round 4: the games without a category table (22 of 53)
        out["pages"] = _standard_pages(t, table, own, shared, kinds)
        return out
    listed = {i for c, k, i in table.records if k == MS.KIND_ADJUSTMENT}
    names = ({c: n.replace("&trade;", "") for c, n in MS.wide_category_names(t).items()} if wide
             else category_names(t))
    # round 4: every Machine Settings page, in the menu's order, whether or not one of ours is on it (the menu as it
    # is, to see before adding to it), and any other page that carries one of ours after them
    machine = _machine_pages(t, table)
    # round 5: a page of our own (menu_settings.own_page) is listed in its place among them, by its new name
    machine = sorted(set(machine) | {s.category for s in own if s.category in MACHINE_PAGES})
    if any(s.category == MS.OWN_CATEGORY for s in own) and not wide:
        names[MS.OWN_CATEGORY] = MS.OWN_PAGE
    out["own"] = MS.OWN_PAGE if any(s.category == MS.OWN_CATEGORY for s in own) else ""
    # the page's help on the Machine Settings list, as menu_settings.own_page writes it (Simon and David: an asterisk
    # on a setting that takes effect on the next power-up, and the help line saying so)
    out["own_help"] = (MS.OWN_HELP_POWER_UP[0] if any(s.key in MS.POWER_UP for s in own) else MS.OWN_HELP) \
        if out["own"] else ""
    out["machine_list"] = [names.get(c, "Page %d" % c) for c in machine]
    cats = machine + sorted({s.category for s in own} - set(machine))
    for category in cats:
        page = []
        for c, k, i in table.records:
            if c == category and k == MS.KIND_ADJUSTMENT and i not in {s.id for s in own}:
                page.append(_game_row(t, i))
        page += _ours_rows([x for x in own if x.category == category], shared, kinds)
        if t.elem == 44:
            for i in range(FEATURE_FIRST, t.count):
                if i in listed:
                    continue
                if struct.unpack_from("<H", t.data, _desc(t, i) + OFF_CATEGORY)[0] == category:
                    page.append(_game_row(t, i))
        # the real menu's walk is measured on Spike 2 (Spike 3's emulator opens no settings page, PAD-1325)
        page_rank = machine.index(category) if category in machine and not wide else None
        name = names.get(category) or ((table.where(category) if hasattr(table, "where") else "") or "").split(
            " > ")[-1] or "Page %d" % category
        out["pages"].append({"category": category, "name": name, "rows": page, "rank": page_rank,
                             "path": "Adjustments > %s > %s" % (names.get(3, "Machine Settings"), name),
                             "ours": any(r["ours"] for r in page)})
    return out


def _ours_rows(own, shared, kinds):
    """The rows of ours *own* as the menu shows them: MORE SETTINGS with each shared setting as an option, the row under
    it as the first of them."""
    out = []
    for s in own:
        row = _our_row(s, kinds)
        if s.key == MS.MORE_SELECT:
            row["options"] = [dict(_our_row(o, kinds), setting=o.key) for o in shared]
            row["values"] = [{"v": k + 1, "text": str(k + 1)} for k in range(len(shared))]
            row["help"] = s.help
        if s.key == MS.MORE_VALUE:
            first = shared[0]
            row = dict(_our_row(first, kinds), shared_value=True, key=MS.MORE_VALUE, setting=first.key)
        out.append(row)
    return out


#: round 4: a game without a category table (:class:`.menu_settings.StandardList`) has two Adjustments pages; ours go
#: at the end of Standard Adjustments (PAD-724)
STANDARD_PAGES = (("Standard Adjustments", "list"), ("Feature Adjustments", "range"))


def _standard_pages(t, table, own, shared, kinds):
    from . import menu_visibility as MV
    reading = MV.MenuVisibility(t)
    feature = []
    try:
        feature = next((list(ids) for kind, ids, _c, _a in reading._pages_raw() if kind == "range" and ids), [])
    except Exception:                                   # noqa: BLE001 - the Standard page alone, then
        feature = []
    ours = {s.id for s in own}
    std = [_game_row(t, i) for i in table.ids if i not in ours] + _ours_rows(own, shared, kinds)
    out = [{"category": -1, "name": "Standard Adjustments", "rows": std, "rank": STANDARD_RANK["Standard Adjustments"],
            "path": "Adjustments > Standard Adjustments", "ours": bool(own), "style": "dmd",
            "label": "STANDARD ADJUSTMENT"}]
    if feature:
        out.append({"category": -2, "name": "Feature Adjustments", "rows": [_game_row(t, i) for i in feature],
                    "rank": STANDARD_RANK["Feature Adjustments"], "path": "Adjustments > Feature Adjustments",
                    "ours": False, "style": "dmd", "label": "FEATURE ADJUSTMENT"})
    return out


#: where the two pages sit in Adjustments on those games, for the real menu's walk: its icons are STANDARD, FEATURE,
#: PREV, QUIT (Aerosmith LE 1.16 and Venom LE 1.07 in the emulator, a dot-matrix menu one adjustment a screen:
#: "STANDARD ADJUSTMENT #n", the row's caption, its value)
STANDARD_RANK = {"Standard Adjustments": 0, "Feature Adjustments": 1}


def category_names(t):
    """``{category: name}`` from the game's own table of page names (Spike 2): a line of five language pointers and a
    zero per category, category c c lines above the line that names INVALID (category 0) - read on Godzilla LE 1.16:
    9 Device Enables, 11 LCD/Lamp, 13 Audio Content, 16 Attract Mode, as its menu shows them. ``{}`` when not found."""
    raw = t.data
    out = {}
    zero = MS.category_name_line(t, 0)
    if zero is None:
        return out
    j = zero
    for c in range(1, 37):
        o = j - c * 24
        if o < 0:
            break
        w = struct.unpack_from("<6I", raw, o)
        if w[5] != 0 or t._off(w[0]) is None:
            break
        name = t._cstr(w[0], 60) or ""
        if not name or not all(32 <= ord(ch) < 127 for ch in name):
            break
        out[c] = name.replace("&trade;", "")
    return out


def _machine_pages(t, table):
    """The Machine Settings pages, in the menu's order: categories 8-17 that have rows (:data:`MACHINE_PAGES`)."""
    have = {c for c, k, _i in table.records if k == MS.KIND_ADJUSTMENT}
    if t.elem == 44:
        for i in range(FEATURE_FIRST, t.count):
            have.add(struct.unpack_from("<H", t.data, _desc(t, i) + OFF_CATEGORY)[0])
    return sorted(c for c in have if c in MACHINE_PAGES)


# ---- which game program to read (round 4) ---------------------------------------------------------------------------
# David, trying the tab on his own project: "The card image could not be opened: ... No such file or directory:
# 'C:\\Users\\david\\OneDrive\\Desktop\\Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition.raw'" - "we need to
# make this work for all game images". A project outlives its card: the file it was extracted from is moved, renamed
# or deleted, while the same game and version sits in the project's own build folder, in the card library, or was read
# here before. The menu is the game program's, so any card of the project's game and version will do.
CARD_EXTS = (".raw", ".img", ".bin")
#: the most card files a search opens (each answer is cached per file size and time)
SEARCH_MAX = 80


def _settings_cards():
    """Card paths the app's settings name (every manufacturer's Extract input, Write original, Emulate card...)."""
    from ...core import config
    import json
    try:
        with open(config.SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.lower().endswith(CARD_EXTS):
            out.append(o)
    walk(data)
    return out


def card_candidates(project, extra=()):
    """Card images that may hold *project*'s game program, best first: the cards the project records (its extract,
    its anchor's paths), then its own Write output (``build``), then *extra* and the app settings' cards, then every
    card file in the folders all of those are in. Paths only: whether each is there, and its game, is asked later."""
    from ...core import extract_source, project_file
    named = []
    try:
        rec = extract_source.read_extract_source(project) or {}
        named.append(rec.get("input_path") or "")
    except Exception:                                   # noqa: BLE001
        pass
    try:
        if project_file.has_anchor(project):
            a = project_file.load_anchor(project) or {}
            paths = a.get("paths") or {}
            named += [a.get("stock_image") or "", paths.get("write_original") or "", paths.get("extract_input") or "",
                      a.get("emulate_card") or ""]
    except Exception:                                   # noqa: BLE001
        pass
    build = os.path.join(project, "build")
    built = []
    if os.path.isdir(build):
        built = sorted((os.path.join(build, n) for n in os.listdir(build) if n.lower().endswith(CARD_EXTS)),
                       key=lambda p: -os.path.getmtime(p))
    known = list(extra) + _settings_cards()
    out, seen = [], set()

    def add(p):
        if not p:
            return
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    for p in named + built + known:
        add(p)
    folders = []
    for p in named + known:
        d = os.path.dirname(p)
        if d and os.path.isdir(d) and os.path.normcase(d) not in [os.path.normcase(x) for x in folders]:
            folders.append(d)
    for d in folders:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if n.lower().endswith(CARD_EXTS):
                add(os.path.join(d, n))
    return out


def _program_cache(game, version):
    from . import title_reader as TR
    from .mode_project import version_key
    return os.path.join(TR.cache_dir("menu_programs"), "%s-%s.elf" % (game, "_".join(map(str, version_key(version)))))


def find_program(project, extra=()):
    """``(elf bytes, where from)`` for *project*'s game, or raise ValueError saying why none was found. The card the
    project was made from when it is there; else another card of the same game and version (its build output, the
    library the app's settings point at), else the copy kept from the last read."""
    from . import mode_project as MP, title_reader as TR
    pc = MP.project_card(project)
    game = getattr(pc, "game_dir", "") or ""
    version = getattr(pc, "version", "") or ""
    recorded = getattr(pc, "image", "") or ""
    tried = 0
    for card in card_candidates(project, extra):
        if not os.path.isfile(card):
            continue
        if os.path.normcase(card) != os.path.normcase(recorded) or not game:
            if not game or tried >= SEARCH_MAX:
                continue
            tried += 1
            g, v = MP.probe_card_title(card)
            if g != game or MP.version_key(v) != MP.version_key(version):
                continue
        try:
            got_game, got_version, elf = TR.game_program(card)
        except Exception:                               # noqa: BLE001 - the next card, then
            continue
        game, version = game or got_game, version or got_version
        try:
            with open(_program_cache(game, version), "wb") as f:
                f.write(elf)
        except OSError:
            pass
        return elf, card
    if game and version:
        try:
            with open(_program_cache(game, version), "rb") as f:
                elf = f.read()
            if elf[:4] == b"\x7fELF":
                return elf, "the copy of %s %s kept from an earlier read" % (game, version)
        except OSError:
            pass
    if not game:
        raise ValueError("This project does not say which game it is for, and the card it was made from is not "
                         "there (%s)." % (recorded or "none recorded"))
    raise ValueError("No card of %s %s was found: the card this project was made from is not there (%s). Put that "
                     "card back, or pick any card of the same game and version on the Extract tab."
                     % (game, version, recorded or "none recorded"))


#: Machine Settings lists the pages of these categories that have rows, in number order (Godzilla LE 1.16 in the
#: emulator: 8 Machine Operation ... 11 LCD/Lamp 4th, 13 Audio Content 6th, 16 Attract Mode 8th, 17 Test Menu Settings)
MACHINE_PAGES = range(8, 18)


def walk(rank, row, style="list", count=0):
    """The presses (``menushot.sh`` steps) that take the game from attract to row *row* of the Machine Settings page
    at *rank*, as walked in the emulator on Godzilla LE 1.16: SELECT into the menu, Adjustments (5th), Machine
    Settings (3rd), the page, then the row (25 select, 26 plus/down; ``w<s>`` waits in game seconds)."""
    if style == "dmd":
        # the older dot-matrix menu (Aerosmith LE 1.16): its icons DIAG, AUD, ADJ (3rd), NET...; ADJ's STANDARD,
        # FEATURE...; then one adjustment a screen, MINUS from the first wrapping round to the last (where ours are)
        steps = ["25", "w2", "25", "w2", "26", "26", "25", "w2"] + ["26"] * int(rank) + ["25", "w2"]
        row, count = int(row), int(count or 0)
        steps += (["27"] * (count - row) if count and row > count // 2 else ["26"] * row) + ["w1"]
        return steps
    steps = ["25", "w2", "25", "w2"] + ["26"] * 4 + ["25", "w1.5"] + ["26"] * 2 + ["25", "w1.5"]
    steps += ["26"] * int(rank) + ["25", "w2"] + ["26"] * int(row) + ["w1"]
    return steps
