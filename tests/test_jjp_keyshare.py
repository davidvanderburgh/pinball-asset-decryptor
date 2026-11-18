"""PAD-1416: a JJP machine lends its security key to PAD on the network.

The machine side is tools/jjp_emu/padkeyshare.py (a small USB/IP server); a
key sharing stick (plugins/jjp/keyshare.py) puts it on the machine through
the game's hot fix.  The whole loop - the real GnR system in a VM lending the
real key to PAD's attach in WSL - was proven by hand (ticket PAD-1416); these
pin the parts that can be checked anywhere.
"""
import hashlib
import importlib.util
import os
import shutil
import socket
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.jjp import custom_modes as CM
from pinball_decryptor.plugins.jjp import keyshare

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server():
    spec = importlib.util.spec_from_file_location(
        "padkeyshare", os.path.join(ROOT, "tools", "jjp_emu", "padkeyshare.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ the stick
def test_stick_carries_the_server_its_hook_and_sums(tmp_path):
    ok, lines = keyshare.write_stick(str(tmp_path), "install")
    assert ok, lines
    hot = tmp_path / "hotfix"
    src = (hot / "padkeyshare" / "padkeyshare.py").read_bytes()
    assert src == open(os.path.join(ROOT, "tools", "jjp_emu", "padkeyshare.py"), "rb").read()
    h, rel = (hot / "padkeyshare.sha256").read_text().split()
    assert rel == "padkeyshare/padkeyshare.py" and h == hashlib.sha256(src).hexdigest()
    runme = (hot / "runme.sh").read_bytes()
    assert b"\r" not in runme and b"@" not in runme.replace(b"@WRITTEN", b"")   # LF, all filled
    text = runme.decode()
    assert "ACTION=install" in text and keyshare.MARK in text
    assert "'[ -r $JJPEDIR/scripts/padkeyshare.sh ] && . $JJPEDIR/scripts/padkeyshare.sh'" in text
    assert (hot / "padkeyshare.sh").read_text() == keyshare.PADKEYSHARE_SH
    readme = (tmp_path / "PADKEYSHARE_README.txt").read_text()
    assert "Hold the LEFT FLIPPER" in readme and "leave Bus ID empty" in readme


def test_a_modes_stick_and_a_key_sharing_stick_replace_each_other(tmp_path):
    assert keyshare.write_stick(str(tmp_path), "install")[0]
    assert CM.hotfix_on(str(tmp_path)) == "pad"           # the modes tab may write over it
    (tmp_path / "hotfix" / "runme.sh").write_text("#!/bin/dash\n# PAD custom modes stick\n")
    assert keyshare.write_stick(str(tmp_path), "remove")[0]
    assert "ACTION=remove" in (tmp_path / "hotfix" / "runme.sh").read_text()


def test_someone_elses_hot_fix_is_never_written_over(tmp_path):
    (tmp_path / "hotfix").mkdir()
    (tmp_path / "hotfix" / "runme.sh").write_text("#!/bin/sh\necho theirs\n")
    ok, lines = keyshare.write_stick(str(tmp_path), "install")
    assert not ok and "not PAD's" in lines[-1]
    assert (tmp_path / "hotfix" / "runme.sh").read_text() == "#!/bin/sh\necho theirs\n"
    assert keyshare.write_stick(str(tmp_path), "wipe")[0] is False


RUNGAME = """#!/bin/bash
export JJPEDIR='/jjpe/gen1'
. $JJPEDIR/setenv.sh
$JJPEDIR/scripts/runonce.sh

while true
do
  $GAMEDIR/game
done
"""


def _posix(path):
    p = str(path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def _dash():
    """How to run the stick's runme.sh: dash, in WSL on Windows (where the
    environment does not cross, so it rides in the command)."""
    if sys.platform == "win32":
        if not shutil.which("wsl.exe"):
            pytest.skip("no WSL")
        return lambda env, script: subprocess.run(
            ["wsl.exe", "-e", "sh", "-c", " ".join("%s='%s'" % kv for kv in env.items())
             + " dash '%s'" % script], timeout=60).returncode
    if not shutil.which("dash") or not shutil.which("sha256sum"):
        pytest.skip("needs dash + sha256sum")
    return lambda env, script: subprocess.run(
        ["dash", script], env=dict(os.environ, **env), timeout=60).returncode


def test_runme_installs_once_refuses_without_the_driver_and_removes(tmp_path):
    run = _dash()
    j = tmp_path / "J"
    (j / "scripts").mkdir(parents=True)
    (j / "scripts" / "rungame.sh").write_bytes(RUNGAME.encode())
    kmods = tmp_path / "kmods"
    kmods.mkdir()
    env = {"JJPEDIR": _posix(j), "PAD_STICK_LOG": _posix(tmp_path / "log"),
           "PAD_STICK_PYTHON": "/bin/sh", "PAD_STICK_KMODS": _posix(kmods)}
    stick = tmp_path / "usb"
    stick.mkdir()
    keyshare.write_stick(str(stick), "install")
    script = _posix(stick / "hotfix" / "runme.sh")

    # no usbip-host on this "machine": refused, nothing changed
    assert run(env, script) == 1
    assert (j / "scripts" / "rungame.sh").read_bytes() == RUNGAME.encode()
    assert not (j / "padkeyshare").exists()
    assert "no usbip-host driver" in (tmp_path / "log").read_text()

    (kmods / "kernel").mkdir()
    (kmods / "kernel" / "usbip-host.ko").write_bytes(b"")
    assert run(env, script) == 0
    hooked = (j / "scripts" / "rungame.sh").read_text()
    lines = hooked.splitlines()
    at = lines.index("$JJPEDIR/scripts/runonce.sh")
    assert lines[at + 1:at + 4] == keyshare.HOOK_LINES
    assert (j / "padkeyshare" / "padkeyshare.py").exists()
    assert (j / "scripts" / "padkeyshare.sh").read_text() == keyshare.PADKEYSHARE_SH
    assert run(env, script) == 0                           # again: hooked once
    assert (j / "scripts" / "rungame.sh").read_text() == hooked

    keyshare.write_stick(str(stick), "remove")
    assert run(env, script) == 0
    assert (j / "scripts" / "rungame.sh").read_bytes() == RUNGAME.encode()
    assert not (j / "padkeyshare").exists() and not (j / "scripts" / "padkeyshare.sh").exists()


def test_the_hook_starts_the_server_outside_the_game_service():
    sh = keyshare.PADKEYSHARE_SH
    assert "systemd-run --unit=padkeyshare" in sh          # jjp.service restarting never stops it
    assert "--log /jjpe/temp/padkeyshare.log" in sh


# ----------------------------------------------------------------- the server
def _fake_sysfs(tmp_path, busid="1-4", vid="0529", pid="0001"):
    d = tmp_path / "devices" / busid
    d.mkdir(parents=True)
    for k, v in (("idVendor", vid), ("idProduct", pid), ("bcdDevice", "0434"), ("busnum", "1"),
                 ("devnum", "3"), ("speed", "12"), ("bDeviceClass", "ff"), ("bDeviceSubClass", "00"),
                 ("bDeviceProtocol", "00"), ("bConfigurationValue", "1"), ("bNumConfigurations", "1"),
                 ("bNumInterfaces", " 1")):
        (d / k).write_text(v + "\n")
    if os.name != "nt":                                    # no ':' in a Windows name; reads as 0
        i = tmp_path / "devices" / (busid + ":1.0")
        i.mkdir()
        for k, v in (("bInterfaceClass", "ff"), ("bInterfaceSubClass", "00"),
                     ("bInterfaceProtocol", "00")):
            (i / k).write_text(v + "\n")
    (d / "usbip_sockfd").write_text("")
    (d / "usbip_status").write_text("1\n")
    return str(tmp_path)


def test_only_security_keys_are_offered(tmp_path):
    ks = _server()
    root = _fake_sysfs(tmp_path)
    _fake_sysfs(tmp_path, "2-1", vid="046d", pid="c52b")    # a mouse
    assert ks.keys(root) == ["1-4"]


def test_the_device_record_is_usbip_usb_device(tmp_path):
    ks = _server()
    root = _fake_sysfs(tmp_path)
    rec = ks.device_record("1-4", root)
    assert len(rec) == 312
    f = struct.unpack(ks.DEV_FMT, rec)
    assert f[1].rstrip(b"\0") == b"1-4"
    assert f[2:6] == (1, 3, 2, 0x0529) and f[6] == 0x0001 and f[7] == 0x0434
    assert f[8] == 0xFF and f[11:] == (1, 1, 1)
    assert len(ks.device_record("1-4", root, interfaces=True)) == 316


@pytest.mark.parametrize("addr,ok", [
    ("192.168.1.20", True), ("10.0.2.2", True), ("172.16.5.1", True), ("127.0.0.1", True),
    ("169.254.3.3", True), ("fe80::1", True), ("::ffff:192.168.1.2", True),
    ("8.8.8.8", False), ("2001:4860::8888", False), ("nonsense", False)])
def test_only_the_local_network_is_answered(addr, ok):
    assert _server().local_peer(addr) is ok


def _ask(ks, srv, request):
    a, b = socket.socketpair()
    a.sendall(request)
    try:
        srv.handle(b, "192.168.1.9")
    finally:
        b.close()
    a.settimeout(2)
    out = b""
    while True:
        part = a.recv(4096)
        if not part:
            break
        out += part
    a.close()
    return out


@pytest.fixture
def server(tmp_path, monkeypatch):
    ks = _server()
    root = _fake_sysfs(tmp_path)
    lent, back = [], []
    monkeypatch.setattr(ks, "lend", lambda b, r=None: lent.append(b) or True)
    monkeypatch.setattr(ks, "give_back", lambda b, r=None: back.append(b))
    srv = ks.Server(port=0, root=root, host="127.0.0.1")
    srv.calls = (lent, back)
    yield ks, srv, tmp_path
    srv.sock.close()


def test_the_device_list_names_the_key(server):
    ks, srv, _ = server
    out = _ask(ks, srv, struct.pack("!HHI", ks.VERSION, ks.OP_REQ_DEVLIST, 0))
    assert struct.unpack("!HHII", out[:12]) == (ks.VERSION, ks.OP_REP_DEVLIST, 0, 1)
    assert out[12 + 256:12 + 256 + 3] == b"1-4" and len(out) == 12 + 316


def test_an_import_lends_the_key_and_it_comes_back_when_the_pc_lets_go(server):
    ks, srv, tmp = server
    lent, back = srv.calls
    req = struct.pack("!HHI", ks.VERSION, ks.OP_REQ_IMPORT, 0) + b"1-4".ljust(32, b"\0")
    out = _ask(ks, srv, req)
    assert struct.unpack("!HHI", out[:8]) == (ks.VERSION, ks.OP_REP_IMPORT, ks.ST_OK)
    assert out[8 + 256:8 + 259] == b"1-4" and len(out) == 8 + 312
    assert lent == ["1-4"] and srv.lent == {"1-4"}
    assert (tmp / "devices" / "1-4" / "usbip_sockfd").read_text().isdigit()   # the kernel got it
    # a second PC while it is lent: busy, and nothing taken twice
    (tmp / "devices" / "1-4" / "usbip_status").write_text("2\n")
    out = _ask(ks, srv, req)
    assert struct.unpack("!HHI", out[:8])[2] == ks.ST_DEV_BUSY and lent == ["1-4"]
    srv.watch()
    assert back == []                                       # still in use
    (tmp / "devices" / "1-4" / "usbip_status").write_text("1\n")
    srv.watch()
    assert back == ["1-4"] and srv.lent == set()


def test_give_back_unbinds_rebinds_then_forgets_and_lend_clears_a_stale_entry(tmp_path, monkeypatch):
    # PAD-1416, found on the GnR VM: deleting the table entry before the unbind left it
    # "removed", and the next lend's bind failed with ENODEV
    ks = _server()
    root = _fake_sysfs(tmp_path)
    drv = os.path.join(root, "drivers", "usbip-host")
    os.makedirs(drv)
    wrote = []
    monkeypatch.setattr(ks, "_write", lambda p, t: wrote.append((os.path.basename(p), t)))
    monkeypatch.setattr(ks, "bound_to_us", lambda b, r=None: True)
    ks.give_back("1-4", root)
    assert wrote == [("unbind", "1-4"), ("rebind", "1-4"), ("match_busid", "del 1-4")]
    wrote.clear()
    monkeypatch.setattr(ks, "bound_to_us", lambda b, r=None: False)
    monkeypatch.setattr(ks.os, "system", lambda c: 0)
    (tmp_path / "devices" / "1-4" / "usbip_status").write_text("1\n")
    assert ks.lend("1-4", root)
    assert wrote == [("match_busid", "del 1-4"), ("match_busid", "add 1-4"), ("bind", "1-4")]


def test_an_import_of_no_key_is_device_not_found(server):
    ks, srv, _ = server
    req = struct.pack("!HHI", ks.VERSION, ks.OP_REQ_IMPORT, 0) + b"9-9".ljust(32, b"\0")
    assert struct.unpack("!HHI", _ask(ks, srv, req)[:8])[2] == ks.ST_NODEV
    assert srv.calls[0] == []
