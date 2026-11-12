"""The Multi-boot tab's root steps on a Linux desktop (PAD-1188).

``sudo -n`` alone failed every build started from a desktop launcher ("sudo:
interactive authentication is required", Brombomb, from the AppImage).  These
pin the route each machine gets, the one root shell a run shares, that a
preview never asks for a password, Cancel during the prompt, and the AppImage
tools copy a root step runs from.  The real thing - a password-sudo user, no
terminal, a squashfuse mount, a two-image card built and verified on one
prompt - is the WSL proof in the ticket; nothing here needs root or Linux.
"""
import os
import sys
import time

import pytest

from pinball_decryptor.core import root_session
from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui import multiboot_root as R


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    R.end_run()
    R._STAGED.clear()
    monkeypatch.setattr(R, "_user_home", lambda: "/home/u")
    yield
    R.end_run()


def _route(monkeypatch, r):
    monkeypatch.setattr(R.root_session, "route", lambda: r)


# ------------------------------------------------------------------ routes
def test_each_route_gets_its_own_argv_and_carries_the_desktop_home(monkeypatch):
    _route(monkeypatch, "root")
    assert R.linux_argv("x") == ["env", "HOME=/home/u", "bash", "-lc", "x"]
    _route(monkeypatch, "sudo")
    assert R.linux_argv("x") == ["sudo", "-n", "env", "HOME=/home/u", "bash", "-lc", "x"]
    _route(monkeypatch, "sudo-tty")
    assert R.linux_argv("x", "/home/v") == ["sudo", "env", "HOME=/home/v", "bash", "-lc", "x"]


def test_the_pkexec_route_is_a_root_line_for_the_runs_root_shell(monkeypatch):
    _route(monkeypatch, "pkexec")
    line = "cd /r && python3 t.py build --selector-dir ~/spike2root/x --titles 'a;b'"
    argv = R.linux_argv(line)
    assert isinstance(argv, R.RootLine)
    assert argv[-1] == line, "the Log echoes argv[-1]"
    assert argv.cmd == "env HOME=/home/u bash -lc " + R.shlex.quote(line)
    _route(monkeypatch, None)       # no way to root: still a root line, and
    assert isinstance(R.linux_argv("x"), R.RootLine)    # RootSession says why


def test_linux_root_steps_resolve_on_the_worker(monkeypatch):
    monkeypatch.setattr(mt.sys, "platform", "linux")
    monkeypatch.setattr(mt._mac, "enabled", lambda: False)
    _route(monkeypatch, "pkexec")
    step = mt.root_command(["t.py", "build"], cwd="/repo")
    assert callable(step), "the route asks sudo: never on the Tk thread"
    argv = step({})
    assert isinstance(argv, R.RootLine) and argv.line == "cd /repo && python3 t.py build"
    sel = mt.root_shell_line("make x", cwd="/repo")
    assert callable(sel) and sel({}).line == "cd /repo && make x"


def test_the_password_note_knows_sudo_rs():
    """Ubuntu 25.10's sudo-rs words it differently - the reporter's log."""
    assert mt.sudo_password_note("sudo: interactive authentication is required")
    assert mt.sudo_password_note("sudo: a password is required")
    assert mt.sudo_password_note("sudo: a terminal is required to read the password")
    assert mt.sudo_password_note("build: exit 1") == ""


# ------------------------------------------------------------ the session
class FakeSession:
    instances = []

    def __init__(self, lines=("one", "two"), rc=0, refuse=None, prompt_s=0):
        self.lines, self.rc, self.refuse, self.prompt_s = lines, rc, refuse, prompt_s
        self.cmds, self.closed, self.killed = [], False, 0
        self.alive = False
        self._proc = None
        FakeSession.instances.append(self)

    def _ensure(self):
        if self.refuse:
            raise root_session.RootError(self.refuse, 126)
        end = time.monotonic() + self.prompt_s     # the dialog is up
        while time.monotonic() < end:
            if self._proc is not None and self._proc.killed:
                raise root_session.RootError(
                    "could not get root through pkexec (exit -9)", -9)
            time.sleep(0.01)
        self.alive = True

    def stream(self, cmd, timeout=600):
        self._ensure()
        self.cmds.append(cmd)
        for ln in self.lines:
            yield ln
        return self.rc

    def kill_streams(self):
        self.killed += 1

    def close(self):
        self.closed = True
        self.alive = False


