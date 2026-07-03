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

    # Size handed to the repacked-emmc guard from both sides (staged file
    # and debugfs inode) so the pipeline proceeds; the guard's failure modes
    # get their own dedicated tests below.
    EMMC_SIZE = 3640655872
    # Byte size of every modified asset the tests stage on disk; the per-file
    # written-size verify stats the file inside the inner ext4 and must see
    # the same number.
    WAV_SIZE = 12

    def run(self, bash_cmd, timeout=120):
        self.commands.append(bash_cmd)
        # The re-packed-P3 fsck guard parses a trailing "__RC__<code>"; hand it
        # a clean result so the pipeline proceeds (this test isn't about fsck).
        if "e2fsck" in bash_cmd:
            return "__RC__0"
        if bash_cmd.startswith("dumpe2fs"):
            # Clean journal (no needs_recovery) -- the armed case gets its
            # own stateful executor below.
            return "Filesystem features:      has_journal ext_attr extent"
        if bash_cmd.startswith("stat -c%s"):
            return str(self.EMMC_SIZE)
        if bash_cmd.startswith("debugfs -R") and "'stat /emmc.img'" in bash_cmd:
            return (f"Inode: 14   Type: regular    Mode:  0644\n"
                    f"User:     0   Group:     0   Size: {self.EMMC_SIZE}\n"
                    f"Fragment:  Address: 0    Number: 0    Size: 0\n")
        if bash_cmd.startswith("debugfs -R") and "'stat " in bash_cmd:
            # per-file written-size verify inside the inner ext4
            return (f"Inode: 20   Type: regular    Mode:  0644\n"
                    f"User:     0   Group:     0   Size: {self.WAV_SIZE}\n"
                    f"Fragment:  Address: 0    Number: 0    Size: 0\n")
        return ""  # every other caller tolerates empty stdout


def _drive_write(tmp_path, monkeypatch):
    rec = _RecordingExecutor()
    done, _cmds = _drive_write_with(rec, tmp_path, monkeypatch)
    return rec, done, rec.to_exec_path(str(
        tmp_path / "AFMr Decryptor out" / "AttackFromMars100Installer.img"))


def _drive_write_with(rec, tmp_path, monkeypatch):
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
    changed_host.parent.mkdir()
    changed_host.write_bytes(b"x" * _RecordingExecutor.WAV_SIZE)

    # Neutralise everything the run touches except the dd-command building.
    monkeypatch.setattr(cgc_pipeline, "detect_game", lambda p: "afm_remake")
    monkeypatch.setattr(cgc_pipeline, "read_checksums",
                        lambda d: {"snd/audio_001.wav": "deadbeef"})
    monkeypatch.setattr(cgc_pipeline, "_diff_assets",
                        lambda a, b, **k: ({"snd/audio_001.wav": str(changed_host)}, []))
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
    wp.executor = rec
    wp.run()  # run(), not _run(): converts PipelineError into done(False, msg)
    return done, rec.commands


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
    host_file = tmp_path / "edited.wav"
    host_file.write_bytes(b"x" * _RecordingExecutor.WAV_SIZE)
    host = str(host_file)
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


def test_write_verifies_inner_fs_and_repacked_emmc(tmp_path, monkeypatch):
    """The Write pipeline must (a) e2fsck the INNER game ext4 after the
    debugfs mods (it's the fs the game boots from; until v0.32.2 it shipped
    unchecked) and (b) verify /emmc.img inside the re-packed P3 exists at its
    exact byte size (a missing/short emmc.img passes e2fsck -- deleting it
    outright leaves a CLEAN fs -- but fails on the machine as the installer's
    "SHELL ERROR", RTS's Pulp Fiction report)."""
    rec, done, _out = _drive_write(tmp_path, monkeypatch)
    assert done.get("ok") is True, done

    fsck_targets = [c for c in rec.commands if c.startswith("e2fsck -fn")]
    assert any("inner.img" in c for c in fsck_targets), (
        f"inner game fs never fsck'd: {fsck_targets}")
    assert any("p3.img" in c for c in fsck_targets), (
        f"re-packed P3 never fsck'd: {fsck_targets}")

    # The emmc guard consulted both sides: staged size + debugfs inode size.
    assert any(c.startswith("stat -c%s") and "emmc.img" in c
               for c in rec.commands), "staged emmc.img size never read"
    assert any(c.startswith("debugfs -R") and "'stat /emmc.img'" in c
               for c in rec.commands), "re-packed /emmc.img never stat'd"


