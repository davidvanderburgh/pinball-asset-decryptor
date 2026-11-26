"""Send to machine for Jersey Jack Pinball installs (PAD-1587).

A JJP build is a whole install ISO (Clonezilla, the root as gzip-split partclone), but what a build changes is
known file by file: the JJP Write puts every changed file into the root with debugfs.  So the build leaves a Send
record beside the ISO, ``<iso>.pad-send/``: ``send.json`` (the game, the install it was built from, every changed
file's path, sha1, size, mode and owner, and a few unchanged files that identify the install's version) and the
changed files' final bytes, read back out of the finished root.  A Send needs nothing else: no partclone to
unpack, no original ISO.

On the machine a Send:

1. checks it runs the same game, and the same install of it (the identifying files match);
2. holds the game the way a Stern Send does (core/remote_send.py: the restart loop, ``rungame.sh`` on JJP, is
   frozen and the game ended);
3. keeps each file's original the first time PAD changes it, in ``/var/lib/pad/send/orig`` on the root, and
   says so in its ledger (``/var/lib/pad/send/ledger.json``) BEFORE it changes it;
4. uploads each changed file beside its place, checks its sha1 there, sets its mode and owner and renames it in;
5. puts back the original of every file an earlier Send changed that this build does not (a build with fewer
   changes leaves the machine as that build, not as both);
6. lets the restart loop go: it starts the game on the new files.

A reinstall replaces the root, so the ledger and the originals go with the files they describe.
"""
import hashlib
import json
import os
import posixpath
import time

from .remote_send import PIDS_FN, SendError, NotThisCard, _q, _human, screen_text

SET_SUFFIX = '.pad-send'
SET_FILE = 'send.json'
KIND = 'pad-jjp-send'
STATE_DIR = '/var/lib/pad/send'
LEDGER = STATE_DIR + '/ledger.json'
ORIG = STATE_DIR + '/orig'
TMP_TAG = '.pad-send'
#: room left on the machine's root after a Send (its logs and the game's temp files need it)
SPARE = 64 << 20
GAME_SH = '. /jjpe/gen1/setenv.sh >/dev/null 2>&1; echo "$GAMENAME"'


def set_dir(iso):
    return str(iso) + SET_SUFFIX


def _iso_stamp(iso):
    st = os.stat(iso)
    return dict(name=os.path.basename(iso), size=st.st_size, mtime=int(st.st_mtime))


def write_set(iso, manifest):
    """Finish the Send record of the build at *iso*: the files are in :func:`set_dir` already (``files[i].file``);
    the record is stamped with the ISO it belongs to and checked against the files' own sha1s."""
    d = set_dir(iso)
    for f in manifest['files']:
        if f.get('file'):
            with open(os.path.join(d, f['file']), 'rb') as fh:
                got = hashlib.sha1(fh.read()).hexdigest()
            if got != f['sha1']:
                raise SendError('The Send record of %s does not match what was built (%s).' % (iso, f['path']))
    manifest = dict(manifest, kind=KIND, version=1, iso=_iso_stamp(iso))
    tmp = os.path.join(d, SET_FILE + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(d, SET_FILE))
    return manifest


def restamp(iso):
    """After the ISO was moved to where the user wanted it (its Send record moved beside it)."""
    path = os.path.join(set_dir(iso), SET_FILE)
    with open(path, encoding='utf-8') as fh:
        manifest = json.load(fh)
    manifest['iso'] = _iso_stamp(iso)
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    os.replace(path + '.tmp', path)


