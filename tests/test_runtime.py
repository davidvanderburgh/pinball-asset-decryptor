"""The PAD Runtime: the Linux the app installs so the user's own stops mattering.

Phase 1 (tests/test_payloads.py) stopped the app compiling on a user's machine.
This is the second half: a rootfs we build and pin, imported as a private WSL
distro, so the emulator no longer runs on whatever Ubuntu, Debian or Arch spin
happened to be that machine's default.

What these tests guard is mostly about NOT DOING DAMAGE and NOT LYING: the app
must never adopt a distro that is not ours, never claim a runtime is ready when
it is a version it does not know, never route a rig into a distro that cannot
run it, and never spend two process launches per status poll asking.
"""
import json
import pathlib
import re
import subprocess
from dataclasses import replace

import pytest

from pinball_decryptor.core import runtime

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "runtime.yml"
DOCKERFILE = REPO / "tools" / "runtime" / "Dockerfile"

MANIFEST = {"runtime_version": runtime.RUNTIME_VERSION, "variant": "base",
            "snapshot": "20260801T000000Z", "built": "2026-09-08T00:00:00Z"}


def _proc(stdout=b"", rc=0, stderr=b""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def _runner(listed=(), manifest_json=MANIFEST, calls=None, fail=None):
    """A fake wsl.exe.  Records what it was asked, so a test can assert on the
    ARGUMENTS as well as the answer - `--version 2` and the unregister-first
    rule are both invisible in a return value."""
    def run(args, timeout=None, stdin=None):
        if calls is not None:
            calls.append(args)
        if fail and fail in args:
            return _proc(rc=1, stderr=b"wsl: something went wrong")
        if args[:3] == ["wsl.exe", "-l", "-q"]:
            return _proc("\n".join(listed).encode("utf-8"))
        if "cat" in args:
            if manifest_json is None:
                return _proc(rc=1)
            return _proc(json.dumps(manifest_json).encode("utf-8"))
        return _proc()
    return run


@pytest.fixture(autouse=True)
def _windows_and_published(monkeypatch):
    """Every test below is about the Windows path with an image published;
    the ones that are not say so themselves."""
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime, "IMAGE",
                        replace(runtime.IMAGE, sha256="ab" * 32, size=123))
    runtime.invalidate()
    yield
    runtime.invalidate()


# ------------------------------------------------------------ what it sees --

def test_the_distro_list_is_read_whatever_encoding_wsl_answers_in():
    """wsl.exe speaks UTF-16LE unless told otherwise, which turns every name
    into "U\\0b\\0u\\0n\\0t\\0u\\0" and every comparison into False."""
    assert runtime.registered(runner=_runner(listed=["Ubuntu", runtime.DISTRO]))
    assert not runtime.registered(runner=_runner(listed=["Ubuntu"]))

    def utf16(args, timeout=None, stdin=None):
        return _proc(("Ubuntu\n%s\n" % runtime.DISTRO).encode("utf-16-le"))
    assert runtime.registered(runner=utf16)


def test_a_distro_of_our_name_that_is_not_ours_is_left_alone():
    """`foreign`, not `ready` and not `stale`.  Somebody else's distro that
    happens to carry this name must never be adopted, upgraded or - the real
    risk, since install() unregisters first - destroyed."""
    state, detail = runtime.status(
        runner=_runner(listed=[runtime.DISTRO], manifest_json=None))
    assert state == "foreign"
    assert "not ours" in detail


def test_an_older_runtime_reads_as_stale_rather_than_ready():
    old = dict(MANIFEST, runtime_version=runtime.RUNTIME_VERSION - 1)
    state, detail = runtime.status(
        runner=_runner(listed=[runtime.DISTRO], manifest_json=old))
    assert state == "stale"
    assert str(runtime.RUNTIME_VERSION) in detail


def test_a_matching_runtime_is_ready_and_says_what_it_is():
    state, detail = runtime.status(runner=_runner(listed=[runtime.DISTRO]))
    assert state == "ready"
    assert "base" in detail


