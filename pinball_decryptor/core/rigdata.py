"""The rigs' work lives on a disk of its own, not inside the Linux we replace.

WHY THIS EXISTS.  core/runtime.py installs a Linux we build; replacing it means
`wsl --unregister`, which destroys that distro's entire filesystem.  The rigs
keep real work in there - games extracted from a user's cards, card caches of
several gigabytes, and SAVE-STATE SLOTS, which are something a person made and
cannot get back.  So every runtime version bump was a choice between stranding
the user's work and never bumping.

It is also the only way to give the disk back.  WSL 2.6.1 answers
`wsl --manage <distro> --set-sparse true` with "currently disabled due to
potential data corruption", so a distro's virtual disk NEVER shrinks: deleting
a 7 GB card cache inside it frees nothing at all.  The unit of reclaim has to
be a file Windows can delete, which is exactly what this is.

WHAT IT IS.  One expandable VHDX under LOCALAPPDATA, attached to the WSL VM by
name so it appears at the same path in EVERY distro (`wsl --mount --vhd
--name`), carrying one directory per rig.  The rigs already take their work
root from the environment - Spike 1's ``S1_WORK``, Spike 2's ``PAD_HOME``
("explicit PAD_HOME always wins", padpath.sh) - so nothing inside either rig
has to learn about this.

MEASURED, NOT ASSUMED, on Windows 11 Home with no Hyper-V module:

  * `diskpart` creates the VHDX UNELEVATED and exits 0 (New-VHD is a Hyper-V
    cmdlet and is simply absent there);
  * `wsl --mount --vhd` attaches it UNELEVATED - "The operation completed
    successfully";
  * inside the distro it is an ordinary block device: mkfs, mount, write, all
    at 1.5 GB/s rather than the 228 MB/s that /mnt/c manages.

So the app can do the whole thing without ever asking for administrator.
"""

import os
import subprocess
import sys
from typing import Optional

#: Where the disk is mounted INSIDE every WSL distro.  `wsl --mount --name`
#: puts it under /mnt/wsl, which WSL shares across distros - so the same path
#: is right whether a rig is running in our runtime or the machine's own.
MOUNT_NAME = "paddata"
MOUNT = "/mnt/wsl/" + MOUNT_NAME

#: EXPANDABLE, but the size is NOT free, and the number below is measured
#: rather than chosen for comfort.  `diskpart` creates a 4 MB file whatever
#: maximum it is given - but mkfs.ext4 then writes metadata into every one of
#: the volume's 128 MB block groups, and each of those touches materialises a
#: 2 MB block in the VHDX.  So an EMPTY disk costs about 4% of its nominal
#: size, and no mkfs tuning changes it (measured with -i, -J size, -m 0,
#: nodiscard and both lazy_*_init flags: identical to the defaults):
#:
#:      8 GB volume ->   420 MB    32 GB volume ->   900 MB
#:     16 GB volume ->   640 MB    64 GB volume ->  1444 MB
#:
#: 32 GB is the balance: it holds Spike 1's whole five-entry extraction cache
#: plus two or three Spike 2 card caches (those run about 7 GB each), for 900 MB
#: of overhead that is only ever paid by someone who is about to write
#: gigabytes anyway - the disk is created on a rig's first run, not at install.
MAX_MB = 32768

#: Below this, say so plainly rather than letting a rig die on ENOSPC halfway
#: through an extraction.
LOW_SPACE_BYTES = 3 * 1024 ** 3

#: One directory per rig, and the environment variable each rig already reads
#: to be told where its work goes: Spike 1's start.sh takes ``S1_WORK``, and
#: Spike 2's padpath.sh says "explicit PAD_HOME always wins".  So the rigs need
#: no change at all - they are simply told a different directory.
RIG_DIRS = {"spike1": "spike1", "spike2": "spike2"}
RIG_ENV = {"spike1": "S1_WORK", "spike2": "PAD_HOME"}

