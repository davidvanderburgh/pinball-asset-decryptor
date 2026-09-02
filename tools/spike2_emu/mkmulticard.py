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
an art PNG, an animated GIF, a music WAV and a confirm WAV of its own (any of them null) plus the
move/confirm sounds and the volume; only the referenced files are staged into
/usr/local/codeselect/media on p2 (flat, names ^[A-Za-z0-9._-]+$, PNG <= 1360x768, GIF <= 1.5 MB /
512x288 / 30 frames, WAV pcm_s16le 44100 Hz 1-2 ch, the whole set <= 20 MB), and images.conf gets
the image lines (image=<device>|<title>|<subtitle>|<art>|<anim>|<music>|<confirm>) and the
sound_move= / sound_confirm= / volume= / mixer_volume= / media= keys.  The line is written only as
wide as it needs to be - 3 fields with no media at all, 6 when no image names a confirm of its own -
and every narrower form stays valid.  An image's own confirm is the sound that plays when THAT image
is chosen; an empty field falls back to the menu-wide sound_confirm=.

THE TWO JSON SIDECARS (item 90, "load a finished card back into the editor").  Beside
images.conf - never inside media/, never in the media budget, never opened by the selector
(it reads images.conf and the files that names) - `build` and `inject` also stage
  build.json  {"tool", "version", "written", "layout",
               "images": [{"device", "source", "title", "subtitle", "art", "anim", "music",
                           "confirm"}],
               "timeout", "default", "volume", "mixer_volume", "sound_move", "sound_confirm"}
              'source' is the .raw each image came from - the one thing images.conf cannot
              hold and a rebuild needs.  An `inject` given no --primary/--extra reads the
              card's build.json first and carries the old sources through: an inject must
              never lose provenance.
  media.json  the manifest selectmedia.py wrote for the staged set, VERBATIM (absent when the
              card carries no media); an `inject` without --media-dir carries the card's own
              through byte for byte.
`inspect` reads both back; a card written by an older version (no sidecars) degrades to nulls
and a warning rather than an error.

GAME CODE VERSIONS (item 90, the same-version gate).  plan / build / verify / inspect all print
a VERSION table - one line per image: index, device, title directory, game code version, where
that answer came from and the node board firmware set.  `build` REFUSES a card whose images are
not the same game code unless --allow-version-mismatch is given; the refusal itself is the loud
warning, and it says what the difference costs (VERSION_COST below).  The version is read off
each image, never guessed from a file name, from up to three places that are cross-checked:
  sidx  /spk/index/<pkg>-<M_mm_p>.sidx - Stern's own package name ('turtles_pro-1_59_0.sidx'),
        all three components, and what the code updater speaks.  The AUTHORITY.  (A bare
        '<pkg>.sidx' symlink sits beside it on some cards; it names no version and is skipped.)
  ELF   the game's per-build identity record: a run of pointers to the game code, the model
        name(s), the RELEASE DATE and (on most builds) the title directory, followed by the
        version as a uint16 - high byte major, low byte minor.  MAJOR.MINOR only: turtles_le
        1.58.1 and turtles_pro 1.58.0 both hold 0x013a.  The CROSS-CHECK: located on 46 of the
        46 cards in David's library, agreeing with the .sidx name on 45 (dungeons_and_dragons_le
        1.00.0's record says 0.01 - a real disagreement, reported, never silently resolved).
  hex   the title directory's node board firmware ('*-1_33_0.hex' on TMNT 1.59, '*-1_19_0.hex'
        on 1.58).  A DIFFERENT number from the game code version, so it is reported on its own
        line and never used as one - but it is the one difference that needs a service call:
        the machine records the running build's node firmware version at every boot, so images
        with different sets can reflash the node boards on every swap.
  NVM   /data's nv/<title>/NVM would carry the machine's own record - but /data is empty on
        every one of the 49 cards checked (it is written on the machine, not by the factory),
        so nothing here depends on it.

