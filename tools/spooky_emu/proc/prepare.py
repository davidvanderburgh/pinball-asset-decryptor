#!/usr/bin/env python3
"""prepare.py - turn a Spooky P-ROC game-code .pkg (Rick and Morty, Alice
Cooper's Nightmare Castle) into a runnable build.

usage: prepare.py PKG [--name NAME] [--force]

A .pkg is [8B size LE][16B IV][AES-256-CBC of a ZIP]; the ZIP is the game
folder the machine keeps at /game/RickAndMorty (Rick and Morty) or
/game/code (Alice Cooper): the game's Python 2.7 bytecode, its own copy of
procgame (SkeletonGame), config/ and assets/ - and for Alice Cooper the
Unity player that draws its screen (uptest/).  This decrypts it with
PAD-Runtime's openssl (its python has no AES module) using the app's own
keys (plugins/spooky/games.py), unpacks it to $SPP_CACHE/<name>/ and deletes
the ZIP; the .pkg is only read.

<name> defaults to <title>_<version>: rm_20220902 (the date in the file
name), ac_<the newest WHATSNEW.txt version>.  `title` in the build says
which game it is (rm | ac), `src` which file it came from (the Emulate tab's
Cache window shows it) and `src_key` that file's name, size and time: the
same file again finds its build without decrypting it (Alice Cooper's
version is only known from inside).  The last line is `build=<name>`
(watch.sh reads it).

Exit 3: not enough free space; 4: not a P-ROC game this knows (Total Nuclear
Annihilation's key is not known), or damaged.
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPP_ROOT = os.environ.get("SPP_ROOT", "/var/tmp/pad_spkproc")
SPP_CACHE = os.path.join(SPP_ROOT, "cache")

# title: (the .pkg name's prefix, the key's name in games.py, a file only
# that game's ZIP has)
TITLES = {
    "rm": ("rm-gamecode", "RM_AES_KEY", "RMGame.pyc"),
    "ac": ("ac-gamecode", "AC_AES_KEY", "ACGame.py"),
}


def keys():
    """The .pkg keys, read from the app's own Spooky plugin."""
    ns = {}
    with open(os.path.join(REPO, "pinball_decryptor", "plugins", "spooky", "games.py")) as f:
        exec(compile(f.read(), "games.py", "exec"), ns)
    return ns


def title_of(pkg):
    base = os.path.basename(pkg).lower()
    for title, (prefix, _, _) in TITLES.items():
        if base.startswith(prefix):
            return title
    if base.startswith("tna-gamecode"):
        print("prepare.py: Total Nuclear Annihilation's .pkg key is not known", file=sys.stderr)
        sys.exit(4)
    print("prepare.py: not a Spooky P-ROC game-code .pkg (rm-gamecode*, ac-gamecode*): %s" % pkg,
          file=sys.stderr)
    sys.exit(4)