_CREATE_FLAGS = (subprocess.CREATE_NO_WINDOW
                 if sys.platform == "win32" else 0)


def disk_path() -> str:
    """The VHDX itself.  Beside the runtime, not inside it: the whole point is
    that removing one does not remove the other."""
    override = os.environ.get("PAD_DATA_DISK")
    if override:
        return override
    from . import wsl_place
    return os.path.join(wsl_place.data_dir(), "pad-data.vhdx")


def exists() -> bool:
    return os.path.isfile(disk_path())


# ---- the shared card store (PAD-651) -----------------------------------------
#: A SECOND disk, made the same way, holding the Spike 2 card cache for every
#: distro: `cardstore.ps1 create` (tools/spike2_emu) makes it, 400 GB
#: expandable, since the newest build of every title is ~320 GB of used
#: blocks - far more than the work disk above is sized for, and a unit of
#: reclaim of its own (delete the file, the cache is gone, the work disk is
#: not).  cardmount.sh keeps its cache at CARDS_MOUNT/cardcache whenever that
#: is a mount; the app's part is only to ATTACH it at a rig start, as it does
#: the work disk, so a WSL restart never silently sends a sweep back to D:.
#: Never created here: 400 GB is a decision the user makes with the script.
CARDS_MOUNT_NAME = "cards"
CARDS_MOUNT = "/mnt/wsl/" + CARDS_MOUNT_NAME
_CARDS_IS_MOUNTED = 'mountpoint -q "%s" && echo mounted || echo no' % CARDS_MOUNT


def cards_disk_path() -> str:
    override = os.environ.get("PAD_CARDS_DISK")
    if override:
        return override
    from . import wsl_place
    return os.path.join(wsl_place.data_dir(), "pad-cards.vhdx")


def cards_exists() -> bool:
    return os.path.isfile(cards_disk_path())


def cards_attached(distro: str, runner=None) -> bool:
    """Is the card store MOUNTED in the WSL VM right now?  Asked of the
    mountpoint, for the same reason :func:`attached` is."""
    run = runner or _run
    try:
        out = run(["bash", "-c", _CARDS_IS_MOUNTED], timeout=60, distro=distro)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "mounted" in _text(out.stdout)


#: The store's filesystem. ext4 as made by `cardstore.ps1 create`; XFS since
#: PAD-1453 (`cardstore.ps1 migrate`), whose reflinks let the library's LE and
#: Pro cards share their identical blocks - 431 GiB of cards in 189 GiB.
#: `wsl --mount` assumes ext4 unless told, so the type is written beside the
#: disk (``<vhdx>.fstype``) and, the file being moved without it (Manage disk
#: space > Move), the other type is tried when the first will not mount.
CARDS_FSTYPES = ("ext4", "xfs")


def cards_fstype() -> str:
    try:
        with open(cards_disk_path() + ".fstype", encoding="ascii") as f:
            t = f.read().strip()
        return t if t in CARDS_FSTYPES else "ext4"
    except OSError:
        return "ext4"


def attach_cards(distro: str, runner=None) -> None:
    run = runner or _run
    first = cards_fstype()
    tried = []
    for fs in [first] + [t for t in CARDS_FSTYPES if t != first]:
        out = run(["wsl.exe", "--mount", "--vhd", cards_disk_path(),
                   "--name", CARDS_MOUNT_NAME, "--type", fs])
        if out.returncode == 0:
            return
        tried.append("%s: %s" % (fs, _text(out.stdout).strip()
                                 or "exit %d" % out.returncode))
        # a failed mount leaves the disk attached: let it go before the next try
        run(["wsl.exe", "--unmount", cards_disk_path()])
    raise RuntimeError("could not attach the card store: %s" % "; ".join(tried))


