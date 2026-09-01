"""Patch the extracted Spike 1 game so the emulator can boot it to a playable state.

Two title-agnostic, symbol-resolved patches (see each function):

  * ``patch_line_frequency`` — the mains line-frequency self-test (below).
  * ``patch_node_status`` — make each playfield node reach the READY status the
    boot's node gate waits for, so the game leaves "LOCATING NODE BOARDS" and
    starts scanning switches / driving lamps + coils.

The emulator has no real AC line.  The firmware's factory self-test
(``sys_factory_config_exec_pdi``) reads the mains frequency from ``/dev/adc``
(``LineSenseThread``) and, when it can't confirm ~50/60 Hz, sets a fault flag and
shows the **"CHECK POWER DISTRIBUTION BOARD"** display effect — a screen every
title sits on instead of booting to attract.  A faithful synthetic AC waveform
does not lock the detector's analog edge timing under emulation (see
docs/architecture/spike1_emulation.md), so we make the game read a valid line
directly, at the one function every consumer goes through:

    sys_line_status_get_operating_frequency_pdi(unsigned& freq, bool& spoofed)

Its whole body is replaced with a 6-instruction stub that reports **60 Hz, not
spoofed, valid** — which makes the factory self-test accept the line AND stops
``power_loss_thread`` ever flagging a loss, with correct behaviour (a real 60 Hz
reading feeds the game's coil timing).  The patch is:

  * **symbol-based** — the address differs per title, so we resolve it from the
    game's own (unstripped) symbol table (reusing :mod:`s1elf`); it therefore
    works for GOT, Ghostbusters, KISS, WWE, …;
  * **guarded** — it refuses unless the stock prologue is the expected
    ``ldr r3,[pc,#N]`` (loading ``adc_fd``), so a title whose function differs is
    never silently corrupted;
  * **idempotent** — a game already carrying the stub is left alone.

Applied to the EXTRACTED copy only (the card is never touched), the same way the
qemu ``/proc/cpuinfo`` and SIGFPE patches make the emulator run.

    python3 s1patch.py <game-elf>     # patches in place; prints patched|already
"""

import struct
import sys

from s1elf import _Elf   # same dir; the minimal ELF reader

# The function symbol is C++-mangled, so match by the demangled name embedded
# in the mangling.  Its SIGNATURE varies per title, and that matters:
#   * most titles (GoT, Ghostbusters, KISS):  (unsigned& freq, bool& spoofed)
#     — mangled `…_pdiRjRb` — the caller passes BOTH a freq& (r0) and a
#     spoofed-bool& (r1).
#   * WWE WrestleMania:  (unsigned& freq) — mangled `…_pdiRj` — ONE ref arg;
#     the caller (sys_factory_config_exec_pdi) sets only r0 and leaves r1
#     garbage/NULL.
# So the stub MUST match the arg count: writing *spoofed via r1 on the 1-arg
# WWE variant dereferences NULL and segfaults the boot (222 crashes/loop).
SYMBOL = "sys_line_status_get_operating_frequency_pdi"

# 2-arg stub, 6 instructions / 24 bytes  (…_pdiRjRb):
#   mov  r2, #60        ; the mains frequency to report (Hz)
#   str  r2, [r0]       ; *freq_out    = 60
#   mov  r2, #0
#   strb r2, [r1]       ; *spoofed_out = 0   (a real reading, not a spoof)
#   mov  r0, #1         ; return "valid"
#   bx   lr
STUB_2ARG = struct.pack("<6I", 0xE3A0203C, 0xE5802000, 0xE3A02000,
                        0xE5C12000, 0xE3A00001, 0xE12FFF1E)
# 1-arg stub, 4 instructions / 16 bytes  (…_pdiRj — WWE): NO r1 write.
#   mov  r2, #60 ; str r2, [r0] ; mov r0, #1 ; bx lr
STUB_1ARG = struct.pack("<4I", 0xE3A0203C, 0xE5802000, 0xE3A00001, 0xE12FFF1E)
_LDR_R3_PC = 0xE59F3000          # `ldr r3, [pc, #N]` — the stock prologue mask

