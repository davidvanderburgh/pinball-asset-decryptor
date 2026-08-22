"""The CGC Write diff must never hand the app's own project files to debugfs.

Reported against v0.152.0 by a tester whose project folder was first extracted
under v0.43: every build died in the Write phase with

    logs/project.log did not land inside the game filesystem
    (expected 13,324 bytes, got NO FILE)
    /home/ubuntu/pin/logs/project.log: File not found by ext2_lookup

``logs/project.log`` is the per-project session log the app itself writes into
the folder it is working on (``core.session_log.set_project``).  It is kept out
of the ``.checksums.md5`` baseline on purpose -- and "not in the baseline" is
precisely what made ``_diff_assets``'s brand-new-file sweep claim it as a game
asset.  debugfs ``write`` cannot create the missing ``logs/`` directory inside
the ext4, so the file never landed and the post-write verify aborted the build.

``build/`` is the same trap with worse odds: it is where Write puts its own
output, so a second build would post a multi-GB installer image into the game
partition.
"""

import os

import pytest

from pinball_decryptor.core.checksums import NON_ASSET_DIRS, md5_file
from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline


def _assets_with_baseline(tmp_path):
    """A minimal CGC extract: one real asset, baselined and then edited."""
    assets = tmp_path / "assets"
    (assets / "data").mkdir(parents=True)
    asset = assets / "data" / "audio_001.wav"
    asset.write_bytes(b"stock bytes")
    baseline = {"data/audio_001.wav": md5_file(str(asset))}
    asset.write_bytes(b"modded bytes")
    return assets, baseline


def test_project_log_is_never_written_back(tmp_path):
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "logs").mkdir()
    (assets / "logs" / "project.log").write_text("session log", encoding="utf-8")

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert "logs/project.log" not in changed
    assert sorted(changed) == ["data/audio_001.wav"]
    assert missing == []


@pytest.mark.parametrize("folder", sorted(NON_ASSET_DIRS))
def test_no_app_written_folder_reaches_the_diff(tmp_path, folder):
    """build/, .hydrate/, card_files/ and logs/ are all ours, not the card's."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / folder).mkdir()
    (assets / folder / "payload.bin").write_bytes(b"app state, not game data")

    changed, _missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert not [rel for rel in changed if rel.startswith(folder + "/")], changed


def test_stale_baseline_entry_under_build_is_ignored(tmp_path):
    """A pre-NON_ASSET_DIRS extract (v0.43 and older) can have baselined the
    build output itself; that entry must not resurrect a multi-GB write."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "build").mkdir()
    out = assets / "build" / "Installer.img"
    out.write_bytes(b"an old build")
    baseline["build/Installer.img"] = md5_file(str(out))
    out.write_bytes(b"a newer build")   # "modified" against that baseline

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert "build/Installer.img" not in changed
    assert "build/Installer.img" not in missing


def test_new_file_in_a_folder_the_game_lacks_is_reported_not_shipped(tmp_path):
    """debugfs cannot create a parent directory, so a new file in a folder the
    image does not have can only ever abort the build.  Skip it, and say so."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "my notes").mkdir()
    (assets / "my notes" / "ideas.txt").write_text("todo", encoding="utf-8")
    # A new file NEXT TO a baselined one is a real asset and must still ship.
    (assets / "data" / "audio_002.wav").write_bytes(b"brand new sound")

    lines = []
    changed, _missing = cgc_pipeline._diff_assets(
        str(assets), baseline, log=lambda msg, lvl="info": lines.append(msg))

    assert "data/audio_002.wav" in changed
    assert "my notes/ideas.txt" not in changed
    assert any("my notes/ideas.txt" in ln for ln in lines), lines


def test_missing_file_error_names_the_real_cause(tmp_path):
    """The abort used to lead with "ran out of free space" for a file that was
    never in the image at all, sending users off to resize a healthy
    partition."""
    class _NoSuchFileExecutor:
        def run(self, bash_cmd, timeout=120):
            if "stat " in bash_cmd:
                return ("/home/ubuntu/pin/logs/project.log: "
                        "File not found by ext2_lookup")
            return ""

        def to_exec_path(self, p):
            return "/mnt/c/" + p.replace(os.sep, "/")

    src = tmp_path / "project.log"
    src.write_bytes(b"x" * 13324)

    wp = cgc_pipeline.WritePipeline.__new__(cgc_pipeline.WritePipeline)
    wp.executor = _NoSuchFileExecutor()
    wp._log = lambda *a, **k: None
    wp._progress = lambda *a, **k: None
    wp._check_cancel = lambda: None

    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        wp._write_modified_files(
            "/tmp/inner.img", {"logs/project.log": str(src)},
            "/home/ubuntu/pin")

    msg = str(ei.value)
    assert "did not land inside the game filesystem" in msg
    assert "ran out of free space" not in msg
    assert "not a game asset" in msg
