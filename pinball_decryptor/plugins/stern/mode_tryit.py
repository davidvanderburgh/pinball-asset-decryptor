"""TRY IT: a project's modes in the emulator, with no card built (item 127), its set built by
WRITE'S OWN CODE (item 149: :func:`.mode_write.build_tryit_set`, i.e. ``engine.write_overrides``).

What a run needs, and where each part goes:

* the modes' own SCREENS and CLIPS are game files - the HUD scene with the screens added,
  the video bank with the clips added, and each clip's file - so they go in an OVERRIDE
  SET, the same kind the Emulate tab builds for a person's edits
  (``engine.write_overrides``): a folder that mirrors the games partition
  (``<title>/assets/...``), bound over the card inside the guest by ``run_game.sh``. A
  clip is a file the card never had, so the set also lists those in ``overrides.new``;
  ``run_game.sh`` overlays their directories rather than binding them, and publishes the
  set to the video host (``dump/vidoverride``).
* the mode OBJECT (the pinned runtime, :mod:`.mode_runtime`), the game's PORT and the
  generated mode FILES are not game files: the rig preloads the object with
  ``PAD_MODE_SO`` and the runtime reads the port and mode files from ``/dump``. They go in
  a folder BESIDE the set (never inside it: ``run_game.sh`` binds every file in a set).

ONE BUILDER. What a person tries must be what Write puts on the card, so the set is the
Emulate tab's override set for the project, built by the same ``_compute_patches`` a card
build runs: the screens and clips from the STOCK scenes of the card being booted (only the
scenes the title can use), the port whose sites match that card's game program, the
manifest composed with the modes in it, a mode's own sounds in a grown ``image.bin`` with
the count patch and the validator bypass in the game program, and the modes matched to the
project's card (item 148). The set carries the project's other edits too, as the card
would. A set already there is patched, not rebuilt (``write_overrides``' own update path);
a set with a sound of a mode's own takes about a minute, most of it the sound bank.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

from . import mode_assets as MA
from . import mode_project as MP
from . import mode_runtime as MR

#: The set's list of files a stock card lacks, one game-partition path per line.
NEW_LIST = "overrides.new"
#: What the guest preloads, in its /lib.
GUEST_OBJECT = "/lib/pad_mode.so"
OBJECT_NAME = "pad_mode.so"
PORT_NAME = "game.port"


class TryItError(ValueError):
    """Try it cannot go ahead; the message is a sentence for the person."""


# ---- where -------------------------------------------------------------------------
def tryit_dir():
    """The host-side work folder: in the temp dir under a ``spike2_`` name, like the
    Emulate tab's own set, so the app's scratch clean-up knows it."""
    return os.path.join(tempfile.gettempdir(), "spike2_mode_tryit")


def set_dir(base=None):
    return os.path.join(base or tryit_dir(), "set")


def stage_dir(base=None):
    """The object, the port and the mode files: BESIDE the set, never in it - where
    ``engine.write_overrides`` writes a set's modes payload (``<set>-modes``)."""
    return set_dir(base) + "-modes"


def _wsl_path(path):
    p = (path or "").replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def try_env(set_path=None):
    """What a Try it run adds to the Emulate tab's launch. Pure: no WSL, no files."""
    return ["PAD_OVERRIDE_DIR=%s" % _wsl_path(set_path or set_dir()),
            "PAD_MODE_SO=%s" % GUEST_OBJECT]


