"""Remote access on a card with one button (PAD-1427).

David: "we need to make the setup of remote access way more friendly here especially for users who don't know what
they're doing. Ideally, we have them modify an attached SD card with the push of a button and it injects the
remote access tooling for them. then, they don't have to manually enter secrets or keys, it's just stored in PAD."

:func:`set_up` puts remote access (the key-only dropbear of PR #38, ``ssh_card``) straight onto the machine's SD card
in the computer's reader, or onto a card image file, in place: no project, no build, no keys to paste. The card
lets in this computer's own key (``pad_ssh_key``, kept beside settings.json, so it survives app updates) and the
project's own saved keys (the user's own SSH programs).  PAD-1531: any other key the card trusted, someone else's
computer (a card written from an image another person built with remote access on), is taken off by default and
named, so the card ends up letting in only this computer; ``keep_others`` keeps them. Stern Spike 2 and Spike 3 (the user's own board key, kept app-wide, opens a
Spike 3 card).

How: the system partition's plain filesystem is copied to a scratch file, ``ssh_card.prepare_rootfs`` adds the
files there and checks them, the 1 MiB blocks that differ are written back to the card (Spike 3: through its LUKS
volume, re-encrypted), and the whole partition is read back from the card and compared. Nothing else on the card
changes: the game, its settings, audits and high scores stay as they were.

A plugged-in card on Windows needs administrator access to write: :func:`set_up_with_privileges` runs the job in
the elevated flash helper (``elevated_flash``, mode ``remote_access``) when the app isn't elevated already."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from . import card_extras, pad_ssh_key, ssh_card, ssh_spike3
from .card_extras import ExtrasError
from .rawdevice import is_device_path

BLOCK = 1 << 20


class _Plain:
    """The system partition's plain filesystem as a byte range of an open stream: Spike 2's p2 as it is, Spike 3's
    through its unlocked LUKS volume."""

    def __init__(self, stream, start, size):
        self.f, self.start, self.size = stream, start, size

    def read(self, off, n):
        self.f.seek(self.start + off)
        return self.f.read(n)

    def write(self, off, data):
        self.f.seek(self.start + off)
        self.f.write(data)


class _Opened:
    """``with _Opened(path, writable, key_source) as (info, plain)``: the card's remote access state and its plain
    system filesystem."""

    def __init__(self, path, writable=False, key_source=None):
        self.path, self.writable, self.key_source = path, writable, key_source
        self._f = self._cm = None

    def __enter__(self):
        f, size = ssh_spike3.open_stream(self.path, False)
        try:
            p2, encrypted = ssh_card.system_partition(f, size)
            info = None if encrypted else ssh_card.inspect_spike2(f, p2)
        finally:
            f.close()
        if not encrypted:
            self._f, _size = ssh_spike3.open_stream(self.path, self.writable)
            return info, _Plain(self._f, p2[2], p2[3])
        self._cm = ssh_spike3.open_rootfs(self.path, writable=self.writable, key_source=self.key_source)
        vol = self._cm.__enter__()
        try:
            from ..plugins.stern.ext4 import Ext4Reader
            r = Ext4Reader(vol, 0, vol.size)
            passwd = ssh_card._read(r, '/etc/passwd')
            if (b'root:*:0:0:root:/root:/bin/sh' not in passwd
                    or b'Stern Pinball Spike 3' not in ssh_card._read(r, '/etc/issue')
                    or not ssh_card._node(r, '/etc/init.d/S95game')):
                raise ExtrasError('This Spike 3 rootfs/boot layout has not been qualified for SSH.')
            p = vol.part
            info = ssh_card.inspect_root(r, ssh_spike3.PLATFORM,
                                         (p['index'], p['ptype'], p['start_lba'] * 512, p['sectors'] * 512))
        except BaseException:
            self._cm.__exit__(None, None, None)
            raise
        self._f = vol._f
        return info, _Plain(vol, 0, vol.size)

    def sync(self):
        ssh_spike3.sync_stream(self._f)

    def __exit__(self, *exc):
        if self._cm is not None:
            return self._cm.__exit__(*exc)
        if self._f is not None:
            self._f.close()
        return False


def _what(path):
    return 'the card' if is_device_path(str(path)) else os.path.basename(path)


def _readable_error(e):
    text = str(e)
    if 'qualified' in text:
        return ("This isn't a Stern Spike 2 or Spike 3 game card PAD can put remote access on. Check that it is "
                "the card from the machine.")
    return text


def look(path, key_source=None, own=''):
    """``{'ok', 'platform', 'enabled', 'lets_pad_in', 'others', 'reason'}`` for the card or image at *path*;
    ``others`` names the keys on it that are neither this computer's nor in *own* (PAD-1531)."""
    try:
        with _Opened(path, key_source=key_source) as (info, _plain):
            line = pad_ssh_key.public_line().strip()
            keys = info.get('public_keys') or ''
            return dict(ok=True, platform=info['platform'], enabled=bool(info['enabled']),
                        lets_pad_in=bool(line) and line.split()[1] in keys,
                        others=[card_extras.key_name(k) for k in card_extras.others(keys, own)], reason='')
    except (OSError, ValueError) as e:
        return dict(ok=False, platform=None, enabled=False, lets_pad_in=False, others=[],
                    reason=_readable_error(e))


