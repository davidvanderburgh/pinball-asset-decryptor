"""Grow files inside an ext4 partition by copying larger replacements over
them, letting the Linux kernel's ext4 driver do the block allocation.

Spike 2 patching is otherwise size-neutral: a replacement asset has to fit the
original file's byte slot, because we edit the card image at raw disk offsets
without a filesystem driver.  That crushes an oversized video into its (often
tiny) slot — which both looks bad and trips the game's content validation.

The stock manufacturer tools instead **grow** the asset file: same on-card
path, more bytes.  Reproducing that by hand would mean
writing an ext4 allocator (extent-tree edits, block/inode bitmaps, group + super
accounting) — the exact code that, if wrong, yields a card that won't mount.

So we don't.  On Windows/Linux we loop-mount the partition through the
platform's Linux (WSL2 on Windows, native elsewhere) and ``cp`` the full-size
file over the asset; the kernel grows the inode correctly and the filesystem
stays valid (verified with ``e2fsck``).  macOS has no ext4 driver and a sealed
read-only root, so there we go through e2fsprogs' ``debugfs`` instead (the
same battle-tested path the JJP plugin uses): ``kill_file`` + ``rm`` +
``write`` per asset against the partition opened at its raw offset
(``image.raw?offset=N``), then one ``e2fsck -fy`` to reconcile the free-count
accounting debugfs leaves stale.  This module is the thin, well-guarded
wrapper around both.
"""

import base64
import os
import re
import shlex
import subprocess
import sys

from .executor import create_executor


def _mb(n):
    return "%.0f MB" % (float(n) / 10 ** 6)


def no_space_message(need=None, avail=None, items=(), what="file(s)"):
    """The "it doesn't fit" message, with the numbers a user can act on.

    The scripts have always computed the shortfall and then thrown it away, so
    a modder whose 542 replaced videos and grown sound bank overran the card
    was told only that there was "not enough free space" — after twenty-odd
    minutes of encoding, with nothing to say how far over he was or what was
    taking the room (PAD-176).  The card's games partition is the size Stern
    made it for the original's card, so the answer is "take something out" -
    or build for a bigger SD card, which the Stern engine says after this
    sentence when it could help (engine._bigger_card_hint, card_size.py).

    *items* are ``(growth_in_bytes, card_path)`` pairs.  The biggest few are
    named because a mod's space is rarely spread evenly across its files.
    """
    msg = ("Not enough free space on the card's games partition to write the "
           "larger %s. They keep their stock content on the card." % what)
    if need is None or avail is None:
        return msg
    msg += (" This build is %s over: it grows files by %s and the partition "
            "has %s free, so something has to come out (fewer or smaller "
            "replacements, or fewer longer sounds)."
            % (_mb(max(need - avail, 0)), _mb(need), _mb(avail)))
    big = sorted(items, reverse=True)[:5]
    if big:
        msg += ("  Biggest: %s."
                % ", ".join("%s (+%s)" % (rel, _mb(d)) for d, rel in big))
    return msg


def parse_space_report(text):
    """``(need, avail, [(growth, card_path), ...])`` from a script's output.

    ``(None, None, [])`` when the markers aren't there, which is what an
    older script or a failure before the accounting ran looks like."""
    need = avail = None
    m = re.search(r"PAD_GROW_ENOSPC need=(\d+) avail=(\d+)", text or "")
    if m:
        need, avail = int(m.group(1)), int(m.group(2))
    items = [(int(d), rel) for d, rel in
             re.findall(r"PAD_GROW_ITEM (\d+) (\S+)", text or "")]
    return need, avail, items


class Ext4GrowError(Exception):
    """A file-growth operation failed (with a user-facing message).

    ``grown`` carries how many files had already grown successfully before
    the failure, so callers can report honest counts."""

    def __init__(self, message, grown=0):
        super().__init__(message)
        self.grown = grown


class Ext4GrowUnavailable(Ext4GrowError):
    """The platform can't mount ext4 (no WSL / no Linux) — caller should fall
    back to size-neutral behaviour and warn."""


class Ext4GrowNoSpace(Ext4GrowError):
    """The partition hasn't room for the requested growth.  Split out from the
    generic error so a caller can word it for what IT was growing — the base
    message says "file(s)" because the same path now carries videos, a
    re-serialised scene, a rebuilt game program and a grown sound bank, and it
    is wrong for e.g. a Partition Explorer swap on the OS partition.

    ``need`` and ``avail`` are the growth and the free space in bytes, and
    ``items`` the ``(growth, card_path)`` pairs, as the check measured them
    (``None`` / empty when it didn't get that far), so a caller can work out
    what would fit - the Stern engine names the one SD card size that does
    (engine._bigger_card_hint)."""

    def __init__(self, message, grown=0, need=None, avail=None, items=()):
        super().__init__(message, grown=grown)
        self.need = need
        self.avail = avail
        self.items = list(items or ())


def _no_space(text, grown=0):
    """The :class:`Ext4GrowNoSpace` for a script's failure output *text*."""
    need, avail, items = parse_space_report(text)
    return Ext4GrowNoSpace(no_space_message(need, avail, items), grown=grown,
                           need=need, avail=avail, items=items)


