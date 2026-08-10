#!/usr/bin/env python3
"""trough.py - which switches are the ball trough, in trough ORDER, and what
the balls are doing.

THE ORDER IS THE WHOLE POINT, not the count. Item 20 was a wrong-end bug:
plunge.py opened TROUGH 1, the eject end, where a ball leaving can only ever
open TROUGH 6 at the far end - and it took reading the guest's own `[sw]`
stream to see it. A display that says "5 balls" would have shown that fault as
a perfectly healthy 5. Six positions drawn in trough order shows it by eye, in
one glance, which is why David asked for "visual indication of trough switches
being correctly closed or open" rather than for a number.

WHICH SWITCHES, AND WHY BY NAME. The ids are per title and nothing else about
them is stable: Godzilla's trough is 71..66, Jaws's is 65..60, John Wick's is
75..70. The NAME is the portable identifier - `TROUGH 1` .. `TROUGH 6`, case
varying by title - and that is already this rig's rule, not a new one:
`padglhost.c` resolves its window-open trough latch exactly this way
(binds_resolve(), the `TROUGH %d` loop), and plunge.py was unblocked by the
same change. The match here is deliberately IDENTICAL to padglhost's - upper
case, trailing blanks stripped, compared whole - so the thing that latches the
balls on and the thing that draws them cannot disagree about which switches
they are.

TROUGH 1 IS THE EJECT END. Item 20 measured it: 71 TROUGH 1 sits at x=254
beside TROUGH JAM, balls are taken from the FAR end, and a returning ball
fills the far end first. So position 1 is where the next ball leaves from and
position 6 is where a drained ball arrives, and a drawing that puts 1 on the
left reads left-to-right in the direction the balls travel.

THE FALLBACK IS LABELLED, NEVER SILENT. On the titles whose switch names all
come back `?` (item 29 - Led Zeppelin, Elvira) there is no name to match, and
those are exactly the titles where a human most needs to see the trough,
because nothing else on screen says why the game cannot find its balls. Every
switch list on this disk - godzilla_pro, jaws_le, john_wick_le, star_wars_le,
turtles_pro, led_zeppelin_le, elvira3 - carries the trough at node 8, bits
32..37, with bit 37 = TROUGH 1; the five that have names confirm the mapping
and the two that do not have the same rows. That is a strong shape and still a
GUESS, so find() says which of the two answers it gave and the caller is
expected to show it.
"""
import re

#: `TROUGH 1` .. `TROUGH N`, and nothing else. Anchored on purpose: `TROUGH
#: JAM` is a real switch on every title here and is NOT a ball position - it
#: is the opto that says two balls are stuck in the eject - so a loose
#: substring match would draw seven positions and call one of them a ball.
NAME_RE = re.compile(r"^TROUGH\s+(\d+)$")

#: The shape every switch list on this disk agrees on, used only when the
#: names are `?`. Position 1 (the eject end) is the HIGHEST bit; see the
#: module docstring for the five titles that confirm it by name.
FALLBACK_NODE = 8
FALLBACK_BITS = (37, 36, 35, 34, 33, 32)     # positions 1..6

#: How many positions a trough is expected to have. Not a limit on what find()
#: will return from names - a title with eight would give eight - but it is
#: what the fallback shape covers.
POSITIONS = 6


def _norm(name):
    """padglhost's normalisation, so the two agree switch for switch."""
    return (name or "").upper().strip()


def load_list(path):
    """switch_list.txt -> rows find() understands: id, num, node, bit, name.

    THE PARSE LIVES HERE so the window and the command-line cross-check read
    the file the same way. playfield.py cannot be imported by anything running
    inside WSL - it imports tkinter, which this WSL has none of - so without a
    module like this one, swshow.py would need a second copy of the parser and
    the two would drift, which is the failure this rig has already had twice.
    """
    out = []
    try:
        f = open(path)
    except OSError:
        return out
    with f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 5:
                continue
            try:
                out.append(dict(id=int(p[0]), num=int(p[1]), node=int(p[2]),
                                bit=int(p[3]), name=" ".join(p[4:])))
            except ValueError:
                continue
    return out


