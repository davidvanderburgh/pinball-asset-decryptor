"""``where="native"`` prerequisites are probed where the plugin's executor
runs: WSL on Windows, the host on macOS/Linux (PAD-220).  Barrels of Fun's
gpg was ``wsl``, so a Mac answered "n/a" and stayed green without GnuPG."""

from pinball_decryptor.core import prereqs
from pinball_decryptor.core.prereqs import Prerequisite, check_prerequisite
from pinball_decryptor.plugins.bof.manufacturer import build_prerequisites

GPG = Prerequisite(name="gpg", where="native", probe="command -v gpg",
                   reason="x", install_hint="hint")


def test_native_goes_to_wsl_on_windows(monkeypatch):
    # the static hint is the one for a PC whose runtime is not in use; a
    # runtime answer warmed by an earlier test on this worker must not
    # swap in the runtime's own hint
    monkeypatch.setattr(prereqs.runtime, "wsl_distro", lambda *a, **k: None)
    monkeypatch.setattr(prereqs, "_native_location", lambda: "wsl")
    seen = []
    monkeypatch.setattr(prereqs, "_probe_wsl",
                        lambda cmd: (seen.append(cmd), False, "no", "")[1:])
    monkeypatch.setattr(prereqs, "_probe_host",
                        lambda cmd: (_ for _ in ()).throw(AssertionError))
    res = check_prerequisite(GPG)
    assert seen == ["command -v gpg"]
    assert res.ok is False and res.install_hint == "hint"
    assert prereqs.probes_wsl(GPG) is True


def test_native_goes_to_the_host_on_a_mac(monkeypatch):
    monkeypatch.setattr(prereqs, "_native_location", lambda: "host")
    monkeypatch.setattr(prereqs, "_probe_wsl",
                        lambda cmd: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(prereqs, "_probe_host",
                        lambda cmd: (False, "bash: gpg: command not found"))
    res = check_prerequisite(GPG)
    assert res.ok is False
    assert "command not found" in res.message
    assert prereqs.probes_wsl(GPG) is False
    # never the "n/a (non-Windows)" green a wsl row gets off Windows
    assert "n/a" not in res.message


def test_native_location_follows_the_platform(monkeypatch):
    monkeypatch.setattr(prereqs.sys, "platform", "win32")
    assert prereqs._native_location() == "wsl"
    monkeypatch.setattr(prereqs.sys, "platform", "darwin")
    assert prereqs._native_location() == "host"
    monkeypatch.setattr(prereqs.sys, "platform", "linux")
    assert prereqs._native_location() == "host"


def test_host_probe_looks_in_the_homebrew_folders_on_a_mac(monkeypatch):
    """A GUI app on a Mac inherits launchd's PATH, which has no
    /opt/homebrew/bin, so a PATH-only lookup called an installed gpg
    missing."""
    monkeypatch.setattr(prereqs.sys, "platform", "darwin")
    # the launchd PATH, joined with THIS host's separator: the test runs on
    # Windows (";") as well as on the Linux and macOS CI legs (":")
    monkeypatch.setenv("PATH", prereqs.os.pathsep.join(["/usr/bin", "/bin"]))
    seen = {}

    def which(name, path=None):
        seen["path"] = path
        return "/opt/homebrew/bin/gpg" if "/opt/homebrew/bin" in (
            path or "") else None

    monkeypatch.setattr(prereqs.shutil, "which", which)
    ok, msg = prereqs._probe_host("command -v gpg")
    assert ok is True
    parts = seen["path"].split(prereqs.os.pathsep)
    assert parts[:2] == ["/opt/homebrew/bin", "/usr/local/bin"]
    assert parts[-2:] == ["/usr/bin", "/bin"]


def test_host_probe_off_a_mac_is_the_plain_path_lookup(monkeypatch):
    monkeypatch.setattr(prereqs.sys, "platform", "linux")
    monkeypatch.setattr(prereqs.shutil, "which", lambda name: "/usr/bin/gpg")
    assert prereqs._probe_host("command -v gpg") == (True, "gpg on PATH")


def test_bof_gpg_and_tar_are_native_and_the_mac_hint_names_install_missing():
    rows = {p.name: p for p in build_prerequisites("darwin")}
    assert rows["gpg"].where == "native"
    assert rows["tar"].where == "native"
    assert rows["gpg"].mac_pkg == "gnupg"
    assert "Install Missing" in rows["gpg"].install_hint
    assert "brew install gnupg" in rows["gpg"].install_hint
    assert "WSL" not in rows["gpg"].install_hint
    # GDRE and xvfb are the Linux/WSL write path's and stay wsl
    assert rows["gdre_tools"].where == "wsl"
    assert rows["xvfb-run"].where == "wsl"
    win = {p.name: p for p in build_prerequisites("win32")}
    assert win["gpg"].install_hint == "apt-get install gnupg (in WSL)"
    assert win["gpg"].where == "native"
