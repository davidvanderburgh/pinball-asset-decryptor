"""Attach the game's own Sound/Speaker-Test menu names to extracted SFX.

Newer Spike 2 titles (Led Zeppelin onward) carry a Sound Test menu that lists
every sound effect as ``SE FX <NAME>`` with a per-sound number.  That number is
the sound's *asset id* (the resolver ``sid``), and the firmware plays it through
the same descriptor->container path the game uses in-play.  This module mines the
menu name table statically, then drives the firmware's asset resolver in the
emulator to map each menu name onto the extraction ``idx`` (master-directory
record) so a decoded WAV can be titled with its official name.

The linkage, end to end:

  menu name  --(id-array)-->  sid
  sid        --(resolver get_asset_descriptor)-->  descriptor (op11 band value)
  op11 key0  --(container find key)-->  master-dir record  ==  extraction idx

The container key is snapshotted per record during
:meth:`Spike2Emu.derive_params` (``row["key0"]``) at the skipped find; each
descriptor embeds that same key at its op11 payload, so matching the two yields
``sid -> idx``.  Everything derives from ``game_real`` + ``image.bin`` alone.

Everything here is best-effort and title-generic: any step that can't be located
(older menu-less builds, an un-mappable resolver) returns an empty map and the
extract simply keeps the plain ``idx`` names.  Only the validated codec is
required for decode; naming never blocks it.
"""

import struct

from .elf import parse_elf
from .emulator import DESC_BASE

# image.bin runtime mapping base the resolver returns descriptor pointers in
# (``descriptor_va = DESC_BASE + file_offset``).  Reuses the emulator's
# offset-identity anchor; validated per-run by requiring magic-5 descriptors.
IMG_BASE = DESC_BASE

_SEFX = b"SE FX "


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


