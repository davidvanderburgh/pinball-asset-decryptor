#!/usr/bin/env python3
"""mks3multi.py - a Stern Spike 3 multi-boot card (PAD-1263).

Several Spike 3 card images on ONE card, with a boot menu the machine shows at
power-up: the coin door's NEXT / PREVIOUS move, SELECT boots, the countdown
boots the remembered choice. The menu is the code selector the Spike 2 card,
JJP, Barrels of Fun, Dutch Pinball and Spooky machines carry
(tools/spike2_emu/codeselect), built for this machine as `s3select`
(`make PLATFORM=s3`, ensures3select.sh). MULTIBOOT.md beside this file is the
design; this is its builder.

WHAT A SPIKE 3 MULTI-BOOT CARD IS. A copy of image 0's card in which only
the games partition (p6, LUKS2 over ext4) differs:

    /games/pad/img0/      image 0's games tree, moved here whole
    /games/pad/img1/ ...  every other image's games tree, copied whole
    /games/pad/s3select   the menu, padselect.sh (the hook), font.ttf,
                          images.conf, media/, build.json
    /games/game           -> pad/padselect.sh   (game_monitor runs this)
    /games/conagent, data, spike3, spk  -> pad/img0/...  (what the boot splash
                          and conagent look for before the menu has run)

The signed boot partition and the rootfs are image 0's, byte for byte: every
image runs on image 0's rootfs (all eleven cards measured carry Buildroot
2024.08.1). The hook bind-mounts the chosen tree over /games, so each game
sees exactly the tree it shipped in.

    mks3multi.py plan  --primary A.raw --extra B.raw [--extra ...] [--keyfile K]
    mks3multi.py build --primary A.raw --extra B.raw ... --out OUT.raw
                       --selector-dir DIR [--keyfile K] [--titles ...] [...]
    mks3multi.py verify --card OUT.raw [--primary A.raw --extra ...] [--keyfile K]
    mks3multi.py media  --primary A.raw --extra ... --out DIR [...]

`build` and `verify` need root (losetup, the dm-crypt mapping, mount);
`plan` reads the cards with PAD's own decryptor and needs nothing.

THE KEY. The user's own board key (padkeys.json with `otp_keyfile`), the one
Extract and Emulate use: --keyfile, else $PAD_SPIKE3_KEYFILE, a padkeys.json
beside the card, ~/.pad/spike3_padkeys.json. It unwraps each card's games
volume key in this process; the volume key goes to the kernel's dm-crypt
through an ioctl and is never written to a file.
"""
import argparse
import collections
import contextlib
import datetime
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "tools", "spike2_emu"), os.path.join(ROOT, "tools", "bof_emu")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mkmulticard as mkc                                           # noqa: E402  the shared pure parts
from mkmulticard import Refused, PROGRESS                           # noqa: E402
import mkbofmulti as bof                                            # noqa: E402  the conf writer

TOOL = "mks3multi"
#: build.json's shape; a reader must accept an older (or missing) one.
VERSION = "1.0"
PAD = "pad"                                    # /games/pad on the card
PAD_DIR = "/games/" + PAD
MEDIA_DIR = PAD_DIR + "/media"
MAX_IMAGES = 9
VOLUME_DEFAULT = 50
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
#: the files of --selector-dir (ensures3select.sh installs them) -> (mode, required)
SELECTOR_FILES = collections.OrderedDict([
    ("s3select", (0o755, True)),
    ("padselect.sh", (0o755, True)),
    ("font.ttf", (0o644, False)),
])
#: the top-level links of a multi-boot games partition: the hook, and what
#: S95game / conagent_monitor look for before the menu has bound a tree
TOP_LINKS = collections.OrderedDict([
    ("game", PAD + "/padselect.sh"),
    ("conagent", PAD + "/img0/conagent"),
    ("data", PAD + "/img0/data"),
    ("spike3", PAD + "/img0/spike3"),
    ("spk", PAD + "/img0/spk"),
])
#: the coin door's service buttons are what the menu reads (stubs_s3.c); the
#: Spike 3 menu's OWN footer says this (codeselect.c SEL_COIN_DOOR), so a card
#: whose conf names no footer= draws it too
FOOTER = "NEXT / PREVIOUS: choose      SELECT: boot"
CONF_HEADER = [
    "# images.conf - the Spike 3 boot menu (s3select + padselect.sh); written by mks3multi.py",
    "# image=<dir>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
    "# <dir> = the games tree in /games/pad that is bound over /games when it is chosen;",
    "# default = highlight when there is no last choice; timeout = seconds before it boots by itself"]