# Can the executor's Linux hand out a loop device?  ``losetup -f`` only ASKS
# for a free device (nothing is attached), so the probe is side-effect free —
# but it is the exact call ``_bash_script`` opens with, so it fails when and
# only when the mount would.  It matters because "WSL answers as root" is NOT
# the same thing: a WSL 1 distro passes ``echo ok`` while owning zero loop
# devices, which is how a 489-video write shipped nothing after the card's
# .sidx had already been rewritten (PAD-13).  The modprobe is a cheap
# remediation for a native kernel whose loop module simply isn't loaded, and
# harmless where the driver is built in (WSL2) or absent entirely (WSL1).
# The Stern prerequisite strip runs this same string (manufacturer.py) so the
# GUI indicator can never disagree with what the write path actually needs.
LOOP_PROBE = ("modprobe loop >/dev/null 2>&1 || true; "
              "losetup -f >/dev/null && echo ok")


def loop_unavailable_reason(ex, what="card image"):
    """``None`` when *ex*'s Linux can hand out a loop device, else a
    user-facing reason naming what to look at.  On Windows the classic culprit
    is a WSL 1 distro (no loop devices, ever), but a distro that has stopped
    starting fails the same probe — the message walks the user through telling
    them apart instead of leaving a bare losetup error to search for, and
    instead of naming one of them as the answer (PAD-113).

    Public because the JJP ISO flows need the same verdict: they loop-mount
    the ext4 image they extract from the .iso, so a distro without loop
    devices fails them exactly as it fails a Stern grow (PAD-45).  *what*
    names the thing that couldn't be mounted, since "card image" is Stern's
    noun and a JJP user is looking at an .iso."""
    try:
        ex.run(LOOP_PROBE, timeout=60)
        return None
    except Exception as e:  # noqa: BLE001 — executor raises CommandError
        lines = [ln.strip() for ln in str(e).splitlines() if ln.strip()]
        detail = next((ln for ln in lines if "losetup" in ln),
                      lines[-1] if lines else "losetup -f failed")
        if sys.platform == "win32":
            # NEVER LEAD WITH A GUESS.  "This usually means WSL 1" read as a
            # diagnosis: the reporter checked (VERSION 2), ran the conversion
            # anyway, was told the distro was already version 2, and went on
            # to upgrade the whole distro in place hunting the fault it named
            # (PAD-113).  Three different machines fail this way and one
            # command separates them, so ask for that instead of picking one.
            # The prerequisite strip diagnoses the same states from the app,
            # where it can run the checks itself (prereqs._probe_wsl); this
            # runs mid-pipeline and stays pure.
            return ("WSL can't create a loop device to mount the %s (%s). "
                    "Look at the distro before changing anything: 'wsl -l -v' "
                    "in PowerShell. VERSION 1 has no loop devices and has to "
                    "be converted with 'wsl --set-version <name> 2'. VERSION "
                    "2 is not a version problem: run 'wsl --shutdown' and try "
                    "again. If even 'wsl -d <name> -- echo ok' fails, the "
                    "distro itself has stopped starting and no package or "
                    "conversion will help" % (what, detail))
        return ("this system can't create a loop device to mount the %s "
                "(%s); a loop device needs root, so run the app as root or "
                "with passwordless sudo, load the loop module (modprobe loop) "
                "or reboot, then try again" % (what, detail))


#: Where e2fsprogs keeps its binaries off a user's PATH: macOS (Homebrew keg-only,
#: MacPorts) and native Linux (Debian's /sbin and /usr/sbin are root's PATH only).
E2FSPROGS_DIRS = ("/opt/homebrew/opt/e2fsprogs/sbin",     # Homebrew ARM
                  "/usr/local/opt/e2fsprogs/sbin",        # Homebrew Intel
                  "/opt/local/sbin",                      # MacPorts
                  "/sbin", "/usr/sbin")                   # Linux (PAD-314)


def _find_e2fsprogs():
    """Locate the e2fsprogs binaries: macOS keeps them keg-only (Homebrew) and a
    Linux user's PATH leaves out /sbin, where Debian puts them.

    Returns ``{"debugfs": path, "e2fsck": path}`` or ``None`` if either is
    missing.  dumpe2fs is deliberately NOT used: 1.47.x resolves its device
    argument through blkid WITHOUT first splitting the ``?offset=`` suffix
    (unlike e2fsck, which does), so ``dumpe2fs image.raw?offset=N`` dies with
    "Unable to resolve '-h'" — free space is read via ``debugfs stats -h``
    instead, which never goes through blkid.
    """
    import shutil
    dirs = E2FSPROGS_DIRS
    tools = {}
    for name in ("debugfs", "e2fsck"):
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                tools[name] = p
                break
        else:
            p = shutil.which(name)
            if not p:
                return None
            tools[name] = p
    return tools


#: How to install e2fsprogs, per platform (the debugfs route's one need)
E2FSPROGS_HINT = {"darwin": "brew install e2fsprogs",
                  "linux": "sudo apt install e2fsprogs (Debian/Ubuntu), or your distro's "
                           "e2fsprogs package"}


def uses_debugfs(platform=None):
    """Does this platform write into the card image with e2fsprogs' debugfs instead
    of a loop mount? macOS always has; native Linux since PAD-314 (Ales): the loop
    mount needs root, which a GUI app has no terminal to ask sudo for, so every build
    on a Linux desktop left its new files off the card. debugfs writes a user's own
    image file as the user."""
    p = platform or sys.platform
    return p == "darwin" or p.startswith("linux")


def available():
    """``(ok, message)`` — whether ext4 growth can run on this platform."""
    if uses_debugfs():
        if _find_e2fsprogs() is None:
            return False, ("e2fsprogs isn't installed — install it with: %s"
                           % E2FSPROGS_HINT["darwin" if sys.platform == "darwin" else "linux"])
        return True, "macOS debugfs" if sys.platform == "darwin" else "Linux debugfs"
    try:
        ex = create_executor()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    ok, msg = ex.check_available()
    if not ok:
        return False, msg
    reason = loop_unavailable_reason(ex)
    if reason:
        return False, reason
    return True, msg