def find(rows):
    """(positions, how) for a switch table.

    `rows` is what playfield.py's load_switch_list()/load_switches() return -
    dicts with at least id, node, bit and name. `positions` is a list of
    dicts in TROUGH ORDER, position 1 (the eject end) first:

        [{"pos": 1, "id": 71, "name": "Trough 1"}, ...]

    `how` is "named" when the names carried it, "assumed" when the node 8 /
    bit 37..32 shape did, and None when neither could - an empty list then,
    and the caller draws no trough rather than a made-up one.
    """
    by_pos = {}
    for r in rows or ():
        m = NAME_RE.match(_norm(r.get("name")))
        if m:
            by_pos.setdefault(int(m.group(1)), r)
    if by_pos:
        return ([dict(pos=p, id=by_pos[p]["id"], name=by_pos[p].get("name"))
                 for p in sorted(by_pos)], "named")

    # No names. Take the shape only if EVERY position of it is present: a
    # partial match means this is not the layout being guessed at, and five
    # circles out of six would be a quieter lie than none at all.
    at = {}
    for r in rows or ():
        if r.get("node") == FALLBACK_NODE:
            at[r.get("bit")] = r
    if all(b in at for b in FALLBACK_BITS):
        return ([dict(pos=i + 1, id=at[b]["id"], name=at[b].get("name"))
                 for i, b in enumerate(FALLBACK_BITS)], "assumed")
    return ([], None)


def closed(mrg, positions):
    """[bool] per position - True where the GAME is being handed a made switch.

    `mrg` is the merged array (padsw.py's OFF_MRG region), which is what the
    game sees; reading the keyboard's or the scripts' half would answer a
    question about one writer instead of about the machine. A short or absent
    array reads as all-open rather than raising, because this runs in a draw
    loop against a file on the other side of a VM boundary.
    """
    out = []
    for P in positions:
        i = P["id"]
        out.append(bool(mrg[i]) if mrg is not None and 0 <= i < len(mrg)
                   else False)
    return out


class Balls:
    """How many balls are in the trough, and how many are therefore in play.

    THE COMPLEMENT IS LEARNED, AND THAT IS THE HONEST FORM. Nothing on the
    wire says how many balls this machine was built with - the game knows, in
    an adjustment this rig does not read - so "in play" cannot be read
    directly from anything. What CAN be observed is the most balls ever seen
    home at once, and a machine at rest has all of them home: the window
    normally opens during attract, padglhost latches the trough full at window
    open, and the high-water mark is right from the first reading.

    So `in_play` is a DERIVED number and it is allowed to be unknown. Opening
    the window mid-multiball starts the complement low and it corrects itself
    the moment the balls drain; until something has been seen in the trough at
    all, `total` is None and the caller shows the positions without a count
    rather than showing a confident zero.
    """

    def __init__(self):
        self.total = None        # complement: most balls seen home at once
        self.slots = 0           # how many POSITIONS there are, which is a fact
        self.in_trough = 0
        self.in_play = None

    def update(self, flags):
        """Take a fresh [bool] per position; returns (in_trough, in_play)."""
        self.slots = len(flags)
        self.in_trough = sum(1 for f in flags if f)
        if self.in_trough:
            self.total = max(self.total or 0, self.in_trough)
        self.in_play = (None if self.total is None
                        else max(0, self.total - self.in_trough))
        return self.in_trough, self.in_play

    def text(self):
        """The one-line summary for a status bar.

        THE DENOMINATOR IS THE NUMBER OF POSITIONS, NOT THE COMPLEMENT, and
        the difference matters when the two disagree. A window opened
        mid-multiball has only ever seen four balls home, so a complement
        denominator printed "trough 4/4" beside a panel visibly showing two
        EMPTY positions (offline check, 2026-08-10). The position count is a
        fact about the machine; the complement is learned, and it is only
        allowed to decide the derived number it is needed for.
        """
        if self.total is None:
            return "trough 0/%d   no balls seen yet" % self.slots
        return ("trough %d/%d   %s in play"
                % (self.in_trough, self.slots,
                   "?" if self.in_play is None else self.in_play))
