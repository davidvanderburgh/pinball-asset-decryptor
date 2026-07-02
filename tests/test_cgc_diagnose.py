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


def test_assess_payload_flags_empty_carried_from_source():
    """RTS's Pulp Fiction card: a 0-byte /emmc.img dated 2023 (older than the
    build) is the SHELL ERROR, and the verdict must say it came IN with the
    source .img."""
    import datetime as dt
    from pinball_decryptor.plugins.cgc.diagnose import _assess_payload_size

    now = dt.datetime(2026, 7, 2, 21, 0, tzinfo=dt.timezone.utc)
    old = dt.datetime(2023, 6, 28, tzinfo=dt.timezone.utc)
    msg = _assess_payload_size(0, old, now)
    assert msg is not None
    assert "0 bytes" in msg
    assert "SHELL ERROR" in msg
    assert "source .img" in msg and "ORIGINAL image" in msg


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
