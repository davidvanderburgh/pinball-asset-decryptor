"""Prolonged Competition on a Spike 2 card's start menu (PAD-1041; sdk/MODE_SDK.md "Prolonged Competition",
pad_mode_runtime.c "Prolonged Competition on the start menu").

Joe_Blasi (Pinside): "can the prolonged comp (in player menu) be added to all games?" Venom and Dungeons & Dragons
offer it on CHOOSE YOUR MODE OF PLAY (both flipper buttons in attract): COMPETITION GAME PLAY UNTIL POWERED OFF. Picked
once, every game after it plays as Competition until the machine is switched off; picked again, it ends. Every other
Spike 2 game has only the one-game COMPETITION entry, which sets one flag, FG_PLAYER_COMPETITION_MODE_ACTIVE, and
nothing else (the menu's kind jump, read on all 53 latest builds). The mode runtime adds a PROLONGED entry to that menu
and keeps the flag set at every game's start while it is on.

The Modes tab's tick (the project sidecar's ``prolonged_comp: {"on": true}``) puts ``comp.cfg`` beside the runtime: the
flag's id and the menu's COMPETITION and STANDARD captions, read off the card's own game program (:func:`cfg_text`).
Like the game's own Competition, it keeps the card on Insider Connected."""
import re

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "prolonged_comp"
#: the runtime's file beside it on the card
CFG_NAME = "comp.cfg"
#: the port lines the runtime needs: the start menu's (portchallenge.py's) and the event bus
PORT_SITES = ("challenge_menu", "challenge_menu_pick", "hook_dispatch")
PORT_VALUES = ("challenge_menu_list_at", "challenge_menu_cap")
PORT_EVENTS = ("game_start", "ball_start")
#: the titles with a Prolonged Competition of their own: they keep theirs, by their title keys' stems
OWN = ("venom_", "dungeons_and_dragons_")
FLAG = "FG_PLAYER_COMPETITION_MODE_ACTIVE"

LABEL = "Prolonged Competition"
NO_TITLE = "The app cannot tell which game this project is for, so it cannot give it Prolonged Competition."
OWN_ONE = "%s has Prolonged Competition on its start menu already."
NO_PORT = ("The app does not know %s's start menu yet, so it cannot add Prolonged Competition to it.")
NO_FLAG = "The game program names no %s flag, so there is no Competition game to prolong." % FLAG
NO_CAPTION = "The game program's start menu has no COMPETITION and STANDARD captions to show the entry with."
#: how a player uses it, for the tab and the log
HOW = ("hold both flipper buttons in attract to open the start menu: COMPETITION / UNTIL POWERED OFF makes every game "
       "a Competition game until the machine is switched off, and STANDARD / ENDS PROLONGED COMPETITION ends it")
#: the Modes tab's line under the tick
NOTE = "On the card: COMPETITION / UNTIL POWERED OFF on the start menu. Picked again, it ends."


class CompError(ValueError):
    """The card's game program cannot take Prolonged Competition; the message says why."""


def load(project):
    """Whether the project's sidecar asks for it."""
    if not project:
        return False
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: no
        return False
    return bool(isinstance(raw, dict) and raw.get("on"))


def save(project, on):
    """Ask (or stop asking) for it; returns what it was before."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    was = bool(isinstance(data.get(STAGED_KEY), dict) and data[STAGED_KEY].get("on"))
    if on:
        data[STAGED_KEY] = {"on": True}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def port_ready(port):
    """1 when a parsed port names the start menu and the events the runtime keeps the flag set at."""
    if not port:
        return False
    sites, values = port.get("site", {}), port.get("value", {})
    events = {e[0] for e in port.get("event", ()) if len(e) > 1 and e[1] == "bus"}   # on the bus, as the runtime's
    return (all(s in sites for s in PORT_SITES) and all(v in values for v in PORT_VALUES)
            and ("challenge_menu_count_at" in values or "challenge_menu_count_reg" in values)
            and all(e in events for e in PORT_EVENTS))


def title_refusal(prof):
    """Why ``prof``'s game cannot have it (or has its own), or ``""``."""
    if prof is None:
        return NO_TITLE
    if prof.key.startswith(OWN):
        return OWN_ONE % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    return "" if port_ready(port) else NO_PORT % prof.label


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def card_lines(game_elf):
    """``(flag, caption, caption_end)`` read off the card's game program: the Competition flag's id (the FG_ name
    table's index) and the start menu's COMPETITION and STANDARD caption message ids (the first of each after CHOOSE
    YOUR MODE OF PLAY's). Raises :class:`CompError`."""
    from . import portchallenge as PC
    try:
        e = PC.Elf(game_elf)
    except Exception as ex:                             # noqa: BLE001 - not an ELF the reader knows
        raise CompError("the card's game program could not be read (%s)" % ex) from None
    names = PC.flag_names(e)
    if FLAG not in names:
        raise CompError(NO_FLAG)
    table, n = PC.message_table(e)
    head = None
    if table:
        head = next((i for i in range(n) if PC.message_text(e, table, i) == "CHOOSE YOUR MODE OF PLAY"), None)
    if head is None:
        raise CompError(NO_CAPTION)

    def caption(words):
        return next((i for i in range(head, min(n, head + 40)) if PC.message_text(e, table, i) == words), None)
    comp, std = caption("COMPETITION"), caption("STANDARD")
    if comp is None or std is None:
        raise CompError(NO_CAPTION)
    return names.index(FLAG), comp, std


def cfg_text(game_elf, only):
    """``comp.cfg`` for the card's game program; *only* when the card carries no modes (the runtime then arms this
    and nothing else). Raises :class:`CompError`."""
    flag, comp, std = card_lines(game_elf)
    return ("# PAD-1041: Prolonged Competition on the start menu\ncomp on\nflag %d\ncaption %d\ncaption_end %d\n%s"
            % (flag, comp, std, "only\n" if only else ""))


def cfg_values(text):
    """The numbers a ``comp.cfg`` names, by key (for the tests and the build's log)."""
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"(?m)^(flag|caption|caption_end) (\d+)$", text or "")}
