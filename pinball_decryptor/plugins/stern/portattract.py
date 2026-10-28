"""PAD-782: the game's attract cycle, read off a Spike 2 build's own program.

The attract mode of every Spike 2 build is one process (the attract SEQUENCER) walking a table of pages. Each entry
names a test (shown this time round? 0 = always) and a page: a function the sequencer starts as a process of its own,
a child it waits for, one page at a time; the flipper buttons step back and on through the table (the sequencer kills
the page). Two generations (emulator and program, 2026-10-27):

- Godzilla LE/Pro 1.16 (the older framework): 16-byte entries ``{test, page, float seconds, flags}`` at table + 8, a
  fixed count (``cmp r4, #90``: 91 entries, all used); the seconds go to the page process (+0xb0, frames).
- James Bond LE 1.06 (the newer): 8-byte entries ``{test, page}``, the table ends at the first entry with no page.

Both start a page the same way::

    ldr  rP, [rE, #<page>] ; mov r1, #0 ; bl <process create> ; cmp r0, #0 ; [beq] ; str(ne) rC, [r0, #0xa0]
    ... mov r0, #1 ; bl <process sleep: a frame>

with the table's address in a ``movw/movt`` pair of the same function and the test called through ``blx r3``.

The runtime (pad_mode_runtime.c "attract items") puts an item of the owner's between two of the game's pages by
pointing ONE entry's page at a page of its own: the game's page runs as it was, then (in the same process, which the
sequencer waits for) each item after it plays while the process sleeps a frame at a time. Nothing is added to the
table and nothing else of the game's moves; a flipper or a game start ends the process, and our item with it.

The port lines::

    data  attract_table       first entry
    value attract_entry_size  16 or 8
    value attract_page_at     the page's offset in an entry (4)
    value attract_count       entries
    site  attract_sleep       the process sleep (frames)
"""
from __future__ import annotations

import struct

from .portchallenge import Elf, bl_target

#: `str(ne) rX, [r0, #0xa0]`: the sequencer stamps the cycle on the page process it just made
_STAMP_MASK, _STAMP = 0x0FFF0FFF, 0x058000A0
#: entries the runtime will look at (pad_mode_runtime.c ATT_ENTRIES)
MAX_ENTRIES = 160


def _imm16(x):
    return (x >> 4 & 0xF000) | (x & 0xFFF)


def _ldr_imm(x):
    """``(rd, rn, offset)`` of `ldr rd, [rn, #+off]`, or None."""
    if x & 0xFFF00000 != 0xE5900000:
        return None
    return x >> 12 & 15, x >> 16 & 15, x & 0xFFF


class Sequencer:
    """The attract sequencer of a build: where its table is and how it reads it."""

    def __init__(self, base, entry, size, pred_at, page_at, count, create, sleep, at):
        self.base, self.entry, self.size = base, entry, size
        self.pred_at, self.page_at, self.count = pred_at, page_at, count
        self.create, self.sleep, self.at = create, sleep, at

    def entries(self, e):
        """``[(test, page, seconds or None), ...]`` read off the program."""
        out = []
        for k in range(self.count):
            va = self.entry + self.size * k
            if e.off(va + self.size - 1) is None:
                break
            test, page = e.word(va), e.word(va + self.page_at)
            secs = None
            if self.size > 8:
                secs = struct.unpack("<f", struct.pack("<I", e.word(va + 8)))[0]
            out.append((test, page, secs))
        return out


def _base_reg_value(w, lo, hi, reg):
    """The movw/movt pair loading *reg* in words w[lo:hi] (the last one), as an address."""
    val = None
    for i in range(lo, hi):
        x = w[i]
        if x & 0xFFF00000 == 0xE3000000 and x >> 12 & 15 == reg:
            for j in range(i + 1, min(hi, i + 8)):
                y = w[j]
                if y & 0xFFF00000 == 0xE3400000 and y >> 12 & 15 == reg:
                    val = _imm16(x) | _imm16(y) << 16
                    break
    return val


def _is_code(e, va):
    o = e.off(va) if va else None
    return o is not None and not va & 3 and e.text_va <= va < e.text_va + 4 * len(e.words)


