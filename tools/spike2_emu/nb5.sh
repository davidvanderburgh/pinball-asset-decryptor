#!/bin/bash
# nb5.sh - find the code that formats "Check Node Board %d : %s".
# The literal is at file offset 6248668; .rodata maps VA = file offset + 0x8000.
. "$(dirname "$0")/padpath.sh"
export PAD_ELF="${PAD_ELF:-${G:-$(python3 "$RIG/gameinfo.py" --elf)}}"
python3 - <<'PY'
print(hex(6248668 + 0x8000), hex(6248868 + 0x8000))
PY
echo "=== refs to the format string ==="
bash $RIG/findref.sh 0x5fda9c 0x5fdb64
echo "=== the status strings, in file order ==="
python3 - <<'PY'
import os
d = open(os.environ['PAD_ELF'],'rb').read()
o = 6248640
end = 6249100
s = d[o:end].split(b'\0')
p = o
for x in s:
    if x:
        print('%08x  va %08x  %r' % (p, p + 0x8000, x.decode('latin1')))
    p += len(x) + 1
PY
