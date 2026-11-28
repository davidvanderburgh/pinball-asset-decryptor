"""Looking after a machine over remote access: its logs, its status, its settings and scores, and a restart
(PAD-1467).

David, asked what else remote access is good for: "I think grabbing logs from the machine would be very useful.
what else?" and, to the list that followed, "make all of these".

Everything here goes through a connected ``remote_send`` machine (the encrypted connection the app's key opens),
and everything but :func:`restore_settings`, :func:`restart_game` and :func:`restart_machine` only reads.

- :func:`status`: what runs on it, how long for, its Wi-Fi band and signal, the room on its card, and which PAD
  options its card carries.
- :func:`grab_logs`: the system's log, the kernel's, PAD's mode log and the connectivity logs, with a status report,
  as one zip.  No password is in it: ``wpa_supplicant.conf`` is never read.
- :func:`backup_settings` / :func:`restore_settings`: ``/data/nv``, where the game keeps its adjustments, audits and
  high scores (a card written whole loses them).  A restore holds the game, swaps the folder (the one it replaces
  is kept beside it as ``nv.pad-old``), checks every file, and starts the game again.
- :func:`mode_log_tail`: the end of PAD's mode log, for following it while a game is played.

PAD-1587: a Jersey Jack Pinball machine (an x86-64 PC running Ubuntu) gets the same, from its own places: the game's
logs in ``/jjpe/temp``, the system's (syslog, kern.log, Xorg, the systemd journal), and ``/jjpe/perm`` (where the
game keeps its adjustments, audits and high scores, in ``vf``).  ``/jjpe/perm`` is a partition of its own, so a
restore empties it and fills it again, the contents it replaces kept as ``/var/lib/pad/perm.pad-old.tar``.

A copy of the whole card was built and taken out again (David: "takes far too long"): the machine reads its card
at 3.5 to 6 MB a second, so 16 GB held the game for over an hour, and the settings backup is what is worth keeping.
"""
import hashlib
import io
import json
import re
import tarfile
import time
import zipfile

from . import machine_screen

SETTINGS_DIR = '/data/nv'
MODE_LOG = '/dump/mode.log'
LOG_CAP = 8 << 20
#: log files: taken when they are there, the last :data:`LOG_CAP` bytes of each
LOG_LIST = ('for f in /var/log/messages /var/log/dmesg /var/log/boot %s '
            '$(find /dump/log -type f 2>/dev/null); do [ -f "$f" ] && echo "$(wc -c < "$f") $f"; done' % MODE_LOG)
#: one report of the machine's state; each "== name" line starts a section
REPORT = r'''
echo "== when"; date; uptime
echo "== versions"; readlink /games/game; cat /usr/local/spike/VERSION.txt 2>/dev/null; uname -r; cat /etc/hostname 2>/dev/null
echo "== card"; df -k / /games /data /dump 2>/dev/null
echo "== memory"; cat /proc/meminfo | sed -n 1,5p
echo "== processes"; ps 2>/dev/null | grep -v " \[" | cut -c1-120
echo "== network"; ifconfig 2>/dev/null | grep -E "^[a-z]|inet addr|RX bytes"
echo "== wifi"; wpa_cli -i wlan0 status 2>/dev/null | grep -E "^(wpa_state|freq|ssid|bssid|key_mgmt|ip_address)="; wpa_cli -i wlan0 signal_poll 2>/dev/null
echo "== adapter"; for d in /sys/bus/usb/devices/*; do [ -e $d/idVendor ] && echo "$(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/product 2>/dev/null)"; done
echo "== pad"; ls -la /usr/local/padmode /usr/local/bin/pad-* /etc/wpa_supplicant/driver.wlan0 2>/dev/null; cat /etc/wpa_supplicant/driver.wlan0 2>/dev/null; cat /run/pad-buttons.state 2>/dev/null
echo "== game"; ls -la /games/ 2>/dev/null
echo "== kernel log now"; dmesg 2>/dev/null | tail -n 200
'''
STATUS = r'''
echo "game $(readlink /games/game)"
echo "system $(cat /usr/local/spike/VERSION.txt 2>/dev/null)"
read u _ < /proc/uptime; echo "up ${u%%.*}"
wpa_cli -i wlan0 status 2>/dev/null | grep -E "^(wpa_state|freq|ssid|ip_address)=" | sed "s/^/wifi /"
wpa_cli -i wlan0 signal_poll 2>/dev/null | grep -E "^(RSSI|LINKSPEED)=" | sed "s/^/wifi /"
df -k /games /dump 2>/dev/null | awk 'NR>1 && NF>=6 {print "disk " $6 " " $4 " " $2}'
[ -f /etc/wpa_supplicant/driver.wlan0 ] && echo "pad wifi-startup $(cat /etc/wpa_supplicant/driver.wlan0)"
[ -x /usr/local/bin/pad-wifi-band ] && echo "pad wifi-5ghz yes"
[ -f /usr/local/bin/pad-buttons.so ] && echo "pad buttons yes"
[ -f /usr/local/padmode/mode.so ] && echo "pad modes yes"
[ -f /usr/local/spikebt/enabled ] && echo "pad bluetooth $(cat /usr/local/spikebt/pad-release 2>/dev/null)"
[ -e /dump/spikebt/disabled ] && echo "pad bluetooth-off yes"
'''

