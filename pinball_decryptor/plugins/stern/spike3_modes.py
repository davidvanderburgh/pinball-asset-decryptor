"""Custom modes on a Stern **Spike 3** card (PAD-1272).

A Spike 2 card carries its modes on the system partition (``/usr/local/padmode``, with
``/etc/init.d/game_monitor`` hooked: :mod:`tools/spike2_emu/modehook`). A Spike 3 card's
rootfs is LUKS2 like every other partition but it is the signed image's, and a Write
changes only the games partition (p6, ``/games``), so the modes go there:

    /games/pad/padmode/mode.so        the 64-bit runtime (prebuilt/mode64.so), 0755
    /games/pad/padmode/game.port      the port, mode.cfg, mode1.cfg ..., stock.cfg
    /games/pad/padmode/padmode.sh     the hook, 0755
    /games/pad/padmode/game.target    where /games/game pointed on the stock card
    /games/game                       -> pad/padmode/padmode.sh

``/etc/init.d/S95game`` -> ``game_monitor`` runs ``/games/game`` in a restart loop and reads
its exit code (MULTIBOOT.md, "How a Spike 3 machine starts its game"). The hook preloads the
runtime into THE GAME - conagent has a monitor of its own and never sees it - and becomes
the game with ``exec``, so game_monitor reads the game's own code, exactly as Spike 3
multi-boot's ``padselect.sh`` does from the same link. The runtime reads its files from
``PM_CARD_DIR`` (pad_mode.h: ``/games/pad/padmode/`` on aarch64) and logs to /dump.

What a Spike 3 build carries: the modes made in the form, with their own start, shot and end
sounds and music where the title's carriers are known (PAD-1296, :func:`own_sounds`: each sound
a record appended to the card's ``image.bin``, swapped in on a carrier while the mode plays it).
PAD-1295: code modes too, compiled for the card's 64-bit ARM with the pinned aarch64 gcc
(``tools/spike3_emu/xgcc.pins``) into the card's ``mode.so``, their music and calls carried as
the form modes' sounds are. The Spike 2 parts of a build stay Spike 2's: the rest of the family
(co-op, handicap, attract items ...), which the engine leaves out on a Spike 3 volume, each with
its reason (PAD-1297's census, docs/plans/spike3_modes.md). The score feed is the one that goes
on as files alone (:func:`feed_wanted`): with the modes, or by itself.

The build itself is :func:`.mode_write.plan` - the same port lookup (64-bit programs
read too), the same mode files, and the screens and clips built into the title's own
scenes, which a Spike 3 card carries as Spike 2's asset tree does - so a title's port
(PAD-1271) is all a Spike 3 card needs to take the modes the tab makes.
"""
import os
import shlex
import shutil
import struct

from . import mode_project as MP
from . import mode_write as MW

#: on the games partition (relative to /games)
MODE_DIR = "pad/padmode"
HOOK_NAME = "padmode.sh"
TARGET_NAME = "game.target"
#: what /games/game points at on a card with modes
HOOK_LINK = MODE_DIR + "/" + HOOK_NAME
#: a Spike 3 multi-boot card's link (mks3multi.py): its images are whole games trees
MULTIBOOT_LINK = "pad/padselect.sh"

#: the hook. Plain POSIX sh (the card's busybox ash). Never a dead machine: with no
#: game.target, or one that is not a program, the card's first game program runs stock.
HOOK_SCRIPT = """#!/bin/sh
# padmode.sh - custom modes on this Stern Spike 3 card (PAD-1272). game_monitor runs
# /games/game in its restart loop; on a card with modes that is this script. It preloads
# the mode runtime into the game (conagent has its own monitor and never sees it) and
# becomes the game with exec, so game_monitor reads the game's own exit code.
# game.target beside it is where /games/game pointed on the stock card.
D=/games/pad/padmode
T=$(cat "$D/game.target" 2>/dev/null)
case "$T" in
    /*) G=$T ;;
    *)  G=/games/$T ;;
esac
if [ -z "$T" ] || [ ! -x "$G" ]; then
    for G in /games/*/game; do
        [ -x "$G" ] && exec "$G" "$@"
    done
    exit 4
fi
# PAD-1324: the game program with the modes' rows in its operator menu (MUSIC MODE), when the
# build made one: the card's own program stays as it shipped
if [ -x "$D/game.pad" ]; then
    G=$D/game.pad
fi
if [ -f "$D/mode.so" ]; then
    LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$D/mode.so"
    export LD_PRELOAD
fi
exec "$G" "$@"
"""

#: why a multi-boot Spike 3 card takes no modes
MULTIBOOT_WORDS = ("this is a multi-boot card; modes go on a card of the one game they were "
                   "made for")


