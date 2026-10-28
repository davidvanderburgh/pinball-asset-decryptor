"""An extra sound bank this app adds to a Spike 2 card: ``image-scNN.bin`` beside
``image.bin`` (PAD-595).

A Spike 2 game opens its sound bank with 32-bit calls and streams long sounds
with 32-bit reads, so no bank can pass 2 GiB (``emulator.MAX_IMAGE_BYTES``).
Six music titles get round that the vendor's way: their songs live in
per-category banks, ``image-scNN.bin``, loaded at boot after ``image.bin`` by
the game's own loader.  This module builds such a bank for a title that ships
with one, so the sounds a build appends -- the modes' own calls and music beds
-- are not bounded by what ``image.bin`` has left.

What the game needs of a bank, read off Godzilla LE 1.16's program (the plan
``docs/plans/extra_sound_banks.md`` has the addresses):

* ``image.bin``'s header names it: the category count at ``0x68`` and the id
  array from ``0x6c``, one u32 each.  The boot tail loads every id in turn
  (``load_category_assets``, ``MASTERDIR_DECODE``) and then unmaps the bank;
  a play maps it again.  The ids sit between the header's fixed part and its
  first table (``hdr[0x28]``), which leaves room for 18 more on every card
  seen.
* The bank's header is 0x68 bytes, the same layout as ``image.bin``'s head:
  ``0x28`` the fragment table's offset, ``0x38`` the file size less 4,
  ``0x40`` the master directory's offset, ``0x48`` where the data after the
  fragment table starts, ``0x5c`` the fragment count, ``0x60`` the record
  count.  The loader copies these 0x68 bytes and the file size and reads
  nothing else of the header.
* Its master directory is the same encrypted record array as ``image.bin``'s
  (``masterdir``), under the firmware's cipher -- the key comes from the seed
  word alone, so one firmware packs any bank.

A bank sound is PLAYED by a sid of the bank's own category, ``cat << 16 | n``,
the vendor's way (a rig run of the first design, a key swap at the game's
record lookup, played every bank sound as white noise: the game streams a
sound from the file of the SID's category, so a bank record reached under a
cat-0 sid was read out of image.bin).  The game's resolver
(``get_asset_descriptor``, read off Deadpool LE 1.16 and Godzilla LE 1.16)
takes the sid's low half as a FRAGMENT index into the bank's fragment table
(``hdr[0x28]``): a fragment is ``stride`` (5 on every card seen) 8-byte slots,
one per random variant the game may pick, each slot's low word the
descriptor's offset in the bank whitened with four bytes of the firmware's
vf2 keystream at :func:`slot_vf2_offset` (slot index); the high word is
zero.  The DESCRIPTOR (the same script a cat-0 sid has: bus, declared
duration, the op11 record key, the loop tail) lies in the bank, whitened
with the vf2 keystream at an offset the resolver derives from the
descriptor's offset (``(off ^ X) & M``, per build:
:func:`.bank_build.resolver_rule` measures X and M off cat-0 sids).  Its op11
key is the bank record's own key, verbatim: the game masks out the bits it
fills from the sid's category and a registered key already carries them.
The vendor keeps its descriptors just before the directory; so does this.

The file is pure geometry here; the cipher half is :mod:`masterdir`'s and the
derive is :meth:`.category.CatEmu.derive_bank`.
"""
import collections
import os
import struct

from . import masterdir as MD
from .emulator import MAX_IMAGE_BYTES

