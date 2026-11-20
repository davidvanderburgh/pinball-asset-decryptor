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
'''


class CareError(Exception):
    """Why it could not be done, in words for the user."""


def _text(answer):
    return answer[1] if isinstance(answer, tuple) else answer


def _sh(machine, script, timeout=60):
    return _text(machine.sh(script, timeout=timeout, check=False)) or ''


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


def parse_status(text):
    """``[(what, value), ...]`` for the Network tab, from :data:`STATUS`'s answer."""
    got, wifi, disks, pad = {}, {}, [], []
    for line in (text or '').splitlines():
        a = line.split(None, 1)
        if len(a) < 2:
            continue
        key, rest = a[0], a[1].strip()
        if key in ('game', 'system', 'up'):
            got[key] = rest
        elif key == 'wifi' and '=' in rest:
            k, v = rest.split('=', 1)
            wifi[k] = v
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
        if wifi.get('LINKSPEED', '').isdigit():
            said += ', link %s Mbit/s' % wifi['LINKSPEED']
        rows.append(('Wi-Fi', said))
    elif wifi:
        rows.append(('Wi-Fi', 'not connected (%s)' % wifi.get('wpa_state', 'unknown')))
    for mount, free, total in disks:
        rows.append(('Room on the card, %s' % ('games' if mount == '/games' else 'logs'),
                     '%s free of %s' % (_human(free), _human(total))))
    names = []
    for item in pad:
        if item.startswith('wifi-startup'):
            names.append('reliable Wi-Fi start-up')
        elif item.startswith('wifi-5ghz'):
            names.append('newer adapter driver (5 GHz)')
        elif item.startswith('buttons'):
            names.append('remote buttons')
        elif item.startswith('modes'):
            names.append("PAD's mode runtime")
    rows.append(('From PAD on this card', ', '.join(names) if names else 'remote access only'))
    return rows


def status(machine):
    return parse_status(_sh(machine, STATUS, 40))


# ------------------------------------------------------------------ logs
def _files(machine):
    out = []
    for line in _sh(machine, LOG_LIST, 60).splitlines():
        a = line.split(None, 1)
        if len(a) == 2 and a[0].isdigit() and a[1].startswith('/'):
            out.append((a[1], int(a[0])))
    return out


def _quote(path):
    return "'" + path.replace("'", "'\\''") + "'"


def grab_logs(machine, dest, progress=None):
    """Write the machine's logs and a status report to the zip at *dest*; ``(files, bytes)``."""
    report = _sh(machine, REPORT, 90)
    files = _files(machine)
    total = 0
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt',
                   'Logs from a pinball machine, collected by Pinball Asset Decryptor over remote access.\n\n'
                   'report.txt        the machine at that moment: versions, card space, processes, Wi-Fi\n'
                   'var/log/messages  the system log since the machine was switched on\n'
                   'var/log/dmesg     the kernel log at start-up\n'
                   'dump/mode.log     the log of PAD\'s own modes\n'
                   'dump/log/...      the connectivity logs\n\n'
                   'It names your Wi-Fi network and the machine\'s addresses. It holds no password.\n'
                   'Of a long log only the last %d MB is kept.\n' % (LOG_CAP >> 20))
        z.writestr('report.txt', report)
        total += len(report)
        for i, (path, size) in enumerate(files):
            if progress:
                progress(i, len(files), path)
            data = machine_screen._bytes_of(machine, 'tail -c %d %s 2>/dev/null' % (LOG_CAP, _quote(path)), 120)
            z.writestr(path.lstrip('/'), data)
            total += len(data)
    return len(files) + 1, total


def mode_log_tail(machine, lines=200):
    """The last *lines* lines of PAD's mode log ('' when the card has none)."""
    return _sh(machine, 'tail -n %d %s 2>/dev/null' % (max(1, min(int(lines), 2000)), MODE_LOG), 30)


# ------------------------------------------------------------------ settings, audits and scores
MANIFEST = 'pad-machine-settings.json'
TAR_NAME = 'nv.tar'


def backup_settings(machine, dest):
    """Save the machine's settings, audits and high scores (``/data/nv``) to the zip at *dest*.
    ``dict(game, files, bytes)``."""
    raw = machine_screen._bytes_of(machine, 'cd /data && tar cf - nv 2>/dev/null', 180)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            members = [m for m in t.getmembers() if m.isfile()]
            sums = {m.name: hashlib.sha1(t.extractfile(m).read()).hexdigest() for m in members}
    except tarfile.TarError as e:
        raise CareError("The machine's settings did not arrive whole (%s); try again." % e) from None
    if not sums:
        raise CareError('The machine has no saved settings yet (%s is empty).' % SETTINGS_DIR)
    games = sorted({n.split('/')[1] for n in sums if n.count('/') >= 2})
    manifest = dict(kind='pad-machine-settings', version=1, taken=time.strftime('%Y-%m-%d %H:%M:%S'),
                    games=games, game=_sh(machine, 'readlink /games/game', 20).strip().split('/')[0],
                    files=sums, bytes=sum(m.size for m in members))
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, indent=1, sort_keys=True))
        z.writestr(TAR_NAME, raw)
    return dict(game=manifest['game'], files=len(sums), bytes=manifest['bytes'])


def read_backup(path):
    """``(manifest, tar bytes)`` of a settings backup, checked against its own record."""
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read(MANIFEST).decode('utf-8'))
            raw = z.read(TAR_NAME)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise CareError('That file is not a settings backup this app made.') from None
    if not isinstance(manifest, dict) or manifest.get('kind') != 'pad-machine-settings' or not manifest.get('files'):
        raise CareError('That file is not a settings backup this app made.')
    try:
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            sums = {m.name: hashlib.sha1(t.extractfile(m).read()).hexdigest() for m in t.getmembers() if m.isfile()}
            bad = [m.name for m in t.getmembers()
                   if not (m.name == 'nv' or m.name.startswith('nv/')) or '..' in m.name.split('/')
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


def restore_settings(machine, path, log=None):
    """Put a settings backup back on *machine*: the game is held, ``/data/nv`` swapped (the one it replaces kept
    as ``/data/nv.pad-old``), every file checked, and the game started again.  ``dict(game, files)``."""
    manifest, raw = read_backup(path)
    game = _sh(machine, 'readlink /games/game', 20).strip().split('/')[0]
    if manifest.get('game') and game and manifest['game'] != game:
        raise CareError('That backup is from another game (%s); this machine runs %s. It is not put on.'
                        % (manifest['game'], game))
    say = log or (lambda *a, **k: None)
    say("Holding the machine's game while its settings are put back...", 'info')
    machine.pause_game()
    ok = False
    try:
        with machine.sftp.open('/dump/pad-settings-restore.tar', 'wb') as f:
            f.write(raw)
        out = _sh(machine, RESTORE, 180)
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
                _sh(machine, ROLL_BACK, 60)
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
