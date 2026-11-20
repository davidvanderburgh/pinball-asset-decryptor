"""PAD-1465: a Send's big writes go over plain TCP into the machine's helper (padpieces recv), not through SSH.

On a Godzilla (ARMv7, dropbear offering only AES-CTR + HMAC-SHA2-256) SSH topped out at 3.1-5.5 MB/s with the wide
window and two lanes; the raw lanes did 7.4-7.9 MB/s.  Every frame is signed with a key that went over SSH and is
checked on the machine before a byte of it is written.  These tests drive the REAL helper (padpieces.c, compiled for
this computer) where a C compiler and POSIX sockets are at hand, and the fallback to SSH everywhere."""
import hashlib
import hmac
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from pinball_decryptor.core import remote_send as R

SRC = Path(R.__file__).resolve().parent.parent / "resources" / "pieces" / "padpieces.c"
CC = shutil.which("cc") or shutil.which("gcc")
needs_cc = pytest.mark.skipif(sys.platform == "win32" or CC is None, reason="needs a C compiler and POSIX sockets")


@pytest.fixture(scope="module")
def helper(tmp_path_factory):
    out = tmp_path_factory.mktemp("padpieces") / "padpieces"
    subprocess.run([CC, "-O2", "-Wall", "-Wextra", "-Wno-unused-result", "-o", str(out), str(SRC)],
                   check=True)
    return str(out)


