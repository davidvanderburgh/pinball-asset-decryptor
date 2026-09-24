"""The game's OWN modes: their timers and awards, edited from the app (item 145).

WHAT A STOCK MODE IS. A mode a Spike 2 game shipped with is compiled C++ in the game ELF, not
a file: one ``cmode_*`` class per mode, and every number it uses either an instruction's
immediate, a literal-pool or ``.data`` word, an operator ADJUSTMENT (``get_adjustment``), or
something the code computes. Item 144 reads a title's modes off its ELF and writes them down
in a TABLE, one fact per line, in the grammar MODE_SDK.md sets out ("The game's own modes");
:mod:`.stock_mode_tables` carries the tables the app knows. This module is the app's side:

* :func:`parse` reads that grammar into :class:`Build` / :class:`Mode` / :class:`Number`;
* :class:`ElfImage` maps a VA to a file offset through the ELF's PT_LOAD headers;
* :func:`encode` / :func:`decode` turn a value into the word(s) of its kind and back
  (``imm`` an 8-bit value rotated, ``movw`` 16 bits, ``movwt`` a ``movw``+``movt`` pair on one
  register, ``lit`` / ``data`` a whole word);
* the STAGING, like the Defaults tab's: ``.staged_changes.json`` key ``stock_modes`` =
  ``{"build": "<game> <version>", "values": {"<mode id>.<key>": value}}`` for word rows,
  and an ADJUSTMENT row stages into Defaults' own ``settings`` key (one number, whichever tab
  set it);
* :func:`compute_writes`, called by the Write (``engine._compute_patches``) after the display
  text: the staged words written in place in the game ELF, and a project's staged table
  settings as their compiled defaults in the same ELF, handed back as a file overlay so
  the validator bypass - the last writer of the game ELF's ``.sidx`` record - digests the
  file that actually ships (the path ``progtext`` edits already take). Every Write path
  shares that patch set: the image Write, Direct SD and the emulator's override set.

WHERE THE LINES ARE. Only a ``word`` row is edited in place, and only when the card's words
at its VA(s) are the table's stock words, or the same instruction with another value in it (a
card this module wrote before). Anything else - a different build, a patched instruction, a
number the code computes (``code``), a scene - is refused and says why. A row put back to
stock writes the stock words back, byte for byte.

SHOTS AS DATA (item 159). Item 158 measured that a stock mode's LIT MASK (the ``initial_mask``
rows, the getter cmode's START stores) is not what two of Godzilla's modes play: tank attack
never reads it (its shots are a six-entry PATH table the tanks walk) and battle vs Ebirah
rebuilds it from its spin counts at every start. Item 159's desk audit found the same for six
more modes (their own start stores the field again). So:

* an ``initial_mask`` row carrying ``inert <why>`` is read-only, with the reason (``inline_copy``:
  cmode's START uses an inlined copy of the base getter; ``start_rewrites``: the mode's own start
  stores the field again). A stale staged value for such a row is never written; a card that
  holds an older app's edit of it still goes back to stock;
* three more kinds: ``path <va>`` (a 16-byte tank path entry ``{u64 position, u16 lamp, u16 id,
  u32 0}``, four words; the value is the position mask, the lamp and id are kept), ``qword
  <va>`` (a u64 data word pair) and ``insn <va>`` (an instruction that LOADS the number from
  elsewhere, ``ldr rd,[rn,#off]``; the table's value is what it loads, measured; a value of the
  app's own replaces the load with ``mov rd,#N`` on the same register, back to stock is the
  load word again);
* ``fixed <why>`` marks a path position that code also names (``seed``: tanks appear there,
  ``goal``: tanks head there): read-only, with the reason;
* ``follows path`` marks a row the Write keeps IN STEP with a mode's path rows (the counted-shots
  words, the spot list): never staged by itself, planned with the family (:func:`family_words`).
  A ``path`` row staged at 0 means NONE: the entry becomes a copy of its neighbour away from the
  goal, so the tanks' walk skips it (item 158 live-3, emulator-proven for position 4 of tank
  attack on Premium/LE 1.16).
"""

import hashlib
import json
import os
import re
import struct
from dataclasses import dataclass, field

#: the table format this module reads (MODE_SDK.md, "The table format (format 1)")
FORMAT = 1

#: kind -> how many tokens follow it
KIND_ARITY = {"imm": 1, "movw": 1, "movwt": 2, "lit": 1, "data": 1, "adj": 2, "code": 1,
              "path": 1, "qword": 1, "insn": 1}
#: kinds whose number is one or more words at VAs this module can rewrite
WORD_KINDS = ("imm", "movw", "movwt", "lit", "data", "path", "qword", "insn")
#: kinds whose words are INSTRUCTIONS (a skeleton + a value)
INSN_KINDS = ("imm", "movw", "movwt", "insn")
#: kinds whose one VA starts a run of several words (else: one word per VA)
WORD_COUNT = {"path": 4, "qword": 2}
#: ``uncertain``: one word the app could write, but what the game does with it isn't certain
#: (a value set on one path only, an undecoded field of the award record): read-only
CLASSES = ("word", "adjustment", "code", "scene", "uncertain")

#: why an ``inert`` initial_mask row does nothing in play (item 158 / 159, by its key)
INERT_REASONS = {
    "inline_copy": "the mode never reads its lit shots (its start keeps an inlined copy of the "
                   "game's default); what it plays are the tank positions below",
    "start_rewrites": "the mode rebuilds its lit shots when it starts, so this number never "
                      "reaches play",
}
#: why a ``fixed`` path position stays as it is
FIXED_REASONS = {
    "seed": "tanks appear at this position (its shot is a word in the game's code too), so it "
            "stays where it is",
    "goal": "every tank heads for this position (its shot is a word in the game's code too), so "
            "it stays where it is",
}
#: spinner bits the ports name only in a comment, by title (a spinner sends three bits a spin: the
#: game's own rules test the MIDDLE one, which the ports name as the shot; the tank path holds the
#: top spinner's FIRST bit 0x800, which no port names). A port name that collides with one of
#: these for another bit is told apart by :func:`shot_names`.
SPINNER_BITS = {"godzilla": {0x200: "Left spinner", 0x800: "Top spinner, first bit",
                             0x20000: "Shield ramp spinner"}}
#: shots the switches never send ALONE (item 158's census saw them with 0x1 in one mask): a
#: tank position must be a single bit the router dispatches by itself, so never these
NOT_ALONE = {"godzilla": {0x1000000000}}          # Big loop arrives as 0x1000000001


def word_count(kind, args):
    """How many words a row of *kind* with these VA args carries."""
    return WORD_COUNT.get(kind, len(args))

#: .staged_changes.json key for the staged word values
STAGE_KEY = "stock_modes"
#: Defaults' key: adjustment rows stage there, so both tabs edit one number
SETTINGS_KEY = "settings"


class StockModeError(ValueError):
    """A value that can't be staged or written, with the reason in words."""


# ---- the table -----------------------------------------------------------------------------
@dataclass
class Mode:
    id: int
    cls: str
    obj: int = 0
    vtable: int = 0
    title_msg: object = None           # msg id or None
    starts: list = field(default_factory=list)
    label: str = ""                    # the table's own name for the mode (``name Drive_My_Car``)

    @property
    def name(self):
        """``cmode_battle_vs_ebirah`` -> ``Battle vs Ebirah``; a table's own name when it
        gives one, its contractions spelled with their apostrophe (``It Wont Be Long`` ->
        ``It Won't Be Long``: a name read from an audit's constant has lost it)."""
        if self.label:
            return _apostrophes(self.label.replace("_", " "))
        words = self.cls[6:] if self.cls.startswith("cmode_") else self.cls
        out = []
        for w in words.split("_"):
            if not w:
                continue
            out.append(w if w in ("vs", "and", "of", "the", "mb") and out else w.capitalize())
        return " ".join(out).replace(" mb", " Multiball")


#: contractions a name read from a constant (``AUD_IT_WONT_BE_LONG_STARTED``) has lost the
#: apostrophe of; only words that are never anything else
_CONTRACTIONS = {w.replace("'", ""): w for w in (
    "won't", "don't", "can't", "isn't", "aren't", "ain't", "doesn't", "didn't", "wasn't",
    "weren't", "couldn't", "shouldn't", "wouldn't", "haven't", "hasn't", "you're", "they're",
    "we're", "i'm", "you've", "i've", "we've", "they've", "you'll", "we'll", "they'll",
    "let's", "that's", "what's", "there's", "rock'n'roll")}


def _apostrophes(name):
    """``It Wont Be Long`` -> ``It Won't Be Long``, keeping each word's capitals."""
    def fix(m):
        w = m.group(0)
        right = _CONTRACTIONS.get(w.lower())
        if right is None:
            return w
        out = right
        if w[:1].isupper():
            out = out[:1].upper() + out[1:]
        if w.isupper() and len(w) > 1:
            out = out.upper()
        return out
    return re.sub(r"[A-Za-z]+", fix, name)


