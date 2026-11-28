"""PAD-1643 stand-in proof, part 2: the app's own "put it on the machine" code against the stand-in machine at
127.0.0.1, over its own dropbear, with the real v0.3.0 release.  Each check prints a VERDICT line."""
import hashlib
import os
import signal
import stat
import subprocess
import sys
import time

W = sys.argv[1]
R = os.environ['STANDIN_ROOT']
from pinball_decryptor.core import bluetooth_card as BT, card_plugins as P, network_apply as A  # noqa: E402
from pinball_decryptor.core import pad_ssh_key, remote_buttons as B, remote_send  # noqa: E402
from pinball_decryptor.core.card_extras import ExtrasError  # noqa: E402

pad_ssh_key.KEY_DIR = os.path.join(W, 'pc')
ok_all = []


def verdict(what, ok, detail=''):
    ok_all.append(bool(ok))
    print('VERDICT %s: %s%s' % (what, 'PASS' if ok else 'FAIL', ('  (%s)' % detail) if detail else ''), flush=True)


def inside(path):
    """The PC's path of the machine's *path*, its links followed inside the machine (its /tmp is a link)."""
    parts, done, hops = [x for x in path.split('/') if x], '', 0
    while parts:
        part = parts.pop(0)
        full = R + done + '/' + part
        if os.path.islink(full) and hops < 16:
            hops += 1
            target = os.readlink(full)
            if target.startswith('/'):
                done = ''
            parts = [x for x in target.split('/') if x] + parts
            continue
        done += '/' + part
    return R + done


def covered():
    """The machine's paths that something is mounted over (its /data, /dev, the stand-ins): not the card's."""
    with open('/proc/mounts') as f:
        return sorted(l.split()[1][len(R):] for l in f if l.split()[1].startswith(R + '/'))


def tree(root, skip=()):
    """{path: (kind, mode, uid, gid, sha1 or link target)} of the filesystem mounted at *root*, without the paths
    in *skip* and what is under them."""
    out = {}
    for dp, dn, fn in os.walk(root):
        rel_dir = ('/' + os.path.relpath(dp, root).replace(os.sep, '/')) if dp != root else ''
        dn[:] = [d for d in dn if rel_dir + '/' + d not in skip]
        for n in dn + fn:
            p = os.path.join(dp, n)
            rel = rel_dir + '/' + n
            if rel in skip:
                continue
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                what = os.readlink(p)
            elif stat.S_ISREG(st.st_mode):
                with open(p, 'rb') as f:
                    what = hashlib.sha1(f.read()).hexdigest()
            else:
                what = ''
            out[rel] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid, what)
    return out


def differ(a, b):
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def mounted():
    with open('/proc/mounts') as f:
        return next(l.split()[3].split(',')[0] for l in f if l.split()[1] == R)


def pids(word):
    out = []
    for d in os.listdir(os.path.join(R, 'proc')):
        if d.isdigit():
            try:
                with open(os.path.join(R, 'proc', d, 'cmdline'), 'rb') as f:
                    if word.encode() in f.read().replace(b'\0', b' '):
                        out.append(int(d))
            except OSError:
                pass
    return sorted(out)


def asked(want=None):
    """How many times the machine was told to restart (the app asks for it two seconds after its last word)."""
    for _ in range(20 if want else 0):
        if asked() >= want:
            break
        time.sleep(0.5)
    try:
        with open(inside('/tmp/reboot-asked')) as f:
            return len(f.read().split())
    except OSError:
        return 0


