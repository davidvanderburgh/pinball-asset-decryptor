#!/bin/bash
# Q8: 0x30ed20 has no bl callers but IS entry 0x67e40c of a function-pointer
# table, and the crash stack says its caller returns to 0x2a24ac. So 0x2a24a8
# must be the indirect call. Find the index computation and the table base.
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ 0x2a2400 .. 0x2a24c0 : the indirect call site ############"
$OD -d --start-address=0x2a2400 --stop-address=0x2a24c0 $G | sed -n '7,200p'

echo
echo "############ extent of the fn-ptr table around 0x67e40c ############"
python3 - <<'PY'
import struct
P='/home/david/spike2root/games/godzilla_pro/game'
d=open(P,'rb').read()
ph,=struct.unpack_from('<I',d,0x1c); es,en=struct.unpack_from('<HH',d,0x2a)
segs=[]
for i in range(en):
    o=ph+i*es
    t,off,va,_,fsz=struct.unpack_from('<IIIII',d,o)
    if t==1: segs.append((va,off,fsz))
def w(va):
    for va0,o,fsz in segs:
        if va0<=va<va0+fsz: return struct.unpack_from('<I',d,o+va-va0)[0]
    return None
def istext(v): return v is not None and 0x16a00 <= v < 0x5d3168 and (v&3)==0
lo=0x67e40c
while istext(w(lo-4)): lo-=4
hi=0x67e40c
while istext(w(hi+4)): hi+=4
n=(hi-lo)//4+1
print('  table base 0x%x .. 0x%x  (%d entries)  0x30ed20 is index %d'
      % (lo,hi,n,(0x67e40c-lo)//4))
PY
