"""PAD-1434: a Send over a machine's Wi-Fi was held to ~1.4 MB/s by dropbear's 24 KB receive window.

Cards set up from now on start their listener with ``-W 4194304``; a card set up before gets a temporary wide
listener for the Send (same arguments, another port), checked to be the same machine and stopped at the end, and big
files go over two connections at once.  Measured on a Godzilla: upload 1.55 -> 3.6 MB/s, block writes 1.2-1.6 ->
3.2-3.65 MB/s."""
import io
import threading
from pathlib import Path

import pytest

from pinball_decryptor.core import remote_send as R

OLD_ARGS = ["/usr/local/bin/dropbear", "-P", "/var/run/pad-sshd.pid", "-r", "/data/dropbear/dropbear_rsa_host_key",
            "-r", "/data/dropbear/dropbear_ed25519_host_key"]
ID = ("ssh-ed25519", "AAAAthismachine")


class FakeFile:
    def __init__(self, store, lock, who):
        self.store, self.lock, self.who, self.pos = store, lock, who, 0

    def set_pipelined(self, on):
        pass

    def seek(self, off):
        self.pos = off

    def write(self, data):
        if self.who.get("fail_after") is not None and self.who["writes"] >= self.who["fail_after"]:
            raise OSError("no room")
        with self.lock:
            end = self.pos + len(data)
            if len(self.store) < end:
                self.store.extend(b"\0" * (end - len(self.store)))
            self.store[self.pos:end] = data
        self.who["writes"] += 1
        self.pos = end

    def flush(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSftp:
    def __init__(self, store, lock):
        self.store, self.lock, self.who = store, lock, {"writes": 0, "fail_after": None}

    def open(self, path, mode):
        if "w" in mode:
            del self.store[:]
        return FakeFile(self.store, self.lock, self.who)

    def stat(self, path):
        class S:
            st_size = len(self.store)
        return S()


class Lane:
    def __init__(self, port, sftp):
        self.port, self.sftp, self.t, self.closed = port, sftp, _T("t%d" % port), False

    def close(self):
        self.closed = True


class _T(str):
    """A connection's stand-in: its name, and whether it is still up (PAD-1436 asks)."""
    up = True

    def is_active(self):
        return self.up


def machine(args=OLD_ARGS, start_rc=0):
    m = object.__new__(R.SshMachine)
    m.host, m.port, m.identity = "10.0.0.5", 22, ID
    m._lanes, m._parked, m._wide, m._wide_port = [], None, None, None
    m.store, lock = bytearray(), threading.Lock()
    m.t, m.sftp = _T("t22"), FakeSftp(m.store, lock)
    m.lock, m.scripts = lock, []

    def sh(script, stdin=b"", timeout=600, check=True):
        m.scripts.append((m.t, script))
        if "/proc/$p/cmdline" in script and "tr '\\000' '\\n'" in script:
            return 0, "\n".join(args) + ("\n" if args else "")
        if " -W 4194304" in script and script.startswith("/usr/local/bin/dropbear"):
            return start_rc, "" if start_rc == 0 else "Error listening: Address already in use"
        return 0, ""
    m.sh = sh
    return m


def lanes_from(m, made, fail=False):
    def connect_lane(host, port, identity):
        assert (host, identity) == (m.host, ID), "a lane must be checked against the machine's own identity"
        if fail:
            raise R.SendError("10.0.0.5:%d is not the machine this computer is sending to." % port)
        lane = Lane(port, FakeSftp(m.store, m.lock))
        made.append(lane)
        return lane
    return connect_lane


def test_new_cards_start_their_listener_with_the_wide_window():
    script = (Path(R.__file__).parents[1] / "resources" / "ssh" / "sshd").read_text()
    assert '"$DAEMON" -P "$PIDFILE" -W 4194304' in script


@pytest.mark.parametrize("args, want", [
    (OLD_ARGS, 24576), (OLD_ARGS + ["-W", "4194304"], 4194304), (OLD_ARGS + ["-W65536"], 65536)])
def test_the_listeners_window_is_read_from_its_arguments(args, want):
    assert R._window(args) == want


def test_an_old_card_gets_a_temporary_wide_listener_that_the_send_stops(monkeypatch):
    m, made, logs = machine(), [], []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    assert m.widen(lambda t, k="info": logs.append(t)) is True
    start = [s for _t, s in m.scripts if s.startswith("/usr/local/bin/dropbear")]
    # the machine's own listener's arguments, its own pidfile swapped for the temporary one's, another port
    assert start == ["/usr/local/bin/dropbear -r /data/dropbear/dropbear_rsa_host_key -r "
                     "/data/dropbear/dropbear_ed25519_host_key -p 2222 -P /var/run/pad-sshd-send.pid -W 4194304 2>&1"]
    assert any(s == R.WIDE_STOP for _t, s in m.scripts[:3]), "a stale temporary listener is stopped first"
    assert [l.port for l in made] == [2222, 2222] and m.t == "t2222" and m._parked[0] == "t22"
    assert logs == ["Sending over two connections at once with a wider window."]
    m.scripts.clear()
    m.close()
    assert m.scripts == [("t2222", R.WIDE_STOP)] and all(l.closed for l in made)
    assert m.t == "t22" and m._wide_port is None and m._lanes == []


def test_a_card_already_wide_gets_its_second_connection_on_its_own_port(monkeypatch):
    m, made = machine(OLD_ARGS + ["-W", "4194304"]), []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    assert m.widen() is True
    assert not any(s.startswith("/usr/local/bin/dropbear") for _t, s in m.scripts)
    assert [l.port for l in made] == [22] and m._lanes[0] is m and m.t == "t22" and m._wide_port is None
    m.close()
    assert made[0].closed and not any(s == R.WIDE_STOP for _t, s in m.scripts)


@pytest.mark.parametrize("case", ["other machine", "no port", "not PADs listener"])
def test_anything_failing_leaves_the_send_on_its_own_connection(monkeypatch, case):
    m, made, logs = machine([] if case == "not PADs listener" else OLD_ARGS,
                            start_rc=1 if case == "no port" else 0), [], []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made, fail=case == "other machine"))
    assert m.widen(lambda t, k="info": logs.append(t)) is False
    assert m.t == "t22" and m._parked is None and m._lanes == [] and m._wide_port is None
    if case == "not PADs listener":
        assert logs == []
    else:
        assert logs and logs[0].startswith("A faster connection didn't start")
    if case == "other machine":
        assert m.scripts[-1] == ("t22", R.WIDE_STOP), "the listener it started is stopped again"


