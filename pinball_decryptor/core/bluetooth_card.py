"""Bluetooth headphones on a Stern card: mattlqx's spike-pinball-bluetooth, put on by a build (PAD-1554).

https://gitlab.com/mattlqx/spike-pinball-bluetooth gives a Spike 2 or Spike 3 machine Bluetooth headphones: a
Bluetooth entry in the game's own menus, per-headset volume, cabinet speaker control.  Its author asked that this
app **pull his releases rather than carry his code**, so none of it is in this repository: the user installs the
plugin on the Plugins tab (core/card_plugins.py fetches the release at the version tag they pick and checks it),
and a build copies that release's files to the card **unchanged**.

**What the author's install is** (his README, "Install from binaries"): the release's files in
``/usr/local/spikebt`` with an ``enabled`` file beside them, and the game's supervisor running
``/usr/local/spikebt/run-live.sh <game>`` in place of the game (Spike 3: with ``SPIKEBT_BACKEND=bluez5``).  His
launcher starts his helper, preloads his menu into the game together with this app's own mode runtime when that
is on the card, and runs the plain game whenever anything is missing or fails; a game that exits with anything but
0 switches it off for the next start (``/dump/spikebt/disabled``).  On Spike 2 it also loads his USB Bluetooth
driver, only on the one kernel it was built for and only when the file is the one he built.  Spike 3 uses the
machine's own radio and its BlueZ 5 and BlueALSA services, and gets no driver.

**What this module adds to the card's system partition** (Spike 2: plain ext; Spike 3: the LUKS root filesystem,
rewritten with the user's own key the way remote access is, core/ssh_spike3.py):

* ``/usr/local/spikebt/``: every file of the installed release for that machine as its archive holds it, the
  empty ``enabled``, and ``pad-release`` (the version tag, so the app can say which release a card carries).
* ``/etc/init.d/game_monitor``: the line that starts the game becomes the block that calls his launcher.
  Spike 2: ``remote_buttons.BT_HOOK_LINES`` (tools/spike2_emu/modehook.py knows it, so a mode install keeps it).
  Spike 3: :data:`S3_HOOK_LINES`.
* Spike 2 only, ``/usr/local/bin/pad-bt-game``: his launcher preloads his menu and the mode runtime and nothing
  else, so on a card that also has a boot menu or remote buttons the block hands it this file instead of the
  game: it puts those two in front of the launcher's own list and starts the game.

**Spike 3's exit codes.**  Stern's Spike 3 ``game_monitor`` reads the game's exit code, and three of them are a
normal end, not a fault: 1 (reboot asked for, after a software update), 3 (power switched off) and 6 (deep
sleep).  His launcher cannot tell and would switch Bluetooth off for good after any of them, so the block takes
his switched-off mark away again after exactly those three, and hands the code on to Stern's script unchanged.

Off takes everything back out: the folder gone, the script as the card had it without the plugin.
"""
import hashlib
import json
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
    author='mattlqx',
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
    # the game programs each release's menu knows, by the hash of the executable (not in the archives)
    source_keep=('profiles/supported-games.json', 'profiles/spike3/'),
))

SPIKE2, SPIKE3 = 'stern-spike2', 'stern-spike3'
ARCHES = {SPIKE2: 'armv7', SPIKE3: 'arm64'}
ARCH = ARCHES[SPIKE2]
DIR = B.BT_DIR
ENABLED = B.BT_ENABLED
RELEASE = DIR + '/pad-release'
WRAPPER = B.BT_GAME
MONITOR = B.MONITOR
DISABLED = '/dump/spikebt/disabled'              # his launcher's own switched-off mark, on the machine
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

# ---- Spike 3's /etc/init.d/game_monitor: the line that starts the game, and the block that replaces it ----
S3_RUN_LINE = '\t\t$GAME'
S3_HOOK_LINES = [
    "\t\t# Bluetooth headphones (PAD-1554): spike-pinball-bluetooth's launcher starts the game when it is on",
    '\t\t# this card, the plain game when it is not.  PADBT is the game\'s own exit code either way.',
    '\t\tif [ -f ' + ENABLED + ' ] && [ -x ' + B.BT_RUN + ' ]; then',
    '\t\t\tSPIKEBT_BACKEND=bluez5 ' + B.BT_RUN + ' $GAME',
    '\t\t\tPADBT=$?',
    '\t\t\t# the launcher switches itself off after any exit but 0; a reboot asked for (1), the power',
    '\t\t\t# switched off (3) and deep sleep (6) are normal ends here (the table above), so it stays on',
    '\t\t\tcase "$PADBT" in 1|3|6) rm -f ' + DISABLED + ' ;; esac',
    '\t\telse',
    '\t\t\t$GAME',
    '\t\t\tPADBT=$?',
    '\t\tfi',
    '\t\t(exit "$PADBT")',
]

