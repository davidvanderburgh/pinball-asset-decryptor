"""PAD-882: a first boot's Guided Setup is left by the rig itself.

Jaws LE booting a fresh NVRAM opens Guided Setup and waits for an operator; the
auto-advance helper read the attract light show running under it as "past Tech
Alerts" and stopped, so a Visual Pinball table (no service keys) sat on the menu
with Start and the flippers dead. guidedsetup.sh is the walk the rig's jobs used
(rigjob.sh's job_guided_setup), now shared with autoattract.sh. Here it runs
beside stand-ins for glshot.sh / menurow.py / swpoke.py: the menu readings are
scripted, the presses recorded.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")

# the rig is Linux's (WSL): guidedsetup.sh holds util-linux's flock, which macOS has not
needs_bash = pytest.mark.skipif(
    not (sys.platform.startswith("linux") and shutil.which("bash") and shutil.which("python3")
         and shutil.which("flock")),
    reason="needs Linux bash, python3 and flock")

LIST = """# id   num   node  bit  name
25     1009  0     8    Service Select
26     1010  0     9    Service Plus
27     1011  0     10   Service Minus
28     1012  0     11   Service Back
36     93    1     11   Start Button
"""

MENUROW = r'''import sys
p = __import__("os").path.join(__import__("os").path.dirname(__file__), "states.txt")
lines = open(p).read().splitlines()
print(lines[0] if lines else "none")
open(p, "w").write("\n".join(lines[1:] if len(lines) > 1 else lines))
'''

SWPOKE = r'''import os, sys
with open(os.path.join(os.path.dirname(__file__), "presses.txt"), "a") as f:
    f.write("%s %s\n" % (sys.argv[1], os.environ.get("PAD_SW_SRC", "")))
'''


def _rig(tmp_path, states, with_list=True):
    rig = tmp_path / "rig"
    root = tmp_path / "root"
    rig.mkdir(parents=True)
    (root / "dump" / "tables" / "jaws_le").mkdir(parents=True)
    shutil.copy(os.path.join(RIG, "guidedsetup.sh"), rig / "guidedsetup.sh")
    (rig / "padpath.sh").write_text('ROOT=%s\npad_gsleep() { :; }\n' % root)
    (rig / "glshot.sh").write_text(': > "$1"\n')
    (rig / "menurow.py").write_text(MENUROW)
    (rig / "swpoke.py").write_text(SWPOKE)
    (rig / "states.txt").write_text("\n".join(states) + "\n")
    if with_list:
        (root / "dump" / "tables" / "jaws_le" / "switch_list.txt").write_text(LIST)
    return rig


def _walk(rig, *args):
    env = dict(os.environ, PAD_GAME="jaws_le", PAD_SW_SRC="a")
    env.pop("LIST", None)
    r = subprocess.run(["bash", str(rig / "guidedsetup.sh")] + list(args), env=env,
                       capture_output=True, text=True, timeout=60)
    p = rig / "presses.txt"
    return r.returncode, (p.read_text().split("\n")[:-1] if p.exists() else [])


@needs_bash
def test_the_menu_is_walked_to_save_and_exit(tmp_path):
    rig = _rig(tmp_path, ["menu last=no", "menu last=no", "menu last=yes"])
    rc, presses = _walk(rig, "0")
    assert rc == 0
    assert presses == ["26 a", "26 a", "25 a"]          # PLUS, PLUS, SELECT on Save & Exit


@needs_bash
def test_a_pulsing_cursor_is_looked_at_again(tmp_path):
    # Jaws Pro's cursor dims to a teal menurow does not read: a 'none' between two reads
    rig = _rig(tmp_path, ["menu last=no", "none", "menu last=yes"])
    rc, presses = _walk(rig, "0")
    assert rc == 0 and presses == ["26 a", "25 a"]


@needs_bash
def test_not_the_menu_presses_nothing(tmp_path):
    rig = _rig(tmp_path, ["none"] * 40)
    rc, presses = _walk(rig, "0", "--confirm")
    assert rc == 1 and presses == []


@needs_bash
def test_confirm_wants_the_menu_read_twice(tmp_path):
    # one stray read (an attract frame that happens to look like it) is no menu: a PLUS
    # pressed into attract is a volume step
    rig = _rig(tmp_path, ["menu last=no"] + ["none"] * 40)
    rc, presses = _walk(rig, "0", "--confirm")
    assert rc == 1 and presses == []
    rig2 = _rig(tmp_path / "b", ["menu last=no", "none", "menu last=no", "menu last=yes"])
    rc, presses = _walk(rig2, "0", "--confirm")
    assert rc == 0 and presses == ["25 a"]


@needs_bash
def test_a_frame_that_does_not_come_is_asked_for_again(tmp_path):
    # glshot.sh has one request file per slot: a grab by anyone else at the same moment fails ours
    rig = _rig(tmp_path, ["menu last=yes", "menu last=yes", "menu last=yes"])
    (rig / "glshot.sh").write_text(
        'c="$(dirname "$0")/calls"; n=$(cat "$c" 2>/dev/null || echo 0); echo $((n + 1)) > "$c"\n'
        '[ "$n" = 0 ] && exit 1\n: > "$1"\n')
    rc, presses = _walk(rig, "0", "--confirm")
    assert rc == 0 and presses == ["25 a"]


@needs_bash
def test_no_switch_list_yet_is_no_menu(tmp_path):
    rig = _rig(tmp_path, ["menu last=yes"], with_list=False)
    rc, presses = _walk(rig, "0")
    assert rc == 1 and presses == []


@needs_bash
def test_backs_close_a_rows_editor_first(tmp_path):
    rig = _rig(tmp_path, ["none"] * 6 + ["menu last=yes"])
    rc, presses = _walk(rig, "1")
    assert rc == 0 and presses == ["28 a", "25 a"]


@needs_bash
def test_the_frame_judged_not_the_menu_is_kept_for_a_person(tmp_path):
    rig = _rig(tmp_path, ["none"] * 10)
    (rig / "glshot.sh").write_text('echo frame > "$1"\n')
    keep = tmp_path / "gamecheck.png"
    env = dict(os.environ, PAD_GAME="jaws_le", GS_KEEP=str(keep))
    r = subprocess.run(["bash", str(rig / "guidedsetup.sh"), "0"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and keep.read_text() == "frame\n"


@needs_bash
def test_a_second_walker_waits_for_the_first(tmp_path):
    # a rig job's walk and autoattract.sh's look must not press at once
    rig = _rig(tmp_path, ["menu last=yes"])
    root = tmp_path / "root" / "dump"
    holder = subprocess.Popen(["bash", "-c", 'exec 9< "$1"; flock 9; sleep 3', "_", str(root)])
    try:
        import time
        time.sleep(0.5)
        t0 = time.monotonic()
        rc, presses = _walk(rig, "0")
        assert time.monotonic() - t0 >= 2
        assert rc == 0 and presses == ["25 a"]
    finally:
        holder.wait()


def test_every_way_past_tech_alerts_then_looks_for_guided_setup():
    s = open(os.path.join(RIG, "autoattract.sh"), encoding="utf-8").read()
    past = [ln for ln in s.splitlines() if re.search(r'^\s*past && \{ echo "\[auto\]', ln)]
    assert len(past) == 3
    assert all("watch_setup" in ln for ln in past)
    # status.sh's auto_result=ok still matches every one of those lines
    assert all("past Tech Alerts" in ln or "already past" in ln for ln in past)
    assert 'guidedsetup.sh" 0 --confirm' in s
    # a human press still stands it down
    assert re.search(r"watch_setup\(\) \{.*?operator &&", s, re.S)


def test_rig_jobs_walk_the_same_menu():
    s = open(os.path.join(RIG, "rigjob.sh"), encoding="utf-8").read()
    body = s[s.index("job_guided_setup() {"):]
    body = body[:body.index("\n}\n")]
    assert 'guidedsetup.sh" "${1:-0}"' in body and "menurow.py" not in body


@needs_bash
@pytest.mark.parametrize("script", ["guidedsetup.sh", "autoattract.sh", "rigjob.sh", "modes/gamecheck.sh"])
def test_the_scripts_still_parse(script):
    r = subprocess.run(["bash", "-n", os.path.join(RIG, script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
