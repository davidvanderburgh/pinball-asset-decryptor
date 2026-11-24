"""Bluetooth headphones on a Stern card: Matt Kulka's spike-pinball-bluetooth, put on by a build (PAD-1554).

https://gitlab.com/mattlqx/spike-pinball-bluetooth gives a Spike 2 or Spike 3 machine Bluetooth headphones: a
Bluetooth entry in the game's own menus, per-headset volume, cabinet speaker control.  Its author asked that this
app **pull his releases rather than carry his code**, so none of it is in this repository: the user installs the
plugin on the Plugins tab (core/card_plugins.py fetches the release at the version tag they pick and checks it),
and a build copies that release's files to the card **unchanged**.

**What the author's install is** (his README, "Install from binaries"): the release's files in
``/usr/local/spikebt`` with an ``enabled`` file beside them, and the game's supervisor running
``/usr/local/spikebt/run-live.sh <game>`` in place of the game.  His launcher starts his helper, preloads his
menu into the game together with this app's own mode runtime when that is on the card, and runs the plain game
whenever anything is missing or fails; a game that exits badly switches it off for the next start
(``/dump/spikebt/disabled``).  On Spike 2 it also loads his USB Bluetooth driver, only on the one kernel it was
built for and only when the file is the one he built.

**What this module adds to the card** (a Spike 2 system partition):

* ``/usr/local/spikebt/``: every file of the installed release as its archive holds it, the empty ``enabled``,
  and ``pad-release`` (the version tag, so the app can say which release a card carries).
* ``/etc/init.d/game_monitor``: the line that starts the game becomes the block that calls his launcher
  (``remote_buttons.BT_HOOK_LINES``; tools/spike2_emu/modehook.py knows it, so a mode install keeps it).
* ``/usr/local/bin/pad-bt-game``: his launcher preloads his menu and the mode runtime and nothing else, so on a
  card that also has a boot menu or remote buttons the block hands it this file instead of the game: it puts
  those two in front of the launcher's own list and starts the game.  Not used on a card with neither.

Off takes all three back out: the folder gone, the script in the form the card would have without it.
"""
import os
import re
import shutil
import stat
import struct
from pathlib import Path

from . import card_extras, card_plugins, remote_buttons as B, ssh_card
from .card_extras import ExtrasError
from .card_plugins import Plugin, PluginError
from .executor import create_executor
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

PLUGIN = card_plugins.register(Plugin(
    key='bluetooth',
    name='Bluetooth headphones',
    what="Bluetooth headphones for Stern Spike 2 and Spike 3 machines: a Bluetooth entry in the game's own menus, "
         'a volume for each headset, and the cabinet speakers on, off or off while headphones play.',
    author='Matt Kulka (mattlqx)',
    project='https://gitlab.com/mattlqx/spike-pinball-bluetooth',
    license='GPL-2.0',
    archives={'armv7': 'spike-pinball-bluetooth-armv7.tar.gz', 'arm64': 'spike-pinball-bluetooth-arm64.tar.gz'},
    needs={'armv7': ('menu.so', 'spikebt', 'run-live.sh', 'radio-start.sh', 'btusb.ko'),
           'arm64': ('menu.so', 'spikebt', 'run-live.sh')},
    tested='v0.3.0',
    pinned={'v0.3.0': {
        'spike-pinball-bluetooth-armv7.tar.gz': '31433015ed0eccdac49b2625e799b0e5d64c51e28c0d0bb033fbd796e6b77f07',
        'spike-pinball-bluetooth-arm64.tar.gz': 'ff2da6232b156db30ab007937f597c0b3b73ce97dc17452ce998ce5216f46bbf',
    }},
))

ARCH = 'armv7'                                   # a Spike 2 card's
DIR = B.BT_DIR
ENABLED = B.BT_ENABLED
RELEASE = DIR + '/pad-release'
WRAPPER = B.BT_GAME
MONITOR = B.MONITOR
DIRS = ('/usr', '/usr/local', '/usr/local/bin', '/etc', '/etc/init.d', DIR)
#: ours, not the release's: what the block hands the launcher in place of the game when the card has other
#: objects of this app to preload.  The launcher has already set LD_PRELOAD (its menu, the mode runtime); they
#: load into this sh as well and do nothing there (each acts only inside the game).
WRAPPER_TEXT = ('#!/bin/sh\n'
                "# PAD-1554: spike-pinball-bluetooth's launcher runs this in place of the game on a card that also\n"
                "# has this app's boot menu or remote buttons: put them in front of its own preloads, start the game.\n"
                'LD_PRELOAD="$PADPRE${LD_PRELOAD:+:$LD_PRELOAD}"\n'
                'export LD_PRELOAD\n'
                'exec "$PADGAME"\n')
