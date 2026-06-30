"""Regression tests for the JJP executor's tree-kill-hardened command runners.

The JJP pipeline shadows the (verbatim-lift) executor's ``run`` / ``run_host``
with timeout-safe versions: on a momentarily wedged WSL (e.g. a cold boot right
after ``wsl --shutdown``), ``subprocess.run(timeout=...)`` kills only the
immediate child and then deadlocks reaping a grandchild that still holds the
stdout pipe — silently hanging the whole extract.  These tests drive the real
hardened ``run`` against a short-lived Python subprocess (no WSL needed) and
assert it returns/raises *promptly* on a timeout instead of blocking.
"""

import sys
import time

import pytest

from pinball_decryptor.plugins.jjp import pipeline as P
from pinball_decryptor.plugins.jjp.executor import CommandError


class _FakeNative:
    """Stub whose class name is ``NativeExecutor`` so the hardened ``run`` builds
    ``[*_cmd_prefix(), bash_cmd]`` — here a real ``python -c`` invocation."""

    # The hardened _argv() dispatches on type(executor).__name__.
    __name__ = "NativeExecutor"

    def _cmd_prefix(self):
        return [sys.executable, "-c"]

    def run(self, bash_cmd, timeout=120):  # pragma: no cover - must be shadowed
        raise AssertionError("original run should have been shadowed")


# Make type(ex).__name__ == "NativeExecutor".
_FakeNative.__qualname__ = "NativeExecutor"
_FakeNative.__name__ = "NativeExecutor"


@pytest.fixture
def hardened():
    ex = _FakeNative()
    P._install_robust_run_host(ex)
    return ex


def test_install_shadows_run_and_host(hardened):
    # run_host/run_win point at the host runner; run is the hardened closure.
    assert hardened.run_host is P._robust_run_host
    assert hardened.run_win is P._robust_run_host
    assert hardened.run is not _FakeNative.run  # instance attr shadows method


def test_run_success_returns_stdout(hardened):
    assert hardened.run("print('hi')", timeout=10).strip() == "hi"


def test_run_nonzero_raises_commanderror(hardened):
    with pytest.raises(CommandError) as ei:
        hardened.run("import sys; sys.exit(3)", timeout=10)
    assert ei.value.returncode == 3


def test_run_timeout_is_prompt_not_deadlocked(hardened):
    # The whole point: a 30s sleep with a 1s timeout must come back in ~1s
    # (tree-killed), not block for 30s.
    t0 = time.time()
    with pytest.raises(CommandError) as ei:
        hardened.run("import time; time.sleep(30)", timeout=1)
    elapsed = time.time() - t0
    assert "timed out" in str(ei.value).lower()
    assert elapsed < 10, "hardened run did not return promptly (%.1fs)" % elapsed


def test_unknown_executor_falls_back(monkeypatch):
    # An executor whose class name isn't recognised keeps its original run.
    class Weird:
        def run(self, bash_cmd, timeout=120):
            return "orig:" + bash_cmd
    ex = Weird()
    ex.run = P._robust_run(ex)
    assert ex.run("x") == "orig:x"
