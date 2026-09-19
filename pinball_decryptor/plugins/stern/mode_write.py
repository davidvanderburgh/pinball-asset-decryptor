"""WRITE SHIPS THE PROJECT'S MODES (item 149): the card path items 128-133 proved by hand.

A project's modes (:mod:`.mode_project`) reach a card through Write like every other tab's
edits. The recipe the Godzilla Premium 1.16 card was built with (``C:\\tmp\\kaiju_premium``,
hardware-tested 2026-09-16), as the build now does it:

1. the screens into the game's HUD scene and the clips into its video bank, built from the
   card's STOCK scenes every time (:func:`.mode_assets.build`), each clip a file the card
   never had;
2. the ``.sidx`` manifest rebuilt to match: the HUD and bank records refreshed, one record
   appended per new clip, the size total moved (:func:`compose_manifest`);
3. a mode's own END SOUND appended to ``image.bin`` and the time-up request's descriptors
   re-pointed at it - the engine's grow path, forced (``_stage_grown_image`` /
   ``_derive_grown`` / ``_repoint_descriptors``), so the sound engine's count patch and the
   validator bypass follow as they do for any grown bank; a mode's START SOUND, SHOT SOUND and
   MUSIC (item 150) the same way, each on a stock request the game never plays (a carrier,
   :mod:`.mode_sounds`), with the mode file naming the carrier (:func:`choose_own_sounds`);
4. the pinned runtime object, one mode file per mode and the title's port on the system
   partition (``tools/spike2_emu/mode_install.py``, run in the app's Linux).

This module is the planning half, testable without a card: the gates, the card check, the
asset build, which request the end sound rides on, the manifest, the p2 payload and what the
log and the change scan say. :mod:`.engine` runs it.

GATES. THE PREVIEW SWITCH comes first: the mode maker ships dark, and a copy of the app
carries modes only while Settings > Preview features holds a signed code for it
(:mod:`...core.preview`, :func:`preview_on`). Off, a Write never reads the project's modes
at all - it says in one sentence that they are left out - and takes the path a build
without the family takes. ``PAD_STERN_MODES=0`` leaves modes out of every build. A mode build needs an image
file and a host that can write files into ext4 (a direct-SD write cannot add a file). A
mode's own end sound ships unless ``PAD_STERN_MODE_SOUND=0``; with it closed, or when a
second mode also has one, the mode ends with the game's own time-up call.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field

from . import mode_project as MP
from . import mode_runtime as MR
from . import sidx, sidx_append

GATE_ENV = "PAD_STERN_MODES"
SOUND_ENV = "PAD_STERN_MODE_SOUND"
#: where the runtime and its files live on the card's system partition
P2_DIR = "/usr/local/padmode"
#: the card path of a game tree's auto-loaded scenes, below the game dir
LCD = "assets/lcd/auto_loaded"


class ModeWriteError(RuntimeError):
    """A project's modes cannot be put on this card; the message says why."""


# ---- gates -------------------------------------------------------------------------------
#: The preview feature (core/preview.py) the whole mode editor family rides on.
PREVIEW_FEATURE = "modes"
#: Why a copy of the app with the switch off leaves a project's modes out. One clause,
#: for "... are left out of this build: <this>." (the same shape as :data:`MAC_REFUSAL`).
#: NEUTRAL ON PURPOSE: a copy without a code names no preview feature anywhere, and this
#: is what it says when it meets a tester's project.
PREVIEW_REFUSAL = ("a preview feature it needs is not switched on in this copy of the app "
                   "(Settings > Preview features)")


def preview_on():
    """Is the mode maker switched on in this run (a signed preview code, checked at
    start-up)? Everything the family adds to a Write asks this first."""
    from ...core import preview
    return preview.enabled(PREVIEW_FEATURE)


def held_modes(project):
    """``[slug]`` of every mode the project HOLDS (a mode file, or a code mode's source),
    found by name only - nothing is parsed, so a Write with the switch off can say what
    it leaves out without a broken mode stopping it."""
    root = MP.modes_dir(project) if project else ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [slug for slug in names
            if os.path.isfile(os.path.join(root, slug, MP.MODE_FILE))
            or os.path.isfile(os.path.join(root, slug, slug + ".c"))]


def held_stock_mode_changes(project):
    """How many changes to the game's OWN modes (item 145) the project has staged, read
    from its record only; 0 when it has none or it cannot be read."""
    try:
        from . import stock_modes
        return int(stock_modes.pending_count(project) or 0)
    except Exception:                                    # noqa: BLE001
        return 0


def preview_held(project):
    """What a copy with the switch off says a tester's project holds, in NEUTRAL words
    (no feature is named without a code): ``"4 preview item(s) (a, b, c, d) and 3 preview
    change(s)"``, or ``""`` for a project that holds none."""
    if not project:
        return ""
    slugs = held_modes(project)
    n_stock = held_stock_mode_changes(project)
    what = []
    if slugs:
        what.append("%d preview item(s) (%s)" % (len(slugs), ", ".join(slugs)))
    if n_stock:
        what.append("%d preview change(s)" % n_stock)
    return " and ".join(what)


#: How the switch-off sentence starts (tests find it by this).
PREVIEW_LEFT_OUT = "Left out of this build:"


def preview_left_out(project):
    """The one sentence a Write with the switch OFF logs for a project that holds modes
    or changes to the game's own modes (a tester's project), or ``""``. Neutral: it names
    what the project holds by its own folder names, and no feature."""
    what = preview_held(project)
    if not what:
        return ""
    return "%s this project's %s: %s." % (PREVIEW_LEFT_OUT, what, PREVIEW_REFUSAL)


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


def sound_enabled():
    return os.environ.get(SOUND_ENV, "1") != "0"


def code_modes(project):
    """``[slug]`` of the project's CODE modes - ``modes/<slug>/<slug>.c`` with no mode file
    (item 127's New code mode). Write ships the PINNED runtime with the mode files, so a code
    mode does not reach a card; the build log and the change scan say so."""
    root = MP.modes_dir(project) if project else ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [slug for slug in names
            if os.path.isfile(os.path.join(root, slug, slug + ".c"))
            and not os.path.isfile(os.path.join(root, slug, MP.MODE_FILE))]


def code_modes_note(slugs):
    return ("code mode(s) %s are not put on the card: Write ships the pinned mode runtime with "
            "the mode files, and a code mode runs only in Try it for now" % ", ".join(slugs))


def project_modes(project):
    """``[(slug, ModeSpec)]`` of a project, in slot order; ``[]`` for a folder with no modes.
    Raises :class:`ModeWriteError` naming a mode that does not load - a build never drops
    one quietly."""
    if not project or not os.path.isdir(MP.modes_dir(project)):
        return []
    found, broken = MP.list_modes(project)
    if broken:
        raise ModeWriteError("these modes could not be read: %s"
                             % ", ".join("%s (%s)" % b for b in broken))
    return found


