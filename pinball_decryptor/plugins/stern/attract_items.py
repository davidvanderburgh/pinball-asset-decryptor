"""THE ATTRACT MODE EDITOR (PAD-782): an owner's own items between the game's attract screens (Stern Spike 2).

The attract mode of a Spike 2 game is a table of pages its sequencer shows one after another (:mod:`.portattract`):
the last scores, PRESS START, the high scores and champions, the tutorial clips, the logos. A project adds items of
its own between them - photos (one item each, a slideshow when several follow each other), a clip, a text card -
each after (or before) one of the game's pages, each with how long it stays on the glass.

The project records them (``attract_items`` in ``.staged_changes.json``)::

    {"items": [{"kind": "photo" | "clip" | "text", "file": path, "text": "line\\nline",
                "seconds": 0..120 (0: a clip's own length), "entry": <the game page's number>,
                "where": "after" | "before"}, ...],
     "champions": true}          # false: the modes' challenge champions (PAD-660/663) are not shown in attract

and a Write (or a run in the emulator) makes every item a clip of the title's video bank - a photo or a text card a still clip of
its time at the screen's size, a video converted as a slot's replacement is, the project's colour profile applied,
never cut to a slot's length - added under ``PadAttract<k>``, and writes ``attract.cfg`` beside the mode runtime.
The runtime (pad_mode_runtime.c "attract items") plays them between the pages. A card with attract items carries the
mode runtime's whole gate: like a card of modes, it keeps scores off Insider Connected.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass, field

#: the project sidecar's key
STAGED_KEY = "attract_items"
#: items a card may carry (pad_mode_runtime.c AIT_ITEMS) and game pages that may take them (AIT_ANCHORS)
MAX_ITEMS = 48
MAX_PAGES = 16
#: an item's time on the glass, seconds
MAX_SECONDS = 120
DEFAULT_SECONDS = {"photo": 5, "text": 5, "clip": 0}
KINDS = ("photo", "clip", "text")
#: the runtime's file, beside mode.so
CFG_NAME = "attract.cfg"
#: an item's clip in the video bank (k = its number, 1..)
CLIP_NAME = "PadAttract%d"
#: a text card's lines, at most
TEXT_LINES = 4
PHOTO_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg")
CACHE_DIR = os.path.join(".write_cache", "attract_items")
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot add to its attract screens. Extract "
            "the project from a card again and try once more.")
NOT_SPIKE2 = "Only a Stern Spike 2 game's attract screens can take items of your own."
NO_TABLE = ("%s starts its attract screens in a way the app cannot add to yet, so this game's attract screens cannot "
            "take items of your own.")
NO_CLIPS = ("%s plays its clips in a way the app cannot use, so this game's attract screens cannot take items of your "
            "own.")
#: PAD-782 library sweep: on the titles whose clips play on the video bank's surface the attract mode never draws that
#: surface (an item held the cycle but the glass kept the screen before it). Items go only where a route puts them on
#: the glass: the game's own clip call (Godzilla, Jaws, King Kong) or the attract pages' video element (James Bond).
NO_GLASS = ("%s shows its attract clips in a way the app cannot put your items through yet, so this game's attract "
            "screens cannot take items of your own.")
#: the gate, said on the page, in the Write log and in the help
INSIDER_WORDS = ("A card with attract items of your own keeps its scores off Insider Connected: they stay on the "
                 "machine.")


class AttractError(ValueError):
    """An item that cannot be made, or a build that cannot carry them."""


# ---- the record ------------------------------------------------------------------------------------------------
@dataclass
class Item:
    kind: str
    entry: int
    where: str = "after"
    file: str = ""
    text: str = ""
    seconds: int = 0

    def as_dict(self):
        d = {"kind": self.kind, "entry": self.entry, "where": self.where, "seconds": self.seconds}
        if self.kind == "text":
            d["text"] = self.text
        else:
            d["file"] = self.file
        return d

    def label(self):
        if self.kind == "text":
            return "Text: %s" % " / ".join(l for l in self.text.splitlines() if l.strip())
        return "%s: %s" % ("Photo" if self.kind == "photo" else "Clip", os.path.basename(self.file))


@dataclass
class Record:
    items: list = field(default_factory=list)
    champions: bool = True

    def as_dict(self):
        return {"items": [i.as_dict() for i in self.items], "champions": bool(self.champions)}

    def empty(self):
        return not self.items and self.champions


def clean_seconds(v, kind):
    try:
        s = int(round(float(v)))
    except (TypeError, ValueError):
        s = DEFAULT_SECONDS.get(kind, 5)
    lo = 0 if kind == "clip" else 1
    return max(lo, min(MAX_SECONDS, s))


def clean_text(t):
    lines = [l.strip()[:40] for l in str(t or "").replace("\r", "").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines[:TEXT_LINES])


def clean(raw):
    """A :class:`Record` from a sidecar's value: unknown kinds, items with nothing to show and items past
    :data:`MAX_ITEMS` dropped."""
    rec = Record()
    if not isinstance(raw, dict):
        return rec
    rec.champions = raw.get("champions", True) is not False
    for d in raw.get("items") or ():
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            continue
        kind = d["kind"]
        try:
            entry = int(d.get("entry", 0))
        except (TypeError, ValueError):
            continue
        it = Item(kind=kind, entry=max(0, entry), where="before" if d.get("where") == "before" else "after",
                  seconds=clean_seconds(d.get("seconds", DEFAULT_SECONDS[kind]), kind))
        if kind == "text":
            it.text = clean_text(d.get("text"))
            if not it.text:
                continue
        else:
            it.file = str(d.get("file") or "").strip()
            if not it.file:
                continue
        rec.items.append(it)
        if len(rec.items) >= MAX_ITEMS:
            break
    return rec


def load(project):
    if not project:
        return Record()
    from ...core import staged_changes
    try:
        return clean(staged_changes.load(project).get(STAGED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return Record()


def save(project, rec):
    from ...core import staged_changes
    side = staged_changes.load(project)
    if rec.empty():
        side.pop(STAGED_KEY, None)
    else:
        side[STAGED_KEY] = rec.as_dict()
    staged_changes.save(project, side)


def wanted(project):
    """Whether the project asks anything of the attract mode (an item, or the champions off)."""
    return not load(project).empty()


# ---- the title -------------------------------------------------------------------------------------------------
def port_table(prof):
    """``{"table", "size", "page_at", "count", "sleep"}`` from ``prof``'s port, or None."""
    from . import mode_project as MP
    if prof is None or not getattr(prof, "port", None):
        return None
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return None
    data, values, sites = port["data"], port["value"], port["site"]
    if not data.get("attract_table") or "attract_sleep" not in sites:
        return None
    return {"table": data["attract_table"], "size": int(values.get("attract_entry_size", 0)),
            "video_clip": (port.get("text") or {}).get("attract_video_clip", "") if data.get("attract_video") else "",
            "page_at": int(values.get("attract_page_at", 4)), "count": int(values.get("attract_count", 0))}


