r"""Sector-aligned raw-device I/O and whole-image flashing (manufacturer-agnostic).

Two consumers share this, which is why it lives in ``core`` rather than under a
plugin (a plugin importing another plugin's package — e.g. ``stern`` — would drag
in that plugin's heavy engine deps):
  * Stern Spike 2's Direct-SD path points the pure-Python ext4 reader /
    size-neutral patcher at the **physical card** instead of a card *image*.
  * Any plugin with ``capabilities.flash_image`` (Stern, CGC) raw-copies a
    pre-built ``.img``/``.raw`` onto a card via :func:`flash_image_to_device`.

The file-based Extract/Write open the card *image* with ``open(path, "rb")``;
Direct-SD instead points the same pure-Python ext4 reader / size-neutral patcher
at the **physical card** (``\\.\PHYSICALDRIVEn`` on Windows, ``/dev/sdX`` on
Linux/macOS).  Block devices require every read/write to be aligned to the
device's logical sector size, so a plain ``open()`` (which issues arbitrary
offsets/lengths) fails.  :class:`RawDeviceFile` presents the usual
byte-addressable ``seek``/``read``/``write`` interface that ``Ext4Reader`` and
``engine`` expect, doing sector-aligned reads — and read-modify-write for
unaligned writes — underneath.

Why this works for size-neutral writes without taking the disk offline: every
byte we patch lives in the **ext4** data partition, which Windows has no
filesystem driver for, so it is not a mounted volume.  Windows blocks raw writes
only to sectors that belong to a *mounted* volume; the (FAT) boot partition we
never touch.  So an Administrator handle can patch the ext sectors in place.

Reading a physical drive always needs Administrator (Windows) / root (POSIX);
the GUI gates the Direct-SD buttons on that before these are reached.
"""

import contextlib
import os
import re
import shutil
import struct
import subprocess
import sys
import time

# Open block devices in binary mode; O_BINARY only exists on Windows.
_O_BINARY = getattr(os, "O_BINARY", 0)
# Cap each underlying device read/write at 8 MB (a sector multiple) so a single
# os.read/os.write stays well within driver limits while still streaming fast.
_IO_CHUNK = 8 << 20
# Bulk-flash read buffer (a sector multiple).  16 MB keeps the syscall count low
# on multi-GB card images without holding much memory.
_FLASH_CHUNK = 16 << 20


class FlashError(Exception):
    """A flash cannot proceed (e.g. the image is larger than the target card)."""


class FlashCancelled(Exception):
    """The user cancelled a flash mid-write (the card is now incomplete)."""


def is_device_path(path):
    r"""True if *path* names a raw physical device rather than a file.

    Windows: ``\\.\PHYSICALDRIVEn``.  POSIX: anything under ``/dev/``.
    """
    if not path:
        return False
    p = path.strip()
    if sys.platform == "win32":
        return p.upper().startswith("\\\\.\\PHYSICALDRIVE")
    return p.startswith("/dev/")


# ---------------------------------------------------------------------------
# macOS raw-disk access.
#
# Three quirks make a /dev/diskN open that works fine on Windows/Linux fail on
# a Mac (flippermeister's flash-helper EPERM, the first real-hardware run of
# the elevated flash):
#   * Sonoma+ TCC blocks raw block-device opens with EPERM even as *root*
#     unless the responsible app is on the Full Disk Access list — the same
#     wall the JJP Direct-SSD debugfs path hit (see the FDA banner in
#     main_window).  Apple's blessed door is ``/usr/libexec/authopen``, which
#     performs the open itself and passes the fd back over a socket; root gets
#     its authorization silently (no extra dialog).  We try that before
#     surfacing the one-time FDA recipe as the error.
#   * The buffered ``/dev/diskN`` node writes an order of magnitude slower
#     than the raw ``/dev/rdiskN`` node, which is why every imaging tool uses
#     rdisk.  rdisk demands whole-sector aligned I/O — exactly what
#     :class:`RawDeviceFile` already guarantees — so device opens are
#     translated to the raw node here.
#   * macOS auto-mounts the card's FAT partition, and a mounted volume blocks
#     a write open with EBUSY; ``diskutil unmountDisk`` before the flash is
#     the standard fix (the macOS mirror of the Windows offline+lock dance in
#     :func:`_disk_offline_for_write`).
# ---------------------------------------------------------------------------


def _rdisk_path(path):
    """``/dev/diskN[sM]`` -> ``/dev/rdiskN[sM]`` (macOS raw node); anything
    else — including an already-raw ``/dev/rdiskN`` — is returned unchanged."""
    return re.sub(r"^/dev/disk", "/dev/rdisk", path or "")


def _fda_guidance(path):
    """Actionable message for a root EPERM on a macOS disk node (TCC denial)."""
    return (
        "macOS blocked raw access to %s (Operation not permitted). This is "
        "the Full Disk Access privacy protection, not a problem with the "
        "card or the app. One-time fix: open System Settings > Privacy & "
        "Security > Full Disk Access, click +, add Pinball Asset "
        "Decryptor.app, and toggle it ON. Then fully quit the app (Cmd+Q), "
        "reopen it, and flash again." % path)


def _authopen_fd(path, flags):
    """Open *path* via ``/usr/libexec/authopen`` and return the fd (macOS).

    authopen opens the device node itself (an Apple system binary the TCC
    layer trusts) and hands the open fd back over a Unix-socket pair via
    SCM_RIGHTS, sidestepping the Full-Disk-Access check that makes a plain
    ``open()`` fail with EPERM even as root on Sonoma+.  Callers are root
    (the elevated flash helper), so authopen's authorization is pre-granted
    and no password dialog appears.  Returns ``None`` on any failure —
    missing binary, denied authorization, protocol hiccup — and the caller
    falls back to its own error path.
    """
    import socket
    if not hasattr(socket, "recv_fds"):
        return None
    try:
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    except (OSError, AttributeError):
        return None
    proc = None
    try:
        proc = subprocess.Popen(
            ["/usr/libexec/authopen", "-stdoutpipe", "-o", str(int(flags)),
             path],
            stdout=theirs, stderr=subprocess.DEVNULL)
        theirs.close()
        ours.settimeout(30)
        _msg, fds, _flags, _addr = socket.recv_fds(ours, 16, 1)
        proc.wait(timeout=30)
        return fds[0] if fds else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
        with contextlib.suppress(OSError):
            ours.close()
        with contextlib.suppress(OSError):
            theirs.close()


# ---------------------------------------------------------------------------
# Low-level byte-stream backends.
#
# POSIX (and any *file* path on Windows) uses plain ``os`` fd I/O.  But writing
# to a Windows *physical drive* (``\\.\PHYSICALDRIVEn``) through the C-runtime fd
# that ``os.open(O_RDWR)`` hands back fails — ``os.write`` returns ``[Errno 9]
# Bad file descriptor`` even on a handle whose reads succeed, because the CRT fd
# layer doesn't properly support write I/O to raw device handles.  Real imaging
# tools (Win32DiskImager, Rufus, dd) go straight to the Win32 API; so do we for
# the writable device path.  Reads of a card (Extract) keep using the fd backend
# (verified working on hardware), so this change only touches the write path.
# ---------------------------------------------------------------------------


