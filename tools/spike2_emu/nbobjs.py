#!/usr/bin/env python3
"""nbobjs.py <game-elf> - print the node-board OBJECT array's base address, or
nothing.

WHY THIS EXISTS. hwshim's node-board registry lives in a per-title .bss array
(godzilla 0x7bad88, stride 0xe0, self-labelling: slot i holds node id i). The
shim needs its base to read board status and - as of 2026-08-27,
dungeons_and_dragons_le - to REGISTER node 2, whose "Cabinet Lights" board this
build ships with no device config so Stern's registrar leaves it unregistered
and the game refuses to start (see hwshim nb_reg_node2). The shim's by-shape
memory scan CANNOT find the base under QEMU guest_base: it reads candidate
addresses out of /proc/self/maps (host addresses = guest + 0x10000) and then
dereferences them as guest pointers, so every read lands 0x10000 off and the
self-label never matches (the +0x10000 trap, reference_spike2_qemu_guest_base).
An explicit base sidesteps the scan entirely, and the base is a fixed guest
address the ELF's own code carries in the clear.

HOW. The array is indexed by a stride-0xe0 idiom the whole board manager shares:

    rsb  Ra, Rb, Rb, lsl #3      ; Ra = index * 7
    movw Rc, #lo                 ; Rc = base (low half)
    movt Rc, #hi                 ;      base (high half)
    add  Rd, Rc, Ra, lsl #5      ; Rd = base + index*7*32 = base + index*0xe0

The signature is the PAIR: an `add Rd, Rn, Rm, lsl #5` whose index register Rm
was just produced by `rsb Rm, Ri, Ri, lsl #3` (Ri*7). The `add` alone is a
plain *32 stride - which is the 32-byte SWITCH table, indexed all over the
binary; matching it on its own resolved godzilla to its switch struct 0x7a958c,
not its board array. It is the *7-then-*32 = *0xe0 combination that is unique
to the board manager. The movw/movt a few instructions back build the add's
base register. Every board-array access builds the SAME base, so tally the base
each qualifying `add` resolves to and take the mode. Titles that do not use a
0xe0-stride board array (older single-node-set builds already covered by the
hard-coded godzilla address) yield no dominant candidate and this prints
nothing - the shim keeps its previous behaviour.

Matched against the DECODED lookup on dungeons_and_dragons_le 1.00 (0x35fcfc:
cmp #31, rsb r0,r0,r0,lsl#3, movw r3,#0x9558, movt r3,#0x82, add r0,r3,r0,lsl#5)
-> 0x829558, the base a live board-object dump (PAD_NB_OBJS) confirmed.
"""
import struct
import sys


def load_segments(data):
    """PT_LOAD segments as (vaddr, file_off, filesz), little-endian ARM ELF."""
    assert data[:4] == b"\x7fELF", "not an ELF"
    e_phoff = struct.unpack_from("<I", data, 0x1c)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x2a)[0]
    e_phnum = struct.unpack_from("<H", data, 0x2c)[0]
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, _paddr, p_filesz, _memsz, p_flags = \
            struct.unpack_from("<IIIIIII", data, off)
        if p_type == 1:                       # PT_LOAD
            segs.append((p_vaddr, p_offset, p_filesz, p_flags))
    return segs


def find_base(path):
    data = open(path, "rb").read()
    segs = load_segments(data)
    # The executable segment carries the code; scan it as LE words.
    exec_segs = [s for s in segs if s[3] & 1]          # PF_X
    if not exec_segs:
        exec_segs = segs
    # A base is plausible if it falls inside a writable-data span (.data/.bss);
    # take the union of every non-executable PT_LOAD's virtual range, extended
    # to memsz so .bss counts.
    data_lo = data_hi = None
    for i in range(struct.unpack_from("<H", data, 0x2c)[0]):
        off = struct.unpack_from("<I", data, 0x1c)[0] + \
            i * struct.unpack_from("<H", data, 0x2a)[0]
        p_type, _o, p_vaddr, _pa, _fs, p_memsz, p_flags = \
            struct.unpack_from("<IIIIIII", data, off)
        if p_type == 1 and not (p_flags & 1):         # non-executable LOAD
            lo, hi = p_vaddr, p_vaddr + p_memsz
            data_lo = lo if data_lo is None else min(data_lo, lo)
            data_hi = hi if data_hi is None else max(data_hi, hi)

    tally = {}
    for base_v, off, sz, _fl in exec_segs:
        n = sz & ~3
        # Track the last movw/movt immediate per destination register, so an
        # `add ... lsl #5` can resolve its base register to a full address.
        movw = {}                                     # reg -> (imm16, word_idx)
        movt = {}
        times7 = {}                                   # reg -> word_idx of rsb *7
        for wi in range(0, n, 4):
            w = struct.unpack_from("<I", data, off + wi)[0]
            top = w & 0x0ff00000
            if top == 0x03000000:                     # movw Rd, #imm16
                rd = (w >> 12) & 0xf
                imm = ((w >> 4) & 0xf000) | (w & 0xfff)
                movw[rd] = (imm, wi)
            elif top == 0x03400000:                   # movt Rd, #imm16
                rd = (w >> 12) & 0xf
                imm = ((w >> 4) & 0xf000) | (w & 0xfff)
                movt[rd] = (imm, wi)
            elif (w & 0xfff00ff0) == 0xe0600180 and \
                    ((w >> 16) & 0xf) == (w & 0xf):   # rsb Rd, Rm, Rm, lsl #3
                times7[(w >> 12) & 0xf] = wi          #   = Rm * 7
            elif (w & 0xfff00ff0) == 0xe0800280:      # add Rd, Rn, Rm, lsl #5
                rm = w & 0xf
                x7 = times7.get(rm)
                if not x7 or wi - x7 > 40:            # index must be Rm*7*32
                    continue                          #   i.e. a 0xe0 stride
                rn = (w >> 16) & 0xf
                lo = movw.get(rn)
                hi = movt.get(rn)
                if lo and hi and wi - lo[1] <= 40 and wi - hi[1] <= 40:
                    addr = (hi[0] << 16) | lo[0]
                    if data_lo is not None and data_lo <= addr < data_hi:
                        tally[addr] = tally.get(addr, 0) + 1
    if not tally:
        return None
    # The board array is the base the board manager touches most; a stray
    # coincidence of the idiom over some other stride-0xe0 struct would be rare
    # and rarer still to out-count it. Break ties by lowest address.
    best = max(tally.items(), key=lambda kv: (kv[1], -kv[0]))
    # Require real weight: the DnD manager builds it 17 times. A single hit is
    # not a board array.
    return best[0] if best[1] >= 3 else None


def main():
    if len(sys.argv) < 2:
        print("usage: nbobjs.py <game-elf>", file=sys.stderr)
        return 2
    try:
        base = find_base(sys.argv[1])
    except (OSError, AssertionError, struct.error) as e:
        print("nbobjs: %s" % e, file=sys.stderr)
        return 1
    if base is None:
        return 1
    print("0x%08x" % base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
