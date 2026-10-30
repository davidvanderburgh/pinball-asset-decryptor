"""core.desktop.guard_child_env: the frozen Linux app's system programs get
the system's libraries, not the bundle's (PAD-837).

Found in the Docker image: since v1.292.0 the AppImage is built on Ubuntu
22.04, so the libstdc++ it bundles is OLDER than a 24.04 system's, and the
system ffmpeg the Audio tab runs died on it ("GLIBCXX_3.4.32 not found")
because every child inherited PyInstaller's LD_LIBRARY_PATH.  The Audio
tab then said "(preview needs ffmpeg)" with ffmpeg installed.
"""

import os
import subprocess
import sys

import pytest

from pinball_decryptor.core import desktop

BUNDLE = os.path.realpath(os.path.join(os.sep, "opt", "pad", "usr", "bin"))
INTERNAL = os.path.join(BUNDLE, "_internal")


@pytest.fixture
def frozen_env(monkeypatch):
    """This process as the frozen app sees itself: LD_LIBRARY_PATH at the
    bundle, the system's value stashed in _ORIG."""
    monkeypatch.setenv("LD_LIBRARY_PATH", INTERNAL)
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    monkeypatch.setattr(desktop, "_bundle_dirs", lambda: [BUNDLE])


def test_an_inherited_bundle_path_is_given_the_systems_back(frozen_env):
    env = desktop.child_env(None, bundle_dirs=[BUNDLE])
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_a_copy_of_our_environment_counts_as_inherited(frozen_env):
    """The usual call site: os.environ.copy() plus a variable of its own."""
    mine = dict(os.environ, PAD_SLOT="2")
    env = desktop.child_env(mine, bundle_dirs=[BUNDLE])
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert env["PAD_SLOT"] == "2"


def test_a_library_path_the_caller_chose_is_left_alone(frozen_env):
    mine = dict(os.environ, LD_LIBRARY_PATH="/opt/gdre_tools")
    env = desktop.child_env(mine, bundle_dirs=[BUNDLE])
    assert env["LD_LIBRARY_PATH"] == "/opt/gdre_tools"


def test_programs_inside_the_bundle_are_not_system_programs():
    dirs = [BUNDLE]
    assert not desktop._system_program(
        [os.path.join(BUNDLE, "pinball-decryptor"), "--flash-helper"],
        None, False, None, dirs)
    assert not desktop._system_program(
        ["x"], os.path.join(INTERNAL, "imageio_ffmpeg", "ffmpeg"), False,
        None, dirs)
    assert desktop._system_program(["/usr/bin/ffmpeg", "-version"], None,
                                   False, None, dirs)
    assert desktop._system_program("ffmpeg -version", None, True, None, dirs)
    # Not on PATH at all: whatever it is, it is not ours.
    assert desktop._system_program(["no-such-program-pad837"], None, False,
                                   None, dirs)


def test_only_a_frozen_linux_app_installs_it(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert desktop.guard_child_env() is False
    assert getattr(subprocess.Popen.__init__, "_pad_orig", None) is None


def test_every_subprocess_call_gets_the_systems_library_path(frozen_env,
                                                             monkeypatch):
    """End to end through subprocess.run, the way the Audio tab calls
    ffmpeg: no env argument at all."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    original = subprocess.Popen.__init__
    try:
        assert desktop.guard_child_env() is True
        assert desktop.guard_child_env() is True        # once, not twice
        assert subprocess.Popen.__init__._pad_orig is original
        probe = ("import os; print(os.environ.get('LD_LIBRARY_PATH')); "
                 "print(os.environ.get('LD_LIBRARY_PATH_ORIG'))")
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True,
                             timeout=60).stdout.split()
        assert out == ["/usr/local/lib", "None"]
        # ...and the same when the caller passes a copy of ours.
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, timeout=60,
                             env=dict(os.environ)).stdout.split()
        assert out == ["/usr/local/lib", "None"]
    finally:
        subprocess.Popen.__init__ = original