#: The bank header the loader copies: 0x68 bytes.
HDR_LEN = 0x68
#: Header words (u32, little-endian; the high word of each 8-byte slot is 0).
HDR_FRAG_TABLE = 0x28       # where the fragment table starts (field 5 of container_ptr)
HDR_END_WORD = 0x38         # the file size less 4 (not checked by the game)
HDR_MD_OFF = MD.HDR_MD_OFF  # 0x40: the master directory
HDR_DATA = 0x48             # where the data after the fragment table starts (field 9)
HDR_FRAGMENTS = 0x5c        # fragment count (sids of this category): none in ours
HDR_COUNT = MD.HDR_COUNT    # 0x60: record count
#: ``image.bin``'s category count and id array.
IMG_CAT_COUNT = 0x68
IMG_CAT_IDS = 0x6c
#: The trailer word after the directory's seed: the mark of a bank this app made.
PAD_TRAILER = b"PADB"
#: The biggest bank the game can open and stream: the same 2 GiB - 1 as image.bin.
MAX_BANK_BYTES = MAX_IMAGE_BYTES
#: The most a machine has been seen to hold mapped at once: ``image.bin`` and the bank
#: playing (PAD-593).  The game maps both whole into its 32-bit address space, and a
#: Godzilla card at 2,260 MB (image.bin 2,125 MB + a 136 MB bank) died with "FATAL: error
#: 232 (Flash memory init mmap failed)" at its first bank sound.  Stern's own largest is
#: Dungeons & Dragons LE/Pro 1.10: image.bin 2,142,352,388 + its 39,598,976-byte bank
#: (Rush 1.19: 1,836,701,778 + 218,349,330 = 2,055,051,108).  The emulator cannot see this
#: limit: it runs the game with a whole 4 GiB of address space.
MAPPED_MAX = 2_181_951_364
#: How big a bank of the modes' own sounds is made: Stern's largest D&D bank, so the bank
#: playing adds no more beside image.bin than a shipped title does (PAD-593).
BANK_SLICE = 40_000_000
#: The biggest bank Stern ships: Rush LE/Pro 1.19's largest, 218,349,330 bytes (James Bond
#: 1.06's is 205 MiB, Foo Fighters 1.04's 129 MiB).  A sound too long for a
#: :data:`BANK_SLICE` bank gets a bank of its own, sized to the room beside image.bin
#: (:func:`alone_bank_room`) and never past this (PAD-607).
BANK_MAX_SEEN = 218_349_330
#: Category ids the loader can name: ``image-sc%02d.bin``.
MIN_CATEGORY, MAX_CATEGORY = 1, 99
#: A fragment's slot: 8 bytes (the descriptor offset, whitened, and a zero word).
FRAG_SLOT = 8
#: Slots a fragment has on every card seen (the game reads the count off
#: image.bin's own tables: :func:`fragment_stride`).
DEFAULT_STRIDE = 5
#: Room a bank descriptor gets: the window the resolver's callers read.
DESC_SLOT = 0x50
#: PAD-779: the most room a bank's descriptors may get, for a bank that holds a song's whole
#: sequence (intro, song, outro: Iron Maiden LE 1.18's sound id 974 plays four records in 87
#: bytes).  The game's own descriptors run to 108 bytes there, at keystream offsets from the
#: same rule (:func:`.bank_build.resolver_rule`), so its keystream covers this far.
DESC_SLOT_MAX = 0x60
#: The vf2 keystream window the resolver can point into.
VF2_WINDOW = 0x3F00
#: The bank's sid map (PAD-606), between the descriptor block and the directory: which of
#: the GAME's own sids each fragment stands in for (0 for a mode's own sound), so a later
#: Write of the same card can put the game's request lists back.  Nothing the game runs
#: reads it: the descriptors are reached through the fragment table and the directory
#: through ``hdr[0x40]``.
SID_MAP_MAGIC = b"PADS"
#: PAD-779: the sid map's extension, just before it, for the fragments past the records that
#: stand in for one of the game's sids (a song's sequence: each sound id that plays it is a
#: fragment): ``(fragment, game sid)`` u32 pairs, then the pair count and this magic.
SID_MAP_EXT_MAGIC = b"PADX"
#: Sound channels the game plays at once (the voice loop at Godzilla LE 1.16's 0x43c210).
#: A sound's start takes a reference on its sid's bank (0x43cdcc), its stop drops it
#: (0x43c254), and mapping a bank unmaps only the OTHER banks with no sound playing
#: (0x3b57d8): so as many banks as there are channels can be mapped beside image.bin.
SOUND_CHANNELS = 8


