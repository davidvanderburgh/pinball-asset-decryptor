#!/usr/bin/env python3
"""swinit.py - create the switch shared-memory file WITHOUT padglhost.

Normally padglhost creates /dump/padsw and publishes held[] when its window
opens. A measurement run (runbridge.sh / nbrun.sh) has no window, so there is no
keyboard - but the shim will read the file if PAD_SW_SHM is exported to the
guest, whoever wrote it. This writes a valid header plus the machine-at-rest set
(coin door shut, six balls in the trough) so a headless run can still be driven
with swpoke.py / swhold.py.

Run it BEFORE the guest starts.
"""
import struct

PATH = '/home/david/spike2root/dump/padsw'
MAGIC = 0x53444150
REST = [33, 66, 67, 68, 69, 70, 71]

buf = bytearray(4096)
struct.pack_into('<II', buf, 0, MAGIC, 1)
for i in REST:
    buf[8 + i] = 1
open(PATH, 'wb').write(bytes(buf))
print('wrote %s  magic ok, gen=1, held: %s' % (PATH, REST))
