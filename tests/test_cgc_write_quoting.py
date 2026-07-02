"""Regression test: the CGC Write pipeline must shell-quote the user's
image paths in its ``dd`` commands.

A user whose output folder contained a space (".../AFMr Decryptor/...")
hit ``dd: Unrecognized operand 'Decryptor/...img'`` because the path was
interpolated into ``dd if={out_exec} ...`` unquoted, so ``bash`` split it
on the space.  The copy original->output step had already run, so an
*unmodified* .img was left in the destination -- it booted fine but showed
none of the user's changes.

This test drives ``WritePipeline._run`` with a fake recording executor and
spaced input/output/asset paths, then asserts every emitted ``dd`` command
tokenizes into only ``dd`` + ``key=value`` operands (no path fragment ever
splits off into a stray token).  No real .img or WSL needed.
"""

import shlex

import pytest

from pinball_decryptor.core.executor import WslExecutor
from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline
from pinball_decryptor.plugins.cgc.pipeline import WritePipeline

# dd operands we expect after the verb; anything else means a path split.
_DD_OPERAND_PREFIXES = ("if=", "of=", "bs=", "skip=", "seek=", "count=",
                        "conv=", "status=", "iflag=", "oflag=")


class _RecordingExecutor(WslExecutor):
    """Reuses WslExecutor.to_exec_path (pure string logic, no WSL) but
    records every command instead of shelling out."""

    def __init__(self):
        super().__init__()
        self.commands = []

    def run(self, bash_cmd, timeout=120):
        self.commands.append(bash_cmd)
        # The re-packed-P3 fsck guard parses a trailing "__RC__<code>"; hand it
        # a clean result so the pipeline proceeds (this test isn't about fsck).
        if "e2fsck" in bash_cmd:
            return "__RC__0"
        return ""  # every other caller tolerates empty stdout


def _drive_write(tmp_path, monkeypatch):
    # Spaces in EVERY user-controlled path: input image, output image, and
    # the modified asset's host path.
    in_dir = tmp_path / "AFMr Decryptor in"
    in_dir.mkdir()
    original = in_dir / "AttackFromMars100Installer.img"
    original.write_bytes(b"\x00" * 1024)  # only its size is read

    out_dir = tmp_path / "AFMr Decryptor out"
    output = out_dir / "AttackFromMars100Installer.img"

    assets = tmp_path / "afm assets"
    assets.mkdir()
    changed_host = assets / "sound bank" / "audio_001.wav"

    # Neutralise everything the run touches except the dd-command building.
    monkeypatch.setattr(cgc_pipeline, "detect_game", lambda p: "afm_remake")
    monkeypatch.setattr(cgc_pipeline, "read_checksums",
                        lambda d: {"snd/audio_001.wav": "deadbeef"})
    monkeypatch.setattr(cgc_pipeline, "_diff_assets",
                        lambda a, b: ({"snd/audio_001.wav": str(changed_host)}, []))
    monkeypatch.setattr(cgc_pipeline, "_verify_executor_tools", lambda ex: None)
    monkeypatch.setattr(cgc_pipeline, "_copy_with_progress",
                        lambda *a, **k: None)
    monkeypatch.setattr(cgc_pipeline, "find_data_partition",
                        lambda img: {"start_bytes": 3645 * 1024 ** 2,
                                     "size_bytes": 3702 * 1024 ** 2,
                                     "start_lba": 7464960})
    monkeypatch.setattr(cgc_pipeline, "_parse_mbr_for_linux",
                        lambda h: {"start_bytes": 100 * 1024 ** 2,
                                   "size_bytes": 3000 * 1024 ** 2,
                                   "start_lba": 204800})

    done = {}
    wp = WritePipeline(
        str(original), str(assets), str(output),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda ok, msg: done.update(ok=ok, msg=msg))
    rec = _RecordingExecutor()
    wp.executor = rec
    wp._run()
    return rec, done, rec.to_exec_path(str(output))


def test_write_dd_commands_quote_spaced_paths(tmp_path, monkeypatch):
    rec, done, out_exec = _drive_write(tmp_path, monkeypatch)

    assert done.get("ok") is True, done
    dd_cmds = [c for c in rec.commands if c.startswith("dd ")]
    assert dd_cmds, "expected the Write pipeline to emit dd commands"

    for cmd in dd_cmds:
        tokens = shlex.split(cmd)  # parses exactly as bash word-splits
        assert tokens[0] == "dd"
        for tok in tokens[1:]:
            assert tok.startswith(_DD_OPERAND_PREFIXES), (
                f"path split into a stray token {tok!r} in: {cmd}")

    # And the spaced output path really did flow through intact (so the test
    # is exercising the bug, not a no-op).
    assert " " in out_exec
    assert any(f"if={out_exec}" in shlex.split(c) for c in dd_cmds)
    assert any(f"of={out_exec}" in shlex.split(c) for c in dd_cmds)


