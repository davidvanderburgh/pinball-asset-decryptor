"""GAME POINTS (PAD-798): every point the game adds, times N.

An owner asked whether TMNT's scoring could have "an extra 0" on its point values. The Write tab's
Game points picks a factor (:data:`CHOICES`; Normal, the default, changes nothing). A Write of a
project with a factor above 1 puts ``points.cfg`` beside the mode runtime (one ``times`` line), and
the runtime (pad_mode_runtime.c "game points") wraps the game's own score function: every award the
game gives, its bonus and a mode's points included, is multiplied before the game adds it, so the
display, the playfield multiplier, replays and the high-score board all go with it.

It rides the modes' delivery (the runtime, the title's port and the cfg on the system partition), so
it needs an image build and a title the app has a port for. A multiplied score is not one the game
would have given, so it takes the modes' Insider Connected gate: the machine sends no scores, high
scores or achievements to Insider Connected (the runtime hooks nothing at all without that gate).
"""
from __future__ import annotations

#: the project sidecar's key: ``{"times": N}``
STAGED_KEY = "game_points"
#: the runtime's file, beside mode.so on p2 (pad_mode_runtime.c PTS_FILES)
CFG_NAME = "points.cfg"
#: the factors offered; 1 is Normal (no file on the card)
CHOICES = (1, 2, 3, 5, 10, 100)
#: the runtime's ceiling (pad_mode_runtime.c PTS_TIMES_MAX)
MAX_TIMES = 1000

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot change its "
            "scoring.")
NO_PORT = ("The app does not know %s's game program well enough to change its scoring yet.")
#: the sites the runtime needs: the score function and the Insider Connected gate
_GATE = ("agent_header", "agent_begin")


def label(times):
    """The choice's words: ``Normal`` for 1, else ``x10``."""
    return "Normal" if int(times) <= 1 else "x%d" % int(times)


def load(project):
    """The project's factor, 1 when it asks for none (or the sidecar cannot be read)."""
    if not project:
        return 1
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(STAGED_KEY)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return 1
    try:
        times = int(raw.get("times", 1)) if isinstance(raw, dict) else 1
    except (TypeError, ValueError):
        return 1
    return times if 1 <= times <= MAX_TIMES else 1


def save(project, times):
    """Set the project's factor (1 takes it off); returns what it was before."""
    from ...core import staged_changes
    times = int(times)
    if not 1 <= times <= MAX_TIMES:
        raise ValueError("game points must be 1 to %d times" % MAX_TIMES)
    data = staged_changes.load(project)
    was = load(project)
    if times > 1:
        data[STAGED_KEY] = {"times": times}
    else:
        data.pop(STAGED_KEY, None)
    staged_changes.save(project, data)
    return was


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def title_refusal(prof):
    """Why ``prof``'s game cannot have its points changed, or ``""``: its port must name the score
    function the runtime wraps and the Insider Connected gate."""
    from . import mode_project as MP
    if prof is None:
        return NO_TITLE
    if not getattr(prof, "port", None):
        return NO_PORT % prof.label
    try:
        sites = MP.read_port(MP.port_path(prof))["site"]
    except (OSError, MP.ModeProjectError):
        return NO_PORT % prof.label
    if not ("score_add" in sites or "score_add32" in sites) or not all(s in sites for s in _GATE):
        return NO_PORT % prof.label
    return ""


def cfg_text(times):
    """``points.cfg`` for factor *times*."""
    times = int(times)
    if not 2 <= times <= MAX_TIMES:
        raise ValueError("game points must be 2 to %d times" % MAX_TIMES)
    return ("# PAD-798 game points: every point the game adds, times this\n"
            "times\t%d\n" % times)
