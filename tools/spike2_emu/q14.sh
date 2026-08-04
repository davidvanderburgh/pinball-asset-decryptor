#!/bin/bash
# Q14: the queue pool at [0x7b8a90] is live (0x9b1a98) and the teardown path
# hands queues back to it via 0x458674. Find the ACQUIRE counterpart and the
# store that puts a queue into voice+0x38.
G=/home/david/spike2root/games/godzilla_pro/game
D=/home/david/game.dis
OD=arm-linux-gnueabihf-objdump

echo "############ stores to +0x38 in the sound-instance TU (0x330000-0x345000) ############"
$OD -d --start-address=0x330000 --stop-address=0x345000 $G | grep -aE '	str	r[0-9a-z]+, \[r[0-9a-z]+, #56\]' | head -20

echo
echo "############ 0x33a3e8 : the other caller of 0x458674 ############"
$OD -d --start-address=0x33a380 --stop-address=0x33a420 $G | sed -n '7,40p'

echo
echo "############ 0x33a5c0..0x33a620 (0x33a5e4 was on the stack) ############"
$OD -d --start-address=0x33a5a0 --stop-address=0x33a620 $G | sed -n '7,40p'

echo
echo "############ who else touches the pool global 0x7b8a90 ? ############"
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/findref.sh 0x7b8a90
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
pat=struct.pack('<I',0x7b8a90); start=0; hits=[]
while True:
    i=d.find(pat,start)
    if i<0: break
    if i%4==0:
        v=va_of(i)
        if v is not None and v<0x5d3168: hits.append(v)
    start=i+1
print('  literal-pool entries for 0x7b8a90:', ' '.join('0x%x'%h for h in hits) or '(none)')
PY
