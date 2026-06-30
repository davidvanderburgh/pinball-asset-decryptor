"""Pulp Fiction JPS-bank extraction guards (fixture-free).

These cover the two safety nets added after a real-world report where
``pfspeech.bnk`` (the 92 MB uncensored speech bank) silently extracted to
an empty folder: a ``debugfs rdump`` had run out of staging-disk space and
truncated the file to 0 bytes, so the explode step quietly wrote a
near-empty manifest and no WAVs.

  * ``_verify_staged_sizes`` — compares each data-dir file's true inode
    size (debugfs) against its staged copy and reports any short/missing
    file (the disk-full signature), so Extract aborts with a clear error.
  * ``_explode_jps_banks`` — loudly flags any 0-byte or 0-sound bank
    instead of letting it pass as a successful "0 sound(s)" decode.
"""

import os

from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline
from pinball_decryptor.plugins.cgc.pipeline import ExtractPipeline


# ---------------------------------------------------------------------------
# _verify_staged_sizes
# ---------------------------------------------------------------------------

class _FakeExecutor:
    """Returns canned debugfs `ls -l` and `find` output keyed on the cmd."""

    def __init__(self, ls_out, find_out):
        self._ls_out = ls_out
        self._find_out = find_out

    def run(self, cmd, timeout=None):
        if "debugfs" in cmd:
            return self._ls_out
        if "find" in cmd:
            return self._find_out
        return ""


# A realistic debugfs `ls -l` listing of /home/ubuntu/pin/data: six banks,
# one sub-directory (which must be ignored), and the . / .. entries.
_LS_OUT = """\
 129560  40755 (2)   1000   1001      4096  4-Aug-2024 22:22 .
      2  40755 (2)      0      0      4096 18-Aug-2024 12:00 ..
 129571  100660 (1)   1000   1001 171042893  9-Apr-2024 09:49 pfsndfx.bnk
 129553  100660 (1)   1000   1001 232897688 19-Feb-2024 20:00 pfmusic.bnk
 129732  100660 (1)   1000   1001  96326912 25-Jan-2024 15:15 pfspeech.bnk
 129608  100660 (1)   1000   1001  93973300 25-Jan-2024 15:15 pfspeechBEEPD.bnk
 129563  100660 (1)   1000   1001   2872003  4-Aug-2024 22:22 pfsndui.bnk
 129593  100660 (1)   1000   1001   3173963 23-Sep-2023 14:55 pfsnddiag.bnk
 129999  40755 (2)   1000   1001      4096  4-Aug-2024 22:22 subdir
"""


def test_verify_staged_sizes_all_present():
    # Every file staged at its full source size -> no problems, and the
    # directory entry is correctly ignored.
    find_out = "\n".join([
        "171042893 pfsndfx.bnk",
        "232897688 pfmusic.bnk",
        "96326912 pfspeech.bnk",
        "93973300 pfspeechBEEPD.bnk",
        "2872003 pfsndui.bnk",
        "3173963 pfsnddiag.bnk",
    ])
    ex = _FakeExecutor(_LS_OUT, find_out)
    assert cgc_pipeline._verify_staged_sizes(ex, "inner.img", "/src", "/st") == []


def test_verify_staged_sizes_truncated_and_missing():
    # pfspeech.bnk truncated to 0 bytes; pfsnddiag.bnk never staged.
    find_out = "\n".join([
        "171042893 pfsndfx.bnk",
        "232897688 pfmusic.bnk",
        "0 pfspeech.bnk",
        "93973300 pfspeechBEEPD.bnk",
        "2872003 pfsndui.bnk",
    ])
    ex = _FakeExecutor(_LS_OUT, find_out)
    problems = cgc_pipeline._verify_staged_sizes(ex, "inner.img", "/src", "/st")
    by_name = {n: (sz, got) for n, sz, got in problems}
    assert by_name["pfspeech.bnk"] == (96326912, 0)
    assert by_name["pfsnddiag.bnk"] == (3173963, -1)  # missing
    assert "pfsndfx.bnk" not in by_name  # full-size files are fine


def test_verify_staged_sizes_unparseable_is_noop():
    # If debugfs gives nothing parseable, don't block extraction.
    ex = _FakeExecutor("debugfs 1.47.0\n", "")
    assert cgc_pipeline._verify_staged_sizes(ex, "inner.img", "/src", "/st") == []


# ---------------------------------------------------------------------------
# _explode_jps_banks loud guards
# ---------------------------------------------------------------------------

def _make_explode_pipeline(output_dir):
    """Build an ExtractPipeline shell wired only for _explode_jps_banks."""
    p = ExtractPipeline.__new__(ExtractPipeline)
    p.output_dir = str(output_dir)
    logs = []
    p._log = lambda msg, level="info": logs.append((level, msg))
    p._check_cancel = lambda: None
    p._progress = lambda *a, **k: None
    return p, logs


def test_explode_flags_empty_bank(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "pfspeech.bnk").write_bytes(b"")  # 0-byte -> the reported bug

    p, logs = _make_explode_pipeline(tmp_path)
    p._explode_jps_banks()

    errs = [m for lvl, m in logs if lvl == "error"]
    assert any("pfspeech.bnk" in m and "EMPTY" in m for m in errs)
    # Loud closing summary naming the failed bank.
    assert any("did not decode" in m and "pfspeech.bnk" in m for m in errs)
    # No WAVs were written for it.
    assert not (data / "pfspeech").exists() or not any(
        f.endswith(".wav") for f in os.listdir(data / "pfspeech"))


def test_explode_flags_nonempty_zero_sound_bank(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    # Non-empty but not a valid JPS bank -> parse finds 0 buffers.
    (data / "pfsndui.bnk").write_bytes(b"not a real jps bank" * 64)

    p, logs = _make_explode_pipeline(tmp_path)
    p._explode_jps_banks()

    errs = [m for lvl, m in logs if lvl == "error"]
    assert any("pfsndui.bnk" in m and "0 sounds" in m for m in errs)
    assert any("did not decode" in m for m in errs)


def test_explode_no_banks_is_silent(tmp_path):
    # No .bnk files at all -> early return, no error noise.
    p, logs = _make_explode_pipeline(tmp_path)
    p._explode_jps_banks()
    assert [m for lvl, m in logs if lvl == "error"] == []