#: The one directory a delivery may CREATE: a scene's ``scene.assets``, when the scene's own
#: directory is there (item 164: a clip grafted into The Munsters' HUD scene, which has no
#: asset files of its own). Any other missing directory still stops the delivery by name.
MAKE_DIR = "scene.assets"


def _makes_dir(card_rel):
    """The ``(dir, its parent)`` a job may create, or ``None``."""
    parts = card_rel.strip("/").split("/")
    if len(parts) >= 3 and parts[-2] == MAKE_DIR:
        return "/".join(parts[:-1]), "/".join(parts[:-2])
    return None


def _bash_script(loop_off, jobs_exec, image_exec):
    """Compose the mount → free-space check → cp → sync → unmount script.

    *jobs_exec* is ``[(card_rel, src_exec_path), ...]`` with exec-side paths.
    Everything is shell-quoted; the script cleans up its loop device and mount
    on any exit via a trap so a mid-run failure never leaves the card mounted.
    """
    lines = [
        "set -e",
        "IMG=%s" % shlex.quote(image_exec),
        "OFF=%d" % loop_off,
        "LOOP=",
        # A fresh temp dir as the mountpoint — /mnt is not universally
        # writable (and does not even exist on some hosts).
        "MP=$(mktemp -d /var/tmp/pad_grow_XXXXXX)",
        # Clean up loop + mount no matter how we exit.
        # syncfs on THIS filesystem, never a bare `sync`: under WSL2 a global sync also
        # flushes the virtiofs mounts of the Windows drives and can park in D state for
        # good (2026-09-16: a card build hung 15 minutes after its copies had landed).
        'cleanup() { sync -f "$MP" 2>/dev/null; umount "$MP" 2>/dev/null || true; '
        '[ -n "$LOOP" ] && losetup -d "$LOOP" 2>/dev/null || true; '
        'rmdir "$MP" 2>/dev/null || true; }',
        "trap cleanup EXIT",
        'LOOP=$(losetup --find --show -o "$OFF" "$IMG")',
        'mount "$LOOP" "$MP"',
        # Sum the net growth (new size - current size) and compare to free bytes
        # on the mounted filesystem, so we fail clearly instead of ENOSPC
        # mid-copy (which could leave a truncated asset).
        "need=0",
    ]
    for card_rel, src in jobs_exec:
        tgt = '"$MP"/' + shlex.quote(card_rel)
        s = shlex.quote(src)
        lines.append(
            'cur=$( [ -f %s ] && stat -c%%s %s || echo 0 ); '
            'new=$(stat -c%%s %s); d=$((new-cur)); '
            '[ "$d" -gt 0 ] && { need=$((need+d)); '
            'echo "PAD_GROW_ITEM $d %s"; } || true'
            % (tgt, tgt, s, shlex.quote(card_rel)))
    lines += [
        "avail=$(df -B1 --output=avail \"$MP\" | tail -1 | tr -d ' ')",
        'if [ "$need" -gt "$avail" ]; then '
        'echo "PAD_GROW_ENOSPC need=$need avail=$avail" >&2; exit 3; fi',
        'echo "PAD_GROW_SPACE need=$need avail=$avail"',
    ]
    for i, (card_rel, src) in enumerate(jobs_exec):
        tgt = '"$MP"/' + shlex.quote(card_rel)
        made = _makes_dir(card_rel)
        if made:
            lines.append('if [ ! -e "$MP"/%s ] && [ -d "$MP"/%s ]; then mkdir "$MP"/%s; '
                         'chown --reference="$MP"/%s "$MP"/%s; chmod --reference="$MP"/%s "$MP"/%s; fi'
                         % (shlex.quote(made[0]), shlex.quote(made[1]), shlex.quote(made[0]),
                            shlex.quote(made[1]), shlex.quote(made[0]), shlex.quote(made[1]),
                            shlex.quote(made[0])))
        lines.append(
            'if [ ! -e "$(dirname %s)" ]; then '
            'echo "PAD_GROW_NODIR %s" >&2; exit 4; fi' % (tgt, shlex.quote(card_rel)))
        lines.append("cp %s %s" % (shlex.quote(src), tgt))
        lines.append('echo "PAD_GROW_OK %d %s"' % (i, shlex.quote(card_rel)))
    lines += ['sync -f "$MP"', 'echo "PAD_GROW_DONE"']
    return "\n".join(lines)


