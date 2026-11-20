"""PAD-1467: a Spike 2 card whose Wi-Fi joins the network at the first attempt.

Stern's game tells its connectivity agent to bring Wi-Fi up with ``wpa-driver wext``, the old wireless-extensions
interface.  The card's wpa_supplicant (2.3) and its Realtek USB drivers are cfg80211 ones, and through wext every
join logs "Association request to the driver failed": on 2.4 GHz a retry usually gets through after a while, which
is the machine that takes minutes to appear on the network, or never does.  Measured on David's Godzilla LE with
Stern's AC1200 (RTL8822BU) adapter, 2026-11-20: wext, nine joins of nine failed in 150 s on one access point;
nl80211, joined at the first attempt 14 s after wpa_supplicant started, two boots of two
(docs/plans/spike2-wifi-5ghz.md).

The card needs no script edit.  Its own start-up hook, ``/etc/network/if-pre-up.d/wpa-supplicant``, reads
``/etc/wpa_supplicant/driver.<interface>`` first and uses what it says as the driver name; the shipped card has no
such file.  This module writes that one file with ``nl80211,wext``: nl80211 first, wext still there for an adapter
whose driver cannot do nl80211.  It changes nothing about which band the machine joins.

Built like remote access (core/ssh_card.py): the project's choice is ``extras.wifi`` (core/card_extras.py), the
change goes onto a scratch copy of the system partition with debugfs, and only a checked, read-back copy is written
into the build.  A card qualifies by what is on it (the hook that reads the file, and a wpa_supplicant that knows
nl80211), so every Spike 2 system that ships that hook is covered, whatever the game or its version."""

import os
import shutil
import stat
import struct
from pathlib import Path

from . import card_extras, ssh_card
from .card_extras import ExtrasError
from .executor import create_executor
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

DIR = '/etc/wpa_supplicant'
#: the file the card's own start-up hook reads for the driver name
OVERRIDE = DIR + '/driver.wlan0'
#: nl80211 first; wext stays as the fallback for an adapter whose driver has no cfg80211 support
DRIVER = b'nl80211,wext'
CONTENT = DRIVER + b'\n'
HOOK = '/etc/network/if-pre-up.d/wpa-supplicant'
#: what the hook must contain to be the one that reads OVERRIDE
HOOK_READS = b'/etc/wpa_supplicant/driver.$IFACE'
SUPPLICANT = '/usr/sbin/wpa_supplicant'

NOT_SPIKE2 = 'The Wi-Fi start-up option is for Stern Spike 2 cards.'
NO_HOOK = ("This card's system does not have the Wi-Fi start-up hook this option uses, so it is left as it is.")
FOREIGN = ('This card already names its own Wi-Fi driver (%s); it will not be overwritten.')


def offered(mfr):
    """True when the option applies to cards of *mfr* as it is set now (Stern Spike 2)."""
    return getattr(mfr, 'key', '') == 'stern' and getattr(mfr, '_era', 'spike2') == 'spike2'


def _fail(text):
    raise ExtrasError(text)


def _read(reader, path, limit):
    try:
        return ssh_card._read(reader, path, limit)
    except ExtrasError:
        _fail('A Wi-Fi system file on the card has an unsafe type or size.')


def inspect_root(reader):
    """``{'enabled': bool}`` for the Spike 2 system filesystem behind *reader*, or ExtrasError when the card does
    not qualify (no hook that reads the override, a wpa_supplicant without nl80211, or an override of its own)."""
    game = _read(reader, '/etc/init.d/game', 1024 * 1024)
    if b'/usr/local/spike' not in game:
        _fail(NOT_SPIKE2)
    if HOOK_READS not in _read(reader, HOOK, 64 * 1024):
        _fail(NO_HOOK)
    if b'nl80211' not in _read(reader, SUPPLICANT, 16 << 20):
        _fail(NO_HOOK)
    directory = ssh_card._node(reader, DIR)
    if directory is not None and stat.S_IFMT(directory['mode']) != stat.S_IFDIR:
        _fail('The card has something unexpected where its Wi-Fi settings folder goes.')
    node = ssh_card._node(reader, OVERRIDE)
    if node is None:
        return {'enabled': False}
    if stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1:
        _fail('The card has something unexpected where its Wi-Fi driver setting goes.')
    said = _read(reader, OVERRIDE, 4096).strip()
    if said != DRIVER:
        _fail(FOREIGN % (said[:40].decode('ascii', 'replace') or 'an empty file'))
    return {'enabled': True}


def _inspect(path, allow_pending=False):
    ssh_card._regular(path, allow_pending=allow_pending)
    with open(path, 'rb') as f:
        parts = ssh_card._partitions(f)
        p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
        if p2 is None:
            _fail(NOT_SPIKE2)
        f.seek(p2[2])
        if f.read(6) == b'LUKS\xba\xbe':
            _fail(NOT_SPIKE2)
        info = inspect_root(Ext4Reader(f, p2[2], p2[3]))
        info['partition'] = p2
        return info


