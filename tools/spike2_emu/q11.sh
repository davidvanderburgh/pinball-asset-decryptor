#!/bin/bash
# Q11: findref.sh only resolves movw/movt. The mixer loads the voice array from
# a pc-relative LITERAL POOL, so scan .text for pool words equal to 0x7b90c0
# and friends, then find the stores that fill voice+0x38.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ literal-pool words pointing into the voice array ############"
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
def va_of(off):
    for va,o,fsz in segs:
        if o<=off<o+fsz: return va+off-o
for target,label in ((0x7b90c0,'voice array base'),
                     (0x7b8990,'audio state block'),
                     (0x704bf4,'audio global mutex'),
                     (0x7b8a74,'per-bit s16 table')):
    pat=struct.pack('<I',target); hits=[]; start=0
    while True:
        i=d.find(pat,start)
        if i<0: break
        if i%4==0:
            v=va_of(i)
            if v is not None and v < 0x5d3168: hits.append(v)   # inside .text = a literal pool
        start=i+1
    print('  %-20s 0x%x : pool entries at %s'%(label,target,' '.join('0x%x'%h for h in hits) or '(none)'))
PY

echo
echo "############ stores to +0x38 anywhere in the audio TU (0x2a0000-0x2b8000) ############"
$OD -d --start-address=0x2a0000 --stop-address=0x2b8000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #56\]' | head -30

echo
echo "############ the 8 voice slots as they sit in the FILE (.data image) ############"
$OD -s --start-address=0x7b90c0 --stop-address=0x7b92c0 $G 2>&1 | tail -40
