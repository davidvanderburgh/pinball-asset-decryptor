"""Remote access on a Jersey Jack Pinball install (PAD-1587).

A JJP machine is an x86-64 PC running Ubuntu with systemd; its install ISO carries the root filesystem (``sda3``:
the system plus ``/jjpe``) as a gzip-split partclone image, which the JJP Write already restores to a raw ext4
image and edits with debugfs.  Remote access goes into that same root as it does on a Stern card: PAD's own
static, key-only Dropbear (no password logins are compiled in) and SFTP server, a start script, and the one hook
that starts it - here a systemd unit enabled in ``multi-user.target``.

The install's own OpenSSH server (``/usr/sbin/sshd``, not enabled by JJP) is left alone: its host keys are baked
into the ISO, so every machine installed from it would answer with the same identity.  PAD's server makes its
host keys on the machine itself, on first start, in ``/var/lib/pad/dropbear`` on the root partition: a reinstall
replaces the root and so gives the machine a new identity, and a settings restore (``/jjpe/perm``) never carries
one machine's identity to another.

What a build carries is said by its Send record beside the ISO (core/remote_send_jjp.py), so the Network and
Write tabs can tell without unpacking gigabytes of partclone.
"""
import hashlib
import shlex
import stat

from .card_extras import ExtrasError
from .ssh_card import RESOURCES

PLATFORM = 'jjp'
ARCH = 'x86_64'
#: resources/ssh/build-x86_64.sh (dropbear 2025.88, pkg/sftp v1.13.2; the same options as Spike 2 and Spike 3)
X86_64_HASHES = {
    'dropbear': '7d3c6a2585a41cb20838abb8e89c70074b06914fcb70b048920265b5f2e7674a',
    'dropbearkey': '6c33e0751c5f1bd2c6524949e9a27b9e9d89ccfaa0774544c6b22f832a339165',
    'sftp-server': 'd836a10674ce10e81f782a9d4862e38b85054b8467ff6d5ddbab626030db25dc',
}
KEYDIR = '/var/lib/pad/dropbear'
UNIT = '/etc/systemd/system/pad-sshd.service'
HOOK = '/etc/systemd/system/multi-user.target.wants/pad-sshd.service'
FILES = {'dropbear': '/usr/local/bin/dropbear', 'dropbearkey': '/usr/local/bin/dropbearkey',
         'sftp-server': '/usr/local/libexec/pad-sftp-server', 'sshd': '/usr/local/sbin/pad-sshd',
         'unit': UNIT, 'authorized_keys': '/root/.ssh/authorized_keys'}
DIRS = ('/usr', '/usr/local', '/usr/local/bin', '/usr/local/libexec', '/usr/local/sbin', '/etc', '/etc/systemd',
        '/etc/systemd/system', '/etc/systemd/system/multi-user.target.wants', '/root', '/root/.ssh')
SSH_DIR = '/root/.ssh'
#: the install's own server, which would hold port 22 if JJP ever enabled it
STOCK_UNITS = ('/etc/systemd/system/multi-user.target.wants/ssh.service',
               '/etc/systemd/system/multi-user.target.wants/sshd.service',
               '/etc/systemd/system/sshd.service')

