#!/usr/bin/env python3
"""mkjjpmulti.py - two JJP install ISOs in, one multi-boot install ISO out (item 116).

A JJP release ISO is a Clonezilla live stick: /live/ (the installer's Linux),
/home/partimag/img/ (partclone images of the machine's four partitions, gzipped
and split into 1 GB pieces: sda1 EFI, sda2 /boot, sda3 the Ubuntu root with
/jjpe/gen1/<Game>, sda4 perm) and JJP's own installer, /jjp/bin/jjp_install.sh
inside /live/filesystem.squashfs, named by ocs_live_run= in both boot configs.
That installer partitions the machine's disk into JJP's A/B layout and restores
sda3 into BOTH root slots (p3 = root A, p5 = root B); grub always boots A.

THE MULTI-BOOT INSTALL (plans/jjp_multiboot_plan.md 2.1 / 2.4).  Image 0's root
goes into root A with the boot menu staged into it; image 1's root goes into
root B VERBATIM - JJP's installer already restores a full root there, this tool
only changes WHICH image.  On the machine, rungame.sh runs the hook
(padselect.sh, item 115) which shows the menu (jjpselect, item 114) and, for
image 1, mounts root B and bind-mounts its /jjpe/gen1/<Game> over root A's
before the game starts.  Perm A is shared, so settings and scores are one set.
The ISO that comes out differs from the stock one in exactly these ways:

  /home/partimag/img/sda3.ext4-ptcl-img.gz.a?   image 0's root, re-imaged with the
                                                 menu staged (/jjpe/gen1/padselect/,
                                                 /jjpe/gen1/scripts/padselect.sh, ONE
                                                 guarded line in scripts/rungame.sh)
  /home/partimag/img/sda5.ext4-ptcl-img.gz.a?   image 1's sda3 pieces, copied byte for
                                                 byte and renamed - never re-encoded
  /jjp/pad_install.sh                            a copy of the stick's own jjp_install.sh
                                                 with two lines changed: root B is checked
                                                 and restored from sda5.ext4-ptcl-img
  /syslinux/syslinux.cfg, /boot/grub/grub.cfg    ocs_live_run= names that copy
                                                 ("bash /lib/live/mount/medium/jjp/pad_install.sh":
                                                 the medium IS the stick, Clonezilla evals the
                                                 string, so no squashfs repack and no exec bit)
  /jjp/padselect/                                a mirror of what was staged into root A
                                                 (images.conf, build.json, media.json, the
                                                 media, the hook, the selector) so `inspect`
                                                 reads a finished ISO without restoring it

Nothing else on the ISO moves; xorriso rewrites it with -boot_image any replay,
which is how the app's own Write pipeline splices a modified root into a stock
ISO (plugins/jjp/pipeline.py _phase_build_iso).  The stick is a FAT copy of the
ISO's files (the app's existing stick flow), so the boot records only matter for
a burned ISO.

THE SAME-VERSION GATE.  Two roots on one perm partition must be the same game
code: version_info.txt's Name and Version on both ISOs, setenv.sh's GAMENAME and
the sha256 of /jjpe/gen1/<Game>/game and of its fl.dat must all agree, or `build`
refuses (--allow-version-mismatch overrides; read the refusal first - a second
version reads settings the first one wrote).  A retheme built by this app passes:
it keeps the game binary and forges its asset CRCs to the shipped fl.dat.

THE RESTORE CACHE is the rig's: /var/tmp/jjp_<slug>/sda3.raw, the directory
tools/jjp_emu/mount.sh restores an ISO into (padpath.sh's jjp_slug), so an ISO
the emulator has run needs no second restore here and one this tool restored
mounts instantly in the emulator.  A restore lands as sda3.raw.part and is
renamed only when complete, so an interrupted run leaves nothing a later one
would trust.  --cache-dir moves the base directory.

THE CLI PROTOCOL is mkmulticard.py's, so the Multi-boot tab's parsers hold
(item 118): `[card] progress a/b p% stage` lines from one byte meter over the
whole build, `image-size` rows, a `fits` line per stick size, `[card] error:`
for every refusal (exit 2), `verify: PASS|FAIL`, `inspect --json` one object.

  mkjjpmulti.py plan    --primary ISO0 --extra ISO1 [--media-dir DIR] [--cache-dir DIR]
        the version table, the byte rows and which USB stick it fits; writes nothing
        (no root needed: the ISOs are read through xorriso)
  mkjjpmulti.py build   --primary ISO0 --extra ISO1 --out OUT.iso --selector-dir DIR
                        [--media-dir DIR] [--titles "T0;T1"] [--subtitles "S0;S1"]
                        [--timeout N] [--default N] [--volume V] [--heading TEXT]
                        [--theme NAME] [--color ROLE=RRGGBB ...] [--conf FILE]
                        [--jjp-update refuse|allow] [--debug-log] [--allow-version-mismatch]
                        [--force] [--workdir DIR] [--cache-dir DIR] [--keep-work]
        root (wsl -u root): loop mounts of the ISOs and of the scratch root
  mkjjpmulti.py inject  --iso OUT.iso --selector-dir DIR [--media-dir DIR] [conf flags...]
        redo the staging on an existing multi ISO IN PLACE (a menu/media/conf change):
        its own sda3 is restored, re-staged, re-imaged and spliced back; the provenance
        in build.json is carried through
  mkjjpmulti.py verify  --iso OUT.iso [--primary ISO0] [--extra ISO1] [--quick] [--workdir DIR]
        the cfg lines, the installer diff (against the ISO's own squashfs copy), every
        piece present and gunzip -t clean, sda5 == ISO1's sda3 byte for byte, and the
        staged files inside sda3 (restored to scratch) against the shas build.json
        recorded; --quick skips the gunzip/sha/restore work
  mkjjpmulti.py inspect --iso X [--json] [--media-out DIR]
        read a finished ISO back: the menu, the provenance, the media (no root)
  mkjjpmulti.py media   --primary ISO0 --extra ISO1 --out DIR [--art N=auto|none|PATH|VIDEO@T]
                        [--anim N=none|PATH[@START[:SECONDS[:FPS]]]] [--music N=PATH|none]
                        [--sound-move synth|none|PATH] [--sound-confirm synth|none|PATH|N=...]
                        [--volume V] [--visual-only]
        the media set + media.json through selectmedia.py with JJP's seams: 'auto' art is
        the image's own /jjpe/gen1/miscfiles/graphics/JJP_logo_message.png (plaintext,
        1360x768); an attract clip has no JJP seam yet, so an animation is a video file
  mkjjpmulti.py selftest DIR
        two synthetic JJP ISOs (root: mke2fs -d, partclone, mksquashfs, xorriso) ->
        build -> verify -> inspect -> inject -> the mismatch refusal; in DIR

Every OUTPUT path is explicit; an existing one needs --force; nothing is ever
written under David's image library (mkmulticard's refusal, shared).
"""
import argparse
import collections
import difflib
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SPIKE2_EMU = os.path.join(REPO_ROOT, "tools", "spike2_emu")
CODESELECT = os.path.join(SPIKE2_EMU, "codeselect")
if SPIKE2_EMU not in sys.path:
    sys.path.insert(0, SPIKE2_EMU)
import mkmulticard as mkc                                           # noqa: E402  the shared pure parts
from mkmulticard import Refused, say, PROGRESS, check_output_path   # noqa: E402

TOOL = "mkjjpmulti"
#: build.json's shape; a reader must accept an older (or missing) one.
VERSION = "1.0"

# ---- the ISO ---------------------------------------------------------------------------------
PARTIMAG = "/home/partimag/img"
PIECE_RE = re.compile(r"^(sda\d+)\.(vfat|ext4)-ptcl-img\.gz\.([a-z]{2})$")
ROOT_PART, ROOTB_PART = "sda3", "sda5"
ROOT_PIECE = "sda3.ext4-ptcl-img"
ROOTB_PIECE = "sda5.ext4-ptcl-img"
SQUASHFS = "/live/filesystem.squashfs"
SQ_INSTALLER = "jjp/bin/jjp_install.sh"              # inside the squashfs
PAD_INSTALLER = "/jjp/pad_install.sh"                # on the ISO / the stick
CFG_FILES = ("/syslinux/syslinux.cfg", "/boot/grub/grub.cfg")
OCS_STOCK = 'ocs_live_run="/jjp/bin/jjp_install.sh"'
#: Clonezilla writes $ocs_live_run into a temp script and runs THAT (ocs-live-run-menu), so
#: this is a shell command line: 'bash <file>' runs the copy on the stick whatever exec bit
#: a FAT copy or a loop-mounted ISO gives it, and whether the medium is mounted noexec.
OCS_PAD = 'ocs_live_run="bash /lib/live/mount/medium/jjp/pad_install.sh"'
ISO_PAD_DIR = "/jjp/padselect"
VERSION_INFO = "/version_info.txt"
SPLIT_DEFAULT = 1000000000                           # JJP's pieces: 1 GB, decimal, exactly

# ---- the root --------------------------------------------------------------------------------
JJPEDIR = "/jjpe/gen1"
PADSELECT_DIR = JJPEDIR + "/padselect"
MEDIA_DIR = PADSELECT_DIR + "/media"
HOOK_PATH = JJPEDIR + "/scripts/padselect.sh"
RUNGAME = JJPEDIR + "/scripts/rungame.sh"
SETENV = JJPEDIR + "/setenv.sh"
FS_UUIDS = JJPEDIR + "/scripts/fs_uuids.sh"
LOGO_PNG = JJPEDIR + "/miscfiles/graphics/JJP_logo_message.png"
RUNONCE_LINE = "$JJPEDIR/scripts/runonce.sh"
HOOK_LINES = [
    "",
    "# PAD multi-boot: a boot menu when this install carries more than one image (padselect.sh)",
    "[ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh",
]
#: staged name -> (mode, required); jjpselect + font under PADSELECT_DIR, the hook under scripts/
SELECTOR_FILES = collections.OrderedDict([
    ("jjpselect", (0o755, True)),
    ("padselect.sh", (0o755, True)),
    ("font.ttf", (0o644, False)),
])
JJP_CARD_LOG = "/jjpe/temp/jjpselect.log"
DEVICES = ("rootA", "rootB")
DEVICE_RE = re.compile(r"^root([AB])(?::([A-Za-z0-9._-]+))?$")
CONF_KEYS = ("default", "timeout", "heading", "font", "sound_move", "sound_confirm", "volume",
             "volume_max", "media", "theme", "jjp_update", "log")
JJP_UPDATE_POLICIES = ("refuse", "allow")
#: THE MENU'S VOLUME ON A JJP MACHINE (item 120).  JJP runs its amplifier chain at full
#: (root A's asound.state holds 0 dB, scripts/audio/mute.pl sets 100%) and turns only the
#: game's own stream down to the operator volume, so the menu's software gain is the level
#: the speakers get - volume=50 was "very high" on the first GNR.  A quiet default, a cap
#: this builder refuses past (the selector's JJP build cannot pass it either, and the
#: machine's own Volume+/- buttons step within it), and every menu sound and music bed the
#: media step writes peak-levelled to one mark, so no source file arrives louder than planned.
VOLUME_DEFAULT = 20
VOLUME_MAX = 40
# -3 dBFS, not -12: at -12 on top of volume 20 the menu's 40 ms click peaked 20 dB under
# the pre-120 menu David called very loud, and on the GNR that read as no sound at all
# (2026-09-14).  At -3 the default sits 11 dB under it and the cap 5 dB under it.
MEDIA_PEAK_DBFS = -3.0

# ---- the installer patch (exact lines of JJP's jjp_install.sh) --------------------------------
CHECK_ROOT_LINE = 'check_image "ROOT" "sda3.ext4-ptcl-img"'
CHECK_ROOTB_LINE = 'check_image "ROOT B" "sda5.ext4-ptcl-img"'
RESTORE_B_STOCK = 'restore_partition "$PART_ROOTB" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTB"'
RESTORE_B_PAD = 'restore_partition "$PART_ROOTB" "sda5.ext4-ptcl-img" "$FS_UUID_ROOTB"'
PAD_HEADER = [
    "# PAD multi-boot (mkjjpmulti.py): root B is restored from sda5.ext4-ptcl-img - the second",
    "# image on this stick - instead of a copy of root A.  Two lines differ from",
    "# /jjp/bin/jjp_install.sh; everything else is Jersey Jack's installer as shipped.",
]

#: Usable bytes of a FAT32 USB stick by marketing size - the decimal size less the ~4% every
#: stick loses to its controller and the FAT (a 16 GB stick formats to ~15.4 GB).
USB_SIZES = collections.OrderedDict([("8G", 7_700_000_000), ("16G", 15_400_000_000),
                                     ("32G", 30_900_000_000), ("64G", 61_800_000_000)])
CACHE_DIR_DEFAULT = "/var/tmp"
CHUNK = 8 << 20
MOUNT_PREFIX = "/var/tmp/mkjjpmulti_mnt_"


# ============================================================================= small helpers
def _run(argv, ok_rc=(0,), input_bytes=None, env=None):
    r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, input=input_bytes, env=env)
    out = r.stdout.decode("utf-8", "replace")
    if r.returncode not in ok_rc:
        raise Refused("%s failed (rc=%d): %s" % (" ".join(argv[:3]), r.returncode, out.strip()[-1500:]))
    return out