@dataclass
class Number:
    mode_id: int
    key: str
    value: object                      # int, or None for "?"
    kind: str
    args: tuple                        # the kind's tokens (VAs as ints; adj: name, id)
    words: tuple                       # stock words as ints ((), for "-")
    klass: str
    shared: int = 0
    seen: str = ""
    comment: str = ""
    extra: dict = field(default_factory=dict)     # the other trailing tokens (inert, fixed, follows)

    @property
    def row_key(self):
        return "%d.%s" % (self.mode_id, self.key)

    @property
    def inert(self):
        """The reason key when the row does nothing in play (an ``inert`` token), else ''."""
        return str(self.extra.get("inert") or "")

    @property
    def fixed(self):
        """The reason key when a path position stays as it is (a ``fixed`` token), else ''."""
        return str(self.extra.get("fixed") or "")

    @property
    def follows(self):
        """The family this row is kept in step with (a ``follows`` token), else ''."""
        return str(self.extra.get("follows") or "")

    @property
    def path_index(self):
        """``path.3`` -> 3; None for any other key."""
        m = re.match(r"^path\.(\d+)$", self.key)
        return int(m.group(1)) if m else None

    @property
    def vas(self):
        return tuple(self.args) if self.kind in WORD_KINDS else ()

    @property
    def adj_name(self):
        return self.args[0] if self.kind == "adj" else ""

    @property
    def adj_range(self):
        """``(min, max)`` from the row's comment (``range 30..70``), or None."""
        m = re.search(r"range\s+(-?\d+)\s*\.\.\s*(-?\d+)", self.comment or "")
        return (int(m.group(1)), int(m.group(2))) if m else None

    @property
    def is_word(self):
        return self.klass == "word" and self.kind in WORD_KINDS and self.value is not None

    @property
    def is_adjustment(self):
        return self.klass == "adjustment" and self.kind == "adj" and self.value is not None

    @property
    def range_inverted(self):
        """The game ships a few settings whose minimum is above their maximum (Godzilla Pro
        1.15's AD_MONSTER_ISLAND_MADNESS_TIMER: 90..60). No value passes the game's own
        range check, so the Defaults write refuses them; so does this tab."""
        rng = self.adj_range
        return bool(rng) and rng[0] > rng[1]

    @property
    def words_agree(self):
        """The row's stock words hold its value the way its kind says (a row that doesn't is
        never written: the app would be guessing at the instruction). An ``insn`` row's stock
        word LOADS its value from elsewhere (the value is measured, not in the word): it agrees
        when the word is that load."""
        if self.kind == "insn":
            return len(self.words) == 1 and _is_ldr_imm(self.words[0])
        return self.kind not in WORD_KINDS or decode(self.kind, self.words) == self.value

    @property
    def editable(self):
        if self.inert or self.fixed or self.follows:
            return False
        return (self.is_word and self.words_agree) or (self.is_adjustment and not self.range_inverted)

    def why_read_only(self):
        """Why a person can't change this number here ('' when they can)."""
        if self.editable:
            return ""
        if self.inert:
            return INERT_REASONS.get(self.inert, "the game never uses this number in play")
        if self.fixed:
            return FIXED_REASONS.get(self.fixed, "it stays as it is")
        if self.follows:
            return ("the Write keeps it in step with the %s rows, so it isn't set by itself"
                    % self.follows)
        if self.is_word and not self.words_agree:
            return ("the table's words for it (%s) don't hold %s the way a '%s' number does" % (
                ",".join("%08x" % w for w in self.words), format(self.value, ","), self.kind))
        if self.is_adjustment and self.range_inverted:
            return ("the game's own range for this setting is %d to %d (the minimum is above the "
                    "maximum), so no default can be written for it" % self.adj_range)
        if self.klass == "uncertain":
            why = (self.comment or "").split(";")[0].strip()
            return ("it is one word in the game program, but the app can't be sure what the "
                    "game does with it%s" % (" (%s)" % why if why else ""))
        if self.klass == "code" or self.kind == "code":
            return ("the game computes it in code (not one word), so it can only change "
                    "with a hook or a code cave")
        if self.klass == "scene":
            return "it lives in a scene file, not in the game program"
        if self.value is None:
            return "its value hasn't been measured"
        if self.kind not in KIND_ARITY:
            return "this app doesn't know how to write a '%s' number" % self.kind
        return "it isn't one word the app can change in place"

    @property
    def label(self):
        """What the number is, in words: ``start.caward_add#2`` -> ``Start award (2)``."""
        if self.is_adjustment or self.kind == "adj":
            from .adjustments import _label_from_name
            return _label_from_name(self.adj_name)
        # a repeat in one mode is '@2' (format 1 as published) or '#2' (the first draft)
        base, rep = re.match(r"^(.*?)(?:[@#](\d+))?$", self.key).groups()
        rep = rep or ""
        role, _dot, call = base.partition(".")
        if role == "timer":
            shown = call or "?"
            if shown.endswith(".ctor"):         # 144: the constant the mode's constructor stores
                shown = "start value"           # fits the tab's Number column
            return "Timer (%s)%s" % (shown, (" (%s)" % rep) if rep else "")
        if role == "path":                      # item 159: a tank position, or what follows it
            if call.isdigit():
                return "Position %d" % (int(call) + 1)
            if call.startswith("counted"):
                return "Counted shots (%s)" % (call.partition(".")[2] or "?")
            if call.startswith("spot."):
                return "Spot list entry %s" % call.partition(".")[2]
        if role == "spins":
            return "%s spinner spins" % {"left": "Left", "top": "Top",
                                         "shield": "Shield ramp"}.get(call, call.capitalize())
        role_word = {"start": "Start", "shot": "Shot", "end": "End", "stop": "Stop",
                     "timer": "Timer", "reset": "Reset", "ball_end": "Ball end",
                     "start_display": "Start display", "total_display": "Total display"}.get(
            role, role.replace("_", " ").capitalize())
        if re.fullmatch(r"v\d+", role):
            role_word = "Other"                 # a slot whose role the reader didn't name
        if call == "award_value":
            what = "award value"
        elif call.startswith("caward_add_scaled"):
            what = "award multiplier" if call.endswith(".mult") else "scaled award"
        elif call.startswith("caward_add") or call.startswith("score_add"):
            what = "award"
        elif call.startswith("ctimer") or call.startswith("timer"):
            what = "timer"
        elif not call:
            return self.key.replace("_", " ").capitalize()
        else:
            what = call.replace("_", " ").replace(".", " ")
        return "%s %s%s" % (role_word, what, (" (%s)" % rep) if rep else "")

    @property
    def is_player_facing(self):
        """An award, a timer or an adjustment: what the Modes tab lists. Message ids,
        audits, events and show ids stay in the table, not on the tab."""
        if self.kind == "adj" or self.klass == "adjustment":
            return True
        call = self.key.partition("#")[0].partition(".")[2]
        role = self.key.partition(".")[0]
        if role in ("path", "spins"):           # item 159: what a mode really plays
            return not self.follows
        return (call.startswith(("caward_add", "score_add", "award_value", "ctimer"))
                or role == "timer")

    def where_text(self):
        """Where the number lives, for a person (the Modes tab's column)."""
        if self.kind == "adj":
            return "operator setting %s" % self.adj_name
        if self.kind in WORD_KINDS:
            n = len(self.args)
            what = {"imm": "an instruction", "movw": "an instruction",
                    "movwt": "two instructions", "lit": "a literal word",
                    "data": "a data word", "path": "a 16-byte path entry",
                    "qword": "a data word pair", "insn": "an instruction"}[self.kind]
            return "game program, %s at 0x%x%s" % (
                what if n == 1 or self.kind == "movwt" else "%d words" % n, self.args[0],
                ", shared by %d" % self.shared if self.shared else "")
        if self.kind == "code":
            return "computed in code at 0x%x" % self.args[0] if self.args else "computed in code"
        return self.where()

    def where(self):
        """Where the number lives, in the table's own words."""
        if self.kind == "adj":
            return "adjustment %s" % self.adj_name
        if self.kind in WORD_KINDS or self.kind == "code":
            return "%s %s" % (self.kind, " ".join("0x%x" % v for v in self.args))
        return self.kind


@dataclass
class Build:
    game: str
    version: str
    sha1: str
    modes: dict = field(default_factory=dict)       # id -> Mode
    numbers: list = field(default_factory=list)     # [Number]

    @property
    def id(self):
        return "%s %s" % (self.game, self.version)

    def number(self, row_key):
        for n in self.numbers:
            if n.row_key == row_key:
                return n
        return None

    def mode_name(self, mode_id):
        m = self.modes.get(mode_id)
        return m.name if m else "Mode %d" % mode_id

    def row_label(self, number):
        """The number's label without its mode's name in front (the tab shows the mode in
        its own column): ``Battle Vs Ebirah Timer`` under Battle vs Ebirah -> ``Timer``, and
        ``Mode Drive My Car Timer`` under Drive My Car -> ``Timer``."""
        label = number.label
        mode = self.mode_name(number.mode_id)
        for head in (mode, "mode " + mode):
            if label.lower().startswith(head.lower() + " "):
                rest = label[len(head) + 1:]
                return rest[:1].upper() + rest[1:]
        return label

    def adjustment_numbers(self):
        """``{AD_NAME: Number}`` - the first row naming each adjustment."""
        out = {}
        for n in self.numbers:
            if n.is_adjustment and n.adj_name not in out:
                out[n.adj_name] = n
        return out

    def same_title(self, game, version):
        return game == self.game and version_key(version) == version_key(self.version)


def version_key(v):
    """``"1.15.0"``, ``"1.15"`` -> ``(1, 15)``: trailing zero parts don't count."""
    parts = [int(p) for p in re.findall(r"\d+", str(v or ""))]
    while parts and parts[-1] == 0 and len(parts) > 1:
        parts.pop()
    return tuple(parts)


