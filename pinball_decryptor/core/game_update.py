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


def carry_report(plan, detail_lines, modes_line="", modes_blocked=False, new_label="", modes_left=()):
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
    left = [text for level, text in detail_lines if level in ("error", "warning")] + list(modes_left)
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


# ---- modes (Stern Spike 2): carried by shot name onto the new build --------------------------------------
def modes_check(project, workspace):
    """``(carry, left_out)`` for the modes of *project* on the build extracted into *workspace*, checked the way
    ``mode_project.copy_modes`` matches them (shots by NAME, :func:`retarget`) without copying anything:
    *carry* the slugs that run there as they are (and code modes, which a build checks), *left_out* a sentence
    per mode that names a shot the new build lacks or does not load. Those stay in the old project (nothing
    is lost): an update without them never puts a mode on the card that a build would refuse.
    ``([], [])`` when the project has no modes or the new build has no port (``mode_news`` says that)."""
    from ..plugins.stern import mode_project as MP
    from ..plugins.stern import code_modes as CM
    try:
        found, broken = MP.list_modes(project)
        codes = CM.code_slugs(project)
    except Exception:                                   # noqa: BLE001
        return [], []
    if not found and not broken and not codes:
        return [], []
    try:
        _card, p = MP.project_profile(workspace)
    except Exception:                                   # noqa: BLE001
        p = None
    if p is None:
        return [], []
    carry, left = [], []
    for slug, spec in found:
        new, dropped = MP.retarget(spec, p)
        problems = []
        if not dropped:
            try:
                problems = MP.validate(new, MP.mode_folder(project, slug))
            except Exception:                           # noqa: BLE001
                problems = []
        if dropped or problems:
            why = ("%s has no %s" % (p.label, ", ".join(dropped))) if dropped else " ".join(problems)
            left.append("Mode %s: %s. It stays in the old project: pick its shots again there, then Copy to... "
                        "on the Modes tab carries it over." % (spec.name, why))
        else:
            carry.append(slug)
    for slug, why in broken:
        left.append("Mode %s: its file does not load (%s)." % (slug, why))
    return carry + list(codes), left


def carry_modes(project, workspace, slugs, log=None):
    """Copy the modes *slugs* (:func:`modes_check`'s *carry*) of *project* into the new build's *workspace*
    (``mode_project.copy_modes``: whole folders, saved for the new title). -> the report's summary ('' when
    there is nothing to carry)."""
    if not slugs:
        return ""
    from ..plugins.stern import mode_project as MP
    report = MP.copy_modes(project, workspace, slugs=slugs)
    if log:
        for line in report.lines():
            log("Modes: " + line, "info")
    return report.summary().split("\n\n", 1)[0]


# ---- a multi-boot card: every image of the game, the rest left alone ------------------------------------
def multiboot_plan(rows, new_card, reader=None, project_of=None):
    """What an update does to each image of a multi-boot card, before anything runs.

    *rows* are ``(index, path, is_group)`` of the Multi-boot tab's rows; *new_card* the new stock image. A row is
    ``("project", folder)`` when its image is a build of the same game the app made from a project that is still
    there (the project goes onto the new build, as a one-game update), ``("stock", "")`` when it is Stern's own
    image of that game (it becomes the new image as it is), or ``("keep", why)`` - another game, a random card, a
    build of this game the app has no project of, an image not older than the new one. -> ``(new_label, [(index,
    kind, what)])``; raises :class:`UpdateRefused` when no row is that game at all."""
    if reader is None:
        from ..plugins.stern import title_reader
        reader = title_reader.game_program
    if project_of is None:
        from .extract_source import _build_project
        project_of = _build_project
    try:
        new_game, new_ver = read_build(new_card, reader)
    except Exception as e:                              # noqa: BLE001
        raise UpdateRefused("%s is not a Stern Spike 2 card image the app can read (%s)."
                            % (os.path.basename(new_card), e)) from None
    new_label = _label(new_game, new_ver)
    out, same = [], 0
    for index, path, group in rows:
        if group:
            out.append((index, "keep", "a random card: it rolls between the images it names"))
            continue
        try:
            game, ver = read_build(path, reader)
        except Exception:                               # noqa: BLE001
            out.append((index, "keep", "its image (%s) could not be read" % os.path.basename(path or "?")))
            continue
        if game != new_game:
            out.append((index, "keep", "another game (%s)" % _label(game, ver)))
            continue
        same += 1
        if _key(ver) >= _key(new_ver):
            out.append((index, "keep", "already %s" % _label(game, ver)))
            continue
        project = project_of(path)
        if project and os.path.isdir(project):
            out.append((index, "project", project))
        elif project:
            out.append((index, "keep", "a build of %s whose project folder (%s) is gone"
                        % (_label(game, ver), project)))
        else:
            stock = _stock_status(path)
            if stock == "official":
                out.append((index, "stock", ""))
            elif stock in ("", "unknown"):
                # the stock records cover current releases only, and an update starts from an older one: an
                # image the app did not build and cannot check is taken as Stern's, and the question says so
                out.append((index, "stock", "unchecked"))
            else:
                out.append((index, "keep", "a build of %s made elsewhere: the app has no project of it to carry"
                            % _label(game, ver)))
    if not same:
        raise UpdateRefused("No image on this card is %s's game: pick the new card image of one of its games."
                            % new_label)
    return new_label, out


def _stock_status(path):
    """The stock check's word for *path*: "official" (Stern's own release, byte for byte), "modified" (a release
    with files changed), "unknown" (a release the app has no record of - every older build) or ""."""
    try:
        from ..plugins.stern import stock_prints
        got = stock_prints.check_card(path)
        return (got or {}).get("status") or ""
    except Exception:                                   # noqa: BLE001
        return ""


def workspace_for(project, new_label):
    """Where an update's extract of the new build goes: beside *project*, named for it and the new build, so two
    projects in one folder never share one."""
    parent = os.path.dirname(os.path.abspath(project))
    return os.path.join(parent, "%s (%s)" % (os.path.basename(os.path.normpath(project)), new_label))
