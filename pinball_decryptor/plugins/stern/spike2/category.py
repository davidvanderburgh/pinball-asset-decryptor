"""Per-category (``image-scNN.bin``) audio for Spike 2.

Six titles split their audio into per-category banks the cat-0 (``image.bin``)
path never decodes — Metallica (24 banks = the licensed songs, 1 song ≈ 1 bank),
Dungeons & Dragons (29), Rush (17), Deadpool / Foo Fighters (16), John Wick (14).
The other 20 titles have ``image.bin[0x68] == 0`` categories and are fully covered
by cat-0.

The firmware loads each bank with ``load_category_assets(catid)`` then decodes it
with ``MASTERDIR_DECODE(catid)`` (the boot tail loops the id-array at
``image.bin[0x6c..]``).  We replicate that headless on top of the cat-0 oracle:

  * keep ``image.bin`` mapped at ``DESC_BASE`` (its mmap backs the cat-0 registry
    the firmware still reads), and serve the category file at a SECOND window
    ``DESC2``;
  * drive ``load_category_assets(cat)`` + ``MASTERDIR_DECODE(cat)`` reusing the
    cat-0 band-build hooks + codec — only the body source changes (the category
    file, at ``body_off`` relative to it).

Two build-specific firmware helpers must be stubbed (only the
``image-sc%02d.bin`` branch of the loader hits them; cat-0 takes the literal
``"image.bin"`` branch, which is why cat-0 always worked):

  * **snprintf** — the real statically-linked formatter crashes standalone.
  * a **map-revalidation** helper that spins (``Rb_tree_increment``) in the
    minimal emulator.

The revalidation helper's address varies by build, so it's located by resolving
the loader's ``mmap`` import (robust across layouts) and trial-selecting among the
local calls between ``fstat`` and ``mmap`` — the right stub is the one whose
decode yields real audio.  A bad guess is gated out by a cheap "did the category
register?" probe BEFORE ``MASTERDIR_DECODE`` runs, so it skips instead of spinning.

See ``plans/spike2_multicat_handoff.md``.
"""

import collections
import mmap
import os
import re
import struct

from unicorn import UcError
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_PC)

from . import locate as L
from .elf import parse_elf
from .emulator import DESC_BASE, MAX_RECORDS, PAGE, Spike2Emu, _R, _algn, _u32
from unicorn import UC_PROT_EXEC, UC_PROT_READ


# Fallback 2nd offset-identity window.  The real one is computed per card in
# :class:`CatEmu.__init__` so it always sits clear of the image.bin window —
# a fixed address here is NOT safe: Foo Fighters 1.04's 1.33 GB image.bin
# covers 0xb0000000, and _backing checks the image.bin range FIRST, so a
# DESC2 inside it serves the category file's reads from image.bin at the
# wrong offset (every bank's header then registers as garbage and every
# record-count gate fails — the songs silently never extracted).
DESC2 = 0xb0000000


# --------------------------------------------------------------------------
# firmware-address location (category-specific; generic across builds)
# --------------------------------------------------------------------------
def _expand_imm(w):
    """ARM data-processing modified-immediate (rotate)."""
    imm = w & 0xff
    rot = ((w >> 8) & 0xf) * 2
    return ((imm >> rot) | (imm << (32 - rot))) & 0xffffffff if rot else imm


def _plt_got(fw, plt):
    """GOT vaddr a 3-instruction ARM PLT stub jumps through, else None::

        add ip, pc, #a ; add ip, ip, #b ; ldr pc, [ip, #c]!
    """
    t = fw.secs[".text"]
    off = t["off"] + (plt - t["addr"])
    if off < 0 or off + 12 > len(fw.raw):
        return None
    w0, w1, w2 = struct.unpack_from("<III", fw.raw, off)
    if (w0 & 0x0fff0000) != 0x028f0000:        # add ip, pc, #a
        return None
    if (w1 & 0x0fff0000) != 0x028c0000:        # add ip, ip, #b
        return None
    if (w2 & 0x0fff0000) != 0x05bc0000:        # ldr pc, [ip, #c]!
        return None
    return (plt + 8) + _expand_imm(w0) + _expand_imm(w1) + (w2 & 0xfff)


def _raw_bls(fw, lo, hi):
    """[(site_va, target_va), ...] for every ARM ``bl`` (cond=AL) in ``[lo,hi)``.
    Raw-word scan: the linear disassembler desyncs on literal pools."""
    t = fw.secs[".text"]; base = t["addr"]; o = t["off"]
    out = []
    for va in range(lo, hi, 4):
        w = struct.unpack_from("<I", fw.raw, o + (va - base))[0]
        if (w >> 28) == 0xe and (w & 0x0f000000) == 0x0b000000:
            imm = w & 0xffffff
            if imm & 0x800000:
                imm -= 0x1000000
            out.append((va, va + 8 + imm * 4))
    return out


def _is_funcstart(fw, tgt):
    """True if ``tgt`` looks like a function entry (push {..,lr} prologue within
    the first few instructions) — filters literal-pool false ``bl`` matches."""
    t = fw.secs[".text"]; base = t["addr"]; o = t["off"]
    if not (base <= tgt < base + t["size"]):
        return False
    for d in (0, 4, 8, 12):
        w = struct.unpack_from("<I", fw.raw, o + (tgt - base + d))[0]
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):    # push {..,lr}
            return True
        if w == 0xE52DE004:                                    # str lr,[sp,#-4]!
            return True
    return False


