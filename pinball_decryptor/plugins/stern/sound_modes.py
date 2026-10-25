"""MUSIC MODES (PAD-494): one card, several sets of sounds; the operator's MUSIC MODE picks the set.

A tester rebuilding Godzilla kept an "Orchestral Edition" and a "Standard Edition" of every card
and asked instead for "multiple audio files slotted into the same replacement" - Slot A, B, C - and
"a service menu setting [that] allows the user to select a MUSIC MODE", the modes "custom titled
by the user"; then, once it shipped, "need at least 4" and more on demand. The Audio tab gives a
sound files for modes 2 to :data:`MAX_MODES` beside its own (mode 1: the sound the slot plays
today, its replacement or the stock one; :data:`SHOWN_MODES` are offered before the user adds
more), the project names the modes (``.staged_changes.json`` ``sound_modes``: ``{"names": [...],
"slots": {rel: {"2": file, "3": file}}, "levels": {rel: {"2": dB}}}``; unnamed ones are
"Standard", "Custom A"...), and a Write does three things:

1. each mode file is made into its slot's own format (the conversion a replacement gets,
   :func:`core.audio_slots.stage_replacement` against the slot's pristine sound) and goes into
   the sound bank as a record of its own: a grown copy of a record the project does not touch
   (a HOST), left un-pointed, so nothing the game plays names it (the engine's forced grows, the
   path the modes' own sounds take); its loudness is matched to the SLOT's, as a replacement's is,
   then moved by the mode file's OWN loudness offset (``levels``; the Audio tab's "Loudness for
   this clip" while that file is in the Replacement pane). The slot's own offset is its own
   sound's: "the individual loudness setting [should be] specific to mode files", the tester
   asked, once a level set on a stock song for its mode files read as a level on the stock song.
   A project saved before mode files had their own (no ``levels`` key) gives each one its slot's
   offset, as those builds did. One file in several modes of a slot at one level is one record. A
   file longer than its slot's sound is cut
   to that length unless the build may keep replacements whole ("Allow replacements longer than
   the original"), as a replacement is;
2. the operator menu gets MUSIC MODE (:mod:`.menu_settings`: Audio Content, the modes' names in
   its help line, values 1..n; PAD-724: on the 21 games whose Adjustments are Standard and Feature
   Adjustments, the last rows of Standard Adjustments, where the DMD shows no help line);
3. ``sounds.cfg`` beside the mode runtime names, for every sound id of the game that plays a slot
   with a mode file, that mode's DESCRIPTOR - the game's own script for the sound, naming the
   mode's record and declaring the mode file's own length - and where the setting's value lives.
   The runtime (pad_mode_runtime.c "music modes") hands the game those bytes whenever the setting
   says that mode (emulator-proven on Godzilla Premium/LE 1.16: Music Mode set to 2 in the menu,
   and the game's music request played the mode's record; PAD-724: on the latest build of every
   Spike 2 game, each port naming its game's resolver as ``site sound_resolve``). A sound id plays one line per mode,
   every slot of that mode it plays swapped in it. A slot the game plays as the OPENING part of
   a song in parts (Godzilla's "SE GZ MX TUNE 16": idx 2241's 9.6 s, then the unnamed idx 799,
   looped; PAD-511, where the tester heard their file's first seconds and then the game's own
   song) gets a descriptor that plays the mode's record in place of the whole song, once or looped
   as the song was, and the song's length is its file's room. So do the sound ids that play that
   song without its opening ("SE GZ MX TUNE 16 NO INTRO": idx 799 alone).

It rides the modes' delivery (the runtime, its port and the cfg on p2), so it needs an image
file and a host that can add files to one, and it grows the game program, so an image build.

SOUNDS IN TURN (PAD-565): an owner asked "is it possible to assign two other sounds to a single
sound and play them alternately?". A slot can also have more files that the game plays IN TURN
with its own (``turns``: ``{rel: [file 2, file 3, ...]}``, at most :data:`TURN_MAX` in all, its
own one included): each time the game starts that sound it plays the next one, its own sound (or
its replacement) first, then file 2, file 3... and round again. They take the music modes' road
whole: each one is a record of its own made the same way, under a pseudo mode
(:func:`turn_mode`: :data:`TURN_BASE` + k, never a menu value), and ``sounds.cfg`` names its
record key on a ``turn`` line beside the slot's own (pad_mode_runtime.c "sounds in turn": the
game's record lookup, ``site sound_lookup``, gets the next key each time it looks the slot up). A
file plays for as long as its slot's sound, so each one is cut to that length. No setting goes in the menu for them.
While a music mode gives the slot a file of its own, that file plays every time (its descriptor
names that file's record, not the slot's).

IN A MUSIC MODE (PAD-638, round 3: "can a set of random variants be assigned to an audio mode
slot?"): a slot's file for music mode m can have files in turn (or at random) of its own
(``mode_turns``: ``{rel: {m: [file 2, ...]}}``, ``mode_random``: ``{rel: [m, ...]}``,
``mode_turn_levels``: ``{rel: {m: {k: dB}}}``). Mode m's descriptors name the mode file's own new
record, so the game looks THAT record's key up while the setting says m: its ``turn`` / ``random``
lines name that key, and the runtime swaps it as it does a slot's (no runtime change). Each is cut
to its mode file's length (the descriptor declares it). They stay in image.bin: a mode file in a
sound bank is reached by a bank sound id, not its key, so its own files in turn are left out.

AT RANDOM (PAD-638): an owner asked for "random audio variants ... like a jukebox". A slot with
files in turn can play them AT RANDOM instead (``random``: ``[rel, ...]``, slots with files in
turn only): each play picks any of its files but the one it played last. The same files, records
and lines; ``sounds.cfg`` adds a ``random`` line naming the slot's record key (pad_mode_runtime.c
"AT RANDOM").

IN A SOUND BANK (PAD-608): a file ``image.bin`` has no room for goes into a sound bank of the app's
own (``image-scNN.bin``, PAD-595), as the modes' own sounds and the longer replacements do. The game
plays a bank's sound only under a sound id of the bank's own (it streams from the file of the id's
category), so such a file gets one bank sound id for every game sound id that plays its slot, each
with that game id's descriptor naming the bank's record, and ``sounds.cfg`` says which (``bsid``
for a mode's file, ``tsid`` for a file in turn): the runtime points the game's sound requests at
the bank's ids when the setting (or the turn) wants that file (pad_mode_runtime.c "IN A SOUND
BANK"). The card's record names such a file's record as ``<bank>:<record>``, and an extract of the
card decodes that bank to bring it back.

ATTRACT FLIPPER SOUNDS (PAD-641): an owner noticed every other Spike 2 game plays a sound or a
callout when a flipper button is pressed in attract mode, and James Bond plays none (measured in the
emulator: Godzilla LE 1.16 plays its request 64, Bond LE 1.06 nothing in 8 presses), and asked to add
a few. The project lists its own files (``attract``: ``[file 1, file 2, ...]``, at most
:data:`ATTRACT_MAX`); a press of either flipper button in attract plays the next of them, in turn.
The game has no sound for that, so the files ride a CARRIER, a request the game never plays (the
modes' own calls' road, :mod:`.mode_sounds`): each is a record of its own, made as a file in turn
is (a grown copy of a host record, cut to the carrier's length) under a pseudo mode
(:func:`attract_mode`) on the carrier's slot, and ``sounds.cfg`` names the carrier, its record's
key, the flipper buttons' switch ids and each file's record key and length (``attract`` /
``afile`` lines). The runtime (pad_mode_runtime.c "attract flipper sounds") hooks the framework's
switch drain and plays the carrier with the next file's key swapped in at the game's record lookup,
only while the game's mode mask says attract, and not while the last one still plays.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
from dataclasses import dataclass, field

from . import menu_settings as _MS

#: the project sidecar's key: ``{"names": [name, ...], "slots": {rel: {"2": file, "3": file}},
#: "levels": {rel: {"2": dB}}}``
STAGED_KEY = "sound_modes"
#: a mode file's loudness offset, as the per-clip one: whole dB, at most this far either way
LEVEL_MAX = 12
#: how many modes a project may have (mode 1 is the card's own sounds). The tester asked for "at
#: least 4" and room for more; the runtime and the menu setting both take 8
MAX_MODES = 8
#: how many the Audio tab offers before the user adds more
SHOWN_MODES = 4
#: PAD-641: the most files the flipper buttons play in attract, and the pseudo mode file k of them
#: is built under (:func:`attract_mode`; above :data:`TURN_BASE`, so the build treats it as a file in
#: turn: cut to its carrier's length, matched to the carrier's loudness)
ATTRACT_MAX = 16
#: PAD-641 round 2: the times the Audio tab offers between two of them, in seconds (0: any time, once
#: the last one has played), the owner's "only allow playing the flipper sounds every so often like 30
#: seconds"; a project's own value is kept within 0..ATTRACT_GAP_MAX
ATTRACT_GAPS = (0, 10, 30, 60, 120, 300)
ATTRACT_GAP_MAX = 3600
ATTRACT_BASE = 200
#: PAD-645: the pseudo file the build adds after them, a short silence: the game's own sound at the
#: press plays it instead (``aquiet`` in sounds.cfg), so only the project's file is heard
ATTRACT_QUIET = ATTRACT_MAX + 1
ATTRACT_QUIET_SECONDS = 0.1
#: the runtime's table, beside mode.so on p2 (pad_mode_runtime.c SNDM_FILES)
CFG_NAME = "sounds.cfg"
#: ``PAD_STERN_SOUND_MODES=0`` leaves every mode file out of a build
GATE_ENV = "PAD_STERN_SOUND_MODES"
#: where the converted mode files are kept between builds, in the project
CACHE_DIR = os.path.join(".write_cache", "sound_modes")
#: ``<game>-<version>`` of the builds where the swap and the menu setting were SEEN working
#: (emulator: the setting on Audio Content, set in the menu, the game playing the mode's record).
#: PAD-724: the latest build of every Spike 2 game (:data:`.menu_settings.PROVEN`; each port names
#: its game's ``sound_resolve``)
PROVEN = _MS.PROVEN
#: PAD-565: the most files one sound plays in turn, its own one included (pad_mode_runtime.c
#: SNDT_MAX), and the pseudo mode file k of them is built under (:func:`turn_mode`)
TURN_MAX = 16
TURN_BASE = 100
#: PAD-638: music mode m's file k in turn is built under pseudo mode MODE_TURN_BASE + m * 20 + k
#: (:func:`mode_turn`; above :data:`TURN_BASE`, so the build treats it as a file in turn)
MODE_TURN_BASE = 1000
#: PAD-685: the jukebox's song k (1..) is built under pseudo mode JUKE_BASE + k (:func:`juke_mode`;
#: above :data:`TURN_BASE`, so the build treats it as a file in turn, matched to its slot's loudness -
#: but never cut: the game plays a song whole, :mod:`.jukebox`)
JUKE_BASE = 5000
#: PAD-565: ``<game>-<version>`` of the builds where the sounds in turn were SEEN working: the
#: LATEST build of every Stern Spike 2 game in the image library (David: "just the latest
#: versions"), each swept in the emulator (an override set built by Write's own code, the slot's
#: request fired six times, the files heard in the order the runtime picked them; work/artifacts/
#: PAD-565/emulator/sweep; Avengers Infinity Quest Pro 1.10 by the same sweep once PAD-481 let its
#: sound bank be rewritten). They need only the record lookup, not the resolver or the menu setting.
#: Not here: every build older than its game's latest.
TURN_PROVEN = frozenset({
    "aerosmith-1.16", "aerosmith_le-1.16", "avengers_infinity_le-1.10",
    "avengers_infinity_pro-1.10", "batman-1.14",
    "beatles-1.29", "deadpool_le-1.16", "deadpool_pro-1.16", "dungeons_and_dragons_le-1.10",
    "dungeons_and_dragons_pro-1.10", "elvira3-1.13", "foo_fighters_le-1.04",
    "foo_fighters_pro-1.04", "godzilla_le-1.16", "godzilla_pro-1.16", "guardians-1.15",
    "guardians_le-1.15", "iron_maiden_le-1.18", "iron_maiden_pro-1.18", "james_bond_60th_le-1.11",
    "james_bond_le-1.06", "james_bond_pro-1.06", "jaws_le-1.02", "jaws_pro-1.02",
    "john_wick_le-1.02", "john_wick_pro-1.02", "jurassic_park_le-1.16", "jurassic_park_pro-1.16",
    "jurassic_park_the_pin-1.05", "king_kong_le-0.97", "king_kong_pro-0.97",
    "led_zeppelin_le-1.22", "led_zeppelin_pro-1.22", "mando_le-1.45", "mando_pro-1.45",
    "metallica_spike-1.04", "munsters_le-1.28", "munsters_pro-1.28", "rush_le-1.19",
    "rush_pro-1.19", "star_wars_elg-1.10", "star_wars_le-1.31", "star_wars_pro-1.31",
    "stranger_things-1.13", "stranger_things_le-1.13", "sword_of_rage_le-1.19",
    "sword_of_rage_pro-1.19", "turtles_le-1.59", "turtles_pro-1.59", "uncanny_xmen_le-0.98",
    "uncanny_xmen_pro-0.98", "venom_le-1.07", "venom_pro-1.07",
})

NO_TITLE = ("The app cannot tell which game this project is for, so it cannot give it a "
            "MUSIC MODE.")
NOT_PROVEN = ("Music modes are not offered on %s. They work on the latest version of each Stern "
              "Spike 2 game: update the machine's code to use them.")
#: PAD-724: the latest builds whose program cannot grow (:data:`.menu_settings.NO_ROOM`)
NO_ROOM = ("Music modes are not offered on %s: its game program has no room to grow, so its "
           "operator menu cannot take MUSIC MODE.")
NOT_PROVEN_TURNS = ("Sounds in turn are not offered on %s. They work on the latest version of each "
                    "Stern Spike 2 game: update the machine's code to use them.")
NOT_SOUND = "Only a sound the game keeps in its sound bank (an idx file) can have a file for another mode."
NOT_SOUND_TURN = "Only a sound the game keeps in its sound bank (an idx file) can play files in turn."
#: PAD-641: why the flipper buttons cannot play sounds in attract on a build
NO_TITLE_ATTRACT = ("The app cannot tell which game this project is for, so it cannot give its flipper "
                    "buttons sounds in attract mode.")
NO_ATTRACT = ("Sounds for the flipper buttons in attract mode are not offered on %s: %s.")

_IDX_RE = re.compile(r"(?:^|/)idx(\d+)")


class SoundModeError(ValueError):
    """Mode files a build cannot carry; the message says why."""


def enabled():
    return os.environ.get(GATE_ENV, "1") != "0"


@dataclass
class Modes:
    """A project's music modes: the names of modes 1..n, each slot's files for modes 2..n, and
    their loudness offsets (``None``: a project saved before mode files had their own, whose mode
    files take their slot's)."""
    names: list = field(default_factory=list)
    slots: dict = field(default_factory=dict)      # {rel: {mode: file}}
    levels: dict = field(default_factory=dict)     # {rel: {mode: dB}}, or None
    turns: dict = field(default_factory=dict)      # PAD-565: {rel: [file 2, file 3, ...]}
    random: set = field(default_factory=set)       # PAD-638: slots whose files in turn play at random
    turn_levels: dict = field(default_factory=dict)  # PAD-638: {rel: {k: dB}}, file k in turn's own
    #: PAD-638: a music mode's own files in turn: {rel: {m: [file 2, ...]}}, the slots' modes of
    #: them that play at random {rel: {m, ...}}, and their loudness {rel: {m: {k: dB}}}
    mode_turns: dict = field(default_factory=dict)
    mode_random: dict = field(default_factory=dict)
    mode_turn_levels: dict = field(default_factory=dict)
    attract: list = field(default_factory=list)    # PAD-641: [file 1, file 2, ...]
    #: PAD-641 round 2: at least this many seconds from one of them to the next (0: any time)
    attract_gap: int = 0
    #: PAD-641: the carrier's slot the attract files are built on (a build sets it; never saved)
    attract_rel: str = ""
    #: PAD-641: the build's carrier for them: ``{"request", "slot", "switches"}`` (never saved)
    attract_plan: dict = field(default_factory=dict)
    #: PAD-645: the silence the build adds for the game's own sound at a press (a build sets it;
    #: never saved)
    attract_quiet: str = ""
    #: PAD-685: the jukebox's songs' audio files and the slot they are made like (a build sets them
    #: from :mod:`.jukebox`; never saved here)
    jukebox: list = field(default_factory=list)
    juke_rel: str = ""
    #: PAD-685: the build's jukebox: ``{"box": jukebox.Jukebox, "prof": profile}`` (never saved)
    juke_plan: dict = field(default_factory=dict)

    @property
    def any(self):
        """Whether a build has anything of these to carry: a music mode, a sound in turn or a
        sound for the flipper buttons in attract."""
        return bool(self.count or self.turns or self.attract or self.jukebox)

    @property
    def count(self):
        """How many modes the card offers: the highest mode a file is set for (2 or more), else 0."""
        top = max((m for files in self.slots.values() for m in files), default=0)
        return top if top >= 2 else 0

    def name(self, mode):
        if is_juke(mode):
            return "jukebox"
        if is_attract(mode):
            return "in attract"
        if is_mode_turn(mode):
            return "%s, in turn" % self.name(mode_turn_of(mode)[0])
        if is_turn(mode):
            return "in turn"
        n = self.names[mode - 1] if 0 < mode <= len(self.names) else ""
        return " ".join(str(n or "").split()) or default_name(mode)

    def menu_names(self):
        """The names the menu's help line gives modes 1..count."""
        return [self.name(m) for m in range(1, self.count + 1)]

    def files(self):
        """``[(rel, mode, file)]``, in slot then mode order, then the sounds in turn (each under
        its pseudo mode, :func:`turn_mode`), then the flipper buttons' sounds in attract on the
        carrier's slot once a build has named it (:attr:`attract_rel`, :func:`attract_mode`)."""
        return ([(rel, m, f) for rel in sorted(self.slots) for m, f in sorted(self.slots[rel].items())]
                + [(rel, turn_mode(k), f) for rel in sorted(self.turns)
                   for k, f in enumerate(self.turns[rel], 2)]
                + [(rel, mode_turn(m, k), f) for rel in sorted(self.mode_turns)
                   for m in sorted(self.mode_turns[rel])
                   for k, f in enumerate(self.mode_turns[rel][m], 2)]
                + ([(self.attract_rel, attract_mode(k), f) for k, f in enumerate(self.attract, 1)]
                   if self.attract_rel else [])
                + ([(self.attract_rel, attract_mode(ATTRACT_QUIET), self.attract_quiet)]
                   if self.attract_rel and self.attract_quiet and self.attract else [])
                + ([(self.juke_rel, juke_mode(k), f) for k, f in enumerate(self.jukebox, 1)]
                   if self.juke_rel else []))

    def level(self, rel, mode):
        """Mode *mode*'s file's loudness offset in dB for slot *rel* (0: matched to the slot's
        sound), or ``None`` for a project saved before mode files had their own. A file in turn
        has a loudness of its own too (PAD-638: ``turn_levels``), 0 unless one was set."""
        if is_juke(mode):
            return 0
        if is_mode_turn(mode):
            m, k = mode_turn_of(mode)
            return int(((self.mode_turn_levels.get(rel) or {}).get(m) or {}).get(k, 0) or 0)
        if is_turn(mode):
            return int((self.turn_levels.get(rel) or {}).get(turn_of(mode), 0) or 0)
        if self.levels is None:
            return None
        return int((self.levels.get(rel) or {}).get(mode, 0) or 0)


def clean_gap(v):
    """PAD-641 round 2: a time between two flipper sounds as kept: whole seconds within
    0..:data:`ATTRACT_GAP_MAX` (0 for junk)."""
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(ATTRACT_GAP_MAX, v))


