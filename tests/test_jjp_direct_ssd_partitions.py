"""Unit tests for the JJP Direct-SSD partition discovery + pick logic.

These cover the path-of-least-evidence layer that Habo's bug report
exposed: how we enumerate partitions on the SSD, how we pick which
one to try, and how A/B layouts are detected.  The platform-specific
runners (``_discover_partitions_<platform>``) are thin wrappers
around ``executor.run_host``; we test the parsing + selection logic
directly with canned tool output so we don't need WSL/Docker/a real
drive in CI.

The bug we're guarding against:
  • Old Windows picker returned the *first* "Unknown" partition,
    which on Habo's drive was the OS-boot slot, not the game data.
  • macOS picker assumed "largest Linux" was always game data —
    fine on every drive we have data for, but the only verification
    was the file-not-found at the end.
  • Neither path looked at what was *on* the partition before
    committing to it.
"""

import pytest

from pinball_decryptor.plugins.jjp.pipeline import (
    DirectSSDDecryptPipeline,
    _PartitionInfo,
    _parse_linux_partitions,
    _parse_macos_partitions,
    _parse_windows_partitions,
)


# ----------------------------------------------------------------------
# Per-platform parser tests — canned tool output → _PartitionInfo list
# ----------------------------------------------------------------------

class TestParseWindowsPartitions:
    """Get-Partition output via PowerShell ForEach-Object."""

    def test_empty_input_returns_empty_list(self):
        assert _parse_windows_partitions("") == []
        assert _parse_windows_partitions(None) == []

    def test_skips_lines_without_pipe(self):
        # Stray status lines / blank lines shouldn't trip the parser.
        out = "\n\nsome warning\n1|System|536870912\n"
        parts = _parse_windows_partitions(out)
        assert len(parts) == 1
        assert parts[0].number == 1
        assert parts[0].raw_type == "System"
        assert parts[0].fs_kind == "efi"  # System → EFI System Partition

    def test_skips_lines_with_non_numeric_partition_or_size(self):
        out = (
            "abc|Unknown|12345\n"      # bad number
            "1|Unknown|notasize\n"     # bad size
            "2|Unknown|999\n"          # valid
        )
        parts = _parse_windows_partitions(out)
        assert [p.number for p in parts] == [2]

    def test_habo_style_drive_layout(self):
        # Habo's symptom: partition 2 (the auto-pick winner) was
        # mountable but didn't contain /jjpe/gen1.  Expected real
        # layout: EFI + small boot Linux + large game-data Linux.
        out = (
            "1|System|536870912\n"             # 512 MB EFI
            "2|Unknown|1073741824\n"           # 1 GB OS-boot Linux
            "3|Unknown|107374182400\n"         # 100 GB game data
        )
        parts = _parse_windows_partitions(out)
        assert len(parts) == 3
        # Boot Linux + game data should both be classified as "linux"
        # (Windows reports both as Unknown — no driver for ext4).
        linux = [p for p in parts if p.fs_kind == "linux"]
        assert {p.number for p in linux} == {2, 3}
        # The largest Linux is the game data, partition 3.
        biggest = max(linux, key=lambda p: p.size_bytes)
        assert biggest.number == 3

    def test_a_b_layout_two_matching_linux_partitions(self):
        # Drive with a A/B layout: two same-sized large Linux slots.
        out = (
            "1|System|536870912\n"             # EFI
            "2|Unknown|107374182400\n"         # 100 GB slot A
            "3|Unknown|107374182400\n"         # 100 GB slot B
        )
        parts = _parse_windows_partitions(out)
        linux = [p for p in parts if p.fs_kind == "linux"]
        assert len(linux) == 2
        assert linux[0].size_bytes == linux[1].size_bytes


class TestParseMacosPartitions:
    """diskutil list output."""

    def test_empty_input(self):
        assert _parse_macos_partitions("") == []
        assert _parse_macos_partitions(None) == []

    def test_linux_filesystem_label(self):
        out = (
            "/dev/disk2 (external, physical):\n"
            "   #:                       TYPE NAME                    SIZE       IDENTIFIER\n"
            "   0:      GUID_partition_scheme                        *128.0 GB   disk2\n"
            "   1:                        EFI EFI                     209.7 MB   disk2s1\n"
            "   2:           Linux Filesystem                         100.0 GB   disk2s2\n"
        )
        parts = _parse_macos_partitions(out)
        nums = [p.number for p in parts]
        # The "GUID_partition_scheme" line isn't a partition row
        # (it doesn't have a diskNsM suffix), so we skip it.
        assert 1 in nums and 2 in nums
        linux = [p for p in parts if p.fs_kind == "linux"]
        assert len(linux) == 1
        assert linux[0].number == 2
        assert linux[0].size_bytes == 100 * 1_000_000_000

    def test_bare_linux_label_is_recognised(self):
        # Some installers shorten "Linux Filesystem" to "Linux".
        out = "   2:                    Linux                  12.0 GB   disk2s2\n"
        parts = _parse_macos_partitions(out)
        assert len(parts) == 1
        assert parts[0].fs_kind == "linux"

    def test_efi_partition_recognised_separately(self):
        out = "   1:                        EFI EFI                     209.7 MB   disk2s1\n"
        parts = _parse_macos_partitions(out)
        assert len(parts) == 1
        assert parts[0].fs_kind == "efi"


