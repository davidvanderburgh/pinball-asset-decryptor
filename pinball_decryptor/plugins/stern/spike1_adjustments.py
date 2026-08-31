"""Spike 1 operator-adjustment decoder + default patcher (game ELF).

The Spike 1 counterpart of :mod:`.adjustments` (Spike 2).  Same principle:
operator settings live in the board's i2c NVRAM, and the one card-editable
lever is the COMPILED DEFAULT in the game ELF — the game copies these into
NVRAM on a fresh flash / factory reset, so patching e.g. the replay level's
default changes what a freshly-set-up machine starts with.  A machine that
already has a stored value keeps it.

The layout was reverse-engineered from the game ELF's own accessors
(``sys_adjustment_get_value`` / ``_get_default_value`` / ``_set_value``) and
verified across Game of Thrones, Ghostbusters, KISS and WWE WrestleMania:

  * ``adjustment_table_data`` — a symbol; the descriptor array, stride 32.
  * ``ADJUSTMENT_TABLE_DATA_ENTRY_COUNT`` — a symbol; the entry count (u32).
  * each 32-byte entry:  ``+0x00`` ptr to the RAM value block (unused here),
    ``+0x04`` default (i32), ``+0x08`` min (i32), ``+0x0c`` max (i32),
    ``+0x10`` step (i32), ``+0x18`` ptr to the adjustment's name (a 4-language
    ``char*[]``; ``[0]`` is English), ``+0x1c`` a type code (low 16 bits index
    the type table; the high bits are display flags).

Everything is derived from the ELF bytes alone via the symbol table, and
patching a default is size-neutral (one 4-byte field), so a downstream card
checksum/refresh applies unchanged.  This module is pure (bytes in / bytes
out); extracting the ELF from a card and writing it back live elsewhere.
"""
import struct

_EHDR = struct.Struct("<16sHHIIIIIHHHHHH")
_SHDR = struct.Struct("<IIIIIIIIII")
_SYM = struct.Struct("<IIIBBH")
_SHT_SYMTAB = 2

# entry field offsets (bytes), stride 32
_E_STRIDE = 32
_E_DEFAULT, _E_MIN, _E_MAX, _E_STEP = 0x04, 0x08, 0x0C, 0x10
_E_NAME_PTR, _E_TYPE = 0x18, 0x1C


class Spike1AdjustmentError(Exception):
    pass


class _Elf:
    """Minimal ELF32-LE reader: symbol table + virtual-address reads.

    A self-contained copy (the rig's ``tools/spike1_emu/s1elf.py`` has the
    same reader, but the plugin must not import from the rig tree)."""

    def __init__(self, data):
        if data[:6] != b"\x7fELF\x01\x01":
            raise Spike1AdjustmentError("not an ELF32 little-endian file")
        self.data = data
        (_ident, _type, _mach, _ver, _entry, _phoff, shoff, _flags,
         _ehsize, _phes, _phn, shentsize, shnum, _shstrndx) = \
            _EHDR.unpack_from(data, 0)
        self.sections = []
        for i in range(shnum):
            (name, styp, flags, addr, off, size, link, info, align,
             entsize) = _SHDR.unpack_from(data, shoff + i * shentsize)
            self.sections.append(dict(type=styp, addr=addr, off=off,
                                      size=size, link=link))
        self.syms = self._read_symbols()

    def _read_symbols(self):
        out = {}
        for sh in self.sections:
            if sh["type"] != _SHT_SYMTAB:
                continue
            strtab = self.sections[sh["link"]]
            stroff = strtab["off"]
            for o in range(sh["off"], sh["off"] + sh["size"], _SYM.size):
                st_name, st_value, _sz, _info, _oth, _shndx = \
                    _SYM.unpack_from(self.data, o)
                if not st_name or not st_value:
                    continue
                nend = self.data.index(b"\x00", stroff + st_name)
                name = self.data[stroff + st_name:nend].decode("latin1")
                out.setdefault(name, st_value)
        return out

    def sym(self, name):
        if name not in self.syms:
            raise Spike1AdjustmentError("symbol %r not in ELF" % name)
        return self.syms[name]

    def _file_off(self, vaddr, n):
        for sh in self.sections:
            if sh["off"] == 0 or sh["addr"] == 0:
                continue
            if sh["addr"] <= vaddr < sh["addr"] + sh["size"]:
                start = sh["off"] + (vaddr - sh["addr"])
                if start + n <= len(self.data):
                    return start
        return None

    def read(self, vaddr, n):
        off = self._file_off(vaddr, n)
        if off is None:
            raise Spike1AdjustmentError("vaddr 0x%x not mapped" % vaddr)
        return self.data[off:off + n]

    def u32(self, vaddr):
        return struct.unpack("<I", self.read(vaddr, 4))[0]

    def i32(self, vaddr):
        return struct.unpack("<i", self.read(vaddr, 4))[0]

    def cstr(self, vaddr, maxn=90):
        try:
            b = self.read(vaddr, maxn)
        except Spike1AdjustmentError:
            return None
        i = b.find(b"\x00")
        s = b[:i if i >= 0 else maxn]
        if s and all(9 <= c < 127 for c in s):
            return s.decode("latin1")
        return None


