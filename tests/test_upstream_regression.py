"""Regression check vs the four upstream standalone decryptor repos.

Runs the equivalent of:
    python tests/verify_no_upstream_regression.py

…inside pytest, so a dev environment with the sibling repos checked
out will catch any accidental drift on the verbatim-lifted files as
part of `pytest tests`.

CI runners that only have this repo checked out won't have the
upstreams next to them, so this test skips cleanly there.
"""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
UPSTREAMS = [
    ROOT.parent / "pb" / "pb_decryptor",
    ROOT.parent / "spooky" / "spooky_decryptor",
    ROOT.parent / "bof" / "bof_decryptor",
    ROOT.parent / "jjp" / "jjp_decryptor",
]


@pytest.mark.skipif(
    not all(p.is_dir() for p in UPSTREAMS),
    reason="upstream decryptor repos not present alongside this one")
def test_no_regression_vs_upstream():
    """Run the verification script and assert exit code 0.

    Failure means either:
      - A file marked IDENTICAL has drifted from upstream (bug to fix here)
      - A file marked IMPORT-ONLY has changes beyond the rewire patterns
      - The plan in the script is stale (file moved / renamed)

    The verbose verification output is captured + included in the
    pytest failure message so the regression is investigable without
    re-running the script.
    """
    script = ROOT / "tests" / "verify_no_upstream_regression.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        "verify_no_upstream_regression.py reported drift:\n"
        + result.stdout + "\n" + result.stderr)
