#!/usr/bin/env python3
"""Seed the shared block with the machine AT REST before the game boots.

Why this runs before the game and not just in the UI: the game latches its ball
count at power-up from what the trough reads on the very first frames.  The
trough switches are inverted optos - a present ball reads OPEN - so a shim idle
frame (matrix electrically open) looks to the game like a JAMMED, PHANTOM-BALL
mess, and a UI that only seats the trough AFTER the game is up is already too
late: the game has decided balls are missing and never recovers.  So we lay
down the correct rest state - trough full, other inverted optos clear, door
shut - into the block first, using the cached device dump for the inverted set.

If there is no dump yet (a brand-new title, first ever boot), we leave the shim
idle frame alone; the dump written by that run makes the next boot correct.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jjpsw                                                     # noqa: E402
import jjpball                                                   # noqa: E402


def main():
    dev_path = sys.argv[1] if len(sys.argv) > 1 else '/var/tmp/jjp_devices.json'
    if not os.path.exists(dev_path):
        print('seed_rest: no device dump yet - leaving the shim idle frame')
        return 0
    devices = json.load(open(dev_path))
    switches = {}
    inverted = set()
    by_sym = {}
    for s in devices.get('switches', []):
        fb, mask = s.get('frame_byte'), s.get('frame_bit')
        if fb is None or not mask or fb >= jjpsw.FRAME_LEN:
            continue
        switches.setdefault((fb, mask), s)
        by_sym.setdefault((s.get('symbol') or '').lower(), (fb, mask))
        if s.get('inverted') and not jjpsw.direct_byte(fb):
            inverted.add((fb, mask))

    if not any(s.get('inverted') for s in devices.get('switches', [])):
        print('seed_rest: dump predates the inverted flag - re-run swdump; '
              'leaving idle frame')
        return 0

    shm = jjpsw.SwitchShm()
    shm.inverted = inverted
    shm.idle()                                   # inverted optos -> clear
    door = by_sym.get('dswitch_coin_door_open')
    if door:
        shm.set_switch(door[0], door[1], True)   # coin door shut
    positions, how = jjpball.find_trough(switches)
    for _n, k in positions:
        shm.set_switch(k[0], k[1], True)         # a ball at every position
    print('seed_rest: rest state laid down - trough %d/%d (%s), door shut, '
          '%d inverted optos' % (len(positions), len(positions), how, len(inverted)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
