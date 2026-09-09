"""The playfield window has to say WHICH Linux it is talking to.

Reported 2026-09-09: clicking switches on the virtual playfield did nothing,
while the game window's keyboard worked perfectly in the same run.

That asymmetry is the whole diagnosis.  The renderer is a process INSIDE the
run, so its key presses never cross a distro boundary; this window is a Windows
process and every click shells back into Linux to drive the switch.  It did that
with a bare ``wsl.exe -e``, which runs in the DEFAULT distro -- fine while there
was only one, and wrong the moment the app grew its own PAD-Runtime.  The game
sat in one Linux and every click was delivered into another, writing a switch
ring nobody was reading.  Measured on one run: 68 keyboard events reached the
guest and 0 playfield events did, while the *other* distro's ring kept ticking.

Naming the distro is only half of it.  A fresh ``wsl.exe`` starts with that
distro's own defaults, so the helper would resolve ``$HOME/spike2root`` -- and
under the runtime distro the rig lives on a shared volume somewhere else.  So
the rig root crosses back too, in its POSIX spelling: ``PAD_ROOT`` reaches the
window translated to ``\\\\wsl.localhost\\...`` (WSLENV marks it ``/p``), which is
exactly the wrong thing to hand a Linux helper.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


@pytest.fixture()
def pf(monkeypatch):
    """``playfield``'s two command builders, as a Windows process sees them."""
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    monkeypatch.setenv("PAD_ROOT", r"\\wsl.localhost\PAD-Runtime\rig")
    import playfield
    return playfield


def test_the_distro_is_named_when_the_run_says_which(pf, monkeypatch):
    monkeypatch.setenv("PAD_WSL_DISTRO", "PAD-Runtime")
    assert pf.wsl_head() == ["wsl.exe", "-d", "PAD-Runtime"]
    assert pf.wsl_head(root=True) == ["wsl.exe", "-d", "PAD-Runtime",
                                      "-u", "root"]


def test_without_a_named_distro_it_behaves_as_it_always_did(pf, monkeypatch):
    """A run started by hand, or an older watch.sh: the default distro is still
    the right answer, and must not become an error."""
    monkeypatch.delenv("PAD_WSL_DISTRO", raising=False)
    assert pf.wsl_head() == ["wsl.exe"]
    assert pf.wsl_head(root=True) == ["wsl.exe", "-u", "root"]


def test_the_rig_root_crosses_back_in_its_posix_spelling(pf, monkeypatch):
    """Not the ``\\\\wsl.localhost`` form the window itself was handed."""
    monkeypatch.setenv("PAD_ROOT_WSL", "/mnt/wsl/paddata/spike2/spike2root")
    assert pf.wsl_rig_env() == ["PAD_ROOT=/mnt/wsl/paddata/spike2/spike2root"]


def test_the_windows_spelling_is_never_sent_back(pf, monkeypatch):
    """PAD_ROOT alone must not be forwarded: a helper would try to open a UNC
    string as a directory."""
    monkeypatch.delenv("PAD_ROOT_WSL", raising=False)
    assert pf.wsl_rig_env() == []
    assert not any("wsl.localhost" in a for a in pf.wsl_rig_env())


def test_a_switch_click_is_addressed_to_the_runs_own_linux(pf, monkeypatch):
    """The end of the report, as one assertion over the built command."""
    monkeypatch.setenv("PAD_WSL_DISTRO", "PAD-Runtime")
    monkeypatch.setenv("PAD_ROOT_WSL", "/mnt/wsl/paddata/spike2/spike2root")
    cmd = (pf.wsl_head() + ["-e", "env", "PAD_SW_SRC=f"] + pf.wsl_rig_env()
           + ["python3", "/rig/swpoke.py", "59"])
    assert cmd[:3] == ["wsl.exe", "-d", "PAD-Runtime"]
    assert "PAD_ROOT=/mnt/wsl/paddata/spike2/spike2root" in cmd
    assert "PAD_SW_SRC=f" in cmd          # still tagged as this window


def test_every_wsl_call_in_the_window_goes_through_the_helper(pf):
    """Four call sites had the distro missing, not one.  A fifth added later
    with a bare ``wsl.exe`` would be the same bug again, silently."""
    src = open(os.path.join(RIG, "playfield.py"), encoding="utf-8").read()
    # The only literal left is the one inside wsl_head() itself.
    assert src.count('["wsl.exe"') == 1
    assert '"wsl.exe", "-e"' not in src
    assert '"wsl.exe", "-u"' not in src


def test_watch_sh_exports_the_posix_root_for_the_round_trip(pf):
    """The window can only forward what it is given."""
    src = open(os.path.join(RIG, "padpath.sh"), encoding="utf-8").read()
    assert "PAD_ROOT_WSL=$ROOT" in src
    assert "PAD_ROOT_WSL" in src.split("WSLENV=")[1].split("\n")[0]
