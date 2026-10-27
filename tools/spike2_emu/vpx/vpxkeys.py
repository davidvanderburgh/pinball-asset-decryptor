#!/usr/bin/env python3
"""vpxkeys.py <key> [hold_ms] ... - press keys in a running patched table.

    python vpxkeys.py start            # Start, 300 ms
    python vpxkeys.py launch 300       # the launch button
    python vpxkeys.py lflip 400 rflip 400
    python vpxkeys.py 2 300            # any DirectInput code

The table's PadTestTimer (patch_godzilla.py) reads %TEMP%\\padvpx_keys.txt
every 100 ms and feeds the table's own key handlers, so a test run does not
depend on Visual Pinball's window having the keyboard. A `down` line, the
hold, then an `up` line - each its own file, so the timer sees the edges
apart.
"""
import os
import sys
import time

KEYS = {"start": 2, "launch": 28, "plunger": 28, "lflip": 42, "rflip": 54,
        "coin": 6, "esc": 1}
PATH = os.path.join(os.environ.get("TEMP", "."), "padvpx_keys.txt")


def send(line):
    for _ in range(40):                     # the timer deletes the file it read
        if not os.path.exists(PATH):
            break
        time.sleep(0.05)
    with open(PATH, "w") as f:
        f.write(line + "\n")


def press(code, hold_ms):
    send("down %d" % code)
    time.sleep(hold_ms / 1000.0)
    send("up %d" % code)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    i = 0
    while i < len(argv):
        key = argv[i]
        code = KEYS.get(key.lower(), None)
        if code is None:
            code = int(key)
        hold = 300
        if i + 1 < len(argv) and argv[i + 1].isdigit():
            hold = int(argv[i + 1])
            i += 1
        press(code, hold)
        print("%s (%d) held %d ms" % (key, code, hold))
        i += 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
