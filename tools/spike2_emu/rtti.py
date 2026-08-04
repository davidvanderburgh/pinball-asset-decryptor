import struct, sys

PATH = '/home/david/spike2root/games/godzilla_pro/game'
data = open(PATH, 'rb').read()

# Program headers give the real VA -> file offset mapping; the +0x8000 rule of
# thumb only holds for the first PT_LOAD.
e_phoff, = struct.unpack_from('<I', data, 0x1c)
e_phentsize, e_phnum = struct.unpack_from('<HH', data, 0x2a)
segs = []
for i in range(e_phnum):
    off = e_phoff + i * e_phentsize
    p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from('<IIIII', data, off)
    if p_type == 1:
        segs.append((p_vaddr, p_offset, p_filesz))

def rd(va, n):
    for vaddr, offset, filesz in segs:
        if vaddr <= va < vaddr + filesz:
            o = offset + (va - vaddr)
            return data[o:o + n]
    return None

def word(va):
    b = rd(va, 4)
    return struct.unpack('<I', b)[0] if b else None

def cstr(va):
    b = rd(va, 200)
    if not b:
        return None
    return b.split(b'\0')[0].decode('latin1')

for vt in [int(a, 16) for a in sys.argv[1:]]:
    print('=== vtable candidate 0x%x ===' % vt)
    top, ti = word(vt - 8), word(vt - 4)
    print('  offset-to-top = 0x%x   typeinfo = 0x%x' % (top, ti))
    if ti:
        namep = word(ti + 4)
        print('  RTTI name = %r' % cstr(namep))
        base = word(ti + 8)
        if base:
            bn = word(base + 4)
            print('  base class = %r' % cstr(bn))
    print('  virtual slots:')
    for i in range(0, 16):
        fn = word(vt + i * 4)
        if fn is None:
            break
        print('    +0x%02x -> 0x%x' % (i * 4, fn))