# ---- node "ready" status patch --------------------------------------------
# The boot's node gate `node_bus_are_all_nodes_OK` keeps the game on the
# "LOCATING NODE BOARDS / NODES NOT FOUND" screen — never scanning switches or
# driving lamps/coils — until every playfield node reaches the READY status 2.
# On real hardware a node reaches 2 only after its firmware validates (a matching
# proc-id + firmware version + checksum); the emulated node responder makes each
# node PRESENT (status 4) but has no real firmware to validate, so the game sits
# there forever.  Verified live: writing status 2 into the runtime node blocks
# makes the game immediately poll switches (cmd 0x11) and drive outputs
# (cmd 0x80-0xbe) and reach attract — status 2 is the one thing gating a playable
# state.  So in `node_bus_update_node_status` we make the "node present" branch
# report status 2 instead of 4:
#     mov r3,#4 ; mov r0,r8 ; str r3,[r10,#24]  ->  mov r3,#2 ; mov r0,r8 ; str …
# Surgical (only that one immediate) so the function still stores the node's board
# id / version normally; symbol-resolved so it is title-agnostic; guarded so a
# title whose write differs is refused rather than corrupted.
NODE_STATUS_SYMBOL = "node_bus_update_node_status"
# The "node present" status write is `mov r3,#4 ; mov r0,r8 ; str r3,[r10,#OFF]`
# where OFF is the status field in the runtime node block — #24 on most titles
# (GoT/GBLE/KISS) but #16 on WWE.  Match the invariant prefix + the str and flip
# ONLY the #4 immediate to #2, whatever the offset, so the patch is title-
# agnostic instead of refusing on WWE's differing layout.
_PRESENT_PREFIX = struct.pack("<II", 0xE3A03004, 0xE1A00008)  # mov r3,#4;mov r0,r8
_PRESENT_PREFIX_FIXED = struct.pack("<II", 0xE3A03002, 0xE1A00008)  # #4 -> #2
_STR_R3_R10 = 0xE58A3000         # `str r3,[r10,#imm]` (imm in the low 12 bits)
_STR_R3_R10_MASK = 0xFFFFF000
_NODE_STATUS_WINDOW = 0x400      # bytes into the function to search for the write

# ---- registered-return patch (WWE's boot-to-attract gate) ------------------
# In WWE's `node_bus_update_node_status`, the path a responder-backed node
# actually takes — deterministic GetVersion reply, mode byte 0 (application),
# proc id 0 (unknown to NODEBUS_GetProcID), so no runtime hex image to check —
# stores the READY status 2 but then RETURNS THE STALE MODE BYTE (r8 == 0)
# instead of success:
#     mov r3,#2 ; mov r0,r8 ; str r3,[r10,#16] ; add sp,sp,#32 ; pop {…,pc}
# The startup/control loop counts a node as registered only on a TRUE return,
# so every node re-graded once a second forever (cmd 0xfe x96+ per node on the
# wire), the matrix scan never started (cmd 0x11 stuck at one per node) and
# the game sat on the Stern splash driving its lightshow.  Found by the
# SIGWINCH guest-CPU dump + a stack walk to the waiting dispatch loop, then
# reading this function.  Fix: flip the return to `mov r0,#1` — the exact
# WWE twin of patch_node_status's 4→2 flip on the other titles (same gate,
# different codegen).  The status write itself is already correct (2).
# Guarded: the full 5-word shape must match (status-2 mov, return mov, the
# str at ANY [r10,#imm] offset, an `add sp,sp,#imm` and a `pop {…,pc}`), and
# exactly ONE site may match; a title without the shape reports 'absent'.
_REG_RET_OLD = 0xE1A00008        # mov r0, r8
_REG_RET_NEW = 0xE3A00001        # mov r0, #1
_REG_MOV_R3_2 = 0xE3A03002       # mov r3, #2
_ADD_SP_SP = 0xE28DD000          # add sp, sp, #imm
_ADD_SP_MASK = 0xFFFFF000
_POP_PC = 0xE8BD8000             # pop {…, pc}  (LDMIA sp! with PC in the list)
_POP_PC_MASK = 0xFFFF8000


def _reg_ret_sites(win, ret_word):
    """Offsets in *win* of `mov r3,#2 ; <ret_word> ; str r3,[r10,#imm] ;
    add sp,sp,#imm ; pop {…,pc}` — the status-2 early-return site."""
    out = []
    for j in range(0, len(win) - 19, 4):
        w = struct.unpack_from("<5I", win, j)
        if (w[0] == _REG_MOV_R3_2 and w[1] == ret_word
                and (w[2] & _STR_R3_R10_MASK) == _STR_R3_R10
                and (w[3] & _ADD_SP_MASK) == _ADD_SP_SP
                and (w[4] & _POP_PC_MASK) == _POP_PC):
            out.append(j)
    return out