def _is_leaf_funcstart(fw, tgt):
    """True if ``tgt`` looks like a LEAF function's entry: up to four
    ``movw``/``movt`` loading its globals, then a ``push`` that saves no ``lr``
    (it calls nothing).  Deadpool 1.16's map-revalidation helper (0x3845e8) is
    one: ``movw r3; movw ip; movt r3; movt ip; push {r4, r5}``, which
    :func:`_is_funcstart` turns down, so its 16 song banks never extracted
    (PAD-813)."""
    t = fw.secs[".text"]; base = t["addr"]; o = t["off"]
    if not (base <= tgt < base + t["size"] - 24):
        return False
    for d in range(0, 24, 4):
        w = struct.unpack_from("<I", fw.raw, o + (tgt - base + d))[0]
        if (w & 0xFFFF0000) == 0xE92D0000 and w & 0xFFFF:       # push {...}
            return True
        if (w & 0x0FF00000) not in (0x03000000, 0x03400000) or (w >> 28) != 0xE:
            return False                                         # not movw / movt
    return False


def _find_snprintf(fw, cat0, end):
    """First ``bl`` after the movw/movt that builds the ``image-sc…`` filename
    string's address."""
    pend = {}; armed = False
    for x in L._disasm(fw, cat0, end):
        if x.mnemonic == "movw":
            pend[x.op_str.split(",")[0]] = int(x.op_str.split("#")[1], 0)
        elif x.mnemonic == "movt":
            rd = x.op_str.split(",")[0]
            if rd in pend:
                c = (int(x.op_str.split("#")[1], 0) << 16) | pend[rd]
                fo = fw.off_of(c)
                if fo is not None and fw.raw[fo:fo + 8] == b"image-sc":
                    armed = True
        elif x.mnemonic == "bl" and armed:
            return int(x.op_str.lstrip("#"), 0)
    return None


def category_locators(raw, addrs):
    """Locate the category-decode firmware helpers from the ELF, generically.

    Returns ``{"SNPRINTF": va, "REVALIDATE_CANDIDATES": [va, ...]}`` or ``None``
    when the loader can't be analysed (→ caller skips category audio, cat-0 still
    works).  ``addrs`` = :func:`locate.locate_all` result (for CAT0_REGISTER)."""
    try:
        fw = L._FwView(raw)
        _segs, relocs = parse_elf(raw)
        got2name = {gv: nm for gv, nm in relocs}
        cat0 = addrs["CAT0_REGISTER"]
        end = L._func_end(fw, cat0)

        snp = _find_snprintf(fw, cat0, end)
        if snp is None:
            return None

        # Resolve the loader's import calls; anchor on fstat + mmap.
        fstat_site = mmap_site = None
        for site, tgt in _raw_bls(fw, cat0, end):
            nm = got2name.get(_plt_got(fw, tgt))
            if not nm:
                continue
            if "stat" in nm:
                fstat_site = site
            elif "mmap" in nm:
                mmap_site = site
        if mmap_site is None:
            return None

        # The map-revalidation helper is a local function called between the
        # fstat and mmap calls (the not-found registration path).  Usually 1-3
        # candidates; the caller trial-selects.  A leaf function (no lr saved)
        # is a candidate too, tried after the others (PAD-813: Deadpool 1.16's).
        lo = fstat_site if fstat_site is not None else cat0
        cands, leaves, seen = [], [], set()
        for site, tgt in _raw_bls(fw, lo, mmap_site):
            if tgt == cat0 or tgt in seen:
                continue
            seen.add(tgt)
            if _is_funcstart(fw, tgt):
                cands.append(tgt)
            elif _is_leaf_funcstart(fw, tgt):
                leaves.append(tgt)
        cands += leaves
        if not cands:
            return None
        return {"SNPRINTF": snp, "REVALIDATE_CANDIDATES": cands}
    except Exception:
        return None


