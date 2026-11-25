"""Checked, offline SSH changes to image copies. Platform qualification is explicit."""

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import stat
import struct
import tempfile

from . import card_extras
from .card_extras import ExtrasError
from .executor import create_executor
from .rawdevice import is_device_path
from ..plugins.stern.ext4 import Ext4Reader, Ext4Error

# Add entries ONLY with committed functional emulator evidence for this adapter.
QUALIFIED_PLATFORMS = {'stern-spike2', 'stern-spike3',  # docs/validation/2026-11-17-extras-ssh*.md
                       'jjp'}  # PAD-1587: docs/validation/2026-11-25-pad-1587-jjp-remote-access.md
RESOURCES = Path(__file__).resolve().parents[1] / 'resources' / 'ssh'
HASHES = {
    'dropbear': '01ccdc69e1047f3c301fad7f0de7d522dde16a5c8cc6684d6846d54714dfe236',
    'dropbearkey': 'd6fbc9fa5042c9c6af5c8da0f4813995a2c81fe6cc0258554abd054caa6e0d76',
    'sftp-server': 'bd8396f4b450b371b9762f2b879229434b084316ae8ca77110af7205461f09e9',
}
HOOK = '/etc/rc5.d/S30sshd'
HOOK_TARGET = '../init.d/sshd'
FILES = {'dropbear': '/usr/local/bin/dropbear', 'dropbearkey': '/usr/local/bin/dropbearkey',
         'sftp-server': '/usr/libexec/sftp-server', 'sshd': '/etc/init.d/sshd',
         'authorized_keys': '/home/root/.ssh/authorized_keys'}
DIRS = ('/usr', '/usr/local', '/usr/local/bin', '/usr/libexec', '/etc', '/etc/init.d',
        '/etc/rc5.d', '/home', '/home/root', '/home/root/.ssh')


#: the card eras remote access is qualified on (emulator-proven, PR #38)
ERAS = ('spike2', 'spike3')


#: PAD-1587: the other makers remote access is qualified on (an install ISO the JJP Write builds)
MAKERS = ('jjp',)


def offered(mfr):
    """True when remote access can go on a card of *mfr* as it is set now (Stern Spike 2 or Spike 3, or a JJP
    install, PAD-1587).

    PAD-1399: the Network tab's rail gate and the tab itself both ask this, so the tab is never hidden on an era
    remote access supports (it was gated on the Spike 2 mode runtime, and so vanished on Spike 3)."""
    key = getattr(mfr, 'key', '')
    if key in MAKERS:
        return True
    return key == 'stern' and getattr(mfr, '_era', 'spike2') in ERAS


def layout(platform='stern-spike2'):
    if platform == 'stern-spike2':
        return dict(files=FILES, dirs=DIRS, hook=HOOK, target=HOOK_TARGET,
                    linked=True, ssh_dir='/home/root/.ssh', arch='armv7', hashes=HASHES)
    if platform == 'stern-spike3':
        from .ssh_spike3 import AARCH64_HASHES
        files = dict(FILES, sshd='/etc/init.d/sshd',
                     authorized_keys='/root/.ssh/authorized_keys',
                     **{'sftp-server': '/usr/local/libexec/pad-sftp-server'})
        return dict(files=files, dirs=('/usr', '/usr/local', '/usr/local/bin',
                    '/usr/local/libexec', '/etc', '/etc/init.d', '/root', '/root/.ssh'),
                    hook='/etc/init.d/S60padsshd', target='sshd', linked=True, ssh_dir='/root/.ssh',
                    arch='aarch64', hashes=AARCH64_HASHES)
    if platform == 'jjp':
        from . import ssh_jjp
        return ssh_jjp.layout()
    raise ExtrasError('SSH has not been qualified for this card platform.')

def ensure_not_incomplete(path, links_ok=True):
    """Refuse an image a failed SSH preparation left behind.

    *links_ok* False also refuses a hard-linked image, whose pending marker
    could sit beside another of its names: only where SSH is in play.  A card
    read as a source, or built/emulated without SSH, may be hard-linked (a
    library sharing one file between two folders) and is never written here.
    """
    if not path:
        return
    real = os.path.realpath(path)
    if (str(path).endswith('.ssh-incomplete') or real.endswith('.ssh-incomplete')
            or pending_marker(path).exists() or os.path.exists(str(path) + '.ssh-pending')):
        raise ExtrasError('This image has incomplete SSH preparation; rebuild it from the original before use.')
    if not links_ok and os.path.isfile(real) and os.stat(real).st_nlink != 1:
        raise ExtrasError('Incomplete SSH preparation status cannot be verified for a hard-linked image; use a separate image copy.')