NOT_OFFERED = 'Bluetooth headphones can be put on Stern Spike 2 and Spike 3 cards only.'
NOT_SPIKE2 = NOT_OFFERED                         # the name the Plugins tab reads
NOT_STOCK = ("This card's game start-up script (/etc/init.d/game_monitor) is not one this app knows, so it is left "
             'as it is and Bluetooth headphones cannot be put on it.')
NOT_INSTALLED = ('The Bluetooth headphones plugin is not installed on this computer. Install it on the Plugins tab, '
                 'or untick it there for this project.')
NO_KEY = 'Unlock this Spike 3 card with your own key on the Extract tab before putting Bluetooth headphones on it.'


def details(platform=SPIKE2):
    """What the Plugins tab shows under "Exactly what it changes on the card": (what, value, in code type)."""
    s3 = platform == SPIKE3
    rows = [
        ('Files added to the card', DIR + "/ (system partition, owner root): the release's files exactly as its "
         'author published them (menu.so, spikebt, run-live.sh, rollback.sh, %sits licence and checksums), an '
         'empty file named enabled, and pad-release holding the version'
         % ('' if s3 else 'radio-start.sh, btusb.ko, '), True),
        ('File changed', MONITOR + ': the one line that starts the game runs ' + B.BT_RUN + ' with the game instead',
         True),
    ]
    if s3:
        rows += [
            ('How the card is changed', 'A Spike 3 system partition is encrypted. It is opened with your own key, '
             'changed, written back and read back, as remote access is. Its header and the signed boot partition '
             'are not touched.', False),
            ('What it needs', "Nothing added: Spike 3 uses the machine's own Bluetooth radio and services.", False),
            ('Normal power-off', "The launcher switches itself off after a game that ended badly. Power off, a "
             'reboot for an update and deep sleep are not that, so the changed line keeps it on after those.', False),
        ]
    else:
        rows += [
            ('File added by this app', WRAPPER + ' (6 lines of sh): used only on a card that also has a boot menu '
             'or remote buttons, so the game still loads those', True),
            ('What it needs', 'Spike 2: a USB Bluetooth adapter in the machine (the author tested StarTech '
             'USBBT2EDR4 and USBBT1EDR4). Its driver is loaded only on the kernel it was built for.', False),
        ]
    rows += [
        ('Which games', 'The exact game versions its author lists. On any other version the game runs as Stern '
         'shipped it, with no Bluetooth entry.', False),
        ('If something fails', "The author's launcher starts the plain game whenever its own parts are missing or "
         'do not start, and switches itself off after a game that ended badly.', False),
        ('Kept on the machine', "Paired headphones and settings, in /dump/spikebt on the machine's own data. A "
         'card build does not touch them.', False),
        ('To undo', 'Untick it and write the card: the folder is taken off and the script put back.', False),
    ]
    return tuple(rows)


DETAILS = details(SPIKE2)


def platform_of(mfr):
    """The card platform of *mfr*'s current era that the plugin goes on, or None."""
    if mfr is None or getattr(mfr, 'key', '') != 'stern':
        return None
    return {'spike2': SPIKE2, 'spike3': SPIKE3}.get(getattr(mfr, '_era', ''))


def offered(mfr):
    """Whether *mfr*'s current platform could ever take the plugin (Stern Spike 2 and Spike 3)."""
    return platform_of(mfr) is not None


def _read(reader, path, limit=32 << 20):
    """The bytes of the regular file at *path*, None when there is none."""
    node = ssh_card.resolve(reader, path)[1]                # PAD-1619: Stern's updater links game_monitor
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


def _find(lines, block):
    n = len(block)
    return next((k for k in range(len(lines) - n + 1) if lines[k:k + n] == block), None)