def _int(tok):
    return int(tok, 0)


def parse(text):
    """The table text -> ``[Build]``. Raises :class:`StockModeError` naming the line when a
    line can't be read; a line kind this format doesn't know is skipped (a later format's
    facts don't break an older reader)."""
    builds = []
    cur = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        # A comment's '#' starts the line or follows a space; the '#2' of a repeated key
        # (``start.caward_add#2``) follows a letter and is part of the key.
        m = re.search(r"(?:^|\s)#", raw)
        line, comment = (raw[:m.start()], raw[m.end():]) if m else (raw, "")
        tok = line.split()
        if not tok:
            continue
        what = tok[0]
        try:
            if what == "build":
                if len(tok) < 5 or tok[3] != "sha1":
                    raise StockModeError("a build line is 'build <game> <version> sha1 <hex>'")
                cur = Build(tok[1], tok[2], tok[4].lower())
                builds.append(cur)
                continue
            if cur is None:
                raise StockModeError("a '%s' line before any build line" % what)
            if what == "mode":
                mid = int(tok[1])
                mode = Mode(mid, tok[2])
                kv = dict(zip(tok[3::2], tok[4::2]))
                mode.obj = _int(kv["obj"]) if kv.get("obj", "?") != "?" else 0
                mode.vtable = _int(kv["vtable"]) if kv.get("vtable", "?") != "?" else 0
                tm = kv.get("title_msg", "?")
                mode.title_msg = None if tm == "?" else int(tm)
                if kv.get("name", "?") != "?":
                    mode.label = kv["name"]
                cur.modes[mid] = mode
            elif what == "start":
                mid = int(tok[1])
                if mid in cur.modes:
                    cur.modes[mid].starts.append(" ".join(tok[2:]))
            elif what == "number":
                cur.numbers.append(_parse_number(tok, comment.strip()))
            # ctor / callout / scene / clip / lights / shots: facts the editor doesn't use
        except StockModeError as e:
            raise StockModeError("line %d: %s" % (lineno, e)) from None
        except (IndexError, ValueError, KeyError) as e:
            raise StockModeError("line %d: can't read %r (%s)" % (lineno, raw.strip(), e)) from None
    return builds


def _parse_number(tok, comment):
    if len(tok) < 5:
        raise StockModeError("a number line needs id, key, value and kind")
    mid, key, value, kind = int(tok[1]), tok[2], tok[3], tok[4]
    value = None if value == "?" else int(value.replace(",", ""), 0)
    rest = tok[5:]
    if kind in KIND_ARITY:
        n = KIND_ARITY[kind]
        args, rest = rest[:n], rest[n:]
        if len(args) < n:
            raise StockModeError("kind %s takes %d token(s)" % (kind, n))
        # one number the game keeps at several sites: more VAs of the same kind follow
        while kind in WORD_KINDS and len(rest) > 2 and rest[0].lower().startswith("0x"):
            more, rest = rest[:n], rest[n:]
            if len(more) < n or not all(t.lower().startswith("0x") for t in more):
                raise StockModeError("kind %s takes its VAs %d at a time" % (kind, n))
            args = args + more
        if kind == "adj":
            args = (args[0], int(args[1], 0))
        else:
            args = tuple(_int(a) for a in args)
    else:
        # an unknown kind: its arity is unknown, so find the class token from the end
        ci = max((i for i, t in enumerate(rest) if t in CLASSES), default=None)
        if ci is None or ci == 0:
            raise StockModeError("unknown kind %r and no class token" % kind)
        args, rest = tuple(rest[:ci - 1]), rest[ci - 1:]
    if len(rest) < 2:
        raise StockModeError("a number line ends '<words> <class>'")
    words_tok, klass, extra = rest[0], rest[1], rest[2:]
    words = () if words_tok == "-" else tuple(int(w, 16) for w in words_tok.split(","))
    if kind in WORD_KINDS and kind in KIND_ARITY and len(words) != word_count(kind, args):
        raise StockModeError("%s needs %d word(s), the line has %d"
                             % (kind, word_count(kind, args), len(words)))
    shared, seen = 0, ""
    kv = dict(zip(extra[0::2], extra[1::2]))
    if "shared" in kv:
        shared = int(kv.pop("shared"))
    if "seen" in kv:
        seen = kv.pop("seen")
    return Number(mid, key, value, kind, args, words, klass, shared, seen, comment, kv)


# ---- instruction words -------------------------------------------------------------------
def _rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


def _imm8_encoding(v):
    """``(rot, imm8)`` for ``mov rd, #v``, or None when v isn't an 8-bit value rotated."""
    v &= 0xFFFFFFFF
    for r in range(16):
        x = ((v << (2 * r)) | (v >> (32 - 2 * r))) & 0xFFFFFFFF if r else v
        if x <= 0xFF:
            return r, x
    return None


def _is_mov(w):
    return (w & 0x0FEF0000) == 0x03A00000


def _is_mvn(w):
    return (w & 0x0FEF0000) == 0x03E00000


def _is_movw(w):
    return (w & 0x0FF00000) == 0x03000000


def _is_movt(w):
    return (w & 0x0FF00000) == 0x03400000


def _is_ldr_imm(w):
    """``ldr rt, [rn, #+-imm]`` (a word load with an immediate offset, no writeback)."""
    return (w & 0x0E500000) == 0x04100000 and (w & 0x00200000) == 0


def _imm16(w):
    return ((w >> 16) & 0xF) << 12 | (w & 0xFFF)


def _with_imm16(w, v):
    return (w & 0xFFF0F000) | ((v >> 12) & 0xF) << 16 | (v & 0xFFF)


def _arity(kind):
    """Words per site: a multi-word kind (a path entry, a qword) keeps all of its words at ONE VA."""
    return WORD_COUNT.get(kind, 2 if kind == "movwt" else 1)


def decode(kind, words):
    """The value the word(s) of *kind* hold, or None when they aren't that kind's shape. A
    number kept at several sites decodes when every site holds the same value."""
    n = _arity(kind)
    if kind in WORD_KINDS and len(words) > n and len(words) % n == 0:
        vals = {_decode_one(kind, tuple(words[i:i + n])) for i in range(0, len(words), n)}
        return vals.pop() if len(vals) == 1 and None not in vals else None
    return _decode_one(kind, words)


def _decode_one(kind, words):
    if kind == "imm" and len(words) == 1:
        w = words[0]
        if _is_mov(w):
            return _rot_imm(w)
        if _is_mvn(w):
            return (~_rot_imm(w)) & 0xFFFFFFFF
        return None
    if kind == "movw" and len(words) == 1:
        return _imm16(words[0]) if _is_movw(words[0]) else None
    if kind == "movwt" and len(words) == 2:
        lo, hi = words
        if not _is_movt(hi) or (lo >> 12) & 0xF != (hi >> 12) & 0xF:
            return None
        if _is_movw(lo):
            return _imm16(hi) << 16 | _imm16(lo)
        # item 144 also publishes a pair whose LOW word is a plain mov ("the low word is a
        # mov": mov r0,#0x800 ; movt r0,#0x70 = 0x700800) - movt keeps the low 16 bits
        if _is_mov(lo) and _rot_imm(lo) <= 0xFFFF:
            return _imm16(hi) << 16 | _rot_imm(lo)
        return None
    if kind in ("lit", "data") and len(words) == 1:
        return words[0]
    if kind == "path" and len(words) == 4:
        return words[1] << 32 | words[0]
    if kind == "qword" and len(words) == 2:
        return words[1] << 32 | words[0]
    if kind == "insn" and len(words) == 1:
        # the stock word is a load (the value is measured, not in it); a card this module
        # wrote holds `mov rd, #N` in its place
        return _rot_imm(words[0]) if _is_mov(words[0]) else None
    return None


def skeleton(kind, words):
    """The word(s) with the value masked out: two sites hold the same instruction when their
    skeletons match (condition, opcode, register). None for a whole-word kind."""
    if kind == "imm":
        return tuple(w & 0xFFFFF000 for w in words)
    if kind in ("movw", "movwt"):
        # a movwt pair's low word may be a plain mov (its value is the low 12 bits)
        return tuple(w & 0xFFFFF000 if (_is_mov(w) or _is_mvn(w)) else w & 0xFFF0F000
                     for w in words)
    if kind == "insn":
        # the load and the mov that replaces it share the condition and the register
        return tuple(w & 0xF000F000 for w in words)
    return None


def encode(kind, stock_words, value):
    """The word(s) holding *value* in the shape of *stock_words* (every site of a number kept
    at several). Raises StockModeError with the reason when the value doesn't fit."""
    n = _arity(kind)
    if kind in WORD_KINDS and len(stock_words) > n and len(stock_words) % n == 0:
        out = ()
        for i in range(0, len(stock_words), n):
            out += _encode_one(kind, tuple(stock_words[i:i + n]), value)
        return out
    return _encode_one(kind, stock_words, value)


