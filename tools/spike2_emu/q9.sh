#!/bin/bash
# Q9: the loop at 0x2a241c walks 8 x 64-byte voice slots, computes a 0..255
# level (usat #8) and calls a mixer through a 512-entry fn-ptr table.
# Read the two literals it uses, find the enclosing function and its callers,
# and check whether 0x674fc0 really is a 256-entry gain curve.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
D=$HOME/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ literals used by the mixer loop ############"
$OD -s --start-address=0x2a25a0 --stop-address=0x2a25b0 $G | tail -3

echo
echo "############ start of the enclosing function ############"
$OD -d --start-address=0x2a212c --stop-address=0x2a21c0 $G | sed -n '7,40p'

echo
echo "############ callers of 0x2a212c ############"
grep -naE 'bl	2a212c' $D | head

echo
echo "############ 0x674fc0: first 32 halfwords (gain curve?) ############"
export PAD_ELF="${PAD_ELF:-${G:-$(python3 "$RIG/gameinfo.py" --elf)}}"
python3 - <<'PY'
import struct
import os
P=os.environ['PAD_ELF']
d=open(P,'rb').read()
ph,=struct.unpack_from('<I',d,0x1c); es,en=struct.unpack_from('<HH',d,0x2a)
segs=[]
for i in range(en):
    o=ph+i*es
    t,off,va,_,fsz=struct.unpack_from('<IIIII',d,o)
    if t==1: segs.append((va,off,fsz))
def rd(va,n):
    for va0,o,fsz in segs:
        if va0<=va<va0+fsz: return d[o+va-va0:o+va-va0+n]
b=rd(0x674fc0,512)
v=struct.unpack('<256H',b)
print('  first 24 :', v[:24])
print('  last  8  :', v[-8:])
print('  monotonic non-decreasing:', all(v[i]<=v[i+1] for i in range(255)))
print('  max      :', max(v))
PY