def grow_files(image_path, part_offset, jobs, log=None, cancel=None,
               timeout=1800):
    """Copy each ``(card_rel, host_src_path)`` in *jobs* over its file inside
    the ext4 partition at *part_offset* in *image_path*, growing the inode.

    *card_rel* is the ``/``-relative path inside the partition (no leading
    slash); *host_src_path* is a full-size source file on the host.  Returns
    the number of files grown.  Raises :class:`Ext4GrowUnavailable` when the
    platform can't mount ext4 (caller should fall back), or
    :class:`Ext4GrowError` on any mount/copy failure.
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    # A job whose source file has gone missing used to be dropped here without
    # a word, and the caller read the resulting "0 grown" as an ordinary
    # failure.  That is how a deleted scratch file turned into cards that had
    # their .sidx already rewritten for a firmware which was never copied on
    # (see engine._compute_patches' grow_work note).  Never drop one quietly.
    missing = [rel for rel, src in jobs if not (src and os.path.isfile(src))]
    for rel in missing:
        log("Can't write %s onto the card: the prepared file is missing from "
            "the build's scratch space. This is a bug — please report it."
            % rel, "error")
    jobs = [(rel.lstrip("/"), src) for rel, src in jobs
            if src and os.path.isfile(src)]
    if not jobs:
        if missing:
            raise Ext4GrowError(
                "None of the %d prepared file(s) could be found on disk when "
                "it was time to copy them onto the card." % len(missing))
        return 0

    if uses_debugfs():                   # macOS, and native Linux (PAD-314)
        return _grow_files_debugfs(image_path, part_offset, jobs, log, cancel,
                                   timeout)

    ex = create_executor()
    ok, msg = ex.check_available()
    if not ok:
        raise Ext4GrowUnavailable(
            "Can't grow files on this system: %s. The affected "
            "file(s) keep their stock content on the card." % msg)
    # Re-checked here (not only in available()) so a caller that skipped the
    # planning-time check still degrades to the graceful Unavailable path —
    # a loop-less host used to reach losetup inside the mount script and come
    # back as a raw Ext4GrowError with no hint at the fix (PAD-13).
    reason = loop_unavailable_reason(ex)
    if reason:
        raise Ext4GrowUnavailable(
            "Can't grow files on this system: %s. The affected "
            "file(s) keep their stock content on the card." % reason)

    image_exec = ex.to_exec_path(image_path)
    jobs_exec = [(rel, ex.to_exec_path(src)) for rel, src in jobs]

    log("Growing %d file(s) to full size via the Linux filesystem "
        "driver..." % len(jobs), "info")
    script = _bash_script(part_offset, jobs_exec, image_exec)
    # Ship the script through a base64 temp FILE, not the command line:
    #  * base64 (pure ASCII) survives wsl.exe's argument mangling, which would
    #    otherwise corrupt the script's shell quoting (``-o "$OFF"`` -> ``""``);
    #  * a file avoids the Windows command-line length limit, which a run of
    #    dozens of copy commands blows past (WinError 206).
    import tempfile
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    fd, tmp = tempfile.mkstemp(suffix=".b64", prefix="pad_grow_")
    try:
        os.write(fd, b64.encode("ascii"))
        os.close(fd)
        tmp_exec = ex.to_exec_path(tmp)
        out = ex.run("base64 -d < %s | bash" % shlex.quote(tmp_exec),
                     timeout=timeout)
    except Exception as e:  # noqa: BLE001 — executor raises CommandError
        text = str(e)
        # Files copied before a mid-run failure DID land (each prints its
        # PAD_GROW_OK marker first) — surface that count to the caller.
        n_ok = text.count("PAD_GROW_OK ")
        if "PAD_GROW_ENOSPC" in text:
            raise _no_space(text, grown=n_ok) from e
        raise Ext4GrowError(
            "Couldn't grow files:\n%s" % text, grown=n_ok) from e
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    grown = out.count("PAD_GROW_OK ")
    for line in out.splitlines():
        if line.startswith("PAD_GROW_OK "):
            rel = line.split(" ", 2)[-1]
            log("  grew %s" % rel, "info")
    log("Grew %d file(s) to full size (filesystem left valid)." % grown,
        "success")
    return grown


# --------------------------------------------------------------------------
# macOS: no ext4 driver, no loop devices — go through e2fsprogs' debugfs.
# --------------------------------------------------------------------------

def _run_tool(argv, timeout, what):
    """Run an e2fsprogs binary directly (no shell — paths pass as argv), and
    return combined output.  *what* names the step for error messages."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise Ext4GrowError("%s timed out after %ds" % (what, timeout)) from e
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode, out


def _debugfs(tools, dev, command, timeout, writable=True):
    """One ``debugfs -R`` command against *dev*.  debugfs exits 0 even when
    the command itself failed, so failures are detected from the output."""
    argv = [tools["debugfs"]] + (["-w"] if writable else []) + \
        ["-R", command, dev]
    rc, out = _run_tool(argv, timeout, "debugfs %s" % command.split()[0])
    lowered = out.lower()
    if rc != 0 or "ext2_lookup" in lowered or "ext2fs_" in lowered \
            or "could not allocate" in lowered or "not found" in lowered:
        raise Ext4GrowError("debugfs '%s' failed:\n%s"
                            % (command, out.strip()))
    return out


def _debugfs_file_size(tools, dev, card_rel, timeout):
    """Size in bytes of */card_rel* inside *dev*, or ``None`` if absent."""
    import re
    argv = [tools["debugfs"], "-R", 'stat "/%s"' % card_rel, dev]
    rc, out = _run_tool(argv, timeout, "debugfs stat")
    m = re.search(r"Size:\s*(\d+)", out)
    return int(m.group(1)) if (rc == 0 and m) else None


def _wants_exec(src):
    """Should the inode debugfs creates for *src* be executable?  An ELF
    (the game program) always; anything else only when the host copy already
    carries an execute bit.  Content-based first so the verdict is the same
    on a Windows host, whose stat reports no execute bits at all."""
    try:
        with open(src, "rb") as f:
            if f.read(4) == b"\x7fELF":
                return True
        return bool(os.stat(src).st_mode & 0o111)
    except OSError:
        return False


