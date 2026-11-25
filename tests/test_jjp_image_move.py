"""PAD-1592: a JJP extract moves its raw card image to the output folder
only once cleanup has unmounted it.

The copy phase used to rsync --remove-source-files the image while it was
still loop-mounted read-write under the chroot: it changed under rsync, which
copied all 34 GB and then refused to delete the source ("Skipping sender
remove for changed file"), and the failure logged rsync's whole progress
stream as the warning.
"""
import pytest

from pinball_decryptor.plugins.jjp import pipeline as P

IMG = "/var/tmp/jjp_raw_GunsNRoses-v03.03.img"
MP = "/mnt/jjp_abcd1234"
OUT = "/mnt/c/out"

PROGRESS = [
    " 27,705,573,376  80%  141.66MB/s    0:00:45  ",
    " 34,359,738,368 100%  137.69MB/s    0:03:57 (xfr#1, to-chk=0/1)",
]


class _Exec:
    """Records every command; the image counts as mounted until umount."""

    def __init__(self, rsync_error=None, sizes=("34359738368", "34359738368")):
        self.cmds = []
        self.mounted = True
        self.rsync_error = rsync_error
        self.sizes = sizes
        self.rsync_while_mounted = False

    def run(self, cmd, timeout=None):
        self.cmds.append(cmd)
        if cmd.startswith(f"umount '{MP}'"):
            self.mounted = False
        if cmd.startswith("losetup -j"):
            return "/dev/loop3: [2049]:12 (x)\n" if self.mounted else ""
        if cmd.startswith("stat -c%s"):
            return "\n".join(self.sizes) + "\n"
        return ""

    def stream(self, cmd, timeout=None):
        self.cmds.append(cmd)
        if cmd.startswith("rsync"):
            self.rsync_while_mounted = self.mounted
        yield from PROGRESS
        if self.rsync_error:
            raise P.CommandError(cmd, 23, self.rsync_error)

    def to_exec_path(self, p):
        return OUT if p == "C:\\out" else p


def _pipe(ex):
    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = ex
    pipe.logs = []
    pipe.log = lambda msg, level="info": pipe.logs.append((level, msg))
    pipe.on_progress = lambda *a, **k: None
    pipe.cancelled = False
    pipe.mount_point = MP
    pipe._bind_mounted = []
    pipe._iso_mount = None
    pipe._raw_img_path = IMG
    pipe._image_to_output = (f"{OUT}/jjp_raw_GunsNRoses-v03.03.img",
                             "C:\\out\\jjp_raw_GunsNRoses-v03.03.img")
    pipe._detach_dongle = lambda: None
    pipe._discard_iso_scratch = lambda: None
    return pipe


def _index(cmds, prefix):
    return next(i for i, c in enumerate(cmds) if c.startswith(prefix))


def test_image_moves_after_unmount_and_source_goes():
    ex = _Exec()
    pipe = _pipe(ex)
    pipe._phase_cleanup()

    assert not ex.rsync_while_mounted, "image copied while still mounted"
    rsync = ex.cmds[_index(ex.cmds, "rsync")]
    assert "--remove-source-files" not in rsync
    assert _index(ex.cmds, f"umount '{MP}'") < _index(ex.cmds, "rsync")
    # the source goes only after the size check
    assert _index(ex.cmds, "stat -c%s") < ex.cmds.index(f"rm -f '{IMG}'")
    assert any("Game image saved to: C:\\out\\" in m for _, m in pipe.logs)
    assert pipe._image_to_output is None


def test_real_unmount_first_lazy_only_as_fallback():
    ex = _Exec()
    _pipe(ex)._phase_cleanup()
    um = ex.cmds[_index(ex.cmds, f"umount '{MP}'")]
    assert um.startswith(f"umount '{MP}' 2>/dev/null || umount -l '{MP}'")


def test_failed_move_logs_the_error_not_rsync_progress():
    ex = _Exec(rsync_error="\n".join(PROGRESS + [
        "ERROR: Skipping sender remove for changed file: x.img",
        PROGRESS[-1] + "rsync error: some files/attrs were not transferred "
        "(see previous errors) (code 23) at main.c(1356) [sender=3.2.7]"]))
    pipe = _pipe(ex)
    pipe._phase_cleanup()

    warn = [m for _, m in pipe.logs if "Could not move image" in m]
    assert len(warn) == 1
    assert "Skipping sender remove" in warn[0]
    # glued onto the last progress line by rsync, still found
    assert "(code 23)" in warn[0]
    assert "MB/s" not in warn[0] and "\n" not in warn[0]
    assert not any("Game image saved" in m for _, m in pipe.logs)
    # the temp-dir sweep still deletes the 34 GB source
    assert f"rm -f '{IMG}' 2>/dev/null; true" in ex.cmds
    assert pipe.logs[-1] == ("success", "Cleanup complete.")


def test_short_copy_keeps_source_until_sweep_and_warns():
    ex = _Exec(sizes=("34359738368", "1048576"))
    pipe = _pipe(ex)
    assert pipe._move_image(IMG, f"{OUT}/x.img") is False
    assert f"rm -f '{IMG}'" not in ex.cmds
    assert any("1048576 bytes" in m for _, m in pipe.logs)


def test_cancel_during_move_does_not_abort_cleanup():
    ex = _Exec()
    pipe = _pipe(ex)
    pipe.cancelled = True
    pipe._phase_cleanup()
    assert any("Image move canceled" in m for _, m in pipe.logs)
    assert f"rm -f '{IMG}' 2>/dev/null; true" in ex.cmds
    assert pipe.logs[-1] == ("success", "Cleanup complete.")


def test_failed_run_never_moves_the_image():
    ex = _Exec()
    pipe = _pipe(ex)
    pipe._image_to_output = None       # the copy phase never finished
    pipe._phase_cleanup()
    assert not any(c.startswith("rsync") for c in ex.cmds)
    assert f"rm -f '{IMG}' 2>/dev/null; true" in ex.cmds


def test_copy_phase_only_records_the_move(tmp_path):
    ex = _Exec()
    pipe = _pipe(ex)
    pipe._image_to_output = None
    pipe.output_path = "C:\\out"
    pipe._generate_checksums = lambda _out: None
    pipe._phase_copy()
    assert not any(IMG in c for c in ex.cmds), \
        "the copy phase must not touch the still-mounted image"
    dest, win = pipe._image_to_output
    assert dest == f"{OUT}/jjp_raw_GunsNRoses-v03.03.img"
    assert win.endswith("jjp_raw_GunsNRoses-v03.03.img")


@pytest.mark.parametrize("line,progress", [
    (PROGRESS[0], True), (PROGRESS[1], True),
    ("ERROR: Skipping sender remove for changed file: x.img", False),
    ("rsync error: some files/attrs were not transferred (code 23)", False),
])
def test_progress_line_filter(line, progress):
    assert bool(P.DecryptionPipeline._RSYNC_PROGRESS.match(line)) is progress
