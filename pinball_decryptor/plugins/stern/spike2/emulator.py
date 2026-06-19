"""Boot ``game_real`` in unicorn and use it as the Spike 2 audio codec oracle.

This is the self-contained merge of the proven reverse-engineering harness:

  * boots the firmware from the parsed ELF (segments + GOT import stubs);
  * lets the firmware's own boot build the vf2 keystream **and** the runtime
    tables (no captured ``vf2_table.bin`` / ``cap8_rt_*`` files);
  * serves ``image.bin`` to the firmware loader through an offset-identity mmap
    window paged on demand (so the native asset registration runs and we can
    derive every sound's decode params straight from the card);
  * decodes a sound by driving the scale-selected codec function and feeding the
    body through the shared body-provider hook (synthesized voice — the codec
    only reads ``voice[0]`` = obj ptr and ``voice[0xc]`` = cursor; the volume is
    the passed constant).

Everything derives from ``game_real`` + ``image.bin``; nothing is bundled.  The
only firmware-version coupling is the set of hardcoded addresses below (stable
across games on the same Spike 2 build).
"""

import mmap
import struct

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_FETCH_UNMAPPED,
                     UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_MODE_ARM, Uc, UcError)
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC,
                               UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                               UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                               UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
                               UC_ARM_REG_SP)

from . import rbtree as RB
from .elf import parse_elf

# r0..r12 as an explicit ordered list (don't assume the unicorn const ids are
# contiguous).  Index 9 = r9, etc.
_R = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
      UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
      UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12]

PAGE = 0x1000


def _algn(x, a=PAGE):
    return (x + a - 1) & ~(a - 1)


def _u16(b, o=0):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


# --- firmware addresses (this Spike 2 build) --------------------------------
VF2_VA = 0x5bb97c          # vf2 keystream base
REG_BASE = 0x6c33f8        # runtime register block (rt table ptrs at +0xac4/8/c)
DESC_BASE = 0x703da000     # image.bin offset-identity window anchor
PROV = 0x3e8e9c            # shared codec body-provider
DISPATCH = 0x539d00        # codec dispatch: render base; decode = +0x20
QMUL_TABLE = 0x530af8      # mem16[QMUL_TABLE + 2*VOL] = volume multiply
BOOT_LO, BOOT_HI = 0x348198, 0x348408   # boot: build keystream + rt tables
CAT0_REGISTER = 0x3e7008   # register category 0
RBTREE_HDR = 0x6c7a8c      # registry rb-tree header node
RBTREE_ACC = 0x6c7a80      # byte accumulator
MASTERDIR_DECODE = 0x346d2c  # decode master directory + per-record band build
MASTERDIR_MALLOC = 0x346d74  # after malloc: r0 = dir buffer, r5 = record count
BANDLOOP = 0x347944        # per-record band-build loop head
BANDOBJ = 0x3480a8         # band-build epilogue: r7 = built codec obj
CHAIN_STUBS = (0x4bda28, 0x4bdad0, 0x348550)  # stubbed to 0 during the chain
LENGTH_XOR = 0x5572ae9b    # length = this ^ record[16]

VOL = {1: 28, 2: 11}       # mono / stereo mixer volume -> QMUL 22294 / 42905

# Byte signatures (ARM function prologues) of the supported firmware build at a
# few of the hardcoded addresses above.  The codec oracle is pinned to this
# exact build; a card whose ``game`` ELF doesn't match is a *different* Spike 2
# build (different title/version) whose codec lives at other addresses, so its
# keystream can't be built from these constants.  Video extraction is fully
# data-driven and still works; audio decode needs this map to match.
_BUILD_SIG = {
    BOOT_LO:       bytes.fromhex("f0432de9"),   # stmdb sp!, {r4-r9, lr}
    CAT0_REGISTER: bytes.fromhex("f0402de9"),   # stmdb sp!, {r4-r7, lr}
    PROV:          bytes.fromhex("f04f2de9"),   # stmdb sp!, {r4-r11, lr}
}