def attract_mode(k):
    """PAD-641: the pseudo mode the flipper buttons' file *k* in attract (1..:data:`ATTRACT_MAX`)
    is built under."""
    return ATTRACT_BASE + int(k)


def is_attract(mode):
    return ATTRACT_BASE < int(mode) < MODE_TURN_BASE


def mode_turn(m, k):
    """PAD-638: the pseudo mode music mode *m*'s file *k* in turn (2..:data:`TURN_MAX`) is built
    under."""
    return MODE_TURN_BASE + int(m) * 20 + int(k)


def is_mode_turn(mode):
    return MODE_TURN_BASE < int(mode) < JUKE_BASE


def juke_mode(k):
    """PAD-685: the pseudo mode the jukebox's song *k* (1..) is built under."""
    return JUKE_BASE + int(k)


def is_juke(mode):
    return int(mode) > JUKE_BASE


def mode_turn_of(mode):
    """``(m, k)``: music mode m's file k in turn, from its pseudo mode."""
    return divmod(int(mode) - MODE_TURN_BASE, 20)


def attract_of(mode):
    """File k of the flipper buttons' sounds in attract, from its pseudo mode."""
    return int(mode) - ATTRACT_BASE


def turn_mode(k):
    """The pseudo mode a slot's file *k* in turn (2..:data:`TURN_MAX`) is built under."""
    return TURN_BASE + int(k)