def patch_registered_return(path):
    """Make ``node_bus_update_node_status``'s status-2 early return report
    success (see the comment above).  Returns 'patched', 'already', 'absent'
    (a title without the WWE code shape), or raises on ambiguity."""
    with open(path, "rb") as f:
        data = bytearray(f.read())
    elf = _Elf(bytes(data))
    cands = sorted(v for n, v in elf.syms.items() if NODE_STATUS_SYMBOL in n)
    if not cands:
        raise ValueError("symbol %s not found — not a Spike 1 game?"
                         % NODE_STATUS_SYMBOL)
    start = _file_offset(elf, cands[0])
    win = bytes(data[start:start + _NODE_STATUS_WINDOW])
    if _reg_ret_sites(win, _REG_RET_NEW):
        return "already"
    hits = _reg_ret_sites(win, _REG_RET_OLD)
    if not hits:
        return "absent"
    if len(hits) > 1:
        raise ValueError("ambiguous status-2 return site — refusing")
    struct.pack_into("<I", data, start + hits[0] + 4, _REG_RET_NEW)
    with open(path, "wb") as f:
        f.write(data)
    return "patched"


# ---- no-firmware-flash patch ----------------------------------------------
# A node reports the firmware version it is running; the game compares that to the
# shipped node .hex images (accbridgenode/coil4node-*-0_49_0.hex) and, on a
# mismatch, tries to FLASH the node over the bus.  The emulated nodes have no real
# LPC firmware to accept a flash, so `node_bus_update_node_runtime_hex_image_if_
# necessary` would keep reporting "update pending" and the game would keep trying.
# Stub it to return 0 ("no update needed") so it never attempts a flash.
#
# (The boot's "LOCATING NODE BOARDS" gate itself is cleared without any code patch,
# by the node-bus responder: it makes node_bus_identify_attached_nodes see the
# real attached nodes, so the game's own sys_node_board_set_runtime_flags sets
# their ready flag and node_bus_are_all_nodes_OK passes.  See nodebus.py.)
NODE_READY_SYMBOL = "node_bus_update_node_runtime_hex_image_if_necessary"
READY_STUB = struct.pack("<2I", 0xE3A00000, 0xE12FFF1E)   # mov r0,#0 ; bx lr
_PUSH_MASK = 0xFFFF0000           # a function prologue `push {…, lr}` is 0xE92D....
_PUSH_LR = 0xE92D0000


def _file_offset(elf, vaddr):
    for sh in elf.sections:
        if sh["off"] and sh["addr"] and \
                sh["addr"] <= vaddr < sh["addr"] + sh["size"]:
            return sh["off"] + (vaddr - sh["addr"])
    raise ValueError("vaddr 0x%x is not in a file-backed section" % vaddr)


def patch_line_frequency(path):
    """Patch the ELF at *path* in place.  Returns 'patched', 'already', or
    raises on a missing symbol / unexpected prologue.

    Chooses the stub by the function's ARG COUNT (from its mangled name): the
    2-arg ``…RjRb`` variant writes *spoofed via r1, the 1-arg ``…Rj`` (WWE)
    must not — see the STUB comments above."""
    with open(path, "rb") as f:
        data = bytearray(f.read())
    elf = _Elf(bytes(data))
    # match the mangled function symbol by its embedded demangled name, and
    # keep the mangled name so we can read its argument signature.
    cands = sorted(((v, n) for n, v in elf.syms.items() if SYMBOL in n))
    if not cands:
        raise ValueError("symbol %s not found — not a Spike 1 game?" % SYMBOL)
    va, mangled = cands[0]
    # `…RjRb` = (unsigned&, bool&) -> 2-arg stub; `…Rj` (no trailing Rb) = WWE's
    # single (unsigned&) -> 1-arg stub (no NULL-prone r1 write).
    stub = STUB_2ARG if mangled.endswith("RjRb") else STUB_1ARG
    off = _file_offset(elf, va)
    if bytes(data[off:off + len(stub)]) == stub:
        return "already"
    first = struct.unpack_from("<I", data, off)[0]
    # accept the stock `ldr r3,[pc]` prologue, OR either of our own stubs — the
    # latter so a re-run can CORRECT an ELF a previous build stubbed with the
    # wrong arg count (the WWE-crash regression) instead of refusing it.
    known_stub = (bytes(data[off:off + len(STUB_2ARG)]) == STUB_2ARG
                  or bytes(data[off:off + len(STUB_1ARG)]) == STUB_1ARG)
    if (first & 0xFFFFF000) != _LDR_R3_PC and not known_stub:
        raise ValueError("unexpected %s prologue 0x%08x — refusing to patch"
                         % (SYMBOL, first))
    data[off:off + len(stub)] = stub
    with open(path, "wb") as f:
        f.write(data)
    return "patched"


