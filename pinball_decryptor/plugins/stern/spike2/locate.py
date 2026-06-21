"""Build-independent firmware-address discovery for Spike 2 ``game`` ELFs.

The codec oracle (:mod:`.emulator`) needs ~20 absolute addresses inside the
firmware (boot routine, keystream/register bases, the master-directory decoder
and its band-build internal PCs, the codec dispatch table, the shared body
provider, the volume-multiply table).  On the one validated build (TMNT 1.58)
these are hardcoded; for every *other* Spike 2 title the same routines live at
different addresses, so this module locates them generically from the ELF by
string xrefs and instruction-pattern matching.

Validated: every address here reproduces the TMNT hardcoded constants exactly
(so the emulator can use this path on TMNT too without drift), and the full set
drives a bit-exact Godzilla decode.  Builds whose codec is *dual-path* (no
``PROV``/``QMUL`` resolvable from a decode-slot function — e.g. Aerosmith, D&D)
return ``None`` from :func:`locate_all`, so the engine skips audio gracefully.

Everything is read straight from the ELF bytes; nothing here boots or needs
unicorn.  capstone is used only for the few instruction-pattern scans.
"""

import collections
import struct

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

from .elf import _u16, _u32

_cs = Cs(CS_ARCH_ARM, CS_MODE_ARM)


# --------------------------------------------------------------------------
# minimal ELF view (sections with vaddrs + PT_LOAD segments)
# --------------------------------------------------------------------------
class _FwView:
    """Read-only ELF accessor: section table (with vaddrs) + load segments."""

    def __init__(self, raw):
        if raw[:4] != b"\x7fELF" or raw[4] != 1:
            raise ValueError("not a 32-bit ELF")
        self.raw = raw
        e_phoff = _u32(raw, 0x1c); e_phentsize = _u16(raw, 0x2a); e_phnum = _u16(raw, 0x2c)
        e_shoff = _u32(raw, 0x20); e_shentsize = _u16(raw, 0x2e); e_shnum = _u16(raw, 0x30)
        e_shstrndx = _u16(raw, 0x32)
        self.segs = []
        for i in range(e_phnum):
            ph = e_phoff + i * e_phentsize
            if _u32(raw, ph) == 1:  # PT_LOAD
                self.segs.append(dict(vaddr=_u32(raw, ph + 8), off=_u32(raw, ph + 4),
                                      filesz=_u32(raw, ph + 16), memsz=_u32(raw, ph + 20)))
        shstr_off = _u32(raw, e_shoff + e_shstrndx * e_shentsize + 16)

        def name(no):
            base = shstr_off + no
            return raw[base: raw.index(b"\x00", base)].decode()
        self.secs = {}
        for i in range(e_shnum):
            sh = e_shoff + i * e_shentsize
            self.secs[name(_u32(raw, sh))] = dict(
                off=_u32(raw, sh + 16), size=_u32(raw, sh + 20), addr=_u32(raw, sh + 12))

    def off_of(self, va):
        for s in self.segs:
            if s["vaddr"] <= va < s["vaddr"] + s["filesz"]:
                return s["off"] + (va - s["vaddr"])
        return None

    def u32_va(self, va):
        o = self.off_of(va)
        return _u32(self.raw, o) if o is not None else None

    def w_text(self, va):
        """u32 instruction word at a .text vaddr (no segment lookup)."""
        t = self.secs[".text"]
        return _u32(self.raw, t["off"] + (va - t["addr"]))


# --------------------------------------------------------------------------
# instruction / const primitives
# --------------------------------------------------------------------------
def _decode_movw_movt(w):
    """ARM A1 MOVW/MOVT -> ('movw'|'movt', Rd, imm16), else None."""
    if (w & 0x0FF00000) == 0x03000000:
        return ("movw", (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF))
    if (w & 0x0FF00000) == 0x03400000:
        return ("movt", (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF))
    return None


def _disasm(fw, lo, hi):
    """Linear ARM disasm over [lo,hi) in .text, skipping undecodable words
    (literal pools) instead of desyncing."""
    t = fw.secs[".text"]; o = t["off"]; base = t["addr"]
    va = lo
    while va < hi:
        code = fw.raw[o + (va - base): o + (va - base) + 4]
        for ins in _cs.disasm(code, va):
            yield ins
            break
        va += 4