def run_env(ts):
    """What a run of the BUILT set ``ts`` (a :class:`TrySet`) adds to the Emulate tab's
    launch. Pure: no WSL, no files.

    ``PAD_OVERRIDE_DIR`` only when the set holds game files. Modes whose Screen is unticked
    and whose Clip is none build no files at all, so their set is just its manifest and
    ``overrides.new``; ``run_game.sh`` refuses a set that binds nothing ("nothing in this
    set belongs to the title being booted", exit 1), and the game would never start. Such
    a run needs only the object: the mode files and the port reach the guest through
    ``modes/tryit.sh install``, not through the set.

    Only a file of the TITLE counts (item 149). Write's set always carries the rebuilt
    ``spk/index/<title>.sidx``, which sits BESIDE the title: a card run mounts only the
    title's directory, so ``run_game.sh`` skips that file, and a set of nothing else (Jaws,
    whose game program has no validator to bypass) is the same refusal."""
    if not title_files(ts):
        return ["PAD_MODE_SO=%s" % GUEST_OBJECT]
    return try_env(ts.set_dir)


def title_files(ts):
    """The files of ``ts`` a card run can bind: under the title's own directory, never
    beside it (``spk/index``)."""
    game = getattr(ts, "game_dir", "") or ""
    out = []
    for rel in list(getattr(ts, "files", None) or []):
        top = str(rel).replace("\\", "/").lstrip("/").split("/", 1)[0]
        if top != "spk" and (not game or top == game):
            out.append(rel)
    return out


# ---- the title --------------------------------------------------------------------
def profile_version(prof):
    """``1.15`` for ``godzilla_pro_1_15``: a profile's key is its game dir and version."""
    key, game = prof.key, prof.game_dir
    if key.startswith(game + "_"):
        return key[len(game) + 1:].replace("_", ".")
    return ""


def card_title(card):
    """``(game_dir, version, partition index)`` of a card image, read from its own
    ``/spk/index/<title>-<version>.sidx`` name the way the other two title readers do
    (:func:`.mode_project.card_from_name`, as ``probe_card_title`` and the engine's
    ``card_title_index`` read it). A card's index survives a renamed file, and it names
    the title whatever else sits beside it: a multi-boot card keeps ``img1``/``img2``
    next to the title's directory, and the old one-directory rule made that "an unknown
    title". Only when no ``.sidx`` parses does the one title directory decide."""
    from .explorer import CardImage
    from .info import version_from_filename
    try:
        img = CardImage(card)
    except OSError as e:
        raise TryItError("The card image could not be opened: %s" % e) from None
    with img:
        parts = sorted((p for p in img.partitions() if p.browsable), key=lambda p: -p.size)
        for p in parts:
            try:
                names = [e.name for e in img.list_dir(p.index, "/spk/index")
                         if not e.is_dir and e.name.lower().endswith(".sidx")]
                dirs = [e.name for e in img.list_dir(p.index, "/")
                        if e.is_dir and e.name not in ("spk", "lost+found")]
            except (OSError, ValueError):
                continue
            if not dirs:
                continue
            for name in sorted(names):
                game, version = MP.card_from_name(name)
                if game:
                    return game, version, p.index
            version = version_from_filename(names[0])[0] if names else None
            return dirs[0] if len(dirs) == 1 else "", version or "", p.index
    raise TryItError("%s is not a Spike 2 card image this can read (no games partition)."
                     % os.path.basename(card))


def check_title(prof, game_dir, version):
    """Refuse, in a sentence, a card that is not the build the modes were made for."""
    want = profile_version(prof)
    if game_dir != prof.game_dir or (want and MP.version_key(version) != MP.version_key(want)):
        raise TryItError(
            "These modes are made for %s, and the card in the Emulate tab is %s %s. Pick a "
            "%s card there." % (prof.label, game_dir or "an unknown title", version or "",
                                prof.label))


# ---- the modes ---------------------------------------------------------------------
def code_mode_sources(project):
    """``[(slug, path)]`` of the project's CODE modes: ``modes/<slug>/<slug>.c``."""
    out = []
    try:
        names = sorted(os.listdir(MP.modes_dir(project)))
    except OSError:
        return out
    for slug in names:
        path = os.path.join(MP.mode_folder(project, slug), slug + ".c")
        if os.path.isfile(path):
            out.append((slug, path))
    return out


