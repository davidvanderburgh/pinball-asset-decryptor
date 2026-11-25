"""showmatch.py <earlier program> <earlier port> <new program> <new port> [N ...] - the game's own light shows
(`site show_<N>`) an earlier build's port names, found in a new build by their whole bodies (PAD-1555).

port_tool.py places a show by the shape of its first instructions and by its callers; many of a title's shows open
alike (King Kong's "Wide red and white fade" and "Wide blue and white fade": push, two calls, the same moves) and
have no caller of their own (the process registry starts them), so it leaves them out. Here every function of the new
program that opens with the same two calls as the earlier show (each call's target mapped through the earlier and
new ports' placed sites, or else the function the earlier show calls there) is compared with the earlier show's whole
body - branch targets and literal-pool loads left out, every immediate (colours, times, lamp counts) kept. A show is
placed when exactly one function matches it whole, or one is the clear best (FUZZY alike, MARGIN ahead of the
next), and no other show claims that function. Prints `site` lines."""
import difflib
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
LIMIT = 400
#: a body that changed a little: at least this alike, and this far ahead of the next candidate
FUZZY = 0.9
MARGIN = 0.05


def body(md, elf, va):
    """Normalised instructions of the function at va, up to its last unconditional return."""
    out = []
    code = elf.b[elf.off(va):elf.off(va) + 4 * LIMIT]
    for ins in md.disasm(code, va):
        m, ops = ins.mnemonic, ins.op_str
        if m.startswith("b") and m not in ("bic", "bics", "bfi", "bfc") or "[pc" in ops:
            ops = re.sub(r"#0x[0-9a-f]+|#-?\d+", "#X", ops)
        out.append(m + " " + ops)
        if (m == "pop" and "pc" in ops) or (m == "bx" and ops == "lr"):
            if len(out) > 8:
                break
    return out


def data_sig(md, elf, va):
    """What the function's literal-pool loads point at: 64 words from each, zero or not (lamp ids move between builds,
    which of a table's places are filled does not - King Kong's red and its blue fade differ only there)."""
    out = []
    code = elf.b[elf.off(va):elf.off(va) + 4 * LIMIT]
    for ins in md.disasm(code, va):
        from capstone import arm as A
        if ins.mnemonic == "ldr" and len(ins.operands) == 2 and ins.operands[1].type == A.ARM_OP_MEM \
                and ins.operands[1].mem.base == A.ARM_REG_PC:              # ldr rX, [pc, #imm]
            ptr = elf.word(ins.address + 8 + ins.operands[1].mem.disp)
            o = elf.off(ptr) if ptr else None
            if o is not None:
                out += [int(elf.word(ptr + 4 * k) != 0) for k in range(64)]
        if (ins.mnemonic == "pop" and "pc" in ins.op_str) and len(out) > 0:
            break
    return out


def agree(a, b):
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] == b[i]) / n if n else 0.0


def calls(md, elf, va, n=8):
    code = elf.b[elf.off(va):elf.off(va) + 4 * n]
    return [i.operands[0].imm for i in md.disasm(code, va) if i.mnemonic == "bl"]


def sites(text):
    return {m.group(1): int(m.group(2), 16) for m in re.finditer(r"^site (\S+)\s+(0x[0-9a-f]+)", text, re.M)}


def main():
    sys.path.insert(0, REPO)
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    from pinball_decryptor.plugins.stern import portgen
    old_elf, old_port, new_elf, new_port = sys.argv[1:5]
    want = [int(x) for x in sys.argv[5:]]
    oe, ne = portgen.Elf(old_elf), portgen.Elf(new_elf)
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.detail = True
    ot, nt = open(old_port, encoding="utf-8").read(), open(new_port, encoding="utf-8").read()
    os_, ns = sites(ot), sites(nt)
    by_old = {v: ns[k] for k, v in os_.items() if k in ns}      # earlier address -> new, through both ports' sites
    # every function start in the new program (a push {...lr})
    starts = [ne.tva + 4 * i for i, w in enumerate(ne.words) if (w & 0xffff4000) == 0xe92d4000]
    found = {}
    for n in want or sorted(int(k[5:]) for k in os_ if re.fullmatch(r"show_\d+", k)):
        va = os_.get("show_%d" % n)
        if va is None:
            continue
        ob = body(md, oe, va)
        oc = calls(md, oe, va)
        scored = []
        for s in starts:
            if ne.word(s) != oe.word(va):
                continue
            nc = calls(md, ne, s)
            if len(nc) < len(oc) or any(by_old.get(a) not in (None, b) for a, b in zip(oc, nc)):
                continue
            scored.append((difflib.SequenceMatcher(None, ob, body(md, ne, s), autojunk=False).ratio(), s))
        scored.sort(reverse=True)
        exact = [s for r, s in scored if r == 1.0]
        tied = [s for r, s in scored if scored and r >= max(FUZZY - 0.05, 0.8) and r >= scored[0][0] - 0.01]
        if len(exact) > 1 or (not exact and len(tied) > 1):
            # alike in code: what their tables hold decides (FUZZY - 0.05: a short show's body is a few words)
            os_sig = data_sig(md, oe, va)
            by = sorted(((agree(os_sig, data_sig(md, ne, s)), s) for s in (exact or tied)), reverse=True)
            exact = [by[0][1]] if os_sig and by[0][0] >= 0.95 and by[1][0] < by[0][0] else []
            if not exact:
                exact, scored = [], []
        if exact:
            hits = exact
        elif scored and scored[0][0] >= FUZZY and (len(scored) == 1 or scored[1][0] <= scored[0][0] - MARGIN):
            hits = [scored[0][1]]          # the one clear best: a body changed a little between builds
        else:
            hits = []
        found[n] = hits
    claimed = {}
    for n, hits in found.items():
        for h in hits:
            claimed.setdefault(h, []).append(n)
    for n, hits in sorted(found.items()):
        if len(hits) == 1 and len(claimed[hits[0]]) == 1:
            a = hits[0]
            print("site %-16s 0x%08x 0x%08x 0x%08x   # PAD-1555: the earlier build's show_%d by its whole body (showmatch.py)"
                  % ("show_%d" % n, a, ne.word(a), ne.word(a + 4), n))
        else:
            print("# show_%d: %d function(s) match its whole body%s" % (n, len(hits), (" (" + ", ".join("0x%x" % h for h in hits) + ")") if hits else ""))


if __name__ == "__main__":
    main()