def pending_marker(path):
    return Path(os.path.realpath(path) + '.ssh-pending')


def _regular(path, allow_pending=False, writable=False):
    if not path or is_device_path(str(path)) or not os.path.isfile(path):
        raise ExtrasError('Remote access (SSH) needs a regular card image file, not a device.')
    if not allow_pending:
        ensure_not_incomplete(path)
    if writable and os.stat(path).st_nlink != 1:
        # writing one name of a hard link would change the other as well
        raise ExtrasError('Hard-linked card images cannot be used for SSH preparation.')


def validate_output(original, output):
    _regular(original)
    if not output or is_device_path(str(output)):
        raise ExtrasError('SSH preparation requires an output image file, not a device.')
    if os.path.lexists(output) and not os.path.isfile(output):
        raise ExtrasError('The SSH output must be a regular image file, not a directory, link target or special file.')
    if os.path.islink(output) or (os.path.exists(output) and os.stat(output).st_nlink != 1):
        raise ExtrasError('The SSH output must not be a symlink or hard-linked image.')
    if (os.path.normcase(os.path.realpath(original)) == os.path.normcase(os.path.realpath(output))
            or (os.path.exists(output) and os.path.samefile(original, output))):
        raise ExtrasError('SSH preparation must not write the original image or an alias of it.')


def _partitions(stream, size=None):
    if size is None:
        size = os.fstat(stream.fileno()).st_size
    stream.seek(0)
    mbr = stream.read(512)
    if len(mbr) != 512 or mbr[510:] != b'\x55\xaa':
        raise ExtrasError('The image has no supported MBR partition table.')
    parts = []
    for i in range(4):
        p = mbr[446 + i * 16:462 + i * 16]
        start, count = struct.unpack_from('<II', p, 8)
        if count:
            lo, n = start * 512, count * 512
            if lo < 512 or lo + n > size:
                raise ExtrasError('A card partition lies outside the image.')
            parts.append((i + 1, p[4], lo, n))
    ordered = sorted(parts, key=lambda p: p[2])
    if any(a[2] + a[3] > b[2] for a, b in zip(ordered, ordered[1:])):
        raise ExtrasError('The card has overlapping primary partitions.')
    return parts


def _node(reader, path):
    node = reader.read_inode(2)
    for name in path.strip('/').split('/'):
        if stat.S_IFMT(node['mode']) != stat.S_IFDIR:
            raise ExtrasError('An SSH system directory is not a directory.')
        ino = next((ino for nm, ino, _ in reader._iter_dir(node) if nm == name), None)
        if ino is None:
            return None
        node = reader.read_inode(ino)
    return node


def _read(reader, path, limit=256 * 1024):
    node = _node(reader, path)
    if node is None:
        return b''
    if stat.S_IFMT(node['mode']) != stat.S_IFREG or node['size'] > limit:
        raise ExtrasError('An SSH-related file has an unsafe type or size.')
    return reader.read_file_bytes(node)


def _managed(reader):
    script = _read(reader, '/etc/init.d/sshd')
    return (b'# PAD key-only SSH' in script or
            (b'DAEMON=/usr/local/bin/dropbear' in script and b'KEYDIR=/data/dropbear' in script))


def _inspect(path, allow_pending=False, key_source=None):
    _regular(path, allow_pending=allow_pending)
    from . import ssh_jjp
    if ssh_jjp.is_iso(path):
        # PAD-1587: a JJP install ISO (its root is partclone inside; a PAD build's Send record says what it carries)
        return ssh_jjp.inspect_iso(path)
    with open(path, 'rb') as f:
        parts = _partitions(f)
        p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
        if p2 is None:
            raise ExtrasError('SSH has not been qualified for this card platform.')
        f.seek(p2[2])
        if f.read(6) == b'LUKS\xba\xbe':
            from . import ssh_spike3
            return ssh_spike3.inspect_image(path, key_source=key_source)
        return inspect_spike2(f, p2)


