import re,sys
import os
lo=0x1d5400; hi=0x1d8800
tlo=0x1e6700; thi=0x1e7c80
pat=re.compile(r'^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(bl|b|blx|bne|beq)\s+([0-9a-f]+)')
out=[]
for line in open(os.path.expanduser("~/game.dis"),'r',errors='ignore'):
    m=pat.match(line)
    if not m: continue
    a=int(m.group(1),16)
    t=int(m.group(3),16)
    if lo<=a<hi and tlo<=t<thi:
        out.append((a,m.group(2),t))
for a,mn,t in out:
    print('%08x  %-4s %08x'%(a,mn,t))
print('count',len(out))
