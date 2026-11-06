"""Inactivity pauses the timers on a Spike 2 card whose game ignores its own setting (PAD-1022; sdk/MODE_SDK.md
"Inactivity pauses the timers", pad_mode_runtime.c "inactivity pauses the game's timers").

Joe_Blasi (Pinside): ALLOW INACTIVITY TO PAUSE TIMERS does nothing on Guardians of the Galaxy. Every Spike 2 game's
menu has the setting, and the other titles' own timers stop when nobody has scored for a few seconds; Guardians 1.15
(Pro and LE) never reads it. The mode runtime gives it the rule: while the setting is on and the player has not scored
for 6 seconds, the missions' clocks (their songs' clocks) and the hurry-ups wait.

The runtime does this on any card it runs on whose port names the game's clocks (``PORT_SITES``). The Modes tab's tick
(the project sidecar's ``idle_pause: {"on": true}``) puts ``idle.cfg`` beside the runtime so a card with no modes of
its own carries it too."""

#: the project sidecar's key: ``{"on": true}``
STAGED_KEY = "idle_pause"
#: the runtime's file beside it on the card
CFG_NAME = "idle.cfg"
#: the port lines that say the game needs the runtime's rule (either is enough; pad_mode_runtime.c idle_arm)
PORT_SITES = ("timers_paused", "song_track")
PORT_VALUE = "inactive_adj"

LABEL = "Inactivity pauses timers"
NO_TITLE = "The app cannot tell which game this project is for."
NO_NEED = "%s pauses its timers by itself when its ALLOW INACTIVITY TO PAUSE TIMERS setting is on."
#: what the card does, for the tab and the log
HOW = ("with ALLOW INACTIVITY TO PAUSE TIMERS on (the game's own setting, on by default), the missions' clocks and "
       "the hurry-ups wait when nobody has scored for 6 seconds, and run on at the next score")
#: the Modes tab's line under the tick
NOTE = "On the card: the clocks wait after 6 seconds with no score, while the game's setting is on."


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


def port_needs(port):
    """1 when a parsed port names the clocks of a game that ignores its own setting."""
    return bool(port) and any(s in port.get("site", {}) for s in PORT_SITES) and PORT_VALUE in port.get("value", {})


def title_refusal(prof):
    """Why ``prof``'s game does not need (or cannot have) it, or ``""``."""
    if prof is None:
        return NO_TITLE
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_NEED % prof.label
    return "" if port_needs(port) else NO_NEED % prof.label


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def cfg_text(only):
    """``idle.cfg``: *only* when the card carries no modes (the runtime then arms this and nothing else)."""
    return "# PAD-1022: inactivity pauses the game's timers\nidle on\n" + ("only\n" if only else "")

