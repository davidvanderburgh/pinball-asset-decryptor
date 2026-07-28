"""Attach the game's own Sound/Speaker-Test menu names to extracted SFX.

Newer Spike 2 titles (Led Zeppelin onward) carry a Sound Test menu that lists
every sound effect as ``SE FX <NAME>`` with a per-sound number.  This module
mines the menu statically, follows the firmware's own menu-entry -> sound-id
indirection, then drives the asset resolver in the emulator to land each name
on an extraction ``idx`` (master-directory record) so a decoded WAV can be
titled with its official name.

The linkage, end to end::

  menu name    --(24B name-group table, position p)
  node id      --({group_ptr, node_id} array immediately BEFORE the table)
  sound-id list--(NUL-terminated u32 lists immediately BEFORE that array,
                  indexed FROM THE END: list = lists[(nlists - 1) - node_id];
                  the list's LAST element is the sid the entry plays)
  sid          --(resolver get_asset_descriptor)-->  descriptor
  op11 key     --(container find key)-->  master-dir record  ==  extraction idx

Two traps live in that chain, both of which shipped wrong names before:

* the 8-byte array is ``{group_ptr, node_id}``, **not** ``{node_id, group_ptr}``.
  Reading it the other way shifts every id by one entry (the v0.61.0 bug).
* the sound-id list block's final u32 is the terminator that closes list id 0,
  so splitting on zeros yields a trailing empty list that **must be kept** —
  dropping it as spurious renumbers every list and shifts the whole map by one.

The number the machine *displays* in its menu is a third thing again: a plain
reversed position, ``(N - 1) - p``, which is what :func:`locate_menu_names`
reports for the ``sound_test_names.csv`` sidecar.  It is not the resolver sid.

Everything here is best-effort and title-generic: any step that can't be located
(older menu-less builds, an un-mappable resolver) returns an empty map and the
extract simply keeps the plain ``idx`` names.  Only the validated codec is
required for decode; naming never blocks it.  The finished map is additionally
put through :func:`validate_name_map`, a permutation test of the names against
the audio, so a build whose layout differs enough to shift the mapping rejects
its own names instead of shipping mislabels.
"""

import random
import struct

from .elf import parse_elf
from .emulator import DESC_BASE

# image.bin runtime mapping base the resolver returns descriptor pointers in
# (``descriptor_va = DESC_BASE + file_offset``).  Reuses the emulator's
# offset-identity anchor; validated per-run by requiring magic-5 descriptors.
IMG_BASE = DESC_BASE

_SEFX = b"SE FX "

# Ceiling for a node id (an index into the sound-id list block, so bounded by
# the block's length) — guards the walk over the {group_ptr, node_id} array.
_MAX_NODE_ID = 0x10000
# How far back the sound-id list block may be searched for, in bytes.
_MAX_LIST_BLOCK = 1 << 20


def _u32(b, o=0):
    return struct.unpack_from("<I", b, o)[0]


def _seg_maps(segs):
    """Return ``(off2va, va2off)`` closures for the ELF's PT_LOAD segments.

    ``segs`` = ``[(p_vaddr, p_offset, p_filesz, p_memsz), ...]`` from
    :func:`parse_elf`.  Each segment maps file<->virtual by a constant delta."""
    def off2va(off):
        for v, o, fs, _ in segs:
            if o <= off < o + fs:
                return v + (off - o)
        return None

    def va2off(va):
        for v, o, fs, _ in segs:
            if v <= va < v + fs:
                return o + (va - v)
        return None
    return off2va, va2off


