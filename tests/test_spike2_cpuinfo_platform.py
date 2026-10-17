"""PAD-603: a game that asks /proc/cpuinfo what board it is on gets the Spike 2's answer.

deadpool_le 0.99's node bus library picks its platform by popen-ing
`/bin/cat /proc/cpuinfo | /bin/grep Hardware` and looking for
"Freescale i.MX6". Under qemu-user the file is the host's, the platform read
0, NODEBUS_Init took the Spike 1 (/dev/gpio) branch and failed, and the game
stayed at "bringing up node boards". hwshim's popen now answers a
`cat /proc/cpuinfo` with the board's own Hardware line and runs the rest of
the pipeline as written.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")


def _shim():
    with open(os.path.join(RIG, "hwshim.c"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _cpuinfo_block(src):
    start = src.index("#define SPIKE2_CPUINFO_HW")
    end = src.index("void *shim_popen(", start)
    return src[start:end]


def test_the_answer_names_the_board_the_old_code_looks_for():
    hw = re.search(r'#define SPIKE2_CPUINFO_HW "([^"]*)"', _shim()).group(1)
    assert hw.startswith("Hardware\\t: ")
    # PLATFORMUTIL_getPlatform's strstr for platform 2 (Spike 2)
    assert "Freescale i.MX6" in hw


def test_popen_runs_the_rewritten_command():
    src = _shim()
    body = src[src.index("void *shim_popen(const char *cmd, const char *mode)\n{"):]
    body = body[:body.index("\n}\n")]
    assert "cpuinfo_cmd(cmd" in body
    assert "real_popen(run, mode)" in body, "popen still runs the original command"


_HARNESS = r"""
#include <stdio.h>
#include <string.h>
%s
int main(int argc, char **argv)
{
    char out[512];
    puts(cpuinfo_cmd(argv[1], out, sizeof out));
    return 0;
}
"""


@pytest.mark.skipif(not shutil.which("gcc") or sys.platform == "win32",
                    reason="needs gcc and a POSIX shell")
@pytest.mark.parametrize("cmd,expect", [
    ("/bin/cat /proc/cpuinfo | /bin/grep Hardware",
     "echo 'Hardware\t: Freescale i.MX6 Quad/DualLite (Device Tree)' | /bin/grep Hardware"),
    ("cat /proc/cpuinfo",
     "echo 'Hardware\t: Freescale i.MX6 Quad/DualLite (Device Tree)'"),
    ("/bin/mount -oremount,async /data", "/bin/mount -oremount,async /data"),
])
def test_cpuinfo_cmd_rewrites_only_the_cat(tmp_path, cmd, expect):
    src = tmp_path / "h.c"
    src.write_text(_HARNESS % _cpuinfo_block(_shim()))
    exe = tmp_path / "h"
    subprocess.run(["gcc", "-o", str(exe), str(src)], check=True)
    got = subprocess.run([str(exe), cmd], capture_output=True, text=True,
                         check=True).stdout.rstrip("\n")
    assert got == expect
    # and the rewritten pipeline really gives the old code its platform
    if "cpuinfo" in cmd:
        out = subprocess.run(["sh", "-c", got], capture_output=True,
                             text=True).stdout
        assert "Freescale i.MX6" in out
