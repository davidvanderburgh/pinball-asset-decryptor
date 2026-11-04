"""mkspkproc.py - the P-ROC half of mkspkmulti.py (PAD-980): a multi-boot for Rick and Morty
(rm-gamecode-*.pkg) or Alice Cooper's Nightmare Castle (ac-gamecode.pkg).  MULTIBOOT.md,
"P-ROC titles", has the design; mkspkmulti.py calls in here for these two titles and keeps
its command line.

Both packages are a ZIP encrypted with AES-256-CBC ([8 bytes size LE][16 bytes IV][data],
the key in plugins/spooky/games.py), which the machine's codeupdate decrypts and unzips into
the game's own folder (/game/RickAndMorty, /game/code).  The games run only there, so the
multi-boot package is the STOCK package's ZIP as it is - the stock build lands in the folder
the machine's way - plus:

    PAD_MULTIBOOT/          the launcher (padselect.sh = codeselect/padselect_proc.sh), the
                            menu (spkselect, font.ttf, images.conf, media/), the reader
                            (dpprocsw), proc.conf, builds.txt, build.json, every other
                            build's files (d<k>/, d<k>.removed); the hook renames it .pad.
                            A plain name, not a dot: Alice Cooper's pkgprocess copies
                            `extracted/*`, which skips dot entries
    PAD_MULTIBOOT_LIVE      "b0 <stamp>": the folder holds b0 of this multi-boot
    the hook                Rick and Morty: run-on-update.sh (codeupdate runs it as root
                            after unzipping, then deletes it) - Spooky's own runs first,
                            then .pad, then ~launch/.local/rmstart.sh.  Alice Cooper: its
                            codeupdate runs no package script, but its xinitrc runs
                            uptest/main.x86_64 as root - a one-time stub that puts the real
                            player back (shipped as main.x86_64.real), .pad, the launcher's
                            xinitrc, and reboots

The AES layer is openssl's (PAD-Runtime's python has no AES module, as proc/prepare.py
found), or pycryptodome's when that is there.
"""
import json
import os
import shutil
import stat
import struct
import subprocess
import tarfile
import time
import zipfile

PAD_DIR = "PAD_MULTIBOOT"
MARK = "PAD_MULTIBOOT_LIVE"
SELECTOR_FILES = (("spkselect", 0o755), ("dpprocsw", 0o755), ("padselect_proc.sh", 0o755),
                  ("font.ttf", 0o644))

#: the two titles: their folder, what starts the game there, the machine's libpinproc, the
#: machine yaml's flipper / START switches, the settings files the game writes in its folder
PROC = {
    "rick_and_morty": dict(
        folder="/game/RickAndMorty", lib="/usr/local/lib", sw=("SD14", "SD8", "SD15"),
        start="python RMGame.pyc 2>> /tmp/runlog", program="RMGame.pyc", hook="rm",
        keep=("config/game_user_data.yaml", "config/game_user_settings.yaml")),
    "alice_cooper": dict(
        folder="/game/code", lib="/usr/lib", sw=("SD14", "SD10", "SD15"),
        start=("chmod +x uptest/main.x86_64; (cd uptest && exec ./main.x86_64 . &); "
               "find /game/log.txt -size +100M -delete; python2 ACGame.py >> /game/log.txt 2>&1"),
        program="ACGame.py", hook="ac",
        keep=("config/game_user_data.yaml", "config/game_user_settings.yaml")),
}

RM_HOOK = r'''#!/bin/bash
# run-on-update.sh - the PAD multi-boot's install step (PAD-980).  codeupdate runs this as
# root once it has unzipped the package into /game/RickAndMorty, and deletes it after.
G=/game/RickAndMorty
cd "$G" || exit 1
# Spooky's own install step first, exactly as a normal update runs it
[ -f "$G/PAD_MULTIBOOT/run-on-update.stock.sh" ] && bash "$G/PAD_MULTIBOOT/run-on-update.stock.sh"
# the multi-boot's folder in place (a dot folder: the next normal update's rm -rf G/* keeps it)
rm -rf "$G/.pad.old"
[ -d "$G/.pad" ] && mv "$G/.pad" "$G/.pad.old"
mv "$G/PAD_MULTIBOOT" "$G/.pad" && rm -rf "$G/.pad.old"
# the start script the game's X session runs: the menu, then the game
H=/game/images/launch/.local
mkdir -p "$H"
if [ -f "$H/rmstart.sh" ] && ! grep -q "PAD multi-boot" "$H/rmstart.sh"; then
    cp -p "$H/rmstart.sh" "$H/rmstart.sh.stock"
fi
cp -f "$G/.pad/rmstart.sh" "$H/rmstart.sh"
chmod 755 "$H/rmstart.sh"
chown launch:launch "$H/rmstart.sh" 2>/dev/null
chown -R launch:launch "$G/.pad" "$G/PAD_MULTIBOOT_LIVE" 2>/dev/null
sync
'''

