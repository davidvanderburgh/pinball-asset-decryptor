"""PAD-1467: a Spike 2 card whose Wi-Fi joins the network at the first attempt, and can use 5 GHz.

Two choices, both the project's ``extras.wifi`` (core/card_extras.py), both put on a build's system partition the
checked way remote access is (core/ssh_card.py): a scratch copy changed with debugfs, read back, then written in.

**Wi-Fi start-up** (``enabled``).  Stern's game tells its connectivity agent to bring Wi-Fi up with ``wpa-driver
wext``, the old wireless-extensions interface.  The card's wpa_supplicant (2.3) and its Realtek USB drivers are
cfg80211 ones, and through wext every join logs "Association request to the driver failed": on 2.4 GHz a retry
usually gets through after a while, which is the machine that takes minutes to appear on the network, or never
does.  The card's own start-up hook, ``/etc/network/if-pre-up.d/wpa-supplicant``, reads
``/etc/wpa_supplicant/driver.<interface>`` first and uses what it says as the driver name; the shipped card has no
such file.  This writes that one file with ``nl80211,wext``: nl80211 first, wext still there for an adapter whose
driver cannot do nl80211.  No script is edited.

**5 GHz** (``band5``, needs the first).  Stern's driver for the AC1200 adapter (RTL8822BU; ``8812bu.ko``, Realtek
v5.3.1 of April 2018) associates on 5 GHz and is dropped at once by a current access point (reason 34, frames not
acknowledged), whatever its parameters.  Realtek's v5.8.7.1 (November 2019) holds the link.  This puts that driver
at the path Stern's start-up script already loads (``/usr/local/spike/8812bu.ko``), and adds a small helper that,
once the machine has joined on 2.4 GHz, asks wpa_supplicant to move to the same network's 5 GHz access point.  A
kernel module fits one kernel build only: the card qualifies when the driver it ships was built for the kernel the
bundled one was (``KERNEL``), so a card with another kernel is refused, not guessed at.

Measured on David's Godzilla LE with an eero, 2026-11-20 (docs/plans/spike2-wifi-5ghz.md): wext, nine joins of nine
failed in 150 s on one access point; nl80211, joined at the first attempt in 14 to 16 s on every start; Stern's
driver, 12 of 12 5 GHz attempts dropped; the newer driver, on 5 GHz (channel 40, 80 MHz) within a minute of a
plain restart.

The bundled driver is Realtek's GPL-2.0 source, unmodified, built against the public kernel tree the card's kernel
came from; resources/wifi/README.md says where the source is and how it was built."""

import hashlib
import os
import shutil
import stat
import struct
from pathlib import Path

from . import card_extras, ssh_card
from .card_extras import ExtrasError
from .executor import create_executor
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

RESOURCES = Path(__file__).resolve().parents[1] / 'resources' / 'wifi'

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

#: the kernel build the bundled adapter driver was made for (its vermagic), and so the only one it loads on
KERNEL = '3.14.28_1.0.0_ga-wandboard+g08f5291'
VERMAGIC = b'vermagic=' + KERNEL.encode() + b' '
#: where Stern's start-up script loads the AC1200 adapter's driver from
MODULE = '/usr/local/spike/8812bu.ko'
NEW_MODULE = RESOURCES / '88x2bu.ko'
NEW_MODULE_SHA256 = '7a2194e4cda4bbd3d4f01c3627fbf75e95080f731df12930493aedaa6239ea3d'
NEW_VERSION = 'v5.8.7.1_35809.20191129'
OLD_VERSION = 'v5.3.1_27678.20180430'
HELPER = '/usr/local/bin/pad-wifi-band'
INIT = '/etc/init.d/padwifi'
LINK = '/etc/rc5.d/S31padwifi'
LINK_TARGET = '../init.d/padwifi'
#: (card path, bundled file, mode) for the 5 GHz choice's own files, besides the driver
BAND_FILES = ((HELPER, 'pad-wifi-band', 0o755), (INIT, 'padwifi', 0o755))
BAND_DIRS = ('/usr', '/usr/local', '/usr/local/bin', '/usr/local/spike', '/etc', '/etc/init.d', '/etc/rc5.d')

