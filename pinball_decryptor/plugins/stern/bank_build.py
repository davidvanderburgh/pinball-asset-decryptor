"""Building an extra sound bank into a Write (PAD-595): which sounds spill out of
``image.bin``, the bank file staged for them, its records encoded along the
firmware's own chain, and the finished bank checked.

The pieces (``spike2/soundbank.py`` has the file's geometry and the why):

* :func:`plan_spill` -- of the modes' own sounds a Write grows into
  ``image.bin``, the ones that would take it past the game's 2 GiB, largest
  first, split into banks each under 2 GiB.
* :func:`stage_bank` -- the bank file for one of them: one record per sound,
  a copy of its host's stock record with the bank's geometry, its body a
  scaffold of the host's own audio (the chain derive runs over these bytes
  first), the directory packed under the firmware's cipher.
* :func:`chain_encode` -- the sounds encoded in the bank's own chain order,
  each with the parameters the firmware gives its record and its bytes put
  in before the next record's step (as ``engine._chain_encode_appended``
  does for ``image.bin``), so every window holds the sound's own audio and
  every key is the one the finished bank registers.
* :func:`verify_bank` -- the finished file derived again on a fresh
  emulator: the same codec objects and the same keys, or the Write stops.
* :func:`write_bank_tables` / :func:`verify_tables` -- the play tables that
  make the bank's sounds PLAYABLE by a sid of its category (``soundbank``
  has the why): one fragment a sound and a descriptor copied from the
  sound's carrier with the bank record's key and length, whitened as the
  game's resolver expects (:func:`resolver_rule` measures the rule off the
  card's own cat-0 sids), then every bank sid resolved through the game's
  own resolver on the finished file.

Everything here is driven through :class:`.spike2.category.CatEmu`, the
emulator that serves a bank at a second window exactly as the game's loader
maps it.
"""
import collections
import os
import struct
from dataclasses import dataclass

from ...core.longpath import ext as _lp
from .spike2 import masterdir as MD
from .spike2 import soundbank as SB

#: ``PAD_STERN_BANK_CAP=<bytes>``: a lower ceiling for ``image.bin`` than the
#: game's 2 GiB, so a build on a small stock bank spills into a sound bank of
#: its own the way a full one does (the emulator proof; never set by a user).
BANK_CAP_ENV = "PAD_STERN_BANK_CAP"


def image_cap():
    """The most ``image.bin`` may measure in this Write: the game's own limit,
    or :data:`BANK_CAP_ENV` below it."""
    from .spike2.emulator import MAX_IMAGE_BYTES
    v = os.environ.get(BANK_CAP_ENV)
    try:
        return min(MAX_IMAGE_BYTES, int(v)) if v else MAX_IMAGE_BYTES
    except ValueError:
        return MAX_IMAGE_BYTES


# --------------------------------------------------------------------------
# which sounds spill
# --------------------------------------------------------------------------
def plan_spill(grows, bankable, byidx, img_path, limit=None, start=()):
    """``(kept, spilled)``: *grows* (``{idx: (room, want)}``) less the
    *bankable* ones that have to leave ``image.bin`` for it to stay within
    *limit* (default :func:`image_cap`) with the bodies *start* placed as well.
    The largest bankable body goes first, so the fewest sounds move; a sound
    that is not bankable always stays (a longer replacement reaches its
    record through a re-pointed play table, which cannot name a bank)."""
    from . import engine as E
    limit = image_cap() if limit is None else int(limit)
    # past an earlier build's bodies, as the grow lays it out (PAD-593): the
    # tester's card keeps its record array at 1.65 GB and 360 MB of bodies
    # behind it, and the header alone said 1.9 GB where the file would be 2.26
    md_off, count = MD.image_grow_geometry(_lp(img_path))
    kept = dict(grows)
    spilled = {}
    bodies = {i: E._grown_body_bytes(byidx[i], g[1]) for i, g in grows.items()}
    while kept and E._grown_bank_bytes(md_off, count, list(start) + list(bodies.values())) > limit:
        cands = [i for i in kept if i in bankable]
        if not cands:
            break
        i = max(cands, key=lambda k: (bodies[k], k))
        spilled[i] = kept.pop(i)
        bodies.pop(i)
    return kept, spilled


def bank_edits(spilled, byidx, directory):
    """The :class:`.soundbank.BankEdit` list for *spilled* grows (``{idx:
    (room, want)}``) longest first: each sound's host record out of *directory*
    (``image.bin``'s), its length and the body its longer copy takes.  A host
    an earlier build already grew plays its appended record (``shadows``), the
    one *byidx* describes, so that is the record copied (PAD-593)."""
    from . import engine as E
    from .spike2.emulator import BLOCK
    out = []
    # longest first, as image.bin's appended records (PAD-677, E._chain_order)
    for idx in E._chain_order(spilled):
        _room, want = spilled[idx]
        p = byidx[idx]
        src = idx if p.get("shadows") is None else int(p["shadows"])
        out.append(SB.BankEdit(idx, directory.record(src), int(p["length"]),
                               int(want) + BLOCK, E._grown_body_bytes(p, want)))
    return out


