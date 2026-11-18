"""PAD-1436: a Send whose connection drops part way (a machine reached over the internet) connects again and does
the cut-off step again, instead of ending in "Unexpected error: Server connection dropped".

The machine's connection is a stand-in here (no paramiko); the real drop - the server's session killed under a
Send - is proven on the emulator stand-in (docs/plans/send-to-machine.md)."""

import os
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.core import remote_send as R


class FakeTransport:
    def __init__(self):
        self.up = True

    def is_active(self):
        return self.up

    def close(self):
        self.up = False


class FakeFile:
    def __init__(self, sftp, path):
        self.sftp, self.path = sftp, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_pipelined(self, on):
        pass

    def seek(self, off):
        self.at = off

    def write(self, data):
        self.sftp.machine.on_write(self.sftp, self.path, self.at, data)
        self.at += len(data)

    def flush(self):
        pass


class FakeSftp:
    def __init__(self, machine, t):
        self.machine, self.t = machine, t

    def open(self, path, mode):
        if not self.t.up:
            raise EOFError()
        return FakeFile(self, path)

    def putfo(self, fileobj, path, file_size=0, callback=None, confirm=True):
        data = b""
        while True:
            b = fileobj.read(7)
            if not b:
                break
            data += b
            self.machine.on_put(self, path, data)
        self.machine.files[path] = data

    def chown(self, *a):
        pass

    def chmod(self, *a):
        pass

    def close(self):
        pass


class DroppingMachine(R.SshMachine):
    """An SshMachine whose connection is a stand-in that can be dropped at a chosen moment."""

    def __init__(self, boot="boot-1", drop_after=None, redial_fails=0):
        self.host, self.port, self._timeout = "pin.example", 22, 15
        self.files, self.logs, self.dials, self.scripts = {}, [], 0, []
        self.drop_after = drop_after          # writes before the connection drops (once)
        self.redial_fails = redial_fails
        self.boot_now = boot
        self.rehold = "PAD_SEND_HELD"
        self.log = lambda m, level="info": self.logs.append((level, m))
        self._dial()
        self._boot = boot
        self.writes = 0

    def _dial(self):
        self.dials += 1
        if self.dials > 1 and self.redial_fails:
            self.redial_fails -= 1
            raise R.Unreachable("nothing answered")
        self.t = FakeTransport()
        self.sftp = FakeSftp(self, self.t)

    def drop(self):
        self.t.up = False
        raise EOFError()

    def on_write(self, sftp, path, off, data):
        if not sftp.t.up:
            raise EOFError()
        self.writes += 1
        if self.drop_after is not None and self.writes > self.drop_after:
            self.drop_after = None
            self.drop()
        buf = bytearray(self.files.get(path, b""))
        buf[off:off + len(data)] = data
        self.files[path] = bytes(buf)

    def on_put(self, sftp, path, sofar):
        if self.drop_after is not None and len(sofar) > self.drop_after:
            self.drop_after = None
            self.drop()

    def sh(self, script, stdin=b"", timeout=600, check=True):
        if not self.t.up:
            raise EOFError()
        self.scripts.append(script)
        if "boot_id" in script:
            return 0, self.boot_now + "\n"
        if "PAD_SEND_GONE" in script:
            return 0, self.rehold + "\n"
        return 0, ""


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(R, "RECONNECT_WAITS", (0.01,))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)


def test_a_dropped_connection_mid_update_connects_again_and_finishes_the_write():
    m = DroppingMachine(drop_after=2)
    m.files["/games/a"] = b"." * 40
    m.write_ranges("/games/a", [(0, b"AAAA"), (10, b"BBBB"), (20, b"CCCC"), (30, b"DDDD")])
    assert m.files["/games/a"] == b"AAAA......BBBB......CCCC......DDDD......"
    assert m.dials == 2
    assert any(level == "warning" and "connection to the machine dropped" in msg for level, msg in m.logs)
    assert any("Connected again" in msg for _level, msg in m.logs)


def test_an_upload_cut_off_is_sent_again_from_its_first_byte():
    m = DroppingMachine(drop_after=10)

    class Tree:
        def chunks(self, node):
            yield 0, b"0123456789abcdefghij"
    m.upload("/games/b", R._ChunkFile(Tree(), {}), 20, 0o644, 0, 0)
    assert m.files["/games/b"] == b"0123456789abcdefghij"
    assert m.dials == 2


def test_the_boot_partition_copy_cut_off_starts_again_whole():
    f = R._RawFile(lambda: iter([(0, b"abc"), (3, b"def")]))
    assert f.read() + f.read() == b"abcdef"
    f.rewind()
    assert f.read() == b"abc"


def test_a_machine_that_answers_again_after_a_few_tries_is_carried_on_with():
    m = DroppingMachine(drop_after=0, redial_fails=3)
    m.files["/games/a"] = b"...."
    m.write_ranges("/games/a", [(0, b"AB")])
    assert m.files["/games/a"] == b"AB.."
    assert m.dials == 5


