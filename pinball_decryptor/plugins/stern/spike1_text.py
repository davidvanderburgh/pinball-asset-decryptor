"""Editable display text inside the Stern Spike 1 game program (PAD-869).

Spike 1 draws every word on its DMD from C strings in the static armel game
ELF (``<TITLE>/game``): mode titles, the KISS song names on the song-select
screen, award lines, settings captions.  The strings are reached the same way
as on Spike 2 — groups of five identical ``char*`` (one per UI language, then
a NULL) named ``lang_text_*`` in the ELF's own symbol table — so the Spike 2
reader and planner (:mod:`.progtext`, :mod:`.progreloc`) work on these
programs unchanged: KISS LE 1.41 offers 7,861 lines, every song title among
them, and the census sees every reference to all but a few hundred.

What differs is where LONGER text goes.  Spike 2 appends a new segment at the
end of the ELF and has the file grown inside the ext4 image.  A Spike 1 ELF
carries ~99 KB of ``.debug_frame`` that no PT_LOAD maps (the game never reads
it; only a debugger would), so the new segment's bytes go THERE instead and
are mapped, read-only, into the page-aligned hole between the text and data
segments (28-32 KB on every title but Ghostbusters, which has none) through
the ELF's PT_NOTE header (nothing on the machine reads it; PT_GNU_STACK is
the fallback).  The file keeps its size, so the edit is an in-place patch
through the ext file->disk map like every other Spike 1 write, and the card's
``.sidx`` record for the program is refreshed the way the settings-default
patch does it (:func:`.spike1.write_game_elf_defaults`).

The segment is mapped at its full size from the first write and carries the
same ``PADTXT01`` + used header as Spike 2's (:func:`.progreloc.
extension_segment`), so a second Write appends after the first one's text and
a re-Extract of a built card lists the live strings.
"""

import os
import struct

from . import progreloc, progtext

#: The Text tab's path for a Spike 1 program row, under the game folder.
PROGRAM_NAME = "game"

_PT_NOTE = 4
_SHT_STRTAB = 3
#: The unloaded section the extension segment's bytes are put in.
_SPARE_SECTION = b".debug_frame"


def _sections(raw):
    """``{name: (sh_offset, sh_size)}`` of the ELF *raw*'s sections; ``{}``
    when the section headers don't parse."""
    try:
        shoff = struct.unpack_from("<I", raw, 0x20)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", raw, 0x2e)
        if not shoff or shentsize < 40 or shstrndx >= shnum:
            return {}
        hdrs = [struct.unpack_from("<10I", raw, shoff + i * shentsize)
                for i in range(shnum)]
        str_off = hdrs[shstrndx][4]
        out = {}
        for h in hdrs:
            end = raw.index(b"\0", str_off + h[0])
            out[bytes(raw[str_off + h[0]:end])] = (h[4], h[5])
        return out
    except (struct.error, ValueError, IndexError):
        return {}


def _spare_slot(raw):
    """File offset of the program header the new segment takes (PT_NOTE,
    else PT_GNU_STACK), or ``None``."""
    phdrs = progreloc.iter_phdrs(raw)
    for t in (_PT_NOTE, progreloc.PT_GNU_STACK):
        for (o, pt, _off, _va, _fs, _ms, _fl, _al) in phdrs:
            if pt == t:
                return o
    return None


