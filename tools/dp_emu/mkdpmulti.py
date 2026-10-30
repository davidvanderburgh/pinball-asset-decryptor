#!/usr/bin/env python3
"""mkdpmulti.py - a multi-boot for The Big Lebowski (Dutch Pinball, PAD-853): several builds
on one machine and a boot menu it shows at power-up - the flippers choose, START boots, the
countdown boots the last one picked - drawn by the same menu program a Stern card, a JJP
machine and a Barrels of Fun machine show.  tools/dp_emu/MULTIBOOT.md has the whole story.

    mkdpmulti.py plan    --primary STOCK.zip --extra MOD.zip ...         what it costs
    mkdpmulti.py build   --primary STOCK.zip --extra MOD.zip --out OUT.zip --selector-dir DIR ...
    mkdpmulti.py verify  --zip OUT.zip                                   read it back, check it
    mkdpmulti.py inspect --zip OUT.zip [--json] [--media-out DIR]        the menu it carries
    mkdpmulti.py inject  --zip OUT.zip ...                               a new menu, written over it
    mkdpmulti.py media   --primary STOCK.zip --extra MOD.zip --out DIR   the menu's pictures

WHAT IT MAKES: ONE TBL update zip, TBL-v<V>.zip, that the machine's own USB update installs
as ~/game/<V>/ and its own Version Select switches to once.  <V> is digits and dots (the
update menu and Version Select list nothing else), not a version Dutch Pinball uses ("9."
and four digits), and short: the game's PyInstaller loader fails on a long path, so <V>
plus one digit - a build's folder - stays at seven characters.

    <V>/start              the launcher (codeselect/padselect_dp.sh): run.sh runs it at
                           every power-up; it makes the builds, shows the menu, starts one
    <V>/database/          empty: Version Select copies the running database into it
    <V>/pad/dpselect       the menu (static), dpprocsw (the buttons, on the game's own
                           libpinproc), font.ttf, images.conf, builds.txt, build.json, media/
    <V>/pad/b<k>/          build k's files: an update zip's <version>/ folder as it is

THE IMAGES.  --primary is the STOCK version the machine runs: a Dutch Pinball update zip
(TBL-v1.15.zip), read only for its version - nothing of it travels, because the machine has
it already; its card boots that folder (and, when the machine does not have it, the newest
stock version there).  Every --extra is another TBL update zip - a mod PAD wrote, or another
Dutch Pinball version - whose <version>/ folder travels as pad/b<k>/ and becomes ~/game/<V><k>
on the machine the first time the launcher runs: a hard-linked copy of the newest version
its `delta` names that the machine has, the build's files laid over it, as the USB update
lays a delta.  A zip with no `delta` is whole and needs no base.

Pure Python (zipfile); runs anywhere the tab does.
"""
import argparse
import collections
import json
import os
import re
import shutil
import stat
import sys
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

TOOL = "mkdpmulti"
#: build.json's shape; a reader must accept an older (or missing) one.
VERSION = "1.0"
PAD = "pad"
MAX_IMAGES = 7                                 # <V> + one digit: builds 1..9; the menu's cards
NAME_MAX = 7                                   # a version folder's name (the PyInstaller loader)
FAT32_MAX = 4 * 1024 ** 3 - 1
FAT32_MARGIN = 64 << 20
USB_SIZES = collections.OrderedDict([("8G", 7_700_000_000), ("16G", 15_400_000_000),
                                     ("32G", 30_900_000_000), ("64G", 61_800_000_000)])
#: the USB update refuses a zip unless the machine has 2.5 times its unpacked size free
#: (menuitem_usbupdate_download.py)
UNZIP_FACTOR = 2.5
SELECTOR_FILES = collections.OrderedDict([      # name in --selector-dir -> (mode, required)
    ("dpselect", (0o755, True)),
    ("dpprocsw", (0o755, True)),
    ("padselect.sh", (0o755, True)),
    ("font.ttf", (0o644, False)),
])
VOLUME_DEFAULT = 50
HOST_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TITLE = "THE BIG LEBOWSKI"
#: the buttons the launcher reads off the stock version's machine.yaml; written into the conf
#: for the record (the launcher passes them to dpprocsw; the menu reads its pipe)
SWITCHES = collections.OrderedDict()
#: already compressed: stored, not deflated again
STORED_EXT = {".mp4", ".mov", ".ogg", ".ogv", ".mp3", ".png", ".jpg", ".jpeg", ".zip", ".gz",
              ".cdmd", ".ttf", ".webm", ".flac"}
