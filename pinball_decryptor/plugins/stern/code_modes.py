"""A CODE mode's OWN clip, screen, music and calls, carried through the project like a form mode's.

A mode written in C lives in the card project as ``modes/<slug>/<slug>.c`` (the Modes tab's New
code mode, or one of its Examples). What it plays of its own sits beside it, named in
``modes/<slug>/assets.json``::

    {
      "format": 1,
      "name": "KING GHIDORAH",
      "seconds": 85,                 the longest the mode can run: its music bed outlasts it
      "screen": true,                its own screen on the HUD (PadMode_<slug>_Screen)
      "screen_art": "screen.png",    the picture ("" = a generated panel with the name)
      "words_on_art": true,          its progress words sit on the picture's bottom band
      "clip": "clip.mp4",            its start clip ("" = none)
      "music": "music.wav",          its own music bed ("" = none)
      "calls": {"sever": "sever.wav", "spike": {"wav": "spike.wav", "priority": 3}},
      "film": {...}                  where each was cut from (an Example's recipe), optional
    }

The CUES are the mode's own words (``pa_call(&own, "sever")`` in its C); the project maps each
to a WAV. Write (and Try it, which is Write's own code) then does for a code mode what it does
for a form mode: the screen into the HUD scene, the clip into the video bank, the music on a
bed and each call on a carrier of its own (:mod:`.mode_sounds`), and the mode compiled into the
object the card carries with ``mode_file.c``. The carriers it chose go on the card as
``<slug>.assets`` beside ``mode.so`` (:func:`runtime_text`), which the mode reads through
``tools/spike2_emu/modes/sdk/pad_mode_assets.h``.

EXAMPLES. The Modes tab offers the SDK's five intricate example modes (:data:`EXAMPLES`), each
with its code and an asset RECIPE: which film each clip, picture, music loop and call is cut
from and where. Nothing of a film is in the app, so an example's assets are cut from the
person's own copy of the films with the app's film cutter (:mod:`.film_cut`) when those films
are found (:func:`cut_example`); without them the mode is added with its code alone and plays
the game's own sounds, and the tab says which films it looked for.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field, fields

from . import mode_project as MP

ASSETS_FILE = "assets.json"
FORMAT = 1
#: what the build puts beside mode.so for each code mode
RUNTIME_SUFFIX = ".assets"
#: pad_mode_assets.h reads at most this many calls
MAX_CALLS = 16
CUE_RE = re.compile(r"^[a-z][a-z0-9_]{0,14}$")
SECONDS_MAX = 600


class CodeModeError(ValueError):
    """A code mode's assets that cannot be used as asked; the message is a sentence."""


@dataclass
class CodeAssets:
    name: str = ""
    seconds: int = 60
    screen: bool = True
    screen_art: str = ""
    words_on_art: bool = False
    panel_color: str = "#146e28"
    title_color: str = "#ffe600"
    clip: str = ""
    music: str = ""
    calls: dict = field(default_factory=dict)
    film: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def to_json(self):
        out = {"format": FORMAT}
        for f in fields(self):
            if f.name != "extra":
                out[f.name] = getattr(self, f.name)
        for k, v in self.extra.items():
            out.setdefault(k, v)
        return out

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            raise CodeModeError("a code mode's assets.json holds a JSON object")
        if int(data.get("format", 1)) > FORMAT:
            raise CodeModeError("these assets were saved by a newer version of the app")
        known = {f.name for f in fields(cls)} - {"extra"}
        spec = cls()
        for k, v in data.items():
            if k == "format":
                continue
            if k in known:
                setattr(spec, k, v)
            else:
                spec.extra[k] = v
        return spec

    def call_list(self):
        """``[(cue, wav, priority)]`` in the order the file names them."""
        out = []
        for cue, v in (self.calls or {}).items():
            if isinstance(v, dict):
                out.append((cue, str(v.get("wav") or ""), int(v.get("priority") or 4)))
            else:
                out.append((cue, str(v or ""), 4))
        return out

    def has_assets(self):
        return bool(self.screen or self.clip or self.music or self.calls)


# ---- the project -------------------------------------------------------------------------------
def source_path(project, slug):
    return os.path.join(MP.mode_folder(project, slug), slug + ".c")


def code_slugs(project):
    """``[slug]`` of the project's CODE modes: ``modes/<slug>/<slug>.c`` with no mode file (a
    folder with both is a form mode that keeps a C file of its own)."""
    root = MP.modes_dir(project) if project else ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [s for s in names if os.path.isfile(os.path.join(root, s, s + ".c"))
            and not os.path.isfile(os.path.join(root, s, MP.MODE_FILE))]


