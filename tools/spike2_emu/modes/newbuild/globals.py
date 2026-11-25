"""globals.py <earlier port> <new port> [name ...] - an earlier build's `data` lines (globals: the game's static objects,
typeinfo records) placed in a new build by the shift of their neighbours (PAD-1555).

A version bump moves a stretch of the game's data and bss by one offset. For a global the earlier port names and the
new one lacks, the two globals both ports place on either side of it (by address in the earlier build) give the
shift; when they agree, the global is placed at its earlier address plus that shift. Measured on the November 2026
builds: every global both ports place whose two neighbours agree was predicted exactly (69 of 69). Where the
neighbours disagree (a stretch grew between them) nothing is placed. Prints `data` lines, or `# <name>: why not`."""
import re
import sys


def data_lines(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^data\s+(\S+)\s+(0x[0-9a-f]+)(.*)$", line)
        if m and m.group(1) not in out:
            out[m.group(1)] = (int(m.group(2), 16), m.group(3))
    return out


def place(old, new, names):
    both = sorted((old[k][0], new[k][0]) for k in new if k in old and old[k][0] >= 0x10000)
    out = []
    for name in names:
        if name not in old:
            out.append("# %s: the earlier port has no such global" % name)
            continue
        a, rest = old[name]
        lo = max((x for x in both if x[0] <= a), default=None)
        hi = min((x for x in both if x[0] >= a), default=None)
        if not lo or not hi:
            out.append("# %s: no global placed on both sides of it" % name)
            continue
        d1, d2 = lo[1] - lo[0], hi[1] - hi[0]
        if d1 != d2:
            out.append("# %s: its neighbours moved by %+#x and %+#x - not placed" % (name, d1, d2))
            continue
        out.append("data %-22s 0x%08x%s   # PAD-1555: the earlier build's + %#x, its neighbours' shift (globals.py)"
                   % (name, a + d1, rest.split("#")[0].rstrip() if "#" not in rest else "  #" + rest.split("#", 1)[1].rstrip(), d1))
    return out


def main():
    rd = lambda p: open(p, encoding="utf-8").read()
    old, new = data_lines(rd(sys.argv[1])), data_lines(rd(sys.argv[2]))
    names = sys.argv[3:] or [k for k in old if k not in new]
    for line in place(old, new, names):
        print(line)


if __name__ == "__main__":
    main()
