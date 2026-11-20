"""PAD-1467: looking after a machine over remote access (core/machine_care.py) and the Network tab's Machine care
card: status, logs, settings and scores, restart, the mode log, the whole card, and recording the live view."""
import io
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from pinball_decryptor.core import machine_care as C, machine_screen as MS
from tests.webui_harness import web_app

STATUS = '''game godzilla_le/game
system SPIKE v2.7.0
up 4000
wifi wpa_state=COMPLETED
wifi freq=5200
wifi ssid=HomeNet
wifi ip_address=192.168.4.77
wifi RSSI=-48
wifi LINKSPEED=867
disk /games 2831155 13841000
disk /dump 501657 519782
pad wifi-startup nl80211,wext
pad wifi-5ghz yes
pad buttons yes
'''


def _tar(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


SETTINGS = {'nv/godzilla_le/NVM/00000031': b'scores' * 50, 'nv/godzilla_le/NVRAM/00000014': b'adjust'}


class Machine:
    """A stand-in for a connected machine: answers by what the script asks for, and records what it was told."""

    def __init__(self):
        self.ran, self.files, self.paused, self.resumed, self.restore_reads = [], {}, 0, 0, None
        self.sftp, self.host = self, '127.0.0.1'

    def sh(self, script, timeout=60, check=True):
        self.ran.append(script)
        if 'wifi-startup' in script:
            return 0, STATUS
        if script.startswith('for f in /var/log/messages'):
            return 0, '120 /var/log/messages\n40 /dump/mode.log\n'
        if '== when' in script:
            return 0, '== when\nnow\n== wifi\nssid=HomeNet\n'
        if 'tail -n' in script:
            return 0, 'line one\nline two\n'
        if script.startswith('readlink /games/game'):
            return 0, 'godzilla_le/game\n'
        if 'pad-settings-restore.tar' in script:
            import hashlib
            sums = self.restore_reads or {n: hashlib.sha1(d).hexdigest() for n, d in SETTINGS.items()}
            return 0, ''.join('%s %s\n' % (v, k) for k, v in sorted(sums.items()))
        if script.startswith('cat /sys/block/mmcblk0/size'):
            return 0, '0\n'
        return 0, ''

    def raw(self, command):
        self.ran.append(command)
        if command.startswith('cd /data && tar'):
            return _tar(SETTINGS)
        return b'log bytes of ' + command.split()[-2].strip("'").encode()

    def open(self, path, mode):                              # sftp.open
        m, buf = self, io.BytesIO()

        class F:
            def __enter__(self_):
                return buf

            def __exit__(self_, *a):
                m.files[path] = buf.getvalue()
        return F()

    def pause_game(self):
        self.paused += 1

    def resume_game(self, text=None):
        self.resumed += 1
        return 'PAD_SEND_RESTARTED'

    def restart_game(self):
        return 'PAD_SEND_RESTARTED'

    def reboot(self):
        self.ran.append('REBOOT')

    def close(self):
        pass


def test_status_reads_as_plain_rows():
    rows = dict(C.status(Machine()))
    assert rows['Game on the card'] == 'godzilla_le' and rows['System'] == 'SPIKE v2.7.0'
    assert rows['Switched on for'] == '1 h 6 min'
    assert rows['Wi-Fi'] == 'HomeNet, 5 GHz (5200 MHz), signal -48 dBm, link 867 Mbit/s'
    assert rows['Room on the card, games'].startswith('2.7 GB free of 13.2 GB')
    assert rows['From PAD on this card'] == 'reliable Wi-Fi start-up, newer adapter driver (5 GHz), remote buttons'
    assert dict(C.parse_status('game x/game\nwifi wpa_state=SCANNING\n'))['Wi-Fi'] == 'not connected (SCANNING)'
    assert dict(C.parse_status('wifi wpa_state=COMPLETED\nwifi freq=2412\nwifi ssid=H\n'))['Wi-Fi'].startswith('H, 2.4 GHz')
    assert 'psk' not in C.STATUS and 'wpa_supplicant.conf' not in C.STATUS + C.REPORT + C.LOG_LIST   # never the password


def test_logs_are_one_zip_with_a_report_and_no_password(tmp_path):
    m = Machine()
    dest = tmp_path / 'logs.zip'
    files, size = C.grab_logs(m, str(dest))
    with zipfile.ZipFile(dest) as z:
        names = set(z.namelist())
        assert names == {'README.txt', 'report.txt', 'var/log/messages', 'dump/mode.log'} and files == 3
        assert b'== when' in z.read('report.txt') and b'holds no password' in z.read('README.txt')
        assert z.read('dump/mode.log').startswith(b'log bytes of')
    assert any("tail -c %d '/dump/mode.log'" % C.LOG_CAP in r for r in m.ran)                 # a long log is capped
    assert C.mode_log_tail(m, 99999) == 'line one\nline two\n' and 'tail -n 2000' in m.ran[-1]
    assert C.file_stem('Godzilla LE', 'logs').startswith('Godzilla_LE-logs-20')


def test_settings_backup_and_restore_check_every_file(tmp_path):
    m = Machine()
    dest = tmp_path / 'settings.zip'
    res = C.backup_settings(m, str(dest))
    assert res == dict(game='godzilla_le', files=2, bytes=sum(len(d) for d in SETTINGS.values()))
    manifest, raw = C.read_backup(str(dest))
    assert manifest['games'] == ['godzilla_le'] and set(manifest['files']) == set(SETTINGS) and raw == _tar(SETTINGS)

    assert C.restore_settings(m, str(dest)) == dict(game='godzilla_le', files=2)
    assert m.paused == 1 and m.resumed == 1 and m.files['/dump/pad-settings-restore.tar'] == raw
    restore = next(r for r in m.ran if 'pad-settings-restore.tar' in r)
    assert 'mv nv nv.pad-old' in restore and 'sha1sum' in restore            # what it replaces is kept, once

    # a file that does not read back as saved: the machine's own settings go back, and the game still starts
    m2 = Machine()
    m2.restore_reads = {n: '0' * 40 for n in SETTINGS}
    with pytest.raises(C.CareError, match="machine's own were put back"):
        C.restore_settings(m2, str(dest))
    assert m2.resumed == 1 and any(r == C.ROLL_BACK for r in m2.ran)

    # a backup from another game is refused before anything is touched
    class Other(Machine):
        def sh(self, script, timeout=60, check=True):
            if script.startswith('readlink /games/game'):
                return 0, 'deadpool_le/game\n'
            return super().sh(script, timeout, check)
    m3 = Other()
    with pytest.raises(C.CareError, match='another game'):
        C.restore_settings(m3, str(dest))
    assert m3.paused == 0

    # a backup that was changed, or is not one, is refused
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(dest) as z, zipfile.ZipFile(bad, 'w') as out:
        out.writestr(C.MANIFEST, z.read(C.MANIFEST))
        out.writestr(C.TAR_NAME, _tar(dict(SETTINGS, **{'nv/godzilla_le/NVRAM/00000014': b'edited'})))
    with pytest.raises(C.CareError, match='damaged or was changed'):
        C.read_backup(str(bad))
    with zipfile.ZipFile(bad, 'w') as out:
        out.writestr(C.MANIFEST, '{"kind": "pad-machine-settings", "files": {"etc/passwd": "x"}}')
        out.writestr(C.TAR_NAME, _tar({'etc/passwd': b'x'}))
    with pytest.raises(C.CareError):
        C.read_backup(str(bad))                                              # nothing outside nv/ ever goes on
    (tmp_path / 'not.zip').write_bytes(b'hello')
    with pytest.raises(C.CareError, match='not a settings backup'):
        C.read_backup(str(tmp_path / 'not.zip'))


def test_card_backup_needs_a_card_it_can_measure(tmp_path):
    with pytest.raises(C.CareError, match='could not be measured'):
        C.backup_card(Machine(), str(tmp_path / 'card.raw'))
    assert not set(C.CARD_PORTS) & set(MS.LIVE_PORTS)
    assert 'if=/dev/mmcblk0' in Path(C.__file__).read_text(encoding='utf-8') and ' of=/dev' not in Path(C.__file__).read_text(encoding='utf-8')


def test_a_recording_is_saved_as_a_video_or_a_gif(tmp_path):
    from PIL import Image
    frames = []
    for shade in (10, 120, 240):
        out = io.BytesIO()
        Image.new('RGB', (64, 32), (shade, 0, 0)).save(out, 'JPEG')
        frames.append(out.getvalue())
    gif = tmp_path / 'screen.gif'
    assert MS.save_recording(frames, 5, str(gif)) == 'animated GIF'
    im = Image.open(gif)
    assert im.n_frames == 3 and im.size == (32, 16)
    with pytest.raises(MS.ScreenError):
        MS.save_recording([], 5, str(gif))


def _wait(w, done):
    for _ in range(300):
        w.drain()
        if done(w.state('network')):
            return
        time.sleep(0.02)
    raise AssertionError('never settled: %r' % {k: v for k, v in w.state('network').items() if k.startswith('care')})


def test_network_tab_machine_care(tmp_path, monkeypatch):
    from pinball_decryptor.core import pad_ssh_key, remote_send, ssh_card
    from pinball_decryptor.webui import compat
    with web_app(tmp_path, mfr='stern') as w:
        project = tmp_path / 'project'; project.mkdir()
        image = tmp_path / 'source.raw'; image.write_bytes(b'card')
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=True, reason='', platform='stern-spike2',
                                                                        enabled=False, public_keys=''))
        monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
        w.run(w.window.write_assets_var.set, str(project))
        w.run(w.window.write_upd_var.set, str(image))
        svc = w.window.service('network')
        w.run(svc.on_show)
        w.call('network.set_address', '192.168.1.40')
        made = []

        def connect(address):
            made.append(Machine())
            return made[-1]
        monkeypatch.setattr(remote_send, 'connect', connect)
        idle = lambda s: not s.get('care_busy')                              # noqa: E731

        assert w.call('network.machine_status')
        _wait(w, idle)
        st = w.state('network')
        assert ['Game on the card', 'godzilla_le'] in st['care_status'] and st['care_kind'] == 'ok'

        logs = tmp_path / 'logs.zip'
        monkeypatch.setattr(w.window, 'ask_save', lambda *a, **k: str(logs))
        assert w.call('network.grab_logs')
        _wait(w, idle)
        assert zipfile.is_zipfile(logs) and 'Saved 3 files' in w.state('network')['care_note']

        saved = tmp_path / 'settings.zip'
        monkeypatch.setattr(w.window, 'ask_save', lambda *a, **k: str(saved))
        assert w.call('network.backup_settings')
        _wait(w, idle)
        assert 'settings, audits and high scores' in w.state('network')['care_note'] and saved.exists()

        asked = []
        monkeypatch.setattr(w.window, 'ask_open', lambda *a, **k: str(saved))
        monkeypatch.setattr(compat.messagebox, 'askyesno', lambda title, text, **k: asked.append(title) or False)
        assert w.call('network.restore_settings') is False and asked == ['Restore settings']   # No: nothing happens
        assert w.call('network.restart_machine') is False
        monkeypatch.setattr(compat.messagebox, 'askyesno', lambda *a, **k: True)
        assert w.call('network.restore_settings')
        _wait(w, idle)
        assert 'Put back 2 settings files' in w.state('network')['care_note'] and made[-1].paused == 1
        assert w.call('network.restart_game')
        _wait(w, idle)
        assert w.state('network')['care_note'] == 'The game restarted.'
        assert w.call('network.restart_machine')
        _wait(w, idle)
        assert 'REBOOT' in made[-1].ran and 'about a minute' in w.state('network')['care_note']

        assert w.call('network.follow_log', True)
        _wait(w, lambda s: 'line one' in (s.get('care_log') or ''))
        assert w.call('network.follow_log', False) and not w.state('network')['care_following']

        def refused(address):
            raise remote_send.SendError("192.168.1.40 didn't let this computer in.")
        monkeypatch.setattr(remote_send, 'connect', refused)
        assert w.call('network.machine_status')
        _wait(w, idle)
        assert w.state('network')['care_kind'] == 'err' and "didn't let" in w.state('network')['care_note']
    js = (Path(C.__file__).parents[1] / 'webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    for call in ('machine_status', 'grab_logs', 'follow_log', 'backup_settings', 'restore_settings', 'restart_game',
                 'restart_machine', 'backup_card', 'record_live'):
        assert 'network.%s' % call in js, call