def _kept_keys(card_keys, pad_line, own='', keep_others=False):
    """PAD-1531: the keys the card goes on trusting: this computer's, the card's keys that are also in *own* (the
    project's saved keys), and the card's other keys only with *keep_others*."""
    strangers = {card_extras.key_id(k) for k in card_extras.others(card_keys, own)}
    lines = [k for k in (card_keys or '').splitlines()
             if keep_others or card_extras.key_id(k.strip()) not in strangers]
    return _merged_keys('\n'.join(lines), pad_line)


def _merged_keys(card_keys, pad_line):
    """The card's own trusted keys (when its remote access is PAD's) with this computer's added, each once."""
    seen, out = set(), []
    for line in (card_keys or '').splitlines() + [pad_line.strip()]:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        body = ' '.join(line.split()[:2])
        if body in seen:
            continue
        seen.add(body)
        out.append(line)
    return card_extras.validate_keys('\n'.join(out) + '\n')


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise ExtrasError('Canceled. The card was not changed.')


def set_up(path, *, pad_line=None, log=None, progress=None, cancel=None, key_source=None, own='',
           keep_others=False):
    """Put remote access on the card or card image at *path*, letting in this computer's key (*pad_line*, the
    public key line; this computer's own when None) and the card's keys that are in *own* (the project's saved
    keys).  Any other key on the card is taken off unless *keep_others* (PAD-1531).  Returns ``'done'``, or
    ``'already'`` when the card had it and nothing was to come off."""
    say = log or (lambda *_a: None)
    tick = progress or (lambda *_a: None)
    pad_line = (pad_line or pad_ssh_key.public_line()).strip()
    if not pad_line:
        raise ExtrasError("PAD couldn't make its own key on this computer, so it can't set up remote access.")
    pad_body = pad_line.split()[1]
    if not is_device_path(str(path)):
        ssh_card._regular(path, writable=True)
    what = _what(path)
    work_root = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix='pad-remote-', dir=work_root) as tmp:
        work = Path(tmp)
        part = work / 'rootfs.img'
        # 1. the card's state, and its plain system filesystem copied out
        with _Opened(path, key_source=key_source) as (info, plain):
            card_keys = info.get('public_keys') or ''
            strangers = [] if keep_others else card_extras.others(card_keys, own)
            if info['enabled'] and pad_body in card_keys and not strangers:
                say('Remote access is already on %s, and it lets this computer in.' % what, 'ok')
                return 'already'
            if strangers:
                # PAD-1531: named in the log before anything changes, so the user sees whose access goes
                say('%s also let in %s: %s. Taking %s off, so only this computer can get in.'
                    % (what[:1].upper() + what[1:], _count(len(strangers)),
                       ', '.join(card_extras.key_name(k) for k in strangers),
                       'it' if len(strangers) == 1 else 'them'), 'warning')
            platform, size = info['platform'], plain.size
            config = {'enabled': True,
                      'public_keys': _kept_keys(card_keys if info['enabled'] else '', pad_line, own,
                                                keep_others)}
            if shutil.disk_usage(work_root).free < size + (64 << 20):
                raise ExtrasError('Not enough free space on this computer (%d MB needed) to set up the card.'
                                  % ((size >> 20) + 64))
            say('Reading the system files on %s...' % what, 'info')
            with part.open('wb') as out:
                done = 0
                while done < size:
                    _cancelled(cancel)
                    chunk = plain.read(done, min(BLOCK, size - done))
                    if not chunk:
                        raise ExtrasError("The card's system partition is cut short.")
                    out.write(chunk)
                    done += len(chunk)
                    tick(done, size * 3, 'Reading the card')
        # 2. remote access added to the copy, and checked there
        say('Adding remote access...', 'info')
        ssh_card.prepare_rootfs(part, work, config, platform=platform, cancel=cancel)
        expected = ssh_card._hash_file(part)
        _cancelled(cancel)
        # 3. the blocks that differ written to the card, then all of it read back
        changed = 0
        with _device_guard(path, say):
            with _Opened(path, writable=True, key_source=key_source) as (_info, dest), part.open('rb') as src:
                say('Writing the changes to %s...' % what, 'info')
                done = 0
                while done < size:                  # once begun it finishes: never half a card
                    new = src.read(min(BLOCK, size - done))
                    if dest.read(done, len(new)) != new:
                        dest.write(done, new)
                        changed += 1
                    done += len(new)
                    tick(size + done, size * 3, 'Writing the card')
                _opened_sync(dest)
            say('Checking what %s now holds...' % what, 'info')
            got = hashlib.sha256()
            with _Opened(path, key_source=key_source) as (after, check):
                done = 0
                while done < size:
                    chunk = check.read(done, min(BLOCK, size - done))
                    if not chunk:
                        raise ExtrasError('Reading the card back was cut short.')
                    got.update(chunk)
                    done += len(chunk)
                    tick(2 * size + done, size * 3, 'Checking the card')
    left = after.get('public_keys') or ''
    left_ids = {card_extras.key_id(x.strip()) for x in left.splitlines()}
    if (got.hexdigest() != expected or not after['enabled'] or pad_body not in left
            or any(card_extras.key_id(k) in left_ids for k in strangers)):
        raise ExtrasError("The card didn't read back as written. Try again, or try another card reader.")
    say('Remote access is on %s now (%d MB of its system files changed).' % (what, changed), 'ok')
    return 'done'


