"""Prepare a JJP USB install stick — format FAT32/MBR + copy the ISO's files.

A JJP machine never boots the install stick.  At power-on the game's own boot
sequence mounts the stick's FAT volume and runs the installer it finds there,
so a raw-imaged (Etcher/dd) stick is unreadable to it — the machine shows
"Failed to mount USB stick" and boots the old game (Alex's Sonic report,
2026-07-29).  JJP's own procedure is Rufus in ISO Image mode on Windows, or
"format MS-DOS(FAT) + copy the ISO's files" on macOS.  This pipeline is that
procedure in-app:

  1. Check    — sanity: real device (or test dir), ISO present, rough fit.
  2. Format   — one FAT32 primary partition in an MBR table, label JJPUSB
                (the label JJP's own Mac instructions use).
  3. Copy     — mount the ISO read-only and copy every file onto the stick.
  4. Verify   — re-walk the stick: every source file present, same size.
  5. Eject    — flush + OS-eject so it's safe to pull immediately.

Per-OS mechanics:
  * Windows — PowerShell storage cmdlets (Clear-Disk/New-Partition/
    Format-Volume) for the format; ``Mount-DiskImage`` for the ISO.  Windows
    refuses to *create* FAT32 volumes above 32 GiB, so the partition is
    capped there (plenty: the stick only ever holds this one installer) and
    an ISO whose contents won't fit is refused with a pointer at Rufus'
    large-FAT32 mode.  Formatting needs Administrator; the shipped build
    already runs elevated (launcher.vbs), and an unelevated source run gets
    a one-shot UAC prompt (``Start-Process -Verb RunAs``).
  * macOS   — ``diskutil eraseDisk MS-DOS JJPUSB MBR`` (no root needed for
    external media) and ``hdiutil attach`` for the ISO.
  * Linux   — ``pkexec`` runs parted + mkfs.vfat (root needed for block
    devices); ``udisksctl`` provides the unprivileged loop-mount of the ISO
    and the stick mount/power-off.

Testability: a *directory* ``device_path`` is treated as an already-mounted
stick (Format and Eject become no-ops) and a *directory* ``iso_path`` as
already-mounted ISO contents — the whole Check/Copy/Verify core then runs on
plain folders with no privileges, devices or images involved.
"""

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from ...core.admin import is_admin
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.rawdevice import is_device_path

# FAT volume label — matches the name JJP's own Mac instructions pick.
STICK_LABEL = "JJPUSB"

# Windows cannot CREATE FAT32 volumes above 32 GiB (reading them is fine).
_WIN_FAT32_MAX = 32 * 1024 ** 3
# Leave headroom for FAT tables / cluster slack when checking the cap.
_WIN_FAT32_USABLE = int(_WIN_FAT32_MAX * 0.98)

_COPY_CHUNK = 4 * 1024 * 1024

PHASES = ("Check stick", "Format stick", "Copy installer files",
           "Verify", "Eject")


def _creationflags():
    # Hide transient console windows for subprocess calls on Windows.
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run_cmd(args, timeout=120):
    """Run *args*, return (returncode, combined output)."""
    proc = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", timeout=timeout,
        creationflags=_creationflags())
    return proc.returncode, (proc.stdout or "").strip()


def _ps(script, timeout=180):
    """Run a PowerShell script in-process (no elevation)."""
    return _run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout)


