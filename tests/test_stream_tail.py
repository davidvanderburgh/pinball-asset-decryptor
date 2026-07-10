"""Regression tests: executor.stream() must carry the failing command's
last output lines in CommandError.output.

Before this fix every stream() implementation raised
``CommandError(bash_cmd, rc, "")`` on a non-zero exit — the streamed
lines were gone once yielded, so callers (e.g. the JJP Build ISO phase)
showed bare "xorriso failed:" dialogs with no clue what went wrong
(tonyscoots' macOS report, 2026-07-10).

Drives the REAL stream() generators of all four executor modules by
subclassing their NativeExecutor with a ``python -c`` command prefix,
so the tests run anywhere (no WSL / sudo / Docker needed) — including
Windows, where the same loop body backs WslExecutor.stream().
"""

import sys

import pytest

from pinball_decryptor.core import executor as core_exec
from pinball_decryptor.plugins.bof import executor as bof_exec
from pinball_decryptor.plugins.jjp import executor as jjp_exec
from pinball_decryptor.plugins.spooky import executor as spooky_exec

MODULES = [core_exec, jjp_exec, spooky_exec, bof_exec]
MODULE_IDS = ["core", "jjp", "spooky", "bof"]

# Emits stdout + stderr chatter, then fails: the tail must capture both
# streams (stream() merges stderr into stdout) and the exit code.
FAIL_SCRIPT = (
    "import sys\n"
    "print('progress 10%')\n"
    "sys.stderr.write('xorriso : FAILURE : No space left on device\\n')\n"
    "sys.exit(7)\n"
)

OK_SCRIPT = "print('alpha'); print('beta')"


def _python_executor(mod):
    """NativeExecutor whose command prefix runs `python -c` instead of
    sudo/bash, so stream(<python code>) drives the real generator."""
    prefix = [sys.executable, "-c"]

    class _Exec(mod.NativeExecutor):
        def _cmd_prefix(self):       # jjp / spooky / bof NativeExecutor
            return prefix

        def _prefix(self):           # core NativeExecutor
            return prefix

    return _Exec()


@pytest.mark.parametrize("mod", MODULES, ids=MODULE_IDS)
def test_stream_success_yields_lines_unchanged(mod):
    ex = _python_executor(mod)
    assert list(ex.stream(OK_SCRIPT, timeout=30)) == ["alpha", "beta"]


@pytest.mark.parametrize("mod", MODULES, ids=MODULE_IDS)
def test_stream_failure_carries_output_tail(mod):
    ex = _python_executor(mod)
    with pytest.raises(mod.CommandError) as ei:
        list(ex.stream(FAIL_SCRIPT, timeout=30))
    err = ei.value
    assert err.returncode == 7
    assert "No space left on device" in err.output
    assert "progress 10%" in err.output


@pytest.mark.parametrize("mod", MODULES, ids=MODULE_IDS)
def test_stream_failure_lines_were_still_yielded(mod):
    # Buffering the tail must not eat the live stream the caller sees.
    ex = _python_executor(mod)
    seen = []
    with pytest.raises(mod.CommandError):
        for line in ex.stream(FAIL_SCRIPT, timeout=30):
            seen.append(line)
    assert "progress 10%" in seen
