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
# r0..r15 (sp=13, lr=14, pc=15) for decoding LDREX/STREX register fields.
_R16 = _R + [UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC]

# LDREX/STREX family (ARM A1, cond=0xE) -> (is_store, byte-width).  unicorn's
# bare ARM core has no exclusive monitor, so these raise; in a single-threaded
# emulation they are correct as plain load / store-returns-success.
_ATOMIC = {0x01900090: (False, 4), 0x01d00090: (False, 1), 0x01f00090: (False, 2),
           0x01b00090: (False, 8), 0x01800090: (True, 4), 0x01c00090: (True, 1),
           0x01e00090: (True, 2), 0x01a00090: (True, 8)}

def _atomic_kind(w):
    return _ATOMIC.get(w & 0x0FF000F0) if (w >> 28) == 0xE else None

PAGE = 0x1000


def _algn(x, a=PAGE):
    return (x + a - 1) & ~(a - 1)


def _u16(b, o=0):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


def _next_prime(n):
    """Smallest prime >= n (libstdc++ _M_next_bkt semantics; n capped sanely)."""
    n = max(2, int(n) & 0xffffffff)
    if n > 1 << 24:            # absurd request -> a fixed large prime
        return 16777259
    if n <= 2:
        return 2
    n |= 1                     # primes > 2 are odd
    while True:
        if all(n % d for d in range(3, int(n ** 0.5) + 1, 2)):
            return n
        n += 2


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
RET_SENTINEL = 0xdeadbee0  # even ``call()`` return trap (interwork-safe; see call())

# The codec emits in 200-sample blocks driven from a cursor that starts at 200,
# and within the block at cursor C it emits sample i only while ``C + i < length``
# (measured register-level on mono+stereo, validated + generic builds).  So a
# sound's true decoded output is exactly ``length - BLOCK`` samples — the first
# block is a cursor lead-in — and any block past that emits nothing (the decode
# scratch stays zero).  Decoding/encoding the full ``length`` would tack on (or
# silently drop) up to ~200 trailing zero samples, which is inaudible on a
# one-shot SFX but clicks at the loop point of looping music.
BLOCK = 200


def emitted_length(length):
    """True decoded sample count for a sound of header ``length`` (see BLOCK)."""
    return max(0, int(length) - BLOCK)

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


def _build_supported_raw(raw):
    try:
        segs, _ = parse_elf(raw)
    except Exception:
        return False

    def _at(va, n):
        for vaddr, off, filesz, _memsz in segs:
            if vaddr <= va < vaddr + filesz:
                return raw[off + (va - vaddr): off + (va - vaddr) + n]
        return b""

    return all(_at(va, len(sig)) == sig for va, sig in _BUILD_SIG.items())


def firmware_build_supported(game_real_path):
    """True if the card's ``game`` firmware is the validated (TMNT 1.58) build
    the codec oracle's hardcoded addresses were mapped from.  Cheap: parses the
    ELF program headers and compares a few prologue bytes; never boots."""
    try:
        raw = open(game_real_path, "rb").read()
    except Exception:
        return False
    return _build_supported_raw(raw)


def audio_decode_supported(game_real_path):
    """True if this firmware's audio can be decoded: either the validated build
    (above) or a *different* single-path build whose codec addresses locate
    generically (see :mod:`.locate`).  Dual-path codecs (no resolvable
    ``PROV``/``QMUL``) return False, so the engine skips audio gracefully."""
    try:
        raw = open(game_real_path, "rb").read()
    except Exception:
        return False
    if _build_supported_raw(raw):
        return True
    from . import locate
    return locate.locate_all(raw=raw) is not None


