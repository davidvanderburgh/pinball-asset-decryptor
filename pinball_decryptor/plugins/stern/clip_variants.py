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
title whose swap was seen in the emulator (:data:`PROVEN`).
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

#: ``<game>-<version>`` of the builds where the swap was SEEN: the game asked for a clip, the
#: runtime's log named the variant it played and the variant was on the glass (emulator).
PROVEN = frozenset({"godzilla_pro-1.16", "godzilla_le-1.16"})

#: why a slot cannot vary, as the tab's menu says it
NOT_STERN = "Only a Stern Spike 2 game can play one of several clips at random."
NO_TITLE = ("The app cannot tell which game this project is for, so it cannot tell which "
            "clips the game plays by name.")
NOT_PROVEN = ("Random clips have not been tried on %s yet, so they are not offered there. "
              "Godzilla Pro and Premium/LE 1.16 have them.")
NOT_BANK = ("The game does not play this clip by name (a scene plays it on its own), so it "
            "cannot be swapped for another at random. The clips the game plays by name are "
            "the ones in its in-game video bank: modes, battles, awards.")
NO_MANIFEST = ("This project's video/manifest.txt does not say where this clip is on the "
               "card. Extract the card again to fix that.")


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
    clipv_arm): ``"clip_play"``, ``"surface"`` (clip v2) or ``""`` (it cannot)."""
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
    return ""


def title_refusal(prof):
    """Why no clip of ``prof``'s title can vary, or ``""``."""
    if prof is None:
        return NO_TITLE
    if title_key(prof) not in PROVEN:
        return NOT_PROVEN % prof.label
    if not prof.can("clip"):
        return NOT_PROVEN % prof.label
    from . import mode_project as MP
    if not hook_route(MP.port_path(prof)):
        return NOT_PROVEN % prof.label
    return ""


def bank_assets(prof):
    """The card folder (no leading slash, trailing slash) the bank's clips are in."""
    return "%s/%s/scene.assets/" % (prof.game_dir, prof.lcd("bank"))


def bank_scene(prof):
    """The bank scene's card path (no leading slash)."""
    return "%s/%s/scene.radium" % (prof.game_dir, prof.lcd("bank"))


def slot_refusal(prof, card_path):
    """Why the slot at ``card_path`` cannot vary on ``prof``'s title, or ``""``. ``prof`` is
    taken as already passing :func:`title_refusal`."""
    if not card_path:
        return NO_MANIFEST
    if not card_path.lstrip("/").startswith(bank_assets(prof)):
        return NOT_BANK
    return ""


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
    return "", {rel: slot_refusal(prof, cards.get(rel, "")) for rel in rels}


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


@dataclass
class VariantBuild:
    bank: bytes                                  # the bank scene with every clip added
    slots: list                                  # [Slot] that vary
    new: list                                    # [(card path, staged file)] the added clips
    cfg: str                                     # clips.cfg's path
    lines: list = field(default_factory=list)    # what the log says


def cfg_text(slots, only):
    """``clips.cfg``: ``only`` first for a card with no modes, then one line per slot."""
    out = ["# PAD-446: clips that play one of several at random (pad_mode_runtime.c)"]
    if only:
        out.append("only")
    for s in slots:
        out.append("\t".join(["clip", s.stock] + list(s.names)))
    return "\n".join(out) + "\n"


def _bank_names(parsed, prof):
    """``{card path: bank name}`` for every clip in the bank's library."""
    base = bank_assets(prof)
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


