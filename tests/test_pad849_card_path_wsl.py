r"""PAD-849: a card the app can open must be a card the emulator can open.

WSL mounts the PC's local drives and nothing else.  A card on a network share,
a drive mapped to one, or a ``subst`` drive opened fine in the app, and was
handed to the rig as a path that did not exist inside WSL - so the emulator
said "Pick a card image" about the card that had been picked, every Start.

``rig.wsl_path`` now spells a subst drive as its folder and a share as
``/mnt/unc/<server>/<share>/...``, and ``rig.reach_argv`` mounts that share
ahead of a root rig command.  Proven on the real rig in the ticket: Foo
Fighters LE booted from ``\\localhost\D$`` and from a subst drive, where main
said "no image at ...".
"""

import os

import pytest

from pinball_decryptor.webui import emulate_core
from pinball_decryptor.webui import rig as _rig


@pytest.fixture
def windows(monkeypatch):
    r"""A Windows host whose Q: is ``subst Q: D:\cards`` and whose N: is a
    network drive mapped to ``\\NAS\Pinball``; every other letter local."""
    targets = {"Q": r"D:\cards", "N": r"\\NAS\Pinball"}
    monkeypatch.setattr(_rig.sys, "platform", "win32")
    monkeypatch.setattr(_rig, "_drive_target",
                        lambda letter: targets.get(letter.upper()))


@pytest.mark.parametrize("win, wsl", [
    (r"C:\cards\gz.raw", "/mnt/c/cards/gz.raw"),
    (r"Q:\gz.raw", "/mnt/d/cards/gz.raw"),
    (r"N:\Stern\ff.raw", "/mnt/unc/nas/pinball/Stern/ff.raw"),
    (r"\\NAS\Pinball\Stern\ff.raw", "/mnt/unc/nas/pinball/Stern/ff.raw"),
    (r"\\?\UNC\NAS\Pinball\ff.raw", "/mnt/unc/nas/pinball/ff.raw"),
    (r"\\?\C:\cards\gz.raw", "/mnt/c/cards/gz.raw"),
    (r"\\nas\C$\x y\gz.raw", "/mnt/unc/nas/c$/x y/gz.raw"),
    ("/home/u/gz.raw", "/home/u/gz.raw"),
])
def test_wsl_path_spells_what_wsl_can_see(windows, win, wsl):
    assert _rig.wsl_path(win) == wsl


def test_linux_desktop_paths_untouched(monkeypatch):
    monkeypatch.setattr(_rig.sys, "platform", "linux")
    assert _rig.wsl_path("/home/u/gz.raw") == "/home/u/gz.raw"
    assert _rig.wsl_path(r"C:\cards\gz.raw") == "/mnt/c/cards/gz.raw"


def test_real_drive_target_of_a_local_drive_is_none():
    if os.name != "nt":
        pytest.skip("Windows lookups")
    assert _rig._drive_target("C") is None


def _root(*rest):
    return ["wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e"] + list(rest)


def test_root_command_mounts_the_share_first(windows):
    card = _rig.wsl_path(r"\\NAS\Pinball\Stern\ff.raw")
    argv = _root("env", "PAD_CARD=" + card, "bash", "/x/watch.sh", "3")
    got = _rig.reach_argv(argv)
    assert got[:6] == argv[:6]
    assert got[6:8] == ["sh", "-c"]
    step = got[8]
    assert "mount -t drvfs '//nas/pinball' '/mnt/unc/nas/pinball'" in step
    assert step.startswith("mountpoint -q '/mnt/unc/nas/pinball'")
    assert step.endswith('exec "$@"')
    assert got[9] == "pad-reach" and got[10:] == argv[6:]


def test_share_named_twice_is_mounted_once(windows):
    a = _rig.wsl_path(r"\\NAS\Pinball\a.raw")
    b = _rig.wsl_path(r"\\nas\pinball\b\c.raw")
    assert _rig.unc_mounts(["PAD_CARD=" + a, b]) == [
        ("//nas/pinball", "/mnt/unc/nas/pinball")]


def test_failed_mount_says_which_share(windows):
    step = _rig.reach_argv(_root("bash", "/mnt/unc/nas/pinball/x.raw"))[8]
    assert "could not open the network share \\\\nas\\pinball from WSL" in step
    # printf, not echo: dash's echo turns the \n of \\nas into a new line
    assert "printf '%s\\n'" in step


@pytest.mark.parametrize("argv", [
    ["wsl.exe", "-e", "bash", "/x/cardmount.sh", "/mnt/unc/nas/p/x.raw"],
    _root("bash", "/x/watch.sh", "/mnt/d/cards/gz.raw"),
])
def test_left_alone_without_root_or_a_share(windows, argv):
    assert _rig.reach_argv(argv) == argv


def test_every_root_launcher_mounts(windows, monkeypatch):
    """Spike 2's own root launchers and the shared one (Spooky, AP, BoF, DP,
    Pinball Brothers, JJP) all go through reach_argv."""
    card = _rig.wsl_path(r"N:\ff.raw")
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setattr(emulate_core, "_rig_env", lambda: [])
    monkeypatch.setattr(emulate_core, "wsl_home", lambda: "/home/u")
    monkeypatch.setattr(emulate_core, "_wsl_head",
                        lambda root=False: ["wsl.exe"]
                        + (["-u", "root"] if root else []) + ["-e"])
    for argv in (emulate_core.rig_cmd_root("cardmount.sh", card),
                 emulate_core.watch_cmd(3, ["PAD_CARD=" + card]),
                 _rig.rig_cmd_root("C:/rig", "watch.sh", card)):
        assert "pad-reach" in argv, argv


def test_rig_message_names_the_card_it_cannot_see():
    """The fresh-machine message no longer says "Pick a card image" when a
    card WAS picked."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "tools", "spike2_emu",
                            "ensurebuild.sh"), encoding="utf-8").read()
    body = src[src.index("pad_ensure_rootfs() {"):]
    body = body[:body.index("\n}\n")]
    unseen = body.index('[ -n "$_card" ] && [ ! -f "$_card" ]')
    assert unseen < body.index("Pick a card image")
    assert "pad_card_unseen" in body
    assert "/mnt/unc/*)" in src[src.index("pad_card_unseen() {"):]
