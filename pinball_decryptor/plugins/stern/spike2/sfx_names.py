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

# The table's last entry is a placeholder, never a sound.
_NOT_A_SOUND = {"INVALID", ""}


def _is_sound_entry(name):
    return bool(name) and name.strip() not in _NOT_A_SOUND


def _is_music_entry(name):
    """Does the menu itself call this slot music?

    Titles that name their music (Elvira's House of Horrors lists 53 tracks as
    "MUSIC: <NAME>") must be allowed to name long records — the blanket
    music-length guard below exists for the opposite case, where an *event*
    name would otherwise land on a shared song master."""
    return name.strip().upper().startswith(("MUSIC:", "SONG:"))

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


def _group_sites(raw):
    """File offsets where five identical non-zero dwords sit in a row.

    A name-group is five copies of one ``char*`` (the five UI languages all
    point at the same English string for a debug name), so this is a cheap
    superset of every group head in the binary — a few tens of thousands of
    sites on a 69 MB firmware, which the caller then filters."""
    import numpy as np
    n = len(raw) // 4
    if n < 8:
        return []
    a = np.frombuffer(raw[: n * 4], dtype="<u4")
    eq = a[:-4] == a[1:-3]
    for k in range(2, 5):
        eq &= a[:-4] == a[k: len(a) - 4 + k]
    eq &= a[:-4] != 0
    return (np.flatnonzero(eq) * 4).tolist()


def _walk_menu_table(raw):
    """Mine the Sound/Speaker-Test menu structure, or ``None``.

    Returns ``{"names": [...], "node_ids": {position: node_id},
    "lists": [[sid, ...], ...]}``.  ``names`` covers the WHOLE table (the sound
    entries plus the trailing speaker-routing names and "INVALID") because the
    full length is what sets the displayed numbering."""
    try:
        segs, _ = parse_elf(raw)
    except Exception:
        return None
    off2va, va2off = _seg_maps(segs)

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
        ANY entry (sound names, speaker names, INVALID) so the whole table is
        walked — the full length is what determines the displayed numbering."""
        if goff < 0 or goff + 24 > len(raw):
            return False
        p0 = _u32(raw, goff)
        if not all(_u32(raw, goff + 4 * k) == p0 for k in range(5)):
            return False
        return name_at_group(goff) is not None

    # Find the menu table by SHAPE rather than by any name it contains.  Only
    # the Sound/Speaker-Test table has a full {group_ptr, node_id} array
    # pointing at it — of the ~140 name-group tables in a Stern binary, exactly
    # one does.  Anchoring on the literal "SE FX " instead (as this did
    # originally) only ever worked on the titles using that prefix: TMNT names
    # its entries "SPEECH: ...", "SOUND: ...", "MUSIC: ...", and Elvira's House
    # of Horrors uses "VO: ...", "FX: ...".
    tables, seen = [], set()
    for goff in _group_sites(raw):
        if goff in seen or not is_group(goff):
            continue
        start = goff
        while is_group(start - 24):
            start -= 24
        if start in seen:
            continue
        names, g = [], start
        while is_group(g):
            names.append(name_at_group(g))
            seen.add(g)
            g += 24
        if len(names) >= 8:
            tables.append((start, names))
    if not tables:
        return None

    # Locate the array by finding where the table's groups are POINTED AT, not
    # by assuming it sits immediately before them.  It usually does, but not
    # always: Godzilla parks its array 14 KB ahead of a 1315-entry table, and
    # requiring adjacency found nothing there at all.
    group_va = {}
    for ti, (start, names) in enumerate(tables):
        for p in range(len(names)):
            va = off2va(start + 24 * p)
            if va is not None:
                group_va[va] = (ti, p)
    if not group_va:
        return None
    import numpy as np
    words = np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<u4")
    keys = np.array(sorted(group_va), dtype="<u4")
    hits = [int(h) for h in (np.flatnonzero(np.isin(words, keys)) * 4)
            if _u32(raw, h + 4) <= _MAX_NODE_ID] if len(keys) else []

    best = None                                # (count, table index, offset)
    i = 0
    while i < len(hits):
        ti = group_va[_u32(raw, hits[i])][0]
        j = i
        while (j + 1 < len(hits) and hits[j + 1] - hits[j] == 8
               and group_va[_u32(raw, hits[j + 1])][0] == ti):
            j += 1
        run = j - i + 1
        if best is None or run > best[0]:
            best = (run, ti, hits[i])
        i = j + 1
    if best is None:
        return None
    k, ti, pairs_start = best
    start, names = tables[ti]
    n = len(names)
    if k < max(8, n // 2):                     # not a menu table after all
        return None
    node_ids = {}
    for e in range(k):
        ptr, nid = struct.unpack_from("<2I", raw, pairs_start + e * 8)
        node_ids[group_va[ptr][1]] = nid

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
            if _is_sound_entry(name)]


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
        if not _is_sound_entry(name):
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
    are left bare unless the menu entry is itself a music name."""
    out = {}
    for _sid, name, idx in entries:
        if (_is_music_entry(name)
                or seconds_by_idx.get(idx, 0.0) < _MUSIC_MIN_SECONDS):
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
_MIN_MUSIC = 5