OURS = ('enabled', 'pad-release')                # the two files in DIR that are not the release's
MARGIN = 1 << 20

NOT_SPIKE2 = 'Bluetooth headphones can be put on Stern Spike 2 cards only.'
NOT_STOCK = ("This card's game start-up script (/etc/init.d/game_monitor) is not one this app knows, so it is left "
             'as it is and Bluetooth headphones cannot be put on it.')
NOT_INSTALLED = ('The Bluetooth headphones plugin is not installed on this computer. Install it on the Plugins tab, '
                 'or untick it there for this project.')
#: what the Plugins tab shows under "Exactly what it changes on the card": (what, value, in code type)
DETAILS = (
    ('Files added to the card', DIR + "/ (system partition, owner root): the release's files exactly as its "
     'author published them (menu.so, spikebt, run-live.sh, radio-start.sh, rollback.sh, btusb.ko, its licence '
     'and checksums), an empty file named enabled, and pad-release holding the version', True),
    ('File changed', MONITOR + ': the one line that starts the game runs ' + B.BT_RUN + ' with the game instead', True),
    ('File added by this app', WRAPPER + ' (6 lines of sh): used only on a card that also has a boot menu or '
     'remote buttons, so the game still loads those', True),
    ('What it needs', 'Spike 2: a USB Bluetooth adapter in the machine (the author tested StarTech USBBT2EDR4 and '
     'USBBT1EDR4). Its driver is loaded only on the kernel it was built for.', False),
    ('Which games', 'The exact game versions its author lists. On any other version the game runs as Stern '
     'shipped it, with no Bluetooth entry.', False),
    ('If something fails', "The author's launcher starts the plain game whenever its own parts are missing or do "
     'not start, and switches itself off after a game that ended badly.', False),
    ('Kept on the machine', "Paired headphones and settings, in /dump/spikebt on the machine's own data "
     'partition. A card build does not touch them.', False),
    ('To undo', 'Untick it and write the card: the folder is taken off and the script put back.', False),
)


def offered(mfr):
    """Whether *mfr*'s current platform could ever take the plugin (Stern Spike 2)."""
    return bool(mfr is not None and getattr(mfr, 'key', '') == 'stern' and getattr(mfr, '_era', '') == 'spike2')


def _read(reader, path, limit=32 << 20):
    """The bytes of the regular file at *path*, None when there is none."""
    node = ssh_card._node(reader, path)
    if node is None:
        return None
    if stat.S_IFMT(node['mode']) != stat.S_IFREG or node['size'] > limit:
        raise ExtrasError('A Bluetooth system file on the card has an unsafe type or size.')
    return reader.read_file_bytes(node)


def _names(reader, path):
    """The entries of the folder at *path* (no dots), [] when there is none."""
    node = ssh_card._node(reader, path)
    if node is None:
        return []
    if stat.S_IFMT(node['mode']) != stat.S_IFDIR:
        raise ExtrasError('A Bluetooth destination folder on the card is a link or special file.')
    return sorted(name for name, _ino, _kind in reader._iter_dir(node) if name not in ('.', '..'))


def inspect_root(reader):
    """What a Spike 2 system partition carries: ``dict(enabled, hooked, files, release)``, or ExtrasError when its
    start-up script is not known.  *enabled* is the whole install: the block, the ``enabled`` file, the wrapper,
    and every file its own SHA256SUMS names, reading back as that list says."""
    script = _read(reader, MONITOR, 64 << 10)
    if not script:
        raise ExtrasError(NOT_STOCK)
    try:
        B.monitor_text(script, False)                       # refuses a script that is not a known form
    except ExtrasError:
        raise ExtrasError(NOT_STOCK) from None
    hooked = B.has_block(script, B.BT_HOOK_LINES)
    names = _names(reader, DIR)
    wrapper = _read(reader, WRAPPER, 64 << 10)
    release = (_read(reader, RELEASE, 64) or b'').decode('ascii', 'replace').strip() if 'pad-release' in names else ''
    intact = False
    if hooked and 'enabled' in names and card_plugins.SUMS in names and card_plugins.TAG.match(release):
        try:
            sums = card_plugins.parse_sums(_read(reader, DIR + '/' + card_plugins.SUMS, 64 << 10) or b'')
        except PluginError:
            sums = {}
        intact = bool(sums) and set(PLUGIN.needs[ARCH]) <= set(sums) and all(
            n in names and card_plugins.sha256(_read(reader, DIR + '/' + n) or b'') == h for n, h in sums.items())
    return {'enabled': bool(intact and wrapper == WRAPPER_TEXT.encode()), 'hooked': hooked,
            'files': bool(names) or wrapper is not None,
            'release': release if card_plugins.TAG.match(release) else ''}


