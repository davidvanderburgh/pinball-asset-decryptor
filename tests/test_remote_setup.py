"""PAD-1427: remote access made friendly.

* a card (an image file, or the machine's SD card in this computer's reader) gets remote access with one button,
  in place, letting in PAD's own key: nothing to paste (core/remote_setup.py, the elevated helper's job);
* a scan finds the machine on the home network and it is remembered with its identity, so a machine the router
  moved is found again (core/machine_scan.py, pad_ssh_key.machine, remote_send.connect);
* the Network tab drives both (webui/tabs/network.py).

The card tests need real e2fsprogs (mke2fs/debugfs): they run under WSL/Linux and skip elsewhere, as
test_ssh_card does. The real-card proof (a stock Deadpool LE card set up, booted in the PAD-1397 machine stand-in,
found by a scan and logged in to) is in docs/plans/remote-access-friendly.md."""
import contextlib
import ipaddress
import json
import os
import socket
import threading

import pytest

from pinball_decryptor.core import card_extras, machine_scan, pad_ssh_key, rawdevice, remote_send, remote_setup
from pinball_decryptor.core import ssh_card as S
from pinball_decryptor.core.card_extras import ExtrasError
from tests.test_card_extras import key
from tests.test_ssh_card import card  # noqa: F401 - the fixture


@pytest.fixture(autouse=True)
def own_key_dir(tmp_path, monkeypatch):
    """Each test its own PAD key and machine list (conftest's is shared by the whole session)."""
    monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', str(tmp_path / 'remote_access'))


@pytest.fixture
def qualified(monkeypatch):
    monkeypatch.setattr(S, 'QUALIFIED_PLATFORMS', {'stern-spike2'})


# ---------------------------------------------------------------- one button: a card gets remote access
def test_set_up_puts_remote_access_on_an_image_in_place_and_nothing_else(card, qualified):
    before = card.read_bytes()
    assert not remote_setup.look(str(card))['enabled']
    notes = []
    assert remote_setup.set_up(str(card), log=lambda t, l='info': notes.append(t)) == 'done'
    state = S.inspect_image(str(card))
    pad = pad_ssh_key.public_line().strip()
    assert state['enabled'] and state['public_keys'].strip() == pad
    after = card.read_bytes()
    assert after[:1 << 20] == before[:1 << 20] and after[25 << 20:] == before[25 << 20:]
    assert any('Remote access is on' in n for n in notes)
    look = remote_setup.look(str(card))
    assert look['ok'] and look['enabled'] and look['lets_pad_in']
    # pressed again: nothing to do, nothing written
    assert remote_setup.set_up(str(card)) == 'already'
    assert card.read_bytes() == after


def test_set_up_keeps_the_keys_the_card_already_trusted(card, qualified, tmp_path):
    out = tmp_path / 'built.raw'
    out.write_bytes(card.read_bytes())
    S.apply_to_build(str(card), str(out), {'enabled': True, 'public_keys': key()})
    assert remote_setup.set_up(str(out)) == 'done'
    keys = S.inspect_image(str(out))['public_keys']
    assert key() in keys and pad_ssh_key.public_line().split()[1] in keys


def test_a_plugged_in_card_is_set_up_through_the_device_path(card, qualified, monkeypatch):
    """The machine's SD card in the reader: opened as a raw device (RawDeviceFile), the disk held as a flash holds
    it while the blocks are written."""
    dev = str(card)
    monkeypatch.setattr(rawdevice, 'is_device_path', lambda p: str(p) == dev)
    monkeypatch.setattr(remote_setup, 'is_device_path', lambda p: str(p) == dev)
    held = []

    @contextlib.contextmanager
    def hold(path, log=None):
        held.append(path)
        yield
    monkeypatch.setattr(rawdevice, '_disk_offline_for_write', hold)
    monkeypatch.setattr(rawdevice, '_locked_volumes', hold)
    opened = []
    real = rawdevice.RawDeviceFile

    class Dev(real):
        def __init__(self, path, writable=False, sector=None):
            opened.append((path, writable))
            super().__init__(path, writable, sector=512)
    monkeypatch.setattr(rawdevice, 'RawDeviceFile', Dev)
    notes = []
    assert remote_setup.set_up(dev, log=lambda t, l='info': notes.append(t)) == 'done'
    assert held == [dev, dev] and (dev, True) in opened
    assert any('the card' in n for n in notes)
    monkeypatch.setattr(rawdevice, 'is_device_path', lambda p: False)
    assert S.inspect_image(dev)['enabled']