def _stride(e, entry, cap=MAX_ENTRIES):
    """``(stride, run)``: the entry size (8, 12 or 16) under which the most entries in a row starting at *entry*
    hold a page that is code and a test that is 0 or code, and that run."""
    best = (0, 0)
    for s in (8, 12, 16):
        k = 0
        while k < cap and e.off(entry + s * k + 7) is not None:
            test, page = e.word(entry + s * k), e.word(entry + s * k + 4)
            if not _is_code(e, page) or (test and not _is_code(e, test)):
                break
            k += 1
        if k > best[1]:
            best = (s, k)
    return best


def find(e):
    """The build's :class:`Sequencer`, or None when the program has not exactly one."""
    if not isinstance(e, Elf):
        e = Elf(e)
    w, base = e.words, e.text_va
    n = len(w)
    found = []
    for i in range(8, n - 16):
        if w[i] & _STAMP_MASK != _STAMP or w[i] >> 28 not in (0x1, 0xE):
            continue
        # bl <create> at most eight words before (cmp r0, #0 ; [beq] ; the process's other fields)
        k = next((k for k in range(i - 2, i - 9, -1)
                  if bl_target(base + 4 * k, w[k]) is not None and 0xE3A01000 in w[k - 3:k]), None)   # mov r1, #0
        if k is None:
            continue
        create = bl_target(base + 4 * k, w[k])
        # the page: `ldr rP, [rE, #q]` just before (q: the page's offset from the table register's address)
        page = None
        for j in range(k - 1, max(k - 9, 0), -1):
            got = _ldr_imm(w[j])
            if got and 4 <= got[2] <= 0x1000 and not got[2] & 3 and got[0] in (0, 3):
                page = got
                break
        if page is None:
            continue
        # mov r0, #1 ; bl <sleep> soon after
        sleep = None
        for j in range(i + 1, min(n - 1, i + 16)):
            if w[j] == 0xE3A00001 and bl_target(base + 4 * (j + 1), w[j + 1]) is not None:
                sleep = bl_target(base + 4 * (j + 1), w[j + 1])
                break
        if sleep is None:
            continue
        # the function: back to its push, at most 1000 words
        start = next((j for j in range(k, max(k - 1000, -1), -1) if w[j] & 0xFFFF4000 == 0xE92D4000), None)
        if start is None:
            continue
        body = w[start:min(n, i + 200)]
        if not any(x & 0xFFFFFFF0 == 0xE12FFF30 for x in body):          # blx rN: the entry's test
            continue
        # the table: an address a movw/movt pair of the function loads, whose entries (test at q - 4, page at q,
        # 8, 12 or 16 bytes apart) hold the longest run of pages
        best = None
        for reg in range(13):
            tbl = _base_reg_value(w, start, i, reg)
            if tbl is None or e.off(tbl) is None:
                continue
            entry = tbl + page[2] - 4
            size, run = _stride(e, entry)
            if run >= 4 and (best is None or run > best[2]):
                best = (tbl, entry, run, size)
        if best is None:
            continue
        tbl, entry, run, size = best
        # a fixed count: the index's `cmp rI, #imm` (91 on Godzilla, 55 on Deadpool), else the run to the first
        # entry with no page (Bond)
        cmps = [x & 0xFF for x in body if x & 0xFFF0FF00 == 0xE3500000 and 8 <= x & 0xFF < 255]
        count = max(cmps) + 1 if cmps and max(cmps) + 1 <= run else run
        if not 2 <= count <= MAX_ENTRIES:
            continue
        found.append(Sequencer(tbl, entry, size, 0, 4, count, create, sleep, base + 4 * start))
    uniq = {(s.entry, s.size, s.count): s for s in found}
    return next(iter(uniq.values())) if len(uniq) == 1 else None


def lines(e):
    """The port lines for the build's attract table (empty when it has none the runtime can use)."""
    if not isinstance(e, Elf):
        e = Elf(e)
    s = find(e)
    if s is None:
        return []
    return ["# PAD-782: the attract mode's page table (portattract.py); an owner's attract items play between its pages",
            "data  attract_table       0x%08x" % s.entry,
            "value attract_entry_size  %d" % s.size,
            "value attract_page_at     %d" % s.page_at,
            "value attract_count       %d" % s.count,
            "site  attract_sleep       0x%08x 0x%08x 0x%08x" % (s.sleep, e.word(s.sleep), e.word(s.sleep + 4))]
