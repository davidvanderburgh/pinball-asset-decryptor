#!/usr/bin/env python3
"""mkspkmulti.py - a multi-boot for a Spooky Pinball game (PAD-980): several builds of one
title on one machine and a boot menu it shows at power-up - the flippers choose, START boots,
the countdown boots the last one picked - drawn by the same menu program a Stern card, a JJP,
a Barrels of Fun and a Big Lebowski machine show.  tools/spooky_emu/MULTIBOOT.md has the story.

    mkspkmulti.py plan    --primary STOCK --extra MOD ...                 what it costs
    mkspkmulti.py build   --primary STOCK --extra MOD --out OUT --selector-dir DIR ...
    mkspkmulti.py verify  --zip OUT                                       read it back, check it
    mkspkmulti.py inspect --zip OUT [--json] [--media-out DIR]            the menu it carries
    mkspkmulti.py inject  --zip OUT ...                                   a new menu, written over it
    mkspkmulti.py media   --primary STOCK --extra MOD --out DIR           the menu's pictures

WHAT IT MAKES: ONE update file of the title's own kind, under the primary's own name (the
machines' update menus list by extension, Texas Chainsaw's by tcm-N_NN.pkg), packed the way
the primary came: a .scooby / .ed / tcm .pkg as tar.gz, a .looney as tar, a .beetlejuice
signed (it installs in the game's developer mode, as every non-Spooky Beetlejuice update
does), a Halloween / Ultraman code_*.pkg GPG-encrypted with the title's passphrase.  The
machine's own install puts it in /game/code/uptest:

    uptest/main.x86_64     the launcher (codeselect/padselect_spk.sh): the machine's desktop
                           runs it at every power-up; it makes the builds, shows the menu,
                           starts one (and first moves pad/ to /game/pad)
    uptest/pad/            spkselect, spksw, font.ttf, spk.conf, images.conf, builds.txt,
                           build.json, media/
    uptest/pad/b0/         the primary build WHOLE, laid out as on the machine: uptest/...,
                           and assets/, config/ for the titles that keep them in /game/code
    uptest/pad/d<k>/       build k's files that differ from b0's; d<k>.removed the ones it lacks

(A flat title - Beetlejuice, Scooby-Doo, Looney Tunes - has no uptest/ in its archive: the
archive's root IS uptest.)  Every image must be the same title; the primary is the stock build
everything falls back to.

Pure Python (tarfile) plus the Spooky plugin's GPG helpers; runs anywhere the tab does.
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SPIKE2_EMU = os.path.join(REPO_ROOT, "tools", "spike2_emu")
BOF_EMU = os.path.join(REPO_ROOT, "tools", "bof_emu")
for _p in (SPIKE2_EMU, BOF_EMU, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import mkmulticard as mkc                                           # noqa: E402  the shared pure parts
from mkmulticard import Refused, say, PROGRESS, check_output_path   # noqa: E402
import mkbofmulti as bof                                            # noqa: E402  the conf writer
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mkspkproc as sp                                              # noqa: E402  the P-ROC titles

TOOL = "mkspkmulti"
#: build.json's shape; a reader must accept an older (or missing) one.
VERSION = "1.0"
PAD = "pad"
MAX_IMAGES = 9
FAT32_MAX = 4 * 1024 ** 3 - 1
FAT32_MARGIN = 64 << 20
USB_SIZES = collections.OrderedDict([("8G", 7_700_000_000), ("16G", 15_400_000_000),
                                     ("32G", 30_900_000_000), ("64G", 61_800_000_000)])
SELECTOR_FILES = collections.OrderedDict([      # name in --selector-dir -> (mode, required)
    ("spkselect", (0o755, True)),
    ("spksw", (0o755, True)),
    ("padselect.sh", (0o755, True)),
    ("font.ttf", (0o644, False)),
])
VOLUME_DEFAULT = 50
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SWITCHES = collections.OrderedDict()
CONF_HEADER = [
    "# images.conf - Spooky Pinball boot menu (spkselect + the launcher uptest/main.x86_64); written by mkspkmulti.py",
    "# image=b<k>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
    "# b<k> = the build the card starts (b0 is the primary, carried whole; the launcher makes the rest);",
    "# default = highlight when there is no last choice; timeout = seconds before it boots by itself"]

#: Every title this builds for, keyed by the Spooky plugin's game key (formats.detect_game).
#:   flat     the archive's root is uptest/ (else it holds uptest/, assets/, config/)
#:   board    warden | pinotaur, and its L / R / START switches (spktitles.py's cabinet rows)
#:   roots    per-build folders outside uptest: name -> where the game reads them
#:   free     what /game has free on the factory restore image (MULTIBOOT.md), for the plan
TITLES = {
    "beetlejuice": dict(name="BEETLEJUICE", flat=True, board="warden", sw=(86, 80, 87), roots=(),
                        free=219_600_000_000),
    "scooby_doo": dict(name="SCOOBY-DOO", flat=True, board="warden", sw=(86, 80, 87), roots=(),
                       free=None),
    "legends_of_tera": dict(name="LOONEY TUNES", flat=True, board="warden", sw=(86, 80, 87), roots=(),
                            free=12_500_000_000),
    "evil_dead": dict(name="EVIL DEAD", flat=False, board="warden", sw=(86, 80, 87),
                      roots=(("assets", "/game/code/assets"),), free=230_400_000_000),
    "texas_chainsaw": dict(name="TEXAS CHAINSAW MASSACRE", flat=False, board="warden", sw=(86, 80, 87),
                           roots=(("assets", "/game/code/assets"), ("config", "/game/code/config")),
                           free=5_800_000_000),
    "halloween_78": dict(name="HALLOWEEN", flat=False, board="pinotaur", sw=(81, 80, 87),
                         roots=(("assets", "/game/code/assets"), ("config", "/game/code/config")),
                         free=14_800_000_000),
    "ultraman": dict(name="ULTRAMAN", flat=False, board="pinotaur", sw=(81, 80, 87),
                     roots=(("assets", "/game/code/assets"), ("config", "/game/code/config")),
                     free=14_600_000_000),
    # The P-ROC titles (mkspkproc.py): the package's root IS the game's folder, the stock
    # build stays there, and the menu, the launcher and the other builds travel in
    # PAD_MULTIBOOT/.  Free: Rick and Morty's /home (7.4 GB, the build 3.5 GB), Alice
    # Cooper's /game (16 GB, 3.2 GB used) - the builds share b0's files by hard links.
    "rick_and_morty": dict(sp.PROC["rick_and_morty"], name="RICK AND MORTY", flat=False, proc=True,
                           roots=(), free=3_500_000_000),
    "alice_cooper": dict(sp.PROC["alice_cooper"], name="ALICE COOPER'S NIGHTMARE CASTLE", flat=False,
                         proc=True, roots=(), free=14_000_000_000),
}
for _t in TITLES.values():
    _t.setdefault("program", "uptest/main.x86_64")
    _t.setdefault("proc", False)
#: the multi-boot's own folder in a build's paths: inside uptest on the Linux titles, beside
#: the game on the P-ROC ones
def pad_of(title):
    return (sp.PAD_DIR if title["proc"] else "uptest/" + PAD) + "/"


AES_FMTS = ("rm_pkg", "ac_pkg")
#: the launcher and the menu are ours; a build's own file by these names would be shadowed
RESERVED = ("uptest/main.x86_64",)
#: where an update's member list is kept when no --cache-dir is given (SpkUpdate.index):
#: a few hundred KB per update, never the update itself.  /var/tmp, not /tmp: WSL empties
#: /tmp whenever the distro restarts, and the tab's next plan read every update again
#: (the preview's picture waits behind the plan: they share one worker)
INDEX_CACHE = os.environ.get("SPK_MULTI_INDEX") or (
    "/var/tmp/pad_spkmulti" if os.path.isdir("/var/tmp")
    else os.path.join(tempfile.gettempdir(), "pad_spkmulti"))


def _gb(n):
    return "%.2f GB" % (n / 1e9) if n is not None else "?"


def split_list(s):
    return bof.split_list(s)


def _spooky():
    """the Spooky plugin's format and GPG helpers (imported late: plan --help needs none)"""
    from pinball_decryptor.plugins.spooky import formats, gpg, games
    return formats, gpg, games


