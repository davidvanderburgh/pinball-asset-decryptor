#!/usr/bin/env python3
"""mkbofmulti.py - a Barrels of Fun multi-boot update (PAD-342): several builds of one
title in ONE .fun, and a boot menu the machine shows on power-up - flippers choose,
START boots - drawn by the same menu program a Stern card and a JJP machine show.

    mkbofmulti.py plan    --primary A.fun --extra B.fun          what it costs, does it fit
    mkbofmulti.py build   --primary A.fun --extra B.fun --out M.fun --selector-dir DIR ...
    mkbofmulti.py verify  --fun M.fun [--quick]                  read it back, rebuild every image
    mkbofmulti.py inspect --fun M.fun [--json] [--media-out DIR] the menu it carries
    mkbofmulti.py media   --primary A.fun --extra B.fun --out DIR ...   the menu's pictures

HOW A BOF MACHINE TAKES AN UPDATE (Labyrinth; read out of its own .fun, 2026-10-03).  The
.fun is a GPG-symmetric gzip tarball.  The machine's ~/updatecode.sh empties
/home/pinball/extracted, decrypts the .fun into it, untars it into extracted/decrypt,
requires exactly ONE *.x86_64 there, renames it GDCraze.x86_64, copies it to
~/craze/GDCraze.x86_64 (what ~/.bash_profile's ./startgame runs) and records its size in
~/craze/GAMEFILESIZE - and then runs the update's own update/update.sh, which copies
update/.bash_profile over ~/.bash_profile and update/updatecode.sh over the updater itself.
So an update changes how the machine STARTS, not just the game, and that is the whole door:

  * image 0 (--primary) is the .fun as it is: its one program, installed by BOF's updater
    exactly as a normal update installs it;
  * every other image travels as a DELTA against image 0 (pad_imageN.delta), because a
    .fun is one file on a FAT32 stick, which cannot hold 4 GiB, and two 4.3 GB programs
    do not fit.  A mod is its title's program with some packed files changed - the Sarah
    build of Labyrinth shares the engine and 8,411 of its 8,512 packed files with stock
    and differs in 311 MB - so the delta is made from the two programs' own Godot pack
    directories (copy the files they share, carry the ones they do not) and checked here,
    byte for byte, before anything is written;
  * padselect/ carries the menu (bofselect), the rebuilder (paddelta), the boot hook
    (padselect.sh), the install step (pad_install.sh), images.conf, the md5 of every
    image (programs) and the menu's pictures;
  * update/update.sh runs pad_install.sh first (it rebuilds the extra images from their
    deltas, checks every md5, and takes an image that does not check out out of the
    menu), and update/.bash_profile carries ONE hook line before its loop starts the game.

All of it lives under extracted/, which BOF's updater empties at the start of EVERY update:
a later normal update takes the whole multi-boot install away with it, and that update's
own update.sh puts its own .bash_profile back.  That is the way back to a stock machine.

THE PROFILE IS PATCHED IN TWO PLACES, both anchored on the vendor's exact text, and a
profile without them is refused rather than guessed at: the hook block before `while true`,
and an `rm -f` in front of the profile's own self-repair copy (`cp -rf .../decrypt/
GDCraze.x86_64 .../craze/GDCraze.x86_64`), because the program the game runs is a HARD LINK
to the chosen image after a switch, and a copy onto a hard link would write through it into
the other image.

What is supported: Labyrinth (its updater is the one read).  Dune's updater is a Python
script with its own md5 rule and Winchester's update carries no scripts at all; Bon Jovi's
is a signed disk image.  They are refused by name until each is read the same way.

Runs on Linux (WSL): gpg, tar, gzip (pigz when there is one).
"""
import argparse
import collections
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
for _p in (SPIKE2_EMU, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import mkmulticard as mkc                                           # noqa: E402  the shared pure parts
from mkmulticard import Refused, say, PROGRESS, check_output_path   # noqa: E402

TOOL = "mkbofmulti"
#: build.json's shape; a reader must accept an older (or missing) one.
VERSION = "1.0"

# ---- the machine ---------------------------------------------------------------------------------
HOME = "/home/pinball"
DECRYPT = HOME + "/extracted/decrypt"
PADSELECT = "padselect"                        # the folder in the .fun = DECRYPT/padselect on the machine
PADSELECT_DIR = DECRYPT + "/" + PADSELECT
MEDIA_DIR = PADSELECT_DIR + "/media"
IMAGE0_FILE = "GDCraze.x86_64"                 # what Labyrinth's updater renames the one *.x86_64 to
EXTRA_FILE = "pad_image%d.bin"                 # NOT .x86_64: the updater wants exactly one of those
DELTA_FILE = "pad_image%d.delta"
PROGRAMS = "programs"
INSTALL_LINE = "/bin/bash %s/pad_install.sh" % PADSELECT_DIR
HOOK_BLOCK = [
    "# PAD multi-boot (PAD-342): the boot menu picks which program is the game before the",
    "# loop below starts it.  Any failure leaves image 0; a later normal update takes all of",
    "# it away (it lives under extracted/) and puts its own profile back.",
    'if [ "$SESSION_TYPE" == "console" ] && [ -f %s/padselect.sh ]; then' % PADSELECT_DIR,
    "  /bin/bash %s/padselect.sh < /dev/null" % PADSELECT_DIR,
    "fi",
]
HOOK_MARK = "PAD multi-boot (PAD-342)"
WHILE_RE = re.compile(r"^while true\s*$")
HEAL_RE = re.compile(r"^(\s*)(cp -rf /home/pinball/extracted/decrypt/GDCraze\.x86_64 "
                     r"/home/pinball/craze/GDCraze\.x86_64\s*)$")
HEAL_RM = "rm -f /home/pinball/craze/GDCraze.x86_64; "

#: the titles whose update has been read, and what their menu needs to know
TITLES = collections.OrderedDict([
    ("labyrinth", {
        "display": "Jim Henson's Labyrinth",
        "passphrase": "funkey",
        "fun_name": "lab.fun",
        "program_re": re.compile(r"^GDCraze.*\.x86_64$"),
        # the switch table's own numbers (tools/bof_emu/profiles/labyrinth.json): LOWER
        # LEFT FLIPPER 15, LOWER RIGHT FLIPPER 22, START 14 - and LAUNCH 20 as a second START
        "switches": collections.OrderedDict([("switch_left", "15"), ("switch_right", "22"),
                                             ("switch_start", "14,20")]),
        # A BUILD'S OWN PICTURES ('auto', PAD-342): the attract clips in its pack, in the
        # order 'auto' tries them, each with the moment its still is taken.  Image 0 takes
        # the first, the game's title; every other build the first one it CHANGED - the
        # Sarah build's intro is film footage under the film's own title - else the first.
        "attract_clips": [("assets/videos/attract_main_title_no_sound.ogv", 4.0),
                          ("assets/videos/attract/bof_logo_v9_PR422_48khz.ogv", 0.6),
                          ("assets/videos/peach/attract_ballroom.ogv", 1.5),
                          ("assets/videos/attract_background_view_of_castle.ogv", 2.0),
                          ("assets/videos/attract_background_garden_view_of_castle.ogv", 2.0),
                          ("assets/videos/attract_background_front_walls.ogv", 2.0)],
        # ...and its own SOUND ('auto', PAD-342), the game's imported samples (source paths:
        # each one's .import names the .sample it became).  A build's music bed is picked the
        # way its clip is: image 0 the first, the gold title's "Into the Labyrinth" loop (the
        # title clip itself is silent); any other build the first it changed - the Sarah
        # build's intro soundtrack, the sound of the very clip its card plays.  The flipper's
        # click is the game's own service-menu sound and START the clock's bell, off image 0.
        "music": [("assets/sounds/music/Into_the_Labyrinth-Anxious_ssd_loopable_dpp_remaster_01.wav", None),
                  ("assets/sounds/sfx/logo_video_v9_audio.wav", None)],
        "sound_move": "assets/sounds/sfx/service_menu/menu_down.wav",
        "sound_confirm": "assets/sounds/sfx/clock_bell.wav",
    }),
])
#: titles a BOF .fun can be, and why they are not offered yet
NOT_YET = {
    "dune": "Dune's updater is a Python script with an md5 rule of its own; it has not been read for a menu yet",
    "winchester": "Winchester's update carries no startup scripts to put a menu into",
    "bonjovi": "Bon Jovi's update is a signed disk image, which cannot be rebuilt",
}
OTHER_PASSPHRASES = collections.OrderedDict([("dune", "dunekey"), ("winchester", "winchesterkey")])

MAX_IMAGES = 4
FAT32_MAX = 4 * 1024 ** 3 - 1                  # the biggest file a FAT32 stick holds
FAT32_MARGIN = 64 << 20                        # the estimate's slack before the plan says no
USB_SIZES = collections.OrderedDict([("8G", 7_700_000_000), ("16G", 15_400_000_000),
                                     ("32G", 30_900_000_000), ("64G", 61_800_000_000)])
CACHE_DIR_DEFAULT = "/var/tmp/pad_bofmulti_cache"
CACHE_KEEP = 4
MEDIA_SUFFIX = ".media"                        # CACHE/<unpack>.media/: that build's own clips + stills
CHUNK = 8 << 20
SELECTOR_FILES = collections.OrderedDict([      # name in --selector-dir -> (mode, required)
    ("bofselect", (0o755, True)),
    ("paddelta", (0o755, True)),
    ("padselect.sh", (0o755, True)),
    ("pad_install.sh", (0o755, True)),
    ("font.ttf", (0o644, False)),
])
VOLUME_DEFAULT = 50
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ============================================================================== small helpers
def _gb(n):
    return "%.2f GB" % (n / 1e9) if n is not None else "?"


def need_tools(*names):
    missing = [n for n in names if not shutil.which(n)]
    if missing:
        raise Refused("this needs %s on the Linux side (apt install %s)" % (
            ", ".join(missing), " ".join("gnupg" if m == "gpg" else m for m in missing)))


def md5_file(path, meter=None):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            if meter:
                meter(len(b))
    return h.hexdigest()


def split_list(s):
    return [x.strip() for x in s.split(";")] if s else []


# ============================================================================== the .fun
def title_of_name(path):
    """The title a .fun's NAME says, or None (a renamed file is identified by decrypting)."""
    b = os.path.basename(path).lower()
    for key, t in TITLES.items():
        if b == t["fun_name"]:
            return key
    names = {"dune.fun": "dune", "winchester.fun": "winchester"}
    if b in names:
        return names[b]
    if b.startswith("bon-jovi") or b.startswith("bonjovi"):
        return "bonjovi"
    return None


def _gpg_argv(passphrase, src):
    return ["gpg", "--batch", "--quiet", "--yes", "--pinentry-mode", "loopback",
            "--passphrase", passphrase, "--decrypt", src]


def identify(fun):
    """-> (title key, passphrase).  By name first, then by trying each title's passphrase
    on the first bytes (a wrong passphrase fails at once)."""
    key = title_of_name(fun)
    if key in NOT_YET:
        raise Refused("%s: %s" % (os.path.basename(fun), NOT_YET[key]))
    if key:
        return key, TITLES[key]["passphrase"]
    cands = [(k, t["passphrase"]) for k, t in TITLES.items()] + list(OTHER_PASSPHRASES.items())
    for k, pw in cands:
        p = subprocess.Popen(_gpg_argv(pw, fun), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        head = p.stdout.read(4)
        p.kill()
        p.wait()
        if head[:2] == b"\x1f\x8b":
            if k in NOT_YET:
                raise Refused("%s is a %s update: %s" % (os.path.basename(fun), k, NOT_YET[k]))
            return k, pw
    raise Refused("%s is not a Barrels of Fun update this can read (none of the titles' "
                  "passphrases opens it)" % fun)


def unpack(fun, passphrase, dest, meter=None):
    """gpg -d FUN | tar -xz -C DEST, counting the .fun's bytes as they are read."""
    os.makedirs(dest, exist_ok=True)
    g = subprocess.Popen(_gpg_argv(passphrase, fun), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t = subprocess.Popen(["tar", "-xz", "--no-same-owner", "-C", dest], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while True:
            b = g.stdout.read(CHUNK)
            if not b:
                break
            t.stdin.write(b)
            if meter:
                meter(len(b))
        t.stdin.close()
    except BrokenPipeError:
        pass
    gerr = g.stderr.read().decode(errors="replace")
    terr = t.stderr.read().decode(errors="replace")
    grc, trc = g.wait(), t.wait()
    if grc != 0:
        raise Refused("gpg could not decrypt %s: %s" % (fun, gerr.strip() or "exit %d" % grc))
    if trc != 0:
        raise Refused("tar could not unpack %s: %s" % (fun, terr.strip()[-400:] or "exit %d" % trc))


class Unpacked:
    """One .fun, decrypted and unpacked into the cache: its program, its update scripts."""

    def __init__(self, fun, title, root):
        self.fun = fun
        self.title = title
        self.root = root
        progs = [n for n in os.listdir(root) if n.endswith(".x86_64") and not n.startswith(".")]
        if len(progs) != 1:
            raise Refused("%s carries %d *.x86_64 programs; BOF's updater installs exactly one"
                          % (os.path.basename(fun), len(progs)))
        self.program_name = progs[0]
        if not TITLES[title]["program_re"].match(self.program_name):
            raise Refused("%s carries %s, not the %s program its updater installs"
                          % (os.path.basename(fun), self.program_name, TITLES[title]["display"]))
        self.program = os.path.join(root, self.program_name)
        self.size = os.path.getsize(self.program)
        m = re.search(r"(\d{4})(\d{2})(\d{2})", self.program_name)
        self.version = "%s.%s.%s" % m.groups() if m else None
        self.update = os.path.join(root, "update")

    def members(self):
        """What goes into the multi-boot .fun from this one: every top-level name but the
        macOS AppleDouble ('._*') clutter a Mac-made tarball carries."""
        return sorted(n for n in os.listdir(self.root) if not n.startswith("._") and n != ".complete")


def cached_unpack(fun, cache_dir, meter=None):
    """The .fun unpacked once into CACHE/<name>-<size>-<mtime>/ (a .complete marker says it
    finished); the oldest of more than CACHE_KEEP are removed."""
    fun = os.path.abspath(fun)
    title, pw = identify(fun)
    st = os.stat(fun)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(os.path.dirname(fun)) + "_" + os.path.basename(fun))
    d = os.path.join(cache_dir, "%s-%d-%d" % (slug, st.st_size, int(st.st_mtime)))
    if not os.path.isfile(os.path.join(d, ".complete")):
        if os.path.isdir(d):
            shutil.rmtree(d)
        say("unpacking %s (%s)" % (fun, _gb(st.st_size)))
        unpack(fun, pw, d + ".part", meter)
        os.rename(d + ".part", d)
        with open(os.path.join(d, ".complete"), "w") as f:
            f.write(fun + "\n")
        prune_cache(cache_dir, keep=d)
    else:
        say("cached: %s" % d)
        if meter:
            meter(st.st_size)
    os.utime(os.path.join(d, ".complete"))
    return Unpacked(fun, title, d)


def prune_cache(cache_dir, keep):
    try:
        ds = [os.path.join(cache_dir, n) for n in os.listdir(cache_dir)]
    except OSError:
        return
    done = [d for d in ds if os.path.isfile(os.path.join(d, ".complete"))]
    done.sort(key=lambda d: os.path.getmtime(os.path.join(d, ".complete")), reverse=True)
    for d in done[CACHE_KEEP:]:
        if d != keep:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(d + MEDIA_SUFFIX, ignore_errors=True)     # its own pictures (own_media)
    for d in ds:
        if d.endswith(".part"):
            shutil.rmtree(d, ignore_errors=True)


# ============================================================================== the delta
DELTA_MAGIC = b"PADDLT01"


_PCK_SAID = []


def _pck_entries(path):
    """[(abs offset, size, md5)] of a Godot pack's files, or None (no readable directory)."""
    try:
        from pinball_decryptor.plugins.bof import pck_directory
    except ImportError as e:
        if not _PCK_SAID:
            _PCK_SAID.append(1)
            say("note: the Godot pack reader is not here (%s): the builds are compared byte "
                "by byte at the same offsets, which makes a much bigger update" % e)
        return None
    try:
        d = pck_directory.read(path)
    except Exception:
        return None
    if d is None:
        return None
    out = []
    for e in d.entries:
        out.append((d.pck_off + d.base + e["ofs"], e["size"], bytes(e["md5"])))
    out.sort()
    return out


def delta_ops(a_path, b_path):
    """The ops that rebuild B from A -> list of ('C', a_off, len) / ('D', b_off, len).

    Where both are Godot packs, every file B shares with A (same md5, same size) is a copy
    of A's bytes wherever they sit; everything else in B (the engine before the pack, the
    pack's header and directory, a changed file, the trailer) is compared against A at the
    SAME offset in 1 MiB steps - equal = copy, else B's own bytes.  Without pack
    directories it is that same-offset comparison all the way."""
    a_size, b_size = os.path.getsize(a_path), os.path.getsize(b_path)
    a_ents = _pck_entries(a_path)
    b_ents = _pck_entries(b_path) if a_ents is not None else None
    by_md5 = {}
    for off, size, md5 in a_ents or []:
        by_md5.setdefault((md5, size), off)
    ops = []

    def add(op, off, n):
        if n <= 0:
            return
        if ops and ops[-1][0] == op and ops[-1][1] + ops[-1][2] == off:
            ops[-1] = (op, ops[-1][1], ops[-1][2] + n)
        else:
            ops.append((op, off, n))

    step = 1 << 20

    def same_offset(fa, fb, start, end):
        pos = start
        while pos < end:
            n = min(step, end - pos)
            fb.seek(pos)
            bb = fb.read(n)
            if pos + n <= a_size:
                fa.seek(pos)
                if fa.read(n) == bb:
                    add("C", pos, n)
                    pos += n
                    continue
            add("D", pos, n)
            pos += n

    with open(a_path, "rb") as fa, open(b_path, "rb") as fb:
        pos = 0
        for off, size, md5 in b_ents or []:
            if off < pos or off + size > b_size:
                continue                      # overlapping / out of range: the comparison covers it
            src = by_md5.get((md5, size))
            if src is None:
                continue
            same_offset(fa, fb, pos, off)
            add("C", src, size)
            pos = off + size
        same_offset(fa, fb, pos, b_size)
    return ops


def delta_data_bytes(ops):
    return sum(n for op, _o, n in ops if op == "D")


def write_delta(ops, a_path, b_path, out_path, meter=None):
    """The PADDLT01 file paddelta.c reads."""
    a_size, b_size = os.path.getsize(a_path), os.path.getsize(b_path)
    with open(b_path, "rb") as fb, open(out_path + ".part", "wb") as out:
        out.write(DELTA_MAGIC + struct.pack("<QQ", a_size, b_size))
        for op, off, n in ops:
            if op == "C":
                out.write(b"C" + struct.pack("<QQ", off, n))
            else:
                out.write(b"D" + struct.pack("<Q", n))
                fb.seek(off)
                left = n
                while left:
                    b = fb.read(min(CHUNK, left))
                    if not b:
                        raise Refused("%s ended early while writing the delta" % b_path)
                    out.write(b)
                    left -= len(b)
                    if meter:
                        meter(len(b))
        out.write(b"E")
    os.replace(out_path + ".part", out_path)


def apply_delta_md5(a_path, delta_path, meter=None):
    """What paddelta would write, as an md5 and a size - read, never written."""
    h = hashlib.md5()
    total = 0
    with open(a_path, "rb") as fa, open(delta_path, "rb") as fd:
        if fd.read(8) != DELTA_MAGIC:
            raise Refused("%s is not a PAD delta" % delta_path)
        src_size, dst_size = struct.unpack("<QQ", fd.read(16))
        if src_size != os.path.getsize(a_path):
            raise Refused("%s was not made against %s (size)" % (delta_path, a_path))
        while True:
            op = fd.read(1)
            if op == b"E":
                break
            if op == b"C":
                off, n = struct.unpack("<QQ", fd.read(16))
                fa.seek(off)
                left = n
                while left:
                    b = fa.read(min(CHUNK, left))
                    if not b:
                        raise Refused("%s: a copy runs past the end of the source" % delta_path)
                    h.update(b)
                    left -= len(b)
                    total += len(b)
                    if meter:
                        meter(len(b))
            elif op == b"D":
                (n,) = struct.unpack("<Q", fd.read(8))
                left = n
                while left:
                    b = fd.read(min(CHUNK, left))
                    if not b:
                        raise Refused("%s: a data block is cut short" % delta_path)
                    h.update(b)
                    left -= len(b)
                    total += len(b)
                    if meter:
                        meter(len(b))
            else:
                raise Refused("%s: an unknown op %r" % (delta_path, op))
    if total != dst_size:
        raise Refused("%s rebuilds %d bytes, not the %d it promises" % (delta_path, total, dst_size))
    return h.hexdigest(), total


# ============================================================================== the scripts
def patch_profile(text):
    """The vendor's update/.bash_profile with the hook block before `while true` and the
    rm -f in front of its self-repair copy.  Refused when either anchor is not exactly there."""
    if HOOK_MARK in text:
        raise Refused("update/.bash_profile already carries a PAD multi-boot hook: build from the "
                      "stock .fun, not from a multi-boot one")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    whiles = [i for i, ln in enumerate(lines) if WHILE_RE.match(ln)]
    heals = [i for i, ln in enumerate(lines) if HEAL_RE.match(ln)]
    if len(whiles) != 1:
        raise Refused("update/.bash_profile: expected one line 'while true' (the loop that starts "
                      "the game), found %d - this is not the profile this tool was written against"
                      % len(whiles))
    if len(heals) != 1:
        raise Refused("update/.bash_profile: expected one self-repair line 'cp -rf /home/pinball/"
                      "extracted/decrypt/GDCraze.x86_64 /home/pinball/craze/GDCraze.x86_64', found %d"
                      % len(heals))
    m = HEAL_RE.match(lines[heals[0]])
    lines[heals[0]] = m.group(1) + HEAL_RM + m.group(2)
    i = whiles[0]
    lines[i:i] = HOOK_BLOCK + [""]
    return nl.join(lines)


def patch_update_sh(text):
    """The vendor's update/update.sh with the install step as its first command."""
    if INSTALL_LINE in text:
        raise Refused("update/update.sh already runs the PAD install step: build from the stock .fun")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    at = 1 if lines and lines[0].startswith("#!") else 0
    lines[at:at] = ["", "# PAD multi-boot (PAD-342): rebuild and check the extra images first; it always",
                    "# exits 0, so nothing below is ever skipped", INSTALL_LINE]
    if not any(re.search(r"\.bash_profile\s+/home/pinball/\.bash_profile", ln) for ln in lines):
        raise Refused("update/update.sh does not copy update/.bash_profile over ~/.bash_profile - "
                      "the menu's hook would never reach the machine")
    return nl.join(lines)


def check_update_dir(u):
    for n in (".bash_profile", "update.sh"):
        if not os.path.isfile(os.path.join(u.update, n)):
            raise Refused("%s has no update/%s: an update without its startup scripts cannot carry "
                          "a menu" % (os.path.basename(u.fun), n))


# ============================================================================== the conf
def render_conf(programs, titles, subtitles, default, timeout, rows, sound_move, sound_confirm, volume,
                switches, theme=None, colors=None, heading=None, text_size=None, counter=None,
                countdown_word=None, footer=None, font=True, learn=False, groups=None, default_card=None):
    """images.conf text.  ``groups`` are RANDOM cards (mkmulticard's check_groups shape: title,
    subtitle, media, members, keep, pos, roll), written as the Stern card writes them: a
    ``group=`` line before the image it sits in front of.  The menu and the hook need nothing
    more - the menu rolls a member and writes ITS image index to the choice file."""
    n = len(programs)
    titles = list(titles or [])
    subtitles = list(subtitles or [])
    rows = [tuple(r) + ("",) * (len(mkc.MEDIA_ROW) - len(r)) for r in (rows or [])]
    if len(titles) > n or len(subtitles) > n or len(rows) > n:
        raise Refused("images.conf: %d titles / %d subtitles / %d media rows for %d images"
                      % (len(titles), len(subtitles), len(rows), n))
    titles += ["image %d" % i for i in range(len(titles), n)]
    subtitles += [""] * (n - len(subtitles))
    rows += [mkc.MEDIA_ROW] * (n - len(rows))
    for s in titles + subtitles:
        if "|" in s or "\n" in s or "\r" in s:
            raise Refused("images.conf: title/subtitle %r may not contain '|' or a newline" % s)
    rows = [tuple(mkc._media_name_ok(x or "", w) for x, w in zip(r, mkc.MEDIA_FIELDS)) for r in rows]
    if not 0 <= int(default) < n:
        raise Refused("images.conf: default=%s is not an image index (0..%d)" % (default, n - 1))
    if int(timeout) < 0:
        raise Refused("images.conf: timeout must be >= 0")
    theme = mkc.check_theme(theme)
    colors = mkc.check_colors(colors or {})
    text_size = mkc.check_text_size(text_size)
    counter = mkc.check_counter(counter)
    groups = mkc.check_groups(groups, n)
    if default_card is not None:
        ncards = n - sum(len(g["members"]) for g in groups if not g["keep"]) + len(groups)
        if not 0 <= int(default_card) < ncards:
            raise Refused("images.conf: default_card=%s is not a card index (0..%d)" % (default_card, ncards - 1))
    any_media = any(any(r) for r in rows) or any(any(g["media"]) for g in groups)
    width = 4 if (any(r[3] for r in rows) or any(g["media"][3] for g in groups)) else (3 if any_media else 0)
    out = ["# images.conf - the Barrels of Fun boot menu (bofselect + padselect.sh); written by mkbofmulti.py",
           "# image=<program>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
           "# <program> = the file in %s that becomes craze/GDCraze.x86_64 when it is chosen;" % DECRYPT,
           "# default = highlight when there is no last choice; timeout = seconds before it boots by itself;",
           "# switch_* = the FAST switch numbers of the buttons the menu reads (a second after a comma)"]
    if groups:
        out.append("# group=[+][not-last|any|shuffle:]<first>-<last>|<title>|<subtitle>[|media]   a RANDOM card:")
        out.append("# it boots one of those images at every power-up ('+' = they keep cards of their own too)")

    def group_line(g):
        roll = "" if g["roll"] == mkc.ROLL_DEFAULT else g["roll"] + ":"
        return ("group=%s%s%d-%d|%s|%s" % ("+" if g["keep"] else "", roll, g["members"][0],
                                            g["members"][-1], g["title"], g["subtitle"])
                + "".join("|" + x for x in g["media"][:width]))

    at = {}
    for g in groups:
        at.setdefault(g["pos"], []).append(g)
    for i, (p, t, s, r) in enumerate(zip(programs, titles, subtitles, rows)):
        out.extend(group_line(g) for g in at.get(i, ()))     # a card sits where its line sits
        out.append("image=%s|%s|%s" % (p, t, s) + "".join("|" + x for x in r[:width]))
    out.extend(group_line(g) for g in at.get(n, ()))
    out.append("default=%d" % int(default))
    if default_card is not None:
        out.append("default_card=%d" % int(default_card))
    out.append("timeout=%d" % int(timeout))
    if heading is not None:
        out.append("heading=%s" % mkc.conf_heading(heading))
    if text_size is not None:
        out.append("text_size=%s" % text_size)
    if counter is not None:
        out.append("counter=%s" % counter)
    if countdown_word is not None:
        out.append("countdown_word=%s" % mkc.conf_countdown_word(countdown_word))
    if footer is not None:
        out.append("footer=%s" % mkc.conf_footer(footer))
    if font:
        out.append("font=%s/font.ttf" % PADSELECT_DIR)
    if sound_move:
        out.append("sound_move=%s" % mkc._media_name_ok(sound_move, "sound_move"))
    if sound_confirm:
        out.append("sound_confirm=%s" % mkc._media_name_ok(sound_confirm, "sound_confirm"))
    out.append("volume=%d" % (VOLUME_DEFAULT if volume is None else mkc._int_range(volume, "volume", 0, 100)))
    if any_media or sound_move or sound_confirm:
        out.append("media=%s" % MEDIA_DIR)
    if theme:
        out.append("theme=%s" % theme)
    for role in mkc.boot_themes()["roles"]:
        if role in colors:
            out.append("color_%s=%s" % (role, colors[role]))
    for k, v in switches.items():
        out.append("%s=%s" % (k, v))
    if learn:
        out.append("learn=1")
    for line in out:
        if len(line) > mkc.CONF_LINE_MAX:
            raise Refused("images.conf: a line is %d characters; the selector reads at most %d"
                          % (len(line), mkc.CONF_LINE_MAX))
    return "\n".join(out) + "\n"


def parse_conf(text):
    """images.conf -> {'images': [(program, title, subtitle)], 'media': [rows], 'groups': [random
    cards, render_conf's shape], 'default', 'default_card', ...}."""
    out = {"images": [], "media": [], "groups": [], "default": None, "default_card": None, "timeout": None,
           "heading": None, "text_size": None, "counter": None, "countdown_word": None, "footer": None,
           "font": None, "sound_move": None, "sound_confirm": None, "volume": None, "theme": None,
           "colors": {}, "switches": {}, "media_dir": None}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key == "image":
            f = val.split("|")
            f += [""] * (7 - len(f))
            out["images"].append((f[0], f[1], f[2]))
            out["media"].append(tuple(f[3:7]))
        elif key == "group":
            f = val.split("|")
            f += [""] * (7 - len(f))
            spec = f[0]
            keep = spec.startswith("+")
            roll, spec = mkc.split_roll_spec(spec[1:] if keep else spec)
            out["groups"].append({"members": mkc.parse_member_spec(spec), "keep": keep, "roll": roll,
                                  "pos": len(out["images"]), "title": f[1], "subtitle": f[2],
                                  "media": tuple(f[3:7])})
        elif key == "media":
            # the DIRECTORY line - not 'media', which is the per-image rows above (a
            # 'key in out' here once replaced those rows with this path)
            out["media_dir"] = val
        elif key in ("default", "default_card", "timeout", "volume"):
            try:
                out[key] = int(val)
            except ValueError:
                pass
        elif key.startswith("color_"):
            out["colors"][key[6:]] = val
        elif key.startswith("switch_"):
            out["switches"][key] = val
        elif key in out:
            out[key] = val
    return out


def conf_from_args(a, programs, media, default_titles):
    if getattr(a, "conf", None):
        with open(a.conf, encoding="utf-8") as f:
            text = f.read()
        if [p for p, _t, _s in parse_conf(text)["images"]] != list(programs):
            raise Refused("--conf %s does not list %r" % (a.conf, list(programs)))
        return text
    titles = split_list(a.titles) or list(default_titles)
    subtitles = split_list(a.subtitles)
    rows, move, confirm, volume = ([], None, None, None)
    if media:
        rows, move, confirm, volume = media["rows"], media["sound_move"], media["sound_confirm"], media["volume"]
    if a.volume is not None:
        volume = a.volume
    # A RANDOM CARD'S OWN PICTURE AND SOUNDS are media.json's 'groups' rows, by group index;
    # a card that already names its own (an inject carrying the update's conf) keeps them
    groups = [dict(g) for g in (getattr(a, "groups", None) or [])]
    group_rows = (media or {}).get("group_rows") or []
    for gi, g in enumerate(groups):
        if gi < len(group_rows) and not any(g.get("media") or ()):
            g["media"] = group_rows[gi]
    footer = None if a.footer_own else a.footer
    return render_conf(programs, titles, subtitles, a.default or 0, 15 if a.timeout is None else a.timeout,
                       rows, move, confirm, volume, TITLES[a._title]["switches"], theme=a.theme,
                       colors=mkc.parse_color_flags(a.color), heading=a.heading, text_size=a.text_size,
                       counter=a.counter, countdown_word=a.countdown_word, footer=footer,
                       learn=bool(getattr(a, "learn", False)), groups=groups,
                       default_card=getattr(a, "default_card", None))


# ============================================================================== plan
def _inputs(a):
    primary = os.path.abspath(a.primary)
    extras = [os.path.abspath(e) for e in a.extra]
    if not extras:
        raise Refused("a multi-boot update needs at least two images: --primary and one --extra")
    if 1 + len(extras) > MAX_IMAGES:
        raise Refused("at most %d images fit one Barrels of Fun multi-boot update" % MAX_IMAGES)
    for p in [primary] + extras:
        if not os.path.isfile(p):
            raise Refused("%s does not exist" % p)
    mkc.check_groups(getattr(a, "groups", None), 1 + len(extras))    # before any unpacking
    return primary, extras


def unpack_all(primary, extras, cache_dir):
    funs = [primary] + extras
    need = sum(os.path.getsize(f) for f in funs)
    PROGRESS.start(need, "unpack")
    us = []
    for f in funs:
        PROGRESS.step("unpack %s" % os.path.basename(f), os.path.getsize(f))
        u = cached_unpack(f, cache_dir, PROGRESS.add)
        us.append(u)
    PROGRESS.finish()
    t0 = us[0].title
    for u in us[1:]:
        if u.title != t0:
            raise Refused("%s is %s and %s is %s: one multi-boot update holds builds of ONE title"
                          % (os.path.basename(us[0].fun), TITLES[t0]["display"], os.path.basename(u.fun),
                             TITLES[u.title]["display"]))
    return us


def make_plan(a):
    need_tools("gpg", "tar")
    primary, extras = _inputs(a)
    cache = a.cache_dir or CACHE_DIR_DEFAULT
    us = unpack_all(primary, extras, cache)
    check_update_dir(us[0])
    deltas = []
    for u in us[1:]:
        say("comparing %s with %s" % (u.program_name, us[0].program_name))
        ops = delta_ops(us[0].program, u.program)
        deltas.append(delta_data_bytes(ops))
    media = mkc.plan_media(a.media_dir, len(us)) if a.media_dir else None
    menu = 4_000_000 + (media["total"] if media else 0)
    total = os.path.getsize(primary) + sum(deltas) + menu
    return {"units": us, "deltas": deltas, "media": media, "menu": menu, "total": total}


def print_plan(plan):
    us = plan["units"]
    print("== layout: image 0 = the primary .fun as it is (BOF's updater installs its program); "
          "every other image = a delta against it, rebuilt and checked by the install step")
    print("== game code versions")
    for i, u in enumerate(us):
        print("  %d  %s  %s  %s" % (i, IMAGE0_FILE if i == 0 else EXTRA_FILE % i, os.path.basename(u.fun),
                                    u.version or "UNKNOWN"))
    print("== bytes in the update")
    print("image-size 0 %s %d the primary .fun as it is" % (IMAGE0_FILE, os.path.getsize(us[0].fun)))
    for i, d in enumerate(plan["deltas"], 1):
        print("image-size %d %s %d delta: %s of its %s differ from image 0"
              % (i, EXTRA_FILE % i, d, _gb(d), _gb(us[i].size)))
    print("image-size overhead %d the menu, its pictures and the scripts" % plan["menu"])
    print("fun-size %d estimated multi-boot .fun" % plan["total"])
    ok32 = plan["total"] + FAT32_MARGIN <= FAT32_MAX
    print("fat32: %s (one file on a FAT32 stick holds at most %s)"
          % ("fits" if ok32 else "TOO BIG", _gb(FAT32_MAX)))
    best = None
    for k, cap in USB_SIZES.items():
        ok = ok32 and plan["total"] <= cap
        print("fits USB %s stick size %d: %s (spare %d)" % (k, cap, "YES" if ok else "NO", cap - plan["total"]))
        if ok and best is None:
            best = k
    print("stick: %s" % (best or ("none: the update is bigger than a FAT32 stick holds in one file"
                                  if not ok32 else "none of %s is big enough" % ", ".join(USB_SIZES))))


# ============================================================================== build
def check_selector_dir(d):
    if not d or not os.path.isdir(d):
        raise Refused("--selector-dir %s is not a directory (ensurebofselect.sh installs one)" % d)
    for name, (_mode, required) in SELECTOR_FILES.items():
        if required and not os.path.isfile(os.path.join(d, name)):
            raise Refused("--selector-dir %s has no %s (ensurebofselect.sh installs it)" % (d, name))


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_fun(a):
    need_tools("gpg", "tar")
    primary, extras = _inputs(a)
    out = os.path.abspath(check_output_path(a.out, [primary] + extras, force=a.force))
    if not out.lower().endswith(".fun"):
        raise Refused("--out %s: a BOF update ends .fun (and the machine looks for lab.fun on the stick)" % out)
    check_selector_dir(a.selector_dir)
    cache = a.cache_dir or CACHE_DIR_DEFAULT
    us = unpack_all(primary, extras, cache)
    u0 = us[0]
    check_update_dir(u0)
    a._title = u0.title
    media = mkc.plan_media(a.media_dir, len(us)) if a.media_dir else None
    work = os.path.abspath(a.workdir) if a.workdir else os.path.join(cache, "build-" + str(os.getpid()))
    if os.path.isdir(work):
        shutil.rmtree(work)
    stage = os.path.join(work, "stage")
    os.makedirs(stage)
    try:
        # the work: two md5s per extra and image 0's, the deltas, the archive
        budget = u0.size + sum(u.size * 3 for u in us[1:]) + u0.size
        PROGRESS.start(budget, "md5")
        # image 0: the primary's members, as they are, but the two scripts
        for name in u0.members():
            src = os.path.join(u0.root, name)
            if name == "update":
                shutil.copytree(src, os.path.join(stage, name), copy_function=_link_or_copy)
            elif os.path.isdir(src):
                shutil.copytree(src, os.path.join(stage, name), copy_function=_link_or_copy)
            else:
                _link_or_copy(src, os.path.join(stage, name))
        for junk in [n for n in os.listdir(os.path.join(stage, "update")) if n.startswith("._")]:
            os.unlink(os.path.join(stage, "update", junk))
        for n, fn in ((".bash_profile", patch_profile), ("update.sh", patch_update_sh)):
            p = os.path.join(stage, "update", n)
            with open(p, "r", encoding="utf-8", newline="") as f:
                text = f.read()
            mode = os.stat(p).st_mode & 0o777
            os.unlink(p)                       # a hard link to the cache: never written through
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(fn(text))
            os.chmod(p, mode)
        PROGRESS.step("md5 image 0", u0.size)
        programs = [(0, IMAGE0_FILE, u0.size, md5_file(u0.program, PROGRESS.add), "")]
        say("image 0: %s %s, md5 %s" % (u0.program_name, _gb(u0.size), programs[0][3]))
        delta_names = []
        delta_bytes = 0
        for i, u in enumerate(us[1:], 1):
            PROGRESS.step("md5 image %d" % i, u.size)
            want = md5_file(u.program, PROGRESS.add)
            ops = delta_ops(u0.program, u.program)
            dbytes = delta_data_bytes(ops)
            say("image %d: %s %s, md5 %s; %s differ from image 0 (%d ops)"
                % (i, u.program_name, _gb(u.size), want, _gb(dbytes), len(ops)))
            dname = DELTA_FILE % i
            delta_bytes += dbytes
            PROGRESS.step("delta image %d" % i, dbytes)
            write_delta(ops, u0.program, u.program, os.path.join(stage, dname), PROGRESS.add)
            PROGRESS.step("check image %d" % i, u.size)
            got, size = apply_delta_md5(u0.program, os.path.join(stage, dname), PROGRESS.add)
            if got != want or size != u.size:
                raise Refused("image %d: the delta rebuilds md5 %s (%d bytes), not %s (%d) - nothing written"
                              % (i, got, size, want, u.size))
            say("image %d: the delta rebuilds it byte for byte" % i)
            programs.append((i, EXTRA_FILE % i, u.size, want, dname))
            delta_names.append(dname)
        # padselect/
        pad = os.path.join(stage, PADSELECT)
        os.makedirs(os.path.join(pad, "media"))
        for name, (mode, required) in SELECTOR_FILES.items():
            src = os.path.join(a.selector_dir, name)
            if name == "font.ttf" and not os.path.isfile(src):
                # A FONT ALWAYS TRAVELS: nobody has seen what fonts a BOF machine's
                # Arch image carries, and a menu with no font draws nothing at all
                src = HOST_FONT
                if not os.path.isfile(src):
                    raise Refused("no font.ttf in %s and no %s on this Linux: the menu would have "
                                  "nothing to draw its words with (apt install fonts-dejavu-core)"
                                  % (a.selector_dir, HOST_FONT))
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(pad, name))
                os.chmod(os.path.join(pad, name), mode)
        conf = conf_from_args(a, [p[1] for p in programs], media,
                              [os.path.splitext(os.path.basename(u.fun))[0] for u in us])
        with open(os.path.join(pad, "images.conf"), "w", encoding="utf-8", newline="\n") as f:
            f.write(conf)
        with open(os.path.join(pad, PROGRAMS), "w", encoding="utf-8", newline="\n") as f:
            for idx, name, size, md5, dname in programs:
                f.write(("%d %s %d %s %s" % (idx, name, size, md5, dname)).rstrip() + "\n")
        if media:
            for name, src in media["files"].items():
                shutil.copyfile(src, os.path.join(pad, "media", name))
            shutil.copyfile(os.path.join(a.media_dir, mkc.MEDIA_MANIFEST), os.path.join(pad, mkc.MEDIA_MANIFEST))
        manifest = collections.OrderedDict([
            ("tool", TOOL), ("version", VERSION), ("written", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ("title", u0.title),
            ("images", [collections.OrderedDict([
                ("index", idx), ("program", name), ("size", size), ("md5", md5), ("delta", dname or None),
                ("source", us[idx].fun), ("source_program", us[idx].program_name),
                ("game_version", us[idx].version)]) for idx, name, size, md5, dname in programs])])
        with open(os.path.join(pad, mkc.BUILD_MANIFEST), "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(manifest, indent=1) + "\n")
        # the archive: the scripts and the menu first (inspect reads them without the rest),
        # the deltas, then everything else of image 0, its program last
        order = ["update", PADSELECT] + delta_names
        rest = [n for n in sorted(os.listdir(stage)) if n not in order and n != u0.program_name]
        order += rest + [u0.program_name]
        PROGRESS.step("archive", u0.size + delta_bytes)
        pack(stage, order, out, TITLES[u0.title]["passphrase"], PROGRESS)
        PROGRESS.finish()
        say("wrote %s (%s)" % (out, _gb(os.path.getsize(out))))
        if os.path.getsize(out) > FAT32_MAX:
            say("warning: %s is bigger than a FAT32 stick holds in one file (%s)" % (out, _gb(FAT32_MAX)))
        say("put it on the stick as %s" % TITLES[u0.title]["fun_name"])
        return 0
    finally:
        if not a.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def pack(stage, order, out, passphrase, meter=None):
    """tar -c ORDER | gzip | gpg --symmetric AES256 -> OUT (written as OUT.part, renamed).

    gpg writes to a PIPE and this writes the file, 8 MiB at a time: the output is usually on
    a Windows drive seen through WSL, where gpg's own small writes crawled at about a
    megabyte a second (a 3 GB update would have taken an hour)."""
    import threading
    part = out + ".part"
    z = ["pigz", "-6"] if shutil.which("pigz") else ["gzip", "-6"]
    tar = subprocess.Popen(["tar", "-c", "-C", stage, "--owner=0", "--group=0", "--numeric-owner",
                            "--dereference", "--"] + order, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    gz = subprocess.Popen(z + ["-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    gpg = subprocess.Popen(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase", passphrase,
                            "--symmetric", "--cipher-algo", "AES256", "--compress-algo", "none",
                            "--output", "-"], stdin=gz.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    gz.stdout.close()
    wrote = {"err": None}

    def drain():
        try:
            with open(part, "wb", buffering=CHUNK) as f:
                while True:
                    b = gpg.stdout.read(CHUNK)
                    if not b:
                        break
                    f.write(b)
        except OSError as e:
            wrote["err"] = e
            gpg.stdout.close()

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    try:
        while True:
            b = tar.stdout.read(CHUNK)
            if not b:
                break
            gz.stdin.write(b)
            if meter:
                meter.add(len(b))
        gz.stdin.close()
    except BrokenPipeError:
        pass
    terr = tar.stderr.read().decode(errors="replace")
    trc, zrc = tar.wait(), gz.wait()
    gerr = gpg.stderr.read().decode(errors="replace")
    grc = gpg.wait()
    t.join()
    if trc or zrc or grc or wrote["err"]:
        if os.path.exists(part):
            os.unlink(part)
        raise Refused("writing %s failed: tar %d %s / %s %d / gpg %d %s%s"
                      % (out, trc, terr.strip()[-300:], z[0], zrc, grc, gerr.strip()[-300:],
                         " / %s" % wrote["err"] if wrote["err"] else ""))
    os.replace(part, out)


# ============================================================================== read back
def read_front(fun, passphrase, want):
    """The small files at the front of a multi-boot .fun (update/, padselect/) without
    unpacking the programs: stream it, keep members under WANT, stop at the first program."""
    import tarfile
    g = subprocess.Popen(_gpg_argv(passphrase, fun), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    got = collections.OrderedDict()
    names = []
    try:
        with tarfile.open(fileobj=g.stdout, mode="r|gz") as tf:
            for m in tf:
                names.append(m.name)
                top = m.name.split("/", 1)[0]
                if m.isfile() and top not in ("update", PADSELECT):
                    break                      # the deltas and the programs come after
                if m.isfile() and top in want and m.size < (64 << 20):
                    got[m.name] = tf.extractfile(m).read()
    except Exception as e:
        if not got:
            raise Refused("%s could not be read as a BOF update: %s" % (fun, e))
    finally:
        g.kill()
        g.wait()
    return got, names


def inspect_fun(fun, media_out=None):
    fun = os.path.abspath(fun)
    title, pw = identify(fun)
    got, names = read_front(fun, pw, {"update", PADSELECT})
    conf_b = got.get(PADSELECT + "/images.conf")
    if conf_b is None:
        raise Refused("%s carries no boot menu (no padselect/images.conf): it is not a multi-boot update"
                      % os.path.basename(fun))
    conf = parse_conf(conf_b.decode("utf-8", errors="replace"))
    build = {}
    if PADSELECT + "/" + mkc.BUILD_MANIFEST in got:
        try:
            build = json.loads(got[PADSELECT + "/" + mkc.BUILD_MANIFEST].decode("utf-8"))
        except ValueError:
            build = {}
    media_man = None
    if PADSELECT + "/" + mkc.MEDIA_MANIFEST in got:
        try:
            media_man = json.loads(got[PADSELECT + "/" + mkc.MEDIA_MANIFEST].decode("utf-8"))
        except ValueError:
            media_man = None
    bimgs = {b.get("index"): b for b in build.get("images", [])}
    warnings = []
    images = []
    for i, ((prog, t, s), (art, anim, music, confirm)) in enumerate(zip(conf["images"], conf["media"])):
        b = bimgs.get(i, {})
        m = {}
        if isinstance(media_man, dict) and isinstance(media_man.get("images"), list) \
                and i < len(media_man["images"]) and isinstance(media_man["images"][i], dict):
            m = media_man["images"][i]
        src = b.get("source")
        if src and not os.path.isfile(src):
            warnings.append("image %d: its source %s is not on this machine" % (i, src))
        images.append(collections.OrderedDict([
            ("index", i), ("device", prog), ("title", t), ("subtitle", s),
            ("art", art or None), ("anim", anim or None), ("music", music or None), ("confirm", confirm or None),
            # what made the pictures, so the tab can make them again (the same keys as the
            # Stern and JJP reports; 'none' is no source)
            ("art_source", m.get("art_source") if m.get("art_source") not in (None, "none") else None),
            ("anim_source", m.get("anim_source") if m.get("anim_source") not in (None, "none") else None),
            ("music_source", m.get("music_source") if m.get("music_source") not in (None, "none") else None),
            ("confirm_source", m.get("confirm_source") if m.get("confirm_source") not in (None, "none") else None),
            ("source", src), ("source_exists", bool(src) and os.path.isfile(src)),
            ("name", b.get("source_program")), ("version", b.get("game_version")),
            ("game_version", b.get("game_version")),
            ("size", b.get("size")), ("md5", b.get("md5")), ("delta", b.get("delta"))]))
    media_files = sorted(n.split("/", 2)[2] for n in got if n.startswith(PADSELECT + "/media/"))
    profile = got.get("update/.bash_profile", b"").decode("utf-8", errors="replace")
    upd = got.get("update/update.sh", b"").decode("utf-8", errors="replace")
    rep = collections.OrderedDict([
        ("fun", fun), ("size", os.path.getsize(fun)), ("title", title),
        ("tool", build.get("tool")), ("tool_version", build.get("version")), ("written", build.get("written")),
        ("hook", HOOK_MARK in profile), ("install_step", INSTALL_LINE in upd),
        ("images", images),
        # the random cards, in the Stern card's inspect shape (the tab reads either)
        ("groups", [collections.OrderedDict([
            ("index", gi), ("title", g["title"]), ("subtitle", g["subtitle"]),
            ("members", list(g["members"])), ("keep", bool(g["keep"])), ("pos", g["pos"]),
            ("roll", g["roll"]), ("art", g["media"][0] or None), ("anim", g["media"][1] or None),
            ("music", g["media"][2] or None), ("confirm", g["media"][3] or None)])
            for gi, g in enumerate(conf["groups"])]),
        ("default_card", conf.get("default_card")),
        ("timeout", conf["timeout"]), ("default", conf["default"]), ("heading", conf.get("heading")),
        ("text_size", conf.get("text_size")), ("counter", conf.get("counter")),
        ("countdown_word", conf.get("countdown_word")), ("footer", conf.get("footer")),
        ("volume", conf["volume"]), ("sound_move", conf["sound_move"]), ("sound_confirm", conf["sound_confirm"]),
        ("theme", conf.get("theme")), ("colors", conf.get("colors") or {}), ("switches", conf["switches"]),
        ("media_files", media_files), ("media", media_man), ("warnings", warnings)])
    if media_out:
        os.makedirs(media_out, exist_ok=True)
        for n in media_files:
            with open(os.path.join(media_out, n), "wb") as f:
                f.write(got[PADSELECT + "/media/" + n])
        if media_man is not None:
            with open(os.path.join(media_out, mkc.MEDIA_MANIFEST), "wb") as f:
                f.write(got[PADSELECT + "/" + mkc.MEDIA_MANIFEST])
        rep["media_out"] = os.path.abspath(media_out)
    return rep


def print_inspect(rep):
    print("== %s (%s, %s)" % (rep["fun"], _gb(rep["size"]), rep["title"]))
    print("written by %s %s at %s; hook in the profile: %s; install step: %s"
          % (rep["tool"] or "?", rep["tool_version"] or "?", rep["written"] or "?",
             "yes" if rep["hook"] else "NO", "yes" if rep["install_step"] else "NO"))
    for im in rep["images"]:
        print("image %d %s '%s' '%s' art=%s version=%s source=%s"
              % (im["index"], im["device"], im["title"], im["subtitle"], im["art"], im["game_version"], im["source"]))
    for g in rep["groups"]:
        print("random card %d '%s' over images %s (%s, %s) before image %d"
              % (g["index"], g["title"], ",".join(str(m) for m in g["members"]), g["roll"],
                 "they keep their cards" if g["keep"] else "in their place", g["pos"]))
    if rep["sound_move"] or rep["sound_confirm"] or any(im.get("music") for im in rep["images"]):
        print("sound: move=%s confirm=%s volume=%s" % (rep["sound_move"], rep["sound_confirm"], rep["volume"]))
    print("timeout=%s default=%s theme=%s switches=%s" % (rep["timeout"], rep["default"], rep["theme"],
                                                          ",".join("%s=%s" % kv for kv in rep["switches"].items())))
    for w in rep["warnings"]:
        print("warning: " + w)


def verify_fun(a):
    """Read a multi-boot .fun back the way the machine will: the scripts patched, the menu
    there, exactly one *.x86_64, and (unless --quick) every image rebuilt from its delta by
    the paddelta it carries and checked against the md5 it records."""
    need_tools("gpg", "tar")
    fun = os.path.abspath(a.fun)
    title, pw = identify(fun)
    bad = []
    got, names = read_front(fun, pw, {"update", PADSELECT})
    profile = got.get("update/.bash_profile", b"").decode("utf-8", errors="replace")
    upd = got.get("update/update.sh", b"").decode("utf-8", errors="replace")
    if HOOK_MARK not in profile:
        bad.append("update/.bash_profile carries no menu hook")
    if not any(HEAL_RM in ln for ln in profile.splitlines()):
        bad.append("update/.bash_profile's self-repair copy has no rm -f in front of it")
    if INSTALL_LINE not in upd:
        bad.append("update/update.sh does not run the install step")
    for name in list(SELECTOR_FILES) + ["images.conf", PROGRAMS]:
        if PADSELECT + "/" + name not in got:
            bad.append("padselect/%s is missing" % name)
    progs = []
    for line in got.get(PADSELECT + "/" + PROGRAMS, b"").decode().splitlines():
        f = line.split()
        if len(f) >= 4:
            progs.append((int(f[0]), f[1], int(f[2]), f[3], f[4] if len(f) > 4 else ""))
    conf = parse_conf(got.get(PADSELECT + "/images.conf", b"").decode("utf-8", errors="replace"))
    if [p for p, _t, _s in conf["images"]] != [p[1] for p in progs]:
        bad.append("images.conf names %r but programs records %r"
                   % ([p for p, _t, _s in conf["images"]], [p[1] for p in progs]))
    for b in bad:
        say("verify: " + b)
    if a.quick or bad:
        say("verify: %s%s" % ("FAILED" if bad else "OK", " (quick: nothing unpacked)" if a.quick and not bad else ""))
        return 0 if not bad else 1
    base = a.workdir or CACHE_DIR_DEFAULT
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="bofverify.", dir=base)
    try:
        PROGRESS.start(os.path.getsize(fun) + sum(p[2] for p in progs), "unpack")
        PROGRESS.step("unpack", os.path.getsize(fun))
        unpack(fun, pw, tmp, PROGRESS.add)
        xs = [n for n in os.listdir(tmp) if n.endswith(".x86_64") and not n.startswith(".")]
        if len(xs) != 1:
            bad.append("%d *.x86_64 programs (BOF's updater wants exactly one): %r" % (len(xs), xs))
        else:
            os.rename(os.path.join(tmp, xs[0]), os.path.join(tmp, IMAGE0_FILE))
        paddelta = os.path.join(tmp, PADSELECT, "paddelta")
        for idx, name, size, md5, dname in progs:
            path = os.path.join(tmp, name)
            if dname:
                if not os.path.isfile(os.path.join(tmp, dname)):
                    bad.append("image %d: %s is missing" % (idx, dname))
                    continue
                r = subprocess.run([paddelta, os.path.join(tmp, IMAGE0_FILE), os.path.join(tmp, dname), path],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if r.returncode != 0:
                    bad.append("image %d: paddelta failed: %s" % (idx, r.stdout.decode(errors="replace").strip()))
                    continue
            PROGRESS.step("md5 image %d" % idx, size)
            if not os.path.isfile(path):
                bad.append("image %d: %s is missing" % (idx, name))
                continue
            have = md5_file(path, PROGRESS.add)
            if have != md5 or os.path.getsize(path) != size:
                bad.append("image %d: %s is md5 %s, %d bytes; programs says %s, %d"
                           % (idx, name, have, os.path.getsize(path), md5, size))
            else:
                say("verify: image %d (%s) rebuilt and checked: md5 %s" % (idx, name, md5))
        PROGRESS.finish()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for b in bad:
        say("verify: " + b)
    say("verify: %s" % ("FAILED" if bad else "OK"))
    return 0 if not bad else 1


# ============================================================================== inject
def inject_fun(a):
    """A new menu for an existing multi-boot .fun, written over it: the update unpacked,
    padselect/ rewritten (the conf from the flags, falling back to the update's own values;
    the menu program from --selector-dir when given; the pictures from --media-dir, else
    the ones it carries), packed and encrypted again.  The programs and the deltas are not
    touched; minutes, not a rebuild."""
    need_tools("gpg", "tar")
    fun = os.path.abspath(check_output_path(a.fun, [], must_exist=True))
    title, pw = identify(fun)
    got, _names = read_front(fun, pw, {PADSELECT})
    if PADSELECT + "/images.conf" not in got:
        raise Refused("%s carries no boot menu: build a multi-boot update first" % os.path.basename(fun))
    old = parse_conf(got[PADSELECT + "/images.conf"].decode("utf-8", errors="replace"))
    if a.selector_dir:
        check_selector_dir(a.selector_dir)
    cache = a.cache_dir or CACHE_DIR_DEFAULT
    os.makedirs(cache, exist_ok=True)
    work = os.path.abspath(a.workdir) if a.workdir else tempfile.mkdtemp(prefix="bofinject.", dir=cache)
    stage = os.path.join(work, "stage")
    try:
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        size = os.path.getsize(fun)
        PROGRESS.start(size * 3, "unpack")
        PROGRESS.step("unpack", size)
        unpack(fun, pw, stage, PROGRESS.add)
        pad = os.path.join(stage, PADSELECT)
        programs = [p for p, _t, _s in old["images"]]
        media = None
        media_dir = a.media_dir
        if media_dir is None and os.path.isfile(os.path.join(pad, mkc.MEDIA_MANIFEST)):
            media_dir = os.path.join(work, "media_carried")
            shutil.copytree(os.path.join(pad, "media"), media_dir)
            shutil.copyfile(os.path.join(pad, mkc.MEDIA_MANIFEST), os.path.join(media_dir, mkc.MEDIA_MANIFEST))
            say("media: the update's own set is carried through")
        if media_dir:
            media = mkc.plan_media(media_dir, len(programs))
        # every flag the tab sends; the update's own value where one is left off
        for k in ("timeout", "default", "volume", "heading", "text_size", "counter", "countdown_word", "theme"):
            if getattr(a, k, None) is None and old.get(k) is not None:
                setattr(a, k, old[k])
        if not a.footer_own and a.footer is None and old.get("footer") is not None:
            a.footer = old["footer"]
        if not a.color and old.get("colors"):
            a.color = ["%s=%s" % kv for kv in old["colors"].items()]
        if a.subtitles is None:                 # '' is a choice: no subtitles
            a.subtitles = ";".join(s for _p, _t, s in old["images"])
        # the random cards are the update's own (inject rewrites the menu, not which builds
        # it holds); --default-card overrides, else the update's own
        # (their pictures and sounds come from the media set, new or carried, like every card's)
        a.groups = [dict(g, media=mkc.MEDIA_ROW) for g in old["groups"]]
        if getattr(a, "default_card", None) is None:
            a.default_card = old.get("default_card")
        a._title = title
        conf = conf_from_args(a, programs, media, [t for _p, t, _s in old["images"]])
        with open(os.path.join(pad, "images.conf"), "w", encoding="utf-8", newline="\n") as f:
            f.write(conf)
        if a.selector_dir:
            for name, (mode, _req) in SELECTOR_FILES.items():
                src = os.path.join(a.selector_dir, name)
                if os.path.isfile(src):
                    shutil.copyfile(src, os.path.join(pad, name))
                    os.chmod(os.path.join(pad, name), mode)
        if a.media_dir:
            shutil.rmtree(os.path.join(pad, "media"), ignore_errors=True)
            os.makedirs(os.path.join(pad, "media"))
            for name, src in media["files"].items():
                shutil.copyfile(src, os.path.join(pad, "media", name))
            shutil.copyfile(os.path.join(a.media_dir, mkc.MEDIA_MANIFEST), os.path.join(pad, mkc.MEDIA_MANIFEST))
        bp = os.path.join(pad, mkc.BUILD_MANIFEST)
        if os.path.isfile(bp):
            with open(bp, encoding="utf-8") as f:
                try:
                    man = json.load(f, object_pairs_hook=collections.OrderedDict)
                except ValueError:
                    man = collections.OrderedDict()
            man["menu_written"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(bp, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(man, indent=1) + "\n")
        prog = [n for n in os.listdir(stage) if n.endswith(".x86_64") and not n.startswith(".")]
        if len(prog) != 1:
            raise Refused("%s carries %d *.x86_64 programs; it is not one this tool wrote" % (fun, len(prog)))
        deltas = sorted(n for n in os.listdir(stage) if re.match(r"^pad_image\d+\.delta$", n))
        order = ["update", PADSELECT] + deltas
        order += [n for n in sorted(os.listdir(stage)) if n not in order and n != prog[0]] + [prog[0]]
        PROGRESS.step("archive", size * 2)
        pack(stage, order, fun, pw, PROGRESS)
        PROGRESS.finish()
        say("the menu of %s is rewritten (%s)" % (fun, _gb(os.path.getsize(fun))))
        return 0
    finally:
        if not getattr(a, "keep_work", False):
            shutil.rmtree(work, ignore_errors=True)


# ============================================================================== media
def _bof_sound(spec):
    """'auto' is a sound pulled off a STERN card (through the emulator); a .fun has no such
    catalogue the tools can reach, so it is the built-in synthetic click / chime here - what
    the JJP menu does too.  Everything else passes through."""
    s = (spec or "").strip()
    return "synth" if s.lower().startswith("auto") else s


def _pack_files(program):
    """(directory, {path: entry}) of a program's Godot pack (plugins/bof/pck_directory.py)."""
    from pinball_decryptor.plugins.bof import pck_directory
    d = pck_directory.read(program)
    if d is None:
        raise Refused("%s has no Godot pack directory" % os.path.basename(program))
    return d, {e["praw"].rstrip(b"\0").decode("utf-8", "replace"): e for e in d.entries}


def _copy_out(program, d, e, dest):
    """One packed file to *dest*, md5-checked against the directory, written once."""
    if os.path.isfile(dest) and os.path.getsize(dest) == e["size"]:
        return
    h = hashlib.md5()
    with open(program, "rb") as src, open(dest + ".part", "wb") as out:
        src.seek(d.pck_off + d.base + e["ofs"])
        left = e["size"]
        while left:
            buf = src.read(min(CHUNK, left))
            if not buf:
                raise Refused("%s ends inside %s" % (os.path.basename(program), os.path.basename(dest)))
            h.update(buf)
            out.write(buf)
            left -= len(buf)
    if h.digest() != bytes(e["md5"]):
        os.unlink(dest + ".part")
        raise Refused("%s: %s does not match its md5 in the pack" % (os.path.basename(program), dest))
    os.rename(dest + ".part", dest)


def _read_packed(program, d, e):
    """One small packed file's bytes, md5-checked against the directory."""
    with open(program, "rb") as f:
        f.seek(d.pck_off + d.base + e["ofs"])
        data = f.read(e["size"])
    if len(data) != e["size"] or hashlib.md5(data).digest() != bytes(e["md5"]):
        raise Refused("%s: a packed file does not match its md5" % os.path.basename(program))
    return data


def _imported(program, d, files, src):
    """The imported resource a source file became (``res://`` path=... in its .import), or None."""
    imp = files.get(src + ".import")
    if not imp:
        return None
    m = re.search(rb'path="res://([^"]+)"', _read_packed(program, d, imp))
    res = m.group(1).decode("utf-8", "replace") if m else None
    return res if res in files else None


def _sound_out(program, d, files, res, src, mdir):
    """A packed sample (*res*, from *src*) decoded to a sound file in *mdir*, written once - a
    .wav for PCM and QOA (plugins/bof/source_converter.py), an .ogg passed through.  None when
    it does not decode."""
    try:
        from pinball_decryptor.plugins.bof import source_converter
    except ImportError as e:
        # an install that does not carry the decoder: the fallback sound, never a failed build
        # (a Mac build stopped here with the module missing from its container, 2026-10-05)
        say("note: the game's sounds cannot be decoded here (%s)" % e)
        return None
    stem = os.path.join(mdir, re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(src)[0]))
    for ext in (".wav", ".ogg"):
        if os.path.isfile(stem + ext):
            return stem + ext
    ext, data = source_converter._decode_sample(_read_packed(program, d, files[res]))
    if not data or ext not in (".wav", ".ogg"):
        return None
    with open(stem + ".part", "wb") as f:
        f.write(data)
    os.rename(stem + ".part", stem + ext)
    return stem + ext


def own_audio(images, cache_dir, music_need, sounds):
    """``{"music": {image: file}, "move": file|None, "confirm": file|None}`` - the game's own
    sound for 'auto' (TITLES[..]['music'] / 'sound_move' / 'sound_confirm'), decoded out of
    each build's pack into CACHE/<unpack>.media/.  The music bed is each asked-for build's own
    (pick_clip's rule: image 0 the first, a mod the first it changed); the move and confirm
    sounds are image 0's, and only when *sounds*.  What cannot be found or decoded is left
    out, and says so: the caller falls back (no bed; the synthetic click and chime)."""
    out = {"music": {}, "move": None, "confirm": None}
    if not music_need and not sounds:
        return out
    u0 = cached_unpack(images[0], cache_dir)
    spec = TITLES[u0.title]
    try:
        d0, base = _pack_files(u0.program)
    except Exception as e:                                  # noqa: BLE001
        say("note: %s's pack cannot be read (%s): 'auto' sounds are the synthetic ones"
            % (os.path.basename(images[0]), e))
        return out
    if sounds:
        mdir = u0.root + MEDIA_SUFFIX
        os.makedirs(mdir, exist_ok=True)
        for key in ("move", "confirm"):
            src = spec.get("sound_" + key)
            res = _imported(u0.program, d0, base, src) if src else None
            out[key] = _sound_out(u0.program, d0, base, res, src, mdir) if res else None
            say("%s sound: %s" % (key, ("the game's own %s" % src) if out[key] else "not found, the synthetic one"))
    for i in sorted(music_need):
        u = u0 if i == 0 else cached_unpack(images[i], cache_dir)
        try:
            d, files = (d0, base) if i == 0 else _pack_files(u.program)
        except Exception as e:                              # noqa: BLE001
            say("note: image %d: its pack cannot be read (%s): no music of its own" % (i, e))
            continue
        table = [(r, s) for r, s in ((_imported(u.program, d, files, s), s) for s, _t in spec.get("music") or [])
                 if r]
        pick = pick_clip(table, base, files, i)
        if pick is None:
            say("note: image %d carries none of the music 'auto' knows: no bed" % i)
            continue
        res, src, changed = pick
        mdir = u.root + MEDIA_SUFFIX
        os.makedirs(mdir, exist_ok=True)
        f = _sound_out(u.program, d, files, res, src, mdir)
        if f:
            out["music"][i] = f
            say("image %d: its own music, %s%s" % (i, src, " (changed from image 0)" if changed else ""))
        else:
            say("note: image %d: %s does not decode: no bed" % (i, src))
    return out


def own_media(images, cache_dir, need):
    """{image: (clip, still)} - each asked-for build's OWN attract clip and a still of it, out
    of its own program (PAD-342: what 'auto' is on BOF, the way a Stern card's 'auto' is its
    logo and attract clip).  Which clip is TITLES[..]['attract_clips']: image 0 the first there
    is, every other build the first one it changed from image 0, else the first.  Written once
    into CACHE/<unpack>.media/, so selectmedia's own cache keeps hitting.  A build whose pack
    has none of them, or no readable directory, is left out, and says so: its card is words."""
    if not need:
        return {}
    units = {}

    def unit(i):
        if i not in units:
            units[i] = cached_unpack(images[i], cache_dir)
        return units[i]

    table = TITLES[unit(0).title].get("attract_clips") or []
    try:
        base = _pack_files(unit(0).program)[1]
    except Exception as e:                                  # noqa: BLE001 - said, then text cards
        say("note: %s's pack cannot be read (%s): 'auto' pictures are none" % (os.path.basename(images[0]), e))
        return {}
    import selectmedia
    ff = selectmedia.find_ffmpeg()
    out = {}
    for i in sorted(need):
        u = unit(i)
        try:
            d, files = _pack_files(u.program)
        except Exception as e:                              # noqa: BLE001
            say("note: image %d: its pack cannot be read (%s): its 'auto' picture is none" % (i, e))
            continue
        pick = pick_clip(table, base, files, i)
        if pick is None:
            say("note: image %d carries none of the attract clips 'auto' knows: its card is words" % i)
            continue
        path, at, changed = pick
        mdir = u.root + MEDIA_SUFFIX
        os.makedirs(mdir, exist_ok=True)
        clip = os.path.join(mdir, os.path.basename(path))
        _copy_out(u.program, d, files[path], clip)
        still = os.path.join(mdir, "%s@%g.png" % (os.path.splitext(os.path.basename(path))[0], at))
        if not os.path.isfile(still):
            if not ff:
                raise Refused("ffmpeg is required for a BOF build's own picture")
            r = subprocess.run([ff, "-v", "error", "-y", "-ss", "%g" % at, "-i", clip, "-frames:v", "1",
                                still + ".part.png"], capture_output=True, text=True)
            if r.returncode or not os.path.isfile(still + ".part.png"):
                raise Refused("could not take a still from %s: %s" % (clip, r.stderr.strip()[-300:]))
            os.rename(still + ".part.png", still)
        say("image %d: its own %s%s" % (i, path, " (changed from image 0)" if changed else ""))
        out[i] = (clip, still)
    return out


def pick_clip(table, base, files, i):
    """``(pack path, still at, changed)`` - which of *table*'s clips is image *i*'s own, out of
    its pack's *files* and image 0's (*base*), both ``{path: entry}``: image 0 the first it
    carries; any other the first it CHANGED from image 0 (or added), else the first it carries.
    None when it carries none of them."""
    have = [(p, t) for p, t in table if p in files]
    if not have:
        return None
    if i:
        for p, t in have:
            if p not in base or bytes(base[p]["md5"]) != bytes(files[p]["md5"]):
                return p, t, True
    return have[0][0], have[0][1], False


def _is_style(spec):
    import selectmedia
    return (spec or "").strip().lower() in set(selectmedia.GROUP_ART_STYLES) | set(selectmedia.GROUP_ANIM_STYLES)


def cmd_media(a):
    """The menu's pictures and sounds through selectmedia.py prepare.  'auto' art and animation
    are the build's own attract clip and a still of it (:func:`own_media`), and those stills are
    the logos a random card's styles are drawn from (``--logo``).  'auto' music is the build's
    own bed and an 'auto' move or confirm sound the game's own (:func:`own_audio`); what cannot
    be found falls back to no bed and the synthetic click and chime.  media.json still records
    'auto' for what was resolved, which is what the tab asked for.  The sounds play through the
    machine's own aplay (padselect.sh pipes the menu's mix to it)."""
    import selectmedia
    images = [os.path.abspath(a.primary)] + [os.path.abspath(e) for e in a.extra]
    n = len(images)
    arts = selectmedia.parse_index_spec(a.art, n, "none")
    anims = selectmedia.parse_index_spec(a.anim, n, "none")
    musics = selectmedia.parse_index_spec(a.music, n, "none")
    members = {}
    for spec in a.group_members:
        g, _sep, val = spec.partition("=")
        members[g.strip()] = [int(x) for x in val.split(",") if x.strip().isdigit()]
    styled = [g for g, val in (s.partition("=")[::2] for s in a.group_art + a.group_anim) if _is_style(val)]
    need = {i for i in range(n) if arts[i].startswith("auto") or anims[i].startswith("auto")}
    need |= {m for g in styled for m in members.get(g.strip(), []) if 0 <= m < n}
    own = own_media(images, a.cache_dir or CACHE_DIR_DEFAULT, need)
    argv = ["prepare", "--primary", images[0]]
    for e in images[1:]:
        argv += ["--extra", e]
    argv += ["--out", os.path.abspath(a.out)]
    if a.cards:
        argv += ["--cards", str(a.cards)]
    resolved = {}                                  # (key, image) -> the spec the tab asked for
    for i, spec in enumerate(arts):
        if spec.startswith("auto"):
            resolved[("art_source", i)] = spec
            spec = own[i][1] if i in own else "none"
        argv += ["--art", "%d=%s" % (i, spec)]
    for i, spec in enumerate(anims):
        if spec.startswith("auto"):
            resolved[("anim_source", i)] = spec
            start = spec.partition("@")[2]
            spec = (own[i][0] + ("@" + start if start else "")) if i in own else "none"
        argv += ["--anim", "%d=%s" % (i, spec)]
    for i in sorted(own):
        argv += ["--logo", "%d=%s" % (i, own[i][1])]
    # THE GAME'S OWN SOUND for 'auto' (own_audio): each build's music bed, the move click and
    # the START sound; what it cannot find stays what it was (no bed, the synthetic ones)
    auto = lambda s: (s or "").strip().lower().startswith("auto")       # noqa: E731
    confirms = [s.partition("=")[2] if s.partition("=")[1] and s.partition("=")[0].strip().isdigit() else s
                for s in a.sound_confirm or []] + [s.partition("=")[2] for s in a.group_confirm]
    sounds = not a.visual_only and (auto(a.sound_move) or any(auto(s) for s in confirms))
    aud = own_audio(images, a.cache_dir or CACHE_DIR_DEFAULT, {i for i in range(n) if auto(musics[i])}, sounds)
    top = {}                                       # media.json top-level key -> the spec asked for

    def sound(s, key=None, rows=None):
        if not auto(s):
            return s
        kind = "confirm" if key != "sound_move_source" else "move"
        if not aud[kind]:
            return _bof_sound(s)
        if rows is not None:
            resolved[rows] = s
        elif key:
            top[key] = s
        return aud[kind]
    for i, spec in enumerate(musics):
        if auto(spec):
            if i in aud["music"]:
                resolved[("music_source", i)] = spec
            spec = aud["music"].get(i, "none")
        argv += ["--music", "%d=%s" % (i, spec)]
    argv += ["--sound-move", sound(a.sound_move, "sound_move_source")]
    for spec in a.sound_confirm or ["none"]:
        idx, sep, val = spec.partition("=")
        if sep and idx.strip().isdigit():
            argv += ["--sound-confirm", "%s=%s" % (idx, sound(val, rows=("confirm_source", int(idx))))]
        else:
            argv += ["--sound-confirm", sound(spec, "sound_confirm_source")]
    for spec in a.group_members:
        argv += ["--group-members", spec]

    def picture(g, val):
        # a style is drawn from the members' logos - their own stills - so it needs every one
        s = (val or "").strip()
        if s.lower().startswith("auto"):
            return "none"
        if _is_style(s) and not all(m in own for m in members.get(g.strip(), [None])):
            say("note: random card %s: a %s is drawn from its builds' own pictures, and not every "
                "one has one - it shows its words" % (g, s))
            return "none"
        return s
    for flag, specs, fix in (("--group-art", a.group_art, picture),
                             ("--group-anim", a.group_anim, picture),
                             ("--group-music", a.group_music,
                              lambda _g, s: "none" if s.lower().startswith("auto") else s),
                             ("--group-confirm", a.group_confirm,
                              lambda g, s: sound(s, rows=("group", "confirm_source", int(g))))):
        for spec in specs:
            g, _sep, val = spec.partition("=")
            argv += [flag, "%s=%s" % (g, fix(g, val))]
    argv += ["--volume", str(VOLUME_DEFAULT if a.volume is None else a.volume)]
    if a.size:
        argv += ["--size", a.size]
    if a.visual_only:
        argv += ["--visual-only"]
    if a.work:
        argv += ["--work", a.work]
    rc = selectmedia.main(argv)
    if rc == 0 and (resolved or top):
        # THE MANIFEST SAYS WHAT WAS ASKED FOR: 'auto', not the clip or sample it came to in the
        # cache - the tab offers a rendered picture, and counts a sound as ready, only while its
        # source is the row's own spec, and a load of the update reads the row back from it
        man_path = os.path.join(os.path.abspath(a.out), "media.json")
        with open(man_path) as f:
            man = json.load(f)
        for where, spec in resolved.items():
            section, key, i = ("images",) + where if len(where) == 2 else where
            rows = man.get("groups" if section == "group" else "images") or []
            if i < len(rows) and isinstance(rows[i], dict) and rows[i].get(key) not in (None, "none"):
                rows[i][key] = spec
        for key, spec in top.items():
            if man.get(key) not in (None, "none"):
                man[key] = spec
        with open(man_path + ".part", "w") as f:
            json.dump(man, f)
        os.replace(man_path + ".part", man_path)
    return rc


# ============================================================================== main
def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="a directory holding bofselect, paddelta, padselect.sh, pad_install.sh "
                                          "and optionally font.ttf (ensurebofselect.sh installs one)")
    s.add_argument("--media-dir", help="directory holding media.json (mkbofmulti.py media) and the files it names")
    s.add_argument("--titles", help="';'-separated titles, one per image (index order)")
    s.add_argument("--subtitles", help="';'-separated subtitles, one per image")
    s.add_argument("--timeout", type=int, help="images.conf timeout in seconds (default 15; 0 = wait for ever)")
    s.add_argument("--heading", metavar="TEXT", help="images.conf heading=TEXT ('' = no line)")
    s.add_argument("--footer", metavar="TEXT", help="images.conf footer=TEXT ('' = no line)")
    s.add_argument("--footer-own", action="store_true", help="no footer= line: the selector's own wording")
    s.add_argument("--counter", choices=list(mkc.COUNTERS))
    s.add_argument("--countdown-word", metavar="TEXT")
    s.add_argument("--text-size", choices=list(mkc.TEXT_SIZES))
    s.add_argument("--default", type=int, help="images.conf default index (default 0)")
    s.add_argument("--volume", type=int, help="images.conf volume 0-100: the menu's sounds, mixed in software")
    s.add_argument("--theme", help="the menu's colours: one of codeselect/themes.json's names, or custom")
    s.add_argument("--color", action="append", metavar="ROLE=RRGGBB", help="one colour on top of the theme")
    s.add_argument("--conf", help="use this images.conf verbatim instead of generating one")
    s.add_argument("--learn", action="store_true",
                   help="images.conf learn=1: the hook runs the menu with --learn (every switch change in its log)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan", help="what the update costs and whether it fits a FAT32 stick; writes nothing")
    s.add_argument("--primary", required=True, help="image 0's .fun (installed by BOF's updater as it is)")
    # ORDERED against the random-card flags, exactly as mkmulticard reads them: a --member is
    # an image (a delta like any --extra) and where its flag sits fixes its index
    s.add_argument("--extra", action=mkc._OrderedImage, default=[], metavar="FUN",
                   help="another build of the same title")
    mkc._add_group_flags(s)
    s.add_argument("--media-dir")
    s.add_argument("--cache-dir", help="where the .fun files are unpacked (default %s)" % CACHE_DIR_DEFAULT)
    s = sub.add_parser("build", help="write the multi-boot .fun")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action=mkc._OrderedImage, default=[], metavar="FUN")
    mkc._add_group_flags(s)
    s.add_argument("--out", required=True, help="the .fun to write")
    _add_conf_flags(s)
    s.add_argument("--force", action="store_true", help="overwrite an existing --out")
    s.add_argument("--workdir", help="scratch directory (default: under the cache)")
    s.add_argument("--cache-dir")
    s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("inject", help="a new menu for an existing multi-boot .fun, written over it")
    s.add_argument("--fun", required=True, help="the multi-boot .fun to rewrite IN PLACE")
    _add_conf_flags(s)
    s.add_argument("--default-card", type=int, metavar="N",
                   help="highlight CARD N (menu order) - a random card whose members keep their own "
                        "(default: the update's own)")
    s.add_argument("--primary", help="(recorded for the tab; nothing is read from it)")
    s.add_argument("--extra", action="append", default=[], metavar="FUN")
    s.add_argument("--workdir")
    s.add_argument("--cache-dir")
    s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("verify", help="read a multi-boot .fun back and rebuild every image")
    s.add_argument("--fun", required=True)
    s.add_argument("--primary", help="(recorded for the tab; the .fun carries everything checked)")
    s.add_argument("--extra", action="append", default=[], metavar="FUN")
    s.add_argument("--quick", action="store_true", help="the scripts and the menu only; nothing unpacked")
    s.add_argument("--workdir")
    s = sub.add_parser("inspect", help="read a multi-boot .fun's menu back")
    s.add_argument("--fun", required=True)
    s.add_argument("--json", action="store_true", dest="as_json", help="print ONE JSON object")
    s.add_argument("--media-out", help="also extract the menu media + media.json into this directory")
    s = sub.add_parser("media", help="the menu's pictures + media.json through selectmedia.py")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[], metavar="FUN")
    s.add_argument("--out", required=True)
    s.add_argument("--art", action="append", default=[], metavar="N=auto|none|PATH|VIDEO@T",
                   help="image N's picture ('auto' = a still of the build's own attract clip)")
    s.add_argument("--anim", action="append", default=[], metavar="N=auto|none|PATH[@START[:SECONDS[:FPS]]]",
                   help="image N's clip ('auto' = the build's own attract clip, out of its .fun)")
    s.add_argument("--music", action="append", default=[], metavar="N=none|PATH",
                   help="the bed that loops while image N is highlighted ('auto' = the build's own, out of its .fun)")
    s.add_argument("--sound-move", default="none", metavar="PATH|synth|none",
                   help="the click a flipper makes ('auto' = the game's own menu sound)")
    s.add_argument("--sound-confirm", action="append", default=[], metavar="[N=]PATH|synth|none",
                   help="the sound START makes: a bare value for every card, N= for image N's own")
    s.add_argument("--cards", type=int, default=0, metavar="N",
                   help="how many CARDS the menu draws (a random card stands for several images)")
    s.add_argument("--group-members", action="append", default=[], metavar="G=I,J,...")
    s.add_argument("--group-art", action="append", default=[], metavar="G=STYLE|PATH|none",
                   help="random card G's picture: a style drawn from its builds' own stills, or a file")
    s.add_argument("--group-anim", action="append", default=[], metavar="G=STYLE|none")
    s.add_argument("--group-music", action="append", default=[], metavar="G=PATH|none")
    s.add_argument("--group-confirm", action="append", default=[], metavar="G=PATH|synth|none")
    s.add_argument("--volume", type=int)
    s.add_argument("--size")
    s.add_argument("--visual-only", action="store_true",
                   help="the pictures only (the preview): no sound work")
    s.add_argument("--work")
    s.add_argument("--cache-dir")
    a = ap.parse_args(list(sys.argv[1:]) if argv is None else list(argv))
    try:
        if a.cmd in ("plan", "build"):
            mkc.resolve_image_args(a)           # a.extra (members included) + a.groups
        if a.cmd == "plan":
            print_plan(make_plan(a))
            return 0
        if a.cmd == "build":
            return build_fun(a)
        if a.cmd == "inject":
            return inject_fun(a)
        if a.cmd == "verify":
            return verify_fun(a)
        if a.cmd == "inspect":
            rep = inspect_fun(a.fun, a.media_out)
            if a.as_json:
                print(json.dumps(rep, indent=1))
            else:
                print_inspect(rep)
            return 0
        if a.cmd == "media":
            return cmd_media(a)
    except Refused as e:
        say("error: %s" % e)
        return 2
    except KeyboardInterrupt:
        say("error: interrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
