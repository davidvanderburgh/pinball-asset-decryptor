import re, sys, collections
path = sys.argv[1]
fdpath = {}
readbytes = collections.Counter()
readcount = collections.Counter()
op = re.compile(r'open(?:at)?\((?:AT_FDCWD,)?"([^"]+)"[^)]*\)\s*=\s*(\d+)')
rd = re.compile(r'\b(p?read)\((\d+),[^,]+,(\d+)\)\s*=\s*(\d+)')
mm = re.compile(r'mmap2?\([^,]+,(\d+),[^,]+,[^,]+,(\d+),')
mmaps = collections.Counter()
with open(path, 'rb') as fh:
    for raw in fh:
        line = raw.decode('latin1')
        for m in op.finditer(line):
            fdpath[m.group(2)] = m.group(1)
        for m in rd.finditer(line):
            fd = m.group(2); n = int(m.group(4))
            if n > 0:
                readbytes[fdpath.get(fd, 'fd'+fd)] += n
                readcount[fdpath.get(fd, 'fd'+fd)] += 1
        for m in mm.finditer(line):
            sz = int(m.group(1)); fd = m.group(2)
            if fd != '4294967295' and int(fd) >= 0 and sz > 1000000:
                mmaps[(fdpath.get(fd, 'fd'+fd), sz)] += 1
print('=== top files by bytes read ===')
for p, n in readbytes.most_common(20):
    print('%12d  %5d reads  %s' % (n, readcount[p], p))
print()
print('=== large mmaps by fd path ===')
for (p, sz), c in mmaps.most_common(10):
    print('%12d  x%d  %s' % (sz, c, p))