def _ps_elevated(script, timeout=300):
    """Run a PowerShell script through a one-shot UAC prompt.

    The elevated child appends its output to a temp file (stdout of an
    elevated process is invisible to us); we poll for the file.  Returns
    (returncode, output) like :func:`_ps` — returncode 1 with the last
    output when the child never produced a result (declined UAC, crash).
    """
    ipc = tempfile.mkdtemp(prefix="pad_jjp_usb_")
    result_path = os.path.join(ipc, "result.txt")
    script_path = os.path.join(ipc, "job.ps1")
    # The elevated child's stdout is invisible to us, so the wrapper pipes
    # the script's own output lines into the result file alongside the
    # RC=0/RC=1 marker the parent looks for.
    wrapped = (
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        "  & {\n" + script + "\n"
        "  } | Out-File -Append -Encoding utf8 '" + result_path + "'\n"
        "  'RC=0' | Out-File -Append -Encoding utf8 '" + result_path + "'\n"
        "} catch {\n"
        "  $_ | Out-String | "
        "Out-File -Append -Encoding utf8 '" + result_path + "'\n"
        "  'RC=1' | Out-File -Append -Encoding utf8 '" + result_path + "'\n"
        "}\n")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(wrapped)
    try:
        rc, out = _ps(
            "Start-Process -FilePath powershell -Verb RunAs -Wait "
            "-WindowStyle Hidden -ArgumentList "
            "'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',"
            "'-File','%s'" % script_path, timeout=timeout)
        if rc != 0:
            return 1, out or "Administrator access was not granted."
        deadline = time.time() + 10
        while not os.path.isfile(result_path) and time.time() < deadline:
            time.sleep(0.2)
        if not os.path.isfile(result_path):
            return 1, "The elevated helper produced no result."
        with open(result_path, "r", encoding="utf-8-sig",
                  errors="replace") as f:
            body = f.read()
        rc = 0 if re.search(r"^RC=0\s*$", body, re.M) else 1
        body = re.sub(r"^RC=[01]\s*$", "", body, flags=re.M).strip()
        return rc, body
    finally:
        shutil.rmtree(ipc, ignore_errors=True)


def _ps_admin(script, timeout=300, log=None):
    """Run a PowerShell script with admin rights — in-process when the app
    is already elevated (the shipped build), else via one UAC prompt."""
    if is_admin():
        return _ps(script, timeout=timeout)
    if log is not None:
        log("Formatting the stick needs administrator access — approve the "
            "prompt to continue (the app itself keeps running normally).",
            "info")
    return _ps_elevated(script, timeout=timeout)


def _disk_number(device_path):
    m = re.search(r"PHYSICALDRIVE(\d+)$", device_path or "", re.IGNORECASE)
    if not m:
        raise PipelineError(
            PHASES[0],
            "Expected a Windows physical drive path like "
            r"\\.\PHYSICALDRIVE3, got %r." % device_path)
    return int(m.group(1))


def _linux_partition_node(device):
    # /dev/sdb -> /dev/sdb1; /dev/nvme0n1 or /dev/mmcblk0 -> ...p1
    return device + ("p1" if device[-1].isdigit() else "1")


def _iter_files(root):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            yield os.path.join(dirpath, name)


def _tree_size(root):
    total = 0
    for path in _iter_files(root):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


# ---------------------------------------------------------------------------
# Per-OS: format the stick, mount the ISO, eject.  Each returns/consumes
# plain paths so the pipeline core stays OS-agnostic and unit-testable.
# ---------------------------------------------------------------------------

def format_stick_windows(device_path, log):
    """Clean + MBR + one FAT32 partition; returns the mount root ('E:\\\\')."""
    n = _disk_number(device_path)
    script = (
        "$disk = Get-Disk -Number %(n)d\n"
        "if ($disk.IsBoot -or $disk.IsSystem) "
        "{ throw 'Refusing to format the boot/system disk.' }\n"
        "Clear-Disk -Number %(n)d -RemoveData -RemoveOEM -Confirm:$false\n"
        "Initialize-Disk -Number %(n)d -PartitionStyle MBR "
        "-ErrorAction SilentlyContinue\n"
        "$size = (Get-Disk -Number %(n)d).Size\n"
        "if ($size -gt %(cap)d) {\n"
        "  $part = New-Partition -DiskNumber %(n)d -Size %(cap)d "
        "-AssignDriveLetter\n"
        "} else {\n"
        "  $part = New-Partition -DiskNumber %(n)d -UseMaximumSize "
        "-AssignDriveLetter\n"
        "}\n"
        "$null = Format-Volume -Partition $part -FileSystem FAT32 "
        "-NewFileSystemLabel %(label)s -Confirm:$false\n"
        "$part = Get-Partition -DiskNumber %(n)d "
        "-PartitionNumber $part.PartitionNumber\n"
        "'LETTER=' + $part.DriveLetter\n"
        % {"n": n, "cap": _WIN_FAT32_MAX, "label": STICK_LABEL})
    rc, out = _ps_admin(script, timeout=300, log=log)
    m = re.search(r"^LETTER=([A-Za-z])\s*$", out, re.M)
    if rc != 0 or not m:
        raise PipelineError(
            PHASES[1],
            "Formatting the USB stick failed:\n%s" % (out or "(no output)"))
    root = "%s:\\" % m.group(1).upper()
    deadline = time.time() + 15
    while not os.path.isdir(root) and time.time() < deadline:
        time.sleep(0.3)
    if not os.path.isdir(root):
        raise PipelineError(
            PHASES[1],
            "The stick was formatted but its drive letter (%s) never "
            "appeared." % root)
    return root


