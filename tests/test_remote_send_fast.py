"""PAD-1467: what this ticket added to Send to machine.  (Its own plain-connection upload was dropped for
PAD-1465's, which landed on main first: signed frames into the machine's helper, tests/test_remote_send.py.)"""
import inspect

from pinball_decryptor.core import remote_buttons, remote_send, wifi_card


def test_a_send_of_start_up_files_restarts_the_machine_not_just_the_game():
    """The Wi-Fi files, the adapter driver and the script that starts the game are read at start-up."""
    for path in (wifi_card.OVERRIDE, wifi_card.MODULE, wifi_card.HELPER, wifi_card.INIT, wifi_card.LINK,
                 remote_buttons.SO, remote_buttons.MONITOR):
        assert remote_send.boot_only(path), path
    for path in ('/games/godzilla_le/game', '/usr/local/padmode/mode.so', '/etc/init.d/sshd', '/etc/wpa_supplicant'):
        assert not remote_send.boot_only(path), path
    src = inspect.getsource(remote_send.send)
    assert 'boot_only(op.path) for op in needed' in src and src.index('boot_only(') < src.index('machine.resume_game()')


def test_the_plain_connection_of_the_live_view_and_card_backup_follows_the_sends_switch(monkeypatch):
    monkeypatch.delenv('PAD_SEND_RAW', raising=False)
    monkeypatch.delenv('PAD_SEND_PLAIN', raising=False)
    assert remote_send.plain_allowed()
    monkeypatch.setenv('PAD_SEND_RAW', '0')
    assert not remote_send.plain_allowed()
    monkeypatch.setenv('PAD_SEND_RAW', '1')
    monkeypatch.setenv('PAD_SEND_PLAIN', 'off')
    assert not remote_send.plain_allowed()