class TestParseLinuxPartitions:
    """lsblk -brno NAME,FSTYPE,SIZE output."""

    def test_empty_input(self):
        assert _parse_linux_partitions("") == []
        assert _parse_linux_partitions(None) == []

    def test_basic_ext4_drive(self):
        # `lsblk -brno NAME,FSTYPE,SIZE /dev/sdb` — first row is the
        # whole device with no FSTYPE, partition rows follow.
        out = (
            "sdb         128000000000\n"
            "sdb1 vfat   536870912\n"
            "sdb2 ext4   1073741824\n"
            "sdb3 ext4   107374182400\n"
        )
        parts = _parse_linux_partitions(out)
        # Whole-device row has no trailing digit, so it's skipped.
        nums = [p.number for p in parts]
        assert nums == [1, 2, 3]
        assert parts[0].fs_kind == "fat"
        assert parts[1].fs_kind == "linux"
        assert parts[2].fs_kind == "linux"

    def test_swap_partition_recognised(self):
        out = "sdb2 swap   2147483648\n"
        parts = _parse_linux_partitions(out)
        assert parts[0].fs_kind == "swap"


# ----------------------------------------------------------------------
# Candidate-builder + A/B detection — exercised via a stub that
# borrows the real methods without needing the full pipeline ctor.
# ----------------------------------------------------------------------

class _CandidateStub:
    """Minimal stand-in carrying the state the real methods read.

    Borrowing the actual methods (instead of re-implementing them)
    keeps the test honest — any regression in the real code will show
    up here.
    """
    # Borrow the methods straight from the real class.
    _build_partition_candidates = (
        DirectSSDDecryptPipeline._build_partition_candidates)
    _update_ab_partitions_for = (
        DirectSSDDecryptPipeline._update_ab_partitions_for)
    _format_partition_map_for_error = (
        DirectSSDDecryptPipeline._format_partition_map_for_error)

    def __init__(self, parts, override=None):
        self._stub_parts = list(parts)
        self.partition_override = override
        self._partition_map = []
        self._ab_partitions = None

    # Stub: real _discover_partitions hits the executor; we just
    # hand back our pre-built list so the builder can sort it.
    def _discover_partitions(self, device):
        self._partition_map = self._stub_parts
        return self._stub_parts

    def log(self, *args, **kwargs):
        pass