def title_refusal(prof):
    """Why ``prof``'s attract mode cannot take items, or ``""``."""
    from . import clip_variants as CV
    if prof is None:
        return NO_TITLE
    t = port_table(prof)
    if t is None or t["size"] not in (8, 12, 16) or not 2 <= t["count"] <= 256:
        return NO_TABLE % prof.label
    route = CV.route_of(prof)
    if not route:
        return NO_CLIPS % prof.label
    if route != "clip_play" and not t.get("video_clip"):
        return NO_GLASS % prof.label
    return ""


# ---- the game's pages ------------------------------------------------------------------------------------------
@dataclass
class Page:
    entry: int
    page: int
    test: int
    seconds: float = 0.0
    name: str = ""

    @property
    def sometimes(self):
        """The game shows it only at times (its entry has a test: after a game, with the setting on...)."""
        return bool(self.test)


def _strings_of(e, fn, limit=240):
    """C strings a function (and the functions it calls, one level) loads by movw/movt or a literal pool."""
    from .portchallenge import bl_target
    out = []

    def cstr(va):
        o = e.off(va) if va else None
        if o is None:
            return None
        end = e.d.find(b"\0", o, o + 120)
        b = e.d[o:end] if end > o else b""
        if len(b) < 4 or not all(32 <= c < 127 for c in b):
            return None
        return b.decode()

    def scan(start, depth):
        k = (start - e.text_va) // 4
        w = e.words
        if not 0 <= k < len(w):
            return
        lo = {}
        for i in range(k, min(len(w), k + limit)):
            x = w[i]
            if x & 0xFFF00000 == 0xE3000000:
                lo[x >> 12 & 15] = (x >> 4 & 0xF000) | (x & 0xFFF)
            elif x & 0xFFF00000 == 0xE3400000 and (x >> 12 & 15) in lo:
                s = cstr(lo.pop(x >> 12 & 15) | ((x >> 4 & 0xF000) | (x & 0xFFF)) << 16)
                if s:
                    out.append(s)
            elif x & 0xFFFF0000 == 0xE59F0000:                  # ldr rX, [pc, #imm]
                lit = e.text_va + 4 * i + 8 + (x & 0xFFF)
                if e.off(lit) is not None:
                    s = cstr(e.word(lit))
                    if s:
                        out.append(s)
            elif depth and bl_target(e.text_va + 4 * i, x) is not None:
                scan(bl_target(e.text_va + 4 * i, x), depth - 1)
            if x & 0xFFFF8000 == 0xE8BD8000 or x == 0xE12FFF1E:  # pop {.., pc} / bx lr
                break

    scan(fn, 1)
    return out


