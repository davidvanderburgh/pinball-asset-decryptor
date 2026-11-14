"""PAD-1307: three rig-hygiene fixes.

R4  a VISIBLE Barrels of Fun run renders on the GPU (GALLIUM_DRIVER=d3d12)
    where WSL has one, instead of Mesa's llvmpipe; hidden runs are untouched.
R5  watch.sh gives the rig user back files an elevated run left to root,
    and refuses only when no root can be had without asking.
R6  systemd-timesyncd is turned off in the running WSL distros (it fights
    WSL's own clock, and the sound drifts).
"""
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from pinball_decryptor.core import timesync

REPO = Path(__file__).resolve().parents[1]
WATCH = REPO / "tools" / "spike2_emu" / "watch.sh"
BOF_RUN = REPO / "tools" / "bof_emu" / "run_game.sh"


# ---------------------------------------------------------------- R6 (unit)

class _Runner:
    def __init__(self, running, answers):
        self.running, self.answers, self.calls = running, answers, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[1:3] == ["-l", "--running"]:
            out = "".join(n + "\r\n" for n in self.running).encode("utf-16-le")
            return subprocess.CompletedProcess(argv, 0, out, b"")
        name = argv[argv.index("-d") + 1]
        return subprocess.CompletedProcess(argv, 0, self.answers.get(name, b""), b"")


@pytest.fixture
def _fresh(monkeypatch):
    monkeypatch.delenv("PAD_KEEP_TIMESYNC", raising=False)
    monkeypatch.setattr(timesync, "_done", False)


def test_timesync_turned_off_where_running(_fresh):
    run = _Runner(["Ubuntu", "docker-desktop", "PAD-Runtime"],
                  {"Ubuntu": b"PAD_TIMESYNC_OFF\n"})
    said = []
    assert timesync.quiet_clocks(log=said.append, runner=run) == ["Ubuntu"]
    asked = [c[c.index("-d") + 1] for c in run.calls if "-d" in c]
    assert asked == ["Ubuntu", "PAD-Runtime"]          # docker's own skipped
    cmd = run.calls[1]
    assert cmd[:6] == ["wsl.exe", "-d", "Ubuntu", "-u", "root", "-e"]
    assert cmd[6:8] == ["sh", "-c"] and "disable --now systemd-timesyncd" in cmd[8]
    assert '"' not in cmd[8] and "'" not in cmd[8]     # crosses wsl.exe's line
    assert len(said) == 1 and "Ubuntu" in said[0]


def test_timesync_once_per_session_and_opt_out(_fresh, monkeypatch):
    run = _Runner(["Ubuntu"], {"Ubuntu": b"PAD_TIMESYNC_OFF\n"})
    timesync.quiet_clocks(runner=run)
    n = len(run.calls)
    assert timesync.quiet_clocks(runner=run) == [] and len(run.calls) == n
    monkeypatch.setattr(timesync, "_done", False)
    monkeypatch.setenv("PAD_KEEP_TIMESYNC", "1")
    assert timesync.quiet_clocks(runner=run) == [] and len(run.calls) == n


def test_timesync_already_off_says_nothing(_fresh):
    said = []
    assert timesync.quiet_clocks(log=said.append,
                                 runner=_Runner(["Ubuntu"], {})) == []
    assert said == []


def test_every_emulate_tab_quiets_the_clock_before_its_run():
    tabs = REPO / "pinball_decryptor" / "webui" / "tabs"
    for f in ["emulate.py", "emulate_ap.py", "emulate_bof.py", "emulate_dp.py",
              "emulate_jjp.py", "emulate_pb.py", "emulate_spooky.py"]:
        text = (tabs / f).read_text(encoding="utf-8")
        assert "timesync.quiet_clocks_async(self._log)" in text, f


def test_installer_and_watch_turn_it_off_too():
    ps = (REPO / "installer" / "install_prerequisites.ps1").read_text(encoding="utf-8")
    assert "function Disable-WslTimesyncd" in ps
    assert "Set-WslOrdinaryUser; Disable-WslTimesyncd" in ps
    w = WATCH.read_text(encoding="utf-8")
    i = w.index("NO SECOND CLOCK-SETTER")
    block = w[i:i + 1500]
    assert "pad_is_wsl" in block and "disable --now systemd-timesyncd" in block


# ------------------------------------------------- WSL behaviour (R4, R5, R6)