#: PAD-1297: why each part of the mode family a project can ask for is left out of a Spike 3
#: build that passed its own checks (a title the part's gate refuses has said why already), in
#: the engine's words for it. The census behind them is docs/plans/spike3_modes.md, "The family
#: on Spike 3". The score feed is not here: it goes on (:func:`feed_wanted`), and so do the random clips
#: (:func:`variants_wanted`) and the screen times (:func:`screen_times_wanted`, PAD-1323), the music
#: modes (:mod:`.spike3_music`, PAD-1324), EDITION (:mod:`.spike3_menu`, PAD-1325), and co-op play
#: and the handicaps (:func:`coop_wanted`, :func:`hand_wanted`, PAD-1326), and
#: Prolonged Competition (:func:`comp_wanted`, PAD-1327: on a title whose Spike 3 port knows its
#: start menu; the engine's `_comp_for_build` says why another is left out).
FAMILY_LEFT_OUT = {
    "picture settings": "they cannot be added to a Spike 3 game yet",
    "expression light shows": "the 64-bit runtime cannot light a Spike 3 cabinet's expression lights yet",
}


def family_left_out_lines(asked):
    """The log's sentences for the family parts *asked* (names in :data:`FAMILY_LEFT_OUT`) a
    Spike 3 build leaves out: one each, with its reason."""
    return ["%s: left out of this build: %s." % (w[0].upper() + w[1:], FAMILY_LEFT_OUT[w])
            for w in asked if w in FAMILY_LEFT_OUT]


def card_state(reader):
    """``(state, target)`` of the games volume *reader* (an Ext4Reader over it):
    ``"stock"`` (``/games/game`` is the title's own link, *target* it), ``"modes"`` (a card
    this module wrote: *target* the stock link kept in ``game.target``), ``"multiboot"``
    (mks3multi's boot menu), or ``"unknown"`` (no link: *target* "")."""
    node = MW.lookup(reader, "game")
    if node is None or (node["mode"] & 0xF000) != 0xA000:
        return "unknown", ""
    link = reader.read_symlink(node).strip()
    if link in (MULTIBOOT_LINK, "/games/" + MULTIBOOT_LINK):
        return "multiboot", link
    if link in (HOOK_LINK, "/games/" + HOOK_LINK):
        tnode = MW.lookup(reader, MODE_DIR + "/" + TARGET_NAME)
        target = (bytes(reader.read_file_bytes(tnode)).decode("utf-8", "replace").strip()
                  if tnode is not None else "")
        return "modes", target
    return "stock", link


def game_program(reader, target):
    """The inode of the game program the stock link *target* names, or None."""
    rel = target[len("/games/"):] if target.startswith("/games/") else target.lstrip("/")
    node = MW.lookup(reader, rel)
    if node is None or (node["mode"] & 0xF000) != 0x8000:
        return None
    return node


class Spike3ModePlan:
    """What a Spike 3 Write puts on the card for the project's modes."""

    def __init__(self, result, payload, names, lines, sound_adds=None, program="", target=""):
        self.result = result            # mode_write.ModePlan
        self.payload = payload          # mode_write.p2_payload's dict, mode.so the 64-bit one
        self.names = names              # the modes' names
        self.lines = lines              # what the build says of them
        #: PAD-1296: ``{container card path: [spike3_write.NewRecord]}`` - the modes' own sounds,
        #: appended to the game's image.bin (spike3_write.plan_sounds ``adds``)
        self.sound_adds = sound_adds or {}
        #: PAD-1324: the game program with MUSIC MODE in its menu (spike3_music.PROGRAM_NAME), or ""
        self.program = program
        #: where /games/game pointed on the stock card (the program game.pad stands in for)
        self.target = target
        # the title's scenes the modes' screens and clips rewrite, and any new file: whole
        self.jobs = [(rel.lstrip("/"), src) for rel, src in
                     list(result.replaced) + list(result.new)]

    def files(self):
        """``[(name on the card, host path, mode)]`` in ``pad/padmode``."""
        p = self.payload
        out = [("mode.so", p["so"], 0o755)]
        if self.program:
            from .spike3_music import PROGRAM_NAME
            out.append((PROGRAM_NAME, self.program, 0o755))
        for path in (list(p["cfgs"]) + list(p.get("assets") or ()) + list(p.get("extras") or ())
                     + [p["port"]] + ([p["bundle"]] if p.get("bundle") else [])):
            out.append((os.path.basename(path), path, 0o644))
        return out


class _NodeFile:
    """A read-only file over the volume file *node* (what :func:`.spike3_requests.sound_parts`
    reads: the header, the descriptor block and the directory, never the bodies)."""

    def __init__(self, reader, node):
        self.reader, self.node, self.pos = reader, node, 0

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.node["size"] + off if whence == 2 else self.pos + off)
        return self.pos

    def read(self, n):
        n = max(0, min(n, self.node["size"] - self.pos))
        b = bytes(self.reader.read_range(self.node, self.pos, n)) if n else b""
        self.pos += len(b)
        return b


def _wav_ms(path, channels):
    from . import mode_sounds as MS
    ms = MS.sound_ms(path)
    if ms:
        return ms
    from . import spike3_write
    import math

    class _R:
        pass
    r = _R()
    r.channels = channels
    n = len(spike3_write._pcm(path, r, spike3_write._np()))
    return int(math.ceil(n * 1000.0 / 44100)) if n else 0


