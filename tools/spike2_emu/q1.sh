#!/bin/bash
# Q1: find how 0x30ed30 is entered, and what class it belongs to.
# It has no `bl` callers, so look for (a) `b` tail branches and (b) the address
# sitting in a data word, i.e. a vtable slot or a function-pointer table.
G=/home/david/spike2root/games/godzilla_pro/game
D=/home/david/game.dis

echo "### tail branches / any reference to 30ed30 in the disassembly ###"
grep -nE '\b(b|bl|blx)\t30ed30' $D | head -20
echo "(none above means: not reached by a direct branch either)"

echo
echo "### words in the file equal to 0x30ed30 / 0x30ed31 (vtable or fn-ptr table) ###"
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
def va_of(off):
    for va,o,fsz in segs:
        if o<=off<o+fsz: return va+off-o
    return None
for target in (0x30ed30,0x30ed31,0x4db74c,0x4db74d,0x458fa0,0x458fa1,0x2a2470,0x33a5e0):
    pat=struct.pack('<I',target)
    hits=[]
    start=0
    while True:
        i=d.find(pat,start)
        if i<0: break
        if i%4==0:
            v=va_of(i)
            if v is not None: hits.append(v)
        start=i+1
    print('0x%x : %s' % (target, ' '.join('0x%x'%h for h in hits) or '(no data-word references)'))
PY