@dataclass
class TrySet:
    """A built (or reused) Try it set."""
    set_dir: str
    stage_dir: str
    game_dir: str
    version: str
    reused: bool = False
    files: list = field(default_factory=list)       # game-partition paths in the set
    new_files: list = field(default_factory=list)   # of those, the ones a stock card lacks
    mode_files: list = field(default_factory=list)  # mode.cfg, mode1.cfg ... in slot order
    slots: list = field(default_factory=list)       # [(slot, slug, name)]
    port: str = ""
    #: slug -> the ModeSpec as this run has it: matched to the project's card (item 148)
    specs: dict = field(default_factory=dict)
    #: the end sound Write's set carries, ``{"name", "request", "idx"}``, or None (item 149)
    end_sound: dict = None
    #: slug -> ``{"requests": {key: carrier}, "ms": {key: length}}``: the start / shot sounds
    #: and music Write's set carries for that mode (item 150 through item 149)
    own_sounds: dict = field(default_factory=dict)
    #: the CODE modes Write's set carries with their own assets, and whether the stage's object
    #: was compiled from them by Write (then Try it does not compile them again)
    codes: list = field(default_factory=list)
    code_object: bool = False


def build_set(project, card, base=None, ffmpeg=None, log=None, progress=None, cancel=None,
              sound_ok=None):
    """Build Try it's set for ``project`` against ``card`` (the image to BOOT; the builder
    prepares the set from the card the project was measured on, PAD-161) - WRITE'S OWN CODE
    (:func:`.mode_write.build_tryit_set`) - with the object, port and mode files beside it in
    :func:`stage_dir`. Returns a :class:`TrySet`. ``ffmpeg`` is found by the build itself
    and kept for callers. ``progress(done, total, text)`` and ``cancel()`` reach the engine's
    own checkpoints, so the tab's bar moves and its Cancel is honoured mid-build; ``sound_ok``
    (None = the environment gate, as a Write reads it; False = a mode's own sounds left out
    of this build) is handed on as it is: None reaches the engine, which reads the gate.
    Raises :class:`TryItError` with a sentence for the person."""
    from . import mode_write as MW
    log = log or (lambda msg: None)
    if not MW.preview_on():
        raise TryItError("Try it needs the mode maker, a preview feature that is not "
                         "switched on in this copy of the app (Settings > Preview features).")
    if not project or not os.path.isdir(project):
        raise TryItError(MP.NO_PROJECT_HELP)
    found, broken = MP.list_modes(project)
    if broken:
        raise TryItError("These modes could not be read: %s"
                         % ", ".join("%s (%s)" % b for b in broken))
    code = code_modes_with_assets(project)
    if not found and not code:
        raise TryItError("There are no modes in this project to try.")
    found = modes_for_the_card(project, found)
    titles = {spec.title for _slug, spec in found}
    if len(titles) > 1:
        raise TryItError("Every mode in a project must be for the same game.")
    try:
        if titles:
            prof = MP.profile(titles.pop())
        else:
            from . import code_modes as CM
            prof = CM.profile_for(project, code)
            if prof is None:
                raise TryItError(CM.NO_TITLE)
    except MP.ModeProjectError as e:
        raise TryItError(str(e)) from None
    if not card or not os.path.isfile(card):
        raise TryItError("Pick a %s card image in the Emulate tab first." % prof.label)
    game_dir, version, _part = card_title(card)
    check_title(prof, game_dir, version)
    log("building the set with Write's own code (engine.write_overrides)")

    def say(msg, level="info"):
        log(msg)
    try:
        ws = MW.build_tryit_set(project, card, base or tryit_dir(), log=say, progress=progress,
                                cancel=cancel, sound_ok=sound_ok)
    except MW.ModeWriteError as e:
        raise TryItError(str(e)) from None
    if ws is None:
        raise TryItError("Try it was cancelled before its set was built.")
    return TrySet(set_dir=ws.set_dir, stage_dir=ws.stage_dir, game_dir=ws.game_dir or game_dir,
                  version=version or ws.version, reused=ws.reused, files=list(ws.files),
                  new_files=list(ws.new_files), mode_files=list(ws.mode_files),
                  slots=list(ws.slots), port=ws.port, specs=dict(found),
                  end_sound=getattr(ws, "end_sound", None),
                  own_sounds=dict(getattr(ws, "own_sounds", None) or {}),
                  codes=list(getattr(ws, "codes", None) or ()),
                  code_object=bool(getattr(ws, "code_object", False)))


