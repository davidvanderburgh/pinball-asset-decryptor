import sys, struct, capstone
from elftools.elf.elffile import ELFFile
P=sys.argv[1]; d=open(P,'rb').read(); e=ELFFile(open(P,'rb'))
segs=[(s['p_vaddr'],s['p_offset'],s['p_filesz']) for s in e.iter_segments() if s['p_type']=='PT_LOAD']
def o2v(o):
    for v,off,sz in segs:
        if off<=o<off+sz: return v+o-off
def v2o(v):
    for va,off,sz in segs:
        if va<=v<va+sz: return off+v-va
text=e.get_section_by_name('.text'); tv=text['sh_addr']; to=text['sh_offset']; tsz=text['sh_size']
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM)
words=struct.unpack_from('<%dI'%(tsz//4),d,to)
def find_refs(target):
    # movw/movt pairs and literal pools
    res=[]
    lo=target&0xffff; hi=target>>16
    for i,w in enumerate(words):
        if w==target: res.append(('lit',tv+4*i))
        # movw: cond 0011 0000 imm4 Rd imm12
        if (w&0x0ff00000)==0x03000000 and (((w>>4)&0xf000)|(w&0xfff))==lo:
            rd=(w>>12)&0xf
            for j in range(i+1,min(i+8,len(words))):
                w2=words[j]
                if (w2&0x0ff00000)==0x03400000 and ((w2>>12)&0xf)==rd and (((w2>>4)&0xf000)|(w2&0xfff))==hi:
                    res.append(('movw',tv+4*i)); break
    return res
def callers(fva):
    res=[]
    for i,w in enumerate(words):
        if (w&0x0e000000)==0x0a000000 and ((w>>24)&1 or (w>>28)==0xf):
            off=w&0xffffff
            if off&0x800000: off-=0x1000000
            if tv+4*i+8+off*4==fva: res.append(tv+4*i)
    return res
def func_start(va):
    i=(va-tv)//4
    while i>0:
        w=words[i]
        if (w&0xffff0000)==0xe92d0000: return tv+4*i
        i-=1
cmd=sys.argv[2]
if cmd=='str':
    s=sys.argv[3].encode(); o=d.find(s); v=o2v(o); print('str',hex(v))
    for k,a in find_refs(v): print(k,hex(a),'func',hex(func_start(a)))
elif cmd=='callers':
    for a in callers(int(sys.argv[3],16)): print(hex(a),'in',hex(func_start(a)))
elif cmd=='dis':
    a=int(sys.argv[3],16); n=int(sys.argv[4])
    for ins in md.disasm(d[v2o(a):v2o(a)+4*n],a): print(hex(ins.address),ins.mnemonic,ins.op_str)
if cmd=='strs':
    # list string refs (movw/movt) inside a function range
    a=int(sys.argv[3],16); b=int(sys.argv[4],16)
    for i in range((a-tv)//4,(b-tv)//4):
        w=words[i]
        if (w&0x0ff00000)==0x03000000:
            rd=(w>>12)&0xf; lo=((w>>4)&0xf000)|(w&0xfff)
            for j in range(i+1,min(i+8,len(words))):
                w2=words[j]
                if (w2&0x0ff00000)==0x03400000 and ((w2>>12)&0xf)==rd:
                    v=lo|((((w2>>4)&0xf000)|(w2&0xfff))<<16); o=v2o(v)
                    if o:
                        s=d[o:d.find(b'\0',o)][:90]
                        if len(s)>3 and all(32<=c<127 or c in (10,) for c in s): print(hex(tv+4*i),s)
                    break
if cmd=='near':
    t=int(sys.argv[3],16); span=int(sys.argv[4],16)
    for i,w in enumerate(words):
        if (w&0x0ff00000)==0x03000000:
            rd=(w>>12)&0xf; lo=((w>>4)&0xf000)|(w&0xfff)
            for j in range(i+1,min(i+10,len(words))):
                w2=words[j]
                if (w2&0x0ff00000)==0x03400000 and ((w2>>12)&0xf)==rd:
                    v=lo|((((w2>>4)&0xf000)|(w2&0xfff))<<16)
                    if t-span<=v<=t: print(hex(tv+4*i),hex(v),'func',hex(func_start(tv+4*i)))
                    break
if cmd=='auditcall':
    tgt=int(sys.argv[3],16); aid=int(sys.argv[4])
    for a in callers(tgt):
        i=(a-tv)//4
        for j in range(i-6,i):
            w=words[j]
            if (w&0xfffff000)==0xe3a00000 and (w&0xff)==aid and ((w>>8)&0xf)==0: print(hex(a),'func',hex(func_start(a))); break