# --------------------------------------------------------------------------
# category-aware emulator
# --------------------------------------------------------------------------
class CatEmu(Spike2Emu):
    """Spike 2 oracle extended to decode the per-category ``image-scNN.bin``
    banks.  Boots exactly like the cat-0 emulator (image.bin), then serves a
    category file at a second offset-identity window on demand."""

    def __init__(self, game_real_path, image_path):
        super().__init__(game_real_path, image_path)
        self._mm_img = self.mm
        self._img0 = self._mm_img.size()
        # The category window goes just past the image.bin window's end (page
        # aligned), where _backing's image.bin branch can never reach it.  A
        # ~2 GB image (MAX_IMAGE_BYTES) plus the largest bank still fits under
        # 4 GB: 0x703da000 + 0x80000000 + 0x9000000 < 0x100000000.
        self.DESC2 = _algn(DESC_BASE + self._img0 + 0x10000)
        self._catf = None
        self._mm_cat = None
        self.cat2size = 0
        # PAD-595: the bank window backed in ONE piece (a private copy-on-write
        # view), as the image.bin window is; (lo, hi) of the region, else (0, 0)
        self._catcow = self._catbuf = None
        self._cat_lo = self._cat_hi = 0
        self._serving_cat = False
        self._revalidate = None      # selected once per card
        raw = open(game_real_path, "rb").read()
        fw = L._FwView(raw)
        bls = _raw_bls(fw, self.MASTERDIR_DECODE, self.MASTERDIR_DECODE + 0x40)
        self._count_fn = bls[0][1] if bls else None   # MD's 1st bl == count_fn
        self._cat_locs = category_locators(raw, {"CAT0_REGISTER": self.CAT0_REGISTER})

    @property
    def categories_supported(self):
        return bool(self._cat_locs) and self._count_fn is not None

    # ---- two-window backing -------------------------------------------------
    def _backing(self, addr):
        if DESC_BASE <= addr < DESC_BASE + self._img0 + 0x10000:
            return (self._mm_img, addr - DESC_BASE)
        d2 = self.DESC2
        if (self._mm_cat is not None
                and d2 <= addr < d2 + self.cat2size + 0x10000):
            return (self._mm_cat, addr - d2)
        return (None, None)

    def _ensure_page(self, addr):
        base = addr & ~(PAGE - 1)
        if self._card_lo <= base < self._card_hi or self._cat_lo <= base < self._cat_hi:
            return True            # backed by a one-piece region already
        if base in self.mapped_pages:
            return True
        try:
            self.mu.mem_map(base, PAGE)
        except UcError:
            self.mapped_pages.add(base)
            return True
        self.mapped_pages.add(base)
        mm, fo = self._backing(base)
        if mm is not None and 0 <= fo < mm.size():
            n = min(PAGE, mm.size() - fo)
            self.mu.mem_write(base, mm[fo:fo + n])
        return True

    def _mmap(self):
        sp = self.mu.reg_read(UC_ARM_REG_SP)
        off = struct.unpack("<I", bytes(self.mu.mem_read(sp + 4, 4)))[0]
        self._ret((self.DESC2 if self._serving_cat else DESC_BASE) + off)

    def _fstat(self):
        sb = self.mu.reg_read(UC_ARM_REG_R2)
        sz = self.cat2size if self._serving_cat else self._img0
        try:
            self.mu.mem_write(sb, b"\x00" * 0x60)
            # st_size is at +0x2c in `struct stat` (e.g. Metallica/__fxstat) and
            # +0x30 in `struct stat64` (e.g. Deadpool/__fxstat64); write the
            # 8-byte size at both so the loader's mmap length is right either way.
            self.mu.mem_write(sb + 0x2c, struct.pack("<Q", sz))
            self.mu.mem_write(sb + 0x30, struct.pack("<Q", sz))
        except UcError:
            pass
        self._ret(0)

    # ---- category file in the 2nd window ------------------------------------
    def set_category_file(self, sc_path):
        """Map ``image-scNN.bin`` into the DESC2 window (replacing any previous
        one — its window pages are invalidated so they re-fill).

        The window is backed in ONE piece where it can be (PAD-595), the way
        :meth:`Spike2Emu._map_card_window` backs image.bin's: a bank this app
        builds has whole bodies written into the window by the chain encode,
        and paging those in 4 KiB at a time left every later guest access
        searching thousands of tiny regions (the three first beds of a nine-bed
        bank took 136, 355 and 816 s).  Any failure keeps the paging path."""
        if self._mm_cat is not None:
            d2 = self.DESC2
            self._unmap_cat_region()
            for base in [p for p in self.mapped_pages
                         if d2 <= p < d2 + self.cat2size + 0x20000]:
                try:
                    self.mu.mem_unmap(base, PAGE)
                except UcError:
                    pass
                self.mapped_pages.discard(base)
            try:
                self._mm_cat.close()
            except Exception:
                pass
            try:
                self._catf.close()
            except Exception:
                pass
        self._catf = open(sc_path, "rb")
        self._mm_cat = mmap.mmap(self._catf.fileno(), 0, access=mmap.ACCESS_READ)
        self.cat2size = self._mm_cat.size()
        self._map_cat_region()

    def _map_cat_region(self):
        span = self.cat2size & ~(PAGE - 1)
        d2 = self.DESC2
        if span <= 0 or d2 + span > 0x1_0000_0000:
            return
        # PAD-777 (spike2.window): a bank's encode writes its bodies into this
        # window, so it is a copy-on-write view from the start as it always was
        # (a bank is 218 MB at most; image.bin's window is the one that weighed)
        try:
            self.mu.map_window(d2, span, self._catf, UC_PROT_READ | UC_PROT_EXEC,
                               copy=True)
        except Exception as e:                                       # noqa: BLE001
            self.log.append(("cat_map_ptr", str(e)))
            return
        self._cat_lo, self._cat_hi = d2, d2 + span

    def _unmap_cat_region(self):
        if self._cat_hi > self._cat_lo:
            try:
                self.mu.unmap_window(self._cat_lo)
            except UcError:
                pass
        self._cat_lo = self._cat_hi = 0
        self._catbuf = None
        self._catcow = None

    def close(self):
        try:
            self._unmap_cat_region()
        except Exception:                                            # noqa: BLE001
            pass
        for f in (self._mm_cat, self._catf):
            try:
                if f is not None:
                    f.close()
            except Exception:
                pass
        self._mm_cat = self._catf = None
        super().close()

    # ---- snprintf stub (filename irrelevant — window chosen by the flag) -----
    def _snprintf_stub(self, eng):
        buf = eng.mu.reg_read(UC_ARM_REG_R0)
        try:
            eng.mu.mem_write(buf, b"image-sc.bin\x00")
        except UcError:
            pass
        eng.mu.reg_write(UC_ARM_REG_R0, 12)
        eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))

    @staticmethod
    def _ret_stub(eng):
        eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))

    # ---- derive one category's params --------------------------------------
    def _derive_cat(self, cat, revalidate, load_limit=80_000_000,
                    md_limit=600_000_000, after_step=None):
        """Drive ``load_category_assets(cat)`` + ``MASTERDIR_DECODE(cat)`` with
        the two stubs; return the per-sound params (mirrors
        :meth:`Spike2Emu.derive_params`) or ``None`` if the category didn't
        register (bad ``revalidate`` stub / empty category) — gated BEFORE
        ``MASTERDIR_DECODE`` so a wrong stub can't spin it."""
        mu = self.mu
        snp = self._cat_locs["SNPRINTF"]
        self.add_hook(snp, self._snprintf_stub)
        self.add_hook(revalidate, self._ret_stub)
        try:
            if self._generic:
                self._blank_buf = self.alloc(0x100)
                self._blank_node = self.alloc(0x10)
                mu.mem_write(self._blank_buf, b"\x00" * 0x100)
                mu.mem_write(self._blank_node, struct.pack("<I", self._blank_buf))
                try:
                    mu.mem_write(self.REG_BASE + 0xad8, struct.pack("<I", 11))
                except UcError:
                    pass

            self._serving_cat = True
            self.call(self.CAT0_REGISTER, (cat,), limit=load_limit)

            # Anti-hang gate: count_fn(cat) must return a sane record count
            # before we let MASTERDIR_DECODE run.  count_fn = MD's 1st bl.
            cnt = self.call(self._count_fn, (cat, 4), limit=20_000_000)
            n = cnt[1] if cnt[0] == "ok" else 0
            if not (1 <= n <= MAX_RECORDS):
                return None

            cap = {"mddst": None, "state": None}

            def at_md(eng):
                if cap["mddst"] is None:
                    cap["mddst"] = eng.mu.reg_read(UC_ARM_REG_R0)

            def at_bb(eng):
                if cap["state"] is None:
                    m = eng.mu; sp = m.reg_read(UC_ARM_REG_SP)
                    cap["state"] = dict(
                        regs=[m.reg_read(r) for r in _R] + [sp, m.reg_read(UC_ARM_REG_LR)],
                        sp=sp, frame=bytes(m.mem_read(sp, 0x2a0)))
                    m.emu_stop()
            self.extra[self.MASTERDIR_MALLOC] = at_md
            self.extra[self.BANDLOOP] = at_bb
            self.call(self.MASTERDIR_DECODE, (cat,), limit=md_limit)
            self.extra.pop(self.MASTERDIR_MALLOC, None)
            self.extra.pop(self.BANDLOOP, None)
            if cap["state"] is None or cap["mddst"] is None:
                return None
            self._ensure_range(cap["mddst"], n * 24)
            md = bytes(mu.mem_read(cap["mddst"], n * 24))
            # Bounds the per-record write-back in _drive_step to each record's
            # own slot; without it the replay scribbles 24 bytes at a
            # pseudo-random address per record, and bounding it to the array
            # alone still lets a misaligned hit straddle two records (see
            # emulator._record_write_addr).
            self._md_range = (cap["mddst"], cap["mddst"] + n * 24)
            return self._chain_records(md, n, cap["state"], after_step)
        finally:
            self.del_hook(snp)
            self.del_hook(revalidate)
            self._serving_cat = False

    def _chain_records(self, md, n, state, after_step=None):
        """Replay each master-dir record's band-build in isolation (identical to
        :meth:`Spike2Emu.derive_params`'s chain), reading the raw obj verbatim.

        Each row also carries the record's ``identity`` bytes and the container
        key it registered under (``findkey`` / ``key0``, generic builds), as
        :meth:`Spike2Emu.derive_params` reports them.  *after_step* ``(idx, row,
        redo)`` is that method's chain-aware hook (PAD-595: a bank this app
        builds is encoded along its own chain): it may change the bank's bytes
        in this emulator's memory and call ``redo()`` for the same record's
        step again, returning the new ``(obj, next)`` to carry the chain on."""
        def _stub(eng):
            eng.mu.reg_write(UC_ARM_REG_R0, 0)
            eng.mu.reg_write(UC_ARM_REG_PC, eng.mu.reg_read(UC_ARM_REG_LR))
        for a in self.CHAIN_STUBS:
            self.extra[a] = _stub
        _orig = self._imp

        def _capped(sent):
            nm = self.imports.get(sent)
            if nm in ("memcpy", "memmove", "memset"):
                c = self.mu.reg_read(UC_ARM_REG_R2)
                if c > 0x40000:
                    self.mu.reg_write(UC_ARM_REG_R2, 0x40000)
            return _orig(sent)
        self._imp = _capped
        rows = []
        cur = dict(regs=list(state["regs"]), sp=state["sp"], frame=state["frame"])
        try:
            for idx in range(n):
                rec = md[idx * 24: idx * 24 + 24]
                obj, nxt = self._drive_step(cur, rec, rec_idx=idx)
                if obj is None:
                    break
                fk = getattr(self, "_last_find_key", None)
                row = dict(idx=idx, body_off=_u32(obj, 0x00),
                           length=_u32(obj, 0x10), scale=obj[0x1d],
                           chan=obj[0x1b], _rawobj=obj,
                           identity=rec[4:16] + rec[20:24],
                           key0=_u32(fk, 0) if fk and len(fk) >= 4 else None,
                           findkey=bytes(fk) if fk and len(fk) >= 8 else None)
                if after_step is not None:
                    def redo(_cur=cur, _rec=rec, _idx=idx):
                        return self._drive_step(_cur, _rec, rec_idx=_idx)
                    got = after_step(idx, row, redo)
                    if got is not None:
                        obj2, nxt2 = got
                        if obj2 is None or obj2[:0x20] != obj[:0x20]:
                            raise RuntimeError(
                                "bank record %d built a different codec object when its "
                                "own body changed; a record's windows set only the records "
                                "after it" % idx)
                        nxt = nxt2
                        fk2 = getattr(self, "_last_find_key", None)
                        if fk2 and len(fk2) >= 8:
                            row["key0"] = _u32(fk2, 0)
                            row["findkey"] = bytes(fk2)
                rows.append(row)
                if nxt is None:
                    break
                cur = dict(regs=nxt[0], sp=nxt[1], frame=nxt[2])
        finally:
            self._imp = _orig
            for a in self.CHAIN_STUBS:
                self.extra.pop(a, None)
        return rows

    # ---- a bank this app built (PAD-595) ------------------------------------
    def derive_bank(self, cat, sc_path, after_step=None, revalidate=None):
        """Derive the records of the bank *sc_path* as category *cat*, through the
        firmware's own loader and directory decode, each row with the container
        key it registers under.  *revalidate* is the map-revalidation stub
        (:meth:`pick_revalidate`); None tries the build's candidates in turn.
        *after_step* is :meth:`_chain_records`'s.  Returns the rows, or raises
        when the firmware does not register the bank -- a file the game would
        not load either.  Use a FRESH emulator per call: a second derive on one
        booted emulator finds the category already registered."""
        if not self.categories_supported:
            raise RuntimeError("this game program's category loader cannot be driven")
        self.set_category_file(sc_path)
        cands = [revalidate] if revalidate is not None else \
            list(self._cat_locs["REVALIDATE_CANDIDATES"])
        if self._revalidate is not None and revalidate is None:
            cands = [self._revalidate]
        last = None
        for rev in cands:
            try:
                rows = self._derive_cat(cat, rev, after_step=after_step)
            except RuntimeError:
                raise
            except Exception as e:                                  # noqa: BLE001
                rows, last = None, e
            if rows:
                self._revalidate = rev
                return rows
        raise RuntimeError("the firmware did not register sound bank %s as category %d%s"
                           % (os.path.basename(sc_path), cat,
                              " (%s)" % last if last is not None else ""))

    def register_bank(self, cat, sc_path, revalidate=None, load_limit=80_000_000):
        """Load the bank *sc_path* as category *cat* through the firmware's own
        loader (``load_category_assets``: open, fstat, mmap, the header copied,
        the container registered) WITHOUT decoding its directory, and return
        the record count the firmware then reports for it (PAD-595).  The
        game's resolver can then be driven for the bank's sids: it needs only
        the container's base and header.  (A full :meth:`derive_bank` of a
        bank with real audio left this emulator unable to run the resolver
        afterwards, where the records had derived correctly.)"""
        if not self.categories_supported:
            raise RuntimeError("this game program's category loader cannot be driven")
        self.set_category_file(sc_path)
        rev = revalidate if revalidate is not None else self._revalidate
        if rev is None:
            rev = list(self._cat_locs["REVALIDATE_CANDIDATES"])[0]
        snp = self._cat_locs["SNPRINTF"]
        self.add_hook(snp, self._snprintf_stub)
        self.add_hook(rev, self._ret_stub)
        try:
            self._serving_cat = True
            st = self.call(self.CAT0_REGISTER, (cat,), limit=load_limit)
            if st[0] != "ok":
                raise RuntimeError("the firmware's bank loader did not return for %s (%s)"
                                   % (os.path.basename(sc_path), st[1]))
            cnt = self.call(self._count_fn, (cat, 4), limit=20_000_000)
            return cnt[1] if cnt[0] == "ok" else 0
        finally:
            self.del_hook(snp)
            self.del_hook(rev)
            self._serving_cat = False

    # ---- decode a category sound (body from the category file) --------------
    def decode_cat(self, p, max_secs=None, cancel=None, progress=None):
        prev = self.mm
        self.mm = self._mm_cat          # body fill reads the category file
        try:
            return self.decode(p, max_secs=max_secs, cancel=cancel,
                               progress=progress)
        finally:
            self.mm = prev

    # ---- pick the revalidate stub by the count-gate (no decode) -------------
    def pick_revalidate(self, probe_cat, sc_path):
        """Select the map-revalidation stub by deriving ``probe_cat`` with each
        candidate and keeping the one that registers (the count-gate inside
        :meth:`_derive_cat` passes → non-empty rows).  Uses NO decode, so the
        emulator stays on the global hook and more categories can be derived
        afterwards.  Returns ``(revalidate_va, probe_rows)`` or ``(None, None)``
        (→ skip categories for this title; cat-0 still extracts)."""
        if not self._cat_locs:
            return (None, None)
        self.set_category_file(sc_path)
        for rev in self._cat_locs["REVALIDATE_CANDIDATES"]:
            try:
                rows = self._derive_cat(probe_cat, rev, md_limit=120_000_000)
            except Exception:
                rows = None
            if rows:
                self._revalidate = rev
                return (rev, rows)
        return (None, None)


