"""PAD-1588: settings and score backups a machine gets by itself, before a Send and before a card write, kept
per machine and pruned, and restored from My machines."""
import hashlib
import io
import os
import tarfile
import time
import zipfile

import pytest

from pinball_decryptor.core import machine_backups as B, machine_care as C, pad_ssh_key, remote_send

DAY = 24 * 3600
HK = ('ssh-ed25519', 'AAAAC3NzaC1lZDI1NTE5AAAAIHostKeyOfTheBasementGodzilla')


def _tar(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as t:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


class Machine:
    """A stand-in for a connected machine whose ``/data/nv`` is :attr:`nv`; a restore puts the tar it was sent there."""

    def __init__(self, nv):
        self.nv, self.ran, self.paused, self.resumed, self.uploaded = nv, [], 0, 0, None
        self.sftp, self.host, self.port, self.identity, self.closed = self, '192.168.4.77', 22, HK, 0

    def sh(self, script, timeout=60, check=True):
        self.ran.append(script)
        if script == B.SUMS:
            return 0, ''.join('%s %s\n' % (hashlib.sha1(d).hexdigest(), n) for n, d in sorted(self.nv.items()))
        if script.startswith('readlink /games/game'):
            return 0, 'godzilla_le/game\n'
        if 'pad-settings-restore.tar' in script:
            with tarfile.open(fileobj=io.BytesIO(self.uploaded)) as t:
                self.nv = {m.name: t.extractfile(m).read() for m in t.getmembers() if m.isfile()}
            return 0, ''.join('%s %s\n' % (hashlib.sha1(d).hexdigest(), n) for n, d in sorted(self.nv.items()))
        return 0, ''

    def raw(self, command):
        self.ran.append(command)
        assert command.startswith('cd /data && tar')
        return _tar(self.nv)

    def open(self, path, mode):                              # sftp.open, for a restore's upload
        m, buf = self, io.BytesIO()

        class F:
            def __enter__(self_):
                return buf

            def __exit__(self_, *a):
                m.uploaded = buf.getvalue()
        return F()

    def pause_game(self):
        self.paused += 1

    def resume_game(self, text=None):
        self.resumed += 1

    def close(self):
        self.closed += 1


NV = {'nv/godzilla_le/NVM/00000031': b'GRAND CHAMPION DAV 1,200,000,000' * 8,
      'nv/godzilla_le/NVRAM/00000014': b'adjustments: balls 3, replay auto'}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(B, 'root', lambda: str(tmp_path / 'machine_backups'))
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', str(tmp_path / 'keys'))
    pad_ssh_key.remember_machine('192.168.4.77', HK, 'godzilla_le')
    return tmp_path


def _zips(mid):
    return sorted(n for n in os.listdir(B.folder(mid)) if n.endswith('.zip'))


def test_a_machine_with_remote_access_is_backed_up_without_a_click(store):
    m = Machine(dict(NV))
    mid = B.machine_id(HK)
    seen, said = [], []

    def connect(address):
        seen.append(address)
        return m
    t0 = time.time()
    out = B.auto_pass({'godzilla_le'}, 5, connect=connect, now=t0, log=lambda t, l='info': said.append(t))
    assert seen == ['192.168.4.77'] and out[0][1]['status'] == 'taken' and len(_zips(mid)) == 1
    assert 'by itself' in said[0] and m.closed == 1
    # only reads: the game is never held, and nothing is written to the machine
    assert m.paused == 0 and m.resumed == 0 and m.uploaded is None
    assert not any('rm ' in r or 'mv ' in r for r in m.ran)
    got = B.kept(mid)[0]
    assert (got['game'], got['files'], got['why']) == ('godzilla_le', 2, 'auto')

    # the same day: not looked at again (no login at all)
    assert B.auto_pass({'godzilla_le'}, 5, connect=connect, now=t0 + 3600) == [] and len(seen) == 1
    # a day later, nothing changed: looked at, no duplicate kept, and not looked at again for a day
    out = B.auto_pass({'godzilla_le'}, 5, connect=connect, now=t0 + DAY + 60)
    assert out[0][1]['status'] == 'unchanged' and len(_zips(mid)) == 1
    assert not any(r.startswith('cd /data && tar') for r in m.ran[-2:])          # only the sums were read
    assert B.auto_pass({'godzilla_le'}, 5, connect=connect, now=t0 + DAY + 3600) == []
    # a machine not on My machines, and one not on the network, are left alone
    assert B.auto_pass({'deadpool_le'}, 5, connect=connect, now=t0 + 9 * DAY) == []

    def gone(address):
        raise remote_send.Unreachable('Nothing answered at %s.' % address)
    out = B.auto_pass({'godzilla_le'}, 5, connect=gone, now=t0 + 9 * DAY)
    assert out[0][1] is None and 'Nothing answered' in out[0][2]


def test_old_backups_are_pruned_to_the_kept_count(store):
    m = Machine(dict(NV))
    mid = B.machine_id(HK)
    t0 = time.time()
    for day in range(6):
        m.nv['nv/godzilla_le/NVM/00000031'] = b'scores of day %d' % day
        res = B.take(m, mid, 3, now=t0 + day * DAY + 1)
        assert res['status'] == 'taken'
    kept = B.kept(mid, sums=True)
    assert len(kept) == 3 and len(_zips(mid)) == 3
    # the newest three stay
    assert [k['sums']['nv/godzilla_le/NVM/00000031'] for k in kept] == [
        hashlib.sha1(b'scores of day %d' % d).hexdigest() for d in (5, 4, 3)]
    # the owner keeps fewer: pruned at once
    assert len(B.prune(mid, 1)) == 2 and len(_zips(mid)) == 1


def _age(path, stamp):
    """Make a backup read as taken at *stamp* (its record says when it was taken)."""
    import json
    with zipfile.ZipFile(path) as z:
        man = json.loads(z.read(C.MANIFEST))
        raw = z.read(C.TAR_NAME)
    man['taken'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp))
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(C.MANIFEST, json.dumps(man))
        z.writestr(C.TAR_NAME, raw)


