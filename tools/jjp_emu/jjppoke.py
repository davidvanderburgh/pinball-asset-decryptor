#!/usr/bin/env python3
"""Press a JJP switch by name from the command line - the hidden-run
(PAD_HIDDEN=1) stand-in for clicking it on the matrix window (PAD-1335).

    jjppoke.py switch_target_jam              # pulse it (120 ms)
    jjppoke.py dswitch_start --hold-ms 300
    jjppoke.py switch_trough_1 --set 1        # latch active (ball present)
    jjppoke.py --list jam                     # find names

Names are the game's own Switch symbols or display names (case-insensitive),
read from the live device dump (swdump.py -> /var/tmp/jjp_devices.json).
"Active" means contact made / ball present: SwitchShm flips inverted optos
itself, so a trough position is pressed exactly like a target.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jjpsw  # noqa: E402


def load(devices):
    d = json.load(open(devices))
    return [s for s in d['switches'] if 0 <= s.get('frame_byte', 255) < jjpsw.FRAME_LEN]


def find(switches, name):
    n = name.lower()
    for key in ('symbol', 'name'):
        hits = [s for s in switches if s[key].lower() == n]
        if len(hits) == 1:
            return hits[0]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('switch', nargs='*')
    ap.add_argument('--devices', default='/var/tmp/jjp_devices.json')
    ap.add_argument('--shm', default=jjpsw.DEFAULT_SHM)
    ap.add_argument('--hold-ms', type=int, default=120)
    ap.add_argument('--set', type=int, choices=(0, 1), default=None,
                    help='latch active (1) or inactive (0) instead of pulsing')
    ap.add_argument('--list', default=None, metavar='TEXT')
    a = ap.parse_args(argv)
    switches = load(a.devices)
    if a.list is not None:
        t = a.list.lower()
        for s in switches:
            if t in s['symbol'].lower() or t in s['name'].lower():
                print(f"{s['symbol']:32s} {s['name']:32s} byte {s['frame_byte']} bit {s['frame_bit']}"
                      f"{' inverted' if s['inverted'] else ''}")
        return 0
    shm = jjpsw.SwitchShm(a.shm)
    shm.inverted = frozenset((s['frame_byte'], s['frame_bit']) for s in switches if s['inverted'])
    rc = 0
    for name in a.switch:
        s = find(switches, name)
        if not s:
            print(f'jjppoke: no switch named {name!r} (try --list)', file=sys.stderr)
            rc = 2
            continue
        fb, mask = s['frame_byte'], s['frame_bit']
        if a.set is not None:
            shm.set_switch(fb, mask, bool(a.set))
            print(f"{s['symbol']}: {'active' if a.set else 'inactive'}")
        else:
            shm.set_switch(fb, mask, True)
            time.sleep(a.hold_ms / 1000)
            shm.set_switch(fb, mask, False)
            print(f"{s['symbol']}: pulsed {a.hold_ms} ms")
    return rc


if __name__ == '__main__':
    sys.exit(main())