def is_turn(mode):
    """Whether a file is built as a file in turn is: a slot's file in turn, or (PAD-641) a sound of
    the flipper buttons in attract (:func:`is_attract`)."""
    return int(mode) > TURN_BASE


def turn_of(mode):
    """File k of a slot's sounds in turn, from its pseudo mode (PAD-638: of a music mode's too)."""
    if is_juke(mode):
        return int(mode) - JUKE_BASE
    if is_mode_turn(mode):
        return mode_turn_of(mode)[1]
    return int(mode) - TURN_BASE


def who(mode):
    """The log lines' heading for a file built under *mode*."""
    if is_juke(mode):
        return "Jukebox"
    if is_attract(mode):
        return "Attract flipper sounds"
    return "Sounds in turn" if is_turn(mode) else "Music modes"


def what(rel, mode, name=""):
    """A file built under *mode* for slot *rel*, as the log names it."""
    base = os.path.basename(str(rel).replace("\\", "/"))
    if is_juke(mode):
        return "song %d" % turn_of(mode)
    if is_attract(mode):
        if attract_of(mode) == ATTRACT_QUIET:
            return "the silence the game's own sound at a press plays"
        return "flipper sound %d" % attract_of(mode)
    if is_mode_turn(mode):
        m, k = mode_turn_of(mode)
        return "%s's mode %d file %d in turn" % (base, m, k)
    if is_turn(mode):
        return "%s's file %d in turn" % (base, turn_of(mode))
    return "%s's file for mode %d (%s)" % (base, mode, name or default_name(mode))


