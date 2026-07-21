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

# Values are shown in the firmware's own internal units.  We previously
# assumed the master volume displayed as internal/4 (a 0-16 menu scale), but
# monkeybug's hardware test (LZ LE 1.22, 2026-07-20) disproved it: his
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
        self.table_va, self.count, self.elem, self.node = self._find_section()
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
    def _find_names(self):
        ad_va = {}
        for m in _AD_RE.finditer(self.data):
            va = self._va(m.start())
            if va is not None:
                ad_va[va] = self.data[m.start():m.end() - 1].decode("latin1")
        va_set = set(ad_va)
        best = []
        for po, pv, fsz in self._loads:
            i, run = po, []
            while i < po + fsz - 3:
                w = struct.unpack_from("<I", self.data, i)[0]
                if w in va_set:
                    v = pv + (i - po)
                    if run and v - run[-1] != 4:
                        if len(run) > len(best):
                            best = run
                        run = []
                    run.append(v)
                i += 4
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
                        return table, count, elem, node_s
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
# (name, label, kind, help, scale) — scale is the internal-per-display factor
# (internal = display * scale); 1 for everything except the master volume.
CURATED = [
    ("AD_FREE_PLAY", "Free Play", "toggle",
     "Boot the game in free play (no credits needed).", 1),
    ("AD_SOUND_MASTER_VOLUME_SETTING", "Master Volume", "number",
     "Default master volume, in the firmware's own 0-64 units. UNVERIFIED "
     "on real machines: titles with a first-boot setup wizard (Guided "
     "Setup) pick their own volume and may ignore this default.", 1),
    ("AD_LANGUAGE", "Language", "enum",
     "Default menu / game language.", 1),
    ("AD_REPLAY_PERCENTAGE", "Replay Percentage", "number",
     "Target percentage of games that earn a replay.", 1),
    ("AD_CREDIT_LIMIT", "Credit Limit", "number",
     "Maximum credits the machine will bank.", 1),
    ("AD_MAX_PLAYERS_PER_GAME", "Max Players Per Game", "number", "", 1),
    ("AD_BALLS_PER_GAME", "Balls Per Game", "number", "", 1),
    ("AD_FREE_GAME_LIMIT", "Free Game Limit", "number", "", 1),
    ("AD_BALL_SAVE_TIME", "Ball Save Time", "number", "", 1),
    ("AD_TILT_WARNINGS", "Tilt Warnings", "number", "", 1),
]

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


def curated_rows(table):
    """One row per curated setting this build exposes, in DISPLAY units.

    Each row: ``{name, label, kind, help, default, min, max, scale, labels}``
    where default/min/max are what the operator menu shows (internal value //
    scale), ``scale`` is the internal-per-display factor (so internal =
    display * scale), and ``labels`` maps a display value to its text for
    enums (else None).  A scale that doesn't divide the internal range evenly
    is ignored (shown as stored) so a build that doesn't match the assumption
    can't produce nonsense."""
    rows = []
    for name, label, kind, help_, scale in CURATED:
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
            "scale": scale, "labels": labels,
            "default": e["default"] // scale,
            "min": e["min"] // scale,
            "max": e["max"] // scale,
        })
    return rows