#: PAD-1587: a JJP machine's own logs (its jjpe/gen1/scripts/dumplogs.sh collects the same for JJP's support)
JJP_LOG_LIST = ('for f in /jjpe/temp/*.log* /var/log/syslog /var/log/syslog.1 /var/log/kern.log '
                '/var/log/Xorg.0.log /var/log/dmesg; do [ -f "$f" ] && echo "$(wc -c < "$f") $f"; done')
JJP_GAME = '. /jjpe/gen1/setenv.sh >/dev/null 2>&1; echo "$GAMENAME"'
JJP_REPORT = r'''
echo "== when"; date; uptime
echo "== versions"; . /jjpe/gen1/setenv.sh >/dev/null 2>&1; echo "game $GAMENAME"; grep PRETTY_NAME /etc/os-release; uname -r; cat /etc/hostname 2>/dev/null
echo "== disk"; df -k / /jjpe/perm /jjpe/temp 2>/dev/null
echo "== memory"; sed -n 1,5p /proc/meminfo
echo "== processes"; ps -eo pid,etime,rss,args 2>/dev/null | grep -v " \[" | cut -c1-140
echo "== network"; ip -br addr 2>/dev/null; ip route 2>/dev/null | head -5
echo "== wifi"; nmcli -t -f ACTIVE,SSID,FREQ,SIGNAL,RATE dev wifi 2>/dev/null | grep "^yes"
echo "== usb"; lsusb 2>/dev/null
echo "== pad"; ls -la /usr/local/bin/dropbear /usr/local/sbin/pad-sshd /etc/systemd/system/pad-sshd.service /var/lib/pad/send 2>/dev/null
echo "== game"; ls -la /jjpe/gen1 /jjpe/perm 2>/dev/null
echo "== kernel log now"; dmesg 2>/dev/null | tail -n 200
'''
JJP_STATUS = r'''
. /jjpe/gen1/setenv.sh >/dev/null 2>&1; echo "game $GAMENAME"
echo "system $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
read u _ < /proc/uptime; echo "up ${u%%.*}"
nmcli -t -f ACTIVE,SSID,FREQ,SIGNAL dev wifi 2>/dev/null | grep "^yes:" | head -1 | sed "s/^/nm /"
d=$(ip route 2>/dev/null | awk '/^default/ {print $5; exit}'); [ -n "$d" ] && echo "net $d $(ip -4 -br addr show "$d" 2>/dev/null | awk '{print $3}')"
df -k / /jjpe/perm 2>/dev/null | awk 'NR>1 && NF>=6 {print "disk " $6 " " $4 " " $2}'
[ -L /etc/systemd/system/multi-user.target.wants/pad-sshd.service ] && echo "pad remote yes"
[ -f /var/lib/pad/send/ledger.json ] && echo "pad send yes"
'''


class CareError(Exception):
    """Why it could not be done, in words for the user."""


def _text(answer):
    return answer[1] if isinstance(answer, tuple) else answer


def _sh(machine, script, timeout=60):
    return _text(machine.sh(script, timeout=timeout, check=False)) or ''


