#!/bin/bash
G=/home/david/spike2root/games/godzilla_pro/game
OD=arm-linux-gnueabihf-objdump

echo "### string/global refs inside the faulting function 0x30ed30..0x30ef80 ###"
$OD -d --start-address=0x30ed30 --stop-address=0x30ef80 $G > /tmp/f.dis
awk '
/movw\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movw\t/,"",s); split(s,p,", #"); lo[p[1]]=p[2]+0 }
/movt\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movt\t/,"",s); split(s,p,", #");
  v=(p[2]+0)*65536+lo[p[1]]; printf "  0x%x\n", v }
' /tmp/f.dis | sort -u

echo
echo "### resolve any of those that land in .rodata as strings ###"
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
def rd(va,n):
    for va0,off,fsz in segs:
        if va0<=va<va0+fsz: return d[off+va-va0:off+va-va0+n]
    return None
import re,subprocess
out=subprocess.run(['awk','''
/movw\\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movw\\t/,"",s); split(s,p,", #"); lo[p[1]]=p[2]+0 }
/movt\\t[a-z0-9]+, #[0-9]+/ { s=$0; sub(/.*movt\\t/,"",s); split(s,p,", #");
  printf "%d\\n", (p[2]+0)*65536+lo[p[1]] }
''','/tmp/f.dis'],capture_output=True,text=True).stdout.split()
for v in sorted(set(int(x) for x in out)):
    b=rd(v,60)
    if b:
        s=b.split(b'\0')[0]
        if 3<len(s)<60 and all(32<=c<127 for c in s):
            print('  0x%x -> %r'%(v,s.decode()))
PY