def _walk_menu_table(raw):
    """Mine the Sound/Speaker-Test menu structure, or ``None``.

    Returns ``{"names": [...], "node_ids": {position: node_id},
    "lists": [[sid, ...], ...]}``.  ``names`` covers the WHOLE table (SE FX
    entries plus the trailing speaker-routing names and "INVALID") because the
    full length is what sets the displayed numbering."""
    try:
        segs, _ = parse_elf(raw)
    except Exception:
        return None
    off2va, va2off = _seg_maps(segs)

    # VAs of every pooled "SE FX " string (NUL-preceded == a pool entry start),
    # used only to LOCATE the table (an SE FX group is an unambiguous anchor).
    sefx_vas = set()
    pos = raw.find(_SEFX)
    while pos != -1:
        if pos > 0 and raw[pos - 1] == 0:
            va = off2va(pos)
            if va is not None:
                sefx_vas.add(va)
        pos = raw.find(_SEFX, pos + 1)
    if len(sefx_vas) < 8:                      # no menu (or too few to trust)
        return None

    def name_at_group(goff):
        p = _u32(raw, goff)
        so = va2off(p)
        if so is None:
            return None
        end = raw.find(b"\x00", so, so + 96)
        if end < 0 or end == so:
            return None
        s = raw[so:end]
        if not all(32 <= c < 127 for c in s):
            return None
        return s.decode("latin1")

    def is_group(goff):
        """A name-group: five identical pointers to a valid string.  Accepts
        ANY entry (SE FX, speaker names, INVALID) so the whole table is walked
        — the full length is what determines the displayed numbering."""
        if goff < 0 or goff + 24 > len(raw):
            return False
        p0 = _u32(raw, goff)
        if not all(_u32(raw, goff + 4 * k) == p0 for k in range(5)):
            return False
        return name_at_group(goff) is not None

    seed = None
    for va in sorted(sefx_vas):
        at = raw.find(struct.pack("<I", va) * 5)
        if at != -1:
            seed = at
            break
    if seed is None:
        return None
    start = seed
    while is_group(start - 24):
        start -= 24
    names, goff = [], start
    while is_group(goff):
        names.append(name_at_group(goff))
        goff += 24
    n = len(names)
    if n < 8:
        return None

    # {group_ptr, node_id} pairs, immediately BEFORE the name table, one per
    # group.  Walk back while each entry points into the table.
    node_ids, k = {}, 0
    while k < n:
        o = start - (k + 1) * 8
        if o < 0:
            break
        ptr, nid = struct.unpack_from("<2I", raw, o)
        po = va2off(ptr)
        if (po is None or po < start or (po - start) % 24
                or (po - start) // 24 >= n or nid > _MAX_NODE_ID):
            break
        node_ids[(po - start) // 24] = nid
        k += 1
    pairs_start = start - k * 8

    # NUL-terminated u32 sound-id lists, immediately BEFORE the pairs array.
    # Walk back counting terminators until the block holds every id the menu
    # asks for, rather than bounding the *values*: on the multi-category titles
    # (Rush, Metallica, Deadpool, ...) a sound id carries its category in the
    # high half, so any value ceiling low enough to be meaningful cuts the block
    # short.  Over-shooting the start costs nothing — ids are counted from the
    # END, so extra leading lists renumber nothing.
    # The margin absorbs the terminator the walk stops on (which would otherwise
    # split off a leading empty list and swallow the highest id's slot) plus any
    # padding words trimmed below.
    need = (max(node_ids.values()) + 1 + 4) if node_ids else 0
    b = pairs_start
    floor = max(0, pairs_start - _MAX_LIST_BLOCK)
    zeros = 0
    while b - 4 >= floor and zeros < need:
        b -= 4
        if _u32(raw, b) == 0:
            zeros += 1
    lists, cur, o = [], [], b
    while o < pairs_start:
        v = _u32(raw, o)
        if v == 0:
            lists.append(cur)
            cur = []
        else:
            cur.append(v)
        o += 4
    if cur:
        lists.append(cur)
    # The block ends with the empty list id 0 followed by padding words, which
    # split into further empty lists.  Since ids count from the END, each stray
    # trailing empty renumbers every list — so keep exactly one.
    while len(lists) >= 2 and not lists[-1] and not lists[-2]:
        lists.pop()
    return {"names": names, "node_ids": node_ids, "lists": lists}


def locate_menu_names(raw):
    """Mine the Sound-Test menu -> ``[(displayed_number, name)]`` for SE FX.

    The number is the one the machine prints beside the entry, a reversed
    position ``(N - 1) - p`` over the whole table (OCR-verified against Led
    Zeppelin's on-machine Sound Test: "NOTE 22" is position 43 of 245 groups
    and displays "#201").  This powers the ``sound_test_names.csv`` sidecar so
    an operator can play a number on the machine and name that slot by hand.

    It is emphatically NOT the resolver sid — see :func:`locate_menu_sids`.
    Returns ``[]`` for any build without this menu."""
    t = _walk_menu_table(raw)
    if t is None:
        return []
    names = t["names"]
    n = len(names)
    return [((n - 1) - p, name) for p, name in enumerate(names)
            if name and name.startswith("SE FX")]


def locate_menu_sids(raw):
    """Mine the Sound-Test menu -> ``[(sid, name)]`` in menu-table order.

    Follows the menu's real indirection (node id -> sound-id list, counted from
    the end of the list block) and takes the list's last element, which is the
    sid the entry plays.  Multi-element lists are routing/prefix sequences: the
    speaker-test prompts carry three, the first two selecting the output.

    Returns ``[]`` when the menu or the indirection can't be read."""
    t = _walk_menu_table(raw)
    if t is None:
        return []
    lists = t["lists"]
    nl = len(lists)
    out = []
    for p, name in enumerate(t["names"]):
        if not name or not name.startswith("SE FX"):
            continue
        nid = t["node_ids"].get(p)
        if nid is None:
            continue
        li = (nl - 1) - nid
        if not 0 <= li < nl:                   # never let a negative index wrap
            continue
        lst = lists[li]
        if lst:
            out.append((lst[-1], name))
    return out


def _find_resolver(emu, fw=None):
    """Locate + verify the firmware ``get_asset_descriptor(sid, out)`` function.

    It reads the vf2 keystream (``emu.VF2_VA``) to de-whiten descriptors, so code
    that materialises that runtime address (an ARM ``movw``/``movt`` pair) points
    at it.  Each candidate is driven with a probe sid and accepted only if it
    returns a descriptor pointer inside the image window that de-whitens to a
    magic-5 header — so a wrong candidate (e.g. the vf2 *builder*) is rejected.
    Returns ``(addr, out_buf)`` or ``(None, None)``.
    """
    import numpy as np
    fw = emu_fw_bytes(emu) if fw is None else fw
    vf2 = emu.VF2_VA
    lo16, hi16 = vf2 & 0xFFFF, (vf2 >> 16) & 0xFFFF
    # ARM: movw rd,#lo16 == 0xE3000000|((lo16>>12)<<16)|(lo16&0xfff) (rd masked);
    #      movt rd,#hi16 == 0xE3400000|((hi16>>12)<<16)|(hi16&0xfff).
    movw = 0xE3000000 | ((lo16 >> 12) << 16) | (lo16 & 0xFFF)
    movt = 0xE3400000 | ((hi16 >> 12) << 16) | (hi16 & 0xFFF)
    words = np.frombuffer(fw[:len(fw) & ~3], dtype="<u4") & 0xFFFF0FFF
    movw_off = (np.flatnonzero(words == movw) * 4)
    movt_set = set(int(x) * 4 for x in np.flatnonzero(words == movt))
    cand_fn = set()
    for o in movw_off:
        o = int(o)
        if any((o + d) in movt_set for d in (4, 8, 12, 16, -4, -8, -12)):
            cand_fn.add(_func_start(fw, o))
    out = emu.alloc(0x40)
    for addr in sorted(cand_fn):
        try:
            if _try_resolve(emu, addr, out, sid=1) is not None:
                return addr, out
        except Exception:
            continue
    return None, None


def emu_fw_bytes(emu):
    """The firmware ELF bytes the emulator was built from (re-read on demand)."""
    return open(emu._gr_path, "rb").read()


def _func_start(fw, off):
    """Walk back from *off* to the enclosing ``push {..., lr}`` prologue."""
    for k in range(off, max(0, off - 0x600), -4):
        if (_u32(fw, k) & 0xFFFF4000) == 0xE92D4000:
            return k + 0x8000                       # seg1 va = off + 0x8000
    return off + 0x8000


def _try_resolve(emu, addr, out, sid):
    """Call *addr* as the resolver; return de-whitened descriptor bytes or None."""
    emu.mu.mem_write(out, b"\x00" * 0x40)
    st = emu.call(addr, (sid, out), limit=5_000_000)
    if st[0] != "ok":
        return None
    d = st[1]
    if not (IMG_BASE <= d < IMG_BASE + emu.imgsize):
        return None
    ks = _u32(bytes(emu.mu.mem_read(out, 4)))
    keyoff = ks - emu.VF2_VA
    if not (0 <= keyoff < 0x3F00):
        return None
    dec0 = d - IMG_BASE
    body = emu.mm[dec0:dec0 + 0x50]
    if len(body) < 0x50:
        return None
    vf2 = bytes(emu.mu.mem_read(emu.VF2_VA + keyoff, 0x50))
    desc = bytes(body[k] ^ vf2[k] for k in range(0x50))
    return desc if desc and desc[0] == 5 else None


# Records at least this long are music beds/masters, not effects.  Led Zeppelin
# has no music banks — its mode songs are cat-0 records that shot and mode
# events play into — so an event descriptor can legitimately reference a full
# song master.  No single event name is right for a shared master, and leaving
# it bare lets the music-ID pass title the actual song.
_MUSIC_MIN_SECONDS = 20.0

_OP11 = b"\x0b\x00\x00\x00"


def _primary_idx(desc, key0_to_idx):
    """The extraction record a descriptor owns, or ``None``.

    op11 (opcode 0x0b) carries the 8-byte band value whose low word is the
    container key.  The descriptor has a variable-length field ahead of it, so
    the marker's offset moves between builds and entries; the first marker at
    or after offset 9 is the entry's own primary asset.  (Checking only the two
    fixed offsets 10 and 28, as v0.61.x did, silently lost a third of the
    coverage and pushed the rest onto a broad scan that matched references to
    shared music masters.)"""
    p = desc.find(_OP11, 9)
    if p < 0 or p + 8 > len(desc):
        return None
    return key0_to_idx.get(_u32(desc, p + 4))


def _select_names(entries, seconds_by_idx):
    """``{idx: name}`` from resolved menu *entries* = ``[(sid, name, idx)]``.

    *entries* arrive in menu-table order, so where two entries resolve to one
    record the earlier menu name wins.  Records at or over the music threshold
    are left bare regardless."""
    out = {}
    for _sid, name, idx in entries:
        if seconds_by_idx.get(idx, 0.0) < _MUSIC_MIN_SECONDS:
            out.setdefault(idx, name)
    return out


# --------------------------------------------------------------------------
# Validation: do the NAMES predict the AUDIO?
#
# Two properties of Stern's own naming, tested against a null that shuffles
# which named slot gets which name.  Both hold overwhelmingly on a correct map
# (p < 1/20000 on Led Zeppelin) and collapse on a shifted one, and neither
# needs a decode — durations come straight from the derived params.
_VALIDATE_TRIALS = 2000
_VALIDATE_ALPHA = 0.01
_MIN_LIT_PAIRS = 6
_MIN_GROUPS = 3


def _lit_unlit_pairs(names):
    """``[(lit_name, unlit_name)]`` for targets the menu names both ways."""
    have = set(names)
    return sorted((n, n[:-len(" LIT")] + " UNLIT") for n in have
                  if n.endswith(" LIT")
                  and n[:-len(" LIT")] + " UNLIT" in have)


def _name_groups(names):
    """Names bucketed by everything but their trailing token.

    "ROCK BANK TARGET K/C/O/R LIT" or "ELECTRIC MAGIC NOTE 1..36" are one
    sound design per bank or series, so their durations cluster tightly."""
    g = {}
    for n in names:
        parts = n.split()
        if len(parts) >= 2:
            g.setdefault(" ".join(parts[:-1]), []).append(n)
    return {k: v for k, v in g.items() if len(v) >= 3}


def _mean_cv(durations_by_group):
    """Mean coefficient of variation of duration within each group."""
    cvs = []
    for ds in durations_by_group:
        if len(ds) < 3:
            continue
        m = sum(ds) / len(ds)
        if m <= 0:
            continue
        var = sum((d - m) ** 2 for d in ds) / len(ds)
        cvs.append((var ** 0.5) / m)
    return (sum(cvs) / len(cvs)) if cvs else None


def validate_name_map(name_map, seconds_by_idx, trials=_VALIDATE_TRIALS):
    """``(ok, report)`` — does this name map describe the audio it points at?

    Runs whichever of the two tests the title supplies enough names for, each
    against *trials* reshuffles of the same slot set, and fails the map if an
    applicable test doesn't clear ``p <= 0.01``.  A title with too few paired
    or grouped names to judge returns ``(True, ...)`` with an empty report and
    the caller falls back to the note-tonality check."""
    named = {n: i for i, n in name_map.items()}
    durs = {n: seconds_by_idx.get(i) for n, i in named.items()}
    durs = {n: d for n, d in durs.items() if d}
    pairs = [(a, b) for a, b in _lit_unlit_pairs(durs) if a in durs and b in durs]
    groups = [v for v in _name_groups(durs).values() if len(v) >= 3]

    if len(pairs) < _MIN_LIT_PAIRS and len(groups) < _MIN_GROUPS:
        return True, ""

    def wins(d):
        return sum(1 for a, b in pairs if d[a] > d[b])

    def cv(d):
        return _mean_cv([[d[n] for n in g] for g in groups])

    obs_w, obs_cv = wins(durs), cv(durs)
    rng = random.Random(0x5EF7)
    names = list(durs)
    pool = list(durs.values())
    ge_w = le_cv = 0
    for _ in range(trials):
        rng.shuffle(pool)
        shuf = dict(zip(names, pool))
        if pairs and wins(shuf) >= obs_w:
            ge_w += 1
        if groups:
            c = cv(shuf)
            if c is not None and obs_cv is not None and c <= obs_cv:
                le_cv += 1

    bits, ok = [], True
    if len(pairs) >= _MIN_LIT_PAIRS:
        p = (ge_w + 1) / (trials + 1)
        bits.append("lit/unlit %d/%d p=%.4f" % (obs_w, len(pairs), p))
        ok = ok and p <= _VALIDATE_ALPHA
    if len(groups) >= _MIN_GROUPS and obs_cv is not None:
        p = (le_cv + 1) / (trials + 1)
        bits.append("group spread %.3f p=%.4f" % (obs_cv, p))
        ok = ok and p <= _VALIDATE_ALPHA
    return ok, ", ".join(bits)


def build_name_map(emu, params, log=None):
    """Return ``{idx: "SE FX <NAME>"}`` for the SFX the Sound-Test menu names.

    *emu* is a **booted** :class:`Spike2Emu`; *params* is its
    :meth:`derive_params` output (rows must carry ``key0`` — the container key
    snapshot).  Best-effort: returns ``{}`` if the menu, the resolver, or the
    keys can't be located, or if the finished map fails validation.  Never
    raises."""
    try:
        return _build_name_map(emu, params, log)
    except Exception:
        return {}


def _build_name_map(emu, params, log=None):
    key0_to_idx = {p["key0"]: p["idx"]
                   for p in params if p.get("key0") is not None}
    if not key0_to_idx:
        return {}
    fw = emu_fw_bytes(emu)                          # 69 MB — read once, reuse
    names = locate_menu_sids(fw)
    if not names:
        return {}
    resolver, out = _find_resolver(emu, fw)
    if resolver is None:
        return {}
    from .emulator import emitted_length
    seconds_by_idx = {p["idx"]: emitted_length(p.get("length", 0)) / 44100.0
                      for p in params}
    entries = []
    for sid, name in names:
        desc = _try_resolve(emu, resolver, out, sid)
        if desc is None:
            continue
        idx = _primary_idx(desc, key0_to_idx)
        if idx is not None:
            entries.append((sid, name, idx))
    result = _select_names(entries, seconds_by_idx)
    if not result:
        return {}

    ok, report = validate_name_map(result, seconds_by_idx)
    if not ok:
        if log:
            log("Sound Test names didn't match the audio on this build (%s) — "
                "sounds keep their idx names." % report, "info")
        return {}
    if not report and not _notes_look_tonal(emu, params, result):
        return {}
    if log and report:
        log("Sound Test name check passed (%s)." % report, "info")
    return result


def _notes_look_tonal(emu, params, name_map):
    """Fallback validation for titles with too few paired/grouped names.

    The "... NOTE n" entries are musical note stings, so a correct mapping
    lands them on TONAL sounds; a shifted one lands them on speech and other
    effects.  Costs a short decode per note, so it only runs when the
    duration-based tests can't be applied."""
    import numpy as np
    note_idx = [idx for idx, nm in name_map.items() if " NOTE " in nm]
    if len(note_idx) < 12:
        return True                                # too few to judge; trust it
    pby = {p["idx"]: p for p in params}
    tons = []
    for idx in sorted(note_idx)[:24]:
        p = pby.get(idx)
        if p is None:
            continue
        try:
            r = emu.decode(p, max_secs=1.5)
        except Exception:
            r = None
        if r is None:
            continue
        x = np.asarray(r[0], float)
        if len(x) < 4000:
            continue
        x = x[len(x) // 4: len(x) // 4 + 12000]
        x = x - x.mean()
        if x.std() < 1:
            continue
        ac = np.correlate(x, x, "full")[len(x) - 1:]
        seg = ac[31250 // 1500: 31250 // 60]       # ~60..1500 Hz lag window
        if len(seg) and ac[0] > 0:
            tons.append(float(seg.max() / ac[0]))
    # Correct LZ mapping medians ~0.7; a wrong base (notes -> speech) drops well
    # below.  Only reject on a clear failure so a real mapping is never dropped.
    return len(tons) < 6 or float(np.median(tons)) > 0.30
