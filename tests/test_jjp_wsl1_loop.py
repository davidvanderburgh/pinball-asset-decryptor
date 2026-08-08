"""PAD-45 — a WSL 1 distro must stop a JJP run before it costs anything.

Field report (Sonic .iso, Windows 10, ``wsl -l -v`` VERSION 1): the app
reported every prerequisite OK, spent five minutes restoring 7.5 GB of
partclone parts, failed to mount the result with a bare "mount failed: No
such file or directory", concluded the image was corrupt, re-extracted the
whole thing and failed identically.  Twenty minutes and two 7.5 GB scratch
copies — one of which the reporter had to delete by hand mid-run to keep
the disk from filling — to reach a verdict that was knowable before the
first byte was read: WSL 1 has no loop devices, and every JJP flow
loop-mounts the ext4 image it pulls out of the .iso.

Three guards here: the gate says no up front, a mount failure that IS this
never pays for a second extraction, and the scratch directory gets deleted
whichever way the .iso was read.
"""

import pytest

from pinball_decryptor.core.ext4_grow import LOOP_PROBE
from pinball_decryptor.plugins.jjp import pipeline as P
from pinball_decryptor.plugins.jjp.executor import WslExecutor


class _FakeWsl(WslExecutor):
    """A WSL distro that answers as root; ``loop_ok`` decides whether it
    owns a loop device.  Subclasses the real class because
    ``check_prerequisites`` branches on ``isinstance``."""

    def __init__(self, loop_ok):
        self.loop_ok = loop_ok
        self.commands = []

    def run(self, cmd, timeout=None):
        self.commands.append(cmd)
        if "losetup" in cmd and not self.loop_ok:
            raise P.CommandError(cmd, 1,
                "losetup: cannot find an unused loop device: "
                "No such file or directory")
        return "ok\n"


def _wsl2_result(executor):
    results = P.check_prerequisites(executor, standalone=True)
    return next((r for r in results if r[0] == "WSL2"), None)


def test_prereq_gate_rejects_a_loopless_distro(monkeypatch):
    """"Answers echo as root" is not the capability the pipeline needs.

    This is the gate the reporter's run walked straight through — every
    JJP flow loop-mounts, so the probe has to be a loop probe."""
    monkeypatch.setattr(P.sys, "platform", "win32")
    ex = _FakeWsl(loop_ok=False)

    name, passed, msg = _wsl2_result(ex)
    assert not passed, (
        "a distro with zero loop devices passed the WSL2 prerequisite — "
        "the run goes on to spend ten minutes reaching a mount error")
    assert any("losetup" in c for c in ex.commands), (
        "the gate never asked for a loop device; it is still probing "
        "reachability only")
    # The message has to name the actual fix, not just the symptom.
    assert "wsl --set-version" in msg and "wsl -l -v" in msg


def test_prereq_gate_passes_a_normal_wsl2_distro(monkeypatch):
    monkeypatch.setattr(P.sys, "platform", "win32")
    name, passed, msg = _wsl2_result(_FakeWsl(loop_ok=True))
    assert passed, msg


def test_mount_without_loop_devices_skips_the_reextract(monkeypatch):
    """The delete-and-re-extract retry assumes a corrupt image.  When the
    Linux owns no loop devices the image is fine and nothing here can ever
    be mounted, so the retry is a second five-minute restore that ends at
    the same error (it did, in the report).  Fail with the fix instead."""
    monkeypatch.setattr(P.sys, "platform", "win32")

    class _LooplessExecutor:
        def __init__(self):
            self.commands = []

        def run(self, cmd, timeout=None):
            self.commands.append(cmd)
            if cmd.startswith("mount -o loop"):
                raise P.CommandError(cmd, 32,
                    "mount: /mnt/jjp_6bcbc092: mount failed: "
                    "No such file or directory.")
            if "losetup -f" in cmd:
                raise P.CommandError(cmd, 1,
                    "losetup: cannot find an unused loop device: "
                    "No such file or directory")
            return ""

    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = _LooplessExecutor()
    pipe.log = lambda *a, **k: None
    pipe.on_phase = lambda *a, **k: None
    pipe._raw_img_path = "/var/tmp/jjp_raw_Sonic-v00.929.img"
    pipe._is_iso = lambda: True
    reextracted = []
    pipe._phase_extract = lambda: reextracted.append(True)

    with pytest.raises(P.PipelineError) as exc:
        pipe._phase_mount()

    assert not reextracted, (
        "a loop-less host must not trigger the delete-and-re-extract "
        "retry — the image is fine and the second attempt cannot mount "
        "either (PAD-45: two full extractions, same error)")
    assert "wsl --set-version" in str(exc.value), (
        "the user is left with the raw 'No such file or directory' that "
        "started this ticket")