# --------------------------------------------------------------------------
_SC_RE = re.compile(r"image-sc0*(\d+)\.bin$", re.IGNORECASE)


def read_category_id(sc_path):
    """The category id of a bank file = the number in its name: the firmware
    builds the path as ``image-sc%02d.bin`` from the id, so the filename number
    IS the category id (the id-array is non-sequential on some builds, e.g.
    Deadpool's ``image-sc01,03,05,…,55.bin`` → cats 1,3,5,…,55).  ``None`` if the
    name doesn't match."""
    m = _SC_RE.search(os.path.basename(sc_path))
    return int(m.group(1)) if m else None


def _find_revalidate(game_real_path, image_path, files, log):
    """Boot one CatEmu and locate the map-revalidation stub (``rev``) for this
    title by probing the first bank.  Returns ``rev`` (an int) or ``None`` when
    the build's category loader can't be driven (→ caller skips, cat-0 audio is
    unaffected).  Run ONCE per extract — the workers reuse the same ``rev`` so
    they never re-pay the candidate trial."""
    emu = CatEmu(game_real_path, image_path)
    try:
        emu.boot()
        if not emu.categories_supported:
            log("Per-category music banks aren't supported for this title's "
                "firmware build; skipping them (cat-0 audio already "
                "extracted).", "warning")
            return None
        rev, _rows0 = emu.pick_revalidate(files[0][0], files[0][1])
        if rev is None:
            log("Couldn't drive this title's category loader; skipping the "
                "per-song banks (cat-0 audio already extracted).", "warning")
        return rev
    finally:
        emu.close()