def card_modes(project, modes):
    """*modes* (``[(slug, ModeSpec)]``) as the PROJECT'S CARD runs them (item 148,
    :func:`.mode_assets._modes_for_the_card`): each mode's shots matched by name to the port
    of the card the project was made from, so a project made from a Premium/LE 1.16 card
    whose modes were saved as Pro 1.15 builds for Premium. A project that names no card
    keeps each mode's own title. It may open the project's card image (a renamed card's
    index), so a build calls it, never the UI thread. Raises :class:`ModeWriteError`."""
    if not modes:
        return modes
    from . import mode_assets
    try:
        return mode_assets._modes_for_the_card(project, list(modes))
    except mode_assets.ModeAssetError as e:
        raise ModeWriteError(str(e)) from None


#: Why a Mac cannot carry modes yet (the pinned delivery runs Linux tools; see host_refusal).
MAC_REFUSAL = ("a Mac cannot put a mode's files on the card yet (the tools that copy them "
               "onto the card run only on Windows and Linux); write the card on Windows or "
               "Linux to carry the project's modes")


def host_refusal(platform=None):
    """Why THIS host cannot carry modes at all, or ``""``. On macOS ``ext4_grow.available``
    says yes once Homebrew's e2fsprogs is installed, but a mode build's delivery
    (``ext4_grow.grow_files_pinned`` and ``mode_install.py``, bash through the Mac executor)
    finds no debugfs on its PATH (Homebrew keeps e2fsprogs keg-only) and uses GNU
    ``stat -c%s``, which BSD stat refuses: no whole file lands while the in-place firmware
    writes do, which is a card not to be used. So modes are refused up front, with a
    sentence."""
    if (platform or sys.platform) == "darwin":
        return MAC_REFUSAL
    return ""


def gate(dest_is_device, ext4_available=None, platform=None):
    """``(ok, why)``: may this build carry modes at all? *ext4_available* is
    ``ext4_grow.available``-shaped and *platform* ``sys.platform``-shaped (injected for
    tests)."""
    if not preview_on():
        return False, PREVIEW_REFUSAL
    if not enabled():
        return False, "%s=0 leaves modes out of this build" % GATE_ENV
    if dest_is_device:
        return False, ("a direct-SD write cannot add files to the card, and a mode adds "
                       "several; build an image file to carry the project's modes")
    host = host_refusal(platform)
    if host:
        return False, host
    if ext4_available is None:
        from ...core import ext4_grow
        ext4_available = ext4_grow.available
    ok, why = ext4_available()
    if not ok:
        return False, "this system cannot write new files into the card image (%s)" % why
    return True, ""


def sound_gate():
    if not sound_enabled():
        return False, "%s=0" % SOUND_ENV
    return True, ""


# ---- the card ----------------------------------------------------------------------------
def scene_rels(prof):
    """``(hud, bank)`` card paths (manifest form, no leading slash) of a title's scenes,
    ``""`` for a part the title cannot do. :func:`.mode_assets.build` adds a screen only
    where ``prof.can("screen")`` and a clip only where ``prof.can("clip")``, so a build never
    reads the other; item 148's TMNT Pro and Deadpool ports name no HUD scene at all, and a
    lookup of ``turtles_pro/assets/lcd/auto_loaded//scene.radium`` refused every mode there."""
    def rel(scene, part):
        if not scene or not prof.can(part):
            return ""
        return "%s/%s/%s/scene.radium" % (prof.game_dir, LCD, scene)
    return rel(prof.hud_scene, "screen"), rel(prof.bank_scene, "clip")


def lookup(reader, card_rel):
    """The inode of *card_rel* on *reader*'s partition, or None."""
    node = reader.read_inode(2)
    for name in card_rel.strip("/").split("/"):
        if not name:
            continue
        if (node["mode"] & 0xF000) != 0x4000:
            return None
        child = next((c for n, c, _t in reader._iter_dir(node) if n == name), None)
        if child is None:
            return None
        node = reader.read_inode(child)
    return node


def _elf_segments(elf):
    if elf[:4] != b"\x7fELF" or elf[4] != 1:
        raise ModeWriteError("the card's game program is not a 32-bit ELF")
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x2A)
    out = []
    for i in range(phnum):
        p_type, p_off, p_vaddr, _pa, p_filesz, _ms, _fl, _al = struct.unpack_from(
            "<8I", elf, phoff + i * phentsize)
        if p_type == 1:
            out.append((p_vaddr, p_off, p_filesz))
    return out


_SITE = re.compile(r"^\s*site\s+(\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)")


def port_sites(port_path):
    """``[(name, address, w0, w1)]`` of a port's ``site`` lines."""
    out = []
    with open(port_path, "r", encoding="utf-8") as f:
        for line in f:
            m = _SITE.match(line)
            if m:
                out.append((m.group(1), int(m.group(2), 16), int(m.group(3), 16),
                            int(m.group(4), 16)))
    return out


def site_mismatches(port_path, elf):
    """The names of a port's sites whose first two instruction words are not the card's.
    Empty = the port was measured on this very program."""
    segs = _elf_segments(elf)
    bad = []
    for name, va, w0, w1 in port_sites(port_path):
        got = None
        for vaddr, off, size in segs:
            if vaddr <= va and va + 8 <= vaddr + size:
                got = struct.unpack_from("<II", elf, off + va - vaddr)
                break
        if got != (w0, w1):
            bad.append(name)
    return bad


def find_port(prof, elf):
    """The SDK port for the card's game program: one for the title's game dir whose every
    site matches the ELF. Raises :class:`ModeWriteError` saying what was tried."""
    tried = []
    for game_dir, version in MR.ports():
        if game_dir != prof.game_dir:
            continue
        path = MR.port_file(game_dir, version)
        if not path:
            continue
        sites = port_sites(path)
        bad = site_mismatches(path, elf)
        if sites and not bad:
            return path
        tried.append("%s %s (%d of %d functions differ)" % (game_dir, version, len(bad), len(sites)))
    raise ModeWriteError(
        "no mode port matches this card's game program%s, so a mode could never start on it"
        % (": tried " + "; ".join(tried) if tried else " (the SDK has none for %s)" % prof.game_dir))