def format_stick_macos(device_path, log):
    rc, out = _run_cmd(
        ["diskutil", "eraseDisk", "MS-DOS", STICK_LABEL, "MBR", device_path],
        timeout=300)
    if rc != 0:
        raise PipelineError(
            PHASES[1], "diskutil eraseDisk failed:\n%s" % out)
    part = device_path + "s1"
    deadline = time.time() + 20
    while time.time() < deadline:
        rc, info = _run_cmd(["diskutil", "info", "-plist", part], timeout=30)
        if rc == 0:
            try:
                mount = plistlib.loads(info.encode()).get("MountPoint")
            except Exception:
                mount = None
            if mount:
                return mount
        time.sleep(0.5)
    raise PipelineError(
        PHASES[1],
        "The stick was formatted but its volume never mounted (%s)." % part)


def format_stick_linux(device_path, log):
    part = _linux_partition_node(device_path)
    if shutil.which("pkexec") is None:
        raise PipelineError(
            PHASES[1],
            "Formatting a USB stick needs root. Install pkexec (polkit) or "
            "re-run the app as root.")
    shell = (
        "set -e; "
        "wipefs -a %(dev)s; "
        "parted -s %(dev)s mklabel msdos mkpart primary fat32 1MiB 100%%; "
        "udevadm settle || true; "
        "mkfs.vfat -F 32 -n %(label)s %(part)s"
        % {"dev": device_path, "part": part, "label": STICK_LABEL})
    rc, out = _run_cmd(["pkexec", "bash", "-c", shell], timeout=300)
    if rc != 0:
        raise PipelineError(
            PHASES[1], "Formatting the USB stick failed:\n%s" % out)
    rc, out = _run_cmd(["udisksctl", "mount", "-b", part], timeout=60)
    if rc != 0:
        raise PipelineError(
            PHASES[1], "Mounting the fresh FAT volume failed:\n%s" % out)
    m = re.search(r" at (.+?)\.?$", out.strip())
    if not m:
        raise PipelineError(
            PHASES[1], "Could not parse the mount point from:\n%s" % out)
    return m.group(1)


def mount_iso_windows(iso_path, log):
    """Mount the ISO read-only; returns (source_root, unmount_callable)."""
    script = (
        "$null = Mount-DiskImage -ImagePath '%(iso)s' -Access ReadOnly\n"
        "$vol = Get-DiskImage -ImagePath '%(iso)s' | Get-Volume\n"
        "'LETTER=' + $vol.DriveLetter\n" % {"iso": iso_path})
    rc, out = _ps(script, timeout=120)
    m = re.search(r"^LETTER=([A-Za-z])\s*$", out, re.M)
    if rc != 0 or not m:
        raise PipelineError(
            PHASES[2],
            "Windows could not mount the ISO to read its files:\n%s"
            % (out or "(no output)"))
    root = "%s:\\" % m.group(1).upper()

    def _unmount():
        _ps("Dismount-DiskImage -ImagePath '%s'" % iso_path, timeout=60)

    return root, _unmount


def mount_iso_macos(iso_path, log):
    rc, out = _run_cmd(
        ["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", iso_path],
        timeout=120)
    if rc != 0:
        raise PipelineError(PHASES[2], "hdiutil attach failed:\n%s" % out)
    mount = None
    try:
        for ent in plistlib.loads(out.encode()).get("system-entities", []):
            if ent.get("mount-point"):
                mount = ent["mount-point"]
                break
    except Exception:
        pass
    if not mount:
        raise PipelineError(
            PHASES[2], "hdiutil attach returned no mount point:\n%s" % out)

    def _unmount():
        _run_cmd(["hdiutil", "detach", mount, "-force"], timeout=60)

    return mount, _unmount