def bank_sound_test_names(game_real_path, image_path, rev, catid, sc_path, rows,
                          entries):
    """``{record: name}``: the Sound Test entries *entries* ``[(sid, name)]`` of
    category *catid* (:func:`.sfx_names.bank_menu_sids`), landed on the bank's
    records (*rows*, its derive, for the keys and lengths) through the game's
    own resolver (PAD-820).  A FRESH emulator, the bank loaded by the game's
    loader alone: a full derive leaves an emulator unable to run the resolver
    (:meth:`CatEmu.register_bank`).  ``{}`` when nothing can be named; never
    raises."""
    from . import sfx_names as SN
    entries = [(s, n) for s, n in entries if s >> 16 == catid]
    if not entries or not rows:
        return {}
    keys = collections.Counter(r.get("key0") for r in rows)
    key0_to_idx = {r["key0"]: r["idx"] for r in rows
                   if r.get("key0") is not None and keys[r["key0"]] == 1}
    seconds = {r["idx"]: r.get("length", 0) / 44100.0 for r in rows}
    emu = CatEmu(game_real_path, image_path)
    try:
        emu.boot()
        if not emu.register_bank(catid, sc_path, revalidate=rev):
            return {}
        resolver, out = SN._find_resolver(emu)
        if resolver is None:
            return {}
        d2, mm = emu.DESC2, emu._mm_cat

        def resolve(sid):
            emu.mu.mem_write(out, b"\x00" * 0x40)
            st = emu.call(resolver, (sid, out), limit=5_000_000)
            if st[0] != "ok" or not d2 <= st[1] < d2 + emu.cat2size:
                return None
            off = st[1] - d2
            ks = _u32(bytes(emu.mu.mem_read(out, 4))) - emu.VF2_VA
            if not 0 <= ks < 0x3F00:
                return None
            body = mm[off:off + SN.DESC_WINDOW]
            vf2 = bytes(emu.mu.mem_read(emu.VF2_VA + ks, len(body)))
            return bytes(a ^ b for a, b in zip(body, vf2))
        return SN.bank_name_map(resolve, entries, key0_to_idx, seconds)
    except Exception:                                               # noqa: BLE001
        return {}
    finally:
        emu.close()


