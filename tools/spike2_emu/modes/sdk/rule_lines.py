"""rule_lines.py <game program> <port> [--dry] - write the port's RULE block lines (PAD-398): one `site
block_rule_<n>` per rule of the game's that reads shots, so that while a mode of ours runs none of them sees a
shot - nothing of the game's lights, locks, counts or awards - unless the mode keeps it (pm_block_rules_keep).

David, 2026-10-05: "when our custom modes start, we should ONLY be in those modes unless explicitly noted."

The rules are read by the app's own scanner (pinball_decryptor/plugins/stern/game_mode_blocks.py read_rules,
which a drafted port's block section uses too). Replaces every block_rule_* line (and PAD-363's hand-made Saucer
Attack section) and keeps the rest of the port. Run under the repo root's Python (it imports the app)."""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
from pinball_decryptor.plugins.stern import game_mode_blocks as G  # noqa: E402

OLD = re.compile(r"^(site block_rule_\d+|value block_rule_(lo|hi)_\d+|text block_rule_name_\d+)\b")
OLD_COMMENT = ("# PAD-398: every rule of the game's that reads shots",
               "# PAD-363 (David's Premium, 2026-10-04: \"overlapping text for saucer")


def rewrite(port_path, rules):
    with open(port_path, "rb") as f:
        raw = f.read()
    crlf = b"\r\n" in raw
    lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
    keep, at, skipping = [], None, False
    for ln in lines:
        if ln.startswith(OLD_COMMENT):
            skipping = True
            at = len(keep) if at is None else at
            continue
        if skipping and ln.startswith("#"):
            continue
        skipping = False
        if OLD.match(ln):
            at = len(keep) if at is None else at
            continue
        keep.append(ln)
    if at is None:
        at = len(keep)
        while at and not keep[at - 1].strip():
            at -= 1
    text = "\n".join(keep[:at] + G.rule_lines(rules) + keep[at:])
    with open(port_path, "wb") as f:
        f.write((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("program")
    ap.add_argument("port")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    with open(a.program, "rb") as f:
        rules = G.read_rules(f.read())
    for ln in G.rule_lines(rules):
        print(ln)
    if not a.dry:
        rewrite(a.port, rules)
        print("wrote %d rule(s) into %s" % (len(rules), a.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