def test_extract_discards_the_previous_iso_scratch():
    """A retry re-enters the extract phase with a fresh random tag, so the
    previous xorriso extraction is orphaned under /var/tmp — and cleanup
    only ever knew the newest path.  On a Sonic .iso that is 7.5 GB the
    run can no longer account for."""
    stale = "/var/tmp/jjp_iso_deadbeef"

    class _Recorder:
        def __init__(self):
            self.commands = []

        def run(self, cmd, timeout=None):
            self.commands.append(cmd)
            return ""

        def to_exec_path(self, p):
            return "/mnt/d/Sonic-v00.929.iso"

    pipe = object.__new__(P.StandaloneDecryptPipeline)
    pipe.executor = _Recorder()
    pipe.log = lambda *a, **k: None
    pipe.image_path = r"D:\Sonic-v00.929.iso"
    pipe._iso_mount = stale
    pipe._iso_mounted = False   # xorriso extraction, not a loop mount
    pipe._raw_img_path = None

    # No partclone parts in the (fake) ISO, so the phase stops right after
    # the setup we care about.
    with pytest.raises(P.PipelineError):
        pipe._phase_extract()

    removed = [c for c in pipe.executor.commands
               if c.startswith(f"rm -rf '{stale}'")]
    assert removed, (
        "the previous ISO extraction was never deleted — a second copy "
        "lands beside it and both survive to the end of the run")
    # ...and it went before the replacement was created, or the disk holds
    # both at once, which is the state the reporter had to fix by hand.
    first_mkdir = next(i for i, c in enumerate(pipe.executor.commands)
                       if c.startswith("mkdir -p /var/tmp/jjp_iso_"))
    assert pipe.executor.commands.index(removed[0]) < first_mkdir


def test_standalone_cleanup_deletes_an_xorriso_extraction():
    """Cleanup used ``rmdir``, which only ever emptied a loop MOUNT.  The
    reporter's machine could not loop-mount at all, so its .iso was read
    with xorriso — into that same directory, which rmdir then refused to
    remove.  "Cleanup complete" left 7.5 GB behind, every run."""
    scratch = "/var/tmp/jjp_iso_c0ffee42"

    class _Recorder:
        def __init__(self):
            self.commands = []

        def run(self, cmd, timeout=None):
            self.commands.append(cmd)
            return ""

    pipe = object.__new__(P.StandaloneDecryptPipeline)
    pipe.executor = _Recorder()
    pipe.log = lambda *a, **k: None
    pipe.mount_point = None
    pipe._iso_mount = scratch
    pipe._iso_mounted = False
    pipe._raw_img_path = None
    pipe._succeeded = True
    pipe._phase_cleanup_standalone()

    assert any(c.startswith(f"rm -rf '{scratch}'")
               for c in pipe.executor.commands), (
        "the xorriso extraction is still being removed with rmdir, which "
        "cannot delete a directory holding the partition parts")
    assert pipe._iso_mount is None


def test_manufacturer_strip_probes_for_loop_devices():
    """The GUI indicator must not disagree with the pipeline's own gate —
    an all-green strip on a WSL 1 box is what sent the reporter into a
    twenty-minute extract."""
    from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer

    prereqs = {p.name: p for p in JJPManufacturer().prerequisites}
    assert "WSL2" in prereqs, (
        "JJP declares five tool probes and nothing that checks WSL can "
        "mount anything")
    assert prereqs["WSL2"].probe == LOOP_PROBE
    assert "set-version" in prereqs["WSL2"].install_hint