# ============================================================================== the images
class SpkUpdate:
    """One Spooky update file: its title, how it is packed, and - read once and cached - every
    member as a build path (uptest/..., assets/...) with its size and sha1."""

    def __init__(self, path, cache_dir=None):
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise Refused("%s does not exist" % self.path)
        formats, _gpg, _games = _spooky()
        gf = formats.detect_game(self.path)
        if gf is None or gf.game_key not in TITLES:
            what = gf.game_name if gf is not None and gf.game_key else "not a Spooky update the menu takes"
            raise Refused("%s: %s (a multi-boot takes Beetlejuice, Scooby-Doo, Texas Chainsaw, Evil Dead, "
                          "Looney Tunes, Halloween, Ultraman, Rick and Morty and Alice Cooper updates)"
                          % (os.path.basename(self.path), what))
        self.key = gf.game_key
        self.game = gf.game_name
        self.fmt = gf.format_type
        self.title = TITLES[self.key]
        self.cache_dir = cache_dir
        self._tar = None
        self.size = os.path.getsize(self.path)
        self._index = None

    # -- the plain tar under the packing
    def tar_path(self, work):
        """the update as a tar(.gz) tarfile can read: itself, or its GPG layer taken off into
        the cache (kept by name, size and time - the next run reads it again for nothing)"""
        if self.fmt in ("tar_gz", "plain_tar"):
            return self.path
        if self._tar and os.path.isfile(self._tar):
            return self._tar
        _f, gpg, games = _spooky()
        base = self.cache_dir or work
        os.makedirs(base, exist_ok=True)
        st = os.stat(self.path)
        out = os.path.join(base, "%s.%d.%d.%s" % (re.sub(r"[^\w.-]", "_", os.path.basename(self.path)),
                                                  st.st_size, int(st.st_mtime),
                                                  "zip" if self.fmt in AES_FMTS else "tar.gz"))
        if not os.path.isfile(out) and self.fmt in AES_FMTS:
            say("unpacking %s's encryption layer" % os.path.basename(self.path))
            try:
                sp.aes_decrypt(self.path, out + ".part", self.fmt)
            except sp.Refused as e:
                raise Refused(str(e))
            os.replace(out + ".part", out)
        if not os.path.isfile(out):
            part = out + ".part"
            say("unpacking %s's %s layer" % (os.path.basename(self.path),
                                             "signature" if self.fmt == "gpg_tar_gz" else "encryption"))
            if self.fmt == "gpg_tar_gz":
                gpg.strip_gpg_signature(self.path, part)
            elif self.fmt in games.GPG_PASSPHRASES:
                gpg.decrypt_gpg_symmetric(self.path, part, games.GPG_PASSPHRASES[self.fmt])
            else:
                raise Refused("%s: packed as %s, which a multi-boot cannot take" % (
                    os.path.basename(self.path), self.fmt))
            os.replace(part, out)
        self._tar = out
        return out

    def build_path(self, name):
        """an archive member's name -> where it sits in a build (uptest/... on a flat title)"""
        name = name.replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        name = name.strip("/")
        if not name or name.startswith("/") or ".." in name.split("/"):
            return None
        return ("uptest/" + name) if self.title["flat"] else name

    def members(self, work):
        """(TarInfo, build path) for every member, in archive order, as a stream.  A GPG-
        packed update is read straight off `gpg --decrypt` when there is a gpg (and its
        layer is not unpacked already): writing a 2 GB Beetlejuice tar out first and reading
        it back doubled the first plan of the tab, which the preview waits behind."""
        if self.fmt in AES_FMTS:
            for r, ti, name in sp.zip_members(self.tar_path(work)):
                bp = self.build_path(name)
                if bp is not None:
                    yield r, ti, bp
            return
        proc = self._gpg_stream()
        try:
            src = {"fileobj": proc.stdout} if proc else {"name": self.tar_path(work)}
            with tarfile.open(mode="r|*", **src) as tf:
                for ti in tf:
                    bp = self.build_path(ti.name)
                    if bp is None:
                        continue
                    yield tf, ti, bp
        finally:
            if proc:
                proc.stdout.close()
                proc.kill()
                proc.wait()
                shutil.rmtree(proc.pad_home, ignore_errors=True)

    def _gpg_stream(self):
        """`gpg --decrypt` of this update on a pipe, or None (not GPG-packed, already
        unpacked into the cache, or no gpg here)"""
        if self.fmt in ("tar_gz", "plain_tar") + AES_FMTS or (self._tar and os.path.isfile(self._tar)):
            return None
        _f, gpg, games = _spooky()
        exe = gpg._find_gpg()
        if not exe or (self.fmt != "gpg_tar_gz" and self.fmt not in games.GPG_PASSPHRASES):
            return None
        import subprocess
        home = tempfile.mkdtemp(prefix="spkgpg.")
        cmd = [exe, "--homedir", home, "--batch", "--yes", "--no-default-keyring"]
        if self.fmt != "gpg_tar_gz":
            cmd += ["--passphrase", games.GPG_PASSPHRASES[self.fmt]]
        cmd += ["--decrypt", self.path]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.pad_home = home
        return proc

    def index(self, work):
        """{build path: (kind, size, sha1 or link target, mode)} - every member, hashed once and
        kept: in --cache-dir, else in INDEX_CACHE.  The tab plans again on every change of the
        list, and reading a 2 GB signed update through gpg takes a minute or two; its list,
        kept by path, size and time, makes every plan after the first instant."""
        if self._index is not None:
            return self._index
        st = os.stat(self.path)
        cache = None
        cdir = self.cache_dir or INDEX_CACHE
        try:
            os.makedirs(cdir, exist_ok=True)
        except OSError:
            cdir = None
        if cdir:
            tag = hashlib.sha1(self.path.encode("utf-8", "replace")).hexdigest()[:10]
            cache = os.path.join(cdir, "%s.%s.%d.%d.index.json" % (
                re.sub(r"[^\w.-]", "_", os.path.basename(self.path)), tag, st.st_size, int(st.st_mtime)))
            if os.path.isfile(cache):
                try:
                    with open(cache, encoding="utf-8") as f:
                        self._index = {k: tuple(v) for k, v in json.load(f).items()}
                    return self._index
                except (OSError, ValueError):
                    pass
        idx = collections.OrderedDict()
        say("reading %s" % os.path.basename(self.path))
        for tf, ti, bp in self.members(work):
            if ti.isdir():
                idx[bp] = ("d", 0, "", ti.mode)
            elif ti.issym() or ti.islnk():
                idx[bp] = ("l", 0, ti.linkname, ti.mode)
            elif ti.isfile():
                h = hashlib.sha1()
                f = tf.extractfile(ti)
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
                    PROGRESS.add(len(b))
                idx[bp] = ("f", ti.size, h.hexdigest(), ti.mode)
        if cache:
            try:
                with open(cache + ".part", "w", encoding="utf-8") as f:
                    json.dump(idx, f)
                os.replace(cache + ".part", cache)
            except OSError:
                pass
        self._index = idx
        return idx

    def unpacked(self, work):
        return sum(v[1] for v in self.index(work).values())