def test_big_files_go_over_both_connections_and_arrive_whole(monkeypatch):
    m, made = machine(), []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    m.widen()
    data = bytes(range(256)) * ((5 << 20) // 256 + 7)
    seen = []
    m._put("/games/x.bin", io.BytesIO(data), len(data), lambda d, total: seen.append((d, total)))
    assert bytes(m.store) == data and seen[-1] == (len(data), len(data))
    assert all(l.sftp.who["writes"] > 0 for l in made), "both connections carried pieces"
    ranges = [(i << 20, bytes([i]) * (1 << 20)) for i in (0, 2, 4, 5)]
    m.write_ranges("/games/x.bin", ranges)
    for off, d in ranges:
        assert bytes(m.store[off:off + len(d)]) == d


def test_a_lane_that_stops_raises_instead_of_hanging(monkeypatch):
    m, made = machine(), []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    m.widen()
    made[1].sftp.who["fail_after"] = 0
    with pytest.raises(R.SendError, match="stopped taking"):
        m._put("/games/x.bin", io.BytesIO(b"\1" * (12 << 20)), 12 << 20)


def test_small_files_stay_on_one_connection(monkeypatch):
    m, made = machine(), []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    m.widen()
    puts = []
    made[0].sftp.putfo = lambda f, path, file_size, callback, confirm: puts.append((path, file_size))
    m._put("/games/small.bin", io.BytesIO(b"x" * 100), 100)
    assert puts == [("/games/small.bin", 100)]


def test_a_lane_whose_connection_dropped_is_a_dropped_connection_not_a_refusal(monkeypatch):
    # PAD-1436 meets PAD-1434: a lane cut off with its connection raises as a dropped connection, so the Send
    # connects again and does the step again (a refusal, "stopped taking", is never retried)
    m, made = machine(), []
    monkeypatch.setattr(R, "_connect_lane", lanes_from(m, made))
    m.widen()
    made[1].sftp.who["fail_after"] = 0
    made[1].t.up = False
    with pytest.raises(Exception) as got:
        m._put("/games/x.bin", io.BytesIO(b"" * (12 << 20)), 12 << 20)
    assert not isinstance(got.value, R.SendError)
    assert not m._alive()
