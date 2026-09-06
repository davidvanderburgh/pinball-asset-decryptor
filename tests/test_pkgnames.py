"""The Debian-to-Arch package name table (core/pkgnames.py) and the places it
is applied: the prerequisite strip's hints, the Emulate tab's printed advice
on a Linux desktop, and the rig's own facts behind that advice.

Background: a user ran the app from source on Omarchy (an Arch spin) on
2026-09-06, translating every apt name by hand, because nothing in the app
spoke pacman.  The installer got its own table in shell the same day; this
module is the app's copy, and the first test here is what keeps the two the
same table.
"""
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.core import pkgnames

REPO = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = REPO / "installer" / "install_prerequisites_linux.sh"
RIG = REPO / "tools" / "spike2_emu"
PLUGINS = sorted((REPO / "pinball_decryptor" / "plugins").rglob("manufacturer.py"))


def _manifest(src, name):
    body = src.split(name + "=(", 1)[1].split("\n)", 1)[0]
    return {int(k): v.split() for k, v in
            re.findall(r'^\s*\[(\d+)\]="([^"]*)"', body, re.M)}


def test_the_python_table_and_the_installers_shell_table_agree():
    """Two copies of one table: the installer's, in shell because it runs
    without Python, and this module's, for the app.  Held together here
    rather than trusted to stay so: every apt list in the installer,
    translated by the Python table, must be the installer's own pacman list
    for the same manufacturer, and its AUR list too."""
    src = INSTALLER.read_text(encoding="utf-8")
    apt = _manifest(src, "MFR_PACKAGES")
    pac = _manifest(src, "MFR_PACMAN_PACKAGES")
    aur = _manifest(src, "MFR_AUR_PACKAGES")
    assert set(apt) == set(pac), "the two manifests list different manufacturers"
    for mfr, names in apt.items():
        want_pac, want_aur = pkgnames.to_pacman(names)
        assert set(want_pac) <= set(pac[mfr]), (
            f"[{mfr}] the Python table translates to {want_pac}, and the "
            f"installer's pacman list lacks {set(want_pac) - set(pac[mfr])}")
        # python-pip is pacman's alone: Arch's python ships no pip, and the
        # installer's pip step needs one.  It translates from nothing.
        extra = set(pac[mfr]) - set(want_pac)
        assert extra <= {"python-pip"}, (
            f"[{mfr}] the installer's pacman list has {extra}, which no apt "
            f"name translates to - one table moved without the other")
        assert set(want_aur) == set(aur.get(mfr, [])), (mfr, want_aur, aur)


def test_every_plugins_hint_translates_with_no_debian_name_left():
    """The hints are literal strings in each plugin.  A new one written in
    apt's spelling for a package this table does not know would reach an Arch
    user untranslated, so every apt name any plugin hints at must be one the
    table maps or one spelled the same on Arch - the latter checked against
    the installer's pacman lists, which are the names Arch actually has."""
    src = INSTALLER.read_text(encoding="utf-8")
    arch_has = {n for names in _manifest(src, "MFR_PACMAN_PACKAGES").values()
                for n in names}
    debian = list(pkgnames.ARCH_NAMES) + list(pkgnames.AUR_NAMES)
    seen = 0
    for path in PLUGINS:
        for m in re.finditer(r"apt-get install ((?:[\w.+-]+)(?: [\w.+-]+)*)",
                             path.read_text(encoding="utf-8")):
            for name in m.group(1).split():
                seen += 1
                assert (name in pkgnames.ARCH_NAMES
                        or name in pkgnames.AUR_NAMES
                        or name in arch_has), (
                    f"{path.parent.name}: hints at {name}, which the Arch "
                    f"table does not know and no pacman list carries")
            out = pkgnames.localize_hint(m.group(0), pm="pacman")
            assert "apt-get" not in out, out
            # By token, not by regex: `\b` reads the hyphen in
            # xorg-server-xvfb as a boundary and finds "xvfb" inside it.
            left = [d for d in debian if d in out.split()]
            assert not left, (
                f"{path.parent.name}: {left} survive translation: {out}")
    assert seen, "no plugin hints found - the regex or the layout moved"


