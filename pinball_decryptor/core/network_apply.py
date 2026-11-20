"""Put the Wi-Fi and remote-buttons options straight where they go, without a build (PAD-1467).

David: 'is there a way on the wifi and score feed panels to directly write to the SD card that is attached? (or to
one on remote access?)' ... 'Add "Put on the attached card" and "Put on my machine now" to the Wi-Fi and Remote
buttons panels. Leave Score feed on the build path, with a line saying so.'

Both options are a few files on the card's system partition, so they can go on directly:

- :func:`to_card`: onto a card in this computer's reader, or a card image file, the way the Network tab puts remote
  access on one (``core/remote_setup.py``): the system partition is copied off, changed with the same checked
  steps a build uses (``wifi_card.prepare_rootfs``, ``remote_buttons.prepare_rootfs``), the blocks that differ
  written back, and all of it read back.
- :func:`to_machine`: onto a machine over remote access: each file written beside its place, checked by its sha1,
  moved into place, and the machine restarted (it reads all of these only when it starts).

What does NOT go this way: the 5 GHz option's menu wording (the six lines without "2.4GHz" are an edit inside the
game program, which a build makes), and the score feed (part of PAD's mode runtime).  A build or a Send puts those
on; :data:`WAYS` is what the Network tab shows on each panel.
"""
import hashlib
import os
import posixpath

from . import remote_buttons, wifi_card
from .card_extras import ExtrasError

#: how each panel's settings reach a card: (key, label, what it means)
WAY_LABELS = (
    ('build', 'Write tab: build and write the card', 'Saved with the project; every card you build from it carries it.'),
    ('send', 'Send to machine', 'The same build, sent over your network instead of written to the card.'),
    ('card', 'Straight onto an attached card', 'No build: the card in this computer\'s reader is changed now.'),
    ('machine', 'Straight onto the machine', 'No build: over remote access, now; the machine restarts.'),
)
WAYS = {
    'remote_access': ('build', 'send', 'card'),
    'wifi': ('build', 'send', 'card', 'machine'),
    'buttons': ('build', 'send', 'card', 'machine'),
    'score_feed': ('build', 'send'),
}
WAY_NOTES = {
    'remote_access': 'Remote access has to reach the card once by hand (the first two ways, or the button below): '
                     'it is what lets this computer reach the machine at all.',
    'wifi': 'Straight onto a card or the machine puts the Wi-Fi files on; the menu wording without "2.4GHz" is '
            'inside the game program and comes with the next build or Send.',
    'buttons': '',
    'score_feed': 'The score feed is part of the code PAD builds into the game, so it needs a build: it cannot be '
                  'put straight onto a card or a machine.',
}


def ways(panel):
    """``[{'key', 'label', 'hint', 'on'}, ...]`` for the Network tab's panel *panel*."""
    have = WAYS.get(panel, ())
    return [dict(key=key, label=label, hint=hint, on=key in have) for key, label, hint in WAY_LABELS]


def _said(wifi, buttons):
    parts = []
    if wifi is not None:
        parts.append(('the reliable Wi-Fi start-up' + (' and the newer adapter driver (5 GHz)' if wifi.get('band5') else ''))
                     if wifi.get('enabled') else 'Wi-Fi back as shipped')
    if buttons is not None:
        parts.append('remote buttons' if buttons.get('enabled') else 'remote buttons off')
    return ' and '.join(parts)