def kind(machine):
    """PAD-1587: ``'jjp'`` for a Jersey Jack Pinball machine, ``'stern'`` otherwise (asked once a connection)."""
    got = getattr(machine, '_care_kind', None)
    if got is None:
        out = _sh(machine, '[ -d /jjpe/gen1 ] && [ -f /jjpe/gen1/setenv.sh ] && echo jjp || echo stern', 20).strip()
        got = 'jjp' if out.endswith('jjp') else 'stern'
        try:
            machine._care_kind = got
        except AttributeError:
            pass
    return got


def game_on(machine):
    """The game the machine runs."""
    if kind(machine) == 'jjp':
        return _sh(machine, JJP_GAME, 20).strip()
    return _sh(machine, 'readlink /games/game', 20).strip().split('/')[0]


def _human(n):
    n = float(n)
    for unit in ('bytes', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return ('%d %s' % (n, unit)) if unit == 'bytes' else ('%.1f %s' % (n, unit))
        n /= 1024


def _duration(seconds):
    seconds = int(seconds)
    d, h, m = seconds // 86400, seconds % 86400 // 3600, seconds % 3600 // 60
    if d:
        return '%d day%s %d h' % (d, '' if d == 1 else 's', h)
    return '%d h %d min' % (h, m) if h else '%d min' % m


#: where each disk the status names is, in words
_DISKS = {'/games': 'Room on the card, games', '/dump': 'Room on the card, logs',
          '/var/volatile/multi': 'Room on the card, games',     # a multi-boot card: where its games are mounted
          '/': 'Room on the disk, system', '/jjpe/perm': 'Room on the disk, settings'}


def parse_status(text):
    """``[(what, value), ...]`` for the Network tab, from :data:`STATUS`'s (or :data:`JJP_STATUS`'s) answer.
    A value is a sentence, or a list of short lines the page shows as bullets (what PAD put on the card)."""
    got, wifi, disks, pad = {}, {}, [], []
    for line in (text or '').splitlines():
        a = line.split(None, 1)
        if len(a) < 2:
            continue
        key, rest = a[0], a[1].strip()
        if key in ('game', 'system', 'up', 'net'):
            got[key] = rest
        elif key == 'wifi' and '=' in rest:
            k, v = rest.split('=', 1)
            wifi[k] = v
        elif key == 'nm':
            # PAD-1587: NetworkManager's active Wi-Fi (JJP): yes:SSID:FREQ:SIGNAL
            f = rest.split(':')
            if len(f) >= 4:
                wifi.update(wpa_state='COMPLETED', ssid=f[1], freq=re.sub(r'\D', '', f[2]), signal_pct=f[3])
        elif key == 'disk':
            b = rest.split()
            if len(b) == 3 and b[1].isdigit() and b[2].isdigit():
                disks.append((b[0], int(b[1]) * 1024, int(b[2]) * 1024))
        elif key == 'pad':
            pad.append(rest)
    rows = []
    game = got.get('game', '').split('/')[0]
    if game:
        rows.append(('Game on the card', game))
    if got.get('system'):
        rows.append(('System', got['system']))
    if got.get('up', '').isdigit():
        rows.append(('Switched on for', _duration(got['up'])))
    if wifi.get('wpa_state') == 'COMPLETED':
        freq = int(wifi['freq']) if wifi.get('freq', '').isdigit() else 0
        band = '5 GHz' if freq >= 5000 else '2.4 GHz' if freq else 'band not reported'
        said = '%s, %s' % (wifi.get('ssid', 'connected'), band)
        if freq:
            said += ' (%d MHz)' % freq
        if wifi.get('RSSI', '').lstrip('-').isdigit():
            said += ', signal %s dBm' % wifi['RSSI']
        elif wifi.get('signal_pct', '').isdigit():
            said += ', signal %s%%' % wifi['signal_pct']
        if wifi.get('LINKSPEED', '').isdigit():
            said += ', link %s Mbit/s' % wifi['LINKSPEED']
        rows.append(('Wi-Fi', said))
    elif wifi:
        rows.append(('Wi-Fi', 'not connected (%s)' % wifi.get('wpa_state', 'unknown')))
    if got.get('net'):
        rows.append(('Network', got['net']))
    for mount, free, total in disks:
        rows.append((_DISKS.get(mount, 'Room on ' + mount), '%s free of %s' % (_human(free), _human(total))))
    # PAD-1647 (David: "we should bullet point the features we are adding there instead of a sentence structure",
    # and "see at a glance that my bluetooth plugin is installed"): one line a feature, a list the pages bullet.
    # Remote access is always one of them: the status was read over it.
    names = ['Remote access']
    bt_off = any(item.split()[0] == 'bluetooth-off' for item in pad)
    for item in pad:
        key = item.split()[0]
        if key == 'wifi-startup':
            names.append('Reliable Wi-Fi start-up')
        elif key == 'wifi-5ghz':
            names.append('Newer Wi-Fi adapter driver (5 GHz)')
        elif key == 'buttons':
            names.append('Remote buttons')
        elif key == 'modes':
            names.append("PAD's mode runtime")
        elif key == 'send':
            names.append('Files sent from PAD')
        elif key == 'bluetooth':
            tag = item.split()[1] if len(item.split()) == 2 and re.match(r'^v[0-9.]{1,16}$', item.split()[1]) else ''
            names.append('Bluetooth headphones plugin%s%s' % (
                ' ' + tag if tag else '',
                ' (switched itself off after a game that ended badly; Check it on the machine, on the Plugins '
                'tab, switches it back on)' if bt_off else ''))
    rows.append(('From PAD on this card', names))
    return rows


def status(machine):
    return parse_status(_sh(machine, JJP_STATUS if kind(machine) == 'jjp' else STATUS, 40))


# ------------------------------------------------------------------ logs
def _files(machine):
    out = []
    for line in _sh(machine, JJP_LOG_LIST if kind(machine) == 'jjp' else LOG_LIST, 60).splitlines():
        a = line.split(None, 1)
        if len(a) == 2 and a[0].isdigit() and a[1].startswith('/'):
            out.append((a[1], int(a[0])))
    return out


def _quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


README = ('Logs from a pinball machine, collected by Pinball Asset Decryptor over remote access.\n\n'
          'report.txt        the machine at that moment: versions, card space, processes, Wi-Fi\n'
          'var/log/messages  the system log since the machine was switched on\n'
          'var/log/dmesg     the kernel log at start-up\n'
          'dump/mode.log     the log of PAD\'s own modes\n'
          'dump/log/...      the connectivity logs\n\n'
          'It names your Wi-Fi network and the machine\'s addresses. It holds no password.\n'
          'Of a long log only the last %d MB is kept.\n' % (LOG_CAP >> 20))
JJP_README = ('Logs from a Jersey Jack Pinball machine, collected by Pinball Asset Decryptor over remote access.\n\n'
              'report.txt          the machine at that moment: versions, disk space, processes, network\n'
              'jjpe/temp/*.log     the game\'s own logs (game.log is what the game and its start-up loop print)\n'
              'var/log/...         the system log, the kernel log and the display server\'s log\n'
              'journal.txt         the systemd journal since the machine was switched on\n\n'
              'It names your network and the machine\'s addresses. It holds no password.\n'
              'Of a long log only the last %d MB is kept.\n' % (LOG_CAP >> 20))


def grab_logs(machine, dest, progress=None):
    """Write the machine's logs and a status report to the zip at *dest*; ``(files, bytes)``."""
    jjp = kind(machine) == 'jjp'
    report = _sh(machine, JJP_REPORT if jjp else REPORT, 90)
    files = _files(machine)
    steps = len(files) + (1 if jjp else 0)
    total = 0
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', JJP_README if jjp else README)
        z.writestr('report.txt', report)
        total += len(report)
        for i, (path, size) in enumerate(files):
            if progress:
                progress(i, steps, path)
            data = machine_screen._bytes_of(machine, 'tail -c %d %s 2>/dev/null' % (LOG_CAP, _quote(path)), 120)
            z.writestr(path.lstrip('/'), data)
            total += len(data)
        if jjp:
            # the systemd journal: what the game's service, the display and the network said since start-up
            if progress:
                progress(len(files), steps, 'journal')
            journal = machine_screen._bytes_of(
                machine, 'journalctl -b -o short-precise --no-pager 2>/dev/null | tail -c %d' % LOG_CAP, 180)
            z.writestr('journal.txt', journal)
            total += len(journal)
    return steps + 1, total


def mode_log_tail(machine, lines=200):
    """The last *lines* lines of PAD's mode log ('' when the card has none)."""
    return _sh(machine, 'tail -n %d %s 2>/dev/null' % (max(1, min(int(lines), 2000)), MODE_LOG), 30)


# ------------------------------------------------------------------ settings, audits and scores
MANIFEST = 'pad-machine-settings.json'
TAR_NAME = 'nv.tar'
#: PAD-1587: a JJP machine's settings partition, and what of it a backup holds (all but lost+found, the file
#: system's own)
JJP_DIR = '/jjpe/perm'
JJP_TAR = 'perm.tar'
JJP_BACKUP = 'cd /jjpe && tar cf - --exclude=perm/lost+found perm 2>/dev/null'
JJP_UPLOAD = '/var/lib/pad/settings-restore.tar'
JJP_OLD = '/var/lib/pad/perm.pad-old.tar'


def backup_settings(machine, dest):
    """Save the machine's settings, audits and high scores (``/data/nv``; ``/jjpe/perm`` on JJP) to the zip at
    *dest*.  ``dict(game, files, bytes)``."""
    jjp = kind(machine) == 'jjp'
    raw = machine_screen._bytes_of(machine, JJP_BACKUP if jjp else 'cd /data && tar cf - nv 2>/dev/null', 180)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            members = [m for m in t.getmembers() if m.isfile()]
            sums = {m.name: hashlib.sha1(t.extractfile(m).read()).hexdigest() for m in members}
    except tarfile.TarError as e:
        raise CareError("The machine's settings did not arrive whole (%s); try again." % e) from None
    if not sums:
        raise CareError('The machine has no saved settings yet (%s is empty).' % (JJP_DIR if jjp else SETTINGS_DIR))
    games = sorted({n.split('/')[1] for n in sums if n.count('/') >= 2})
    manifest = dict(kind='pad-machine-settings', version=1, taken=time.strftime('%Y-%m-%d %H:%M:%S'),
                    games=games, game=game_on(machine), files=sums, bytes=sum(m.size for m in members))
    if jjp:
        manifest.update(maker='jjp', root='perm')
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, indent=1, sort_keys=True))
        z.writestr(JJP_TAR if jjp else TAR_NAME, raw)
    return dict(game=manifest['game'], files=len(sums), bytes=manifest['bytes'])