def inspect_image(path, *, allow_pending=False):
    """Never raises: ``{'supported', 'reason', 'enabled', 'release'}`` (and ``'partition'``) for the card image at
    *path*."""
    try:
        ssh_card._regular(path, allow_pending=allow_pending)
        with open(path, 'rb') as f:
            parts = ssh_card._partitions(f)
            p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
            if p2 is None:
                raise ExtrasError(NOT_SPIKE2)
            f.seek(p2[2])
            if f.read(6) == b'LUKS\xba\xbe':
                raise ExtrasError(NOT_SPIKE2)
            info = inspect_root(Ext4Reader(f, p2[2], p2[3]))
        info.update(supported=True, reason='', partition=p2)
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        return {'supported': False, 'reason': str(e).replace('Remote access (SSH) needs', 'This plugin needs'),
                'enabled': False, 'release': ''}


def describe(info):
    if not info.get('supported'):
        return ''
    return ('spike-pinball-bluetooth %s, started with the game' % info['release'] if info.get('enabled')
            else 'no Bluetooth headphones (as shipped)')


def validate_request(original, project):
    """The project's saved choice (``{'enabled'}``) when a build must apply it, None when it never set one."""
    config = card_extras.load_bluetooth(project)
    if config is None:
        return None
    info = inspect_image(original)
    if not info['supported']:
        if not config['enabled']:
            return None
        raise ExtrasError(info['reason'])
    if config['enabled'] and card_plugins.installed(PLUGIN) is None:
        raise ExtrasError(NOT_INSTALLED)
    return config


def wanted_release(config):
    """The release a build with *config* puts on the card ('' for off or nothing installed)."""
    rec = card_plugins.installed(PLUGIN) if config and config.get('enabled') else None
    return rec['tag'] if rec else ''


def guard_flash(project, image):
    config = validate_request(image, project)
    if config is None:
        return
    info = inspect_image(image)
    if info['enabled'] != config['enabled'] or (config['enabled'] and info['release'] != wanted_release(config)):
        raise ExtrasError('Build the complete image first to apply the pending Bluetooth headphones change, then '
                          'flash that build.')