def s3_monitor_text(text, on):
    """A Spike 3 game start-up script for the choice *on*: the block in place of Stern's line, or that line back.
    ExtrasError when the script is not Stern's with exactly one such line."""
    lines = (text.decode('utf-8', 'replace') if isinstance(text, bytes) else text).split('\n')
    k = _find(lines, S3_HOOK_LINES)
    if k is not None:
        lines[k:k + len(S3_HOOK_LINES)] = [S3_RUN_LINE]
    hits = [i for i, l in enumerate(lines) if l == S3_RUN_LINE]
    if len(hits) != 1 or not any(l.strip() == 'GAME_EXIT_REASON="$?"' for l in lines[hits[0] + 1:hits[0] + 2]):
        raise ExtrasError(NOT_STOCK)
    if on:
        lines[hits[0]:hits[0] + 1] = S3_HOOK_LINES
    return '\n'.join(lines)


def inspect_root(reader, platform=SPIKE2):
    """What a system partition carries: ``dict(enabled, hooked, files, release)``, or ExtrasError when its
    start-up script is not known.  *enabled* is the whole install: the block, the ``enabled`` file, on Spike 2 the
    wrapper, and every file its own SHA256SUMS names, reading back as that list says."""
    script = _read(reader, MONITOR, 64 << 10)
    if not script:
        raise ExtrasError(NOT_STOCK)
    if platform == SPIKE3:
        if b'Stern Pinball Spike 3' not in (_read(reader, '/etc/issue', 64 << 10) or b''):
            raise ExtrasError('This Spike 3 system partition is not one this app knows.')
        s3_monitor_text(script, False)                      # refuses a script that is not a known form
        hooked = _find(script.decode('utf-8', 'replace').split('\n'), S3_HOOK_LINES) is not None
        wrapper, wrapper_ok = None, True
    else:
        try:
            B.monitor_text(script, False)
        except ExtrasError:
            raise ExtrasError(NOT_STOCK) from None
        hooked = B.has_block(script, B.BT_HOOK_LINES)
        wrapper = _read(reader, WRAPPER, 64 << 10)
        wrapper_ok = wrapper == WRAPPER_TEXT.encode()
    names = _names(reader, DIR)
    release = (_read(reader, RELEASE, 64) or b'').decode('ascii', 'replace').strip() if 'pad-release' in names else ''
    intact = False
    if hooked and 'enabled' in names and card_plugins.SUMS in names and card_plugins.TAG.match(release):
        try:
            sums = card_plugins.parse_sums(_read(reader, DIR + '/' + card_plugins.SUMS, 64 << 10) or b'')
        except PluginError:
            sums = {}
        intact = bool(sums) and set(PLUGIN.needs[ARCHES[platform]]) <= set(sums) and all(
            n in names and card_plugins.sha256(_read(reader, DIR + '/' + n) or b'') == h for n, h in sums.items())
    return {'enabled': bool(intact and wrapper_ok), 'hooked': hooked,
            'files': bool(names) or wrapper is not None,
            'release': release if card_plugins.TAG.match(release) else ''}


def inspect_image(path, *, allow_pending=False, key_source=None):
    """Never raises: ``{'supported', 'reason', 'enabled', 'release', 'platform'}`` (and ``'partition'`` on
    Spike 2) for the card image at *path*.  A Spike 3 card needs the user's key to be looked into."""
    platform = ''
    try:
        ssh_card._regular(path, allow_pending=allow_pending)
        with open(path, 'rb') as f:
            parts = ssh_card._partitions(f)
            p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
            if p2 is None:
                raise ExtrasError(NOT_OFFERED)
            f.seek(p2[2])
            luks = f.read(6) == b'LUKS\xba\xbe'
            if not luks:
                platform = SPIKE2
                info = inspect_root(Ext4Reader(f, p2[2], p2[3]), SPIKE2)
        if luks:
            platform = SPIKE3
            from . import ssh_spike3
            with ssh_spike3.open_rootfs(path, key_source=key_source) as vol:
                info = inspect_root(Ext4Reader(vol, 0, vol.size), SPIKE3)
        info.update(supported=True, reason='', partition=p2, platform=platform)
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        reason = str(e).replace('Remote access (SSH) needs', 'This plugin needs')
        if 'before configuring SSH' in reason:
            reason = NO_KEY
        return {'supported': False, 'reason': reason, 'enabled': False, 'release': '', 'platform': platform}