def _encode_one(kind, stock_words, value):
    value = int(value)
    if value < 0:
        raise StockModeError("a negative number can't be written here")
    if kind == "imm":
        w = stock_words[0]
        if _is_mvn(w):
            enc = _imm8_encoding((~value) & 0xFFFFFFFF)
        else:
            enc = _imm8_encoding(value)
        if enc is None or value > 0xFFFFFFFF:
            near = _nearest_imm8(value)
            raise StockModeError(
                "%s doesn't fit this instruction (an 8-bit value shifted by an even number of "
                "bits%s)" % (format(value, ","), "; the nearest that fits is " + ", ".join(
                    format(n, ",") for n in near) if near else ""))
        return ((w & 0xFFFFF000) | enc[0] << 8 | enc[1],)
    if kind == "movw":
        if value > 0xFFFF:
            raise StockModeError("%s is too big for this instruction (at most 65,535)"
                                 % format(value, ","))
        return (_with_imm16(stock_words[0], value),)
    if kind == "movwt":
        if value > 0xFFFFFFFF:
            raise StockModeError("%s is too big (at most 4,294,967,295)" % format(value, ","))
        lo_w = stock_words[0]
        if _is_mov(lo_w):
            # a plain mov holds the low half: an 8-bit value shifted by an even number of bits
            enc = _imm8_encoding(value & 0xFFFF)
            if enc is None:
                raise StockModeError(
                    "%s doesn't fit these instructions (the low half, %s, has to be an 8-bit "
                    "value shifted by an even number of bits)" % (format(value, ","),
                                                                  format(value & 0xFFFF, ",")))
            return ((lo_w & 0xFFFFF000) | enc[0] << 8 | enc[1],
                    _with_imm16(stock_words[1], value >> 16))
        return (_with_imm16(stock_words[0], value & 0xFFFF),
                _with_imm16(stock_words[1], value >> 16))
    if kind in ("lit", "data"):
        if value > 0xFFFFFFFF:
            raise StockModeError("%s is too big (at most 4,294,967,295)" % format(value, ","))
        return (value,)
    if kind in ("path", "qword"):
        if value > 0xFFFFFFFFFFFFFFFF:
            raise StockModeError("0x%x is too big for a 64-bit shot mask" % value)
        lo, hi = value & 0xFFFFFFFF, value >> 32
        # a path entry keeps its lamp and id words: only the position changes
        return (lo, hi, stock_words[2], stock_words[3]) if kind == "path" else (lo, hi)
    if kind == "insn":
        w = stock_words[0]
        if value == 0:
            raise StockModeError("0 can't be written here (the count has to be at least 1)")
        enc = _imm8_encoding(value)
        if enc is None or value > 0xFFFFFFFF:
            near = _nearest_imm8(value)
            raise StockModeError(
                "%s doesn't fit this instruction (an 8-bit value shifted by an even number of "
                "bits%s)" % (format(value, ","), "; the nearest that fits is " + ", ".join(
                    format(n, ",") for n in near if n) if near else ""))
        # mov rd, #value: the load's condition and destination register, the value in place
        return ((w & 0xF0000000) | 0x03A00000 | (w & 0x0000F000) | enc[0] << 8 | enc[1],)
    raise StockModeError("a '%s' number can't be written in place" % kind)


def _nearest_imm8(value):
    """The encodable values either side of *value* (for the refusal message)."""
    cands = set()
    for r in range(16):
        for imm in range(256):
            cands.add(((imm >> (2 * r)) | (imm << (32 - 2 * r))) & 0xFFFFFFFF if r else imm)
    lo = max((c for c in cands if c <= value), default=None)
    hi = min((c for c in cands if c >= value), default=None)
    return [c for c in (lo, hi) if c is not None and c != value]


def check_value(number, value):
    """Raise StockModeError when *value* can't be staged for *number*; else return it (int).
    A ``path`` row takes a shot mask (decimal or ``0x`` hex) or ``none`` (0)."""
    if not number.editable:
        raise StockModeError("%s can't be changed here: %s" % (number.label, number.why_read_only()))
    text = str(value).replace(",", "").strip()
    if number.kind == "path" and text.lower() in ("none", "no", "skip", "-"):
        text = "0"
    try:
        value = int(text, 0) if number.kind in ("path", "qword") else int(text)
    except ValueError:
        raise StockModeError("%r isn't a whole number" % (value,)) from None
    if number.kind == "path" and value:
        if value & (value - 1):
            raise StockModeError("a tank position is ONE shot (one bit), not 0x%x" % value)
    if number.is_adjustment:
        rng = number.adj_range
        if rng and not rng[0] <= value <= rng[1]:
            raise StockModeError("%s must be between %d and %d (the game's own range for this "
                                 "setting)" % (number.label, rng[0], rng[1]))
        return value
    encode(number.kind, number.words, value)
    return value


# ---- shots as data: the tank path family and the shot names (item 159) -----------------------
def _title(build):
    """``godzilla_le`` -> ``godzilla``: the title the per-title facts are keyed by."""
    return (build.game or "").split("_")[0]


def shot_names(build):
    """``{mask: name}`` for the build's title: the SDK port's shot lines (what the Modes tab
    calls the shots) plus the spinner bits the port names only in a comment."""
    names = {}
    try:
        from . import mode_project as MP
        p = MP.profiles().get("%s_%s" % (build.game, str(build.version).replace(".", "_")))
    except Exception:                               # noqa: BLE001 - no ports: bits by number
        p = None
    if p is not None:
        for name, mask in p.shots:
            names.setdefault(int(mask), name)
    for mask, name in SPINNER_BITS.get(_title(build), {}).items():
        names.setdefault(mask, name)
    # one label, one bit: a port name reused for another mask gets its bit spelled out
    seen = {}
    for mask in sorted(names):
        label = names[mask]
        if label in seen:
            names[mask] = "%s (bit %d)" % (label, mask.bit_length() - 1)
        seen.setdefault(label, mask)
    return names


def shot_name(build, mask):
    """A shot in words: its port name, ``none`` for 0, else ``bit N``."""
    if not mask:
        return "none"
    name = shot_names(build).get(mask)
    if name:
        return name
    bits = [b for b in range(64) if mask >> b & 1]
    return "bit %d" % bits[0] if len(bits) == 1 else "bits " + ", ".join(str(b) for b in bits)


def display(build, number, value):
    """*value* of *number* in words: a shot name for a ``path`` row, hex for a ``qword``,
    the number otherwise (the Modes tab's Value and Stock columns, the Write list)."""
    if value is None:
        return "?"
    if number.kind == "path":
        return shot_name(build, int(value))
    if number.kind == "qword":
        return "0x%x" % int(value)
    return format(int(value), ",")


def path_rows(build, mode_id):
    """The mode's ``path`` rows in position order."""
    return sorted((n for n in build.numbers if n.mode_id == mode_id and n.kind == "path"),
                  key=lambda n: n.path_index if n.path_index is not None else 99)


def path_goal(rows):
    """The index of the position every tank heads for (the ``fixed goal`` row), or None."""
    return next((n.path_index for n in rows if n.fixed == "goal"), None)


def path_none_neighbour(rows, index):
    """The entry a position set to NONE copies: its neighbour AWAY from the goal (the proven
    way: position 4 := position 5 on Godzilla, item 158). None when there is no such entry."""
    goal = path_goal(rows)
    if goal is None:
        return None
    j = index - 1 if index < goal else index + 1
    return next((n for n in rows if n.path_index == j), None)


def path_choices(build, number, values=None):
    """``[(mask, label)]`` a position picker offers for *number* (a ``path`` row): NONE when the
    position may be skipped, then every single-bit shot the switches send alone that no other
    position of the mode holds (*values* = the staged ``{row key: int}``, to count a staged
    neighbour). ``[]`` for a row that isn't an editable position."""
    if number.kind != "path" or not number.editable:
        return []
    values = values or {}
    rows = path_rows(build, number.mode_id)
    taken = set()
    for n in rows:
        if n.row_key != number.row_key:
            v = values.get(n.row_key, n.value)
            if not v:                               # a NONE neighbour holds its neighbour's shot
                nb = path_none_neighbour(rows, n.path_index)
                v = values.get(nb.row_key, nb.value) if nb else 0
            if v:
                taken.add(v)
    out = []
    if path_none_neighbour(rows, number.path_index) is not None:
        out.append((0, "none (the tanks skip this position)"))
    names = shot_names(build)
    bad = NOT_ALONE.get(_title(build), set())
    cands = set(names) | {n.value for n in rows if n.value}
    for mask in sorted(cands, key=lambda m: (m.bit_length(), m)):
        if mask & (mask - 1) or mask in bad or mask in taken:
            continue
        out.append((mask, names.get(mask) or shot_name(build, mask)))
    return out


def check_path(build, number, value, values=None):
    """Raise StockModeError when *value* (an int from :func:`check_value`) can't be a tank
    position for *number* beside the other positions (*values* = the staged ones): it must be
    a shot the switches send alone, held by no other position, and the family's counted-shots
    words must still encode. NONE (0) needs a neighbour to copy."""
    values = dict(values or {})
    rows = path_rows(build, number.mode_id)
    if value == 0:
        if path_none_neighbour(rows, number.path_index) is None:
            raise StockModeError("%s can't be none: there is no neighbouring position for the "
                                 "tanks to take instead" % number.label)
    else:
        if value in NOT_ALONE.get(_title(build), set()):
            raise StockModeError("the switches never send %s alone (it arrives with another "
                                 "bit), so a tank can't stand on it" % shot_name(build, value))
        for n in rows:
            if n.row_key == number.row_key:
                continue
            v = values.get(n.row_key, n.value)
            if not v:
                nb = path_none_neighbour(rows, n.path_index)
                v = values.get(nb.row_key, nb.value) if nb else 0
            if v == value:
                raise StockModeError("%s is already position %d" % (shot_name(build, value),
                                                                   n.path_index + 1))
    values[number.row_key] = value
    try:
        family_words(build, number.mode_id, values)
    except StockModeError as e:
        raise StockModeError("with the other positions, %s doesn't fit the mode's counted-shots "
                             "instruction: %s" % (shot_name(build, value), e)) from None
    return value


