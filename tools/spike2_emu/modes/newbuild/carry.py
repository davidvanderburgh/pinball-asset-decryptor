"""carry.py <new port> <transfer> <predecessor port> <new program> [-o OUT] - the same model's earlier port's feature
lines onto a new build's port (PAD-1555).

A new build's port is derived (port_derive) and proven by a build check, but the derivation keeps only what the
framework's references agree on: the feature blocks the earlier port of the same model carries (light shows by number,
the shaker, mini-wizards, challenges, clip seeks, held coils, co-op extras...) are not in it. <transfer> is
`port_tool.py <earlier program> <earlier port> <new program>`: the earlier port re-placed in the new program. Its
placements are only used when they agree with the new port's own on every site both place (`agree` below; a
transfer from the wrong earlier program agreed on 55%).

Every site / data / value / scene / text entry the earlier port has and the new port lacks is taken from the transfer
when the transfer placed it (a site's two words are the new program's own); a value that is an address in the earlier
program is taken only when the transfer moved it. What cannot be carried is listed, never guessed. Entries the new port
holds on purpose stay as they are: its own (shots, lamps, events, callouts, its scanned own_pass list) and a
switch_spawn it left out."""
import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
KINDS = ("site", "data", "value", "scene", "text")
NEVER = ("own_ret_scanned", "own_pass_", "switch_spawn")


def entries(text):
    """{(kind, name): line} for live lines, in order, and each one's section header."""
    out, sect, head = {}, {}, ""
    for line in text.splitlines():
        if line.startswith("# ----"):
            head = line
            continue
        f = line.split()
        if len(f) >= 3 and f[0] in KINDS and not line.startswith("#"):
            k = (f[0], f[1])
            if k not in out:
                out[k], sect[k] = line, head
    return out, sect


def prune(new_text, pred_text):
    """Another title's NOT PLACED notes out of a new build's port (PAD-420's practice): a `# <kind> <name> NOT PLACED`
    note, with its candidate lines, when the same model's earlier port has no such entry at all."""
    import re
    names = {(m.group(1), m.group(2)) for m in re.finditer(r"^#?\s*(site|data|value|scene|text)\s+(\S+)", pred_text, re.M)}
    out, skip, n = [], False, 0
    for line in new_text.splitlines():
        m = re.match(r"^# (site|data|value|scene|text)\s+(\S+)\s+NOT PLACED", line)
        if m and (m.group(1), m.group(2)) not in names:
            skip, n = True, n + 1
            continue
        if skip and line.startswith("#   candidate"):
            continue
        skip = False
        out.append(line)
    return "\n".join(out) + "\n", n


def agree(new, xfer):
    both = [k for k in xfer if k[0] in ("site", "data") and k in new]
    same = [k for k in both if new[k].split()[2] == xfer[k].split()[2]]
    return len(same), len(both)


def carry(new_text, xfer_text, pred_text, elf):
    new, _ = entries(new_text)
    xfer, _ = entries(xfer_text)
    pred, sect = entries(pred_text)
    same, both = agree(new, xfer)
    if both == 0 or same != both:
        raise SystemExit("the transfer agrees with the new port on %d of %d sites - not used" % (same, both))
    carried, missed = {}, []
    for k, line in pred.items():
        if k in new or k[1].startswith(NEVER):
            continue
        x = xfer.get(k)
        if x is None:
            missed.append(k)
            continue
        if k[0] == "value":
            v = line.split()[2]
            try:
                n = int(v, 0)
            except ValueError:
                n = None
            if n is not None and 0x10000 <= n < 0x2000000 and x.split()[2] == v:
                missed.append(k)                    # an address of the earlier program the transfer did not move
                continue
        carried.setdefault(sect[k], []).append(x)
    out = new_text.rstrip("\n").split("\n")
    for head, lines in carried.items():
        out += ["", head or "# ----", "# PAD-1555: carried from the same model's earlier port (newbuild/carry.py: port_tool.py's "
                "re-placing, %d of %d sites agreeing with this port's own)" % (same, both)] + lines
    return "\n".join(out) + "\n", sum(len(v) for v in carried.values()), missed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("new")
    ap.add_argument("xfer")
    ap.add_argument("pred")
    ap.add_argument("program")
    ap.add_argument("-o", "--out")
    ap.add_argument("--prune-only", action="store_true", help="only take other titles' NOT PLACED notes out")
    a = ap.parse_args(argv)
    sys.path.insert(0, REPO)
    from pinball_decryptor.plugins.stern import portgen
    rd = lambda p: open(p, encoding="utf-8").read()
    if a.prune_only:
        text, n = prune(rd(a.new), rd(a.pred))
        with open(a.out or a.new, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("%s: %d notes of other titles' entries taken out" % (os.path.basename(a.new), n))
        return
    text, n, missed = carry(rd(a.new), rd(a.xfer), rd(a.pred), portgen.Elf(a.program))
    with open(a.out or a.new, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("%s: %d carried; not carried (the transfer could not place them): %s"
          % (os.path.basename(a.new), n, " ".join("%s:%s" % k for k in missed) or "none"))


if __name__ == "__main__":
    main()