RM_START = r'''#!/bin/bash
# rmstart.sh - PAD multi-boot (PAD-980): the boot menu, which then starts the chosen build;
# the game itself when the menu is gone.
L=/game/RickAndMorty/.pad/padselect.sh
[ -f "$L" ] && exec bash "$L"
cd /game/RickAndMorty && exec python RMGame.pyc 2>> /tmp/runlog
'''

AC_STUB = r'''#!/bin/bash
# The PAD multi-boot's install step for Alice Cooper (PAD-980).  The machine's xinitrc runs
# uptest/main.x86_64 - as root - and this is it, once: the real player back in its place,
# the multi-boot's folder in place, the launcher's xinitrc installed, and a restart into it.
C=/game/code
mv -f "$C/uptest/main.x86_64.real" "$C/uptest/main.x86_64" || exit 1
chmod +x "$C/uptest/main.x86_64"
rm -rf "$C/.pad.old"
[ -d "$C/.pad" ] && mv "$C/.pad" "$C/.pad.old"
mv "$C/PAD_MULTIBOOT" "$C/.pad" && rm -rf "$C/.pad.old"
unlock-root
cp -f "$C/.pad/xinitrc" /etc/X11/xinit/xinitrc
lock-root
sync
reboot
'''

AC_BLOCK = '''# PAD multi-boot (PAD-980): the boot menu puts the chosen build in /game/code and starts it;
# without the menu, the machine's own start (these lines keep the words uptest and delete)
if [ -f /game/code/.pad/padselect.sh ]; then
bash /game/code/.pad/padselect.sh
else
chmod +x /game/code/uptest/main.x86_64
cd /game/code/uptest
./main.x86_64 . &
cd /game/code
find /game/log.txt -size +100M -delete
python2 ACGame.py >> /game/log.txt 2>&1
fi
'''


class Refused(Exception):
    pass


def ac_xinitrc(stock):
    """The stock xinitrc with its two start lines (from `chmod +x .../main.x86_64` to
    `python2 ACGame.py`) replaced by AC_BLOCK"""
    lines = stock.splitlines(True)
    a = [i for i, ln in enumerate(lines) if ln.strip().startswith("chmod +x /game/code/uptest/main.x86_64")]
    b = [i for i, ln in enumerate(lines) if ln.strip().startswith("python2 ACGame.py")]
    if not a or not b or b[-1] < a[0]:
        raise Refused("the update's xinitrc does not start the game the way this builder knows")
    out = "".join(lines[:a[0]]) + AC_BLOCK + "".join(lines[b[-1] + 1:])
    if "uptest" not in out or "delete" not in out:
        raise Refused("the launcher's xinitrc lost the words the game checks for")
    return out


# ============================================================================ AES
def _key(fmt):
    import importlib
    games = importlib.import_module("pinball_decryptor.plugins.spooky.games")
    return {"rm_pkg": games.RM_AES_KEY, "ac_pkg": games.AC_AES_KEY}[fmt]


def _have_crypto():
    try:
        from Crypto.Cipher import AES  # noqa: F401
        return True
    except ImportError:
        return False