def read_backup(path):
    """``(manifest, tar bytes)`` of a settings backup, checked against its own record."""
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read(MANIFEST).decode('utf-8'))
            jjp = isinstance(manifest, dict) and manifest.get('root') == 'perm'
            raw = z.read(JJP_TAR if jjp else TAR_NAME)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise CareError('That file is not a settings backup this app made.') from None
    if not isinstance(manifest, dict) or manifest.get('kind') != 'pad-machine-settings' or not manifest.get('files'):
        raise CareError('That file is not a settings backup this app made.')
    top = 'perm' if jjp else 'nv'
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            sums = {m.name: hashlib.sha1(t.extractfile(m).read()).hexdigest() for m in t.getmembers() if m.isfile()}
            bad = [m.name for m in t.getmembers()
                   if not (m.name == top or m.name.startswith(top + '/')) or '..' in m.name.split('/')
                   or not (m.isfile() or m.isdir())]
    except tarfile.TarError:
        raise CareError('The settings backup is damaged.') from None
    if bad or sums != manifest['files']:
        raise CareError('The settings backup is damaged or was changed: it is not put on the machine.')
    return manifest, raw


RESTORE = r'''
set -e
cd /data
rm -rf nv.pad-new && mkdir nv.pad-new
tar xf /dump/pad-settings-restore.tar -C nv.pad-new
[ -d nv.pad-new/nv ]
rm -rf nv.pad-old
if [ -d nv ]; then mv nv nv.pad-old; fi
mv nv.pad-new/nv nv && rmdir nv.pad-new
rm -f /dump/pad-settings-restore.tar
sync
cd /data && find nv -type f | sort | while read f; do echo "$(sha1sum "$f" | cut -d" " -f1) $f"; done
'''
ROLL_BACK = 'cd /data && [ -d nv.pad-old ] && { rm -rf nv; mv nv.pad-old nv; sync; }; rm -rf /data/nv.pad-new'
#: PAD-1587: /jjpe/perm is a partition (its folder can't be renamed away): what is on it goes into a tar first, it
#: is emptied and filled from the backup; the rollback empties it and unpacks that tar
JJP_RESTORE = r'''
set -e
[ -d /jjpe/perm ]
rm -rf /var/lib/pad/settings-new && mkdir -p /var/lib/pad/settings-new
tar xf @UP@ -C /var/lib/pad/settings-new
[ -d /var/lib/pad/settings-new/perm ]
cd /jjpe && tar cf @OLD@.tmp --exclude=perm/lost+found perm && mv -f @OLD@.tmp @OLD@
find /jjpe/perm -mindepth 1 -maxdepth 1 ! -name lost+found -exec rm -rf {} +
cp -a /var/lib/pad/settings-new/perm/. /jjpe/perm/
rm -rf /var/lib/pad/settings-new @UP@
sync
cd /jjpe && find perm -type f ! -path "perm/lost+found/*" | sort | while read f; do echo "$(sha1sum "$f" | cut -d" " -f1) $f"; done
'''.replace('@UP@', JJP_UPLOAD).replace('@OLD@', JJP_OLD)
JJP_ROLL_BACK = ('[ -f %s ] && { find /jjpe/perm -mindepth 1 -maxdepth 1 ! -name lost+found -exec rm -rf {} +; '
                 'cd /jjpe && tar xf %s; sync; }; rm -rf /var/lib/pad/settings-new %s'
                 % (JJP_OLD, JJP_OLD, JJP_UPLOAD))


