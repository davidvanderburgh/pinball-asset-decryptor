"""Stern **Spike 3**: the game's sound REQUESTS and the sounds each plays (PAD-1244).

The Audio tab's Requests column (PAD-635) reads :data:`.clip_sounds.REQUESTS_TSV`, which a
Spike 2 extract writes by booting the 32-bit game firmware and asking its own
``get_asset_descriptor`` what every sound id plays.  A Spike 3 game is a 64-bit (aarch64)
position-independent program, but the tables it is built from are Spike 2's, so the whole map
is read statically here, no emulator:

* **The request table.**  The same generated registry of ``{table, count, record size}``
  triples, now three u64s; the request table's records are 32 bytes with the sid-list pointer
  at +16, and as on Spike 2 the last record points at the table's own end (the sid lists start
  right after it).  Every pointer of a PIE is zero-relocated: its value is the addend of an
  ``R_AARCH64_RELATIVE`` entry in ``.rela.dyn`` (:func:`relocations`).  Fallout LE 0.82: 2298
  requests whose lists reach 2870 of its 2873 sound ids.
* **The Sound Test names.**  Spike 2's menu shape too: name groups (five equal pointers to the
  entry's name, then a zero; 48 bytes) and an array of ``{group, node id}`` (16 bytes) whose
  node id is the request id.
* **Sound id -> recording.**  On Spike 2 the descriptors are whitened and only the firmware
  finds them; on Spike 3 they are plaintext in ``image.bin``: the header's u64 at ``0x20`` ends
  a table of five equal u64 pointers per sound id (``5 * fragments``), each at the sound's
  descriptor in the block between the last PCM body and the master directory.  A descriptor
  names each recording it plays with Spike 2's op-11 marker (``0b 00 xx 00``) followed by the
  record's own ``flags_lo`` and ``param`` words (the master directory's +0x08/+0x0c), unique per
  record.  Fallout LE 0.82: 2864 of 2873 sound ids name a recording, all 2870 recordings named.

Best-effort throughout: anything off-pattern gives nothing, and the Audio tab then says why it
has no Requests column.
"""

from __future__ import annotations

import os
import re
import struct

#: ``R_AARCH64_RELATIVE``
_R_RELATIVE = 1027
#: request-table record sizes worth trying (Spike 3 builds use 32)
_REC_SIZES = (24, 32, 40, 48)
_MIN_REQUESTS = 8
_MAX_REQUESTS = 1 << 20
#: share of the sound ids a genuine request table reaches (Spike 2's bound, sound_requests.py)
_SPAN_NUM, _SPAN_DEN = 9, 10
LIST_MAX = 1 << 16
#: name groups: five equal pointers to the entry's name (then a zero), 48 bytes apart
_GROUP_PTRS = 5
#: ``image.bin``: the u64 that ends the sound-id pointer table, and pointers per sound id
_DESC_TABLE_END = 0x20
_PTRS_PER_SID = 5
_OP11_ANY = re.compile(rb"\x0b\x00.\x00", re.S)


class Program:
    """A 64-bit little-endian ELF game program: its bytes, file offsets of virtual
    addresses, and the relocated value of every pointer slot."""

    def __init__(self, raw):
        self.raw = raw
        if raw[:4] != b"\x7fELF" or raw[4] != 2 or raw[5] != 1:
            raise ValueError("not a 64-bit little-endian ELF")
        phoff = struct.unpack_from("<Q", raw, 0x20)[0]
        phentsize, phnum = struct.unpack_from("<HH", raw, 0x36)
        self.segs = []
        for i in range(phnum):
            p_type, _fl, off, vaddr, _pa, filesz, _memsz, _al = struct.unpack_from(
                "<IIQQQQQQ", raw, phoff + i * phentsize)
            if p_type == 1 and filesz:
                self.segs.append((vaddr, off, filesz))
        self.rel = relocations(raw)

    def off(self, va):
        for vaddr, foff, filesz in self.segs:
            if vaddr <= va < vaddr + filesz:
                return foff + va - vaddr
        return None

    def u64(self, va):
        o = self.off(va)
        if o is None or o + 8 > len(self.raw):
            return None
        return struct.unpack_from("<Q", self.raw, o)[0]

    def ptr(self, va):
        """The pointer stored at *va* once loaded (``None``: not a relocated slot)."""
        return self.rel.get(va)

    def cstr(self, va, limit=96):
        o = self.off(va)
        if o is None:
            return None
        end = self.raw.find(b"\x00", o, o + limit)
        if end <= o:
            return None
        s = self.raw[o:end]
        if not all(32 <= c < 127 for c in s):
            return None
        return s.decode("latin1")