def system_partition(f, size):
    """``(partition, encrypted)``: the card's system partition (p2) in the open stream *f* of *size* bytes, and
    whether it is a Spike 3 LUKS volume (PAD-1427: an SD card is read as a stream, not an image path)."""
    parts = _partitions(f, size)
    p2 = next((p for p in parts if p[0] == 2 and p[1] == 0x83), None)
    if p2 is None:
        raise ExtrasError('SSH has not been qualified for this card platform.')
    f.seek(p2[2])
    return p2, f.read(6) == b'LUKS\xba\xbe'


def inspect_spike2(f, p2):
    """The remote access state of the Spike 2 system partition *p2* in the open stream *f*, or ExtrasError when
    it is not the qualified Spike 2 layout."""
    r = Ext4Reader(f, p2[2], p2[3])
    passwd = _read(r, '/etc/passwd')
    game = _read(r, '/etc/init.d/game', 1024 * 1024)
    fstab = _read(r, '/etc/fstab')
    init = _read(r, '/etc/inittab')
    if (b':/home/root:/bin/sh' not in passwd or b'/usr/local/spike' not in game
            or b'spike2' not in game or b'/dev/mmcblk0p5' not in fstab
            or b'/etc/init.d/rc 5' not in init):
        raise ExtrasError('SSH has not been qualified for this card platform.')
    return inspect_root(r, 'stern-spike2', p2)



def inspect_root(r, platform, partition):
    l = layout(platform)
    files = l['files']
    script = _read(r, files['sshd'])
    managed = (b'# PAD key-only SSH' in script or (platform == 'stern-spike2' and
               b'DAEMON=/usr/local/bin/dropbear' in script and b'KEYDIR=/data/dropbear' in script))
    hook = _node(r, l['hook'])
    if hook is not None and l['linked'] and (stat.S_IFMT(hook['mode']) != stat.S_IFLNK
                              or r.read_symlink(hook) != l['target']):
        raise ExtrasError('The SSH boot hook belongs to an unrecognized service.')
    if _node(r, files['sshd']) is not None and not managed:
        raise ExtrasError('The card has an unrecognized SSH service; it will not be overwritten.')
    if not managed and any(_node(r, files[name]) is not None for name in
                           ('dropbear', 'dropbearkey', 'sftp-server')):
        raise ExtrasError('The card has an unrecognized SSH payload; it will not be overwritten.')
    for path in ('/usr/sbin/sshd', '/usr/sbin/dropbear', '/usr/local/sbin/sshd',
                 '/usr/local/sbin/dropbear', '/usr/bin/dropbear', '/usr/local/bin/sshd',
                 '/sbin/sshd', '/sbin/dropbear', '/etc/init/ssh.conf', '/etc/init/dropbear.conf'):
        if _node(r, path) is not None:
            raise ExtrasError('The card has a competing SSH server; it needs a separate qualified adapter.')
    for directory in ('/etc/init.d', '/etc/rcS.d', *('/etc/rc%d.d' % i for i in range(7))):
        node = _node(r, directory)
        if node is None:
            continue
        if stat.S_IFMT(node['mode']) != stat.S_IFDIR:
            raise ExtrasError('The card has an unrecognized service directory.')
        for name, _, _ in r._iter_dir(node):
            lower = name.casefold()
            if 'ssh' in lower or 'dropbear' in lower:
                path = directory + '/' + name
                if not (managed and path in (files['sshd'], l['hook'])):
                    raise ExtrasError('The card has an unrecognized SSH startup service; it needs a separate qualified adapter.')
    keys = _read(r, files['authorized_keys']).decode('utf-8') if managed else ''
    return {'platform': platform, 'enabled': bool(managed and hook),
            'public_keys': keys, 'partition': partition}

def inspect_image(path, *, allow_pending=False, key_source=None):
    try:
        info = _inspect(path, allow_pending=allow_pending, key_source=key_source)
        info['supported'] = info['platform'] in QUALIFIED_PLATFORMS
        info['reason'] = '' if info['supported'] else 'SSH emulator qualification is not complete for this platform.'
        return info
    except (OSError, ValueError, Ext4Error, struct.error) as e:
        return {'platform': None, 'supported': False, 'reason': str(e),
                'enabled': False, 'public_keys': ''}


def validate_request(original, project, key_source=None):
    ensure_not_incomplete(original)
    config = card_extras.configuration(project)
    if config is not None:
        info = inspect_image(original, key_source=key_source)
        if not info['supported']:
            raise ExtrasError(info['reason'])
    return config


