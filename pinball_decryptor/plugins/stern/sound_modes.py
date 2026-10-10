"""MUSIC MODES (PAD-494): one card, several sets of sounds; the operator's MUSIC MODE picks the set.

A tester rebuilding Godzilla kept an "Orchestral Edition" and a "Standard Edition" of every card
and asked instead for "multiple audio files slotted into the same replacement" - Slot A, B, C - and
"a service menu setting [that] allows the user to select a MUSIC MODE", the modes "custom titled
by the user". The Audio tab gives a sound files for modes 2 and 3 beside its own (mode 1: the
sound the slot plays today, its replacement or the stock one), the project names the modes
(``.staged_changes.json`` ``sound_modes``: ``{"names": [...], "slots": {rel: {"2": file, "3":
file}}}``), and a Write does three things:

1. each mode file is made into its slot's own format (the conversion a replacement gets,
   :func:`core.audio_slots.stage_replacement` against the slot's pristine sound) and goes into
   the sound bank as a record of its own: a grown copy of a record the project does not touch
   (a HOST), left un-pointed, so nothing the game plays names it (the engine's forced grows, the
   path the modes' own sounds take); its loudness is matched to the SLOT's, as a replacement's is;
2. the operator menu gets MUSIC MODE (:mod:`.menu_settings`: Audio Content, the modes' names in
   its help line, values 1..n);
3. ``sounds.cfg`` beside the mode runtime names, for every sound id of the game that plays a slot
   with a mode file, that mode's DESCRIPTOR - the game's own script for the sound, naming the
   mode's record and declaring the mode file's own length - and where the setting's value lives.
   The runtime (pad_mode_runtime.c "music modes") hands the game those bytes whenever the setting
   says that mode (emulator-proven on Godzilla Premium/LE 1.16: Music Mode set to 2 in the menu,
   and the game's music request played the mode's record).

It rides the modes' delivery (the runtime, its port and the cfg on p2), so it needs an image
file and a host that can add files to one, and it grows the game program, so an image build.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field

#: the project sidecar's key: ``{"names": [name, ...], "slots": {rel: {"2": file, "3": file}}}``
STAGED_KEY = "sound_modes"
#: how many modes a project may have (mode 1 is the card's own sounds)
MAX_MODES = 3
#: the runtime's table, beside mode.so on p2 (pad_mode_runtime.c SNDM_FILES)
CFG_NAME = "sounds.cfg"
#: ``PAD_STERN_SOUND_MODES=0`` leaves every mode file out of a build
GATE_ENV = "PAD_STERN_SOUND_MODES"
#: where the converted mode files are kept between builds, in the project
CACHE_DIR = os.path.join(".write_cache", "sound_modes")
#: ``<game>-<version>`` of the builds where the swap and the menu setting were SEEN working
#: (emulator: the setting on Audio Content, set in the menu, the game playing the mode's record)
PROVEN = frozenset({"godzilla_le-1.16", "godzilla_pro-1.16"})

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot give it a "
            "MUSIC MODE.")
NOT_PROVEN = ("Music modes have not been tried on %s yet, so they are not offered there. "
              "Godzilla Pro and Premium/LE 1.16 have them.")
NOT_SOUND = "Only a sound the game keeps in its sound bank (an idx file) can have a file for another mode."

_IDX_RE = re.compile(r"(?:^|/)idx(\d+)")


class SoundModeError(ValueError):
    """Mode files a build cannot carry; the message says why."""


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


@dataclass
class Modes:
    """A project's music modes: the names of modes 1..n and each slot's files for modes 2..n."""
    names: list = field(default_factory=list)
    slots: dict = field(default_factory=dict)      # {rel: {mode: file}}

    @property
    def count(self):
        """How many modes the card offers: the highest mode a file is set for (2 or more), else 0."""
        top = max((m for files in self.slots.values() for m in files), default=0)
        return top if top >= 2 else 0

    def name(self, mode):
        n = self.names[mode - 1] if 0 < mode <= len(self.names) else ""
        return " ".join(str(n or "").split()) or "Mode %d" % mode

    def menu_names(self):
        """The names the menu's help line gives modes 1..count."""
        return [self.name(m) for m in range(1, self.count + 1)]

    def files(self):
        """``[(rel, mode, file)]``, in slot then mode order."""
        return [(rel, m, f) for rel in sorted(self.slots) for m, f in sorted(self.slots[rel].items())]


def clean(raw):
    """A :class:`Modes` from a sidecar's value: modes 2..:data:`MAX_MODES` only, empty paths and
    empty slots dropped, at most :data:`MAX_MODES` names."""
    out = Modes()
    if not isinstance(raw, dict):
        return out
    names = raw.get("names")
    if isinstance(names, (list, tuple)):
        out.names = [str(n) if isinstance(n, str) else "" for n in names][:MAX_MODES]
    slots = raw.get("slots")
    if isinstance(slots, dict):
        for rel, files in slots.items():
            if not isinstance(rel, str) or not isinstance(files, dict):
                continue
            keep = {}
            for m, f in files.items():
                try:
                    m = int(m)
                except (TypeError, ValueError):
                    continue
                if 2 <= m <= MAX_MODES and isinstance(f, str) and f.strip():
                    keep[m] = f
            if keep:
                out.slots[rel] = keep
    return out