def name_cat_wavs(out_dir, catid, names):
    """Rename this bank's decoded ``music_catNN_MMMM.wav`` files to
    ``music_catNN_MMMM - <name>.wav`` (the cat-0 ``idx#### - <name>`` shape,
    the name cleaned the same way).  Returns the count renamed."""
    from ..engine import _ILLEGAL_FN
    n = 0
    for idx, name in names.items():
        stem = "music_cat%02d_%04d" % (catid, idx)
        src = os.path.join(out_dir, stem + ".wav")
        safe = _ILLEGAL_FN.sub("", name).strip().rstrip(".")[:80]
        if not safe or not os.path.isfile(src):
            continue
        try:
            os.replace(src, os.path.join(out_dir, "%s - %s.wav" % (stem, safe)))
            n += 1
        except OSError:
            pass
    return n


def _derive_decode_bank(game_real_path, image_path, rev, catid, sc_path, sink,
                        cancel, only=None, menu=None, named=None):
    """Derive + decode ONE bank on a FRESH CatEmu, emitting each decoded sound
    to ``sink(catid, idx, L, R, stereo)``.  Returns the count decoded.

    A fresh emulator PER BANK is deliberate: deriving several categories on one
    booted emu accumulates registry state that makes the 3rd-and-later derive's
    ``MASTERDIR_DECODE`` grind to its instruction cap (minutes per bank).  A
    fresh emu derives every bank in ~13 s flat, so the whole job parallelises
    cleanly.  The decode reuses this same emu — decoding is registry-stateless
    and switches the emulator to the narrow-hook fast path (~1 s per 20 s of
    audio), so re-deriving it elsewhere would be wasted work.  *only*: the
    record numbers to decode (PAD-608: a sound bank of this app's, of which an
    extract wants the music modes' files alone); all when None.

    *menu* ``[(sid, name)]`` (:func:`.sfx_names.bank_menu_sids`, PAD-820): once
    the bank is decoded, the Sound Test names of its records are worked out on
    a fresh emulator (:func:`bank_sound_test_names`) and handed to
    ``named(catid, {record: name})``."""
    emu = CatEmu(game_real_path, image_path)
    ok = 0
    try:
        emu.boot()
        if not emu.categories_supported:
            return 0
        emu.set_category_file(sc_path)
        try:
            rows = emu._derive_cat(catid, rev)
        except Exception:
            rows = None
        if not rows:
            return 0
        for r in rows:
            if cancel():
                break
            if only is not None and r["idx"] not in only:
                continue
            try:
                res = emu.decode_cat(r, cancel=cancel)
            except Exception as e:
                from .parallel import out_of_memory
                if out_of_memory(e):
                    raise   # PAD-830: the caller decodes the bank again alone
                res = None
            if res is None:
                continue
            L, R, stereo = res
            sink(catid, r["idx"], L, R, stereo)
            ok += 1
    finally:
        emu.close()
    if ok and menu and named is not None and not cancel():
        names = bank_sound_test_names(game_real_path, image_path, rev, catid,
                                      sc_path, rows, menu)
        if names:
            named(catid, names)
    return ok


