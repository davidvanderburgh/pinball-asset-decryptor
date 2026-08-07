#!/bin/bash
# Q24: 0x7acb54 reads 1 when the audio worker starts and 0 at crash time.
# Find who writes it (strb through movw/movt or a literal pool) so we know
# what the flag means before experimenting on it.
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "############ literal-pool entries for 0x7acb54 ############"
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
pat=struct.pack('<I',0x7acb54); start=0; hits=[]
while True:
    i=d.find(pat,start)
    if i<0: break
    if i%4==0:
        v=va_of(i)
        if v is not None: hits.append(v)
    start=i+1
print('  ', ' '.join('0x%x'%h for h in hits) or '(none)')
PY

echo
echo "############ the reader in the audio worker, byte-exact ############"
$OD -d --start-address=0x459190 --stop-address=0x4591c0 $G | sed -n '7,20p'

echo
echo "############ the same construct elsewhere: 0x1d7d14 and 0x3bba10 ############"
$OD -d --start-address=0x1d7d14 --stop-address=0x1d7d34 $G | sed -n '7,20p'

echo
echo "############ strb to the flag: search .text for 'strb .*[r?, #0]' near movw 0xcb54 ############"
grep -naE 'movw	r[0-9a-z]+, #52052' $HOME/game.dis | head -20