CONF_HEADER = [
    "# images.conf - The Big Lebowski boot menu (dpselect + the launcher <V>/start); written by mkdpmulti.py",
    "# image=<folder>|<title>|<subtitle>[|<art>|<anim>|<music>[|<confirm>]]   index = order (0-based);",
    "# <folder> = the version folder in ~/game the card starts (a build's is made by the launcher);",
    "# default = highlight when there is no last choice; timeout = seconds before it boots by itself"]
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def _gb(n):
    return "%.2f GB" % (n / 1e9) if n is not None else "?"


def split_list(s):
    return bof.split_list(s)


# ============================================================================== TBL zips
class TblZip:
    """One TBL update zip: its <version>/ folder, the versions its delta may be laid over
    (empty = whole), the files and their unpacked size."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        if not os.path.isfile(self.path):
            raise Refused("%s does not exist" % self.path)
        try:
            zf = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as e:
            raise Refused("%s is not a zip: %s" % (os.path.basename(self.path), e))
        with zf:
            tops = set()
            self.members = []
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise Refused("%s: unsafe member %r" % (os.path.basename(self.path), name))
                top = name.split("/", 1)[0]
                if top.startswith("__MACOSX") or top.startswith("._"):
                    continue
                tops.add(top)
                self.members.append(info)
            if len(tops) != 1 or not VERSION_RE.match(next(iter(tops))):
                raise Refused("%s is not a Big Lebowski update: it should hold ONE <version>/ folder "
                              "(it holds %s)" % (os.path.basename(self.path), ", ".join(sorted(tops)) or "nothing"))
            self.version = next(iter(tops))
            self.delta = []
            try:
                text = zf.read(self.version + "/delta").decode("utf-8", errors="replace")
                self.delta = [v.strip() for v in re.split(r"[,\s]+", text) if VERSION_RE.match(v.strip())]
            except KeyError:
                pass
            names = {i.filename for i in self.members}
            self.has_start = (self.version + "/start") in names
            self.size = sum(i.file_size for i in self.members)
            self.zsize = sum(i.compress_size for i in self.members)

    @property
    def whole(self):
        return not self.delta


def default_v(now=None):
    """'9.' and four digits from the minute it is built: never a Dutch Pinball version,
    new for every build (the USB update offers only a version the machine has not got)."""
    minute = int((now if now is not None else time.time()) // 60)
    return "9.%04d" % (minute % 9000 + 1000)


def check_v(v, n_builds):
    if not VERSION_RE.match(v or ""):
        raise Refused("--version %r: the machine's update menu and Version Select list only "
                      "digits and dots" % v)
    if len(v) + 1 > NAME_MAX and n_builds:
        raise Refused("--version %s: a build's folder is it plus one digit, %d characters; the game's "
                      "loader needs at most %d" % (v, len(v) + 1, NAME_MAX))
    if n_builds > 9:
        raise Refused("at most 9 builds: a build's folder is the version plus one digit")
    return v


def _inputs(a):
    if not a.extra:
        raise Refused("a multi-boot needs at least two images: --primary (the stock version) and one --extra")
    if 1 + len(a.extra) > MAX_IMAGES:
        raise Refused("at most %d images in one Big Lebowski multi-boot" % MAX_IMAGES)
    zs = [TblZip(a.primary)] + [TblZip(e) for e in a.extra]
    v = check_v(getattr(a, "version", None) or default_v(), len(zs) - 1)
    for z in zs:
        if z.version == v:
            raise Refused("%s is version %s, the multi-boot's own: pick another --version"
                          % (os.path.basename(z.path), v))
    for i, z in enumerate(zs[1:], 1):
        if z.whole and not z.has_start:
            raise Refused("image %d (%s): a zip with no delta list must be a whole version, and it has no "
                          "program (%s/start)" % (i, os.path.basename(z.path), z.version))
    return zs, v


def build_folder(v, k):
    return "%s%d" % (v, k)


def targets_of(zs, v):
    """what each card boots: the stock version's folder, then each build's"""
    return [zs[0].version] + [build_folder(v, k) for k in range(1, len(zs))]


# ============================================================================== plan
def make_plan(a):
    zs, v = _inputs(a)
    media = mkc.plan_media(a.media_dir, len(zs)) if getattr(a, "media_dir", None) else None
    menu = 3_500_000 + (media["total"] if media else 0)
    total = sum(z.zsize for z in zs[1:]) + menu
    unpacked = sum(z.size for z in zs[1:]) + menu
    return {"zips": zs, "v": v, "media": media, "menu": menu, "total": total, "unpacked": unpacked}


def print_plan(plan):
    zs, v = plan["zips"], plan["v"]
    print("== layout: one update zip TBL-v%s.zip; the machine's USB update installs it as ~/game/%s, "
          "Version Select switches to it once; image 0 = the stock version already on the machine; "
          "every other image = a build made beside it the first time the menu starts" % (v, v))
    print("== game code versions")
    for i, (z, t) in enumerate(zip(zs, targets_of(zs, v))):
        kind = ("stock, on the machine" if i == 0 else
                "whole" if z.whole else "laid over %s" % ",".join(z.delta))
        print("  %d  %s  %s  %s  (%s)" % (i, t, os.path.basename(z.path), z.version, kind))
    print("== bytes in the update")
    print("image-size 0 %s 0 the stock version: already on the machine, nothing travels" % zs[0].version)
    for i, z in enumerate(zs[1:], 1):
        print("image-size %d %s %d %s's files (%s unpacked)"
              % (i, build_folder(v, i), z.zsize, os.path.basename(z.path), _gb(z.size)))
    print("image-size overhead %d the menu, its pictures and the launcher" % plan["menu"])
    print("zip-size %d estimated multi-boot zip" % plan["total"])
    print("machine-free %d the machine's update needs %.1f times the unpacked %s free on its drive"
          % (int(plan["unpacked"] * UNZIP_FACTOR), UNZIP_FACTOR, _gb(plan["unpacked"])))
    ok32 = plan["total"] + FAT32_MARGIN <= FAT32_MAX
    print("fat32: %s (one file on a FAT32 stick holds at most %s)" % ("fits" if ok32 else "TOO BIG", _gb(FAT32_MAX)))
    best = None
    for k, cap in USB_SIZES.items():
        ok = ok32 and plan["total"] <= cap
        print("fits USB %s stick size %d: %s (spare %d)" % (k, cap, "YES" if ok else "NO", cap - plan["total"]))
        if ok and best is None:
            best = k
    print("stick: %s" % (best or ("none: the update is bigger than a FAT32 stick holds in one file"
                                  if not ok32 else "none of %s is big enough" % ", ".join(USB_SIZES))))
    print("install: copy TBL-v%s.zip to the stick, install it with the service menu's USB update, then "
          "select %s in Version Select" % (v, v))


# ============================================================================== the conf
def render_conf(targets, titles, subtitles, default, timeout, rows, sound_move, sound_confirm, volume, **kw):
    return bof.render_conf(targets, titles, subtitles, default, timeout, rows, sound_move, sound_confirm,
                           volume, SWITCHES, header=CONF_HEADER, font=False, **kw)


def parse_conf(text):
    return bof.parse_conf(text)


def default_titles(zs):
    out = [("%s|Stock %s" % (TITLE, zs[0].version))]
    for z in zs[1:]:
        stem = re.sub(r"\.zip$", "", os.path.basename(z.path), flags=re.I)
        out.append("%s|%s" % (TITLE, stem))
    return out


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
                       countdown_word=a.countdown_word, footer=footer, learn=bool(getattr(a, "learn", False)))


# ============================================================================== the zip
def _info(name, mode, is_dir=False, when=None):
    zi = zipfile.ZipInfo(name, date_time=time.localtime(when or time.time())[:6])
    zi.create_system = 3                      # unix: unzip restores the modes
    if is_dir:
        zi.external_attr = ((stat.S_IFDIR | mode) << 16) | 0x10
    else:
        zi.external_attr = (stat.S_IFREG | mode) << 16
        ext = os.path.splitext(name)[1].lower()
        zi.compress_type = zipfile.ZIP_STORED if ext in STORED_EXT else zipfile.ZIP_DEFLATED
    return zi


def _write_bytes(zout, name, data, mode=0o644):
    zout.writestr(_info(name, mode), data)


def _write_file(zout, name, src, mode=0o644):
    with open(src, "rb") as f, zout.open(_info(name, mode, when=os.path.getmtime(src)), "w", force_zip64=True) as d:
        shutil.copyfileobj(f, d, 1 << 20)


def _member_mode(info, rel):
    m = (info.external_attr >> 16) & 0o777
    if info.create_system == 3 and m:
        return m
    return 0o755 if rel == "start" or rel.endswith(".so") or ".so." in rel else 0o644


def _copy_build(zout, z, dest, meter=None):
    """z's <version>/ folder into the new zip as dest/, member by member"""
    pre = z.version + "/"
    n = 0
    with zipfile.ZipFile(z.path) as zf:
        for info in z.members:
            name = info.filename.replace("\\", "/")
            if not name.startswith(pre):
                continue
            rel = name[len(pre):]
            if not rel:
                continue
            if name.endswith("/"):
                zout.writestr(_info(dest + rel, 0o755, is_dir=True), b"")
                continue
            zi = _info(dest + rel, _member_mode(info, rel))
            zi.date_time = info.date_time
            with zf.open(info) as s, zout.open(zi, "w", force_zip64=True) as d:
                while True:
                    b = s.read(1 << 20)
                    if not b:
                        break
                    d.write(b)
                    if meter:
                        meter(len(b))
            n += 1
    return n


