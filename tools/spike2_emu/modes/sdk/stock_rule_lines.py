"""stock_rule_lines.py <game program> <port> [--dry] - write the port's `rule` lines (PAD-699): one per mode of the
game's own (its battles, its multiballs), `rule <id> <vtable pointer> <name>`, read off the game program by the app's
scanner (pinball_decryptor/plugins/stern/game_mode_blocks.py stock_rule_lines), so a counts-as or instead-of row
(stock.cfg; the Modes tab's Shots) may name any of them.

Replaces every `rule` line (the new block goes where the first one was, or at the end) and keeps the rest of the
port. A derived port gets the same lines from portgen.block_section. Run under the repo root's Python (it imports
the app)."""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
from pinball_decryptor.plugins.stern import game_mode_blocks as G  # noqa: E402

COMMENT = "# PAD-699: the game's own modes a counts-as"


def rewrite(port_path, lines):
    with open(port_path, "rb") as f:
        raw = f.read()
    crlf = b"\r\n" in raw
    old = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
    keep, at, skip = [], None, False
    for ln in old:
        if ln.startswith(COMMENT):
            skip = True
            at = len(keep) if at is None else at
            continue
        if skip and ln.startswith("# from the game program"):
            continue
        skip = False
        if ln.startswith("rule "):
            at = len(keep) if at is None else at
            continue
        keep.append(ln)
    if at is None:
        at = len(keep)
        while at and not keep[at - 1].strip():
            at -= 1
    text = "\n".join(keep[:at] + lines + keep[at:])
    with open(port_path, "wb") as f:
        f.write((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("program")
    ap.add_argument("port")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    with open(a.program, "rb") as f:
        lines = G.stock_rule_lines(G.read_modes(f.read()))
    print("\n".join(lines))
    if not a.dry:
        rewrite(a.port, lines)
        print("wrote %d rule line(s) into %s" % (len(lines) - 2, a.port))


if __name__ == "__main__":
    main()