#: SD card sizes a Spike 3 card is written to (the cards are 64G images)
CARD_SIZES = collections.OrderedDict([("64G", 61_924_705_792), ("128G", 124_000_000_000)])
SECTOR = 512


def say(msg):
    print("[card] " + msg, flush=True)


def _gb(n):
    return "%.2f GB" % (n / 1e9)


def split_list(s):
    if s is None:
        return []
    return [x.strip() for x in s.split(";")]


# ============================================================================== the cards
def _s3():
    from pinball_decryptor.plugins.stern import spike3 as s3
    return s3


def _card_mod():
    from pinball_decryptor.plugins.stern import spike3_card
    return spike3_card


def _key_source(keyfile, image_path):
    from pinball_decryptor.plugins.stern.spike3_keys import Spike3KeySource
    card = _card_mod()
    iid = card.image_id(image_path)
    path = keyfile or os.environ.get("PAD_SPIKE3_KEYFILE") or ""
    if path:
        if not os.path.isfile(path):
            raise Refused("--keyfile %s does not exist" % path)
        return Spike3KeySource.from_keyfile(path, image_id=iid)
    ks = Spike3KeySource.discover(image_path=image_path, image_id=iid)
    if ks is None or not ks.has_any():
        raise Refused("no Spike 3 key for %s: unlock a card in the Extract tab first (your own "
                      "board's key), or give --keyfile" % os.path.basename(image_path))
    return ks


class Card:
    """One Spike 3 card image: its games volume's place, size, key and fill."""

    def __init__(self, path, keyfile=None):
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise Refused("%s does not exist" % path)
        card = _card_mod()
        try:
            vol = card.open_games(self.path, key_source=_key_source(keyfile, self.path))
        except Refused:
            raise
        except Exception as e:                   # Spike3KeyError, ValueError: say which card
            raise Refused("%s: %s" % (os.path.basename(path), e))
        try:
            self.iid = card.image_id(self.path)
            self.size = os.path.getsize(self.path)
            self.part_offset = vol.part_offset
            self.part_bytes = vol.part["sectors"] * SECTOR
            self.segment_offset = vol.segment_offset
            self.key = bytes(vol.master_key)
            self.cipher = "aes-xts-plain64"
            sb = self._superblock(vol)
        finally:
            vol.close()
        self.block = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
        blocks = struct.unpack_from("<I", sb, 0x04)[0] | (struct.unpack_from("<I", sb, 0x150)[0] << 32)
        free = struct.unpack_from("<I", sb, 0x0C)[0] | (struct.unpack_from("<I", sb, 0x158)[0] << 32)
        if struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
            raise Refused("%s: its games partition is not ext4" % os.path.basename(path))
        self.fs_bytes = blocks * self.block
        self.used = (blocks - free) * self.block
        m = re.match(r"^([a-z0-9_]+?)-(\d+(?:_\d+)*)", self.iid)
        self.title = m.group(1) if m else self.iid
        self.version = m.group(2).replace("_", ".") if m else ""

    @staticmethod
    def _superblock(vol):
        vol.seek(1024)
        return vol.read(1024)

    def label(self):
        return "%s %s" % (self.title.replace("_", " ").upper(), self.version)


def _inputs(a):
    paths = [a.primary] + list(a.extra or [])
    if len(paths) < 2:
        raise Refused("a multi-boot card needs at least two images (--primary and an --extra)")
    if len(paths) > MAX_IMAGES:
        raise Refused("at most %d images on one card" % MAX_IMAGES)
    seen = set()
    for p in paths:
        n = os.path.normcase(os.path.abspath(p))
        if n in seen:
            raise Refused("%s is given twice" % p)
        seen.add(n)
    return [Card(p, getattr(a, "keyfile", None)) for p in paths]


# ============================================================================== the plan
def menu_bytes(media):
    return 4_000_000 + (media["total"] if media else 0)


