#!/usr/bin/env python3
"""hexreg.py - read the LIVE game's node-board hex-image expectations.

    wsl -u root -e python3 $RIG/hexreg.py            # find the game itself
    wsl -u root -e python3 $RIG/hexreg.py <pid>

READ-ONLY: /proc/<pid>/mem only, no ptrace stop, no writes. Root because
/proc mem access needs it; the run is not disturbed.

WHAT IT ANSWERS. The game grades every node board's claimed identity against
its <type>-<class>-*.hex image, through 0x5a8644's TWO paths: the parsed
HEADER (the encrypted 06/07 records) when the image node's [+32] selector is
set - true on both node4 images - and the DECRYPTED buffer (variant at flash
0x1008, version at 0x1009..0x100b) otherwise. This prints the value the game
will actually grade against, marked (header)/(image); the two DISAGREE on
node4, whose buffer bytes are not a version block at all - the misread that
kept slot 4 at status 7 = Checksum. The hex files on the card are
ENCRYPTED (record types 06/07 carry the key material), so the only place those
bytes exist in the clear is the running game's own hex-image registry - a
linked list keyed by CRC32(type name) and LPC class. This walks the process's
memory BY SHAPE (the per-title list head is unknowable statically; godzilla
pro's 0x7e1b98 is a literal that segfaulted stranger_things, item 52) and
prints every image's type, class, variant and version.

WHY IT EXISTS, 2026-08-22: nbdir.py must GUESS a variant it cannot read out
of an encrypted image, godzilla_le's tmc5041node guess (0x01) disagreed with
the decrypted truth (0x0d), and that one byte put every Heisei boot through
~80 s of failed "UPDATING NODE BOARD RUNTIME" retries on node 10. This tool
read the truth off the live game in one pass. hwshim's nb_hexreg_answer() now
does the same scan in-process and corrects its claims at runtime; this is the
desk-side twin for measuring a new title without instrumenting a run.

THE SHAPE (hwshim.c nb_dump_hexlist annotations; w = u32 at node offset 4*i):
    w[0]  CRC32 of the type name (zlib polynomial - verified against the
          keys hwshim recorded: pinnode dcc6afb2, ws2812node d2a9be05,
          node4 f585d1cf)
    w[1]  LPC class 1..7
    w[2]  char* path ending .hex          (guest pointer)
    w[7]  decrypted image buffer, indexed by ABSOLUTE flash address
    w[10] image-kind flag == 1 (min addr == 0x1000)
    w[11] min flash address == 0x1000
    w[12] span > 11

qemu-user maps guest VA -> host VA + 0x10000 (guest_base; see
reference_spike2_qemu_guest_base), so host reads add that bias and printed
addresses subtract it back to the guest's own numbers.
"""
import os
import re
import struct
import sys
import zlib

GUEST_BASE = 0x10000

#: The game's own 43-entry type table carries these (nbdir.TYPE_NAMES); a
#: registry node's key must CRC-match one or the candidate is skipped.
TYPES = [b"pinnode", b"ws2812pinnode", b"ws2812node", b"coil4_lednode",
         b"coil4node", b"lcdnode", b"hdminode", b"hdmi_ws2812node", b"afnode",
         b"magsensornode", b"node4", b"tmc2590node", b"tmc5041node",
         b"netbridge"]
CRC = {zlib.crc32(t) & 0xffffffff: t.decode() for t in TYPES}


def find_game_pid():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % pid) as f:
                if f.read().strip() == "game":
                    return pid
        except OSError:
            continue
    return None


def read_mem(mem, host_addr, n):
    try:
        mem.seek(host_addr)
        return mem.read(n)
    except (OSError, ValueError, OverflowError):
        return b""


def main(argv):
    pid = argv[1] if len(argv) > 1 else find_game_pid()
    if not pid:
        print("no running game found (and no pid given)", file=sys.stderr)
        return 2
    maps = []
    with open("/proc/%s/maps" % pid) as f:
        for line in f:
            m = re.match(r"([0-9a-f]+)-([0-9a-f]+) rw", line)
            if not m:
                continue
            lo, hi = int(m.group(1), 16), int(m.group(2), 16)
            # guest memory sits below 4G+guest_base in qemu-user's host space;
            # everything above is qemu's own and cannot hold guest pointers
            if lo >= 0x100000000:
                continue
            maps.append((lo, hi))
    found = 0
    with open("/proc/%s/mem" % pid, "rb", buffering=0) as mem:
        for lo, hi in maps:
            if hi - lo > 64 * 1024 * 1024:
                continue
            data = read_mem(mem, lo, hi - lo)
            pos = -4
            while True:
                # w[11] == 0x1000 (min flash address) is the rarest cheap
                # anchor; everything else is checked off its position
                pos = data.find(b"\x00\x10\x00\x00", pos + 4)
                if pos < 0 or pos + 20 > len(data):
                    break
                off = pos - 44                       # w[11] lives at +44
                if off < 0 or off + 64 > len(data) or off % 4:
                    continue
                w = struct.unpack_from("<16I", data, off)
                if w[0] not in CRC or not 1 <= w[1] <= 7:
                    continue
                if w[10] != 1 or w[12] <= 11:
                    continue
                path = read_mem(mem, w[2] + GUEST_BASE, 256).split(b"\0")[0]
                if not path.endswith(b".hex"):
                    continue
                # ★ TWO VERSION SOURCES, mirroring the game's reader 0x5a8644:
                # with the node's [+32] selector SET (w[8], true on both node4
                # images) it grades against the parsed HEADER - maj/min/patch
                # at node+16/18/20, variant at node+26, decoded from the
                # encrypted 06/07 records - and only otherwise against the
                # decrypted buffer at flash 0x1008. Reading only the buffer is
                # the misread that had node 4 claiming 124.107.0/0x98 against
                # a header saying 1.35.0/0x03 (status 7 on every boot).
                raw = data[off:off + 64]
                if w[8]:
                    src, var = "header", raw[26]
                    v = (raw[16], raw[18], raw[20])
                else:
                    buf = read_mem(mem, w[7] + GUEST_BASE + w[11] + 8, 4)
                    if len(buf) < 4:
                        continue
                    src, var = "image", buf[0]
                    v = (buf[1], buf[2], buf[3])
                found += 1
                print("type=%-16s class=%u variant=0x%02x VERSION=%u.%u.%u  "
                      "(%s)  guest=0x%08x  %s"
                      % (CRC[w[0]], w[1], var, v[0], v[1], v[2], src,
                         lo - GUEST_BASE + off, path.decode()))
    print("nodes found: %d" % found)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