def _inputs(a, work):
    if not a.extra:
        raise Refused("a multi-boot needs at least two images: --primary (the stock build) and one --extra")
    if 1 + len(a.extra) > MAX_IMAGES:
        raise Refused("at most %d images in one Spooky multi-boot" % MAX_IMAGES)
    cache = getattr(a, "cache_dir", None)
    us = [SpkUpdate(a.primary, cache)] + [SpkUpdate(e, cache) for e in a.extra]
    for i, u in enumerate(us[1:], 1):
        if u.key != us[0].key:
            raise Refused("image %d (%s) is %s, the primary is %s: every build on one machine must be the "
                          "same game" % (i, os.path.basename(u.path), u.game, us[0].game))
    for u in us:
        idx = u.index(work)
        prog = u.title["program"]
        if prog not in idx or idx[prog][0] != "f":
            raise Refused("%s has no game program (%s): the machine's install would refuse it"
                          % (os.path.basename(u.path), "main.x86_64" if u.title["flat"] else prog))
        if pad_of(u.title) + "images.conf" in idx or sp.MARK in idx:
            raise Refused("%s is a multi-boot already: add the builds it was made from instead"
                          % os.path.basename(u.path))
    return us


def diff(base, other):
    """build paths of *other* that differ from *base* (new or changed), and those it lacks"""
    changed = [p for p, v in other.items() if base.get(p) != v and not (v[0] == "d" and p in base)]
    removed = [p for p in base if p not in other]
    # a folder the build lacks takes everything under it: list the folder only
    top = [p for p in removed if not any(p.startswith(q + "/") for q in removed if base[q][0] == "d")]
    return changed, top


def targets_of(us):
    return ["b%d" % k for k in range(len(us))]


# ============================================================================== plan
def make_plan(a, work):
    us = _inputs(a, work)
    base = us[0].index(work)
    builds = []
    for u in us[1:]:
        ch, rm = diff(base, u.index(work))
        idx = u.index(work)
        builds.append({"changed": ch, "removed": rm, "bytes": sum(idx[p][1] for p in ch)})
    media = mkc.plan_media(a.media_dir, len(us)) if getattr(a, "media_dir", None) else None
    menu = 3_500_000 + (media["total"] if media else 0)
    b0 = us[0].unpacked(work)
    # compressed: b0 as the primary file is; the builds' files at the primary's own ratio
    ratio = us[0].size / max(b0, 1)
    total = us[0].size + int(sum(b["bytes"] for b in builds) * ratio) + menu
    unpacked = b0 + sum(b["bytes"] for b in builds) + menu
    return {"us": us, "builds": builds, "media": media, "menu": menu, "total": total, "unpacked": unpacked}


def print_plan(plan):
    us = plan["us"]
    t = us[0].title
    print("== layout: one %s update under the primary's name (%s); the machine's own install puts it in "
          "/game/code/uptest, its desktop starts the launcher; image 0 = the primary, carried whole; every "
          "other image = its own files over it, made on the machine the first time the menu starts"
          % (us[0].game, os.path.basename(us[0].path)))
    print("== game code versions")
    for i, u in enumerate(us):
        kind = "whole (the stock build)" if i == 0 else "%d changed, %d removed" % (
            len(plan["builds"][i - 1]["changed"]), len(plan["builds"][i - 1]["removed"]))
        print("  %d  b%d  %s  (%s)" % (i, i, os.path.basename(u.path), kind))
    print("== bytes in the update")
    print("image-size 0 b0 %d %s, whole" % (us[0].size, os.path.basename(us[0].path)))
    for i, b in enumerate(plan["builds"], 1):
        print("image-size %d b%d %d %s's own files (%s unpacked)"
              % (i, i, int(b["bytes"] * us[0].size / max(us[0].unpacked(None), 1)),
                 os.path.basename(us[i].path), _gb(b["bytes"])))
    print("image-size overhead %d the menu, its pictures and the launcher" % plan["menu"])
    print("upd-size %d estimated multi-boot update" % plan["total"])
    # on the machine: the file in /game/tmp, it unpacked, the old build backed up, the new copy
    need = plan["total"] + 2 * plan["unpacked"] + us[0].unpacked(None)
    print("machine-free %d while it installs (the file, it unpacked and copied in, the old build backed up)" % need)
    if t["free"]:
        print("machine: a factory %s has %s free on /game: %s" % (
            us[0].game, _gb(t["free"]), "fits" if need < t["free"] else "TOO BIG - fewer builds"))
    ok32 = plan["total"] + FAT32_MARGIN <= FAT32_MAX
    print("fat32: %s (one file on a FAT32 stick holds at most %s; an exFAT or NTFS stick has no limit)"
          % ("fits" if ok32 else "TOO BIG", _gb(FAT32_MAX)))
    best = None
    for k, cap in USB_SIZES.items():
        ok = plan["total"] <= cap
        print("fits USB %s stick size %d: %s (spare %d)" % (k, cap, "YES" if ok else "NO", cap - plan["total"]))
        if ok and best is None:
            best = k
    print("stick: %s" % (best or "none of %s is big enough" % ", ".join(USB_SIZES)))


