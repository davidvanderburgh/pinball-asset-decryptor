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
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(base, "pinball_decryptor", "data", "pad-data.vhdx")


def exists() -> bool:
    return os.path.isfile(disk_path())


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
    return subprocess.run(args, capture_output=True, timeout=timeout, env=env,
                          creationflags=_CREATE_FLAGS)


def _text(raw) -> str:
    raw = raw or b""
    if b"\x00" in raw:
        return raw.decode("utf-16-le", "replace")
    return raw.decode("utf-8", "replace")


def create(runner=None) -> None:
    """Make the VHDX with diskpart, which needs no administrator and no
    Hyper-V - the two things a Windows Home machine does not have."""
    run = runner or _run
    path = disk_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    script = os.path.join(os.path.dirname(path), "create.dpt")
    with open(script, "w", encoding="ascii") as f:
        f.write('create vdisk file="%s" maximum=%d type=expandable\nexit\n'
                % (path, MAX_MB))
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
_IS_MOUNTED = (
    'if findmnt -no FSTYPE "%s" >/dev/null 2>&1; then echo mounted; '
    'elif [ "$(stat -c %%d "%s" 2>/dev/null)" != '
    '"$(stat -c %%d "$(dirname "%s")" 2>/dev/null)" ]; then echo mounted; fi'
    % (MOUNT, MOUNT, MOUNT))


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


def _format_new_disk(distro: str, runner=None) -> None:
    """A freshly created VHDX has no filesystem, and `wsl --mount` without
    --bare would refuse to mount it.  So it goes on BARE first, gets an ext4
    on it, and comes back properly the second time.

    The device is found by DIFFING the block devices around the attach rather
    than by matching a size: a machine can have another blank disk of any size,
    and formatting the wrong one is not a mistake worth risking to save a
    round trip."""
    run = runner or _run
    before = _devices(distro, run)
    out = run(["wsl.exe", "--mount", "--vhd", disk_path(), "--bare"])
    if out.returncode != 0:
        raise RuntimeError("could not attach the data disk: %s"
                           % (_text(out.stdout).strip() or "exit %d" % out.returncode))
    try:
        new = _devices(distro, run) - before
        if len(new) != 1:
            raise RuntimeError(
                "could not tell which disk was just attached (%s) - nothing "
                "was formatted" % (", ".join(sorted(new)) or "none appeared"))
        dev = "/dev/" + new.pop()
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
        run(["wsl.exe", "--unmount", disk_path()])


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
