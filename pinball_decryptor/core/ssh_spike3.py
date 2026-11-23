"""Spike 3 SSH adapter: checked plaintext edits inside an unchanged LUKS volume."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from .card_extras import ExtrasError
from ..plugins.stern import spike3, spike3_card
from ..plugins.stern.spike3_keys import Spike3KeySource

PLATFORM = 'stern-spike3'
# Exact native payload tested by the qualification harness.
AARCH64_HASHES = {
    'dropbear': '0a36c26216646d3370cba21a9ebd1eaab08580e4274c6c4790f98195748cacdc',
    'dropbearkey': '13ba947cd4b3ffb988e8b97e0d9b15952b79685fffec738449b9ab43d3fc3bc4',
    'sftp-server': 'df3f7f979f7002aa5a47b30757715b0f932f08cde0b538dfffccead5409b97d8',
}


def validate_geometry(part, header):
    """Only the qualified SD-card cipher/sector layout; never header bytes."""
    try:
        if set(header.json['segments']) != {'0'}:
            raise ValueError()
        seg = header.segment('0')
        offset, sector = int(seg['offset']), int(seg.get('sector_size', 512))
        total = int(part['sectors']) * 512
        keyslots_size = int(header.json['config']['keyslots_size'])
        if keyslots_size < 0:
            raise ValueError()
        metadata_end = 2 * int(header.hdr_size) + keyslots_size
        for slot in header.json['keyslots'].values():
            area = slot['area']
            start, size = int(area['offset']), int(area['size'])
            if start < 2 * header.hdr_size or size <= 0:
                raise ValueError()
            metadata_end = max(metadata_end, start + size)
        if (seg.get('type') != 'crypt' or seg.get('encryption') != 'aes-xts-plain64'
                or sector != 512 or int(seg.get('iv_tweak', 0)) != 0
                or header.hdr_size < 4096 or offset < 2 * header.hdr_size or offset < metadata_end
                or offset <= 0 or offset >= total or offset % sector or (total - offset) % sector
                or seg.get('size') != 'dynamic'):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ExtrasError('The Spike 3 LUKS data segment has unqualified or unsafe geometry.') from None


def validate_partitions(parts, size):
    extended = [p for p in parts if p['ptype'] in (0x05, 0x0f)]
    real = sorted((p for p in parts if p['ptype'] not in (0x05, 0x0f)), key=lambda p:p['start_lba'])
    for p in real:
        lo, hi = p['start_lba'] * 512, (p['start_lba'] + p['sectors']) * 512
        if lo < 512 or hi <= lo or hi > size:
            raise ExtrasError('A Spike 3 partition lies outside the image.')
        if p['index'] >= 5 and not any(e['start_lba'] * 512 <= lo and
                hi <= (e['start_lba'] + e['sectors']) * 512 for e in extended):
            raise ExtrasError('A Spike 3 logical partition lies outside its extended partition.')
    if any(a['start_lba'] + a['sectors'] > b['start_lba'] for a,b in zip(real,real[1:])):
        raise ExtrasError('The Spike 3 filesystems overlap.')


def open_stream(path, writable=False):
    """``(stream, size)`` over an image file or, PAD-1427, a plugged-in SD card (a raw device)."""
    from .rawdevice import RawDeviceFile, is_device_path
    if is_device_path(str(path)):
        dev = RawDeviceFile(path, writable=writable)
        if not dev.size:
            dev.close()
            raise ExtrasError("Couldn't tell how big the card is.")
        return dev, dev.size
    f = open(path, 'r+b' if writable else 'rb')
    return f, os.fstat(f.fileno()).st_size


def sync_stream(f):
    """Everything written to *f* on the card or file."""
    f.flush()
    if not hasattr(f, 'reopen'):                       # RawDeviceFile.flush already syncs
        os.fsync(f.fileno())


def key_for(path, key_source=None):
    from .rawdevice import is_device_path
    try:
        keys = key_source
        if keys is None and is_device_path(str(path)):
            # a plugged-in card has no file name to find a per-card key by: the user's own board key opens it
            keys = Spike3KeySource.discover(None, None)
        if keys is None:
            from ..plugins.stern import engine
            rec = engine.read_build_manifest(path)
            original = rec.get('source_path') if rec.get('spike3') else None
            if isinstance(original, str) and os.path.isabs(original):
                # Non-secret provenance only. Keep the original image id for
                # per-image master keys and source-only key sidecars.
                keys = Spike3KeySource.discover(original, image_id=spike3_card.image_id(original))
            if keys is None or not keys.has_any():
                keys = Spike3KeySource.discover(path, image_id=spike3_card.image_id(path))
        if keys is None or not keys.has_any():
            raise ValueError()
        keys._image_id = getattr(keys, '_image_id', None) or spike3_card.image_id(path)
        return keys
    except Exception:
        raise ExtrasError('Unlock this Spike 3 card with your own key on the Extract tab before configuring SSH.') from None


@contextmanager
def open_rootfs(path, writable=False, key_source=None):
    """A plaintext rootfs stream; never write headers or another partition."""
    with open_volume(path, 'rootfs', writable=writable, key_source=key_source) as vol:
        yield vol


@contextmanager
def open_volume(path, role, writable=False, key_source=None):
    """A plaintext stream of the card's encrypted *role* partition (``rootfs``, ``data``, ``connectivity``);
    never write headers or another partition.  PAD-1531: a build for sharing empties ``data`` and
    ``connectivity`` the same way remote access changes ``rootfs``."""
    from . import ssh_card as S
    what = {'rootfs': 'root filesystem', 'data': 'data partition',
            'connectivity': 'connectivity partition'}.get(role, role)
    keys = key_for(path, key_source)
    f, size = open_stream(path, writable)
    try:
        S._partitions(f, size)  # file bounds and non-overlapping primary partitions
        parts = spike3.parse_partitions(f)
        validate_partitions(parts, size)
        if not spike3.is_spike3_card_parts(parts):
            raise ExtrasError('Not a recognized Spike 3 encrypted card layout.')
        part = spike3.partition_for_role(parts, role)
        if part is None or not part.get('luks'):
            raise ExtrasError('The Spike 3 %s is not an encrypted partition.' % what)
        try:
            header = spike3.read_luks_header(f, part['start_lba'])
            header._pad_part_sectors = part['sectors']
        except Exception:
            raise ExtrasError('The Spike 3 %s has an unreadable LUKS header.' % what) from None
        validate_geometry(part, header)
        try:
            master = keys.master_key(header, role=role, part=part)
            if not spike3._luks_otp().verify_master_key(header, master):
                raise ValueError()
        except Exception:
            raise ExtrasError('The supplied Spike 3 key could not unlock the %s.' % what) from None
        vol = spike3_card.GamesVolume(f, part, header, master, writable=writable)
        if vol.size <= 0 or vol.segment_offset + vol.size > part['sectors'] * 512:
            raise ExtrasError('The encrypted %s lies outside its partition.' % what)
        yield vol
    finally:
        f.close()


def inspect_image(path, key_source=None):
    from . import ssh_card as S
    from ..plugins.stern.ext4 import Ext4Reader
    with open_rootfs(path, key_source=key_source) as vol:
        r = Ext4Reader(vol, 0, vol.size)
        passwd = S._read(r, '/etc/passwd')
        init = S._read(r, '/etc/inittab')
        rcs = S._read(r, '/etc/init.d/rcS')
        if (b'root:*:0:0:root:/root:/bin/sh' not in passwd
                or b'Stern Pinball Spike 3' not in S._read(r, '/etc/issue')
                or b'/etc/init.d/rcS' not in init or b'/etc/init.d/S??*' not in rcs
                or not S._node(r, '/etc/init.d/S95game')):
            raise ExtrasError('This Spike 3 rootfs/boot layout has not been qualified for SSH.')
        p = vol.part
        info = S.inspect_root(r, PLATFORM, (p['index'], p['ptype'], p['start_lba'] * 512, p['sectors'] * 512))
        info['segment_offset'] = vol.segment_offset
        info['plaintext_size'] = vol.size
        return info


def export_rootfs(path, dest, key_source=None, cancel=None):
    from . import ssh_card as S
    with open_rootfs(path, key_source=key_source) as vol, open(dest, 'wb') as out:
        left = vol.size
        while left:
            S._cancel(cancel)
            chunk = vol.read(min(left, 1 << 20))
            if not chunk:
                raise ExtrasError('The encrypted root filesystem is truncated.')
            out.write(chunk)
            left -= len(chunk)


def apply_to_build(original, output, config, log=None, cancel=None, key_source=None):
    from . import ssh_card as S
    S.validate_output(original, output)
    keys = key_for(original, key_source)
    source = S.inspect_image(original, key_source=keys)
    dest = S.inspect_image(output, key_source=keys, allow_pending=True)
    if (not source['supported'] or not dest['supported'] or source['platform'] != PLATFORM
            or source['partition'] != dest['partition']
            or source['segment_offset'] != dest['segment_offset']
            or source['plaintext_size'] != dest['plaintext_size']):
        raise ExtrasError(source.get('reason') or dest.get('reason') or 'The Spike 3 system partition changed unexpectedly.')
    size = dest['plaintext_size']
    if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
        raise ExtrasError('Not enough free space to stage the decrypted Spike 3 root filesystem.')
    with tempfile.TemporaryDirectory(prefix='pad-ssh-s3-', dir=str(Path(output).parent)) as tmp:
        work = Path(tmp); part = work / 'rootfs.img'
        export_rootfs(output, part, key_source=keys, cancel=cancel)
        S.prepare_rootfs(part, work, config, platform=PLATFORM, cancel=cancel)
        expected = S._hash_file(part)
        S._cancel(cancel)
        with open_rootfs(output, writable=True, key_source=keys) as vol, part.open('rb') as src:
            left = size
            while left:
                S._cancel(cancel)
                chunk = src.read(min(left, 1 << 20))
                if not chunk:
                    raise ExtrasError('The staged Spike 3 filesystem is truncated.')
                vol.write(chunk)
                left -= len(chunk)
            sync_stream(vol._f)
        # Reopen: cached plaintext must not substitute for encrypted read-back.
        got = hashlib.sha256()
        with open_rootfs(output, key_source=keys) as vol:
            left = size
            while left:
                S._cancel(cancel)
                chunk = vol.read(min(left, 1 << 20))
                if not chunk:
                    raise ExtrasError('The Spike 3 read-back is truncated.')
                got.update(chunk); left -= len(chunk)
        if got.hexdigest() != expected:
            raise ExtrasError('The re-encrypted Spike 3 filesystem failed read-back verification.')
    text = 'SSH server enabled (key-only, port 22).' if config['enabled'] else S.OFF_TEXT
    if log: log(text, 'info')
    return text