def patch_node_status(path):
    """Make the 'node present' status of ``node_bus_update_node_status`` report
    the READY value 2 instead of 4, so the boot's node gate is satisfied.  Returns
    'patched', 'already', or raises on a missing symbol / unexpected code."""
    with open(path, "rb") as f:
        data = bytearray(f.read())
    elf = _Elf(bytes(data))
    cands = sorted(v for n, v in elf.syms.items() if NODE_STATUS_SYMBOL in n)
    if not cands:
        raise ValueError("symbol %s not found — not a Spike 1 game?"
                         % NODE_STATUS_SYMBOL)
    start = _file_offset(elf, cands[0])
    win = bytes(data[start:start + _NODE_STATUS_WINDOW])

    def _sites(prefix):
        """Offsets where *prefix* (mov r3,#imm ; mov r0,r8) is followed by a
        `str r3,[r10,#OFF]` — the status write, at whatever field offset."""
        out, j = [], 0
        while True:
            j = win.find(prefix, j)
            if j < 0:
                break
            nxt = struct.unpack_from("<I", win, j + len(prefix))[0]
            if (nxt & _STR_R3_R10_MASK) == _STR_R3_R10:
                out.append(j)
            j += 4
        return out

    # "already" = the #2 write with EITHER return: the stock `mov r0,r8`, or
    # `mov r0,#1` once patch_registered_return has also fixed the return at
    # the same site (WWE) — without the second form, a re-run raised on an
    # ELF carrying both patches and start.sh skipped the whole patch pass.
    _fixed_ret = struct.pack("<II", 0xE3A03002, _REG_RET_NEW)
    if _sites(_PRESENT_PREFIX_FIXED) or _sites(_fixed_ret):
        return "already"
    hits = _sites(_PRESENT_PREFIX)
    if not hits:
        raise ValueError("node-present status write not found in %s — refusing"
                         % NODE_STATUS_SYMBOL)
    if len(hits) > 1:
        raise ValueError("ambiguous node-present status write — refusing")
    off = start + hits[0]
    data[off:off + len(_PRESENT_PREFIX_FIXED)] = _PRESENT_PREFIX_FIXED
    with open(path, "wb") as f:
        f.write(data)
    return "patched"


def patch_node_ready(path):
    """Stub ``node_bus_update_node_runtime_hex_image_if_necessary`` to return 0,
    so the node control thread always marks each node ready (block flag bit1).
    Returns 'patched', 'already', or raises on a missing symbol / unexpected
    prologue."""
    with open(path, "rb") as f:
        data = bytearray(f.read())
    elf = _Elf(bytes(data))
    cands = sorted(v for n, v in elf.syms.items() if NODE_READY_SYMBOL in n)
    if not cands:
        raise ValueError("symbol %s not found — not a Spike 1 game?"
                         % NODE_READY_SYMBOL)
    off = _file_offset(elf, cands[0])
    if data[off:off + len(READY_STUB)] == READY_STUB:
        return "already"
    first = struct.unpack_from("<I", data, off)[0]
    if (first & _PUSH_MASK) != _PUSH_LR:
        raise ValueError("unexpected %s prologue 0x%08x — refusing to patch"
                         % (NODE_READY_SYMBOL, first))
    data[off:off + len(READY_STUB)] = READY_STUB
    with open(path, "wb") as f:
        f.write(data)
    return "patched"


#: The four patches all resolve symbols of the 2015-2016 framework.  An EARLY
#: card's firmware (the 2012 home models, PAD-101) has none of them — no line-
#: frequency self-test to spoof, no node status gate, no in-game node
#: flashing — so there is nothing to patch, and saying so beats four
#: "symbol not found" refusals that read like a broken card.
_ERA_SYMBOLS = (SYMBOL, NODE_STATUS_SYMBOL, NODE_READY_SYMBOL)


def is_early_era(path):
    with open(path, "rb") as f:
        elf = _Elf(f.read())
    return not any(any(sym in n for n in elf.syms) for sym in _ERA_SYMBOLS)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: s1patch.py <game-elf>", file=sys.stderr)
        return 2
    try:
        if is_early_era(argv[0]):
            print("early firmware era: none of the DMD-generation boot gates "
                  "exist in this game, nothing to patch")
            return 0
        lf = patch_line_frequency(argv[0])
        ns = patch_node_status(argv[0])
        nr = patch_node_ready(argv[0])
        rr = patch_registered_return(argv[0])
        print("line-freq=%s node-status=%s no-flash=%s registered-return=%s"
              % (lf, ns, nr, rr))
    except Exception as exc:                               # noqa: BLE001
        print("s1patch: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