def test_not_a_game_card_is_refused_plainly_and_left_alone(tmp_path):
    junk = tmp_path / 'photos.img'
    junk.write_bytes(b'\0' * (2 << 20))
    with pytest.raises(ExtrasError):
        remote_setup.set_up(str(junk))
    assert junk.read_bytes() == b'\0' * (2 << 20)
    look = remote_setup.look(str(junk))
    assert not look['ok'] and look['reason']


def test_cancel_before_writing_leaves_the_card_as_it_was(card, qualified):
    before = card.read_bytes()
    with pytest.raises(ExtrasError, match='Canceled'):
        remote_setup.set_up(str(card), cancel=lambda: True)
    assert card.read_bytes() == before


def test_the_elevated_helper_runs_the_job_and_reports_it(card, qualified, tmp_path):
    from pinball_decryptor.core import elevated_flash as ef
    ipc = tmp_path / 'ipc'
    ipc.mkdir()
    (ipc / 'job.json').write_text(json.dumps({'mode': 'remote_access', 'device': str(card),
                                              'pad_line': pad_ssh_key.public_line()}))
    assert ef.run_helper_main(['--flash-helper', str(ipc)]) == 0
    res = json.loads((ipc / 'result.json').read_text())
    assert res['ok'] and res['text'] == 'done'
    assert any('Remote access is on' in json.loads(line)['text']
               for line in (ipc / 'log.jsonl').read_text().splitlines())
    assert S.inspect_image(str(card))['enabled']


def test_the_elevated_helper_reports_a_refusal(tmp_path):
    from pinball_decryptor.core import elevated_flash as ef
    junk = tmp_path / 'x.img'
    junk.write_bytes(b'\0' * 4096)
    ipc = tmp_path / 'ipc'
    ipc.mkdir()
    (ipc / 'job.json').write_text(json.dumps({'mode': 'remote_access', 'device': str(junk)}))
    ef.run_helper_main(['--flash-helper', str(ipc)])
    res = json.loads((ipc / 'result.json').read_text())
    assert not res['ok'] and res['error']


def test_a_plugged_in_card_asks_for_administrator_access(monkeypatch):
    from pinball_decryptor.core import admin, elevated_flash as ef
    monkeypatch.setattr(admin, 'is_admin', lambda: False)
    monkeypatch.setattr(remote_setup, 'is_device_path', lambda p: True)
    jobs = []

    def spawn(ipc):
        jobs.append(json.load(open(os.path.join(ipc, 'job.json'))))
        return None                                     # the prompt couldn't be shown
    monkeypatch.setattr(ef, '_spawn_elevated_helper', spawn)
    with pytest.raises(ExtrasError, match='administrator'):
        remote_setup.set_up_with_privileges(r'\\.\PhysicalDrive3')
    assert jobs == [{'mode': 'remote_access', 'device': r'\\.\PhysicalDrive3', 'pad_line': pad_ssh_key.public_line()}]


# ---------------------------------------------------------------- the scan, and the machine remembered
def test_game_of_reads_the_games_link_either_way():
    assert machine_scan.game_of('deadpool_le/game\nstern\n') == 'deadpool_le'        # Spike 2: relative
    assert machine_scan.game_of('/games/fallout_le/game\n') == 'fallout_le'
    assert machine_scan.game_of('') == ''


@pytest.fixture
def ssh_like_server():
    """A local server that answers like an SSH server (its banner) on a free port."""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(8)
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                continue
            with c:
                c.sendall(b'SSH-2.0-dropbear_2025.88\r\n')
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield srv.getsockname()[1]
    stop.set()
    t.join(2)
    srv.close()