def inspect_image(path, *, allow_pending=False):
    """Never raises: ``{'supported', 'reason', 'enabled'}`` (and ``'partition'`` when supported) for the card image
    at *path*."""
    try:
        info = _inspect(path, allow_pending=allow_pending)
        info.update(supported=True, reason='')
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        return {'supported': False, 'reason': str(e).replace('Remote access (SSH) needs', 'This option needs'),
                'enabled': False}


def validate_request(original, project):
    """The project's saved choice (``{'enabled': bool}``) when a build must apply it, None when the project never
    set it.  ExtrasError when it is set and *original* cannot take it."""
    config = card_extras.load_wifi(project)
    if config is not None:
        info = inspect_image(original)
        if not info['supported']:
            if not config['enabled']:
                return None                 # nothing to take off a card that cannot carry it
            raise ExtrasError(info['reason'])
    return config


def guard_flash(project, image):
    """Flash-only may use a finished image, never one that lacks the project's pending Wi-Fi choice."""
    config = validate_request(image, project)
    if config is None:
        return
    if inspect_image(image)['enabled'] != config['enabled']:
        raise ExtrasError('Build the complete image first to apply the pending Wi-Fi start-up change, then flash '
                          'that build.')


def _cancel(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('Wi-Fi preparation canceled.')


def _command(ex, program, *args):
    try:
        return ssh_card._command(ex, program, *args)
    except ExtrasError:
        raise ExtrasError('Wi-Fi preparation failed running %s; no completed build was produced.' % program) from None


def _verify(reader, enabled):
    node = ssh_card._node(reader, OVERRIDE)
    if not enabled:
        if node is not None:
            raise ExtrasError('The Wi-Fi driver setting could not be taken off the card.')
        return
    directory = ssh_card._node(reader, DIR)
    if (node is None or node['mode'] != stat.S_IFREG | 0o644 or node['uid'] or node['gid'] or node['links'] != 1
            or _read(reader, OVERRIDE, 4096) != CONTENT
            or directory is None or directory['mode'] != stat.S_IFDIR | 0o755 or directory['uid']
            or directory['gid']):
        raise ExtrasError('The Wi-Fi driver setting on the card did not read back as written.')


def prepare_rootfs(part, work, enabled, cancel=None):
    """Put the override on (or take it off) a scratch plaintext ext filesystem *part*, checked before and after;
    never a card."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    ex = create_executor()
    _cancel(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    commands = []
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        state = inspect_root(r)             # refuses a symlink, a hard link or an override that is not ours
        directory = ssh_card._node(r, DIR)
        if enabled:
            staged = work / 'driver.wlan0'
            staged.write_bytes(CONTENT)
            src = ex.to_exec_path(str(staged))
            if any(c in src for c in ('"', '\n', '\r', '\\')):
                raise ExtrasError('The staging path contains unsupported filesystem-tool characters.')
            if directory is None:
                commands.append('mkdir %s' % DIR)
            if state['enabled']:
                commands.append('rm %s' % OVERRIDE)
            commands.append('write "%s" %s' % (src, OVERRIDE))
            for field, val in (('mode', '0100644'), ('uid', '0'), ('gid', '0')):
                commands.append('set_inode_field %s %s %s' % (OVERRIDE, field, val))
            for field, val in (('mode', '040755'), ('uid', '0'), ('gid', '0')):
                commands.append('set_inode_field %s %s %s' % (DIR, field, val))
        elif state['enabled']:
            commands.append('rm %s' % OVERRIDE)
            names = [name for name, _, _ in r._iter_dir(directory) if name not in ('.', '..')]
            if names == [os.path.basename(OVERRIDE)]:
                commands.append('rmdir %s' % DIR)        # the folder was ours: the card goes back as shipped
    script = work / 'debugfs.commands'
    script.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        _verify(Ext4Reader(f, 0, size), enabled)


def apply_to_build(original, output, config, log=None, cancel=None):
    """Put the project's Wi-Fi choice *config* on the built image *output* (a copy, never *original*), or raise
    before success.  Returns the line for the build's summary ('' when *config* is None or nothing had to change).

    As with remote access, a failure may leave *output* with a part-written system partition: the pipeline
    quarantines it."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise ExtrasError('Invalid Wi-Fi option.')
    enabled = config['enabled']
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('Wi-Fi preparation must not write the original image.')
    dest = inspect_image(output, allow_pending=True)
    if not dest['supported']:
        raise ExtrasError(dest['reason'])
    text = ('Wi-Fi start-up: the machine joins with the nl80211 driver.' if enabled
            else "Wi-Fi start-up: as Stern ships it.")
    if dest['enabled'] == enabled:
        if log and enabled:
            log(text, 'info')
        return text if enabled else ''
    _cancel(cancel)
    _, _, start, size = dest['partition']
    if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
        raise ExtrasError('Not enough free space to prepare the Wi-Fi start-up on the system partition.')
    ssh_card.rewrite_partition(output, start, size,
                               lambda part, work: prepare_rootfs(part, work, enabled, cancel=cancel),
                               cancel, what='Wi-Fi', stop=_cancel)
    if inspect_image(output, allow_pending=True).get('enabled') != enabled:
        raise ExtrasError('The Wi-Fi driver setting on the built image did not read back as written.')
    if log:
        log(text, 'info')
    return text
