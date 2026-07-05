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

So we don't.  We loop-mount the partition through the platform's Linux (WSL2 on
Windows, native elsewhere) and ``cp`` the full-size file over the asset; the
kernel grows the inode correctly and the filesystem stays valid (verified with
``e2fsck``).  This module is the thin, well-guarded wrapper around that.
"""

import base64
import os
import shlex

from .executor import create_executor


class Ext4GrowError(Exception):
    """A file-growth operation failed (with a user-facing message)."""


class Ext4GrowUnavailable(Ext4GrowError):
    """The platform can't mount ext4 (no WSL / no Linux) — caller should fall
    back to size-neutral behaviour and warn."""


def available():
    """``(ok, message)`` — whether ext4 growth can run on this platform."""
    try:
        ex = create_executor()
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    ok, msg = ex.check_available()
    return ok, msg


def _bash_script(loop_off, mountpoint, jobs_exec, image_exec):
    """Compose the mount → free-space check → cp → sync → unmount script.

    *jobs_exec* is ``[(card_rel, src_exec_path), ...]`` with exec-side paths.
    Everything is shell-quoted; the script cleans up its loop device and mount
    on any exit via a trap so a mid-run failure never leaves the card mounted.
    """
    lines = [
        "set -e",
        "IMG=%s" % shlex.quote(image_exec),
        "MP=%s" % shlex.quote(mountpoint),
        "OFF=%d" % loop_off,
        "LOOP=",
        # Clean up loop + mount no matter how we exit.
        'cleanup() { sync; umount "$MP" 2>/dev/null || true; '
        '[ -n "$LOOP" ] && losetup -d "$LOOP" 2>/dev/null || true; '
        'rmdir "$MP" 2>/dev/null || true; }',
        "trap cleanup EXIT",
        'mkdir -p "$MP"',
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
    jobs = [(rel.lstrip("/"), src) for rel, src in jobs
            if src and os.path.isfile(src)]
    if not jobs:
        return 0

    ex = create_executor()
    ok, msg = ex.check_available()
    if not ok:
        raise Ext4GrowUnavailable(
            "Can't grow the video slots on this system: %s. The replacement "
            "videos were size-fit to their slots instead." % msg)

    mountpoint = "/mnt/pad_grow_%d" % (part_offset & 0xffffffff)
    image_exec = ex.to_exec_path(image_path)
    jobs_exec = [(rel, ex.to_exec_path(src)) for rel, src in jobs]

    log("Growing %d video slot(s) to full size via the Linux filesystem "
        "driver..." % len(jobs), "info")
    script = _bash_script(part_offset, mountpoint, jobs_exec, image_exec)
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
        if "PAD_GROW_ENOSPC" in text:
            raise Ext4GrowError(
                "Not enough free space on the card's data partition to grow "
                "the videos to full size. The replacements were left size-fit "
                "to their slots.") from e
        raise Ext4GrowError(
            "Couldn't grow the video slots (the card image was not modified by "
            "this step):\n%s" % text) from e
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
