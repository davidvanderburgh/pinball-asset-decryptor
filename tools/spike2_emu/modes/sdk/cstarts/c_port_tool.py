"""c_port_tool.py [--dry] [key ...] - PAD-363: the block section of the plain-C titles' ports (and JP LE / Rush,
whose start slot the stock scanner misses), from find_c_starts.py's json/<key>.json. Chapter tables read the
game program from PAD_GAME_PROGRAMS/<key>.elf.
A start the finder rejected only because its caller reads a non-zero result as "began" (a song select, a chapter
table) is written too, with `value block_ret_<id> 0`: the runtime refuses it with 0."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
wt = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
dry = "--dry" in sys.argv
keys = [a for a in sys.argv[1:] if not a.startswith("--")]
ELVES = os.environ.get("PAD_GAME_PROGRAMS", os.path.join(HERE, "elves"))
sys.path.insert(0, wt)
sys.path.insert(0, os.path.join(wt, "tools", "spike2_emu", "modes", "sdk"))
from pinball_decryptor.plugins.stern import game_mode_blocks as G   # noqa: E402
import block_tool as BT                                              # noqa: E402

CHAPTERS = {
    "stranger_things_le-1.12": (0x5564c8, 100, ["Where's Barb", "Monster Hunting", "Bullies", "Get Me Out",
                                                "Operation Mirkwood", "Follow the Compass", "Quarter Hunt", "Save Will",
                                                "What Mama Says", "Morse Code", "Lure Dart", "Turn Up the Heat"]),
    "james_bond_le-1.06": (0x62d080, 0x68, ["Dr No's Lair", "Orient Express", "Oddjob Battles Bond", "Cut Bond in Half",
                                            "Mr Osato", "Professor Dent", "Mr Wint & Mr Kidd", "Feeding Frenzy",
                                            "Fiona Volpe", "Under Water Fight", "Training Grounds", "Diamond Death Ray"]),
}
CS = os.path.join(HERE, "json")
PORTS = os.path.join(wt, "tools", "spike2_emu", "modes", "sdk", "ports")
TITLES = keys or sorted(f[:-5] for f in os.listdir(CS) if f.endswith(".json"))
for key in TITLES:
    d = json.load(open(os.path.join(CS, key + ".json")))
    modes, ret0 = [], set()
    for m in d["modes"]:
        w = tuple(int(x, 16) for x in m["words"])
        modes.append(G.GameMode(int(m["id"]), "", m["name"], int(m.get("obj", "0x0"), 16), 0, int(m["start"], 16), w, False))
    used = {m.id for m in modes}
    nxt = max(used | {-1}) + 1
    for r in d.get("rejected", []):
        why = r.get("why", "")
        bl_only = why.startswith("entry not movable: word 2 is bl")       # the runtime relocates it now
        if not ("returns 0" in why or bl_only) or not r.get("start") or not r.get("words"):
            continue
        w = tuple(int(x, 16) for x in r["words"])
        if not G.movable(w) or nxt >= G.MAX_ID:
            continue
        modes.append(G.GameMode(nxt, "", r["name"], 0, 0, int(r["start"], 16), w, False))
        if not bl_only:
            ret0.add(nxt)
        nxt += 1
    # chapter tables whose caller stops cleanly on 0 (the start finder grouped them): a chapter's start is at +0xc
    # of its entry; names in the table's order (Stranger Things: four of its entries carry their chapter's own
    # assets, in that order; James Bond: the same framework, named in the same audit order - inferred)
    if key in CHAPTERS:
        table, stride, names = CHAPTERS[key]
        from pinball_decryptor.plugins.stern import stock_scan as S
        prog = S.Program(open(os.path.join(ELVES, key + ".elf"), "rb").read())
        for i, nm in enumerate(names):
            f = prog.word(table + stride * i + 0xc)
            w = (prog.word(f), prog.word(f + 4))
            if nxt < G.MAX_ID and G.movable(w):
                modes.append(G.GameMode(nxt, "", nm, 0, 0, f, w, False))
                ret0.add(nxt)
                nxt += 1
    modes = [m for m in modes if m.blockable]
    if not modes:
        print("%-28s nothing to name" % key)
        continue
    section = G.port_lines(modes, header=["plain-C / slot-less title: starts found by the start finder (PAD-363, cstarts)"]
                           if d.get("family") == "c" else ["start slot %s (the start finder; the scanner finds none)" % d.get("start_slot")])
    section += ["value block_ret_%-11d 0" % i for i in sorted(ret0)]
    port = os.path.join(PORTS, key + ".port")
    raw = open(port, "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    lines = BT.strip_old(raw.replace("\r\n", "\n").rstrip("\n").split("\n"))
    lines = [ln for ln in lines if not ln.startswith("value block_ret_")]
    while lines and not lines[-1].strip():
        lines.pop()
    out = "\n".join(lines + [""] + section) + "\n"
    print("%-28s %d named (%d refused with 0)" % (key, len(modes), len(ret0)))
    if dry:
        continue
    if crlf:
        out = out.replace("\n", "\r\n")
    open(port, "wb").write(out.encode("utf-8"))