def own_sounds(project, modes, reader, game_raw, prof, log=None, code=()):
    """PAD-1296: a Spike 3 card's own sounds for *modes*: ``(used, adds)``.

    The sounds :func:`.mode_write.choose_own_sounds` picks (start, shot and music, and the end
    sound: a Spike 3 build always carries it, :func:`.mode_write.end_on_carrier`) each go on the
    card as a record of their own appended to the game's ``image.bin``, keyed beside its carrier's
    record (:func:`.spike3_write.free_key`), and the mode swaps the carrier's key for it while it
    plays (``swap <request> <stock key> <our key>``, the item 163 route; pad_mode_runtime.c's
    lookup hook takes the 64-bit find's key). A carrier is a request of the build the game never
    plays (:data:`.mode_sounds.TITLES_A64`); its stock key is the record its first sound id's
    descriptor names. *used* is the engine's carried list for :func:`.mode_write.plan`
    (``slug``, ``key``, ``request``, ``ms``, ``stock_key``, ``our_key``); *adds* is
    ``{container card path: [NewRecord]}`` for :func:`.spike3_write.plan_sounds`. A sound that
    cannot be carried is left out with its reason in the log; the mode plays the game's own.
    PAD-1295: *code* (``[(slug, spec)]``) adds the code modes' music and calls
    (:func:`.mode_write.choose_code_sounds`, ``call:<cue>`` / ``music:<bed>`` keys), each a
    record of its own on a carrier the same way."""
    log = log or (lambda *a, **k: None)
    from . import mode_sounds as MS
    from . import spike3_requests as Q
    from . import spike3_write as W
    from .info import container_counts
    wanted = MW.choose_own_sounds(project, modes, (True, ""), end_sound=None, log=log)
    if code:
        req, beds = MW.own_sounds_taken(wanted)
        wanted = list(wanted) + MW.choose_code_sounds(project, code, (True, ""), prof, taken=req,
                                                      taken_beds=beds, log=log)
    if not wanted:
        return [], {}
    conts = W.project_sound_dirs(reader)
    if not conts:
        log("Modes: the modes' own sounds are not put on this card: it has no sound container.",
            "warning")
        return [], {}
    card_path, node = conts[0][0], conts[0][1]
    _hdr, img = W.read_container(reader, node)
    f = _NodeFile(reader, node)
    fragments, _count = container_counts(f.read(0x100))
    try:
        lists = Q.request_table(Q.Program(bytes(game_raw)), fragments)
    except ValueError:
        lists = []
    parts = Q.sound_parts(f) if lists else {}
    if not lists or not parts:
        log("Modes: the modes' own sounds are not put on this card: its sound requests could not "
            "be read off the game program and %s." % card_path, "warning")
        return [], {}

    def stock_record(request):
        sids = lists[request] if 0 < request < len(lists) else []
        idx = (parts.get(sids[0]) or [None])[0] if sids else None
        return img.records[idx] if idx is not None and idx < img.count else None

    used, adds, taken, p2s = [], [], [], []
    mine = {}                           # slug -> carriers this mode already took (distinct within one)
    for e in wanted:
        cands = list(e.get("candidates") or [e["request"]])
        cands = [r for r in cands if r not in mine.get(e["slug"], ())] or cands
        rec, req = None, 0
        for r in cands:
            rec = stock_record(int(r))
            if rec is not None:
                req = int(r)
                break
        if rec is None:
            log("Modes: %s's %s is not put on this card: none of %s's carriers (%s) names a "
                "recording of %s." % (e["name"], MW.sound_words(e["key"]), prof.label,
                                      ", ".join(str(r) for r in cands), card_path), "warning")
            continue
        flags, param = W.free_key(img.records, rec.flags_lo, rec.param, taken)
        taken.append((flags, param))
        p2 = W.free_param2(img.records, ("%s|%s|%d" % (e["slug"], e["key"], req)).encode(), p2s)
        p2s.append(p2)
        nr = W.NewRecord(e["wav"], rec.channels, flags, param, p2)
        adds.append(nr)
        mine.setdefault(e["slug"], []).append(req)
        u = {"slug": e["slug"], "name": e["name"], "key": e["key"], "request": req,
             "wav": e["wav"], "music": bool(e.get("music")),
             "stock_key": struct.pack("<II", rec.flags_lo, rec.param).hex(),
             "our_key": nr.key.hex(), "idx": img.count + len(adds) - 1}
        if not e.get("music"):
            u["ms"] = _wav_ms(e["wav"], rec.channels)
        used.append(u)
    for u in used:
        log("Modes: %s's own %s rides request %d (its record %d, appended to %s)."
            % (u["name"], MW.sound_words(u["key"]), u["request"], u["idx"], card_path), "info")
    return used, ({card_path: adds} if adds else {})


#: Try it's image.bin patches, in its mode files folder (s3run.sh applies them in the rig slot)
GAMES_PATCH = "games.patch"


