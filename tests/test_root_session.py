"""PAD-1173: a JJP run on a Linux desktop asks for root ONCE.

The JJP, Spooky and BoF Linux executors sent every command as ``sudo bash -c``;
from a desktop launcher sudo has no terminal to ask a password on, so every
mount, cp and umount of a JJP extract failed.  core/root_session.py gives a run
one root shell through pkexec (one password dialog) and the executors send
their commands to it; Spooky and BoF, which need no root, run as the user.

The shell tests start the REAL shell script under a stand-in ``pkexec`` (drops
its flag and runs the rest as the same user), so they need Linux bash/setsid.
"""
import os
import stat
import subprocess
import sys
import time

import pytest

from pinball_decryptor.core import executor as CEX
from pinball_decryptor.core import root_session as RS

linux = pytest.mark.skipif(not sys.platform.startswith("linux"),
                           reason="the root shell is bash + setsid")


# -- route ---------------------------------------------------------------
def _route_env(monkeypatch, uid=1000, sudo=False, pkexec=True, display=True,
               tty=False):
    monkeypatch.setattr(RS.os, "getuid", lambda: uid, raising=False)
    monkeypatch.setattr(CEX.NativeExecutor, "_sudo_ok", sudo)
    monkeypatch.setattr(RS.shutil, "which",
                        lambda n: {"pkexec": "/usr/bin/pkexec" if pkexec else None,
                                   "sudo": "/usr/bin/sudo"}.get(n))
    for k in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(k, raising=False)
    if display:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(RS, "_on_terminal", lambda: tty)


def test_route_root_and_passwordless_sudo_keep_the_old_prefix(monkeypatch):
    _route_env(monkeypatch, uid=0)
    assert RS.route() == "root"
    _route_env(monkeypatch, sudo=True)
    assert RS.route() == "sudo"


def test_route_desktop_without_free_sudo_is_one_pkexec_session(monkeypatch):
    _route_env(monkeypatch)
    assert RS.route() == "pkexec"
    _route_env(monkeypatch, tty=True)          # started from a terminal too
    assert RS.route() == "pkexec"


def test_route_terminal_without_pkexec_keeps_sudo_asking_there(monkeypatch):
    _route_env(monkeypatch, pkexec=False, tty=True)
    assert RS.route() == "sudo-tty"
    _route_env(monkeypatch, display=False, tty=True)
    assert RS.route() == "sudo-tty"


def test_route_nothing_at_all(monkeypatch):
    _route_env(monkeypatch, pkexec=False)
    assert RS.route() is None
    assert RS.NO_ROOT in RS.describe(None)


# -- the JJP executor ----------------------------------------------------
class _FakeSession:
    def __init__(self, rc=0, out="", err="", lines=()):
        self.calls, self.rc, self.out, self.err = [], rc, out, err
        self.lines, self.closed, self.killed = list(lines), 0, 0

    def run(self, cmd, timeout=120):
        self.calls.append(("run", cmd))
        return self.rc, self.out, self.err

    def stream(self, cmd, timeout=600):
        self.calls.append(("stream", cmd))
        for line in self.lines:
            yield line
        return self.rc

    def kill_streams(self):
        self.killed += 1

    def close(self):
        self.closed += 1


@pytest.fixture
def jjp_native(monkeypatch):
    from pinball_decryptor.plugins.jjp import executor as JEX
    monkeypatch.setattr(RS, "route", lambda: "pkexec")
    ex = JEX.NativeExecutor()
    sess = _FakeSession(out="hello\n")
    ex._root = sess
    return JEX, ex, sess


def test_jjp_commands_go_to_the_runs_root_session(jjp_native):
    JEX, ex, sess = jjp_native
    assert ex._cmd_prefix() is None
    assert ex.run("mount -o loop a b") == "hello\n"
    sess.lines, sess.rc = ["1%", "50%"], 0
    assert list(ex.stream("partclone ...")) == ["1%", "50%"]
    assert sess.calls == [("run", "mount -o loop a b"),
                          ("stream", "partclone ...")]


