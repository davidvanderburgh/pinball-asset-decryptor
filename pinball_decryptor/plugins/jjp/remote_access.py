"""Remote access in a JJP build, and the build's Send record (PAD-1587).

The JJP Write (``StandaloneModPipeline``) edits the install's restored root (a raw ext4 image) with debugfs.  Two
steps join it here:

- :func:`apply`, after the changed assets are written: the project's Remote access choice (core/card_extras.py,
  the Network tab), put on or taken off the root (core/ssh_jjp.py), then read back and checked;
- :func:`write_send_record`, once the ISO is built and the root still there: every file the build wrote, read
  back out of the finished root into ``<iso>.pad-send/`` with its mode and owner, and the few unchanged files
  that identify the install (core/remote_send_jjp.py), so a Send needs nothing of the ISO.
"""
import hashlib
import os
import re
import shutil
import tempfile

from ...core import card_extras, ssh_jjp, remote_send_jjp
from .executor import CommandError


class RemoteAccessError(Exception):
    pass


def config_for(pipeline):
    """The project's Remote access choice, or None when the project never set one (the install keeps what it
    has)."""
    try:
        return card_extras.configuration(pipeline.assets_folder)
    except Exception as e:                              # noqa: BLE001 - a broken record is the user's to fix
        raise RemoteAccessError('The project\'s remote access setting could not be read: %s' % e) from None


def _native(pipeline):
    return bool(getattr(pipeline, '_native_debugfs_path', None))


def _stage(pipeline, name, data):
    """*data* as a file debugfs can read: ``(path where debugfs runs, host path to remove)``."""
    if _native(pipeline):
        fd, host = tempfile.mkstemp(prefix='pad-ra-', suffix='-' + name)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        return host, host
    fd, host = tempfile.mkstemp(prefix='pad-ra-', suffix='-' + name, dir=pipeline.executor.host_tmp_dir())
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    return pipeline.executor.to_exec_path(host), host


def _out_path(pipeline, host):
    return host if _native(pipeline) else pipeline.executor.to_exec_path(host)


def _dbg(pipeline, cmd, writable=False, timeout=120):
    return pipeline._debugfs_run(cmd, writable=writable, timeout=timeout)


def _stat(pipeline, path):
    try:
        return _dbg(pipeline, 'stat "%s"' % path, timeout=15)
    except CommandError:
        return ''


def _exists(out):
    return bool(out) and 'Inode:' in out and 'File not found' not in out


def _dump(pipeline, path, host):
    _dbg(pipeline, 'dump -p "%s" "%s"' % (path, _out_path(pipeline, host)), timeout=900)
    if not os.path.isfile(host):
        raise RemoteAccessError('%s could not be read back out of the built root.' % path)
    with open(host, 'rb') as f:
        return f.read()


def apply(pipeline, config):
    """Put the project's remote access on (or take it off) the root being built, and check it is there."""
    if config is None:
        return ''
    if type(config.get('enabled')) is not bool:
        raise RemoteAccessError('Invalid remote access setting.')
    config = dict(config)
    if config['enabled']:
        config['public_keys'] = card_extras.validate_keys(config.get('public_keys', ''))
        for unit in ssh_jjp.STOCK_UNITS[:2]:
            if _exists(_stat(pipeline, unit)):
                raise RemoteAccessError('This install starts its own SSH server already (%s), which would hold '
                                        'the port PAD\'s remote access needs.' % unit)
    staged, cleanup = {}, []
    try:
        if config['enabled']:
            for name in ssh_jjp.FILES:
                where, host = _stage(pipeline, name, ssh_jjp.payload_bytes(name, config))
                staged[name] = where
                cleanup.append(host)
        for line in ssh_jjp.debugfs_commands(config, staged):
            try:
                _dbg(pipeline, line, writable=True, timeout=120)
            except CommandError as e:
                # rm of what is not there and mkdir of what is are expected to complain; the check below decides
                if not line.startswith(('rm ', 'mkdir ')):
                    raise RemoteAccessError('Remote access could not be written into the root (%s): %s'
                                            % (line.split()[0], e)) from None
        _verify(pipeline, config)
    finally:
        for host in cleanup:
            try:
                os.unlink(host)
            except OSError:
                pass
    if config['enabled']:
        for path in ssh_jjp.changed_paths(config):
            pipeline._note_sent(path)
        text = 'Remote access on (key-only, port 22): this computer can reach the machine and Send to it.'
    else:
        text = 'Remote access off: no SSH server and no trusted keys on the install.'
    pipeline.log(text, 'success')
    return text


def _mode_of(stat_out):
    m = re.search(r'Mode:\s*0?([0-7]{3,4})', stat_out or '')
    t = re.search(r'Type:\s*(\w+)', stat_out or '')
    owner = re.search(r'User:\s*(\d+)\s+Group:\s*(\d+)', stat_out or '')
    return (t.group(1) if t else '', int(m.group(1), 8) if m else -1,
            (int(owner.group(1)), int(owner.group(2))) if owner else None)