def _count(n):
    return 'another computer' if n == 1 else '%d other computers' % n


def _device_guard(path, log):
    """What a card flash holds while it writes (``rawdevice``): the disk offline and its lettered volumes locked,
    so Windows neither caches nor touches the card meanwhile.  Nothing for an image file."""
    import contextlib
    stack = contextlib.ExitStack()
    if is_device_path(str(path)):
        from . import rawdevice
        stack.enter_context(rawdevice._disk_offline_for_write(path, log))
        stack.enter_context(rawdevice._locked_volumes(path, log))
    return stack


def _opened_sync(plain):
    f = plain.f
    if hasattr(f, '_f'):                    # a Spike 3 LUKS volume: its stream underneath
        f = f._f
    ssh_spike3.sync_stream(f)


def set_up_with_privileges(path, *, log=None, progress=None, cancel=None, own='', keep_others=False):
    """:func:`set_up`, elevated for a plugged-in card when the app isn't (Windows UAC, macOS, pkexec)."""
    from . import elevated_flash as ef
    from .admin import is_admin
    pad_line = pad_ssh_key.public_line()
    if is_admin() or not is_device_path(str(path)):
        return set_up(path, pad_line=pad_line, log=log, progress=progress, cancel=cancel, own=own,
                      keep_others=keep_others)
    if log is not None:
        log('Changing the card needs administrator access: approve the prompt to continue.', 'info')
    ipc = ef._ipc_dir('pad_remote_')
    try:
        import json
        with open(os.path.join(ipc, ef._JOB), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'remote_access', 'device': path, 'pad_line': pad_line, 'own': own or '',
                       'keep_others': bool(keep_others)}, f)
        run = ef._spawn_elevated_helper(ipc)
        if run is None:
            raise ExtrasError('Could not ask for administrator access on this computer. Start PAD as '
                              'administrator and try again.')
        try:
            ef._relay_until_done(run, ipc, log=log, progress=progress, cancel=cancel, on_verify_start=None)
        except ef.FlashCancelled:
            raise ExtrasError('Canceled. The card was not changed.') from None
        except ef.FlashError as e:
            text = str(e)
            if 'declined' in text:
                text = 'Administrator access was declined, so the card was not changed.'
            raise ExtrasError(text) from None
        return (ef._read_json(os.path.join(ipc, ef._RESULT)) or {}).get('text') or 'done'
    finally:
        ef._rmtree_quiet(ipc)


def run_in_helper(job, log, progress, cancel):
    """The elevated helper's side of :func:`set_up_with_privileges`: ``{'ok', 'text'}`` (raises on failure)."""
    return set_up(job['device'], pad_line=job.get('pad_line') or None, log=log, progress=progress, cancel=cancel,
                  own=job.get('own') or '', keep_others=bool(job.get('keep_others')))