class SoundBankError(MD.MasterDirError):
    """The bank could not be planned or written."""


def bank_name(cat):
    """The file the game's loader opens for category *cat*."""
    return "image-sc%02d.bin" % int(cat)


def category_of(name):
    """The category id a bank file name carries, or None."""
    from .category import read_category_id
    return read_category_id(name)


# --------------------------------------------------------------------------
# image.bin's category list
# --------------------------------------------------------------------------
def category_slots(image_header):
    """``(count, ids, room)`` from ``image.bin``'s header: the categories it
    names, their ids, and how many more ids fit before the header's first
    table (``hdr[0x28]``) begins."""
    h = bytes(image_header)
    count = struct.unpack_from("<I", h, IMG_CAT_COUNT)[0]
    first_table = struct.unpack_from("<I", h, HDR_FRAG_TABLE)[0]
    if not 0 <= count <= 64 or first_table < IMG_CAT_IDS + 4 * count:
        raise SoundBankError("image.bin names %d categories past its header's "
                             "first table at 0x%x" % (count, first_table))
    ids = [struct.unpack_from("<I", h, IMG_CAT_IDS + 4 * i)[0] for i in range(count)]
    room = (first_table - IMG_CAT_IDS) // 4 - count
    return count, ids, room


def next_category_ids(ids, taken=(), n=1):
    """The *n* lowest category ids the card does not use: not in *ids*
    (``image.bin``'s list) and not among *taken* (bank files present in the
    game's directory, by name or id)."""
    used = {int(i) for i in ids}
    for t in taken:
        c = category_of(str(t)) if not isinstance(t, int) else t
        if c is not None:
            used.add(int(c))
    out = []
    for c in range(MIN_CATEGORY, MAX_CATEGORY + 1):
        if c not in used:
            out.append(c)
            if len(out) == n:
                return out
    raise SoundBankError("no category id is free for a new sound bank")


def header_writes_new_categories(image_header, cats):
    """``{offset: bytes}`` that make ``image.bin``'s header name the new
    categories *cats* after the ones it has: the count word and one id word
    each.  Raises when the header has no room for them."""
    count, ids, room = category_slots(image_header)
    cats = [int(c) for c in cats]
    if len(cats) > room:
        raise SoundBankError("image.bin's header has room for %d more sound bank(s), "
                             "not %d" % (room, len(cats)))
    for c in cats:
        if c in ids or cats.count(c) > 1:
            raise SoundBankError("category %d is already a sound bank of this card" % c)
    out = {IMG_CAT_COUNT: struct.pack("<I", count + len(cats))}
    for i, c in enumerate(cats):
        out[IMG_CAT_IDS + 4 * (count + i)] = struct.pack("<I", c)
    return out


# --------------------------------------------------------------------------
# the bank's geometry
# --------------------------------------------------------------------------
#: One sound to put in the bank: the record of its HOST (the stock record the
#: game looks the carrier up by, 24 bytes), the host's decoded length, the
#: length the bank's record declares and how many bytes its body takes.
BankEdit = collections.namedtuple("BankEdit", "idx record old_length new_length body_bytes")
#: Where a sound landed: its host idx, its record number in the bank, its body.  PAD-608: a
#: FRAGMENT past the records that plays one of them (*record*, that record's number; ``None`` for a
#: record's own fragment) - a music mode's file several of the game's sound ids play, each with a
#: descriptor of its own - is a placement too, *new_idx* its fragment number, the rest its record's.
BankPlacement = collections.namedtuple("BankPlacement",
                                       "idx new_idx body_off length body_bytes desc_off record",
                                       defaults=(None,))


def records(places):
    """The placements of *places* that are records (not a fragment that plays one, PAD-608)."""
    return [pl for pl in places if pl.record is None]


def record_of(pl):
    """The bank record placement *pl*'s fragment plays: its own number, or *record*."""
    return pl.new_idx if pl.record is None else pl.record