def _verify(pipeline, config):
    hook = _stat(pipeline, ssh_jjp.HOOK)
    if not config['enabled']:
        left = [p for p in [ssh_jjp.HOOK] + list(ssh_jjp.FILES.values()) if _exists(_stat(pipeline, p))]
        if left:
            raise RemoteAccessError('Remote access could not be taken off the install completely (%s).' % left[0])
        return
    if 'symlink' not in hook or ssh_jjp.UNIT not in hook:
        raise RemoteAccessError('The remote access start-up hook did not land in the root.')
    want = ssh_jjp.expected(config)
    tmpdir = tempfile.mkdtemp(prefix='pad-ra-check-', dir=None if _native(pipeline)
                              else pipeline.executor.host_tmp_dir())
    try:
        for i, (path, (mode, digest)) in enumerate(sorted(want.items())):
            kind, perms, owner = _mode_of(_stat(pipeline, path))
            data = _dump(pipeline, path, os.path.join(tmpdir, 'f%d' % i))
            if (kind != 'regular' or perms != (mode & 0o7777) or owner != (0, 0)
                    or hashlib.sha256(data).hexdigest() != digest):
                raise RemoteAccessError('Remote access did not read back from the root as written (%s).' % path)
        kind, perms, owner = _mode_of(_stat(pipeline, ssh_jjp.SSH_DIR))
        if kind != 'directory' or perms != 0o700 or owner != (0, 0):
            raise RemoteAccessError('The trusted keys folder (%s) did not get its private permissions.'
                                    % ssh_jjp.SSH_DIR)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _game_name(pipeline):
    try:
        out = _dbg(pipeline, 'cat /jjpe/gen1/setenv.sh', timeout=30)
    except CommandError:
        return ''
    m = re.search(r'GAMENAME=["\']?([A-Za-z0-9_.-]+)', out)
    return m.group(1) if m else ''


def write_send_record(pipeline, iso, config):
    """The Send record beside the built *iso* (host path), read out of the finished root while it is still there."""
    d = remote_send_jjp.set_dir(iso)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    files = []
    game = _game_name(pipeline)
    paths = sorted(getattr(pipeline, '_send_paths', ()))
    for i, path in enumerate(paths):
        out = _stat(pipeline, path)
        if not _exists(out):
            continue                                    # taken off (remote access off): nothing to send
        kind, perms, owner = _mode_of(out)
        if kind == 'symlink':
            m = re.search(r'Fast link dest:\s*"([^"]*)"', out)
            if not m:
                raise RemoteAccessError('%s is a link the Send record could not read.' % path)
            files.append(dict(path=path, link=m.group(1)))
            continue
        if kind != 'regular' or owner is None:
            raise RemoteAccessError('%s in the built root is not a plain file; it cannot be sent.' % path)
        name = 'f%05d' % i
        data = _dump(pipeline, path, os.path.join(d, name))
        files.append(remote_send_jjp.manifest_entry(path, name, data, perms, owner[0], owner[1]))
    ident = {}
    for path in ('/jjpe/gen1/%s/game' % game, '/jjpe/gen1/fl.dat', '/jjpe/gen1/%s/fl.dat' % game):
        if not game or path in paths or not _exists(_stat(pipeline, path)):
            continue
        host = os.path.join(d, 'identity.tmp')
        ident[path] = hashlib.sha1(_dump(pipeline, path, host)).hexdigest()
        os.unlink(host)
    remote = {}
    if config is not None:
        remote = dict(enabled=bool(config.get('enabled')),
                      public_keys=config.get('public_keys', '') if config.get('enabled') else '')
    else:
        keys = _stat(pipeline, ssh_jjp.FILES['authorized_keys'])
        if _exists(keys) and _exists(_stat(pipeline, ssh_jjp.HOOK)):
            host = os.path.join(d, 'keys.tmp')
            remote = dict(enabled=True, public_keys=_dump(pipeline, ssh_jjp.FILES['authorized_keys'], host)
                          .decode('utf-8', 'replace'))
            os.unlink(host)
    manifest = dict(game=game, source=os.path.basename(pipeline.image_path), files=files, identity=ident,
                    remote=remote)
    remote_send_jjp.write_set(iso, manifest)
    pipeline.log('Send record written beside the build: %d changed file%s a Send to the machine puts on it.'
                 % (len(files), '' if len(files) == 1 else 's'), 'info')
    return manifest


def move_record(produced, target):
    """The ISO moved from *produced* to *target*: its Send record goes with it."""
    src, dst = remote_send_jjp.set_dir(produced), remote_send_jjp.set_dir(target)
    if not os.path.isdir(src):
        return
    shutil.rmtree(dst, ignore_errors=True)
    shutil.move(src, dst)
    remote_send_jjp.restamp(target)