# ============================================================================== the conf
def render_conf(targets, titles, subtitles, default, timeout, rows, sound_move, sound_confirm, volume, **kw):
    return bof.render_conf(targets, titles, subtitles, default, timeout, rows, sound_move, sound_confirm,
                           volume, SWITCHES, header=CONF_HEADER, font=False, **kw)


def parse_conf(text):
    return bof.parse_conf(text)


def default_titles(us):
    name = us[0].title["name"]
    out = [(name, "Stock %s" % _stem(us[0].path))]
    for u in us[1:]:
        out.append((name, _stem(u.path)))
    return out


def _stem(path):
    b = os.path.basename(path)
    return re.sub(r"\.(beetlejuice|scooby|looney|ed|pkg)$", "", b, flags=re.I)


def conf_from_args(a, targets, media, titles_default, subtitles_default):
    if getattr(a, "conf", None):
        with open(a.conf, encoding="utf-8") as f:
            text = f.read()
        if [p for p, _t, _s in parse_conf(text)["images"]] != list(targets):
            raise Refused("--conf %s does not list %r" % (a.conf, list(targets)))
        return text
    titles = split_list(a.titles) or list(titles_default)
    subtitles = split_list(a.subtitles) if a.subtitles is not None else list(subtitles_default)
    rows, move, confirm, volume = ([], None, None, None)
    if media:
        rows, move, confirm, volume = media["rows"], media["sound_move"], media["sound_confirm"], media["volume"]
    if a.volume is not None:
        volume = a.volume
    footer = None if a.footer_own else a.footer
    return render_conf(targets, titles, subtitles, a.default or 0, 15 if a.timeout is None else a.timeout,
                       rows, move, confirm, volume, theme=a.theme, colors=mkc.parse_color_flags(a.color),
                       heading=a.heading, text_size=a.text_size, counter=a.counter,
                       countdown_word=a.countdown_word, footer=footer, learn=bool(getattr(a, "learn", False)),
                       default_card=getattr(a, "default_card", None))


def spk_conf(title):
    l, r, s = title["sw"]
    lines = ["# spk.conf - the machine, for the launcher; written by mkspkmulti.py",
             "board=%s" % title["board"], "L=%d" % l, "R=%d" % r, "S=%d" % s]
    lines += ["root=%s %s" % kv for kv in title["roots"]]
    return "\n".join(lines) + "\n"


def builds_text(n):
    out = ["# builds.txt - b<k> <its files under pad/> (laid over b0; <files>.removed = what it lacks); "
           "written by mkspkmulti.py"]
    out += ["b%d d%d" % (k, k) for k in range(1, n)]
    return "\n".join(out) + "\n"


# ============================================================================== the archive
def check_selector_dir(d, title=None):
    if not d or not os.path.isdir(d):
        raise Refused("--selector-dir %s is not a directory (ensurespkselect.sh installs one)" % d)
    need = [n for n, (_m, req) in SELECTOR_FILES.items() if req]
    if title is not None and title["proc"]:
        need = [n for n, _m in sp.SELECTOR_FILES if n != "font.ttf"]
    for name in need:
        if not os.path.isfile(os.path.join(d, name)):
            raise Refused("--selector-dir %s has no %s (ensurespkselect.sh installs it)" % (d, name))


def _font_src(selector_dir):
    src = os.path.join(selector_dir, "font.ttf") if selector_dir else ""
    if src and os.path.isfile(src):
        return src
    if os.path.isfile(HOST_FONT):
        return HOST_FONT
    raise Refused("no font.ttf in %s and no %s on this Linux: the menu would have nothing to draw its "
                  "words with (apt install fonts-dejavu-core)" % (selector_dir, HOST_FONT))


class _Out:
    """the output tar: names relative to the archive root, the prefix a nested title needs"""

    def __init__(self, tf, flat):
        self.tf = tf
        self.pre = "" if flat else "uptest/"
        self.when = time.time()
        self.dirs = set()

    def _dir(self, name):
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d not in self.dirs:
                self.dirs.add(d)
                ti = tarfile.TarInfo(d)
                ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, self.when
                self.tf.addfile(ti)

    def data(self, rel, data, mode=0o644):
        name = self.pre + rel
        self._dir(name)
        ti = tarfile.TarInfo(name)
        ti.size, ti.mode, ti.mtime = len(data), mode, self.when
        self.tf.addfile(ti, io.BytesIO(data))

    def file(self, rel, src, mode=0o644):
        name = self.pre + rel
        self._dir(name)
        ti = self.tf.gettarinfo(src, arcname=name)
        ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = mode, 0, 0, "", ""
        with open(src, "rb") as f:
            self.tf.addfile(ti, f)

    def member(self, rel, ti, f=None, linkname=None):
        """an input member under a new name, its kind, mode and time kept (a hard link's
        target given as its new archive name)"""
        name = self.pre + rel
        self._dir(name)
        n = tarfile.TarInfo(name)
        n.type, n.mode, n.mtime = ti.type, ti.mode, ti.mtime
        n.linkname = linkname if linkname is not None else ti.linkname
        n.size = ti.size if ti.isfile() else 0
        if ti.isdir():
            self.dirs.add(name)
        self.tf.addfile(n, f)