def fragment_stride(image_header):
    """Slots per fragment, read off ``image.bin``'s own tables: the fragment
    table (``hdr[0x28]``) runs to the data block (``hdr[0x48]``), 8 bytes a
    slot, ``hdr[0x5c]`` fragments.  :data:`DEFAULT_STRIDE` when the header
    does not say."""
    h = bytes(image_header)
    table, data, nfrag = (struct.unpack_from("<I", h, o)[0]
                          for o in (HDR_FRAG_TABLE, HDR_DATA, HDR_FRAGMENTS))
    if nfrag and data > table and (data - table) % (nfrag * FRAG_SLOT) == 0:
        stride = (data - table) // (nfrag * FRAG_SLOT)
        if 1 <= stride <= 16:
            return stride
    return DEFAULT_STRIDE


def slot_vf2_offset(slot):
    """Where in the vf2 keystream the four bytes whitening fragment slot
    *slot* (fragment * stride + variant) are: ``((slot >> 6) & 0x3f) << 8 |
    (slot & 0x7f)``, as the resolver computes it on every build read."""
    return (((slot >> 6) & 0x3F) << 8) | (slot & 0x7F)


def emulator_bank_room(image_size):
    """The biggest bank the emulator can serve beside an ``image.bin`` of
    *image_size* bytes: it maps the bank in the game's own 32-bit address
    space right after image.bin's window (:data:`.emulator.DESC_BASE`), so
    both have to end under 4 GiB.  The game itself takes a bank up to
    :data:`MAX_BANK_BYTES`; a build splits its sounds over more banks when
    this is the smaller."""
    from .emulator import DESC_BASE
    return max(0, 0x1_0000_0000 - DESC_BASE - int(image_size) - 0x120000)


def bank_sid(cat, n):
    """The sound id the game plays bank *cat*'s fragment *n* by."""
    return (int(cat) << 16) | int(n)


def _tables_len(n, stride):
    """The fragment table and the 16-byte data block after the header."""
    return n * stride * FRAG_SLOT + 16


def _bodies_start(nfrag, stride):
    """Where a bank's first body starts: past the header and room for the
    fragment table of :func:`~.masterdir.grow_slots` fragments, not just
    *nfrag*, behind its zero pad (PAD-677: a mode's added sound no longer
    moves every body of the bank, so the others' kept encodes still fit).
    The room past the table and its data block is never read: the header
    names both and each record its own body."""
    return MD.align16(HDR_LEN + _tables_len(MD.grow_slots(nfrag), stride)) + MD.BODY_PAD


def bank_bytes(bodies, stride=DEFAULT_STRIDE, aliases=0, desc_slot=DESC_SLOT, mapped=0):
    """What a bank with the appended *bodies* (byte sizes) measures: the
    header, the fragment table, each body behind its zero pad, the
    descriptor block, then the directory and its trailer.  *aliases*: the
    fragments past the records that play one of them (PAD-608), each a slot
    in the fragment table and the descriptor block.  PAD-779: *desc_slot* the
    room each descriptor gets, *mapped* how many of the aliases the sid map's
    extension names (:func:`sid_map_ext_len`)."""
    bodies = list(bodies)
    n = len(bodies)
    nfrag = n + int(aliases)
    body_end = (_bodies_start(nfrag, stride)
                + sum(MD.BODY_PAD + b for b in bodies) - MD.BODY_PAD)
    return (MD.align16(MD.align16(body_end + MD.BODY_PAD) + nfrag * int(desc_slot))
            + sid_map_ext_len(mapped) + sid_map_len(n) + MD.tail_len(n))


def sid_map_len(n):
    """Bytes the sid map of a bank of *n* sounds takes: :data:`SID_MAP_MAGIC`, the
    count, one u32 a fragment, rounded up to 16."""
    return MD.align16(8 + 4 * int(n))


def sid_map_ext_len(m):
    """PAD-779: bytes the sid map's extension of *m* fragments takes (none for 0)."""
    return MD.align16(8 * int(m) + 8) if m else 0


