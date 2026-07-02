r"""Read-only diagnostics for a flashed CGC installer card.

The on-machine installer (``pinstall``, on the card's P2 at
``/home/ubuntu/pinstall/``) forks exactly one shell command --
``./dcfldd if=/data/emmc.img of=/dev/mmcblk1 sizeprobe=if`` -- and shows
"SHELL ERROR" on the displays when that fork fails (nonzero exit, a
pinstall-side timeout, or a signal).  dcfldd's stderr -- the progress
ticks AND any error line -- is captured to ``procstat.txt`` next to the
binary, so a failed install leaves its reason readable on the card.

Getting that file off an ext4 partition is beyond most users
(``wsl --mount`` can't even attach the typical USB SD reader -- it
enumerates as removable media), so this module reads it back through the
app's own raw-device layer: MBR -> pure-Python ext4 walk -> report
string.  No WSL, no mounting, read-only.

Works on the physical card (``\\.\PHYSICALDRIVEn``, needs Administrator)
or on a whole-card ``.img`` file (how the tests drive it).
"""

import datetime
import re
import struct

from ...core.rawdevice import RawDeviceFile
# Pure-Python ext4 reader; lives in the Stern plugin (Direct-SD extract)
# but is generic -- same cross-plugin reuse as pipeline.py's williams
# import.
from ..stern.ext4 import Ext4Error, Ext4Reader

PINSTALL_DIR = "/home/ubuntu/pinstall"
PROCSTAT = "procstat.txt"

# procstat.txt progress tick, e.g. "[37% of 3472Mb]".
_PROGRESS_RE = re.compile(r"\[(\d+)% of (\d+)Mb\]")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _mbr_partitions(sector0):
    """Parse the 4 primary MBR entries out of the first sector (bytes)."""
    if sector0[510:512] != b"\x55\xaa":
        raise ValueError("not an MBR-partitioned card/image")
    parts = []
    for i in range(4):
        entry = sector0[0x1BE + i * 16:0x1BE + (i + 1) * 16]
        ptype = entry[4]
        start_lba, sectors = struct.unpack("<II", entry[8:16])
        if ptype == 0 or sectors == 0:
            continue
        parts.append({
            "index": i + 1, "type": ptype,
            "start_bytes": start_lba * 512,
            "size_bytes": sectors * 512,
        })
    return parts


def _resolve(reader, path):
    """Walk *path* from the root directory; inode number or None."""
    ino = 2
    for part in path.strip("/").split("/"):
        found = None
        for name, child, _ftype in reader._iter_dir(reader.read_inode(ino)):
            if name == part:
                found = child
                break
        if found is None:
            return None
        ino = found
    return ino


def _inode_mtime(reader, ino):
    """The inode's raw mtime as a UTC datetime (ext2 epoch field)."""
    group = (ino - 1) // reader.inodes_per_group
    index = (ino - 1) % reader.inodes_per_group
    it_block = reader._group_desc_inode_table(group)
    off = it_block * reader.block_size + index * reader.inode_size
    raw = reader._read(off, reader.inode_size)
    secs = struct.unpack_from("<I", raw, 0x10)[0]
    return datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)


def _read_span(reader, inode, off, n):
    """Bytes ``[off, off+n)`` of a file, zero-filling sparse holes (a
    debugfs-written emmc.img is sparse where the payload was all zeros)."""
    bs = reader.block_size
    n = max(0, min(n, inode["size"] - off))
    out = bytearray(n)
    for log, phys, cnt in reader._runs(inode):
        run_start = log * bs
        lo = max(run_start, off)
        hi = min(run_start + cnt * bs, off + n)
        if lo >= hi:
            continue
        data = reader._read(phys * bs + (lo - run_start), hi - lo)
        out[lo - off:lo - off + len(data)] = data
    return bytes(out)


def _fmt_when(dt):
    return dt.strftime("%Y-%m-%d %H:%M UTC")


# A real CGC install payload (emmc.img) is 2-4 GB.  Anything under this is an
# empty or truncated payload the installer can't copy.
MIN_PLAUSIBLE_EMMC = 256 * 1024 * 1024