class _ArmedJournalExecutor(_RecordingExecutor):
    """Reports every staged partition's ext4 journal as ARMED
    (needs_recovery) until an ``e2fsck -fy`` has run against that image --
    the real CGC condition: stock installers ship P3 with the factory's
    stale journal still pending."""

    def __init__(self):
        super().__init__()
        self.replayed = set()

    def run(self, bash_cmd, timeout=120):
        if bash_cmd.startswith("dumpe2fs -h "):
            self.commands.append(bash_cmd)
            target = shlex.split(bash_cmd)[2]
            if target in self.replayed:
                return "Filesystem features:      has_journal ext_attr extent"
            return ("Filesystem features:      has_journal ext_attr "
                    "needs_recovery extent")
        if bash_cmd.startswith("e2fsck -fy "):
            self.commands.append(bash_cmd)
            self.replayed.add(shlex.split(bash_cmd)[2])
            return "__RC__0"
        return super().run(bash_cmd, timeout)


def test_write_replays_armed_journal_before_any_debugfs(tmp_path, monkeypatch):
    """THE Pulp Fiction SHELL ERROR root cause (proven on two machines):
    stock CGC installers ship P3 with the factory journal armed
    (needs_recovery).  Our debugfs edits bypass the journal, so the
    machine's first mount of /data replayed the stale factory transactions
    OVER the edits and reverted /emmc.img to a deleted 0-byte inode --
    dcfldd then had nothing to copy.  The Write pipeline must replay/retire
    the journal (e2fsck -fy) BEFORE any debugfs touches a staged partition
    image."""
    rec = _ArmedJournalExecutor()
    # reuse _drive_write's monkeypatching but with the stateful executor
    done, cmds = _drive_write_with(rec, tmp_path, monkeypatch)
    assert done.get("ok") is True, done

    for img in ("p3.img", "inner.img"):
        replay_idx = [i for i, c in enumerate(cmds)
                      if c.startswith("e2fsck -fy ") and img in c]
        assert replay_idx, f"no journal replay ever ran for {img}: {cmds}"
        debugfs_idx = [i for i, c in enumerate(cmds)
                       if c.startswith("debugfs") and img in c]
        assert debugfs_idx, f"expected debugfs commands against {img}"
        assert replay_idx[0] < debugfs_idx[0], (
            f"journal replay for {img} ran AFTER debugfs first touched it -- "
            f"the machine would replay the stale journal over the edits")


def test_write_verifies_each_written_file_size(tmp_path, monkeypatch):
    """debugfs write failures are masked by `|| true` (needed for the grep)
    and by debugfs's own exit-0-on-error habit; a dropped/truncated file must
    be caught by the post-write per-file stat, not shipped."""
    class _TruncatingExecutor(_RecordingExecutor):
        def run(self, bash_cmd, timeout=120):
            if (bash_cmd.startswith("debugfs -R") and "'stat " in bash_cmd
                    and "/emmc.img'" not in bash_cmd):
                self.commands.append(bash_cmd)
                return "audio_001.wav: File not found by ext2_lookup\n"
            return super().run(bash_cmd, timeout)

    rec = _TruncatingExecutor()
    done, _cmds = _drive_write_with(rec, tmp_path, monkeypatch)
    assert done.get("ok") is False
    assert "did not land inside the game filesystem" in done.get("msg", "")


class _FixedOutputExecutor:
    def __init__(self, outputs):
        self.outputs = outputs  # list of successive run() results

    def run(self, bash_cmd, timeout=120):
        return self.outputs.pop(0)


def _bare_write_pipeline(executor):
    wp = WritePipeline.__new__(WritePipeline)
    wp.executor = executor
    wp._log = lambda *a, **k: None
    return wp


def test_verify_repacked_emmc_rejects_missing_file():
    """debugfs `stat` on a deleted /emmc.img prints "File not found by
    ext2_lookup" (no Size line) and still exits 0 -- the guard must raise."""
    wp = _bare_write_pipeline(_FixedOutputExecutor(
        ["3640655872", "/emmc.img: File not found by ext2_lookup \n"]))
    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        wp._verify_repacked_emmc("/tmp/p3.img", "/tmp/emmc.img")
    assert "NO FILE" in str(ei.value)


