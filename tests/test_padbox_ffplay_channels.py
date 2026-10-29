"""PAD-832: the Mac box's speaker says the channel count the way its ffplay takes it.

A Mac user's Emulate run was silent: the log said
"Failed to set value '2' for option 'ac': Option not found".  FFmpeg 7 took
``-ac`` away from ffplay (only ``-ch_layout`` is left) and Homebrew ships 7 and
newer, so padbox.sh's ``ffplay ... -ac 2`` exited at once.

padbox.sh's ``ffplay_channel_args`` is run here with ``ffplay`` replaced by a
shell function that prints the raw demuxer's help as each FFmpeg does, fed on
stdin for the reason test_padbox_build_watch.py gives (the ``bash`` on PATH may
be WSL's, which cannot open a Windows path).
"""
import os
import re
import subprocess

import pytest

from tests.conftest import HAS_BASH

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BOX = os.path.join(RIG, "docker", "padbox.sh")

needs_bash = pytest.mark.skipif(not (os.path.isfile(BOX) and HAS_BASH),
                                reason="rig or working bash not present")

# `ffplay -h demuxer=s16le` as each generation prints it (trimmed)
_HELP = {
    "8.1": ("  -sample_rate       <int>        .D.........  (default 44100)\n"
            "  -ch_layout         <channel_layout> .D.........  (default \"mono\")\n"),
    "6.1": ("  -sample_rate       <int>        .D.........  (default 44100)\n"
            "  -channels          <int>        .D........P  (default 1)\n"
            "  -ch_layout         <channel_layout> .D......... \n"),
    "4.4": ("  -sample_rate       <int>        .D.........  (default 44100)\n"
            "  -channels          <int>        .D.........  (default 1)\n"),
}


def _function(name):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % name, body, re.S | re.M)
    assert m, "%s() not found in padbox.sh" % name
    return m.group(0)


def _channel_args(version, ch):
    script = "\n".join([
        "set -u",
        "ffplay() { printf '%%s' %s; }" % _shell_quote(_HELP[version]),
        _function("ffplay_channel_args"),
        "ffplay_channel_args %d" % ch,
        "",
    ])
    out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=30)
    assert out.returncode == 0, out.stdout
    return out.stdout.decode("utf-8", "replace").strip()


def _shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


@needs_bash
@pytest.mark.parametrize("version", ["8.1", "6.1"])
def test_an_ffplay_with_ch_layout_is_given_a_layout(version):
    assert _channel_args(version, 2) == "-ch_layout stereo"
    assert _channel_args(version, 1) == "-ch_layout mono"
    assert _channel_args(version, 6) == "-ch_layout 6c"


@needs_bash
def test_an_ffplay_older_than_5_1_still_gets_ac():
    assert _channel_args("4.4", 2) == "-ac 2"


def test_the_player_never_passes_ac_itself():
    # the one ffplay command line takes its channel words from the probe
    player = _function("host_player")
    cmd = player[player.index("exec ffplay"):]
    cmd = cmd[:cmd.index("tcp://")]
    assert "-ac" not in cmd
    assert "$chargs" in cmd
