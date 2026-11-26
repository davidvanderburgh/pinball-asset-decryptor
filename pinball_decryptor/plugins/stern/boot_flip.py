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


def cfg_text(live, key, default=DEFAULT_SECONDS):
    """``padmenu.cfg``: the row's value word *live* (a row of its own: the game's address of the value; on the MORE
    SETTINGS rows: the runtime's word, :data:`.menu_settings.SHARED_BASE` and up, whose value padmenu reads from
    /dump/pad_settings.state by *key*), and the seconds to use until there is one. ``flip_secs``: the value IS the
    seconds (the first build's ``flip_row`` 1..3 only ever went to Simon's test table)."""
    return "flip_secs\t0x%08x\t%s\t%d\n" % (int(live) & 0xffffffff, key, int(default))