def stage_try_it_sounds(reader, mplan, files_dir):
    """PAD-1296: the modes' own sounds of *mplan* for Try it on the Spike 3 rig: each container
    they go into as a patch of the card's own file (:func:`.spike3_write.stage_tail`) in
    ``<files_dir>/games.patch``, with its ``patches`` list (``<path in /games>|<cut>|<head>|<tail>``)
    that s3run.sh builds the slot's file from. Returns the number of containers (0: nothing)."""
    from . import spike3_write as W
    if not mplan.sound_adds:
        return 0
    out = os.path.join(files_dir, GAMES_PATCH)
    os.makedirs(out, exist_ok=True)
    nodes = {p: n for p, n, _f, _s in W.project_sound_dirs(reader)}
    lines = []
    for k, (card_path, adds) in enumerate(sorted(mplan.sound_adds.items())):
        node = nodes.get(card_path)
        if node is None:
            raise MW.ModeWriteError("the card has no %s for the modes' own sounds" % card_path)
        cut, head, tail = W.stage_tail(reader, node, adds, out, "c%d" % k)
        lines.append("%s|%d|%s|%s" % (card_path.lstrip("/"), cut, os.path.basename(head),
                                      os.path.basename(tail)))
    with open(os.path.join(out, "patches"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


def stage_try_it_scenes(mplan, files_dir):
    """PAD-1284: the title's scenes the modes' screens and clips rewrote, and their new files (a
    mode's clip), for Try it on the Spike 3 rig: each staged whole in ``<files_dir>/games.patch``
    and named in its ``patches`` list as ``<path in /games>|whole|<file>|`` (after any sound
    container :func:`stage_try_it_sounds` wrote there), which s3run.sh puts in the slot's /games.
    Returns the number of files (0: nothing). PAD-1324: the game program with MUSIC MODE in its
    menu (:attr:`Spike3ModePlan.program`) goes the same way, over the stock program the card's
    /games/game names (on a card the hook runs it from pad/padmode instead)."""
    jobs = list(mplan.jobs)
    prog = getattr(mplan, "program", "")
    tgt = getattr(mplan, "target", "")
    if prog and tgt:
        rel = tgt[len("/games/"):] if tgt.startswith("/games/") else tgt.lstrip("/")
        jobs.append((rel, prog))
    if not jobs:
        return 0
    out = os.path.join(files_dir, GAMES_PATCH)
    os.makedirs(out, exist_ok=True)
    lines = []
    for k, (rel, src) in enumerate(jobs):
        name = "w%d" % k
        shutil.copyfile(src, os.path.join(out, name))
        lines.append("%s|whole|%s|" % (rel.lstrip("/"), name))
    with open(os.path.join(out, "patches"), "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


def feed_wanted(project, real_card=True):
    """PAD-1297: ``(address, profile)`` of the score feed (:mod:`.score_feed`) this Spike 3 build
    carries, else ``("", None)``. The feed is the one part of the family a Spike 3 card takes as
    files alone (``scorefeed.cfg`` beside the 64-bit runtime: the tick, the event bus and the
    64-bit scores are all it reads, docs/plans/spike3_modes.md "The family on Spike 3"). Quiet:
    the engine's Write (``_feed_for_build``) has already said why one is left out."""
    from . import score_feed as SF
    url = SF.wanted(project)
    if not url or MW.host_refusal():
        return "", None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return "", None
    prof = SF.project_title(project, probe=True)
    if SF.title_refusal(prof):
        return "", None
    return url, prof


def coop_wanted(project, real_card=True):
    """PAD-1326: the profile co-op play (:mod:`.coop_play`) goes on in this Spike 3 build, else None: the 64-bit
    runtime follows the game's players through the port's player change, add player and player bytes (a title whose
    port has them: title_refusal), a teammate joining with the right flipper button held. Quiet: the engine's Write
    (``_coop_for_build``) has already said why it is left out."""
    from . import coop_play as CP
    if not CP.load(project) or not MW.preview_on() or MW.host_refusal():
        return None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return None
    prof = CP.project_title(project, probe=True)
    if prof is None or CP.title_refusal(prof):
        return None
    return prof


#: PAD-1326: why a Spike 3 card with co-op play carries no handicaps (with both on, the emulator's ELG game stopped at a
#: teammate's turn: the handicaps' wrap of the adjustment getter beside co-op's of the player change)
HAND_WITH_COOP = ("on a Spike 3 game the handicaps do not go on a card that also has co-op play yet; a card of "
                  "handicaps without co-op takes them")


def hand_wanted(project, real_card=True):
    """PAD-1326: the profile the handicaps (:mod:`.handicap`) go on in this Spike 3 build, else None: the 64-bit runtime
    answers the game's adjustment getter with the player's level while they are up, each player picking theirs with
    the flippers at their first ball. Quiet: the engine's Write (``_handicap_for_build``) has already said why not."""
    from . import handicap as HC
    if not HC.load(project) or MW.host_refusal():
        return None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return None
    prof = HC.project_title(project, probe=True)
    if prof is None or HC.title_refusal(prof):
        return None
    if coop_wanted(project, real_card=real_card) is not None:
        return None                                     # HAND_WITH_COOP, said by plan()
    return prof


def comp_wanted(project, real_card=True):
    """PAD-1327: the profile of the title Prolonged Competition (:mod:`.prolonged_comp`) goes on in this Spike 3 build,
    else None. ``comp.cfg`` beside the 64-bit runtime: the start menu's sites in the title's Spike 3 port (the entry
    appended by hook_full, the pick played as Standard), the event bus and the game's flags. Quiet: the engine's
    Write (``_comp_for_build``) has already said why it is left out."""
    from . import prolonged_comp as PCo
    if not PCo.load(project) or MW.host_refusal():
        return None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return None
    prof = PCo.project_title(project, probe=True)
    if PCo.title_refusal(prof):
        return None
    return prof


def records_wanted(project, real_card=True):
    """PAD-1327: ``(records, profile)`` of the owner's records (:mod:`.mode_records`) this Spike 3 build carries, else
    ``([], None)``: ``records.cfg`` beside the 64-bit runtime, filed through the game's own end-of-game high scores
    (the port's challenge_scores, challenge_score_entry, challenge_scores_table and the record's 64-bit layout).
    Quiet: the engine's Write (``_records_for_build``) has already said why they are left out."""
    from . import mode_records as MRec
    recs = MRec.load(project)
    if not recs or not MW.preview_on() or MW.host_refusal():
        return [], None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return [], None
    prof = MRec.project_title(project, probe=True)
    if prof is None or MRec.title_refusal(prof):
        return [], None
    return recs, prof


def attract_wanted(project, real_card=True):
    """PAD-1328: the profile of the title the owner's attract items (:mod:`.attract_items`) go on in this Spike 3
    build, else None: their clips in the title's video bank, ``attract.cfg`` beside the 64-bit runtime (the port's
    attract table, read off the 64-bit sequencer, and a clip route). Quiet: the engine's Write
    (``_attract_for_build``) has already said why they are left out."""
    from . import attract_items as AI, clip_variants as CV
    if AI.load(project).empty() or MW.host_refusal():
        return None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return None
    prof = CV.project_title(project, probe=True)
    if prof is None or AI.title_refusal(prof):
        return None
    return prof


def variants_wanted(project, real_card=True):
    """PAD-1323: ``(slots, profile)`` of the random clips (:mod:`.clip_variants`) this Spike 3 build carries,
    else ``({}, None)``. The 64-bit runtime hooks the game's ask on the video bank's surface (clip v2: a port
    with surface_find / surface_set_video, and no string_new: it builds the name itself). Quiet: the engine's
    Write (``_variants_for_build``) has already said why they are left out."""
    from . import clip_variants as CV
    slots = CV.load(project)
    if not slots or not CV.enabled() or MW.host_refusal():
        return {}, None
    if real_card:
        from ...core import ext4_grow
        if not ext4_grow.available()[0]:
            return {}, None
    prof = CV.project_title(project, probe=True)
    if CV.title_refusal(prof):
        return {}, None
    return slots, prof


def _changed_videos(project):
    from . import engine as E
    from ...core.checksums import read_checksums
    return E._changed_videos(project, read_checksums(project))


def screen_times_wanted(project, game_raw, log, real_card=True):
    """PAD-1323: ``(stime lines, profile)`` - the screens of the card's game program *game_raw* (64-bit:
    :func:`.screen_time.screens_a64`) that show one of the project's replaced clips for a fixed time, made to
    last as long as the clip; ``([], None)`` when none. The engine's own reckoning (``_screen_times_from``),
    with its log lines: on Spike 3 the engine leaves the screen times to this build."""
    from . import engine as E
    from . import screen_time as ST
    if not ST.enabled():
        return [], None
    edits = _changed_videos(project)
    if not edits:
        return [], None
    return E._screen_times_from(game_raw, project, edits, False, log,
                                ext4_available=None if real_card else (lambda: (True, "")))


def plan(project, reader, scratch, log=None, real_card=True, sound_ok=(True, ""), coop_setting=0, coop_ok=True,
         hand_setting=0):
    """The project's modes for the Spike 3 games volume *reader*, built into *scratch*, or
    None when it has none this card can carry (each reason said in the log, as a Spike 2
    Write leaves modes out: the rest of the project is still written). Raises
    :class:`.mode_write.ModeWriteError` for a mode that cannot be built (the Write stops,
    as on Spike 2). *real_card* False is Try it's build for the emulator: nothing is
    written into a card, and a port derived on this PC that never ran may run there.
    PAD-1297: the project's score feed (:func:`feed_wanted`) goes with them, or alone on a
    card with no modes (the runtime then arms it and nothing else: ``only`` in its file).
    PAD-1323: so do the random clips (:func:`variants_wanted`: their clips into the video bank,
    ``clips.cfg`` beside the runtime) and the screen times (:func:`screen_times_wanted`: ``stime``
    lines in it). PAD-1324: so do the music modes (:mod:`.spike3_music`: their files appended to
    image.bin, ``sounds.cfg`` beside the runtime, and ``game.pad``, the program with MUSIC MODE in
    its operator menu, which the hook runs in the stock one's place).
    PAD-1326: so does co-op play (:func:`coop_wanted`: ``coop.cfg``), *coop_setting* the CO-OP
    PLAY row's live value at the program's own address (spike3_menu placed it; 0: always on), *coop_ok* False
    when the project asked for the row and the card could not take it (then no co-op, as on Spike 2). So do the
    handicaps (:func:`hand_wanted`: ``handicap.cfg``), *hand_setting* the HANDICAP row's live value (0: always on).
    With the music modes the machine runs their program, so both values are read off it.
    PAD-1327: and Prolonged Competition (:func:`comp_wanted`: ``comp.cfg``, its flag
    and captions read off the card's own program)."""
    log = log or (lambda *a, **k: None)
    from . import spike3_music as S3MU
    music, music_prof = S3MU.wanted(project, real_card=real_card)
    for _line in S3MU.left_out_lines(project):
        log(_line, "warning")
    feed, feed_prof = feed_wanted(project, real_card=real_card)
    coop_prof = coop_wanted(project, real_card=real_card) if coop_ok else None
    hand_prof = hand_wanted(project, real_card=real_card)
    if hand_prof is None and coop_prof is not None:
        from . import handicap as HC
        if HC.load(project):
            log("Handicaps: left out of this build: %s." % HAND_WITH_COOP, "warning")
    slots, var_prof = variants_wanted(project, real_card=real_card)
    comp_prof = comp_wanted(project, real_card=real_card)
    recs, recs_prof = records_wanted(project, real_card=real_card)       # PAD-1327
    att_prof = attract_wanted(project, real_card=real_card)              # PAD-1328
    from . import screen_time as ST
    stime_maybe = ST.enabled() and bool(_changed_videos(project))
    modes, code = [], []
    if not MW.preview_on():
        off = MW.preview_left_out(project)
        if off:
            log(off, "warning")
    else:
        modes = MW.project_modes(project)
        code = MW.code_mode_list(project)        # PAD-1295: compiled for the card's 64-bit ARM
    if (not modes and not code and not feed and not slots and not stime_maybe and music is None and coop_prof is None
            and hand_prof is None and comp_prof is None and not recs and att_prof is None):
        return None

    def left(why):
        log("Modes: the project's %d mode(s) are left out of this build: %s."
            % (len(modes) + len(code), why.rstrip(".")), "warning")
        return [], []
    if (modes or code) and real_card:
        ok, why = MW.gate(dest_is_device=False)
        if not ok:
            modes, code = left(why)
    if modes or code:
        why = MW.card_refusal(project, real_card=real_card)
        if why:
            modes, code = left(why)
    if (not modes and not code and not feed and not slots and not stime_maybe and music is None and coop_prof is None
            and hand_prof is None and comp_prof is None and not recs and att_prof is None):
        return None
    state, target = card_state(reader)
    if state == "multiboot":
        if modes or code:
            left(MULTIBOOT_WORDS)
        if feed:
            log("Score feed: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "the score feed goes on").replace("they were", "it was"), "warning")
        if slots:
            log("Random clips: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "random clips go on"), "warning")
        if music is not None:
            log("Music modes: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "music modes go on"), "warning")
        if coop_prof is not None:                   # PAD-1326
            log("Co-op play: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "co-op play goes on").replace("they were", "it was"), "warning")
        if hand_prof is not None:
            log("Handicaps: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "the handicaps go on"), "warning")
        if comp_prof is not None:
            log("Prolonged Competition: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "Prolonged Competition goes on").replace("they were", "it was"), "warning")
        if recs:
            log("Records on the high scores: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "records go on"), "warning")
        if att_prof is not None:                    # PAD-1328
            log("Attract items: left out of this build: %s." % MULTIBOOT_WORDS.replace(
                "modes go on", "attract items go on"), "warning")
        return None
    fw = game_program(reader, target) if target else None
    if fw is None:
        raise MW.ModeWriteError("the card's game program was not found (/games/game names %s)"
                                % (target or "nothing"))
    game_raw = bytes(reader.read_file_bytes(fw))
    stime, stime_prof = (screen_times_wanted(project, game_raw, log, real_card=real_card) if stime_maybe
                         else ([], None))
    if (not modes and not code and not feed and not slots and not stime and music is None and coop_prof is None
            and hand_prof is None and comp_prof is None and not recs and att_prof is None):
        return None
    used, adds = [], {}
    hud, bank = b"", b""
    if modes or code:
        log("Found %d mode(s) to write: %s." % (len(modes) + len(code), ", ".join(
            [s.name for _g, s in modes] + ["%s (code mode)" % c.name for _s, c in code])), "info")
        _card, prof = MP.project_profile(project, probe=True)
        if prof is None and code:
            from . import code_modes as CM
            prof = CM.profile_for(project, code)
        hud_rel, bank_rel = MW.scene_rels(prof) if prof is not None else ("", "")

        def scene(rel):
            node = MW.lookup(reader, rel) if rel else None
            return bytes(reader.read_file_bytes(node)) if node is not None else b""
        hud, bank = scene(hud_rel), scene(bank_rel)
        if prof is not None and sound_ok[0]:
            used, adds = own_sounds(project, modes, reader, game_raw, prof, log, code=code)
        elif prof is not None:
            MW.choose_own_sounds(project, modes, sound_ok, log=log)   # says they are left out, and why
            if code:
                MW.choose_code_sounds(project, code, sound_ok, prof, log=log)
    if (slots or att_prof is not None) and not bank:
        # PAD-1323: the random clips go into the title's video bank (the modes' bank when it has them); PAD-1328:
        # so do the attract items' clips
        _vbank = MW.scene_rels(var_prof or att_prof)[1]
        node = MW.lookup(reader, _vbank) if _vbank else None
        bank = bytes(reader.read_file_bytes(node)) if node is not None else b""

    mus, mus_cfg, mus_prog = None, "", ""
    if music is not None:
        try:
            mus = S3MU.plan(project, music, music_prof, reader, game_raw, log, only=not (modes or code),
                            adds=adds)
        except S3MU.Spike3MusicError as e:
            log("Music modes: left out of this build: %s." % str(e).rstrip("."), "warning")
        if mus is not None:
            mdir = os.path.join(scratch, "music")
            os.makedirs(mdir, exist_ok=True)
            mus_cfg = os.path.join(mdir, "sounds.cfg")
            with open(mus_cfg, "w", encoding="utf-8", newline="\n") as f:
                f.write(mus.cfg)
            mus_prog = os.path.join(mdir, S3MU.PROGRAM_NAME)
            with open(mus_prog, "wb") as f:
                f.write(mus.program)
            if coop_prof is not None or hand_prof is not None:
                # PAD-1326: the machine runs the music modes' program, MUSIC MODE grown first and then the rows
                # of spike3_menu.rows_wanted: CO-OP PLAY's and HANDICAP's live values are read off that same grow
                from . import menu_settings as MS, spike3_menu
                _g, _placed, _r = spike3_menu.grow(game_raw, [(MS.MUSIC_MODE, music.count, music.menu_names())]
                                                   + list(spike3_menu.rows_wanted(project)))
                live = {st.key: st.live for st in _placed}
                if coop_prof is not None and coop_setting:
                    coop_setting = live.get(MS.COOP_PLAY, 0)
                    if not coop_setting:
                        log("Co-op play: left out of this build: the game's operator menu has no room for CO-OP PLAY "
                            "beside MUSIC MODE.", "warning")
                        coop_prof = None
                if hand_prof is not None and hand_setting:
                    hand_setting = live.get(MS.HANDICAP, 0)    # none: the handicaps always on, as on Spike 2
            adds = dict(adds)
            for cp, news in mus.news.items():
                adds[cp] = list(adds.get(cp) or ()) + list(news)
    if (not modes and not code and not feed and not slots and not stime and mus is None and coop_prof is None
            and hand_prof is None and comp_prof is None and not recs and att_prof is None):   # PAD-1326: co-op or handicaps alone; PAD-1327: or Competition
        return None

    def read_card(rel):
        node = MW.lookup(reader, rel)
        return bytes(reader.read_file_bytes(node)) if node is not None else None

    def scan_card(names):
        return MW.CV_scene_counts(reader, var_prof.game_dir, names) if var_prof is not None else {}
    result = MW.plan(project, hud, bank, game_raw,
                     os.path.join(scratch, "modes"), sound_ok=(False, "a Spike 3 card"), log=log,
                     end_sound=None, own_sounds=used, code_ok=True, arch="a64",
                     modes_on=bool(modes or code), score_feed=feed, score_feed_prof=feed_prof,
                     variants=bool(slots), variants_prof=var_prof,
                     screen_times=stime, screen_prof=stime_prof,
                     sound_modes=mus_cfg, sound_modes_prof=music_prof if mus is not None else None,
                     coop=coop_prof is not None, coop_prof=coop_prof, coop_setting=coop_setting,   # PAD-1326
                     handicap=hand_prof is not None, handicap_prof=hand_prof, handicap_setting=hand_setting,
                     comp=comp_prof is not None, comp_prof=comp_prof,
                     records=recs or None, records_prof=recs_prof,                   # PAD-1327
                     attract=att_prof is not None, attract_prof=att_prof,             # PAD-1328
                     read_card=read_card, scan_card=scan_card)
    if result is None:
        return None
    payload = MW.p2_payload(result, os.path.join(scratch, "modes", "padmode"), project=project,
                            arch="a64")
    names = (list(getattr(result, "mode_names", None) or [s.name for _g, s in modes])
             if modes or code else [])
    # describe() names Spike 2's place for the mode files; this card's is the games partition
    lines = [l.replace("on the system partition", "in /games/" + MODE_DIR)
             for l in result.lines]
    lines = [("Score feed: " + l[len("score feed: "):]) if l.startswith("score feed: ") else l
             for l in lines]
    # PAD-1323: and so do the random clips' and the screen times'
    for low, cap in (("random clips: ", "Random clips: "), ("screen times: ", "Screen times: "),
                     ("prolonged competition: ", "Prolonged Competition: "),   # PAD-1327
                     ("records: ", "Records on the high scores: "),
                     ("attract items: ", "Attract items: ")):                            # PAD-1328
        lines = [(cap + l[len(low):]) if l.startswith(low) else l for l in lines]
    if mus is not None:                      # PAD-1324
        lines.append("Music modes: MUSIC MODE (%d modes: %s) goes on the operator menu's %s; %d file(s) "
                     "appended to the game's sounds, played in their mode in place of the game's own."
                     % (mus.count, ", ".join(music.menu_names()), mus.setting.where.split(" > ")[-1],
                        mus.n_files))
    return Spike3ModePlan(result, payload, names, lines, sound_adds=adds, program=mus_prog, target=target)


def install_body(files, to_exec):
    """The shell lines (over the mounted games volume ``"$MP"``) that put *files* -
    ``[(name, host path, mode)]`` - in ``pad/padmode`` and point ``/games/game`` at the hook.
    Idempotent: a card already carrying modes keeps its stock target and gets the new set."""
    q = shlex.quote
    d = '"$MP"/' + MODE_DIR
    lines = [
        'G="$MP"/game',
        '[ -L "$G" ] || { echo "PAD_MODE_REFUSED /games/game is not a link" >&2; exit 6; }',
        'T=$(readlink "$G")',
        'case "$T" in',
        '    %s|/games/%s) echo "PAD_MODE_REFUSED multi-boot card" >&2; exit 6 ;;'
        % (MULTIBOOT_LINK, MULTIBOOT_LINK),
        '    %s|/games/%s) T=$(cat %s/%s) ;;' % (HOOK_LINK, HOOK_LINK, d, TARGET_NAME),
        'esac',
        '[ -n "$T" ] || { echo "PAD_MODE_REFUSED no stock game link" >&2; exit 6; }',
        'rm -rf %s' % d,
        'mkdir -p %s' % d,
        'chown 0:0 "$MP"/pad %s; chmod 755 "$MP"/pad %s' % (d, d),
    ]
    for name, src, mode in files:
        tgt = "%s/%s" % (d, q(name))
        lines.append("cp %s %s && chown 0:0 %s && chmod %o %s"
                     % (q(to_exec(src)), tgt, tgt, mode, tgt))
        lines.append('echo "PAD_MODE_FILE %s"' % q(name))
    hook = "%s/%s" % (d, HOOK_NAME)
    lines += [
        "cat > %s <<'PAD_MODE_HOOK_EOF'\n%sPAD_MODE_HOOK_EOF" % (hook, HOOK_SCRIPT),
        'chown 0:0 %s; chmod 755 %s' % (hook, hook),
        'printf "%%s\\n" "$T" > %s/%s; chmod 644 %s/%s' % (d, TARGET_NAME, d, TARGET_NAME),
        'ln -sfn %s "$G"' % HOOK_LINK,
        'sync -f "$MP"',
        'echo "PAD_MODE_OK $T"',
    ]
    return lines


def remove_body(_to_exec=None):
    """The shell lines that take the modes off: ``/games/game`` back to its stock target,
    ``pad/padmode`` gone (and ``pad`` when nothing else is in it)."""
    d = '"$MP"/' + MODE_DIR
    return [
        'G="$MP"/game',
        'T=$(cat %s/%s 2>/dev/null)' % (d, TARGET_NAME),
        '[ -n "$T" ] || { echo "PAD_MODE_REFUSED no stock game link kept" >&2; exit 6; }',
        'ln -sfn "$T" "$G"',
        'rm -rf %s' % d,
        'rmdir "$MP"/pad 2>/dev/null || true',
        'sync -f "$MP"',
        'echo "PAD_MODE_OK $T"',
    ]


def _luks_run(card_path, vol, body, log, what):
    from ...core import ext4_grow
    luks = {"key": vol["key"], "offset": vol["offset"], "sector_size": vol["sector_size"],
            "cipher": vol["cipher"]}
    try:
        out = ext4_grow.run_on_luks(card_path, vol["part_offset"], body, luks, vol["part_size"])
    except ext4_grow.Ext4GrowUnavailable as e:
        raise MW.ModeWriteError("the modes could not be %s: %s" % (what, e)) from None
    except ext4_grow.Ext4GrowError as e:
        text = str(e)
        why = next((l.split("PAD_MODE_REFUSED ", 1)[1] for l in text.splitlines()
                    if "PAD_MODE_REFUSED " in l), "")
        raise MW.ModeWriteError("the modes could not be %s%s" % (
            what, ": " + why if why else " (%s)" % text.strip()[-400:])) from None
    if "PAD_MODE_OK" not in out:
        raise MW.ModeWriteError("the modes could not be %s (%s)" % (what, out.strip()[-400:]))
    return out


def install(card_path, vol, mplan, log=None):
    """Put *mplan* (:func:`plan`) on the Spike 3 card *card_path*'s games partition. *vol*:
    the volume's ``{key, offset, sector_size, cipher, part_offset, part_size}``. Returns
    the number of files placed."""
    log = log or (lambda *a, **k: None)
    files = mplan.files()
    out = _luks_run(card_path, vol, lambda to_exec: install_body(files, to_exec), log, "put on the card")
    n = out.count("PAD_MODE_FILE ")
    log("Modes: put %s on the card's games partition (/games/%s: %d file(s)); the game starts "
        "through %s." % (", ".join(mplan.names), MODE_DIR, n, HOOK_LINK), "info")
    log("Modes: %s" % MP.INSIDER_NOTE, "info")
    return n


def remove(card_path, vol, log=None):
    """Take a card's modes off (it was built with modes; this build carries none)."""
    log = log or (lambda *a, **k: None)
    _luks_run(card_path, vol, remove_body, log, "taken off the card")
    log("Modes: took the earlier build's modes off the card; /games/game is the game's own "
        "again.", "info")