def locate_menu_names(raw):
    """Mine the Sound/Speaker-Test menu -> ``[(sid, name), ...]`` for SE FX entries.

    The menu is a contiguous table of 24-byte name-groups (five identical
    ``char*`` — the UI languages, all pointing at the same English string —
    plus a trailing word).  The firmware assigns this category's sound ids to
    the table in REVERSE order: the last group gets sound #0 and the first gets
    the highest, so a group at position ``p`` in a table of ``N`` groups has

        sid = (N - 1) - p

    (verified against Led Zeppelin's on-machine Sound Test: "Note 22" is
    position 43 of 245 groups -> sid 201, matching the "#201" it shows).  The
    machine's displayed "SOUND #" is exactly this sid, and the resolver plays
    it.  Returns ``[]`` for any build without this menu (older titles) or whose
    layout doesn't match, so the caller degrades to plain ``idx`` names.

    NOTE: the parallel ``{id, group_ptr}`` array's ``id`` (= a reversed *display*
    index, NOT the sid) must NOT be used here — doing so shipped wrong names in
    v0.61.0.  The whole table's length is what sets the sid base.
    """
    try:
        segs, _ = parse_elf(raw)
    except Exception:
        return []
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
        return []

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
        — the full length is what determines the sid base."""
        if goff < 0 or goff + 24 > len(raw):
            return False
        p0 = _u32(raw, goff)
        if not all(_u32(raw, goff + 4 * k) == p0 for k in range(5)):
            return False
        return name_at_group(goff) is not None

    # Locate the table via an SE FX group (five identical pointers to an SE FX
    # name), then walk the WHOLE contiguous table both directions.
    seed = None
    for va in sorted(sefx_vas):
        at = raw.find(struct.pack("<I", va) * 5)
        if at != -1:
            seed = at
            break
    if seed is None:
        return []
    start = seed
    while is_group(start - 24):
        start -= 24
    groups = []                                    # position -> name (full table)
    goff = start
    while is_group(goff):
        groups.append(name_at_group(goff))
        goff += 24
    n = len(groups)
    if n < 8:
        return []

    # sid = (N-1) - position; emit only the SE FX entries.
    out = []
    for p, name in enumerate(groups):
        if name and name.startswith("SE FX"):
            out.append(((n - 1) - p, name))
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


# Records at least this long are music beds/masters, not effects — never give
# one an event name off the weak (broad-scan) evidence path.  Matches the
# music threshold the transcribe / music-ID passes use.
_MUSIC_MIN_SECONDS = 20.0


def _descriptor_refs(desc, key0_to_idx):
    """The extraction records a descriptor references.

    Returns ``("anchored", idx)``, ``("broad", frozenset_of_idx)`` or
    ``(None, None)``.  op11 (opcode 0x0b) carries the 8-byte band value whose
    low word is the container key; the two fixed layouts anchor the opcode at
    offset 10 or 28 (payload lo32 at 14 / 32) — a key found there is the
    entry's own primary asset.  Without an anchor, every 0x0b byte is scanned
    and ALL known-key matches are returned: event/sequence descriptors embed
    references to several assets (their sting plus the music bed they play
    into), so a lone scan hit is a reference, not necessarily ownership."""
    if len(desc) >= 18 and desc[10] == 0x0B:
        idx = key0_to_idx.get(_u32(desc, 14))
        if idx is not None:
            return "anchored", idx
    if len(desc) >= 36 and desc[28] == 0x0B:
        idx = key0_to_idx.get(_u32(desc, 32))
        if idx is not None:
            return "anchored", idx
    hits = set()
    for o in range(1, len(desc) - 7):
        if desc[o] == 0x0B:
            idx = key0_to_idx.get(_u32(desc, o + 4))
            if idx is not None:
                hits.add(idx)
    return ("broad", frozenset(hits)) if hits else (None, None)


def _select_names(entries, seconds_by_idx):
    """``{idx: name}`` from resolved menu *entries*, naming only what is safe.

    *entries* = ``[(sid, name, kind, ref)]`` in menu-table order, where
    ``ref`` is an idx for kind "anchored" or a frozenset for "broad".

    Anchored bindings name unconditionally — the opcode-anchored op11 is the
    firmware's own answer for that entry (verified coherent: every Led
    Zeppelin blip lands right).  Broad-scan bindings are weak evidence, so
    one names a record only when the record is (a) that descriptor's sole
    reference, (b) referenced by NO other menu entry, and (c) shorter than
    the music threshold.

    (b) and (c) are what David's mislabel report exposed: LZ has no music
    banks — shot and mode events all play into a handful of shared full-song
    masters, so many entries reference the same long record ("LEFT RAMP
    EXIT" and "ZEPPELIN AWARD" both reference the same 4:45 track).  No
    single event name is correct for a shared music master; leaving it bare
    lets the music-ID pass title the actual song.  The old
    take-the-first-scan-hit logic is how v0.61.2 put "SE FX SEQ BALL SAVE
    LIT" on an 8-minute track (and produced monkeybug's LE dual-labels)."""
    census = {}
    for _sid, _name, kind, ref in entries:
        for i in ((ref,) if kind == "anchored" else ref):
            census[i] = census.get(i, 0) + 1
    out = {}
    for _sid, name, kind, ref in entries:
        if kind == "anchored":
            out.setdefault(ref, name)
        elif len(ref) == 1:
            idx = next(iter(ref))
            if (census[idx] == 1
                    and seconds_by_idx.get(idx, 0.0) < _MUSIC_MIN_SECONDS):
                out.setdefault(idx, name)
    return out


def build_name_map(emu, params):
    """Return ``{idx: "SE FX <NAME>"}`` for the SFX the Sound-Test menu names.

    *emu* is a **booted** :class:`Spike2Emu`; *params* is its
    :meth:`derive_params` output (rows must carry ``key0`` — the container key
    snapshot).  Best-effort: returns ``{}`` if the menu, the resolver, or the
    keys can't be located.  Never raises."""
    try:
        return _build_name_map(emu, params)
    except Exception:
        return {}


def _build_name_map(emu, params):
    key0_to_idx = {p["key0"]: p["idx"]
                   for p in params if p.get("key0") is not None}
    if not key0_to_idx:
        return {}
    fw = emu_fw_bytes(emu)                          # 69 MB — read once, reuse
    names = locate_menu_names(fw)
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
        kind, ref = _descriptor_refs(desc, key0_to_idx)
        if kind is not None:
            entries.append((sid, name, kind, ref))
    result = _select_names(entries, seconds_by_idx)
    # Safety gate: the "... NOTE n" entries are musical note stings, so a correct
    # mapping lands them on TONAL sounds.  A wrong sid base (the v0.61.0 bug)
    # lands them on speech/other and they read as non-tonal.  If there are
    # enough NOTE entries and they're clearly NOT tonal, the base is wrong for
    # this build -> return nothing rather than ship mislabels.  (No decode, no
    # judgement when a build has too few NOTE entries -> trust the derived sid.)
    if not _notes_look_tonal(emu, params, result):
        return {}
    return result


def _notes_look_tonal(emu, params, name_map):
    """Cheap, Whisper-free validation of the sid mapping via the note stings."""
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
