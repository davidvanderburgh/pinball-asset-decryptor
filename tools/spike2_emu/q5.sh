#!/bin/bash
# Q5: 0x30ed20 is the real entry (0x30ed30 was mid-prologue). Re-run the
# data-word scan with the corrected addresses, and dump the SoLoud vtables.
echo "### data words pointing at the corrected function entries ###"
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
for target in (0x30ed20,0x458e98,0x2a212c,0x33a1d0):
    pat=struct.pack('<I',target); hits=[]; start=0
    while True:
        i=d.find(pat,start)
        if i<0: break
        if i%4==0:
            v=va_of(i)
            if v is not None: hits.append(v)
        start=i+1
    print('  0x%x : %s' % (target, ' '.join('0x%x'%h for h in hits) or '(none)'))
PY

echo
echo "### SoLoud vtables ###"
python3 /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/rtti.py 0x6f6e08 0x6f6e60 0x6f6e88 0x6f6e30 2>&1
