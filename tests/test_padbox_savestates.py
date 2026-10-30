"""PAD-835: save states on a Mac - what padbox.sh asks docker for.

Save states need a root guest that criu can freeze, and on a Mac the rig runs
in a container (docker/padbox.sh). So a save-state Start is a root,
privileged box; the save, load and slot scripts run as root INSIDE the box
that holds the game; with no box up, the slots are read from the rootfs volume
by a throwaway one. And a run with save states off is the box it always was.

padbox.sh is fed on stdin, as test_padbox_build_watch.py does it (the bash on
PATH may be WSL's, which cannot open a Windows path), with ``docker`` a stand-in
script that prints what it was asked. A script, not a function, because
padbox.sh ``exec``s docker, and exec cannot run a function.
"""
import os
import subprocess

import pytest

from tests.conftest import HAS_BASH

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BOX = os.path.join(RIG, "docker", "padbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")

_FAKE = r"""
d=$(mktemp -d)
cat > "$d/docker" <<'EOF'
#!/bin/bash
echo "DOCKER $*"
case "$1" in
    ps) [ -n "${BOX_UP:-}" ] && echo pad-spike2 ;;
    image) [ -z "${NO_IMAGE:-}" ] ;;
    *) exit 0 ;;
esac
EOF
chmod +x "$d/docker"
export PATH="$d:$PATH"
"""


def _box(*args, **env):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    exports = " ".join("%s=%s" % kv for kv in env.items())
    prelude = "\n".join([
        _FAKE,
        "set -- %s" % " ".join(args),
        "export PAD_BOX_IMAGE=pad835-test:1 PAD_AUDIO=0 %s" % exports,
        "",
    ])
    out = subprocess.run(["bash", "-s"], input=(prelude + body).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, [ln for ln in text.splitlines()
                            if ln.startswith("DOCKER ")], text


def _one(calls, verb):
    hits = [c for c in calls if c.split()[1] == verb]
    assert len(hits) == 1, calls
    return hits[0].split()[2:]


@needs_bash
def test_a_save_state_start_is_a_root_privileged_box():
    rc, calls, text = _box("watch.sh", "30", PAD_PIVOT="1")
    assert rc == 0, text
    run = _one(calls, "run")
    assert "--privileged" in run, run
    assert run[run.index("-u") + 1] == "0", run
    assert "PAD_PIVOT=1" in run and "PAD_USER=pad" in run, run
    # the rest of the box is what it always was
    assert "SYS_ADMIN" in run and "/dev/fuse" in run, run
    assert run[-3:] == ["pad835-test:1", "watch.sh", "30"], run


@needs_bash
def test_a_start_without_save_states_is_the_box_it_always_was():
    rc, calls, text = _box("watch.sh", "30")
    assert rc == 0, text
    run = _one(calls, "run")
    assert "--privileged" not in run and "-u" not in run, run
    assert "PAD_PIVOT=1" not in run, run


@needs_bash
def test_the_save_state_scripts_run_as_root_in_the_box_holding_the_game():
    for script in ("savegame.sh", "loadgame.sh", "slots.sh", "status.sh",
                   "killgame.sh", "alive.sh", "restartgame.sh"):
        rc, calls, text = _box(script, "s1", BOX_UP="1")
        assert rc == 0, text
        ex = _one(calls, "exec")
        assert ex == ["-u", "0", "pad-spike2", "bash", "/pad/rig/" + script,
                      "s1"], (script, ex)
        assert not [c for c in calls if c.split()[1] == "run"], calls


@needs_bash
def test_a_load_carries_its_kill_request_into_the_box():
    rc, calls, text = _box("loadgame.sh", "s1", BOX_UP="1",
                           PAD_RESTORE_KILL="1")
    ex = _one(calls, "exec")
    assert ex[:4] == ["-u", "0", "-e", "PAD_RESTORE_KILL=1"], ex


@needs_bash
def test_save_and_load_with_no_box_say_so_and_start_nothing():
    for script in ("savegame.sh", "loadgame.sh"):
        rc, calls, text = _box(script, "s1")
        assert rc == 1, text
        assert "the emulator is not running" in text, text
        assert not [c for c in calls
                    if c.split()[1] in ("run", "exec", "build")], calls


@needs_bash
def test_the_slots_with_no_box_are_read_from_the_rootfs_volume_as_root():
    rc, calls, text = _box("slots.sh", "list")
    assert rc == 0, text
    run = _one(calls, "run")
    assert run[:3] == ["--rm", "-u", "0"], run
    assert "pad-spike2-rootfs:/pad/rootfs" in run, run
    assert run[-3:] == ["pad835-test:1", "/pad/rig/slots.sh", "list"], run
    # a status read never builds the image
    assert not [c for c in calls if c.split()[1] == "build"], calls


@needs_bash
def test_the_slots_before_any_image_never_build_one():
    rc, calls, text = _box("slots.sh", "list", NO_IMAGE="1")
    assert rc == 1, text
    assert "has not been set up yet" in text, text
    assert not [c for c in calls if c.split()[1] in ("build", "run")], calls
