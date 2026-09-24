"""Build a Spike 2 card for a BIGGER SD card: the games partition grown to
fill Stern's 16 GB or 32 GB card class.

WHY.  Every file a build replaces whole (full-size videos, a grown sound bank,
a rebuilt game program) lands on the card's games partition, p3.  On an 8 GB
class card that partition is whatever Stern left free: 368 MB on a stock
Godzilla 1.16.  A retheme of hundreds of videos and a longer soundtrack runs
out of it after twenty minutes of encoding (PAD-176), while the SD card in the
machine is usually 16 or 32 GB with the rest of it unused.

WHAT STERN ALREADY DOES.  Stern ships the SAME card at three sizes.  Read off
the stock images (godzilla_pro 8G, jaws_le 16G, metallica 32G):

    p1  FAT boot     LBA 8192,   16384 sectors       every class
    p2  rootfs       LBA 24576,  688128 sectors      every class
    p3  games        LBA 712704, <class> sectors     only its LENGTH differs
    p4  extended     p3's end + 2, 1239038 sectors   moves with p3's end
      p5 /data, p6 /dump                            their EBRs are byte-identical
    image            p4's end + 2 sectors

and every partition entry past p2 carries the capped CHS bytes (03 e0 ff), so
the only bytes of the partition tables that differ between an 8G and a 16G
card are MBR entry 3's sector count and entry 4's start LBA.  The EBRs hold
RELATIVE addresses and do not change at all.  (The MBR's disk id differs by
class too, and Stern's own 8G cards ship with two different ones; nothing on
the machine reads it, so a grown card keeps its original's.)

WHAT THIS MODULE DOES.  :func:`expand_image` takes a build's output (a copy of
the original with the build's in-place patches already in it) and turns it into
the bigger class in place: the file grows (sparse where the filesystem allows),
the extended partition (the two EBRs, /data and /dump) is copied verbatim to
its new place at the end, read back and compared, the two MBR fields are
rewritten (the commit point), and ``resize2fs`` grows p3's ext4 to fill the
partition through a loop device bounded to it, followed by a read-only
``e2fsck``.  The partition table that comes out is Stern's own for that
class.  Nothing before p3's end moves: p1, p2 and p3's start are where they
were, so every offset the build computed from the original is still right.

THE RULES THAT KEEP IT SAFE.
  * Only a card laid out exactly like Stern's (the table above, a stock class
    size, two logicals) is expanded; anything else is refused with the reason
    before a byte is written (a multi-boot card, a hand-edited table).
  * The move is verified by reading both copies back BEFORE the MBR is
    rewritten, so a failed copy leaves a card whose table still points at the
    untouched originals.
  * resize2fs only ever grows here.  :func:`check_blocks_unmoved` compares
    every regular file's extent map on p3 against the original card after the
    resize: the build's in-place patches were resolved through the ORIGINAL's
    extents, and the next build's update relies on them too.
  * resize2fs never sees the image FILE: handed a regular file it truncates
    it to the filesystem's length at the end, offset or not (see
    :class:`_E2fs`).  It works on a loop device limited to p3.
  * The card that comes out must pass ``e2fsck -fn`` (read-only) on p3, keep
    its size to the byte, and read back as the planned partition table.  A
    clean e2fsck alone proves little: it passed on a card resize2fs had
    truncated, because it never reads a new group's uninitialised blocks.
"""

import collections
import os
import shlex
import struct
import sys
import time

from ...core.longpath import ext as _lp

SECTOR = 512
#: Stern's image size per card class, read off the stock images (every title of
#: a class is the same size to the byte).
CARD_SIZES = collections.OrderedDict([
    ("8G", 7861174272),
    ("16G", 15494807552),
    ("32G", 30359420928),
])
#: The build option, set by the Write tab (webui/tabs/write.py) like the other
#: Stern build options: unset means "the original's size", which is what every
#: headless caller has always built.
ENV = "PAD_STERN_CARD_SIZE"
#: Set ("1") while the app's Port + build runs.  A port builds every card at
#: its own original's size, whatever the Write tab says (app.py pops ENV for
#: the whole chain), so a ported card that runs out of room is never told to
#: set SD card size on the Write tab: that is for building the card on its own.
FIXED_ENV = "PAD_STERN_CARD_SIZE_FIXED"

P1 = (0x0C, 8192, 16384)
P2 = (0x83, 24576, 688128)
P3_START = 712704
LINUX = 0x83
EXT_TYPES = (0x05, 0x0F)
TAIL = 2                    # every stock image ends 2 sectors after p4
LOGICALS = 2                # p5 (/data) and p6 (/dump)
CHUNK = 8 << 20


class CardSizeError(Exception):
    """The card can't be built at the size asked for (a user-facing
    sentence)."""


class Cancelled(CardSizeError):
    """The user cancelled while the card was being grown.  The build's
    caller treats it like any other cancel, not as a failure."""


def words(cls):
    """``"16 GB"`` for ``"16G"``: the words the Write tab and the packaging
    use, for every sentence a user reads."""
    return str(cls or "").replace("G", " GB") if cls else ""


def supported():
    """Whether this computer can grow a card at all.  macOS has no loop
    devices, which is the only safe way to hand resize2fs the partition (see
    :class:`_E2fs`), so the option is not offered there yet."""
    return sys.platform != "darwin"


#: ext4's incompat "needs_recovery" bit: the journal holds changes that were
#: never written home, because the filesystem was not cleanly unmounted.
_NEEDS_RECOVERY = 0x4


def journal_pending(f):
    """True when the games partition of the card open as *f* was not cleanly
    unmounted and its journal still has to be replayed."""
    f.seek(P3_START * SECTOR + 1024)
    sb = f.read(1024)
    if len(sb) < 1024 or sb[0x38:0x3A] != b"\x53\xef":
        return False
    return bool(struct.unpack_from("<I", sb, 0x60)[0] & _NEEDS_RECOVERY)


