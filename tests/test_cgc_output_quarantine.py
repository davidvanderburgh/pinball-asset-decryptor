"""A CGC Write that refuses its own output must quarantine the file.

The final payload verify can only reject the output AFTER the file has been
fully written, so "The build was aborted; do not flash this image" used to
leave a complete-looking, flashable .img at the output path -- with all the
user's mods inside, indistinguishable from a good build by eye.  RTS flashed
exactly such a leftover and got a card that failed Card Diagnostics with the
armed-journal verdict.  The fix renames the rejected file to
``*.REJECTED.img`` (and the flash pipeline refuses that name), so the
refusal sticks.
"""

import sys

import pytest

from pinball_decryptor.plugins.cgc.pipeline import (
    FlashImagePipeline, PipelineError, WritePipeline)

# A syntactically valid device path for the current platform, so _run gets
# past the device check and reaches the .REJECTED refusal (nothing is ever
# opened -- the refusal raises first).
_DEV = "\\\\.\\PHYSICALDRIVE9" if sys.platform == "win32" else "/dev/sdz9"


def _bare_pipeline(original, output, logs=None):
    wp = WritePipeline.__new__(WritePipeline)
    wp.original_img = str(original)
    wp.output_img = str(output)
    if logs is None:
        wp._log = lambda *a, **k: None
    else:
        wp._log = lambda msg, level="info": logs.append((level, msg))
    return wp


def _mk_pair(tmp_path):
    original = tmp_path / "PulpFiction102Installer.img"
    original.write_bytes(b"orig")
    output = tmp_path / "PulpFiction102Installer_modified.img"
    output.write_bytes(b"built-but-refused")
    return original, output


def test_quarantine_renames_output(tmp_path):
    original, output = _mk_pair(tmp_path)
    logs = []
    wp = _bare_pipeline(original, output, logs)

    note = wp._quarantine_output()

    renamed = tmp_path / "PulpFiction102Installer_modified.REJECTED.img"
    assert not output.exists()
    assert renamed.read_bytes() == b"built-but-refused"
    # The note names the new file and lands in the error dialog text.
    assert "REJECTED" in note
    # And the rename was announced loudly in the log.
    assert any(lvl == "error" and "REJECTED" in msg for lvl, msg in logs)


def test_quarantine_replaces_stale_rejected_leftover(tmp_path):
    """A second failed build must not die on the previous run's quarantine
    file -- os.replace semantics, not os.rename."""
    original, output = _mk_pair(tmp_path)
    renamed = tmp_path / "PulpFiction102Installer_modified.REJECTED.img"
    renamed.write_bytes(b"previous failure")

    wp = _bare_pipeline(original, output)
    note = wp._quarantine_output()

    assert "REJECTED" in note
    assert not output.exists()
    assert renamed.read_bytes() == b"built-but-refused"


def test_quarantine_never_renames_inplace_source(tmp_path):
    """If output == original (in-place build) the file is the user's only
    copy of their source image -- leave it where it is."""
    same = tmp_path / "PulpFiction102Installer.img"
    same.write_bytes(b"orig")

    wp = _bare_pipeline(same, same)
    assert wp._quarantine_output() == ""
    assert same.read_bytes() == b"orig"


def test_final_verify_quarantines_on_refusal(tmp_path):
    """The armed-journal / empty-payload refusal must rename the output and
    say so in the raised error itself."""
    original, output = _mk_pair(tmp_path)
    wp = _bare_pipeline(original, output)

    def _refuse(expect_clean_journal=False):
        raise PipelineError("Verify",
                            "The finished installer's data partition still "
                            "has an armed ext4 journal (needs_recovery).")
    wp._verify_output_payload = _refuse

    with pytest.raises(PipelineError) as ei:
        wp._final_output_verify(expect_clean_journal=True)

    assert ei.value.phase == "Verify"
    assert "armed ext4 journal" in ei.value.message
    assert ".REJECTED" in ei.value.message
    assert not output.exists()
    assert (tmp_path
            / "PulpFiction102Installer_modified.REJECTED.img").exists()


def test_final_verify_passes_through_clean_build(tmp_path):
    original, output = _mk_pair(tmp_path)
    wp = _bare_pipeline(original, output)
    wp._verify_output_payload = lambda expect_clean_journal=False: None

    wp._final_output_verify(expect_clean_journal=True)  # no raise

    assert output.read_bytes() == b"built-but-refused"  # untouched


def test_flash_refuses_rejected_image(tmp_path):
    """The Flash button is the door the quarantine bolts shut: a *.REJECTED
    image must be refused before the device is touched."""
    img = tmp_path / "PulpFiction102Installer_modified.REJECTED.img"
    img.write_bytes(b"refused build")

    fp = FlashImagePipeline(
        str(img), _DEV,
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)

    with pytest.raises(PipelineError, match="REJECTED"):
        fp._run()


def test_flash_rejected_check_is_case_insensitive(tmp_path):
    img = tmp_path / "build.rejected.img"
    img.write_bytes(b"x")
    fp = FlashImagePipeline(
        str(img), _DEV,
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)
    with pytest.raises(PipelineError, match="REJECTED"):
        fp._run()
