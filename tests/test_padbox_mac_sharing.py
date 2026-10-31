"""PAD-884: on a Mac, everything the box mounts has to be somewhere the
container engine shares - and the one folder every engine shares is home.

colima (what "Set up emulator..." installs) shares ~ and nothing else, and a
bind mount of a path its VM cannot see comes up EMPTY rather than failing. The
old test was Docker Desktop's sharing list (/Volumes, /private, /tmp...), so an
app run from its disk image or from a translocated copy was mounted uncopied
and the box said "no rig at /pad/rig". The override set lives in the Mac's temp
dir (/var/folders/...) and had the same hole, silently: a run without your edits.

...BUT THAT WAS NOT DUSTIN'S CASE. His app was in /Applications, already copied
into home, and colima still said "no rig at /pad/rig": entrypoint.sh tested
watch.sh with -x, the rig ships its scripts 644, and only Docker Desktop's
sharing (and WSL's /mnt/c) invents the execute bit. colima's virtiofs shows the
real mode. The last tests here run the real entrypoint against a 644 rig.

padbox.sh is fed on stdin as in test_padbox_savestates.py, with `uname` faked
to say Darwin and `docker` / `rsync` stand-ins that print what they were asked.
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

# $W/home is HOME; $W/apps is "elsewhere" - a disk image, a translocated app.
_FAKE = r"""
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/bin" "$W/home" "$W/apps/rig/docker" "$W/home/dev/rig/docker" \
         "$W/apps/T/spike2_overrides/sub"
echo game > "$W/apps/T/spike2_overrides/sub/game"
for r in "$W/apps/rig" "$W/home/dev/rig"; do echo x > "$r/watch.sh"; done
cat > "$W/bin/docker" <<'EOF'
#!/bin/bash
echo "DOCKER $*"
case "$1" in image) exit 0 ;; esac
exit 0
EOF
cat > "$W/bin/uname" <<'EOF'
#!/bin/bash
echo Darwin
EOF
cat > "$W/bin/rsync" <<'EOF'
#!/bin/bash
echo "RSYNC $*"
for a; do :; done; dst=$a
src=${@: -2:1}
cp -R "$src". "$dst"
EOF
chmod +x "$W/bin/"*
export PATH="$W/bin:$PATH" HOME="$W/home"
"""


def _box(where, **env):
    with open(BOX, "rb") as fh:
        body = fh.read().decode("utf-8")
    # $0 is the shell itself under `bash -s`, so SELF is pinned to the fake rig
    # we stand in: left to $0 it named /, and the rig copy copied the disk.
    pin = 'SELF=$(cd "$(dirname "$0")" && pwd)'
    assert pin in body
    body = body.replace(pin, "SELF=$(pwd)", 1)
    exports = " ".join("%s=%s" % kv for kv in env.items())
    prelude = "\n".join([
        _FAKE,
        # SELF is $(dirname "$0") = "." under `bash -s`: the rig is where we are
        'cd "$W/%s/rig/docker"' % where,
        "set -- watch.sh 30",
        "export PAD_BOX_IMAGE=pad884-test:1 PAD_AUDIO=0 %s" % exports,
        "",
    ])
    epilogue = '\necho "W=$W"\n'
    out = subprocess.run(["bash", "-s"],
                         input=(prelude + body + epilogue).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    text = out.stdout.decode("utf-8", "replace")
    run = [ln for ln in text.splitlines() if ln.startswith("DOCKER run ")]
    assert len(run) == 1, text
    return out.returncode, run[0], text


@needs_bash
def test_a_rig_outside_home_is_copied_into_home_and_that_is_mounted():
    rc, run, text = _box("apps")
    assert rc == 0, text
    assert "outside Docker's file sharing; using a copy" in text, text
    stage = "/home/Library/Application Support/pinball_decryptor/spike2_emu"
    assert stage + ":/pad/rig:ro" in run, run
    assert "/apps/rig:/pad/rig" not in run, run


@needs_bash
def test_a_rig_under_home_is_mounted_where_it_is():
    rc, run, text = _box("home/dev")
    assert rc == 0, text
    assert "using a copy" not in text, text
    assert "/home/dev/rig:/pad/rig:ro" in run, run


@needs_bash
def test_an_override_set_in_the_mac_temp_dir_is_mirrored_into_home():
    rc, run, text = _box("home/dev",
                         PAD_OVERRIDE_DIR='"$W/apps/T/spike2_overrides"')
    assert rc == 0, text
    stage = "/home/Library/Caches/pinball_decryptor/spike2_overrides"
    rs = [ln for ln in text.splitlines() if ln.startswith("RSYNC ")]
    assert len(rs) == 1 and "--delete" in rs[0], text
    assert stage + ":/pad/overrides:ro" in run, run
    assert "PAD_OVERRIDE_DIR=/pad/overrides" in run, run


@needs_bash
def test_an_override_set_under_home_is_mounted_where_it_is():
    rc, run, text = _box("home/dev",
                         PAD_OVERRIDE_DIR='"$W/home/dev/rig"')
    assert rc == 0, text
    assert "RSYNC" not in text, text
    assert "/home/dev/rig:/pad/overrides:ro" in run, run


ENTRY = os.path.join(RIG, "docker", "entrypoint.sh")

_ENTRY_RIG = r"""
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/rig" "$W/empty"
echo 'echo WATCH' > "$W/rig/watch.sh"
echo 'echo ALIVE "$@"' > "$W/rig/alive.sh"
chmod 644 "$W/rig/"*.sh
"""


def _entry(rig_dir):
    with open(ENTRY, "rb") as fh:
        body = fh.read().decode("utf-8")
    prelude = "\n".join([_ENTRY_RIG,
                         'export PAD_RIG="$W/%s"' % rig_dir,
                         "set -- alive.sh now", ""])
    out = subprocess.run(["bash", "-s"], input=(prelude + body).encode("utf-8"),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60)
    return out.returncode, out.stdout.decode("utf-8", "replace")


@needs_bash
def test_the_box_runs_a_rig_whose_scripts_have_no_execute_bit():
    rc, text = _entry("rig")
    assert "no rig" not in text, text
    assert "ALIVE now" in text, text
    assert rc == 0, text


@needs_bash
def test_an_empty_rig_mount_says_the_engine_did_not_share_it():
    rc, text = _entry("empty")
    assert rc == 1, text
    assert "did not share the folder" in text, text
