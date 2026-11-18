#!/usr/bin/env python3
"""PAD key sharing: a JJP machine lends its purple security key to PAD on the
same network (PAD-1416).

WHAT.  Runs on the machine (installed by a key sharing stick, see
pinball_decryptor/plugins/jjp/keyshare.py).  It is a small USB/IP server, the
same protocol usbipd-win and Linux usbipd speak, so PAD's Emulate tab
("On another PC (network)", PAD-529) attaches the key from the machine exactly
as it does from a PC.  The machine's own kernel does the USB work
(usbip-host.ko, which every JJP Ubuntu image ships); this only answers the
two questions a client asks - "what do you offer" and "give me that one" -
and hands the connection to the kernel.

ONE KEY, ONE USER.  A Sentinel HL Pro key is local only: its license manager
refuses other computers, so the machine and a PC can never use it at the same
time.  While PAD has it the game finds no key, and the game's own launcher
(scripts/rungame.sh) shows "SECURITY KEY MISSING ... Game will rescan" and
tries again every few seconds - exactly what pulling the key out does.  When
PAD lets go (Stop in the Emulate tab, or the PC goes away) the key goes back
to the machine and the game starts again by itself.  Nothing here stops or
starts the game.

Only computers on the local network (private, link-local and loopback
addresses) are answered.  Python 3.9 standard library only: that is what the
machine has.  ``python3 padkeyshare.py --log FILE`` runs it; the stick's hook
starts it once per boot.
"""

import argparse
import ipaddress
import os
import select
import signal
import socket
import struct
import sys
import time

VERSION = 0x0111                 # USB/IP protocol 1.1.1
OP_REQ_DEVLIST, OP_REP_DEVLIST = 0x8005, 0x0005
OP_REQ_IMPORT, OP_REP_IMPORT = 0x8003, 0x0003
#: op status: usbip prints "Request Failed", "Device Busy - exported",
#: "Device not found" for them
ST_OK, ST_NA, ST_DEV_BUSY, ST_NODEV = 0, 1, 2, 4
PORT = 3240
KEY_IDS = ("0529", "0001")       # every HASP / Sentinel key
SYS = "/sys/bus/usb"
DRIVER = SYS + "/drivers/usbip-host"
#: usbip_status: 1 available, 2 used, 3 error
AVAILABLE, USED = "1", "2"
#: struct usbip_usb_device without its interfaces, and one interface
DEV_FMT = "!256s32sIIIHHHBBBBBB"
IF_FMT = "!BBBx"
SPEEDS = {"1.5": 1, "12": 2, "480": 3, "53.3-480": 4, "5000": 5, "10000": 6, "20000": 6}

_log_file = None


def log(msg):
    line = "%s padkeyshare: %s\n" % (time.strftime("%F %T"), msg)
    try:
        if _log_file:
            with open(_log_file, "a") as f:
                f.write(line)
        else:
            sys.stderr.write(line)
    except OSError:
        pass


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


# ------------------------------------------------------------------ the device
def keys(root=SYS):
    """Bus ids of the security keys plugged in, sorted."""
    out = []
    base = root + "/devices"
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        if ":" in n or n.startswith("usb"):
            continue
        d = os.path.join(base, n)
        if (_read(d + "/idVendor"), _read(d + "/idProduct")) == KEY_IDS:
            out.append(n)
    return sorted(out)


def _num(text, base=10):
    try:
        return int(text.strip(), base)
    except (ValueError, AttributeError):
        return 0


def device_record(busid, root=SYS, interfaces=False):
    """The wire record of *busid*: struct usbip_usb_device, plus each
    interface's class triple when *interfaces* (the device list wants them,
    an import does not)."""
    d = os.path.join(root, "devices", busid)
    path = os.path.realpath(d).encode()[:255]
    nif = _num(_read(d + "/bNumInterfaces"))
    rec = struct.pack(
        DEV_FMT, path, busid.encode()[:31],
        _num(_read(d + "/busnum")), _num(_read(d + "/devnum")),
        SPEEDS.get(_read(d + "/speed"), 0),
        _num(_read(d + "/idVendor"), 16), _num(_read(d + "/idProduct"), 16),
        _num(_read(d + "/bcdDevice"), 16),
        _num(_read(d + "/bDeviceClass"), 16), _num(_read(d + "/bDeviceSubClass"), 16),
        _num(_read(d + "/bDeviceProtocol"), 16),
        _num(_read(d + "/bConfigurationValue")), _num(_read(d + "/bNumConfigurations")),
        nif)
    if interfaces:
        cfg = _num(_read(d + "/bConfigurationValue")) or 1
        for i in range(nif):
            f = os.path.join(d, "%s:%d.%d" % (busid, cfg, i))
            rec += struct.pack(IF_FMT, _num(_read(f + "/bInterfaceClass"), 16),
                               _num(_read(f + "/bInterfaceSubClass"), 16),
                               _num(_read(f + "/bInterfaceProtocol"), 16))
    return rec


def status(busid, root=SYS):
    return _read(os.path.join(root, "devices", busid, "usbip_status"))


def bound_to_us(busid, root=SYS):
    return os.path.basename(os.path.realpath(
        os.path.join(root, "devices", busid, "driver"))) == "usbip-host"