def extract_category_audio(game_real_path, image_path, sc_files, write_wav,
                           log=None, progress=None, cancel=None):
    """Decode every per-category bank in ``sc_files`` (``image-scNN.bin`` paths)
    to WAV via ``write_wav(catid, idx, L, R, stereo)``.

    Each bank is derived + decoded on its own fresh emulator (see
    :func:`_derive_decode_bank` for why), serially.  Returns the count decoded.
    Skips gracefully (returns 0, never hangs) when the title's category loader
    can't be driven — cat-0 audio is unaffected.  :func:`extract_category_audio_parallel`
    is the production path; this serial form backs the tests + the no-pool
    fallback."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    if not sc_files:
        return 0
    files = sorted((c, p) for p in sc_files
                   if (c := read_category_id(p)) is not None)
    if not files:
        return 0
    rev = _find_revalidate(game_real_path, image_path, files, log)
    if rev is None:
        return 0
    ok = 0
    for catid, p in files:
        if cancel():
            break
        try:
            ok += _derive_decode_bank(game_real_path, image_path, rev, catid, p,
                                      write_wav, cancel)
        except Exception as e:
            log("Category %d: failed (%s); skipped." % (catid, e), "warning")
        if progress:
            progress(ok, len(files))
    return ok


# --------------------------------------------------------------------------
# parallel decode (one FRESH CatEmu per bank, fanned across spawned processes)
# --------------------------------------------------------------------------
def _write_cat_wav(out_dir, catid, idx, L, R, stereo):
    import wave

    import numpy as np
    chans = [L, R] if stereo else [L]
    n = len(chans[0])
    inter = np.empty(n * len(chans), np.int16)
    for i, c in enumerate(chans):
        inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
    path = os.path.join(out_dir, "music_cat%02d_%04d.wav" % (catid, idx))
    w = wave.open(path, "wb")
    w.setnchannels(len(chans))
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(inter.tobytes())
    w.close()


def _bank_pool_worker(args):
    """One task = derive + decode a SINGLE bank on a fresh emu, writing its WAVs
    straight to ``out_dir`` (so only a small count crosses the process boundary).
    Top-level so it pickles across the spawn boundary; ``rev`` is found once in
    the parent and passed in.  Returns ``(decoded, named from the Sound Test)``;
    decoded is :data:`.parallel.NO_MEMORY` when the bank ran out of memory
    (PAD-830: it used to come back as 0, its songs silently missing)."""
    game_real_path, image_path, rev, catid, sc_path, out_dir = args[:6]
    only = args[6] if len(args) > 6 else None
    menu = args[7] if len(args) > 7 else None
    renamed = []

    def named(c, names):
        renamed.append(name_cat_wavs(out_dir, c, names))
    try:
        n = _derive_decode_bank(
            game_real_path, image_path, rev, catid, sc_path,
            lambda c, idx, L, R, stereo: _write_cat_wav(out_dir, c, idx, L, R,
                                                        stereo),
            lambda: False, only=only, menu=menu, named=named)
    except Exception as e:
        from .parallel import NO_MEMORY, out_of_memory
        if out_of_memory(e):
            return NO_MEMORY, 0
        n = 0
    return n, sum(renamed)


def _bank_pool_indexed(arg):
    """``(i, task)`` -> ``(i, _bank_pool_worker(task))``: which bank a pool
    answer is for, to decode it again when it ran out of memory (PAD-830)."""
    i, task = arg
    return i, _bank_pool_worker(task)


def extract_category_audio_parallel(game_real_path, image_path, sc_files, out_dir,
                                    nworkers=None, log=None, progress=None,
                                    cancel=None, only=None, names=False):
    """Parallel twin of :func:`extract_category_audio` — one task PER BANK, each
    deriving + decoding on a fresh emulator in its own spawned process (so the
    per-bank derive can't accumulate the state that grinds a long-lived emu, and
    the work spreads across cores).  ``rev`` is located once up front and shared.
    Writes ``music_catNN_*.wav`` into ``out_dir``; falls back to the serial path
    if the pool can't start.  Returns the count decoded.  *only* ``{category:
    {record, ...}}`` decodes just those records of those banks (PAD-608).
    *names* titles the songs the game's Sound Test names
    (``music_catNN_MMMM - <name>.wav``, :func:`bank_sound_test_names`, PAD-820)."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    files = sorted((c, p) for p in sc_files
                   if (c := read_category_id(p)) is not None)
    if not files:
        return 0
    rev = _find_revalidate(game_real_path, image_path, files, log)
    if rev is None:
        return 0
    import multiprocessing as mp

    from .parallel import NO_MEMORY, emulator_commit, emulators_that_fit
    want = max(1, min(nworkers or max(1, min((os.cpu_count() or 2) - 2, 8)),
                      len(files)))
    # PAD-830: a bank's worker holds its longest song decoded, so it is held to
    # two emulators' worth of the memory the computer has room for
    nworkers = emulators_that_fit(2 * emulator_commit(image_path), want)
    if nworkers < want:
        log("Decoding the music banks on %d process(es), not %d: this computer "
            "has the memory for %d now." % (nworkers, want, nworkers), "info")
    # Longest-processing-time-first: the pool pulls tasks greedily, so start the
    # biggest banks (≈ longest songs ≈ longest decodes) first — otherwise a 9-min
    # song picked up in the final round becomes pure tail latency.  Bank file
    # size is a good proxy for decoded length.
    def _sz(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0
    ordered = sorted(files, key=lambda cp: _sz(cp[1]), reverse=True)
    menu = None
    if names:
        try:
            from .sfx_names import bank_menu_sids
            with open(game_real_path, "rb") as f:
                menu = bank_menu_sids(f.read()) or None
        except Exception:                                           # noqa: BLE001
            menu = None

    def _task(catid, p):
        return (game_real_path, image_path, rev, catid, p, out_dir,
                frozenset((only or {}).get(catid, ())) if only is not None else None,
                [e for e in menu if e[0] >> 16 == catid] if menu else None)
    tasks = [_task(catid, p) for catid, p in ordered]
    titled = 0
    log("Decoding %d music bank(s) across %d process(es)..."
        % (len(files), nworkers), "info")
    try:
        ctx = mp.get_context("spawn")
        ok = 0
        done = 0
        # maxtasksperchild=1: a fresh process per bank reclaims the large
        # unicorn mappings a long song's decode allocates, and guarantees the
        # per-bank emu never inherits another bank's accumulated state.
        again = []
        with ctx.Pool(nworkers, maxtasksperchild=1) as pool:
            for i, (n, t) in pool.imap_unordered(_bank_pool_indexed,
                                                 list(enumerate(tasks))):
                task = tasks[i]
                if n == NO_MEMORY:
                    again.append(task)
                else:
                    ok += n
                    titled += t
                    done += 1
                if progress:
                    progress(done, len(tasks))
                if cancel():
                    pool.terminate()
                    break
        # PAD-830: a bank whose worker ran out of memory beside the others is
        # decoded again here, alone, once the pool has given its memory back
        missing = []
        for task in again:
            if cancel():
                break
            log("Music bank %d ran out of memory beside the others; decoding it "
                "again on its own." % task[3], "warning")
            n, t = _bank_pool_worker(task)
            if n == NO_MEMORY:
                missing.append(task[3])
                continue
            ok += n
            titled += t
            done += 1
            if progress:
                progress(done, len(tasks))
        if missing:
            log("Music bank(s) %s could not be decoded: this computer ran out of "
                "memory even with nothing else decoding. Close other programs, "
                "check the C: drive has a few GB free so Windows can grow its "
                "page file, and extract again."
                % ", ".join(map(str, missing)), "error")
        _log_titled(log, titled)
        return ok
    except Exception as e:
        log("Parallel music decode unavailable (%s); using one process." % e,
            "warning")
        ok = titled = 0
        for catid, p in files:
            if cancel():
                break
            n, t = _bank_pool_worker(_task(catid, p))
            if n == NO_MEMORY:
                log("Music bank %d could not be decoded: this computer ran out "
                    "of memory." % catid, "error")
                continue
            ok += n
            titled += t
            if progress:
                progress(ok, len(files))
        _log_titled(log, titled)
        return ok


def _log_titled(log, titled):
    if titled:
        log("Named %d song file(s) from the game's Sound Test menu." % titled,
            "success")
