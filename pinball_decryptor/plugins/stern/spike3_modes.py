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

What a Spike 3 build carries: the modes made in the form, on the game's own sounds. The
Spike 2 parts of a build stay Spike 2's: code modes (compiled for its 32-bit ARM), a mode's
own sounds and end sound (carriers in Spike 2's sound bank), and the rest of the family
(co-op, handicap, attract items ...), which the engine leaves out on a Spike 3 volume.

The build itself is :func:`.mode_write.plan` - the same port lookup (64-bit programs
read too), the same mode files, and the screens and clips built into the title's own
scenes, which a Spike 3 card carries as Spike 2's asset tree does - so a title's port
(PAD-1271) is all a Spike 3 card needs to take the modes the tab makes.
"""
import os
import shlex

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
if [ -f "$D/mode.so" ]; then
    LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$D/mode.so"
    export LD_PRELOAD
fi
exec "$G" "$@"
"""

#: why a Spike 3 build leaves a project's code modes out
CODE_MODES_WORDS = ("code modes are built for Spike 2 cards only; a Spike 3 card takes the "
                    "modes made in the form")
#: why a multi-boot Spike 3 card takes no modes
MULTIBOOT_WORDS = ("this is a multi-boot card; modes go on a card of the one game they were "
                   "made for")


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

    def __init__(self, result, payload, names, lines):
        self.result = result            # mode_write.ModePlan
        self.payload = payload          # mode_write.p2_payload's dict, mode.so the 64-bit one
        self.names = names              # the modes' names
        self.lines = lines              # what the build says of them
        # the title's scenes the modes' screens and clips rewrite, and any new file: whole
        self.jobs = [(rel.lstrip("/"), src) for rel, src in
                     list(result.replaced) + list(result.new)]

    def files(self):
        """``[(name on the card, host path, mode)]`` in ``pad/padmode``."""
        p = self.payload
        out = [("mode.so", p["so"], 0o755)]
        for path in (list(p["cfgs"]) + list(p.get("assets") or ()) + list(p.get("extras") or ())
                     + [p["port"]] + ([p["bundle"]] if p.get("bundle") else [])):
            out.append((os.path.basename(path), path, 0o644))
        return out


def plan(project, reader, scratch, log=None, real_card=True):
    """The project's modes for the Spike 3 games volume *reader*, built into *scratch*, or
    None when it has none this card can carry (each reason said in the log, as a Spike 2
    Write leaves modes out: the rest of the project is still written). Raises
    :class:`.mode_write.ModeWriteError` for a mode that cannot be built (the Write stops,
    as on Spike 2). *real_card* False is Try it's build for the emulator: nothing is
    written into a card, and a port derived on this PC that never ran may run there."""
    log = log or (lambda *a, **k: None)
    if not MW.preview_on():
        off = MW.preview_left_out(project)
        if off:
            log(off, "warning")
        return None
    modes = MW.project_modes(project)
    code = MW.code_mode_list(project)
    if code:
        log("Modes: the project's %d code mode(s) are left out of this build: %s."
            % (len(code), CODE_MODES_WORDS), "warning")
    if not modes:
        return None
    left = lambda why: log("Modes: the project's %d mode(s) are left out of this build: %s."
                           % (len(modes), why.rstrip(".")), "warning")
    if real_card:
        ok, why = MW.gate(dest_is_device=False)
        if not ok:
            left(why)
            return None
    why = MW.card_refusal(project, real_card=real_card)
    if why:
        left(why)
        return None
    state, target = card_state(reader)
    if state == "multiboot":
        left(MULTIBOOT_WORDS)
        return None
    fw = game_program(reader, target) if target else None
    if fw is None:
        raise MW.ModeWriteError("the card's game program was not found (/games/game names %s)"
                                % (target or "nothing"))
    log("Found %d mode(s) to write: %s." % (len(modes), ", ".join(s.name for _g, s in modes)),
        "info")
    _card, prof = MP.project_profile(project, probe=True)
    hud_rel, bank_rel = MW.scene_rels(prof) if prof is not None else ("", "")

    def scene(rel):
        node = MW.lookup(reader, rel) if rel else None
        return bytes(reader.read_file_bytes(node)) if node is not None else b""
    result = MW.plan(project, scene(hud_rel), scene(bank_rel), bytes(reader.read_file_bytes(fw)),
                     os.path.join(scratch, "modes"), sound_ok=(False, "a Spike 3 card"), log=log,
                     end_sound=None, own_sounds=(), code_ok=False)
    if result is None:
        return None
    payload = MW.p2_payload(result, os.path.join(scratch, "modes", "padmode"), project=project,
                            arch="a64")
    names = list(getattr(result, "mode_names", None) or [s.name for _g, s in modes])
    # describe() names Spike 2's place for the mode files; this card's is the games partition
    lines = [l.replace("on the system partition", "in /games/" + MODE_DIR)
             for l in result.lines]
    return Spike3ModePlan(result, payload, names, lines)


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