def ensure_cards(distro: str, log=None, runner=None) -> Optional[str]:
    """Attach the card store if the file exists and it is not mounted.
    Returns the mountpoint when it is attached, None when there is no store
    (an ordinary install, or one made without it) - never an error for that:
    cardmount.sh then uses the per-distro cache as it always did."""
    if sys.platform != "win32" or not cards_exists():
        return None
    say = log or (lambda _m: None)
    if not cards_attached(distro, runner=runner):
        say("Attaching the Spike 2 card store (%s)…" % cards_disk_path())
        attach_cards(distro, runner=runner)
    return CARDS_MOUNT


# ---- a user's card cache, on a disk of its own (PAD-1459) ---------------------
#: A user has no store (`cardstore.ps1` is a developer's script), so their
#: Spike 2 cards were cached inside a Linux disk - and a WSL disk never gives
#: space back to C:. The cache is mostly the same blocks over and over: a
#: custom build is the stock card with a few files changed, an LE card shares
#: 73-80% with its Pro (PAD-1453: David's 101 GiB of cache held 28.8 GiB of
#: unique blocks). So the app gives it a THIRD disk, made the way the work disk
#: is (diskpart, `wsl --mount --vhd`, no administrator), but XFS with reflink:
#: cardmount.sh caches into it, shares each new copy's identical blocks with
#: what is there (storededupe.py, after the copy, off the boot path), and
#: counts its limit by the disk's real use - so the same 64 GB holds about
#: twice the builds. Never made where the store exists: that one holds the
#: cache already.
CACHE_DISK_MOUNT_NAME = "padcache"
CACHE_DISK_MOUNT = "/mnt/wsl/" + CACHE_DISK_MOUNT_NAME

#: The disk's maximum: the cache's limit plus the room one more card's copy
#: needs before its blocks are shared (a compact copy is 6-10 GB; 32 GB covers
#: the largest card's whole image). Expandable, so the maximum costs nothing
#: until it is used; XFS writes only a few MB of metadata when it is made
#: (measured: an empty 96 GB volume is a 138 MB file), not ext4's 4%.
CACHE_DISK_ROOM_GB = 32
#: cardmount.sh's own default limit on a disk of its own (PAD_CACHE_MAX_GB).
CACHE_LIMIT_GB = 64

_CACHE_DISK_IS_MOUNTED = ('mountpoint -q "%s" && echo mounted || echo no'
                          % CACHE_DISK_MOUNT)


def cache_disk_path() -> str:
    override = os.environ.get("PAD_CACHE_DISK")
    if override:
        return override
    from . import wsl_place
    return os.path.join(wsl_place.data_dir(), "pad-cardcache.vhdx")


def cache_disk_exists() -> bool:
    return os.path.isfile(cache_disk_path())


def cache_disk_size_gb(limit_gb: int = 0, used_gb: int = 0) -> int:
    """The maximum to make the disk with: room for the cache's limit (or
    for what the old cache already holds, if that is more) and one more
    card's copy."""
    return max(int(limit_gb or CACHE_LIMIT_GB), int(used_gb or 0)) \
        + CACHE_DISK_ROOM_GB


def cache_disk_attached(distro: str, runner=None) -> bool:
    run = runner or _run
    try:
        out = run(["bash", "-c", _CACHE_DISK_IS_MOUNTED], timeout=60,
                  distro=distro)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "mounted" in _text(out.stdout)


def attach_cache_disk(runner=None) -> None:
    run = runner or _run
    out = run(["wsl.exe", "--mount", "--vhd", cache_disk_path(),
               "--name", CACHE_DISK_MOUNT_NAME, "--type", "xfs"])
    if out.returncode != 0:
        # a failed mount leaves the disk attached: let it go
        run(["wsl.exe", "--unmount", cache_disk_path()])
        raise RuntimeError(
            "could not attach the card cache disk: %s"
            % (_text(out.stdout).strip() or "exit %d" % out.returncode))


