"""A build for sharing carries nothing of the machine it came from (PAD-1531).

David: "if someone distributes a built image with their remote access set up on it, will another user on the
other side of the world have access to the original user's machine? we don't want that to happen."

A card or image only ever carries the PUBLIC half of a computer's key (the private half stays beside
settings.json, core/pad_ssh_key.py), and the card's SSH server takes keys only.  Still, a card with remote access
on lets in whoever holds the matching private key: written onto someone else's machine, it lets the builder in.
So a project can be built **for sharing** (``extras.share``, core/card_extras.py), which is:

* remote access off, completely: no boot hook, no trusted key, none of PAD's SSH programs (ssh_card); and
* the machine's own partitions emptied, as a stock card ships them.  An image built from a dump of the builder's
  own card would otherwise carry that machine's settings, audits, scores and logs, and with remote access once
  on, its SSH host keys (``/data/dropbear``).  On Spike 2 those are ``/data`` (p5) and ``/dump`` (p6); the game's
  Wi-Fi network is kept with its settings in ``/data`` (the root filesystem is read-only, and its
  ``/etc/wpa_supplicant.conf`` holds no network; ``/connectivity`` is the board's own flash, not the SD card).  On
  Spike 3 they are the encrypted ``data`` (p3) and ``connectivity`` (p5) volumes.  A stock card has every one of
  them empty (2026-11-23: Aerosmith 1.16 and a Godzilla build on Spike 2, Fallout 0.82 on Spike 3).

Emptying is the checked way remote access changes a card: a scratch copy of the partition, the journal replayed
and every entry but ``lost+found`` removed with debugfs, checked with e2fsck and read back, then written in (the
blocks that differ, on Spike 3 through the volume's encryption) and read back again.  A partition that is empty
already is left alone, byte for byte."""

import hashlib
import os
import shlex
import shutil
import stat
import struct
import tempfile
from pathlib import Path

from .card_extras import ExtrasError
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

KEEP = ('.', '..', 'lost+found')
#: Spike 2: the logical partitions a machine writes to (fstab: /data and /dump), by their 0-based table index
SPIKE2_PARTS = {4: '/data', 5: '/dump'}
#: Spike 3: the encrypted volumes a machine writes to
SPIKE3_ROLES = ('data', 'connectivity')
BLOCK = 1 << 20


def _stop(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('Canceled while emptying the machine data for sharing.')


def entries(reader):
    """The names at the root of the filesystem *reader* reads, other than ``lost+found``."""
    return [name for name, _ino, _t in reader._iter_dir(reader.read_inode(2)) if name not in KEEP]


def empty_commands(reader):
    """debugfs commands removing everything in the filesystem but ``lost+found``: files first, then each directory
    once it is empty (debugfs has no recursive remove)."""
    out = []

    def walk(node, path, depth):
        if depth > 64:
            raise ExtrasError('The machine data on this image is nested too deeply to empty.')
        for name, ino, _t in reader._iter_dir(node):
            if name in ('.', '..') or (not path and name == 'lost+found'):
                continue
            if any(c in name for c in '"\n\r\\') or not name.isprintable():
                raise ExtrasError('The machine data on this image has a file name PAD cannot remove safely.')
            child = reader.read_inode(ino)
            full = path + '/' + name
            if stat.S_IFMT(child['mode']) == stat.S_IFDIR:
                walk(child, full, depth + 1)
                out.append('rmdir "%s"' % full)
            else:
                out.append('rm "%s"' % full)
    walk(reader.read_inode(2), '', 0)
    return out


def empty_filesystem(part, work, cancel=None):
    """Empty the plain ext filesystem in the scratch file *part* (never a card), and check it."""
    from .executor import create_executor
    part, work = Path(part), Path(work)
    ex = create_executor()
    exec_part = ex.to_exec_path(str(part))
    q = shlex.quote(exec_part)
    _stop(cancel)
    # a dump of a card that was in use: its journal may need replaying first (exit 1 = fixed, which is fine here)
    try:
        ex.run('e2fsck -fy %s >/dev/null 2>&1; rc=$?; [ "$rc" -le 1 ]' % q, timeout=600)
    except Exception:
        raise ExtrasError("The machine data on this image is damaged, so it can't be emptied for sharing.") from None
    with part.open('rb') as f:
        commands = empty_commands(Ext4Reader(f, 0, part.stat().st_size))
    if commands:
        script = work / 'empty.commands'
        script.write_text('\n'.join(commands) + '\n', encoding='utf-8', newline='\n')
        try:
            ex.run('debugfs -w -f %s %s' % (shlex.quote(ex.to_exec_path(str(script))), q), timeout=600)
            ex.run('e2fsck -fn %s' % q, timeout=600)
        except Exception:
            raise ExtrasError("The machine data on this image couldn't be emptied for sharing.") from None
    with part.open('rb') as f:
        if entries(Ext4Reader(f, 0, part.stat().st_size)):
            raise ExtrasError('The machine data on this image could not be emptied completely.')


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b''):
            h.update(chunk)
    return h.hexdigest()