def code_modes_with_assets(project):
    """``[(slug, CodeAssets)]`` of the project's CODE modes that carry assets of their own (a
    clip, a screen, music or calls, :mod:`.code_modes`): those go through Write's set like a form
    mode. A code mode with none is only compiled in (:func:`code_mode_sources`). Raises
    :class:`TryItError` naming an assets.json that does not load."""
    from . import code_modes as CM
    try:
        return [(s, c) for s, c in CM.list_code(project) if c.has_assets()]
    except CM.CodeModeError as e:
        raise TryItError(str(e)) from None


def slot_of(project, slug):
    """The slot a mode's file takes (its place in the project's slug order), or None."""
    found, _broken = MP.list_modes(project)
    for slot, (s, _spec) in enumerate(found):
        if s == slug:
            return slot
    return None


def _c_ident(slug):
    """The C name a mode's folder gives its struct: a C name cannot start with a digit."""
    return slug if slug[:1].isalpha() else "m_" + slug


def _c_title(name, slug):
    """A mode's name as a C string literal can hold it (no quote or backslash inside)."""
    return (name or slug).replace("\\", "").replace('"', "'")


def code_mode_text(template, name, slug):
    """``sdk/template_mode.c`` made into a code mode of its own: its name, its folder's
    screen names (``PadMode_<slug>_Screen``, the names a build gives a mode folder), its
    own test triggers (``/dump/<slug>.start``, ``<slug>.stop``) and its own struct name.
    Everything else is the template, comments and all, to change from there."""
    ident = _c_ident(slug)
    title = _c_title(name, slug)
    out = template.replace('#define MODE_NAME        "TARGET RUSH"',
                           '#define MODE_NAME        "%s"' % title)
    out = out.replace("PadMode_template_", "PadMode_%s_" % slug)
    out = out.replace('this template\'s folder is "template"', 'this mode\'s folder is "%s"' % slug)
    out = out.replace('"template.start"', '"%s.start"' % slug)
    out = out.replace('"template.stop"', '"%s.stop"' % slug)
    out = out.replace("/dump/template.start", "/dump/%s.start" % slug)
    out = out.replace("target_rush", "%s_mode" % ident)
    out = out.replace("/* template_mode.c - a complete game mode to copy and change. (item 134)",
                      "/* %s.c - %s, a code mode made from template_mode.c (item 134)" % (slug, title))
    return out


def _free_slug(project, base):
    """``base``, or the first of ``base_2``, ``base_3`` ... whose folder is not there: the
    numbering :func:`.mode_project.new_mode` and ``duplicate_mode`` give a form mode."""
    slug, n = base, 2
    while os.path.exists(MP.mode_folder(project, slug)):
        slug, n = "%s_%d" % (base, n), n + 1
    return slug


def _write_default_assets(project, slug, name):
    """A fresh code mode's ``assets.json``: its name and nothing of its own (no screen, clip,
    music or call), so ``has_assets()`` stays False and Try it keeps the compile-only path
    for it. Read back at once, because a file this cannot load would stop every later list
    of the project's code modes."""
    from . import code_modes as CM
    path = CM.save(project, slug, CM.CodeAssets(name=name, screen=False))
    try:
        CM.load(project, slug)
    except (OSError, ValueError) as e:
        raise TryItError("%s was written but does not load: %s" % (path, e)) from None
    return path


