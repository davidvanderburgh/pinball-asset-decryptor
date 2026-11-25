"""PAD-1587 proof, the client side: the app's own code against the JJP stand-in (netns padc, WSL python).

    ip netns exec padc env PYTHONPATH=/tmp/pad1587-py python3 client.py <iso>
"""
import hashlib
import io
import json
import os
import sys
import tarfile
import time
import zipfile

WT = '/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1587'
sys.path.insert(0, WT)
from pinball_decryptor.core import pad_ssh_key  # noqa: E402

pad_ssh_key.KEY_DIR = '/tmp/pad1587-client/remote_access'      # the throwaway key, never this PC's own
from pinball_decryptor.core import machine_care, machine_scan, remote_send, remote_send_jjp  # noqa: E402

ISO = sys.argv[1]
OUT = '/mnt/c/tmp/PAD-1587/proof'
os.makedirs(OUT, exist_ok=True)
PIC = '/jjpe/gen1/miscfiles/graphics/JJP_logo_message.png'
verdicts = []


def say(*a):
    print(*a, flush=True)


def verdict(name, ok, detail=''):
    verdicts.append((name, ok))
    say('VERDICT %-22s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail))


def sh(m, cmd):
    return m.sh(cmd, check=False)[1].strip()


# 1. the machine found on the network (the app's own scan; nothing told it the address)
t = time.time()
found = machine_scan.scan(nets=None)
say('scan:', found)
hit = [f for f in found if str(f.get('address', '')).startswith('192.168.77.50')]
verdict('found on the network', bool(hit) and hit[0].get('game') == 'Wonka',
        '%s in %.1f s' % (hit[0] if hit else None, time.time() - t))
addr = '192.168.77.50'
if hit and hit[0].get('host_key'):
    pad_ssh_key.remember_host(addr, 22, *hit[0]['host_key'])

# 2. status
m = remote_send.connect(addr)
rows = machine_care.status(m)
say('status:', rows)
verdict('status', ('Game on the card', 'Wonka') in rows and machine_care.kind(m) == 'jjp', str(rows[:3]))
# the machine as installed from a build with remote access alone: the install's own picture (the stock one)
import subprocess
stock = subprocess.run(['debugfs', '-R', 'cat ' + PIC, '/var/tmp/jjp_Wonka-v03.03/sda3.raw'],
                       capture_output=True).stdout
assert hashlib.sha1(stock).hexdigest() == 'e7c0a567ddb7bd98ca8be09c30e306f2a3540cbc'
with m.sftp.open(PIC, 'wb') as f:
    f.write(stock)
m.sh('rm -rf /var/lib/pad/send /var/lib/pad/perm.pad-old.tar', check=False)
say('setup: stock picture back on the machine; restart:', m.restart_game())
time.sleep(2)
before_pic = sh(m, 'sha1sum %s | cut -c1-40' % PIC)
time.sleep(2)
before_game = sh(m, 'cat /jjpe/temp/standin-game.log')
say('before game log tail:', before_game.splitlines()[-1:])
m.close()

# 3. Send: the app's own run (SendPipeline -> send_image -> remote_send_jjp.send_build)
rec = remote_send_jjp.read_set(ISO)
want = {f['path']: f for f in rec['files']}
say('record: %d entries: %s' % (len(rec['files']), sorted(want)))
logs = []
res = {}
p = remote_send.SendPipeline(ISO, addr, lambda msg, lvl='info': (logs.append(msg), say('  send log:', msg)),
                             lambda *a: None, lambda *a: None, lambda ok, s: res.update(ok=ok, s=s))
p.run()
say('send result:', res)
m = remote_send.connect(addr)
after_pic = sh(m, 'sha1sum %s | cut -c1-40' % PIC)
time.sleep(3)
after_game = sh(m, 'cat /jjpe/temp/standin-game.log')
ledger = remote_send_jjp.read_ledger(m)
verdict('send as a delta', res.get('ok') and after_pic == want[PIC]['sha1'] and after_pic != before_pic
        and 'Sent 1 changed file' in res.get('s', ''), res.get('s', ''))
new_lines = [ln for ln in after_game.splitlines() if ln not in before_game.splitlines()]
verdict('game restarted on it', 'the game restarted on them' in res.get('s', '')
        and any(want[PIC]['sha1'][:12] in ln for ln in new_lines), ' | '.join(new_lines))
verdict('original kept', ledger.get('paths', {}).get(PIC) == 'saved'
        and sh(m, 'sha1sum /var/lib/pad/send/orig%s | cut -c1-40' % PIC) == before_pic, json.dumps(ledger)[:200])
m.close()

# 4. the same build again: nothing to send
res2 = {}
p = remote_send.SendPipeline(ISO, addr, lambda msg, lvl='info': None, lambda *a: None, lambda *a: None,
                             lambda ok, s: res2.update(ok=ok, s=s))
p.run()
verdict('second send no-op', res2.get('ok') and 'nothing to send' in res2.get('s', ''), res2.get('s', ''))

# 5. logs
m = remote_send.connect(addr)
zpath = os.path.join(OUT, 'wonka-logs.zip')
n, size = machine_care.grab_logs(m, zpath)
names = zipfile.ZipFile(zpath).namelist()
verdict('logs pulled', 'report.txt' in names and 'jjpe/temp/game.log' in names and 'journal.txt' in names,
        '%d files, %d bytes: %s' % (n, size, names))
report = zipfile.ZipFile(zpath).read('report.txt').decode('utf-8', 'replace')
say('report head:', report[:400])

# 6. settings, audits and scores: back up, change on the machine (a game played), restore
bpath = os.path.join(OUT, 'wonka-settings.zip')
got = machine_care.backup_settings(m, bpath)
man = json.loads(zipfile.ZipFile(bpath).read('pad-machine-settings.json'))
verdict('settings backed up', got['game'] == 'Wonka' and 'perm/vf/hiscores.dat' in man['files'], str(got))
sh(m, "printf 'XXX 1\\n' > /jjpe/perm/vf/hiscores.dat; printf 'BALLS 5\\n' > /jjpe/perm/vf/settings/adjustments.cfg;"
      " echo stray > /jjpe/perm/vf/new-after-backup.dat")
changed = sh(m, 'sha1sum /jjpe/perm/vf/hiscores.dat | cut -c1-40')
game_before = sh(m, 'cat /jjpe/temp/standin-game.log | wc -l')
r = machine_care.restore_settings(m, bpath, log=lambda *a: say('  restore log:', a[0]))
time.sleep(3)
back = sh(m, 'cd /jjpe && find perm -type f ! -path "perm/lost+found/*" | sort | xargs sha1sum')
backed = {ln.split()[1]: ln.split()[0] for ln in back.splitlines()}
old = sh(m, 'tar tf /var/lib/pad/perm.pad-old.tar | sort | tr "\\n" " "')
verdict('settings restored', backed == man['files'] and backed['perm/vf/hiscores.dat'] != changed
        and 'new-after-backup' in old, '%s; old kept: %s' % (r, old[:160]))
verdict('game back after restore', int(sh(m, 'cat /jjpe/temp/standin-game.log | wc -l')) > int(game_before),
        sh(m, 'tail -n 1 /jjpe/temp/standin-game.log'))

# 7. restart the game from Machine care
before = int(sh(m, 'cat /jjpe/temp/standin-game.log | wc -l'))
said = machine_care.restart_game(m)
time.sleep(2)
verdict('restart the game', said.startswith('PAD_SEND_RESTARTED')
        and int(sh(m, 'cat /jjpe/temp/standin-game.log | wc -l')) > before, said)
m.close()

say('ALL', 'PASS' if all(ok for _n, ok in verdicts) else 'FAIL', '%d/%d' % (sum(ok for _n, ok in verdicts), len(verdicts)))