def _grow_files_debugfs(image_path, part_offset, jobs, log, cancel, timeout):
    """macOS growth: replace each asset inside the ext4 partition via debugfs
    (``kill_file`` frees the old blocks, ``rm`` drops the entry, ``write``
    allocates the full-size copy), then one ``e2fsck -fy`` to reconcile the
    free block/inode counts debugfs leaves stale.  Verified bit-exact against
    a loop-mounted reference."""
    tools = _find_e2fsprogs()
    if tools is None:
        raise Ext4GrowUnavailable(
            "Can't grow files on this system: e2fsprogs isn't "
            "installed (%s). The affected videos keep "
            "their stock content on the card."
            % E2FSPROGS_HINT["darwin" if sys.platform == "darwin" else "linux"])
    if "?" in image_path:
        # unix_io splits the device name on '?' for its offset= suffix.
        raise Ext4GrowError(
            "The image path contains a '?' (%s), which the ext4 tools can't "
            "open. Rename the file and try again." % image_path)
    dev = "%s?offset=%d" % (image_path, part_offset)

    log("Growing %d file(s) to full size via debugfs..." % len(jobs),
        "info")

    # Free-space guard: fail clearly up front instead of ENOSPC mid-write
    # (which would leave a partially-written asset).  Read via debugfs, not
    # dumpe2fs — see _find_e2fsprogs for why dumpe2fs chokes on ?offset=.
    import re
    rc, head = _run_tool([tools["debugfs"], "-R", "stats -h", dev], 60,
                         "debugfs stats")
    mf = re.search(r"^Free blocks:\s*(\d+)", head, re.M)
    mb = re.search(r"^Block size:\s*(\d+)", head, re.M)
    if rc != 0 or not (mf and mb):
        raise Ext4GrowError(
            "Couldn't read the card's games partition (the card image was not "
            "modified by this step):\n%s" % head.strip())
    avail = int(mf.group(1)) * int(mb.group(1))
    need = 0
    items = []
    for card_rel, src in jobs:
        cur = _debugfs_file_size(tools, dev, card_rel, 60) or 0
        d = max(os.path.getsize(src) - cur, 0)
        need += d
        if d:
            items.append((d, card_rel))
    if need > avail:
        raise Ext4GrowNoSpace(no_space_message(need, avail, items),
                              need=need, avail=avail, items=items)

    grown, touched = 0, False
    try:
        for card_rel, src in jobs:
            if cancel():
                break
            tgt = '"/%s"' % card_rel
            touched = True
            # A file the card NEVER HAD is a legitimate job: a mode's own asset,
            # indexed by a freshly appended .sidx record (item 129).  kill_file and
            # rm both fail on a path that does not exist yet and _debugfs raises on
            # "not found", so creating one used to die on the very first command --
            # while the Linux path created it happily with a plain `cp`.  Free the
            # old blocks only when there ARE old blocks; `write` makes the inode
            # either way.
            exists = _debugfs_file_size(tools, dev, card_rel, 60) is not None
            if exists:
                _debugfs(tools, dev, "kill_file %s" % tgt, 120)
                _debugfs(tools, dev, "rm %s" % tgt, 120)
            else:
                # Match the Linux script's PAD_GROW_NODIR guard and name the
                # directory: debugfs would otherwise fail deep inside `write`
                # with nothing saying which parent was missing.
                parent = card_rel.rsplit("/", 1)[0] if "/" in card_rel else ""
                made = _makes_dir(card_rel)
                if made and _debugfs_file_size(tools, dev, made[0], 60) is None:
                    _debugfs(tools, dev, 'mkdir "/%s"' % made[0], 120)
                if parent:
                    prc, pout = _run_tool(
                        [tools["debugfs"], "-R", 'stat "/%s"' % parent, dev],
                        60, "debugfs stat")
                    if prc != 0 or "Inode:" not in pout:
                        raise Ext4GrowError(
                            "Can't create /%s on the card: its directory /%s "
                            "does not exist." % (card_rel, parent))
                log("  creating %s (new file)" % card_rel, "info")
            _debugfs(tools, dev, 'write "%s" %s' % (src, tgt), timeout)
            want = os.path.getsize(src)
            got = _debugfs_file_size(tools, dev, card_rel, 60)
            if got != want:
                raise Ext4GrowError(
                    "debugfs wrote %s B of %s B for %s — the file was left "
                    "incomplete on the card image." % (got, want, card_rel))
            if _wants_exec(src):
                # debugfs ``write`` creates the inode with the HOST file's
                # mode, and a staged game ELF opened "wb" is 0644 unless the
                # engine chmod'ed it: the card's game_monitor then execs it,
                # gets EACCES, and shows RESTARTING GAME forever.  Stock cards
                # carry the game at 0100775 and every asset at 0100664, so
                # only an executable (an ELF, or a source already marked
                # executable) is promoted -- a grown video keeps its mode.
                _debugfs(tools, dev,
                         "set_inode_field %s mode 0100755" % tgt, 120)
            grown += 1
            log("  grew %s" % card_rel, "info")
    except Ext4GrowError as e:
        e.grown = grown
        raise
    finally:
        # debugfs updates the bitmaps but not the free-count summaries;
        # e2fsck reconciles them (exit 1 = "errors corrected" — expected).
        # Runs even after a mid-loop failure so already-grown files never
        # ship with stale accounting.
        if touched:
            rc, out = _run_tool([tools["e2fsck"], "-fy", dev], timeout,
                                "e2fsck")
            if rc not in (0, 1, 2):
                raise Ext4GrowError(
                    "e2fsck could not repair the card's games partition after "
                    "growth (exit %d):\n%s" % (rc, out.strip()[-2000:]))
    log("Grew %d file(s) to full size (filesystem left valid)." % grown,
        "success")
    return grown


