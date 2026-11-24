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

#: THE MULTI-BOOT FORM (PAD-1309).  A multi-boot card's selector directory carries
#: padmenu.so - BACK held 3 s (Hold BACK, back_hold=) on the coin door restarts the machine into the boot
#: menu - and it has to be preloaded into the game whatever that image is, stock
#: or with modes of its own.  So a multi-boot card's game_monitor carries this
#: block instead of HOOK_LINES: each object preloaded when it is there, both when
#: both are (padmenu.so first: it hands every ioctl on, so mode.so sees the game's
#: calls exactly as it does without it), the stock line when neither is.  Still
#: command-scoped, still one block strip_hook puts the stock line back for.
#: mode_install.py's single-card hook stays HOOK_LINES, byte for byte.
MENU_SO = "/usr/local/codeselect/padmenu.so"
MENU_HOOK_LINES = [
    "\t# padmode (item 128) + padmenu (PAD-1309): preload into THE GAME only.",
    "\t# Command-scoped, so the restart lines below and conagent never see it.",
    "\tPADPRE=",
    "\t[ -f " + MENU_SO + " ] && PADPRE=" + MENU_SO,
    "\t[ -f " + MODE_SO + " ] && PADPRE=${PADPRE:+$PADPRE:}" + MODE_SO,
    "\tif [ -n \"$PADPRE\" ]; then",
    "\t\tLD_PRELOAD=$PADPRE $1",
    "\telse",
    "\t\t$1",
    "\tfi",
]
#: THE REMOTE-BUTTONS FORM (PAD-1467).  A card with remote buttons (the app's core/remote_buttons.py, which
#: writes this block) preloads pad-buttons.so into the game as well: it adds a press from the PC to the cabinet
#: word the game reads, coin door permitting.  One block for every case: each of the three objects when it is
#: there, the stock line when none is.  The menu first, then the buttons, then the mode runtime: each hands
#: every ioctl on.  core/remote_buttons.py carries the same lines, and a test holds the two equal.
BUTTONS_SO = "/usr/local/bin/pad-buttons.so"
ALL_HOOK_LINES = [
    "\t# padmode (item 128) + padmenu (PAD-1309) + pad-buttons (PAD-1467): preload into THE GAME only.",
    "\t# Command-scoped, so the restart lines below and conagent never see it.",
    "\tPADPRE=",
    "\t[ -f " + MENU_SO + " ] && PADPRE=" + MENU_SO,
    "\t[ -f " + BUTTONS_SO + " ] && PADPRE=${PADPRE:+$PADPRE:}" + BUTTONS_SO,
    "\t[ -f " + MODE_SO + " ] && PADPRE=${PADPRE:+$PADPRE:}" + MODE_SO,
    "\tif [ -n \"$PADPRE\" ]; then",
    "\t\tLD_PRELOAD=$PADPRE $1",
    "\telse",
    "\t\t$1",
    "\tfi",
]
#: THE BLUETOOTH FORM (PAD-1554).  A card with Bluetooth headphones (the app's core/bluetooth_card.py, which
#: writes this block) starts the game through spike-pinball-bluetooth's own launcher,
#: /usr/local/spikebt/run-live.sh (https://gitlab.com/mattlqx/spike-pinball-bluetooth): it starts its helper,
#: preloads its menu and our mode.so into the game itself, and runs the plain game when anything is missing.
#: The launcher knows mode.so only, so when the card also has padmenu.so or pad-buttons.so it is handed
#: BT_GAME instead of the game: a few lines of sh that put those in front of the launcher's own preload list
#: and exec the game (PADGAME).  With no launcher on the card, or its `enabled` file gone, the block does what
#: ALL_HOOK_LINES does.  core/remote_buttons.py carries the same lines, and a test holds the two equal.
BT_DIR = "/usr/local/spikebt"
BT_RUN = BT_DIR + "/run-live.sh"
BT_ENABLED = BT_DIR + "/enabled"
BT_GAME = "/usr/local/bin/pad-bt-game"
BT_HOOK_LINES = [
    "\t# padmode (item 128) + padmenu (PAD-1309) + pad-buttons (PAD-1467) + Bluetooth headphones (PAD-1554).",
    "\t# Command-scoped, so the restart lines below and conagent never see it.",
    "\tPADPRE=",
    "\t[ -f " + MENU_SO + " ] && PADPRE=" + MENU_SO,
    "\t[ -f " + BUTTONS_SO + " ] && PADPRE=${PADPRE:+$PADPRE:}" + BUTTONS_SO,
    "\tif [ -f " + BT_ENABLED + " ] && [ -x " + BT_RUN + " ]; then",
    "\t\t# spike-pinball-bluetooth's launcher starts the game: it preloads its menu and mode.so itself",
    '\t\tif [ -n "$PADPRE" ] && [ -x ' + BT_GAME + " ]; then",
    "\t\t\tPADGAME=$1 PADPRE=$PADPRE " + BT_RUN + " " + BT_GAME,
    "\t\telse",
    "\t\t\t" + BT_RUN + " $1",
    "\t\tfi",
    "\telse",
    "\t\t[ -f " + MODE_SO + " ] && PADPRE=${PADPRE:+$PADPRE:}" + MODE_SO,
    '\t\tif [ -n "$PADPRE" ]; then',
    "\t\t\tLD_PRELOAD=$PADPRE $1",
    "\t\telse",
    "\t\t\t$1",
    "\t\tfi",
    "\tfi",
]
BLOCKS = (BT_HOOK_LINES, ALL_HOOK_LINES, MENU_HOOK_LINES, HOOK_LINES)


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
    for block in BLOCKS:
        n = len(block)
        for k in range(len(lines) - n + 1):
            if lines[k:k + n] == block:
                lines[k:k + n] = [RUN_LINE]
                return "\n".join(lines)
    return "\n".join(lines)


