from pathlib import Path
import pytest
from pinball_decryptor.core import card_extras, ssh_card, staged_changes
from tests.test_card_extras import key
from tests.webui_harness import web_app


def ready(w, tmp_path, monkeypatch):
    project = tmp_path / 'project'; project.mkdir()
    image = tmp_path / 'source.raw'; image.write_bytes(b'card')
    monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=True, reason='', platform='stern-spike2', enabled=False, public_keys=''))
    w.run(w.window.write_assets_var.set, str(project))
    w.run(w.window.write_upd_var.set, str(image))
    svc = w.window.service('network')
    assert svc is not None
    w.run(svc.on_show)
    return project, svc


@pytest.mark.parametrize('era', ['spike2', 'spike3'])
def test_sidebar_and_project_persistence(tmp_path, monkeypatch, era):
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = era
        project, svc = ready(w, tmp_path, monkeypatch)
        rail = w.state('shell')['tabs']
        entry = next(t for t in rail if t['ns'] == 'network')
        assert entry['group'] == 'Make' and entry['label'] == 'Network' and entry['visible']
        assert not staged_changes.load(str(project)).get('extras')
        w.call('network.configure', True, key(), str(project))
        assert card_extras.configuration(str(project))['enabled']
        w.call('network.configure', False, key(), str(project))
        assert not card_extras.configuration(str(project))['enabled']
        assert w.state('network')['public_keys'].strip() == key()
        other = tmp_path / 'other'; other.mkdir()
        w.run(w.window.write_assets_var.set, str(other))
        w.run(svc.on_project, str(other))
        assert not w.state('network')['enabled'] and not w.state('network')['public_keys']
        assert w.call('network.configure', True, key(), str(project)) is False
        assert card_extras.load(str(other)) is None


def test_invalid_key_blocks_effective_config_and_does_not_echo(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        assert w.call('network.configure', True, 'ssh-ed25519 AAAA invalid', str(project)) is False
        assert w.state('network')['error']
        with pytest.raises(card_extras.ExtrasError):
            card_extras.configuration(str(project))
        assert 'AAAA' not in w.state('network')['error']


def test_running_and_unsupported_are_locked(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        w.run(svc.on_running, True, 'write')
        assert w.call('network.configure', True, key(), str(project)) is False
        w.run(svc.on_running, False, 'write')
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=False, reason='Unqualified platform', enabled=False, public_keys=''))
        w.run(svc.on_show)
        assert not w.state('network')['supported']
        assert w.call('network.configure', True, key(), str(project)) is False
        assert card_extras.load(str(project)) is None


def test_private_key_error_prevents_build_dispatch(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        w.call('network.configure', True, key(), str(project))
        assert w.call('network.configure', True, '-----BEGIN OPENSSH PRIVATE KEY-----', str(project)) is False
        w.run(w.app._start_write)
        assert w.asked[-1]['title'] == 'Remote access'
        assert 'private' in w.asked[-1]['message'].lower()


def test_disabling_ssh_is_pending_when_source_has_it_enabled(tmp_path, monkeypatch):
    from tests.test_webui_write import wait_for
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda *a, **kw: dict(
            supported=True, reason='', enabled=True, public_keys=key() + '\n'))
        (project / '.checksums.md5').write_text('')
        assert w.call('network.configure', False, key(), str(project))
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        assert any('SSH server' in row['file'] and 'disable' in row['file']
                   for row in w.state('write')['rows'])


def test_switching_source_refreshes_whether_ssh_disable_is_a_change(tmp_path, monkeypatch):
    from tests.test_webui_write import wait_for
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        stock = tmp_path / 'stock.raw'; stock.write_bytes(b'card')
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(
            supported=True, reason='', enabled=str(path) != str(stock), public_keys=key() + '\n'))
        (project / '.checksums.md5').write_text('')
        assert w.call('network.configure', False, key(), str(project))
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        assert w.state('write')['count'] == 1
        w.call('ui.select_tab', 'network')
        w.run(w.window.write_upd_var.set, str(stock))
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        assert w.state('write')['rows'] == []