#: David (PAD-1467): "be more technically specific about the settings we are changing so that users can have
#: confidence in what this option does".  The Network tab shows these rows as they are: (what, value, in code type)
DETAILS = (
    ('File added to the card', OVERRIDE + ' (system partition, owner root, permissions 644)', True),
    ('What the file says', DRIVER.decode(), True),
    ('Read by', HOOK + ", Stern's own start-up script, which is not changed", True),
    ('wpa_supplicant then starts with', '-D ' + DRIVER.decode() + '   (as shipped: -D wext)', True),
    ('What that means', 'wpa_supplicant talks to the Wi-Fi adapter through nl80211, the current Linux Wi-Fi '
     'interface, in place of wext, the older one. If nl80211 cannot start for an adapter, it uses wext as before.',
     False),
    ('Not changed', 'The game, the Wi-Fi driver modules (8812bu.ko, 8192eu.ko, 8188eu.ko), '
     '/etc/wpa_supplicant.conf, and your network name, password and band.', False),
    ('To undo', 'Untick it and write the card (or Send to machine): the file is taken off again.', False),
)
BAND_DETAILS = (
    ('File replaced on the card', MODULE + ' (system partition): the driver for the AC1200 USB adapter, '
     'Realtek RTL8822BU', True),
    ('Driver as shipped', 'Realtek rtl88x2bu ' + OLD_VERSION + ' (April 2018)', True),
    ('Driver with this option', 'Realtek rtl88x2bu ' + NEW_VERSION + ' (November 2019), unmodified GPL source, '
     'built for kernel ' + KERNEL, True),
    ('Files added', HELPER + ', ' + INIT + ', ' + LINK, True),
    ('What the added files do', 'A short shell script, started with the machine. Once the machine has joined '
     'your network on 2.4 GHz, it asks wpa_supplicant to move to the same network\'s 5 GHz access point '
     '(wpa_cli roam) when one is in reach. If the move fails the machine stays on 2.4 GHz, and after three '
     'failed moves the script stops asking until the next start.', False),
    ('Menu wording', 'The game\'s network menus stop saying "2.4GHz" (for one, "Find 2.4GHz WiFi Network" '
     'becomes "Find WiFi Network"). The words are changed in the game program; nothing else in it is.', False),
    ('Not changed', "Stern's start-up script, the other adapters' drivers (8192eu.ko, 8188eu.ko), "
     '/etc/wpa_supplicant.conf, and your network name and password.', False),
    ('To undo', "Untick it and write the card (or Send to machine): Stern's driver is put back from the "
     'original card and the added files are taken off.', False),
)
#: David (PAD-1467): "show rough comparisons of stock, all the way to 5GHz ... how ticking each box can help", and
#: then "i don't want all of the 'not measured yet' items in there".  One row per box, each on top of the one
#: before; every figure is one measured on his Godzilla LE (docs/plans/spike2-wifi-5ghz.md has each run).  The
#: 2.4 GHz speed is the encrypted connection's, the only one timed on that band, so it is given as a floor.
COMPARE_HEAD = ('', 'Joins Wi-Fi', 'Band', 'Send to machine')
COMPARE = (
    ('As shipped', 'Often minutes, sometimes never', '2.4 GHz', 'At least 2 MB a second'),
    ('+ Reliable start-up', 'At the first try, about 15 s', '2.4 GHz', 'At least 2 MB a second'),
    ('+ 5 GHz driver', 'At the first try', '5 GHz', '7 to 13 MB a second'),
)
#: behind "How these were measured" on the tab (David: the panel read as a wall of text)
COMPARE_NOTE = ("Rough figures from one machine: a Godzilla LE with an AC1200 (RTL8822BU) adapter, an eero router in the "
                'same room, 24 to 64 MB files. Yours will differ with distance and router. Send to machine needs '
                'remote access on the card. The 2.4 GHz speed is what the encrypted connection did there; big '
                'files now go over plain connections, each piece signed and checked, which were timed on 5 GHz. '
                "Encrypted, 5 GHz reached 3.4 MB a second: the machine's processor, not the radio, is the limit "
                'there. A 1 GB update is about 9 minutes at 2 MB a second and about 2 at 10: worked out from the '
                'speeds, not timed.')