def aes_decrypt(pkg, out_zip, fmt):
    key = _key(fmt)
    with open(pkg, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
        if _have_crypto():
            from Crypto.Cipher import AES
            dec = AES.new(key, AES.MODE_CBC, iv)
            with open(out_zip, "wb") as o:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    o.write(dec.decrypt(b))
        else:
            # a file of its own at byte 24: f's buffered reads have moved its descriptor on
            with open(out_zip, "wb") as o, open(pkg, "rb") as src:
                src.seek(24)
                p = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
                                      "-K", key.hex(), "-iv", iv.hex()], stdin=src, stdout=o)
                if p.wait() != 0:
                    raise Refused("openssl could not decrypt %s" % os.path.basename(pkg))
    os.truncate(out_zip, size)
    with open(out_zip, "rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise Refused("%s did not decrypt to a zip (a damaged package?)" % os.path.basename(pkg))


def aes_encrypt(zip_path, out_pkg, fmt):
    key = _key(fmt)
    size = os.path.getsize(zip_path)
    iv = os.urandom(16)
    pad = (-size) % 16
    with open(out_pkg, "wb") as o:
        o.write(struct.pack("<Q", size))
        o.write(iv)
        o.flush()
        if _have_crypto():
            from Crypto.Cipher import AES
            enc = AES.new(key, AES.MODE_CBC, iv)
            with open(zip_path, "rb") as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    if len(b) % 16:
                        b += b"\0" * (16 - len(b) % 16)
                    o.write(enc.encrypt(b))
            return
        p = subprocess.Popen(["openssl", "enc", "-e", "-aes-256-cbc", "-nopad",
                              "-K", key.hex(), "-iv", iv.hex()], stdin=subprocess.PIPE, stdout=o)
        with open(zip_path, "rb") as f:
            shutil.copyfileobj(f, p.stdin, 1 << 20)
        p.stdin.write(b"\0" * pad)
        p.stdin.close()
        if p.wait() != 0:
            raise Refused("openssl could not encrypt the package")


# ============================================================================ the zip as tar members
class _ZipReader:
    """tarfile's reading interface over a zip, for SpkUpdate.members"""

    def __init__(self, zf):
        self.zf = zf

    def extractfile(self, ti):
        return self.zf.open(ti.pad_zinfo)


class _ZipTarInfo(tarfile.TarInfo):
    """a TarInfo that can carry its zip entry (TarInfo itself has __slots__)"""


def zip_members(zip_path):
    """(reader, TarInfo, name) for every member of a decrypted package"""
    with zipfile.ZipFile(zip_path) as zf:
        r = _ZipReader(zf)
        for zi in zf.infolist():
            name = zi.filename
            ti = _ZipTarInfo(name.rstrip("/"))
            mode = (zi.external_attr >> 16) & 0o177777
            ti.mode = (mode & 0o7777) or (0o755 if name.endswith("/") else 0o644)
            ti.mtime = time.mktime(zi.date_time + (0, 0, -1))
            if name.endswith("/") or stat.S_ISDIR(mode):
                ti.type = tarfile.DIRTYPE
            elif stat.S_ISLNK(mode):
                ti.type = tarfile.SYMTYPE
                ti.linkname = zf.read(zi).decode("utf-8", "replace")
            else:
                ti.type = tarfile.REGTYPE
                ti.size = zi.file_size
            ti.pad_zinfo = zi
            yield r, ti, name


class ZipOut:
    """the output zip, with mkspkmulti._Out's interface"""
    STORED = {".mp4", ".mov", ".ogg", ".ogv", ".mp3", ".png", ".jpg", ".jpeg", ".zip", ".gz", ".ttf",
              ".webm", ".flac", ".wav"}

    def __init__(self, zf):
        self.zf = zf
        self.pre = ""
        self.dirs = set()
        self.when = time.localtime()[:6]

    def _info(self, name, mode, is_dir=False, when=None):
        zi = zipfile.ZipInfo(name + ("/" if is_dir else ""), date_time=when or self.when)
        zi.create_system = 3
        if is_dir:
            zi.external_attr = ((stat.S_IFDIR | mode) << 16) | 0x10
        else:
            zi.external_attr = (stat.S_IFREG | mode) << 16
            zi.compress_type = (zipfile.ZIP_STORED if os.path.splitext(name)[1].lower() in self.STORED
                                else zipfile.ZIP_DEFLATED)
        return zi

    def _dir(self, name):
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d not in self.dirs:
                self.dirs.add(d)
                self.zf.writestr(self._info(d, 0o755, True), b"")

    def data(self, rel, data, mode=0o644):
        self._dir(rel)
        self.zf.writestr(self._info(rel, mode), data)

    def file(self, rel, src, mode=0o644):
        self._dir(rel)
        with open(src, "rb") as f, self.zf.open(self._info(rel, mode), "w", force_zip64=True) as d:
            shutil.copyfileobj(f, d, 1 << 20)

    def member(self, rel, ti, f=None, linkname=None):
        self._dir(rel)
        when = time.localtime(ti.mtime)[:6] if ti.mtime else None
        if ti.isdir():
            if rel not in self.dirs:
                self.dirs.add(rel)
                self.zf.writestr(self._info(rel, ti.mode or 0o755, True, when), b"")
            return
        if ti.issym():
            zi = self._info(rel, 0o777, when=when)
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            self.zf.writestr(zi, (linkname or ti.linkname).encode("utf-8"))
            return
        with self.zf.open(self._info(rel, ti.mode or 0o644, when=when), "w", force_zip64=True) as d:
            if f is not None:
                shutil.copyfileobj(f, d, 1 << 20)


# ============================================================================ the package
def proc_conf(t):
    l, r, s = t["sw"]
    lines = ["# proc.conf - the machine, for the launcher; written by mkspkmulti.py",
             "game=%s" % t["folder"], "start=%s" % t["start"], "lib=%s" % t["lib"],
             "L=%s" % l, "R=%s" % r, "S=%s" % s]
    lines += ["keep=%s" % k for k in t["keep"]]
    return "\n".join(lines) + "\n"


def write_menu(out, selector_dir, font, conf, title, builds_txt, manifest, media, media_dir, removed,
               manifest_name, media_manifest, stock_hook, stock_xinitrc):
    """PAD_MULTIBOOT/ and the hook - everything but the builds' files"""
    pad = PAD_DIR + "/"
    for name, mode in SELECTOR_FILES:
        src = font if name == "font.ttf" else os.path.join(selector_dir, name)
        out.file(pad + ("padselect.sh" if name == "padselect_proc.sh" else name), src, mode)
    out.data(pad + "images.conf", conf.encode("utf-8"))
    out.data(pad + "builds.txt", builds_txt.encode("utf-8"))
    out.data(pad + "proc.conf", proc_conf(title).encode("utf-8"))
    out.data(pad + manifest_name, (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    for k, rm in removed.items():
        out.data(pad + "d%d.removed" % k, ("".join(p + "\n" for p in rm)).encode("utf-8"))
    if media:
        for name, src in sorted(media["files"].items()):
            out.file(pad + "media/" + name, src)
        out.file(pad + media_manifest, os.path.join(media_dir, media_manifest))
    out.data(MARK, ("b0 %s\n" % manifest["stamp"]).encode("utf-8"))
    if title["hook"] == "rm":
        out.data("run-on-update.sh", RM_HOOK.encode("utf-8"), 0o755)
        out.data(pad + "rmstart.sh", RM_START.encode("utf-8"), 0o755)
        if stock_hook is not None:
            out.data(pad + "run-on-update.stock.sh", stock_hook, 0o755)
    else:
        if stock_xinitrc is None:
            raise Refused("the Alice Cooper update carries no xinitrc to start the menu from")
        out.data(pad + "xinitrc", ac_xinitrc(stock_xinitrc.decode("utf-8", "replace")).encode("utf-8"), 0o755)
        out.data("uptest/main.x86_64", AC_STUB.encode("utf-8"), 0o755)


def rename_b0(title, bp):
    """where a member of the stock build sits in the package: as it is, except the two our
    hook takes the place of"""
    if title["hook"] == "rm" and bp == "run-on-update.sh":
        return None                                   # shipped as PAD_MULTIBOOT/run-on-update.stock.sh
    if title["hook"] == "ac" and bp == "uptest/main.x86_64":
        return "uptest/main.x86_64.real"
    return bp


def read_all(u, work, names):
    """{name: bytes} of the named members of an update"""
    got = {}
    for r, ti, bp in u.members(work):
        if bp in names and ti.isfile():
            got[bp] = r.extractfile(ti).read()
    return got