def known_games(platform):
    """``{sha256 of a game program: its name}`` the installed release's menu knows for *platform*, or None when
    the list was not kept at install (then the app says nothing either way)."""
    texts = card_plugins.source_texts(PLUGIN)
    out = {}
    try:
        if platform == SPIKE3:
            rows = [json.loads(t) for p, t in sorted(texts.items()) if p.startswith('profiles/spike3/')]
            for row in rows:
                out[row['executable_sha256']] = '%s %s' % (row['title'], row.get('version', ''))
        elif 'profiles/supported-games.json' in texts:
            for row in json.loads(texts['profiles/supported-games.json'])['games']:
                out[row['executable_sha256']] = row['title']
    except (ValueError, KeyError, TypeError):
        return None
    return {k: v.strip() for k, v in out.items() if re.match(r'^[0-9a-f]{64}$', str(k))} or None


def _hash_node(reader, node):
    if node is None or stat.S_IFMT(node['mode']) != stat.S_IFREG or not 0 < node['size'] <= (512 << 20):
        raise ExtrasError("The card's game program could not be read.")
    digest = hashlib.sha256()
    for _offset, chunk in reader.read_file_chunks(node):
        digest.update(chunk)
    return digest.hexdigest()


def game_program_sha256(path, key_source=None):
    """``(platform, sha256)`` of the game program the card at *path* starts: the file its menu would be loaded
    into.  ExtrasError (or an OSError) when it cannot be told: a multi-boot card, a card that is not unlocked."""
    with open(path, 'rb') as f:
        parts = ssh_card._partitions(f)
        p2 = next((p for p in parts if p[0] == 2), None)
        if p2 is None:
            raise ExtrasError(NOT_OFFERED)
        f.seek(p2[2])
        if f.read(6) != b'LUKS\xba\xbe':
            p3 = next((p for p in parts if p[0] == 3 and p[1] == 0x83), None)
            if p3 is None:
                raise ExtrasError("The card's games partition was not found.")
            reader = Ext4Reader(f, p3[2], p3[3])
            node = ssh_card._node(reader, '/game')
            hops = 0
            while node is not None and stat.S_IFMT(node['mode']) == stat.S_IFLNK and hops < 4:
                target = reader.read_symlink(node)
                target = target.decode('utf-8', 'replace') if isinstance(target, bytes) else target
                node = ssh_card._node(reader, target if target.startswith('/') else '/' + target)
                hops += 1
            return SPIKE2, _hash_node(reader, node)
    from . import ssh_spike3
    from ..plugins.stern import spike3_modes
    with ssh_spike3.open_volume(path, 'games', key_source=key_source) as vol:
        reader = Ext4Reader(vol, 0, vol.size)
        state, target = spike3_modes.card_state(reader)
        if state not in ('stock', 'modes') or not target:
            raise ExtrasError("The card's game program could not be told (a multi-boot card starts several).")
        node = None
        if state == 'modes':                                # the program this app made for the card, when it did
            node = ssh_card._node(reader, '/' + spike3_modes.MODE_DIR + '/game.pad')
        return SPIKE3, _hash_node(reader, node or spike3_modes.game_program(reader, target))


def game_check(path, key_source=None):
    """Whether the installed release's menu knows the game program of the card at *path*:
    ``dict(known, text)`` with *known* True, False, or None when it cannot be told.  Never raises."""
    rec = card_plugins.installed(PLUGIN)
    if rec is None:
        return {'known': None, 'text': ''}
    try:
        platform, digest = game_program_sha256(path, key_source)
    except (OSError, ValueError, Ext4Error, struct.error, KeyError, TypeError):
        return {'known': None, 'text': ''}
    games = known_games(platform)
    if games is None:
        return {'known': None, 'text': ''}
    if digest in games:
        return {'known': True, 'text': "This card's game is one %s %s knows: %s." % (
            'spike-pinball-bluetooth', rec['tag'], games[digest])}
    return {'known': False, 'text': (
        "This card's game program is not one spike-pinball-bluetooth %s knows, so the game will run as it is, "
        'with no Bluetooth entry. It knows exact game versions only (%d of them for this kind of machine), and a '
        'game program this app has changed (Music Mode rows, editions) is not one of them.' % (rec['tag'], len(games)))}


