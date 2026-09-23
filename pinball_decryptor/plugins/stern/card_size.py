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
RELATIVE addresses and do not change at all.

WHAT THIS MODULE DOES.  :func:`expand_image` takes a build's output (a copy of
the original with the build's in-place patches already in it) and turns it into
the bigger class in place: the file grows (sparse where the filesystem allows),
the extended partition (the two EBRs, /data and /dump) is copied verbatim to
its new place at the end, read back and compared, the two MBR fields are
rewritten (the commit point), and ``resize2fs`` grows p3's ext4 to fill the
partition, followed by a read-only ``e2fsck``.  The partition table that comes
out is Stern's own for that class.  Nothing before p3's end moves: p1, p2 and
p3's start are where they were, so every offset the build computed from the
original is still right.

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
  * The card that comes out must pass ``e2fsck -fn`` (read-only) on p3.
"""

import collections
import os
import shlex
import struct
import subprocess
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

P1 = (0x0C, 8192, 16384)
P2 = (0x83, 24576, 688128)
P3_START = 712704
LINUX = 0x83
EXT_TYPES = (0x05, 0x0F)
TAIL = 2                    # every stock image ends 2 sectors after p4
LOGICALS = 2                # p5 (/data) and p6 (/dump)
CHUNK = 8 << 20
BLOCK = 4096                # the games partition's ext4 block size (checked)


class CardSizeError(Exception):
    """The card can't be built at the size asked for (a user-facing
    sentence)."""


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
                "This card can't be built for a %s SD card: %s." % (target, e))
    delta, _new = plan(layout, target)
    if delta <= 0:
        return None
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
            "card, and the Multi-boot tab sets the size of those." % target)
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
# e2fsprogs, wherever this platform keeps it
# ---------------------------------------------------------------------------

def _mac_tools():
    dirs = ("/opt/homebrew/opt/e2fsprogs/sbin",
            "/usr/local/opt/e2fsprogs/sbin",
            "/opt/local/sbin")
    import shutil
    tools = {}
    for name in ("resize2fs", "e2fsck"):
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                tools[name] = p
                break
        else:
            p = shutil.which(name)
            if not p:
                return None
            tools[name] = p
    return tools


class _E2fs:
    """Runs ``e2fsck`` / ``resize2fs`` against a partition of an image file
    (``IMG?offset=N`` - no loop device, no root) and hands back the exit
    code with the output, since e2fsck's exit code is its answer."""

    def __init__(self):
        self.mac = sys.platform == "darwin"
        if self.mac:
            self.tools = _mac_tools()
            if self.tools is None:
                raise CardSizeError(
                    "e2fsprogs isn't installed (brew install e2fsprogs)")
            self.ex = None
        else:
            from ...core.executor import create_executor
            self.ex = create_executor()
            ok, msg = self.ex.check_available()
            if not ok:
                raise CardSizeError(msg)
            rc, out = self._shell("command -v resize2fs && command -v e2fsck",
                                  60)
            if rc != 0:
                raise CardSizeError(
                    "resize2fs isn't installed in the Linux this app uses")

    def dev(self, image_path, offset):
        p = image_path if self.mac else self.ex.to_exec_path(image_path)
        return "%s?offset=%d" % (p, int(offset))

    def _shell(self, cmd, timeout):
        try:
            out = self.ex.run("%s; echo PAD_RC=$?" % cmd, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - CommandError / timeout
            return -1, str(e)
        rc = -1
        for line in out.splitlines():
            if line.startswith("PAD_RC="):
                try:
                    rc = int(line[7:])
                except ValueError:
                    pass
        return rc, out

    def run(self, tool, args, timeout):
        if self.mac:
            try:
                r = subprocess.run([self.tools[tool]] + list(args),
                                   capture_output=True, text=True,
                                   timeout=timeout)
            except (OSError, subprocess.SubprocessError) as e:
                return -1, str(e)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        cmd = " ".join([tool] + [shlex.quote(a) for a in args]) + " 2>&1"
        return self._shell(cmd, timeout)


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
            raise CardSizeError("cancelled")
        step = min(CHUNK, pos)
        pos -= step
        f.seek(src + pos)
        buf = f.read(step)
        if len(buf) != step:
            raise CardSizeError("the card image ended early while moving its "
                                "data partition")
        f.seek(dst + pos)
        f.write(buf)


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


def preflight(original_path, target):
    """Everything :func:`expand_image` needs, checked before the build
    spends any time: the original is a Stern-shaped card that can grow to
    *target*, and this machine can run resize2fs.  Returns the class the
    build will come out at (``None``: the original is that big already)."""
    t = target_for(original_path, target)
    if t:
        try:
            _E2fs()
        except CardSizeError as e:
            raise CardSizeError(
                "This card can't be built for a %s SD card on this computer: "
                "%s." % (t, e))
    return t


def expand_image(path, target, log=None, cancel=None):
    """Grow the card image at *path* IN PLACE to Stern's *target* class
    (``"16G"`` / ``"32G"``).  Returns True when it grew, False when it was
    that size or bigger already.  Raises :class:`CardSizeError`; a failure
    before the partition table is rewritten leaves the card as it was."""
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
            "%.2f GB to %.2f GB, and the data partitions move to the end."
            % (target, old.p3_count * SECTOR / 1e9,
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
                raise CardSizeError("the moved data partitions did not read "
                                    "back the same")
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
    p3 = e2.dev(path, P3_START * SECTOR)
    # resize2fs will not grow a filesystem mounted since its last full check
    # (every stock p3 has been); -p fixes only what is safe to fix unattended.
    rc, out = e2.run("e2fsck", ["-fp", p3], 1800)
    if rc not in (0, 1):
        raise CardSizeError("the games partition failed its check before "
                            "growing (e2fsck exit %d):\n%s" % (rc, out[-2000:]))
    blocks = new.p3_count * SECTOR // BLOCK
    rc, out = e2.run("resize2fs", [p3, str(blocks)], 3600)
    if rc != 0:
        raise CardSizeError("resize2fs could not grow the games partition "
                            "(exit %d):\n%s" % (rc, out[-2000:]))
    rc, out = e2.run("e2fsck", ["-fn", p3], 1800)
    if rc != 0:
        raise CardSizeError("the grown games partition did not check clean "
                            "(e2fsck exit %d):\n%s" % (rc, out[-2000:]))
    log("The card is a %s card now (%s)." % (target, _fmt(time.monotonic() - t0)),
        "success")
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

