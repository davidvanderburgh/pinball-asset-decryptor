#!/usr/bin/env python3
"""vpxsetup.py - the Visual Pinball kit's setup, for the app's Visual Pinball tab.

The app's tab (pinball_decryptor/webui/tabs/vpx.py) runs this with the app's
own Windows Python and reads one JSON object back from its last line, so the
kit's pywin32, its DPI awareness and its module names never enter the app's
process:

    vpxsetup.py state                     what is set up: Visual Pinball, the controller,
                                          the card folder and each table the kit knows
    vpxsetup.py vpx <folder>              Visual Pinball is here
    vpxsetup.py download <folder>         download the 10.8.0 release and unpack it there
                                          (progress lines first: `progress <0..1>`)
    vpxsetup.py library <folder>          the folder of card images
    vpxsetup.py downloads [<folder>]      read the downloads in the tables folder (PAD-943)
    vpxsetup.py tables [<folder>]         where the patched tables live (none:
                                          Visual Pinball's own tables folder)
    vpxsetup.py layout <key> <player> <lcd>
                                          where the windows go: [x, y, w, h] JSON or null
    vpxsetup.py open <table name>         open a (PAD) table in Visual Pinball
    vpxsetup.py open_download <path>      open a download as it is (PAD-952: TNA, AMH)

PAD SHIPS NO TABLE. The kit patches the copy the user downloaded from its
author (`padvpx patch`); each map names the table it fits (`table`) so the
tab can say which download that is.
"""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
for p in (HERE, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)

import padisplay  # noqa: E402
import padlaunch   # noqa: E402
import padvpx      # noqa: E402

VPX_URL = ("https://github.com/vpinball/vpinball/releases/download/v10.8.0-2051-28dd6c3/"
           "Developer.VPinballX-10.8.0-2051-28dd6c3-Release-win-x64.zip")
VPX_DEFAULT_DIR = r"C:\Visual Pinball"
#: the oldest Visual Pinball the kit's tables open in (PAD-887): JAWS, Deadpool,
#: Foo Fighters, Metallica, Rush, Sword of Rage and Star Wars are saved by 10.8
#: (file version 1080), which an older player refuses; 10.8.0 is what the tab
#: downloads and what every table was proven on
VPX_MIN = (10, 8, 0)


def controller_registration():
    """(registered, the folder PAD.Controller is registered to): registered
    only when what it points at is still there (PAD-850). The key alone said
    "Registered" while the folder it named had been deleted, and every table
    then stopped on "Can't load PAD.Controller: ActiveX component can't
    create object"; now the tab offers Register again instead."""
    try:
        import winreg
        root = winreg.HKEY_CLASSES_ROOT
        clsid = winreg.QueryValue(root, "PAD.Controller\\CLSID")
        path = winreg.QueryValue(root, "CLSID\\%s\\PythonCOMPath" % clsid)
        server = winreg.QueryValue(root, "CLSID\\%s\\LocalServer32" % clsid)
    except Exception:                                       # noqa: BLE001
        return False, ""
    return registration_ok(path, server), path or ""


def controller_registered():
    return controller_registration()[0]


def registered_here(path):
    """The registered folder is THIS kit's (PAD-943). A table patched by
    one copy of the app calls whichever PAD.Controller the registry names:
    David's Spike 1 tables stopped on "no Spike 2 run is up" because the
    registration was an older checkout's, with no Spike 1 in it."""
    if not path:
        return False
    try:
        return os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(HERE))
    except OSError:
        return False


def registration_ok(com_path, server_cmd):
    """The registered folder holds padcontroller.py, and the python the
    server command starts exists."""
    exe = server_cmd.strip()
    exe = exe[1:].split('"', 1)[0] if exe.startswith('"') else exe.split(" ", 1)[0]
    return (bool(com_path) and os.path.isfile(os.path.join(com_path, "padcontroller.py"))
            and bool(exe) and os.path.isfile(exe))


def find_vpx():
    kit = padlaunch.kit_load().get("vpx")
    for d in [kit, VPX_DEFAULT_DIR, os.path.join(os.environ.get("ProgramFiles", ""), "Visual Pinball"),
              os.path.join(os.path.expanduser("~"), "Visual Pinball")]:
        if d and os.path.isfile(os.path.join(d, "VPinballX64.exe")):
            return d
    return ""