def test_jjp_failures_keep_the_command_error_shape(jjp_native):
    JEX, ex, sess = jjp_native
    sess.rc, sess.err = 32, "mount: wrong fs type"
    with pytest.raises(JEX.CommandError) as e:
        ex.run("mount x y")
    assert e.value.returncode == 32 and "wrong fs type" in e.value.output
    sess.lines = ["partclone: error 7"]
    with pytest.raises(JEX.CommandError) as e:
        list(ex.stream("partclone"))
    assert e.value.returncode == 32 and "error 7" in e.value.output


def test_jjp_refused_prompt_is_a_command_error(jjp_native):
    JEX, ex, sess = jjp_native

    def refused(cmd, timeout=120):
        raise RS.RootError("the password prompt for root was canceled or "
                           "refused", 126)
    sess.run = refused
    with pytest.raises(JEX.CommandError) as e:
        ex.run("mount x y")
    assert e.value.returncode == 126 and "canceled" in e.value.output


def test_jjp_kill_and_close_reach_the_session(jjp_native):
    JEX, ex, sess = jjp_native
    ex.kill()
    assert sess.killed == 1
    ex.close_root()
    assert sess.closed == 1 and ex._root is None


def test_jjp_no_root_route_says_how_to_get_it(monkeypatch):
    from pinball_decryptor.plugins.jjp import executor as JEX
    monkeypatch.setattr(RS, "route", lambda: None)
    ex = JEX.NativeExecutor()
    with pytest.raises(JEX.CommandError) as e:
        ex.run("mount x y")
    assert "pkexec" in e.value.output
    ok, msg = ex.check_available()
    assert not ok and "pkexec" in msg


def test_jjp_check_available_never_asks_for_a_password(jjp_native):
    JEX, ex, sess = jjp_native
    ok, msg = ex.check_available()
    assert ok and "password" in msg and sess.calls == []


def test_jjp_linux_prerequisites_probe_tools_as_the_user(monkeypatch, jjp_native):
    JEX, ex, sess = jjp_native
    from pinball_decryptor.plugins.jjp import pipeline as P
    monkeypatch.setattr(P.sys, "platform", "linux")
    probed = []
    ex.run_user = lambda cmd, timeout=30: probed.append(cmd) or "/usr/bin/x\n"
    results = P.check_prerequisites(ex)
    assert sess.calls == []                      # no root, no password
    assert len(probed) == 5 and all(c.startswith("command -v") for c in probed)
    assert all(ok for _n, ok, _m in results)


def test_jjp_robust_run_leaves_session_commands_to_the_executor(jjp_native):
    JEX, ex, sess = jjp_native
    from pinball_decryptor.plugins.jjp import pipeline as P
    P._install_robust_run_host(ex)
    assert ex.run("losetup -j img") == "hello\n"
    assert sess.calls == [("run", "losetup -j img")]


def test_jjp_run_done_ends_the_root_session(jjp_native):
    JEX, ex, sess = jjp_native
    from pinball_decryptor.plugins.jjp import pipeline as P
    seen = []
    done = P._done_ends_root(lambda ok, msg: seen.append((ok, msg, sess.closed)),
                             ex)
    done(True, "complete")
    assert seen == [(True, "complete", 1)]       # closed BEFORE done reported


def test_jjp_pipelines_wire_the_done_callback(monkeypatch, jjp_native):
    JEX, ex, sess = jjp_native
    from pinball_decryptor.plugins.jjp import pipeline as P
    monkeypatch.setattr(P, "create_executor", lambda: ex)
    seen = []
    pl = P.DecryptionPipeline("a.iso", "/out", lambda *a: None,
                              lambda *a: None, lambda *a: None,
                              lambda ok, msg: seen.append(ok))
    pl.on_done(False, "x")
    assert seen == [False] and sess.closed == 1


# -- Spooky / BoF: no root needed, so no sudo that would ask --------------
@pytest.mark.parametrize("mod, meth", [("spooky", "_cmd_prefix"),
                                       ("bof", "_prefix")])