def syncfs(path):
    """syncfs(2) on the filesystem holding `path` (coreutils `sync -f`) - NEVER a global sync():
    under WSL2 a global sync also flushes the virtiofs mounts of the Windows drives, and that
    wait (fuse_sync_fs -> request_wait_answer) parked a build for good on 2026-09-13."""
    subprocess.run(["sync", "-f", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def need_tools(*names):
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise Refused("missing tool(s): %s (apt-get install partclone xorriso pigz e2fsprogs "
                      "squashfs-tools)" % ", ".join(missing))


def is_root():
    return os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0


def require_root(what):
    if not is_root():
        raise Refused("%s needs root for its loop mounts: run it under 'wsl -u root'" % what)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _gb(n):
    return "%.2f GB" % (n / 1e9)


def iso_slug(path):
    """padpath.sh's jjp_slug: the basename without .iso, every other character a '_', trailing
    '_' dropped - the directory the rig restores an ISO into."""
    b = os.path.basename(path)
    b = re.sub(r"\.[Ii][Ss][Oo]$", "", b)
    b = re.sub(r"[^A-Za-z0-9._-]", "_", b)
    return b.rstrip("_")


def cache_base(iso, cache_dir=None):
    return os.path.join(cache_dir or CACHE_DIR_DEFAULT, "jjp_" + iso_slug(iso))


def default_title(path):
    """'CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso' -> 'CHAKAs LOTLJ V1.0 GNR LE 3.03'."""
    b = os.path.basename(path or "image")
    b = re.sub(r"\.[Ii][Ss][Oo]$", "", b)
    return re.sub(r"[_\s]+", " ", b).strip() or "image"


def split_list(s):
    return [x for x in s.split(";")] if s else []


# ============================================================================= the ISO, read
def read_version_info(text):
    """version_info.txt -> {'Title': ..., 'Name': ..., 'Version': ..., ...}; '#' lines skipped."""
    out = collections.OrderedDict()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def parse_piece_name(name):
    m = PIECE_RE.match(name)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def iso_files(iso):
    """Every FILE on the ISO -> [(path, size)], through xorriso (no mount, no root)."""
    need_tools("xorriso")
    out = _run(["xorriso", "-report_about", "SORRY", "-indev", iso, "-find", "/", "-type", "f",
                "-exec", "lsdl", "--"])
    files = []
    for line in out.splitlines():
        m = re.match(r"^([-dl])\S+\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\d+\s+\S+\s+(.*)$", line.strip())
        if not m or m.group(1) != "-":
            continue
        name = m.group(3).strip()
        if name.startswith("'") and name.endswith("'"):
            name = name[1:-1]
        files.append((name if name.startswith("/") else "/" + name, int(m.group(2))))
    if not files:
        raise Refused("%s: xorriso lists no files - not an ISO image?" % iso)
    return files


def iso_extract(iso, paths, dest_dir):
    """Extract ISO paths (files or directories) under dest_dir, same relative paths (no root)."""
    need_tools("xorriso")
    argv = ["xorriso", "-report_about", "SORRY", "-osirrox", "on", "-indev", iso]
    for p in paths:
        d = os.path.join(dest_dir, p.lstrip("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        argv += ["-extract", p, d]
    argv += ["--"]
    _run(argv)
    for root, dirs, fnames in os.walk(dest_dir):            # xorriso keeps the ISO's r-- modes
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in fnames:
            os.chmod(os.path.join(root, f), 0o644)


def iso_has_joliet(iso):
    """True / False: does the ISO carry a Joliet tree (read off the volume
    descriptor set; None when it is not an ISO 9660 image)?  Windows reads an
    ISO's long names from Joliet, and the app's stick maker on Windows copies
    what Windows shows - without it every `sdaN.ext4-ptcl-img.gz.aa` lands on
    the stick as `SDAN_EXT4_PTCL_IMG_GZ.AA` and the installer finds nothing
    (item 119).  The same test as plugins/jjp/usbstick.py's."""
    sector = 2048
    try:
        with open(iso, "rb") as f:
            for i in range(16, 64):
                f.seek(i * sector)
                vd = f.read(sector)
                if len(vd) < 91 or vd[1:6] != b"CD001":
                    return None if i == 16 else False
                if vd[0] == 255:
                    return False
                if vd[0] == 2 and vd[88:91] in (b"%/@", b"%/C", b"%/E"):
                    return True
    except OSError:
        return None
    return False


def iso_has_boot(iso):
    """True when the ISO carries El Torito boot records (a stock JJP ISO does; the selftest's
    synthetic ones do not, and -boot_image any replay on those is a refusal)."""
    out = _run(["xorriso", "-report_about", "SORRY", "-indev", iso, "-report_el_torito", "plain"],
               ok_rc=(0, 1, 2, 3))
    # 'El Torito boot img :   1  BIOS  y   none ...' per image; nothing at all without a catalog
    return "El Torito boot img" in out


class IsoInfo:
    """What a JJP install ISO says about itself, from its small files and its listing."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.version = collections.OrderedDict()
        self.pieces = collections.OrderedDict()             # part -> [(name, size)] in order
        self.files = []                                     # [(path, size)]
        self.cfg = {}                                       # cfg path -> text
        self.has_squashfs = False
        self.pad_dir = False

    @property
    def title(self):
        return self.version.get("Title") or ""

    @property
    def name(self):
        return self.version.get("Name") or ""

    @property
    def game_version(self):
        return self.version.get("Version") or ""

    def piece_bytes(self, part):
        return sum(s for _n, s in self.pieces.get(part, []))

    def overhead_bytes(self):
        """Everything on the ISO but the root pieces (image 0's sda3 and image 1's sda5)."""
        skip = set(n for p in (ROOT_PART, ROOTB_PART) for n, _s in self.pieces.get(p, []))
        return sum(s for path, s in self.files
                   if not (path.startswith(PARTIMAG + "/") and os.path.basename(path) in skip))

    def split_size(self):
        """The piece size the ISO was split with: the first piece's, when there is a second one
        to prove the first is full; JJP's 1 GB otherwise."""
        p = self.pieces.get(ROOT_PART) or []
        return p[0][1] if len(p) >= 2 else SPLIT_DEFAULT

    def check_stock_shape(self, what="ISO"):
        if not self.pieces.get(ROOT_PART):
            raise Refused("%s %s carries no %s pieces under %s - not a JJP install ISO"
                          % (what, self.path, ROOT_PIECE, PARTIMAG))
        if not self.has_squashfs:
            raise Refused("%s %s has no %s - not a Clonezilla live ISO" % (what, self.path, SQUASHFS))
        if not self.name or not self.game_version:
            raise Refused("%s %s: %s names no Name/Version" % (what, self.path, VERSION_INFO))


def iso_info(iso, mnt=None):
    """IsoInfo from a loop-mounted ISO (mnt) or through xorriso (no root)."""
    info = IsoInfo(iso)
    if mnt:
        files = []
        for root, _dirs, fnames in os.walk(mnt):
            for f in fnames:
                p = os.path.join(root, f)
                files.append(("/" + os.path.relpath(p, mnt).replace(os.sep, "/"), os.path.getsize(p)))
        info.files = sorted(files)

        def read(p):
            fp = os.path.join(mnt, p.lstrip("/"))
            if not os.path.isfile(fp):
                return None
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    else:
        info.files = sorted(iso_files(iso))
        tmp = tempfile.mkdtemp(prefix="mkjjpmulti_iso_")
        want = [p for p in (VERSION_INFO,) + CFG_FILES if any(fp == p for fp, _s in info.files)]
        try:
            if want:
                iso_extract(iso, want, tmp)
            texts = {}
            for p in want:
                with open(os.path.join(tmp, p.lstrip("/")), "r", encoding="utf-8", errors="replace") as f:
                    texts[p] = f.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        def read(p):
            return texts.get(p)
    info.version = read_version_info(read(VERSION_INFO))
    for p in CFG_FILES:
        t = read(p)
        if t is not None:
            info.cfg[p] = t
    for path, size in info.files:
        if path.startswith(PARTIMAG + "/"):
            pp = parse_piece_name(os.path.basename(path))
            if pp:
                info.pieces.setdefault(pp[0], []).append((os.path.basename(path), size))
        elif path == SQUASHFS:
            info.has_squashfs = True
        elif path.startswith(ISO_PAD_DIR + "/"):
            info.pad_dir = True
    for part in info.pieces:
        info.pieces[part].sort()
    return info


class IsoMount:
    """A read-only loop mount of an ISO for a `with` block (root)."""

    def __init__(self, iso, mnt):
        self.iso, self.mnt = os.path.abspath(iso), mnt

    def __enter__(self):
        os.makedirs(self.mnt, exist_ok=True)
        if os.path.ismount(self.mnt):
            _run(["umount", self.mnt])
        _run(["mount", "-o", "loop,ro", self.iso, self.mnt])
        return self.mnt

    def __exit__(self, *exc):
        for attempt in range(5):
            r = subprocess.run(["umount", self.mnt], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode == 0:
                break
            time.sleep(0.5 * (attempt + 1))
        else:
            say("WARNING: could not unmount %s: %s" % (self.mnt, r.stdout.decode("utf-8", "replace").strip()))
        try:
            os.rmdir(self.mnt)
        except OSError:
            pass
        return False


# ============================================================================= the root, read
def fs_size_bytes(raw):
    """The ext4 superblock's own size (0 when there is no superblock)."""
    with open(raw, "rb") as f:
        f.seek(0x400)
        sb = f.read(0x400)
    if len(sb) < 0x400 or sb[0x38:0x3A] != b"\x53\xef":
        return 0
    blocks = struct.unpack_from("<I", sb, 0x4)[0]
    if struct.unpack_from("<I", sb, 0x60)[0] & 0x80:
        blocks |= struct.unpack_from("<I", sb, 0x150)[0] << 32
    return blocks * (1024 << struct.unpack_from("<I", sb, 0x18)[0])


def debugfs_cat(raw, path):
    """The bytes of a file inside an ext4 image, or None when it is not there (no mount)."""
    r = subprocess.run(["debugfs", "-R", 'cat "%s"' % path, raw], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0 or "File not found" in err or "not found" in err.lower() and not r.stdout:
        return None
    return r.stdout


def debugfs_exists(raw, path):
    r = subprocess.run(["debugfs", "-R", 'stat "%s"' % path, raw], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = r.stderr.decode("utf-8", "replace")
    return r.returncode == 0 and "File not found" not in err and b"Inode:" in r.stdout


def root_identity(raw):
    """What a restored JJP root says it is: the game directory, its game and fl.dat shas, the
    used bytes, root B's UUID, whether the menu is already staged."""
    ident = collections.OrderedDict()
    setenv = debugfs_cat(raw, SETENV)
    m = re.search(r"^\s*(?:export\s+)?GAMENAME=['\"]?([A-Za-z0-9_.-]+)", (setenv or b"").decode("utf-8", "replace"), re.M)
    if not m:
        raise Refused("%s: no GAMENAME in %s - not a JJP root" % (raw, SETENV))
    ident["gamename"] = m.group(1)
    gamedir = JJPEDIR + "/" + ident["gamename"]
    game = debugfs_cat(raw, gamedir + "/game")
    if game is None:
        raise Refused("%s: no %s/game" % (raw, gamedir))
    ident["game_bytes"], ident["game_sha256"] = len(game), sha256_bytes(game)
    fl = debugfs_cat(raw, gamedir + "/fl.dat")
    ident["fldat_bytes"] = len(fl) if fl is not None else None
    ident["fldat_sha256"] = sha256_bytes(fl) if fl is not None else None
    uu = (debugfs_cat(raw, FS_UUIDS) or b"").decode("utf-8", "replace")
    m = re.search(r"^FS_UUID_ROOTB=([0-9a-fA-F-]+)", uu, re.M)
    ident["fs_uuid_rootb"] = m.group(1) if m else None
    rg = (debugfs_cat(raw, RUNGAME) or b"").decode("utf-8", "replace")
    ident["rungame_hooked"] = has_hook(rg)
    ident["padselect_staged"] = debugfs_exists(raw, PADSELECT_DIR + "/images.conf")
    used, total = mkc.ext_used_bytes(raw, 0)
    ident["used_bytes"], ident["fs_bytes"] = used, total
    return ident


# ============================================================================= restore
def restore_pieces(pieces, dest, meter=None, label="sda3"):
    """cat pieces | gunzip | partclone.restore into a sparse raw file, then size it up to the
    filesystem's own block count (partclone stops at the last used block).  Written as
    dest.part and renamed when complete.  The pieces are fed from here so the meter sees
    the compressed bytes go by."""
    need_tools("gunzip", "partclone.restore")
    part = dest + ".part"
    log = dest + ".restore.log"
    for p in (part, log):
        if os.path.exists(p):
            os.unlink(p)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    # TEXT mode, not -N: in partclone 0.3.x -N means "use the NCURSES
    # interface", so the log used to hold a full-screen UI's escape codes and
    # a failure's tail was unreadable.  -f 5 -B: a "Completed: N%" line every
    # five seconds and no block-count line under each - the log stays small
    # and a refusal's tail says how far it got.  (The meter above is the
    # builder's own progress; this is only what the log records.)
    cmd = 'set -o pipefail; gunzip -c | partclone.restore -C -f 5 -B -s - -o "$0" >"$1" 2>&1'
    proc = subprocess.Popen(["bash", "-c", cmd, part, log], stdin=subprocess.PIPE)
    fed = 0
    broken = False
    try:
        for piece in pieces:
            with open(piece, "rb") as f:
                for chunk in iter(lambda: f.read(CHUNK), b""):
                    try:
                        proc.stdin.write(chunk)
                    except BrokenPipeError:
                        broken = True
                        break
                    fed += len(chunk)
                    if meter is not None:
                        meter.sample(fed)
            if broken:
                break
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        rc = proc.wait()
    if rc != 0 or broken:
        tail = ""
        if os.path.isfile(log):
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read()[-1200:]
        for p in (part,):
            if os.path.exists(p):
                os.unlink(p)
        raise Refused("%s: partclone.restore failed (rc=%d)%s" % (label, rc, ("\n" + tail) if tail else ""))
    fs = fs_size_bytes(part)
    if fs and os.path.getsize(part) < fs:
        os.truncate(part, fs)
    os.replace(part, dest)
    if os.path.isfile(log):
        os.unlink(log)
    return dest


def piece_paths(mnt, info, part):
    return [os.path.join(mnt, PARTIMAG.lstrip("/"), n) for n, _s in info.pieces.get(part, [])]


def cached_root_raw(iso, cache_dir=None, mnt=None, info=None, meter=None):
    """The rig-shaped restore of an ISO's sda3 (restored here when absent and `mnt` allows)."""
    base = cache_base(iso, cache_dir)
    raw = os.path.join(base, "sda3.raw")
    if os.path.isfile(raw) and os.path.getsize(raw) > 0:
        return raw
    if mnt is None or info is None:
        return None
    os.makedirs(base, exist_ok=True)
    say("restoring %s's root into %s (%s compressed)" % (os.path.basename(iso), raw, _gb(info.piece_bytes(ROOT_PART))))
    restore_pieces(piece_paths(mnt, info, ROOT_PART), raw, meter, label=os.path.basename(iso) + " sda3")
    return raw


def sparse_copy(src, dst, meter=None):
    """cp --sparse=always (a 32 GiB declared root with ~8 GB used copies in about a minute)."""
    if os.path.exists(dst):
        os.unlink(dst)
    _run(["cp", "--sparse=always", src, dst])
    if meter is not None:
        meter.sample(os.path.getsize(src))


# ============================================================================= the hook + conf
def has_hook(text):
    return HOOK_LINES[2] in (text or "")


def hook_rungame(text):
    """rungame.sh with the guarded hook line after runonce.sh (idempotent).  Refused when the
    anchor is not there: a rungame.sh this tool does not know is not edited blind."""
    if has_hook(text):
        return text
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == RUNONCE_LINE]
    if len(at) != 1:
        raise Refused("rungame.sh: expected exactly one '%s' line to hook after, found %d" % (RUNONCE_LINE, len(at)))
    i = at[0] + 1
    return "\n".join(lines[:i] + HOOK_LINES + lines[i:])


def strip_hook(text):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        if lines[i:i + len(HOOK_LINES)] == HOOK_LINES:
            i += len(HOOK_LINES)
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def parse_device(dev):
    m = DEVICE_RE.match(dev or "")
    if not m:
        raise Refused("images.conf: device %r is not rootA, rootB or rootB:<subdir>" % (dev,))
    return m.group(1), m.group(2)


def check_jjp_update(policy):
    p = (policy or "refuse").strip().lower()
    if p not in JJP_UPDATE_POLICIES:
        raise Refused("jjp_update=%r: refuse or allow" % (policy,))
    return p


def render_images_conf(devices, titles=None, subtitles=None, default=0, timeout=15, font=None, media=None,
                       sound_move=None, sound_confirm=None, volume=None, media_dir=None, theme=None,
                       colors=None, heading=None, jjp_update="refuse", debug_log=False):
    """images.conf for the JJP hook + selector: the same grammar the Stern builder writes (an
    image line as wide as it needs to be, the global keys after) with JJP's device tokens and
    its one extra key, jjp_update=."""
    devices = list(devices)
    if not devices:
        raise Refused("images.conf: no images")
    if len(devices) > mkc.MAX_IMAGES:
        raise Refused("images.conf: %d images; the selector takes at most %d" % (len(devices), mkc.MAX_IMAGES))
    for d in devices:
        parse_device(d)
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    rows = [tuple(m) if m else mkc.MEDIA_ROW for m in (media or [])]
    rows = [m + ("",) * (len(mkc.MEDIA_ROW) - len(m)) if len(m) < len(mkc.MEDIA_ROW) else m for m in rows]
    if len(titles) > len(devices) or len(subtitles) > len(devices) or len(rows) > len(devices):
        raise Refused("images.conf: %d titles / %d subtitles / %d media rows for %d images"
                      % (len(titles), len(subtitles), len(rows), len(devices)))
    titles += ["image %d" % i for i in range(len(titles), len(devices))]
    subtitles += [""] * (len(devices) - len(subtitles))
    rows += [mkc.MEDIA_ROW] * (len(devices) - len(rows))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    rows = [tuple(mkc._media_name_ok(x or "", what) for x, what in zip(m, mkc.MEDIA_FIELDS)) for m in rows]
    sound_move = mkc._media_name_ok(sound_move or "", "sound_move")
    sound_confirm = mkc._media_name_ok(sound_confirm or "", "sound_confirm")
    if not (0 <= int(default) < len(devices)):
        raise Refused("images.conf: default=%s is not an image index (0..%d)" % (default, len(devices) - 1))
    if int(timeout) < 0:
        raise Refused("images.conf: timeout must be >= 0")
    volume = VOLUME_DEFAULT if volume is None else mkc._int_range(volume, "volume", 0, 100)
    if volume > VOLUME_MAX:
        raise Refused("images.conf: volume=%d is above %d, the most a JJP boot menu may play at "
                      "(the machine's amplifiers run at full while it does)" % (volume, VOLUME_MAX))
    theme = mkc.check_theme(theme)
    colors = mkc.check_colors(colors)
    jjp_update = check_jjp_update(jjp_update)
    any_media = any(any(r) for r in rows)
    width = 4 if any(r[3] for r in rows) else (3 if any_media else 0)
    out = ["# images.conf - the JJP boot menu (jjpselect + padselect.sh); written by mkjjpmulti.py",
           "# image=<device>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
           "# device: rootA = this root, rootB = the machine's root B slot (image 1), rootB:<dir> a tree",
           "# under it; media names are relative to media=; default = highlight when no last choice;",
           "# timeout = seconds before the highlighted image boots by itself (0 = for ever);",
           "# jjp_update=refuse masks JJP's updater on a multi-boot install (it would overwrite image 1)"]
    for d, t, s, r in zip(devices, titles, subtitles, rows):
        out.append("image=%s|%s|%s" % (d, t, s) + "".join("|" + x for x in r[:width]))
    out.append("default=%d" % int(default))
    out.append("timeout=%d" % int(timeout))
    if heading is not None:
        out.append("heading=%s" % mkc.conf_heading(heading))
    if font:
        out.append("font=%s" % font)
    if sound_move:
        out.append("sound_move=%s" % sound_move)
    if sound_confirm:
        out.append("sound_confirm=%s" % sound_confirm)
    out.append("volume=%d" % volume)
    out.append("volume_max=%d" % VOLUME_MAX)
    if media_dir:
        out.append("media=%s" % media_dir)
    elif any_media or sound_move or sound_confirm:
        out.append("media=%s" % MEDIA_DIR)
    if theme:
        out.append("theme=%s" % theme)
    for role in mkc.boot_themes()["roles"]:
        if role in colors:
            out.append("color_%s=%s" % (role, colors[role]))
    out.append("jjp_update=%s" % jjp_update)
    if debug_log:
        out.append("# log: the selector's own diagnostics on the machine - one file per boot plus the")
        out.append("# previous one, 1 MB each; JJP's Utilities log dump copies /jjpe/temp/*.log* to a")
        out.append("# stick (the hook's one-line-per-boot /jjpe/temp/padselect.log is always written)")
        out.append("log=%s" % JJP_CARD_LOG)
    for line in out:
        if len(line) > mkc.CONF_LINE_MAX:
            raise Refused("images.conf: a line is %d characters; the selector reads at most %d: %r"
                          % (len(line), mkc.CONF_LINE_MAX, line[:80] + "..."))
    return "\n".join(out) + "\n"


def parse_images_conf(text):
    """-> {'images': [(device, title, subtitle)], 'media': [(art, anim, music, confirm)], the keys}."""
    out = {"images": [], "media": [], "default": None, "timeout": None, "heading": None, "font": None,
           "sound_move": None, "sound_confirm": None, "volume": None, "volume_max": None, "media_dir": None,
           "theme": None, "colors": {}, "jjp_update": None, "log": None}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key == "image":
            f = val.split("|")
            if len(f) < 3:
                raise Refused("images.conf: image line needs device|title|subtitle: %r" % line)
            if len(f) > 3 + len(mkc.MEDIA_ROW):
                raise Refused("images.conf: image line has %d fields (at most %d): %r" % (len(f), 3 + len(mkc.MEDIA_ROW), line))
            parse_device(f[0])
            out["images"].append((f[0], f[1], f[2]))
            m = tuple(f[3:]) + ("",) * (len(mkc.MEDIA_ROW) - len(f[3:]))
            out["media"].append(m)
        elif key in ("default", "timeout", "volume", "volume_max"):
            try:
                out[key] = int(val.strip())
            except ValueError:
                raise Refused("images.conf: bad %s=%r" % (key, val))
        elif key == "media":
            out["media_dir"] = val.strip()
        elif key.startswith("color_"):
            out["colors"][key[6:]] = val.strip()
        elif key in ("heading", "font", "sound_move", "sound_confirm", "theme", "jjp_update", "log"):
            out[key] = val
    if not out["images"]:
        raise Refused("images.conf: no image= lines")
    return out


def conf_for_args(devices, args, existing=None, media=None, default_titles=None, font=True):
    """images.conf text: --conf verbatim, else from the flags, falling back to an existing
    conf's values (an inject), then to the defaults."""
    if getattr(args, "conf", None):
        with open(args.conf, "r", encoding="utf-8") as f:
            text = f.read()
        parsed = parse_images_conf(text)
        devs = [d for (d, _t, _s) in parsed["images"]]
        if devs != list(devices):
            raise Refused("--conf %s lists %r but the install holds %r" % (args.conf, devs, list(devices)))
        return text
    ex = existing or {"images": [], "media": [], "default": None, "timeout": None, "heading": None,
                      "font": None, "sound_move": None, "sound_confirm": None, "volume": None,
                      "theme": None, "colors": {}, "jjp_update": None}
    n = len(devices)
    same_n = len(ex["images"]) == n
    titles = split_list(getattr(args, "titles", None))
    subtitles = split_list(getattr(args, "subtitles", None))
    if not titles:
        titles = [t for (_d, t, _s) in ex["images"]][:n] if same_n else list(default_titles or [])
    if not subtitles:
        subtitles = [s for (_d, _t, s) in ex["images"]][:n] if same_n else []
    default = args.default if getattr(args, "default", None) is not None else (ex["default"] if ex["default"] is not None else 0)
    timeout = args.timeout if getattr(args, "timeout", None) is not None else (ex["timeout"] if ex["timeout"] is not None else 15)
    if media is not None:
        rows, move, confirm, volume = media["rows"], media["sound_move"], media["sound_confirm"], media["volume"]
    else:
        rows = list(ex.get("media") or [])[:n] if same_n else []
        move, confirm, volume = ex.get("sound_move"), ex.get("sound_confirm"), ex.get("volume")
    if getattr(args, "volume", None) is not None:
        volume = args.volume
    elif volume is not None and int(volume) > VOLUME_MAX:
        # an install or a media set from before the cap (item 120): brought down, out loud
        say("note: volume=%s from the existing menu is above the JJP cap; %d is written" % (volume, VOLUME_MAX))
        volume = VOLUME_MAX
    theme = mkc.check_theme(getattr(args, "theme", None))
    colors = mkc.check_colors(mkc.parse_color_flags(getattr(args, "color", None)))
    if theme is None:
        theme = ex.get("theme")
        if theme and theme != mkc.CUSTOM_THEME and theme not in mkc.theme_names():
            say("note: the install's theme=%s is not a theme this build knows; the default is written" % theme)
            theme = None
        if not colors:
            colors = dict(ex.get("colors") or {})
    heading = getattr(args, "heading", None)
    if heading is None:
        heading = ex.get("heading")
    policy = getattr(args, "jjp_update", None) or ex.get("jjp_update") or "refuse"
    return render_images_conf(devices, titles, subtitles, default, timeout,
                              PADSELECT_DIR + "/font.ttf" if font else None, rows, move, confirm, volume,
                              theme=theme, colors=colors, heading=heading, jjp_update=policy,
                              debug_log=bool(getattr(args, "debug_log", False)))


# ============================================================================= the installer
def patch_installer(text):
    """JJP's jjp_install.sh -> /jjp/pad_install.sh: root B checked and restored from the sda5
    pieces.  The anchors must be exactly one line each; already-patched text comes back as is."""
    lines = text.split("\n")
    if any(ln.strip() == RESTORE_B_PAD for ln in lines) and not any(ln.strip() == RESTORE_B_STOCK for ln in lines):
        return text
    checks = [i for i, ln in enumerate(lines) if ln.strip() == CHECK_ROOT_LINE]
    restores = [i for i, ln in enumerate(lines) if ln.strip() == RESTORE_B_STOCK]
    if len(checks) != 1 or len(restores) != 1:
        raise Refused("jjp_install.sh: expected exactly one %r line and one %r line (found %d and %d) - "
                      "an installer this tool does not know is not edited blind"
                      % (CHECK_ROOT_LINE, RESTORE_B_STOCK, len(checks), len(restores)))
    indent = lines[checks[0]][:len(lines[checks[0]]) - len(lines[checks[0]].lstrip())]
    lines.insert(checks[0] + 1, indent + CHECK_ROOTB_LINE)
    r = restores[0] + 1
    ind = lines[r][:len(lines[r]) - len(lines[r].lstrip())]
    lines[r] = ind + RESTORE_B_PAD
    at = 1 if lines and lines[0].startswith("#!") else 0
    return "\n".join(lines[:at] + PAD_HEADER + lines[at:])


def installer_diff(stock, patched):
    return list(difflib.unified_diff(stock.splitlines(), patched.splitlines(), "jjp/bin/jjp_install.sh",
                                     "jjp/pad_install.sh", lineterm="", n=0))


def patch_cfg(text):
    """A boot config with ocs_live_run= pointed at the copy on the stick (idempotent)."""
    if OCS_STOCK not in text:
        if OCS_PAD in text:
            return text
        raise Refused("boot config: no %s line to redirect" % OCS_STOCK)
    return text.replace(OCS_STOCK, OCS_PAD)


def unsquash_installer(squashfs, dest_dir):
    """The stock installer out of the live squashfs -> its text.  unsquashfs
    where squashfs-tools is installed; a read-only loop mount of the squashfs
    otherwise - root, which a build is anyway - because the app's own runtime
    distro (PAD-Runtime) ships no squashfs-tools and every JJP install ISO's
    live system is a squashfs the kernel can mount."""
    p = os.path.join(dest_dir, SQ_INSTALLER)
    if shutil.which("unsquashfs"):
        _run(["unsquashfs", "-q", "-n", "-f", "-d", dest_dir, squashfs, SQ_INSTALLER])
    elif is_root() and shutil.which("mount"):
        mnt = tempfile.mkdtemp(prefix="mkjjpmulti_sq_")
        try:
            _run(["mount", "-t", "squashfs", "-o", "loop,ro", squashfs, mnt])
            try:
                src = os.path.join(mnt, SQ_INSTALLER)
                if not os.path.isfile(src):
                    raise Refused("%s carries no /%s" % (squashfs, SQ_INSTALLER))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                shutil.copyfile(src, p)
            finally:
                subprocess.run(["umount", mnt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                os.rmdir(mnt)
            except OSError:
                pass
    else:
        raise Refused("no unsquashfs (apt-get install squashfs-tools) and not root, so %s cannot be "
                      "read out of %s" % (SQ_INSTALLER, squashfs))
    if not os.path.isfile(p):
        raise Refused("%s carries no /%s" % (squashfs, SQ_INSTALLER))
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ============================================================================= staging
class LoopRW:
    """A raw ext4 file attached to a loop device and mounted rw for a `with` block (root)."""

    def __init__(self, raw):
        self.raw = raw
        self.loop = self.mnt = None

    def __enter__(self):
        require_root("staging into the root image")
        need_tools("losetup", "mount", "umount")
        out = _run(["losetup", "--find", "--show", self.raw]).strip().splitlines()
        self.loop = out[-1]
        self.mnt = tempfile.mkdtemp(prefix=MOUNT_PREFIX)
        try:
            _run(["mount", "-t", "ext4", "-o", "rw,noatime", self.loop, self.mnt])
        except Refused:
            self._detach()
            raise
        return self.mnt

    def _detach(self):
        problems = []
        if self.mnt and os.path.ismount(self.mnt):
            syncfs(self.mnt)
            for attempt in range(6):
                r = subprocess.run(["umount", self.mnt], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if r.returncode == 0:
                    break
                time.sleep(0.5 * (attempt + 1))
            else:
                problems.append("umount %s: %s" % (self.mnt, r.stdout.decode("utf-8", "replace").strip()))
        if self.mnt:
            try:
                os.rmdir(self.mnt)
            except OSError:
                pass
        if self.loop:
            r = subprocess.run(["losetup", "-d", self.loop], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            msg = r.stdout.decode("utf-8", "replace").strip()
            if r.returncode != 0 and "no such device" not in msg.lower():
                problems.append("losetup -d %s: %s" % (self.loop, msg))
        syncfs(os.path.dirname(os.path.abspath(self.raw)) or ".")
        return problems

    def __exit__(self, *exc):
        problems = self._detach()
        if problems:
            raise Refused("releasing %s: %s" % (self.raw, "; ".join(problems)))
        return False


def e2fsck(raw):
    """e2fsck -fy: 0 clean, 1/2 repaired; anything else is a refusal."""
    r = subprocess.run(["e2fsck", "-fy", raw], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode not in (0, 1, 2):
        raise Refused("e2fsck -fy %s: rc=%d\n%s" % (raw, r.returncode, r.stdout.decode("utf-8", "replace")[-1000:]))
    return r.returncode


def selector_paths(selector_dir):
    """{name: path} for jjpselect / padselect.sh / font.ttf: a FLAT directory holding the three,
    or a `make install PLATFORM=jjp DESTDIR=X` tree (X/jjpe/gen1/padselect/{jjpselect,font.ttf}
    + X/jjpe/gen1/scripts/padselect.sh) - the card's own layout."""
    tree = os.path.join(selector_dir or "", "jjpe", "gen1")
    if os.path.isfile(os.path.join(tree, "padselect", "jjpselect")):
        return {"jjpselect": os.path.join(tree, "padselect", "jjpselect"),
                "padselect.sh": os.path.join(tree, "scripts", "padselect.sh"),
                "font.ttf": os.path.join(tree, "padselect", "font.ttf")}
    return {n: os.path.join(selector_dir or "", n) for n in SELECTOR_FILES}


def selector_font(selector_dir):
    p = selector_paths(selector_dir)["font.ttf"]
    if os.path.isfile(p):
        return p
    if os.path.isfile(mkc.HOST_FONT):
        return mkc.HOST_FONT
    return None


def check_selector_dir(selector_dir):
    if not selector_dir or not os.path.isdir(selector_dir):
        raise Refused("--selector-dir %s is not a directory (make install PLATFORM=jjp DESTDIR=... in "
                      "tools/spike2_emu/codeselect, or a flat directory with jjpselect + padselect.sh)" % selector_dir)
    paths = selector_paths(selector_dir)
    for name, (_mode, required) in SELECTOR_FILES.items():
        if required and not os.path.isfile(paths[name]):
            raise Refused("--selector-dir %s has no %s" % (selector_dir, name))
    if selector_font(selector_dir) is None:
        raise Refused("--selector-dir %s has no font.ttf and %s is not on this host: the selector needs a font"
                      % (selector_dir, mkc.HOST_FONT))


def _put(src_or_bytes, dest, mode, staged, iso_path):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if isinstance(src_or_bytes, bytes):
        with open(dest, "wb") as f:
            f.write(src_or_bytes)
    else:
        shutil.copyfile(src_or_bytes, dest)
    os.chmod(dest, mode)
    try:
        os.chown(dest, 0, 0)
    except (OSError, AttributeError):
        pass
    staged[iso_path] = sha256_file(dest)


def stage_into_root(raw, selector_dir, conf_text, media, sidecars, meter=None):
    """The menu into a root image: PADSELECT_DIR rebuilt from scratch (selector, font, conf,
    sidecars, media), the hook under scripts/, rungame.sh hooked; e2fsck after.  -> the
    OrderedDict of every file written {path in the root: sha256} (verify's oracle)."""
    staged = collections.OrderedDict()
    with LoopRW(raw) as mnt:
        d = mnt + PADSELECT_DIR
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
        os.chmod(d, 0o755)
        _put(selector_paths(selector_dir)["jjpselect"], d + "/jjpselect", 0o755, staged, PADSELECT_DIR + "/jjpselect")
        _put(selector_font(selector_dir), d + "/font.ttf", 0o644, staged, PADSELECT_DIR + "/font.ttf")
        _put(conf_text.encode("utf-8"), d + "/images.conf", 0o644, staged, PADSELECT_DIR + "/images.conf")
        for name, data in (sidecars or {}).items():
            if data is None:
                continue
            _put(data if isinstance(data, bytes) else data.encode("utf-8"), d + "/" + name, 0o644, staged,
                 PADSELECT_DIR + "/" + name)
        if media is not None and media["files"]:
            os.makedirs(d + "/media")
            os.chmod(d + "/media", 0o755)
            done = 0
            for name, src in media["files"].items():
                _put(src, d + "/media/" + name, 0o644, staged, MEDIA_DIR + "/" + name)
                done += os.path.getsize(src)
                if meter is not None:
                    meter.sample(done)
        _put(selector_paths(selector_dir)["padselect.sh"], mnt + HOOK_PATH, 0o755, staged, HOOK_PATH)
        rg = mnt + RUNGAME
        if not os.path.isfile(rg):
            raise Refused("%s: no %s in this root" % (raw, RUNGAME))
        with open(rg, "r", encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        hooked = hook_rungame(text)
        if hooked != text:
            mode = os.stat(rg).st_mode & 0o7777
            with open(rg, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(hooked)
            os.chmod(rg, mode)
        staged[RUNGAME] = sha256_file(rg)
        syncfs(mnt)
    rc = e2fsck(raw)
    say("staged %d file(s) into %s (e2fsck rc %d)" % (len(staged), os.path.basename(raw), rc))
    return staged


def unstage_root(raw):
    """The menu taken back out (the selftest's check that strip_hook and the layout agree)."""
    with LoopRW(raw) as mnt:
        for p in (mnt + PADSELECT_DIR,):
            if os.path.isdir(p):
                shutil.rmtree(p)
        for p in (mnt + HOOK_PATH,):
            if os.path.isfile(p):
                os.unlink(p)
        rg = mnt + RUNGAME
        with open(rg, "r", encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        with open(rg, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(strip_hook(text))
        syncfs(mnt)
    e2fsck(raw)


# ============================================================================= partclone
def partclone_root(raw, chunks_dir, split_size, meter=None, budget=None):
    """partclone.ext4 -c | pigz --fast -b 1024 --rsyncable | split: the app's own recipe for a
    modified JJP root (the flags JJP's Clonezilla used).  -> the chunk paths in order."""
    need_tools("partclone.ext4", "split")
    comp = "pigz -c --fast -b 1024 --rsyncable" if shutil.which("pigz") else "gzip -c --fast --rsyncable"
    if os.path.isdir(chunks_dir):
        shutil.rmtree(chunks_dir)
    os.makedirs(chunks_dir)
    prefix = os.path.join(chunks_dir, ROOT_PIECE + ".gz.")
    log = os.path.join(chunks_dir, "partclone.log")
    cmd = ('set -o pipefail; partclone.ext4 -c -s "$0" -o - 2>"$1" | %s | split -b %d -a 2 - "$2"'
           % (comp, int(split_size)))
    proc = subprocess.Popen(["bash", "-c", cmd, raw, log, prefix])
    while proc.poll() is None:
        time.sleep(1.0)
        if meter is not None:
            try:
                written = sum(os.path.getsize(os.path.join(chunks_dir, n)) for n in os.listdir(chunks_dir)
                              if n.startswith(ROOT_PIECE))
            except OSError:
                written = 0
            meter.sample(min(written, budget) if budget else written)
    if proc.returncode != 0:
        tail = ""
        if os.path.isfile(log):
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read().replace("\r", "\n")[-1200:]
        raise Refused("partclone.ext4 of %s failed (rc=%d)\n%s" % (raw, proc.returncode, tail))
    chunks = sorted(os.path.join(chunks_dir, n) for n in os.listdir(chunks_dir) if n.startswith(ROOT_PIECE))
    if not chunks:
        raise Refused("partclone.ext4 of %s wrote no pieces" % raw)
    if os.path.isfile(log):
        os.unlink(log)
    return chunks


# ============================================================================= xorriso
def xorriso_build(indev, outdev, removes, find_removes, maps, chmods, meter=None, budget=None):
    """The output ISO = the input ISO with files removed, files/directories mapped in and
    modes set; the boot records replayed when the input has any."""
    need_tools("xorriso")
    # -joliet on: THE LONG-NAME TREE WINDOWS READS.  xorriso writes only Rock
    # Ridge unless told, so rewriting a stock JJP ISO (which carries Joliet)
    # dropped it, and Windows then showed the plain ISO 9660 names -
    # sda3.ext4-ptcl-img.gz.aa as SDA3_EXT4_PTCL_IMG_GZ.AA.  The app's stick
    # maker copies what Windows shows, so the GNR multi-boot stick carried names
    # JJP's installer never finds (item 119, 2026-09-13).
    argv = ["xorriso", "-report_about", "UPDATE", "-indev", indev, "-outdev", outdev,
            "-joliet", "on"]
    if iso_has_boot(indev):
        argv += ["-boot_image", "any", "replay"]
    for path in removes:
        argv += ["-rm_r", path, "--"]
    for (where, pattern) in find_removes:
        argv += ["-find", where, "-name", pattern, "-exec", "rm", "--"]
    for src, dst in maps:
        argv += ["-map", src, dst]
    for mode, path in chmods:
        argv += ["-chmod", mode, path, "--"]
    argv += ["-end"]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = collections.deque(maxlen=60)
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if not line:
            continue
        lines.append(line)
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        if m and meter is not None and budget:
            meter.sample(int(float(m.group(1)) / 100.0 * budget))
    rc = proc.wait()
    bad = [ln for ln in lines if re.search(r"FAILURE|SORRY|FATAL|ABORT", ln)]
    if rc != 0 or bad:
        raise Refused("xorriso failed (rc=%d):\n%s" % (rc, "\n".join(list(lines)[-25:])))
    if not os.path.isfile(outdev):
        raise Refused("xorriso wrote no %s" % outdev)


# ============================================================================= build.json
def build_manifest(conf, sources, infos, idents, staged=None, split_size=None, installer=None, written=None,
                   existing=None):
    """build.json: the menu, where each image came from and what game code it was."""
    prev = {}
    for im in (existing or {}).get("images") or []:
        if isinstance(im, dict) and im.get("device"):
            prev[im["device"]] = im
    rows = []
    for i, (dev, title, sub) in enumerate(conf["images"]):
        art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else mkc.MEDIA_ROW
        old = prev.get(dev) or {}
        src = sources[i] if i < len(sources) and sources[i] else old.get("source")
        info = infos[i] if i < len(infos) and infos[i] is not None else None
        ident = idents[i] if i < len(idents) and idents[i] is not None else None
        rows.append(collections.OrderedDict([
            ("device", dev), ("source", os.path.abspath(src) if src and info is not None else src),
            ("title", title), ("subtitle", sub),
            ("art", art or None), ("anim", anim or None), ("music", music or None), ("confirm", confirm or None),
            ("name", (info.name if info else None) or old.get("name")),
            ("game_title", (info.title if info else None) or old.get("game_title")),
            ("game_version", (info.game_version if info else None) or old.get("game_version")),
            ("gamename", (ident or {}).get("gamename") or old.get("gamename")),
            ("game_sha256", (ident or {}).get("game_sha256") or old.get("game_sha256")),
            ("fldat_sha256", (ident or {}).get("fldat_sha256") or old.get("fldat_sha256")),
            ("used_bytes", (ident or {}).get("used_bytes") if ident else old.get("used_bytes")),
            ("pieces", len(info.pieces.get(ROOT_PART, [])) if info else old.get("pieces")),
            ("pieces_bytes", info.piece_bytes(ROOT_PART) if info else old.get("pieces_bytes"))]))
    out = collections.OrderedDict([
        ("tool", TOOL), ("version", VERSION),
        ("written", written or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ("layout", "jjp-ab"),
        ("images", rows),
        ("timeout", conf["timeout"]), ("default", conf["default"]), ("volume", conf["volume"]),
        ("sound_move", conf["sound_move"]), ("sound_confirm", conf["sound_confirm"]),
        ("heading", conf.get("heading")), ("theme", conf.get("theme")), ("colors", dict(conf.get("colors") or {})),
        ("jjp_update", conf.get("jjp_update")),
        ("split_size", split_size if split_size is not None else (existing or {}).get("split_size")),
        ("installer", installer if installer is not None else (existing or {}).get("installer"))])
    if staged is not None:
        out["staged"] = collections.OrderedDict(staged)
    return out


def parse_manifest(raw, what, warnings=None):
    if raw is None:
        return None
    try:
        v = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except ValueError as e:
        (warnings if warnings is not None else []).append("%s: not JSON (%s)" % (what, e))
        return None
    return v if isinstance(v, dict) else None


# ============================================================================= gate + plan
def version_rows(infos, idents):
    rows = []
    for i, (info, ident) in enumerate(zip(infos, idents)):
        rows.append(collections.OrderedDict([
            ("index", i), ("device", DEVICES[i] if i < len(DEVICES) else "rootB:img%d" % i),
            ("iso", info.path if info else None),
            ("name", info.name if info else None), ("title", info.title if info else None),
            ("version", info.game_version if info else None),
            ("gamename", (ident or {}).get("gamename")),
            ("game_sha256", (ident or {}).get("game_sha256")),
            ("fldat_sha256", (ident or {}).get("fldat_sha256")),
            ("used_bytes", (ident or {}).get("used_bytes")),
            ("pieces_bytes", info.piece_bytes(ROOT_PART) if info else None)]))
    return rows


def print_version_table(rows):
    print("== game code versions")
    for r in rows:
        print("version %d %s %s %s %s game=%s fl.dat=%s used=%s" % (
            r["index"], r["device"], r["name"] or "?", r["version"] or "?",
            (r["gamename"] or "?"), (r["game_sha256"] or "?")[:16], (r["fldat_sha256"] or "?")[:16],
            _gb(r["used_bytes"]) if r["used_bytes"] else "?"))


VERSION_COST = ("two roots that are not the same game code share ONE perm partition (settings, audits, "
                "scores): the second version reads what the first wrote, and JJP's own upgrade path "
                "(a settings conversion on first boot) never runs between them")


def check_same_version(infos, idents, allow=False):
    """The gate: Name+Version from the ISOs, GAMENAME, the game and fl.dat shas from the roots."""
    why = []
    base_info, base_id = infos[0], idents[0]
    for i in range(1, len(infos)):
        info, ident = infos[i], idents[i]
        if (info.name, info.game_version) != (base_info.name, base_info.game_version):
            why.append("image %d is %s %s, image 0 is %s %s (version_info.txt)"
                       % (i, info.name, info.game_version, base_info.name, base_info.game_version))
        if ident and base_id:
            if ident["gamename"] != base_id["gamename"]:
                why.append("image %d's GAMENAME is %s, image 0's %s" % (i, ident["gamename"], base_id["gamename"]))
            if ident["game_sha256"] != base_id["game_sha256"]:
                why.append("image %d's game binary differs from image 0's (%s vs %s)"
                           % (i, ident["game_sha256"][:12], base_id["game_sha256"][:12]))
            if ident["fldat_sha256"] != base_id["fldat_sha256"]:
                why.append("image %d's fl.dat differs from image 0's (%s vs %s)"
                           % (i, (ident["fldat_sha256"] or "none")[:12], (base_id["fldat_sha256"] or "none")[:12]))
    if why:
        msg = "the images are not the same game code: " + "; ".join(why) + ". " + VERSION_COST
        if not allow:
            raise Refused(msg + ". Pass --allow-version-mismatch to build it anyway")
        say("WARNING: " + msg + " (--allow-version-mismatch given)")
    return why


def make_plan(primary, extras, media_dir=None, cache_dir=None):
    if len(extras) != 1:
        raise Refused("a JJP multi-boot install holds exactly TWO images (root A and root B); got %d extra(s)"
                      % len(extras))
    infos = [iso_info(p) for p in [primary] + list(extras)]
    for info in infos:
        info.check_stock_shape()
    idents = []
    for p in [primary] + list(extras):
        # the rig's restores are root's (0400); a plan run as the user (the
        # app's) still plans, it just cannot say what game code the root holds
        raw = cached_root_raw(p, cache_dir)
        ident = None
        if raw and shutil.which("debugfs") and os.access(raw, os.R_OK):
            try:
                ident = root_identity(raw)
            except Refused:
                ident = None
        idents.append(ident)
    media = mkc.plan_media(media_dir, len(infos)) if media_dir else None
    c0 = infos[0].piece_bytes(ROOT_PART)
    c1 = infos[1].piece_bytes(ROOT_PART)
    media_bytes = media["total"] if media else 0
    overhead = infos[0].overhead_bytes() + 2_000_000              # + the installer copy, cfgs, sidecars
    # image 0 is re-imaged: the same content plus the menu, so about the same size
    est0 = int(c0 * 1.01) + media_bytes + 1_000_000
    total = est0 + c1 + overhead
    fits = collections.OrderedDict((k, (total <= v, v - total)) for k, v in USB_SIZES.items())
    return {"infos": infos, "idents": idents, "media": media, "image_bytes": [est0, c1],
            "overhead": overhead, "media_bytes": media_bytes, "total": total, "fits": fits,
            "rows": version_rows(infos, idents)}


def print_plan(plan):
    infos = plan["infos"]
    print("== layout: image 0 -> root A (sda3, re-imaged with the menu), image 1 -> root B (sda5, verbatim)")
    for i, info in enumerate(infos):
        print("image %d %s %s  (%s %s, %d piece(s), %s compressed)"
              % (i, DEVICES[i], os.path.basename(info.path), info.name, info.game_version,
                 len(info.pieces.get(ROOT_PART, [])), _gb(info.piece_bytes(ROOT_PART))))
    print_version_table(plan["rows"])
    print("== bytes on the stick")
    for i, n in enumerate(plan["image_bytes"]):
        print("image-size %d %s %d %s" % (i, DEVICES[i], n, "re-imaged root A + the menu" if i == 0 else "root B, verbatim"))
    print("image-size overhead %d installer live system + EFI/boot/perm pieces + configs" % plan["overhead"])
    if plan["media"]:
        print("media-size %d menu media (%d file(s))" % (plan["media_bytes"], len(plan["media"]["files"])))
    print("iso-size %d estimated multi-boot ISO" % plan["total"])
    best = None
    for k, (ok, spare) in plan["fits"].items():
        print("fits USB %s stick size %d: %s (spare %d)" % (k, USB_SIZES[k], "YES" if ok else "NO", spare))
        if ok and best is None:
            best = k
    print("stick: %s" % (best or "none of %s is big enough" % ", ".join(USB_SIZES)))


# ============================================================================= build
def _budget(infos, cached1, media, used0):
    c0, c1 = infos[0].piece_bytes(ROOT_PART), infos[1].piece_bytes(ROOT_PART)
    restore0 = c0
    restore1 = 0 if cached1 else c1
    copy0 = used0 or int(c0 * 1.4)
    stage = (media["total"] if media else 0) + 1_000_000
    part = int(c0 * 1.02)
    iso = int(c0 * 1.02) + c1 + infos[0].overhead_bytes()
    return {"restore0": restore0, "restore1": restore1, "copy0": copy0, "stage": stage, "partclone": part, "iso": iso}


def build_iso(a):
    require_root("build")
    need_tools("partclone.ext4", "partclone.restore", "gunzip", "split", "e2fsck", "losetup", "mount", "umount",
               "debugfs", "xorriso", "cp")
    primary = os.path.abspath(a.primary)
    extras = [os.path.abspath(e) for e in a.extra]
    if len(extras) != 1:
        raise Refused("a JJP multi-boot install holds exactly TWO images (root A and root B); got %d extra(s)"
                      % len(extras))
    for p in [primary] + extras:
        if not os.path.isfile(p):
            raise Refused("%s does not exist" % p)
    out = os.path.abspath(check_output_path(a.out, [primary] + extras, force=a.force))
    check_selector_dir(a.selector_dir)
    media = mkc.plan_media(a.media_dir, 2) if a.media_dir else None
    work = os.path.abspath(a.workdir) if a.workdir else os.path.join(os.path.dirname(out), ".mkjjpmulti_" + os.path.basename(out))
    os.makedirs(work, exist_ok=True)
    say("workdir %s" % work)
    t0 = time.time()
    try:
        with IsoMount(primary, os.path.join(work, "iso0")) as m0, IsoMount(extras[0], os.path.join(work, "iso1")) as m1:
            infos = [iso_info(primary, m0), iso_info(extras[0], m1)]
            for i, info in enumerate(infos):
                info.check_stock_shape("image %d" % i)
                if OCS_STOCK not in info.cfg.get(CFG_FILES[0], "") and OCS_PAD not in info.cfg.get(CFG_FILES[0], ""):
                    raise Refused("image %d: %s has no %s line" % (i, CFG_FILES[0], OCS_STOCK))
            cache1 = cached_root_raw(extras[0], a.cache_dir)
            cache0 = cached_root_raw(primary, a.cache_dir)
            b = _budget(infos, cache1 is not None, media, None)
            if cache0 is not None:
                b["restore0"] = 0
            PROGRESS.start(sum(b.values()), "restore")
            # image 1's root: restored only for the gate (its pieces go on the ISO verbatim)
            PROGRESS.step("restore image 1", b["restore1"])
            raw1 = cached_root_raw(extras[0], a.cache_dir, m1, infos[1], PROGRESS)
            id1 = root_identity(raw1)
            # image 0's root: restored into the rig's cache (so the emulator has it too), then a
            # scratch copy of that gets the menu - the cache itself is never written to
            PROGRESS.step("restore image 0", b["restore0"])
            cache0 = cached_root_raw(primary, a.cache_dir, m0, infos[0], PROGRESS)
            work_raw = os.path.join(work, "sda3.raw")
            PROGRESS.step("copy image 0", b["copy0"])
            say("copying the cached root %s -> %s" % (cache0, work_raw))
            sparse_copy(cache0, work_raw, PROGRESS)
            id0 = root_identity(work_raw)
            if id0["padselect_staged"] or id0["rungame_hooked"]:
                say("note: image 0's root already carries a menu (a multi-boot ISO as --primary); it is re-staged")
            rows = version_rows(infos, [id0, id1])
            print_version_table(rows)
            check_same_version(infos, [id0, id1], allow=a.allow_version_mismatch)
            # the menu
            titles = ["%s %s" % (infos[0].title or infos[0].name, infos[0].game_version), default_title(extras[0])]
            conf_text = conf_for_args(DEVICES, a, media=media, default_titles=titles)
            conf = parse_images_conf(conf_text)
            split_size = infos[0].split_size()
            sq_dir = os.path.join(work, "sq")
            stock_installer = unsquash_installer(os.path.join(m0, SQUASHFS.lstrip("/")), sq_dir)
            pad_installer = patch_installer(stock_installer)
            installer_rec = {"stock_sha256": sha256_bytes(stock_installer.encode("utf-8", "surrogateescape")),
                             "pad_sha256": sha256_bytes(pad_installer.encode("utf-8", "surrogateescape")),
                             "diff": installer_diff(stock_installer, pad_installer)}
            man_root = build_manifest(conf, [primary, extras[0]], infos, [id0, id1], split_size=split_size,
                                      installer=installer_rec)
            sidecars = collections.OrderedDict([(mkc.BUILD_MANIFEST, json.dumps(man_root, indent=1) + "\n")])
            if a.media_dir:
                with open(os.path.join(a.media_dir, mkc.MEDIA_MANIFEST), "rb") as f:
                    sidecars[mkc.MEDIA_MANIFEST] = f.read()
            PROGRESS.step("stage", b["stage"])
            staged = stage_into_root(work_raw, a.selector_dir, conf_text, media, sidecars, PROGRESS)
            man_iso = build_manifest(conf, [primary, extras[0]], infos, [id0, id1], staged=staged,
                                     split_size=split_size, installer=installer_rec, written=man_root["written"])
            # image 0's pieces
            PROGRESS.step("partclone image 0", b["partclone"])
            chunks = partclone_root(work_raw, os.path.join(work, "chunks"), split_size, PROGRESS, b["partclone"])
            say("image 0: %d piece(s), %s compressed" % (len(chunks), _gb(sum(os.path.getsize(c) for c in chunks))))
            # what goes on the ISO beside the pieces
            iso_stage = os.path.join(work, "isofiles")
            if os.path.isdir(iso_stage):
                shutil.rmtree(iso_stage)
            os.makedirs(os.path.join(iso_stage, "jjp", "padselect", "media"))
            with open(os.path.join(iso_stage, "jjp", "pad_install.sh"), "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(pad_installer)
            os.chmod(os.path.join(iso_stage, "jjp", "pad_install.sh"), 0o755)
            pad = os.path.join(iso_stage, "jjp", "padselect")
            with open(os.path.join(pad, "images.conf"), "w", encoding="utf-8") as f:
                f.write(conf_text)
            with open(os.path.join(pad, mkc.BUILD_MANIFEST), "w", encoding="utf-8") as f:
                f.write(json.dumps(man_iso, indent=1) + "\n")
            if mkc.MEDIA_MANIFEST in sidecars:
                with open(os.path.join(pad, mkc.MEDIA_MANIFEST), "wb") as f:
                    f.write(sidecars[mkc.MEDIA_MANIFEST])
            for name in ("jjpselect", "padselect.sh"):
                shutil.copyfile(selector_paths(a.selector_dir)[name], os.path.join(pad, name))
                os.chmod(os.path.join(pad, name), 0o755)
            shutil.copyfile(selector_font(a.selector_dir), os.path.join(pad, "font.ttf"))
            if media is not None:
                for name, src in media["files"].items():
                    shutil.copyfile(src, os.path.join(pad, "media", name))
            cfg_dir = os.path.join(iso_stage, "cfg")
            maps = []
            for p in CFG_FILES:
                if p not in infos[0].cfg:
                    raise Refused("image 0 has no %s" % p)
                dst = os.path.join(cfg_dir, p.lstrip("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w", encoding="utf-8", errors="surrogateescape") as f:
                    f.write(patch_cfg(infos[0].cfg[p]))
                maps.append((dst, p))
            for c in chunks:
                maps.append((c, PARTIMAG + "/" + os.path.basename(c)))
            for (name, _size) in infos[1].pieces[ROOT_PART]:
                suffix = name.rsplit(".", 1)[-1]
                maps.append((os.path.join(m1, PARTIMAG.lstrip("/"), name), PARTIMAG + "/" + ROOTB_PIECE + ".gz." + suffix))
            maps.append((os.path.join(iso_stage, "jjp", "pad_install.sh"), PAD_INSTALLER))
            maps.append((pad, ISO_PAD_DIR))
            removes = [p for p in CFG_FILES] + ([PAD_INSTALLER] if infos[0].pad_dir else [])
            if infos[0].pad_dir:
                removes.append(ISO_PAD_DIR)
            find_removes = [(PARTIMAG, ROOT_PIECE + ".gz.*"), (PARTIMAG, ROOTB_PIECE + ".gz.*")]
            PROGRESS.step("write ISO", b["iso"])
            if os.path.exists(out):
                os.unlink(out)
            xorriso_build(primary, out, removes, find_removes, maps, [("0755", PAD_INSTALLER)], PROGRESS, b["iso"])
            PROGRESS.finish()
        size = os.path.getsize(out)
        say("wrote %s: %s in %d s" % (out, _gb(size), int(time.time() - t0)))
        best = next((k for k, v in USB_SIZES.items() if size <= v), None)
        print("iso-size %d written" % size)
        print("stick: %s" % (best or "larger than %s" % list(USB_SIZES)[-1]))
        return 0
    finally:
        if not a.keep_work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


# ============================================================================= inspect
def read_pad_dir(iso, dest):
    """/jjp/padselect off the ISO into dest (no root) -> its local path, or None."""
    files = iso_files(iso)
    if not any(p.startswith(ISO_PAD_DIR + "/") for p, _s in files):
        return None
    iso_extract(iso, [ISO_PAD_DIR], dest)
    return os.path.join(dest, ISO_PAD_DIR.lstrip("/"))


def inspect_iso(iso, media_out=None):
    iso = os.path.abspath(iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    warnings = []
    tmp = tempfile.mkdtemp(prefix="mkjjpmulti_inspect_")
    try:
        pad = read_pad_dir(iso, tmp)
        if pad is None:
            raise Refused("%s carries no %s - not a multi-boot install ISO this tool wrote" % (iso, ISO_PAD_DIR))
        cp = os.path.join(pad, "images.conf")
        if not os.path.isfile(cp):
            raise Refused("%s: %s holds no images.conf" % (iso, ISO_PAD_DIR))
        with open(cp, "r", encoding="utf-8") as f:
            conf_text = f.read()
        conf = parse_images_conf(conf_text)
        bp = os.path.join(pad, mkc.BUILD_MANIFEST)
        build = parse_manifest(open(bp, "rb").read(), mkc.BUILD_MANIFEST, warnings) if os.path.isfile(bp) else None
        mp = os.path.join(pad, mkc.MEDIA_MANIFEST)
        media_man = parse_manifest(open(mp, "rb").read(), mkc.MEDIA_MANIFEST, warnings) if os.path.isfile(mp) else None
        if build is None:
            warnings.append("no %s on this ISO: the images' source ISOs are unknown" % mkc.BUILD_MANIFEST)
        info = iso_info(iso)
        prev = {im["device"]: im for im in ((build or {}).get("images") or []) if isinstance(im, dict) and im.get("device")}
        mrows = (media_man or {}).get("images") or []
        images = []
        for i, (dev, title, sub) in enumerate(conf["images"]):
            art, anim, music, confirm = conf["media"][i] if i < len(conf["media"]) else mkc.MEDIA_ROW
            b = prev.get(dev) or {}
            m = mrows[i] if i < len(mrows) and isinstance(mrows[i], dict) else {}
            src = b.get("source")
            if src and not os.path.isfile(src):
                warnings.append("image %d: its source %s is not on this machine" % (i, src))
            images.append(collections.OrderedDict([
                ("index", i), ("device", dev), ("title", title), ("subtitle", sub),
                ("art", art or None), ("anim", anim or None), ("music", music or None), ("confirm", confirm or None),
                ("art_source", m.get("art_source")), ("anim_source", m.get("anim_source")),
                ("music_source", m.get("music_source")), ("confirm_source", m.get("confirm_source")),
                ("source", src), ("source_exists", bool(src) and os.path.isfile(src)),
                ("name", b.get("name")), ("game_version", b.get("game_version")), ("gamename", b.get("gamename")),
                ("game_sha256", b.get("game_sha256")), ("used_bytes", b.get("used_bytes")),
                ("pieces", len(info.pieces.get(ROOT_PART if i == 0 else ROOTB_PART, []))),
                ("pieces_bytes", info.piece_bytes(ROOT_PART if i == 0 else ROOTB_PART))]))
        media_dir = os.path.join(pad, "media")
        media_files = sorted(os.listdir(media_dir)) if os.path.isdir(media_dir) else []
        cfg_ok = all(OCS_PAD in info.cfg.get(p, "") for p in CFG_FILES)
        report = collections.OrderedDict([
            ("iso", iso), ("size", os.path.getsize(iso)), ("tool", (build or {}).get("tool")),
            ("tool_version", (build or {}).get("version")), ("written", (build or {}).get("written")),
            ("layout", (build or {}).get("layout") or "jjp-ab"),
            ("game", collections.OrderedDict([("name", info.name), ("title", info.title), ("version", info.game_version)])),
            ("installer_redirected", cfg_ok),
            ("images", images),
            ("timeout", conf["timeout"]), ("default", conf["default"]), ("heading", conf.get("heading")),
            ("volume", conf["volume"]), ("sound_move", conf["sound_move"]), ("sound_confirm", conf["sound_confirm"]),
            ("theme", conf.get("theme")), ("colors", conf.get("colors") or {}), ("jjp_update", conf.get("jjp_update")),
            ("log", conf.get("log")), ("media_files", media_files),
            ("media", media_man), ("warnings", warnings)])
        if media_out:
            os.makedirs(media_out, exist_ok=True)
            for n in media_files:
                shutil.copyfile(os.path.join(media_dir, n), os.path.join(media_out, n))
            if os.path.isfile(mp):
                shutil.copyfile(mp, os.path.join(media_out, mkc.MEDIA_MANIFEST))
            report["media_out"] = os.path.abspath(media_out)
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def print_inspect(rep):
    print("== %s (%s)" % (rep["iso"], _gb(rep["size"])))
    print("game: %s %s (%s); written by %s %s at %s; installer redirected: %s"
          % (rep["game"]["name"], rep["game"]["version"], rep["game"]["title"], rep["tool"] or "?",
             rep["tool_version"] or "?", rep["written"] or "?", "yes" if rep["installer_redirected"] else "NO"))
    for im in rep["images"]:
        print("image %d %s '%s' '%s' art=%s anim=%s music=%s confirm=%s  %d piece(s) %s  source=%s%s"
              % (im["index"], im["device"], im["title"], im["subtitle"], im["art"], im["anim"], im["music"],
                 im["confirm"], im["pieces"], _gb(im["pieces_bytes"]), im["source"],
                 "" if im["source_exists"] else " (missing)"))
    print("default=%s timeout=%s heading=%s volume=%s theme=%s jjp_update=%s log=%s"
          % (rep["default"], rep["timeout"], rep["heading"], rep["volume"], rep["theme"], rep["jjp_update"],
             rep["log"] or "off"))
    print("media: %s" % (", ".join(rep["media_files"]) or "none"))
    for w in rep["warnings"]:
        print("warning: %s" % w)


# ============================================================================= verify
def verify_iso(iso, primary=None, extra=None, quick=False, workdir=None):
    require_root("verify")
    need_tools("mount", "umount", "gunzip", "debugfs", "xorriso")
    iso = os.path.abspath(iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    work = os.path.abspath(workdir) if workdir else os.path.join(os.path.dirname(iso), ".mkjjpmulti_verify_" + os.path.basename(iso))
    os.makedirs(work, exist_ok=True)
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print("%s: %s%s" % ("ok" if ok else "FAIL", name, (" - " + detail) if detail else ""))
        return bool(ok)

    try:
        with IsoMount(iso, os.path.join(work, "iso")) as m:
            info = iso_info(iso, m)
            for p in CFG_FILES:
                t = info.cfg.get(p, "")
                check("%s names the copy on the stick" % p, OCS_PAD in t and OCS_STOCK not in t,
                      "" if OCS_PAD in t else "no %s" % OCS_PAD)
            pad_path = os.path.join(m, PAD_INSTALLER.lstrip("/"))
            if check("%s present" % PAD_INSTALLER, os.path.isfile(pad_path)):
                with open(pad_path, "r", encoding="utf-8", errors="surrogateescape") as f:
                    pad_text = f.read()
                stock = unsquash_installer(os.path.join(m, SQUASHFS.lstrip("/")), os.path.join(work, "sq"))
                expect = patch_installer(stock)
                d = installer_diff(stock, pad_text)
                check("%s is the stick's own installer plus the two root B lines" % PAD_INSTALLER, pad_text == expect,
                      "diff has %d line(s)" % len(d) if pad_text != expect else "%d diff line(s), as recorded" % len(d))
                mode = os.stat(pad_path).st_mode & 0o777
                check("%s mode" % PAD_INSTALLER, mode & 0o111, "mode %o" % mode)
            for part in ("sda1", "sda2", ROOT_PART, "sda4", ROOTB_PART):
                check("%s pieces present" % part, bool(info.pieces.get(part)),
                      "%d piece(s)" % len(info.pieces.get(part, [])))
            # the stick is a FAT32 copy of these files (the app's stick flow), so nothing may reach 4 GiB
            big = [(p, s) for p, s in info.files if s >= (4 << 30)]
            check("every file fits FAT32 (under 4 GiB) for the stick copy", not big,
                  ", ".join(os.path.basename(p) for p, _s in big[:3]))
            # ...and keeps its NAME there: Windows copies the Joliet names
            check("a Joliet tree, so Windows copies the real file names onto the stick",
                  iso_has_joliet(iso) is True)
            pad = os.path.join(m, ISO_PAD_DIR.lstrip("/"))
            conf = build = conf_text = None
            if check("%s on the ISO" % ISO_PAD_DIR, os.path.isdir(pad)):
                cp = os.path.join(pad, "images.conf")
                if check("images.conf on the ISO", os.path.isfile(cp)):
                    with open(cp, "r", encoding="utf-8") as f:
                        conf_text = f.read()
                    try:
                        conf = parse_images_conf(conf_text)
                        check("images.conf parses", True, "%d image(s)" % len(conf["images"]))
                        check("images.conf names rootA then rootB",
                              [d for d, _t, _s in conf["images"]][:2] == list(DEVICES))
                    except Refused as e:
                        check("images.conf parses", False, str(e))
                bp = os.path.join(pad, mkc.BUILD_MANIFEST)
                if check("%s on the ISO" % mkc.BUILD_MANIFEST, os.path.isfile(bp)):
                    build = parse_manifest(open(bp, "rb").read(), mkc.BUILD_MANIFEST)
                    check("%s is this tool's with a staged-file record" % mkc.BUILD_MANIFEST,
                          bool(build) and build.get("tool") == TOOL and isinstance(build.get("staged"), dict))
                    if build:
                        im0 = (build.get("images") or [{}])[0]
                        check("version_info.txt matches image 0's record",
                              (info.name, info.game_version) == (im0.get("name"), im0.get("game_version")),
                              "%s %s" % (info.name, info.game_version))
            if not quick:
                for part in (ROOT_PART, ROOTB_PART, "sda1", "sda2", "sda4"):
                    paths = piece_paths(m, info, part)
                    if not paths:
                        continue
                    r = subprocess.run("cat %s | gunzip -t" % " ".join("'%s'" % p for p in paths), shell=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    check("%s pieces gunzip -t" % part, r.returncode == 0, r.stdout.decode("utf-8", "replace").strip()[-200:])
            if extra:
                with IsoMount(os.path.abspath(extra), os.path.join(work, "iso1")) as m1:
                    info1 = iso_info(extra, m1)
                    src = info1.pieces.get(ROOT_PART, [])
                    dst = info.pieces.get(ROOTB_PART, [])
                    same = [n.rsplit(".", 1)[-1] for n, _s in src] == [n.rsplit(".", 1)[-1] for n, _s in dst] and \
                        [s for _n, s in src] == [s for _n, s in dst]
                    check("sda5 pieces = %s's sda3 pieces (count, suffixes, sizes)" % os.path.basename(extra), same,
                          "%d vs %d" % (len(src), len(dst)))
                    if same and not quick:
                        ok = True
                        for (sn, _ss), (dn, _ds) in zip(src, dst):
                            if sha256_file(os.path.join(m1, PARTIMAG.lstrip("/"), sn)) != sha256_file(os.path.join(m, PARTIMAG.lstrip("/"), dn)):
                                ok = False
                                break
                        check("sda5 pieces byte-identical to image 1's sda3", ok)
            if primary:
                with IsoMount(os.path.abspath(primary), os.path.join(work, "iso0")) as m0:
                    info0 = iso_info(primary, m0)
                    for part in ("sda1", "sda2", "sda4"):
                        a_, b_ = info0.pieces.get(part, []), info.pieces.get(part, [])
                        ok = a_ == b_
                        if ok and not quick:
                            ok = all(sha256_file(os.path.join(m0, PARTIMAG.lstrip("/"), n)) == sha256_file(os.path.join(m, PARTIMAG.lstrip("/"), n))
                                     for n, _s in a_)
                        check("%s pieces untouched from image 0" % part, ok)
                    check("split size kept", info.split_size() == info0.split_size(), "%d" % info.split_size())
            if not quick and build and isinstance(build.get("staged"), dict):
                raw = os.path.join(work, "verify_sda3.raw")
                restore_pieces(piece_paths(m, info, ROOT_PART), raw, None, "verify sda3")
                bad = []
                for path, sha in build["staged"].items():
                    data = debugfs_cat(raw, path)
                    if data is None or sha256_bytes(data) != sha:
                        bad.append(path)
                check("every staged file inside root A matches build.json (%d file(s))" % len(build["staged"]),
                      not bad, ", ".join(bad[:5]))
                rg = (debugfs_cat(raw, RUNGAME) or b"").decode("utf-8", "replace")
                check("rungame.sh carries the hook exactly once", rg.count(HOOK_LINES[2]) == 1)
                ic = debugfs_cat(raw, PADSELECT_DIR + "/images.conf")
                check("images.conf inside root A = the ISO's copy",
                      ic is not None and conf is not None and ic.decode("utf-8", "replace") == conf_text)
                try:
                    ident = root_identity(raw)
                    im0 = (build.get("images") or [{}])[0]
                    check("root A's game binary = image 0's record", ident["game_sha256"] == im0.get("game_sha256"),
                          ident["game_sha256"][:16])
                except Refused as e:
                    check("root A reads as a JJP root", False, str(e))
                os.unlink(raw)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ok = all(r[1] for r in results)
    print("verify: %s (%d check(s), %d failed)" % ("PASS" if ok else "FAIL", len(results), sum(1 for r in results if not r[1])))
    return ok


# ============================================================================= inject
def inject_iso(a):
    require_root("inject")
    need_tools("partclone.ext4", "partclone.restore", "gunzip", "split", "e2fsck", "losetup", "mount", "umount",
               "debugfs", "xorriso")
    iso = os.path.abspath(a.iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    mkc.check_library_path(iso)
    check_selector_dir(a.selector_dir)
    work = os.path.abspath(a.workdir) if a.workdir else os.path.join(os.path.dirname(iso), ".mkjjpmulti_inject_" + os.path.basename(iso))
    os.makedirs(work, exist_ok=True)
    tmp_out = iso + ".inject.tmp"
    t0 = time.time()
    try:
        with IsoMount(iso, os.path.join(work, "iso")) as m:
            info = iso_info(iso, m)
            info.check_stock_shape("the multi-boot ISO")
            if not info.pieces.get(ROOTB_PART) or not info.pad_dir:
                raise Refused("%s is not a multi-boot ISO this tool wrote (no sda5 pieces / no %s)" % (iso, ISO_PAD_DIR))
            pad = os.path.join(m, ISO_PAD_DIR.lstrip("/"))
            with open(os.path.join(pad, "images.conf"), "r", encoding="utf-8") as f:
                old_conf = parse_images_conf(f.read())
            bp = os.path.join(pad, mkc.BUILD_MANIFEST)
            old_build = parse_manifest(open(bp, "rb").read(), mkc.BUILD_MANIFEST) if os.path.isfile(bp) else None
            media = None
            media_dir = a.media_dir
            if media_dir is None and os.path.isdir(os.path.join(pad, "media")) and os.path.isfile(os.path.join(pad, mkc.MEDIA_MANIFEST)):
                media_dir = os.path.join(work, "media_carried")
                if os.path.isdir(media_dir):
                    shutil.rmtree(media_dir)
                shutil.copytree(os.path.join(pad, "media"), media_dir)
                shutil.copyfile(os.path.join(pad, mkc.MEDIA_MANIFEST), os.path.join(media_dir, mkc.MEDIA_MANIFEST))
                say("media: the ISO's own set is carried through")
            if media_dir:
                media = mkc.plan_media(media_dir, 2)
            c0 = info.piece_bytes(ROOT_PART)
            b = {"restore": c0, "stage": (media["total"] if media else 0) + 1_000_000, "partclone": int(c0 * 1.02),
                 "iso": os.path.getsize(iso)}
            PROGRESS.start(sum(b.values()), "restore")
            PROGRESS.step("restore root A", b["restore"])
            work_raw = os.path.join(work, "sda3.raw")
            restore_pieces(piece_paths(m, info, ROOT_PART), work_raw, PROGRESS, "root A")
            id0 = root_identity(work_raw)
            sources = [getattr(a, "primary", None), (a.extra[0] if getattr(a, "extra", None) else None)]
            conf_text = conf_for_args(DEVICES, a, existing=old_conf, media=media,
                                      default_titles=[t for _d, t, _s in old_conf["images"]])
            conf = parse_images_conf(conf_text)
            man_root = build_manifest(conf, sources, [info, None], [id0, None], split_size=info.split_size(),
                                      existing=old_build)
            sidecars = collections.OrderedDict([(mkc.BUILD_MANIFEST, json.dumps(man_root, indent=1) + "\n")])
            if media_dir:
                with open(os.path.join(media_dir, mkc.MEDIA_MANIFEST), "rb") as f:
                    sidecars[mkc.MEDIA_MANIFEST] = f.read()
            PROGRESS.step("stage", b["stage"])
            staged = stage_into_root(work_raw, a.selector_dir, conf_text, media, sidecars, PROGRESS)
            man_iso = build_manifest(conf, sources, [info, None], [id0, None], staged=staged,
                                     split_size=info.split_size(), existing=old_build, written=man_root["written"])
            PROGRESS.step("partclone root A", b["partclone"])
            chunks = partclone_root(work_raw, os.path.join(work, "chunks"), info.split_size(), PROGRESS, b["partclone"])
            newpad = os.path.join(work, "padselect")
            if os.path.isdir(newpad):
                shutil.rmtree(newpad)
            os.makedirs(os.path.join(newpad, "media"))
            with open(os.path.join(newpad, "images.conf"), "w", encoding="utf-8") as f:
                f.write(conf_text)
            with open(os.path.join(newpad, mkc.BUILD_MANIFEST), "w", encoding="utf-8") as f:
                f.write(json.dumps(man_iso, indent=1) + "\n")
            if mkc.MEDIA_MANIFEST in sidecars:
                with open(os.path.join(newpad, mkc.MEDIA_MANIFEST), "wb") as f:
                    f.write(sidecars[mkc.MEDIA_MANIFEST])
            for name in ("jjpselect", "padselect.sh"):
                shutil.copyfile(selector_paths(a.selector_dir)[name], os.path.join(newpad, name))
                os.chmod(os.path.join(newpad, name), 0o755)
            shutil.copyfile(selector_font(a.selector_dir), os.path.join(newpad, "font.ttf"))
            if media is not None:
                for name, src in media["files"].items():
                    shutil.copyfile(src, os.path.join(newpad, "media", name))
            maps = [(c, PARTIMAG + "/" + os.path.basename(c)) for c in chunks] + [(newpad, ISO_PAD_DIR)]
            PROGRESS.step("write ISO", b["iso"])
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)
            xorriso_build(iso, tmp_out, [ISO_PAD_DIR], [(PARTIMAG, ROOT_PIECE + ".gz.*")], maps, [], PROGRESS, b["iso"])
            PROGRESS.finish()
        os.replace(tmp_out, iso)
        say("injected %s: %s in %d s" % (iso, _gb(os.path.getsize(iso)), int(time.time() - t0)))
        return 0
    finally:
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)
        if not a.keep_work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


# ============================================================================= media
def jjp_logo_png(iso, out_png, cache_dir=None, work=None):
    """The image's own plaintext logo (LOGO_PNG) out of its restored root -> out_png."""
    raw = cached_root_raw(iso, cache_dir)
    if raw is None:
        if not is_root():
            raise Refused("%s has no restored root at %s; restore it first (a build, or tools/jjp_emu/mount.sh, "
                          "both under wsl -u root)" % (os.path.basename(iso), cache_base(iso, cache_dir)))
        # the ISO is mounted on the Linux side, never under the media directory
        # (a Windows drive, on the app's runs)
        with IsoMount(iso, tempfile.mkdtemp(prefix="mkjjpmulti_logo_")) as m:
            info = iso_info(iso, m)
            info.check_stock_shape()
            raw = cached_root_raw(iso, cache_dir, m, info)
    data = debugfs_cat(raw, LOGO_PNG)
    if not data or not data.startswith(b"\x89PNG"):
        raise Refused("%s: no plaintext %s in the root" % (os.path.basename(iso), LOGO_PNG))
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with open(out_png, "wb") as f:
        f.write(data)
    return out_png


def cmd_media(a):
    import selectmedia
    images = [os.path.abspath(a.primary)] + [os.path.abspath(e) for e in a.extra]
    n = len(images)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    src_dir = os.path.join(out, ".jjp_src")
    arts = selectmedia.parse_index_spec(a.art, n, "auto")
    anims = selectmedia.parse_index_spec(a.anim, n, "none")
    argv = ["prepare", "--primary", images[0]]
    for e in images[1:]:
        argv += ["--extra", e]
    argv += ["--out", out]
    for i, spec in enumerate(arts):
        if spec == "auto":
            spec = jjp_logo_png(images[i], os.path.join(src_dir, "logo%d.png" % i), a.cache_dir, out)
            say("art %d: auto = %s of %s" % (i, os.path.basename(LOGO_PNG), os.path.basename(images[i])))
        argv += ["--art", "%d=%s" % (i, spec)]
    for i, spec in enumerate(anims):
        if spec.startswith("auto"):
            raise Refused("anim %d: 'auto' has no JJP seam yet (the attract clip sits encrypted in edata); "
                          "give a video file, or none" % i)
        argv += ["--anim", "%d=%s" % (i, spec)]
    for m in a.music:
        argv += ["--music", m]
    argv += ["--sound-move", a.sound_move]
    for s in (a.sound_confirm or ["synth"]):
        argv += ["--sound-confirm", s]
    volume = VOLUME_DEFAULT if a.volume is None else a.volume
    if not 0 <= volume <= VOLUME_MAX:
        raise Refused("--volume %d: a JJP boot menu plays at 0-%d (the machine's amplifiers run at full)"
                      % (volume, VOLUME_MAX))
    argv += ["--volume", str(volume)]
    # every menu sound and music bed levelled to one peak (item 120)
    argv += ["--peak-dbfs", "%g" % MEDIA_PEAK_DBFS]
    if a.size:
        argv += ["--size", a.size]
    if a.visual_only:
        argv += ["--visual-only"]
    if a.work:
        argv += ["--work", a.work]
    return selectmedia.main(argv)


# ============================================================================= selftest
def _write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    os.chmod(path, mode)


FAKE_INSTALLER = """#!/bin/bash
################################################################################
# Copyright (c) 2025 Jersey Jack Pinball
################################################################################
lib_path="/jjp/lib"
medium_path="/lib/live/mount/medium"
function check_image {
    pieces="$medium_path/home/partimag/img/$2.gz.a?"
    cat $pieces | gunzip -t
}
check_image "EFI"  "sda1.vfat-ptcl-img"
check_image "BOOT" "sda2.ext4-ptcl-img"
check_image "ROOT" "sda3.ext4-ptcl-img"
check_image "PERM" "sda4.ext4-ptcl-img"
function restore_partition {
    cat $medium_path/home/partimag/img/$2.gz.a? | gunzip -c | partclone.restore -N -s - -o "$1"
}
restore_partition "$PART_EFI"   "sda1.vfat-ptcl-img" "$FS_UUID_EFI"
restore_partition "$PART_BOOT"  "sda2.ext4-ptcl-img" "$FS_UUID_BOOT"
restore_partition "$PART_ROOTA" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTA"
restore_partition "$PART_ROOTB" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTB"
halt -f
"""

FAKE_RUNGAME = """#!/bin/dash
export JJPEDIR='/jjpe/gen1'
. $JJPEDIR/setenv.sh
export GAMEDIR=$JJPEDIR/$GAMENAME
chmod +x $JJPEDIR/scripts/runonce.sh
$JJPEDIR/scripts/runonce.sh
while true
do
  $GAMEDIR/game
done
"""

FAKE_CFG = ("label Clonezilla live with img\n  kernel /live/vmlinuz\n"
            "  append initrd=/live/initrd.img boot=live ocs_prerun=\"sudo mount --bind /lib/live/mount/medium/home/partimag /home/partimag\" "
            + OCS_STOCK + " ocs_live_batch=yes\n")


def make_fake_iso(work, name, version, game_bytes, edata_bytes, size_mb=64):
    """A synthetic JJP install ISO: a real ext4 root (mke2fs -d) partcloned into sda3 pieces,
    gzip'd fillers for the other partitions, a squashfs with the installer, both cfgs."""
    need_tools("mke2fs", "partclone.ext4", "gzip", "split", "mksquashfs", "xorriso")
    d = os.path.join(work, "fake_" + name.replace(".", "_"))
    if os.path.isdir(d):
        shutil.rmtree(d)
    tree = os.path.join(d, "tree")
    g = os.path.join(tree, "jjpe", "gen1")
    _write(os.path.join(g, "setenv.sh"), "# generated\nexport GAMENAME=GunsNRoses\n", 0o755)
    _write(os.path.join(g, "fl.dat"), b"top-level fl.dat\n")
    _write(os.path.join(g, "scripts", "rungame.sh"), FAKE_RUNGAME, 0o755)
    _write(os.path.join(g, "scripts", "runonce.sh"), "#!/bin/dash\nexit 0\n", 0o755)
    _write(os.path.join(g, "scripts", "updater.sh"), "#!/bin/dash\necho updater\n", 0o755)
    _write(os.path.join(g, "scripts", "fs_uuids.sh"),
           "#!/bin/dash\nFS_UUID_ROOTA=d8223f69-d29a-474f-a837-0a11dccc27f2\n"
           "FS_UUID_ROOTB=e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87\n", 0o755)
    _write(os.path.join(g, "GunsNRoses", "game"), game_bytes, 0o755)
    _write(os.path.join(g, "GunsNRoses", "fl.dat"), b"game fl.dat " + game_bytes[:8] + b"\n")
    _write(os.path.join(g, "GunsNRoses", "edata", "graphics", "Attract Mode", "a.bin"), edata_bytes)
    if os.path.join(CODESELECT, "test") not in sys.path:
        sys.path.insert(0, os.path.join(CODESELECT, "test"))
    import mkmedia
    os.makedirs(os.path.join(g, "miscfiles", "graphics"))
    mkmedia.png_solid(os.path.join(g, "miscfiles", "graphics", "JJP_logo_message.png"), 136, 76, (0x10, 0x20, 0x30))
    raw = os.path.join(d, "sda3.raw")
    with open(raw, "wb") as f:
        f.truncate(size_mb << 20)
    _run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", tree, "-L", "roota", raw])
    iso_dir = os.path.join(d, "iso")
    img = os.path.join(iso_dir, PARTIMAG.lstrip("/"))
    os.makedirs(img)
    _run(["bash", "-c", 'set -o pipefail; partclone.ext4 -c -s "$0" -o - 2>/dev/null | gzip -c --fast | split -b 3000000 -a 2 - "$1"',
          raw, os.path.join(img, ROOT_PIECE + ".gz.")])
    for part, kind in (("sda1", "vfat"), ("sda2", "ext4"), ("sda4", "ext4")):
        _run(["bash", "-c", 'head -c 200000 /dev/urandom | gzip -c > "$0"', os.path.join(img, "%s.%s-ptcl-img.gz.aa" % (part, kind))])
    _write(os.path.join(img, "parts"), "sda1 sda2 sda3 sda4\n")
    _write(os.path.join(img, "Info-img-size.txt"), "Image size (Bytes):\n1.3G\t/home/partimag/img\n")
    _write(os.path.join(iso_dir, "version_info.txt"),
           "################################################################################\n"
           "# Copyright (c) 2025 Jersey Jack Pinball\n"
           "################################################################################\n"
           "Title: Guns N Roses\nName: GunsNRoses\nVersion: %s\nType: iso\nDisksize: 111\nOS: Ubuntu 21.10\n" % version)
    for p in CFG_FILES:
        _write(os.path.join(iso_dir, p.lstrip("/")), FAKE_CFG)
    sq = os.path.join(d, "sq")
    _write(os.path.join(sq, SQ_INSTALLER), FAKE_INSTALLER, 0o755)
    _write(os.path.join(sq, "jjp", "bin", "donglecheck"), "#!/bin/sh\nexit 0\n", 0o755)
    os.makedirs(os.path.join(iso_dir, "live"))
    _run(["mksquashfs", sq, os.path.join(iso_dir, "live", "filesystem.squashfs"), "-no-progress", "-quiet", "-noappend"])
    _write(os.path.join(iso_dir, "live", "vmlinuz"), b"not a kernel\n")
    out = os.path.join(work, name + ".iso")
    if os.path.exists(out):
        os.unlink(out)
    _run(["xorriso", "-report_about", "SORRY", "-outdev", out, "-map", iso_dir, "/", "--", "-end"])
    shutil.rmtree(tree)
    return out, raw


def selftest(root_dir, selector=None):
    require_root("selftest")
    need_tools("partclone.ext4", "partclone.restore", "gunzip", "split", "e2fsck", "losetup", "mount", "umount",
               "debugfs", "xorriso", "unsquashfs", "mksquashfs", "mke2fs")
    work = os.path.abspath(root_dir)
    os.makedirs(work, exist_ok=True)
    cache = os.path.join(work, "cache")
    os.makedirs(cache, exist_ok=True)
    failures = []

    def expect(name, ok, detail=""):
        print("%s: %s%s" % ("ok" if ok else "FAIL", name, (" - " + detail) if detail else ""))
        if not ok:
            failures.append(name)

    game = os.urandom(50000)
    iso0, raw0 = make_fake_iso(work, "fake0-v03.03", "03.03", game, os.urandom(400000))
    iso1, raw1 = make_fake_iso(work, "fake1_custom", "03.03", game, os.urandom(600000))
    iso2, _ = make_fake_iso(work, "fake2-v03.04", "03.04", os.urandom(50000), os.urandom(100000))
    sel = os.path.join(work, "selector")
    if os.path.isdir(sel):
        shutil.rmtree(sel)
    os.makedirs(sel)
    _write(os.path.join(sel, "jjpselect"), selector and open(selector, "rb").read() or b"#!/bin/sh\necho 0 > \"$4\"\n", 0o755)
    shutil.copyfile(os.path.join(CODESELECT, "padselect.sh"), os.path.join(sel, "padselect.sh"))
    os.chmod(os.path.join(sel, "padselect.sh"), 0o755)
    _write(os.path.join(sel, "font.ttf"), b"\x00\x01\x00\x00fake font")
    media = os.path.join(work, "media")
    if os.path.isdir(media):
        shutil.rmtree(media)
    os.makedirs(media)
    subprocess.run([sys.executable, os.path.join(CODESELECT, "test", "mkmedia.py"), "make", media], check=True)
    _write(os.path.join(media, mkc.MEDIA_MANIFEST), json.dumps({
        "images": [{"art": "art0.png", "anim": None, "music": "music0.wav", "confirm": None},
                   {"art": "art1.png", "anim": "anim1.gif", "music": None, "confirm": "confirm1.wav"}],
        "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 40}))
    for n in ("bad.wav",):
        p = os.path.join(media, n)
        if os.path.exists(p):
            os.unlink(p)
    out = os.path.join(work, "multi.iso")
    # the plan (no root needed, but we are root): sizes + fits
    plan = make_plan(iso0, [iso1], media_dir=media, cache_dir=cache)
    print_plan(plan)
    expect("plan fits an 8G stick", plan["fits"]["8G"][0])
    # the build
    ns = argparse.Namespace(primary=iso0, extra=[iso1], out=out, selector_dir=sel, media_dir=media, titles="Stock;Custom",
                            subtitles="a;b", timeout=20, default=1, volume=None, heading="PICK ONE", theme="midnight",
                            color=None, conf=None, debug_log=True, jjp_update="refuse", allow_version_mismatch=False,
                            force=True, workdir=os.path.join(work, "wbuild"), cache_dir=cache, keep_work=False)
    rc = build_iso(ns)
    expect("build returns 0", rc == 0)
    expect("the restore cache holds both roots",
           os.path.isfile(os.path.join(cache_base(iso0, cache), "sda3.raw")) and os.path.isfile(os.path.join(cache_base(iso1, cache), "sda3.raw")))
    rep = inspect_iso(out, media_out=os.path.join(work, "media_out"))
    print_inspect(rep)
    expect("inspect: two images rootA/rootB", [im["device"] for im in rep["images"]] == list(DEVICES))
    expect("inspect: titles/subtitles", [(im["title"], im["subtitle"]) for im in rep["images"]] == [("Stock", "a"), ("Custom", "b")])
    expect("inspect: media rows", rep["images"][1]["anim"] == "anim1.gif" and rep["images"][1]["confirm"] == "confirm1.wav")
    expect("inspect: keys", rep["timeout"] == 20 and rep["default"] == 1 and rep["heading"] == "PICK ONE"
           and rep["theme"] == "midnight" and rep["jjp_update"] == "refuse" and rep["log"] == JJP_CARD_LOG and rep["volume"] == 40)
    expect("inspect: installer redirected", rep["installer_redirected"])
    expect("inspect: sources recorded", rep["images"][0]["source"] == iso0 and rep["images"][1]["source"] == iso1)
    expect("inspect: media extracted", os.path.isfile(os.path.join(work, "media_out", "anim1.gif")))
    ok = verify_iso(out, primary=iso0, extra=iso1, workdir=os.path.join(work, "wverify"))
    expect("verify PASS", ok)
    # the ISO's files: sda5 = fake1's sda3, the installer diff, the cfgs
    info = iso_info(out)
    i1 = iso_info(iso1)
    expect("sda5 pieces are image 1's sda3 pieces", [s for _n, s in info.pieces[ROOTB_PART]] == [s for _n, s in i1.pieces[ROOT_PART]])
    expect("cfgs redirected", all(OCS_PAD in info.cfg[p] and OCS_STOCK not in info.cfg[p] for p in CFG_FILES))
    tmp = os.path.join(work, "x")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    iso_extract(out, [PAD_INSTALLER], tmp)
    with open(os.path.join(tmp, PAD_INSTALLER.lstrip("/")), "r") as f:
        pad = f.read()
    d = [ln for ln in installer_diff(FAKE_INSTALLER, pad) if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    expect("installer diff = header + check + restore (%d lines)" % len(d),
           d == ["+" + x for x in PAD_HEADER] + ["+" + CHECK_ROOTB_LINE, "-" + RESTORE_B_STOCK, "+" + RESTORE_B_PAD], "\n".join(d))
    # the staged root, read back: hook once, files in place
    with IsoMount(out, os.path.join(work, "m")) as m:
        vi = iso_info(out, m)
        raw = os.path.join(work, "check_sda3.raw")
        restore_pieces(piece_paths(m, vi, ROOT_PART), raw)
    rg = (debugfs_cat(raw, RUNGAME) or b"").decode()
    expect("rungame.sh hooked once after runonce", rg.count(HOOK_LINES[2]) == 1 and rg.index(RUNONCE_LINE) < rg.index(HOOK_LINES[2]))
    expect("strip_hook undoes hook_rungame", strip_hook(rg) == FAKE_RUNGAME)
    expect("jjpselect + hook + font + conf + media staged",
           all(debugfs_cat(raw, p) is not None for p in (PADSELECT_DIR + "/jjpselect", HOOK_PATH, PADSELECT_DIR + "/font.ttf",
                                                         PADSELECT_DIR + "/images.conf", MEDIA_DIR + "/anim1.gif",
                                                         PADSELECT_DIR + "/" + mkc.BUILD_MANIFEST)))
    expect("the root's game is untouched", sha256_bytes(debugfs_cat(raw, JJPEDIR + "/GunsNRoses/game")) == sha256_bytes(game))
    os.unlink(raw)
    # inject: new titles, the media carried through, provenance kept
    ns2 = argparse.Namespace(iso=out, selector_dir=sel, media_dir=None, titles="Stock2;Custom2", subtitles=None, timeout=None,
                             default=None, volume=None, heading=None, theme=None, color=None, conf=None, debug_log=False,
                             jjp_update=None, workdir=os.path.join(work, "winject"), keep_work=False, primary=None, extra=None)
    rc = inject_iso(ns2)
    expect("inject returns 0", rc == 0)
    rep2 = inspect_iso(out)
    expect("inject: titles changed, subtitles kept", [(im["title"], im["subtitle"]) for im in rep2["images"]] == [("Stock2", "a"), ("Custom2", "b")])
    expect("inject: media carried", rep2["images"][1]["anim"] == "anim1.gif" and rep2["media_files"] == rep["media_files"])
    expect("inject: provenance carried", rep2["images"][1]["source"] == iso1 and rep2["images"][0]["game_sha256"] == rep["images"][0]["game_sha256"])
    expect("inject: log turned off without --debug-log", rep2["log"] is None)
    ok = verify_iso(out, primary=iso0, extra=iso1, quick=True, workdir=os.path.join(work, "wverify2"))
    expect("verify --quick PASS after inject", ok)
    # the gate
    ns3 = argparse.Namespace(**dict(vars(ns), extra=[iso2], out=os.path.join(work, "multi2.iso"), media_dir=None,
                                    workdir=os.path.join(work, "wbuild2"), allow_version_mismatch=False))
    try:
        build_iso(ns3)
        expect("a different version is refused", False)
    except Refused as e:
        expect("a different version is refused", "not the same game code" in str(e), str(e)[:120])
    ns3.allow_version_mismatch = True
    rc = build_iso(ns3)
    expect("--allow-version-mismatch builds it", rc == 0 and os.path.isfile(ns3.out))
    print("selftest: %s (%d failure(s))" % ("PASS" if not failures else "FAIL", len(failures)))
    for f in failures:
        print("  FAIL " + f)
    return 0 if not failures else 1


# ============================================================================= CLI
def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="a flat directory holding jjpselect, padselect.sh and optionally font.ttf, "
                                          "or a `make install PLATFORM=jjp DESTDIR=X` tree (X/jjpe/gen1/padselect + "
                                          "X/jjpe/gen1/scripts)")
    s.add_argument("--media-dir", help="directory holding media.json (mkjjpmulti.py media / selectmedia.py prepare) and the files it names")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--heading", metavar="TEXT", help="images.conf heading=TEXT (the selector's own '%s' when unset; '' = no line)" % mkc.DEF_HEADING)
    s.add_argument("--default", type=int, help="images.conf default index (default 0)")
    s.add_argument("--volume", type=int, help="images.conf volume 0-%d (default %d; overrides media.json) - a JJP "
                                              "machine's amplifiers run at full while the menu plays"
                                              % (VOLUME_MAX, VOLUME_DEFAULT))
    s.add_argument("--theme", help="the menu's colours: one of codeselect/themes.json's names, or custom")
    s.add_argument("--color", action="append", metavar="ROLE=RRGGBB", help="one colour on top of the theme (repeatable)")
    s.add_argument("--conf", help="use this images.conf verbatim instead of generating one")
    s.add_argument("--jjp-update", choices=JJP_UPDATE_POLICIES, dest="jjp_update",
                   help="images.conf jjp_update=: refuse (default) masks JJP's own updater on the machine - it would "
                        "overwrite image 1 and boot it without the menu; allow leaves it alone")
    # The selector's own log ON THE MACHINE, on by default since 2026-09-14: the GNR's menu
    # came up silent and nothing on the machine could say why.  It is bounded (one file
    # per boot plus the previous one, 1 MB each, ~8 KB a boot) and JJP's own dumplogs.sh
    # copies /jjpe/temp/*.log* onto a stick, so it can be read without opening the machine.
    s.add_argument("--no-machine-log", dest="debug_log", action="store_false", default=True,
                   help="leave the selector's own log (images.conf log=%s, collected by JJP's "
                        "Utilities log dump) off the machine" % JJP_CARD_LOG)
    s.add_argument("--debug-log", dest="debug_log", action="store_true", help=argparse.SUPPRESS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="the version table, byte rows and stick fit; writes nothing")
    s.add_argument("--primary", required=True, help="image 0's install ISO (root A, gets the menu)")
    s.add_argument("--extra", action="append", default=[], metavar="ISO", help="image 1's install ISO (root B, verbatim)")
    s.add_argument("--media-dir")
    s.add_argument("--cache-dir", help="where restored roots are kept (default %s, the rig's)" % CACHE_DIR_DEFAULT)
    s = sub.add_parser("build", help="write the multi-boot install ISO (root)")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[], metavar="ISO")
    s.add_argument("--out", required=True, help="the ISO to write")
    _add_conf_flags(s)
    s.add_argument("--allow-version-mismatch", action="store_true", help="build although the images are not the same game code")
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s.add_argument("--workdir", help="scratch directory (default: beside --out); needs ~2x image 0's root")
    s.add_argument("--cache-dir")
    s.add_argument("--keep-work", action="store_true", help="leave the scratch directory behind")
    s = sub.add_parser("inject", help="redo the menu staging on an existing multi-boot ISO in place (root)")
    s.add_argument("--iso", required=True, help="the multi-boot ISO to modify IN PLACE")
    _add_conf_flags(s)
    s.add_argument("--primary", help="RECORD this path as image 0's source; nothing is read from it")
    s.add_argument("--extra", action="append", default=[], metavar="ISO", help="RECORD this path as image 1's source")
    s.add_argument("--workdir")
    s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("verify", help="check a multi-boot ISO (root)")
    s.add_argument("--iso", required=True)
    s.add_argument("--primary", help="also compare the untouched pieces against image 0's ISO")
    s.add_argument("--extra", action="append", default=[], metavar="ISO", help="also compare sda5 against image 1's sda3")
    s.add_argument("--quick", action="store_true", help="skip gunzip -t, the piece shas and the root restore")
    s.add_argument("--workdir")
    s = sub.add_parser("inspect", help="read a multi-boot ISO back (no root)")
    s.add_argument("--iso", required=True)
    s.add_argument("--json", action="store_true", dest="as_json", help="print ONE JSON object")
    s.add_argument("--media-out", help="also extract the menu media + media.json into this directory")
    s = sub.add_parser("media", help="the media set + media.json through selectmedia.py with JJP's seams")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[], metavar="ISO")
    s.add_argument("--out", required=True)
    s.add_argument("--art", action="append", default=[], metavar="N=auto|none|PATH|VIDEO@T")
    s.add_argument("--anim", action="append", default=[], metavar="N=none|PATH[@START[:SECONDS[:FPS]]]")
    s.add_argument("--music", action="append", default=[], metavar="N=PATH[@SECONDS]|none")
    s.add_argument("--sound-move", default="synth", metavar="PATH|synth|none")
    s.add_argument("--sound-confirm", action="append", default=[], metavar="PATH|synth|none | N=...")
    s.add_argument("--volume", type=int, help="media.json volume 0-%d (default %d)" % (VOLUME_MAX, VOLUME_DEFAULT))
    s.add_argument("--size", help="WxH of the art panel (default: the menu's own for the image count)")
    s.add_argument("--visual-only", action="store_true")
    s.add_argument("--work")
    s.add_argument("--cache-dir")
    s = sub.add_parser("selftest", help="synthetic end-to-end test (root; partclone, xorriso, squashfs-tools, e2fsprogs)")
    s.add_argument("dir")
    s.add_argument("--selector", help="a real jjpselect to stage instead of a stand-in")
    a = ap.parse_args(list(sys.argv[1:]) if argv is None else list(argv))
    try:
        if a.cmd == "plan":
            print_plan(make_plan(a.primary, a.extra, a.media_dir, a.cache_dir))
            return 0
        if a.cmd == "build":
            return build_iso(a)
        if a.cmd == "inject":
            return inject_iso(a)
        if a.cmd == "verify":
            return 0 if verify_iso(a.iso, a.primary, a.extra[0] if a.extra else None, a.quick, a.workdir) else 1
        if a.cmd == "inspect":
            rep = inspect_iso(a.iso, a.media_out)
            if a.as_json:
                print(json.dumps(rep, indent=1))
            else:
                print_inspect(rep)
            return 0
        if a.cmd == "media":
            return cmd_media(a)
        if a.cmd == "selftest":
            return selftest(a.dir, a.selector)
    except Refused as e:
        say("error: %s" % e)
        return 2
    except KeyboardInterrupt:
        say("error: interrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
