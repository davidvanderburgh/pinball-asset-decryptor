#!/usr/bin/env python3
"""s3bridge - the Spike 3 netbridge board, answering its host UART (PAD-1090).

On the machine the CPU module talks to the RP2040 "netbridge" board over a
UART (/dev/ttyAMA5). The board's program is on the card -
games/<title>/spike3/netbridge/netbridge.elf, unstripped - and everything this
answers is read off it (uart_host.c's HOSTUART_SendMessage and main.c's
HOST_Update dispatch), the same footing as Spike 2's netbridge.py:

  frame     02 <cmd> <id> <payload...> <sum> 03; cmd..sum add to 0 mod 256
            (unescaped); 0x02/0x03/0x1b inside are sent as 1b <byte|0x80>.
            Replies carry the request's cmd and id.
  0x20      version: [0, 98, 4, adc] - the firmware's own strings "0","98",
            "4" and the board revision its ADC ladder reads (0..10)
  0x30      CRC32 (zlib's) of the board's flash 0x10000100..0x10012b40, i.e.
            of the image it runs. Computed from the card's netbridge.elf, so
            the game sees the image it would flash already there and does not
            run openocd to reflash the board.
  0x25      NODEBUS_Poll: the lowest node address raising a request, 0 for
            none (its binary search moves down on every answer)
  0x27 n    LCD; sub 0 (and 2) answer LCD_GetStatus, one byte
  0x41      a node bus exchange: [node] [n] [n bytes] [reply_len]. The board
            sends the bytes to the node chain and answers reply_len bytes:
            reply_len-1 from the node, then its node status byte - 0x00 for a
            complete reply, 0x04 for a timeout (the rest left 0x55, as the
            board's buffer is). reply_len 0 = a write, no answer.
  0x10..1f  forwarded to the power distribution board (not answered yet)

THE NODE BOARDS behind 0x41 are the title's own: s3nodes.py reads its node
directory and board catalog out of the game program, and each declared node
answers the node bus protocol Spike 2's emulator worked out (the Spike 3 game
sends the very same frames - `81 02 fe 7f 0d` is node 1's identity request on
both). The request is [0x80|node] [n] [payload..., checksum] and the node's
reply is reply_len-2 payload bytes and a checksum that makes them sum to 0:
  fe     the identity - [0, fw maj, min, patch, LE32 MCU part id, LE16 board
         id, variant] - claimed as s3nodes.py derives it (the class, part id
         and variant the title's own <type>-<class>-<ver>.hex grades against)
  f9 00  runtime info; bytes 8..11 the board's part number (catalog x100)
  else   zeros
A node the directory does not declare times out, as an empty address does.

    s3bridge.py DIR [NETBRIDGE_ELF [GAME_ELF]]
        writes DIR/bridge.path (the pty) and DIR/bridge.log
"""
import os
import pty
import select
import struct
import sys
import time
import tty
import zlib

STX, ETX, ESC = 0x02, 0x03, 0x1B
FW_VERSION = (0, 98, 4)          # main.c's version strings, pokemon_le 0.82.0
BOARD_REV = 0                    # what ADC_Update's ladder can report: 0..10
LCD_STATUS = 0
FLASH = (0x10000100, 0x10012B40)  # the range HOST_Update's 0x30 handler CRCs


def flash_crc(elf_path):
    """CRC32 the board computes over its own flash, from its ELF image."""
    d = open(elf_path, "rb").read()
    phoff, = struct.unpack_from("<I", d, 0x1C)
    phsz, phn = struct.unpack_from("<HH", d, 0x2A)
    for i in range(phn):
        t, off, va, pa, fsz, msz, fl, al = struct.unpack_from("<8I", d, phoff + i * phsz)
        if t == 1 and va <= FLASH[0] and FLASH[1] <= va + fsz:
            return zlib.crc32(d[off + FLASH[0] - va: off + FLASH[1] - va]) & 0xFFFFFFFF
    raise ValueError("%s: no load segment covers the flash range" % elf_path)


def frame(cmd, ident, payload=b""):
    body = bytes([cmd, ident]) + bytes(payload)
    body += bytes([(-sum(body)) & 0xFF])
    out = bytearray([STX])
    for b in body:
        out += bytes([ESC, b | 0x80]) if b in (STX, ETX, ESC) else bytes([b])
    out.append(ETX)
    return bytes(out)


class Node:
    """One node board, answering as the title expects its board to."""

    def __init__(self, nid, claim, log):
        self.nid, self.c, self.log, self.said = nid, claim, log, set()

    def __call__(self, data, k):
        """k reply bytes (payload + checksum) for request payload `data`."""
        plen = k - 1
        if plen < 0:
            return None
        p = bytearray(plen)
        cmd = data[0] if data else None
        c = self.c
        if cmd == 0xFE and plen >= 10:
            fw = c["fw"]
            p[0:4] = bytes([0, fw[0], fw[1], fw[2]])
            p[4:8] = struct.pack("<I", c["part"])
            p[8:10] = struct.pack("<H", c["hwid"])
            if plen >= 11:
                p[10] = c["variant"]
            self.once("fe", "node %d claims %s part=0x%08x variant=0x%02x fw=%d.%d.%d (%s)" % (
                self.nid, c["type"], c["part"], c["variant"], fw[0], fw[1], fw[2], c["hex"]))
        elif cmd == 0xF9 and len(data) > 1 and data[1] == 0 and plen >= 12:
            p[8:12] = struct.pack("<I", c["partno"])
            self.once("f9", "node %d reports part %s (%d)" % (self.nid, c["partstr"], c["partno"]))
        return bytes(p) + bytes([(-sum(p)) & 0xFF])

    def once(self, key, msg):
        if key not in self.said:
            self.said.add(key)
            self.log.write("# [node] %s\n" % msg)


