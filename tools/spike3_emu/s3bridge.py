#!/usr/bin/env python3
"""s3bridge - the Spike 3 netbridge's host UART (PAD-1090).

On the machine the CPU module talks to the RP2040 "netbridge" board over a
UART (/dev/ttyAMA5); the board's firmware (games/<title>/spike3/netbridge/
netbridge.elf, on the card) runs that link in uart_host.c and fans out to the
node boards, LEDs, DMD, LCD and power distribution. This holds the master end
of a pty for the chroot's /dev/ttyAMA5, so the game's open succeeds, and logs
every byte the game sends with the time it came.

    s3bridge.py DIR        writes DIR/bridge.path (the pty) and DIR/bridge.log

Stage one only listens: it is the recon end that shows what the game asks
the board before anything answers it.
"""
import os
import pty
import select
import sys
import time
import tty


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    tty.setraw(master)
    tty.setraw(slave)
    os.chmod(name, 0o666)
    log = open(os.path.join(d, "bridge.log"), "w", buffering=1)
    log.write("# s3bridge on %s\n" % name)
    with open(os.path.join(d, "bridge.path"), "w") as f:
        f.write(name)
    t0 = time.time()
    pend, last = b"", 0.0
    while True:
        r, _, _ = select.select([master], [], [], 0.05)
        now = time.time() - t0
        if r:
            try:
                data = os.read(master, 4096)
            except OSError:
                time.sleep(0.2)      # no slave open (yet): hold the pty
                continue
            if data:
                pend += data
                last = now
        # a burst ends after 20 ms of quiet: one log line per burst
        if pend and now - last > 0.02:
            log.write("%9.3f tx[%d] %s\n" % (last, len(pend), pend[:256].hex()))
            pend = b""


if __name__ == "__main__":
    main()