Layout = collections.namedtuple(
    "Layout", "size laid_out p3_count p4_start p4_count logicals")
# size       the file's size in bytes
# laid_out   the Stern class size the table describes (p4's end + TAIL), bytes
# p3_count   p3's length in sectors
# p4_start   the extended partition's start LBA (EBR1)
# p4_count   its length in sectors
# logicals   [(ebr_lba, start_lba, count), ...] for p5, p6


def requested():
    """The card size the build was asked for (``"16G"`` / ``"32G"``), or
    ``None`` for the original's own size."""
    v = (os.environ.get(ENV) or "").strip().upper()
    return v if v in CARD_SIZES and v != "8G" else None


def size_fixed():
    """Whether this build can't take an SD card size at all: Port + build
    (:data:`FIXED_ENV`) makes every card at its own original's size."""
    return os.environ.get(FIXED_ENV) == "1"


def bigger_card(cls, free=None, fixed=False):
    """The words that send a user to a build for the *cls* SD card, with the
    room its games partition then has (*free* bytes) when known, to follow
    "if the SD card in the machine is 16 GB or bigger, ...": "build it for a
    16 GB SD card (SD card size on the Write tab: 7.87 GB free there)".
    With *fixed* (:func:`size_fixed`) the build is a port's, which can't
    take a size, so they say to build the card on its own instead."""
    room = size_words(free) + " free there" if free is not None else ""
    if fixed:
        return ("build this card on its own from the Write tab for a %s SD "
                "card (%sa port builds every card at its original's size)"
                % (words(cls), room + "; " if room else ""))
    return ("build it for a %s SD card (SD card size on the Write tab%s)"
            % (words(cls), ": " + room if room else ""))


def class_of(nbytes):
    """``"8G"`` / ``"16G"`` / ``"32G"`` for a Stern image size, else None."""
    for name, size in CARD_SIZES.items():
        if int(nbytes) == size:
            return name
    return None


def _entry(buf, i):
    raw = buf[446 + 16 * i: 462 + 16 * i]
    ptype = raw[4]
    start, count = struct.unpack("<II", raw[8:16])
    return ptype, start, count


def read_layout(f, size=None):
    """The card's :class:`Layout` from the open binary file *f*, or
    :class:`CardSizeError` saying why this is not a card laid out the way
    Stern lays one out."""
    if size is None:
        f.seek(0, os.SEEK_END)
        size = f.tell()
    f.seek(0)
    mbr = f.read(SECTOR)
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
        raise CardSizeError("it has no partition table")
    e = [_entry(mbr, i) for i in range(4)]
    if e[0] != P1 or e[1] != P2:
        raise CardSizeError("its boot and system partitions are not where a "
                            "Spike 2 card has them")
    t3, s3, c3 = e[2]
    if t3 != LINUX or s3 != P3_START or not c3:
        raise CardSizeError("its games partition is not where a Spike 2 card "
                            "has it")
    t4, s4, c4 = e[3]
    if t4 not in EXT_TYPES or s4 < s3 + c3 or not c4:
        raise CardSizeError("it has no extended partition after the games "
                            "partition (a multi-boot card, or a hand-edited "
                            "table)")
    logicals, ebr, seen = [], s4, set()
    while ebr and len(logicals) <= LOGICALS:
        if ebr in seen or not (s4 <= ebr < s4 + c4):
            raise CardSizeError("its extended partition's chain is broken")
        seen.add(ebr)
        f.seek(ebr * SECTOR)
        sec = f.read(SECTOR)
        if len(sec) < SECTOR or sec[510:512] != b"\x55\xaa":
            raise CardSizeError("its extended partition's chain is broken")
        lt, ls, lc = _entry(sec, 0)
        nt, ns, _nc = _entry(sec, 1)
        if lt != LINUX or not lc:
            raise CardSizeError("its extended partition holds something other "
                                "than the two Linux partitions Stern puts there")
        logicals.append((ebr, ebr + ls, lc))
        ebr = s4 + ns if (nt in EXT_TYPES and ns) else 0
    if len(logicals) != LOGICALS:
        raise CardSizeError("it has %s logical partitions where Stern's cards "
                            "have two (a multi-boot card is sized by the "
                            "Multi-boot tab)"
                            % ("more than two" if len(logicals) > LOGICALS
                               else len(logicals)))
    for _ebr, ls, lc in logicals:
        if ls + lc > s4 + c4:
            raise CardSizeError("a partition runs past the end of the "
                                "extended partition")
    laid_out = (s4 + c4 + TAIL) * SECTOR
    if class_of(laid_out) is None:
        raise CardSizeError("its partitions describe a %.2f GB card, which is "
                            "not one of Stern's card sizes" % (laid_out / 1e9))
    if size < laid_out:
        raise CardSizeError("the file is shorter than its own partition table "
                            "says (a truncated image)")
    return Layout(int(size), laid_out, c3, s4, c4, logicals)


def plan(layout, target):
    """``(delta_sectors, new_layout)`` for growing *layout* to the *target*
    class; ``(0, layout)`` when the card is that size or bigger already."""
    new_laid = CARD_SIZES[target]
    delta = (new_laid - layout.laid_out) // SECTOR
    if delta <= 0:
        return 0, layout
    new = Layout(max(layout.size, new_laid), new_laid,
                 layout.p3_count + delta, layout.p4_start + delta,
                 layout.p4_count,
                 [(e + delta, s + delta, c) for e, s, c in layout.logicals])
    return delta, new


