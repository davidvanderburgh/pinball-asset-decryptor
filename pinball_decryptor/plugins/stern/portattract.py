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
            if self.size == 16:
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
        # bl <create> two or three words before (cmp r0, #0 ; [beq])
        k = next((k for k in (i - 2, i - 3) if bl_target(base + 4 * k, w[k]) is not None), None)
        if k is None or w[k - 1] != 0xE3A01000:            # mov r1, #0
            continue
        create = bl_target(base + 4 * k, w[k])
        # the page: `ldr r0, [rE, #q]` (or ldr r3 ... mov r0, r3) just before
        page = None
        for j in range(k - 2, max(k - 9, 0), -1):
            got = _ldr_imm(w[j])
            if got and got[2] in (4, 8, 0xC, 0x10):
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
        # the function: back to its push, at most 160 words
        start = next((j for j in range(k, max(k - 160, 0), -1) if w[j] & 0xFFFF4000 == 0xE92D4000), None)
        if start is None:
            continue
        body = w[start:min(n, i + 200)]
        if not any(x & 0xFFFFFFF0 == 0xE12FFF30 for x in body):          # blx rN: the entry's test
            continue
        size = None
        if any(x & 0xFFFF0FF0 == 0xE1A00200 for x in w[start:i]):         # lsl rX, rY, #4: 16-byte entries
            size = 16
        elif any(x & 0xFFF00FF0 == 0xE7900180 for x in w[start:i]):       # ldr rX, [rB, rI, lsl #3]
            size = 8
        if size is None:
            continue
        # the table register: the base of the test's load (16: `add r7, rB, r5`; 8: `ldr r3, [rB, r4, lsl #3]`)
        reg = None
        pred_at = 0
        for x in w[start:i]:
            if size == 8 and x & 0xFFF00FF0 == 0xE7900180:
                reg = x >> 16 & 15
                break
            got = _ldr_imm(x)
            if size == 16 and got and got[0] == 3 and got[2] in (0, 4, 8):
                pred_at = got[2]
        if size == 16:
            # `add rE, rB, rO` before the test's load: rB is the table's register
            for x in w[start:i]:
                if x & 0xFFF00FF0 == 0xE0800000 and (x & 15) != (x >> 16 & 15):
                    cand = x >> 16 & 15
                    if _base_reg_value(w, start, i, cand) is not None:
                        reg = cand
                        break
        if reg is None:
            continue
        tbl = _base_reg_value(w, start, i, reg)
        if tbl is None or e.off(tbl) is None:
            continue
        page_at = page[2] - pred_at
        if size == 8:
            entry, count = tbl, 0
            while count < MAX_ENTRIES and e.off(entry + 8 * count + 7) is not None \
                    and e.word(entry + 8 * count + 4):
                count += 1
        else:
            entry = tbl + pred_at
            cmps = [x & 0xFF for x in body if x & 0xFFFFFF00 == 0xE3540000]   # cmp r4, #imm
            if not cmps:
                continue
            count = max(cmps) + 1
        if not 2 <= count <= MAX_ENTRIES or page_at not in (4,):
            continue
        found.append(Sequencer(tbl, entry, size, 0, page_at, count, create, sleep, base + 4 * start))
    uniq = {(s.entry, s.size, s.count): s for s in found}
    return next(iter(uniq.values())) if len(uniq) == 1 else None


def lines(e):
    """The port lines for the build's attract table (empty when it has none the runtime can use)."""
    s = find(e)
    if s is None:
        return []
    return ["# PAD-782: the attract mode's page table (portattract.py); an owner's attract items play between its pages",
            "data  attract_table       0x%08x" % s.entry,
            "value attract_entry_size  %d" % s.size,
            "value attract_page_at     %d" % s.page_at,
            "value attract_count       %d" % s.count,
            "site  attract_sleep       0x%08x 0x%08x 0x%08x" % (s.sleep, e.word(s.sleep), e.word(s.sleep + 4))]