def tag(rel, mode):
    """The build record's words for a file built under *mode* for slot *rel*."""
    base = os.path.basename(str(rel).replace("\\", "/"))
    if is_juke(mode):
        return "jukebox song %d" % turn_of(mode)
    if is_attract(mode):
        if attract_of(mode) == ATTRACT_QUIET:
            return "the silence for the game's own sound at a flipper button press in attract"
        return "flipper sound %d in attract" % attract_of(mode)
    if is_mode_turn(mode):
        return "%s (mode %d, file %d in turn)" % ((base,) + mode_turn_of(mode))
    if is_turn(mode):
        return "%s (file %d in turn)" % (base, turn_of(mode))
    return "%s (mode %d)" % (base, int(mode))


def when(mode):
    """When the game plays a file built under *mode*: "while MUSIC MODE is 2", "every 2nd time"."""
    if is_juke(mode):
        return "when the jukebox draws it for a song mode"
    if is_attract(mode):
        if attract_of(mode) == ATTRACT_QUIET:
            return "in place of the game's own sound at a flipper button press in attract"
        return "at a flipper button press in attract (sound %d)" % attract_of(mode)
    if is_mode_turn(mode):
        return "while MUSIC MODE is %d, at its turn (file %d)" % mode_turn_of(mode)
    if is_turn(mode):
        return "at its turn (file %d)" % turn_of(mode)
    return "while MUSIC MODE is %d" % int(mode)


def default_name(mode):
    """A mode nobody named: "Standard" for mode 1 (the sounds as they are), then "Custom A",
    "Custom B"... (the tester's own words for them)."""
    return "Standard" if mode <= 1 else "Custom %s" % chr(ord("A") + mode - 2)


def _modes_of(files, keep):
    """``{mode: value}`` of *files*' modes 2..:data:`MAX_MODES` whose value *keep* turns into
    something (``None`` drops it)."""
    out = {}
    for m, v in files.items():
        try:
            m = int(m)
        except (TypeError, ValueError):
            continue
        if 2 <= m <= MAX_MODES:
            v = keep(v)
            if v is not None:
                out[m] = v
    return out


def clean_level(v):
    """A loudness offset as kept: whole dB within :data:`LEVEL_MAX`, ``None`` for 0 or junk."""
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(-LEVEL_MAX, min(LEVEL_MAX, v)) or None


def clean(raw):
    """A :class:`Modes` from a sidecar's value: modes 2..:data:`MAX_MODES` only, empty paths and
    empty slots dropped, at most :data:`MAX_MODES` names, levels of files the slot has only."""
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
            keep = _modes_of(files, lambda f: f if isinstance(f, str) and f.strip() else None)
            if keep:
                out.slots[rel] = keep
    turns = raw.get("turns")
    if isinstance(turns, dict):
        for rel, files in turns.items():
            if not isinstance(rel, str) or not isinstance(files, (list, tuple)):
                continue
            keep = [f for f in files if isinstance(f, str) and f.strip()][:TURN_MAX - 1]
            if keep:
                out.turns[rel] = keep
    rnd = raw.get("random")
    if isinstance(rnd, (list, tuple)):
        out.random = {rel for rel in rnd if isinstance(rel, str) and rel in out.turns}
    tl = raw.get("turn_levels")
    for rel, v in (tl.items() if isinstance(tl, dict) else ()):
        if rel not in out.turns or not isinstance(v, dict):
            continue
        keep = {}
        for k, db in v.items():
            try:
                k = int(k)
            except (TypeError, ValueError):
                continue
            if 2 <= k <= len(out.turns[rel]) + 1 and clean_level(db):
                keep[k] = clean_level(db)
        if keep:
            out.turn_levels[rel] = keep
    # PAD-638: a music mode's own files in turn, only for a mode the slot has a file for
    mt = raw.get("mode_turns")
    for rel, by in (mt.items() if isinstance(mt, dict) else ()):
        if rel not in out.slots or not isinstance(by, dict):
            continue
        for m, files in by.items():
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            keep = [f for f in (files if isinstance(files, (list, tuple)) else ())
                    if isinstance(f, str) and f.strip()][:TURN_MAX - 1]
            if m in out.slots[rel] and keep:
                out.mode_turns.setdefault(rel, {})[m] = keep
    mr = raw.get("mode_random")
    for rel, ms in (mr.items() if isinstance(mr, dict) else ()):
        keep = set()
        for m in (ms if isinstance(ms, (list, tuple)) else ()):
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            if m in (out.mode_turns.get(rel) or {}):
                keep.add(m)
        if keep:
            out.mode_random[rel] = keep
    ml = raw.get("mode_turn_levels")
    for rel, by in (ml.items() if isinstance(ml, dict) else ()):
        for m, v in (by.items() if isinstance(by, dict) else ()):
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            files = (out.mode_turns.get(rel) or {}).get(m)
            if not files or not isinstance(v, dict):
                continue
            keep = {}
            for k, db in v.items():
                try:
                    k = int(k)
                except (TypeError, ValueError):
                    continue
                if 2 <= k <= len(files) + 1 and clean_level(db):
                    keep[k] = clean_level(db)
            if keep:
                out.mode_turn_levels.setdefault(rel, {})[m] = keep
    attract = raw.get("attract")
    if isinstance(attract, (list, tuple)):
        out.attract = [f for f in attract if isinstance(f, str) and f.strip()][:ATTRACT_MAX]
    out.attract_gap = clean_gap(raw.get("attract_gap")) if out.attract else 0
    levels = raw.get("levels")
    if not isinstance(levels, dict):
        out.levels = None
        return out
    for rel, files in levels.items():
        if rel in out.slots and isinstance(files, dict):
            keep = {m: v for m, v in _modes_of(files, clean_level).items() if m in out.slots[rel]}
            if keep:
                out.levels[rel] = keep
    return out