def mount_iso_linux(iso_path, log):
    rc, out = _run_cmd(
        ["udisksctl", "loop-setup", "-r", "-f", iso_path], timeout=60)
    m = re.search(r"as (/dev/loop\d+)\.?$", out.strip())
    if rc != 0 or not m:
        raise PipelineError(
            PHASES[2], "udisksctl loop-setup failed:\n%s" % out)
    loop = m.group(1)
    rc, out = _run_cmd(["udisksctl", "mount", "-b", loop], timeout=60)
    mp = re.search(r" at (.+?)\.?$", out.strip())
    if rc != 0 or not mp:
        _run_cmd(["udisksctl", "loop-delete", "-b", loop], timeout=30)
        raise PipelineError(
            PHASES[2], "Mounting the ISO loop device failed:\n%s" % out)
    mount = mp.group(1)

    def _unmount():
        _run_cmd(["udisksctl", "unmount", "-b", loop], timeout=60)
        _run_cmd(["udisksctl", "loop-delete", "-b", loop], timeout=30)

    return mount, _unmount


def eject_stick_windows(mount_root, device_path, log):
    letter = mount_root.rstrip(":\\/")
    _ps("Write-VolumeCache -DriveLetter %s" % letter, timeout=120)
    rc, out = _ps(
        "(New-Object -ComObject Shell.Application).Namespace(17)"
        ".ParseName('%s:').InvokeVerb('Eject')" % letter, timeout=60)
    if rc != 0:
        log("Could not auto-eject the stick (%s) — use 'Safely Remove "
            "Hardware' before pulling it." % (out or "unknown error"),
            "info")


def eject_stick_macos(mount_root, device_path, log):
    rc, out = _run_cmd(["diskutil", "eject", device_path], timeout=120)
    if rc != 0:
        log("Could not auto-eject the stick (%s) — eject it in Finder "
            "before pulling it." % out, "info")


