"""PAD-1587: remote access, Send to machine, logs, status and the settings backup on Jersey Jack Pinball machines.

The machine itself is proven on the stand-in (docs/validation/2026-11-25-pad-1587-jjp-remote-access.md); these
pin the parts that decide what goes where: the payload and the debugfs script that put remote access on a JJP
root, the Send record beside a build, and what a Send does on a machine (in memory here)."""
import hashlib
import io
import json
import os
import posixpath
import re
import stat
import tarfile
import zipfile

import pytest

from pinball_decryptor.core import machine_care as C
from pinball_decryptor.core import machine_scan, pad_ssh_key, remote_send, remote_send_jjp as J, ssh_card, ssh_jjp


# ------------------------------------------------------------------ the payload
def test_x86_64_payload_is_the_pinned_build():
    for name, digest in ssh_jjp.X86_64_HASHES.items():
        data = (ssh_jjp.RESOURCES / 'x86_64' / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert data[:4] == b'\x7fELF' and data[4] == 2 and data[18] == 0x3e     # 64-bit, x86-64


def test_start_script_keeps_host_keys_on_the_root():
    text = ssh_jjp.start_script().decode()
    assert 'KEYDIR=/var/lib/pad/dropbear' in text and '/data/' not in text
    assert '\r' not in text and text.startswith('#!/bin/sh')
    assert 'PIDFILE=/var/run/pad-sshd.pid' in text             # the unit's PIDFile (/var/run is /run)
    assert 'PIDFile=/run/pad-sshd.pid' in ssh_jjp.UNIT_TEXT
    assert 'ExecStart=%s start' % ssh_jjp.FILES['sshd'] in ssh_jjp.UNIT_TEXT


def test_debugfs_script_on_and_off():
    cfg = {'enabled': True, 'public_keys': 'ssh-ed25519 AAAA test'}
    staged = {n: '/tmp/s/%s' % n for n in ssh_jjp.FILES}
    on = ssh_jjp.debugfs_commands(cfg, staged)
    assert on[-1] == 'symlink %s %s' % (ssh_jjp.HOOK, ssh_jjp.UNIT)
    for name, dest in ssh_jjp.FILES.items():
        assert 'write /tmp/s/%s %s' % (name, dest) in on
        assert 'set_inode_field %s mode 0%o' % (dest, stat.S_IFREG | ssh_jjp.mode_of(name)) in on
    assert 'set_inode_field /root/.ssh mode 040700' in on
    assert ssh_jjp.mode_of('authorized_keys') == 0o600 and ssh_jjp.mode_of('unit') == 0o644
    off = ssh_jjp.debugfs_commands({'enabled': False}, {})
    assert off == ['rm %s' % ssh_jjp.HOOK] + ['rm %s' % d for d in ssh_jjp.FILES.values()]
    assert ssh_jjp.expected(cfg)[ssh_jjp.FILES['authorized_keys']][1] == hashlib.sha256(
        b'ssh-ed25519 AAAA test').hexdigest()


def test_offered_on_jjp_and_stern_only():
    class M:
        def __init__(self, key, era=None):
            self.key = key
            if era:
                self._era = era
    assert ssh_card.offered(M('jjp'))
    assert ssh_card.offered(M('stern', 'spike2')) and ssh_card.offered(M('stern', 'spike3'))
    for key in ('spooky', 'bof', 'dp', 'pb', 'ap'):
        assert not ssh_card.offered(M(key))
    assert 'jjp' in ssh_card.QUALIFIED_PLATFORMS and ssh_card.layout('jjp')['arch'] == 'x86_64'


def _iso(tmp_path, name='Wonka-v03.03-mod.iso'):
    p = tmp_path / name
    data = bytearray(0x8010)
    data[0x8001:0x8006] = b'CD001'
    p.write_bytes(bytes(data))
    return str(p)


def test_an_iso_is_inspected_as_jjp(tmp_path):
    iso = _iso(tmp_path)
    info = ssh_card.inspect_image(iso)
    assert info['platform'] == 'jjp' and info['supported'] and not info['enabled']


# ------------------------------------------------------------------ the Send record
PIC = '/jjpe/gen1/miscfiles/graphics/JJP_logo_message.png'
GAME = '/jjpe/gen1/Wonka/game'


def _build(tmp_path, files, keys=None, name='Wonka-v03.03-mod.iso'):
    """A JJP build with its Send record: *files* ``{path: bytes}``."""
    iso = _iso(tmp_path, name)
    d = J.set_dir(iso)
    os.makedirs(d, exist_ok=True)
    entries = []
    for i, (path, data) in enumerate(sorted(files.items())):
        if isinstance(data, tuple):                     # ('link', target)
            entries.append(dict(path=path, link=data[1]))
            continue
        (tmp_path / (name + J.SET_SUFFIX) / ('f%d' % i)).write_bytes(data)
        entries.append(J.manifest_entry(path, 'f%d' % i, data, 0o644, 0, 0))
    keys = pad_ssh_key.public_line() if keys is None else keys
    J.write_set(iso, dict(game='Wonka', source='Wonka-v03.03.iso', files=entries,
                          identity={GAME: hashlib.sha1(b'game v3.03').hexdigest()},
                          remote=dict(enabled=bool(keys), public_keys=keys)))
    return iso


def test_record_is_tied_to_its_iso(tmp_path):
    iso = _build(tmp_path, {PIC: b'new picture'})
    assert J.read_set(iso)['game'] == 'Wonka'
    assert ssh_card.inspect_image(iso)['enabled']
    with open(iso, 'ab') as f:
        f.write(b'built again')
    with pytest.raises(J.SendError, match='not the build'):
        J.read_set(iso)


def test_record_moves_with_the_iso(tmp_path):
    from pinball_decryptor.plugins.jjp.remote_access import move_record
    iso = _build(tmp_path, {PIC: b'new picture'})
    target = str(tmp_path / 'out' / 'chosen.iso')
    os.makedirs(os.path.dirname(target))
    os.replace(iso, target)
    move_record(iso, target)
    assert not os.path.exists(J.set_dir(iso)) and J.read_set(target)['files'][0]['path'] == PIC


# ------------------------------------------------------------------ a Send, on a machine in memory
class Jjp:
    """A JJP machine in memory: its files, a game that restarts, and the scripts a Send runs."""

    def __init__(self, files=None, game='Wonka'):
        self.fs = {GAME: b'game v3.03', '/jjpe/gen1/setenv.sh': b'export GAMENAME=%s\n' % game.encode(),
                   PIC: b'stock picture'}
        self.fs.update(files or {})
        self.links, self.game, self.sftp, self.restarts, self.held = {}, game, self, 0, False
        self.loop_stops = True

    # the connection's own steps
    def sh(self, script, stdin=b'', timeout=600, check=True):
        if script == J.GAME_SH:
            return 0, self.game + '\n'
        if script.startswith('[ -d /jjpe/gen1 ]'):
            return 0, ''
        if script == J.HELD_SCRIPT:
            stopped = self.held and self.loop_stops
            return 0, 'LOOP %s\n' % ('T' if stopped else 'S') + ('' if stopped else 'GAME 4242\n')
        if script.startswith('mkdir -p') or script == 'sync':
            return 0, ''
        m = re.match(r"mv -f (\S+) (\S+) && sync", script)
        if m:
            self.fs[m.group(2)] = self.fs.pop(m.group(1))
            return 0, ''
        if 'echo saved' in script:
            p, o = re.search(r"p=(\S+); o=(\S+)", script).groups()
            if p in self.fs:
                self.fs[o] = self.fs[p]
                return 0, 'saved\n'
            return 0, 'absent\n'
        if 'PAD_NO_ORIGINAL' in script:
            p, o, how = re.search(r"p=(\S+); o=(\S+); how=(\S+)", script).groups()
            if how == 'saved':
                self.fs[p] = self.fs.pop(o)
            else:
                self.fs.pop(p, None)
            return 0, ''
        raise AssertionError('unexpected script: %r' % script[:80])

    def open(self, path, mode='rb'):
        fs = self.fs

        class F(io.BytesIO):
            def __exit__(s, *a):
                if 'w' in mode:
                    fs[path] = s.getvalue()
                return False
        if 'r' in mode:
            if path not in fs:
                raise OSError(path)
            return F(fs[path])
        return F()

    def file_sha1s(self, paths):
        return {p: ('file', hashlib.sha1(self.fs[p]).hexdigest()) for p in paths if p in self.fs}

    def state(self, paths):
        return {p: ('link', self.links[p]) if p in self.links else None for p in paths}

    def free(self, mount):
        return 10 << 30

    def upload(self, path, fileobj, size, mode, uid, gid, callback=None):
        self.fs[path] = fileobj.read()
        if callback:
            callback(size, size)

    def commit(self, renames, links, deletes):
        assert self.held, 'files changed while the game ran'
        for tmp, final in renames:
            self.fs[final] = self.fs.pop(tmp)
        for path, target, _u, _g in links:
            self.links[path] = target

    def remove(self, paths):
        for p in paths:
            self.fs.pop(p, None)

    def sync(self):
        pass

    def pause_game(self):
        self.held = True

    def resume_game(self, text=None):
        self.held = False
        self.restarts += 1
        return 'PAD_SEND_RESTARTED 4242'

    def screen_progress(self, *a):
        pass

    def screen_changing(self):
        pass

    def screen_stopped(self, changed):
        self.held = False


def _ledger(m):
    return json.loads(m.fs[J.LEDGER])


def test_send_puts_the_changes_keeps_the_original_and_restarts(tmp_path):
    iso = _build(tmp_path, {PIC: b'new picture', ssh_jjp.HOOK: ('link', ssh_jjp.UNIT)})
    m = Jjp()
    said = J.send_build(iso, m)
    assert m.fs[PIC] == b'new picture' and m.links[ssh_jjp.HOOK] == ssh_jjp.UNIT
    assert m.fs[J.ORIG + PIC] == b'stock picture' and m.restarts == 1 and not m.held
    assert _ledger(m)['paths'] == {PIC: 'saved', ssh_jjp.HOOK: 'absent'} and 'sending' not in _ledger(m)
    assert said.startswith('Sent 2 changed files') and 'the game restarted on them' in said
    assert not any(p.endswith(J.TMP_TAG) for p in m.fs)
    # the same build again: nothing goes, the game is not touched
    assert J.send_build(iso, m) == 'The machine already has this build: nothing to send.' and m.restarts == 1


def test_a_later_build_puts_back_what_it_no_longer_changes(tmp_path):
    first = _build(tmp_path, {PIC: b'new picture', '/jjpe/gen1/Wonka/extra.dat': b'added'}, name='a.iso')
    m = Jjp()
    J.send_build(first, m)
    second = _build(tmp_path, {'/jjpe/gen1/Wonka/other.dat': b'other'}, name='b.iso')
    said = J.send_build(second, m)
    assert m.fs[PIC] == b'stock picture' and '/jjpe/gen1/Wonka/extra.dat' not in m.fs
    assert m.fs['/jjpe/gen1/Wonka/other.dat'] == b'other'
    assert _ledger(m)['paths'] == {'/jjpe/gen1/Wonka/other.dat': 'absent'} and J.ORIG + PIC not in m.fs
    assert '2 put back as the install has them' in said


def test_nothing_changes_when_the_game_is_not_held(tmp_path):
    iso = _build(tmp_path, {PIC: b'new picture'})
    m = Jjp()
    m.loop_stops = False
    with pytest.raises(J.SendError, match='could not be held'):
        J.send_build(iso, m)
    assert m.fs[PIC] == b'stock picture' and J.LEDGER not in m.fs and not m.held


def test_refuses_another_game_another_version_and_remote_access_off(tmp_path):
    iso = _build(tmp_path, {PIC: b'new picture'})
    with pytest.raises(remote_send.NotThisCard, match='runs Pirates'):
        J.send_build(iso, Jjp(game='Pirates'))
    with pytest.raises(remote_send.NotThisCard, match='another version of Wonka'):
        J.send_build(iso, Jjp({GAME: b'game v3.02'}))
    off = _build(tmp_path, {PIC: b'new picture'}, keys='', name='off.iso')
    with pytest.raises(J.SendError, match='remote access off'):
        J.send_build(off, Jjp())
    m = Jjp()
    J.send_build(iso, m)
    assert m.fs[PIC] == b'new picture'


def test_send_image_hands_a_jjp_build_to_the_jjp_send(tmp_path, monkeypatch):
    iso = _build(tmp_path, {PIC: b'new picture'})
    seen = []
    monkeypatch.setattr(J, 'send_build', lambda *a, **k: seen.append(a[0]) or 'ok')
    assert remote_send.send_image(iso, object()) == 'ok' and seen == [iso]


def test_a_jjp_machine_names_its_game():
    assert machine_scan.game_of('/jjpe/Wonka/game\nWonka-standin\n') == 'Wonka'
    assert '/jjpe/gen1/setenv.sh' in remote_send.GAME_LINK and remote_send.GAME_LINK.startswith('readlink /games/game')
    # the loop a Send holds on JJP, and the message screen it uses there
    assert 'pids_named rungame.sh' in remote_send.PAUSE_SCRIPT and '/jjpe/gen1/scripts/jimg' in remote_send.SCREEN_FNS


# ------------------------------------------------------------------ logs, status, settings on JJP
JJP_STATUS = '''game Wonka
system Ubuntu 21.10
up 7300
nm yes:HomeNet:5180 MHz:78
net enp2s0 192.168.4.80/24
disk / 9000000 16000000
disk /jjpe/perm 100000 120000
pad remote yes
pad send yes
'''


def test_jjp_status_rows():
    rows = dict(C.parse_status(JJP_STATUS))
    assert rows['Game on the card'] == 'Wonka' and rows['System'] == 'Ubuntu 21.10'
    assert rows['Wi-Fi'] == 'HomeNet, 5 GHz (5180 MHz), signal 78%'
    assert rows['Network'] == 'enp2s0 192.168.4.80/24'
    assert rows['Room on the disk, system'].endswith('free of 15.3 GB') and 'Room on the disk, settings' in rows
    assert rows['From PAD on this card'] == 'files sent from PAD'


class Care:
    def __init__(self, files):
        self.files = files

    def sh(self, script, timeout=60, check=True):
        if script.startswith('[ -d /jjpe/gen1 ]'):
            return 0, 'jjp\n'
        if script == C.JJP_GAME:
            return 0, 'Wonka\n'
        raise AssertionError(script[:60])


def _tar(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_jjp_backup_is_the_perm_partition(tmp_path, monkeypatch):
    files = {'perm/vf/hiscores.dat': b'DAV 9876543210', 'perm/vf/settings/adjustments.cfg': b'BALLS 3'}
    asked = []
    monkeypatch.setattr(C.machine_screen, '_bytes_of', lambda m, cmd, t: asked.append(cmd) or _tar(files))
    dest = tmp_path / 'b.zip'
    got = C.backup_settings(Care(files), str(dest))
    assert asked == [C.JJP_BACKUP] and got == dict(game='Wonka', files=2, bytes=21)
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist()) == {C.MANIFEST, C.JJP_TAR}
    manifest, _raw = C.read_backup(str(dest))
    assert manifest['root'] == 'perm' and manifest['maker'] == 'jjp' and set(manifest['files']) == set(files)


def test_a_stern_backup_is_not_put_on_a_jjp_machine(tmp_path):
    dest = tmp_path / 's.zip'
    with zipfile.ZipFile(dest, 'w') as z:
        raw = _tar({'nv/godzilla_le/NVM/1': b'x'})
        z.writestr(C.MANIFEST, json.dumps(dict(kind='pad-machine-settings', game='godzilla_le', files={
            'nv/godzilla_le/NVM/1': hashlib.sha1(b'x').hexdigest()})))
        z.writestr(C.TAR_NAME, raw)
    with pytest.raises(C.CareError, match='from a Stern machine'):
        C.restore_settings(Care({}), str(dest))


def test_jjp_restore_script_keeps_what_it_replaces():
    assert '/var/lib/pad/perm.pad-old.tar' in C.JJP_RESTORE and '! -name lost+found' in C.JJP_RESTORE
    assert C.JJP_RESTORE.index('perm.pad-old.tar.tmp') < C.JJP_RESTORE.index('-exec rm -rf')
    assert posixpath.dirname(C.JJP_UPLOAD) == '/var/lib/pad'