def restart():
    """What a restart does for the game: the card's game_monitor is started afresh (traced), with the stand-in
    game.  Returns (the trace, the stand-in's own record)."""
    for word in ('game_monitor', '/games/standin', 'run-live.sh', 'spikebt', 'pad-bt-game'):
        for p in pids(word):
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
    time.sleep(1)
    # a machine that starts mounts its card read-only; here the same remount the app asked for is asked again,
    # now that the old game_monitor (which still held its replaced script file open) has ended
    subprocess.run(['chroot', R, '/bin/sh', '-c', 'mount -o remount,ro /'], capture_output=True)
    for n in ('gm.log', 'standin.log'):
        try:
            os.remove(inside('/tmp/' + n))
        except OSError:
            pass
    subprocess.run(['chroot', R, '/bin/sh', '-c',
                    '/bin/sh -x /etc/init.d/game_monitor /games/standin </dev/null >/tmp/gm.log 2>&1 &'], check=True)
    for _ in range(90):
        time.sleep(1)
        if os.path.exists(inside('/tmp/standin.log')):
            break
    time.sleep(2)

    def read(n):
        try:
            with open(inside('/tmp/' + n), errors='replace') as f:
                return f.read()
        except OSError:
            return ''
    return read('gm.log'), read('standin.log')


def connect():
    return remote_send.SshMachine('127.0.0.1', 22)


def say(text, *_a):
    print('    app: %s' % text, flush=True)


rec = P.installed(BT.PLUGIN)
print('release on this PC: %s (tested with the app: %s)' % (rec['tag'], rec['tested']))
SKIP = covered()
print('mounted over the card, so left out of every comparison: %s' % ', '.join(SKIP))
before, twin = tree(os.path.join(W, 'before'), SKIP), tree(os.path.join(W, 'twin'), SKIP)
start = tree(R, SKIP)
verdict('the machine starts as the card without the plugin, mounted read-only', not differ(start, before)
        and mounted() == 'ro', '%d files and folders, root %s' % (len(start), mounted()))
trace, record = restart()
verdict('before: its game_monitor starts the game directly', 'run-live.sh' not in trace and 'STANDIN started' in record,
        record.strip().replace('\n', ' | '))

# ---- 1. what Check it on the machine says before
m = connect()
print('machine: %s' % m.describe().splitlines()[0])
said = BT.check_machine(m)
verdict('Check it on the machine, before', 'has no Bluetooth headphones on it' in said, said)
probe = BT.probe_machine(m)
verdict('the machine is told apart by its own answers', probe['platform'] == BT.SPIKE2
        and probe['monitor'] == BT.MONITOR and probe['free'] and not probe['dir'],
        'platform %s, script %s, %.1f MB free' % (probe['platform'], probe['monitor'], (probe['free'] or 0) / 1e6))

# ---- 2. put it on
# the launcher's own switched-off mark, as a game that ended badly leaves it: a fresh install must not stay off
m.sh('mkdir -p /dump/spikebt && : > ' + BT.DISABLED)
t0 = time.time()
res = BT.to_machine(m, True, log=say)
took = time.time() - t0
m.close()
print('    said on the page: %s' % BT.machine_said(res, True))
verdict('Put it on the machine now', res['result'] == 'done' and res['tag'] == rec['tag']
        and res['platform'] == BT.SPIKE2, 'result %s, release %s, %.1f s' % (res['result'], res['tag'], took))
verdict('the restart was asked for, once', asked(1) == 1)
verdict("the machine's real game program is one the release knows", res['game']['known'] is True, res['game']['text'])
print('    the card straight after: mounted %s (while the running game_monitor still holds its replaced script '
      'open the card cannot go back to read-only; the restart ends that)' % mounted())
verdict("the launcher's switched-off mark is gone", not os.path.exists(inside(BT.DISABLED)))
after = tree(R, SKIP)
d = differ(after, twin)
verdict("the machine's card now equals one the card-write path made, file for file (bytes, mode, owner)",
        not d, '%d entries compared; differ: %s' % (len(twin), d[:6] or 'none'))
new = sorted(p for p in after if p not in start)
changed = sorted(p for p in after if p in start and after[p] != start[p])
print('    added: %s' % ', '.join(new))
print('    changed: %s' % ', '.join(changed))
verdict('only the plugin folder, the wrapper and game_monitor changed',
        changed == [BT.MONITOR] and all(p == BT.DIR or p.startswith(BT.DIR + '/') or p == BT.WRAPPER for p in new))