#: PAD-1531: said when a build or a write puts remote access on a card
LETS_THIS_COMPUTER_IN = ('This image lets this computer in over the network (remote access). Keep it for your own '
                         'machine: to give it to someone, turn on Build for sharing on the Network tab and build '
                         'again.')


def strangers_note(count, names):
    """PAD-1531: the sentence for an image that lets in other computers than this one."""
    who = 'another computer' if count == 1 else '%d other computers' % count
    return ('The original image lets %s in over the network (%s), and a card built from it keeps %s. Take %s off '
            'on the Network tab (Remote access), or turn on Build for sharing there.'
            % (who, ', '.join(names), 'that access' if count == 1 else 'their access',
               'it' if count == 1 else 'them'))


def who_gets_in(original, config, key_source=None):
    """PAD-1531: ``(level, sentence)`` saying who a card built from *original* with *config* (the project's
    effective record, card_extras.configuration) lets in over the network, or None when nobody."""
    if config is not None:
        return ('warning', LETS_THIS_COMPUTER_IN) if config.get('enabled') else None
    # a project that never set remote access keeps whatever the original trusts
    state = inspect_image(original, key_source=key_source)
    if not state.get('enabled'):
        return None
    strangers = card_extras.others(state.get('public_keys', ''))
    if strangers:
        return 'warning', strangers_note(len(strangers), [card_extras.key_name(k) for k in strangers])
    return 'warning', LETS_THIS_COMPUTER_IN


def say_who_gets_in(original, config, log, key_source=None):
    try:
        said = who_gets_in(original, config, key_source)
    except (OSError, ValueError):
        said = None
    if said and log:
        log(said[1], said[0])
    return said


def guard_flash(project, image):
    """Flash-only may consume a completed image, never omit pending intent."""
    ensure_not_incomplete(image)
    from . import wifi_card
    wifi_card.guard_flash(project, image)       # PAD-1467: the Wi-Fi start-up choice is pending intent too
    from . import remote_buttons
    remote_buttons.guard_flash(project, image)  # and the remote-buttons choice
    from . import bluetooth_card
    bluetooth_card.guard_flash(project, image)  # PAD-1554: and the Bluetooth headphones plugin
    config = validate_request(image, project)
    if config is None:
        return
    ensure_not_incomplete(image, links_ok=False)
    state = inspect_image(image)
    if (state['enabled'] != config['enabled'] or
            (config['enabled'] and state['public_keys'] != config['public_keys'])):
        raise ExtrasError('Build the complete image first to apply the pending remote access (SSH) change, then flash that build.')
    if config.get('share'):
        # PAD-1531: an image written for sharing has no trusted key and none of a machine's own data left on it
        from . import share_build
        if state['public_keys'].strip() or share_build.machine_data(image) != []:
            raise ExtrasError('Build the image again with Build for sharing on, then flash that build: this one '
                              'still carries remote access or a machine\'s own data.')


def note_build(output, project):
    from ..plugins.stern import engine
    rec = engine.read_build_manifest(output)
    if rec:
        rec['ssh_extras'] = card_extras.digest(project)
        rec['output'] = engine._file_stamp(output)
        engine._write_build_manifest(output, rec)


