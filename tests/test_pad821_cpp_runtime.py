"""PAD-821: Auto-name call-outs died on a clean Windows PC with "Could not
find module ...ctranslate2.dll (or one of its dependencies)" right after the
prerequisite list read all green.

ctranslate2.dll (and onnxruntime, astc_encoder, UnityPy's boost module)
import MSVCP140.dll, the Visual C++ runtime, which the Python embeddable zip
does not carry; a PC without the Redistributable has none.  The installer
now ships it beside python.exe, the faster-whisper prerequisite row checks
for it, and a load failure reads as a plain message, not a traceback.
"""

import os
import sys
from pathlib import Path

from pinball_decryptor.core import prereqs
from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.core.prereqs import Prerequisite

BUILD_PS1 = Path(__file__).resolve().parent.parent / "installer" / "build.ps1"

WHISPER = Prerequisite(name="faster-whisper", where="host",
                       probe="python:faster_whisper",
                       reason="Auto-name call-outs",
                       install_hint="pip install faster-whisper")


def test_build_bundles_the_cpp_runtime_beside_python():
    text = BUILD_PS1.read_text(encoding="utf-8")
    for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
                "msvcp140_1.dll", "msvcp140_2.dll"):
        assert '"%s"' % dll in text, dll
    # copied into the bundled Python's own folder, before the installer
    # is compiled, and a missing source stops the build
    copy = text.index("Copy-Item -Path $src -Destination (Join-Path $PythonDir $dll)")
    assert copy < text.index("Compiling installer")
    assert "install the Visual C++ 2015-2022 Redistributable" in text
    # the smoke test fails the build when the runtime comes from elsewhere
    smoke = text.index("C++ runtime smoke test failed")
    assert "exit 1" in text[smoke:smoke + 120]


def _fake_python(tmp_path, monkeypatch, beside=False, system32=False):
    exe_dir = tmp_path / "python"
    root = tmp_path / "Windows"
    (exe_dir).mkdir()
    (root / "System32").mkdir(parents=True)
    if beside:
        (exe_dir / "msvcp140.dll").write_bytes(b"MZ")
    if system32:
        (root / "System32" / "msvcp140.dll").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(exe_dir / "python.exe"))
    monkeypatch.setenv("SystemRoot", str(root))


def test_runtime_found_beside_python_or_in_system32(tmp_path, monkeypatch):
    _fake_python(tmp_path, monkeypatch)
    assert prereqs.cpp_runtime_found() is False
    (tmp_path / "python" / "msvcp140.dll").write_bytes(b"MZ")
    assert prereqs.cpp_runtime_found() is True
    os.remove(tmp_path / "python" / "msvcp140.dll")
    (tmp_path / "Windows" / "System32" / "msvcp140.dll").write_bytes(b"MZ")
    assert prereqs.cpp_runtime_found() is True


def test_runtime_never_asked_for_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert prereqs.cpp_runtime_found() is True


def test_whisper_row_red_without_the_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(prereqs, "_probe_python_import",
                        lambda m: (True, m + " 1.2.1"))
    _fake_python(tmp_path, monkeypatch)
    r = prereqs.check_prerequisite(WHISPER)
    assert r.ok is False
    assert "MSVCP140.dll" in r.message
    assert "Visual C++" in r.install_hint
    assert "pip install" not in r.install_hint


def test_whisper_row_green_with_the_bundled_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(prereqs, "_probe_python_import",
                        lambda m: (True, m + " 1.2.1"))
    _fake_python(tmp_path, monkeypatch, beside=True)
    r = prereqs.check_prerequisite(WHISPER)
    assert (r.ok, r.message) == (True, "faster_whisper 1.2.1")


def test_other_python_rows_do_not_look_for_it(tmp_path, monkeypatch):
    monkeypatch.setattr(prereqs, "_probe_python_import",
                        lambda m: (True, m + " 2.0"))
    _fake_python(tmp_path, monkeypatch)
    numpy = Prerequisite(name="numpy", where="host", probe="python:numpy",
                         reason="", install_hint="pip install numpy")
    assert prereqs.check_prerequisite(numpy).ok is True


def test_engine_that_will_not_load_is_a_plain_message(tmp_path, monkeypatch):
    """The user's exact failure: importing faster_whisper raised the
    FileNotFoundError ctypes gives for a DLL whose dependency is missing."""
    pkg = tmp_path / "site" / "faster_whisper"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "raise FileNotFoundError(\"Could not find module "
        "'C:\\\\x\\\\ctranslate2.dll' (or one of its dependencies). Try "
        "using the full path with constructor syntax.\")\n")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)

    from pinball_decryptor.core.transcribe import TranscribePipeline
    logs, done = [], []
    pipe = TranscribePipeline(str(tmp_path), lambda t, lvl="info": logs.append((lvl, t)),
                              lambda *a: None, lambda *a: None,
                              lambda ok, msg: done.append((ok, msg)))
    try:
        pipe._run()
    except PipelineError as e:
        assert "could not start its speech engine" in e.message
        assert "ctranslate2.dll" in e.message
    else:
        raise AssertionError("no PipelineError")
    pipe.run()
    assert done and done[0][0] is False
    assert not done[0][1].startswith("Unexpected error")
    assert not any("Traceback" in t for _, t in logs)