sums = subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=R + BT.DIR, capture_output=True, text=True)
verdict("the author's own SHA256SUMS checks out on the machine", sums.returncode == 0,
        '%d files OK' % sums.stdout.count(': OK'))
verdict('nothing left on its way', not [p for p in after if p.endswith(BT.NEW)])

# ---- 3. the restart: the card's own game_monitor now starts the game through the author's launcher
trace, record = restart()
verdict('once the old game_monitor has ended the card is read-only again', mounted() == 'ro')
launcher = [l.strip() for l in trace.splitlines() if 'run-live.sh' in l]
verdict('after the restart game_monitor runs the launcher with the game', bool(launcher) and 'STANDIN started' in record,
        '%s -> %s' % (launcher[-1] if launcher else 'no launcher line', record.strip().replace('\n', ' | ')))
print('    game_monitor trace (tail):')
for line in trace.splitlines()[-14:]:
    print('      ' + line)
m = connect()
said = BT.check_machine(m)
verdict('Check it on the machine, after', 'spike-pinball-bluetooth %s is on the machine and switched on' % rec['tag'] in said, said)

# ---- 4. again: nothing to do
n0 = asked()
time.sleep(4)
res = BT.to_machine(m, True, log=say)
verdict('Put it on again changes nothing and does not restart', res['result'] == 'already' and asked() == n0
        and not differ(tree(R, SKIP), twin), BT.machine_said(res, True))

# ---- 5. take it off
res = BT.to_machine(m, False, log=say)
m.close()
d = differ(tree(R, SKIP), before)
verdict('Take it off the machine puts the card back exactly as it was', res['result'] == 'done' and not d
        and asked(n0 + 1) == n0 + 1, 'differ from the card before: %s' % (d[:6] or 'none'))
trace, record = restart()
verdict('after that restart game_monitor starts the game directly again', 'run-live.sh' not in trace
        and 'STANDIN started' in record)

# ---- 6. a card Stern's own updater brought up to date: game_monitor is a link into /spk/packages (PAD-1619)
real = '/spk/packages/spike-1.16.0/etc/init.d/game_monitor'
subprocess.run(['mount', '-o', 'remount,rw', R], check=True)
os.makedirs(os.path.dirname(R + real), exist_ok=True)
os.rename(R + BT.MONITOR, R + real)
os.symlink(real, R + BT.MONITOR)
subprocess.run(['mount', '-o', 'remount,ro', R], check=True)
m = connect()
verdict('a linked game_monitor is followed to its file', BT.probe_machine(m)['monitor'] == real
        and A._real(m, BT.MONITOR) == real, real)
res = BT.to_machine(m, True, log=say)
with open(R + real) as f:
    text = f.read()
verdict('on such a card the link stays and its file gets the block', res['result'] == 'done'
        and os.path.islink(R + BT.MONITOR) and os.readlink(R + BT.MONITOR) == real and B.has_block(text, B.BT_HOOK_LINES))
trace, record = restart()
verdict('and its game_monitor runs the launcher', 'run-live.sh' in trace and 'STANDIN started' in record)

# ---- 7. a machine that cannot take it is left alone
P_files = P.files
P.files = lambda *a, **k: (_ for _ in ()).throw(P.PluginError('The Bluetooth headphones plugin is not installed.'))
snap = tree(R, SKIP)
try:
    BT.to_machine(m, True)
    refused = False
except ExtrasError as e:
    refused = 'not installed' in str(e)
P.files = P_files
verdict('with the plugin not on this PC it is refused and the machine untouched', refused and not differ(tree(R, SKIP), snap))
m.close()
print('ALL %d CHECKS PASSED' % len(ok_all) if all(ok_all) else 'FAILED: %d of %d' % (ok_all.count(False), len(ok_all)))
sys.exit(0 if all(ok_all) else 1)