def make_plan(a):
    cards = _inputs(a)
    media = mkc.plan_media(a.media_dir, len(cards)) if getattr(a, "media_dir", None) else None
    p0 = cards[0]
    # the copies land beside image 0's tree in its own games filesystem; ext4
    # keeps ~5 % for root and the trees' metadata grows, so a tenth is held back
    room = p0.fs_bytes - p0.used
    need = sum(c.used for c in cards[1:]) + menu_bytes(media)
    return {"cards": cards, "media": media, "room": room, "need": need,
            "fits": need * 1.10 + (256 << 20) <= room, "total": p0.size}


def print_plan(plan):
    cards = plan["cards"]
    print("== layout: image 0's card with every image's games tree in its games partition "
          "(/games/pad/imgN); the boot and rootfs partitions are image 0's, untouched")
    print("== game code versions")
    for i, c in enumerate(cards):
        print("  %d  img%d  %s  %s  %s" % (i, i, os.path.basename(c.path), c.title, c.version))
    titles = {c.title for c in cards}
    if len(titles) > 1:
        print("note: the images are of %d titles (%s): each needs the machine it was made for"
              % (len(titles), ", ".join(sorted(titles))))
    if any(c.version != cards[0].version for c in cards[1:]):
        print("note: every image runs on image 0's rootfs (%s %s)" % (cards[0].title, cards[0].version))
    print("== bytes in the games partition")
    print("image-size 0 img0 %d %s, already on the card" % (cards[0].used, cards[0].iid))
    for i, c in enumerate(cards[1:], 1):
        print("image-size %d img%d %d %s's games tree" % (i, i, c.used, c.iid))
    print("image-size overhead %d the menu and its pictures" % menu_bytes(plan["media"]))
    print("games-room %d free in image 0's games partition, %d needed (%s)"
          % (plan["room"], plan["need"], "fits" if plan["fits"] else "TOO BIG"))
    print("card-size %d the card image (image 0's size)" % plan["total"])
    best = None
    for k, cap in CARD_SIZES.items():
        ok = plan["fits"] and plan["total"] <= cap
        print("fits SD %s card size %d: %s (spare %d)" % (k, cap, "YES" if ok else "NO", cap - plan["total"]))
        if ok and best is None:
            best = k
    print("card: %s" % (best or "none: the images do not fit in one games partition"))


# ============================================================================== the conf
def render_conf(dirs, titles, subtitles, default, timeout, rows, sound_move, sound_confirm, volume, **kw):
    text = bof.render_conf(dirs, titles, subtitles, default, timeout, rows, sound_move, sound_confirm,
                           volume, collections.OrderedDict(), header=CONF_HEADER, font=False, **kw)
    # bof writes ITS media folder; the menu's pictures live in /games/pad/media here
    return re.sub(r"(?m)^media=.*$", "media=" + MEDIA_DIR, text)


def parse_conf(text):
    return bof.parse_conf(text)


def default_titles(cards):
    return ["%s|%s" % (c.label(), "Stock" if i == 0 else os.path.basename(c.path).split(".", 1)[0])
            for i, c in enumerate(cards)]


def conf_from_args(a, cards, media):
    dirs = ["img%d" % i for i in range(len(cards))]
    if getattr(a, "conf", None):
        with open(a.conf, encoding="utf-8") as f:
            text = f.read()
        if [p for p, _t, _s in parse_conf(text)["images"]] != dirs:
            raise Refused("--conf %s does not list %r" % (a.conf, dirs))
        return text
    dt = [t.split("|", 1) for t in default_titles(cards)]
    titles = split_list(a.titles) or [t for t, _s in dt]
    subtitles = split_list(a.subtitles) if a.subtitles is not None else [s for _t, s in dt]
    rows, move, confirm, volume = ([], None, None, None)
    if media:
        rows, move, confirm, volume = media["rows"], media["sound_move"], media["sound_confirm"], media["volume"]
    if a.volume is not None:
        volume = a.volume
    # no footer= at all: the menu's own, which on Spike 3 names the coin door
    footer = None if a.footer_own else a.footer
    return render_conf(dirs, titles, subtitles, a.default or 0, 15 if a.timeout is None else a.timeout,
                       rows, move, confirm, volume, theme=a.theme, colors=mkc.parse_color_flags(a.color),
                       heading=a.heading, text_size=a.text_size, counter=a.counter,
                       countdown_word=a.countdown_word, footer=footer)


