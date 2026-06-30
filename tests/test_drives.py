"""Unit tests for the physical-drive enumerator (Direct-SSD picker).

We can't depend on a real drive being plugged in at test time, so the
per-platform helpers are pure parsers over canned tool output.  These
tests cover those parsers; the subprocess-launching wrappers
(``_list_physical_drives_<platform>``) are thin enough that "they
swallow OSError and return []" is the only contract worth checking.
"""

from pinball_decryptor.core.drives import (
    PhysicalDrive,
    _parse_linux_lsblk,
    _parse_macos_diskutil_info,
    _parse_macos_diskutil_list,
    _parse_windows_get_disk,
    pick_best_game_ssd,
    visible_drives,
)


# ----------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------

class TestParseWindowsGetDisk:
    def test_empty_input(self):
        assert _parse_windows_get_disk("") == []
        assert _parse_windows_get_disk(None) == []

    def test_typical_dev_box_layout(self):
        # Mix of internal SATA + external USB drive — same format
        # Get-Disk emits via our ForEach-Object wrapper.
        out = (
            "0|Samsung SSD 970 EVO 1TB|1000204886016|NVMe\n"
            "1|ST4000DM005-2DP166|4000787030016|SATA\n"
            "2|JMicron Tech|120034123776|USB\n"
        )
        drives = _parse_windows_get_disk(out)
        assert len(drives) == 3
        # Device paths preserve the Number column verbatim.
        assert drives[0].device_path == r"\\.\PHYSICALDRIVE0"
        assert drives[2].device_path == r"\\.\PHYSICALDRIVE2"
        # USB drives surface as "External" in the display string.
        assert drives[2].location == "External"
        # The display string mirrors the standalone JJP decryptor's
        # format: "Model (Size, Location) — DevicePath".
        assert "—" in drives[2].display
        assert "External" in drives[2].display
        assert r"\\.\PHYSICALDRIVE2" in drives[2].display

    def test_missing_model_defaults(self):
        out = "0||500000000000|SATA\n"
        drives = _parse_windows_get_disk(out)
        assert len(drives) == 1
        assert drives[0].model == "(unknown model)"

    def test_garbage_lines_skipped(self):
        out = (
            "random progress noise\n"
            "0|Samsung SSD|1000000000000|NVMe\n"
            "abc|wrong|wrong|wrong\n"
            "1|Other Disk|500000000000|SATA\n"
        )
        drives = _parse_windows_get_disk(out)
        assert [d.device_path for d in drives] == [
            r"\\.\PHYSICALDRIVE0",
            r"\\.\PHYSICALDRIVE1",
        ]

    def test_drive_letters_optional_fifth_field(self):
        # New 5-field form carries comma-joined mounted drive letters;
        # the parser turns them into an "E: F:" mount label and the
        # 4-field form (older command) stays letterless.
        out = (
            "0|Samsung SSD|1000000000000|NVMe|C\n"
            "3|Generic- USB3.0 CRW -SD|7700000000|USB|E,F\n"
            "4|No Letters Disk|500000000000|SATA\n"
        )
        drives = _parse_windows_get_disk(out)
        assert drives[0].mount_label == "C:"
        assert drives[1].mount_label == "E: F:"
        assert drives[2].mount_label == ""
        # The mount label surfaces in the dropdown display.
        assert "[E: F:]" in drives[1].display


# ----------------------------------------------------------------------
# macOS
# ----------------------------------------------------------------------

class TestParseMacosDiskutilList:
    def test_empty_input(self):
        assert _parse_macos_diskutil_list("") == []
        assert _parse_macos_diskutil_list(None) == []

    def test_picks_internal_and_external_physical_disks(self):
        out = (
            "/dev/disk0 (internal, physical):\n"
            "   #:                       TYPE NAME ...\n"
            "/dev/disk2 (external, physical):\n"
            "   #:                       TYPE NAME ...\n"
            "/dev/disk3 (synthesized):\n"        # APFS container — skip
            "/dev/disk4 (disk image):\n"          # image — skip
        )
        drives = _parse_macos_diskutil_list(out)
        paths = [d.device_path for d in drives]
        assert "/dev/disk0" in paths
        assert "/dev/disk2" in paths
        assert "/dev/disk3" not in paths
        assert "/dev/disk4" not in paths
        external = next(d for d in drives if d.device_path == "/dev/disk2")
        assert external.bus_type == "USB"  # external → USB hint
        internal = next(d for d in drives if d.device_path == "/dev/disk0")
        assert internal.bus_type == "SATA"  # internal → SATA default