def test_spooky_bof_run_as_the_user_when_sudo_would_ask(monkeypatch, mod, meth):
    import importlib
    M = importlib.import_module(f"pinball_decryptor.plugins.{mod}.executor")
    monkeypatch.setattr(M.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(CEX.NativeExecutor, "_sudo_ok", False)
    assert getattr(M.NativeExecutor(), meth)() == ["bash", "-c"]
    monkeypatch.setattr(CEX.NativeExecutor, "_sudo_ok", True)
    assert getattr(M.NativeExecutor(), meth)() == ["sudo", "bash", "-c"]
    monkeypatch.setattr(M.os, "getuid", lambda: 0, raising=False)
    assert getattr(M.NativeExecutor(), meth)() == ["bash", "-c"]


# -- host ISO mounts (Spooky, Pinball Brothers) ---------------------------
def test_iso_mount_on_a_desktop_is_one_session_for_mount_and_umount(monkeypatch):
    made = []

    class _S(_FakeSession):
        def __init__(self):
            super().__init__()
            made.append(self)
    monkeypatch.setattr(RS, "route", lambda: "pkexec")
    monkeypatch.setattr(RS, "RootSession", _S)
    mp, cleanup = RS.mount_iso("/isos/My Game.iso", prefix="pad_iso_")
    try:
        assert os.path.isdir(mp) and len(made) == 1
        assert made[0].calls[0][1].startswith(
            "mount -o loop,ro '/isos/My Game.iso' ")
        assert made[0].closed == 0                # held until the umount
    finally:
        cleanup()
    assert [c[1].split()[0] for c in made[0].calls] == ["mount", "umount"]
    assert made[0].closed == 1 and not os.path.exists(mp)


def test_iso_mount_failure_cleans_up_and_says_why(monkeypatch):
    made = []

    class _S(_FakeSession):
        def __init__(self):
            super().__init__(rc=32, err="mount: permission denied")
            made.append(self)
    monkeypatch.setattr(RS, "route", lambda: "pkexec")
    monkeypatch.setattr(RS, "RootSession", _S)
    before = set(os.listdir(RS.tempfile.gettempdir()))
    with pytest.raises(RuntimeError, match="permission denied"):
        RS.mount_iso("/x.iso")
    assert made[0].closed == 1
    assert set(os.listdir(RS.tempfile.gettempdir())) <= before


def test_iso_mount_with_no_root_route(monkeypatch):
    monkeypatch.setattr(RS, "route", lambda: None)
    with pytest.raises(RuntimeError, match="pkexec"):
        RS.mount_iso("/x.iso")


def test_spooky_and_clonezilla_linux_mounts_use_the_helper(monkeypatch):
    from pinball_decryptor.core import clonezilla as CZ
    from pinball_decryptor.plugins.spooky import clonezilla as SC
    got = []
    monkeypatch.setattr(RS, "mount_iso",
                        lambda p, prefix="": got.append((p, prefix)) or ("/m", None))
    assert CZ._mount_linux("/a.iso", None) == ("/m", "/m", None)
    assert SC._mount_iso_linux("/b.iso") == ("/m", None)
    assert got == [("/a.iso", "pad_iso_"), ("/b.iso", "spooky_iso_")]


# -- the real root shell, under a stand-in pkexec -------------------------
@pytest.fixture
def session(tmp_path):
    fake = tmp_path / "pkexec"
    count = tmp_path / "asked"
    fake.write_text('#!/bin/sh\necho x >> "%s"\n'
                    '[ "$1" = --disable-internal-agent ] && shift\n'
                    'exec "$@"\n' % count)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    s = RS.RootSession(pkexec=str(fake))
    s.asked = lambda: len(count.read_text().split()) if count.exists() else 0
    yield s
    s.close()


@linux
def test_session_runs_many_commands_on_one_prompt(session):
    for i in range(20):
        assert session.run("echo out%d; echo err%d >&2; exit %d" % (i, i, i % 3)) \
            == (i % 3, "out%d\n" % i, "err%d\n" % i)
    assert session.asked() == 1 and session.starts == 1


@linux
def test_session_keeps_quotes_newlines_and_unicode(session):
    cmd = "printf '%s\\n' \"it's\" 'a \"b\"' 'café'\nfalse || echo $((6*7))"
    rc, out, _ = session.run(cmd)
    assert rc == 0 and out == "it's\na \"b\"\ncafé\n42\n"


@linux
def test_session_stream_yields_lines_as_they_come(session):
    gen = session.stream("echo one; sleep 0.3; printf 'p1\\rp2\\r'; "
                         "echo two >&2; printf 'last'; exit 4")
    first = next(gen)
    t = time.monotonic()
    rest = []
    try:
        while True:
            rest.append(next(gen))
    except StopIteration as stop:
        rc = stop.value
    assert first == "one" and time.monotonic() - t > 0.2
    assert rest == ["p1", "p2", "two", "last"] and rc == 4


@linux
def test_session_timeout_stops_the_whole_command(session, tmp_path):
    pidf = tmp_path / "child"
    with pytest.raises(RS.RootTimeout):
        session.run("sleep 30 & echo $! > %s; wait" % pidf, timeout=1)
    pid = int(pidf.read_text())
    time.sleep(0.3)
    assert not os.path.exists("/proc/%d" % pid)       # its group was killed
    assert session.run("echo still")[1] == "still\n"  # and the shell goes on


@linux
def test_session_runs_commands_side_by_side(session):
    import threading
    out = {}

    def go(i):
        out[i] = session.run("sleep 0.5; echo %d" % i)
    t0 = time.monotonic()
    th = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert time.monotonic() - t0 < 1.8
    assert {i: o[1] for i, o in out.items()} == {i: "%d\n" % i for i in range(4)}


@linux
def test_session_kill_streams_stops_a_running_stream(session):
    import threading
    gen = session.stream("echo go; sleep 30; echo never")
    assert next(gen) == "go"
    threading.Timer(0.3, session.kill_streams).start()
    t0 = time.monotonic()
    with pytest.raises(StopIteration) as stop:
        next(gen)
    assert stop.value.value == 143 and time.monotonic() - t0 < 5


@linux
def test_session_files_live_in_its_own_unwritable_dir(session):
    session.run("true")
    d = session._dir
    st = os.stat(d)
    assert stat.S_IMODE(st.st_mode) == 0o711
    session.close()
    time.sleep(0.3)
    assert not os.path.exists(d)                      # removed at the end


@linux
def test_session_close_stops_what_still_runs(session, tmp_path):
    pidf = tmp_path / "child"
    gen = session.stream("echo $$ > %s; echo up; sleep 30" % pidf)
    assert next(gen) == "up"
    pid = int(pidf.read_text())
    session.close()
    time.sleep(0.5)
    assert not os.path.exists("/proc/%d" % pid)


@linux
def test_refused_prompt_is_not_asked_again_until_closed(tmp_path):
    fake = tmp_path / "pkexec"
    count = tmp_path / "asked"
    fake.write_text('#!/bin/sh\necho x >> "%s"\n'
                    'echo "Error executing command as another user: '
                    'Not authorized" >&2\nexit 127\n' % count)
    fake.chmod(0o755)
    s = RS.RootSession(pkexec=str(fake))
    for _ in range(3):
        with pytest.raises(RS.RootError) as e:
            s.run("umount /x")
        assert e.value.rc == 127 and "canceled or refused" in str(e.value)
    assert len(count.read_text().split()) == 1        # cleanup did not re-ask
    s.close()                                          # the next run asks again
    with pytest.raises(RS.RootError):
        s.run("true")
    assert len(count.read_text().split()) == 2


@linux
def test_no_agent_says_so(tmp_path):
    fake = tmp_path / "pkexec"
    fake.write_text('#!/bin/sh\necho "Error: No authentication agent found." >&2\n'
                    'exit 127\n')
    fake.chmod(0o755)
    with pytest.raises(RS.RootError, match="no polkit authentication agent"):
        RS.RootSession(pkexec=str(fake)).run("true")


@linux
def test_jjp_executor_end_to_end_through_the_shell(monkeypatch, session):
    from pinball_decryptor.plugins.jjp import executor as JEX
    from pinball_decryptor.plugins.jjp import pipeline as P
    monkeypatch.setattr(RS, "route", lambda: "pkexec")
    ex = P._install_robust_run_host(JEX.NativeExecutor())
    ex._root = session
    assert ex.run("echo $((2+2))") == "4\n"
    assert list(ex.stream("seq 3")) == ["1", "2", "3"]
    with pytest.raises(JEX.CommandError) as e:
        ex.run("echo nope >&2; exit 5")
    assert e.value.returncode == 5 and e.value.output == "nope"
    with pytest.raises(JEX.CommandError, match="timed out"):
        ex.run("sleep 10", timeout=1)
    assert session.asked() == 1