def read_set(iso, check_files=True):
    """The Send record of the JJP build at *iso*, or None when it has none.  Raises :class:`SendError` when the
    record is not this ISO's (the ISO was built again or replaced) or is damaged."""
    path = os.path.join(set_dir(iso), SET_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        raise SendError('The Send record beside %s is damaged; build it again.' % os.path.basename(iso)) from None
    if not isinstance(rec, dict) or rec.get('kind') != KIND:
        raise SendError('The Send record beside %s is not one this app made.' % os.path.basename(iso))
    stamp = rec.get('iso') or {}
    try:
        now = _iso_stamp(iso)
    except OSError:
        raise SendError('There is no built image to send yet: build it first.') from None
    if (stamp.get('size'), stamp.get('mtime')) != (now['size'], now['mtime']):
        raise SendError('%s is not the build its Send record describes (it was changed or replaced); build it '
                        'again, then send.' % os.path.basename(iso))
    if check_files:
        for f in rec.get('files') or []:
            if 'link' in f:
                continue
            p = os.path.join(set_dir(iso), f.get('file') or '')
            if not os.path.isfile(p) or os.path.getsize(p) != f['size']:
                raise SendError('The Send record beside %s is missing %s; build it again.'
                                % (os.path.basename(iso), f['path']))
    return rec


def is_build(iso):
    return os.path.isfile(os.path.join(set_dir(iso), SET_FILE))


# ------------------------------------------------------------------ the machine
def machine_game(machine):
    _rc, out = machine.sh(GAME_SH, check=False, timeout=30)
    return out.strip().splitlines()[-1].strip() if out.strip() else ''


def is_jjp_machine(machine):
    rc, _out = machine.sh('[ -d /jjpe/gen1 ] && [ -f /jjpe/gen1/setenv.sh ]', check=False, timeout=30)
    return rc == 0


def read_ledger(machine):
    try:
        with machine.sftp.open(LEDGER, 'rb') as f:
            data = json.loads(f.read().decode('utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_ledger(machine, data):
    machine.sh('mkdir -p %s' % _q(STATE_DIR))
    with machine.sftp.open(LEDGER + '.tmp', 'wb') as f:
        f.write(json.dumps(data, indent=1, sort_keys=True).encode('utf-8'))
    machine.sh('mv -f %s %s && sync' % (_q(LEDGER + '.tmp'), _q(LEDGER)))


#: the hold checked before anything changes: the game's loop stopped, and no game running (``LOOP T`` / ``GAME <pid>``)
HELD_SCRIPT = PIDS_FN + r'''
for p in $(pids_named rungame.sh); do read -r st < /proc/$p/stat 2>/dev/null && echo "LOOP ${st##*) }"; done
for p in $(pids_named game); do
  read -r st < /proc/$p/stat 2>/dev/null || continue
  case "${st##*) }" in Z*) ;; *) echo "GAME $p" ;; esac
done
'''


def held(machine):
    """True when the machine's game loop is stopped and no game runs (what a Send needs before it changes files)."""
    _rc, out = machine.sh(HELD_SCRIPT, check=False, timeout=60)
    lines = out.splitlines()
    loops = [ln.split()[1] for ln in lines if ln.startswith('LOOP ') and len(ln.split()) > 1]
    return bool(loops) and all(st[0] in 'Tt' for st in loops) and not any(ln.startswith('GAME ') for ln in lines)


def _orig(path):
    return ORIG + path


KEEP_SCRIPT = r'''
p=@P@; o=@O@
if [ -e "$p" ] || [ -L "$p" ]; then mkdir -p "$(dirname "$o")" && rm -rf "$o" && cp -a "$p" "$o" && echo saved
else echo absent; fi
'''

PUT_BACK_SCRIPT = r'''
p=@P@; o=@O@; how=@HOW@
if [ "$how" = saved ]; then
  [ -e "$o" ] || [ -L "$o" ] || { echo "PAD_NO_ORIGINAL"; exit 3; }
  t="$(dirname "$p")/.$(basename "$p").pad-send"
  rm -rf "$t" && cp -a "$o" "$t" && mv -f "$t" "$p" && rm -f "$o"
else
  rm -f "$p"
fi
'''


def _plan(rec, machine, ledger):
    """``(puts, put_backs)``: the build's files the machine does not have as built, and the files an earlier Send
    changed that this build leaves as the install has them."""
    files = rec['files']
    plain = [f for f in files if 'link' not in f]
    have = machine.file_sha1s([f['path'] for f in plain]) if plain else {}
    links = [f for f in files if 'link' in f]
    now = machine.state([f['path'] for f in links]) if links else {}
    puts = ([f for f in plain if have.get(f['path']) != ('file', f['sha1'])]
            + [f for f in links if now.get(f['path']) != ('link', f['link'])])
    mine = {f['path'] for f in files}
    backs = sorted(p for p in (ledger.get('paths') or {}) if p not in mine)
    return puts, backs


def _check_identity(rec, machine, ledger):
    """The machine runs the install this was built from: each identifying file is as the install has it (or, when
    an earlier Send changed it, the original PAD kept of it is)."""
    ident = rec.get('identity') or {}
    if not ident:
        return
    changed = ledger.get('paths') or {}
    look = {p: (_orig(p) if changed.get(p) == 'saved' else p) for p in ident}
    got = machine.file_sha1s(sorted(set(look.values())))
    wrong = [p for p, want in sorted(ident.items()) if got.get(look[p]) != ('file', want)]
    if wrong:
        raise NotThisCard('The machine runs another version of %s than %s, which this build was made from (%s '
                          'differs). Install the build from a USB stick instead.'
                          % (rec.get('game') or 'the game', rec.get('source') or 'the install',
                             posixpath.basename(wrong[0])))


def send_build(iso, machine, log=None, progress=None, cancel=None):
    """Send the JJP build at *iso* to *machine*; a summary line."""
    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a, **k: None)
    cancelled = cancel or (lambda: False)
    rec = read_set(iso)
    if rec is None:
        raise SendError('%s has no Send record: it was built by an older version, or is not a JJP build. Build '
                        'it again, then send.' % os.path.basename(iso))
    from . import pad_ssh_key
    remote = rec.get('remote') or {}
    mine = pad_ssh_key.public_line().split()
    if not remote.get('enabled') or len(mine) < 2 or mine[1] not in remote.get('public_keys', ''):
        raise SendError("This build has remote access off, or doesn't let this computer in, so after it the "
                        "machine couldn't be reached from here again. Turn Remote access on (Network tab) and "
                        "build again.")
    progress(0, 1, 'Comparing the build with the machine')
    if not is_jjp_machine(machine):
        raise NotThisCard('The machine at this address is not a Jersey Jack Pinball machine; this is a JJP build.')
    game = machine_game(machine)
    if rec.get('game') and game != rec['game']:
        raise NotThisCard('The machine runs %s, and this build is of %s. Pick the right machine.'
                          % (game or 'another game', rec['game']))
    ledger = read_ledger(machine)
    _check_identity(rec, machine, ledger)
    puts, backs = _plan(rec, machine, ledger)
    if not puts and not backs:
        return 'The machine already has this build: nothing to send.'
    known = ledger.get('paths') or {}
    need = sum(f.get('size', 0) for f in puts) * 2 + SPARE
    free = machine.free('/')
    if free < need:
        raise SendError('The machine has %s free on its system disk and this Send needs about %s (each changed '
                        "file goes beside the one it replaces, and PAD keeps the original). Install the build "
                        'from a USB stick instead.' % (_human(free), _human(need)))
    log("Holding the machine's game for the Send (a game being played ends).", 'info')
    machine.pause_game()
    if not held(machine):
        # never change files under a running game: say so, and give the game back
        try:
            machine.screen_stopped(False)
        except Exception:                               # noqa: BLE001 - the refusal is what to report
            pass
        raise SendError("The machine's game could not be held for the Send (its game loop did not stop); nothing "
                        'was changed. Send again; if it says this again, restart the machine first.')
    total = sum(f.get('size', 0) for f in puts) or 1
    done = 0
    changed = False
    try:
        new_ledger = dict(ledger, game=game, paths=dict(known))
        # every original is kept, and the ledger says so, before anything of the machine changes
        for f in puts:
            if f['path'] in known:
                continue
            _rc, out = machine.sh(KEEP_SCRIPT.replace('@P@', _q(f['path'])).replace('@O@', _q(_orig(f['path']))),
                                  timeout=600)
            new_ledger['paths'][f['path']] = 'saved' if out.strip().endswith('saved') else 'absent'
        new_ledger['build'] = (rec.get('iso') or {}).get('name', os.path.basename(iso))
        new_ledger['sending'] = True
        write_ledger(machine, new_ledger)
        temps = []
        for f in puts:
            if 'link' in f:
                continue
            if cancelled():
                raise SendError('The Send was stopped before anything on the machine changed.')
            path = f['path']
            tmp = posixpath.join(posixpath.dirname(path), '.' + posixpath.basename(path) + TMP_TAG)
            machine.sh('mkdir -p %s' % _q(posixpath.dirname(path)))
            size = f['size']
            base = done
            with open(os.path.join(set_dir(iso), f['file']), 'rb') as fh:
                machine.upload(tmp, fh, size, f['mode'], f['uid'], f['gid'],
                               callback=lambda n, _t, b=base: progress(b + n, total, 'Uploading %s'
                                                                       % posixpath.basename(path)))
            done += size
            temps.append((tmp, path, f['sha1']))
            machine.screen_progress(done, total, 'Uploading')
        got = machine.file_sha1s([t for t, _p, _s in temps])
        bad = [p for t, p, s in temps if got.get(t) != ('file', s)]
        if bad:
            machine.remove([t for t, _p, _s in temps])
            raise SendError('%s did not arrive on the machine as built; nothing was changed. Send again.' % bad[0])
        progress(total, total, 'Updating the machine')
        machine.screen_changing()
        changed = True
        machine.commit([(t, p) for t, p, _s in temps],
                       [(f['path'], f['link'], 0, 0) for f in puts if 'link' in f], [])
        for p in backs:
            how = known.get(p, 'absent')
            machine.sh(PUT_BACK_SCRIPT.replace('@P@', _q(p)).replace('@O@', _q(_orig(p)))
                       .replace('@HOW@', _q(how)), timeout=600)
            new_ledger['paths'].pop(p, None)
        machine.sync()
        new_ledger.pop('sending', None)
        new_ledger['sent'] = time.strftime('%Y-%m-%d %H:%M:%S')
        write_ledger(machine, new_ledger)
        progress(total, total, 'Finishing: restarting the game')
        said = machine.resume_game(screen_text('UPDATE DONE', 'RESTARTING GAME'))
    except BaseException:
        if not changed:
            try:
                machine.screen_stopped(False)
            except Exception:                           # noqa: BLE001 - the first failure is the one to report
                pass
        raise
    parts = ['%d changed file%s (%s)' % (len(puts), '' if len(puts) == 1 else 's',
                                         _human(sum(f.get('size', 0) for f in puts)))]
    if backs:
        parts.append('%d put back as the install has %s' % (len(backs), 'it' if len(backs) == 1 else 'them'))
    if said.startswith('PAD_SEND_RESTARTED'):
        tail = 'the game restarted on them.'
    elif said == 'PAD_SEND_NOT_RUNNING':
        tail = 'the game was not running; it starts on them next time.'
    else:
        tail = 'the game has not come back yet: restart the machine if it does not.'
    return 'Sent %s to the machine; %s' % (', '.join(parts), tail)


# ------------------------------------------------------------------ the build's side
def manifest_entry(path, file_name, data, mode, uid, gid):
    return dict(path=path, file=file_name, sha1=hashlib.sha1(data).hexdigest(), size=len(data), mode=mode,
                uid=uid, gid=gid)

