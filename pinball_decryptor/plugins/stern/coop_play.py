"""Co-op play on a Spike 2 card (PAD-1017; sdk/MODE_SDK.md "Co-op play", docs/plans/pad1017_coop.md).

daveyvandy: co-op on the games that have none, 2-4 players sharing progress, with high score boards of its own. The
game plays one player, whose progress and score are the team's, and the mode runtime takes the teammates in turn, a
ball each (pad_mode_runtime.c "co-op play"; the port lines are portcoop.py's). A teammate joins when Start is pressed
with the right flipper button held; a plain Start adds a competing player as the game always has.

The Modes tab's tick (the project sidecar's ``coop_play: {"on": true}``) puts ``coop.cfg`` beside the runtime on the
card: ``coop on`` and the right flipper button's switch id, read off the card's own game program.

Round 2 (DoomWalrus666, David): ``coop_play: {"on": true, "menu": true}`` also gives the game's own service menu a
CO-OP PLAY row (1 Off, 2 On; :mod:`.menu_settings`, on a spare setting), and ``coop.cfg`` names its live value
(``setting <address>``): teammates join only while it says On, and on a card of co-op and nothing else (no mode, no
attract item) the Insider Connected gate holds back only while it says On - Off, the card is the game's own on Insider
Connected."""
from . import sound_modes as _SMo

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "coop_play"
#: the runtime's file beside it on the card
CFG_NAME = "coop.cfg"
#: the port lines the runtime needs (portcoop.py)
PORT_SITES = ("coop_player_change", "coop_add_player")
PORT_DATA = ("coop_player", "coop_players")
#: the titles with co-op of their own: they keep theirs (TMNT, Venom, Mandalorian, D&D, Jaws, Jurassic Park, King
#: Kong, Bond 60th), by their title keys' stems
OWN_COOP = ("turtles_", "venom_", "mando_", "dungeons_and_dragons_", "jaws_", "jurassic_park_le", "jurassic_park_pro",
            "king_kong_", "james_bond_60th_")

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot give it co-op play.")
OWN = "%s has co-op play of its own, so the app does not add another."
NO_PORT = ("The app does not know where %s keeps its players yet, so it cannot give it co-op play.")
NO_BUTTON = "The game program names no right flipper button, so a teammate could not join."
#: round 2: the service menu's row (menu_settings.COOP_PLAY): its values, and its help line in the game's own menu
MENU_VALUES = 2
MENU_HELP = "1 Off, 2 On. On: R flipper+Start adds teammates, Insider off"
#: how a teammate joins, for the tab and the log
HOW = ("hold the right flipper button and press Start to add a teammate (2-4 players share one game); "
       "a plain Start adds a competing player as always")


class CoopError(ValueError):
    """The card's game program cannot take co-op play; the message says why."""


def load(project):
    """Whether the project's sidecar asks for co-op play."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def menu_asked(project):
    """Round 2: whether co-op is switched in the service menu (CO-OP PLAY) rather than always on."""
    if not load(project):
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("menu"))


def save(project, on, menu=None):
    """Ask (or stop asking) for co-op play; *menu* (round 2) True/False sets whether it is switched in the service
    menu, None keeps it. Returns what ``on`` was before."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    old = data.get(STAGED_KEY) if isinstance(data.get(STAGED_KEY), dict) else {}
    was = bool(old.get("on"))
    if on:
        rec = {"on": True}
        if (old.get("menu") if menu is None else menu):
            rec["menu"] = True
        data[STAGED_KEY] = rec
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def title_refusal(prof):
    """Why ``prof``'s title cannot have co-op play, or ``""``."""
    if prof is None:
        return NO_TITLE
    key = _SMo.title_key(prof)
    if key.startswith(OWN_COOP):
        return OWN % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    if not all(s in port.get("site", {}) for s in PORT_SITES) or not all(d in port.get("data", {}) for d in PORT_DATA):
        return NO_PORT % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def cfg_text(game_elf, setting=0):
    """``coop.cfg`` for the card whose game program is *game_elf* (bytes): co-op on, the right flipper button, and
    (round 2) *setting*, the CO-OP PLAY row's live value, when the service menu switches it."""
    buttons = _SMo.flipper_buttons(game_elf)
    if len(buttons) != 2:
        raise CoopError(NO_BUTTON)
    return "coop on\nbutton %d\n" % buttons[1] + ("setting 0x%08x\n" % setting if setting else "")
