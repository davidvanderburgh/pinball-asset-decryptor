"""The JJP dongle flow's C-toolchain guard (_ensure_compiler).

Alex Glaser's Sonic dongle extract died five phases in — after the ISO
extract, the mount, the chroot and the dongle handshake — on

    fatal error: stdio.h: No such file or directory

His WSL had gcc: Ubuntu's ``gcc`` package only *recommends* ``libc6-dev``,
so the driver was on PATH with none of its headers, and every ``which gcc``
style check said "fine".  The guard therefore compiles for real and installs
the toolchain itself, and the pipeline calls it before the extract.
"""

import pytest

from pinball_decryptor.plugins.jjp import pipeline as P
from pinball_decryptor.plugins.jjp.executor import CommandError


class _FakeExecutor:
    """Records commands; *fail* decides which ones raise CommandError."""

    def __init__(self, fail):
        self.fail = fail
        self.cmds = []

    def run(self, bash_cmd, timeout=120):
        self.cmds.append(bash_cmd)
        if self.fail(bash_cmd, self.cmds):
            raise CommandError(bash_cmd, 1, "boom")
        return ""


def _pipeline(fail):
    """A DecryptionPipeline with only the bits _ensure_compiler touches."""
    p = P.DecryptionPipeline.__new__(P.DecryptionPipeline)
    p.executor = _FakeExecutor(fail)
    p.logged = []
    p.log = lambda text, level="info": p.logged.append((text, level))
    return p


def _is_probe(cmd):
    return "jjp_ccprobe.c" in cmd


def _is_install(cmd):
    return "apt-get install" in cmd or "apk add" in cmd


def test_working_toolchain_installs_nothing():
    p = _pipeline(lambda cmd, cmds: False)
    p._ensure_compiler()

    assert all(not _is_install(c) for c in p.executor.cmds)
    assert p._compiler_ready is True
    assert p.logged == []


def test_probe_compiles_a_real_file_not_a_which_lookup():
    # The whole point: gcc on PATH is not the test — headers are.
    p = _pipeline(lambda cmd, cmds: False)
    p._ensure_compiler()

    probe = p.executor.cmds[0]
    assert "gcc" in probe and "which" not in probe
    assert "base64 -d" in probe  # the probe source is written out, then built


def test_missing_headers_are_installed_then_rechecked():
    state = {"headers": False}

    def fail(cmd, cmds):
        if _is_install(cmd):
            state["headers"] = True   # apt-get install gcc libc6-dev
            return False
        return _is_probe(cmd) and not state["headers"]

    p = _pipeline(fail)
    p._ensure_compiler()

    installs = [c for c in p.executor.cmds if _is_install(c)]
    assert installs and "libc6-dev" in installs[0]
    # Probed again after installing — an install that didn't help must not
    # be reported as a fixed toolchain.
    assert sum(1 for c in p.executor.cmds if _is_probe(c)) >= 2
    assert p._compiler_ready is True


def test_unfixable_toolchain_raises_naming_the_headers_package():
    p = _pipeline(lambda cmd, cmds: _is_probe(cmd))

    with pytest.raises(P.PipelineError) as ei:
        p._ensure_compiler()

    msg = str(ei.value)
    assert "libc6-dev" in msg
    assert "gcc" in msg


def test_result_is_cached_across_phases():
    p = _pipeline(lambda cmd, cmds: False)
    p._ensure_compiler()
    n = len(p.executor.cmds)
    p._ensure_compiler()          # Compile phase after the pre-extract check
    assert len(p.executor.cmds) == n


def test_run_checks_the_compiler_before_extracting():
    """Fail-fast ordering: no 32 GB extract before a one-line apt install."""
    p = P.DecryptionPipeline.__new__(P.DecryptionPipeline)
    p.executor = _FakeExecutor(lambda cmd, cmds: _is_probe(cmd))
    p.image_path = "game.iso"
    p.output_path = "out"
    p.executor.check_path_accessible = lambda path: (True, "")
    p.log = lambda text, level="info": None
    p.on_phase = lambda idx: None
    p.on_done = lambda ok, msg: None
    p._phase_cleanup = lambda: None
    p._phase_extract = lambda: pytest.fail("extract ran before the toolchain check")
    p.cancelled = False

    p.run()  # swallows the PipelineError into on_done

    assert any(_is_probe(c) for c in p.executor.cmds)