class Spike2Emu:
    # memory layout (no region overlaps; see module docstring)
    STK = 0x20000000; STKSZ = 0x00400000
    HEAP = 0x30000000; HEAPSZ = 0x20000000          # 0x30000000..0x50000000
    IMPORT = 0x60000000
    LAND = 0x10000000                               # decode return sentinel
    OBJ_VA = 0x18000000; VOICE_VA = 0x18001000      # codec obj + voice
    ACC_VA = 0x19000000                             # decode scratch (fixed; see setup_decode)
    BB = 0x50000000                                 # body buffer (grown lazily)

    def __init__(self, game_real_path, image_path):
        raw = open(game_real_path, "rb").read()
        segs, relocs = parse_elf(raw)
        self._segs = segs   # (vaddr, off, filesz, memsz) — for fn-ptr validation
        # Firmware addresses: the validated (TMNT) build uses the hardcoded
        # module constants; any other build's codec lives elsewhere, so locate
        # every address generically (see :mod:`.locate`).  ``audio_supported``
        # is False for dual-path / unlocatable builds (engine skips audio).
        self._generic = not _build_supported_raw(raw)
        if self._generic:
            from . import locate
            addrs = locate.locate_all(raw=raw)
            self.audio_supported = addrs is not None
        else:
            addrs = None
            self.audio_supported = True
        self._set_addrs(addrs)
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu = mu
        self._atomic_pcs = set()
        for vaddr, off, filesz, memsz in segs:
            b = vaddr & ~0xfff
            e = _algn(vaddr + memsz)
            mu.mem_map(b, e - b)
            mu.mem_write(vaddr, raw[off:off + filesz])
            # index every LDREX/STREX so the global hook can emulate them inline
            # (the firmware's C++ runtime uses atomics heavily; unicorn has no
            # exclusive monitor, so without this they raise and abort the boot).
            for i in range(0, filesz & ~3, 4):
                if _atomic_kind(_u32(raw, off + i)):
                    self._atomic_pcs.add(vaddr + i)
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
        # Optional per-instruction watchdog (set only during params derivation).
        # The global code hook calls it each instruction so a mis-located build
        # can bail early instead of burning the whole instruction cap.
        self._watchdog = None
        self._hooks()

        # decode scratch (set up lazily by setup_decode)
        self.BBSZ = 0
        self.ACC = None
        self._decode_ready = False
        self._mapped = set()
        self.st = {"R": 0, "k": 0}
        self._slot_cache = {}   # (scale, chan) -> resolved codec entry (generic)

    def _set_addrs(self, addrs):
        """Bind every firmware address as an instance attribute.  Defaults are
        the validated (TMNT) module constants; ``addrs`` (from :mod:`.locate`)
        overrides them for any other build.  ``OBJREG`` is the band-build's
        codec-obj pointer register (TMNT r7); ``FIND_BL`` is the band-template
        lookup ``bl`` skipped on generic builds (None on the validated build,
        whose real lookup already works)."""
        self.BOOT_LO = BOOT_LO; self.BOOT_HI = BOOT_HI
        self.VF2_VA = VF2_VA; self.REG_BASE = REG_BASE
        self.PROV = PROV; self.DISPATCH = DISPATCH; self.QMUL_TABLE = QMUL_TABLE
        self.CAT0_REGISTER = CAT0_REGISTER
        self.RBTREE_HDR = RBTREE_HDR; self.RBTREE_ACC = RBTREE_ACC
        self.MASTERDIR_DECODE = MASTERDIR_DECODE
        self.MASTERDIR_MALLOC = MASTERDIR_MALLOC
        self.BANDLOOP = BANDLOOP; self.BANDOBJ = BANDOBJ
        self.CHAIN_STUBS = CHAIN_STUBS; self.LENGTH_XOR = LENGTH_XOR
        self.OBJREG = 7
        self.FIND_BL = None
        if addrs:
            for k in ("BOOT_LO", "BOOT_HI", "VF2_VA", "REG_BASE", "PROV",
                      "DISPATCH", "QMUL_TABLE", "CAT0_REGISTER", "RBTREE_HDR",
                      "RBTREE_ACC", "MASTERDIR_DECODE", "MASTERDIR_MALLOC",
                      "BANDLOOP", "BANDOBJ", "FIND_BL"):
                setattr(self, k, addrs[k])
            self.OBJREG = addrs["OBJREG"]
            # generic derive skips the template lookup (find-skip) instead of
            # stubbing the chain helpers, and takes the length from the raw obj.
            self.CHAIN_STUBS = ()
            self.LENGTH_XOR = 0

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
            w = self._watchdog
            if w is not None:
                w()
            if addr in self._atomic_pcs:
                self._emu_atomic(addr)
                return
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
    def _emu_atomic(self, addr):
        """Emulate the LDREX*/STREX* at *addr* as a plain load / store-success,
        then step past it (correct for single-threaded emulation)."""
        mu = self.mu
        w = _u32(bytes(mu.mem_read(addr, 4)))
        k = _atomic_kind(w)
        if k is not None:
            is_store, width = k
            base = mu.reg_read(_R16[(w >> 16) & 0xf])
            try:
                if not is_store:
                    rt = (w >> 12) & 0xf
                    d = bytes(mu.mem_read(base, width))
                    if width == 8:
                        lo, hi = struct.unpack("<II", d)
                        mu.reg_write(_R16[rt], lo); mu.reg_write(_R16[rt + 1], hi)
                    else:
                        mu.reg_write(_R16[rt], int.from_bytes(d, "little"))
                else:
                    rd = (w >> 12) & 0xf; rt = w & 0xf
                    if width == 8:
                        mu.mem_write(base, struct.pack(
                            "<II", mu.reg_read(_R16[rt]) & 0xffffffff,
                            mu.reg_read(_R16[rt + 1]) & 0xffffffff))
                    else:
                        mu.mem_write(base, (mu.reg_read(_R16[rt])
                                            & ((1 << (8 * width)) - 1)).to_bytes(width, "little"))
                    mu.reg_write(_R16[rd], 0)
            except UcError:
                pass
        mu.reg_write(UC_ARM_REG_PC, addr + 4)

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
        if nm in ("__fxstat", "__xstat", "fstat", "stat",
                  "__fxstat64", "__xstat64", "fstat64", "stat64"):
            # 64-bit variants matter for the per-category banks (the loader reads
            # the fstat size for the mmap length); cat-0 is offset-identity and
            # doesn't depend on it, but routing them is harmless there.
            self._fstat(); return
        if nm in ("mmap", "mmap64"):
            self._mmap(); return
        if nm in ("munmap", "close", "read", "pread", "lseek", "lseek64"):
            self._ret(0); return
        # ``.dynsym`` names are mangled (``_ZSt29_Rb_tree_insert_and_rebalance``);
        # accept the demangled spelling too.  (On TMNT the hardcoded PLT stub
        # masked this; other builds reach it only by name via the GOT path.)
        if (nm.startswith("_ZSt29_Rb_tree_insert_and_rebalance")
                or nm.startswith("std::_Rb_tree_insert_and_rebalance")):
            self._rbinsert_regs(); return
        # std::_Rb_tree_increment / _decrement (in-order successor / predecessor)
        # -- both overloads (P... and PK... = const) mangle with this prefix.
        # Needed by builds that iterate a non-empty registry map during the
        # master-directory decode (Led Zeppelin LE 1.22.0); the old ret-0 stub
        # made that iteration loop forever off node 0.
        if (nm.startswith("_ZSt18_Rb_tree_increment")
                or nm.startswith("std::_Rb_tree_increment")):
            self._ret(RB.increment(mu, r0)); return
        if (nm.startswith("_ZSt18_Rb_tree_decrement")
                or nm.startswith("std::_Rb_tree_decrement")):
            self._ret(RB.decrement(mu, r0)); return
        # std::__detail::_Prime_rehash_policy::_M_next_bkt(unsigned n) const
        # returns the next prime >= n for a std::unordered_map's bucket count.
        # Returning 0 (the default stub) leaves bucket_count==0, so a later
        # bucket = hash % bucket_count divides by zero and the firmware's
        # band-template lookup throws.  Return a real prime so the map works.
        if nm.startswith("_ZNKSt8__detail20_Prime_rehash_policy11_M_next_bkt"):
            self._ret(_next_prime(mu.reg_read(UC_ARM_REG_R1))); return
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

    @property
    def fast_reg_read(self):
        """``(uc_reg_read C function, uc handle)`` for reading a register
        straight through unicorn's C API from inside a hot hook, or ``None`` if
        this unicorn build doesn't expose them.

        The keystream-recovery capture fires a code hook once per output sample
        (hundreds of thousands of times for a long song) and reads one register
        each time; the normal ``mu.reg_read`` Python wrapper re-selects the
        register class and allocates a fresh ctypes object every call, which
        profiling showed to be ~30% of the whole re-encode.  Bypassing it (the
        caller reuses one buffer + this bound C function) is a pure speedup with
        a safe fallback: if the private attributes ever move, this returns
        ``None`` and the caller keeps using ``mu.reg_read``."""
        cached = getattr(self, "_fast_reg_cache", False)
        if cached is False:
            try:
                from unicorn.unicorn_py3.unicorn import uclib
                cached = (uclib.uc_reg_read, self.mu._uch)
            except Exception:
                cached = None
            self._fast_reg_cache = cached
        return cached

    # ---- boot ---------------------------------------------------------------
    def _build_keystream(self):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, self.STK + self.STKSZ - 0x20000)
        mu.reg_write(UC_ARM_REG_LR, 0xdeadbeef)
        try:
            mu.emu_start(self.BOOT_LO, self.BOOT_HI, count=50_000_000)
        except UcError as e:
            self.log.append(("keystream_err", str(e)))
        vf2 = bytes(mu.mem_read(self.VF2_VA, 0x4000))
        if self._generic:
            # The rt-table pointer at REG_BASE+0xac4 is populated only on the
            # validated build; other builds keep the codec's runtime tables
            # elsewhere (e.g. Godzilla leaves +0xac4 == 0 yet decodes fine), so
            # the keystream being built is the only universal success signal.
            return any(vf2)
        rt = _u32(bytes(mu.mem_read(self.REG_BASE + 0xac4, 4)))
        return any(vf2) and rt != 0

    def _init_rbtree(self):
        mu = self.mu; hdr = self.RBTREE_HDR
        mu.mem_write(hdr + 0,    struct.pack("<I", 0))      # color red
        mu.mem_write(hdr + 4,    struct.pack("<I", 0))      # root null
        mu.mem_write(hdr + 8,    struct.pack("<I", hdr))    # left = &header
        mu.mem_write(hdr + 0xc,  struct.pack("<I", hdr))    # right = &header
        mu.mem_write(hdr + 0x10, struct.pack("<I", 0))      # node_count
        mu.mem_write(self.RBTREE_ACC, b"\x00" * 8)

    def call(self, fn, args=(), limit=200_000_000):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, self.STK + self.STKSZ - 0x40000)
        for i, a in enumerate(args):
            mu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                          UC_ARM_REG_R3][i], a)
        # EVEN return sentinel: a callee returning via ``bx lr`` (older builds,
        # e.g. Star Wars) interworks on bit0, so an odd sentinel would land in
        # Thumb one byte before it and the ``until`` stop never matches; an even
        # sentinel traps both ``bx lr`` and ``pop {pc}``/``mov pc, lr`` returns.
        mu.reg_write(UC_ARM_REG_LR, RET_SENTINEL)
        try:
            mu.emu_start(fn, RET_SENTINEL, count=limit)
            return ("ok", mu.reg_read(UC_ARM_REG_R0))
        except UcError as e:
            return ("err", (str(e), hex(mu.reg_read(UC_ARM_REG_PC)), self.faults[-6:]))

    def boot(self):
        """Build the keystream + rt tables, init the registry, register cat 0."""
        if not self._build_keystream():
            raise RuntimeError("Spike 2 boot: keystream/rt build failed")
        if self._generic:
            # A nonzero unordered_map bucket count so the band-template lookup's
            # ``hash % bucket_count`` (run before the find we skip) can't divide
            # by zero.  Re-asserted in derive_params (boot may zero this bss).
            try:
                self.mu.mem_write(self.REG_BASE + 0xad8, struct.pack("<I", 11))
            except UcError:
                pass
        self._init_rbtree()
        st = self.call(self.CAT0_REGISTER, (0,), limit=5_000_000)
        if st[0] != "ok":
            raise RuntimeError("Spike 2 boot: cat-0 register failed: %r" % (st,))
        return self

    def qmul(self, chan):
        v = VOL[chan]
        return _u16(bytes(self.mu.mem_read(self.QMUL_TABLE + 2 * v, 2)))

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
                eng._watchdog = None      # located OK -> stop the fail-fast count

        def at_bb(eng):
            if cap["state"] is None:
                m = eng.mu; sp = m.reg_read(UC_ARM_REG_SP)
                cap["state"] = dict(
                    regs=[m.reg_read(r) for r in _R] + [sp, m.reg_read(UC_ARM_REG_LR)],
                    sp=sp, frame=bytes(m.mem_read(sp, 0x2a0)))
                m.emu_stop()

        if self._generic:
            # find-skip scratch + nonzero bucket count (see boot()/_drive_step).
            self._blank_buf = self.alloc(0x100)
            self._blank_node = self.alloc(0x10)
            mu.mem_write(self._blank_buf, b"\x00" * 0x100)
            mu.mem_write(self._blank_node, struct.pack("<I", self._blank_buf))
            try:
                mu.mem_write(self.REG_BASE + 0xad8, struct.pack("<I", 11))
            except UcError:
                pass

        self.extra[self.MASTERDIR_MALLOC] = at_md
        self.extra[self.BANDLOOP] = at_bb
        # Generous cap: at_bb emu_stops the instant BANDLOOP is reached, so this
        # only bounds the master-directory decode.  Big catalogs (e.g. D&D's
        # ~10.5k sounds across image-scNN segments) need more than the ~120M a
        # ~2k-sound card uses.
        #
        # Fail-fast watchdog: the record-array malloc (MASTERDIR_MALLOC, caught
        # by at_md) sits at the very top of the decode on every mapped build, so
        # mddst is set within the first instructions regardless of catalog size.
        # If a newer/unrecognised build's addresses locate to the wrong PCs the
        # hook never fires, and without this the emulation would burn the whole
        # 600M-instruction cap (~19 min on real HW) before failing.  at_md clears
        # the watchdog the moment it fires, so a good build pays ~nothing; a bad
        # one bails after a wide margin (~1-2 min) with the error below.
        wd = {"n": 0}

        def _wd():
            wd["n"] += 1
            if wd["n"] >= 40_000_000 and cap["mddst"] is None:
                mu.emu_stop()
        self._watchdog = _wd
        try:
            self.call(self.MASTERDIR_DECODE, (0,), limit=600_000_000)
        finally:
            self._watchdog = None
            self.extra.pop(self.MASTERDIR_MALLOC, None)
            self.extra.pop(self.BANDLOOP, None)
        if cap["state"] is None or cap["mddst"] is None or not cap["nrec"]:
            raise RuntimeError(
                "Spike 2 params: registration did not reach band-build "
                "(cap=%r). The engine could not map this firmware build's audio "
                "codec -- most likely a newer game update than this version of "
                "the app recognises." % ({k: v for k, v in cap.items()
                                          if k != "state"},))
        nrec = cap["nrec"]
        self._ensure_range(cap["mddst"], nrec * 24)
        md = bytes(mu.mem_read(cap["mddst"], nrec * 24))

        # chain forward from states[0]: stub a few helpers and cap bulk copies
        # so each per-record band-build runs cheaply.
        def _stub(eng):
            eng.mu.reg_write(UC_ARM_REG_R0, 0)
            eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))
        for a in self.CHAIN_STUBS:
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
                length = (self.LENGTH_XOR ^ _u32(rec, 16)) & 0xffffffff
                obj, nxt = self._drive_step(cur, rec)
                if obj is None:
                    break
                row = dict(
                    idx=idx, body_off=dw0, length=length,
                    pred16=_u16(obj, 0x18), seed_a=_u32(obj, 0x14),
                    band0_keyoff_rel=(_u32(obj, 0x0c) - self.VF2_VA) & 0xffffffff,
                    stride=obj[0x1a], chan=obj[0x1b], scale=obj[0x1d])
                if self._generic:
                    # The generic decode replays the raw band-build obj verbatim
                    # (no per-build field reassembly), with body_off / length /
                    # scale / chan read straight from it (no LENGTH_XOR).
                    row["_rawobj"] = obj
                    row["body_off"] = _u32(obj, 0x00)
                    row["length"] = _u32(obj, 0x10)
                    row["scale"] = obj[0x1d]
                    row["chan"] = obj[0x1b]
                rows.append(row)
                if nxt is None:
                    break
                cur = dict(regs=nxt[0], sp=nxt[1], frame=nxt[2])
        finally:
            self._imp = _orig_imp
            for a in self.CHAIN_STUBS:
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

        objreg = _R[self.OBJREG]

        def at_bd(eng):
            m = eng.mu
            try:
                cap["obj"] = bytes(m.mem_read(m.reg_read(objreg), 0x80))
            except UcError:
                pass

        # generic builds skip the band-template std::unordered_map lookup: inject
        # a blank writable scratch node and step past the find `bl`.  The build
        # only *writes* the codec-obj fields into the node (never reads the
        # template), so a blank node is bit-exact (validated on TMNT too).
        find_skip = self._generic and self.FIND_BL is not None
        if find_skip:
            def at_find(eng):
                eng.mu.reg_write(UC_ARM_REG_R0, self._blank_node)
                eng.mu.reg_write(UC_ARM_REG_PC, self.FIND_BL + 4)
            self.extra[self.FIND_BL] = at_find
        self.extra[self.BANDLOOP] = at_bl
        self.extra[self.BANDOBJ] = at_bd
        try:
            mu.emu_start(self.BANDLOOP, 0, count=limit)
        except UcError:
            pass
        if find_skip:
            self.extra.pop(self.FIND_BL, None)
        self.extra.pop(self.BANDLOOP, None)
        self.extra.pop(self.BANDOBJ, None)
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
        # Decode scratch (accumulator) at a FIXED dedicated address, NOT from
        # the bump allocator: some large builds' boot legitimately requests a
        # huge working buffer (e.g. Led Zeppelin 1.21.0's master-directory
        # decode asks for ~800 MB) that runs the heap pointer past the HEAP
        # window.  A heap-allocated ACC would then land unmapped and the
        # host-side mem_writes below would fault -- which _slot_metrics swallows,
        # so every sound silently decodes to None ("Decoded 0/N").  A fixed
        # mapped page is position-independent and equivalent for the codec.
        self.ACC = self.ACC_VA
        self._ensure_range(self.ACC, 0x10000)
        # map the obj + voice page(s).  Page-by-page (not one bulk mem_map) so a
        # page the firmware already faulted into this region during boot/derive
        # (some builds, e.g. Metallica, touch 0x18000000 via on-demand paging)
        # doesn't make the map fail -- _ensure_page skips already-mapped pages.
        base = self.OBJ_VA & ~0xfff
        for pg in range(base, _algn(self.VOICE_VA + 0x80), PAGE):
            self._ensure_page(pg)
        self.add_hook(self.PROV, self._at_prov)
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
        # Grow the body buffer with ONE bulk mem_map.  Mapping page-by-page here
        # is O(pages^2) -- unicorn inserts each region in O(region-count), so a
        # long sound's huge body (a 12-min stereo track is ~134 MB = ~33k pages)
        # spends minutes churning in mem_map *before any block decodes*, which
        # looked like a hang stuck at 0%.  One contiguous region is O(1).
        # Fallback: if a stray page already faulted into the BB region (e.g.
        # Metallica's on-demand paging during boot) the bulk map raises on the
        # overlap, so drop back to the page-by-page path (which skips the
        # already-mapped pages individually).
        span = _algn(span)
        if span <= self.BBSZ:
            return
        addr = self.BB + self.BBSZ
        length = span - self.BBSZ
        try:
            self.mu.mem_map(addr, length)
            for pg in range(addr, addr + length, PAGE):
                self.mapped_pages.add(pg)
        except UcError:
            self._ensure_range(addr, length)
        self.BBSZ = span

    def _build_obj(self, p):
        # generic builds replay the raw band-build obj verbatim (proven correct
        # by hardware capture); the validated build reassembles it from fields.
        if self._generic:
            return p["_rawobj"]
        obj = bytearray(0x80)
        struct.pack_into("<I", obj, 0x00, p["body_off"])
        struct.pack_into("<I", obj, 0x0c, (self.VF2_VA + p["band0_keyoff_rel"]) & 0xffffffff)
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
        firmware dispatch table (render slot base, decode slot at +0x20)."""
        mu = self.mu
        sub = 0 if chan == 2 else 1
        render = _u32(bytes(mu.mem_read(self.DISPATCH + scale * 0x40 + sub * 4, 4)))
        decode = _u32(bytes(mu.mem_read(self.DISPATCH + 0x20 + scale * 0x40 + sub * 4, 4)))
        return render, decode

    def recover_entry(self, p):
        """Codec entry function that the keystream recovery / re-encode path must
        drive — identical to what :meth:`decode` runs for this sound.  On a
        generic build the audio fn sits at a build-specific dispatch sub-slot
        (the channel->slot parity flips per build), so resolve it the same way
        decode does (:meth:`_resolve_entry`, cached per scale/chan).  The
        validated build keeps the dispatch render/decode fn (bit-exact path).
        ``codec_fns`` alone is wrong here: it predates the slot-parity fix and
        returns the noise slot on flipped builds."""
        if self._generic:
            return self._resolve_entry(p)
        render_fn, decode_fn = self.codec_fns(p["scale"], p["chan"])
        return render_fn if p["chan"] == 2 else decode_fn

    def decode(self, p, max_secs=None, cancel=None, progress=None):
        """Decode one sound to ``(L, R, stereo)`` int64 arrays (mono consumers
        use only L).  Returns None if cancelled or no codec entry resolved.

        ``progress`` (if given) is called ``(cur, nmax)`` once per decoded block
        (samples-so-far / total) so a caller can surface live per-sound progress
        for the long music tracks; it's cheap, so the caller throttles."""
        if self._generic:
            entry = self._resolve_entry(p)
            if entry is None:
                return None
        else:
            render_fn, decode_fn = self.codec_fns(p["scale"], p["chan"])
            entry = render_fn if p["chan"] == 2 else decode_fn
        return self._decode_with_entry(p, entry, max_secs=max_secs, cancel=cancel,
                                       progress=progress)

    @staticmethod
    def _specflat(x):
        """Spectral flatness of a signal: ~0.8+ for white noise, <0.45 for real
        audio.  Used to pick the audio-producing codec slot on generic builds."""
        import numpy as np
        x = np.asarray(x, float)
        if len(x) < 64 or np.std(x) < 1e-6:
            return 1.0
        n = 1 << int(np.floor(np.log2(len(x))))
        X = np.abs(np.fft.rfft((x[:n] - x[:n].mean()) * np.hanning(n)))[1:]
        X = np.maximum(X, 1e-9)
        return float(np.exp(np.mean(np.log(X))) / np.mean(X))

    # Per-scale dispatch sub-slots (stride 0x40 = 16 u32 fn pointers per scale)
    # to probe for the audio codec on a generic build.  The audio fn lives in
    # one of the low slots, but WHICH one varies by build: the channel->slot
    # parity is even on some builds (TMNT/Godzilla/Led Zeppelin: mono=slot1,
    # stereo=slot0) and FLIPPED on others (Avengers/Iron Maiden: mono=slot0,
    # stereo=slot1).  Probing 0..3 in order finds the right slot on every
    # observed build (slots 0/2 and 1/3 alias the two real codecs).
    _PROBE_SLOTS = (0, 1, 2, 3)

    # The WRONG codec for a sound (a mono codec fed a stereo body, or vice
    # versa) decodes to near-white noise at roughly a third of full scale --
    # measured stable across every build at specflat ~0.85 / rms ~12.4k
    # (stereo) and ~0.66 / rms ~6.4k (mono).  Real audio tops out around
    # specflat 0.6 even when loud, and a CORRECT codec on a quiet passage is
    # flat but quiet.  So a slot that is BOTH very flat AND loud is the wrong
    # codec -- never the right one.  This lets a correct-but-quiet slot
    # (silence, rms~0) beat the wrong loud-noise slot, which a bare "lowest
    # specflat wins" cannot (silence reads flatter than noise).  That bare rule
    # on a 0.5s probe window is exactly why music tracks with a silent intro
    # used to decode to static.
    _NOISE_SF = 0.70
    _NOISE_RMS = 7000.0

    def _slot_metrics(self, p, fnv, secs):
        """``(specflat, rms)`` of decoding ``p`` with codec ``fnv`` over the
        first ``secs`` -- or None if it doesn't decode.  Stereo takes the WORSE
        channel of each, since a mono codec fed a stereo body can yield an
        audio-looking L with a garbage R."""
        import numpy as np
        try:
            res = self._decode_with_entry(p, fnv, max_secs=secs)
        except Exception:
            return None
        if res is None:
            return None
        sf = self._specflat(res[0])
        rms = float(np.sqrt(np.mean(np.asarray(res[0], float) ** 2)))
        if p["chan"] == 2:
            sf = max(sf, self._specflat(res[1]))
            rms = max(rms, float(np.sqrt(np.mean(np.asarray(res[1], float) ** 2))))
        return sf, rms

    def _resolve_entry(self, p):
        """Pick the codec function that actually decodes audio for a generic
        build.  The audio fn lives at a build-specific dispatch sub-slot (see
        :data:`_PROBE_SLOTS`); they're indistinguishable statically (all
        reference PROV/QMUL), so probe and measure.  Cached per (scale, chan).

        Two passes.  Pass 1 (cheap, 0.6s): take the first slot that's clearly
        audio (specflat < 0.45) -- the common case, loud sounds resolve
        instantly.  Pass 2 (only if none was clearly audio -- a quiet/silent
        intro): re-probe over a longer window and pick the lowest-specflat slot
        that ISN'T the wrong loud-noise codec (see :data:`_NOISE_RMS`), so a
        correct-but-quiet slot beats the noise codec instead of losing to it.
        The noise rejection makes resolution robust no matter which sound first
        seeds a given (scale, chan) -- even a short, silent one."""
        key = (p["scale"], p["chan"])
        if key in self._slot_cache:
            return self._slot_cache[key]
        mu = self.mu
        cands = []
        for slot in self._PROBE_SLOTS:
            fnv = _u32(bytes(mu.mem_read(
                self.DISPATCH + p["scale"] * 0x40 + slot * 4, 4)))
            if fnv and self._backing_off(fnv) is not None and fnv not in cands:
                cands.append(fnv)
        # Pass 1: a short window resolves loud sounds immediately.
        best = None
        for fnv in cands:
            m = self._slot_metrics(p, fnv, 0.6)
            if m is not None and m[0] < 0.45:
                best = fnv
                break
        # Pass 2: nothing was clearly audio -- the sound has a quiet/silent
        # intro.  Re-probe longer, reject the loud-noise codec, take lowest sf.
        if best is None:
            scored = []
            for fnv in cands:
                m = self._slot_metrics(p, fnv, 3.5)
                if m is not None:
                    scored.append((fnv, m[0], m[1]))
            survivors = [(f, sf) for f, sf, rms in scored
                         if not (sf > self._NOISE_SF and rms > self._NOISE_RMS)]
            pool = survivors if survivors else [(f, sf) for f, sf, _ in scored]
            if pool:
                best = min(pool, key=lambda t: t[1])[0]
        self._slot_cache[key] = best
        return best

    def _backing_off(self, va):
        """File offset of a firmware vaddr (None if not in a load segment) —
        used to sanity-check a dispatch-slot fn pointer before probing it."""
        for vaddr, off, filesz, _memsz in self._segs:
            if vaddr <= va < vaddr + filesz:
                return off + (va - vaddr)
        return None

    def _decode_with_entry(self, p, entry, max_secs=None, cancel=None,
                           progress=None):
        """Decode one sound by driving codec ``entry``; see :meth:`decode`."""
        import numpy as np
        self.setup_decode()
        mu = self.mu
        chan = p["chan"]; stereo = (chan == 2); length = p["length"]
        Rmul, Roff = (4, 800) if stereo else (2, 400)
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
            if progress is not None:
                progress(cur, nmax)
        if not Ls:
            return None
        L = np.concatenate(Ls); R = np.concatenate(Rs)
        # Trim the trailing decode-scratch padding: the codec only ever emits
        # ``length - BLOCK`` real samples (see emitted_length); the last decoded
        # block(s) carry zero padding past that.  A capped (max_secs) run keeps
        # everything it decoded (it never reaches the padding).
        n = min(len(L), emitted_length(length))
        return L[:n], R[:n], stereo

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass
        try:
            self._imgf.close()
        except Exception:
            pass
