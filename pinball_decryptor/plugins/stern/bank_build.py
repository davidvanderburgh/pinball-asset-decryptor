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
import os
import struct

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
    (room, want)}``) in idx order: each sound's host record out of *directory*
    (``image.bin``'s), its length and the body its longer copy takes.  A host
    an earlier build already grew plays its appended record (``shadows``), the
    one *byidx* describes, so that is the record copied (PAD-593)."""
    from . import engine as E
    from .spike2.emulator import BLOCK
    out = []
    for idx in sorted(spilled):
        _room, want = spilled[idx]
        p = byidx[idx]
        src = idx if p.get("shadows") is None else int(p["shadows"])
        out.append(SB.BankEdit(idx, directory.record(src), int(p["length"]),
                               int(want) + BLOCK, E._grown_body_bytes(p, want)))
    return out


# --------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------
def stage_bank(gr_path, img_path, work, byidx, edits, cat, log, emu=None, stride=None):
    """Write the bank for category *cat* holding *edits* into *work* and return
    ``(path, places)``.  Each body starts as the host's stock audio repeated
    to fill; *emu* is a booted emulator on the card's program (one is made
    when None)."""
    from .spike2.emulator import Spike2Emu
    if stride is None:
        with open(_lp(img_path), "rb") as f:
            stride = SB.fragment_stride(f.read(0x100))
    directory, places = SB.plan_bank(edits, stride)
    scaffold = {}
    with open(_lp(img_path), "rb") as f:
        for pl in places:
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
        "this bank's own)." % (SB.bank_name(cat), len(places), size / 1e6,
                                SB.MAX_BANK_BYTES // 10**6), "info")
    return path, places


# --------------------------------------------------------------------------
# the chain encode
# --------------------------------------------------------------------------
def chain_encode(gr_path, img_path, bank_path, cat, params, places, edits, np, log,
                 loops=(), gains=None, level_refs=None, progress=None, cancel=None,
                 revalidate=None):
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
    by_new = {pl.new_idx: pl for pl in places}
    stock_rows = [p for p in params if not p.get("grown")]
    want = {pl.new_idx: pl.idx for pl in places if pl.idx in edits}
    if not want:
        return [], {}
    if progress:
        progress(0, 100, "Encoding the sounds of bank %s along the firmware's chain: "
                 "starting the firmware..." % SB.bank_name(cat))
    emu_e = CatEmu(gr_path, img_path)
    emu_d = CatEmu(gr_path, img_path)
    patches, done, state = {}, [], {"gr": None, "sr": None}
    try:
        emu_e.boot()
        emu_d.boot()
        refs = {}
        for idx, ref in (level_refs or {}).items():
            q = byidx.get(ref)
            if q is not None and idx in edits:
                refs[idx] = E._stock_render(emu_e, q, np, stereo=byidx[idx].get("chan") == 2)
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
            if p["chan"] == 2:
                state["sr"] = state["sr"] or StereoRecover(emu_e)
            else:
                state["gr"] = state["gr"] or GenRecover(emu_e)
            if not E._recovery_valid(emu_e, state["gr"], state["sr"], p, np):
                raise RuntimeError(
                    "idx %d: this sound's codec cannot re-encode bit-exact on bank %s's "
                    "chain parameters (scale %s)" % (idx, SB.bank_name(cat), p["scale"]))
            kw = dict(pred=None, log=log, gain_db=gains.get(idx), loop=idx in loops)
            if idx in refs:
                kw["orig"] = refs[idx]
            pe = E._extended_row(p, E._APPENDED_TAIL)
            off, body = (E._encode_stereo(emu_e, state["sr"], pe, edits[idx], np, **kw)
                         if p["chan"] == 2 else
                         E._encode_mono(emu_e, state["gr"], pe, edits[idx], np, **kw))
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
                      music_idx, log, stride=None):
    """Write the fragment table and the descriptors into the staged bank for
    the records *rows* (the chain's, with ``host`` and ``findkey``):
    placement *n*'s descriptor is a copy of its carrier's (*carriers*
    ``{host idx: carrier sid}``, resolved through the game's resolver) naming
    the bank record's key and declaring *durations[host idx]*; hosts in
    *music_idx* are looping beds.  Returns ``{new_idx: (sid, plain, ks)}``
    for :func:`verify_tables`."""
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
        vf2 = bytes(emu.mu.mem_read(emu.VF2_VA, SB.VF2_WINDOW + SB.DESC_SLOT))
        descs = {}
        for pl in places:
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
                            lambda off: (off ^ xor) & mask, stride)
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
    finished bank registered (a fresh :class:`CatEmu`): the descriptor must
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
        got_rows = emu.derive_bank(cat, bank_path, revalidate=revalidate)
        if len(got_rows) != len(places):
            raise RuntimeError("bank %s registers %d record(s), not %d" % (
                SB.bank_name(cat), len(got_rows), len(places)))
        if resolver is None:
            resolver, out = SN._find_resolver(emu)
        if resolver is None:
            raise RuntimeError("the game's descriptor resolver could not be located on the finished "
                               "bank")
        emu._ensure_range(out, 0x40)
        d2 = emu.DESC2
        for pl in places:
            sid, plain, ks = expect[pl.new_idx]
            emu.mu.mem_write(out, b"\x00" * 0x40)
            st = emu.call(resolver, (sid, out), limit=5_000_000)
            d = st[1] if st[0] == "ok" else None
            if d != d2 + pl.desc_off:
                raise RuntimeError("sound id %#x does not resolve to its descriptor in bank %s "
                                   "(got %s, wanted bank+%#x)" % (
                                       sid, SB.bank_name(cat), hex(d) if d else st[0], pl.desc_off))
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
            if not ops or bytes(ops[0][1]) != bytes(by_new[pl.new_idx]["findkey"]):
                raise RuntimeError("sound id %#x: its descriptor names key %s, the record's is %s" % (
                    sid, ops[0][1].hex() if ops else "none", bytes(by_new[pl.new_idx]["findkey"]).hex()))
    finally:
        emu.close()
    log("Sound bank %s: every one of its %d sound id(s) resolves through the game's own resolver "
        "to its descriptor and its record." % (SB.bank_name(cat), len(places)), "success")