def has_menu_hook(text):
    """True when this script carries the multi-boot block (MENU_HOOK_LINES)."""
    lines = _lines(text)
    n = len(MENU_HOOK_LINES)
    return any(lines[k:k + n] == MENU_HOOK_LINES for k in range(len(lines) - n + 1))


def has_buttons_hook(text):
    """True when this script carries the remote-buttons block (ALL_HOOK_LINES)."""
    lines = _lines(text)
    n = len(ALL_HOOK_LINES)
    return any(lines[k:k + n] == ALL_HOOK_LINES for k in range(len(lines) - n + 1))


def has_bluetooth_hook(text):
    """True when this script carries the Bluetooth block (BT_HOOK_LINES)."""
    lines = _lines(text)
    n = len(BT_HOOK_LINES)
    return any(lines[k:k + n] == BT_HOOK_LINES for k in range(len(lines) - n + 1))


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


def hook_game_monitor(text, menu=None):
    """Replace the stock `\\t$1` line with the guarded preload block: the
    multi-boot one (MENU_HOOK_LINES) when `menu`, HOOK_LINES when not, and when
    `menu` is None whichever the script already carries (so a mode install on a
    multi-boot card keeps padmenu.so preloaded).

    Idempotent: an already hooked script comes out the same, because the block is
    stripped first. Anything unexpected about the anchor raises Refused - the
    same discipline as mkmulticard.hook_game_script, which is what keeps a card
    build from editing a script it does not recognise.
    """
    if menu is None:
        menu = has_menu_hook(text)
    buttons = has_buttons_hook(text)        # PAD-1467: a card with remote buttons keeps its block, whatever else
    bluetooth = has_bluetooth_hook(text)    # PAD-1554: and one with Bluetooth headphones keeps that one
    text = strip_hook(text)
    lines = _lines(text)
    hits = [k for k, l in enumerate(lines) if l == RUN_LINE]
    if len(hits) != 1:
        raise Refused(
            "game_monitor: expected exactly one %r line, found %d - this is not a "
            "stock Spike 2 game_monitor and nothing has been written"
            % (RUN_LINE, len(hits)))
    k = hits[0]
    lines[k:k + 1] = (BT_HOOK_LINES if bluetooth else ALL_HOOK_LINES if buttons
                      else MENU_HOOK_LINES if menu else HOOK_LINES)
    return "\n".join(lines)


def describe(text):
    """One line for a log: whether this script carries the mode hook."""
    if has_bluetooth_hook(text):
        return ("game_monitor: Bluetooth hook present, the game started by %s when it is there, else "
                "preloading %s, %s and %s when there" % (BT_RUN, MENU_SO, BUTTONS_SO, MODE_SO))
    if has_buttons_hook(text):
        return ("game_monitor: remote-buttons hook present, preloading %s, %s and %s when there"
                % (MENU_SO, BUTTONS_SO, MODE_SO))
    if has_menu_hook(text):
        return ("game_monitor: multi-boot hook present, preloading %s and %s when there"
                % (MENU_SO, MODE_SO))
    return ("game_monitor: mode hook present, preloading " + MODE_SO
            if has_hook(text) else "game_monitor: stock (no mode hook)")