def new_code_mode(project, name):
    """Copy ``sdk/template_mode.c`` into ``modes/<slug>/<slug>.c`` for a new code mode, with
    a default ``assets.json`` beside it (the mode's name, nothing of its own yet).
    Returns ``(slug, path)``. Never overwrites a folder that exists."""
    if not project or not os.path.isdir(project):
        raise TryItError(MP.NO_PROJECT_HELP)
    slug = _free_slug(project, MP.slugify(name))
    with open(os.path.join(MR.sdk_dir(), "template_mode.c"), "r", encoding="utf-8") as f:
        template = f.read()
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder)
    path = os.path.join(folder, slug + ".c")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code_mode_text(template, name, slug))
    _write_default_assets(project, slug, _c_title(name, slug))
    return slug, path


def _source_name(path):
    """The ``MODE_NAME`` define of a code mode's C file, or ``""``."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            m = re.search(r'#define\s+MODE_NAME\s+"([^"]*)"', f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def list_all(project):
    """``[(slug, kind, name)]`` of every mode in the project: the form modes first, in the
    order :func:`.mode_project.list_modes` gives them (``kind`` ``"form"``, the spec's
    name), then the code modes in slug order (``kind`` ``"code"``, named by their
    ``assets.json``, else by the ``MODE_NAME`` define in the C file, else by the folder in
    capitals, as :func:`.code_modes.load` names one). A
    folder whose ``mode.json`` does not load is skipped, as ``list_modes`` skips it; a code
    mode whose ``assets.json`` does not load is still listed, named from its C file, so a
    person can see it and take it out."""
    from . import code_modes as CM
    out = []
    if not project:
        return out
    found, _broken = MP.list_modes(project)
    for slug, spec in found:
        out.append((slug, "form", spec.name))
    for slug in CM.code_slugs(project):
        try:
            name = CM.load(project, slug).name
        except (OSError, ValueError):
            name = ""
        out.append((slug, "code", name or _source_name(CM.source_path(project, slug)) or slug))
    return out


def _rename_code_text(text, slug, new_slug, name=None):
    """A code mode's C text moved to another folder: every name the folder gives it
    (:func:`code_mode_text`'s substitutions, and the examples' ``FOLDER`` define and
    struct name) now says ``new_slug``, and, when ``name`` is given, ``MODE_NAME`` says
    that. The rest of the text is untouched."""
    ident, new_ident = _c_ident(slug), _c_ident(new_slug)
    out = text.replace("PadMode_%s_" % slug, "PadMode_%s_" % new_slug)
    for suffix in (".start", ".stop", ".shot"):
        out = out.replace('"%s%s"' % (slug, suffix), '"%s%s"' % (new_slug, suffix))
    out = out.replace("/dump/%s." % slug, "/dump/%s." % new_slug)
    out = out.replace('this mode\'s folder is "%s"' % slug, 'this mode\'s folder is "%s"' % new_slug)
    out = re.sub(r'(#define\s+FOLDER\s+)"%s"' % re.escape(slug), r'\g<1>"%s"' % new_slug, out)
    out = re.sub(r"\b%s_mode\b" % re.escape(ident), "%s_mode" % new_ident, out)
    out = re.sub(r"(struct pm_mode\s+)%s\b" % re.escape(ident), r"\g<1>%s" % new_ident, out)
    out = re.sub(r"(PM_REGISTER\(\s*)%s\b" % re.escape(ident), r"\g<1>%s" % new_ident, out)
    head = "/* %s.c - " % slug
    if out.startswith(head):
        out = "/* %s.c - " % new_slug + out[len(head):]
    if name is not None:
        out = re.sub(r'(#define\s+MODE_NAME\s+)"[^"]*"', lambda m: '%s"%s"' % (m.group(1), name),
                     out, count=1)
    return out


def duplicate_code_mode(project, slug, name=None):
    """Copy the code mode ``slug``'s whole folder (its C file, headers, picture, clip and
    sounds) to a free slug, the way ``duplicate_mode`` copies a form mode: the copy is
    named ``name``, or "<its name> COPY", and its C file is rewritten as ``<new_slug>.c``
    with the new folder's names and triggers, so the two never answer to one trigger.
    Returns ``(new_slug, path)``. Never overwrites a folder that exists."""
    from . import code_modes as CM
    if not project or not os.path.isdir(project):
        raise TryItError(MP.NO_PROJECT_HELP)
    src = CM.source_path(project, slug)
    if not os.path.isfile(src):
        raise TryItError("There is no code mode called %s in this project." % slug)
    try:
        old_name = CM.load(project, slug).name
    except (OSError, ValueError):
        old_name = _source_name(src) or slug
    new_name = _c_title(name, slug) if name else old_name + " COPY"
    new_slug = _free_slug(project, MP.slugify(new_name))
    folder = MP.mode_folder(project, new_slug)
    shutil.copytree(MP.mode_folder(project, slug), folder)
    with open(os.path.join(folder, slug + ".c"), "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    path = os.path.join(folder, new_slug + ".c")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_rename_code_text(text, slug, new_slug, name=new_name))
    os.remove(os.path.join(folder, slug + ".c"))
    if os.path.isfile(os.path.join(folder, CM.ASSETS_FILE)):
        try:
            spec = CM.load(project, new_slug)
        except (OSError, ValueError) as e:
            raise TryItError("%s was copied, but its %s does not load: %s"
                             % (old_name, CM.ASSETS_FILE, e)) from None
        spec.name = new_name
        CM.save(project, new_slug, spec)
    return new_slug, path


def delete_code_mode(project, slug):
    """Remove the code mode ``slug``'s folder, and only that: the folder must sit in the
    project's ``modes/`` and hold ``<slug>.c``, and a folder that also holds a mode file is
    a form mode, which ``delete_mode`` owns."""
    if not project or not os.path.isdir(project):
        raise TryItError(MP.NO_PROJECT_HELP)
    root = os.path.abspath(MP.modes_dir(project))
    folder = os.path.abspath(MP.mode_folder(project, slug or ""))
    if not slug or os.path.dirname(folder) != root or os.path.basename(folder) != slug:
        raise TryItError("%r is not a mode folder of this project." % slug)
    if not os.path.isfile(os.path.join(folder, slug + ".c")):
        raise TryItError("There is no code mode called %s in this project." % slug)
    if os.path.isfile(os.path.join(folder, MP.MODE_FILE)):
        raise TryItError("%s is a mode made in the tab, not a code mode." % slug)
    shutil.rmtree(folder)


def code_trigger_name(slug):
    """Whether ``slug`` can name a code mode's test triggers: ``tryit.sh`` writes
    ``/dump/<slug>.start`` and ``.stop`` only for a plain ``[a-z0-9_]`` name (what New
    code mode makes); a folder made by hand with other characters gets no trigger."""
    return bool(re.fullmatch(r"[a-z0-9_]+", slug or ""))


def unreachable_code_modes(codes):
    """The code modes in ``codes`` (slugs, or ``(slug, ...)`` tuples as
    :func:`code_mode_sources` gives them) that End mode cannot reach, by slug: those whose
    folder name is not a trigger name (:func:`code_trigger_name`)."""
    out = []
    for c in codes or ():
        slug = c[0] if isinstance(c, (tuple, list)) else c
        if not code_trigger_name(slug):
            out.append(slug)
    return out


def asset_signature(spec):
    """The fields of a mode that change its BUILT assets (the screen and the clip). An
    edit to one of these applies at the next Try it; everything else reloads live.
    Item 141's second clip and item 142's film cuts (a new span is a new clip or picture)
    are built assets too, and so is the NAME wherever a build draws it: on the generated
    panel of a screen with no title or picture of its own, and on a title-card clip with no
    title of its own (:mod:`.mode_assets`). The award is not: the runtime writes the
    screen's words ("1,000,000 A SHOT") from the mode file each time the mode starts."""
    got = {k: getattr(spec, k, None) for k in (
        "screen", "screen_title", "screen_art", "panel_color", "title_color",
        "clip", "clip_title", "clip_file", "clip_seconds", "clip_when", "title",
        "clip_both", "clip_source", "clip_from", "clip_length", "clip_crop",
        "art_source", "art_from", "art_crop")}
    both = getattr(spec, "clip_both", None)
    drawn = ((getattr(spec, "screen", False) and not getattr(spec, "screen_art", "")
              and not getattr(spec, "screen_title", ""))
             or (getattr(spec, "clip", "") == "title" and not getattr(spec, "clip_title", ""))
             or (getattr(spec, "clip", "none") != "none" and isinstance(both, dict)
                 and both.get("clip") == "title" and not both.get("title")))
    got["name_drawn"] = getattr(spec, "name", None) if drawn else None
    return json.dumps(got, sort_keys=True)