def _nice(s):
    """A program's name for a thing in words: its first dotted part, CamelCase and underscores split."""
    import re
    s = s.split(".")[0].replace("_", " ").strip()
    s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s[:1].upper() + s[1:] if s else s


def _page_name(e, page, champion_fns, clip_names):
    """A few words saying what a page of the game's shows."""
    from .portchallenge import bl_target
    if page in champion_fns:
        return "High score / champion page"
    k = (page - e.text_va) // 4
    if 0 <= k < len(e.words):
        for i in range(k, min(len(e.words), k + 400)):
            t = bl_target(e.text_va + 4 * i, e.words[i])
            if t is not None and t in champion_fns:
                return "High score / champion page"
            if e.words[i] & 0xFFFF8000 == 0xE8BD8000:
                break
    strings = _strings_of(e, page)
    for s in strings:
        if s in clip_names:
            return "Clip: %s" % _nice(s)
    for s in strings:
        if " " not in s and any(c.isalpha() for c in s) and len(s) <= 64 and not s.startswith("/") \
                and not _generic(s):
            return _nice(s)
    return ""


#: names a page's program uses for its parts that say nothing of what it shows
_GENERIC = {"videosurface", "line1", "line2", "line3", "text", "text2", "textbox", "background", "instance"}


def _generic(s):
    import re
    head = s.split(".")[0]
    return (head.lower() in _GENERIC or re.fullmatch(r"[0-9a-f]{16,}", head) is not None
            or re.fullmatch(r"(?i)line\d+", head) is not None)


def read_pages(elf_bytes, prof, clip_names=()):
    """The game's attract pages in table order (:class:`Page`), read off its program with ``prof``'s port lines."""
    from . import mode_project as MP
    from .portchallenge import Elf
    t = port_table(prof)
    if t is None:
        return []
    e = Elf(elf_bytes)
    try:
        sites = MP.read_port(MP.port_path(prof))["site"]
    except (OSError, MP.ModeProjectError):
        sites = {}
    champion_fns = set()
    for name, s in sites.items():
        if name.startswith("challenge_pages_") or name in ("challenge_page", "challenge_list_page",
                                                            "challenge_score_entry"):
            addr = s[0] if isinstance(s, (tuple, list)) else s
            if isinstance(addr, int):
                champion_fns |= {addr, addr - 4}
    names = set(clip_names or ())
    out = []
    for k in range(t["count"]):
        va = t["table"] + t["size"] * k
        if e.off(va + t["size"] - 1) is None:
            break
        test, page = e.word(va), e.word(va + t["page_at"])
        secs = 0.0
        if t["size"] > 8:
            secs = struct.unpack("<f", struct.pack("<I", e.word(va + 8)))[0]
        p = Page(entry=k, page=page, test=test, seconds=secs if 0 < secs < 600 else 0.0)
        p.name = _page_name(e, page, champion_fns, names) or "Game screen %d" % (k + 1)
        out.append(p)
    return out


NO_BANK = ("%s keeps its clips in a way the app cannot add to yet, so this game's attract screens cannot take "
           "items of your own.")