def request_sids(game_elf, image_head, request):
    """The sid chain the game's request table gives *request* (what ``callout N`` plays)."""
    from .info import container_counts
    from .spike2 import sound_requests as SR
    from .spike2.elf import parse_elf
    counts = container_counts(image_head)
    fragments = counts[0] if isinstance(counts, tuple) else counts.get("fragments")
    count, table = SR.locate_sound_requests(game_elf, fragments)
    if table is None:
        return []
    # A request the table does not have (a profile's number out of range, or an
    # unexpected program) names no sound: never read past the table.
    if count is None or not 0 <= int(request) < int(count) \
            or table + (int(request) + 1) * 20 > len(game_elf):
        return []
    segs, _r = parse_elf(game_elf)

    def va2off(va):
        for vaddr, foff, filesz, _m in segs:
            if vaddr <= va < vaddr + filesz:
                return foff + va - vaddr
        return None

    for w in struct.unpack_from("<5I", game_elf, table + request * 20):
        o = va2off(w) if w else None
        if o is None or o <= table:
            continue
        out = []
        for i in range(64):
            if o + 4 * i + 4 > len(game_elf):
                break
            (s,) = struct.unpack_from("<I", game_elf, o + 4 * i)
            if s == 0:
                break
            out.append(s)
        if out:
            return out
    return []


def request_record(game_elf, image_head, params, sites, request, mask):
    """The stock record idx *request* plays: request -> sid chain -> each sid's descriptor
    keys under the build's key *mask* -> the record whose container key it is. Raises
    :class:`ModeWriteError` when the chain does not end at exactly one record."""
    from . import engine as E
    sids = request_sids(game_elf, image_head, request)
    if not sids:
        raise ModeWriteError("the game's request table has no sound for request %d" % request)
    by_key = {bytes(p["findkey"]): p for p in params if p.get("findkey")}
    found = set()
    for sid in sids:
        for s in sites:
            if s.sid == sid:
                p = by_key.get(E._play_key(s.payload, s.sid, mask))
                if p is not None:
                    found.add(p["idx"])
    if not found:
        # A params table cached before whole container keys were recorded carries
        # only their first word (``key0``) - the word the grow path's own
        # named-by-a-descriptor check matches on. The exact eight-byte match
        # happens once the staged bank is derived (_plan_descriptor_repoint).
        by_w1 = {}
        for p in params:
            k0 = p.get("key0")
            if k0 is None and p.get("findkey"):
                k0 = struct.unpack_from("<I", bytes(p["findkey"]))[0]
            if k0 is not None:
                by_w1.setdefault(k0, set()).add(p["idx"])
        for sid in sids:
            for s in sites:
                if s.sid == sid:
                    found |= by_w1.get(struct.unpack_from("<I", s.payload)[0], set())
    if len(found) != 1:
        raise ModeWriteError("request %d (sids %s) names %s, not one sound record"
                             % (request, sids, sorted(found) or "no record"))
    return found.pop()


def sid_record(params, sites, sid, mask):
    """The stock record idx sound id *sid* names (a music bed's sid, item 150 follow-up): its
    descriptor keys under the build's key *mask* -> the record whose container key it is.
    Raises :class:`ModeWriteError` unless that is exactly one record."""
    from . import engine as E
    by_key = {bytes(p["findkey"]): p for p in params if p.get("findkey")}
    found = {by_key[E._play_key(s.payload, s.sid, mask)]["idx"] for s in sites
             if s.sid == sid and E._play_key(s.payload, s.sid, mask) in by_key}
    if len(found) != 1:
        raise ModeWriteError("sid %d names %s, not one sound record" % (sid, sorted(found) or "no record"))
    return found.pop()


# ---- the plan ------------------------------------------------------------------------------
@dataclass
class ModePlan:
    project: str
    profile: object
    port: str
    build: object                                   # mode_assets.ModeBuild
    replaced: list = field(default_factory=list)    # [(card_rel, staged source)]
    new: list = field(default_factory=list)         # [(card_rel, staged source)]
    mode_files: list = field(default_factory=list)  # [(name on p2, staged source)] slot order
    end_sound: dict = None                          # {"slug", "name", "wav", "request"}
    lines: list = field(default_factory=list)       # what the log says was added
    #: the start / shot sounds and music on carriers: [{"slug", "name", "key", "request", ...}]
    own_sounds: list = field(default_factory=list)
    #: the project's CODE modes ([(slug, CodeAssets)]), the object compiled from them ("" = the
    #: pinned one) and their <slug>.assets files [(name on p2, staged source)]
    code: list = field(default_factory=list)
    object: str = ""
    asset_files: list = field(default_factory=list)

    @property
    def jobs(self):
        """Every whole-file copy the modes need on the games partition, stock files
        first, then the new ones."""
        return list(self.replaced) + list(self.new)


def choose_end_sound(project, modes, sound_ok, log=None):
    """``(end_sound or None, [log lines])``. ONE own end sound per card: the time-up request
    is re-pointed for the whole game, so a second mode's sound could never play."""
    log = log or (lambda *a, **k: None)
    with_sound = [(slug, spec) for slug, spec in modes if spec.end_sound]
    if not with_sound:
        return None
    ok, why = sound_ok
    if not ok:
        log("Modes: own end sounds are off for this build (%s); %s end with the game's own "
            "time-up call." % (why, ", ".join(s.name for _g, s in with_sound)), "info")
        return None
    slug, spec = with_sound[0]
    wav = os.path.join(MP.mode_folder(project, slug), spec.end_sound)
    prof = MP.profile(spec.title)
    for _g, other in with_sound[1:]:
        log("Modes: %s has its own end sound too, but a card carries one (the time-up "
            "callout is re-pointed for the whole game); it ends with %s's." % (other.name, spec.name),
            "warning")
    return {"slug": slug, "name": spec.name, "wav": wav, "request": prof.callout_time_up}


#: A mode's own sounds that ride on CARRIERS (item 150): a stock request the game never
#: plays, its record grown to hold the sound. The END call is not one of them: it stays on the
#: title's time-up request (:func:`choose_end_sound`), the path the hardware card proved.
CARRIED_SOUNDS = ("sound_start", "sound_shot", "music")
SOUND_WORDS = {"sound_start": "start sound", "sound_shot": "shot sound", "music": "music"}


