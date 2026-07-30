"""Spike 2 operator-adjustment DEFAULT decoder + patcher (game ELF).

Operator settings/adjustments are NOT on the SD card — they live in the board's
i2c NVRAM.  The one card-editable lever is the COMPILED DEFAULT in the game ELF
(``game_real``): the game copies these into NVRAM on a fresh flash / factory
reset, so patching e.g. free-play's default flips a fresh card to free play.  A
machine that already has a stored value keeps it and ignores the default.

The layout was reverse-engineered across Led Zeppelin (1.21/1.22) and Elvira HoH
(see ``plans/spike2_settings_defaults_handoff.md``):

  * ``names[]`` — a packed ``char*[N]`` of the ``AD_*`` strings, indexed by
    adjustment id (``AD_INVALID`` = 0).
  * a ``.data`` section record ``{live, table, count, elem, node}`` whose
    ``count == len(names)`` and ``elem`` is the per-entry struct size (44 bytes
    on LZ, 32 on Elvira — the record carries it, so we never assume).
  * the descriptor array at ``table``: ``count`` entries of ``elem`` bytes, with
    STABLE field offsets ``default @+0x04, min @+0x08, max @+0x0c`` and
    ``step @+0x10``.

Everything is derived from the ELF bytes alone; patching a default is
size-neutral (one 4-byte field), so the card's ``.sidx`` refresh applies
unchanged.  This module is pure (bytes in / bytes out); the ext4 read/write and
sidx refresh live in :mod:`.explorer`.
"""
import re
import struct

_AD_RE = re.compile(rb"AD_[A-Z0-9_]{2,80}\x00")
OFF_DEFAULT, OFF_MIN, OFF_MAX, OFF_STEP = 0x04, 0x08, 0x0c, 0x10
# Later in the same descriptor: the operator menu's own caption for this
# adjustment ("GRAND CHAMPION SCORE") and its one-line help ("Change the
# default Grand Champion Score.").  Used by :mod:`.high_scores` to tie a
# high-score record to the adjustment holding that slot's default score.
OFF_MENU_LABEL, OFF_MENU_HELP = 0x18, 0x20

# Values are shown in the firmware's own internal units.  We previously
# assumed the master volume displayed as internal/4 (a 0-16 menu scale), but
# a tester's hardware test (LZ LE 1.22, 2026-07-20) disproved it: his
# machine's Guided Setup shows raw values (default 30 on a raw scale) that
# don't come from this compiled default at all, so the display transform —
# and whether the default even reaches the operator's volume on wizard
# titles — is title-dependent and unconfirmed.  Until that's properly RE'd,
# no scale is applied anywhere and the volume row's help says so.  The
# per-row ``scale`` plumbing stays (presets store internal units through it).

# Enum value -> label for the enum settings we expose.  The stored value is an
# index; the machine shows the label.  Language index 0 = English is confirmed
# on-machine; 1..4 follow the standard Stern order.  The editor always shows the
# index next to the label so the exact value is never hidden.
LANGUAGE_LABELS = ["English", "German", "French", "Spanish", "Italian"]
ONOFF_LABELS = ["Off", "On"]