def ensure_cache_disk(distro: str, mkfs_argv, size_gb: int = 0, log=None,
                      runner=None) -> Optional[str]:
    """Make the card cache disk if it does not exist, and attach it.

    *mkfs_argv* is how to run ``cachedisk.sh mkfs`` as root in *distro*
    (the rig's own folder is the caller's to know); the device is appended.
    Returns the mountpoint, or None where it does not apply: not Windows, or
    the card store exists (it is the cache there). Raises with a sentence if
    a step fails, and a disk that was never formatted is deleted again, so
    the next Start tries afresh rather than mounting an empty file."""
    if sys.platform != "win32" or cards_exists():
        return None
    say = log or (lambda _m: None)
    run = runner or _run
    path = cache_disk_path()
    if not cache_disk_exists():
        gb = size_gb or cache_disk_size_gb()
        say("Giving the Spike 2 card cache a disk of its own (up to %d GB; "
            "identical blocks are stored once)…" % gb)
        _create_vhdx(path, gb * 1024, run)
        try:
            _format_new_disk(distro, runner=runner, path=path,
                             mkfs=lambda dev: list(mkfs_argv) + [dev],
                             what="the card cache disk")
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
    if not cache_disk_attached(distro, runner=runner):
        attach_cache_disk(runner=runner)
    return CACHE_DISK_MOUNT


def cache_disk_delete(runner=None) -> bool:
    run = runner or _run
    run(["wsl.exe", "--unmount", cache_disk_path()])
    try:
        os.remove(cache_disk_path())
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def size_on_disk() -> int:
    """Bytes the disk is actually costing, which is what a user deciding
    whether to delete it needs to know."""
    try:
        return os.path.getsize(disk_path())
    except OSError:
        return 0


def _run(args, timeout=300, distro=None):
    if distro:
        args = ["wsl.exe", "-d", distro, "-u", "root", "-e"] + args
    env = dict(os.environ)
    env["WSL_UTF8"] = "1"
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=env,
                          creationflags=_CREATE_FLAGS)


def _text(raw) -> str:
    raw = raw or b""
    if b"\x00" in raw:
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def create(runner=None) -> None:
    """Make the VHDX with diskpart, which needs no administrator and no
    Hyper-V - the two things a Windows Home machine does not have."""
    _create_vhdx(disk_path(), MAX_MB, runner or _run)


def _create_vhdx(path, max_mb, run) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    script = os.path.join(os.path.dirname(path), "create.dpt")
    with open(script, "w", encoding="ascii") as f:
        f.write('create vdisk file="%s" maximum=%d type=expandable\nexit\n'
                % (path, max_mb))
    try:
        out = run(["cmd", "/c", "diskpart", "/s", script])
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    # diskpart's own exit code is the honest signal here; its console output is
    # not captured reliably when it is driven from a script.
    if out.returncode != 0 or not os.path.isfile(path):
        raise RuntimeError(
            "could not create the emulator's data disk at %s (%s). Nothing "
            "else was changed." % (path, _text(out.stdout).strip()
                                   or "diskpart exit %s" % out.returncode))


#: Ask whether MOUNT is a real mount rather than an ordinary directory.
#: ``findmnt`` with a bare path matches only an actual mountpoint; where it is
#: missing, a directory sitting on a different device from its parent is one.
#: Prints "mounted" or nothing, so the caller reads the text and not an exit
#: code that a missing tool would also produce.
#:
#: ``[ -d ]`` FIRST IN THE FALLBACK, and it is not decoration.  After a full WSL
#: restart ``/mnt/wsl`` is a fresh tmpfs and the mountpoint DOES NOT EXIST: its
#: ``stat`` prints nothing, nothing differs from the parent's device number, and
#: the comparison alone answered "mounted" for a disk attached nowhere - so Start
#: skipped the re-attach and handed the rig a path that was not there (measured
#: on David's PC, 2026-09-18, with every distro stopped beforehand).  A directory
#: that does not exist is not a mount.
_IS_MOUNTED = (
    'if findmnt -no FSTYPE "%s" >/dev/null 2>&1; then echo mounted; '
    'elif [ -d "%s" ] && [ "$(stat -c %%d "%s" 2>/dev/null)" != '
    '"$(stat -c %%d "$(dirname "%s")" 2>/dev/null)" ]; then echo mounted; fi'
    % (MOUNT, MOUNT, MOUNT, MOUNT))