def choose_own_sounds(project, modes, sound_ok, end_sound=None, log=None):
    """The start sounds, shot sounds and music a card built from *modes* carries:
    ``[{"slug", "name", "key", "request", "wav", "music"}]`` in slot order, each on its own
    carrier (:func:`.mode_sounds.assign`, one sound at a time with every carrier already
    chosen - the end sound's request too - taken, so no carrier gets two sounds). A sound
    that cannot be carried is left out and logged: the gate closed, a title with no measured
    carriers, or the carriers run out (Godzilla has ONE music carrier, so a second mode's
    music). Nothing is built here."""
    log = log or (lambda *a, **k: None)
    wanted = [(slug, spec, key) for slug, spec in modes for key in CARRIED_SOUNDS
              if getattr(spec, key, "")]
    if not wanted:
        return []
    ok, why = sound_ok
    if not ok:
        log("Modes: own sounds are off for this build (%s); the start sound, shot sound and "
            "music of %s are not put on the card." % (why, _names(wanted)), "info")
        return []
    from . import mode_sounds as MS
    prof = MP.profile(modes[0][1].title)
    game, version = MS.title_version(prof.key)
    if MS.carriers(game, version) is None:
        log("Modes: the start sound, shot sound and music of %s are not put on this card: no "
            "stock requests to carry them have been measured for %s yet."
            % (_names(wanted), prof.label), "warning")
        return []
    taken = [int(end_sound["request"])] if end_sound and end_sound.get("request") else []
    taken_beds = []
    out = []
    for slug, spec, key in wanted:
        try:
            got = MS.assign(game, version, [(key,)], taken=taken, taken_beds=taken_beds)[0]
        except MS.ModeSoundError as e:
            log("Modes: %s's %s is not put on this card: %s." % (spec.name, SOUND_WORDS[key], e),
                "warning")
            continue
        request = got[key]
        taken.append(request)
        entry = {"slug": slug, "name": spec.name, "key": key, "request": int(request),
                 "wav": os.path.join(MP.mode_folder(project, slug), getattr(spec, key)),
                 "music": key == "music"}
        if key == "music" and got.get("music_sid"):
            # item 150 follow-up: the mode's own bed, on the one music carrier, long enough that the
            # mode never reaches the record's own loop
            entry["sid"] = int(got["music_sid"])
            entry["seconds"] = int(getattr(spec, "seconds", 0) or 0)
            taken_beds.append(entry["sid"])
        out.append(entry)
    return out


def _names(wanted):
    seen = []
    for _slug, spec, _key in wanted:
        if spec.name not in seen:
            seen.append(spec.name)
    return ", ".join(seen)


def own_cfg_args(project, slug, spec, own_sounds):
    """``(own_sounds, own_sound_ms)`` for :func:`.mode_project.runtime_cfg` from the build's
    carried sounds (the engine's ``used`` list, each with ``request`` and ``ms``), or
    ``(None, None)`` when this mode carries none."""
    mine = [u for u in own_sounds or () if u.get("slug") == slug]
    if not mine:
        return None, None
    requests = {u["key"]: int(u["request"]) for u in mine}
    for u in mine:
        if u["key"] == "music" and u.get("sid"):
            requests["music_sid"] = int(u["sid"])     # item 150 follow-up: the mode's own bed
    ms = {u["key"]: int(u["ms"]) for u in mine if u.get("ms") and u["key"] != "music"}
    return requests, ms or None


def plan(project, stock_hud, stock_bank, game_elf, scratch, ffmpeg=None, sound_ok=(True, ""),
         log=None, end_sound="choose", own_sounds=None):
    """Build a project's modes against this card's STOCK scenes into *scratch* and say what
    goes where. ``None`` when the project has no modes. Raises :class:`ModeWriteError`.
    *end_sound* is the build's own decision when it has already made one (the engine
    settles it before the sound bank is staged); ``"choose"`` asks
    :func:`choose_end_sound`. *own_sounds* is the engine's list of the start sounds, shot
    sounds and music that went into the bank (each with its carrier ``request``): their
    modes' files name the carriers."""
    from . import mode_assets
    log = log or (lambda *a, **k: None)
    modes = card_modes(project, project_modes(project))
    code = code_mode_list(project)          # the code modes' own assets travel too
    if not modes and not code:
        return None
    titles = {spec.title for _s, spec in modes}
    if len(titles) > 1:
        raise ModeWriteError("every mode on a card must be for the same game")
    try:
        if titles:
            prof = MP.profile(titles.pop())
        else:
            from . import code_modes as CM
            prof = CM.profile_for(project, code)
    except MP.ModeProjectError as e:
        raise ModeWriteError(str(e)) from None
    port = find_port(prof, game_elf)
    if (any(spec.clip != "none" for _s, spec in modes) or any(c.clip for _s, c in code)) and not ffmpeg:
        from ...core.audio import find_ffmpeg
        ffmpeg = find_ffmpeg()
    tree = os.path.join(scratch, "tree")
    try:
        kw = {"code": code, "prof": prof} if code else {}     # a form-mode build is called as before
        build = mode_assets.build(project, stock_hud, stock_bank, tree, ffmpeg=ffmpeg, **kw)
    except (mode_assets.ModeAssetError, MP.ModeProjectError) as e:
        raise ModeWriteError(str(e)) from None
    result = ModePlan(project=project, profile=prof, port=port, build=build)
    for rel in build.files:
        src = os.path.join(tree, *rel.split("/"))
        card = "%s/%s" % (prof.game_dir, rel)
        (result.new if rel in build.new_files else result.replaced).append((card, src))
    for name in build.mode_files:
        result.mode_files.append((name, os.path.join(tree, "padmode", name)))
    result.own_sounds = list(own_sounds or ())
    if result.own_sounds:
        # the modes whose own sounds went into the bank name their carriers (item 150's keys)
        from .mode_assets import mode_file_name
        for slot, (slug, spec) in enumerate(modes):
            requests, ms = own_cfg_args(project, slug, spec, result.own_sounds)
            if not requests:
                continue
            path = os.path.join(tree, "padmode", mode_file_name(slot))
            try:
                text = MP.runtime_cfg(spec, slug, own_sounds=requests, own_sound_ms=ms)
            except MP.ModeProjectError as e:
                raise ModeWriteError("%s: %s" % (spec.name, e)) from None
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    result.end_sound = (choose_end_sound(project, modes, sound_ok, log)
                        if end_sound == "choose" else end_sound)
    result.lines = describe(modes, result, prof=prof)
    if code:
        code_plan(project, result, code, tree, prof, log=log)
        result.lines += describe_code(code, result, prof=prof)
    return result