Run under WSL/Linux (needs debugfs, e2fsck, mke2fs, sfdisk, fdisk from e2fsprogs/util-linux);
the pure-python parts (layout, MBR/EBR bytes, hook, images.conf, media checks, the version
record decoder) are tested on Windows.

  mkmulticard.py plan        --primary P --extra E [--extra E2 ...] [--layout L] [--allow-unreachable]
        print the layout, byte totals and whether it fits Stern's 16G / 32G sizes; writes nothing
  mkmulticard.py check-stock IMG
        regenerate IMG's own MBR entries + EBR chain with this writer and byte-compare them
  mkmulticard.py build       --primary P --extra E [...] --out OUT --selector-dir DIR
                             [--layout auto|parts|multi] [--media-dir DIR] [--bypass-validation]
                             [--allow-version-mismatch]
                             [--titles "T0;T1;..."] [--subtitles "S0;S1;..."] [--timeout N]
                             [--default N] [--volume V] [--mixer-volume M] [--conf FILE]
                             [--no-inject] [--dd] [--force] [--workdir DIR] [--allow-unreachable]
        write the sparse OUT (partition ranges copied, MBR entries + EBR chain regenerated; for
        the multi layout the p7 image is built first), then inject DIR/{codeselect,select.sh
        [,font.ttf]} + the media + a generated images.conf + the hooked /etc/init.d/game into
        p2, record md5 sidecars (OUT.p2.md5, and OUT.pN.md5 for every partition the bypass or
        the multi build wrote), and apply the bypass when asked
  mkmulticard.py inject      --card OUT --selector-dir DIR [--media-dir DIR] [--conf FILE]
                             [--primary P] [--extra E ...] [...]
        redo only the p2 injection on an existing multi card (idempotent: re-extract, rm+write,
        verify); without --media-dir the card's media directory, its media.json and the conf's
        media fields are carried through; --primary/--extra are RECORDED in build.json and
        nothing is read from them (without them the card's own provenance is carried through);
        the p2 sidecar is rewritten
  mkmulticard.py inspect     --card X [--json] [--media-out DIR]
        read a finished card back with no mounts and no writes: the table, the menu (images.conf),
        the provenance (build.json), the media (media.json + the files on p2) and every games
        tree's validator state.  A human table by default; --json prints ONE object on stdout
        (the GUI's 'Load card' fills its fields from it) and --media-out DIR extracts the card's
        media directory + media.json into DIR (the flat layout --media-dir reads back), so the
        menu can be previewed and re-injected without a rebuild.  Exit 0 with the report, 2 when
        the file is not a Spike 2 card or carries no selector
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

#: This tool's own version, stamped into build.json so a card says what wrote it.  Bump it when
#: the sidecar's SHAPE changes; a reader must accept an older (or missing) one.
#: 1.1 added each image's "title_dir" / "version" / "node_fw_version" (item 90's version gate).
VERSION = "1.1"

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
#: The two JSON files staged BESIDE images.conf (item 90, loading a card back).  They are not
#: media: they never go into MEDIA_DIR (where the selector scans), never count against
#: MEDIA_BUDGET and are never subject to the "only what media.json names is staged" rule.
BUILD_MANIFEST = "build.json"
SIDECAR_MANIFESTS = (BUILD_MANIFEST, MEDIA_MANIFEST)
#: 'codeselect 2.1 - Spike 2 boot-time code selector' lives in the binary's .rodata
SELECTOR_VERSION_RE = re.compile(rb"codeselect (\d+(?:\.\d+)+)")
SELECTOR_VERSION_MAX = 8 << 20                # do not read a huge file just to sniff a version
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

#: An image's own media, in the order the images.conf line carries it after the device, the title
#: and the subtitle.  `confirm` is that image's own confirm sound; an empty one falls back to the
#: menu-wide sound_confirm=.  Everything that builds or reads a media row measures itself against
#: these two, so widening the line again is one edit here plus the staging.
MEDIA_FIELDS = ("art", "anim", "music", "confirm")
MEDIA_ROW = ("",) * len(MEDIA_FIELDS)

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

# ---- game code versions (item 90: the same-version gate) -----------------------------------
#: A games tree's package manifest, '/spk/index/<pkg>-<M_mm_p>.sidx' - Stern's own name for the
#: build ('turtles_pro-1_59_0.sidx').  A card may carry a bare '<pkg>.sidx' SYMLINK beside it;
#: only the regular file names a version, so the symlink is skipped.
SIDX_NAME_RE = re.compile(r"^(?P<pkg>[A-Za-z0-9_.+-]+?)-(?P<ver>\d+_\d+_\d+)\.sidx$")
#: A node board firmware image in the title directory: 'coil4node-LPC1313-1_33_0.hex'.  Every
#: hex in one tree carries the same <M_mm_p>; that number is what the machine records per boot.
NODE_FW_RE = re.compile(r"^(?P<base>.+)-(?P<ver>\d+_\d+_\d+)\.hex$", re.I)
#: The per-build identity record in the game ELF's data segment: a run of consecutive pointers
#: to short printable strings (the game code, the model name(s), the RELEASE DATE and, on most
#: builds, the title directory) followed by the version as a uint16 - high byte major, low byte
#: minor, exactly what the firmware's own '%c%d.%02d.%d' banner prints.  There is no third
#: (patch) component in this record: turtles_le 1.58.1 and turtles_pro 1.58.0 both hold 0x013a.
#: Verified against all 46 cards in David's library (see the module docstring's VERSIONS note).
IDENT_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
IDENT_DATE_RE = re.compile((r"^" + IDENT_MONTH + r"[a-z]*\.?\s{1,2}\d{1,2},?\s\d{4}$").encode(), re.I)
IDENT_MAX_STR = 80                            # a longer "string" is not one of this record's
IDENT_MAX_VER = 0x6400                        # major <= 99...
IDENT_MAX_MINOR = 99                          # ...and minor <= 99, so 0x4cf0 (a pointer) is out
IDENT_MIN_RUN = 2                             # a lone pointer is a table entry, not this record
#: The record sat in the LAST PT_LOAD on all 46 cards measured.  A build that put it elsewhere
#: falls back to scanning the whole file - but only for a game ELF small enough that the scan
#: costs seconds; the biggest in the library is rush_le's 190 MB, and a tool must not hang.
IDENT_FULL_SCAN_MAX = 32 << 20


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
    """images.conf text.  v2 (item 90 media): `media` is one (art, anim, music, confirm) per image
    (names relative to the media dir, '' = none; a 3-tuple without the confirm is accepted).  The
    line is written only as wide as it needs to be: 7 fields when any image names a confirm of its
    own, 6 when some other media is set, else the 3-field form every older selector reads.  The
    global keys follow."""
    devices = list(devices)
    if not devices:
        raise Refused("images.conf: no images")
    if len(devices) > MAX_IMAGES:
        raise Refused("images.conf: %d images; the selector takes at most %d" % (len(devices), MAX_IMAGES))
    for d in devices:
        parse_device(d)
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    media = [tuple(m) if m else MEDIA_ROW for m in (media or [])]
    # a caller from before the per-image confirm passes 3-tuples; widen them rather than refuse
    media = [m + ("",) * (len(MEDIA_ROW) - len(m)) if len(m) < len(MEDIA_ROW) else m
             for m in media]
    if len(titles) > len(devices) or len(subtitles) > len(devices) or len(media) > len(devices):
        raise Refused("images.conf: %d titles / %d subtitles / %d media rows for %d images"
                      % (len(titles), len(subtitles), len(media), len(devices)))
    titles += ["image %d" % i for i in range(len(titles), len(devices))]
    subtitles += [""] * (len(devices) - len(subtitles))
    media += [MEDIA_ROW] * (len(devices) - len(media))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    rows = []
    for m in media:
        if len(m) != len(MEDIA_ROW):
            raise Refused("images.conf: a media row is (art, anim, music, confirm), got %r" % (m,))
        rows.append(tuple(_media_name_ok(x or "", what) for x, what in zip(m, MEDIA_FIELDS)))
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
    # the seventh field is written only when some image has a confirm sound of its own, so a menu
    # where every image uses the menu-wide sound reads exactly as it did before this existed
    width = 4 if any(r[3] for r in rows) else (3 if any_media else 0)
    out = ["# images.conf - codeselect, the boot-time code selector (item 90); written by mkmulticard.py",
           "# image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
           "# media names are relative to media= (default /usr/local/codeselect/media); <confirm> is that",
           "# image's own confirm sound and an empty one falls back to sound_confirm=; default = highlight",
           "# when no last choice; timeout = seconds before the highlighted image boots by itself (0 = for ever)"]
    for d, t, s, r in zip(devices, titles, subtitles, rows):
        out.append("image=%s|%s|%s" % (d, t, s) + "".join("|" + x for x in r[:width]))
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
    """-> {'images': [(device, title, subtitle)], 'media': [(art, anim, music, confirm)] (aligned,
    '' = none), 'default': int, 'timeout': int, 'font': str|None, 'sound_move': str|None,
    'sound_confirm': str|None, 'volume': int|None, 'mixer_volume': int|None, 'media_dir': str|None}.
    3-field and 6-field image lines are valid; more than 7 fields, a bad device, a media name with
    '|' ':' or '/', or more than 16 images is refused.  Unknown keys are ignored (the file may
    grow)."""
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
            if len(f) > 3 + len(MEDIA_ROW):
                raise Refused("images.conf: image line has %d fields (at most %d): %r"
                              % (len(f), 3 + len(MEDIA_ROW), raw))
            f += [""] * (3 + len(MEDIA_ROW) - len(f))
            parse_device(f[0])
            conf["images"].append((f[0], f[1], f[2]))
            conf["media"].append(tuple(_media_name_ok(x, what)
                                       for x, what in zip(f[3:3 + len(MEDIA_ROW)], MEDIA_FIELDS)))
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
    {"images": [{"art": "art0.png", "anim": "anim0.gif"|null, "music": "music0.wav"|null,
                 "confirm": "confirm0.wav"|null}, ...],
     "sound_move": "move.wav"|null, "sound_confirm": "confirm.wav"|null, "volume": 50}
    ("mixer_volume" optional; "confirm" is that image's OWN confirm sound, null = the menu-wide
    one, and the "*_source" keys selectmedia also writes are provenance this tool ignores)."""
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
    file -> {'rows': [(art, anim, music, confirm)], 'sound_move', 'sound_confirm', 'volume', 'mixer_volume',
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
                     take(e.get("music"), "wav", "images[%d].music" % i),
                     take(e.get("confirm"), "wav", "images[%d].confirm" % i)))
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


def check_library_path(path):
    """Refuse ANY output - a file or a directory - inside David's card library."""
    if not path:
        raise Refused("no output path")
    n = _norm(path)
    for pre in FORBIDDEN_OUTPUT_PREFIXES:
        pn = _norm(pre)
        if n == pn or n.startswith(pn + "/"):
            raise Refused("refusing to write under %s (David's card library): %s" % (pre, path))
    return path


def check_output_path(path, inputs, force=False, must_exist=False):
    """Refuse an output the tool must never write.  Raises Refused with the reason."""
    n = _norm(check_library_path(path))
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
def stage_selector(selector_dir, stage, conf_text, hooked_game, media_files=None, manifests=None):
    """Copy the selector files into `stage` with their FINAL modes (debugfs write copies the source
    mode).  `media_files` ({name: source path}, from plan_media) go to stage/media/<name> and
    MEDIA_DIR/<name> on the card, 0644.  `manifests` ({name: text or bytes}, from
    selector_manifests) are the JSON sidecars and land BESIDE images.conf - in SELECT_DIR, never
    in MEDIA_DIR, so the selector's media scan never sees them.  -> [(staged path, card path, mode)]."""
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
    for name, text in (manifests or {}).items():
        if name not in SIDECAR_MANIFESTS:
            raise Refused("%r is not one of the selector's JSON sidecars %r" % (name, list(SIDECAR_MANIFESTS)))
        dst = os.path.join(stage, name)
        with open(dst, "wb") as f:                       # bytes: a carried-through media.json is verbatim
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        os.chmod(dst, 0o644)
        items.append((dst, SELECT_DIR + "/" + name, 0o644))
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


def inject_into_p2(p2_image, selector_dir, conf_text, stage_dir, media_files=None, replace_media=False,
                   manifests=None):
    """Modify an extracted rootfs image in place: /usr/local/codeselect/* (+ media/, + the JSON
    sidecars `manifests` names) and the hooked game script.  Idempotent (existing files are
    removed first; an existing media directory is
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
    items = stage_selector(selector_dir, stage_dir, conf_text, hooked, media_files, manifests)
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


def inject_card(card, selector_dir, conf_text, workdir=None, media_files=None, replace_media=False,
                manifests=None):
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
        written = inject_into_p2(p2, selector_dir, conf_text, stage, media_files, replace_media, manifests)
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


# ============================================================================= the JSON sidecars
def build_manifest(plan, conf, sources=None, existing=None, written=None, versions=None):
    """build.json: what the card's menu says, plus WHERE each image came from and WHAT GAME CODE
    it was - the provenance a reload needs and images.conf cannot hold.  Pure.

    plan      the card's Plan (for the layout), or None
    conf      the images.conf about to be written, PARSED (parse_images_conf)
    sources   the build's --primary/--extra in image order; an empty or missing entry falls
              back to `existing`
    existing  the build.json already on the card - its sources AND its recorded versions are
              carried through BY DEVICE, so an inject never loses provenance
    versions  :func:`plan_identities`' records in image order (title dir + game code version):
              what the card was BUILT from.  `inspect` re-reads the live truth off the card, so
              this is a record of the build, not an oracle
    """
    prev = {}
    for im in (existing or {}).get("images") or []:
        if isinstance(im, dict) and im.get("device"):
            prev[im["device"]] = im
    vers = {v["device"]: v for v in (versions or []) if v.get("device")}
    sources = list(sources or [])
    rows = []
    for i, (dev, title, sub) in enumerate(conf["images"]):
        art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else MEDIA_ROW
        given = sources[i] if i < len(sources) else None
        # only a freshly given path is absolutised; a carried one is already absolute and may
        # be spelled for another OS (a /mnt/d path read on Windows must not be mangled)
        old = prev.get(dev) or {}
        src = os.path.abspath(given) if given else old.get("source")
        v = vers.get(dev) or {}
        rows.append(collections.OrderedDict([
            ("device", dev), ("source", src or None), ("title", title), ("subtitle", sub),
            ("art", art or None), ("anim", anim or None), ("music", music or None),
            ("confirm", confirm or None),
            ("title_dir", v.get("title") or old.get("title_dir")),
            ("version", v.get("version") or old.get("version")),
            ("node_fw_version", v.get("node_fw_version") or old.get("node_fw_version"))]))
    return collections.OrderedDict([
        ("tool", "mkmulticard"),
        ("version", VERSION),
        ("written", written or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ("layout", getattr(plan, "layout", None)),
        ("images", rows),
        ("timeout", conf["timeout"]),
        ("default", conf["default"]),
        ("volume", conf["volume"]),
        ("mixer_volume", conf["mixer_volume"]),
        ("sound_move", conf["sound_move"]),
        ("sound_confirm", conf["sound_confirm"])])


def selector_manifests(plan, conf_text, media_dir=None, sources=None, existing_build=None,
                       existing_media=None, written=None, versions=None):
    """The JSON sidecars to stage beside images.conf -> OrderedDict {name: text or bytes}.
    build.json is always written (from `conf_text` + `sources`, carrying `existing_build`'s
    sources through); media.json is --media-dir's file verbatim when one was given, else the
    card's own `existing_media` bytes carried through unchanged, else absent."""
    out = collections.OrderedDict()
    out[BUILD_MANIFEST] = json.dumps(
        build_manifest(plan, parse_images_conf(conf_text), sources, existing_build, written, versions),
        indent=1) + "\n"
    if media_dir:
        with open(os.path.join(media_dir, MEDIA_MANIFEST), "rb") as f:
            out[MEDIA_MANIFEST] = f.read()
    elif existing_media:
        out[MEDIA_MANIFEST] = existing_media
    return out


def parse_manifest(raw, what, warnings=None):
    """A staged JSON sidecar's bytes -> dict, or None.  A malformed one is a warning (a card
    written by a broken run must still load), or a Refusal when no warning list is offered."""
    if raw is None:
        return None
    try:
        obj = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        why = None if isinstance(obj, dict) else "top level is %s, not an object" % type(obj).__name__
    except ValueError as exc:                            # 'as' names die with the except block
        why = str(exc)
    if why is None:
        return obj
    msg = "%s on the card is not a JSON object (%s); ignored" % (what, why)
    if warnings is None:
        raise Refused(msg)
    warnings.append(msg)
    return None


# ============================================================================= reading a card back
def select_ref(card):
    """The debugfs reference for the card's p2 - where the selector, its images.conf and the two
    JSON sidecars live.  The same read path verify uses."""
    geom = Geometry.from_file(card)
    t, st, _cnt = geom.part(2)
    if t != 0x83:
        raise Refused("%s: p2 is type 0x%02x, not Linux (not a Spike 2 card)" % (card, t))
    return fs_ref(card, st * SECTOR)


def read_select_file(ref, name):
    """SELECT_DIR/<name> as bytes, or None when the card does not carry it."""
    path = SELECT_DIR + "/" + name
    if not debugfs_exists(ref, path):
        return None
    return debugfs_cat(ref, path)


def card_conf(card, ref=None):
    """The images.conf already on a card's p2, parsed, or None."""
    raw = read_select_file(ref or select_ref(card), "images.conf")
    return None if raw is None else parse_images_conf(raw)


def multi_subdirs_on(card, part_num=7):
    """The imgN subdirectories at the root of partition `part_num` (the multi layout's marker),
    numerically ordered, or [] when that partition is a plain games tree / not there / not ext4.
    Pure python (the ext4 reader), so a card is recognised on Windows too."""
    try:
        _vp, _sx, ext4, _adj = _stern_plugins()
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
    """(valpatch, sidx, ext4, adjustments) - the app's own Stern modules, imported when first
    needed.  `adjustments` is here for its PT_LOAD parser alone: the game ELF's identity record
    is located exactly the way that module locates the adjustment table, so the two share one
    program-header reader rather than growing a second copy."""
    try:
        from pinball_decryptor.plugins.stern import valpatch, sidx, ext4, adjustments
    except ImportError:
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        try:
            from pinball_decryptor.plugins.stern import valpatch, sidx, ext4, adjustments
        except ImportError as e:
            raise Refused("the validator bypass needs the app's pinball_decryptor package "
                          "(looked beside %s): %s" % (REPO_ROOT, e))
    return valpatch, sidx, ext4, adjustments


def bypass_state(elf):
    """'bypassed' (the entry already holds bx lr), 'armed' (a live validator was located),
    'absent' (this build carries none) or 'unlocated' (it carries one we cannot pin)."""
    valpatch, _s, _e, _adj = _stern_plugins()
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
    _v, _s, ext4, _adj = _stern_plugins()
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
    _v, _s, ext4, _adj = _stern_plugins()
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
    valpatch, sidx, _e, _adj = _stern_plugins()
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
    rec = read_tree(card, part, subdir)
    return rec["bypass"], rec["title"], rec["game_path"]


# ============================================================ game code versions (item 90)
def version_text(ver):
    """Stern's '1_59_0' (a .sidx / .hex name) -> '1.59.0'."""
    return ver.replace("_", ".") if ver else None


def game_identity(elf, title_dir=None):
    """The game ELF's per-build identity record -> {"version", "raw", "strings", "date",
    "name", "title_dir", "offset"} or None.  Reads bytes only; nothing is written.

    HOW IT IS LOCATED (no fixed address, the same shape as :mod:`plugins.stern.adjustments`):
    the record is a MAXIMAL run of consecutive 4-byte words that are pointers to short printable
    C strings, immediately followed by the uint16 version.  The run always holds either the
    build's RELEASE DATE or the title directory's name (usually both), which is what tells this
    record apart from the many other pointer tables in .data.  Everything is derived from the
    ELF's own program headers, so a build that moved the record is found anyway.
    """
    _v, _s, _e, adjustments = _stern_plugins()
    segs = adjustments._load_segments(elf)
    if not segs:
        return None
    want = (title_dir or "").encode()

    def v2o(v):
        for off, va, sz in segs:
            if va <= v < va + sz:
                return off + (v - va)
        return None

    def cstr(v):
        o = v2o(v)
        if o is None:
            return None
        end = elf.find(b"\x00", o, o + IDENT_MAX_STR)
        if end <= o:
            return None
        s = elf[o:end]
        return None if any(c < 0x20 or c > 0x7E for c in s) else s

    # the record lives in the last PT_LOAD (the writable data segment) on every card measured;
    # a build that put it elsewhere falls back to the whole file rather than going unread
    scopes = [(segs[-1][0], segs[-1][0] + segs[-1][2])] if len(segs) > 1 else []
    if not scopes or len(elf) <= IDENT_FULL_SCAN_MAX:
        scopes.append((0, len(elf)))
    best = None
    for lo, hi in scopes:
        run, run_at, o = [], lo, (lo + 3) & ~3
        while o + 4 <= hi:
            s = cstr(struct.unpack_from("<I", elf, o)[0])
            if s is not None:
                if not run:
                    run_at = o
                run.append(s)
                o += 4
                continue
            if len(run) >= IDENT_MIN_RUN and o + 2 <= len(elf):
                v = struct.unpack_from("<H", elf, o)[0]
                dates = [x for x in run if IDENT_DATE_RE.match(x)]
                named = bool(want) and want in run
                if 0 < v < IDENT_MAX_VER and (v & 0xFF) <= IDENT_MAX_MINOR and (dates or named):
                    score = (100 if named else 0) + (50 if dates else 0) + min(len(run), 8)
                    if best is None or score > best[0]:
                        best = (score, run_at, list(run), v, dates)
            run, run_at = [], o
            o += 4
        if best is not None:
            break
    if best is None:
        return None
    _score, at, run, v, dates = best
    texts = [x.decode("ascii") for x in run]
    # the model name is the string just BEFORE the release date ('TMNT PRO', 'GODZILLA LE');
    # with no date in the run (star_wars_le) it is the one before the title directory
    stop = run.index(dates[-1]) if dates else (len(run) - 1 if want and run[-1] == want else len(run))
    return collections.OrderedDict([
        ("version", "%d.%02d" % (v >> 8, v & 0xFF)), ("raw", v), ("offset", at),
        ("name", texts[stop - 1] if stop else texts[-1]),
        ("date", dates[-1].decode("ascii") if dates else None),
        ("title_dir", texts[-1] if want and run[-1] == want else None),
        ("strings", texts)])


def tree_dir_inode(reader, root_ino, *names):
    """The inode number of `root/names...` when every step is a directory, else None."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = root_ino
    for name in names:
        ents = _dir_entries(reader, ino)
        if name not in ents:
            return None
        ino = ents[name][0]
        if (reader.read_inode(ino)["mode"] & ext4.S_IFMT) != ext4.S_IFDIR:
            return None
    return ino


def tree_packages(reader, root_ino, title=None):
    """[(file name, package, '1.59.0')] for every REGULAR /spk/index/<pkg>-<M_mm_p>.sidx in the
    tree - Stern's own name for the build.  The bare '<pkg>.sidx' symlink beside it names no
    version and is skipped, and so is anything that is not a .sidx.  A tree carrying more than
    one puts the package named after the TITLE DIRECTORY first: that is the game's own."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = tree_dir_inode(reader, root_ino, "spk", "index")
    out = []
    for name, (child, _t) in (sorted(_dir_entries(reader, ino).items()) if ino else []):
        m = SIDX_NAME_RE.match(name)
        if not m:
            continue
        try:
            node = reader.read_inode(child)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) == ext4.S_IFREG:
            out.append((name, m.group("pkg"), version_text(m.group("ver"))))
    return sorted(out, key=lambda r: r[1] != title)


def tree_node_firmware(reader, root_ino, title_dir):
    """(sorted .hex names, the one version they share or None) of the title directory's NODE
    BOARD firmware.  This is the set the machine flashes into the node boards, and it is
    recorded per boot: two images whose sets differ can reflash the boards on every swap."""
    _v, _s, ext4, _adj = _stern_plugins()
    ino = tree_dir_inode(reader, root_ino, title_dir) if title_dir else None
    names, vers = [], set()
    for name, (child, _t) in (sorted(_dir_entries(reader, ino).items()) if ino else []):
        m = NODE_FW_RE.match(name)
        if not m:
            continue
        try:
            node = reader.read_inode(child)
        except Exception:
            continue
        if (node["mode"] & ext4.S_IFMT) == ext4.S_IFREG:
            names.append(name)
            vers.add(version_text(m.group("ver")))
    return sorted(names), (vers.pop() if len(vers) == 1 else None)


def read_tree(card, part, subdir=None):
    """Everything one games tree says about ITSELF, read-only and with no mounts: the title
    directory, the game code version, where each answer came from, the node board firmware set
    and the validator state.  -> an OrderedDict; :func:`tree_state` is the two-line view of it.

    THE SOURCES, most reliable first (a disagreement between the first two is reported, never
    silently resolved - it is exactly the kind of thing that means a card was hand-assembled):
      sidx  /spk/index/<pkg>-<M_mm_p>.sidx, Stern's own package name for the build.  It carries
            all three components (1.59.0) and is what the code updater and the menu speak.
      elf   the game ELF's build-identity record (:func:`game_identity`): major.minor only.
      hex   the title directory's node firmware version - a different number (1.33.0 on TMNT
            1.59), never the game code version, so it is reported but never used as one.
    """
    _v, _s, ext4, _adj = _stern_plugins()
    with open(card, "rb") as f:
        r = ext4.Ext4Reader(f, part.start * SECTOR, part.count * SECTOR)
        root = tree_root_inode(r, subdir)
        title, gpath, _gino, gnode = tree_game(r, root)
        elf = r.read_file_bytes(gnode)                    # one read: the version AND the state
        pkgs = tree_packages(r, root, title)
        fw, fwver = tree_node_firmware(r, root, title)
    ident = game_identity(elf, title)
    notes = []
    sidx_name, package, sidx_ver = pkgs[0] if pkgs else (None, None, None)
    if len(pkgs) > 1:
        notes.append("this tree carries %d .sidx packages (%s); %s is used, as the one named "
                     "after the title directory"
                     % (len(pkgs), ", ".join(n for (n, _p, _v) in pkgs), sidx_name))
    elf_ver = ident["version"] if ident else None
    # compare the NUMBERS, not the text: the ELF holds major.minor as two bytes and the package
    # name spells them however Stern spelled them ('1_00_0' would never prefix-match '0.01')
    if ident and _version_pair(sidx_ver) not in (None, (ident["raw"] >> 8, ident["raw"] & 0xFF)):
        notes.append("the package name says %s but the game ELF's own build record says %s - "
                     "these two DISAGREE, and the package name is the one the machine installs by"
                     % (sidx_ver, elf_ver))
    if sidx_ver and elf_ver:
        source = "spk index + game ELF"
    elif sidx_ver:
        source = "spk index"
        notes.append("the game ELF carries no build-identity record this tool can locate; the "
                     "version is the .sidx package name alone")
    elif elf_ver:
        source = "game ELF"
        notes.append("this tree has no /spk/index/<pkg>-<M_mm_p>.sidx; the version is the game "
                     "ELF's build record alone, which carries no third component")
    else:
        source = None
        notes.append("neither a .sidx package name nor a game ELF build record could be read: "
                     "this tree's game code version is UNKNOWN")
    try:
        state = bypass_state(elf)
    except Exception as e:                                # a report never dies on one odd ELF
        state = "error"
        notes.append("the validator locator could not read %s (%s: %s)"
                     % (gpath, type(e).__name__, e))
    return collections.OrderedDict([
        ("device", device_name(part.num, subdir)), ("title", title), ("game_path", gpath),
        ("version", sidx_ver or elf_ver), ("version_source", source),
        ("package", package), ("sidx", sidx_name), ("sidx_version", sidx_ver),
        ("elf_version", elf_ver), ("elf_name", ident["name"] if ident else None),
        ("elf_date", ident["date"] if ident else None),
        ("node_fw", fw), ("node_fw_version", fwver), ("node_fw_digest", _fw_digest(fw)),
        ("bypass", state), ("notes", notes)])


def _version_pair(text):
    """'1.59.0' -> (1, 59), the two components the game ELF's record carries; None when the
    text is missing or not a version."""
    try:
        a, b = text.split(".")[:2]
        return int(a), int(b)
    except (AttributeError, ValueError):
        return None


def _fw_digest(names):
    """A short stable digest of a node firmware SET, so a JSON reader can compare two images
    without carrying twenty file names (the names are carried too; this is the cheap key)."""
    return hashlib.md5("\n".join(sorted(names)).encode("utf-8")).hexdigest()[:12] if names else None


def source_part(path, num=3):
    """The Part of one SOURCE image's games partition - what `plan` and `build` must read
    versions from, since the card does not exist yet."""
    t, st, cnt = Geometry.from_file(path).part(num)
    return Part(num, t, st, cnt, path, st, None)


def plan_identities(plan, progress=say):
    """One :func:`read_tree` record per image, read from the SOURCE images - so `plan` and
    `build` can refuse before a byte is written.  A tree that cannot be read becomes a record
    with version None and the reason in its notes; nothing here raises."""
    out = []
    for i, (dev, path) in enumerate(zip(plan.devices(), [plan.primary] + list(plan.extras))):
        rec = collections.OrderedDict([("index", i), ("device", dev), ("source", path)])
        try:
            rec.update(read_tree(path, source_part(path)))
        except Exception as e:                            # a version read never breaks a build
            rec.update(_unread_tree(dev, "%s could not be read (%s: %s)"
                                    % (path, type(e).__name__, e)))
        rec["device"] = dev                               # the card's device, not the source's
        out.append(rec)
        if progress:
            progress("image %d %s: %s %s (%s)" % (i, dev, rec["title"], rec["version"], rec["version_source"]))
    return out


def card_identities(card, plan=None, progress=None):
    """One :func:`read_tree` record per games tree ON the card (what verify and inspect report)."""
    out = []
    for i, part, sub in card_trees(card, plan):
        dev = device_name(part.num, sub)
        rec = collections.OrderedDict([("index", i), ("device", dev), ("source", card)])
        try:
            rec.update(read_tree(card, part, sub))
        except Exception as e:                            # a version read never breaks a verify
            rec.update(_unread_tree(dev, "this tree could not be read (%s: %s)"
                                    % (type(e).__name__, e)))
        rec["device"] = dev
        out.append(rec)
        if progress:
            progress("image %d %s: %s %s (%s)" % (i, dev, rec["title"], rec["version"], rec["version_source"]))
    return out


def _unread_tree(dev, why):
    """The record of a tree that could not be read: everything unknown, the reason kept."""
    return collections.OrderedDict([
        ("device", dev), ("title", None), ("game_path", None), ("version", None),
        ("version_source", None), ("package", None), ("sidx", None), ("sidx_version", None),
        ("elf_version", None), ("elf_name", None), ("elf_date", None),
        ("node_fw", []), ("node_fw_version", None), ("node_fw_digest", None),
        ("bypass", "error"), ("notes", [why])])


def _distinct(recs, key):
    """The distinct non-None values of `key`, in image order."""
    seen = []
    for r in recs:
        v = r.get(key)
        if v is not None and v not in seen:
            seen.append(v)
    return seen


def version_findings(recs):
    """What the version table found -> OrderedDict of PLAIN-ENGLISH sentences (or None).

    title_mismatch     the images are not even the same game - the larger warning
    version_mismatch   the umbrella 'these images are not the same game code' sentence: it
                       names the title difference when there is one, so a reader that shows
                       only this key never misses the louder problem
    node_fw_mismatch   the images ship different NODE BOARD firmware sets - the one failure
                       here that needs service, and it can happen with matching versions
    unknown_version    a tree whose version could not be read at all
    version_only       the version sentence WITHOUT the title one folded in, so the refusal can
                       put the two on their own lines; readers want version_mismatch
    """
    # only trees that were actually READ can disagree; one that could not be read is its own
    # finding (unknown_version) and never fabricates a mismatch
    known = [r for r in recs if r.get("title") is not None]
    titles, versions = _distinct(known, "title"), _distinct(known, "version")
    known = [dict(r, node_fw_label=_fw_label(r)) for r in known]
    fws = _distinct(known, "node_fw_label")
    unread = [r for r in recs if r.get("version") is None]
    title_bad = version_bad = fw_bad = unknown = None
    if len(titles) > 1:
        title_bad = ("this card mixes DIFFERENT TITLES (%s): %s. Nothing carries between them - "
                     "settings, audits and high scores are stored per title - and each title "
                     "wants its own node boards, coils and switch table."
                     % (", ".join(titles), _image_list(known, "title")))
    if len(versions) > 1:
        version_bad = ("the images do not all run the same GAME CODE VERSION (%s): %s."
                       % (", ".join(versions), _image_list(known, "version")))
    version_only = version_bad
    if title_bad:
        version_bad = title_bad if not version_bad else title_bad + " " + version_bad
    if len(fws) > 1:
        fw_bad = ("the images ship DIFFERENT NODE BOARD FIRMWARE: %s. %s The machine records the "
                  "running build's node firmware version at every boot, so swapping between "
                  "these images can reflash the node boards on every swap."
                  % (_image_list(known, "node_fw_label"), _fw_diff(known)))
    if unread:
        unknown = ("%d image(s) did not say what game code they run: %s."
                   % (len(unread), "; ".join("image %d (%s)" % (r["index"], "; ".join(r["notes"]))
                                             for r in unread)))
    return collections.OrderedDict([("title_mismatch", title_bad), ("version_mismatch", version_bad),
                                    ("node_fw_mismatch", fw_bad), ("unknown_version", unknown),
                                    ("version_only", version_only)])


def _fw_label(rec):
    """What to CALL one image's node firmware set: its shared version, 'no node firmware' when
    the title directory carries none, or the set's digest when the files disagree among
    themselves - never 'unknown', which would read as 'we did not look'."""
    if rec.get("node_fw_version"):
        return rec["node_fw_version"]
    return ("mixed set " + rec["node_fw_digest"]) if rec.get("node_fw") else "no node firmware"


def _image_list(recs, key, fallback=None):
    """'image 0 = 1.59.0, image 1 = 1.58.0' for a findings sentence."""
    return ", ".join("image %d = %s" % (r["index"], r.get(key) or (r.get(fallback) if fallback else None) or "unknown")
                     for r in recs)


def _fw_diff(recs, limit=6):
    """'images 0, 1 carry a.hex, b.hex; image 2 carries c.hex' - WHICH node firmware files
    differ, so the reader is told what is about to be reflashed rather than that something is.
    Images that ship the SAME set are named together: on a three-image card two of them usually
    agree, and calling either one's files 'only its own' would be a lie."""
    common = set.intersection(*[set(r["node_fw"]) for r in recs]) if recs else set()
    groups = collections.OrderedDict()
    for r in recs:
        groups.setdefault(tuple(sorted(r["node_fw"])), []).append(r["index"])
    parts = []
    for names, idx in groups.items():
        only = sorted(set(names) - common)
        if not only:
            continue
        parts.append("image%s %s carr%s %s%s"
                     % ("s" if len(idx) > 1 else "", ", ".join(str(i) for i in idx),
                        "y" if len(idx) > 1 else "ies", ", ".join(only[:limit]),
                        " and %d more" % (len(only) - limit) if len(only) > limit else ""))
    return ("; ".join(parts) + ".") if parts else "(the file names match; only their versions differ.)"


def print_version_table(recs, findings=None):
    """The VERSION table plan / build / verify / inspect all print - one line per image."""
    print("== game code versions")
    print("%-3s %-22s %-24s %-9s %-22s %s" % ("idx", "device", "title", "version", "read from", "node firmware"))
    for r in recs:
        fw = "%s (%d hex)" % (r["node_fw_version"] or "mixed", len(r["node_fw"])) if r["node_fw"] else "none"
        print("%-3d %-22s %-24s %-9s %-22s %s"
              % (r["index"], r["device"], r["title"] or "?", r["version"] or "UNKNOWN",
                 r["version_source"] or "-", fw))
        for note in r["notes"]:
            print("    NOTE image %d: %s" % (r["index"], note))
    found = version_findings(recs) if findings is None else findings
    for key in ("version_mismatch", "node_fw_mismatch", "unknown_version"):
        if found.get(key):                    # title_mismatch is folded into version_mismatch
            print("WARNING: %s" % found[key])


#: What a version difference actually costs, in the operator's own terms.  Measured on a TMNT
#: 1.59 -> 1.58 -> 1.59 round trip (memory: reference_spike2_settings_are_caption_keyed): the
#: board NVRAM keys every setting by the SHA1 of its MENU CAPTION, so 11 of 11 settings survived
#: the trip even though 202 of the 228 shared captions were renumbered between the builds.
VERSION_COST = """\
Two builds of the SAME title do share a machine's settings, audits and scores: those live in the
node board's NVRAM keyed by the SHA1 of each setting's MENU CAPTION, not by its number, so a
caption both builds spell the same way carries over untouched (11 of 11 measured across a TMNT
1.59 -> 1.58 -> 1.59 round trip, with 202 of the 228 shared captions renumbered in between).

What a version difference DOES cost is narrower, and all of it is real:
  * a setting only ONE build has falls back to that build's compiled default whenever you boot
    the other one (43 settings of TMNT 1.59 and 13 of 1.58 on that measured pair);
  * a setting Stern RENAMED between the builds REVERTS - the new caption hashes to a slot that
    has never been written (3 on that pair);
  * the store keeps only THREE generations, so two boots of the other build erase a
    build-exclusive value for good.

And the part that needs a service call rather than a settings pass: each image ships its OWN
NODE BOARD FIRMWARE, and the machine records the running build's node firmware version at every
boot - so a card whose images disagree can REFLASH the node boards on every single swap.

THE FIX is to give every image on the card the same game code version.  Same title AND same
version costs nothing at all - a re-skin of a build, paired with that same build, differs only
in its artwork and shares every setting the machine holds."""


def report_versions(recs, allow=False):
    """Print the VERSION table and apply the gate -> the findings; raises Refused when the images
    are not the same game code and `allow` is not set.  The table always comes out FIRST, and its
    per-finding WARNING lines are left out when the refusal is about to say the same thing at
    length - the reader should meet each sentence once."""
    try:
        found = check_versions(recs, allow)
    except Refused:
        print_version_table(recs, {"unknown_version": version_findings(recs)["unknown_version"]})
        raise
    print_version_table(recs, found)
    return found


def check_versions(recs, allow=False, flag="--allow-version-mismatch"):
    """Refuse a card whose images are not the same game code, unless `allow`.  A refusal you can
    override IS the loud warning, so the message says what it costs and how to fix it.  ->
    the findings (so the caller can report them); raises Refused when it will not proceed."""
    findings = version_findings(recs)
    # one paragraph each, loudest first: a different TITLE, then a different VERSION, then a
    # different NODE FIRMWARE set (which can be the only difference)
    bad = [findings[k] for k in ("title_mismatch", "version_only", "node_fw_mismatch") if findings[k]]
    if not bad or allow:
        return findings
    rows = "\n".join(
        "  image %-2d %-22s %-22s game code %-9s node firmware %s"
        % (r["index"], r["device"], r["title"] or "?", r["version"] or "UNKNOWN",
           _fw_label(r))
        for r in recs)
    raise Refused("%s\n\n%s\n\n%s\n\nIf you know all of that and want this card anyway, pass %s."
                  % ("\n\n".join(bad), rows, VERSION_COST, flag))


def bypass_card(card, plan=None, dry_run=False):
    """Apply the validator bypass to every games tree on `card`, rewrite the sidecar of every
    partition written into, print one line per tree.  -> {index: state after}."""
    _v, _s, ext4, _adj = _stern_plugins()
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
        print("    JSON sidecars: %s" % ", ".join(
            "%s %s" % (n, ("%d bytes" % dict((e[4], e[5]) for e in ents)[n]) if n in names else "absent")
            for n in SIDECAR_MANIFESTS))
        conf = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
        devs = [d for (d, _t, _s) in conf["images"]]
        check("images.conf devices = %r" % (plan.devices(),), devs == plan.devices(), "got %r" % (devs,))
        for (d, t, s), m in zip(conf["images"], conf["media"]):
            print("    image %s | %s | %s%s"
                  % (d, t, s, "".join(" | %s" % x for x in m) if any(m) else ""))
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
            # the JSON sidecars live beside images.conf; the selector scans this directory
            check("no JSON sidecar inside %s" % MEDIA_DIR, not (set(SIDECAR_MANIFESTS) & set(on_card)),
                  "found %r" % sorted(set(SIDECAR_MANIFESTS) & set(on_card)))
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
    # every games tree's game code version + node board firmware, read off the CARD (item 90):
    # the same table plan and build print, so a finished card can be held to what it claims
    recs = card_identities(card, plan)
    for r in recs:
        print("image %d %s bypass_status: %s (%s)"
              % (r["index"], r["device"], r["bypass"], r["game_path"] or "; ".join(r["notes"])))
    print_version_table(recs)
    # a mismatch is REPORTED here, never a FAIL: a card built with --allow-version-mismatch is a
    # card its owner chose, and verify's job is to say what is on it - build's is to refuse
    alloc = allocated_bytes(card)
    if alloc is not None:
        print("allocated %s of %s apparent (sparse)" % (_gb(alloc), _gb(os.path.getsize(card))))
    print("VERIFY %s %s" % (card, "PASS" if ok else "FAIL"))
    return ok


# ============================================================================= inspect
def extract_card_media(ref, out_dir, names, media_json=None):
    """Write the card's media directory (and its media.json when it carries one) into `out_dir`,
    flat - the exact shape selectmedia.py writes and --media-dir reads back, so a loaded card can
    be previewed and re-injected without a rebuild.  -> (names written, names skipped).

    Nothing in `out_dir` is ever deleted (it may be a media set of your own), so give it a
    per-card scratch directory: a file left there by an earlier load is still there afterwards,
    and --media-dir would stage what media.json names, not what the card carries."""
    check_library_path(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    written, skipped = [], []
    for name in names:
        if not MEDIA_NAME_RE.match(name):
            skipped.append(name)                 # never came from this tool; never write it out
            continue
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(debugfs_cat(ref, MEDIA_DIR + "/" + name))
        written.append(name)
    if media_json is not None:
        with open(os.path.join(out_dir, MEDIA_MANIFEST), "wb") as f:
            f.write(media_json)
        written.append(MEDIA_MANIFEST)
    return written, skipped


def inspect_card(card, media_out=None):
    """Read a finished multi card back: everything a loader needs to fill an editor's fields,
    with no mounts and no writes.  -> the report dict (contract B of "load a card back").

    The menu comes from images.conf, the provenance from build.json, the art/animation SPECS
    from media.json, the file list from the media directory and each image's validator state
    from its games tree.  A card written by an older version carries no JSON sidecars: those
    fields degrade to null with a warning - never an error.  Refused only when the file is not
    a Spike 2 card or carries no selector.  `media_out` also extracts the media directory.
    """
    need_tools("debugfs")
    warnings = []
    path = os.path.abspath(card)
    size = os.path.getsize(path)
    geom = Geometry.from_file(path)
    ref = select_ref(path)
    if not debugfs_exists(ref, SELECT_DIR):
        raise Refused("%s: no %s on its p2 - no boot selector is installed (a stock card, or one "
                      "built without --selector-dir)" % (path, SELECT_DIR))
    ents = [e for e in debugfs_ls(ref, SELECT_DIR) if e[4] not in (".", "..")]
    sizes = {e[4]: e[5] for e in ents}
    isdir = {e[4]: statmod.S_ISDIR(e[1]) for e in ents}
    raw_conf = read_select_file(ref, "images.conf")
    if raw_conf is None:
        raise Refused("%s: %s is on the card but holds no images.conf - there is no menu to read"
                      % (path, SELECT_DIR))
    conf = parse_images_conf(raw_conf)
    build = parse_manifest(read_select_file(ref, BUILD_MANIFEST), BUILD_MANIFEST, warnings)
    media_json = read_select_file(ref, MEDIA_MANIFEST)
    media_man = parse_manifest(media_json, MEDIA_MANIFEST, warnings)
    if build is None:
        warnings.append("no %s on this card (it predates the sidecar, or another tool wrote it): "
                        "the images' source .raw paths are unknown - re-inject with --primary/"
                        "--extra to record them" % BUILD_MANIFEST)
    if media_man is None and any(any(m) for m in conf["media"]):
        warnings.append("no %s on this card: the art/animation SPECS are unknown (the staged file "
                        "names are still in images.conf)" % MEDIA_MANIFEST)
    plan = None
    try:
        plan = plan_from_card(path)
    except Refused as e:
        warnings.append("the partition table does not read as a multi card (%s); the images below "
                        "come from images.conf alone" % e)
    trees = {device_name(p.num, s): (p, s) for (p, s) in (plan.trees if plan else [])}
    prev = {im["device"]: im for im in ((build or {}).get("images") or [])
            if isinstance(im, dict) and im.get("device")}
    mrows = (media_man or {}).get("images") or []
    images, treerecs = [], []
    for i, (dev, title, subtitle) in enumerate(conf["images"]):
        art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else MEDIA_ROW
        b = prev.get(dev) or {}
        m = mrows[i] if i < len(mrows) and isinstance(mrows[i], dict) else {}
        src = b.get("source") or None
        exists = bool(src) and os.path.isfile(src)
        if src and not exists:
            warnings.append("image %d: its source %s is not on this machine - the menu can still "
                            "be edited and re-injected, only a rebuild needs it" % (i, src))
        if dev in trees:
            p, s = trees[dev]
            try:
                tree = read_tree(path, p, s)
            except Exception as e:                        # ...nor an inspect
                tree = _unread_tree(dev, "its games tree could not be read (%s: %s)"
                                    % (type(e).__name__, e))
        else:
            tree = _unread_tree(dev, "images.conf names %s but the card carries no such games "
                                     "tree" % dev)
        for note in tree["notes"]:
            warnings.append("image %d (%s): %s" % (i, dev, note))
        tree["index"] = i
        treerecs.append(tree)
        title_dir = tree["title"]
        state = None if tree["bypass"] == "error" else ("none" if tree["bypass"] == "absent" else tree["bypass"])
        images.append(collections.OrderedDict([
            ("index", i), ("device", dev), ("title", title), ("subtitle", subtitle),
            ("art", art or None), ("anim", anim or None), ("music", music or None),
            # this image's OWN confirm sound; null = it plays the menu-wide one
            ("confirm", confirm or None), ("confirm_source", m.get("confirm_source")),
            ("art_source", m.get("art_source")), ("anim_source", m.get("anim_source")),
            ("source", src), ("source_exists", exists),
            ("title_dir", title_dir), ("bypass", state),
            # what game code this image actually is, read off the card (item 90's version gate);
            # 'built_version' is what build.json recorded when the card was written
            ("version", tree.get("version")), ("version_source", tree.get("version_source")),
            ("sidx", tree.get("sidx")), ("sidx_version", tree.get("sidx_version")),
            ("elf_version", tree.get("elf_version")), ("elf_name", tree.get("elf_name")),
            ("elf_date", tree.get("elf_date")),
            ("node_fw", tree.get("node_fw") or []), ("node_fw_version", tree.get("node_fw_version")),
            ("node_fw_digest", tree.get("node_fw_digest")),
            ("built_version", b.get("version")), ("built_title_dir", b.get("title_dir"))]))
    findings = version_findings(treerecs)
    media = []
    if isdir.get("media"):
        for _ino, _mode, _uid, _gid, name, msize in debugfs_ls(ref, MEDIA_DIR):
            if name not in (".", ".."):
                media.append(collections.OrderedDict([("name", name), ("bytes", msize)]))
        media.sort(key=lambda x: x["name"])
    have = {x["name"] for x in media}
    missing = [n for n in conf_media_names(conf) if n not in have]
    if missing:
        warnings.append("images.conf names %d media file(s) the card does not carry: %s"
                        % (len(missing), ", ".join(missing)))
    sel = collections.OrderedDict([("bytes", sizes.get("codeselect")), ("version", None)])
    if "codeselect" not in sizes:
        warnings.append("no codeselect binary in %s: this card will not show a menu" % SELECT_DIR)
    elif sizes["codeselect"] <= SELECTOR_VERSION_MAX:
        m = SELECTOR_VERSION_RE.search(read_select_file(ref, "codeselect") or b"")
        if m:
            sel["version"] = m.group(1).decode("ascii", "replace")
    out = None
    if media_out:
        written, skipped = extract_card_media(ref, media_out, [x["name"] for x in media], media_json)
        out = collections.OrderedDict([("dir", os.path.abspath(media_out)), ("files", len(written))])
        if skipped:
            warnings.append("%d media file(s) with names this tool never writes were left on the "
                            "card: %s" % (len(skipped), ", ".join(skipped)))
        if media_json is None and os.path.isfile(os.path.join(media_out, MEDIA_MANIFEST)):
            warnings.append("%s already held a %s and this card carries none - it is an EARLIER "
                            "load's, not this card's; use a fresh directory before re-injecting "
                            "from it" % (media_out, MEDIA_MANIFEST))
    parts = [collections.OrderedDict([("num", n), ("type", t), ("start", st), ("count", cnt),
                                      ("bytes", cnt * SECTOR)])
             for (n, t, st, cnt) in ([(x[0], x[1], x[2], x[3]) for x in geom.prim]
                                     + [(5 + i, t, st, cnt) for i, (_e, t, st, cnt) in enumerate(geom.logical)])]
    return collections.OrderedDict([
        ("card", path), ("size", size),
        ("layout", plan.layout if plan else ("multi" if any(":" in d for (d, _t, _s) in conf["images"]) else "parts")),
        ("partitions", parts), ("images", images),
        ("timeout", conf["timeout"]), ("default", conf["default"]),
        ("volume", conf["volume"]), ("mixer_volume", conf["mixer_volume"]),
        ("sound_move", conf["sound_move"]), ("sound_confirm", conf["sound_confirm"]),
        ("font", conf["font"]), ("media_dir", conf["media_dir"]),
        ("media", media), ("media_out", out),
        ("has_media_json", media_json is not None), ("has_build_json", build is not None),
        ("build", None if build is None else collections.OrderedDict(
            [(k, build.get(k)) for k in ("tool", "version", "written")])),
        # the version gate's answers, ready-made sentences so a GUI shows them without
        # re-deriving anything (null when the images agree)
        ("title_mismatch", findings["title_mismatch"]),
        ("version_mismatch", findings["version_mismatch"]),
        ("node_fw_mismatch", findings["node_fw_mismatch"]),
        ("unknown_version", findings["unknown_version"]),
        ("selector", sel), ("warnings", warnings)])


def print_inspect(rep):
    """The human table `inspect` prints without --json."""
    print("card       %s" % rep["card"])
    print("size       %s (%d bytes)" % (_gb(rep["size"]), rep["size"]))
    print("layout     %s" % rep["layout"])
    print("table      %s" % ", ".join("p%d %s %s" % (p["num"], "0x%02x" % p["type"], _gb(p["bytes"]))
                                      for p in rep["partitions"]))
    sel = rep["selector"]
    print("selector   codeselect %s, %s; build.json %s, media.json %s"
          % (sel["version"] or "(version unknown)",
             "%d bytes" % sel["bytes"] if sel["bytes"] else "MISSING",
             "yes" if rep["has_build_json"] else "no", "yes" if rep["has_media_json"] else "no"))
    if rep.get("build"):
        print("built      %s by %s %s" % (rep["build"].get("written"), rep["build"].get("tool"),
                                          rep["build"].get("version")))
    print("menu       default=%s timeout=%s volume=%s mixer_volume=%s sound_move=%s sound_confirm=%s font=%s"
          % (rep["default"], rep["timeout"], rep["volume"], rep["mixer_volume"],
             rep["sound_move"], rep["sound_confirm"], rep["font"]))
    for im in rep["images"]:
        print("image %d    %s  %r / %r" % (im["index"], im["device"], im["title"], im["subtitle"]))
        print("           art=%s anim=%s music=%s confirm=%s"
              % (im["art"], im["anim"], im["music"],
                 im["confirm"] or "(the menu's)"))
        if im["art_source"] or im["anim_source"] or im["confirm_source"]:
            print("           art_source=%s anim_source=%s confirm_source=%s"
                  % (im["art_source"], im["anim_source"], im["confirm_source"]))
        print("           source=%s%s" % (im["source"], "" if im["source"] is None else
                                          (" (on this machine)" if im["source_exists"] else " (MISSING here)")))
        print("           title dir=%s  validator=%s" % (im["title_dir"], im["bypass"]))
        print("           game code=%s (%s; sidx=%s, ELF=%s %s)  node firmware=%s (%d hex)"
              % (im["version"] or "UNKNOWN", im["version_source"] or "-", im["sidx_version"],
                 im["elf_version"], im["elf_date"], im["node_fw_version"] or "-", len(im["node_fw"])))
        if im["built_version"] and im["built_version"] != im["version"]:
            print("           BUILT FROM %s per build.json - the tree on this card says %s"
                  % (im["built_version"], im["version"]))
    for key in ("version_mismatch", "node_fw_mismatch", "unknown_version"):
        if rep.get(key):
            print("VERSION WARNING: %s" % rep[key])
    print("media      %d file(s), %d KB of the %d KB budget"
          % (len(rep["media"]), sum(m["bytes"] for m in rep["media"]) >> 10, MEDIA_BUDGET >> 10))
    for m in rep["media"]:
        print("           %-28s %d bytes" % (m["name"], m["bytes"]))
    if rep.get("media_out"):
        print("extracted  %d file(s) into %s" % (rep["media_out"]["files"], rep["media_out"]["dir"]))
    for w in rep["warnings"]:
        print("WARNING: %s" % w)


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


def make_synthetic_card(path, tag, seed, with_fs=False, title=None, version=None, node_fw=None):
    """A stock-shaped card, 10 MiB: p1@8192x2048 p2@10240x2048 p3@12288x2046 ext@14336 p5@16384x2046
    EBR2@18430 p6@18432x2046.  with_fs=False: random payloads (pure python, for the tests);
    with_fs=True: real ext4 with a stand-in game script in p2 and a title dir + game link in p3.

    `title` names the games tree's title directory (default '<tag>_title').  `version` ('1_59_0')
    and `node_fw` ('1_33_0') give that tree a real GAME CODE VERSION to read: the /spk/index
    manifest is named '<title>-<version>.sidx', the title directory gets '<node>-<fw>.hex' node
    firmware files, and its `game` becomes a :func:`synth_game_elf` carrying the same version.
    Without them the tree keeps the older shape (an unversioned .sidx, a text `game`) - which is
    itself worth a card: it is what "this tree's version is UNKNOWN" looks like."""
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
                td = title or ("%s_title" % tag)
                files = {"/%s/game" % td: (synth_game_elf(td, version_text(version) or "1.59.0",
                                                          model="%s MODEL" % tag)
                                           if version else ("%s p3 game\n" % tag).encode()),
                         "/%s/conagent" % td: ("%s p3 conagent\n" % tag).encode(),
                         "/%s/data/marker" % td: ("%s p3 data\n" % tag).encode(),
                         "/spk/index/%s%s.sidx" % (td, "-" + version if version else ""): b"not a manifest\n"}
                for node in ("pinnode-LPC1313", "coil4node-LPC1313", "lcdnode-LPC1113_302"):
                    if node_fw:
                        files["/%s/%s-%s.hex" % (td, node, node_fw)] = (":00000001FF\n").encode()
                _mkext(p, cnt * SECTOR // 1024, files,
                       links=[("/game", "%s/game" % td), ("/conagent", "%s/conagent" % td),
                              ("/data", "%s/data" % td)])
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


def synth_game_elf(title_dir="turtles_pro", version="1.59.0", model="TMNT PRO", code="TMT",
                   date="AUGUST 25, 2019", extra_names=(), with_title=True, hi=0):
    """A tiny 32-bit little-endian ARM ELF carrying ONE build-identity record, exactly the shape
    :func:`game_identity` reads off a real card: a .rodata segment of C strings and a .data
    segment holding [code][model...][date][title dir] pointers followed by the uint16 version.

    with_title=False builds the godzilla shape (no title-directory pointer in the record); `hi`
    puts junk in the version word's high half (the james_bond shape, where the version really is
    a uint16 and the word above it is another field).  Pure python - no card, no WSL."""
    major, minor = (int(x) for x in version.split(".")[:2])
    names = [code, model] + list(extra_names) + [date] + ([title_dir] if with_title else [])
    ro, offs = bytearray(), []
    for s in names:
        offs.append(len(ro))
        ro += s.encode("ascii") + b"\x00"
        ro += b"\x00" * (-len(ro) % 4)
    ehsize, phentsize, shentsize = 0x34, 32, 40
    text = b"\x00" * 16                                # empty enough that no locator matches it
    text_off = ehsize + 2 * phentsize
    ro_off = text_off + len(text)
    ro_va = 0x8000 + ro_off
    data = bytearray(b"\x00" * 16)                     # a run of non-pointers before the record
    for o in offs:
        data += struct.pack("<I", ro_va + o)
    data += struct.pack("<HH", (major << 8) | minor, hi)
    data += b"\x00" * 32
    data_off = ro_off + len(ro)
    data_va = 0x100000 + data_off
    shstr = b"\x00.text\x00.shstrtab\x00"
    shstr_off = data_off + len(data)
    sh_off = shstr_off + len(shstr)
    elf = bytearray(b"\x7fELF\x01\x01\x01" + b"\x00" * 9)
    elf += struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, ro_va, ehsize, sh_off, 0,
                       ehsize, phentsize, 2, shentsize, 3, 2)
    for off, va, blob in ((ro_off, ro_va, ro), (data_off, data_va, data)):
        elf += struct.pack("<IIIIIIII", 1, off, va, va, len(blob), len(blob), 6, 4)
    elf += text + ro + data + shstr
    elf += struct.pack("<10I", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)                       # SHT_NULL
    elf += struct.pack("<10I", 1, 1, 6, 0x8000, text_off, len(text), 0, 0, 4, 0)    # .text
    elf += struct.pack("<10I", 7, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)       # .shstrtab
    return bytes(elf)


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
        # image 1 gets a confirm sound of its OWN, so the 7-field line, the staging of
        # confirm1.wav and the fallback for the images without one are all exercised
        synth_wav(os.path.join(d, "confirm1.wav"))
        imgs[1]["anim"], imgs[1]["music"] = "anim1.gif", "music1.wav"
        imgs[1]["confirm"] = "confirm1.wav"
    synth_wav(os.path.join(d, "move.wav"), ch=1)
    synth_wav(os.path.join(d, "confirm.wav"))
    synth_wav(os.path.join(d, "wrong_rate.wav"), rate=48000)                # unreferenced, must NOT be staged
    with open(os.path.join(d, MEDIA_MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"images": imgs, "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 40}, f, indent=1)
    return d


class Checks:
    """``ok &= <expression>`` that SAYS WHICH EXPRESSION FAILED.

    The selftest is one long chain of `ok &=`, and a False in the middle of
    it used to print nothing at all: the run just ended in FAIL, and the
    only way to find the check was to swap older copies of this file in and
    bisect.  That happened, once, and one line of output would have saved
    it - so this stands in for the plain bool and names the line."""

    def __init__(self):
        self.ok = True
        self.failed = []

    def __iand__(self, value):
        if not value:
            # the CALLER's frame, file and line together: a name taken from
            # this module and a line taken from the caller would point at a
            # line that is not the check
            frame = sys._getframe(1)
            line = frame.f_lineno
            print("    CHECK FAILED at %s:%d"
                  % (os.path.basename(frame.f_code.co_filename), line))
            self.failed.append(line)
            self.ok = False
        return self

    def __bool__(self):
        return self.ok


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
    ok = Checks()
    ok &= plan.unreachable_note() == "p8 unreachable on the machine"
    try:
        check_reachable(plan)
        print("SELFTEST: check_reachable accepted a p8 image")
        ok &= False
    except Refused as e:
        print("refused without --allow-unreachable, as it should be: %s" % str(e).splitlines()[0])
    check_reachable(plan, allow=True)
    print("== build (parts)")
    build_image(plan, out)
    ms = plan_media(media, 3)
    ok &= list(ms["files"]) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "confirm1.wav",
                                "art2.png", "move.wav", "confirm.wav"]
    ok &= ms["rows"][1][3] == "confirm1.wav" and ms["rows"][0][3] == ""
    ok &= "wrong_rate.wav" not in ms["files"] and ms["volume"] == 40
    conf = render_images_conf(plan.devices(), ["A stock", "B", "C"], ["synthetic", "", "third"], 1, 7, None,
                              ms["rows"], ms["sound_move"], ms["sound_confirm"], ms["volume"])
    mans = selector_manifests(plan, conf, media, [A, B, C])
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"], manifests=mans)
    print("== verify")
    ok &= verify_card(out, plan, sel, media)
    print("== inject again with the media directory present (idempotence)")
    inject_card(out, sel, conf, workdir=d, media_files=ms["files"], manifests=mans)
    ok &= verify_card(out, plan, sel, media)
    print("== inject without media: the media directory, media.json and the conf's media fields are carried through")
    ref0 = select_ref(out)
    old_build = parse_manifest(read_select_file(ref0, BUILD_MANIFEST), BUILD_MANIFEST)
    old_media = read_select_file(ref0, MEDIA_MANIFEST)
    carried = conf_for_plan(plan, argparse.Namespace(), existing=card_conf(out, ref0))
    inject_card(out, sel, carried, workdir=d,
                manifests=selector_manifests(plan, carried, None, None, old_build, old_media))
    ok &= verify_card(out, plan, sel, media)
    ref0 = select_ref(out)
    now = parse_manifest(read_select_file(ref0, BUILD_MANIFEST), BUILD_MANIFEST)
    ok &= [im["source"] for im in now["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= read_select_file(ref0, MEDIA_MANIFEST) == old_media
    print("provenance carried through an inject with no sources: %s"
          % ", ".join(os.path.basename(im["source"] or "?") for im in now["images"]))
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
    ok &= back["media"] == [("art0.png", "", "", ""),
                            ("art1.png", "anim1.gif", "music1.wav", "confirm1.wav"),
                            ("art2.png", "", "", "")]
    # the seventh field survived the write and the read back: image 1 plays its OWN sound
    ok &= "|art1.png|anim1.gif|music1.wav|confirm1.wav" in conf
    ok &= back["default"] == 1 and back["timeout"] == 7 and back["volume"] == 40
    ok &= (back["sound_move"], back["sound_confirm"], back["media_dir"]) == ("move.wav", "confirm.wav", MEDIA_DIR)
    names = sorted(e[4] for e in debugfs_ls(ref, MEDIA_DIR) if e[4] not in (".", ".."))
    ok &= names == sorted(ms["files"])
    print("media on the card: %s" % ", ".join(names))
    print("== inspect (the card read back) + --media-out")
    mout = os.path.join(d, "loaded media")
    rep = inspect_card(out, mout)
    print_inspect(rep)
    ok &= rep["has_build_json"] and rep["has_media_json"] and rep["layout"] == "parts"
    ok &= [im["device"] for im in rep["images"]] == plan.devices()
    ok &= [im["title"] for im in rep["images"]] == ["A stock", "B", "C"]
    ok &= [im["source"] for im in rep["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= [im["source_exists"] for im in rep["images"]] == [True, True, True]
    ok &= (rep["default"], rep["timeout"], rep["volume"]) == (1, 7, 40)
    ok &= sorted(m["name"] for m in rep["media"]) == names
    ok &= sorted(os.listdir(mout)) == sorted(names + [MEDIA_MANIFEST])
    # the extracted directory is a --media-dir again: the round trip a GUI reload needs
    ok &= list(plan_media(mout, 3)["files"]) == list(ms["files"])
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
            ok &= False
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
    inject_card(out2, sel, conf2, workdir=d, manifests=selector_manifests(plan2, conf2, None, [A, B, C]))
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
    print("== inspect (multi): the subdirectory devices and the provenance of each tree")
    rep2 = inspect_card(out2)
    print_inspect(rep2)
    ok &= rep2["layout"] == "multi" and [im["device"] for im in rep2["images"]] == plan2.devices()
    ok &= [im["source"] for im in rep2["images"]] == [os.path.abspath(x) for x in (A, B, C)]
    ok &= [im["title_dir"] for im in rep2["images"]] == ["A_title", "B_title", "C_title"]
    ok &= rep2["has_build_json"] and not rep2["has_media_json"] and rep2["media"] == []
    ok &= all(im["version"] is None for im in rep2["images"])          # no versioned .sidx here
    ok &= rep2["title_mismatch"] and "DIFFERENT TITLES" in rep2["title_mismatch"]
    ok &= rep2["unknown_version"] and "did not say what game code" in rep2["unknown_version"]
    print("SELFTEST part 2 (multi layout)", "PASS" if ok else "FAIL")

    # ------------------------------------------------- part 3: the same-version gate (item 90)
    print("== the game code version gate")
    V = [make_synthetic_card(os.path.join(d, "V%d.img" % i), "V%d" % i, 0x0D0D0D00 + i, with_fs=True,
                             title="turtles_pro", version=v, node_fw=fw)
         for i, (v, fw) in enumerate([("1_59_0", "1_33_0"), ("1_59_0", "1_33_0"), ("1_58_0", "1_19_0")])]
    same = plan_identities(make_plan(V[0], [V[1]], "parts"), progress=None)
    print_version_table(same)
    ok &= [r["version"] for r in same] == ["1.59.0", "1.59.0"]
    ok &= [r["version_source"] for r in same] == ["spk index + game ELF"] * 2
    ok &= [r["node_fw_version"] for r in same] == ["1.33.0", "1.33.0"]
    ok &= all(v is None for v in check_versions(same).values())        # same version: SILENT
    diff = plan_identities(make_plan(V[0], [V[2]], "parts"), progress=None)
    print_version_table(diff)
    try:
        check_versions(diff)
        print("SELFTEST: a mismatched pair was accepted")
        ok &= False
    except Refused as e:
        ok &= "GAME CODE VERSION" in str(e) and "NODE BOARD FIRMWARE" in str(e)
        ok &= "--allow-version-mismatch" in str(e) and "1.59.0" in str(e) and "1.58.0" in str(e)
        print("refused, as it should be:\n%s" % e)
    ok &= check_versions(diff, allow=True)["version_mismatch"] is not None
    out3 = os.path.join(d, "versions.img")
    args = ["build", "--primary", V[0], "--extra", V[2], "--out", out3, "--selector-dir", sel,
            "--layout", "parts", "--force"]
    ok &= main(args) == 2 and not os.path.exists(out3)         # refused BEFORE a byte was written
    print("build refused and wrote nothing: %s" % (not os.path.exists(out3)))
    ok &= main(args + ["--allow-version-mismatch"]) == 0 and os.path.isfile(out3)
    rep3 = inspect_card(out3)
    print_inspect(rep3)
    ok &= [im["version"] for im in rep3["images"]] == ["1.59.0", "1.58.0"]
    ok &= [im["built_version"] for im in rep3["images"]] == ["1.59.0", "1.58.0"]
    ok &= [im["node_fw_version"] for im in rep3["images"]] == ["1.33.0", "1.19.0"]
    ok &= rep3["version_mismatch"] and rep3["node_fw_mismatch"] and not rep3["title_mismatch"]
    print("SELFTEST", "PASS" if ok else "FAIL")
    return bool(ok)


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
    s.add_argument("--allow-version-mismatch", action="store_true",
                   help="build a card whose images are NOT the same game code - a different game code version, "
                        "a different title, or a different node board firmware set. Read the refusal first: it "
                        "says what each of those costs")
    s.add_argument("--no-inject", action="store_true", help="only copy + tables; leave p2 stock")
    s.add_argument("--dd", action="store_true", help="copy the ranges with dd bs=16M conv=sparse instead of python")
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s.add_argument("--workdir", help="scratch directory for the p2 extract and the multi layout's tree + p7 image (default: beside --out)")
    s = sub.add_parser("inject", help="redo only the p2 injection on an existing multi card (idempotent)")
    s.add_argument("--card", required=True, help="the multi card to modify IN PLACE")
    _add_conf_flags(s)
    s.add_argument("--primary", help="RECORD this path as image 0's source in build.json; nothing is read "
                                     "from it (without it the card's own build.json is carried through)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG",
                   help="RECORD this path as the next image's source in build.json (repeatable); nothing is read from it")
    _add_reach_flag(s)
    s = sub.add_parser("inspect", help="read a finished card back: table, menu, provenance, media, validator state")
    s.add_argument("--card", required=True, help="the card to read (READ-ONLY; nothing is written to it)")
    s.add_argument("--json", action="store_true", dest="as_json",
                   help="print ONE JSON object on stdout instead of the table (the GUI's 'Load card' reads it)")
    s.add_argument("--media-out", help="also extract the card's media directory + media.json into this directory "
                                       "(give it a per-card scratch directory: nothing there is deleted)")
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
            recs = plan_identities(plan, progress=None)
            try:                                 # plan writes nothing, so it reports and does
                report_versions(recs)            # not refuse - but it says what build will do
            except Refused as e:
                print("\n== build will REFUSE this card\n%s" % e)
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
            versions = plan_identities(plan)                 # read off the SOURCE images...
            report_versions(versions, a.allow_version_mismatch)  # ...and refuse before --out exists
            workdir = a.workdir or os.path.dirname(os.path.abspath(a.out))
            os.makedirs(workdir, exist_ok=True)
            conf = media = manifests = None
            if not a.no_inject:
                if a.media_dir:
                    media = plan_media(a.media_dir, len(plan.trees))
                    for name in media["files"]:
                        say("media %s: %s" % (name, media["kinds"][name]))
                    say("media: %d files, %s" % (len(media["files"]), _gb(media["total"])))
                conf = conf_for_plan(plan, a, media=media)          # generated (and validated) before the long copy
                manifests = selector_manifests(plan, conf, a.media_dir, [a.primary] + list(a.extra),
                                               versions=versions)
                stage_selector(a.selector_dir, tempfile.mkdtemp(prefix="mkmulticard.chk."), conf, hook_game_script(SYNTH_GAME),
                               media["files"] if media else None, manifests)
                print("== images.conf to inject\n" + conf.rstrip())
                print("== %s\n%s" % (BUILD_MANIFEST, manifests[BUILD_MANIFEST].rstrip()))
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
                            replace_media=bool(a.media_dir), manifests=manifests)
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
            check_output_path(a.card, [a.conf, a.selector_dir, a.media_dir, a.primary] + list(a.extra), must_exist=True)
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
            # read the card's own sidecars BEFORE touching it: an inject that is given no source
            # paths carries the old provenance through, and one without --media-dir carries the
            # card's media.json through byte for byte
            ref = select_ref(a.card)
            warns = []
            old_build = parse_manifest(read_select_file(ref, BUILD_MANIFEST), BUILD_MANIFEST, warns)
            old_media = None if a.media_dir else read_select_file(ref, MEDIA_MANIFEST)
            for w in warns:
                say("WARNING: " + w)
            conf = conf_for_plan(plan, a, existing=card_conf(a.card, ref), media=media)
            sources = [a.primary] + list(a.extra) if (a.primary or a.extra) else None
            manifests = selector_manifests(plan, conf, a.media_dir, sources, old_build, old_media)
            say("%s: %s; %s: %s" % (
                BUILD_MANIFEST,
                "sources given" if sources else ("sources carried through from the card" if old_build
                                                 else "no sources known (pass --primary/--extra to record them)"),
                MEDIA_MANIFEST,
                "from --media-dir" if a.media_dir else ("carried through (%d bytes)" % len(old_media) if old_media
                                                        else "absent")))
            print("== images.conf to inject\n" + conf.rstrip())
            print("== %s\n%s" % (BUILD_MANIFEST, manifests[BUILD_MANIFEST].rstrip()))
            written = inject_card(a.card, a.selector_dir, conf, workdir=os.path.dirname(os.path.abspath(a.card)),
                                  media_files=media["files"] if media else None, replace_media=bool(a.media_dir),
                                  manifests=manifests)
            say("injected into %s: %s" % (a.card, ", ".join(written)))
        elif a.cmd == "inspect":
            if not os.path.isfile(a.card):
                raise Refused("%s does not exist" % a.card)
            rep = inspect_card(a.card, a.media_out)
            if a.as_json:
                json.dump(rep, sys.stdout, indent=1)
                sys.stdout.write("\n")
            else:
                print_inspect(rep)
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