def to_json(modes):
    """The sidecar value for *modes* (``None`` when there is nothing to keep)."""
    names = [n for n in modes.names]
    while names and not str(names[-1] or "").strip():
        names.pop()
    if not modes.slots and not names and not modes.turns and not modes.attract:
        return None
    out = {"names": names,
           "slots": {rel: {str(m): f for m, f in sorted(files.items())}
                     for rel, files in sorted(modes.slots.items()) if files}}
    if modes.turns:
        out["turns"] = {rel: list(files) for rel, files in sorted(modes.turns.items()) if files}
        rnd = sorted(rel for rel in modes.random if modes.turns.get(rel))
        if rnd:
            out["random"] = rnd
        tl = {rel: {str(k): int(db) for k, db in sorted(v.items()) if db}
              for rel, v in sorted(modes.turn_levels.items()) if modes.turns.get(rel)}
        tl = {rel: v for rel, v in tl.items() if v}
        if tl:
            out["turn_levels"] = tl
    mt = {rel: {str(m): list(f) for m, f in sorted(by.items()) if f and m in (modes.slots.get(rel) or {})}
          for rel, by in sorted(modes.mode_turns.items())}
    mt = {rel: by for rel, by in mt.items() if by}
    if mt:
        out["mode_turns"] = mt
        mr = {rel: sorted(str(m) for m in ms if str(m) in mt.get(rel, {}))
              for rel, ms in sorted(modes.mode_random.items())}
        mr = {rel: ms for rel, ms in mr.items() if ms}
        if mr:
            out["mode_random"] = mr
        ml = {rel: {str(m): {str(k): int(db) for k, db in sorted(v.items()) if db}
                    for m, v in sorted(by.items()) if str(m) in mt.get(rel, {})}
              for rel, by in sorted(modes.mode_turn_levels.items())}
        ml = {rel: {m: v for m, v in by.items() if v} for rel, by in ml.items()}
        ml = {rel: by for rel, by in ml.items() if by}
        if ml:
            out["mode_turn_levels"] = ml
    if modes.attract:
        out["attract"] = list(modes.attract)
        if modes.attract_gap:
            out["attract_gap"] = int(modes.attract_gap)
    if modes.levels is not None:
        out["levels"] = {rel: {str(m): int(db) for m, db in sorted(v.items()) if db}
                         for rel, v in sorted(modes.levels.items()) if any(v.values())}
    return out


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


#: PAD-565: ``PAD_STERN_TURNS_ANY=1`` offers the sounds in turn on every build whose port names
#: ``sound_lookup``, proven or not: the proof sweep builds each one with it before it is listed in
#: :data:`TURN_PROVEN`
TURNS_ANY_ENV = "PAD_STERN_TURNS_ANY"


def turns_any():
    return os.environ.get(TURNS_ANY_ENV) == "1"


#: PAD-724: ``PAD_STERN_MODES_ANY=1`` offers the music modes (and :mod:`.editions` EDITION) on every
#: build whose port names ``sound_resolve`` and whose menu takes the setting, proven or not: the proof
#: sweep builds each one with it before it is listed in :data:`PROVEN`
MODES_ANY_ENV = "PAD_STERN_MODES_ANY"


def modes_any():
    return os.environ.get(MODES_ANY_ENV) == "1"


#: PAD-641: what the runtime needs of a build's port for the flipper buttons' sounds in attract: the
#: framework's switch drain (the presses), the game's record lookup (the swap) and its sound play
ATTRACT_SITES = ("switch_edge", "switch_drain", "sound_lookup", "sound_play")
#: PAD-645: the builds whose sound bank the app reads without each record's play key (TMNT Pro 1.58:
#: the codec's validated path, 2053 records, none with a key; TMNT LE 1.58's bank does not derive),
#: so no request can be told the record it plays and nothing can carry the flipper buttons' sounds
ATTRACT_NO_KEYS = frozenset({"turtles_pro-1.58", "turtles_le-1.58"})
ATTRACT_VALUES = ("switch_drain_size", "switch_record_size", "switch_level_at", "switch_flags_at",
                  "switch_polarity_at")
ATTRACT_DATA = ("switch_records", "mode_mask")


def attract_refusal(prof):
    """PAD-641: why ``prof``'s build cannot play the flipper buttons' sounds in attract, or ``""``:
    it needs a port with the switch drain, the record lookup and the sound play. Its carrier is a
    request the game never plays (:func:`.mode_sounds.carriers`) or, on a build none was measured
    on (PAD-645: an older or a locally derived build), a call read off its own play tables when
    it is built (:func:`.mode_sounds.own_calls`)."""
    if prof is None:
        return NO_TITLE_ATTRACT
    if title_key(prof) in ATTRACT_NO_KEYS:
        return NO_ATTRACT % (prof.label, "the app cannot tell which of its sound records each of its "
                             "sounds plays")
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except OSError:
        return NO_ATTRACT % (prof.label, "the app has no map of its game program")
    if any(x not in port["site"] for x in ATTRACT_SITES) or any(
            x not in port.get("data", {}) for x in ATTRACT_DATA) or any(
            x not in port.get("value", {}) for x in ATTRACT_VALUES):
        return NO_ATTRACT % (prof.label, "the app has not found where its game program reads the "
                             "switches or looks its sounds up")
    return ""


