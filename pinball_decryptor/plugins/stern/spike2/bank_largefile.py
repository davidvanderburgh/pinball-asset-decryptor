"""A sound bank past 2 GiB: the game program's bank loader taught the large-file calls (PAD-593).

The loader opens ``image.bin`` with the 32-bit calls and reads its size off them::

    add   r0, rP, #imm          the bank's path
    mov   r1, #0                open(path, O_RDONLY)
    bl    open@plt
    subs  rF, r0, #0
    blt   <failed>
    mov   r0, #3                __fxstat(_STAT_VER, fd, &st)
    mov   r1, rF
    add   r2, sp, #N
    bl    __fxstat@plt
    ...   ldr rX, [sp, #N+0x2c]     st.st_size, as a signed 32-bit off_t
    ...   mov rY, rX, asr #31       ... sign-extended to 64 bits
    ...   mmap(0, st_size, PROT_READ, MAP_SHARED, fd, 0)

A 32-bit kernel refuses that ``open`` for a file past 2 GiB (EOVERFLOW: the program did not ask
for large files), glibc's ``__fxstat`` refuses to report such a size in a 32-bit ``st_size``,
and the loader's own arithmetic would read it back negative.  So, in place, nothing moved:

* the ``open`` asks for ``O_RDONLY | O_LARGEFILE`` (``mov r1, #0x20000``);
* the size comes from ``__xstat64(_STAT_VER, path, &st)`` - imported by every build measured,
  by the PATH still in ``rP + imm`` (``rP`` is callee-saved) - into the same stack buffer, whose
  ``st_size`` then sits at ``N + 0x30`` (``struct stat64``; its 104 bytes run 16 past the 88 of
  ``struct stat`` into scratch the loader fills later);
* each load of the size reads ``N + 0x30``, and each sign extension of it becomes a zero
  extension, so a bank up to 4 GiB reads back as its size.

Measured on Godzilla Premium/LE 1.16 (the loader at 0x3b5aac).  The ``mmap`` is the 32-bit one
with offset 0, which a large-file descriptor serves whole; what bounds the bank then is the
process's address space (:data:`LARGE_BANK_BYTES`)."""
import struct

O_LARGEFILE = 0x20000                   # ARM EABI
#: The largest bank a patched program is given (2.40 GB).  A 32-bit process maps the whole file
#: into a ~3 GB address space shared with its code, libraries and buffers (spike2.emulator,
#: MAX_IMAGE_BYTES), so never 4 GiB; and the desk emulator serves the bank at
#: ``emulator.DESC_BASE`` (0x703da000), which leaves 0x8fc26000 bytes below 4 GiB - every
#: build derives its bank there, so that is the ceiling, with a little room.
LARGE_BANK_BYTES = 0x8F000000

_MOV_R1_0 = 0xE3A01000
_MOV_R1_LARGE = 0xE3A01802             # mov r1, #0x20000
_MOV_R0_3 = 0xE3A00003


def _bl_target(word, va):
    if (word & 0x0F000000) != 0x0B000000:
        return None
    imm = word & 0xFFFFFF
    if imm & 0x800000:
        imm -= 1 << 24
    return (va + 8 + (imm << 2)) & 0xFFFFFFFF


def _bl(frm, to):
    return 0xEB000000 | (((to - (frm + 8)) >> 2) & 0xFFFFFF)


class LargefileError(Exception):
    """The bank loader is not the shape this patch knows."""


def _elf(elf_bytes):
    from ..portgen import Elf
    return Elf(bytes(elf_bytes))


def _find(elf):
    """``(site va, N, path reg, path imm, fd reg)`` of the one bank loader, or raise."""
    plt = elf.plt_by_name
    p_open, p_fx, p_x64 = plt.get("open"), plt.get("__fxstat"), plt.get("__xstat64")
    if p_open is None or p_x64 is None:
        raise LargefileError("the program does not import open and __xstat64")
    w, tva = elf.words, elf.tva
    hits = []
    for i in range(1, len(w) - 9):
        if w[i] not in (_MOV_R1_0, _MOV_R1_LARGE):
            continue
        va = tva + 4 * i
        if _bl_target(w[i + 1], va + 4) != p_open:
            continue
        # add r0, rP, #imm  (rP callee-saved, so the path is still there at the stat)
        a = w[i - 1]
        if (a & 0xFFF0F000) != 0xE2800000:
            continue
        rp = (a >> 16) & 0xF
        if not 4 <= rp <= 11:
            continue
        s = w[i + 2]                                    # subs rF, r0, #0
        if (s & 0xFFFF0FFF) != 0xE2500000:
            continue
        rf = (s >> 12) & 0xF
        if (w[i + 3] & 0xFF000000) != 0xBA000000:       # blt
            continue
        if w[i + 4] != _MOV_R0_3:
            continue
        m = w[i + 5]
        patched = (m & 0xFFFFF000) == (0xE2801000 | (rp << 16))
        if not patched and m != (0xE1A01000 | rf):      # mov r1, rF
            continue
        g = w[i + 6]                                    # add r2, sp, #N
        if (g & 0xFFFFFF00) != 0xE28D2000:
            continue
        tgt = _bl_target(w[i + 7], va + 28)
        if tgt not in (p_fx, p_x64) or tgt is None:
            continue
        hits.append((va, g & 0xFF, rp, a & 0xFFF, rf))
    if len(hits) != 1:
        raise LargefileError("%d bank loader(s) of the known shape" % len(hits))
    return hits[0]


