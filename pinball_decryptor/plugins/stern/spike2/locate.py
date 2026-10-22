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
drives bit-exact decode + re-encode on all 26 shipped Spike 2 titles — including
the very large Foo Fighters / Led Zeppelin builds (their master-directory
decoder is found via :func:`_find_masterdir_decode`; they just take longer for
the one-time params derivation).  Should a *future* build's firmware shape ever
fail to fully locate, :func:`locate_all` returns ``None`` so the engine skips
audio gracefully — a safety net no current title hits.

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
    """ARM A1 MOVW/MOVT -> ('movw'|'movt', Rd, imm16), else None.

    A ``mov rd, #imm`` (rotated immediate, no S) whose value fits 16 bits
    reads as a ``movw``: the compiler picks it for a low half it can encode
    that way, and a ``movt`` after it builds the constant just the same
    (Avengers Pro 1.10's sound-bank CRC seed: ``mov r0,#0x3940 ; movt
    r0,#0xf148``)."""
    if (w & 0x0FF00000) == 0x03000000:
        return ("movw", (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF))
    if (w & 0x0FF00000) == 0x03400000:
        return ("movt", (w >> 12) & 0xF, ((w >> 4) & 0xF000) | (w & 0xFFF))
    if (w & 0x0FFF0000) == 0x03A00000:
        rot = ((w >> 8) & 0xF) * 2
        imm = w & 0xFF
        v = ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF if rot else imm
        if v <= 0xFFFF:
            return ("movw", (w >> 12) & 0xF, v)
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


def _find_masterdir_decode(fw):
    """Locate MASTERDIR_DECODE by its own band-build epilogue rather than the
    boot call site.  Scans ``.text`` for the codec-obj scale/chan store
    ``strb _,[rN,#0x1d]`` ; ``strb _,[rN,#0x1c]`` (e5cN_T01d / e5cN_T01c, same
    base reg), takes each hit's enclosing function, and returns the one whose
    internal PCs (the ``*24`` record malloc + band loop + band-obj epilogue) all
    resolve.  That signature is unique and reproduces the boot-derived address
    exactly on every locatable build, so it's a safe fallback for builds whose
    boot doesn't expose the ``str [r6],#4`` call site (the large Foo Fighters /
    Led Zeppelin builds)."""
    t = fw.secs[".text"]; base = t["addr"]; o = t["off"]; size = t["size"] & ~3
    starts = set()
    for i in range(0, size - 4, 4):
        if (_u32(fw.raw, o + i) & 0xfff00fff) != 0xe5c0001d:
            continue
        w0 = _u32(fw.raw, o + i); w1 = _u32(fw.raw, o + i + 4)
        if ((w1 & 0xfff00fff) == 0xe5c0001c
                and ((w0 >> 16) & 0xf) == ((w1 >> 16) & 0xf)):
            s = _func_start(fw, base + i, back=0x2000)
            if s:
                starts.add(s)
    for s in sorted(starts):
        ipc = _find_internal_pcs(fw, s)
        if all(ipc.get(k) for k in ("MASTERDIR_MALLOC", "BANDLOOP", "BANDOBJ")):
            return s
    return None


def _boot_md_hi(fw, boot_lo):
    """From the boot disasm: MASTERDIR_DECODE (the ``bl`` after ``str [r6],#4``)
    and BOOT_HI (the instr after the ``bne`` guarded by ``cmp r6,..``).  Large
    builds whose boot lacks the ``str [r6],#4`` call site fall back to locating
    MASTERDIR_DECODE by its band-build signature (:func:`_find_masterdir_decode`)."""
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
    if md is None:
        md = _find_masterdir_decode(fw)
    return md, bh


_REG_ALIAS = {"sb": 9, "sl": 10, "fp": 11, "ip": 12}


def _reg_index(name):
    """r0..r12 index for a capstone ARM register name (incl. sb/sl/fp/ip)."""
    name = name.strip()
    if name in _REG_ALIAS:
        return _REG_ALIAS[name]
    if name.startswith("r") and name[1:].isdigit():
        i = int(name[1:])
        return i if i <= 12 else None
    return None


