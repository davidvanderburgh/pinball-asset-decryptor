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

A record in a bank registers with the game's sound container under a key that
carries its category in bits 13..28 of the second word (measured on Deadpool
LE 1.16), so no play table of a cat-0 sound can be re-pointed at it: a bank
sound is reached by the mode runtime's key swap at the game's record lookup
(``pm_sound_swap``), which hands the game the bank record's eight-byte key.
That is why a bank carries no fragment table: nothing resolves a sid of its
category.

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
#: Category ids the loader can name: ``image-sc%02d.bin``.
MIN_CATEGORY, MAX_CATEGORY = 1, 99


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
#: Where a sound landed: its host idx, its record number in the bank, its body.
BankPlacement = collections.namedtuple("BankPlacement", "idx new_idx body_off length body_bytes")


def bank_bytes(bodies):
    """What a bank with the appended *bodies* (byte sizes) measures: the
    header, each body behind its zero pad, then the directory and its trailer."""
    bodies = list(bodies)
    return (MD.align16(HDR_LEN + sum(MD.BODY_PAD + b for b in bodies) + MD.BODY_PAD)
            + MD.tail_len(len(bodies)))


def split_banks(edits, limit=MAX_BANK_BYTES):
    """*edits* (:class:`BankEdit`) split into banks in order, each as full as
    *limit* allows.  Raises when one sound alone is bigger than a bank."""
    banks, cur = [], []
    for e in edits:
        if bank_bytes([e.body_bytes]) > limit:
            raise SoundBankError("sound idx %d alone (%d MB) is bigger than a sound bank can be"
                                 % (e.idx, e.body_bytes // 10**6))
        if cur and bank_bytes([x.body_bytes for x in cur] + [e.body_bytes]) > limit:
            banks.append(cur)
            cur = []
        cur.append(e)
    if cur:
        banks.append(cur)
    return banks


def plan_bank(edits):
    """``(directory, placements)`` for a bank holding *edits*: record *n* is a
    copy of edit *n*'s host record with only its body offset and length word
    replaced (as :func:`masterdir.plan_grow_records` appends to ``image.bin``),
    the bodies follow the header each behind a zero pad, and the directory
    comes after the last body.  The directory carries :data:`PAD_TRAILER`."""
    edits = [BankEdit(*e) for e in edits]
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
    off = HDR_LEN + MD.BODY_PAD
    records, places = [], []
    for n, e in enumerate(edits):
        word = MD._u32(e.record, 16) ^ (e.old_length & 0xffffffff) ^ (e.new_length & 0xffffffff)
        records.append(MD.set_geometry(e.record, body_off=off, length_word=word))
        places.append(BankPlacement(e.idx, n, off, e.new_length, e.body_bytes))
        off += e.body_bytes + MD.BODY_PAD
    md_off = MD.align16(off)
    directory = MD.Directory(b"".join(records), len(records), md_off, 0,
                             trailer=PAD_TRAILER)
    return directory, places


def bank_header(size, md_off, count):
    """The 0x68-byte header of a bank *size* bytes long whose directory of
    *count* records is at *md_off*: no fragment table and no data block (both
    begin and end at the header's end), as nothing resolves a sid of ours."""
    h = bytearray(HDR_LEN)
    struct.pack_into("<I", h, HDR_FRAG_TABLE, HDR_LEN)
    struct.pack_into("<I", h, HDR_END_WORD, (size - 4) & 0xffffffff)
    struct.pack_into("<I", h, HDR_MD_OFF, md_off)
    struct.pack_into("<I", h, HDR_DATA, HDR_LEN)
    struct.pack_into("<I", h, HDR_FRAGMENTS, 0)
    struct.pack_into("<I", h, HDR_COUNT, count)
    return bytes(h)


def write_bank(path, directory, places, scaffold, emu):
    """Write the bank file: the header, each body's zero pad and its scaffold
    (*scaffold* ``{new_idx: bytes}``, real card audio repeated to fill -- the
    encoder overwrites it, but the chain derive runs over these bytes first and
    a degenerate body gives a degenerate chain), then the directory packed
    under the firmware's cipher (*emu*, a booted emulator on the card's
    program).  Returns the file size."""
    tail = MD.write_directory(directory, emu)[directory.md_off]
    size = directory.md_off + len(tail)
    with open(path, "wb") as f:
        f.write(bank_header(size, directory.md_off, directory.count))
        for pl in places:
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