def test_no_image_pinned_yet_is_its_own_answer(monkeypatch):
    """The mechanism ships before the image is cut, exactly as the payloads
    did - and while it has no hash the app must say so rather than try to
    download a file that does not exist."""
    monkeypatch.setattr(runtime, "IMAGE", replace(runtime.IMAGE, sha256="", size=0))
    runtime.invalidate()
    assert runtime.status(runner=_runner())[0] == "unpublished"
    with pytest.raises(RuntimeError, match="no pinned runtime image"):
        runtime.install(runner=_runner())


def test_off_windows_it_is_not_a_failure_it_is_not_applicable(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    runtime.invalidate()
    assert runtime.status()[0] == "unsupported"


# ------------------------------------------------------------- the routing --

def test_only_rigs_the_image_can_actually_run_are_routed_into_it():
    """The `base` image carries the Spike 1 emulator and none of Spike 2's
    toolchain, so routing Spike 2 into it would swap a working default distro
    for one with no qemu-user-static.  Per rig, not global."""
    r = _runner(listed=[runtime.DISTRO])
    assert runtime.distro_for("spike1", runner=r) == runtime.DISTRO
    assert runtime.distro_for("spike2", runner=r) is None


def test_a_rig_is_not_routed_into_a_runtime_that_is_not_ready():
    assert runtime.distro_for("spike1", runner=_runner(listed=["Ubuntu"])) is None
    assert runtime.distro_for(
        "spike1", runner=_runner(listed=[runtime.DISTRO],
                                 manifest_json=None)) is None


def test_the_escape_hatch_turns_it_off(monkeypatch):
    """PAD_RUNTIME=0 for a machine where the runtime is installed but
    suspect: the rig goes back to the default distro without uninstalling
    anything."""
    monkeypatch.setenv("PAD_RUNTIME", "0")
    assert runtime.distro_for(
        "spike1", runner=_runner(listed=[runtime.DISTRO])) is None


def test_the_health_answer_is_cached_because_it_is_asked_on_a_timer(monkeypatch):
    """Two wsl.exe launches per status poll is two console processes every
    couple of seconds.  The cache is what makes routing free; invalidate() is
    what keeps it honest after an install."""
    calls = []
    monkeypatch.setattr(runtime, "_run", _runner(listed=[runtime.DISTRO],
                                                 calls=calls))
    assert runtime.status()[0] == "ready"
    n = len(calls)
    assert n >= 2                      # the list, then the manifest
    for _ in range(5):
        runtime.status()
    assert len(calls) == n, "a cached answer must cost nothing"
    runtime.invalidate()
    runtime.status()
    assert len(calls) > n


# ------------------------------------------------------------- the install --

def test_installing_replaces_a_registered_runtime_rather_than_failing_on_it(
        monkeypatch, tmp_path):
    """`wsl --import` refuses a name that exists, and the states this heals -
    a half-imported runtime, one from an older app version - are exactly the
    ones where the user pressed a button that says Fix."""
    tar = tmp_path / "img.tar.gz"
    tar.write_bytes(b"x")
    monkeypatch.setattr(runtime, "ensure_cached", lambda *a, **k: str(tar))
    monkeypatch.setattr(runtime, "verify", lambda *a: (True, ""))
    monkeypatch.setenv("PAD_RUNTIME_DIR", str(tmp_path / "dest"))
    calls = []
    runtime.install(runner=_runner(listed=[runtime.DISTRO], calls=calls))
    flat = [" ".join(c) for c in calls]
    assert any("--unregister" in c for c in flat), flat
    imp = [c for c in flat if "--import" in c]
    assert imp, flat
    # WSL 1 has no loop devices and cannot run any of this; an imported distro
    # inherits the machine's default version unless told, so it is told.
    assert "--version 2" in imp[0], imp
    assert flat.index(imp[0]) > flat.index(
        [c for c in flat if "--unregister" in c][0]), "imported over a live one"


def test_a_supplied_file_is_held_to_the_same_hash(monkeypatch, tmp_path):
    """The offline path: a runtime image copied from another machine is
    checked exactly as a downloaded one is."""
    bad = tmp_path / "img.tar.gz"
    bad.write_bytes(b"not our image")
    monkeypatch.setenv("PAD_RUNTIME_DIR", str(tmp_path / "dest"))
    with pytest.raises(RuntimeError, match="not the runtime we built"):
        runtime.install(runner=_runner(), source=str(bad))


def test_a_failed_import_names_the_thing_the_app_cannot_do_for_you(
        monkeypatch, tmp_path):
    """WSL itself has to be installed first, and that needs an administrator
    and a reboot - so the message says the command instead of pretending the
    app could have handled it."""
    tar = tmp_path / "img.tar.gz"
    tar.write_bytes(b"x")
    monkeypatch.setattr(runtime, "ensure_cached", lambda *a, **k: str(tar))
    monkeypatch.setenv("PAD_RUNTIME_DIR", str(tmp_path / "dest"))
    with pytest.raises(RuntimeError) as exc:
        runtime.install(runner=_runner(fail="--import"))
    assert "wsl --install" in str(exc.value)


def test_an_import_that_does_not_answer_as_ours_is_a_failure(
        monkeypatch, tmp_path):
    """A tarball that unpacks but has no manifest is not a runtime, and
    reporting "ready" for it would send every later rig command into a distro
    that cannot run them."""
    tar = tmp_path / "img.tar.gz"
    tar.write_bytes(b"x")
    monkeypatch.setattr(runtime, "ensure_cached", lambda *a, **k: str(tar))
    monkeypatch.setenv("PAD_RUNTIME_DIR", str(tmp_path / "dest"))
    with pytest.raises(RuntimeError, match="does not answer as ours"):
        runtime.install(runner=_runner(listed=[], manifest_json=None))


# --------------------------------------------------- the image and the CI --

def test_the_pinned_image_is_the_one_the_workflow_publishes():
    """A hash in the app that nothing in CI produces is a runtime no user can
    install."""
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "pad-runtime-${{ inputs.variant }}.tar.gz" in wf
    assert runtime.IMAGE.filename == "pad-runtime-base.tar.gz"
    assert "--version 2" not in wf, "the workflow does not import; the app does"


def test_the_image_carries_what_the_rig_looks_for():
    """The rig finds its desktop user by NUMBER (`getent passwd 1000`) and its
    emulator at a fixed path.  An image without either would import cleanly and
    then fail minutes into a first run."""
    df = DOCKERFILE.read_text(encoding="utf-8")
    assert "useradd -m -u 1000" in df
    assert "/home/pad/qemubuild/qemu-arm" in df
    assert "/home/pad/s1emu/s1hwshim" in df
    assert "pad-runtime.json" in df


def test_the_base_image_is_pinned_by_digest_not_by_tag():
    """`ubuntu:24.04` is rebuilt every few weeks, so the same Dockerfile would
    otherwise mean a different Linux each time it was built."""
    df = DOCKERFILE.read_text(encoding="utf-8")
    m = re.search(r"^FROM\s+ubuntu:[\d.]+@(sha256:[0-9a-f]{64})\s*$", df, re.M)
    assert m, "the base image must be pinned by digest"


def test_the_packages_come_from_a_snapshot_of_the_archive():
    """The ordinary archive carries only the newest version of anything, so a
    rebuild silently picks up whatever security update has landed since.  A
    snapshot is the archive as it stood at one instant."""
    df = DOCKERFILE.read_text(encoding="utf-8")
    assert "snapshot.ubuntu.com" in df
    assert re.search(r"SNAPSHOT=\d{8}T\d{6}Z", df)


def test_the_workflow_verifies_the_binaries_it_bakes_in():
    """The image must not become a second, unverified copy of the emulator:
    it downloads the payloads the app already pins and checks them against the
    app's own hashes before they go in."""
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "payloads.verify" in wf
    assert "payloads.stamp_text" in wf, (
        "the rig's rebuild rule reads a stamp beside the binary; an image "
        "without one rebuilds the shim on every start")