def _find_internal_pcs(fw, md_start):
    """MASTERDIR_MALLOC / MASTERDIR_COUNT / BANDOBJ / BANDLOOP inside the
    master-dir decoder."""
    end = _func_end(fw, md_start)
    ins = list(_disasm(fw, md_start, end))
    out = {"_end": end}
    # MALLOC: bl preceded by `lsl _,_,#3` (*8) and `add _,rN,rN,lsl#1` (*3) = *24.
    # Window is 8 (not 6): some builds (e.g. Jurassic Park) put the *3 add 7
    # instructions ahead of the malloc bl, just outside a tighter window.
    #
    # COUNT: that `add _,rN,rN,lsl#1` is the ONLY place the record count is
    # provably live in a known register — rN holds it, and the instruction is
    # the first half of the *24 size computation.  Capturing the count there
    # (MASTERDIR_COUNT = its PC, COUNTREG = N) instead of at the malloc return
    # is build-shape-independent: some builds (Deadpool Pro 1.16) go on to
    # REUSE that same register for the aligned byte size they pass to malloc
    # (`add r5,r7,#0xf ; bic r5,r5,#0xf`), so by the malloc-return PC it reads
    # ~24x high and the derive chains through garbage records — the
    # "Deriving codec parameters" hang behind a field report.
    for i, x in enumerate(ins):
        if x.mnemonic == "bl":
            win = ins[max(0, i - 8):i]
            mul3 = [w for w in win
                    if w.mnemonic == "add" and "lsl #1" in w.op_str]
            if (any(w.mnemonic == "lsl" and w.op_str.endswith("#3") for w in win)
                    and mul3 and i + 1 < len(ins)):
                out["MASTERDIR_MALLOC"] = ins[i + 1].address
                # rD, rN, rN, lsl #1  ->  rN is the count (operands 1 and 2 are
                # the same register; the shifted operand is what makes it *3).
                p = [q.strip() for q in mul3[-1].op_str.split(",")]
                if len(p) >= 3 and p[1] == p[2]:
                    n = _reg_index(p[1])
                    if n is not None:
                        out["MASTERDIR_COUNT"] = mul3[-1].address
                        out["COUNTREG"] = n
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


def _is_body_provider(fw, va):
    """True if ``va`` begins the shared codec body provider, identified by its
    distinctive prologue: ``push {r4-r8,sb,sl,fp,lr}`` ; ``movw r6,#imm`` ;
    ``movt r6,#1`` ; ``cmp r6,#0`` (a guard on a ~0x1_0000 asset-registry count).
    Every decode-slot fn calls this one function to fetch its body, so the PROV
    ``bl`` is identified by its *target*, not the call site -- the body-descriptor
    pointer arg is loaded from ``[_,#0x38]`` on some builds and ``[_,#0xa94]`` on
    others, so anchoring on a fixed call-site ``ldr`` offset misses many."""
    t = fw.secs[".text"]
    if not (t["addr"] <= va < t["addr"] + t["size"]):
        return False
    w0 = fw.w_text(va); w1 = fw.w_text(va + 4); w2 = fw.w_text(va + 8)
    return (w0 == 0xe92d4ff0
            and (w1 & 0xfff0f000) == 0xe3006000      # movw r6, #imm
            and (w2 & 0xfff0ffff) == 0xe3406001)     # movt r6, #1


def _resolve_prov_qmul(fw, disp):
    """PROV (shared body provider) + QMUL_TABLE from a populated decode-slot
    function: QMUL_TABLE = the fn's first movw/movt const + 0x98; PROV = the
    first ``bl`` whose target is the shared body provider (:func:`_is_body_provider`).
    Returns (prov, qmul) or (None, None) if no scale resolves both.

    Many builds emit the codec's ``cursor>=length`` early-out path *first*, so
    the normal decode body -- and its PROV ``bl`` -- can sit ~0x480 into the fn,
    well past the old fixed 0x140 prologue window.  Scan the whole fn instead.
    The fn's own ``push`` prologue may itself sit a few instrs in (after the
    qmul-table setup), so anchor the end-of-fn search after that push."""
    t = fw.secs[".text"]; tlo, thi = t["addr"], t["addr"] + t["size"]
    for scale in range(32):
        fn = fw.u32_va(disp + 0x20 + scale * 0x40 + 4)
        if fn is None or not (tlo <= fn < thi):
            continue
        of = fw.off_of(fn)
        if of is None:
            continue
        p0 = fn
        for off in range(0, 0x20, 4):
            w = fw.w_text(fn + off)
            if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):  # push {..,lr}
                p0 = fn + off; break
        code = fw.raw[of:of + (_func_end(fw, p0) - fn)]
        prov = qmul = pend = None
        for x in _cs.disasm(code, fn):
            if x.mnemonic == "movw":
                pend = int(x.op_str.split("#")[1], 0)
            elif x.mnemonic == "movt" and pend is not None and qmul is None:
                qmul = ((int(x.op_str.split("#")[1], 0) << 16) | pend) + 0x98
            elif x.mnemonic == "bl":
                tgt = int(x.op_str.lstrip("#"), 0)
                if _is_body_provider(fw, tgt):
                    prov = tgt; break
        if prov is not None and qmul is not None:
            return prov, qmul
    return None, None


