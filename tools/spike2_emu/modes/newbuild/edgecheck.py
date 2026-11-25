"""edgecheck.py <mode.log> - SWITCH_EDGE_PROVEN's evidence off a checkjob.sh run's log (gamecheck.sh play: `check mark <switch>`
before each press, `check shot 0x<mask>` for each shot the switch drain hands the modes). PAD-1555.

Prints `<n> of <m> switches one shot each on a bit of its own`, then the others (none, or several shots); exit 0 always."""
import re
import sys


def main(path):
    marks, cur = [], None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"check mark (\S+)", line)
        if m:
            cur = [m.group(1), []]
            marks.append(cur)
            continue
        m = re.search(r"check shot (0x[0-9a-f]+) in_game 1", line)
        if m and cur is not None:
            cur[1].append(int(m.group(1), 16))
    one = [(sw, s[0]) for sw, s in marks if len(s) == 1 and bin(s[0]).count("1") == 1]
    bits = {}
    for sw, b in one:
        bits.setdefault(b, set()).add(sw)
    bad = {sw for sw, s in marks if not (len(s) == 1 and bin(s[0]).count("1") == 1 and len(bits[s[0]]) == 1)}
    names = sorted({sw for sw, _s in marks}, key=lambda x: (len(x), x))
    print("%d of %d switches one shot each press, on a bit of its own (%d presses)" % (len(names) - len(bad), len(names),
                                                                                     len(marks)))
    for sw in names:
        if sw in bad:
            print("  %s: %s" % (sw, "; ".join(" ".join(hex(x) for x in s) or "no shot" for n, s in marks if n == sw)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