# --------------------------------------------------------------------------
# Item 149: a delivery that is BYTE-IDENTICAL from one build to the next.
# --------------------------------------------------------------------------
# A second Write of the same project must give the same card.  The kernel path
# above cannot: two runs of grow_files with the same jobs into two copies of
# one image differ in 217 bytes (measured 2026-09-16 in PAD-Runtime, 150 MB +
# 1.2 MB + a new 3 MB file + 301 KB into a 600 MB ext4): the journal's commit
# blocks (119), s_last_mounted (the random mktemp mountpoint), s_mtime/s_wtime,
# every touched inode's ctime/mtime (and a new inode's atime/crtime), the
# random i_generation of a new inode, i_version, and their checksums.  No data
# block moved.  The same jobs through debugfs with libext2fs's clock pinned
# (E2FSPROGS_FAKE_TIME) and e2fsck's (E2FSCK_TIME) differ in ZERO bytes and
# e2fsck is clean - so a build that must be reproducible delivers this way.
#
# Beyond the macOS sequence it keeps each replaced file's mode, owner and group
# (debugfs `write` takes them from the HOST file, which on a Windows drive is
# 0777), and gives a new file the stock asset mode 0100664 and its directory's
# owner.
#
# The files go through a FEW debugfs sessions, not four per file.  Every session
# opens the partition afresh - on Windows through WSL onto the image on the
# Windows drive - and a writing one reads and rewrites its bitmaps and group
# descriptors, so a session per step was most of what a big delivery cost (601
# files: some 2,400 sessions, and minutes with nothing new in the log).  Now one
# read-only session looks up every path the jobs name, the whole plan is made
# from that (replaced or new, which mode and owner, which scene.assets to make)
# before anything is written, and the files go in batches of one session each,
# which stats what it wrote; the log names each file as its batch lands.

#: The mode a new file gets: what every stock asset on a Spike 2 card carries.
PINNED_NEW_MODE = 0o100664

#: A batch of a pinned delivery ends at this many files or bytes (a bigger file
#: is a batch of its own): few enough sessions to cost nothing next to the
#: copies, small enough that the log moves while a big delivery lands.
PINNED_BATCH_FILES = 32
PINNED_BATCH_BYTES = 64 << 20

_PINNED_HEAD = r'''set -e
export E2FSPROGS_FAKE_TIME=@EPOCH@ E2FSCK_TIME=@EPOCH@
DEV=@DEV@
command -v debugfs >/dev/null && command -v e2fsck >/dev/null || { echo "PAD_GROW_NOTOOLS debugfs/e2fsck" >&2; exit 5; }
stats=$(debugfs -R stats "$DEV" 2>/dev/null)
fb=$(echo "$stats" | awk -F: '/^Free blocks:/ { gsub(/ /, "", $2); print $2 }')
bs=$(echo "$stats" | awk -F: '/^Block size:/ { gsub(/ /, "", $2); print $2 }')
[ -n "$fb" ] && [ -n "$bs" ] || { echo "PAD_GROW_NOFS" >&2; exit 7; }
LOG=$(mktemp /var/tmp/pad_pinned_XXXXXX)
trap 'rm -f "$LOG" "$LOG".*' EXIT
# a session's output -> for each `stat "<path>"` it ran, in order,
# "<size> <mode> <uid> <gid> <path>", or "- - - - <path>" when it is not there
stats_of() {
    awk '
        function out() {
            if (p == "") return
            v = (m != "") ? s " " m " " u " " g : "- - - -"
            print v, p; p = m = ""
        }
        /^debugfs: / { out(); if (index($0, "debugfs: stat \"") == 1) p = substr($0, 16, length($0) - 16); next }
        p != "" && /^Inode:/ { for (i = 1; i < NF; i++) if ($i == "Mode:") m = $(i + 1) }
        p != "" && /^User:/  { u = $2; g = $4; for (i = 1; i < NF; i++) if ($i == "Size:") s = $(i + 1) }
        END { out() }' "$1"
}
'''