# --------------------------------------------------------------------------
# master-directory crypto (optional; consumed by :mod:`.masterdir`)
# --------------------------------------------------------------------------
# First 16 bytes of each table -- unique in a 6-70 MB ELF, and present in
# rodata on every Spike 2 build examined.
_SBOX16 = bytes.fromhex("637c777bf26b6fc53001672bfed7ab76")
_CRC_TAB16 = struct.pack("<4I", 0x00000000, 0x77073096, 0xEE0E612C, 0x990951BA)
# A table's address may be taken a little way in (an inner loop indexing
# ``table + k``), so accept a load anywhere in its first quarter.
_TABLE_SPAN = 0x400


def _va_of_off(fw, off):
    for s in fw.segs:
        if s["off"] <= off < s["off"] + s["filesz"]:
            return s["vaddr"] + (off - s["off"])
    return None


def _find_table(fw, pat):
    """vaddr of the first occurrence of ``pat`` inside a load segment."""
    start = 0
    while True:
        i = fw.raw.find(pat, start)
        if i == -1:
            return None
        va = _va_of_off(fw, i)
        if va is not None:
            return va
        start = i + 1


def _func_end_late_push(fw, start, maxspan=0x1c00):
    """Function end for a routine whose ``push {..,lr}`` is NOT its first
    instruction.

    The AES and CRC entries set up a register or two before pushing, so
    :func:`_func_end` -- "the next push" -- stops on the function's OWN
    prologue a couple of instructions in, and a constant scan bounded by it
    sees nothing at all.  Skip any push inside the first 0x20 bytes, then take
    the next one."""
    t = fw.secs[".text"]
    o = t["off"]
    base = t["addr"]
    if not (base <= start < base + t["size"]):
        return start
    hi = min(start + maxspan, base + t["size"])
    for va in range(start + 4, hi, 4):
        w = _u32(fw.raw, o + (va - base))
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):
            if va - start <= 0x20:
                continue                  # this function's own late prologue
            return va
    return start + maxspan


def _consts_in(fw, lo, hi):
    """Every 32-bit constant materialised in ``[lo, hi)``: movw/movt pairs and
    PC-relative literal loads (the two ways these builds form a table
    address)."""
    vals = set()
    pend = {}
    for va in range(lo, hi, 4):
        w = fw.u32_va(va)
        if w is None:
            break
        d = _decode_movw_movt(w)
        if d:
            kind, rd, imm = d
            if kind == "movw":
                pend[rd] = imm
            elif rd in pend:
                vals.add((imm << 16) | pend[rd])
            continue
        if (w & 0x0F7F0000) in (0x051F0000, 0x059F0000):   # ldr rD, [pc, #imm]
            imm = w & 0xFFF
            lit = va + 8 + (imm if (w & 0x00800000) else -imm)
            v = fw.u32_va(lit)
            if v is not None:
                vals.add(v)
    return vals


def _bl_sites(fw, lo, hi):
    """``[(call_site, target), ...]`` for every ARM ``bl`` in ``[lo, hi)``."""
    out = []
    for va in range(lo, hi, 4):
        w = fw.u32_va(va)
        if w is None:
            break
        if (w & 0x0F000000) == 0x0B000000:
            off = w & 0x00FFFFFF
            if off & 0x800000:
                off -= 0x1000000
            out.append((va, (va + 8 + off * 4) & 0xFFFFFFFF))
    return out


def _reaches_table(fw, fn, table_va, depth=1, span=0x400, _seen=None):
    """True if ``fn`` -- or, within ``depth`` levels, something it calls --
    materialises an address inside the table at ``table_va``."""
    if fn is None or table_va is None:
        return False
    if _seen is None:
        _seen = set()
    if fn in _seen:
        return False
    _seen.add(fn)
    hi = min(fn + span, _func_end_late_push(fw, fn))
    for v in _consts_in(fw, fn, hi):
        if table_va <= v < table_va + _TABLE_SPAN:
            return True
    if depth > 0:
        for _site, tgt in _bl_sites(fw, fn, hi):
            if _reaches_table(fw, tgt, table_va, depth - 1, span, _seen):
                return True
    return False