def attached(distro: str, runner=None) -> bool:
    """Is the disk MOUNTED in the WSL VM right now?

    Asked of the mountpoint rather than remembered: `wsl --shutdown`, a reboot
    and WSL's own idle timeout all drop it, and every one of those looks
    exactly like a working machine until something tries to write.

    And asked as "is this a mount", NOT as "does this directory exist".  The
    two are not the same here and the difference is a whole failed session:
    ``/mnt/wsl`` is a tmpfs, so once :func:`ensure` has made the per-rig
    directories under it, those directories SURVIVE the disk being dropped.
    A ``test -d`` then says the disk is attached when it is not, ``attach`` is
    skipped, and the rig is handed a path in RAM — which the rig refuses,
    correctly, leaving a user who has done nothing wrong unable to start the
    emulator until they restart WSL by hand (David's machine after a Windows
    reboot, 2026-09-10)."""
    run = runner or _run
    try:
        out = run(["bash", "-c", _IS_MOUNTED], timeout=60, distro=distro)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "mounted" in _text(out.stdout)


def _devices(distro: str, runner) -> set:
    out = (runner or _run)(["lsblk", "-ndo", "NAME"], timeout=60, distro=distro)
    return {n.strip() for n in _text(out.stdout).splitlines() if n.strip()}


def _format_new_disk(distro: str, runner=None, path=None, mkfs=None,
                     what="the data disk") -> None:
    """A freshly created VHDX has no filesystem, and `wsl --mount` without
    --bare would refuse to mount it.  So it goes on BARE first, gets an ext4
    on it, and comes back properly the second time.

    The device is found by DIFFING the block devices around the attach rather
    than by matching a size: a machine can have another blank disk of any size,
    and formatting the wrong one is not a mistake worth risking to save a
    round trip."""
    run = runner or _run
    path = path or disk_path()
    before = _devices(distro, run)
    out = run(["wsl.exe", "--mount", "--vhd", path, "--bare"])
    if out.returncode != 0:
        raise RuntimeError("could not attach %s: %s"
                           % (what, _text(out.stdout).strip() or "exit %d" % out.returncode))
    try:
        new = _devices(distro, run) - before
        if len(new) != 1:
            raise RuntimeError(
                "could not tell which disk was just attached (%s) - nothing "
                "was formatted" % (", ".join(sorted(new)) or "none appeared"))
        dev = "/dev/" + new.pop()
        if mkfs is not None:
            # the card cache disk (PAD-1459): XFS, through the rig's own
            # cachedisk.sh, which brings the pinned mkfs.xfs
            out = run(mkfs(dev), timeout=900, distro=distro)
            if out.returncode != 0:
                raise RuntimeError("could not put a filesystem on %s: %s"
                                   % (what, (_text(out.stderr) or _text(out.stdout)).strip()))
            return
        # THROUGH bash, WITH AN EXPLICIT PATH.  `wsl -e <prog>` execs
        # directly with a minimal PATH, and mkfs.ext4 lives in /usr/sbin - so
        # the direct form fails with "execvpe(mkfs.ext4) failed: No such file
        # or directory" on a machine that has it.
        # THE DEFAULTS COST 4.6 GB ON AN EMPTY DISK, measured.  ext4 sizes
        # its inode tables for one inode per 16 KB, which on a 256 GB volume
        # is 16 million inodes and about 4 GB of tables - and every one of
        # those blocks gets WRITTEN, so an expandable VHDX materialises them
        # immediately.  This disk holds extractions and card caches: thousands
        # of large files, not millions of small ones.
        #   -i 1048576   one inode per MB - 256k inodes, ~64 MB of tables
        #   -J size=64   a 64 MB journal instead of a gigabyte
        #   -m 0         no blocks reserved for root; nothing here is a system
        #   lazy_*_init  let the kernel finish the tables in the background
        #                rather than writing them all at format time
        out = run(["bash", "-c",
                   'PATH=/usr/sbin:/sbin:$PATH mkfs.ext4 -q -F -L PADDATA '
                   '-i 1048576 -J size=64 -m 0 '
                   '-E lazy_itable_init=1,lazy_journal_init=1 "%s"'
                   % dev], timeout=600, distro=distro)
        if out.returncode != 0:
            raise RuntimeError("could not put a filesystem on the data disk: %s"
                               % _text(out.stderr).strip())
    finally:
        run(["wsl.exe", "--unmount", path])