def decrypt(pkg, out_zip, key):
    with open(pkg, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        iv = f.read(16)
    with open(pkg, "rb") as src, open(out_zip, "wb") as dst:
        src.seek(24)
        p = subprocess.Popen(["openssl", "enc", "-d", "-aes-256-cbc", "-nopad",
                              "-K", key.hex(), "-iv", iv.hex()],
                             stdin=src, stdout=dst)
        if p.wait() != 0:
            sys.exit("prepare.py: openssl failed on %s" % pkg)
    os.truncate(out_zip, size)


def src_key(pkg):
    st = os.stat(pkg)
    return "%s %d %d" % (os.path.basename(pkg), st.st_size, int(st.st_mtime))


def cached(key):
    """The finished build made from the file with this src_key, or None."""
    try:
        names = sorted(os.listdir(SPP_CACHE))
    except OSError:
        return None
    for name in names:
        d = os.path.join(SPP_CACHE, name)
        try:
            with open(os.path.join(d, "src_key")) as f:
                if f.read().strip() == key and os.path.exists(os.path.join(d, "title")):
                    return name
        except OSError:
            continue
    return None


def room_for(pkg):
    """The ZIP and its unpacked tree side by side: about 2.5x the .pkg."""
    if not hasattr(os, "statvfs"):         # the tests, on Windows
        return True
    st = os.statvfs(SPP_CACHE)
    return st.f_bavail * st.f_frsize >= int(os.path.getsize(pkg) * 2.5)


def ready(out):
    print("prepare.py: %s ready (--force to redo)" % out)
    print("build=%s" % os.path.basename(out))


def version(title, pkg, out):
    if title == "rm":
        m = re.search(r"(\d{8})", os.path.basename(pkg))
        return m.group(1) if m else "0"
    # Alice Cooper's WHATSNEW.txt opens with its newest version ("v1.23 ...").
    try:
        with open(os.path.join(out, "WHATSNEW.txt"), errors="replace") as f:
            m = re.search(r"[vV](?:ersion)?\s*(\d+(?:\.\d+)+)", f.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    return "0"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pkg")
    ap.add_argument("--name")
    ap.add_argument("--force", action="store_true", help="unpack again over a finished build")
    a = ap.parse_args()
    title = title_of(a.pkg)
    _, key_name, marker = TITLES[title]
    os.makedirs(SPP_CACHE, exist_ok=True)
    # Unpacked under a scratch name first: the version is read from the ZIP.
    tmp = os.path.join(SPP_CACHE, ".unpack-%s-%d" % (title, os.getpid()))
    if a.name and os.path.exists(os.path.join(SPP_CACHE, a.name, "title")) and not a.force:
        ready(os.path.join(SPP_CACHE, a.name))
        return
    key = src_key(a.pkg)
    hit = None if a.force or a.name else cached(key)
    if hit:
        ready(os.path.join(SPP_CACHE, hit))
        return
    if not room_for(a.pkg):
        print("prepare.py: not enough free space in %s to unpack %s" % (SPP_CACHE, a.pkg),
              file=sys.stderr)
        sys.exit(3)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp_zip = tmp + ".zip"
    decrypt(a.pkg, tmp_zip, keys()[key_name])
    try:
        with zipfile.ZipFile(tmp_zip) as z:
            if marker not in z.namelist():
                print("prepare.py: %s has no %s - not the game its name says" % (a.pkg, marker),
                      file=sys.stderr)
                sys.exit(4)
            for info in z.infolist():
                z.extract(info, tmp)
                mode = info.external_attr >> 16
                if mode & 0o111:
                    os.chmod(os.path.join(tmp, info.filename), mode & 0o777)
    except zipfile.BadZipFile:
        shutil.rmtree(tmp, ignore_errors=True)
        print("prepare.py: %s did not decrypt to a ZIP (wrong key?)" % a.pkg, file=sys.stderr)
        sys.exit(4)
    finally:
        os.remove(tmp_zip)
    # Alice Cooper's archive carries no execute bits on its Unity player.
    for exe in ("uptest/main.x86_64",):
        if os.path.exists(os.path.join(tmp, exe)):
            os.chmod(os.path.join(tmp, exe), 0o755)
    name = a.name or "%s_%s" % (title, version(title, a.pkg, tmp))
    out = os.path.join(SPP_CACHE, name)
    if os.path.exists(os.path.join(out, "title")) and not a.force:
        shutil.rmtree(tmp, ignore_errors=True)
        with open(os.path.join(out, "src_key"), "w") as f:
            f.write(key + "\n")
        ready(out)
        return
    shutil.rmtree(out, ignore_errors=True)
    with open(os.path.join(tmp, "src"), "w") as f:
        f.write(os.path.abspath(a.pkg) + "\n")
    with open(os.path.join(tmp, "src_key"), "w") as f:
        f.write(key + "\n")
    with open(os.path.join(tmp, "title"), "w") as f:
        f.write(title + "\n")
    os.rename(tmp, out)
    print("prepare.py: %s (title %s)" % (out, title))
    print("build=%s" % name)


if __name__ == "__main__":
    main()