def _bank_refusal(card, prof):
    """Why the scene the items' clips go into (the attract video element's own on a clip v2 title, else the video
    bank) cannot take them on ``card``, or ``""``."""
    from . import engine as E, mode_write as MW, video_bank as VB
    from . import clip_variants as CV
    clip = (port_table(prof) or {}).get("video_clip") or ""
    try:
        with open(card, "rb") as f:
            reader, _fw, _img = E._locate(f, E._linux_partitions(card))
            scene = element_scene(reader, prof.game_dir, clip) if clip else CV.bank_scene(prof)
            node = MW.lookup(reader, scene) if scene else None
            if node is None:
                return NO_BANK % prof.label
            VB.parse_scene(bytes(reader.read_file_bytes(node)))
    except VB.VideoBankError:
        return NO_BANK % prof.label
    except Exception:                                   # noqa: BLE001 - an unreadable card: the build says
        return ""
    return ""


def project_refusal(project, prof=None):
    """Why the card this project was made from cannot take attract items (read with :func:`project_pages`, cached
    with them), or ``""``."""
    project_pages(project, prof)
    return _CARD_WHY.get(os.path.abspath(project), "")


_CARD_WHY = {}


def project_pages(project, prof=None):
    """The game's attract pages for a project, read from the card it was extracted from (cached by the program's
    hash in the title cache), or ``[]`` when the card is not on this PC. Whether the card's clip scene can take the
    items is read with them (:func:`project_refusal`)."""
    import hashlib
    import json
    from . import mode_project as MP, title_reader as TR, clip_variants as CV
    prof = prof or CV.project_title(project)
    if prof is None:
        return []
    got = MP.project_card(project)
    card = getattr(got, "image", "") if got is not None else ""
    if not card or not os.path.isfile(card):
        return []
    cache = os.path.join(TR.cache_dir("attract"), "%s.json" % CV.title_key(prof))
    key = "%s|%d|%d" % (card, os.path.getsize(card), int(os.path.getmtime(card)))
    try:
        with open(cache, encoding="utf-8") as f:
            got = json.load(f)
        if got.get("key") == key and got.get("v") == 2:
            _CARD_WHY[os.path.abspath(project)] = got.get("why", "")
            return [Page(**p) for p in got["pages"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        _g, _v, elf = TR.game_program(card)
    except Exception:                                   # noqa: BLE001 - no card, no names
        return []
    names = {os.path.splitext(os.path.basename(r))[0] for r in CV.manifest(project)}
    names |= {n.split("_", 1)[-1] for n in names}
    pages = read_pages(elf, prof, names)
    why = _bank_refusal(card, prof) if pages else ""
    _CARD_WHY[os.path.abspath(project)] = why
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"v": 2, "key": key, "sha1": hashlib.sha1(elf).hexdigest(), "why": why,
                       "pages": [p.__dict__ for p in pages]}, f)
    except OSError:
        pass
    return pages