def _loader_index(fw):
    """Map each movw/movt-reconstructed 32-bit constant -> [addrs that load it].
    Used to find which code references a given string/data address."""
    t = fw.secs[".text"]
    data = fw.raw[t["off"]: t["off"] + (t["size"] & ~3)]
    base = t["addr"]; idx = {}; pend = {}
    for i in range(0, len(data), 4):
        d = _decode_movw_movt(struct.unpack_from("<I", data, i)[0])
        if not d:
            continue
        kind, rd, imm = d
        if kind == "movw":
            pend[rd] = (base + i, imm)
        elif rd in pend:
            a, low = pend[rd]
            idx.setdefault((imm << 16) | low, []).append(a)
    return idx


def _str_va(fw, s, ref_index=None):
    """vaddr of byte string ``s`` (optionally one that code actually loads)."""
    if isinstance(s, str):
        s = s.encode()
    start = 0
    while True:
        i = fw.raw.find(s, start)
        if i == -1:
            return None
        va = None
        for sg in fw.segs:
            if sg["off"] <= i < sg["off"] + sg["filesz"]:
                va = sg["vaddr"] + (i - sg["off"]); break
        if va is not None and (ref_index is None or va in ref_index):
            return va
        start = i + 1


def _func_start(fw, addr, back=0x1200):
    """Walk back to the enclosing function's ``push {..,lr}`` prologue."""
    t = fw.secs[".text"]; base = t["addr"]; o = t["off"]
    a = addr & ~3
    for bo in range(0, back, 4):
        va = a - bo
        w = _u32(fw.raw, o + (va - base))
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):  # push {..,lr}
            return va
        if w == 0xE52DE004:                                  # str lr,[sp,#-4]!
            return va
    return None


def _func_end(fw, start, maxspan=0x1c00):
    """Heuristic function end: the next ``push {..,lr}`` prologue."""
    t = fw.secs[".text"]; o = t["off"]; base = t["addr"]
    for va in range(start + 4, start + maxspan, 4):
        w = _u32(fw.raw, o + (va - base))
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):
            return va
    return start + maxspan


def _sec_of(fw, va):
    for nm, s in fw.secs.items():
        if s["addr"] and s["addr"] <= va < s["addr"] + s["size"]:
            return nm
    return None


def _func_const_loads(fw, start, span=0x400):
    t = fw.secs[".text"]; base = t["addr"]; o0 = t["off"] + (start - base)
    out = []; pend = {}
    for i in range(0, span, 4):
        d = _decode_movw_movt(_u32(fw.raw, o0 + i))
        if not d:
            continue
        kind, rd, imm = d
        if kind == "movw":
            pend[rd] = imm
        elif rd in pend:
            out.append((start + i, (imm << 16) | pend[rd]))
    return out


# --------------------------------------------------------------------------
# locators
# --------------------------------------------------------------------------
def _find_dispatch(fw):
    """The codec dispatch table is a dense, contiguous, 0x40-aligned array of
    .text pointers (32 scale-blocks x 0x40).  Find the maximal run of
    consecutive code-pointers in .rodata; round up to the 0x40-aligned base."""
    t = fw.secs[".text"]; tlo, thi = t["addr"], t["addr"] + t["size"]
    ro = fw.secs[".rodata"]; lo, hi = ro["addr"], ro["addr"] + ro["size"]; o0 = ro["off"]
    best = None; run_start = None; n = 0
    va = lo
    while va + 4 <= hi:
        w = _u32(fw.raw, o0 + (va - lo))
        if tlo <= w < thi:
            if run_start is None:
                run_start = va; n = 0
            n += 1
        else:
            if run_start is not None and (best is None or n > best[1]):
                best = (run_start, n)
            run_start = None
        va += 4
    if run_start is not None and (best is None or n > best[1]):
        best = (run_start, n)
    if not best:
        return None
    return (best[0] + 0x3f) & ~0x3f


def _find_boot(fw, idx):
    """Boot routine: the function loading the ``sndscript`` string.  VF2_VA is
    its only .data const, REG_BASE its only .bss const."""
    sva = _str_va(fw, b"sndscript", idx)
    starts = sorted({_func_start(fw, L) for L in idx.get(sva, []) if _func_start(fw, L)})
    if not starts:
        return None
    boot = starts[0]
    vf2 = reg = None
    for _at, v in _func_const_loads(fw, boot, span=0x300):
        s = _sec_of(fw, v)
        if s == ".data" and vf2 is None:
            vf2 = v
        elif s == ".bss" and reg is None:
            reg = v
    return dict(BOOT_LO=boot, VF2_VA=vf2, REG_BASE=reg)


def _find_cat0(fw, idx):
    sva = _str_va(fw, b"image-sc%02d.bin", idx)
    starts = sorted({_func_start(fw, L) for L in idx.get(sva, []) if _func_start(fw, L)})
    return starts[0] if starts else None