# ------------------------------------------------------------------ a card in the reader, or a card image file
def to_card(path, *, wifi=None, buttons=None, stern_from=None, log=None, progress=None, cancel=None):
    """Put *wifi* (``{'enabled', 'band5'}``) and/or *buttons* (``{'enabled'}``) on the card or card image at
    *path*; ``'done'`` or ``'already'``.  *stern_from* is a card image that still has Stern's own adapter driver,
    needed only to take the 5 GHz option off a card that has ours."""
    import shutil
    import tempfile
    from pathlib import Path
    from . import remote_setup, ssh_card
    from .rawdevice import is_device_path
    from ..plugins.stern.ext4 import Ext4Reader
    if wifi is None and buttons is None:
        raise ExtrasError('There is nothing to put on the card.')
    say = log or (lambda *_a: None)
    tick = progress or (lambda *_a: None)
    if not is_device_path(str(path)):
        ssh_card._regular(path, writable=True)
    what = remote_setup._what(path)
    with tempfile.TemporaryDirectory(prefix='pad-network-') as tmp:
        work = Path(tmp)
        part = work / 'rootfs.img'
        with remote_setup._Opened(path) as (info, plain):
            if info.get('platform') != 'stern-spike2':
                raise ExtrasError('These options are for Stern Spike 2 cards only.')
            size = plain.size
            if shutil.disk_usage(tmp).free < size + (64 << 20):
                raise ExtrasError('Not enough free space on this computer (%d MB needed) to change the card.'
                                  % ((size >> 20) + 64))
            say('Reading the system files on %s...' % what, 'info')
            with part.open('wb') as out:
                done = 0
                while done < size:
                    remote_setup._cancelled(cancel)
                    chunk = plain.read(done, min(remote_setup.BLOCK, size - done))
                    if not chunk:
                        raise ExtrasError("The card's system partition is cut short.")
                    out.write(chunk)
                    done += len(chunk)
                    tick(done, size * 3, 'Reading the card')
        before = ssh_card._hash_file(part)
        # what the card has already is left exactly as it is (found on a real card image: putting the same
        # options on twice rewrote 2 MB of identical files and said "done")
        with part.open('rb') as f:
            r = Ext4Reader(f, 0, size)
            if wifi is not None:
                ws = wifi_card.inspect_root(r)
                want_on, want_band = bool(wifi.get('enabled')), bool(wifi.get('enabled') and wifi.get('band5'))
                if ws['enabled'] == want_on and ws['band5'] == want_band and (want_band or ws['stern_module']):
                    wifi = None
            if buttons is not None:
                bs = remote_buttons.inspect_root(r)
                want = bool(buttons.get('enabled'))
                if bs['enabled'] == want and (want or not (bs['hooked'] or bs['file'])):
                    buttons = None
        if wifi is None and buttons is None:
            say('%s already has what is ticked; nothing was changed.' % what, 'ok')
            return 'already'
        say('Putting on %s...' % _said(wifi, buttons), 'info')
        if wifi is not None:
            on, band = bool(wifi.get('enabled')), bool(wifi.get('enabled') and wifi.get('band5'))
            with part.open('rb') as f:
                state = wifi_card.inspect_root(Ext4Reader(f, 0, size))
            stern = None
            if not band and not state['stern_module']:
                if not stern_from:
                    raise ExtrasError(wifi_card.NO_STERN_DRIVER)
                stern = wifi_card._stern_module(stern_from)
            wifi_card.prepare_rootfs(part, work, {'enabled': on, 'band5': band}, stern, cancel=cancel)
        if buttons is not None:
            remote_buttons.prepare_rootfs(part, work, bool(buttons.get('enabled')), cancel=cancel)
        expected = ssh_card._hash_file(part)
        if expected == before:
            say('%s already has %s.' % (what, _said(wifi, buttons)), 'ok')
            return 'already'
        remote_setup._cancelled(cancel)
        changed = 0
        with remote_setup._device_guard(path, say):
            with remote_setup._Opened(path, writable=True) as (_info, dest), part.open('rb') as src:
                say('Writing the changes to %s...' % what, 'info')
                done = 0
                while done < size:                  # once begun it finishes: never half a card
                    new = src.read(min(remote_setup.BLOCK, size - done))
                    if dest.read(done, len(new)) != new:
                        dest.write(done, new)
                        changed += 1
                    done += len(new)
                    tick(size + done, size * 3, 'Writing the card')
                remote_setup._opened_sync(dest)
            say('Checking what %s now holds...' % what, 'info')
            got = hashlib.sha256()
            with remote_setup._Opened(path) as (_after, check):
                done = 0
                while done < size:
                    chunk = check.read(done, min(remote_setup.BLOCK, size - done))
                    if not chunk:
                        raise ExtrasError('Reading the card back was cut short.')
                    got.update(chunk)
                    done += len(chunk)
                    tick(2 * size + done, size * 3, 'Checking the card')
    if got.hexdigest() != expected:
        raise ExtrasError("The card didn't read back as written. Try again, or try another card reader.")
    say('%s has %s now (%d MB of its system files changed).' % (what, _said(wifi, buttons), changed), 'ok')
    return 'done'