def firmware_build_supported(game_real_path):
    """True if the card's ``game`` firmware is the build the codec oracle was
    mapped from (so the hardcoded addresses above are valid).  Cheap: parses the
    ELF program headers and compares a few prologue bytes; never boots."""
    try:
        raw = open(game_real_path, "rb").read()
        segs, _ = parse_elf(raw)
    except Exception:
        return False

    def _at(va, n):
        for vaddr, off, filesz, _memsz in segs:
            if vaddr <= va < vaddr + filesz:
                return raw[off + (va - vaddr): off + (va - vaddr) + n]
        return b""

    return all(_at(va, len(sig)) == sig for va, sig in _BUILD_SIG.items())


class Spike2Emu:
    # memory layout (no region overlaps; see module docstring)
    STK = 0x20000000; STKSZ = 0x00400000
    HEAP = 0x30000000; HEAPSZ = 0x20000000          # 0x30000000..0x50000000
    IMPORT = 0x60000000
    LAND = 0x10000000                               # decode return sentinel
    OBJ_VA = 0x18000000; VOICE_VA = 0x18001000      # codec obj + voice
    BB = 0x50000000                                 # body buffer (grown lazily)

    def __init__(self, game_real_path, image_path):
        raw = open(game_real_path, "rb").read()
        segs, relocs = parse_elf(raw)
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu = mu
        for vaddr, off, filesz, memsz in segs:
            b = vaddr & ~0xfff
            e = _algn(vaddr + memsz)
            mu.mem_map(b, e - b)
            mu.mem_write(vaddr, raw[off:off + filesz])
        mu.mem_map(self.STK, self.STKSZ)
        mu.mem_map(self.HEAP, self.HEAPSZ)
        mu.mem_map(self.IMPORT & ~0xfff, 0x4000)
        mu.mem_map(self.LAND & ~0xfff, PAGE)
        self.heap = self.HEAP + 0x100000

        # image.bin backing (offset-identity window; keep the handle alive).
        self._imgf = open(image_path, "rb")
        self.mm = mmap.mmap(self._imgf.fileno(), 0, access=mmap.ACCESS_READ)
        self.imgsize = self.mm.size()
        self.mapped_pages = set()

        # GOT import stubs: point each slot at a per-name sentinel address.
        self.name2sent = {}; self.imports = {}
        sent = self.IMPORT
        for got_va, name in relocs:
            if name not in self.name2sent:
                self.name2sent[name] = sent
                self.imports[sent] = name
                sent += 4
            try:
                mu.mem_write(got_va, struct.pack("<I", self.name2sent[name]))
            except UcError:
                pass
        mu.mem_write(self.IMPORT, b"\x00" * 0x4000)

        self.fds = {}; self.nextfd = 10
        self.faults = []; self.ondemand = 0
        self.extra = {}; self.log = []
        self._hooks()

        # decode scratch (set up lazily by setup_decode)
        self.BBSZ = 0
        self.ACC = None
        self._decode_ready = False
        self._mapped = set()
        self.st = {"R": 0, "k": 0}

    # ---- on-demand paging ---------------------------------------------------
    def _backing_byte_offset(self, addr):
        if DESC_BASE <= addr < DESC_BASE + self.imgsize + 0x10000:
            return addr - DESC_BASE
        return None

    def _ensure_page(self, addr):
        base = addr & ~(PAGE - 1)
        if base in self.mapped_pages:
            return True
        try:
            self.mu.mem_map(base, PAGE)
        except UcError:
            self.mapped_pages.add(base)
            return True
        self.mapped_pages.add(base)
        fo = self._backing_byte_offset(base)
        if fo is not None and 0 <= fo < self.imgsize:
            n = min(PAGE, self.imgsize - fo)
            self.mu.mem_write(base, self.mm[fo:fo + n])
        return True

    def _ensure_range(self, addr, length):
        """Page-in everything a host-side mem_read/write will touch (the
        unmapped hook only fires for CPU accesses, not host-side ones)."""
        if length <= 0:
            return
        a = addr & ~(PAGE - 1)
        end = addr + length
        while a < end:
            self._ensure_page(a)
            a += PAGE

    def _hooks(self):
        mu = self.mu

        # Boot + params use a single global code hook (fires per instruction,
        # dispatching by address).  It's simple and proven; the ~1-2 min params
        # derivation runs once.  Decode/encode then switch to narrow,
        # address-filtered hooks (see _switch_to_narrow_hooks) so the codec body
        # runs at full JIT speed instead of paying a Python callback on every
        # one of its ~13k instructions per block (~100x faster decode).
        def code(mu, addr, size, ud):
            if addr in self.imports:
                self._imp(addr)
                return
            h = self.PLT.get(addr)
            if h:
                h(self)
                return
            fn = self.extra.get(addr)
            if fn:
                fn(self)
        self._global_hook = mu.hook_add(UC_HOOK_CODE, code)
        self._narrow = False
        self._extra_handles = {}

        def inv(mu, t, addr, sz, val, u):
            self.ondemand += 1
            if len(self.faults) < 200:
                self.faults.append((t, hex(addr), hex(mu.reg_read(UC_ARM_REG_PC))))
            try:
                self._ensure_page(addr)
                return True
            except Exception:
                return False
        mu.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED
                    | UC_HOOK_MEM_FETCH_UNMAPPED, inv)

    # ---- narrow (address-filtered) hooks for the hot decode/encode path -----
    def _on_import(self, mu, addr, size, ud):
        if addr in self.imports:
            self._imp(addr)

    def _on_plt(self, mu, addr, size, ud):
        h = self.PLT.get(addr)
        if h:
            h(self)

    def _on_extra(self, mu, addr, size, ud):
        fn = self.extra.get(addr)
        if fn:
            fn(self)

    def _switch_to_narrow_hooks(self):
        """Drop the global per-instruction code hook and replace it with hooks
        scoped to just the addresses we care about, so the codec runs natively.
        Called once, after boot/params, before the first decode."""
        if self._narrow:
            return
        mu = self.mu
        mu.hook_del(self._global_hook)
        self._global_hook = None
        # all GOT import stubs live in one contiguous sentinel block
        lo = self.IMPORT
        hi = self.IMPORT + 4 * max(1, len(self.imports)) + 4
        mu.hook_add(UC_HOOK_CODE, self._on_import, begin=lo, end=hi)
        for a in self.PLT:
            mu.hook_add(UC_HOOK_CODE, self._on_plt, begin=a, end=a)
        self._narrow = True
        # re-register any extra hooks added before the switch
        for a in list(self.extra):
            if a not in self._extra_handles:
                self._extra_handles[a] = mu.hook_add(
                    UC_HOOK_CODE, self._on_extra, begin=a, end=a)

    # ---- import stubs -------------------------------------------------------
    def _ret(self, val=0):
        self.mu.reg_write(UC_ARM_REG_R0, val & 0xffffffff)
        self.mu.reg_write(UC_ARM_REG_PC, self.mu.reg_read(UC_ARM_REG_LR))

    def _imp(self, sent):
        mu = self.mu; nm = self.imports[sent]; r0 = mu.reg_read(UC_ARM_REG_R0)
        if nm in ("malloc", "calloc", "_Znwj", "operator new(unsigned int)",
                  "operator new[](unsigned int)", "_Znaj"):
            n = r0 if nm != "calloc" else r0 * mu.reg_read(UC_ARM_REG_R1)
            self._ret(self.alloc(max(16, n)))
            return
        if nm in ("free", "_ZdlPv", "operator delete(void*)", "_ZdaPv",
                  "operator delete[](void*)"):
            self._ret(0); return
        if nm in ("memcpy", "memmove"):
            d = r0; s = mu.reg_read(UC_ARM_REG_R1); n = mu.reg_read(UC_ARM_REG_R2)
            self._ensure_range(s, n); self._ensure_range(d, n)
            try:
                mu.mem_write(d, bytes(mu.mem_read(s, n)))
            except UcError as ex:
                self.log.append(("memcpy_fail", hex(d), hex(s), n, str(ex)))
            self._ret(d); return
        if nm == "memset":
            d = r0; v = mu.reg_read(UC_ARM_REG_R1) & 0xff; n = mu.reg_read(UC_ARM_REG_R2)
            n = min(n, 0x800000)
            self._ensure_range(d, n)
            try:
                mu.mem_write(d, bytes([v]) * n)
            except UcError:
                pass
            self._ret(d); return
        if nm == "strlen":
            self._ensure_range(r0, 256)
            try:
                b = bytes(mu.mem_read(r0, 256))
                self._ret(b.index(0) if 0 in b else 256)
            except UcError:
                self._ret(0)
            return
        if nm in ("mlock", "munlock"):
            self._ret(0); return
        if nm in ("open", "open64", "openat"):
            self._open(); return
        if nm in ("__fxstat", "__xstat", "fstat", "stat"):
            self._fstat(); return
        if nm in ("mmap", "mmap64"):
            self._mmap(); return
        if nm in ("munmap", "close", "read", "pread", "lseek", "lseek64"):
            self._ret(0); return
        if nm.startswith("std::_Rb_tree_insert_and_rebalance"):
            self._rbinsert_regs(); return
        self._ret(0)

    def _read_cstr(self, va, maxn=96):
        self._ensure_range(va, maxn)
        try:
            b = bytes(self.mu.mem_read(va, maxn))
            return b.split(b"\x00")[0].decode("latin1")
        except Exception:
            return "?"

    def _open(self):
        fn = self._read_cstr(self.mu.reg_read(UC_ARM_REG_R0))
        fd = self.nextfd; self.nextfd += 1
        self.fds[fd] = fn
        self._ret(fd)

    def _fstat(self):
        mu = self.mu; fd = mu.reg_read(UC_ARM_REG_R1); sb = mu.reg_read(UC_ARM_REG_R2)
        # cat-0 only needs image.bin; any fd reports the image size (offset
        # identity makes that the correct backing for every served file).
        try:
            mu.mem_write(sb, b"\x00" * 0x60)
            mu.mem_write(sb + 0x2c, struct.pack("<Q", self.imgsize))
        except UcError:
            pass
        self._ret(0)

    def _mmap(self):
        mu = self.mu
        sp = mu.reg_read(UC_ARM_REG_SP)
        off = struct.unpack("<I", bytes(mu.mem_read(sp + 4, 4)))[0]
        self._ret(DESC_BASE + off)   # offset identity: base + rel == image[off+rel]

    def _sprintf(self):
        mu = self.mu
        buf = mu.reg_read(UC_ARM_REG_R0)
        fmt = self._read_cstr(mu.reg_read(UC_ARM_REG_R1))
        arg = mu.reg_read(UC_ARM_REG_R2)
        try:
            s = (fmt % arg).encode() + b"\x00"
        except Exception:
            s = fmt.encode() + b"\x00"
        try:
            mu.mem_write(buf, s)
        except UcError:
            pass
        self._ret(len(s) - 1)

    def _opnew(self):
        self._ret(self.alloc(max(16, self.mu.reg_read(UC_ARM_REG_R0))))

    def _rbinsert_regs(self):
        mu = self.mu
        il = mu.reg_read(UC_ARM_REG_R0); x = mu.reg_read(UC_ARM_REG_R1)
        p = mu.reg_read(UC_ARM_REG_R2); h = mu.reg_read(UC_ARM_REG_R3)
        try:
            RB.insert_and_rebalance(mu, il & 1, x, p, h)
        except Exception as e:
            self.log.append(("rbinsert_err", str(e)))
        mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))

    # PLT stub address -> handler (this firmware build).
    PLT = {
        0x15744: lambda s: s._open(),
        0x14a78: lambda s: s._fstat(),
        0x15a74: lambda s: s._mmap(),
        0x155d0: lambda s: s._ret(0),     # close
        0x15dc8: lambda s: s._ret(0),     # munmap
        0x1b420: lambda s: s._sprintf(),
        0x1632c: lambda s: s._rbinsert_regs(),
        0x156b4: lambda s: s._opnew(),
    }

    def alloc(self, n):
        p = self.heap
        self.heap = p + _algn(max(16, n), 16) + 64
        return p

    def add_hook(self, addr, fn):
        self.extra[addr] = fn
        if self._narrow and addr not in self._extra_handles:
            self._extra_handles[addr] = self.mu.hook_add(
                UC_HOOK_CODE, self._on_extra, begin=addr, end=addr)

    def del_hook(self, addr):
        self.extra.pop(addr, None)
        hh = self._extra_handles.pop(addr, None)
        if hh is not None:
            self.mu.hook_del(hh)

    # ---- boot ---------------------------------------------------------------
    def _build_keystream(self):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, self.STK + self.STKSZ - 0x20000)
        mu.reg_write(UC_ARM_REG_LR, 0xdeadbeef)
        try:
            mu.emu_start(BOOT_LO, BOOT_HI, count=50_000_000)
        except UcError as e:
            self.log.append(("keystream_err", str(e)))
        vf2 = bytes(mu.mem_read(VF2_VA, 0x4000))
        rt = _u32(bytes(mu.mem_read(REG_BASE + 0xac4, 4)))
        return any(vf2) and rt != 0

    def _init_rbtree(self):
        mu = self.mu; hdr = RBTREE_HDR
        mu.mem_write(hdr + 0,    struct.pack("<I", 0))      # color red
        mu.mem_write(hdr + 4,    struct.pack("<I", 0))      # root null
        mu.mem_write(hdr + 8,    struct.pack("<I", hdr))    # left = &header
        mu.mem_write(hdr + 0xc,  struct.pack("<I", hdr))    # right = &header
        mu.mem_write(hdr + 0x10, struct.pack("<I", 0))      # node_count
        mu.mem_write(RBTREE_ACC, b"\x00" * 8)

    def call(self, fn, args=(), limit=200_000_000):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, self.STK + self.STKSZ - 0x40000)
        for i, a in enumerate(args):
            mu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                          UC_ARM_REG_R3][i], a)
        mu.reg_write(UC_ARM_REG_LR, 0xdeadbeef)
        try:
            mu.emu_start(fn, 0xdeadbeef, count=limit)
            return ("ok", mu.reg_read(UC_ARM_REG_R0))
        except UcError as e:
            return ("err", (str(e), hex(mu.reg_read(UC_ARM_REG_PC)), self.faults[-6:]))

    def boot(self):
        """Build the keystream + rt tables, init the registry, register cat 0."""
        if not self._build_keystream():
            raise RuntimeError("Spike 2 boot: keystream/rt build failed")
        self._init_rbtree()
        st = self.call(CAT0_REGISTER, (0,), limit=5_000_000)
        if st[0] != "ok":
            raise RuntimeError("Spike 2 boot: cat-0 register failed: %r" % (st,))
        return self

    def qmul(self, chan):
        v = VOL[chan]
        return _u16(bytes(self.mu.mem_read(QMUL_TABLE + 2 * v, 2)))

    # ---- params derivation (chain) -----------------------------------------
    def derive_params(self):
        """Cold-derive the decode-params table for every cat-0 sound, straight
        from ``game_real`` + ``image.bin``.  Returns a list of dicts:
        ``{idx, body_off, length, pred16, seed_a, band0_keyoff_rel, stride,
        chan, scale}``.  ~1 minute for ~2000 sounds.
        """
        mu = self.mu
        cap = {"mddst": None, "nrec": None, "state": None}

        def at_md(eng):
            if cap["mddst"] is None:
                cap["mddst"] = eng.mu.reg_read(UC_ARM_REG_R0)
                cap["nrec"] = eng.mu.reg_read(UC_ARM_REG_R5)

        def at_bb(eng):
            if cap["state"] is None:
                m = eng.mu; sp = m.reg_read(UC_ARM_REG_SP)
                cap["state"] = dict(
                    regs=[m.reg_read(r) for r in _R] + [sp, m.reg_read(UC_ARM_REG_LR)],
                    sp=sp, frame=bytes(m.mem_read(sp, 0x2a0)))
                m.emu_stop()

        self.extra[MASTERDIR_MALLOC] = at_md
        self.extra[BANDLOOP] = at_bb
        self.call(MASTERDIR_DECODE, (0,), limit=120_000_000)
        self.extra.pop(MASTERDIR_MALLOC, None)
        self.extra.pop(BANDLOOP, None)
        if cap["state"] is None or cap["mddst"] is None or not cap["nrec"]:
            raise RuntimeError("Spike 2 params: registration did not reach "
                               "band-build (cap=%r)" % ({k: v for k, v in cap.items()
                                                         if k != "state"},))
        nrec = cap["nrec"]
        self._ensure_range(cap["mddst"], nrec * 24)
        md = bytes(mu.mem_read(cap["mddst"], nrec * 24))

        # chain forward from states[0]: stub a few helpers and cap bulk copies
        # so each per-record band-build runs cheaply.
        def _stub(eng):
            eng.mu.reg_write(UC_ARM_REG_R0, 0)
            eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))
        for a in CHAIN_STUBS:
            self.extra[a] = _stub
        _orig_imp = self._imp

        def _capped(sent):
            nm = self.imports.get(sent)
            if nm in ("memcpy", "memmove", "memset"):
                n = self.mu.reg_read(UC_ARM_REG_R2)
                if n > 0x40000:
                    self.mu.reg_write(UC_ARM_REG_R2, 0x40000)
            return _orig_imp(sent)
        self._imp = _capped

        rows = []
        cur = dict(regs=list(cap["state"]["regs"]), sp=cap["state"]["sp"],
                   frame=cap["state"]["frame"])
        try:
            for idx in range(nrec):
                rec = md[idx * 24: idx * 24 + 24]
                dw0 = _u32(rec, 0)
                length = (LENGTH_XOR ^ _u32(rec, 16)) & 0xffffffff
                obj, nxt = self._drive_step(cur, rec)
                if obj is None:
                    break
                rows.append(dict(
                    idx=idx, body_off=dw0, length=length,
                    pred16=_u16(obj, 0x18), seed_a=_u32(obj, 0x14),
                    band0_keyoff_rel=(_u32(obj, 0x0c) - VF2_VA) & 0xffffffff,
                    stride=obj[0x1a], chan=obj[0x1b], scale=obj[0x1d]))
                if nxt is None:
                    break
                cur = dict(regs=nxt[0], sp=nxt[1], frame=nxt[2])
        finally:
            self._imp = _orig_imp
            for a in CHAIN_STUBS:
                self.extra.pop(a, None)
        return rows

    def _drive_step(self, cur, record_bytes, limit=4_000_000):
        mu = self.mu
        sp = cur["sp"]
        self._ensure_range(sp, 0x2a0)
        mu.mem_write(sp, cur["frame"])
        for i, r in enumerate(_R):
            mu.reg_write(r, cur["regs"][i])
        mu.reg_write(UC_ARM_REG_SP, sp)
        mu.reg_write(UC_ARM_REG_LR, cur["regs"][14])
        r9 = cur["regs"][9]
        self._ensure_range(r9 - 8, 24)
        mu.mem_write(r9 - 8, record_bytes)
        cap = {"obj": None, "next": None, "hits": 0}

        def at_bl(eng):
            cap["hits"] += 1
            if cap["hits"] >= 2:
                m = eng.mu; nsp = m.reg_read(UC_ARM_REG_SP)
                cap["next"] = (
                    [m.reg_read(r) for r in _R] + [nsp, m.reg_read(UC_ARM_REG_LR)],
                    nsp, bytes(m.mem_read(nsp, 0x2a0)))
                m.emu_stop()

        def at_bd(eng):
            m = eng.mu; r7 = m.reg_read(UC_ARM_REG_R7)
            try:
                cap["obj"] = bytes(m.mem_read(r7, 0x80))
            except UcError:
                pass

        self.extra[BANDLOOP] = at_bl
        self.extra[BANDOBJ] = at_bd
        try:
            mu.emu_start(BANDLOOP, 0, count=limit)
        except UcError:
            pass
        self.extra.pop(BANDLOOP, None)
        self.extra.pop(BANDOBJ, None)
        return cap["obj"], cap["next"]

    # ---- decode -------------------------------------------------------------
    def setup_decode(self):
        if self._decode_ready:
            return
        mu = self.mu
        self._switch_to_narrow_hooks()   # codec runs at full JIT speed now
        try:
            mu.reg_write(UC_ARM_REG_C1_C0_2,
                         mu.reg_read(UC_ARM_REG_C1_C0_2) | (0xf << 20))
            mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        except Exception:
            pass
        self.ACC = self.alloc(0x8000)
        # map the obj + voice page(s)
        base = self.OBJ_VA & ~0xfff
        mu.mem_map(base, _algn(self.VOICE_VA + 0x80) - base)
        self.add_hook(PROV, self._at_prov)
        self._decode_ready = True

    def _at_prov(self, eng):
        m = self.mu
        rr0 = m.reg_read(UC_ARM_REG_R0)
        r2 = m.reg_read(UC_ARM_REG_R2)
        m.mem_write(rr0, struct.pack("<III", r2,
                                     (self.BB + self.st["R"]) & 0xffffffff,
                                     self.st["k"]))
        m.reg_write(UC_ARM_REG_PC, m.reg_read(UC_ARM_REG_LR))

    def _ensure_body(self, span):
        if span > self.BBSZ:
            try:
                self.mu.mem_map(self.BB + self.BBSZ, _algn(span) - self.BBSZ)
            except UcError:
                pass
            self.BBSZ = _algn(span)

    def _build_obj(self, p):
        obj = bytearray(0x80)
        struct.pack_into("<I", obj, 0x00, p["body_off"])
        struct.pack_into("<I", obj, 0x0c, (VF2_VA + p["band0_keyoff_rel"]) & 0xffffffff)
        struct.pack_into("<I", obj, 0x10, p["length"] & 0xffffffff)
        struct.pack_into("<I", obj, 0x14, p["seed_a"] & 0xffffffff)
        struct.pack_into("<I", obj, 0x18,
                         (p["pred16"] | (p["stride"] << 16) | (p["chan"] << 24)) & 0xffffffff)
        obj[0x1c] = 0x01
        obj[0x1d] = p["scale"]
        return bytes(obj)

    def _voice(self, chan):
        v = bytearray(0x40)
        struct.pack_into("<I", v, 0x00, self.OBJ_VA)   # obj pointer
        struct.pack_into("<I", v, 0x30, VOL[chan])     # volume
        return bytes(v)

    def codec_fns(self, scale, chan):
        """Return ``(render_fn, decode_fn)`` for a sound's scale/chan from the
        firmware dispatch table."""
        mu = self.mu
        sub = 0 if chan == 2 else 1
        render = _u32(bytes(mu.mem_read(DISPATCH + scale * 0x40 + sub * 4, 4)))
        decode = _u32(bytes(mu.mem_read(DISPATCH + 0x20 + scale * 0x40 + sub * 4, 4)))
        return render, decode

    def decode(self, p, max_secs=None, cancel=None):
        """Decode one sound to ``(L, R, stereo)`` int64 arrays (R == L for mono
        consumers only use L).  Returns None if cancelled mid-decode."""
        import numpy as np
        self.setup_decode()
        mu = self.mu
        chan = p["chan"]; stereo = (chan == 2); length = p["length"]
        Rmul, Roff = (4, 800) if stereo else (2, 400)
        render_fn, decode_fn = self.codec_fns(p["scale"], chan)
        entry = render_fn if stereo else decode_fn
        OBJ = self._build_obj(p)
        VOICE = self._voice(chan)
        vol = VOL[chan]
        bo = p["body_off"]; bodysz = Rmul * length
        span = _algn(min(bodysz + 0x4000, 0x10000000))
        self._ensure_body(span)
        mu.mem_write(self.BB, self.mm[bo:bo + span])
        r1 = self.ACC + 0x80
        nmax = length if max_secs is None else min(int(44100 * max_secs), length)
        Ls = []; Rs = []; cur = 200
        while cur < nmax and (Rmul * cur - Roff) < span - 0x2000:
            if cancel is not None and cancel():
                return None
            mu.mem_write(self.OBJ_VA, OBJ)
            mu.mem_write(self.VOICE_VA, VOICE)
            R = max(0, Rmul * cur - Roff)
            self.st["R"] = R; self.st["k"] = R
            mu.mem_write(self.VOICE_VA + 0xc, struct.pack("<I", cur))
            mu.mem_write(self.ACC, b"\x00" * 0x8000)
            mu.reg_write(UC_ARM_REG_R0, self.VOICE_VA)
            mu.reg_write(UC_ARM_REG_R1, r1)
            mu.reg_write(UC_ARM_REG_R2, vol)
            mu.reg_write(UC_ARM_REG_SP, self.STK + self.STKSZ - 0x80000)
            mu.reg_write(UC_ARM_REG_LR, self.LAND)
            try:
                mu.emu_start(entry, self.LAND, count=20_000_000)
            except UcError:
                break
            o = np.frombuffer(bytes(mu.mem_read(r1 - 0x10, 204 * 8)),
                              dtype="<i4").astype(np.int64)
            Ls.append(o[0::2][2:202])
            Rs.append(o[1::2][2:202])
            cur += 200
        if not Ls:
            return None
        return np.concatenate(Ls), np.concatenate(Rs), stereo

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass
        try:
            self._imgf.close()
        except Exception:
            pass
