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
    svc = w.window.service('extras')
    assert svc is not None
    w.run(svc.on_show)
    return project, svc


@pytest.mark.parametrize('era', ['spike2', 'spike3'])
def test_sidebar_and_project_persistence(tmp_path, monkeypatch, era):
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = era
        project, svc = ready(w, tmp_path, monkeypatch)
        rail = w.state('shell')['tabs']
        entry = next(t for t in rail if t['ns'] == 'extras')
        assert entry['group'] == 'Replace' and entry['label'] == 'Extras' and entry['visible']
        assert not staged_changes.load(str(project)).get('extras')
        w.call('extras.configure', True, key(), str(project))
        assert card_extras.configuration(str(project))['enabled']
        w.call('extras.configure', False, key(), str(project))
        assert not card_extras.configuration(str(project))['enabled']
        assert w.state('extras')['public_keys'].strip() == key()
        other = tmp_path / 'other'; other.mkdir()
        w.run(w.window.write_assets_var.set, str(other))
        w.run(svc.on_project, str(other))
        assert not w.state('extras')['enabled'] and not w.state('extras')['public_keys']
        assert w.call('extras.configure', True, key(), str(project)) is False
        assert card_extras.load(str(other)) is None


def test_invalid_key_blocks_effective_config_and_does_not_echo(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        assert w.call('extras.configure', True, 'ssh-ed25519 AAAA invalid', str(project)) is False
        assert w.state('extras')['error']
        with pytest.raises(card_extras.ExtrasError):
            card_extras.configuration(str(project))
        assert 'AAAA' not in w.state('extras')['error']


def test_running_and_unsupported_are_locked(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        w.run(svc.on_running, True, 'write')
        assert w.call('extras.configure', True, key(), str(project)) is False
        w.run(svc.on_running, False, 'write')
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=False, reason='Unqualified platform', enabled=False, public_keys=''))
        w.run(svc.on_show)
        assert not w.state('extras')['supported']
        assert w.call('extras.configure', True, key(), str(project)) is False
        assert card_extras.load(str(project)) is None


def test_private_key_error_prevents_build_dispatch(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        w.call('extras.configure', True, key(), str(project))
        assert w.call('extras.configure', True, '-----BEGIN OPENSSH PRIVATE KEY-----', str(project)) is False
        w.run(w.app._start_write)
        assert w.asked[-1]['title'] == 'SSH Extras'
        assert 'private' in w.asked[-1]['message'].lower()


def test_disabling_ssh_is_pending_when_source_has_it_enabled(tmp_path, monkeypatch):
    from tests.test_webui_write import wait_for
    with web_app(tmp_path, mfr='stern') as w:
        project, svc = ready(w, tmp_path, monkeypatch)
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda *a, **kw: dict(
            supported=True, reason='', enabled=True, public_keys=key() + '\n'))
        (project / '.checksums.md5').write_text('')
        assert w.call('extras.configure', False, key(), str(project))
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
        assert w.call('extras.configure', False, key(), str(project))
        w.call('ui.select_tab', 'write')
        assert wait_for(w, lambda: not w.state('write')['scanning'])
        assert w.state('write')['count'] == 1
        w.call('ui.select_tab', 'extras')
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
        assert w.call('extras.configure', not source_enabled, key(), str(project))
        assert w.call('shellx.reset_open')
        rows = w.state('shellx')['reset']['rows']
        assert any(row['key'] == 'extras' and row['n'] == 1 for row in rows)
        w.answers.extend(['yes', 'ok'])
        assert w.call('shellx.reset_run', [row['key'] for row in rows])
        assert wait_for(w, lambda: not w.window._running
                        and w.state('extras')['enabled'] is source_enabled
                        and w.state('extras')['public_keys'] == source_keys)
        assert card_extras.load(str(project)) is None
        assert w.state('extras')['enabled'] is source_enabled
        assert w.state('extras')['public_keys'] == source_keys
        assert w.state('extras')['error'] == ''