def resolve_path(build, mode_id, values):
    """``({index: (mask, words)}, counted)`` for the mode's positions with the staged
    *values* applied: a NONE (0) position is a whole copy of its neighbour away from the goal
    (lamp and id included, the proven way), and *counted* is the OR of the positions."""
    rows = path_rows(build, mode_id)
    out = {}
    for n in rows:
        v = values.get(n.row_key, n.value)
        if v == 0:
            nb = path_none_neighbour(rows, n.path_index)
            if nb is None:
                raise StockModeError("position %d can't be none: no neighbouring position"
                                     % (n.path_index + 1))
            nv = values.get(nb.row_key, nb.value)
            words = encode("path", nb.words, nv) if nv else tuple(nb.words)
        else:
            words = encode("path", n.words, v)
        out[n.path_index] = (decode("path", words), words)
    counted = 0
    for mask, _w in out.values():
        counted |= mask
    return out, counted


def family_words(build, mode_id, values):
    """``{row key: words}`` for every row of the mode's PATH FAMILY (the positions and the
    rows that ``follow path``: the counted-shots words = the OR of the positions, and each
    spot list entry = the position whose stock shot it holds) with the staged *values*
    applied. Raises StockModeError when a word can't be encoded."""
    rows = path_rows(build, mode_id)
    resolved, counted = resolve_path(build, mode_id, values)
    out = {n.row_key: resolved[n.path_index][1] for n in rows}
    for n in build.numbers:
        if n.mode_id != mode_id or n.follows != "path":
            continue
        if n.key == "path.counted.lo":
            out[n.row_key] = encode(n.kind, n.words, counted & 0xFFFFFFFF)
        elif n.key == "path.counted.hi":
            out[n.row_key] = encode(n.kind, n.words, counted >> 32)
        elif n.key.startswith("path.spot."):
            # a replaced position's spot entry follows it; a NONE position's entry stays (the
            # entry is then neither lit nor counted, so the game never spots it)
            pos = next((p for p in rows if p.value == n.value), None)
            v = values.get(pos.row_key, pos.value) if pos is not None else n.value
            out[n.row_key] = encode(n.kind, n.words, v if v else n.value)
        else:
            out[n.row_key] = tuple(n.words)
    return out


# ---- the ELF -------------------------------------------------------------------------------
class ElfImage:
    """VA <-> file offset through a 32-bit little-endian ELF's PT_LOAD headers."""

    def __init__(self, data):
        self.data = data
        if bytes(data[:4]) != b"\x7fELF" or data[4] != 1 or data[5] != 1:
            raise StockModeError("the game program isn't a 32-bit little-endian ELF")
        phoff = struct.unpack_from("<I", data, 0x1C)[0]
        phent, phnum = struct.unpack_from("<HH", data, 0x2A)
        self.loads = []
        for i in range(phnum):
            p_type, off, va, _pa, fsz, _msz, _flg, _al = struct.unpack_from(
                "<8I", data, phoff + i * phent)
            if p_type == 1:
                self.loads.append((off, va, fsz))

    def va_to_off(self, va):
        for off, v, fsz in self.loads:
            if v <= va and va + 4 <= v + fsz:
                o = off + (va - v)
                return o if o + 4 <= len(self.data) else None
        return None

    def words(self, vas):
        out = []
        for va in vas:
            o = self.va_to_off(va)
            if o is None:
                return None
            out.append(struct.unpack_from("<I", self.data, o)[0])
        return tuple(out)

    def row_words(self, number):
        """The words a row describes: one per VA, or a run of :func:`word_count` words from
        its one VA (a ``path`` entry, a ``qword``). None when a word isn't in the file."""
        n = word_count(number.kind, number.vas)
        if number.kind in WORD_COUNT:
            return self.words(tuple(number.vas[0] + 4 * k for k in range(n))) if number.vas else None
        return self.words(number.vas)

    @property
    def sha1(self):
        return hashlib.sha1(bytes(self.data)).hexdigest()


def row_offsets(img, number):
    """The file offsets of a row's words, in word order (None when any is missing)."""
    if number.kind in WORD_COUNT:
        vas = tuple(number.vas[0] + 4 * k for k in range(word_count(number.kind, number.vas)))
    else:
        vas = number.vas
    offs = tuple(img.va_to_off(va) for va in vas)
    return None if any(o is None for o in offs) else offs


def site_state(img, number):
    """``(state, current words)``: ``stock`` (the table's words), ``ours`` (the same
    instruction with another value - a card this module wrote), ``value`` (a whole-word kind
    holding another value), ``differs`` (not what the table describes) or ``missing`` (the
    VA isn't in the file)."""
    cur = img.row_words(number)
    if cur is None:
        return "missing", None
    if cur == tuple(number.words):
        return "stock", cur
    if number.kind in INSN_KINDS:
        if skeleton(number.kind, cur) == skeleton(number.kind, number.words) \
                and decode(number.kind, cur) is not None:
            return "ours", cur
        return "differs", cur
    return "value", cur


def identify(img, builds, game=None, version=None):
    """``(Build, how, why)`` for the game ELF in *img*: ``how`` = ``"sha1"`` for the exact
    build, ``"words"`` when the file differs but every instruction row of the title's table
    is its stock instruction (a card this app, or another tool, changed a value in). ``(None,
    None, why)`` when no table describes it."""
    sha = img.sha1
    for b in builds:
        if b.sha1 == sha:
            return b, "sha1", ""
    why = "no stock-mode table for this game program (sha1 %s)" % sha[:12]
    cands = [b for b in builds if game is None or b.same_title(game, version)]
    for b in cands:
        insn = [n for n in b.numbers if n.is_word and n.kind in INSN_KINDS]
        whole = [n for n in b.numbers if n.is_word and n.kind not in INSN_KINDS]
        if not insn and not whole:
            # a table of operator settings alone (a plain-C title): the program is that build
            # when it has every one of the table's settings at the table's id
            if game is not None and _settings_agree(img, b):
                return b, "settings", ""
            continue
        bad = None
        for n in insn:
            st, cur = site_state(img, n)
            if st not in ("stock", "ours"):
                bad = (n, cur)
                break
        if bad is None and not insn:
            for n in whole:
                st, cur = site_state(img, n)
                if st != "stock":
                    bad = (n, cur)
                    break
        if bad is None:
            return b, "words", ""
        n, cur = bad
        why = ("the game program isn't %s: at 0x%x the table has %s and the card has %s"
               % (b.id, n.vas[0], ",".join("%08x" % w for w in n.words),
                  ",".join("%08x" % w for w in cur) if cur else "nothing"))
    return None, None, why


def _settings_agree(img, build):
    """Every operator setting *build*'s rows name is in the program at the row's id."""
    rows = [n for n in build.numbers if n.kind == "adj"]
    if not rows:
        return False
    from .adjustments import AdjustmentTable
    try:
        table = AdjustmentTable(bytes(img.data))
    except ValueError:
        return False
    return all(table.by_name.get(n.args[0]) == n.args[1] for n in rows)


# ---- the tables the app knows --------------------------------------------------------------
_TABLES = None


def hand_tables():
    """Every :class:`Build` in :mod:`.stock_mode_tables` (parsed once)."""
    global _TABLES
    if _TABLES is None:
        from . import stock_mode_tables
        _TABLES = parse(stock_mode_tables.TABLE)
    return _TABLES


def tables():
    """Every :class:`Build` the app knows: the hand tables, then the tables generated on this
    machine from a card's own game program (:mod:`.stock_reader`), a hand table winning for
    its program."""
    hand = hand_tables()
    try:
        from .stock_reader import cached_builds
        gen = cached_builds()
    except Exception:
        gen = []
    if not gen:
        return hand
    shas = {b.sha1 for b in hand}
    return list(hand) + [b for b in gen if b.sha1 not in shas]


def table_for(game, version, builds=None):
    for b in (tables() if builds is None else builds):
        if b.same_title(game, version):
            return b
    return None


def project_build(assets_dir):
    """``(game, version)`` of the card the project was extracted from, from its
    ``.extract_source.json`` (``godzilla_pro-1_15_0...raw`` -> ``("godzilla_pro", "1.15.0")``),
    or None."""
    from ...core.extract_source import read_extract_source, version_hint_from_name
    rec = read_extract_source(assets_dir) or {}
    name = rec.get("input_name") or os.path.basename(rec.get("input_path") or "")
    if not name or "-" not in name:
        return None
    game = name.split("-", 1)[0]
    version = rec.get("card_version") or version_hint_from_name(name)
    if not version:
        return None
    return game, str(version).split(" ")[0]


def table_for_project(assets_dir, builds=None):
    pb = project_build(assets_dir)
    return table_for(pb[0], pb[1], builds) if pb else None


