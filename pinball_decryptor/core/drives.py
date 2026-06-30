"""Cross-platform physical-drive enumeration for the Direct-SSD picker.

Returns a list of drives suitable for the GUI dropdown: each drive
carries an OS-native device path (which the Direct-SSD pipeline
accepts verbatim) plus a friendly display string the user can
recognise (model + size + bus type).

Per platform:
  * Windows  — PowerShell ``Get-Disk`` (FriendlyName, Size, BusType,
    Number) joined to ``\\\\.\\PHYSICALDRIVE<Number>``.
  * macOS    — ``diskutil list -plist`` + ``diskutil info``.
  * Linux    — ``lsblk -dbno NAME,MODEL,SIZE,TRAN`` (``-b`` for
    bytes; ``-d`` to skip partitions).

The display string mirrors the standalone JJP decryptor's drive
picker exactly so users transitioning across see the same format:
``JMicron Tech SCSI Disk Device (111.8 GB, External) — \\\\.\\PHYSICALDRIVE3``.
"""

import re
import subprocess
import sys
from dataclasses import dataclass

# CREATE_NO_WINDOW on Windows = 0x08000000.  Without this flag,
# subprocess.run on a console exe (powershell.exe, diskutil) flashes
# a black console window for the duration of the call — which the
# user sees as "the app freezes and a window flickers" the first
# time they tick "From SSD".  Defined as 0 on non-Windows so the
# subprocess kwargs always work.
_NO_WINDOW = (subprocess.CREATE_NO_WINDOW
              if sys.platform == "win32"
              else 0)


@dataclass(frozen=True)
class PhysicalDrive:
    """One physical disk discovered on the host."""

    device_path: str   # exact OS-native path the pipeline accepts
    model: str         # human-readable model (e.g. "Samsung SSD 970")
    size_bytes: int    # 0 if unknown
    bus_type: str = "" # "USB" / "SATA" / "NVMe" / "SD" / "" if unknown
    # Human-recognisable mount hint for the picker — Windows drive
    # letters ("E:" / "E: F:") for whatever partitions of this disk are
    # mounted.  Empty when none are lettered (e.g. an all-ext4 Spike card
    # whose data partitions Windows can't read) or on platforms where
    # letters don't apply.  Surfaced in display so users who think in
    # drive letters can still spot their card.
    mount_label: str = ""

    @property
    def location(self):
        """One-word location hint suitable for the display string.

        USB drives become "External"; everything else stays as the
        bus type (SATA, NVMe, etc.).  Empty bus type → "Internal" as
        a sane default.
        """
        bt = self.bus_type.upper()
        if not bt:
            return "Internal"
        if bt in ("USB",):
            return "External"
        return self.bus_type

    @property
    def display(self):
        """Single-line label shown in the drive-picker dropdown."""
        size = (f"{self.size_bytes / 1e9:.1f} GB"
                if self.size_bytes else "size ?")
        letters = f" [{self.mount_label}]" if self.mount_label else ""
        return (f"{self.model} ({size}, {self.location}){letters} "
                f"— {self.device_path}")


# ----------------------------------------------------------------------
# Parsers — module-level so they unit-test against canned tool output
# without spinning up a subprocess.
# ----------------------------------------------------------------------

def _parse_windows_get_disk(raw_output):
    """Parse ``num|model|size|bustype[|letters]`` lines into drives.

    PowerShell BusType values are integers wrapped in the
    Microsoft.Management.Infrastructure name table; calling .ToString()
    gives them as ``USB``, ``SATA``, ``NVMe``, etc.  The optional fifth
    field is a comma-joined list of mounted drive letters for the disk
    (e.g. ``E,F``) — older callers emit only four fields, so it's
    treated as optional.  Junk lines and blanks are skipped silently —
    a broken Get-Disk shouldn't take down the picker.
    """
    out = []
    if not raw_output:
        return out
    for line in raw_output.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        fields = line.split("|", 4)
        if len(fields) < 4:
            continue
        try:
            num = int(fields[0].strip())
            size = int(fields[2].strip())
        except ValueError:
            continue
        model = fields[1].strip() or "(unknown model)"
        bus = fields[3].strip()
        letters_raw = fields[4].strip() if len(fields) >= 5 else ""
        # "E,F" → "E: F:"; tolerate stray whitespace/empties.
        mount = " ".join(f"{c.strip()}:" for c in letters_raw.split(",")
                         if c.strip())
        out.append(PhysicalDrive(
            device_path=f"\\\\.\\PHYSICALDRIVE{num}",
            model=model, size_bytes=size, bus_type=bus,
            mount_label=mount))
    return out


