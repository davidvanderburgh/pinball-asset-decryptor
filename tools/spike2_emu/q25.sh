#!/bin/bash
# Q25: sanity-check the mixer-clone table bounds before writing them down.
. "$(dirname "$0")/padpath.sh"
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
def w(va):
    for va0,o,fsz in segs:
        if va0<=va<va0+fsz: return struct.unpack_from('<I',d,o+va-va0)[0]
for a in (0x67e1b4,0x67e1b8,0x67e1bc,0x67e1c0,0x67e1c4,
          0x67e9b8,0x67e9bc,0x67e9c0,0x67e9c4):
    print('  0x%08x : 0x%08x' % (a, w(a)))
vals=[w(0x67e1c0+4*i) for i in range(512)]
print('  entries all in .text 0x2f0000-0x340000 :', all(0x2f0000<=v<0x340000 for v in vals))
print('  strictly descending                    :', all(vals[i]>vals[i+1] for i in range(511)))
print('  first / last                           : 0x%x / 0x%x' % (vals[0], vals[-1]))
print('  index of 0x30ed20                      :', vals.index(0x30ed20))
for probe in (0x339204,0x336c6c):
    print('  index of 0x%x                      : %s'
          % (probe, vals.index(probe) if probe in vals else 'NOT in this table'))
PY
