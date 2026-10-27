"""PAD-769: the Mac's container build is narrated, and a silent one is stopped.

A Mac user pressed Start, the log said "[box] building pad-spike2-emu:...
(first time takes a few minutes)", and twenty minutes later it still said
that, with the Emulate tab's state reading "Not running".  Nothing told a slow
download from a docker that had stopped answering.

padbox.sh is run here with ``docker`` replaced by a shell function (so the
test needs no Docker and no Mac), fed on stdin for the reason
test_emulate_setup_check.py's test_setupcheck_still_parses_as_key_value
writes out: the ``bash`` on PATH may be WSL's, which cannot open a Windows
path.  The minute is shortened to a second (PAD_BOX_TICK_S) so the heartbeat
and the silence limit can be seen in a few seconds.
"""
import os
import re
import subprocess
import time

import pytest

from tests.conftest import HAS_BASH
from pinball_decryptor.webui import emulate_core as core

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BOX = os.path.join(RIG, "docker", "padbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")

# `exec` so the background job IS the stand-in docker, as the real one is a
# single process: killing it has to close the pipe it writes to.
_DOCKERS = {
    # never quiet for longer than a second, against a 3 s silence limit
    "ok": 'echo "#5 [1/2] FROM ubuntu"; sleep 1; echo "#6 [2/2] RUN apt-get";'
          ' for i in 1 2 3 4; do sleep 1; echo "#6 $i.0 Get:$i"; done;'
          ' echo "#6 DONE 5.0s"; return 0',
    "silent": 'echo "#5 [1/2] FROM ubuntu"; exec sleep 60',
    "fails": 'echo "#6 [2/2] RUN apt-get"; echo "ERROR: no space left";'
             ' return 17',
}


def _run_build(kind):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    prelude = "\n".join([
        "set -- --build",
        "export PAD_BOX_IMAGE=pad769-test:1 PAD_BOX_TICK_S=1"
        " PAD_BOX_SILENT_S=3",
        # `local` and PIPESTATUS behave the same in a function body as at the
        # top of the script; `command -v docker` accepts a function.
        "docker() {",
        '  case "$1" in',
        "    info) return 0 ;;",
        '    build) [ "$BUILDKIT_PROGRESS" = plain ] || echo NOT-PLAIN;'
        " %s ;;" % _DOCKERS[kind],
        "    *) return 0 ;;",
        "  esac",
        "}",
        # padbox.sh's own `set -u` follows; the stub sets nothing it reads
        "",
    ])
    t0 = time.time()
    out = subprocess.run(["bash", "-s"], input=(prelude + body).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=90)
    return (out.returncode, out.stdout.decode("utf-8", "replace"),
            time.time() - t0)


@needs_bash
def test_a_build_is_narrated_with_plain_progress_and_a_heartbeat():
    rc, text, _secs = _run_build("ok")
    assert rc == 0, text
    assert "NOT-PLAIN" not in text
    assert "[box] building pad769-test:1" in text
    assert "#6 [2/2] RUN apt-get" in text
    # the test's "minute" is shorter than the watcher's 2 s look, so the
    # count may skip; with the real 60 s minute it counts 1, 2, 3...
    assert re.search(r"^\[box\] still building the emulator container: "
                     r"\d+ min so far$", text, re.M), text
    assert "did not build" not in text


@needs_bash
def test_a_build_docker_stops_talking_to_is_stopped_and_says_where_to_look():
    rc, text, secs = _run_build("silent")
    assert rc != 0, text
    assert "docker has printed nothing" in text
    assert "Open Docker Desktop" in text
    assert "the emulator container did not build" in text
    # stopped at the limit, not left to the stand-in's 60 s
    assert secs < 40, (secs, text)


@needs_bash
def test_a_failed_build_says_so_and_keeps_dockers_exit_code():
    rc, text, _secs = _run_build("fails")
    assert rc == 17, text
    assert "ERROR: no space left" in text
    assert "the emulator container did not build (docker exit 17)" in text


def test_the_state_label_follows_the_build_and_lets_go_when_it_ends():
    st = {}
    feed = [
        ("[box] some path is outside Docker's file sharing", None),
        ("[box] building pad-spike2-emu:c1 (first time takes a few minutes)",
         "Building the emulator container…"),
        ("#0 building with \"desktop-linux\" instance", None),
        ("#5 [1/6] FROM docker.io/library/ubuntu:24.04",
         "Building the emulator container (step 1 of 6)"),
        ("#6 [2/6] RUN apt-get update",
         "Building the emulator container (step 2 of 6)"),
        ("#6 12.05 Get:114 http://archive.ubuntu.com", None),
        ("[box] still building the emulator container: 3 min so far",
         "Building the emulator container (step 2 of 6, 3 min)"),
        ("[box] starting; the picture appears at vnc://", ""),
        ("[box] still building the emulator container: 4 min so far", None),
    ]
    for line, want in feed:
        assert core.box_build_line(line, st) == want, line


@pytest.mark.parametrize("end", [
    "[box] the emulator container did not build (docker exit 1); ...",
    "[box] docker has printed nothing for 10 min, so the build is stopped.",
])
def test_a_build_that_ends_badly_clears_the_label(end):
    st = {}
    core.box_build_line("[box] building x (first time takes a few minutes)",
                        st)
    assert core.box_build_line(end, st) == ""


def test_lines_outside_a_build_change_nothing():
    st = {}
    for line in ("#6 [2/6] RUN apt-get", "[box] starting",
                 "[box] still building the emulator container: 2 min so far"):
        assert core.box_build_line(line, st) is None