class TestParseMacosDiskutilInfo:
    def test_pulls_model_and_size(self):
        out = (
            "   Device Identifier:        disk2\n"
            "   Device Node:              /dev/disk2\n"
            "   Whose:                    /\n"
            "   Device / Media Name:      JMicron Tech SCSI Disk Device\n"
            "   Volume Name:              Not applicable (no file system)\n"
            "   Disk Size:                120.0 GB "
            "(120034123776 Bytes) (exactly 234441648 512-Byte-Units)\n"
        )
        model, size = _parse_macos_diskutil_info(out)
        assert model == "JMicron Tech SCSI Disk Device"
        assert size == 120034123776

    def test_empty(self):
        assert _parse_macos_diskutil_info("") == (None, None)


# ----------------------------------------------------------------------
# Linux
# ----------------------------------------------------------------------

class TestParseLinuxLsblk:
    def test_empty(self):
        assert _parse_linux_lsblk("") == []
        assert _parse_linux_lsblk(None) == []

    def test_basic(self):
        # `lsblk -dbno NAME,MODEL,SIZE,TRAN` on a typical box.
        out = (
            "nvme0n1 Samsung_SSD_970 500000000000 nvme\n"
            "sda Seagate_Backup 4000000000000 sata\n"
            "sdb JMicron_Tech 120000000000 usb\n"
        )
        drives = _parse_linux_lsblk(out)
        assert len(drives) == 3
        # Device path is /dev/<name>.
        assert drives[0].device_path == "/dev/nvme0n1"
        assert drives[2].device_path == "/dev/sdb"
        # USB → "External" via the bus-type label normaliser.
        assert drives[2].bus_type == "USB"
        assert drives[2].location == "External"

    def test_model_with_spaces(self):
        # Real-world model strings include spaces; the parser must
        # walk back from TRAN/SIZE so MODEL can be arbitrary words.
        out = "sda Western Digital WD40EFRX 4000000000000 sata\n"
        drives = _parse_linux_lsblk(out)
        assert len(drives) == 1
        assert drives[0].model == "Western Digital WD40EFRX"
        assert drives[0].size_bytes == 4_000_000_000_000


# ----------------------------------------------------------------------
# Display formatting — what the user sees in the dropdown
# ----------------------------------------------------------------------

class TestPhysicalDriveDisplay:
    def test_matches_standalone_jjp_decryptor_format(self):
        # The JJP standalone decryptor showed:
        #   "JMicron Tech SCSI Disk Device (111.8 GB, External) — \\.\PHYSICALDRIVE3"
        # New users coming from that app should see the same shape.
        d = PhysicalDrive(
            device_path=r"\\.\PHYSICALDRIVE3",
            model="JMicron Tech SCSI Disk Device",
            size_bytes=120034123776,
            bus_type="USB")
        # Size in GB to 1 decimal; bus mapped to External.
        assert d.display == (
            "JMicron Tech SCSI Disk Device (120.0 GB, External) "
            "— \\\\.\\PHYSICALDRIVE3")

    def test_unknown_bus_defaults_to_internal(self):
        d = PhysicalDrive(
            device_path=r"\\.\PHYSICALDRIVE0",
            model="Some Drive", size_bytes=500000000000,
            bus_type="")
        assert d.location == "Internal"
        assert "Internal" in d.display

    def test_mount_label_shown_when_present(self):
        d = PhysicalDrive(
            device_path=r"\\.\PHYSICALDRIVE3",
            model="Generic- USB3.0 CRW -SD", size_bytes=7_700_000_000,
            bus_type="USB", mount_label="E:")
        assert "[E:]" in d.display
        # Letterless drives don't get an empty bracket.
        bare = PhysicalDrive(
            device_path=r"\\.\PHYSICALDRIVE3", model="x",
            size_bytes=1, bus_type="USB")
        assert "[" not in bare.display


# ----------------------------------------------------------------------
# Auto-pick logic — choose the most-likely-JJP drive without prompting
# ----------------------------------------------------------------------