def sid_map_block(orig, n):
    """The sid map for a bank of *n* fragments: *orig* ``{fragment: game sid}``."""
    out = bytearray(sid_map_len(n))
    out[0:4] = SID_MAP_MAGIC
    struct.pack_into("<I", out, 4, int(n))
    for k, sid in (orig or {}).items():
        if not 0 <= int(k) < n:
            raise SoundBankError("sid map: fragment %d of %d" % (k, n))
        struct.pack_into("<I", out, 8 + 4 * int(k), int(sid) & 0xffffffff)
    return bytes(out)


def write_sid_map(path, md_off, n, orig):
    """Write the sid map of a staged bank whose directory of *n* records is at
    *md_off* (it sits just before the directory).  PAD-779: the fragments of
    *orig* past the records go into the extension before it, which the bank
    has room for when it was planned with them (:func:`plan_bank` *mapped*)."""
    orig = {int(k): int(v) for k, v in (orig or {}).items()}
    more = sorted((k, v) for k, v in orig.items() if k >= n)
    at = int(md_off) - sid_map_len(n)
    with open(path, "r+b") as f:
        f.seek(at)
        f.write(sid_map_block({k: v for k, v in orig.items() if k < n}, n))
        if more:
            ext = bytearray(sid_map_ext_len(len(more)))
            for j, (k, v) in enumerate(more):
                struct.pack_into("<II", ext, 8 * j, k, v & 0xffffffff)
            struct.pack_into("<I", ext, len(ext) - 8, len(more))
            ext[len(ext) - 4:] = SID_MAP_EXT_MAGIC
            f.seek(at - len(ext))
            f.write(bytes(ext))


def read_sid_map(data):
    """``{fragment: game sid}`` out of a whole bank file's bytes *data*: the game
    sounds a PAD bank stands in for (:func:`read_sid_map_at`)."""
    data = bytes(data)
    return read_sid_map_at(lambda off, n: data[off:off + n], len(data))


def read_sid_map_at(read, size):
    """``{fragment: game sid}`` of the bank *size* bytes long that ``read(off, n)``
    reads: the game sounds a PAD bank stands in for.  ``{}`` for a vendor bank, a bank
    built before PAD-606, or anything that is not a bank."""
    try:
        h = bytes(read(0, HDR_LEN))
        if len(h) < HDR_LEN:
            return {}
        md_off, count = MD.header_geometry(h)
        if not 0 < count <= MD.MAX_RECORDS or md_off + MD.tail_len(count) != size:
            return {}
        if bytes(read(md_off + MD.align16(MD.RECORD_SIZE * count) + 4, 4)) != PAD_TRAILER:
            return {}
        at = md_off - sid_map_len(count)
        if at < HDR_LEN:
            return {}
        block = bytes(read(at, sid_map_len(count)))
        if block[:4] != SID_MAP_MAGIC or struct.unpack_from("<I", block, 4)[0] != count:
            return {}
        out = {}
        for k in range(count):
            sid = struct.unpack_from("<I", block, 8 + 4 * k)[0]
            if sid:
                out[k] = sid
        # PAD-779: the fragments past the records, in the extension before it
        foot = bytes(read(at - 8, 8)) if at - 8 >= HDR_LEN else b""
        if len(foot) == 8 and foot[4:] == SID_MAP_EXT_MAGIC:
            m = struct.unpack_from("<I", foot, 0)[0]
            if 0 < m <= MD.MAX_RECORDS and at - sid_map_ext_len(m) >= HDR_LEN:
                ext = bytes(read(at - sid_map_ext_len(m), 8 * m))
                for j in range(m):
                    k, sid = struct.unpack_from("<II", ext, 8 * j)
                    if k >= count and sid:
                        out[k] = sid
        return out
    except (ValueError, struct.error, MD.MasterDirError):
        return {}