def _stop(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('The Bluetooth headphones preparation was canceled.')


def _command(ex, program, *args):
    try:
        return ssh_card._command(ex, program, *args)
    except ExtrasError:
        raise ExtrasError('Bluetooth headphones preparation failed running %s; no completed build was produced.'
                          % program) from None


def free_bytes(part):
    """The free space of the ext filesystem in the file *part*, from its superblock."""
    with open(part, 'rb') as f:
        f.seek(1024)
        sb = f.read(0x60)
    if len(sb) < 0x60 or sb[0x38:0x3a] != b'\x53\xef':
        raise ExtrasError('The card system partition is not a readable ext filesystem.')
    return struct.unpack_from('<I', sb, 0x0c)[0] * (1024 << struct.unpack_from('<I', sb, 0x18)[0])


def card_files(members, tag):
    """``{name in DIR: (bytes, mode)}`` for the release *members* at *tag*: the archive's files as they are, and
    the two of ours."""
    out = dict(members)
    out['enabled'] = (b'', 0o644)
    out['pad-release'] = ((tag + '\n').encode('ascii'), 0o644)
    return out


def prepare_rootfs(part, work, on, members=None, tag='', cancel=None):
    """Bring the scratch plaintext ext filesystem *part* to the choice *on* (with the release *members* at *tag*),
    checked before and after."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    ex = create_executor()
    _stop(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    commands, staged_n = [], [0]
    want = card_files(members, tag) if on else {}

    def stage(data):
        staged_n[0] += 1
        staged = work / ('bt-%03d' % staged_n[0])
        staged.write_bytes(data)
        src = ex.to_exec_path(str(staged))
        if any(c in src for c in ('"', '\n', '\r', '\\')):
            raise ExtrasError('The staging path contains unsupported filesystem-tool characters.')
        return src

    def plain(reader, dest):
        node = ssh_card._node(reader, dest)
        if node is not None and (stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1):
            raise ExtrasError('A Bluetooth destination on the card is a link or hard-linked file.')
        return node

    def put(reader, dest, data, mode):
        if plain(reader, dest) is not None:
            commands.append('rm %s' % dest)
        commands.append('write "%s" %s' % (stage(data), dest))
        for fld, val in (('mode', '0100%o' % mode), ('uid', '0'), ('gid', '0')):
            commands.append('set_inode_field %s %s %s' % (dest, fld, val))

    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        state = inspect_root(r)
        script = _read(r, MONITOR, 64 << 10)
        there = _names(r, DIR)
        if any(not re.match(r'^[A-Za-z0-9._-]{1,64}$', n) for n in there):
            raise ExtrasError('The Bluetooth folder on the card holds a file this app does not know.')
        buttons = ssh_card._node(r, B.SO) is not None and (state['hooked'] or B.has_block(script, B.ALL_HOOK_LINES))
        want_script = B.monitor_text(script, buttons, mode=ssh_card._node(r, B.MODE_SO) is not None,
                                     menu=ssh_card._node(r, B.MENU_SO) is not None, bluetooth=on).encode('utf-8')
        if on:
            need = sum(len(d) + 4096 for d, _ in want.values()) + MARGIN
            if free_bytes(part) < need:
                raise ExtrasError("The card's system partition has %.1f MB free and Bluetooth headphones needs "
                                  '%.1f MB.' % (free_bytes(part) / 1e6, need / 1e6))
            for path in DIRS:
                node = ssh_card._node(r, path)
                if node is None:
                    commands.append('mkdir %s' % path)
                elif stat.S_IFMT(node['mode']) != stat.S_IFDIR:
                    raise ExtrasError('A Bluetooth destination folder on the card is a link or special file.')
            for name in there:
                if name not in want:                        # a file of another release: it does not stay
                    plain(r, DIR + '/' + name)
                    commands.append('rm %s/%s' % (DIR, name))
            for name, (data, mode) in sorted(want.items()):
                if name not in there or _read(r, DIR + '/' + name) != data:
                    put(r, DIR + '/' + name, data, mode)
            if _read(r, WRAPPER, 64 << 10) != WRAPPER_TEXT.encode():
                put(r, WRAPPER, WRAPPER_TEXT.encode(), 0o755)
        else:
            for name in there:
                plain(r, DIR + '/' + name)
                commands.append('rm %s/%s' % (DIR, name))
            if ssh_card._node(r, DIR) is not None:
                commands.append('rmdir %s' % DIR)
            if plain(r, WRAPPER) is not None:
                commands.append('rm %s' % WRAPPER)
        if want_script != script:
            put(r, MONITOR, want_script, 0o755)
    script_file = work / 'debugfs.commands'
    script_file.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script_file)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        after = inspect_root(r)
        node = ssh_card._node(r, MONITOR)
        ok = after['enabled'] == on and _read(r, MONITOR, 64 << 10) == want_script \
            and stat.S_IMODE(node['mode']) == 0o755
        if on:
            ok = ok and after['release'] == tag and _names(r, DIR) == sorted(want) and all(
                _read(r, DIR + '/' + n) == d and stat.S_IMODE(ssh_card._node(r, DIR + '/' + n)['mode']) == m
                for n, (d, m) in want.items())
        else:
            ok = ok and not after['files'] and ssh_card._node(r, DIR) is None
        if not ok:
            raise ExtrasError('The Bluetooth headphones files did not read back from the card as written.')


def note(on, tag=''):
    return ('Bluetooth headphones: spike-pinball-bluetooth %s is on the card. A Spike 2 machine needs a USB '
            'Bluetooth adapter.' % tag if on else 'Bluetooth headphones: off, as Stern ships it.')


def apply_to_build(original, output, config, log=None, cancel=None):
    """Put the project's choice *config* on the built image *output* (never *original*), or raise before success.
    Returns the line for the build's summary ('' when nothing is asked or nothing is on the card)."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise ExtrasError('Invalid Bluetooth headphones option.')
    on = config['enabled']
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('Bluetooth headphones preparation must not write the original image.')
    dest = inspect_image(output, allow_pending=True)
    if not dest['supported']:
        if not on:
            return ''
        raise ExtrasError(dest['reason'])
    tag, members = '', None
    if on:
        try:
            tag, members = card_plugins.files(PLUGIN, ARCH)
        except PluginError as e:
            raise ExtrasError(str(e)) from None
    if (on and dest['enabled'] and dest['release'] == tag) or (not on and not (dest['hooked'] or dest['files'])):
        if log and on:
            log(note(on, tag), 'info')
        return note(on, tag) if on else ''
    _stop(cancel)
    _, _, start, size = dest['partition']
    if shutil.disk_usage(Path(output).parent).free < size + (64 << 20):
        raise ExtrasError('Not enough free space to prepare Bluetooth headphones on the system partition.')
    ssh_card.rewrite_partition(
        output, start, size, lambda part, work: prepare_rootfs(part, work, on, members, tag, cancel=cancel),
        cancel, what='Bluetooth headphones', stop=_stop)
    after = inspect_image(output, allow_pending=True)
    if after.get('enabled') != on or (on and after.get('release') != tag):
        raise ExtrasError('The Bluetooth headphones choice on the built image did not read back as written.')
    if log:
        log(note(on, tag), 'info')
    return note(on, tag)