def _copy_out(read, size, dest, cancel):
    with open(dest, 'wb') as out:
        done = 0
        while done < size:
            _stop(cancel)
            chunk = read(done, min(BLOCK, size - done))
            if not chunk:
                raise ExtrasError('The machine data partition is cut short.')
            out.write(chunk)
            done += len(chunk)


def _write_back(read, write, size, src, cancel):
    """Write the 1 MiB blocks of *src* that differ; once begun it finishes."""
    with open(src, 'rb') as f:
        done = 0
        while done < size:
            new = f.read(min(BLOCK, size - done))
            if read(done, len(new)) != new:
                write(done, new)
            done += len(new)


def _read_hash(read, size):
    got = hashlib.sha256()
    done = 0
    while done < size:
        chunk = read(done, min(BLOCK, size - done))
        if not chunk:
            raise ExtrasError('Reading the emptied machine data back was cut short.')
        got.update(chunk)
        done += len(chunk)
    return got.hexdigest()


def _is_spike3(path):
    from . import ssh_card
    with open(path, 'rb') as f:
        _p2, encrypted = ssh_card.system_partition(f, os.fstat(f.fileno()).st_size)
    return encrypted


def _spike2_parts(path):
    from ..plugins.stern.formats import parse_all_partitions_file
    with open(path, 'rb') as f:
        parts = {i: (t, s * 512, n * 512) for i, t, s, n in parse_all_partitions_file(f)}
    found = []
    for index, mount in SPIKE2_PARTS.items():
        p = parts.get(index)
        if p is None or p[0] != 0x83:
            raise ExtrasError("This image has no %s partition where a Stern Spike 2 card keeps it, so PAD can't "
                              "check it for sharing." % mount)
        found.append((mount, p[1], p[2]))
    return found


def _spike2(output, log, cancel):
    emptied = []
    for mount, start, size in _spike2_parts(output):
        _stop(cancel)
        try:
            with open(output, 'rb') as f:
                left = entries(Ext4Reader(f, start, size))
        except (Ext4Error, ValueError, struct.error):
            raise ExtrasError("The %s partition on this image isn't readable, so PAD can't empty it for sharing."
                              % mount) from None
        if not left:
            continue
        if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
            raise ExtrasError('Not enough free space to empty the machine data for sharing.')
        if log:
            log('Emptying %s (%s) for sharing...' % (mount, ', '.join(sorted(left)[:6])), 'info')
        with tempfile.TemporaryDirectory(prefix='pad-share-', dir=str(Path(output).parent)) as tmp:
            work = Path(tmp)
            part = work / 'part.img'
            with open(output, 'rb') as f:
                def read(off, n, f=f):
                    f.seek(start + off)
                    return f.read(n)
                _copy_out(read, size, part, cancel)
            empty_filesystem(part, work, cancel)
            expected = _hash_file(part)
            _stop(cancel)
            with open(output, 'r+b') as f:
                def read(off, n, f=f):
                    f.seek(start + off)
                    return f.read(n)

                def write(off, data, f=f):
                    f.seek(start + off)
                    f.write(data)
                _write_back(read, write, size, part, cancel)
                f.flush()
                os.fsync(f.fileno())
            with open(output, 'rb') as f:
                def read(off, n, f=f):
                    f.seek(start + off)
                    return f.read(n)
                if _read_hash(read, size) != expected:
                    raise ExtrasError('The emptied machine data did not read back as written.')
        emptied.append(mount)
    return emptied