class Bridge:
    def __init__(self, crc, log, claims=None):
        self.crc = crc
        self.log = log
        # node address -> model: the title's declared node boards
        self.nodes = {nid: Node(nid, c, log) for nid, c in (claims or {}).items()}
        self.counts = {}

    def attention(self):
        """The lowest node address with something to report, 0 for none."""
        return 0

    def node_exchange(self, node, data, reply_len):
        """reply_len bytes for a 0x41 exchange (reply_len-1 from the node,
        then the board's status byte)."""
        model = self.nodes.get(node & 0x3F)
        if model is not None:
            r = model(data, reply_len - 1)
            if r is not None:
                return bytes(r[:reply_len - 1]).ljust(reply_len - 1, b"\x55") + b"\x00"
        return b"\x55" * (reply_len - 1) + b"\x04"

    def handle(self, cmd, ident, p):
        self.counts[cmd] = self.counts.get(cmd, 0) + 1
        if cmd == 0x20:
            return frame(0x20, ident, bytes(FW_VERSION) + bytes([BOARD_REV & 0xFF]))
        if cmd == 0x30:
            return frame(0x30, ident, struct.pack("<I", self.crc))
        if cmd == 0x25:
            # NODEBUS_Poll's binary search goes DOWN on every answer: it
            # returns the LOWEST node address raising a request (0: none) -
            # the attention poll, not a count. No node wants service here.
            return frame(0x25, ident, bytes([self.attention()]))
        if cmd == 0x27:
            if p and p[0] in (0, 2):
                return frame(0x27, ident, bytes([LCD_STATUS]))
            return None
        if cmd == 0x41:
            if len(p) < 3:
                return None
            n = p[1]
            if len(p) < n + 3:
                return None
            reply_len = p[n + 2]
            if reply_len == 0:
                return None
            return frame(0x41, ident, self.node_exchange(p[0], p[2:2 + n], reply_len))
        return None


def frames_in(buf):
    """Split complete frames off the front of buf: (frames, rest). Each frame
    is (cmd, id, payload, ok)."""
    out = []
    while True:
        s = buf.find(bytes([STX]))
        if s < 0:
            return out, b""
        e = buf.find(bytes([ETX]), s + 1)
        if e < 0:
            return out, buf[s:]
        raw, body, i = buf[s + 1:e], bytearray(), 0
        while i < len(raw):
            if raw[i] == ESC and i + 1 < len(raw):
                body.append(raw[i + 1] & 0x7F)
                i += 2
            else:
                body.append(raw[i])
                i += 1
        buf = buf[e + 1:]
        if len(body) >= 3:
            out.append((body[0], body[1], bytes(body[2:-1]), sum(body) & 0xFF == 0))


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    elf = sys.argv[2] if len(sys.argv) > 2 else None
    log = open(os.path.join(d, "bridge.log"), "w", buffering=1)
    crc = 0
    if elf:
        try:
            crc = flash_crc(elf)
            log.write("# netbridge image %s, flash CRC32 %08x\n" % (elf, crc))
        except (OSError, ValueError) as e:
            log.write("# no image CRC (%s): the game will want to reflash\n" % e)
    claims = {}
    game = sys.argv[3] if len(sys.argv) > 3 else None
    if game:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import s3nodes
            claims = s3nodes.derive(game)
            log.write("# node directory of %s: %s\n" % (game, " ".join(
                "%d=%s" % (n, c["type"]) for n, c in sorted(claims.items()))))
        except Exception as e:                       # a run without nodes still boots
            log.write("# no node directory (%s): every node will time out\n" % e)
    br = Bridge(crc, log, claims)
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    tty.setraw(master)
    tty.setraw(slave)
    os.chmod(name, 0o666)
    log.write("# s3bridge on %s\n" % name)
    with open(os.path.join(d, "bridge.path"), "w") as f:
        f.write(name)
    t0 = time.time()
    pend = b""
    seen = {}
    while True:
        r, _, _ = select.select([master], [], [], 0.5)
        if not r:
            continue
        try:
            data = os.read(master, 4096)
        except OSError:
            time.sleep(0.2)      # no slave open (yet): hold the pty
            continue
        pend += data
        got, pend = frames_in(pend)
        now = time.time() - t0
        for cmd, ident, p, ok in got:
            reply = br.handle(cmd, ident, p) if ok else None
            if reply:
                os.write(master, reply)
            key = (cmd, p[:3] if cmd == 0x41 else p)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= 3:       # the first few of each kind, then quiet
                log.write("%9.3f %s cmd %02x id %02x %s%s\n" % (
                    now, "rx" if ok else "BAD-SUM", cmd, ident, p.hex(),
                    (" -> " + reply.hex()) if reply else ""))


if __name__ == "__main__":
    main()