def describe(modes, result=None, prof=None):
    """One sentence per mode saying what it adds to the card - the log's and the change
    scan's wording. Without a *result* it is what the project would add. *prof* is the
    CARD'S title profile when the caller knows it; without one each mode is read against
    the title its own file names. A part the title cannot do is never promised: TMNT,
    Deadpool and Jaws build no screen and TMNT and Deadpool no clip, whatever the mode
    asks for (item 148, and :func:`.mode_assets.build` does the same)."""
    lines = []
    chosen_sound = None if result is None else (result.end_sound or None)
    for slot, (slug, spec) in enumerate(modes):
        p = prof or _title_profile(spec)
        can_screen = p is None or p.can("screen")
        can_clip = p is None or p.can("clip")
        parts = []
        if spec.screen and can_screen:
            parts.append("its own screen in the game's HUD scene")
        elif spec.screen:
            parts.append("not its own screen (%s cannot add one)" % p.label)
        if spec.clip != "none" and not can_clip:
            parts.append("not its own clip (%s cannot add one)" % p.label)
        elif spec.clip == "title":
            parts.append("a %.0f s title-card clip (a new file)" % float(spec.clip_seconds))
        elif spec.clip == "file":
            parts.append("its own clip %s (a new file)" % spec.clip_file)
        if spec.end_sound:
            chosen = None if result is None else (result.end_sound or {}).get("slug")
            if result is None or chosen == slug:
                parts.append("its own end sound %s" % spec.end_sound)
                if chosen == slug:
                    parts.append("which the game's own time-up call now plays too")
            elif chosen is None:
                parts.append("the game's own time-up call (its own end sound is not on "
                             "this card)")
            else:
                parts.append("another mode's end sound (a card carries one): %s's"
                             % chosen_sound.get("name", "?"))
        elif chosen_sound:
            # every mode ends on the time-up request, which is re-pointed for the whole game
            parts.append("%s's end sound when it ends (the time-up call is re-pointed for "
                         "the whole game)" % chosen_sound.get("name", "?"))
        parts += _own_sound_parts(slug, spec, result)
        from .mode_assets import mode_file_name
        parts.append("mode file %s on the system partition" % mode_file_name(slot))
        lines.append("%s: %s" % (spec.name, ", ".join(parts)))
    return lines


def _title_profile(spec):
    """The profile :func:`describe` writes a mode's line against: the title the mode is on
    NOW, which for a build is the CARD'S (:func:`card_modes` retargets each mode to it,
    item 148), so a line never promises a part that title cannot add. ``None`` when the
    title has no port, and then nothing is left out."""
    try:
        return MP.profile(spec.title)
    except MP.ModeProjectError:
        return None


def _own_sound_parts(slug, spec, result):
    """:func:`describe`'s words for a mode's start sound, shot sound and music: on which
    carrier each goes, or that the card will not carry it."""
    parts = []
    carried = {u["key"]: u for u in (getattr(result, "own_sounds", None) or ())
               if u.get("slug") == slug}
    for key in CARRIED_SOUNDS:
        name = getattr(spec, key, "")
        if not name:
            continue
        if result is None:
            parts.append("its own %s %s" % (SOUND_WORDS[key], name))
        elif key in carried and carried[key].get("sid"):
            # item 150 follow-up: the music carrier plays this mode's own bed while it runs
            parts.append("its own %s %s (request %d, its own bed: sound id %d)"
                         % (SOUND_WORDS[key], name, carried[key]["request"], carried[key]["sid"]))
        elif key in carried:
            parts.append("its own %s %s (request %d)"
                         % (SOUND_WORDS[key], name, carried[key]["request"]))
        else:
            parts.append("not its own %s (this card cannot carry it; the log says why)"
                         % SOUND_WORDS[key])
    return parts


@dataclass
class _EndSoundOnly:
    """What :func:`describe` reads of a plan: the build's end-sound decision."""
    end_sound: dict = None
    own_sounds: list = field(default_factory=list)


def _has_code_modes(project):
    from . import code_modes as CM
    return bool(CM.code_slugs(project))


def describe_code(code, result=None, prof=None):
    """The log's and change scan's line for each CODE mode (:func:`.code_modes.describe`)."""
    from . import code_modes as CM
    carried = None if result is None else list(getattr(result, "own_sounds", None) or ())
    return [CM.describe(slug, spec, carried, prof) for slug, spec in code or ()]


def pending_lines(project, modes=None):
    """The Write change scan's wording for a project's modes: :func:`describe` with the
    decision a build would make about end sounds (ONE per card, none with
    ``PAD_STERN_MODE_SOUND=0``) and about the start sounds, shot sounds and music (a carrier
    each, while the title's carriers last), so a scan never promises a sound the card will
    not carry. The screen and the clip follow the PROJECT'S CARD where its title is
    recorded, so the scan does not promise a screen or a clip to a card whose game cannot
    take one either. Nothing is built and nothing is logged, and the card image is never
    opened: this runs on the UI thread."""
    if modes is None:
        modes = project_modes(project)
    if not modes and not _has_code_modes(project):
        return []
    try:
        _card, prof = MP.project_profile(project)          # probe=False: no image is opened
    except Exception:
        prof = None
    chosen = choose_end_sound(project, modes, sound_gate())
    own = choose_own_sounds(project, modes, sound_gate(), end_sound=chosen)
    lines = describe(modes, _EndSoundOnly(chosen, own), prof=prof)
    try:
        code = code_mode_list(project)
    except ModeWriteError:
        code = []
    if code:
        # the code modes' own sounds as the build would carry them (no image opened: the title
        # is the project card's, else the one the code names)
        cprof = prof or (_title_profile(modes[0][1]) if modes else None) or MP.GODZILLA_PRO_1_15
        req, beds = own_sounds_taken(own)
        if chosen and chosen.get("request"):
            req.append(int(chosen["request"]))
        carried = choose_code_sounds(project, code, sound_gate(), cprof, taken=req, taken_beds=beds)
        lines += describe_code(code, _EndSoundOnly(chosen, list(own) + carried), prof=cprof)
    return lines


def conflicts(result, touched_rels=(), audio_idx=(), sound_idx=None):
    """Why this build cannot carry the modes alongside the project's other edits: another
    edit rewrites the HUD or bank scene the modes are built into, or replaces the sound the
    end sound goes in place of. Empty = none."""
    out = []
    hud, bank = scene_rels(result.profile)
    touched = {r.lstrip("/") for r in touched_rels}
    for rel, what in ((hud, "HUD scene"), (bank, "video bank scene")):
        if rel and rel in touched:
            out.append("another edit in this project changes the %s (%s) the modes' screens "
                       "and clips are built into" % (what, rel))
    if sound_idx is not None and sound_idx in set(audio_idx):
        out.append("sound idx %d is replaced in this project and is also the time-up call a "
                   "mode's own end sound goes in place of" % sound_idx)
    return out


# ---- the manifest ---------------------------------------------------------------------------
def _set_size_total(man, fmt):
    """Store the sum of every record's size where the format keeps it (FI64 ``SZ64``, FINF
    header 0x34), recomputed rather than adjusted, so every refresh before it counts."""
    si = man.find(b"STRS")
    strs_len = struct.unpack_from("<I", man, si + 4)[0]
    pos, tag, total = si + 8 + strs_len, fmt.encode("latin1"), 0
    while pos + 8 <= len(man) and man[pos:pos + 4] == tag:
        rl = struct.unpack_from("<I", man, pos + 4)[0]
        total += sidx_append._record_size(bytes(man[pos + 8:pos + 8 + rl]), fmt)
        pos += 8 + rl
    sz = man.find(b"SZ64")
    if sz >= 0:
        struct.pack_into("<Q", man, sz + 8, total)
    else:
        if total > 0xFFFFFFFF:
            raise ModeWriteError("the manifest's 32-bit size total cannot hold %d" % total)
        struct.pack_into("<I", man, 0x34, total)