def vpx_version(folder):
    """VPinballX64.exe's own file version in *folder*, as (major, minor,
    patch), or None when it cannot be read (no exe, not Windows)."""
    exe = os.path.join(folder or "", "VPinballX64.exe")
    if not folder or not os.path.isfile(exe) or sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        n = ver.GetFileVersionInfoSizeW(exe, None)
        buf = ctypes.create_string_buffer(n)
        if not n or not ver.GetFileVersionInfoW(exe, 0, n, buf):
            return None
        p, size = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(size)):
            return None
        # VS_FIXEDFILEINFO: signature, struct version, then FileVersionMS/LS
        ms, ls = ctypes.cast(p, ctypes.POINTER(wintypes.DWORD * 4)).contents[2:4]
    except Exception:                                       # noqa: BLE001
        return None
    return (ms >> 16, ms & 0xFFFF, ls >> 16)


def dotted(v):
    return ".".join(str(x) for x in v) if v else ""


def vpx_tables_dir():
    """Where the patched tables live: the folder chosen on the tab (PAD-848,
    David keeps his in a folder on the desktop), else Visual Pinball's own
    tables folder. The "Patched" marks, the Play list and Patch's output all
    use it."""
    own = padlaunch.kit_load().get("tables")
    if own and os.path.isdir(own):
        return own
    vpx = find_vpx()
    return os.path.join(vpx, "tables") if vpx else ""


def set_tables(folder):
    """The patched tables' folder (PAD-848); "" goes back to Visual Pinball's."""
    if folder and not os.path.isdir(folder):
        return "There is no folder %s." % folder
    d = padlaunch.kit_load()
    if folder:
        d["tables"] = folder
    else:
        d.pop("tables", None)
    padlaunch.kit_save(d)
    return "ok"


def set_vpx(folder):
    if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
        return "There is no VPinballX64.exe in %s." % folder
    d = padlaunch.kit_load()
    d["vpx"] = folder
    padlaunch.kit_save(d)
    return "ok"


def set_library(folder):
    d = padlaunch.kit_load()
    d["library"] = folder
    padlaunch.kit_save(d)
    return cards_in(folder)


CARD_RE = {"spike2": r"^([a-z0-9_]+)-\d+_\d+_\d+.*\.sdcard\.raw$",
           "spike1": r"^([a-z0-9_]+)-\d+[._]\d+(?:[._]\d+)?.*\.iso$"}       # GOT_LE-1_37.iso, transformers_pin-1.0.18.iso


def cards_in(folder, platform="spike2"):
    """{title: [file names]} of the platform's card images in `folder`. A
    Spooky title's is its update file (code_H78.pkg), PAD-952."""
    out = {}
    if folder and os.path.isdir(folder):
        for f in os.listdir(folder):
            if platform == "spooky":
                for title, globs in padlaunch.SPOOKY_UPDATES.items():
                    if any(fnmatch.fnmatch(f.lower(), g.lower()) for g in globs):
                        out.setdefault(title, []).append(f)
                continue
            m = re.match(CARD_RE.get(platform, CARD_RE["spike2"]), f, re.I)
            if m:
                out.setdefault(m.group(1).lower(), []).append(f)
    return out


def all_cards(lib, kit=None):
    """The library's Spike 2 cards and, from the Spike 1 libraries beside it
    (padlaunch.libraries), the Spike 1 .iso cards (PAD-943): the Card images
    row said "No card for got_le, kiss_le..." while their rows had found
    the .iso."""
    out = cards_in(lib)
    seen = {os.path.normcase(os.path.abspath(lib))} if lib else set()
    # PAD-952: and the Spooky updates from the maker's folder beside it
    for platform in ("spike1", "spooky"):
        for d in padlaunch.libraries(platform, kit):
            key = (platform, os.path.normcase(os.path.abspath(d)))
            if key in seen or (platform == "spike1" and key[1] in seen):
                continue
            seen.add(key)
            for title, files in cards_in(d, platform).items():
                out.setdefault(title, []).extend(f for f in files if f not in out.get(title, []))
    return out