def _fake(monkeypatch, **kw):
    FakeSession.instances = []
    monkeypatch.setattr(R.root_session, "RootSession", lambda: FakeSession(**kw))


def _drain(proc):
    return [b.decode().rstrip("\n") for b in proc.stdout], proc.wait(5)


def test_a_run_shares_one_root_shell_and_ends_it(monkeypatch):
    _fake(monkeypatch)
    a = R.start(_rl("a"))
    assert _drain(a) == (["one", "two"], 0)
    b = R.start(_rl("b"))
    assert _drain(b) == (["one", "two"], 0)
    assert len(FakeSession.instances) == 1, "one password prompt a run"
    s = FakeSession.instances[0]
    assert s.cmds == ["bash -lc a", "bash -lc b"]
    R.end_run()
    assert s.closed and R._SESSION[0] is None


def _rl(line):
    rl = R.RootLine(line)
    rl.cmd = "bash -lc " + line
    return rl


def test_a_failed_command_and_a_refused_prompt_say_so(monkeypatch):
    _fake(monkeypatch, lines=("boom",), rc=3)
    assert _drain(R.start(_rl("a"))) == (["boom"], 3)
    R.end_run()
    _fake(monkeypatch, refuse="the password prompt for root was canceled or refused")
    lines, rc = _drain(R.start(_rl("a")))
    assert rc == 126 and "canceled or refused" in lines[-1]


def test_a_preview_never_asks_for_a_password(monkeypatch):
    _fake(monkeypatch)
    lines, rc = _drain(R.start(_rl("a"), preview=True))
    assert rc == 1 and lines == [R.PREVIEW_NO_PROMPT]
    assert FakeSession.instances == [], "no session, so no dialog"
    # ...but it uses the shell a run already has open
    assert _drain(R.start(_rl("a")))[1] == 0
    assert _drain(R.start(_rl("b"), preview=True)) == (["one", "two"], 0)
    assert len(FakeSession.instances) == 1


def test_cancel_during_the_prompt_stops_pkexec_and_the_step(monkeypatch):
    _fake(monkeypatch, prompt_s=5)

    class P:
        killed = False

        def kill(self):
            P.killed = True
            self.killed = True
    proc = R.start(_rl("a"))
    time.sleep(0.05)
    s = FakeSession.instances[0]
    s._proc = P()
    t0 = time.monotonic()
    proc.kill()
    lines, rc = _drain(proc)
    assert P.killed and rc != 0 and time.monotonic() - t0 < 3
    assert s.cmds == [], "the build never started"


# ------------------------------------------------------- the panel's runner
class _Panel:
    def __init__(self):
        self._busy = self._pv_busy = False
        self._cancelled = self._cancel_pending = self._pv_cancel = False
        self._pending_run = self._drain_job = self._proc = None
        self._proc_preview = False
        self.out, self.said = [], []

    def _set_busy(self, b):
        self._busy = b

    def _append(self, line):
        self.out.append(line)

    _write = _warm_log = _append

    def _error(self, m):
        self.out.append(m)

    def _ui(self, fn):
        fn()

    def _drain(self):
        pass

    def _say_once(self, s):
        if s:
            self.said.append(s)

    def _phase_step(self, label):
        pass

    def _progress_tick(self, *a):
        pass

    def _phase_done(self, rc, failed):
        pass

    def _phase_cancelled(self):
        pass

    def _pv_say(self, s):
        pass

    def schedule_preview(self):
        pass


def _run(monkeypatch, cmds, preview=False):
    for name in ("_run_commands", "_start_worker"):
        monkeypatch.setattr(_Panel, name, getattr(mt.MultibootPanel, name), raising=False)
    monkeypatch.setattr(mt._mac, "enabled", lambda: False)
    p, res = _Panel(), {}
    p._run_commands(cmds, on_done=lambda rc, f, t: res.update(rc=rc, failed=f, texts=t),
                    preview=preview)
    end = time.monotonic() + 10
    while "rc" not in res and time.monotonic() < end:
        time.sleep(0.02)
    return p, res