# ---- staging ---------------------------------------------------------------------------------
def staged(assets_dir):
    """``{"build": str|None, "values": {row key: int}, "touched": [row key]}`` recorded for
    the project. ``touched`` = every word row the project ever staged a value for, kept when
    the row goes back to stock: a whole-word row (``lit`` / ``data``) holding another value
    is only put back when the project once changed it."""
    from ...core import staged_changes
    rec = staged_changes.load(assets_dir).get(STAGE_KEY)
    if not isinstance(rec, dict):
        return {"build": None, "values": {}, "touched": []}
    vals = {}
    for k, v in (rec.get("values") or {}).items():
        try:
            vals[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    touched = rec.get("touched")
    touched = sorted({str(k) for k in touched} if isinstance(touched, list) else set())
    return {"build": rec.get("build"), "values": vals, "touched": touched}


# ---- a staged row key across table readers ----------------------------------------------------
def _older_numbers(build):
    """``{row key: Number}`` of the tables older readers kept for *build*'s program
    (:func:`.stock_reader.older_tables`), newest reader first. ``{}`` for a hand table."""
    try:
        from .stock_reader import older_tables
        olds = older_tables(build.sha1)
    except Exception:
        return {}
    out = {}
    for b in olds:
        for n in b.numbers:
            out.setdefault(n.row_key, n)
    return out


def _same_row(build, old):
    """The row of *build* that is *old* (a Number of an older reader's table): the same
    operator setting, or a word row at the same addresses. None when there is none."""
    for n in build.numbers:
        if old.kind == "adj" and n.kind == "adj" and n.adj_name == old.adj_name:
            return n
        if old.kind in WORD_KINDS and n.kind in WORD_KINDS and old.args and \
                tuple(n.args) == tuple(old.args):
            return n
    return None


def resolve_keys(values, build):
    """*values* ``{row key: value}`` staged by the project, with every key this table does
    not have mapped to the row it names, through the table an OLDER READER kept for the same
    program (an app update that raises :data:`.stock_reader.READER_REV` may give rows new
    keys): the same operator setting, or the same instruction addresses. A key this table has
    wins over a mapped one; a key nothing maps is kept as it is (reported, never written)."""
    values = dict(values or {})
    if build is None or not values:
        return values
    have = {n.row_key for n in build.numbers}
    missing = [k for k in values if k not in have]
    if not missing:
        return values
    old = _older_numbers(build)
    out = {k: v for k, v in values.items() if k in have}
    for k in missing:
        n = old.get(k)
        new = _same_row(build, n) if n is not None else None
        if new is None:
            out.setdefault(k, values[k])
        elif new.row_key not in out:
            out[new.row_key] = values[k]
    return out


def staged_for(assets_dir, build):
    """:func:`staged` with its row keys read against *build* (:func:`resolve_keys`)."""
    rec = staged(assets_dir)
    if build is not None and rec["build"] == build.id:
        rec["values"] = resolve_keys(rec["values"], build)
        rec["touched"] = sorted(resolve_keys(dict.fromkeys(rec["touched"]), build))
    return rec


def _record(data, build):
    """The project's ``stock_modes`` record for *build* as ``(values, touched)`` copies, their
    keys read against *build* (:func:`resolve_keys`); a record staged for another build starts
    again empty."""
    rec = data.get(STAGE_KEY) if isinstance(data.get(STAGE_KEY), dict) else {}
    if rec.get("build") != build.id:
        return {}, set()
    touched = rec.get("touched")
    touched = {str(k) for k in touched} if isinstance(touched, list) else set()
    return (resolve_keys(dict(rec.get("values") or {}), build),
            set(resolve_keys(dict.fromkeys(touched), build)))


def _put_record(data, build, values, touched):
    rec = {"build": build.id, "values": values}
    if touched:
        rec["touched"] = sorted(touched)
    data[STAGE_KEY] = rec


def _staged_settings(data):
    s = data.get(SETTINGS_KEY)
    return s if isinstance(s, dict) else {}


def stage(assets_dir, build, number, value):
    """Stage *value* for *number* in the project: a word row under ``stock_modes``, an
    adjustment under Defaults' ``settings``. Staging the stock value un-stages the row.
    Returns the value staged (None when it is back at stock). Raises StockModeError."""
    from ...core import staged_changes
    if not assets_dir or not os.path.isdir(assets_dir):
        raise StockModeError("open or extract a card project first (Extract tab)")
    value = check_value(number, value)
    data = staged_changes.load(assets_dir)
    back_to_stock = value == number.value
    vals, touched = _record(data, build)
    if number.kind == "path" and not back_to_stock:
        # a tank position is checked beside the mode's other positions (item 159)
        check_path(build, number, value, vals)
    if number.is_adjustment:
        settings = dict(_staged_settings(data))
        if back_to_stock:
            settings.pop(number.adj_name, None)
        else:
            settings[number.adj_name] = value
        if settings:
            data[SETTINGS_KEY] = settings
        else:
            data.pop(SETTINGS_KEY, None)
        if not back_to_stock:
            # a setting default is a whole data word: like a lit/data row, the Write only
            # puts its stock value back over another one when this project once changed it
            touched.add(number.row_key)
    else:
        if back_to_stock:
            vals.pop(number.row_key, None)
        else:
            vals[number.row_key] = value
            touched.add(number.row_key)
    # The record is written for an adjustment row too, and stays with an empty map after a
    # revert: "this project manages the game's own modes, and they are stock". A Write then
    # puts stock words back over ours (on a card built from one that holds them) and puts
    # this project's build at the output back to the original when nothing else is staged -
    # also after a TIMER was the only change. A managed project's staged timers go into the
    # game program with the award words (plan_overlay), so every Write path carries them. A
    # project that stages the same setting only on the Defaults tab has no record, and its
    # Write behaves as it always did (Defaults applies it after an image build).
    _put_record(data, build, vals, touched)
    staged_changes.save(assets_dir, data)
    return None if back_to_stock else value


def unstage(assets_dir, build, number):
    """Put one row back to stock (staged)."""
    return stage(assets_dir, build, number, number.value)


def unstage_all(assets_dir, build):
    """Every row of *build* back to stock: word values cleared, and the table's adjustments
    taken out of ``settings`` (other staged settings are left alone). Returns how many."""
    from ...core import staged_changes
    data = staged_changes.load(assets_dir)
    n = 0
    rec = data.get(STAGE_KEY)
    if isinstance(rec, dict):
        n += len(rec.get("values") or {})
    _vals, touched = _record(data, build)
    _put_record(data, build, {}, touched)
    settings = dict(_staged_settings(data))
    for name in build.adjustment_numbers():
        if name in settings:
            settings.pop(name)
            n += 1
    if settings:
        data[SETTINGS_KEY] = settings
    else:
        data.pop(SETTINGS_KEY, None)
    staged_changes.save(assets_dir, data)
    return n


def staged_edits(assets_dir, build=None):
    """``[{"number", "mode", "stock", "new", "staged_for"}]`` - every changed row of the
    project's table: word values under ``stock_modes`` and the table's adjustments under
    ``settings``. ``staged_for`` is the build the value was staged against (a word value
    staged for another build is listed, and not written).

    The table's adjustments count only in a project that MANAGES the game's own modes (it
    has a ``stock_modes`` record: the Modes tab staged something). A setting staged only on
    the Defaults tab is Defaults' business, as it always was: it is applied after the next
    build, it doesn't make a Write build on its own and it isn't a Write-list row."""
    if not assets_dir:
        return []
    rec = staged(assets_dir)
    if build is None:
        build = table_for_project(assets_dir)
    if build is None and rec["build"]:
        # no .extract_source.json to name the card: the build the values were staged for
        game, _sp, version = rec["build"].partition(" ")
        build = table_for(game, version)
    if build is None:
        return []
    from ...core import staged_changes
    data = staged_changes.load(assets_dir)
    out = []
    values = resolve_keys(rec["values"], build) if rec["build"] == build.id else rec["values"]
    for key, v in sorted(values.items()):
        n = build.number(key)
        if n is None or not n.is_word or n.inert or n.follows:
            continue                # a stale value for an inert row is never a pending change
        out.append({"number": n, "mode": build.mode_name(n.mode_id), "stock": n.value, "new": v,
                    "staged_for": rec["build"], "stock_text": display(build, n, n.value),
                    "new_text": display(build, n, v)})
    settings = _staged_settings(data) if isinstance(data.get(STAGE_KEY), dict) else {}
    for name, n in build.adjustment_numbers().items():
        if name in settings:
            try:
                v = int(settings[name])
            except (TypeError, ValueError):
                continue
            out.append({"number": n, "mode": build.mode_name(n.mode_id), "stock": n.value,
                        "new": v, "staged_for": build.id})
    return out


def unread_staged(assets_dir):
    """How many changes the project staged for the game's own modes while no table of its
    build is on this computer (the kept table was lost, an app update raised the reader's
    revision, or the project came from another PC): its word values and staged settings.
    They are not dropped: a Write reads the table again from the card's own game program
    (:func:`plan_overlay`), and the Write list shows them as not read yet. 0 when the table
    is here, the project manages none, or on any trouble."""
    try:
        if not assets_dir or not manages(assets_dir):
            return 0
        rec = staged(assets_dir)
        if table_for_project(assets_dir) is not None:
            return 0
        if rec["build"]:
            game, _sp, version = rec["build"].partition(" ")
            if table_for(game, version) is not None:
                return 0
        from ...core import staged_changes
        return len(rec["values"]) + len(_staged_settings(staged_changes.load(assets_dir)))
    except Exception:
        return 0


def pending_count(assets_dir):
    """How many of the project's stock-mode rows are staged (0 on any trouble). The Write's
    'Nothing to write' guard counts these. A project with NOTHING staged any more is not
    counted here: when the card it is built from still holds our words the guard counts
    :func:`restore_count`, and a build of this project already at the output is put back to
    the original by the Write (``engine._stock_mode_restore_ok``)."""
    try:
        return len(staged_edits(assets_dir)) + unread_staged(assets_dir)
    except Exception:
        return 0


def pending_adjustments(assets_dir):
    """The staged adjustment rows alone. The Write puts their defaults into the game program
    with the award words (:func:`plan_overlay`), on every Write path."""
    try:
        return [e for e in staged_edits(assets_dir) if e["number"].is_adjustment]
    except Exception:
        return []


def manages(assets_dir):
    """True when the project has a ``stock_modes`` record (even an all-stock one)."""
    from ...core import staged_changes
    try:
        return isinstance(staged_changes.load(assets_dir).get(STAGE_KEY), dict)
    except Exception:
        return False


def kept_by_revert_all(data):
    """What "Revert all changes" keeps of a project's staged changes (*data*, the whole
    ``.staged_changes.json``): its ``stock_modes`` record with every value cleared (the
    rows it ever changed are kept), else nothing. Every change is dropped, but the project
    still manages the game's own modes, so the next Write puts a card of this project that
    holds our words back to stock instead of stopping at "Nothing to write"."""
    rec = data.get(STAGE_KEY) if isinstance(data, dict) else None
    if not isinstance(rec, dict):
        return {}
    out = {"build": rec.get("build"), "values": {}}
    if isinstance(rec.get("touched"), list) and rec["touched"]:
        out["touched"] = sorted({str(k) for k in rec["touched"]})
    return {STAGE_KEY: out}


def fingerprint(assets_dir):
    """A cheap equality summary of the staged stock-mode state (the Write scan's)."""
    try:
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
        return json.dumps([data.get(STAGE_KEY), sorted((_staged_settings(data)).items())],
                          sort_keys=True, default=str)
    except Exception:
        return None


# ---- the Write -------------------------------------------------------------------------------
def plan_overlay(elf_bytes, assets_dir, log, builds=None, stats=None):
    """``({file_offset: bytes}, n_changed, build)`` for the project's staged word values on
    *elf_bytes*: each staged row's words, and every other word row of the table whose card
    words are OURS (not stock) put back to stock - an instruction row whenever it holds
    another value, a whole-word row only when this project once changed it (``touched``).
    The table's staged operator settings (a battle timer) go in the same overlay as their
    compiled defaults (:func:`_plan_setting_defaults`). Refusals are logged, never raised.

    *stats*, a dict when given, gets ``held``: how many staged numbers the program already
    holds (a card this project wrote before, e.g. a second Direct SD Write)."""
    say = log or (lambda *a, **k: None)
    if stats is not None:
        stats["held"] = 0
    rec = staged(assets_dir)
    if rec["build"] is None:
        return {}, 0, None
    read_here = builds is None
    builds = tables() if builds is None else builds
    try:
        img = ElfImage(elf_bytes)
    except StockModeError as e:
        say("The game's own modes: %s; nothing changed." % e, "warning")
        return {}, 0, None
    game, _sp, version = (rec["build"] or "").partition(" ")
    if read_here and table_for(game, version, builds) is None:
        # no table of this build on this computer (a lost cache, a raised reader revision, a
        # project from another PC): read it now from the card's own game program
        got = _read_table_now(elf_bytes, game, version, say)
        if got is not None:
            builds = list(builds) + [got]
    build, how, why = identify(img, builds, game, version)
    if build is None:
        n_staged = len(rec["values"]) + len(_staged_setting_values(assets_dir, None, game,
                                                                   version))
        if n_staged:
            say("The game's own modes: %d staged change(s) NOT written - %s. They were staged "
                "for %s." % (n_staged, why, rec["build"]), "warning")
        return {}, 0, None
    if build.id != rec["build"]:
        n_staged = len(rec["values"]) + len(_staged_setting_values(assets_dir, build))
        if n_staged:
            say("The game's own modes: %d change(s) were staged for %s, but this card is %s; "
                "none were written." % (n_staged, rec["build"], build.id), "warning")
        return {}, 0, build
    rec = dict(rec, values=resolve_keys(rec["values"], build),
               touched=sorted(resolve_keys(dict.fromkeys(rec["touched"]), build)))
    overlay, n = {}, 0
    sites = {}                  # VA -> (row key, the word this Write leaves there)
    # A word two rows share (``shared N``) is settled by a STAGED row first, whatever the
    # table's order: an unstaged row at the same VA must never put the stock words back over
    # a value somebody staged (on a card that already holds it, the staged row writes nothing
    # and still claims the site).
    ordered = ([num for num in build.numbers if num.is_word and num.row_key in rec["values"]]
               + [num for num in build.numbers
                  if num.is_word and num.row_key not in rec["values"]])
    for num in ordered:
        if num.kind == "path" or num.follows:
            continue                # planned together, as one family (item 159), below
        want = rec["values"].get(num.row_key, num.value)
        if num.inert and want != num.value:
            # an older project's value for a row item 158 proved inert: never written, but
            # a card holding it (an older app's Write) still goes back to stock below
            say("The game's own modes: %s %s not written - %s." % (
                build.mode_name(num.mode_id), build.row_label(num).lower(),
                num.why_read_only()), "warning")
            want = num.value
        st, cur = site_state(img, num)
        if not num.words_agree:
            if num.row_key in rec["values"]:
                say("The game's own modes: %s %s not written - %s." % (
                    build.mode_name(num.mode_id), build.row_label(num).lower(),
                    num.why_read_only()), "warning")
            continue
        if st in ("missing", "differs"):
            if num.row_key in rec["values"]:
                say("The game's own modes: %s %s not written - %s." % (
                    build.mode_name(num.mode_id), build.row_label(num).lower(),
                    "its address isn't in this game program" if st == "missing" else
                    "the instruction at 0x%x isn't the one the table describes" % num.vas[0]),
                    "warning")
            continue
        if st == "stock" and num.row_key not in rec["values"]:
            continue            # a stock site nobody asked to change is never rewritten
        try:
            # back to stock = the table's own words, byte for byte (never a re-encoding)
            new = tuple(num.words) if want == num.value else encode(num.kind, num.words, want)
        except StockModeError as e:
            say("The game's own modes: %s %s not written - %s." % (
                build.mode_name(num.mode_id), build.row_label(num).lower(), e), "warning")
            continue
        if st == "value" and num.row_key not in rec["values"] \
                and num.row_key not in rec["touched"]:
            continue            # a whole word holding someone else's value: never touched unasked
        # (a whole word this project once changed, now back at stock: its stock word goes back)
        new_at = dict(zip(num.vas, new))
        prior = [(va, sites[va]) for va in num.vas if va in sites]
        if prior:
            clash = [va for va, (_key, w) in prior if w != new_at[va]]
            if clash and num.row_key in rec["values"]:
                say("The game's own modes: %s and %s are the same word(s) at 0x%x; the first "
                    "is kept." % (prior[0][1][0], num.row_key, clash[0]), "warning")
            continue
        for va, w in zip(num.vas, new):
            sites[va] = (num.row_key, w)
        if new == cur:
            if stats is not None and num.row_key in rec["values"]:
                stats["held"] += 1
            continue
        for va, w in zip(num.vas, new):
            overlay[img.va_to_off(va)] = struct.pack("<I", w)
        n += 1
        # a stock insn row's word LOADS its value: the table's measured value is what it held
        old_v = num.value if st == "stock" else decode(num.kind, cur)
        say("The game's own modes: %s %s %s -> %s (game program, %s)%s." % (
            build.mode_name(num.mode_id), build.row_label(num).lower(),
            format(old_v, ",") if old_v is not None else "?", format(want, ","), num.where(),
            " - back to stock" if want == num.value else ""), "info")
    for mid in sorted({num.mode_id for num in build.numbers if num.kind == "path"}):
        f_overlay, f_n = _plan_path_family(img, build, mid, rec, say, sites, stats)
        overlay.update(f_overlay)
        n += f_n
    s_overlay, s_n = _plan_setting_defaults(elf_bytes, build, assets_dir, rec["touched"], say,
                                            overlay, stats)
    overlay.update(s_overlay)
    return overlay, n + s_n, build


def _read_table_now(elf_bytes, game, version, say):
    """The table of the game's own modes read from *elf_bytes* now (:func:`.stock_reader.
    ensure_table`: a second or two, kept for next time), or None with the reason logged."""
    try:
        from .stock_reader import ensure_table
        got = ensure_table(bytes(elf_bytes), game, version)
    except Exception as e:                      # noqa: BLE001 - said, never raised
        say("The game's own modes: their table could not be read from this card's game "
            "program (%s)." % e, "warning")
        return None
    if got.build is None:
        say("The game's own modes: their table could not be read from this card's game "
            "program. %s" % " ".join(got.notes or ()), "warning")
        return None
    say("The game's own modes: read their table from this card's game program (%s)."
        % got.build.id, "info")
    return got.build


def _plan_path_family(img, build, mode_id, rec, say, sites, stats):
    """``({file_offset: bytes}, n_changed)`` for one mode's PATH FAMILY (item 159): its
    ``path`` rows and the rows that ``follow path``, planned together from the staged
    positions (:func:`family_words`). Nothing is touched unless the project staged a position
    or once did (``touched``); then every family word the card holds differently from what
    the positions say is written - which is also how a family goes back to stock, byte for
    byte. Refusals are logged, never raised."""
    rows = path_rows(build, mode_id)
    if not rows:
        return {}, 0
    fam = rows + [n for n in build.numbers if n.mode_id == mode_id and n.follows == "path"]
    keys = {n.row_key for n in rows}
    staged = {k: v for k, v in rec["values"].items() if k in keys}
    if not staged and not (keys & set(rec["touched"])):
        return {}, 0
    name = build.mode_name(mode_id)
    cur = {}
    for n in fam:
        st, w = site_state(img, n)
        if st == "missing":
            say("The game's own modes: %s positions not written - the address of %s isn't in "
                "this game program." % (name, build.row_label(n).lower()), "warning")
            return {}, 0
        cur[n.row_key] = w
    try:
        want = family_words(build, mode_id, staged)
    except StockModeError as e:
        say("The game's own modes: %s positions not written - %s." % (name, e), "warning")
        return {}, 0
    overlay, n_changed, held = {}, 0, 0
    for n in fam:
        new = want[n.row_key]
        offs = row_offsets(img, n)
        for k, w in enumerate(new):
            sites[n.vas[0] + 4 * k] = (n.row_key, w)
        if new == cur[n.row_key]:
            if n.row_key in staged:
                held += 1
            continue
        for off, w in zip(offs, new):
            overlay[off] = struct.pack("<I", w)
        n_changed += 1
        if n.kind == "path":
            old = decode("path", cur[n.row_key])
            new_v = staged.get(n.row_key, n.value)
            say("The game's own modes: %s position %d: %s -> %s (game program, %s)%s." % (
                name, n.path_index + 1, shot_name(build, old), shot_name(build, new_v),
                n.where(), " - back to stock" if n.row_key not in staged else ""), "info")
        else:
            say("The game's own modes: %s %s kept in step with the positions (game program, "
                "%s)." % (name, build.row_label(n).lower(), n.where()), "info")
    if stats is not None:
        stats["held"] = stats.get("held", 0) + held
    return overlay, n_changed


def _staged_setting_values(assets_dir, build, game=None, version=None):
    """``{AD_NAME: int}`` - the table's operator settings staged in ``settings`` for a
    project that manages the game's own modes (the settings of *build*, or of the table for
    *game* / *version* when *build* is None). ``{}`` on any trouble."""
    try:
        from ...core import staged_changes
        data = staged_changes.load(assets_dir)
        if not isinstance(data.get(STAGE_KEY), dict):
            return {}
        if build is None:
            build = table_for(game, version) if game else None
        if build is None:
            return {}
        settings = _staged_settings(data)
        out = {}
        for name in build.adjustment_numbers():
            if name in settings:
                try:
                    out[name] = int(settings[name])
                except (TypeError, ValueError):
                    continue
        return out
    except Exception:
        return {}


def settings_already_built(assets_dir, table, overrides):
    """The names in *overrides* (``{AD_NAME: value}``, the app's post-build settings step)
    that are this project's staged stock-mode settings and whose default in *table* (the
    BUILT game program's :class:`.adjustments.AdjustmentTable`) already is that value: the
    Write put them there. The step leaves them out, so a build it has nothing else to write
    into keeps its mtime and the next Write can update it in place. ``[]`` on any trouble."""
    try:
        mine = _staged_setting_values(assets_dir, table_for_project(assets_dir))
        out = []
        for name, value in (overrides or {}).items():
            if mine.get(name) == int(value) and name in table.by_name \
                    and table.get(name)["default"] == int(value):
                out.append(name)
        return out
    except Exception:
        return []


def _plan_setting_defaults(elf_bytes, build, assets_dir, touched, say, taken=None, stats=None):
    """``({file_offset: bytes}, n_changed)`` - the table's operator settings (a battle timer)
    as their COMPILED DEFAULTS in the game program: the 4-byte ``default`` field of the
    setting's descriptor, the word :meth:`.adjustments.AdjustmentTable.patched_bytes` (the
    Defaults tab's writer) changes.

    WHY HERE. A timer the Modes tab staged used to reach a card only through the app's
    post-build settings step, which runs after a Write to an image FILE; a Direct SD Write and
    the emulator's override set never ran it, yet the Write's count said the timer was
    written. In the shared patch set it lands on every path, and the validator bypass
    refreshes the program's ``.sidx`` record over it with the award words.

    A staged value is written when the program holds another; a setting this project once
    changed (``touched``) and has put back to stock gets the stock default back over another
    value; a setting nobody here changed is never touched. Refusals are logged."""
    staged_vals = _staged_setting_values(assets_dir, build)
    rows = build.adjustment_numbers()
    touched_names = {n.adj_name for n in build.numbers
                     if n.is_adjustment and n.row_key in (touched or ())}
    wanted = {}
    for name, num in rows.items():
        if name in staged_vals:
            wanted[name] = (staged_vals[name], True)
        elif name in touched_names and num.value is not None:
            wanted[name] = (num.value, False)
    if not wanted:
        return {}, 0
    from .adjustments import AdjustmentTable
    try:
        table = AdjustmentTable(elf_bytes)
        if not table.sane():
            raise ValueError("its settings table doesn't read as one")
    except ValueError as e:
        n_staged = sum(1 for _v, is_staged in wanted.values() if is_staged)
        if n_staged:
            say("The game's own modes: %d staged setting(s) NOT written - the game program's "
                "settings can't be read (%s)." % (n_staged, e), "warning")
        return {}, 0
    overlay, n = {}, 0
    for name, (want, is_staged) in sorted(wanted.items(), key=lambda kv: table.by_name.get(
            kv[0], 0)):
        num = rows[name]
        label = "%s %s" % (build.mode_name(num.mode_id), build.row_label(num).lower())
        if not num.editable:
            if is_staged:
                say("The game's own modes: %s not written - %s." % (label, num.why_read_only()),
                    "warning")
            continue
        if name not in table.by_name:
            if is_staged:
                say("The game's own modes: %s not written - this game program has no setting "
                    "%s." % (label, name), "warning")
            continue
        e = table.get(name)
        if not e["min"] <= want <= e["max"]:
            if is_staged:
                say("The game's own modes: %s not written - %s is outside the game's own range "
                    "for %s (%d to %d)." % (label, format(want, ","), name, e["min"], e["max"]),
                    "warning")
            continue
        if e["default"] == want:
            if stats is not None and is_staged:
                stats["held"] += 1
            continue
        off = table.default_file_offset(name)
        if off is None or (taken and off in taken):
            if is_staged:
                say("The game's own modes: %s not written - its default isn't a word this "
                    "Write can change." % label, "warning")
            continue
        overlay[off] = struct.pack("<i", int(want))
        n += 1
        say("The game's own modes: %s %s -> %s (game program, the default of operator setting "
            "%s)%s." % (label, format(e["default"], ","), format(want, ","), name,
                        "" if is_staged else " - back to stock"), "info")
    return overlay, n


def restore_count(reader, fw_node, assets_dir, builds=None):
    """How many rows a Write would put back to stock on the game ELF at *fw_node* when the
    project manages the game's own modes but has nothing staged: the card being built FROM
    holds our words (a card this app built, used as the original). 0 when nothing would
    change, the project doesn't manage them, or on any trouble. Logs nothing."""
    try:
        if not manages(assets_dir) or fw_node is None:
            return 0
        _overlay, n, _build = plan_overlay(bytes(reader.read_file_bytes(fw_node)), assets_dir,
                                           None, builds=builds)
        return n
    except Exception:
        return 0


def compute_writes(reader, fw_node, assets_dir, log, patched_fw=None, builds=None, stats=None):
    """``(writes, overlay, n_changed)`` - the project's staged stock-mode words (and the
    table's staged settings, as their compiled defaults) for the game
    ELF at *fw_node*: flat ``[(disk_offset, bytes)]`` in-place writes and the same edits as
    ``{file_offset: bytes}`` for whoever refreshes the ELF's ``.sidx`` record last (the
    validator bypass). When a staged whole-file firmware exists (*patched_fw*: the blip-free
    cave or a grown program-text ELF), the edits go INTO that file instead - it replaces the
    card's ELF, and its record is computed from it - and no in-place write is returned.
    *stats* as :func:`plan_overlay`'s. Never raises."""
    say = log or (lambda *a, **k: None)
    try:
        if not manages(assets_dir):
            return [], {}, 0
        if patched_fw is not None:
            with open(patched_fw, "rb") as f:
                elf = bytearray(f.read())
        else:
            if fw_node is None:
                return [], {}, 0
            elf = bytearray(reader.read_file_bytes(fw_node))
        overlay, n, _build = plan_overlay(bytes(elf), assets_dir, say, builds=builds,
                                          stats=stats)
        if not overlay:
            return [], {}, 0
        if patched_fw is not None:
            for off, b in overlay.items():
                elf[off:off + len(b)] = b
            with open(patched_fw, "wb") as f:
                f.write(bytes(elf))
            say("The game's own modes: %d change(s) baked into the rebuilt game program." % n,
                "info")
            return [], {}, n
        writes = []
        for off, b in sorted(overlay.items()):
            payload = b
            for disk, cnt in reader.disk_ranges(fw_node, off, len(b)):
                writes.append((disk, payload[:cnt]))
                payload = payload[cnt:]
        return writes, overlay, n
    except Exception as e:                      # never fail a Write over this
        say("The game's own modes: skipped (%s)." % e, "warning")
        return [], {}, 0