def _cancel(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('SSH preparation canceled.')


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _command(ex, program, *args):
    cmd = ' '.join(shlex.quote(str(x)) for x in (program, *args))
    try:
        return ex.run(cmd, timeout=180)
    except Exception:
        # CommandError contains the command and output; key content must never
        # be included in a user-facing error. All requested values are files.
        raise ExtrasError(f'SSH preparation failed running {program}; no completed SSH build was produced.') from None


def _verify_tree(reader, config, payload, platform='stern-spike2'):
    l = layout(platform)
    files = l['files']
    hook = _node(reader, l['hook'])
    if not config['enabled']:
        if hook is not None:
            raise ExtrasError('The SSH startup hook could not be disabled.')
        # PAD-1531: off is off - no trusted key and none of PAD's SSH programs stay behind on the card
        if any(_node(reader, dest) is not None for dest in files.values()):
            raise ExtrasError('Remote access could not be taken off the card completely.')
        return
    if (hook is None or (l['linked'] and (stat.S_IFMT(hook['mode']) != stat.S_IFLNK
            or reader.read_symlink(hook) != l['target']))):
        raise ExtrasError('SSH startup hook verification failed.')
    for name, dest in files.items():
        node = _node(reader, dest)
        mode = 0o600 if name == 'authorized_keys' else 0o755
        if (node is None or node['mode'] != stat.S_IFREG | mode
                or node['uid'] or node['gid'] or node['links'] != 1
                or _read(reader, dest, 16 << 20) != payload[name].read_bytes()):
            raise ExtrasError('SSH payload content or permissions verification failed.')
    directory = _node(reader, l['ssh_dir'])
    if directory['mode'] != stat.S_IFDIR | 0o700 or directory['uid'] or directory['gid']:
        raise ExtrasError('SSH public-key directory permissions verification failed.')



def payload_bytes(name, config, l):
    """The exact bytes one card file gets.

    Text goes on the card with LF line ends whatever the host: a Windows
    checkout (core.autocrlf) gives the start script CRLF, and text-mode
    writes there turn every key line's end into CRLF.  The card's /bin/sh
    cannot run "#!/bin/sh\\r", and keys read back with CR never match the
    project's, so Flash refused the image it had just built (PR #38 review).
    """
    if name == 'authorized_keys':
        return config['public_keys'].replace('\r\n', '\n').encode('utf-8')
    if name == 'sshd':
        return (RESOURCES / 'sshd').read_bytes().replace(b'\r\n', b'\n')
    data = (RESOURCES / l['arch'] / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != l['hashes'][name]:
        raise ExtrasError('The bundled SSH payload is missing or has an unexpected hash.')
    return data


def prepare_rootfs(part, work, config, platform='stern-spike2', cancel=None):
    """Modify/check only a scratch plaintext ext filesystem; never a card."""
    part, work = Path(part), Path(work)
    size = part.stat().st_size
    ex = create_executor()
    l = layout(platform)
    files, hook = l['files'], l['hook']
    _cancel(cancel)
    exec_part = ex.to_exec_path(str(part))
    _command(ex, 'e2fsck', '-fn', exec_part)
    payload = {}
    commands = []
    with part.open('rb') as f:
        r = Ext4Reader(f, 0, size)
        # Refuse symlink parents and non-regular/hard-linked destinations,
        # even when a foreign card tries to look like a recognized system.
        for path in l['dirs']:
            node = _node(r, path)
            if node is not None and stat.S_IFMT(node['mode']) != stat.S_IFDIR:
                raise ExtrasError('An SSH destination directory is a symlink or special file.')
            if node is None and config['enabled']:
                commands.append(f'mkdir {path}')
        for path in files.values():
            node = _node(r, path)
            if node is not None and (stat.S_IFMT(node['mode']) != stat.S_IFREG or node['links'] != 1):
                raise ExtrasError('An SSH destination is a symlink or hard-linked file.')
        if _node(r, hook) is not None and (l['linked'] or not config['enabled']):
            commands.append(f'rm {hook}')
        if not config['enabled']:
            # PAD-1531: off takes the trusted keys and PAD's SSH programs off as well, not only the boot hook: a
            # card written "off" and handed on carries no login for anyone (inspect_root has already refused a
            # card whose SSH files are not PAD's)
            for dest_path in files.values():
                if _node(r, dest_path) is not None:
                    commands.append(f'rm {dest_path}')
        if config['enabled']:
            for name, dest_path in files.items():
                staged = work / name
                staged.write_bytes(payload_bytes(name, config, l))
                payload[name] = staged
                if _node(r, dest_path) is not None:
                    commands.append(f'rm {dest_path}')
                src_path = ex.to_exec_path(str(staged))
                if any(c in src_path for c in ('"', '\n', '\r', '\\')):
                    raise ExtrasError('The SSH staging path contains unsupported filesystem-tool characters.')
                commands.append(f'write "{src_path}" {dest_path}')
                mode = '0100600' if name == 'authorized_keys' else '0100755'
                for field, val in (('mode', mode), ('uid', '0'), ('gid', '0')):
                    commands.append(f'set_inode_field {dest_path} {field} {val}')
            for field, val in (('mode', '040700'), ('uid', '0'), ('gid', '0')):
                commands.append(f"set_inode_field {l['ssh_dir']} {field} {val}")
            if l['linked']:
                commands.append(f"symlink {hook} {l['target']}")
    script = work / 'debugfs.commands'
    script.write_text('\n'.join(commands) + '\n')
    if commands:
        _command(ex, 'debugfs', '-w', '-f', ex.to_exec_path(str(script)), exec_part)
    _command(ex, 'e2fsck', '-fn', exec_part)
    with part.open('rb') as f:
        _verify_tree(Ext4Reader(f, 0, size), config, payload, platform)

def rewrite_partition(output, start, size, prepare, cancel=None, what='SSH', stop=None):
    """Copy the *size* bytes at *start* of the image *output* to a scratch file, let ``prepare(part, work)`` change
    and verify that file, then write it back and read it back.  Only a prepared, verified partition is written;
    a failure raises ExtrasError and the caller must treat *output* as incomplete.  *what* names the change in the
    messages; *stop* is the cancel check (default: this module's)."""
    stop = stop or _cancel
    with tempfile.TemporaryDirectory(prefix='pad-ssh-', dir=str(Path(output).parent)) as work:
        work = Path(work)
        part = work / 'rootfs.img'
        with open(output, 'rb') as src, part.open('wb') as dst:
            src.seek(start)
            remaining = size
            while remaining:
                stop(cancel)
                chunk = src.read(min(1 << 20, remaining))
                if not chunk:
                    raise ExtrasError('The system partition is truncated.')
                dst.write(chunk)
                remaining -= len(chunk)
        prepare(part, work)
        stop(cancel)
        expected = _hash_file(part)
        with open(output, 'r+b') as dst, part.open('rb') as src:
            dst.seek(start)
            remaining = size
            while remaining:
                stop(cancel)
                chunk = src.read(min(1 << 20, remaining))
                if not chunk:
                    raise ExtrasError('The staged system partition is truncated.')
                dst.write(chunk)
                remaining -= len(chunk)
            dst.flush(); os.fsync(dst.fileno())
            dst.seek(start)
            got = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = dst.read(min(1 << 20, remaining))
                if not chunk:
                    raise ExtrasError('%s system partition read-back was truncated.' % what)
                got.update(chunk); remaining -= len(chunk)
            if got.hexdigest() != expected:
                raise ExtrasError('%s system partition read-back verification failed.' % what)


def apply_to_build(original, output, config, log=None, cancel=None, key_source=None):
    """Apply desired SSH state to an existing output COPY, or raise before success.

    Only a verified partition is written back. A failed/canceled write is
    reported to the pipeline, which must quarantine its incomplete output.

    PAD-1531: a build for sharing (``config['share']``, card_extras.configuration) is remote access off, and then
    the machine's own partitions emptied as a stock card ships them (core/share_build.py).
    """
    if config is None:
        return ''
    text = _apply_ssh(original, output, config, log, cancel, key_source)
    if config.get('share'):
        from . import share_build
        said = share_build.scrub(original, output, log=log, cancel=cancel, key_source=key_source)
        text = SHARE_TEXT + ((' ' + said) if said else '')
    return text


#: what a build for sharing says it did (the Write summary and log)
SHARE_TEXT = 'Built for sharing: no remote access on it.'
OFF_TEXT = 'Remote access off: no SSH server and no trusted keys on the card.'


def _apply_ssh(original, output, config, log=None, cancel=None, key_source=None):
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise ExtrasError('Invalid SSH enablement.')
    config = dict(config)
    if config['enabled']:
        config['public_keys'] = card_extras.validate_keys(config.get('public_keys', ''))
    _regular(original); _regular(output, allow_pending=True, writable=True)
    if os.path.samefile(original, output):
        raise ExtrasError('SSH preparation must not write the original image.')
    source = inspect_image(original, key_source=key_source)
    if source['platform'] == 'stern-spike3':
        from . import ssh_spike3
        return ssh_spike3.apply_to_build(original, output, config, log, cancel, key_source)
    dest = inspect_image(output, allow_pending=True)
    if not source['supported'] or not dest['supported'] or source['partition'] != dest['partition']:
        raise ExtrasError(source.get('reason') or dest.get('reason') or 'The system partition changed unexpectedly.')
    _cancel(cancel)
    _, _, start, size = dest['partition']
    if shutil.disk_usage(Path(output).parent).free < size + (32 << 20):
        raise ExtrasError('Not enough free space to prepare the SSH system partition.')
    rewrite_partition(output, start, size,
                      lambda part, work: prepare_rootfs(part, work, config, cancel=cancel), cancel)
    text = 'SSH server enabled (key-only, port 22).' if config['enabled'] else OFF_TEXT
    if log:
        log(text, 'info')
    return text