def test_a_hint_is_spelled_for_the_linux_it_is_shown_on(monkeypatch):
    h = "apt-get install zstd python3-zstandard (in WSL)"
    assert (pkgnames.localize_hint(h, "pacman")
            == "sudo pacman -S --needed zstd python-zstandard")
    # An apt desktop is still not WSL.
    assert (pkgnames.localize_hint(h, "apt")
            == "apt-get install zstd python3-zstandard")
    # Windows and macOS: as written, "(in WSL)" and all.
    monkeypatch.setattr(pkgnames, "linux_package_manager", lambda: None)
    assert pkgnames.localize_hint(h) == h
    # A multi-platform hint keeps its other lines and its "(Linux)" tag.
    multi = ("brew install ffmpeg        (macOS)\n"
             "apt-get install ffmpeg       (Linux)")
    out = pkgnames.localize_hint(multi, "pacman").splitlines()
    assert out[0] == "brew install ffmpeg        (macOS)"
    assert out[1] == "sudo pacman -S --needed ffmpeg       (Linux)"
    # One that names no apt package is never touched, and neither is nothing.
    wsl = "Run `wsl --set-version Ubuntu 2` in an admin PowerShell"
    assert pkgnames.localize_hint(wsl, "pacman") == wsl
    assert pkgnames.localize_hint("", "pacman") == ""


def test_the_tabs_commands_split_the_aur_from_the_repositories():
    cmds = pkgnames.pacman_commands(
        ["qemu-user-static", "gcc-arm-linux-gnueabihf", "gcc libc6-dev",
         "ffmpeg"])
    assert cmds[0] == ("sudo pacman -S --needed qemu-user-static "
                       "qemu-user-static-binfmt gcc ffmpeg")
    assert cmds[1].startswith("yay -S arm-linux-gnueabihf-gcc"), cmds
    assert "AUR" in cmds[1]
    assert "libc6-dev" not in " ".join(cmds)
    assert pkgnames.pacman_commands([]) == []
    assert (pkgnames.binfmt_advice("pacman")
            == "sudo pacman -S --needed qemu-user-static qemu-user-static-binfmt")
    assert pkgnames.binfmt_advice(None) == "sudo apt install qemu-user-static"
    assert pkgnames.binfmt_advice("apt") == "sudo apt install qemu-user-static"


def test_the_prerequisite_result_carries_the_localized_hint(monkeypatch):
    """check_prerequisite is the one place both the strip's tooltip and the
    log's `fix:` line read from, so the translation lives there and not in
    either of them."""
    from pinball_decryptor.core import prereqs
    monkeypatch.setattr(pkgnames, "linux_package_manager", lambda: "pacman")
    p = prereqs.Prerequisite(
        name="zstd", where="host", probe="python:no_such_module_pad_test",
        reason="x", install_hint="apt-get install zstd python3-zstandard (in WSL)")
    r = prereqs.check_prerequisite(p)
    assert not r.ok
    assert r.install_hint == "sudo pacman -S --needed zstd python-zstandard"
    monkeypatch.setattr(pkgnames, "linux_package_manager", lambda: None)
    assert (prereqs.check_prerequisite(p).install_hint
            == "apt-get install zstd python3-zstandard (in WSL)")


def test_setupcheck_reports_the_package_manager_it_found():
    """The tab's advice is spelled from this fact, and it has to be the
    RIG's answer - the machine the run happens on - not the app's guess."""
    check = (RIG / "setupcheck.sh").read_text(encoding="utf-8")
    block = check[check.index("AND WHAT IT INSTALLS PACKAGES WITH"):]
    block = block[block.index("if command -v apt-get"):]
    block = block[:block.index("\nfi\n") + 4]
    for pm, fake in (("apt", "apt-get"), ("pacman", "pacman"), ("none", None)):
        harness = "T=$(mktemp -d)\n"
        if fake:
            harness += ("printf '#!/bin/sh\\nexit 0\\n' > \"$T/%s\"\n"
                        "chmod +x \"$T/%s\"\n" % (fake, fake))
        harness += 'PATH="$T"\n' + block
        r = subprocess.run(["bash", "-s"], input=harness.encode("utf-8"),
                           capture_output=True, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert "pm=%s" % pm in out, (pm, out, r.stderr)


def test_the_binfmt_advice_knows_archs_file_and_package():
    """Arch's qemu-user-static-binfmt puts the conf at qemu-arm-static.conf,
    not Debian's qemu-arm.conf, and registers it through systemd-binfmt; a
    machine with no conf at all and no apt is told pacman's package, both
    halves of it.  Static, because the function reads the real /usr/lib and
    a WSL Ubuntu with the emulator set up answers its first branch."""
    eb = (RIG / "ensurebuild.sh").read_text(encoding="utf-8")
    fn = eb[eb.index("_pad_binfmt_advice() {"):]
    fn = fn[:fn.index("\n}")]
    assert "/usr/lib/binfmt.d/qemu-arm-static.conf" in fn
    assert "systemctl restart systemd-binfmt" in fn
    assert "pacman -S --needed qemu-user-static qemu-user-static-binfmt" in fn
    # ...and Debian's own answers are still there, ahead of it.
    assert fn.index("qemu-arm.conf") < fn.index("qemu-arm-static.conf")
    assert "update-binfmts --import qemu-arm" in fn
    assert fn.rstrip().endswith('echo "sudo apt install qemu-user-static"\n    fi')