def restore_settings(machine, path, log=None):
    """Put a settings backup back on *machine*: the game is held, ``/data/nv`` swapped (the one it replaces kept
    as ``/data/nv.pad-old``; on JJP ``/jjpe/perm`` refilled, its old contents kept as
    ``/var/lib/pad/perm.pad-old.tar``), every file checked, and the game started again.  ``dict(game, files)``."""
    manifest, raw = read_backup(path)
    jjp = kind(machine) == 'jjp'
    if jjp != (manifest.get('root') == 'perm'):
        raise CareError('That backup is from a %s machine and this one is a %s machine. It is not put on.'
                        % (('Stern', 'Jersey Jack Pinball') if jjp else ('Jersey Jack Pinball', 'Stern')))
    game = game_on(machine)
    if manifest.get('game') and game and manifest['game'] != game:
        raise CareError('That backup is from another game (%s); this machine runs %s. It is not put on.'
                        % (manifest['game'], game))
    say = log or (lambda *a, **k: None)
    say("Holding the machine's game while its settings are put back...", 'info')
    machine.pause_game()
    ok = False
    try:
        if jjp:
            _sh(machine, 'mkdir -p /var/lib/pad', 20)
        with machine.sftp.open(JJP_UPLOAD if jjp else '/dump/pad-settings-restore.tar', 'wb') as f:
            f.write(raw)
        out = _sh(machine, JJP_RESTORE if jjp else RESTORE, 180)
        got = {}
        for line in out.splitlines():
            a = line.split(None, 1)
            if len(a) == 2 and len(a[0]) == 40:
                got[a[1]] = a[0]
        if got != manifest['files']:
            raise CareError("The settings did not read back from the machine as saved; the machine's own were put "
                            'back.')
        ok = True
    finally:
        if not ok:
            try:
                _sh(machine, JJP_ROLL_BACK if jjp else ROLL_BACK, 60)
            except Exception:                               # noqa: BLE001 - the first failure is the one to report
                pass
        machine.resume_game()
    return dict(game=game, files=len(manifest['files']))


def restart_game(machine):
    return machine.restart_game()


def restart_machine(machine):
    machine.reboot()


_SAFE = re.compile(r'[^A-Za-z0-9_.-]+')


def file_stem(game, what):
    """A file name for something saved from a machine: ``godzilla_le-logs-20261120-1432``."""
    return '%s-%s-%s' % (_SAFE.sub('_', game or 'machine').strip('_') or 'machine', what, time.strftime('%Y%m%d-%H%M'))