def test_verify_repacked_emmc_rejects_short_file():
    wp = _bare_write_pipeline(_FixedOutputExecutor(
        ["3640655872",
         "Inode: 14   Type: regular\n"
         "User:     0   Group:     0   Size: 1073741824\n"
         "Fragment:  Address: 0    Number: 0    Size: 0\n"]))
    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        wp._verify_repacked_emmc("/tmp/p3.img", "/tmp/emmc.img")
    assert "1,073,741,824" in str(ei.value)


def test_verify_dumped_emmc_rejects_empty_source():
    """A source .img whose emmc.img dumped out empty/tiny (RTS's Pulp Fiction
    card carried a 0-byte payload) must abort the build -- the downstream
    staged-vs-repacked guard can't catch it (0 == 0 passes)."""
    wp = _bare_write_pipeline(_FixedOutputExecutor(["0"]))
    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        wp._verify_dumped_emmc("/tmp/emmc.img")
    assert "empty or truncated" in str(ei.value)


def test_verify_dumped_emmc_rejects_truncated_source():
    wp = _bare_write_pipeline(_FixedOutputExecutor([str(10 * 1024 * 1024)]))
    with pytest.raises(cgc_pipeline.PipelineError):
        wp._verify_dumped_emmc("/tmp/emmc.img")


def test_verify_dumped_emmc_accepts_plausible_source():
    wp = _bare_write_pipeline(_FixedOutputExecutor([str(3_640_655_872)]))
    wp._verify_dumped_emmc("/tmp/emmc.img")  # no raise


def test_verify_repacked_emmc_accepts_exact_size():
    wp = _bare_write_pipeline(_FixedOutputExecutor(
        ["3640655872",
         "Inode: 14   Type: regular\n"
         "User:     0   Group:     0   Size: 3640655872\n"
         "Fragment:  Address: 0    Number: 0    Size: 0\n"]))
    wp._verify_repacked_emmc("/tmp/p3.img", "/tmp/emmc.img")  # no raise


class _FakeExt4Reader:
    """Minimal stand-in: root dir holds one file 'emmc.img' of *size* bytes."""
    _EMMC_INO = 14

    def __init__(self, size):
        self._size = size

    def read_inode(self, ino):
        return {"size": self._size if ino == self._EMMC_INO else 0,
                "mode": 0x8000}

    def _iter_dir(self, node):
        yield ("emmc.img", self._EMMC_INO, 1)


def _run_output_guard(tmp_path, monkeypatch, emmc_size):
    img = tmp_path / "out.img"
    img.write_bytes(b"\x00" * 512)  # just needs to be openable
    monkeypatch.setattr(cgc_pipeline, "find_data_partition",
                        lambda p: {"start_bytes": 0, "size_bytes": 1 << 30})
    import pinball_decryptor.plugins.stern.ext4 as ext4mod
    monkeypatch.setattr(ext4mod, "Ext4Reader",
                        lambda f, off, sz: _FakeExt4Reader(emmc_size))
    wp = WritePipeline.__new__(WritePipeline)
    wp.output_img = str(img)
    wp._log = lambda *a, **k: None
    wp._verify_output_payload()


def test_output_payload_guard_aborts_on_empty(tmp_path, monkeypatch):
    """The finished-output guard must reject a 0-byte emmc.img -- the no-op
    copy path's only defence against a source whose payload is empty (RTS's
    recurring 0-byte/2023 payload copied straight through to the card)."""
    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        _run_output_guard(tmp_path, monkeypatch, 0)
    assert "empty or truncated" in str(ei.value)


def test_output_payload_guard_aborts_on_truncated(tmp_path, monkeypatch):
    with pytest.raises(cgc_pipeline.PipelineError):
        _run_output_guard(tmp_path, monkeypatch, 100 * 1024 * 1024)


def test_output_payload_guard_accepts_real_payload(tmp_path, monkeypatch):
    _run_output_guard(tmp_path, monkeypatch, 3_640_655_872)  # no raise


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