def test_scan_finds_an_ssh_server_and_says_what_it_is(ssh_like_server):
    found = machine_scan.scan([ipaddress.IPv4Network('127.0.0.1/32')], port=ssh_like_server, log_in=False)
    assert [(f['address'], f['banner']) for f in found] == [('127.0.0.1', 'SSH-2.0-dropbear_2025.88')]
    assert machine_scan.scan([ipaddress.IPv4Network('127.0.0.2/32')], port=ssh_like_server, log_in=False) == []


def test_networks_are_the_24_around_each_address():
    nets = machine_scan.networks([ipaddress.IPv4Address('192.168.4.37'), ipaddress.IPv4Address('192.168.4.9'),
                                  ipaddress.IPv4Address('10.0.0.2')])
    assert [str(n) for n in nets] == ['192.168.4.0/24', '10.0.0.0/24']


def test_every_machine_found_is_remembered_and_one_is_picked():
    """David: "I can have MANY machines on my network (deadpool, guardians, bond, etc.) so I need a way to connect
    to a specific one"."""
    pad_ssh_key.remember_machine('192.168.1.57', ('ssh-ed25519', 'AAAA'), 'deadpool_le')
    pad_ssh_key.remember_machine('192.168.1.58', ('ssh-ed25519', 'BBBB'), 'guardians_le', make_current=False)
    pad_ssh_key.remember_machine('192.168.1.59', ('ssh-ed25519', 'CCCC'), 'james_bond_007_le', make_current=False)
    assert [m['game'] for m in pad_ssh_key.machines()] == ['deadpool_le', 'guardians_le', 'james_bond_007_le']
    assert pad_ssh_key.last_address() == '192.168.1.57'
    assert pad_ssh_key.select_machine('192.168.1.58') and pad_ssh_key.machine()['game'] == 'guardians_le'
    assert not pad_ssh_key.select_machine('192.168.1.99')
    assert pad_ssh_key.machine_for_game('james_bond_007_le') == '192.168.1.59'
    assert pad_ssh_key.machine_for_game('godzilla_pro') == ''
    # the router moves Guardians: the same identity at a new address is the same machine, still the one picked
    pad_ssh_key.remember_machine('192.168.1.70', ('ssh-ed25519', 'BBBB'), 'guardians_le', make_current=False)
    assert [m['address'] for m in pad_ssh_key.machines()] == ['192.168.1.57', '192.168.1.70', '192.168.1.59']
    assert pad_ssh_key.last_address() == '192.168.1.70'
    # forgetting the one picked moves to the first left
    pad_ssh_key.forget_machine('192.168.1.70')
    assert pad_ssh_key.last_address() == '192.168.1.57' and len(pad_ssh_key.machines()) == 2


def test_a_typed_address_becomes_the_machine_used():
    pad_ssh_key.remember_machine('192.168.1.57', ('ssh-ed25519', 'AAAA'), 'deadpool_le')
    pad_ssh_key.remember_address('192.168.1.80')
    assert pad_ssh_key.machine() == {'address': '192.168.1.80', 'host_key': None, 'game': ''}
    pad_ssh_key.remember_address('192.168.1.57')
    assert pad_ssh_key.machine()['host_key'] == ('ssh-ed25519', 'AAAA')
    assert len(pad_ssh_key.machines()) == 2


def test_the_one_address_file_of_before_reads_as_one_machine():
    os.makedirs(pad_ssh_key.KEY_DIR, exist_ok=True)
    with open(os.path.join(pad_ssh_key.KEY_DIR, 'machines.json'), 'w') as fh:
        json.dump({'address': '192.168.1.40'}, fh)
    assert pad_ssh_key.last_address() == '192.168.1.40'
    assert pad_ssh_key.machines() == [{'address': '192.168.1.40', 'host_key': None, 'game': ''}]


