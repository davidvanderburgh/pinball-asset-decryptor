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
from dataclasses import dataclass

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


# ---- clip v2: the attract video element ----------------------------------------------------------------------------
#: James Bond LE 1.06 (and the other builds whose bank's surface is drawn only by the main-play screen): the attract
#: pages that show a clip (the intro, the tutorials) play it through one ELEMENT of their own, the game's own way -
#:   ldr r4, [<element pointer>] ; std::string(&s, <clip name>) ;
#:   mov r0, r4 ; add r1, sp, #n ; mov r2, #0 ; mov r3, #1 ; bl <play> ; ...
#:   loop: mov r0, r4 ; bl <update> ; mov r0, r4 ; bl <draw> ; bl <yield> ; mov r0, r4 ; bl <playing> ; cmp r0, #0 ; bne
#: (Bond: *0x818c80, play 0x1ce69c, update 0x1ce788, draw 0x1ce790, yield 0x2fd144, playing 0x1ce680). An item plays
#: the same way from its page (the clips in the element's own scene: the one whose library holds the page's clip).
@dataclass
class Element:
    pointer: int
    play: int
    playing: int
    update: int
    draw: int
    yield_: int
    clip: str


def _element_in(e, va, depth=1):
    """The :class:`Element` a page at ``va`` plays a clip through, or None. A page that is a thunk (`movw r0; movt r0;
    b <common page>`: Bond's tutorials) is followed into the common page, its clip name the thunk's r0."""
    w, base = e.words, e.text_va
    k = (va - base) // 4
    if not 0 <= k < len(w) - 4:
        return None
    lo = {}
    r0_name = None
    for i in range(k, min(len(w) - 12, k + 120)):
        x = w[i]
        if x & 0xFFF00000 == 0xE3000000:
            lo[x >> 12 & 15] = (x >> 4 & 0xF000) | (x & 0xFFF)
        elif x & 0xFFF00000 == 0xE3400000 and (x >> 12 & 15) in lo:
            reg = x >> 12 & 15
            lo[reg] |= ((x >> 4 & 0xF000) | (x & 0xFFF)) << 16
            if reg == 0:
                r0_name = lo[reg]
        if x & 0xFF000000 == 0xEA000000 and depth:            # b <common page>: a thunk
            t = (base + 4 * i + 8 + (((x & 0xFFFFFF) << 8 & 0xFFFFFFFF) - ((x & 0x800000) << 9) >> 6)) & 0xFFFFFFFF
            got = _element_in(e, t, depth - 1)
            if got is not None and not got.clip and r0_name:
                got.clip = _cstr(e, r0_name) or ""
            return got
        # mov r0, r4 ; add r1, sp, #n ; mov r2, #0 ; mov r3, #1 ; bl <play>
        if x == 0xE1A00004 and w[i + 1] & 0xFFFFF000 == 0xE28D1000 and w[i + 2] == 0xE3A02000 \
                and w[i + 3] == 0xE3A03001 and bl_target(base + 4 * (i + 4), w[i + 4]) is not None:
            play = bl_target(base + 4 * (i + 4), w[i + 4])
            pointer = None
            for j in range(i - 1, max(k - 1, i - 30), -1):        # ldr r4, [rX] with rX = movw/movt <pointer>
                if w[j] & 0xFFF0FFFF == 0xE5904000 and (w[j] >> 16 & 15) in lo:
                    pointer = lo[w[j] >> 16 & 15]
                    break
            if pointer is None:
                return None
            loop = None
            for j in range(i + 5, min(len(w) - 9, i + 60)):
                if (w[j] == 0xE1A00004 and w[j + 2] == 0xE1A00004 and w[j + 5] == 0xE1A00004
                        and all(bl_target(base + 4 * (j + q), w[j + q]) is not None for q in (1, 3, 4, 6))):
                    loop = [bl_target(base + 4 * (j + q), w[j + q]) for q in (1, 3, 4, 6)]
                    break
            if loop is None:
                return None
            # the clip's name: a string the page made just before the play (`movw r1 ; movt r1`), when it has one
            name = ""
            for j in range(i - 1, max(k - 1, i - 16), -1):
                if w[j] & 0xFFF0F000 == 0xE3401000:
                    lo1 = next((w[q] for q in range(j - 1, max(k - 1, j - 6), -1)
                                if w[q] & 0xFFF0F000 == 0xE3001000), None)
                    if lo1 is not None:
                        name = _cstr(e, ((lo1 >> 4 & 0xF000) | (lo1 & 0xFFF))
                                     | ((w[j] >> 4 & 0xF000) | (w[j] & 0xFFF)) << 16) or ""
                    break
            return Element(pointer, play, loop[3], loop[0], loop[1], loop[2], name)
    return None


def _cstr(e, va):
    o = e.off(va) if va else None
    if o is None:
        return None
    end = e.d.find(b"\0", o, o + 120)
    b = e.d[o:end] if end > o else b""
    return b.decode() if len(b) >= 3 and all(32 <= c < 127 for c in b) else None


def element(e, s=None):
    """The attract video element the build's attract pages play their clips through (the one most pages use), or
    None."""
    if not isinstance(e, Elf):
        e = Elf(e)
    s = s or find(e)
    if s is None:
        return None
    seen = {}
    for k in range(s.count):
        va = s.entry + s.size * k + s.page_at
        if e.off(va) is None:
            break
        el = _element_in(e, e.word(va))
        if el is not None:
            key = (el.pointer, el.play, el.playing, el.update, el.draw, el.yield_)
            got = seen.setdefault(key, el)
            if not got.clip and el.clip:
                got.clip = el.clip
    if not seen:
        return None
    best = max(seen.values(), key=lambda el: sum(1 for k in seen if k[0] == el.pointer))
    return best if best.clip else None


def element_lines(e, s=None):
    if not isinstance(e, Elf):
        e = Elf(e)
    el = element(e, s)
    if el is None:
        return []
    out = ["# PAD-782: the attract video element its pages play their clips through (an item plays the same way)",
           "data  attract_video       0x%08x" % el.pointer]
    for name, va in (("attract_video_play", el.play), ("attract_video_playing", el.playing),
                     ("attract_video_update", el.update), ("attract_video_draw", el.draw),
                     ("attract_video_yield", el.yield_)):
        out.append("site  %-21s 0x%08x 0x%08x 0x%08x" % (name, va, e.word(va), e.word(va + 4)))
    out.append("text  attract_video_clip  %s" % el.clip)
    return out
