"""Card-diagnostics reader (plugins.cgc.diagnose).

After an on-machine install fails (pinstall's "SHELL ERROR"), the
installer leaves dcfldd's output in procstat.txt on the card's ext4 P2 --
unreachable for most users on Windows (wsl --mount can't attach the
typical removable-media USB SD reader; RTS hit exactly that wall).  The
diagnose module reads it back over core.rawdevice + the pure-Python ext4
reader instead.

The end-to-end test drives the real Pulp Fiction installer image bundled
under images/CGC/ (skipped when absent, e.g. on CI).
"""

import os
import struct

import pytest

from pinball_decryptor.plugins.cgc.diagnose import (
    _mbr_partitions, diagnose_installer_card)
from pinball_decryptor.plugins.cgc.manufacturer import CGCManufacturer

_PF_IMG = os.path.join(
    os.path.dirname(__file__), "..", "images", "CGC",
    "PulpFiction102Installer.img")


@pytest.mark.skipif(not os.path.isfile(_PF_IMG),
                    reason="bundled PF installer image not present")
def test_diagnose_reads_stock_pf_installer():
    logs = []
    report = diagnose_installer_card(_PF_IMG, log=logs.append)

    # Partition map + config parsed.
    assert "GAME_NAME = Pulp Fiction" in report
    assert "INSTALL_DEST = /dev/mmcblk1" in report

    # The stock card ships its factory journal armed, and the jbd2 scan
    # dates its single pending transaction to CGC's mastering-day install
    # test (minutes before procstat.txt's 16:44 timestamp).  An OLD payload
    # mtime keeps it out of the problems list -- stock cards install fine.
    assert "ext4 journal: ARMED" in report
    assert ("pending transactions: 1, newest committed "
            "2024-08-19 16:39 UTC") in report
    assert "VERDICT: no obvious problem" in report

    # procstat.txt found, recognised as CGC's factory leftover (its mtime
    # matches the other mastering-time files), with the completed-copy
    # markers from CGC's own mastering run.
    assert "procstat.txt" in report
    assert "factory files" in report
    assert "100% of 3472 MB" in report
    assert "records in/out present" in report

    # Payload check: emmc.img present at full size and readable.
    assert "/emmc.img: present, 3,640,655,872 bytes" in report
    assert "head/tail read: OK" in report

    # Progress callbacks fired and nothing crashed midway.
    assert logs and logs[-1] == "Done."


def test_assess_payload_flags_empty_old_mtime_names_journal_revert():
    """The 0-byte /emmc.img dated 2023 (older than the build) is the SHELL
    ERROR, and the verdict must name the proven mechanism: the machine's
    boot-time replay of the stale factory journal reverting a pre-v0.36.0
    modded build (with bad-source as the fallback for never-booted images)."""
    import datetime as dt
    from pinball_decryptor.plugins.cgc.diagnose import _assess_payload_size

    now = dt.datetime(2026, 7, 2, 21, 0, tzinfo=dt.timezone.utc)
    old = dt.datetime(2023, 6, 28, tzinfo=dt.timezone.utc)
    msg = _assess_payload_size(0, old, now)
    assert msg is not None
    assert "0 bytes" in msg
    assert "SHELL ERROR" in msg
    assert "replayed it OVER" in msg and "v0.36.0" in msg
    assert "source .img" in msg  # never-booted fallback still mentioned


def test_assess_payload_fresh_mtime_blames_build():
    """A too-small payload with a fresh (recent) mtime points at the build
    writing it empty, not the source."""
    import datetime as dt
    from pinball_decryptor.plugins.cgc.diagnose import _assess_payload_size

    now = dt.datetime(2026, 7, 2, 21, 0, tzinfo=dt.timezone.utc)
    fresh = now - dt.timedelta(minutes=3)
    msg = _assess_payload_size(1024, fresh, now)
    assert msg is not None
    assert "written empty during the build" in msg


def test_assess_payload_accepts_real_size():
    import datetime as dt
    from pinball_decryptor.plugins.cgc.diagnose import _assess_payload_size
    now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
    assert _assess_payload_size(3_640_655_872, now, now) is None


# ---------------------------------------------------------------------------
# ext4 journal (jbd2) inspection: dating the armed journal's pending
# transactions to tell stale FACTORY transactions (the proven payload-revert
# SHELL ERROR) from a journal armed by a mount AFTER the build (machine boot,
# or a Windows ext4 driver writing to the card) -- RTS's 2026-07-05 card
# report couldn't distinguish the two.
# ---------------------------------------------------------------------------

_JBD2_MAGIC = 0xC03B3998


def _jbd2_block(btype, seq, bs=1024, commit_secs=None):
    blk = bytearray(bs)
    struct.pack_into(">III", blk, 0, _JBD2_MAGIC, btype, seq)
    if commit_secs is not None:
        struct.pack_into(">Q", blk, 0x30, commit_secs)
    return bytes(blk)


def test_parse_journal_sb_roundtrip():
    from pinball_decryptor.plugins.cgc.diagnose import _parse_journal_sb
    buf = bytearray(1024)
    struct.pack_into(">III", buf, 0, _JBD2_MAGIC, 4, 0)     # header, v2 sb
    struct.pack_into(">5I", buf, 0x0C, 1024, 8192, 1, 7, 42)
    assert _parse_journal_sb(bytes(buf)) == {
        "blocksize": 1024, "maxlen": 8192, "first": 1,
        "sequence": 7, "start": 42}