def stage(project, rel, files, log=None, cancel=None):
    """Each of ``files`` made into slot ``rel``'s format, as the slot's own replacement would be
    (its length and conversion choices, the tab's options, the project's colour profile).
    Returns the converted files in order. Raises :class:`VariantError` naming the clip that
    could not be made."""
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
        for k, src in enumerate(files, 2):
            if cancel is not None and cancel():
                raise VariantError("cancelled")
            if not os.path.isfile(src):
                raise VariantError("%s: random clip %d (%s) is not there any more"
                                   % (rel, k, src))
            out = os.path.join(out_dir, "%s__%d%s" % (_safe(rel), k, ext))
            target = VS.VideoSlot(rel_path="%s#%d" % (rel, k), abs_path=out, ext=ext, info=info,
                                  size=os.path.getsize(pristine), probed=True)
            if seconds:
                target = VS._with_length(target, seconds)
            recipe = VS.StagedCache.recipe(target, src, pristine, trim=trim, length=seconds or 0,
                                           noconv=noconv, rate=round(rate or 0), best=best,
                                           colour=colour.key() if colour is not None else "")
            key = target.rel_path
            if cache.fresh(key, recipe, out):
                log("  ✓ %s, random clip %d (already converted from this file - kept)" % (rel, k),
                    "success")
                made.append(out)
                continue
            ok, detail = VS.stage_replacement(
                target, src, trim_to_length=trim, no_conversion=noconv, cancel_cb=cancel,
                match_bitrate=rate, best_quality=best,
                **({"colour": colour} if colour is not None else {}))
            if not ok:
                cache.entries.pop(key, None)
                raise VariantError("%s: random clip %d (%s) could not be made into this slot's "
                                   "format: %s" % (rel, k, os.path.basename(src), detail))
            cache.record(key, recipe, out)
            log("  ✓ %s, random clip %d  ←  %s%s" % (rel, k, os.path.basename(src),
                                                    ("  (%s)" % detail) if detail else ""),
                "success")
            made.append(out)
    finally:
        cache.save()
    return made


def build(project, prof, bank, out_dir, only, variants=None, log=None, progress=None, cancel=None,
          stage_fn=None):
    """Every varying slot's extra clips added to ``bank`` (the title's bank scene, stock or with
    the modes' clips already in it), each converted clip copied to its card path under
    ``out_dir``, and ``clips.cfg`` written there. ``None`` when the project has no variants that
    can go on this title. ``only``: the card carries no mode (the runtime arms this and nothing
    else). Raises :class:`VariantError`."""
    from . import video_bank as VB
    log = log or (lambda *a, **k: None)
    variants = load(project) if variants is None else clean(variants)
    if not variants:
        return None
    why = title_refusal(prof)
    if why:
        raise VariantError(why)
    cards = manifest(project)
    try:
        parsed = VB.parse(bank)
    except VB.VideoBankError as e:
        raise VariantError("the game's video bank could not be read (%s)" % e) from None
    names = _bank_names(parsed, prof)
    slots, left = [], []
    for rel in sorted(variants):
        card = cards.get(rel, "")
        why = slot_refusal(prof, card)
        if not why and card not in names:
            why = NOT_BANK
        if why:
            left.append((rel, why))
            continue
        slots.append(Slot(rel=rel, card=card, stock=names[card], files=list(variants[rel])))
    for rel, why in left:
        log("Random clips: %s is left out: %s" % (rel, why), "warning")
    if not slots:
        return None
    if len(slots) > MAX_SLOTS:
        raise VariantError("%d clips play at random; a card can carry %d" % (len(slots), MAX_SLOTS))
    stage_fn = stage_fn or stage
    total = sum(len(s.files) for s in slots)
    done = 0
    new = []
    taken = {c.name for c in parsed.library.entries}
    for s in slots:
        if progress is not None:
            progress(done, total, "Converting the random clips for %s..." % s.rel)
        s.staged = list(stage_fn(project, s.rel, s.files, log=log, cancel=cancel))
        for k, src in enumerate(s.staged, 2):
            name = variant_name(s.stock, k)
            if name in taken:
                raise VariantError("the card being written already has random clips from an "
                                   "earlier build (its video bank has %s); write onto the card "
                                   "that build was made from" % name)
            try:
                bank, info = VB.add_clip(bank, name, os.path.getsize(src))
            except VB.VideoBankError as e:
                raise VariantError("%s could not be added to the video bank (%s)" % (name, e)) from None
            taken.add(name)
            card = bank_assets(prof) + info["path"]
            dst = os.path.join(out_dir, *card.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            s.names.append(name)
            s.paths.append(card)
            new.append((card, dst))
            done += 1
    if progress is not None:
        progress(total, total, "")
    os.makedirs(out_dir, exist_ok=True)
    cfg = os.path.join(out_dir, CFG_NAME)
    with open(cfg, "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg_text(slots, only))
    lines = ["%s plays one of %d clips at random (%s)"
             % (s.rel, 1 + len(s.names), ", ".join(os.path.basename(f) for f in s.files))
             for s in slots]
    return VariantBuild(bank=bank, slots=slots, new=new, cfg=cfg, lines=lines)


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


def describe(vb):
    """One sentence for the build's summary."""
    if vb is None or not vb.slots:
        return ""
    return ("%d clip(s) play one of several at random (%d added clip(s))"
            % (len(vb.slots), len(vb.new)))
