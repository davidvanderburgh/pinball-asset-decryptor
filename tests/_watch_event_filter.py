"""The real [event] awk program out of watch.sh, for the tests that run it.

ONE COPY, because the second one is what burned v0.225.1 (PAD-186,
2026-09-20). test_spike2_picture_oracle.py and test_spike2_window_position.py
each lifted the program out of watch.sh by scanning for a line that ended in
the literal ``| awk '``. PAD-186 made that line ``| $AWK '`` - the variable
picks ``awk -W interactive`` on mawk, whose input buffering held the live
feed back by minutes - and both scrapers raised a bare StopIteration before a
single assertion ran, on the ubuntu and macOS runners, a minute after the
merge landed on main. The awk change was right; the anchor was an unwritten
contract with watch.sh that lived in two places and named itself in neither.

So: both spellings are accepted, a missing anchor fails with a sentence that
says what moved, and `test_watch_sh_keeps_the_event_filter_anchor` in the
picture-oracle tests pins the contract so the next rename breaks ONE test
with a message instead of three with a traceback.
"""
import os

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

#: The line the awk program hangs off, as watch.sh spells it. `awk` for the
#: plain pipeline; `$AWK` since PAD-186's mawk probe.
ANCHORS = ("| awk '", "| $AWK '")
#: The line that closes the single-quoted program and backgrounds the feed.
CLOSE = "' &"


def anchor_lines(src):
    """Indices of every line that opens the awk program."""
    return [i for i, ln in enumerate(src.split("\n"))
            if ln.rstrip().endswith(ANCHORS)]


def event_filter(src=None):
    """The awk program's text, from `src` or from the rig's watch.sh."""
    if src is None:
        with open(os.path.join(RIG, "watch.sh"), encoding="utf-8",
                  errors="replace") as fh:
            src = fh.read()
    lines = src.split("\n")
    starts = anchor_lines(src)
    assert starts, ("watch.sh no longer has a line ending in %s - the [event] "
                    "feed's awk was renamed or restructured, and this scraper "
                    "is a contract with that line" % " or ".join(map(repr, ANCHORS)))
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == CLOSE), None)
    assert end is not None, ("watch.sh's awk program is not closed by a %r "
                             "line after line %d" % (CLOSE, start + 1))
    return "\n".join(lines[start + 1:end])