def to_card_with_privileges(path, *, wifi=None, buttons=None, stern_from=None, log=None, progress=None, cancel=None):
    """:func:`to_card`, elevated for a plugged-in card when the app isn't (as ``remote_setup`` does)."""
    import json
    from . import elevated_flash as ef
    from .admin import is_admin
    from .rawdevice import is_device_path
    if is_admin() or not is_device_path(str(path)):
        return to_card(path, wifi=wifi, buttons=buttons, stern_from=stern_from, log=log, progress=progress,
                       cancel=cancel)
    if log is not None:
        log('Changing the card needs administrator access: approve the prompt to continue.', 'info')
    ipc = ef._ipc_dir('pad_network_')
    try:
        with open(os.path.join(ipc, ef._JOB), 'w', encoding='utf-8') as f:
            json.dump({'mode': 'remote_access', 'device': path,
                       'network_options': {'wifi': wifi, 'buttons': buttons, 'stern_from': stern_from}}, f)
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
    """The elevated helper's side of :func:`to_card_with_privileges`."""
    opts = job['network_options']
    return to_card(job['device'], wifi=opts.get('wifi'), buttons=opts.get('buttons'),
                   stern_from=opts.get('stern_from'), log=log, progress=progress, cancel=cancel)


# ------------------------------------------------------------------ a machine, over remote access
def _q(text):
    return "'" + str(text).replace("'", "'\\''") + "'"


def _sh(machine, script, timeout=120):
    answer = machine.sh(script, timeout=timeout, check=False)
    return answer if isinstance(answer, tuple) else (0, answer)


def _read(machine, path):
    try:
        with machine.sftp.open(path, 'rb') as f:
            return f.read()
    except (OSError, IOError):
        return None


def plan_machine(machine, *, wifi=None, buttons=None, stern_module=None):
    """What :func:`to_machine` would do: ``(puts, links, removes)``, *puts* ``{path: (bytes, mode)}`` only for
    files that differ from what the machine has.  Raises ExtrasError for a machine that cannot take it."""
    puts, links, removes = {}, {}, []
    rc, out = _sh(machine, 'uname -r; for f in %s; do [ -e "$f" ] || [ -L "$f" ] && echo "have $f"; done'
                  % ' '.join(_q(p) for p in (wifi_card.OVERRIDE, wifi_card.HELPER, wifi_card.INIT, wifi_card.LINK,
                                              wifi_card.HOOK, remote_buttons.SO, remote_buttons.MONITOR,
                                              remote_buttons.MODE_SO, remote_buttons.MENU_SO)), 40)
    lines = out.splitlines()
    kernel = lines[0].strip() if lines else ''
    have = {line[5:] for line in lines if line.startswith('have ')}
    if wifi is not None:
        on, band = bool(wifi.get('enabled')), bool(wifi.get('enabled') and wifi.get('band5'))
        if on and wifi_card.HOOK not in have:
            raise ExtrasError(wifi_card.NO_HOOK)
        if on:
            puts[wifi_card.OVERRIDE] = (wifi_card.CONTENT, 0o644)
        elif wifi_card.OVERRIDE in have:
            removes.append(wifi_card.OVERRIDE)
        module = _read(machine, wifi_card.MODULE)
        ours = module is not None and wifi_card._is_ours(module)
        if band:
            if kernel != wifi_card.KERNEL:
                raise ExtrasError(wifi_card.OTHER_KERNEL)
            for path, (data, mode) in wifi_card.band_payload().items():
                puts[path] = (data, mode)
            links[wifi_card.LINK] = wifi_card.LINK_TARGET
        else:
            if ours:
                if not stern_module:
                    raise ExtrasError(wifi_card.NO_STERN_DRIVER)
                puts[wifi_card.MODULE] = (stern_module, 0o644)
            removes += [p for p in (wifi_card.LINK, wifi_card.HELPER, wifi_card.INIT) if p in have]
    if buttons is not None:
        on = bool(buttons.get('enabled'))
        script = _read(machine, remote_buttons.MONITOR)
        if script is None:
            raise ExtrasError(remote_buttons.NOT_STOCK)
        want = remote_buttons.monitor_text(script, on, mode=remote_buttons.MODE_SO in have,
                                           menu=remote_buttons.MENU_SO in have).encode('utf-8')
        puts[remote_buttons.MONITOR] = (want, 0o755)
        if on:
            puts[remote_buttons.SO] = (remote_buttons.shim_bytes(), 0o755)
        elif remote_buttons.SO in have:
            removes.append(remote_buttons.SO)
    # only what differs
    for path in list(puts):
        if _read(machine, path) == puts[path][0]:
            del puts[path]
    if links:
        rc, out = _sh(machine, '; '.join('echo "$(readlink %s 2>/dev/null)"' % _q(p) for p in links), 30)
        got = out.splitlines()
        for i, path in enumerate(list(links)):
            if i < len(got) and got[i].strip() == links[path]:
                del links[path]
    return puts, links, removes