def linux_parts(layout):
    """``[(byte_offset, byte_size), ...]`` of the Linux partitions of
    *layout*, largest first: :func:`.formats.linux_partitions`' answer for a
    card with this layout.  That reads the four MBR entries only, so it is
    p3 and p2 - the app never locates /data or /dump, and no build writes
    them."""
    parts = [(P3_START, layout.p3_count), (P2[1], P2[2])]
    parts.sort(key=lambda p: p[1], reverse=True)
    return [(s * SECTOR, c * SECTOR) for s, c in parts]


def target_for(original_path, target=None):
    """The class a build of *original_path* comes out at when *target* (or
    the build option, when None) is asked for: the class name when the card
    will actually grow, else ``None``.  Raises :class:`CardSizeError` when
    the original can't be grown."""
    target = target or requested()
    if not target:
        return None
    with open(_lp(original_path), "rb") as f:
        try:
            layout = read_layout(f)
        except CardSizeError as e:
            raise CardSizeError(
                "This card can't be built for a %s SD card: %s."
                % (words(target), e))
        delta, _new = plan(layout, target)
        if delta <= 0:
            return None
        # The check that runs before the games partition grows replays an
        # unfinished journal, and the replay rewrites files the build has
        # already patched by where they sat on the original (a real library
        # image, turtles_le 1.58.1 "1987", has one pending).  Refuse up front
        # instead of discarding the build after the whole encode.
        if journal_pending(f):
            raise CardSizeError(
                "This card can't be built for a %s SD card: its games "
                "partition was not cleanly unmounted, so it still has changes "
                "waiting to be written, and growing it would move files the "
                "build has already placed. Build it at its own size, or "
                "start from a clean copy of the card." % words(target))
    # A multi-boot STORE card is laid out exactly like a stock one (its extras
    # live inside a grown p3), so the table alone can't tell: ask the reader
    # that knows.  The Multi-boot tab sizes those cards itself.
    try:
        from .multiimage import images_for_path
        multi = len(images_for_path(original_path)) > 1
    except Exception:  # noqa: BLE001 - not readable as multi-boot = not one
        multi = False
    if multi:
        raise CardSizeError(
            "This card can't be built for a %s SD card: it is a multi-boot "
            "card, and the Multi-boot tab sets the size of those."
            % words(target))
    return target


def output_parts(original_path, parts, target):
    """The Linux partitions a build's output has when it was grown to
    *target* (or *parts* unchanged when *target* is None)."""
    if not target:
        return [(int(o), int(s)) for o, s in parts]
    with open(_lp(original_path), "rb") as f:
        layout = read_layout(f)
    return linux_parts(plan(layout, target)[1])


# ---------------------------------------------------------------------------
# Room on the games partition, measured before a build spends any time
# ---------------------------------------------------------------------------
# PAD-176 failed after twenty minutes of encoding because nothing compared
# what the build would copy on whole with the games partition's free space
# until the copy itself.  Everything needed to compare them up front is on
# the card: the free block counts, and the layout resize2fs gives a partition
# grown to a bigger class, which is fixed arithmetic.  The engine's pre-flight
# (engine._SpaceCheck) adds up the build's side.

#: How a build's whole-file copies reach the card, which decides how much of
#: the free space they may use.  The kernel's ext4 driver (a loop mount,
#: ext4_grow.grow_files; what df reports) holds a reserve back from every
#: writer.  e2fsprogs' debugfs (ext4_grow.grow_files_pinned, a build carrying
#: modes, and every copy on macOS) does not.
ROUTE_MOUNT = "mount"
ROUTE_PINNED = "pinned"

#: The kernel's reserved clusters (fs/ext4/super.c,
#: ext4_calculate_resv_clusters): 2% of the blocks, at most this many, kept
#: back from every writer, root included.  It is why df on a stock Godzilla
#: Pro 1.16 games partition says 352 MB where the superblock counts 368 MB.
_KERNEL_RESERVE_MAX = 4096

_INCOMPAT_META_BG = 0x10
_RO_COMPAT_SPARSE_SUPER = 0x1

P3Space = collections.namedtuple(
    "P3Space", "block_size blocks free r_blocks blocks_per_group "
               "inodes_per_group inode_size reserved_gdt first_data_block "
               "desc_size sparse_super meta_bg")
# block_size        bytes per filesystem block (4096 on every Stern card)
# blocks            the filesystem's length in blocks
# free              free blocks: the group descriptors' counts added up
# r_blocks          blocks reserved for root (0 on every stock card)
# reserved_gdt      blocks set aside for the group descriptor table to grow
# the rest          what resize2fs lays out each new block group from


