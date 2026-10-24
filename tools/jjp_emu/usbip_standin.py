#!/usr/bin/env python3
"""A stand-in USB/IP key server: exports fake Sentinel keys (0529:0001).

    python3 usbip_standin.py [--port 3241] [--bus 1-4] [--bus 1-5]

PAD-529's proof rig.  It speaks the real USB/IP protocol (v1.1.1, what
usbipd-win and Linux usbipd speak), so ``usbip attach -r`` from inside WSL
attaches one of its keys exactly as it would attach the purple key from the
PC across the room: the device enumerates on the WSL kernel's vhci-hcd and
shows in /sys/bus/usb/devices as 0529:0001.  It answers the descriptor and
configuration requests enumeration needs, and nothing else - it is NOT a
key: it carries no licence, so a licence daemon or a game finds no key on
it.  What it proves is the transport: attach by bus ID, the sysfs probe,
"in use by another PC", "no such bus ID", leases and detach.

A bus ID that is already imported answers "Device busy" to a second import,
as a real server does for a key another PC holds.
"""

import argparse
import socket
import struct
import threading

VERSION = 0x0111
OP_REQ_DEVLIST, OP_REP_DEVLIST = 0x8005, 0x0005
OP_REQ_IMPORT, OP_REP_IMPORT = 0x8003, 0x0003
CMD_SUBMIT, CMD_UNLINK, RET_SUBMIT, RET_UNLINK = 1, 2, 3, 4
ST_OK, ST_DEV_BUSY, ST_NODEV = 0, 2, 4
SPEED_FULL = 2
EPIPE = -32

DEVICE = bytes([18, 1, 0x00, 0x02, 0, 0, 0, 8,
                0x29, 0x05, 0x01, 0x00, 0x28, 0x04, 1, 2, 3, 1])
CONFIG = bytes([9, 2, 18, 0, 1, 1, 0, 0x80, 50,
                9, 4, 0, 0, 0, 0xFF, 0, 0, 0])


def _string(text):
    raw = text.encode("utf-16-le")
    return bytes([2 + len(raw), 3]) + raw


class Key:
    def __init__(self, busid, serial):
        self.busid = busid
        self.serial = serial
        self.lock = threading.Lock()
        self.user = None

    def record(self):
        bus, dev = self.busid.split("-")
        busnum, devnum = int(bus), int(dev.split(".")[-1])
        path = ("/sys/devices/pad-standin/usb%d/%s" % (busnum, self.busid))
        return (path.encode().ljust(256, b"\0")
                + self.busid.encode().ljust(32, b"\0")
                + struct.pack(">III", busnum, devnum, SPEED_FULL)
                + struct.pack(">HHH", 0x0529, 0x0001, 0x0428)
                + bytes([0, 0, 0, 1, 1, 1]))

    def control(self, setup):
        rtype, req, value, index, length = struct.unpack("<BBHHH", setup)
        if rtype & 0x80 and req == 6:                 # GET_DESCRIPTOR
            kind, idx = value >> 8, value & 0xFF
            if kind == 1:
                data = DEVICE
            elif kind == 2:
                data = CONFIG
            elif kind == 3:
                data = {0: bytes([4, 3, 0x09, 0x04]),
                        1: _string("PAD stand-in"),
                        2: _string("Stand-in Sentinel key (no licence)"),
                        3: _string(self.serial)}.get(idx)
            else:
                data = None
            return (0, data[:length]) if data is not None else (EPIPE, b"")
        if rtype & 0x80 and req == 0:                 # GET_STATUS
            return 0, b"\0\0"[:length]
        if rtype & 0x80 and req == 8:                 # GET_CONFIGURATION
            return 0, b"\x01"[:length]
        if not rtype & 0x80 and req in (9, 11, 1, 3):  # SET_CONFIG/IFACE/...
            return 0, b""
        return EPIPE, b""


def _recv(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def serve_urbs(conn, key):
    while True:
        head = _recv(conn, 48)
        cmd, seq, _devid, direction, ep = struct.unpack(">IIIII", head[:20])
        if cmd == CMD_UNLINK:
            conn.sendall(struct.pack(">IIIIIi", RET_UNLINK, seq, 0, 0, 0, 0)
                         + b"\0" * 24)
            continue
        if cmd != CMD_SUBMIT:
            raise EOFError
        _flags, length, _sf, npk, _iv = struct.unpack(">IiiiI", head[20:40])
        setup = head[40:48]
        if direction == 0 and length > 0:
            _recv(conn, length)
        if ep == 0:
            status, data = key.control(setup)
        else:
            status, data = EPIPE, b""
        if direction == 0:
            actual, data = (length if status == 0 else 0), b""
        else:
            actual = len(data)
        conn.sendall(struct.pack(">IIIIIiiiii", RET_SUBMIT, seq, 0, 0, 0,
                                 status, actual, 0,
                                 npk if npk in (0, -1) else 0, 0)
                     + b"\0" * 8 + data)


def handle(conn, keys, log):
    key = None
    try:
        version, code, _status = struct.unpack(">HHI", _recv(conn, 8))
        if code == OP_REQ_DEVLIST:
            free = [k for k in keys.values() if k.user is None]
            out = struct.pack(">HHII", VERSION, OP_REP_DEVLIST, ST_OK,
                              len(free))
            for k in free:
                out += k.record() + bytes([0xFF, 0, 0, 0])
            conn.sendall(out)
            log("list: offered %s" % [k.busid for k in free])
            return
        if code != OP_REQ_IMPORT:
            return
        busid = _recv(conn, 32).rstrip(b"\0").decode()
        key = keys.get(busid)
        if key is None:
            conn.sendall(struct.pack(">HHI", VERSION, OP_REP_IMPORT,
                                     ST_NODEV))
            log("import %s: no such bus id" % busid)
            key = None
            return
        with key.lock:
            if key.user is not None:
                conn.sendall(struct.pack(">HHI", VERSION, OP_REP_IMPORT,
                                         ST_DEV_BUSY))
                log("import %s: busy" % busid)
                key = None
                return
            key.user = conn
        conn.sendall(struct.pack(">HHI", VERSION, OP_REP_IMPORT, ST_OK)
                     + key.record())
        log("import %s: attached" % busid)
        serve_urbs(conn, key)
    except (EOFError, OSError):
        pass
    finally:
        if key is not None and key.user is conn:
            key.user = None
            log("import %s: released" % key.busid)
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3241)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--bus", action="append", default=[])
    a = ap.parse_args()
    keys = {b: Key(b, "PAD%04d" % i)
            for i, b in enumerate(a.bus or ["1-4"])}

    def log(msg):
        print("[standin] " + msg, flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.bind, a.port))
    srv.listen(8)
    log("serving %s on %s:%d" % (sorted(keys), a.bind, a.port))
    while True:
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(conn, keys, log),
                         daemon=True).start()


if __name__ == "__main__":
    main()