# ---- making the clips ------------------------------------------------------------------------------------------
def reference_slot(project, prof):
    """``(slot rel, info)``: the bank clip of the project whose picture is the biggest - the format every item is
    made into - or ``(None, None)``."""
    from . import clip_variants as CV
    from ...core.video import detect_video_info
    best = (None, None, 0)
    bank = CV.bank_assets(prof)
    for rel, card in sorted(CV.manifest(project).items()):
        if not card.startswith(bank):
            continue
        path = os.path.join(project, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        info = detect_video_info(path)
        if not info:
            continue
        area = int(getattr(info, "width", 0) or 0) * int(getattr(info, "height", 0) or 0)
        if area > best[2]:
            best = (rel, info, area)
        if area >= 1360 * 768:
            break
    return best[0], best[1]


def _ffmpeg():
    from ...core.audio import find_ffmpeg
    f = find_ffmpeg()
    if not f:
        raise AttractError("ffmpeg was not found, so the attract items cannot be made into clips")
    return f


def text_card(text, out_png, w, h):
    """A text card: the lines centred, white on black, as big as fit."""
    from PIL import Image, ImageDraw
    from .mode_assets import _fit_font
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = [l for l in clean_text(text).split("\n")] or [" "]
    size = int(h / (len(lines) + 1.2))
    font = min((_fit_font(d, l or " ", int(w * 0.9), size) for l in lines), key=lambda f: f.size)
    lh = int(font.size * 1.25)
    y = (h - lh * len(lines)) // 2
    for l in lines:
        tw = d.textlength(l, font=font)
        d.text(((w - tw) / 2, y), l, font=font, fill=(255, 255, 255))
        y += lh
    img.save(out_png)
    return out_png


def still_clip(image, seconds, out, w, h, ffmpeg=None):
    """A still picture as a clip of ``seconds`` at ``w`` x ``h`` (fitted, black bars), 30 frames a second."""
    ff = ffmpeg or _ffmpeg()
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
          % (w, h, w, h))
    cmd = [ff, "-y", "-v", "error", "-loop", "1", "-i", image, "-t", "%d" % seconds, "-r", "30", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", out]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if r.returncode or not os.path.isfile(out):
        raise AttractError("%s could not be made into a clip: %s" % (os.path.basename(image),
                                                                      (r.stderr or "").strip()[-200:]))
    return out


def clip_seconds(path):
    from ...core.video import detect_video_info
    info = detect_video_info(path)
    d = float(getattr(info, "duration", 0) or 0) if info else 0.0
    return d


def _stage(project, rel, info, src, out, cancel=None):
    """``src`` made into slot ``rel``'s format (as its replacement would be: the project's colour profile, never cut
    to the slot's length) at ``out``."""
    from ...core import video_slots as VS
    from ...core import staged_originals
    pristine = staged_originals.snapshot_path(project, rel) or os.path.join(project, *rel.split("/"))
    ext = os.path.splitext(pristine)[1].lower()
    try:
        from ...core import colour_profile
        colour = colour_profile.active(project)
    except Exception:                                   # noqa: BLE001 - no profile then
        colour = None
    target = VS.VideoSlot(rel_path="%s#attract" % rel, abs_path=out, ext=ext, info=info,
                          size=os.path.getsize(pristine), probed=True)
    ok, detail = VS.stage_replacement(target, src, trim_to_length=False, no_conversion=False, cancel_cb=cancel,
                                      match_bitrate=VS._clip_bitrate(pristine),
                                      **({"colour": colour} if colour is not None else {}))
    if not ok:
        raise AttractError("%s could not be made into the game's clip format: %s" % (os.path.basename(src), detail))
    return out


@dataclass
class AttractBuild:
    bank: bytes                 # the scene the clips went into, rewritten (``scene``: its card path)
    new: list
    cfg: str
    lines: list
    items: list
    scene: str = ""


def cfg_text(entries, champions=True):
    """``attract.cfg``: ``entries`` = ``[(entry, where, clip name, ms), ...]`` in play order."""
    out = ["# PAD-782: the owner's attract items (pad_mode_runtime.c attract items)"]
    if not champions:
        out.append("champions off")
    out += ["item %d %s %s %d" % (e, w, n, ms) for e, w, n, ms in entries]
    return "\n".join(out) + "\n"


def element_scene(reader, game_dir, clip):
    """The card path (no leading slash) of the scene whose video library holds ``clip``: the attract video element's
    own scene on a clip v2 title, or None. Reads every scene of the game until one has it."""
    from . import video_bank as VB
    tag = struct.pack("<Q", len(clip)) + clip.encode("latin1")
    top = "/%s/assets/lcd/" % game_dir
    for path, _ino, node in reader.iter_regular_files(max_depth=12):
        if not path.endswith("/scene.radium") or not ("/" + path.lstrip("/")).startswith(top):
            continue
        raw = bytes(reader.read_file_bytes(node))
        if tag not in raw:
            continue
        try:
            if any(c.name == clip for c in VB.parse_scene(raw).library.entries):
                return path.lstrip("/")
        except VB.VideoBankError:
            continue
    return None


def build(project, prof, bank, out_dir, log=None, progress=None, cancel=None, rec=None, pages=None,
          read_card=None, find_scene=None):
    """Every item made into a clip and added to ``bank`` (the title's bank scene, as the build has it so far), each
    clip copied to its card path under ``out_dir``, ``attract.cfg`` written there. None when the project asks
    nothing of the attract mode. Raises :class:`AttractError`."""
    from . import clip_variants as CV
    from . import video_bank as VB
    log = log or (lambda *a, **k: None)
    rec = load(project) if rec is None else rec
    if rec.empty():
        return None
    why = title_refusal(prof)
    if why:
        raise AttractError(why)
    count = port_table(prof)["count"]
    items = [i for i in rec.items if i.entry < count]
    for i in rec.items:
        if i.entry >= count:
            log("Attract items: %s is left out: the game has no screen %d" % (i.label(), i.entry + 1), "warning")
    gone = [i for i in items if i.kind != "text" and not os.path.isfile(i.file)]
    for i in gone:
        log("Attract items: %s is left out: the file is not on this PC any more" % i.label(), "warning")
    items = [i for i in items if i not in gone]
    anchors = []
    for i in items:
        if i.entry not in anchors:
            anchors.append(i.entry)
    if len(anchors) > MAX_PAGES:
        raise AttractError("items follow %d of the game's screens; a card can carry items around %d"
                           % (len(anchors), MAX_PAGES))
    os.makedirs(out_dir, exist_ok=True)
    data = bank
    scene = CV.bank_scene(prof)
    clip = port_table(prof).get("video_clip") or ""
    if clip and items:
        # clip v2: the attract pages' own video element plays the items, from its own scene's library
        scene = find_scene(clip) if find_scene is not None else None
        data = read_card(scene) if scene and read_card is not None else None
        if not data:
            raise AttractError("the scene the game's attract clips play from (the one holding %s) was not found on "
                               "the card" % clip)
    new, entries, lines = [], [], []
    if items:
        rel, info = reference_slot(project, prof)
        if rel is None:
            raise AttractError("the project has none of the game's clips to make the attract items like (extract "
                               "its videos first)")
        w, h = int(info.width), int(info.height)
        try:
            parsed = VB.parse_scene(data)
        except VB.VideoBankError as e:
            raise AttractError("the game's video bank could not be read (%s)" % e) from None
        taken = {c.name for c in parsed.library.entries}
        work = os.path.join(project, CACHE_DIR)
        os.makedirs(work, exist_ok=True)
        assets = scene[:-len("scene.radium")] + "scene.assets/"
        for k, it in enumerate(items, 1):
            if cancel is not None and cancel():
                raise AttractError("cancelled")
            if progress is not None:
                progress(k - 1, len(items), "Making attract item %d of %d..." % (k, len(items)))
            name = CLIP_NAME % k
            if name in taken:
                raise AttractError("the card being written already has attract items from an earlier build (its "
                                   "video bank has %s); write onto the card that build was made from" % name)
            src = it.file
            if it.kind == "text":
                src = text_card(it.text, os.path.join(work, "text%d.png" % k), w, h)
            if it.kind in ("text", "photo"):
                src = still_clip(src, it.seconds, os.path.join(work, "still%d.mp4" % k), w, h)
                ms = it.seconds * 1000
            else:
                own = clip_seconds(src)
                ms = int(1000 * (min(own, it.seconds) if it.seconds and own else own or it.seconds or 5))
                ms = max(500, min(MAX_SECONDS * 1000, ms))
            made = _stage(project, rel, info, src, os.path.join(work, "item%d%s" % (
                k, os.path.splitext(os.path.join(project, *rel.split("/")))[1].lower())), cancel=cancel)
            try:
                data, got = VB.add_clip(data, name, os.path.getsize(made))
            except VB.VideoBankError as e:
                raise AttractError("%s could not be added to the video bank (%s)" % (name, e)) from None
            taken.add(name)
            card = assets + got["path"]
            dst = os.path.join(out_dir, *card.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(made, dst)
            new.append((card, dst))
            entries.append((it.entry, it.where, name, ms))
            lines.append("attract item %d (%s, %.1f s) %s the game's screen %d"
                         % (k, it.label(), ms / 1000.0, it.where, it.entry + 1))
        if progress is not None:
            progress(len(items), len(items), "")
    if not rec.champions:
        lines.append("the modes' challenge champions are not shown in attract")
    cfg = os.path.join(out_dir, CFG_NAME)
    with open(cfg, "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg_text(entries, rec.champions))
    return AttractBuild(bank=data, new=new, cfg=cfg, lines=lines, items=items, scene=scene)