def _crc_init_arg(fw, site, back=0x28):
    """The CRC's initial value: the movw/movt pair loading r0 just before the
    call (TMNT ``movw r0,#0x8ff1 ; movt r0,#0x11a5`` -> 0x11a58ff1)."""
    lo16 = hi16 = None
    for va in range(max(fw.secs[".text"]["addr"], site - back), site, 4):
        d = _decode_movw_movt(fw.u32_va(va) or 0)
        if not d or d[1] != 0:
            continue
        if d[0] == "movw":
            lo16 = d[2]
        else:
            hi16 = d[2]
    if lo16 is None or hi16 is None:
        return None
    return (hi16 << 16) | lo16


def _crc_gate(fw, crc_site, hi):
    """The ``cmp`` of the computed CRC against the permuted seed word, and
    which register holds the expected value.  Either operand order."""
    for va in range(crc_site + 4, min(crc_site + 0x40, hi), 4):
        w = fw.u32_va(va)
        if w is None:
            break
        if (w & 0x0FFF0FF0) != 0x01500000:        # cmp rN, rM (no shift)
            continue
        rn = (w >> 16) & 0xF
        rm = w & 0xF
        if rn == 0 and rm != 0:
            return va, rm
        if rm == 0 and rn != 0:
            return va, rn
    return None, None


def _loop_bound_slot(fw, md_start):
    """The stack slot the band loop compares its record counter against
    (TMNT ``ldr r2,[sp,#0x14c] ; cmp r3,r2 ; beq``).  Raising it is what lets
    the chain run one record past the catalog, onto an appended record."""
    ipc = _find_internal_pcs(fw, md_start)
    top = ipc.get("_bandobj_target")
    if top is None:
        return None
    slot = None
    for x in _disasm(fw, top, top + 0x40):
        if x.mnemonic == "ldr" and "[sp," in x.op_str and "#" in x.op_str:
            try:
                slot = int(x.op_str.rsplit("#", 1)[1].rstrip("]"), 0)
            except ValueError:
                slot = None
        elif x.mnemonic == "cmp" and slot is not None:
            return slot
    return None


def find_masterdir_crypto(fw, md_start, md_end=None):
    """Locate the master-directory cipher sites, or return ``None``.

    Keys: ``SBOX_VA``, ``CRC_TABLE_VA``, ``AES_INIT``, ``CBC``, ``CRC``,
    ``CRC_GATE``, ``CRC_EXPECT_REG``, ``CRC_INIT``, ``LOOP_BOUND_SLOT``.

    ``AES_INIT`` and ``CBC`` are the decoder's two calls into the AES module,
    taken in program order -- the key schedule must precede the decrypt.  They
    are NOT told apart by the inverse S-box: neither call reaches it on any
    build examined, so :mod:`.masterdir` confirms the pairing at runtime, where
    the CBC call's buffer argument is the record array.

    Everything here is read from the ELF; nothing boots.  Reported as OPTIONAL
    keys from :func:`locate_all`, so a build this misses still decodes audio --
    only growing the sound bank is refused there, with a named reason."""
    if md_end is None:
        md_end = _func_end(fw, md_start)
    sbox = _find_table(fw, _SBOX16)
    crctab = _find_table(fw, _CRC_TAB16)
    if sbox is None or crctab is None:
        return None
    calls = _bl_sites(fw, md_start, md_end)
    aes = [s for s, t in calls if _reaches_table(fw, t, sbox, depth=1)]
    crc = [s for s, t in calls if _reaches_table(fw, t, crctab, depth=1)]
    if len(aes) < 2 or not crc:
        return None
    out = {"SBOX_VA": sbox, "CRC_TABLE_VA": crctab,
           "AES_INIT": aes[0], "CBC": aes[1], "CRC": crc[0]}
    gate, reg = _crc_gate(fw, out["CRC"], md_end)
    out["CRC_GATE"] = gate
    out["CRC_EXPECT_REG"] = reg
    out["CRC_INIT"] = _crc_init_arg(fw, out["CRC"])
    out["LOOP_BOUND_SLOT"] = _loop_bound_slot(fw, md_start)
    if any(out[k] is None for k in
           ("CRC_GATE", "CRC_EXPECT_REG", "CRC_INIT", "LOOP_BOUND_SLOT")):
        return None
    return out


def masterdir_crypto(raw=None, game_real_path=None, md_start=None):
    """:func:`find_masterdir_crypto` from raw ELF bytes, locating
    ``MASTERDIR_DECODE`` first when it isn't given.  ``None`` on any failure --
    an unmappable build must degrade, never raise."""
    try:
        if raw is None:
            with open(game_real_path, "rb") as f:
                raw = f.read()
        fw = _FwView(raw)
        if md_start is None:
            boot = _find_boot(fw, _loader_index(fw)) or {}
            if not boot.get("BOOT_LO"):
                return None
            md_start, _bh = _boot_md_hi(fw, boot["BOOT_LO"])
            if md_start is None:
                return None
        return find_masterdir_crypto(fw, md_start)
    except Exception:
        return None


