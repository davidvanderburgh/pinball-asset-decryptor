"""BOOT MENU FLIPPER: the multi-boot card's right flipper hold, switched in the game's own service menu.

Simon (2026-11-25, on the table): "in the service menu on this Godzilla ... there is no "custom" so there is no way to
enable or disable the right flipper action." On a multi-boot card the right flipper held 5 s with no game on restarts
the machine into the boot menu (tools/spike2_emu/codeselect/padmenu.c, "THE RIGHT FLIPPER, HELD"), as the Multi-boot
tab's Menu settings say (images.conf boot_menu= / flip_guard=). This row lets the operator switch it at the machine:

    0           Off: the hold does nothing
    1 to 120    the hold counts once the flippers have been off that many seconds (the end of a game, a tilt, the
                bonus are past)

Simon (2026-11-26, after the table check): first 1 Off / 2 20 s / 3 60 s; then "we let the user set the values" - a
plain number of seconds the operator steps with +/- (menu_settings.WIDE_VALUES), 15 to start with. The Multi-boot tab's
own 20 s / 60 s stay as they are (Simon) for games without the row.

Where the card has the row, it wins over the tab's settings. The Write puts the row on (a spare row, or MORE SETTINGS)
and :data:`CFG_NAME` beside the mode runtime says where its value is; padmenu.so, which runs inside the game, reads it
there. A card that is not a multi-boot card has no padmenu, so the row does nothing on it (its help says what it is).
"""

#: the row's values: seconds, 0 (Off) to MAX_SECONDS, stored as shown
MAX_SECONDS = 120
MENU_VALUES = MAX_SECONDS + 1
#: 15 s to start with (menu_settings counts a default from 1: value 15 is the 16th)
DEFAULT_SECONDS = 15
MENU_DEFAULT = DEFAULT_SECONDS + 1
#: the help line (63 characters is the spare help lines' room). Simon (2026-11-26): "we should state default and
#: recommended MINIMUM - 15 sec if there is text room" - exactly 63
MENU_HELP = "R flipper 5s: boot menu. 0 Off, secs after game. Min/default 15"
#: beside the mode runtime on the card (/usr/local/padmode), read by padmenu.so
CFG_NAME = "padmenu.cfg"
#: where the Service menu tab says it does something
WHERE = ("For a multi-boot card (Multi-boot tab): the operator sets the right flipper hold that restarts into the "
         "boot menu - 0 Off, or the seconds after a game before it works (15 to start with, and the recommended "
         "minimum). It wins over the tab's own setting.")


def cfg_text(live, key, default=DEFAULT_SECONDS):
    """``padmenu.cfg``: the row's value word *live* (a row of its own: the game's address of the value; on the MORE
    SETTINGS rows: the runtime's word, :data:`.menu_settings.SHARED_BASE` and up, whose value padmenu reads from
    /dump/pad_settings.state by *key*), and the seconds to use until there is one. ``flip_secs``: the value IS the
    seconds (the first build's ``flip_row`` 1..3 only ever went to Simon's test table)."""
    return "flip_secs\t0x%08x\t%s\t%d\n" % (int(live) & 0xffffffff, key, int(default))
