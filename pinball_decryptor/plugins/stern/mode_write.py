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

import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
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
    (item 127's New code mode). Write carries them as it carries the form modes: compiled
    into the card's ``mode.so`` (:func:`code_plan`), each with its ``<slug>.assets`` and its
    own screen, clip and sounds through the same set. The change scan names them beside the
    form modes (:func:`pending_lines`); only a build that leaves every mode out says they
    are not put on the card (:func:`code_modes_note`)."""
    root = MP.modes_dir(project) if project else ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [slug for slug in names
            if os.path.isfile(os.path.join(root, slug, slug + ".c"))
            and not os.path.isfile(os.path.join(root, slug, MP.MODE_FILE))]


def code_modes_note(slugs, why=None):
    """The change scan's one line for the code modes when THIS build leaves every mode out:
    a code mode goes on the card with the modes, so it stays off with them. *why* is the
    build's own reason when the caller has it (the gate's sentence, the Direct-SD refusal,
    the host refusal); without it the line names the three ways a build leaves modes out,
    because a project of code modes alone has no form-mode rows to point at."""
    if not why:
        why = ("the modes gate is off, a Direct-SD write cannot add files to the card, or "
               "this computer cannot put a mode's files on a card")
    return ("code mode(s) %s are not put on the card: this build leaves every mode out (%s), "
            "and a code mode goes on the card with the modes" % (", ".join(slugs), why))


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


def card_refusal(project, probe=True, real_card=False):
    """Why the PROJECT'S CARD cannot carry any mode, or ``""``: the project names a card
    whose game build has no port (shipped, or derived on this machine), so neither a form
    mode nor a code mode can run on it. A Write then leaves the modes out with this reason
    and writes everything else, instead of refusing the whole build. ``probe=True`` may open
    the card image (a renamed card's index): a build calls it that way, never the UI
    thread.

    ``real_card=True`` (a Write to a card or an image, not Try it's set for the emulator): a
    port DERIVED on this machine that no Try it has run live yet (:func:`derived_not_run`)
    refuses too. Its every entry was worked out from the program alone, so it goes on a real
    card only after the emulator has run the game with it."""
    if not project:
        return ""
    try:
        card, prof = MP.project_profile(project, probe=probe)
    except (OSError, ValueError):
        return ""
    if card is None or not card.game_dir:
        return ""
    if prof is None:
        return MP.no_port_words(MP.title_label(card.game_dir, card.version))
    if real_card and derived_not_run(prof):
        return try_it_first_words(prof.label)
    return ""


def derived_not_run(prof):
    """Is ``prof``'s port one derived on this machine that no Try it has run live yet?"""
    from . import port_derive
    path = MP.port_path(prof) if prof is not None else ""
    return bool(path) and port_derive.is_derived(path) and not port_derive.ran_live(path)


def try_it_first_words(label):
    """The sentence for modes left out of a Write because :func:`derived_not_run`."""
    return ("the app worked out how to run modes on %s by itself, and they have not run in the "
            "emulator on this PC yet. Press Try it once first (Modes tab), then Write again: "
            "until a Try it has run the game with them, a card gets no modes." % label)


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
    def rel(scene, part, which):
        if not scene or not prof.can(part):
            return ""
        return "%s/%s/scene.radium" % (prof.game_dir, prof.lcd(which))
    return rel(prof.hud_scene, "screen", "hud"), rel(prof.bank_scene, "clip", "bank")


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


def port_unproven(port_path):
    """True when a port's header says it has never run (:data:`.mode_project.UNPROVEN_MARK`:
    drafted by hand, or derived on this machine)."""
    try:
        with open(port_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if not s.startswith("#"):
                    return False
                if MP.UNPROVEN_MARK in s:
                    return True
    except OSError:
        return True
    return False


def _same_file(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def find_port(prof, elf):
    """The port for the card's game program: one for the title's game dir whose every site
    matches the ELF, shipped ones first, then those derived on this machine
    (:func:`.mode_runtime.port_dirs`). Raises :class:`ModeWriteError` saying what was tried.

    A port that has never run (:func:`port_unproven`; every port derived on this machine is
    one) is taken only when it IS the profile's own port: the person chose that build's title
    and was told it is unproven. Modes made for another build are never quietly written with
    one; they are refused, naming the build to make them for."""
    tried, unproven = [], []
    own = MP.port_path(prof)
    for game_dir, version, path in MR.port_paths():
        if game_dir != prof.game_dir:
            continue
        sites = port_sites(path)
        bad = site_mismatches(path, elf)
        if sites and not bad:
            if not port_unproven(path) or _same_file(path, own):
                return path
            unproven.append(version)
            continue
        tried.append("%s %s (%d of %d functions differ)" % (game_dir, version, len(bad), len(sites)))
    if unproven:
        label = MP.title_label(prof.game_dir, unproven[0])
        raise ModeWriteError(
            "this card is %s, and what the app knows of how to run modes on it has never run in "
            "the emulator, and these modes were made for %s; make them for %s to write them to "
            "this card" % (label, prof.label, label))
    raise ModeWriteError(
        "what the app knows of how to run modes on %s does not match this card's game "
        "program, so a mode could never start on it%s"
        % (prof.label, " (tried: " + "; ".join(tried) + ")" if tried else ""))


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


def request_records_all(game_elf, image_head, params, sites, request, mask):
    """Every stock record idx *request* can play, in its sid list's order (item 163): a
    time-up call with variants ("Time's up." / "Your time is up!" ...) names one record per
    variant, and a mode's own end sound goes in place of each, so whichever the game picks
    plays it. Raises :class:`ModeWriteError` when a sid names no record or more than one."""
    from . import engine as E
    sids = request_sids(game_elf, image_head, request)
    if len(sids) <= 1:
        return [request_record(game_elf, image_head, params, sites, request, mask)]
    by_key = {bytes(p["findkey"]): p["idx"] for p in params if p.get("findkey")}
    out = []
    for sid in sids:
        found = {by_key[E._play_key(s.payload, s.sid, mask)] for s in sites
                 if s.sid == sid and E._play_key(s.payload, s.sid, mask) in by_key}
        if len(found) != 1:
            raise ModeWriteError("request %d's sid %d names %s, not one sound record"
                                 % (request, sid, sorted(found) or "no record"))
        idx = found.pop()
        if idx not in out:
            out.append(idx)
    return out


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
    #: item 160: the "counts as" table for the game's own rules (``stock.cfg`` beside the mode
    #: files), or "" when the project has no rows
    stock_file: str = ""

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
    if end_on_carrier(prof):
        return None         # item 164: each mode's end sound rides a carrier (choose_own_sounds)
    for _g, other in with_sound[1:]:
        log("Modes: %s has its own end sound too, but a card carries one (the time-up "
            "callout is re-pointed for the whole game); it ends with %s's." % (other.name, spec.name),
            "warning")
    return {"slug": slug, "name": spec.name, "wav": wav, "request": prof.callout_time_up}


#: A mode's own sounds that ride on CARRIERS (item 150): a stock request the game never
#: plays, its record grown to hold the sound. The END call is not one of them: it stays on the
#: title's time-up request (:func:`choose_end_sound`), the path the hardware card proved.
CARRIED_SOUNDS = ("sound_start", "sound_shot", "music")
SOUND_WORDS = {"sound_start": "start sound", "sound_shot": "shot sound", "music": "music",
               "sound_end": "end sound"}
#: the spec field each carried sound's WAV is in (the end sound's is ``end_sound``)
_SPEC_FIELD = {"sound_end": "end_sound"}


def end_on_carrier(prof):
    """item 164: a title whose time-up callout is not known carries a mode's END sound on a
    carrier too (mode_file.c ``sound_end``), one per mode, instead of re-pointing the time-up
    request - :func:`.mode_project.end_sound_carried`."""
    return not prof.callout_time_up


def carried_keys(prof):
    """The sound keys a build puts on carriers for *prof*'s title."""
    return CARRIED_SOUNDS + (("sound_end",) if end_on_carrier(prof) else ())


def _wav_name(spec, key):
    return getattr(spec, _SPEC_FIELD.get(key, key), "")


def choose_own_sounds(project, modes, sound_ok, end_sound=None, log=None):
    """The start sounds, shot sounds and music a card built from *modes* carries:
    ``[{"slug", "name", "key", "request", "wav", "music"}]`` in slot order, each on its own
    carrier (:func:`.mode_sounds.assign`, one sound at a time with every carrier already
    chosen - the end sound's request too - taken, so no carrier gets two sounds). A sound
    that cannot be carried is left out and logged: the gate closed, a title with no measured
    carriers, or the carriers run out (Godzilla has ONE music carrier, so a second mode's
    music). Nothing is built here."""
    log = log or (lambda *a, **k: None)
    if not modes:
        return []
    prof = MP.profile(modes[0][1].title)
    wanted = [(slug, spec, key) for slug, spec in modes for key in carried_keys(prof)
              if _wav_name(spec, key)]
    if not wanted:
        return []
    ok, why = sound_ok
    if not ok:
        log("Modes: own sounds are off for this build (%s); the start sound, shot sound and "
            "music of %s are not put on the card." % (why, _names(wanted)), "info")
        return []
    from . import mode_sounds as MS
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
                 "wav": os.path.join(MP.mode_folder(project, slug), _wav_name(spec, key)),
                 "music": key == "music"}
        if key == "music" and got.get("music_sid"):
            # item 150 follow-up: the mode's own bed, on the one music carrier, long enough that the
            # mode never reaches the record's own loop
            entry["sid"] = int(got["music_sid"])
            entry["seconds"] = int(getattr(spec, "seconds", 0) or 0)
            taken_beds.append(entry["sid"])
        if MS.carriers(game, version).swap:
            entry["swap"] = True        # item 163: swapped in at run time, no stock sound id changes
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
        if u.get("stock_key") and u.get("our_key"):
            # item 163: the mode swaps its own record in on this carrier
            requests.setdefault("swaps", []).append((int(u["request"]), u["stock_key"], u["our_key"]))
    ms = {u["key"]: int(u["ms"]) for u in mine if u.get("ms") and u["key"] != "music"}
    return requests, ms or None


def mode_file_text(project, slug, spec, own_sounds):
    """The runtime mode file a build writes for the mode *slug*: :func:`.mode_project.runtime_cfg`
    naming the carriers of its own sounds in *own_sounds* (the build's carried list), or as
    :func:`.mode_assets.build` writes it for a mode that carries none. What :func:`plan` writes,
    and what a settings-only Try it writes again (:func:`tryit_settings_only`)."""
    requests, ms = own_cfg_args(project, slug, spec, own_sounds)
    try:
        if not requests:
            return MP.runtime_cfg(spec, slug)
        return MP.runtime_cfg(spec, slug, own_sounds=requests, own_sound_ms=ms)
    except MP.ModeProjectError as e:
        raise ModeWriteError("%s: %s" % (spec.name, e)) from None


def plan(project, stock_hud, stock_bank, game_elf, scratch, ffmpeg=None, sound_ok=(True, ""),
         log=None, end_sound="choose", own_sounds=None, progress=None, stock_font=b""):
    """Build a project's modes against this card's STOCK scenes into *scratch* and say what
    goes where. ``None`` when the project has no modes. Raises :class:`ModeWriteError`.
    *end_sound* is the build's own decision when it has already made one (the engine
    settles it before the sound bank is staged); ``"choose"`` asks
    :func:`choose_end_sound`. *own_sounds* is the engine's list of the start sounds, shot
    sounds and music that went into the bank (each with its carrier ``request``): their
    modes' files name the carriers. *progress* ``(done, total, words)`` follows the clips."""
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
            if prof is None:
                raise ModeWriteError(CM.NO_TITLE)
    except MP.ModeProjectError as e:
        raise ModeWriteError(str(e)) from None
    port = find_port(prof, game_elf)
    if (any(spec.clip != "none" for _s, spec in modes) or any(c.clip for _s, c in code)) and not ffmpeg:
        from ...core.audio import find_ffmpeg
        ffmpeg = find_ffmpeg()
    tree = os.path.join(scratch, "tree")
    try:
        kw = {"code": code, "prof": prof} if code else {}     # a form-mode build is called as before
        if stock_font:
            kw["stock_font"] = stock_font
        if progress is not None:
            kw["progress"] = progress
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
            if not own_cfg_args(project, slug, spec, result.own_sounds)[0]:
                continue
            path = os.path.join(tree, "padmode", mode_file_name(slot))
            text = mode_file_text(project, slug, spec, result.own_sounds)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    result.end_sound = (choose_end_sound(project, modes, sound_ok, log)
                        if end_sound == "choose" else end_sound)
    result.lines = describe(modes, result, prof=prof)
    if not getattr(prof, "proven", True):
        # find_port takes a port that never ran only as the profile's own: say so in the log
        from . import port_derive
        try:
            live = port_derive.ran_live(MP.port_path(prof))
        except Exception:                           # noqa: BLE001 - the plainer sentence then
            live = False
        if live:
            result.lines.append("what the app worked out of how to run modes on %s has run in the "
                                "emulator on this PC (a Try it), not yet on a machine" % prof.label)
        else:
            result.lines.append("what the app knows of how to run modes on %s has never run in the "
                                "emulator, so they may not start on this card" % prof.label)
    if code:
        code_plan(project, result, code, tree, prof, log=log)
        result.lines += describe_code(code, result, prof=prof, project=project)
    stock_plan(project, result, tree)
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
        if spec.end_sound and p is not None and end_on_carrier(p):
            # item 164: no time-up callout known - the end sound rides a carrier of its own
            mine = [u for u in (getattr(result, "own_sounds", None) or ())
                    if u.get("slug") == slug and u.get("key") == "sound_end"]
            if result is None:
                parts.append("its own end sound %s" % spec.end_sound)
            elif mine:
                parts.append("its own end sound %s (request %d)" % (spec.end_sound, mine[0]["request"]))
            else:
                parts.append("not its own end sound (this card cannot carry it; the log says why)")
        elif spec.end_sound:
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


def describe_code(code, result=None, prof=None, project=None):
    """The log's and change scan's line for each CODE mode (:func:`.code_modes.describe`); with
    *project*, a code mode that rewrites one of the game's own rules (item 161,
    :mod:`.stock_rewrite`) says which."""
    from . import code_modes as CM
    from . import stock_rewrite as SW
    carried = None if result is None else list(getattr(result, "own_sounds", None) or ())
    port = MP.port_path(prof) if project and prof is not None and getattr(prof, "port", None) else None
    return [CM.describe(slug, spec, carried, prof) + (SW.describe_suffix(project, slug, port) if project else "")
            for slug, spec in code or ()]


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
        return stock_lines(project, carried=False)
    try:
        _card, prof = MP.project_profile(project)          # probe=False: no image is opened
    except Exception:
        prof = None
    refused = card_refusal(project, probe=False, real_card=True)
    if refused:
        # the project's card has no port (or one no Try it has run yet): a Write leaves every
        # mode out and writes the rest (the engine's own decision), so the scan promises none
        refused = refused[:1].upper() + refused[1:]
        try:
            code = code_mode_list(project)
        except ModeWriteError:
            code = []
        return (["%s: not put on the card. %s" % (spec.name, refused) for _s, spec in modes]
                + ["%s (code mode): not put on the card. %s" % (c.name, refused)
                   for _s, c in code])
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
        cprof = prof or (_title_profile(modes[0][1]) if modes else None) or _code_title(code)
        if cprof is None:
            from . import code_modes as CM
            return lines + ["%s (code mode): not put on the card. %s" % (c.name, CM.NO_TITLE)
                            for _s, c in code]
        req, beds = own_sounds_taken(own)
        if chosen and chosen.get("request"):
            req.append(int(chosen["request"]))
        carried = choose_code_sounds(project, code, sound_gate(), cprof, taken=req, taken_beds=beds)
        lines += describe_code(code, _EndSoundOnly(chosen, list(own) + carried), prof=cprof, project=project)
    lines += stock_lines(project, carried=True, prof=prof)
    return lines


def _code_title(code):
    """The title the first code mode names (its assets' ``title``), or None: what
    :func:`.code_modes.profile_for` falls back to, without opening a card image."""
    for _slug, spec in code or ():
        key = (getattr(spec, "extra", None) or {}).get("title")
        if key:
            try:
                return MP.profile(key)
            except MP.ModeProjectError:
                return None
    return None


#: The change scan's and the Write log's words for a counts-as table with no mode to ride with.
COUNTS_AS_NEEDS_A_MODE = ("Counts as: the %d row(s) in modes/stock.json are NOT written: the table rides "
                          "with the modes' runtime, which a build puts on the card only with at least one "
                          "mode (add a mode, or a rewrite in C, and Write again)")


def stock_lines(project, carried, prof=None):
    """Item 160: the change scan's line for the project's counts-as rows (``modes/stock.json``):
    what the table adds when a mode carries it (:func:`.stock_remap.describe`), or that it is NOT
    written when nothing carries it (``carried=False``: the project has no mode and no code mode,
    so no runtime goes on the card and :func:`stock_plan` is never reached). Nothing is opened but
    the project's files and the port; never raises."""
    try:
        from . import stock_remap as SR
        rows = SR.load(project)
    except Exception:                                    # noqa: BLE001
        rows = []
    if not rows:
        return []
    if not carried:
        return [COUNTS_AS_NEEDS_A_MODE % len(rows)]
    if prof is None:
        try:
            _card, prof = MP.project_profile(project)    # probe=False: no image is opened
        except Exception:                                # noqa: BLE001
            prof = None
    port = MP.port_path(prof) if prof is not None and getattr(prof, "port", "") else ""
    if not port or not os.path.isfile(port):
        return ["Counts as: %d row(s) (stock.cfg) for the card's port" % len(rows)]
    try:
        return [SR.describe(rows, SR.port_rules(port), SR.port_shots(port))]
    except Exception:                                    # noqa: BLE001
        return ["Counts as: %d row(s) (stock.cfg) for the card's port" % len(rows)]


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
        extras = []                                  # item 160: stock.cfg, the counts-as table
        if getattr(result, "stock_file", ""):
            from . import stock_remap as SR
            dst = os.path.join(out_dir, SR.FILE_NAME)
            shutil.copyfile(result.stock_file, dst)
            extras.append(dst)
    except OSError as e:
        raise ModeWriteError("the modes' system-partition files could not be staged (%s)"
                             % e) from None
    return {"so": so, "cfgs": cfgs, "port": port, "assets": assets, "extras": extras}


def stock_plan(project, result, tree):
    """Item 160: render the project's counts-as rows (``modes/stock.json``) for the card's port
    into ``<tree>/padmode/stock.cfg`` and name it in *result*; nothing when there are none.
    A row the port cannot take stops the build with the reason."""
    from . import stock_remap as SR
    rows = SR.load(project)
    if not rows:
        return result
    padmode = os.path.join(tree, "padmode")
    os.makedirs(padmode, exist_ok=True)
    path = os.path.join(padmode, SR.FILE_NAME)
    try:
        n = SR.write_file(project, result.port, path)
    except SR.StockRemapError as e:
        raise ModeWriteError("the game's own rules' counts-as table: %s" % e) from None
    if n:
        result.stock_file = path
        result.lines.append(SR.describe(rows, SR.port_rules(result.port), SR.port_shots(result.port)))
    return result


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
    for a in payload.get("extras") or ():
        args += ["--file", ex.to_exec_path(ab(a))]       # item 160: stock.cfg
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
    reused: bool = False                             # handed back unbuilt (the sidecar test)
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


#: Beside the set, never inside it (``run_game.sh`` binds every file in a set): what the
#: last Try it was built from, so the next one can hand the set back unbuilt.
TRYIT_SIDECAR = "set.tryit.json"
TRYIT_SIDECAR_VERSION = 1
#: The log's one line for a set handed back as it is.
TRYIT_REUSED = ("nothing of the modes, the edits or the cards changed since the last Try it, "
                "so the set is used as it is")


def _card_identity(path):
    """``{path, size, mtime}`` for a card image (the identity the engine's manifest and the
    rig's own card cache key on), or None when it cannot be read."""
    try:
        st = os.stat(path)
    except (OSError, TypeError):
        return None
    return {"path": os.path.abspath(str(path)), "size": st.st_size, "mtime": int(st.st_mtime)}


def modes_fingerprint(project):
    """Every file under ``<project>/modes`` as ``[relpath, mtime_ns, size]``, sorted: what a
    mode edit, a new WAV beside one or a deleted mode changes. A walk of a few small files,
    no hashing. Pure, and the same idea as the Write tab's own modes fingerprint
    (``main_window._modes_write_fingerprint``), reimplemented here so no plugin imports the
    window; posix relpaths, so a sidecar written on Windows still reads on Linux."""
    out = []
    root = MP.modes_dir(project) if project else ""
    if not root or not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append([os.path.relpath(p, root).replace("\\", "/"), st.st_mtime_ns, st.st_size])
    return sorted(out)


def assets_fingerprint(assets_dir):
    """``"<files> <newest-mtime>"`` for everything under *assets_dir*: the Emulate tab's own
    "have the edits moved?" question (``emulate_tab.assets_fingerprint``), reimplemented
    here because that one lives in a Tk module. A stat walk, no hashing, because a project
    is a whole extract; compared for EQUALITY, because a build writes its hash cache back
    into the folder, so the value kept is the one taken AFTER the build, and a file put
    back from an older copy moves it too."""
    return _assets_fingerprints(assets_dir)[0]


def _assets_fingerprints(assets_dir, apart=None):
    """``(whole, rest)``: :func:`assets_fingerprint` of *assets_dir*, and the same of it without
    the folder *apart* (``None``: ``rest`` is ``None``), in one walk."""
    apart = os.path.normcase(os.path.abspath(apart)) if apart else None
    newest, count = 0, 0
    r_newest, r_count = 0, 0
    for root, _dirs, files in os.walk(assets_dir):
        inside = apart is not None and (
            os.path.normcase(os.path.abspath(root)) + os.sep).startswith(apart + os.sep)
        for name in files:
            count += 1
            if not inside:
                r_count += 1
            try:
                m = os.stat(os.path.join(root, name)).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
            if not inside and m > r_newest:
                r_newest = m
    return ("%d %.6f" % (count, newest),
            "%d %.6f" % (r_count, r_newest) if apart is not None else None)


def tryit_sidecar(base):
    return os.path.join(base, TRYIT_SIDECAR)


def _build_env():
    """Every ``PAD_STERN_*`` variable of the build's environment, sorted: the app mirrors its
    build options into them (the text grow, the blip-free callouts, the audio grow ...), and
    a set built under another option is not the set this build would make. The engine's own
    caches key on the same variables (``_audio_cache_base_key``)."""
    return sorted([k, v] for k, v in os.environ.items() if k.startswith("PAD_STERN_"))


def _tryit_record(base_card, card, project, sound_ok):
    """What the reuse test compares: the two cards' identities, the project, the gates, the
    build's options and the app's version, and the two fingerprints. Everything in it is
    JSON, so a read-back compares equal."""
    from ... import __version__
    modes = modes_fingerprint(project)
    whole, rest = _assets_fingerprints(project, apart=MP.modes_dir(project))
    return {
        "version": TRYIT_SIDECAR_VERSION,
        "base_card": _card_identity(base_card),
        "run_card": _card_identity(card),
        "assets": os.path.normcase(os.path.abspath(project)),
        "sound_ok": sound_ok,
        "preview": bool(preview_on()),
        "gates": [bool(enabled()), bool(sound_enabled())],
        "env": _build_env(),
        "app": __version__,
        "modes": modes,
        "assets_fingerprint": whole,
        # for the settings-only test (tryit_settings_only): each mode file as it reads, the
        # rest of the modes' folders, and the project without its modes
        "mode_json": _mode_json_dicts(project),
        "modes_other": [e for e in modes if e[0].rsplit("/", 1)[-1] != MP.MODE_FILE],
        "assets_other": rest,
    }


def read_tryit_sidecar(base):
    try:
        with open(tryit_sidecar(base), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_tryit_sidecar(base, record):
    with open(tryit_sidecar(base), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)


def tryit_reuse_reason(base, set_dir, base_card, card, project, sound_ok, engine=None):
    """Why the set in *set_dir* cannot be handed back as it is, or ``""`` when it can: the
    sidecar beside it names the same base card, run card, project, gates and fingerprints
    as now, and the set's manifest is a finished one whose files are still exactly as the
    build left them (the engine's own all-or-nothing test). A sentence, as the Emulate
    tab's reuse test gives one, because "rebuilding" with no reason is what a four-minute
    wait looks like when nothing changed."""
    E = engine
    if E is None:
        from . import engine as E
    kept = read_tryit_sidecar(base)
    if not kept:
        return "there is no record of the last Try it"
    now = _tryit_record(base_card, card, project, sound_ok)
    if not now["base_card"] or not now["run_card"]:
        return "a card image could not be read"
    if kept.get("version") != now["version"]:
        return "the last Try it was recorded by another version of the app"
    for key, words in (("base_card", "it was prepared from a different card image"),
                       ("run_card", "it was prepared to run on a different card"),
                       ("assets", "it was built from a different project"),
                       ("sound_ok", "the own-sound choice changed"),
                       ("preview", "a preview feature was switched since it was built"),
                       ("gates", "a build gate changed since it was built"),
                       ("env", "a build option changed since it was built"),
                       ("app", "the app was updated since it was built"),
                       ("modes", "the modes changed since it was built"),
                       ("assets_fingerprint", "the project's edits changed since it was built")):
        if kept.get(key) != now[key]:
            return words
    return _set_intact_reason(set_dir, base_card, E)


def _set_intact_reason(set_dir, base_card, E):
    """Why the set in *set_dir* is not a finished set whose files and stage are as its build
    left them, or ``""`` when it is (the engine's own all-or-nothing test)."""
    manifest = E.read_override_manifest(set_dir) or {}
    if not manifest or manifest.get("building") or not manifest.get("generation"):
        return "the set was never finished"
    carried = manifest.get("modes")
    if not carried:
        return "the set carries no modes"
    # The stage the install reads (the object, the port, the mode files) sits BESIDE the
    # set and is not in its manifest's file list: a temp clean that took it leaves a set
    # the install would refuse ("no stage folder") with nothing to make it build again.
    stage = carried.get("dir") or (set_dir.rstrip("\\/") + E.OVERRIDE_MODES_SUFFIX)
    for name in (E.OVERRIDE_MODES_OBJECT, "game.port"):
        if not os.path.isfile(os.path.join(stage, name)):
            return "the modes' runtime folder is gone"
    check = getattr(E, "_override_reuse", None)
    if check is not None and check(set_dir, manifest, base_card) is None:
        return "the set's files are not as the build left them"
    return ""


# ---- a settings-only edit: the set stays, the mode files are written again ---------------
#: The ``mode.json`` fields that reach nothing but the mode's own runtime file
#: (:func:`.mode_project.runtime_cfg`): no screen, clip, sound, scene or game-program byte
#: of a build reads them. A Try it whose only change since the last one is to these keeps
#: the set as it is and writes the mode files again (:func:`tryit_settings_only`), in
#: milliseconds where the build took most of a minute. A field not named here (a new one
#: included) always builds the set again.
SETTINGS_ONLY_FIELDS = frozenset((
    "start_shot", "start_count", "seconds", "scoring_shots", "countdown", "lights",
    "light_color", "light_on_raw", "light_off_raw", "stack", "award_ladder", "shot_award",
    "end_shot", "callout_at", "restore_after", "starts_on", "ends_on", "starts", "cooldown",
    "priority", "light_shots", "light_shots_pattern"))
#: ...except these, for a mode with music of its own: its bed is cut to the mode's length.
_SETTINGS_ONLY_UNLESS_MUSIC = frozenset(("seconds",))


def _mode_json_dicts(project):
    """``{slug: the mode.json's fields}`` of every form mode, as read (``None`` for one that
    does not read as JSON)."""
    out = {}
    root = MP.modes_dir(project) if project else ""
    try:
        names = sorted(os.listdir(root)) if root else []
    except OSError:
        return out
    for slug in names:
        path = os.path.join(root, slug, MP.MODE_FILE)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        out[slug] = data if isinstance(data, dict) else None
    return out


def _settings_only_reason(kept, now):
    """Why the change from the record *kept* to *now* is not a settings-only one, or ``""``
    when every difference is a :data:`SETTINGS_ONLY_FIELDS` field of a form mode."""
    if not kept or kept.get("version") != now["version"]:
        return "there is no record of the last Try it"
    for key in ("base_card", "run_card", "assets", "sound_ok", "preview", "gates", "env", "app"):
        if kept.get(key) != now[key]:
            return "not only the modes changed"
    if kept.get("assets_other") is None or kept.get("assets_other") != now["assets_other"]:
        return "the project's other edits changed"
    if kept.get("modes_other") != now["modes_other"]:
        return "a mode's own files changed, or a mode was added or taken out"
    old, new = kept.get("mode_json") or {}, now["mode_json"] or {}
    if sorted(old) != sorted(new):
        return "a mode was added or taken out"
    changed = 0
    for slug in new:
        a, b = old.get(slug), new.get(slug)
        if not isinstance(a, dict) or not isinstance(b, dict):
            return "a mode's file does not read"
        diff = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
        if diff - SETTINGS_ONLY_FIELDS:
            return "a mode's screen, clip, sound or name changed"
        if diff & _SETTINGS_ONLY_UNLESS_MUSIC and (a.get("music") or b.get("music")):
            return "a mode with music of its own changed its length"
        changed += bool(diff)
    if not changed:
        return "nothing of the modes' settings changed"
    return ""


def tryit_settings_only(project, base, set_dir, base_card, card, sound_ok, engine=None,
                        log=None):
    """A Try it after an edit to the modes' SETTINGS only (:data:`SETTINGS_ONLY_FIELDS`: the
    timer, the shots, the lights, the scoring ...): the set is the last build's, byte for
    byte, and only the mode files in its stage change. Writes them again, exactly as the
    build writes them (:func:`mode_file_text`, with the carried own sounds the set's
    manifest names), records the press, and returns ``(listed manifest, [mode files
    rewritten])``; ``(None, why)`` when this is not such a change, and nothing is touched."""
    E = engine
    if E is None:
        from . import engine as E
    from .mode_assets import mode_file_name
    kept = read_tryit_sidecar(base)
    now = _tryit_record(base_card, card, project, sound_ok)
    if not now["base_card"] or not now["run_card"]:
        return None, "a card image could not be read"
    why = _settings_only_reason(kept, now) or _set_intact_reason(set_dir, base_card, E)
    if why:
        return None, why
    listed = E.read_override_manifest(set_dir) or {}
    carried = listed.get("modes") or {}
    stage = carried.get("dir") or (set_dir.rstrip("\\/") + E.OVERRIDE_MODES_SUFFIX)
    modes = card_modes(project, project_modes(project))
    names = [mode_file_name(slot) for slot in range(len(modes))]
    if names != [n for n in carried.get("files") or () if n.endswith(".cfg")]:
        return None, "the set's mode files are not the project's modes"
    rewritten = []
    for slot, (slug, spec) in enumerate(modes):
        text = mode_file_text(project, slug, spec, carried.get("own_sounds") or ())
        path = os.path.join(stage, names[slot])
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            rewritten.append(names[slot])
    write_tryit_sidecar(base, now)
    if log:
        log("only the modes' settings changed since the last Try it, so its set is used as it "
            "is and the mode files are written again (%s)" % ", ".join(rewritten or ["none"]))
    return listed, rewritten


def build_tryit_set(project, card, base, log=None, progress=None, cancel=None, label=None,
                    sound_ok=None):
    """Build Try it's set for *project* against the card image *card* in ``<base>/set``, with
    the object, the port and the mode files in ``<base>/set-modes``, through
    ``engine.write_overrides`` - Write's own code. Returns a :class:`TryItSet`, or ``None``
    when *cancel* stopped it. Raises :class:`ModeWriteError` with a sentence for the person.

    *card* is the image the run BOOTS. The set is PREPARED FROM the card the project was
    extracted from when that is another copy of the same build (:func:`.cards.override_base_card`,
    PAD-161: every offset in the project was measured on that card), and *card* goes along
    as ``run_card`` so the set's game program keeps what that card's own build changed in it
    (PAD-172) - exactly as the Emulate tab's own "apply my edits" path prepares its set.

    A SET THAT IS STILL CURRENT IS HANDED BACK UNBUILT. The sidecar :data:`TRYIT_SIDECAR`
    beside the set records what the last build was made from (both cards, the project, the
    gates, the build options and the app's version, a fingerprint of the modes and one of
    the project's edits); when all of it is as it was, the set's manifest is a finished one
    and the stage the install reads is still there, the :class:`TryItSet` is read back from
    that manifest with ``reused=True`` and one log line, and the engine is never called. A
    second press with nothing changed used to cost the whole build again (four minutes with
    one own sound), because ``write_overrides``' own patch-in-place path still stages and
    re-encodes the sound bank.

    *progress* ``(done, total, text)`` and *cancel* reach the engine's checkpoints. *sound_ok*
    is the own-sound gate for this build (None = the environment gate, as a Write reads it;
    False = a mode's own sounds left out), handed to the engine as it is. *log* may take
    ``(message)`` or ``(message, level)``. The set carries every edit of the project, as
    Write would: a card with the modes and without the rest does not exist."""
    from . import cards
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
        raise ModeWriteError(MP.NO_PROJECT_HELP)
    modes = card_modes(project, project_modes(project))
    code = code_mode_list(project)          # code modes with their own assets go through Write too
    if not modes and not code:
        raise ModeWriteError("There are no modes in this project to try.")
    if not card or not os.path.isfile(card):
        raise ModeWriteError("Pick the card image to try the modes on first.")
    set_dir = os.path.join(base, TRYIT_SET)
    os.makedirs(base, exist_ok=True)

    # PAD-161: prepared from the card the extract measured, run over the one picked.
    base_card, note = cards.override_base_card(card, project, E.card_title_index)
    if note:
        elog(note, "info")

    # The reuse test, before any build: the same cards, the same project, the same gates
    # and nothing of the modes or the edits moved means the set already there is the one
    # this build would make.
    why = tryit_reuse_reason(base, set_dir, base_card, card, project, sound_ok, engine=E)
    if not why:
        listed = E.read_override_manifest(set_dir) or {}
        kept = listed.get("counts") or {}
        counts = tuple(kept.get(k, 0) for k in ("audio", "video", "image", "text"))
        elog(TRYIT_REUSED, "info")
        return _tryit_set_from_manifest(project, modes, code, set_dir, listed, counts, E,
                                        reused=True)
    # Only the modes' settings moved (the timer, the shots, the lights ...): the set is the
    # last build's byte for byte, so only the mode files beside it are written again.
    listed, _rewritten = tryit_settings_only(project, base, set_dir, base_card, card,
                                             sound_ok, engine=E,
                                             log=lambda m: elog(m, "info"))
    if listed is not None:
        kept = listed.get("counts") or {}
        counts = tuple(kept.get(k, 0) for k in ("audio", "video", "image", "text"))
        return _tryit_set_from_manifest(project, modes, code, set_dir, listed, counts, E,
                                        reused=False)
    elog("preparing the modes (%s)" % why, "info")

    try:
        # pressed again and again on one card: keep its firmware + sound bank between builds
        with E.keep_card_extracts():
            got = E.write_overrides(base_card, project, set_dir, log=elog, progress=progress,
                                    cancel=cancel, label=label, run_card=card,
                                    sound_ok=sound_ok)
    except (RuntimeError, OSError, ValueError) as e:
        raise ModeWriteError(str(e)) from None
    counts = got[0]
    if counts is None:
        return None
    listed = E.read_override_manifest(set_dir) or {}
    # reused=False: the engine ran, so the set is THIS build's (patched in place or made
    # from scratch - the manifest's ``parent`` tells those apart, and neither is a set
    # handed back as it was, which is what the tab says of reused=True).
    result = _tryit_set_from_manifest(project, modes, code, set_dir, listed, tuple(counts), E,
                                      reused=False)
    # Taken AFTER the build: the engine writes its hash cache back into the project, and the
    # fingerprint kept has to be the one the next press will measure.
    try:
        write_tryit_sidecar(base, _tryit_record(base_card, card, project, sound_ok))
    except OSError as e:
        elog("the record of this Try it could not be kept (%s); the next one builds again"
             % e, "warning")
    return result


def _tryit_set_from_manifest(project, modes, code, set_dir, listed, counts, E, reused=False):
    """The :class:`TryItSet` a set's manifest describes - read the same way after a build and
    for a set handed back unbuilt, so the tab sees one shape either way."""
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
        if prof is None:
            raise ModeWriteError(CM.NO_TITLE)
    from .mode_assets import mode_file_name
    result = TryItSet(
        set_dir=set_dir, stage_dir=stage, game_dir=prof.game_dir, version=_port_version(port),
        reused=reused,
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
        if MS.carriers(game, version).swap:
            entry["swap"] = True        # item 163: swapped in at run time
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


#: ``PAD_CODE_CACHE=0``: the code modes are compiled on every build, never taken from an
#: earlier build of the same sources.
CODE_CACHE_ENV = "PAD_CODE_CACHE"
#: Objects kept at most; the least recently used go first.
CODE_CACHE_KEEP = 20
_PENDING = {}                    # object key -> threading.Event of a compile started early
_PENDING_LOCK = threading.Lock()
_PREFETCHED = set()              # keys this process compiled early (for the log's words)


def code_cache_dir():
    """Where compiled objects are kept: the temp dir, under a ``spike2_`` name like the other
    build scratch."""
    return os.path.join(tempfile.gettempdir(), "spike2_code_cache")


#: What sits beside a code mode's C that a compile never reads: its pictures, clips, sounds
#: and assets.json. Leaving them out keeps the kept object across an asset edit.
_NOT_COMPILED = frozenset((".wav", ".mp3", ".ogg", ".flac", ".mp4", ".mov", ".mkv", ".webm",
                           ".avi", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".json"))
#: Past this size a file beside a mode is keyed by its size and time, not its bytes.
_KEY_BYTES_MAX = 4 << 20


def _mode_folder_files(folder):
    """Every file under *folder* (recursively, sorted) a compile could include: gcc finds a
    quoted include beside the source or in any folder under it, whatever its extension."""
    got = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names):
            if os.path.splitext(n)[1].lower() not in _NOT_COMPILED:
                got.append(os.path.join(root, n))
    return got


def code_object_key(sources):
    """The digest an object is kept under: the bytes of every code mode's C file and of every
    other file under its folder a compile could include (:func:`_mode_folder_files`), and of
    everything of the SDK ``build_mode.sh`` compiles in (the runtime, the mode-file interpreter,
    the headers, the script itself). The same key is the same object: gcc is pinned in the
    app's Linux."""
    sdk = MR.sdk_dir()
    files = [(n, os.path.join(sdk, n)) for n in (BUILD_MODE, "pad_mode_runtime.c", "mode_file.c")]
    files += sorted((n, os.path.join(sdk, n)) for n in os.listdir(sdk) if n.endswith(".h"))
    for src in sources:
        folder = os.path.dirname(os.path.abspath(src))
        files.append((os.path.basename(src), src))
        files += [(os.path.relpath(p, folder).replace(os.sep, "/"), p)
                  for p in _mode_folder_files(folder)
                  if os.path.normcase(os.path.abspath(p)) != os.path.normcase(os.path.abspath(src))]
    h = hashlib.sha256(b"pad code object 2\0")
    for name, p in files:
        h.update(name.encode("utf-8") + b"\0")
        st = os.stat(p)
        if st.st_size > _KEY_BYTES_MAX:
            h.update(b"big %d %d\0" % (st.st_size, st.st_mtime_ns))
            continue
        with open(p, "rb") as f:
            data = f.read()
        h.update(b"%d\0" % len(data))
        h.update(data)
    return h.hexdigest()


def _cached_object(key, wait=600):
    """The kept object for *key*, or ``None``; waits for a compile of the same key started early
    (:func:`prefetch_code_object`)."""
    with _PENDING_LOCK:
        ev = _PENDING.get(key)
    if ev is not None:
        ev.wait(wait)
    path = os.path.join(code_cache_dir(), key + ".so")
    return path if os.path.isfile(path) and os.path.getsize(path) > 0 else None


def _keep_object(key, built):
    folder = code_cache_dir()
    try:
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, "%s.%d.%d.tmp" % (key, os.getpid(), threading.get_ident()))
        shutil.copyfile(built, tmp)
        os.replace(tmp, os.path.join(folder, key + ".so"))
        kept = sorted((n for n in os.listdir(folder) if n.endswith(".so")),
                      key=lambda n: os.path.getmtime(os.path.join(folder, n)))
        for n in kept[:-CODE_CACHE_KEEP] if len(kept) > CODE_CACHE_KEEP else ():
            os.remove(os.path.join(folder, n))
    except OSError:
        pass


def compile_code_object(sources, out, log=None, executor=None, timeout=600):
    """Build the object a card with code modes carries: the runtime, every code mode and the
    mode-file interpreter (so the project's form modes run beside them). Returns *out*. Raises
    :class:`ModeWriteError` with the compiler's words when it fails.

    With the app's own executor (*executor* None) the object is kept by
    :func:`code_object_key`, and a build of the same sources takes the kept one instead of
    compiling (1.5 s, and 10-15 s on a busy PC); a compile of them already started by
    :func:`prefetch_code_object` is waited for. A caller's own executor always compiles."""
    say = log or (lambda *a, **k: None)
    names = ", ".join(os.path.splitext(os.path.basename(s))[0] for s in sources)
    key = None
    if executor is None and os.environ.get(CODE_CACHE_ENV) != "0":
        try:
            key = code_object_key(sources)
        except OSError:
            key = None
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if key:
        kept = _cached_object(key, wait=timeout)
        if kept:
            shutil.copyfile(kept, out)
            try:
                os.utime(kept, None)
            except OSError:
                pass
            if key in _PREFETCHED:
                say("Modes: built the code mode(s) %s into the card's mode.so with the "
                    "mode-file interpreter beside the rest of the build (%d bytes)."
                    % (names, os.path.getsize(out)), "info")
            else:
                say("Modes: the code mode(s) %s are as they were for an earlier build, so its "
                    "mode.so is used (%d bytes; PAD_CODE_CACHE=0 compiles every time)."
                    % (names, os.path.getsize(out)), "info")
            return out
    if executor is None:
        from ...core.executor import create_executor
        executor = create_executor()
    try:
        said = executor.run(compile_command(executor, out, sources), timeout=timeout)
    except Exception as e:                   # the executor's CommandError, a missing WSL
        raise ModeWriteError("the code modes did not build: %s" % str(e)[-600:]) from None
    if not os.path.isfile(out):
        raise ModeWriteError("the code modes did not build (no object was written): %s"
                             % (said or "").strip()[-400:])
    if key:
        _keep_object(key, out)
    say("Modes: built the code mode(s) %s into the card's mode.so with the mode-file interpreter (%d bytes)."
        % (names, os.path.getsize(out)), "info")
    return out


_compile_code_object = compile_code_object


def prefetch_code_object(sources, timeout=600):
    """Start compiling *sources* in the background now, into the kept objects, so the build's
    own :func:`compile_code_object` of them later finds the object ready (or waits for the rest
    of this compile) instead of compiling at the end of the build. Returns the started thread,
    or ``None`` when there is nothing to start: an object already kept or already being made,
    caching off, a source that cannot be read, or a stand-in compile (a test's), which is never
    run early. A compile that fails here is simply not kept: the build's own compile then runs
    and says why."""
    if compile_code_object is not _compile_code_object or not sources:
        return None
    if os.environ.get(CODE_CACHE_ENV) == "0":
        return None
    try:
        key = code_object_key(sources)
    except OSError:
        return None
    with _PENDING_LOCK:
        if key in _PENDING or os.path.isfile(os.path.join(code_cache_dir(), key + ".so")):
            return None
        ev = _PENDING[key] = threading.Event()

    def run():
        out = os.path.join(tempfile.gettempdir(), "spike2_code_prefetch_%s_%d.so"
                           % (key[:16], threading.get_ident()))
        try:
            from ...core.executor import create_executor
            ex = create_executor()
            ex.run(compile_command(ex, out, sources), timeout=timeout)
            if os.path.isfile(out):
                _keep_object(key, out)
                with _PENDING_LOCK:
                    _PREFETCHED.add(key)
        except Exception:                                   # noqa: BLE001
            pass
        finally:
            try:
                os.remove(out)
            except OSError:
                pass
            with _PENDING_LOCK:
                _PENDING.pop(key, None)
            ev.set()
    t = threading.Thread(target=run, name="pad-code-prefetch", daemon=True)
    t.start()
    return t


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
