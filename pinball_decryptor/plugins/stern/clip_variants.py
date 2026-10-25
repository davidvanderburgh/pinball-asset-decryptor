"""CLIP VARIANTS (PAD-446): one of the game's clips plays one of several, at random.

A tester rebuilding Godzilla asked: "Add a few slots for a single asset so the video could have
variation in-game." The Video tab gives a slot more clips than its own (``video_variants`` in the
project's ``.staged_changes.json``: ``{slot rel: [file, ...]}``), and a Write does three things:

1. each extra clip is made into the slot's own format, the conversion a replacement gets
   (:func:`core.video_slots.stage_replacement` against the slot's pristine clip, with the slot's
   length and conversion choices), and added to the title's in-game VIDEO BANK under a name of
   its own, ``<the game's name>__PadVar<k>`` (:func:`.video_bank.add_clip`), as a file the card
   never had;
2. ``clips.cfg`` lists, one TAB-separated line per slot, the game's name and the added ones;
3. the mode runtime (``mode.so``, preloaded into the game by ``/etc/init.d/game_monitor``) reads
   it and, every time the game asks for that clip by name, plays one of the line's clips at
   random, never the same one twice in a row (pad_mode_runtime.c "clip variants").

It rides the modes' delivery (:mod:`.mode_write`: the rewritten bank and the new clips are whole
files, the ``.sidx`` manifest gains a record per clip, p2 gets ``mode.so``, the port and
``clips.cfg``) but not the mode maker's preview switch, because nothing of a mode goes on a card
that only has variants. Its ``clips.cfg`` then starts with ``only``, and the runtime arms that
one hook and nothing else, so the card's scores still reach Insider Connected.

WHICH CLIPS. The bank's: the clips the game plays BY NAME (Godzilla: 598 of its 658, every mode,
battle and award clip). A clip a scene plays on its own (an attract loop, a background a scene's
own Video draws) never passes through the call the runtime hooks, so its slot is not offered. A
slot is offered when its card path is a file in the bank scene's ``scene.assets`` folder, on a
title whose port gives the runtime a way to hook the game's ask (:func:`hook_route`).

PAD-723: EVERY BANK, EVERY TITLE. Most titles keep their by-name clips in more than one bank scene,
and the port's ``video_bank`` is not always where they are (Venom Pro, Stranger Things Pro, The
Munsters, Rush, Metallica, Iron Maiden and Bond 60th name the HUD the modes graft their clips into,
and play theirs from 60ed7e50; The Beatles has three banks, John Wick two). On a clip v2 build a
slot also varies in any OTHER scene of the card that walks as a video bank (:mod:`.video_bank`,
read off the card: :func:`card_banks`); its ``clips.cfg`` line is ``sclip`` and names that scene,
and the runtime swaps the name only on that scene's VideoSurface. There is no per-build list: the
swap was seen on the glass in the emulator across the newest builds (the PAD-723 sweep,
``docs/plans/pad-723-random-clips-every-title.md``), and older and derived builds have it wherever
their port has the route.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, replace

#: the project sidecar's key: ``{slot rel: [file, ...]}``, the slot's clips beyond its own
STAGED_KEY = "video_variants"
#: clips a slot may have beyond its own (pad_mode_runtime.c CLIPV_PICKS - 1)
MAX_EXTRA = 15
#: slots a card may vary (pad_mode_runtime.c CLIPV_SLOTS)
MAX_SLOTS = 512
#: the runtime's table, beside mode.so on p2 (mode_install.py EXTRA_FILES)
CFG_NAME = "clips.cfg"
#: ``PAD_STERN_CLIP_VARIANTS=0`` leaves every slot's variants out of a build
GATE_ENV = "PAD_STERN_CLIP_VARIANTS"
#: what an added clip is called in the bank: the game's name and the variant's number (2 = the
#: first extra one, so the game's own clip is 1)
NAME_FORMAT = "%s__PadVar%d"
#: where the converted clips are kept between builds, in the project
CACHE_DIR = os.path.join(".write_cache", "video_variants")
CACHE_FILE = os.path.join(".write_cache", "video_variants.json")

#: why a slot cannot vary, as the tab's menu says it
NOT_STERN = "Only a Stern Spike 2 game can play one of several clips at random."
NO_TITLE = ("The app cannot tell which game this project is for, so it cannot tell which "
            "clips the game plays by name.")
NO_ROUTE = ("%s asks for its clips through a call the app cannot hook on this build, so random "
            "clips are not offered there.")
NOT_BANK = ("The game does not play this clip by name (a scene plays it on its own), so it "
            "cannot be swapped for another at random. The clips the game plays by name are "
            "the ones in its in-game video bank: modes, battles, awards.")
NO_MANIFEST = ("This project's video/manifest.txt does not say where this clip is on the "
               "card. Extract the card again to fix that.")
NO_CARD = ("The card this project was extracted from is not on this PC, so the app cannot read "
           "which of the game's video banks this clip is in. Point the project at its card "
           "(Select card) to fix that.")


class VariantError(ValueError):
    """Variants a build cannot carry; the message says why."""


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


def variant_name(stock, k):
    return NAME_FORMAT % (stock, k)


# ---- the project's record ------------------------------------------------------------------
def clean(raw):
    """``{rel: [path, ...]}`` from a sidecar's value, every list cut to :data:`MAX_EXTRA`, empty
    paths and empty lists dropped."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for rel, files in raw.items():
        if not isinstance(rel, str) or not isinstance(files, (list, tuple)):
            continue
        keep = [f for f in files if isinstance(f, str) and f.strip()][:MAX_EXTRA]
        if keep:
            out[rel] = keep
    return out


