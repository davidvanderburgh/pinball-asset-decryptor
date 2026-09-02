#!/usr/bin/env python3
"""mkmulticard.py - build a multi-image Stern Spike 2 SD card for the boot-time code selector (item 90).

One card, several complete game images.  p1 (FAT boot) and p2 (ext4 rootfs) are the
PRIMARY image's, p3 is the primary's games partition verbatim, p4 is the extended
partition grown to the end of the card, p5 (/data) and p6 (/dump) are the primary's,
and p7, p8, ... are each EXTRA image's games partition verbatim.  The selector
(/usr/local/codeselect/) and its one guarded hook line in /etc/init.d/game are
injected into p2 with `debugfs -w`; nothing else on the card is touched.

TWO LAYOUTS (--layout auto|parts|multi).  The card's own kernel (i.MX6, 3.14,
CONFIG_MMC_BLOCK_MINORS=8) gives mmcblk0 eight minors: the whole device and p1..p7, so p7 is
the last partition the machine can open.
  parts  ONE extra image, its games partition copied verbatim as p7 (today's layout; a second
         extra would land on p8, which the machine cannot open - refused unless
         --allow-unreachable, for emulator experiments).
  multi  ANY number of extras: p7 is ONE ext4 partition (label 'multi') holding img1/, img2/,
         ... imgK/, each the COMPLETE file tree of that extra's games partition (spk/, the
         title dir, the game/conagent/data symlinks), populated with `debugfs rdump` from the
         read-only source into a scratch tree and `mke2fs -d`, sized to the sum of the extras'
         used bytes + 10% + 256 MiB (rounded to a MiB); ownership put back with debugfs.  The
         selector's devices are '/dev/mmcblk0p7:img1', '/dev/mmcblk0p7:img2', ...; select.sh
         mounts p7 at /mnt/multi and binds the subdirectory over /games.  Never p8.
  auto   parts for one extra, multi for two or more.

THE VALIDATOR BYPASS (--bypass-validation, and the standalone `bypass --card`).  Every games
tree on the OUTPUT card (p3's title dir, p7's title dir, or each p7/imgN/<title>) gets Stern's
game self/asset validator neutered exactly as the app's Write does (plugins/stern/valpatch.py:
find the routine by signature, `bx lr` at its entry, refresh that tree's .sidx record of the
game file); 'validator: bypassed' / 'validator: none on this build' is printed per tree, the
partition's md5 sidecar is rewritten, and verify reports the bypass state per tree.

MEDIA (--media-dir DIR, item 90 v2).  DIR/media.json (written by selectmedia.py) names per image
an art PNG, an animated GIF and a music WAV (any of them null) plus the move/confirm sounds and
the volume; only the referenced files are staged into /usr/local/codeselect/media on p2 (flat,
names ^[A-Za-z0-9._-]+$, PNG <= 1360x768, GIF <= 1.5 MB / 512x288 / 30 frames, WAV pcm_s16le
44100 Hz 1-2 ch, the whole set <= 20 MB), and images.conf gets the 6-field image lines
(image=<device>|<title>|<subtitle>|<art>|<anim>|<music>) and the sound_move= / sound_confirm= /
volume= / mixer_volume= / media= keys.  A 3-field line stays valid.

Run under WSL/Linux (needs debugfs, e2fsck, mke2fs, sfdisk, fdisk from e2fsprogs/util-linux);
the pure-python parts (layout, MBR/EBR bytes, hook, images.conf, media checks) are tested on
Windows.

  mkmulticard.py plan        --primary P --extra E [--extra E2 ...] [--layout L] [--allow-unreachable]
        print the layout, byte totals and whether it fits Stern's 16G / 32G sizes; writes nothing
  mkmulticard.py check-stock IMG
        regenerate IMG's own MBR entries + EBR chain with this writer and byte-compare them
  mkmulticard.py build       --primary P --extra E [...] --out OUT --selector-dir DIR
                             [--layout auto|parts|multi] [--media-dir DIR] [--bypass-validation]
                             [--titles "T0;T1;..."] [--subtitles "S0;S1;..."] [--timeout N]
                             [--default N] [--volume V] [--mixer-volume M] [--conf FILE]
                             [--no-inject] [--dd] [--force] [--workdir DIR] [--allow-unreachable]
        write the sparse OUT (partition ranges copied, MBR entries + EBR chain regenerated; for
        the multi layout the p7 image is built first), then inject DIR/{codeselect,select.sh
        [,font.ttf]} + the media + a generated images.conf + the hooked /etc/init.d/game into
        p2, record md5 sidecars (OUT.p2.md5, and OUT.pN.md5 for every partition the bypass or
        the multi build wrote), and apply the bypass when asked
  mkmulticard.py inject      --card OUT --selector-dir DIR [--media-dir DIR] [--conf FILE] [...]
        redo only the p2 injection on an existing multi card (idempotent: re-extract, rm+write,
        verify); without --media-dir the card's media directory and the conf's media fields are
        carried through; the p2 sidecar is rewritten
  mkmulticard.py bypass      --card OUT
        apply the validator bypass to every games tree on an existing card (this is what fixes
        a card that shows GAME VALIDATION ERROR without a rebuild); sidecars rewritten
  mkmulticard.py verify      --card OUT --primary P --extra E [...] [--selector-dir DIR] [--media-dir DIR]
        table parse-back (own parser + sfdisk -d), md5 of every copied range vs its source (or
        vs its OUT.pN.md5 sidecar when the tool wrote into it - p2 always, and reported as
        'patched' with the /etc/init.d/game diff, the selector file list and the media list),
        e2fsck -fn of every ext4 partition, root listing + validator state of every games tree,
        PASS/FAIL
  mkmulticard.py selftest DIR
        synthetic 10 MiB cards -> 3-image parts card with injection + media -> every check above;
        a 3-image multi card with synthetic games trees (symlinks, ownership, debugfs ls of
        p7/img1) and the bypass on it; in DIR

Every OUTPUT path is explicit.  The tool refuses to overwrite an existing output without
--force, refuses any output under /mnt/d/Pinball/images (David's card library - after
resolving symlinks and junctions, since the repo's own images/ is a link into it) and refuses
an output equal to one of its inputs - a flag whose value turned out to be an output has
destroyed a card image in this project before.

LAYOUT WRITTEN (512-byte sectors; every number was read off the stock cards, see
tools/spike2_emu/codeselect/DESIGN.md):
  sectors 0..8191   copied verbatim from the primary (MBR bootstrap + disk id; u-boot.imx at
                    sectors 2..655), then the four MBR entries are rewritten with the same
                    CHS convention (H=4, S=32, capped at cylinder 1023 = 03 e0 ff)
  p1 p2 p3          verbatim from the primary at the primary's LBAs (8192 / 24576 / 712704)
  p4 (0x0f)         extended container: same start as the primary's, count grown to the last logical
  EBR1 p5, EBR2 p6  the primary's logicals (data, dump) at their exact LBAs; EBR2 gets the link to p7
  EBRk p(6+k)       one games partition per --extra: EBR at prev_end+1, partition at the next 1 MiB
                    boundary (exactly how the stock EBR2/p6 sit after p5), size = the extra's p3
                    sector count verbatim (13402110 for an 8G source)
  image size        last logical end + 1 + 2 tail sectors (every stock card ends 2 sectors after p6)
  Two 8G images = 28755968 sectors = 14,723,055,616 B (fits a 16G card); three would need a 32G
  card AND put the third on p8, which the machine cannot open (see above).
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import shutil
import stat as statmod
import struct
import subprocess
import sys
import tempfile
import time

#: The repo root (tools/spike2_emu/../..): the validator bypass and the ext4 reader are the
#: app's own plugins/stern modules, imported lazily so the pure parts need no package.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SECTOR = 512
HEADS, SPT = 4, 32          # geometry the stock CHS bytes decode with (p1: 64/0/1 .. 191/3/32)
ALIGN = 2048                # every stock partition start is 1 MiB aligned
EXT_TYPES = (0x05, 0x0f)
TAIL = 2                    # stock: image ends 2 sectors after the extended partition
PRE_P1 = 8192               # stock: p1 starts at 8192; u-boot occupies sectors 2..655
CHUNK = 8 << 20
STERN_SIZES = collections.OrderedDict([("8G", 7861174272), ("16G", 15494807552), ("32G", 30359420928)])
STOCK_P1 = (0x0C, 8192, 16384)
STOCK_P2 = (0x83, 24576, 688128)
# The card's kernel (i.MX6, 3.14, CONFIG_MMC_BLOCK_MINORS=8): mmcblk0 + p1..p7 are the only
# minors it allocates, so /dev/mmcblk0p8 never exists on the machine however valid the table.
MMC_BLOCK_MINORS = 8
LAST_REACHABLE_PART = MMC_BLOCK_MINORS - 1          # p7

# ---- what goes on the card -----------------------------------------------------------------
SELECT_DIR = "/usr/local/codeselect"
GAME_SCRIPT = "/etc/init.d/game"
DEVICE_FMT = "/dev/mmcblk0p%d"
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PKILL_LINE = "pkill boot_display "            # the trailing space is Stern's; the anchor is exact
IF_LINE = "if [ -f $GAMES_PATH/game ]; then"
HOOK_LINES = [
    "",
    "# codeselect: boot-time code selector (item 90) - runs the menu and remounts /games",
    "if [ -x /usr/local/codeselect/select.sh ]; then",
    "\t/usr/local/codeselect/select.sh",
    "fi",
]
# staged name -> (card name, mode, required)
SELECTOR_FILES = collections.OrderedDict([
    ("codeselect", ("codeselect", 0o755, True)),
    ("select.sh", ("select.sh", 0o755, True)),
    ("font.ttf", ("font.ttf", 0o644, False)),
])
FORBIDDEN_OUTPUT_PREFIXES = ("/mnt/d/Pinball/images", "D:/Pinball/images", "D:\\Pinball\\images")

# ---- media (item 90 v2) --------------------------------------------------------------------
MEDIA_DIR = SELECT_DIR + "/media"
MEDIA_MANIFEST = "media.json"                 # selectmedia.py writes it; --media-dir reads it
MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MEDIA_BUDGET = 20 << 20                       # the whole set on p2 (194 MB free on a stock rootfs)
PNG_MAX = (1360, 768)                         # the panel; the tools pre-scale
GIF_MAX = (512, 288)
GIF_MAX_FRAMES = 30
GIF_MAX_BYTES = 3 << 19                       # 1.5 MiB
WAV_RATE = 44100
P2_FREE_MARGIN = 8 << 20                      # never fill p2 to the last block
#: images.conf v2: up to 16 images; a device is '/dev/mmcblk0pN' (parts layout),
#: '/dev/mmcblk0pN:<subdir>' (multi layout) or the emulator's 'pN' / 'pN:<subdir>' tokens.
MAX_IMAGES = 16
DEVICE_RE = re.compile(r"^(/dev/mmcblk0p|p)(\d+)(?::([A-Za-z0-9._-]+))?$")
CONF_KEYS = ("default", "timeout", "font", "sound_move", "sound_confirm", "volume", "mixer_volume", "media")

# ---- the multi layout ----------------------------------------------------------------------
MULTI_LABEL = "multi"
MULTI_SUBDIR_RE = re.compile(r"^img(\d+)$")
#: The stock games partition's feature set (dumpe2fs of turtles_pro 1.59's p3), so the card's
#: 3.14 kernel mounts p7 exactly as it mounts p3; the four ^ entries are e2fsprogs 1.47 defaults
#: that kernel does not know (metadata_csum_seed, orphan_file) or that p3 does not use.
MULTI_FEATURES = ("has_journal,ext_attr,resize_inode,dir_index,filetype,extent,flex_bg,sparse_super,"
                  "large_file,huge_file,uninit_bg,dir_nlink,extra_isize,"
                  "^metadata_csum,^metadata_csum_seed,^64bit,^orphan_file")
MULTI_SLACK = 0.10                            # size = used * (1 + slack) + headroom, MiB-rounded
MULTI_HEADROOM = 256 << 20
LAYOUTS = ("auto", "parts", "multi")


class Refused(Exception):
    """A path or an input the tool will not act on."""


def say(msg):
    print("[card] " + msg, flush=True)


# ============================================================================= table bytes
def chs(lba):
    c, r = divmod(lba, HEADS * SPT)
    h, s = divmod(r, SPT)
    s += 1
    if c > 1023:
        c, h, s = 1023, HEADS - 1, SPT
    return bytes((h, (s & 0x3f) | ((c >> 2) & 0xc0), c & 0xff))


def entry(ptype, start, count, chs_base=0):
    """16-byte table entry. `start` goes in the LBA field as given (relative inside an EBR);
    CHS bytes are derived from the absolute LBA chs_base+start (all capped past cylinder 1023)."""
    if not ptype:
        return bytes(16)
    a = chs_base + start
    return bytes((0,)) + chs(a) + bytes((ptype,)) + chs(a + count - 1) + struct.pack("<II", start, count)


def align_up(x, a=ALIGN):
    return (x + a - 1) // a * a


class Geometry:
    """One card's partition table: the MBR primaries and the EBR chain.

    prim     [(num, type, start, count)]                  kernel numbers 1..4
    ext      (start, count) of the 0x05/0x0f container or None
    logical  [(ebr_lba, type, start_abs, count)]          kernel numbers 5, 6, ...
    mbr      the 512-byte MBR (bootstrap + disk id are reused as the template)
    ebr_raw  {ebr_lba: 512 bytes} as read (check-stock compares against these)
    """

    def __init__(self, size, mbr, prim, ext, logical, ebr_raw=None, path=None):
        self.size, self.mbr, self.prim, self.ext, self.logical = size, mbr, list(prim), ext, list(logical)
        self.ebr_raw = ebr_raw or {}
        self.path = path

    @property
    def sectors(self):
        return self.size // SECTOR

    @classmethod
    def from_file(cls, path):
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            def read_sector(lba):
                f.seek(lba * SECTOR)
                return f.read(SECTOR)
            return cls.from_reader(size, read_sector, path)

    @classmethod
    def from_reader(cls, size, read_sector, path=None):
        mbr = read_sector(0)
        if len(mbr) != SECTOR or mbr[510:512] != b"\x55\xaa":
            raise Refused("%s: no MBR signature" % (path or "image"))
        prim, ext, logical, ebr_raw = [], None, [], {}
        for i in range(4):
            e = mbr[0x1BE + 16 * i:0x1BE + 16 * i + 16]
            t = e[4]
            st, cnt = struct.unpack_from("<II", e, 8)
            if t and cnt:
                prim.append((i + 1, t, st, cnt))
                if t in EXT_TYPES and ext is None:
                    ext = (st, cnt)
        if ext:
            base = ext[0]
            cur, seen = base, set()
            while cur not in seen and cur * SECTOR < size:
                seen.add(cur)
                eb = read_sector(cur)
                if len(eb) != SECTOR or eb[510:512] != b"\x55\xaa":
                    break
                ebr_raw[cur] = eb
                e1, e2 = eb[0x1BE:0x1CE], eb[0x1CE:0x1DE]
                t = e1[4]
                rel, cnt = struct.unpack_from("<II", e1, 8)
                lt = e2[4]
                lrel, _lcnt = struct.unpack_from("<II", e2, 8)
                if t and cnt:
                    logical.append((cur, t, cur + rel, cnt))
                if not (lt in EXT_TYPES and lrel):
                    break
                cur = base + lrel
        return cls(size, mbr, prim, ext, logical, ebr_raw, path)

    def part(self, n):
        """(type, start, count) by kernel number: 1-4 primaries, 5.. logicals in chain order."""
        if n <= 4:
            for i, t, st, cnt in self.prim:
                if i == n:
                    return (t, st, cnt)
            raise Refused("%s: no primary partition %d" % (self.path or "image", n))
        if n - 5 >= len(self.logical):
            raise Refused("%s: no logical partition %d" % (self.path or "image", n))
        _e, t, st, cnt = self.logical[n - 5]
        return (t, st, cnt)

    def numbers(self):
        return [n for (n, _t, _s, _c) in self.prim] + [5 + i for i in range(len(self.logical))]

    def shape_issues(self):
        """Why this is not a stock-shaped Spike 2 card (empty list = it is)."""
        out = []
        nums = [n for (n, _t, _s, _c) in self.prim]
        if nums != [1, 2, 3, 4]:
            out.append("primaries are %r, expected [1, 2, 3, 4]" % (nums,))
            return out
        if self.part(1) != STOCK_P1:
            out.append("p1 is %r, stock is %r" % (self.part(1), STOCK_P1))
        if self.part(2) != STOCK_P2:
            out.append("p2 is %r, stock is %r" % (self.part(2), STOCK_P2))
        if self.ext is None:
            out.append("p4 is not an extended partition")
        if len(self.logical) < 2:
            out.append("only %d logical partition(s); stock has p5 (data) and p6 (dump)" % len(self.logical))
        return out


# ============================================================================= the plan
Part = collections.namedtuple("Part", "num ptype start count src src_start ebr")


class Plan:
    """Where every byte of the output comes from.

    prims  [Part] p1, p2, p3 (ebr None)      logs [Part] p5, p6, p7, ... (ebr = their EBR's LBA)
    images [Part] the partitions holding games trees, in order: p3, p7, p8, ... (parts layout)
           or p3, p7 (multi layout)
    trees  [(Part, subdir|None)] every games tree in selector index order - the unit the
           conf, the bypass and verify's root listing work on; subdir is 'img1', 'img2', ...
           for the multi layout's p7 and None for a whole-partition tree
    layout 'parts' (each extra's games partition verbatim as p7, p8, ...) or 'multi' (one
           ext4 p7 holding img1/, img2/, ... - see the module docstring)
    """

    def __init__(self, primary_geom, extra_geoms, primary=None, extras=None, layout="parts",
                 multi_sectors=None, multi_subdirs=None, multi_src=None):
        P = primary_geom
        if P.ext is None or len(P.logical) < 1:
            raise Refused("%s: no extended partition / logical chain" % (primary or "primary"))
        for n in (1, 2, 3):
            P.part(n)
        if layout not in ("parts", "multi"):
            raise Refused("layout %r is not 'parts' or 'multi'" % (layout,))
        self.layout = layout
        self.primary, self.extras = primary, list(extras or [None] * len(extra_geoms))
        self.primary_geom, self.extra_geoms = P, list(extra_geoms)
        self.ext_base = P.ext[0]
        self.prims = [Part(n, P.part(n)[0], P.part(n)[1], P.part(n)[2], primary, P.part(n)[1], None)
                      for n in (1, 2, 3)]
        self.logs = []
        num = 5
        for ebr, t, st, cnt in P.logical:
            self.logs.append(Part(num, t, st, cnt, primary, st, ebr))
            num += 1
        prev_end = self.logs[-1].start + self.logs[-1].count - 1
        self.images = [self.prims[2]]
        self.trees = [(self.prims[2], None)]
        self.multi_part = None
        self.multi_subdirs = []
        self.multi_used = None
        if layout == "parts":
            for x, xp in zip(self.extra_geoms, self.extras):
                t, xs, xc = x.part(3)
                ebr = prev_end + 1
                st = align_up(ebr + 1)
                p = Part(num, t, st, xc, xp, xs, ebr)
                self.logs.append(p)
                self.images.append(p)
                self.trees.append((p, None))
                num += 1
                prev_end = st + xc - 1
        else:
            subs = list(multi_subdirs) if multi_subdirs else ["img%d" % (i + 1) for i in range(len(self.extra_geoms))]
            if multi_sectors is None:
                self.multi_used = multi_used_bytes(self.extras, self.extra_geoms)
                multi_sectors = multi_size_sectors(self.multi_used)
            if subs:
                ebr = prev_end + 1
                st = align_up(ebr + 1)
                p = Part(num, 0x83, st, int(multi_sectors), multi_src, 0, ebr)
                self.logs.append(p)
                self.images.append(p)
                self.multi_part = p
                self.multi_subdirs = subs
                for s in subs:
                    self.trees.append((p, s))
                num += 1
                prev_end = st + p.count - 1
        self.ext_count = prev_end + 1 - self.ext_base
        self.total = prev_end + 1 + TAIL

    @property
    def total_bytes(self):
        return self.total * SECTOR

    def table(self):
        """[(num, type, start, count)] as a parser should read the output back."""
        return ([(p.num, p.ptype, p.start, p.count) for p in self.prims]
                + [(4, 0x0F, self.ext_base, self.ext_count)]
                + [(p.num, p.ptype, p.start, p.count) for p in self.logs])

    def devices(self):
        return [device_name(p.num, sub) for (p, sub) in self.trees]

    def with_multi_src(self, path):
        """The same plan with the multi layout's p7 sourced from `path` (the built p7 image)."""
        p = Plan(self.primary_geom, self.extra_geoms, self.primary, self.extras, self.layout,
                 self.multi_part.count if self.multi_part else None, self.multi_subdirs or None, path)
        p.multi_used = self.multi_used
        return p

    def fits(self):
        return collections.OrderedDict((k, v - self.total_bytes) for k, v in STERN_SIZES.items())

    def unreachable(self):
        """The image partitions past p7 - present in the table, absent from the machine's /dev."""
        return [p for p in self.images if p.num > LAST_REACHABLE_PART]

    def unreachable_note(self):
        """'' or 'p8/p9 unreachable on the machine' for the plan printout."""
        bad = self.unreachable()
        return "" if not bad else "%s unreachable on the machine" % "/".join("p%d" % p.num for p in bad)


def device_name(num, subdir=None):
    return DEVICE_FMT % num + ((":" + subdir) if subdir else "")


def parse_device(dev):
    """'/dev/mmcblk0p7:img2' / 'p7:img2' -> (7, 'img2'); (n, None) for a whole partition;
    Refused for anything else (a second ':' or an empty/odd subdirectory included)."""
    m = DEVICE_RE.match(dev or "")
    if not m:
        raise Refused("images.conf: device %r is not /dev/mmcblk0pN[:subdir] or pN[:subdir]" % (dev,))
    return int(m.group(2)), m.group(3)


# ---- the multi layout's size --------------------------------------------------------------
def ext_used_bytes(path, offset):
    """(used bytes, total bytes) of the ext2/3/4 filesystem at `offset` in `path`, from its
    superblock alone (64-bit counts honoured).  Refused when there is no superblock there."""
    with open(path, "rb") as f:
        f.seek(offset + 1024)
        sb = f.read(1024)
    if len(sb) < 1024 or struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
        raise Refused("%s@%d: no ext4 superblock (not a games partition?)" % (path, offset))
    bs = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
    blocks = struct.unpack_from("<I", sb, 0x4)[0]
    free = struct.unpack_from("<I", sb, 0xC)[0]
    if struct.unpack_from("<I", sb, 0x60)[0] & 0x80:            # INCOMPAT_64BIT: the hi words count
        blocks |= struct.unpack_from("<I", sb, 0x150)[0] << 32
        free |= struct.unpack_from("<I", sb, 0x158)[0] << 32
    return (blocks - free) * bs, blocks * bs


def multi_used_bytes(extras, extra_geoms):
    """Sum of the used bytes of every extra's games partition (what the multi p7 must hold)."""
    total = 0
    for x, g in zip(extras, extra_geoms):
        _t, st, _cnt = g.part(3)
        if x is None:
            raise Refused("the multi layout needs the extra images' paths to size p7")
        total += ext_used_bytes(x, st * SECTOR)[0]
    return total


def multi_size_sectors(used_bytes):
    """used + 10% + 256 MiB, rounded up to a MiB, in sectors."""
    size = int(used_bytes * (1 + MULTI_SLACK)) + MULTI_HEADROOM
    size = (size + (1 << 20) - 1) // (1 << 20) * (1 << 20)
    return size // SECTOR


def resolve_layout(layout, n_extra):
    """'auto' -> parts for one extra (or none), multi for two or more."""
    if layout not in LAYOUTS:
        raise Refused("--layout %r: choose one of %s" % (layout, "/".join(LAYOUTS)))
    if layout == "auto":
        return "multi" if n_extra >= 2 else "parts"
    return layout


def make_plan(primary, extras, layout="auto", multi_sectors=None, multi_src=None, multi_subdirs=None):
    lay = resolve_layout(layout, len(extras))
    return Plan(Geometry.from_file(primary), [Geometry.from_file(x) for x in extras], primary, list(extras),
                lay, multi_sectors=multi_sectors, multi_subdirs=multi_subdirs, multi_src=multi_src)


def check_reachable(plan, allow=False):
    """Refuse a layout the machine cannot boot from: more than one extra puts an image on p8,
    and the card's kernel exposes minors for p1..p7 only (CONFIG_MMC_BLOCK_MINORS=8).  With
    allow=True (--allow-unreachable) the layout is built anyway - the emulator mounts partitions
    by table offset and does not care - but the refusal is the default so a card is never burnt
    for a machine that will boot the primary and nothing else from it."""
    bad = plan.unreachable()
    if not bad or allow:
        return plan
    raise Refused(
        "%d extra images put %s on %s, and p%d is the last partition the card's kernel can open\n"
        "  (i.MX6 3.14, CONFIG_MMC_BLOCK_MINORS=8: mmcblk0 + p1..p7). The machine could never mount\n"
        "  %s; only ONE --extra fits this layout. A 3-image card needs a different layout - two\n"
        "  images inside one partition - which is a design follow-up. --allow-unreachable builds\n"
        "  it anyway (the emulator can run it; the machine cannot)."
        % (len(plan.images) - 1,
           ", ".join("image %d" % i for i, p in enumerate(plan.images) if p in bad),
           "/".join(DEVICE_FMT % p.num for p in bad), LAST_REACHABLE_PART,
           "/".join(DEVICE_FMT % p.num for p in bad)))


def mbr_entries(plan):
    """The 64 bytes at 0x1be: p1 p2 p3 verbatim, p4 = the grown extended container."""
    ents = [entry(p.ptype, p.start, p.count) for p in plan.prims] + [entry(0x0F, plan.ext_base, plan.ext_count)]
    return b"".join(ents)


def mbr_sector(plan, template=None):
    m = bytearray(template if template is not None else plan.primary_geom.mbr)
    m[0x1BE:0x1FE] = mbr_entries(plan)
    m[510:512] = b"\x55\xaa"
    return bytes(m)


def ebr_sector(plan, i):
    """The EBR sector of logical i (0 = p5): its own entry relative to the EBR, and the 0x05 link
    to the next EBR relative to the extended base (LBA = next EBR, count = through the next end)."""
    p = plan.logs[i]
    eb = bytearray(SECTOR)
    eb[0x1BE:0x1CE] = entry(p.ptype, p.start - p.ebr, p.count, chs_base=p.ebr)
    if i + 1 < len(plan.logs):
        nx = plan.logs[i + 1]
        nend = nx.start + nx.count - 1
        eb[0x1CE:0x1DE] = entry(0x05, nx.ebr - plan.ext_base, nend + 1 - nx.ebr, chs_base=plan.ext_base)
    eb[510:512] = b"\x55\xaa"
    return bytes(eb)


def _gb(n):
    return "%.2f GB" % (n / 1e9)


def print_plan(plan):
    print("primary %s (%d bytes)" % (plan.primary, plan.primary_geom.size))
    for x, g in zip(plan.extras, plan.extra_geoms):
        print("extra   %s (%d bytes)" % (x, g.size))
    for w in plan.primary_geom.shape_issues():
        print("WARNING primary: " + w)
    for x, g in zip(plan.extras, plan.extra_geoms):
        for w in g.shape_issues():
            print("WARNING %s: %s" % (os.path.basename(x or "extra"), w))
    print("layout: %s" % plan.layout)
    print("%-4s %-4s %-12s %-12s %-12s %-16s %s" % ("part", "type", "start", "count", "end", "bytes", "source"))
    rows = [(p.num, p.ptype, p.start, p.count, "%s@%d" % (os.path.basename(p.src or "primary"), p.src_start))
            for p in plan.prims]
    rows.append((4, 0x0F, plan.ext_base, plan.ext_count, "(extended container)"))
    for p in plan.logs:
        if plan.multi_part is not None and p.num == plan.multi_part.num:
            src = "multi ext4: " + ", ".join("%s=%s" % (s, os.path.basename(x or "extra"))
                                            for s, x in zip(plan.multi_subdirs, plan.extras))
        else:
            src = "%s@%d" % (os.path.basename(p.src or "image"), p.src_start)
        rows.append((p.num, p.ptype, p.start, p.count, src))
    for n, t, st, cnt, src in rows:
        print("p%-3d 0x%02x %-12d %-12d %-12d %-16d %s" % (n, t, st, cnt, st + cnt - 1, cnt * SECTOR, src))
    for p in plan.logs:
        print("  EBR for p%d at LBA %d" % (p.num, p.ebr))
    if plan.multi_part is not None:
        mp = plan.multi_part
        used = ("sum of used bytes %s + %d%% + %d MiB" % (_gb(plan.multi_used), int(MULTI_SLACK * 100), MULTI_HEADROOM >> 20)
                if plan.multi_used is not None else "size read from the card")
        print("p%d (multi layout): %d trees %s, %d MiB (%s)" % (mp.num, len(plan.multi_subdirs), "/".join(plan.multi_subdirs),
                                                             mp.count * SECTOR >> 20, used))
    note = plan.unreachable_note()
    print("images: " + ", ".join("%d=%s" % (i, d) for i, d in enumerate(plan.devices()))
          + ("  (%s)" % note if note else ""))
    print("image: %d sectors = %d bytes (%s)" % (plan.total, plan.total_bytes, _gb(plan.total_bytes)))
    for k, spare in plan.fits().items():
        print("  fits Stern %-3s image size %d: %s (spare %d)%s" % (k, STERN_SIZES[k], "YES" if spare >= 0 else "NO", spare,
                                                                 (" - " + note) if note else ""))
    if note:
        print("WARNING: %s - the card's kernel exposes p1..p7 only (CONFIG_MMC_BLOCK_MINORS=8); "
              "the machine boots the primary from such a card and nothing else" % note)


# ============================================================================= the hook
def hook_game_script(text):
    """Insert HOOK_LINES into Stern's /etc/init.d/game right after 'pkill boot_display ' and
    before 'if [ -f $GAMES_PATH/game ]; then'.  Idempotent: an already hooked script comes out
    the same.  Anything unexpected about the anchors raises Refused - never a guess."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    text = strip_hook(text)
    lines = text.split("\n")
    pk = [k for k, l in enumerate(lines) if l == PKILL_LINE]
    if len(pk) != 1:
        raise Refused("game script: expected exactly one %r line, found %d" % (PKILL_LINE, len(pk)))
    iff = [k for k, l in enumerate(lines) if l == IF_LINE]
    if len(iff) != 1:
        raise Refused("game script: expected exactly one %r line, found %d" % (IF_LINE, len(iff)))
    i, j = pk[0], iff[0]
    if not (i < j <= i + 2) or any(l.strip() for l in lines[i + 1:j]):
        raise Refused("game script: %r (line %d) is not directly before %r (line %d)" % (PKILL_LINE, i + 1, IF_LINE, j + 1))
    lines[i + 1:i + 1] = HOOK_LINES
    return "\n".join(lines)


def strip_hook(text):
    """Remove one HOOK_LINES block if present (the inverse of hook_game_script)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    lines = text.split("\n")
    n = len(HOOK_LINES)
    for k in range(len(lines) - n + 1):
        if lines[k:k + n] == HOOK_LINES:
            del lines[k:k + n]
            return "\n".join(lines)
    return text


def has_hook(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return strip_hook(text) != text


# ============================================================================= images.conf
def _media_name_ok(name, what):
    """A media file name as it goes into a conf field: flat, ^[A-Za-z0-9._-]+$ (so never a '|',
    a ':' or a '/'), or empty."""
    if name and not MEDIA_NAME_RE.match(name):
        raise Refused("images.conf: %s %r is not a plain media file name (^[A-Za-z0-9._-]+$; no '|', ':' or '/')"
                      % (what, name))
    return name or ""


def _int_range(val, key, lo, hi):
    try:
        v = int(val)
    except (TypeError, ValueError):
        raise Refused("images.conf: bad %s=%r" % (key, val))
    if not (lo <= v <= hi):
        raise Refused("images.conf: %s=%d is outside %d..%d" % (key, v, lo, hi))
    return v


def render_images_conf(devices, titles=None, subtitles=None, default=0, timeout=15, font=None,
                       media=None, sound_move=None, sound_confirm=None, volume=None, mixer_volume=None,
                       media_dir=None):
    """images.conf text.  v2 (item 90 media): `media` is one (art, anim, music) per image (names
    relative to the media dir, '' = none); the image lines carry the 6 fields only when any media
    is set, else the 3-field form every older selector reads.  The global keys follow."""
    devices = list(devices)
    if not devices:
        raise Refused("images.conf: no images")
    if len(devices) > MAX_IMAGES:
        raise Refused("images.conf: %d images; the selector takes at most %d" % (len(devices), MAX_IMAGES))
    for d in devices:
        parse_device(d)
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    media = [tuple(m) if m else ("", "", "") for m in (media or [])]
    if len(titles) > len(devices) or len(subtitles) > len(devices) or len(media) > len(devices):
        raise Refused("images.conf: %d titles / %d subtitles / %d media rows for %d images"
                      % (len(titles), len(subtitles), len(media), len(devices)))
    titles += ["image %d" % i for i in range(len(titles), len(devices))]
    subtitles += [""] * (len(devices) - len(subtitles))
    media += [("", "", "")] * (len(devices) - len(media))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    rows = []
    for m in media:
        if len(m) != 3:
            raise Refused("images.conf: a media row is (art, anim, music), got %r" % (m,))
        rows.append(tuple(_media_name_ok(x or "", what) for x, what in zip(m, ("art", "anim", "music"))))
    sound_move = _media_name_ok(sound_move or "", "sound_move")
    sound_confirm = _media_name_ok(sound_confirm or "", "sound_confirm")
    if not (0 <= int(default) < len(devices)):
        raise Refused("images.conf: default=%s is not an image index (0..%d)" % (default, len(devices) - 1))
    if int(timeout) < 0:
        raise Refused("images.conf: timeout must be >= 0")
    if volume is not None:
        volume = _int_range(volume, "volume", 0, 100)
    if mixer_volume is not None:
        mixer_volume = _int_range(mixer_volume, "mixer_volume", 0, 63)
    if media_dir and ("|" in media_dir or "\n" in media_dir):
        raise Refused("images.conf: media=%r may not contain '|' or a newline" % media_dir)
    any_media = any(any(r) for r in rows)
    out = ["# images.conf - codeselect, the boot-time code selector (item 90); written by mkmulticard.py",
           "# image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>]   index = order (0-based); media names are",
           "# relative to media= (default /usr/local/codeselect/media); default = highlight when no last choice;",
           "# timeout = seconds before the highlighted image boots by itself (0 = wait for ever)"]
    for d, t, s, r in zip(devices, titles, subtitles, rows):
        out.append("image=%s|%s|%s" % (d, t, s) + ("|%s|%s|%s" % r if any_media else ""))
    out.append("default=%d" % int(default))
    out.append("timeout=%d" % int(timeout))
    if font:
        out.append("font=%s" % font)
    if sound_move:
        out.append("sound_move=%s" % sound_move)
    if sound_confirm:
        out.append("sound_confirm=%s" % sound_confirm)
    if volume is not None:
        out.append("volume=%d" % volume)
    if mixer_volume is not None:
        out.append("mixer_volume=%d" % mixer_volume)
    if media_dir:
        out.append("media=%s" % media_dir)
    elif any_media or sound_move or sound_confirm:
        out.append("media=%s" % MEDIA_DIR)
    return "\n".join(out) + "\n"


def parse_images_conf(text):
    """-> {'images': [(device, title, subtitle)], 'media': [(art, anim, music)] (aligned, '' = none),
    'default': int, 'timeout': int, 'font': str|None, 'sound_move': str|None, 'sound_confirm': str|None,
    'volume': int|None, 'mixer_volume': int|None, 'media_dir': str|None}.  A 3-field image line is
    valid; more than 6 fields, a bad device, a media name with '|' ':' or '/', or more than 16
    images is refused.  Unknown keys are ignored (the file may grow)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    conf = {"images": [], "media": [], "default": 0, "timeout": 15, "font": None,
            "sound_move": None, "sound_confirm": None, "volume": None, "mixer_volume": None, "media_dir": None}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _sep, val = line.partition("=")
        key = key.strip()
        if key == "image":
            f = [x.strip() for x in val.split("|")]
            if len(f) > 6:
                raise Refused("images.conf: image line has %d fields (at most 6): %r" % (len(f), raw))
            f += [""] * (6 - len(f))
            parse_device(f[0])
            conf["images"].append((f[0], f[1], f[2]))
            conf["media"].append(tuple(_media_name_ok(x, what) for x, what in zip(f[3:6], ("art", "anim", "music"))))
            if len(conf["images"]) > MAX_IMAGES:
                raise Refused("images.conf: more than %d images" % MAX_IMAGES)
        elif key in ("default", "timeout"):
            try:
                conf[key] = int(val.strip())
            except ValueError:
                raise Refused("images.conf: bad %s=%r" % (key, val))
        elif key == "font":
            conf["font"] = val.strip() or None
        elif key in ("sound_move", "sound_confirm"):
            conf[key] = _media_name_ok(val.strip(), key) or None
        elif key == "volume":
            conf["volume"] = _int_range(val.strip(), key, 0, 100)
        elif key == "mixer_volume":
            conf["mixer_volume"] = _int_range(val.strip(), key, 0, 63)
        elif key == "media":
            conf["media_dir"] = val.strip() or None
    return conf


def conf_media_names(conf):
    """Every media file name a parsed conf refers to (per-image fields + the two sounds)."""
    names = []
    for row in conf.get("media", []):
        names += [x for x in row if x]
    names += [conf.get(k) for k in ("sound_move", "sound_confirm") if conf.get(k)]
    return sorted(set(names))


# ============================================================================= media
def png_info(data):
    """(w, h) from a PNG's IHDR, or None when `data` is not a PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        return None
    return struct.unpack_from(">II", data, 16)


def gif_info(data):
    """(w, h, frames) of a GIF, or None when `data` is not one.  Walks the block stream
    (extensions and image descriptors, local colour tables, LZW sub-blocks) to count frames."""
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 13:
        return None
    w, h = struct.unpack_from("<HH", data, 6)
    flags = data[10]
    pos = 13 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
    frames = 0

    def skip_sub_blocks(p):
        while p < len(data) and data[p] != 0:
            p += data[p] + 1
        return p + 1

    while pos < len(data):
        b = data[pos]
        if b == 0x3B:                                  # trailer
            break
        if b == 0x21:                                  # extension: label + sub-blocks
            pos = skip_sub_blocks(pos + 2)
        elif b == 0x2C:                                # image descriptor
            frames += 1
            if pos + 10 > len(data):
                break
            lflags = data[pos + 9]
            pos += 10 + (3 << ((lflags & 7) + 1) if lflags & 0x80 else 0)
            pos = skip_sub_blocks(pos + 1)             # LZW minimum code size, then the data
        else:
            raise Refused("GIF: unexpected block 0x%02x at %d" % (b, pos))
    return w, h, frames


def wav_info(data):
    """(format tag, channels, rate, bits) from a RIFF/WAVE 'fmt ' chunk, or None when `data`
    is not a WAV.  Chunks are walked (Logic exports put JUNK/LGWV/bext before fmt)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if cid == b"fmt " and pos + 8 + 16 <= len(data):
            tag, ch, rate = struct.unpack_from("<HHI", data, pos + 8)
            bits = struct.unpack_from("<H", data, pos + 8 + 14)[0]
            return tag, ch, rate, bits
        pos += 8 + size + (size & 1)
    return None


def check_media_file(path, kind):
    """Refuse a media file the selector could not use; -> (kind word, size).  `kind` is
    'art' (PNG <= 1360x768), 'anim' (GIF <= 1.5 MB, 512x288, 30 frames) or 'wav' (RIFF
    pcm_s16le 44100 Hz 1-2 ch: music, sound_move, sound_confirm)."""
    name = os.path.basename(path)
    if not MEDIA_NAME_RE.match(name):
        raise Refused("media %r: names must match ^[A-Za-z0-9._-]+$" % name)
    if not os.path.isfile(path):
        raise Refused("media %s: %s does not exist" % (name, path))
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        data = f.read()
    if kind == "art":
        d = png_info(data)
        if d is None:
            raise Refused("media %s: art must be a PNG" % name)
        if d[0] > PNG_MAX[0] or d[1] > PNG_MAX[1]:
            raise Refused("media %s: PNG is %dx%d, larger than the %dx%d panel (pre-scale it)" % (name, d[0], d[1], PNG_MAX[0], PNG_MAX[1]))
        return "png %dx%d" % d, size
    if kind == "anim":
        g = gif_info(data)
        if g is None:
            raise Refused("media %s: anim must be an animated GIF" % name)
        if size > GIF_MAX_BYTES:
            raise Refused("media %s: GIF is %d bytes, over the %d byte cap" % (name, size, GIF_MAX_BYTES))
        if g[0] > GIF_MAX[0] or g[1] > GIF_MAX[1]:
            raise Refused("media %s: GIF is %dx%d, over %dx%d" % (name, g[0], g[1], GIF_MAX[0], GIF_MAX[1]))
        if g[2] > GIF_MAX_FRAMES:
            raise Refused("media %s: GIF has %d frames, over %d" % (name, g[2], GIF_MAX_FRAMES))
        if g[2] < 1:
            raise Refused("media %s: GIF has no frames" % name)
        return "gif %dx%d %d frames" % g, size
    if kind == "wav":
        w = wav_info(data)
        if w is None:
            raise Refused("media %s: must be a RIFF WAV" % name)
        tag, ch, rate, bits = w
        if tag != 1 or bits != 16 or rate != WAV_RATE or ch not in (1, 2):
            raise Refused("media %s: WAV is fmt %d / %d ch / %d Hz / %d-bit; the selector plays pcm_s16le %d Hz 1-2 ch only"
                          % (name, tag, ch, rate, bits, WAV_RATE))
        return "wav %d Hz %d ch" % (rate, ch), size
    raise Refused("media %s: unknown kind %r" % (name, kind))


def read_media_manifest(media_dir):
    """DIR/media.json -> dict; the shape selectmedia.py writes:
    {"images": [{"art": "art0.png", "anim": "anim0.gif"|null, "music": "music0.wav"|null}, ...],
     "sound_move": "move.wav"|null, "sound_confirm": "confirm.wav"|null, "volume": 50}
    ("mixer_volume" optional)."""
    path = os.path.join(media_dir, MEDIA_MANIFEST)
    if not os.path.isdir(media_dir):
        raise Refused("--media-dir %s is not a directory" % media_dir)
    if not os.path.isfile(path):
        raise Refused("%s has no %s (selectmedia.py prepare writes it)" % (media_dir, MEDIA_MANIFEST))
    with open(path, "r", encoding="utf-8") as f:
        try:
            man = json.load(f)
        except ValueError as e:
            raise Refused("%s: not JSON (%s)" % (path, e))
    if not isinstance(man, dict) or not isinstance(man.get("images"), list):
        raise Refused("%s: expected {\"images\": [...], ...}" % path)
    return man


def plan_media(media_dir, n_images):
    """Validate DIR/media.json against a card with `n_images` images and check every referenced
    file -> {'rows': [(art, anim, music)], 'sound_move', 'sound_confirm', 'volume', 'mixer_volume',
    'files': OrderedDict name -> source path, 'total': bytes, 'kinds': {name: kind word}}.
    Only referenced files are staged; a missing, misnamed, malformed or over-budget one refuses."""
    man = read_media_manifest(media_dir)
    imgs = man["images"]
    if len(imgs) != n_images:
        raise Refused("%s/%s lists %d images; the card holds %d" % (media_dir, MEDIA_MANIFEST, len(imgs), n_images))
    files = collections.OrderedDict()
    kinds = {}
    total = 0

    def take(name, kind, what):
        nonlocal total
        if name is None or name == "":
            return ""
        if not isinstance(name, str):
            raise Refused("%s: %s must be a file name or null, got %r" % (MEDIA_MANIFEST, what, name))
        name = _media_name_ok(name, what)
        if name not in files:
            src = os.path.join(media_dir, name)
            word, size = check_media_file(src, kind)
            files[name] = src
            kinds[name] = word
            total += size
        return name

    rows = []
    for i, e in enumerate(imgs):
        if not isinstance(e, dict):
            raise Refused("%s: images[%d] must be an object" % (MEDIA_MANIFEST, i))
        rows.append((take(e.get("art"), "art", "images[%d].art" % i),
                     take(e.get("anim"), "anim", "images[%d].anim" % i),
                     take(e.get("music"), "wav", "images[%d].music" % i)))
    out = {"rows": rows,
           "sound_move": take(man.get("sound_move"), "wav", "sound_move") or None,
           "sound_confirm": take(man.get("sound_confirm"), "wav", "sound_confirm") or None,
           "volume": None, "mixer_volume": None, "files": files, "total": total, "kinds": kinds}
    if man.get("volume") is not None:
        out["volume"] = _int_range(man.get("volume"), "volume", 0, 100)
    if man.get("mixer_volume") is not None:
        out["mixer_volume"] = _int_range(man.get("mixer_volume"), "mixer_volume", 0, 63)
    if total > MEDIA_BUDGET:
        raise Refused("media set is %d bytes, over the %d byte budget (%d files)" % (total, MEDIA_BUDGET, len(files)))
    return out


def default_title(path):
    """'turtles_pro-1_59_0.Release.8G.sdcard.raw' -> 'turtles_pro-1_59_0.Release'."""
    b = os.path.basename(path or "image")
    b = re.sub(r"\.(raw|img|bin|iso)$", "", b, flags=re.I)
    b = re.sub(r"\.\d+G\.sdcard$", "", b, flags=re.I)
    return b


def split_list(s):
    return [x.strip() for x in s.split(";")] if s else []


# ============================================================================= output safety
def _norm(p):
    """Absolute, LINK-RESOLVED, forward slashes, lower case.  Symlinks and junctions are followed
    (os.path.realpath) because the repo's own images/ is a junction into D:\\Pinball\\images -
    the card library the refusal below exists for - and a prefix test on the spelled path
    would let `images/x.raw` straight through.  An output that does not exist yet has its
    PARENT resolved and the basename re-joined."""
    a = os.path.abspath(p)
    if os.path.exists(a):
        r = os.path.realpath(a)
    else:
        r = os.path.join(os.path.realpath(os.path.dirname(a)), os.path.basename(a))
    return os.path.normpath(r).replace("\\", "/").lower()


def check_output_path(path, inputs, force=False, must_exist=False):
    """Refuse an output the tool must never write.  Raises Refused with the reason."""
    if not path:
        raise Refused("no output path")
    n = _norm(path)
    for pre in FORBIDDEN_OUTPUT_PREFIXES:
        pn = _norm(pre)
        if n == pn or n.startswith(pn + "/"):
            raise Refused("refusing to write under %s (David's card library): %s" % (pre, path))
    for inp in inputs:
        if not inp:
            continue
        same = _norm(inp) == n
        if not same and os.path.exists(path) and os.path.exists(inp):
            try:
                same = os.path.samefile(path, inp)
            except OSError:
                same = False
        if same:
            raise Refused("output %s is also an input" % path)
    if os.path.isdir(path):
        raise Refused("output %s is a directory" % path)
    if must_exist:
        if not os.path.isfile(path):
            raise Refused("%s does not exist" % path)
    elif os.path.exists(path) and not force:
        raise Refused("%s exists; pass --force to overwrite it" % path)
    return path


# ============================================================================= copying
ZERO = bytes(CHUNK)


def copy_range(src, soff, out, doff, length, label="", sparse=True, progress=say):
    """Copy length bytes src@soff -> out@doff in 8 MiB chunks; sparse=True skips all-zero chunks
    (the output must be a fresh hole there); progress lines every ~2 s."""
    t0 = last = time.monotonic()
    done = skipped = 0
    with open(src, "rb") as s, open(out, "r+b") as o:
        s.seek(soff)
        left, pos = length, doff
        while left:
            b = s.read(min(CHUNK, left))
            if not b:
                raise EOFError("%s: short read at byte %d" % (src, soff + length - left))
            if sparse and b == ZERO[:len(b)]:
                skipped += len(b)
            else:
                o.seek(pos)
                o.write(b)
            pos += len(b)
            left -= len(b)
            done += len(b)
            now = time.monotonic()
            if progress and label and now - last >= 2.0:
                last = now
                progress("  %s %s / %s  %.0f MB/s" % (label, _gb(done), _gb(length), done / 1e6 / max(now - t0, 1e-9)))
        o.flush()
    dt = time.monotonic() - t0
    if progress and label:
        progress("  %s done: %s in %.1f s (%.0f MB/s), %s all-zero skipped" %
                 (label, _gb(length), dt, length / 1e6 / max(dt, 1e-9), _gb(skipped)))
    return dt


def dd_range(src, soff, out, doff, length, label=""):
    t0 = time.monotonic()
    cmd = ["dd", "if=" + src, "of=" + out, "bs=16M", "iflag=skip_bytes,count_bytes", "oflag=seek_bytes",
           "skip=%d" % soff, "seek=%d" % doff, "count=%d" % length, "conv=sparse,notrunc", "status=none"]
    subprocess.run(cmd, check=True)
    dt = time.monotonic() - t0
    if label:
        say("  %s done (dd): %s in %.1f s (%.0f MB/s)" % (label, _gb(length), dt, length / 1e6 / max(dt, 1e-9)))
    return dt


def md5_range(path, off, length):
    h = hashlib.md5()
    with open(path, "rb") as f:
        f.seek(off)
        left = length
        while left:
            b = f.read(min(CHUNK, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def md5_file(path):
    return md5_range(path, 0, os.path.getsize(path))


# ---- the md5 sidecars -----------------------------------------------------------------------
# verify cannot compare p2 to its source (it is patched), so without this a p2 corrupted
# anywhere OUTSIDE the injected files passed.  Every write-back of p2 records md5 of the whole
# range beside the card, and verify compares the card's p2 to it.  The same file shape covers
# every other partition this tool WRITES INTO after the copy: the validator bypass patches the
# game ELF + .sidx inside p3 / p7, and the multi layout's p7 has no source image at all - so
# those get <card>.pN.md5 too, and verify holds them to it instead of to a source.
def sidecar_path(card, n):
    return card + ".p%d.md5" % n


def p2_sidecar_path(card):
    return sidecar_path(card, 2)


def part_range(card, n):
    """(offset, length) of partition n in bytes; must be a Linux partition."""
    t, st, cnt = Geometry.from_file(card).part(n)
    if t != 0x83:
        raise Refused("%s: p%d is type 0x%02x, not Linux" % (card, n, t))
    return st * SECTOR, cnt * SECTOR


def p2_range(card):
    """(offset, length) of p2 in bytes."""
    return part_range(card, 2)


def write_part_sidecar(card, n):
    """md5 of the card's whole pN range -> <card>.pN.md5 (one line: '<md5>  pN @<offset>+<length>').
    Returns the digest."""
    off, length = part_range(card, n)
    h = md5_range(card, off, length)
    with open(sidecar_path(card, n), "w", newline="\n") as f:
        f.write("%s  p%d @%d+%d\n" % (h, n, off, length))
    return h


def read_part_sidecar(card, n):
    """The digest recorded beside the card for pN, or None when there is no sidecar."""
    side = sidecar_path(card, n)
    if not os.path.isfile(side):
        return None
    with open(side, "r") as f:
        tok = f.read().split()
    if not tok or not re.fullmatch(r"[0-9a-f]{32}", tok[0]):
        raise Refused("%s: not a p%d sidecar (expected '<md5>  p%d @off+len')" % (side, n, n))
    return tok[0]


def check_part_sidecar(card, n):
    """-> (recorded, actual): recorded is None without a sidecar; actual is md5 of pN now."""
    want = read_part_sidecar(card, n)
    off, length = part_range(card, n)
    return want, md5_range(card, off, length)


def write_p2_sidecar(card):
    return write_part_sidecar(card, 2)


def read_p2_sidecar(card):
    return read_part_sidecar(card, 2)


def check_p2_sidecar(card):
    return check_part_sidecar(card, 2)


def drop_stale_sidecars(card, keep=(2,)):
    """Remove <card>.pN.md5 files for partitions a fresh build did not write into."""
    d = os.path.dirname(os.path.abspath(card)) or "."
    base = os.path.basename(card)
    for name in os.listdir(d):
        m = re.fullmatch(re.escape(base) + r"\.p(\d+)\.md5", name)
        if m and int(m.group(1)) not in keep:
            os.unlink(os.path.join(d, name))


def write_tables(plan, out):
    """MBR (bootstrap + disk id from the primary, entries regenerated) and the EBR chain."""
    with open(out, "r+b") as o:
        o.seek(0)
        o.write(mbr_sector(plan))
        for i in range(len(plan.logs)):
            o.seek(plan.logs[i].ebr * SECTOR)
            o.write(ebr_sector(plan, i))
        o.flush()


def build_image(plan, out, use_dd=False):
    """The sparse output: pre-p1 region verbatim, every partition range, then the tables."""
    with open(out, "wb") as o:
        o.truncate(plan.total_bytes)
    say("output %s: %d bytes apparent (sparse), %d partition ranges to copy" % (out, plan.total_bytes, 3 + len(plan.logs)))
    copy_range(plan.primary, 0, out, 0, PRE_P1 * SECTOR, "pre-p1 (bootstrap + u-boot)")
    for p in plan.prims + plan.logs:
        label = "p%d %s" % (p.num, default_title(p.src))
        say("copying %s: %s from %s@LBA %d -> LBA %d" % ("p%d" % p.num, _gb(p.count * SECTOR), os.path.basename(p.src), p.src_start, p.start))
        if use_dd:
            dd_range(p.src, p.src_start * SECTOR, out, p.start * SECTOR, p.count * SECTOR, label)
        else:
            copy_range(p.src, p.src_start * SECTOR, out, p.start * SECTOR, p.count * SECTOR, label)
    write_tables(plan, out)
    say("tables written: MBR entries + %d EBR sector(s)" % len(plan.logs))


def allocated_bytes(path):
    st = os.stat(path)
    blocks = getattr(st, "st_blocks", None)
    return None if blocks is None else blocks * 512


# ============================================================================= ext4 tooling
def need_tools(*names):
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise Refused("missing tool(s): %s (run this under WSL/Linux with e2fsprogs + util-linux)" % ", ".join(missing))


def fs_ref(image, offset):
    """The 'file?offset=N' form debugfs and e2fsck accept for a partition inside a whole-card image."""
    return image if not offset else "%s?offset=%d" % (image, offset)


def debugfs_read(ref, request):
    """Run one read-only debugfs request; return stdout bytes (the banner goes to stderr)."""
    r = subprocess.run(["debugfs", "-R", request, ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace")
    bad = [l for l in err.splitlines() if l and not l.startswith("debugfs ")]
    if r.returncode != 0 or bad:
        raise Refused("debugfs %r on %s failed: %s" % (request, ref, " | ".join(bad) or "rc=%d" % r.returncode))
    return r.stdout


def debugfs_cat(ref, path):
    return debugfs_read(ref, "cat " + path)


def debugfs_ls(ref, path):
    """-> [(inode, mode, uid, gid, name, size)] from 'ls -p' (the parseable form)."""
    out = []
    for line in debugfs_read(ref, "ls -p " + path).decode("utf-8", "replace").splitlines():
        f = line.split("/")
        if len(f) >= 7 and f[1].isdigit():
            out.append((int(f[1]), int(f[2], 8), int(f[3]), int(f[4]), f[5], int(f[6] or 0)))
    return out


def debugfs_exists(ref, path):
    r = subprocess.run(["debugfs", "-R", "stat " + path, ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode == 0 and b"Inode:" in r.stdout


def debugfs_stat(ref, path):
    """-> {'mode': int, 'uid': int, 'gid': int, 'atime': int, 'ctime': int, 'mtime': int, 'link': str|None}"""
    txt = debugfs_read(ref, "stat " + path).decode("utf-8", "replace")
    info = {"link": None}
    m = re.search(r"Mode:\s+(0[0-7]+)", txt)
    if m:
        info["mode"] = int(m.group(1), 8)
    m = re.search(r"User:\s+(\d+)\s+Group:\s+(\d+)", txt)
    if m:
        info["uid"], info["gid"] = int(m.group(1)), int(m.group(2))
    for k in ("atime", "ctime", "mtime"):
        m = re.search(r"^\s*%s:\s+0x([0-9a-fA-F]+)" % k, txt, re.M)
        if m:
            info[k] = int(m.group(1), 16)
    m = re.search(r'Fast link dest: "([^"]*)"', txt)
    if m:
        info["link"] = m.group(1)
    return info


def dq(path):
    """A path as one debugfs argument.  debugfs parses its requests with libss, which honours
    double quotes - without them `write /tmp/my stage/x /usr/local/x` is three words, and a
    card or output under a directory with a space in its name ('D:\\Pinball\\TMNT 1987\\multi')
    put the staging directory exactly there."""
    if '"' in path:
        raise Refused("path %r: debugfs cannot take a double quote inside an argument" % path)
    return '"%s"' % path


def debugfs_write_script(image, commands):
    """Run a debugfs -w script.  debugfs exits 0 whatever happened, so every output line that is not
    the banner or an 'Allocated inode' note is treated as an error."""
    with tempfile.NamedTemporaryFile("w", suffix=".debugfs", delete=False) as f:
        f.write("\n".join(commands) + "\n")
        script = f.name
    try:
        r = subprocess.run(["debugfs", "-w", "-f", script, image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    finally:
        os.unlink(script)
    out = r.stdout.decode("utf-8", "replace")
    bad = []
    for l in out.splitlines():
        s = l.strip()
        if not s or s.startswith("debugfs ") or s.startswith("Allocated inode:") or s.startswith("debugfs:"):
            continue
        bad.append(s)
    if r.returncode != 0 or bad:
        raise Refused("debugfs -w reported: %s" % (" | ".join(bad) or "rc=%d" % r.returncode))
    return out


def e2fsck(ref):
    """-> (rc, output); rc 0 is clean."""
    r = subprocess.run(["e2fsck", "-fn", ref], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def e2fsck_blocks(txt):
    """(used, total) blocks from e2fsck's summary line ('...: 4493/86016 files (...), 145489/344064 blocks')."""
    m = re.search(r"(\d+)/(\d+) blocks", txt)
    if not m:
        raise Refused("e2fsck printed no 'used/total blocks' line:\n%s" % txt.strip())
    return int(m.group(1)), int(m.group(2))


def ext_block_size(path, offset=0):
    with open(path, "rb") as f:
        f.seek(offset + 1024 + 0x18)
        return 1024 << struct.unpack("<I", f.read(4))[0]


def debugfs_rdump(ref, src, dest):
    """`rdump <src> <dest>` out of a read-only filesystem (symlinks come out as symlinks -
    measured).  As an ordinary user debugfs cannot chown what it extracts and says so on stderr
    for every entry; those lines are the expected noise, anything else is an error."""
    r = subprocess.run(["debugfs", "-R", "rdump %s %s" % (dq(src), dq(dest)), ref],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace") + r.stdout.decode("utf-8", "replace")
    bad = [l for l in err.splitlines()
           if l.strip() and not l.startswith("debugfs ") and "while changing ownership" not in l]
    if r.returncode != 0 or bad:
        raise Refused("debugfs rdump %s -> %s failed: %s" % (src, dest, " | ".join(bad) or "rc=%d" % r.returncode))


def debugfs_walk(ref, sub="/"):
    """Every entry under `sub`, recursively: [(relative path, inode, mode, uid, gid, size)].
    Symlinks are listed and not followed; directories are descended."""
    out = []
    for ino, mode, uid, gid, name, size in debugfs_ls(ref, sub):
        if name in (".", ".."):
            continue
        rel = (sub.rstrip("/") + "/" + name).lstrip("/")
        out.append((rel, ino, mode, uid, gid, size))
        if statmod.S_ISDIR(mode):
            out += debugfs_walk(ref, "/" + rel)
    return out


# ============================================================================= injection
def stage_selector(selector_dir, stage, conf_text, hooked_game, media_files=None):
    """Copy the selector files into `stage` with their FINAL modes (debugfs write copies the source
    mode).  `media_files` ({name: source path}, from plan_media) go to stage/media/<name> and
    MEDIA_DIR/<name> on the card, 0644.  -> [(staged path, card path, mode)]."""
    if not os.path.isdir(selector_dir):
        raise Refused("selector dir %s is not a directory" % selector_dir)
    items = []
    for name, (card, mode, required) in SELECTOR_FILES.items():
        src = os.path.join(selector_dir, name)
        if not os.path.isfile(src):
            if name == "font.ttf" and os.path.isfile(HOST_FONT):
                say("selector dir has no font.ttf; using the host's %s" % HOST_FONT)
                src = HOST_FONT
            elif required:
                raise Refused("selector dir %s lacks %s" % (selector_dir, name))
            else:
                continue
        dst = os.path.join(stage, name)
        shutil.copyfile(src, dst)
        os.chmod(dst, mode)
        items.append((dst, SELECT_DIR + "/" + card, mode))
    conf = os.path.join(stage, "images.conf")
    with open(conf, "w", newline="\n") as f:
        f.write(conf_text)
    os.chmod(conf, 0o644)
    items.append((conf, SELECT_DIR + "/images.conf", 0o644))
    if media_files:
        mdir = os.path.join(stage, "media")
        os.makedirs(mdir, exist_ok=True)
        for name, src in media_files.items():
            if not MEDIA_NAME_RE.match(name):
                raise Refused("media %r: names must match ^[A-Za-z0-9._-]+$" % name)
            dst = os.path.join(mdir, name)
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o644)
            items.append((dst, MEDIA_DIR + "/" + name, 0o644))
    game = os.path.join(stage, "game")
    with open(game, "wb") as f:
        f.write(hooked_game.encode("utf-8"))
    os.chmod(game, 0o755)
    items.append((game, GAME_SCRIPT, 0o755))
    return items


def inject_commands(items, existing, times, existing_media=None):
    """The debugfs -w script for one injection (pure, so it is testable without debugfs).

    items           [(staged native path, card path, mode)] from stage_selector
    existing        FILE names already in SELECT_DIR (removed first), or None when the directory
                    is missing; 'media' (a directory) is never in this list
    times           the game script's {atime, ctime, mtime} to put back
    existing_media  the names inside MEDIA_DIR when that directory is to be REPLACED (each is
                    rm'd, then the directory rmdir'd - debugfs's rm cannot take a directory);
                    None leaves an existing media directory alone
    MEDIA_DIR is mkdir'd (+ 040755 root:root) exactly when an item lands in it.
    Every path is double-quoted (dq): the staged path is a NATIVE path and may hold a space."""
    cmds = []
    if existing is None:
        cmds.append("mkdir " + dq(SELECT_DIR))
    else:
        for name in existing:
            cmds.append("rm " + dq(SELECT_DIR + "/" + name))
    if existing_media is not None:
        for name in existing_media:
            cmds.append("rm " + dq(MEDIA_DIR + "/" + name))
        cmds.append("rmdir " + dq(MEDIA_DIR))
    cmds.append("rm " + dq(GAME_SCRIPT))
    media_items = [it for it in items if it[1].startswith(MEDIA_DIR + "/")]
    if media_items:
        cmds.append("mkdir " + dq(MEDIA_DIR))
    for staged, card, _mode in items:
        cmds.append("write %s %s" % (dq(staged), dq(card)))
    cmds.append("set_inode_field %s mode 040755" % dq(SELECT_DIR))
    cmds.append("set_inode_field %s uid 0" % dq(SELECT_DIR))
    cmds.append("set_inode_field %s gid 0" % dq(SELECT_DIR))
    if media_items:
        cmds.append("set_inode_field %s mode 040755" % dq(MEDIA_DIR))
        cmds.append("set_inode_field %s uid 0" % dq(MEDIA_DIR))
        cmds.append("set_inode_field %s gid 0" % dq(MEDIA_DIR))
    for _staged, card, mode in items:
        cmds.append("set_inode_field %s mode 0%o" % (dq(card), statmod.S_IFREG | mode))
        cmds.append("set_inode_field %s uid 0" % dq(card))
        cmds.append("set_inode_field %s gid 0" % dq(card))
    for k in ("atime", "ctime", "mtime"):
        if k in times:
            cmds.append("set_inode_field %s %s @%d" % (dq(GAME_SCRIPT), k, times[k]))
    return cmds


def inject_into_p2(p2_image, selector_dir, conf_text, stage_dir, media_files=None, replace_media=False):
    """Modify an extracted rootfs image in place: /usr/local/codeselect/* (+ media/) and the hooked
    game script.  Idempotent (existing files are removed first; an existing media directory is
    replaced when media is staged or `replace_media` asks, else left alone).  Refuses to fill p2
    past its free space.  Verifies by e2fsck -fn and full read-back."""
    need_tools("debugfs", "e2fsck")
    rc, txt = e2fsck(p2_image)
    if rc != 0:
        raise Refused("p2 is not clean before injection (e2fsck rc=%d):\n%s" % (rc, txt))
    used, total = e2fsck_blocks(txt)
    bs = ext_block_size(p2_image)
    free = (total - used) * bs
    margin = min(P2_FREE_MARGIN, total * bs // 20)          # 8 MiB, or 5% of a small (synthetic) p2
    orig = debugfs_cat(p2_image, GAME_SCRIPT)
    if not orig:
        raise Refused("%s is empty or missing in p2" % GAME_SCRIPT)
    times = debugfs_stat(p2_image, GAME_SCRIPT)
    hooked = hook_game_script(orig)
    items = stage_selector(selector_dir, stage_dir, conf_text, hooked, media_files)
    existing = existing_media = None
    reclaim = len(orig)                                    # the game script is rm'd and rewritten
    if debugfs_exists(p2_image, SELECT_DIR):
        ents = [e for e in debugfs_ls(p2_image, SELECT_DIR) if e[4] not in (".", "..")]
        existing = [e[4] for e in ents if not statmod.S_ISDIR(e[1])]
        reclaim += sum(e[5] for e in ents if not statmod.S_ISDIR(e[1]))
        has_media = any(e[4] == "media" and statmod.S_ISDIR(e[1]) for e in ents)
        if has_media and (media_files or replace_media):
            ments = [e for e in debugfs_ls(p2_image, MEDIA_DIR) if e[4] not in (".", "..")]
            existing_media = [e[4] for e in ments]
            reclaim += sum(e[5] for e in ments)
    staged_bytes = sum(os.path.getsize(s) for (s, _c, _m) in items)
    if staged_bytes > free + reclaim - margin:
        raise Refused("p2 has %d KB free (+ %d KB the re-injection frees) and the injection needs %d KB (+ %d KB margin)"
                      % (free >> 10, reclaim >> 10, staged_bytes >> 10, margin >> 10))
    debugfs_write_script(p2_image, inject_commands(items, existing, times, existing_media))
    rc, txt = e2fsck(p2_image)
    if rc != 0:
        raise Refused("p2 is not clean after injection (e2fsck rc=%d):\n%s" % (rc, txt))
    for staged, card, mode in items:
        back = debugfs_cat(p2_image, card)
        if hashlib.md5(back).hexdigest() != md5_file(staged):
            raise Refused("%s read back differs from %s" % (card, staged))
        st = debugfs_stat(p2_image, card)
        if st.get("mode") != mode or st.get("uid") != 0 or st.get("gid") != 0:
            raise Refused("%s has mode %o uid %s gid %s after injection" % (card, st.get("mode", 0), st.get("uid"), st.get("gid")))
    after = debugfs_stat(p2_image, GAME_SCRIPT)
    nmedia = len([1 for (_s, c, _m) in items if c.startswith(MEDIA_DIR + "/")])
    say("injected %d files (%d media, %d KB); %s hook %s; game script times %s; p2 had %d KB free" %
        (len(items), nmedia, staged_bytes >> 10, GAME_SCRIPT, "present" if has_hook(hooked) else "MISSING",
         "kept" if all(after.get(k) == times.get(k) for k in ("atime", "ctime", "mtime") if k in times) else "changed",
         free >> 10))
    return [card for (_s, card, _m) in items]


def inject_card(card, selector_dir, conf_text, workdir=None, media_files=None, replace_media=False):
    """Extract p2 from the card, inject, e2fsck, write it back.  -> list of card paths written."""
    geom = Geometry.from_file(card)
    t, st, cnt = geom.part(2)
    if t != 0x83:
        raise Refused("%s: p2 is type 0x%02x, not Linux" % (card, t))
    tmp = tempfile.mkdtemp(prefix="mkmulticard.", dir=workdir)
    try:
        p2 = os.path.join(tmp, "p2.img")
        say("extracting p2 (%s) from %s" % (_gb(cnt * SECTOR), card))
        with open(p2, "wb") as f:
            f.truncate(cnt * SECTOR)
        copy_range(card, st * SECTOR, p2, 0, cnt * SECTOR, "p2 extract", sparse=False, progress=None)
        stage = os.path.join(tmp, "stage")
        os.mkdir(stage)
        written = inject_into_p2(p2, selector_dir, conf_text, stage, media_files, replace_media)
        say("writing the patched p2 back to %s @LBA %d" % (card, st))
        copy_range(p2, 0, card, st * SECTOR, cnt * SECTOR, "p2 write-back", sparse=False, progress=None)
        a, b = md5_file(p2), md5_range(card, st * SECTOR, cnt * SECTOR)
        if a != b:
            raise Refused("p2 write-back mismatch (%s vs %s)" % (a, b))
        # the sidecar verify compares p2 against (rewritten on every injection)
        say("p2 md5 %s recorded in %s" % (write_p2_sidecar(card), p2_sidecar_path(card)))
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tree_source_title(plan, part, sub):
    """A default menu title for a games tree: the source image's name."""
    if sub:
        k = plan.multi_subdirs.index(sub) if sub in plan.multi_subdirs else -1
        x = plan.extras[k] if 0 <= k < len(plan.extras) else None
        return default_title(x) if x and x != plan.primary else "image %s" % device_name(part.num, sub)
    return default_title(part.src)


def conf_for_plan(plan, args, existing=None, media=None):
    """images.conf text for the card: --conf verbatim, else generated from the layout with the
    flags, falling back to `existing` (a parsed conf already on the card) then to defaults.
    `media` (plan_media's answer) supplies the per-image media rows, the sounds and the volume;
    without it an `existing` conf's media fields are carried through unchanged."""
    if getattr(args, "conf", None):
        with open(args.conf, "r") as f:
            text = f.read()
        parsed = parse_images_conf(text)
        devs = [d for (d, _t, _s) in parsed["images"]]
        if devs != plan.devices():
            raise Refused("--conf %s lists %r but the card holds %r" % (args.conf, devs, plan.devices()))
        return text
    ex = existing or {"images": [], "media": [], "default": None, "timeout": None, "font": None,
                      "sound_move": None, "sound_confirm": None, "volume": None, "mixer_volume": None}
    n = len(plan.trees)
    same_n = len(ex["images"]) == n
    titles = split_list(getattr(args, "titles", None))
    subtitles = split_list(getattr(args, "subtitles", None))
    if not titles:
        titles = [t for (_d, t, _s) in ex["images"]][:n] if same_n else \
                 [tree_source_title(plan, p, s) for (p, s) in plan.trees]
    if not subtitles:
        subtitles = [s for (_d, _t, s) in ex["images"]][:n] if same_n else []
    default = args.default if getattr(args, "default", None) is not None else (ex["default"] if ex["default"] is not None else 0)
    timeout = args.timeout if getattr(args, "timeout", None) is not None else (ex["timeout"] if ex["timeout"] is not None else 15)
    font = SELECT_DIR + "/font.ttf"
    sel = getattr(args, "selector_dir", None)
    if sel and not os.path.isfile(os.path.join(sel, "font.ttf")) and not os.path.isfile(HOST_FONT):
        font = None
    if media is not None:
        rows, move, confirm = media["rows"], media["sound_move"], media["sound_confirm"]
        volume, mixer = media["volume"], media["mixer_volume"]
    else:
        rows = list(ex.get("media") or [])[:n] if same_n else []
        move, confirm = ex.get("sound_move"), ex.get("sound_confirm")
        volume, mixer = ex.get("volume"), ex.get("mixer_volume")
    if getattr(args, "volume", None) is not None:
        volume = args.volume
    if getattr(args, "mixer_volume", None) is not None:
        mixer = args.mixer_volume
    return render_images_conf(plan.devices(), titles, subtitles, default, timeout, font,
                              rows, move, confirm, volume, mixer)


def card_conf(card):
    """The images.conf already on a card's p2, parsed, or None."""
    geom = Geometry.from_file(card)
    _t, st, _cnt = geom.part(2)
    ref = fs_ref(card, st * SECTOR)
    if not debugfs_exists(ref, SELECT_DIR + "/images.conf"):
        return None
    return parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))


def multi_subdirs_on(card, part_num=7):
    """The imgN subdirectories at the root of partition `part_num` (the multi layout's marker),
    numerically ordered, or [] when that partition is a plain games tree / not there / not ext4.
    Pure python (the ext4 reader), so a card is recognised on Windows too."""
    try:
        _vp, _sx, ext4 = _stern_plugins()
        off, size = part_range(card, part_num)
        with open(card, "rb") as f:
            r = ext4.Ext4Reader(f, off, size)
            root = r.read_inode(2)
            names = {n: (c, t) for (n, c, t) in r._iter_dir(root) if n not in (".", "..")}
            if "spk" in names:
                return []
            subs = []
            for n, (c, _t) in names.items():
                m = MULTI_SUBDIR_RE.match(n)
                if m and (r.read_inode(c)["mode"] & ext4.S_IFMT) == ext4.S_IFDIR:
                    subs.append((int(m.group(1)), n))
            return [n for (_k, n) in sorted(subs)]
    except Exception:
        return []


def plan_from_card(card):
    """A Plan describing an existing multi card: p3 + every logical after p6 is an image
    partition; a p7 whose root holds img1/, img2/ ... (and no spk/) is the multi layout."""
    G = Geometry.from_file(card)
    stock_logs = G.logical[:2]
    base = Geometry(G.size, G.mbr, G.prim, G.ext, stock_logs, G.ebr_raw, card)
    if len(G.logical) == 3:
        subs = multi_subdirs_on(card, 7)
        if subs:
            _e, _t, _st, cnt = G.logical[2]
            return Plan(base, [], card, [], "multi", multi_sectors=cnt, multi_subdirs=subs, multi_src=None)
    extra_geoms = []
    for ebr, t, st, cnt in G.logical[2:]:
        extra_geoms.append(Geometry(cnt * SECTOR, bytes(SECTOR), [(3, t, st, cnt)], None, [], path=card))
    return Plan(base, extra_geoms, card, [card] * len(extra_geoms))


# ============================================================================= the multi layout
def build_multi_partition(plan, workdir=None):
    """Build the multi layout's p7 image: every extra's games partition rdump'd into
    <tmp>/tree/imgK (symlinks survive - measured), mke2fs -d of that tree with the stock p3's
    feature set, ownership put back from the sources (rdump as a user cannot chown, and
    mke2fs -d records the running uid), e2fsck -fn.  -> (p7 image path, tmp dir to remove)."""
    need_tools("debugfs", "e2fsck", "mke2fs")
    mp = plan.multi_part
    tmp = tempfile.mkdtemp(prefix="mkmulticard.multi.", dir=workdir)
    tree = os.path.join(tmp, "tree")
    os.mkdir(tree)
    owners = {}
    t0 = time.monotonic()
    for sub, x, g in zip(plan.multi_subdirs, plan.extras, plan.extra_geoms):
        _t, st, _cnt = g.part(3)
        ref = fs_ref(x, st * SECTOR)
        dest = os.path.join(tree, sub)
        os.mkdir(dest)
        ents = [e for e in debugfs_ls(ref, "/") if e[4] not in (".", "..", "lost+found")]
        say("%s <- %s p3: %d root entries (%s)" % (sub, os.path.basename(x), len(ents),
                                                     ", ".join(e[4] for e in ents)))
        for ino, mode, uid, gid, name, size in ents:
            debugfs_rdump(ref, "/" + name, dest)
        for rel, ino, mode, uid, gid, size in debugfs_walk(ref, "/"):
            if rel == "lost+found" or rel.startswith("lost+found/"):
                continue
            owners[sub + "/" + rel] = (uid, gid)
        # the three links the machine boots through must have survived as links
        for name in ("game", "conagent", "data"):
            src_st = debugfs_stat(ref, "/" + name) if any(e[4] == name for e in ents) else None
            if src_st and src_st.get("link") is not None:
                p = os.path.join(dest, name)
                if not os.path.islink(p):
                    if os.path.lexists(p):
                        shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
                    os.symlink(src_st["link"], p)
                    say("  %s/%s recreated as a symlink -> %s" % (sub, name, src_st["link"]))
        title = [e[4] for e in ents if statmod.S_ISDIR(e[1]) and e[4] != "spk" and os.path.isfile(os.path.join(dest, e[4], "game"))]
        if not title:
            raise Refused("%s: no title directory with a game file came out of %s's p3" % (sub, x))
        say("  %s: title %s, %d entries copied in %.0f s" % (sub, "/".join(title), len(owners), time.monotonic() - t0))
    img = os.path.join(tmp, "p7.img")
    with open(img, "wb") as f:
        f.truncate(mp.count * SECTOR)
    say("mke2fs -d %s -> %s (%d MiB, label %s)" % (tree, img, mp.count * SECTOR >> 20, MULTI_LABEL))
    r = subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-m", "0", "-L", MULTI_LABEL, "-O", MULTI_FEATURES,
                        "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", tree, img, str(mp.count * SECTOR // 1024) + "k"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise Refused("mke2fs failed (rc=%d):\n%s" % (r.returncode, r.stdout.decode("utf-8", "replace")))
    shutil.rmtree(tree, ignore_errors=True)
    rc, txt = e2fsck(img)
    if rc != 0:
        raise Refused("the multi p7 image is not clean after mke2fs (rc=%d):\n%s" % (rc, txt))
    # ownership: every inode of the new filesystem back to what its source said (by inode
    # number, so symlinks are set and not followed); the root directory is root's
    cmds = ["set_inode_field <2> uid 0", "set_inode_field <2> gid 0"]
    for rel, ino, mode, uid, gid, size in debugfs_walk(img, "/"):
        if rel == "lost+found":
            continue
        want = owners.get(rel, (0, 0))
        if (uid, gid) != want:
            cmds.append("set_inode_field <%d> uid %d" % (ino, want[0]))
            cmds.append("set_inode_field <%d> gid %d" % (ino, want[1]))
    if cmds:
        debugfs_write_script(img, cmds)
        rc, txt = e2fsck(img)
        if rc != 0:
            raise Refused("the multi p7 image is not clean after the ownership fix (rc=%d):\n%s" % (rc, txt))
    say("p7 image built: %d ownership fixes, e2fsck clean, %.0f s" % (len(cmds) // 2, time.monotonic() - t0))
    return img, tmp


# ============================================================================= the validator bypass
def _stern_plugins():
    """(valpatch, sidx, ext4) - the app's own Stern modules, imported when first needed."""
    try:
        from pinball_decryptor.plugins.stern import valpatch, sidx, ext4
    except ImportError:
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        try:
            from pinball_decryptor.plugins.stern import valpatch, sidx, ext4
        except ImportError as e:
            raise Refused("the validator bypass needs the app's pinball_decryptor package "
                          "(looked beside %s): %s" % (REPO_ROOT, e))
    return valpatch, sidx, ext4


def bypass_state(elf):
    """'bypassed' (the entry already holds bx lr), 'armed' (a live validator was located),
    'absent' (this build carries none) or 'unlocated' (it carries one we cannot pin)."""
    valpatch, _s, _e = _stern_plugins()
    elf = bytes(elf)
    eoff = valpatch.find_validation_exec(elf)
    if eoff is not None:
        return "bypassed" if elf[eoff:eoff + 4] == valpatch._BX_LR else "armed"
    return "unlocated" if valpatch.carries_validator(elf) else "absent"


def bypass_words(state):
    return {"bypassed": "validator: bypassed", "armed": "validator: ARMED", "absent": "validator: none on this build",
            "unlocated": "validator: UNLOCATED (this build carries one the locator cannot pin)"}.get(state, "validator: ?")


def _dir_entries(reader, ino):
    return {n: (c, t) for (n, c, t) in reader._iter_dir(reader.read_inode(ino)) if n not in (".", "..")}


def tree_root_inode(reader, subdir):
    """The inode of a games tree's root: 2, or the subdir's inode under it (multi layout)."""
    _v, _s, ext4 = _stern_plugins()
    if not subdir:
        return 2
    ents = _dir_entries(reader, 2)
    if subdir not in ents:
        raise Refused("no %s directory at the root of this partition" % subdir)
    ino = ents[subdir][0]
    if (reader.read_inode(ino)["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
        raise Refused("%s is not a directory" % subdir)
    return ino


def tree_game(reader, root_ino):
    """(title, game path relative to the tree root, inode number, inode) of the tree's game ELF:
    the title directory's game_real when it is an ARM ELF, else its game.  Refused when the tree
    has no title directory holding a game."""
    _v, _s, ext4 = _stern_plugins()
    for name, (c, t) in sorted(_dir_entries(reader, root_ino).items()):
        if name in ("lost+found", "spk"):
            continue
        try:
            node = reader.read_inode(c)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
            continue
        inside = _dir_entries(reader, c)
        if "game" not in inside:
            continue
        for cand in ("game_real", "game"):
            if cand in inside:
                gi = inside[cand][0]
                gn = reader.read_inode(gi)
                if (gn["mode"] & ext4.S_IFMT) == ext4.S_IFREG and gn["size"] > 0:
                    return name, "%s/%s" % (name, cand), gi, gn
    raise Refused("no title directory with a game file in this tree")


def tree_sidx(reader, root_ino):
    """(path relative to the tree root, inode) of the tree's /spk/index/*.sidx, or (None, None)."""
    for path, ino, node in reader.iter_regular_files(root_ino=root_ino, max_depth=6, min_size=1):
        if path.endswith(".sidx") and "/spk/index/" in path:
            return path.lstrip("/"), node
    return None, None


def compute_bypass_writes(reader, root_ino):
    """Neuter the tree's validator and refresh its .sidx record, as plugins/stern/valpatch's
    compute_writes does for a whole partition - but rooted at `root_ino` so a multi layout's
    imgN tree patches ITS game and ITS manifest.  -> (state before, [(disk offset, bytes)],
    notes).  No writes when the state is not 'armed'."""
    valpatch, sidx, _e = _stern_plugins()
    title, gpath, gino, gnode = tree_game(reader, root_ino)
    elf = bytearray(reader.read_file_bytes(gnode))
    state = bypass_state(elf)
    notes = ["%s (%d bytes)" % (gpath, len(elf))]
    if state != "armed":
        return state, [], notes
    eoff = valpatch.find_validation_exec(bytes(elf))
    elf[eoff:eoff + 4] = valpatch._BX_LR
    writes = []
    b = valpatch._BX_LR
    for disk, n in reader.disk_ranges(gnode, eoff, 4):
        writes.append((disk, b[:n]))
        b = b[n:]
    notes.append("bx lr at ELF offset 0x%x" % eoff)
    spath, snode = tree_sidx(reader, root_ino)
    if snode is None:
        notes.append("no .sidx manifest in this tree - the spk layer may flag the game file")
        return state, writes, notes
    sdata = reader.read_file_bytes(snode)
    recs, _crc, fmt = sidx.parse_records(sdata)
    # the manifest names the game file by its path in the tree; match by inode (extent block)
    # like valpatch does, so game vs game_real is settled by what is actually on disk
    want = bytes(gnode["i_block"])
    rec_path = None
    for path, ino, node in reader.iter_regular_files(root_ino=root_ino, max_depth=20, min_size=0x10000):
        if ino == gino or bytes(node["i_block"]) == want:
            if path.lstrip("/") in recs:
                rec_path = path.lstrip("/")
                break
    if rec_path is None and gpath in recs:
        rec_path = gpath
    if rec_path is None:
        notes.append("%s has no record for %s - the spk layer may flag the game file" % (spath, gpath))
        return state, writes, notes
    hm, md = sidx.digests(bytes(elf))
    for foff, rb in sidx.record_field_writes(recs[rec_path], hm, md, fmt):
        for disk, n in reader.disk_ranges(snode, foff, len(rb)):
            writes.append((disk, rb[:n]))
            rb = rb[n:]
    notes.append("%s record %r (%s) refreshed" % (spath, rec_path, fmt))
    return state, writes, notes


def card_trees(card, plan=None):
    """[(index, Part, subdir)] of every games tree on a card, from `plan` (default: read off the card)."""
    plan = plan or plan_from_card(card)
    return [(i, p, s) for i, (p, s) in enumerate(plan.trees)]


def tree_state(card, part, subdir):
    """(bypass state, title, game path) of one tree on `card` - read-only."""
    _v, _s, ext4 = _stern_plugins()
    with open(card, "rb") as f:
        r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
        root = tree_root_inode(r, subdir)
        title, gpath, _gi, gnode = tree_game(r, root)
        return bypass_state(r.read_file_bytes(gnode)), title, gpath


def bypass_card(card, plan=None, dry_run=False):
    """Apply the validator bypass to every games tree on `card`, rewrite the sidecar of every
    partition written into, print one line per tree.  -> {index: state after}."""
    _v, _s, ext4 = _stern_plugins()
    plan = plan or plan_from_card(card)
    states = {}
    touched = []
    for i, part, sub in card_trees(card, plan):
        dev = device_name(part.num, sub)
        try:
            with open(card, "rb") as f:
                r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
                root = tree_root_inode(r, sub)
                before, writes, notes = compute_bypass_writes(r, root)
        except Refused as e:
            print("image %d %s: validator: SKIPPED (%s)" % (i, dev, e))
            states[i] = "error"
            continue
        if before == "armed" and writes and not dry_run:
            with open(card, "r+b") as f:
                for disk, b in writes:
                    f.seek(disk)
                    f.write(b)
                f.flush()
            touched.append(part.num)
            after = "bypassed"
        else:
            after = before
        line = bypass_words(after)
        if before == "armed" and after == "bypassed":
            line += " (was armed; %d bytes written)" % sum(len(b) for (_d, b) in writes)
        elif before == "armed" and dry_run:
            line += " (dry run: %d bytes would be written)" % sum(len(b) for (_d, b) in writes)
        elif before == "bypassed":
            line += " (already)"
        print("image %d %s: %s - %s" % (i, dev, line, "; ".join(notes)))
        states[i] = after
    for n in sorted(set(touched)):
        say("p%d md5 %s recorded in %s" % (n, write_part_sidecar(card, n), sidecar_path(card, n)))
    return states


# ============================================================================= verify
def sfdisk_table(image):
    """[(num, start, count, type)] from `sfdisk -d`.  The device column is the image path plus
    the partition number, and the path may hold a SPACE ('.../TMNT 1987/multi.img7 : start=...'),
    so it is matched with .*? rather than \\S+ - the latter parsed such a card to []."""
    r = subprocess.run(["sfdisk", "-d", image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(.*?)(\d+)\s*:\s*start=\s*(\d+),\s*size=\s*(\d+),\s*type=\s*([0-9a-fA-F]+)", line)
        if m:
            rows.append((int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16)))
    return rows, out


def verify_card(card, plan, selector_dir=None, media_dir=None):
    ok = True

    def check(label, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print("%-58s %s%s" % (label, "OK" if good else "FAIL", ("  " + detail) if detail else ""))

    need_tools("debugfs", "e2fsck", "sfdisk", "fdisk")
    O = Geometry.from_file(card)
    got = [(n, t, st, cnt) for (n, t, st, cnt) in O.prim] + [(5 + i, t, st, cnt) for i, (_e, t, st, cnt) in enumerate(O.logical)]
    check("table parse-back (own parser)", plan.table() == got, "" if plan.table() == got else "got %r" % (got,))
    rows, sf = sfdisk_table(card)
    want_sf = [(n, st, cnt, t) for (n, t, st, cnt) in plan.table()]
    check("table parse-back (sfdisk -d)", rows == want_sf, "" if rows == want_sf else "got %r" % (rows,))
    print(sf.rstrip())
    r = subprocess.run(["fdisk", "-l", card], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout.decode("utf-8", "replace").rstrip())
    check("image size %d" % plan.total_bytes, os.path.getsize(card) == plan.total_bytes, "actual %d" % os.path.getsize(card))
    # the MBR: bootstrap + disk id verbatim, entries regenerated
    with open(card, "rb") as f:
        mbr = f.read(SECTOR)
    check("MBR bootstrap + disk id verbatim", mbr[:0x1BE] == plan.primary_geom.mbr[:0x1BE])
    check("MBR entries", mbr[0x1BE:] == mbr_sector(plan)[0x1BE:])
    a = md5_range(plan.primary, SECTOR, (PRE_P1 - 1) * SECTOR)
    b = md5_range(card, SECTOR, (PRE_P1 - 1) * SECTOR)
    check("sectors 1..%d (u-boot) md5" % (PRE_P1 - 1), a == b, a)
    for i, p in enumerate(plan.logs):
        with open(card, "rb") as f:
            f.seek(p.ebr * SECTOR)
            eb = f.read(SECTOR)
        check("EBR for p%d @%d" % (p.num, p.ebr), eb == ebr_sector(plan, i))
    # every copied range: against its source, or against the sidecar recorded when this tool
    # wrote into it after the copy (the validator bypass, the multi layout's built p7)
    for p in plan.prims + plan.logs:
        t0 = time.monotonic()
        if p.num == 2:
            continue
        try:
            want = read_part_sidecar(card, p.num)
        except Refused as e:
            check("p%d sidecar" % p.num, False, str(e))
            continue
        b = md5_range(card, p.start * SECTOR, p.count * SECTOR)
        if want is not None:
            check("p%d md5 vs sidecar %s (written into; %.0f s)" % (p.num, os.path.basename(sidecar_path(card, p.num)), time.monotonic() - t0),
                  want == b, b if want == b else "card %s sidecar %s" % (b, want))
        elif p.src:
            a = md5_range(p.src, p.src_start * SECTOR, p.count * SECTOR)
            check("p%d md5 vs %s (%.0f s)" % (p.num, os.path.basename(p.src), time.monotonic() - t0), a == b, a)
        else:
            check("p%d md5" % p.num, False, "no source image and no %s sidecar to hold it to" % os.path.basename(sidecar_path(card, p.num)))
    # p2 is patched, so its source is no oracle: the sidecar written at the last write-back is
    t0 = time.monotonic()
    try:
        want, got = check_p2_sidecar(card)
        if want is None:
            print("p2: no sidecar (built before this check)")
        else:
            check("p2 sidecar md5 (%s, %.0f s)" % (os.path.basename(p2_sidecar_path(card)), time.monotonic() - t0),
                  want == got, got if want == got else "card %s sidecar %s" % (got, want))
    except Refused as e:
        check("p2 sidecar md5", False, str(e))
    # p2: patched
    p2 = plan.prims[1]
    ref = fs_ref(card, p2.start * SECTOR)
    pref = fs_ref(plan.primary, p2.src_start * SECTOR)
    print("p2 (rootfs): patched - selector files and the hooked %s:" % GAME_SCRIPT)
    try:
        cur = debugfs_cat(ref, GAME_SCRIPT).decode("utf-8", "replace")
        orig = debugfs_cat(pref, GAME_SCRIPT).decode("utf-8", "replace")
        diff = list(difflib.unified_diff(orig.splitlines(), cur.splitlines(), "primary:" + GAME_SCRIPT, "card:" + GAME_SCRIPT, lineterm="", n=1))
        print("\n".join("    " + l for l in diff) if diff else "    (identical - NOT hooked)")
        check("%s = primary's + the hook block only" % GAME_SCRIPT, has_hook(cur) and strip_hook(cur) == orig)
        st = debugfs_stat(ref, GAME_SCRIPT)
        ost = debugfs_stat(pref, GAME_SCRIPT)
        check("%s mode/uid/gid/mtime kept" % GAME_SCRIPT,
              all(st.get(k) == ost.get(k) for k in ("mode", "uid", "gid", "mtime")),
              "card %r primary %r" % ({k: st.get(k) for k in ("mode", "uid", "gid", "mtime")},
                                      {k: ost.get(k) for k in ("mode", "uid", "gid", "mtime")}))
    except Refused as e:
        check("p2 game script", False, str(e))
    try:
        ents = [e for e in debugfs_ls(ref, SELECT_DIR) if e[4] not in (".", "..")]
        for ino, mode, uid, gid, name, size in ents:
            print("    %s/%-14s mode %o uid %d gid %d %d bytes" % (SELECT_DIR, name, mode & 0o7777, uid, gid, size))
        names = {e[4] for e in ents}
        check("%s holds codeselect, select.sh, images.conf" % SELECT_DIR, {"codeselect", "select.sh", "images.conf"} <= names)
        conf = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
        devs = [d for (d, _t, _s) in conf["images"]]
        check("images.conf devices = %r" % (plan.devices(),), devs == plan.devices(), "got %r" % (devs,))
        for (d, t, s), m in zip(conf["images"], conf["media"]):
            print("    image %s | %s | %s%s" % (d, t, s, (" | %s | %s | %s" % m) if any(m) else ""))
        print("    default=%d timeout=%d font=%s" % (conf["default"], conf["timeout"], conf["font"]))
        print("    sound_move=%s sound_confirm=%s volume=%s mixer_volume=%s media=%s"
              % (conf["sound_move"], conf["sound_confirm"], conf["volume"], conf["mixer_volume"], conf["media_dir"]))
        if selector_dir:
            for name, (cardname, mode, required) in SELECTOR_FILES.items():
                src = os.path.join(selector_dir, name)
                if os.path.isfile(src) and cardname in names:
                    back = hashlib.md5(debugfs_cat(ref, SELECT_DIR + "/" + cardname)).hexdigest()
                    check("%s/%s == selector dir's" % (SELECT_DIR, cardname), back == md5_file(src))
        # the media directory (item 90 v2): listed, every conf-named file present, md5 vs --media-dir
        wanted = conf_media_names(conf)
        on_card = {}
        if any(e[4] == "media" and statmod.S_ISDIR(e[1]) for e in ents):
            for ino, mode, uid, gid, name, size in debugfs_ls(ref, MEDIA_DIR):
                if name in (".", ".."):
                    continue
                on_card[name] = size
                print("    %s/%-24s mode %o uid %d gid %d %d bytes" % (MEDIA_DIR, name, mode & 0o7777, uid, gid, size))
            print("    media: %d files, %s (budget %s)" % (len(on_card), _gb(sum(on_card.values())), _gb(MEDIA_BUDGET)))
            check("%s total <= budget" % MEDIA_DIR, sum(on_card.values()) <= MEDIA_BUDGET)
        else:
            print("    (no %s)" % MEDIA_DIR)
        missing = [n for n in wanted if n not in on_card]
        check("images.conf media files present on the card (%d named)" % len(wanted), not missing, "missing %r" % (missing,) if missing else "")
        if media_dir:
            for name in sorted(on_card):
                src = os.path.join(media_dir, name)
                if os.path.isfile(src):
                    back = hashlib.md5(debugfs_cat(ref, MEDIA_DIR + "/" + name)).hexdigest()
                    check("%s/%s == %s's" % (MEDIA_DIR, name, os.path.basename(media_dir)), back == md5_file(src))
                else:
                    check("%s/%s in %s" % (MEDIA_DIR, name, media_dir), False, "not in the media dir")
    except Refused as e:
        check("p2 selector files", False, str(e))
    # every ext4 partition
    for p in plan.prims + plan.logs:
        if p.ptype != 0x83:
            continue
        t0 = time.monotonic()
        rc, txt = e2fsck(fs_ref(card, p.start * SECTOR))
        check("e2fsck -fn p%d (%.0f s)" % (p.num, time.monotonic() - t0), rc == 0, "" if rc == 0 else txt.strip().splitlines()[-1])
    # every games tree: its root (title dir + the game link) and the validator's state
    for i, (p, sub) in enumerate(plan.trees):
        dev = device_name(p.num, sub)
        root = ("/" + sub) if sub else "/"
        try:
            ref = fs_ref(card, p.start * SECTOR)
            ents = debugfs_ls(ref, root)
            dirs = [e[4] for e in ents if statmod.S_ISDIR(e[1]) and e[4] not in (".", "..", "lost+found", "spk")]
            has_spk = any(e[4] == "spk" and statmod.S_ISDIR(e[1]) for e in ents)
            links = {}
            for name in ("game", "conagent", "data"):
                if any(e[4] == name and statmod.S_ISLNK(e[1]) for e in ents):
                    links[name] = debugfs_stat(ref, root.rstrip("/") + "/" + name).get("link")
            check("image %d %s root: spk %s, title dir %r, links %r" % (i, dev, "yes" if has_spk else "NO", dirs, links),
                  dirs and has_spk and links.get("game"))
        except Refused as e:
            check("image %d %s root" % (i, dev), False, str(e))
        try:
            state, title, gpath = tree_state(card, p, sub)
            print("image %d %s bypass_status: %s (%s)" % (i, dev, state, gpath))
        except Refused as e:
            print("image %d %s bypass_status: unknown (%s)" % (i, dev, e))
    alloc = allocated_bytes(card)
    if alloc is not None:
        print("allocated %s of %s apparent (sparse)" % (_gb(alloc), _gb(os.path.getsize(card))))
    print("VERIFY %s %s" % (card, "PASS" if ok else "FAIL"))
    return ok


def check_stock(path):
    """Regenerate the stock card's own table with this writer and compare bytes."""
    plan = make_plan(path, [])
    P = plan.primary_geom
    m = mbr_sector(plan)
    ok = True
    print("MBR entries 0x1be..0x1ff regenerated == stock: %s" % (m[0x1BE:] == P.mbr[0x1BE:]))
    if m[0x1BE:] != P.mbr[0x1BE:]:
        ok = False
        print("  want", P.mbr[0x1BE:].hex())
        print("  got ", m[0x1BE:].hex())
    for i, p in enumerate(plan.logs):
        e = ebr_sector(plan, i)
        raw = P.ebr_raw.get(p.ebr)
        print("EBR @%d regenerated == stock: %s" % (p.ebr, e == raw))
        if e != raw:
            ok = False
            print("  want", (raw or b"").hex())
            print("  got ", e.hex())
    print("stock image sectors %d, plan total %d (%s)" % (P.sectors, plan.total, "OK" if P.sectors == plan.total else "DIFFERENT"))
    for w in P.shape_issues():
        print("WARNING: " + w)
    return ok and P.sectors == plan.total


# ============================================================================= synthetic cards
SYNTH_PARTS = {1: (0x0C, 8192, 2048), 2: (0x83, 10240, 2048), 3: (0x83, 12288, 2046)}
SYNTH_EXT = 14336
SYNTH_LOGS = [(5, 0x83, 16384, 2046), (6, 0x83, 18432, 2046)]
# (built by concatenation: the anchor's trailing space must never sit at a physical line end,
#  where an editor would strip it)
SYNTH_GAME = ("#!/bin/sh\n"
              "# synthetic stand-in for Stern's /etc/init.d/game (mkmulticard selftest)\n"
              "GAMES_PATH=/games\n\n"
              "echo \"checking network bridge code version...\"\n\n"
              + PKILL_LINE + "\n\n"
              + IF_LINE + "\n"
              "\techo \"starting application...\"\n"
              "fi\n")


def _mkext(path, kib, files, links=()):
    """A 1 KiB-block ext4 image holding `files` {card path: bytes} (parents created) and symlinks."""
    with open(path, "wb") as f:
        f.truncate(kib * 1024)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-b", "1024", path, str(kib)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmds, made = [], set()
    stage = tempfile.mkdtemp(prefix="synth.")
    for k, (cardpath, data) in enumerate(files.items()):
        parts = cardpath.strip("/").split("/")
        for d in range(1, len(parts)):
            dp = "/" + "/".join(parts[:d])
            if dp not in made:
                made.add(dp)
                cmds.append("mkdir " + dp)
        sp = os.path.join(stage, "f%d" % k)
        with open(sp, "wb") as f:
            f.write(data)
        os.chmod(sp, 0o755)
        cmds.append("write %s %s" % (dq(sp), dq(cardpath)))
    for name, target in links:
        cmds.append("symlink %s %s" % (name, target))
    try:
        debugfs_write_script(path, cmds)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def make_synthetic_card(path, tag, seed, with_fs=False):
    """A stock-shaped card, 10 MiB: p1@8192x2048 p2@10240x2048 p3@12288x2046 ext@14336 p5@16384x2046
    EBR2@18430 p6@18432x2046.  with_fs=False: random payloads (pure python, for the tests);
    with_fs=True: real ext4 with a stand-in game script in p2 and a title dir + game link in p3."""
    import random
    rnd = random.Random(seed)
    d = os.path.dirname(os.path.abspath(path))
    ebrs = [SYNTH_EXT, SYNTH_LOGS[0][2] + SYNTH_LOGS[0][3]]
    assert align_up(ebrs[1] + 1) == SYNTH_LOGS[1][2]
    prev_end = SYNTH_LOGS[1][2] + SYNTH_LOGS[1][3] - 1
    ext_count = prev_end + 1 - SYNTH_EXT
    total = prev_end + 1 + TAIL
    payload = {}

    def blob(n):
        return rnd.getrandbits(n * 8).to_bytes(n, "little")

    for n, (t, st, cnt) in SYNTH_PARTS.items():
        payload[n] = None
    for n, t, st, cnt in SYNTH_LOGS:
        payload[n] = None
    for n in payload:
        cnt = SYNTH_PARTS[n][2] if n in SYNTH_PARTS else [l for l in SYNTH_LOGS if l[0] == n][0][3]
        if with_fs and n != 1:
            p = os.path.join(d, "%s_p%d.ext4" % (tag, n))
            if n == 2:
                _mkext(p, cnt * SECTOR // 1024, {"/etc/init.d/game": SYNTH_GAME.encode(), "/usr/local/README": b"synthetic\n"})
            elif n == 3:
                # a stock games root in miniature: spk/, the title dir (game, conagent, data/),
                # and the three symlinks the machine boots through
                _mkext(p, cnt * SECTOR // 1024,
                       {"/%s_title/game" % tag: ("%s p3 game\n" % tag).encode(),
                        "/%s_title/conagent" % tag: ("%s p3 conagent\n" % tag).encode(),
                        "/%s_title/data/marker" % tag: ("%s p3 data\n" % tag).encode(),
                        "/spk/index/%s_title.sidx" % tag: b"not a manifest\n"},
                       links=[("/game", "%s_title/game" % tag), ("/conagent", "%s_title/conagent" % tag),
                              ("/data", "%s_title/data" % tag)])
            else:
                _mkext(p, cnt * SECTOR // 1024, {"/MARKER": ("%s p%d\n" % (tag, n)).encode()})
            with open(p, "rb") as f:
                payload[n] = f.read()
        else:
            payload[n] = blob(cnt * SECTOR)
    boot = bytearray(SECTOR)
    boot[:0x4C] = blob(0x4C)                                # fake bootstrap
    boot[0x1B8:0x1BC] = struct.pack("<I", seed & 0xffffffff)  # disk id
    boot[0x1BE:0x1FE] = b"".join([entry(*SYNTH_PARTS[1]), entry(*SYNTH_PARTS[2]), entry(*SYNTH_PARTS[3]),
                                  entry(0x0F, SYNTH_EXT, ext_count)])
    boot[510:512] = b"\x55\xaa"
    with open(path, "wb") as o:
        o.truncate(total * SECTOR)
    with open(path, "r+b") as o:
        o.seek(0)
        o.write(bytes(boot))
        o.seek(2 * SECTOR)
        o.write(blob(654 * SECTOR))                         # fake u-boot at sectors 2..655
        for n, (t, st, cnt) in SYNTH_PARTS.items():
            o.seek(st * SECTOR)
            o.write(payload[n])
        for i, (n, t, st, cnt) in enumerate(SYNTH_LOGS):
            eb = bytearray(SECTOR)
            eb[0x1BE:0x1CE] = entry(t, st - ebrs[i], cnt, chs_base=ebrs[i])
            if i + 1 < len(SYNTH_LOGS):
                _nn, _nt, nst, ncnt = SYNTH_LOGS[i + 1]
                eb[0x1CE:0x1DE] = entry(0x05, ebrs[i + 1] - SYNTH_EXT, nst + ncnt - ebrs[i + 1], chs_base=SYNTH_EXT)
            eb[510:512] = b"\x55\xaa"
            o.seek(ebrs[i] * SECTOR)
            o.write(bytes(eb))
            o.seek(st * SECTOR)
            o.write(payload[n])
    return path


def synth_png(path, w=4, h=3, rgb=(0xC0, 0x30, 0x40)):
    """A tiny valid RGB PNG (zlib only)."""
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)
    return data


def synth_gif(path, w=4, h=3, frames=2):
    """A tiny valid animated GIF (2-colour global table, one uncompressed-ish LZW image per frame)."""
    out = bytearray(b"GIF89a" + struct.pack("<HH", w, h) + bytes([0x80, 0, 0]) + b"\x00\x00\x00\xff\xff\xff")
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"                       # loop for ever
    for i in range(frames):
        out += b"\x21\xf9\x04\x00\x0a\x00\x00\x00"                                # GCE: 100 ms
        out += b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00"               # image descriptor
        # LZW min code size 2: codes clear=4, end=5, 3 bits wide.  A clear before EVERY pixel
        # keeps the decoder's table empty, so the width never grows and each pixel is one
        # 3-bit literal (0 or 1).
        pix = [(x + i) & 1 for x in range(w * h)]
        bits, nb, cur = [], 0, 0
        codes = []
        for p in pix:
            codes += [4, p]
        codes.append(5)
        width = 3
        for c in codes:
            cur |= c << nb
            nb += width
            while nb >= 8:
                bits.append(cur & 0xff)
                cur >>= 8
                nb -= 8
        if nb:
            bits.append(cur & 0xff)
        out += b"\x02"                                                            # LZW minimum code size
        for k in range(0, len(bits), 255):                                        # <= 255-byte sub-blocks
            blk = bits[k:k + 255]
            out += bytes([len(blk)]) + bytes(blk)
        out += b"\x00"
    out += b"\x3b"
    with open(path, "wb") as f:
        f.write(out)
    return bytes(out)


def synth_wav(path, rate=WAV_RATE, ch=2, secs=0.05, bits=16):
    """A short RIFF pcm WAV of silence (the header is what the checks read)."""
    n = int(rate * secs)
    data = bytes(n * ch * (bits // 8))
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def synth_media_dir(d, n_images):
    """A media directory with media.json for `n_images` images: art for every image, an anim
    and a music for image 1, the two sounds.  -> path."""
    os.makedirs(d, exist_ok=True)
    imgs = []
    for i in range(n_images):
        synth_png(os.path.join(d, "art%d.png" % i))
        imgs.append({"art": "art%d.png" % i, "anim": None, "music": None})
    if n_images > 1:
        synth_gif(os.path.join(d, "anim1.gif"))
        synth_wav(os.path.join(d, "music1.wav"))
        imgs[1]["anim"], imgs[1]["music"] = "anim1.gif", "music1.wav"
    synth_wav(os.path.join(d, "move.wav"), ch=1)
    synth_wav(os.path.join(d, "confirm.wav"))
    synth_wav(os.path.join(d, "wrong_rate.wav"), rate=48000)                # unreferenced, must NOT be staged
    with open(os.path.join(d, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"images": imgs, "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 40}, f, indent=1)
    return d


def selftest(d, selector_file=None):
    """PART 1 (parts layout): synthetic A+B+C -> 3-image card with injection + media -> verify ->
    inject again with the media dir present (idempotence) -> verify -> a byte of p2 flipped
    outside the injected files -> verify FAILS on the sidecar -> put back.  Three images on
    purpose (p7 AND p8): the layout arithmetic is exercised past the hardware limit; the plan
    printout says p8 is unreachable, and the build here is what --allow-unreachable would do.
    PART 2 (multi layout): the same three sources as a p3 + p7{img1,img2} card: parse-back of
    the devices, the symlinks and ownership of p7/img1 by debugfs ls, e2fsck, the bypass
    subcommand on trees whose game is not an ELF ('none on this build'), verify PASS.
    The staging directory has a SPACE in its name so the debugfs quoting is exercised."""
    need_tools("debugfs", "e2fsck", "mke2fs", "sfdisk", "fdisk")
    d = os.path.join(d, "self test")
    os.makedirs(d, exist_ok=True)
    A = make_synthetic_card(os.path.join(d, "A.img"), "A", 0x0A0A0A0A, with_fs=True)
    B = make_synthetic_card(os.path.join(d, "B.img"), "B", 0x0B0B0B0B, with_fs=True)
    C = make_synthetic_card(os.path.join(d, "C.img"), "C", 0x0C0C0C0C, with_fs=True)
    sel = os.path.join(d, "seldir")
    os.makedirs(sel, exist_ok=True)
    with open(os.path.join(sel, "codeselect"), "wb") as f:
        f.write(open(selector_file, "rb").read() if selector_file else b"#!/bin/sh\necho '[select] chose 0 selftest'\n")
    with open(os.path.join(sel, "select.sh"), "w", newline="\n") as f:
        f.write("#!/bin/sh\n# selftest placeholder\nexit 0\n")
    media = synth_media_dir(os.path.join(d, "media dir"), 3)
    out = os.path.join(d, "multi.img")
    if os.path.exists(out):
        os.unlink(out)
    drop_stale_sidecars(out, keep=())
    plan = make_plan(A, [B, C], layout="parts")
    print("== plan (parts)")
    print_plan(plan)
    ok = plan.unreachable_note() == "p8 unreachable on the machine"
    try:
        check_reachable(plan)
        print("SELFTEST: check_reachable accepted a p8 image")
        ok = False
    except Refused as e:
        print("refused without --allow-unreachable, as it should be: %s" % str(e).splitlines()[0])
    check_reachable(plan, allow=True)
    print("== build (parts)")
    build_image(plan, out)
    ms = plan_media(media, 3)
    ok &= list(ms["files"]) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "art2.png", "move.wav", "confirm.wav"]
    ok &= "wrong_rate.wav" not in ms["files"] and ms["volume"] == 40
    conf = render_images_conf(plan.devices(), ["A stock", "B", "C"], ["synthetic", "", "third"], 1, 7, None,
                              ms["rows"], ms["sound_move"], ms["sound_confirm"], ms["volume"])
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"])
    print("== verify")
    ok &= verify_card(out, plan, sel, media)
    print("== inject again with the media directory present (idempotence)")
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"])
    ok &= verify_card(out, plan, sel, media)
    print("== inject without media: the media directory and the conf's media fields are carried through")
    carried = conf_for_plan(plan, argparse.Namespace(), existing=card_conf(out))
    inject_card(out, sel, carried, workdir=d)
    ok &= verify_card(out, plan, sel, media)
    print("== p2 corrupted outside the injected files: verify must FAIL on the sidecar")
    p2off, p2len = p2_range(out)
    spot = p2off + p2len - 3 * 1024            # the last blocks of a 1 MiB ext4: free, so e2fsck stays clean
    with open(out, "r+b") as f:
        f.seek(spot)
        was = f.read(1)
        f.seek(spot)
        f.write(bytes([was[0] ^ 0xff]))
    want, got = check_p2_sidecar(out)
    ok &= want is not None and want != got
    ok &= not verify_card(out, plan, sel)
    with open(out, "r+b") as f:
        f.seek(spot)
        f.write(was)
    want, got = check_p2_sidecar(out)
    ok &= want == got
    print("== p2 put back: verify PASS again")
    ok &= verify_card(out, plan, sel)
    ref = fs_ref(out, plan.prims[1].start * SECTOR)
    back = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
    ok &= back["images"] == [("/dev/mmcblk0p3", "A stock", "synthetic"), ("/dev/mmcblk0p7", "B", ""), ("/dev/mmcblk0p8", "C", "third")]
    ok &= back["media"] == [("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav"), ("art2.png", "", "")]
    ok &= back["default"] == 1 and back["timeout"] == 7 and back["volume"] == 40
    ok &= (back["sound_move"], back["sound_confirm"], back["media_dir"]) == ("move.wav", "confirm.wav", MEDIA_DIR)
    names = sorted(e[4] for e in debugfs_ls(ref, MEDIA_DIR) if e[4] not in (".", ".."))
    ok &= names == sorted(ms["files"])
    print("media on the card: %s" % ", ".join(names))
    for n in (7, 8):
        _t, st, _c = Geometry.from_file(out).part(n)
        link = debugfs_stat(fs_ref(out, st * SECTOR), "/game").get("link")     # a fast symlink has no blocks to cat
        marker = debugfs_cat(fs_ref(out, st * SECTOR), "/" + (link or "game")).decode().strip()
        print("p%d /game -> %r -> %r" % (n, link, marker))
        ok &= marker == ("%s p3 game" % ("B" if n == 7 else "C"))
    print("== a media set that names a missing file / a 48 kHz WAV is refused before anything is written")
    bad = synth_media_dir(os.path.join(d, "bad media"), 3)
    with open(os.path.join(bad, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"images": [{"art": "art0.png"}, {"art": "nope.png"}, {}], "sound_move": "move.wav"}, f)
    for want_msg, man in (("does not exist", None),
                          ("48000 Hz", {"images": [{}, {}, {}], "sound_move": "wrong_rate.wav"}),
                          ("plain media file name", {"images": [{"art": "../x.png"}, {}, {}]}),
                          ("lists 2 images", {"images": [{}, {}]})):
        if man is not None:
            with open(os.path.join(bad, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
                json.dump(man, f)
        try:
            plan_media(bad, 3)
            print("SELFTEST: a bad media set was accepted (%s)" % want_msg)
            ok = False
        except Refused as e:
            print("refused: %s" % e)
            ok &= want_msg in str(e)
    print("SELFTEST part 1 (parts layout)", "PASS" if ok else "FAIL")

    # ---------------------------------------------------------------- part 2: the multi layout
    print("== plan (multi)")
    out2 = os.path.join(d, "multi3.img")
    if os.path.exists(out2):
        os.unlink(out2)
    drop_stale_sidecars(out2, keep=())
    plan2 = make_plan(A, [B, C], layout="auto")
    ok &= plan2.layout == "multi" and plan2.multi_subdirs == ["img1", "img2"]
    ok &= plan2.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "/dev/mmcblk0p7:img2"]
    ok &= [p.num for p in plan2.logs] == [5, 6, 7] and plan2.unreachable() == []
    print_plan(plan2)
    print("== build (multi)")
    p7img, tmp = build_multi_partition(plan2, workdir=d)
    try:
        plan2 = plan2.with_multi_src(p7img)
        build_image(plan2, out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say("p7 md5 %s recorded in %s" % (write_part_sidecar(out2, 7), sidecar_path(out2, 7)))
    conf2 = conf_for_plan(plan2, argparse.Namespace(titles="A stock;B;C", subtitles="synthetic;;third", timeout=9))
    inject_card(out2, sel, conf2, workdir=d)
    print("== the card reads back as a multi card")
    back2 = plan_from_card(out2)
    ok &= back2.layout == "multi" and back2.devices() == plan2.devices() and back2.table() == plan2.table()
    for sub, tag in (("img1", "B"), ("img2", "C")):
        _t, st, _c = Geometry.from_file(out2).part(7)
        ref7 = fs_ref(out2, st * SECTOR)
        ents = {e[4]: e for e in debugfs_ls(ref7, "/" + sub)}
        print("p7/%s: %s" % (sub, ", ".join("%s(%o uid %d)" % (n, e[1] & 0o170777, e[2]) for n, e in sorted(ents.items()) if n not in (".", ".."))))
        ok &= statmod.S_ISDIR(ents["spk"][1]) and statmod.S_ISDIR(ents["%s_title" % tag][1])
        for name in ("game", "conagent", "data"):
            ok &= name in ents and statmod.S_ISLNK(ents[name][1]) and ents[name][2] == 0 and ents[name][3] == 0
        link = debugfs_stat(ref7, "/%s/game" % sub).get("link")
        marker = debugfs_cat(ref7, "/%s/%s" % (sub, link)).decode().strip()
        print("p7/%s/game -> %r -> %r" % (sub, link, marker))
        ok &= marker == "%s p3 game" % tag and link == "%s_title/game" % tag
        ok &= ents["%s_title" % tag][2] == 0 and ents["spk"][2] == 0
    print("== bypass on trees whose game is not an ELF: 'none on this build', nothing written")
    before = md5_file(out2)
    states = bypass_card(out2)
    ok &= states == {0: "absent", 1: "absent", 2: "absent"} and md5_file(out2) == before
    print("== verify (multi)")
    ok &= verify_card(out2, plan2, sel)
    ref2 = fs_ref(out2, plan2.prims[1].start * SECTOR)
    cb = parse_images_conf(debugfs_cat(ref2, SELECT_DIR + "/images.conf"))
    ok &= [dv for (dv, _t, _s) in cb["images"]] == plan2.devices() and cb["timeout"] == 9
    ok &= [t for (_d, t, _s) in cb["images"]] == ["A stock", "B", "C"]
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


# ============================================================================= CLI
def _add_images(s, out_flag, reach_flag=True, layout_flag=True):
    s.add_argument("--primary", required=True, help="the image whose p1/p2/p3/p5/p6 the card gets (index 0)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG",
                   help="an extra image (its games partition becomes p7 [parts layout] or p7/imgN [multi layout])")
    if out_flag:
        s.add_argument(out_flag, required=True, help="the multi-image card image")
    if layout_flag:
        s.add_argument("--layout", choices=LAYOUTS, default="auto",
                       help="parts = one extra as p7 verbatim; multi = every extra as a tree inside one ext4 p7; "
                            "auto = parts for one extra, multi for two or more")
    if reach_flag:
        _add_reach_flag(s)


def _add_reach_flag(s):
    s.add_argument("--allow-unreachable", action="store_true",
                   help="accept a parts layout with an image past p7 (the machine's kernel exposes p1..p7 only; "
                        "the emulator can still run it)")


def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="directory holding codeselect (ARM binary), select.sh and optionally font.ttf")
    s.add_argument("--media-dir", help="directory holding media.json (selectmedia.py prepare) and the art/anim/sound files it names")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--default", type=int, help="images.conf default index (default 0)")
    s.add_argument("--volume", type=int, help="images.conf volume 0-100 (software mix gain; overrides media.json)")
    s.add_argument("--mixer-volume", type=int, help="images.conf mixer_volume 0-63 (the game's codec curve on selem PCM; only when set)")
    s.add_argument("--conf", help="use this images.conf verbatim instead of generating one")


def _bypass_after_build(card, plan):
    print("== validator bypass")
    return bypass_card(card, plan)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="print the layout + byte totals; writes nothing")
    _add_images(s, None)
    s = sub.add_parser("check-stock", help="regenerate a stock card's tables with this writer and byte-compare")
    s.add_argument("image")
    s = sub.add_parser("build", help="write the sparse multi card and inject the selector into p2")
    _add_images(s, "--out")
    _add_conf_flags(s)
    s.add_argument("--bypass-validation", action="store_true",
                   help="neuter Stern's game validator in EVERY games tree on the output card (+ refresh its .sidx record)")
    s.add_argument("--no-inject", action="store_true", help="only copy + tables; leave p2 stock")
    s.add_argument("--dd", action="store_true", help="copy the ranges with dd bs=16M conv=sparse instead of python")
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s.add_argument("--workdir", help="scratch directory for the p2 extract and the multi layout's tree + p7 image (default: beside --out)")
    s = sub.add_parser("inject", help="redo only the p2 injection on an existing multi card (idempotent)")
    s.add_argument("--card", required=True, help="the multi card to modify IN PLACE")
    _add_conf_flags(s)
    _add_reach_flag(s)
    s = sub.add_parser("bypass", help="apply the validator bypass to every games tree on an existing card (in place)")
    s.add_argument("--card", required=True, help="the card to modify IN PLACE")
    s.add_argument("--dry-run", action="store_true", help="report every tree's state; write nothing")
    s = sub.add_parser("verify", help="check an existing multi card against its sources")
    s.add_argument("--card", required=True)
    _add_images(s, None, reach_flag=False, layout_flag=False)
    s.add_argument("--selector-dir", help="also compare the injected files against this directory")
    s.add_argument("--media-dir", help="also compare the media files against this directory")
    s = sub.add_parser("selftest", help="synthetic end-to-end test (needs debugfs/mke2fs/e2fsck/sfdisk/fdisk)")
    s.add_argument("dir")
    s.add_argument("--selector", help="any small file to stand in for the codeselect binary")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            plan = make_plan(a.primary, a.extra, a.layout)
            print_plan(plan)
            check_reachable(plan, a.allow_unreachable)
        elif a.cmd == "check-stock":
            return 0 if check_stock(a.image) else 1
        elif a.cmd == "build":
            check_output_path(a.out, [a.primary] + a.extra + [a.conf, a.selector_dir, a.media_dir], force=a.force)
            if not a.no_inject and not a.selector_dir:
                raise Refused("build needs --selector-dir (or --no-inject)")
            plan = make_plan(a.primary, a.extra, a.layout)
            print_plan(plan)
            check_reachable(plan, a.allow_unreachable)       # before a byte is written
            if not a.extra:
                say("WARNING: no --extra given; building a one-image card")
            workdir = a.workdir or os.path.dirname(os.path.abspath(a.out))
            os.makedirs(workdir, exist_ok=True)
            conf = media = None
            if not a.no_inject:
                if a.media_dir:
                    media = plan_media(a.media_dir, len(plan.trees))
                    for name in media["files"]:
                        say("media %s: %s" % (name, media["kinds"][name]))
                    say("media: %d files, %s" % (len(media["files"]), _gb(media["total"])))
                conf = conf_for_plan(plan, a, media=media)          # generated (and validated) before the long copy
                stage_selector(a.selector_dir, tempfile.mkdtemp(prefix="mkmulticard.chk."), conf, hook_game_script(SYNTH_GAME),
                               media["files"] if media else None)
                print("== images.conf to inject\n" + conf.rstrip())
            if a.bypass_validation:
                _stern_plugins()                                  # refuse up front, not after the copy
            for x, g in zip(plan.extras, plan.extra_geoms):
                t2, s2, c2 = g.part(2)
                same = md5_range(x, s2 * SECTOR, c2 * SECTOR) == md5_range(plan.primary, plan.prims[1].src_start * SECTOR, plan.prims[1].count * SECTOR)
                say("extra %s rootfs (p2) == primary rootfs: %s" % (os.path.basename(x), "YES" if same else
                    "NO - only its games partition is carried; its rootfs changes are NOT on this card"))
            t0 = time.monotonic()
            tmp = None
            try:
                if plan.layout == "multi":
                    p7img, tmp = build_multi_partition(plan, workdir)
                    plan = plan.with_multi_src(p7img)
                build_image(plan, a.out, use_dd=a.dd)
            finally:
                if tmp:
                    shutil.rmtree(tmp, ignore_errors=True)
            say("copy + tables took %.0f s" % (time.monotonic() - t0))
            drop_stale_sidecars(a.out, keep=())
            if plan.layout == "multi":
                say("p%d md5 %s recorded in %s" % (plan.multi_part.num, write_part_sidecar(a.out, plan.multi_part.num),
                                                  sidecar_path(a.out, plan.multi_part.num)))
            if not a.no_inject:
                t1 = time.monotonic()
                inject_card(a.out, a.selector_dir, conf, workdir=workdir, media_files=media["files"] if media else None,
                            replace_media=bool(a.media_dir))
                say("injection took %.0f s" % (time.monotonic() - t1))
            else:
                # stock p2, still recorded: verify then has something to hold p2 against
                say("p2 md5 %s recorded in %s" % (write_p2_sidecar(a.out), p2_sidecar_path(a.out)))
            if a.bypass_validation:
                _bypass_after_build(a.out, plan)
            alloc = allocated_bytes(a.out)
            say("wrote %s: %d bytes apparent%s in %.0f s" % (a.out, plan.total_bytes,
                (", %s allocated" % _gb(alloc)) if alloc is not None else "", time.monotonic() - t0))
            if conf:
                print(conf.rstrip())
        elif a.cmd == "inject":
            check_output_path(a.card, [a.conf, a.selector_dir, a.media_dir], must_exist=True)
            if not a.selector_dir:
                raise Refused("inject needs --selector-dir")
            plan = plan_from_card(a.card)
            if len(plan.trees) < 2:
                say("WARNING: %s holds no extra images (p7...); injecting a one-image selector" % a.card)
            check_reachable(plan, a.allow_unreachable)       # an images.conf naming p8 is one the machine cannot honour
            media = None
            if a.media_dir:
                media = plan_media(a.media_dir, len(plan.trees))
                for name in media["files"]:
                    say("media %s: %s" % (name, media["kinds"][name]))
            conf = conf_for_plan(plan, a, existing=card_conf(a.card), media=media)
            print("== images.conf to inject\n" + conf.rstrip())
            written = inject_card(a.card, a.selector_dir, conf, workdir=os.path.dirname(os.path.abspath(a.card)),
                                  media_files=media["files"] if media else None, replace_media=bool(a.media_dir))
            say("injected into %s: %s" % (a.card, ", ".join(written)))
        elif a.cmd == "bypass":
            check_output_path(a.card, [], must_exist=True)
            plan = plan_from_card(a.card)
            print("layout: %s; trees: %s" % (plan.layout, ", ".join(plan.devices())))
            states = bypass_card(a.card, plan, dry_run=a.dry_run)
            bad = [i for i, st in states.items() if st not in ("bypassed", "absent")]
            if bad:
                print("[card] %d tree(s) NOT bypassed: %s" % (len(bad), ", ".join("image %d (%s)" % (i, states[i]) for i in bad)))
                return 1
        elif a.cmd == "verify":
            subs = multi_subdirs_on(a.card, 7)
            if subs:
                # the multi layout: p7's size and subdirectories as the build chose them, off the card
                if a.extra and len(a.extra) != len(subs):
                    raise Refused("%s holds %d trees in p7 (%s) but %d --extra were given" % (a.card, len(subs), "/".join(subs), len(a.extra)))
                plan = make_plan(a.primary, a.extra, "multi", multi_sectors=Geometry.from_file(a.card).part(7)[2],
                                 multi_subdirs=subs)
            else:
                plan = make_plan(a.primary, a.extra, "parts")
            return 0 if verify_card(a.card, plan, a.selector_dir, a.media_dir) else 1
        elif a.cmd == "selftest":
            return 0 if selftest(a.dir, a.selector) else 1
    except Refused as e:
        print("[card] error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
