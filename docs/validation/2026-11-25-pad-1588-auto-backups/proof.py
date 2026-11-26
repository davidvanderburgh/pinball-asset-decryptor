"""PAD-1588 stand-in proof, part 2: the app's own backup code against the stand-in machine at 127.0.0.1.

Each check prints a VERDICT line.  The clock of the "by itself" passes is moved on with ``now`` (a day each), as
the app's half-hourly pass would see it on days that follow."""
import hashlib
import os
import sys
import time

W = sys.argv[1]
R = os.environ['STANDIN_ROOT']
from pinball_decryptor.core import machine_backups as B, machine_care as C, machine_scan, pad_ssh_key, remote_send  # noqa

pad_ssh_key.KEY_DIR = os.path.join(W, 'pc')
store = os.path.join(W, 'store')
B.root = lambda: store
DAY = 24 * 3600
ok_all = []


def verdict(what, ok, detail=''):
    ok_all.append(ok)
    print('VERDICT %s: %s%s' % (what, 'PASS' if ok else 'FAIL', ('  (%s)' % detail) if detail else ''))


def pids(name):
    out = []
    for d in os.listdir(os.path.join(R, 'proc')):
        if d.isdigit():
            try:
                with open(os.path.join(R, 'proc', d, 'stat')) as f:
                    if ' (%s) ' % name in f.read():
                        out.append(int(d))
            except OSError:
                pass
    return sorted(out)


def local_sums():
    out = {}
    base = os.path.join(R, 'data')
    for dp, _dn, fn in os.walk(os.path.join(base, 'nv')):
        for n in fn:
            p = os.path.join(dp, n)
            out[os.path.relpath(p, base)] = hashlib.sha1(open(p, 'rb').read()).hexdigest()
    return out


def zips():
    d = B.folder(mid)
    return sorted(n for n in os.listdir(d) if n.endswith('.zip')) if os.path.isdir(d) else []


# the machine, found as a scan finds it: logged in with this PC's key, its identity and game remembered
m = remote_send.SshMachine('127.0.0.1', 22)
game = machine_scan.game_of(m.describe())
pad_ssh_key.remember_machine('127.0.0.1', m.identity, game)
m.close()
mid = B.machine_id(m.identity)
print('machine: game %s, identity %s..., backups kept in %s' % (game, m.identity[1][:24], B.folder(mid)))
verdict('the stand-in lets this PC in and names its game', game == 'godzilla_le', game)

ran = []
real_connect = B._connect


def connect(address, timeout=10):
    mm = real_connect(address, timeout)
    real_sh = mm.sh

    def sh(script, *a, **k):
        ran.append(script)
        return real_sh(script, *a, **k)
    mm.sh = sh
    return mm


KEEP = 3
t0 = time.time()
games_before, monitor = pids('game'), pids('game_monitor')
nv_before = local_sums()
said = []
log = lambda t, l='info': said.append(t)                                       # noqa: E731

# 1. by itself, no click
out = B.auto_pass({'godzilla_le'}, KEEP, connect=connect, now=t0, log=log)
res = out[0][1] if out else None
verdict('1 a machine with remote access is backed up without a click', bool(res) and res['status'] == 'taken'
        and len(zips()) == 1, '%s, %s; log: %s' % (res and res['status'], zips(), said[-1:] if said else ''))
kept = B.kept(mid, sums=True)
verdict('1 the backup holds every file of /data/nv byte for byte', kept and kept[0]['sums'] == nv_before,
        '%d files' % len(nv_before))
verdict('1 it only read: the game ran on, not held or restarted', pids('game') == games_before and games_before
        and pids('game_monitor') == monitor and local_sums() == nv_before
        and not any(w in s for s in ran for w in ('kill', 'pause', 'mv ', 'rm ', 'dprint')),
        'game pid %s -> %s; scripts run: %d, none holding or changing anything' % (games_before, pids('game'), len(ran)))

# 2. a second pass with nothing changed: the same day nothing at all; a day later, read but no duplicate
n_ran = len(ran)
out2 = B.auto_pass({'godzilla_le'}, KEEP, connect=connect, now=t0 + 3600)
verdict('2 the same day: not even logged in to', out2 == [] and len(ran) == n_ran)
out3 = B.auto_pass({'godzilla_le'}, KEEP, connect=connect, now=t0 + DAY + 60)
verdict('2 a day later, nothing changed: no duplicate kept', out3 and out3[0][1]['status'] == 'unchanged'
        and len(zips()) == 1, '%s, %s' % (out3 and out3[0][1]['status'], zips()))
verdict('2 ...and only the sums were read (no copy)', not any(s.startswith('cd /data && tar') for s in ran[n_ran:]))

# 3. scores change each day (as games are played): a new backup each day, pruned to the kept count
first = B.kept(mid)[0]['path']
nvm = sorted(p for p in nv_before if '/NVM/' in p and not p.endswith('.crc32'))[0]


def poke(text):
    """The game writes new scores into its NVM file (64 bytes in), as playing does."""
    with open(os.path.join(R, 'data', nvm), 'r+b') as f:
        f.seek(64)
        f.write(text)

for day in range(2, 6):
    poke(b'HIGH SCORE DAY %d' % day)
    o = B.auto_pass({'godzilla_le'}, KEEP, connect=connect, now=t0 + day * DAY + 60)
    print('  day %d: %s, kept %d, pruned %s' % (day, o[0][1]['status'], len(zips()), o[0][1]['pruned']))
verdict('3 old ones are pruned to the kept count (%d)' % KEEP, len(zips()) == KEEP and not os.path.exists(first),
        ', '.join(zips()))

# 4. restore a kept backup (day 3's scores) after the scores changed again: they come back
target = B.kept(mid, sums=True)[-1]
poke(b'CARD WRITTEN WHOLE, SCORES GONE')
mm = real_connect('127.0.0.1')
changed = local_sums()
res = C.restore_settings(mm, target['path'], log=lambda t, l='info': print('  restore: %s' % t))
mm.close()
after = local_sums()
verdict('4 a restore from a kept backup brings back changed scores', changed != target['sums'] and
        after == target['sums'], '%s restored: %d files; %s now reads %r' % (
            target['taken'], res['files'], nvm, open(os.path.join(R, 'data', nvm), 'rb').read()[64:80]))

# 5. before a Send: one is taken whatever its age; none when nothing changed since
mm = real_connect('127.0.0.1')
r1 = B.before_send(mm, KEEP, log)
r2 = B.before_send(mm, KEEP, log)
mm.close()
verdict('5 before a Send: the restored settings backed up, then no duplicate', r1['status'] in ('taken', 'unchanged')
        and r2['status'] == 'unchanged', '%s then %s; %s' % (r1['status'], r2['status'], said[-1]))
print('ALL', 'PASS' if all(ok_all) else 'FAIL')