def _runtime():
    try:
        r = subprocess.run(["wsl.exe", "-d", "PAD-Runtime", "-e", "true"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


needs_runtime = pytest.mark.skipif(os.name != "nt" or not _runtime(),
                                   reason="needs the PAD-Runtime WSL distro")


def _wsl(script: str, tmp_path, *args, user=None):
    """Run *script* (a bash file) in PAD-Runtime; return (rc, stdout+stderr)."""
    f = tmp_path / ("s_%s.sh" % uuid.uuid4().hex[:6])
    f.write_bytes(script.replace("\r\n", "\n").encode())
    win = str(f).replace("\\", "/")
    argv = ["wsl.exe", "-d", "PAD-Runtime"] + (["-u", user] if user else []) + \
        ["--cd", "/", "-e", "bash", "-c", 'bash "$(wslpath -a "$0")" "$@"', win] + list(args)
    r = subprocess.run(argv, capture_output=True, timeout=180)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def _bof_gl_block():
    t = BOF_RUN.read_text(encoding="utf-8")
    return t[t.index('GL_ENV=""'):t.index('echo "renderer=')] + \
        'echo "renderer=${GL_ENV:-mesa-default}"\n'


@needs_runtime
@pytest.mark.parametrize("env, want", [
    ("VISIBLE=0", "renderer=mesa-default"),
    ("VISIBLE=1", "renderer=GALLIUM_DRIVER=d3d12"),
    ("VISIBLE=1 GALLIUM_DRIVER=llvmpipe", "renderer=GALLIUM_DRIVER=llvmpipe"),
    ("VISIBLE=1 PAD_GL_DRIVER=mesa", "renderer=mesa-default"),
    ("VISIBLE=1 PAD_GL_ADAPTER=NVIDIA", "MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA"),
])
def test_bof_visible_run_picks_d3d12(tmp_path, env, want):
    tools = "/tmp/pad1307_%s" % uuid.uuid4().hex[:6]
    script = ("set -u; export %s; BOF_TOOLS=%s/bof_emu; mkdir -p $BOF_TOOLS\n"
              "[ -e /dev/dxg ] || { echo NODXG; exit 0; }\n" % (env, tools)
              + _bof_gl_block() + "rm -rf %s\n" % tools)
    rc, out = _wsl(script, tmp_path)
    if "NODXG" in out:
        pytest.skip("no /dev/dxg in this WSL")
    assert rc == 0 and want in out, out


def _repair_block():
    t = WATCH.read_text(encoding="utf-8")
    i = t.index("pad_root_noask() {")
    j = t.index("# ★ NO SECOND CLOCK-SETTER")
    return t[i:j]


@needs_runtime
@pytest.mark.parametrize("reach_root", [True, False])
def test_watch_gives_back_root_owned_nvram(tmp_path, reach_root):
    """Real files, really owned by root (made via wsl -u root), and the real
    block of watch.sh run as the rig user: given back via WSL interop, or -
    with no way to root - the old refusal."""
    base = "/tmp/pad1307_%s" % uuid.uuid4().hex[:8]
    mk = ("set -e; mkdir -p {b}/root/data/nv/bond/LKRAM {b}/root/dump {b}/home/cardcache;"
          "chown -R pad:pad {b}; touch {b}/root/data/nv/bond/LKRAM/00000008.crc32 "
          "{b}/root/data/nvram-bond.bin {b}/root/dump/debug_log.txt {b}/home/cardcache/x;"
          "chmod 000 {b}/root/data/nv/bond/LKRAM/00000008.crc32;"
          "chown root:root {b}/root/data/nv/bond/LKRAM/00000008.crc32 "
          "{b}/root/data/nvram-bond.bin {b}/root/dump/debug_log.txt {b}/home/cardcache/x\n").format(b=base)
    rc, out = _wsl(mk, tmp_path, user="root")
    assert rc == 0, out
    try:
        run = ("set -u; ROOT={b}/root; GAME=bond; PAD_HOME={b}/home\n"
               "%s\n" % ("" if reach_root else "WSL_DISTRO_NAME=\n")).format(b=base) \
            + _repair_block() + \
            ("echo STARTED; find {b} ! -user pad | wc -l | sed 's/^/LEFT=/'\n").format(b=base)
        rc, out = _wsl(run, tmp_path)
        if reach_root:
            assert rc == 0 and "STARTED" in out, out
            assert re.search(r"gave pad back 4 file\(s\)", out), out
            assert "LEFT=0" in out, out
        else:
            assert rc == 1 and "REFUSING" in out and "STARTED" not in out, out
            assert "could not be given back" in out, out
    finally:
        _wsl("rm -rf %s\n" % base, tmp_path, user="root")