#: David (PAD-1467): "add a comparison for the stock adapter vs. the one we bought ... (does the stock not support
#: 5GHz?)".  The card's start-up script (/etc/init.d/game) loads three adapter drivers; two are for chips with a
#: 2.4 GHz radio only.  Bands and link rates are the chips' own (Realtek's figures), not measurements.
ADAPTER_HEAD = ('Adapter (the chip inside)', 'Bands', 'Fastest link, on paper', 'What the two boxes do for it')
ADAPTERS = (
    ('N150 adapters: Realtek RTL8188EU (driver 8188eu.ko)', '2.4 GHz only', '150 Mbit/s',
     'First box: start-up through nl80211, or wext as before if the driver has no nl80211. Second box: nothing; '
     'the chip has no 5 GHz radio.'),
    ('N300 adapters: Realtek RTL8192EU (driver 8192eu.ko)', '2.4 GHz only', '300 Mbit/s',
     'The same as the row above.'),
    ('AC1200 adapters: Realtek RTL8822BU (driver 8812bu.ko)', '2.4 GHz and 5 GHz',
     '867 Mbit/s on 5 GHz, 300 Mbit/s on 2.4 GHz',
     'Both boxes: joins at the first try, then moves to 5 GHz. This is the adapter the figures above were '
     'measured with.'),
)
ADAPTER_NOTE = ('These are the three kinds of USB Wi-Fi adapter a Spike 2 machine has drivers for. An adapter with a '
                '2.4 GHz-only chip cannot join 5 GHz whatever is on the card; for 5 GHz the machine needs an AC1200 '
                '(RTL8822BU) adapter. The first two rows were not tried on a machine.')
#: the game program's own network-menu wording, and what it becomes with the 5 GHz choice on (each shorter, so it is
#: written in place; plugins/stern/engine.py adds these to a build's program text)
MENU_TEXT = (
    ('Available 2.4GHz WiFi networks', 'Available WiFi networks'),
    ('No 2.4GHz WiFi networks found.', 'No WiFi networks found.'),
    ('Scanning for 2.4GHz WiFi networks', 'Scanning for WiFi networks'),
    ('Enter name for private 2.4GHz WiFi network.', 'Enter name for private WiFi network.'),
    ('Private 2.4GHz WiFi Network', 'Private WiFi Network'),
    ('Find 2.4GHz WiFi Network', 'Find WiFi Network'),
)

NOT_SPIKE2 = 'The Wi-Fi start-up option is for Stern Spike 2 cards.'
NO_HOOK = ("This card's system does not have the Wi-Fi start-up hook this option uses, so it is left as it is.")
FOREIGN = ('This card already names its own Wi-Fi driver (%s); it will not be overwritten.')
OTHER_KERNEL = ("The newer adapter driver was built for one system version (kernel %s). This card's system has "
                'another, so its own driver is left in place.' % KERNEL)
NO_STERN_DRIVER = ("The original card already carries the newer adapter driver, so Stern's own cannot be put "
                   'back from it. Use the card image Stern shipped as the original.')


def offered(mfr):
    """True when the options apply to cards of *mfr* as it is set now (Stern Spike 2)."""
    return getattr(mfr, 'key', '') == 'stern' and getattr(mfr, '_era', 'spike2') == 'spike2'


def describe(info):
    """What the card at hand has now, for the Network tab: ``-D wext`` as shipped, or ours."""
    if not info.get('supported'):
        return ''
    return ('-D ' + DRIVER.decode() + ' (this option is already on the card)') if info.get('enabled') \
        else '-D wext (as shipped)'


def describe_band(info):
    """The adapter driver the card at hand has now, for the Network tab."""
    if not info.get('supported') or not info.get('band5_supported'):
        return ''
    return ('rtl88x2bu ' + NEW_VERSION + ' (this option is already on the card)') if info.get('band5') \
        else 'rtl88x2bu ' + OLD_VERSION + ' (as shipped)'


def menu_text(project):
    """``{shipped words: new words}`` for the game program when *project* has the 5 GHz choice on, else ``{}``."""
    try:
        rec = card_extras.load_wifi(project)
    except ExtrasError:
        return {}
    return dict(MENU_TEXT) if rec and rec['enabled'] and rec['band5'] else {}


