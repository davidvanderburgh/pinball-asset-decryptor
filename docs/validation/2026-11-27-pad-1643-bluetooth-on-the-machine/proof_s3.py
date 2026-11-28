"""PAD-1643 Spike 3 stand-in proof: the app's own "put it on the machine" code against the real Fallout LE 0.82
system partition running as a machine at 127.0.0.1 (its own dropbear, its own busybox under qemu-aarch64), with
the real v0.3.0 arm64 release.  Each check prints a VERDICT line."""
import hashlib
import os
import stat
import subprocess
import sys
import time

W = sys.argv[1]
R = os.environ['STANDIN_ROOT']
from pinball_decryptor.core import bluetooth_card as BT, card_plugins as P  # noqa: E402
from pinball_decryptor.core import pad_ssh_key, remote_send  # noqa: E402

pad_ssh_key.KEY_DIR = os.path.join(W, 'pc')
ok_all = []


def verdict(what, ok, detail=''):
    ok_all.append(bool(ok))
    print('VERDICT %s: %s%s' % (what, 'PASS' if ok else 'FAIL', ('  (%s)' % detail) if detail else ''), flush=True)


def covered():
    with open('/proc/mounts') as f:
        return sorted(l.split()[1][len(R):] for l in f if l.split()[1].startswith(R + '/'))


def tree(root, skip=()):
    out = {}
    for dp, dn, fn in os.walk(root):
        rel_dir = ('/' + os.path.relpath(dp, root)) if dp != root else ''
        dn[:] = [d for d in dn if rel_dir + '/' + d not in skip]
        for n in dn + fn:
            p, rel = os.path.join(dp, n), rel_dir + '/' + n
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


def asked(want=0):
    for _ in range(20):
        try:
            with open(os.path.join(W, 'reboot-asked')) as f:
                n = len(f.read().split())
        except OSError:
            n = 0
        if n >= want:
            break
        time.sleep(0.5)
    return n


def say(text, *_a):
    if ': file ' not in text:
        print('    app: %s' % text, flush=True)


rec = P.installed(BT.PLUGIN)
SKIP = covered()
print('mounted over the card, so left out of every comparison: %s' % ', '.join(SKIP))
before, twin = tree(os.path.join(W, 'before'), SKIP), tree(os.path.join(W, 'twin'), SKIP)
start = tree(R, SKIP)
verdict('the machine starts as the card without the plugin, mounted read-only', not differ(start, before)
        and mounted() == 'ro', '%d files and folders, root %s' % (len(start), mounted()))
m = remote_send.SshMachine('127.0.0.1', 22)
said = BT.check_machine(m)
verdict('Check it on the machine, before', 'has no Bluetooth headphones on it' in said, said)
probe = BT.probe_machine(m)
verdict('the machine is told apart by its own answers', probe['platform'] == BT.SPIKE3 and probe['free'],
        'platform %s, script %s, %.1f MB free' % (probe['platform'], probe['monitor'], (probe['free'] or 0) / 1e6))
m.sh('mkdir -p /dump/spikebt && : > ' + BT.DISABLED)
res = BT.to_machine(m, True, log=say)
print('    said on the page: %s' % BT.machine_said(res, True))
verdict('Put it on the machine now', res['result'] == 'done' and res['tag'] == rec['tag'] and res['platform'] == BT.SPIKE3)
verdict('the restart was asked for, once', asked(1) == 1)
print('    the card straight after: mounted %s' % mounted())
after = tree(R, SKIP)
d = differ(after, twin)
verdict("the machine's card now equals one the card-write path made, file for file (bytes, mode, owner)",
        not d, '%d entries compared; differ: %s' % (len(twin), d[:6] or 'none'))
new = sorted(p for p in after if p not in start)
changed = sorted(p for p in after if p in start and after[p] != start[p])
print('    added: %s' % ', '.join(new))
print('    changed: %s' % ', '.join(changed))
verdict('only the plugin folder and game_monitor changed; no driver, no wrapper', changed == [BT.MONITOR]
        and all(p == BT.DIR or p.startswith(BT.DIR + '/') for p in new)
        and BT.DIR + '/btusb.ko' not in after and BT.WRAPPER not in after)
with open(R + BT.MONITOR) as f:
    text = f.read()
verdict('game_monitor runs the launcher with bluez5', 'SPIKEBT_BACKEND=bluez5 /usr/local/spikebt/run-live.sh $GAME' in text)
sums = subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=R + BT.DIR, capture_output=True, text=True)
verdict("the author's own SHA256SUMS checks out on the machine", sums.returncode == 0,
        '%d files OK' % sums.stdout.count(': OK'))
verdict("the launcher's switched-off mark is gone", not os.path.exists(R + '/connectivity/dump/spikebt/disabled'))
said = BT.check_machine(m)
verdict('Check it on the machine, after', 'spike-pinball-bluetooth %s is on the machine and switched on' % rec['tag'] in said, said)
time.sleep(4)
n0 = asked()
res = BT.to_machine(m, True, log=say)
verdict('Put it on again changes nothing and does not restart', res['result'] == 'already' and asked() == n0
        and not differ(tree(R, SKIP), twin), BT.machine_said(res, True))
res = BT.to_machine(m, False, log=say)
d = differ(tree(R, SKIP), before)
verdict('Take it off the machine puts the card back exactly as it was', res['result'] == 'done' and not d
        and asked(n0 + 1) == n0 + 1, 'differ from the card before: %s' % (d[:6] or 'none'))
m.close()
print('ALL %d CHECKS PASSED' % len(ok_all) if all(ok_all) else 'FAILED: %d of %d' % (ok_all.count(False), len(ok_all)))
sys.exit(0 if all(ok_all) else 1)
