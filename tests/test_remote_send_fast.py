"""PAD-1467: Send to machine puts a big file's bytes over a plain connection (SshMachine._put_fast), because
encrypting on the machine is what holds a Send back.  The encrypted connection stays the fallback, and the Send's own
sha1 check of every uploaded file stays the judge of what arrived."""
import io
import socket

import pytest

from pinball_decryptor.core import remote_send as R


class Stat:
    def __init__(self, size):
        self.st_size = size


class Sftp:
    def __init__(self, m):
        self.m = m

    def stat(self, path):
        return Stat(len(self.m.files[path]))

    def putfo(self, fileobj, path, file_size=0, callback=None, confirm=True):
        self.m.files[path] = fileobj.read()
        self.m.encrypted.append(path)


class Sock:
    def __init__(self, m, fail=None, drop=0):
        self.m, self.fail, self.drop, self.buf = m, fail, drop, bytearray()

    def settimeout(self, t):
        pass

    def sendall(self, data):
        if self.fail:
            raise OSError(self.fail)
        self.buf += data

    def shutdown(self, how):
        assert how == socket.SHUT_WR

    def close(self):
        # the machine's listener writes what arrived to the file it was started for
        if self.m.listening:
            self.m.files[self.m.listening] = bytes(self.buf[:len(self.buf) - self.drop])
            self.m.listening = None


def machine(monkeypatch, listen=True, connect=None, fail=None, drop=0):
    m = object.__new__(R.SshMachine)
    m.host, m.port, m._lanes = "192.168.4.77", 22, []
    m.files, m.encrypted, m.scripts, m.listening, m.said = {}, [], [], None, []
    m.sftp = Sftp(m)
    m.log = lambda text, level="info": m.said.append(text)

    def sh(script, stdin=b"", timeout=600, check=True):
        m.scripts.append(script)
        if "nc -l -p" in script:
            if not listen:
                return 1, ""
            m.listening = script.split(" > ")[1].split(" ")[0].strip("'\"")
            return 0, "listening\n"
        if "rm -f" in script and "nc -l" not in script and script.rstrip().endswith(tuple(m.files)) is False:
            pass
        return 0, ""
    m.sh = sh
    dials = []

    def dial(addr, timeout=None):
        dials.append(addr)
        if connect:
            raise OSError(connect)
        return Sock(m, fail, drop)
    monkeypatch.setattr(socket, "create_connection", dial)
    m.dials = dials
    return m


BIG = bytes(range(256)) * (R.FAST_MIN // 256 + 64)


def test_a_big_file_goes_over_the_plain_connection_and_says_so_once(monkeypatch):
    m = machine(monkeypatch)
    seen = []
    m._put("/games/.x.pad-send", io.BytesIO(BIG), len(BIG), lambda done, total: seen.append((done, total)))
    assert m.files["/games/.x.pad-send"] == BIG and m.encrypted == []
    assert m.dials == [("192.168.4.77", R.FAST_PORTS[0])]          # the machine's address, not the login's port
    assert seen[-1] == (len(BIG), len(BIG)) and len(seen) >= 4       # progress about every megabyte
    assert m._plain is True and len(m.said) == 1 and "plain connection" in m.said[0] and "hash" in m.said[0]
    # the listener was started for this file alone, and stopped afterwards
    assert "nc -l -p %d > /games/.x.pad-send" % R.FAST_PORTS[0] in m.scripts[0]
    assert R.FAST_PIDFILE in m.scripts[-1]
    m._put("/games/.y.pad-send", io.BytesIO(BIG), len(BIG))
    assert m.files["/games/.y.pad-send"] == BIG and len(m.said) == 1


def test_a_small_file_stays_on_the_encrypted_connection(monkeypatch):
    m = machine(monkeypatch)
    small = b"x" * (R.FAST_MIN - 1)
    m._put("/games/.s.pad-send", io.BytesIO(small), len(small))
    assert m.encrypted == ["/games/.s.pad-send"] and m.dials == [] and m._plain is None


@pytest.mark.parametrize("kw,why", [(dict(listen=False), "could not listen"),
                                    (dict(connect="timed out"), "timed out"),
                                    (dict(fail="connection reset"), "connection reset"),
                                    (dict(drop=7), "arrived")])
def test_when_the_plain_connection_fails_the_encrypted_one_takes_the_file_and_the_rest(monkeypatch, kw, why):
    m = machine(monkeypatch, **kw)
    m._put("/games/.x.pad-send", io.BytesIO(BIG), len(BIG))
    assert m.files["/games/.x.pad-send"] == BIG and m.encrypted == ["/games/.x.pad-send"]      # whole, from the start
    assert m._plain is False and len(m.said) == 1 and why in m.said[0] and "encrypted" in m.said[0]
    dials = len(m.dials)
    m._put("/games/.y.pad-send", io.BytesIO(BIG), len(BIG))
    assert m.encrypted[-1] == "/games/.y.pad-send" and len(m.dials) == dials and len(m.said) == 1  # not tried again


def test_a_cancel_stops_the_listener_and_takes_the_part_file_away(monkeypatch):
    m = machine(monkeypatch)

    def cancel(done, total):
        raise R.SendError("Send canceled.")
    with pytest.raises(R.SendError, match="canceled"):
        m._put("/games/.x.pad-send", io.BytesIO(BIG), len(BIG), cancel)
    assert m.encrypted == [] and m._plain is None                  # a cancel is not a failed connection
    assert "rm -f /games/.x.pad-send" in m.scripts[-1] and R.FAST_PIDFILE in m.scripts[-1]


def test_the_plain_connection_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("PAD_SEND_PLAIN", "0")
    m = machine(monkeypatch)
    m._put("/games/.x.pad-send", io.BytesIO(BIG), len(BIG))
    assert m.encrypted == ["/games/.x.pad-send"] and m.dials == [] and m.said == []


def test_the_send_checks_a_plain_upload_by_hash_like_any_other():
    """Nothing about the plain path is trusted: the fake machine's corrupt upload is the same check a tampered
    plain connection would meet (tests/test_remote_send.py covers the refusal itself)."""
    import inspect
    src = inspect.getsource(R.send)
    assert "machine.state(" in src and "op.sha1" in src
    assert "machine.state(" in inspect.getsource(R.sync)


def test_a_send_of_start_up_files_restarts_the_machine_not_just_the_game():
    """PAD-1467: the Wi-Fi files, the adapter driver and the script that starts the game are read at start-up."""
    from pinball_decryptor.core import remote_buttons, remote_send, wifi_card
    for path in (wifi_card.OVERRIDE, wifi_card.MODULE, wifi_card.HELPER, wifi_card.INIT, wifi_card.LINK,
                 remote_buttons.SO, remote_buttons.MONITOR):
        assert remote_send.boot_only(path), path
    for path in ('/games/godzilla_le/game', '/usr/local/padmode/mode.so', '/etc/init.d/sshd', '/etc/wpa_supplicant'):
        assert not remote_send.boot_only(path), path
    import inspect
    src = inspect.getsource(remote_send.send)
    assert 'boot_only(op.path) for op in needed' in src and src.index('boot_only(') < src.index('machine.resume_game()')