class TestPickBestGameSsd:
    """JJP game SSDs are removable, so the auto-pick prefers USB.

    The user pulls the SSD out of the machine, plugs it into their
    PC over USB.  Internal SATA / NVMe is almost certainly the
    system disk — picking it would be hostile.  So:

      * exactly one external → high confidence, that's our pick
      * multiple externals   → low confidence, pick the largest
      * no externals         → low confidence, pick the largest
                               internal so the user has *something*
                               selected to override
    """

    def test_no_drives_returns_none(self):
        best, conf, reason = pick_best_game_ssd([])
        assert best is None
        assert conf is None
        assert reason is None

    def test_single_external_high_confidence(self):
        # Habo's situation: one external USB drive plugged in.
        # The auto-pick should be confident.
        drives = [
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE0",
                model="Internal NVMe", size_bytes=1_000_000_000_000,
                bus_type="NVMe"),
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE3",
                model="JMicron Tech",
                size_bytes=120_000_000_000, bus_type="USB"),
        ]
        best, conf, reason = pick_best_game_ssd(drives)
        assert best.device_path == r"\\.\PHYSICALDRIVE3"
        assert conf == "high"
        assert "USB" in reason or "external" in reason

    def test_multiple_externals_picks_largest_low_confidence(self):
        # Two USB drives plugged in — could be the SSD or could be
        # someone's backup drive.  Pick the larger one but flag low
        # confidence so the GUI suggests manual override.
        drives = [
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE2",
                model="USB Thumb", size_bytes=16_000_000_000,
                bus_type="USB"),
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE3",
                model="JMicron Tech",
                size_bytes=120_000_000_000, bus_type="USB"),
        ]
        best, conf, reason = pick_best_game_ssd(drives)
        # 120 GB > 16 GB → JMicron wins.
        assert best.device_path == r"\\.\PHYSICALDRIVE3"
        assert conf == "low"
        # Reason mentions the also-seen drive so the user can spot
        # the ambiguity in the log.
        assert r"\\.\PHYSICALDRIVE2" in reason

    def test_no_externals_low_confidence_warns_to_connect(self):
        # No USB drive plugged in — pick the largest internal as a
        # placeholder but tell the user to connect the SSD.
        drives = [
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE0",
                model="System NVMe", size_bytes=1_000_000_000_000,
                bus_type="NVMe"),
            PhysicalDrive(
                device_path=r"\\.\PHYSICALDRIVE1",
                model="Data SATA", size_bytes=4_000_000_000_000,
                bus_type="SATA"),
        ]
        best, conf, reason = pick_best_game_ssd(drives)
        # Largest internal — 4 TB > 1 TB → SATA wins.
        assert best.device_path == r"\\.\PHYSICALDRIVE1"
        assert conf == "low"
        # Reason nudges the user to plug in the SSD.
        assert "USB" in reason or "Connect" in reason


