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
  mkjjpmulti.py install --iso X.iso --disk /dev/sdX [--yes] [--no-verify] [--workdir DIR]
        the ISO written straight onto a disk - the game's SSD in a dock on this PC - by
        the same steps JJP's installer runs on the machine, READ OUT OF THE ISO'S OWN
        INSTALLER (partition numbers, filesystem UUIDs, the sgdisk template by disk
        size, the size gate, which image lands in which slot, the temp partition); a
        multi-boot ISO's pad_install.sh puts image 1 in root B, a stock ISO's
        jjp_install.sh a copy of root A.  No stick, no live boot, no security key.
        The disk is WIPED (--yes, or the device name typed at a prompt); a disk with
        anything mounted from it is refused.  Then the disk is verified: the table
        sector for sector, every UUID, the menu in root A, the game in both roots,
        grub set to A, the loader on the EFI partition, an empty temp.  A file takes
        `losetup -P --find --show FILE` first; the app attaches a docked SSD with
        `wsl --mount` of its PhysicalDrive path, `--bare`, and passes the /dev/sdX that appears.
        The table is written from the template by this tool, not by sgdisk: gdisk ends
        every write with the global sync() that hangs under WSL2 (2026-09-13, 2026-09-15).
        Two partial writes onto a disk that ALREADY holds this ISO's install (the slots and
        UUIDs are checked first; the games, settings and scores stay):
          --menu-only            the ISO's menu into root A (inject the ISO first for a new
                                 title, clip or conf): two minutes, nothing else touched
          --image N --from Y.iso image N's root (0 = A, the menu re-staged on top; 1 = B)
                                 restored from Y's own sda3 pieces - a new custom code in
                                 slot B without a reinstall; the same-version gate holds
                                 against the OTHER root on the disk (one settings partition)
  mkjjpmulti.py selftest DIR
        two synthetic JJP ISOs (root: mke2fs -d, partclone, mksquashfs, xorriso) ->
        build -> verify -> inspect -> inject -> the mismatch refusal -> install onto a
        120 GB sparse file on a loop device (+ the in-use and too-small refusals); in DIR

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
import uuid
import zlib

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
#: the SECOND patch of rungame.sh: the game exits 68 / 69 after a fresh install (a
#: maintenance reboot) and rungame.sh reboots, and the menu asked again on the way back
#: (David, 2026-09-14: "too confusing to see it twice after a fresh install").  Before the
#: `reboot` of every case whose label carries JJP's own comment, the hook is told, and the
#: next boot repeats the last choice without the menu.  A rungame.sh without such cases is
#: left as it is (the menu then shows again after such a reboot).
MAINT_CASE_MARK = "# maintenance reboot"
MAINT_CALL = "[ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh --maintenance-reboot"
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
             "volume_max", "media", "theme", "jjp_update", "log", "learn")
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
#: the selector's key_<name>= conf keys, in its order (conf.c); a value is <byte>.<bit>
KEY_NAMES = ("key_left", "key_right", "key_start", "key_plus", "key_minus")


def check_key_pos(name, val):
    """<byte>.<bit> as conf.c reads it (0-63 . 0-7), or two of them with a comma - the same
    button in a second place (the GNR's lockdown-bar Action button beside START,
    key_start=3.0,3.4; David 2026-09-14) - or Refused."""
    places = str(val).split(",")
    if not 1 <= len(places) <= 2:
        raise Refused("%s=%r is not <byte>.<bit> or <byte>.<bit>,<byte>.<bit>" % (name, val))
    out = []
    for place in places:
        parts = place.strip().split(".")
        try:
            b, bit = int(parts[0]), int(parts[1])
        except (IndexError, ValueError):
            raise Refused("%s=%r is not <byte>.<bit>" % (name, val))
        if len(parts) != 2 or not 0 <= b <= 63 or not 0 <= bit <= 7:
            raise Refused("%s=%r is not <0-63>.<0-7>" % (name, val))
        out.append("%d.%d" % (b, bit))
    return ",".join(out)

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
def _partclone_feed(pieces, out_path, log, meter=None):
    """cat pieces | gunzip | partclone.restore -C ... -o out_path (a raw file or a partition
    device), the pieces fed from here so the meter sees the compressed bytes go by.
    Returns (rc, broken).

    TEXT mode, not -N: in partclone 0.3.x -N means "use the NCURSES interface", so the log
    used to hold a full-screen UI's escape codes and a failure's tail was unreadable.
    -f 5 -B: a "Completed: N%" line every five seconds and no block-count line under each -
    the log stays small and a refusal's tail says how far it got."""
    cmd = 'set -o pipefail; gunzip -c | partclone.restore -C -f 5 -B -s - -o "$0" >"$1" 2>&1'
    proc = subprocess.Popen(["bash", "-c", cmd, out_path, log], stdin=subprocess.PIPE)
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
    return rc, broken


def _log_tail(log, n=1200):
    if os.path.isfile(log):
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    return ""


def restore_pieces(pieces, dest, meter=None, label="sda3"):
    """cat pieces | gunzip | partclone.restore into a sparse raw file, then size it up to the
    filesystem's own block count (partclone stops at the last used block).  Written as
    dest.part and renamed when complete."""
    need_tools("gunzip", "partclone.restore")
    part = dest + ".part"
    log = dest + ".restore.log"
    for p in (part, log):
        if os.path.exists(p):
            os.unlink(p)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    rc, broken = _partclone_feed(pieces, part, log, meter)
    if rc != 0 or broken:
        tail = _log_tail(log)
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
def hook_line_count(text):
    """Lines that ARE the hook line (MAINT_CALL carries it as a prefix, so a substring
    count would read 3 on a hooked rungame.sh)."""
    return sum(1 for ln in (text or "").split("\n") if ln.strip() == HOOK_LINES[2])


def has_hook(text):
    return hook_line_count(text) > 0


def mark_maintenance_reboots(text):
    """MAINT_CALL before the `reboot` of every case whose label line carries
    MAINT_CASE_MARK in its comment, indented like that reboot (idempotent); a case that
    ends without a reboot, or a rungame.sh without such cases, is left alone."""
    out = []
    pending = False
    for ln in text.split("\n"):
        st = ln.strip()
        if pending:
            if st == "reboot":
                if not out or out[-1].strip() != MAINT_CALL:
                    out.append(ln[:len(ln) - len(ln.lstrip())] + MAINT_CALL)
                pending = False
            elif st.endswith(";;") or st == "esac":
                pending = False
        if "#" in st and MAINT_CASE_MARK in st[st.index("#"):] and ")" in st[:st.index("#")]:
            pending = True
        out.append(ln)
    return "\n".join(out)


def hook_rungame(text):
    """rungame.sh with the guarded hook line after runonce.sh and the maintenance-reboot
    cases marked (idempotent).  Refused when the anchor is not there: a rungame.sh this
    tool does not know is not edited blind."""
    if has_hook(text):
        return mark_maintenance_reboots(text)
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == RUNONCE_LINE]
    if len(at) != 1:
        raise Refused("rungame.sh: expected exactly one '%s' line to hook after, found %d" % (RUNONCE_LINE, len(at)))
    i = at[0] + 1
    return mark_maintenance_reboots("\n".join(lines[:i] + HOOK_LINES + lines[i:]))


def strip_hook(text):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        if lines[i:i + len(HOOK_LINES)] == HOOK_LINES:
            i += len(HOOK_LINES)
            continue
        if lines[i].strip() == MAINT_CALL:
            i += 1
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
                       colors=None, heading=None, jjp_update="refuse", debug_log=False, keys=None, learn=False):
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
    # the cabinet buttons the selector reads, where a machine has them elsewhere than the
    # defaults (jjpcrt's LEFT 1.0 / RIGHT 1.2 / START 3.0, the table's Up 1.5 / Down 1.6):
    # <byte>.<bit> in the I/O board frame, as the menu's --learn line names them
    for name in KEY_NAMES:
        if keys and keys.get(name):
            out.append("%s=%s" % (name, keys[name]))
    if learn:
        out.append("# learn: the hook runs the menu with --learn - the I/O board frame's changes and any")
        out.append("# unmapped bit into the selector log, for reading a new machine's buttons off it")
        out.append("learn=1")
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
           "theme": None, "colors": {}, "jjp_update": None, "log": None, "learn": None, "keys": {}}
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
        elif key in ("heading", "font", "sound_move", "sound_confirm", "theme", "jjp_update", "log", "learn"):
            out[key] = val
        elif key in KEY_NAMES:
            out["keys"][key] = check_key_pos(key, val.strip())
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
    keys = dict(ex.get("keys") or {})
    for name in KEY_NAMES:
        v = getattr(args, name, None)
        if v is not None:
            keys[name] = check_key_pos(name, v)
    # learn=1 is carried by an inject (a calibration the operator asked for); the log is
    # not (inject: log off without the flag) except that --learn needs somewhere to write
    learn = bool(getattr(args, "learn", False)) or (ex.get("learn") or "") == "1"
    return render_images_conf(devices, titles, subtitles, default, timeout,
                              PADSELECT_DIR + "/font.ttf" if font else None, rows, move, confirm, volume,
                              theme=theme, colors=colors, heading=heading, jjp_update=policy,
                              debug_log=bool(getattr(args, "debug_log", False)) or learn, keys=keys,
                              learn=learn)


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


