"""Minimal 32-bit little-endian ARM ELF parser.

Extracts exactly what the emulator needs to boot ``game_real`` without any
captured side files:

  * PT_LOAD segments ``(vaddr, file_off, filesz, memsz)`` — to map the image.
  * dynamic GOT relocations ``(got_va, symbol_name)`` — so the harness can
    point each import's GOT slot at a stub sentinel and dispatch by name.

(Verified against the firmware's own relocation table: the parsed segments and
import names match the previously hand-captured ``fl_s_relocs.txt`` exactly.)
"""

import struct


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def parse_elf(raw):
    """Return ``(segments, relocs)`` for a 32-bit LE ELF.

    ``segments`` = ``[(p_vaddr, p_offset, p_filesz, p_memsz), ...]`` (PT_LOAD).
    ``relocs``   = ``[(got_va, symbol_name), ...]`` from ``.rel.plt`` /
    ``.rel.dyn`` (entries with a non-zero symbol index).
    """
    if raw[:4] != b"\x7fELF" or raw[4] != 1:
        raise ValueError("not a 32-bit ELF")
    e_phoff = _u32(raw, 0x1c); e_phentsize = _u16(raw, 0x2a); e_phnum = _u16(raw, 0x2c)
    e_shoff = _u32(raw, 0x20); e_shentsize = _u16(raw, 0x2e); e_shnum = _u16(raw, 0x30)
    e_shstrndx = _u16(raw, 0x32)

    segs = []
    for i in range(e_phnum):
        ph = e_phoff + i * e_phentsize
        if _u32(raw, ph) == 1:  # PT_LOAD
            segs.append((_u32(raw, ph + 8),   # p_vaddr
                         _u32(raw, ph + 4),   # p_offset
                         _u32(raw, ph + 16),  # p_filesz
                         _u32(raw, ph + 20))) # p_memsz

    # section headers (to find .dynsym / .dynstr / .rel.plt / .rel.dyn)
    shstr_off = _u32(raw, e_shoff + e_shstrndx * e_shentsize + 16)

    def _name(name_off):
        base = shstr_off + name_off
        return raw[base: raw.index(b"\x00", base)].decode()

    secs = {}
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        secs[_name(_u32(raw, sh))] = dict(
            off=_u32(raw, sh + 16), size=_u32(raw, sh + 20))

    dynsym = secs.get(".dynsym"); dynstr = secs.get(".dynstr")

    def _symname(idx):
        nameoff = _u32(raw, dynsym["off"] + idx * 16)
        base = dynstr["off"] + nameoff
        return raw[base: raw.index(b"\x00", base)].decode()

    relocs = []
    for relname in (".rel.plt", ".rel.dyn"):
        s = secs.get(relname)
        if not s:
            continue
        for i in range(s["size"] // 8):
            r = s["off"] + i * 8
            r_offset = _u32(raw, r)
            sym = _u32(raw, r + 4) >> 8
            if sym:
                relocs.append((r_offset, _symname(sym)))
    return segs, relocs
