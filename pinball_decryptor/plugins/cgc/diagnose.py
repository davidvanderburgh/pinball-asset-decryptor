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


# ---------------------------------------------------------------------------
# ext4 journal (jbd2) inspection
# ---------------------------------------------------------------------------
# The needs_recovery flag alone can't say WHO armed the journal: CGC's
# factory (stale 2024 transactions that revert a modded build's debugfs
# edits at first mount -- the proven SHELL ERROR mechanism) or a mount that
# happened AFTER the build (the machine itself, or a Windows ext4 driver
# like Paragon extFS writing to the card behind the user's back).  Dating
# the journal's pending commit blocks tells them apart.
#
# jbd2 on-disk structures are BIG-endian.

_JBD2_MAGIC = 0xC03B3998
_JBD2_COMMIT_BLOCK = 2
_JBD2_SUPERBLOCK_TYPES = (3, 4)  # v1 / v2


def _parse_journal_sb(buf):
    """Parse a jbd2 journal superblock; dict or ``None`` when it isn't one.

    Header: h_magic @0x00, h_blocktype @0x04; then s_blocksize @0x0C,
    s_maxlen @0x10, s_first @0x14, s_sequence @0x18, s_start @0x1C
    (``s_start == 0`` means the journal is empty -- nothing to replay).
    """
    if len(buf) < 0x20:
        return None
    magic, btype = struct.unpack_from(">II", buf, 0)
    if magic != _JBD2_MAGIC or btype not in _JBD2_SUPERBLOCK_TYPES:
        return None
    bs, maxlen, first, seq, start = struct.unpack_from(">5I", buf, 0x0C)
    return {"blocksize": bs, "maxlen": maxlen, "first": first,
            "sequence": seq, "start": start}


def _pending_commit_times(blocks, sequence):
    """Commit timestamps of the transactions a mount would still replay.

    ``blocks`` yields raw journal blocks.  A commit block (h_blocktype 2)
    whose h_sequence is >= the journal superblock's s_sequence belongs to a
    PENDING transaction; already-replayed history keeps smaller sequence
    numbers.  Journalled data blocks can never alias a control block (jbd2
    escapes any data block that starts with its magic), so a plain magic +
    blocktype match is safe.  h_commit_sec is a be64 @0x30.
    """
    out = []
    for blk in blocks:
        if len(blk) < 0x38:
            continue
        magic, btype, seq = struct.unpack_from(">III", blk, 0)
        if magic != _JBD2_MAGIC or btype != _JBD2_COMMIT_BLOCK:
            continue
        if seq < sequence:
            continue
        secs = struct.unpack_from(">Q", blk, 0x30)[0]
        if 10 ** 9 < secs < 2 ** 32:  # plausible: 2001..2106
            out.append(datetime.datetime.fromtimestamp(
                secs, datetime.timezone.utc))
    return out


def _journal_pending_commits(reader, sb):
    """Count + date the armed journal's pending transactions.

    Returns ``(count, newest_commit_datetime)`` -- ``(0, None)`` when the
    journal is armed but empty -- or ``None`` when the journal can't be
    read at all (never fail the whole diagnosis over it).
    """
    try:
        j_inum = struct.unpack_from("<I", sb, 0xE0)[0]  # s_journal_inum
        if not j_inum:
            return None
        jnode = reader.read_inode(j_inum)
        jsb = _parse_journal_sb(_read_span(reader, jnode, 0, 1024))
        if jsb is None:
            return None
        if jsb["start"] == 0:
            return (0, None)
        bs = jsb["blocksize"] or reader.block_size
        if not 1024 <= bs <= 65536 or bs & (bs - 1):
            return None
        total = min(jsb["maxlen"] * bs, jnode["size"], 512 * 2 ** 20)
        commits = []
        step = 4 * 2 ** 20  # a multiple of any jbd2 block size
        for off in range(0, total, step):
            data = _read_span(reader, jnode, off, min(step, total - off))
            commits.extend(_pending_commit_times(
                (data[i:i + bs] for i in range(0, len(data), bs)),
                jsb["sequence"]))
        return (len(commits), max(commits) if commits else None)
    except (Ext4Error, OSError, ValueError, struct.error):
        return None


def _armed_journal_problem(pending, payload_mtime):
    """Word the armed-journal + fresh-payload verdict.  Pure (unit-testable).

    ``pending`` is :func:`_journal_pending_commits`' result.  Returns the
    problem string, or ``None`` when the armed flag isn't actually a
    problem (empty journal: the machine's mount just clears it).
    """
    base = (
        "This card carries a modified build (payload written "
        f"{_fmt_when(payload_mtime)}) but the data partition's ext4 journal "
        "is still armed (needs_recovery). ")
    tail_stale = (
        "At its first mount the machine replays them OVER the "
        "modifications and reverts the payload to a deleted 0-byte inode "
        "-- the install then fails with SHELL ERROR. Rebuild this image "
        "with v0.36.0 or newer (which retires the journal during the "
        "build) and re-flash.")
    if pending is None:
        return base + (
            "Its pending transactions could not be read to date them; if "
            "they are the factory's stale transactions, " + tail_stale)
    count, newest = pending
    if count == 0:
        return None
    if newest < payload_mtime:
        return base + (
            f"Its {count} pending transaction(s) were committed "
            f"{_fmt_when(newest)} -- BEFORE this build was written: these "
            "are the stale factory transactions. " + tail_stale)
    return base + (
        f"Its {count} pending transaction(s) were committed "
        f"{_fmt_when(newest)} -- AFTER this build was written, so these "
        "are NOT the stale factory transactions: something mounted this "
        "partition after the image was built. If this card has been in a "
        "machine since it was flashed, the machine's own mount did this "
        "and it is normal aftermath, not the factory-revert failure. If "
        "it has NOT been in a machine, something on this PC is mounting "
        "and writing to the card after flashing (typically a Windows ext4 "
        "driver such as Paragon extFS or DiskGenius). Either way, check "
        "the image itself: run these diagnostics on the .img FILE you "
        "flashed (the \"Image file...\" button, no Administrator needed). "
        "If the file reports a clean journal, the image is good -- "
        "re-flash it and re-run this diagnostic before anything mounts "
        "the card.")


