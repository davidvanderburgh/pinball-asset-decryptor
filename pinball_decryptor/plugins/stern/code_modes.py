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
      "screen_layout": {"x": 40, ...},  where the screen goes (PAD-323; {} = placed automatically)
      "screen_style": "words",       PAD-521: no panel - its words alone, large and white, where the game
                                     letters its own (James Bond: over the TV); "" = the panel
      "info_line": true,             PAD-547: a line of words and a value under its name (PadMode_<slug>_Info), where
                                     the title's port puts one (James Bond: under the status bar)
      "points_layout": {"y": 600},   PAD-709: where a words-alone mode's scored number goes (PadMode_<slug>_Points;
                                     {} = under the status bar, large, as the game's own mini-wizards show a shot's)
      "clip": "clip.mp4",            its start clip ("" = none)
      "music": "music.wav",          its own music bed ("" = none)
      "beds": {"swamp": "music_swamp.wav"},   PAD-658: more beds by name, which the mode switches to while it runs
                                     (pa_music_bed: a multiball of its own, a stage)
      "calls": {"sever": "sever.wav", "spike": {"wav": "spike.wav", "priority": 3}},
      "clips": {"intro": "intro.mp4", "loop": "loop.mp4", "sever": "sever.mp4"},
      "hud": {"title": "KING GHIDORAH", "timer": {"label": "GHIDORAH", "icon": "bolt"}, ...},
      "game_modes": "block",         PAD-347: while it runs, the game's own modes wait ("block", the
                                     default) or one starting ends it ("give_way")
      "block_modes": [21, 23],       PAD-363: which of the game's modes it holds off (the title's mode ids,
                                     as the Modes tab lists them; [] = every one the port names)
      "keep_rules": ["Bridge"],      PAD-398: the game's features (its rules, by the Modes tab's names) that
                                     go on counting while it runs; [] = none: only this mode counts
      "film": {...}                  PAD-691: where an example that is no longer in the app was cut from;
                                     kept as it was, read by nothing
    }