def find_band_codecs(fw, dispatch):
    """Where the codec dispatch keeps a MULTI-BAND record's render functions
    (PAD-637), as ``{"BAND_RENDER": off}``: the stereo function of scale ``S``
    is the pointer at ``dispatch + off + 0x40 * S``, the mono one 4 bytes on.
    ``None`` when the selector isn't found.

    The voice setup picks a sound's codec from its obj: chan (+0x1b), bands
    (+0x1c) and scale (+0x1d)::

        ldrb r2, [obj, #0x1b] ; ldrb r1, [obj, #0x1c] ; sub r2, r2, #1
        ldrb r3, [obj, #0x1d] ; clz r2, r2 ; cmp r1, #1 ; ...
        bls  <one band>       ; cmp <voice+0x2c>, #0 ; beq <...>
        cmp r2, #0 ; movw/movt base ; add r3, base, r3, lsl #6
        ldrne r2, [r3, #-mono] ; ldreq r2, [r3, #-stereo] ; ...

    Read from the code, not assumed from the table: the table's 0x40-aligned
    base (:func:`_find_dispatch`) sits at a different place in each build's
    rows, so the slot a plain sound resolves to says nothing about the
    multi-band one (Led Zeppelin Pro 1.22's plain codec IS its multi-band
    one, Foo Fighters 1.04's is not)."""
    t = fw.secs[".text"]
    raw, toff, tva, tsz = fw.raw, t["off"], t["addr"], t["size"]
    for o in range(toff, toff + tsz - 4, 4):
        w = _u32(raw, o)
        if (w & 0x0FFF0FF0) != 0x016F0F10 or (w >> 28) != 0xE:     # clz
            continue
        va = tva + (o - toff)
        ins = list(_disasm(fw, va - 0x18, va + 0x40))
        ops = [(x.mnemonic, x.op_str) for x in ins]
        head = " | ".join("%s %s" % m for m in ops[:7])
        if "#0x1b]" not in head or "#0x1c]" not in head or "#0x1d]" not in head:
            continue
        base = {}
        reg_base = None
        for i, x in enumerate(ins):
            w2 = fw.w_text(x.address)
            mm = _decode_movw_movt(w2)
            if mm and mm[0] == "movw":
                base[mm[1]] = mm[2]
            elif mm and mm[0] == "movt" and mm[1] in base:
                base[mm[1]] |= mm[2] << 16
                reg_base = base[mm[1]]
            elif reg_base is not None and x.mnemonic in ("ldrne", "ldreq")                     and "#-" in x.op_str:
                nxt = ins[i + 1] if i + 1 < len(ins) else None
                if nxt is None or nxt.mnemonic not in ("ldrne", "ldreq"):
                    break
                offs = {}
                for y in (x, nxt):
                    offs[y.mnemonic] = int(y.op_str.split("#-")[1].rstrip("]"), 16)
                if set(offs) != {"ldrne", "ldreq"}                         or offs["ldreq"] - offs["ldrne"] != 4:
                    break
                return {"BAND_RENDER": reg_base - offs["ldreq"] - dispatch}
    return None


# --------------------------------------------------------------------------
# top-level
# --------------------------------------------------------------------------
_REQUIRED = ("BOOT_LO", "BOOT_HI", "VF2_VA", "REG_BASE", "CAT0_REGISTER",
             "RBTREE_HDR", "MASTERDIR_DECODE", "MASTERDIR_MALLOC", "BANDLOOP",
             "BANDOBJ", "FIND_BL", "DISPATCH", "PROV", "QMUL_TABLE")


def locate_all(game_real_path=None, raw=None):
    """Locate every firmware address the codec oracle needs, generically.

    Returns a dict (keys = :data:`_REQUIRED` plus ``RBTREE_ACC`` and ``OBJREG``)
    or ``None`` if any required address isn't found (:func:`missing` names
    which).
    """
    if raw is None:
        with open(game_real_path, "rb") as f:
            raw = f.read()
    res, _gone = _locate(raw)
    return res


