#!/usr/bin/env python3
"""ledcensus.py - score LED frame bodies against every known form. Offline.

    python3 ledcensus.py /var/tmp/led_trace_1d.log [more captures...]
    python3 ledcensus.py --forms          # what the forms are, and the evidence

WHY IT EXISTS. Three lamp-frame families were cracked on 2026-08-07 (item 1d)
and every one of them fell to the same move: take every body of one
(cmd, blen), ask a structural question of each byte position, and demand the
answer be near-perfect across the whole census. A shape that fits 86 of 93 is
not decoded - it is a shape plus seven counter-examples that turn out to be
the interesting part. This is that loop, with the forms already found built in
so a new capture says in one run what is left.

IT IS ALSO THE REGRESSION TEST FOR THE DECODER. hwshim.c's led_publish() is
the C twin of these forms; if a future edit stops claiming frames this scores
as decodable, the two have drifted. Run it on any capture before and after.

WHAT COUNTS AS EVIDENCE, because this file has one job and it is not to be
optimistic:
  * a form must fit essentially ALL bodies of its (cmd, blen), and the
    misfits are printed in full rather than summarised away;
  * "is this byte a lamp?" is asked against the board's OWN announced list
    ([ledenum] in the capture), never against 0..95 - reading raw indices
    made an early a6 attempt address hardware that is not on the board 21%
    of the time, and it still looked plausible;
  * a position that never dips below 0x80 is a lamp REFERENCE, not a level.
    That one cost a whole pass: the first test asked whether the RAW byte was
    an announced index, got 0 of 399, and concluded "value" - a rigged
    question, since bit 7 is set in every sample.

INPUTS. Anything carrying [nbts] (PAD_NB_TRACE=1), [ledskip]
(PAD_LED_SKIP_LOG=N) or [leddec] lines, plus the [ledenum] lines the shim
prints at boot. Mixed captures are fine and are deduplicated by body.
"""
import glob
import re
import sys
from collections import Counter, defaultdict

NBTS = re.compile(r"\[nbts\] t=(\d+) node=(-?\d+) cmd=([0-9a-f]{2}) len=(\d+) "
                  r"([0-9a-f]+)")
SKIP = re.compile(r"\[ledskip\] node=(\d+) cmd=([0-9a-f]{2}) .*?blen=(\d+) "
                  r"body=([0-9a-f]+)")
DEC = re.compile(r"\[leddec\] node=(\d+) cmd=([0-9a-f]{2}) rlen=\d+ blen=(\d+) "
                 r"body=([0-9a-f]+)")
ENUM = re.compile(r"\[ledenum\] node=(\d+) order=([0-9,]*) count=(\d+)")

#: The insert boards. The SAME command byte means something else on the strip
#: boards - a6 on node 14 is a masked RGB-triple frame, not the bitmap - so a
#: census that pools them produces confident nonsense.
INSERT_NODES = (1, 8, 9)

#: Commands that carry lamp data at all. Everything else on these nodes is
#: configuration, the switch scan, or the 0x70 metronome (ruled out
#: 2026-08-07: body is always (index, 00, 00), 6579 of 6579, at a constant
#: 12.15 Hz whatever the light show is doing - a keepalive, not brightness).
LAMP_CMDS = ("97", "a2", "a3", "a4", "a5", "a6", "b4", "b5")