def _size_uses(elf, site, n):
    """Indexes (into ``elf.words``) of every load of ``st_size`` after *site*, and of each
    sign extension of a loaded size, through the end of the loader."""
    w, tva = elf.words, elf.tva
    i0 = (site - tva) // 4 + 8
    loads, exts = [], []
    old, new = n + 0x2C, n + 0x30
    loaded = {}                                         # register -> index of its load
    for i in range(i0, min(i0 + 120, len(w))):
        x = w[i]
        if (x & 0xFFF00000) == 0xE5900000 and ((x >> 16) & 0xF) == 13 \
                and (x & 0xFFF) in (old, new):        # ldr rX, [sp, #st_size]
            loads.append(i)
            loaded[(x >> 12) & 0xF] = i
            continue
        near = {r for r, j in loaded.items() if i - j <= _EXT_REACH}
        if (x & 0x0FEF0FF0) == 0x01A00FC0 and (x & 0xF) in near:      # mov rY, rX, asr #31
            exts.append(i)
        elif (x & 0x0FE00FF0) == 0x00A00FC0 and (x & 0xF) in near:    # adc rA, rB, rX, asr #31
            exts.append(i)
    return loads, exts


#: How many instructions after a load of the size its sign extension may sit (5 on Godzilla).
_EXT_REACH = 6


def overlay(elf_bytes):
    """``{file offset: 4 bytes}`` that teach the bank loader the large-file calls; ``{}`` when
    the program already carries them.  Raises :class:`LargefileError` on another shape."""
    elf = _elf(elf_bytes)
    site, n, rp, imm, rf = _find(elf)
    w, tva = elf.words, elf.tva
    i = (site - tva) // 4
    p_x64 = elf.plt_by_name["__xstat64"]
    want = {
        i: _MOV_R1_LARGE,
        i + 5: 0xE2801000 | (rp << 16) | imm,           # add r1, rP, #imm (the path)
        i + 7: _bl(site + 28, p_x64),
    }
    loads, exts = _size_uses(elf, site, n)
    if not loads:
        raise LargefileError("no load of the bank's size after the stat")
    for j in loads:
        want[j] = (w[j] & ~0xFFF) | (n + 0x30)
    for j in exts:
        x = w[j]
        if (x & 0x0FEF0FF0) == 0x01A00FC0:               # mov rY, rX, asr #31 -> mov rY, #0
            want[j] = (x & 0xF000F000) | 0x03A00000
        else:                                            # adc rA, rB, rX, asr #31 -> adc rA, rB, #0
            want[j] = (x & 0xF00FF000) | 0x02A00000
    out = {}
    for j, v in sorted(want.items()):
        if w[j] != v:
            out[elf.off(tva + 4 * j)] = struct.pack("<I", v & 0xFFFFFFFF)
    return out


def carries(elf_bytes):
    """True when the program's bank loader already uses the large-file calls."""
    try:
        return not overlay(elf_bytes)
    except Exception:                                    # noqa: BLE001 - another shape: no
        return False


def patchable(elf_bytes):
    """True when :func:`overlay` can teach this program the large-file calls (or it has them)."""
    try:
        overlay(elf_bytes)
        return True
    except Exception:                                    # noqa: BLE001
        return False


def bank_limit(elf_bytes):
    """The largest ``image.bin`` this program can open once patched: :data:`LARGE_BANK_BYTES`
    for a loader of the known shape, else the 32-bit calls' 2 GiB - 1."""
    from .emulator import MAX_IMAGE_BYTES
    return LARGE_BANK_BYTES if patchable(elf_bytes) else MAX_IMAGE_BYTES