def _parse_macos_diskutil_list(raw_output):
    """Parse ``diskutil list`` summary rows into drives.

    diskutil prints one block per whole disk; we want only the
    ``/dev/disk0 (external, physical):`` style header lines.  This
    parser pulls the disk number and the "external/internal,
    physical/virtual" hint; sizes come from a follow-up
    ``diskutil info`` so we can stay self-contained here.
    """
    out = []
    if not raw_output:
        return out
    # Header rows look like:
    #   /dev/disk2 (external, physical):
    #   /dev/disk0 (internal, physical):
    # Virtual disks (APFS containers, RAID, disk images) are ignored.
    for line in raw_output.splitlines():
        m = re.match(
            r'^/dev/disk(\d+)\s+\((internal|external),\s+physical\)',
            line.strip())
        if not m:
            continue
        num = m.group(1)
        kind = m.group(2)  # internal / external
        out.append(PhysicalDrive(
            device_path=f"/dev/disk{num}",
            model="(diskutil info needed)",  # filled by caller
            size_bytes=0,
            bus_type="USB" if kind == "external" else "SATA"))
    return out


def _parse_macos_diskutil_info(raw_output):
    """Pull ``Device / Media Name`` and ``Disk Size`` from diskutil info.

    Returns ``(model, size_bytes)``.  Either may be None if missing.
    """
    if not raw_output:
        return None, None
    model = None
    size = None
    for line in raw_output.splitlines():
        m = re.match(r'\s*Device / Media Name:\s+(.+?)\s*$', line)
        if m:
            model = m.group(1).strip()
            continue
        # "Disk Size: 128.0 GB (128034708480 Bytes) (exactly ...)"
        m = re.match(r'\s*Disk Size:.*?\((\d+)\s+Bytes\)', line)
        if m:
            try:
                size = int(m.group(1))
            except ValueError:
                pass
    return model, size


def _parse_linux_lsblk(raw_output):
    """Parse ``lsblk -dbno NAME,MODEL,SIZE,TRAN`` into drives.

    ``-d`` keeps only whole devices (no partitions), ``-b`` makes
    SIZE an int (bytes), ``-n`` skips the header, ``-o`` selects
    exactly the columns we need.
    """
    out = []
    if not raw_output:
        return out
    for line in raw_output.strip().splitlines():
        # lsblk separates by whitespace, but MODEL can contain spaces.
        # The fixed-position scheme: NAME (1 col) MODEL (variable, may
        # be empty) SIZE (numeric) TRAN.  Easiest: split on whitespace
        # and pull NAME + SIZE + TRAN from known positions; MODEL is
        # everything between.
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[0]
        # TRAN is always the last token, SIZE is the second-to-last
        # numeric token.  Walk back from the end to find SIZE.
        tran = ""
        size_idx = None
        for i in range(len(fields) - 1, 0, -1):
            tok = fields[i]
            if tok.isdigit():
                size_idx = i
                tran = (" ".join(fields[i + 1:])
                        if i + 1 < len(fields) else "")
                break
        if size_idx is None:
            continue
        try:
            size = int(fields[size_idx])
        except ValueError:
            continue
        model = " ".join(fields[1:size_idx]) or "(unknown model)"
        out.append(PhysicalDrive(
            device_path=f"/dev/{name}",
            model=model, size_bytes=size, bus_type=tran.upper()))
    return out


# ----------------------------------------------------------------------
# Per-platform enumerators
# ----------------------------------------------------------------------