class _FdIO:
    """``os``-level fd backend: POSIX always, and every *file* path on Windows."""

    def __init__(self, path, writable):
        self.path = path
        flags = (os.O_RDWR if writable else os.O_RDONLY) | _O_BINARY
        try:
            self.fd = os.open(path, flags)
        except PermissionError as e:
            # macOS TCC denies raw-disk opens with EPERM even as root unless
            # the app is on the Full Disk Access list.  authopen (Apple's own
            # disk-open broker) is exempt and silent for root, so try it
            # before turning the failure into one-time setup instructions.
            # Non-root opens keep the plain error: there EPERM just means
            # "needs elevation", which the callers already handle.
            euid = getattr(os, "geteuid", lambda: -1)()
            if not (sys.platform == "darwin" and is_device_path(path)
                    and euid == 0):
                raise
            fd = _authopen_fd(path, flags)
            if fd is None:
                raise PermissionError(e.errno, _fda_guidance(path),
                                      path) from e
            self.fd = fd

    def seek(self, pos):
        os.lseek(self.fd, pos, os.SEEK_SET)

    def read(self, n):
        return os.read(self.fd, n)

    def write(self, data):
        return os.write(self.fd, data)

    def size(self):
        try:
            end = os.lseek(self.fd, 0, os.SEEK_END)
            os.lseek(self.fd, 0, os.SEEK_SET)
            return end if end and end > 0 else None
        except OSError:
            return None

    def fsync(self):
        try:
            os.fsync(self.fd)
        except OSError:
            pass

    def fileno(self):
        return self.fd

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_BEGIN = 0
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    # IOCTL_DISK_GET_LENGTH_INFO — the only reliable way to get a physical
    # drive's byte length (SEEK_END reports 0 on a raw device handle).
    _IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
    # Volume lock/dismount — a whole-disk flash overwrites the mounted FAT boot
    # partition's sectors, which Windows blocks (ERROR_ACCESS_DENIED) until the
    # volume is locked + dismounted (Set-Disk -IsOffline is unreliable on
    # removable SD cards, so we do it the way imaging tools do).
    _IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
    _FSCTL_LOCK_VOLUME = 0x00090018
    _FSCTL_UNLOCK_VOLUME = 0x0009001C
    _FSCTL_DISMOUNT_VOLUME = 0x00090020

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                             wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE

    _ReadFile = _kernel32.ReadFile
    _ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _ReadFile.restype = wintypes.BOOL

    _WriteFile = _kernel32.WriteFile
    _WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _WriteFile.restype = wintypes.BOOL

    _SetFilePointerEx = _kernel32.SetFilePointerEx
    _SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                  ctypes.POINTER(ctypes.c_longlong),
                                  wintypes.DWORD]
    _SetFilePointerEx.restype = wintypes.BOOL

    _DeviceIoControl = _kernel32.DeviceIoControl
    _DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    _DeviceIoControl.restype = wintypes.BOOL

    _FlushFileBuffers = _kernel32.FlushFileBuffers
    _FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _FlushFileBuffers.restype = wintypes.BOOL

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    class _Win32IO:
        """Win32 ``CreateFileW``/``ReadFile``/``WriteFile`` backend for raw
        physical-drive I/O (used for *writable* device opens on Windows)."""

        def __init__(self, path, writable):
            self.path = path
            access = _GENERIC_READ | (_GENERIC_WRITE if writable else 0)
            share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
            handle = _CreateFileW(path, access, share, None, _OPEN_EXISTING,
                                  _FILE_ATTRIBUTE_NORMAL, None)
            if handle is None or handle == _INVALID_HANDLE_VALUE:
                err = ctypes.get_last_error()
                raise OSError(
                    0, "Couldn't open %s for %s (WinError %d). Direct-SD writes "
                    "need Administrator." % (
                        path, "read/write" if writable else "read", err), path,
                    err)
            self._h = handle

        def seek(self, pos):
            newpos = ctypes.c_longlong(0)
            if not _SetFilePointerEx(self._h, ctypes.c_longlong(pos),
                                     ctypes.byref(newpos), _FILE_BEGIN):
                raise OSError(0, "SetFilePointerEx(%s) failed (WinError %d)"
                              % (self.path, ctypes.get_last_error()))

        def read(self, n):
            if n <= 0:
                return b""
            buf = ctypes.create_string_buffer(n)
            got = wintypes.DWORD(0)
            if not _ReadFile(self._h, buf, n, ctypes.byref(got), None):
                raise OSError(0, "ReadFile(%s) failed (WinError %d)"
                              % (self.path, ctypes.get_last_error()))
            return buf.raw[:got.value]

        def write(self, data):
            mv = memoryview(data)
            n = mv.nbytes
            if n == 0:
                return 0
            cbuf = (ctypes.c_char * n).from_buffer_copy(mv)
            wrote = wintypes.DWORD(0)
            if not _WriteFile(self._h, cbuf, n, ctypes.byref(wrote), None):
                raise OSError(0, "WriteFile(%s) failed (WinError %d)"
                              % (self.path, ctypes.get_last_error()))
            return wrote.value

        def size(self):
            buf = ctypes.create_string_buffer(8)
            ret = wintypes.DWORD(0)
            if _DeviceIoControl(self._h, _IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                                buf, 8, ctypes.byref(ret), None):
                (length,) = struct.unpack("<q", buf.raw[:8])
                return length if length > 0 else None
            return None

        def fsync(self):
            _FlushFileBuffers(self._h)

        def fileno(self):
            return -1

        def close(self):
            if self._h is not None:
                _CloseHandle(self._h)
                self._h = None


def _open_backend(path, writable):
    r"""Pick the byte-stream backend for *path*.

    The Win32 backend is used only where the fd path is known to break: a
    *writable* open of a real ``\\.\PHYSICALDRIVE`` on Windows.  Everything else
    — POSIX, file paths, and read-only card opens (the verified Extract path) —
    stays on plain ``os`` fd I/O.
    """
    if (sys.platform == "win32" and writable and is_device_path(path)):
        return _Win32IO(path, writable)
    if sys.platform == "darwin" and is_device_path(path):
        # Use the raw node: the buffered /dev/diskN crawls on bulk writes, and
        # rdisk's whole-sector alignment requirement is already satisfied by
        # RawDeviceFile's aligned reads/writes.
        path = _rdisk_path(path)
    return _FdIO(path, writable)


#: How long a window the flash's speed readout averages over.  Long enough
#: that a chunk boundary does not swing it, short enough that it follows a
#: card falling off its SLC cache within a few seconds.
_RATE_WINDOW_S = 30.0


def _time_left(seconds):
    """``'about 41 minutes left'``, coarse - or ``''`` when there is no
    honest answer.  A card's write rate is nowhere near steady enough to
    quote seconds at anyone."""
    if seconds is None or seconds != seconds or seconds < 0:    # NaN included
        return ""
    if seconds > 24 * 3600:
        return ""
    if seconds < 60:
        return "less than a minute left"
    mins = int(round(seconds / 60.0))
    if mins < 60:
        return "about %d minute%s left" % (mins, "" if mins == 1 else "s")
    hours, mins = divmod(mins, 60)
    if not mins:
        return "about %d hour%s left" % (hours, "" if hours == 1 else "s")
    return "about %dh %dm left" % (hours, mins)