_PINNED_BODY = r'''
# every path the jobs name, looked up in ONE read-only session
for i in "${!REL[@]}"; do
    printf 'stat "%s"\nstat "%s"\n' "${REL[$i]}" "${PAR[$i]}"
    [ -z "${MKD[$i]}" ] || printf 'stat "%s"\nstat "%s"\n' "${MKD[$i]}" "${MKU[$i]}"
done > "$LOG.cmd"
debugfs -f "$LOG.cmd" "$DEV" > "$LOG.out" 2>/dev/null || { echo "PAD_GROW_DEBUGFS looking up the files on the card failed" >&2; exit 6; }
stats_of "$LOG.out" > "$LOG.st"
declare -A ST
while read -r s m u g p; do
    [ "$s" = - ] || ST["$p"]="$s $m $u $g"
done < "$LOG.st"

need=0
for i in "${!REL[@]}"; do
    cur=${ST[${REL[$i]}]%% *}
    d=$((SZ[i] - ${cur:-0}))
    if [ "$d" -gt 0 ]; then need=$((need + d)); echo "PAD_GROW_ITEM $d ${REL[$i]#/}"; fi
done
avail=$((fb * bs))
if [ "$need" -gt "$avail" ]; then echo "PAD_GROW_ENOSPC need=$need avail=$avail" >&2; exit 3; fi
echo "PAD_GROW_SPACE need=$need avail=$avail"

# the whole plan before anything is written: each batch's commands, ST kept as
# each path will be once the jobs before it have run
k=0
for i in "${!REL[@]}"; do
    [ "$i" -lt "${CUT[$k]}" ] || k=$((k + 1))
    B="$LOG.b$k"; t=${REL[$i]}; dir=${MKD[$i]}
    # a scene.assets the card never had: made with its scene directory's mode and owner
    if [ -n "$dir" ] && [ -z "${ST[$dir]}" ] && [ -n "${ST[${MKU[$i]}]}" ]; then
        set -- ${ST[${MKU[$i]}]}; dmode=$(printf "%o" $((8#40000 | 8#$2)))
        printf 'mkdir "%s"\nset_inode_field "%s" mode 0%s\nset_inode_field "%s" uid %s\nset_inode_field "%s" gid %s\n' \
            "$dir" "$dir" "$dmode" "$dir" "$3" "$dir" "$4" >> "$B"
        ST[$dir]="0 $dmode $3 $4"; MADE[$i]=1
    fi
    if [ -n "${ST[$t]}" ]; then
        set -- ${ST[$t]}; mode=$2; uid=$3; gid=$4
        printf 'kill_file "%s"\nrm "%s"\n' "$t" "$t" >> "$B"
    else
        [ -n "${ST[${PAR[$i]}]}" ] || { echo "PAD_GROW_NODIR ${t#/}" >&2; exit 4; }
        set -- ${ST[${PAR[$i]}]}; mode=$NEWMODE; uid=$3; gid=$4
    fi
    # debugfs prints a mode's permission bits only (0664); a FILE needs S_IFREG too
    case "$mode" in 10????) ;; *) mode=$(printf "%o" $((8#100000 | 8#$mode))) ;; esac
    printf 'write "%s" "%s"\nset_inode_field "%s" mode 0%s\nset_inode_field "%s" uid %s\nset_inode_field "%s" gid %s\nstat "%s"\n' \
        "${SRC[$i]}" "$t" "$t" "$mode" "$t" "$uid" "$t" "$gid" "$t" >> "$B"
    ST[$t]="${SZ[$i]} $mode $uid $gid"
done

# one writing session a batch; its stats read back what it wrote, in order
i=0
for k in "${!CUT[@]}"; do
    last=$((CUT[k] - 1))
    rc=0; debugfs -w -f "$LOG.b$k" "$DEV" > "$LOG.out" 2> "$LOG.err" || rc=$?
    bad=$(grep -v '^debugfs\|^$' "$LOG.err" || true)
    if [ "$rc" -ne 0 ] || [ -n "$bad" ]; then
        echo "PAD_GROW_DEBUGFS ${REL[$i]#/} to ${REL[$last]#/} (exit $rc): $bad" >&2; exit 6
    fi
    stats_of "$LOG.out" > "$LOG.st"
    while read -r s m u g p; do
        [ "$i" -le "$last" ] && [ "$p" = "${REL[$i]}" ] && [ "$s" = "${SZ[$i]}" ] || {
            echo "PAD_GROW_SHORT ${p#/} $s/${SZ[$i]}" >&2; exit 6; }
        [ -z "${MADE[$i]}" ] || echo "PAD_GROW_MKDIR ${MKD[$i]}"
        echo "PAD_GROW_OK $i ${REL[$i]#/}"
        i=$((i + 1))
    done < "$LOG.st"
    [ "$i" -gt "$last" ] || { echo "PAD_GROW_SHORT ${REL[$i]#/} was not read back" >&2; exit 6; }
done
echo "PAD_GROW_CHECKING"
'''

_PINNED_TAIL = r'''rc=0; e2fsck -fy "$DEV" > "$LOG" 2>&1 || rc=$?
if [ "$rc" -gt 2 ]; then echo "PAD_GROW_FSCK rc=$rc" >&2; tail -n 20 "$LOG" >&2; exit 8; fi
echo "PAD_GROW_DONE fsck=$rc"
'''


def _pinned_batches(sizes):
    """Where each batch of a pinned delivery ends (one past its last job) for
    jobs of *sizes* bytes: :data:`PINNED_BATCH_FILES` files and
    :data:`PINNED_BATCH_BYTES` bytes at most, a bigger file a batch of its
    own."""
    cuts, n, total = [], 0, 0
    for i, size in enumerate(sizes):
        if n and (n >= PINNED_BATCH_FILES or total + size > PINNED_BATCH_BYTES):
            cuts.append(i)
            n = total = 0
        n += 1
        total += size
    if n:
        cuts.append(len(sizes))
    return cuts


def _pinned_script(part_offset, jobs_exec, image_exec, epoch, sizes=None):
    """The bash script :func:`grow_files_pinned` runs: one read-only debugfs
    session looks up every path the jobs name; a free-space check; the whole
    plan (kill_file/rm when the file exists, write, the old or stock
    mode/uid/gid, a scene.assets made where one may be) before anything is
    written; then per batch (:func:`_pinned_batches`) one ``debugfs -w`` that
    stats what it wrote, a size check and a ``PAD_GROW_OK`` marker per file in
    order; then one ``e2fsck -fy`` to reconcile the free counts debugfs leaves
    stale.  Every tool runs with the clock pinned to *epoch*.  *sizes* are the
    sources' sizes in bytes (read here when not given, where the job paths are
    this host's; a source not there counts 0, and grow_files_pinned refuses
    one before it gets here).

    A batch debugfs complains about counts as NOT written, every file in it:
    the complaint does not say which file it is about (``write: Ext2 file
    already exists``), and a file counted that is not on the card would go
    into the build record as on it, where one not counted only makes the next
    build whole."""
    q = shlex.quote
    for rel, src in jobs_exec:
        if '"' in src or '"' in rel:
            raise Ext4GrowError("a path contains a double quote, which debugfs "
                                "cannot take: %s" % (src if '"' in src else rel))
    if sizes is None:
        sizes = [os.path.getsize(src) if os.path.isfile(src) else 0
                 for _rel, src in jobs_exec]
    tgts = ["/" + rel for rel, _src in jobs_exec]
    made = [_makes_dir(rel) for rel, _src in jobs_exec]

    def arr(name, values):
        return "%s=(%s)\n" % (name, " ".join(q(str(v)) for v in values))
    return "".join([
        _PINNED_HEAD.replace("@EPOCH@", str(int(epoch))).replace(
            "@DEV@", q("%s?offset=%d" % (image_exec, int(part_offset)))),
        # per job: its card path, its directory, its source and size, and the
        # scene.assets it may make with that directory's own parent
        arr("REL", tgts),
        arr("PAR", [t.rsplit("/", 1)[0] or "/" for t in tgts]),
        arr("SRC", [src for _rel, src in jobs_exec]),
        arr("SZ", [int(s) for s in sizes]),
        arr("MKD", ["/" + m[0] if m else "" for m in made]),
        arr("MKU", ["/" + m[1] if m else "" for m in made]),
        arr("CUT", _pinned_batches(sizes)),
        "NEWMODE=%o\n" % PINNED_NEW_MODE,
        _PINNED_BODY,
        _PINNED_TAIL])