# ---- the project's card decides the title (item 148) --------------------------------
def modes_for_the_card(project, found):
    """``found`` (``[(slug, ModeSpec)]``) as the PROJECT'S CARD runs them, exactly as a
    build makes them (:func:`mode_assets._modes_for_the_card`): each mode's shots matched
    by name to the port of the card the project was made from. A mode keeps the title it
    was made for in its ``mode.json`` (every mode made before item 148 says Godzilla Pro
    1.15), so without this a project made from a Premium/LE 1.16 card refused its own card.
    A project that names no card keeps each mode's own title. It may OPEN the project's
    card image (a renamed card's index): never on the UI thread."""
    try:
        return MA._modes_for_the_card(project, found)
    except MA.ModeAssetError as e:
        raise TryItError(str(e)) from None


def project_title(project):
    """The profile ``project``'s modes run on, without opening any image: its card's port
    when it names a card that has one (item 148), else the title its first mode was made
    for, else None (there is no default game). For words only (which card to pick)."""
    try:
        card, prof = MP.project_profile(project)
    except (OSError, ValueError):
        card, prof = None, None
    if prof is not None:
        return prof
    found = MP.list_modes(project)[0] if project else []
    for _slug, spec in found:
        try:
            return MP.profile(spec.title)
        except MP.ModeProjectError:
            break
    return None