def offer_attract(project, probe=True):
    """PAD-641: why the project's game cannot give its flipper buttons sounds in attract (``""``
    when it can)."""
    if not enabled():
        return "%s=0 leaves the flipper buttons' sounds in attract out of this app." % GATE_ENV
    return attract_refusal(project_title(project, probe=probe))


_FLIPPER_BUTTON = re.compile(r"^(LEFT|L|RIGHT|R) FLIPPER BUTTON$")


def flipper_buttons(game_elf):
    """PAD-641: the switch ids of the left and right flipper buttons in the game program
    *game_elf* (bytes), by the game's own switch names ("LEFT FLIPPER BUTTON", "R FLIPPER
    BUTTON"; never an upper flipper's), ``[]`` when its switch table cannot be read. Every Spike 2
    build in the image library names them so (69 of 69, 2026-10-20)."""
    from . import portgen as G
    from . import portswitch as PS
    try:
        sws = PS.switches(G.Elf(bytes(game_elf)))
    except (G.PortgenError, ValueError, struct.error, IndexError):
        return []
    out = []
    for side in ("L", "R"):
        for sw in sws:
            m = _FLIPPER_BUTTON.match(" ".join(str(sw["name"]).upper().split()))
            if m and m.group(1)[0] == side:
                out.append(int(sw["id"]))
                break
    return out