def _boot_md_hi(fw, boot_lo):
    """From the boot disasm: MASTERDIR_DECODE (the ``bl`` after ``str [r6],#4``)
    and BOOT_HI (the instr after the ``bne`` guarded by ``cmp r6,..``)."""
    ins = list(_disasm(fw, boot_lo, boot_lo + 0x400))
    md = bh = None
    for i, x in enumerate(ins):
        if x.mnemonic == "str" and "[r6], #4" in x.op_str:
            for j in range(i, min(i + 8, len(ins))):
                if ins[j].mnemonic == "bl":
                    md = int(ins[j].op_str.lstrip("#"), 0); break
        if (x.mnemonic == "bne" and ins[i - 1].mnemonic == "cmp"
                and "r6" in ins[i - 1].op_str):
            bh = ins[i + 1].address
    return md, bh


def _find_internal_pcs(fw, md_start):
    """MASTERDIR_MALLOC / BANDOBJ / BANDLOOP inside the master-dir decoder."""
    end = _func_end(fw, md_start)
    ins = list(_disasm(fw, md_start, end))
    out = {"_end": end}
    # MALLOC: bl preceded by `lsl _,_,#3` (*8) and `add _,r5,r5,lsl#1` (*3) = *24.
    # Window is 8 (not 6): some builds (e.g. Jurassic Park) put the *3 add 7
    # instructions ahead of the malloc bl, just outside a tighter window.
    for i, x in enumerate(ins):
        if x.mnemonic == "bl":
            win = ins[max(0, i - 8):i]
            if (any(w.mnemonic == "lsl" and w.op_str.endswith("#3") for w in win)
                    and any(w.mnemonic == "add" and "lsl #1" in w.op_str for w in win)
                    and i + 1 < len(ins)):
                out["MASTERDIR_MALLOC"] = ins[i + 1].address
                break
    # BANDOBJ: strb _,[rX,#0x1d] ; strb _,[rX,#0x1c] ; ... b <loop top>.
    for i in range(len(ins) - 2):
        a, b = ins[i], ins[i + 1]
        if (a.mnemonic == "strb" and "#0x1d]" in a.op_str
                and b.mnemonic == "strb" and "#0x1c]" in b.op_str):
            for j in range(i + 2, min(i + 5, len(ins))):
                if ins[j].mnemonic == "b":
                    out["BANDOBJ"] = ins[j].address
                    out["_bandobj_target"] = int(ins[j].op_str.lstrip("#"), 0)
                    break
            break
    # BANDLOOP: instr after the header-exit branch at the loop top.
    top = out.get("_bandobj_target")
    if top is not None:
        loop = list(_disasm(fw, top, top + 0x40))
        for k, x in enumerate(loop):
            if x.mnemonic in ("beq", "bne") and k + 1 < len(loop):
                out["BANDLOOP"] = loop[k + 1].address
                break
    return out


def _find_find_bl(fw, md_start, md_end):
    """The band-build template-lookup ``bl`` (skipped at runtime).  Canonical
    epilogue after the lookup returns the map node ptr in r0::

        A-0x18: bl <lookup>
        A-0x14: cmp r0, #0
        A-0x0c: ldr rX, [r0]        ; rX = *node (value-part base)
        A:      add rD, rX, #0x10    ; advance past the key (rD = OBJREG)

    The destination rD is build-specific and is NOT always == rX (Avengers:
    ``add r7,r7,#0x10``; Stranger Things: ``add r8,r3,#0x10``), so match any rD
    and anchor on the ``ldr rX,[r0]`` deref (Rt == the add's Rn) instead."""
    for va in range(md_start, md_end, 4):
        w = fw.w_text(va)
        if (w & 0xfff00fff) != 0xe2800010:     # add rD, rX, #0x10 (imm, cond=e)
            continue
        rx = (w >> 16) & 0xf                    # Rn = dereferenced node register
        ldr = fw.w_text(va - 0xc)              # ldr rX, [r0]
        if (((ldr & 0xffff0fff) == 0xe5900000) and ((ldr >> 12) & 0xf) == rx
                and fw.w_text(va - 0x14) == 0xe3500000              # cmp r0, #0
                and (fw.w_text(va - 0x18) & 0x0f000000) == 0x0b000000):  # bl
            return va - 0x18
    return None