#: A mode's OWN sounds (items 131 and 150): WAVs a Write puts in the card's sound bank.
#: Try it's set is Write's, so a run carries the ones a card would (:func:`sounds_left_out`).
OWN_SOUND_FIELDS = ("end_sound", "sound_start", "sound_shot", "sound_shot_every", "music")


def own_sound_modes(specs):
    """The names of the modes in ``specs`` (ModeSpecs) that carry a sound of their own."""
    return [s.name for s in specs
            if any(getattr(s, k, "") for k in OWN_SOUND_FIELDS if k != "sound_shot_every")]


def sound_signature(spec):
    """The fields of a mode that name its own sounds: an edit to one reaches no Try it run."""
    return json.dumps({k: getattr(spec, k, None) for k in OWN_SOUND_FIELDS}, sort_keys=True)


def sounds_left_out(ts):
    """The names of the modes in ``ts`` (a :class:`TrySet`) with a sound of their own that
    its set does NOT carry - the ones a card Written from the project would not carry
    either (a second mode's end sound, a title with no measured carriers, a closed gate;
    the build log says why). The run plays the game's own calls for those."""
    out = []
    end = (ts.end_sound or {}).get("name")
    for slug, spec in (ts.specs or {}).items():
        own = ((ts.own_sounds or {}).get(slug) or {}).get("requests") or {}
        missing = False
        if getattr(spec, "end_sound", "") and spec.name != end:
            missing = True
        for key in ("sound_start", "sound_shot", "music"):
            if getattr(spec, key, "") and key not in own:
                missing = True
        if missing:
            out.append(spec.name)
    return out