def p3_space(reader):
    """The :class:`P3Space` of the filesystem an :class:`.ext4.Ext4Reader` is
    open on (the games partition of a card).

    FREE is the group descriptors' free counts added up, which is what the
    kernel counts when it mounts the partition, rather than the superblock's
    own total: that one is only brought up to date at a clean unmount, and a
    card whose journal was never replayed can carry a stale one.  The
    superblock's total stands in when the descriptors can't be read."""
    sb = reader._sb
    wide = bool(reader.is_64bit)

    def u32(off, hi=None):
        v = struct.unpack_from("<I", sb, off)[0]
        if wide and hi is not None:
            v |= struct.unpack_from("<I", sb, hi)[0] << 32
        return v

    bs = int(reader.block_size)
    blocks = u32(0x04, 0x150)
    r_blocks = u32(0x08, 0x154)
    sb_free = u32(0x0C, 0x158)
    bpg = int(reader.blocks_per_group)
    fdb = int(reader.first_data_block)
    ds = int(reader.desc_size)
    groups = -(-(blocks - fdb) // bpg) if bpg else 0
    free = None
    if groups:
        raw = reader._read(reader.gdt_block * bs, groups * ds)
        if len(raw) == groups * ds:
            free = 0
            for g in range(groups):
                n = struct.unpack_from("<H", raw, g * ds + 0x0C)[0]
                if ds >= 0x30:
                    n |= struct.unpack_from("<H", raw, g * ds + 0x2C)[0] << 16
                free += n
            if free > blocks:
                free = None             # not descriptors after all
    if free is None:
        free = sb_free
    return P3Space(
        block_size=bs, blocks=blocks, free=free, r_blocks=r_blocks,
        blocks_per_group=bpg, inodes_per_group=int(reader.inodes_per_group),
        inode_size=int(reader.inode_size),
        reserved_gdt=struct.unpack_from("<H", sb, 0xCE)[0],
        first_data_block=fdb, desc_size=ds,
        sparse_super=bool(struct.unpack_from("<I", sb, 0x64)[0]
                          & _RO_COMPAT_SPARSE_SUPER),
        meta_bg=bool(struct.unpack_from("<I", sb, 0x60)[0]
                     & _INCOMPAT_META_BG))


def read_space(path, offset=P3_START * SECTOR):
    """:func:`p3_space` of the games partition at *offset* of the card image
    at *path*."""
    from .ext4 import Ext4Reader
    with open(_lp(path), "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        return p3_space(Ext4Reader(f, offset, size - offset))


def _has_super(g, sparse):
    """Whether block group *g* carries a backup superblock and descriptor
    table: group 0 and 1 and the powers of 3, 5 and 7 under sparse_super."""
    if g <= 1 or not sparse:
        return True
    for b in (3, 5, 7):
        n = g
        while n % b == 0:
            n //= b
        if n == 1:
            return True
    return False


def grown(space, new_blocks):
    """``(blocks, free, r_blocks)`` of the filesystem *space* once resize2fs
    has grown it to *new_blocks* (the grown partition's length in blocks);
    the filesystem as it is when that is no longer than it already is.

    What resize2fs 1.47 does (resize/resize2fs.c, adjust_fs_info): every new
    block group costs its two bitmaps and its inode table, and a group that
    carries a backup superblock (see :func:`_has_super`) also that block, the
    descriptor table and the blocks reserved for it to grow, which shrink by
    as many as the table itself grows.  A last group too short to hold its
    own bookkeeping and 50 blocks more is left off.  The root reserve keeps
    its percentage.  Checked against three real grows, exact to the block:
    godzilla_pro 1.16 8G to 16G (1,924,909 free) and to 32G (5,497,389), and
    jaws_le 1.02 16G to 32G (5,114,786)."""
    s = space
    new_blocks = int(new_blocks or 0)
    if new_blocks <= s.blocks:
        return s.blocks, s.free, s.r_blocks
    if s.meta_bg:
        raise CardSizeError("its games partition uses a layout (meta_bg) the "
                            "free-space estimate doesn't know")
    bs, bpg, fdb = s.block_size, s.blocks_per_group, s.first_data_block
    per_block = bs // s.desc_size
    itable = -(-s.inodes_per_group * s.inode_size // bs)
    groups_old = -(-(s.blocks - fdb) // bpg)
    gdt_old = -(-groups_old // per_block)
    blocks = new_blocks
    while True:
        groups = -(-(blocks - fdb) // bpg)
        gdt = -(-groups // per_block)
        resv = min(max(s.reserved_gdt - (gdt - gdt_old), 0), bs // 4)

        def overhead(g):
            return 2 + itable + (1 + gdt + resv
                                 if _has_super(g, s.sparse_super) else 0)
        rem = (blocks - fdb) % bpg
        if groups > 1 and rem and rem < overhead(groups - 1) + 50:
            blocks -= rem
            continue
        break
    if blocks <= s.blocks:
        return s.blocks, s.free, s.r_blocks
    free = (s.free + (blocks - s.blocks)
            - sum(overhead(g) for g in range(groups_old, groups)))
    r_blocks = (int(s.r_blocks * 100.0 / s.blocks * blocks / 100.0)
                if s.r_blocks else 0)
    return blocks, free, r_blocks


def kernel_reserve(blocks):
    """The kernel's reserved clusters for a filesystem of *blocks* blocks."""
    return min(int(blocks) // 50, _KERNEL_RESERVE_MAX)


def usable_blocks(space, new_blocks=None, route=ROUTE_MOUNT):
    """Blocks the whole-file copies of a build may use on the games partition
    *space*, grown to *new_blocks* first when that is given:
    ``free - kernel reserve - root reserve``.  *route* (:data:`ROUTE_MOUNT`
    or :data:`ROUTE_PINNED`) is how the copies reach the card; only the
    kernel's driver holds its reserve back.  The root reserve is taken off
    on both, though a copy by debugfs could use it: never promise room that
    one route has and the other hasn't."""
    blocks, free, r_blocks = grown(space, new_blocks)
    k = kernel_reserve(blocks) if route == ROUTE_MOUNT else 0
    return max(0, free - k - r_blocks)


def p3_blocks_at(layout, target, block_size):
    """The games partition's length in filesystem blocks once *layout* is
    grown to the *target* class; ``None`` when that isn't bigger than the
    card already is."""
    if not target or target not in CARD_SIZES:
        return None
    delta, new = plan(layout, target)
    if delta <= 0:
        return None
    return new.p3_count * SECTOR // int(block_size)


def room_by_class(layout, space, classes, route=ROUTE_MOUNT):
    """``{class: usable bytes}`` on the games partition *space* of a card
    laid out as *layout*, at each of *classes* (as it is for its own class or
    a smaller one), smallest class first."""
    out = collections.OrderedDict()
    for c in sorted({c for c in classes if c in CARD_SIZES},
                    key=CARD_SIZES.get):
        nb = p3_blocks_at(layout, c, space.block_size)
        out[c] = usable_blocks(space, nb, route) * space.block_size
    return out


def smallest_fit(need, room, above=None):
    """The smallest class of *room* (:func:`room_by_class`) whose usable
    bytes hold *need* bytes, or ``None``.  With *above*, only classes bigger
    than that one are considered."""
    floor = CARD_SIZES.get(above, 0) if above else 0
    for c, have in room.items():
        if CARD_SIZES[c] > floor and need <= have:
            return c
    return None


def candidates(original_path):
    """The classes a build of *original_path* can come out at, smallest
    first: its own, then the bigger ones this computer can grow it to
    (:func:`offered`)."""
    with open(_lp(original_path), "rb") as f:
        own = class_of(read_layout(f).laid_out)
    return [c for c in CARD_SIZES if c == own or c in offered(original_path)]


def room_gained(path, target, route=ROUTE_MOUNT):
    """Usable bytes the games partition of the card image at *path* gains
    when the card is grown to *target* (0 when it is that big already)."""
    from .ext4 import Ext4Reader
    with open(_lp(path), "rb") as f:
        layout = read_layout(f)
        f.seek(0, os.SEEK_END)
        size = f.tell()
        space = p3_space(Ext4Reader(f, P3_START * SECTOR,
                                    size - P3_START * SECTOR))
    nb = p3_blocks_at(layout, target, space.block_size)
    if not nb:
        return 0
    return ((usable_blocks(space, nb, route) - usable_blocks(space, None, route))
            * space.block_size)


def size_words(n):
    """A byte count the way a user reads one: ``7.87 GB``, ``352 MB``,
    ``4.2 MB``, ``12 KB``."""
    n = max(0, int(n))
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 1e9)
    if n >= 10 ** 7:
        return "%d MB" % round(n / 1e6)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 1e6)
    return "%d KB" % max(1 if n else 0, round(n / 1e3))


class WontFit(CardSizeError):
    """What a build copies on whole doesn't fit the games partition, found
    before the build wrote a byte to its output (a build already there is
    left as it was).  ``str()`` is the refusal a user reads.

    *need* and *avail* are bytes: what the build adds to the partition and
    what the partition has for it, both measured on the ORIGINAL grown to
    the size this build is for (*at*, when it grows the card): the figures
    the Write tab's SD card size note gives.  *items* are ``(bytes, name)``
    for the files that grow the most, named the way the user knows them.
    *fits* is the smallest SD card size the build does fit at (with
    *fits_room*, its usable bytes there), or ``None``; *largest* /
    *largest_room* the biggest size that was considered, said when even that
    is too small.  All of them come from the one *need*.  *fixed*: the build
    can't take a size (a port's, see :func:`bigger_card`).  *current* is the
    SD card size the build was measured at (the original's own, or the one
    it was asked to grow to), which :func:`bigger_card_offer` offers to
    change.

    *early*: found by the Build's first step (Stern write_preflight), before
    any replacement was converted, which counts only what is sure, so *need*
    is a floor.  Without it the refusal comes from the engine's pre-flight,
    after the Build converted the replacements it had to (they stay in the
    project), and before the card image was written.  *uncounted* clips of
    an early refusal couldn't be sized before they are converted: *fits* is
    then only the smallest size that could hold the build, and said so."""

    def __init__(self, need, avail, items=(), fits=None, fits_room=None,
                 largest=None, largest_room=None, at=None, fixed=False,
                 early=False, uncounted=0, current=None):
        self.current = current
        self.need = int(need)
        self.avail = int(avail)
        self.items = sorted(items, reverse=True)
        self.fits = fits
        self.fits_room = fits_room
        self.largest = largest
        self.largest_room = largest_room
        self.at = at
        self.fixed = bool(fixed)
        self.early = bool(early)
        self.uncounted = int(uncounted or 0)
        super().__init__(self._sentence())

    def _sentence(self):
        need, avail = size_words(self.need), size_words(self.avail)
        msg = ("This build needs %s%s on the card's games partition, which "
               "has %s free%s%s, so the build was stopped before "
               % ("at least " if self.early else "", need, avail,
                  " on a %s SD card" % words(self.at) if self.at else "",
                  # the same figure twice reads as fitting: say the gap
                  " (%s short)" % size_words(self.need - self.avail)
                  if need == avail else ""))
        if self.early:
            msg += "anything was converted or written."
        else:
            msg += ("anything was written to the card image. Any replacements "
                    "it converted first are kept in the project.")
        out = "fewer or smaller replacements"
        if self.uncounted:
            msg += (" It may need more: %d replaced video(s) can't be sized "
                    "until the build converts them." % self.uncounted)
        if self.fits and self.uncounted:
            # a floor: the size that fits it may still be too small
            where = ("build this card on its own from the Write tab for that "
                     "size (a port builds every card at its original's size)"
                     if self.fixed else
                     "pick it under SD card size on the Write tab")
            msg += (" Only a %s SD card or bigger could hold it: if the SD "
                    "card in the machine is that big, %s. Otherwise take "
                    "something out (%s)." % (words(self.fits), where, out))
        elif self.fits and self.fixed:
            msg += (" If the SD card in that machine is %s or bigger, %s. "
                    "Otherwise take something out (%s)."
                    % (words(self.fits),
                       bigger_card(self.fits, self.fits_room, fixed=True), out))
        elif self.fits:
            # only a machine whose SD card is that big can take the image
            msg += (" Build it for a %s SD card if the SD card in the machine "
                    "is %s or bigger (SD card size on the Write tab%s). "
                    "Otherwise take something out (%s)."
                    % (words(self.fits), words(self.fits),
                       ": %s free there" % size_words(self.fits_room)
                       if self.fits_room is not None else "", out))
        elif self.largest and self.largest_room is not None:
            msg += (" Even a %s SD card has only %s free there, so something "
                    "has to come out (%s)."
                    % (words(self.largest), size_words(self.largest_room), out))
        else:
            msg += " Something has to come out (%s)." % out
        big = [(n, rel) for n, rel in self.items if n > 0][:5]
        if big:
            msg += " Biggest: %s." % ", ".join(
                "%s (+%s)" % (rel, size_words(n)) for n, rel in big)
        return msg


class RefusalText(str):
    """A refusal's sentence, as Stern's ``write_preflight`` returns it, that
    still carries the :class:`WontFit` it came from (*refusal*), so the app
    can offer the SD card size that fits instead of only showing it."""

    def __new__(cls, text, refusal=None):
        s = super().__new__(cls, text)
        s.refusal = refusal
        return s


def bigger_card_offer(refusal):
    """``(current, fits)`` when *refusal* can be answered in one click by
    building for a bigger SD card from the Write tab: it is a
    :class:`WontFit` measured at a known size, a bigger size fits it, the
    build can take a size (not a port's) and this computer can grow a card.
    ``None`` otherwise."""
    if not isinstance(refusal, WontFit) or refusal.fixed or not supported():
        return None
    cur, fits = refusal.current, refusal.fits
    if cur not in CARD_SIZES or fits not in CARD_SIZES:
        return None
    if CARD_SIZES[fits] <= CARD_SIZES[cur]:
        return None
    return cur, fits


def offer_question(current, fits):
    """The one-click question for :func:`bigger_card_offer`'s answer."""
    now = words(current)
    return ("Your assets no longer fit on %s %s SD card. Would you like to "
            "change the size requirement to %s so that you don't have to "
            "compress any assets?\n\nThe SD card in the machine has to be %s "
            "or bigger."
            % ("an" if now.startswith("8") else "a", now, words(fits),
               words(fits)))


# ---------------------------------------------------------------------------
# e2fsprogs, wherever this platform keeps it
# ---------------------------------------------------------------------------

class _E2fs:
    """Checks and grows the games partition's filesystem through a LOOP
    DEVICE bounded to exactly that partition (``losetup -o OFF --sizelimit
    SIZE``), as root in the Linux this app uses (WSL on Windows).

    NEVER through ``IMG?offset=N``.  e2fsck reads that form fine, but
    resize2fs 1.47.0, handed a regular file, finishes by truncating it to
    the new filesystem's length - ``ftruncate(fd, blocks * blocksize)``
    (resize/main.c:683), with no idea the filesystem starts at an offset.
    On a real Godzilla card that cut the image off 365 MB into the grown
    games partition, taking the moved /data and /dump with it, and the
    e2fsck -fn that followed still passed because it never reads a new
    group's uninitialised blocks.  A block device is never truncated, and
    the loop's size limit is the partition's own end.

    macOS has no loop devices, so the option is not offered there yet."""

    def __init__(self):
        if not supported():
            raise CardSizeError("growing the games partition isn't "
                                "available on macOS yet")
        from ...core.executor import create_executor
        from ...core.ext4_grow import LOOP_PROBE
        self.ex = create_executor()
        ok, msg = self.ex.check_available()
        if not ok:
            raise CardSizeError(msg)
        try:
            out = self.ex.run("command -v resize2fs >/dev/null && "
                              "command -v e2fsck >/dev/null && "
                              "command -v losetup >/dev/null && echo tools; "
                              + LOOP_PROBE, timeout=120)
        except Exception as e:  # noqa: BLE001 - CommandError / timeout
            out = str(e)
        if "tools" not in out:
            raise CardSizeError("the Linux this app uses has no tool to grow "
                                "a filesystem (e2fsprogs' resize2fs)")
        if not out.rstrip().endswith("ok"):
            raise CardSizeError("the Linux this app uses can't attach the "
                                "card image as a disk (no loop devices)")

    def grow(self, image_path, offset, size, epoch=None, timeout=5400):
        """Check, grow to fill and re-check the ext4 at *offset*, the
        partition being *size* bytes.  The size goes to resize2fs in 512-byte
        SECTORS: a bare number is counted in the filesystem's own block size,
        which Stern's cards set to 4 KiB but nothing here may assume.  Returns ``{step: (rc, output)}`` for
        the steps that ran: ``loop``, ``fsck`` (-fp), ``resize``, ``check``
        (-fn).  A step runs only when the one before it succeeded.

        *epoch* pins the clock every tool stamps into the filesystem (the
        superblock and its backups, the resize inode): the same original then
        grows to the same bytes on every build, which item 149's
        byte-identical mode rebuilds rely on.  The new groups' inode tables
        are always ZEROED (RESIZE2FS_FORCE_ITABLE_INIT), as on Stern's own
        16G/32G cards: left lazy, the kernel zeroes them at a pace that
        depends on how long each later mount lasts, so no two builds agree,
        and the machine finishes the job on its first read-write mount."""
        img = self.ex.to_exec_path(image_path)
        env = ["export RESIZE2FS_FORCE_ITABLE_INIT=1"]
        if epoch:
            env.append("export E2FSCK_TIME=%d E2FSPROGS_FAKE_TIME=%d"
                       % (int(epoch), int(epoch)))
        script = "\n".join(env + [
            "IMG=%s" % shlex.quote(img),
            # a loop left attached to this image by a killed earlier run would
            # keep the file open (and busy) through the whole build
            'losetup -j "$IMG" 2>/dev/null | cut -d: -f1 | '
            'xargs -r -n1 losetup -d 2>/dev/null',
            'L=$(losetup -f --show -o %d --sizelimit %d "$IMG" 2>&1) || '
            '{ echo "PAD_E2 loop 1 $L"; exit 0; }' % (int(offset), int(size)),
            'trap \'losetup -d "$L" 2>/dev/null\' EXIT',
            'echo "PAD_E2 loop 0"',
            # resize2fs will not grow a filesystem mounted since its last full
            # check (every stock p3 has been); -p fixes only what is safe to
            # fix unattended, and 1 means it did
            'e2fsck -fp "$L" > /tmp/pad_e2.$$ 2>&1; r=$?',
            'sed "s/^/PAD_OUT fsck /" /tmp/pad_e2.$$; echo "PAD_E2 fsck $r"',
            '[ $r -le 1 ] || exit 0',
            'resize2fs "$L" %ds > /tmp/pad_e2.$$ 2>&1; r=$?'
            % (int(size) // SECTOR),
            'sed "s/^/PAD_OUT resize /" /tmp/pad_e2.$$; echo "PAD_E2 resize $r"',
            '[ $r -eq 0 ] || exit 0',
            'e2fsck -fn "$L" > /tmp/pad_e2.$$ 2>&1; r=$?',
            'sed "s/^/PAD_OUT check /" /tmp/pad_e2.$$; echo "PAD_E2 check $r"',
            'rm -f /tmp/pad_e2.$$',
        ])
        out = _run_script(self.ex, script, timeout)
        res, text = {}, {}
        for line in out.splitlines():
            if line.startswith("PAD_OUT "):
                _t, step, rest = (line.split(" ", 2) + [""])[:3]
                text.setdefault(step, []).append(rest)
            elif line.startswith("PAD_E2 "):
                bits = line.split(" ", 3)
                try:
                    rc = int(bits[2])
                except (IndexError, ValueError):
                    rc = -1
                res[bits[1]] = (rc, "\n".join(text.get(bits[1], []))
                                or (bits[3] if len(bits) > 3 else ""))
        if not res:
            res["loop"] = (-1, out[-2000:])
        return res


def _run_script(ex, script, timeout):
    """Run *script* under bash in the executor's Linux, shipped as a base64
    temp FILE the way ext4_grow ships its own (wsl.exe mangles quoting on a
    command line).  Returns its output; an executor failure comes back as
    the error's text, which carries no ``PAD_E2`` marker."""
    import base64
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".b64", prefix="pad_card_size_")
    try:
        os.write(fd, base64.b64encode(script.encode("utf-8")))
        os.close(fd)
        try:
            return ex.run("base64 -d < %s | bash" % shlex.quote(
                ex.to_exec_path(tmp)), timeout=timeout)
        except Exception as e:  # noqa: BLE001 - CommandError / timeout
            return str(e)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# the expansion
# ---------------------------------------------------------------------------

def _grow_file(f, old_size, new_size):
    """Extend *f* to *new_size*, leaving the new part a HOLE where the
    filesystem can.  Never ``truncate`` on Windows: the C runtime grows a
    file by WRITING zeros (29 s for 8 GB, measured), sparse flag or not.
    Marking the file sparse and writing its last byte grows it at once, and
    NTFS leaves everything between unallocated, reading as zeros.  A
    filesystem without sparse files (exFAT) fills the gap itself - slower,
    same bytes."""
    if new_size <= old_size:
        return
    if sys.platform == "win32":
        try:
            from ...core import rawdevice as rd
            rd._win_fsctl(f, rd._FSCTL_SET_SPARSE)
        except (ImportError, AttributeError):
            pass
        f.seek(new_size - 1)
        f.write(b"\0")
        f.flush()
        return
    f.truncate(new_size)


def _copy_range(f, src, dst, n, cancel):
    """Copy *n* bytes from *src* to *dst* within *f*, safe when the ranges
    overlap (the destination is always the later one, so back to front)."""
    pos = n
    while pos > 0:
        if cancel():
            raise Cancelled("cancelled")
        step = min(CHUNK, pos)
        pos -= step
        f.seek(src + pos)
        buf = f.read(step)
        if len(buf) != step:
            raise CardSizeError("the card image ended early while moving its "
                                "settings and log partitions")
        if not buf.count(0) == step or not _is_zero(f, dst + pos, step):
            f.seek(dst + pos)
            f.write(buf)


def _is_zero(f, off, n):
    """Whether [off, off+n) of *f* already reads as zeros.  Writing zeros
    over zeros would allocate a sparse file's holes for nothing: most of
    /data and /dump is empty, and the new place is a fresh hole."""
    f.seek(off)
    got = f.read(n)
    return len(got) == n and got.count(0) == n


def _same_range(f, a, b, n):
    pos = 0
    while pos < n:
        step = min(CHUNK, n - pos)
        f.seek(a + pos)
        x = f.read(step)
        f.seek(b + pos)
        if f.read(step) != x:
            return False
        pos += step
    return True


def _set_mbr(f, p3_count, p4_start):
    f.seek(0)
    mbr = bytearray(f.read(SECTOR))
    struct.pack_into("<I", mbr, 446 + 16 * 2 + 12, int(p3_count))
    struct.pack_into("<I", mbr, 446 + 16 * 3 + 8, int(p4_start))
    f.seek(0)
    f.write(bytes(mbr))


def check_tools(target):
    """Raise :class:`CardSizeError` unless this computer can grow a card to
    *target* (the loop device, e2fsprogs, not macOS)."""
    try:
        _E2fs()
    except CardSizeError as e:
        raise CardSizeError(
            "This card can't be built for a %s SD card on this computer: "
            "%s." % (words(target), e))


def preflight(original_path, target, tools=True):
    """Everything :func:`expand_image` needs, checked before the build
    spends any time: the original is a Stern-shaped card that can grow to
    *target*, and (with *tools*) this computer can grow one.  Returns the
    class the build will come out at (``None``: the original is that big
    already)."""
    t = target_for(original_path, target)
    if t and tools:
        check_tools(t)
    return t


def offered(original_path):
    """The bigger classes *original_path* can be built for on this computer:
    what the Write tab offers, and what a no-space failure may suggest."""
    if not supported():
        return []
    out = []
    for c in CARD_SIZES:
        try:
            if target_for(original_path, c):
                out.append(c)
        except (CardSizeError, OSError):
            continue
    return out


def _zero_range(f, off, n):
    """Make [off, off+n) of *f* read as zeros: a hole on NTFS (instant, and
    the space comes back), written zeros elsewhere."""
    if n <= 0:
        return
    if sys.platform == "win32":
        try:
            from ...core import rawdevice as rd
            f.flush()
            if rd._win_fsctl(f, rd._FSCTL_SET_ZERO_DATA,
                             rd._ZeroDataInformation(off, off + n)):
                return
        except (ImportError, AttributeError):
            pass
    zeros = bytes(CHUNK)
    pos = 0
    while pos < n:
        step = min(CHUNK, n - pos)
        if not _is_zero(f, off + pos, step):
            f.seek(off + pos)
            f.write(zeros[:step])
        pos += step


def expand_image(path, target, log=None, cancel=None, epoch=None):
    """Grow the card image at *path* IN PLACE to Stern's *target* class
    (``"16G"`` / ``"32G"``).  Returns True when it grew, False when it was
    that size or bigger already.  Raises :class:`CardSizeError` (and
    :class:`Cancelled` when *cancel* says so); a failure before the partition
    table is rewritten leaves the card as it was.  *epoch*: see
    :meth:`_E2fs.grow`."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    t0 = time.monotonic()
    e2 = _E2fs()
    with open(_lp(path), "r+b") as f:
        old = read_layout(f)
        delta, new = plan(old, target)
        if delta <= 0:
            return False
        log("Making the card a %s card: the games partition grows from "
            "%.2f GB to %.2f GB, and the two small partitions that hold the "
            "machine's settings and logs move to the end of the card."
            % (words(target), old.p3_count * SECTOR / 1e9,
               new.p3_count * SECTOR / 1e9), "info")
        src = old.p4_start * SECTOR
        dst = new.p4_start * SECTOR
        n = old.laid_out - src          # EBR1 .. p6 .. the 2-sector tail
        try:
            _grow_file(f, old.size, new.size)
            _copy_range(f, src, dst, n, cancel)
            f.flush()
            os.fsync(f.fileno())
            if not _same_range(f, src, dst, n):
                raise CardSizeError("the moved settings and log partitions "
                                    "did not read back the same")
        except BaseException:
            # nothing points at the new place yet: give the file its size back
            try:
                f.truncate(old.size)
            except OSError:
                pass
            raise
        # THE COMMIT POINT: from here the card's table points at the copy.
        _set_mbr(f, new.p3_count, new.p4_start)
        f.flush()
        os.fsync(f.fileno())
        check = read_layout(f)
        if check != new:
            raise CardSizeError("the rewritten partition table does not read "
                                "back as planned")
        # The old copy of the moved partitions now lies inside the grown games
        # partition, past its filesystem's end until the resize: nothing
        # points at it, so it goes, rather than leave a stale partition table
        # and an old /data filesystem in the games partition's free space.
        _zero_range(f, src, min(n, dst - src))
        f.flush()
        os.fsync(f.fileno())
    if cancel():
        raise Cancelled("cancelled")
    res = e2.grow(path, P3_START * SECTOR, new.p3_count * SECTOR,
                  epoch=epoch)
    for step, what, ok in (
            ("loop", "the card image could not be attached as a disk",
             lambda rc: rc == 0),
            ("fsck", "the games partition failed its check before growing",
             lambda rc: rc in (0, 1)),
            ("resize", "the games partition could not be grown",
             lambda rc: rc == 0),
            ("check", "the grown games partition did not check clean",
             lambda rc: rc == 0)):
        rc, out = res.get(step, (None, ""))
        if rc is None or not ok(rc):
            raise CardSizeError("%s (%s):\n%s" % (
                what, "did not run" if rc is None else "exit %d" % rc,
                (out or "")[-2000:]))
    # Defence in depth: nothing past the games partition may have moved.
    if os.path.getsize(_lp(path)) != new.size:
        raise CardSizeError("the card image changed size while its games "
                            "partition grew (%d bytes, expected %d)"
                            % (os.path.getsize(_lp(path)), new.size))
    with open(_lp(path), "rb") as f:
        if read_layout(f) != new:
            raise CardSizeError("the partition table does not read back as "
                                "planned after the games partition grew")
    log("The card is a %s card now (%s)."
        % (words(target), _fmt(time.monotonic() - t0)), "success")
    return True


def check_blocks_unmoved(original_path, path, parts, log=None):
    """``None`` when every regular file on the games partition of the card at
    *path* sits in exactly the blocks it has on *original_path*; otherwise
    the first file that moved.  *parts* are the original's Linux partitions
    (largest first, so p3 leads)."""
    from .ext4 import Ext4Reader
    off, size = int(parts[0][0]), int(parts[0][1])
    with open(_lp(original_path), "rb") as a, open(_lp(path), "rb") as b:
        ra = Ext4Reader(a, off, size)
        b.seek(0, os.SEEK_END)
        rb = Ext4Reader(b, off, b.tell() - off)
        after = {p: n for p, _i, n in rb.iter_regular_files(min_size=0)}
        n_files = 0
        for p, _ino, node in ra.iter_regular_files(min_size=0):
            n_files += 1
            got = after.get(p)
            if got is None or got.get("size") != node.get("size"):
                return p
            sz = int(node.get("size") or 0)
            if sz and (list(ra.disk_ranges(node, 0, sz))
                       != list(rb.disk_ranges(got, 0, sz))):
                return p
    if log:
        log("All %d files on the games partition are in the blocks they had "
            "on the original." % n_files, "info")
    return None


def _fmt(sec):
    sec = int(sec)
    return "%d:%02d" % (sec // 60, sec % 60)

