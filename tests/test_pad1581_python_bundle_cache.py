"""PAD-1581: the release job keeps the bundled Python between runs.

installer/build.ps1 takes -PythonCache and reuses a bundle whose fingerprint
(Python version, build.ps1, the three pinned requirement lists) matches; the
release workflow restores that folder with actions/cache.  The workflow's key
must cover every file build.ps1 fingerprints, or a release could restore a
bundle made from other inputs (build.ps1 would rebuild it, but the stale
cache would then never be replaced under the same key).
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BUILD = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
STEPS = WORKFLOW["jobs"]["build-windows"]["steps"]


def _fingerprinted_requirements():
    block = BUILD[BUILD.index("$fpParts = @("):BUILD.index("$fingerprint =")]
    return set(re.findall(r'"(requirements[\w-]*\.txt)"', block))


def test_build_fingerprints_what_it_installs():
    installed = set(re.findall(r'Join-Path \$ProjectDir "(requirements[\w-]*\.txt)"',
                               BUILD[BUILD.index("Installing pinned deps") - 400:]))
    assert installed, "build.ps1 no longer names its requirement lists"
    assert installed <= _fingerprinted_requirements()
    assert "$MyInvocation.MyCommand.Path" in BUILD[BUILD.index("$fpParts = @("):]
    assert 'python=$PythonVersion' in BUILD


def test_workflow_key_covers_the_fingerprint():
    cache = next(s for s in STEPS if str(s.get("uses", "")).startswith("actions/cache@"))
    key = cache["with"]["key"]
    hashed = set(re.findall(r"'([^']+)'", key[key.index("hashFiles("):]))
    assert "installer/build.ps1" in hashed
    assert _fingerprinted_requirements() <= hashed
    assert "steps.py.outputs.python-version" in key
    assert "pad-python" in cache["with"]["path"]


def test_cache_is_restored_before_the_build_that_uses_it():
    names = [s.get("name") for s in STEPS]
    cache_i = next(i for i, s in enumerate(STEPS)
                   if str(s.get("uses", "")).startswith("actions/cache@"))
    build_i = names.index("Build installer")
    assert cache_i < build_i
    assert "-PythonCache" in STEPS[build_i]["run"]
    assert "pad-python" in STEPS[build_i]["run"]


def test_cached_copy_is_taken_before_the_per_build_steps():
    # The C++ runtime comes from the runner image's System32 and the final
    # ._pth is rewritten every build: both must run on a hit too.
    keep = BUILD.index("Keeping the bundled Python")
    assert keep < BUILD.index("# --- Visual C++ runtime, app-local")
    assert keep < BUILD.index("# --- Patch python3XX._pth for final layout")
    assert keep < BUILD.index("# --- Smoke tests")