def _write_menu(out, a, conf, title, n, manifest, media, media_dir, removed):
    out.data("main.x86_64", open(os.path.join(a.selector_dir, "padselect.sh"), "rb").read(), 0o755)
    pad = PAD + "/"
    for name, (mode, _req) in SELECTOR_FILES.items():
        if name == "padselect.sh":
            continue
        src = _font_src(a.selector_dir) if name == "font.ttf" else os.path.join(a.selector_dir, name)
        out.file(pad + name, src, mode)
    out.data(pad + "images.conf", conf.encode("utf-8"))
    out.data(pad + "builds.txt", builds_text(n).encode("utf-8"))
    out.data(pad + "spk.conf", spk_conf(title).encode("utf-8"))
    out.data(pad + mkc.BUILD_MANIFEST, (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    for k, rm in removed.items():
        out.data(pad + "d%d.removed" % k, ("".join(p + "\n" for p in rm)).encode("utf-8"))
    if media:
        for name, src in sorted(media["files"].items()):
            out.file(pad + "media/" + name, src)
        out.file(pad + mkc.MEDIA_MANIFEST, os.path.join(media_dir, mkc.MEDIA_MANIFEST))


def _pack(us0, tar_tmp, out_path):
    """the plain tar(.gz) written -> the update, packed as the primary was"""
    _f, gpg, games = _spooky()
    if us0.fmt in ("tar_gz", "plain_tar"):
        os.replace(tar_tmp, out_path)
    elif us0.fmt == "gpg_tar_gz":
        say("signing it as a Beetlejuice update (the machine installs it in developer mode)")
        gpg.sign_beetlejuice(tar_tmp, out_path)
    elif us0.fmt in games.GPG_PASSPHRASES:
        say("encrypting it with %s's passphrase" % us0.game)
        gpg.encrypt_gpg_symmetric(tar_tmp, out_path, games.GPG_PASSPHRASES[us0.fmt])
    else:
        raise Refused("cannot pack a %s update" % us0.fmt)


def build_update(a):
    work = tempfile.mkdtemp(prefix="spkmulti.", dir=a.workdir or None)
    try:
        us = _inputs(a, work)
        out = os.path.abspath(a.out)
        want = os.path.basename(us[0].path)
        if os.path.isdir(out):
            out = os.path.join(out, want)
        if os.path.basename(out) != want:
            raise Refused("--out %s: the machine's update menu lists the title's own names, so the "
                          "multi-boot keeps the primary's (%s) - in another folder" % (os.path.basename(out), want))
        out = os.path.abspath(check_output_path(out, [u.path for u in us], force=a.force))
        check_selector_dir(a.selector_dir, us[0].title)
        media = mkc.plan_media(a.media_dir, len(us)) if a.media_dir else None
        targets = targets_of(us)
        tdef = default_titles(us)
        conf = conf_from_args(a, targets, media, [t for t, _s in tdef], [s for _t, s in tdef])
        base = us[0].index(work)
        changes, removed = {}, {}
        for k, u in enumerate(us[1:], 1):
            ch, rm = diff(base, u.index(work))
            changes[k] = set(ch)
            removed[k] = rm
        manifest = collections.OrderedDict([
            ("tool", TOOL), ("version", VERSION), ("written", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ("title", us[0].key), ("game", us[0].game), ("format", us[0].fmt),
            ("images", [collections.OrderedDict([
                ("index", i), ("build", t), ("source", u.path), ("name", os.path.basename(u.path)),
                ("size", u.size), ("files", None if i == 0 else len(changes[i])),
                ("removed", None if i == 0 else len(removed[i]))])
                for i, (u, t) in enumerate(zip(us, targets))])])
        if us[0].title["proc"]:
            _build_proc(a, us, work, out, conf, manifest, media, changes, removed)
            return 0
        gz = us[0].fmt != "plain_tar"
        tar_tmp = os.path.join(work, "multi.tar" + (".gz" if gz else ""))
        total = us[0].unpacked(work) + sum(sum(u.index(work)[p][1] for p in changes[k])
                                           for k, u in enumerate(us[1:], 1))
        PROGRESS.start(max(total, 1), "update")
        with tarfile.open(tar_tmp, "w:gz" if gz else "w", compresslevel=6) if gz else \
                tarfile.open(tar_tmp, "w") as tf:
            o = _Out(tf, us[0].title["flat"])
            # the menu first: inspect reads it without the rest
            _write_menu(o, a, conf, us[0].title, len(us), manifest, media, a.media_dir, removed)
            for k, u in enumerate(us):
                PROGRESS.step("build %d (%s)" % (k, os.path.basename(u.path)), 0)
                n = 0
                for tf_in, ti, bp in u.members(work):
                    if k and bp not in changes[k]:
                        continue
                    tree = "%s/%s%d/" % (PAD, "b" if k == 0 else "d", k)
                    dest = tree + bp
                    if ti.islnk():
                        # a hard link names another member of the same input: as it now sits
                        # (a build's link whose target did not change is a whole copy instead)
                        tgt = u.build_path(ti.linkname)
                        if k and tgt not in changes[k]:
                            raise Refused("%s: %s is a hard link to an unchanged file; this builder "
                                          "cannot carry it" % (os.path.basename(u.path), bp))
                        o.member(dest, ti, linkname=o.pre + tree + tgt)
                    elif ti.isfile():
                        f = tf_in.extractfile(ti)
                        o.member(dest, ti, _Meter(f))
                    else:
                        o.member(dest, ti)
                    n += 1
                say("image %d: %s, %d %s -> b%d" % (
                    k, os.path.basename(u.path), n, "members (whole)" if k == 0 else "changed members", k))
        PROGRESS.finish()
        part = out + ".part"
        try:
            _pack(us[0], tar_tmp, part)
            os.replace(part, out)
        finally:
            if os.path.exists(part):
                os.unlink(part)
        say("wrote %s (%s)" % (out, _gb(os.path.getsize(out))))
        if os.path.getsize(out) > FAT32_MAX:
            say("warning: %s is bigger than a FAT32 stick holds in one file (%s): use an exFAT or NTFS "
                "stick" % (out, _gb(FAT32_MAX)))
        say("on the machine: install it the way every %s update is installed; the menu shows from the "
            "next power-up" % us[0].game)
        return 0
    finally:
        if not getattr(a, "keep_work", False):
            shutil.rmtree(work, ignore_errors=True)


def _build_proc(a, us, work, out, conf, manifest, media, changes, removed, stock=None):
    """The P-ROC package (mkspkproc.py): the stock build at the root as it came, the menu,
    the launcher and the other builds' files in PAD_MULTIBOOT/, the marker and the hook;
    zipped and encrypted with the title's key.  *stock* (inject): the hook files read off
    the multi-boot being rewritten instead of the stock package."""
    t = us[0].title
    manifest.setdefault("stamp", time.strftime("%Y%m%d%H%M%S"))
    if stock is None:
        stock = sp.read_all(us[0], work, {"run-on-update.sh", "xinitrc"})
    zip_tmp = os.path.join(work, "multi.zip")
    total = us[0].unpacked(work) + sum(sum(u.index(work)[p][1] for p in changes.get(k, ()))
                                       for k, u in enumerate(us[1:], 1))
    PROGRESS.start(max(total, 1), "update")
    with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as zf:
        o = sp.ZipOut(zf)
        try:
            sp.write_menu(o, a.selector_dir, _font_src(a.selector_dir), conf, t, builds_text(len(us)),
                          manifest, media, a.media_dir, removed, mkc.BUILD_MANIFEST, mkc.MEDIA_MANIFEST,
                          stock.get("run-on-update.sh"), stock.get("xinitrc"))
        except sp.Refused as e:
            raise Refused(str(e))
        for k, u in enumerate(us):
            PROGRESS.step("build %d (%s)" % (k, os.path.basename(u.path)), 0)
            n = 0
            for r, ti, bp in u.members(work):
                if k == 0:
                    dest = sp.rename_b0(t, bp)
                    if dest is None:
                        continue
                elif bp not in changes[k]:
                    continue
                else:
                    dest = "%s/d%d/%s" % (sp.PAD_DIR, k, bp)
                if ti.isfile():
                    o.member(dest, ti, _Meter(r.extractfile(ti)))
                else:
                    o.member(dest, ti)
                n += 1
            say("image %d: %s, %d %s -> b%d" % (
                k, os.path.basename(u.path), n, "members (whole, in the game's folder)" if k == 0
                else "changed members", k))
    PROGRESS.finish()
    part = out + ".part"
    try:
        say("encrypting it with %s's key" % us[0].game)
        sp.aes_encrypt(zip_tmp, part, us[0].fmt)
        os.replace(part, out)
    finally:
        if os.path.exists(part):
            os.unlink(part)
    say("wrote %s (%s)" % (out, _gb(os.path.getsize(out))))
    say("on the machine: install it the way every %s update is installed (the USB stick); the menu "
        "shows from the next power-up" % us[0].game)


class _Meter:
    """a member's stream that moves the progress bar as it is read"""

    def __init__(self, f):
        self.f = f

    def read(self, n=-1):
        b = self.f.read(n)
        if b:
            PROGRESS.add(len(b))
        return b


# ============================================================================== read back
def _open_out(path, work):
    """(SpkUpdate, tar path) of a multi-boot update"""
    u = SpkUpdate(path)
    return u, u.tar_path(work)


def _menu_of(path, work):
    """the menu files (pad/ minus the builds), the launcher, the builds' member counts"""
    u, tp = _open_out(path, work)
    if u.title["proc"]:
        return _menu_of_proc(u, path, work)
    pre = ("" if u.title["flat"] else "uptest/") + PAD + "/"
    got, builds, start = {}, collections.Counter(), b""
    launcher = ("" if u.title["flat"] else "uptest/") + "main.x86_64"
    with tarfile.open(tp, "r|*") as tf:
        for ti in tf:
            name = ti.name.lstrip("./") if ti.name.startswith("./") else ti.name
            if name == launcher and ti.isfile():
                start = tf.extractfile(ti).read()
                continue
            if not name.startswith(pre):
                continue
            rel = name[len(pre):]
            m = re.match(r"^([bd]\d+)/", rel)
            if m:
                if not ti.isdir():
                    builds[m.group(1)] += 1
                continue
            if ti.isfile():
                got[rel] = tf.extractfile(ti).read()
    if "images.conf" not in got:
        raise Refused("%s carries no boot menu (no %simages.conf): it is not a multi-boot"
                      % (os.path.basename(path), pre))
    return u, got, start, builds


def _menu_of_proc(u, path, work):
    pre = sp.PAD_DIR + "/"
    got, builds, start = {}, collections.Counter(), b""
    for r, ti, bp in u.members(work):
        if not bp.startswith(pre):
            continue
        rel = bp[len(pre):]
        m = re.match(r"^(d\d+)/", rel)
        if m:
            if not ti.isdir():
                builds[m.group(1)] += 1
            continue
        if ti.isfile():
            got[rel] = r.extractfile(ti).read()
    start = got.get("padselect.sh", b"")
    if "images.conf" not in got:
        raise Refused("%s carries no boot menu (no %simages.conf): it is not a multi-boot"
                      % (os.path.basename(path), pre))
    return u, got, start, builds


def inspect_update(path, media_out=None):
    work = tempfile.mkdtemp(prefix="spkinspect.")
    try:
        u, got, start, builds = _menu_of(path, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    conf = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
    try:
        build = json.loads(got.get(mkc.BUILD_MANIFEST, b"{}").decode("utf-8"))
    except ValueError:
        build = {}
    try:
        media_man = json.loads(got[mkc.MEDIA_MANIFEST].decode("utf-8")) if mkc.MEDIA_MANIFEST in got else None
    except ValueError:
        media_man = None
    bimgs = {b.get("index"): b for b in build.get("images", [])}
    warnings, images = [], []
    for i, ((dev, t, s), (art, anim, music, confirm)) in enumerate(zip(conf["images"], conf["media"])):
        b = bimgs.get(i, {})
        m = {}
        if isinstance(media_man, dict) and isinstance(media_man.get("images"), list) \
                and i < len(media_man["images"]) and isinstance(media_man["images"][i], dict):
            m = media_man["images"][i]
        src = b.get("source")
        if src and not os.path.isfile(src):
            warnings.append("image %d: its source %s is not on this machine" % (i, src))

        def _src(k):
            return m.get(k) if m.get(k) not in (None, "none") else None
        images.append(collections.OrderedDict([
            ("index", i), ("device", dev), ("title", t), ("subtitle", s),
            ("art", art or None), ("anim", anim or None), ("music", music or None), ("confirm", confirm or None),
            ("art_source", _src("art_source")), ("anim_source", _src("anim_source")),
            ("music_source", _src("music_source")), ("confirm_source", _src("confirm_source")),
            ("source", src), ("source_exists", bool(src) and os.path.isfile(src)),
            ("name", os.path.basename(src) if src else None), ("version", None), ("game_version", None),
            ("size", b.get("size")), ("md5", None), ("delta", None)]))
    media_files = sorted(n.split("/", 1)[1] for n in got if n.startswith("media/"))
    rep = collections.OrderedDict([
        ("zip", os.path.abspath(path)), ("fun", os.path.abspath(path)), ("size", os.path.getsize(path)),
        ("title", u.key), ("game", u.game),
        ("tool", build.get("tool")), ("tool_version", build.get("version")), ("written", build.get("written")),
        ("hook", b"multi-boot launcher" in start), ("install_step", b"multi-boot launcher" in start),
        ("builds", dict(builds)), ("images", images), ("groups", []), ("default_card", conf.get("default_card")),
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
                f.write(got["media/" + n])
        if media_man is not None:
            with open(os.path.join(media_out, mkc.MEDIA_MANIFEST), "wb") as f:
                f.write(got[mkc.MEDIA_MANIFEST])
        rep["media_out"] = os.path.abspath(media_out)
    return rep


def print_inspect(rep):
    print("== %s (%s, %s multi-boot)" % (rep["zip"], _gb(rep["size"]), rep["game"]))
    print("written by %s %s at %s; launcher: %s" % (rep["tool"] or "?", rep["tool_version"] or "?",
                                                   rep["written"] or "?", "yes" if rep["hook"] else "NO"))
    for im in rep["images"]:
        print("image %d %s '%s' '%s' art=%s source=%s"
              % (im["index"], im["device"], im["title"], im["subtitle"], im["art"], im["source"]))
    print("timeout=%s default=%s theme=%s" % (rep["timeout"], rep["default"], rep["theme"]))
    for w in rep["warnings"]:
        print("warning: " + w)


class _Done(Exception):
    pass


def _verify_proc(u, got, start, work):
    """a P-ROC package's own checks (verify_update does the cards)"""
    bad = []
    t = u.title
    if not start.startswith(b"#!") or b"multi-boot launcher" not in start:
        bad.append("PAD_MULTIBOOT/padselect.sh is not the launcher")
    for name in ("spkselect", "dpprocsw", "proc.conf"):
        if name not in got:
            bad.append("PAD_MULTIBOOT/%s is missing" % name)
    idx = u.index(work)
    if t["program"] not in idx:
        bad.append("no %s: the stock build is not in the package" % t["program"])
    if sp.MARK not in idx:
        bad.append("no %s: the launcher would take the folder for a normal update" % sp.MARK)
    hooks = sp.read_all(u, work, {"run-on-update.sh", "uptest/main.x86_64"})
    if t["hook"] == "rm" and b"PAD multi-boot" not in hooks.get("run-on-update.sh", b""):
        bad.append("run-on-update.sh is not the multi-boot's install step")
    if t["hook"] == "ac":
        if b"PAD multi-boot" not in hooks.get("uptest/main.x86_64", b""):
            bad.append("uptest/main.x86_64 is not the multi-boot's install step")
        if "uptest/main.x86_64.real" not in idx:
            bad.append("the real Unity player (uptest/main.x86_64.real) is missing")
        x = got.get("xinitrc", b"")
        if b"padselect.sh" not in x or b"uptest" not in x or b"delete" not in x:
            bad.append("PAD_MULTIBOOT/xinitrc does not start the menu, or lost the words the game checks for")
    return bad


def verify_update(a):
    """The update read back (every member, so a damaged gzip shows): the launcher, the menu
    programs, b0's game program, and every card naming b0 or a build the update carries."""
    path = os.path.abspath(a.zip)
    work = tempfile.mkdtemp(prefix="spkverify.", dir=getattr(a, "workdir", None) or None)
    bad = []
    try:
        u, got, start, builds = _menu_of(path, work)
        if u.title["proc"]:
            bad += _verify_proc(u, got, start, work)
            conf = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
            raise _Done()
        if not start.startswith(b"#!") or b"multi-boot launcher" not in start:
            bad.append("main.x86_64 is not the launcher")
        for name, (_mode, required) in SELECTOR_FILES.items():
            if required and name != "padselect.sh" and name not in got:
                bad.append("pad/%s is missing" % name)
        if "spk.conf" not in got:
            bad.append("pad/spk.conf is missing")
        idx = u.index(work)
        if "uptest/main.x86_64" not in idx:
            bad.append("no %s: the machine's install refuses it" % ("main.x86_64" if u.title["flat"]
                                                                    else "uptest/main.x86_64"))
        if "uptest/pad/b0/uptest/main.x86_64" not in idx:
            bad.append("b0 has no game program")
        conf = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
        lines = [ln.split() for ln in got.get("builds.txt", b"").decode("utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        made = {ln[0]: ln[1] for ln in lines if len(ln) >= 2}
        for i, (dev, _t, _s) in enumerate(conf["images"]):
            if dev == "b0":
                continue
            if dev not in made:
                bad.append("image %d (%s) is no build in builds.txt" % (i, dev))
            elif not builds.get(made[dev]) and ("%s.removed" % made[dev]) not in got:
                bad.append("image %d (%s): pad/%s/ carries nothing" % (i, dev, made[dev]))
    except _Done:
        pass
    except Refused as e:
        bad.append(str(e))
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as e:
        bad.append("the update does not read back: %s" % e)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for b in bad:
        say("verify: FAIL %s" % b)
    if bad:
        return 1
    say("verify: OK %s - %d cards, b0 + %d builds, the launcher and the menu" % (
        os.path.basename(path), len(conf["images"]), len([b for b in builds if b.startswith("d")])))
    return 0


def inject_update(a):
    """A new menu for an existing multi-boot update, written over it: every build member copied
    across as it is, the menu files rewritten from the flags (falling back to its own values)."""
    path = os.path.abspath(check_output_path(a.zip, [], must_exist=True))
    work = tempfile.mkdtemp(prefix="spkinject.", dir=os.path.dirname(path))
    try:
        u, got, start, _builds = _menu_of(path, work)
        old = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
        proc = u.title["proc"]
        targets = [p for p, _t, _s in old["images"]]
        media_dir = a.media_dir
        if media_dir is None and mkc.MEDIA_MANIFEST in got:
            media_dir = os.path.join(work, "media_carried")
            os.makedirs(media_dir)
            for n, data in got.items():
                if n.startswith("media/") or n == mkc.MEDIA_MANIFEST:
                    with open(os.path.join(media_dir, n.split("/", 1)[-1]), "wb") as f:
                        f.write(data)
        media = mkc.plan_media(media_dir, len(targets)) if media_dir else None
        for k in ("timeout", "default", "volume", "heading", "text_size", "counter", "countdown_word", "theme"):
            if getattr(a, k, None) is None and old.get(k) is not None:
                setattr(a, k, old[k])
        if not a.footer_own and a.footer is None and old.get("footer") is not None:
            a.footer = old["footer"]
        if not a.color and old.get("colors"):
            a.color = ["%s=%s" % kv for kv in old["colors"].items()]
        if a.subtitles is None:
            a.subtitles = ";".join(s for _p, _t, s in old["images"])
        conf = conf_from_args(a, targets, media, [t for _p, t, _s in old["images"]],
                              [s for _p, _t, s in old["images"]])
        sel = a.selector_dir
        if sel:
            check_selector_dir(sel)
        else:
            sel = os.path.join(work, "sel")
            os.makedirs(sel)
            for name in list(SELECTOR_FILES) + [n for n, _m in sp.SELECTOR_FILES]:
                if name in got:
                    with open(os.path.join(sel, name), "wb") as f:
                        f.write(got[name])
            with open(os.path.join(sel, "padselect_proc.sh" if proc else "padselect.sh"), "wb") as f:
                f.write(start)
        if proc:
            _inject_proc(a, u, got, work, path, conf, media, media_dir, sel)
            return 0
        pre = ("" if u.title["flat"] else "uptest/") + PAD + "/"
        gz = u.fmt != "plain_tar"
        tar_tmp = os.path.join(work, "multi.tar" + (".gz" if gz else ""))
        PROGRESS.start(max(os.path.getsize(path), 1), "inject")
        with (tarfile.open(tar_tmp, "w:gz", compresslevel=6) if gz else tarfile.open(tar_tmp, "w")) as tf:
            o = _Out(tf, u.title["flat"])
            sa = argparse.Namespace(selector_dir=sel)
            man = json.loads(got.get(mkc.BUILD_MANIFEST, b"{}").decode("utf-8") or "{}",
                             object_pairs_hook=collections.OrderedDict)
            man["menu_written"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            removed = {}
            for n, data in got.items():
                m = re.match(r"^d(\d+)\.removed$", n)
                if m:
                    removed[int(m.group(1))] = [p for p in data.decode("utf-8").splitlines() if p]
            _write_menu(o, sa, conf, u.title, len(targets), man, media, media_dir, removed)
            o.dirs.add(pre.rstrip("/"))
            with tarfile.open(u.tar_path(work), "r|*") as tin:
                for ti in tin:
                    # the builds' members as they are; the menu's are written above
                    if not re.match(r"^%s[bd]\d+/" % re.escape(pre), ti.name):
                        continue
                    f = tin.extractfile(ti) if ti.isfile() else None
                    tf.addfile(ti, _Meter(f) if f else None)
        PROGRESS.finish()
        part = path + ".part"
        try:
            _pack(u, tar_tmp, part)
            os.replace(part, path)
        finally:
            if os.path.exists(part):
                os.unlink(part)
        say("the menu of %s is rewritten (%s)" % (path, _gb(os.path.getsize(path))))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _inject_proc(a, u, got, work, path, conf, media, media_dir, sel):
    """inject for a P-ROC package: every member but the menu's copied across, the menu, the
    marker (the same stamp: the builds on the machine stay) and the hook written again"""
    man = json.loads(got.get(mkc.BUILD_MANIFEST, b"{}").decode("utf-8") or "{}",
                     object_pairs_hook=collections.OrderedDict)
    man["menu_written"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    removed = {}
    for n, data in got.items():
        m = re.match(r"^d(\d+)\.removed$", n)
        if m:
            removed[int(m.group(1))] = [p for p in data.decode("utf-8").splitlines() if p]
    n_img = len(parse_conf(conf)["images"])
    stock = {"run-on-update.sh": got.get("run-on-update.stock.sh"),
             "xinitrc": sp.read_all(u, work, {"xinitrc"}).get("xinitrc")}
    ours = {sp.MARK, "run-on-update.sh"} | ({"uptest/main.x86_64"} if u.title["hook"] == "ac" else set())
    pre = sp.PAD_DIR + "/"
    zip_tmp = os.path.join(work, "multi.zip")
    PROGRESS.start(max(os.path.getsize(path), 1), "inject")
    with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as zf:
        o = sp.ZipOut(zf)
        try:
            sp.write_menu(o, sel, _font_src(sel), conf, u.title, builds_text(n_img), man, media, media_dir,
                          removed, mkc.BUILD_MANIFEST, mkc.MEDIA_MANIFEST, stock["run-on-update.sh"],
                          stock["xinitrc"])
        except sp.Refused as e:
            raise Refused(str(e))
        for r, ti, bp in u.members(work):
            if bp in ours or (bp.startswith(pre) and not re.match(r"^%sd\d+(/|$)" % re.escape(pre), bp)) \
                    or bp == sp.PAD_DIR:
                continue
            if ti.isfile():
                o.member(bp, ti, _Meter(r.extractfile(ti)))
            else:
                o.member(bp, ti)
    PROGRESS.finish()
    part = path + ".part"
    try:
        sp.aes_encrypt(zip_tmp, part, u.fmt)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.unlink(part)
    say("the menu of %s is rewritten (%s)" % (path, _gb(os.path.getsize(path))))


# ============================================================================== media
def cmd_media(a):
    """The menu's pictures and sounds through selectmedia.py, as the DP builder does.  'auto'
    art is no picture for now; sounds are the built-in click / chime."""
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
            spec = "none"
        argv += ["--art", "%d=%s" % (i, spec)]
    for i, spec in enumerate(anims):
        if spec.startswith("auto"):
            spec = "none"
        argv += ["--anim", "%d=%s" % (i, spec)]
    for m in a.music:
        argv += ["--music", m]
    argv += ["--sound-move", "synth" if a.sound_move == "auto" else a.sound_move]
    for s in (a.sound_confirm or ["synth"]):
        argv += ["--sound-confirm", re.sub(r"(^|=)auto$", r"\1synth", s)]
    volume = VOLUME_DEFAULT if a.volume is None else a.volume
    if not 0 <= volume <= 100:
        raise Refused("--volume %d: 0-100" % volume)
    argv += ["--volume", str(volume)]
    if a.size:
        argv += ["--size", a.size]
    if a.visual_only:
        argv += ["--visual-only"]
    if a.work:
        argv += ["--work", a.work]
    return selectmedia.main(argv)


# ============================================================================== main
def _add_conf_flags(s):
    s.add_argument("--selector-dir", help="a directory holding spkselect, spksw, padselect.sh and "
                                          "optionally font.ttf (ensurespkselect.sh installs one)")
    s.add_argument("--media-dir", help="directory holding media.json (mkspkmulti.py media) and the files it names")
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
    s.add_argument("--learn", action="store_true")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "build"):
        s = sub.add_parser(name)
        s.add_argument("--primary", required=True, help="the stock build's update file")
        s.add_argument("--extra", action="append", default=[], metavar="FILE", help="a build: an update file")
        s.add_argument("--cache-dir", help="where the unpacked GPG layers and the member lists are kept")
        s.add_argument("--workdir")
        if name == "plan":
            s.add_argument("--media-dir")
            s.add_argument("--out")
        else:
            s.add_argument("--out", required=True, help="where to write it: a folder, or a file named as the primary")
            _add_conf_flags(s)
            s.add_argument("--default-card", type=int)
            s.add_argument("--force", action="store_true")
            s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("inject")
    s.add_argument("--zip", "--fun", "--update", dest="zip", required=True)
    _add_conf_flags(s)
    s.add_argument("--default-card", type=int)
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--workdir")
    s.add_argument("--cache-dir")
    s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("verify")
    s.add_argument("--zip", "--fun", "--update", dest="zip", required=True)
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--quick", action="store_true")
    s.add_argument("--workdir")
    s = sub.add_parser("inspect")
    s.add_argument("--zip", "--fun", "--update", dest="zip", required=True)
    s.add_argument("--json", action="store_true", dest="as_json")
    s.add_argument("--media-out")
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
    s.add_argument("--cache-dir")
    a = ap.parse_args(list(sys.argv[1:]) if argv is None else list(argv))
    try:
        if a.cmd == "plan":
            work = tempfile.mkdtemp(prefix="spkplan.", dir=a.workdir or None)
            try:
                print_plan(make_plan(a, work))
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return 0
        if a.cmd == "build":
            return build_update(a)
        if a.cmd == "inject":
            return inject_update(a)
        if a.cmd == "verify":
            return verify_update(a)
        if a.cmd == "inspect":
            rep = inspect_update(a.zip, a.media_out)
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