def test_write_tab_send_goes_to_the_machine_that_runs_the_card(tmp_path, monkeypatch):
    from pinball_decryptor.webui import compat
    from tests.webui_harness import web_app
    pad_ssh_key.remember_machine('192.168.1.57', ('ssh-ed25519', 'AAAA'), 'deadpool_le')
    pad_ssh_key.remember_machine('192.168.1.58', ('ssh-ed25519', 'BBBB'), 'guardians_le')
    project = tmp_path / 'project'
    project.mkdir()
    card_extras.save(str(project), True, '')
    sent = []
    with web_app(tmp_path, mfr='stern') as w:
        w.run(w.window.write_assets_var.set, str(project))
        w.run(w.window.write_upd_var.set, str(tmp_path / 'deadpool_le-1_16_0.Release.8G.sdcard.raw'))
        write = w.window.service('write')
        monkeypatch.setattr(write, '_target_write_path', lambda: str(tmp_path / 'out.raw'))
        monkeypatch.setitem(w.window.cb, 'on_build_send', sent.append)
        monkeypatch.setattr(compat.messagebox, 'showinfo', lambda *a, **k: pytest.fail(a))
        assert w.call('write.send_to_machine') is True
        # a card no known machine runs goes to the one picked
        w.run(w.window.write_upd_var.set, str(tmp_path / 'godzilla_pro-1_0_0.Release.8G.sdcard.raw'))
        assert w.call('write.send_to_machine') is True
    assert sent == ['192.168.1.57', '192.168.1.58']


def test_connect_finds_a_remembered_machine_the_router_moved(monkeypatch):
    pad_ssh_key.remember_machine('192.168.1.57', ('ssh-ed25519', 'AAAA'), 'deadpool_le')

    class M:
        def __init__(self, host, port=22):
            if host == '192.168.1.57':
                raise remote_send.Unreachable("Couldn't reach 192.168.1.57")
            self.host, self.port = host, port
    monkeypatch.setattr(remote_send, 'SshMachine', M)
    monkeypatch.setattr(machine_scan, 'find_moved', lambda hk, port=22, nets=None:
                        '192.168.1.61' if tuple(hk) == ('ssh-ed25519', 'AAAA') else None)
    logs = []
    m = remote_send.connect('192.168.1.57', log=lambda t, l='info': logs.append(t))
    assert m.host == '192.168.1.61'
    assert pad_ssh_key.machine()['address'] == '192.168.1.61'
    assert pad_ssh_key.host_key('192.168.1.61') == ('ssh-ed25519', 'AAAA')
    assert any('Found it at 192.168.1.61' in t for t in logs)


def test_connect_does_not_look_for_a_machine_it_never_found(monkeypatch):
    pad_ssh_key.remember_address('192.168.1.57')

    def unreachable(host, port=22):
        raise remote_send.Unreachable('nope')
    monkeypatch.setattr(remote_send, 'SshMachine', unreachable)
    monkeypatch.setattr(machine_scan, 'find_moved', lambda *a, **k: pytest.fail('scanned'))
    with pytest.raises(remote_send.Unreachable):
        remote_send.connect('192.168.1.57')


# ---------------------------------------------------------------- the Network tab
def _settle(w, key):
    import time
    for _ in range(300):
        w.drain()
        if not w.state('network')[key]:
            return
        time.sleep(0.02)