def _load_segments(data):
    """PT_LOAD segments as ``[(file_off, vaddr, filesz), ...]`` from the ELF
    program headers (manual parse — no pyelftools dependency).  Returns [] if
    it isn't a little-endian 32-bit ELF."""
    if len(data) < 0x34 or data[:4] != b"\x7fELF":
        return []
    if data[4] != 1 or data[5] != 1:            # 32-bit, little-endian
        return []
    e_phoff = struct.unpack_from("<I", data, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", data, 0x2c)[0]
    segs = []
    for i in range(e_phnum):
        base = e_phoff + i * e_phentsize
        if base + 32 > len(data):
            break
        p_type, p_offset, p_vaddr, _pa, p_filesz = struct.unpack_from(
            "<IIIII", data, base)
        if p_type == 1:                          # PT_LOAD
            segs.append((p_offset, p_vaddr, p_filesz))
    return segs


class AdjustmentTable:
    """Decode (and patch) the adjustment-default table of a game ELF held in
    memory as ``bytes``.  Raises :class:`ValueError` if the table can't be
    located (an unrecognised build — the caller falls back to no editor)."""

    def __init__(self, elf_bytes):
        self.data = bytes(elf_bytes)
        self._loads = _load_segments(self.data)
        if not self._loads:
            raise ValueError("not a little-endian 32-bit ELF")
        self.names = self._find_names()
        (self.table_va, self.count, self.elem, self.node,
         self.record_va) = self._find_section()
        self.by_name = {n: i for i, n in enumerate(self.names) if n}

    # --- address mapping ---
    def _off(self, va):
        for po, pv, fsz in self._loads:
            if pv <= va < pv + fsz:
                return po + (va - pv)
        return None

    def _va(self, off):
        for po, pv, fsz in self._loads:
            if po <= off < po + fsz:
                return pv + (off - po)
        return None

    def _cstr(self, va, n=90):
        o = self._off(va)
        if o is None:
            return None
        e = self.data.find(b"\x00", o, o + n)
        if e < 0:
            return None
        try:
            s = self.data[o:e].decode("latin1")
        except Exception:
            return None
        return s if s.isprintable() else None

    # --- discovery ---
    def _words(self, po, fsz):
        """``(base_offset, memoryview of u32)`` over a PT_LOAD's aligned words.

        The name hunt has to look at every word of every loadable segment, and
        the biggest game ELFs are ~190 MB (Rush) — a per-word
        ``struct.unpack_from`` there costs seconds, a cast memoryview about a
        fifth of that.
        """
        base = (po + 3) & ~3
        n = (po + fsz - base) // 4
        if n <= 0:
            return base, memoryview(b"").cast("I")
        return base, memoryview(self.data)[base:base + n * 4].cast("I")

    def _find_names(self):
        ad_va = {}
        for m in _AD_RE.finditer(self.data):
            va = self._va(m.start())
            if va is not None:
                ad_va[va] = self.data[m.start():m.end() - 1].decode("latin1")
        va_set = set(ad_va)
        best = []
        for po, pv, fsz in self._loads:
            base, words = self._words(po, fsz)
            run = []
            for j, w in enumerate(words):
                if w in va_set:
                    v = pv + (base + 4 * j - po)
                    if run and v - run[-1] != 4:
                        if len(run) > len(best):
                            best = run
                        run = []
                    run.append(v)
            if len(run) > len(best):
                best = run
        if not best:
            raise ValueError("no AD_ name array found")
        # Walk contiguously from the run base so any non-AD slot is still
        # counted (keeps the id index aligned with the descriptor array).
        names, va = [], best[0]
        while True:
            w = struct.unpack_from("<I", self.data, self._off(va))[0]
            if w in va_set:
                names.append(ad_va[w])
            else:
                s = self._cstr(w) if w else None
                if names and (not s or not s.startswith("AD_")):
                    break
                names.append(s or "")
            va += 4
            if len(names) > 6000:
                break
        return names

    def _find_section(self):
        target = len(self.names)
        for po, pv, fsz in self._loads:
            i = po
            while i <= po + fsz - 20:      # record spans i..i+20 (node @ +16)
                count = struct.unpack_from("<I", self.data, i + 8)[0]
                elem = struct.unpack_from("<I", self.data, i + 12)[0]
                if count == target and 24 <= elem <= 96 and elem % 4 == 0:
                    table = struct.unpack_from("<I", self.data, i + 4)[0]
                    node = struct.unpack_from("<I", self.data, i + 16)[0]
                    node_s = self._cstr(node, 16)
                    if self._off(table) is not None and node_s:
                        # The record's own VA matters too: the firmware passes
                        # ``record + 4`` (table/count/elem) to the accessor the
                        # operator menu walks, which is how
                        # :mod:`.menu_visibility` finds the menu's pages.
                        return table, count, elem, node_s, self._va(i)
                i += 4
        raise ValueError("adjustment section record not found")

    # --- read ---
    def _s32(self, off):
        return struct.unpack_from("<i", self.data, off)[0]

    def entry(self, idx):
        o = self._off(self.table_va + idx * self.elem)
        return {"id": idx, "name": self.names[idx],
                "default": self._s32(o + OFF_DEFAULT),
                "min": self._s32(o + OFF_MIN),
                "max": self._s32(o + OFF_MAX),
                "step": self._s32(o + OFF_STEP)}

    def get(self, name):
        return self.entry(self.by_name[name])

    def default_file_offset(self, name):
        idx = self.by_name[name]
        return self._off(self.table_va + idx * self.elem + OFF_DEFAULT)

    def sane(self):
        """True iff default in [min,max] for a strong majority of entries — a
        sanity gate before trusting an unfamiliar build for a write."""
        ok = 0
        for i in range(self.count):
            e = self.entry(i)
            if e["min"] <= e["default"] <= e["max"] and e["min"] <= e["max"]:
                ok += 1
        return ok >= int(self.count * 0.95)

    # --- patch ---
    def patched_bytes(self, overrides):
        """Return a copy of the ELF with each ``{name: value}`` default set,
        validated against that adjustment's own min/max.  Raises ValueError on
        an unknown name or out-of-range value."""
        buf = bytearray(self.data)
        for name, value in overrides.items():
            if name not in self.by_name:
                raise ValueError("unknown adjustment %r" % name)
            e = self.get(name)
            value = int(value)
            if not (e["min"] <= value <= e["max"]):
                raise ValueError("%s = %d out of range [%d, %d]"
                                 % (name, value, e["min"], e["max"]))
            struct.pack_into("<i", buf, self.default_file_offset(name), value)
        return bytes(buf)


# ---------------------------------------------------------------------------
# Curated display set: the operator settings a modder actually wants to preset
# on a fresh image, shown in the SAME units/labels the machine's menu uses.
# Only settings whose on-machine display we've verified are listed — the
# index-based enums whose option labels aren't RE'd yet (Game Pricing's 73
# schemes, the External Volume Knob options) are deliberately left out rather
# than shown as raw numbers.  ``kind`` drives the editor widget:
#   "toggle" (on/off), "number" (spinbox, in display units), "enum" (dropdown).
# ---------------------------------------------------------------------------
# (name, label, kind, help, scale, group) — scale is the internal-per-display
# factor (internal = display * scale); 1 for everything except the master
# volume.  ``group`` heads the block the row is drawn under, and the list is
# kept in group order: a tester read one flat column and asked "is there any
# particular logic to the order of the fields?", which there was, but nothing
# on screen said so.
GROUP_GAME = "Game"
GROUP_SOUND = "Sound"
GROUP_LIGHTING = "Lighting"
GROUP_INSIDER = "Insider Connected"
GROUP_HIGH_SCORES = "High scores"

CURATED = [
    ("AD_FREE_PLAY", "Free Play", "toggle",
     "Boot the game in free play (no credits needed).", 1, GROUP_GAME),
    ("AD_LANGUAGE", "Language", "enum",
     "Default menu / game language.", 1, GROUP_GAME),
    ("AD_REPLAY_PERCENTAGE", "Replay Percentage", "number",
     "Target percentage of games that earn a replay.", 1, GROUP_GAME),
    ("AD_CREDIT_LIMIT", "Credit Limit", "number",
     "Maximum credits the machine will bank.", 1, GROUP_GAME),
    ("AD_MAX_PLAYERS_PER_GAME", "Max Players Per Game", "number", "", 1,
     GROUP_GAME),
    ("AD_BALLS_PER_GAME", "Balls Per Game", "number", "", 1, GROUP_GAME),
    ("AD_FREE_GAME_LIMIT", "Free Game Limit", "number", "", 1, GROUP_GAME),
    ("AD_BALL_SAVE_TIME", "Ball Save Time", "number", "", 1, GROUP_GAME),
    ("AD_TILT_WARNINGS", "Tilt Warnings", "number", "", 1, GROUP_GAME),
    ("AD_SOUND_MASTER_VOLUME_SETTING", "Master Volume", "number",
     "Default master volume, in the firmware's own 0-64 units. UNVERIFIED "
     "on real machines: titles with a first-boot setup wizard (Guided "
     "Setup) pick their own volume and may ignore this default.", 1,
     GROUP_SOUND),
    # The two attenuation trims a tester asked for (batch 23).  They sit in
    # the game's own adjustments rather than the standard/general ones, and
    # unlike most settings they are SIGNED — -60..+60 around 0, so a negative
    # value is the thing you actually want when call-outs are too loud.  There
    # is no game-SFX sibling on Led Zeppelin 1.22; only these two exist, so
    # only these two are offered (the Defaults tab's all-settings list is the
    # place to check a title that might carry more).
    ("AD_MUSIC_ATTENUATION", "Music Attenuation", "number",
     "Trim applied to music, in the firmware's own units — negative makes "
     "music quieter relative to everything else, 0 leaves it alone.", 1,
     GROUP_SOUND),
    ("AD_SPEECH_ATTENUATION", "Speech Attenuation", "number",
     "Trim applied to speech / call-outs — negative makes them quieter "
     "relative to music and effects, 0 leaves them alone.", 1, GROUP_SOUND),
    ("AD_KNOCKER_VOLUME", "Knocker Volume", "number",
     "How loud the knocker fires.", 1, GROUP_SOUND),
    # Brightness family (feedback batch 21 — he wants the in-game backbox
    # default).  All are plain 0/25-100 ranges, i.e. the percentage the
    # operator menu shows; display verification on hardware still pending,
    # same caveat class as the master volume.
    ("AD_BACKBOX_BRIGHTNESS", "Backbox Brightness", "number",
     "Backbox brightness outside a game (attract / menus), as a "
     "percentage.", 1, GROUP_LIGHTING),
    ("AD_GAME_BACKBOX_BRIGHTNESS", "Backbox Brightness In Game", "number",
     "Backbox brightness while a game is being played, as a percentage — "
     "lower it to keep the backbox from washing out the playfield.", 1,
     GROUP_LIGHTING),
    ("AD_CABINET_BRIGHTNESS", "Cabinet Brightness", "number",
     "Cabinet lighting brightness, as a percentage.", 1, GROUP_LIGHTING),
    ("AD_GI_BRIGHTNESS", "GI Brightness", "number",
     "General-illumination brightness, as a percentage.", 1, GROUP_LIGHTING),
    ("AD_LED_BRIGHTNESS", "LED Brightness", "number",
     "Playfield LED brightness, as a percentage.", 1, GROUP_LIGHTING),
    ("AD_FLASHER_BRIGHTNESS", "Flasher Brightness", "number",
     "Flasher brightness, as a percentage.", 1, GROUP_LIGHTING),
    # Insider Connected (feedback batch 23).  Note there is NO master
    # on/off adjustment: whether the machine talks to Insider Connected at
    # all is decided by its registration and its dongle, not by a setting the
    # card carries.  What IS card-settable is how it behaves once connected,
    # which is what these are.  The MESSAGE OF THE DAY setting only decides
    # whether the message is DISPLAYED — the text is served to the machine,
    # not stored on the card, so there is nothing here to type it into.
    ("AD_INSIDER_CONNECTED_MESSAGE_OF_DAY", "Display Message Of The Day",
     "toggle",
     "Show the Insider Connected message of the day in attract mode. The "
     "text itself comes from Insider Connected, not from the card.", 1,
     GROUP_INSIDER),
    ("AD_HOW_TO_CONNECT_MESSAGE", "Show How To Connect Message", "toggle",
     "Show the \"how to connect\" prompt in attract mode.", 1, GROUP_INSIDER),
    ("AD_INSIDER_CONNECTED_HOME_TEAM_ACTIVE_MODE", "Enable Home Team",
     "number", "Home Team mode.", 1, GROUP_INSIDER),
    ("AD_INSIDER_CONNECTED_HOME_TEAM_PRELOAD_FIRST_USER",
     "Home Team Menu Logs In User #1", "toggle", "", 1, GROUP_INSIDER),
    ("AD_INSIDER_CONNECTED_HOME_TEAM_GUEST_RETENTION",
     "Home Team Guest Retention", "number", "", 1, GROUP_INSIDER),
    ("AD_NET_LOGIN_TIMER", "Insider Login Timer", "number",
     "Seconds the login prompt stays up.", 1, GROUP_INSIDER),
    ("AD_NET_PLAY_AGAIN_TIMER", "Insider Play Again Timer", "number",
     "Seconds the play-again prompt stays up.", 1, GROUP_INSIDER),
    ("AD_CUSTOM_MESSAGE", "Custom Message", "toggle",
     "Show the game's custom attract message. The wording itself is an "
     "on-screen string — edit it on the Replace Text tab.", 1, GROUP_INSIDER),
    # High-score defaults (feedback batch 22).  These are the scores the
    # machine seeds its high-score table with on a fresh flash / factory
    # reset.  The initials and player names that go with them live in their
    # own table in the same ELF and are edited in the High Scores block the
    # GUI builds out of these rows (see plugins.stern.high_scores).
    ("AD_ALLOW_HIGH_SCORES", "Allow High Scores", "toggle",
     "Whether the game records high scores at all.", 1, GROUP_HIGH_SCORES),
    ("AD_HSTD_RESET_COUNT", "Reset High Scores After", "number",
     "Number of games after which the high-score table resets itself "
     "(0 = never).", 1, GROUP_HIGH_SCORES),
    ("AD_GRAND_CHAMPION_SCORE", "Grand Champion Score", "number",
     "Default Grand Champion score on a fresh flash / factory reset.", 1,
     GROUP_HIGH_SCORES),
    ("AD_HIGH_SCORE_1_SCORE", "High Score 1", "number",
     "Default first-place score on a fresh flash / factory reset.", 1,
     GROUP_HIGH_SCORES),
    ("AD_HIGH_SCORE_2_SCORE", "High Score 2", "number",
     "Default second-place score on a fresh flash / factory reset.", 1,
     GROUP_HIGH_SCORES),
    ("AD_HIGH_SCORE_3_SCORE", "High Score 3", "number",
     "Default third-place score on a fresh flash / factory reset.", 1,
     GROUP_HIGH_SCORES),
    ("AD_HIGH_SCORE_4_SCORE", "High Score 4", "number",
     "Default fourth-place score on a fresh flash / factory reset.", 1,
     GROUP_HIGH_SCORES),
]

# Per-mode champion thresholds are title-specific — Led Zeppelin ships ~30 of
# them, an older title none — so they can't be listed in CURATED by name.  They
# are picked up generically instead, and the label is derived from the name.
# The naming shapes come from the same 34-card census as
# :data:`_SLOT_SUFFIX_RE` below, minus the multi-place high-score TABLES
# (AD_..._HIGH_SCORE_n_SCORE, AD_..._HSTD_n): those are the co-op / 2-team /
# home-team boards, whose four-plus places would swamp the editor and whose
# main slots are already curated by name.  The _AWARD / _AWARDS siblings are
# award counts, not scores, so they never match.
_CHAMPION_SUFFIX_RE = re.compile(
    r"_(?:CHAMPION_SCORE|CHAMP_SCORE|CHAMPION|CHAMP)$")

# Words that must not be title-cased when a label is derived from an AD_ name.
_ACRONYMS = {"GI", "LED", "TOTC", "HSTD", "EM", "4P", "2P", "3P"}

# Words whose plain capitalisation reads wrong (the co-op / team boards).
_WORD_FIXES = {"COOP": "Co-op", "2TEAM": "2-Team", "3TEAM": "3-Team",
               "4TEAM": "4-Team", "2112": "2112"}


def _label_from_name(name):
    """Human label for an ``AD_*`` adjustment with no curated entry:
    ``AD_ELECTRIC_MAGIC_FRENZY_CHAMPION`` -> ``Electric Magic Frenzy
    Champion``.  Known acronyms keep their capitals."""
    words = name[3:].split("_") if name.startswith("AD_") else name.split("_")
    out = []
    for w in words:
        if not w:
            continue
        if w in _WORD_FIXES:
            out.append(_WORD_FIXES[w])
        elif w in _ACRONYMS:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def champion_rows(table):
    """``(name, label, kind, help, scale, group)`` tuples for every per-mode
    champion threshold this build carries, in adjustment-id order (which is
    the order the game's own menu lists them in).  Empty for titles without
    them.

    Names already listed in :data:`CURATED` are skipped so the Grand Champion
    doesn't appear twice."""
    curated = {c[0] for c in CURATED}
    rows = []
    for name, _idx in sorted(table.by_name.items(), key=lambda kv: kv[1]):
        if name in curated or name in _NOT_SLOTS:
            continue
        if name.endswith(("_AWARD", "_AWARDS")):
            continue                    # what you win, not a score to beat
        if not _CHAMPION_SUFFIX_RE.search(name):
            continue
        rows.append((name, _label_from_name(name), "number",
                     "Default champion score for this mode on a fresh flash "
                     "/ factory reset.", 1, GROUP_HIGH_SCORES))
    return rows


#: Curated names that hold one of the high-score board's own values, so the
#: GUI can draw them in its High Scores block instead of the settings grid.
_CURATED_SCORE_NAMES = frozenset((
    "AD_GRAND_CHAMPION_SCORE", "AD_HIGH_SCORE_1_SCORE",
    "AD_HIGH_SCORE_2_SCORE", "AD_HIGH_SCORE_3_SCORE",
    "AD_HIGH_SCORE_4_SCORE"))


def is_score_adjustment(name):
    """True when *name* holds a score on the machine's high-score board.

    The GUI keeps every one of these together under High Scores.  Matching by
    NAME rather than by "did we find its initials/player-name record?" is the
    point: Led Zeppelin's BLACK DOG CHAMPION has no such record, so it used to
    be the one champion left stranded up in the settings grid between Allow
    High Scores and Reset High Scores After (a tester's red circle)."""
    if name in _CURATED_SCORE_NAMES:
        return True
    if name in _NOT_SLOTS or name.endswith(("_AWARD", "_AWARDS")):
        return False
    return bool(_CHAMPION_SUFFIX_RE.search(name))


# Every score the machine's high-score board records — the four high scores,
# the Grand Champion, and each mode/challenge champion — is one adjustment in
# this same table, but Stern renamed the family several times over the Spike 2
# years.  A census of all 34 vendor cards on hand turned up six shapes:
#
#   AD_HIGH_SCORE_1_SCORE      four-place table (and its COOP_/2TEAM_/
#                              IMPOSSIBLE_/HOME_TEAM_/2P_COOP_… variants)
#   AD_GRAND_CHAMPION_SCORE    ..._CHAMPION_SCORE, incl. the co-op boards
#   AD_KASHMIR_CHAMPION        Led Zeppelin, Venom, Godzilla, TMNT, X-Men …
#   AD_SKILL_SHOT_CHAMP        James Bond 60th
#   AD_LOOP_CHAMPION_SCORE     Sword of Rage
#   AD_TOTC_CHALLENGE_TIME_HSTD_1   timed challenge boards (LZ, Rush,
#                              Jurassic Park, Avengers, Godzilla)
#
# plus a handful of one-off names (Iron Maiden's AD_SPINNER_MASTER,
# AD_FOI_COMBO_KING, …) that are recognised instead by having their own
# _AWARD/_AWARDS companion, which only a recorded champion carries.
_SLOT_SUFFIX_RE = re.compile(
    r"_(?:HIGH_SCORE_\d+_SCORE|CHAMPION_SCORE|CHAMP_SCORE"
    r"|CHAMPION|CHAMP|HSTD_\d+)$")

# "What do you win for beating one" settings, shared by every slot on the
# titles that have them — they read like slots but record nothing.
_NOT_SLOTS = frozenset(("AD_HSTD_CHAMPION", "AD_GAME_FEATURE_CHAMPION",
                        "AD_FEATURE_HSTD_TABLES"))


def high_score_names(names):
    """The adjustment names that are recorded high-score slots, in id order.

    Counting these answers "how many high scores does this game keep?" without
    an Extract (a tester).  Note this is deliberately broader than
    :func:`champion_rows`, which only offers the plain ``_CHAMPION`` scores for
    editing: here a co-op board or a timed-challenge board counts too.
    """
    known = {n for n in names if n}
    out = []
    for name in names:
        if not name or name.endswith(("_AWARD", "_AWARDS")):
            continue
        if name in _NOT_SLOTS:
            continue
        if (_SLOT_SUFFIX_RE.search(name)
                or name + "_AWARD" in known or name + "_AWARDS" in known):
            out.append(name)
    return out


# Per-setting enum labels (index -> text).  Only for enums whose option list is
# known; others stay out of CURATED.
_ENUM_LABELS = {"AD_LANGUAGE": LANGUAGE_LABELS}


def _labels_for(name, e):
    """``{value: label}`` for an enum setting, or ``None``.  A min0/max1 field
    is Off/On; a known enum uses its label list; anything else is None."""
    if e["min"] == 0 and e["max"] == 1:
        return {0: ONOFF_LABELS[0], 1: ONOFF_LABELS[1]}
    labels = _ENUM_LABELS.get(name)
    if labels and e["max"] < len(labels):
        return {i: labels[i] for i in range(e["min"], e["max"] + 1)}
    return None


def _is_caption(text):
    """True for a string that could really be an operator-menu caption.

    ``_cstr`` decodes latin-1 and ``str.isprintable`` happily accepts the
    high-byte soup that reading a pointer as text produces (``'Ø'`` and friends
    are printable), so a caption has to be plain ASCII with something
    alphanumeric in it before it can be trusted.
    """
    t = (text or "").strip()
    if len(t) < 2 or not all(32 <= ord(c) < 127 for c in t):
        return False
    return any(c.isalnum() for c in t)


def _caption_at(table, idx):
    """``(direct, indirect)`` caption candidates for one descriptor."""
    off = table._off(table.table_va + idx * table.elem)
    if off is None or OFF_MENU_LABEL + 4 > table.elem:
        return None, None
    va = struct.unpack_from("<I", table.data, off + OFF_MENU_LABEL)[0]
    if not va:
        return None, None
    direct = table._cstr(va, 64)
    indirect = None
    inner = table._off(va)
    if inner is not None and inner + 4 <= len(table.data):
        first = struct.unpack_from("<I", table.data, inner)[0]
        if first:
            indirect = table._cstr(first, 64)
    return direct, indirect


def _caption_mode(table):
    """Whether ``+0x18`` holds the caption or a pointer to a caption struct.

    The 44-byte descriptor generation stores the caption pointer inline; the
    32-byte one stores a pointer to a five-language caption struct whose first
    entry is the English caption.  Deciding per entry is unsafe — the four
    pointer bytes of the struct sometimes decode as a plausible little string
    ("8VU") — so the whole table votes once and every row follows the winner.
    """
    mode = getattr(table, "_caption_mode_cache", None)
    if mode:
        return mode
    direct = indirect = 0
    step = max(1, table.count // 40)
    for idx in range(1, table.count, step):
        d, i = _caption_at(table, idx)
        direct += _is_caption(d)
        indirect += _is_caption(i)
    mode = "indirect" if indirect > direct else "direct"
    table._caption_mode_cache = mode
    return mode


def menu_label(table, idx):
    """The caption the operator menu prints for adjustment *idx*.

    Falls back to a label derived from the ``AD_`` name when the build stores
    the caption somewhere this doesn't recognise."""
    d, i = _caption_at(table, idx)
    order = (i, d) if _caption_mode(table) == "indirect" else (d, i)
    for cand in order:
        if _is_caption(cand):
            return cand.strip()
    return _label_from_name(table.names[idx] or "")


def all_rows(table, statuses=None):
    """One display row per adjustment in the build, in the menu's own order.

    Read-only companion to :func:`curated_rows` — every setting the firmware
    carries, with the caption the machine itself would print and (when
    :mod:`.menu_visibility` could read the menu) whether the machine can reach
    it at all.  ``status`` is ``""`` for a normal Adjustments-menu setting,
    ``"service"`` for one edited on another service screen, ``"debug"`` for one
    no menu reaches, and ``None`` when the menu couldn't be read.
    """
    rows = []
    for i in range(1, table.count):
        name = table.names[i]
        if not name or not name.startswith("AD_"):
            continue
        e = table.entry(i)
        rows.append({
            "id": i, "name": name, "label": menu_label(table, i),
            "default": e["default"], "min": e["min"], "max": e["max"],
            "step": e["step"] or 1,
            "labels": _labels_for(name, e),
            "status": statuses.get(i) if statuses else None,
        })
    return rows


def curated_rows(table, statuses=None):
    """One row per curated setting this build exposes, in DISPLAY units.

    Each row: ``{name, label, kind, help, default, min, max, step, scale,
    labels, group, status}`` where default/min/max/step are what the operator
    menu shows (internal value // scale), ``scale`` is the internal-per-display
    factor (so internal = display * scale), ``step`` is the adjustment's own
    increment (high scores step by a million, not by one), and ``labels``
    maps a display value to its text for enums (else None).  A scale that
    doesn't divide the internal range evenly is ignored (shown as stored) so
    a build that doesn't match the assumption can't produce nonsense.

    ``group`` is the heading the row belongs under.  ``status`` is what
    :mod:`.menu_visibility` says about reaching it on the machine — ``""`` in
    the Adjustments menu, ``"service"`` edited on some other service screen,
    ``"debug"`` never shown, ``None`` when the caller didn't pass *statuses*
    or this build's menu couldn't be read.  Pass ``statuses(table)`` to get
    it; it is advisory only and never changes which rows are offered.

    The curated list comes first, then this build's per-mode champion
    thresholds (title-specific, matched generically — see
    :func:`champion_rows`)."""
    rows = []
    for name, label, kind, help_, scale, group in (
            list(CURATED) + champion_rows(table)):
        if name not in table.by_name:
            continue
        e = table.get(name)
        if scale != 1 and (e["max"] % scale or e["min"] % scale):
            scale = 1
        labels = _labels_for(name, e)
        k = "toggle" if (e["min"] == 0 and e["max"] == 1) else \
            ("enum" if labels else kind)
        rows.append({
            "name": name, "label": label, "kind": k, "help": help_,
            "scale": scale, "labels": labels, "group": group,
            "status": (statuses or {}).get(table.by_name[name]),
            "default": e["default"] // scale,
            "min": e["min"] // scale,
            "max": e["max"] // scale,
            # A step of 0 (or one that the scale doesn't divide) would make a
            # spinbox useless — fall back to 1.
            "step": max(1, e["step"] // scale) if e["step"] else 1,
        })
    return rows
