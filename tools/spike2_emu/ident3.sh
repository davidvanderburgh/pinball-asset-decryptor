#!/bin/bash
. "$(dirname "$0")/padpath.sh"
G=$ROOT/games/godzilla_pro/game
arm-linux-gnueabihf-objdump -d --start-address=0x2a1000 --stop-address=0x2a3200 $G > /tmp/g.dis
export PAD_ELF="${PAD_ELF:-${G:-$(python3 "$RIG/gameinfo.py" --elf)}}"
python3 - <<'PY'
import struct, subprocess
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
    for va0,off,fsz in segs:
        if va0<=va<va0+fsz: return d[off+va-va0:off+va-va0+n]
    return None
out=subprocess.run(['awk','''
/movw\\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movw\\t/,"",s); split(s,p,", #"); lo[p[1]]=p[2]+0 }
/movt\\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movt\\t/,"",s); split(s,p,", #");
  printf "%d\\n", (p[2]+0)*65536+lo[p[1]] }
''','/tmp/g.dis'],capture_output=True,text=True).stdout.split()
seen=set()
for v in sorted(set(int(x) for x in out)):
    b=rd(v,80)
    if not b: continue
    s=b.split(b'\0')[0]
    if 3<len(s)<70 and all(32<=c<127 for c in s):
        t=s.decode()
        if t not in seen:
            seen.add(t); print('  0x%x -> %r'%(v,t))
PY
