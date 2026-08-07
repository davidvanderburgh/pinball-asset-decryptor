#!/usr/bin/env python3
r"""padpath.py - every machine-specific path, worked out rather than written down.

THIS EXISTS BECAUSE THE RIG WAS WELDED TO ONE MACHINE. `/home/david` appeared in
187 of its files and the checkout's absolute path in 51 more, on both sides of
the WSL boundary, so a clone anywhere else could not run a single script.
Nothing here is clever - it is the four questions those literals were answering,
asked properly instead of assumed:

    RIG        where the scripts are      - from __file__, so a checkout moves
    root()     where the guest rootfs is  - PAD_ROOT, else ~/spike2root
    tables()   where DERIVED per-title data is cached
    to_win()   any of the above as WINDOWS sees it

THE UNC PATH IS NOT A CONSTANT EITHER, and it was the least obvious of them.
`\\wsl.localhost\Ubuntu\...` was hard-coded in four files: it names a distro
that need not exist, under a prefix that older WSL spells `\\wsl$` instead. So
it is not built here by pasting strings together - `wslpath -w` is asked, which
knows the right answer for the running system. That costs about 200 ms, so the
answer is cached for the life of the process.

CROSSING THE BOUNDARY WITHOUT PAYING FOR IT. watch.sh exports PAD_ROOT and
PAD_TABLES through WSLENV with the `/p` flag, which makes WSL translate them for
the Windows process it launches. The playfield window therefore normally finds
both already in Windows form and never spawns anything at all. The wslpath
fallback below is only for running that window by hand.

WHY THE DERIVED TABLES LIVE UNDER THE ROOTFS. They are written inside WSL (by
watch.sh, from the game binary) and read from Windows (by the playfield window),
so the two sides must name ONE directory - and `dump/` is already that place:
padled, padsw and the audio FIFO all live there. It is per machine, outside the
checkout, and thrown away with the rootfs, which is exactly the lifetime derived
data should have.
"""
import os
import subprocess
import sys

#: The rig's own directory. Every script that used to carry the checkout's
#: absolute path asks for this instead.
RIG = os.path.dirname(os.path.abspath(__file__))

_WIN = sys.platform == "win32"

#: CREATE_NO_WINDOW, so asking WSL a question does not flash a console over the
#: playfield window.
_CREATE_NO_WINDOW = 0x08000000

#: wslpath answers, cached: the round trip is ~200 ms and the answer cannot
#: change while this process lives.
_WIN_CACHE = {}


def _env(name):
    """``os.environ.get``, with an empty value treated as unset.

    NOT PEDANTRY. `env A="$B" cmd` passes an EMPTY A when B is unset rather than
    passing nothing, and the rig does exactly that in several places, so "" must
    not read as an answer. padglhost's atoi() learned this the hard way.
    """
    v = os.environ.get(name)
    v = v.strip() if v else ""
    return v or None


def is_windows_path(p):
    """Whether `p` is already in a form Windows can open - UNC or drive letter.

    The test that lets one variable carry either form: PAD_ROOT is a POSIX path
    inside WSL and, thanks to WSLENV's `/p`, the translated Windows path in the
    process WSL launches. Both are correct; only the reader differs.
    """
    return bool(p) and (p.startswith("\\\\") or p.startswith("//")
                        or (len(p) > 1 and p[1] == ":"))


def _wsl(args):
    """Run a program inside WSL, from Windows, and return its stdout or None.

    `wsl.exe -e <prog>` runs the program DIRECTLY, with no shell, and that is
    the whole point rather than a detail: with a shell in the way the arguments
    are re-parsed, and `$VAR` and `$(...)` both expand to nothing in that second
    pass. `printenv` and `wslpath` are used below for the same reason - neither
    needs a shell to do its job.
    """
    cmd = ["wsl.exe"]
    distro = _env("PAD_WSL_DISTRO")
    if distro:
        cmd += ["-d", distro]
    cmd += ["-e"] + list(args)
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=20,
                           creationflags=_CREATE_NO_WINDOW if _WIN else 0)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").strip() or None


def to_win(path):
    """A WSL path as Windows sees it, or `path` unchanged if it already is one.

    Asked of `wslpath`, never assembled here. Building `\\\\wsl.localhost\\` +
    a distro name + the path is the version this replaces, and it is wrong on
    any machine whose distro is not called Ubuntu and on any WSL old enough to
    still publish `\\\\wsl$`.
    """
    if not path or is_windows_path(path):
        return path
    if path in _WIN_CACHE:
        return _WIN_CACHE[path]
    _WIN_CACHE[path] = _wsl(["wslpath", "-w", path])
    return _WIN_CACHE[path]


def to_wsl(path):
    """A Windows path as WSL sees it, or `path` unchanged if it already is one.

    The mirror of to_win(), and needed for the same reason: the playfield window
    runs helper scripts INSIDE WSL through interop, and cannot hand them the
    Windows path it was itself loaded from. The literal this replaces assumed
    the checkout was under `/mnt/c/Users/david/...`.
    """
    if not path or not is_windows_path(path):
        return path
    key = "u:" + path
    if key in _WIN_CACHE:
        return _WIN_CACHE[key]
    _WIN_CACHE[key] = _wsl(["wslpath", "-u", path]) or path
    return _WIN_CACHE[key]


def wsl_home():
    """The WSL user's home directory, in POSIX form."""
    v = _env("PAD_WSL_HOME")
    if v:
        return v
    if not _WIN:
        return os.path.expanduser("~")
    return _wsl(["printenv", "HOME"])


def wsl_root():
    """The guest rootfs, in the form WSL uses.

    `~/spike2root` by default - which is where the extraction recipe in
    rootfs.sh puts it - and PAD_ROOT to move it.
    """
    p = _env("PAD_ROOT")
    if p and not is_windows_path(p):
        return p
    home = wsl_home()
    return home.rstrip("/") + "/spike2root" if home else None


def win_root():
    """The rootfs as Windows sees it."""
    p = _env("PAD_ROOT")
    if is_windows_path(p):
        return p                      # WSLENV's /p already did the work
    return to_win(wsl_root())


def root():
    """The rootfs, in the form THIS interpreter can open."""
    return win_root() if _WIN else wsl_root()


def rig():
    """The rig directory, in the form THIS interpreter can open.

    On Windows that is the checkout's own path - the playfield window is a
    Windows process started from a Windows checkout - so this is only ever
    translated when a WSL-side caller asks for the Windows form.
    """
    return RIG


def tables():
    """Where derived per-title data is cached, in the form this side can open.

    See the module header for why this is under the rootfs and not beside the
    scripts: one directory, both sides of the VM boundary, and outside git.
    """
    p = _env("PAD_TABLES")
    if p:
        return to_win(p) if _WIN else p
    r = root()
    return os.path.join(r, "dump", "tables") if r else None


def dump():
    """The host/guest shared area: padled, padsw, the audio FIFO, the tables."""
    r = root()
    return os.path.join(r, "dump") if r else None


def main():
    print("platform         : %s" % ("windows" if _WIN else "wsl/linux"))
    print("rig              : %s" % RIG)
    print("wsl home         : %s" % wsl_home())
    print("rootfs (wsl)     : %s" % wsl_root())
    if _WIN:
        print("rootfs (windows) : %s" % win_root())
    print("dump             : %s" % dump())
    print("tables           : %s" % tables())
    for name in ("PAD_ROOT", "PAD_TABLES", "PAD_WSL_DISTRO", "PAD_WSL_HOME"):
        if _env(name):
            print("  %-14s = %s" % (name, _env(name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