def check_selector_dir(d):
    if not d or not os.path.isdir(d):
        raise Refused("--selector-dir %s is not a directory (ensures3select.sh installs one)" % d)
    for name, (_mode, required) in SELECTOR_FILES.items():
        if required and not os.path.isfile(os.path.join(d, name)):
            raise Refused("--selector-dir %s has no %s (ensures3select.sh installs it)" % (d, name))


def _font_src(selector_dir):
    src = os.path.join(selector_dir, "font.ttf")
    if os.path.isfile(src):
        return src
    if os.path.isfile(HOST_FONT):
        return HOST_FONT
    raise Refused("no font.ttf in %s and no %s on this Linux: the menu would have nothing to draw its "
                  "words with (apt install fonts-dejavu-core)" % (selector_dir, HOST_FONT))


# ============================================================================== root: the volumes
def _run(cmd, **kw):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    if r.returncode:
        raise Refused("%s failed: %s" % (" ".join(cmd[:2]), r.stderr.decode(errors="replace").strip()))
    return r.stdout.decode(errors="replace").strip()


def _need_root():
    if os.geteuid() != 0:
        raise Refused("this step needs root (losetup, dm-crypt, mount): run it as root in WSL")


@contextlib.contextmanager
def games_mounted(card, image, writable, mnt):
    """*image*'s games partition (laid out as *card*'s) mapped through dm-crypt
    and mounted at *mnt*; everything undone on the way out."""
    from pinball_decryptor.core import dmcrypt
    _need_root()
    subprocess.run(["modprobe", "dm_crypt"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists("/dev/mapper/control"):
        raise Refused("this Linux has no device-mapper (/dev/mapper/control): the card cannot be opened")
    name = "pad1263_%s_%d" % ("rw" if writable else "ro", os.getpid()) + "_" + uuid.uuid4().hex[:6]
    loop = dm = None
    mounted = False
    try:
        loop = _run(["losetup", "-f", "--show"] + ([] if writable else ["-r"]) +
                    ["-o", str(card.part_offset), "--sizelimit", str(card.part_bytes), image])
        length = (card.part_bytes - card.segment_offset) // SECTOR
        dm = dmcrypt.open_crypt(name, loop, card.segment_offset // SECTOR, length, card.key,
                                readonly=not writable)
        os.makedirs(mnt, exist_ok=True)
        _run(["mount", "-t", "ext4", "-o", "rw" if writable else "ro,noload", dm, mnt])
        mounted = True
        yield mnt
    finally:
        if mounted:
            subprocess.run(["sync", "-f", mnt])
            subprocess.run(["umount", mnt])
        if dm:
            dmcrypt.close_crypt(name)
        if loop:
            subprocess.run(["losetup", "-d", loop])
        with contextlib.suppress(OSError):
            os.rmdir(mnt)


def _tree_bytes(d):
    n = files = 0
    for root, dirs, fs in os.walk(d):
        for f in fs:
            p = os.path.join(root, f)
            if not os.path.islink(p):
                with contextlib.suppress(OSError):
                    n += os.lstat(p).st_size
                    files += 1
    return n, files


def _tree_manifest(d):
    """{relative path: (kind, size or link target)} of a games tree."""
    out = {}
    for root, dirs, fs in os.walk(d):
        for name in dirs + fs:
            p = os.path.join(root, name)
            rel = os.path.relpath(p, d)
            if os.path.islink(p):
                out[rel] = ("l", os.readlink(p))
            elif os.path.isdir(p):
                out[rel] = ("d", 0)
            else:
                out[rel] = ("f", os.lstat(p).st_size)
    return out


def _copy_image_file(src, dst, total):
    """The card copy, metered; an all-zero MiB is skipped (a hole where the
    filesystem allows one), so a fresh copy costs no more than its data."""
    CH = 8 << 20
    PROGRESS.step("copying image 0's card", total)
    zero = bytes(CH)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(CH)
            if not b:
                break
            if b == zero[:len(b)]:
                fo.seek(len(b), 1)
            else:
                fo.write(b)
            PROGRESS.add(len(b))
        fo.truncate(fi.tell())


def _lay_out(mnt, conf, selector_dir, media, media_dir, build_doc):
    """image 0's tree into pad/img0, the menu into pad/, the top-level links"""
    pad = os.path.join(mnt, PAD)
    if os.path.lexists(pad):
        raise Refused("image 0's games partition already has a /games/pad: is it a multi-boot card already?")
    img0 = os.path.join(pad, "img0")
    os.makedirs(img0)
    for name in sorted(os.listdir(mnt)):
        if name in (PAD, "lost+found"):
            continue
        os.rename(os.path.join(mnt, name), os.path.join(img0, name))
    if not os.path.lexists(os.path.join(img0, "game")):
        raise Refused("image 0's games partition has no `game` link: not a Spike 3 games tree")
    for name, (mode, _req) in SELECTOR_FILES.items():
        src = os.path.join(selector_dir, name) if name != "font.ttf" else _font_src(selector_dir)
        shutil.copyfile(src, os.path.join(pad, name))
        os.chmod(os.path.join(pad, name), mode)
    with open(os.path.join(pad, "images.conf"), "w", encoding="utf-8", newline="\n") as f:
        f.write(conf)
    if media:
        md = os.path.join(pad, "media")
        os.makedirs(md, exist_ok=True)
        for fn in media["files"]:
            shutil.copyfile(os.path.join(media_dir, fn), os.path.join(md, fn))
    with open(os.path.join(pad, "build.json"), "w", encoding="utf-8") as f:
        json.dump(build_doc, f, indent=1)


def _link_top(mnt):
    for name, target in TOP_LINKS.items():
        p = os.path.join(mnt, name)
        if os.path.lexists(p):
            os.unlink(p)
        os.symlink(target, p)


def build_card(a):
    _need_root()
    plan = make_plan(a)
    cards, media = plan["cards"], plan["media"]
    if not plan["fits"]:
        raise Refused("the images need %s and image 0's games partition has %s free"
                      % (_gb(plan["need"]), _gb(plan["room"])))
    check_selector_dir(a.selector_dir)
    out = os.path.abspath(a.out)
    for c in cards:
        if os.path.normcase(c.path) == os.path.normcase(out):
            raise Refused("--out is one of the images")
    if os.path.exists(out) and not a.force:
        raise Refused("%s exists (--force replaces it)" % out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    free = shutil.disk_usage(os.path.dirname(out) or ".").free
    if free < cards[0].size + (1 << 30):
        raise Refused("%s has %s free; the card needs %s" % (os.path.dirname(out), _gb(free), _gb(cards[0].size)))
    conf = conf_from_args(a, cards, media)
    if media:
        for fn in media["files"]:
            if not os.path.isfile(os.path.join(a.media_dir, fn)):
                raise Refused("--media-dir %s has no %s" % (a.media_dir, fn))
    build_id = uuid.uuid4().hex
    doc = {"tool": TOOL, "version": VERSION, "built": datetime.datetime.now().isoformat(timespec="seconds"),
           "build_id": build_id, "images": [
               {"dir": "img%d" % i, "card": os.path.basename(c.path), "title": c.title,
                "version": c.version, "bytes": c.used} for i, c in enumerate(cards)]}
    print_plan(plan)
    work = sum(c.used for c in cards[1:])
    PROGRESS.start(cards[0].size + work, "building")
    # THE LOOP DEVICE STAYS ON THE LINUX SIDE: the build maps the card through
    # a loop device, and one over a file on a Windows drive (/mnt/<drive>, 9p)
    # is the one place this tool must never put one (the JJP builder's rule).
    # A Windows --out is built in --workdir and copied there once finished.
    on_windows = bool(re.match(r"^/mnt/[a-z]/", out))
    if on_windows:
        wd = os.path.abspath(a.workdir or "/var/tmp/pad_s3multi")
        os.makedirs(wd, exist_ok=True)
        wfree = shutil.disk_usage(wd).free
        if wfree < cards[0].size + (1 << 30):
            raise Refused("the work folder %s has %s free; the card needs %s (give --workdir on a bigger Linux disk)"
                          % (wd, _gb(wfree), _gb(cards[0].size)))
        part = os.path.join(wd, os.path.basename(out) + ".part")
        PROGRESS.start(2 * cards[0].size + work, "building")
    else:
        part = out + ".part"
    t0 = time.time()
    say("copying %s (%s) to %s" % (os.path.basename(cards[0].path), _gb(cards[0].size), part))
    _copy_image_file(cards[0].path, part, cards[0].size)
    tmp = tempfile.mkdtemp(prefix="pad_s3multi_", dir="/var/tmp")
    try:
        with games_mounted(cards[0], part, True, os.path.join(tmp, "out")) as mo:
            _lay_out(mo, conf, a.selector_dir, media, a.media_dir, doc)
            say("image 0 (%s) moved to /games/pad/img0" % cards[0].iid)
            for i, c in enumerate(cards[1:], 1):
                dst = os.path.join(mo, PAD, "img%d" % i)
                os.makedirs(dst)
                PROGRESS.step("copying image %d's games" % i, c.used)
                with games_mounted(c, c.path, False, os.path.join(tmp, "src%d" % i)) as ms:
                    say("image %d: copying %s's games tree (%s)" % (i, c.iid, _gb(c.used)))
                    _run(["cp", "-a", ms + "/.", dst + "/"])
                    with contextlib.suppress(OSError):
                        shutil.rmtree(os.path.join(dst, "lost+found"))
                    src_n, src_f = _tree_bytes(ms)
                dst_n, dst_f = _tree_bytes(dst)
                if (src_n, src_f) != (dst_n, dst_f):
                    raise Refused("image %d copied %d files / %d bytes of %d / %d" % (i, dst_f, dst_n, src_f, src_n))
                PROGRESS.add(c.used)
                say("image %d: %d files, %s, in /games/pad/img%d" % (i, dst_f, _gb(dst_n), i))
            _link_top(mo)
            say("/games/game -> %s: the menu runs first at every power-up" % TOP_LINKS["game"])
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(part)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if on_windows:
        say("copying the finished card to %s" % out)
        _copy_image_file(part, out + ".part", cards[0].size)
        os.unlink(part)
        part = out + ".part"
    os.replace(part, out)
    with open(out + ".pad-build.json", "w", encoding="utf-8") as f:
        json.dump({"build_id": build_id, "tool": TOOL, "multiboot": True,
                   "images": [os.path.basename(c.path) for c in cards]}, f, indent=1)
    PROGRESS.finish()
    say("built %s: %d images in %.0f s" % (out, len(cards), time.time() - t0))
    return 0


# ============================================================================== inject
def inject_card(a):
    """The menu alone, rewritten into an existing multi-boot card: s3select,
    padselect.sh, font.ttf, images.conf (from the flags, or the card's own
    titles when none are given) and media/. The games trees are not touched.
    Works on the card where it is (a Windows drive too, as Write's grow step
    does): only a few MB are written."""
    _need_root()
    check_selector_dir(a.selector_dir)
    card = Card(a.card, a.keyfile)
    tmp = tempfile.mkdtemp(prefix="pad_s3inject_", dir="/var/tmp")
    try:
        with games_mounted(card, card.path, True, os.path.join(tmp, "card")) as m:
            pad = os.path.join(m, PAD)
            conf_p = os.path.join(pad, "images.conf")
            if not os.path.isfile(conf_p):
                raise Refused("%s has no /games/pad/images.conf: not a Spike 3 multi-boot card" % a.card)
            with open(conf_p, encoding="utf-8") as f:
                old = parse_conf(f.read())
            dirs = [p for p, _t, _s in old["images"]]
            media = mkc.plan_media(a.media_dir, len(dirs)) if a.media_dir else None
            if a.titles is None:
                a.titles = ";".join(t for _p, t, _s in old["images"])
            if a.subtitles is None:
                a.subtitles = ";".join(s for _p, _t, s in old["images"])
            stand_ins = [type("C", (), {"label": lambda self: "", "path": d})() for d in dirs]
            conf = conf_from_args(a, stand_ins, media)
            for name, (mode, _req) in SELECTOR_FILES.items():
                src = os.path.join(a.selector_dir, name) if name != "font.ttf" else _font_src(a.selector_dir)
                shutil.copyfile(src, os.path.join(pad, name + ".new"))
                os.chmod(os.path.join(pad, name + ".new"), mode)
                os.replace(os.path.join(pad, name + ".new"), os.path.join(pad, name))
            with open(conf_p + ".new", "w", encoding="utf-8", newline="\n") as f:
                f.write(conf)
            os.replace(conf_p + ".new", conf_p)
            if media:
                md = os.path.join(pad, "media")
                shutil.rmtree(md, ignore_errors=True)
                os.makedirs(md)
                for fn in media["files"]:
                    shutil.copyfile(os.path.join(a.media_dir, fn), os.path.join(md, fn))
            _link_top(m)
            say("the menu rewritten on %s (%d images)" % (a.card, len(dirs)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rec = card.path + ".pad-build.json"
    doc = {}
    with contextlib.suppress(OSError, ValueError):
        with open(rec, encoding="utf-8") as f:
            doc = json.load(f)
    doc.update({"build_id": uuid.uuid4().hex, "tool": TOOL, "multiboot": True,
                "injected": datetime.datetime.now().isoformat(timespec="seconds")})
    with open(rec, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return 0


# ============================================================================== verify
def verify_card(a):
    _need_root()
    card = Card(a.card, a.keyfile)
    sources = []
    if a.primary:
        sources = [Card(p, a.keyfile) for p in [a.primary] + list(a.extra or [])]
    bad = []
    tmp = tempfile.mkdtemp(prefix="pad_s3verify_", dir="/var/tmp")
    try:
        with games_mounted(card, card.path, False, os.path.join(tmp, "card")) as m:
            pad = os.path.join(m, PAD)
            conf_p = os.path.join(pad, "images.conf")
            if not os.path.isfile(conf_p):
                raise Refused("%s has no /games/pad/images.conf: not a Spike 3 multi-boot card" % a.card)
            with open(conf_p, encoding="utf-8") as f:
                conf = parse_conf(f.read())
            dirs = [p for p, _t, _s in conf["images"]]
            print("images: %s" % " ".join(dirs))
            for name, target in TOP_LINKS.items():
                got = os.readlink(os.path.join(m, name)) if os.path.islink(os.path.join(m, name)) else None
                print("link /games/%s -> %s: %s" % (name, got, "OK" if got == target else "WRONG"))
                if got != target:
                    bad.append("link " + name)
            for name in SELECTOR_FILES:
                ok = os.path.isfile(os.path.join(pad, name))
                if a.selector_dir and name != "font.ttf" and ok:
                    ok = _sha(os.path.join(pad, name)) == _sha(os.path.join(a.selector_dir, name))
                print("menu %s: %s" % (name, "OK" if ok else "MISSING or DIFFERENT"))
                if not ok:
                    bad.append(name)
            for i, d in enumerate(dirs):
                tree = os.path.join(pad, d)
                g = os.path.join(tree, "game")
                game_ok = os.path.islink(g) and os.path.isfile(os.path.realpath(g)) and \
                    os.path.realpath(g).startswith(os.path.realpath(tree) + os.sep)
                n, files = _tree_bytes(tree) if os.path.isdir(tree) else (0, 0)
                line = "image %d %s: %d files, %s, game %s" % (i, d, files, _gb(n), "OK" if game_ok else "BROKEN")
                if not game_ok:
                    bad.append(d + " game")
                if i < len(sources):
                    with games_mounted(sources[i], sources[i].path, False, os.path.join(tmp, "s%d" % i)) as ms:
                        want = _tree_manifest(ms)
                    want.pop("lost+found", None)
                    got = _tree_manifest(tree)
                    same = want == got
                    line += ", against %s: %s" % (os.path.basename(sources[i].path),
                                                   "IDENTICAL" if same else "DIFFERS")
                    if not same:
                        diff = sorted(set(want.items()) ^ set(got.items()))[:5]
                        line += " %r" % diff
                        bad.append(d + " tree")
                print(line)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("verify: %s" % ("OK" if not bad else "FAILED (%s)" % ", ".join(bad)))
    return 0 if not bad else 1


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ============================================================================== media
def cmd_media(a):
    """The menu's pictures and sounds through selectmedia.py. A Spike 3 card's
    stills and clips are inside its encrypted games tree, so 'auto' is no
    picture; the menu is silent on the machine (stubs_s3.c), so no sounds."""
    import selectmedia
    images = [os.path.abspath(a.primary)] + [os.path.abspath(e) for e in a.extra]
    n = len(images)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    arts = selectmedia.parse_index_spec(a.art, n, "auto")
    anims = selectmedia.parse_index_spec(a.anim, n, "none")
    argv = ["prepare", "--primary", images[0]]
    for e in images[1:]:
        argv += ["--extra", e]
    argv += ["--out", out]
    for i, spec in enumerate(arts):
        if spec == "auto":
            say("art %d: 'auto' - a Spike 3 card's pictures are encrypted on it; no picture" % i)
            spec = "none"
        argv += ["--art", "%d=%s" % (i, spec)]
    for i, spec in enumerate(anims):
        if spec.startswith("auto"):
            say("anim %d: 'auto' - no attract clip the tools can take; none" % i)
            spec = "none"
        argv += ["--anim", "%d=%s" % (i, spec)]
    argv += ["--sound-move", "none", "--sound-confirm", "none"]
    volume = VOLUME_DEFAULT if a.volume is None else a.volume
    argv += ["--volume", str(volume)]
    if a.size:
        argv += ["--size", a.size]
    argv += ["--visual-only"]
    if a.work:
        argv += ["--work", a.work]
    return selectmedia.main(argv)


# ============================================================================== main
def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="a directory holding s3select, padselect.sh and font.ttf "
                   "(ensures3select.sh installs one)")
    s.add_argument("--media-dir", help="directory holding media.json (mks3multi.py media) and the files it names")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--heading", metavar="TEXT")
    s.add_argument("--footer", metavar="TEXT")
    s.add_argument("--footer-own", action="store_true")
    s.add_argument("--counter", choices=list(mkc.COUNTERS))
    s.add_argument("--countdown-word", metavar="TEXT")
    s.add_argument("--text-size", choices=list(mkc.TEXT_SIZES))
    s.add_argument("--default", type=int)
    s.add_argument("--volume", type=int)
    s.add_argument("--theme")
    s.add_argument("--color", action="append", metavar="ROLE=RRGGBB")
    s.add_argument("--conf")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mks3multi.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "build"):
        s = sub.add_parser(name)
        s.add_argument("--primary", required=True, help="image 0: a Spike 3 card image (.raw)")
        s.add_argument("--extra", action="append", default=[], metavar="RAW", help="another Spike 3 card image")
        s.add_argument("--keyfile", help="the padkeys.json holding your board's OTP key")
        s.add_argument("--cache-dir", help="(accepted for the tab; nothing is cached)")
        if name == "plan":
            s.add_argument("--media-dir")
        else:
            s.add_argument("--out", required=True, help="the card image to write (.raw)")
            _add_conf_flags(s)
            s.add_argument("--default-card", type=int)
            s.add_argument("--force", action="store_true")
            s.add_argument("--workdir", help="a Linux folder for the card while it is built when --out is on "
                           "a Windows drive (default /var/tmp/pad_s3multi)")
    s = sub.add_parser("inject")
    s.add_argument("--card", required=True)
    s.add_argument("--keyfile")
    s.add_argument("--default-card", type=int, help="(accepted for the tab; a Spike 3 card has no random cards)")
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--cache-dir")
    _add_conf_flags(s)
    s = sub.add_parser("verify")
    s.add_argument("--card", required=True)
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--keyfile")
    s.add_argument("--selector-dir")
    s.add_argument("--media-dir")
    s = sub.add_parser("conf")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--keyfile")
    _add_conf_flags(s)
    s = sub.add_parser("media")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--out", required=True)
    s.add_argument("--art", action="append", default=[])
    s.add_argument("--anim", action="append", default=[])
    s.add_argument("--music", action="append", default=[])
    s.add_argument("--sound-move", default="none")
    s.add_argument("--sound-confirm", action="append", default=[])
    s.add_argument("--cards", type=int, default=0)
    s.add_argument("--volume", type=int)
    s.add_argument("--size")
    s.add_argument("--visual-only", action="store_true")
    s.add_argument("--work")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            print_plan(make_plan(a))
            return 0
        if a.cmd == "build":
            return build_card(a)
        if a.cmd == "inject":
            return inject_card(a)
        if a.cmd == "verify":
            return verify_card(a)
        if a.cmd == "conf":
            sys.stdout.write(conf_from_args(a, _inputs(a), None))
            return 0
        if a.cmd == "media":
            return cmd_media(a)
    except Refused as e:
        print("[card] REFUSED: %s" % e, flush=True)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