def missing(game_real_path=None, raw=None):
    """What :func:`locate_all` could not find in this game program, as the
    :data:`_REQUIRED` names (``OBJREG`` for the band object's register, or
    ``"ELF: <why>"`` when the file doesn't read as a game program at all).
    Empty when everything locates.  PAD-657: a user's card that doesn't
    locate says which part, so the program they send in is a lead."""
    if raw is None:
        with open(game_real_path, "rb") as f:
            raw = f.read()
    return _locate(raw)[1]


# --------------------------------------------------------------------------
# board-keyed builds (PAD-674): the sound key comes from the CPU board
# --------------------------------------------------------------------------
def _fn_ins(fw, fn, span=0x100):
    """*fn*'s instructions up to the next ``push {..,lr}`` or *span* bytes."""
    t = fw.secs[".text"]
    hi = min(fn + span, t["addr"] + (t["size"] & ~3))
    if not t["addr"] <= fn < hi:
        return []
    for va in range(fn + 4, hi, 4):
        w = _u32(fw.raw, t["off"] + (va - t["addr"]))
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):
            hi = va
            break
    return list(_disasm(fw, fn, hi))


def _frame_sender(fw, fn, span=0x100):
    """If *fn* builds a ``0d 05`` node-bus frame on its stack -- the request
    that has the CPU board's bus master compute a 4-byte answer (``mov
    rX,#0xd ; strb rX,[sp,#n]`` and ``mov rY,#5 ; strb rY,[sp,#n+1]``, JP
    1.13's 0x46474c; PAD-603 met the frame in Venom LE 0.95) -- the target
    of the ``bl`` that sends it: the bus exchange ``(frame, reply, len) ->
    ok``.  None otherwise."""
    regs = {}; stores = {}
    built = False
    for x in _fn_ins(fw, fn, span):
        ops = [o.strip() for o in x.op_str.split(",")]
        if x.mnemonic == "mov" and len(ops) == 2 and ops[1].startswith("#"):
            try:
                regs[ops[0]] = int(ops[1][1:], 0)
            except ValueError:
                regs.pop(ops[0], None)
        elif x.mnemonic == "strb" and ops[0] in regs and ops[1].startswith("[sp"):
            if len(ops) == 2 and ops[1] == "[sp]":
                off = 0
            elif len(ops) == 3 and ops[1] == "[sp" and ops[2].startswith("#"):
                off = int(ops[2][1:].rstrip("]"), 0)
            else:
                off = None
            if off is not None:
                stores[off] = regs[ops[0]]
                built = any(v == 0xd and stores.get(o + 1) == 5 for o, v in stores.items())
        elif x.mnemonic == "bl" and built:
            return int(x.op_str.lstrip("#"), 0)
        elif ops and ops[0] in regs and x.mnemonic not in ("strb", "str", "cmp", "tst"):
            regs.pop(ops[0], None)
    return None


def _masks_slot(fw, fn):
    """True if *fn* takes its frame's op from ``r0 & 0x30``: the slot setter
    (JP 1.13's 0x4646cc), which also seeds the game's own reply mask."""
    return any(x.mnemonic == "and" and x.op_str.endswith("#0x30")
               for x in _fn_ins(fw, fn))


_ARG_REGS = {"r0": 0, "r1": 1, "r2": 2, "r3": 3, "ip": 12, "lr": 14}


def _init_seeds(fw, site):
    """The four slot seeds the bus init at *site* (a ``bl``) is called with:
    its 3rd to 6th arguments ``(r2, r3, [sp], [sp+4])``, constants the caller
    builds with movw/movt just before the call.  None if any is not a
    constant there."""
    start = _func_start(fw, site) or site - 0x80
    ins = list(_disasm(fw, max(start, site - 0x80), site))
    consts = {}
    stack = {}
    for x in ins:
        mm = _decode_movw_movt(fw.w_text(x.address))
        if mm and mm[0] == "movw":
            consts[mm[1]] = mm[2]
        elif mm and mm[0] == "movt" and mm[1] in consts:
            consts[mm[1]] = (consts[mm[1]] & 0xffff) | (mm[2] << 16)
        elif x.mnemonic == "str":
            ops = [o.strip() for o in x.op_str.split(",")]
            if len(ops) == 2 and ops[1] == "[sp]":
                stack[0] = _ARG_REGS.get(ops[0])
            elif len(ops) == 3 and ops[1] == "[sp" and ops[2] == "#4]":
                stack[4] = _ARG_REGS.get(ops[0])
    regs = [2, 3, stack.get(0), stack.get(4)]
    if any(r is None or r not in consts for r in regs):
        return None
    return tuple(consts[r] for r in regs)


