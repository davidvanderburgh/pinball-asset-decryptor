#!/usr/bin/env python3
"""mkmulticard.py - build a multi-image Stern Spike 2 SD card for the boot-time code selector (item 90).

One card, several complete game images.  p1 (FAT boot) and p2 (ext4 rootfs) are the
PRIMARY image's, p3 is the primary's games partition verbatim, p4 is the extended
partition grown to the end of the card, p5 (/data) and p6 (/dump) are the primary's,
and p7, p8, ... are each EXTRA image's games partition verbatim.  The selector
(/usr/local/codeselect/) and its one guarded hook line in /etc/init.d/game are
injected into p2 with `debugfs -w`; nothing else on the card is touched.

Run under WSL/Linux (needs debugfs, e2fsck, sfdisk, fdisk from e2fsprogs/util-linux);
the pure-python parts (layout, MBR/EBR bytes, hook, images.conf) are tested on Windows.

  mkmulticard.py plan        --primary P --extra E [--extra E2 ...]
        print the layout, byte totals and whether it fits Stern's 16G / 32G sizes; writes nothing
  mkmulticard.py check-stock IMG
        regenerate IMG's own MBR entries + EBR chain with this writer and byte-compare them
  mkmulticard.py build       --primary P --extra E [...] --out OUT --selector-dir DIR
                             [--titles "T0;T1;..."] [--subtitles "S0;S1;..."] [--timeout N]
                             [--default N] [--conf FILE] [--no-inject] [--dd] [--force]
        write the sparse OUT (partition ranges copied, MBR entries + EBR chain regenerated),
        then inject DIR/{codeselect,select.sh[,font.ttf]} + a generated images.conf + the
        hooked /etc/init.d/game into p2
  mkmulticard.py inject      --card OUT --selector-dir DIR [--conf FILE] [--titles ...] [...]
        redo only the p2 injection on an existing multi card (idempotent: re-extract, rm+write, verify)
  mkmulticard.py verify      --card OUT --primary P --extra E [...] [--selector-dir DIR]
        table parse-back (own parser + sfdisk -d), md5 of every copied range vs its source
        (p2 reported as 'patched' with the /etc/init.d/game diff and the selector file list),
        e2fsck -fn of every ext4 partition, root listing of every games partition, PASS/FAIL
  mkmulticard.py selftest DIR
        synthetic 10 MiB cards -> 3-image card with injection -> every check above, in DIR

Every OUTPUT path is explicit.  The tool refuses to overwrite an existing output without
--force, refuses any output under /mnt/d/Pinball/images (David's card library) and refuses
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
  Two 8G images = 28755968 sectors = 14,723,055,616 B (fits a 16G card); three need a 32G card.
"""
import argparse
import collections
import difflib
import hashlib
import os
import re
import shutil
import stat as statmod
import struct
import subprocess
import sys
import tempfile
import time

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
    images [Part] the games partitions in selector index order: p3, p7, p8, ...
    """

    def __init__(self, primary_geom, extra_geoms, primary=None, extras=None):
        P = primary_geom
        if P.ext is None or len(P.logical) < 1:
            raise Refused("%s: no extended partition / logical chain" % (primary or "primary"))
        for n in (1, 2, 3):
            P.part(n)
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
        for x, xp in zip(self.extra_geoms, self.extras):
            t, xs, xc = x.part(3)
            ebr = prev_end + 1
            st = align_up(ebr + 1)
            p = Part(num, t, st, xc, xp, xs, ebr)
            self.logs.append(p)
            self.images.append(p)
            num += 1
            prev_end = st + xc - 1
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
        return [DEVICE_FMT % p.num for p in self.images]

    def fits(self):
        return collections.OrderedDict((k, v - self.total_bytes) for k, v in STERN_SIZES.items())


def make_plan(primary, extras):
    return Plan(Geometry.from_file(primary), [Geometry.from_file(x) for x in extras], primary, list(extras))


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
    print("%-4s %-4s %-12s %-12s %-12s %-16s %s" % ("part", "type", "start", "count", "end", "bytes", "source"))
    rows = [(p.num, p.ptype, p.start, p.count, "%s@%d" % (os.path.basename(p.src or "primary"), p.src_start))
            for p in plan.prims]
    rows.append((4, 0x0F, plan.ext_base, plan.ext_count, "(extended container)"))
    rows += [(p.num, p.ptype, p.start, p.count, "%s@%d" % (os.path.basename(p.src or "image"), p.src_start))
             for p in plan.logs]
    for n, t, st, cnt, src in rows:
        print("p%-3d 0x%02x %-12d %-12d %-12d %-16d %s" % (n, t, st, cnt, st + cnt - 1, cnt * SECTOR, src))
    for p in plan.logs:
        print("  EBR for p%d at LBA %d" % (p.num, p.ebr))
    print("images: " + ", ".join("%d=%s" % (i, DEVICE_FMT % p.num) for i, p in enumerate(plan.images)))
    print("image: %d sectors = %d bytes (%s)" % (plan.total, plan.total_bytes, _gb(plan.total_bytes)))
    for k, spare in plan.fits().items():
        print("  fits Stern %-3s image size %d: %s (spare %d)" % (k, STERN_SIZES[k], "YES" if spare >= 0 else "NO", spare))


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
def render_images_conf(devices, titles=None, subtitles=None, default=0, timeout=15, font=None):
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    if len(titles) > len(devices) or len(subtitles) > len(devices):
        raise Refused("images.conf: %d titles / %d subtitles for %d images" % (len(titles), len(subtitles), len(devices)))
    titles += ["image %d" % i for i in range(len(titles), len(devices))]
    subtitles += [""] * (len(devices) - len(subtitles))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    if not (0 <= int(default) < len(devices)):
        raise Refused("images.conf: default=%s is not an image index (0..%d)" % (default, len(devices) - 1))
    if int(timeout) < 0:
        raise Refused("images.conf: timeout must be >= 0")
    out = ["# images.conf - codeselect, the boot-time code selector (item 90); written by mkmulticard.py",
           "# image=<device>|<title>|<subtitle>   index = order (0-based); default = highlight when no last choice;",
           "# timeout = seconds before the highlighted image boots by itself (0 = wait for ever)"]
    for d, t, s in zip(devices, titles, subtitles):
        out.append("image=%s|%s|%s" % (d, t, s))
    out.append("default=%d" % int(default))
    out.append("timeout=%d" % int(timeout))
    if font:
        out.append("font=%s" % font)
    return "\n".join(out) + "\n"


def parse_images_conf(text):
    """-> {'images': [(device, title, subtitle)], 'default': int, 'timeout': int, 'font': str|None}"""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    conf = {"images": [], "default": 0, "timeout": 15, "font": None}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _sep, val = line.partition("=")
        key = key.strip()
        if key == "image":
            f = val.split("|")
            conf["images"].append((f[0].strip(), f[1].strip() if len(f) > 1 else "", f[2].strip() if len(f) > 2 else ""))
        elif key in ("default", "timeout"):
            try:
                conf[key] = int(val.strip())
            except ValueError:
                raise Refused("images.conf: bad %s=%r" % (key, val))
        elif key == "font":
            conf["font"] = val.strip() or None
    return conf


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
    return os.path.normpath(os.path.abspath(p)).replace("\\", "/").lower()


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


# ============================================================================= injection
def stage_selector(selector_dir, stage, conf_text, hooked_game):
    """Copy the selector files into `stage` with their FINAL modes (debugfs write copies the source
    mode).  -> [(staged path, card path, mode)]."""
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
    game = os.path.join(stage, "game")
    with open(game, "wb") as f:
        f.write(hooked_game.encode("utf-8"))
    os.chmod(game, 0o755)
    items.append((game, GAME_SCRIPT, 0o755))
    return items


def inject_into_p2(p2_image, selector_dir, conf_text, stage_dir):
    """Modify an extracted rootfs image in place: /usr/local/codeselect/* and the hooked game script.
    Idempotent (existing files are removed first).  Verifies by e2fsck -fn and full read-back."""
    need_tools("debugfs", "e2fsck")
    rc, txt = e2fsck(p2_image)
    if rc != 0:
        raise Refused("p2 is not clean before injection (e2fsck rc=%d):\n%s" % (rc, txt))
    orig = debugfs_cat(p2_image, GAME_SCRIPT)
    if not orig:
        raise Refused("%s is empty or missing in p2" % GAME_SCRIPT)
    times = debugfs_stat(p2_image, GAME_SCRIPT)
    hooked = hook_game_script(orig)
    items = stage_selector(selector_dir, stage_dir, conf_text, hooked)
    cmds = []
    if debugfs_exists(p2_image, SELECT_DIR):
        for ent in debugfs_ls(p2_image, SELECT_DIR):
            if ent[4] not in (".", ".."):
                cmds.append("rm %s/%s" % (SELECT_DIR, ent[4]))
    else:
        cmds.append("mkdir " + SELECT_DIR)
    cmds.append("rm " + GAME_SCRIPT)
    for staged, card, _mode in items:
        cmds.append("write %s %s" % (staged, card))
    cmds.append("set_inode_field %s mode 040755" % SELECT_DIR)
    cmds.append("set_inode_field %s uid 0" % SELECT_DIR)
    cmds.append("set_inode_field %s gid 0" % SELECT_DIR)
    for _staged, card, mode in items:
        cmds.append("set_inode_field %s mode 0%o" % (card, statmod.S_IFREG | mode))
        cmds.append("set_inode_field %s uid 0" % card)
        cmds.append("set_inode_field %s gid 0" % card)
    for k in ("atime", "ctime", "mtime"):
        if k in times:
            cmds.append("set_inode_field %s %s @%d" % (GAME_SCRIPT, k, times[k]))
    debugfs_write_script(p2_image, cmds)
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
    say("injected %d files; %s hook %s; game script times %s" %
        (len(items), GAME_SCRIPT, "present" if has_hook(hooked) else "MISSING",
         "kept" if all(after.get(k) == times.get(k) for k in ("atime", "ctime", "mtime") if k in times) else "changed"))
    return [card for (_s, card, _m) in items]


def inject_card(card, selector_dir, conf_text, workdir=None):
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
        written = inject_into_p2(p2, selector_dir, conf_text, stage)
        say("writing the patched p2 back to %s @LBA %d" % (card, st))
        copy_range(p2, 0, card, st * SECTOR, cnt * SECTOR, "p2 write-back", sparse=False, progress=None)
        a, b = md5_file(p2), md5_range(card, st * SECTOR, cnt * SECTOR)
        if a != b:
            raise Refused("p2 write-back mismatch (%s vs %s)" % (a, b))
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def conf_for_plan(plan, args, existing=None):
    """images.conf text for the card: --conf verbatim, else generated from the layout with the
    flags, falling back to `existing` (a parsed conf already on the card) then to defaults."""
    if getattr(args, "conf", None):
        with open(args.conf, "r") as f:
            text = f.read()
        parsed = parse_images_conf(text)
        devs = [d for (d, _t, _s) in parsed["images"]]
        if devs != plan.devices():
            raise Refused("--conf %s lists %r but the card holds %r" % (args.conf, devs, plan.devices()))
        return text
    ex = existing or {"images": [], "default": None, "timeout": None, "font": None}
    n = len(plan.images)
    titles = split_list(getattr(args, "titles", None))
    subtitles = split_list(getattr(args, "subtitles", None))
    if not titles:
        titles = [t for (_d, t, _s) in ex["images"]][:n] if len(ex["images"]) == n else \
                 [default_title(p.src) for p in plan.images]
    if not subtitles:
        subtitles = [s for (_d, _t, s) in ex["images"]][:n] if len(ex["images"]) == n else []
    default = args.default if getattr(args, "default", None) is not None else (ex["default"] if ex["default"] is not None else 0)
    timeout = args.timeout if getattr(args, "timeout", None) is not None else (ex["timeout"] if ex["timeout"] is not None else 15)
    font = SELECT_DIR + "/font.ttf"
    sel = getattr(args, "selector_dir", None)
    if sel and not os.path.isfile(os.path.join(sel, "font.ttf")) and not os.path.isfile(HOST_FONT):
        font = None
    return render_images_conf(plan.devices(), titles, subtitles, default, timeout, font)


def card_conf(card):
    """The images.conf already on a card's p2, parsed, or None."""
    geom = Geometry.from_file(card)
    _t, st, _cnt = geom.part(2)
    ref = fs_ref(card, st * SECTOR)
    if not debugfs_exists(ref, SELECT_DIR + "/images.conf"):
        return None
    return parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))


def plan_from_card(card):
    """A Plan describing an existing multi card: p3 + every logical after p6 is an image."""
    G = Geometry.from_file(card)
    stock_logs = G.logical[:2]
    extra_geoms = []
    for ebr, t, st, cnt in G.logical[2:]:
        extra_geoms.append(Geometry(cnt * SECTOR, bytes(SECTOR), [(3, t, st, cnt)], None, [], path=card))
    base = Geometry(G.size, G.mbr, G.prim, G.ext, stock_logs, G.ebr_raw, card)
    return Plan(base, extra_geoms, card, [card] * len(extra_geoms))


# ============================================================================= verify
def sfdisk_table(image):
    """[(num, start, count, type)] from `sfdisk -d`."""
    r = subprocess.run(["sfdisk", "-d", image], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(\S+?)(\d+)\s*:\s*start=\s*(\d+),\s*size=\s*(\d+),\s*type=\s*([0-9a-fA-F]+)", line)
        if m:
            rows.append((int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16)))
    return rows, out


def verify_card(card, plan, selector_dir=None):
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
    # every copied range
    for p in plan.prims + plan.logs:
        t0 = time.monotonic()
        if p.num == 2:
            continue
        a = md5_range(p.src, p.src_start * SECTOR, p.count * SECTOR)
        b = md5_range(card, p.start * SECTOR, p.count * SECTOR)
        check("p%d md5 vs %s (%.0f s)" % (p.num, os.path.basename(p.src), time.monotonic() - t0), a == b, a)
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
        for d, t, s in conf["images"]:
            print("    image %s | %s | %s" % (d, t, s))
        print("    default=%d timeout=%d font=%s" % (conf["default"], conf["timeout"], conf["font"]))
        if selector_dir:
            for name, (cardname, mode, required) in SELECTOR_FILES.items():
                src = os.path.join(selector_dir, name)
                if os.path.isfile(src) and cardname in names:
                    back = hashlib.md5(debugfs_cat(ref, SELECT_DIR + "/" + cardname)).hexdigest()
                    check("%s/%s == selector dir's" % (SELECT_DIR, cardname), back == md5_file(src))
    except Refused as e:
        check("p2 selector files", False, str(e))
    # every ext4 partition
    for p in plan.prims + plan.logs:
        if p.ptype != 0x83:
            continue
        t0 = time.monotonic()
        rc, txt = e2fsck(fs_ref(card, p.start * SECTOR))
        check("e2fsck -fn p%d (%.0f s)" % (p.num, time.monotonic() - t0), rc == 0, "" if rc == 0 else txt.strip().splitlines()[-1])
    # every games partition root
    for i, p in enumerate(plan.images):
        try:
            ents = debugfs_ls(fs_ref(card, p.start * SECTOR), "/")
            dirs = [e[4] for e in ents if statmod.S_ISDIR(e[1]) and e[4] not in (".", "..", "lost+found", "spk")]
            link = debugfs_stat(fs_ref(card, p.start * SECTOR), "/game").get("link") if any(e[4] == "game" for e in ents) else None
            check("image %d p%d root: title dir %r, game -> %r" % (i, p.num, dirs, link), dirs and link)
        except Refused as e:
            check("image %d p%d root" % (i, p.num), False, str(e))
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
        cmds.append("write %s %s" % (sp, cardpath))
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
                _mkext(p, cnt * SECTOR // 1024, {"/%s_title/game" % tag: ("%s p3 game\n" % tag).encode()},
                       links=[("/game", "%s_title/game" % tag)])
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


def selftest(d, selector_file=None):
    """Synthetic A+B+C -> multi card with injection -> verify -> inject again -> verify (idempotence)."""
    need_tools("debugfs", "e2fsck", "mke2fs", "sfdisk", "fdisk")
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
    out = os.path.join(d, "multi.img")
    if os.path.exists(out):
        os.unlink(out)
    plan = make_plan(A, [B, C])
    print("== plan")
    print_plan(plan)
    print("== build")
    build_image(plan, out)
    conf = render_images_conf(plan.devices(), ["A stock", "B", "C"], ["synthetic", "", "third"], 1, 7, None)
    inject_card(out, sel, conf, workdir=d)
    print("== verify")
    ok = verify_card(out, plan, sel)
    print("== inject again (idempotence)")
    inject_card(out, sel, conf, workdir=d)
    ok &= verify_card(out, plan, sel)
    ref = fs_ref(out, plan.prims[1].start * SECTOR)
    back = parse_images_conf(debugfs_cat(ref, SELECT_DIR + "/images.conf"))
    ok &= back["images"] == [("/dev/mmcblk0p3", "A stock", "synthetic"), ("/dev/mmcblk0p7", "B", ""), ("/dev/mmcblk0p8", "C", "third")]
    ok &= back["default"] == 1 and back["timeout"] == 7
    for n in (7, 8):
        _t, st, _c = Geometry.from_file(out).part(n)
        link = debugfs_stat(fs_ref(out, st * SECTOR), "/game").get("link")     # a fast symlink has no blocks to cat
        marker = debugfs_cat(fs_ref(out, st * SECTOR), "/" + (link or "game")).decode().strip()
        print("p%d /game -> %r -> %r" % (n, link, marker))
        ok &= marker == ("%s p3 game" % ("B" if n == 7 else "C"))
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


# ============================================================================= CLI
def _add_images(s, out_flag):
    s.add_argument("--primary", required=True, help="the image whose p1/p2/p3/p5/p6 the card gets (index 0)")
    s.add_argument("--extra", action="append", default=[], metavar="IMG", help="an extra image (its games partition becomes p7, p8, ...)")
    if out_flag:
        s.add_argument(out_flag, required=True, help="the multi-image card image")


def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="directory holding codeselect (ARM binary), select.sh and optionally font.ttf")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--default", type=int, help="images.conf default index (default 0)")
    s.add_argument("--conf", help="use this images.conf verbatim instead of generating one")


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
    s.add_argument("--no-inject", action="store_true", help="only copy + tables; leave p2 stock")
    s.add_argument("--dd", action="store_true", help="copy the ranges with dd bs=16M conv=sparse instead of python")
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s = sub.add_parser("inject", help="redo only the p2 injection on an existing multi card (idempotent)")
    s.add_argument("--card", required=True, help="the multi card to modify IN PLACE")
    _add_conf_flags(s)
    s = sub.add_parser("verify", help="check an existing multi card against its sources")
    s.add_argument("--card", required=True)
    _add_images(s, None)
    s.add_argument("--selector-dir", help="also compare the injected files against this directory")
    s = sub.add_parser("selftest", help="synthetic end-to-end test (needs debugfs/mke2fs/e2fsck/sfdisk/fdisk)")
    s.add_argument("dir")
    s.add_argument("--selector", help="any small file to stand in for the codeselect binary")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            print_plan(make_plan(a.primary, a.extra))
        elif a.cmd == "check-stock":
            return 0 if check_stock(a.image) else 1
        elif a.cmd == "build":
            check_output_path(a.out, [a.primary] + a.extra + [a.conf, a.selector_dir], force=a.force)
            if not a.no_inject and not a.selector_dir:
                raise Refused("build needs --selector-dir (or --no-inject)")
            plan = make_plan(a.primary, a.extra)
            print_plan(plan)
            if not a.extra:
                say("WARNING: no --extra given; building a one-image card")
            conf = None
            if not a.no_inject:
                conf = conf_for_plan(plan, a)          # generated (and validated) before the long copy
                stage_selector(a.selector_dir, tempfile.mkdtemp(prefix="mkmulticard.chk."), conf, hook_game_script(SYNTH_GAME))
                print("== images.conf to inject\n" + conf.rstrip())
            for x, g in zip(plan.extras, plan.extra_geoms):
                t2, s2, c2 = g.part(2)
                same = md5_range(x, s2 * SECTOR, c2 * SECTOR) == md5_range(plan.primary, plan.prims[1].src_start * SECTOR, plan.prims[1].count * SECTOR)
                say("extra %s rootfs (p2) == primary rootfs: %s" % (os.path.basename(x), "YES" if same else
                    "NO - only its games partition is carried; its rootfs changes are NOT on this card"))
            t0 = time.monotonic()
            build_image(plan, a.out, use_dd=a.dd)
            say("copy + tables took %.0f s" % (time.monotonic() - t0))
            if not a.no_inject:
                t1 = time.monotonic()
                inject_card(a.out, a.selector_dir, conf, workdir=os.path.dirname(os.path.abspath(a.out)))
                say("injection took %.0f s" % (time.monotonic() - t1))
            alloc = allocated_bytes(a.out)
            say("wrote %s: %d bytes apparent%s in %.0f s" % (a.out, plan.total_bytes,
                (", %s allocated" % _gb(alloc)) if alloc is not None else "", time.monotonic() - t0))
            if conf:
                print(conf.rstrip())
        elif a.cmd == "inject":
            check_output_path(a.card, [a.conf, a.selector_dir], must_exist=True)
            if not a.selector_dir:
                raise Refused("inject needs --selector-dir")
            plan = plan_from_card(a.card)
            if len(plan.images) < 2:
                say("WARNING: %s holds no extra images (p7...); injecting a one-image selector" % a.card)
            conf = conf_for_plan(plan, a, existing=card_conf(a.card))
            print("== images.conf to inject\n" + conf.rstrip())
            written = inject_card(a.card, a.selector_dir, conf, workdir=os.path.dirname(os.path.abspath(a.card)))
            say("injected into %s: %s" % (a.card, ", ".join(written)))
        elif a.cmd == "verify":
            plan = make_plan(a.primary, a.extra)
            return 0 if verify_card(a.card, plan, a.selector_dir) else 1
        elif a.cmd == "selftest":
            return 0 if selftest(a.dir, a.selector) else 1
    except Refused as e:
        print("[card] error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
