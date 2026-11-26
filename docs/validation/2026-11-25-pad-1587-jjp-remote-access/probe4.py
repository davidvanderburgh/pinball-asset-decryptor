import sys
import time
sys.path.insert(0, '/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1587')
from pinball_decryptor.core import pad_ssh_key
pad_ssh_key.KEY_DIR = '/tmp/pad1587-client/remote_access'
from pinball_decryptor.core import remote_send
m = remote_send.connect('192.168.77.50')
FN = remote_send.PIDS_FN
LIVE = FN + ('for p in $(pids_named game); do read -r st < /proc/$p/stat; case "${st##*) }" in Z*) ;; *) echo $p;; esac;'
             ' done; for p in $(pids_named rungame.sh); do cut -d" " -f3 /proc/$p/stat; done')
bad = 0
for delay in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0, 1.1):
    m.sh(FN + 'kill -9 $(pids_named game)', check=False)
    time.sleep(delay)
    m.pause_game()
    out = m.sh(LIVE, check=False)[1].split()
    loop_state = out[-1] if out else '?'
    games = out[:-1]
    r = m.resume_game()
    time.sleep(2)
    after = m.sh(LIVE, check=False)[1].split()
    ok = not games and loop_state == 'T' and len(after) == 2 and after[-1] == 'S'
    bad += not ok
    print('delay %.2f held: games=%s loop=%s | after: %s %s  %s' % (delay, games, loop_state, after, r,
                                                                    'OK' if ok else 'BAD'), flush=True)
print('RACE', 'PASS' if not bad else 'FAIL %d' % bad)
m.close()