def _find_rbtree_hdr(fw, cat0):
    """RBTREE_HDR: the most-loaded .bss address in the cat-0 register routine
    (the registry rb-tree header node)."""
    bss = fw.secs[".bss"]; c = collections.Counter()
    for va in range(cat0 - 0x1200, cat0 + 0x600, 4):
        wv = fw.w_text(va)
        if bss["addr"] <= wv < bss["addr"] + bss["size"]:
            c[wv] += 1
    if not c:
        return None
    return sorted(v for v, _ in c.most_common(2))[-1]


def _resolve_prov_qmul(fw, disp):
    """PROV (shared body provider) + QMUL_TABLE from a populated decode-slot
    function: PROV = the ``bl`` after ``ldr _,[_,#0x38]``; QMUL_TABLE = the
    function's first movw/movt const + 0x98.  Returns (prov, qmul) or (None,..)
    if no scale resolves both (the codec is dual-path / unsupported)."""
    t = fw.secs[".text"]; tlo, thi = t["addr"], t["addr"] + t["size"]
    for scale in range(32):
        fn = fw.u32_va(disp + 0x20 + scale * 0x40 + 4)
        if fn is None or not (tlo <= fn < thi):
            continue
        of = fw.off_of(fn)
        if of is None:
            continue
        code = fw.raw[of:of + 0x140]
        prov = qmul = pend = None; prev38 = False
        for x in _cs.disasm(code, fn):
            if x.mnemonic == "movw":
                pend = int(x.op_str.split("#")[1], 0)
            elif x.mnemonic == "movt" and pend is not None and qmul is None:
                qmul = ((int(x.op_str.split("#")[1], 0) << 16) | pend) + 0x98
            if x.mnemonic == "ldr" and "#0x38]" in x.op_str:
                prev38 = True
            elif x.mnemonic == "bl" and prev38:
                prov = int(x.op_str.lstrip("#"), 0); break
            elif x.mnemonic == "bl":
                prev38 = False
        if prov is not None and qmul is not None:
            return prov, qmul
    return None, None


# --------------------------------------------------------------------------
# top-level
# --------------------------------------------------------------------------
_REQUIRED = ("BOOT_LO", "BOOT_HI", "VF2_VA", "REG_BASE", "CAT0_REGISTER",
             "RBTREE_HDR", "MASTERDIR_DECODE", "MASTERDIR_MALLOC", "BANDLOOP",
             "BANDOBJ", "FIND_BL", "DISPATCH", "PROV", "QMUL_TABLE")


def locate_all(game_real_path=None, raw=None):
    """Locate every firmware address the codec oracle needs, generically.

    Returns a dict (keys = :data:`_REQUIRED` plus ``RBTREE_ACC`` and ``OBJREG``)
    or ``None`` if the build isn't a single-path decodable codec (any required
    address missing, or no PROV/QMUL resolvable -> dual-path / unsupported).
    """
    if raw is None:
        with open(game_real_path, "rb") as f:
            raw = f.read()
    try:
        fw = _FwView(raw)
        idx = _loader_index(fw)
        boot = _find_boot(fw, idx) or {}
        cat0 = _find_cat0(fw, idx)
        disp = _find_dispatch(fw)
        if not boot.get("BOOT_LO") or cat0 is None or disp is None:
            return None
        md, bh = _boot_md_hi(fw, boot["BOOT_LO"])
        if md is None or bh is None:
            return None
        ipc = _find_internal_pcs(fw, md)
        find_bl = _find_find_bl(fw, md, ipc["_end"])
        objreg = (fw.w_text(ipc["BANDOBJ"] - 8) >> 16) & 0xf if "BANDOBJ" in ipc else None
        hdr = _find_rbtree_hdr(fw, cat0)
        prov, qmul = _resolve_prov_qmul(fw, disp)
        res = dict(
            BOOT_LO=boot["BOOT_LO"], BOOT_HI=bh, VF2_VA=boot["VF2_VA"],
            REG_BASE=boot["REG_BASE"], CAT0_REGISTER=cat0, RBTREE_HDR=hdr,
            RBTREE_ACC=(hdr - 0xc) if hdr is not None else None,
            MASTERDIR_DECODE=md, MASTERDIR_MALLOC=ipc.get("MASTERDIR_MALLOC"),
            BANDLOOP=ipc.get("BANDLOOP"), BANDOBJ=ipc.get("BANDOBJ"),
            FIND_BL=find_bl, OBJREG=objreg, DISPATCH=disp, PROV=prov,
            QMUL_TABLE=qmul)
    except Exception:
        return None
    if any(res.get(k) is None for k in _REQUIRED) or objreg is None:
        return None
    return res