def compose_manifest(stock, inplace=(), refreshed=(), new=(), expect_paths=()):
    """The card's manifest with the modes in it, as bytes.

    *inplace* ``[(file_off, bytes)]`` are the other edits' record refreshes, at stock
    offsets (the build folds them in and drops them from its in-place writes, since the
    manifest is now copied whole); *refreshed* ``[(card_rel, source)]`` get their size,
    HMAC and MD5 from the source; the size total is recomputed; *new* ``[(card_rel,
    source)]`` are appended in order. Refuses - nothing is written - unless
    :func:`.sidx_append.verify` passes with every path in *expect_paths* and *new*."""
    man = bytearray(stock)
    for off, b in inplace:
        if off < 0 or off + len(b) > len(man):
            raise ModeWriteError("an edit writes past the end of the manifest (0x%x)" % off)
        man[off:off + len(b)] = b
    recs, _crc, fmt = sidx.parse_records(bytes(man))
    if not recs:
        raise ModeWriteError("the card's .sidx manifest is not one this app can read")
    for rel, src in refreshed:
        if rel not in recs:
            raise ModeWriteError("the manifest has no record for %s" % rel)
        hm, md = sidx.digests_file(src)
        for off, b in sidx.record_field_writes(recs[rel], hm, md, fmt, size=os.path.getsize(src)):
            man[off:off + len(b)] = b
    _set_size_total(man, fmt)
    out = bytes(man)
    for rel, src in new:
        try:
            out = sidx_append.append_file_record(out, rel, src)
        except sidx_append.SidxAppendError as e:
            raise ModeWriteError(str(e)) from None
    want = list(expect_paths) + [r for r, _s in refreshed] + [r for r, _s in new]
    bad = sidx_append.verify(out, expect_paths=want)
    if bad:
        raise ModeWriteError("the rebuilt manifest would not be valid (%s); nothing was written"
                             % "; ".join(bad))
    return out


def fold_writes(writes, extents):
    """Split a build's in-place ``[(disk_offset, bytes)]`` into the ones that land in a
    file whose ``extents`` (``[(disk_offset, length)]`` in file order) are given - returned
    as ``[(file_offset, bytes)]`` - and the rest, untouched. A write that straddles the
    file's edge is refused: it would half-land either way."""
    runs, f_off = [], 0
    for disk, n in extents:
        runs.append((int(disk), int(disk) + int(n), f_off))
        f_off += int(n)
    folded, rest = [], []
    for disk, buf in writes:
        end = disk + len(buf)
        hit = None
        for lo, hi, base in runs:
            if disk < hi and end > lo:
                if disk < lo or end > hi:
                    raise ModeWriteError("an edit at disk offset 0x%x straddles the edge of "
                                         "the manifest's blocks" % disk)
                hit = base + disk - lo
                break
        if hit is None:
            rest.append((disk, buf))
        else:
            folded.append((hit, bytes(buf)))
    return folded, rest


def epoch_at(disk_f, part_offset):
    """:func:`.ext4_grow.partition_epoch` from an open card stream."""
    disk_f.seek(int(part_offset) + 1024)
    sb = disk_f.read(1024)
    if len(sb) < 1024 or sb[0x38:0x3A] != b"\x53\xef":
        raise ModeWriteError("no ext4 superblock at offset %d" % part_offset)
    mtime, wtime = struct.unpack_from("<II", sb, 0x2C)
    return max(mtime, wtime, struct.unpack_from("<I", sb, 0x40)[0])


def p2_offset(disk_f):
    """The system partition's offset: the MBR's second entry, as mode_install finds it."""
    disk_f.seek(0)
    mbr = disk_f.read(512)
    if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
        raise ModeWriteError("the card image has no MBR")
    start, _count = struct.unpack_from("<II", mbr, 0x1BE + 16 + 8)
    return start * 512


# ---- the system partition ---------------------------------------------------------------------
def p2_payload(result, out_dir):
    """Stage what goes in ``/usr/local/padmode``: the pinned object as ``mode.so``, the mode
    files in slot order, the port as ``game.port``. Returns ``{"so", "cfgs", "port"}``."""
    os.makedirs(out_dir, exist_ok=True)
    so = os.path.join(out_dir, "mode.so")
    # A missing file here is a broken install or staging, never "nothing to write":
    # say so as this module's error, so the build stops with the reason.
    try:
        # a project with code modes carries the object compiled from them (code_plan)
        shutil.copyfile(getattr(result, "object", "") or MR.prebuilt_object(), so)
        cfgs = []
        for name, src in result.mode_files:
            dst = os.path.join(out_dir, name)
            shutil.copyfile(src, dst)
            cfgs.append(dst)
        port = os.path.join(out_dir, "game.port")
        shutil.copyfile(result.port, port)
        assets = []
        for name, src in getattr(result, "asset_files", None) or ():
            dst = os.path.join(out_dir, name)
            shutil.copyfile(src, dst)
            assets.append(dst)
    except OSError as e:
        raise ModeWriteError("the modes' system-partition files could not be staged (%s)"
                             % e) from None
    return {"so": so, "cfgs": cfgs, "port": port, "assets": assets}


def tools_dir():
    """``tools/spike2_emu`` (where mode_install.py lives), beside the SDK."""
    return os.path.dirname(os.path.dirname(MR.sdk_dir()))


def install_command(ex, image_path, payload, epoch):
    """The bash command that installs *payload* on *image_path*'s system partition with
    ``mode_install.py`` in the executor's Linux, clock pinned to *epoch*."""
    import shlex
    q = shlex.quote
    # absolute paths: the command changes directory before it runs
    ab = os.path.abspath
    args = ["install", ex.to_exec_path(ab(image_path)), "--so", ex.to_exec_path(ab(payload["so"]))]
    for c in payload["cfgs"]:
        args += ["--cfg", ex.to_exec_path(ab(c))]
    for a in payload.get("assets") or ():
        args += ["--asset", ex.to_exec_path(ab(a))]      # a code mode's <slug>.assets
    args += ["--port", ex.to_exec_path(ab(payload["port"]))]
    return ("cd %s && E2FSPROGS_FAKE_TIME=%d python3 mode_install.py %s"
            % (q(ex.to_exec_path(tools_dir())), int(epoch), " ".join(q(a) for a in args)))


def install_p2(image_path, payload, epoch, log=None, executor=None, timeout=900):
    """Put the payload on the card's system partition (mode_install.py: debugfs, e2fsck
    before and after, a fresh read-back, game_monitor hooked). Returns its report line."""
    log = log or (lambda *a, **k: None)
    if executor is None:
        from ...core.executor import create_executor
        executor = create_executor()
    out = executor.run(install_command(executor, image_path, payload, epoch), timeout=timeout)
    line = next((l for l in out.splitlines() if l.startswith("[mode]")), out.strip())
    log("Modes: %s" % line, "info")
    return line