def _bucket_off(fw, md, bss, default=0xad8):
    """Where the master-directory decoder keeps the band-template map's
    bucket count, as an offset from the sound object *bss*: the ``ldr r1,
    [rX, #off]`` right after rX is built as *bss* (0xad8 on JP LE 1.16, 0xa88
    on 1.13).  The emulator writes a nonzero count at REG_BASE + 0xad8, so
    REG_BASE is set from this."""
    ins = list(_disasm(fw, md, _func_end(fw, md, maxspan=0x2400)))
    pend = {}
    armed = None
    for x in ins:
        mm = _decode_movw_movt(fw.w_text(x.address))
        if mm and mm[0] == "movw":
            pend[mm[1]] = (mm[2], x.address)
        elif mm and mm[0] == "movt" and mm[1] in pend:
            if ((mm[2] << 16) | pend[mm[1]][0]) == bss:
                armed = (mm[1], x.address)
        elif armed and x.mnemonic == "ldr" and x.address - armed[1] <= 12:
            ops = [o.strip() for o in x.op_str.split(",")]
            if (len(ops) == 3 and ops[0] == "r1" and _reg_index(ops[1].lstrip("[")) == armed[0]
                    and ops[2].startswith("#")):
                return int(ops[2][1:].rstrip("]"), 0)
    return default


def _bus_parts(fw, md):
    """What a board-keyed program (see :mod:`.netbridge`) needs besides the
    codec addresses, or None for a program that seeds from constants:

    * ``BOOT_LO``/``BOOT_HI``: the sound init that calls the master-directory
      decoder *md*, up to that call; before it, it calls a key builder that
      asks the bus (:func:`_frame_sender`).  ``VF2_VA`` is the .data table the
      init hands the key builder, ``BSS`` its sound object.
    * ``BUS_XCHG``: the bus exchange the frame builders call.
    * ``BUS_SEED``: the slot setter (:func:`_masks_slot`); ``BUS_SEEDS``: the
      four seeds its init is called with (:func:`_init_seeds`), slot order.
      Both None when the program asks the bus but these aren't found.
    """
    t = fw.secs[".text"]
    text = (t["addr"], t["addr"] + (t["size"] & ~3))
    sites = _bl_sites(fw, *text)
    boot = ask_fn = xchg = md_site = None
    for site, tgt in sites:
        if tgt != md:
            continue
        start = _func_start(fw, site)
        if start is None:
            continue
        for _s, fn in _bl_sites(fw, start, site):
            if fn == md:
                break
            for c in [fn] + [f2 for _s2, f2 in _bl_sites(fw, fn, _func_end(fw, fn))]:
                x = _frame_sender(fw, c)
                if x is not None:
                    boot, ask_fn, xchg, md_site = start, c, x, site
                    break
            if boot is not None:
                break
        if boot is not None:
            break
    if boot is None:
        return None
    out = dict(BOOT_LO=boot, BOOT_HI=md_site - 4, MASTERDIR_DECODE=md,
               BUS_XCHG=xchg, BUS_ASK=ask_fn, BUS_SEED=None, BUS_SEEDS=None,
               VF2_VA=None, BSS=None)
    for _at, v in _func_const_loads(fw, boot, span=md_site - boot):
        s = _sec_of(fw, v)
        if s == ".data" and out["VF2_VA"] is None:
            out["VF2_VA"] = v
        elif s == ".bss" and out["BSS"] is None:
            out["BSS"] = v
    callers = sorted({_func_start(fw, s) for s, tg in sites if tg == xchg} - {None})
    for fn in callers:
        if fn != ask_fn and _frame_sender(fw, fn) == xchg and _masks_slot(fw, fn):
            out["BUS_SEED"] = fn
            break
    if out["BUS_SEED"] is None:
        return out
    inits = sorted({_func_start(fw, s) for s, tg in sites if tg == out["BUS_SEED"]} - {None})
    for init in inits:
        n = sum(1 for _s, tg in _bl_sites(fw, init, _func_end(fw, init)) if tg == out["BUS_SEED"])
        if n < 4:
            continue
        for s, tg in sites:
            if tg == init:
                seeds = _init_seeds(fw, s)
                if seeds:
                    out["BUS_SEEDS"] = seeds
                    return out
    return out