def lend(busid, root=SYS):
    """Take the key from the machine and give it to usbip-host (what
    ``usbip bind`` does).  True when it is ready to export."""
    os.system("modprobe usbip-host >/dev/null 2>&1")
    drv = root + "/drivers/usbip-host"
    if not os.path.isdir(drv):
        log("no usbip-host driver on this machine")
        return False
    dev = os.path.join(root, "devices", busid)
    if not bound_to_us(busid, root):
        # a stale entry in usbip-host's bus id table (left "removed" or
        # "other") would make the bind below fail with ENODEV: clear it first
        try:
            _write(drv + "/match_busid", "del " + busid)
        except OSError:
            pass
        try:
            if os.path.exists(dev + "/driver"):
                _write(dev + "/driver/unbind", busid)
            _write(drv + "/match_busid", "add " + busid)
            _write(drv + "/bind", busid)
        except OSError as e:
            log("could not take key %s from the machine: %s" % (busid, e))
            give_back(busid, root)
            return False
    for _ in range(20):
        if status(busid, root) == AVAILABLE:
            return True
        time.sleep(0.1)
    return False


def give_back(busid, root=SYS):
    """The key back to the machine: the game finds it on its next rescan.

    The order matters (PAD-1416: the second lend failed with ENODEV when the
    entry was deleted first).  Unbind from usbip-host, then ``rebind`` (marks
    the entry "other" and hands the key to the normal USB driver), then
    delete the entry, which clears an "other" one for good.  Kernels without
    ``rebind`` get ``drivers_probe``."""
    drv = root + "/drivers/usbip-host"
    steps = []
    if bound_to_us(busid, root):
        steps.append((drv + "/unbind", busid))
    steps += [(drv + "/rebind", busid), (drv + "/match_busid", "del " + busid)]
    rebound = False
    for p, text in steps:
        try:
            _write(p, text)
            rebound = rebound or p.endswith("/rebind")
        except OSError:
            pass
    if not rebound:
        try:
            _write(root + "/drivers_probe", busid)
        except OSError:
            pass
    log("key %s back with the machine" % busid)


# ------------------------------------------------------------------ the wire
def op(code, st=ST_OK):
    return struct.pack("!HHI", VERSION, code, st)


def devlist_reply(busids, root=SYS):
    recs = [device_record(b, root, interfaces=True) for b in busids]
    return op(OP_REP_DEVLIST) + struct.pack("!I", len(recs)) + b"".join(recs)


def local_peer(addr):
    """Only the local network gets an answer."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _recv(conn, n):
    buf = b""
    while len(buf) < n:
        part = conn.recv(n - len(buf))
        if not part:
            raise EOFError
        buf += part
    return buf


class Server:
    def __init__(self, port=PORT, root=SYS, host="0.0.0.0"):
        self.root = root
        self.lent = set()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(4)
        # a key left with usbip-host by a run that died goes back first
        for b in keys(root):
            if bound_to_us(b, root):
                give_back(b, root)

    def handle(self, conn, peer):
        conn.settimeout(10)
        ver, code, _st = struct.unpack("!HHI", _recv(conn, 8))
        if ver != VERSION:
            log("%s speaks USB/IP %04x, not %04x" % (peer, ver, VERSION))
            return
        if code == OP_REQ_DEVLIST:
            ks = keys(self.root)
            conn.sendall(devlist_reply(ks, self.root))
            log("%s asked what is offered: %s" % (peer, ", ".join(ks) or "no key"))
            return
        if code != OP_REQ_IMPORT:
            log("%s sent request %04x" % (peer, code))
            return
        busid = _recv(conn, 32).split(b"\0")[0].decode("ascii", "replace")
        if busid not in keys(self.root):
            log("%s asked for %s: no key there" % (peer, busid))
            conn.sendall(op(OP_REP_IMPORT, ST_NODEV))
            return
        if busid in self.lent or not lend(busid, self.root):
            log("%s asked for %s: in use" % (peer, busid))
            conn.sendall(op(OP_REP_IMPORT, ST_DEV_BUSY))
            return
        try:
            _write(os.path.join(self.root, "devices", busid, "usbip_sockfd"),
                   str(conn.fileno()))
        except OSError as e:
            log("%s asked for %s: the kernel refused it (%s)" % (peer, busid, e))
            conn.sendall(op(OP_REP_IMPORT, ST_NA))
            give_back(busid, self.root)
            return
        conn.sendall(op(OP_REP_IMPORT) + device_record(busid, self.root))
        self.lent.add(busid)
        log("key %s lent to %s; the game waits for it" % (busid, peer))

    def watch(self):
        """A lent key whose PC let go goes back to the machine."""
        for b in list(self.lent):
            if not os.path.isdir(os.path.join(self.root, "devices", b)):
                self.lent.discard(b)
            elif status(b, self.root) != USED:
                self.lent.discard(b)
                give_back(b, self.root)

    def serve_once(self, timeout=1.0):
        r, _w, _x = select.select([self.sock], [], [], timeout)
        if r:
            conn, (addr, _port) = self.sock.accept()
            try:
                if local_peer(addr):
                    self.handle(conn, addr)
                else:
                    log("refused %s: not on the local network" % addr)
            except (EOFError, OSError, struct.error) as e:
                log("%s: %s" % (addr, e or "closed"))
            finally:
                conn.close()            # the kernel holds its own reference
        self.watch()

    def close(self):
        for b in list(self.lent):
            give_back(b, self.root)
        self.lent.clear()
        self.sock.close()


def main(argv=None):
    global _log_file
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    _log_file = a.log
    srv = Server(a.port)
    log("offering %s on port %d" % (", ".join(keys()) or "no key yet", a.port))
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    try:
        while not stop:
            srv.serve_once()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
