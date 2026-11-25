import json, re, struct, sys
r = json.load(open('spikebt/profiles/discovery/spike2/godzilla_le-1.16.json'))
elf = open('/c/tmp/gzle116_stock.elf', 'rb').read() if False else open(r'C:\tmp\gzle116_stock.elf', 'rb').read()
ph = struct.unpack_from('<I', elf, 28)[0]; n = struct.unpack_from('<H', elf, 44)[0]
segs = [struct.unpack_from('<8I', elf, ph + i * 32) for i in range(n)]
def word(va):
    for t, off, v, p, fs, ms, fl, al in segs:
        if t == 1 and v <= va < v + fs: return struct.unpack_from('<I', elf, off + va - v)[0]
ok = sum(1 for g in r['guards'] if word(g[0]) is not None and (word(g[0]) & g[2]) == (g[1] & g[2]))
print('guards', len(r['guards']), 'matching stock words at that VA:', ok)
gva = {g[0] for g in r['guards']}
port = open(r'C:\Users\david\Documents\development\pad-triage\work\tickets\PAD-1572\tools\spike2_emu\modes\sdk\ports\godzilla_le-1.16.port').read()
for m in re.finditer(r'^site\s+(\S+)\s+0x([0-9a-f]+)', port, re.M):
    a = int(m.group(2), 16)
    hit = sorted(x for x in gva if a <= x < a + 16)
    if hit: print('site %-20s 0x%08x guards at %s' % (m.group(1), a, ' '.join('0x%x' % h for h in hit)))
