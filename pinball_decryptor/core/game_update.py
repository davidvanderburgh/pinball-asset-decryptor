"""PAD-1585: "Update to 1.0.1" - a machine's project carried onto Stern's newer build, by PAD instead of Stern's
updater (which a card PAD built now refuses: core/update_guard.py).

The steps are the one-click port's (core/mod_port.py: extract the new stock image, transfer the project's work onto
it, stage, build); what this module adds is what an UPDATE needs on top:

* :func:`check_new_card`: the image the owner gives is the same game as the machine's and a newer build, before
  minutes go into extracting it;
* :func:`carry_report`: what cannot be carried, said BEFORE anything is built (a sound whose slot is gone or now
  holds another sound, a clip the new build lacks, modes the app has no port for yet), so the owner chooses
  between updating without those and waiting.

The app downloads nothing: the owner fetches the new image from Stern and points at it.
"""
from __future__ import annotations

import os


class UpdateRefused(Exception):
    """The image cannot update this machine (another game, an older or the same build): the words say why."""


def _label(game, version):
    try:
        from ..plugins.stern.mode_project import title_label
        return title_label(game, version)
    except Exception:                                   # noqa: BLE001
        return "%s %s" % (game, version)


def _key(version):
    try:
        return tuple(int(p) for p in str(version).replace("_", ".").split("."))
    except ValueError:
        return (str(version),)


def read_build(card, reader=None):
    """``(game, version)`` of the Spike 2 card image *card* (its game program's own words)."""
    if reader is None:
        from ..plugins.stern import title_reader
        reader = title_reader.game_program
    game, version = reader(card)[:2]
    return game, version


def check_new_card(machine_card, new_card, reader=None):
    """``(old_label, new_label)`` when *new_card* is the same game as *machine_card* and a newer build of it;
    raises :class:`UpdateRefused` otherwise, in words for the owner."""
    try:
        new_game, new_ver = read_build(new_card, reader)
    except Exception as e:                              # noqa: BLE001
        raise UpdateRefused("%s is not a Stern Spike 2 card image the app can read (%s)."
                            % (os.path.basename(new_card), e)) from None
    try:
        old_game, old_ver = read_build(machine_card, reader)
    except Exception:                                   # noqa: BLE001
        old_game, old_ver = None, None
    new_label = _label(new_game, new_ver)
    if old_game is None:
        return "", new_label
    old_label = _label(old_game, old_ver)
    if old_game != new_game:
        raise UpdateRefused("%s is %s, but this machine is %s: pick the new card image of its own game."
                            % (os.path.basename(new_card), new_label, old_label))
    if _key(new_ver) <= _key(old_ver):
        raise UpdateRefused("%s is %s, and this machine already runs %s: pick the newer build."
                            % (os.path.basename(new_card), new_label, old_label))
    return old_label, new_label


#: the plan's categories as the report counts them
_CATS = (("audio", "sound"), ("video", "video"), ("image", "picture"), ("text", "text edit"))


def _n(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def carry_report(plan, detail_lines, modes_line="", modes_blocked=False, new_label=""):
    """What the update carries and what it cannot, for the question asked before the build.

    *plan* is :func:`core.mod_transfer.plan_transfer`'s; *detail_lines* its
    :func:`~core.mod_transfer.plan_detail_lines` (``[(level, text)]``: the error and warning ones name what is
    left out); *modes_line* the manufacturer's ``mode_news`` sentence and *modes_blocked* whether it says the
    modes can't run on the new build. -> ``{"carried": [...], "left_out": [...], "modes": str, "clean": bool}``."""
    carried = []
    for key, word in _CATS:
        got = plan.get(key) or {}
        n = len(got.get("matched") or ()) + len(got.get("remapped") or ())
        if n:
            carried.append(_n(n, word))
    left = [text for level, text in detail_lines if level in ("error", "warning")]
    text_drop = len((plan.get("text") or {}).get("dropped") or ())
    if text_drop and not any(t.startswith("Text") for t in left):
        left.append("%s cannot be carried: the new build has no matching line." % _n(text_drop, "text edit"))
    modes = modes_line if modes_blocked else ""
    return {"carried": carried, "left_out": left, "modes": modes,
            "clean": not left and not modes, "new_label": new_label}


def question(report, cap=12):
    """``(title, message)`` of the question asked before the build: yes builds without what is left out."""
    new = report.get("new_label") or "the new build"
    carried = ", ".join(report["carried"]) or "nothing"
    lines = ["Carried onto %s: %s." % (new, carried)]
    if report["clean"]:
        lines += ["", "Everything in the project carries over.", "",
                  "Build the update now? Nothing has been written yet."]
        return "Update to %s" % new, "\n".join(lines)
    lines += ["", "These can NOT be carried:"]
    left = report["left_out"]
    lines += ["  - " + t for t in left[:cap]]
    if len(left) > cap:
        lines.append("  - and %d more (all of them are in the log)" % (len(left) - cap))
    if report["modes"]:
        lines.append("  - " + report["modes"])
        lines.append("    The modes go on again once the app can run them on this build: update without them "
                     "now, or wait.")
    lines += ["", "Yes builds the update without these. No stops here: nothing has been written."]
    return "Update to %s without these?" % new, "\n".join(lines)
