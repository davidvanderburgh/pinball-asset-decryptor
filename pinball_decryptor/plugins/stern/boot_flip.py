"""BOOT MENU FLIPPER: the multi-boot card's right flipper hold, switched in the game's own service menu.

Simon (2026-11-25, on the table): "in the service menu on this Godzilla ... there is no "custom" so there is no way to
enable or disable the right flipper action." On a multi-boot card the right flipper held 5 s with no game on restarts
the machine into the boot menu (tools/spike2_emu/codeselect/padmenu.c, "THE RIGHT FLIPPER, HELD"), as the Multi-boot
tab's Menu settings say (images.conf boot_menu= / flip_guard=). This row lets the operator switch it at the machine:

    1 Off       the hold does nothing
    2 20 s      the hold counts once the flippers have been off 20 s (the end of a game, a tilt, the bonus are past)
    3 60 s      the same after 60 s

Where the card has the row, it wins over the tab's settings. The Write puts the row on (a spare row, or MORE SETTINGS)
and :data:`CFG_NAME` beside the mode runtime says where its value is; padmenu.so, which runs inside the game, reads it
there. A card that is not a multi-boot card has no padmenu, so the row does nothing on it (its help says what it is).
"""

#: the row's values, as the menu numbers them (stored 1..3)
MENU_NAMES = ("Off", "20 s", "60 s")
#: 20 s: what the Multi-boot tab starts with
MENU_DEFAULT = 2
#: the flippers off this long before a hold counts, by value (seconds; 0: the hold is off)
GUARD_S = {1: 0, 2: 20, 3: 60}
#: the help line (63 characters is the spare help lines' room)
MENU_HELP = "Right flipper 5 s: boot menu. 1 Off, 2 20 s, 3 60 s after game"
#: beside the mode runtime on the card (/usr/local/padmode), read by padmenu.so
CFG_NAME = "padmenu.cfg"
#: where the Service menu tab says it does something
WHERE = ("For a multi-boot card (Multi-boot tab): the operator switches the right flipper hold that restarts into the "
         "boot menu - Off, or after 20 s or 60 s with no game on. It wins over the tab's own setting.")


def cfg_text(live, key, default=MENU_DEFAULT):
    """``padmenu.cfg``: the row's value word *live* (a row of its own: the game's address of the value; on the MORE
    SETTINGS rows: the runtime's word, :data:`.menu_settings.SHARED_BASE` and up, whose value padmenu reads from
    /dump/pad_settings.state by *key*), and the value to use until there is one."""
    return "flip_row\t0x%08x\t%s\t%d\n" % (int(live) & 0xffffffff, key, int(default))
