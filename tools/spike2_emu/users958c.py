import re
lines=open('/home/david/game.dis','r',errors='ignore').read().split('\n')
pat=re.compile(r'^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+movw\s+(\w+), #38284')
hits=[]
for i,l in enumerate(lines):
    m=pat.match(l)
    if m: hits.append((int(m.group(1),16),m.group(2),i))
print("movw 0x958c sites:",len(hits))
for a,r,i in hits:
    # look ahead 6 lines for movt #122 same reg, then print next 8 lines
    ok=False
    for j in range(i+1,min(i+8,len(lines))):
        if re.search(r'movt\s+%s, #122'%r, lines[j]): ok=True;break
    if not ok: continue
    ctx=[]
    for j in range(i,min(i+14,len(lines))):
        s=lines[j].split('\t')
        if len(s)>=3: ctx.append(s[2].strip()+(' '+s[3].strip() if len(s)>3 else ''))
    print('--- %08x reg=%s'%(a,r))
    for c in ctx: print('    ',c.split('<')[0].strip())
