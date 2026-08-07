#!/bin/bash
# Q6: 0x30ed20 is referenced from a table at 0x67e40c and 0x33a1d0 from
# 0x7069c0. Work out what those tables are, and read the SoLoud vtables using
# the ELF convention (symbol address = start of the vtable OBJECT, so
# [0]=offset-to-top, [1]=typeinfo, [2..]=virtual functions).
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
def rd(va,n):
    for va0,o,fsz in segs:
        if va0<=va<va0+fsz: return d[o+va-va0:o+va-va0+n]
    return None
def w(va):
    b=rd(va,4)
    return struct.unpack('<I',b)[0] if b else None
def s(va):
    b=rd(va,300)
    if not b: return None
    t=b.split(b'\0')[0]
    return t.decode('latin1') if t else None

sym={}
import os
for line in open(os.path.expanduser('~/dynsym.txt')):
    a,n=line.split(); sym[int(a,16)]=n

def rtti_of(vt):
    """vt = address of the vtable OBJECT: [0]=off-to-top [1]=typeinfo"""
    ti=w(vt+4)
    if not ti: return None
    nm=w(ti+4)
    return s(nm) if nm else None

print('### words around the table that holds 0x30ed20 (0x67e40c) ###')
for a in range(0x67e3d0,0x67e460,4):
    v=w(a)
    mark=' <== 0x30ed20' if v==0x30ed20 else ''
    print('  0x%08x : 0x%08x %s%s'%(a,v,sym.get(v,''),mark))

print()
print('### walk back from 0x67e40c looking for a vtable header ###')
for base in range(0x67e40c, 0x67e40c-0x120, -4):
    ti=w(base+4)
    if ti and 0x600000 < ti < 0x780000:
        nm=rtti_of(base)
        if nm:
            print('  vtable object at 0x%08x  RTTI=%r  (slot index of 0x30ed20 = %d)'
                  % (base, nm, (0x67e40c-base-8)//4))
            break

print()
print('### words around 0x7069c0 (holds 0x33a1d0) ###')
for a in range(0x706990,0x7069f0,4):
    v=w(a)
    mark=' <== 0x33a1d0' if v==0x33a1d0 else ''
    print('  0x%08x : 0x%08x %s%s'%(a,v,sym.get(v,''),mark))
print()
for base in range(0x7069c0, 0x7069c0-0x120, -4):
    ti=w(base+4)
    if ti and 0x600000 < ti < 0x780000:
        nm=rtti_of(base)
        if nm:
            print('  vtable object at 0x%08x  RTTI=%r  (slot index of 0x33a1d0 = %d)'
                  % (base, nm, (0x7069c0-base-8)//4))
            break

print()
print('### SoLoud vtables, read correctly ###')
for vt in (0x6f6e08,0x6f6e30,0x6f6e60,0x6f6e88,0x6f6f88,0x6f6fb8):
    print('  0x%08x %-40s RTTI=%r'%(vt,sym.get(vt,''),rtti_of(vt)))
PY