def _lit_unlit_pairs(names):
    """``[(lit_name, unlit_name)]`` for targets the menu names both ways."""
    have = set(names)
    return sorted((n, n[:-len(" LIT")] + " UNLIT") for n in have
                  if n.endswith(" LIT")
                  and n[:-len(" LIT")] + " UNLIT" in have)


def _name_groups(names):
    """Names bucketed by everything but their trailing token.

    "ROCK BANK TARGET K/C/O/R LIT" or "ELECTRIC MAGIC NOTE 1..36" are one
    sound design per bank or series, so their durations cluster tightly.

    The key must be at least two tokens, which keeps a bare category prefix
    from posing as a series: Elvira's five "FX: SCREAM / THUNDER / ORGAN /
    FANFARE / EXPLOSION" share the token "FX:" and nothing else, and their
    durations have no reason to agree."""
    g = {}
    for n in names:
        parts = n.split()
        if len(parts) >= 3:
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


def _mean_rank(values, subset):
    """Mean rank (1 = shortest) of *subset* within *values*."""
    order = {v: i for i, v in enumerate(sorted(values))}
    return sum(order[v] for v in subset) / len(subset)


def validate_name_map(name_map, seconds_by_idx, trials=_VALIDATE_TRIALS):
    """``(ok, report)`` — does this name map describe the audio it points at?

    Runs whichever tests the title supplies enough names for, each against
    *trials* reshuffles of the same slot set, and fails the map if an
    applicable test doesn't clear ``p <= 0.01``.  A title with too little to
    judge returns ``(True, "")`` and the caller falls back to the note-tonality
    check.

    The lit/unlit and series tests look only at effect names: a menu that names
    music ("MUSIC: CRYPT #1..#3") names genuinely different recordings, so
    their durations must not be expected to agree.  Those titles get the third
    test instead."""
    named = {n: i for i, n in name_map.items()}
    durs = {n: seconds_by_idx.get(i) for n, i in named.items()}
    durs = {n: d for n, d in durs.items() if d}
    fx = {n: d for n, d in durs.items() if not _is_music_entry(n)}
    music = [n for n in durs if _is_music_entry(n)]

    pairs = [(a, b) for a, b in _lit_unlit_pairs(fx) if a in fx and b in fx]
    groups = [v for v in _name_groups(fx).values() if len(v) >= 3]
    do_music = len(music) >= _MIN_MUSIC and len(fx) >= _MIN_MUSIC

    if (len(pairs) < _MIN_LIT_PAIRS and len(groups) < _MIN_GROUPS
            and not do_music):
        return True, ""

    def wins(d):
        return sum(1 for a, b in pairs if d[a] > d[b])

    def cv(d):
        return _mean_cv([[d[n] for n in g] for g in groups])

    def music_rank(d):
        return _mean_rank(list(d.values()), [d[n] for n in music])

    obs_w, obs_cv = wins(durs), cv(durs)
    obs_mr = music_rank(durs) if do_music else None
    rng = random.Random(0x5EF7)
    names = list(durs)
    pool = list(durs.values())
    ge_w = le_cv = ge_mr = 0
    for _ in range(trials):
        rng.shuffle(pool)
        shuf = dict(zip(names, pool))
        if pairs and wins(shuf) >= obs_w:
            ge_w += 1
        if groups:
            c = cv(shuf)
            if c is not None and obs_cv is not None and c <= obs_cv:
                le_cv += 1
        if do_music and music_rank(shuf) >= obs_mr:
            ge_mr += 1

    bits, ok = [], True
    if len(pairs) >= _MIN_LIT_PAIRS:
        p = (ge_w + 1) / (trials + 1)
        bits.append("lit/unlit %d/%d p=%.4f" % (obs_w, len(pairs), p))
        ok = ok and p <= _VALIDATE_ALPHA
    if len(groups) >= _MIN_GROUPS and obs_cv is not None:
        p = (le_cv + 1) / (trials + 1)
        bits.append("group spread %.3f p=%.4f" % (obs_cv, p))
        ok = ok and p <= _VALIDATE_ALPHA
    if do_music:
        p = (ge_mr + 1) / (trials + 1)
        bits.append("music longer (rank %.0f of %d) p=%.4f"
                    % (obs_mr, len(durs), p))
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