class TestPickBestSdCard:
    """Stern Spike ships on a small SD card, so prefer="sd_card" must
    never default to a big backup drive just because it's the largest
    external — the bug monkeybug hit (a 4 TB Sabrent auto-selected as
    the write target over the 7.7 GB card reader).
    """

    def _sabrent(self, num, size):
        return PhysicalDrive(
            device_path=rf"\\.\PHYSICALDRIVE{num}",
            model="Sabrent Dual SATA Bridge", size_bytes=size,
            bus_type="USB")

    def _card_reader(self, num, size=7_700_000_000):
        return PhysicalDrive(
            device_path=rf"\\.\PHYSICALDRIVE{num}",
            model="Generic- USB3.0 CRW -SD", size_bytes=size,
            bus_type="USB")

    def test_monkeybug_scenario_prefers_card_reader_over_4tb(self):
        # Exactly the reported layout: several multi-TB Sabrents plus
        # the SD card in a USB reader.  The reader must win, not the
        # biggest drive.
        drives = [
            self._sabrent(1, 4_000_800_000_000),
            self._sabrent(2, 4_000_800_000_000),
            self._card_reader(3),
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE4",
                          model="SABRENT", size_bytes=3_000_600_000_000,
                          bus_type="USB"),
        ]
        best, conf, reason = pick_best_game_ssd(drives, prefer="sd_card")
        assert best.device_path == r"\\.\PHYSICALDRIVE3"
        assert conf == "high"
        assert "reader" in reason.lower()

    def test_sd_bus_type_counts_as_card(self):
        drives = [
            self._sabrent(1, 4_000_000_000_000),
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE2",
                          model="Built-in card slot", size_bytes=32_000_000_000,
                          bus_type="SD"),
        ]
        best, conf, _ = pick_best_game_ssd(drives, prefer="sd_card")
        assert best.device_path == r"\\.\PHYSICALDRIVE2"
        assert conf == "high"

    def test_no_reader_picks_smallest_external_not_largest(self):
        # No card-reader hint in any model string — fall back to the
        # smallest SD-card-sized external, low confidence.
        drives = [
            self._sabrent(1, 4_000_000_000_000),
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE2",
                          model="Kingston DataTraveler",
                          size_bytes=16_000_000_000, bus_type="USB"),
        ]
        best, conf, reason = pick_best_game_ssd(drives, prefer="sd_card")
        assert best.device_path == r"\\.\PHYSICALDRIVE2"
        assert conf == "low"
        assert "confirm" in reason.lower()

    def test_all_externals_large_warns_to_connect_card(self):
        # Every external is way over the SD-card ceiling — don't trust
        # any of them; pick the smallest but tell the user to connect.
        drives = [
            self._sabrent(1, 4_000_000_000_000),
            self._sabrent(2, 2_000_000_000_000),
        ]
        best, conf, reason = pick_best_game_ssd(drives, prefer="sd_card")
        assert best.device_path == r"\\.\PHYSICALDRIVE2"  # smallest
        assert conf == "low"
        assert "connect" in reason.lower()

    def test_single_sd_sized_external_high_confidence(self):
        drives = [
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE0",
                          model="System NVMe", size_bytes=1_000_000_000_000,
                          bus_type="NVMe"),
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE2",
                          model="Lexar USB", size_bytes=32_000_000_000,
                          bus_type="USB"),
        ]
        best, conf, _ = pick_best_game_ssd(drives, prefer="sd_card")
        assert best.device_path == r"\\.\PHYSICALDRIVE2"
        assert conf == "high"

    def test_ssd_default_unchanged_by_new_param(self):
        # The default prefer="ssd" must keep the old largest-external
        # behaviour for JJP.
        drives = [
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE2",
                          model="USB Thumb", size_bytes=16_000_000_000,
                          bus_type="USB"),
            PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE3",
                          model="JMicron Tech", size_bytes=120_000_000_000,
                          bus_type="USB"),
        ]
        best, conf, _ = pick_best_game_ssd(drives)  # default prefer
        assert best.device_path == r"\\.\PHYSICALDRIVE3"  # largest
        assert conf == "low"


class TestVisibleDrives:
    """The dropdown hides obvious backup disks for SD-card media so the
    user isn't scrolling past multi-TB Sabrents to find the card
    (monkeybug: "large sized drives still being listed").
    """

    def _usb(self, num, size, model="Some USB"):
        return PhysicalDrive(device_path=rf"\\.\PHYSICALDRIVE{num}",
                             model=model, size_bytes=size, bus_type="USB")

    def test_ssd_mode_shows_everything(self):
        # JJP's game medium IS a big removable SSD — never filter it out.
        drives = [self._usb(1, 4_000_000_000_000), self._usb(2, 120_000_000_000)]
        assert visible_drives(drives, prefer="ssd") == drives

    def test_sd_card_mode_hides_oversize(self):
        card = self._usb(3, 32_000_000_000, "Lexar USB")
        big = self._usb(1, 4_000_000_000_000, "Sabrent")
        shown = visible_drives([big, card], prefer="sd_card")
        assert card in shown
        assert big not in shown

    def test_sd_card_keeps_sizeless(self):
        # size 0 = unknown; never hide it (could be the card).
        unknown = self._usb(4, 0)
        big = self._usb(1, 4_000_000_000_000)
        shown = visible_drives([big, unknown], prefer="sd_card")
        assert unknown in shown
        assert big not in shown

    def test_sd_card_all_large_falls_back_to_full_list(self):
        # If everything is oversize, show all rather than an empty list so
        # the user can still pick manually.
        drives = [self._usb(1, 4_000_000_000_000), self._usb(2, 2_000_000_000_000)]
        assert visible_drives(drives, prefer="sd_card") == drives

    def test_sd_card_keep_overrides_size(self):
        # The auto-picked drive stays visible even if oversize, so the
        # selection always exists in the dropdown.
        big = self._usb(1, 4_000_000_000_000)
        card = self._usb(3, 32_000_000_000)
        shown = visible_drives([big, card], prefer="sd_card", keep=(big,))
        assert big in shown
        assert card in shown

    def test_boundary_at_ceiling_inclusive(self):
        # Exactly 128 GB is allowed (<=); just over is hidden.
        at = self._usb(1, 128 * 1024 ** 3)
        over = self._usb(2, 128 * 1024 ** 3 + 1)
        shown = visible_drives([at, over], prefer="sd_card")
        assert at in shown
        assert over not in shown