def to_machine(machine, *, wifi=None, buttons=None, stern_module=None, log=None, restart=True):
    """Put *wifi* and/or *buttons* on *machine* (a connected ``remote_send`` machine) and restart it.
    ``'done'``, or ``'already'`` when it had them (then nothing is written and it is not restarted)."""
    say = log or (lambda *_a: None)
    if wifi is None and buttons is None:
        raise ExtrasError('There is nothing to put on the machine.')
    puts, links, removes = plan_machine(machine, wifi=wifi, buttons=buttons, stern_module=stern_module)
    if not puts and not links and not removes:
        say('The machine already has %s.' % _said(wifi, buttons), 'ok')
        return 'already'
    say('Putting %s on the machine...' % _said(wifi, buttons), 'info')
    rc, out = _sh(machine, 'mount -o remount,rw / 2>&1 && echo PAD_RW', 60)
    if 'PAD_RW' not in out:
        raise ExtrasError("The machine's system partition could not be opened for writing: %s" % out.strip()[-160:])
    try:
        staged = []
        for path, (data, mode) in puts.items():
            tmp = path + '.pad-new'
            _sh(machine, 'mkdir -p %s' % _q(posixpath.dirname(path)), 30)
            with machine.sftp.open(tmp, 'wb') as f:
                f.write(data)
            staged.append((tmp, path, mode, hashlib.sha1(data).hexdigest()))
        # every file checked where it was written, before any is moved into place
        if staged:
            rc, out = _sh(machine, 'sha1sum %s' % ' '.join(_q(t) for t, _p, _m, _s in staged), 120)
            got = {a.split()[1]: a.split()[0] for a in out.splitlines() if len(a.split()) == 2}
            bad = [p for t, p, _m, s in staged if got.get(t) != s]
            if bad:
                _sh(machine, 'rm -f %s' % ' '.join(_q(t) for t, _p, _m, _s in staged), 30)
                raise ExtrasError('%s did not arrive on the machine as sent; nothing was changed.' % bad[0])
        steps = ['chmod %o %s && chown 0:0 %s && mv -f %s %s' % (m, _q(t), _q(t), _q(t), _q(p))
                 for t, p, m, _s in staged]
        steps += ['mkdir -p %s && ln -sfn %s %s' % (_q(posixpath.dirname(p)), _q(target), _q(p))
                  for p, target in links.items()]
        steps += ['rm -f %s' % _q(p) for p in removes]
        if wifi is not None and not wifi.get('enabled'):
            steps.append('rmdir %s 2>/dev/null; true' % _q(wifi_card.DIR))
        rc, out = _sh(machine, ' && '.join(steps) + ' && sync && echo PAD_PUT', 120)
        if 'PAD_PUT' not in out:
            raise ExtrasError('The machine did not take the change: %s' % out.strip()[-200:])
    finally:
        _sh(machine, 'sync; mount -o remount,ro / 2>/dev/null; true', 60)
    if restart:
        say('Restarting the machine: it reads these files only when it starts.', 'info')
        machine.reboot()
    return 'done'