def load(project):
    """The project's variants, ``{slot rel: [file, ...]}``."""
    if not project:
        return {}
    from ...core import staged_changes
    try:
        return clean(staged_changes.load(project).get(STAGED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return {}


def manifest(project):
    """``{slot rel: card path}`` from the project's ``video/manifest.txt`` (card paths without a
    leading slash), ``{}`` when it has none."""
    out = {}
    try:
        with open(os.path.join(project, "video", "manifest.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 2 and cols[0] and cols[1]:
                    out["video/" + cols[0]] = cols[1].lstrip("/")
    except OSError:
        pass
    return out


# ---- which titles, which slots ----------------------------------------------------------------
def title_key(prof):
    return "%s-%s" % (prof.game_dir, prof.version) if prof is not None else ""


def hook_route(port_path):
    """How the runtime hooks the game's ask for a clip on this port (pad_mode_runtime.c
    clipv_arm): ``"clip_play"``, ``"surface"`` (clip v2), ``"layer"`` (PAD-723: Deadpool's
    full-screen video layer, asked by name) or ``""`` (it cannot)."""
    from . import mode_project as MP
    try:
        port = MP.read_port(port_path)
    except OSError:
        return ""
    sites, data, values = port["site"], port["data"], port["value"]
    if all(n in sites for n in ("clip_play", "video_surface", "surface_state")):
        return "clip_play"
    need_s = ("surface_find", "surface_set_video", "surface_state", "string_new", "resource_get",
              "dynamic_cast")
    need_d = ("resource_manager", "typeinfo_resource", "typeinfo_scene_player")
    if (all(n in sites for n in need_s) and all(data.get(n) for n in need_d)
            and "scene_player_scene" in values
            and (port["scene"].get("video_bank") or "video_surface" in sites)):
        return "surface"
    if all(n in sites for n in ("layer_video", "string_new")) and data.get("video_layer"):
        return "layer"
    return ""


def route_of(prof):
    """:func:`hook_route` of ``prof``'s port."""
    from . import mode_project as MP
    return hook_route(MP.port_path(prof)) if prof is not None and prof.port else ""


def title_refusal(prof):
    """Why no clip of ``prof``'s title can vary, or ``""``."""
    if prof is None:
        return NO_TITLE
    if not route_of(prof):
        return NO_ROUTE % prof.label
    return ""


def bank_assets(prof):
    """The card folder (no leading slash, trailing slash) the bank's clips are in."""
    return "%s/%s/scene.assets/" % (prof.game_dir, prof.lcd("bank"))


def bank_scene(prof):
    """The bank scene's card path (no leading slash)."""
    return "%s/%s/scene.radium" % (prof.game_dir, prof.lcd("bank"))


def scene_of(prof, card_path):
    """PAD-723: ``(scene card path, scene id)`` of the scene whose ``scene.assets`` holds the clip at
    ``card_path`` - its ``scene.radium`` and the id the resource manager knows it by (the path under
    ``assets/lcd/<tree>/``) - or ``None`` when it is not a scene's asset."""
    p = card_path.lstrip("/")
    head, sep, _rest = p.partition("/scene.assets/")
    parts = head.split("/")
    if not sep or len(parts) < 5 or parts[0] != prof.game_dir or parts[1:3] != ["assets", "lcd"]:
        return None
    return head + "/scene.radium", "/".join(parts[4:])


def other_scenes(prof, card_paths, route=None):
    """PAD-723: the scene card paths a set of slots' clips are in, beside the port's bank (only on
    a clip v2 build: clip_play plays on the one bank)."""
    route = route if route is not None else route_of(prof)
    if route != "surface":
        return set()
    own = bank_scene(prof)
    out = set()
    for card in card_paths:
        sc = scene_of(prof, card or "")
        if sc and sc[0] != own:
            out.add(sc[0])
    return out


def slot_refusal(prof, card_path, banks=None, route=None):
    """Why the slot at ``card_path`` cannot vary on ``prof``'s title, or ``""``. ``prof`` is
    taken as already passing :func:`title_refusal`. PAD-723: a clip in another scene varies on a
    clip v2 build when that scene is a video bank: *banks* is :func:`card_banks`' answer for it
    (None: the card could not be read)."""
    if not card_path:
        return NO_MANIFEST
    if card_path.lstrip("/").startswith(bank_assets(prof)):
        return ""
    route = route if route is not None else route_of(prof)
    sc = scene_of(prof, card_path)
    if route != "surface" or sc is None:
        return NOT_BANK
    if banks is None:
        return NO_CARD
    return "" if card_path.lstrip("/") in (banks.get(sc[0]) or {}) else NOT_BANK


_BANKS = {}


def scene_counts(reader, game_dir, names):
    """PAD-723: ``{name: how many scene files of the card name it}`` - a clip's name as a scene writes
    it (``u64`` length, then the bytes), counted over every ``scene.radium`` under the game's
    ``assets/lcd``."""
    import struct
    want = {n: struct.pack("<Q", len(n)) + n.encode("latin1") for n in names}
    out = dict.fromkeys(names, 0)
    top = "/%s/assets/lcd/" % game_dir
    for path, _ino, node in reader.iter_regular_files(max_depth=12):
        if not path.endswith("/scene.radium") or not ("/" + path.lstrip("/")).startswith(top):
            continue
        raw = bytes(reader.read_file_bytes(node))
        for n, tag in want.items():
            if tag in raw:
                out[n] += 1
    return out


def card_banks(image, scenes):
    """PAD-723: ``{scene card path: {card path: clip name}}`` for each of *scenes* on the card
    *image* that walks as a video bank (``{}`` for one that does not, or is not on the card);
    ``None`` when the card cannot be read. Opens the image: never on the UI thread. Kept per card
    (its path, size and time) and scene."""
    try:
        st = os.stat(image)
    except (OSError, TypeError):
        return None
    key = (os.path.abspath(image), st.st_size, int(st.st_mtime))
    have = _BANKS.setdefault(key, {})
    want = [sc for sc in scenes if sc not in have]
    if want:
        from . import engine as E, mode_write as MW, video_bank as VB
        try:
            with open(image, "rb") as f:
                reader, _fw, _img = E._locate(f, E._linux_partitions(image))
                for sc in want:
                    node = MW.lookup(reader, sc)
                    names = {}
                    if node is not None and (node["mode"] & 0xF000) == 0x8000:
                        try:
                            names = _bank_names(VB.parse_scene(bytes(reader.read_file_bytes(node))),
                                                sc[:-len("scene.radium")] + "scene.assets/")
                        except VB.VideoBankError:
                            names = {}
                    have[sc] = names
        except Exception:                               # noqa: BLE001 - an unreadable card: unknown
            return None
    return {sc: have[sc] for sc in scenes}


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None. ``probe=True`` may open the
    card image (a renamed card's index), so never on the UI thread."""
    from . import mode_project as MP
    try:
        _card, prof = MP.project_profile(project, probe=probe)
    except (OSError, ValueError):
        return None
    return prof


def offer(project, rels, probe=True):
    """``(title_why, {rel: why})`` for the Video tab: why no clip of the project's game can
    vary (``""`` when they can), and per slot why that one cannot (``""`` when it can)."""
    if not enabled():
        return ("%s=0 leaves random clips out of this app." % GATE_ENV), {}
    prof = project_title(project, probe=probe)
    why = title_refusal(prof)
    if why:
        return why, {}
    cards = manifest(project)
    route = route_of(prof)
    scenes = other_scenes(prof, [cards.get(rel, "") for rel in rels], route)
    banks = {}
    if scenes:
        from . import mode_project as MP
        card = MP.project_card(project)
        banks = card_banks(card.image, scenes) if probe and card is not None and card.image else None
    return "", {rel: slot_refusal(prof, cards.get(rel, ""), banks, route) for rel in rels}


# ---- the build ---------------------------------------------------------------------------------
@dataclass
class Slot:
    rel: str                     # the Video tab's slot, "video/<name>"
    card: str                    # its clip's card path
    stock: str                   # the bank's name for it: what the game asks for
    files: list                  # the person's extra clips, in order
    staged: list = field(default_factory=list)   # each one in the slot's format
    names: list = field(default_factory=list)    # the bank names they were added under
    paths: list = field(default_factory=list)    # their card paths
    scene: str = ""              # PAD-723: its bank scene's id when that is not the port's video_bank
    bank_sc: str = ""            # PAD-723: its bank scene's card path


@dataclass
class VariantBuild:
    bank: bytes                                  # the port's bank scene with every clip added
    slots: list                                  # [Slot] that vary
    new: list                                    # [(card path, staged file)] the added clips
    cfg: str                                     # clips.cfg's path
    lines: list = field(default_factory=list)    # what the log says
    others: dict = field(default_factory=dict)   # PAD-723: {scene card path: bytes}, other banks grown


def cfg_text(slots, only):
    """``clips.cfg``: ``only`` first for a card with no modes, then one line per slot."""
    out = ["# PAD-446: clips that play one of several at random (pad_mode_runtime.c)"]
    if only:
        out.append("only")
    for s in slots:
        head = ["sclip", s.scene] if s.scene else ["clip"]     # PAD-723: another bank scene's
        out.append("\t".join(head + [s.stock] + list(s.names)))
    return "\n".join(out) + "\n"


def _bank_names(parsed, base):
    """``{card path: bank name}`` for every clip in a bank's library; ``base`` is its
    ``scene.assets/`` folder's card path."""
    return {base + c.path: c.name for c in parsed.library.entries if c.path}


class _Cache:
    """Which converted clip came from which file with which settings (a slot's
    :class:`core.video_slots.StagedCache`, kept apart: its entries are the slots' own)."""

    def __init__(self, project):
        self.path = os.path.join(project, CACHE_FILE)
        self.entries = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("v") == 1:
                self.entries = dict(data.get("clips") or {})
        except (OSError, ValueError):
            pass

    def fresh(self, key, recipe, out):
        e = self.entries.get(key)
        if not recipe or not isinstance(e, dict) or e.get("recipe") != recipe:
            return False
        try:
            st = os.stat(out)
        except OSError:
            return False
        return st.st_size == e.get("size") and st.st_mtime_ns == e.get("mtime_ns")

    def record(self, key, recipe, out):
        try:
            st = os.stat(out)
        except OSError:
            return
        self.entries[key] = {"recipe": recipe, "size": st.st_size, "mtime_ns": st.st_mtime_ns}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "clips": self.entries}, f, indent=0, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _safe(rel):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in rel.replace("/", "__"))


def stage(project, rel, files, log=None, cancel=None, tag="", first=2, what="random clip"):
    """Each of ``files`` made into slot ``rel``'s format, as the slot's own replacement would be
    (its length and conversion choices, the tab's options, the project's colour profile).
    Returns the converted files in order. Raises :class:`VariantError` naming the clip that
    could not be made. PAD-685: *tag* keeps another feature's clips made like the same slot apart
    in the cache (the jukebox's ``"juke"``), numbered from *first* and called *what* in the log."""
    from ...core import staged_changes, staged_originals
    from ...core import video_slots as VS
    from ...core.video import detect_video_info
    log = log or (lambda *a, **k: None)
    side = staged_changes.load(project)
    pristine = staged_originals.snapshot_path(project, rel) or ""
    if not os.path.isfile(pristine):
        pristine = os.path.join(project, *rel.split("/"))
    if not os.path.isfile(pristine):
        raise VariantError("%s: the clip it varies is not in the project folder" % rel)
    info = detect_video_info(pristine)
    if info is None:
        raise VariantError("%s: its clip could not be read (is ffmpeg installed?)" % rel)
    ext = os.path.splitext(pristine)[1].lower()
    choice = (side.get("video_length_slots") or {}).get(rel)
    seconds = VS.length_seconds(choice)
    if choice == VS.LENGTH_FULL:
        trim = False
    elif choice == VS.LENGTH_STOCK or seconds:
        trim = True
    else:
        trim = bool(side.get("video_trim"))
    asis = (side.get("video_asis_slots") or {}).get(rel)
    noconv = bool(side.get("video_no_conversion")) if asis is None else bool(asis)
    best = bool(side.get("video_best_quality"))
    rate = VS._clip_bitrate(pristine)
    try:
        from ...core import colour_profile
        colour = colour_profile.active(project)
    except Exception:                                   # noqa: BLE001 - no profile then
        colour = None
    out_dir = os.path.join(project, CACHE_DIR)
    os.makedirs(out_dir, exist_ok=True)
    cache = _Cache(project)
    made = []
    try:
        for k, src in enumerate(files, first):
            if cancel is not None and cancel():
                raise VariantError("cancelled")
            if not os.path.isfile(src):
                raise VariantError("%s: %s %d (%s) is not there any more"
                                   % (rel, what, k, src))
            out = os.path.join(out_dir, "%s__%s%d%s" % (_safe(rel), tag, k, ext))
            target = VS.VideoSlot(rel_path="%s#%s%d" % (rel, tag, k), abs_path=out, ext=ext, info=info,
                                  size=os.path.getsize(pristine), probed=True)
            if seconds:
                target = VS._with_length(target, seconds)
            recipe = VS.StagedCache.recipe(target, src, pristine, trim=trim, length=seconds or 0,
                                           noconv=noconv, rate=round(rate or 0), best=best,
                                           colour=colour.key() if colour is not None else "")
            key = target.rel_path
            if cache.fresh(key, recipe, out):
                log("  ✓ %s, %s %d (already converted from this file - kept)" % (rel, what, k),
                    "success")
                made.append(out)
                continue
            ok, detail = VS.stage_replacement(
                target, src, trim_to_length=trim, no_conversion=noconv, cancel_cb=cancel,
                match_bitrate=rate, best_quality=best,
                **({"colour": colour} if colour is not None else {}))
            if not ok:
                cache.entries.pop(key, None)
                raise VariantError("%s: %s %d (%s) could not be made into this slot's "
                                   "format: %s" % (rel, what, k, os.path.basename(src), detail))
            cache.record(key, recipe, out)
            log("  ✓ %s, %s %d  ←  %s%s" % (rel, what, k, os.path.basename(src),
                                              ("  (%s)" % detail) if detail else ""),
                "success")
            made.append(out)
    finally:
        cache.save()
    return made


def build(project, prof, bank, out_dir, only, variants=None, log=None, progress=None, cancel=None,
          stage_fn=None, read_card=None, scan_card=None):
    """Every varying slot's extra clips added to ``bank`` (the title's bank scene, stock or with
    the modes' clips already in it), each converted clip copied to its card path under
    ``out_dir``, and ``clips.cfg`` written there. ``None`` when the project has no variants that
    can go on this title. ``only``: the card carries no mode (the runtime arms this and nothing
    else). PAD-723: a slot in another of the title's bank scenes (:func:`slot_refusal`) is added to
    that scene, read with *read_card* ``(card path) -> bytes or None``, and returned in
    ``others``. A slot in a DEMAND-loaded bank, which the runtime cannot look up by id, has its
    scene written ``*<id>`` when *scan_card* ``(names) -> {name: scenes naming it}`` finds its name in
    that one scene of the card alone (the runtime then takes any surface asking for it as that
    scene's). Raises :class:`VariantError`."""
    from . import video_bank as VB
    log = log or (lambda *a, **k: None)
    variants = load(project) if variants is None else clean(variants)
    juke = jukebox_clips(project, prof)           # PAD-685: the jukebox's songs' intro videos
    if not variants and not juke:
        return None
    why = title_refusal(prof) if variants else ""
    if why:
        raise VariantError(why)
    cards = manifest(project)
    route = route_of(prof)
    own = bank_scene(prof)
    data = {own: bank}                            # {scene card path: its bytes as they grow}
    parsed = {}

    def bank_of(sc):
        """``(parse, {card path: name})`` of a bank scene, or None when it is not one."""
        if sc not in parsed:
            raw = data.get(sc)
            if raw is None and read_card is not None:
                raw = read_card(sc)
                if raw is not None:
                    data[sc] = raw = bytes(raw)
            try:
                got = VB.parse_scene(raw) if raw else None
            except VB.VideoBankError as e:
                if sc == own and not juke and route != "surface":
                    raise VariantError("the game's video bank could not be read (%s)" % e) from None
                got = None
            parsed[sc] = (got, _bank_names(got, sc[:-len("scene.radium")] + "scene.assets/")
                          if got is not None else {})
        return parsed[sc] if parsed[sc][0] is not None else None

    slots, left, stocks = [], [], set()
    for rel in sorted(variants):
        card = cards.get(rel, "").lstrip("/")
        sc = scene_of(prof, card) if card else None
        if not card:
            bank_sc, why = "", NO_MANIFEST
        elif card.startswith(bank_assets(prof)):
            bank_sc, why = own, ""
        elif route == "surface" and sc is not None:
            bank_sc, why = sc[0], ""
        else:
            bank_sc, why = "", NOT_BANK
        got = bank_of(bank_sc) if not why else None
        if not why and (got is None or card not in got[1]):
            why = NOT_BANK
        # a clip the project names that is not on this PC (a project moved here: Project >
        # Relink moved files... re-points them) is left out, as a gone replacement is
        files = [f for f in variants[rel] if os.path.isfile(f)]
        for f in variants[rel]:
            if f not in files and not why:
                log("Random clips: %s is not there any more, so %s plays without it"
                    % (f, rel), "warning")
        if not why and not files:
            why = "none of its random clips is on this PC"
        stock = got[1][card] if not why else ""
        if not why and stock in stocks:
            # PAD-723: the runtime finds a line by the game's name, so two banks' clips of one
            # name cannot both vary
            why = "another clip the game calls %s already plays at random" % stock
        if why:
            left.append((rel, why))
            continue
        stocks.add(stock)
        slots.append(Slot(rel=rel, card=card, stock=stock, files=files,
                          scene="" if bank_sc == own else sc[1], bank_sc=bank_sc))
    for rel, why in left:
        log("Random clips: %s is left out: %s" % (rel, why), "warning")
    if not slots and not juke:
        return None
    if len(slots) > MAX_SLOTS:
        raise VariantError("%d clips play at random; a card can carry %d" % (len(slots), MAX_SLOTS))
    demand = [s for s in slots if s.scene and "/demand_loaded/" in s.bank_sc]
    if demand and scan_card is not None:
        counts = scan_card(sorted({s.stock for s in demand})) or {}
        for s in demand:
            if counts.get(s.stock) == 1:
                s.scene = "*" + s.scene
    stage_fn = stage_fn or stage
    total = sum(len(s.files) for s in slots) + (len(juke[1]) if juke else 0)
    done = 0
    new = []
    taken = {sc: {c.name for c in p.library.entries} for sc, (p, _n) in parsed.items() if p}

    def add(sc, name, src):
        if name in taken[sc]:
            return False
        try:
            data[sc], info = VB.add_clip(data[sc], name, os.path.getsize(src), spaces=" " in name)
        except VB.VideoBankError as e:
            raise VariantError("%s could not be added to the video bank (%s)" % (name, e)) from None
        taken[sc].add(name)
        card = sc[:-len("scene.radium")] + "scene.assets/" + info["path"]
        dst = os.path.join(out_dir, *card.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        new.append((card, dst))
        return card

    for s in slots:
        if progress is not None:
            progress(done, total, "Converting the random clips for %s..." % s.rel)
        s.staged = list(stage_fn(project, s.rel, s.files, log=log, cancel=cancel))
        for k, src in enumerate(s.staged, 2):
            name = variant_name(s.stock, k)
            card = add(s.bank_sc, name, src)
            if not card:
                raise VariantError("the card being written already has random clips from an "
                                   "earlier build (its video bank has %s); write onto the card "
                                   "that build was made from" % name)
            s.names.append(name)
            s.paths.append(card)
            done += 1
    lines = ["%s plays one of %d clips at random (%s)"
             % (s.rel, 1 + len(s.names), ", ".join(os.path.basename(f) for f in s.files))
             for s in slots]
    if juke:
        # PAD-685: each song's intro video, made like the title's first song mode's intro and added
        # under the name sounds.cfg's jsong line gives it; no clips.cfg line (the jukebox picks)
        if bank_of(own) is None:
            raise VariantError("the game's video bank could not be read")
        rel, songs = juke
        if progress is not None:
            progress(done, total, "Converting the jukebox's intro videos...")
        made = list(stage_fn(project, rel, [f for _k, f in songs], log=log, cancel=cancel,
                             tag="juke", first=1, what="jukebox song"))
        for (k, src_file), src in zip(songs, made):
            name = _jb_clip_name(k)
            if not add(own, name, src):
                raise VariantError("the card being written already has a jukebox from an earlier "
                                   "build (its video bank has %s); write onto the card that build "
                                   "was made from" % name)
            done += 1
        lines.append("the jukebox's %d intro video(s) are in the video bank (%s)"
                     % (len(songs), ", ".join(_jb_clip_name(k) for k, _f in songs)))
    if progress is not None:
        progress(total, total, "")
    os.makedirs(out_dir, exist_ok=True)
    cfg = os.path.join(out_dir, CFG_NAME)
    with open(cfg, "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg_text(slots, only))
    return VariantBuild(bank=data[own], slots=slots, new=new, cfg=cfg, lines=lines,
                        others={sc: b for sc, b in data.items()
                                if sc != own and any(s.bank_sc == sc for s in slots)})


def _jb_clip_name(k):
    from . import jukebox as JB
    return JB.clip_name(k)


def jukebox_clips(project, prof):
    """PAD-685: ``(slot rel, [(song number, video file), ...])`` - the jukebox's songs with an intro
    video on this PC, to be made like the title's first song mode's intro (:mod:`.jukebox`); ``None``
    when there are none, the title has no song modes or the project lacks that intro."""
    from . import jukebox as JB
    if not JB.enabled() or JB.title_refusal(prof):
        return None
    songs = [(k, s.video) for k, s in enumerate(JB.load(project).songs, 1)
             if s.video and os.path.isfile(s.video)]
    modes = JB.song_modes(prof)
    if not songs or not modes:
        return None
    rel = modes[0].intros[0]
    if not os.path.isfile(os.path.join(project, *rel.split("/"))):
        return None
    return rel, songs


#: what an added clip's file holds beyond its frames, at most (the container, a free box)
CONTAINER_BYTES = 64 << 10
#: Best quality's peak, in bits per pixel per frame (core.video transcode_video_to: 0.64 bpp
#: of the slot's pixel rate, 20 Mbps at 1360x768 / 30)
BEST_PEAK_BPP = 0.64
#: the stock rate a slot whose clip cannot be measured is taken at: the highest-rate stock clip
#: measured on Godzilla 1.16 (stern.md "Best quality"), so the bound stays a bound
STOCK_RATE_FALLBACK = 13.3e6


def size_bound(project, variants=None, probe=None, rate=None):
    """An upper bound of what the project's random clips add to the games partition, in bytes,
    sized before anything is converted (the build's free-space pre-flight): each extra clip
    whole at the larger of its own size and its length at the rate its conversion is held to -
    the slot's stock clip's bitrate, or Best quality's peak - plus its container. *probe*
    ``path -> VideoInfo`` and *rate* ``path -> bits/s`` are injectable for tests."""
    from ...core import staged_changes, staged_originals
    from ...core import video_slots as VS
    if probe is None:
        from ...core.video import detect_video_info as probe
    rate = rate or VS._clip_bitrate
    variants = load(project) if variants is None else clean(variants)
    if not variants:
        return 0
    best = bool(staged_changes.load(project).get("video_best_quality"))
    total = 0
    for rel, files in variants.items():
        pristine = staged_originals.snapshot_path(project, rel) or ""
        if not os.path.isfile(pristine):
            pristine = os.path.join(project, *rel.split("/"))
        bps = rate(pristine) if os.path.isfile(pristine) else None
        bps = float(bps or STOCK_RATE_FALLBACK)
        info = probe(pristine) if os.path.isfile(pristine) else None
        if best and info is not None and info.width and info.height and info.fps:
            bps = max(bps, BEST_PEAK_BPP * info.width * info.height * info.fps)
        for src in files:
            try:
                size = os.path.getsize(src)
            except OSError:
                continue
            got = probe(src)
            seconds = float(getattr(got, "duration", 0) or 0)
            total += max(size, int(seconds * bps / 8)) + CONTAINER_BYTES
    return total


def jukebox_size_bound(project, probe=None, rate=None):
    """PAD-685: an upper bound of what the jukebox's intro videos add to the games partition, sized as
    :func:`size_bound` sizes a random clip: each whole at the larger of its own size and its length at the
    intro clip's stock bitrate (the first song mode's of a title the project has), plus its container."""
    from . import jukebox as JB
    from ...core import video_slots as VS
    if probe is None:
        from ...core.video import detect_video_info as probe
    rate = rate or VS._clip_bitrate
    files = [s.video for s in JB.load(project).songs if s.video and os.path.isfile(s.video)]
    if not files:
        return 0
    bps = None
    for modes in JB.TITLES.values():
        intro = os.path.join(project, *modes[0].intros[0].split("/"))
        if os.path.isfile(intro):
            bps = rate(intro)
            break
    bps = float(bps or STOCK_RATE_FALLBACK)
    total = 0
    for src in files:
        got = probe(src)
        seconds = float(getattr(got, "duration", 0) or 0)
        total += max(os.path.getsize(src), int(seconds * bps / 8)) + CONTAINER_BYTES
    return total


def describe(vb):
    """One sentence for the build's summary."""
    if vb is None or not vb.slots:
        return ""
    return ("%d clip(s) play one of several at random (%d added clip(s))"
            % (len(vb.slots), len(vb.new)))
