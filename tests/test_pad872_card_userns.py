"""Stern Emulate in a container without SYS_ADMIN (PAD-872).

The card's FUSE mount went through the setuid fusermount3, which needs
CAP_SYS_ADMIN, so the Docker image's run line asked for that capability.  A
card run in a container without it now re-executes itself in a user
namespace of its own (padpath.sh pad_card_ns), where fuse2fs may mount the
card and every helper of the run shares the mount; the image ships the
seccomp profile that lets a container make one.  Proven in the image with
only --device /dev/fuse and that profile: Venom Pro boots, and both the
run's own teardown and an outside killgame.sh leave nothing running.
"""

import json
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
RIG = REPO / "tools" / "spike2_emu"
DOCKER = REPO / "installer" / "docker"
PROFILE = DOCKER / "root" / "usr" / "share" / "pad" / "pad-seccomp.json"


def _bash_runs_scripts():
    """Same guard as test_pkgnames.py: `bash` here may be git-bash or a WSL
    launcher with no distro."""
    try:
        r = subprocess.run(["bash", "-c", 'echo "${BASH_VERSINFO[0]}"'],
                           capture_output=True, timeout=30)
        return int(r.stdout.decode().strip()) >= 4
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


needs_bash = pytest.mark.skipif(not _bash_runs_scripts(),
                                reason="needs a bash 4 that runs scripts")


def _fn(src, name):
    body = src[src.index(name + "() {"):]
    return body[:body.index("\n}") + 2]


# --- when a run goes into its own namespace --------------------------------

# CapBnd as a desktop (or a container with --cap-add SYS_ADMIN) has it, and
# as Docker's default capability set has it: bit 21, CAP_SYS_ADMIN, clear.
FULL = "000001ffffffffff"
DOCKER_DEFAULT = "00000000a80425fb"


def _needed(capbnd, uid="1000", **env):
    fn = _fn((RIG / "padpath.sh").read_text(encoding="utf-8"),
             "pad_card_ns_needed")
    fn = fn.replace("/proc/self/status", '"$STATUS"')
    # On stdin, not -c: on Windows `bash` is WSL's launcher, which mangles a
    # -c script on the way in (and passes no environment).
    script = (
        "".join("%s='%s'\n" % kv for kv in env.items())
        + 'UID_IS=%s\n' % uid
        + 'STATUS=$(mktemp); printf "Name:\\tbash\\nCapBnd:\\t%s\\n" "$1" > "$STATUS"\n'
        'id() { echo "$UID_IS"; }\n'
        + fn +
        '\npad_card_ns_needed; rc=$?; rm -f "$STATUS"; echo "rc=$rc"\n')
    # bytes, so Windows does not turn the script's newlines into CRLF
    r = subprocess.run(["bash", "-s", "--", capbnd],
                       input=script.encode("utf-8"),
                       capture_output=True, timeout=60)
    return r.stdout.decode().strip().splitlines()[-1]


@needs_bash
def test_a_card_run_without_sys_admin_goes_into_its_own_namespace():
    assert _needed(DOCKER_DEFAULT, PAD_CARD="/data/x.raw") == "rc=0"


@needs_bash
def test_a_desktop_or_a_sys_admin_container_mounts_as_it_always_did():
    assert _needed(FULL, PAD_CARD="/data/x.raw") == "rc=1"


@needs_bash
def test_root_a_folder_run_and_the_reexecuted_run_stay_where_they_are():
    assert _needed(DOCKER_DEFAULT, uid="0", PAD_CARD="/data/x.raw") == "rc=1"
    assert _needed(DOCKER_DEFAULT) == "rc=1"                  # no card
    assert _needed(DOCKER_DEFAULT, PAD_CARD="/data/x.raw",
                   PAD_CARD_NS="1") == "rc=1"


def test_the_namespace_keeps_the_users_uid_and_its_capabilities():
    src = _fn((RIG / "padpath.sh").read_text(encoding="utf-8"), "pad_card_ns")
    # the user's own uid, so no `id -u = 0` branch of the rig flips; the
    # namespace's capabilities carried over the exec, so fuse2fs can mount
    for flag in ("--user", "--map-current-user", "--keep-caps", "--mount",
                 "--propagation slave"):
        assert flag in src, flag
    assert "export PAD_CARD_NS=1" in src


def test_every_card_entry_point_asks_first():
    for script in ("watch.sh", "run_game.sh"):
        src = (RIG / script).read_text(encoding="utf-8")
        head = src[src.index('padpath.sh"'):]
        # straight after padpath.sh, before anything of the run starts
        assert 'pad_card_ns "$0" "$@" || exit 1' in head.split("\n")[1:6], \
            script


def test_killgame_ends_a_mount_in_a_runs_own_namespace_with_term():
    src = (RIG / "killgame.sh").read_text(encoding="utf-8")
    body = src[src.index("A CARD MOUNTED IN A RUN'S OWN USER NAMESPACE"):]
    body = body[:body.index("\ndone\n")]
    assert 'kill -TERM "$_fp"' in body          # fuse2fs unmounts itself
    assert "kill -9" not in body                # never the wedging kill
    assert '"$_ns" != "$_myns"' in body          # only another namespace's


# --- the image -------------------------------------------------------------

def test_the_profile_is_dockers_default_plus_namespaces_and_mounts():
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert prof["defaultAction"] == "SCMP_ACT_ERRNO"
    ours = [s for s in prof["syscalls"] if "PAD-872" in s.get("comment", "")]
    assert len(ours) == 1
    extra = ours[0]
    assert extra["action"] == "SCMP_ACT_ALLOW"
    assert not extra.get("includes") and not extra.get("args")
    assert {"unshare", "mount", "umount2", "setns"} <= set(extra["names"])
    # nothing beyond namespaces and mounts: the rest of what Docker gates
    # on SYS_ADMIN stays shut
    for shut in ("bpf", "perf_event_open", "syslog", "quotactl",
                 "sethostname", "lookup_dcookie", "fanotify_init"):
        assert shut not in extra["names"], shut
    # and Docker's own rules are all still there, SYS_ADMIN-gated ones too
    gated = [s for s in prof["syscalls"]
             if "CAP_SYS_ADMIN" in s.get("includes", {}).get("caps", [])]
    assert any("bpf" in s["names"] for s in gated)


def test_the_guide_runs_it_without_sys_admin_and_copies_the_profile_out():
    guide = (REPO / "docs" / "guide" / "docker.md").read_text(encoding="utf-8")
    run = guide[guide.index("docker run -d"):]
    run = run[:run.index("```")]
    assert "--cap-add" not in run and "--privileged" not in run
    assert "--device /dev/fuse" in run
    assert "seccomp=/mnt/user/appdata/pinball-asset-decryptor/pad-seccomp.json" in run
    # the path it copies out is the file the image carries
    assert "/usr/share/pad/pad-seccomp.json" in guide
    df = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY docker/root/ /" in df
    assert "/usr/share/pad/pad-seccomp.json" in df