def new_module_bytes():
    """The bundled driver, checked against the hash it was committed with."""
    try:
        data = NEW_MODULE.read_bytes()
    except OSError:
        raise ExtrasError('The bundled adapter driver is missing from this copy of the app.') from None
    if hashlib.sha256(data).hexdigest() != NEW_MODULE_SHA256 or VERMAGIC not in data:
        raise ExtrasError('The bundled adapter driver has an unexpected hash.')
    return data


def band_payload():
    """``{card path: (bytes, mode)}`` for everything the 5 GHz choice writes.  Scripts go on with LF line ends
    whatever the host (a Windows checkout gives them CRLF, which the card's /bin/sh cannot run)."""
    out = {MODULE: (new_module_bytes(), 0o644)}
    for dest, name, mode in BAND_FILES:
        out[dest] = ((RESOURCES / name).read_bytes().replace(b'\r\n', b'\n'), mode)
    return out


def _fail(text):
    raise ExtrasError(text)


def _read(reader, path, limit):
    try:
        return ssh_card._read(reader, path, limit)
    except ExtrasError:
        _fail('A Wi-Fi system file on the card has an unsafe type or size.')


def _is_ours(module):
    return hashlib.sha256(module).hexdigest() == NEW_MODULE_SHA256


def inspect_root(reader):
    """The Wi-Fi state of the Spike 2 system filesystem behind *reader*:
    ``{'enabled', 'band5', 'band5_supported', 'band5_reason'}``, or ExtrasError when the card does not qualify at
    all (no hook that reads the override, a wpa_supplicant without nl80211, or an override of its own)."""
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
    enabled = False
    if node is not None:
        if stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1:
            _fail('The card has something unexpected where its Wi-Fi driver setting goes.')
        said = _read(reader, OVERRIDE, 4096).strip()
        if said != DRIVER:
            _fail(FOREIGN % (said[:40].decode('ascii', 'replace') or 'an empty file'))
        enabled = True
    info = {'enabled': enabled, 'band5': False, 'band5_supported': False, 'band5_reason': OTHER_KERNEL,
            'stern_module': True}
    mod = ssh_card._node(reader, MODULE)
    if mod is None or stat.S_IFMT(mod['mode']) != stat.S_IFREG or mod['links'] != 1 or mod['size'] > (16 << 20):
        return info
    module = _read(reader, MODULE, 16 << 20)
    if VERMAGIC not in module or MODULE.encode() not in game:
        return info
    info.update(band5_supported=True, band5_reason='', stern_module=not _is_ours(module))
    link = ssh_card._node(reader, LINK)
    info['band5'] = bool(_is_ours(module) and link is not None and stat.S_IFMT(link['mode']) == stat.S_IFLNK
                         and reader.read_symlink(link) == LINK_TARGET
                         and all(ssh_card._node(reader, dest) is not None for dest, _n, _m in BAND_FILES))
    return info


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
    """Never raises: ``{'supported', 'reason', 'enabled', 'band5', 'band5_supported', 'band5_reason'}`` (and
    ``'partition'`` when supported) for the card image at *path*."""
    try:
        info = _inspect(path, allow_pending=allow_pending)
        info.update(supported=True, reason='')
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        reason = str(e).replace('Remote access (SSH) needs', 'This option needs')
        return {'supported': False, 'reason': reason, 'enabled': False, 'band5': False,
                'band5_supported': False, 'band5_reason': reason, 'stern_module': True}


def _wanted(config):
    return bool(config['enabled']), bool(config['enabled'] and config.get('band5'))


def _stern_module(original):
    """The bytes of Stern's own adapter driver from the *original* card image (what the 5 GHz choice puts back)."""
    with open(original, 'rb') as f:
        parts = ssh_card._partitions(f)
        p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
        if p2 is None:
            _fail(NOT_SPIKE2)
        module = _read(Ext4Reader(f, p2[2], p2[3]), MODULE, 16 << 20)
    if not module or VERMAGIC not in module or _is_ours(module):
        _fail(NO_STERN_DRIVER)
    return module