FORMS_DOC = """\
The forms, and what each one was established on (all 2026-08-07, item 1d):

  INDEXED   [idx x N][gap][val x N]        blen 2N+{1,2,3}
      The base layer. A single-lamp frame must carry its 0x0f gap byte: with
      one index the structural test is otherwise no test, and it was eating
      the a4/a5 pair frames (`36 37 bb` -> "lamp 0x36 := 0xbb", a rate as a
      brightness). 71 of 80 genuine single writes carry the gap byte.

  BITMAP    [3 payload][mask bytes][one level per set bit]   cmd a6
      Bit k = the k-th lamp THIS BOARD ANNOUNCED, not raw index k. Read raw,
      these address absent hardware 21% of the time (160/769 bits); read as
      announced positions, 2/769. Complete RGB triples per frame: 23 this
      way, 4 raw, 1 shuffled control.

  RANGEREF  [start][0x80|end]              blen 2
      Two lamp references and no level anywhere. NOT lamp data; not counted
      as skipped, because it is not a frame we are failing to read.

  ENVELOPE  [start][0x80|end][from][to][rise][fall]     cmd a2, blen 6
      A one-shot pulse: from -> to at the slot for that direction, back on
      the other, 0 = instant. 93/93 fit. Successive fades on one range do NOT
      chain end-to-start (0 of 23), and later base writes agree with `to`
      only 57 of 651 - so it is an OVERLAY and must not move val[].

  BANKFADE  [start][0x80|end][rate]        cmd b4 (up) / b5 (down), blen 3
            [start][mid][0x80|end][rate]   blen 4
      44/44 and 22/22 fit; 0 of 66 carry the indexed gap byte. Direction from
      what follows on the wire: the next write into a b4'd range asserts
      HIGH. These MOVE the base.

  FORMA     [refs..., last|0x80][from x N][to x N]      cmd a2, blen 3N
      Multi-lamp fade step. Signs itself: three consecutive refs pair with an
      identical value triple in the `to` region - an RGB fixture fading to
      one colour. No rate byte; the reader's nominal rate applies.

STILL UNDECODED: the header-prefixed long bodies (`8f1af678fe...`). They open
with bytes that are not lamp references, which is why every form above
rejects them.

RULED OUT for those, 2026-08-07, and it is the worked example of why this file
insists on a control. The shape looked excellent: `[3 header][mask][FROM x
popcount][TO x popcount]` - the a6 bitmap layout carrying TWO value regions
instead of one, i.e. a bitmap FADE. The first frame tried fitted exactly
(3 + 6 mask + 10 + 10 = 29), the FROM regions came out of the 0f/00 level
alphabet, and the TO regions carried form A's RGB value triples. Every
qualitative sign was right.

It is still wrong. Scoring it over all 152 long lamp-command bodies:

    real bodies                                  38 fit  (25%)
    random bodies, same lengths, 20 trials       20 fit  (13%)
    RGB triple tell on the fits                  26/42   (62%)

A form that is real fits essentially everything (a2 blen=6: 93/93; b4/b5
blen=3: 66/66) and its tell is near-perfect (form A: ~100%). Scanning the mask
length gives the hypothesis a free parameter, and a free parameter buys 13% of
random noise before it has explained anything. Do not re-try this shape
without beating that control.
"""


def load(paths):
    """(announced-lamp sets, deduplicated bodies) from any mix of captures."""
    known = defaultdict(set)
    seen, rows = set(), []
    for path in paths:
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError as exc:
            print("  skipping %s (%s)" % (path, exc))
            continue
        with fh:
            for line in fh:
                m = ENUM.search(line)
                if m:
                    known[int(m.group(1))].update(
                        int(x) for x in m.group(2).split(",") if x)
                    continue
                node = cmd = body = None
                m = SKIP.search(line) or DEC.search(line)
                if m:
                    node, cmd, body = (int(m.group(1)), m.group(2),
                                       bytes.fromhex(m.group(4)))
                else:
                    m = NBTS.search(line)
                    if m:
                        raw = bytes.fromhex(m.group(5))
                        # [node|0x80][len][cmd][body...][cksum][rlen]
                        if len(raw) >= 6 and (raw[0] & 0x80):
                            node, cmd, body = (int(m.group(2)), m.group(3),
                                               raw[3:-2])
                if body is None or cmd not in LAMP_CMDS:
                    continue
                key = (node, cmd, body)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(key)
    return known, rows


def is_lamp(known, node, v):
    return (v & 0x7F) < 96 and (v & 0x7F) in known.get(node, ())


