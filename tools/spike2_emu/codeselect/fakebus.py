#!/usr/bin/env python3
"""fakebus.py - a fake Spike 2 node bus on a pty, for testing codeselect --input hw.

Creates a pty, prints the slave path on stdout (first line, flushed), and
answers the wire protocol the way the boards + netbridge do (read_nodebus.md):

  unaddressed  0a 00 -> 03 00        03 00 -> 00 05 00
               07 xx / 08 xx         -> nothing
               00 (bare poll)        -> the next node wanting service: 1, 8, 0, 1, 8, 0 ...
  addressed    [0x80|node][n+1][payload][ck][reply_len]; a bad checksum is
               logged as 'BAD CK' and NOT answered
               f0 / f1 / any reply_len 0 -> nothing
               fe  -> 11-byte identity 00 01 21 00 23 00 02 00 64 00 01 + ck + STATUS 0
               f9 / fc -> 16 zero bytes + ck + 0
               ff  -> 8 zero bytes + ck + 0
               11  -> 8 switch bytes (node 8 at rest 00 ff 1f fb 40 00 00 00,
                      node 1 at rest ff x8; pressed buttons named in the
                      control file clear their bit: left = node 8 bit 25,
                      right = node 8 bit 24, start = node 1 bit 11,
                      action = node 1 bit 2, the lockdown-bar button) + u16 0
                      + ck + STATUS 0

Every frame is logged ('TX' = what the client sent, 'RX' = the reply).

  fakebus.py [--control FILE] [--log FILE] [--path-file FILE] [--idle SEC] [--max SEC]
"""
import argparse
import os
import select
import sys
import time

REST8 = bytes([0x00, 0xff, 0x1f, 0xfb, 0x40, 0x00, 0x00, 0x00])
REST1 = bytes([0xff] * 8)
IDENTITY = bytes([0x00, 0x01, 0x21, 0x00, 0x23, 0x00, 0x02, 0x00, 0x64, 0x00, 0x01])
POLL_CYCLE = [1, 8, 0]


def hexs(b):
    return " ".join("%02x" % x for x in b)


def ck(body):
    return (-sum(body)) & 0xff


class FakeBus:
    def __init__(self, args):
        self.args = args
        self.logf = open(args.log, "a") if args.log else None
        self.master, self.slave = os.openpty()
        self.slave_name = os.ttyname(self.slave)
        self.buf = bytearray()
        self.poll_i = 0
        self.t0 = time.monotonic()
        self.last_traffic = None

    def log(self, msg):
        line = "%8.3f %s" % (time.monotonic() - self.t0, msg)
        if self.logf:
            self.logf.write(line + "\n")
            self.logf.flush()
        else:
            print(line, flush=True)

    def pressed(self):
        try:
            with open(self.args.control) as f:
                return set(f.read().split())
        except OSError:
            return set()

    def switches(self, node):
        if node == 8:
            sw = bytearray(REST8)
            p = self.pressed()
            if "left" in p:
                sw[3] &= ~0x02
            if "right" in p:
                sw[3] &= ~0x01
            return bytes(sw)
        if node == 1:
            sw = bytearray(REST1)
            p = self.pressed()
            if "start" in p:
                sw[1] &= ~0x08          # bit 11
            if "action" in p:
                sw[0] &= ~0x04          # bit 2 = Action / LOCKDOWN BUTTON
            return bytes(sw)
        return bytes([0xff] * 8)

    def reply_addressed(self, node, payload, reply_len):
        if reply_len == 0 or not payload:
            return None
        pl = reply_len - 2
        cmd = payload[0]
        if cmd == 0x11:
            body = self.switches(node) + b"\x00\x00"
        elif cmd == 0xfe:
            body = IDENTITY
        elif cmd in (0xf9, 0xfc):
            body = bytes(16)
        elif cmd == 0xff:
            body = bytes(8)
        else:
            body = bytes(pl)
        body = (body + bytes(pl))[:pl]
        return body + bytes([ck(body), 0x00])

    def reply_unaddressed(self, cmd, payload):
        if cmd == 0x00:
            n = POLL_CYCLE[self.poll_i % len(POLL_CYCLE)]
            self.poll_i += 1
            return bytes([n])
        if cmd == 0x0a:
            return bytes([0x03, 0x00])
        if cmd == 0x03:
            return bytes([0x00, 0x05, 0x00])
        return None

    def send(self, data):
        if data:
            os.write(self.master, data)
            self.log("RX %s" % hexs(data))

    def parse(self):
        """consume complete frames from self.buf"""
        while self.buf:
            b0 = self.buf[0]
            if b0 & 0x80:
                if len(self.buf) < 2:
                    return
                L = self.buf[1]
                total = L + 3
                if len(self.buf) < total:
                    return
                frame = bytes(self.buf[:total])
                del self.buf[:total]
                node = b0 & 0x7f
                payload = frame[2:2 + L - 1]
                reply_len = frame[L + 2]
                if sum(frame[:L + 2]) & 0xff:
                    self.log("TX %s BAD CK" % hexs(frame))
                    continue
                self.log("TX %s (node %d cmd %02x reply_len %d)" %
                         (hexs(frame), node, payload[0] if payload else 0, reply_len))
                self.send(self.reply_addressed(node, payload, reply_len))
            else:
                if b0 == 0x00:
                    total = 1
                else:
                    if len(self.buf) < 2:
                        return
                    total = 2 + self.buf[1]
                if len(self.buf) < total:
                    return
                frame = bytes(self.buf[:total])
                del self.buf[:total]
                self.log("TX %s (unaddressed)" % hexs(frame))
                self.send(self.reply_unaddressed(b0, frame[2:]))

    def run(self):
        print(self.slave_name, flush=True)
        if self.args.path_file:
            with open(self.args.path_file, "w") as f:
                f.write(self.slave_name + "\n")
        self.log("fakebus on %s (control %s)" % (self.slave_name, self.args.control))
        start = time.monotonic()
        while True:
            now = time.monotonic()
            if self.args.max and now - start > self.args.max:
                self.log("max time reached, exiting")
                break
            if self.args.idle and self.last_traffic and now - self.last_traffic > self.args.idle:
                self.log("idle for %.1fs, exiting" % self.args.idle)
                break
            r, _, _ = select.select([self.master], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(self.master, 4096)
            except OSError:
                self.log("slave closed, exiting")
                break
            if not data:
                break
            self.last_traffic = time.monotonic()
            self.buf += data
            self.parse()
        if self.logf:
            self.logf.close()


def main():
    ap = argparse.ArgumentParser(description="fake Spike 2 node bus on a pty")
    ap.add_argument("--control", default="fakebus.ctl",
                    help="file naming pressed buttons: left right start action")
    ap.add_argument("--log", default=None, help="frame log (default stdout)")
    ap.add_argument("--path-file", default=None, help="also write the slave path here")
    ap.add_argument("--idle", type=float, default=0, help="exit after SEC without traffic (0 = never)")
    ap.add_argument("--max", type=float, default=120, help="exit after SEC total (0 = never)")
    args = ap.parse_args()
    FakeBus(args).run()


if __name__ == "__main__":
    main()
