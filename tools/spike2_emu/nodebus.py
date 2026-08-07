#!/usr/bin/env python3
"""Virtual node bus: stands in for the RS485 chain of node boards.

The game drives switches, coils and lamps over a plain UART (/dev/ttymxc1), so
the whole playfield is reachable from userspace. This holds the master end of a
pty, records everything the game transmits, and can be taught to answer.

Run it before the game, then bind-mount the slave path it prints onto
/dev/ttymxc1 inside the container.
"""
import os
import pty
import select
import sys
import termios
import time
import tty

#: Where the pty path and the traffic log are written. run_game.sh sets
#: PAD_NODEBUS_DIR to the rootfs `dump/` directory, which is the shared area
#: everything else in the rig already publishes into; the fallback keeps this
#: runnable by hand. Both were absolute paths into one user's home directory.
_DIR = os.environ.get("PAD_NODEBUS_DIR") or os.path.expanduser("~")
PATH_FILE = os.path.join(_DIR, "nodebus.path")
LOG_FILE = os.path.join(_DIR, "nodebus.log")


def main() -> None:
    reply_len = int(os.environ.get("PAD_NODEBUS_REPLY", "0"))
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    tty.setraw(master)
    tty.setraw(slave)
    os.chmod(name, 0o666)
    with open(PATH_FILE, "w") as fh:
        fh.write(name)
    print(name, flush=True)

    log = open(LOG_FILE, "w", buffering=1)
    log.write(f"# virtual node bus on {name}\n")

    t0 = time.time()
    total = 0
    last_flush = t0
    while True:
        ready, _, _ = select.select([master], [], [], 1.0)
        now = time.time()
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            total += len(data)
            log.write(f"{now - t0:8.3f} TX {len(data):4d} {data.hex()}\n")
            # Replying with a deliberately short frame makes the game report
            # "received N, expected length=M", which hands over the expected
            # reply length for every command it sends.
            if reply_len:
                os.write(master, bytes(reply_len))
                log.write(f"{now - t0:8.3f} RX {reply_len:4d} {'00' * reply_len}\n")
        if now - last_flush > 5:
            last_flush = now
            log.write(f"# {now - t0:.1f}s elapsed, {total} bytes seen\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
