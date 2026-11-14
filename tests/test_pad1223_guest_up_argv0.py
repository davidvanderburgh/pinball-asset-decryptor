"""PAD-1223: a `cp` of qemu is not the guest.

A PAD_PIVOT boot copies the static qemu into the guest root
(`cp -f /usr/bin/qemu-arm-static $R/.padqemu/game`) shortly before the guest
exists. pad_guest_up used to match ANY command line naming qemu, so on a cold
first start (slow copy) watch.sh's start wait took the copy for the game and
its poll loop then called the gap before /.padqemu/game "the game exited"
(Batman 66 in VPX: the LCD never came up on the first launch). The
interpreter must be argv0.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
PATTERN = r"^[^ ]*(arm-binfmt|qemu-arm)[^ /]*( |$)"


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as f:
        return f.read()


GUESTS = [
    # measured in WSL (binfmt, flags POF), 2026-11-13
    "/usr/libexec/qemu-binfmt/arm-binfmt-P /games/godzilla_le/game ./game",
    # the chroot's busybox sh before ./game execs, under binfmt
    "/usr/libexec/qemu-binfmt/arm-binfmt-P /bin/sh sh -c ./game",
    # a container whose binfmt names qemu itself
    "/usr/bin/qemu-arm-static ./game",
    "/usr/bin/qemu-arm ./game",
]

NOT_GUESTS = [
    "cp -f /usr/bin/qemu-arm-static /var/tmp/root/.padqemu/game",
    "cp -f /usr/bin/qemu-arm /var/tmp/root/.padqemu/game",
    "ldd /usr/bin/qemu-arm",
    "file -L /usr/libexec/qemu-binfmt/arm-binfmt-P",
    "bash /x/watch.sh 240",
]


def test_the_pattern_keeps_every_guest_and_drops_tools_run_on_qemu():
    for line in GUESTS:
        assert re.search(PATTERN, line), line
    for line in NOT_GUESTS:
        assert not re.search(PATTERN, line), line


def test_pad_guest_up_uses_the_argv0_pattern():
    text = _read("padpath.sh")
    assert "PAD_GUEST_INTERP_RE='" + PATTERN + "'" in text
    body = text[text.index("pad_guest_up() {"):]
    body = body[:body.index("\n}")]
    assert 'pad_pids -f "$PAD_GUEST_INTERP_RE"' in body
    assert "'arm-binfmt|qemu-arm'" not in body


def test_the_other_guest_checks_agree():
    assert PATTERN in _read("longplay.sh")
    assert PATTERN in _read("guestmem.py")
    assert "pad_pids -f 'arm-binfmt|qemu-arm'" not in _read("longplay.sh")


def test_the_pivot_boot_still_copies_qemu_before_the_guest():
    # the copy this guards against is still there, so the guard still matters
    run = _read("run_game.sh")
    assert 'cp -f "$QEMU" "$R/.padqemu/game"' in run
    assert "exec /.padqemu/game ./game" in run