# A real CGC install payload (emmc.img) is 2-4 GB.  Anything under this is an
# empty or truncated payload the installer can't copy.
MIN_PLAUSIBLE_EMMC = 256 * 1024 * 1024


def _assess_payload_size(size, mtime, now):
    """Return a problem string if the emmc.img payload is implausibly small,
    else ``None``.  Pure (no I/O) so the verdict wording is unit-testable.

    A payload dated well before ``now`` on a card that has been in a machine
    is the machine's own boot reverting a modded build: installers built
    before v0.36.0 shipped the factory's stale ext4 journal still armed, and
    the kernel's journal replay at first mount clobbered the build's debugfs
    edits, reverting /emmc.img to a deleted 0-byte factory inode (dated
    2023-06-28 on Pulp Fiction -- proven on two real machines).  A fresh
    mtime instead points at the build/flash itself.
    """
    if size >= MIN_PLAUSIBLE_EMMC:
        return None
    carried = mtime < now - datetime.timedelta(days=1)
    origin = (
        f"The payload's timestamp ({_fmt_when(mtime)}) predates this build. "
        "If this card has been in a machine, the machine did this: builds "
        "made before v0.36.0 left the factory's stale ext4 journal armed, "
        "and the machine's first mount replayed it OVER the build's "
        "modifications, reverting the payload to a deleted 0-byte factory "
        "inode. Rebuild with v0.36.0+ and re-flash. If this image was never "
        "in a machine, the ORIGINAL source .img may itself carry an empty "
        "payload -- run these diagnostics on that exact source .img file."
        if carried else
        "The payload was written empty during the build/flash, so the image "
        "you flashed never had a real payload. Re-check the source .img "
        "(run these diagnostics on it, or re-image the installer), rebuild "
        "on v0.34.1+ (which aborts a build with an empty payload), and "
        "re-flash.")
    return (
        f"The install payload /emmc.img is only {size:,} bytes (should be "
        "~2-4 GB). This empty/truncated payload IS the SHELL ERROR: the "
        "machine's copy step has nothing to write. " + origin)


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
        # Journal state.  Stock CGC images ship P3 with the factory's ext4
        # journal still armed (needs_recovery set) -- harmless on a factory
        # card, but fatal on a modded build made before v0.36.0: the
        # machine's first mount replays the stale factory transactions over
        # the build's debugfs edits, reverting /emmc.img to a deleted
        # 0-byte inode (SHELL ERROR).  s_magic @0x38, s_feature_incompat
        # @0x60, EXT3_FEATURE_INCOMPAT_RECOVER = 0x0004.
        sb = dev._aligned_read(data["start_bytes"] + 1024, 1024)
        journal_armed = None
        journal_pending = None  # (count, newest commit) once read
        if sb[0x38:0x3A] == b"\x53\xEF":
            journal_armed = bool(
                struct.unpack("<I", sb[0x60:0x64])[0] & 0x0004)
            say("  ext4 journal: "
                + ("ARMED (needs_recovery -- normal for a stock/factory "
                   "image; fatal for a pre-v0.36.0 modded build)"
                   if journal_armed else "clean"))
            if journal_armed:
                # Date the pending transactions: stale factory ones are the
                # proven payload-revert mechanism, fresh ones just mean
                # something mounted the card after it was written.
                _log("Reading the armed journal's pending transactions...")
                journal_pending = _journal_pending_commits(r3, sb)
                if journal_pending is None:
                    say("    (its pending transactions could not be read, "
                        "so they can't be dated)")
                elif journal_pending[0] == 0:
                    say("    pending transactions: none -- the armed flag "
                        "sits over an empty journal; a mount just clears it")
                else:
                    say(f"    pending transactions: {journal_pending[0]}, "
                        f"newest committed {_fmt_when(journal_pending[1])}")
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
            now = datetime.datetime.now(datetime.timezone.utc)
            bad = _assess_payload_size(node["size"], mt, now)
            if bad is not None:
                say(f"  *** PROBLEM: this payload is far too small (a real "
                    f"Pulp Fiction payload is ~3.6 GB). An empty or truncated "
                    f"emmc.img is exactly what makes the machine SHELL ERROR "
                    f"-- dcfldd has nothing to copy.")
                problems.append(bad)
            elif journal_armed and mt > now - datetime.timedelta(days=30):
                # Healthy-looking payload with a build-fresh mtime BUT the
                # journal is still armed.  Stale factory transactions mean a
                # pre-v0.36.0 modded build that looks perfect now and dies
                # at the machine's first mount; transactions dated AFTER the
                # build mean something merely mounted the card since it was
                # written.  _armed_journal_problem words each case (and
                # clears the empty-journal one).
                bad_journal = _armed_journal_problem(journal_pending, mt)
                if bad_journal is not None:
                    say("  *** PROBLEM: modded build with the journal still "
                        "armed -- see the verdict below.")
                    problems.append(bad_journal)
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
