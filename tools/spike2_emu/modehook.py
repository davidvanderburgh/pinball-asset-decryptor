#!/usr/bin/env python3
"""modehook.py - item 128's edit to a card's /etc/init.d/game_monitor, so a mode
of our own is preloaded into THE GAME and into nothing else.

WHY game_monitor AND NOT game, which is what this item's own wording assumed.
Read off a stock Godzilla Pro 1.15 p2 with debugfs: /etc/init.d/game does not
exec the game at all. Its launch section is

    pkill boot_display
    if [ -f $GAMES_PATH/game ]; then
            echo "starting conagent..."
            /etc/init.d/conagent_monitor $GAMES_PATH/conagent < ... &
            sleep 2
            echo "starting application..."
            /etc/init.d/game_monitor    $GAMES_PATH/game     < ... &

so an LD_PRELOAD exported there is inherited by BOTH monitors - including
conagent, Stern's Insider Connected agent - and by every child either spawns.
Item 125 measured that hazard in the emulator: a PAD_PIVOT run leaked
LD_PRELOAD into the game's system() children and the first probe SEGV'd a child
/bin/sh, which is why hook.h rule 1 gates on hk_is_game_process().

game_monitor is a restart loop whose body is a bare TAB + "$1" - the game,
invoked directly - with boot_display, dprint and pkill only on the RESTART path:

    while [ true ] ;
    do
            $1
            /usr/local/bin/boot_display&
            eval /usr/local/bin/dprint "... RESTARTING ... GAME"
            sleep 1
            pkill boot_display
    done

A COMMAND-SCOPED assignment on that one line reaches the game and nothing else -
not conagent, not boot_display, not dprint. That is the whole reason this file
edits game_monitor.

AND IT AVOIDS AN ANCHOR COLLISION. mkmulticard.hook_game_script REFUSES unless
'pkill boot_display ' sits within two lines of 'if [ -f $GAMES_PATH/game ]; then',
and codeselect's own five hook lines land exactly between them. A second hook at
that anchor would make a codeselect re-inject refuse on a card carrying ours.
Different file, different anchor, no collision - the two hooks coexist.

THE ONE DEPARTURE FROM THE PRECEDENT, and it is the part that has to be right.
hook_game_script INSERTS a block after an anchor and strip_hook deletes that
block. Ours REPLACES the "$1" line, so removal has to put that exact line back.
"Removing the mode leaves the card stock" is an acceptance clause, so strip is
written to restore byte-for-byte and the round-trip is tested, not assumed.
"""

#: The loop body of a stock game_monitor: one tab, then "$1". Byte-exact, the way
#: mkmulticard's PKILL_LINE keeps Stern's trailing space - read off the card with
#: `debugfs -R "cat /etc/init.d/game_monitor" | cat -A`, which showed "^I$1$".
RUN_LINE = "\t$1"

#: Where a card build puts the mode. /usr/local already exists on a stock p2
#: (inode 1987, 040755 root:root, holding bin/ and spike/), so this needs no new
#: parent directory.
MODE_DIR = "/usr/local/padmode"
MODE_SO = MODE_DIR + "/mode.so"
MODE_CFG = MODE_DIR + "/mode.cfg"

#: What replaces RUN_LINE. Guarded on the .so existing, so a card whose mode has
#: been removed - or was never installed - runs the stock line and nothing else.
#: The assignment is command-scoped ON PURPOSE: `LD_PRELOAD=... $1` applies to
#: that one invocation, never to the boot_display/dprint/pkill lines below it.
HOOK_LINES = [
    "\t# padmode (item 128): preload a mode of our own into THE GAME only.",
    "\t# Command-scoped, so the restart lines below and conagent never see it.",
    "\tif [ -f " + MODE_SO + " ]; then",
    "\t\tLD_PRELOAD=" + MODE_SO + " $1",
    "\telse",
    "\t\t$1",
    "\tfi",
]


class Refused(Exception):
    """The script is not what we expect, so nothing is written. Never a guess."""


def _lines(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return text.split("\n")


def strip_hook(text):
    """Remove one HOOK_LINES block, restoring the stock RUN_LINE in its place.

    The exact inverse of hook_game_monitor. Returns the text unchanged when the
    block is not there, so it is safe to call on a stock script.
    """
    lines = _lines(text)
    n = len(HOOK_LINES)
    for k in range(len(lines) - n + 1):
        if lines[k:k + n] == HOOK_LINES:
            lines[k:k + n] = [RUN_LINE]
            return "\n".join(lines)
    return "\n".join(lines)


def has_hook(text):
    """True when this script already carries our block.

    Asked of strip_hook rather than by looking for a marker line, so there is ONE
    definition of "is it hooked" and it is the same contiguous-block match that
    removal uses. Two functions answering this question their own way is how
    autoattract.sh and status.sh came to disagree about Tech Alerts for a whole
    run; mkmulticard.has_hook is written this way for the same reason.
    """
    t = "\n".join(_lines(text))          # normalise bytes/str ONCE, then compare
    return strip_hook(t) != t


def hook_game_monitor(text):
    """Replace the stock `\\t$1` line with the guarded preload block.

    Idempotent: an already hooked script comes out the same, because the block is
    stripped first. Anything unexpected about the anchor raises Refused - the
    same discipline as mkmulticard.hook_game_script, which is what keeps a card
    build from editing a script it does not recognise.
    """
    text = strip_hook(text)
    lines = _lines(text)
    hits = [k for k, l in enumerate(lines) if l == RUN_LINE]
    if len(hits) != 1:
        raise Refused(
            "game_monitor: expected exactly one %r line, found %d - this is not a "
            "stock Spike 2 game_monitor and nothing has been written"
            % (RUN_LINE, len(hits)))
    k = hits[0]
    lines[k:k + 1] = HOOK_LINES
    return "\n".join(lines)


def describe(text):
    """One line for a log: whether this script carries the mode hook."""
    return ("game_monitor: mode hook present, preloading " + MODE_SO
            if has_hook(text) else "game_monitor: stock (no mode hook)")