def partition_epoch(image_path, part_offset):
    """A fixed clock for a pinned delivery, taken from the stock card itself:
    the latest of the partition superblock's mount, write and check times.  The
    same original gives the same clock on every build, and no time e2fsck sees
    is later than it, so nothing reads as being in the future."""
    import struct
    with open(image_path, "rb") as f:
        f.seek(int(part_offset) + 1024)
        sb = f.read(1024)
    if len(sb) < 1024 or sb[0x38:0x3A] != b"\x53\xef":
        raise Ext4GrowError("no ext4 superblock at offset %d of %s"
                            % (part_offset, image_path))
    mtime, wtime = struct.unpack_from("<II", sb, 0x2C)
    lastcheck = struct.unpack_from("<I", sb, 0x40)[0]
    return max(mtime, wtime, lastcheck)


def grow_files_pinned(image_path, part_offset, jobs, epoch, log=None,
                      timeout=3600):
    """:func:`grow_files` with every clock pinned to *epoch*, so the same jobs
    into the same original give the same bytes (item 149).  Same contract:
    returns how many files landed, in order; raises :class:`Ext4GrowError`
    (with ``grown``) or :class:`Ext4GrowNoSpace`.  Runs through e2fsprogs in the
    executor's Linux (PAD-Runtime on Windows) - no mount, no loop device."""
    log = log or (lambda *a, **k: None)
    missing = [rel for rel, src in jobs if not (src and os.path.isfile(src))]
    for rel in missing:
        log("Can't write %s onto the card: the prepared file is missing from "
            "the build's scratch space. This is a bug - please report it."
            % rel, "error")
    if missing:
        raise Ext4GrowError("%d prepared file(s) could not be found on disk "
                            "when it was time to copy them onto the card."
                            % len(missing))
    jobs = [(rel.lstrip("/"), src) for rel, src in jobs]
    if not jobs:
        return 0
    ex = create_executor()
    ok, msg = ex.check_available()
    if not ok:
        raise Ext4GrowUnavailable(
            "Can't write files on this system: %s. The affected file(s) keep "
            "their stock content on the card." % msg)
    image_exec = ex.to_exec_path(os.path.abspath(image_path))
    jobs_exec = [(rel, ex.to_exec_path(os.path.abspath(src))) for rel, src in jobs]
    log("Writing %d file(s) onto the card with a fixed clock, so the next "
        "build of the same project is byte-identical..." % len(jobs), "info")
    script = _pinned_script(part_offset, jobs_exec, image_exec, epoch,
                            sizes=[os.path.getsize(src) for _rel, src in jobs])
    import tempfile
    import threading
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    fd, tmp = tempfile.mkstemp(suffix=".b64", prefix="pad_pinned_")
    # The script's lines are read as they come, so the log names each file as
    # its batch lands instead of all of them once the last one has.  stream()
    # sets no deadline while output flows, so the run is stopped at *timeout*
    # here, as run() stopped it.
    timed_out = []
    timer = threading.Timer(timeout, lambda: (timed_out.append(True), ex.kill()))
    timer.daemon = True
    lines, grown = [], 0
    try:
        os.write(fd, b64.encode("ascii"))
        os.close(fd)
        timer.start()
        for line in ex.stream("base64 -d < %s | bash"
                              % shlex.quote(ex.to_exec_path(tmp)),
                              timeout=timeout):
            lines.append(line)
            if line.startswith("PAD_GROW_OK "):
                grown += 1
                log("  wrote %s (%d of %d)"
                    % (line.split(" ", 2)[-1], grown, len(jobs)), "info")
            elif line.startswith("PAD_GROW_CHECKING"):
                log("Checking the card's games partition after the copies "
                    "(e2fsck)...", "info")
    except Exception as e:  # noqa: BLE001 - executor raises CommandError
        text = "\n".join(lines)
        if "PAD_GROW_ENOSPC" in text:
            raise _no_space(text, grown=grown) from e
        if timed_out:
            raise Ext4GrowError("Couldn't write files: stopped after %d s "
                                "with %d of %d written."
                                % (timeout, grown, len(jobs)),
                                grown=grown) from e
        # what went wrong, without the progress lines that came before it
        said = [ln for ln in lines if ln and not ln.startswith(
            ("PAD_GROW_OK ", "PAD_GROW_ITEM ", "PAD_GROW_SPACE ",
             "PAD_GROW_MKDIR ", "PAD_GROW_CHECKING"))]
        raise Ext4GrowError("Couldn't write files (exit %s):\n%s"
                            % (getattr(e, "returncode", "?"),
                               "\n".join(said[-20:]) or e),
                            grown=grown) from e
    finally:
        timer.cancel()
        try:
            os.remove(tmp)
        except OSError:
            pass
    log("Wrote %d file(s) with the clock fixed at %d (filesystem checked)."
        % (grown, int(epoch)), "success")
    return grown
