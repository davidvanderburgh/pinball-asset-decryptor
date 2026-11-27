"""PAD-1635: the app relaunched by an in-app update could not open folders
reached through a user-made junction (WinError 448, "untrusted mount point").

Inno Setup 6.7.0 - 6.7.3 turn on Windows' RedirectionGuard for Setup and
hand it down to the app the /RELAUNCH=1 entry starts.  Covered here:

* the build refuses those compilers and the release workflow pins 6.7.4;
* an ELEVATED app's update passes /NOREDIRECTIONGUARD (6.7.4 still hands
  the guard down when Setup had no unelevated user to drop to);
* multiboot_core._norm no longer raises when realpath cannot walk a path,
  and still resolves the junction, so the library gate keeps working.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pinball_decryptor.core import updater
from pinball_decryptor.webui import multiboot_core as mb

ROOT = Path(__file__).resolve().parents[1]


# --- the installer build ----------------------------------------------------

def test_iss_refuses_inno_6_7_0_to_6_7_3():
    iss = (ROOT / "installer" / "pinball_decryptor.iss").read_text(
        encoding="utf-8")
    assert "#if (Ver >= EncodeVer(6, 7, 0)) && (Ver < EncodeVer(6, 7, 4))" \
        in iss
    gate = iss.index("EncodeVer(6, 7, 4)")
    assert "#error" in iss[gate:gate + 200]


def test_release_workflow_pins_inno_6_7_4_by_hash():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    assert "choco install innosetup" not in wf
    assert "is-6_7_4/innosetup-6.7.4.exe" in wf
    assert ("a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c"
            in wf)
    # the runner's own older Inno must not be the one build.ps1 finds first
    assert "-InnoSetupPath $env:ISCC" in wf


def test_relaunch_entry_still_runs_as_the_original_user():
    iss = (ROOT / "installer" / "pinball_decryptor.iss").read_text(
        encoding="utf-8")
    line = next(l for l in iss.splitlines()
                if "Check: RelaunchRequested" in l and l.startswith("Filename"))
    assert "runasoriginaluser" in line


# --- the update's switches --------------------------------------------------

def test_unelevated_update_keeps_the_guard():
    assert updater.installer_args(elevated=False) == updater.INSTALLER_ARGS
    assert "/NOREDIRECTIONGUARD" not in updater.installer_args(False).split()


def test_elevated_update_turns_the_guard_off():
    args = updater.installer_args(elevated=True)
    assert args.startswith(updater.INSTALLER_ARGS)
    assert "/NOREDIRECTIONGUARD" in args.split()


def test_launch_passes_the_switch_when_elevated(tmp_path):
    calls = []

    def fake(hwnd, verb, path, args, cwd, show):
        calls.append(args)
        return 42

    assert updater.launch_installer_windows(tmp_path / "s.exe",
                                            shell_execute=fake, elevated=True)
    assert updater.launch_installer_windows(tmp_path / "s.exe",
                                            shell_execute=fake, elevated=False)
    assert "/NOREDIRECTIONGUARD" in calls[0].split()
    assert "/NOREDIRECTIONGUARD" not in calls[1].split()


# --- _norm when realpath cannot walk the path -------------------------------

def test_norm_reads_the_links_itself_when_realpath_fails(tmp_path,
                                                         monkeypatch):
    link = str(tmp_path / "images")
    lib = str(tmp_path / "library")
    path = os.path.join(link, "Stern", "spike2", "x.raw")

    def refuse(p, *a, **k):
        raise OSError(448, "untrusted mount point", p)

    def readlink(p):
        if os.path.normcase(p) == os.path.normcase(link):
            return lib
        raise OSError(22, "not a link", p)

    said = []
    monkeypatch.setattr(mb.os.path, "realpath", refuse)
    monkeypatch.setattr(mb.os, "readlink", readlink)
    monkeypatch.setattr(mb, "_NORM_FALLBACK_SAID", [])
    from pinball_decryptor.core import session_log
    monkeypatch.setattr(session_log, "append",
                        lambda text, level="info": said.append(level))
    want = os.path.normpath(os.path.join(lib, "Stern", "spike2", "x.raw"))
    assert mb._norm(path) == want.replace("\\", "/").lower()
    assert mb._norm(path + ".new").endswith("/x.raw.new")
    assert said == ["warning"]          # once per run, not per path


@pytest.mark.skipif(sys.platform != "win32", reason="RedirectionGuard is Windows")
def test_norm_under_the_real_guard(tmp_path):
    """The real mechanism: a junction made by this (unelevated) user, read
    from a process with EnforceRedirectionTrust on.  In a child process, so
    the guard never reaches the test worker."""
    target = tmp_path / "library"
    (target / "Stern").mkdir(parents=True)
    junction = tmp_path / "images"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction),
                        str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("cannot make a junction here: " + r.stdout + r.stderr)
    code = textwrap.dedent(r"""
        import ctypes, os, sys
        from ctypes import wintypes
        sys.path.insert(0, sys.argv[1])
        from pinball_decryptor.webui import multiboot_core as mb
        from pinball_decryptor.core import session_log
        session_log.append = lambda *a, **k: None
        p = os.path.join(sys.argv[2], "Stern", "x.raw")
        plain = mb._norm(p)
        ok = ctypes.WinDLL("kernel32").SetProcessMitigationPolicy(
            16, ctypes.byref(wintypes.DWORD(1)), 4)
        if not ok:
            print("NOGUARD"); sys.exit()
        try:
            os.path.realpath(os.path.dirname(p), strict=True)
            print("NOT ENFORCED"); sys.exit()
        except OSError as e:
            assert e.winerror == 448, e
        print("SAME" if mb._norm(p) == plain else "DIFF %s %s" % (mb._norm(p), plain))
    """)
    out = subprocess.run([sys.executable, "-c", code, str(ROOT),
                          str(junction)], capture_output=True, text=True,
                         timeout=120)
    if "NOGUARD" in out.stdout or "NOT ENFORCED" in out.stdout:
        pytest.skip("this Windows has no RedirectionGuard: " + out.stdout)
    assert out.stdout.strip() == "SAME", out.stdout + out.stderr