# --------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------
def stage_bank(gr_path, img_path, work, byidx, edits, cat, log, emu=None, stride=None,
               aliases=(), desc_slot=SB.DESC_SLOT, mapped=0):
    """Write the bank for category *cat* holding *edits* into *work* and return
    ``(path, places)``.  Each body starts as the host's stock audio repeated
    to fill; *emu* is a booted emulator on the card's program (one is made
    when None).  PAD-608: *aliases* (:func:`.soundbank.plan_bank`) are the
    fragments past the records that play one of them.  PAD-779: *desc_slot* and
    *mapped* as :func:`.soundbank.plan_bank` takes them (a song in parts)."""
    from .spike2.emulator import Spike2Emu
    if stride is None:
        with open(_lp(img_path), "rb") as f:
            stride = SB.fragment_stride(f.read(0x100))
    directory, places = SB.plan_bank(edits, stride, aliases=aliases, desc_slot=desc_slot,
                                     mapped=mapped)
    scaffold = {}
    with open(_lp(img_path), "rb") as f:
        for pl in SB.records(places):
            p = byidx[pl.idx]
            step = 4 if p.get("chan") == 2 else 2
            f.seek(p["body_off"])
            scaffold[pl.new_idx] = f.read(step * int(p["length"])) or b"\x00"
    os.makedirs(_lp(work), exist_ok=True)
    path = os.path.join(work, SB.bank_name(cat))
    own = emu is None
    if own:
        emu = Spike2Emu(gr_path, img_path)
        emu.boot()
    try:
        # image.bin's own directory first: reading it settles the cipher's key
        # length by the firmware's checksum (24 bytes on every build seen),
        # where a key asked for cold is guessed from its shape and a wrong
        # guess packs a directory the game rejects (found building the first
        # bank of a Write, whose emulator had read nothing)
        MD.read_directory(_lp(img_path), emu)
        size = SB.write_bank(_lp(path), directory, places, scaffold, emu, stride)
    finally:
        if own:
            emu.close()
    log("Sound bank %s: %d sound(s) staged, %.1f MB (the game's %d MB limit is "
        "this bank's own)." % (SB.bank_name(cat), len(SB.records(places)), size / 1e6,
                                SB.MAX_BANK_BYTES // 10**6), "info")
    return path, places


# --------------------------------------------------------------------------
# the chain encode
# --------------------------------------------------------------------------
def chain_encode(gr_path, img_path, bank_path, cat, params, places, edits, np, log,
                 loops=(), gains=None, level_refs=None, progress=None, cancel=None,
                 revalidate=None, body_cache=None):
    """Encode *edits* (``{host idx: wav}``) into the staged bank at *bank_path*
    along the firmware's chain for category *cat*, and compose the bodies
    into the file.  *params* are ``image.bin``'s rows (the codec entries and
    loudness references come from its stock sounds); *places* the bank's
    :class:`.soundbank.BankPlacement` list.  *loops*, *gains* and
    *level_refs* are ``engine._chain_encode_appended``'s, keyed by host idx.
    Returns ``(rows, patches, revalidate)``: the bank's rows as the finished
    file derives them, each with ``host`` (its sound's idx in ``image.bin``)
    and the key it registers under, the ``{offset: body}`` written, and the
    map-revalidation stub the derive settled on (for :func:`verify_bank`)."""
    from . import engine as E
    from .spike2.category import CatEmu
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import BLOCK
    gains = gains or {}
    loops = set(loops or ())
    byidx = {p["idx"]: p for p in params}
    places = SB.records(places)
    by_new = {pl.new_idx: pl for pl in places}
    stock_rows = [p for p in params if not p.get("grown")]
    want = {pl.new_idx: pl.idx for pl in places if pl.idx in edits}
    if not want:
        return [], {}
    if progress:
        progress(0, 100, "Encoding the sounds of bank %s along the firmware's chain: "
                 "starting the firmware..." % SB.bank_name(cat))
    # A long sound's blocks go to workers (PAD-599, spike2.parallel); they
    # boot while the firmware below walks the bank's chain.
    from .spike2.parallel import start_block_pool
    pool = start_block_pool(
        "cat", gr_path, img_path, stock_rows, cat_file=bank_path, log=log,
        longest=max(int(by_new[n].length or 0) for n in want))
    emu_e = CatEmu(gr_path, img_path)
    emu_d = CatEmu(gr_path, img_path)
    patches, done, state = {}, [], {"gr": None, "sr": None}
    try:
        emu_e.boot()
        emu_d.boot()
        def render(idx, q):
            # a stock sound of image.bin's, decoded from image.bin's window
            was, emu_e.mm = emu_e.mm, emu_e._mm_img
            try:
                return E._stock_render(emu_e, q, np, stereo=byidx[idx].get("chan") == 2)
            finally:
                emu_e.mm = was

        # PAD-609: decoded only when an encode needs it (E._LazyRefs)
        refs = E._LazyRefs({idx: byidx[ref] for idx, ref in (level_refs or {}).items()
                            if byidx.get(ref) is not None and idx in edits}, render)
        emu_e.set_category_file(bank_path)

        def after(n, row, redo):
            idx = want.get(n)
            if idx is None:
                return None
            if cancel is not None and cancel():
                raise RuntimeError("cancelled")
            p = dict(row, host=idx, grown=True)
            # the codec entry for the record's (scale, chan), settled from a stock
            # sound of image.bin's -- never from the scaffold
            emu_e.mm = emu_e._mm_img
            emu_e.warm_slots_for_grown(stock_rows + [dict(p, idx=-1 - n)])
            emu_e.mm = emu_e._mm_cat
            if pool is not None:
                pool.warm(dict(p, idx=-1 - n))
            if p["chan"] == 2:
                state["sr"] = state["sr"] or StereoRecover(emu_e)
            else:
                state["gr"] = state["gr"] or GenRecover(emu_e)
            if not E._recovery_valid(emu_e, state["gr"], state["sr"], p, np):
                raise RuntimeError(
                    "idx %d: this sound's codec cannot re-encode bit-exact on bank %s's "
                    "chain parameters (scale %s)" % (idx, SB.bank_name(cat), p["scale"]))
            kw = dict(pred=None, log=log, gain_db=gains.get(idx), loop=idx in loops,
                      blocks=pool.blocks if pool is not None else None)
            pe = E._extended_row(p, E._APPENDED_TAIL)
            # *body_cache*: the same encode a build made before (PAD-599)
            off, body = E._chain_encoded(
                body_cache, SB.bank_name(cat), emu_e, pe, edits[idx],
                lambda: (E._encode_stereo(emu_e, state["sr"], pe, edits[idx], np,
                                          **refs.kw(idx, kw))
                         if p["chan"] == 2 else
                         E._encode_mono(emu_e, state["gr"], pe, edits[idx], np,
                                        **refs.kw(idx, kw))),
                gain_db=kw["gain_db"], loop=kw["loop"],
                ref=byidx.get((level_refs or {}).get(idx)) if idx in refs else None,
                chan=p["chan"])
            emu_d._ensure_range(emu_d.DESC2 + off, len(body))
            emu_d.mu.mem_write(emu_d.DESC2 + off, bytes(body))
            patches[off] = bytes(body)
            done.append(idx)
            if progress:
                progress(95 + int(len(done) * 5 / max(len(want), 1)), 100,
                         "Encoding the sounds of bank %s (%d of %d)..."
                         % (SB.bank_name(cat), len(done), len(want)))
            log("idx %d (bank %s record %d): encoded on the bank's chain parameters "
                "(scale %s), %s; its windows hold its own audio."
                % (idx, SB.bank_name(cat), n, p["scale"],
                   "a loop" if idx in loops else "%.2f s" % (
                       (p["length"] - BLOCK) / 44100.0)), "info")
            return redo()

        rows = emu_d.derive_bank(cat, bank_path, after_step=after, revalidate=revalidate)
        rev = emu_d._revalidate
    finally:
        if pool is not None:
            pool.close()
        emu_e.mm = emu_e._mm_img
        emu_e.close()
        emu_d.close()
    missing = sorted(set(want.values()) - set(done))
    if missing:
        raise RuntimeError("bank %s's chain never reached sound(s) %s"
                           % (SB.bank_name(cat), missing))
    for r in rows:
        pl = by_new.get(r["idx"])
        r["host"] = pl.idx if pl is not None else None
        r["grown"] = True
        if not r.get("findkey"):
            raise RuntimeError("bank %s record %d registered no container key, so no mode "
                               "could swap it in" % (SB.bank_name(cat), r["idx"]))
    with open(_lp(bank_path), "r+b") as f:
        for off, body in patches.items():
            f.seek(off)
            f.write(body)
    log("Sound bank %s: %d sound(s) encoded along the firmware's chain and composed "
        "into the file (%.1f MB)." % (SB.bank_name(cat), len(done),
                                       os.path.getsize(_lp(bank_path)) / 1e6), "info")
    return rows, patches, rev


# --------------------------------------------------------------------------
# every bank of a Write, side by side (PAD-609)
# --------------------------------------------------------------------------
#: ``PAD_STERN_BANK_WORKERS``: how many banks are encoded at once (1 = one after
#: another, in this process, as before PAD-609).
BANK_WORKERS_ENV = "PAD_STERN_BANK_WORKERS"


@dataclass
class BankJob:
    """One bank of :func:`encode_banks`: category *cat*'s staged file at *path*,
    its :class:`.soundbank.BankPlacement` list and ``{host idx: wav}``."""
    cat: int
    path: str
    places: list
    wavs: dict


def bank_workers(n_banks, first_too=False):
    """How many banks :func:`encode_banks` encodes at once: one per four cores
    (each bank's long sounds have block workers of their own), at most the banks
    after the first (*first_too*: at most all of them); :data:`BANK_WORKERS_ENV`
    overrides it."""
    most = n_banks if first_too else n_banks - 1
    v = os.environ.get(BANK_WORKERS_ENV, "")
    try:
        if v.strip():
            return max(1, min(int(v), max(1, most)))
    except ValueError:
        pass
    return max(1, min((os.cpu_count() or 1) // 4, most))


def encode_and_verify(gr_path, img_path, job, params, np, log, loops=(), gains=None,
                      level_refs=None, progress=None, cancel=None, revalidate=None,
                      body_cache=None):
    """:func:`chain_encode` then :func:`verify_bank` for one :class:`BankJob`;
    returns ``(rows, revalidate)`` (the chain's rows, which carry each
    record's host sound)."""
    rows, _patches, rev = chain_encode(
        gr_path, img_path, job.path, job.cat, params, job.places, job.wavs, np, log,
        loops=set(loops or ()) & set(job.wavs), gains=gains, level_refs=level_refs,
        progress=progress, cancel=cancel, revalidate=revalidate, body_cache=body_cache)
    # the check derives the finished file afresh
    verify_bank(gr_path, img_path, job.path, job.cat, rows, log, revalidate=rev)
    return rows, rev


def _bank_worker(task):
    """A worker of :func:`encode_banks`: one bank, its log lines held and
    handed back whole (the parent says them in bank order).  A cancel is the
    parent's flag file appearing."""
    (gr_path, img_path, job, params, loops, gains, level_refs, revalidate, body_cache,
     flag, blocks) = task
    import numpy as np
    if blocks is not None:
        os.environ["PAD_STERN_BLOCK_WORKERS"] = str(blocks)
    lines = []
    if body_cache is not None:
        # what this bank used, handed back for the parent's cache to keep
        import copy
        body_cache = copy.copy(body_cache)
        body_cache.used, body_cache.hits = set(), 0
    try:
        rows, rev = encode_and_verify(
            gr_path, img_path, job, params, np,
            lambda m, lv="info", *_a, **_k: lines.append((m, lv)),
            loops=loops, gains=gains, level_refs=level_refs,
            cancel=lambda: os.path.exists(flag), revalidate=revalidate,
            body_cache=body_cache)
    except Exception as e:                              # noqa: BLE001
        return ("error", (type(e).__name__, str(e)), lines, None)
    used = (body_cache.used, body_cache.hits) if body_cache is not None else None
    return ("ok", (rows, rev), lines, used)


def encode_banks(gr_path, img_path, jobs, params, np, log, loops=(), gains=None,
                 level_refs=None, progress=None, cancel=None, body_cache=None):
    """``[(rows, revalidate), ...]``: :func:`encode_and_verify` for every
    :class:`BankJob` of *jobs*, in order.

    The first bank is encoded here: its derive settles the firmware's
    map-revalidation stub, which every later bank's derive is then handed.
    Those are encoded side by side in worker processes (:func:`bank_workers`),
    each its own file, its own emulators and its own share of the cores for
    its long sounds' blocks; their log lines are said in bank order as they
    come back.  A Godzilla build with 11 modes' music had them one after
    another: 11 banks, 5 to 30 s each.  A worker's failure stops the Write
    with the bank's own words, as it would have here; a pool that cannot
    start leaves the rest to be encoded here.

    A game program with one candidate for that stub has nothing to settle,
    so every bank goes to the workers at once (PAD-609: the first bank of a
    Godzilla build was a minute on its own before the others started)."""
    from .engine import _span
    out = []
    n = len(jobs)

    def span(i):
        return _span(progress, int(100 * i / n), int(100 * (i + 1) / n))
    if not jobs:
        return out
    w = bank_workers(n, first_too=True)
    rev = known_revalidate(gr_path, img_path) if w > 1 else None
    if rev is not None:
        got = _encode_banks_parallel(gr_path, img_path, jobs, params, log, loops, gains,
                                     level_refs, progress, cancel, body_cache, rev, w, n,
                                     done0=0)
        if got is not None:
            return got
    rows, rev = encode_and_verify(gr_path, img_path, jobs[0], params, np, log, loops=loops,
                                  gains=gains, level_refs=level_refs, progress=span(0),
                                  cancel=cancel, body_cache=body_cache)
    out.append((rows, rev))
    rest = jobs[1:]
    w = bank_workers(n)
    got = None
    if w > 1 and len(rest) > 1:
        got = _encode_banks_parallel(gr_path, img_path, rest, params, log, loops, gains,
                                     level_refs, progress, cancel, body_cache, rev, w, n)
    if got is not None:
        return out + got
    for i, job in enumerate(rest, 1):
        out.append(encode_and_verify(gr_path, img_path, job, params, np, log, loops=loops,
                                     gains=gains, level_refs=level_refs, progress=span(i),
                                     cancel=cancel, revalidate=rev, body_cache=body_cache))
    return out


def _job_bytes(job):
    """How much audio a :class:`BankJob` encodes, by its sounds' file sizes."""
    n = 0
    for wav in (job.wavs or {}).values():
        try:
            n += os.path.getsize(wav)
        except (OSError, TypeError):
            pass
    return n


def known_revalidate(gr_path, img_path):
    """The game program's map-revalidation stub when it has only one
    candidate for it (a derive would settle on that one or fail), else None:
    several candidates, or a loader that cannot be analysed."""
    try:
        from .spike2.category import CatEmu
        emu = CatEmu(gr_path, img_path)
        try:
            cands = list((emu._cat_locs or {}).get("REVALIDATE_CANDIDATES") or ())
        finally:
            emu.close()
    except Exception:                                   # noqa: BLE001
        return None
    return cands[0] if len(cands) == 1 else None


def _encode_banks_parallel(gr_path, img_path, jobs, params, log, loops, gains, level_refs,
                           progress, cancel, body_cache, rev, workers, n_all, done0=1):
    """:func:`encode_banks`' workers; None when the pool could not start (the
    caller encodes the banks itself).  *done0*: the banks already encoded
    before these (the first, here)."""
    import multiprocessing as mp
    import tempfile
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    from .spike2.parallel import block_workers, emulator_commit, emulators_that_fit
    # PAD-609: a worker runs two emulators and its block workers, each committing
    # its share of memory; the workers and their blocks are as many as fit
    per = max(emulator_commit(img_path, j.path) for j in jobs)
    room = emulators_that_fit(per, workers * (2 + block_workers()))
    if room // 2 < workers:
        log("Sound banks: %d at a time, not %d: this computer has room for the "
            "memory of %d sound encoder(s) now." % (max(1, room // 2), workers, room), "info")
        workers = room // 2
        if workers < 2:
            return None
    # the cores shared out: a worker's long sounds take its share for their blocks
    blocks = min(max(0, (os.cpu_count() or 1) // workers - 1), block_workers(),
                 room // workers - 2)
    if blocks < 2:
        blocks = 0
    fd, flag = tempfile.mkstemp(prefix="spike2_bankcancel_")
    os.close(fd)
    os.remove(flag)
    log("Sound banks %s: encoded %d at a time, each in a worker of its own." % (
        ", ".join(SB.bank_name(j.cat) for j in jobs), workers), "info")
    results = [None] * len(jobs)
    said = 0
    pool = None
    try:
        try:
            pool = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"))
            # the biggest banks first, so no worker is left with a long one at
            # the end; their lines are still said in bank order
            futs = {pool.submit(_bank_worker, (gr_path, img_path, jobs[i], params,
                                               set(loops or ()), gains, level_refs, rev,
                                               body_cache, flag, blocks)): i
                    for i in sorted(range(len(jobs)), key=lambda i: -_job_bytes(jobs[i]))}
        except Exception as e:                          # noqa: BLE001
            log("Sound banks are encoded one after another: the workers did not start "
                "(%s)." % e, "info")
            return None
        pending = set(futs)
        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if cancel is not None and cancel():
                open(flag, "w").close()
            for f in done:
                try:
                    results[futs[f]] = f.result()
                except Exception as e:                  # noqa: BLE001
                    results[futs[f]] = ("error", ("RuntimeError", "sound bank %s's worker "
                                                  "stopped (%s)" % (SB.bank_name(
                                                      jobs[futs[f]].cat), e)), [], None)
            # the log lines of every bank done so far, in bank order
            while said < len(jobs) and results[said] is not None:
                tag, val, lines, used = results[said]
                for m, lv in lines:
                    log(m, lv)
                if tag != "ok":
                    open(flag, "w").close()
                    raise RuntimeError(val[1])
                if used is not None and body_cache is not None:
                    body_cache.used |= used[0]
                    body_cache.hits += used[1]
                said += 1
                if progress:
                    progress(int(100 * (said + done0) / n_all), 100,
                             "Encoding the modes' sound banks (%d of %d)..."
                             % (said + done0, n_all))
        return [r[1] for r in results]
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        try:
            os.remove(flag)
        except OSError:
            pass


# --------------------------------------------------------------------------
# the finished bank
# --------------------------------------------------------------------------
def verify_bank(gr_path, img_path, bank_path, cat, rows, log, revalidate=None):
    """Derive the finished bank again on a fresh emulator and compare: every
    record's codec object and container key must be the chain's.  Raises
    rather than let a bank the game would decode differently reach a card."""
    from .spike2.category import CatEmu
    emu = CatEmu(gr_path, img_path)
    try:
        emu.boot()
        got = emu.derive_bank(cat, bank_path, revalidate=revalidate)
    finally:
        emu.close()
    if len(got) != len(rows):
        raise RuntimeError("bank %s: the finished file derives %d record(s) where %d were "
                           "encoded" % (SB.bank_name(cat), len(got), len(rows)))
    for a, b in zip(rows, got):
        if (a.get("_rawobj") or b"")[:0x20] != (b.get("_rawobj") or b"")[:0x20] \
                or a.get("findkey") != b.get("findkey"):
            raise RuntimeError(
                "bank %s record %d: the finished file derives other codec parameters or "
                "another key than it was encoded with; aborting rather than shipping a "
                "bank whose sounds would play as noise" % (SB.bank_name(cat), a["idx"]))
    log("Sound bank %s verified: all %d record(s) derive the parameters and keys they "
        "were encoded with." % (SB.bank_name(cat), len(got)), "success")
    return got


def key_hex(row):
    """A bank row's container key as the mode file carries it."""
    return bytes(row["findkey"]).hex()


def image_header_writes(img_path, cats):
    """``{offset: bytes}`` naming the new categories *cats* in ``image.bin``'s
    header (:func:`.soundbank.header_writes_new_categories`)."""
    with open(_lp(img_path), "rb") as f:
        head = f.read(0x200)
    return SB.header_writes_new_categories(head, cats)


def category_ids_free(img_path, bank_names, n):
    """The *n* category ids a new bank may take on this card: not in
    ``image.bin``'s list and not a bank file already in the game's directory."""
    with open(_lp(img_path), "rb") as f:
        _count, ids, _room = SB.category_slots(f.read(0x200))
    return SB.next_category_ids(ids, bank_names, n)



# --------------------------------------------------------------------------
# the play tables: a sid of the bank's category for every sound
# --------------------------------------------------------------------------
#: How many cat-0 sids :func:`resolver_rule` reads to measure the keystream
#: rule; the mask's bits all show within a few hundred.
RULE_SIDS = 1200


def resolver_rule(emu, resolver, out, img_path, limit=RULE_SIDS):
    """``(mask, xor)``: the game's rule for a descriptor's keystream offset,
    ``ks = (desc_off ^ xor) & mask``, measured on this build's own cat-0 sids
    through its resolver (*emu* booted, *resolver*/*out* from
    :func:`.sfx_names._find_resolver`).  Godzilla LE 1.16 has ``off & 0x2a6``,
    Deadpool LE 1.16 ``(off ^ 0xb8162db5) & 0xb95``; read off the resolver
    rather than its code so a build with other constants measures its own.
    Raises when the sids do not agree on one rule."""
    from .spike2 import sfx_names as SN
    pairs = []
    ceiling = min(SN.sid_ceiling(_lp(img_path)), limit)
    for sid in range(ceiling):
        emu.mu.mem_write(out, b"\x00" * 0x40)
        st = emu.call(resolver, (sid, out), limit=5_000_000)
        if st[0] != "ok" or not (SN.IMG_BASE <= st[1] < SN.IMG_BASE + emu.imgsize):
            continue
        ks = struct.unpack("<I", bytes(emu.mu.mem_read(out, 4)))[0] - emu.VF2_VA
        if not 0 <= ks < SB.VF2_WINDOW:
            continue
        pairs.append((st[1] - SN.IMG_BASE, ks))
    if len(pairs) < 50:
        raise RuntimeError("the game's resolver answered for %d sound id(s), too few to measure "
                           "its keystream rule" % len(pairs))
    mask = 0
    for _off, ks in pairs:
        mask |= ks
    xors = {(off ^ ks) & mask for off, ks in pairs}
    if len(xors) != 1:
        raise RuntimeError("the game's resolver does not derive a descriptor's keystream offset "
                           "from its offset by one rule (%d seen over %d sound ids)"
                           % (len(xors), len(pairs)))
    xor = xors.pop()
    bad = [off for off, ks in pairs if ((off ^ xor) & mask) != ks]
    if bad:
        raise RuntimeError("keystream rule mismatch on %d sound id(s)" % len(bad))
    return mask, xor


def compose_descriptor(template, key8, duration, music):
    """A bank descriptor: *template* (a carrier's de-whitened descriptor
    bytes) with its first op11 record key replaced by *key8* (the bank
    record's own key) and its declared duration by *duration* (1/4000 s
    units).  A music bed's template must be a looping music descriptor, as
    :func:`engine._music_template_writes` demands of a bed's carrier."""
    from . import engine as E
    t = bytes(template)
    ops = E._op11_payloads(t)
    if not ops:
        raise RuntimeError("the carrier's descriptor names no record (%s)" % t[:24].hex())
    p = ops[0][0]
    if music and t[p + 8:p + 12] != E._MUSIC_LOOP_TAIL:
        raise RuntimeError("the music carrier's descriptor is not a looping music one (%s)"
                           % t[:40].hex())
    plain = bytearray(t)
    plain[p:p + 8] = bytes(key8)
    plain[E._DESC_DUR_OFF:E._DESC_DUR_OFF + 4] = struct.pack("<I", int(duration) & 0xFFFFFFFF)
    return bytes(plain)


def write_bank_tables(gr_path, img_path, bank_path, cat, places, rows, carriers, durations,
                      music_idx, log, stride=None, given=None, desc_slot=SB.DESC_SLOT):
    """Write the fragment table and the descriptors into the staged bank for
    the records *rows* (the chain's, with ``host`` and ``findkey``):
    placement *n*'s descriptor is a copy of its carrier's (*carriers*
    ``{host idx: carrier sid}``, resolved through the game's resolver) naming
    the bank record's key and declaring *durations[host idx]*; hosts in
    *music_idx* are looping beds.  PAD-608: *given* ``{new_idx: plain
    descriptor}`` are fragments whose descriptor the caller wrote (a music
    mode's file: the game sound id's own, naming the bank record), every
    fragment past the records among them.  PAD-779: *desc_slot* the bank's room a
    descriptor (:func:`.soundbank.plan_bank`).  Returns ``{new_idx: (sid, plain,
    ks)}`` for :func:`verify_tables`."""
    from .spike2 import sfx_names as SN
    from .spike2.emulator import Spike2Emu
    if stride is None:
        with open(_lp(img_path), "rb") as f:
            stride = SB.fragment_stride(f.read(0x100))
    by_new = {r["idx"]: r for r in rows}
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        resolver, out = SN._find_resolver(emu)
        if resolver is None:
            raise RuntimeError("the game's descriptor resolver could not be located, so the sound "
                               "bank's play tables cannot be written")
        mask, xor = resolver_rule(emu, resolver, out, img_path)
        vf2 = bytes(emu.mu.mem_read(emu.VF2_VA, SB.VF2_WINDOW + max(SB.DESC_SLOT,
                                                                    int(desc_slot))))
        descs = {n: bytes(d) for n, d in (given or {}).items()}
        for pl in places:
            if pl.new_idx in descs:
                continue
            r = by_new[pl.new_idx]
            csid = carriers[pl.idx]
            got = SN.resolve_descriptor(emu, resolver, out, csid)
            if got is None:
                raise RuntimeError("sound id %d (the carrier of the sound in bank record %d) has no "
                                   "descriptor to copy" % (csid, pl.new_idx))
            descs[pl.new_idx] = compose_descriptor(got[2], r["findkey"], durations[pl.idx],
                                                   pl.idx in music_idx)
    finally:
        emu.close()
    ks_by = SB.write_tables(_lp(bank_path), places, descs, vf2,
                            lambda off: (off ^ xor) & mask, stride, desc_slot=desc_slot)
    log("Sound bank %s: %d fragment(s) and descriptor(s) written (keystream rule mask %#x xor "
        "%#x, %d slot(s) a fragment)." % (SB.bank_name(cat), len(places), mask, xor, stride), "info")
    out_map = {pl.new_idx: (SB.bank_sid(cat, pl.new_idx), descs[pl.new_idx], ks_by[pl.new_idx])
               for pl in places}
    # the resolver's address and its answer buffer, for verify_tables: found
    # here on the plain emulator (the probe that finds it can fail on the bank
    # emulator after a big derive, where the resolver itself still runs)
    out_map["resolver"] = (resolver, out)
    return out_map


def verify_tables(gr_path, img_path, bank_path, cat, places, expect, rows, log, revalidate=None):
    """Resolve every bank sid through the game's own resolver with the
    finished bank loaded and registered by the game's own loader (a fresh
    :class:`CatEmu`, :meth:`~.category.CatEmu.register_bank`): the descriptor must
    be ours, at our offset, whitened at the keystream offset we derived, and
    its key the record's.  Raises otherwise."""
    from .spike2 import sfx_names as SN
    from .spike2.category import CatEmu
    from . import engine as E
    by_new = {r["idx"]: r for r in rows}
    resolver, out = expect.get("resolver", (None, None))
    emu = CatEmu(gr_path, img_path)
    try:
        emu.boot()
        # the game's loader alone (the records were derived by verify_bank):
        # a full derive of a bank with real audio left the emulator unable
        # to run the resolver afterwards
        n = emu.register_bank(cat, bank_path, revalidate=revalidate)
        if n != len(SB.records(places)):
            raise RuntimeError("bank %s registers %d record(s), not %d" % (
                SB.bank_name(cat), n, len(SB.records(places))))
        if resolver is None:
            resolver, out = SN._find_resolver(emu)
        if resolver is None:
            raise RuntimeError("the game's descriptor resolver could not be located on the finished "
                               "bank")
        out = emu.alloc(0x40)        # this emulator's own answer buffer
        d2 = emu.DESC2
        for pl in places:
            sid, plain, ks = expect[pl.new_idx]
            emu.mu.mem_write(out, b"\x00" * 0x40)
            st = emu.call(resolver, (sid, out), limit=5_000_000)
            d = st[1] if st[0] == "ok" else None
            if d != d2 + pl.desc_off:
                raise RuntimeError("sound id %#x does not resolve to its descriptor in bank %s "
                                   "(got %s, wanted bank+%#x; %s)" % (
                                       sid, SB.bank_name(cat), hex(d) if d else st[0], pl.desc_off,
                                       st[1:] if st[0] != "ok" else ""))
            got_ks = struct.unpack("<I", bytes(emu.mu.mem_read(out, 4)))[0] - emu.VF2_VA
            if got_ks != ks:
                raise RuntimeError("sound id %#x: the resolver whitens its descriptor at %#x, not "
                                   "the %#x it was written with" % (sid, got_ks, ks))
            with open(_lp(bank_path), "rb") as f:
                f.seek(pl.desc_off)
                raw = f.read(len(plain))
            vf2 = bytes(emu.mu.mem_read(emu.VF2_VA + ks, len(plain)))
            back = bytes(a ^ b for a, b in zip(raw, vf2))
            if back != plain:
                raise RuntimeError("sound id %#x: its descriptor does not read back as written" % sid)
            ops = E._op11_payloads(back)
            key = bytes(by_new[SB.record_of(pl)]["findkey"])
            if not ops or bytes(ops[0][1]) != key:
                raise RuntimeError("sound id %#x: its descriptor names key %s, the record's is %s" % (
                    sid, ops[0][1].hex() if ops else "none", key.hex()))
    finally:
        emu.close()
    log("Sound bank %s: every one of its %d sound id(s) resolves through the game's own resolver "
        "to its descriptor and its record." % (SB.bank_name(cat), len(places)), "success")


# --------------------------------------------------------------------------
# PAD-606: the game's own sounds in a bank
# --------------------------------------------------------------------------
# A longer replacement of one of the game's own sounds reaches its record through the
# descriptor of the sid that plays it, and a cat-0 sid's descriptor can only name an
# image.bin record (the key's category bits come from the sid).  So a game sound that goes
# into a bank gets a sid of the bank's category, as a mode's own sound does, and the game is
# made to play THAT: the sid lists of the game's request table (``spike2.sound_requests``),
# which the play worker reads at every play, name the bank sid where they named the game's.
# That is how the music titles play their own banks' songs: their request lists carry the
# songs' ``cat << 16 | n`` sids.

#: Longest sid list :func:`request_list_slots` follows, a runaway guard: the walk stops at
#: the list's zero (it was 256, and 16 titles have longer lists: PAD-635); the same
#: bound as ``spike2.sound_requests.LIST_MAX``.
_LIST_MAX = 1 << 16


def request_list_slots(elf, head):
    """``{sid: [file offsets]}``: every place the game's request table's sid lists (in
    the game ELF *elf*; *head* is image.bin's header, for its fragment count) name a sid.
    ``{}`` when the table cannot be found."""
    from .info import container_counts
    from .spike2 import sound_requests as SR
    from .spike2.elf import parse_elf
    counts = container_counts(head)
    fragments = counts[0] if isinstance(counts, tuple) else counts.get("fragments")
    count, table = SR.locate_sound_requests(elf, fragments)
    if table is None or not count:
        return {}
    segs, _r = parse_elf(elf)

    def va2off(va):
        for vaddr, foff, filesz, _m in segs:
            if vaddr <= va < vaddr + filesz:
                return foff + va - vaddr
        return None

    out, seen = {}, set()
    for r in range(int(count)):
        for w in struct.unpack_from("<5I", elf, table + r * 20):
            o = va2off(w) if w else None
            if o is None or o <= table:
                continue
            # the first word that points past the record array is the list
            # (mode_write.request_sids reads it the same way)
            if o not in seen:
                seen.add(o)
                for i in range(_LIST_MAX):
                    at = o + 4 * i
                    if at + 4 > len(elf):
                        break
                    (sid,) = struct.unpack_from("<I", elf, at)
                    if sid == 0:
                        break
                    out.setdefault(sid, []).append(at)
            break
    return out


def stock_slots(slots, old_map):
    """*slots* (:func:`request_list_slots`) keyed by the GAME's sid: a bank sid an
    earlier Write put in a list (*old_map* ``{bank sid: game sid}``, the card's banks'
    sid maps) counts as the sid it stands in for."""
    out = {}
    for sid, offs in slots.items():
        out.setdefault(old_map.get(sid, sid), []).extend(offs)
    return out


def game_sound_sids(grows, byidx, sites, mask, slots, exclude=()):
    """``(ok, why)``: of the user's longer replacements *grows* (``{idx: (room,
    want)}``), ``ok`` ``{idx: sid}`` the ones a bank can hold, each with the game sid that
    plays it, and ``why`` ``{idx: reason}`` for the rest.  A sound can move when exactly
    one sid of the game's plays it (*sites*, the card's descriptor sites; *mask* its key
    mask), that sid's descriptor names nothing else, a request list names the sid
    (*slots*, :func:`stock_slots`), and it is not one a mode of this Write uses
    (*exclude*)."""
    from . import engine as E
    exclude = {int(s) for s in exclude or ()}
    by_key, sid_sites = {}, {}
    for s in sites:
        sid_sites.setdefault(s.sid, []).append(s)
        by_key.setdefault(E._play_key(s.payload, s.sid, mask), set()).add(s.sid)
    ok, why = {}, {}
    for idx in sorted(grows):
        key = (byidx.get(idx) or {}).get("findkey")
        sids = sorted(by_key.get(bytes(key), ())) if key else []
        if len(sids) != 1:
            why[idx] = ("%d of the game's sound ids play it" % len(sids) if sids
                        else "no sound id of the game's plays it")
            continue
        sid = sids[0]
        if len(sid_sites[sid]) != 1:
            why[idx] = "sound id %d plays it as one of %d parts" % (sid, len(sid_sites[sid]))
        elif sid >> 16:
            why[idx] = "sound id %d is already in a sound bank of the game's" % sid
        elif sid in exclude:
            why[idx] = "sound id %d is one a mode of this card plays" % sid
        elif not slots.get(sid):
            why[idx] = "the game plays sound id %d other than through its sound requests" % sid
        else:
            ok[idx] = sid
    return ok, why


#: PAD-779: a song in parts a bank can hold: the user's longer replacements *grown* (idxs) of
#: its records, every sound id of the game's that plays one of them, *sids* ``{sid: [idx, ...]}``
#: in its descriptor's order, *descs* ``{sid: plain descriptor}`` (the resolver's, through its
#: own end), and *parts* every record those name, in order (the stock ones are copied).
SeqGroup = collections.namedtuple("SeqGroup", "grown sids descs parts")


def game_sound_groups(grows, byidx, wide, slots, exclude=(), busy=()):
    """PAD-779: ``(groups, why)`` - the user's longer replacements *grows* (``{idx: (room,
    want)}``) that the game plays in parts, as :class:`SeqGroup` s a bank can hold, and ``why``
    ``{idx: reason}`` for the ones it cannot.  Iron Maiden plays its songs as intro, song and
    outro sequences and medleys, each a sound id whose descriptor names several records: such
    a song moves only with every sound id that plays it, and every record those name goes into
    the same bank (a bank sound id's descriptor can only name records of its own bank).  Songs
    that share a sound id (a medley) are one group.  *wide* ``{sid: (descriptor, [idx or
    None, ...])}`` is every sound id's descriptor through its own end and the records it plays
    (:func:`.engine._wide_descriptors`); *slots*, *exclude* as :func:`game_sound_sids`;
    *busy* the idxs this Write gives other sounds (a mode's, a music mode's file), which can't
    be copied as a part.  A sound one sound id plays alone is :func:`game_sound_sids`'s, not
    a group."""
    from .spike2.emulator import bands_of
    exclude = {int(x) for x in exclude or ()}
    busy = {int(x) for x in busy or ()}
    plays_of = {}
    for sid, (_d, idxs) in wide.items():
        for i in idxs:
            if i is not None:
                plays_of.setdefault(i, set()).add(sid)
    groups, why, seen = [], {}, set()
    for x in sorted(grows):
        if x in seen:
            continue
        grown, sids, todo = {x}, set(), [x]
        while todo:
            for sid in sorted(plays_of.get(todo.pop(), ())):
                if sid in sids:
                    continue
                sids.add(sid)
                for j in wide[sid][1]:
                    if j in grows and j not in grown:
                        grown.add(j)
                        todo.append(j)
        seen |= grown
        if len(sids) == 1 and wide[next(iter(sids))][1] == [x]:
            continue
        parts = []
        for sid in sorted(sids):
            parts.extend(j for j in wide[sid][1] if j not in parts)
        bad = None if sids else "no sound id of the game's plays it"
        for sid in sorted(sids):
            desc, idxs = wide[sid]
            if sid >> 16:
                bad = "sound id %d is already in a sound bank of the game's" % sid
            elif sid in exclude:
                bad = "sound id %d is one a mode of this card plays" % sid
            elif not slots.get(sid):
                bad = "the game plays sound id %d other than through its sound requests" % sid
            elif None in idxs:
                bad = "sound id %d plays a record the card's directory does not name" % sid
            elif len(desc) > SB.DESC_SLOT_MAX:
                bad = ("sound id %d's script is %d bytes, longer than a sound bank's can be (%d)"
                       % (sid, len(desc), SB.DESC_SLOT_MAX))
            if bad:
                break
        for j in parts:
            if bad:
                break
            if j not in grown and j in busy:
                bad = "sound idx %d, one of its parts, plays another sound in this Write" % j
            elif j not in byidx or bands_of(byidx[j]) > 1:
                bad = "sound idx %d, one of its parts, is a record of several variants" % j
        if bad:
            for j in grown:
                why[j] = bad
            continue
        groups.append(SeqGroup(sorted(grown), {s: list(wide[s][1]) for s in sorted(sids)},
                               {s: bytes(wide[s][0]) for s in sorted(sids)}, parts))
    return groups, why


def seq_fragments(group):
    """PAD-779: ``(own, aliases)`` for *group*'s fragments: ``own`` ``{record idx: sid}`` the
    sound id whose descriptor a record's own fragment takes (one that opens with it, the one
    that plays it alone first), ``aliases`` ``[(sid, record idx)]`` the rest, each a fragment
    past the records playing from its first record.  A record no sound id opens with gets a
    descriptor nothing plays (its fragment has to resolve)."""
    own, aliases = {}, []
    for sid, idxs in sorted(group.sids.items(), key=lambda kv: (len(kv[1]) > 1, kv[0])):
        if idxs[0] not in own:
            own[idxs[0]] = sid
        else:
            aliases.append((sid, idxs[0]))
    return own, aliases


def seq_descriptor(desc, sid, keys, moves, mask):
    """PAD-779: sound id *sid*'s descriptor *desc* (through its own end) as a bank's: every
    op11 payload naming one of *keys* ``{play key: bank record key}`` names the bank record's
    key verbatim (:func:`compose_descriptor`), and its declared duration moves by *moves*
    ``{play key: 1/4000 s}`` for each payload of that record.  Raises when a payload names a
    record not in *keys*: a bank sound id's descriptor can only name its own bank's."""
    from . import engine as E
    d = bytearray(desc)
    moved = 0
    pls = E._op11_payloads(bytes(d))
    if not pls:
        raise RuntimeError("sound id %d's descriptor names no record" % sid)
    for off, pl in pls:
        k = E._play_key(pl, sid, mask)
        if k not in keys:
            raise RuntimeError("sound id %d's descriptor names a record outside its sound bank"
                               % sid)
        d[off:off + 8] = bytes(keys[k])
        moved += int(moves.get(k, 0))
    dur = struct.unpack_from("<I", d, E._DESC_DUR_OFF)[0]
    struct.pack_into("<I", d, E._DESC_DUR_OFF, max(1, dur + moved) & 0xFFFFFFFF)
    return bytes(d)


def list_writes(slots, old_map, new_map):
    """``{file offset: u32 bytes}``: the request lists as this Write wants them, against
    *slots* (:func:`request_list_slots` of the game ELF the writes go into, keyed by the
    sid each place holds now).  A place an earlier Write gave a bank sid (*old_map*) goes
    back to the game's sid, and a game sid this Write put in a bank (*new_map* ``{game
    sid: bank sid}``) takes the bank's."""
    out = {}
    for sid, offs in slots.items():
        want = old_map.get(sid, sid)
        want = new_map.get(want, want)
        if want != sid:
            for o in offs:
                out[o] = struct.pack("<I", want & 0xFFFFFFFF)
    return out


def card_sid_map(reader):
    """``{bank sid: game sid}`` over the sound banks on the card *reader* reads: the
    game sounds an earlier Write moved into banks of this app's (their sid maps,
    :func:`.soundbank.read_sid_map_at`).  ``{}`` when there are none."""
    out = {}
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        cat = SB.category_of(path.rsplit("/", 1)[-1])
        if cat is None:
            continue
        got = SB.read_sid_map_at(lambda off, n, _node=node: reader.read_range(_node, off, n),
                                 int(node["size"]))
        for k, sid in got.items():
            out[SB.bank_sid(cat, k)] = int(sid)
    return out