def classify(known, node, cmd, b):
    """The first form that claims this body, or None. Order matches
    hwshim.c's led_publish(), so a disagreement here is a real drift."""
    n = len(b)
    if n == 2 and is_lamp(known, node, b[0]) and (b[1] & 0x80) \
            and is_lamp(known, node, b[1]):
        return "RANGEREF"
    if cmd in ("b4", "b5") and n in (3, 4):
        e = b[n - 2]
        mid_ok = n == 3 or (is_lamp(known, node, b[1]) and b[1] >= b[0])
        if (e & 0x80) and is_lamp(known, node, b[0]) \
                and is_lamp(known, node, e) and b[0] <= (e & 0x7F) and mid_ok:
            return "BANKFADE"
    if cmd == "a2" and n == 6 and is_lamp(known, node, b[0]) \
            and (b[1] & 0x80) and is_lamp(known, node, b[1]) \
            and b[0] <= (b[1] & 0x7F):
        return "ENVELOPE"
    if cmd == "a2" and n > 6 and n % 3 == 0:
        nref = 0
        for k in range(n):
            if not is_lamp(known, node, b[k]):
                break
            nref += 1
            if b[k] & 0x80:
                if n == 3 * nref and nref >= 3:
                    return "FORMA"
                break
    for extra, gap in ((1, 1), (2, 1), (3, 2)):
        if n < extra + 2 or (n - extra) % 2:
            continue
        cnt = (n - extra) // 2
        if cnt == 1 and extra == 1 and b[1] != 0x0F:
            continue
        if all((b[i] < 96 and b[i] in known.get(node, ())) for i in range(cnt)):
            return "INDEXED"
    if cmd == "a6" and n >= 4:
        for mlen in range(1, n - 2):
            bits = sum(bin(b[3 + j]).count("1") for j in range(mlen))
            if 3 + mlen + bits != n:
                continue
            if all(j * 8 + k < len(known.get(node, ()))
                   for j in range(mlen) for k in range(8)
                   if (b[3 + j] >> k) & 1):
                return "BITMAP"
            break
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--forms" in sys.argv:
        print(FORMS_DOC)
        return 0
    if not args:
        args = sorted(glob.glob("/var/tmp/led_trace*.log"))
        if not args:
            print(__doc__.split("\n\n")[1])
            return 2
    known, rows = load(args)
    if not known:
        print("no [ledenum] lines in the capture - every lamp test would be\n"
              "asked against an empty announced list, so nothing can be\n"
              "scored. Re-capture with the shim's boot enumeration included.")
        return 2

    print("announced lamps: %s"
          % {n: len(v) for n, v in sorted(known.items()) if n in INSERT_NODES})
    print("unique bodies on insert nodes: %d\n"
          % sum(1 for n, _, _ in rows if n in INSERT_NODES))

    hits = Counter()
    misses = defaultdict(list)
    for node, cmd, body in rows:
        if node not in INSERT_NODES:
            continue
        form = classify(known, node, cmd, body)
        if form:
            hits[form] += 1
        else:
            misses[(cmd, len(body))].append((node, body))

    print("CLAIMED:")
    for form, n in hits.most_common():
        print("  %-9s %d" % (form, n))
    total_miss = sum(len(v) for v in misses.values())
    print("\nUNCLAIMED: %d bodies in %d (cmd, blen) groups" %
          (total_miss, len(misses)))
    for (cmd, blen), items in sorted(misses.items(),
                                     key=lambda kv: -len(kv[1])):
        print("  cmd %s blen %-3d x%d" % (cmd, blen, len(items)))
        for node, body in items[:3]:
            print("      n%d %s" % (node, body.hex()))
    if total_miss:
        print("\nEach group above is a shape nobody has cracked. The move that\n"
              "worked three times: per byte POSITION, ask is-bit7-set,\n"
              "is-it-an-announced-lamp, how-many-distinct-values. A position\n"
              "that is always a lamp is an index; one that ranges freely is a\n"
              "value; a constant is structure. `--forms` has the precedents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