def alone_bank_room(image_size):
    """The biggest bank one long sound can have to itself beside an ``image.bin``
    of *image_size* bytes (PAD-607): what is left of :data:`MAPPED_MAX` with
    image.bin mapped, no bigger than :data:`BANK_MAX_SEEN` or the emulator's
    window (:func:`emulator_bank_room`), which builds and checks it."""
    return max(0, min(MAPPED_MAX - int(image_size), BANK_MAX_SEEN, MAX_BANK_BYTES,
                      emulator_bank_room(image_size)))


def split_banks(edits, limit=MAX_BANK_BYTES, stride=DEFAULT_STRIDE, alone=None):
    """*edits* (:class:`BankEdit`) split into banks in order, each as full as
    *limit* allows.  A sound too big for a *limit* bank gets a bank of its own
    when it fits *alone* bytes (PAD-607: a long song).  Raises when one sound
    alone is bigger than a bank can be."""
    banks, cur = [], []
    alone = limit if alone is None else max(int(alone), limit)
    for e in edits:
        one = bank_bytes([e.body_bytes], stride)
        if one > alone:
            raise SoundBankError("sound idx %d alone (%d MB) is bigger than a sound bank can be"
                                 % (e.idx, e.body_bytes // 10**6))
        if one > limit:
            banks.append([e])
            continue
        if cur and bank_bytes([x.body_bytes for x in cur] + [e.body_bytes], stride) > limit:
            banks.append(cur)
            cur = []
        cur.append(e)
    if cur:
        banks.append(cur)
    return banks


#: PAD-779: sounds that go into one bank together - one sound, or a song's whole sequence
#: (every record the sound ids that play it name, each of those sound ids a fragment) -
#: *edits* the records, *aliases* its fragments past them, *desc_slot* the room its
#: descriptors need and *mapped* the aliases the sid map's extension names.
BankUnit = collections.namedtuple("BankUnit", "edits aliases desc_slot mapped",
                                  defaults=(0, DESC_SLOT, 0))


def unit_bytes(units, stride=DEFAULT_STRIDE):
    """What one bank holding every :class:`BankUnit` of *units* measures."""
    units = list(units)
    return bank_bytes([e.body_bytes for u in units for e in u.edits], stride,
                      aliases=sum(int(u.aliases) for u in units),
                      desc_slot=max([DESC_SLOT] + [int(u.desc_slot) for u in units]),
                      mapped=sum(int(u.mapped) for u in units))


def split_units(units, limit=MAX_BANK_BYTES, stride=DEFAULT_STRIDE):
    """PAD-779: :func:`split_banks` for :class:`BankUnit` s: *units* split into banks
    in order, each as full as *limit* allows, a unit never split; ``[[unit, ...]]``.
    A unit bigger than *limit* is a bank of its own (the caller checks it fits)."""
    banks, cur = [], []
    for u in units:
        if unit_bytes([u], stride) > limit:
            banks.append([u])
            continue
        if cur and unit_bytes(cur + [u], stride) > limit:
            banks.append(cur)
            cur = []
        cur.append(u)
    if cur:
        banks.append(cur)
    return banks


def plan_bank(edits, stride=DEFAULT_STRIDE, aliases=(), desc_slot=DESC_SLOT, mapped=0):
    """``(directory, placements)`` for a bank holding *edits*: record *n* is a
    copy of edit *n*'s host record with only its body offset and length word
    replaced (as :func:`masterdir.plan_grow_records` appends to ``image.bin``).
    After the header come the fragment table (one fragment of *stride* slots
    a sound) and a 16-byte data block, then the bodies each behind a zero
    pad, then the descriptor block (:data:`DESC_SLOT` a sound) and the
    directory, which carries :data:`PAD_TRAILER`.  Each placement names its
    descriptor's offset; the tables themselves are written by
    :func:`write_tables` once the records' keys are known.

    PAD-608: *aliases* ``[host idx, ...]``: one more fragment each, past the
    records, that plays that host's record (a placement with ``record``
    set), for a sound several of the game's sound ids play, each through a
    descriptor of its own.

    PAD-779: *desc_slot* the room each descriptor gets (up to :data:`DESC_SLOT_MAX`, for a
    song's whole sequence), and room for the sid map's extension of *mapped* aliases (each a
    sound id of the game's that plays a song in parts)."""
    edits = [BankEdit(*e) for e in edits]
    desc_slot = int(desc_slot)
    if not DESC_SLOT <= desc_slot <= DESC_SLOT_MAX or desc_slot % 16:
        raise SoundBankError("a descriptor slot of %d bytes" % desc_slot)
    if not edits:
        raise SoundBankError("plan_bank called with no sounds")
    xors = set()
    for e in edits:
        if len(e.record) != MD.RECORD_SIZE:
            raise SoundBankError("idx %d: the host record is %d bytes" % (e.idx, len(e.record)))
        if e.new_length <= 0 or e.body_bytes <= 0:
            raise SoundBankError("idx %d: a bank record needs a length and a body" % e.idx)
        xors.add(MD._u32(e.record, 16) ^ (e.old_length & 0xffffffff))
    if len(xors) > 1:
        raise SoundBankError(
            "the bank's records disagree about this build's length constant (%s)"
            % ", ".join("0x%08x" % v for v in sorted(xors)))
    aliases = [int(i) for i in aliases or ()]
    nfrag = len(edits) + len(aliases)
    off = _bodies_start(nfrag, stride)
    records, places = [], []
    for n, e in enumerate(edits):
        word = MD._u32(e.record, 16) ^ (e.old_length & 0xffffffff) ^ (e.new_length & 0xffffffff)
        records.append(MD.set_geometry(e.record, body_off=off, length_word=word))
        places.append([e.idx, n, off, e.new_length, e.body_bytes])
        off += e.body_bytes + MD.BODY_PAD
    desc0 = MD.align16(off)
    places = [BankPlacement(*pl, desc_off=desc0 + desc_slot * pl[1]) for pl in places]
    by_idx = {pl.idx: pl for pl in places}
    for j, idx in enumerate(aliases):
        pl = by_idx.get(idx)
        if pl is None:
            raise SoundBankError("a fragment for idx %d, which is not in the bank" % idx)
        n = len(edits) + j
        places.append(pl._replace(new_idx=n, desc_off=desc0 + desc_slot * n, record=pl.new_idx))
    # the sid map (PAD-606) between the descriptors and the directory, its extension
    # (PAD-779) before it
    md_off = (MD.align16(desc0 + desc_slot * nfrag) + sid_map_ext_len(mapped)
              + sid_map_len(len(edits)))
    directory = MD.Directory(b"".join(records), len(records), md_off, 0,
                             trailer=PAD_TRAILER)
    return directory, places


def bank_header(size, md_off, count, nfrag=0, stride=DEFAULT_STRIDE):
    """The 0x68-byte header of a bank *size* bytes long whose directory of
    *count* records is at *md_off*: the fragment table of *nfrag* fragments
    right after the header, the data block after that."""
    h = bytearray(HDR_LEN)
    struct.pack_into("<I", h, HDR_FRAG_TABLE, HDR_LEN)
    struct.pack_into("<I", h, HDR_END_WORD, (size - 4) & 0xffffffff)
    struct.pack_into("<I", h, HDR_MD_OFF, md_off)
    struct.pack_into("<I", h, HDR_DATA, HDR_LEN + nfrag * stride * FRAG_SLOT)
    struct.pack_into("<I", h, HDR_FRAGMENTS, nfrag)
    struct.pack_into("<I", h, HDR_COUNT, count)
    return bytes(h)


def write_bank(path, directory, places, scaffold, emu, stride=DEFAULT_STRIDE):
    """Write the bank file: the header, each body's zero pad and its scaffold
    (*scaffold* ``{new_idx: bytes}``, real card audio repeated to fill -- the
    encoder overwrites it, but the chain derive runs over these bytes first and
    a degenerate body gives a degenerate chain), then the directory packed
    under the firmware's cipher (*emu*, a booted emulator on the card's
    program).  The fragment table and the descriptor block are left zero for
    :func:`write_tables`.  Returns the file size."""
    tail = MD.write_directory(directory, emu)[directory.md_off]
    size = directory.md_off + len(tail)
    with open(path, "wb") as f:
        f.write(bank_header(size, directory.md_off, directory.count, len(places), stride))
        for pl in records(places):
            src = scaffold[pl.new_idx] or b"\x00"
            reps = -(-pl.body_bytes // len(src))
            f.seek(pl.body_off - MD.BODY_PAD)
            f.write(b"\x00" * MD.BODY_PAD)
            f.write((src * reps)[:pl.body_bytes])
        f.seek(directory.md_off)
        f.write(tail)
    if os.path.getsize(path) != size:
        raise SoundBankError("the bank came to %d bytes, not %d" % (os.path.getsize(path), size))
    return size


def write_tables(path, places, descs, vf2, ks_of, stride=DEFAULT_STRIDE, desc_slot=DESC_SLOT):
    """Put the play tables into a staged bank: for placement *n*, *stride*
    fragment slots each naming its descriptor's offset (whitened with four
    bytes of *vf2*, the firmware's keystream window, at
    :func:`slot_vf2_offset`), and the descriptor *descs[new_idx]* (plain
    bytes, at most :data:`DESC_SLOT`) at ``desc_off`` whitened with *vf2* at
    ``ks_of(desc_off)``, the offset the resolver will derive.  Returns
    ``{new_idx: keystream offset}``.  PAD-779: *desc_slot* is the bank's room
    a descriptor (:func:`plan_bank`)."""
    vf2 = bytes(vf2)
    out = {}
    with open(path, "r+b") as f:
        for pl in places:
            plain = bytes(descs[pl.new_idx])
            if not 0 < len(plain) <= int(desc_slot):
                raise SoundBankError("record %d: a descriptor of %d bytes does not fit its "
                                     "%d-byte slot" % (pl.new_idx, len(plain), int(desc_slot)))
            for k in range(stride):
                slot = pl.new_idx * stride + k
                o = slot_vf2_offset(slot)
                if o + 4 > len(vf2):
                    raise SoundBankError("fragment slot %d whitens past the keystream window" % slot)
                word = pl.desc_off ^ struct.unpack_from("<I", vf2, o)[0]
                f.seek(HDR_LEN + slot * FRAG_SLOT)
                f.write(struct.pack("<II", word & 0xffffffff, 0))
            ks = int(ks_of(pl.desc_off))
            if ks < 0 or ks + len(plain) > len(vf2):
                raise SoundBankError("record %d: descriptor keystream offset %#x is past the window"
                                     % (pl.new_idx, ks))
            f.seek(pl.desc_off)
            f.write(bytes(a ^ b for a, b in zip(plain, vf2[ks:ks + len(plain)])))
            out[pl.new_idx] = ks
    return out


def read_bank_header(path):
    """``(md_off, count, size)`` of a bank file."""
    with open(path, "rb") as f:
        h = f.read(HDR_LEN)
        f.seek(0, 2)
        size = f.tell()
    if len(h) < HDR_LEN:
        raise SoundBankError("%s is shorter than a bank header" % os.path.basename(path))
    md_off, count = MD.header_geometry(h)
    return md_off, count, size


def is_pad_bank(path):
    """True when the bank at *path* is one this app made: its directory's
    trailer word is :data:`PAD_TRAILER`.  False for a vendor bank, or a file
    that is not a bank at all."""
    try:
        md_off, count, size = read_bank_header(path)
        if not 0 < count <= MD.MAX_RECORDS or md_off + MD.tail_len(count) != size:
            return False
        with open(path, "rb") as f:
            f.seek(md_off + MD.align16(MD.RECORD_SIZE * count) + 4)
            return f.read(4) == PAD_TRAILER
    except (OSError, ValueError, struct.error, MD.MasterDirError):
        return False