UNIT_TEXT = """[Unit]
Description=PAD key-only remote access
After=network.target local-fs.target

[Service]
Type=forking
PIDFile=/run/pad-sshd.pid
ExecStart=/usr/local/sbin/pad-sshd start
ExecStop=/usr/local/sbin/pad-sshd stop
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def layout():
    return dict(files=dict(FILES), dirs=DIRS, hook=HOOK, target=UNIT, linked=True, ssh_dir=SSH_DIR, arch=ARCH,
                hashes=X86_64_HASHES)


def start_script():
    """resources/ssh/sshd (the start script both Stern cards run) with the host keys kept on the JJP root."""
    text = (RESOURCES / 'sshd').read_bytes().replace(b'\r\n', b'\n')
    if b'KEYDIR=/data/dropbear' not in text or b'PIDFILE=/var/run/pad-sshd.pid' not in text:
        raise ExtrasError('The bundled remote access start script is not the one PAD expects.')
    text = text.replace(b'KEYDIR=/data/dropbear', b'KEYDIR=' + KEYDIR.encode())
    text = text.replace(b'mkdir -p "$KEYDIR"', b'mkdir -p "$KEYDIR" && chmod 755 /var/lib/pad')
    return text.replace(b'# PAD key-only SSH; host identity belongs to this cabinet\'s data partition.',
                        b'# PAD key-only SSH (JJP); host identity belongs to this machine\'s own root.')


def payload_bytes(name, config):
    """The exact bytes one file of the root gets (text with LF line ends, whatever the host)."""
    if name == 'authorized_keys':
        return config['public_keys'].replace('\r\n', '\n').encode('utf-8')
    if name == 'sshd':
        return start_script()
    if name == 'unit':
        return UNIT_TEXT.encode('ascii')
    data = (RESOURCES / ARCH / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != X86_64_HASHES[name]:
        raise ExtrasError('The bundled remote access payload is missing or has an unexpected hash.')
    return data


def mode_of(name):
    return 0o600 if name == 'authorized_keys' else 0o644 if name == 'unit' else 0o755


def debugfs_commands(config, staged):
    """The ``debugfs -w -f`` script that puts remote access on (or takes it off) a JJP root.

    *staged*: ``{name: path of the file's bytes where debugfs runs}`` (only needed to put it on).  Off is off: the
    hook, the unit, the programs and the trusted keys all go (the ``/root/.ssh`` folder stays; it is the root
    user's own)."""
    q = shlex.quote
    lines = ['rm %s' % HOOK]
    for dest in FILES.values():
        lines.append('rm %s' % dest)
    if not config.get('enabled'):
        return lines
    for d in DIRS:
        lines.append('mkdir %s' % d)
    for name, dest in FILES.items():
        lines.append('write %s %s' % (q(staged[name]), dest))
        lines.append('set_inode_field %s mode 0%o' % (dest, stat.S_IFREG | mode_of(name)))
        lines.append('set_inode_field %s uid 0' % dest)
        lines.append('set_inode_field %s gid 0' % dest)
    lines.append('set_inode_field %s mode 0%o' % (SSH_DIR, stat.S_IFDIR | 0o700))
    lines.append('set_inode_field %s uid 0' % SSH_DIR)
    lines.append('set_inode_field %s gid 0' % SSH_DIR)
    lines.append('symlink %s %s' % (HOOK, UNIT))
    return lines


def expected(config):
    """``{path: (mode bits, sha256)}`` the root must carry after :func:`debugfs_commands` (on), for the check."""
    return {dest: (stat.S_IFREG | mode_of(name), hashlib.sha256(payload_bytes(name, config)).hexdigest())
            for name, dest in FILES.items()}


def changed_paths(config):
    """What a build with *config* changes on the root, for its Send record: the files (and the hook)."""
    return sorted(FILES.values()) + [HOOK]


def inspect_iso(path):
    """What remote access the JJP install at *path* carries: a PAD build says so in its Send record; a JJP
    original carries none (JJP never enables an SSH server)."""
    from . import remote_send_jjp
    info = dict(platform=PLATFORM, supported=True, reason='', enabled=False, public_keys='', managed=False)
    try:
        rec = remote_send_jjp.read_set(path, check_files=False)
    except remote_send_jjp.SendError:
        rec = None
    if rec:
        remote = rec.get('remote') or {}
        info.update(enabled=bool(remote.get('enabled')), public_keys=remote.get('public_keys', ''),
                    managed=bool(remote))
    return info


def is_iso(path):
    """True for an ISO 9660 image (the JJP install's container)."""
    try:
        with open(path, 'rb') as f:
            f.seek(0x8001)
            return f.read(5) == b'CD001'
    except OSError:
        return False
