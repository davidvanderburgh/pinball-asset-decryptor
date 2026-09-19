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
a set with a sound of a mode's own takes about three minutes, most of it the sound bank.
"""
from __future__ import annotations

import json
import os
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


def _version_key(version):
    parts = [p for p in str(version or "").replace("_", ".").split(".") if p]
    if len(parts) == 3 and parts[2].strip("0") == "":
        parts = parts[:2]
    return ".".join(parts)


def card_title(card):
    """``(game_dir, version, partition index)`` of a card image, from its own
    ``/spk/index/<title>-<version>.sidx`` and its one title directory."""
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
            version = version_from_filename(names[0])[0] if names else None
            return dirs[0] if len(dirs) == 1 else "", version or "", p.index
    raise TryItError("%s is not a Spike 2 card image this can read (no games partition)."
                     % os.path.basename(card))


def check_title(prof, game_dir, version):
    """Refuse, in a sentence, a card that is not the build the modes were made for."""
    want = profile_version(prof)
    if game_dir != prof.game_dir or (want and _version_key(version) != _version_key(want)):
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


def build_set(project, card, base=None, ffmpeg=None, log=None):
    """Build Try it's set for ``project`` against ``card`` - WRITE'S OWN CODE
    (:func:`.mode_write.build_tryit_set`) - with the object, port and mode files beside it in
    :func:`stage_dir`. Returns a :class:`TrySet`. ``ffmpeg`` is found by the build itself
    and kept for callers. Raises :class:`TryItError` with a sentence for the person."""
    from . import mode_write as MW
    log = log or (lambda msg: None)
    if not MW.preview_on():
        raise TryItError("Try it needs the mode maker, a preview feature that is not "
                         "switched on in this copy of the app (Settings > Preview features).")
    if not project or not os.path.isdir(project):
        raise TryItError("Open or extract a card project first: modes live in it.")
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
        ws = MW.build_tryit_set(project, card, base or tryit_dir(), log=say)
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


def code_mode_text(template, name, slug):
    """``sdk/template_mode.c`` made into a code mode of its own: its name, its folder's
    screen names (``PadMode_<slug>_Screen``, the names a build gives a mode folder), its
    own test triggers (``/dump/<slug>.start``, ``<slug>.stop``) and its own struct name.
    Everything else is the template, comments and all, to change from there."""
    ident = slug if slug[:1].isalpha() else "m_" + slug
    title = (name or slug).replace("\\", "").replace('"', "'")
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


def new_code_mode(project, name):
    """Copy ``sdk/template_mode.c`` into ``modes/<slug>/<slug>.c`` for a new code mode.
    Returns ``(slug, path)``. Never overwrites a folder that exists."""
    if not project or not os.path.isdir(project):
        raise TryItError("Open or extract a card project first: modes live in it.")
    base = MP.slugify(name)
    slug, n = base, 2
    while os.path.exists(MP.mode_folder(project, slug)):
        slug, n = "%s_%d" % (base, n), n + 1
    with open(os.path.join(MR.sdk_dir(), "template_mode.c"), "r", encoding="utf-8") as f:
        template = f.read()
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder)
    path = os.path.join(folder, slug + ".c")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code_mode_text(template, name, slug))
    return slug, path


def asset_signature(spec):
    """The fields of a mode that change its BUILT assets (the screen and the clip). An
    edit to one of these applies at the next Try it; everything else reloads live.
    Item 141's second clip and item 142's film cuts (a new span is a new clip or picture)
    are built assets too."""
    return json.dumps({k: getattr(spec, k, None) for k in (
        "screen", "screen_title", "screen_art", "panel_color", "title_color",
        "clip", "clip_title", "clip_file", "clip_seconds", "clip_when", "title",
        "clip_both", "clip_source", "clip_from", "clip_length", "clip_crop",
        "art_source", "art_from", "art_crop")},
        sort_keys=True)


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
    for, else Godzilla Pro 1.15. For words only (which card to pick)."""
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
    return MP.GODZILLA_PRO_1_15


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