def test_the_runner_sends_a_root_line_to_the_root_shell_and_ends_it(monkeypatch):
    _fake(monkeypatch, lines=("[card] built",), rc=0)
    _route(monkeypatch, "pkexec")
    monkeypatch.setattr(mt.subprocess, "Popen", lambda *a, **k: pytest.fail("Popen"))
    p, res = _run(monkeypatch, [("build", lambda _t: R.linux_argv("cd /r && make"))])
    assert res["rc"] == 0 and res["failed"] is None
    assert "$ cd /r && make" in p.out and "[card] built" in p.out
    assert res["texts"]["build"] == "[card] built"
    assert FakeSession.instances[0].closed, "the run's root shell ends with it"


def test_the_runner_preview_fails_with_a_sentence_not_a_dialog(monkeypatch):
    _fake(monkeypatch)
    _route(monkeypatch, "pkexec")
    p, res = _run(monkeypatch, [("prepare", R.linux_argv("x"))], preview=True)
    assert res["rc"] == 1 and res["failed"] == "prepare"
    assert R.PREVIEW_NO_PROMPT in p.out and FakeSession.instances == []


# ------------------------------------------------------- the AppImage copy
def _appimage(monkeypatch, tmp_path):
    mount = tmp_path / ".mount_PADx" / "usr" / "bin" / "_internal"
    (mount / "tools" / "spike2_emu" / "__pycache__").mkdir(parents=True)
    (mount / "tools" / "spike2_emu" / "mkmulticard.py").write_text("print(1)\n")
    (mount / "tools" / "spike2_emu" / "__pycache__" / "x.pyc").write_text("")
    (mount / "pinball_decryptor" / "plugins").mkdir(parents=True)
    (mount / "pinball_decryptor" / "plugins" / "ext4.py").write_text("")
    (mount / "_tcl_data").mkdir()
    img = tmp_path / "PAD.AppImage"
    img.write_text("elf")
    monkeypatch.setattr(R.sys, "platform", "linux")
    monkeypatch.setenv("APPDIR", str(tmp_path / ".mount_PADx"))
    monkeypatch.setenv("APPIMAGE", str(img))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    if hasattr(os, "geteuid"):
        monkeypatch.setattr(R.os, "geteuid", lambda: 1000)
    return str(mount), img


def test_an_appimage_root_step_runs_from_a_copy_root_can_read(monkeypatch, tmp_path):
    mount, img = _appimage(monkeypatch, tmp_path)
    dst = R.root_repo_dir(mount)
    assert dst.startswith(str(tmp_path / "cache" / "pinball_decryptor" / "root-rig"))
    assert os.path.isfile(os.path.join(dst, "tools", "spike2_emu", "mkmulticard.py"))
    assert os.path.isfile(os.path.join(dst, "pinball_decryptor", "plugins", "ext4.py"))
    assert not os.path.exists(os.path.join(dst, "tools", "spike2_emu", "__pycache__"))
    assert not os.path.exists(os.path.join(dst, "_tcl_data")), "only what the tools need"
    # the step's line cds there
    monkeypatch.setattr(mt.sys, "platform", "linux")
    monkeypatch.setattr(mt._mac, "enabled", lambda: False)
    _route(monkeypatch, "pkexec")
    assert mt.root_command(["t.py"], cwd=mount)({}).line == "cd %s && python3 t.py" % mt._q(dst)
    # a newer AppImage gets a fresh copy and the old one goes
    R._STAGED.clear()
    img.write_text("a newer build")
    os.utime(img, (time.time() + 60, time.time() + 60))
    dst2 = R.root_repo_dir(mount)
    assert dst2 != dst and os.path.isdir(dst2) and not os.path.exists(dst)


def test_a_checkout_or_a_root_app_runs_in_place(monkeypatch, tmp_path):
    mount, _ = _appimage(monkeypatch, tmp_path)
    assert R.root_repo_dir(str(tmp_path / "checkout")) == str(tmp_path / "checkout")
    monkeypatch.delenv("APPIMAGE")
    assert R.root_repo_dir(mount) == mount
    monkeypatch.setattr(R.sys, "platform", "win32")
    assert R.root_repo_dir(mount) == mount