def test_parse_journal_sb_rejects_non_journal():
    from pinball_decryptor.plugins.cgc.diagnose import _parse_journal_sb
    assert _parse_journal_sb(b"\x00" * 1024) is None      # no magic
    assert _parse_journal_sb(b"\x00" * 8) is None         # too short
    commit = _jbd2_block(2, 7)                            # wrong blocktype
    assert _parse_journal_sb(commit) is None


def test_pending_commit_times_filters_replayed_and_noise():
    import datetime as dt
    from pinball_decryptor.plugins.cgc.diagnose import _pending_commit_times

    factory = int(dt.datetime(2024, 8, 19, 16, 39,
                              tzinfo=dt.timezone.utc).timestamp())
    blocks = [
        _jbd2_block(2, 7, commit_secs=factory),      # pending commit: counted
        _jbd2_block(2, 6, commit_secs=factory - 60), # replayed history: no
        _jbd2_block(1, 7),                           # descriptor block: no
        b"\x00" * 1024,                              # data block: no magic
        _jbd2_block(2, 8, commit_secs=0),            # implausible timestamp
        b"\xff" * 16,                                # runt: skipped
    ]
    times = _pending_commit_times(blocks, sequence=7)
    assert times == [dt.datetime(2024, 8, 19, 16, 39,
                                 tzinfo=dt.timezone.utc)]


def _dt(*args):
    import datetime as dt
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


def test_armed_journal_stale_factory_is_the_fatal_verdict():
    """Pending transactions dated BEFORE the build = the factory's stale
    journal: the machine's first mount reverts the payload (SHELL ERROR)."""
    from pinball_decryptor.plugins.cgc.diagnose import _armed_journal_problem
    msg = _armed_journal_problem((1, _dt(2024, 8, 19, 16, 39)),
                                 _dt(2026, 7, 5, 13, 9))
    assert msg is not None
    assert "BEFORE" in msg and "stale factory transactions" in msg
    assert "SHELL ERROR" in msg and "v0.36.0" in msg
    assert "2024-08-19 16:39 UTC" in msg


def test_armed_journal_post_build_mount_names_the_real_writer():
    """Pending transactions dated AFTER the build are NOT the factory's:
    something (machine boot, or a Windows ext4 driver) mounted the card
    after it was written.  The verdict must say so and steer the user to
    diagnosing the .img file to localize img-vs-card."""
    from pinball_decryptor.plugins.cgc.diagnose import _armed_journal_problem
    built = _dt(2026, 7, 5, 13, 9)
    msg = _armed_journal_problem((3, _dt(2026, 7, 5, 14, 30)), built)
    assert msg is not None
    assert "AFTER" in msg and "NOT the stale factory transactions" in msg
    assert "ext4 driver" in msg
    assert "Image file" in msg          # points at the file-mode diagnostic
    assert "v0.36.0" not in msg         # a rebuild is NOT the prescription


def test_armed_journal_empty_journal_is_not_a_problem():
    """needs_recovery over an EMPTY journal (s_start == 0): nothing to
    replay, a mount just clears the flag."""
    from pinball_decryptor.plugins.cgc.diagnose import _armed_journal_problem
    assert _armed_journal_problem((0, None), _dt(2026, 7, 5)) is None


def test_armed_journal_unreadable_falls_back_to_stale_wording():
    """When the journal can't be read the old (worst-case) advice stands,
    with an honest note that the transactions couldn't be dated."""
    from pinball_decryptor.plugins.cgc.diagnose import _armed_journal_problem
    msg = _armed_journal_problem(None, _dt(2026, 7, 5, 13, 9))
    assert msg is not None
    assert "could not be read" in msg
    assert "v0.36.0" in msg


def test_diagnose_rejects_non_cgc_card(tmp_path):
    """A valid MBR with no Linux partitions must fail with a clear message,
    not a traceback from deep inside the ext4 reader."""
    img = tmp_path / "random.img"
    sector0 = bytearray(512)
    # One FAT16 partition only.
    struct.pack_into("<BBBBBBBBII", sector0, 0x1BE, 0, 0, 0, 0, 0x0e,
                     0, 0, 0, 2048, 131072)
    sector0[510:512] = b"\x55\xaa"
    img.write_bytes(bytes(sector0) + b"\x00" * (1024 * 1024))
    with pytest.raises(ValueError, match="CGC installer card"):
        diagnose_installer_card(str(img))


def test_diagnose_rejects_non_mbr_file(tmp_path):
    img = tmp_path / "noise.img"
    img.write_bytes(b"\x00" * 4096)
    with pytest.raises(ValueError, match="MBR"):
        diagnose_installer_card(str(img))


def test_mbr_parser_skips_empty_entries():
    sector0 = bytearray(512)
    struct.pack_into("<BBBBBBBBII", sector0, 0x1BE + 16, 0, 0, 0, 0, 0x83,
                     0, 0, 0, 2048, 4096)
    sector0[510:512] = b"\x55\xaa"
    parts = _mbr_partitions(bytes(sector0))
    assert parts == [{"index": 2, "type": 0x83,
                      "start_bytes": 2048 * 512, "size_bytes": 4096 * 512}]


def test_only_cgc_exposes_diagnose_card():
    """The GUI gates the "Card diagnostics…" button on the manufacturer
    having a diagnose_card method; make sure CGC has it (with its help
    text) and that it isn't accidentally inherited by everyone."""
    from pinball_decryptor.core.registry import Manufacturer
    assert callable(getattr(CGCManufacturer, "diagnose_card", None))
    assert getattr(CGCManufacturer, "diagnose_card_help", "")
    assert getattr(Manufacturer, "diagnose_card", None) is None