@pytest.mark.parametrize('source_enabled', [False, True])
def test_revert_all_resets_extras_to_source_and_clears_keys(tmp_path, monkeypatch, source_enabled):
    from tests.test_webui_write import wait_for
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        source_keys = key(seed=b'y') + '\n' if source_enabled else ''
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda *a, **kw: dict(
            supported=True, reason='', enabled=source_enabled, public_keys=source_keys))
        (project / '.checksums.md5').write_text('')
        assert w.call('network.configure', not source_enabled, key(), str(project))
        assert w.call('shellx.reset_open')
        rows = w.state('shellx')['reset']['rows']
        assert any(row['key'] == 'extras' and row['n'] == 1 for row in rows)
        w.answers.extend(['yes', 'ok'])
        assert w.call('shellx.reset_run', [row['key'] for row in rows])
        assert wait_for(w, lambda: not w.window._running
                        and w.state('network')['enabled'] is source_enabled
                        and w.state('network')['public_keys'] == source_keys)
        assert card_extras.load(str(project)) is None
        assert w.state('network')['enabled'] is source_enabled
        assert w.state('network')['public_keys'] == source_keys
        assert w.state('network')['error'] == ''


def test_every_rail_tab_is_listed_once():
    # PR #38 review: a doubled TABS entry drew "Network" twice in the rail
    from pinball_decryptor.webui import tabs as T
    names = [t[0] for t in T.TABS]
    assert len(names) == len(set(names)), [n for n in names if names.count(n) > 1]
    win = (Path(T.__file__).parents[1] / 'window.py').read_text(encoding='utf-8')
    assert win.count('"Network": g("modes") or _ssh_offered(mfr),') == 1


def _network_row(w):
    return next(t for t in w.state('shell')['tabs'] if t['ns'] == 'network')


@pytest.mark.parametrize('era,shown', [('spike3', True), ('spike2', True), ('spike1', False),
                                       ('sam', False), ('whitestar', False)])
def test_network_tab_follows_the_era_the_card_switches_to(tmp_path, era, shown):
    # PAD-1399: a Spike 3 card switches the Stern era to spike3, where the mode runtime (and so g("modes")) is off;
    # the Network tab was gated on that and vanished, hiding remote access on a platform it supports
    with web_app(tmp_path, mfr='stern') as w:
        if era != 'spike2':
            w.run(w.window.set_era, era)
        assert w.window.current_mfr.current_era == era
        assert _network_row(w)['visible'] is shown
        if era != 'spike2':
            w.run(w.window.set_era, 'spike2')
            assert _network_row(w)['visible'] is True


def test_offered_is_stern_spike2_and_spike3_only():
    class M:
        def __init__(self, key, era):
            self.key, self._era = key, era
    assert ssh_card.offered(M('stern', 'spike3')) and ssh_card.offered(M('stern', 'spike2'))
    assert not ssh_card.offered(M('stern', 'sam')) and not ssh_card.offered(M('jjp', 'spike3'))