def _spike3(original, output, log, cancel, key_source):
    from . import ssh_spike3
    keys = ssh_spike3.key_for(original, key_source)
    emptied = []
    for role in SPIKE3_ROLES:
        _stop(cancel)
        with ssh_spike3.open_volume(output, role, key_source=keys) as vol:
            size = vol.size
            left = entries(Ext4Reader(vol, 0, size))
        if not left:
            continue
        if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
            raise ExtrasError('Not enough free space to empty the machine data for sharing (%d MB needed).'
                              % ((size >> 20) + 32))
        if log:
            log('Emptying the %s partition for sharing...' % role, 'info')
        with tempfile.TemporaryDirectory(prefix='pad-share-s3-', dir=str(Path(output).parent)) as tmp:
            work = Path(tmp)
            part = work / 'part.img'
            with ssh_spike3.open_volume(output, role, key_source=keys) as vol:
                def read(off, n, vol=vol):
                    vol.seek(off)
                    return vol.read(n)
                _copy_out(read, size, part, cancel)
            empty_filesystem(part, work, cancel)
            expected = _hash_file(part)
            _stop(cancel)
            with ssh_spike3.open_volume(output, role, writable=True, key_source=keys) as vol:
                def read(off, n, vol=vol):
                    vol.seek(off)
                    return vol.read(n)

                def write(off, data, vol=vol):
                    vol.seek(off)
                    vol.write(data)
                _write_back(read, write, size, part, cancel)
                ssh_spike3.sync_stream(vol._f)
            # reopened: the encrypted bytes on the image are what is read back, not a cache
            with ssh_spike3.open_volume(output, role, key_source=keys) as vol:
                def read(off, n, vol=vol):
                    vol.seek(off)
                    return vol.read(n)
                if _read_hash(read, size) != expected:
                    raise ExtrasError('The emptied machine data did not read back as written.')
        emptied.append(role)
    return emptied


def scrub(original, output, log=None, cancel=None, key_source=None):
    """Empty the machine's own partitions of the built image *output* (a copy, never the original).  Returns what
    it says it did, '' when they were empty already."""
    if os.path.samefile(original, output):
        raise ExtrasError('A build for sharing must not change the original image.')
    emptied = (_spike3(original, output, log, cancel, key_source) if _is_spike3(output)
               else _spike2(output, log, cancel))
    if not emptied:
        return ''
    text = ("Took the machine's own settings, scores, logs and network identity off it (%s), as a stock card "
            "has them." % ', '.join(emptied))
    if log:
        log(text, 'info')
    return text


def machine_data(path, key_source=None):
    """What of a machine's own the image at *path* carries: ``[(partition, [names])]`` for each non-empty one,
    or None when it can't be read (PAD-1531: the Write tab says so for an image that came from a used card)."""
    try:
        if _is_spike3(path):
            from . import ssh_spike3
            out = []
            for role in SPIKE3_ROLES:
                with ssh_spike3.open_volume(path, role, key_source=key_source) as vol:
                    left = entries(Ext4Reader(vol, 0, vol.size))
                if left:
                    out.append((role, left))
            return out
        out = []
        for mount, start, size in _spike2_parts(path):
            with open(path, 'rb') as f:
                left = entries(Ext4Reader(f, start, size))
            if left:
                out.append((mount, left))
        return out
    except (OSError, ValueError, Ext4Error, struct.error):
        return None