def relocations(raw):
    """``{slot VA: value}`` of every ``R_AARCH64_RELATIVE`` relocation (``.rela.dyn``, found
    through the dynamic section's ``DT_RELA``/``DT_RELASZ``, else the section headers)."""
    shoff = struct.unpack_from("<Q", raw, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", raw, 0x3a)
    rela = []
    if shoff and shnum and shoff + shnum * shentsize <= len(raw):
        secs = [struct.unpack_from("<IIQQQQIIQQ", raw, shoff + i * shentsize)
                for i in range(shnum)]
        for s in secs:
            if s[1] == 4 and s[9] == 24:                     # SHT_RELA, Elf64_Rela
                rela.append((s[4], s[5]))
    out = {}
    for off, size in rela:
        end = min(off + size, len(raw))
        for o in range(off, end - 23, 24):
            r_off, r_info, r_add = struct.unpack_from("<QQq", raw, o)
            if r_info & 0xffffffff == _R_RELATIVE:
                out[r_off] = r_add
    return out


def _read_list(prog, va):
    sids = []
    o = prog.off(va)
    if o is None:
        return sids
    raw = prog.raw
    for i in range(LIST_MAX):
        if o + 4 * i + 4 > len(raw):
            break
        s = struct.unpack_from("<I", raw, o + 4 * i)[0]
        if s == 0:
            break
        sids.append(s)
    return sids


def request_table(prog, fragments):
    """``[[sid, ...] per request]`` of the game program, or ``[]``.

    A registry triple ``{table, count, size}`` is taken only when its table's last record points
    at the table's own end, and its lists then have to reach most of the card's *fragments*
    sound ids (the meaning test that tells the table from the generator's other tables)."""
    if not fragments:
        return []
    best = None
    for a, table in prog.rel.items():
        count = prog.u64(a + 8)
        size = prog.u64(a + 16)
        if size not in _REC_SIZES or not count or not _MIN_REQUESTS <= count < _MAX_REQUESTS:
            continue
        end = table + count * size
        last = table + (count - 1) * size
        field = next((f for f in range(0, size, 8) if prog.ptr(last + f) == end), None)
        if field is None:
            continue
        lists = []
        for r in range(count):
            p = prog.ptr(table + r * size + field)
            lists.append(_read_list(prog, p) if p else [])
        reach = len({s for li in lists for s in li if s < fragments})
        if reach * _SPAN_DEN < fragments * _SPAN_NUM:
            continue
        if best is None or count > len(best):
            best = lists
    return best or []


def menu_entries(prog, lists):
    """``[(request, Sound Test name)]`` in the menu's own order: the longest ``{group, node id}``
    array of the program, an entry kept where its node id is a request, it names a sound (not
    ``INVALID``), and it is not left on a placeholder sound (Spike 2's rules,
    :mod:`.spike2.sfx_names`)."""
    from .spike2 import sfx_names as SN
    n = len(lists)
    if not n:
        return []
    rel = prog.rel

    def group_name(va):
        p = rel.get(va)
        if p is None or any(rel.get(va + 8 * k) != p for k in range(1, _GROUP_PTRS)):
            return None
        return prog.cstr(p)

    entries = {}                                   # array slot VA -> (group VA, node id, name)
    for a, g in rel.items():
        nid = prog.u64(a + 8)
        if nid is None or nid >= n:
            continue
        name = group_name(g)
        if name is not None:
            entries[a] = (g, nid, name)
    run, best = [], []
    for a in sorted(entries):
        if run and a - run[-1] != 16:
            run = []
        run.append(a)
        if len(run) > len(best):
            best = list(run)
    found = []
    for g, nid, name in sorted(entries[a] for a in best):
        if SN._is_sound_entry(name) and lists[nid]:
            found.append((nid, lists[nid][-1], name.strip()))
    parked = SN._placeholder_sids([(sid, name) for _n, sid, name in found])
    return [(nid, name) for nid, sid, name in found if sid not in parked]


def menu_names(prog, lists):
    """``{request: Sound Test name}`` (:func:`menu_entries`)."""
    return dict(menu_entries(prog, lists))


def sound_names(entries, lists, parts, seconds_by_idx, log=None):
    """``{idx: Sound Test name}`` for the decoded sounds the menu names: each entry's sound is
    the first part of the last sound id its request plays (the menu's own pick, Spike 2's
    ``locate_menu_sids``), the earlier entry wins a shared sound, music-length sounds keep
    their idx names unless the entry is music, and the map has to pass Spike 2's check of the
    names against the audio (:func:`.spike2.sfx_names.validate_name_map`)."""
    from .spike2 import sfx_names as SN
    picked = []
    for nid, name in entries:
        sid = lists[nid][-1]
        p = parts.get(sid)
        if p:
            picked.append((sid, name, p[0]))
    result = SN._select_names(picked, seconds_by_idx)
    if not result:
        return {}
    ok, report = SN.validate_name_map(result, seconds_by_idx)
    if not ok:
        if log:
            log("Sound Test names didn't match the audio on this card (%s), so the sounds "
                "keep their idx names." % report, "info")
        return {}
    return result


_ILLEGAL_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_BARE_WAV = re.compile(r"^idx0*(\d+)\.wav$", re.IGNORECASE)


def apply_names(audio_dir, name_map, log=None):
    """Rename each bare ``idxNNNN.wav`` the map names to ``idxNNNN - <NAME>.wav`` (Spike 2's
    menu-named files, ``engine._apply_sfx_names``).  Returns the count renamed."""
    if not name_map or not os.path.isdir(audio_dir):
        return 0
    renamed = 0
    for fn in sorted(os.listdir(audio_dir)):
        m = _BARE_WAV.match(fn)
        name = name_map.get(int(m.group(1))) if m else None
        if not name:
            continue
        safe = _ILLEGAL_FN.sub("", name).strip().rstrip(".")[:80] or "sound"
        try:
            os.replace(os.path.join(audio_dir, fn),
                       os.path.join(audio_dir, fn[:-4] + " - " + safe + ".wav"))
            renamed += 1
        except OSError:
            pass
    if renamed and log:
        log("Named %d sound(s) from the game's Sound Test menu." % renamed, "success")
    return renamed


def sound_parts(image_path):
    """``{sid: [idx, ...]}``: the master-directory records (Extract's ``idxNNNN.wav``) each sound
    id of the plaintext Spike 3 ``image.bin`` at *image_path* plays, its first part first.
    ``{}`` when the container's descriptor table is not where its header says."""
    from .info import container_counts
    with open(image_path, "rb") as f:
        head = f.read(0x100)
        fragments, count = container_counts(head)
        if not fragments or not count:
            return {}
        md = struct.unpack_from("<Q", head, 0x40)[0]
        tend = struct.unpack_from("<Q", head, _DESC_TABLE_END)[0]
        tstart = tend - 8 * _PTRS_PER_SID * fragments
        size = os.fstat(f.fileno()).st_size
        if not 0x80 <= tstart < tend <= md or md + 24 * count > size:
            return {}
        f.seek(tstart)
        t = f.read(tend - tstart)
        f.seek(md)
        dd = f.read(24 * count)
        ptrs = [struct.unpack_from("<Q", t, 8 * _PTRS_PER_SID * s)[0] for s in range(fragments)]
        lo = min(ptrs)
        if not tend <= lo < md:
            return {}
        f.seek(lo)
        block = f.read(md - lo)
    key = {}
    for i in range(count):
        k = struct.unpack_from("<Q", dd, i * 24 + 8)[0]          # flags_lo | param << 32
        key.setdefault(k, i)
    starts = sorted(set(ptrs))
    extent = {a: b - a for a, b in zip(starts, starts[1:] + [md])}
    out = {}
    for sid, a in enumerate(ptrs):
        d = block[a - lo:a - lo + extent[a]]
        if not d or d[0] != 5:
            continue
        parts = []
        for m in _OP11_ANY.finditer(d, 9):
            p = m.start()
            if p + 12 > len(d):
                break
            i = key.get(struct.unpack_from("<Q", d, p + 4)[0])
            if i is not None and i not in parts:
                parts.append(i)
        if parts:
            out[sid] = parts
    return out


def resolve(lists, parts):
    """``(idx_of, also)`` as :func:`.clip_sounds.resolve_requests` gives them: each request's
    sounds by its sound ids' first parts, and the later parts it plays besides."""
    idx_of, also = {}, {}
    for req, sids in enumerate(lists):
        got, more = [], []
        for sid in sids:
            p = parts.get(sid, ())
            if p and p[0] not in got:
                got.append(p[0])
            more.extend(i for i in p[1:] if i not in more)
        if got:
            idx_of[req] = got
        more = [i for i in more if i not in got]
        if more:
            also[req] = more
    return idx_of, also


def seconds_by_idx(image_path):
    """``{idx: seconds}`` of the container's recordings (44100 Hz frames)."""
    from .spike3_sound import ImageSound
    return {r.index: r.duration_s for r in ImageSound(image_path).records}


def map_sounds(game_raw, image_path, output_dir, audio_dir=None, log=None):
    """From the Spike 3 game program's bytes *game_raw* and its ``image.bin`` at *image_path*:
    write :data:`.clip_sounds.REQUESTS_TSV` into *output_dir* (the Audio tab's Requests column;
    ``None``: no map) and,
    with *audio_dir* (the folder its ``idxNNNN.wav`` were decoded to), name the sounds the
    game's Sound Test names, as a Spike 2 extract does.  Returns ``(requests mapped, sounds
    named)``; ``(0, 0)`` writes nothing, and the Audio tab then says it could not be read.
    ``PINBALL_SOUND_REQUESTS=0`` / ``PINBALL_SFX_NAMES=0`` turn either off (Spike 2's)."""
    from . import clip_sounds as _cs
    from .info import container_counts
    mapped = named = 0
    try:
        with open(image_path, "rb") as f:
            fragments = container_counts(f.read(0x100))[0]
        prog = Program(game_raw)
        lists = request_table(prog, fragments)
        if not lists:
            if log and output_dir:
                log("The game's sound request table wasn't found, so the sounds keep their "
                    "idx names and the Audio tab has no Requests column for this card.", "info")
            elif log:
                log("%s: its program has no Sound Test, so these sounds keep their idx names."
                    % os.path.basename(os.path.normpath(audio_dir or "")), "info")
            return 0, 0
        parts = sound_parts(image_path)
        entries = menu_entries(prog, lists)
        if output_dir and os.environ.get("PINBALL_SOUND_REQUESTS") != "0":
            idx_of, also = resolve(lists, parts)
            if idx_of:
                _cs.write_requests(os.path.join(output_dir, _cs.REQUESTS_TSV), lists, idx_of,
                                   dict(entries), also=also)
                mapped = len(idx_of)
                if log:
                    log("Mapped %d of the game's %d sound requests to their sounds (%s)."
                        % (mapped, len(lists), _cs.REQUESTS_TSV), "info")
            elif log:
                log("The game's sound requests couldn't be matched to its sounds.", "info")
        if audio_dir and os.environ.get("PINBALL_SFX_NAMES") != "0":
            names = sound_names(entries, lists, parts, seconds_by_idx(image_path), log)
            named = apply_names(audio_dir, names, log)
    except Exception as e:                                   # noqa: BLE001
        if log:
            log("The sound request map couldn't be written (%s)." % e, "info")
    return mapped, named