hud-layers: ``clips`` names a clip per CUE - "intro" plays full screen when the mode starts, "loop"
plays behind the HUD while it runs (the runtime's backdrop), any other cue on an event or at the end
(``pad_mode_assets.h``); the old ``clip`` is the "start" cue. ``hud`` is the mode's HUD at the glass's
edges (:mod:`.mode_hud`: its title and instruction line, counters, timer badge and gauge), built into
Godzilla's slide-outs scene. A mode with a HUD needs no ``screen``.

The CUES are the mode's own words (``pa_call(&own, "sever")`` in its C); the project maps each
to a WAV. Write (and Try it, which is Write's own code) then does for a code mode what it does
for a form mode: the screen into the HUD scene, the clip into the video bank, the music on a
bed and each call on a carrier, shared with the other modes' (:mod:`.mode_sounds`), and the mode compiled into the
object the card carries with ``mode_file.c``. The carriers it chose go on the card as
``<slug>.assets`` beside ``mode.so`` (:func:`runtime_text`), which the mode reads through
``tools/spike2_emu/modes/sdk/pad_mode_assets.h``.

"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields

from . import mode_project as MP

ASSETS_FILE = "assets.json"
FORMAT = 1
#: what the build puts beside mode.so for each code mode
RUNTIME_SUFFIX = ".assets"
#: pad_mode_assets.h reads at most this many calls
MAX_CALLS = 16
#: pad_mode_assets.h reads at most this many clips (hud-layers)
MAX_CLIPS = 12
#: PAD-658: pad_mode_assets.h reads at most this many further music beds (PA_BEDS_MAX)
MAX_BEDS = 6
CUE_RE = re.compile(r"^[a-z][a-z0-9_]{0,14}$")
SECONDS_MAX = 600


class CodeModeError(ValueError):
    """A code mode's assets that cannot be used as asked; the message is a sentence."""


#: PAD-347: what a code mode does about the game's own modes while it runs - keeps them from starting
#: (the ones the port lets a mode refuse; a multiball or a battle still ends it), or gives way: one
#: of them starting ends it
GAME_MODES = ("block", "give_way")


@dataclass
class CodeAssets:
    name: str = ""
    seconds: int = 60
    screen: bool = True
    screen_art: str = ""
    words_on_art: bool = False
    panel_color: str = "#146e28"
    title_color: str = "#ffe600"
    screen_layout: dict = field(default_factory=dict)   # PAD-323: as a form mode's (mode_assets.LAYOUT_KEYS)
    screen_style: str = ""                        # PAD-521: "words" = no panel, its words large and white
    info_line: bool = False                       # PAD-547: a line of words and a value under its name (PadMode_<slug>_Info)
    info_layout: dict = field(default_factory=dict)     # PAD-547: where the Scenes editor put that line (LAYOUT_KEYS)
    points_layout: dict = field(default_factory=dict)   # PAD-709: where it put a words-alone mode's scored number
    more: dict = field(default_factory=dict)      # PAD-707: {"slot": n, "picture": file} - a monster on MORE KAIJU
    clip: str = ""
    music: str = ""
    beds: dict = field(default_factory=dict)      # PAD-658: {name: wav} more music beds it switches to
    calls: dict = field(default_factory=dict)
    clips: dict = field(default_factory=dict)     # hud-layers: {cue: file}
    hud: dict = field(default_factory=dict)       # hud-layers: the HUD at the glass's edges
    game_modes: str = "block"                     # PAD-347: GAME_MODES
    block_modes: list = field(default_factory=list)   # PAD-363: the game's mode ids it holds off; [] = every one
    keep_rules: list = field(default_factory=list)    # PAD-398: the game's features (names) that keep counting
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

    def clip_list(self):
        """``[(cue, file)]``: every clip, the old start ``clip`` as the "start" cue (hud-layers)."""
        out = [(str(cue), str(f or "")) for cue, f in (self.clips or {}).items()]
        if self.clip and not any(c in ("start", "intro") for c, _f in out):
            out.insert(0, ("start", str(self.clip)))
        return out

    def has_assets(self):
        return bool(self.screen or self.clip or self.clips or self.hud or self.music or self.calls
                    or self.more)      # PAD-707: a new monster on the selection screen is drawn there


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
    from .mode_assets import layout_problems             # PAD-323
    out += ["%s: %s." % (spec.name, w) for w in layout_problems(spec.screen_layout)]
    if spec.game_modes not in GAME_MODES:                # PAD-347
        out.append("%s: game_modes is block or give_way, not %r." % (spec.name, spec.game_modes))
    ids = spec.block_modes if isinstance(spec.block_modes, list) else None   # PAD-363
    if ids is None or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i <= 127 for i in ids):
        out.append("%s: block_modes is a list of the game's mode ids, 0 to 127." % spec.name)
    calls = spec.call_list() if isinstance(spec.calls, dict) else None
    if calls is None:
        out.append("%s: calls maps each cue to a WAV." % spec.name)
        calls = []
    if len(calls) > MAX_CALLS:
        out.append("%s: a code mode carries at most %d calls." % (spec.name, MAX_CALLS))
    if not isinstance(spec.clips, dict) or not isinstance(spec.hud, dict):
        out.append("%s: clips maps each cue to a video, and hud is an object." % spec.name)
    else:
        clips = spec.clip_list()
        if len(clips) > MAX_CLIPS:
            out.append("%s: a code mode carries at most %d clips." % (spec.name, MAX_CLIPS))
        for cue, f in clips:
            if not CUE_RE.match(cue):
                out.append("%s: the clip cue %r is 1 to 15 lower-case letters, digits or _." % (spec.name, cue))
            if not f:
                out.append("%s: the %s clip names no video." % (spec.name, cue))
    beds = spec.beds if isinstance(spec.beds, dict) else None              # PAD-658
    if beds is None:
        out.append("%s: beds maps each bed's name to a WAV." % spec.name)
        beds = {}
    if beds and not spec.music:
        out.append("%s: more music beds need its own music first." % spec.name)
    if len(beds) > MAX_BEDS:
        out.append("%s: a code mode carries at most %d more music beds." % (spec.name, MAX_BEDS))
    for name, wav in beds.items():
        if not CUE_RE.match(str(name)):
            out.append("%s: the bed name %r is 1 to 15 lower-case letters, digits or _." % (spec.name, name))
        if not wav:
            out.append("%s: the %s bed names no WAV." % (spec.name, name))
    for cue, wav, prio in calls:
        if not CUE_RE.match(cue):
            out.append("%s: the cue %r is 1 to 15 lower-case letters, digits or _." % (spec.name, cue))
        if not 1 <= prio <= 7:
            out.append("%s: the %s call's priority is 1 to 7." % (spec.name, cue))
        if not wav:
            out.append("%s: the %s call names no WAV." % (spec.name, cue))
    if folder is not None:
        named = [("the picture", spec.screen_art), ("the music", spec.music)]
        named += [("the %s clip" % cue, f) for cue, f in (spec.clip_list() if isinstance(spec.clips, dict) else [])]
        named += [("the %s call" % cue, wav) for cue, wav, _p in calls]
        named += [("the %s music bed" % n, wav) for n, wav in beds.items()]
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


def bed_key(name):
    """PAD-658: the own-sound key one of a code mode's further music beds rides under."""
    return "music:%s" % name


def bed_of(key):
    return key[6:] if str(key).startswith("music:") else None


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
            for bed, wav in (spec.beds or {}).items():                  # PAD-658: its other beds
                out.append({"slug": slug, "name": spec.name, "key": bed_key(bed), "music": True,
                            "wav": os.path.join(folder, wav), "seconds": int(spec.seconds or 0)})
        for cue, wav, prio in spec.call_list():
            out.append({"slug": slug, "name": spec.name, "key": call_key(cue), "music": False,
                        "wav": os.path.join(folder, wav), "priority": prio})
    return out


def clip_name(slug, cue):
    """The name a code mode's clip for ``cue`` has in the video bank: the start cue keeps the old
    ``PadMode_<slug>_Clip``, every other is ``PadMode_<slug>_<Cue>`` (hud-layers)."""
    if cue == "start":
        return MP.asset_names(slug)["clip"]
    return "PadMode_%s_%s" % (slug, cue[:1].upper() + cue[1:])


def runtime_text(slug, spec, prof, own_sounds=(), screen=False, clip=False):
    """``<slug>.assets``, the file the mode reads (pad_mode_assets.h): its screen and clip as the
    build named them, and every own sound the build CARRIED (*own_sounds*: the engine's list,
    each with ``request``, ``ms`` and, for the music, ``sid``). A sound the build could not carry
    is left out, so the mode plays the game's own call there."""
    names = MP.asset_names(slug)
    lines = ["# GENERATED by the app's Write from modes/%s/%s - edit the mode there." % (slug, ASSETS_FILE),
             "name   %s" % spec.name.strip()]
    if getattr(spec, "game_modes", "block") == "give_way":
        lines.append("game_modes give_way")              # PAD-347: block is what the mode does without it
    else:
        if isinstance(getattr(spec, "block_modes", None), list) and spec.block_modes:   # PAD-363
            ids = sorted({i for i in spec.block_modes if isinstance(i, int) and 0 <= i <= 127})
            lines.append("block_modes %s" % " ".join(str(i) for i in ids))
        keep = MP.keep_rule_ids(spec, prof) if prof is not None else []                 # PAD-398
        if keep:
            lines.append("keep_rules %s" % " ".join(str(n) for n in keep))
    if screen:
        lines.append("screen %s %s" % (names["screen_node"], names["screen_text"]))
    if clip:
        for cue, _f in spec.clip_list():
            lines.append("clip   %s %s" % (cue, clip_name(slug, cue)))
    mine = [u for u in own_sounds or () if u.get("slug") == slug]
    prio = {cue: p for cue, _w, p in spec.call_list()}
    for u in mine:
        if u.get("key") == "music":
            # PAD-595: a bed in a sound bank of its own is played by that bank's sound id
            bed = u.get("bank_sid") or u.get("sid")
            lines.append("music  %d%s" % (int(u["request"]), " %d" % int(bed) if bed else ""))
    for u in mine:
        if bed_of(u.get("key")) and (u.get("bank_sid") or u.get("sid")):
            # PAD-658: a further bed on a sound id of its own (a bed sid, or a sound bank's); a swapped one rides
            # its "swap ... music:<name>" line below
            lines.append("bed    %s %d" % (bed_of(u["key"]), int(u.get("bank_sid") or u.get("sid"))))
    for u in mine:
        if u.get("bank_sid") and u.get("key") != "music" and not bed_of(u.get("key")):
            # PAD-595: a call in a sound bank of its own: the carrier is pointed at the bank's
            # sound id for that play (whose, as a swap's tag)
            lines.append("sid    %d %d %s" % (int(u["request"]), int(u["bank_sid"]), u["key"]))
        elif u.get("stock_key") and u.get("our_key"):     # item 163: swapped in at run time
            # hud-layers: and whose ("music" or "call:<cue>"): a carrier can take several of the
            # mode's sounds' neighbours in other modes, so the mode picks its own swap by cue
            lines.append("swap   %d %s %s %s" % (int(u["request"]), u["stock_key"], u["our_key"], u["key"]))
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
    clips = spec.clip_list()
    if clips and can_clip:
        if len(clips) == 1:
            parts.append("its own %s clip %s (a new file)" % (clips[0][0], clips[0][1]))
        else:
            parts.append("%d clips of its own (%s)" % (len(clips), ", ".join(c for c, _f in clips)))
    if spec.hud and can_screen:
        parts.append("its own HUD at the screen's edges")
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


def examples_dir():
    """The SDK's folder of the kit every code and blocks mode builds with (``intricate_kit.h``, PAD-691: no example
    modes are in it any more)."""
    from . import mode_runtime as MR
    return os.path.join(MR.sdk_dir(), "examples")
# ---- the kit beside a code mode (PAD-390) -------------------------------------------------------
#: the examples' kit: copied beside an example's C when it is added (:func:`_copy_code`)
KIT_FILE = "intricate_kit.h"
#: one sha256 per kit the app has shipped (CRLF read as LF)
KIT_SHIPPED = "kit_shipped.txt"


def _kit_digest(data):
    import hashlib
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def shipped_kits():
    """The digests of every ``intricate_kit.h`` the app has shipped (:data:`KIT_SHIPPED`)."""
    try:
        with open(os.path.join(examples_dir(), KIT_SHIPPED), "r", encoding="utf-8") as f:
            return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    except OSError:
        return set()


def refresh_kit(folder, log=None):
    """PAD-390: a code mode's folder holds its own copy of the kit, put there when the example was added and
    never touched since, so a kit fix (the HUDs hidden again when the game has its HUD scene back as built)
    never reached a project made before it. A copy that is one the app shipped (never edited) is brought up
    to the app's kit; an edited one is left as it is, and said. Returns "current", "refreshed", "edited" or
    "none" (no kit in the folder)."""
    say = log or (lambda *a, **k: None)
    dst = os.path.join(folder, KIT_FILE)
    try:
        with open(dst, "rb") as f:
            have = f.read()
        with open(os.path.join(examples_dir(), KIT_FILE), "rb") as f:
            app = f.read()
    except OSError:
        return "none"
    if _kit_digest(have) == _kit_digest(app):
        return "current"
    slug = os.path.basename(os.path.normpath(folder))
    if _kit_digest(have) not in shipped_kits():
        say("Modes: %s's %s is not one the app shipped (edited) - built with it as it is, without the "
            "app's newer kit." % (slug, KIT_FILE))
        return "edited"
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(app)
    os.replace(tmp, dst)
    say("Modes: %s's %s brought up to this app's kit (it was an earlier app's own copy)." % (slug, KIT_FILE))
    return "refreshed"


def refresh_kits(sources, log=None):
    """:func:`refresh_kit` for the folder of each code mode's C file in *sources*."""
    for src in sources:
        refresh_kit(os.path.dirname(os.path.abspath(src)), log=log)
