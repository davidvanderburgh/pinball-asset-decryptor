"""PAD-884: a Mac's container engine has to run 32-bit ARM, and colima's does
not out of the box (it registers only 386 and amd64; Docker Desktop also
registers ARM). The guest then died at its first program, "chroot: failed to
run command '/bin/sh': Exec format error". padbox.sh now runs docker/binfmt.sh
in a throwaway privileged box before every run, which registers the image's own
qemu-arm handler when the engine has none and leaves any handler alone.

binfmt.sh is run against a fake handler table (PAD_BINFMT_DIR); padbox.sh is
fed on stdin as in test_padbox_savestates.py, with a stand-in docker.
"""
import os
import subprocess

import pytest

from tests.conftest import HAS_BASH

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BINFMT = os.path.join(RIG, "docker", "binfmt.sh")
BOX = os.path.join(RIG, "docker", "padbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")

# Ubuntu 24.04's qemu-user-static line, as the image carries it.
CONF = (r":qemu-arm:M::\x7f\x45\x4c\x46\x01\x01\x01\x00\x00\x00\x00\x00\x00"
        r"\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff"
        r"\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:"
        r"/usr/libexec/qemu-binfmt/arm-binfmt-P:OPF")

ARM = "magic 7f454c4601010100000000000000000002002800"
AARCH64 = "magic 7f454c460201010000000000000000000200b700"


def _binfmt(table):
    """`table` is {name: (state, magic)} - the entries already registered."""
    lines = ["W=$(mktemp -d)", "trap 'rm -rf \"$W\"' EXIT",
             'mkdir -p "$W/t"; echo enabled > "$W/t/status"',
             "cat > \"$W/conf\" <<'EOF'", CONF, "EOF"]
    for name, (state, magic) in table.items():
        lines.append('printf "%%s\\ninterpreter /x\\nflags: F\\n%%s\\n" %s %s'
                     ' > "$W/t/%s"' % (state, magic.replace(" ", "\\ "), name))
    with open(BINFMT, "rb") as fh:
        body = fh.read().decode("utf-8")
    body = body.replace("set -u\n", "set -u\ntrap - EXIT\n", 1)
    script = "\n".join(lines + [
        'export PAD_BINFMT_DIR="$W/t" PAD_BINFMT_CONF="$W/conf"',
        "(", body, ")", "rc=$?",
        'echo "RC=$rc"',
        'for f in "$W/t"/*; do echo "== ${f##*/}"; cat "$f"; done', ""])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    return out.stdout.decode("utf-8", "replace")


@needs_bash
def test_an_engine_without_an_arm_handler_gets_the_images_one():
    text = _binfmt({"qemu-x86_64": ("enabled", "magic 7f454c4602"),
                    "qemu-aarch64": ("enabled", AARCH64)})
    assert "binfmt: registered" in text and "RC=0" in text, text
    reg = text.split("== register", 1)[1]
    assert CONF in reg, text


@needs_bash
def test_an_engine_that_has_one_is_left_alone():
    # Docker Desktop's name for it, not ours: matched on the magic
    text = _binfmt({"qemu-arm-dd": ("enabled", ARM)})
    assert "binfmt: present (qemu-arm-dd)" in text and "RC=0" in text, text
    assert "== register" not in text, text


@needs_bash
def test_a_disabled_handler_is_switched_on_not_replaced():
    text = _binfmt({"qemu-arm": ("disabled", ARM)})
    assert "binfmt: enabled (qemu-arm)" in text and "RC=0" in text, text
    assert "== register" not in text, text
    assert text.split("== qemu-arm", 1)[1].split()[0] == "1", text


_FAKE = r"""
d=$(mktemp -d)
cat > "$d/docker" <<'EOF'
#!/bin/bash
echo "DOCKER $*" >> "${0%/*}/calls"
case "$*" in *binfmt.sh*) echo "docker chatter"; echo "binfmt: ${BINFMT_SAYS:-present (qemu-arm)}" ;; esac
case "$1" in image) exit 0 ;; esac
exit 0
EOF
chmod +x "$d/docker"
export PATH="$d:$PATH"
trap 'cat "$d/calls" 2>/dev/null; rm -rf "$d"' EXIT
"""


def _box(*args, **env):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    exports = " ".join("%s=%s" % kv for kv in env.items())
    prelude = "\n".join([_FAKE, "set -- %s" % " ".join(args),
                         "export PAD_BOX_IMAGE=pad884-test:1 PAD_AUDIO=0 %s"
                         % exports, ""])
    out = subprocess.run(["bash", "-s"], input=(prelude + body).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    return out.returncode, [ln for ln in text.splitlines()
                            if ln.startswith("DOCKER run ")], text


@needs_bash
def test_every_run_asks_the_engine_for_arm_first_in_a_privileged_box():
    rc, runs, text = _box("watch.sh", "30")
    assert rc == 0, text
    assert len(runs) == 2, runs
    first, run = runs
    assert "binfmt.sh" in first and "--privileged" in first, first
    assert "/pad/rig:ro" in first and "pad884-test:1" in first, first
    assert "binfmt.sh" not in run and run.endswith("watch.sh 30"), run
    # a handler that was there already is not news
    assert "32-bit ARM" not in text, text


@needs_bash
def test_a_registration_is_said_and_a_failure_does_not_stop_the_run():
    rc, runs, text = _box("watch.sh", "30", BINFMT_SAYS="registered")
    assert rc == 0, text
    assert "registered the image's qemu handler" in text, text
    rc, runs, text = _box("watch.sh", "30", BINFMT_SAYS="registering\\ failed")
    assert rc == 0 and len(runs) == 2, text
    assert "could not check this container engine's 32-bit ARM" in text, text


@needs_bash
def test_status_reads_never_start_a_privileged_box():
    for script in ("status.sh", "alive.sh"):
        rc, runs, text = _box(script)
        assert not runs, (script, runs)
