"""PAD-1534: the Multi-boot preview recompiled the whole menu program on
every preview.

The installed app's files carried times about five hours in the future: Inno
Setup's default restores the compiling machine's LOCAL wall clock, and the
release runner's local time is UTC (v1.579.1 was tagged 14:24 EST = 19:24
UTC; its files were installed stamped 19:25 EST).  make saw a Makefile newer
than every object, rebuilt all of them each time, and poured the gcc lines
and "Clock skew detected" into the user's project log.

Two fixes, both asked here: the installer keeps times in UTC, and the
preview's build (previewselect.sh) asks a digest of the sources instead of
file times, quietly.
"""
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
SCRIPT = os.path.join(RIG, "previewselect.sh")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_installer_restores_file_times_in_utc():
    iss = _read(os.path.join(ROOT, "installer", "pinball_decryptor.iss"))
    setup = iss[iss.index("[Setup]"):]
    setup = setup[:setup.index("\n[", 1)]
    assert re.search(r"(?m)^TimeStampsInUTC=yes\s*$", setup), \
        "without it a UTC build machine installs files hours in the future"


def test_the_tab_builds_its_preview_through_the_digest_gate():
    from pinball_decryptor.webui import multiboot_core as mc
    line = mc.ensure_selector_line("", "/r/tools/spike2_emu/codeselect")
    assert line.startswith("if bash tools/spike2_emu/previewselect.sh "
                           "/r/tools/spike2_emu/codeselect "
                           "~/emusrc/codeselect-preview ~/spike2root; then ")
    assert "make -C" not in line
    assert os.path.isfile(os.path.join(ROOT, mc.PREVIEWSELECT))


def test_the_script_digests_the_installed_selectors_own_list():
    """One list of sources (PAD_SELECT_SRCS) and one digest (pad_src_hash):
    the installed selector's gate and the preview's can never disagree on
    which files count."""
    code = "\n".join(ln for ln in _read(SCRIPT).splitlines()
                     if not ln.lstrip().startswith("#"))
    assert '. "$(dirname "$0")/padpath.sh"' in code
    assert "pad_src_hash \"$SRC_RIG\" $PAD_SELECT_SRCS" in code
    # a moved digest rebuilds EVERYTHING: file times are what is not trusted
    assert 'make -B -C "$SRC"' in code
    assert '>"$LOG" 2>&1' in code
    # the stamp goes before a build starts and comes back only after one
    # that worked
    assert code.index('rm -f "$STAMP"') < code.index("make -B")
    assert code.index("make -B") < code.index('> "$STAMP"')


_FAKE_MAKEFILE = """\
all:
\t@echo compiling >> $(BUILD)/runs
\t@if grep -q BROKEN codeselect.c; then echo 'codeselect.c:1:1: error: boom'; exit 1; fi
\t@for i in 1 2 3 4 5 6 7 8 9 10; do echo "gcc -O2 -c noise$$i.c"; done
\t@printf '#!/bin/sh\\n' > $(BUILD)/codeselect; chmod +x $(BUILD)/codeselect
"""


@pytest.mark.skipif(not sys.platform.startswith("linux")
                    or not shutil.which("bash") or not shutil.which("make"),
                    reason="runs the rig script under a Linux bash and make")
def test_a_second_preview_compiles_nothing_even_with_future_file_times(
        tmp_path):
    """The rig script itself, on a stand-in rig whose sources are dated five
    hours ahead, as the installed app's were."""
    rig = tmp_path / "tools" / "spike2_emu"
    src = rig / "codeselect"
    src.mkdir(parents=True)
    for name in ("previewselect.sh", "padpath.sh", "padslot.sh"):
        shutil.copy(os.path.join(RIG, name), str(rig / name))
    (src / "Makefile").write_text(_FAKE_MAKEFILE)
    (src / "codeselect.c").write_text("int main(void) { return 0; }\n")
    ahead = time.time() + 5 * 3600
    for f in src.iterdir():
        os.utime(str(f), (ahead, ahead))
    build = tmp_path / "build"
    sysroot = tmp_path / "root"
    env = dict(os.environ, HOME=str(tmp_path))
    env.pop("PAD_SLOT", None)

    def preview():
        p = subprocess.run(["bash", str(rig / "previewselect.sh"), str(src),
                            str(build), str(sysroot)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, env=env, cwd=str(tmp_path))
        runs = (build / "runs").read_text().count("compiling") \
            if (build / "runs").exists() else 0
        return p.returncode, p.stdout.strip().splitlines(), runs

    rc, out, runs = preview()
    assert (rc, runs) == (0, 1), out
    assert len(out) == 1 and out[0].startswith("[preview] menu program built"), out
    # ...the compiler's lines are in the file, not the log
    assert "gcc -O2" in (build / "make.log").read_text()
    rc, out, runs = preview()
    assert (rc, runs) == (0, 1), out
    assert out == ["[preview] menu program up to date: %s/codeselect" % build]

    # an edit rebuilds, once
    with open(str(src / "codeselect.c"), "a") as fh:
        fh.write("/* edit */\n")
    assert preview()[2] == 2
    assert preview()[2] == 2

    # a broken build fails, says its error and where the rest is, and is
    # never later taken as current
    with open(str(src / "codeselect.c"), "a") as fh:
        fh.write("BROKEN\n")
    rc, out, runs = preview()
    assert rc != 0 and runs == 3
    text = "\n".join(out)
    assert "error: boom" in text and "make.log" in text
    assert "gcc -O2" not in text
    assert not (build / "codeselect.srcs").exists()
    assert preview()[2] == 4