def _rate_note(hist, done, total, now=None):
    """``' - 6.1 MB/s, about 41 minutes left'`` from the RECENT rate, or ''.

    RECENT, and not the average since the start.  A cheap card takes its
    first gigabyte at the speed of its SLC cache and then falls to a fifth
    of that for the rest, so an average is a number nobody will live with;
    the one worth putting in front of a person is the one they are on now.
    Without it a flash is an elapsed clock and a crawling bar, and finding
    out at minute forty that the CARD is the problem is finding out too
    late.  *hist* is the caller's own list, kept across calls."""
    now = time.monotonic() if now is None else now
    hist.append((now, done))
    while len(hist) > 2 and now - hist[0][0] > _RATE_WINDOW_S:
        del hist[0]
    if len(hist) < 2:
        return ""
    span, moved = now - hist[0][0], done - hist[0][1]
    if span <= 0 or moved <= 0:
        return ""
    rate = moved / span
    left = _time_left((total - done) / rate)
    return " - %.1f MB/s%s" % (rate / 1e6, (", " + left) if left else "")


class RawDeviceFile:
    """A seekable byte stream over a raw block device with aligned underlying I/O.

    ``writable=False`` opens read-only (Extract); ``writable=True`` opens
    read-write for the in-place size-neutral patch (Write).  ``sector`` may be
    forced (used by tests against a regular file); otherwise it is probed.
    """

    def __init__(self, path, writable=False, sector=None):
        self.path = path
        self.writable = writable
        self._io = _open_backend(path, writable)
        try:
            self.sector = sector or self._probe_sector()
            self._size = self._io.size()
        except Exception:
            self._io.close()
            raise
        self._pos = 0

    @property
    def size(self):
        """Total device byte length, or ``None`` if it couldn't be probed."""
        return self._size

    # ---- probing -----------------------------------------------------------
    def _probe_sector(self):
        """Logical sector size: the smallest power-of-two read that succeeds.

        A block device rejects reads whose length isn't a multiple of its
        logical sector size, so a successful 512-byte read at offset 0 means
        512; otherwise 4096.  (Regular files accept any length → 512.)"""
        for s in (512, 4096):
            try:
                self._io.seek(0)
                if len(self._io.read(s)) == s:
                    return s
            except OSError:
                continue
        return 512

    # ---- stream interface --------------------------------------------------
    def seek(self, pos, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._pos = pos
        elif whence == os.SEEK_CUR:
            self._pos += pos
        elif whence == os.SEEK_END:
            if self._size is None:
                raise OSError("device size unknown; SEEK_END unsupported")
            self._pos = self._size + pos
        else:
            raise ValueError("invalid whence: %r" % (whence,))
        return self._pos

    def tell(self):
        return self._pos

    def _aligned_read(self, start, length):
        """Return exactly the bytes ``[start, start+length)`` (start/length need
        not be aligned), reading only whole sectors from the device."""
        if length <= 0:
            return b""
        sec = self.sector
        a_start = (start // sec) * sec
        a_end = ((start + length + sec - 1) // sec) * sec
        if self._size is not None:
            a_end = min(a_end, self._size)
        if a_end <= a_start:
            return b""
        self._io.seek(a_start)
        buf = bytearray()
        want = a_end - a_start
        while len(buf) < want:
            chunk = self._io.read(min(_IO_CHUNK, want - len(buf)))
            if not chunk:
                break
            buf += chunk
        lo = start - a_start
        return bytes(buf[lo:lo + length])

    def read(self, n=-1):
        if n is None or n < 0:
            if self._size is None:
                raise OSError("read-to-EOF unsupported on this device")
            n = max(0, self._size - self._pos)
        data = self._aligned_read(self._pos, n)
        self._pos += len(data)
        return data

    def write(self, data):
        """Write *data* at the current position via read-modify-write of the
        sectors it touches (so an arbitrary-offset, arbitrary-length patch lands
        without violating the device's sector alignment)."""
        if not self.writable:
            raise OSError("device opened read-only")
        if not data:
            return 0
        sec = self.sector
        start = self._pos
        length = len(data)
        a_start = (start // sec) * sec
        a_end = ((start + length + sec - 1) // sec) * sec
        # Never write past the device end: a block device's length is a sector
        # multiple, so clamping keeps the region sector-aligned; for a backing
        # file it just avoids extending it past its original size.
        if self._size is not None:
            a_end = min(a_end, self._size)
        region = bytearray(self._aligned_read(a_start, a_end - a_start))
        if len(region) < (a_end - a_start):           # extend (tail / new file)
            region += bytes((a_end - a_start) - len(region))
        lo = start - a_start
        region[lo:lo + length] = data
        self._io.seek(a_start)
        mv = memoryview(region)
        off = 0
        while off < len(region):
            off += self._io.write(mv[off:off + min(_IO_CHUNK, len(region) - off)])
        self._pos += length
        return length

    def copy_image_onto(self, src, total, *, progress=None, cancel=None,
                        chunk=None):
        """Bulk-copy ``total`` bytes from file object *src* onto this device,
        starting at offset 0 (a dd-style flash).

        Whole-sector chunks are written straight through the fd (no
        read-modify-write — a flash overwrites every sector, so the RMW
        pre-read :meth:`write` does would be pure wasted I/O).  Only the final
        partial sector — rare, since disk images are almost always a sector
        multiple — falls back to RMW so the bytes past the image end are
        preserved.

        ``progress(done, total, desc)`` is called as bytes land; ``cancel()``
        (if given) is polled between chunks and a True return raises
        :class:`FlashCancelled` (a partial flash leaves the card unbootable —
        the caller is expected to surface that).  Returns the bytes written.
        """
        if not self.writable:
            raise OSError("device opened read-only")
        sec = self.sector
        # None, not the constant as a default argument: a default is bound
        # at def time, so a test that wants a smaller chunk could not get
        # one by patching the constant.
        chunk = _FLASH_CHUNK if chunk is None else chunk
        # Round the read buffer down to a whole number of sectors so every
        # bulk write is sector-aligned; never let it collapse to zero.
        step = max((chunk // sec) * sec, sec)
        written = 0
        rate = []
        self._io.seek(0)
        while written < total:
            if cancel is not None and cancel():
                raise FlashCancelled(
                    "Flash cancelled after %d of %d bytes." % (written, total))
            want = min(step, total - written)
            buf = src.read(want)
            if not buf:
                break
            if len(buf) % sec == 0:
                # Aligned fast path: write directly, capped per write syscall.
                self._io.seek(written)
                mv = memoryview(buf)
                off = 0
                while off < len(buf):
                    off += self._io.write(
                        mv[off:off + min(_IO_CHUNK, len(buf) - off)])
            else:
                # Final sub-sector tail: RMW the trailing sector(s) so we don't
                # disturb whatever lies past the image's last byte.
                self.seek(written)
                self.write(buf)
            written += len(buf)
            if progress is not None:
                progress(written, total, "Writing image to SD card…"
                         + _rate_note(rate, written, total))
        return written

    def flush(self):
        self._io.fsync()

    def fileno(self):
        return self._io.fileno()

    def close(self):
        if self._io is not None:
            try:
                self._io.close()
            finally:
                self._io = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def read_mbr(device_path):
    r"""Read the first 512 bytes (the MBR) of a raw device, sector-aligned.

    Returns the bytes (possibly empty on failure).  Used to confirm the Spike 2
    partition signature and locate the ext partitions before extracting/writing.
    """
    try:
        with RawDeviceFile(device_path, writable=False) as f:
            return f.read(512)
    except OSError:
        return b""


def device_size(device_path):
    """Total byte length of a raw device, or ``None`` if it can't be probed.

    Used by the flasher's preflight to compare the card's capacity against the
    image size before any write (so a too-big image is refused, not truncated).
    On Windows a physical drive's size is read via IOCTL — ``SEEK_END`` reports
    0 on a raw-device fd, which is why the GUI used to say "couldn't read size".
    """
    if sys.platform == "win32" and is_device_path(device_path):
        try:
            io = _Win32IO(device_path, writable=False)
        except OSError:
            return None
        try:
            return io.size()
        finally:
            io.close()
    if sys.platform == "darwin" and is_device_path(device_path):
        try:
            with RawDeviceFile(device_path, writable=False) as f:
                if f.size:
                    return f.size
        except OSError:
            pass
        # The raw open was denied (unprivileged GUI preflight, or TCC without
        # Full Disk Access) or SEEK_END came back empty — diskutil reports the
        # size without touching the device node, so the capacity check still
        # works.
        return _diskutil_total_size(device_path)
    try:
        with RawDeviceFile(device_path, writable=False) as f:
            return f.size
    except OSError:
        return None


def _diskutil_total_size(device_path):
    """Disk byte length via ``diskutil info -plist`` (macOS), or ``None``."""
    try:
        r = subprocess.run(["diskutil", "info", "-plist", device_path],
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    return _parse_diskutil_total_size(r.stdout)


def _parse_diskutil_total_size(plist_bytes):
    """``TotalSize`` (bytes) out of a ``diskutil info -plist`` document."""
    import plistlib
    try:
        info = plistlib.loads(plist_bytes)
    except Exception:
        return None
    size = info.get("TotalSize") or info.get("Size")
    try:
        return int(size) if size else None
    except (TypeError, ValueError):
        return None


def format_size(n):
    """Human-readable size string (``7.83 GB``) for the flash UI / logs.

    ``None`` -> ``"unknown"``.  Uses decimal GB/MB (10^9 / 10^6) to match how
    card capacities are advertised, so a "16 GB" card reads ~14.9 GB nowhere
    and the comparison the user sees lines up with the packaging.
    """
    if n is None:
        return "unknown"
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 10 ** 9)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 10 ** 6)
    if n >= 10 ** 3:
        return "%.0f KB" % (n / 10 ** 3)
    return "%d bytes" % n


def flash_preflight(image_path, device_path):
    """Return ``(image_size, card_size_or_None)`` for the flash confirm UI.

    Pure inspection (no writes): lets the GUI show "Image 7.8 GB -> Card 14.9 GB"
    and decide whether the image fits before the user commits.
    """
    img = os.path.getsize(image_path)
    return img, device_size(device_path)


def _physicaldrive_number(device_path):
    r"""Extract N from ``\\.\PHYSICALDRIVEn`` (Windows), else ``None``."""
    m = re.search(r"PHYSICALDRIVE(\d+)", device_path or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


@contextlib.contextmanager
def _disk_offline_for_write(device_path, log=None):
    r"""Take the target disk offline (+ writable) for a whole-disk flash, then
    bring it back online.

    A flash overwrites the *entire* disk, including the FAT boot partition that
    Windows mounts as a drive letter — and Windows blocks raw writes to sectors
    belonging to a *mounted* volume.  ``Set-Disk -IsOffline`` dismounts every
    volume on the disk so an Administrator handle can write all of it, the same
    thing dd/imaging tools do under the hood.  Best-effort: a failure here is
    logged and we proceed (the write itself then surfaces any access error).

    On macOS the card's auto-mounted volumes are unmounted with ``diskutil
    unmountDisk`` first — a mounted volume blocks the whole-disk write open
    with EBUSY, same idea as the Windows lock/dismount.  There is no "online"
    step to undo afterwards: DiskArbitration re-probes the disk by itself once
    the flash finishes.  On Linux (no elevation-safe unmount tool we can rely
    on) we log a hint.  No-op for non-device paths (e.g. a backing file in
    tests).
    """
    if sys.platform != "win32":
        if sys.platform == "darwin" and is_device_path(device_path):
            _macos_unmount_disk(device_path, log)
        elif log is not None and (device_path or "").startswith("/dev/"):
            log("If the write fails as busy, unmount the card's partitions "
                "first (they may have been auto-mounted).", "info")
        yield
        return
    n = _physicaldrive_number(device_path)
    if n is None:                          # a file path (tests) — nothing to do
        yield
        return

    def _ps(cmd):
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as e:
            if log is not None:
                log("Disk offline/online step failed (%s) — continuing." % e,
                    "warning")

    if log is not None:
        log("Taking disk %d offline so the whole card can be written…" % n,
            "info")
    _ps("Set-Disk -Number %d -IsReadOnly $false; "
        "Set-Disk -Number %d -IsOffline $true" % (n, n))
    try:
        yield
    finally:
        if log is not None:
            log("Bringing disk %d back online." % n, "info")
        _ps("Set-Disk -Number %d -IsOffline $false" % n)


def _macos_unmount_disk(device_path, log=None):
    """``diskutil unmountDisk`` every volume on *device_path* (best-effort).

    Failure is logged and we press on — the write open itself surfaces any
    real block (EBUSY), matching the Windows helpers' best-effort contract."""
    if log is not None:
        log("Unmounting the card's volumes so the whole card can be "
            "written (diskutil unmountDisk)…", "info")
    try:
        r = subprocess.run(["diskutil", "unmountDisk", device_path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        if log is not None:
            log("Couldn't unmount the card's volumes (%s) — continuing." % e,
                "warning")
        return
    if r.returncode != 0 and log is not None:
        log("diskutil unmountDisk reported: %s — continuing; the write "
            "itself will surface any real block."
            % (r.stderr or r.stdout or "unknown error").strip(), "warning")


def _eject_device(device_path, log=None):
    """Unmount + eject the just-flashed card so it's safe to pull without a manual
    OS eject (balenaEtcher-style — flippermeister feedback).

    Best-effort and non-fatal: the flash has already completed AND read-back
    verified before this runs, so the card's data is safe regardless; a failed
    eject only means the user ejects it themselves.  No-op for non-device paths
    (a backing file in tests).

      * macOS  — ``diskutil eject`` (unmounts every volume + releases the disk).
      * Windows — ``Set-Disk -IsOffline`` dismounts every volume so the drive
        letters go away and the card is safe to remove (a true media-eject isn't
        reliable across USB card readers; offline is the same safe state Explorer
        reaches via "Safely Remove Hardware").
      * Linux  — ``udisksctl power-off`` (or ``eject``) to spin it down + detach.
    """
    if not is_device_path(device_path):
        return
    ok = False
    try:
        if sys.platform == "darwin":
            # the write open uses /dev/rdiskN; eject the /dev/diskN whole-disk.
            disk = device_path.replace("/dev/rdisk", "/dev/disk")
            r = subprocess.run(["diskutil", "eject", disk],
                               capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
        elif sys.platform == "win32":
            n = _physicaldrive_number(device_path)
            if n is not None:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Set-Disk -Number %d -IsOffline $true" % n],
                    capture_output=True, text=True, timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                ok = r.returncode == 0
        else:
            for cmd in (["udisksctl", "power-off", "-b", device_path],
                        ["eject", device_path]):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=30)
                except (OSError, subprocess.SubprocessError):
                    continue
                if r.returncode == 0:
                    ok = True
                    break
    except (OSError, subprocess.SubprocessError):
        ok = False
    if log is not None:
        log("Card ejected — safe to remove." if ok else
            "Couldn't auto-eject the card — eject it through your OS before "
            "removing it (the flash itself completed and verified).",
            "success" if ok else "info")


def _volume_disk_number(letter):
    """Windows: the physical-disk number backing drive ``letter`` (e.g. ``E``),
    or ``None`` if the letter isn't a single-disk volume we can query."""
    path = "\\\\.\\%s:" % letter
    handle = _CreateFileW(path, 0, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None,
                          _OPEN_EXISTING, 0, None)
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        return None
    try:
        buf = ctypes.create_string_buffer(12)   # STORAGE_DEVICE_NUMBER (3 DWORD)
        ret = wintypes.DWORD(0)
        if _DeviceIoControl(handle, _IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                            buf, 12, ctypes.byref(ret), None):
            _devtype, devnum, _part = struct.unpack("<III", buf.raw[:12])
            return devnum
        return None
    finally:
        _CloseHandle(handle)


@contextlib.contextmanager
def _locked_volumes(device_path, log=None):
    r"""Lock + dismount every mounted volume on the target disk so a whole-disk
    flash isn't blocked, then unlock on exit (Windows; no-op elsewhere).

    A flash overwrites the card's FAT boot partition, whose sectors Windows
    refuses raw writes to while it's mounted (``ERROR_ACCESS_DENIED`` /
    ``WinError 5``).  ``Set-Disk -IsOffline`` is unreliable on removable SD
    cards, so — exactly as Win32DiskImager/Rufus do — we open each drive letter
    on the target disk, ``FSCTL_LOCK_VOLUME`` + ``FSCTL_DISMOUNT_VOLUME`` it, and
    hold the handle open for the whole write (the lock lapses when it closes, so
    the volume remounts on exit).  Only FAT volumes have letters; the ext data
    partitions Windows can't mount don't block writes.  Best-effort: a volume we
    can't lock is logged and we press on (the write surfaces any real block).
    """
    if sys.platform != "win32" or _physicaldrive_number(device_path) is None:
        yield
        return
    n = _physicaldrive_number(device_path)
    handles = []
    try:
        for i in range(26):
            letter = chr(ord("A") + i)
            if _volume_disk_number(letter) != n:
                continue
            handle = _CreateFileW(
                "\\\\.\\%s:" % letter, _GENERIC_READ | _GENERIC_WRITE,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0,
                None)
            if handle is None or handle == _INVALID_HANDLE_VALUE:
                continue
            ret = wintypes.DWORD(0)
            locked = False
            for _attempt in range(10):           # files may be transiently open
                if _DeviceIoControl(handle, _FSCTL_LOCK_VOLUME, None, 0, None, 0,
                                    ctypes.byref(ret), None):
                    locked = True
                    break
                time.sleep(0.2)
            # Dismount regardless: forces the FS to release the sectors even if
            # the lock didn't take (the held handle keeps it dismounted).
            _DeviceIoControl(handle, _FSCTL_DISMOUNT_VOLUME, None, 0, None, 0,
                             ctypes.byref(ret), None)
            handles.append(handle)
            if log is not None:
                log("Dismounted volume %s: on disk %d (locked=%s)."
                    % (letter, n, "yes" if locked else "no"),
                    "info" if locked else "warning")
        yield
    finally:
        for handle in handles:
            ret = wintypes.DWORD(0)
            _DeviceIoControl(handle, _FSCTL_UNLOCK_VOLUME, None, 0, None, 0,
                             ctypes.byref(ret), None)
            _CloseHandle(handle)


#: Below this, a card is worth replacing rather than waiting for.  Every
#: current card clears it several times over: the U3 / V30 marking IS a
#: guaranteed 30 MB/s sustained write, and a real A2 card does 60-90.  A
#: card under 10 MB/s is an old, a counterfeit, or a worn one.
SLOW_CARD_MB_S = 10.0

#: ...and how much has to have been written before saying so.  A cheap card
#: takes its first gigabyte at the speed of its SLC cache; judging it inside
#: that burst calls a good card slow, and judging it too late is no use at
#: all.  256 MB and 20 s is past the burst on every card measured.
_SLOW_AFTER_BYTES = 256 << 20
_SLOW_AFTER_S = 20.0

#: What to say about it - said ONCE per run, and only with a number in hand.
#: Concrete, because "get a faster card" is not an instruction: these are the
#: current A2/V30 families, the marking to look for, and the two other things
#: that cap a write (the reader and the cable, not just the port).
SLOW_CARD_ADVICE = (
    "This card is writing at {rate:.1f} MB/s, which is slow enough to be "
    "worth replacing: {whole} at this rate, against about {fast} on a "
    "current card.\n"
    "  * Look for A2 and V30 (or U3) on the card - V30 is a GUARANTEED "
    "30 MB/s sustained write, and a real A2 card does 60-90 MB/s. SanDisk "
    "Extreme, Samsung PRO Plus or EVO Select, Kingston Canvas Go! Plus and "
    "Lexar Professional 1066x all qualify.\n"
    "  * Buy 32 GB or bigger, and from a seller you trust. Small cards tend "
    "to be old stock with old controllers, and fake cards are common - they "
    "report a big size and write at a few MB/s, exactly like this.\n"
    "  * Samsung PRO Endurance is the one built for a machine that writes "
    "logs and scores every time it runs.\n"
    "  * Check the READER and the CABLE, not just the port: a USB 2.0 reader "
    "caps the whole path at about 35 MB/s however fast the card is.")

#: ...and the one line that beats all of it where it applies: the fastest
#: write is the one you do not do.
SLOW_CARD_MENU_HINT = (
    "\n  * You do not need this wait to change the MENU: tick 'Only the boot "
    "menu' in the flash dialog and it writes one partition instead of the "
    "whole image - about a minute, even on this card, and the machine keeps "
    "its settings and scores.")


def slow_card_advice(rate, total, menu_only=False):
    """The advice, with this card's own numbers in it - or '' when the rate
    is not one worth complaining about.

    A message that quotes what the wait IS and what it WOULD BE is one
    someone can act on; "your card is slow" is not.  *menu_only* adds the
    line that beats a new card outright where it applies."""
    if not rate or rate >= SLOW_CARD_MB_S * 1e6:
        return ""
    whole = _time_left(total / rate) if total else ""
    fast = _time_left(total / (60 * 1e6)) if total else ""
    text = SLOW_CARD_ADVICE.format(
        rate=rate / 1e6,
        whole=whole.replace("left", "for this write").strip() or "a long time",
        fast=fast.replace(" left", "").replace("about ", "").strip()
        or "a few minutes")
    return text + (SLOW_CARD_MENU_HINT if menu_only else "")


def _has_menu_partition(image_path):
    """Could this image be written menu-only?  512 bytes of partition table,
    so it is free to ask before offering the advice that says so."""
    try:
        menu_write_plan(image_path)
        return True
    except Exception:                                   # noqa: BLE001
        return False


def _slow_card_watch(log, progress, menu_only=False):
    """Wrap a progress callback so a slow card SAYS SO, once, while there is
    still time to do something about it.

    In the loop rather than at the end on purpose: finding out that the card
    was the problem after the forty minutes is finding out too late (David:
    "we should put some helpful information like this in the gui for when
    users complain of slow speeds writing")."""
    if log is None:
        return progress
    state = {"said": False, "t0": None, "b0": 0}

    def wrapped(done, total, desc=""):
        if progress is not None:
            progress(done, total, desc)
        if state["said"]:
            return
        now = time.monotonic()
        if state["t0"] is None:
            state["t0"], state["b0"] = now, done
            return
        span, moved = now - state["t0"], done - state["b0"]
        if span < _SLOW_AFTER_S or moved < _SLOW_AFTER_BYTES:
            return
        state["said"] = True
        note = slow_card_advice(moved / span, total, menu_only)
        if note:
            log(note, "warning")
    return wrapped


def flash_image_to_device(image_path, device_path, *, log=None, progress=None,
                          cancel=None, verify=True, on_verify_start=None,
                          eject=True):
    """dd-style raw copy of *image_path* onto the physical *device_path*.

    Refuses (``FlashError``) when the image is larger than the target card — a
    too-big image would be truncated and produce an unbootable card (the failure
    a tester hit with an external imaging tool).  When the card size can't be
    probed it proceeds with a logged warning rather than blocking.  Reports
    progress and honours ``cancel`` (a True return raises :class:`FlashCancelled`
    mid-write).  Returns the number of bytes written.

    With *verify* (default True) the card is read back after the write and
    compared byte-for-byte to the image; a mismatch raises :class:`FlashError`
    so a silently-bad flash (flaky card/reader) is caught here instead of on
    the machine.

    On Windows the disk is taken offline and its mounted volumes are
    locked + dismounted for the duration (a flash overwrites the mounted FAT
    boot partition too); see :func:`_disk_offline_for_write` and
    :func:`_locked_volumes`.

    With *eject* (default True) the card is unmounted/ejected once the verified
    write finishes, so it's safe to pull without a manual OS eject (balenaEtcher
    behaviour; flippermeister feedback).  Best-effort — a failed eject never
    fails the flash.
    """
    img_size = os.path.getsize(image_path)
    # Probe the capacity read-only and guard BEFORE taking the disk offline, so a
    # too-big image is rejected without disturbing the card's mount state.
    dev_size = device_size(device_path)
    if log is not None:
        log("Image: %s (%s)" % (os.path.basename(image_path),
                                format_size(img_size)), "info")
        log("Target card: %s (%s)" % (device_path, format_size(dev_size)),
            "info")
    if dev_size is not None and img_size > dev_size:
        raise FlashError(
            "The image (%s) is larger than the card (%s). Use a larger "
            "SD card." % (format_size(img_size), format_size(dev_size)))
    if dev_size is None and log is not None:
        log("Could not read the card's size — proceeding without a capacity "
            "check. Make sure the card is at least %s." % format_size(img_size),
            "warning")

    try:
        with _disk_offline_for_write(device_path, log), \
                _locked_volumes(device_path, log):
            with RawDeviceFile(device_path, writable=True) as dev:
                with open(image_path, "rb") as src:
                    written = dev.copy_image_onto(
                        src, img_size,
                        progress=_slow_card_watch(
                            log, progress, _has_menu_partition(image_path)),
                        cancel=cancel)
                dev.flush()
            # Read the card back and confirm it byte-for-byte matches the
            # image.  A raw flash has no other integrity check, and a
            # silently-bad write (flaky card/reader) produces a card the
            # machine can't install from -- on CGC, a corrupt journal region
            # got replayed on the machine and reverted the payload to a SHELL
            # ERROR, indistinguishable from a good card until it failed on
            # the hardware.  Verify here, with a fresh read handle
            # (post-flush, post-close) so we compare what actually landed,
            # not a write-cache echo.
            if verify:
                if on_verify_start is not None:
                    on_verify_start()
                _verify_flash_readback(device_path, image_path, img_size,
                                       log=log, progress=progress,
                                       cancel=cancel)
    except PermissionError as e:
        # Surface a denied device open (macOS TCC without Full Disk Access,
        # or a genuinely unelevated run) as a FlashError so the dialog shows
        # the remedy instead of a helper traceback.
        raise FlashError(str(e)) from e
    if progress is not None:
        progress(img_size, img_size, "Flash complete")
    if log is not None:
        log("Wrote %s to %s%s." % (
            format_size(written), device_path,
            " (verified)" if verify else ""), "success")
    # Auto-eject so the user can pull the card without a manual OS eject (matches
    # balenaEtcher; flippermeister feedback).  Runs only after a fully-verified
    # write, and never fails the flash.
    if eject:
        _eject_device(device_path, log)
    return written


# Read-back verify chunk (bytes).  Large enough that the per-chunk overhead is
# negligible against the multi-GB read, small enough to report smooth progress.
_VERIFY_CHUNK = 16 * 1024 * 1024


def read_device_to_image(device_path, image_path, *, log=None, progress=None,
                         cancel=None):
    """dd-style raw copy of the whole card *device_path* into *image_path*.

    The exact inverse of :func:`flash_image_to_device`: every sector of the
    card, in order, into one ``.raw`` file the app's own Partitions / Compare
    tabs (and any imaging tool) can open.  Batch 33 asked for it — the app
    could write a card but not back one up, so "image the card, change one
    setting on the machine, image it again and diff" needed an outside tool.

    Refuses (:class:`FlashError`) when the card's size can't be probed or the
    destination volume hasn't room for it; both are cheap checks that turn a
    multi-GB failure at 99% into an instant, explicable one.  Reports progress
    and honours ``cancel`` (a True return raises :class:`FlashCancelled`).
    Returns the number of bytes read.

    The image is built at ``<image_path>.part`` and renamed only once the whole
    card has landed, so an interrupted read can never leave a short file
    sitting there looking like a good backup.
    """
    dev_size = device_size(device_path)
    if not dev_size:
        raise FlashError(
            "Could not read the size of %s, so there is no way to know how "
            "much to copy. Re-seat the card (or its reader) and try again."
            % device_path)

    dest_dir = os.path.dirname(os.path.abspath(image_path)) or "."
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        raise FlashError("Could not create the folder for the image:\n%s"
                         % e) from e
    try:
        free = shutil.disk_usage(dest_dir).free
    except OSError:
        free = None
    if free is not None and free < dev_size:
        raise FlashError(
            "The card is %s but only %s is free in %s. A card image is a "
            "copy of the whole card, empty space included, so it needs the "
            "card's full size. Pick a location with more room."
            % (format_size(dev_size), format_size(free), dest_dir))

    if log is not None:
        log("Source card: %s (%s)" % (device_path, format_size(dev_size)),
            "info")
        log("Image: %s" % image_path, "info")

    part_path = image_path + ".part"
    read = 0
    try:
        with RawDeviceFile(device_path, writable=False) as dev, \
                open(part_path, "wb") as out:
            while read < dev_size:
                if cancel is not None and cancel():
                    raise FlashCancelled(
                        "Read cancelled after %d of %d bytes."
                        % (read, dev_size))
                want = min(_VERIFY_CHUNK, dev_size - read)
                buf = dev._aligned_read(read, want)
                if not buf:
                    break
                out.write(buf)
                read += len(buf)
                if progress is not None:
                    progress(read, dev_size, "Reading SD card…")
            out.flush()
            os.fsync(out.fileno())
    except PermissionError as e:
        # Same remedy as the flash side: a denied raw open is elevation
        # (or macOS Full Disk Access), not a broken card.
        _unlink_quiet(part_path)
        raise FlashError(str(e)) from e
    except FlashCancelled:
        _unlink_quiet(part_path)
        raise
    except OSError as e:
        _unlink_quiet(part_path)
        raise FlashError("Reading the card failed at byte %s:\n%s"
                         % (f"{read:,}", e)) from e

    if read < dev_size:
        # The card stopped handing bytes back early — a short image would
        # look complete in Explorer and fail on the machine.
        _unlink_quiet(part_path)
        raise FlashError(
            "The card stopped responding after %s of %s. The image was not "
            "kept. Re-seat the card (or its reader) and try again."
            % (format_size(read), format_size(dev_size)))

    try:
        os.replace(part_path, image_path)
    except OSError as e:
        _unlink_quiet(part_path)
        raise FlashError("Could not save the finished image to %s:\n%s"
                         % (image_path, e)) from e

    if progress is not None:
        progress(read, read, "Read complete")
    if log is not None:
        log("Read %s from %s into %s."
            % (format_size(read), device_path, image_path), "success")
    return read


def _unlink_quiet(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ============================================================ the menu-only write
#: The rootfs partition: MBR primary index 1, and the ONLY partition a menu
#: change touches.  The selector, its media and images.conf all live in p2
#: (mkmulticard's ``inject``), which is why "Apply to card" rewrites a card
#: image in seconds - and why writing that one partition onto a card the
#: image was already flashed from is a minute's work instead of an hour's.
_ROOTFS_INDEX = 1

#: How much of a partition is read to identify it: the ext4 superblock lives
#: at byte 1024 and carries the filesystem UUID, the block counts and the
#: checksum seed, so 4 KiB from the start tells two different games trees
#: apart with certainty.  A FAT boot sector is in the same 4 KiB.
_IDENT_BYTES = 4096

#: The partitions a menu write neither compares nor writes, because the
#: MACHINE owns what is in them and they differ from the image on any card
#: that has ever booted:
#:
#:   p1  /mnt/boot, and it is FAT.  A FAT filesystem is rewritten by being
#:       MOUNTED - the dirty flag in the boot sector, the FSInfo block - so
#:       its first bytes stop matching the image the moment the machine
#:       reads the kernel out of it.  This one cost a refusal on a card that
#:       WAS the right card (David: "why is the write failing? this is the
#:       exact raw image that I wrote onto the attached sd card").  It was
#:       only ever a cheap extra proof, and it proved nothing about which
#:       GAMES are on the card, which is the whole question.
#:   p5  /data - the settings, the NVRAM, the scores.
#:   p6  /dump - the logs.
#:
#: What is left is what cannot drift: the partition table and the EBR chain
#: (nothing rewrites those), and the ext4 superblock of every games tree,
#: which the machine mounts READ-ONLY and therefore never touches.
_MACHINE_OWNED = (1, 5, 6)


def _mbr_primaries(mbr):
    """``[(index, type, lba, sectors)]`` from a 512-byte MBR, empty if it is
    not one.  Kept here rather than borrowed from the Stern plugin: core does
    not import plugins, and this is six lines of a fixed on-disk format."""
    if len(mbr) < 512 or mbr[510:512] != b"\x55\xaa":
        return []
    out = []
    for i in range(4):
        e = mbr[446 + i * 16:446 + i * 16 + 16]
        ptype = e[4]
        lba, count = struct.unpack_from("<II", e, 8)
        if ptype and count:
            out.append((i, ptype, lba, count))
    return out


def _ebr_chain(read_at, ext_lba, sector=512, limit=64):
    """Walk the extended partition's EBR chain -> ``[(ebr_lba, type, start,
    count)]`` for the logicals, in card order (p5, p6, p7, ...).

    *read_at* reads one sector at an LBA.  ``limit`` is a cycle guard: a
    corrupt chain must not spin.
    """
    out = []
    cur, seen = ext_lba, set()
    while cur and cur not in seen and len(out) < limit:
        seen.add(cur)
        sec = read_at(cur)
        if len(sec) < 512 or sec[510:512] != b"\x55\xaa":
            break
        e0 = sec[446:462]
        if e0[4] and struct.unpack_from("<II", e0, 8)[1]:
            start, count = struct.unpack_from("<II", e0, 8)
            out.append((cur, e0[4], cur + start, count))
        e1 = sec[462:478]
        nxt = struct.unpack_from("<II", e1, 8)[0] if e1[4] else 0
        cur = (ext_lba + nxt) if nxt else 0
    return out


def menu_write_plan(image_path):
    """What a menu-only write would touch, off the IMAGE alone (no device).

    ``{"write": [(offset, length, what)], "prove": [(offset, length, what)],
    "sector": 512}`` - *write* is the rootfs partition, *prove* is every range
    that has to match on the card before a byte is written.

    THE PROOF IS THE WHOLE SAFETY ARGUMENT.  Writing one partition onto a
    card is only correct if the rest of the card is already the rest of this
    image, and the cheap way to know that is to compare the things that
    identify it AND CANNOT DRIFT: the MBR (the table and the disk
    signature), every EBR sector (the logical chain), and the ext4
    superblock of every GAMES tree - UUID, block counts and checksum seed,
    which two different builds never share, on partitions the machine mounts
    read-only and so never writes.

    EVERYTHING THE MACHINE OWNS IS LEFT OUT (see :data:`_MACHINE_OWNED`),
    and that is not a weakening: a range that differs on a card which IS the
    right card does not prove anything, it just refuses.  p1 is the trap -
    it is FAT, and FAT is rewritten by being mounted.
    """
    with open(image_path, "rb") as f:
        def read_at(lba):
            f.seek(lba * 512)
            return f.read(512)

        mbr = read_at(0)
        prim = _mbr_primaries(mbr)
        if not prim:
            raise FlashError(
                "%s does not start with a partition table, so there is no "
                "menu partition to write. Flash the whole image instead."
                % os.path.basename(image_path))
        rootfs = [p for p in prim if p[0] == _ROOTFS_INDEX]
        if not rootfs or rootfs[0][1] != 0x83:
            raise FlashError(
                "%s has no Linux rootfs as its second partition, so it is "
                "not a Stern card image. Flash the whole image instead."
                % os.path.basename(image_path))
        _i, _t, r_lba, r_count = rootfs[0]
        prove = [(0, 512, "the card's partition table")]
        for idx, ptype, lba, _count in prim:
            if idx == _ROOTFS_INDEX:
                continue            # it is what we are about to overwrite
            if ptype == 0x0F:       # the extended container: walk its chain
                for n, (ebr, ltype, lstart, _lc) in enumerate(
                        _ebr_chain(read_at, lba)):
                    part = 5 + n
                    prove.append((ebr * 512, 512,
                                  "the card's p%d table entry" % part))
                    if ltype == 0x83 and part not in _MACHINE_OWNED:
                        # NAMED FOR WHAT IT IS TO A PERSON.  "p7's filesystem
                        # does not match" is true and useless; what it means
                        # is that the games on the card are not the games in
                        # this image, which is the one thing worth knowing.
                        prove.append((lstart * 512, _IDENT_BYTES,
                                      "the games on p%d" % part))
                continue
            if (idx + 1) in _MACHINE_OWNED or ptype != 0x83:
                continue        # p1 is FAT and the machine writes it
            prove.append((lba * 512, _IDENT_BYTES,
                          "the games on p%d" % (idx + 1)))
    return {"write": [(r_lba * 512, r_count * 512, "the menu partition (p2)")],
            "prove": prove, "sector": 512}


def _ranges_match(dev, src, ranges, log=None):
    """Every range the same on the device and in the image?  -> (ok, what).

    Reads the DEVICE through the aligned reader, so a 4096-sector card is
    read the way it insists on being read."""
    for off, length, what in ranges:
        want = _read_file_range(src, off, length)
        got = dev._aligned_read(off, len(want))
        if got[:len(want)] != want:
            return False, what
        if log is not None:
            log("  %s matches" % what, "info")
    return True, ""


def _read_file_range(f, off, length):
    f.seek(off)
    return f.read(length)


def flash_menu_to_device(image_path, device_path, *, log=None, progress=None,
                         cancel=None, verify=True, on_verify_start=None):
    """Write ONLY the menu partition of *image_path* onto *device_path*.

    For the card you already flashed from this image and have since changed
    the MENU of - new titles, a different countdown, other sounds.  An Apply
    rewrites p2 of the image in seconds; this puts that one partition on the
    card, which is 350 MB rather than the whole image (David, watching a
    14.72 GB write crawl at 6 MB/s: "yes, build the menu-only write").

    IT REFUSES A CARD THAT IS NOT THAT CARD.  Every range
    :func:`menu_write_plan` calls for is compared first, and a single
    mismatch raises :class:`FlashError` naming what differed - writing one
    partition of an image onto a card holding a different one makes a card
    that boots a menu into games that are not there.

    It also LEAVES /data AND /dump ALONE, which a whole-image flash cannot:
    the machine's settings, its NVRAM and its scores stay as the machine
    left them.  Returns the bytes written.
    """
    if not os.path.isfile(image_path):
        raise FlashError("Image file not found: %s" % image_path)
    plan = menu_write_plan(image_path)
    dev_size = device_size(device_path)
    need = max(off + length for off, length, _w in plan["write"])
    if dev_size is not None and dev_size < need:
        raise FlashError(
            "The card (%s) is smaller than this image's menu partition needs "
            "(%s). It cannot be the card this image was flashed onto."
            % (format_size(dev_size), format_size(need)))
    if log is not None:
        log("Menu-only write: checking that this card was flashed from %s"
            % os.path.basename(image_path), "info")
    written = 0
    with _disk_offline_for_write(device_path, log), \
            _locked_volumes(device_path, log):
        with open(image_path, "rb") as src:
            with RawDeviceFile(device_path, writable=True) as dev:
                ok, what = _ranges_match(dev, src, plan["prove"], log=log)
                if not ok:
                    raise FlashError(
                        "This card does not hold the images in %s: %s does "
                        "not match, so writing only the menu would leave a "
                        "menu pointing at games that are not there. Nothing "
                        "was written. Untick 'Only the boot menu' and write "
                        "the whole image - or put in the card this image was "
                        "flashed onto."
                        % (os.path.basename(image_path), what))
                if log is not None:
                    log("This is that card. Writing the menu partition only "
                        "- /data and /dump (the machine's settings and "
                        "scores) are left as they are.", "info")
                if cancel is not None and cancel():
                    raise FlashCancelled("Cancelled before anything was "
                                         "written.")
                total = sum(length for _o, length, _w in plan["write"])
                rate = []
                for off, length, _what in plan["write"]:
                    src.seek(off)
                    dev.seek(off)
                    done = 0
                    while done < length:
                        if cancel is not None and cancel():
                            raise FlashCancelled(
                                "Menu write cancelled after %d of %d bytes - "
                                "the card's menu is half written and must be "
                                "written again." % (written, total))
                        buf = src.read(min(_FLASH_CHUNK, length - done))
                        if not buf:
                            break
                        dev.write(buf)
                        done += len(buf)
                        written += len(buf)
                        if progress is not None:
                            progress(written, total,
                                     "Writing the boot menu onto the card\u2026"
                                     + _rate_note(rate, written, total))
                dev.flush()
        if verify:
            if on_verify_start is not None:
                on_verify_start()
            _verify_menu_readback(device_path, image_path, plan,
                                  log=log, progress=progress, cancel=cancel)
    if log is not None:
        log("Menu written: %s onto %s." % (format_size(written), device_path),
            "success")
    return written


def _verify_menu_readback(device_path, image_path, plan, *, log=None,
                          progress=None, cancel=None):
    """Read the menu partition back and confirm it matches the image.

    The same reasoning as the whole-image verify: a raw write has no other
    integrity check, and a card whose menu half landed boots into nothing."""
    if log is not None:
        log("Verifying the menu partition (reading it back)\u2026", "info")
    total = sum(length for _o, length, _w in plan["write"])
    checked = 0
    rate = []
    with RawDeviceFile(device_path, writable=False) as dev, \
            open(image_path, "rb") as src:
        for off, length, _what in plan["write"]:
            src.seek(off)
            done = 0
            while done < length:
                if cancel is not None and cancel():
                    raise FlashCancelled(
                        "Verify cancelled after %d of %d bytes." % (checked,
                                                                    total))
                exp = src.read(min(_VERIFY_CHUNK, length - done))
                if not exp:
                    break
                got = dev._aligned_read(off + done, len(exp))
                if got[:len(exp)] != exp:
                    raise FlashError(
                        "The card does not match the image at byte %s of the "
                        "menu partition - the write did not land. Try again, "
                        "or write the whole image."
                        % f"{off + done:,}")
                done += len(exp)
                checked += len(exp)
                if progress is not None:
                    progress(checked, total, "Verifying the boot menu\u2026"
                             + _rate_note(rate, checked, total))
    if log is not None:
        log("Menu verified: it matches the image byte-for-byte.", "success")


def _verify_flash_readback(device_path, image_path, img_size, *, log=None,
                           progress=None, cancel=None):
    """Read the just-flashed card back and compare it to the source image.

    Raises :class:`FlashError` at the first mismatch (the card is bad -- a
    flaky write/card/reader); the caller must NOT let such a card reach the
    machine.  Honours ``cancel``.
    """
    if log is not None:
        log("Verifying the flashed card (reading it back)…", "info")
    checked = 0
    rate = []
    with RawDeviceFile(device_path, writable=False) as dev, \
            open(image_path, "rb") as src:
        while checked < img_size:
            if cancel is not None and cancel():
                raise FlashCancelled(
                    "Verify cancelled after %d of %d bytes." % (
                        checked, img_size))
            want = min(_VERIFY_CHUNK, img_size - checked)
            exp = src.read(want)
            if not exp:
                break
            got = dev._aligned_read(checked, len(exp))
            if got != exp:
                off = next((i for i in range(min(len(got), len(exp)))
                            if got[i] != exp[i]), min(len(got), len(exp)))
                raise FlashError(
                    "The card does not match the image after flashing (first "
                    "difference at byte %s). The write didn't land correctly "
                    "-- usually a flaky SD card or card reader. Flash again, "
                    "or use a different card / reader. Do NOT install this "
                    "card on the machine: a partially-written installer can "
                    "fail with a SHELL ERROR or leave the machine unbootable."
                    % f"{checked + off:,}")
            checked += len(exp)
            if progress is not None:
                progress(checked, img_size, "Verifying flashed card…"
                         + _rate_note(rate, checked, img_size))
    if log is not None:
        log("Card verified: it matches the image byte-for-byte.", "success")