def check_selector_dir(d):
    if not d or not os.path.isdir(d):
        raise Refused("--selector-dir %s is not a directory (ensuredpselect.sh installs one)" % d)
    for name, (_mode, required) in SELECTOR_FILES.items():
        if required and not os.path.isfile(os.path.join(d, name)):
            raise Refused("--selector-dir %s has no %s (ensuredpselect.sh installs it)" % (d, name))


def _font_src(selector_dir):
    src = os.path.join(selector_dir, "font.ttf") if selector_dir else ""
    if src and os.path.isfile(src):
        return src
    if os.path.isfile(HOST_FONT):
        return HOST_FONT
    raise Refused("no font.ttf in %s and no %s on this Linux: the menu would have nothing to draw its "
                  "words with (apt install fonts-dejavu-core)" % (selector_dir, HOST_FONT))


def _write_menu(zout, v, a, conf, builds_txt, manifest, media, media_dir):
    """<V>/start, <V>/database/, <V>/pad/<the menu> - everything but the builds' files"""
    pad = v + "/" + PAD + "/"
    zout.writestr(_info(v + "/", 0o755, is_dir=True), b"")
    _write_file(zout, v + "/start", os.path.join(a.selector_dir, "padselect.sh"), 0o755)
    zout.writestr(_info(v + "/database/", 0o755, is_dir=True), b"")
    zout.writestr(_info(pad, 0o755, is_dir=True), b"")
    for name, (mode, _req) in SELECTOR_FILES.items():
        if name == "padselect.sh":
            continue
        src = _font_src(a.selector_dir) if name == "font.ttf" else os.path.join(a.selector_dir, name)
        _write_file(zout, pad + name, src, mode)
    _write_bytes(zout, pad + "images.conf", conf.encode("utf-8"))
    _write_bytes(zout, pad + "builds.txt", builds_txt.encode("utf-8"))
    _write_bytes(zout, pad + mkc.BUILD_MANIFEST, (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    zout.writestr(_info(pad + "media/", 0o755, is_dir=True), b"")
    if media:
        for name, src in sorted(media["files"].items()):
            _write_file(zout, pad + "media/" + name, src)
        _write_file(zout, pad + mkc.MEDIA_MANIFEST, os.path.join(media_dir, mkc.MEDIA_MANIFEST))


def builds_text(zs, v):
    out = ["# builds.txt - <folder> <bases the files are laid over, newest present wins; - = whole> "
           "<files under pad/>; written by mkdpmulti.py"]
    for k, z in enumerate(zs[1:], 1):
        out.append("%s %s b%d" % (build_folder(v, k), ",".join(z.delta) if z.delta else "-", k))
    return "\n".join(out) + "\n"


def build_zip(a):
    zs, v = _inputs(a)
    out_default = "TBL-v%s.zip" % v
    out = os.path.abspath(a.out)
    if os.path.isdir(out):
        out = os.path.join(out, out_default)
    out = os.path.abspath(check_output_path(out, [z.path for z in zs], force=a.force))
    want = "TBL-v%s.zip" % v
    if os.path.basename(out) != want:
        # the machine's update menu reads the version off the FILE NAME; the folder inside must match
        say("note: the machine's update menu reads the version off the file name: it is written as %s" % want)
        out = os.path.join(os.path.dirname(out), want)
        out = os.path.abspath(check_output_path(out, [z.path for z in zs], force=a.force))
    check_selector_dir(a.selector_dir)
    media = mkc.plan_media(a.media_dir, len(zs)) if a.media_dir else None
    targets = targets_of(zs, v)
    tdef = default_titles(zs)
    conf = conf_from_args(a, targets, media, [t.split("|")[0] for t in tdef], [t.split("|")[1] for t in tdef])
    manifest = collections.OrderedDict([
        ("tool", TOOL), ("version", VERSION), ("written", time.strftime("%Y-%m-%dT%H:%M:%S")),
        ("title", "tbl"), ("multiboot_version", v),
        ("images", [collections.OrderedDict([
            ("index", i), ("folder", t), ("source", z.path), ("game_version", z.version),
            ("delta", z.delta or None), ("size", z.size), ("files", None if i == 0 else "b%d" % i)])
            for i, (z, t) in enumerate(zip(zs, targets))])])
    part = out + ".part"
    total = sum(z.size for z in zs[1:])
    PROGRESS.start(max(total, 1), "zip")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as zout:
            # the menu first: inspect reads it without the rest
            _write_menu(zout, v, a, conf, builds_text(zs, v), manifest, media, a.media_dir)
            for k, z in enumerate(zs[1:], 1):
                PROGRESS.step("build %d (%s)" % (k, os.path.basename(z.path)), z.size)
                n = _copy_build(zout, z, "%s/%s/b%d/" % (v, PAD, k), PROGRESS.add)
                say("image %d: %s (%s), %d files -> %s on the machine, laid over %s"
                    % (k, os.path.basename(z.path), z.version, n, build_folder(v, k),
                       ",".join(z.delta) if z.delta else "nothing (whole)"))
        os.replace(part, out)
    finally:
        if os.path.exists(part):
            os.unlink(part)
    PROGRESS.finish()
    say("wrote %s (%s)" % (out, _gb(os.path.getsize(out))))
    if os.path.getsize(out) > FAT32_MAX:
        say("warning: %s is bigger than a FAT32 stick holds in one file (%s)" % (out, _gb(FAT32_MAX)))
    say("on the machine: install it with the service menu's USB update, then select %s in Version Select" % v)
    return 0


# ============================================================================== read back
def _menu_of(path):
    path = os.path.abspath(path)
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise Refused("%s is not a zip: %s" % (os.path.basename(path), e))
    with zf:
        names = zf.namelist()
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) != 1:
            raise Refused("%s is not a Big Lebowski update (%d top folders)" % (os.path.basename(path), len(tops)))
        v = next(iter(tops))
        pad = v + "/" + PAD + "/"
        if pad + "images.conf" not in names:
            raise Refused("%s carries no boot menu (no %simages.conf): it is not a multi-boot" % (
                os.path.basename(path), pad))
        got = {}
        for n in names:
            if not n.startswith(pad) or n.endswith("/"):
                continue
            rel = n[len(pad):]
            if not re.match(r"^b\d+/", rel):      # the menu, not a build's files
                got[rel] = zf.read(n)
        start = zf.read(v + "/start") if (v + "/start") in names else b""
        builds = collections.Counter()
        for n in names:
            m = re.match(r"^%s(b\d+)/(.+[^/])$" % re.escape(pad), n)
            if m:
                builds[m.group(1)] += 1
        return v, got, start, builds, names


def inspect_zip(path, media_out=None):
    v, got, start, builds, _names = _menu_of(path)
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
    for i, ((folder, t, s), (art, anim, music, confirm)) in enumerate(zip(conf["images"], conf["media"])):
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
            ("index", i), ("device", folder), ("title", t), ("subtitle", s),
            ("art", art or None), ("anim", anim or None), ("music", music or None), ("confirm", confirm or None),
            ("art_source", _src("art_source")), ("anim_source", _src("anim_source")),
            ("music_source", _src("music_source")), ("confirm_source", _src("confirm_source")),
            ("source", src), ("source_exists", bool(src) and os.path.isfile(src)),
            ("name", os.path.basename(src) if src else None), ("version", b.get("game_version")),
            ("game_version", b.get("game_version")), ("size", b.get("size")), ("md5", None),
            ("delta", ",".join(b["delta"]) if b.get("delta") else None)]))
    media_files = sorted(n.split("/", 1)[1] for n in got if n.startswith("media/"))
    rep = collections.OrderedDict([
        ("zip", os.path.abspath(path)), ("fun", os.path.abspath(path)), ("size", os.path.getsize(path)),
        ("title", "tbl"), ("multiboot_version", v),
        ("tool", build.get("tool")), ("tool_version", build.get("version")), ("written", build.get("written")),
        # the launcher is the install step too (it makes the builds the first time)
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
    print("== %s (%s, The Big Lebowski multi-boot %s)" % (rep["zip"], _gb(rep["size"]), rep["multiboot_version"]))
    print("written by %s %s at %s; launcher: %s" % (rep["tool"] or "?", rep["tool_version"] or "?",
                                                   rep["written"] or "?", "yes" if rep["hook"] else "NO"))
    for im in rep["images"]:
        print("image %d %s '%s' '%s' art=%s version=%s source=%s"
              % (im["index"], im["device"], im["title"], im["subtitle"], im["art"], im["game_version"], im["source"]))
    print("timeout=%s default=%s theme=%s" % (rep["timeout"], rep["default"], rep["theme"]))
    for w in rep["warnings"]:
        print("warning: " + w)


def verify_zip(a):
    """The zip read back: every member's CRC, the launcher, the menu programs, and every card
    pointing at a build the zip carries (or the stock version)."""
    path = os.path.abspath(a.zip)
    v, got, start, builds, names = _menu_of(path)
    bad = []
    if not re.match(r"^TBL-v%s\.zip$" % re.escape(v), os.path.basename(path)):
        bad.append("the file is %s, but the machine's update menu reads the version off the name: "
                   "it must be TBL-v%s.zip" % (os.path.basename(path), v))
    if not start.startswith(b"#!"):
        bad.append("%s/start is not the launcher" % v)
    for name, (_mode, required) in SELECTOR_FILES.items():
        if required and name != "padselect.sh" and name not in got:
            bad.append("pad/%s is missing" % name)
    if (v + "/database/") not in names:
        bad.append("%s/database/ is missing (Version Select copies the database into it)" % v)
    conf = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
    lines = [ln.split() for ln in got.get("builds.txt", b"").decode("utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    folders = {ln[0]: ln for ln in lines if len(ln) >= 3}
    for i, (folder, _t, _s) in enumerate(conf["images"]):
        if i == 0:
            if folder in folders:
                bad.append("image 0 (%s) should be the stock version, not a build" % folder)
            continue
        ln = folders.get(folder)
        if not ln:
            bad.append("image %d (%s) is no build in builds.txt" % (i, folder))
        elif not builds.get(ln[2]):
            bad.append("image %d (%s): pad/%s/ carries no files" % (i, folder, ln[2]))
        elif len(folder) > NAME_MAX:
            bad.append("image %d: folder %s is longer than the game's loader takes" % (i, folder))
    if not getattr(a, "quick", False):
        PROGRESS.start(max(os.path.getsize(path), 1), "verify")
        with zipfile.ZipFile(path) as zf:
            first = zf.testzip()
        PROGRESS.finish()
        if first:
            bad.append("member %s does not match its CRC" % first)
    for b in bad:
        say("verify: FAIL %s" % b)
    if bad:
        return 1
    say("verify: OK %s - %d cards, %d builds, the launcher and the menu" % (
        os.path.basename(path), len(conf["images"]), len(builds)))
    return 0


def inject_zip(a):
    """A new menu for an existing multi-boot zip, written over it: the builds' members copied
    across as they are, pad/ rewritten (the conf from the flags, falling back to the zip's own
    values; the menu programs from --selector-dir when given; the pictures from --media-dir,
    else the ones it carries)."""
    path = os.path.abspath(check_output_path(a.zip, [], must_exist=True))
    v, got, _start, _builds, _names = _menu_of(path)
    old = parse_conf(got["images.conf"].decode("utf-8", errors="replace"))
    targets = [p for p, _t, _s in old["images"]]
    work = tempfile.mkdtemp(prefix="dpinject.", dir=os.path.dirname(path))
    try:
        media_dir = a.media_dir
        if media_dir is None and mkc.MEDIA_MANIFEST in got:
            media_dir = os.path.join(work, "media_carried")
            os.makedirs(media_dir)
            for n, data in got.items():
                if n.startswith("media/") or n == mkc.MEDIA_MANIFEST:
                    with open(os.path.join(media_dir, n.split("/", 1)[-1]), "wb") as f:
                        f.write(data)
            say("media: the zip's own set is carried through")
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
            for name in SELECTOR_FILES:
                if name in got:
                    with open(os.path.join(sel, name), "wb") as f:
                        f.write(got[name])
            with zipfile.ZipFile(path) as zf:
                with open(os.path.join(sel, "padselect.sh"), "wb") as f:
                    f.write(zf.read(v + "/start"))
        man = collections.OrderedDict()
        try:
            man = json.loads(got.get(mkc.BUILD_MANIFEST, b"{}").decode("utf-8"),
                             object_pairs_hook=collections.OrderedDict)
        except ValueError:
            pass
        man["menu_written"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        b_txt = got.get("builds.txt", b"").decode("utf-8")

        class _A:
            pass
        sa = _A()
        sa.selector_dir = sel
        part = path + ".part"
        size = os.path.getsize(path)
        PROGRESS.start(max(size, 1), "inject")
        try:
            with zipfile.ZipFile(path) as zin, \
                    zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zout:
                _write_menu(zout, v, sa, conf, b_txt, man, media, media_dir)
                pad = v + "/" + PAD + "/"
                for info in zin.infolist():
                    if not re.match(r"^%sb\d+/" % re.escape(pad), info.filename):
                        continue
                    with zin.open(info) as s, zout.open(info, "w", force_zip64=True) as d:
                        shutil.copyfileobj(s, d, 1 << 20)
                    PROGRESS.add(info.compress_size)
            os.replace(part, path)
        finally:
            if os.path.exists(part):
                os.unlink(part)
        PROGRESS.finish()
        say("the menu of %s is rewritten (%s)" % (path, _gb(os.path.getsize(path))))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ============================================================================== media
def cmd_media(a):
    """The menu's pictures and sounds through selectmedia.py, as the JJP builder does.  A TBL
    update has no picture the tools can take for 'auto' (its clips are .cdmd dot-matrix
    sequences), so 'auto' is no picture; sounds are the built-in click / chime."""
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
            say("art %d: 'auto' - a Big Lebowski update has no still the tools can take; no picture" % i)
            spec = "none"
        argv += ["--art", "%d=%s" % (i, spec)]
    for i, spec in enumerate(anims):
        if spec.startswith("auto"):
            say("anim %d: 'auto' - no attract clip the tools can play; none" % i)
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
    s.add_argument("--selector-dir", help="a directory holding dpselect, dpprocsw, padselect.sh and "
                                          "optionally font.ttf (ensuredpselect.sh installs one)")
    s.add_argument("--media-dir", help="directory holding media.json (mkdpmulti.py media) and the files it names")
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
        s.add_argument("--primary", required=True, help="the stock version's update zip (TBL-v1.15.zip)")
        s.add_argument("--extra", action="append", default=[], metavar="ZIP", help="a build: a TBL update zip")
        s.add_argument("--version", help="the multi-boot's own version folder (default 9. and four digits)")
        s.add_argument("--cache-dir", help="(accepted for the tab; nothing is cached)")
        if name == "plan":
            s.add_argument("--media-dir")
        else:
            s.add_argument("--out", required=True, help="the zip to write (or a folder: TBL-v<V>.zip in it)")
            _add_conf_flags(s)
            s.add_argument("--force", action="store_true")
            s.add_argument("--workdir")
            s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("inject")
    s.add_argument("--zip", "--fun", dest="zip", required=True)
    _add_conf_flags(s)
    s.add_argument("--default-card", type=int)
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--workdir")
    s.add_argument("--cache-dir")
    s.add_argument("--keep-work", action="store_true")
    s = sub.add_parser("verify")
    s.add_argument("--zip", "--fun", dest="zip", required=True)
    s.add_argument("--primary")
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--quick", action="store_true")
    s.add_argument("--workdir")
    s = sub.add_parser("inspect")
    s.add_argument("--zip", "--fun", dest="zip", required=True)
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
            print_plan(make_plan(a))
            return 0
        if a.cmd == "build":
            return build_zip(a)
        if a.cmd == "inject":
            return inject_zip(a)
        if a.cmd == "verify":
            return verify_zip(a)
        if a.cmd == "inspect":
            rep = inspect_zip(a.zip, a.media_out)
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