def attach(distro: str, runner=None) -> None:
    """Attach by NAME, so the same path exists in every distro."""
    run = runner or _run
    out = run(["wsl.exe", "--mount", "--vhd", disk_path(),
               "--name", MOUNT_NAME])
    if out.returncode != 0:
        raise RuntimeError(
            "could not attach the emulator's data disk: %s"
            % (_text(out.stdout).strip() or "exit %d" % out.returncode))


def ensure(distro: str, log=None, runner=None) -> Optional[str]:
    """Make the disk exist, be attached, and hold a directory per rig.

    Returns the mountpoint, or None where this cannot apply (not Windows).
    Raises with a sentence for the log if a step fails - a rig started against
    a half-made data disk would write into a directory that vanishes on the
    next restart."""
    if sys.platform != "win32":
        return None
    say = log or (lambda _m: None)
    run = runner or _run
    if not exists():
        say("Setting aside a disk for the emulator's work (extractions, "
            "cards, save states)…")
        create(runner=runner)
        _format_new_disk(distro, runner=runner)
    if not attached(distro, runner=runner):
        attach(distro, runner=runner)
    # The rigs run as the desktop user for everything they can, so the
    # directories they write into have to belong to that user - the mount
    # itself is root's.
    run(["bash", "-c",
         'set -e; u="$(getent passwd 1000 | cut -d: -f1)"; '
         'for d in %s; do mkdir -p "%s/$d"; chown "$u": "%s/$d"; done'
         % (" ".join(RIG_DIRS.values()), MOUNT, MOUNT)],
        timeout=120, distro=distro)
    return MOUNT


def free_bytes(distro: str, runner=None) -> int:
    """What is left on the disk, so a run can say "you are nearly out" before
    an extraction dies halfway through rather than after."""
    run = runner or _run
    try:
        out = run(["bash", "-c", "df -B1 --output=avail %s | tail -1" % MOUNT],
                  timeout=60, distro=distro)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    try:
        return int(_text(out.stdout).strip().split()[-1])
    except (ValueError, IndexError):
        return 0


def work_dir(rig: str) -> Optional[str]:
    """Where a rig's work goes, or None for a rig that has no place here."""
    name = RIG_DIRS.get(rig)
    return MOUNT + "/" + name if name else None


def rig_env(rig: str, ready: bool = True) -> list:
    """The one environment entry that moves a rig's work onto this disk.

    Empty when the disk is not ready, and that is the whole fallback: the rig
    then uses the same default it always has, inside whatever distro it is
    running in.  Nothing half-moves."""
    var, where = RIG_ENV.get(rig), work_dir(rig)
    if not ready or not var or not where:
        return []
    return ["%s=%s" % (var, where)]


def detach(runner=None) -> bool:
    run = runner or _run
    out = run(["wsl.exe", "--unmount", disk_path()])
    return out.returncode == 0


def delete(runner=None) -> bool:
    """Detach and remove the file.  THIS is the reclaim: files deleted inside
    a WSL disk free nothing, because WSL 2.6.1 refuses to shrink one."""
    detach(runner=runner)
    try:
        os.remove(disk_path())
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