def describe(info):
    if not info.get('supported'):
        return ''
    return ('spike-pinball-bluetooth %s, started with the game' % info['release'] if info.get('enabled')
            else 'no Bluetooth headphones (as shipped)')


def validate_request(original, project, key_source=None):
    """The project's saved choice (``{'enabled'}``) when a build must apply it, None when it never set one."""
    config = card_extras.load_bluetooth(project)
    if config is None:
        return None
    info = inspect_image(original, key_source=key_source)
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


def prepare_rootfs(part, work, on, members=None, tag='', cancel=None, platform=SPIKE2):
    """Bring the scratch plaintext ext filesystem *part* to the choice *on* (with the release *members* at *tag*),
    checked before and after."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    s3 = platform == SPIKE3
    ex = create_executor()
    _stop(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    commands, staged_n = [], [0]
    want = card_files(members, tag) if on else {}
    dirs = ('/usr', '/usr/local', DIR) if s3 else ('/usr', '/usr/local', '/usr/local/bin', '/etc', '/etc/init.d', DIR)

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
        state = inspect_root(r, platform)
        script = _read(r, MONITOR, 64 << 10)
        there = _names(r, DIR)
        if any(not re.match(r'^[A-Za-z0-9._-]{1,64}$', n) for n in there):
            raise ExtrasError('The Bluetooth folder on the card holds a file this app does not know.')
        if s3:
            want_script = s3_monitor_text(script, on).encode('utf-8')
        else:
            buttons = ssh_card._node(r, B.SO) is not None and (
                state['hooked'] or B.has_block(script, B.ALL_HOOK_LINES))
            want_script = B.monitor_text(script, buttons, mode=ssh_card._node(r, B.MODE_SO) is not None,
                                         menu=ssh_card._node(r, B.MENU_SO) is not None,
                                         bluetooth=on).encode('utf-8')
        if on:
            need = sum(len(d) + 4096 for d, _ in want.values()) + MARGIN
            if free_bytes(part) < need:
                raise ExtrasError("The card's system partition has %.1f MB free and Bluetooth headphones needs "
                                  '%.1f MB.' % (free_bytes(part) / 1e6, need / 1e6))
            for path in dirs:
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
            if not s3 and _read(r, WRAPPER, 64 << 10) != WRAPPER_TEXT.encode():
                put(r, WRAPPER, WRAPPER_TEXT.encode(), 0o755)
        else:
            for name in there:
                plain(r, DIR + '/' + name)
                commands.append('rm %s/%s' % (DIR, name))
            if ssh_card._node(r, DIR) is not None:
                commands.append('rmdir %s' % DIR)
            if not s3 and plain(r, WRAPPER) is not None:
                commands.append('rm %s' % WRAPPER)
        monitor = ssh_card.script_dest(r, MONITOR, 'Bluetooth')
        if want_script != script:
            put(r, monitor, want_script, 0o755)
    script_file = work / 'debugfs.commands'
    script_file.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script_file)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        after = inspect_root(r, platform)
        node = ssh_card.resolve(r, MONITOR)[1]
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


def note(on, tag='', platform=SPIKE2):
    if not on:
        return 'Bluetooth headphones: off, as Stern ships it.'
    return ('Bluetooth headphones: spike-pinball-bluetooth %s is on the card. %s' % (
        tag, "It uses the machine's own Bluetooth radio." if platform == SPIKE3
        else 'A Spike 2 machine needs a USB Bluetooth adapter.'))


def apply_to_build(original, output, config, log=None, cancel=None, key_source=None):
    """Put the project's choice *config* on the built image *output* (never *original*), or raise before success.
    Returns the line for the build's summary ('' when nothing is asked or nothing is on the card).  *key_source*
    is the user's Spike 3 key, as a Spike 3 build has it."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise ExtrasError('Invalid Bluetooth headphones option.')
    on = config['enabled']
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('Bluetooth headphones preparation must not write the original image.')
    keys = None
    if inspect_image(original, key_source=key_source)['platform'] == SPIKE3:
        from . import ssh_spike3
        try:
            keys = ssh_spike3.key_for(original, key_source)
        except ExtrasError:
            if not on:
                return ''
            raise ExtrasError(NO_KEY) from None
    dest = inspect_image(output, allow_pending=True, key_source=keys)
    if not dest['supported']:
        if not on:
            return ''
        raise ExtrasError(dest['reason'])
    platform = dest['platform']
    tag, members = '', None
    if on:
        try:
            tag, members = card_plugins.files(PLUGIN, ARCHES[platform])
        except PluginError as e:
            raise ExtrasError(str(e)) from None
    if (on and dest['enabled'] and dest['release'] == tag) or (not on and not (dest['hooked'] or dest['files'])):
        if log and on:
            log(note(on, tag, platform), 'info')
        return note(on, tag, platform) if on else ''
    _stop(cancel)

    def prepare(part, work):
        prepare_rootfs(part, work, on, members, tag, cancel=cancel, platform=platform)

    if platform == SPIKE3:
        from . import ssh_spike3
        ssh_spike3.rewrite_rootfs(output, prepare, keys, cancel=cancel, what='Bluetooth headphones', stop=_stop)
    else:
        _, _, start, size = dest['partition']
        if shutil.disk_usage(Path(output).parent).free < size + (64 << 20):
            raise ExtrasError('Not enough free space to prepare Bluetooth headphones on the system partition.')
        ssh_card.rewrite_partition(output, start, size, prepare, cancel, what='Bluetooth headphones', stop=_stop)
    after = inspect_image(output, allow_pending=True, key_source=keys)
    if after.get('enabled') != on or (on and after.get('release') != tag):
        raise ExtrasError('The Bluetooth headphones choice on the built image did not read back as written.')
    said = note(on, tag, platform)
    if log:
        log(said, 'info')
    if on:
        # the card as built: a build that changed the game program made one the menu does not know
        check = game_check(output, keys)
        if check['known'] is False:
            if log:
                log(check['text'], 'warning')
            said += '\n' + check['text']
    return said