def test_network_tab_scan_remembers_every_machine_and_picks_one(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    deadpool = dict(address='192.168.1.57', banner='dropbear', lets_in=True, game='deadpool_le',
                    host_key=('ssh-ed25519', 'AAAA'), note='')
    other = dict(address='192.168.1.20', banner='OpenSSH', lets_in=False, game='', host_key=None,
                 note="doesn't let this computer in")
    with web_app(tmp_path, mfr='stern') as w:
        monkeypatch.setattr(machine_scan, 'scan', lambda **k: [dict(deadpool), dict(other)])
        w.call('network.scan')
        _settle(w, 'scanning')
        st = w.state('network')
        assert st['address'] == '192.168.1.57' and st['machine_game'] == 'Deadpool LE'
        assert 'remembered it' in st['scan_note'] and st['scan_kind'] == 'ok'
        assert pad_ssh_key.machine()['host_key'] == ('ssh-ed25519', 'AAAA')
        assert pad_ssh_key.host_key('192.168.1.57') == ('ssh-ed25519', 'AAAA')

        # David's network: Deadpool, Guardians and Bond.  All are remembered; Deadpool stays the one picked
        many = [dict(deadpool), dict(deadpool, address='192.168.1.58', game='guardians_le',
                                     host_key=('ssh-ed25519', 'BBBB')),
                dict(deadpool, address='192.168.1.59', game='james_bond_007_le', host_key=('ssh-ed25519', 'CCCC')),
                dict(other)]
        monkeypatch.setattr(machine_scan, 'scan', lambda **k: [dict(r) for r in many])
        w.call('network.scan')
        _settle(w, 'scanning')
        st = w.state('network')
        assert 'Found 3 machines (Deadpool LE, Guardians LE, James Bond 007 LE)' in st['scan_note']
        assert '2 of them new' in st['scan_note'] and 'Pick the one' in st['scan_note']
        assert [m['label'] for m in st['machines']] == ['Deadpool LE at 192.168.1.57', 'Guardians LE at 192.168.1.58',
                                                         'James Bond 007 LE at 192.168.1.59']
        assert st['address'] == '192.168.1.57' and st['found'] == []
        assert w.call('network.use_machine', '192.168.1.20') is False      # it doesn't let PAD in
        assert w.call('network.use_machine', '192.168.1.59') is True
        assert w.state('network')['address'] == '192.168.1.59'
        assert w.state('network')['machine_game'] == 'James Bond 007 LE'
        assert pad_ssh_key.last_address() == '192.168.1.59'
        # forget the one picked: the next is used
        w.call('network.forget_machine')
        assert w.state('network')['address'] == '192.168.1.57' and len(w.state('network')['machines']) == 2

        monkeypatch.setattr(machine_scan, 'scan', lambda **k: [dict(other)])
        w.call('network.scan')
        _settle(w, 'scanning')
        st = w.state('network')
        assert st['scan_kind'] == 'err' and 'only other devices' in st['scan_note'] and len(st['found']) == 1

        monkeypatch.setattr(machine_scan, 'scan', lambda **k: [])
        w.call('network.scan')
        _settle(w, 'scanning')
        assert w.state('network')['scan_kind'] == 'err' and 'Found no machine' in w.state('network')['scan_note']


def test_network_tab_sets_up_the_picked_card_and_keeps_it_on_for_the_project(tmp_path, monkeypatch):
    from pinball_decryptor.webui import compat
    from tests.test_webui_network import ready
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr='stern') as w:
        project, _svc = ready(w, tmp_path, monkeypatch)
        assert w.state('shell') is not None
        w.window.service('network').set(cards=[{'display': 'SD card (7.9 GB, External)',
                                                 'device': r'\\.\PhysicalDrive3'}], cards_state='ok')
        w.call('network.pick_card', r'\\.\PhysicalDrive3')
        asked, ran = [], []
        monkeypatch.setattr(compat.messagebox, 'askyesno', lambda *a, **k: asked.append(a[1]) or True)

        def fake(path, log=None, progress=None, cancel=None):
            ran.append(path)
            log('Writing the changes to the card...', 'info')
            progress(50, 100)
            return 'done'
        monkeypatch.setattr(remote_setup, 'set_up_with_privileges', fake)
        assert w.call('network.set_up_card') is True
        _settle(w, 'setup_busy')
        st = w.state('network')
        assert ran == [r'\\.\PhysicalDrive3'] and 'SD card (7.9 GB, External)' in asked[0]
        assert st['setup_kind'] == 'ok' and 'has remote access now' in st['setup_note']
        assert 'Find my machine' in st['setup_note']
        # a card written later from the open project keeps it
        assert card_extras.load(str(project))['enabled']

        def refused(path, **k):
            raise ExtrasError('Administrator access was declined, so the card was not changed.')
        monkeypatch.setattr(remote_setup, 'set_up_with_privileges', refused)
        w.call('network.set_up_card')
        _settle(w, 'setup_busy')
        assert w.state('network')['setup_kind'] == 'err' and 'declined' in w.state('network')['setup_note']


def test_network_tab_needs_no_project():
    from pinball_decryptor.webui.tabs.network import NetworkTab
    assert NetworkTab.rail_needs(None) == 'none'