def unsquash_files(squashfs, dest_dir, paths):
    """Files out of the live squashfs -> their paths under dest_dir.  unsquashfs where
    squashfs-tools is installed; a read-only loop mount of the squashfs otherwise - root,
    which a build is anyway - because the app's own runtime distro (PAD-Runtime) ships no
    squashfs-tools and every JJP install ISO's live system is a squashfs the kernel can
    mount."""
    out = [os.path.join(dest_dir, p) for p in paths]
    if shutil.which("unsquashfs"):
        _run(["unsquashfs", "-q", "-n", "-f", "-d", dest_dir, squashfs] + list(paths))
    elif is_root() and shutil.which("mount"):
        mnt = tempfile.mkdtemp(prefix="mkjjpmulti_sq_")
        try:
            _run(["mount", "-t", "squashfs", "-o", "loop,ro", squashfs, mnt])
            try:
                for p, dst in zip(paths, out):
                    src = os.path.join(mnt, p)
                    if not os.path.isfile(src):
                        raise Refused("%s carries no /%s" % (squashfs, p))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(src, dst)
            finally:
                subprocess.run(["umount", mnt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                os.rmdir(mnt)
            except OSError:
                pass
    else:
        raise Refused("no unsquashfs (apt-get install squashfs-tools) and not root, so %s cannot be "
                      "read out of %s" % (", ".join(paths), squashfs))
    for p, dst in zip(paths, out):
        if not os.path.isfile(dst):
            raise Refused("%s carries no /%s" % (squashfs, p))
    return out


def unsquash_installer(squashfs, dest_dir):
    """The stock installer out of the live squashfs -> its text."""
    p = unsquash_files(squashfs, dest_dir, [SQ_INSTALLER])[0]
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ============================================================================= staging
class LoopRW:
    """A raw ext4 file attached to a loop device and mounted rw for a `with` block (root) - or
    a partition device, mounted as it is (the disk modes of `install`)."""

    def __init__(self, raw):
        self.raw = raw
        self.loop = self.mnt = None

    def __enter__(self):
        require_root("staging into the root image")
        need_tools("losetup", "mount", "umount")
        import stat as _stat
        if _stat.S_ISBLK(os.stat(self.raw).st_mode):
            dev = self.raw                                  # a partition on a disk: mounted as it is
        else:
            out = _run(["losetup", "--find", "--show", self.raw]).strip().splitlines()
            self.loop = dev = out[-1]
        self.mnt = tempfile.mkdtemp(prefix=MOUNT_PREFIX)
        try:
            _run(["mount", "-t", "ext4", "-o", "rw,noatime", dev, self.mnt])
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
            ("log", conf.get("log")), ("keys", dict(conf.get("keys") or {})), ("media_files", media_files),
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
    print("default=%s timeout=%s heading=%s volume=%s theme=%s jjp_update=%s log=%s keys=%s"
          % (rep["default"], rep["timeout"], rep["heading"], rep["volume"], rep["theme"], rep["jjp_update"],
             rep["log"] or "off", " ".join("%s=%s" % kv for kv in sorted((rep.get("keys") or {}).items())) or "default"))
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
                check("rungame.sh carries the hook exactly once", hook_line_count(rg) == 1)
                check("rungame.sh's maintenance reboots tell the hook first", rg.count(MAINT_CALL) >= 1,
                      "%d case(s)" % rg.count(MAINT_CALL) if rg.count(MAINT_CALL)
                      else "no '# maintenance reboot' case: the menu shows again after one")
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

# ============================================================================= install (a disk)
# THE ISO WRITTEN STRAIGHT ONTO A DISK - the game's SSD in a dock on this PC (item 123) - by
# THE SAME STEPS JJP'S INSTALLER RUNS ON THE MACHINE, READ OUT OF THE ISO'S OWN INSTALLER.
# jjp_install.sh (this tool's pad_install.sh on a multi-boot ISO) names the partition numbers,
# the filesystem UUIDs grub.cfg, fstab and the perm mount generator expect, the sgdisk
# templates by disk size, the size gate, which image lands in which slot in what order, and
# how the temp partition is made.  Each of those lines is anchored exactly (like the installer
# patch above) and run here, so a stock ISO installs as JJP's does (root B = a copy of root A)
# and a multi-boot ISO as pad_install.sh does (root B = the second image); an installer that
# does not parse is refused, never guessed at.  What the machine's run has and this one does
# not: the live system, the framebuffer screens, and donglecheck - the security key gates the
# GAME, not the disk.  What the ISO has and neither reads: partimag's `parts`, `sda-pt.sf`,
# `sda-gpt-*` - Clonezilla's record of a 4.6 GB golden disk the installer never looks at.
SQ_LIB = "jjp/lib"                                            # the templates, inside the squashfs

# ---- the partition table: JJP's sgdisk backup, written and read by hand ----------------------
# `sgdisk --load-backup` is what the installer runs, and it ends every write with sync() -
# the GLOBAL sync, which hangs under WSL2 whenever a Windows drive has dirty pages (it parked
# a build for good on 2026-09-13, and the first loop-device proof of this command for
# fourteen minutes in D state on 2026-09-15).  The backup file is only the three things the
# disk needs - the protective MBR, the primary header, the 128 entries - so they are written
# here, sized to the disk exactly as sgdisk sizes them (the backup header at the last
# sector, the last usable sector 34 from the end, the protective entry capped at 2 TiB),
# with every GUID verbatim, and read back the same way.  No gdisk in the runtime image.
SECTOR = 512
GPT_SIG = b"EFI PART"
GPT_ENTRIES = 128
GPT_ENTRY_SIZE = 128
GPT_TABLE_SECTORS = GPT_ENTRIES * GPT_ENTRY_SIZE // SECTOR              # 32
GPT_BACKUP_SIZE = 3 * SECTOR + GPT_ENTRIES * GPT_ENTRY_SIZE            # 17920: MBR, main header, backup header, entries
_GPT_HDR = struct.Struct("<8sIIII QQQQ 16s QIII")
GPT_TYPE_EFI = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GPT_TYPE_LINUX = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
GPT_TYPE_MSDATA = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
O_BINARY = getattr(os, "O_BINARY", 0)                     # Windows opens TEXT by default; the pure tests run there


def _crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def parse_gpt_header(hdr):
    """One 512-byte GPT header -> its fields (Refused unless the signature and its own CRC hold)."""
    if len(hdr) < 92 or hdr[:8] != GPT_SIG:
        raise Refused("no GPT header (signature %r)" % hdr[:8])
    (sig, rev, hsize, hcrc, _res, my, alt, first, last, guid, elba, n, esize, ecrc) = _GPT_HDR.unpack_from(hdr, 0)
    if hsize < 92 or hsize > SECTOR:
        raise Refused("GPT header size %d" % hsize)
    if _crc(hdr[:16] + b"\0\0\0\0" + hdr[20:hsize]) != hcrc:
        raise Refused("GPT header CRC does not match")
    return {"rev": rev, "size": hsize, "my": my, "alt": alt, "first": first, "last": last, "guid": guid,
            "elba": elba, "entries": n, "entry_size": esize, "entries_crc": ecrc}


def build_gpt_header(h, my, alt, first, last, elba, entries):
    """A 512-byte header from the fields of `h` with these positions, both CRCs fresh."""
    body = bytearray(_GPT_HDR.pack(GPT_SIG, h["rev"], 92, 0, 0, my, alt, first, last, h["guid"], elba,
                                   GPT_ENTRIES, GPT_ENTRY_SIZE, _crc(entries)))
    struct.pack_into("<I", body, 16, _crc(bytes(body)))
    return bytes(body) + b"\0" * (SECTOR - len(body))


def parse_gpt_backup(data):
    """An sgdisk backup (gdisk's SaveGPTBackup: the protective MBR, the main header, the backup
    header, the 128 entries) -> (protective MBR, main header fields, the entries as bytes)."""
    if len(data) != GPT_BACKUP_SIZE:
        raise Refused("sgdisk backup: %d bytes, not %d (MBR + two headers + %d entries)" % (len(data), GPT_BACKUP_SIZE, GPT_ENTRIES))
    mbr, hdr, hdr2, entries = data[:SECTOR], data[SECTOR:2 * SECTOR], data[2 * SECTOR:3 * SECTOR], data[3 * SECTOR:]
    if mbr[510:512] != b"\x55\xaa":
        raise Refused("sgdisk backup: no MBR signature")
    h = parse_gpt_header(hdr)
    h2 = parse_gpt_header(hdr2)
    if h2["guid"] != h["guid"] or h2["entries_crc"] != h["entries_crc"]:
        raise Refused("sgdisk backup: its two headers disagree")
    if h["entries"] != GPT_ENTRIES or h["entry_size"] != GPT_ENTRY_SIZE:
        raise Refused("sgdisk backup: %d entries of %d bytes, not %d of %d" % (h["entries"], h["entry_size"], GPT_ENTRIES, GPT_ENTRY_SIZE))
    if _crc(entries) != h["entries_crc"]:
        raise Refused("sgdisk backup: the entries' CRC does not match the header")
    return mbr, h, entries


def gpt_entries(entries):
    """The used entries: [{num, type, guid, first, last, attrs, name}] (GUIDs as upper-case text)."""
    out = []
    for i in range(GPT_ENTRIES):
        e = entries[i * GPT_ENTRY_SIZE:(i + 1) * GPT_ENTRY_SIZE]
        t, g, first, last, attrs = struct.unpack_from("<16s16sQQQ", e, 0)
        if t == b"\0" * 16:
            continue
        out.append({"num": i + 1, "type": str(uuid.UUID(bytes_le=t)).upper(), "guid": str(uuid.UUID(bytes_le=g)).upper(),
                    "first": first, "last": last, "attrs": attrs,
                    "name": e[56:128].decode("utf-16-le", "replace").rstrip("\0")})
    return out


def gpt_rows(entries):
    return {e["num"]: (e["first"], e["last"]) for e in gpt_entries(entries)}


def protective_mbr(mbr, total_sectors):
    """The template's protective MBR with its 0xEE entry sized to this disk (sgdisk's rule:
    everything after LBA 0, capped at what 32 bits hold)."""
    out = bytearray(mbr)
    for i in range(4):
        at = 0x1BE + 16 * i
        if out[at + 4] == 0xEE:
            struct.pack_into("<II", out, at + 8, 1, min(total_sectors - 1, 0xFFFFFFFF))
            break
    else:
        raise Refused("sgdisk backup: the MBR has no protective (0xEE) entry")
    return bytes(out)


def gpt_layout(mbr, h, entries, total_sectors):
    """What sgdisk would put on a disk of `total_sectors` from this backup: [(lba, bytes)...] -
    the MBR, the primary header and table at the start, the table and header again at the end."""
    last = total_sectors - 1
    if total_sectors < 2 * (1 + GPT_TABLE_SECTORS) + 2:
        raise Refused("a disk of %d sectors cannot hold a GPT" % total_sectors)
    used = gpt_entries(entries)
    last_usable = total_sectors - 1 - GPT_TABLE_SECTORS - 1
    if used and max(e["last"] for e in used) > last_usable:
        raise Refused("the template's partitions end at sector %d, past what a %s disk holds (last usable %d)"
                      % (max(e["last"] for e in used), _gb(total_sectors * SECTOR), last_usable))
    first_usable = h["first"]
    primary = build_gpt_header(h, 1, last, first_usable, last_usable, 2, entries)
    backup = build_gpt_header(h, last, 1, first_usable, last_usable, total_sectors - 1 - GPT_TABLE_SECTORS, entries)
    return [(0, protective_mbr(mbr, total_sectors)), (1, primary), (2, entries),
            (total_sectors - 1 - GPT_TABLE_SECTORS, entries), (last, backup)]


def dev_size_bytes(dev):
    """A block device's size (blockdev), or a plain file's (the self-tests write onto files)."""
    import stat as _stat
    if _stat.S_ISBLK(os.stat(dev).st_mode):
        ss = int(_run(["blockdev", "--getss", dev]).strip() or SECTOR)
        if ss != SECTOR:
            raise Refused("%s has %d-byte sectors; JJP's partition table is laid out for 512 (the machine's installer "
                          "would fail on it too)" % (dev, ss))
        return int(_run(["blockdev", "--getsize64", dev]).strip())
    return os.path.getsize(dev)


def write_gpt(dev, tpl_path):
    """The template onto `dev` as sgdisk -Z + --load-backup would leave it, then the kernel
    told to read the table (no sync(): fsync of the device only)."""
    with open(tpl_path, "rb") as f:
        mbr, h, entries = parse_gpt_backup(f.read())
    total = dev_size_bytes(dev) // SECTOR
    pieces = gpt_layout(mbr, h, entries, total)
    fd = os.open(dev, os.O_RDWR | O_BINARY)
    try:
        # sgdisk -Z: the old table gone first, so a failure half way leaves no stale GPT
        for lba in (1, total - 1):
            os.lseek(fd, lba * SECTOR, 0)
            os.write(fd, b"\0" * SECTOR)
        for lba, data in pieces:
            os.lseek(fd, lba * SECTOR, 0)
            os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    import stat as _stat
    if _stat.S_ISBLK(os.stat(dev).st_mode):
        subprocess.run(["blockdev", "--rereadpt", dev], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return gpt_entries(entries)


def read_gpt(dev):
    """The primary header and table off `dev` -> (header fields, entries bytes), CRC-checked."""
    fd = os.open(dev, os.O_RDONLY | O_BINARY)
    try:
        os.lseek(fd, SECTOR, 0)
        hdr = os.read(fd, SECTOR)
        h = parse_gpt_header(hdr)
        os.lseek(fd, h["elba"] * SECTOR, 0)
        entries = os.read(fd, h["entries"] * h["entry_size"])
    finally:
        os.close(fd)
    if _crc(entries) != h["entries_crc"]:
        raise Refused("%s: the partition entries' CRC does not match the header" % dev)
    return h, entries


def make_gpt_backup(parts, total_sectors, disk_guid=None):
    """An sgdisk-shaped backup for a disk of `total_sectors` from [(type GUID text, size in
    sectors)...] laid out from sector 2048 on 2048-sector boundaries (the self-test's
    stand-in for JJP's backup.sgdisk1/2/3)."""
    entries = bytearray(GPT_ENTRIES * GPT_ENTRY_SIZE)
    at = 2048
    for i, (type_guid, size) in enumerate(parts):
        first, last = at, at + size - 1
        struct.pack_into("<16s16sQQQ", entries, i * GPT_ENTRY_SIZE, uuid.UUID(type_guid).bytes_le, uuid.uuid4().bytes_le,
                         first, last, 0)
        at = (last + 1 + 2047) // 2048 * 2048
    h = {"rev": 0x00010000, "guid": (uuid.UUID(disk_guid) if disk_guid else uuid.uuid4()).bytes_le, "first": 34}
    mbr = bytearray(SECTOR)
    mbr[0x1BE:0x1BE + 16] = bytes([0x00, 0x00, 0x02, 0x00, 0xEE, 0xFF, 0xFF, 0xFF]) + struct.pack("<II", 1, 0)
    mbr[510:512] = b"\x55\xaa"
    layout = gpt_layout(bytes(mbr), h, bytes(entries), total_sectors)
    return layout[0][1] + layout[1][1] + layout[4][1] + bytes(entries)
_INS_UUID_RE = re.compile(r'^FS_UUID_([A-Z]+)="([0-9A-Fa-f-]+)"[ \t]*$', re.M)
_INS_PART_RE = re.compile(r'^PART_([A-Z]+)="\$\{dest_disk\}\$\{part_prefix\}(\d+)"[ \t]*$', re.M)
_INS_TPL_RE = re.compile(r'^sgdisk_backup(\d+)="\$\{lib_path\}/(backup\.sgdisk\d+)"[ \t]*$', re.M)
_INS_RESTORE_RE = re.compile(r'^[ \t]*restore_partition[ \t]+"\$PART_([A-Z]+)"[ \t]+'
                             r'"(sda\d+\.[a-z0-9]+-ptcl-img)"[ \t]+"\$FS_UUID_([A-Z]+)"[ \t]*$', re.M)
_INS_CHOICE_RE = re.compile(r'-lt[ \t]+\$\(\((\d+)[ \t]*\*[ \t]*1024[ \t]*\*[ \t]*1024[ \t]*\*[ \t]*1024\)\)[ \t]*\]\]'
                            r'[ \t]*\n[ \t]*then[ \t]*\n[ \t]*backup_to_use="\$sgdisk_backup(\d+)"')
_INS_DEFAULT_RE = re.compile(r'^[ \t]*backup_to_use="\$sgdisk_backup(\d+)"[ \t]*$', re.M)
_INS_MIN_RE = re.compile(r'^min_disk_size_gib="(\d+)"[ \t]*$', re.M)
_INS_TEMP_MKFS = 'mkfs.ext4 -F "$PART_TEMP"'
_INS_TEMP_UUID = 'tune2fs "$PART_TEMP" -f -U "$FS_UUID_TEMP"'
_INS_LINE_FORMS = ("FS_UUID_<NAME>=\"..\"", "PART_<NAME>=\"${dest_disk}${part_prefix}N\"",
                   "sgdisk_backup<GB>=\"${lib_path}/backup.sgdiskN\"", "backup_to_use=",
                   "restore_partition \"$PART_<NAME>\" \"sdaN.<fs>-ptcl-img\" \"$FS_UUID_<NAME>\"",
                   "min_disk_size_gib=", _INS_TEMP_MKFS, _INS_TEMP_UUID)


def parse_installer(text):
    """jjp_install.sh / pad_install.sh -> what an install does: {uuids, parts, templates,
    choices [(GiB, template key)...] in the installer's order, default (template key),
    restores [(PART name, image, UUID name)...] in order, min_disk_gib}.  Refused when a
    line this needs is missing or doubled - an installer this tool does not know is not run
    blind."""
    uuids = dict(_INS_UUID_RE.findall(text))
    parts = {k: int(v) for k, v in _INS_PART_RE.findall(text)}
    templates = dict(_INS_TPL_RE.findall(text))
    choices = [(int(g), t) for g, t in _INS_CHOICE_RE.findall(text)]
    defaults = _INS_DEFAULT_RE.findall(text)
    restores = _INS_RESTORE_RE.findall(text)
    mins = _INS_MIN_RE.findall(text)
    problems = []
    if not uuids:
        problems.append("no FS_UUID_* lines")
    if not parts:
        problems.append("no PART_* lines")
    elif len(set(parts.values())) != len(parts):
        problems.append("two PART_* names share a partition number")
    if not templates:
        problems.append("no sgdisk_backup* lines")
    if not defaults:
        problems.append("no backup_to_use= line")
    if not restores:
        problems.append("no restore_partition lines")
    if len(mins) != 1:
        problems.append("%d min_disk_size_gib= lines" % len(mins))
    for what, line in (("mkfs", _INS_TEMP_MKFS), ("UUID", _INS_TEMP_UUID)):
        n = sum(1 for ln in text.split("\n") if ln.strip().startswith(line))
        if n != 1:
            problems.append("%d line(s) for the temp partition's %s" % (n, what))
    if "TEMP" not in parts or "TEMP" not in uuids:
        problems.append("no PART_TEMP / FS_UUID_TEMP")
    seen = set()
    for p, _img, u in restores:
        if p not in parts:
            problems.append("PART_%s is restored but never defined" % p)
        if u not in uuids:
            problems.append("FS_UUID_%s is used but never defined" % u)
        if parts.get(p) in seen:
            problems.append("PART_%s is restored twice" % p)
        seen.add(parts.get(p))
    default = defaults[0] if defaults else None
    for _g, t in choices + ([(0, default)] if default else []):
        if t not in templates:
            problems.append("sgdisk_backup%s is chosen but never defined" % t)
    if problems:
        raise Refused("the ISO's installer: %s - an installer this tool does not know is not run blind "
                      "(it reads these line forms: %s)" % ("; ".join(problems), "; ".join(_INS_LINE_FORMS)))
    return {"uuids": uuids, "parts": parts, "templates": templates, "choices": choices, "default": default,
            "restores": [tuple(r) for r in restores], "min_disk_gib": int(mins[0])}


def pick_template(ins, size_bytes):
    """The installer's choice: the first `-lt N GiB` that holds, else the default."""
    for gib, t in ins["choices"]:
        if size_bytes < (gib << 30):
            return ins["templates"][t]
    return ins["templates"][ins["default"]]


def part_dev(disk, n):
    """/dev/sda -> /dev/sda3; /dev/nvme0n1 -> /dev/nvme0n1p3; /dev/loop7 -> /dev/loop7p3: the
    installer's part_prefix rule (a name ending in a digit takes a 'p')."""
    return "%s%s%d" % (disk, "p" if disk[-1:].isdigit() else "", n)


def _lsblk_col(dev, col):
    r = subprocess.run(["lsblk", "-dno", col, dev], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode("utf-8", "replace").strip()


def disk_facts(disk):
    """{dev (resolved), size, ro, model, tran, in_use [..]}: in_use names every mount and swap
    that sits on the disk or one of its partitions - the whole reason a disk gets refused."""
    import stat as _stat
    real = os.path.realpath(disk)
    try:
        st = os.stat(real)
    except OSError as e:
        raise Refused("%s: %s" % (disk, e.strerror))
    if not _stat.S_ISBLK(st.st_mode):
        raise Refused("%s is not a block device (a disk image takes `losetup -P --find --show FILE` first)" % disk)
    size = int(_run(["blockdev", "--getsize64", real]).strip())
    ro = _run(["blockdev", "--getro", real]).strip() == "1"

    def on_disk(src):
        if not src.startswith("/dev/"):
            return False
        rs = os.path.realpath(src)
        if rs == real:
            return True
        return rs.startswith(real) and rs[len(real):].lstrip("p").isdigit() and rs[len(real):] != ""

    in_use = []
    for table, what in (("/proc/mounts", "mounted on"), ("/proc/swaps", "swap")):
        try:
            with open(table, "r") as f:
                for line in f:
                    cols = line.split()
                    if len(cols) >= 2 and on_disk(cols[0]):
                        in_use.append("%s %s %s" % (cols[0], what, cols[1]) if what == "mounted on" else "%s is swap" % cols[0])
        except OSError:
            pass
    return {"dev": real, "size": size, "ro": ro, "model": _lsblk_col(real, "MODEL"), "tran": _lsblk_col(real, "TRAN"),
            "in_use": in_use}


def confirm_wipe(disk, facts, what="EVERYTHING on %s (%s, %s) is erased."):
    """No --yes: the disk as it is now, then its name typed back, or Refused."""
    if not sys.stdin.isatty():
        raise Refused("%s would be wiped: pass --yes (there is no terminal to confirm on)" % disk)
    r = subprocess.run(["lsblk", "-o", "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS", disk], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(r.stdout.decode("utf-8", "replace").rstrip())
    name = os.path.basename(disk)
    try:
        typed = input((what + " Type %s to go on: ") % (disk, facts["model"] or "no model", _gb(facts["size"]), name))
    except EOFError:
        typed = ""
    if typed.strip() != name:
        raise Refused("not confirmed; nothing was written")


def wait_for_parts(disk, numbers, seconds=20):
    """The partition nodes after the table is written: write_gpt asks the kernel to re-read it
    (blockdev --rereadpt); asked once more when the nodes are slow to appear; then wait."""
    want = [part_dev(disk, n) for n in numbers]
    t0 = time.time()
    asked = False
    while time.time() - t0 < seconds:
        if all(os.path.exists(p) for p in want):
            return want
        if not asked and time.time() - t0 > 2:
            subprocess.run(["blockdev", "--rereadpt", disk], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            asked = True
        time.sleep(0.25)
    missing = [p for p in want if not os.path.exists(p)]
    raise Refused("after the table was written the kernel shows no %s - is %s attached with partition scanning "
                  "(losetup -P; wsl --mount --bare)?" % (", ".join(missing), disk))


def _finish_ext4(dev, uuid):
    """The installer's restore_partition tail for an ext4 slot: fsck, grow into the partition,
    fsck, the UUID grub/fstab expect."""
    _run(["e2fsck", "-f", "-y", dev], ok_rc=(0, 1, 2))
    _run(["resize2fs", dev])
    _run(["e2fsck", "-f", "-y", dev], ok_rc=(0, 1, 2))
    _run(["tune2fs", dev, "-f", "-U", uuid])


def _finish_vfat(dev, uuid):
    """The installer's line for the EFI slot is `dosfslabel -i DEV ID`, which under the
    dosfstools the live system carries (4.2) changes nothing - `-i` takes no value there,
    so the line prints the id and sets no label - and the shipped image already carries
    the id the fstab wants.  Nothing is run; verify checks the id on the disk instead."""
    return None


def flush_disk(disk):
    subprocess.run(["blockdev", "--flushbufs", disk], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        fd = os.open(disk, os.O_RDWR | O_BINARY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


class DevMount:
    """A read-only mount of a partition device for a `with` block (root)."""

    def __init__(self, dev, fstype=None):
        self.dev, self.fstype, self.mnt = dev, fstype, None

    def __enter__(self):
        self.mnt = tempfile.mkdtemp(prefix=MOUNT_PREFIX)
        try:
            _run(["mount", "-o", "ro"] + (["-t", self.fstype] if self.fstype else []) + [self.dev, self.mnt])
        except Refused:
            os.rmdir(self.mnt)
            self.mnt = None
            raise
        return self.mnt

    def __exit__(self, *exc):
        if not self.mnt:
            return
        for attempt in range(6):
            r = subprocess.run(["umount", self.mnt], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode == 0:
                break
            time.sleep(0.5 * (attempt + 1))
        try:
            os.rmdir(self.mnt)
        except OSError:
            pass


def template_rows(tpl):
    """{number: (first, last)} of the template's partitions."""
    with open(tpl, "rb") as f:
        _mbr, _h, entries = parse_gpt_backup(f.read())
    return gpt_rows(entries)


def blkid_uuid(dev):
    r = subprocess.run(["blkid", "-s", "UUID", "-o", "value", dev], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode("utf-8", "replace").strip()


def _uuid_norm(u):
    return (u or "").replace("-", "").upper()


def check_jjp_disk(disk, ins):
    """A disk this tool or the machine's installer wrote: the installer's slots on its GPT and
    every slot's filesystem UUID the installer's.  Refused otherwise - the menu and image
    modes change one part of such a disk and must never land on anything else."""
    try:
        _h, entries = read_gpt(disk)
    except Refused as e:
        raise Refused("%s carries no partition table this tool reads (%s): not a JJP disk - a full install "
                      "(no --menu-only / --image) writes it whole" % (disk, e))
    rows = gpt_rows(entries)
    missing = sorted(n for n in ins["parts"].values() if n not in rows)
    if missing:
        raise Refused("%s has no partition %s: not a JJP disk laid out as the installer lays it - a full install "
                      "writes it whole" % (disk, ", ".join(str(n) for n in missing)))
    bad = []
    for name, n in sorted(ins["parts"].items(), key=lambda kv: kv[1]):
        got = blkid_uuid(part_dev(disk, n))
        if _uuid_norm(got) != _uuid_norm(ins["uuids"][name]):
            bad.append("%s %s is %s, not %s" % (name, part_dev(disk, n), got or "no filesystem", ins["uuids"][name]))
    if bad:
        raise Refused("%s is not a JJP disk as the installer lays it out (%s) - a full install writes it whole"
                      % (disk, "; ".join(bad[:3])))
    return rows


def root_manifest_bytes(man):
    """build.json as it sits INSIDE root A: the manifest without its `staged` map (that map
    describes the root, and the ISO's copy carries it) - the bytes `build` staged, so the map's
    own sha of build.json holds after a menu write too."""
    out = collections.OrderedDict((k, v) for k, v in man.items() if k != "staged")
    return (json.dumps(out, indent=1) + "\n").encode("utf-8")


def carried_media(pad, work):
    """The ISO's own media set as a flat directory (media.json beside the files), the way
    `inject` carries it -> (media_dir or None, plan or None)."""
    if not (os.path.isdir(os.path.join(pad, "media")) and os.path.isfile(os.path.join(pad, mkc.MEDIA_MANIFEST))):
        return None, None
    media_dir = os.path.join(work, "media_carried")
    if os.path.isdir(media_dir):
        shutil.rmtree(media_dir)
    shutil.copytree(os.path.join(pad, "media"), media_dir)
    shutil.copyfile(os.path.join(pad, mkc.MEDIA_MANIFEST), os.path.join(media_dir, mkc.MEDIA_MANIFEST))
    return media_dir, mkc.plan_media(media_dir, 2)


def read_pad(pad):
    """The multi-boot ISO's menu record: (images.conf text, its parse, build.json dict)."""
    with open(os.path.join(pad, "images.conf"), "r", encoding="utf-8") as f:
        conf_text = f.read()
    conf = parse_images_conf(conf_text)
    bp = os.path.join(pad, mkc.BUILD_MANIFEST)
    build = parse_manifest(open(bp, "rb").read(), mkc.BUILD_MANIFEST) if os.path.isfile(bp) else None
    if not build or not isinstance(build.get("images"), list) or len(build["images"]) < 2:
        raise Refused("%s carries no %s naming its two images - not a multi-boot ISO this tool wrote" % (pad, mkc.BUILD_MANIFEST))
    return conf_text, conf, build


def gate_root_pair(finfo, rec_other, id_new, id_other, n, allow):
    """The same-version gate for one slot: the new ISO's Name/Version against what build.json
    records for the other image, and the new root's game code against the other root ON THE
    DISK (both share one settings partition)."""
    why = []
    if (finfo.name, finfo.game_version) != (rec_other.get("name"), rec_other.get("game_version")):
        why.append("%s is %s %s, the other image is %s %s (version_info.txt vs build.json)"
                   % (os.path.basename(finfo.path), finfo.name, finfo.game_version, rec_other.get("name"), rec_other.get("game_version")))
    if id_new["gamename"] != id_other["gamename"]:
        why.append("its GAMENAME is %s, the other root's %s" % (id_new["gamename"], id_other["gamename"]))
    if id_new["game_sha256"] != id_other["game_sha256"]:
        why.append("its game binary differs from the other root's (%s vs %s)" % (id_new["game_sha256"][:12], id_other["game_sha256"][:12]))
    if id_new["fldat_sha256"] != id_other["fldat_sha256"]:
        why.append("its fl.dat differs from the other root's (%s vs %s)"
                   % ((id_new["fldat_sha256"] or "none")[:12], (id_other["fldat_sha256"] or "none")[:12]))
    if why:
        msg = "image %d would not be the same game code as the other image: %s. %s" % (n, "; ".join(why), VERSION_COST)
        if not allow:
            raise Refused(msg + ". Pass --allow-version-mismatch to write it anyway")
        say("WARNING: " + msg + " (--allow-version-mismatch given)")
    return why


def verify_disk(disk, ins, info, tpl, work, expect_staged=None, expect_images=None, fresh=True):
    """The written disk read back: the table sector for sector against the template, every
    slot's UUID, root A's menu (or its absence on a stock install), the game in both roots,
    grub set to A with root A's UUID, a loader on the EFI partition, mountable perms, an
    empty temp.  `expect_staged` ({path in root A: sha256}, the ISO's build.json map): every
    menu file in root A is that file.  `expect_images` ({n: {"source", "game_sha256"}}):
    root A's build.json records image n so, and slot n's game IS that binary.  `fresh`: a full
    install just made the temp partition, so it is empty; after a partial write it holds the
    machine's logs from its boots, and only has to mount.  Prints ok/FAIL lines like `verify`;
    returns True when all hold."""
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        print("%s: %s%s" % ("ok" if ok else "FAIL", name, (" - " + detail) if detail else ""))
        return bool(ok)

    def norm(u):
        return (u or "").replace("-", "").upper()

    def read(mnt, rel):
        p = os.path.join(mnt, rel.lstrip("/"))
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    parts, uuids = ins["parts"], ins["uuids"]
    try:
        h, entries = read_gpt(disk)
        rows = gpt_rows(entries)
        check("%d partitions on %s" % (len(parts), disk), set(rows) == set(parts.values()),
              "found %s" % (sorted(rows) or "none"))
        with open(tpl, "rb") as f:
            _mbr, th, tentries = parse_gpt_backup(f.read())
        check("the partition table is %s entry for entry (GUIDs included)" % os.path.basename(tpl), entries == tentries,
              "" if entries == tentries else "differs at %s" % sorted(n for n in set(rows) | set(gpt_rows(tentries))
                                                                       if rows.get(n) != gpt_rows(tentries).get(n)))
        total = dev_size_bytes(disk) // SECTOR
        check("the GPT is sized to the disk (backup header at the last sector, disk GUID kept)",
              h["alt"] == total - 1 and h["last"] == total - 2 - GPT_TABLE_SECTORS and h["guid"] == th["guid"],
              "alt %d last usable %d of %d" % (h["alt"], h["last"], total))
    except Refused as e:
        check("a GPT on %s" % disk, False, str(e)[-200:])
    for name, n in sorted(parts.items(), key=lambda kv: kv[1]):
        dev = part_dev(disk, n)
        r = subprocess.run(["blkid", "-s", "UUID", "-o", "value", dev], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        got = r.stdout.decode("utf-8", "replace").strip()
        check("%s %s has UUID %s" % (name, dev, uuids[name]), norm(got) == norm(uuids[name]), got or "no filesystem")
    game = JJPEDIR + "/" + info.name + "/game"
    menu_wanted = bool(info.pad_dir)
    for slot in ("ROOTA", "ROOTB"):
        dev = part_dev(disk, parts[slot])
        try:
            with DevMount(dev) as m:
                gb = read(m, game)
                check("%s holds %s" % (slot, game), gb is not None)
                n_slot = 0 if slot == "ROOTA" else 1
                if expect_images and n_slot in expect_images and gb is not None:
                    want = expect_images[n_slot]["game_sha256"]
                    check("%s's game is %s's binary (%s)" % (slot, os.path.basename(expect_images[n_slot]["source"]), want[:12]),
                          sha256_bytes(gb) == want, sha256_bytes(gb)[:12])
                rg = (read(m, RUNGAME) or b"").decode("utf-8", "replace")
                has_menu = os.path.isdir(os.path.join(m, PADSELECT_DIR.lstrip("/")))
                if slot == "ROOTA" and menu_wanted:
                    check("root A carries the menu: %s and rungame.sh hooked once" % PADSELECT_DIR,
                          has_menu and hook_line_count(rg) == 1, "menu %s, hook lines %d" % (has_menu, hook_line_count(rg)))
                    bj = read(m, PADSELECT_DIR + "/" + mkc.BUILD_MANIFEST)
                    check("root A carries %s" % (PADSELECT_DIR + "/" + mkc.BUILD_MANIFEST), bj is not None)
                    if expect_staged:
                        skip = PADSELECT_DIR + "/" + mkc.BUILD_MANIFEST
                        bad = [p for p, sha in expect_staged.items()
                               if p != skip and (read(m, p) is None or sha256_bytes(read(m, p)) != sha)]
                        check("every staged menu file in root A is the ISO's (%d file(s))" % (len(expect_staged) - (skip in expect_staged)),
                              not bad, ", ".join(bad[:4]))
                    if expect_images and bj is not None:
                        man = parse_manifest(bj, mkc.BUILD_MANIFEST) or {}
                        for n, want in sorted(expect_images.items()):
                            rec = (man.get("images") or [{}, {}])[n] if n < len(man.get("images") or []) else {}
                            check("root A's build.json records image %d as %s (%s)" % (n, os.path.basename(want["source"]), want["game_sha256"][:12]),
                                  rec.get("source") == want["source"] and rec.get("game_sha256") == want["game_sha256"],
                                  "%s %s" % (rec.get("source"), (rec.get("game_sha256") or "?")[:12]))
                else:
                    check("%s is a stock root (no menu, no hook)" % slot, not has_menu and hook_line_count(rg) == 0)
                fu = (read(m, FS_UUIDS) or b"").decode("utf-8", "replace")
                check("%s's fs_uuids.sh names root A/B as the installer does" % slot,
                      all(re.search(r'^FS_UUID_%s="?%s"?\s*$' % (k, re.escape(uuids.get(k, "?"))), fu, re.M | re.I)
                          for k in ("ROOTA", "ROOTB")))
        except Refused as e:
            check("%s mounts" % slot, False, str(e)[-200:])
    if "BOOT" in parts:
        try:
            with DevMount(part_dev(disk, parts["BOOT"])) as m:
                cur = (read(m, "grub/curgrub") or b"").decode("utf-8", "replace").strip()
                check("grub boots slot a (curgrub)", cur == "a", cur or "no curgrub")
                cfg = (read(m, "grub/grub.cfg") or b"").decode("utf-8", "replace")
                check("grub.cfg boots root A's UUID", uuids.get("ROOTA", "?") in cfg)
                check("a kernel on the boot partition", any(n.startswith("vmlinuz") for n in os.listdir(m)))
        except Refused as e:
            check("BOOT mounts", False, str(e)[-200:])
    if "EFI" in parts:
        try:
            with DevMount(part_dev(disk, parts["EFI"]), "vfat") as m:
                efi = [os.path.join(r, f) for r, _d, fs in os.walk(m) for f in fs if f.lower().endswith(".efi")]
                check("a boot loader on the EFI partition", bool(efi), "%d .efi file(s)" % len(efi))
        except Refused as e:
            check("EFI mounts", False, str(e)[-200:])
    for slot in ("PERMA", "PERMB"):
        if slot in parts:
            try:
                with DevMount(part_dev(disk, parts[slot])):
                    check("%s mounts" % slot, True)
            except Refused as e:
                check("%s mounts" % slot, False, str(e)[-200:])
    try:
        with DevMount(part_dev(disk, parts["TEMP"])) as m:
            extra = [n for n in os.listdir(m) if n != "lost+found"]
            if fresh:
                check("temp is an empty ext4", not extra, ", ".join(extra[:4]))
            else:
                check("temp mounts (the machine's logs stay: %d entr%s)" % (len(extra), "y" if len(extra) == 1 else "ies"), True)
    except Refused as e:
        check("TEMP mounts", False, str(e)[-200:])
    ok = all(r[1] for r in results)
    print("install verify: %s (%d check(s), %d failed)" % ("PASS" if ok else "FAIL", len(results), sum(1 for r in results if not r[1])))
    return ok


def install_args_check(a):
    """The mode from the flags, before anything else: full (the default), menu (--menu-only),
    image (--image N --from ISO).  Refused for a mix or a half."""
    menu = bool(getattr(a, "menu_only", False))
    image = getattr(a, "image", None)
    from_iso = getattr(a, "from_iso", None)
    if menu and (image is not None or from_iso):
        raise Refused("--menu-only and --image are two different writes: give one of them")
    if (image is None) != (not from_iso):
        raise Refused("--image N and --from ISO go together (the image's own install ISO for that slot)")
    if image is not None and image not in (0, 1):
        raise Refused("--image takes 0 (root A) or 1 (root B)")
    return "menu" if menu else ("image" if image is not None else "full")


PROGRESS_T0 = []


def install_disk(a):
    """`install`: the ISO onto a.disk as the ISO's own installer would put it on the machine
    (full), or - on a disk that already holds that install - only the menu (--menu-only) or
    only one image's root (--image N --from ISO); the two partial writes leave the settings
    partition, and everything else, alone."""
    mode = install_args_check(a)
    require_root("install")
    PROGRESS_T0[:] = [time.time()]
    need_tools("partclone.restore", "gunzip", "e2fsck", "resize2fs", "tune2fs", "mkfs.ext4",
               "blockdev", "lsblk", "blkid", "mount", "umount", "debugfs")
    iso = os.path.abspath(a.iso)
    if not os.path.isfile(iso):
        raise Refused("%s does not exist" % iso)
    facts = disk_facts(a.disk)
    disk = facts["dev"]
    if facts["in_use"]:
        raise Refused("%s is in use (%s) - not a disk to write" % (disk, "; ".join(facts["in_use"][:4])))
    if facts["ro"]:
        raise Refused("%s is read-only" % disk)
    work = os.path.abspath(a.workdir) if a.workdir else tempfile.mkdtemp(prefix="mkjjpmulti_install_")
    os.makedirs(work, exist_ok=True)
    t0 = time.time()
    try:
        with IsoMount(iso, os.path.join(work, "iso")) as m:
            info = iso_info(iso, m)
            info.check_stock_shape("ISO")
            pad_path = os.path.join(m, PAD_INSTALLER.lstrip("/"))
            squashfs = os.path.join(m, SQUASHFS.lstrip("/"))
            if os.path.isfile(pad_path):
                with open(pad_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                which = PAD_INSTALLER + " (this tool's copy of JJP's installer, on the ISO)"
            else:
                text = unsquash_installer(squashfs, os.path.join(work, "sq"))
                which = "/" + SQ_INSTALLER + " (JJP's installer, in the live system)"
            ins = parse_installer(text)
            dev_size_bytes(disk)                          # 512-byte sectors, or Refused before anything is written
            tpl_name = pick_template(ins, facts["size"])
            tpl = unsquash_files(squashfs, os.path.join(work, "sq"), [SQ_LIB + "/" + tpl_name])[0]
            pad = os.path.join(m, ISO_PAD_DIR.lstrip("/"))
            if mode == "full":
                ok = _install_full(a, disk, facts, ins, info, m, tpl, tpl_name, iso, which, work)
            else:
                if not info.pad_dir or not info.pieces.get(ROOTB_PART):
                    raise Refused("%s is not a multi-boot ISO this tool wrote (no %s / no sda5 pieces): --menu-only and "
                                  "--image work with the menu such an ISO carries" % (os.path.basename(iso), ISO_PAD_DIR))
                check_jjp_disk(disk, ins)
                if mode == "menu":
                    ok = _install_menu(a, disk, facts, ins, info, pad, tpl, work)
                else:
                    ok = _install_image(a, disk, facts, ins, info, pad, tpl, work)
        say("install: %s (%s, %s, %d s)" % ("DONE" if ok else "FAILED VERIFY", mode, disk, time.time() - t0))
        return 0 if ok else 1
    finally:
        if not a.workdir:
            shutil.rmtree(work, ignore_errors=True)


def _install_full(a, disk, facts, ins, info, m, tpl, tpl_name, iso, which, work):
    """Everything, as the machine's installer writes it."""
    try:
        min_gib = int(str(info.version.get("Disksize") or "").strip() or ins["min_disk_gib"])
    except ValueError:
        min_gib = ins["min_disk_gib"]
    if facts["size"] < (min_gib << 30):
        raise Refused("%s holds %s; %s wants a disk of at least %d GiB (version_info.txt Disksize) - the "
                      "machine's installer would refuse it too" % (disk, _gb(facts["size"]), os.path.basename(iso), min_gib))
    for p, img, _u in ins["restores"]:
        part = img.split(".")[0]
        if not info.pieces.get(part):
            raise Refused("the installer restores %s into PART_%s but the ISO carries no %s pieces" % (img, p, part))
    say("install %s -> %s (%s%s, %s) by %s" % (os.path.basename(iso), disk, facts["model"] or "no model",
                                               (", " + facts["tran"]) if facts["tran"] else "", _gb(facts["size"]), which))
    say("slots: " + ", ".join("%s=%s" % (p, part_dev(disk, n)) for p, n in sorted(ins["parts"].items(), key=lambda kv: kv[1])))
    say("images: " + ", ".join("%s -> %s" % (img, p) for p, img, _u in ins["restores"]) + "; TEMP mkfs")
    if not a.yes:
        confirm_wipe(disk, facts)
    budget = sum(info.piece_bytes(img.split(".")[0]) for _p, img, _u in ins["restores"])
    PROGRESS.start(budget + 2, "install")
    PROGRESS.step("partition table", 1)
    say("partition table: %s (the installer's choice for this size), written as sgdisk -Z + --load-backup would"
        % tpl_name)
    written = write_gpt(disk, tpl)
    say("  %d partition(s): %s" % (len(written), ", ".join("%d %s" % (e["num"], _gb((e["last"] - e["first"] + 1) * SECTOR))
                                                          for e in written)))
    wait_for_parts(disk, sorted(set(ins["parts"].values())))
    for p, img, u in ins["restores"]:
        dev = part_dev(disk, ins["parts"][p])
        uuid = ins["uuids"][u]
        part = img.split(".")[0]
        pieces = piece_paths(m, info, part)
        PROGRESS.step("%s -> %s" % (img, dev), info.piece_bytes(part))
        say("%s: %s (%d piece(s), %s) -> %s, %s" % (p, img, len(pieces), _gb(info.piece_bytes(part)), dev,
                                                   ("volume id %s" % uuid) if "vfat" in img else ("resize2fs, UUID %s" % uuid)))
        _restore_slot(pieces, dev, img, uuid, work)
    dev = part_dev(disk, ins["parts"]["TEMP"])
    PROGRESS.step("temp " + dev, 1)
    say("TEMP: mkfs.ext4 %s, UUID %s" % (dev, ins["uuids"]["TEMP"]))
    _run(["mkfs.ext4", "-q", "-F", dev])
    _run(["e2fsck", "-f", "-y", dev], ok_rc=(0, 1, 2))
    _run(["tune2fs", dev, "-f", "-U", ins["uuids"]["TEMP"]])
    PROGRESS.finish()
    flush_disk(disk)
    say("written in %d s" % (time.time() - PROGRESS_T0[0] if PROGRESS_T0 else 0))
    if getattr(a, "no_verify", False):
        return True
    staged = None
    if info.pad_dir:
        pad = os.path.join(m, ISO_PAD_DIR.lstrip("/"))
        try:
            _ct, _conf, build = read_pad(pad)
            staged = build.get("staged") if isinstance(build.get("staged"), dict) else None
        except Refused:
            staged = None
    return verify_disk(disk, ins, info, tpl, work, expect_staged=staged)


def _restore_slot(pieces, dev, img, uuid, work):
    """One slot: the pieces through partclone onto the partition, then the installer's tail."""
    part = img.split(".")[0]
    log = os.path.join(work, part + ".restore.log")
    rc, broken = _partclone_feed(pieces, dev, log, PROGRESS)
    if rc != 0 or broken:
        raise Refused("%s -> %s: partclone.restore failed (rc=%d)%s" % (img, dev, rc, ("\n" + _log_tail(log)) if _log_tail(log) else ""))
    if "vfat" in img:
        _finish_vfat(dev, uuid)
    else:
        _finish_ext4(dev, uuid)


def _install_menu(a, disk, facts, ins, info, pad, tpl, work):
    """--menu-only: the ISO's menu into root A of the disk - the staging `build` and `inject`
    do, onto the partition itself - and nothing else on the disk touched."""
    dev_a = part_dev(disk, ins["parts"]["ROOTA"])
    conf_text, _conf, build = read_pad(pad)
    id_a = root_identity(dev_a)
    im0 = build["images"][0] if isinstance(build["images"][0], dict) else {}
    if im0.get("game_sha256") and im0["game_sha256"] != id_a["game_sha256"] and not getattr(a, "allow_version_mismatch", False):
        raise Refused("root A on %s is not this ISO's image 0 (game %s on the disk, %s in build.json): this menu "
                      "belongs to an install of that ISO; --allow-version-mismatch writes it here anyway"
                      % (disk, id_a["game_sha256"][:12], im0["game_sha256"][:12]))
    media_dir, media = carried_media(pad, work)
    sidecars = collections.OrderedDict([(mkc.BUILD_MANIFEST, root_manifest_bytes(build))])
    if media_dir:
        with open(os.path.join(media_dir, mkc.MEDIA_MANIFEST), "rb") as f:
            sidecars[mkc.MEDIA_MANIFEST] = f.read()
    say("menu only: %s's menu -> root A (%s) of %s (%s, %s); the games, settings and scores stay"
        % (os.path.basename(info.path), dev_a, disk, facts["model"] or "no model", _gb(facts["size"])))
    if not a.yes:
        confirm_wipe(disk, facts, what="The boot menu on %s (%s, %s) is replaced; nothing else changes.")
    PROGRESS.start((media["total"] if media else 0) + 1_000_000, "menu")
    PROGRESS.step("stage", (media["total"] if media else 0) + 1_000_000)
    staged = stage_into_root(dev_a, pad, conf_text, media, sidecars, PROGRESS)
    PROGRESS.finish()
    flush_disk(disk)
    if getattr(a, "no_verify", False):
        return True
    return verify_disk(disk, ins, info, tpl, work, expect_staged=staged, fresh=False)


def _install_image(a, disk, facts, ins, info, pad, tpl, work):
    """--image N --from ISO: that slot's root restored from the ISO's own sda3 pieces (image 0:
    the menu re-staged on top), root A's build.json updated, the rest of the disk untouched."""
    n = a.image
    slot, other = ("ROOTA", "ROOTB") if n == 0 else ("ROOTB", "ROOTA")
    from_iso = os.path.abspath(a.from_iso)
    if not os.path.isfile(from_iso):
        raise Refused("%s does not exist" % from_iso)
    conf_text, conf, build = read_pad(pad)
    with IsoMount(from_iso, os.path.join(work, "from")) as mf:
        finfo = iso_info(from_iso, mf)
        finfo.check_stock_shape("--from ISO")
        if finfo.pad_dir:
            raise Refused("%s is a multi-boot ISO: --from takes the game's own install ISO (its sda3 is what goes into "
                          "slot %d); to change the menu use --menu-only" % (os.path.basename(from_iso), n))
        rec_other = build["images"][1 - n] if isinstance(build["images"][1 - n], dict) else {}
        c = finfo.piece_bytes(ROOT_PART)
        PROGRESS.start(c * 2 + 1_000_000, "image")
        PROGRESS.step("read %s's root" % os.path.basename(from_iso), c)
        raw = cached_root_raw(from_iso, getattr(a, "cache_dir", None), mf, finfo, PROGRESS)
        id_new = root_identity(raw)
        id_other = root_identity(part_dev(disk, ins["parts"][other]))
        gate_root_pair(finfo, rec_other, id_new, id_other, n, getattr(a, "allow_version_mismatch", False))
        dev = part_dev(disk, ins["parts"][slot])
        uuid = ins["uuids"][slot]
        say("image %d only: %s's root -> %s (%s) of %s (%s, %s)%s; the other image, settings and scores stay"
            % (n, os.path.basename(from_iso), slot, dev, disk, facts["model"] or "no model", _gb(facts["size"]),
               ", the menu re-staged on top" if n == 0 else ""))
        if not a.yes:
            confirm_wipe(disk, facts, what="Image %d on %%s (%%s, %%s) is replaced; the other image and the settings stay." % n)
        pieces = piece_paths(mf, finfo, ROOT_PART)
        PROGRESS.step("%s -> %s" % (ROOT_PIECE, dev), c)
        _restore_slot(pieces, dev, ROOT_PIECE, uuid, work)
        sources = [None, None]
        sources[n] = from_iso
        infos = [None, None]
        infos[n] = finfo
        idents = [None, None]
        idents[n] = id_new
        man = build_manifest(conf, sources, infos, idents, split_size=build.get("split_size"), existing=build)
        PROGRESS.step("menu", 1_000_000)
        if n == 0:
            media_dir, media = carried_media(pad, work)
            sidecars = collections.OrderedDict([(mkc.BUILD_MANIFEST, root_manifest_bytes(man))])
            if media_dir:
                with open(os.path.join(media_dir, mkc.MEDIA_MANIFEST), "rb") as f:
                    sidecars[mkc.MEDIA_MANIFEST] = f.read()
            staged = stage_into_root(dev, pad, conf_text, media, sidecars, PROGRESS)
        else:
            dev_a = part_dev(disk, ins["parts"]["ROOTA"])
            with LoopRW(dev_a) as mnt:
                p = mnt + PADSELECT_DIR + "/" + mkc.BUILD_MANIFEST
                if not os.path.isdir(os.path.dirname(p)):
                    raise Refused("root A on %s carries no %s: not a multi-boot install" % (disk, PADSELECT_DIR))
                with open(p, "wb") as f:
                    f.write(root_manifest_bytes(man))
                os.chmod(p, 0o644)
                syncfs(mnt)
            e2fsck(dev_a)
            staged = build.get("staged") if isinstance(build.get("staged"), dict) else None
        PROGRESS.finish()
        flush_disk(disk)
        if getattr(a, "no_verify", False):
            return True
        return verify_disk(disk, ins, info, tpl, work, expect_staged=staged, fresh=False,
                           expect_images={n: {"source": from_iso, "game_sha256": id_new["game_sha256"]}})





def _write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    os.chmod(path, mode)


#: The shape of JJP's jjp_install.sh (GNR 3.03, Sonic 00.925): every line `install` reads.
FAKE_INSTALLER = """#!/bin/bash
################################################################################
# Copyright (c) 2025 Jersey Jack Pinball
################################################################################
lib_path="/jjp/lib"
bin_path="/jjp/bin"
medium_path="/lib/live/mount/medium"
sgdisk_backup30="${lib_path}/backup.sgdisk1"
sgdisk_backup60="${lib_path}/backup.sgdisk2"
sgdisk_backup120="${lib_path}/backup.sgdisk3"

FS_UUID_EFI="DD8B8D65"
FS_UUID_BOOT="61af91e2-2fcf-4434-8508-4d1aaf8d2c59"
FS_UUID_ROOTA="d8223f69-d29a-474f-a837-0a11dccc27f2"
FS_UUID_ROOTB="e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87"
FS_UUID_PERMA="3930f288-dba6-4e1a-ab3d-5a23b73aae76"
FS_UUID_PERMB="bb26c099-d746-457e-abcc-dad19f55c7ab"
FS_UUID_TEMP="76695bac-6f28-4546-8fad-d3b121016394"
min_disk_size_gib="111"
ver_info_file="$medium_path/version_info.txt"
while read -r line
do
    value=$( printf "$line" | cut -d ':' -f 2 | sed 's/^[[:blank:]]*//;s/[[:blank:]]*$//' )
    case "$line" in
    Disksize*)
        min_disk_size_gib=$value
        ;;
    esac
done < "$ver_info_file"
dest_disk="/dev/sda"
part_prefix=""
disk_size=$( lsblk -dnb -o SIZE "$dest_disk" )
if [[ "$disk_size" -lt $(( $min_disk_size_gib * 1024 * 1024 * 1024 )) ]]
then
    jjp_error "Storage device $dest_disk not large enough"
fi
PART_EFI="${dest_disk}${part_prefix}1"
PART_BOOT="${dest_disk}${part_prefix}2"
PART_ROOTA="${dest_disk}${part_prefix}3"
PART_ROOTB="${dest_disk}${part_prefix}5"
PART_PERMA="${dest_disk}${part_prefix}4"
PART_PERMB="${dest_disk}${part_prefix}6"
PART_TEMP="${dest_disk}${part_prefix}7"
function check_image {
    pieces="$medium_path/home/partimag/img/$2.gz.a?"
    cat $pieces | gunzip -t
}
check_image "EFI"  "sda1.vfat-ptcl-img"
check_image "BOOT" "sda2.ext4-ptcl-img"
check_image "ROOT" "sda3.ext4-ptcl-img"
check_image "PERM" "sda4.ext4-ptcl-img"
compatible=""
if [[ "$compatible" != "true" ]]
then
    backup_to_use="$sgdisk_backup120"
    if [[ "$disk_size" -lt $((55 * 1024 * 1024 * 1024)) ]]
    then
        backup_to_use="$sgdisk_backup30"
    elif [[ "$disk_size" -lt $((111 * 1024 * 1024 * 1024)) ]]
    then
        backup_to_use="$sgdisk_backup60"
    fi
    sgdisk -Z "$dest_disk" &> /dev/null
    sgdisk --load-backup="$backup_to_use" "$dest_disk" &> /dev/null
fi
function restore_partition {
    cat $medium_path/home/partimag/img/$2.gz.a? | gunzip -c | partclone.restore -N -s - -o "$1"
    if [[ -z "${2##*vfat*}" ]]
    then
        dosfslabel -i "$1" "$3"
    else
        e2fsck -f -y "$1" &> /dev/null
        resize2fs "$1" &> /dev/null
        e2fsck -f -y "$1" &> /dev/null
        tune2fs "$1" -f -U "$3" &> /dev/null
    fi
}
restore_partition "$PART_EFI"   "sda1.vfat-ptcl-img" "$FS_UUID_EFI"
restore_partition "$PART_BOOT"  "sda2.ext4-ptcl-img" "$FS_UUID_BOOT"
restore_partition "$PART_ROOTA" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTA"
restore_partition "$PART_ROOTB" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTB"
if [[ "$compatible" != "true" ]]
then
    restore_partition "$PART_PERMA" "sda4.ext4-ptcl-img" "$FS_UUID_PERMA"
    restore_partition "$PART_PERMB" "sda4.ext4-ptcl-img" "$FS_UUID_PERMB"
fi
mkfs.ext4 -F "$PART_TEMP" &> /dev/null
e2fsck -f -y "$PART_TEMP" &> /dev/null
tune2fs "$PART_TEMP" -f -U "$FS_UUID_TEMP" &> /dev/null
halt -f
"""

#: the fake installer's UUIDs, for the fake's boot/EFI images and the self-test's checks
FAKE_UUIDS = dict(_INS_UUID_RE.findall(FAKE_INSTALLER))


def make_fake_templates(lib_dir, work=None):
    """Three sgdisk-shaped backups like JJP's (EFI, boot, root A, perm A, root B, perm B, temp)
    for 30/60/120 GB disks."""
    os.makedirs(lib_dir, exist_ok=True)
    mib = 2048
    for n, gb, root, perm, temp in ((1, 30, 9 * 1024, 256, 8 * 1024), (2, 60, 19 * 1024, 1024, 14 * 1024),
                                    (3, 120, 40 * 1024, 2 * 1024, 27 * 1024)):
        parts = [(GPT_TYPE_EFI, 94 * mib), (GPT_TYPE_LINUX, 250 * mib), (GPT_TYPE_LINUX, root * mib), (GPT_TYPE_LINUX, perm * mib),
                 (GPT_TYPE_LINUX, root * mib), (GPT_TYPE_LINUX, perm * mib), (GPT_TYPE_LINUX, temp * mib)]
        with open(os.path.join(lib_dir, "backup.sgdisk%d" % n), "wb") as f:
            f.write(make_gpt_backup(parts, gb * 1000 ** 3 // SECTOR))


def _partclone_piece(kind, raw, dest):
    """partclone.<kind> -c | gzip | split -> dest.aa (one piece)."""
    _run(["bash", "-c", 'set -o pipefail; partclone.%s -c -s "$0" -o - 2>/dev/null | gzip -c --fast | split -b 3000000 -a 2 - "$1"' % kind,
          raw, dest])

FAKE_RUNGAME = """#!/bin/dash
export JJPEDIR='/jjpe/gen1'
. $JJPEDIR/setenv.sh
export GAMEDIR=$JJPEDIR/$GAMENAME
chmod +x $JJPEDIR/scripts/runonce.sh
$JJPEDIR/scripts/runonce.sh
while true
do
  $GAMEDIR/game
  result="$?"
  case "$result" in
    42) # net img or delta update
        reboot
        sleep 99 ;;
    68) # maintenance reboot (hostname set)
        reboot
        sleep 99 ;;
    69) # maintenance reboot
        reboot
        sleep 99 ;;
  esac
done
"""

FAKE_CFG = ("label Clonezilla live with img\n  kernel /live/vmlinuz\n"
            "  append initrd=/live/initrd.img boot=live ocs_prerun=\"sudo mount --bind /lib/live/mount/medium/home/partimag /home/partimag\" "
            + OCS_STOCK + " ocs_live_batch=yes\n")


def make_fake_iso(work, name, version, game_bytes, edata_bytes, size_mb=64):
    """A synthetic JJP install ISO: a real ext4 root (mke2fs -d) partcloned into sda3 pieces,
    gzip'd fillers for the other partitions, a squashfs with the installer, both cfgs."""
    need_tools("mke2fs", "partclone.ext4", "partclone.vfat", "mkfs.vfat", "gzip", "split", "mksquashfs", "xorriso")
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
    # EFI: a vfat with the shipped volume id and a loader; boot: grub set to slot a with root A's
    # UUID and a "kernel"; perm: an ext4 with vf/ - small images `install` grows into the slots
    efi_raw = os.path.join(d, "sda1.raw")
    with open(efi_raw, "wb") as f:
        f.truncate(40 << 20)
    _run(["mkfs.vfat", "-F", "32", "-i", FAKE_UUIDS["EFI"], efi_raw])
    emnt = tempfile.mkdtemp(prefix=MOUNT_PREFIX)
    try:
        _run(["mount", "-o", "loop", efi_raw, emnt])
        try:
            _write(os.path.join(emnt, "EFI", "BOOT", "BOOTX64.EFI"), b"not a loader\n")
        finally:
            _run(["umount", emnt])
    finally:
        os.rmdir(emnt)
    _partclone_piece("vfat", efi_raw, os.path.join(img, "sda1.vfat-ptcl-img.gz."))
    boot_tree = os.path.join(d, "boot_tree")
    _write(os.path.join(boot_tree, "grub", "curgrub"), "a\n")
    _write(os.path.join(boot_tree, "grub", "grub.cfg"), "search --no-floppy --fs-uuid --set=root %s\nlinux /vmlinuz root=UUID=%s ro quiet\n"
           % (FAKE_UUIDS["ROOTA"], FAKE_UUIDS["ROOTA"]))
    _write(os.path.join(boot_tree, "vmlinuz"), b"not a kernel\n")
    boot_raw = os.path.join(d, "sda2.raw")
    with open(boot_raw, "wb") as f:
        f.truncate(48 << 20)
    _run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", boot_tree, "-L", "boot", boot_raw])
    _partclone_piece("ext4", boot_raw, os.path.join(img, "sda2.ext4-ptcl-img.gz."))
    perm_tree = os.path.join(d, "perm_tree")
    _write(os.path.join(perm_tree, "vf", "settings.dat"), b"factory\n")
    perm_raw = os.path.join(d, "sda4.raw")
    with open(perm_raw, "wb") as f:
        f.truncate(32 << 20)
    _run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", perm_tree, "-L", "perm", perm_raw])
    _partclone_piece("ext4", perm_raw, os.path.join(img, "sda4.ext4-ptcl-img.gz."))
    for p in (efi_raw, boot_raw, perm_raw):
        os.unlink(p)
    shutil.rmtree(boot_tree)
    shutil.rmtree(perm_tree)
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
    make_fake_templates(os.path.join(sq, SQ_LIB), d)
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
    need_tools("partclone.ext4", "partclone.restore", "partclone.vfat", "gunzip", "split", "e2fsck", "losetup", "mount",
               "umount", "debugfs", "xorriso", "unsquashfs", "mksquashfs", "mke2fs", "mkfs.vfat", "resize2fs",
               "tune2fs", "mkfs.ext4", "blkid", "blockdev")
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
    edata0 = os.urandom(400000)
    iso0, raw0 = make_fake_iso(work, "fake0-v03.03", "03.03", game, edata0)
    edata1 = os.urandom(600000)
    iso1, raw1 = make_fake_iso(work, "fake1_custom", "03.03", game, edata1)
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
    expect("rungame.sh hooked once after runonce", hook_line_count(rg) == 1 and rg.index(RUNONCE_LINE) < rg.index(HOOK_LINES[2]))
    rgl = rg.split("\n")
    expect("the two maintenance reboots tell the hook first, the update reboot does not",
           rg.count(MAINT_CALL) == 2 and all(rgl[i + 1].strip() == "reboot" for i, ln in enumerate(rgl) if ln.strip() == MAINT_CALL)
           and rgl[rgl.index("    42) # net img or delta update") + 1].strip() == "reboot")
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
    # install: the multi ISO onto a "disk" - a 120 GB sparse file on a loop device, the block
    # device a docked SSD is once the app attaches it - exactly as pad_install.sh lays it out
    ins = parse_installer(FAKE_INSTALLER)
    expect("parse_installer reads the fake installer's seven slots and six restores",
           sorted(ins["parts"].values()) == [1, 2, 3, 4, 5, 6, 7] and len(ins["restores"]) == 6 and ins["default"] == "120"
           and ins["choices"] == [(55, "30"), (111, "60")] and ins["min_disk_gib"] == 111)
    disk_raw = os.path.join(work, "disk.raw")
    with open(disk_raw, "wb") as f:
        f.truncate(120 * 1000 ** 3)
    loop = _run(["losetup", "-P", "--find", "--show", disk_raw]).strip().splitlines()[-1]
    try:
        ns4 = argparse.Namespace(iso=out, disk=loop, yes=True, no_verify=False, workdir=os.path.join(work, "winstall"),
                                 menu_only=False, image=None, from_iso=None, allow_version_mismatch=False, cache_dir=cache)
        rc = install_disk(ns4)
        expect("install onto %s returns 0 (its verify PASSED)" % loop, rc == 0)
        with DevMount(part_dev(loop, ins["parts"]["ROOTB"])) as mb:
            with open(os.path.join(mb, "jjpe", "gen1", "GunsNRoses", "edata", "graphics", "Attract Mode", "a.bin"), "rb") as f:
                expect("root B on the disk is image 1's root (its edata)", sha256_bytes(f.read()) == sha256_bytes(edata1))
        with DevMount(part_dev(loop, ins["parts"]["ROOTA"])) as ma:
            expect("root A on the disk is image 0's root with the menu",
                   os.path.isfile(os.path.join(ma, "jjpe", "gen1", "GunsNRoses", "game")) and os.path.isfile(os.path.join(ma, PADSELECT_DIR.lstrip("/"), "jjpselect")))
            try:
                install_disk(ns4)
                expect("a disk with a mount on it is refused", False)
            except Refused as e:
                expect("a disk with a mount on it is refused", "in use" in str(e), str(e)[:100])
        with DevMount(part_dev(loop, ins["parts"]["PERMA"])) as mp:
            expect("perm A on the disk is the factory perm image", os.path.isfile(os.path.join(mp, "vf", "settings.dat")))
        # item 124: the menu alone, then one image alone, onto that installed disk - a "score"
        # planted in perm A must survive both
        edata_path = os.path.join("jjpe", "gen1", "GunsNRoses", "edata", "graphics", "Attract Mode", "a.bin")

        def edata_on(slot):
            with DevMount(part_dev(loop, ins["parts"][slot])) as mm:
                with open(os.path.join(mm, edata_path), "rb") as f:
                    return sha256_bytes(f.read())

        def perm_marker():
            with DevMount(part_dev(loop, ins["parts"]["PERMA"])) as mm:
                return os.path.isfile(os.path.join(mm, "vf", "marker.dat"))

        with LoopRW(part_dev(loop, ins["parts"]["PERMA"])) as mp:
            _write(os.path.join(mp, "vf", "marker.dat"), b"a score\n")
        with LoopRW(part_dev(loop, ins["parts"]["TEMP"])) as mt:
            _write(os.path.join(mt, "game.log"), b"the machine booted\n")       # a partial write leaves the logs alone
        ns5 = argparse.Namespace(**dict(vars(ns2), titles="Stock3;Custom3", workdir=os.path.join(work, "winject2")))
        expect("inject (new titles for the menu-only leg) returns 0", inject_iso(ns5) == 0)
        disk_ns = dict(iso=out, disk=loop, yes=True, no_verify=False, menu_only=False, image=None, from_iso=None,
                       allow_version_mismatch=False, cache_dir=cache)
        rc = install_disk(argparse.Namespace(**dict(disk_ns, menu_only=True, workdir=os.path.join(work, "wmenu"))))
        expect("install --menu-only returns 0 (its verify PASSED)", rc == 0)
        with DevMount(part_dev(loop, ins["parts"]["ROOTA"])) as ma:
            with open(os.path.join(ma, PADSELECT_DIR.lstrip("/"), "images.conf"), "r", encoding="utf-8") as f:
                expect("--menu-only: root A's menu carries the new titles", "Stock3" in f.read())
            with open(os.path.join(ma, RUNGAME.lstrip("/")), "r") as f:
                expect("--menu-only: rungame.sh still hooked once", hook_line_count(f.read()) == 1)
        expect("--menu-only: root B untouched (image 1's edata)", edata_on("ROOTB") == sha256_bytes(edata1))
        expect("--menu-only: perm A kept (the score)", perm_marker())
        rc = install_disk(argparse.Namespace(**dict(disk_ns, image=1, from_iso=iso0, workdir=os.path.join(work, "wimg1"))))
        expect("install --image 1 --from fake0 returns 0 (its verify PASSED)", rc == 0)
        expect("--image 1: root B is now fake0's root (its edata)", edata_on("ROOTB") == sha256_bytes(edata0))
        expect("--image 1: root A untouched (image 0's edata)", edata_on("ROOTA") == sha256_bytes(edata0))
        with DevMount(part_dev(loop, ins["parts"]["ROOTA"])) as ma:
            man = parse_manifest(open(os.path.join(ma, PADSELECT_DIR.lstrip("/"), mkc.BUILD_MANIFEST), "rb").read(), "build.json")
            expect("--image 1: root A's build.json records image 1 from fake0", man["images"][1]["source"] == iso0
                   and man["images"][1]["game_sha256"] == sha256_bytes(game) and "staged" not in man)
        expect("--image 1: perm A kept (the score)", perm_marker())
        try:
            install_disk(argparse.Namespace(**dict(disk_ns, image=1, from_iso=iso2, workdir=os.path.join(work, "wimg1b"))))
            expect("--image 1 from a different version is refused", False)
        except Refused as e:
            expect("--image 1 from a different version is refused", "not be the same game code" in str(e), str(e)[:120])
        expect("...and root B is untouched by the refusal", edata_on("ROOTB") == sha256_bytes(edata0))
        rc = install_disk(argparse.Namespace(**dict(disk_ns, image=0, from_iso=iso1, workdir=os.path.join(work, "wimg0"))))
        expect("install --image 0 --from fake1 returns 0 (its verify PASSED)", rc == 0)
        expect("--image 0: root A is now fake1's root (its edata)", edata_on("ROOTA") == sha256_bytes(edata1))
        with DevMount(part_dev(loop, ins["parts"]["ROOTA"])) as ma:
            expect("--image 0: the menu re-staged on the new root A",
                   os.path.isfile(os.path.join(ma, PADSELECT_DIR.lstrip("/"), "jjpselect")) and os.path.isfile(os.path.join(ma, HOOK_PATH.lstrip("/"))))
            with open(os.path.join(ma, RUNGAME.lstrip("/")), "r") as f:
                expect("--image 0: rungame.sh hooked once", hook_line_count(f.read()) == 1)
        expect("--image 0: perm A kept (the score)", perm_marker())
        with DevMount(part_dev(loop, ins["parts"]["TEMP"])) as mt:
            expect("the partial writes left the machine's log on temp alone", os.path.isfile(os.path.join(mt, "game.log")))
        try:
            install_disk(argparse.Namespace(**dict(disk_ns, image=1, from_iso=out, workdir=os.path.join(work, "wimg1c"))))
            expect("--from a multi-boot ISO is refused", False)
        except Refused as e:
            expect("--from a multi-boot ISO is refused", "is a multi-boot ISO" in str(e), str(e)[:100])
    finally:
        subprocess.run(["losetup", "-d", loop], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    blank = os.path.join(work, "blank.raw")
    with open(blank, "wb") as f:
        f.truncate(120 * 1000 ** 3)
    loop = _run(["losetup", "-P", "--find", "--show", blank]).strip().splitlines()[-1]
    try:
        install_disk(argparse.Namespace(iso=out, disk=loop, yes=True, no_verify=False, workdir=None, menu_only=True, image=None,
                                        from_iso=None, allow_version_mismatch=False, cache_dir=cache))
        expect("--menu-only onto a blank disk is refused", False)
    except Refused as e:
        expect("--menu-only onto a blank disk is refused", "not a JJP disk" in str(e), str(e)[:100])
    finally:
        subprocess.run(["losetup", "-d", loop], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(blank)
    os.unlink(disk_raw)
    small = os.path.join(work, "small.raw")
    with open(small, "wb") as f:
        f.truncate(20 * 1000 ** 3)
    loop = _run(["losetup", "--find", "--show", small]).strip().splitlines()[-1]
    try:
        install_disk(argparse.Namespace(iso=out, disk=loop, yes=True, no_verify=False, workdir=None, menu_only=False, image=None,
                                        from_iso=None, allow_version_mismatch=False, cache_dir=cache))
        expect("a disk under Disksize is refused", False)
    except Refused as e:
        expect("a disk under Disksize is refused", "at least 111 GiB" in str(e), str(e)[:100])
    finally:
        subprocess.run(["losetup", "-d", loop], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(small)
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
    # The selector's own log ON THE MACHINE - on by default from 2026-09-14, while the GNR's
    # menu was silent and nothing on the machine could say why, off again since 2026-09-15
    # (everything working; David: turn the logs off).  It is bounded (one file
    # per boot plus the previous one, 1 MB each, ~8 KB a boot) and JJP's own dumplogs.sh
    # copies /jjpe/temp/*.log* onto a stick, so it can be read without opening the machine.
    for name in KEY_NAMES:
        s.add_argument("--" + name.replace("_", "-"), dest=name, metavar="BYTE.BIT[,BYTE.BIT]",
                       help="images.conf %s=: where this machine's %s button sits in the I/O board frame "
                            "(<0-63>.<0-7>, as the menu's --learn line names it; a comma and a second "
                            "position is the same button in a second place, e.g. the GNR's Action "
                            "button as a second START: --key-start 3.0,3.4); default: the selector's own"
                            % (name, name[4:].upper()))
    s.add_argument("--machine-log", dest="debug_log", action="store_true", default=False,
                   help="the selector's own log on the machine (images.conf log=%s, bounded; JJP's "
                        "Utilities log dump collects it); off by default" % JJP_CARD_LOG)
    s.add_argument("--no-machine-log", dest="debug_log", action="store_false", help=argparse.SUPPRESS)
    s.add_argument("--debug-log", dest="debug_log", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--learn", action="store_true", default=False,
                   help="images.conf learn=1: the hook runs the menu with --learn - the I/O board frame's "
                        "changes and any unmapped bit into the selector log, for reading a new machine's "
                        "buttons off it (implies --machine-log)")


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
    s = sub.add_parser("install", help="write an install ISO onto a disk (a docked SSD) the way JJP's installer does on "
                                       "the machine, then verify it (root; WIPES the disk)")
    s.add_argument("--iso", required=True, help="a multi-boot ISO (root B = image 1) or a stock JJP install ISO (root B = a copy of A)")
    s.add_argument("--disk", required=True, metavar="/dev/sdX", help="the whole disk (sdX, nvmeXnY, loopN with -P); every byte on it goes")
    s.add_argument("--yes", action="store_true", help="write without the typed confirmation (no terminal = required)")
    s.add_argument("--menu-only", action="store_true", dest="menu_only",
                   help="only the boot menu, into root A of a disk that already holds this ISO's install "
                        "(a multi-boot ISO; inject it first for a new menu); the games, settings and scores stay")
    s.add_argument("--image", type=int, metavar="N",
                   help="only image N's root (0 = root A, the menu re-staged on top; 1 = root B), restored from --from "
                        "onto a disk that already holds this ISO's install; the other image, settings and scores stay")
    s.add_argument("--from", dest="from_iso", metavar="ISO", help="the game's own install ISO whose root goes into --image N")
    s.add_argument("--allow-version-mismatch", action="store_true",
                   help="--image / --menu-only although the game code differs (read the refusal first)")
    s.add_argument("--cache-dir", help="where --from's root is restored for its identity (default %s, the rig's)" % CACHE_DIR_DEFAULT)
    s.add_argument("--no-verify", action="store_true", dest="no_verify", help="skip reading the disk back afterwards")
    s.add_argument("--workdir", help="scratch for the ISO mount, the installer and the logs (default: a temp dir)")
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
        if a.cmd == "install":
            return install_disk(a)
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