def test_a_restore_from_a_kept_backup_brings_back_changed_scores(store):
    m = Machine(dict(NV))
    mid = B.machine_id(HK)
    first = B.take(m, mid, 5)['path']
    m.nv['nv/godzilla_le/NVM/00000031'] = b'scores wiped by a card written whole'
    assert B.take(m, mid, 5, force=True)['status'] == 'taken' and len(B.kept(mid)) == 2
    res = C.restore_settings(m, first)
    assert res['files'] == 2 and m.nv == NV and m.paused == 1 and m.resumed == 1


def test_settings_put_back_are_no_new_backup_and_are_pruned_last(store):
    """A restored backup is the machine's settings again: no copy of it is kept, and it is the last one pruned."""
    m = Machine(dict(NV))
    mid = B.machine_id(HK)
    t0 = time.time()
    a = B.take(m, mid, 3, now=t0)['path']
    for day in (1, 2):
        m.nv['nv/godzilla_le/NVM/00000031'] = b'day %d' % day
        assert B.take(m, mid, 3, now=t0 + day * DAY)['status'] == 'taken'
    C.restore_settings(m, a)
    res = B.take(m, mid, 3, force=True, now=t0 + 3 * DAY)
    assert res['status'] == 'unchanged' and res['path'] == a and len(B.kept(mid)) == 3
    assert B.kept(mid)[0]['path'] == a                                  # what the machine has now, first
    m.nv['nv/godzilla_le/NVM/00000031'] = b'day 4'
    assert B.take(m, mid, 3, now=t0 + 4 * DAY)['pruned'] != [os.path.basename(a)]
    assert os.path.exists(a) and len(B.kept(mid)) == 3


def test_before_a_send_one_is_taken_whatever_its_age_but_never_a_duplicate(store):
    m = Machine(dict(NV))
    said = []
    log = lambda t, l='info': said.append((l, t))                                    # noqa: E731
    assert B.before_send(m, 5, log)['status'] == 'taken'
    assert B.before_send(m, 5, log)['status'] == 'unchanged'
    assert len(B.kept(B.machine_id(HK))) == 1
    assert 'first (2 files)' in said[0][1] and 'the same as its backup of' in said[1][1]
    # a backup that can't be taken never stops the Send
    m.raw = lambda command: b'not a tar'
    m.nv['nv/godzilla_le/x'] = b'new'
    assert B.before_send(m, 5, log) is None and said[-1][0] == 'warning' and 'the Send goes on' in said[-1][1]


def test_before_a_card_write_every_reachable_machine_of_the_game_is_backed_up(store):
    m = Machine(dict(NV))
    said = []
    out = B.before_write('godzilla_le', 5, lambda t, l='info': said.append(t), connect=lambda a: m)
    assert [r['status'] for r in out] == ['taken'] and 'before this card is written' in said[0]
    assert B.kept(B.machine_id(HK))[0]['why'] == 'write'
    assert B.before_write('deadpool_le', 5, connect=lambda a: m) == []

    def gone(address):
        raise remote_send.Unreachable('no')
    assert B.before_write('godzilla_le', 5, connect=gone) == []


def test_the_send_pipeline_backs_up_first(store, monkeypatch):
    m = Machine(dict(NV))
    order = []
    monkeypatch.setattr(remote_send, 'send_image', lambda *a, **k: order.append('send') or 'Sent.')
    real = B.before_send
    monkeypatch.setattr(B, 'before_send', lambda *a, **k: order.append('backup') or real(*a, **k))
    done = []
    p = remote_send.SendPipeline('card.raw', '192.168.4.77', lambda *a, **k: None, lambda i: None,
                                 lambda *a: None, lambda ok, s: done.append(ok), connect_fn=lambda a: m, backup_keep=5)
    p.run()
    assert order == ['backup', 'send'] and done == [True] and len(B.kept(B.machine_id(HK))) == 1
    # the owner turned backups off: none
    order.clear()
    p = remote_send.SendPipeline('card.raw', '192.168.4.77', lambda *a, **k: None, lambda i: None,
                                 lambda *a: None, lambda ok, s: None, connect_fn=lambda a: m)
    p.run()
    assert order == ['send']