def validate_request(original, project):
    """The project's saved choice (``{'enabled', 'band5'}``) when a build must apply it, None when the project
    never set it.  ExtrasError when it asks for something *original* cannot take."""
    config = card_extras.load_wifi(project)
    if config is None:
        return None
    on, band = _wanted(config)
    info = inspect_image(original)
    if not info['supported']:
        if not on:
            return None                     # nothing to take off a card that cannot carry it
        raise ExtrasError(info['reason'])
    if band and not info['band5_supported']:
        raise ExtrasError(info['band5_reason'])
    return config


def guard_flash(project, image):
    """Flash-only may use a finished image, never one that lacks the project's pending Wi-Fi choices."""
    config = validate_request(image, project)
    if config is None:
        return
    on, band = _wanted(config)
    state = inspect_image(image)
    if state['enabled'] != on or state['band5'] != band:
        raise ExtrasError('Build the complete image first to apply the pending Wi-Fi change, then flash '
                          'that build.')


def _cancel(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('Wi-Fi preparation canceled.')


def _command(ex, program, *args):
    try:
        return ssh_card._command(ex, program, *args)
    except ExtrasError:
        raise ExtrasError('Wi-Fi preparation failed running %s; no completed build was produced.' % program) from None


def _band_left(reader):
    """True when any of the 5 GHz choice's own files is on the filesystem behind *reader*."""
    return (ssh_card._node(reader, LINK) is not None
            or any(ssh_card._node(reader, dest) is not None for dest, _n, _m in BAND_FILES))


def _verify(reader, on, band, payload, stern):
    node = ssh_card._node(reader, OVERRIDE)
    if not on:
        if node is not None:
            raise ExtrasError('The Wi-Fi driver setting could not be taken off the card.')
    else:
        directory = ssh_card._node(reader, DIR)
        if (node is None or node['mode'] != stat.S_IFREG | 0o644 or node['uid'] or node['gid'] or node['links'] != 1
                or _read(reader, OVERRIDE, 4096) != CONTENT
                or directory is None or directory['mode'] != stat.S_IFDIR | 0o755 or directory['uid']
                or directory['gid']):
            raise ExtrasError('The Wi-Fi driver setting on the card did not read back as written.')
    if band:
        for dest, (data, mode) in payload.items():
            got = ssh_card._node(reader, dest)
            if (got is None or got['mode'] != stat.S_IFREG | mode or got['uid'] or got['gid'] or got['links'] != 1
                    or _read(reader, dest, 16 << 20) != data):
                raise ExtrasError('The adapter driver files on the card did not read back as written.')
        link = ssh_card._node(reader, LINK)
        if link is None or stat.S_IFMT(link['mode']) != stat.S_IFLNK or reader.read_symlink(link) != LINK_TARGET:
            raise ExtrasError('The Wi-Fi helper start-up link did not read back as written.')
    elif _band_left(reader) or (stern is not None and _read(reader, MODULE, 16 << 20) != stern):
        raise ExtrasError("Stern's adapter driver could not be put back on the card.")


def prepare_rootfs(part, work, config, stern_module=None, cancel=None):
    """Bring a scratch plaintext ext filesystem *part* to the Wi-Fi state *config* asks for, checked before and
    after; never a card.  *stern_module* is the original card's own adapter driver, needed only to take the 5 GHz
    choice off again."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    on, band = _wanted(config)
    ex = create_executor()
    _cancel(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    commands, payload, stern = [], {}, None

    def stage(name, data):
        staged = work / name
        staged.write_bytes(data)
        src = ex.to_exec_path(str(staged))
        if any(c in src for c in ('"', '\n', '\r', '\\')):
            raise ExtrasError('The staging path contains unsupported filesystem-tool characters.')
        return src

    def put(reader, dest, src, mode):
        if ssh_card._node(reader, dest) is not None:
            commands.append('rm %s' % dest)
        commands.append('write "%s" %s' % (src, dest))
        for field, val in (('mode', '0100%o' % mode), ('uid', '0'), ('gid', '0')):
            commands.append('set_inode_field %s %s %s' % (dest, field, val))

    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        state = inspect_root(r)             # refuses a symlink, a hard link or an override that is not ours
        directory = ssh_card._node(r, DIR)
        if on:
            if directory is None:
                commands.append('mkdir %s' % DIR)
            if not state['enabled']:
                put(r, OVERRIDE, stage('driver.wlan0', CONTENT), 0o644)
            for field, val in (('mode', '040755'), ('uid', '0'), ('gid', '0')):
                commands.append('set_inode_field %s %s %s' % (DIR, field, val))
        elif state['enabled']:
            commands.append('rm %s' % OVERRIDE)
            names = [name for name, _, _ in r._iter_dir(directory) if name not in ('.', '..')]
            if names == [os.path.basename(OVERRIDE)]:
                commands.append('rmdir %s' % DIR)        # the folder was ours: the card goes back as shipped
        if band:
            if not state['band5_supported']:
                raise ExtrasError(state['band5_reason'])
            payload = band_payload()
            for path in BAND_DIRS:
                node = ssh_card._node(r, path)
                if node is not None and stat.S_IFMT(node['mode']) != stat.S_IFDIR:
                    raise ExtrasError('A Wi-Fi destination folder on the card is a link or special file.')
                if node is None:
                    commands.append('mkdir %s' % path)
            for i, (dest, (data, mode)) in enumerate(payload.items()):
                node = ssh_card._node(r, dest)
                if node is not None and (stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1):
                    raise ExtrasError('A Wi-Fi destination on the card is a link or hard-linked file.')
                put(r, dest, stage('band%d' % i, data), mode)
            if ssh_card._node(r, LINK) is not None:
                commands.append('rm %s' % LINK)
            commands.append('symlink %s %s' % (LINK, LINK_TARGET))
        elif not state['stern_module'] or _band_left(r):
            if not state['stern_module']:
                if stern_module is None:
                    raise ExtrasError(NO_STERN_DRIVER)
                put(r, MODULE, stage('stern.ko', stern_module), 0o644)
                stern = stern_module
            for dest in (LINK,) + tuple(d for d, _n, _m in BAND_FILES):
                if ssh_card._node(r, dest) is not None:
                    commands.append('rm %s' % dest)
    script = work / 'debugfs.commands'
    script.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        _verify(Ext4Reader(f, 0, size), on, band, payload, stern)


def note(on, band):
    """The build summary's line for a Wi-Fi state."""
    if band:
        return ('Wi-Fi: joins with the nl80211 driver interface; adapter driver rtl88x2bu %s, moves to 5 GHz '
                'when in reach.' % NEW_VERSION)
    return ('Wi-Fi start-up: the machine joins with the nl80211 driver.' if on
            else 'Wi-Fi start-up: as Stern ships it.')


def apply_to_build(original, output, config, log=None, cancel=None):
    """Put the project's Wi-Fi choices *config* on the built image *output* (a copy, never *original*), or raise
    before success.  Returns the line for the build's summary ('' when *config* is None or nothing had to change).

    As with remote access, a failure may leave *output* with a part-written system partition: the pipeline
    quarantines it."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool or type(config.get('band5', False)) is not bool:
        raise ExtrasError('Invalid Wi-Fi option.')
    on, band = _wanted(config)
    ssh_card._regular(original)
    ssh_card._regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('Wi-Fi preparation must not write the original image.')
    dest = inspect_image(output, allow_pending=True)
    if not dest['supported']:
        raise ExtrasError(dest['reason'])
    if band and not dest['band5_supported']:
        raise ExtrasError(dest['band5_reason'])
    text = note(on, band)
    if dest['enabled'] == on and dest['band5'] == band and (band or dest['stern_module']):
        if log and on:
            log(text, 'info')
        return text if on else ''
    _cancel(cancel)
    stern = None
    if not band and not dest['stern_module']:
        stern = _stern_module(original)
    _, _, start, size = dest['partition']
    if shutil.disk_usage(Path(output).parent).free < size + (48 << 20):
        raise ExtrasError('Not enough free space to prepare the Wi-Fi options on the system partition.')
    ssh_card.rewrite_partition(
        output, start, size,
        lambda part, work: prepare_rootfs(part, work, {'enabled': on, 'band5': band}, stern, cancel=cancel),
        cancel, what='Wi-Fi', stop=_cancel)
    after = inspect_image(output, allow_pending=True)
    if after.get('enabled') != on or after.get('band5') != band:
        raise ExtrasError('The Wi-Fi options on the built image did not read back as written.')
    if log:
        log(text, 'info')
    return text