def _list_physical_drives_windows():
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Disk | ForEach-Object { "
             "$n = $_.Number; $dl = ''; "
             "try { $dl = ((Get-Partition -DiskNumber $n "
             "-ErrorAction SilentlyContinue | "
             "Where-Object { $_.DriveLetter -match '[A-Za-z]' } | "
             "Select-Object -ExpandProperty DriveLetter) -join ',') } "
             "catch { }; "
             "'{0}|{1}|{2}|{3}|{4}' -f $n, $_.FriendlyName, "
             "$_.Size, $_.BusType, $dl }"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return _parse_windows_get_disk(result.stdout)


def _list_physical_drives_macos():
    try:
        result = subprocess.run(
            ["diskutil", "list"],
            capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    drives = _parse_macos_diskutil_list(result.stdout)
    # Backfill model + size via per-device diskutil info.  Slow-ish
    # (one subprocess per disk), but only a handful of disks on any
    # realistic system.
    out = []
    for d in drives:
        try:
            info = subprocess.run(
                ["diskutil", "info", d.device_path],
                capture_output=True, text=True, timeout=10,
                creationflags=_NO_WINDOW)
            model, size = _parse_macos_diskutil_info(info.stdout)
        except (OSError, subprocess.SubprocessError):
            model, size = None, None
        out.append(PhysicalDrive(
            device_path=d.device_path,
            model=model or d.model,
            size_bytes=size or 0,
            bus_type=d.bus_type))
    return out


def _list_physical_drives_linux():
    try:
        result = subprocess.run(
            ["lsblk", "-dbno", "NAME,MODEL,SIZE,TRAN"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return _parse_linux_lsblk(result.stdout)


def list_physical_drives():
    """Enumerate physical drives on the current platform.

    Returns a list of :class:`PhysicalDrive`, possibly empty.  Errors
    from the per-platform helpers are swallowed so a broken
    enumerator never crashes the GUI — at worst the dropdown shows
    "No drives found".
    """
    if sys.platform == "win32":
        return _list_physical_drives_windows()
    if sys.platform == "darwin":
        return _list_physical_drives_macos()
    return _list_physical_drives_linux()


# Above this size an external drive is almost certainly a backup
# SSD/HDD, not a game SD card — Spike 2 cards top out well under this.
# Used by the SD-card picker so a multi-TB Sabrent never gets auto-
# selected as the write target just because it's the biggest external.
_SD_CARD_MAX_BYTES = 128 * 1024 ** 3  # 128 GB

# Model-string hints that a drive is a memory-card reader.  ``CRW`` =
# "card reader/writer" (e.g. "Generic- USB3.0 CRW -SD"); the trailing
# "-SD" matches the bare ``sd`` token.  ``\bsd\b`` will NOT match inside
# "SSD" (no word boundary), so backup SSDs don't trip this.
_CARD_READER_RE = re.compile(
    r'\b(micro\s*sd|sdhc|sdxc|sdcard|sd|mmc|crw|card\s*reader|'
    r'card\s*writer|cardreader)\b',
    re.IGNORECASE)


def _looks_like_card_reader(d):
    """True if *d* is plausibly a memory-card reader / SD card."""
    if d.bus_type.upper() in ("SD", "MMC"):
        return True
    return bool(_CARD_READER_RE.search(d.model or ""))


def _pick_sd_card(drives, externals):
    """Auto-pick heuristic for plugins whose medium is a small SD card.

    Spike 2 (Stern) ships on an SD card — small removable media, often
    in a USB card reader sitting alongside large backup SSDs.  Picking
    the *largest* external (the JJP heuristic) is actively dangerous
    here: it'll default the write target to a 4 TB backup drive.  So:

      * exactly one card-reader-looking drive → high confidence
      * the smallest SD-card-sized external   → low confidence
      * nothing card-sized                     → low confidence, and a
        loud "connect the card and Refresh" so we never auto-trust a
        big drive as the write target.
    """
    readers = [d for d in externals if _looks_like_card_reader(d)]
    if len(readers) == 1:
        d = readers[0]
        return (d, "high",
                f"detected an SD-card reader — using {d.device_path}")
    if len(readers) > 1:
        best = min(readers, key=lambda d: d.size_bytes or 1 << 62)
        others = [d.device_path for d in readers if d is not best]
        return (best, "low",
                f"multiple card readers connected — picked the smallest "
                f"({best.device_path}); also seen: {', '.join(others)}")

    # No obvious reader.  An SD card is small, so prefer the smallest
    # external under the card-size ceiling — never the biggest.
    small = [d for d in externals
             if d.size_bytes and d.size_bytes <= _SD_CARD_MAX_BYTES]
    if small:
        best = min(small, key=lambda d: d.size_bytes)
        only_one = len(small) == 1 and len(externals) == 1
        if only_one:
            return (best, "high",
                    f"only one SD-card-sized drive is connected — "
                    f"using {best.device_path}")
        return (best, "low",
                f"picked the smallest external ({best.device_path}, "
                f"{best.size_bytes / 1e9:.1f} GB) as the likely SD card — "
                f"confirm it's the card before writing")

    # Every external is large (or sizeless): almost certainly NOT the
    # card.  Tentatively select the smallest, but be loud about it so
    # the user plugs the card in rather than writing to a backup drive.
    pool = externals or drives
    best = min(pool, key=lambda d: d.size_bytes or 1 << 62)
    return (best, "low",
            f"no SD-card-sized drive found — connect the SD card (or its "
            f"reader) and click Refresh. Tentatively selected the smallest "
            f"drive ({best.device_path}); verify before writing.")


def visible_drives(drives, prefer="ssd", keep=()):
    """Drives to show in the picker dropdown for a given medium.

    For small-SD-card media (Stern Spike 2) the user's multi-TB backup
    SSDs are never the write target, so hiding everything well above an
    SD card's size keeps the dropdown short and the right card easy to
    spot.  For large-SSD media (JJP) every drive stays — the game disk
    *is* a big removable SSD.

    *keep* is an iterable of drives that must remain visible regardless
    of size (typically the auto-picked best, so the selection always
    exists in the dropdown).  If filtering would hide every drive — e.g.
    only large disks are connected — the full list is returned so the
    user can still pick manually.
    """
    if prefer != "sd_card":
        return list(drives)
    keep_set = set(keep)
    small = [d for d in drives
             if d in keep_set
             or not d.size_bytes
             or d.size_bytes <= _SD_CARD_MAX_BYTES]
    return small or list(drives)


def pick_best_game_ssd(drives, prefer="ssd"):
    """Return the drive most likely to be the game medium, or None.

    Game media are removable — users pull the SSD/SD out of the machine
    and plug it into their PC.  The heuristic depends on *prefer*:

      * ``"ssd"`` (default, JJP) — a large removable SSD; prefer USB
        external and, among several, the largest.
      * ``"sd_card"`` (Stern Spike 2) — a small SD card in a reader;
        prefer a card reader / the smallest external, and never high-
        confidence-select a multi-TB drive.  See :func:`_pick_sd_card`.

    Returns ``(drive, confidence, reason)`` where ``confidence`` is
    "high" / "low" and ``reason`` is one short sentence suitable
    for the console log.  Returns ``(None, None, None)`` if no
    drives were found at all.
    """
    if not drives:
        return None, None, None

    # Card readers can present as bus type SD/MMC, not just USB.
    externals = [d for d in drives
                 if d.bus_type.upper() in ("USB", "SD", "MMC")]
    if prefer == "sd_card":
        return _pick_sd_card(drives, externals)

    if len(externals) == 1:
        d = externals[0]
        return (d, "high",
                f"only one external (USB) drive is connected — "
                f"using {d.device_path}")
    if len(externals) > 1:
        # Multiple externals — pick the largest, flag ambiguity.
        best = max(externals, key=lambda d: d.size_bytes)
        others = [d.device_path for d in externals if d is not best]
        return (best, "low",
                f"multiple external drives connected — picked the "
                f"largest ({best.device_path}); also seen: "
                f"{', '.join(others)}")

    # No externals — fall back to the largest internal so the user
    # at least has a sensible default to override.  Confidence is
    # explicitly low because this is almost certainly the system
    # disk and the user needs to confirm.
    best = max(drives, key=lambda d: d.size_bytes)
    return (best, "low",
            f"no external/USB drives connected — guessed at the "
            f"largest internal ({best.device_path}). Connect the "
            f"game SSD via USB and click Refresh.")
