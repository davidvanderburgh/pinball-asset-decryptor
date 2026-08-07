import re
import os
# find all ldr/str with -3020 (0x7aa9b8) or -3024 (0x7aa9b4) displacement
pat=re.compile(r'^\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(\S+)\s+(.*)$')
for line in open(os.path.expanduser("~/game.dis"),'r',errors='ignore'):
    m=pat.match(line)
    if not m: continue
    ops=m.group(3)
    if '#-3020' in ops or '#-3024' in ops or '#-3016' in ops or '#-3012' in ops:
        print(m.group(1), m.group(2), ops.split('<')[0].strip())