def title_refusal(prof, turns=False):
    """Why no sound of ``prof``'s title can have mode files (*turns*: files in turn, PAD-565: the
    record lookup, not the resolver), or ``""``."""
    if prof is None:
        return NO_TITLE if not turns else NO_TITLE.replace("give it a MUSIC MODE",
                                                           "play its sounds in turn")
    if not turns and title_key(prof) in _MS.NO_ROOM:
        return NO_ROOM % prof.label
    if title_key(prof) not in (TURN_PROVEN if turns else PROVEN) and not (turns_any() if turns else modes_any()):
        return (NOT_PROVEN_TURNS if turns else NOT_PROVEN) % prof.label
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except OSError:
        return (NOT_PROVEN_TURNS if turns else NOT_PROVEN) % prof.label
    if ("sound_lookup" if turns else "sound_resolve") not in port["site"]:
        return (NOT_PROVEN_TURNS if turns else NOT_PROVEN) % prof.label
    return ""


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None (:func:`.clip_variants.project_title`).
    PAD-565: with *probe*, a build no port was shipped for gets one derived now from the card's
    game program (:func:`.title_reader.read_card`, as the Modes tab's read does), so the sounds in
    turn reach every Spike 2 build, not only the ones a person opened the Modes tab on."""
    from .clip_variants import project_title as _pt
    prof = _pt(project, probe=probe)
    if prof is not None or not probe:
        return prof
    from . import mode_project as MP
    try:
        card = MP.project_card(project)
        if card is None or not card.game_dir or not card.image or not os.path.isfile(card.image):
            return None
        from .title_reader import read_card
        if not read_card(card.image).port_path:
            return None
        return MP.profile_for_card(card.game_dir, card.version)
    except Exception:                                   # noqa: BLE001 - no port to be had: no title
        return None


def offer_turns(project, rels, probe=True):
    """PAD-565: :func:`offer` for the sounds in turn."""
    if not enabled():
        return ("%s=0 leaves sounds in turn out of this app." % GATE_ENV), {}
    prof = project_title(project, probe=probe)
    why = title_refusal(prof, turns=True)
    if why:
        return why, {}
    return "", {rel: ("" if slot_idx(rel) is not None else NOT_SOUND_TURN) for rel in rels}


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
    # not keyed on the mode: one file in several modes of a slot is one conversion (and one record)
    key = hashlib.md5(json.dumps([os.path.abspath(src), st.st_size, st.st_mtime_ns,
                                  os.path.abspath(pristine), sp.st_size, sp.st_mtime_ns, rel]
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
        log("%s: %s (%s) made into the slot's format%s." % (
            who(mode), os.path.basename(src), what(rel, mode), " (%s)" % why if why else ""), "info")
    return out


def cut(wav, frames):
    """*wav* (a converted PCM WAV) cut to its first *frames* card samples (44.1 kHz), as a copy
    beside it, kept while it is there. Returns the copy's path."""
    import wave
    out = "%s.cut%d.wav" % (os.path.splitext(wav)[0], int(frames))
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return out
    with wave.open(wav, "rb") as r:
        params = r.getparams()
        n = int(round(int(frames) * r.getframerate() / 44100.0))
        data = r.readframes(min(n, r.getnframes()))
    tmp = out + ".part"
    with wave.open(tmp, "wb") as w:
        w.setparams(params)
        w.writeframes(data)
    os.replace(tmp, out)
    return out


# ---- the runtime's table ------------------------------------------------------------------------
def cfg_text(live, count, sounds, only, record=(), turns=(), bsids=(), tsids=(), randoms=(),
             attract=None, jukebox=None):
    """``sounds.cfg``: *live* the setting's value address, *count* the modes (0: no MUSIC MODE,
    the card has sounds in turn only), *sounds* ``[(mode, sound id, descriptor bytes)]`` (a
    *only* when the card carries no modes, *turns* ``[(k, slot key, file k's key)]`` the sounds in
    turn (PAD-565: ``turn`` lines, the record keys the runtime swaps at the game's lookup).
    PAD-608: *bsids* ``[(mode, sound id, bank sound id)]`` and *tsids* ``[(k, slot key, sound id,
    bank sound id)]``, the files in a sound bank (``bsid`` / ``tsid`` lines: the runtime points the
    game's requests at the bank's id). PAD-638: *randoms* the slot keys whose files play at random
    (``random`` lines).
    PAD-553: *record* (:func:`card_record`) goes in as comment lines the runtime skips, so an
    extract of the card brings the modes back (:func:`read_card_record`).
    PAD-641: *attract* ``{"request", "key", "switches": [id, ...], "files": [(key, ms), ...]}``, the
    flipper buttons' sounds in attract: an ``attract`` line (the carrier, its own record's key, the
    buttons' switch ids) and an ``afile`` line per file (its record's key, its length in ms);
    PAD-645: and with ``"quiet"`` (a silent record's key) an ``aquiet`` line: the game's own sound
    at a press plays it instead.
    PAD-685: *jukebox* ``{"modes": [(start site, [intro clip names], [record keys])], "songs":
    [(weight, record key, clip name or "")]}``, a ``jmode`` line per song mode and a ``jsong`` line per
    song (pad_mode_runtime.c "the jukebox")."""
    lines = ["# PAD-494 music modes: the operator's MUSIC MODE picks which descriptor each sound id plays"]
    if only:
        lines.append("only")
    if count:
        lines.append("setting\t0x%08x\t%d" % (int(live), int(count)))
    for mode, sid, desc in sounds:
        lines.append("sound\t%d\t%d\t%s" % (int(mode), int(sid), bytes(desc).hex()))
    for k, slot, host in turns:
        lines.append("turn\t%d\t%s\t%s" % (int(k), bytes(slot).hex(), bytes(host).hex()))
    for mode, sid, bank in bsids:
        lines.append("bsid\t%d\t%d\t%d" % (int(mode), int(sid), int(bank)))
    for k, slot, sid, bank in tsids:
        lines.append("tsid\t%d\t%s\t%d\t%d" % (int(k), bytes(slot).hex(), int(sid), int(bank)))
    for slot in randoms:
        lines.append("random\t%s" % bytes(slot).hex())
    if attract and attract.get("files"):
        lines.append("attract\t%d\t%s\t%s" % (int(attract["request"]), bytes(attract["key"]).hex(),
                                               ",".join(str(int(i)) for i in attract["switches"])))
        for k, (key, ms) in enumerate(attract["files"], 1):
            lines.append("afile\t%d\t%s\t%d" % (k, bytes(key).hex(), int(ms)))
        if attract.get("quiet"):
            lines.append("aquiet\t%s" % bytes(attract["quiet"]).hex())
        if attract.get("gap_ms"):
            lines.append("agap\t%d" % int(attract["gap_ms"]))      # PAD-641 round 2
    if jukebox and jukebox.get("modes") and jukebox.get("songs"):
        for site, clips, keys in jukebox["modes"]:
            lines.append("jmode\t%s\t%s\t%s" % (site or "-", ",".join(clips) or "-",
                                                 ",".join(bytes(k).hex() for k in keys)))
        for weight, key, clip in jukebox["songs"]:
            lines.append("jsong\t%d\t%s\t%s" % (int(weight), bytes(key).hex(), clip or "-"))
    lines += list(record)
    return "\n".join(lines) + "\n"


# ---- the card's record (PAD-553) ----------------------------------------------------------------
#: the comment lines of ``sounds.cfg`` that say what the project gave the card: a mode's name
#: (``#mode <m> <name>``) and a slot's file for a mode (``#file <m> <slot idx> <record idx> <dB or
#: -> <slot rel> <the file's own name>``), TAB-separated. The runtime skips every ``#`` line.
REC_MODE, REC_FILE = "#mode", "#file"
#: PAD-565: a slot's file in turn: ``#turn <k> <slot idx> <record idx> <dB or -> <slot rel>
#: <the file's own name>``
REC_TURN = "#turn"
#: PAD-638: a slot whose files in turn play at random: ``#random <slot idx> <slot rel>``
REC_RANDOM = "#random"
#: PAD-638: music mode m's own file k in turn: ``#mturn <m> <k> <slot idx> <record idx> <dB or ->
#: <slot rel> <the file's own name>``; and ``#mrandom <m> <slot idx> <slot rel>`` when they play at
#: random
REC_MTURN, REC_MRANDOM = "#mturn", "#mrandom"
#: PAD-641: a flipper button sound in attract: ``#attract <k> <slot idx> <record idx> - <slot rel>
#: <the file's own name>`` (the slot is the carrier's)
REC_ATTRACT = "#attract"
#: PAD-641 round 2: the time between two of them: ``#agap <seconds>``
REC_AGAP = "#agap"
#: PAD-685: a jukebox song: ``#jsong <k> <slot idx> <record idx> <weight> <slot rel> <the file's own
#: name>`` (its intro clip, when it has one, is in the video bank as ``jukebox.clip_name(k)``)
REC_JSONG = "#jsong"
#: PAD-608: a file in a sound bank names its record as ``<bank category>:<record idx>`` (an app
#: before PAD-608 skips such a line: its record field is not a number)
_BANK_HOST = re.compile(r"^(\d{1,2}):(\d+)$")


def _rec_host(u):
    """The record field of a used entry *u*: ``<bank>:<record>`` for a file in a sound bank."""
    if u.get("bank") is not None and u.get("bank_idx") is not None:
        return "%d:%d" % (int(u["bank"]), int(u["bank_idx"]))
    return str(int(u["host"]))


def _read_host(text):
    """``(record idx, bank category or None)`` of a record field (:func:`_rec_host`)."""
    m = _BANK_HOST.match(text.strip())
    if m:
        return int(m.group(2)), int(m.group(1))
    return int(text), None


def _rec_word(text):
    """*text* as one field of a record line: no TAB or line break in it."""
    return re.sub(r"[\t\r\n]+", " ", str(text or "")).strip()


def card_record(modes, used):
    """The record lines for a card built with *modes* (a :class:`Modes`): every mode's name, and
    for every file that landed (*used*, the engine's entries: ``rel``, ``slot``, ``mode``,
    ``host``, ``db`` and ``lines``, how many sound ids play it) the record holding it (PAD-608:
    ``bank`` and ``bank_idx`` for one in a sound bank)."""
    out = ["# PAD-553 what the project gave the card, for an extract of it to bring back"]
    out += ["%s\t%d\t%s" % (REC_MODE, m, _rec_word(modes.name(m))) for m in range(1, modes.count + 1)]
    for u in used:
        if not u.get("lines"):
            continue
        m = int(u["mode"])
        if is_juke(m):
            k = turn_of(m)
            src = modes.jukebox[k - 1] if 0 < k <= len(modes.jukebox) else ""
            box = (modes.juke_plan or {}).get("box")
            weight = box.songs[k - 1].weight if box is not None and 0 < k <= len(box.songs) else 2
            out.append("\t".join([REC_JSONG, str(k), str(int(u["slot"])), _rec_host(u), str(int(weight)),
                                  _rec_word(u["rel"]),
                                  _rec_word(os.path.basename(str(src).replace("\\", "/")))]))
            continue
        if is_attract(m):
            k = attract_of(m)
            if k == ATTRACT_QUIET:                  # the build's own silence: nothing to bring back
                continue
            src = modes.attract[k - 1] if 0 < k <= len(modes.attract) else ""
            out.append("\t".join([REC_ATTRACT, str(k), str(int(u["slot"])), _rec_host(u), "-",
                                  _rec_word(u["rel"]),
                                  _rec_word(os.path.basename(str(src).replace("\\", "/")))]))
            continue
        if is_mode_turn(m):
            mm, k = mode_turn_of(m)
            files = (modes.mode_turns.get(u["rel"]) or {}).get(mm) or []
            src = files[k - 2] if 0 <= k - 2 < len(files) else ""
            db = u.get("db")
            out.append("\t".join([REC_MTURN, str(mm), str(k), str(int(u["slot"])), _rec_host(u),
                                  "-" if db is None else str(int(db)), _rec_word(u["rel"]),
                                  _rec_word(os.path.basename(str(src).replace("\\", "/")))]))
            continue
        if is_turn(m):
            files = modes.turns.get(u["rel"]) or []
            src = files[turn_of(m) - 2] if 0 <= turn_of(m) - 2 < len(files) else ""
        else:
            src = (modes.slots.get(u["rel"]) or {}).get(m, "")
        db = u.get("db")
        out.append("\t".join([REC_TURN if is_turn(m) else REC_FILE,
                               str(turn_of(m) if is_turn(m) else m), str(int(u["slot"])), _rec_host(u),
                              "-" if db is None else str(int(db)), _rec_word(u["rel"]),
                              _rec_word(os.path.basename(str(src).replace("\\", "/")))]))
    landed = {u["rel"]: int(u["slot"]) for u in used if u.get("lines") and is_turn(u["mode"])
              and not is_mode_turn(u["mode"]) and not is_juke(u["mode"])}
    out += ["%s\t%d\t%s" % (REC_RANDOM, landed[rel], _rec_word(rel))
            for rel in sorted(modes.random) if rel in landed]
    mlanded = {(u["rel"], mode_turn_of(u["mode"])[0]): int(u["slot"]) for u in used
               if u.get("lines") and is_mode_turn(u["mode"])}
    out += ["%s\t%d\t%d\t%s" % (REC_MRANDOM, m, mlanded[(rel, m)], _rec_word(rel))
            for rel in sorted(modes.mode_random) for m in sorted(modes.mode_random[rel])
            if (rel, m) in mlanded]
    if modes.attract_gap and any(u.get("lines") and is_attract(u["mode"]) for u in used):
        out.append("%s\t%d" % (REC_AGAP, int(modes.attract_gap)))
    return out


def read_card_record(text):
    """``{"names": [...], "files": [{"mode", "slot", "host", "db", "rel", "name"}]}`` (and
    ``"turns"`` ``[{"turn", "slot", "host", "db", "rel", "name"}]`` when the card plays sounds in
    turn, PAD-565; ``"random"`` ``[{"slot", "rel"}]`` the slots of them that play at random,
    PAD-638; ``"attract"`` ``[{"k", "slot", "host", "rel", "name"}]`` when its flipper buttons
    play sounds in attract, PAD-641) from a card's ``sounds.cfg`` (*text*), or ``None``
    when it has no record (a card written before PAD-553). PAD-608: an entry whose file is in a
    sound bank has ``"bank"``, the bank's category, and ``"host"`` is the bank's record."""
    names, files, turns, rnd, attract, seen = {}, [], [], [], [], False
    mturns, mrnd, juke = [], [], []
    agap = 0
    for line in str(text or "").splitlines():
        f = line.split("\t")
        try:
            if f[0] == REC_MODE and len(f) >= 3:
                seen = True
                m = int(f[1])
                if 1 <= m <= MAX_MODES:
                    names[m] = f[2].strip()
            elif f[0] == REC_FILE and len(f) >= 6:
                seen = True
                m = int(f[1])
                if 2 <= m <= MAX_MODES:
                    host, bank = _read_host(f[3])
                    files.append(dict({"mode": m, "slot": int(f[2]), "host": host,
                                       "db": None if f[4] == "-" else (clean_level(f[4]) or 0),
                                       "rel": f[5], "name": f[6] if len(f) > 6 else ""},
                                      **({"bank": bank} if bank is not None else {})))
            elif f[0] == REC_TURN and len(f) >= 6:
                seen = True
                k = int(f[1])
                if 2 <= k <= TURN_MAX:
                    host, bank = _read_host(f[3])
                    turns.append(dict({"turn": k, "slot": int(f[2]), "host": host,
                                       "db": None if f[4] == "-" else (clean_level(f[4]) or 0),
                                       "rel": f[5], "name": f[6] if len(f) > 6 else ""},
                                      **({"bank": bank} if bank is not None else {})))
            elif f[0] == REC_RANDOM and len(f) >= 3:
                rnd.append({"slot": int(f[1]), "rel": f[2]})
            elif f[0] == REC_MTURN and len(f) >= 7:
                seen = True
                m, k = int(f[1]), int(f[2])
                if 2 <= m <= MAX_MODES and 2 <= k <= TURN_MAX:
                    host, bank = _read_host(f[4])
                    mturns.append(dict({"mode": m, "turn": k, "slot": int(f[3]), "host": host,
                                        "db": None if f[5] == "-" else (clean_level(f[5]) or 0),
                                        "rel": f[6], "name": f[7] if len(f) > 7 else ""},
                                       **({"bank": bank} if bank is not None else {})))
            elif f[0] == REC_MRANDOM and len(f) >= 4:
                mrnd.append({"mode": int(f[1]), "slot": int(f[2]), "rel": f[3]})
            elif f[0] == REC_ATTRACT and len(f) >= 6:
                seen = True
                k = int(f[1])
                if 1 <= k <= ATTRACT_MAX:
                    host, bank = _read_host(f[3])
                    attract.append(dict({"k": k, "slot": int(f[2]), "host": host, "rel": f[5],
                                         "name": f[6] if len(f) > 6 else ""},
                                        **({"bank": bank} if bank is not None else {})))
            elif f[0] == REC_AGAP and len(f) >= 2:
                agap = clean_gap(f[1])
            elif f[0] == REC_JSONG and len(f) >= 6:          # PAD-685
                seen = True
                juke.append({"k": int(f[1]), "slot": int(f[2]), "host": int(f[3]),
                             "weight": int(f[4]) if f[4].isdigit() else 2, "rel": f[5],
                             "name": f[6] if len(f) > 6 else ""})
        except ValueError:
            continue
    if not seen:
        return None
    top = max(list(names) + [0])
    out = {"names": [names.get(m, "") for m in range(1, top + 1)], "files": files}
    if turns:
        out["turns"] = turns
        if rnd:
            out["random"] = rnd
    if attract:
        out["attract"] = sorted(attract, key=lambda a: a["k"])
        if agap:
            out["attract_gap"] = agap
    if mturns:
        out["mode_turns"] = mturns
        if mrnd:
            out["mode_random"] = mrnd
    if juke:
        out["jukebox"] = sorted(juke, key=lambda j: j["k"])
    return out


def card_bank_records(rec):
    """``{bank category: {record idx, ...}}``: the records of the app's sound banks a card's record
    (:func:`read_card_record`) names (PAD-608: files in a sound bank), for an extract to decode."""
    out = {}
    for f in (list((rec or {}).get("files") or ()) + list((rec or {}).get("turns") or ())
              + list((rec or {}).get("attract") or ())):
        if f.get("bank") is not None:
            out.setdefault(int(f["bank"]), set()).add(int(f["host"]))
    return out