def test_no_card_picked_says_so(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        w.run(w.window.write_upd_var.set, '')
        w.run(svc.publish)
        st = w.state('network')
        assert not st['supported'] and st['reason'] == 'Select the card image first (Select card tab).'


def _settle(w):
    import time
    for _ in range(200):
        w.drain()
        if not w.state('network')['checking']:
            return
        time.sleep(0.02)


def test_send_to_machine_card_remembers_the_address_and_says_what_a_check_found(tmp_path, monkeypatch):
    """PAD-1397: the Network tab's Send to machine card - the address is kept for this computer, Check connection
    says what the machine runs (or why it couldn't log in), and Forget drops a remembered machine identity."""
    from pinball_decryptor.core import pad_ssh_key, remote_send
    with web_app(tmp_path, mfr='stern') as w:
        _project, _svc = ready(w, tmp_path, monkeypatch)
        assert w.state('network')['offered']
        w.call('network.set_address', ' 192.168.1.40 ')
        assert w.state('network')['address'] == '192.168.1.40'
        assert pad_ssh_key.last_address() == '192.168.1.40'

        class M:
            def describe(self):
                return '/games/deadpool_le/game\nstern\n/dev/mmcblk0p3 3000 1000 2000 33% /games\n'

            def close(self):
                pass
        monkeypatch.setattr(remote_send, 'connect', lambda a: M())
        w.call('network.check_connection')
        _settle(w)
        assert w.state('network')['check'] == 'Connected: the machine runs Deadpool LE, and lets this computer in.'
        # PAD-1427: the machine is remembered with the game it runs, said as a title
        assert pad_ssh_key.machine()['game'] == 'deadpool_le' and w.state('network')['machine_game'] == 'Deadpool LE'

        def refused(a):
            raise remote_send.SendError("192.168.1.40 didn't let this computer in.")
        monkeypatch.setattr(remote_send, 'connect', refused)
        w.call('network.check_connection')
        _settle(w)
        assert w.state('network')['check_kind'] == 'err' and "didn't let" in w.state('network')['check']

        pad_ssh_key.remember_host('192.168.1.40', 22, 'ssh-ed25519', 'AAAA')
        w.call('network.set_address', '192.168.1.40')
        assert w.state('network')['known']
        w.call('network.forget_machine')
        assert not w.state('network')['known'] and pad_ssh_key.host_key('192.168.1.40') is None


def test_send_pipeline_reports_its_summary_or_why_not(monkeypatch):
    from pinball_decryptor.core import remote_send
    done, logs = [], []

    class M:
        closed = False

        def close(self):
            M.closed = True
    monkeypatch.setattr(remote_send, 'send_image', lambda image, m, log, progress, cancel: 'Sent 2 change(s).')
    p = remote_send.SendPipeline('card.raw', '10.0.0.5', lambda t, l='info': logs.append(t), lambda *a: None,
                                 lambda *a: None, lambda ok, m: done.append((ok, m)), connect_fn=lambda a: M())
    p.run()
    assert done == [(True, 'Sent 2 change(s).')] and M.closed

    def no(a):
        raise remote_send.SendError("Couldn't reach 10.0.0.5")
    done.clear()
    remote_send.SendPipeline('card.raw', '10.0.0.5', lambda *a, **k: None, lambda *a: None, lambda *a: None,
                             lambda ok, m: done.append((ok, m)), connect_fn=no).run()
    assert done == [(False, "Couldn't reach 10.0.0.5")]


def test_wifi_start_up_choice_is_saved_shown_and_listed_on_write(tmp_path, monkeypatch):
    """PAD-1467: the Network tab's Wi-Fi start-up switch is the project's ``extras.wifi``; a choice that differs
    from the source card is a row on the Write tab, and Revert all takes it back."""
    from pinball_decryptor.core import wifi_card
    from tests.test_webui_write import wait_for
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        st = w.state('network')
        assert st['wifi_offered'] and not st['wifi_supported'] and st['wifi_reason']      # b'card' is no card
        assert w.call('network.configure_wifi', True, str(project)) is False
        assert card_extras.load_wifi(str(project)) is None
        monkeypatch.setattr(wifi_card, 'inspect_image', lambda *a, **kw: dict(supported=True, reason='', enabled=False))
        w.run(svc.on_show)
        st = w.state('network')
        assert st['wifi_supported'] and st['wifi_enabled'] is False and st['wifi_error'] == ''
        assert w.call('network.configure_wifi', True, str(tmp_path / 'elsewhere')) is False
        w.run(svc.on_running, True, 'write')
        assert w.call('network.configure_wifi', True, str(project)) is False
        w.run(svc.on_running, False, 'write')
        assert w.call('network.configure_wifi', True, str(project)) is True
        assert card_extras.load_wifi(str(project)) == {'enabled': True, 'band5': False}
        assert w.state('network')['wifi_enabled'] is True
        assert card_extras.load(str(project)) is None                    # remote access is its own setting
        (project / '.checksums.md5').write_text('')
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        rows = [row['file'] for row in w.state('write')['rows']]
        assert rows == ['Wi-Fi start-up — join at the first attempt']
        # the same as the source card: nothing to write
        w.call('ui.select_tab', 'network')
        assert w.call('network.configure_wifi', False, str(project)) is True
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'] and w.state('write')['rows'] == [])
        # Revert all forgets the choice
        w.call('ui.select_tab', 'network')
        assert w.call('network.configure_wifi', True, str(project)) is True
        assert w.call('shellx.reset_open')
        rows = w.state('shellx')['reset']['rows']
        assert any(row['key'] == 'extras' and row['n'] == 1 for row in rows)
        w.answers.extend(['yes', 'ok'])
        assert w.call('shellx.reset_run', [row['key'] for row in rows])
        assert wait_for(w, lambda: not w.window._running and w.state('network')['wifi_enabled'] is False)
        assert card_extras.load_wifi(str(project)) is None


def test_wifi_start_up_is_a_spike2_option():
    from pinball_decryptor.core import wifi_card
    with web_app(Path(__import__('tempfile').mkdtemp()), mfr='stern') as w:
        w.window.current_mfr._era = 'spike3'
        svc = w.window.service('network')
        w.run(svc.on_show)
        assert w.state('network')['wifi_offered'] is False
        info = svc._inspect_wifi()
        assert not info['supported'] and info['reason'] == wifi_card.NOT_SPIKE2 and not info['band5_supported']


def test_wifi_start_up_says_exactly_what_it_changes(tmp_path, monkeypatch):
    """David (PAD-1467): the option names the file, its contents, the script that reads it and the resulting
    wpa_supplicant argument, and what the picked card has now."""
    from pinball_decryptor.core import wifi_card
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(wifi_card, 'inspect_image', lambda *a, **kw: dict(supported=True, reason='', enabled=False))
        w.run(svc.on_show)
        st = w.state('network')
        rows = {r[0]: r[1] for r in st['wifi_details']}
        assert rows['File added to the card'].startswith('/etc/wpa_supplicant/driver.wlan0')
        assert rows['What the file says'] == 'nl80211,wext' == wifi_card.DRIVER.decode()
        assert rows['Read by'].startswith('/etc/network/if-pre-up.d/wpa-supplicant')
        assert rows['wpa_supplicant then starts with'].startswith('-D nl80211,wext') and '-D wext' in rows['wpa_supplicant then starts with']
        assert '8812bu.ko' in rows['Not changed'] and 'To undo' in rows
        assert st['wifi_now'] == '-D wext (as shipped)'
        monkeypatch.setattr(wifi_card, 'inspect_image', lambda *a, **kw: dict(supported=True, reason='', enabled=True))
        w.run(svc.on_show)
        assert w.state('network')['wifi_now'].startswith('-D nl80211,wext')
    js = (Path(wifi_card.__file__).parents[1] / 'webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    assert 'Exactly what it changes on the card' in js and 'n.wifi_details' in js and 'n.wifi_now' in js


def test_5ghz_choice_needs_the_start_up_choice_and_a_card_with_the_right_kernel(tmp_path, monkeypatch):
    """PAD-1467: the second Wi-Fi switch (newer adapter driver, 5 GHz) is saved beside the first, goes off with it,
    is refused on a card whose kernel the bundled driver was not built for, and is its own row on the Write tab."""
    from pinball_decryptor.core import wifi_card
    from tests.test_webui_write import wait_for
    state = dict(supported=True, reason='', enabled=False, band5=False, band5_supported=False,
                 band5_reason=wifi_card.OTHER_KERNEL)
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(wifi_card, 'inspect_image', lambda *a, **kw: dict(state))
        w.run(svc.on_show)
        st = w.state('network')
        assert st['wifi_supported'] and not st['wifi_band5_supported'] and st['wifi_band5_reason'] == wifi_card.OTHER_KERNEL
        assert w.call('network.configure_wifi', True, str(project), True) is False
        assert card_extras.load_wifi(str(project)) is None
        state.update(band5_supported=True, band5_reason='')
        w.run(svc.on_show)
        st = w.state('network')
        assert st['wifi_band5_supported'] and st['wifi_band_now'].endswith('(as shipped)')
        rows = {r[0]: r[1] for r in st['wifi_band_details']}
        assert rows['File replaced on the card'].startswith('/usr/local/spike/8812bu.ko')
        assert wifi_card.NEW_VERSION in rows['Driver with this option'] and wifi_card.KERNEL in rows['Driver with this option']
        assert wifi_card.OLD_VERSION in rows['Driver as shipped'] and 'wpa_cli roam' in rows['What the added files do']
        assert '/usr/local/bin/pad-wifi-band' in rows['Files added'] and '2.4GHz' in rows['Menu wording']
        assert w.call('network.configure_wifi', True, str(project), True) is True
        assert card_extras.load_wifi(str(project)) == {'enabled': True, 'band5': True}
        assert w.state('network')['wifi_band5'] is True
        assert w.call('network.configure_wifi', True, str(project)) is True          # the first switch alone keeps it
        assert card_extras.load_wifi(str(project)) == {'enabled': True, 'band5': True}
        (project / '.checksums.md5').write_text('')
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        assert [row['file'] for row in w.state('write')['rows']] == [
            'Wi-Fi start-up — join at the first attempt', 'Wi-Fi adapter driver — newer driver, 5 GHz']
        w.call('ui.select_tab', 'network')
        assert w.call('network.configure_wifi', False, str(project)) is True         # off takes 5 GHz with it
        assert card_extras.load_wifi(str(project)) == {'enabled': False, 'band5': False}
        assert w.state('network')['wifi_band5'] is False
    js = (Path(wifi_card.__file__).parents[1] / 'webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    assert 'n.wifi_band_details' in js and 'Also use the newer adapter driver' in js