def _locate(raw):
    """``(addresses or None, [what is missing])`` for :func:`locate_all` and
    :func:`missing`.  A program that doesn't locate the usual way and asks
    the CPU board for its sound key (:func:`_bus_parts`) is located with its
    sound init, bus exchange and seeds; one whose bus parts can't all be
    found is ``["BOARD_KEY"]``."""
    res, gone = _locate_parts(raw)
    if not gone or gone[0].startswith("ELF"):
        return res, gone
    try:
        fw = _FwView(raw)
        md = _find_masterdir_decode(fw)
        bus = _bus_parts(fw, md) if md is not None else None
    except Exception:
        return res, gone
    if bus is None:
        return res, gone
    if not bus["BUS_SEEDS"] or bus["VF2_VA"] is None or bus["BSS"] is None:
        return None, ["BOARD_KEY"]
    res2, gone2 = _locate_parts(
        raw, boot=dict(BOOT_LO=bus["BOOT_LO"], VF2_VA=bus["VF2_VA"], REG_BASE=bus["BSS"]),
        md_bh=(md, bus["BOOT_HI"]))
    if res2 is None:
        return None, gone2
    res2["REG_BASE"] = bus["BSS"] + _bucket_off(fw, md, bus["BSS"]) - 0xad8
    for k in ("BUS_XCHG", "BUS_ASK", "BUS_SEED", "BUS_SEEDS"):
        res2[k] = bus[k]
    return res2, []


def _locate_parts(raw, boot=None, md_bh=None):
    """The codec addresses; *boot* and *md_bh* stand in for the boot finder
    and the boot's master-directory call on a board-keyed program."""
    step = "ELF"
    try:
        fw = _FwView(raw)
        idx = _loader_index(fw)
        step = "BOOT_LO"
        boot = dict(boot) if boot else (_find_boot(fw, idx) or {})
        step = "CAT0_REGISTER"
        cat0 = _find_cat0(fw, idx)
        step = "DISPATCH"
        disp = _find_dispatch(fw)
        early = ((["BOOT_LO"] if not boot.get("BOOT_LO") else [])
                 + (["CAT0_REGISTER"] if cat0 is None else [])
                 + (["DISPATCH"] if disp is None else []))
        if early:
            return None, early
        step = "MASTERDIR_DECODE"
        md, bh = md_bh if md_bh else _boot_md_hi(fw, boot["BOOT_LO"])
        if md is None or bh is None:
            return None, [k for k, v in (("MASTERDIR_DECODE", md),
                                         ("BOOT_HI", bh)) if v is None]
        step = "BANDLOOP"
        ipc = _find_internal_pcs(fw, md)
        step = "FIND_BL"
        find_bl = _find_find_bl(fw, md, ipc["_end"])
        objreg = (fw.w_text(ipc["BANDOBJ"] - 8) >> 16) & 0xf if "BANDOBJ" in ipc else None
        step = "RBTREE_HDR"
        hdr = _find_rbtree_hdr(fw, cat0)
        step = "PROV"
        prov, qmul = _resolve_prov_qmul(fw, disp)
        res = dict(
            BOOT_LO=boot["BOOT_LO"], BOOT_HI=bh, VF2_VA=boot["VF2_VA"],
            REG_BASE=boot["REG_BASE"], CAT0_REGISTER=cat0, RBTREE_HDR=hdr,
            RBTREE_ACC=(hdr - 0xc) if hdr is not None else None,
            MASTERDIR_DECODE=md, MASTERDIR_MALLOC=ipc.get("MASTERDIR_MALLOC"),
            BANDLOOP=ipc.get("BANDLOOP"), BANDOBJ=ipc.get("BANDOBJ"),
            FIND_BL=find_bl, OBJREG=objreg, DISPATCH=disp, PROV=prov,
            QMUL_TABLE=qmul,
            # Optional (not in _REQUIRED): where the record count is provably
            # live.  A build whose *24 computation doesn't parse simply falls
            # back to the malloc-return capture.
            MASTERDIR_COUNT=ipc.get("MASTERDIR_COUNT"),
            COUNTREG=ipc.get("COUNTREG"))
        # Optional: the master-directory cipher sites.  A build these miss
        # decodes audio exactly as before; only growing the sound bank is
        # refused, with a named reason (see :mod:`.masterdir`).
        step = "MASTERDIR_CRYPTO"
        res["MASTERDIR_CRYPTO"] = find_masterdir_crypto(fw, md, ipc["_end"])
        # Optional: a build this misses decodes every plain sound as before;
        # its multi-band records decode through the resolved slot instead.
        try:
            res.update(find_band_codecs(fw, disp) or {})
        except Exception:
            pass
    except Exception as e:
        return None, [("ELF: %s" % e) if step == "ELF" else step]
    gone = [k for k in _REQUIRED if res.get(k) is None]
    if objreg is None:
        gone.append("OBJREG")
    return (None, gone) if gone else (res, [])