# ------------------------------------------------------------------ on the machine, over remote access
#: His launcher switches itself off (the file DISABLED, on the machine's own data) after a game that ended badly,
#: and nothing a card write does brings it back: that file is not on the card.  The Plugins tab asks the machine,
#: and takes the mark away when it is there.
STATUS = ('[ -f ' + ENABLED + ' ] && echo on-card; [ -e ' + DISABLED + ' ] && echo switched-off; '
          'echo "release $(cat ' + RELEASE + ' 2>/dev/null)"; pidof spikebt >/dev/null 2>&1 && echo helper-running; '
          'true')


def parse_status(text):
    """``dict(on_card, switched_off, release, helper)`` from :data:`STATUS`'s answer."""
    lines = [l.strip() for l in (text or '').splitlines()]
    release = next((l.split(None, 1)[1] for l in lines if l.startswith('release ') and len(l.split()) == 2), '')
    return {'on_card': 'on-card' in lines, 'switched_off': 'switched-off' in lines,
            'release': release if card_plugins.TAG.match(release) else '', 'helper': 'helper-running' in lines}


def check_machine(machine):
    """Ask a connected ``remote_send`` machine how the plugin is doing there and, when its launcher has switched
    itself off, switch it back on.  The sentence to show."""
    def sh(script):
        answer = machine.sh(script, timeout=20, check=False)
        return answer[1] if isinstance(answer, tuple) else answer
    state = parse_status(sh(STATUS))
    if not state['on_card']:
        return ("This machine's card has no Bluetooth headphones on it. Tick it here and write the card from "
                'this project.')
    what = 'spike-pinball-bluetooth %s is on the machine' % (state['release'] or '(a release this app did not put on)')
    if state['switched_off']:
        sh('rm -f ' + DISABLED)
        if parse_status(sh(STATUS))['switched_off']:
            raise ExtrasError('%s and has switched itself off; the mark could not be taken away.' % what)
        return ('%s. It had switched itself off after a game that ended badly; it is switched back on, from the '
                'next time the game starts (restart the game on the Network tab, or switch the machine off and on).'
                % what)
    return '%s and switched on%s.' % (what, ', and its helper is running' if state['helper'] else
                                      '; its helper is not running, which is normal on a game version it does '
                                      'not know or with no Bluetooth adapter')