# ---- Try it: the emulator's set, built by Write's code ----------------------------------------
#
# ONE BUILDER. What a person tries in the emulator must be what Write puts on the card, so
# Try it's override set is the Emulate tab's set (``engine.write_overrides``): the same
# ``_compute_patches`` a card build runs - the screens and clips built from the card's stock
# scenes, the port whose sites match the card's own game program, the manifest composed with
# the modes in it, and a mode's own END SOUND in a grown ``image.bin`` with the sound engine's
# count patch and the validator bypass in the game program. Only the delivery differs: files
# in a folder the rig binds over the card, and the runtime, the port and the mode files BESIDE
# it (``<set>-modes``: ``pad_mode.so``, ``game.port``, ``mode.cfg``, ``mode1.cfg`` ...), the
# stage item 127's ``tools/spike2_emu/modes/tryit.sh install`` takes as it is.
#
# The price of that fidelity is time: a set with an own end sound stages and re-encodes the
# sound bank (about 3 minutes on Godzilla Pro 1.15, most of it the grow and the firmware
# integrity check); without one it is the scenes, the clips and the manifest.

#: Inside Try it's work folder, the set (the stage is beside it, ``set-modes``).
TRYIT_SET = "set"


@dataclass
class TryItSet:
    """A Try it set built by :func:`build_tryit_set` - the fields item 127's tab reads of its
    own ``TrySet`` (set_dir, stage_dir, slots ...), plus what the card build would carry."""
    set_dir: str
    stage_dir: str
    game_dir: str
    version: str
    reused: bool = False                             # patched from the set already there
    files: list = field(default_factory=list)       # games-partition paths in the set
    new_files: list = field(default_factory=list)   # of those, the ones a stock card lacks
    mode_files: list = field(default_factory=list)  # mode.cfg, mode1.cfg ... in slot order
    slots: list = field(default_factory=list)       # [(slot, slug, name)]
    port: str = ""                                   # the stage's game.port
    end_sound: dict = None                           # {"name", "request", "idx"} or None
    counts: tuple = ()
    #: slug -> {"requests": {key: carrier request}, "ms": {key: length}}: the start / shot
    #: sounds and music the set carries (item 150's own sounds, see choose_own_sounds)
    own_sounds: dict = field(default_factory=dict)
    #: the project's CODE modes the set carries, and whether its object was compiled from them
    #: (then the stage's pad_mode.so already holds them: Try it does not compile them again)
    codes: list = field(default_factory=list)
    code_object: bool = False


