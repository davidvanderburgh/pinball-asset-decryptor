"""BOOT MENU FLIPPER: the multi-boot card's right flipper hold, switched in the game's own service menu.

Simon (2026-11-25, on the table): "in the service menu on this Godzilla ... there is no "custom" so there is no way to
enable or disable the right flipper action." On a multi-boot card the right flipper held 5 s with no game on restarts
the machine into the boot menu (tools/spike2_emu/codeselect/padmenu.c, "THE RIGHT FLIPPER, HELD"), as the Multi-boot
tab's Menu settings say (images.conf boot_menu= / flip_guard=). This row lets the operator switch it at the machine:

    0           Off: the hold does nothing
    15 ... 120  the hold counts once the flippers have been off that many seconds (the end of a game, a tilt, the
                bonus are past), in steps of 15

Simon (2026-11-26, after the table check): first 1 Off / 2 20 s / 3 60 s; then "we let the user set the values" - a
plain number of seconds, 15 to start with; then "I'd rather the row jump to off from 15": the game's own step of 15
(menu_settings.STEPS), so minus at 15 is Off. On the shared MORE SETTINGS rows the runtime's value row steps by one,
so there padmenu.so takes 1 to 14 as 15. The Multi-boot tab's own 20 s / 60 s stay as they are (Simon) for games
without the row.

Where the card has the row, it wins over the tab's settings. The Write puts the row on (a spare row, or MORE SETTINGS)
and :data:`CFG_NAME` beside the mode runtime says where its value is; padmenu.so, which runs inside the game, reads it
there. A card that is not a multi-boot card has no padmenu, so the row does nothing on it (its help says what it is).
"""

#: the row's values: seconds, 0 (Off), 15, 30 ... MAX_SECONDS (menu_settings.STEPS), stored as shown
MAX_SECONDS = 120
STEP_SECONDS = 15
MENU_VALUES = MAX_SECONDS // STEP_SECONDS + 1
#: 15 s to start with, the 2nd value (menu_settings counts a default from 1); also the least a hold waits
DEFAULT_SECONDS = 15
MENU_DEFAULT = DEFAULT_SECONDS // STEP_SECONDS + 1
#: the help line (63 characters is the spare help lines' room). Simon (2026-11-26): "we should state default and
#: recommended MINIMUM - 15 sec if there is text room" - exactly 63
MENU_HELP = "Hold R flipper 5s=boot menu if no game for N s. 0 Off, min 15"
#: beside the mode runtime on the card (/usr/local/padmode), read by padmenu.so
CFG_NAME = "padmenu.cfg"
#: where the Service menu tab says it does something
WHERE = ("For a multi-boot card (Multi-boot tab): the operator's switch for the right flipper hold back to the boot "
         "menu. The hold is always 5 s; the value is how many seconds no game must have been running before that "
         "hold works, so it never fires during play (0 Off, 15 to start with and the recommended minimum, up to "
         "120). It wins over the tab's own setting.")


# ---- BOOT MENU and BOOT MENU TIMER --------------------------------------------------------------------------------
# Simon (2026-11-27): "No boot menu with facility to enable/disable via service menu. Boot menu with ditto. Bootmenu - no
# service menu option (always boots to menu). We should also be able to set boot menu timer OFF/15 seconds. 30 seconds".
# Two more rows of the same kind, read by padmenu.so inside the game. The boot menu is the CARD's, not a game's, so the
# value is one for the whole card: the last change made in any game's service menu. padmenu.so keeps it in
# :data:`CARD_FILE` on the data partition (every game of a multi-boot card shares it) and, once the game has read its own
# settings, puts the card's value into the rows, so every game's menu shows what the card does. codeselect reads the
# file at power-up. Both only where the Multi-boot tab lets the service menu decide (images.conf ``menu_rows=on``); a
# card built "Boot menu, always" ignores them.
#: BOOT MENU: Off / On (stored 0 / 1). On to start with; padmenu.so puts the card's own value in before anyone looks
SHOW_DEFAULT = 2                        # menu_settings counts an Off / On row's default from 1: 2 is On
SHOW_HELP = "On: the boot menu at power-up. Off: the last game starts"
#: BOOT MENU TIMER: seconds, 0 (Off: the menu waits for START), 15, 30 (menu_settings.STEPS)
TIMER_MAX = 30
TIMER_VALUES = TIMER_MAX // STEP_SECONDS + 1
TIMER_DEFAULT = 1                       # 0 (Off) to start with; padmenu.so puts the card's own value in
TIMER_HELP = "Seconds the boot menu waits, then starts the game. 0 Off"
#: where padmenu.so keeps the card's value (codeselect reads it at power-up): "menu <0|1>" and "timer <seconds>" lines
CARD_FILE = "/data/padmenu.boot"
SHOW_WHERE = ("For a multi-boot card (Multi-boot tab, Boot menu: \"the service menu can turn it on/off\"): Off starts "
              "the last game played at power-up (the right flipper on the start-up screen still opens the menu), On "
              "shows the menu. One setting for the whole card: the last change in any game's service menu wins, and "
              "every game's menu shows it.")
TIMER_WHERE = ("For a multi-boot card (as Boot Menu): how long the boot menu counts down before it starts the game "
               "highlighted, 0 (Off: it waits for START), 15 or 30 seconds. One setting for the whole card, as Boot "
               "Menu.")


def card_lines(show=None, timer=None):
    """``padmenu.cfg`` lines for the BOOT MENU (*show*) and BOOT MENU TIMER (*timer*) rows: each ``(live, key,
    default)`` as :func:`cfg_text`'s, the default as stored (0 / 1; seconds)."""
    out = ""
    if show is not None:
        out += "boot_show\t0x%08x\t%s\t%d\n" % (int(show[0]) & 0xffffffff, show[1], int(show[2]))
    if timer is not None:
        out += "boot_timer\t0x%08x\t%s\t%d\n" % (int(timer[0]) & 0xffffffff, timer[1], int(timer[2]))
    return out


def cfg_text(live, key, default=DEFAULT_SECONDS):
    """``padmenu.cfg``: the row's value word *live* (a row of its own: the game's address of the value; on the MORE
    SETTINGS rows: the runtime's word, :data:`.menu_settings.SHARED_BASE` and up, whose value padmenu reads from
    /dump/pad_settings.state by *key*), and the seconds to use until there is one. ``flip_secs``: the value IS the
    seconds (the first build's ``flip_row`` 1..3 only ever went to Simon's test table)."""
    return "flip_secs\t0x%08x\t%s\t%d\n" % (int(live) & 0xffffffff, key, int(default))