class TestBuildPartitionCandidates:
    """Verify the candidate-ordering logic the Windows mount loop relies on."""

    def test_largest_linux_first(self):
        # Habo-shape drive: tiny EFI + small Linux boot + large Linux
        # game data.  The game data partition should be first.
        parts = [
            _PartitionInfo(1, "System", 536_870_912, "efi"),
            _PartitionInfo(2, "Unknown", 1_073_741_824, "linux"),
            _PartitionInfo(3, "Unknown", 107_374_182_400, "linux"),
        ]
        stub = _CandidateStub(parts)
        candidates = stub._build_partition_candidates("\\\\.\\PHYSICALDRIVE1")
        # Largest Linux (partition 3) wins; the smaller Linux comes
        # next as a fallback for the content-verify loop.
        assert candidates == [3, 2]

    def test_manual_override_skips_auto_discovery(self):
        parts = [
            _PartitionInfo(1, "Unknown", 1_000_000_000, "linux"),
            _PartitionInfo(2, "Unknown", 100_000_000_000, "linux"),
        ]
        stub = _CandidateStub(parts, override=2)
        # Even though partition 2 would also be picked by auto, the
        # override path is the "user knows better" escape hatch — it
        # MUST return exactly the override.
        assert stub._build_partition_candidates(
            "\\\\.\\PHYSICALDRIVE1") == [2]

    def test_override_can_force_a_partition_auto_would_skip(self):
        parts = [
            _PartitionInfo(1, "System", 200_000_000, "efi"),
            _PartitionInfo(2, "Unknown", 100_000_000_000, "linux"),
        ]
        stub = _CandidateStub(parts, override=99)
        # Partition 99 doesn't exist on the drive at all — but the
        # override is the user's escape hatch, so the builder hands
        # exactly 99 back.  The mount loop will fail loudly if 99
        # isn't real; that's the user's signal to pick a different
        # number.
        assert stub._build_partition_candidates(
            "\\\\.\\PHYSICALDRIVE1") == [99]

    def test_no_partitions_falls_back_to_default(self):
        # Totally mysterious drive — discovery returned nothing.
        # Pre-refactor behaviour was to try partition 3 (the config
        # default); preserve that so we don't silently change the
        # blast radius for a no-data case.
        from pinball_decryptor.plugins.jjp import config
        stub = _CandidateStub(parts=[])
        candidates = stub._build_partition_candidates(
            "\\\\.\\PHYSICALDRIVE1")
        assert candidates == [config.GAME_PARTITION_NUMBER]

    def test_efi_swap_msr_are_filtered_out(self):
        # Auto pick must NEVER try to mount an EFI / swap / MS
        # Reserved partition as ext4 — at best it's a wasted mount,
        # at worst it could confuse a Linux mount with no fstype.
        parts = [
            _PartitionInfo(1, "System", 200_000_000, "efi"),
            _PartitionInfo(2, "Microsoft Reserved", 16_000_000, "msr"),
            _PartitionInfo(3, "Unknown", 10_000_000_000, "linux"),
            _PartitionInfo(4, "swap", 2_000_000_000, "swap"),
        ]
        stub = _CandidateStub(parts)
        candidates = stub._build_partition_candidates(
            "\\\\.\\PHYSICALDRIVE1")
        # Only the Linux one is offered; EFI/swap/MSR are dropped.
        assert candidates == [3]


class TestUpdateAbPartitions:
    """A/B partner detection — same-sized peers of the winning slot."""

    def test_two_same_sized_linux_slots_detected(self):
        parts = [
            _PartitionInfo(1, "System", 500_000_000, "efi"),
            _PartitionInfo(2, "Unknown", 100_000_000_000, "linux"),
            _PartitionInfo(3, "Unknown", 100_000_000_000, "linux"),
        ]
        stub = _CandidateStub(parts)
        stub._partition_map = parts
        stub._update_ab_partitions_for(2)
        assert stub._ab_partitions == [2, 3]

    def test_winner_is_primary_partners_follow(self):
        # When we end up using partition 3 (not 2), the A/B list
        # should be primary-first: [3, 2].  This matters for the
        # Windows mirror loop, which iterates [1:] as partners.
        parts = [
            _PartitionInfo(2, "Unknown", 100_000_000_000, "linux"),
            _PartitionInfo(3, "Unknown", 100_000_000_000, "linux"),
        ]
        stub = _CandidateStub(parts)
        stub._partition_map = parts
        stub._update_ab_partitions_for(3)
        assert stub._ab_partitions == [3, 2]

    def test_different_sizes_no_a_b_layout(self):
        # 100 GB and 1 GB are not within 5% of each other —
        # definitely not an A/B mirror.
        parts = [
            _PartitionInfo(2, "Unknown", 100_000_000_000, "linux"),
            _PartitionInfo(3, "Unknown", 1_000_000_000, "linux"),
        ]
        stub = _CandidateStub(parts)
        stub._partition_map = parts
        stub._update_ab_partitions_for(2)
        assert stub._ab_partitions is None

    def test_tiny_winner_no_a_b_check(self):
        # Sanity guard: don't treat 100 MB partitions as A/B even
        # if there are matching peers — too small to be game data.
        parts = [
            _PartitionInfo(1, "Unknown", 100_000_000, "linux"),
            _PartitionInfo(2, "Unknown", 100_000_000, "linux"),
        ]
        stub = _CandidateStub(parts)
        stub._partition_map = parts
        stub._update_ab_partitions_for(1)
        assert stub._ab_partitions is None


class TestFormatPartitionMapForError:
    """The map block that lands in the error message — the user's only
    diagnostic when auto-discovery exhausts every candidate."""

    def test_empty_map(self):
        stub = _CandidateStub(parts=[])
        assert "no partition map" in stub._format_partition_map_for_error()

    def test_each_partition_shows_in_summary(self):
        parts = [
            _PartitionInfo(1, "System", 536_870_912, "efi"),
            _PartitionInfo(2, "Unknown", 107_374_182_400, "linux"),
        ]
        stub = _CandidateStub(parts)
        stub._partition_map = parts
        out = stub._format_partition_map_for_error()
        assert "partition 1" in out and "partition 2" in out
        assert "System" in out and "Unknown" in out
        assert "[efi]" in out and "[linux]" in out