def _assess_payload_size(size, mtime, now):
    """Return a problem string if the emmc.img payload is implausibly small,
    else ``None``.  Pure (no I/O) so the verdict wording is unit-testable.

    A payload dated well before ``now`` was carried straight through from the
    source .img (our build stamps a fresh mtime), so a bad payload came in
    with the original image; a fresh mtime instead points at the build itself.
    """
    if size >= MIN_PLAUSIBLE_EMMC:
        return None
    carried = mtime < now - datetime.timedelta(days=1)
    origin = (
        f"The payload's timestamp ({_fmt_when(mtime)}) predates this build, "
        "so it was carried straight through from the source .img -- the "
        "ORIGINAL image you built/flashed from already had an empty emmc.img."
        if carried else
        "The payload was written empty during the build/flash, so the image "
        "you flashed never had a real payload.")
    return (
        f"The install payload /emmc.img is only {size:,} bytes (should be "
        "~2-4 GB). This empty/truncated payload IS the SHELL ERROR: the "
        "machine's copy step has nothing to write. " + origin + " Re-check "
        "the source .img (run these diagnostics on it, or re-image the "
        "installer), rebuild on v0.34.1+ (which now aborts a build with an "
        "empty payload), and re-flash.")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def diagnose_installer_card(path, log=None):
    """Build a plain-text diagnostic report for a CGC installer card.

    Read-only.  Raises ``ValueError`` when the target isn't recognisable
    as a CGC installer card (so the GUI can show a clear message).
    """
    def _log(msg):
        if log:
            log(msg)

    lines = []
    say = lines.append
    # Critical findings, surfaced again as a loud VERDICT at the end so the
    # user isn't left to spot a 0-byte payload buried mid-report.
    problems = []

    _log("Opening card (read-only)...")
    with RawDeviceFile(path, writable=False) as dev:
        say("CGC installer card diagnostics")
        say(f"  target: {path}")
        if dev.size:
            say(f"  size:   {dev.size:,} bytes ({dev.size / 10**9:.2f} GB)")
        say("")

        parts = _mbr_partitions(dev._aligned_read(0, 512))
        linux = [p for p in parts if p["type"] == 0x83]
        if len(linux) < 2:
            raise ValueError(
                "This doesn't look like a CGC installer card (expected two "
                "Linux partitions; found %d)." % len(linux))
        for p in parts:
            say(f"  P{p['index']}: type 0x{p['type']:02x}  "
                f"{p['size_bytes'] / 2**30:.2f} GiB")
        say("")

        # P2 = installer rootfs (lowest-LBA 0x83); P3 = data (highest).
        rootfs = min(linux, key=lambda p: p["start_bytes"])
        data = max(linux, key=lambda p: p["start_bytes"])

        # ---- installer rootfs: pinstall dir + procstat.txt ----------------
        _log("Reading installer rootfs (P%d)..." % rootfs["index"])
        r2 = Ext4Reader(dev, rootfs["start_bytes"], rootfs["size_bytes"])
        pin_ino = _resolve(r2, PINSTALL_DIR)
        if pin_ino is None:
            raise ValueError(
                f"No {PINSTALL_DIR} directory on P{rootfs['index']} -- not a "
                f"CGC installer card (or a game/backup card, not an "
                f"installer).")

        say(f"[P{rootfs['index']}] installer files ({PINSTALL_DIR}):")
        entries = {}
        for name, child, _ft in r2._iter_dir(r2.read_inode(pin_ino)):
            if name in (".", ".."):
                continue
            node = r2.read_inode(child)
            if node["mode"] & 0xF000 == 0x8000:
                entries[name] = (child, node)
                say(f"  {name}  ({node['size']:,} bytes, modified "
                    f"{_fmt_when(_inode_mtime(r2, child))})")
        say("")

        for cfg in ("config.dat", "package.dat"):
            if cfg in entries:
                text = r2.read_file_bytes(entries[cfg][1]).decode(
                    "utf-8", "replace")
                wanted = ("GAME_NAME", "INSTALL_DEST", "AUTOSTART",
                          "PACKAGE_FILE", "VERSION")
                got = [ln.strip() for ln in text.splitlines()
                       if ln.strip() and not ln.strip().startswith("#")
                       and ln.split("=")[0].strip() in wanted]
                if got:
                    say(f"  {cfg}: " + "; ".join(got))
        say("")

        say(f"procstat.txt -- the installer's copy log (dcfldd output "
            f"from the LAST install attempt):")
        if PROCSTAT not in entries:
            say("  MISSING -- the copy step never started on this card.")
        else:
            ino, node = entries[PROCSTAT]
            when = _inode_mtime(r2, ino)
            # Compare against the FACTORY files only.  procstat.txt and
            # readonly.chk are both (re)written on every install attempt, so
            # including readonly.chk in the baseline made a genuine fresh
            # attempt look "same age as factory" (it shares readonly.chk's
            # timestamp).  Exclude both.
            _restamped = {PROCSTAT, "readonly.chk"}
            others = [_inode_mtime(r2, i)
                      for n, (i, _nd) in entries.items()
                      if n not in _restamped]
            fresh = others and when > max(others) + datetime.timedelta(hours=1)
            say(f"  {node['size']:,} bytes, written {_fmt_when(when)}")
            if node["size"] == 0 and fresh:
                say("  => 0 bytes but freshly written: the machine STARTED "
                    "the copy (dcfldd created this log) but it produced no "
                    "output and failed immediately -- classic sign the "
                    "source payload (emmc.img below) is empty or unreadable.")
                problems.append(
                    "The installer's copy log (procstat.txt) is 0 bytes but "
                    "dated to a real attempt -- dcfldd ran and failed with "
                    "nothing to copy.")
            elif fresh:
                say("  => newer than the factory files: this log is from a "
                    "real install attempt on the machine.")
            else:
                say("  => same age as the factory files: this is CGC's "
                    "leftover mastering log, NOT from your machine. Either "
                    "no install was attempted with this card, or it failed "
                    "before the copy step ever started.")
            text = r2.read_file_bytes(node).decode("utf-8", "replace")
            ticks = _PROGRESS_RE.findall(text)
            if ticks:
                pct, total = ticks[-1]
                say(f"  last progress tick: {pct}% of {total} MB")
            if "records out" in text:
                say("  copy ran to completion (records in/out present).")
            say("  ---- final lines ----")
            tail = text.replace("\r", "\n")[-1200:]
            body = [t for t in tail.split("\n") if t.strip()][-12:]
            if body:
                for ln in body:
                    say(f"  | {ln.strip()}")
            else:
                say("  | (empty)")
        say("")

        # ---- data partition: the payload dcfldd copies ---------------------
        _log("Checking install payload (P%d)..." % data["index"])
        r3 = Ext4Reader(dev, data["start_bytes"], data["size_bytes"])
        say(f"[P{data['index']}] install payload:")
        emmc_ino = _resolve(r3, "/emmc.img")
        if emmc_ino is None:
            say("  /emmc.img: MISSING -- the installer has nothing to copy; "
                "this alone causes SHELL ERROR immediately after the "
                "countdown.")
            problems.append(
                "The install payload /emmc.img is MISSING from the card. The "
                "installer's copy step has no source file, so it fails "
                "instantly (SHELL ERROR).")
        else:
            node = r3.read_inode(emmc_ino)
            mt = _inode_mtime(r3, emmc_ino)
            say(f"  /emmc.img: present, {node['size']:,} bytes, modified "
                f"{_fmt_when(mt)}")
            bad = _assess_payload_size(
                node["size"], mt,
                datetime.datetime.now(datetime.timezone.utc))
            if bad is not None:
                say(f"  *** PROBLEM: this payload is far too small (a real "
                    f"Pulp Fiction payload is ~3.6 GB). An empty or truncated "
                    f"emmc.img is exactly what makes the machine SHELL ERROR "
                    f"-- dcfldd has nothing to copy.")
                problems.append(bad)
            # Force real device reads over the head and tail of the payload
            # (a quick unreadable-card smoke test; NOT a full surface scan).
            if node["size"] > 0:
                try:
                    head = _read_span(r3, node, 0, 64 * 1024)
                    ok_mbr = head[510:512] == b"\x55\xaa"
                    _read_span(r3, node, max(0, node["size"] - 64 * 1024),
                               64 * 1024)
                    say("  head/tail read: OK" +
                        ("" if ok_mbr else "  (WARNING: payload has no MBR "
                                           "signature -- corrupt content?)"))
                except (Ext4Error, OSError) as e:
                    say(f"  head/tail read FAILED: {e} -- the card could not "
                        f"be read where the payload lives; suspect the card "
                        f"itself.")
                    problems.append(
                        "The card could not be read where the payload lives "
                        f"({e}) -- suspect a failing card.")
    say("")

    # ---- verdict -------------------------------------------------------
    say("=" * 60)
    if problems:
        say("VERDICT: problem(s) found")
        for p in problems:
            say("")
            for i, chunk in enumerate(_wrap(p, 58)):
                say(("  * " if i == 0 else "    ") + chunk)
    else:
        say("VERDICT: no obvious problem found on this card. The payload is "
            "present and readable. If the machine still SHELL ERRORs, note "
            "how long after the countdown it happens and re-run this after "
            "the next attempt.")
    say("=" * 60)
    say("")
    say(f"(report generated {_fmt_when(datetime.datetime.now(datetime.timezone.utc))}; "
        f"nothing on the card was modified)")
    _log("Done.")
    return "\n".join(lines)


def _wrap(text, width):
    """Tiny word-wrap for the verdict block (no textwrap import needed)."""
    words = text.split()
    out, line = [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out or [""]