def test_write_dd_commands_are_byte_exact(tmp_path, monkeypatch):
    """Nested partition dd's must copy the *exact* byte size, not a whole
    number of MiB.

    Pulp Fiction's P3 is 4607.998 MiB; the old ``count={size_bytes //
    (1024**2)}`` dropped its sub-MiB tail, so the round-tripped ext4 came out
    255 blocks shorter than its superblock declared ("likely corrupt" per
    e2fsck) and the machine froze mounting /data at power-up.  Every dd that
    moves a partition must therefore use byte-granular ``*_bytes`` flags with
    the true byte count.
    """
    rec, done, _out = _drive_write(tmp_path, monkeypatch)
    # find_data_partition/_parse_mbr_for_linux are monkeypatched to exact byte
    # sizes above; assert those exact values reach the count= operand and that
    # no count is a floored-MiB value.
    p3_size = 3702 * 1024 ** 2
    inner_size = 3000 * 1024 ** 2
    dd_cmds = [c for c in rec.commands if c.startswith("dd ")]
    counts = []
    for cmd in dd_cmds:
        toks = shlex.split(cmd)
        # A byte-exact copy must declare its byte-granularity intent.
        flag_toks = [t for t in toks if t.startswith(("iflag=", "oflag="))]
        assert any("count_bytes" in t for t in flag_toks), (
            f"dd missing count_bytes (would round count to whole MiB): {cmd}")
        for t in toks:
            if t.startswith("count="):
                counts.append(int(t.split("=", 1)[1]))
    # The exact partition sizes must appear verbatim as a count somewhere.
    assert p3_size in counts, counts
    assert inner_size in counts, counts


def test_write_modified_files_handles_apostrophe(tmp_path):
    """A callout filename with an apostrophe (transcribe-named, e.g.
    "S0315_C6 We'll blow ... Martians.wav") must not break the debugfs -w
    commands -- the old ``-R 'rm "...We'll..."'`` closed the outer quote early
    ("unexpected EOF while looking for matching '")."""
    rec = _RecordingExecutor()
    wp = WritePipeline.__new__(WritePipeline)
    wp.executor = rec
    wp._check_cancel = lambda: None
    wp._progress = lambda *a, **k: None
    wp._log = lambda *a, **k: None

    rel = "afmdata/samples/vol_25perc/S0315_C6 We'll blow the Martians.wav"
    host = str(tmp_path / "edited.wav")
    wp._write_modified_files("/tmp/inner.img", {rel: host}, "/home/debian/emumm")

    dbg = [c for c in rec.commands if c.startswith("debugfs -w -R")]
    assert dbg, "expected debugfs -w commands"
    for cmd in dbg:
        # shlex.split raises ValueError on unbalanced quotes -- the whole point.
        toks = shlex.split(cmd)
        ri = toks.index("-R")
        # The -R argument is ONE token carrying the full debugfs command with
        # the apostrophe filename intact.
        assert "We'll blow the Martians.wav" in toks[ri + 1], toks[ri + 1]
    # Both an rm and a write were issued for the file.
    assert any(shlex.split(c)[shlex.split(c).index("-R") + 1].startswith("rm ")
               for c in dbg)
    assert any(shlex.split(c)[shlex.split(c).index("-R") + 1].startswith("write ")
               for c in dbg)


def test_diff_excludes_orig_snapshots(tmp_path):
    """The ``.orig/`` pristine-snapshot store (core.staged_originals) must
    never be diffed as a game asset -- otherwise its files get written into
    the eMMC (and a snapshot of an apostrophe-named callout crashes debugfs)."""
    from pinball_decryptor.core.staged_originals import ORIG_DIR

    assets = tmp_path
    real = assets / "afmdata" / "samples" / "vol_25perc" / "S0001.wav"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"edited bytes")

    snap = (assets / ORIG_DIR / "afmdata" / "samples" / "vol_25perc"
            / "S0315_C6 We'll blow the Martians.wav")
    snap.parent.mkdir(parents=True)
    snap.write_bytes(b"pristine original")

    # Baseline md5 differs from the on-disk real file -> it's "changed".
    baseline = {"afmdata/samples/vol_25perc/S0001.wav": "deadbeef"}
    changed, _missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert "afmdata/samples/vol_25perc/S0001.wav" in changed
    assert not any(ORIG_DIR in k.split("/") for k in changed), \
        f".orig snapshots leaked into the write set: {list(changed)}"
