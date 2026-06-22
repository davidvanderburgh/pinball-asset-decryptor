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
from .emulator import DESC_BASE, PAGE, Spike2Emu, _R, _u32

DESC2 = 0xb0000000          # 2nd offset-identity window (clear of the image.bin one)


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
        # candidates; the caller trial-selects.
        lo = fstat_site if fstat_site is not None else cat0
        cands, seen = [], set()
        for site, tgt in _raw_bls(fw, lo, mmap_site):
            if tgt != cat0 and tgt not in seen and _is_funcstart(fw, tgt):
                seen.add(tgt)
                cands.append(tgt)
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
        self._catf = None
        self._mm_cat = None
        self.cat2size = 0
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
        if (self._mm_cat is not None
                and DESC2 <= addr < DESC2 + self.cat2size + 0x10000):
            return (self._mm_cat, addr - DESC2)
        return (None, None)

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
        mm, fo = self._backing(base)
        if mm is not None and 0 <= fo < mm.size():
            n = min(PAGE, mm.size() - fo)
            self.mu.mem_write(base, mm[fo:fo + n])
        return True

    def _mmap(self):
        sp = self.mu.reg_read(UC_ARM_REG_SP)
        off = struct.unpack("<I", bytes(self.mu.mem_read(sp + 4, 4)))[0]
        self._ret((DESC2 if self._serving_cat else DESC_BASE) + off)

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
        one — its window pages are invalidated so they re-fill)."""
        if self._mm_cat is not None:
            for base in [p for p in self.mapped_pages
                         if DESC2 <= p < DESC2 + self.cat2size + 0x20000]:
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
                    md_limit=600_000_000):
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
            if not (1 <= n <= 1 << 16):
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
            return self._chain_records(md, n, cap["state"])
        finally:
            self.del_hook(snp)
            self.del_hook(revalidate)
            self._serving_cat = False

    def _chain_records(self, md, n, state):
        """Replay each master-dir record's band-build in isolation (identical to
        :meth:`Spike2Emu.derive_params`'s chain), reading the raw obj verbatim."""
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
                obj, nxt = self._drive_step(cur, rec)
                if obj is None:
                    break
                rows.append(dict(idx=idx, body_off=_u32(obj, 0x00),
                                 length=_u32(obj, 0x10), scale=obj[0x1d],
                                 chan=obj[0x1b], _rawobj=obj))
                if nxt is None:
                    break
                cur = dict(regs=nxt[0], sp=nxt[1], frame=nxt[2])
        finally:
            self._imp = _orig
            for a in self.CHAIN_STUBS:
                self.extra.pop(a, None)
        return rows

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


def extract_category_audio(game_real_path, image_path, sc_files, write_wav,
                           log=None, progress=None, cancel=None):
    """Decode every per-category bank in ``sc_files`` (``image-scNN.bin`` paths)
    to WAV via ``write_wav(catid, idx, L, R, stereo)``.

    All params are derived first (the firmware band-build needs the global hook),
    THEN every sound is decoded (decoding switches the emulator to narrow hooks,
    one-way).  Returns the count decoded.  Skips gracefully (returns 0, never
    hangs) when the title's category loader can't be driven — cat-0 audio is
    unaffected."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    if not sc_files:
        return 0
    emu = CatEmu(game_real_path, image_path)
    emu.boot()
    try:
        if not emu.categories_supported:
            log("Per-category music banks aren't supported for this title's "
                "firmware build; skipping them (cat-0 audio already extracted).",
                "warning")
            return 0
        files = sorted((c, p) for p in sc_files
                       if (c := read_category_id(p)) is not None)
        if not files:
            return 0
        rev, rows0 = emu.pick_revalidate(files[0][0], files[0][1])
        if rev is None:
            log("Couldn't drive this title's category loader; skipping the "
                "per-song banks (cat-0 audio already extracted).", "warning")
            return 0

        # Phase A — derive every bank's params (global hook).
        derived = [(files[0][0], files[0][1], rows0)]
        for catid, p in files[1:]:
            if cancel():
                break
            emu.set_category_file(p)
            try:
                rows = emu._derive_cat(catid, rev)
            except Exception as e:
                log("Category %d: derive failed (%s); skipped." % (catid, e),
                    "warning")
                rows = None
            derived.append((catid, p, rows or []))
        total = sum(len(r) for _c, _p, r in derived)
        log("Derived %d sound(s) across %d category bank(s)."
            % (total, len(derived)), "info")
        if not total:
            return 0

        # Phase B — decode (switches to narrow hooks on the first decode).
        ok = 0
        for catid, p, rows in derived:
            if cancel():
                break
            emu.set_category_file(p)
            for r in rows:
                if cancel():
                    break
                try:
                    res = emu.decode_cat(r, cancel=cancel)
                except Exception:
                    res = None
                if res is None:
                    continue
                L, R, stereo = res
                write_wav(catid, r["idx"], L, R, stereo)
                ok += 1
                if progress:
                    progress(ok, total)
        return ok
    finally:
        emu.close()


# --------------------------------------------------------------------------
# parallel decode (one CatEmu per worker, each handling a subset of banks)
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


def _cat_pool_worker(args):
    """One worker = a fresh CatEmu decoding its assigned banks (derive-all then
    decode-all, per :func:`extract_category_audio`).  Returns the count decoded.
    Top-level so it pickles across the spawn boundary."""
    game_real_path, image_path, subset, out_dir = args
    try:
        return extract_category_audio(
            game_real_path, image_path, subset,
            lambda catid, idx, L, R, stereo: _write_cat_wav(
                out_dir, catid, idx, L, R, stereo))
    except Exception:
        return 0


def extract_category_audio_parallel(game_real_path, image_path, sc_files, out_dir,
                                    nworkers=None, log=None, progress=None,
                                    cancel=None):
    """Parallel twin of :func:`extract_category_audio` — splits the banks across
    ``nworkers`` spawned CatEmu processes (each boots once, decodes its subset,
    writes ``music_catNN_*.wav`` into ``out_dir``).  Falls back to a single
    in-process run if the pool can't start.  Returns the count decoded."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    files = sorted((c, p) for p in sc_files
                   if (c := read_category_id(p)) is not None)
    if not files:
        return 0
    import multiprocessing as mp

    nworkers = nworkers or max(1, min((os.cpu_count() or 2) - 2, 8))
    nworkers = max(1, min(nworkers, len(files)))
    # round-robin so each worker gets a spread of (differently-sized) banks
    chunks = [[] for _ in range(nworkers)]
    for i, (_c, p) in enumerate(files):
        chunks[i % nworkers].append(p)
    tasks = [(game_real_path, image_path, chunk, out_dir)
             for chunk in chunks if chunk]
    log("Decoding %d music bank(s) across %d process(es)..."
        % (len(files), len(tasks)), "info")
    try:
        ctx = mp.get_context("spawn")
        ok = 0
        done = 0
        with ctx.Pool(len(tasks)) as pool:
            for n in pool.imap_unordered(_cat_pool_worker, tasks):
                ok += n
                done += 1
                if progress:
                    progress(done, len(tasks))
                if cancel():
                    pool.terminate()
                    break
        return ok
    except Exception as e:
        log("Parallel music decode unavailable (%s); using one process." % e,
            "warning")
        return _cat_pool_worker((game_real_path, image_path,
                                 [p for _c, p in files], out_dir))