def _port_version(port_path):
    try:
        with open(port_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "version":
                    return parts[1]
    except OSError:
        pass
    return ""


def build_tryit_set(project, card, base, log=None, progress=None, cancel=None, label=None):
    """Build Try it's set for *project* against the card image *card* in ``<base>/set``, with
    the object, the port and the mode files in ``<base>/set-modes``, through
    ``engine.write_overrides`` - Write's own code. Returns a :class:`TryItSet`, or ``None``
    when *cancel* stopped it. Raises :class:`ModeWriteError` with a sentence for the person.

    *log* may take ``(message)`` or ``(message, level)``. The set carries every edit of the
    project, as Write would: a card with the modes and without the rest does not exist."""
    from . import engine as E
    say = log or (lambda *a, **k: None)

    def elog(msg, level="info", *a, **k):
        try:
            say(msg, level)
        except TypeError:
            say(msg)

    if not preview_on():
        raise ModeWriteError("Try it needs the mode maker, a preview feature that is not "
                             "switched on in this copy of the app (Settings > Preview features).")
    if not project or not os.path.isdir(project):
        raise ModeWriteError("Open or extract a card project first: modes live in it.")
    modes = card_modes(project, project_modes(project))
    code = code_mode_list(project)          # code modes with their own assets go through Write too
    if not modes and not code:
        raise ModeWriteError("There are no modes in this project to try.")
    if not card or not os.path.isfile(card):
        raise ModeWriteError("Pick the card image to try the modes on first.")
    set_dir = os.path.join(base, TRYIT_SET)
    os.makedirs(base, exist_ok=True)
    try:
        got = E.write_overrides(card, project, set_dir, log=elog, progress=progress,
                                cancel=cancel, label=label)
    except (RuntimeError, OSError, ValueError) as e:
        raise ModeWriteError(str(e)) from None
    counts = got[0]
    if counts is None:
        return None
    listed = E.read_override_manifest(set_dir) or {}
    carried = listed.get("modes") or {}
    if not carried:
        raise ModeWriteError("the set was built without the project's modes (the log says "
                             "why), so there is nothing of them to try")
    stage = carried.get("dir") or (set_dir.rstrip("\\/") + E.OVERRIDE_MODES_SUFFIX)
    port = os.path.join(stage, "game.port")
    if modes:
        prof = MP.profile(modes[0][1].title)
    else:
        from . import code_modes as CM
        prof = CM.profile_for(project, code)
    from .mode_assets import mode_file_name
    result = TryItSet(
        set_dir=set_dir, stage_dir=stage, game_dir=prof.game_dir, version=_port_version(port),
        reused=bool(listed.get("parent")),
        files=[r.get("path", "").lstrip("/") for r in listed.get("files") or ()],
        new_files=[str(r).strip("/") for r in carried.get("added") or ()],
        mode_files=[n for n in carried.get("files") or () if n.endswith(".cfg")],
        slots=[(slot, slug, spec.name) for slot, (slug, spec) in enumerate(modes)],
        port=port, end_sound=carried.get("end_sound"), counts=tuple(counts),
        own_sounds=own_sounds_by_slug(carried.get("own_sounds")),
        codes=[slug for slug, _c in code],
        code_object=bool(carried.get("code_object")))
    if [mode_file_name(s) for s, _g, _n in result.slots] != result.mode_files:
        raise ModeWriteError("the set's mode files %s do not match the project's %d mode(s)"
                             % (result.mode_files, len(result.slots)))
    return result


def own_sounds_by_slug(used):
    """A build record's ``own_sounds`` list (``[{"slug", "key", "request", "ms", ...}]``) as
    ``{slug: {"requests": {key: request}, "ms": {key: ms}}}`` - what ``runtime_cfg`` takes."""
    out = {}
    for u in used or ():
        slug, key = u.get("slug"), u.get("key")
        if not slug or not key:
            continue
        got = out.setdefault(slug, {"requests": {}, "ms": {}})
        got["requests"][key] = int(u.get("request"))
        if u.get("ms"):
            got["ms"][key] = int(u["ms"])
    return out


def tryit_env(set_dir, guest_object="/lib/pad_mode.so"):
    """What a Try it run adds to the Emulate tab's launch (item 127's ``try_env``): the set
    bound over the card, and the runtime ``tryit.sh install`` put in the guest's /lib."""
    p = (set_dir or "").replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return ["PAD_OVERRIDE_DIR=%s" % p, "PAD_MODE_SO=%s" % guest_object]


# ---- CODE modes carry their own assets (the intricate modes' own audio and video) ----------------
#
# A code mode (modes/<slug>/<slug>.c, :mod:`.code_modes`) used to reach Try it only. Write now
# carries it the way it carries a form mode: its screen and clip into the HUD scene and bank (the
# same :func:`.mode_assets.build` pass), its music on a bed and each call on a carrier of its own
# (the same :func:`choose_own_sounds` allocator and the engine's grow), and on the system partition
# the object COMPILED from the project's code modes with the mode-file interpreter (instead of the
# pinned one) and one ``<slug>.assets`` per code mode naming what the build carried.

def code_mode_list(project):
    """``[(slug, CodeAssets)]`` of the project's code modes. Raises :class:`ModeWriteError`
    naming a code mode whose assets.json does not load (never dropped quietly)."""
    from . import code_modes as CM
    if not project:
        return []
    try:
        return CM.list_code(project)
    except CM.CodeModeError as e:
        raise ModeWriteError(str(e)) from None


def sound_words(key):
    """The log's words for an own-sound key: a form mode's (``SOUND_WORDS``) or a code mode's call
    (``call:<cue>`` -> "<cue> call")."""
    if str(key).startswith("call:"):
        return "%s call" % str(key)[5:]
    return SOUND_WORDS.get(key, key)


def choose_code_sounds(project, code, sound_ok, prof, taken=(), taken_beds=(), log=None):
    """The music and calls a card built from the project's CODE modes carries, each on a carrier
    of its own from the same allocator as the form modes' (:func:`.mode_sounds.assign`, with every
    carrier and bed already chosen passed as taken): ``[{"slug", "name", "key", "request", "wav",
    "music", ["sid", "seconds"]}]``. A sound that cannot be carried is left out and logged; the
    mode then plays the game's own call for it (``pa_call`` returns 0)."""
    from . import code_modes as CM
    from . import mode_sounds as MS
    log = log or (lambda *a, **k: None)
    wants = CM.sound_wants(project, code)
    if not wants:
        return []
    ok, why = sound_ok
    if not ok:
        log("Modes: own sounds are off for this build (%s); the music and calls of the code mode(s) "
            "%s are not put on the card." % (why, ", ".join(sorted({w["name"] for w in wants}))), "info")
        return []
    game, version = MS.title_version(prof.key)
    if MS.carriers(game, version) is None:
        log("Modes: the music and calls of the code mode(s) are not put on this card: no stock "
            "requests to carry them have been measured for %s yet." % prof.label, "warning")
        return []
    taken, taken_beds, out = [int(t) for t in taken], [int(b) for b in taken_beds], []
    for w in wants:
        kind = "music" if w["music"] else "sound_start"
        try:
            got = MS.assign(game, version, [(kind,)], taken=taken, taken_beds=taken_beds)[0]
        except MS.ModeSoundError as e:
            log("Modes: %s's %s is not put on this card: %s." % (w["name"], sound_words(w["key"]), e), "warning")
            continue
        entry = dict(w, request=int(got[kind]))
        taken.append(entry["request"])
        if w["music"] and got.get("music_sid"):
            entry["sid"] = int(got["music_sid"])
            taken_beds.append(entry["sid"])
        entry.pop("priority", None)
        out.append(entry)
    return out


def own_sounds_taken(own):
    """``(requests, beds)`` already carrying a sound in *own* (the engine's list)."""
    return ([int(u["request"]) for u in own or () if u.get("request") and not u.get("sid")],
            [int(u["sid"]) for u in own or () if u.get("sid")])


#: The compiler lives in the app's Linux (the PAD-Runtime distro on Windows), as for Try it.
BUILD_MODE = "build_mode.sh"


def compile_command(ex, out, sources):
    """The bash command that builds *sources* (the code modes' .c files) with the mode-file
    interpreter into *out*, through ``sdk/build_mode.sh`` in the executor's Linux."""
    import shlex
    q = shlex.quote
    ab = os.path.abspath
    sdk = MR.sdk_dir()
    args = [ex.to_exec_path(ab(os.path.join(sdk, BUILD_MODE))), "-o", ex.to_exec_path(ab(out))]
    args += [ex.to_exec_path(ab(s)) for s in sources]
    args.append(ex.to_exec_path(ab(os.path.join(sdk, "mode_file.c"))))
    return "bash " + " ".join(q(a) for a in args)


def compile_code_object(sources, out, log=None, executor=None, timeout=600):
    """Build the object a card with code modes carries: the runtime, every code mode and the
    mode-file interpreter (so the project's form modes run beside them). Returns *out*. Raises
    :class:`ModeWriteError` with the compiler's words when it fails."""
    say = log or (lambda *a, **k: None)
    if executor is None:
        from ...core.executor import create_executor
        executor = create_executor()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    try:
        said = executor.run(compile_command(executor, out, sources), timeout=timeout)
    except Exception as e:                   # the executor's CommandError, a missing WSL
        raise ModeWriteError("the code modes did not build: %s" % str(e)[-600:]) from None
    if not os.path.isfile(out):
        raise ModeWriteError("the code modes did not build (no object was written): %s"
                             % (said or "").strip()[-400:])
    say("Modes: built the code mode(s) %s into the card's mode.so with the mode-file interpreter (%d bytes)."
        % (", ".join(os.path.splitext(os.path.basename(s))[0] for s in sources), os.path.getsize(out)), "info")
    return out


def code_plan(project, result, code, tree, prof, log=None):
    """Fill *result* (a :class:`ModePlan`) with the CODE modes: the compiled object and one
    ``<slug>.assets`` per code mode naming its screen, its clip and the own sounds the engine
    carried (``result.own_sounds``). Code modes' screens and clips are already in ``result.build``."""
    from . import code_modes as CM
    if not code:
        return result
    padmode = os.path.join(tree, "padmode")
    os.makedirs(padmode, exist_ok=True)
    for slug, spec in code:
        text = CM.runtime_text(slug, spec, prof, own_sounds=result.own_sounds,
                               screen=bool(spec.screen and prof.can("screen")),
                               clip=bool(spec.clip and prof.can("clip")))
        path = os.path.join(padmode, slug + CM.RUNTIME_SUFFIX)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        result.asset_files.append((slug + CM.RUNTIME_SUFFIX, path))
    result.code = list(code)
    result.object = compile_code_object([CM.source_path(project, s) for s, _c in code],
                                        os.path.join(tree, "padmode_obj", "mode.so"), log=log)
    return result