def test_a_machine_that_never_answers_again_ends_the_send_with_a_plain_reason(monkeypatch):
    monkeypatch.setattr(R, "RECONNECT_FOR", 0.05)
    m = DroppingMachine(drop_after=0, redial_fails=10 ** 6)
    with pytest.raises(R.SendError, match="didn't answer again.*picks up where this one stopped"):
        m.write_ranges("/games/a", [(0, b"AB")])


def test_a_machine_that_restarted_meanwhile_is_not_carried_on_with():
    m = DroppingMachine(drop_after=0)
    m.boot_now = "boot-2"
    with pytest.raises(R.SendError, match="restarted while the Send"):
        m.write_ranges("/games/a", [(0, b"AB")])


def test_cancel_while_reconnecting_stops_the_send(monkeypatch):
    m = DroppingMachine(drop_after=0, redial_fails=10 ** 6)
    m.cancel = lambda: m.dials > 2
    with pytest.raises(R.SendError, match="canceled"):
        m.write_ranges("/games/a", [(0, b"AB")])


def test_an_error_on_a_live_connection_is_not_retried():
    m = DroppingMachine()
    m.sftp.open = lambda *a: (_ for _ in ()).throw(PermissionError("read-only"))
    with pytest.raises(PermissionError):
        m.write_ranges("/games/a", [(0, b"AB")])
    assert m.dials == 1


def test_the_game_hold_is_put_back_after_a_reconnect(monkeypatch):
    m = DroppingMachine(drop_after=0)
    m._paused = True
    m.rehold = "PAD_SEND_RESUMED"                 # its watchdog gave the game back while PAD was away
    held = []

    class Stop:
        def set(self):
            held.append("old heartbeat stopped")
    m._beat_stop = Stop()
    monkeypatch.setattr(m, "pause_game", lambda: held.append("held again"))
    m.files["/games/a"] = b"...."
    m.write_ranges("/games/a", [(0, b"AB")])
    assert held == ["old heartbeat stopped", "held again"]
    assert m.files["/games/a"] == b"AB.."


def test_the_steps_a_send_takes_are_all_ones_that_reconnect():
    for name in ("write_ranges", "upload", "commit", "block_hashes", "file_sha1s", "walk", "mount_part", "state",
                 "raw_write", "write_ledger", "copy", "truncate", "set_attrs", "set_mtime", "remount", "mkdir"):
        assert getattr(R.SshMachine, name).__code__ is R._again(lambda: 0).__code__, name
    for name in ("reboot", "restart_game", "pause_game", "resume_game", "sh"):
        assert getattr(R.SshMachine, name).__code__ is not R._again(lambda: 0).__code__, name


# ------------------------------------------------------------------ the machine-side scripts, done twice
needs_sh = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs a POSIX sh")


class ScriptMachine(R.SshMachine):
    def __init__(self):
        self.ran = []

    def sh(self, script, stdin=b"", timeout=600, check=True):
        p = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
        if check and p.returncode:
            raise R.SendError(p.stderr)
        return p.returncode, p.stdout


@needs_sh
def test_a_rename_done_again_after_a_drop_finds_it_done(tmp_path):
    tmp, final = tmp_path / ".a.pad-send", tmp_path / "a"
    tmp.write_bytes(b"new")
    final.write_bytes(b"old")
    m = ScriptMachine()
    m.commit([(str(tmp), str(final))], [], [])
    m.commit([(str(tmp), str(final))], [], [])       # the answer was lost: done again
    assert final.read_bytes() == b"new" and not tmp.exists()


@needs_sh
def test_a_rename_with_its_copy_missing_and_nothing_in_place_still_fails(tmp_path):
    m = ScriptMachine()
    with pytest.raises(R.SendError):
        m.commit([(str(tmp_path / ".a.pad-send"), str(tmp_path / "a"))], [], [])


def _rehold(w):
    return subprocess.run(["sh", "-c", R.REHOLD_SCRIPT.replace("@W@", str(w))], capture_output=True,
                          text=True, check=True).stdout.strip()


@needs_sh
def test_rehold_script_tells_each_state_apart(tmp_path):
    assert _rehold(tmp_path / "gone") == "PAD_SEND_GONE"
    w = tmp_path / "w"
    w.mkdir()
    (w / "fns").write_text("pids_named() { :; }\n")
    (w / "watch").write_text("exit 0\n")
    assert _rehold(w) == "PAD_SEND_HELD"
    assert (w / "alive").exists()
    (w / "done").touch()
    assert _rehold(w) == "PAD_SEND_RESUMED"          # the watchdog gave the game back: no monitor left
    (w / "monitor").write_text("123\n")
    assert _rehold(w) == "PAD_SEND_WATCHING"         # it gave up with the card changing: watched again
    assert not (w / "done").exists()
    assert os.path.exists(w / "alive")