def _name_from_source(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            m = re.search(r'#define\s+MODE_NAME\s+"([^"]+)"', f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def load(project, slug):
    """The code mode's :class:`CodeAssets`: its ``assets.json``, or - a code mode with none -
    no assets at all (no screen, clip, music or call), named after its C file's MODE_NAME."""
    path = os.path.join(MP.mode_folder(project, slug), ASSETS_FILE)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            spec = CodeAssets.from_json(json.load(f))
    else:
        spec = CodeAssets(screen=False)
    if not spec.name:
        spec.name = _name_from_source(source_path(project, slug)) or slug.upper()
    return spec


def save(project, slug, spec):
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, ASSETS_FILE)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(spec.to_json(), f, indent=2)
        f.write("\n")
    os.replace(path + ".tmp", path)
    return path


def list_code(project):
    """``[(slug, CodeAssets)]`` of the project's code modes, in slug order. Raises
    :class:`CodeModeError` naming a mode whose assets.json does not load."""
    out, broken = [], []
    for slug in code_slugs(project):
        try:
            out.append((slug, load(project, slug)))
        except (OSError, ValueError) as e:
            broken.append("%s (%s)" % (slug, e))
    if broken:
        raise CodeModeError("these code modes' assets could not be read: %s" % ", ".join(broken))
    return out


def validate(spec, folder=None):
    """Every reason these assets cannot be built, as sentences. Empty = fine."""
    out = []
    try:
        secs = int(spec.seconds)
    except (TypeError, ValueError):
        secs = -1
    if not 1 <= secs <= SECONDS_MAX:
        out.append("%s: seconds is the longest the mode runs, 1 to %d." % (spec.name, SECONDS_MAX))
    calls = spec.call_list() if isinstance(spec.calls, dict) else None
    if calls is None:
        out.append("%s: calls maps each cue to a WAV." % spec.name)
        calls = []
    if len(calls) > MAX_CALLS:
        out.append("%s: a code mode carries at most %d calls." % (spec.name, MAX_CALLS))
    for cue, wav, prio in calls:
        if not CUE_RE.match(cue):
            out.append("%s: the cue %r is 1 to 15 lower-case letters, digits or _." % (spec.name, cue))
        if not 1 <= prio <= 7:
            out.append("%s: the %s call's priority is 1 to 7." % (spec.name, cue))
        if not wav:
            out.append("%s: the %s call names no WAV." % (spec.name, cue))
    if folder is not None:
        named = [("the picture", spec.screen_art), ("the clip", spec.clip), ("the music", spec.music)]
        named += [("the %s call" % cue, wav) for cue, wav, _p in calls]
        for what, name in named:
            if name and not os.path.isfile(os.path.join(folder, name)):
                out.append("%s: %s file %s is not in the mode's folder." % (spec.name, what, name))
    return out


#: Why a code-mode-only project has no game to build for (:func:`profile_for` gave None).
NO_TITLE = ("This project names no card and no code mode names its game, so the app does not "
            "know which game the code modes are for. Extract the card into the project "
            "(Extract tab) first.")


def profile_for(project, code=()):
    """The title a code-mode-only project builds for: its card's port (item 148), else the title
    its first code mode names (``extra["title"]``), else None (:data:`NO_TITLE`): there is no
    default game."""
    try:
        _card, prof = MP.project_profile(project, probe=True)
    except (OSError, ValueError):
        prof = None
    if prof is not None:
        return prof
    for _slug, spec in code or ():
        key = (spec.extra or {}).get("title")
        if key:
            try:
                return MP.profile(key)
            except MP.ModeProjectError:
                break
    return None


# ---- the sounds, as Write carries them -----------------------------------------------------------
def call_key(cue):
    """The own-sound key a code mode's call rides under in the build (``mode_write``)."""
    return "call:%s" % cue


def cue_of(key):
    return key[5:] if str(key).startswith("call:") else None


def sound_wants(project, code):
    """``[{"slug", "name", "key", "wav", "music", "seconds", "priority"}]`` - every own sound the
    code modes ask for, music first then each call in the order its file names it."""
    out = []
    for slug, spec in code or ():
        folder = MP.mode_folder(project, slug)
        if spec.music:
            out.append({"slug": slug, "name": spec.name, "key": "music", "music": True,
                        "wav": os.path.join(folder, spec.music), "seconds": int(spec.seconds or 0)})
        for cue, wav, prio in spec.call_list():
            out.append({"slug": slug, "name": spec.name, "key": call_key(cue), "music": False,
                        "wav": os.path.join(folder, wav), "priority": prio})
    return out


def runtime_text(slug, spec, prof, own_sounds=(), screen=False, clip=False):
    """``<slug>.assets``, the file the mode reads (pad_mode_assets.h): its screen and clip as the
    build named them, and every own sound the build CARRIED (*own_sounds*: the engine's list,
    each with ``request``, ``ms`` and, for the music, ``sid``). A sound the build could not carry
    is left out, so the mode plays the game's own call there."""
    names = MP.asset_names(slug)
    lines = ["# GENERATED by the app's Write from modes/%s/%s - edit the mode there." % (slug, ASSETS_FILE),
             "name   %s" % spec.name.strip()]
    if screen:
        lines.append("screen %s %s" % (names["screen_node"], names["screen_text"]))
    if clip:
        lines.append("clip   start %s" % names["clip"])
    mine = [u for u in own_sounds or () if u.get("slug") == slug]
    prio = {cue: p for cue, _w, p in spec.call_list()}
    for u in mine:
        if u.get("key") == "music":
            lines.append("music  %d%s" % (int(u["request"]), " %d" % int(u["sid"]) if u.get("sid") else ""))
    for cue, _w, _p in spec.call_list():
        u = next((u for u in mine if u.get("key") == call_key(cue)), None)
        if u is None:
            continue
        lines.append("call   %s %d %d %d" % (cue, int(u["request"]), int(u.get("ms") or 0), prio.get(cue, 4)))
    return "\n".join(lines) + "\n"


def describe(slug, spec, carried=None, prof=None):
    """The Write log's and change scan's words for one code mode."""
    parts = ["its code (%s.c), built into the card's mode.so" % slug]
    can_screen = prof is None or prof.can("screen")
    can_clip = prof is None or prof.can("clip")
    if spec.screen and can_screen:
        parts.append("its own screen%s" % (" with its picture %s" % spec.screen_art if spec.screen_art else ""))
    if spec.clip and can_clip:
        parts.append("its own start clip %s (a new file)" % spec.clip)
    got = {u["key"]: u for u in (carried or ()) if u.get("slug") == slug}
    if spec.music:
        u = got.get("music")
        if carried is None:
            parts.append("its own music %s" % spec.music)
        elif u:
            parts.append("its own music %s (request %d, its own bed: sound id %s)"
                         % (spec.music, u["request"], u.get("sid", "-")))
        else:
            parts.append("not its own music (this card cannot carry it; the log says why)")
    calls = spec.call_list()
    if calls:
        if carried is None:
            parts.append("%d call(s) of its own (%s)" % (len(calls), ", ".join(c for c, _w, _p in calls)))
        else:
            have = [c for c, _w, _p in calls if call_key(c) in got]
            miss = [c for c, _w, _p in calls if call_key(c) not in got]
            if have:
                parts.append("%d call(s) of its own (%s)" % (len(have), ", ".join(
                    "%s on request %d" % (c, got[call_key(c)]["request"]) for c in have)))
            if miss:
                parts.append("not its %s call(s) (this card cannot carry them; the log says why)" % ", ".join(miss))
    parts.append("%s%s on the system partition" % (slug, RUNTIME_SUFFIX))
    return "%s (code mode): %s" % (spec.name, ", ".join(parts))


# ---- the examples: the SDK's intricate modes, with their film recipes ------------------------------
#: The examples' recipes, beside their code: tools/spike2_emu/modes/sdk/examples/film_recipes.json.
#: Every time is seconds into the film: "clip" up to 8 s, "art" one frame, "music" a loop (a whole
#: number of 10 ms steps long), each call a span of the film's sound.
RECIPES_FILE = "film_recipes.json"


def _recipes():
    from . import mode_runtime as MR
    path = os.path.join(MR.sdk_dir(), "examples", RECIPES_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"films": {}, "titles": {}, "examples": []}


_R = _recipes()
#: film key -> the file name of the collection the recipes were measured on
FILMS = dict(_R.get("films") or {})
FILM_TITLES = dict(_R.get("titles") or {})
EXAMPLES = list(_R.get("examples") or [])


def example_names():
    return [e["name"] for e in EXAMPLES]


def example(name):
    for e in EXAMPLES:
        if e["name"] == name:
            return e
    return None


def examples_dir():
    from . import mode_runtime as MR
    return os.path.join(MR.sdk_dir(), "examples")


def recipe_films(ex):
    """The film keys an example's recipe cuts from, in first-use order."""
    out = []
    r = ex.get("recipe") or {}
    parts = [r.get("clip"), r.get("art"), r.get("music")] + list((r.get("calls") or {}).values())
    for p in parts:
        if p and p.get("film") not in out:
            out.append(p["film"])
    return out


def find_film(key, dirs):
    """The path of film *key* (:data:`FILMS`) in the first of *dirs* that holds it, or None."""
    name = FILMS.get(key, key)
    for d in dirs or ():
        if d and os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def film_dirs(project, extra=()):
    """Where to look for the films: *extra* first, then ``PAD_FILMS_DIR``, then every folder a
    mode of the project already cut from (a form mode's ``clip_source`` / ``sound_source`` /
    ``art_source``, a code mode's recorded ``film.dir``)."""
    out = []

    def add(d):
        if d and os.path.isdir(d) and os.path.normcase(os.path.abspath(d)) not in \
                [os.path.normcase(os.path.abspath(x)) for x in out]:
            out.append(d)

    for d in extra or ():
        add(d)
    add(os.environ.get("PAD_FILMS_DIR", ""))
    if project:
        try:
            for _slug, spec in MP.list_modes(project)[0]:
                for src in (spec.clip_source, spec.sound_source, spec.art_source):
                    if src:
                        add(os.path.dirname(str(src)))
        except (OSError, ValueError):
            pass
        for slug in code_slugs(project):
            try:
                add((load(project, slug).film or {}).get("dir", ""))
            except (OSError, ValueError):
                pass
    return out


def _copy_code(project, ex):
    folder = MP.mode_folder(project, ex["slug"])
    os.makedirs(folder, exist_ok=True)
    src = examples_dir()
    for name in [ex["source"]] + list(ex.get("headers") or ()):
        dst = os.path.join(folder, ex["slug"] + ".c" if name == ex["source"] else name)
        shutil.copyfile(os.path.join(src, name), dst)
    return folder


def example_spec(ex, cut=False):
    """The :class:`CodeAssets` an example brings. *cut*: its assets are in the folder (the films
    were found); otherwise only its screen (a generated panel) and its recipe."""
    r = ex.get("recipe") or {}
    spec = CodeAssets(name=ex["name"], seconds=int(ex.get("seconds") or 60), screen=True,
                      panel_color=ex.get("panel_color", "#146e28"), title_color=ex.get("title_color", "#ffe600"))
    spec.film = {"recipe": r, "films": {k: FILMS.get(k, k) for k in recipe_films(ex)},
                 "titles": {k: FILM_TITLES.get(k, k) for k in recipe_films(ex)}}
    if cut:
        if r.get("art"):
            spec.screen_art, spec.words_on_art = "screen.png", True
        if r.get("clip"):
            spec.clip = "clip.mp4"
        if r.get("music"):
            spec.music = "music.wav"
        spec.calls = {cue: ({"wav": "%s.wav" % cue, "priority": int(c.get("priority", 4))}
                            if int(c.get("priority", 4)) != 4 else "%s.wav" % cue)
                      for cue, c in (r.get("calls") or {}).items()}
    return spec


def add_example(project, name, dirs=(), ffmpeg=None, log=None):
    """Put example *name* in the project as ``modes/<slug>/``: its code (and the headers it
    includes) and its ``assets.json``, and cut its assets from the films when they are found
    (:func:`cut_example`). Returns ``(slug, missing)``: *missing* the film keys not found (then
    the mode is added with its code and a generated screen, and plays the game's own sounds).
    Refuses a folder that is already there."""
    ex = example(name)
    if ex is None:
        raise CodeModeError("there is no example called %s" % name)
    if not project or not os.path.isdir(project):
        raise CodeModeError(MP.NO_PROJECT_HELP)
    folder = MP.mode_folder(project, ex["slug"])
    if os.path.exists(folder):
        raise CodeModeError("%s is already in this project (modes/%s)." % (ex["name"], ex["slug"]))
    _copy_code(project, ex)
    missing = [k for k in recipe_films(ex) if not find_film(k, dirs)]
    if missing:
        save(project, ex["slug"], example_spec(ex, cut=False))
        return ex["slug"], missing
    spec = cut_example(project, ex["slug"], ex, dirs, ffmpeg=ffmpeg, log=log)
    save(project, ex["slug"], spec)
    return ex["slug"], []


def compose_art(still_png, out_png, band=72, below=False):
    """The screen's picture: a film frame with its bottom *band* pixels darkened (a gradient to
    85% black), so the mode's progress words, which the build puts on that band
    (``words_on_art``), read over any frame. *below*: the band is added UNDER the frame instead
    (a letterboxed frame whose own bottom carries something to keep, a title), a multiple of 4
    so the picture stays one BC3 texture."""
    from PIL import Image
    img = Image.open(still_png).convert("RGBA")
    w, h = img.size
    if below:
        band = (int(band) + 3) // 4 * 4
        canvas = Image.new("RGBA", (w, h + band), (0, 0, 0, 230))
        canvas.paste(img, (0, 0))
        canvas.save(out_png)
        return canvas.size
    band = min(band, h // 2)
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = shade.load()
    for y in range(h - band, h):
        a = int(round(217 * min(1.0, (y - (h - band)) / max(1.0, band * 0.35))))
        for x in range(w):
            px[x, y] = (0, 0, 0, a)
    out = Image.alpha_composite(img, shade)
    out.save(out_png)
    return out.size


def cut_example(project, slug, ex, dirs, ffmpeg=None, log=None):
    """Cut every asset of example *ex*'s recipe from the films in *dirs* into ``modes/<slug>/``
    with the app's film cutter: the clip (bank size, ``fill``), the picture (a frame with its
    word band), the music loop (stereo, seamless) and each call (mono, levelled like a stock
    callout, 40 ms edges). Returns the :class:`CodeAssets` that names them."""
    from . import film_cut as FC
    say = log or (lambda *a, **k: None)
    r = ex.get("recipe") or {}
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    ff = FC._ffmpeg(ffmpeg)
    pictures = {}

    def film_of(part):
        path = find_film(part["film"], dirs)
        if not path:
            raise CodeModeError("the film %s is not in %s" % (FILMS.get(part["film"], part["film"]),
                                                               ", ".join(dirs) or "any folder given"))
        return path

    def picture(path):
        if path not in pictures:
            pictures[path] = FC.detect_picture(path, ff)
        return pictures[path]

    used_dir = ""
    if r.get("clip"):
        c = r["clip"]
        path = film_of(c)
        FC.cut_clip(path, c["from"], c["length"], os.path.join(folder, "clip.mp4"), ff,
                    crop=c.get("crop", "fill"), picture=picture(path))
        say("%s: clip.mp4 cut from %s at %s for %g s" % (ex["name"], os.path.basename(path),
                                                         FC.format_time(c["from"]), c["length"]))
        used_dir = os.path.dirname(path)
    if r.get("art"):
        a = r["art"]
        path = film_of(a)
        still = os.path.join(folder, "screen_frame.png")
        FC.grab_still(path, a["at"], still, ff, width=int(a.get("width", 640)), crop=a.get("crop", "fill"),
                      picture=picture(path))
        compose_art(still, os.path.join(folder, "screen.png"), band=int(a.get("band", 72)),
                    below=bool(a.get("band_below")))
        os.remove(still)
        say("%s: screen.png is the frame at %s" % (ex["name"], FC.format_time(a["at"])))
    if r.get("music"):
        m = r["music"]
        path = film_of(m)
        FC.cut_loop(path, m["from"], m["length"], os.path.join(folder, "music.wav"), ff)
        say("%s: music.wav is a %.2f s loop from %s" % (ex["name"], m["length"], FC.format_time(m["from"])))
    for cue, c in (r.get("calls") or {}).items():
        path = film_of(c)
        FC.cut_sound(path, c["from"], c["length"], os.path.join(folder, "%s.wav" % cue), ff, channels=1)
        say("%s: %s.wav from %s for %g s" % (ex["name"], cue, FC.format_time(c["from"]), c["length"]))
    spec = example_spec(ex, cut=True)
    spec.film["dir"] = used_dir
    return spec


def recut_example(project, slug, dirs, ffmpeg=None, log=None):
    """Cut an example already in the project again from the films (the tab's "Cut its film
    assets" once the films are found). Returns ``missing`` film keys, or [] when cut."""
    spec = load(project, slug)
    r = (spec.film or {}).get("recipe")
    ex = next((e for e in EXAMPLES if e["slug"] == slug), None)
    if ex is None and r:
        ex = {"name": spec.name, "slug": slug, "recipe": r, "seconds": spec.seconds}
    if ex is None:
        raise CodeModeError("%s has no film recipe to cut from" % spec.name)
    if r:
        ex = dict(ex, recipe=r)
    missing = [k for k in recipe_films(ex) if not find_film(k, dirs)]
    if missing:
        return missing
    new = cut_example(project, slug, ex, dirs, ffmpeg=ffmpeg, log=log)
    new.seconds = spec.seconds
    save(project, slug, new)
    return []


def missing_words(missing):
    """"Godzilla (1954) and Godzilla vs. Destoroyah (1995)" for the tab."""
    names = ["%s (%s)" % (FILM_TITLES.get(k, k), FILMS.get(k, k)) for k in missing]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