def test_settings_switch_and_count():
    assert B.auto_on({}) is True and B.auto_on({B.AUTO_KEY: False}) is False
    assert B.keep_of({}) == B.KEEP_DEFAULT and B.keep_of({B.KEEP_KEY: 0}) == 1
    assert B.keep_of({B.KEEP_KEY: 'x'}) == B.KEEP_DEFAULT and B.keep_of({B.KEEP_KEY: 999}) == B.KEEP_MAX
    # a machine is its identity, so one the router moves keeps its backups
    assert B.machine_id(HK, '192.168.4.77') == B.machine_id(HK, '192.168.4.90')


def test_my_machines_shows_the_last_backup_and_restores_any(tmp_path, monkeypatch):
    """The page: the row of a machine on the network names its last backup and lists every kept one; Back up now,
    the keep count and Restore go through the page's own calls."""
    from tests.webui_harness import web_app
    from pinball_decryptor.core import lineage
    from pinball_decryptor.webui import compat
    card = tmp_path / 'godzilla_le-1_16_0.raw'
    card.write_bytes(b'x' * 4096)
    info = {'print': 'p' * 40, 'sidx': 'godzilla_le-1_16_0', 'label': 'Godzilla LE 1.16', 'official': True,
            'manufacturer': 'stern'}
    monkeypatch.setattr(lineage, 'card_print', lambda p, measure=False: dict(info))
    monkeypatch.setattr(B, 'root', lambda: str(tmp_path / 'machine_backups'))
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', str(tmp_path / 'keys'))
    pad_ssh_key.remember_machine('192.168.4.77', HK, 'godzilla_le')
    m = Machine(dict(NV))
    monkeypatch.setattr(B, '_connect', lambda address, timeout=10: m)
    monkeypatch.setattr(remote_send, 'connect', lambda address, log=None: m)

    def rows(w):
        return (w.state('shellx').get('machines') or {}).get('rows') or []

    def until(w, pred):
        for _ in range(400):
            w.drain()
            if pred():
                return True
            time.sleep(0.02)
        return False
    with web_app(tmp_path) as w:
        mid = w.call('shellx.machines_add', str(card), 'Basement Godzilla')
        assert until(w, lambda: rows(w) and rows(w)[0]['backup_machines'] == ['192.168.4.77'])
        st = w.state('shellx')['machines']
        assert st['backup'] == {'auto': True, 'keep': 5, 'busy': False, 'any': True}
        assert rows(w)[0]['backup_last'] == '' and rows(w)[0]['backups'] == []
        # the pass the app runs by itself
        svc = w.window.service('shellx')
        assert w.run(svc._backup_pass)
        assert until(w, lambda: rows(w)[0]['backup_last'])
        r = rows(w)[0]
        assert len(r['backups']) == 1 and r['backups'][0]['why'] == 'auto' and r['backups'][0]['files'] == 2
        first = r['backups'][0]['path']
        # scores change; Back up now keeps a second
        m.nv['nv/godzilla_le/NVM/00000031'] = b'scores lost'
        assert w.call('shellx.machines_backup_now', mid)
        assert until(w, lambda: len(rows(w)[0]['backups']) == 2)
        assert rows(w)[0]['backups'][0]['why'] == 'by hand'
        # keep 1: pruned at once, the newest kept
        assert w.call('shellx.machines_set_backup', None, 1)
        assert until(w, lambda: len(rows(w)[0]['backups']) == 1)
        assert w.state('shellx')['machines']['backup']['keep'] == 1
        assert not os.path.exists(first)
        # restore the kept one (asked first; No does nothing)
        m.nv['nv/godzilla_le/NVM/00000031'] = b'scores lost again'
        kept_path = rows(w)[0]['backups'][0]['path']
        monkeypatch.setattr(compat.messagebox, 'askyesno', lambda *a, **k: False)
        assert w.call('shellx.machines_restore', mid, kept_path) is False and m.paused == 0
        monkeypatch.setattr(compat.messagebox, 'askyesno', lambda *a, **k: True)
        assert w.call('shellx.machines_restore', mid, kept_path)
        assert until(w, lambda: m.resumed == 1)
        assert m.nv['nv/godzilla_le/NVM/00000031'] == b'scores lost'
        assert until(w, lambda: any('back (2 files)' in t['text'] for t in w.state('shell')['toasts']))
        # the switch off: no pass
        assert w.call('shellx.machines_set_backup', False, None)
        assert w.run(svc._backup_pass) is False
        assert until(w, lambda: w.state('shellx')['machines']['backup']['auto'] is False)