def segment_plan(raw):
    """Where longer text goes in the program *raw*: ``(reloc, new, why)``.

    *reloc* is the ``{"base_va", "capacity", "used"}`` dict
    :func:`.progtext.plan_writes` takes, or ``None`` (*why* says why the
    program can only take text that fits).  *new* is ``None`` when a previous
    Write's segment is reused, else ``{"slot", "off"}``: the program header
    to turn into its PT_LOAD and the file offset its bytes go at."""
    ext = progreloc.extension_segment(raw)
    if ext is not None:
        return ({"base_va": ext["base_va"], "capacity": ext["capacity"],
                 "used": ext["used"]}, None, "")
    hole = progreloc.text_data_hole(raw)
    if hole is None:
        return None, None, ("this game program has no free address space "
                            "between its code and its data")
    slot = _spare_slot(raw)
    if slot is None:
        return None, None, ("this game program has no spare program header "
                            "to map new space with")
    spare = _sections(raw).get(_SPARE_SECTION)
    if spare is None:
        return None, None, "this game program has no unused section to use"
    page = progreloc.PAGE
    loaded = [(off, off + fs) for (_va, off, fs, _ms, _fl)
              in progreloc.load_segments(raw)]
    off = (spare[0] + page - 1) & ~(page - 1)
    room = (spare[0] + spare[1] - off) & ~(page - 1)
    capacity = min(hole[1] - hole[0], room)
    if capacity < page or any(lo < off + capacity and off < hi
                              for lo, hi in loaded):
        return None, None, "this game program's unused section is too small"
    return ({"base_va": hole[0], "capacity": capacity,
             "used": progreloc.EXT_HEADER_LEN},
            {"slot": slot, "off": off}, "")


def scan(raw):
    """The program's editable lines as manifest rows (path left to the
    caller): ``[{"original", "budget", "grow"|"fixed", "unused"}]``.  A line
    is offered longer text only when this program can take a segment for it
    (:func:`segment_plan`); otherwise its budget is its own slot."""
    reloc, _new, _why = segment_plan(raw)
    rows = []
    for e in progtext.enumerate_program_strings(raw):
        row = {"original": e["text"], "budget": e["budget"]}
        if e.get("growable") and reloc is not None:
            row["grow"] = True
        else:
            row["fixed"] = True
            if e.get("growable"):
                # the census can move it, this program has nowhere to put it
                row["budget"] = len(progtext.decode_text(e["text"]))
        if e.get("refs") == 0:
            row["unused"] = True
        rows.append(row)
    return rows


def plan(raw, edits, log=None):
    """The file writes that put *edits* (``{original: replacement}``, in
    manifest form) into the program *raw*: ``([(file_offset, bytes)], n)``.
    Text that fits patches in place; longer text goes into the extension
    segment (created on the first write, see :func:`segment_plan`) with every
    reference the census sees pointed at it.  Every write keeps the file's
    size."""
    log = log or (lambda *a, **k: None)
    reloc, new, why = segment_plan(raw)
    if reloc is not None and os.environ.get("PAD_STERN_TEXT_GROW", "1") == "0":
        # the Write tab's "grow ... for longer text" option, switched off
        reloc, new, why = None, None, "the option to grow for longer text is off"
    writes, n, blob = progtext.plan_writes(raw, edits, log, reloc=reloc,
                                           no_grow_why=why)
    writes = list(writes)
    if not blob:
        return writes, n
    used = reloc["used"] + len(blob)
    if new is not None:
        off = new["off"]
        seg = bytearray(reloc["capacity"])
        seg[reloc["used"]:used] = blob
        seg[:progreloc.EXT_HEADER_LEN] = progreloc.extension_header(used)
        writes.append((new["slot"], struct.pack(
            "<8I", progreloc.PT_LOAD, off, reloc["base_va"],
            reloc["base_va"], reloc["capacity"], reloc["capacity"],
            4, progreloc.PAGE)))
        writes.append((off, bytes(seg)))
        how = "a new read-only segment"
    else:
        off = progreloc.extension_segment(raw)["seg_off"]
        writes.append((off + reloc["used"], bytes(blob)))
        writes.append((off, progreloc.extension_header(used)))
        how = "the segment an earlier build made"
    log("Program text: %d byte(s) of longer text placed at 0x%x in %s "
        "(the game program keeps its size)."
        % (len(blob), reloc["base_va"] + reloc["used"], how), "info")
    return writes, n