class Chan:
    """An SSH session's stand-in: the command runs here, as the machine would run it."""

    def __init__(self, log):
        self.proc, self.log = None, log

    def settimeout(self, t):
        pass

    def exec_command(self, cmd):
        self.log.append(cmd)
        self.proc = subprocess.Popen(cmd.split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def sendall(self, b):
        self.proc.stdin.write(b)
        self.proc.stdin.flush()

    def shutdown_write(self):
        self.proc.stdin.close()

    def recv(self, n):
        return os.read(self.proc.stdout.fileno(), n)

    def close(self):
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc.stdout.close()


class T:
    def __init__(self):
        self.cmds, self.chans = [], []

    def open_session(self):
        c = Chan(self.cmds)
        self.chans.append(c)
        return c

    def is_active(self):
        return True


class Sftp:
    """Real files, as SFTP would write them."""

    def __init__(self):
        self.putfo_paths = []

    def open(self, path, mode):
        return open(path, mode)

    def stat(self, path):
        return os.stat(path)

    def putfo(self, fileobj, path, file_size=0, callback=None, confirm=True):
        self.putfo_paths.append(path)
        with open(path, "wb") as f:
            shutil.copyfileobj(fileobj, f)


def machine(helper_path):
    m = object.__new__(R.SshMachine)
    m.host, m.port, m.t, m.sftp = "127.0.0.1", 22, T(), Sftp()
    m._lanes, m._parked, m._wide, m._wide_port, m._widened = [], None, None, None, False
    m._pieces = helper_path
    m.said = []
    m.log = lambda text, kind="info": m.said.append(text)
    return m


@pytest.fixture
def small_frames(monkeypatch):
    monkeypatch.setattr(R, "_LOOPBACK_OK", True)
    monkeypatch.setattr(R, "RAW_FRAME", 64 << 10)
    monkeypatch.setattr(R, "RAW_MIN", 1 << 20)
    monkeypatch.delenv("PAD_SEND_RAW", raising=False)


@needs_cc
def test_a_big_file_goes_over_two_raw_lanes_and_arrives_exact(helper, tmp_path, small_frames):
    m = machine(helper)
    data = os.urandom(5 * (1 << 20) + 12345)
    path = str(tmp_path / "game.asset")
    seen = []
    m._put(path, __import__("io").BytesIO(data), len(data), callback=lambda done, total: seen.append(done))
    assert Path(path).read_bytes() == data
    assert sum(c.endswith(" recv") for c in m.t.cmds) == R.RAW_LANES
    assert m.sftp.putfo_paths == []                 # nothing went over SSH
    assert seen[-1] == len(data)
    assert any("direct connection" in s for s in m.said)


@needs_cc
def test_scattered_ranges_land_in_place_and_the_file_is_never_cut_short(helper, tmp_path, small_frames):
    m = machine(helper)
    path = tmp_path / "card.img"
    old = os.urandom(4 << 20)
    path.write_bytes(old)
    new = bytearray(old)
    ranges = []
    for off in (3 << 20, 17, 1 << 20, (2 << 20) + 5):
        piece = os.urandom(300000)
        new[off:off + len(piece)] = piece
        ranges.append((off, piece))
    ranges.append((0, os.urandom(1 << 20)))
    new[0:1 << 20] = ranges[-1][1]
    m.write_ranges(str(path), ranges)
    assert path.read_bytes() == bytes(new)
    assert not getattr(m, "_raw_off", False)


def _start(helper_path, key):
    proc = subprocess.Popen([helper_path, "recv"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    proc.stdin.write(key.hex().encode() + b"\n")
    proc.stdin.close()
    port = int(proc.stdout.readline().split()[1])
    return proc, port


def _hello(key):
    return hmac.new(key, R.RAW_HELLO, hashlib.sha1).digest()


@needs_cc
def test_a_tampered_frame_is_refused_before_a_byte_of_it_is_written(helper, tmp_path):
    key = os.urandom(32)
    proc, port = _start(helper, key)
    target = tmp_path / "x"
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(_hello(key))
    head, mac = R.raw_frame(key, 0, "W", str(target).encode(), 0, b"A" * 1000)
    s.sendall(head + b"B" * 1000 + mac)          # the bytes changed on the way
    reply = s.recv(200)
    s.close()
    assert proc.wait(timeout=10) == 1
    assert reply.startswith(b"err bad signature")
    assert not target.exists()


@needs_cc
def test_frames_replayed_out_of_order_are_refused(helper, tmp_path):
    key = os.urandom(32)
    proc, port = _start(helper, key)
    target = tmp_path / "y"
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(_hello(key))
    head, mac = R.raw_frame(key, 1, "W", str(target).encode(), 0, b"later")   # frame 1 sent as the first
    s.sendall(head + b"later" + mac)
    assert s.recv(200).startswith(b"err bad signature")
    s.close()
    assert proc.wait(timeout=10) == 1
    assert not target.exists()


@needs_cc
def test_a_stranger_connecting_first_is_dropped_and_the_send_still_gets_in(helper, tmp_path):
    key = os.urandom(32)
    proc, port = _start(helper, key)
    stranger = socket.create_connection(("127.0.0.1", port))
    stranger.sendall(b"\0" * 20)                  # doesn't know the key
    assert stranger.recv(10) == b""               # dropped
    stranger.close()
    target = tmp_path / "z"
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(_hello(key))
    head, mac = R.raw_frame(key, 0, "W", str(target).encode(), 4, b"data")
    s.sendall(head + b"data" + mac)
    head, mac = R.raw_frame(key, 1, "E")
    s.sendall(head + mac)
    assert s.recv(200) == b"ok 4\n"
    s.close()
    assert proc.wait(timeout=10) == 0
    assert target.read_bytes() == b"\0\0\0\0data"


def test_no_helper_on_the_machine_sends_over_ssh_and_says_so(tmp_path, small_frames):
    m = machine("/nonexistent/padpieces")
    m.t = T()

    def broken():
        raise OSError("no session")
    m.t.open_session = broken
    data = os.urandom(2 << 20)
    path = str(tmp_path / "f")
    m._put(path, __import__("io").BytesIO(data), len(data))
    assert Path(path).read_bytes() == data
    assert m.sftp.putfo_paths == [path]
    assert m._raw_off
    assert any("usual one" in s for s in m.said)
    m.sftp.putfo_paths.clear()
    m._put(path, __import__("io").BytesIO(data), len(data))   # and the rest of the Send doesn't try again
    assert m.sftp.putfo_paths == [path]


def test_pad_send_raw_0_keeps_every_byte_on_ssh(tmp_path, small_frames, monkeypatch):
    monkeypatch.setenv("PAD_SEND_RAW", "0")
    m = machine("/run/pad-pieces-1")
    data = os.urandom(2 << 20)
    path = str(tmp_path / "f")
    m._put(path, __import__("io").BytesIO(data), len(data))
    assert m.t.cmds == []
    assert m.sftp.putfo_paths == [path]


def test_small_writes_stay_on_ssh(tmp_path, small_frames):
    m = machine("/run/pad-pieces-1")
    data = os.urandom(1000)
    path = str(tmp_path / "f")
    m._put(path, __import__("io").BytesIO(data), len(data))
    assert m.t.cmds == []


def test_raw_lanes_only_on_the_home_network():
    assert R._home_network("192.168.4.145")
    assert R._home_network("10.0.0.7")
    assert not R._home_network("8.8.8.8")                 # a forwarded port over the internet
    assert not R._home_network("100.97.146.125")          # a tunnel's address (Tailscale's shared range)
    assert not R._home_network("127.0.0.1")


def test_a_machine_over_the_internet_keeps_every_byte_on_ssh(tmp_path, small_frames, monkeypatch):
    m = machine("/run/pad-pieces-1")
    m.host = "8.8.8.8"
    data = os.urandom(2 << 20)
    path = str(tmp_path / "f")
    m._put(path, __import__("io").BytesIO(data), len(data))
    assert m.t.cmds == []
    assert m.sftp.putfo_paths == [path]


def test_frame_layout_matches_the_helper():
    key = b"k" * 32
    head, mac = R.raw_frame(key, 7, "W", b"/games/a", 0x0102030405, b"xyz")
    assert head == struct.pack(">BQII", ord("W"), 0x0102030405, 3, 8) + b"/games/a"
    want = hmac.new(key, struct.pack(">Q", 7) + head[:17] + b"/games/a" + b"xyz", hashlib.sha1).digest()
    assert mac == want
