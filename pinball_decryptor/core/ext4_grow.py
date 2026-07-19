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
import shlex
import subprocess
import sys

from .executor import create_executor


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


def _find_e2fsprogs():
    """Locate macOS e2fsprogs binaries (Homebrew keg-only, so not on PATH).

    Returns ``{"debugfs": path, "dumpe2fs": path, "e2fsck": path}`` or ``None``
    if any of the three is missing.
    """
    import shutil
    dirs = ("/opt/homebrew/opt/e2fsprogs/sbin",     # Homebrew ARM
            "/usr/local/opt/e2fsprogs/sbin",        # Homebrew Intel
            "/opt/local/sbin")                      # MacPorts
    tools = {}
    for name in ("debugfs", "dumpe2fs", "e2fsck"):
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


def available():
    """``(ok, message)`` — whether ext4 growth can run on this platform."""
    if sys.platform == "darwin":
        if _find_e2fsprogs() is None:
            return False, ("e2fsprogs isn't installed — install it with: "
                           "brew install e2fsprogs")
        return True, "macOS debugfs"
    try:
        ex = create_executor()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    ok, msg = ex.check_available()
    return ok, msg


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
        'cleanup() { sync; umount "$MP" 2>/dev/null || true; '
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
            '[ "$d" -gt 0 ] && need=$((need+d)) || true' % (tgt, tgt, s))
    lines += [
        "avail=$(df -B1 --output=avail \"$MP\" | tail -1 | tr -d ' ')",
        'if [ "$need" -gt "$avail" ]; then '
        'echo "PAD_GROW_ENOSPC need=$need avail=$avail" >&2; exit 3; fi',
        'echo "PAD_GROW_SPACE need=$need avail=$avail"',
    ]
    for i, (card_rel, src) in enumerate(jobs_exec):
        tgt = '"$MP"/' + shlex.quote(card_rel)
        lines.append(
            'if [ ! -e "$(dirname %s)" ]; then '
            'echo "PAD_GROW_NODIR %s" >&2; exit 4; fi' % (tgt, shlex.quote(card_rel)))
        lines.append("cp %s %s" % (shlex.quote(src), tgt))
        lines.append('echo "PAD_GROW_OK %d %s"' % (i, shlex.quote(card_rel)))
    lines += ["sync", 'echo "PAD_GROW_DONE"']
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
    jobs = [(rel.lstrip("/"), src) for rel, src in jobs
            if src and os.path.isfile(src)]
    if not jobs:
        return 0

    if sys.platform == "darwin":
        return _grow_files_debugfs(image_path, part_offset, jobs, log, cancel,
                                   timeout)

    ex = create_executor()
    ok, msg = ex.check_available()
    if not ok:
        raise Ext4GrowUnavailable(
            "Can't grow the video slots on this system: %s. The affected "
            "videos keep their stock content on the card." % msg)

    image_exec = ex.to_exec_path(image_path)
    jobs_exec = [(rel, ex.to_exec_path(src)) for rel, src in jobs]

    log("Growing %d video slot(s) to full size via the Linux filesystem "
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
            raise Ext4GrowError(
                "Not enough free space on the card's data partition to grow "
                "the videos to full size. The affected videos keep their "
                "stock content on the card.", grown=n_ok) from e
        raise Ext4GrowError(
            "Couldn't grow the video slots:\n%s" % text, grown=n_ok) from e
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
    log("Grew %d video slot(s) to full size (filesystem left valid)." % grown,
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


def _grow_files_debugfs(image_path, part_offset, jobs, log, cancel, timeout):
    """macOS growth: replace each asset inside the ext4 partition via debugfs
    (``kill_file`` frees the old blocks, ``rm`` drops the entry, ``write``
    allocates the full-size copy), then one ``e2fsck -fy`` to reconcile the
    free block/inode counts debugfs leaves stale.  Verified bit-exact against
    a loop-mounted reference."""
    tools = _find_e2fsprogs()
    if tools is None:
        raise Ext4GrowUnavailable(
            "Can't grow the video slots on this system: e2fsprogs isn't "
            "installed (brew install e2fsprogs). The affected videos keep "
            "their stock content on the card.")
    if "?" in image_path:
        # unix_io splits the device name on '?' for its offset= suffix.
        raise Ext4GrowError(
            "The image path contains a '?' (%s), which the ext4 tools can't "
            "open. Rename the file and try again." % image_path)
    dev = "%s?offset=%d" % (image_path, part_offset)

    log("Growing %d video slot(s) to full size via debugfs..." % len(jobs),
        "info")

    # Free-space guard: fail clearly up front instead of ENOSPC mid-write
    # (which would leave a partially-written asset).
    import re
    rc, head = _run_tool([tools["dumpe2fs"], "-h", dev], 60, "dumpe2fs")
    mf = re.search(r"^Free blocks:\s*(\d+)", head, re.M)
    mb = re.search(r"^Block size:\s*(\d+)", head, re.M)
    if rc != 0 or not (mf and mb):
        raise Ext4GrowError(
            "Couldn't read the card's data partition (the card image was not "
            "modified by this step):\n%s" % head.strip())
    avail = int(mf.group(1)) * int(mb.group(1))
    need = 0
    for card_rel, src in jobs:
        cur = _debugfs_file_size(tools, dev, card_rel, 60) or 0
        need += max(os.path.getsize(src) - cur, 0)
    if need > avail:
        raise Ext4GrowError(
            "Not enough free space on the card's data partition to grow the "
            "videos to full size (need %d B more, %d B free). The affected "
            "videos keep their stock content on the card." % (need, avail))

    grown, touched = 0, False
    try:
        for card_rel, src in jobs:
            if cancel():
                break
            tgt = '"/%s"' % card_rel
            touched = True
            _debugfs(tools, dev, "kill_file %s" % tgt, 120)
            _debugfs(tools, dev, "rm %s" % tgt, 120)
            _debugfs(tools, dev, 'write "%s" %s' % (src, tgt), timeout)
            want = os.path.getsize(src)
            got = _debugfs_file_size(tools, dev, card_rel, 60)
            if got != want:
                raise Ext4GrowError(
                    "debugfs wrote %s B of %s B for %s — the file was left "
                    "incomplete on the card image." % (got, want, card_rel))
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
                    "e2fsck could not repair the card's data partition after "
                    "growth (exit %d):\n%s" % (rc, out.strip()[-2000:]))
    log("Grew %d video slot(s) to full size (filesystem left valid)." % grown,
        "success")
    return grown