def eject_stick_linux(mount_root, device_path, log):
    part = _linux_partition_node(device_path)
    _run_cmd(["udisksctl", "unmount", "-b", part], timeout=120)
    rc, out = _run_cmd(
        ["udisksctl", "power-off", "-b", device_path], timeout=60)
    if rc != 0:
        log("Could not power the stick off (%s) — unmount it before "
            "pulling it." % out, "info")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class UsbStickPreparePipeline(BasePipeline):
    """Format a USB stick FAT32/MBR and copy a JJP install ISO's files on.

    Constructed by ``JJPManufacturer.make_flash_pipeline`` with the dialog's
    (image, device) pair — the same call shape as the dd-style flash
    pipelines, but the operation is JJP's actual install-stick procedure.
    """

    def __init__(self, iso_path, device_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.iso_path = iso_path
        self.device_path = device_path

    # -- small indirections so tests can monkeypatch the OS layer ----------
    def _format_stick(self):
        fn = {"win32": format_stick_windows,
              "darwin": format_stick_macos}.get(sys.platform,
                                                format_stick_linux)
        return fn(self.device_path, self._log)

    def _mount_iso(self):
        fn = {"win32": mount_iso_windows,
              "darwin": mount_iso_macos}.get(sys.platform, mount_iso_linux)
        return fn(self.iso_path, self._log)

    def _eject_stick(self, mount_root):
        fn = {"win32": eject_stick_windows,
              "darwin": eject_stick_macos}.get(sys.platform,
                                               eject_stick_linux)
        fn(mount_root, self.device_path, self._log)

    # ----------------------------------------------------------------------
    def _run(self):
        # A directory device_path is a pre-mounted target (unit tests);
        # everything privileged is skipped and the Check/Copy/Verify core
        # runs on plain folders.
        premounted = os.path.isdir(self.device_path)

        self._set_phase(0)  # Check stick
        if not premounted and not is_device_path(self.device_path):
            raise PipelineError(
                PHASES[0],
                "Preparing a stick needs a physical drive (e.g. "
                r"\\.\PHYSICALDRIVE2), not a file path (got %r). Pick the "
                "stick from the dropdown." % self.device_path)
        iso_is_dir = os.path.isdir(self.iso_path)
        if not iso_is_dir and not os.path.isfile(self.iso_path):
            raise PipelineError(
                PHASES[0], "ISO not found: %r" % self.iso_path)
        iso_size = (_tree_size(self.iso_path) if iso_is_dir
                    else os.path.getsize(self.iso_path))
        if sys.platform == "win32" and iso_size > _WIN_FAT32_USABLE:
            raise PipelineError(
                PHASES[0],
                "This ISO holds %.1f GB but Windows can only create FAT32 "
                "volumes up to 32 GB, so the app can't prepare this stick "
                "here. Write it with Rufus instead (default settings, 'ISO "
                "Image mode'): Rufus formats large FAT32 itself."
                % (iso_size / 1e9))
        self._log("Preparing a JJP install stick: the stick is formatted "
                  "FAT32 and the ISO's files are copied onto it (the "
                  "machine reads the files off the stick — it never boots "
                  "a raw image).", "info")
        self._check_cancel()

        self._set_phase(1)  # Format stick
        if premounted:
            self._log("Target is a folder — skipping the format (test "
                      "mode).", "info")
            mount_root = self.device_path
        else:
            self._log("Formatting the stick (FAT32, MBR, label %s)..."
                      % STICK_LABEL, "info")
            self._set_band(0, 10)
            self._bp(1, 2, "Formatting…")
            mount_root = self._format_stick()
            self._log("Stick formatted, mounted at %s" % mount_root,
                      "success")
        self._check_cancel()

        free = shutil.disk_usage(mount_root).free
        if free < iso_size:
            raise PipelineError(
                PHASES[1],
                "The stick is too small: the installer needs %.1f GB but "
                "the stick has %.1f GB free. Use a larger stick."
                % (iso_size / 1e9, free / 1e9))

        self._set_phase(2)  # Copy installer files
        if iso_is_dir:
            src_root, unmount = self.iso_path, lambda: None
        else:
            self._log("Mounting the ISO to read its files...", "info")
            src_root, unmount = self._mount_iso()
        try:
            files = sorted(_iter_files(src_root))
            total = sum(os.path.getsize(p) for p in files)
            self._log("Copying %d files (%.1f GB) onto the stick..."
                      % (len(files), total / 1e9), "info")
            self._set_band(10, 90)
            copied = 0
            for src in files:
                self._check_cancel()
                rel = os.path.relpath(src, src_root)
                dst = os.path.join(mount_root, rel)
                os.makedirs(os.path.dirname(dst) or mount_root,
                            exist_ok=True)
                with open(src, "rb") as fin, open(dst, "wb") as fout:
                    while True:
                        chunk = fin.read(_COPY_CHUNK)
                        if not chunk:
                            break
                        fout.write(chunk)
                        copied += len(chunk)
                        self._bp(copied, total, "Copying %s" % rel)
                        self._check_cancel()

            self._set_phase(3)  # Verify
            self._set_band(90, 98)
            self._log("Verifying the copy...", "info")
            bad = []
            for i, src in enumerate(files):
                self._check_cancel()
                rel = os.path.relpath(src, src_root)
                dst = os.path.join(mount_root, rel)
                if not os.path.isfile(dst):
                    bad.append("%s (missing)" % rel)
                elif os.path.getsize(dst) != os.path.getsize(src):
                    bad.append("%s (size mismatch)" % rel)
                self._bp(i + 1, len(files), "Verifying")
            if bad:
                raise PipelineError(
                    PHASES[3],
                    "The copy did not verify — the stick is incomplete and "
                    "must be re-prepared:\n  %s"
                    % "\n  ".join(bad[:10]))
        finally:
            unmount()

        self._set_phase(4)  # Eject
        self._set_band(98, 100)
        if premounted:
            self._log("Target is a folder — skipping the eject (test "
                      "mode).", "info")
        else:
            self._log("Flushing and ejecting the stick...", "info")
            self._eject_stick(mount_root)
        self._bp(1, 1, "Done")

        self._done(True,
                   "USB install stick ready (%d files, %.1f GB).\n\n"
                   "Put it in the USB slot at the front of the machine's "
                   "cabinet (either Cabinet Board slot; OK to unplug the "
                   "dongle), then turn the machine on — the installer "
                   "starts by itself and offers an optional factory "
                   "reset." % (len(files), total / 1e9))