def _label_from_name(name):
    """Human title-case label from the firmware's ALL-CAPS name."""
    if not name:
        return ""
    return " ".join(w if (len(w) <= 2 or not w.isalpha()) else w.capitalize()
                    for w in name.split())


class Spike1Adjustments:
    """Decode the operator-adjustment defaults from a Spike 1 game ELF."""

    _COUNT_SYM = "ADJUSTMENT_TABLE_DATA_ENTRY_COUNT"
    _TABLE_SYM = "adjustment_table_data"

    def __init__(self, elf_bytes):
        self.elf = _Elf(elf_bytes)
        self._size = len(elf_bytes)
        self.table_va = self.elf.sym(self._TABLE_SYM)
        self.count = self.elf.u32(self.elf.sym(self._COUNT_SYM))
        if not (0 < self.count < 4096):
            raise Spike1AdjustmentError(
                "implausible adjustment count %d" % self.count)

    def entry(self, idx):
        """``{default, min, max, step, name, type}`` for adjustment *idx*.

        *name* is the English string (the first of the entry's 4-language
        name array); ``None`` if it can't be read.  ``type`` is the raw
        ``+0x1c`` code (low 16 bits = type-table index, high bits = flags)."""
        if not 0 <= idx < self.count:
            raise Spike1AdjustmentError("adjustment id %d out of range" % idx)
        base = self.table_va + idx * _E_STRIDE
        name_arr = self.elf.u32(base + _E_NAME_PTR)
        name = None
        if name_arr:
            try:
                name = self.elf.cstr(self.elf.u32(name_arr))
            except Spike1AdjustmentError:
                name = None
        return {
            "default": self.elf.i32(base + _E_DEFAULT),
            "min": self.elf.i32(base + _E_MIN),
            "max": self.elf.i32(base + _E_MAX),
            "step": self.elf.i32(base + _E_STEP),
            "name": name,
            "type": self.elf.u32(base + _E_TYPE),
        }

    def default_file_offset(self, idx):
        """File offset of adjustment *idx*'s compiled default (i32), for a
        size-neutral patch."""
        va = self.table_va + idx * _E_STRIDE + _E_DEFAULT
        off = self.elf._file_off(va, 4)
        if off is None:
            raise Spike1AdjustmentError("default for id %d not in file" % idx)
        return off

    def sane(self):
        """A quick self-check that the table decoded to real adjustments:
        the majority of entries have a name and min <= default <= max."""
        good = 0
        checked = 0
        for i in range(1, min(self.count, 40)):
            e = self.entry(i)
            checked += 1
            if e["name"] and e["min"] <= e["default"] <= e["max"]:
                good += 1
        return checked > 0 and good >= checked * 0.6

    def rows(self):
        """One display row per adjustment, in the settings tab's shape:
        ``{id, name, label, default, min, max, step, labels, status}``.

        ``name`` is a stable synthetic key (``AD_<id>``) so pending edits and
        selection keep working exactly like the Spike 2 all-settings list;
        ``label`` is the firmware's own human name.  ``labels`` is ``None``
        (per-value enum captions are a later enrichment) and ``status`` is
        ``None`` (no menu-visibility read on Spike 1 yet)."""
        out = []
        for i in range(1, self.count):
            e = self.entry(i)
            if not e["name"]:
                continue
            out.append({
                "id": i,
                "name": "AD_%d" % i,
                "label": _label_from_name(e["name"]),
                "default": e["default"],
                "min": e["min"],
                "max": e["max"],
                "step": e["step"] if e["step"] else 1,
                "labels": None,
                "status": None,
            })
        return out

    def patched_bytes(self, overrides):
        """Return the ELF bytes with the given ``{id: new_default}`` applied.

        Each new default is validated against the adjustment's own min/max and
        written as a size-neutral i32 in place, so any downstream card refresh
        (checksum/sidx) still applies unchanged."""
        data = bytearray(self.elf.data)
        for idx, value in overrides.items():
            e = self.entry(idx)
            if not (e["min"] <= value <= e["max"]):
                raise Spike1AdjustmentError(
                    "value %d for id %d is outside [%d, %d]"
                    % (value, idx, e["min"], e["max"]))
            off = self.default_file_offset(idx)
            struct.pack_into("<i", data, off, value)
        return bytes(data)