def to_json(modes):
    """The sidecar value for *modes* (``None`` when there is nothing to keep)."""
    names = [n for n in modes.names]
    while names and not str(names[-1] or "").strip():
        names.pop()
    if not modes.slots and not names:
        return None
    return {"names": names,
            "slots": {rel: {str(m): f for m, f in sorted(files.items())}
                      for rel, files in sorted(modes.slots.items()) if files}}


def load(project):
    """The project's music modes (a :class:`Modes`; empty when it has none)."""
    if not project:
        return Modes()
    from ...core import staged_changes
    try:
        return clean(staged_changes.load(project).get(STAGED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return Modes()


def slot_idx(rel):
    """The sound-bank record a slot's file is (``audio/idx2095 - music - ...wav`` -> 2095), or None."""
    m = _IDX_RE.search(str(rel or "").replace("\\", "/"))
    return int(m.group(1)) if m else None


# ---- which titles -------------------------------------------------------------------------------
def title_key(prof):
    return "%s-%s" % (prof.game_dir, prof.version) if prof is not None else ""


def title_refusal(prof):
    """Why no sound of ``prof``'s title can have mode files, or ``""``."""
    if prof is None:
        return NO_TITLE
    if title_key(prof) not in PROVEN:
        return NOT_PROVEN % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except OSError:
        return NOT_PROVEN % prof.label
    if "sound_resolve" not in port["site"]:
        return NOT_PROVEN % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None (:func:`.clip_variants.project_title`)."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def offer(project, rels, probe=True):
    """``(title_why, {rel: why})`` for the Audio tab: why no sound of the project's game can have
    files for other modes (``""`` when they can), and per slot why that one cannot (``""`` when it
    can)."""
    if not enabled():
        return ("%s=0 leaves music modes out of this app." % GATE_ENV), {}
    prof = project_title(project, probe=probe)
    why = title_refusal(prof)
    if why:
        return why, {}
    return "", {rel: ("" if slot_idx(rel) is not None else NOT_SOUND) for rel in rels}


# ---- the files ----------------------------------------------------------------------------------
def _pristine(project, rel):
    """The slot's own sound as it shipped: the ``.orig`` snapshot when a build replaced it, else
    the file in the slot."""
    from ...core import staged_originals
    orig = staged_originals.snapshot_path(project, rel)
    if orig and os.path.isfile(orig):
        return orig
    return os.path.join(project, *rel.split("/"))


def convert(project, rel, mode, src, log=None):
    """*src* made into slot *rel*'s own format (channels, rate, bit depth; never trimmed), kept in
    the project's write cache and reused while neither changes. Returns the WAV's path. Raises
    :class:`SoundModeError` with the reason when it cannot be made."""
    from ...core.audio_slots import AudioSlot, stage_replacement
    from ...core.audio import detect_audio_info
    if not os.path.isfile(src):
        raise SoundModeError("%s is not there any more" % src)
    pristine = _pristine(project, rel)
    st, sp = os.stat(src), os.stat(pristine)
    key = hashlib.md5(json.dumps([os.path.abspath(src), st.st_size, st.st_mtime_ns,
                                  os.path.abspath(pristine), sp.st_size, sp.st_mtime_ns, rel, mode]
                                 ).encode()).hexdigest()[:16]
    cache = os.path.join(project, CACHE_DIR)
    out = os.path.join(cache, "%s.wav" % key)
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return out
    os.makedirs(cache, exist_ok=True)
    info = detect_audio_info(pristine)
    if info is None:
        raise SoundModeError("the slot's own sound (%s) cannot be read" % os.path.basename(pristine))
    tmp = os.path.join(cache, "%s.part.wav" % key)
    shutil.copyfile(pristine, tmp)
    ok, why = stage_replacement(AudioSlot(rel_path=rel, abs_path=tmp, ext=".wav", info=info, size=0), src,
                                trim_to_length=False)
    if not ok:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SoundModeError("%s could not be made into the slot's format (%s)"
                             % (os.path.basename(src), why))
    os.replace(tmp, out)
    if log:
        log("Music modes: %s for mode %d of %s made into the slot's format%s." % (
            os.path.basename(src), mode, os.path.basename(rel), " (%s)" % why if why else ""), "info")
    return out


# ---- the runtime's table ------------------------------------------------------------------------
def cfg_text(live, count, sounds, only):
    """``sounds.cfg``: *live* the setting's value address, *count* the modes, *sounds*
    ``[(mode, sound id, descriptor bytes)]``, *only* when the card carries no modes."""
    lines = ["# PAD-494 music modes: the operator's MUSIC MODE picks which descriptor each sound id plays"]
    if only:
        lines.append("only")
    lines.append("setting\t0x%08x\t%d" % (int(live), int(count)))
    for mode, sid, desc in sounds:
        lines.append("sound\t%d\t%d\t%s" % (int(mode), int(sid), bytes(desc).hex()))
    return "\n".join(lines) + "\n"