def known_tables(tables_dir=None):
    """Each table the kit can patch: the download it fits (the map's
    `table`), the patched name, whether that is in Visual Pinball's tables
    folder, the title Patch takes for it and the card that title boots.
    Maps for one download (JP's Foo Fighters: Pro and LE) are one row:
    `titles` all of them, preferred first, `title` the one padvpx.choose()
    takes, `models` each one's model."""
    tables_dir = vpx_tables_dir() if tables_dir is None else tables_dir
    rows = {}
    for title, info in padvpx.maps().items():
        if not info.get("listed", True):
            continue
        try:
            m = json.load(open(info["map"], encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        t = m.get("table") or {}
        out_name = info["output"] or ""
        row = rows.get(out_name or title)
        if row is None:
            row = rows[out_name or title] = {
                "name": t.get("name") or title, "by": t.get("by") or "",
                "where": t.get("where") or "", "output": out_name,
                "patched": bool(out_name and tables_dir
                                and os.path.isfile(os.path.join(tables_dir, out_name))),
                "titles": [], "models": {}, "fits": []}
        row["titles"].append(title)
        row["models"][title] = info["model"]
        row["fits"].append((title, info))
        row.setdefault("marks", []).extend(m.get("repatch") or [])
    out = []
    for row in rows.values():
        title, _ = padvpx.choose(row.pop("fits"))
        marks = row.pop("marks")
        # PAD-943: a Spike 1 title's card is its .iso, in the spike1 library;
        # the row's platform is what the tab filters by on each manufacturer
        row.update(title=title, platform=padvpx.platform_of(title),
                   card=padlaunch.card_for(title, padvpx.platform_of(title)) or "",
                   patched_title=patched_title(tables_dir, row["output"]) if row["patched"] else "",
                   repatch=missed_fixes(tables_dir, row["output"], marks) if row["patched"] else [],
                   source=patched_from(tables_dir, row["output"]) if row["patched"] else "")
        out.append(row)
    return out


# ---------------------------------------------- the downloads in the folder --
#
# PAD-943 (David: "I just added a handful of VPX original tables to the folder,
# but the app is not showing them"): every .vpx in the tables folder that is
# not a (PAD) copy is a download of the person's, and the page lists it - the
# one a listed map fits on that table's row (its Patch takes the file without
# asking), the rest as rows of their own saying there is no map yet, named
# from the catalogue where the file's name matches a table in it. Reading a
# table's script to see what fits it takes ~0.3 s a file, so that is done
# once per (file, size, mtime) and kept in the kit's cache; `state` lists the
# files at once from the cache, `downloads` reads the unread ones.
DOWNLOADS_CACHE = os.path.join(os.path.expanduser("~"), ".pad-vpx.downloads.json")
_STOP_WORDS = {"the", "and", "for", "stern", "original", "vpx", "mod", "table", "tribute", "edition",
               "limited", "pro", "premium", "le", "se", "vpw", "version", "with"}


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP_WORDS}


def catalog_match(file_name, catalog=None):
    """The catalogue table a download's file name names, or None: the entry
    whose name (or game) shares the most significant words with the file,
    at least two of them and half of its own."""
    cat = catalog or load_catalog()
    fw = _words(os.path.splitext(file_name)[0])
    best, score = None, 0
    for t in cat.get("tables") or []:
        if not t.get("url"):
            continue
        for key in ("name", "game"):
            tw = _words(t.get(key))
            hit = len(fw & tw)
            if hit >= 2 and hit * 2 >= len(tw) and hit > score:
                best, score = t, hit
    if not best:
        return None
    plats = cat.get("platforms") or {}
    # the author's own description, for the download's row on the page
    return {"platform": best["platform"], "platform_name": (plats.get(best["platform"]) or {}).get("name", ""),
            "game": best.get("game", ""), "name": best.get("name", ""), "map": best.get("map", ""),
            "by": best.get("by", ""), "where": best.get("where", ""), "url": best.get("url", ""),
            "version": best.get("version", ""), "kind": best.get("kind", ""), "faithful": bool(best.get("faithful")),
            "title": best.get("title", ""),
            # PAD-952: why nothing can ever play behind it (TNA: its game's key
            # is unknown; AMH: its update holds no game program)
            "no_game": best.get("no_game", "")}


#: what a cache entry must carry (older ones are read again; 3: no_game, PAD-952)
DOWNLOADS_CACHE_V = 3


def maps_signature():
    """What the kit's maps are, as a string: a download read with an older set
    (before got_le's map existed) is read again, or it would say 'no map
    fits' for good (David saw KISS and GOT listed twice, PAD-943)."""
    out = []
    for title, info in sorted(padvpx.maps().items()):
        try:
            out.append("%s:%d" % (title, int(os.path.getmtime(info["map"]))))
        except OSError:
            out.append(title)
    return ";".join(out)


def _downloads_cache():
    try:
        d = json.load(open(DOWNLOADS_CACHE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_downloads_cache(d):
    try:
        with open(DOWNLOADS_CACHE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(DOWNLOADS_CACHE + ".tmp", DOWNLOADS_CACHE)
    except OSError:
        pass


def download_files(tables_dir):
    """The .vpx downloads in the tables folder and in the folders directly in
    it (David keeps his in `originals`, PAD-952): [(file, path)], the
    folder's own first, (PAD) copies left out."""
    out = []
    try:
        top = sorted(os.listdir(tables_dir), key=str.lower)
    except OSError:
        return out
    subs = []
    for f in top:
        path = os.path.join(tables_dir, f)
        if f.lower().endswith(".vpx") and "(PAD)" not in f:
            out.append((f, path))
        elif os.path.isdir(path):
            subs.append(path)
    for d in subs:
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            continue
        out += [(f, os.path.join(d, f)) for f in names
                if f.lower().endswith(".vpx") and "(PAD)" not in f]
    return out


def downloads_in(tables_dir, cache=None):
    """The person's own downloads in the tables folder (and the folders in
    it), at once: [{name, file, path, size, mtime, read, title, catalog}],
    `read` False until read_downloads has looked at the file (then `title`
    is the listed map that fits it, "" when none, and `catalog` the
    catalogue's table it is named after, or None)."""
    if not tables_dir or not os.path.isdir(tables_dir):
        return []
    cache = _downloads_cache() if cache is None else cache
    maps_sig = maps_signature()
    out = []
    for f, path in download_files(tables_dir):
        try:
            st = os.stat(path)
        except OSError:
            continue
        row = {"name": os.path.splitext(f)[0], "file": f, "path": path, "size": st.st_size,
               "mtime": int(st.st_mtime), "read": False, "title": "", "catalog": None}
        c = cache.get(path)
        if c and c.get("size") == row["size"] and c.get("mtime") == row["mtime"] and c.get("v") == DOWNLOADS_CACHE_V                 and (c.get("title") or c.get("maps") == maps_sig):
            row.update(read=True, title=c.get("title") or "", catalog=c.get("catalog"))
            cat = row["catalog"] or {}
            # the card image the game boots, when the catalogue names the title
            row["card"] = padlaunch.card_for(cat["title"], cat.get("platform") or "spike2") or ""                 if cat.get("title") else ""
        out.append(row)
    return out


def read_downloads(tables_dir, say=None):
    """Read every download not read yet: which listed map fits its script,
    which catalogue table its name is; kept in the cache. Returns
    downloads_in() afterwards."""
    cache = _downloads_cache()
    catalog = load_catalog()
    changed = False
    for row in downloads_in(tables_dir, cache):
        if row["read"]:
            continue
        title = ""
        try:
            fits = [t for t, info in padvpx.fitting(row["path"]) if info.get("listed", True)]
            title = fits[0] if fits else ""
        except Exception as exc:                            # noqa: BLE001
            if say:
                say("%s: not read (%s)" % (row["file"], exc))
        cache[row["path"]] = {"size": row["size"], "mtime": row["mtime"], "title": title,
                              "catalog": catalog_match(row["file"], catalog), "v": DOWNLOADS_CACHE_V,
                              "maps": maps_signature()}
        changed = True
        if say:
            say("read %s: %s" % (row["file"], title or "no map fits it"))
    if changed:
        # what is gone from the folder leaves the cache
        keep = {r["path"] for r in downloads_in(tables_dir, cache)}
        cache = {k: v for k, v in cache.items() if k in keep or not k.startswith(tables_dir)}
        _save_downloads_cache(cache)
    return downloads_in(tables_dir, cache)


def link_downloads(rows, downloads):
    """A known table's row gets `download`: the folder's download its map
    fits (its Patch then takes the file without asking)."""
    by_title = {}
    for d in downloads:
        if d["read"] and d["title"]:
            by_title.setdefault(d["title"], d["path"])
    for row in rows:
        row["download"] = next((by_title[t] for t in row.get("titles") or [] if t in by_title), "")
    return rows


#: a scripted tribute's bridge names it on Controller; a ROM table's patcher
#: on its own cGameName (a tribute's cGameName is the table's, "bond")
GAMENAME_RES = (re.compile(r'^\s*Controller\.GameName\s*=\s*"([^"]+)"', re.M),
                re.compile(r'^\s*Const\s+cGameName\s*=\s*"([^"]+)"', re.M | re.I))


def patched_title(tables_dir, out_name):
    """The title a (PAD) table was patched for, from the script every patcher
    writes beside it (`<name>.script.vbs`): an earlier patch may be for another
    model than Patch takes now (PAD-900: Bond's table, patched for the LE
    before the Pro map). "" when the script is not there or names none; a
    name that is none of the row's titles is the table's own, not a model."""
    try:
        text = open(os.path.join(tables_dir, out_name[:-4] + ".script.vbs"),
                    encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    for rx in GAMENAME_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return ""


def missed_fixes(tables_dir, out_name, marks):
    """PAD-939: the fixes a (PAD) table was patched before. A map's `repatch`
    lists {"old": a line only an earlier patcher wrote, "why": what patching
    again mends} (The Beatles' six-ball trough, PAD-933); the script written
    beside the table is read for them. The `why` of each one found."""
    if not marks:
        return []
    try:
        text = open(os.path.join(tables_dir, out_name[:-4] + ".script.vbs"),
                    encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    squash = lambda t: re.sub(r"\s+", " ", t).lower()      # noqa: E731
    text = squash(text)
    return [k["why"] for k in marks if squash(k.get("old", "")).strip() in text and k.get("old")]


def patched_from(tables_dir, out_name):
    """The download a (PAD) table was patched from (padvpx.remember_patch,
    PAD-939), while it is still there: Patch again runs on it. "" when the
    table was patched before the record or the download moved."""
    try:
        src = json.load(open(os.path.join(tables_dir, out_name[:-4] + ".patch.json"),
                             encoding="utf-8")).get("source") or ""
    except (OSError, ValueError, AttributeError):
        return ""
    return src if os.path.isfile(src) else ""


#: (PAD) tables an earlier release patched whose map the kit no longer has
#: (PAD-860: marty's "Jurassic Park Limited Edition" is not the real JP's
#: playfield; JPSalas & marty's "Jurassic Park Pro Le" took its place,
#: PAD-887). A copy left in the tables folder is neither listed nor opened.
#: The value is the table to patch in its place.
DROPPED = {"Jurassic Park Limited Edition (PAD).vpx": "JPSalas & marty's Jurassic Park Pro Le 4.02"}


def patched_in(tables_dir):
    """The (PAD) tables in a tables folder: what can be opened."""
    if not tables_dir or not os.path.isdir(tables_dir):
        return []
    return sorted(f for f in os.listdir(tables_dir) if f.lower().endswith(".vpx") and "(PAD)" in f
                  and f not in DROPPED)


#: PAD-927: the name on the page's layout buttons
LAYOUT_SHORT = {"side": "Side by side", "two": "Two screens", "centre": "Centred"}


def layout_presets(mons):
    """Window layouts for the monitors found: (key, words, player rect, lcd rect)."""
    out = []
    if not mons:
        mons = [(0, 0, 1920, 1080)]
    l, t, r, b = mons[0]
    w, h = r - l, b - t
    pw = int(h * 2 / 3)                                  # a playfield is 2:3
    lw = w - pw
    out.append(("side", "Playfield on the main screen, full height on the left; the LCD on the right",
                (l, t, pw, h), (l + pw, t, lw, int(lw * 9 / 16))))
    if len(mons) > 1:
        l2, t2, r2, b2 = mons[1]
        out.append(("two", "Playfield fills the main screen; the LCD fills the second screen",
                    (l, t, int(h * 2 / 3), h), (l2, t2, r2 - l2, b2 - t2)))
    out.append(("centre", "Playfield in the middle at Visual Pinball's own size; the LCD on top, upper middle",
                None, None))
    return out


def layout_key(kit, presets):
    """Which preset the kit's saved player / lcd rectangles are, or ""."""
    player, lcd = kit.get("player"), kit.get("lcd")
    for key, _, p, q in presets:
        want_p = {"x": p[0], "y": p[1], "w": p[2], "h": p[3]} if p else None
        want_q = dict({"x": q[0], "y": q[1], "w": q[2], "h": q[3]}, topmost=True) if q else {"topmost": True}
        if player == want_p and lcd == want_q:
            return key
    return ""


def apply_layout(key, player, lcd):
    """player / lcd: [x, y, w, h] or None (Visual Pinball's own place, the
    LCD's default). Visual Pinball's ini gets the player size."""
    d = padlaunch.kit_load()
    if player:
        x, y, w, h = [int(v) for v in player]
        d["player"] = {"x": x, "y": y, "w": w, "h": h}
        padvpx.vpx_ini_set({"FullScreen": "0", "Width": str(w), "Height": str(h)})
    else:
        d.pop("player", None)
        padvpx.vpx_ini_set({"FullScreen": "0"})
    if lcd:
        x, y, w, h = [int(v) for v in lcd]
        d["lcd"] = {"x": x, "y": y, "w": w, "h": h, "topmost": True}
    else:
        d["lcd"] = {"topmost": True}
    padlaunch.kit_save(d)
    # PAD-811: the game's renderer places its own window from the display
    # setting, live; CONF named here so a test can point it elsewhere
    padisplay.save(display_for(lcd, padisplay.monitors()), padisplay.CONF)
    return "layout %s saved" % key


def display_for(lcd, mons):
    """The display setting (padisplay) for an LCD rectangle: full screen on a
    monitor it fills, else a borderless window on the monitor holding its
    middle (the main one when none does); no rectangle is free, the kit's
    own place for it."""
    if not lcd:
        return {"mode": "free", "monitor": 1, "border": True}
    x, y, w, h = [int(v) for v in lcd]
    for m in mons:
        if (m["x"], m["y"], m["w"], m["h"]) == (x, y, w, h):
            return {"mode": "fullscreen", "monitor": m["n"], "border": False}
    cx, cy = x + w // 2, y + h // 2
    mon = next((m for m in mons if m["x"] <= cx < m["x"] + m["w"]
                and m["y"] <= cy < m["y"] + m["h"]), mons[0])
    return {"mode": "window", "monitor": mon["n"], "border": False,
            "rx": x - mon["x"], "ry": y - mon["y"], "w": w, "h": h}


def download_vpx(folder, say=print, progress=None):
    folder = folder or VPX_DEFAULT_DIR
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, "vpx-release.zip")
    say("Downloading Visual Pinball 10.8.0 (37 MB)...")

    def hook(n, bs, total):
        if total > 0 and progress:
            progress(min(1.0, n * bs / total))
    urllib.request.urlretrieve(VPX_URL, tmp, hook)
    say("Unpacking into %s" % folder)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(folder)
    os.remove(tmp)
    # the release zip may wrap everything in one folder
    if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
        for sub in os.listdir(folder):
            if os.path.isfile(os.path.join(folder, sub, "VPinballX64.exe")):
                for f in os.listdir(os.path.join(folder, sub)):
                    shutil.move(os.path.join(folder, sub, f), folder)
                os.rmdir(os.path.join(folder, sub))
                break
    os.makedirs(os.path.join(folder, "tables"), exist_ok=True)
    return set_vpx(folder)


CATALOG = os.path.join(HERE, "catalog.json")


def load_catalog():
    """The kit's survey of the Visual Pinball tables of every platform PAD
    reads (catalog.json, PAD-943): {"platforms": {...}, "tables": [...]},
    or empty when the file is not there."""
    try:
        d = json.load(open(CATALOG, encoding="utf-8"))
    except (OSError, ValueError):
        return {"platforms": {}, "tables": []}
    return {"platforms": d.get("platforms") or {}, "tables": d.get("tables") or []}


def refresh_system_script(tables):
    """A patch copies PADSPIKE2.vbs beside the table, and the table loads that
    copy: one an older release left there is brought up to this kit's, so a
    table patched before a fix to it (PAD-852: the backglass) has the fix
    without patching it again. Returns whether it was replaced."""
    ours = os.path.join(HERE, "PADSPIKE2.vbs")
    there = os.path.join(tables, "PADSPIKE2.vbs")
    try:
        if not os.path.isfile(there) or open(there, "rb").read() == open(ours, "rb").read():
            return False
        shutil.copyfile(ours, there)
        return True
    except OSError:
        return False


#: What Play says when VPinballX64.exe cannot start: it imports XINPUT1_3.dll,
#: which is not part of Windows but of Microsoft's DirectX End-User Runtime
#: (June 2010). Without it Windows stops the launch with a "system error" box
#: naming the DLL, and nothing here said why (PAD-882).
NO_DIRECTX = ("Visual Pinball cannot start on this PC: XINPUT1_3.dll is missing. "
              "It comes with Microsoft's DirectX End-User Runtime (June 2010): "
              "install that, then press Play again.")


def missing_directx(vpx):
    """NO_DIRECTX when VPinballX64.exe would not find XINPUT1_3.dll (in its
    own folder or Windows' 64-bit system folder), else "". Off Windows, or
    when the system folder cannot be told, nothing is refused.
    PAD_VPX_SYSDIR names the system folder instead (the proof shots: a PC
    without the DLL, with no Visual Pinball started)."""
    if sys.platform != "win32":
        return ""
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or ""
    # a 32-bit Python sees System32 as SysWOW64; Sysnative is the real one
    sysdirs = ([os.environ["PAD_VPX_SYSDIR"]] if os.environ.get("PAD_VPX_SYSDIR")
               else [os.path.join(root, "Sysnative"), os.path.join(root, "System32")] if root
               else [])
    sysdir = next((d for d in sysdirs if os.path.isdir(d)), None)
    if sysdir is None:
        return ""
    for d in (vpx, sysdir):
        if os.path.isfile(os.path.join(d, "xinput1_3.dll")):
            return ""
    return NO_DIRECTX


def open_table(name):
    vpx = find_vpx()
    if not vpx:
        return "Visual Pinball is not set up."
    if name in DROPPED:
        return "%s is no longer supported: patch %s instead." % (name, DROPPED[name])
    tables = vpx_tables_dir()
    path = os.path.join(tables, name)
    if not os.path.isfile(path):
        return "There is no %s in %s." % (name, tables)
    # no Linux, no game: say so here, not from inside the opened table
    why = padlaunch.no_linux(padlaunch.distro())
    if why:
        return why
    why = missing_directx(vpx)
    if why:
        return why
    refresh_system_script(tables)
    # PAD-858: a table patched before the patchers muted its soundtrack
    # loses it here, once; a table Visual Pinball holds open stays as it is
    try:
        import vpxsounds
        vpxsounds.quiet_in_place(path)
    except (OSError, ValueError):
        pass
    # PAD-882: and one patched before the service keys gets them, once
    try:
        import vpxshadow
        vpxshadow.service_keys_in_place(path)
    except Exception:                                       # noqa: BLE001  never in Play's way
        pass
    subprocess.Popen([os.path.join(vpx, "VPinballX64.exe"), "-play", path], cwd=vpx)
    return "ok"


def open_download(path):
    """PAD-952: one of the person's downloads in the tables folder (or a
    folder in it), opened as it is - a table whose real game cannot run on
    this PC (TNA, America's Most Haunted) plays its author's rules. The file
    is never changed: no muting, no keys."""
    vpx = find_vpx()
    if not vpx:
        return "Visual Pinball is not set up."
    tables = vpx_tables_dir()
    full = os.path.normcase(os.path.abspath(path or ""))
    if not tables or full not in {os.path.normcase(os.path.abspath(p)) for _, p in download_files(tables)}:
        return "%s is not one of the downloads in %s." % (path, tables or "the tables folder")
    why = missing_directx(vpx)
    if why:
        return why
    subprocess.Popen([os.path.join(vpx, "VPinballX64.exe"), "-play", path], cwd=vpx)
    return "ok"


def state():
    kit = padlaunch.kit_load()
    lib = os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or ""
    try:
        import padcontroller
        padcontroller.dpi_aware()
        mons = padcontroller.monitors()
    except Exception:                                       # noqa: BLE001
        mons = []
    presets = layout_presets(mons)
    tables = vpx_tables_dir()
    shown = padisplay.load(padisplay.CONF)
    vpx = find_vpx()
    have = vpx_version(vpx)
    registered, reg_path = controller_registration()
    return {
        "registered": registered,
        # PAD-943: registered, but to another copy of the app (a checkout or
        # an older install): its tables would call that one
        "registered_to": reg_path,
        "registered_here": registered and registered_here(reg_path),
        "vpx": vpx,
        # PAD-887: the minimum shown beside the Visual Pinball line, and an
        # older copy is "Needed", not "Ready" (unread: taken as fine)
        "vpx_min": dotted(VPX_MIN),
        "vpx_version": dotted(have),
        "vpx_old": bool(have) and have < VPX_MIN,
        "tables_dir": tables,
        "tables_own": bool(kit.get("tables")) and tables == kit.get("tables"),
        "library": lib,
        "cards": all_cards(lib, kit),
        "tables": link_downloads(known_tables(tables), downloads_in(tables)),
        "patched": patched_in(tables),
        # PAD-943: the person's own downloads in the folder, listed at once
        "downloads": downloads_in(tables),
        # PAD-943: every platform's tables, where their authors put them
        "catalog": load_catalog(),
        "monitors": len(mons),
        # PAD-927: the page's buttons carry the short name, the words its tip
        "presets": [{"key": k, "words": w, "short": LAYOUT_SHORT.get(k, k), "player": p, "lcd": q}
                    for k, w, p, q in presets],
        "layout": layout_key(kit, presets),
        # PAD-811: where the game's screen goes, as the layout or the
        # Emulate tab last set it
        "display": {"setting": shown, "text": padisplay.describe(shown)},
    }


def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "state":
        out = state()
    elif cmd == "vpx" and len(rest) == 1:
        out = {"result": set_vpx(rest[0])}
    elif cmd == "library" and len(rest) == 1:
        out = {"result": "ok", "cards": set_library(os.path.abspath(rest[0]))}
    elif cmd == "layout" and len(rest) == 3:
        out = {"result": apply_layout(rest[0], json.loads(rest[1]), json.loads(rest[2]))}
    elif cmd == "downloads":
        # PAD-943: read the downloads in the tables folder (or the one given)
        tables = rest[0] if rest else vpx_tables_dir()
        out = {"downloads": read_downloads(tables, say=lambda m: print("say " + m, flush=True)),
               "tables": link_downloads(known_tables(tables), downloads_in(tables))}
    elif cmd == "download" and len(rest) == 1:
        def prog(f):
            print("progress %.3f" % f, flush=True)
        try:
            out = {"result": download_vpx(rest[0], say=lambda m: print("say " + m, flush=True),
                                          progress=prog)}
        except Exception as exc:                            # noqa: BLE001
            out = {"result": "The download did not finish: %s" % exc}
    elif cmd == "tables" and len(rest) <= 1:
        folder = os.path.abspath(rest[0]) if rest and rest[0] else ""
        out = {"result": set_tables(folder), "patched": patched_in(vpx_tables_dir())}
    elif cmd == "open" and len(rest) == 1:
        out = {"result": open_table(rest[0])}
    elif cmd == "open_download" and len(rest) == 1:
        out = {"result": open_download(rest[0])}
    else:
        print(__doc__)
        return 2
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
